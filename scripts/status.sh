#!/bin/bash
# NOFX 本地数据服务器状态检查脚本

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PID_FILE="$BASE_DIR/logs/server.pid"
APP_LOG_FILE="$BASE_DIR/logs/market_data_service.log"
RUNTIME_LOG_FILE="$BASE_DIR/logs/runtime.log"

echo "========== NOFX 本地数据服务器状态 =========="
echo ""

if [ ! -f "$PID_FILE" ]; then
    echo "状态: 未运行 (找不到 PID 文件)"
    echo ""
    echo "使用 ./scripts/start.sh 启动服务器"
    exit 1
fi

PID=$(cat "$PID_FILE")

if ps -p "$PID" > /dev/null 2>&1; then
    echo "状态: 运行中"
    echo "PID:  $PID"
    echo ""

    if command -v ss > /dev/null 2>&1; then
        PORT_STATUS=$(ss -tlnp 2>/dev/null | grep ":30007" | head -1 || true)
        if [ -n "$PORT_STATUS" ]; then
            echo "端口: 30007 (监听中)"
        else
            echo "端口: 30007 (未监听，可能启动中...)"
        fi
    fi

    echo ""
    echo "测试 API 连接..."
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:30007/health" 2>/dev/null || true)
    if [ "$HTTP_STATUS" = "200" ]; then
        echo "API:  正常响应"
    else
        echo "API:  响应异常 (HTTP ${HTTP_STATUS:-unknown})"
    fi

    echo ""
    echo "应用日志: $APP_LOG_FILE"
    echo "最近日志:"
    echo "---"
    tail -5 "$APP_LOG_FILE" 2>/dev/null || echo "(无应用日志)"
    echo "---"
    echo "运行输出: $RUNTIME_LOG_FILE"
else
    echo "状态: 进程不存在 (PID: $PID)"
    rm -f "$PID_FILE"
    echo ""
    echo "使用 ./scripts/start.sh 启动服务器"
    exit 1
fi
