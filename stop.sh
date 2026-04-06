#!/bin/bash
# NOFX 本地数据服务器停止脚本

cd "$(dirname "$0")"

PID_FILE="server.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "服务器未运行 (找不到 PID 文件)"
    exit 0
fi

PID=$(cat "$PID_FILE")

if ps -p "$PID" > /dev/null 2>&1; then
    echo "正在停止服务器 (PID: $PID)..."
    kill "$PID"

    # 等待进程退出
    for i in {1..10}; do
        if ! ps -p "$PID" > /dev/null 2>&1; then
            break
        fi
        sleep 0.5
    done

    # 如果还没退出，强制杀死
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "进程未响应，强制终止..."
        kill -9 "$PID"
    fi

    rm -f "$PID_FILE"
    echo "✅ 服务器已停止"
else
    echo "服务器进程不存在 (PID: $PID)"
    rm -f "$PID_FILE"
fi
