import os, re, asyncio
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import * from datetime import datetime, timedelta

TOKEN = os.environ.get('BOT_TOKEN')
OWNER_ID = int(os.environ.get('OWNER_ID', '0'))

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)

PATTERN = re.compile(r"@?([\w\u4e00-\u9fa5]{2,32})")
LAST_CARD_MSG_ID = {}
ALLOWED_CHAT_IDS = set() 
ADMIN_IDS = set()

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
    
    user_id_text = f"<code>{user_id}</code>" if user_id else "获取失败/未知"
    
    text = f"{medal}<b>{color} @{username}</b>{medal}\n"
    text += f"用户 ID: {user_id_text}\n\n"
    text += f"推荐 <b>{r}</b>　拉黑 <b>{b}</b>\n净值 <b>{net:+d}</b>"
    
    sent = await bot.send_message(chat_id, text, reply_markup=kb(username, user_id))
    LAST_CARD_MSG_ID[chat_id] = sent.message_id

def kb(username: str, user_id: int):
    """键盘回调数据改为绑定 user_id"""
    b = InlineKeyboardBuilder()
    if user_id:
        b.row(InlineKeyboardButton(text="推荐", callback_data=f"rec_{user_id}_{username}"),
              InlineKeyboardButton(text="拉黑", callback_data=f"black_{user_id}_{username}"))
    return b.as_markup()

async def load_configs():
    """从数据库加载并缓存允许的群组和管理员"""
    global ALLOWED_CHAT_IDS, ADMIN_IDS
    try:
        chats = await get_allowed_chats()
        ALLOWED_CHAT_IDS = {c['chat_id'] for c in chats}
        
        ADMIN_IDS = await load_admins()
        if OWNER_ID and OWNER_ID not in ADMIN_IDS:
            ADMIN_IDS.add(OWNER_ID)
            await save_admin(OWNER_ID)
            
    except Exception as e:
        print(f"Error loading configs: {e}")

# === 群组消息处理：包含黑名单检查 ===
@router.message(F.chat.type.in_({"group", "supergroup"}))
async def group(msg: Message):
    if msg.chat.id not in ALLOWED_CHAT_IDS: return

    if msg.from_user.id and await is_banned(msg.from_user.id):
        try:
            await bot.ban_chat_member(msg.chat.id, msg.from_user.id)
            await msg.delete()
            return
        except: pass

    target_username = None
    if msg.reply_to_message and msg.reply_to_message.from_user:
        if msg.reply_to_message.from_user.username:
            target_username = msg.reply_to_message.from_user.username.lower()
    
    if not target_username:
        for raw in PATTERN.findall(msg.text or ""):
            username = raw.lstrip("@").lower()
            if len(username) >= 3 and not username.isdigit():
                target_username = username
                break
    
    if not target_username:
        return

    username = target_username
    user_id = await get_user_id_by_username(username)
    r, b, _ = await get_stats(user_id)
    
    await send_card(msg.chat.id, username, user_id, r, b, r-b)

@router.callback_query()
async def vote(cb: CallbackQuery):
    chat_id = cb.message.chat.id
    voter_id = cb.from_user.id
    
    if chat_id not in ALLOWED_CHAT_IDS:
        await cb.answer("本群未授权", show_alert=True); return
        
    if len(cb.data.split('_')) != 3:
        await cb.answer("数据格式错误", show_alert=True); return
        
    typ, uid_str, username = cb.data.split("_")
    user_id = int(uid_str)
    
    if not cb.message.reply_to_message:
        await cb.answer("请回复一条消息进行投票（作为证据）", show_alert=True); return
        
    evidence_msg_id = cb.message.reply_to_message.message_id
    
    settings = await get_chat_settings(chat_id)
    
    # 强制关注/加入检查
    if settings['force_channel_id'] != 0:
        try:
            channel_id = settings['force_channel_id']
            member = await bot.get_chat_member(channel_id, voter_id)
            if member.status not in ['member', 'administrator', 'creator']:
                channel = await bot.get_chat(channel_id)
                invite_link = channel.invite_link or f"https://t.me/{channel.username or channel_id}"
                await cb.answer(f"⚠️ 使用机器人需先加入频道/群组：{invite_link}", show_alert=True)
                return
        except Exception as e: 
            print(f"Force Check Error: {e}"); 

    # 最小入群时间 (精确检查)
    min_days = settings['min_join_days']
    if min_days > 0:
        try:
            member = await bot.get_chat_member(chat_id, voter_id)
            
            if member.status in ['member', 'restricted']: 
                join_date = member.joined_at.replace(tzinfo=None) if member.joined_at else datetime.min
                time_in_group = datetime.now() - join_date
                
                if time_in_group < timedelta(days=min_days):
                    days_in_group = max(0, time_in_group.days)
                    await cb.answer(f"⚠️ 你的入群时间不足 {min_days} 天，无法投票。已入群 {days_in_group} 天。", show_alert=True)
                    return
        except Exception as e: 
            print(f"Join Days Check Error: {e}");
            await cb.answer("入群时间检查失败，请稍后重试。", show_alert=True)
            return

    # 检查 24 小时投票限制
    if not await can_vote(chat_id, voter_id, user_id, typ):
        await cb.answer("24h内只能投一次", show_alert=True); return
    
    # 异步添加投票
    await add_vote(chat_id, voter_id, user_id, typ, username, evidence_msg_id)
    
    # 更新卡片
    r, b, _ = await get_stats(user_id)
    await delete_old(cb.message.chat.id)
    await send_card(cb.message.chat.id, username, user_id, r, b, r-b)
    await cb.answer("投票成功，证据已记录")

# === 私聊管理员面板：设置门槛和强制关注 ===
@router.message(F.chat.type == "private")
async def private_handler(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        welcome_text = await get_welcome_message()
        await msg.reply(welcome_text)
        return

    text = msg.text.strip()
    
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
            parts = text.split()
            _, chat_id, channel_link = parts[0], parts[1], parts[2]
            chat_id = int(chat_id)
            
            channel_id = None
            if channel_link.startswith('@'):
                channel_link = channel_link.lstrip('@')
            
            try:
                chat_info = await bot.get_chat(channel_link)
                channel_id = chat_info.id
            except:
                try: 
                    channel_id = int(channel_link)
                except: pass
            
            if not channel_id:
                 await msg.reply("❌ 无法解析频道/群组 ID 或链接无效。")
                 return
            
            async with db_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO chat_settings (chat_id, force_channel_id) VALUES ($1, $2)
                    ON CONFLICT (chat_id) DO UPDATE SET force_channel_id = $2
                """, chat_id, channel_id)
                
            await msg.reply(f"✅ 群组 {chat_id} 强制关注设置为：频道/群 {channel_id} (<code>{channel_link}</code>)。")
        except: await msg.reply("用法: /setforcechannel [群ID] [频道/群ID/@链接] (例如: /setforcechannel -100xxx @channelname)")
        
    elif text.startswith("/add "):
        try:
            gid = int(text.split()[1])
            await save_group(gid)
            await load_configs() 
            await msg.reply(f"✅ 已授权: {gid}")
        except: await msg.reply("用法: /add -100xxx")
    
    elif text.startswith("/del "):
        try:
            gid = int(text.split()[1])
            await del_group(gid)
            await load_configs() 
            await msg.reply(f"🗑️ 已删除: {gid}")
        except: await msg.reply("用法: /del -100xxx")

    elif text.startswith("/banuser "):
        try:
            u = text.split(maxsplit=1)[1].lstrip("@").lower()
            uid = await get_user_id_by_username(u)
            if not uid: await msg.reply("❌ 找不到用户ID"); return

            await ban_user(uid, u)
            
            count = 0
            for gid in ALLOWED_CHAT_IDS:
                try: await bot.ban_chat_member(gid, uid); count += 1
                except: pass
            
            await msg.reply(f"🚫 已拉黑 @{u} (ID: {uid}) (在 {count} 个群执行踢出)")
        except: await msg.reply("用法: /banuser @name")
    
    elif text.startswith("/clearuser "):
        try:
            u = text.split(maxsplit=1)[1].lstrip("@").lower()
            uid = await get_user_id_by_username(u)
            if not uid: await msg.reply("❌ 找不到用户ID"); return

            await clear_user_data(uid)
            await msg.reply(f"🧹 已清理 @{u} (ID: {uid}) 所有记录")
        except: await msg.reply("用法: /clearuser @name")
        
    elif text.startswith("/setwelcome "):
        new_text = text[len("/setwelcome "):].strip()
        if not new_text:
            await msg.reply("⚠️ 请提供欢迎词内容。")
            return
            
        await set_welcome_message(new_text)
        await msg.reply(f"📝 欢迎词已更新！\n\n预览：\n{new_text}")

    elif text in ["/start", "/help"]:
        await msg.reply("<b>管理面板:</b>\n/add /del : 授权群管理\n/banuser /clearuser : 用户操作\n/setwelcome : 修改欢迎词\n/setjoindays /setforcechannel : 设置群组门槛")

async def main():
    try:
        await init_schema()
        await load_configs() 
        print("狼猎信誉机器人 - 异步 PostgreSQL 高级功能版本已启动") # READY_FLAG
        await dp.start_polling(bot)
    except Exception as e:
        # **重要修改：打印具体错误信息，以便在 start.sh 超时时捕获**
        print(f"BOT FAILED TO START due to database or config error: {e}") 
        # 确保 Bot 进程在失败时退出，避免无限重试
        exit(1)

if __name__ == "__main__":
    asyncio.run(main())