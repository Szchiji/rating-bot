#!/bin/bash

# --- 1. 启动 Bot 服务 (后台) ---
echo "Starting Bot Service..."
# 将 Bot 输出重定向到 bot.log
nohup python bot.py > bot.log 2>&1 &

# --- 2. 数据库就绪检查 (关键修复) ---
# 检查 db_pool 是否已由 bot.py 初始化。我们使用一个循环来等待 Bot 写入日志中的成功信息。
echo "Waiting for database initialization by Bot (max 30s)..."
COUNTER=0
MAX_ATTEMPTS=6 # 检查 6 次，每次 5 秒
READY_FLAG="已启动" # bot.py 中成功启动的标志

while [ $COUNTER -lt $MAX_ATTEMPTS ]; do
    if grep -q "$READY_FLAG" bot.log; then
        echo "Database pool initialized. Bot is running."
        break
    fi
    echo "Waiting 5 seconds..."
    sleep 5
    COUNTER=$((COUNTER + 1))
done

if [ $COUNTER -eq $MAX_ATTEMPTS ]; then
    echo "FATAL: Bot failed to initialize database pool within 30 seconds."
    echo "--- Bot Log Tail ---"
    tail -n 20 bot.log
    echo "----------------------"
    exit 1 # 启动失败，让 Railway 知道
fi

# --- 3. 启动 Web 服务 (前台) ---
echo "Starting Web Service using Uvicorn Worker..."
# 使用 Uvicorn Worker 启动 Gunicorn，以兼容 WsgiToAsgi 包装后的异步 Web 路由
exec gunicorn --workers 4 --bind 0.0.0.0:$PORT --worker-class uvicorn.workers.UvicornWorker web:app