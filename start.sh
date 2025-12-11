#!/bin/bash

# 使用 nohup 和 & 在后台启动 Bot 服务
# Bot 必须在 Gunicorn 启动之前启动，以确保 database.py 中的 db_pool 被初始化
# Bot 负责初始化数据库结构
nohup python bot.py &

# 稍等片刻，确保 Bot 进程完成数据库初始化
sleep 5

# 使用 gunicorn 启动 web.py 中的 Flask 应用 (使用 worker 线程处理并发)
# -w 4: 运行 4 个工作进程
# -b 0.0.0.0:$PORT: 绑定到 Railway 提供的端口
# --threads 2: 每个 Worker 使用 2 个线程来处理同步 WSGI 请求
# web:app: 运行 web.py 文件中的 app 变量
exec gunicorn --workers 4 --bind 0.0.0.0:$PORT web:app