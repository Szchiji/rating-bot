import os, re, sqlite3, asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

TOKEN = os.environ['BOT_TOKEN']
OWNER_ID = int(os.environ.get('OWNER_ID', '0'))  # 自动读取环境变量

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)

DB = "ratings.db"

def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS ratings (chat_id INTEGER, username TEXT, rec INTEGER DEFAULT 0, black INTEGER DEFAULT 0, PRIMARY KEY(chat_id, username))''')
    c.execute('''CREATE TABLE IF NOT EXISTS votes (chat_id INTEGER, voter INTEGER, username TEXT, type TEXT, time TIMESTAMP, PRIMARY KEY(chat_id,voter,username,type))''')
    c.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS allowed_chats (chat_id INTEGER PRIMARY KEY)''')
    conn.commit()
    conn.close()

init_db()

def load_admins():
    conn = sqlite3.connect(DB); c = conn.cursor()
    c.execute("SELECT user_id FROM admins")
    return {row[0] for row in c.fetchall()}

def load_groups():
    conn = sqlite3.connect(DB); c = conn.cursor()
    c.execute("SELECT chat_id FROM allowed_chats")
    return {row[0] for row in c.fetchall()}

def save_admin(uid):
    conn = sqlite3.connect(DB); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO admins VALUES (?)", (uid,))
    conn.commit(); conn.close()

def save_group(gid):
    conn = sqlite3.connect(DB); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO allowed_chats VALUES (?)", (gid,))
    conn.commit(); conn.close()

ADMIN_IDS = load_admins()
ALLOWED_CHAT_IDS = load_groups()
if OWNER_ID:
    ADMIN_IDS.add(OWNER_ID)

PATTERN = re.compile(r"@?([\w\u4e00-\u9fa5]{2,32})")

# ==================== 完美显示昵称 ====================
async def get_full_name(username):
    try:
        user = await bot.get_chat(username)
        name = user.full_name
        if user.username:
            name += f" (@{user.username})"
        return name
    except:
        return f"@{username}"

# ==================== 超帅信誉卡 ====================
async def send_card(msg: Message, username: str, r: int, b: int, net: int):
    display = await get_full_name(username)
    medal = "Trophy" if net >= 50 else "1st" if net >= 20 else "2nd" if net >= 10 else "3rd" if net >= 5 else ""
    color = "Green" if net > 5 else "Yellow" if net > 0 else "Red" if net < -5 else "White"
    status = "神级大佬" if net >= 50 else "信誉极好" if net >= 10 else "危险人物" if net <= -10 else "普通用户"
    text = f"{medal}<b>{color} {display}</b>{medal}\n\n推荐 {r}　拉黑 {b}\n净值 <b>{net:+d}</b>　{status}"
    await msg.reply(text, reply_markup=kb(username))

# ==================== 群内功能 ====================
@router.message(F.chat.type.in_({"group", "supergroup"}))
async def group(msg: Message):
    if msg.chat.id not in ALLOWED_CHAT_IDS: return
    if not msg.text or msg.text.startswith('/'): return
    for raw in PATTERN.findall(msg.text)[:3]:
        u = raw.lstrip("@").lower()
        if len(u) < 3 or u.isdigit(): continue
        r, b = get_stats(msg.chat.id, u)
        net = r - b
        await send_card(msg, u, r, b, net)

# ==================== 投票 ====================
@router.callback_query()
async def vote(cb: CallbackQuery):
    if cb.message.chat.id not in ALLOWED_CHAT_IDS:
        await cb.answer("本群未授权", show_alert=True)
        return
    if "_" not in cb.data: return
    typ, u = cb.data.split("_", 1)
    u = u.lower()
    if not can_vote(cb.message.chat.id, cb.from_user.id, u, typ):
        await cb.answer("24h内只能投一次", show_alert=True)
        return
    add_vote(cb.message.chat.id, cb.from_user.id, u, typ)
    r, b = get_stats(cb.message.chat.id, u)
    net = r - b
    await send_card(cb.message, u, r, b, net)
    await cb.answer("已推荐" if typ=="rec" else "已拉黑")

# ==================== /top 排行榜 ====================
@router.message(Command("top"))
async def top(msg: Message):
    if msg.chat.id not in ALLOWED_CHAT_IDS: return
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT username, rec, black, (rec-black) as net FROM ratings WHERE chat_id=? ORDER BY net DESC LIMIT 20", (msg.chat.id,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        await msg.reply("本群暂无评价记录")
        return
    lines = ["<b>   本群信誉排行榜 TOP20   </b>\n"]
    for i, (u, r, b, net) in enumerate(rows, 1):
        medal = "1st" if i==1 else "2nd" if i==2 else "3rd" if i==3 else f"{i}th"
        name = await get_full_name(u)
        lines.append(f"{medal} {name}  +{r} -{b} → <b>{net:+d}</b>")
    await msg.reply("\n".join(lines))

# ==================== 私聊面板 ====================
@router.message(F.chat.type == "private")
async def private_handler(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        await msg.reply("欢迎使用信誉机器人！\n在群里 @ 用户查看信誉\n/top 查看排行榜")
        return

    text = msg.text.strip()
    words = text.split(maxsplit=1)

    if len(words) >= 2:
        cmd, arg = words[0], words[1]
        if cmd == "/add":
            try:
                gid = int(arg)
                ALLOWED_CHAT_IDS.add(gid)
                save_group(gid)
                await msg.reply(f"已永久授权群：{gid}")
            except: await msg.reply("用法：/add -100xxxxxxxxxx")
        elif cmd == "/addadmin":
            try:
                uid = int(arg)
                ADMIN_IDS.add(uid)
                save_admin(uid)
                await msg.reply(f"已成功添加管理员：{uid}")
            except: await msg.reply("用法：/addadmin 123456789")
        elif cmd == "/del":
            try:
                gid = int(arg)
                if gid in ALLOWED_CHAT_IDS:
                    ALLOWED_CHAT_IDS.remove(gid)
                    conn = sqlite3.connect(DB); c = conn.cursor()
                    c.execute("DELETE FROM allowed_chats WHERE chat_id=?", (gid,))
                    conn.commit(); conn.close()
                    await msg.reply(f"已永久删除授权群：{gid}")
            except: await msg.reply("用法：/del -100xxxxxxxxxx")
        elif cmd == "/deladmin":
            try:
                uid = int(arg)
                if uid in ADMIN_IDS:
                    ADMIN_IDS.remove(uid)
                    conn = sqlite3.connect(DB); c = conn.cursor()
                    c.execute("DELETE FROM admins WHERE user_id=?", (uid,))
                    conn.commit(); conn.close()
                    await msg.reply(f"已移除管理员：{uid}")
            except: await msg.reply("用法：/deladmin 123456789")

    elif text == "/admins":
        await msg.reply("<b>当前管理员：</b>\n" + "\n".join(str(x) for x in ADMIN_IDS))
    elif text == "/list":
        await msg.reply("<b>已授权群：</b>\n" + "\n".join(str(x) for x in ALLOWED_CHAT_IDS) if ALLOWED_CHAT_IDS else "暂无")

# ==================== 数据库函数（已修复 f-string） ====================
def can_vote(chat, voter, user, typ):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    cutoff = datetime.now() - timedelta(hours=24)
    c.execute("SELECT 1 FROM votes WHERE chat_id=? AND voter=? AND username=? AND type=? AND time>?", (chat, voter, user.lower(), typ, cutoff))
    res = c.fetchone()
    conn.close()
    return res is None

def add_vote(chat, voter, user, typ):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    user = user.lower()
    col = "rec" if typ == "rec" else "black"
    c.execute(f"INSERT INTO ratings (chat_id,username,{col}) VALUES (?,?,1) ON CONFLICT(chat_id,username) DO UPDATE SET {col}={col}+1", (chat, user))
    c.execute("INSERT OR REPLACE INTO votes VALUES (?,?,?,?,?)", (chat, voter, user, typ, datetime.now()))
    conn.commit()
    conn.close()

def get_stats(chat, user):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT rec,black FROM ratings WHERE chat_id=? AND username=?", (chat, user.lower()))
    row = c.fetchone()
    conn.close()
    return (row[0] if row else 0, row[1] if row else 0)

def kb(user):
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="推荐", callback_data=f"rec_{user}"),
        InlineKeyboardButton(text="拉黑", callback_data=f"black_{user}")
    )
    return b.as_markup()

async def main():
    print("机器人已启动 - 终极完美版")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())