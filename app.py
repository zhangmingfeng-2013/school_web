import os
import re
import uuid
import json
import time
import random
import hmac
import threading
import psutil
import platform
import socket
import requests
import datetime
import fnmatch
import pymysql
from collections import deque
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import io
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, send_from_directory, send_file, abort, Response, g,
    render_template_string, make_response,
)
from flask_cors import CORS
from i18n import _, detect_lang, get_supported_langs, SUPPORTED_LANGS


# ---------- 简易内存速率限制 ----------
class RateLimiter:
    """简易内存速率限制（文件持久化，重启不丢失）"""

    def __init__(self, persist_file=None):
        self._lock = threading.Lock()
        self._buckets = {}  # {(ip, route): [ts, ...]}
        self._persist_file = persist_file
        self._save_timer = None
        # 加载历史数据
        if persist_file:
            self._load()

    def check(self, key, max_requests=10, window=60):
        """检查 key 是否超过限制，返回 True=允许, False=拒绝"""
        now = time.time()
        cutoff = now - window
        with self._lock:
            hits = self._buckets.get(key, [])
            # 清理过期记录
            hits = [t for t in hits if t > cutoff]
            if len(hits) >= max_requests:
                self._buckets[key] = hits
                return False
            hits.append(now)
            self._buckets[key] = hits
            self._schedule_save()
            return True

    def _schedule_save(self):
        """去抖保存：延迟 2 秒保存，多次 rapid 调用合并"""
        if not self._persist_file:
            return
        if self._save_timer:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(2.0, self._save)
        self._save_timer.start()

    def _load(self):
        """从文件加载持久化状态"""
        try:
            if os.path.exists(self._persist_file):
                with open(self._persist_file, "r") as f:
                    raw = json.load(f)
                now = time.time()
                # 只保留 65 秒内的记录（最大窗口 60s + 5s 缓冲）
                max_age = 65
                loaded = 0
                with self._lock:
                    for k, timestamps in raw.items():
                        parts = k.split("|", 1)
                        if len(parts) == 2:
                            key = tuple(parts)
                        else:
                            key = (k, "")
                        fresh = [t for t in timestamps if now - t < max_age]
                        if fresh:
                            self._buckets[key] = fresh
                            loaded += 1
                if loaded:
                    print(f"  速率限制: 从文件加载了 {loaded} 条记录")
        except Exception as e:
            print(f"  加载速率限制状态失败: {e}")

    def _save(self):
        """将当前状态保存到文件"""
        if not self._persist_file:
            return
        try:
            with self._lock:
                out = {}
                for k, timestamps in list(self._buckets.items()):
                    key_str = "|".join(k)
                    out[key_str] = timestamps
            with open(self._persist_file, "w") as f:
                json.dump(out, f)
        except Exception:
            pass

    def shutdown(self):
        """优雅关闭，强制保存"""
        if self._save_timer:
            self._save_timer.cancel()
        self._save()


rate_limiter = RateLimiter(persist_file=os.path.join(os.path.dirname(__file__), "rate_limiter.json"))
import plugins

app = Flask(__name__)

# ---------- 持久化 Secret Key ----------
SECRET_KEY_FILE = os.path.join(os.path.dirname(__file__), ".secret_key")
if os.path.exists(SECRET_KEY_FILE):
    with open(SECRET_KEY_FILE, "r") as f:
        app.secret_key = f.read().strip()
else:
    app.secret_key = os.urandom(64).hex()
    with open(SECRET_KEY_FILE, "w") as f:
        f.write(app.secret_key)

CORS(app, supports_credentials=True, origins=['http://localhost:3000', 'http://192.168.3.204:3000'])

# ---------- Session 安全设置 ----------
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=bool(os.environ.get("HTTPS")),  # 生产 HTTPS 环境自动启用 Secure；HTTP 内网环境设为 False
    PERMANENT_SESSION_LIFETIME=datetime.timedelta(hours=2),
)

# ---------- 安全工具 User-Agent 过滤 ----------
_BLOCKED_UAS = [
    "sqlmap", "nikto", "nessus", "nmap", "acunetix", "burpsuite",
    "dirbuster", "openvas", "hydra", "amass", "gobuster", "wpscan",
    "zgrab", "masscan", "whatweb", "httprint", "jaeles"
]


@app.before_request
def block_security_scanners():
    """拦截常见安全扫描工具的 UA"""
    ua = request.headers.get("User-Agent", "").lower()
    for blocked in _BLOCKED_UAS:
        if blocked in ua:
            return Response("", status=403)


@app.before_request
def set_csp_nonce():
    """为每个请求生成 CSP nonce"""
    g.csp_nonce = os.urandom(16).hex()


# ---------- 多语言支持 ----------
@app.before_request
def set_language():
    """检测并设置当前请求的语言"""
    lang = detect_lang(request, session)
    session["lang"] = lang
    # 如果用户已登录，持久化语言偏好到数据库
    if session.get("username"):
        _save_user_lang(session["username"], lang)


@app.context_processor
def inject_csp_nonce():
    """注入 CSP nonce 到所有模板上下文"""
    return {"csp_nonce": getattr(g, "csp_nonce", "")}


@app.context_processor
def inject_i18n():
    """将翻译函数和语言信息注入所有模板"""
    lang = session.get("lang", "zh-CN")
    perm = session.get("permission", "guest")
    return {
        "_": lambda key, default=None, **kw: _(key, lang, default, **kw),
        "lang": lang,
        "supported_langs": get_supported_langs(),
        "lang_name": lambda l: _(f"_name", l) if l in SUPPORTED_LANGS else l,
        "plugin_menu_items": plugins.get_menu_items(perm),
        "plugin_footer_blocks": plugins.get_template_blocks("footer"),
        "plugin_head_blocks": plugins.get_template_blocks("head"),
    }


def _save_user_lang(username, lang):
    """持久化用户语言偏好到数据库"""
    try:
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE user_profiles SET lang=%s WHERE username=%s",
                (lang, username)
            )
            conn.commit()
            cursor.close()
            conn.close()
    except Exception:
        pass


@app.route("/api/lang/switch", methods=["POST"])
def api_lang_switch():
    """切换语言"""
    data = request.get_json(silent=True) or {}
    lang = data.get("lang")
    # 类型校验：必须是字符串
    if not isinstance(lang, str):
        return jsonify({"ok": False, "error": "lang must be a string"}), 400
    lang = lang.strip()
    if lang in SUPPORTED_LANGS:
        session["lang"] = lang
        resp = jsonify({"ok": True, "lang": lang})
        resp.set_cookie("lang", lang, max_age=365*24*3600, httponly=False)
        return resp
    return jsonify({"ok": False, "error": "Unsupported language"}), 400

# ---------- 数据库初始化 ----------
_db_init_done = False
def _init_db_once():
    global _db_init_done
    if not _db_init_done:
        _db_init_done = True
        _init_reset_table()
        _init_marketplace_table()


def _init_reset_table():
    """确保 password_reset_tokens 和 user_profiles 表存在"""
    conn = get_db()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                token VARCHAR(32) NOT NULL UNIQUE,
                used TINYINT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                username VARCHAR(50) PRIMARY KEY,
                nickname VARCHAR(50),
                bio TEXT,
                phone VARCHAR(20),
                email VARCHAR(100),
                birthday DATE,
                lang VARCHAR(10) DEFAULT 'zh-CN',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                action VARCHAR(50) NOT NULL,
                points INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_activity_user (username),
                INDEX idx_activity_time (created_at)
            )
        """)
        # 确保 lang 列存在（兼容旧表）
        try:
            cursor.execute("ALTER TABLE user_profiles ADD COLUMN lang VARCHAR(10) DEFAULT 'zh-CN'")
            conn.commit()
        except Exception:
            pass
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admin_requests (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL UNIQUE,
                status VARCHAR(20) DEFAULT 'pending',
                score INT DEFAULT 0,
                requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_by VARCHAR(50),
                reviewed_at TIMESTAMP NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                title VARCHAR(200) NOT NULL,
                description TEXT,
                event_date DATE NOT NULL,
                event_time TIME,
                category VARCHAR(20) DEFAULT 'other',
                color VARCHAR(7) DEFAULT '#3b82f6',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_cal_user (username),
                INDEX idx_cal_date (event_date)
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
    except pymysql.MySQLError:
        pass


def _init_marketplace_table():
    """确保 plugin_marketplace 表存在 — 管理员上传的 HTML/Vue 插件"""
    conn = get_db()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS plugin_marketplace (
                id INT AUTO_INCREMENT PRIMARY KEY,
                plugin_name VARCHAR(100) NOT NULL UNIQUE,
                display_name VARCHAR(200) NOT NULL,
                description TEXT,
                version VARCHAR(20) DEFAULT '1.0.0',
                author VARCHAR(100) DEFAULT '',
                file_type ENUM('html', 'vue') NOT NULL DEFAULT 'html',
                icon VARCHAR(10) DEFAULT '🧩',
                uploader VARCHAR(50) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
    except pymysql.MySQLError:
        pass


# ---------- IP 访问限制 ----------
# ---------- 速率限制配置（持久化到文件，可在管理后台动态修改） ----------
RATE_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "rate_config.json")

DEFAULT_RATE_CONFIG = {
    "RATE_LIMIT": 40,         # 最大请求数
    "RATE_WINDOW": 10,        # 时间窗口（秒）
    "BLOCK_DURATION": 240,    # 封禁时长（秒）
    "BLOCK_PROBE_LIMIT": 50, # 封禁期间试探次数阈值
    "BLOCK_EXTEND": 240,      # 试探超限后追加封禁（秒）
}

def _load_rate_config():
    """从文件加载速率配置，失败则使用默认值"""
    if os.path.exists(RATE_CONFIG_FILE):
        try:
            with open(RATE_CONFIG_FILE, "r") as f:
                saved = json.load(f)
            # 合并：保留默认值作为回退，覆盖已保存的值
            cfg = dict(DEFAULT_RATE_CONFIG)
            cfg.update(saved)
            return cfg
        except Exception:
            pass
    return dict(DEFAULT_RATE_CONFIG)

def _save_rate_config():
    """保存速率配置到文件"""
    try:
        with open(RATE_CONFIG_FILE, "w") as f:
            json.dump(rate_config, f)
    except Exception:
        pass

rate_config = _load_rate_config()
ip_requests = {}        # {ip: deque(timestamps)}
ip_blocked = {}         # {ip: blocked_until_timestamp}
ip_blocked_probes = {}  # {ip: probe_count}
ip_whitelist = set()    # 白名单 IP，不受速率限制
ip_manual_blocked = {}  # {ip: blocked_until_timestamp} 手动封禁
recent_blocks = []  # [(ip, timestamp, reason)] — 最近封禁记录，供通知功能使用
recent_blocks_lock = threading.Lock()

# ---------- IP 白名单持久化 ----------
WHITELIST_FILE = os.path.join(os.path.dirname(__file__), "ip_whitelist.json")

def _load_whitelist():
    """从文件加载白名单"""
    if os.path.exists(WHITELIST_FILE):
        try:
            with open(WHITELIST_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()

def _save_whitelist():
    """保存白名单到文件"""
    try:
        with open(WHITELIST_FILE, "w") as f:
            json.dump(sorted(ip_whitelist), f)
    except Exception:
        pass

ip_whitelist = _load_whitelist()

def _verify_captcha(user_input):
    """验证图形验证码"""
    if not user_input:
        return False
    stored = session.get("captcha_code", "")
    if user_input.strip().lower() != stored:
        session.pop("captcha_code", None)
        session.pop("captcha_time", None)
        return False
    session.pop("captcha_code", None)
    session.pop("captcha_time", None)
    return True


# ---------- 图形验证码 ----------
@app.route("/api/captcha")
def api_captcha():
    """生成图形验证码"""
    # 验证码接口速率限制: 每 IP 每 60 秒最多 10 次
    client_ip = request.remote_addr or "unknown"
    if not rate_limiter.check((client_ip, "captcha"), max_requests=10, window=60):
        return jsonify({"error": "请求过于频繁"}), 429

    import random as _random
    # 生成4位随机码（数字+字母，排除易混淆字符）
    chars = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    code = "".join(_random.choice(chars) for _ in range(4))
    session["captcha_code"] = code.lower()
    session["captcha_time"] = time.time()

    # 创建验证码图片
    width, height = 140, 50
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # 轻量背景噪点
    for x in range(width):
        for y in range(height):
            if _random.random() < 0.15:
                draw.point((x, y), fill=(_random.randint(220, 255), _random.randint(220, 255), _random.randint(220, 255)))

    # 1 条曲线干扰
    points = [(_random.randint(0, width), _random.randint(0, height)) for _ in range(4)]
    for j in range(len(points) - 1):
        draw.line([points[j], points[j+1]], fill=(_random.randint(180, 230), _random.randint(180, 230), _random.randint(180, 230)), width=1)

    # 3 条短直线
    for _ in range(3):
        x1, y1 = _random.randint(10, width - 10), _random.randint(5, height - 5)
        x2, y2 = x1 + _random.randint(-30, 30), y1 + _random.randint(-15, 15)
        draw.line([(x1, y1), (x2, y2)], fill=(_random.randint(180, 230), _random.randint(180, 230), _random.randint(180, 230)), width=1)

    # 少量随机点
    for _ in range(60):
        x, y = _random.randint(0, width), _random.randint(0, height)
        draw.point((x, y), fill=(_random.randint(100, 200), _random.randint(100, 200), _random.randint(100, 200)))

    # 绘制文字（扭曲）
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 32)
    except:
        font = ImageFont.load_default()

    for i, ch in enumerate(code):
        # 每个字符单独创建并旋转
        char_img = Image.new("RGBA", (40, 48), (0, 0, 0, 0))
        char_draw = ImageDraw.Draw(char_img)
        color = (_random.randint(0, 60), _random.randint(0, 80), _random.randint(160, 255))
        char_draw.text((4, 2), ch, font=font, fill=color)
        # 轻度旋转
        angle = _random.randint(-15, 15)
        char_img = char_img.rotate(angle, expand=True, fillcolor=(0, 0, 0, 0))
        x = 10 + i * 30 + _random.randint(-4, 4)
        y = _random.randint(2, 8)
        img.paste(char_img, (x, y), char_img)

    # 轻微模糊
    img = img.filter(ImageFilter.GaussianBlur(radius=0.4))

    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    from flask import make_response
    resp = make_response(send_file(buf, mimetype="image/png"))
    resp.headers["Cache-Control"] = "no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

# ---------- 登录防爆破 ----------
login_lockout = {}  # {username: (attempts, lockout_until)}

rate_lock = threading.Lock()

# ---------- IP 会话超时（2分钟无动作自动登出） ----------
SESSION_IDLE_TIMEOUT = 150  # 秒
ip_last_active = {}         # {ip: last_activity_timestamp}
session_lock = threading.Lock()

@app.before_request
def check_rate_limit():
    # 静态文件和分享链接跳过速率限制
    path = request.path
    if any(path.startswith(p) for p in ("/static/", "/assets/", "/favicon.ico", "/share/")):
        return None
    ip = request.remote_addr or "0.0.0.0"
    now = time.time()
    with rate_lock:
        # 白名单：跳过检查
        if ip in ip_whitelist:
            return None
        # 手动封禁检查
        if ip in ip_manual_blocked and now < ip_manual_blocked[ip]:
            remaining = int(ip_manual_blocked[ip] - now)
            return jsonify({"error": f"IP已被管理员手动封禁，剩余 {remaining} 秒"}), 403
        # 检查是否在封禁期
        if ip in ip_blocked:
            if now < ip_blocked[ip]:
                # 累加封禁期间的试探次数
                ip_blocked_probes[ip] = ip_blocked_probes.get(ip, 0) + 1
                if ip_blocked_probes[ip] >= rate_config["BLOCK_PROBE_LIMIT"]:
                    ip_blocked[ip] += rate_config["BLOCK_EXTEND"]
                    ip_blocked_probes[ip] = 0  # 重置计数
                    remaining = int(ip_blocked[ip] - now)
                    return jsonify({"error": f"封禁期间持续试探，封禁延长 {rate_config['BLOCK_EXTEND']} 秒，剩余 {remaining} 秒"}), 403
                remaining = int(ip_blocked[ip] - now)
                return jsonify({"error": f"请求过于频繁，IP已被封禁，剩余 {remaining} 秒"}), 403
            else:
                del ip_blocked[ip]
                ip_blocked_probes.pop(ip, None)
        # 记录本次请求
        if ip not in ip_requests:
            ip_requests[ip] = deque()
        q = ip_requests[ip]
        # 清理过期记录
        while q and now - q[0] > rate_config["RATE_WINDOW"]:
            q.popleft()
        q.append(now)
        # 超限则封禁
        if len(q) > rate_config["RATE_LIMIT"]:
            ip_blocked[ip] = now + rate_config["BLOCK_DURATION"]
            ip_blocked_probes[ip] = 0
            with recent_blocks_lock:
                recent_blocks.append((ip, now, "请求超限"))
                if len(recent_blocks) > 100:
                    recent_blocks.pop(0)
            del ip_requests[ip]
            return jsonify({"error": f"请求过于频繁，IP已被封禁 {rate_config['BLOCK_DURATION']} 秒"}), 403


@app.before_request
def check_session_idle_timeout():
    """如果 IP 在 SESSION_IDLE_TIMEOUT 秒内无任何动作，下次请求强制重新登录"""
    # 排除不需要超时检测的路由
    skip_prefixes = ("/static/", "/assets/", "/favicon.ico", "/share/", "/plugin-market/")
    path = request.path
    if any(path.startswith(p) for p in skip_prefixes):
        return None
    # 登录/注册/登出 页面是超时后要去的，不检测
    if path in ("/", "/register", "/logout"):
        return None

    ip = request.remote_addr or "0.0.0.0"
    now = time.time()

    with session_lock:
        # 检查该 IP 是否已超时（仅对已登录用户）
        if "username" in session:
            last = ip_last_active.get(ip, 0)
            if last and (now - last) > SESSION_IDLE_TIMEOUT:
                # 超时了，清除会话
                idle_minutes = int((now - last) / 60)
                session.clear()
                del ip_last_active[ip]
                flash(f"由于 {idle_minutes} 分钟未操作，已自动退出登录", "warning")
                return redirect(url_for("login"))
            # 更新最后活跃时间
            ip_last_active[ip] = now

    return None


# ---------- 全站验证码门禁 ----------
CAPTCHA_SKIP = {"/", "/register", "/logout", "/forgot_password", "/reset_password", "/calculator", "/calculator/sci", "/calculator/net", "/notes", "/change_password", "/profile", "/author", "/chat", "/api/captcha", "/dashboard", "/admin", "/donate", "/calendar", "/network_tools", "/system_monitor", "/db_query", "/db_update", "/marketplace", "/api/marketplace"}
CAPTCHA_SKIP_PREFIX = ("/static/", "/assets/", "/favicon.ico", "/share/", "/api/table/", "/file_manager", "/api/album/", "/api/file/", "/api/chat/", "/api/leaderboard", "/api/admin/", "/api/notifications", "/api/avatar", "/api/system", "/api/vip", "/api/lang/", "/api/calendar/", "/api/network/", "/plugin-market/")

@app.before_request
def check_global_captcha():
    if "username" not in session:
        return None
    path = request.path
    if path in CAPTCHA_SKIP or any(path.startswith(p) for p in CAPTCHA_SKIP_PREFIX):
        return None
    if session.get("global_captcha_verified"):
        return None
    if request.method == "POST" and request.form.get("captcha"):
        inp = request.form.get("captcha", "").strip().lower()
        if inp == session.get("captcha_code", ""):
            session["global_captcha_verified"] = True
            session.pop("captcha_code", None)
            return redirect(request.path)
        flash("验证码错误", "danger")
    if path.startswith("/api/"):
        return jsonify({"error": "需要安全验证"}), 403
    return render_template("global_captcha.html",
                           username=session["username"],
                           permission=session["permission"],
                           csrf_token=session.get("csrf_token", ""))


# ---------- 配置 ----------
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "root@123456",
    "database": "sample"
}
ALBUM_DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "root@123456",
    "database": "sample"
}
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "asdfghjkl;'")
LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "app.log")


# ---------- 安全响应头 ----------
@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # X-XSS-Protection 头在现代浏览器已弃用（Chrome/Edge 完全忽略，Firefox 使用内置过滤器），不再发送
    # CSP: 防 XSS + 点击劫持 + 资源来源限制（使用 nonce 替代 unsafe-inline）
    nonce = getattr(g, "csp_nonce", "")
    nonce_directive = f" 'nonce-{nonce}'" if nonce else ""
    # 如果路由处理器已设置了 CSP，保留原样不覆盖（例如插件沙箱需要 unsafe-inline）
    if "Content-Security-Policy" not in response.headers:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            # script-src：nonce 已覆盖所有 <script> 标签，unsafe-inline 暂保留以兼容 100+ 内联事件 handler（onclick 等），逐步迁移后可移除
            f"script-src 'self' 'unsafe-inline'{nonce_directive} https://cdn.bootcdn.net https://unpkg.com; "
            # style-src：所有内联 <style> 已加 nonce，移除了 unsafe-inline
            f"style-src 'self'{nonce_directive} https://cdn.bootcdn.net https://cdn.jsdelivr.net; "
            "font-src 'self' https://cdn.bootcdn.net; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' https://api.dictionaryapi.dev https://cdn.bootcdn.net https://cdn.jsdelivr.net; "
            "frame-ancestors 'self'; "
            "form-action 'self'"
        )
    # 隐藏 Werkzeug 版本信息
    response.headers.pop("Server", None)
    # 敏感页面禁用缓存
    if "text/html" in response.content_type:
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    # HSTS: 仅在生产环境下使用
    if not os.environ.get("FLASK_DEBUG"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


# ---------- 工具函数 ----------
def get_db():
    try:
        return pymysql.connect(**DB_CONFIG)
    except pymysql.MySQLError as e:
        return None

def get_album_db():
    try:
        conn = pymysql.connect(**ALBUM_DB_CONFIG)
        _init_album_tables(conn)
        return conn
    except pymysql.MySQLError as e:
        return None

# ---------- 初始化相册扩展表 ----------
def _init_album_tables(conn):
    """创建相册扩展功能所需的表（如果不存在）"""
    cursor = conn.cursor()
    # 大事记时间轴
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS album_events (
            id INT AUTO_INCREMENT PRIMARY KEY,
            title VARCHAR(255) NOT NULL,
            description TEXT,
            event_date DATE NOT NULL,
            created_by VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 同学录
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS album_classmates (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(50) NOT NULL,
            nickname VARCHAR(50),
            avatar_url VARCHAR(500),
            birthday DATE,
            phone VARCHAR(30),
            email VARCHAR(100),
            motto TEXT,
            interests TEXT,
            future_plan TEXT,
            class_name VARCHAR(30) DEFAULT '',
            graduation_year VARCHAR(20) DEFAULT '',
            created_by VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 确保 class_name 列存在（兼容旧表）
    cursor.execute("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA='sample' AND TABLE_NAME='album_classmates' AND COLUMN_NAME='class_name'
    """)
    if cursor.fetchone()[0] == 0:
        cursor.execute("ALTER TABLE album_classmates ADD COLUMN class_name VARCHAR(30) DEFAULT ''")
    # 确保 graduation_year 列存在（兼容旧表）
    cursor.execute("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA='sample' AND TABLE_NAME='album_classmates' AND COLUMN_NAME='graduation_year'
    """)
    if cursor.fetchone()[0] == 0:
        cursor.execute("ALTER TABLE album_classmates ADD COLUMN graduation_year VARCHAR(20) DEFAULT ''")
    # 毕业寄语
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS album_wishes (
            id INT AUTO_INCREMENT PRIMARY KEY,
            author VARCHAR(50),
            is_anonymous TINYINT DEFAULT 0,
            content TEXT NOT NULL,
            avatar_color VARCHAR(20),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 照片标签
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS album_tags (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(50) NOT NULL UNIQUE,
            color VARCHAR(20) DEFAULT '#04c'
        )
    """)
    # 照片-标签关联
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS album_image_tags (
            image_id INT NOT NULL,
            tag_id INT NOT NULL,
            PRIMARY KEY (image_id, tag_id)
        )
    """)
    # 毕业歌单
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS album_playlist (
            id INT AUTO_INCREMENT PRIMARY KEY,
            title VARCHAR(255) NOT NULL,
            artist VARCHAR(100),
            url VARCHAR(500),
            added_by VARCHAR(50),
            votes INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 弹幕
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS album_danmaku (
            id INT AUTO_INCREMENT PRIMARY KEY,
            image_id INT NOT NULL,
            text VARCHAR(200) NOT NULL,
            color VARCHAR(20) DEFAULT '#fff',
            position FLOAT DEFAULT 50,
            author VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 分享链接
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS album_share_links (
            id INT AUTO_INCREMENT PRIMARY KEY,
            image_id INT NOT NULL,
            token VARCHAR(64) NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 聊天消息
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INT AUTO_INCREMENT PRIMARY KEY,
            channel VARCHAR(10) NOT NULL DEFAULT 'world',
            sender VARCHAR(50) NOT NULL,
            recipient VARCHAR(50) DEFAULT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_channel (channel),
            INDEX idx_sender (sender),
            INDEX idx_recipient (recipient),
            INDEX idx_created (created_at)
        )
    """)
    # 好友关系
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS friendships (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user1 VARCHAR(50) NOT NULL,
            user2 VARCHAR(50) NOT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            requester VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_pair (user1, user2)
        )
    """)
    conn.commit()
    cursor.close()

    # 学习工具表
    conn2 = get_db()
    if conn2:
        try:
            cur = conn2.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS study_todos (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(50) NOT NULL,
                    title VARCHAR(200) NOT NULL,
                    completed TINYINT DEFAULT 0,
                    priority TINYINT DEFAULT 0,
                    due_date DATE NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS study_flashcards (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(50) NOT NULL,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    tags VARCHAR(100) DEFAULT '',
                    level TINYINT DEFAULT 0,
                    reviewed_count INT DEFAULT 0,
                    last_reviewed TIMESTAMP NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn2.commit()
            cur.close()
            conn2.close()
        except pymysql.MySQLError:
            pass


# ---------- 输入清洗 ----------
_SCRIPT_TAG = re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_HTML_TAG = re.compile(r"<[^>]+>")

def sanitize_input(text, max_length=1000):
    """清洗用户输入：去除 HTML/JS 标签，限制长度"""
    if not text:
        return ""
    text = str(text).strip()
    text = _SCRIPT_TAG.sub("", text)
    text = _HTML_TAG.sub("", text)
    return text[:max_length]

def _mask_cell(col_name, value):
    """直接返回原始值"""
    return str(value) if value is not None else ""

def write_log(action, detail=""):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] {action}"
    if detail:
        entry += f" - {detail}"
    entry += "\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
    except:
        pass

def read_logs():
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                return f.read()
        except:
            return ""
    return ""

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "请先登录"}), 401
            flash("请先登录", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def csrf_required(f):
    """验证 CSRF token（用于非 GET 请求的表单提交）"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
            return f(*args, **kwargs)
        # 检查 session 中的 token
        token = request.form.get("_csrf_token") or request.headers.get("X-CSRF-Token")
        expected = session.get("csrf_token")
        if not expected or not token or not hmac.compare_digest(str(token), str(expected)):
            flash("安全验证失败，请重试", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("permission") != "administrator":
            flash("权限不足，需要管理员权限", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated

def non_guest_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        perm = session.get("permission", "guest")
        if perm == "guest":
            flash("访客无法使用此功能，请申请 VIP 权限", "warning")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated

def vip_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        perm = session.get("permission", "guest")
        if perm not in ("administrator", "vip"):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "需要 VIP 或管理员权限"}), 403
            flash("需要 VIP 或管理员权限", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


# ---------- 数据库二次验证（验证码） ----------
def db_captcha_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("db_captcha_verified"):
            return f(*args, **kwargs)
        if request.method == "POST" and request.form.get("db_captcha"):
            captcha_input = request.form.get("db_captcha", "").strip().lower()
            stored = session.get("captcha_code", "")
            if captcha_input == stored:
                session["db_captcha_verified"] = True
                session.pop("captcha_code", None)
                return redirect(request.path)
            else:
                flash("验证码错误", "danger")
        # API 请求返回 JSON 错误
        if request.path.startswith("/api/"):
            return jsonify({"error": "需要数据库操作验证"}), 403
        return render_template("db_captcha.html",
                               username=session["username"],
                               permission=session["permission"],
                               csrf_token=session.get("csrf_token", ""))
    return decorated


# ---------- 文件管理器密码二次验证 ----------
def fm_password_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("fm_verified"):
            return f(*args, **kwargs)
        if request.method == "POST" and request.form.get("fm_password"):
            pwd = request.form.get("fm_password", "").strip()
            conn = get_db()
            if conn:
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT User_Password FROM users WHERE User_Name = %s", (session["username"],))
                    result = cursor.fetchone()
                    cursor.close()
                    conn.close()
                    if result and check_password_hash(result[0], pwd):
                        session["fm_verified"] = True
                        return redirect(request.path)
                except:
                    pass
            flash("密码错误", "danger")
        return render_template("fm_password.html",
                               username=session["username"],
                               permission=session["permission"],
                               csrf_token=session.get("csrf_token", ""))
    return decorated


# ---------- 路由：登录 ----------
@app.route("/", methods=["GET", "POST"])
def login():
    _init_db_once()
    # 生成 CSRF token
    if "csrf_token" not in session:
        session["csrf_token"] = os.urandom(32).hex()

    # GET 请求频率限制（未登录用户每 60 秒最多 30 次）
    if request.method == "GET" and "username" not in session:
        client_ip = request.remote_addr or "unknown"
        if not rate_limiter.check((client_ip, "login_page"), max_requests=30, window=60):
            return Response("请求过于频繁", status=429)

    if request.method == "POST":
        # 登录速率限制: 每 IP 每 60 秒最多 5 次 POST
        client_ip = request.remote_addr or "unknown"
        if not rate_limiter.check((client_ip, "login"), max_requests=5, window=60):
            return Response("请求过于频繁", status=429)

        username = sanitize_input(request.form.get("username", ""), 50)
        password = request.form.get("password", "").strip()

        if not username or not password:
            flash("用户名和密码不能为空", "danger")
            return render_template("login.html", csrf_token=session.get("csrf_token", ""))

        # 验证码校验
        captcha_input = request.form.get("captcha", "").strip().lower()
        if not _verify_captcha(captcha_input):
            flash("验证码错误", "danger")
            return render_template("login.html", csrf_token=session.get("csrf_token", ""))

        # 登录防爆破检查
        now = time.time()
        if username in login_lockout:
            attempts, lockout_until = login_lockout[username]
            if lockout_until and now < lockout_until:
                remaining = int(lockout_until - now)
                flash(f"账户已被锁定，请 {remaining // 60} 分 {remaining % 60} 秒后重试", "danger")
                return render_template("login.html", csrf_token=session.get("csrf_token", ""))

        conn = get_db()
        if not conn:
            flash("数据库连接失败", "danger")
            return render_template("login.html", csrf_token=session.get("csrf_token", ""))

        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT User_Password, Access_Permission FROM users WHERE User_Name = %s",
                (username,)
            )
            result = cursor.fetchone()
            cursor.close()
            conn.close()

            if result and check_password_hash(result[0], password):
                # 登录成功：清除失败记录
                login_lockout.pop(username, None)
                session["username"] = username
                session["permission"] = result[1]
                session["csrf_token"] = os.urandom(32).hex()
                write_log("用户登录", f"用户名: {username}, 权限: {result[1]}")
                record_activity(username, "登录", 1)
                flash(f"欢迎回来，{sanitize_input(username)}！", "success")
                return redirect(url_for("dashboard"))
            # 兼容旧版：尝试明文密码匹配，并自动升级为 hash
            elif result and result[0] == password:
                # 登录成功：清除失败记录
                login_lockout.pop(username, None)
                hashed = generate_password_hash(password)
                try:
                    cursor_upgrade = conn.cursor()
                    cursor_upgrade.execute("UPDATE users SET User_Password=%s WHERE User_Name=%s", (hashed, username))
                    conn.commit()
                    cursor_upgrade.close()
                except Exception:
                    pass
                session["username"] = username
                session["permission"] = result[1]
                session["csrf_token"] = os.urandom(32).hex()
                write_log("用户登录(旧版密码升级hash)", f"用户名: {username}")
                record_activity(username, "登录", 1)
                flash(f"欢迎回来，{sanitize_input(username)}！密码已升级为更安全的存储方式", "success")
                return redirect(url_for("dashboard"))
            else:
                # 登录失败：记录尝试次数
                attempts, _ = login_lockout.get(username, (0, 0))
                attempts += 1
                if attempts >= 5:
                    login_lockout[username] = (attempts, time.time() + 5 * 60)
                    write_log("账户锁定", f"用户名: {username}, 失败 {attempts} 次，锁定 5 分钟")
                    flash(f"密码错误次数过多，账户已锁定 5 分钟", "danger")
                else:
                    login_lockout[username] = (attempts, 0)
                    remaining = 5 - attempts
                    write_log("登录失败", f"用户名: {username}, 剩余 {remaining} 次尝试")
                    flash(f"用户名或密码错误，还剩 {remaining} 次尝试机会", "danger")
        except pymysql.MySQLError as e:
            flash(f"数据库错误: {str(e)}", "danger")

    return render_template("login.html", csrf_token=session.get("csrf_token", ""))


@app.route("/register", methods=["GET", "POST"])
def register():
    _init_db_once()
    # 生成 CSRF token
    if "csrf_token" not in session:
        session["csrf_token"] = os.urandom(32).hex()
    if request.method == "POST":
        # 注册速率限制: 每 IP 每 60 秒最多 5 次
        client_ip = request.remote_addr or "unknown"
        if not rate_limiter.check((client_ip, "register"), max_requests=5, window=60):
            return Response("请求过于频繁", status=429)

        # 验证码校验
        captcha_input = request.form.get("captcha", "").strip().lower()
        if not _verify_captcha(captcha_input):
            flash("验证码错误", "danger")
            return render_template("register.html", csrf_token=session.get("csrf_token", ""))

        username = sanitize_input(request.form.get("username", ""), 50)
        password = request.form.get("password", "").strip()
        confirm = request.form.get("confirm", "").strip()
        admin_pwd = request.form.get("admin_pwd", "").strip()

        if not username or not password or not confirm:
            flash("所有字段不能为空", "danger")
            return render_template("register.html", csrf_token=session.get("csrf_token", ""))

        if password != confirm:
            flash("两次密码不一致", "danger")
            return render_template("register.html", csrf_token=session.get("csrf_token", ""))

        if len(password) < 8:
            flash("密码长度不能少于8位", "danger")
            return render_template("register.html", csrf_token=session.get("csrf_token", ""))

        # 密码复杂度检查
        if not re.search(r"[A-Za-z]", password):
            flash("密码必须包含至少一个字母", "danger")
            return render_template("register.html", csrf_token=session.get("csrf_token", ""))
        if not re.search(r"[0-9]", password):
            flash("密码必须包含至少一个数字", "danger")
            return render_template("register.html", csrf_token=session.get("csrf_token", ""))

        permission = "administrator" if hmac.compare_digest(admin_pwd, ADMIN_SECRET) else "guest"

        conn = get_db()
        if not conn:
            flash("数据库连接失败", "danger")
            return render_template("register.html", csrf_token=session.get("csrf_token", ""))

        try:
            cursor = conn.cursor()
            hashed_pw = generate_password_hash(password)
            cursor.execute(
                "INSERT INTO users (User_Name, User_Password, Access_Permission) VALUES (%s, %s, %s)",
                (username, hashed_pw, permission)
            )
            conn.commit()
            cursor.close()
            conn.close()
            perm_text = "管理员" if permission == "administrator" else "访客"
            write_log("用户注册", f"用户名: {username}, 权限: {permission}")
            flash(f"注册成功！权限: {perm_text}", "success")
            return redirect(url_for("login"))
        except pymysql.IntegrityError:
            flash("用户名已存在", "danger")
        except pymysql.MySQLError as e:
            flash(f"注册失败: {str(e)}", "danger")

    return render_template("register.html", csrf_token=session.get("csrf_token", ""))


@app.route("/logout", methods=["GET", "POST"])
def logout():
    if request.method == "GET":
        # GET 请求：显示确认页面（可优化为直接重定向带 JS 提交）
        return render_template("logout_confirm.html",
                               csrf_token=session.get("csrf_token", ""))
    # POST 请求：执行登出
    ip = request.remote_addr or "0.0.0.0"
    with session_lock:
        ip_last_active.pop(ip, None)
    session.clear()
    flash("已退出登录", "info")
    return redirect(url_for("login"))


# ---------- 路由：忘记密码 ----------
_reset_rate = {}  # {ip: (count, last_time)} 防滥用

@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    _init_db_once()
    # 生成 CSRF token
    if "csrf_token" not in session:
        session["csrf_token"] = os.urandom(32).hex()
    if request.method == "POST":
        username = sanitize_input(request.form.get("username", ""), 50)
        captcha_input = request.form.get("captcha", "").strip().lower()
        stored = session.get("captcha_code", "")
        ip = request.remote_addr or "0.0.0.0"
        now = time.time()

        # 速率限制：每 IP 3分钟内最多3次
        cnt, last = _reset_rate.get(ip, (0, 0))
        if cnt >= 3 and now - last < 180:
            remaining = int(180 - (now - last))
            flash(f"操作过于频繁，请 {remaining} 秒后重试", "danger")
            return render_template("forgot_password.html", csrf_token=session.get("csrf_token", ""))

        if not username:
            flash("请输入用户名", "danger")
        elif captcha_input != stored:
            session.pop("captcha_code", None)
            flash("验证码错误", "danger")
        else:
            session.pop("captcha_code", None)
            _reset_rate[ip] = (cnt + 1, now)
            conn = get_db()
            if conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE password_reset_tokens SET used=1 WHERE username=%s AND used=0", (username,))
                cursor.execute("DELETE FROM password_reset_tokens WHERE expires_at < NOW()")
                cursor.execute("SELECT User_Name FROM users WHERE User_Name=%s", (username,))
                if cursor.fetchone():
                    token = uuid.uuid4().hex
                    expires = datetime.datetime.now() + datetime.timedelta(minutes=10)
                    cursor.execute(
                        "INSERT INTO password_reset_tokens (username, token, expires_at) VALUES (%s,%s,%s)",
                        (username, token, expires)
                    )
                    conn.commit()
                    write_log("密码重置申请", f"用户名: {username}, IP: {ip}")
                    flash(f"重置令牌（请完整复制）: {token}", "info")
                else:
                    flash("用户名不存在", "danger")
                cursor.close()
                conn.close()

    return render_template("forgot_password.html", csrf_token=session.get("csrf_token", ""))


@app.route("/reset_password", methods=["GET", "POST"])
def reset_password():
    _init_db_once()
    # 生成 CSRF token
    if "csrf_token" not in session:
        session["csrf_token"] = os.urandom(32).hex()
    if request.method == "POST":
        username = sanitize_input(request.form.get("username", ""), 50)
        token = sanitize_input(request.form.get("token", ""), 32)
        new_pwd = request.form.get("new_pwd", "").strip()
        confirm_pwd = request.form.get("confirm_pwd", "").strip()
        captcha_input = request.form.get("captcha", "").strip().lower()
        stored_captcha = session.get("captcha_code", "")

        if not username or not token:
            flash("用户名和重置令牌不能为空", "danger")
        elif captcha_input != stored_captcha:
            session.pop("captcha_code", None)
            flash("验证码错误", "danger")
        elif new_pwd != confirm_pwd:
            flash("两次密码不一致", "danger")
        elif len(new_pwd) < 8:
            flash("密码至少8位", "danger")
        elif not re.search(r"[A-Za-z]", new_pwd):
            flash("密码需包含字母", "danger")
        elif not re.search(r"[0-9]", new_pwd):
            flash("密码需包含数字", "danger")
        else:
            session.pop("captcha_code", None)
            conn = get_db()
            if conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM password_reset_tokens WHERE username=%s AND token=%s AND used=0 AND expires_at > NOW()",
                    (username, token)
                )
                row = cursor.fetchone()
                if not row:
                    flash("令牌无效或已过期", "danger")
                else:
                    # 不允许和旧密码相同
                    cursor.execute("SELECT User_Password FROM users WHERE User_Name=%s", (username,))
                    old_pw = cursor.fetchone()
                    if old_pw and check_password_hash(old_pw[0], new_pwd):
                        flash("新密码不能与旧密码相同", "danger")
                    else:
                        hashed = generate_password_hash(new_pwd)
                        cursor.execute("UPDATE users SET User_Password=%s WHERE User_Name=%s", (hashed, username))
                        cursor.execute("UPDATE password_reset_tokens SET used=1 WHERE id=%s", (row[0],))
                        conn.commit()
                        write_log("密码重置成功", f"用户名: {username}, IP: {request.remote_addr}")
                        flash("密码重置成功，请登录", "success")
                        cursor.close()
                        conn.close()
                        return redirect(url_for("login"))
                cursor.close()
                conn.close()

    return render_template("reset_password.html",
                           csrf_token=session.get("csrf_token", ""))


# ---------- 活跃度系统 ----------
def record_activity(username, action, points=1):
    """记录用户活跃行为"""
    try:
        conn = get_db()
        if not conn:
            return
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO activity_log (username, action, points) VALUES (%s, %s, %s)",
            (username, action, points)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception:
        pass

def get_leaderboard(limit=10):
    """获取活跃度排行榜（同分时访客优先）"""
    conn = get_db()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.username, SUM(a.points) as total_score, COUNT(*) as action_count,
                   COALESCE(u.Access_Permission,'') as perm
            FROM activity_log a
            LEFT JOIN users u ON a.username = u.User_Name
            GROUP BY a.username, u.Access_Permission
            ORDER BY total_score DESC,
                     CASE WHEN COALESCE(u.Access_Permission,'')='guest' THEN 0 ELSE 1 END,
                     a.username
            LIMIT %s
        """, (limit,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return [{"username": r[0], "score": int(r[1]), "actions": int(r[2])} for r in rows]
    except Exception:
        return []

def get_user_rank(username):
    """获取用户排名"""
    conn = get_db()
    if not conn:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT username, SUM(points) as total_score
            FROM activity_log
            GROUP BY username
            ORDER BY total_score DESC
        """)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        for idx, r in enumerate(rows):
            if r[0] == username:
                return {"rank": idx + 1, "username": r[0], "score": int(r[1])}
        return None
    except Exception:
        return None

# ---------- 路由：活跃度排行榜 API ----------
@app.route("/api/leaderboard")
def api_leaderboard():
    limit = request.args.get("limit", 10, type=int)
    return jsonify({"leaderboard": get_leaderboard(limit)})

@app.route("/api/leaderboard/my-rank")
@login_required
def api_my_rank():
    rank_info = get_user_rank(session["username"])
    has_pending = False
    conn = get_db()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT status FROM admin_requests WHERE username=%s AND status='pending'",
                (session["username"],)
            )
            has_pending = cursor.fetchone() is not None
            cursor.close()
            conn.close()
        except Exception:
            pass
    return jsonify({
        "rank": rank_info,
        "has_pending_request": has_pending
    })

# ---------- 路由：申请管理员 ----------
@app.route("/api/admin-request", methods=["POST"])
@login_required
def api_admin_request():
    username = session["username"]
    if session.get("permission") == "administrator":
        return jsonify({"error": "你已经是管理员了"}), 400
    rank_info = get_user_rank(username)
    if not rank_info or rank_info["rank"] != 1:
        return jsonify({"error": "只有排行榜第一名才能申请管理员"}), 403
    conn = get_db()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, status FROM admin_requests WHERE username=%s", (username,))
        existing = cursor.fetchone()
        if existing:
            if existing[1] == "pending":
                return jsonify({"error": "你已经有待审核的申请了"}), 400
            elif existing[1] == "approved":
                return jsonify({"error": "你的申请已经通过了"}), 400
            else:
                cursor.execute(
                    "UPDATE admin_requests SET status='pending', score=%s, requested_at=NOW(), reviewed_by=NULL, reviewed_at=NULL WHERE username=%s",
                    (rank_info["score"], username)
                )
        else:
            cursor.execute(
                "INSERT INTO admin_requests (username, score) VALUES (%s, %s)",
                (username, rank_info["score"])
            )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "管理员申请已提交，请等待现有管理员审核"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- 路由：查看/处理管理员申请 ----------
@app.route("/api/admin-requests")
@login_required
def api_admin_requests():
    if session.get("permission") != "administrator":
        return jsonify({"error": "仅管理员可访问"}), 403
    conn = get_db()
    if not conn:
        return jsonify({"requests": []})
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, username, score, status, requested_at, reviewed_by, reviewed_at
            FROM admin_requests ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, requested_at DESC
        """)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify({
            "requests": [{"id": r[0], "username": r[1], "score": r[2], "status": r[3],
                "requested_at": str(r[4]) if r[4] else None, "reviewed_by": r[5],
                "reviewed_at": str(r[6]) if r[6] else None} for r in rows]
        })
    except Exception:
        return jsonify({"requests": []})

@app.route("/api/admin-review", methods=["POST"])
@login_required
def api_admin_review():
    if session.get("permission") != "administrator":
        return jsonify({"error": "仅管理员可操作"}), 403
    req_id = request.json.get("id")
    action = request.json.get("action")
    if action not in ("approve", "reject"):
        return jsonify({"error": "无效操作"}), 400
    conn = get_db()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT username, status FROM admin_requests WHERE id=%s", (req_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "申请不存在"}), 404
        if row[1] != "pending":
            return jsonify({"error": "申请已处理"}), 400
        if action == "approve":
            cursor.execute("UPDATE users SET Access_Permission='administrator' WHERE User_Name=%s", (row[0],))
            new_status = "approved"
        else:
            new_status = "rejected"
        cursor.execute(
            "UPDATE admin_requests SET status=%s, reviewed_by=%s, reviewed_at=NOW() WHERE id=%s",
            (new_status, session["username"], req_id)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "已" + ("通过" if action == "approve" else "拒绝") + "申请"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- VIP 申请/审核 ----------
@app.route("/api/vip-request", methods=["POST"])
@login_required
def api_vip_request():
    username = session["username"]
    perm = session.get("permission", "guest")
    if perm in ("administrator", "vip"):
        return jsonify({"error": "你已有更高的权限"}), 400
    conn = get_db()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM admin_requests WHERE username=%s AND status='pending'", (username,))
        if cursor.fetchone():
            return jsonify({"error": "你已有待审核的申请"}), 400
        cursor.execute(
            "INSERT INTO admin_requests (username, status, score) VALUES (%s, 'pending', 0)",
            (username,)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "VIP 申请已提交，请等待管理员审核"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/vip-review", methods=["POST"])
@login_required
def api_vip_review():
    """管理员审核 VIP 申请或直接设置 VIP"""
    if session.get("permission") != "administrator":
        return jsonify({"error": "仅管理员可操作"}), 403
    username = request.json.get("username", "").strip()
    action = request.json.get("action", "approve")
    if not username:
        return jsonify({"error": "需要指定用户名"}), 400
    conn = get_db()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        new_perm = "vip" if action == "approve" else "guest"
        cursor.execute("UPDATE users SET Access_Permission=%s WHERE User_Name=%s", (new_perm, username))
        if cursor.rowcount == 0:
            return jsonify({"error": "用户不存在"}), 404
        # 更新对应的待审核申请
        cursor.execute(
            "UPDATE admin_requests SET status=%s, reviewed_by=%s, reviewed_at=NOW() WHERE username=%s AND status='pending'",
            ("approved" if action == "approve" else "rejected", session["username"], username)
        )
        conn.commit()
        cursor.close()
        conn.close()
        write_log("VIP审核", f"管理员: {session['username']}, 目标用户: {username}, 操作: {'通过' if action == 'approve' else '拒绝'}")
        return jsonify({"message": f"已{'设为VIP' if action == 'approve' else '降为访客'}"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- 路由：本地头像生成 (PNG) ----------
AVATAR_CACHE_DIR = os.path.join(os.path.dirname(__file__), "static", "avatars")
os.makedirs(AVATAR_CACHE_DIR, exist_ok=True)

@app.route("/api/avatar/<seed>")
def api_avatar(seed):
    """生成初始头像PNG"""
    from PIL import Image, ImageDraw, ImageFont
    size = request.args.get("size", 140, type=int)
    bgcolor = request.args.get("bg", "667eea")
    color = request.args.get("color", "fff")
    text = seed[0].upper() if seed else "?"

    # 缓存文件名
    cache_key = f"{seed}_{size}_{bgcolor}_{color}"
    cache_file = os.path.join(AVATAR_CACHE_DIR, f"{cache_key}.png")

    # 如果缓存存在则直接发送
    if os.path.exists(cache_file):
        return send_from_directory(AVATAR_CACHE_DIR, f"{cache_key}.png", mimetype="image/png")

    # 解析颜色
    try:
        r = int(bgcolor[0:2], 16)
        g = int(bgcolor[2:4], 16)
        b = int(bgcolor[4:6], 16)
        bg_rgb = (r, g, b)
    except Exception:
        bg_rgb = (102, 126, 234)
    try:
        fc = tuple(int(color[i:i+2], 16) for i in (0, 2, 4))
    except Exception:
        fc = (255, 255, 255)

    img = Image.new("RGBA", (size, size), bg_rgb + (255,))
    draw = ImageDraw.Draw(img)

    # 尝试加载中文字体
    font_paths = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    font = None
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, int(size * 0.5))
                break
            except Exception:
                continue
    if not font:
        font = ImageFont.load_default()

    # 绘制文字（居中）
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (size - tw) / 2 - bbox[0]
    ty = (size - th) / 2 - bbox[1]
    draw.text((tx, ty), text, fill=fc, font=font)

    # 保存并返回
    img.save(cache_file, "PNG")
    return send_from_directory(AVATAR_CACHE_DIR, f"{cache_key}.png", mimetype="image/png")

# ---------- 路由：通知铃铛 API ----------
@app.route("/api/notifications")
@login_required
def api_notifications():
    """获取未读通知数量"""
    username = session["username"]
    is_admin = session.get("permission") == "administrator"
    since = request.args.get("since", "").strip()
    result = {"chat_unread": 0, "admin_requests": 0, "blocked_ips": 0}

    # 聊天未读
    if since:
        try:
            conn = pymysql.connect(**ALBUM_DB_CONFIG)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM chat_messages
                WHERE (channel='world' OR recipient=%s) AND sender!=%s AND created_at > %s
            """, (username, username, since))
            result["chat_unread"] = cursor.fetchone()[0]
            cursor.close()
            conn.close()
        except Exception:
            pass

    # 管理员通知
    if is_admin:
        try:
            conn = get_db()
            if conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM admin_requests WHERE status='pending'")
                result["admin_requests"] = cursor.fetchone()[0]
                cursor.close()
                conn.close()
        except Exception:
            pass
        try:
            cutoff = time.time() - 3600
            with recent_blocks_lock:
                result["blocked_ips"] = sum(1 for _, ts, _ in recent_blocks if ts > cutoff)
        except Exception:
            result["blocked_ips"] = 0
        # 待审核照片数
        try:
            conn2 = get_album_db()
            if conn2:
                cur2 = conn2.cursor()
                cur2.execute("SELECT COUNT(*) FROM album_images WHERE COALESCE(status,'approved')='pending'")
                result["pending_photos"] = cur2.fetchone()[0]
                cur2.close()
                conn2.close()
        except Exception:
            pass

    return jsonify(result)

@app.route("/api/notifications/read", methods=["POST"])
@login_required
def api_notifications_read():
    """标记通知已读"""
    from datetime import datetime
    session["last_notification_read"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    return jsonify({"success": True})

# ---------- 路由：仪表盘 ----------
@app.route("/dashboard")
@login_required
def dashboard():
    leaderboard = get_leaderboard(10)
    my_rank = get_user_rank(session["username"])
    # check pending request
    pending_request = False
    if session.get("permission") != "administrator":
        try:
            conn = get_db()
            if conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM admin_requests WHERE username=%s AND status='pending'",
                    (session["username"],)
                )
                pending_request = cursor.fetchone() is not None
                cursor.close()
                conn.close()
        except Exception:
            pass
    # admin: count pending requests
    pending_admin_reqs = 0
    if session.get("permission") == "administrator":
        try:
            conn = get_db()
            if conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM admin_requests WHERE status='pending'")
                pending_admin_reqs = cursor.fetchone()[0]
                cursor.close()
                conn.close()
        except Exception:
            pass
    return render_template("dashboard.html",
                           username=session["username"],
                           permission=session["permission"],
                           leaderboard=leaderboard,
                           my_rank=my_rank,
                           pending_request=pending_request,
                           pending_admin_reqs=pending_admin_reqs)


# ---------- 路由：个人资料 ----------
@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    conn = get_db()
    if not conn:
        flash("数据库连接失败", "danger")
        return redirect(url_for("dashboard"))
    cursor = conn.cursor()

    if request.method == "POST":
        nickname = sanitize_input(request.form.get("nickname", ""), 50)
        bio = sanitize_input(request.form.get("bio", ""), 500)
        phone = sanitize_input(request.form.get("phone", ""), 20)
        email = sanitize_input(request.form.get("email", ""), 100)
        birthday = request.form.get("birthday", "").strip() or None
        cursor.execute(
            "INSERT INTO user_profiles (username, nickname, bio, phone, email, birthday) "
            "VALUES (%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE "
            "nickname=%s,bio=%s,phone=%s,email=%s,birthday=%s",
            (session["username"], nickname, bio, phone, email, birthday,
             nickname, bio, phone, email, birthday)
        )
        conn.commit()
        flash("个人资料已保存", "success")

    cursor.execute("SELECT * FROM user_profiles WHERE username=%s", (session["username"],))
    cols = [d[0] for d in cursor.description]
    row = cursor.fetchone()
    profile_data = dict(zip(cols, row)) if row else {}
    cursor.close()
    conn.close()
    return render_template("profile.html",
                           username=session["username"],
                           permission=session["permission"],
                           profile=profile_data,
                           csrf_token=session.get("csrf_token", ""))


# ---------- 路由：关于作者 ----------
@app.route("/author")
def author():
    return render_template("author.html",
                           username=session.get("username", ""),
                           permission=session.get("permission", ""))


# ---------- 路由：打赏 ----------
@app.route("/donate")
def donate():
    return render_template("donate.html",
                           username=session.get("username", ""),
                           permission=session.get("permission", ""))


# ---------- 路由：聊天 ----------
@app.route("/chat")
@login_required
def chat_standalone():
    return render_template("chat_standalone.html",
                           username=session["username"],
                           permission=session["permission"])


# ---------- 路由：系统监控 ----------
@app.route("/system_monitor")
@login_required
@admin_required
def system_monitor():
    return render_template("system_monitor.html",
                           username=session["username"],
                           permission=session["permission"])


@app.route("/api/system_info")
@login_required
@admin_required
def api_system_info():
    """返回系统信息的JSON，供前端定时刷新"""
    try:
        boot_time = psutil.boot_time()
        uptime_seconds = int(datetime.datetime.now().timestamp() - boot_time)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, _ = divmod(remainder, 60)

        memory = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count_physical = psutil.cpu_count(logical=False) or "N/A"
        cpu_count_logical = psutil.cpu_count(logical=True)

        partitions = []
        for p in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(p.mountpoint)
                partitions.append({
                    "device": p.device,
                    "mountpoint": p.mountpoint,
                    "fstype": p.fstype,
                    "total_gb": round(usage.total / (1024**3), 2),
                    "used_gb": round(usage.used / (1024**3), 2),
                    "free_gb": round(usage.free / (1024**3), 2),
                    "percent": usage.percent
                })
            except:
                pass

        net = psutil.net_io_counters()

        return jsonify({
            "system": platform.system(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "hostname": platform.node(),
            "uptime": f"{hours}小时{minutes}分钟",
            "cpu": {
                "physical": cpu_count_physical,
                "logical": cpu_count_logical,
                "percent": cpu_percent
            },
            "memory": {
                "total_gb": round(memory.total / (1024**3), 2),
                "used_gb": round(memory.used / (1024**3), 2),
                "available_gb": round(memory.available / (1024**3), 2),
                "percent": memory.percent
            },
            "disk": partitions,
            "network": {
                "sent_mb": round(net.bytes_sent / (1024**2), 2),
                "recv_mb": round(net.bytes_recv / (1024**2), 2),
                "sent_packets": net.packets_sent,
                "recv_packets": net.packets_recv
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/system_users")
@login_required
@admin_required
def api_system_users():
    """返回当前在线用户及活动信息"""
    now = time.time()
    users = []
    with session_lock:
        for ip, last_active in list(ip_last_active.items()):
            idle = int(now - last_active)
            # 只展示 10 分钟内有活动的
            if idle > 600:
                continue
            blocked = ip in ip_blocked and now < ip_blocked[ip]
            whitelisted = ip in ip_whitelist
            manual_blocked = ip in ip_manual_blocked and now < ip_manual_blocked[ip]

            # 速率统计
            reqs = 0
            with rate_lock:
                if ip in ip_requests:
                    reqs = len(ip_requests[ip])

            users.append({
                "ip": ip,
                "idle_seconds": idle,
                "idle_str": f"{idle}s" if idle < 60 else f"{idle//60}m{idle%60}s",
                "requests": reqs,
                "blocked": blocked,
                "whitelisted": whitelisted,
                "manual_blocked": manual_blocked,
            })

    # 数据库中的注册用户统计
    total_users = 0
    admin_count = 0
    vip_count = 0
    try:
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            row = cursor.fetchone()
            total_users = row[0] if row else 0
            cursor.execute("SELECT COUNT(*) FROM users WHERE permission='administrator'")
            row = cursor.fetchone()
            admin_count = row[0] if row else 0
            cursor.execute("SELECT COUNT(*) FROM users WHERE permission='vip'")
            row = cursor.fetchone()
            vip_count = row[0] if row else 0
            cursor.close()
            conn.close()
    except Exception:
        pass

    return jsonify({
        "ok": True,
        "online_ips": len(users),
        "online_users": users,
        "total_registered": total_users,
        "admin_count": admin_count,
        "vip_count": vip_count,
        "total_blocked": len([u for u in users if u["blocked"]]),
        "total_whitelisted": len([u for u in users if u["whitelisted"]]),
    })


# ---------- 路由：网络工具 ----------
@app.route("/network_tools", methods=["GET", "POST"])
@login_required
@vip_required
def network_tools():
    result = None
    result_type = None
    if request.method == "POST":
        action = request.form.get("action")
        if action == "ip_query":
            target = request.form.get("target", "").strip()
            result_type = "ip_query"
            try:
                ip = socket.gethostbyname(target)
                public_ip = ""
                try:
                    resp = requests.get("https://api.ipify.org?format=json", timeout=5)
                    public_ip = resp.json().get("ip", "")
                except:
                    pass
                result = {
                    "hostname": target,
                    "ip": ip,
                    "local_ip": socket.gethostbyname(socket.gethostname()),
                    "public_ip": public_ip
                }
            except socket.gaierror:
                result = {"error": f"无法解析: {target}"}

        elif action == "port_scan":
            target = request.form.get("target", "").strip()
            start_port = request.form.get("start_port", "1")
            end_port = request.form.get("end_port", "100")
            result_type = "port_scan"

            try:
                start = int(start_port)
                end = int(end_port)
                if start < 1 or end > 65535 or start > end:
                    result = {"error": "端口范围无效"}
                else:
                    open_ports = []
                    os_detected = "未知"
                    ports_to_scan = range(start, min(end + 1, start + 200))

                    def scan_port(p):
                        try:
                            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            s.settimeout(0.3)
                            r = s.connect_ex((target, p))
                            s.close()
                            return p if r == 0 else None
                        except:
                            return None

                    threads = []
                    results = [None] * len(ports_to_scan)
                    def scan_wrapper(i, p):
                        results[i] = scan_port(p)

                    for i, p in enumerate(ports_to_scan):
                        t = threading.Thread(target=scan_wrapper, args=(i, p))
                        threads.append(t)
                        t.start()
                    for t in threads:
                        t.join()

                    open_ports = [p for p in results if p is not None]

                    # OS检测
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.settimeout(1)
                        s.connect((target, 80))
                        s.send(b"HEAD / HTTP/1.0\r\n\r\n")
                        resp = s.recv(1024).decode("utf-8", errors="ignore")
                        s.close()
                        if "Server:" in resp:
                            for line in resp.split("\n"):
                                if line.startswith("Server:"):
                                    server = line.split(":", 1)[1].strip()
                                    if "nginx" in server.lower():
                                        os_detected = "Linux (Nginx)"
                                    elif "apache" in server.lower():
                                        os_detected = "Linux/Unix (Apache)"
                                    elif "iis" in server.lower() or "microsoft" in server.lower():
                                        os_detected = "Windows (IIS)"
                                    else:
                                        os_detected = f"推测 Linux/Unix ({server})"
                    except:
                        try:
                            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            s.settimeout(1)
                            if s.connect_ex((target, 3389)) == 0:
                                os_detected = "Windows (RDP开放)"
                            s.close()
                        except:
                            pass

                    result = {
                        "target": target,
                        "start": start,
                        "end": end,
                        "open_ports": open_ports,
                        "os_detected": os_detected
                    }
                    write_log("端口扫描", f"目标: {target}, 开放端口: {len(open_ports)}")
            except ValueError:
                result = {"error": "端口必须是数字"}

    return render_template("network_tools.html",
                           result=result,
                           result_type=result_type,
                           username=session["username"],
                           permission=session["permission"])


# ---------- 网络工具 API ----------
@app.route("/api/network/ping", methods=["POST"])
@login_required
@vip_required
def api_network_ping():
    """Ping 检测"""
    data = request.get_json() or {}
    target = (data.get("target") or "").strip()
    count = min(int(data.get("count") or 4), 20)
    if not target:
        return jsonify({"ok": False, "error": "Target required"}), 400
    # 安全过滤：只允许域名和IP
    if not re.match(r'^[a-zA-Z0-9.\-:]+$', target):
        return jsonify({"ok": False, "error": "Invalid target"}), 400
    import subprocess, shlex
    cmd = ["ping", "-c", str(count), target]
    if platform.system() == "Windows":
        cmd = ["ping", "-n", str(count), target]
    try:
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=15, text=True)
        return jsonify({"ok": True, "output": output})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Ping timeout"}), 408
    except subprocess.CalledProcessError as e:
        return jsonify({"ok": True, "output": e.output or "Ping failed"})
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "ping command not available"}), 500


@app.route("/api/network/traceroute", methods=["POST"])
@login_required
@vip_required
def api_network_traceroute():
    """路由追踪"""
    data = request.get_json() or {}
    target = (data.get("target") or "").strip()
    if not target:
        return jsonify({"ok": False, "error": "Target required"}), 400
    if not re.match(r'^[a-zA-Z0-9.\-:]+$', target):
        return jsonify({"ok": False, "error": "Invalid target"}), 400
    import subprocess
    cmd = ["traceroute", "-m", "15", "-w", "3", target]
    if platform.system() == "Windows":
        cmd = ["tracert", "-h", "15", "-w", "3000", target]
    try:
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=30, text=True)
        return jsonify({"ok": True, "output": output})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Traceroute timeout"}), 408
    except subprocess.CalledProcessError as e:
        return jsonify({"ok": True, "output": e.output or "Traceroute failed"})
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "traceroute command not available"}), 500


@app.route("/api/network/whois", methods=["POST"])
@login_required
@vip_required
def api_network_whois():
    """Whois 查询"""
    data = request.get_json() or {}
    target = (data.get("target") or "").strip()
    if not target:
        return jsonify({"ok": False, "error": "Target required"}), 400
    if not re.match(r'^[a-zA-Z0-9.\-]+$', target):
        return jsonify({"ok": False, "error": "Invalid target"}), 400
    import subprocess
    try:
        output = subprocess.check_output(["whois", target], stderr=subprocess.STDOUT, timeout=10, text=True)
        return jsonify({"ok": True, "output": output})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Whois timeout"}), 408
    except subprocess.CalledProcessError as e:
        return jsonify({"ok": True, "output": e.output or "Whois query failed"})
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "whois command not available"}), 500


@app.route("/api/network/dns", methods=["POST"])
@login_required
@vip_required
def api_network_dns():
    """DNS 记录解析"""
    data = request.get_json() or {}
    target = (data.get("target") or "").strip()
    record_type = (data.get("type") or "A").upper()
    if not target:
        return jsonify({"ok": False, "error": "Target required"}), 400
    if not re.match(r'^[a-zA-Z0-9.\-]+$', target):
        return jsonify({"ok": False, "error": "Invalid target"}), 400
    valid_types = {"A", "AAAA", "MX", "NS", "TXT", "CNAME", "SOA"}
    if record_type not in valid_types:
        return jsonify({"ok": False, "error": f"Invalid record type. Valid: {', '.join(sorted(valid_types))}"}), 400
    results = []
    try:
        if record_type == "A":
            import socket as sock
            try:
                results = [sock.gethostbyname(target)]
            except sock.gaierror as ge:
                return jsonify({"ok": False, "error": str(ge)}), 400
        elif record_type == "AAAA":
            try:
                info = socket.getaddrinfo(target, None, socket.AF_INET6)
                results = list(set(addr[4][0] for addr in info))
            except socket.gaierror:
                results = []
        elif record_type in ("MX", "NS", "TXT", "CNAME", "SOA"):
            # 使用 dig 或 nslookup
            import subprocess
            if record_type == "MX":
                cmd = ["dig", "+short", "MX", target]
            elif record_type == "NS":
                cmd = ["dig", "+short", "NS", target]
            elif record_type == "TXT":
                cmd = ["dig", "+short", "TXT", target]
            elif record_type == "CNAME":
                cmd = ["dig", "+short", "CNAME", target]
            else:
                cmd = ["dig", "+short", "SOA", target]
            try:
                out = subprocess.check_output(cmd, timeout=5, text=True).strip()
                results = [line.strip('"') for line in out.split("\n") if line.strip()] if out else []
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
                # 回退到 nslookup
                try:
                    nscmd = ["nslookup", "-type=" + record_type.lower(), target]
                    out = subprocess.check_output(nscmd, timeout=5, text=True)
                    results = [out]
                except Exception:
                    return jsonify({"ok": False, "error": "DNS tools (dig/nslookup) not available"}), 500
        return jsonify({"ok": True, "results": results, "type": record_type})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/network/http_headers", methods=["POST"])
@login_required
@vip_required
def api_network_http_headers():
    """HTTP 响应头检查"""
    data = request.get_json() or {}
    target = (data.get("target") or "").strip()
    if not target:
        return jsonify({"ok": False, "error": "Target required"}), 400
    if not target.startswith(("http://", "https://")):
        target = "https://" + target
    try:
        resp = requests.get(target, timeout=10, allow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) SchoolWeb/1.0"
        })
        headers = dict(resp.headers)
        return jsonify({
            "ok": True,
            "url": resp.url,
            "status_code": resp.status_code,
            "reason": resp.reason,
            "headers": headers,
            "redirect_count": len(resp.history),
        })
    except requests.RequestException as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/network/ssl", methods=["POST"])
@login_required
@vip_required
def api_network_ssl():
    """SSL 证书检查"""
    data = request.get_json() or {}
    target = (data.get("target") or "").strip()
    if not target:
        return jsonify({"ok": False, "error": "Target required"}), 400
    if not re.match(r'^[a-zA-Z0-9.\-]+$', target):
        return jsonify({"ok": False, "error": "Invalid target"}), 400
    import ssl
    from datetime import datetime
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((target, 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=target) as ssock:
                cert = ssock.getpeercert()
        subject = dict(x[0] for x in cert.get("subject", []))
        issuer = dict(x[0] for x in cert.get("issuer", []))
        not_before = cert.get("notBefore", "")
        not_after = cert.get("notAfter", "")
        # 解析日期
        from datetime import datetime
        try:
            nb = datetime.strptime(not_before, "%b %d %H:%M:%S %Y %Z")
        except Exception:
            nb = None
        try:
            na = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
        except Exception:
            na = None
        days_left = None
        if na:
            days_left = (na - datetime.now()).days
        return jsonify({
            "ok": True,
            "subject": subject,
            "issuer": issuer,
            "not_before": not_before,
            "not_after": not_after,
            "days_left": days_left,
            "san": cert.get("subjectAltName", []),
            "version": cert.get("version"),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/network/subnet", methods=["POST"])
@login_required
@vip_required
def api_network_subnet():
    """子网计算器"""
    import ipaddress
    data = request.get_json() or {}
    cidr = (data.get("cidr") or "").strip()
    if not cidr:
        return jsonify({"ok": False, "error": "CIDR notation required (e.g. 192.168.1.0/24)"}), 400
    try:
        net = ipaddress.ip_network(cidr, strict=False)
        hosts = list(net.hosts())
        return jsonify({
            "ok": True,
            "network_address": str(net.network_address),
            "broadcast_address": str(net.broadcast_address),
            "netmask": str(net.netmask),
            "hostmask": str(net.hostmask),
            "num_addresses": net.num_addresses,
            "usable_hosts": max(0, net.num_addresses - 2),
            "first_host": str(hosts[0]) if hosts else "N/A",
            "last_host": str(hosts[-1]) if hosts else "N/A",
            "is_private": net.is_private,
            "is_global": net.is_global,
        })
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# ---------- 路由：数据库 ----------
@app.route("/db_query", methods=["GET", "POST"])
@login_required
@non_guest_required
@db_captcha_required
def db_query():
    tables = []
    data = None
    columns = []
    selected_table = ""

    conn = get_db()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SHOW TABLES")
            tables = [r[0] for r in cursor.fetchall()]
            cursor.close()
            conn.close()
        except:
            pass

    if request.method == "POST":
        selected_table = request.form.get("table", "")
        if selected_table and selected_table in tables:
            conn = get_db()
            if conn:
                try:
                    cursor = conn.cursor()
                    # 使用反引号包裹表名防止注入（并通过白名单校验）
                    cursor.execute(f"SELECT * FROM `{selected_table}`")
                    columns = [desc[0] for desc in cursor.description] if cursor.description else []
                    raw_data = cursor.fetchall()
                    # 密码列脱敏
                    data = [
                        tuple(_mask_cell(col, val) if val is not None else "" for col, val in zip(columns, row))
                        for row in raw_data
                    ]
                    cursor.close()
                    conn.close()
                except pymysql.MySQLError as e:
                    flash(f"查询失败: {str(e)}", "danger")

    return render_template("db_query.html",
                           tables=tables,
                           data=data,
                           columns=columns,
                           selected_table=selected_table,
                           username=session["username"],
                           permission=session["permission"])


# ---------- API：数据库表数据 ----------
@app.route("/api/table/<table>/data")
@login_required
@admin_required
@db_captcha_required
def api_table_data(table):
    conn = get_db()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        # 白名单校验：确认表存在
        cursor.execute("SHOW TABLES")
        valid_tables = [r[0] for r in cursor.fetchall()]
        if table not in valid_tables:
            return jsonify({"error": "表不存在"}), 404
        cursor.execute(f"DESCRIBE `{table}`")
        cols = cursor.fetchall()
        cursor.execute(f"SELECT * FROM `{table}`")
        rows = cursor.fetchall()
        column_names = [c[0] for c in cols]
        column_types = [c[1] for c in cols]
        primary_key = cols[0][0] if any(c[3] == "PRI" for c in cols) else cols[0][0]
        cursor.close()
        conn.close()
        return jsonify({
            "columns": column_names,
            "types": column_types,
            "primary_key": primary_key,
            "rows": [[
                _mask_cell(col_name, cell) if cell is not None else ""
                for col_name, cell in zip(column_names, row)
            ] for row in rows]
        })
    except pymysql.MySQLError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/table/<table>/insert", methods=["POST"])
@login_required
@admin_required
@db_captcha_required
def api_table_insert(table):
    data = request.get_json()
    if not data:
        return jsonify({"error": "无数据"}), 400
    conn = get_db()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        cols = ", ".join(f"`{k}`" for k in data.keys())
        vals = ", ".join("%s" for _ in data)
        sql = f"INSERT INTO `{table}` ({cols}) VALUES ({vals})"
        cursor.execute(sql, list(data.values()))
        conn.commit()
        cursor.close()
        conn.close()
        write_log("插入数据", f"表: {table}, 用户: {session['username']}")
        return jsonify({"success": True, "affected": cursor.rowcount})
    except pymysql.MySQLError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/table/<table>/update", methods=["POST"])
@login_required
@admin_required
@db_captcha_required
def api_table_update(table):
    data = request.get_json()
    if not data or "pk" not in data or "pk_col" not in data:
        return jsonify({"error": "缺少主键信息"}), 400
    pk_col = data["pk_col"]
    pk_val = data["pk"]
    fields = {k: v for k, v in data["fields"].items()}
    if not fields:
        return jsonify({"error": "无更新字段"}), 400
    conn = get_db()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        set_clause = ", ".join(f"`{k}` = %s" for k in fields.keys())
        sql = f"UPDATE `{table}` SET {set_clause} WHERE `{pk_col}` = %s"
        cursor.execute(sql, list(fields.values()) + [pk_val])
        conn.commit()
        cursor.close()
        conn.close()
        write_log("更新数据", f"表: {table}, 主键: {pk_col}={pk_val}, 用户: {session['username']}")
        return jsonify({"success": True, "affected": cursor.rowcount})
    except pymysql.MySQLError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/table/<table>/delete/<path:pk_val>")
@login_required
@admin_required
@db_captcha_required
def api_table_delete(table, pk_val):
    pk_col = request.args.get("pk_col", "")
    if not pk_col:
        return jsonify({"error": "缺少主键字段"}), 400
    conn = get_db()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        sql = f"DELETE FROM `{table}` WHERE `{pk_col}` = %s"
        cursor.execute(sql, [pk_val])
        conn.commit()
        cursor.close()
        conn.close()
        write_log("删除数据", f"表: {table}, 主键: {pk_col}={pk_val}, 用户: {session['username']}")
        return jsonify({"success": True, "affected": cursor.rowcount})
    except pymysql.MySQLError as e:
        return jsonify({"error": str(e)}), 500


# ---------- 路由：更改数据库（可视化） ----------
@app.route("/db_update")
@login_required
@admin_required
@db_captcha_required
def db_update():
    conn = get_db()
    tables = []
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SHOW TABLES")
            tables = [r[0] for r in cursor.fetchall()]
            cursor.close()
            conn.close()
        except:
            pass
    return render_template("db_update.html",
                           tables=tables,
                           username=session["username"],
                           permission=session["permission"])


# ---------- 路由：文件管理器 ----------
# ---------- 路由：毕业相册 ----------
ALBUM_DIR = os.path.join(os.path.dirname(__file__), "static", "albums")
os.makedirs(ALBUM_DIR, exist_ok=True)

@app.route("/album")
@login_required
def album():
    """Vue3 前端 - 开发时返回 Vite dev 代理，生产时返回构建文件"""
    # 尝试返回构建后的文件
    dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")
    if os.path.exists(os.path.join(dist, "index.html")):
        return send_from_directory(dist, "index.html")
    # fallback: 开发模式 → Vite dev server
    return render_template("album_vue3.html",
                           username=session["username"],
                           permission=session["permission"])


@app.route("/assets/<path:filename>")
def serve_assets(filename):
    """服务 Vite 构建的静态资源"""
    dist_assets = os.path.join(os.path.dirname(__file__), "frontend", "dist", "assets")
    return send_from_directory(dist_assets, filename)


@app.route("/api/album/images")
@login_required
def api_album_images():
    category = request.args.get("category", "graduation")
    sort = request.args.get("sort", "newest")
    search = request.args.get("search", "").strip()
    tag_id = request.args.get("tag_id", "").strip()
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    _init_album_tables(conn)
    try:
        cursor = conn.cursor()
        join_clause = ""
        where = "WHERE category=%s"
        params = [category]
        if search:
            where += " AND name LIKE %s"
            params.append(f"%{search}%")
        if tag_id:
            join_clause = " JOIN album_image_tags ait ON album_images.id=ait.image_id"
            where += " AND ait.tag_id=%s"
            params.append(int(tag_id))
        # 非管理员只看已审核的，管理员看所有
        if session.get("permission") != "administrator":
            where += " AND (COALESCE(album_images.status, 'approved') = 'approved')"
        order = "ORDER BY upload_time DESC" if sort == "newest" else "ORDER BY upload_time ASC"
        cursor.execute(f"SELECT DISTINCT album_images.id, category, name, filename, uploader, uploader_name, upload_time, COALESCE(album_images.status,'approved') FROM album_images{join_clause} {where} {order}", params)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify([{
            "id": r[0], "category": r[1], "name": r[2], "filename": r[3],
            "uploader": r[4], "uploaderName": r[5],
            "uploadTime": r[6].strftime("%Y-%m-%d %H:%M") if r[6] else "",
            "status": r[7] if len(r) > 7 else "approved"
        } for r in rows])
    except pymysql.MySQLError as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/album/images/<int:img_id>", methods=["PUT", "DELETE"])
@login_required
def api_album_image_manage(img_id):
    if session["permission"] != "administrator":
        return jsonify({"error": "权限不足"}), 403
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500

    if request.method == "PUT":
        # 修改名称
        data = request.get_json()
        new_name = sanitize_input(data.get("name", "") if data else "", 100).strip()
        if not new_name:
            return jsonify({"error": "名称不能为空"}), 400
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE album_images SET name=%s WHERE id=%s", [new_name, img_id])
            conn.commit()
            cursor.close()
            conn.close()
            write_log("修改图片名", f"用户: {session['username']}, 图片ID: {img_id}, 新名: {new_name}")
            return jsonify({"success": True})
        except pymysql.MySQLError as e:
            return jsonify({"error": str(e)}), 500

    if request.method == "DELETE":
        try:
            cursor = conn.cursor()
            # 先查文件名
            cursor.execute("SELECT filename FROM album_images WHERE id=%s", [img_id])
            row = cursor.fetchone()
            if not row:
                cursor.close(); conn.close()
                return jsonify({"error": "图片不存在"}), 404
            filename = row[0]
            # 删数据库记录（级联删评论、点赞、分享链接）
            cursor.execute("DELETE FROM album_likes WHERE image_id=%s", [img_id])
            cursor.execute("DELETE FROM album_image_comments WHERE image_id=%s", [img_id])
            cursor.execute("DELETE FROM album_share_links WHERE image_id=%s", [img_id])
            cursor.execute("DELETE FROM album_images WHERE id=%s", [img_id])
            conn.commit()
            cursor.close()
            conn.close()
            # 删文件
            filepath = os.path.join(ALBUM_DIR, filename)
            if os.path.exists(filepath):
                os.remove(filepath)
            write_log("删除图片", f"用户: {session['username']}, 图片ID: {img_id}, 文件: {filename}")
            return jsonify({"success": True})
        except pymysql.MySQLError as e:
            return jsonify({"error": str(e)}), 500

    return jsonify({"error": "未知操作"}), 400


# ---------- 照片审核（管理员） ----------
@app.route("/api/album/pending")
@login_required
def api_album_pending():
    """获取待审核照片"""
    if session.get("permission") != "administrator":
        return jsonify({"error": "权限不足"}), 403
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, category, name, filename, uploader, uploader_name, upload_time FROM album_images WHERE status='pending' ORDER BY upload_time DESC"
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify([{
            "id": r[0], "category": r[1], "name": r[2], "filename": r[3],
            "uploader": r[4], "uploaderName": r[5],
            "uploadTime": r[6].strftime("%Y-%m-%d %H:%M") if r[6] else ""
        } for r in rows])
    except pymysql.MySQLError as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/album/pending/count")
@login_required
def api_album_pending_count():
    """待审核照片数量"""
    if session.get("permission") != "administrator":
        return jsonify({"count": 0})
    conn = get_album_db()
    if not conn:
        return jsonify({"count": 0})
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM album_images WHERE status='pending'")
        count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return jsonify({"count": count})
    except Exception:
        return jsonify({"count": 0})

@app.route("/api/album/images/<int:img_id>/approve", methods=["POST"])
@login_required
def api_album_image_approve(img_id):
    """审核通过照片"""
    if session.get("permission") != "administrator":
        return jsonify({"error": "权限不足"}), 403
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE album_images SET status='approved' WHERE id=%s AND status='pending'", [img_id])
        conn.commit()
        affected = cursor.rowcount
        cursor.close()
        conn.close()
        if affected:
            write_log("审核通过照片", f"管理员: {session['username']}, 图片ID: {img_id}")
            return jsonify({"success": True, "message": "照片已审核通过"})
        return jsonify({"error": "照片不存在或无需审核"}), 404
    except pymysql.MySQLError as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/album/images/<int:img_id>/reject", methods=["POST"])
@login_required
def api_album_image_reject(img_id):
    """拒绝照片（删除）"""
    if session.get("permission") != "administrator":
        return jsonify({"error": "权限不足"}), 403
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT filename FROM album_images WHERE id=%s AND status='pending'", [img_id])
        row = cursor.fetchone()
        if not row:
            cursor.close(); conn.close()
            return jsonify({"error": "待审核照片不存在"}), 404
        filename = row[0]
        cursor.execute("DELETE FROM album_likes WHERE image_id=%s", [img_id])
        cursor.execute("DELETE FROM album_image_comments WHERE image_id=%s", [img_id])
        cursor.execute("DELETE FROM album_images WHERE id=%s", [img_id])
        conn.commit()
        cursor.close()
        conn.close()
        filepath = os.path.join(ALBUM_DIR, filename)
        if os.path.exists(filepath):
            os.remove(filepath)
        write_log("拒绝照片", f"管理员: {session['username']}, 图片ID: {img_id}")
        return jsonify({"success": True, "message": "照片已拒绝删除"})
    except pymysql.MySQLError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/album/upload", methods=["POST"])
@login_required
@non_guest_required
def api_album_upload():
    file = request.files.get("image")
    if not file or not file.filename:
        return jsonify({"error": "未选择文件"}), 400
    if not file.content_type or not file.content_type.startswith("image/"):
        return jsonify({"error": "仅支持图片格式"}), 400

    # 限制文件大小（10MB）
    MAX_FILE_SIZE = 10 * 1024 * 1024
    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)
    if file_size > MAX_FILE_SIZE:
        return jsonify({"error": "文件大小不能超过 10MB"}), 400

    # 验证文件魔数
    header = file.read(12)
    file.seek(0)
    MAGIC_NUMBERS = {
        b"\xff\xd8\xff": ".jpg",
        b"\x89PNG\r\n\x1a\n": ".png",
        b"GIF87a": ".gif",
        b"GIF89a": ".gif",
        b"RIFF": ".webp",
        b"BM": ".bmp",
    }
    ext = ".jpg"
    detected = False
    for magic, magic_ext in MAGIC_NUMBERS.items():
        if header[:len(magic)] == magic:
            ext = magic_ext
            detected = True
            break
    if not detected:
        return jsonify({"error": "文件格式不合法，仅允许 jpg/png/gif/webp/bmp"}), 400

    import uuid
    save_name = f"{uuid.uuid4().hex}{ext}"
    file.save(os.path.join(ALBUM_DIR, save_name))

    category = request.form.get("category", "graduation")
    name = sanitize_input(request.form.get("name", ""), 100).strip() or file.filename[:100]

    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    try:
        cursor = conn.cursor()
        # 确保 status 列存在
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA='sample' AND TABLE_NAME='album_images' AND COLUMN_NAME='status'
        """)
        has_status = cursor.fetchone()[0] > 0
        if not has_status:
            cursor.execute("ALTER TABLE album_images ADD COLUMN status VARCHAR(20) DEFAULT 'approved'")
            conn.commit()

        upload_status = "approved" if session.get("permission") == "administrator" else "pending"
        cursor.execute(
            """INSERT INTO album_images (category, name, filename, uploader, uploader_name, status)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            [category, name, save_name, session["username"], session["username"], upload_status]
        )
        conn.commit()
        img_id = cursor.lastrowid
        cursor.close()
        conn.close()
        write_log("上传图片", f"用户: {session['username']}, 图片: {name}, ID: {img_id}")
        record_activity(session["username"], "上传图片", 5)
        is_approved = session.get("permission") == "administrator"
        return jsonify({"success": True, "id": img_id, "approved": is_approved})
    except pymysql.MySQLError as e:
        return jsonify({"error": str(e)}), 500


# ---------- 点赞 ----------
@app.route("/api/album/images/<int:img_id>/like", methods=["GET", "POST", "DELETE"])
@login_required
@non_guest_required
def api_album_like(img_id):
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    user = session["username"]

    if request.method == "GET":
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM album_likes WHERE image_id=%s", [img_id])
            count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM album_likes WHERE image_id=%s AND user=%s", [img_id, user])
            liked = cursor.fetchone()[0] > 0
            cursor.close()
            conn.close()
            return jsonify({"count": count, "liked": liked})
        except pymysql.MySQLError as e:
            return jsonify({"error": str(e)}), 500

    if request.method == "POST":
        try:
            cursor = conn.cursor()
            cursor.execute("INSERT IGNORE INTO album_likes (image_id, user) VALUES (%s, %s)", [img_id, user])
            conn.commit()
            cursor.close()
            conn.close()
            return jsonify({"success": True})
        except pymysql.MySQLError as e:
            return jsonify({"error": str(e)}), 500

    if request.method == "DELETE":
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM album_likes WHERE image_id=%s AND user=%s", [img_id, user])
            conn.commit()
            cursor.close()
            conn.close()
            return jsonify({"success": True})
        except pymysql.MySQLError as e:
            return jsonify({"error": str(e)}), 500


# ---------- 下载图片 ----------
@app.route("/api/album/images/<int:img_id>/download")
@login_required
def api_album_download(img_id):
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT filename, name FROM album_images WHERE id=%s", [img_id])
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if not row:
            return jsonify({"error": "找不到图片"}), 404
        filename, name = row
        # 保留原始文件后缀
        _, ext = os.path.splitext(filename)
        safe_name = (name if name else filename)
        if ext and not safe_name.lower().endswith(ext.lower()):
            safe_name += ext
        return send_from_directory(ALBUM_DIR, filename, as_attachment=True, download_name=safe_name)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------- 分享链接 ----------

@app.route("/api/album/images/<int:img_id>/share", methods=["GET", "POST"])
@login_required
def api_album_share(img_id):
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500

    if request.method == "POST":
        token = uuid.uuid4().hex
        try:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO album_share_links (image_id, token) VALUES (%s, %s)", [img_id, token])
            conn.commit()
            cursor.close()
            conn.close()
            link = f"{request.host_url}share/{token}"
            return jsonify({"link": link, "token": token})
        except pymysql.MySQLError as e:
            return jsonify({"error": str(e)}), 500

    if request.method == "GET":
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT token FROM album_share_links WHERE image_id=%s ORDER BY created_at DESC LIMIT 1", [img_id])
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            if row:
                link = f"{request.host_url}share/{row[0]}"
                return jsonify({"link": link})
            return jsonify({"link": None})
        except pymysql.MySQLError as e:
            return jsonify({"error": str(e)}), 500


@app.route("/share/<token>")
def share_view(token):
    conn = get_album_db()
    if not conn:
        return "<h2>页面不存在</h2>", 404
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ai.id, ai.name, ai.filename, ai.uploader, ai.upload_time,
                   (SELECT COUNT(*) FROM album_likes WHERE image_id=ai.id) as likes
            FROM album_share_links sl
            JOIN album_images ai ON ai.id = sl.image_id
            WHERE sl.token=%s
        """, [token])
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if not row:
            return "<h2>链接无效或已过期</h2>", 404
        img_id, name, filename, uploader, upload_time, likes = row
        time_str = upload_time.strftime("%Y-%m-%d %H:%M") if upload_time else ""
        return f"""
        <!DOCTYPE html>
        <html><head><meta charset="UTF-8"><title>{name} - 分享</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>body{{margin:0;background:#222;display:flex;align-items:center;justify-content:center;min-height:100vh;font-family:sans-serif}}
        .box{{background:#fff;border-radius:12px;padding:20px;max-width:800px;margin:20px;text-align:center}}
        img{{max-width:100%;max-height:70vh;border-radius:8px}}
        .info{{margin-top:12px;color:#666;font-size:14px}}
        h2{{margin:8px 0;color:#333}}</style></head>
        <body><div class="box">
        <img src="/static/albums/{filename}">
        <h2>{name}</h2>
        <div class="info">{uploader} · {time_str} · ♥ {likes}</div>
        </div></body></html>
        """
    except Exception as e:
        return f"<h2>加载失败: {str(e)}</h2>", 500

@app.route("/api/album/images/<int:img_id>/comments")
@login_required
def api_album_image_comments(img_id):
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, author, author_name, text, time FROM album_image_comments WHERE image_id=%s ORDER BY time ASC",
            [img_id]
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify([{
            "id": r[0], "author": r[1], "authorName": r[2], "text": r[3],
            "time": r[4].strftime("%Y-%m-%d %H:%M") if r[4] else ""
        } for r in rows])
    except pymysql.MySQLError as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/album/images/<int:img_id>/comments", methods=["POST"])
@login_required
def api_album_add_image_comment(img_id):
    data = request.get_json()
    text = sanitize_input(data.get("text", "") if data else "", 500)
    if not text:
        return jsonify({"error": "内容不能为空"}), 400
    reply_to = data.get("reply_to") if data else None
    reply_user = sanitize_input(data.get("reply_user", "") if data else "", 50) or None
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    try:
        cursor = conn.cursor()
        if reply_to:
            cursor.execute(
                "INSERT INTO album_image_comments (image_id, reply_to, reply_user, author, author_name, text) VALUES (%s,%s,%s,%s,%s,%s)",
                [img_id, reply_to, reply_user, session["username"], session["username"], text]
            )
        else:
            cursor.execute(
                "INSERT INTO album_image_comments (image_id, author, author_name, text) VALUES (%s,%s,%s,%s)",
                [img_id, session["username"], session["username"], text]
            )
        conn.commit()
        cid = cursor.lastrowid
        cursor.close()
        conn.close()
        write_log("图片评论", f"用户: {session['username']}, 图片ID: {img_id}")
        record_activity(session["username"], "评论", 2)
        return jsonify({"success": True, "id": cid})
    except pymysql.MySQLError as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/album/comments")
@login_required
def api_album_general_comments():
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, author, author_name, text, time FROM album_general_comments ORDER BY time DESC")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify([{
            "id": r[0], "author": r[1], "authorName": r[2], "text": r[3],
            "time": r[4].strftime("%Y-%m-%d %H:%M") if r[4] else ""
        } for r in rows])
    except pymysql.MySQLError as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/album/comments", methods=["POST"])
@login_required
def api_album_add_general_comment():
    data = request.get_json()
    text = sanitize_input(data.get("text", "") if data else "", 500)
    if not text:
        return jsonify({"error": "内容不能为空"}), 400
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO album_general_comments (author, author_name, text) VALUES (%s,%s,%s)",
            [session["username"], session["username"], text]
        )
        conn.commit()
        cid = cursor.lastrowid
        cursor.close()
        conn.close()
        write_log("总体留言", f"用户: {session['username']}")
        return jsonify({"success": True, "id": cid})
    except pymysql.MySQLError as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/album/comments/<int:cid>", methods=["DELETE"])
@login_required
def api_album_general_comment_delete(cid):
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    cursor = conn.cursor()
    cursor.execute("SELECT author FROM album_general_comments WHERE id=%s", (cid,))
    row = cursor.fetchone()
    if not row:
        return jsonify({"error": "留言不存在"}), 404
    is_admin = session.get("permission") == "administrator"
    is_owner = row[0] == session.get("username")
    if not is_admin and not is_owner:
        return jsonify({"error": "只能删除自己的留言"}), 403
    cursor.execute("DELETE FROM album_general_comments WHERE id=%s", (cid,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/album/stats")
@login_required
def api_album_stats():
    conn = get_album_db()
    if not conn:
        return jsonify({}), 500
    try:
        cursor = conn.cursor()
        # 上传排行榜
        cursor.execute("SELECT uploader, COUNT(*) as cnt FROM album_images GROUP BY uploader ORDER BY cnt DESC LIMIT 5")
        top_uploaders = [{"user": r[0], "count": r[1]} for r in cursor.fetchall()]
        # 评论排行榜
        cursor.execute("SELECT author, COUNT(*) as cnt FROM album_image_comments GROUP BY author ORDER BY cnt DESC LIMIT 5")
        top_commenters = [{"user": r[0], "count": r[1]} for r in cursor.fetchall()]
        # 最受欢迎图片
        cursor.execute("""
            SELECT ai.id, ai.name, ai.filename, COUNT(al.id) as likes
            FROM album_images ai LEFT JOIN album_likes al ON al.image_id=ai.id
            GROUP BY ai.id ORDER BY likes DESC LIMIT 5
        """)
        top_liked = [{"id": r[0], "name": r[1], "filename": r[2], "likes": r[3]} for r in cursor.fetchall()]
        # 总数
        cursor.execute("SELECT COUNT(*) FROM album_images")
        total_images = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM album_image_comments")
        total_comments = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM album_likes")
        total_likes = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return jsonify({
            "totalImages": total_images, "totalComments": total_comments, "totalLikes": total_likes,
            "topUploaders": top_uploaders, "topCommenters": top_commenters, "topLiked": top_liked
        })
    except pymysql.MySQLError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/album/me")
@login_required
def api_album_me():
    return jsonify({
        "username": session["username"],
        "permission": session["permission"],
        "isTeacher": session["permission"] == "administrator"
    })

# ===== 新功能 API =====

# --- 📅 大事记时间轴 ---
@app.route("/api/album/events")
def api_album_events():
    conn = get_album_db()
    if not conn:
        return jsonify([])
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM album_events ORDER BY event_date DESC")
    cols = [d[0] for d in cursor.description]
    rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    for r in rows:
        r["event_date"] = str(r["event_date"])
        r["created_at"] = str(r["created_at"])
    return jsonify(rows)

@app.route("/api/album/events", methods=["POST"])
@login_required
@admin_required
def api_album_events_add():
    data = request.get_json()
    title = sanitize_input(data.get("title", ""))
    desc = sanitize_input(data.get("description", ""), 2000)
    event_date = (data or {}).get("event_date", "")
    if not title or not event_date:
        return jsonify({"error": "标题和日期必填"}), 400
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO album_events (title, description, event_date, created_by) VALUES (%s,%s,%s,%s)",
        (title, desc, event_date, session["username"])
    )
    conn.commit()
    eid = cursor.lastrowid
    cursor.close()
    conn.close()
    return jsonify({"success": True, "id": eid})

@app.route("/api/album/events/<int:eid>", methods=["DELETE"])
@login_required
@admin_required
def api_album_events_delete(eid):
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    cursor = conn.cursor()
    cursor.execute("DELETE FROM album_events WHERE id=%s", (eid,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"success": True})

# --- 👥 同学录 ---
@app.route("/api/album/classmates")
def api_album_classmates():
    conn = get_album_db()
    if not conn:
        return jsonify([])
    cursor = conn.cursor()
    class_filter = request.args.get("class", "").strip()
    if class_filter:
        cursor.execute("SELECT * FROM album_classmates WHERE class_name=%s ORDER BY name", (class_filter,))
    else:
        cursor.execute("SELECT * FROM album_classmates ORDER BY class_name, name")
    cols = [d[0] for d in cursor.description]
    rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
    for r in rows:
        if r.get("birthday"): r["birthday"] = str(r["birthday"])
        if r.get("created_at"): r["created_at"] = str(r["created_at"])
        r["class_name"] = r.get("class_name") or ""
        r["graduation_year"] = r.get("graduation_year") or ""
    cursor.close()
    conn.close()
    return jsonify(rows)

@app.route("/api/album/classmates", methods=["POST"])
@login_required
def api_album_classmates_add():
    data = request.get_json()
    name = sanitize_input(data.get("name", ""))
    if not name:
        return jsonify({"error": "姓名必填"}), 400
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO album_classmates (name, nickname, avatar_url, birthday, phone, email, motto, interests, future_plan, class_name, graduation_year, created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (name, sanitize_input(data.get("nickname","")), sanitize_input(data.get("avatar_url",""),500),
         data.get("birthday","") or None, sanitize_input(data.get("phone","")), sanitize_input(data.get("email","")),
         sanitize_input(data.get("motto",""),500), sanitize_input(data.get("interests",""),500),
         sanitize_input(data.get("future_plan",""),500), sanitize_input(data.get("class_name",""),30),
         sanitize_input(data.get("graduation_year",""),20), session["username"])
    )
    conn.commit()
    cid = cursor.lastrowid
    cursor.close()
    conn.close()
    return jsonify({"success": True, "id": cid})

@app.route("/api/album/classmates/<int:cid>", methods=["PUT"])
@login_required
def api_album_classmates_update(cid):
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    cursor = conn.cursor()
    cursor.execute("SELECT created_by FROM album_classmates WHERE id=%s", (cid,))
    row = cursor.fetchone()
    if not row:
        cursor.close(); conn.close()
        return jsonify({"error": "记录不存在"}), 404
    created_by = row[0]
    # 创建者或管理员可以编辑
    if session["username"] != created_by and session.get("permission") != "administrator":
        cursor.close(); conn.close()
        return jsonify({"error": "不可更改，只有创建者或管理员可以编辑"}), 403
    data = request.get_json()
    name = sanitize_input(data.get("name", ""))
    if not name:
        cursor.close(); conn.close()
        return jsonify({"error": "姓名必填"}), 400
    cursor.execute(
        """UPDATE album_classmates SET name=%s, nickname=%s, avatar_url=%s, birthday=%s, phone=%s, 
           email=%s, motto=%s, interests=%s, future_plan=%s, class_name=%s, graduation_year=%s
           WHERE id=%s""",
        (name, sanitize_input(data.get("nickname","")), sanitize_input(data.get("avatar_url",""),500),
         data.get("birthday","") or None, sanitize_input(data.get("phone","")), sanitize_input(data.get("email","")),
         sanitize_input(data.get("motto",""),500), sanitize_input(data.get("interests",""),500),
         sanitize_input(data.get("future_plan",""),500), sanitize_input(data.get("class_name",""),30),
         sanitize_input(data.get("graduation_year",""),20), cid)
    )
    conn.commit()
    cursor.close(); conn.close()
    return jsonify({"success": True})

@app.route("/api/album/classmates/<int:cid>", methods=["DELETE"])
@login_required
@admin_required
def api_album_classmates_delete(cid):
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    cursor = conn.cursor()
    cursor.execute("DELETE FROM album_classmates WHERE id=%s", (cid,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"success": True})

# --- 🎓 毕业寄语墙 ---
@app.route("/api/album/wishes")
def api_album_wishes():
    conn = get_album_db()
    if not conn:
        return jsonify([])
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM album_wishes ORDER BY created_at DESC")
    cols = [d[0] for d in cursor.description]
    rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
    for r in rows:
        r["created_at"] = str(r["created_at"])
    cursor.close()
    conn.close()
    return jsonify(rows)

@app.route("/api/album/wishes", methods=["POST"])
@login_required
def api_album_wishes_add():
    data = request.get_json()
    content = sanitize_input(data.get("content", ""), 500)
    if not content:
        return jsonify({"error": "内容不能为空"}), 400
    is_anon = 1 if data.get("is_anonymous") else 0
    colors = ["#FF6B6B","#4ECDC4","#45B7D1","#96CEB4","#FFEAA7","#DDA0DD","#98D8C8","#F7DC6F","#BB8FCE","#85C1E9"]
    color = random.choice(colors)
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO album_wishes (author, is_anonymous, content, avatar_color) VALUES (%s,%s,%s,%s)",
        (session["username"], is_anon, content, color)
    )
    conn.commit()
    wid = cursor.lastrowid
    cursor.close()
    conn.close()
    record_activity(session["username"], "寄语", 2)
    return jsonify({"success": True, "id": wid})

@app.route("/api/album/wishes/<int:wid>", methods=["DELETE"])
@login_required
def api_album_wishes_delete(wid):
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    cursor = conn.cursor()
    # 检查所有权：本人或管理员可删除
    cursor.execute("SELECT author FROM album_wishes WHERE id=%s", (wid,))
    row = cursor.fetchone()
    if not row:
        return jsonify({"error": "寄语不存在"}), 404
    is_admin = session.get("permission") == "administrator"
    is_owner = row[0] == session.get("username")
    if not is_admin and not is_owner:
        return jsonify({"error": "只能删除自己的寄语"}), 403
    cursor.execute("DELETE FROM album_wishes WHERE id=%s", (wid,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"success": True})

# --- 🏷️ 照片标签 ---
@app.route("/api/album/tags")
def api_album_tags():
    conn = get_album_db()
    if not conn:
        return jsonify([])
    _init_album_tables(conn)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM album_tags ORDER BY name")
    cols = [d[0] for d in cursor.description]
    rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify(rows)

@app.route("/api/album/tags", methods=["POST"])
@login_required
def api_album_tags_add():
    data = request.get_json()
    name = sanitize_input(data.get("name", ""))
    color = sanitize_input(data.get("color", "#04c"))
    if not name:
        return jsonify({"error": "标签名必填"}), 400
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    _init_album_tables(conn)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO album_tags (name,color) VALUES (%s,%s)", (name, color))
        conn.commit()
        tid = cursor.lastrowid
        cursor.close()
        conn.close()
        record_activity(session["username"], "标签", 1)
        return jsonify({"success": True, "id": tid})
    except pymysql.MySQLError:
        return jsonify({"error": "标签已存在"}), 400

@app.route("/api/album/tags/<int:tid>", methods=["DELETE"])
@login_required
def api_album_tags_delete(tid):
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    _init_album_tables(conn)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM album_image_tags WHERE tag_id=%s", (tid,))
    cursor.execute("DELETE FROM album_tags WHERE id=%s", (tid,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/album/images/<int:img_id>/tags")
def api_album_image_tags(img_id):
    conn = get_album_db()
    if not conn:
        return jsonify([])
    _init_album_tables(conn)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.id, t.name, t.color FROM album_tags t
        JOIN album_image_tags it ON it.tag_id=t.id
        WHERE it.image_id=%s ORDER BY t.name
    """, (img_id,))
    rows = [{"id": r[0], "name": r[1], "color": r[2]} for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify(rows)

@app.route("/api/album/images/<int:img_id>/tags", methods=["POST"])
@login_required
def api_album_image_tags_set(img_id):
    data = request.get_json()
    tag_ids = (data or {}).get("tag_ids", [])
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    _init_album_tables(conn)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM album_image_tags WHERE image_id=%s", (img_id,))
    for tid in tag_ids:
        cursor.execute("INSERT IGNORE INTO album_image_tags (image_id, tag_id) VALUES (%s,%s)", (img_id, tid))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"success": True})

# --- 🎵 毕业歌单 ---
@app.route("/api/album/playlist")
def api_album_playlist():
    conn = get_album_db()
    if not conn:
        return jsonify([])
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM album_playlist ORDER BY votes DESC, created_at DESC")
    cols = [d[0] for d in cursor.description]
    rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
    for r in rows:
        r["created_at"] = str(r["created_at"])
    cursor.close()
    conn.close()
    return jsonify(rows)

@app.route("/api/album/playlist", methods=["POST"])
@login_required
def api_album_playlist_add():
    data = request.get_json()
    title = sanitize_input(data.get("title", ""))
    artist = sanitize_input(data.get("artist", ""))
    url = sanitize_input(data.get("url", ""), 500)
    if not title:
        return jsonify({"error": "歌名必填"}), 400
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO album_playlist (title, artist, url, added_by) VALUES (%s,%s,%s,%s)",
        (title, artist, url, session["username"])
    )
    conn.commit()
    pid = cursor.lastrowid
    cursor.close()
    conn.close()
    record_activity(session["username"], "歌单", 2)
    return jsonify({"success": True, "id": pid})

@app.route("/api/album/playlist/<int:pid>/vote", methods=["POST"])
@login_required
def api_album_playlist_vote(pid):
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    cursor = conn.cursor()
    cursor.execute("UPDATE album_playlist SET votes=votes+1 WHERE id=%s", (pid,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/album/playlist/<int:pid>", methods=["DELETE"])
@login_required
@admin_required
def api_album_playlist_delete(pid):
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    cursor = conn.cursor()
    cursor.execute("DELETE FROM album_playlist WHERE id=%s", (pid,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"success": True})

# --- 💬 弹幕 ---
@app.route("/api/album/images/<int:img_id>/danmaku")
def api_album_danmaku(img_id):
    conn = get_album_db()
    if not conn:
        return jsonify([])
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM album_danmaku WHERE image_id=%s ORDER BY created_at", (img_id,))
    cols = [d[0] for d in cursor.description]
    rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
    for r in rows:
        r["created_at"] = str(r["created_at"])
    cursor.close()
    conn.close()
    return jsonify(rows)

@app.route("/api/album/images/<int:img_id>/danmaku", methods=["POST"])
@login_required
def api_album_danmaku_add(img_id):
    data = request.get_json()
    text = sanitize_input(data.get("text", ""), 200)
    color = sanitize_input(data.get("color", "#fff"))
    position = float((data or {}).get("position", 50))
    if not text:
        return jsonify({"error": "弹幕内容不能为空"}), 400
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO album_danmaku (image_id, text, color, position, author) VALUES (%s,%s,%s,%s,%s)",
        (img_id, text, color, position, session["username"])
    )
    conn.commit()
    did = cursor.lastrowid
    cursor.close()
    conn.close()
    record_activity(session["username"], "弹幕", 1)
    return jsonify({"success": True, "id": did})


# ===== 💬 聊天系统 API =====

@app.route("/api/chat/messages")
def api_chat_messages():
    """获取聊天记录"""
    channel = request.args.get("channel", "world")
    before = request.args.get("before", "")  # 翻页
    limit = min(int(request.args.get("limit", 50)), 100)
    conn = get_album_db()
    if not conn:
        return jsonify([])
    cursor = conn.cursor()
    if channel == "world":
        sql = "SELECT id, channel, sender, content, created_at FROM chat_messages WHERE channel='world'"
        params = []
    else:
        user = session.get("username", "")
        other = request.args.get("with", "")
        if not user or not other:
            return jsonify([])
        sql = "SELECT id, channel, sender, content, created_at FROM chat_messages WHERE channel='dm' AND ((sender=%s AND recipient=%s) OR (sender=%s AND recipient=%s))"
        params = [user, other, other, user]
    if before:
        sql += " AND id < %s"
        params.append(int(before))
    sql += " ORDER BY id DESC LIMIT %s"
    params.append(limit)
    cursor.execute(sql, params)
    cols = [d[0] for d in cursor.description]
    rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
    for r in rows:
        r["created_at"] = str(r["created_at"])
    cursor.close()
    conn.close()
    rows.reverse()
    return jsonify(rows)

@app.route("/api/chat/send", methods=["POST"])
@login_required
def api_chat_send():
    """发送消息"""
    data = request.get_json()
    channel = (data or {}).get("channel", "world")
    content = sanitize_input((data or {}).get("content", ""), 1000)
    recipient = sanitize_input((data or {}).get("recipient", ""), 50) if channel == "dm" else None
    if not content:
        return jsonify({"error": "消息不能为空"}), 400
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO chat_messages (channel, sender, recipient, content) VALUES (%s,%s,%s,%s)",
        (channel, session["username"], recipient, content)
    )
    conn.commit()
    mid = cursor.lastrowid
    cursor.close()
    conn.close()
    record_activity(session["username"], "聊天", 1)
    return jsonify({"success": True, "id": mid})

# 搜索用户
@app.route("/api/chat/search")
@login_required
def api_chat_search():
    q = sanitize_input(request.args.get("q", ""), 50)
    if not q:
        return jsonify([])
    conn = get_db()
    if not conn:
        return jsonify([])
    cursor = conn.cursor()
    cursor.execute("SELECT User_Name FROM users WHERE User_Name LIKE %s AND User_Name != %s LIMIT 10",
                   (f"%{q}%", session["username"]))
    users = [r[0] for r in cursor.fetchall()]
    # 也查 user_profiles 的昵称
    cursor.execute("""
        SELECT u.User_Name, p.nickname FROM users u
        LEFT JOIN user_profiles p ON p.username = u.User_Name
        WHERE (u.User_Name LIKE %s OR p.nickname LIKE %s) AND u.User_Name != %s LIMIT 10
    """, (f"%{q}%", f"%{q}%", session["username"]))
    results = [{"username": r[0], "nickname": r[1] or r[0]} for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify(results)

# 好友操作
@app.route("/api/chat/friends")
@login_required
def api_chat_friends():
    user = session["username"]
    conn = get_album_db()
    if not conn:
        return jsonify([])
    cursor = conn.cursor()
    cursor.execute("""
        SELECT user1, user2, status, requester
        FROM friendships WHERE (user1=%s OR user2=%s) AND status='accepted'
    """, (user, user))
    friends = []
    for r in cursor.fetchall():
        friend = r[0] if r[1] == user else r[1]
        friends.append({"username": friend})
    # 获取好友昵称
    for f in friends:
        cursor.execute("SELECT nickname FROM user_profiles WHERE username=%s", (f["username"],))
        row = cursor.fetchone()
        f["nickname"] = row[0] if row else f["username"]
    cursor.close()
    conn.close()
    return jsonify(friends)

@app.route("/api/chat/friends/requests")
@login_required
def api_chat_friend_requests():
    user = session["username"]
    conn = get_album_db()
    if not conn:
        return jsonify([])
    cursor = conn.cursor()
    cursor.execute("""
        SELECT user1, user2, requester FROM friendships
        WHERE user2=%s AND status='pending'
    """, (user,))
    requests = [{"from": r[0], "nickname": r[0]} for r in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify(requests)

@app.route("/api/chat/friends/request", methods=["POST"])
@login_required
def api_chat_friend_request():
    data = request.get_json()
    target = sanitize_input((data or {}).get("username", ""), 50)
    if not target or target == session["username"]:
        return jsonify({"error": "无效用户"}), 400
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO friendships (user1, user2, requester) VALUES (%s,%s,%s)",
            (session["username"], target, session["username"])
        )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"success": True})
    except pymysql.MySQLError:
        return jsonify({"error": "已发送过好友请求"}), 400

@app.route("/api/chat/friends/accept", methods=["POST"])
@login_required
def api_chat_friend_accept():
    data = request.get_json()
    other = sanitize_input((data or {}).get("username", ""), 50)
    user = session["username"]
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE friendships SET status='accepted' WHERE user1=%s AND user2=%s AND status='pending'",
        (other, user)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/chat/friends/remove", methods=["POST"])
@login_required
def api_chat_friend_remove():
    data = request.get_json()
    other = sanitize_input((data or {}).get("username", ""), 50)
    user = session["username"]
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM friendships WHERE (user1=%s AND user2=%s) OR (user1=%s AND user2=%s)",
        (user, other, other, user)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/chat/messages/<int:mid>", methods=["DELETE"])
@login_required
def api_chat_recall(mid):
    """撤回消息（仅发送者本人）"""
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    cursor = conn.cursor()
    cursor.execute("SELECT sender, content FROM chat_messages WHERE id=%s", (mid,))
    row = cursor.fetchone()
    if not row:
        return jsonify({"error": "消息不存在"}), 404
    if row[0] != session["username"] and session.get("permission") != "administrator":
        return jsonify({"error": "只能撤回自己的消息"}), 403
    # 标记撤回而非物理删除
    cursor.execute("UPDATE chat_messages SET content=%s WHERE id=%s", ("[消息已撤回]", mid))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"success": True})



def _safe_realpath(path):
    """确保路径是真实路径且不包含 '..' 路径穿越"""
    path = os.path.realpath(path)
    # 限制在用户主目录下
    allowed_base = os.path.realpath(os.path.expanduser("~"))
    if not path.startswith(allowed_base):
        return allowed_base
    return path


@app.route("/file_manager", methods=["GET", "POST"])
@login_required
@non_guest_required
@fm_password_required
def file_manager():
    current_path = _safe_realpath(request.form.get("path", os.path.expanduser("~")))
    dirs = []
    files = []
    error = ""

    if request.method == "POST" and "go_up" in request.form:
        parent = os.path.dirname(current_path)
        current_path = _safe_realpath(parent)

    try:
        items = os.listdir(current_path)
        for item in sorted(items):
            full = os.path.join(current_path, item)
            if os.path.isdir(full):
                dirs.append(item)
            else:
                try:
                    size = os.path.getsize(full)
                    if size < 1024:
                        size_str = f"{size} B"
                    elif size < 1024**2:
                        size_str = f"{size/1024:.1f} KB"
                    else:
                        size_str = f"{size/(1024**2):.1f} MB"
                except:
                    size_str = "?"
                files.append({"name": item, "size": size_str})
    except PermissionError:
        error = "没有权限访问该目录"
    except Exception as e:
        error = str(e)

    return render_template("file_manager.html",
                           current_path=current_path,
                           dirs=dirs,
                           files=files,
                           error=error,
                           username=session["username"],
                           permission=session["permission"])


# ---------- 文件管理器 API：上传 ----------
@app.route("/api/file/upload", methods=["POST"])
@login_required
def api_file_upload():
    target_dir = _safe_realpath(request.form.get("path", os.path.expanduser("~")))
    if "file" not in request.files:
        return jsonify({"error": "未选择文件"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "未选择文件"}), 400
    # 安全文件名
    safe_name = re.sub(r"[^\w\-.]", "_", f.filename)
    if not safe_name:
        return jsonify({"error": "无效文件名"}), 400
    # 大小限制 50MB
    f.seek(0, 2)
    size = f.tell()
    f.seek(0)
    if size > 50 * 1024 * 1024:
        return jsonify({"error": "文件不能超过50MB"}), 400
    dest = os.path.join(target_dir, safe_name)
    try:
        f.save(dest)
        write_log("文件管理上传", f"文件: {safe_name}, 路径: {target_dir}, 操作者: {session['username']}")
        return jsonify({"success": True, "name": safe_name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------- 文件管理器 API：下载（仅管理员） ----------
@app.route("/api/file/download", methods=["GET"])
@login_required
def api_file_download():
    filepath = _safe_realpath(request.args.get("path", ""))
    if not os.path.isfile(filepath):
        return jsonify({"error": "文件不存在"}), 404
    dir_name = os.path.dirname(filepath)
    file_name = os.path.basename(filepath)
    # 确认路径穿越防护
    if _safe_realpath(filepath) != filepath:
        return jsonify({"error": "路径非法"}), 403
    return send_from_directory(dir_name, file_name, as_attachment=True)


# ---------- 文件管理器 API：删除（仅管理员） ----------
@app.route("/api/file/delete", methods=["POST"])
@login_required
@admin_required
def api_file_delete():
    filepath = _safe_realpath(request.form.get("path", ""))
    if not os.path.isfile(filepath):
        return jsonify({"error": "文件不存在"}), 404
    try:
        os.remove(filepath)
        write_log("文件管理删除", f"文件: {filepath}, 操作者: {session['username']}")
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------- 路由：备忘录 ----------
NOTES_FILE = os.path.join(os.path.dirname(__file__), "..", "notes.txt")

# ---------- 路由：修改密码 ----------
@app.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    users = []
    is_admin = (session["permission"] == "administrator")

    if is_admin:
        conn = get_db()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT User_Name FROM users")
                users = [r[0] for r in cursor.fetchall()]
                cursor.close()
                conn.close()
            except:
                pass

    if request.method == "POST":
        # 修改密码
        current_user = session["username"]
        target_user = sanitize_input(request.form.get("target_user", current_user), 50)
        old_pwd = request.form.get("old_pwd", "").strip()
        new_pwd = request.form.get("new_pwd", "").strip()
        confirm_pwd = request.form.get("confirm_pwd", "").strip()
        captcha_input = request.form.get("captcha", "").strip().lower()

        # 验证码校验
        stored_code = session.get("captcha_code", "")
        captcha_time = session.get("captcha_time", 0)

        if not stored_code:
            flash("验证码已失效，请刷新", "danger")
        elif time.time() - captcha_time > 300:
            session.pop("captcha_code", None)
            flash("验证码已过期，请刷新", "danger")
        elif captcha_input != stored_code:
            session.pop("captcha_code", None)
            flash("验证码错误", "danger")
        elif not new_pwd or not confirm_pwd:
            flash("新密码和确认密码不能为空", "danger")
        elif new_pwd != confirm_pwd:
            flash("两次输入的新密码不一致", "danger")
        elif len(new_pwd) < 8:
            flash("新密码长度不能少于8位", "danger")
        elif not re.search(r"[A-Za-z]", new_pwd):
            flash("新密码必须包含至少一个字母", "danger")
        elif not re.search(r"[0-9]", new_pwd):
            flash("新密码必须包含至少一个数字", "danger")
        else:
            # 验证通过，清除验证码
            session.pop("captcha_code", None)
            session.pop("captcha_time", None)
            conn = get_db()
            if conn:
                try:
                    cursor = conn.cursor()
                    hashed_new = generate_password_hash(new_pwd)
                    if is_admin:
                        cursor.execute(
                            "UPDATE users SET User_Password = %s WHERE User_Name = %s",
                            (hashed_new, target_user)
                        )
                    else:
                        cursor.execute(
                            "SELECT User_Password FROM users WHERE User_Name = %s",
                            (current_user,)
                        )
                        result = cursor.fetchone()
                        if not result or not check_password_hash(result[0], old_pwd):
                            flash("原密码错误", "danger")
                            cursor.close()
                            conn.close()
                            return render_template("change_password.html",
                                                   is_admin=is_admin, users=users,
                                                   username=session["username"],
                                                   permission=session["permission"])
                        cursor.execute(
                            "UPDATE users SET User_Password = %s WHERE User_Name = %s",
                            (hashed_new, current_user)
                        )
                    conn.commit()
                    affected = cursor.rowcount
                    cursor.close()
                    conn.close()
                    if affected > 0:
                        write_log("修改密码", f"操作者: {current_user}, 目标: {target_user}")
                        flash(f"用户 {sanitize_input(target_user)} 的密码已修改", "success")
                    else:
                        flash("修改密码失败", "danger")
                except pymysql.MySQLError as e:
                    flash(f"修改失败: {str(e)}", "danger")

    return render_template("change_password.html",
                           is_admin=is_admin, users=users,
                           username=session["username"],
                           permission=session["permission"])


# ---------- 路由：备忘录 ----------
@app.route("/notes", methods=["GET", "POST"])
@login_required
def notes():
    content = ""
    if os.path.exists(NOTES_FILE):
        with open(NOTES_FILE, "r", encoding="utf-8") as f:
            content = f.read()

    if request.method == "POST":
        content = request.form.get("content", "")[:50000]  # 限制 50KB
        with open(NOTES_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        flash("备忘录已保存", "success")

    return render_template("notes.html",
                           content=content,
                           username=session["username"],
                           permission=session["permission"])


# ---------- 路由：计算器 ----------
@app.route("/calculator")
@login_required
def calculator():
    return render_template("calculator.html",
                           username=session["username"],
                           permission=session["permission"])

@app.route("/calculator/sci")
@login_required
def calculator_sci():
    return render_template("calculator_sci.html",
                           username=session["username"],
                           permission=session["permission"])

@app.route("/calculator/net")
@login_required
def calculator_net():
    return render_template("calculator_net.html",
                           username=session["username"],
                           permission=session["permission"])

# ---------- 路由：日志 ----------
# ---------- 路由：管理后台 ----------
@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    pending_admin_reqs = 0
    try:
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM admin_requests WHERE status='pending'")
            pending_admin_reqs = cursor.fetchone()[0]
            cursor.close()
            conn.close()
    except Exception:
        pass
    leaderboard = get_leaderboard(10)
    return render_template("admin_dashboard.html",
                           username=session["username"],
                           permission=session["permission"],
                           leaderboard=leaderboard,
                           pending_admin_reqs=pending_admin_reqs)


@app.route("/api/admin/ip_stats")
@login_required
@admin_required
def api_admin_ip_stats():
    """返回所有IP的请求统计"""
    now = time.time()
    result = []
    with rate_lock:
        for ip, q in list(ip_requests.items()):
            count = len(q)
            first_req = q[0] if q else now
            last_req = q[-1] if q else now
            result.append({
                "ip": ip,
                "requests": count,
                "first_request": datetime.datetime.fromtimestamp(first_req).strftime("%H:%M:%S"),
                "last_request": datetime.datetime.fromtimestamp(last_req).strftime("%H:%M:%S"),
                "rate_per_sec": round(count / max(now - first_req, 1), 2) if count > 1 else count,
                "blocked": False,
                "block_remaining": 0
            })
        for ip, blocked_until in list(ip_blocked.items()):
            if now < blocked_until:
                result.append({
                    "ip": ip,
                    "requests": 0,
                    "first_request": "-",
                    "last_request": "-",
                    "rate_per_sec": 0,
                    "blocked": True,
                    "block_remaining": int(blocked_until - now),
                    "block_probes": ip_blocked_probes.get(ip, 0)
                })
    with session_lock:
        for ip, last_active in list(ip_last_active.items()):
            for r in result:
                if r["ip"] == ip:
                    r["last_active"] = datetime.datetime.fromtimestamp(last_active).strftime("%H:%M:%S") if last_active else "-"
                    r["idle_sec"] = int(now - last_active) if last_active else 0
                    break
    result.sort(key=lambda x: x["requests"], reverse=True)
    # 标记白名单和手动封禁
    for r in result:
        r["whitelisted"] = r["ip"] in ip_whitelist
        r["manual_blocked"] = r["ip"] in ip_manual_blocked and now < ip_manual_blocked.get(r["ip"], 0)
        if r["manual_blocked"]:
            r["manual_block_remaining"] = int(ip_manual_blocked[r["ip"]] - now)
    return jsonify({
        "ips": result,
        "total_tracked": len(result),
        "total_blocked": sum(1 for r in result if r["blocked"]),
        "total_whitelisted": len(ip_whitelist),
        "rate_limit": rate_config["RATE_LIMIT"],
        "rate_window": rate_config["RATE_WINDOW"],
        "block_duration": rate_config["BLOCK_DURATION"],
        "block_probe_limit": rate_config["BLOCK_PROBE_LIMIT"],
        "block_extend": rate_config["BLOCK_EXTEND"]
    })


@app.route("/api/admin/ip_stats", methods=["DELETE"])
@login_required
@admin_required
def api_admin_clear_ip_stats():
    """清除IP统计"""
    ip = request.args.get("ip")
    with rate_lock:
        if ip:
            ip_requests.pop(ip, None)
            ip_blocked.pop(ip, None)
            ip_blocked_probes.pop(ip, None)
            ip_manual_blocked.pop(ip, None)
            ip_whitelist.discard(ip)
        else:
            ip_requests.clear()
            ip_blocked.clear()
            ip_blocked_probes.clear()
            ip_manual_blocked.clear()
            ip_whitelist.clear()
    _save_whitelist()
    return jsonify({"success": True})


@app.route("/api/admin/unblock", methods=["POST"])
@login_required
@admin_required
def api_admin_unblock():
    """解封指定IP"""
    data = request.get_json()
    ip = (data or {}).get("ip", "").strip()
    if not ip:
        return jsonify({"error": "未提供IP"}), 400
    with rate_lock:
        ip_blocked.pop(ip, None)
        ip_blocked_probes.pop(ip, None)
        ip_manual_blocked.pop(ip, None)
    write_log("管理后台解封IP", f"IP: {ip}, 操作者: {session['username']}")
    return jsonify({"success": True})


@app.route("/api/admin/whitelist", methods=["GET"])
@login_required
@admin_required
def api_admin_whitelist_list():
    """获取白名单列表"""
    with rate_lock:
        return jsonify({"whitelist": sorted(ip_whitelist), "count": len(ip_whitelist)})


@app.route("/api/admin/whitelist", methods=["POST"])
@login_required
@admin_required
def api_admin_whitelist_add():
    """添加IP到白名单"""
    data = request.get_json()
    ip = (data or {}).get("ip", "").strip()
    if not ip:
        return jsonify({"error": "未提供IP"}), 400
    with rate_lock:
        ip_whitelist.add(ip)
        # 同时清除该IP的封禁状态
        ip_blocked.pop(ip, None)
        ip_blocked_probes.pop(ip, None)
        ip_manual_blocked.pop(ip, None)
        ip_requests.pop(ip, None)
    _save_whitelist()
    write_log("管理后台添加白名单", f"IP: {ip}, 操作者: {session['username']}")
    return jsonify({"success": True, "count": len(ip_whitelist)})


@app.route("/api/admin/whitelist", methods=["DELETE"])
@login_required
@admin_required
def api_admin_whitelist_remove():
    """从白名单移除IP"""
    ip = request.args.get("ip", "").strip()
    if not ip:
        return jsonify({"error": "未提供IP"}), 400
    with rate_lock:
        ip_whitelist.discard(ip)
    _save_whitelist()
    write_log("管理后台移除白名单", f"IP: {ip}, 操作者: {session['username']}")
    return jsonify({"success": True, "count": len(ip_whitelist)})


@app.route("/api/admin/manual_block", methods=["POST"])
@login_required
@admin_required
def api_admin_manual_block():
    """手动封禁IP（可指定时长，默认1小时）"""
    data = request.get_json()
    ip = (data or {}).get("ip", "").strip()
    duration = int((data or {}).get("duration", 3600))  # 默认1小时
    if not ip:
        return jsonify({"error": "未提供IP"}), 400
    with rate_lock:
        # 不能封禁白名单IP
        if ip in ip_whitelist:
            return jsonify({"error": "该IP在白名单中，无法封禁"}), 400
        ip_manual_blocked[ip] = time.time() + duration
        ip_requests.pop(ip, None)
    write_log("管理后台手动封禁", f"IP: {ip}, 时长: {duration}s, 操作者: {session['username']}")
    return jsonify({"success": True, "until": int(time.time() + duration)})


@app.route("/api/admin/batch", methods=["POST"])
@login_required
@admin_required
def api_admin_batch():
    """批量操作：添加白名单 / 手动封禁"""
    data = request.get_json()
    action = (data or {}).get("action")  # "whitelist" 或 "block"
    ips_raw = (data or {}).get("ips", "")
    duration = int((data or {}).get("duration", 3600))

    # 解析IP列表（支持逗号、空格、换行分隔）
    ips = []
    for part in re.split(r"[,;\s\n]+", ips_raw):
        part = part.strip()
        if part:
            ips.append(part)
    if not ips:
        return jsonify({"error": "未提供有效IP"}), 400

    success, skipped, failed = [], [], []
    with rate_lock:
        for ip in ips:
            if ip in ip_whitelist and action == "whitelist":
                skipped.append(ip)
                continue
            if action == "whitelist":
                ip_whitelist.add(ip)
                ip_blocked.pop(ip, None)
                ip_blocked_probes.pop(ip, None)
                ip_manual_blocked.pop(ip, None)
                ip_requests.pop(ip, None)
                success.append(ip)
            elif action == "block":
                if ip in ip_whitelist:
                    skipped.append(ip)
                    continue
                ip_manual_blocked[ip] = time.time() + duration
                ip_requests.pop(ip, None)
                success.append(ip)
            else:
                failed.append(ip)

    if action == "whitelist":
        _save_whitelist()
    write_log(f"管理后台批量{action}", f"IP: {ips}, 成功: {len(success)}, 跳过: {len(skipped)}, 操作者: {session['username']}")
    return jsonify({"success": True, "added": success, "skipped": skipped, "failed": failed})


# ---------- 速率限制配置 API ----------
@app.route("/api/admin/rate_config", methods=["GET"])
@login_required
@admin_required
def api_admin_rate_config_get():
    """获取速率限制配置"""
    return jsonify(dict(rate_config))

@app.route("/api/admin/rate_config", methods=["POST"])
@login_required
@admin_required
def api_admin_rate_config_set():
    """修改速率限制配置"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "无数据"}), 400
    changed = []
    for key in ["RATE_LIMIT", "RATE_WINDOW", "BLOCK_DURATION", "BLOCK_PROBE_LIMIT", "BLOCK_EXTEND"]:
        if key in data:
            val = int(data[key])
            if val <= 0:
                return jsonify({"error": f"{key} 必须为正数"}), 400
            rate_config[key] = val
            changed.append(f"{key}={val}")
    _save_rate_config()
    write_log("管理后台修改速率配置", f"{', '.join(changed)}, 操作者: {session['username']}")
    return jsonify({"success": True, "config": dict(rate_config)})


@app.route("/logs")
@login_required
@admin_required
def logs():
    log_content = read_logs()
    return render_template("logs.html",
                           log_content=log_content,
                           username=session["username"],
                           permission=session["permission"])


@app.route("/logs/clear")
@login_required
@admin_required
def logs_clear():
    try:
        ip = request.remote_addr or "0.0.0.0"
        user = session.get("username", "unknown")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        clear_entry = f"[{now}] 清空日志 - IP: {ip}, 用户: {user}\n"
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write(clear_entry)
        flash("日志已清空", "info")
    except:
        flash("清空日志失败", "danger")
    return redirect(url_for("logs"))


# ---------- 全局错误处理：不泄露内部信息 ----------
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({"error": "页面不存在"}), 404
    return render_template("login.html", csrf_token=session.get("csrf_token", "")), 404

@app.errorhandler(500)
def server_error(e):
    if request.path.startswith('/api/'):
        return jsonify({"error": "服务器内部错误"}), 500
    return "<h2>服务器内部错误，请稍后重试</h2>", 500

@app.errorhandler(403)
def forbidden(e):
    if request.path.startswith('/api/'):
        return jsonify({"error": "禁止访问"}), 403
    return "<h2>禁止访问</h2>", 403


# ---------- IP 地理位置（网络请求地图） ----------
ip_geo_cache = {}  # ip -> {lat, lon, country, city, expire_time}

@app.route("/api/admin/ip_locations")
@login_required
@admin_required
def api_admin_ip_locations():
    """返回活跃 IP 的地理位置（深色地图用）"""
    now = time.time()
    # 获取活跃 IP 列表
    with rate_lock:
        active_ips = set()
        for ip in ip_requests:
            active_ips.add(ip)
        for ip, blocked_until in list(ip_blocked.items()):
            if now < blocked_until:
                active_ips.add(ip)
        for ip, blocked_until in list(ip_manual_blocked.items()):
            if now < blocked_until:
                active_ips.add(ip)
        ip_stats = {}
        for ip, q in ip_requests.items():
            ip_stats[ip] = {"requests": len(q), "blocked": False, "manual_blocked": False}
        for ip, blocked_until in list(ip_blocked.items()):
            if now < blocked_until:
                ip_stats.setdefault(ip, {})["blocked"] = True
                ip_stats.setdefault(ip, {})["requests"] = ip_stats.get(ip, {}).get("requests", 0)
        for ip, blocked_until in list(ip_manual_blocked.items()):
            if now < blocked_until:
                ip_stats.setdefault(ip, {})["manual_blocked"] = True
                ip_stats.setdefault(ip, {})["requests"] = ip_stats.get(ip, {}).get("requests", 0)

    # 使用缓存，5分钟过期
    result = []
    uncached = []
    for ip in list(active_ips):
        cached = ip_geo_cache.get(ip)
        if cached and cached["expire"] > now:
            result.append({
                "ip": ip,
                "lat": cached["lat"],
                "lon": cached["lon"],
                "country": cached["country"],
                "city": cached["city"],
                "requests": ip_stats.get(ip, {}).get("requests", 0),
                "blocked": ip_stats.get(ip, {}).get("blocked", False),
                "manual_blocked": ip_stats.get(ip, {}).get("manual_blocked", False),
            })
        else:
            uncached.append(ip)

    # 批量查询未缓存的 IP（ip-api.com 最多 100 个一批）
    if uncached:
        batch = uncached[:100]
        try:
            resp = requests.post(
                "http://ip-api.com/batch",
                json=[{"query": ip, "fields": "country,city,lat,lon,query"} for ip in batch],
                timeout=10,
            )
            if resp.status_code == 200:
                items = resp.json()
                found_ips = set()
                for item in items:
                    ip = item.get("query", "")
                    found_ips.add(ip)
                    lat = item.get("lat")
                    lon = item.get("lon")
                    if lat is not None and lon is not None:
                        entry = {
                            "lat": lat,
                            "lon": lon,
                            "country": item.get("country", ""),
                            "city": item.get("city", ""),
                            "expire": now + 300,  # 5分钟缓存
                        }
                        ip_geo_cache[ip] = entry
                        result.append({
                            "ip": ip,
                            "lat": lat,
                            "lon": lon,
                            "country": entry["country"],
                            "city": entry["city"],
                            "requests": ip_stats.get(ip, {}).get("requests", 0),
                            "blocked": ip_stats.get(ip, {}).get("blocked", False),
                            "manual_blocked": ip_stats.get(ip, {}).get("manual_blocked", False),
                        })
                    else:
                        # 内网/无法定位的IP，仅统计不画点
                        ip_geo_cache[ip] = {"lat": 0, "lon": 0, "country": "内网", "city": "", "expire": now + 300}
                        result.append({
                            "ip": ip,
                            "lat": None,
                            "lon": None,
                            "country": "内网",
                            "city": "",
                            "requests": ip_stats.get(ip, {}).get("requests", 0),
                            "blocked": ip_stats.get(ip, {}).get("blocked", False),
                            "manual_blocked": ip_stats.get(ip, {}).get("manual_blocked", False),
                        })
                # 批量查询中未返回的IP也计入（可能是ip-api限流或超时）
                for ip in batch:
                    if ip not in found_ips:
                        ip_geo_cache[ip] = {"lat": 0, "lon": 0, "country": "未知", "city": "", "expire": now + 300}
                        result.append({
                            "ip": ip,
                            "lat": None,
                            "lon": None,
                            "country": "未知",
                            "city": "",
                            "requests": ip_stats.get(ip, {}).get("requests", 0),
                            "blocked": ip_stats.get(ip, {}).get("blocked", False),
                            "manual_blocked": ip_stats.get(ip, {}).get("manual_blocked", False),
                        })
        except Exception as e:
            print(f"[IP Geo] batch lookup failed: {e}")

    # 清理过期缓存
    for ip in list(ip_geo_cache.keys()):
        if ip_geo_cache[ip]["expire"] <= now:
            del ip_geo_cache[ip]

    return jsonify(result)


# ---------- 日历 ----------
@app.route("/calendar")
@login_required
def calendar_view():
    """日历页面"""
    return render_template("calendar.html",
                           username=session["username"],
                           permission=session["permission"])


@app.route("/api/calendar/events")
@login_required
def api_calendar_events():
    """获取日历事件（支持按月查询）"""
    year = request.args.get("year", "", type=int)
    month = request.args.get("month", "", type=int)
    username = session["username"]
    is_admin = session.get("permission") == "administrator"

    conn = get_db()
    if not conn:
        return jsonify({"ok": False, "error": "Database unavailable"}), 500

    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        if year and month:
            # 查当月的第一天到最后一天
            import calendar as cal_mod
            last_day = cal_mod.monthrange(year, month)[1]
            date_from = f"{year}-{month:02d}-01"
            date_to = f"{year}-{month:02d}-{last_day:02d}"
            if is_admin:
                cursor.execute(
                    "SELECT * FROM calendar_events WHERE event_date BETWEEN %s AND %s ORDER BY event_date, event_time",
                    (date_from, date_to)
                )
            else:
                cursor.execute(
                    "SELECT * FROM calendar_events WHERE event_date BETWEEN %s AND %s AND username=%s ORDER BY event_date, event_time",
                    (date_from, date_to, username)
                )
        else:
            if is_admin:
                cursor.execute("SELECT * FROM calendar_events ORDER BY event_date DESC, event_time DESC LIMIT 100")
            else:
                cursor.execute("SELECT * FROM calendar_events WHERE username=%s ORDER BY event_date DESC, event_time DESC LIMIT 100", (username,))

        rows = cursor.fetchall()
        events = []
        for r in rows:
            events.append({
                "id": r["id"],
                "title": r["title"],
                "description": r.get("description", ""),
                "event_date": r["event_date"].isoformat() if hasattr(r["event_date"], "isoformat") else str(r["event_date"]),
                "event_time": str(r["event_time"]) if r.get("event_time") else None,
                "category": r.get("category", "other"),
                "color": r.get("color", "#3b82f6"),
                "username": r["username"],
            })
        return jsonify({"ok": True, "events": events})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/api/calendar/events", methods=["POST"])
@login_required
def api_calendar_add_event():
    """添加日历事件"""
    data = request.get_json() or {}
    title = (data.get("title") or "").strip()
    description = (data.get("description") or "").strip()
    event_date = (data.get("event_date") or "").strip()
    event_time = (data.get("event_time") or "").strip() or None
    category = (data.get("category") or "other").strip()
    color = (data.get("color") or "#3b82f6").strip()

    if not title or not event_date:
        return jsonify({"ok": False, "error": "Title and date are required"}), 400

    # 分类颜色映射
    cat_colors = {
        "class": "#3b82f6",
        "exam": "#ef4444",
        "activity": "#10b981",
        "personal": "#f59e0b",
        "holiday": "#8b5cf6",
        "other": "#6b7280",
    }
    if not data.get("color"):
        color = cat_colors.get(category, "#3b82f6")

    conn = get_db()
    if not conn:
        return jsonify({"ok": False, "error": "Database unavailable"}), 500

    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO calendar_events (username, title, description, event_date, event_time, category, color) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (session["username"], title, description, event_date, event_time, category, color)
        )
        conn.commit()
        eid = cursor.lastrowid
        record_activity(session["username"], "添加日历事件")
        return jsonify({"ok": True, "id": eid})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/api/calendar/events/<int:eid>", methods=["PUT"])
@login_required
def api_calendar_update_event(eid):
    """更新日历事件"""
    data = request.get_json() or {}
    conn = get_db()
    if not conn:
        return jsonify({"ok": False, "error": "Database unavailable"}), 500

    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        # 权限检查
        is_admin = session.get("permission") == "administrator"
        if is_admin:
            cursor.execute("SELECT * FROM calendar_events WHERE id=%s", (eid,))
        else:
            cursor.execute("SELECT * FROM calendar_events WHERE id=%s AND username=%s", (eid, session["username"]))
        ev = cursor.fetchone()
        if not ev:
            return jsonify({"ok": False, "error": "Event not found or access denied"}), 404

        updates = []
        params = []
        for field in ["title", "description", "event_date", "event_time", "category", "color"]:
            if field in data:
                updates.append(f"{field}=%s")
                params.append(data[field])
        if updates:
            params.append(eid)
            cursor.execute(f"UPDATE calendar_events SET {', '.join(updates)} WHERE id=%s", params)
            conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/api/calendar/events/<int:eid>", methods=["DELETE"])
@login_required
def api_calendar_delete_event(eid):
    """删除日历事件"""
    conn = get_db()
    if not conn:
        return jsonify({"ok": False, "error": "Database unavailable"}), 500

    try:
        cursor = conn.cursor()
        is_admin = session.get("permission") == "administrator"
        if is_admin:
            cursor.execute("DELETE FROM calendar_events WHERE id=%s", (eid,))
        else:
            cursor.execute("DELETE FROM calendar_events WHERE id=%s AND username=%s", (eid, session["username"]))
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


# ========== 💾 本地文件备份系统 ==========
BACKUP_DIR = os.path.join(os.path.dirname(__file__), "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

# 需要备份的本地文件/目录（相对项目根目录）
BACKUP_INCLUDES = [
    "static/albums",
    "static/avatars",
    "static/img",
    "ip_whitelist.json",
    "rate_config.json",
    ".secret_key",
    "templates",
    "app.py",
    "i18n.py",
    "plugins",
    "requirements.txt",
    "frontend/src",
]

# 需要排除的模式
BACKUP_EXCLUDES = [
    "__pycache__",
    "*.pyc",
    ".DS_Store",
    "node_modules",
    "backups",
    "dist",
    "build",
    ".git",
    ".idea",
    ".workflow",
]


@app.route("/backup")
@login_required
@admin_required
def backup_page():
    """备份管理页面"""
    return render_template("backup.html",
                           username=session["username"],
                           permission=session["permission"])


@app.route("/api/backup/config")
@login_required
@admin_required
def api_backup_config():
    """获取备份配置（备份哪些内容）"""
    return jsonify({
        "includes": BACKUP_INCLUDES,
        "excludes": BACKUP_EXCLUDES,
    })


def _get_backup_files():
    """获取备份目录下所有 .tar.gz 文件列表"""
    backups = []
    try:
        for f in sorted(os.listdir(BACKUP_DIR), reverse=True):
            fpath = os.path.join(BACKUP_DIR, f)
            if os.path.isfile(fpath) and f.endswith(".tar.gz"):
                stat = os.stat(fpath)
                created = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                backups.append({
                    "name": f,
                    "size": stat.st_size,
                    "created": created,
                })
    except Exception:
        pass
    return backups


@app.route("/api/backup/list")
@login_required
@admin_required
def api_backup_list():
    """列出所有备份文件"""
    return jsonify({"backups": _get_backup_files()})


@app.route("/api/backup/create", methods=["POST"])
@login_required
@admin_required
def api_backup_create():
    """创建新备份（tar.gz 打包本地文件）"""
    import subprocess
    import tarfile

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{timestamp}.tar.gz"
    filepath = os.path.join(BACKUP_DIR, filename)
    project_root = os.path.dirname(os.path.abspath(__file__))

    try:
        with tarfile.open(filepath, "w:gz") as tar:
            for inc in BACKUP_INCLUDES:
                src = os.path.join(project_root, inc)
                if os.path.exists(src):
                    # 用 arcname 保留相对路径
                    arcname = inc
                    tar.add(src, arcname=arcname,
                            filter=lambda ti: (
                                None if any(
                                    fnmatch.fnmatch(ti.name, f"*/{e}") or
                                    fnmatch.fnmatch(os.path.basename(ti.name), e)
                                    for e in BACKUP_EXCLUDES
                                ) else ti
                            ) if ti else None)

        size = os.path.getsize(filepath)

        # 统计文件数和目录结构
        file_count = 0
        dir_structure = []
        with tarfile.open(filepath, "r:gz") as tar:
            for m in tar.getmembers():
                file_count += 1
                if m.isdir() and m.name.count("/") <= 1:
                    dir_structure.append(m.name)

        write_log("创建文件备份", f"文件名: {filename}, 大小: {size/1024:.1f}KB, 文件数: {file_count}, 操作者: {session['username']}")
        record_activity(session["username"], "创建备份", 10)
        return jsonify({
            "ok": True,
            "filename": filename,
            "size": size,
            "file_count": file_count,
            "dirs": dir_structure,
            "created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
    except Exception as e:
        if os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({"ok": False, "error": f"备份失败: {str(e)}"}), 500


@app.route("/api/backup/download/<path:filename>")
@login_required
@admin_required
def api_backup_download(filename):
    """下载备份文件"""
    safe_name = os.path.basename(filename)
    if not safe_name.endswith(".tar.gz"):
        return jsonify({"error": "无效的文件名"}), 400
    filepath = os.path.join(BACKUP_DIR, safe_name)
    if not os.path.isfile(filepath):
        return jsonify({"error": "备份文件不存在"}), 404
    write_log("下载备份", f"文件名: {safe_name}, 操作者: {session['username']}")
    return send_from_directory(BACKUP_DIR, safe_name, as_attachment=True, download_name=safe_name)


@app.route("/api/backup/delete/<path:filename>", methods=["DELETE"])
@login_required
@admin_required
def api_backup_delete(filename):
    """删除单个备份文件"""
    safe_name = os.path.basename(filename)
    if not safe_name.endswith(".tar.gz"):
        return jsonify({"error": "无效的文件名"}), 400
    filepath = os.path.join(BACKUP_DIR, safe_name)
    if not os.path.isfile(filepath):
        return jsonify({"error": "备份文件不存在"}), 404
    try:
        os.remove(filepath)
        write_log("删除备份", f"文件名: {safe_name}, 操作者: {session['username']}")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/backup/delete-all", methods=["DELETE"])
@login_required
@admin_required
def api_backup_delete_all():
    """删除所有备份文件"""
    try:
        count = 0
        for f in os.listdir(BACKUP_DIR):
            if f.endswith(".tar.gz"):
                os.remove(os.path.join(BACKUP_DIR, f))
                count += 1
        write_log("清空所有备份", f"删除 {count} 个文件, 操作者: {session['username']}")
        return jsonify({"ok": True, "deleted": count})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/backup/prune", methods=["DELETE"])
@login_required
@admin_required
def api_backup_prune():
    """保留最近 N 个备份，删除旧的"""
    keep = request.args.get("keep", 10, type=int)
    if keep < 1:
        return jsonify({"error": "保留数量至少为 1"}), 400
    try:
        files = sorted([
            f for f in os.listdir(BACKUP_DIR)
            if f.endswith(".tar.gz") and os.path.isfile(os.path.join(BACKUP_DIR, f))
        ], reverse=True)
        to_delete = files[keep:]
        for f in to_delete:
            os.remove(os.path.join(BACKUP_DIR, f))
        write_log("清理旧备份", f"保留 {keep} 个, 删除 {len(to_delete)} 个, 操作者: {session['username']}")
        return jsonify({"ok": True, "deleted": len(to_delete), "kept": min(len(files), keep)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/backup/restore", methods=["POST"])
@login_required
@admin_required
def api_backup_restore():
    """从备份文件恢复本地文件（tar.gz 解压覆盖）"""
    import tarfile
    data = request.get_json()
    filename = (data or {}).get("filename", "")
    safe_name = os.path.basename(filename)
    if not safe_name.endswith(".tar.gz"):
        return jsonify({"ok": False, "error": "无效的文件名"}), 400
    filepath = os.path.join(BACKUP_DIR, safe_name)
    if not os.path.isfile(filepath):
        return jsonify({"ok": False, "error": "备份文件不存在"}), 404

    fsize = os.path.getsize(filepath)
    if fsize > 2 * 1024 * 1024 * 1024:  # 2GB
        return jsonify({"ok": False, "error": "备份文件超过 2GB，请手动恢复"}), 400

    project_root = os.path.dirname(os.path.abspath(__file__))
    restored_files = []

    try:
        with tarfile.open(filepath, "r:gz") as tar:
            for member in tar.getmembers():
                # 安全检查：防止路径穿越
                dest = os.path.normpath(os.path.join(project_root, member.name))
                if not dest.startswith(project_root):
                    continue  # 跳过路径穿越
                if member.issym() or member.islnk():
                    continue  # 跳过符号链接
                restored_files.append(member.name)
            tar.extractall(path=project_root)

        write_log("恢复文件备份",
                  f"文件名: {safe_name}, 大小: {fsize/1024:.1f}KB, 文件数: {len(restored_files)}, 操作者: {session['username']}" )
        return jsonify({
            "ok": True,
            "files_restored": len(restored_files),
            "files_list": restored_files[:100]  # 只返回前 100 个
        })
    except Exception as e:
        return jsonify({"ok": False, "error": f"恢复失败: {str(e)}"}), 500


@app.route("/api/backup/diff/<path:filename>")
@login_required
@admin_required
def api_backup_diff(filename):
    """对比当前文件与备份的文件列表差异"""
    import tarfile
    safe_name = os.path.basename(filename)
    if not safe_name.endswith(".tar.gz"):
        return jsonify({"ok": False, "error": "无效的文件名"}), 400
    filepath = os.path.join(BACKUP_DIR, safe_name)
    if not os.path.isfile(filepath):
        return jsonify({"ok": False, "error": "备份文件不存在"}), 404

    try:
        # 1. 读取备份文件清单
        backup_files = {}  # name -> size
        with tarfile.open(filepath, "r:gz") as tar:
            for m in tar.getmembers():
                if m.isfile():
                    backup_files[m.name] = m.size

        # 2. 扫描当前项目的文件清单
        project_root = os.path.dirname(os.path.abspath(__file__))
        current_files = {}
        for root, dirs, files in os.walk(project_root):
            # 跳过排除目录
            dirs[:] = [d for d in dirs if d not in ("backups", ".git", "node_modules", "__pycache__", "dist", "build", ".idea")]
            for f in files:
                if f.endswith((".pyc", ".DS_Store")):
                    continue
                full = os.path.join(root, f)
                rel = os.path.relpath(full, project_root)
                try:
                    current_files[rel] = os.path.getsize(full)
                except:
                    pass

        # 3. 对比
        diff_lines = []
        adds = dels = changes = 0
        all_keys = sorted(set(list(current_files.keys()) + list(backup_files.keys())))

        for path in all_keys:
            in_current = path in current_files
            in_backup = path in backup_files

            if in_current and not in_backup:
                diff_lines.append(f"+ {path} ({_fmt_size(current_files[path])}) — 备份中没有")
                adds += 1
            elif not in_current and in_backup:
                diff_lines.append(f"- {path} ({_fmt_size(backup_files[path])}) — 当前已不存在")
                dels += 1
            elif current_files[path] != backup_files[path]:
                diff = current_files[path] - backup_files[path]
                sign = "+" if diff > 0 else ""
                diff_lines.append(f"~ {path}: 当前 {_fmt_size(current_files[path])} vs 备份 {_fmt_size(backup_files[path])} ({sign}{_fmt_size(diff)})")
                changes += 1

        # 截断太多行
        diff_display = diff_lines[:200]
        if len(diff_lines) > 200:
            diff_display.append(f"... 还有 {len(diff_lines) - 200} 行差异未显示")

        return jsonify({
            "ok": True,
            "diff": diff_display,
            "adds": adds,
            "dels": dels,
            "changes": changes,
            "backup_file_count": len(backup_files),
            "current_file_count": len(current_files),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def _fmt_size(bytes):
    if bytes < 1024:
        return f"{bytes}B"
    elif bytes < 1024 * 1024:
        return f"{bytes/1024:.1f}KB"
    else:
        return f"{bytes/1024/1024:.1f}MB"


# ========== 📚 学习工具 ==========
@app.route("/study")
@login_required
def study_page():
    """学习工具页面"""
    return render_template("study.html",
                           username=session["username"],
                           permission=session["permission"])


# ── 待办清单 API ──
@app.route("/api/study/todos")
@login_required
def api_study_todos():
    """获取待办列表"""
    conn = get_db()
    if not conn: return jsonify([]), 500
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, title, completed, priority, due_date, created_at
            FROM study_todos WHERE username=%s
            ORDER BY completed ASC, priority DESC, due_date ASC, created_at DESC
        """, [session["username"]])
        rows = [{"id":r[0],"title":r[1],"completed":r[2],"priority":r[3],
                 "due_date":str(r[4]) if r[4] else None,"created_at":str(r[5])[:16]}
                for r in cursor.fetchall()]
        return jsonify(rows)
    finally:
        cursor.close(); conn.close()


@app.route("/api/study/todos", methods=["POST"])
@login_required
def api_study_todos_add():
    """添加待办"""
    data = request.get_json() or {}
    title = sanitize_input(data.get("title",""),200)
    if not title: return jsonify({"error":"标题不能为空"}),400
    conn = get_db()
    if not conn: return jsonify({"error":"DB"}),500
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO study_todos (username,title,priority,due_date) VALUES (%s,%s,%s,%s)",
            [session["username"],title,data.get("priority",0),data.get("due_date")]
        )
        conn.commit()
        tid = cursor.lastrowid
        record_activity(session["username"],"添加待办",1)
        return jsonify({"ok":True,"id":tid})
    finally:
        cursor.close(); conn.close()


@app.route("/api/study/todos/<int:tid>", methods=["DELETE"])
@login_required
def api_study_todos_delete(tid):
    """删除待办"""
    conn = get_db()
    if not conn: return jsonify({"error":"DB"}),500
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM study_todos WHERE id=%s AND username=%s",[tid,session["username"]])
        conn.commit()
        return jsonify({"ok":True})
    finally:
        cursor.close(); conn.close()


@app.route("/api/study/todos/<int:tid>/toggle", methods=["POST"])
@login_required
def api_study_todos_toggle(tid):
    """切换完成状态"""
    conn = get_db()
    if not conn: return jsonify({"error":"DB"}),500
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE study_todos SET completed=1-completed,
            completed_at=IF(completed=1,NULL,NOW())
            WHERE id=%s AND username=%s
        """,[tid,session["username"]])
        conn.commit()
        return jsonify({"ok":True})
    finally:
        cursor.close(); conn.close()


# ── 抽认卡 API ──
@app.route("/api/study/flashcards")
@login_required
def api_study_flashcards():
    """获取抽认卡列表"""
    conn = get_db()
    if not conn: return jsonify([]),500
    try:
        cursor = conn.cursor()
        tag = request.args.get("tag","").strip()
        if tag:
            cursor.execute(
                "SELECT id,question,answer,tags,level,reviewed_count,last_reviewed FROM study_flashcards WHERE username=%s AND tags LIKE %s ORDER BY created_at DESC",
                [session["username"],f"%{tag}%"])
        else:
            cursor.execute(
                "SELECT id,question,answer,tags,level,reviewed_count,last_reviewed FROM study_flashcards WHERE username=%s ORDER BY created_at DESC",
                [session["username"]])
        rows = [{"id":r[0],"question":r[1],"answer":r[2],"tags":r[3],"level":r[4],
                 "reviewed_count":r[5],"last_reviewed":str(r[6])[:16] if r[6] else None}
                for r in cursor.fetchall()]
        return jsonify(rows)
    finally:
        cursor.close(); conn.close()


@app.route("/api/study/flashcards", methods=["POST"])
@login_required
def api_study_flashcards_add():
    """添加抽认卡"""
    data = request.get_json() or {}
    q = sanitize_input(data.get("question",""),500)
    a = sanitize_input(data.get("answer",""),2000)
    if not q or not a: return jsonify({"error":"问题和答案不能为空"}),400
    conn = get_db()
    if not conn: return jsonify({"error":"DB"}),500
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO study_flashcards (username,question,answer,tags) VALUES (%s,%s,%s,%s)",
            [session["username"],q,a,data.get("tags","")]
        )
        conn.commit()
        record_activity(session["username"],"添加抽认卡",2)
        return jsonify({"ok":True,"id":cursor.lastrowid})
    finally:
        cursor.close(); conn.close()


@app.route("/api/study/flashcards/<int:fid>", methods=["DELETE"])
@login_required
def api_study_flashcards_delete(fid):
    """删除抽认卡"""
    conn = get_db()
    if not conn: return jsonify({"error":"DB"}),500
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM study_flashcards WHERE id=%s AND username=%s",[fid,session["username"]])
        conn.commit()
        return jsonify({"ok":True})
    finally:
        cursor.close(); conn.close()


@app.route("/api/study/flashcards/<int:fid>/review", methods=["POST"])
@login_required
def api_study_flashcards_review(fid):
    """记录复习结果"""
    data = request.get_json() or {}
    level = data.get("level",0)  # -1=忘记, 0=困难, 1=简单
    conn = get_db()
    if not conn: return jsonify({"error":"DB"}),500
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE study_flashcards
            SET level=GREATEST(0,level+%s), reviewed_count=reviewed_count+1, last_reviewed=NOW()
            WHERE id=%s AND username=%s
        """,[level+1 if level>=0 else -1, fid, session["username"]])
        conn.commit()
        record_activity(session["username"],"复习抽认卡",2)
        return jsonify({"ok":True})
    finally:
        cursor.close(); conn.close()


@app.route("/api/study/flashcards/review")
@login_required
def api_study_flashcards_next():
    """获取下一个需要复习的抽认卡"""
    conn = get_db()
    if not conn: return jsonify({"card":None}),500
    random_mode = request.args.get("random","0") == "1"
    try:
        cursor = conn.cursor()
        if random_mode:
            cursor.execute("""
                SELECT id,question,answer,tags,level,reviewed_count
                FROM study_flashcards WHERE username=%s
                ORDER BY RAND() LIMIT 1
            """,[session["username"]])
        else:
            cursor.execute("""
                SELECT id,question,answer,tags,level,reviewed_count
                FROM study_flashcards WHERE username=%s
                ORDER BY level ASC, last_reviewed ASC LIMIT 1
            """,[session["username"]])
        r = cursor.fetchone()
        if r:
            return jsonify({"card":{"id":r[0],"question":r[1],"answer":r[2],
                                     "tags":r[3],"level":r[4],"reviewed_count":r[5]}})
        return jsonify({"card":None})
    finally:
        cursor.close(); conn.close()


# ---------- 插件系统 ----------
@app.route("/plugin/<plugin_name>")
@app.route("/plugin/<plugin_name>/<path:subpath>")
def plugin_route(plugin_name, subpath=None):
    """插件路由分发"""
    loaded = plugins.get_loaded_plugins()
    if plugin_name not in loaded:
        abort(404)
    plugin_info = plugins._loaded_plugins.get(plugin_name)
    if plugin_info and plugin_info.get("module") and hasattr(plugin_info["module"], "route"):
        return plugin_info["module"].route(subpath or "")
    return f"<h2>Plugin: {plugin_name}</h2><p>This plugin has no route handler.</p>"


# ---------- 插件管理 API（管理员） ----------
@app.route("/api/admin/plugins")
@login_required
@admin_required
def api_admin_plugins_list():
    """获取所有插件列表"""
    all_plugins = plugins.discover_plugins()
    result = []
    for p in all_plugins:
        m = p["manifest"]
        result.append({
            "name": p["name"],
            "title": m.get("name", p["name"]),
            "version": m.get("version", "0.1"),
            "description": m.get("description", ""),
            "author": m.get("author", ""),
            "loaded": p["loaded"],
            "has_init": p["has_init"],
        })
    return jsonify({"ok": True, "plugins": result})


@app.route("/api/admin/plugins/<name>/load", methods=["POST"])
@login_required
@admin_required
def api_admin_plugins_load(name):
    """加载插件"""
    success, msg = plugins.load_plugin(name)
    return jsonify({"ok": success, "message": msg})


@app.route("/api/admin/plugins/<name>/unload", methods=["POST"])
@login_required
@admin_required
def api_admin_plugins_unload(name):
    """卸载插件"""
    success, msg = plugins.unload_plugin(name)
    return jsonify({"ok": success, "message": msg})


@app.route("/api/admin/plugins/reload", methods=["POST"])
@login_required
@admin_required
def api_admin_plugins_reload_all():
    """重新加载所有插件"""
    loaded = list(plugins._loaded_plugins.keys())
    for name in loaded:
        plugins.unload_plugin(name)
    plugins._create_sample_plugin()
    discovered = plugins.discover_plugins()
    results = []
    for p in discovered:
        ok, msg = plugins.load_plugin(p["name"])
        results.append({"name": p["name"], "ok": ok, "message": msg})
    return jsonify({"ok": True, "results": results})


# ---------- 插件市场目录 ----------
MARKETPLACE_DIR = os.path.join(os.path.dirname(__file__), "plugins", "marketplace")
os.makedirs(MARKETPLACE_DIR, exist_ok=True)


# ---------- 插件市场 API（管理员上传 HTML/Vue 插件） ----------
@app.route("/api/admin/plugins/marketplace/upload", methods=["POST"])
@login_required
@admin_required
def api_admin_plugin_marketplace_upload():
    """管理员上传 HTML 或 Vue 插件到市场"""
    file = request.files.get("file")
    if not file:
        return jsonify({"ok": False, "error": "请选择文件"}), 400

    filename = file.filename or "untitled"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".html", ".vue"):
        return jsonify({"ok": False, "error": "仅支持 .html 或 .vue 文件"}), 400

    file_type = "html" if ext == ".html" else "vue"

    # 安全：校验文件大小为字节对象获取真实大小
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > 5 * 1024 * 1024:  # 5MB 上限
        return jsonify({"ok": False, "error": "文件不能超过 5MB"}), 400

    # 读取文件内容并做安全扫描
    content = file.read()
    try:
        content_str = content.decode("utf-8")
    except UnicodeDecodeError:
        return jsonify({"ok": False, "error": "文件编码必须是 UTF-8"}), 400

    # 基础安全检查：拒绝包含危险标签的 HTML（防止服务端模板注入相关的）
    dangerous_patterns = [
        "{{", "}}", "{%", "%}",  # Jinja2 模板注入防护
    ]
    for pattern in dangerous_patterns:
        if pattern in content_str:
            return jsonify({"ok": False, "error": f"文件包含不安全的模板语法: {pattern}"}), 400

    # 表单参数
    plugin_name = request.form.get("plugin_name", "").strip()
    display_name = request.form.get("display_name", "").strip()
    description = request.form.get("description", "").strip()
    version = request.form.get("version", "1.0.0").strip()
    author = request.form.get("author", "").strip()
    icon = request.form.get("icon", "🧩").strip()

    # 生成唯一目录名
    safe_plugin_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", plugin_name) if plugin_name else ""
    if not safe_plugin_name:
        safe_plugin_name = "plugin_" + uuid.uuid4().hex[:8]

    # 确保不重名
    plugin_dir = os.path.join(MARKETPLACE_DIR, safe_plugin_name)
    counter = 1
    original_name = safe_plugin_name
    while os.path.exists(plugin_dir):
        safe_plugin_name = f"{original_name}_{counter}"
        plugin_dir = os.path.join(MARKETPLACE_DIR, safe_plugin_name)
        counter += 1

    os.makedirs(plugin_dir, exist_ok=True)

    # 保存文件
    dest_path = os.path.join(plugin_dir, "index" + ext)
    try:
        with open(dest_path, "wb") as f:
            f.write(content)
    except Exception as e:
        return jsonify({"ok": False, "error": f"文件保存失败: {e}"}), 500

    # 写入 manifest
    manifest = {
        "name": safe_plugin_name,
        "display_name": display_name or safe_plugin_name,
        "description": description,
        "version": version,
        "author": author,
        "file_type": file_type,
        "icon": icon,
        "uploader": session["username"],
    }
    with open(os.path.join(plugin_dir, "plugin.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # 如果是 Vue 文件，创建 wrapper HTML 用于沙箱渲染
    if file_type == "vue":
        _create_vue_wrapper(plugin_dir, safe_plugin_name, version)

    # 写入数据库
    conn = get_db()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO plugin_marketplace
                    (plugin_name, display_name, description, version, author, file_type, icon, uploader)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    display_name=VALUES(display_name),
                    description=VALUES(description),
                    version=VALUES(version),
                    file_type=VALUES(file_type),
                    icon=VALUES(icon),
                    updated_at=CURRENT_TIMESTAMP
            """, (
                safe_plugin_name,
                display_name or safe_plugin_name,
                description,
                version,
                author,
                file_type,
                icon,
                session["username"],
            ))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            pass  # 数据库可降级，文件已保存

    write_log("插件市场上传", f"插件: {display_name or safe_plugin_name} (类型:{file_type}), 上传者: {session['username']}")
    return jsonify({
        "ok": True,
        "message": "插件上传成功",
        "plugin": {
            "name": safe_plugin_name,
            "display_name": display_name or safe_plugin_name,
            "file_type": file_type,
            "version": version,
        }
    })


def _create_vue_wrapper(plugin_dir, plugin_name, version="3"):
    """为 Vue 插件创建沙箱 wrapper HTML"""
    wrapper_html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{plugin_title}</title>
<script src="https://cdn.bootcdn.net/ajax/libs/vue/3.4.21/vue.global.prod.min.js"></script>
<style>
  * {margin: 0; padding: 0; box-sizing: border-box;}
  body {font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;}
  #app {min-height: 100vh;}
</style>
</head>
<body>
<div id="app"></div>
<script type="module">
  const {createApp} = Vue;
  // 通过 fetch 加载 .vue 模板内容
  try {
    const response = await fetch("./index.vue");
    const template = await response.text();
    // 简易 SFC 解析：提取 <template>, <script>, <style>
    const templateMatch = template.match(/<template>([\\s\\S]*?)<\\/template>/i);
    const scriptMatch = template.match(/<script[^>]*>([\\s\\S]*?)<\\/script>/i);
    const styleMatch = template.match(/<style[^>]*>([\\s\\S]*?)<\\/style>/i);
    const appOptions = {
      template: templateMatch ? templateMatch[1].trim() : "<div>No template found</div>",
    };
    if (scriptMatch) {
      try {
        const scriptContent = scriptMatch[1].trim();
        const componentFunc = new Function("Vue", scriptContent + "; return (typeof defaultExport !== 'undefined' ? defaultExport : (typeof component !== 'undefined' ? component : {}) );");
        const component = componentFunc(Vue);
        if (component && typeof component === "object") {
          Object.assign(appOptions, component);
        }
      } catch (e) {
        console.error("Vue script eval failed:", e);
      }
    }
    // 注入样式
    if (styleMatch) {
      const styleEl = document.createElement("style");
      styleEl.textContent = styleMatch[1];
      document.head.appendChild(styleEl);
    }
    const app = createApp(appOptions);
    app.mount("#app");
  } catch (e) {
    document.getElementById("app").innerHTML = '<div style="padding:20px;color:red;">Plugin load error: ' + e.message + '</div>';
  }
</script>
</body>
</html>'''
    wrapper_html = wrapper_html.replace("{plugin_title}", plugin_name)
    with open(os.path.join(plugin_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(wrapper_html)


@app.route("/api/admin/plugins/marketplace")
@login_required
@admin_required
def api_admin_plugin_marketplace_list():
    """获取插件市场列表（管理员视图，含上传者信息）"""
    result = []
    conn = get_db()
    if conn:
        try:
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            cursor.execute(
                "SELECT * FROM plugin_marketplace ORDER BY updated_at DESC"
            )
            rows = cursor.fetchall()
            for r in rows:
                plugin_dir = os.path.join(MARKETPLACE_DIR, r["plugin_name"])
                result.append({
                    "id": r["id"],
                    "name": r["plugin_name"],
                    "display_name": r["display_name"],
                    "description": r.get("description", ""),
                    "version": r["version"],
                    "author": r.get("author", ""),
                    "file_type": r["file_type"],
                    "icon": r.get("icon", "🧩"),
                    "uploader": r["uploader"],
                    "created_at": r["created_at"].strftime("%Y-%m-%d %H:%M") if r.get("created_at") else "",
                    "exists_on_disk": os.path.isdir(plugin_dir),
                    "preview_url": f"/plugin-market/{r['id']}",
                })
            cursor.close()
            conn.close()
        except Exception:
            pass

    # 合并磁盘上有但数据库没有记录的文件（容错）
    if os.path.isdir(MARKETPLACE_DIR):
        for dirname in os.listdir(MARKETPLACE_DIR):
            full = os.path.join(MARKETPLACE_DIR, dirname)
            if os.path.isdir(full):
                manifest_path = os.path.join(full, "plugin.json")
                if os.path.exists(manifest_path):
                    try:
                        with open(manifest_path, "r", encoding="utf-8") as f:
                            m = json.load(f)
                        db_names = {r["name"] for r in result}
                        if dirname not in db_names:
                            result.append({
                                "id": None,
                                "name": dirname,
                                "display_name": m.get("display_name", dirname),
                                "description": m.get("description", ""),
                                "version": m.get("version", "1.0.0"),
                                "author": m.get("author", ""),
                                "file_type": m.get("file_type", "html"),
                                "icon": m.get("icon", "🧩"),
                                "uploader": m.get("uploader", "?"),
                                "created_at": "",
                                "exists_on_disk": True,
                                "preview_url": f"/plugin-market-raw/{dirname}",
                            })
                    except Exception:
                        pass

    return jsonify({"ok": True, "plugins": result})


@app.route("/api/admin/plugins/marketplace/<int:plugin_id>", methods=["DELETE"])
@login_required
@admin_required
def api_admin_plugin_marketplace_delete(plugin_id):
    """删除插件市场中的插件（数据库 + 文件）"""
    conn = get_db()
    plugin_name = None
    if conn:
        try:
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            cursor.execute(
                "SELECT plugin_name FROM plugin_marketplace WHERE id=%s", (plugin_id,)
            )
            row = cursor.fetchone()
            if row:
                plugin_name = row["plugin_name"]
                cursor.execute("DELETE FROM plugin_marketplace WHERE id=%s", (plugin_id,))
                conn.commit()
            cursor.close()
            conn.close()
        except Exception:
            pass

    # 删除文件
    if plugin_name:
        plugin_dir = os.path.join(MARKETPLACE_DIR, plugin_name)
        if os.path.isdir(plugin_dir):
            import shutil
            shutil.rmtree(plugin_dir, ignore_errors=True)
        write_log("插件市场删除", f"插件: {plugin_name}, 操作者: {session['username']}")
        return jsonify({"ok": True, "message": f"插件 '{plugin_name}' 已删除"})

    return jsonify({"ok": False, "error": "未找到该插件"}), 404


# ---------- 插件市场沙箱渲染（安全隔离） ----------
@app.route("/plugin-market-raw/<dirname>")
def plugin_market_raw_render(dirname):
    """在沙箱 iframe 中渲染磁盘上的插件（无需 DB 记录）"""
    # 安全检查：防止目录遍历
    safe_dirname = re.sub(r"[^a-zA-Z0-9_\-]", "", dirname)
    if safe_dirname != dirname or ".." in dirname:
        return "<h3>无效的插件名称</h3>", 400

    plugin_dir = os.path.join(MARKETPLACE_DIR, safe_dirname)
    if not os.path.isdir(plugin_dir):
        return "<h3>插件不存在</h3>", 404

    # 读取 manifest 获取显示信息
    display_name = safe_dirname
    manifest_path = os.path.join(plugin_dir, "plugin.json")
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                m = json.load(f)
            display_name = m.get("display_name", safe_dirname)
        except Exception:
            pass

    # 读取 index.html
    entry_path = os.path.join(plugin_dir, "index.html")
    if not os.path.exists(entry_path):
        return "<h3>插件入口文件不存在</h3>", 404

    with open(entry_path, "r", encoding="utf-8") as f:
        plugin_content = f.read()

    return render_template_string(
        SANDBOX_TEMPLATE,
        plugin_title=display_name,
        plugin_content=plugin_content,
        iframe_src=f"/plugin-market-raw/{safe_dirname}/direct",
    )


@app.route("/plugin-market-raw/<dirname>/direct")
def plugin_market_raw_direct(dirname):
    """直接提供沙箱内容（iframe src），返回磁盘上的插件 HTML"""
    safe_dirname = re.sub(r"[^a-zA-Z0-9_\-]", "", dirname)
    if safe_dirname != dirname or ".." in dirname:
        return "<h3>无效的插件名称</h3>", 400

    plugin_dir = os.path.join(MARKETPLACE_DIR, safe_dirname)
    entry_path = os.path.join(plugin_dir, "index.html")
    if not os.path.exists(entry_path):
        return "<h3>插件入口文件不存在</h3>", 404

    resp = make_response(send_file(entry_path))
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.bootcdn.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.bootcdn.net; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' https:; "
        "frame-ancestors 'self'; "
        "sandbox allow-scripts allow-same-origin allow-forms allow-modals allow-popups; "
    )
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    return resp


@app.route("/plugin-market/<int:plugin_id>")
def plugin_market_render(plugin_id):
    """在沙箱 iframe 中渲染插件市场中的插件"""
    conn = get_db()
    if conn:
        try:
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            cursor.execute(
                "SELECT * FROM plugin_marketplace WHERE id=%s", (plugin_id,)
            )
            row = cursor.fetchone()
            cursor.close()
            conn.close()

            if row:
                plugin_dir = os.path.join(MARKETPLACE_DIR, row["plugin_name"])
                if not os.path.isdir(plugin_dir):
                    return "<h3>插件文件丢失</h3>", 404

                # 决定用哪个入口文件
                if row["file_type"] == "vue":
                    entry = "index.html"  # Vue wrapper
                else:
                    entry = "index.html"

                entry_path = os.path.join(plugin_dir, entry)
                if not os.path.exists(entry_path):
                    return "<h3>插件入口文件丢失</h3>", 404

                # 读取插件内容
                with open(entry_path, "r", encoding="utf-8") as f:
                    plugin_content = f.read()

                # 构建沙箱页面：插件在 sandboxed iframe 中运行
                return render_template_string(
                    SANDBOX_TEMPLATE,
                    plugin_title=row["display_name"],
                    plugin_content=plugin_content,
                    iframe_src=f"/plugin-market/{plugin_id}/direct",
                )
        except Exception:
            pass

    return "<h3>插件不存在</h3>", 404


@app.route("/plugin-market/<int:plugin_id>/direct")
def plugin_market_direct(plugin_id):
    """直接提供沙箱内容（iframe src），返回插件 HTML 并附加沙箱 CSP"""
    conn = get_db()
    if conn:
        try:
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            cursor.execute(
                "SELECT * FROM plugin_marketplace WHERE id=%s", (plugin_id,)
            )
            row = cursor.fetchone()
            cursor.close()
            conn.close()

            if row:
                plugin_dir = os.path.join(MARKETPLACE_DIR, row["plugin_name"])
                if row["file_type"] == "vue":
                    entry = "index.html"
                else:
                    entry = "index.html"

                entry_path = os.path.join(plugin_dir, entry)
                if os.path.exists(entry_path):
                    resp = make_response(send_file(entry_path))
                    # 强 CSP：限制插件能力
                    resp.headers["Content-Security-Policy"] = (
                        "default-src 'self'; "
                        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.bootcdn.net; "
                        "style-src 'self' 'unsafe-inline' https://cdn.bootcdn.net; "
                        "img-src 'self' data: blob: https:; "
                        "connect-src 'self' https:; "
                        "frame-ancestors 'self'; "
                        "sandbox allow-scripts allow-same-origin allow-forms allow-modals allow-popups; "
                    )
                    resp.headers["X-Content-Type-Options"] = "nosniff"
                    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
                    return resp
        except Exception:
            pass

    return "<h3>插件不存在</h3>", 404


# 沙箱包装页面模板
SANDBOX_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ plugin_title }} - 插件预览</title>
<style nonce="{{ csp_nonce }}">
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #1a1a2e;
    color: #eee;
    display: flex;
    flex-direction: column;
    height: 100vh;
  }
  .toolbar {
    background: #16213e;
    padding: 10px 20px;
    display: flex;
    align-items: center;
    gap: 12px;
    border-bottom: 1px solid #0f3460;
    flex-shrink: 0;
  }
  .toolbar h2 {
    font-size: 16px;
    margin: 0;
    color: #e94560;
    flex: 1;
  }
  .toolbar .badge {
    background: #0f3460;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 11px;
    color: #a8dadc;
  }
  .toolbar button {
    background: #e94560;
    color: white;
    border: none;
    padding: 6px 16px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
  }
  .toolbar button:hover { background: #c73e54; }
  .sandbox-container {
    flex: 1;
    position: relative;
  }
  .sandbox-container iframe {
    width: 100%;
    height: 100%;
    border: none;
    background: white;
  }
  .sandbox-watermark {
    position: absolute;
    bottom: 8px;
    right: 12px;
    font-size: 10px;
    color: #666;
    pointer-events: none;
    background: rgba(255,255,255,0.85);
    padding: 2px 8px;
    border-radius: 4px;
  }
</style>
</head>
<body>
<div class="toolbar">
  <h2>🧩 {{ plugin_title }}</h2>
  <span class="badge">沙箱隔离模式</span>
  <button onclick="window.location.href='/dashboard'">← 返回工具箱</button>
</div>
<div class="sandbox-container">
  <iframe
    src="{{ iframe_src }}"
    sandbox="allow-scripts allow-same-origin"
    referrerpolicy="no-referrer"
    loading="lazy"
  ></iframe>
  <div class="sandbox-watermark">🔒 沙箱隔离 · 插件代码受限运行</div>
</div>
</body>
</html>'''


# ---------- 公开插件市场浏览（所有用户） ----------
@app.route("/marketplace")
@login_required
def marketplace_browse():
    """用户端插件市场浏览页面"""
    return render_template("marketplace.html",
                           username=session["username"],
                           permission=session["permission"])


@app.route("/api/marketplace")
@login_required
def api_marketplace_public():
    """公开 API：获取插件市场列表（不含管理员专属信息）"""
    result = []
    conn = get_db()
    if conn:
        try:
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            cursor.execute(
                "SELECT id, plugin_name, display_name, description, version, "
                "author, file_type, icon, created_at "
                "FROM plugin_marketplace ORDER BY updated_at DESC"
            )
            rows = cursor.fetchall()
            for r in rows:
                result.append({
                    "id": r["id"],
                    "name": r["plugin_name"],
                    "display_name": r["display_name"],
                    "description": r.get("description", ""),
                    "version": r["version"],
                    "author": r.get("author", ""),
                    "file_type": r["file_type"],
                    "icon": r.get("icon", "🧩"),
                    "created_at": r["created_at"].strftime("%Y-%m-%d %H:%M") if r.get("created_at") else "",
                    "preview_url": f"/plugin-market/{r['id']}",
                })
            cursor.close()
            conn.close()
        except Exception:
            pass

    # 合并磁盘上有 plugin.json 但没有数据库记录的文件（容错）
    if os.path.isdir(MARKETPLACE_DIR):
        for dirname in os.listdir(MARKETPLACE_DIR):
            full = os.path.join(MARKETPLACE_DIR, dirname)
            if os.path.isdir(full):
                manifest_path = os.path.join(full, "plugin.json")
                if os.path.exists(manifest_path):
                    try:
                        with open(manifest_path, "r", encoding="utf-8") as f:
                            m = json.load(f)
                        db_names = {r["name"] for r in result}
                        if dirname not in db_names:
                            result.append({
                                "id": None,
                                "name": dirname,
                                "display_name": m.get("display_name", dirname),
                                "description": m.get("description", ""),
                                "version": m.get("version", "1.0.0"),
                                "author": m.get("author", ""),
                                "file_type": m.get("file_type", "html"),
                                "icon": m.get("icon", "🧩"),
                                "created_at": "",
                                "preview_url": f"/plugin-market-raw/{dirname}",
                            })
                    except Exception:
                        pass

    return jsonify({"ok": True, "plugins": result})


def _init_plugins():
    """启动时自动加载所有插件"""
    discovered = plugins.discover_plugins()
    for p in discovered:
        try:
            plugins.load_plugin(p["name"])
        except Exception:
            pass


# ---------- 启动 ----------
if __name__ == "__main__":
    import atexit
    atexit.register(rate_limiter.shutdown)

    print("=" * 50)
    print("  多合一工具箱 Web 版启动")
    print(f"  本地访问: http://127.0.0.1:4444")
    # 自动检测本机局域网 IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
        print(f"  局域网访问: http://{lan_ip}:4444")
    except Exception:
        print(f"  局域网访问: http://192.168.3.160:5800")
    print(f"  调试模式: {'开启' if os.environ.get('FLASK_DEBUG') else '关闭'}")
    print("=" * 50)
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    _init_plugins()
    # 隐藏 Werkzeug 版本信息（HTTP server 层强制加 Server 头，用 patch 覆盖）
    import werkzeug.serving
    werkzeug.serving.WSGIRequestHandler.version_string = lambda self: "SchoolWeb"
    werkzeug.serving.WSGIRequestHandler.sys_version = ''
    app.run(host="0.0.0.0", port=4444, debug=debug_mode, threaded=True)
