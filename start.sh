#!/bin/bash

# 使用 nohup 和 & 在后台启动 Bot 服务
# Bot 必须在 Gunicorn 启动之前启动，以确保 database.py 中的 db_pool 被初始化
# Bot 负责初始化数据库结构
nohup python bot.py &

# 稍等片刻，确保 Bot 进程完成数据库初始化
sleep 5

# 关键修复: 使用 Uvicorn Worker 启动 Gunicorn，让它能够正确处理 ASGI 接口 (即 WsgiToAsgi 包装后的应用)
# -k uvicorn.workers.UvicornWorker: 指定 Uvicorn Worker 类型
# -w 4: 运行 4 个工作进程
# -b 0.0.0.0:$PORT: 绑定到 Railway 提供的端口
# web:app: 运行 web.py 文件中的 app 变量 (它是 WsgiToAsgi 包装后的 ASGI 应用)
exec gunicorn --workers 4 --bind 0.0.0.0:$PORT --worker-class uvicorn.workers.UvicornWorker web:app