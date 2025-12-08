import asyncio, logging, re, sqlite3, os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.deep_linking import decode_payload

TOKEN = os.environ['BOT_TOKEN']
bot = Bot(token=TOKEN, parse_mode="HTML")
dp = Dispatcher()
router = Router()
dp.include_router(router)

USERNAME_PATTERN = re.compile(r"@?([\w\u4e00-\u9fa5]{2,32})", re.UNICODE)
DB_PATH = "/data/ratings.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS ratings (
                    chat_id INTEGER, username TEXT, rec INTEGER DEFAULT 0, black INTEGER DEFAULT 0,
                    PRIMARY KEY(chat_id, username))''')
    c.execute('''CREATE TABLE IF NOT EXISTS votes (
                    chat_id INTEGER, voter INTEGER, username TEXT, type TEXT, time TIMESTAMP,
                    PRIMARY KEY(chat_id,voter,username,type))''')
    conn.commit()
    conn.close()

init_db()

def can_vote(chat, voter, user, typ):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    cutoff = datetime.now() - timedelta(hours=24)
    c.execute("SELECT 1 FROM votes WHERE chat_id=? AND voter=? AND username=? AND type=? AND time>?", 
              (chat,voter,user,typ,cutoff))
    res = c.fetchone()
    conn.close()
    return res is None

def vote(chat, voter, user, typ):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    user = user.lower()
    col = "rec" if typ=="rec" else "black"
    c.execute(f"INSERT INTO ratings (chat_id,username,{col}) VALUES (?,?,1) "
              f"ON CONFLICT(chat_id,username) DO UPDATE SET {col}={col}+1", (chat,user))
    c.execute("INSERT OR REPLACE INTO votes VALUES (?,?,?,?,?)", 
              (chat,voter,user,typ,datetime.now()))
    conn.commit()
    conn.close()

def get(chat, user):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT rec,black FROM ratings WHERE chat_id=? AND username=?", (chat,user.lower()))
    r = c.fetchone()
    conn.close()
    return (r[0] if r else 0, r[1] if r else 0)

def kb(u):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="推荐", callback_data=f"rec_"+u),
          InlineKeyboardButton(text="拉黑", callback_data"f"black_"+u))
    return b.as_markup()

@router.message(F.chat.type.in_({"group","supergroup"}))
async def g(m: Message):
    if not m.text: return
    for raw in USERNAME_PATTERN.findall(m.text)[:3]:
        u = raw.lstrip("@").lower()
        if len(u)<3 or u.isdigit(): continue
        r,b = get(m.chat.id, u)
        n = r-b
        e = "绿灯" if n>5 else "黄灯" if n>0 else "红灯" if n<-2 else "白灯"
        await m.reply(f"<b>{e} @{u}</b>\n推荐 {r}　拉黑 {b}\n净值 {n:+d}", reply_markup=kb(u))

@router.callback_query()
async def v(c: CallbackQuery):
    if "_" not in c.data: return
    typ, u = c.data.split("_",1)
    u = u.lower()
    if not can_vote(c.message.chat.id, c.from_user.id, u, typ):
        return await c.answer("24h内只能投一次", show_alert=True)
    vote(c.message.chat.id, c.from_user.id, u, typ)
    r,b = get(c.message.chat.id, u)
    n = r-b
    e = "绿灯" if n>5 else "黄灯" if n>0 else "红灯" if n<-2 else "白灯"
    await c.message.edit_text(f"<b>{e} @{u}</b>\n推荐 {r}　拉黑 {b}\n净值 {n:+d}", reply_markup=kb(u))
    await c.answer("成功" if typ=="rec" else "已拉黑")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
