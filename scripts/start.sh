#!/bin/bash
# NOFX 本地数据服务器启动脚本

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$BASE_DIR/logs"
PID_FILE="$LOG_DIR/server.pid"
APP_LOG_FILE="$LOG_DIR/market_data_service.log"
RUNTIME_LOG_FILE="$LOG_DIR/runtime.log"
VENV_DIR=""

mkdir -p "$LOG_DIR"
cd "$BASE_DIR"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "服务器已经在运行 (PID: $OLD_PID)"
        echo "使用 ./scripts/stop.sh 停止服务器"
        exit 1
    else
        rm -f "$PID_FILE"
    fi
fi

if [ -d ".venv" ]; then
    VENV_DIR=".venv"
elif [ -d "venv" ]; then
    VENV_DIR="venv"
else
    VENV_DIR=".venv"
    echo "创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
    pip install -r requirements.txt
    pip install pydantic-settings
fi

source "$VENV_DIR/bin/activate"

echo "启动 NOFX 本地数据服务器..."
nohup python main.py >> "$RUNTIME_LOG_FILE" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"

sleep 2

if ps -p "$SERVER_PID" > /dev/null 2>&1; then
    echo "服务器启动成功 (PID: $SERVER_PID)"
    echo "访问地址: http://127.0.0.1:30007"
    echo "应用日志: $APP_LOG_FILE"
    echo "运行输出: $RUNTIME_LOG_FILE"
    echo "使用 ./scripts/stop.sh 停止服务器"
    echo "使用 ./scripts/status.sh 查看服务器状态"
else
    echo "服务器启动失败，请查看日志:"
    echo "- $APP_LOG_FILE"
    echo "- $RUNTIME_LOG_FILE"
    tail -20 "$RUNTIME_LOG_FILE" 2>/dev/null || true
    rm -f "$PID_FILE"
    exit 1
fi
