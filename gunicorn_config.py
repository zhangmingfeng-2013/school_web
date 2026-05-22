"""
Gunicorn 生产配置 — 多合一工具箱 Web 版
===========================================
架构: Nginx (8080) → Gunicorn gthread workers (127.0.0.1:4444)

并发模型:
  4 个 worker 进程 × 4 个线程/worker = 16 并发连接
  适用于 I/O 密集型 Flask 应用（MySQL 查询、文件 I/O）

环境变量自定义（可选）:
  GUNICORN_WORKERS=4       worker 进程数（建议 = 2 * CPU 核心数）
  GUNICORN_THREADS=4       每 worker 的线程数
  GUNICORN_PORT=4444       监听端口
  GUNICORN_TIMEOUT=60      请求超时（秒）
  GUNICORN_LOG_LEVEL=info  日志级别
"""

import os
import multiprocessing

# ---- 监听 ----
bind = f"127.0.0.1:{os.environ.get('GUNICORN_PORT', '4444')}"

# ---- Worker ----
# gthread: 每个 worker 是独立进程，内部分配线程处理请求
# 最适合 I/O 型 Flask 应用（DB 查询、文件读写）
workers = int(os.environ.get("GUNICORN_WORKERS", "4"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
worker_class = "gthread"

# ---- Worker 重启（防止内存泄漏） ----
# 每个 worker 处理 N 个请求后自动重启，保持长期稳定
max_requests = 1000
max_requests_jitter = 100  # 随机偏移，避免所有 worker 同时重启

# ---- 超时 ----
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "60"))       # 请求处理超时
graceful_timeout = 30  # 平滑关闭等待
keepalive = 5           # Nginx upstream keepalive 配合

# ---- 进程管理 ----
# 应用启动前预加载（节省内存，但需注意全局状态）
# 此 Flask 应用有模块级全局状态（rate_config, _db_init_done 等），
# preload 会导致所有 worker 共享同一内存 → 状态不一致
preload_app = False

# 每 worker 启动时执行的钩子
def post_worker_init(worker):
    """Worker 启动完成后记录"""
    worker.log.info(f"Worker {worker.pid} 已就绪")

# 日志
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
accesslog = "/opt/homebrew/var/log/gunicorn_access.log"
errorlog = "/opt/homebrew/var/log/gunicorn_error.log"

# access log 格式（含请求耗时）
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)sμs'

# ---- 守护进程 ----
# 不在此配置中 daemonize（由启动脚本 systemd/launchd 管理）
daemon = False

# PID 文件（用于管理进程）
pidfile = "/tmp/gunicorn_school_web.pid"

# ---- 进程命名 ----
proc_name = "school_web"

# ---- 预启动检查（可选） ----
def on_starting(server):
    """Gunicorn 启动前验证"""
    server.log.info("=" * 60)
    server.log.info(f"多合一工具箱 Web 版 — Gunicorn 启动")
    server.log.info(f"  Workers: {workers} × {threads} threads = {workers * threads} 并发")
    server.log.info(f"  Listen:  {bind}")
    server.log.info(f"  Timeout: {timeout}s")
    server.log.info("=" * 60)
