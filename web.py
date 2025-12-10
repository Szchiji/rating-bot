from flask import Flask, request, session, redirect
import os
import psycopg2 
import psycopg2.extras 
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "wolfhunter2025_default_key")

OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
DATABASE_URL = os.environ.get('DATABASE_URL')
DB_INITIALIZED = False # <--- 新增全局变量，跟踪初始化状态

def get_db_connection():
    """返回 PostgreSQL 数据库连接对象"""
    if not DATABASE_URL:
        # 如果 DATABASE_URL 未设置，抛出异常，让上层函数捕获
        raise ValueError("DATABASE_URL environment variable is not set!")
    return psycopg2.connect(DATABASE_URL)

def init_db():
    global DB_INITIALIZED
    
    if DB_INITIALIZED:
        return

    conn = get_db_connection()
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
              ('welcome', '<b>狼猎信誉系统</b>\\n\\n@用户查看信誉\\n推荐+1 拉黑-1\\n24h内同人只能投一次'))

    conn.commit()
    conn.close()
    DB_INITIALIZED = True # <--- 成功初始化后设置标记

# --- 路由定义 ---
@app.route("/", methods=["GET", "POST"])
def home():
    # 修复：在请求时检查和初始化 DB
    try:
        init_db()
    except ValueError as e:
        # 数据库 URL 未设置，通常是配置问题
        return f"<h1>配置错误</h1><p>数据库URL未设置: {e}</p>", 500
    except Exception as e:
        # 数据库连接失败（例如 PostgreSQL 未启动或密码错误）
        return f"<h1>数据库连接失败</h1><p>请检查 PostgreSQL 服务状态: {e}</p>", 500

    # 登录逻辑
    if request.method == "POST":
        if request.form.get("id") == str(OWNER_ID):
            session["ok"] = True
            return redirect("/")
    
    if session.get("ok"):
        # 已登录的后台主页
        return f'''
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <div style="font-family:sans-serif; max-width:600px; margin:20px auto; padding:20px;">
        <h1>🐺 狼猎信誉后台</h1>
        <p>主人 {OWNER_ID} | 数据库: PostgreSQL</p>
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

# --- 后续路由函数（/groups, /admins, /add, /ban, /clear, /logout）保持 PostgreSQL 版本的 SQL 逻辑不变 ---

@app.route("/groups")
def groups():
    if not session.get("ok"): return redirect("/")
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT chat_id FROM allowed_chats")
    g = [r[0] for r in c.fetchall()]
    conn.close()
    return "<h3>已授权群列表</h3>" + "<br>".join(map(str,g)) or "暂无数据"

@app.route("/admins")
def admins():
    if not session.get("ok"): return redirect("/")
    conn = get_db_connection()
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
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO allowed_chats VALUES (%s) ON CONFLICT (chat_id) DO NOTHING", (g,))
        conn.commit()
    except Exception as e:
        return f"错误: {e}"
    conn.close()
    return redirect("/")

@app.route("/ban", methods=["POST"])
def ban():
    if not session.get("ok"): return "无权限"
    u = request.form["u"].lstrip("@").lower()
    if not u: return "请输入用户名"
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO banned_users VALUES (%s) ON CONFLICT (username) DO NOTHING", (u,))
    conn.commit()
    conn.close()
    return f"<h3>已将 @{u} 加入黑名单数据库 (Bot 需重启生效)</h3><a href='/'>返回</a>"

@app.route("/clear", methods=["POST"])
def clear():
    if not session.get("ok"): return "无权限"
    u = request.form["u"].lstrip("@").lower()
    if not u: return "请输入用户名"
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM ratings WHERE username=%s", (u,))
    c.execute("DELETE FROM votes WHERE username=%s", (u,))
    conn.commit()
    conn.close()
    return f"<h3>已全局清理 @{u} 的信誉记录</h3><a href='/'>返回</a>"

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))