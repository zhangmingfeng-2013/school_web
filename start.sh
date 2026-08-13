#!/bin/bash
# ============================================================
# School_Web 一键启动脚本
# 自动启动: MySQL → Flask 应用 → Cloudflare 隧道（外网访问）
#
# 用法:
#   ./start.sh          # 启动全部服务（前台运行，Ctrl+C 停止）
#   ./start.sh stop     # 停止全部服务
#   ./start.sh restart  # 重启全部服务
#   ./start.sh status   # 查看运行状态
# ============================================================

# ---- 清理环境变量（避免 IDE/TRAE 污染 Python 解释器） ----
unset PYTHONHOME PYTHONPATH

# ---- 配置（可通过环境变量覆盖） ----
PYTHON="${PYTHON:-/Library/Frameworks/Python.framework/Versions/3.14/bin/python3}"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PORT="${APP_PORT:-4444}"
MYSQL_DATADIR="${MYSQL_DATADIR:-/opt/homebrew/var/mysql}"
DB_PASSWORD="${DB_PASSWORD:-root@123456}"
DB_USER="${DB_USER:-root}"
DB_NAME="${DB_NAME:-sample}"
if [ -z "${ADMIN_SECRET}" ]; then
    ADMIN_SECRET="asdfghjkl;'"
fi
MAX_WAIT=30

# ---- 运行时文件 ----
RUN_DIR="/tmp/school_web"
mkdir -p "$RUN_DIR"
MYSQL_PID_FILE="$RUN_DIR/mysql.pid"
APP_PID_FILE="$RUN_DIR/app.pid"
TUNNEL_PID_FILE="$RUN_DIR/tunnel.pid"
MYSQL_LOG="$RUN_DIR/mysql.log"
APP_LOG="$RUN_DIR/app.log"
TUNNEL_LOG="$RUN_DIR/tunnel.log"
TUNNEL_URL_FILE="$RUN_DIR/tunnel_url.txt"

# ---- 颜色输出 ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; }

# ---- 工具函数 ----
check_cmd() { command -v "$1" >/dev/null 2>&1; }

get_lan_ip() {
    ipconfig getifaddr en0 2>/dev/null \
        || ipconfig getifaddr en1 2>/dev/null \
        || echo "127.0.0.1"
}

# ---- CJK 对齐工具 ----
# 计算字符串在终端中的显示宽度（中日韩字符占 2 列，ANSI 控制码占 0 列）
str_width() {
    printf '%s' "$1" | perl -CSD -e '
        my $s = join("", <>);
        $s =~ s/\e\[[0-9;]*m//g;   # 去除 ANSI 颜色码
        my $w = 0;
        for my $c (split //, $s) {
            $w += ($c =~ /[\x{1100}-\x{115f}\x{2e80}-\x{303e}\x{3040}-\x{33ff}\x{3400}-\x{4dbf}\x{4e00}-\x{9fff}\x{a000}-\x{a4cf}\x{ac00}-\x{d7a3}\x{f900}-\x{faff}\x{fe30}-\x{fe4f}\x{ff00}-\x{ff60}\x{ffe0}-\x{ffe6}]/) ? 2 : 1;
        }
        print $w;
    ' 2>/dev/null || echo "${#1}"
}

# 重复字符 n 次
repeat_str() {
    local char="$1" n="$2" out="" i
    for ((i=0; i<n; i++)); do out+="$char"; done
    printf '%s' "$out"
}

# 输出带边框的行（自动 CJK 对齐）
# 用法: box_line "内容" 内宽 [左缩进]
box_line() {
    local content="$1" w="$2" indent="${3:-0}"
    local cw
    cw=$(str_width "$content")
    local rp=$((w - indent - cw))
    [ $rp -lt 0 ] && rp=0
    printf '║%s%s%s║' \
        "$(repeat_str ' ' "$indent")" "$content" "$(repeat_str ' ' "$rp")"
}

# ============================================================
# MySQL
# ============================================================
start_mysql() {
    # 已在运行？
    if mysqladmin ping -u "$DB_USER" -p"$DB_PASSWORD" --silent 2>/dev/null; then
        ok "MySQL 已在运行"
        return 0
    fi

    if ! check_cmd mysqld; then
        fail "未找到 mysqld，请先安装 MySQL: brew install mysql@8.4"
        return 1
    fi

    info "启动 MySQL..."
    nohup mysqld \
        --user="$(whoami)" \
        --datadir="$MYSQL_DATADIR" \
        > "$MYSQL_LOG" 2>&1 &
    local pid=$!
    echo "$pid" > "$MYSQL_PID_FILE"

    # 等待就绪
    local waited=0
    while ! mysqladmin ping -u "$DB_USER" -p"$DB_PASSWORD" --silent 2>/dev/null; do
        sleep 1
        waited=$((waited + 1))
        if [ $waited -ge $MAX_WAIT ]; then
            fail "MySQL 启动超时（${MAX_WAIT}s），日志: $MYSQL_LOG"
            return 1
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            fail "MySQL 进程已退出，日志: $MYSQL_LOG"
            return 1
        fi
    done

    # 确保数据库存在
    mysql -u "$DB_USER" -p"$DB_PASSWORD" \
        -e "CREATE DATABASE IF NOT EXISTS \`$DB_NAME\`;" 2>/dev/null

    ok "MySQL 已启动 (PID: $pid)"
}

# ============================================================
# Flask 应用
# ============================================================
start_app() {
    # 已在运行？
    if curl -sf -o /dev/null "http://127.0.0.1:$APP_PORT/" 2>/dev/null; then
        local existing_pid
        existing_pid=$(pgrep -f "app\.py" 2>/dev/null | head -1)
        if [ -z "$existing_pid" ]; then
            # 回退：查找端口上的 Python 进程（排除 Docker 等）
            for p in $(lsof -tiTCP:"$APP_PORT" -sTCP:LISTEN 2>/dev/null); do
                if ps -p "$p" -o comm= 2>/dev/null | grep -qi python; then
                    existing_pid="$p"
                    break
                fi
            done
        fi
        if [ -n "$existing_pid" ]; then
            echo "$existing_pid" > "$APP_PID_FILE"
            ok "Flask 应用已在运行 (PID: $existing_pid)"
            return 0
        fi
    fi

    if [ ! -x "$PYTHON" ]; then
        fail "未找到 Python: $PYTHON"
        return 1
    fi

    # 检查依赖
    if ! "$PYTHON" -c "import flask, pymysql, waitress, PIL, psutil" 2>/dev/null; then
        fail "Python 依赖缺失，请运行: pip install -r requirements.txt"
        return 1
    fi

    # 预清理端口（排除非 Python 进程占用，如 Docker）
    local port_pids
    port_pids=$(lsof -tiTCP:"$APP_PORT" -sTCP:LISTEN 2>/dev/null)
    if [ -n "$port_pids" ]; then
        for p in $port_pids; do
            if ! ps -p "$p" -o comm= 2>/dev/null | grep -qi python; then
                warn "端口 $APP_PORT 被非 Python 进程占用 (PID: $p)，正在清理..."
                kill -TERM "$p" 2>/dev/null
                sleep 2
                kill -0 "$p" 2>/dev/null && kill -KILL "$p" 2>/dev/null
            fi
        done
        sleep 1
    fi

    info "启动 Flask 应用 (端口: $APP_PORT)..."
    cd "$PROJECT_DIR"
    ADMIN_SECRET="$ADMIN_SECRET" \
    DB_PASSWORD="$DB_PASSWORD" \
    DB_USER="$DB_USER" \
    DB_NAME="$DB_NAME" \
    nohup "$PYTHON" app.py > "$APP_LOG" 2>&1 &
    local pid=$!
    echo "$pid" > "$APP_PID_FILE"

    # 等待就绪
    local waited=0
    while ! curl -sf -o /dev/null "http://127.0.0.1:$APP_PORT/" 2>/dev/null; do
        sleep 1
        waited=$((waited + 1))
        if [ $waited -ge $MAX_WAIT ]; then
            fail "Flask 应用启动超时（${MAX_WAIT}s），日志: $APP_LOG"
            return 1
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            fail "Flask 应用进程已退出，日志: $APP_LOG"
            return 1
        fi
    done

    ok "Flask 应用已启动 (PID: $pid, 端口: $APP_PORT)"
}

# ============================================================
# Cloudflare 隧道
# ============================================================
start_tunnel() {
    if ! check_cmd cloudflared; then
        fail "未找到 cloudflared，请安装: brew install cloudflared"
        return 1
    fi

    # 已在运行？
    if [ -f "$TUNNEL_PID_FILE" ] && \
       kill -0 "$(cat "$TUNNEL_PID_FILE" 2>/dev/null)" 2>/dev/null; then
        ok "Cloudflare 隧道已在运行 (PID: $(cat "$TUNNEL_PID_FILE"))"
        return 0
    fi

    # 清理残留的 cloudflared 进程（避免多个隧道同时运行）
    local orphan_pids
    orphan_pids=$(pgrep -f 'cloudflared.*tunnel.*--url' 2>/dev/null)
    if [ -n "$orphan_pids" ]; then
        warn "发现残留 cloudflared 进程 (PID: $(echo "$orphan_pids" | tr '\n' ' '))，正在清理..."
        echo "$orphan_pids" | while read -r opid; do
            kill -TERM "$opid" 2>/dev/null
        done
        sleep 2
    fi

    info "启动 Cloudflare 隧道..."
    nohup cloudflared tunnel --url "http://localhost:$APP_PORT" \
        > "$TUNNEL_LOG" 2>&1 &
    local pid=$!
    echo "$pid" > "$TUNNEL_PID_FILE"

    # 等待隧道 URL 出现
    local waited=0
    local url=""
    while [ -z "$url" ]; do
        sleep 1
        waited=$((waited + 1))
        url=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' \
            "$TUNNEL_LOG" 2>/dev/null | head -1)
        if [ $waited -ge $MAX_WAIT ]; then
            fail "Cloudflare 隧道启动超时（${MAX_WAIT}s），日志: $TUNNEL_LOG"
            return 1
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            fail "Cloudflare 隧道进程已退出，日志: $TUNNEL_LOG"
            return 1
        fi
    done

    echo "$url" > "$TUNNEL_URL_FILE"
    ok "Cloudflare 隧道已建立 (PID: $pid)"
}

# ============================================================
# 停止
# ============================================================
stop_service() {
    local name="$1" pid_file="$2"
    local pid

    [ -f "$pid_file" ] || return 0
    pid=$(cat "$pid_file" 2>/dev/null)
    rm -f "$pid_file"

    [ -n "$pid" ] || return 0
    if kill -0 "$pid" 2>/dev/null; then
        info "停止 $name (PID: $pid)..."
        kill -TERM "$pid" 2>/dev/null
        local waited=0
        while kill -0 "$pid" 2>/dev/null && [ $waited -lt 10 ]; do
            sleep 1
            waited=$((waited + 1))
        done
        if kill -0 "$pid" 2>/dev/null; then
            kill -KILL "$pid" 2>/dev/null
            sleep 1
        fi
        ok "$name 已停止"
    else
        warn "$name 进程不存在 (PID: $pid)"
    fi
}

stop_all() {
    echo ""
    stop_service "Cloudflare 隧道" "$TUNNEL_PID_FILE"
    stop_service "Flask 应用"    "$APP_PID_FILE"
    stop_service "MySQL"         "$MYSQL_PID_FILE"
    rm -f "$TUNNEL_URL_FILE"
    ok "全部服务已停止"
}

# ============================================================
# 状态
# ============================================================
show_status() {
    local bw=42
    echo ""
    echo -e "${BOLD}╔$(repeat_str '═' $bw)╗${NC}"
    echo -e "${BOLD}$(box_line 'School_Web 服务状态' $bw 7)${NC}"
    echo -e "${BOLD}╚$(repeat_str '═' $bw)╝${NC}"
    echo ""

    # MySQL
    if mysqladmin ping -u "$DB_USER" -p"$DB_PASSWORD" --silent 2>/dev/null; then
        ok "MySQL          运行中"
    else
        fail "MySQL          未运行"
    fi

    # Flask
    if curl -sf -o /dev/null "http://127.0.0.1:$APP_PORT/" 2>/dev/null; then
        local app_pid
        app_pid=$(pgrep -f "app\.py" 2>/dev/null | head -1)
        if [ -z "$app_pid" ]; then
            app_pid=$(cat "$APP_PID_FILE" 2>/dev/null)
        fi
        ok "Flask 应用     运行中 (PID: ${app_pid:-?}, 端口: $APP_PORT)"
    else
        fail "Flask 应用     未运行"
    fi

    # Cloudflare
    local tunnel_pid=""
    [ -f "$TUNNEL_PID_FILE" ] && tunnel_pid=$(cat "$TUNNEL_PID_FILE" 2>/dev/null)
    if [ -n "$tunnel_pid" ] && kill -0 "$tunnel_pid" 2>/dev/null; then
        ok "Cloudflare 隧道 运行中 (PID: $tunnel_pid)"
        if [ -f "$TUNNEL_URL_FILE" ]; then
            echo -e "                外网地址: ${CYAN}$(cat "$TUNNEL_URL_FILE")${NC}"
        fi
    else
        fail "Cloudflare 隧道 未运行"
    fi

    echo ""
}

# ============================================================
# 输出地址
# ============================================================
show_urls() {
    local lan_ip tunnel_url bw=56
    lan_ip=$(get_lan_ip)
    [ -f "$TUNNEL_URL_FILE" ] && tunnel_url=$(cat "$TUNNEL_URL_FILE")

    echo ""
    echo -e "${GREEN}╔$(repeat_str '═' $bw)╗${NC}"
    echo -e "${GREEN}$(box_line '>> School_Web 启动成功！' $bw 10)${NC}"
    echo -e "${GREEN}╚$(repeat_str '═' $bw)╝${NC}"
    echo ""
    echo -e "  ${BOLD}外网地址 (HTTPS)${NC}:"
    echo -e "    ${CYAN}${tunnel_url:-（未获取到隧道地址）}${NC}"
    echo ""
    echo -e "  ${BOLD}本地地址${NC}:"
    echo -e "    http://127.0.0.1:${APP_PORT}"
    echo ""
    echo -e "  ${BOLD}局域网地址${NC}:"
    echo -e "    http://${lan_ip}:${APP_PORT}"
    echo ""
    echo -e "  ${BOLD}管理员注册密钥${NC}: ${YELLOW}${ADMIN_SECRET}${NC}"
    echo ""
    echo -e "  ${BOLD}日志文件${NC}:"
    echo -e "    MySQL:    $MYSQL_LOG"
    echo -e "    Flask:    $APP_LOG"
    echo -e "    隧道:     $TUNNEL_LOG"
    echo ""
    echo -e "  按 ${BOLD}Ctrl+C${NC} 停止全部服务"
    echo -e "${GREEN}╚$(repeat_str '═' $bw)╝${NC}"
    echo ""
}

# ============================================================
# 主逻辑
# ============================================================
do_start() {
    local bw=42
    echo ""
    echo -e "${BOLD}╔$(repeat_str '═' $bw)╗${NC}"
    echo -e "${BOLD}$(box_line 'School_Web 一键启动' $bw 7)${NC}"
    echo -e "${BOLD}╚$(repeat_str '═' $bw)╝${NC}"
    echo ""

    start_mysql  || { fail "MySQL 启动失败，中止"; exit 1; }
    start_app    || { fail "Flask 应用启动失败，中止"; exit 1; }
    start_tunnel || warn "Cloudflare 隧道启动失败，外网暂不可用（本地仍可访问）"

    show_urls

    # 前台驻留，Ctrl+C 退出
    info "服务运行中，按 Ctrl+C 停止..."
    trap 'echo ""; stop_all; exit 0' INT TERM
    while true; do
        sleep 10
        if ! curl -sf -o /dev/null "http://127.0.0.1:$APP_PORT/" 2>/dev/null; then
            warn "Flask 应用无响应，请检查日志: $APP_LOG"
        fi
    done
}

case "${1:-start}" in
    start)   do_start ;;
    stop)    stop_all ;;
    restart) warn "重启全部服务..."; stop_all; sleep 2; do_start ;;
    status)  show_status ;;
    *)
        echo "用法: $0 {start|stop|restart|status}"
        echo ""
        echo "  start    启动全部服务（MySQL + Flask + Cloudflare 隧道）"
        echo "  stop     停止全部服务"
        echo "  restart  重启全部服务"
        echo "  status   查看运行状态"
        exit 1
        ;;
esac
