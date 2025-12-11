from flask import Flask, request, session, redirect, url_for, flash
import os
import asyncio
import database
from functools import wraps
from asgiref.wsgi import WsgiToAsgi
from datetime import datetime

# --- 初始化 Flask App ---
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "WOLF_HUNTER_SECURE_KEY_RANDOM")

OWNER_ID = os.environ.get("OWNER_ID")
OWNER_PASSWORD = os.environ.get("OWNER_PASSWORD")

# --- 基础 CSS 样式 (升级为后台管理系统风格) ---
BASE_CSS = """
<style>
    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; color: #333; margin: 0; display: flex; min-height: 100vh; }
    #sidebar { width: 200px; background-color: #2c3e50; color: white; padding: 20px 0; box-shadow: 2px 0 5px rgba(0, 0, 0, 0.1); flex-shrink: 0; }
    #sidebar a { display: block; padding: 10px 20px; text-decoration: none; color: #ecf0f1; border-left: 5px solid transparent; transition: all 0.2s; }
    #sidebar a:hover, #sidebar a.active { background-color: #34495e; border-left: 5px solid #3498db; }
    #sidebar h3 { color: #ecf0f1; text-align: center; margin-bottom: 30px; }

    #content { flex-grow: 1; padding: 30px; }
    .container { max-width: 1200px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); }
    h1 { color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; margin-bottom: 20px; }
    h3 { color: #2980b9; margin-top: 0; margin-bottom: 20px; }
    hr { border: 0; height: 1px; background-color: #eee; margin: 20px 0; }
    
    .nav-top { text-align: right; margin-bottom: 20px; }
    .nav-top a { text-decoration: none; color: #e74c3c; font-weight: bold; margin-left: 15px; }

    input[type="text"], input[type="number"], input[type="password"] { padding: 10px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
    button, .btn { padding: 10px 15px; background-color: #2ecc71; color: white; border: none; border-radius: 4px; cursor: pointer; transition: background-color 0.3s; text-decoration: none; display: inline-block;}
    button:hover, .btn:hover { background-color: #27ae60; }
    .btn-primary { background-color: #3498db; }
    .btn-primary:hover { background-color: #2980b9; }
    .btn-danger { background-color: #c0392b; }
    .btn-danger:hover { background-color: #a93226; }
    
    .alert-success { background-color: #e6ffe6; color: #1a7c1a; padding: 10px; border-radius: 4px; margin-bottom: 15px; border-left: 5px solid #2ecc71; }
    .alert-error { background-color: #ffe6e6; color: #cc0000; padding: 10px; border-radius: 4px; margin-bottom: 15px; border-left: 5px solid #cc0000; }
    
    table { width: 100%; border-collapse: collapse; margin-top: 15px; }
    th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
    th { background-color: #f2f2f2; }
    
    .action-bar { display: flex; justify-content: space-between; margin-bottom: 20px; align-items: center; }
    .form-inline > * { margin-right: 10px; }
</style>
"""

# --- 辅助函数：运行异步代码 (关键函数，确保 Web 异步操作正常) ---
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

def flash(message, category):
    """自定义 flash 函数，使用 session 存储消息"""
    session.setdefault('_flashes', []).append((category, message))

# --- 装饰器：管理员权限检查 ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("ok"):
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated_function

# --- 侧边栏和主页容器生成器 (新 UI 骨架) ---
def render_admin_page(title, content_html, active_nav):
    messages = session.pop('_flashes', [])
    flash_html = "".join([f'<div class="alert-{category}">{message}</div>' for category, message in messages])
    
    return f"""
    <meta name="viewport" content="width=device-width, initial-scale=1">
    {BASE_CSS}
    <div id="sidebar">
        <h3>🐺 狼猎后台</h3>
        <a href="/" class="{'active' if active_nav == 'home' else ''}">🏠 首页操作</a>
        <a href="/groups" class="{'active' if active_nav == 'groups' else ''}">👥 授权群管理</a>
        <a href="/settings" class="{'active' if active_nav == 'settings' else ''}">⚙️ 群组设置</a>
        <a href="/banned" class="{'active' if active_nav == 'banned' else ''}">🚫 封禁用户</a>
    </div>
    <div id="content">
        <div class="nav-top">
            用户: {OWNER_ID} | <a href="/logout">退出</a>
        </div>
        <div class="container">
            <h1>{title}</h1>
            {flash_html}
            {content_html}
        </div>
    </div>
    """

# --- 首页路由 (Dashboard & 快速操作) ---
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

    if not session.get("ok"):
        # 登录页面的 HTML
        messages = session.pop('_flashes', [])
        flash_html = "".join([f'<div class="alert-{category}">{message}</div>' for category, message in messages])
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

    # 管理后台首页内容
    content = f"""
    <h3>功能操作面板</h3>
    <hr>
    
    <div class="form-group">
        <label>🚫 **封禁用户**</label>
        <form action="/ban_user" method="post" class="form-inline">
          <input name="uid" type="number" placeholder="输入用户 ID" style="width:150px;">
          <input name="uname" placeholder="用户名 (可选)" style="width:150px;">
          <button class="btn-danger">立即封禁</button>
        </form>
    </div>
    
    <div class="form-group">
        <label>🧹 **清理数据**</label>
        <form action="/clear_data" method="post" class="form-inline">
          <input name="uid" type="number" placeholder="输入用户 ID" style="width:150px;">
          <button class="btn-primary" style="background-color:#f39c12;">清理记录</button>
        </form>
    </div>
    """
    
    return render_admin_page("🏠 首页操作面板", content, "home")


# --- 1. 封禁列表管理 (/banned) ---
@app.route("/banned", methods=["GET"])
@login_required
def banned_list():
    async def inner_logic():
        if database.db_pool is None: await database.init_db_pool()
        
        try:
            search_query = request.args.get("search", "").strip()
            
            banned_data = await database.get_banned_list()
            
            # 过滤搜索结果
            if search_query:
                banned_data = [
                    user for user in banned_data 
                    if str(user['user_id']) == search_query or (user.get('username') and search_query.lower() in user['username'].lower())
                ]
                flash(f"🔍 搜索结果: {len(banned_data)} 条", "success")

        except Exception as e:
            banned_data = []
            flash(f"❌ 数据库查询失败: {e}", "error")
        
        if not isinstance(banned_data, list): banned_data = []

        content = f"""
        <h3>封禁用户管理 ({len(banned_data)} 人)</h3>

        <div class="action-bar">
            <form action="/banned" method="get" class="form-inline">
                <input type="text" name="search" placeholder="搜索用户 ID/用户名" value="{search_query}" style="width:200px;">
                <button type="submit" class="btn-primary">搜索</button>
            </form>
            <a href="/" class="btn btn-danger">手动添加封禁</a>
        </div>
        
        <table style="font-size: 0.9em;">
        <thead><tr>
            <th>用户 ID</th>
            <th>用户名</th>
            <th>封禁时间</th>
            <th>状态</th>
            <th>操作</th>
        </tr></thead>
        <tbody>
        """
        
        for user in banned_data:
            try:
                uid = user['user_id']
                uname = user.get('username') or '无用户名'
                ban_time = user.get('time')
                time_str = ban_time.strftime('%Y-%m-%d %H:%M:%S') if ban_time else '未知'
            except KeyError:
                continue
            
            content += f"""
            <tr>
            <td><code>{uid}</code></td>
            <td>@{uname}</td>
            <td>{time_str}</td>
            <td><span style="color: red; font-weight: bold;">已封禁</span></td>
            <td>
            <form action='/unban_user' method='post' style='display:inline;'>
            <input type='hidden' name='uid' value='{uid}'>
            <button class="btn-primary" style='padding:5px 10px; font-size: 0.8em;'>解禁</button>
            </form>
            </td>
            </tr>
            """
            
        if not banned_data:
             content += '<tr><td colspan="5" style="text-align:center;">暂无封禁记录。</td></tr>'

        content += "</tbody></table>"
        return content
        
    return render_admin_page("🚫 封禁用户管理", run_async(inner_logic()), "banned")


# --- 2. 授权群组管理 (/groups) ---
@app.route("/groups", methods=["GET", "POST"])
@login_required
def groups_list():
    async def inner_logic():
        if database.db_pool is None: await database.init_db_pool()
        
        # POST: 添加群组
        if request.method == "POST":
            gid_str = request.form.get("gid", "").strip()
            if gid_str:
                try:
                    gid = int(gid_str)
                    await database.save_group(gid)
                    flash(f"✅ 已授权群组 ID: <code>{gid}</code>", "success")
                except ValueError:
                    flash("❌ 群组 ID 必须是数字。", "error")
                except Exception as e:
                     flash(f"❌ 添加授权失败: {e}", "error")
            return redirect(url_for('groups_list'))

        # GET: 显示群组列表
        groups = await database.get_allowed_chats()
        
        content = f"""
        <h3>已授权群组列表 ({len(groups)} 个)</h3>
        
        <div class="action-bar">
            <form action="/groups" method="post" class="form-inline">
                <input type="number" name="gid" placeholder="输入新的群组 ID" style="width:200px;">
                <button type="submit" class="btn-primary">+ 授权新群组</button>
            </form>
        </div>
        
        <table style="font-size: 0.9em;">
        <thead><tr>
            <th>群组 ID</th>
            <th>操作</th>
        </tr></thead>
        <tbody>
        """
        
        for group in groups:
            gid = group['chat_id']
            content += f"""
            <tr>
            <td><code>{gid}</code></td>
            <td>
            <form action='/del_group_action' method='post' style='display:inline;'>
            <input type='hidden' name='gid' value='{gid}'>
            <button class="btn-danger" style='padding:5px 10px; font-size: 0.8em;'>移除授权</button>
            </form>
            <a href="/settings?gid={gid}" class="btn-primary" style='padding:5px 10px; font-size: 0.8em; background-color:#1abc9c;'>设置门槛</a>
            </td>
            </tr>
            """
        
        if not groups:
             content += '<tr><td colspan="2" style="text-align:center;">暂无授权群组。</td></tr>'
        
        content += "</tbody></table>"
        return content
        
    return render_admin_page("👥 授权群组管理", run_async(inner_logic()), "groups")


@app.route("/del_group_action", methods=["POST"])
@login_required
def del_group_action():
    async def inner_logic():
        if database.db_pool is None: await database.init_db_pool()
        gid_str = request.form.get("gid")
        try:
            gid = int(gid_str)
            await database.del_group(gid)
            flash(f"✅ 已移除群组 ID: <code>{gid}</code> 的授权。", "success")
        except ValueError:
            flash("❌ 群组 ID 格式错误。", "error")
        except Exception as e:
            flash(f"❌ 移除授权失败: {e}", "error")
        return redirect(url_for('groups_list'))
    
    return run_async(inner_logic())


# --- 3. 群组设置管理 (/settings) ---
@app.route("/settings", methods=["GET", "POST"])
@login_required
def group_settings():
    async def inner_logic():
        if database.db_pool is None: await database.init_db_pool()

        # 处理 POST 请求：保存设置
        if request.method == "POST":
            group_id = request.form.get("gid")
            join_days = request.form.get("days", 0)
            channel_id = request.form.get("cid", 0)
            
            try:
                if str(channel_id).strip() and not str(channel_id).strip().startswith(('-', '1', '2', '3', '4', '5', '6', '7', '8', '9')):
                    flash("⚠️ 强制关注ID必须是数字 ID！", "error")
                    return redirect(url_for('group_settings'))

                async with database.db_pool.acquire() as conn:
                     # 确保数据库操作是正确的
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

        # 处理 GET 请求：显示所有已授权群组的设置表单
        groups = await database.get_allowed_chats()
        # 假设 database.py 中新增了 get_chat_settings_list 函数
        try:
            settings = await database.get_chat_settings_list() 
        except Exception as e:
            flash(f"⚠️ 无法加载设置数据：请确保 database.py 中已添加 get_chat_settings_list 函数。{e}", "error")
            settings = []
            
        settings_map = {s['chat_id']: s for s in settings}

        content = f"""
        <h3>群组投票门槛和强制关注设置</h3>
        <p>群组 ID 为负数时代表超级群/频道。只有在 '授权群管理' 中添加的群组才会在这里列出。</p>
        
        <table style="font-size: 0.9em;">
        <thead><tr>
            <th>群组 ID</th>
            <th>入群天数门槛 (天)</th>
            <th>强制关注 ID</th>
            <th>操作</th>
        </tr></thead>
        <tbody>
        """
        
        for group in groups:
            gid = group['chat_id']
            s = settings_map.get(gid, {'min_join_days': 0, 'force_channel_id': 0})
            
            content += f"<form method='post'><tr>"
            content += f"<td><code>{gid}</code><input type='hidden' name='gid' value='{gid}'></td>"
            
            content += f"<td><input type='number' name='days' value='{s['min_join_days']}' style='width:80px;'></td>"
            content += f"<td><input type='text' name='cid' value='{s['force_channel_id']}' placeholder='频道/群ID (数字)' style='width:120px;'></td>"
            content += f"<td><button class='btn-primary' style='padding:5px 10px; font-size: 0.8em;'>保存设置</button></td>"
            content += "</tr></form>"

        if not groups:
             content += '<tr><td colspan="4" style="text-align:center;">请先在授权群管理中添加群组。</td></tr>'
             
        content += "</tbody></table>"
        return content
        
    return render_admin_page("⚙️ 群组设置管理", run_async(inner_logic()), "settings")


# --- 数据库操作路由 (保持不变) ---
@app.route("/ban_user", methods=["POST"])
@login_required
def ban_user_route():
    async def inner_logic():
        if database.db_pool is None: await database.init_db_pool()
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
        if database.db_pool is None: await database.init_db_pool()
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

@app.route("/unban_user", methods=["POST"])
@login_required
def unban_user_route():
    async def inner_logic():
        if database.db_pool is None: await database.init_db_pool()
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


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# 包装 Flask 应用为 ASGI 应用
app = WsgiToAsgi(app)