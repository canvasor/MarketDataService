#!/bin/bash
# NOFX 本地数据服务器状态检查脚本

cd "$(dirname "$0")"

PID_FILE="server.pid"
LOG_FILE="server.log"

echo "========== NOFX 本地数据服务器状态 =========="
echo ""

# 检查 PID 文件
if [ ! -f "$PID_FILE" ]; then
    echo "状态: ❌ 未运行 (找不到 PID 文件)"
    echo ""
    echo "使用 ./start.sh 启动服务器"
    exit 1
fi

PID=$(cat "$PID_FILE")

# 检查进程是否存在
if ps -p "$PID" > /dev/null 2>&1; then
    echo "状态: ✅ 运行中"
    echo "PID:  $PID"
    echo ""

    # 检查端口
    if command -v ss &> /dev/null; then
        PORT_STATUS=$(ss -tlnp 2>/dev/null | grep ":30007" | head -1)
        if [ -n "$PORT_STATUS" ]; then
            echo "端口: 30007 (监听中)"
        else
            echo "端口: 30007 (未监听，可能启动中...)"
        fi
    fi

    # 测试 API
    echo ""
    echo "测试 API 连接..."
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:30007/health" 2>/dev/null)
    if [ "$HTTP_STATUS" = "200" ]; then
        echo "API:  ✅ 正常响应"
    else
        echo "API:  ⚠️  响应异常 (HTTP $HTTP_STATUS)"
    fi

    echo ""
    echo "日志文件: $LOG_FILE"
    echo "最近日志:"
    echo "---"
    tail -5 "$LOG_FILE" 2>/dev/null || echo "(无日志)"
    echo "---"
else
    echo "状态: ❌ 进程不存在 (PID: $PID)"
    rm -f "$PID_FILE"
    echo ""
    echo "使用 ./start.sh 启动服务器"
    exit 1
fi
