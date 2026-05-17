# 多合一工具箱 Web 版 Docker 镜像
FROM python:3.14-slim

LABEL maintainer="Zhang Mingfeng"
LABEL description="多合一工具箱 Web 版"

# 使用阿里云 Debian 镜像加速
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    libfreetype6-dev \
    fonts-wqy-zenhei \
    fonts-wqy-microhei \
    fonts-dejavu-core \
    default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装 Python 依赖（利用 Docker 缓存层）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建运行时需要的目录
RUN mkdir -p backups uploads /var/log && touch /var/log/app.log

# 设置环境变量默认值
ENV FLASK_DEBUG=0
ENV DB_HOST=host.docker.internal
ENV DB_PORT=3306
ENV DB_USER=root
ENV DB_PASSWORD=root@123456
ENV DB_NAME=sample
ENV RATE_GLOBAL_LIMIT=200
ENV RATE_BLOCK_DURATION=10

EXPOSE 4444

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4444/')" || exit 1

# 隐藏 Server 响应头
ENV PYTHONUNBUFFERED=1

CMD ["python3", "-c", "\
import os, atexit, socket, werkzeug.serving; \
from app import app, rate_limiter, _init_plugins; \
atexit.register(rate_limiter.shutdown); \
_init_plugins(); \
werkzeug.serving.WSGIRequestHandler.version_string = lambda self: ''; \
werkzeug.serving.WSGIRequestHandler.sys_version = ''; \
print('=' * 100); \
print('  多合一工具箱 Web 版 (Docker)'); \
print(f'  访问: http://0.0.0.0:4444'); \
print('=' * 100); \
app.run(host='0.0.0.0', port=4444, debug=False, threaded=True) \
"]
