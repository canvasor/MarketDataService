#!/bin/bash
# NOFX 本地数据服务器启动脚本

cd "$(dirname "$0")"

PID_FILE="server.pid"
LOG_FILE="server.log"

# 检查是否已经在运行
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "服务器已经在运行 (PID: $OLD_PID)"
        echo "使用 ./stop.sh 停止服务器"
        exit 1
    else
        rm -f "$PID_FILE"
    fi
fi

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    pip install pydantic-settings
else
    source venv/bin/activate
fi

# 启动服务器（后台运行）
echo "启动 NOFX 本地数据服务器..."
nohup python main.py > "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo $SERVER_PID > "$PID_FILE"

# 等待服务器启动
sleep 2

# 检查是否启动成功
if ps -p $SERVER_PID > /dev/null 2>&1; then
    echo "✅ 服务器启动成功 (PID: $SERVER_PID)"
    echo ""
    echo "访问地址: http://localhost:30007"
    echo "日志文件: $LOG_FILE"
    echo ""
    echo "使用 ./stop.sh 停止服务器"
    echo "使用 ./status.sh 查看服务器状态"
    echo "使用 tail -f $LOG_FILE 查看实时日志"
else
    echo "❌ 服务器启动失败，请查看日志: $LOG_FILE"
    cat "$LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi
