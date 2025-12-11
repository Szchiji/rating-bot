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

# --- 基础 CSS 样式 (增强版：加入数据卡片和人性化细节) ---
BASE_CSS = """
<style>
    /* 基础布局 */
    body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #eef1f5; color: #333; margin: 0; display: flex; min-height: 100vh; }
    #sidebar { width: 220px; background-color: #2c3e50; color: white; padding: 20px 0; box-shadow: 2px 0 10px rgba(0, 0, 0, 0.2); flex-shrink: 0; }
    #sidebar a { display: flex; align-items: center; padding: 12px 20px; text-decoration: none; color: #ecf0f1; border-left: 5px solid transparent; transition: all 0.2s; }
    #sidebar a:hover, #sidebar a.active { background-color: #34495e; border-left: 5px solid #3498db; font-weight: bold; }
    #sidebar h3 { color: #ecf0f1; text-align: center; margin-bottom: 30px; }

    #content { flex-grow: 1; padding: 30px; }
    .container { max-width: 1200px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05); }
    h1 { color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 15px; margin-bottom: 30px; font-weight: 300; }
    h3 { color: #2980b9; margin-top: 0; margin-bottom: 20px; border-bottom: 1px solid #f0f0f0; padding-bottom: 10px; }
    
    .nav-top { text-align: right; margin-bottom: 20px; font-size: 0.9em; }
    .nav-top a { text-decoration: none; color: #e74c3c; font-weight: bold; margin-left: 15px; }

    /* 表单和按钮 */
    input[type="text"], input[type="number"], input[type="password"] { padding: 10px; border: 1px solid #ddd; border-radius: 6px; box-sizing: border-box; transition: border-color 0.3s; }
    input:focus { border-color: #3498db; }
    button, .btn { padding: 10px 18px; background-color: #2ecc71; color: white; border: none; border-radius: 6px; cursor: pointer; transition: background-color 0.3s, transform 0.1s; text-decoration: none; display: inline-block; font-weight: 500;}
    button:hover, .btn:hover { background-color: #27ae60; transform: translateY(-1px); }
    .btn-primary { background-color: #3498db; }
    .btn-primary:hover { background-color: #2980b9; }
    .btn-danger { background-color: #e74c3c; }
    .btn-danger:hover { background-color: #c0392b; }
    .btn-warning { background-color: #f39c12; }
    .btn-warning:hover { background-color: #e67e22; }
    
    /* 警告信息 */
    .alert-success { background-color: #e8f5e9; color: #388e3c; padding: 12px; border-radius: 6px; margin-bottom: 15px; border-left: 5px solid #2ecc71; }
    .alert-error { background-color: #ffebee; color: #d32f2f; padding: 12px; border-radius: 6px; margin-bottom: 15px; border-left: 5px solid #e74c3c; }
    
    /* 表格 */
    table { width: 100%; border-collapse: separate; border-spacing: 0; margin-top: 15px; border-radius: 8px; overflow: hidden; box-shadow: 0 0 10px rgba(0,0,0,0.05); }
    th, td { border-bottom: 1px solid #eee; padding: 15px; text-align: left; }
    th { background-color: #f8f9fa; font-weight: 600; color: #555; }
    tr:last-child td { border-bottom: none; }
    tr:hover { background-color: #f5f5f5; }
    
    /* 操作栏 */
    .action-bar { display: flex; justify-content: space-between; margin-bottom: 25px; align-items: center; padding: 15px; background: #fcfcfc; border-radius: 8px; border: 1px solid #f0f0f0; }
    .form-inline > * { margin-right: 15px; }

    /* Dashboard 卡片样式 */
    .card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-top: 20px; }
    .data-card { background: #fff; padding: 25px; border-radius: 10px; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1); border-left: 5px solid #3498db; transition: transform 0.3s; }
    .data-card:hover { transform: translateY(-5px); }
    .card-title { color: #7f8c8d; font-size: 1em; margin-bottom: 10px; }
    .card-value { font-size: 2.5em; font-weight: 700; color: #2c3e50; }
    .card-icon { float: right; font-size: 2.5em; color: #bdc3c7; }

    /* 登录页面样式 */
    .login-container { max-width: 400px; margin: 100px auto; padding: 40px; background: #fff; border-radius: 10px; box-shadow: 0 8px 30px rgba(0, 0, 0, 0.1); }
</style>
"""

# --- 辅助函数：运行异步代码 (关键函数) ---
def run_async(coro):
    """在一个同步线程中运行异步代码并返回结果"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    if loop.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()
    else:
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
    {