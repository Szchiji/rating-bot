import os, re, asyncio
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import * # <--- 引入所有异步数据库函数

TOKEN = os.environ.get('BOT_TOKEN')
OWNER_ID = int(os.environ.get('OWNER_ID', '0'))

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)

# PATTERN 仍然用于提取用户名
PATTERN = re.compile(r"@?([\w\u4e00-\u9fa5]{2,32})")
LAST_CARD_MSG_ID = {}
ALLOWED_CHAT_IDS = set() # 运行时缓存

# --- 辅助函数 ---

async def get_user_id_by_username(username: str):
    """尝试通过用户名获取用户的 ID"""
    try:
        user_obj = await bot.get_chat(username)
        return user_obj.id
    except: 
        return None
        
async def delete_old(chat_id: int):
    if chat_id in LAST_CARD_MSG_ID:
        try: await bot.delete_message(chat_id, LAST_CARD_MSG_ID[chat_id])
        except: pass
        del LAST_CARD_MSG_ID[chat_id]

async def send_card(chat_id: int, username: str, user_id: int, r: int, b: int, net: int):
    await delete_old(chat_id)
    if net >= 20: color = "Green"; medal = "🏆"
    elif net >= 5: color = "Yellow"; medal = "🥇"
    elif net >= 0: color = "White"; medal = ""
    elif net >= -5: color = "Orange"; medal = ""
    else: color = "Red"; medal = "☠️"
    
    text = f"{medal}<b>{color} @{username}</b>{medal}\n"
    text += f"用户 ID: <code>{user_id}</code>\n\n"
    text += f"推荐 <b>{r}</b>　拉黑 <b>{b}</b>\n净值 <b>{net:+d}</b>"
    
    sent = await bot.send_message(chat_id, text, reply_markup=kb(username, user_id))
    LAST_CARD_MSG_ID[chat_id] = sent.message_id

def kb(username: str, user_id: int):
    """键盘回调数据改为绑定 user_id"""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="推荐", callback_data=f"rec_{user_id}_{username}"),
          InlineKeyboardButton(text="拉黑", callback_data=f"black_{user_id}_{username}"))
    return b.as_markup()

async def load_allowed_chats():
    """从数据库加载并缓存允许的群组 ID"""
    global ALLOWED_CHAT_IDS
    try:
        chats = await get_allowed_chats()
        ALLOWED_CHAT_IDS = {c['chat_id'] for c in chats}
    except Exception as e:
        print(f"Error loading allowed chats: {e}")

# === 群组消息处理：包含黑名单检查 ===
@router.message(F.chat.type.in_({"group", "supergroup"}))
async def group(msg: Message):
    if msg.chat.id not in ALLOWED_CHAT_IDS: return

    # 异步检查发送者是否在黑名单 (使用 user_id)
    if msg.from_user.id and await is_banned(msg.from_user.id):
        try:
            await bot.ban_chat_member(msg.chat.id, msg.from_user.id)
            await msg.delete()
            return
        except: pass

    # 提取 @用户名
    for raw in PATTERN.findall(msg.text)[:3]:
        username = raw.lstrip("@").lower()
        if len(username) < 3 or username.isdigit(): continue
        
        # 核心：通过用户名查找 ID
        user_id = await get_user_id_by_username(username)
        if not user_id: continue 
        
        # 异步获取统计
        r, b, _ = await get_stats(user_id)
        
        await send_card(msg.chat.id, username, user_id, r, b, r-b)

@router.callback_query()
async def vote(cb: CallbackQuery):
    chat_id = cb.message.chat.id
    voter_id = cb.from_user.id
    
    if chat_id not in ALLOWED_CHAT_IDS:
        await cb.answer("本群未授权", show_alert=True); return
        
    # 1. 解析数据
    if len(cb.data.split('_')) != 3:
        await cb.answer("数据格式错误", show_alert=True); return
        
    typ, uid_str, username = cb.data.split("_")
    user_id = int(uid_str)
    
    # 2. 检查回复消息（投票证据绑定）
    if not cb.message.reply_to_message:
        await cb.answer("请回复一条消息进行投票（作为证据）", show_alert=True); return
        
    evidence_msg_id = cb.message.reply_to_message.message_id
    
    # 3. 获取群组设置 (门槛/强制关注)
    settings = await get_chat_settings(chat_id)
    
    # 4. 强制关注/加入检查 (ToS/ToC)
    if settings['force_channel_id'] != 0:
        try:
            channel_id = settings['force_channel_id']
            member = await bot.get_chat_member(channel_id, voter_id)
            if member.status not in ['member', 'administrator', 'creator']:
                channel = await bot.get_chat(channel_id)
                invite_link = channel.invite_link or f"https://t.me/{channel.username}"
                await cb.answer(f"⚠️ 使用机器人需先加入频道/群组：{invite_link}", show_alert=True)
                return
        except: pass # 忽略 Bot 检查错误，避免阻塞

    # 5. 自定义投票门槛检查：最小入群时间 (简易实现)
    min_days = settings['min_join_days']
    if min_days > 0:
        try:
            member = await bot.get_chat_member(chat_id, voter_id)
            # 只有群主/管理员可以忽略门槛 (简化实现)
            if member.status not in ['administrator', 'creator']: 
                 await cb.answer(f"⚠️ 你的入群时间不足 {min_days} 天，无法投票。", show_alert=True)
                 return
        except: pass

    # 6. 检查 24 小时投票限制 (使用 user_id)
    if not await can_vote(chat_id, voter_id, user_id, typ):
        await cb.answer("24h内只能投一次", show_alert=True); return
    
    # 7. 异步添加投票，传入 evidence_msg_id
    await add_vote(chat_id, voter_id, user_id, typ, username, evidence_msg_id)
    
    # 8. 更新卡片
    r, b, _ = await get_stats(user_id)
    await delete_old(cb.message.chat.id)
    await send_card(cb.message.chat.id, username, user_id, r, b, r-b)
    await cb.answer("投票成功，证据已记录")

# === 私聊管理员面板：设置门槛和强制关注 ===
@router.message(F.chat.type == "private")
async def private_handler(msg: Message):
    if msg.from_user.id != OWNER_ID: # 简化：只允许 OWNER_ID
        # ... (获取欢迎词逻辑不变) ...
        return

    text = msg.text.strip()
    
    # --- 新增设置命令 ---
    if text.startswith("/setjoindays "):
        try:
            _, chat_id, days = text.split()
            chat_id, days = int(chat_id), int(days)
            if days < 0: raise ValueError
            
            async with db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO chat_settings (chat_id, min_join_days) VALUES ($1, $2)
                    ON CONFLICT (chat_id) DO UPDATE SET min_join_days = $2
                """, chat_id, days)
                
            await msg.reply(f"✅ 群组 {chat_id} 投票门槛设置为：入群 {days} 天后允许投票。")
        except: await msg.reply("用法: /setjoindays [群ID] [天数] (例如: /setjoindays -100xxx 7)")

    elif text.startswith("/setforcechannel "):
        try:
            _, chat_id, channel_id = text.split()
            chat_id, channel_id = int(chat_id), int(channel_id)
            
            async with db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO chat_settings (chat_id, force_channel_id) VALUES ($1, $2)
                    ON CONFLICT (chat_id) DO UPDATE SET force_channel_id = $2
                """, chat_id, channel_id)
                
            await msg.reply(f"✅ 群组 {chat_id} 强制关注设置为：频道/群 {channel_id}。")
        except: await msg.reply("用法: /setforcechannel [群ID] [频道/群ID] (例如: /setforcechannel -100xxx -100yyy)")

    # --- 其他管理命令 ---
    # ... (其他命令如 /add, /del, /banuser, /clearuser 需调用 database.py 中的异步函数) ...
        
    elif text in ["/start", "/help"]:
        await msg.reply("<b>管理面板:</b>\n/add /del : 授权群管理\n/banuser /clearuser : 用户操作\n/setwelcome : 修改欢迎词\n/setjoindays /setforcechannel : 设置群组门槛")

async def main():
    # 确保异步连接池已初始化
    await init_schema()
    await load_allowed_chats() # 加载允许的群组列表
    print("狼猎信誉机器人 - 异步 PostgreSQL 高级功能版本已启动")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())