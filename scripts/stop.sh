#!/bin/bash
# NOFX 本地数据服务器停止脚本

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PID_FILE="$BASE_DIR/logs/server.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "服务器未运行 (找不到 PID 文件)"
    exit 0
fi

PID=$(cat "$PID_FILE")

if ps -p "$PID" > /dev/null 2>&1; then
    echo "正在停止服务器 (PID: $PID)..."
    kill "$PID"

    for _ in {1..10}; do
        if ! ps -p "$PID" > /dev/null 2>&1; then
            break
        fi
        sleep 0.5
    done

    if ps -p "$PID" > /dev/null 2>&1; then
        echo "进程未响应，强制终止..."
        kill -9 "$PID"
    fi

    rm -f "$PID_FILE"
    echo "服务器已停止"
else
    echo "服务器进程不存在 (PID: $PID)"
    rm -f "$PID_FILE"
fi
