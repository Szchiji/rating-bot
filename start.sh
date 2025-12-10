#!/bin/bash

# 后台启动机器人
python bot.py &

# 前台启动网站 (Gunicorn)，绑定到 Railway 提供的 $PORT 变量
gunicorn web:app --bind 0.0.0.0:$PORT