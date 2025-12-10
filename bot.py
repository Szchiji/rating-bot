import os
import re
import sqlite3
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

# 自动读取环境变量（永不改代码）
TOKEN = os.environ['BOT_TOKEN']
OWNER_ID = int(os.environ.get('OWNER_ID', '0'))

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)

DB = "ratings.db"

# ==================== 初始化数据库 ====================
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS ratings (
                    chat_id INTEGER, username TEXT,
                    rec INTEGER DEFAULT 0, black INTEGER DEFAULT 0,
                    PRIMARY KEY(chat_id, username))''')
    c.execute('''CREATE TABLE IF NOT EXISTS votes (
                    chat_id INTEGER, voter INTEGER, username TEXT, type TEXT, time TIMESTAMP,
                    PRIMARY KEY(chat_id,voter,username,type))''')
    c.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS allowed_chats (chat_id INTEGER PRIMARY KEY)''')
    conn.commit()
    conn.close()

init_db()

# ==================== 永久保存管理员 + 授权群 ====================
def load_admins():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT user_id FROM admins")
    admins = {row[0] for row in c.fetchall()}
    conn.close()
    return admins

def load_groups():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT chat_id FROM allowed_chats")
    groups = {row[0] for row in c.fetchall()}
    conn.close()
    return groups

def save_admin(uid):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO admins VALUES (?)", (uid,))
    conn.commit()
    conn.close()

def save_group(gid):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO allowed_chats VALUES (?)", (gid,))
    conn.commit()
    conn.close()

# 启动时加载（关键！重启不丢）
ADMIN_IDS = load_admins()
ALLOWED_CHAT_IDS = load_groups()
if OWNER_ID and OWNER_ID != 0:
    ADMIN_IDS.add(OWNER_ID)
    save_admin(OWNER_ID)  # 确保你永远在数据库里

PATTERN = re.compile(r"@?([\w\u4e00-\u9fa5]{2,32})")

# ==================== 防刷屏：只保留最新一条 ====================
LAST_CARD_MSG_ID = {}   # {chat_id: message_id}
LAST_TOP_MSG_ID = {}    # {chat_id: message_id}

async def delete_old(chat_id: int, msg_dict: dict):
    if chat_id in msg_dict:
        try:
            await bot.delete_message(chat_id, msg_dict[chat_id])
        except:
            pass
        del msg_dict[chat_id]

# ==================== 信誉卡（显示用户名 + 投票者ID） ====================
async def send_card(chat_id: int, username: str, r: int, b: int, net: int, voter_id: int):
    await delete_old(chat_id, LAST_CARD_MSG_ID)
    
    text = f"<b>@{username}</b>\n"
    text += f"投票者 ID: <code>{voter_id}</code>\n\n"
    text += f"推荐 {r}　拉黑 {b}\n"
    text += f"净值 <b>{net:+d}</b>"
    
    sent = await bot.send_message(chat_id, text, reply_markup=kb(username))
    LAST_CARD_MSG_ID[chat_id] = sent.message_id

# ==================== 群内 @ 人 ====================
@router.message(F.chat.type.in_({"group", "supergroup"}))
async def group(msg: Message):
    if msg.chat.id not in ALLOWED_CHAT_IDS:
        return
    if not msg.text or msg.text.startswith('/'):
        return
    for raw in PATTERN.findall(msg.text)[:3]:
        u = raw.lstrip("@").lower()
        if len(u) < 3 or u.isdigit():
            continue
        r, b = get_stats(msg.chat.id, u)
        net = r - b
        await send_card(msg.chat.id, u, r, b, net, msg.from_user.id)

# ==================== 投票（点击后立即刷新） ====================
@router.callback_query()
async def vote(cb: CallbackQuery):
    chat_id = cb.message.chat.id
    if chat_id not in ALLOWED_CHAT_IDS:
        await cb.answer("本群未授权", show_alert=True)
        return
    if "_" not in cb.data:
        return
    typ, u = cb.data.split("_", 1)
    u = u.lower()
    
    if not can_vote(chat_id, cb.from_user.id, u, typ):
        await cb.answer("24h内只能投一次", show_alert=True)
        return
    
    add_vote(chat_id, cb.from_user.id, u, typ)
    r, b = get_stats(chat_id, u)
    net = r - b
    
    await delete_old(chat_id, LAST_CARD_MSG_ID)
    await send_card(chat_id, u, r, b, net, cb.from_user.id)
    await cb.answer("已推荐" if typ == "rec" else "已拉黑")

# ==================== /top 排行榜（100% 出榜 + 自动删旧） ====================
@router.message(Command("top"))
async def top(msg: Message):
    chat_id = msg.chat.id
    if chat_id not in ALLOWED_CHAT_IDS:
        return
    
    await delete_old(chat_id, LAST_TOP_MSG_ID)
    
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT username, rec, black, (rec-black) as net FROM ratings WHERE chat_id=? ORDER BY net DESC, rec DESC LIMIT 20", (chat_id,))
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        sent = await msg.reply("本群暂无评价记录，快去 @ 别人开始吧！")
        LAST_TOP_MSG_ID[chat_id] = sent.message_id
        return
    
    lines = ["<b>  本群信誉排行榜 TOP20  </b>\n"]
    for i, (u, r, b, net) in enumerate(rows, 1):
        medal = "1st" if i == 1 else "2nd" if i == 2 else "3rd" if i == 3 else f"{i:>2}."
        lines.append(f"{medal} @{u}  +{r} -{b} → <b>{net:+d}</b>\n")
    
    sent = await msg.reply("\n".join(lines))
    LAST_TOP_MSG_ID[chat_id] = sent.message_id

# ==================== 私聊面板（含封禁+清理） ====================
@router.message(F.chat.type == "private")
async def private_handler(msg: Message):
    if msg.from_user.id not in ADMIN_IDS:
        await msg.reply("欢迎使用狼猎信誉机器人！\n在群里 @ 用户查看信誉\n发送 /top 查看排行榜")
        return

    text = msg.text.strip()

    if text.startswith("/add "):
        try:
            gid = int(text.split()[1])
            ALLOWED_CHAT_IDS.add(gid)
            save_group(gid)
            await msg.reply(f"已永久授权群：{gid}")
        except:
            await msg.reply("用法：/add -100xxxxxxxxxx")

    elif text.startswith("/addadmin "):
        try:
            uid = int(text.split()[1])
            ADMIN_IDS.add(uid)
            save_admin(uid)
            await msg.reply(f"已成功添加管理员：{uid}")
        except:
            await msg.reply("用法：/addadmin 123456789")

    elif text.startswith("/del "):
        try:
            gid = int(text.split()[1])
            if gid in ALLOWED_CHAT_IDS:
                ALLOWED_CHAT_IDS.remove(gid)
                conn = sqlite3.connect(DB); c = conn.cursor()
                c.execute("DELETE FROM allowed_chats WHERE chat_id=?", (gid,))
                conn.commit(); conn.close()
                await msg.reply(f"已永久删除授权群：{gid}")
        except:
            await msg.reply("用法：/del -100xxxxxxxxxx")

    elif text.startswith("/deladmin "):
        try:
            uid = int(text.split()[1])
            if uid in ADMIN_IDS:
                ADMIN_IDS.remove(uid)
                conn = sqlite3.connect(DB); c = conn.cursor()
                c.execute("DELETE FROM admins WHERE user_id=?", (uid,))
                conn.commit(); conn.close()
                await msg.reply(f"已移除管理员：{uid}")
        except:
            await msg.reply("用法：/deladmin 123456789")

    elif text.startswith("/banuser "):
        username = text.split(maxsplit=1)[1].lstrip("@")
        try:
            user = await bot.get_chat(username)
            await bot.ban_chat_member(msg.chat.id, user.id)
            await msg.reply(f"已永久封禁 @{username}")
        except:
            await msg.reply("封禁失败（用户名错误或不在群）")

    elif text.startswith("/clearuser "):
        username = text.split(maxsplit=1)[1].lstrip("@").lower()
        conn = sqlite3.connect(DB); c = conn.cursor()
        c.execute("DELETE FROM ratings WHERE username=? AND chat_id=?", (username, msg.chat.id))
        c.execute("DELETE FROM votes WHERE username=? AND chat_id=?", (username, msg.chat.id))
        deleted = c.rowcount
        conn.commit(); conn.close()
        await msg.reply(f"已清理 @{username} 的 {deleted} 条记录" if deleted else "未找到记录")

    elif text == "/admins":
        await msg.reply("<b>当前管理员：</b>\n" + "\n".join(str(x) for x in ADMIN_IDS))
    elif text == "/list":
        await msg.reply("<b>已授权群：</b>\n" + "\n".join(str(x) for x in ALLOWED_CHAT_IDS) if ALLOWED_CHAT_IDS else "暂无")
    elif text in ["/start", "/help"]:
        await msg.reply(
            "<b>狼猎信誉机器人控制面板</b>\n\n"
            "群管理：\n/add -100xxx → 添加授权群\n/del -100xxx → 删除授权群\n/list → 查看已授权群\n\n"
            "管理员：\n/addadmin ID → 添加管理员\n/deladmin ID → 删除管理员\n/admins → 查看管理员\n\n"
            "其他：\n/banuser @xxx → 封禁用户\n/clearuser @xxx → 清理用户记录"
        )

# ==================== 数据库函数 ====================
def can_vote(chat, voter, user, typ):
    conn = sqlite3.connect(DB); c = conn.cursor()
    cutoff = datetime.now() - timedelta(hours=24)
    c.execute("SELECT 1 FROM votes WHERE chat_id=? AND voter=? AND username=? AND type=? AND time>?", 
              (chat, voter, user.lower(), typ, cutoff))
    res = c.fetchone(); conn.close()
    return res is None

def add_vote(chat, voter, user, typ):
    conn = sqlite3.connect(DB); c = conn.cursor()
    user = user.lower()
    col = "rec" if typ == "rec" else "black"
    c.execute(f"INSERT INTO ratings (chat_id,username,{col}) VALUES (?,?,1) "
              f"ON CONFLICT(chat_id,username) DO UPDATE SET {col}={col}+1", (chat, user))
    c.execute("INSERT OR REPLACE INTO votes VALUES (?,?,?,?,?)", 
              (chat, voter, user, typ, datetime.now()))
    conn.commit(); conn.close()

def get_stats(chat, user):
    conn = sqlite3.connect(DB); c = conn.cursor()
    c.execute("SELECT rec,black FROM ratings WHERE chat_id=? AND username=?", (chat, user.lower()))
    row = c.fetchone(); conn.close()
    return (row[0] if row else 0, row[1] if row else 0)

def kb(user):
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="推荐", callback_data=f"rec_{user}"),
        InlineKeyboardButton(text="拉黑", callback_data=f"black_{user}")
    )
    return b.as_markup()

# ==================== 启动 ====================
async def main():
    print("狼猎信誉机器人 - 终极完美版已启动")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())