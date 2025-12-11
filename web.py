import os
import asyncio
from flask import Flask, jsonify, request, render_template_string
from asgiref.wsgi import WsgiToAsgi
from database import get_banned_list, unban_user, get_total_users, get_total_votes, get_chat_settings_list, db_pool, init_db_pool

# --- 配置 ---
app = Flask(__name__)

# 用于 Web 页面身份验证 (非常简陋，生产环境应使用更安全的机制)
WEB_SECRET_KEY = os.environ.get('WEB_SECRET_KEY') or "default_secret"
if WEB_SECRET_KEY == "default_secret":
    print("WARNING: WEB_SECRET_KEY is using the default value. Change it for security.")

# --- 辅助函数 ---

def is_authorized(auth_header):
    """简单的密钥认证"""
    if not auth_header:
        return False
    # 期望格式: Bearer <key>
    try:
        scheme, key = auth_header.split()
        if scheme.lower() == 'bearer' and key == WEB_SECRET_KEY:
            return True
    except:
        pass
    return False

# Flask 视图需要同步函数。
# 由于 database.py 中的函数是异步的，我们使用 asyncio.run 来同步调用它们。
def sync_call(coro):
    """同步地运行异步协程"""
    # 确保只在 Web Worker 中初始化一次数据库连接池
    if not db_pool:
        asyncio.run(init_db_pool())
    return asyncio.run(coro)

# --- Web 路由：API ---

@app.route('/api/stats', methods=['GET'])
def stats_api():
    """获取统计信息 API"""
    if not is_authorized(request.headers.get('Authorization')):
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        total_users = sync_call(get_total_users())
        total_votes = sync_call(get_total_votes())
        return jsonify({
            "total_users": total_users,
            "total_votes": total_votes
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/banned', methods=['GET'])
def banned_api():
    """获取被封禁用户列表 API"""
    if not is_authorized(request.headers.get('Authorization')):
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        banned_users = sync_call(get_banned_list())
        # 格式化时间对象为字符串以便 JSON 序列化
        data = [
            {
                "user_id": user['user_id'], 
                "username": user['username'], 
                "time": user['time'].isoformat() if user['time'] else None
            } 
            for user in banned_users
        ]
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/unban/<int:user_id>', methods=['POST'])
def unban_api(user_id):
    """解除封禁 API"""
    if not is_authorized(request.headers.get('Authorization')):
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        sync_call(unban_user(user_id))
        return jsonify({"status": "success", "user_id": user_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/chat_settings', methods=['GET'])
def chat_settings_api():
    """获取群组设置列表 API"""
    if not is_authorized(request.headers.get('Authorization')):
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        settings_list = sync_call(get_chat_settings_list())
        # 直接返回列表，因为 chat_id, min_join_days, force_channel_id 都是基本类型
        return jsonify(list(settings_list))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- Web 路由：Dashboard (HTML/JS) ---

# 简单的 HTML 模板，包含 JS 用于调用 API
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>信誉系统管理面板</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; margin: 0; padding: 20px; background-color: #f4f7f6; color: #333; }
        .container { max-width: 1200px; margin: auto; background: #fff; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
        h1 { color: #007bff; border-bottom: 2px solid #007bff; padding-bottom: 10px; margin-bottom: 20px; }
        h2 { color: #333; margin-top: 30px; border-bottom: 1px solid #eee; padding-bottom: 5px; }
        .stats { display: flex; gap: 20px; margin-bottom: 20px; }
        .stat-card { background: #e9ecef; padding: 15px 20px; border-radius: 8px; flex: 1; text-align: center; }
        .stat-card h3 { margin: 0 0 5px 0; color: #6c757d; font-size: 14px; }
        .stat-card p { font-size: 24px; font-weight: bold; color: #007bff; margin: 0; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { padding: 12px 15px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background-color: #007bff; color: white; font-weight: 600; }
        tr:hover { background-color: #f1f1f1; }
        .btn-unban { background-color: #dc3545; color: white; border: none; padding: 8px 12px; border-radius: 4px; cursor: pointer; transition: background-color 0.2s; }
        .btn-unban:hover { background-color: #c82333; }
        .message { padding: 15px; border-radius: 5px; margin-bottom: 15px; }
        .message.error { background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🐺 狼猎信誉系统管理面板</h1>
        <div id="auth-error" class="message error" style="display:none;">
            认证失败。请检查 URL 中的密钥或设置 Authorization: Bearer Header。
        </div>

        <div class="stats" id="stats-section">
            </div>

        <h2>⛔ 封禁用户列表</h2>
        <table id="banned-table">
            <thead>
                <tr>
                    <th>用户 ID</th>
                    <th>Username</th>
                    <th>封禁时间 (UTC)</th>
                    <th>操作</th>
                </tr>
            </thead>
            <tbody>
                </tbody>
        </table>

        <h2>⚙️ 群组设置列表</h2>
        <table id="chat-settings-table">
            <thead>
                <tr>
                    <th>群 ID</th>
                    <th>入群投票门槛 (天)</th>
                    <th>强制关注频道 ID</th>
                </tr>
            </thead>
            <tbody>
                </tbody>
        </table>

    </div>

    <script>
        const API_URL = window.location.origin + '/api';
        const AUTH_HEADER = '{{ WEB_SECRET_KEY }}'; // 从 Flask 模板注入密钥

        function getAuthHeaders() {
            // 默认从 URL 注入的密钥生成 Bearer 头
            return {
                'Authorization': 'Bearer ' + AUTH_HEADER,
                'Content-Type': 'application/json'
            };
        }

        function handleError(error) {
            console.error('API Error:', error);
            document.getElementById('auth-error').style.display = 'block';
        }

        // --- 1. 加载统计数据 ---
        async function loadStats() {
            try {
                const response = await fetch(API_URL + '/stats', { headers: getAuthHeaders() });
                if (response.status === 401) throw new Error("Unauthorized");
                const data = await response.json();
                
                const statsHtml = `
                    <div class="stat-card"><h3>总用户数</h3><p>${data.total_users.toLocaleString()}</p></div>
                    <div class="stat-card"><h3>总投票数</h3><p>${data.total_votes.toLocaleString()}</p></div>
                `;
                document.getElementById('stats-section').innerHTML = statsHtml;
            } catch (error) {
                handleError(error);
            }
        }

        // --- 2. 加载封禁用户列表 ---
        async function loadBannedUsers() {
            const tableBody = document.getElementById('banned-table').getElementsByTagName('tbody')[0];
            tableBody.innerHTML = '<tr><td colspan="4">加载中...</td></tr>';
            
            try {
                const response = await fetch(API_URL + '/banned', { headers: getAuthHeaders() });
                if (response.status === 401) throw new Error("Unauthorized");
                const users = await response.json();

                tableBody.innerHTML = ''; // 清空加载提示
                if (users.length === 0) {
                    tableBody.innerHTML = '<tr><td colspan="4">当前没有被封禁的用户。</td></tr>';
                    return;
                }

                users.forEach(user => {
                    const row = tableBody.insertRow();
                    row.insertCell().textContent = user.user_id;
                    row.insertCell().textContent = user.username || 'N/A';
                    row.insertCell().textContent = user.time ? new Date(user.time).toLocaleString() : '未知';
                    
                    const actionCell = row.insertCell();
                    const unbanBtn = document.createElement('button');
                    unbanBtn.className = 'btn-unban';
                    unbanBtn.textContent = '解禁';
                    unbanBtn.onclick = () => unbanUser(user.user_id, unbanBtn);
                    actionCell.appendChild(unbanBtn);
                });
            } catch (error) {
                handleError(error);
                tableBody.innerHTML = '<tr><td colspan="4">加载失败。</td></tr>';
            }
        }

        // --- 3. 解禁用户操作 ---
        async function unbanUser(userId, button) {
            if (!confirm(`确定要解除对用户 ID: ${userId} 的封禁吗？`)) return;

            button.disabled = true;
            button.textContent = '处理中...';

            try {
                const response = await fetch(API_URL + `/unban/${userId}`, { 
                    method: 'POST', 
                    headers: getAuthHeaders() 
                });
                if (response.status === 401) throw new Error("Unauthorized");
                
                const result = await response.json();
                if (result.status === 'success') {
                    alert(`用户 ${userId} 已被解除封禁。`);
                    loadBannedUsers(); // 重新加载列表
                } else {
                    alert('解禁失败: ' + result.error);
                }
            } catch (error) {
                handleError(error);
                alert('解禁操作失败。');
            } finally {
                button.disabled = false;
                button.textContent = '解禁';
            }
        }

        // --- 4. 加载群组设置列表 ---
        async function loadChatSettings() {
            const tableBody = document.getElementById('chat-settings-table').getElementsByTagName('tbody')[0];
            tableBody.innerHTML = '<tr><td colspan="3">加载中...</td></tr>';
            
            try {
                const response = await fetch(API_URL + '/chat_settings', { headers: getAuthHeaders() });
                if (response.status === 401) throw new Error("Unauthorized");
                const settings = await response.json();

                tableBody.innerHTML = ''; // 清空加载提示
                if (settings.length === 0) {
                    tableBody.innerHTML = '<tr><td colspan="3">当前没有群组设置记录。</td></tr>';
                    return;
                }

                settings.forEach(setting => {
                    const row = tableBody.insertRow();
                    row.insertCell().textContent = setting.chat_id;
                    row.insertCell().textContent = setting.min_join_days + ' 天';
                    row.insertCell().textContent = setting.force_channel_id === 0 ? '未设置' : setting.force_channel_id;
                });
            } catch (error) {
                handleError(error);
                tableBody.innerHTML = '<tr><td colspan="3">加载失败。</td></tr>';
            }
        }

        // 页面初始化
        document.addEventListener('DOMContentLoaded', () => {
            loadStats();
            loadBannedUsers();
            loadChatSettings();
        });
    </script>
</body>
</html>
"""

@app.route('/', methods=['GET'])
def dashboard():
    """管理面板主页"""
    # 在生产环境中，应该在这里进行更严格的会话/令牌验证
    # 这里我们依赖 GET 参数或 Bearer Header
    auth_header = request.headers.get('Authorization')
    
    # 如果 Web Worker 启动时数据库连接失败，Dashboard 可能会崩溃，这里先做最基本的检查
    if not db_pool:
        try:
            sync_call(init_db_pool())
        except Exception as e:
            return f"<h1>Web Worker 数据库初始化失败</h1><p>Bot 可能仍在尝试连接或配置错误：{e}</p>", 503

    # 允许通过 URL 参数传递密钥 (简单方便，但安全性低)
    url_key = request.args.get('key')
    
    # 优先检查 Bearer Header
    if is_authorized(auth_header):
        return render_template_string(DASHBOARD_HTML, WEB_SECRET_KEY=WEB_SECRET_KEY)
    
    # 其次检查 URL 密钥
    if url_key and url_key == WEB_SECRET_KEY:
        return render_template_string(DASHBOARD_HTML, WEB_SECRET_KEY=WEB_SECRET_KEY)
        
    # 如果认证失败，只显示认证错误信息
    return """
    <h1>信誉系统管理面板</h1>
    <p>访问被拒绝。请使用正确的密钥（通过 URL 参数 <code>?key=YOUR_KEY</code> 或 Bearer 认证 Header）访问。</p>
    <p>密钥: <code>%s</code></p>
    """ % WEB_SECRET_KEY, 401


# --- ASGI 兼容性包装 ---
# 确保 Gunicorn 可以使用 uvicorn worker 来运行 Flask
app = WsgiToAsgi(app)

# Note: Gunicorn/Uvicorn 会通过 exec gunicorn... web:app 调用此处的 app