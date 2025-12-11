from flask import Flask, request, session, redirect, url_for, flash
import os
import asyncio
import database
from functools import wraps
from asgiref.wsgi import WsgiToAsgi

app = Flask(__name__)
# 确保 SECRET_KEY 是随机的
app.secret_key = os.environ.get("SECRET_KEY", "WOLF_HUNTER_SECURE_KEY_RANDOM")

OWNER_ID = os.environ.get("OWNER_ID")
OWNER_PASSWORD = os.environ.get("OWNER_PASSWORD")

# --- 基础 CSS 样式 ---
BASE_CSS = """
<style>
    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; color: #333; margin: 0; padding: 20px; }
    .container { max-width: 800px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); }
    h1 { color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; margin-bottom: 20px; }
    h3 { color: #2980b9; margin-top: 25px; }
    hr { border: 0; height: 1px; background-color: #eee; margin: 20px 0; }
    .nav a { margin-right: 15px; text-decoration: none; color: #3498db; font-weight: bold; }
    .nav a:hover { color: #2980b9; }
    .form-group { margin-bottom: 15px; padding: 15px; border: 1px solid #e0e0e0; border-radius: 5px; }
    input[type="text"], input[type="number"], input[type="password"] { padding: 10px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
    button { padding: 10px 15px; background-color: #2ecc71; color: white; border: none; border-radius: 4px; cursor: pointer; transition: background-color 0.3s; }
    button:hover { background-color: #27ae60; }
    .alert-success { background-color: #e6ffe6; color: #1a7c1a; padding: 10px; border-radius: 4px; margin-bottom: 15px; border-left: 5px solid #2ecc71; }
    .alert-error { background-color: #ffe6e6; color: #cc0000; padding: 10px; border-radius: 4px; margin-bottom: 15px; border-left: 5px solid #cc0000; }
    table { width: 100%; border-collapse: collapse; margin-top: 15px; }
    th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
    th { background-color: #f2f2f2; }
    .logout { float: right; }
    .login-container { max-width: 400px; margin: 100px auto; text-align: center; }
</style>
"""

# --- 辅助函数：强制运行异步代码 (解决 'coroutine' 错误) ---
def run_async(coro):
    """在一个同步线程中运行异步代码并返回结果"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    if loop.is_running():
        # 如果事件循环已经在运行，使用 run_coroutine_threadsafe
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()
    else:
        # 否则，运行新的事件循环
        return loop.run_until_complete(coro)
# --- 辅助函数结束 ---

def flash(message, category):
    """自定义 flash 函数，使用 session 存储消息"""
    session.setdefault('_flashes', []).append((message, category))

# --- 装饰器：管理员权限检查 ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("ok"):
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

# --- 首页路由 (同步) ---
@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        input_id = request.form.get("id")
        input_pass = request.form.get("password")
        
        if input_id == OWNER_ID and input_pass == OWNER_PASSWORD:
            session["ok"] = True
            return redirect("/")
        elif input_id and input_pass:
            flash("登录失败：ID 或密码错误", "error")
            return redirect(url_for('home'))

    # 获取并显示操作反馈信息
    messages = session.pop('_flashes', [])
    flash_html = "".join([f'<div class="alert-{category}">{message}</div>' for category, message in messages])
    
    if session.get("ok"):
        return f'''
        <meta name="viewport" content="width=device-width, initial-scale=1">
        {BASE_CSS}
        <div class="container">
        <h1>🐺 狼猎信誉后台</h1>
        <p>主人 {OWNER_ID} | 数据库: PostgreSQL (asyncpg)</p>
        <div class="nav">
            <a href="/groups">授权群</a> | 
            <a href="/settings">群组设置</a> | 
            <a href="/banned">封禁列表</a> 
            <a href="/logout" class="logout">退出</a>
        </div>
        <hr>
        {flash_html}
        <h3>功能操作</h3>
        <form action="/ban_user" method="post" class="form-group">
          <label style="display:block; margin-bottom:5px;">🚫 封禁用户 (ID)：</label>
          <input name="uid" type="number" placeholder="输入用户 ID" style="width:150px;">
          <input name="uname" placeholder="用户名 (可选)" style="width:150px;">
          <button style="background-color:#c0392b;">封禁</button>
        </form>
        <form action="/clear_data" method="post" class="form-group">
          <label style="display:block; margin-bottom:5px;">🧹 清理数据 (ID)：</label>
          <input name="uid" type="number" placeholder="输入用户 ID" style="width:150px;">
          <button style="background-color:#f39c12;">清理记录</button>
        </form>
        </div>
        '''
    
    return f'''
    <meta name="viewport" content="width=device-width, initial-scale=1">
    {BASE_CSS}
    <div class="login-container">
    <h2>狼猎信誉后台登录</h2>
    {flash_html}
    <form method="post" style="padding:20px; border:1px solid #ccc; border-radius:5px;">
      <input name="id" type="number" placeholder="输入 Owner ID" style="width: 100%; margin-bottom: 10px;">
      <input name="password" type="password" placeholder="输入 Owner Password" style="width: 100%; margin-bottom: 20px;">
      <button style="width: 100%; background-color: #3498db;">登录</button>
    </form>
    <p style="margin-top:20px; font-size:small;">请在 Railway 变量中设置 OWNER_PASSWORD</p>
    </div>
    '''

# --- 群组设置页面 (同步包装异步) ---
@app.route("/settings", methods=["GET", "POST"])
@login_required
def group_settings():
    async def inner_logic():
        if request.method == "POST":
            group_id = request.form.get("gid")
            join_days = request.form.get("days", 0)
            channel_id = request.form.get("cid", 0)
            
            try:
                # 检查强制关注ID是否是数字（Bot中会再次检查是否有效）
                if str(channel_id).strip() and not str(channel_id).strip().startswith(('-', '1', '2', '3', '4', '5', '6', '7', '8', '9')):
                    flash("⚠️ 强制关注ID必须是数字 ID！", "error")
                    return redirect(url_for('group_settings'))

                async with database.db_pool.acquire() as conn:
                     await conn.execute("""
                        INSERT INTO database.chat_settings (chat_id, min_join_days, force_channel_id) 
                        VALUES ($1, $2, $3)
                        ON CONFLICT (chat_id) DO UPDATE SET 
                        min_join_days = $2, force_channel_id = $3
                    """, int(group_id), int(join_days), int(channel_id))
                flash(f"✅ 群组 <code>{group_id}</code> 设置保存成功！", "success")
                return redirect(url_for('group_settings'))
            except Exception as e:
                flash(f"❌ 保存失败: {e}", "error")
                return redirect(url_for('group_settings'))

        # GET 请求：显示所有已授权群组的设置表单
        async with database.db_pool.acquire() as conn:
            groups = await conn.fetch("SELECT chat_id FROM allowed_chats")
            settings = await conn.fetch("SELECT chat_id, min_join_days, force_channel_id FROM chat_settings")
            settings_map = {s['chat_id']: s for s in settings}

        flash_html = "".join([f'<div class="alert-{category}">{message}</div>' for category, message in session.pop('_flashes', [])])

        html = f"""
        <meta name="viewport" content="width=device-width, initial-scale=1">
        {BASE_CSS}
        <div class="container">
        <h1>🐺 狼猎信誉后台</h1>
        <div class="nav"><a href='/'>返回首页</a></div><hr>
        {flash_html}
        <h3>⚙️ 群组设置与门槛</h3>
        <p>群 ID 为负数时代表超级群/频道，正数时代表用户/Bot。强制关注 ID 必须是数字 ID。</p>
        <table>
        <thead><tr><th>群组 ID</th><th>入群天数门槛 (天)</th><th>强制关注 ID</th><th>操作</th></tr></thead>
        <tbody>
        """
        
        for group in groups:
            gid = group['chat_id']
            s = settings_map.get(gid, {'min_join_days': 0, 'force_channel_id': 0})
            
            html += f"<form method='post'><tr>"
            html += f"<td><code>{gid}</code><input type='hidden' name='gid' value='{gid}'></td>"
            
            html += f"<td><input type='number' name='days' value='{s['min_join_days']}' style='width:80px;'></td>"
            html += f"<td><input type='text' name='cid' value='{s['force_channel_id']}' placeholder='频道/群ID (数字)' style='width:120px;'></td>"
            html += f"<td><button>保存设置</button></td>"
            html += "</tr></form>"

        html += "</tbody></table></div>"
        return html
        
    return run_async(inner_logic())


# --- 授权群列表 (同步包装异步) ---
@app.route("/groups")
@login_required
def groups_list():
    async def inner_logic():
        async with database.db_pool.acquire() as conn:
            groups = await conn.fetch("SELECT chat_id FROM allowed_chats")
            g = [r['chat_id'] for r in groups]
        
        list_html = "".join([f"<li><code>{cid}</code></li>" for cid in g]) or "<li>暂无数据</li>"

        return f"""
        <meta name="viewport" content="width=device-width, initial-scale=1">
        {BASE_CSS}
        <div class="container">
        <h1>🐺 狼猎信誉后台</h1>
        <div class="nav"><a href='/'>返回首页</a></div><hr>
        <h3>已授权群列表 ({len(g)} 个)</h3>
        <ul>{list_html}</ul>
        </div>
        """
        
    return run_async(inner_logic())


# --- 封禁列表与解禁 (同步包装异步) ---
@app.route("/banned")
@login_required
def banned_list():
    async def inner_logic():
        banned = await database.get_banned_list()
        
        flash_html = "".join([f'<div class="alert-{category}">{message}</div>' for category, message in session.pop('_flashes', [])])

        html = f"""
        <meta name="viewport" content="width=device-width, initial-scale=1">
        {BASE_CSS}
        <div class="container">
        <h1>🐺 狼猎信誉后台</h1>
        <div class="nav"><a href='/'>返回首页</a></div><hr>
        {flash_html}
        <h3>🚫 已封禁用户列表 ({len(banned)} 人)</h3>
        <table>
        <thead><tr><th>用户 ID</th><th>用户名</th><th>操作</th></tr></thead>
        <tbody>
        """
        
        for user in banned:
            uid = user['user_id']
            uname = user['username'] or '无用户名'
            
            html += f"""
            <tr>
            <td><code>{uid}</code></td>
            <td>@{uname}</td>
            <td>
            <form action='/unban_user' method='post' style='display:inline;'>
            <input type='hidden' name='uid' value='{uid}'>
            <button style='background-color:#2ecc71; padding:5px 10px;'>解禁</button>
            </form>
            </td>
            </tr>
            """
            
        html += "</tbody></table></div>"
        return html
        
    return run_async(inner_logic())


@app.route("/unban_user", methods=["POST"])
@login_required
def unban_user_route():
    async def inner_logic():
        uid = request.form["uid"]
        if not uid: 
            flash("⚠️ 请提供用户ID。", "error")
            return redirect("/banned")
        try:
            await database.unban_user(int(uid))
            flash(f"✅ 用户 ID: <code>{uid}</code> 已成功解禁。", "success")
            return redirect("/banned")
        except Exception as e:
            flash(f"❌ 解禁失败: {e}", "error")
            return redirect("/banned")
            
    return run_async(inner_logic())


# --- 封禁和清理操作 (同步包装异步) ---
@app.route("/ban_user", methods=["POST"])
@login_required
def ban_user_route():
    async def inner_logic():
        uid = request.form["uid"]
        uname = request.form.get("uname", None)
        if not uid: 
            flash("⚠️ 请输入用户ID。", "error")
            return redirect("/")
        try:
            await database.ban_user(int(uid), uname)
            flash(f"🚫 已将 ID: <code>{uid}</code> 加入黑名单数据库。", "success")
            return redirect("/")
        except Exception as e:
            flash(f"❌ 封禁失败: {e}", "error")
            return redirect("/")
            
    return run_async(inner_logic())


@app.route("/clear_data", methods=["POST"])
@login_required
def clear_data_route():
    async def inner_logic():
        uid = request.form["uid"]
        if not uid: 
            flash("⚠️ 请输入用户ID。", "error")
            return redirect("/")
        try:
            await database.clear_user_data(int(uid))
            flash(f"🧹 已全局清理 ID: <code>{uid}</code> 的所有记录。", "success")
            return redirect("/")
        except Exception as e:
            flash(f"❌ 清理失败: {e}", "error")
            return redirect("/")
            
    return run_async(inner_logic())


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# 包装 Flask 应用为 ASGI 应用
app = WsgiToAsgi(app)

# 仅供本地测试，部署时由 gunicorn 负责
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))