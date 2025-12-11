from flask import Flask, request, session, redirect, url_for
import os
import asyncio
import database
from functools import wraps
from asgiref.wsgi import WsgiToAsgi # 用于异步支持

app = Flask(__name__)
# 确保 SECRET_KEY 是随机的
app.secret_key = os.environ.get("SECRET_KEY", "WOLF_HUNTER_SECURE_KEY_RANDOM")

OWNER_ID = os.environ.get("OWNER_ID")
OWNER_PASSWORD = os.environ.get("OWNER_PASSWORD")

# 确保数据库连接池在 Web 应用启动前初始化一次
try:
    asyncio.run(database.init_schema())
except Exception as e:
    print(f"FATAL: Database initialization failed during Web startup: {e}")

# --- 装饰器：管理员权限检查 ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("ok"):
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

# --- 首页路由（新增密码登录和设置链接） ---
@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        input_id = request.form.get("id")
        input_pass = request.form.get("password")
        
        if input_id == OWNER_ID and input_pass == OWNER_PASSWORD:
            session["ok"] = True
            return redirect("/")
        elif input_id and input_pass:
            return "登录失败：ID 或密码错误", 401
    
    if session.get("ok"):
        return f'''
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <div style="font-family:sans-serif; max-width:600px; margin:20px auto; padding:20px;">
        <h1>🐺 狼猎信誉后台</h1>
        <p>主人 {OWNER_ID} | 数据库: PostgreSQL (asyncpg)</p>
        <p>
            <a href="/groups">授权群</a> | 
            <a href="/settings">群组设置</a> | 
            <a href="/banned">封禁列表</a> | 
            <a href="/logout">退出</a>
        </p>
        <hr>
        <h3>功能操作</h3>
        <form action="/ban_user" method="post" style="margin-bottom:15px;">
          <label>🚫 封禁用户 (ID)：</label><br>
          <input name="uid" type="number" placeholder="输入用户 ID" style="padding:5px;">
          <input name="uname" placeholder="用户名 (可选)" style="padding:5px;">
          <button style="padding:5px;">封禁</button>
        </form>
        <form action="/clear_data" method="post" style="margin-bottom:15px;">
          <label>🧹 清理数据 (ID)：</label><br>
          <input name="uid" type="number" placeholder="输入用户 ID" style="padding:5px;">
          <button style="padding:5px;">清理记录</button>
        </form>
        </div>
        '''
    
    return '''
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <div style="font-family:sans-serif; text-align:center; margin-top:50px;">
    <h2>狼猎信誉后台登录</h2>
    <form method="post">
      <input name="id" type="number" placeholder="输入 Owner ID" style="padding:10px; margin-bottom: 5px;">
      <input name="password" type="password" placeholder="输入 Owner Password" style="padding:10px; margin-bottom: 10px;">
      <button style="padding:10px;">登录</button>
    </form>
    <p style="margin-top:20px; font-size:small;">请在 Railway 变量中设置 OWNER_PASSWORD</p>
    </div>
    '''

# --- 新增：群组设置页面 ---
@app.route("/settings", methods=["GET", "POST"])
@login_required
async def group_settings():
    if request.method == "POST":
        group_id = request.form.get("gid")
        join_days = request.form.get("days", 0)
        channel_id = request.form.get("cid", 0)
        
        try:
            async with database.db_pool.acquire() as conn:
                 await conn.execute("""
                    INSERT INTO database.chat_settings (chat_id, min_join_days, force_channel_id) 
                    VALUES ($1, $2, $3)
                    ON CONFLICT (chat_id) DO UPDATE SET 
                    min_join_days = $2, force_channel_id = $3
                """, int(group_id), int(join_days), int(channel_id))
            return redirect(url_for('group_settings'))
        except Exception as e:
            return f"保存失败: {e}", 500

    # GET 请求：显示所有已授权群组的设置表单
    async with database.db_pool.acquire() as conn:
        groups = await conn.fetch("SELECT chat_id FROM allowed_chats")
        settings = await conn.fetch("SELECT chat_id, min_join_days, force_channel_id FROM chat_settings")
        settings_map = {s['chat_id']: s for s in settings}

    html = "<h3>⚙️ 群组设置与门槛</h3><p><a href='/'>返回首页</a></p>"
    html += "<table border='1' style='width:100%;'><tr><th>群组 ID</th><th>入群天数门槛</th><th>强制关注 ID</th><th>操作</th></tr>"
    
    for group in groups:
        gid = group['chat_id']
        s = settings_map.get(gid, {'min_join_days': 0, 'force_channel_id': 0})
        
        html += f"<form method='post'><tr>"
        html += f"<td>{gid}<input type='hidden' name='gid' value='{gid}'></td>"
        
        html += f"<td><input type='number' name='days' value='{s['min_join_days']}' style='width:80px;'> 天</td>"
        html += f"<td><input type='number' name='cid' value='{s['force_channel_id']}' placeholder='频道/群ID' style='width:120px;'></td>"
        html += f"<td><button>保存设置</button></td>"
        html += "</tr></form>"

    html += "</table>"
    return html

# --- 授权群列表 ---
@app.route("/groups")
@login_required
async def groups_list():
    async with database.db_pool.acquire() as conn:
        groups = await conn.fetch("SELECT chat_id FROM allowed_chats")
        g = [r['chat_id'] for r in groups]
    return "<h3>已授权群列表</h3>" + "<br>".join(map(str, g)) or "暂无数据"


# --- 封禁列表与解禁（Web 路由） ---
@app.route("/banned")
@login_required
async def banned_list():
    banned = await database.get_banned_list()
    
    html = "<h3>🚫 已封禁用户列表</h3>"
    html += "<ul>"
    
    for user in banned:
        html += f"<li>ID: <code>{user['user_id']}</code> (@{user['username'] or '无用户名'}) "
        html += f"<form action='/unban_user' method='post' style='display:inline; margin-left:10px;'>"
        html += f"<input type='hidden' name='uid' value='{user['user_id']}'>"
        html += f"<button style='color:red; background:none; border:1px solid red; cursor:pointer;'>解禁</button>"
        html += "</form></li>"
        
    html += "</ul><p><a href='/'>返回首页</a></p>"
    return html

@app.route("/unban_user", methods=["POST"])
@login_required
async def unban_user_route():
    uid = request.form["uid"]
    if not uid: return "请输入用户ID"
    try:
        await database.unban_user(int(uid))
        return redirect("/banned")
    except Exception as e:
        return f"解禁失败: {e}", 500

# --- 封禁和清理操作（Web 路由） ---
@app.route("/ban_user", methods=["POST"])
@login_required
async def ban_user_route():
    uid = request.form["uid"]
    uname = request.form.get("uname", None)
    if not uid: return "请输入用户ID"
    try:
        await database.ban_user(int(uid), uname)
        return f"<h3>已将 ID: {uid} 加入黑名单数据库</h3><a href='/'>返回</a>"
    except Exception as e:
        return f"封禁失败: {e}", 500

@app.route("/clear_data", methods=["POST"])
@login_required
async def clear_data_route():
    uid = request.form["uid"]
    if not uid: return "请输入用户ID"
    try:
        await database.clear_user_data(int(uid))
        return f"<h3>已全局清理 ID: {uid} 的所有记录</h3><a href='/'>返回</a>"
    except Exception as e:
        return f"清理失败: {e}", 500

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# 确保 gunicorn 可以调用 Flask 应用
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))