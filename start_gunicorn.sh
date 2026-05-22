#!/bin/bash
# ============================================================
# 多合一工具箱 Web 版 — Gunicorn 启动脚本
# 用法: ./start_gunicorn.sh         # 前台运行（调试）
#       ./start_gunicorn.sh -d      # 后台守护进程
#       ./start_gunicorn.sh stop    # 停止
#       ./start_gunicorn.sh restart # 重启
#       ./start_gunicorn.sh status  # 查看状态
# ============================================================

set -e

cd "$(dirname "$0")"

# ---- Python 环境 ----
# 使用裸金属 Python 3.14（已安装所有依赖）
PYTHON="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
GUNICORN="/Library/Frameworks/Python.framework/Versions/3.14/bin/gunicorn"
PID_FILE="/tmp/gunicorn_school_web.pid"

# ---- 环境变量 ----
export FLASK_DEBUG="${FLASK_DEBUG:-0}"

# ---- 函数 ----
check_already_running() {
    if [ -f "$PID_FILE" ]; then
        local pid
        pid="$(cat "$PID_FILE" 2>/dev/null)"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            return 0  # 正在运行
        fi
    fi
    # 也检查是否有残留进程
    local pids
    pids=$(pgrep -f "gunicorn.*school_web" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "⚠️  发现残留 Gunicorn 进程: $pids"
        return 1
    fi
    return 1
}

do_start() {
    local daemon_flag=""
    if [ "$1" = "-d" ]; then
        daemon_flag="--daemon"
    fi

    if check_already_running; then
        echo "❌ Gunicorn 已在运行中 (PID: $(cat "$PID_FILE" 2>/dev/null))"
        echo "   如需重启: $0 restart"
        return 1
    fi

    # 确保日志目录存在
    mkdir -p /opt/homebrew/var/log

    echo "🚀 启动 Gunicorn..."
    cd /Users/zhangmingfeng/School_Web

    exec "$GUNICORN" \
        --config gunicorn_config.py \
        $daemon_flag \
        app:app
}

do_stop() {
    if [ -f "$PID_FILE" ]; then
        local pid
        pid="$(cat "$PID_FILE")"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "🛑 停止 Gunicorn (PID: $pid)..."
            # 发送 TERM → 等待 graceful_timeout → KILL
            kill -TERM "$pid" 2>/dev/null || true

            # 等待进程退出（最多 35 秒 = timeout + 5s margin）
            local waited=0
            while kill -0 "$pid" 2>/dev/null && [ $waited -lt 35 ]; do
                sleep 1
                waited=$((waited + 1))
            done

            if kill -0 "$pid" 2>/dev/null; then
                echo "⚠️  强制终止..."
                kill -KILL "$pid" 2>/dev/null || true
            fi
            rm -f "$PID_FILE"
            echo "✅ Gunicorn 已停止"
        else
            rm -f "$PID_FILE"
            echo "⚠️  PID 文件存在但进程已不存在，已清理"
        fi
    else
        # 尽力清理残留
        local pids
        pids=$(pgrep -f "gunicorn.*school_web" 2>/dev/null || true)
        if [ -n "$pids" ]; then
            echo "🛑 清理残留 Gunicorn 进程: $pids"
            echo "$pids" | xargs kill -TERM 2>/dev/null || true
            sleep 2
        else
            echo "ℹ️  未发现运行中的 Gunicorn"
        fi
    fi
}

do_status() {
    if [ -f "$PID_FILE" ]; then
        local pid
        pid="$(cat "$PID_FILE")"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "✅ Gunicorn 运行中 (PID: $pid)"
            # 显示 worker 进程
            echo ""
            ps aux | grep "gunicorn.*school_web" | grep -v grep || true
        else
            echo "❌ PID 文件存在但进程已退出"
        fi
    else
        local pids
        pids=$(pgrep -f "gunicorn.*school_web" 2>/dev/null || true)
        if [ -n "$pids" ]; then
            echo "⚠️  无 PID 文件，但发现运行中的进程:"
            echo "$pids"
        else
            echo "❌ Gunicorn 未运行"
        fi
    fi
}

# ---- 主逻辑 ----
case "${1:-start}" in
    -d|daemon)
        do_start -d
        sleep 1
        do_status
        ;;
    start)
        # 前台模式：先尝试后台启动，稍后检查
        do_start -d
        sleep 2
        do_status
        ;;
    stop)
        do_stop
        ;;
    restart)
        echo "🔄 重启 Gunicorn..."
        do_stop
        sleep 2
        do_start -d
        sleep 2
        do_status
        ;;
    status)
        do_status
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status}"
        echo "  start    后台启动"
        echo "  stop     停止"
        echo "  restart  重启"
        echo "  status   查看状态"
        exit 1
        ;;
esac
