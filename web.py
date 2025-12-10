from flask import Flask, request, session, redirect
import sqlite3
import os

app = Flask(__name__)
# SECRET_KEY 用于 Flask Session 加密
app.secret_key = os.environ.get("SECRET_KEY", "wolfhunter2025_default_key")

OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

# === 数据库路径适配 Railway Volume ===
# 如果 Railway 挂载了 Volume 到 /data 目录，数据会永久保存
DATA_DIR = "/data" if os.path.exists("/data") else "."
DB = os.path.join(DATA_DIR, "ratings.db")

def init_db():
    """初始化数据库，确保所有必要的表都存在。"""
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    # ratings: 信誉积分 | votes: 投票记录 | admins: 管理员 | allowed_chats: 授权群
    c.execute('''CREATE TABLE IF NOT EXISTS ratings (chat_id INTEGER, username TEXT, rec INTEGER DEFAULT 0, black INTEGER DEFAULT 0, PRIMARY KEY(chat_id, username))''')
    c.execute('''CREATE TABLE IF NOT EXISTS votes (chat_id INTEGER, voter INTEGER, username TEXT, type TEXT, time TIMESTAMP, PRIMARY KEY(chat_id,voter,username,type))''')
    c.execute('''CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS allowed_chats (chat_id INTEGER PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS bot_settings (key TEXT PRIMARY KEY, value TEXT)''')
    # banned_users: 用于 Web 后台和 Bot 同步的封禁列表
    c.execute('''CREATE TABLE IF NOT EXISTS banned_users (username TEXT PRIMARY KEY)''') 
    
    c.execute("INSERT OR IGNORE INTO bot_settings VALUES ('welcome', '<b>狼猎信誉系统</b>\\n\\n@用户查看信誉\\n推荐+1 拉黑-1\\n24h内同人只能投一次')")
    conn.commit()
    conn.close()

# 启动时检查数据库
init_db()

# --- 路由定义 ---
@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        # 简单登录验证
        if request.form.get("id") == str(OWNER_ID):
            session["ok"] = True
            return redirect("/")
    
    if session.get("ok"):
        # 已登录的后台主页
        return f'''
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <div style="font-family:sans-serif; max-width:600px; margin:20px auto; padding:20px;">
        <h1>🐺 狼猎信誉后台</h1>
        <p>主人 {OWNER_ID} | 数据库: {DB}</p>
        <p>
            <a href="/groups">查看授权群</a> | 
            <a href="/admins">查看管理员</a> | 
            <a href="/logout">退出</a>
        </p>
        <hr>
        <h3>功能操作</h3>
        <form action="/add" method="post" style="margin-bottom:15px;">
          <label>➕ 加群授权：</label><br>
          <input name="g" placeholder="-100xxxxxxxxxx" style="padding:5px;">
          <button style="padding:5px;">添加</button>
        </form>
        <form action="/ban" method="post" style="margin-bottom:15px;">
          <label>🚫 封禁用户 (拉黑)：</label><br>
          <input name="u" placeholder="@username" style="padding:5px;">
          <button style="padding:5px;">封禁</button>
        </form>
        <form action="/clear" method="post" style="margin-bottom:15px;">
          <label>🧹 清理数据：</label><br>
          <input name="u" placeholder="@username" style="padding:5px;">
          <button style="padding:5px;">清理记录</button>
        </form>
        </div>
        '''
    # 登录页
    return '''
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <div style="font-family:sans-serif; text-align:center; margin-top:50px;">
    <h2>狼猎信誉后台登录</h2>
    <form method="post">
      <input name="id" type="number" placeholder="输入 Owner ID" style="padding:10px;">
      <button style="padding:10px;">登录</button>
    </form>
    </div>
    '''

@app.route("/groups")
def groups():
    if not session.get("ok"): return redirect("/")
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT chat_id FROM allowed_chats")
    g = [r[0] for r in c.fetchall()]
    conn.close()
    return "<h3>已授权群列表</h3>" + "<br>".join(map(str,g)) or "暂无数据"

@app.route("/admins")
def admins():
    if not session.get("ok"): return redirect("/")
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT user_id FROM admins")
    a = [r[0] for r in c.fetchall()]
    conn.close()
    return "<h3>管理员列表</h3>" + "<br>".join(map(str,a)) or "暂无数据"

@app.route("/add", methods=["POST"])
def add():
    if not session.get("ok"): return "无权限"
    g = request.form["g"]
    if not g: return "请输入群ID"
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    try:
        c.execute("INSERT OR IGNORE INTO allowed_chats VALUES (?)", (g,))
        conn.commit()
    except: pass
    conn.close()
    return redirect("/")

@app.route("/ban", methods=["POST"])
def ban():
    if not session.get("ok"): return "无权限"
    u = request.form["u"].lstrip("@").lower()
    if not u: return "请输入用户名"
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    # 写入封禁表
    c.execute("INSERT OR IGNORE INTO banned_users VALUES (?)", (u,))
    conn.commit()
    conn.close()
    return f"<h3>已将 @{u} 加入黑名单数据库 (Bot 需重启生效)</h3><a href='/'>返回</a>"

@app.route("/clear", methods=["POST"])
def clear():
    if not session.get("ok"): return "无权限"
    u = request.form["u"].lstrip("@").lower()
    if not u: return "请输入用户名"
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    # 全局清理信誉和投票记录
    c.execute("DELETE FROM ratings WHERE username=?", (u,))
    c.execute("DELETE FROM votes WHERE username=?", (u,))
    conn.commit()
    conn.close()
    return f"<h3>已全局清理 @{u} 的信誉记录</h3><a href='/'>返回</a>"

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# 在 Railway 上，Gunicorn 会调用这个 app 实例
if __name__ == "__main__":
    # 仅供本地测试使用
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))