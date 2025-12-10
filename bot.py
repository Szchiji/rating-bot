import os, re, asyncio
from datetime import datetime, timedelta
# 引入 PostgreSQL 驱动
import psycopg2 
import psycopg2.extras 
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

TOKEN = os.environ.get('BOT_TOKEN')
OWNER_ID = int(os.environ.get('OWNER_ID', '0'))

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)

# === PostgreSQL 连接配置 ===
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    if not DATABASE_URL:
        # 如果没有 DATABASE_URL，可能是 Bot 启动早于 DB
        print("Warning: DATABASE_URL is not set. Trying to reconnect later.")
        # 在实际部署中，Railway 会确保这个变量存在
        return None 
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    if not conn: return
    
    c = conn.cursor()
    
    # PostgreSQL 表创建
    c.execute('''CREATE TABLE IF NOT EXISTS ratings (
        chat_id BIGINT NOT NULL, username VARCHAR(32) NOT NULL,
        rec INTEGER DEFAULT 0, black INTEGER DEFAULT 0,
        PRIMARY KEY(chat_id, username)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS votes (
        chat_id BIGINT NOT NULL, voter BIGINT NOT NULL,
        username VARCHAR(32) NOT NULL, type VARCHAR(10) NOT NULL,
        time TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        PRIMARY KEY(chat_id, voter, username, type)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS admins (user_id BIGINT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS allowed_chats (chat_id BIGINT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS bot_settings (key VARCHAR(50) PRIMARY KEY, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS banned_users (username VARCHAR(32) PRIMARY KEY)''')
    
    # PostgreSQL 插入/忽略
    c.execute("INSERT INTO bot_settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING", 
              ('welcome', '<b>狼猎信誉系统</b>\n\n@用户查看信誉\n推荐+1 拉黑-1\n24h内同人只能投一次'))

    conn.commit()
    conn.close()

try:
    init_db()
except:
    print("PostgreSQL Init Failed. Will retry on first use.")

# 辅助函数：加载数据、保存数据 (PostgreSQL 版本)
def load_admins():
    conn = get_db_connection()
    if not conn: return set()
    c = conn.cursor()
    c.execute("SELECT user_id FROM admins"); s = {row[0] for row in c.fetchall()}; conn.close()
    return s

def load_groups():
    conn = get_db_connection()
    if not conn: return set()
    c = conn.cursor()
    c.execute("SELECT chat_id FROM allowed_chats"); s = {row[0] for row in c.fetchall()}; conn.close()
    return s

def save_admin(uid):
    conn = get_db_connection()
    if not conn: return
    c = conn.cursor()
    c.execute("INSERT INTO admins VALUES (%s) ON CONFLICT (user_id) DO NOTHING", (uid,)); conn.commit(); conn.close()

def save_group(gid):
    conn = get_db_connection()
    if not conn: return
    c = conn.cursor()
    c.execute("INSERT INTO allowed_chats VALUES (%s) ON CONFLICT (chat_id) DO NOTHING", (gid,)); conn.commit(); conn.close()
    
ADMIN_IDS = load_admins()
ALLOWED_CHAT_IDS = load_groups()
if OWNER_ID and OWNER_ID not in ADMIN_IDS:
    ADMIN_IDS.add(OWNER_ID); save_admin(OWNER_ID)

PATTERN = re.compile(r"@?([\w\u4e00-\u9fa5]{2,32})")
LAST_CARD_MSG_ID = {}

async def delete_old(chat_id: int):
    if chat_id in LAST_CARD_MSG_ID:
        try: await bot.delete_message(chat_id, LAST_CARD_MSG_ID[chat_id])
        except: pass
        del LAST_CARD_MSG_ID[chat_id]

async def send_card(chat_id: int, username: str, r: int, b: int, net: int, target_id):
    await delete_old(chat_id)
    if net >= 20: color = "Green"; medal = "🏆"
    elif net >= 5: color = "Yellow"; medal = "🥇"
    elif net >= 0: color = "White"; medal = ""
    elif net >= -5: color = "Orange"; medal = ""
    else: color = "Red"; medal = "☠️"
    
    text = f"{medal}<b>{color} @{username}</b>{medal}\n"
    text += f"用户 ID: <code>{target_id}</code>\n\n"
    text += f"推荐 <b>{r}</b>　拉黑 <b>{b}</b>\n净值 <b>{net:+d}</b>"
    
    sent = await bot.send_message(chat_id, text, reply_markup=kb(username))
    LAST_CARD_MSG_ID[chat_id] = sent.message_id

# 数据库核心操作 (PostgreSQL 版本)
def can_vote(chat, voter, user, typ):
    conn = get_db_connection()
    if not conn: return True
    c = conn.cursor()
    cutoff = datetime.now() - timedelta(hours=24)
    # 使用 %s 占位符
    c.execute("SELECT 1 FROM votes WHERE chat_id=%s AND voter=%s AND username=%s AND type=%s AND time>%s", 
              (chat, voter, user.lower(), typ, cutoff))
    res = c.fetchone(); conn.close()
    return res is None

def add_vote(chat, voter, user, typ):
    conn = get_db_connection()
    if not conn: return
    c = conn.cursor()
    user = user.lower()
    col = "rec" if typ == "rec" else "black"
    
    # PostgreSQL UPSERT
    c.execute(f"INSERT INTO ratings (chat_id,username,{col}) VALUES (%s,%s,1) "
              f"ON CONFLICT(chat_id,username) DO UPDATE SET {col}=ratings.{col}+1", (chat, user))
    
    c.execute("INSERT INTO votes (chat_id, voter, username, type, time) VALUES (%s, %s, %s, %s, NOW()) "
              "ON CONFLICT (chat_id, voter, username, type) DO UPDATE SET time = EXCLUDED.time", 
              (chat, voter, user, typ))
    conn.commit(); conn.close()

def get_stats(chat, user):
    conn = get_db_connection()
    if not conn: return (0, 0)
    c = conn.cursor()
    c.execute("SELECT rec,black FROM ratings WHERE chat_id=%s AND username=%s", (chat, user.lower()))
    row = c.fetchone(); conn.close()
    return (row[0] if row else 0, row[1] if row else 0)

def kb(user):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="推荐", callback_data=f"rec_{user}"),
          InlineKeyboardButton(text="拉黑", callback_data=f"black_{user}"))
    return b.as_markup()

# === 群组消息处理：包含黑名单检查 ===
@router.message(F.chat.type.in_({"group", "supergroup"}))
async def group(msg: Message):
    if msg.chat.id not in ALLOWED_CHAT_IDS: return
    if not msg.text or msg.text.startswith('/'): return
    
    # 检查发送者是否在黑名单 (banned_users)
    if msg.from_user.username:
        conn = get_db_connection()
        if conn:
            c = conn.cursor()
            c.execute("SELECT 1 FROM banned_users WHERE username=%s", (msg.from_user.username.lower(),))
            is_banned = c.fetchone(); conn.close()
            if is_banned:
                try:
                    await bot.ban_chat_member(msg.chat.id, msg.from_user.id)
                    await msg.delete()
                    return
                except: pass

    # 提取 @用户名 并发送信誉卡
    for raw in PATTERN.findall(msg.text)[:3]:
        u = raw.lstrip("@").lower()
        if len(u) < 3 or u.isdigit(): continue
        r, b = get_stats(msg.chat.id, u)
        try:
            user_obj = await bot.get_chat(u)
            target_id = user_obj.id
        except: target_id = "未知"
        await send_card(msg.chat.id, u, r, b, r-b, target_id)

@router.callback_query()
async def vote(cb: CallbackQuery):
    chat_id = cb.message.chat.id
    if chat_id not in ALLOWED_CHAT_IDS:
        await cb.answer("本群未授权", show_alert=True); return
    if "_" not in cb.data: return
    typ, u = cb.data.split("_", 1); u = u.lower()
    
    # 检查投票间隔
    if not can_vote(chat_id, cb.from_user.id, u, typ):
        await cb.answer("24h内只能投一次", show_alert=True); return
    
    add_vote(chat_id, cb.from_user.id, u, typ)
    r, b = get_stats(chat_id, u)
    try:
        user_obj = await bot.get_chat(u)
        target_id = user_obj.id
    except: target_id = "未知"
    await delete_old(chat_id)
    await send_card(chat_id, u, r, b, r-b, target_id)
    await cb.answer("投票成功")

# === 私聊管理员面板：全局操作 ===
@router.message(F.chat.type == "private")
async def private_handler(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        conn = get_db_connection()
        if conn:
            c = conn.cursor()
            c.execute("SELECT value FROM bot_settings WHERE key='welcome'")
            row = c.fetchone(); conn.close()
            await msg.reply(row[0] if row else "欢迎使用")
        return

    text = msg.text.strip()
    
    if text.startswith("/add "):
        try:
            gid = int(text.split()[1])
            conn = get_db_connection()
            if conn:
                c = conn.cursor()
                c.execute("INSERT INTO allowed_chats VALUES (%s) ON CONFLICT (chat_id) DO NOTHING", (gid,)); conn.commit(); conn.close()
                ALLOWED_CHAT_IDS.add(gid)
            await msg.reply(f"✅ 已授权: {gid}")
        except: await msg.reply("用法: /add -100xxx")
    
    elif text.startswith("/del "):
        try:
            gid = int(text.split()[1])
            if gid in ALLOWED_CHAT_IDS:
                conn = get_db_connection()
                if conn:
                    c = conn.cursor()
                    c.execute("DELETE FROM allowed_chats WHERE chat_id=%s", (gid,)); conn.commit(); conn.close()
                    ALLOWED_CHAT_IDS.remove(gid)
                await msg.reply(f"🗑️ 已删除: {gid}")
        except: await msg.reply("用法: /del -100xxx")
    
    elif text.startswith("/banuser "):
        try:
            u = text.split(maxsplit=1)[1].lstrip("@").lower()
            conn = get_db_connection()
            if conn:
                c = conn.cursor()
                c.execute("INSERT INTO banned_users VALUES (%s) ON CONFLICT (username) DO NOTHING", (u,)); conn.commit(); conn.close()
            
            count = 0
            try: 
                user_obj = await bot.get_chat(u)
                for gid in ALLOWED_CHAT_IDS:
                    try: await bot.ban_chat_member(gid, user_obj.id); count += 1
                    except: pass
            except: pass
            await msg.reply(f"🚫 已拉黑 @{u} (在 {count} 个群执行踢出)")
        except: await msg.reply("用法: /banuser @name")
    
    elif text.startswith("/clearuser "):
        try:
            u = text.split(maxsplit=1)[1].lstrip("@").lower()
            conn = get_db_connection()
            if conn:
                c = conn.cursor()
                c.execute("DELETE FROM ratings WHERE username=%s", (u,))
                c.execute("DELETE FROM votes WHERE username=%s", (u,)); conn.commit(); conn.close()
            await msg.reply(f"🧹 已清理 @{u} 所有记录")
        except: await msg.reply("用法: /clearuser @name")
        
    elif text.startswith("/setwelcome "):
        new_text = text[len("/setwelcome "):]
        conn = get_db_connection()
        if conn:
            c = conn.cursor()
            c.execute("INSERT INTO bot_settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", 
                      ('welcome', new_text))
            conn.commit(); conn.close()
        await msg.reply(f"📝 欢迎词已更新！\n\n预览：\n{new_text}")

    elif text in ["/start", "/help"]:
        await msg.reply("<b>管理面板:</b>\n/add /del : 授权群管理\n/banuser /clearuser : 用户操作\n/setwelcome : 修改欢迎词")

async def main():
    print("狼猎信誉机器人 - PostgreSQL 版本已启动")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())