"""多合一校园工具箱 Web 应用

技术栈：Flask (Python) + MySQL (pymysql) + Pillow + Jinja2 + Waitress

主要功能模块：
  - 用户认证（登录/注册/找回密码/密码修改）
  - 仪表盘 & 活跃度排行榜
  - 毕业相册（图片上传/评论/点赞/标签/弹幕）
  - 即时聊天（世界频道/私聊/好友系统）
  - AI 写作助手 & 智能翻译
  - 论坛/公告/投诉建议/匿名树洞
  - 校友录 & 校友故事
  - 学习工具（待办/抽认卡）
  - 生活工具（记账/习惯追踪/番茄钟/签到打卡）
  - 网络工具（Ping/路由追踪/Whois/DNS/端口扫描）
  - 系统监控 & 在线用户管理
  - 数据库可视化查询/编辑
  - 插件系统 & 插件市场
  - 实用小工具（密码生成/哈希/Base64/JSON/二维码等）
  - 信息无障碍：多语言支持 (i18n)
  - 安全响应中心 (SRC)
  - 虚拟宠物系统
  - RSS 阅读器 & 每日一言

安全特性：
  - CSRF 保护
  - 图形验证码
  - IP 速率限制 & 自动封禁
  - 安全响应头（CSP/HSTS/XFO 等）
  - 登录防爆破
  - 会话空闲超时
  - SQL 标识符白名单校验
  - 密码明文→哈希自动升级
"""

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
import atexit
import waitress
import plugins
import bcrypt
import io
import logging
import ssl
import werkzeug.serving
import calendar as cal_mod
import socket as sock
import time as _time
import random as _captcha_random
from importlib.metadata import version as pkg_version
from collections import deque
import subprocess
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, send_from_directory, send_file, abort, Response, g,
    render_template_string, make_response,
)
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from i18n import _, detect_lang, get_supported_langs, SUPPORTED_LANGS
import session_manager


def safe_check_password_hash(pwhash: str, password: str) -> bool:
    """安全地验证密码哈希，兼容 werkzeug (scrypt/pbkdf2) 和 bcrypt 格式。

    数据库中可能存在旧版 bcrypt 哈希（以 $2a$/$2b$/$2y$ 开头），
    werkzeug 3.x 不支持这些格式，直接调用 check_password_hash 会抛出 ValueError。
    """
    if not pwhash:
        return False
    try:
        return check_password_hash(pwhash, password)
    except ValueError:
        # 非 werkzeug 格式，尝试 bcrypt
        if pwhash.startswith("$2"):
            try:
                return bcrypt.checkpw(password.encode(), pwhash.encode())
            except Exception:
                return False
        return False



# ========== 安全工具函数 ==========

# ---------- 简易内存速率限制 ----------
class RateLimiter:
    """简易内存速率限制（文件持久化，重启不丢失）

    基于滑动窗口算法限制单个 key (ip+route) 的请求频率。
    数据持久化到 JSON 文件，重启后自动加载，超过窗口期的旧记录被清理。
    """

    def __init__(self, persist_file=None):
        """
        初始化速率限制器

        Args:
            persist_file: str 或 None，持久化文件路径。为 None 时不保存/加载。
        """
        self._lock = threading.Lock()
        self._buckets = {}  # {(ip, route): [ts, ...]}
        self._persist_file = persist_file
        self._save_timer = None
        # 加载历史数据
        if persist_file:
            self._load()

    def check(self, key, max_requests=10, window=60):
        """
        检查 key 是否超过速率限制。

        滑动窗口算法：保留 window 秒内的请求时间戳，
        如果数量 >= max_requests 则拒绝。

        Args:
            key: tuple，通常是 (ip, route_name)
            max_requests: 窗口内允许的最大请求数
            window: 时间窗口（秒）

        Returns:
            True=允许通过, False=超过限制
        """
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
        """
        去抖保存：延迟 2 秒存盘，多次 rapid 调用合并为一次写入。

        避免高频请求下频繁写文件，通过取消前一个定时器实现合并。
        """
        if not self._persist_file:
            return
        if self._save_timer:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(2.0, self._save)
        self._save_timer.start()

    def _load(self):
        """
        从文件加载持久化状态。

        仅加载 65 秒内的记录（最大窗口 60s + 5s 缓冲），
        避免加载已过期的旧数据。
        """
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
        """
        将内存中的速率状态序列化保存到文件。

        tuple key 以 "|" 拼接为字符串存储，
        重启时 _load() 反向解析。
        安全：至少写入时先获取锁，不阻塞读。
        """
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

    def is_blocked(self, ip, window=240):
        """
        只读检查：IP 是否在封禁期内（不记录任何请求）。

        Args:
            ip: IP 地址字符串
            window: 封禁窗口（秒）

        Returns:
            bool: True 表示在封禁期内
        """
        now = time.time()
        with self._lock:
            hits = self._buckets.get((ip, "blocked"), [])
            if hits:
                latest = max(hits)
                return now - latest < window
            return False

    def get_active_ips(self):
        """
        获取当前活跃跟踪的 IP 及其请求计数（供管理后台显示）。

        Returns:
            dict: {ip: request_count} 最近 1 小时内有活动的 IP。
        """
        now = time.time()
        result = {}
        with self._lock:
            for (ip, route), hits in list(self._buckets.items()):
                if route == "global":
                    fresh = [t for t in hits if now - t < 3600]
                    if fresh:
                        result[ip] = len(fresh)
        return result

    def get_blocked_ips(self):
        """
        获取当前被封禁的 IP 及其封禁剩余时间（供管理后台显示）。

        Returns:
            dict: {ip: remaining_seconds} 当前被封禁的 IP。
        """
        now = time.time()
        result = {}
        with self._lock:
            for (ip, route), hits in list(self._buckets.items()):
                if route == "blocked":
                    # 取最新时间戳，计算剩余封禁时间
                    if hits:
                        latest = max(hits)
                        remaining = latest - now
                        if remaining > 0:
                            result[ip] = int(remaining)
        return result

    def clear_ip(self, ip):
        """
        清除指定 IP 的所有速率限制记录（用于管理员手动解封）。

        Args:
            ip: IP 地址字符串。
        """
        with self._lock:
            for route in ("global", "blocked", "rate"):
                self._buckets.pop((ip, route), None)

    def clear_all(self):
        """清除所有速率限制记录（用于管理员重置）。"""
        with self._lock:
            self._buckets.clear()

    def shutdown(self):
        """
        优雅关闭：取消待执行的定时器并强制保存一次。

        注册为 atexit 回调，确保程序退出时不丢失最新数据。
        """
        if self._save_timer:
            self._save_timer.cancel()
        self._save()


rate_limiter = RateLimiter(persist_file=os.path.join(os.path.dirname(__file__), "rate_limiter.json"))

# ---------- 速率限制配置（环境变量，改值后重启生效，无需改代码） ----------
# 格式: RATE_<操作>_MAX / RATE_<操作>_WINDOW
# 例如: RATE_LOGIN_MAX=10 RATE_LOGIN_WINDOW=120 python app.py
RATE_LIMITS = {
    "captcha":    (int(os.environ.get("RATE_CAPTCHA_MAX", "10")),  int(os.environ.get("RATE_CAPTCHA_WINDOW", "60"))),
    "login_page": (int(os.environ.get("RATE_LOGINPAGE_MAX", "30")), int(os.environ.get("RATE_LOGINPAGE_WINDOW", "60"))),
    "login":      (int(os.environ.get("RATE_LOGIN_MAX", "5")),    int(os.environ.get("RATE_LOGIN_WINDOW", "60"))),
    "register":   (int(os.environ.get("RATE_REGISTER_MAX", "5")),  int(os.environ.get("RATE_REGISTER_WINDOW", "60"))),
}


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

# ---------- ProxyFix：部署在 Nginx 后正确获取客户端真实 IP ----------
# 信任第一个反向代理（Nginx）的 X-Forwarded-* 头
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

CORS(app, supports_credentials=True, origins=['http://localhost:3000', 'http://192.168.3.204:3000'])

# ---------- Session 安全设置 ----------
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=bool(os.environ.get("HTTPS")),  # 生产 HTTPS 环境自动启用 Secure；HTTP 内网环境设为 False
    PERMANENT_SESSION_LIFETIME=timedelta(hours=2)
)

# ---------- 安全工具 User-Agent 过滤 ----------
_BLOCKED_UAS = [
    "sqlmap", "nikto", "nessus", "nmap", "acunetix", "burpsuite",
    "dirbuster", "openvas", "hydra", "amass", "gobuster", "wpscan",
    "zgrab", "masscan", "whatweb", "httprint", "jaeles", "zaproxy",
    "davtest", "wfuzz", "sqlint", "sqlworm", "sqlquery", "sqlmapper",
    "wapiti", "skipfish", "nmap""w3af", "dirb", "nuclei"
]


@app.before_request
def block_security_scanners():
    """
    拦截常见安全扫描工具的 User-Agent。

    URL: 全局（所有请求）
    功能：通过黑名单匹配 UA 字符串，命中时直接返回 403 空响应。
    安全：在解析请求体之前拦截，节省 CPU 和带宽。
    """
    # before_request 执行顺序: 第 1 个
    # 安全：硬编码扫描工具 UA 黑名单，不依赖外部配置
    ua = request.headers.get("User-Agent", "").lower()
    for blocked in _BLOCKED_UAS:
        if blocked in ua:
            return Response("", status=403)


@app.before_request
def set_csp_nonce():
    """
    为每个 HTTP 请求生成唯一的 CSP nonce 值。

    URL: 全局
    功能：在 g 对象上设置 csp_nonce，用于 HTML 模板中的 <script nonce="...">
    安全：每个请求的 nonce 不同，防止 inline script 注入被复用。
    """
    # before_request 执行顺序: 第 2 个
    g.csp_nonce = os.urandom(16).hex()


# ========== 多语言支持 ==========
# ---------- 多语言支持 ----------
@app.before_request
def set_language():
    """
    检测并设置当前会话的语言偏好。

    URL: 全局
    功能：通过请求头 / Cookie / 用户设置检测语言，写入 session。
    如果用户已登录，将语言偏好持久化到数据库 user_profiles.lang。
    """
    # before_request 执行顺序: 第 3 个
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
    """将翻译函数、语言信息、缓存破坏器注入所有模板"""
    lang = session.get("lang", "zh-CN")
    perm = session.get("permission", "guest")

    return {
        "_": lambda key, default=None, **kw: _(key, lang, default, **kw),
        "lang": lang,
        "supported_langs": get_supported_langs(),
        "lang_name": lambda l: _(f"_name", l) if l in SUPPORTED_LANGS else l,
        "plugin_menu_items": plugins.get_menu_items(perm),
        "plugin_footer_blocks": plugins.get_template_blocks("footer"),
        "cache_buster": str(int(_time.time() * 1000)),  # captcha/bg 全站缓存破坏
        "plugin_head_blocks": plugins.get_template_blocks("head"),
    }




def _save_user_lang(username, lang):
    """
    持久化用户语言偏好到数据库 user_profiles.lang 字段。

    异常时不抛出，仅静默失败（不阻塞请求）。
    在 set_language before_request 中被调用。
    """
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
    """
    切换语言 API（URL: /api/lang/switch, POST）。

    权限：任意用户（未登录也可切换）
    功能：校验语言参数是否在 SUPPORTED_LANGS 中，更新 session，设置 lang Cookie。
    """
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
_forum_tables_done = False
_confession_tables_done = False
_alumni_stories_tables_done = False
def _init_db_once():
    """
    一站式初始化所有核心数据库表。

    包含：密码重置表、插件市场表、安全报告表、公告表、
    投诉表、生活工具表、论坛表、会话追踪表。
    使用 _db_init_done 全局锁确保只执行一次。
    """
    global _db_init_done
    if not _db_init_done:
        _init_reset_table()
        _init_marketplace_table()
        _init_src_table()
        _init_announcement_table()
        _init_complaints_table()
        _init_life_tables()
        _init_forum_tables()
        _init_session_tables()
        _init_db_done = True


def _init_reset_table():
    """
    初始化密码重置/用户资料/活跃度/管理员申请/日历事件表。

    CREATE TABLE IF NOT EXISTS 保证幂等；
    ALTER TABLE 添加校友录字段（兼容旧表）。
    """
    conn = get_db()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        # 用户主表（核心表，新部署必须创建）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                User_Name VARCHAR(50) NOT NULL UNIQUE,
                User_Password VARCHAR(255) NOT NULL,
                Access_Permission VARCHAR(20) DEFAULT 'guest',
                security_question VARCHAR(200) DEFAULT NULL,
                security_answer VARCHAR(200) DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 兼容旧表：添加可能缺失的列
        for col, col_def in [
            ("security_question", "VARCHAR(200) DEFAULT NULL"),
            ("security_answer", "VARCHAR(200) DEFAULT NULL"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_def}")
            except Exception:
                pass
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
        # 确保校友录字段存在
        for col, col_def in [
            ("graduation_year", "INT DEFAULT NULL"),
            ("class_name", "VARCHAR(50) DEFAULT ''"),
            ("major", "VARCHAR(100) DEFAULT ''"),
            ("city", "VARCHAR(50) DEFAULT ''"),
            ("occupation", "VARCHAR(100) DEFAULT ''"),
            ("wechat", "VARCHAR(50) DEFAULT ''"),
            ("public_profile", "TINYINT DEFAULT 1"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE user_profiles ADD COLUMN {col} {col_def}")
                conn.commit()
            except Exception:
                pass
        # 论坛公告标记
        try:
            cursor.execute("ALTER TABLE forum_posts ADD COLUMN is_announcement TINYINT DEFAULT 0")
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
        # 用户备忘录（多用户隔离，每个用户一条记录）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_notes (
                username VARCHAR(50) PRIMARY KEY,
                content LONGTEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
    except pymysql.MySQLError:
        pass


def _init_marketplace_table():
    """
    创建 plugin_marketplace 表 — 管理员上传的 HTML/Vue 插件元信息。

    存储：插件名、显示名、描述、版本、作者、文件类型、上传者等。
    """
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


def _init_src_table():
    """
    创建 src_reports 表 — SRC 漏洞报告。

    存储漏洞标题、类型、严重级别、影响 URL、复现步骤、状态等。
    """
    conn = get_db()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS src_reports (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                title VARCHAR(500) NOT NULL,
                vuln_type VARCHAR(50) NOT NULL,
                severity VARCHAR(20) NOT NULL DEFAULT 'medium',
                affected_url VARCHAR(500),
                description TEXT NOT NULL,
                steps_to_reproduce TEXT,
                impact TEXT,
            attachment VARCHAR(500),
            wechat_contact VARCHAR(100) DEFAULT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            admin_notes TEXT,
            reviewed_by VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_src_user (username),
            INDEX idx_src_status (status)
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
    except pymysql.MySQLError:
        pass


def _init_announcement_table():
    """
    创建 dashboard_announcements 表 — 仪表盘顶部公告栏。

    支持软删除（is_active 字段）。
    """
    conn = get_db()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_announcements (
                id INT AUTO_INCREMENT PRIMARY KEY,
                content TEXT NOT NULL,
                created_by VARCHAR(50) NOT NULL,
                is_active TINYINT DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
    except pymysql.MySQLError:
        pass


def _init_complaints_table():
    """
    创建 complaints 表 — 用户投诉与建议。

    包含：标题、内容、已读标记、管理员回复、状态字段。
    """
    conn = get_db()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS complaints (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                title VARCHAR(200) NOT NULL,
                content TEXT NOT NULL,
                is_read TINYINT DEFAULT 0,
                reply TEXT,
                status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    "RATE_LIMIT":         int(os.environ.get("RATE_GLOBAL_LIMIT", "40")),
    "RATE_WINDOW":        int(os.environ.get("RATE_GLOBAL_WINDOW", "10")),
    "BLOCK_DURATION":     int(os.environ.get("RATE_BLOCK_DURATION", "240")),
    "BLOCK_PROBE_LIMIT":  int(os.environ.get("RATE_BLOCK_PROBE", "50")),
    "BLOCK_EXTEND":       int(os.environ.get("RATE_BLOCK_EXTEND", "240")),
}

def _load_rate_config():
    """
    从 rate_config.json 文件加载速率配置。

    以 DEFAULT_RATE_CONFIG 为基准，覆盖已保存的值。
    读取失败时回退到默认值。
    """
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
    """
    保存速率配置到 rate_config.json 文件。

    管理员通过 API 动态修改配置后调用此函数持久化。
    """
    try:
        with open(RATE_CONFIG_FILE, "w") as f:
            json.dump(rate_config, f)
    except Exception:
        pass

rate_config = _load_rate_config()
ip_whitelist = set()    # 白名单 IP，不受速率限制
ip_manual_blocked = {}  # {ip: blocked_until_timestamp} 手动封禁
recent_blocks = []  # [(ip, timestamp, reason)] — 最近封禁记录，供通知功能使用
recent_blocks_lock = threading.Lock()

# ---------- IP 白名单持久化 ----------
WHITELIST_FILE = os.path.join(os.path.dirname(__file__), "ip_whitelist.json")

def _load_whitelist():
    """
    从 ip_whitelist.json 文件加载 IP 白名单。

    Returns:
        set(str) IP 地址集合
    """
    if os.path.exists(WHITELIST_FILE):
        try:
            with open(WHITELIST_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()

def _save_whitelist():
    """
    将 IP 白名单保存到 ip_whitelist.json 文件。

    管理员通过管理页修改白名单后调用此函数持久化。
    """
    try:
        with open(WHITELIST_FILE, "w") as f:
            json.dump(sorted(ip_whitelist), f)
    except Exception:
        pass

ip_whitelist = _load_whitelist()

def _verify_captcha(user_input):
    """
    验证图形验证码。统一入口，返回 (success: bool, error_msg: str)。
    
    图片显示大写字母（23456789ABCDEFGHJKLMNPQRSTUVWXYZ），
    session 存储小写码，比较时忽略大小写。
    有效期 5 分钟，防止重放。
    """
    if not user_input or not user_input.strip():
        return False, "验证码不能为空"
    
    stored = session.get("captcha_code", "")
    
    if not stored:
        return False, "验证码已失效，请刷新"
    
    # 5 分钟过期
    captcha_time = session.get("captcha_time", 0)
    if time.time() - captcha_time > 300:
        session.pop("captcha_code", None)
        session.pop("captcha_time", None)
        return False, "验证码已过期，请刷新"
    
    # 不区分大小写比较（图片显示大写，session 存小写）
    if user_input.strip().lower() != stored:
        session.pop("captcha_code", None)
        session.pop("captcha_time", None)
        return False, "验证码错误"
    
    # 验证通过，消费验证码（防止重放攻击）
    session.pop("captcha_code", None)
    session.pop("captcha_time", None)
    return True, "验证通过"


def _generate_captcha():
    """
    预生成验证码存入 session，供表单使用。

    已有未过期（5分钟内）的验证码则复用，防止重复生成导致 session 膨胀。
    生成的验证码是小写字母数字串（从 _captcha_chars 随机取 4 个字符）。
    供 api_captcha 生成图片时和表单渲染时调用，确保图片与 session code 一致。

    Returns:
        str: 小写验证码字符串
    """
    stored = session.get("captcha_code")
    captcha_time = session.get("captcha_time", 0)
    if stored and (time.time() - captcha_time < 300):
        return stored  # 复用已有未过期码
    code = ''.join(_captcha_random.choice(_captcha_chars) for _ in range(4)).lower()
    session["captcha_code"] = code
    session["captcha_time"] = time.time()
    return code


# ---------- 图形验证码 ----------
# 验证码字符集（模块级，供 _generate_captcha 和 api_captcha 共用）

_captcha_chars = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
@app.route("/api/captcha")
def api_captcha():
    """
    生成图形验证码图片（URL: /api/captcha, GET）。

    权限：任意用户
    功能：生成 200x70 的 PNG 验证码图片，包含 4 个字符的干扰线/噪点/旋转。
          安全：使用 no-store 缓存头防止缓存；验证码一次性使用防重放。
          速率限制：captcha 速率（默认 10 次/60 秒）。
    """
    """生成图形验证码。优先复用 session 中未过期的 code，保证图片与 session 一致。"""
    # 验证码接口速率限制
    client_ip = request.remote_addr or "unknown"
    _limit, _window = RATE_LIMITS["captcha"]
    if not rate_limiter.check((client_ip, "captcha"), max_requests=_limit, window=_window):
        return jsonify({"error": "请求过于频繁"}), 429


    code = _generate_captcha()  # 统一使用预生成函数，与表单 code 一致

    # 创建验证码图片（加大尺寸，字体更大更清晰）
    width, height = 200, 70
    img = Image.new("RGB", (width, height), (248, 248, 248))
    draw = ImageDraw.Draw(img)

    # 轻量背景噪点
    for x in range(width):
        for y in range(height):
            if _random.random() < 0.12:
                draw.point((x, y), fill=(_random.randint(220, 255), _random.randint(220, 255), _random.randint(220, 255)))

    # 1 条曲线干扰
    points = [(_random.randint(0, width), _random.randint(0, height)) for _ in range(4)]
    for j in range(len(points) - 1):
        draw.line([points[j], points[j+1]], fill=(_random.randint(180, 230), _random.randint(180, 230), _random.randint(180, 230)), width=2)

    # 3 条短直线
    for _ in range(3):
        x1, y1 = _random.randint(10, width - 10), _random.randint(5, height - 5)
        x2, y2 = x1 + _random.randint(-40, 40), y1 + _random.randint(-20, 20)
        draw.line([(x1, y1), (x2, y2)], fill=(_random.randint(180, 230), _random.randint(180, 230), _random.randint(180, 230)), width=1)

    # 少量随机点
    for _ in range(80):
        x, y = _random.randint(0, width), _random.randint(0, height)
        draw.point((x, y), fill=(_random.randint(100, 200), _random.randint(100, 200), _random.randint(100, 200)))

    # 绘制文字 — 多个字体 fallback，字号加大到 44
    font = None
    font_size = 44
    font_paths = [
        "/System/Library/Fonts/Helvetica.ttc",           # macOS
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux/Docker
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",  # Docker 中文字体
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ]
    for fp in font_paths:
        try:
            font = ImageFont.truetype(fp, font_size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    for i, ch in enumerate(code):
        # 每个字符单独创建并旋转
        char_img = Image.new("RGBA", (52, 60), (0, 0, 0, 0))
        char_draw = ImageDraw.Draw(char_img)
        color = (_random.randint(0, 50), _random.randint(0, 70), _random.randint(140, 240))
        char_draw.text((6, 0), ch, font=font, fill=color)
        # 轻度旋转
        angle = _random.randint(-18, 18)
        char_img = char_img.rotate(angle, expand=True, fillcolor=(0, 0, 0, 0))
        x = 14 + i * 42 + _random.randint(-4, 4)
        y = _random.randint(5, 14)
        img.paste(char_img, (x, y), char_img)

    # 轻微模糊
    img = img.filter(ImageFilter.GaussianBlur(radius=0.4))

    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)

    resp = make_response(send_file(buf, mimetype="image/png"))
    resp.headers["Cache-Control"] = "no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

# ---------- 登录防爆破（使用文件持久化 rate_limiter，多 worker 共享状态） ----------

# ---------- 多用户在线会话超时 ----------
SESSION_IDLE_TIMEOUT = 1800  # 秒（30 分钟空闲超时）

@app.before_request
def check_rate_limit():
    """
    全局 IP 速率限制与封禁（before_request 执行顺序: 第 4 个）。

    URL: 全局（跳过 /static/ /assets/ /favicon.ico /share/）
    功能：使用文件持久化 RateLimiter（多 worker 共享状态），
          滑动窗口统计每个 IP 的请求数，超过 RATE_LIMIT 则封禁 BLOCK_DURATION 秒。
          支持白名单（ip_whitelist）和手动封禁（ip_manual_blocked）。
    """
    # 静态文件和分享链接跳过速率限制
    path = request.path
    if any(path.startswith(p) for p in ("/static/", "/assets/", "/favicon.ico", "/share/")):
        return None
    ip = request.remote_addr or "0.0.0.0"
    now = time.time()

    # 白名单：跳过检查
    if ip in ip_whitelist:
        return None

    # 手动封禁检查
    if ip in ip_manual_blocked and now < ip_manual_blocked[ip]:
        remaining = int(ip_manual_blocked[ip] - now)
        return jsonify({"error": f"IP已被管理员手动封禁，剩余 {remaining} 秒"}), 403

    # 检查是否在封禁期内（只读，不记录）
    if rate_limiter.is_blocked(ip, window=rate_config["BLOCK_DURATION"]):
        return jsonify({"error": f"请求过于频繁，IP已被封禁，剩余约 {rate_config['BLOCK_DURATION']} 秒"}), 403

    # 检查短时速率限制（记录请求时间戳）
    if not rate_limiter.check((ip, "global"), max_requests=rate_config["RATE_LIMIT"], window=rate_config["RATE_WINDOW"]):
        # 超限：触发封禁并返回错误
        rate_limiter.check((ip, "blocked"), max_requests=1, window=rate_config["BLOCK_DURATION"])
        with recent_blocks_lock:
            recent_blocks.append((ip, now, "请求超限"))
            if len(recent_blocks) > 100:
                recent_blocks.pop(0)
        return jsonify({"error": f"请求过于频繁，IP已被封禁 {rate_config['BLOCK_DURATION']} 秒"}), 403


@app.before_request
def check_session_idle_timeout():
    """
    基于会话的时间戳检查空闲超时（before_request 执行顺序: 第 5 个）。

    URL: 跳过 /static/ /assets/ /favicon.ico /share/ /plugin-market/ 及首页/注册/登出
    功能：记录每个请求的 _last_request_time 到 session，
          若超过 SESSION_IDLE_TIMEOUT（30 分钟）未操作，自动登出并调用 session_manager.logout_session。
          多用户同 IP 互不干扰（基于 session 而非 IP）。
    """
    skip_prefixes = ("/static/", "/assets/", "/favicon.ico", "/share/", "/plugin-market/")
    path = request.path
    if any(path.startswith(p) for p in skip_prefixes):
        return None
    if path in ("/", "/register", "/logout"):
        return None

    if "username" not in session:
        return None

    now = time.time()
    last_request = session.get("_last_request_time", 0)

    if last_request and (now - last_request) > SESSION_IDLE_TIMEOUT:
        # 超时，标记数据库会话为非活跃并清除
        idle_minutes = int((now - last_request) / 60)
        session_manager.logout_session(
            session_key=session.get("session_key", ""),
            username=session.get("username", ""),
            ip=request.remote_addr or "0.0.0.0",
            reason="timeout"
        )
        session.clear()
        flash(f"由于 {idle_minutes} 分钟未操作，已自动退出登录", "warning")
        return redirect(url_for("login"))

    session["_last_request_time"] = now
    return None


# ---------- 多用户同时在线：会话追踪 before_request ----------

@app.before_request
def assign_session_key():
    """
    为每个浏览器会话分配唯一的 session_key（before_request 执行顺序: 第 6 个）。

    URL: 全局
    功能：如果 session 尚无 session_key，生成一个 uuid4 hex 并存入。
          用于多设备会话追踪、踢出指定设备、心跳检测等。
          每个浏览器标签页 / 设备获得独立的 session_key（前提是独立 session）。
    """
    if "session_key" not in session:
        session["session_key"] = uuid.uuid4().hex


@app.before_request
def track_session_activity():
    """
    每次请求更新数据库中的会话活跃时间（before_request 执行顺序: 第 7 个）。

    URL: 跳过 /static/ /assets/ /api/heartbeat
    功能：将 session_key + username + ip 写入 active_sessions 表的 last_activity。
          供管理员查看在线用户、idle 时间、以及会话管理使用。
    """
    if "username" not in session:
        return None
    path = request.path
    if path.startswith("/static/") or path.startswith("/assets/") or path == "/api/heartbeat":
        return None
    
    session_key = session.get("session_key")
    username = session.get("username")
    ip = request.remote_addr or "0.0.0.0"
    
    if session_key and username:
        session_manager.update_activity(session_key, username, ip)


@app.before_request
def check_kicked():
    """
    检查当前会话是否被管理员踢出（before_request 执行顺序: 第 8 个）。

    URL: 跳过 /static/ /assets/ 和首页/登录/注册/登出
    功能：调用 session_manager.is_session_valid 检查 session_key 是否有效。
          被踢出的 session 自动清空并重定向到登录页。
          安全：无效的 session 无法访问任何受限页面。
    """
    if "username" not in session:
        return None
    path = request.path
    if path in ("/", "/login", "/register", "/logout"):
        return None
    if path.startswith("/static/") or path.startswith("/assets/"):
        return None
    
    session_key = session.get("session_key")
    if session_key and not session_manager.is_session_valid(session_key):
        session.clear()
        flash("您的会话已被管理员终止", "warning")
        return redirect(url_for("login"))


# ---------- 全站验证码门禁 ----------
CAPTCHA_SKIP = {"/", "/register", "/logout", "/forgot_password", "/reset_password", "/calculator", "/calculator/sci", "/calculator/net", "/notes", "/change_password", "/profile", "/author", "/chat", "/api/captcha", "/api/heartbeat", "/api/online_users", "/dashboard", "/admin", "/admin/sessions", "/admin/reset_requests", "/donate", "/calendar", "/network_tools", "/system_monitor", "/db_query", "/db_update", "/marketplace", "/api/marketplace", "/utils", "/api/utils", "/src", "/src/my", "/src/admin", "/src/rules", "/weather", "/expenses", "/habits", "/pomodoro", "/bookmarks", "/converter", "/rss", "/daily_quote", "/games", "/qrcode", "/image_compress", "/api_tester", "/markdown", "/unit_converter", "/text_diff", "/jwt_decoder", "/countdown", "/sql_formatter", "/mock_data", "/random_tools", "/git_cheatsheet", "/password_analyzer", "/file_converter"}
CAPTCHA_SKIP_PREFIX = ("/static/", "/assets/", "/favicon.ico", "/share/", "/api/table/", "/api/album/", "/api/chat/", "/api/leaderboard", "/api/admin/", "/api/admin-", "/api/notifications", "/api/profile/", "/api/avatar", "/api/system", "/api/vip", "/api/lang/", "/api/calendar/", "/api/network/", "/plugin-market/", "/api/utils/", "/api/src/", "/api/weather", "/api/expenses", "/api/habits", "/api/habit_logs", "/api/bookmarks", "/api/converter", "/api/rss/", "/api/daily_quote", "/api/qrcode", "/api/image_compress", "/api/api_tester/", "/api/announcements", "/api/complaint/", "/api/forum/", "/api/backup/", "/api/checkin", "/api/pet/", "/api/study/", "/api/pomodoro/", "/api/portal/", "/api/translator", "/api/pdf/", "/api/confession/", "/api/alumni/", "/api/auth/", "/api/my/")

@app.before_request
def check_global_captcha():
    """
    全站验证码门禁 — 部分敏感页面需要验证码后才能访问（before_request 执行顺序: 第 9 个）。

    URL: 跳过 CAPTCHA_SKIP 列表和 CAPTCHA_SKIP_PREFIX 前缀
    功能：登录后首次访问某些页面需要输入验证码（防机器人爬虫）。
          验证通过后设置 global_captcha_verified 到 session，同会话后续免验证。
          POST 请求自动验证 form 中的 captcha 字段。
          API 请求返回 403 JSON。
    """
    # 安全：启用二次验证的页面列表明确在白名单中，未列出的敏感页面全局拦截
    if "username" not in session:
        return None
    path = request.path
    if path in CAPTCHA_SKIP or any(path.startswith(p) for p in CAPTCHA_SKIP_PREFIX):
        return None
    if session.get("global_captcha_verified"):
        return None
    if request.method == "POST" and request.form.get("captcha"):
        # 确保验证码存在再验证（防止多标签页竞争消耗导致空码）
        if not session.get("captcha_code"):
            _generate_captcha()
        ok, err_msg = _verify_captcha(request.form.get("captcha", ""))
        if ok:
            session["global_captcha_verified"] = True
            return redirect(request.path)
        flash(err_msg, "danger")
    if path.startswith("/api/"):
        return jsonify({"error": "需要安全验证"}), 403
    # 先预生成验证码再渲染表单，确保 session 中已有 captcha_code
    # 即使浏览器未能加载验证码图片，code 也存在
    _generate_captcha()
    return render_template("global_captcha.html",
                           username=session["username"],
                           permission=session["permission"],
                           csrf_token=session.get("csrf_token", ""))


# ---------- 配置 ----------
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASSWORD", "root@123456"),
    "database": os.environ.get("DB_NAME", "sample"),
    "init_command": "SET time_zone='+00:00'",
}
ALBUM_DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASSWORD", "root@123456"),
    "database": os.environ.get("DB_NAME", "sample"),
    "init_command": "SET time_zone='+00:00'",
}
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "asdfghjkl;'")
LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "app.log")


# ---------- 安全响应头 ----------
@app.after_request
def add_security_headers(response):
    """
    为每个 HTTP 响应添加安全响应头。

    功能：
      - X-Content-Type-Options: nosniff（防 MIME 类型混淆）
      - X-Frame-Options: SAMEORIGIN（防点击劫持）
      - Referrer-Policy: strict-origin-when-cross-origin（限制 referer 泄露）
      - Content-Security-Policy: 使用 nonce 限制脚本资源，限制 form-action、
        frame-ancestors、connect-src 等（防 XSS + 数据外泄）
      - Permissions-Policy: 禁用摄像头/麦克风/位置（防隐私 API 滥用）
      - HSTS: 仅生产环境启用（max-age=1年，含子域名）
      - HTML/JSON 响应强制 no-cache（防敏感数据缓存）
      - 隐藏 Server 头（防信息泄露）
    """
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
            f"script-src 'self' 'unsafe-inline' 'unsafe-eval'{nonce_directive} https://cdn.bootcdn.net https://unpkg.com https://cdn.jsdelivr.net; "
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
    # 敏感页面和 API 禁用缓存
    ct = response.content_type or ""
    if "text/html" in ct or "application/json" in ct:
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
    """
    获取主数据库连接。

    使用 DB_CONFIG 配置连接 MySQL，连接失败时返回 None 而非抛出异常。
    调用方需检查返回值是否为 None。

    Returns:
        pymysql.Connection 或 None
    """
    try:
        return pymysql.connect(**DB_CONFIG)
    except pymysql.MySQLError as e:
        return None

def get_album_db():
    """
    获取相册数据库连接（与主库配置相同），并确保相册扩展表已初始化。

    每次获取连接时调用 _init_album_tables 确保新表存在，
    兼容不同版本代码之间的 schema 差异。

    Returns:
        pymysql.Connection 或 None
    """
    try:
        conn = pymysql.connect(**ALBUM_DB_CONFIG)
        _init_album_tables(conn)
        return conn
    except pymysql.MySQLError as e:
        return None

# ---------- 初始化相册扩展表 ----------
def _init_album_tables(conn):
    """
    初始化相册扩展功能所需的数据库表。

    包含：大事记(album_events)、同学录(album_classmates)、毕业寄语(album_wishes)、
    照片标签(album_tags/image_tags)、毕业歌单(album_playlist)、弹幕(album_danmaku)、
    分享链接(album_share_links)、聊天(chat_messages)、好友(friendships)、
    AI 对话(ai_conversations/config)、学习工具(study_todos/flashcards)。
    兼容旧表：对 album_classmates 尝试添加 class_name 和 graduation_year 列。
    """
    cursor = conn.cursor()
    # 相册图片主表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS album_images (
            id INT AUTO_INCREMENT PRIMARY KEY,
            category VARCHAR(50) DEFAULT NULL,
            name VARCHAR(100) DEFAULT NULL,
            filename VARCHAR(255) NOT NULL COMMENT '存储的文件名',
            uploader VARCHAR(50) NOT NULL,
            uploader_name VARCHAR(50) DEFAULT '',
            upload_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            status VARCHAR(20) DEFAULT 'approved'
        )
    """)
    # 相册点赞表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS album_likes (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            image_id INT NOT NULL,
            user VARCHAR(50) NOT NULL,
            time DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uk_img_user (image_id, user)
        )
    """)
    # 相册图片评论表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS album_image_comments (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            image_id INT NOT NULL,
            reply_to INT DEFAULT NULL,
            reply_user VARCHAR(50) DEFAULT NULL,
            author VARCHAR(50) NOT NULL,
            author_name VARCHAR(50) DEFAULT '',
            text TEXT NOT NULL,
            time DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 相册通用评论表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS album_general_comments (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            author VARCHAR(50) NOT NULL,
            author_name VARCHAR(50) DEFAULT '',
            text TEXT NOT NULL,
            time DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 兼容旧表：添加可能缺失的列
    for tbl, col, col_def in [
        ("album_images", "status", "VARCHAR(20) DEFAULT 'approved'"),
        ("album_images", "uploader_name", "VARCHAR(50) DEFAULT ''"),
        ("album_likes", "time", "DATETIME DEFAULT CURRENT_TIMESTAMP"),
        ("album_image_comments", "reply_to", "INT DEFAULT NULL"),
        ("album_image_comments", "reply_user", "VARCHAR(50) DEFAULT NULL"),
        ("album_image_comments", "author_name", "VARCHAR(50) DEFAULT ''"),
        ("album_general_comments", "author_name", "VARCHAR(50) DEFAULT ''"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {col_def}")
        except Exception:
            pass
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
    # 分享链接（username 用于多用户隔离，追踪分享创建者）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS album_share_links (
            id INT AUTO_INCREMENT PRIMARY KEY,
            image_id INT NOT NULL,
            token VARCHAR(64) NOT NULL UNIQUE,
            username VARCHAR(50) DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 兼容旧表：添加 username 列
    try:
        cursor.execute("ALTER TABLE album_share_links ADD COLUMN username VARCHAR(50) DEFAULT NULL")
    except Exception:
        pass
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
    # AI 对话记录
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ai_conversations (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(50) NOT NULL,
            role VARCHAR(10) NOT NULL COMMENT 'user or assistant',
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_user (username, created_at)
        )
    """)
    # AI 配置
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ai_config (
            username VARCHAR(50) PRIMARY KEY,
            provider_url VARCHAR(500) NOT NULL,
            api_key_encrypted VARCHAR(500) NOT NULL,
            model_name VARCHAR(100) DEFAULT 'gpt-3.5-turbo',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
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
    """
    清洗用户输入：去除 HTML/JS 标签，限制长度，过滤 SQL 危险字符。

    安全：
      1. 移除 <script>...</script> 标签（正则不区分大小写 + DOTALL）
      2. 移除所有剩余 HTML 标签（纵深防御）
      3. 移除 null byte（防止 SQL 截断攻击）
      4. 截断至 max_length 防止长文本攻击

    Args:
        text: 用户输入的原始字符串
        max_length: 截断最大长度（默认 1000）

    Returns:
        清洗后的安全字符串
    """
    if not text:
        return ""
    text = str(text).strip()
    text = _SCRIPT_TAG.sub("", text)
    text = _HTML_TAG.sub("", text)
    # 移除 SQL 注释和控制字符（纵深防御，即使查询已参数化）
    text = text.replace('\x00', '')  # null byte
    text = text[:max_length]
    return text

def _mask_cell(col_name, value):
    """
    对数据库查询结果的单个单元格做脱敏处理。

    安全：对于密码/敏感信息列，掩码显示；非敏感列返回原始值。

    Args:
        col_name: 列名，用于判断是否敏感列
        value: 原始值

    Returns:
        脱敏后的字符串
    """
    return str(value) if value is not None else ""


def _safe_identifier(name):
    """
    安全地清理 SQL 标识符（表名/列名），白名单校验后安全拼接。

    安全：严格正则校验只允许 [a-zA-Z_][a-zA-Z0-9_]* 模式，
    拒绝所有非法字符，从源头杜绝 SQL 注入。
    在构造动态 table/column 查询时，务必通过此函数校验后再 f-string/拼接。

    Args:
        name: 原始标识符字符串

    Returns:
        安全清理后的标识符，或 None（不合法时）
    """
    if not name or not isinstance(name, str):
        return None
    name = name.replace('`', '').strip()
    # 只允许字母、数字、下划线，且必须以字母或下划线开头
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
        return None
    return name


def _get_valid_columns(conn, table_name):
    """
    获取表的合法列名集合（内部先做标识符安全校验）。

    安全：先用 _safe_identifier 校验表名，再执行 SHOW COLUMNS，
    配合 f-string + 反引号包裹 + 白名单校验，确保列名安全。
    用于 api_table_insert/update/delete 等动态列名场景。

    Args:
        conn: 数据库连接
        table_name: 表名

    Returns:
        set(str) 合法列名集合，非法输入或异常返回空集
    """
    table_name = _safe_identifier(table_name)
    if not table_name:
        return set()
    try:
        cursor = conn.cursor()
        # 表名已通过 _safe_identifier 正则校验，安全拼接
        cursor.execute(f"SHOW COLUMNS FROM `{table_name}`")
        cols = {r[0] for r in cursor.fetchall()}
        cursor.close()
        return cols
    except Exception:
        return set()

def write_log(action, detail=""):
    """
    写入操作日志到文件。

    Args:
        action: 操作名称（如 "用户登录"、"删除图片"）
        detail: 操作详情（如 "用户名: admin"）
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
    """
    登录状态校验装饰器。

    URL: 任意需要登录的路由
    功能：检查 session 中是否有 "username" 键。
          API 请求（/api/ 开头）返回 401 JSON，
          页面请求重定向到登录页。
    """
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
    """
    验证 CSRF token 的装饰器。

    安全：
      1. GET/HEAD/OPTIONS/TRACE 安全方法直接放行
      2. 从 form body 或 X-CSRF-Token 头获取 token
      3. 使用 hmac.compare_digest 做常量时间比较（防时序攻击）
      4. token 不匹配时重定向到登录页

    用法：
        @app.route("/submit", methods=["POST"])
        @csrf_required
        def submit():
            ...
    """
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
    """
    管理员权限校验装饰器。

    功能：检查 session 中的 permission 是否为 "administrator"，
    非管理员提示权限不足并重定向到仪表盘。
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("permission") != "administrator":
            flash("权限不足，需要管理员权限", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated

def non_guest_required(f):
    """
    非访客权限校验装饰器（VIP 或管理员可访问）。

    功能：检查 session 中的 permission 是否为 "guest"，
    访客提示申请 VIP 并重定向到仪表盘。
    用于数据库查询等敏感功能。
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        perm = session.get("permission", "guest")
        if perm == "guest":
            flash("访客无法使用此功能，请申请 VIP 权限", "warning")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated

def vip_required(f):
    """
    VIP 或管理员权限校验装饰器。

    功能：检查 session 中的 permission 是否为 "administrator" 或 "vip"，
    API 请求返回 403 JSON，页面请求重定向到仪表盘。
    用于网络工具等 VIP 功能。
    """
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
    """
    数据库二次验证（验证码）装饰器。

    安全：执行数据库写操作前要求验证码二次确认，
    防止 CSRF + XSS 驱动的自动化数据库请求。
    验证通过后将 db_captcha_verified 写入 session，
    同一 session 后续操作不需要重复验证。
    API 请求返回 403 JSON。
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("db_captcha_verified"):
            return f(*args, **kwargs)
        if request.method == "POST" and request.form.get("db_captcha"):
            ok, err_msg = _verify_captcha(request.form.get("db_captcha", ""))
            if ok:
                session["db_captcha_verified"] = True
                return redirect(request.path)
            flash(err_msg, "danger")
        # API 请求返回 JSON 错误
        if request.path.startswith("/api/"):
            return jsonify({"error": "需要数据库操作验证"}), 403
        return render_template("db_captcha.html",
                               username=session["username"],
                               permission=session["permission"],
                               csrf_token=session.get("csrf_token", ""))
    return decorated


# ---------- 路由：登录 ----------
@app.route("/", methods=["GET", "POST"])
def login():
    """
    登录页面（URL: /）—— 也是首页。

    权限：未登录可访问（GET 获取表单，POST 提交登录）
    GET 逻辑：
      - 首次访问时初始化数据库表
      - 生成 CSRF token
      - 未登录时受 login_page 速率限制（默认 30 次/60 秒）
    POST 逻辑：
      - 受 login 速率限制（默认 5 次/60 秒）
      - 验证码校验（5 分钟内过期，一次性使用防重放）
      - 登录防爆破（5 次错误锁定 5 分钟）
      - 密码验证兼容 werkzeug hash 和旧版 bcrypt
      - 旧版明文密码自动升级为 werkzeug hash
      - 多设备在线管理：检查是否允许多设备登录，不允许时踢出旧会话
      - 注册数据库会话（session_manager.register_session）
    """
    _init_db_once()
    # 生成 CSRF token
    if "csrf_token" not in session:
        session["csrf_token"] = os.urandom(32).hex()

    # GET 请求频率限制（未登录用户）
    if request.method == "GET" and "username" not in session:
        client_ip = request.remote_addr or "unknown"
        _limit, _window = RATE_LIMITS["login_page"]
        if not rate_limiter.check((client_ip, "login_page"), max_requests=_limit, window=_window):
            return Response("请求过于频繁", status=429)

    # GET 请求：已登录用户访问登录页，提示可切换账户
    if request.method == "GET" and "username" in session:
        current_user = session["username"]
        flash(f"您已登录为「{sanitize_input(current_user)}」。如需切换到其他账户，请先退出当前账户再登录。", "info")

    if request.method == "POST":
        # 登录速率限制
        client_ip = request.remote_addr or "unknown"
        _limit, _window = RATE_LIMITS["login"]
        if not rate_limiter.check((client_ip, "login"), max_requests=_limit, window=_window):
            return Response("请求过于频繁", status=429)

        username = sanitize_input(request.form.get("username", ""), 50)
        password = request.form.get("password", "").strip()
        captcha_input = request.form.get("captcha", "").strip().lower()

        # ---- 诊断日志：记录每次登录尝试的详细信息 ----

        _login_logger = logging.getLogger('login_diag')
        _login_logger.setLevel(logging.DEBUG)
        if not _login_logger.handlers:
            _h = logging.FileHandler('/tmp/login_diag.log')
            _h.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
            _login_logger.addHandler(_h)
        _login_logger.info(
            f"LOGIN_ATTEMPT | user={username} | pwd_len={len(password)} | "
            f"captcha_input='{captcha_input}' | captcha_session='{session.get('captcha_code','')}' | "
            f"ip={client_ip} | ua={request.headers.get('User-Agent','?')[:80]}"
        )

        if not username or not password:
            _login_logger.info(f"LOGIN_FAIL | reason=empty_fields | user={username}")
            flash("用户名和密码不能为空", "danger")
            return render_template("login.html", csrf_token=session.get("csrf_token", ""))

        # 验证码校验
        ok, err_msg = _verify_captcha(captcha_input)
        if not ok:
            _login_logger.info(f"LOGIN_FAIL | reason=captcha | msg={err_msg} | user={username}")
            flash(err_msg, "danger")
            return render_template("login.html", csrf_token=session.get("csrf_token", ""))

        # 登录防爆破检查（文件持久化，多 worker 共享）
        if not rate_limiter.check((username, "login_fail"), max_requests=5, window=300):
            flash("账户已被锁定，请 5 分钟后重试", "danger")
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

            if result:
                pwd_valid = safe_check_password_hash(result[0], password)
                if not pwd_valid:
                    # 回退：数据库中的密码可能是明文（旧版），尝试明文匹配
                    pwd_valid = (result[0] == password)
                _login_logger.info(f"LOGIN_DB_CHECK | user={username} | pwd_valid={pwd_valid} | perm={result[1]}")
                if pwd_valid:
                    # 生成新的 session_key
                    new_session_key = uuid.uuid4().hex
                    # 多用户同时在线：检查是否允许
                    allow_multi = session_manager.get_user_allow_multi_login(username)
                    if not allow_multi:
                        # 不允许同时在线，踢出所有旧会话
                        session_manager.kick_user_sessions(username, except_session_key=new_session_key)
                    session["username"] = username
                    session["permission"] = result[1]
                    session["csrf_token"] = os.urandom(32).hex()
                    session["_last_request_time"] = time.time()
                    # 注册数据库会话（多用户同时在线追踪）
                    session["session_key"] = new_session_key
                    session_manager.register_session(
                        session_key=new_session_key,
                        username=username,
                        ip=client_ip,
                        user_agent=request.headers.get("User-Agent", "")[:500]
                    )
                    # 如果密码是明文匹配的，升级为 hash
                    if result[0] == password:
                        hashed = generate_password_hash(password)
                        try:
                            cursor_upgrade = conn.cursor()
                            cursor_upgrade.execute("UPDATE users SET User_Password=%s WHERE User_Name=%s", (hashed, username))
                            conn.commit()
                            cursor_upgrade.close()
                        except Exception:
                            pass
                        write_log("用户登录(旧版密码升级hash)", f"用户名: {username}")
                        flash(f"欢迎回来，{sanitize_input(username)}！密码已升级为更安全的存储方式", "success")
                    else:
                        write_log("用户登录", f"用户名: {username}, 权限: {result[1]}")
                        flash(f"欢迎回来，{sanitize_input(username)}！", "success")
                    record_activity(username, "登录", 1)
                    # 检查是否设置了安全问题，未设置则在 dashboard 提醒
                    has_security = False
                    try:
                        conn_check = get_db()
                        if conn_check:
                            cur_check = conn_check.cursor()
                            cur_check.execute(
                                "SELECT security_question FROM users WHERE User_Name=%s",
                                (username,)
                            )
                            sec = cur_check.fetchone()
                            has_security = sec and sec[0] and sec[0].strip()
                            cur_check.close()
                            conn_check.close()
                    except Exception:
                        pass
                    session["_warn_no_security"] = not has_security
                    _login_logger.info(f"LOGIN_SUCCESS | user={username} | perm={result[1]} | redirect_to=/dashboard")
                    return redirect(url_for("dashboard"))
                else:
                    # 密码错误
                    _login_logger.info(f"LOGIN_FAIL | reason=wrong_password | user={username}")
                    write_log("登录失败", f"用户名: {username}, 密码错误")
                    flash("用户名或密码错误", "danger")
            else:
                # 登录失败（用户名不存在）
                _login_logger.info(f"LOGIN_FAIL | reason=user_not_found | user={username}")
                write_log("登录失败", f"用户名: {username}")
                flash("用户名或密码错误", "danger")
        except pymysql.MySQLError as e:
            _login_logger.info(f"LOGIN_FAIL | reason=db_error | error={e}")
            flash(f"数据库错误: {str(e)}", "danger")

    return render_template("login.html", csrf_token=session.get("csrf_token", ""))


@app.route("/register", methods=["GET", "POST"])
def register():
    """
    用户注册页面（URL: /register）。

    权限：无需登录
    GET 逻辑：
      - 生成 CSRF token
    POST 逻辑：
      - 受 register 速率限制（默认 5 次/60 秒）
      - 验证码校验
      - 密码复杂度检查（至少 8 位 + 字母 + 数字）
      - 管理员注册：填写正确 ADMIN_SECRET 可获得管理员权限
      - 用户名查重（主动检测而非依赖 UNIQUE 约束报错）
    """
    _init_db_once()
    # 生成 CSRF token
    if "csrf_token" not in session:
        session["csrf_token"] = os.urandom(32).hex()
    if request.method == "POST":
        # 注册速率限制
        client_ip = request.remote_addr or "unknown"
        _limit, _window = RATE_LIMITS["register"]
        if not rate_limiter.check((client_ip, "register"), max_requests=_limit, window=_window):
            return Response("请求过于频繁", status=429)

        # 验证码校验
        captcha_input = request.form.get("captcha", "").strip().lower()
        ok, err_msg = _verify_captcha(captcha_input)
        if not ok:
            flash(err_msg, "danger")
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
            # 检查用户名是否已存在（主动检测，而非依赖 UNIQUE 约束报错）
            cursor.execute("SELECT COUNT(*) FROM users WHERE User_Name = %s", (username,))
            if cursor.fetchone()[0] > 0:
                flash("用户名已存在，请更换", "danger")
                cursor.close()
                conn.close()
                return render_template("register.html", csrf_token=session.get("csrf_token", ""))

            hashed_pw = generate_password_hash(password)
            cursor.execute(
                "INSERT INTO users (User_Name, User_Password, Access_Permission) VALUES (%s, %s, %s)",
                (username, hashed_pw, permission)
            )
            conn.commit()
            cursor.close()
            conn.close()
            perm_text = "管理员" if permission == "administrator" else "访客"
            write_log("用户注册", f"用户名: {username}, 权限: {perm_text}")
            flash(f"注册成功！权限: {perm_text}", "success")
            return redirect(url_for("login"))
        except pymysql.IntegrityError:
            flash("用户名已存在", "danger")
        except pymysql.MySQLError as e:
            flash(f"注册失败: {str(e)}", "danger")

    return render_template("register.html", csrf_token=session.get("csrf_token", ""))


@app.route("/logout", methods=["GET", "POST"])
def logout():
    """
    退出登录（URL: /logout）。

    权限：任意用户
    GET 逻辑：显示确认页面
    POST 逻辑：清除 session + 标记数据库会话为非活跃
    """
    if request.method == "GET":
        # GET 请求：显示确认页面（可优化为直接重定向带 JS 提交）
        return render_template("logout_confirm.html",
                               csrf_token=session.get("csrf_token", ""))
    # POST 请求：执行登出
    ip = request.remote_addr or "0.0.0.0"
    # 标记数据库会话为非活跃
    session_manager.logout_session(
        session_key=session.get("session_key", ""),
        username=session.get("username", ""),
        ip=ip,
        reason="logout"
    )
    session.clear()
    flash("已退出登录", "info")
    return redirect(url_for("login"))


# ---------- 路由：忘记密码 ----------

@app.route("/forgot_password", methods=["GET", "POST"])

# ========== 忘记密码 / 重置密码 ==========

def forgot_password():
    _init_db_once()
    _generate_captcha()  # 预生成验证码，避免图片加载失败导致 captcha_code 不存在
    # 生成 CSRF token
    if "csrf_token" not in session:
        session["csrf_token"] = os.urandom(32).hex()

    security_question = None  # 展示给用户的安全问题
    reset_token = None        # 生成的重置令牌

    if request.method == "POST":
        ip = request.remote_addr or "0.0.0.0"

        # 速率限制：每 IP 3分钟内最多3次尝试（文件持久化，多 worker 共享）
        if not rate_limiter.check((ip, "forgot_password"), max_requests=3, window=180):
            flash("操作过于频繁，请 3 分钟后重试", "danger")
            return render_template("forgot_password.html",
                                   csrf_token=session.get("csrf_token", ""),
                                   security_question=None, reset_token=None)

        # 验证码校验
        captcha_input = request.form.get("captcha", "").strip().lower()
        ok, err_msg = _verify_captcha(captcha_input)
        if not ok:
            flash(err_msg, "danger")
            return render_template("forgot_password.html",
                                   csrf_token=session.get("csrf_token", ""),
                                   security_question=None, reset_token=None)

        # 判断是第一步（输入用户名）还是第二步（回答安全问题）
        step = request.form.get("step", "1")

        if step == "1":
            # 第一步：验证用户名，查找安全问题
            username = sanitize_input(request.form.get("username", ""), 50)
            if not username:
                flash("请输入用户名", "danger")
                return render_template("forgot_password.html",
                                       csrf_token=session.get("csrf_token", ""),
                                       security_question=None, reset_token=None)

            # 安全：防止用户名枚举——统一返回消息
            conn = get_db()
            if not conn:
                flash("数据库连接失败，请稍后重试", "danger")
                return render_template("forgot_password.html",
                                       csrf_token=session.get("csrf_token", ""),
                                       security_question=None, reset_token=None)

            cursor = conn.cursor()
            cursor.execute(
                "SELECT security_question FROM users WHERE User_Name=%s", (username,)
            )
            row = cursor.fetchone()
            cursor.close()
            conn.close()

            if not row:
                # 用户名不存在——不直接告知，统一提示
                flash("如果该用户存在且设置了安全问题，将进入下一步验证", "info")
            elif not row[0] or not row[0].strip():
                # 无安全问题 → 设置 session 并显示管理员申请表单
                session["reset_username"] = username
                session["reset_attempts"] = 0
                flash("该用户未设置安全问题，请通过管理员申请重置密码", "warning")
            else:
                session["reset_username"] = username
                session["reset_attempts"] = 0  # 重置错误尝试次数
                security_question = row[0]
                flash("请回答您的安全问题以验证身份", "info")

        elif step == "2":
            # 第二步：验证安全问题答案
            username = session.get("reset_username", "")
            if not username:
                flash("会话已过期，请重新操作", "danger")
                return render_template("forgot_password.html",
                                       csrf_token=session.get("csrf_token", ""),
                                       security_question=None, reset_token=None)

            # 安全：按用户名限制安全答案尝试次数（文件持久化，不可通过清 Cookie 绕过）
            if not rate_limiter.check((username, "forgot_pwd_answer"), max_requests=5, window=1800):
                session.pop("reset_username", None)
                session.pop("reset_attempts", None)
                flash("安全答案错误次数过多，请 30 分钟后重试", "danger")
                return render_template("forgot_password.html",
                                       csrf_token=session.get("csrf_token", ""),
                                       security_question=None, reset_token=None)

            security_answer = request.form.get("security_answer", "").strip()
            if not security_answer:
                flash("请输入安全问题的答案", "danger")
                # 重新获取安全问题
                conn = get_db()
                if conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT security_question FROM users WHERE User_Name=%s", (username,)
                    )
                    row = cursor.fetchone()
                    cursor.close()
                    conn.close()
                    security_question = row[0] if row else None
                return render_template("forgot_password.html",
                                       csrf_token=session.get("csrf_token", ""),
                                       security_question=security_question, reset_token=None)

            conn = get_db()
            if not conn:
                flash("数据库连接失败", "danger")
                return render_template("forgot_password.html",
                                       csrf_token=session.get("csrf_token", ""),
                                       security_question=None, reset_token=None)

            cursor = conn.cursor()
            cursor.execute(
                "SELECT security_question, security_answer FROM users WHERE User_Name=%s",
                (username,)
            )
            row = cursor.fetchone()

            if not row:
                flash("用户不存在", "danger")
                session.pop("reset_username", None)
            else:
                stored_answer = (row[1] or "").strip()
                # 大小写不敏感比较，使用 hmac 防时序攻击
                if not hmac.compare_digest(
                    security_answer.lower().strip(),
                    stored_answer.lower()
                ):
                    # 错误次数记录（双重保障：session 内计数 + 文件持久化限制）
                    attempts = session.get("reset_attempts", 0) + 1
                    session["reset_attempts"] = attempts
                    remaining = 5 - attempts
                    if attempts >= 5:
                        session.pop("reset_username", None)
                        session.pop("reset_attempts", None)
                        flash("安全问题答案错误次数过多，请重新操作", "danger")
                    else:
                        flash(f"安全问题答案错误，还剩 {remaining} 次机会", "danger")
                        security_question = row[0]
                else:
                    # 验证通过！生成重置令牌
                    session.pop("reset_attempts", None)
                    session.pop("reset_username", None)

                    # 作废旧令牌
                    cursor.execute(
                        "UPDATE password_reset_tokens SET used=1 WHERE username=%s AND used=0",
                        (username,)
                    )
                    cursor.execute("DELETE FROM password_reset_tokens WHERE expires_at < NOW()")
                    token = uuid.uuid4().hex
                    expires = datetime.now() + timedelta(minutes=10)
                    cursor.execute(
                        "INSERT INTO password_reset_tokens (username, token, expires_at) VALUES (%s,%s,%s)",
                        (username, token, expires)
                    )
                    conn.commit()
                    write_log("密码重置申请（安全问题验证通过）", f"用户名: {username}, IP: {ip}")
                    reset_token = token
                    flash("身份验证通过！请复制下方令牌前往重置密码页面", "success")

            cursor.close()
            conn.close()

        elif step == "3":
            # 第三步：提交管理员重置申请
            username = session.get("reset_username", "")
            if not username:
                flash("会话已过期，请重新操作", "danger")
                return render_template("forgot_password.html",
                                       csrf_token=session.get("csrf_token", ""),
                                       security_question=None, reset_token=None,
                                       admin_reset_needed=False)

            # 安全：按用户名限制管理员重置申请频率（防止骚扰）
            if not rate_limiter.check((username, "forgot_pwd_admin_req"), max_requests=1, window=86400):
                flash("该用户 24 小时内已提交过管理员重置申请，请耐心等待审核", "danger")
                return render_template("forgot_password.html",
                                       csrf_token=session.get("csrf_token", ""),
                                       security_question=None, reset_token=None,
                                       admin_reset_needed=True)

            reason = sanitize_input(request.form.get("reason", ""), 500)
            contact = sanitize_input(request.form.get("contact", ""), 100)
            if not reason:
                flash("请填写申请理由", "danger")
                return render_template("forgot_password.html",
                                       csrf_token=session.get("csrf_token", ""),
                                       security_question=None, reset_token=None,
                                       admin_reset_needed=True)

            conn = get_db()
            if not conn:
                flash("数据库连接失败", "danger")
                return render_template("forgot_password.html",
                                       csrf_token=session.get("csrf_token", ""),
                                       security_question=None, reset_token=None,
                                       admin_reset_needed=True)

            cursor = conn.cursor()
            # 作废旧申请
            cursor.execute(
                "UPDATE password_reset_tokens SET request_status='cancelled' WHERE username=%s AND request_status='pending'",
                (username,)
            )
            cursor.execute("DELETE FROM password_reset_tokens WHERE expires_at < NOW()")
            # 创建新地待审核申请（token 为 NULL，等待管理员审核）
            cursor.execute(
                "INSERT INTO password_reset_tokens (username, token, used, request_reason, request_status, expires_at) VALUES (%s, NULL, 0, %s, 'pending', DATE_ADD(NOW(), INTERVAL 7 DAY))",
                (username, f"联系方式: {contact or '未提供'}\n申请理由: {reason}")
            )
            conn.commit()
            cursor.close()
            conn.close()

            session.pop("reset_username", None)
            session.pop("reset_attempts", None)
            write_log("管理员重置申请", f"用户名: {username}, IP: {ip}, 理由: {reason}")
            flash("申请已提交，管理员审核通过后请重新访问此页面获取令牌。", "success")

    # 判断是否需要显示管理员申请表单
    admin_needed = bool(
        session.get("reset_username") and
        not security_question and
        not reset_token
    )

    return render_template("forgot_password.html",
                           csrf_token=session.get("csrf_token", ""),
                           security_question=security_question,
                           reset_token=reset_token,
                           admin_reset_needed=admin_needed)


@app.route("/reset_password", methods=["GET", "POST"])
def reset_password():
    """
    重置密码页面（URL: /reset_password）。

    权限：需要有效的重置令牌（从 forgot_password 流程获取）
    安全：令牌 + 用户名 + 验证码 + 密码复杂度四重校验。
          不允许新密码与旧密码相同。
    """
    _init_db_once()
    _generate_captcha()  # 预生成验证码
    # 生成 CSRF token
    if "csrf_token" not in session:
        session["csrf_token"] = os.urandom(32).hex()
    if request.method == "POST":
        username = sanitize_input(request.form.get("username", ""), 50)
        token = sanitize_input(request.form.get("token", ""), 32)
        new_pwd = request.form.get("new_pwd", "").strip()
        confirm_pwd = request.form.get("confirm_pwd", "").strip()
        captcha_input = request.form.get("captcha", "").strip().lower()
        ok_captcha, err_captcha = _verify_captcha(captcha_input)

        if not username or not token:
            flash("用户名和重置令牌不能为空", "danger")
        elif not ok_captcha:
            flash(err_captcha, "danger")
        elif new_pwd != confirm_pwd:
            flash("两次密码不一致", "danger")
        elif len(new_pwd) < 8:
            flash("密码至少8位", "danger")
        elif not re.search(r"[A-Za-z]", new_pwd):
            flash("密码需包含字母", "danger")
        elif not re.search(r"[0-9]", new_pwd):
            flash("密码需包含数字", "danger")
        else:
            # 安全：按用户名限制令牌验证尝试（防止暴力枚举令牌）
            if not rate_limiter.check((username, "reset_pwd_token"), max_requests=5, window=600):
                flash("重置密码尝试次数过多，请 10 分钟后重试", "danger")
                return render_template("reset_password.html",
                                       csrf_token=session.get("csrf_token", ""))
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
                    if old_pw and safe_check_password_hash(old_pw[0], new_pwd):
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
    """
    记录用户活跃行为到 activity_log 表。

    用于计算活跃度排行榜。不同操作积分不同（如上传图片 5 分、评论 2 分、登录 1 分）。
    数据库异常时静默忽略，不影响主流程。

    Args:
        username: 用户名
        action: 行为描述（如 "登录"、"上传图片"）
        points: 该行为的活跃积分（默认 1）
    """
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
    """
    活跃度排行榜 API（URL: /api/leaderboard, GET）。

    权限：任意用户
    功能：返回总分降序的排行榜列表，支持 limit 参数。
    """
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

# ========== 管理员申请/审核 ==========

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
        cursor.execute("SELECT id, status FROM admin_requests WHERE username=%s", (username,))
        existing = cursor.fetchone()
        if existing:
            if existing[1] == "pending":
                return jsonify({"error": "你已有待审核的申请"}), 400
            elif existing[1] == "approved":
                return jsonify({"error": "你的申请已经通过了"}), 400
            else:
                # 之前被拒绝的，更新为重新申请
                cursor.execute(
                    "UPDATE admin_requests SET status='pending', requested_at=NOW(), reviewed_by=NULL, reviewed_at=NULL WHERE username=%s",
                    (username,)
                )
        else:
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
    """
    获取未读通知数量（URL: /api/notifications, GET）。

    权限：需要登录
    功能：返回聊天未读/管理员待处理申请/被封IP/论坛未读通知的数量。
    """
    """获取未读通知数量"""
    username = session["username"]
    is_admin = session.get("permission") == "administrator"
    since = request.args.get("since", "").strip()
    result = {"chat_unread": 0, "admin_requests": 0, "blocked_ips": 0, "forum_unread": 0}

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

    # 论坛未读通知
    try:
        conn3 = get_db()
        if conn3:
            cur3 = conn3.cursor()
            cur3.execute("SELECT COUNT(*) FROM forum_notifications WHERE username=%s AND is_read=0", (username,))
            result["forum_unread"] = cur3.fetchone()[0]
            cur3.close()
            conn3.close()
    except Exception:
        pass

    return jsonify(result)

@app.route("/api/notifications/read", methods=["POST"])
@login_required
def api_notifications_read():
    """
    标记通知已读（URL: /api/notifications/read, POST）。

    权限：需要登录
    功能：记录当前 UTC 时间到 session 的 last_notification_read。
    """
    """标记通知已读"""
    from datetime import datetime
    session["last_notification_read"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    return jsonify({"success": True})

# ---------- 路由：仪表盘 ----------
@app.route("/dashboard")
@login_required
def dashboard():
    """
    仪表盘主页（URL: /dashboard）。

    权限：需要登录
    功能：显示活跃度排行榜、我的排名、待审核请求状态。
    """
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
    # 检查安全问题是否设置（用于提醒）
    warn_no_security = session.pop("_warn_no_security", False)
    if not warn_no_security and session.get("permission") != "administrator":
        # 非首次登录也检查一次（管理员不用提醒）
        try:
            conn = get_db()
            if conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT security_question FROM users WHERE User_Name=%s",
                    (session["username"],)
                )
                sec = cursor.fetchone()
                if not sec or not sec[0] or not sec[0].strip():
                    warn_no_security = True
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
                           pending_admin_reqs=pending_admin_reqs,
                           warn_no_security=warn_no_security)


# ---------- 路由：个人资料 ----------
@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """
    个人资料页面（URL: /profile）。

    权限：需要登录
    GET 逻辑：显示当前用户资料和安全问题信息
    POST 逻辑：更新昵称/简介/手机/邮箱/生日
    """
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

    # 获取安全问题信息
    cursor.execute(
        "SELECT security_question, security_answer FROM users WHERE User_Name=%s",
        (session["username"],)
    )
    sec_row = cursor.fetchone()
    has_security = sec_row and sec_row[0] and sec_row[0].strip()

    cursor.close()
    conn.close()
    return render_template("profile.html",
                           username=session["username"],
                           permission=session["permission"],
                           profile=profile_data,
                           security_question=sec_row[0] if has_security else "",
                           has_security=has_security,
                           csrf_token=session.get("csrf_token", ""))


# ---------- API：设置安全问题 ----------
@app.route("/api/profile/security", methods=["POST"])
@login_required
def api_set_security():
    """设置或更新用户的安全问题及答案"""
    data = request.get_json(silent=True) or {}
    security_question = sanitize_input(data.get("security_question", ""), 200)
    security_answer = sanitize_input(data.get("security_answer", ""), 200)

    if not security_question or not security_answer:
        # 允许清除安全问题（两个都为空）
        if security_question == "" and security_answer == "":
            conn = get_db()
            if not conn:
                return jsonify({"ok": False, "error": "数据库连接失败"})
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE users SET security_question=NULL, security_answer=NULL WHERE User_Name=%s",
                    (session["username"],)
                )
                conn.commit()
                cursor.close()
                conn.close()
                write_log("安全问题清除", f"用户名: {session['username']}")
                return jsonify({"ok": True, "message": "安全问题已清除"})
            except pymysql.MySQLError as e:
                return jsonify({"ok": False, "error": f"操作失败: {str(e)}"})
        return jsonify({"ok": False, "error": "安全问题和答案不能为空"})

    if len(security_answer) < 2:
        return jsonify({"ok": False, "error": "答案至少需要2个字符"})

    conn = get_db()
    if not conn:
        return jsonify({"ok": False, "error": "数据库连接失败"})

    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET security_question=%s, security_answer=%s WHERE User_Name=%s",
            (security_question, security_answer, session["username"])
        )
        conn.commit()
        affected = cursor.rowcount
        cursor.close()
        conn.close()
        if affected:
            write_log("安全问题设置", f"用户名: {session['username']}")
            return jsonify({"ok": True, "message": "安全问题已设置"})
        else:
            return jsonify({"ok": False, "error": "用户不存在"})
    except pymysql.MySQLError as e:
        return jsonify({"ok": False, "error": f"保存失败: {str(e)}"})


# ---------- 路由：关于作者 ----------
@app.route("/author")
def author():
    """
    关于作者页面（URL: /author）。

    权限：任意用户（无需登录）
    """
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
    """
    即时聊天页面（URL: /chat）。

    权限：需要登录
    功能：世界频道 + 私聊 + 好友系统，前端通过 Web 聊天界面交互。
    """
    return render_template("chat_standalone.html",
                           username=session["username"],
                           permission=session["permission"])


# ---------- 路由：AI 写作助手 ----------
@app.route("/ai_writing")
@login_required
def ai_writing_page():
    """
    AI 写作助手页面（URL: /ai_writing）。

    权限：需要登录
    功能：提供演讲稿/通知/社交媒体/工作报告/邮件等多种写作模式，
          调用用户配置的 AI API 生成文本。
    """
    return render_template("ai_writing.html",
                           username=session.get("username", ""),
                           permission=session.get("permission", "guest"))


# ---------- 路由：AI 配置页面 ----------
@app.route("/ai_config")
@login_required
def ai_config_page():
    return render_template("ai_config.html",
                           username=session.get("username", ""),
                           permission=session.get("permission", "guest"))


# ---------- 路由：智能翻译 ----------
@app.route("/translator")
@login_required
def translator_page():
    """
    智能翻译页面（URL: /translator）。

    权限：需要登录
    功能：调用用户配置的 AI API 进行翻译，支持中/英/日/韩互译。
    """
    return render_template("translator.html",
                           username=session.get("username", ""),
                           permission=session.get("permission", "guest"))


# ---------- 路由：系统监控 ----------
@app.route("/system_monitor")
@login_required
@admin_required
def system_monitor():
    """
    系统监控页面（URL: /system_monitor）。

    权限：需要管理员权限
    功能：通过 /api/system_info 和 /api/system_users 展示服务器状态。
    """
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
        uptime_seconds = int(datetime.now().timestamp() - boot_time)
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
    """返回当前在线用户及活动信息（基于数据库会话追踪）"""
    now = time.time()
    sessions = session_manager.get_active_sessions(include_idle=False)
    # 按 username 去重，每个用户只显示最活跃的会话
    user_map = {}
    for s in sessions:
        u = s["username"]
        if u not in user_map or s["idle_seconds"] < user_map[u]["idle_seconds"]:
            user_map[u] = s

    blocked_ips = rate_limiter.get_blocked_ips()
    active_ips = rate_limiter.get_active_ips()

    users = []
    for username, s in user_map.items():
        ip = s["ip"]
        blocked = ip in blocked_ips
        whitelisted = ip in ip_whitelist
        manual_blocked = ip in ip_manual_blocked and now < ip_manual_blocked[ip]

        # 速率统计
        reqs = active_ips.get(ip, 0)

        users.append({
            "username": username,
            "ip": ip,
            "idle_seconds": s["idle_seconds"],
            "idle_str": s["idle_str"],
            "login_time": s["login_time"],
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
            cursor.execute("SELECT COUNT(*) FROM users WHERE Access_Permission='administrator'")
            row = cursor.fetchone()
            admin_count = row[0] if row else 0
            cursor.execute("SELECT COUNT(*) FROM users WHERE Access_Permission='vip'")
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


# ---------- 多用户同时在线 API ----------

@app.route("/api/heartbeat", methods=["POST"])
@login_required

# ========== 多用户会话管理 ==========

def api_heartbeat():
    """前端心跳：保持会话活跃"""
    ok = session_manager.heartbeat(
        session_key=session.get("session_key", ""),
        username=session.get("username", ""),
        ip=request.remote_addr or "0.0.0.0"
    )
    online_count = session_manager.get_online_count()
    return jsonify({"ok": ok, "online_count": online_count})


@app.route("/api/online_users", methods=["GET"])
@login_required
def api_online_users():
    """返回当前在线用户列表（按 username 去重）"""
    sessions = session_manager.get_active_sessions(include_idle=False)
    # 同一用户可能有多个 session，取最活跃的那个
    user_map = {}
    for s in sessions:
        u = s["username"]
        if u not in user_map or s["idle_seconds"] < user_map[u]["idle_seconds"]:
            user_map[u] = s
    
    online_users = sorted(user_map.values(), key=lambda x: x["idle_seconds"])
    
    return jsonify({
        "ok": True,
        "online_count": len(online_users),
        "online_users": online_users,
        "total_sessions": len(sessions),
    })


@app.route("/api/admin/sessions", methods=["GET"])
@login_required
@admin_required
def api_admin_sessions():
    """管理员查看所有活跃会话"""
    sessions = session_manager.get_active_sessions(include_idle=True)
    return jsonify({
        "ok": True,
        "sessions": sessions,
        "total": len(sessions),
    })


@app.route("/api/admin/sessions/kick", methods=["POST"])
@login_required
@admin_required
def api_admin_kick_session():
    """管理员强制踢出用户会话"""
    data = request.get_json(silent=True) or {}
    session_key = data.get("session_key", "").strip()
    if not session_key:
        return jsonify({"ok": False, "error": "缺少 session_key"}), 400
    
    ok, msg = session_manager.kick_session(session_key, session.get("username", ""))
    return jsonify({"ok": ok, "message": msg})


@app.route("/admin/sessions")
@login_required
@admin_required
def admin_sessions_page():
    """管理员会话管理页面"""
    return render_template("admin_sessions.html")


# ---------- 多用户在线：普通用户自管理会话 API ----------

@app.route("/api/my/sessions", methods=["GET"])
@login_required
def api_my_sessions():
    """获取当前用户的所有活跃会话"""
    username = session.get("username", "")
    sessions = session_manager.get_user_sessions(username)
    current_key = session.get("session_key", "")
    return jsonify({
        "ok": True,
        "current_session_key": current_key,
        "sessions": sessions,
        "total": len(sessions),
    })


@app.route("/api/my/sessions/kick", methods=["POST"])
@login_required
def api_my_sessions_kick():
    """用户自行踢出某个设备（不能踢自己当前设备）"""
    data = request.get_json(silent=True) or {}
    session_key = data.get("session_key", "").strip()
    if not session_key:
        return jsonify({"ok": False, "error": "缺少 session_key"}), 400
    current_key = session.get("session_key", "")
    if session_key == current_key:
        return jsonify({"ok": False, "error": "不能踢出当前设备，请使用退出登录"}), 400
    ok, msg = session_manager.end_session(session_key, session.get("username", ""))
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/my/multi_login", methods=["GET", "POST"])
@login_required
def api_multi_login_setting():
    """查询/设置是否允许多设备同时在线"""
    username = session.get("username", "")
    if request.method == "GET":
        allow = session_manager.get_user_allow_multi_login(username)
        return jsonify({"ok": True, "allow_multi_login": allow})
    # POST: 切换设置
    data = request.get_json(silent=True) or {}
    allow = data.get("allow_multi_login", True)
    conn = get_db()
    if not conn:
        return jsonify({"ok": False, "error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO user_profiles (username, allow_multi_login) VALUES (%s, %s) ON DUPLICATE KEY UPDATE allow_multi_login=%s",
            (username, int(allow), int(allow))
        )
        conn.commit()
        cursor.close()
        conn.close()
        # 如果关闭了多设备登录，踢出所有其他设备
        if not allow:
            current_key = session.get("session_key", "")
            session_manager.kick_user_sessions(username, except_session_key=current_key)
        return jsonify({"ok": True, "allow_multi_login": bool(allow)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


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

# ========== 数据库管理 ==========

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
        table_raw = request.form.get("table", "")
        selected_table = _safe_identifier(table_raw)
        if selected_table and selected_table in tables:
            conn = get_db()
            if conn:
                try:
                    cursor = conn.cursor()
                    # 表名已通过 _safe_identifier 正则 + SHOW TABLES 白名单双重校验
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
    table = _safe_identifier(table)
    if not table:
        return jsonify({"error": "非法的表名"}), 400
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
        # 表名已通过 _safe_identifier + SHOW TABLES 双重校验
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
    table = _safe_identifier(table)
    if not table:
        return jsonify({"error": "非法的表名"}), 400
    data = request.get_json()
    if not data:
        return jsonify({"error": "无数据"}), 400
    conn = get_db()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute("SHOW TABLES")
        valid_tables = [r[0] for r in cursor.fetchall()]
        if table not in valid_tables:
            cursor.close()
            return jsonify({"error": "表不存在"}), 404
        # 获取合法列名（复用同一连接，先关闭当前 cursor）
        cursor.close()
        valid_cols = _get_valid_columns(conn, table)
        cursor = conn.cursor()
        invalid = [k for k in data.keys() if _safe_identifier(k) not in valid_cols]
        if invalid:
            cursor.close()
            return jsonify({"error": f"非法列名: {', '.join(invalid)}"}), 400
        cols = ", ".join(f"`{_safe_identifier(k)}`" for k in data.keys())
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
    table = _safe_identifier(table)
    if not table:
        return jsonify({"error": "非法的表名"}), 400
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
        cursor.execute("SHOW TABLES")
        valid_tables = [r[0] for r in cursor.fetchall()]
        if table not in valid_tables:
            cursor.close()
            return jsonify({"error": "表不存在"}), 404
        cursor.close()
        valid_cols = _get_valid_columns(conn, table)
        cursor = conn.cursor()
        # 校验主键列
        pk_col_safe = _safe_identifier(pk_col)
        if not pk_col_safe or pk_col_safe not in valid_cols:
            return jsonify({"error": f"非法主键列: {pk_col}"}), 400
        # 校验所有更新列
        invalid = []
        safe_fields = {}
        for k, v in fields.items():
            k_safe = _safe_identifier(k)
            if not k_safe or k_safe not in valid_cols:
                invalid.append(k)
            else:
                safe_fields[k_safe] = v
        if invalid:
            return jsonify({"error": f"非法列名: {', '.join(invalid)}"}), 400
        set_clause = ", ".join(f"`{k}` = %s" for k in safe_fields.keys())
        sql = f"UPDATE `{table}` SET {set_clause} WHERE `{pk_col_safe}` = %s"
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
    table = _safe_identifier(table)
    if not table:
        return jsonify({"error": "非法的表名"}), 400
    pk_col = request.args.get("pk_col", "")
    if not pk_col:
        return jsonify({"error": "缺少主键字段"}), 400
    conn = get_db()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute("SHOW TABLES")
        valid_tables = [r[0] for r in cursor.fetchall()]
        if table not in valid_tables:
            cursor.close()
            return jsonify({"error": "表不存在"}), 404
        cursor.close()
        valid_cols = _get_valid_columns(conn, table)
        cursor = conn.cursor()
        pk_col_safe = _safe_identifier(pk_col)
        if not pk_col_safe or pk_col_safe not in valid_cols:
            cursor.close()
            return jsonify({"error": f"非法主键列: {pk_col}"}), 400
        sql = f"DELETE FROM `{table}` WHERE `{pk_col_safe}` = %s"
        cursor.execute(sql, [pk_val])
        conn.commit()
        cursor.close()
        conn.close()
        write_log("删除数据", f"表: {table}, 主键: {pk_col}={pk_val}, 用户: {session['username']}")
        return jsonify({"success": True, "affected": cursor.rowcount})
    except pymysql.MySQLError as e:
        return jsonify({"error": str(e)}), 500


# ---------- 路由：更改数据库（可视化） ----------
@app.route("/db_update", methods=["GET", "POST"])
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
    """
    毕业相册首页（URL: /album）。

    权限：需要登录
    功能：优先返回 Vue3 构建后的 dist/index.html，
          开发模式下回退到 Vite dev server 代理页面。
    """
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
            cursor.execute("INSERT INTO album_share_links (image_id, token, username) VALUES (%s, %s, %s)", [img_id, token, session["username"]])
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
    """
    分享链接查看页（URL: /share/<token>）。

    权限：任意访问者（无需登录）
    功能：通过分享 token 查询对应图片并以纯 HTML 展示。
          安全：token 为 uuid4 hex，不可猜测；不暴露原始图片路径。
    """
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


# ---------- AI 机器人 ----------

def _ai_encrypt(text):
    """
    简单加密 API Key：与 app.secret_key 异或后 Base64 编码。

    安全：不是真正的对称加密，仅做混淆存储，防御数据库泄露后的明文 API Key 暴露。
    真正的安全方案应使用环境变量注入。
    """
    import base64
    key = app.secret_key or "default_key"
    key_bytes = (key * ((len(text.encode()) // len(key)) + 2)).encode()
    xored = bytes(a ^ b for a, b in zip(text.encode(), key_bytes))
    return base64.urlsafe_b64encode(xored).decode()

def _ai_decrypt(encrypted):
    """
    解密 API Key（_ai_encrypt 的逆操作）。

    从 Base64 解码后与 secret_key 异或还原原始 API Key。
    """
    import base64
    key = app.secret_key or "default_key"
    data = base64.urlsafe_b64decode(encrypted.encode())
    key_bytes = (key * ((len(data) // len(key)) + 2)).encode()
    return bytes(a ^ b for a, b in zip(data, key_bytes)).decode()


@app.route("/api/chat/ai/config", methods=["GET", "POST"])
@login_required
def api_chat_ai_config():
    """获取/保存 AI 配置"""
    user = session["username"]
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500

    if request.method == "GET":
        cursor = conn.cursor()
        cursor.execute("SELECT provider_url, model_name, api_key_encrypted FROM ai_config WHERE username=%s", (user,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row:
            return jsonify({
                "provider_url": row[0],
                "model_name": row[1],
                "has_key": bool(row[2])
            })
        return jsonify({"provider_url": "", "model_name": "gpt-3.5-turbo", "has_key": False})

    # POST: 保存配置
    data = request.get_json() or {}
    provider_url = sanitize_input(data.get("provider_url", ""), 500)
    model_name = sanitize_input(data.get("model_name", "gpt-3.5-turbo"), 100)
    api_key = data.get("api_key", "")

    if not provider_url:
        return jsonify({"error": "请填写 API 地址"}), 400
    if not api_key:
        return jsonify({"error": "请填写 API Key"}), 400

    encrypted = _ai_encrypt(api_key)

    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO ai_config (username, provider_url, api_key_encrypted, model_name)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE provider_url=VALUES(provider_url),
                                api_key_encrypted=VALUES(api_key_encrypted),
                                model_name=VALUES(model_name)
    """, (user, provider_url, encrypted, model_name))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/chat/ai/messages")
@login_required
def api_chat_ai_messages():
    """获取 AI 对话历史"""
    user = session["username"]
    limit = min(int(request.args.get("limit", 50)), 200)
    conn = get_album_db()
    if not conn:
        return jsonify([])
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, role, content, created_at FROM ai_conversations WHERE username=%s ORDER BY id DESC LIMIT %s",
        (user, limit)
    )
    cols = [d[0] for d in cursor.description]
    rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
    for r in rows:
        r["created_at"] = str(r["created_at"])
    cursor.close()
    conn.close()
    rows.reverse()
    return jsonify(rows)


@app.route("/api/chat/ai/ask", methods=["POST"])
@login_required
def api_chat_ai_ask():
    """向 AI 发送消息并获取回复"""
    user = session["username"]
    data = request.get_json() or {}
    message = sanitize_input(data.get("message", ""), 4000)
    if not message:
        return jsonify({"error": "消息不能为空"}), 400

    # 加载用户配置
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    cursor = conn.cursor()
    cursor.execute("SELECT provider_url, api_key_encrypted, model_name FROM ai_config WHERE username=%s", (user,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        return jsonify({"error": "请先配置 AI 机器人（点击侧边栏 ⚙️ 设置）"}), 400

    provider_url, api_key_encrypted, model_name = row
    try:
        api_key = _ai_decrypt(api_key_encrypted)
    except Exception:
        return jsonify({"error": "API Key 解密失败，请重新设置"}), 500

    # 获取最近对话历史作为上下文
    conn = get_album_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT role, content FROM ai_conversations WHERE username=%s ORDER BY id DESC LIMIT 20",
        (user,)
    )
    history = list(cursor.fetchall())
    history.reverse()
    cursor.close()
    conn.close()

    # 构建消息列表
    system_prompt = "你是一个有用的 AI 助手，内置于多合一工具箱中。请用简洁、友好的方式回答问题。"
    messages = [{"role": "system", "content": system_prompt}]
    for role, content in history:
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    # 保存用户消息
    conn = get_album_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO ai_conversations (username, role, content) VALUES (%s, %s, %s)",
                   (user, "user", message))
    conn.commit()
    cursor.close()
    conn.close()

    # 调用 AI 提供商 API
    api_url = provider_url.rstrip("/")
    if not api_url.endswith("/chat/completions"):
        api_url += "/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 2000
    }

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=60)
        if resp.status_code != 200:
            err_text = resp.text[:300]
            return jsonify({"error": f"AI API 返回错误 ({resp.status_code}): {err_text}"}), 502

        result = resp.json()
        ai_reply = result["choices"][0]["message"]["content"]

        # 保存 AI 回复
        conn = get_album_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO ai_conversations (username, role, content) VALUES (%s, %s, %s)",
                       (user, "assistant", ai_reply))
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"reply": ai_reply})

    except requests.exceptions.Timeout:
        return jsonify({"error": "AI API 请求超时（60秒）"}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({"error": f"无法连接到 {provider_url}，请检查 API 地址"}), 502
    except Exception as e:
        return jsonify({"error": f"请求失败: {str(e)}"}), 500


@app.route("/api/chat/ai/clear", methods=["POST"])
@login_required
def api_chat_ai_clear():
    """清空当前用户的 AI 对话历史"""
    user = session["username"]
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "DB"}), 500
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ai_conversations WHERE username=%s", (user,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"success": True})


@app.route("/api/chat/ai/test", methods=["POST"])
@login_required
def api_chat_ai_test():
    """测试 AI 连接是否正常"""
    import time
    user = session["username"]
    conn = get_album_db()
    if not conn:
        return jsonify({"success": False, "error": "数据库连接失败"}), 500
    cursor = conn.cursor()
    cursor.execute("SELECT provider_url, api_key_encrypted, model_name FROM ai_config WHERE username=%s", (user,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        return jsonify({"success": False, "error": "请先配置 AI 连接信息"}), 400

    provider_url, api_key_encrypted, model_name = row
    try:
        api_key = _ai_decrypt(api_key_encrypted)
    except Exception:
        return jsonify({"success": False, "error": "API Key 解密失败，请重新设置"}), 500

    api_url = provider_url.rstrip("/")
    if not api_url.endswith("/chat/completions"):
        api_url += "/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 5
    }

    start = time.time()
    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=15)
        latency = int((time.time() - start) * 1000)
        if resp.status_code == 200:
            result = resp.json()
            return jsonify({"success": True, "model": result.get("model", model_name), "latency_ms": latency})
        else:
            err_text = resp.text[:200]
            return jsonify({"success": False, "error": f"API 返回 {resp.status_code}: {err_text}", "latency_ms": latency})
    except Exception as e:
        latency = int((time.time() - start) * 1000)
        return jsonify({"success": False, "error": f"连接失败: {str(e)}", "latency_ms": latency})


# ---- AI 写作助手 ----
@app.route("/api/ai/writing", methods=["POST"])
@login_required
def api_ai_writing():
    """AI 写作助手：根据模式和主题生成文本"""
    user = session["username"]
    data = request.get_json() or {}
    mode = data.get("mode", "free")
    topic = sanitize_input(data.get("topic", ""), 500)
    requirements = sanitize_input(data.get("requirements", ""), 1000)

    # 模式系统提示词
    mode_prompts = {
        "speech": "你是一位专业的演讲稿撰写人。请根据用户提供的主题和要求，撰写一份正式、有条理、富有感染力的发言稿。注意使用恰当的称呼、过渡语和结束语。",
        "notice": "你是一位活动策划专家。请撰写一份清晰、吸引人的活动通知，包含活动主题、时间地点、议程亮点、参与方式等关键信息。",
        "social": "你擅长写生动有趣的社交媒体文案。请用轻松自然的语气撰写，适当使用emoji，让文案有互动感和分享欲。长度控制在朋友圈舒适阅读范围。",
        "report": "你是一位职场写作专家。请根据用户提供的信息，撰写一份结构清晰的工作总结，突出成果、数据支撑、经验教训和下一步计划。",
        "email": "你是一位商务邮件撰写专家。请使用得体的商务语气，撰写格式规范的邮件，包含恰当的主题行、称呼和署名。",
        "free": "你是一个创意写作助手。请根据用户的描述自由创作，不拘泥于特定格式，发挥你的创造力。",
    }
    system_prompt = mode_prompts.get(mode, mode_prompts["free"])

    # 构建用户消息
    user_message = ""
    if topic:
        user_message += f"主题：{topic}\n"
    if requirements:
        user_message += f"具体要求：{requirements}\n"
    if mode == "free":
        user_message = topic or requirements or "请帮我写一段文字"
    if not user_message.strip():
        user_message = "请帮我写一段文字"

    # 加载用户 AI 配置
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor()
    cursor.execute("SELECT provider_url, api_key_encrypted, model_name FROM ai_config WHERE username=%s", (user,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        return jsonify({"error": "请先在聊天页配置 AI 机器人（⚙️ 设置）"}), 400

    provider_url, api_key_encrypted, model_name = row
    try:
        api_key = _ai_decrypt(api_key_encrypted)
    except Exception:
        return jsonify({"error": "API Key 解密失败，请重新设置"}), 500

    # 构建请求
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]

    api_url = provider_url.rstrip("/")
    if not api_url.endswith("/chat/completions"):
        api_url += "/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0.8,
        "max_tokens": 3000
    }

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=90)
        if resp.status_code != 200:
            err_text = resp.text[:300]
            return jsonify({"error": f"AI API 返回错误 ({resp.status_code}): {err_text}"}), 502
        result = resp.json()
        ai_reply = result["choices"][0]["message"]["content"]
        return jsonify({"result": ai_reply})
    except requests.exceptions.Timeout:
        return jsonify({"error": "AI API 请求超时（90秒）"}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({"error": f"无法连接到 {provider_url}，请检查 API 地址"}), 502
    except Exception as e:
        return jsonify({"error": f"请求失败: {str(e)}"}), 500


# ---- 智能翻译 ----
@app.route("/api/translator", methods=["POST"])
@login_required
def api_translator():
    """AI 智能翻译"""
    user = session["username"]
    data = request.get_json() or {}
    text = sanitize_input(data.get("text", ""), 5000)
    source = data.get("source", "auto")
    target = data.get("target", "en")

    if not text:
        return jsonify({"error": "请输入要翻译的文本"}), 400
    if source == target:
        return jsonify({"error": "源语言和目标语言不能相同"}), 400

    lang_names = {"zh": "简体中文", "en": "英文", "ja": "日文", "ko": "韩文", "auto": "自动检测"}
    target_name = lang_names.get(target, target)
    source_hint = ""
    if source != "auto":
        source_hint = f"从{lang_names.get(source, source)}"

    system_prompt = f"你是一个专业翻译。请将以下文本{source_hint}翻译成{target_name}。只返回翻译结果，不要添加任何解释、注释或额外内容。保持原文的语气和风格。"

    # 加载用户 AI 配置
    conn = get_album_db()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    cursor = conn.cursor()
    cursor.execute("SELECT provider_url, api_key_encrypted, model_name FROM ai_config WHERE username=%s", (user,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if not row:
        return jsonify({"error": "请先在聊天页配置 AI 机器人（⚙️ 设置）"}), 400

    provider_url, api_key_encrypted, model_name = row
    try:
        api_key = _ai_decrypt(api_key_encrypted)
    except Exception:
        return jsonify({"error": "API Key 解密失败，请重新设置"}), 500

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text}
    ]

    api_url = provider_url.rstrip("/")
    if not api_url.endswith("/chat/completions"):
        api_url += "/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 4000
    }

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=60)
        if resp.status_code != 200:
            err_text = resp.text[:300]
            return jsonify({"error": f"AI API 返回错误 ({resp.status_code}): {err_text}"}), 502
        result = resp.json()
        translated = result["choices"][0]["message"]["content"]
        return jsonify({"translated": translated})
    except requests.exceptions.Timeout:
        return jsonify({"error": "AI API 请求超时（60秒）"}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({"error": f"无法连接到 {provider_url}，请检查 API 地址"}), 502
    except Exception as e:
        return jsonify({"error": f"请求失败: {str(e)}"}), 500


# ---------- 路由：备忘录 ----------
@app.route("/notes", methods=["GET", "POST"])
@login_required
def notes():
    """
    备忘录页面（URL: /notes）。

    权限：需要登录
    功能：每个用户独立的备忘录，内容存储到数据库 user_notes 表（上限 50KB）。
          多用户同时在线互不影响，各自拥有独立的备忘录空间。
    """
    username = session["username"]
    conn = get_db()
    content = ""

    if conn:
        try:
            cursor = conn.cursor()
            if request.method == "POST":
                content = request.form.get("content", "")[:50000]  # 限制 50KB
                cursor.execute(
                    "INSERT INTO user_notes (username, content) VALUES (%s, %s) ON DUPLICATE KEY UPDATE content=%s",
                    (username, content, content)
                )
                conn.commit()
                flash("备忘录已保存", "success")
            else:
                cursor.execute("SELECT content FROM user_notes WHERE username=%s", (username,))
                row = cursor.fetchone()
                if row:
                    content = row[0] or ""
            cursor.close()
        except Exception:
            pass
        finally:
            conn.close()

    return render_template("notes.html",
                           content=content,
                           username=session["username"],
                           permission=session["permission"])


# ---------- 路由：修改密码 ----------
@app.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    """
    修改密码页面（URL: /change_password）。

    权限：需要登录
    管理员：可修改任意用户密码（无需原密码）
    普通用户：需要原密码验证 + 验证码 + 新密码复杂度校验
    """
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
        ok, err_msg = _verify_captcha(captcha_input)
        if not ok:
            flash(err_msg, "danger")
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

                    # 安全：验证操作者（当前登录用户）的身份
                    cursor.execute(
                        "SELECT User_Password FROM users WHERE User_Name = %s",
                        (current_user,)
                    )
                    operator = cursor.fetchone()
                    if not operator:
                        flash("当前用户不存在", "danger")
                        cursor.close()
                        conn.close()
                        return render_template("change_password.html",
                                               is_admin=is_admin, users=users,
                                               username=session["username"],
                                               permission=session["permission"])

                    if is_admin:
                        # 管理员修改他人密码：必须验证管理员自己的密码
                        if target_user != current_user and not safe_check_password_hash(operator[0], old_pwd):
                            flash("管理员密码错误，无法修改他人密码", "danger")
                            cursor.close()
                            conn.close()
                            return render_template("change_password.html",
                                                   is_admin=is_admin, users=users,
                                                   username=session["username"],
                                                   permission=session["permission"])
                        cursor.execute(
                            "UPDATE users SET User_Password = %s WHERE User_Name = %s",
                            (hashed_new, target_user)
                        )
                    else:
                        # 普通用户：只能修改自己的密码，必须验证原密码
                        if target_user != current_user:
                            flash("您只能修改自己的密码", "danger")
                            cursor.close()
                            conn.close()
                            return render_template("change_password.html",
                                                   is_admin=is_admin, users=users,
                                                   username=session["username"],
                                                   permission=session["permission"])
                        if not safe_check_password_hash(operator[0], old_pwd):
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
    """
    管理后台首页（URL: /admin）。

    权限：仅管理员
    功能：显示待处理的权限申请、密码重置申请数量，以及活跃度排行榜。
    """
    pending_admin_reqs = 0
    pending_reset_reqs = 0
    try:
        conn = get_db()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM admin_requests WHERE status='pending'")
            pending_admin_reqs = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM password_reset_tokens WHERE request_status='pending'")
            pending_reset_reqs = cursor.fetchone()[0]
            cursor.close()
            conn.close()
    except Exception:
        pass
    leaderboard = get_leaderboard(10)
    return render_template("admin_dashboard.html",
                           username=session["username"],
                           permission=session["permission"],
                           leaderboard=leaderboard,
                           pending_admin_reqs=pending_admin_reqs,
                           pending_reset_reqs=pending_reset_reqs)


@app.route("/admin/reset_requests")
@login_required
@admin_required
def admin_reset_requests():
    """管理员审核密码重置申请页面"""
    return render_template("admin_reset_requests.html",
                           username=session["username"],
                           permission=session["permission"])


@app.route("/api/admin/ip_stats")
@login_required
@admin_required
def api_admin_ip_stats():
    """
    获取所有 IP 的请求统计（URL: /api/admin/ip_stats, GET）。

    权限：仅管理员
    功能：返回每个 IP 的请求数/速率/封禁状态/白名单/手动封禁等信息。
    """
    """返回所有IP的请求统计（使用文件持久化 RateLimiter，多 worker 共享）"""
    now = time.time()
    blocked_ips = rate_limiter.get_blocked_ips()
    active_req_ips = rate_limiter.get_active_ips()

    result = []
    seen_ips = set()
    # 活跃 IP
    for ip, count in active_req_ips.items():
        seen_ips.add(ip)
        result.append({
            "ip": ip,
            "requests": count,
            "first_request": "-",
            "last_request": "-",
            "rate_per_sec": round(count / max(rate_config["RATE_WINDOW"], 1), 2),
            "blocked": False,
            "block_remaining": 0,
            "block_probes": 0
        })
    # 被封禁 IP
    for ip, remaining in blocked_ips.items():
        if ip not in seen_ips:
            result.append({
                "ip": ip,
                "requests": 0,
                "first_request": "-",
                "last_request": "-",
                "rate_per_sec": 0,
                "blocked": True,
                "block_remaining": remaining,
                "block_probes": 0
            })
        else:
            for r in result:
                if r["ip"] == ip:
                    r["blocked"] = True
                    r["block_remaining"] = remaining
                    break

    # 从数据库获取活跃会话的 IP 信息（替代内存 ip_last_active）
    active_sessions = session_manager.get_active_ips()
    for r in result:
        ip = r["ip"]
        if ip in active_sessions:
            last_active = active_sessions[ip]
            try:
                r["last_active"] = datetime.fromtimestamp(float(last_active)).strftime("%H:%M:%S")
                r["idle_sec"] = int(now - float(last_active))
            except (TypeError, ValueError):
                r["last_active"] = "-"
                r["idle_sec"] = 0
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
        "block_probe_limit": rate_config.get("BLOCK_PROBE_LIMIT", 200),
        "block_extend": rate_config.get("BLOCK_EXTEND", 300)
    })


@app.route("/api/admin/ip_stats", methods=["DELETE"])
@login_required
@admin_required
def api_admin_clear_ip_stats():
    """
    清除 IP 统计数据（URL: /api/admin/ip_stats, DELETE）。

    权限：仅管理员
    功能：清空指定 IP 或所有 IP 的请求记录/封禁状态/白名单。
    """
    """清除IP统计"""
    ip = request.args.get("ip")
    if ip:
        rate_limiter.clear_ip(ip)
        ip_manual_blocked.pop(ip, None)
        ip_whitelist.discard(ip)
    else:
        rate_limiter.clear_all()
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
    rate_limiter.clear_ip(ip)
    ip_manual_blocked.pop(ip, None)
    write_log("管理后台解封IP", f"IP: {ip}, 操作者: {session['username']}")
    return jsonify({"success": True})


@app.route("/api/admin/whitelist", methods=["GET"])
@login_required
@admin_required
def api_admin_whitelist_list():
    """获取白名单列表"""
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
    ip_whitelist.add(ip)
    # 同时清除该IP的封禁状态
    rate_limiter.clear_ip(ip)
    ip_manual_blocked.pop(ip, None)
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
    # 不能封禁白名单IP
    if ip in ip_whitelist:
        return jsonify({"error": "该IP在白名单中，无法封禁"}), 400
    ip_manual_blocked[ip] = time.time() + duration
    rate_limiter.clear_ip(ip)
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
    for ip in ips:
        if ip in ip_whitelist and action == "whitelist":
            skipped.append(ip)
            continue
        if action == "whitelist":
            ip_whitelist.add(ip)
            rate_limiter.clear_ip(ip)
            ip_manual_blocked.pop(ip, None)
            success.append(ip)
        elif action == "block":
            if ip in ip_whitelist:
                skipped.append(ip)
                continue
            ip_manual_blocked[ip] = time.time() + duration
            rate_limiter.clear_ip(ip)
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
    """
    获取速率限制配置（URL: /api/admin/rate_config, GET）。

    权限：仅管理员
    功能：返回当前的 RATE_LIMIT/RATE_WINDOW/BLOCK_DURATION 等配置值。
    """
    """获取速率限制配置"""
    return jsonify(dict(rate_config))

@app.route("/api/admin/rate_config", methods=["POST"])
@login_required
@admin_required
def api_admin_rate_config_set():
    """
    修改速率限制配置（URL: /api/admin/rate_config, POST）。

    权限：仅管理员
    功能：更新 RATE_LIMIT/RATE_WINDOW/BLOCK_DURATION/BLOCK_PROBE_LIMIT/BLOCK_EXTEND。
          所有值必须为正数。修改后持久化到文件。
    """
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
    """
    操作日志查看页面（URL: /logs）。

    权限：仅管理员
    功能：读取 app.log 文件并渲染到模板。
    """
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
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
    # 获取活跃 IP 列表（从文件持久化 RateLimiter）
    active_req_ips = rate_limiter.get_active_ips()
    blocked_ips = rate_limiter.get_blocked_ips()
    active_ips = set()
    ip_stats = {}
    for ip, count in active_req_ips.items():
        active_ips.add(ip)
        ip_stats[ip] = {"requests": count, "blocked": ip in blocked_ips, "manual_blocked": False}
    for ip in blocked_ips:
        active_ips.add(ip)
        if ip not in ip_stats:
            ip_stats[ip] = {"requests": 0, "blocked": True, "manual_blocked": False}
    for ip, blocked_until in list(ip_manual_blocked.items()):
        if now < blocked_until:
            active_ips.add(ip)
            if ip in ip_stats:
                ip_stats[ip]["manual_blocked"] = True
            else:
                ip_stats[ip] = {"requests": 0, "blocked": False, "manual_blocked": True}

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
    """
    日历页面（URL: /calendar）。

    权限：需要登录
    功能：前端渲染日历，通过 /api/calendar/events 获取事件数据。
    """
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
    """
    备份管理页面（URL: /backup）。

    权限：仅管理员
    功能：提供 tar.gz 打包/恢复/删除/对比等备份操作的前端页面。
    """
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
                created = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
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

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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
            "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
    """
    格式化文件大小为人类可读样式。

    Args:
        bytes: 文件字节数

    Returns:
        str: 如 "1.5KB"、"3.2MB"
    """
    if bytes < 1024:
        return f"{bytes}B"
    elif bytes < 1024 * 1024:
        return f"{bytes/1024:.1f}KB"
    else:
        return f"{bytes/1024/1024:.1f}MB"


# ========== 🧰 实用工具 ==========
@app.route("/utils")
@login_required
def utils_page():
    """
    实用工具页面（URL: /utils）。

    权限：需要登录
    功能：密码生成器/哈希计算/Base64/URL 编解码/JSON 格式化/UUID/时间戳/字数统计。
    """
    """实用工具页面（密码生成/哈希/Base64/URL/JSON/UUID/时间戳/字数统计）"""
    return render_template("utils.html",
                           username=session["username"],
                           permission=session["permission"])

# --- 密码生成器 ---
@app.route("/api/utils/password")
@login_required
def api_utils_password():
    length = request.args.get("len", 16, type=int)
    upper = request.args.get("upper", "1") != "0"
    lower = request.args.get("lower", "1") != "0"
    digits = request.args.get("digits", "1") != "0"
    symbols = request.args.get("symbols", "0") != "0"
    length = max(8, min(128, length))
    import string, secrets
    pool = ""
    if upper: pool += string.ascii_uppercase
    if lower: pool += string.ascii_lowercase
    if digits: pool += string.digits
    if symbols: pool += "!@#$%^&*()-_=+[]{}|;:,.<>?"
    if not pool: pool = string.ascii_letters + string.digits
    pw = ''.join(secrets.choice(pool) for _ in range(length))
    # Ensure at least one char from each requested set
    required = []
    if upper: required.append(secrets.choice(string.ascii_uppercase))
    if lower: required.append(secrets.choice(string.ascii_lowercase))
    if digits: required.append(secrets.choice(string.digits))
    if symbols: required.append(secrets.choice("!@#$%^&*()-_=+[]{}|;:,.<>?"))
    pw_list = list(pw)
    for i, ch in enumerate(required):
        pw_list[i] = ch
    import random
    random.shuffle(pw_list)
    return jsonify({"ok": True, "password": ''.join(pw_list)})


# --- 哈希计算器 ---
@app.route("/api/utils/hash")
@login_required
def api_utils_hash():
    text = request.args.get("text", "").strip()
    algo = request.args.get("algo", "sha256")
    if not text:
        return jsonify({"ok": False, "error": "请输入文本"})
    import hashlib
    algos = {"md5": "md5", "sha1": "sha1", "sha256": "sha256", "sha512": "sha512"}
    fn = algos.get(algo)
    if not fn:
        return jsonify({"ok": False, "error": "不支持的算法"})
    h = hashlib.new(fn, text.encode("utf-8"))
    return jsonify({"ok": True, "algo": algo, "hash": h.hexdigest()})


# --- Base64 编解码 ---
@app.route("/api/utils/base64", methods=["POST"])
@login_required
def api_utils_base64():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    action = data.get("action", "encode")
    if not text:
        return jsonify({"ok": False, "error": "请输入文本"})
    import base64
    try:
        if action == "encode":
            result = base64.b64encode(text.encode("utf-8")).decode("ascii")
        else:
            result = base64.b64decode(text.encode("ascii")).decode("utf-8")
        return jsonify({"ok": True, "result": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# --- URL 编解码 ---
@app.route("/api/utils/url", methods=["POST"])
@login_required
def api_utils_url():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    action = data.get("action", "encode")
    if not text:
        return jsonify({"ok": False, "error": "请输入文本"})
    from urllib.parse import quote, unquote
    try:
        result = quote(text, safe="") if action == "encode" else unquote(text)
        return jsonify({"ok": True, "result": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# --- JSON 格式化/校验 ---
@app.route("/api/utils/json", methods=["POST"])
@login_required
def api_utils_json():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    indent = data.get("indent", 2)
    try:
        indent = int(indent)
    except (ValueError, TypeError):
        indent = 2
    indent = max(0, min(8, indent))
    if not text:
        return jsonify({"ok": False, "error": "请输入 JSON 文本"})
    try:
        obj = json.loads(text)
        formatted = json.dumps(obj, indent=indent, ensure_ascii=False)
        return jsonify({"ok": True, "result": formatted, "type": type(obj).__name__})
    except json.JSONDecodeError as e:
        return jsonify({"ok": False, "error": f"JSON 解析错误: {e}"})
    except Exception as e:
        return jsonify({"ok": False, "error": f"处理错误: {e}"})


# --- UUID 生成器 ---
@app.route("/api/utils/uuid")
@login_required
def api_utils_uuid():
    count = request.args.get("count", 1, type=int)
    version = request.args.get("version", "4")
    count = max(1, min(50, count))
    import uuid as _uuid
    uuids = []
    for _ in range(count):
        if version == "1":
            uuids.append(str(_uuid.uuid1()))
        elif version == "7":
            uuids.append(str(_uuid.uuid7())) if hasattr(_uuid, 'uuid7') else uuids.append(str(_uuid.uuid4()))
        else:
            uuids.append(str(_uuid.uuid4()))
    return jsonify({"ok": True, "uuids": uuids})


# --- 时间戳转换 ---
@app.route("/api/utils/timestamp")
@login_required
def api_utils_timestamp():
    ts = request.args.get("ts", "").strip()
    import time
    now = int(time.time())
    if not ts:
        return jsonify({"ok": True, "now": now, "now_readable": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    try:
        val = int(ts)
        # 13-digit → ms, 10-digit → s
        if val > 1e12:
            val = val // 1000
        dt = datetime.fromtimestamp(val)
        return jsonify({"ok": True, "ts": val, "readable": dt.strftime("%Y-%m-%d %H:%M:%S"), "iso": dt.isoformat()})
    except (ValueError, OSError):
        # Try parsing human-readable
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"]:
            try:
                dt = datetime.strptime(ts, fmt)
                ts_val = int(dt.timestamp())
                return jsonify({"ok": True, "ts": ts_val, "readable": dt.strftime("%Y-%m-%d %H:%M:%S")})
            except ValueError:
                continue
        return jsonify({"ok": False, "error": "无法解析时间"})


# --- 字数统计 ---
@app.route("/api/utils/count", methods=["POST"])
@login_required
def api_utils_count():
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    chars = len(text)
    chars_no_space = len(text.replace(" ", "").replace("\n", "").replace("\t", ""))
    words = len(text.split()) if text.strip() else 0
    lines = text.count("\n") + (1 if text else 0)
    bytes_utf8 = len(text.encode("utf-8"))
    cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf')
    return jsonify({"ok": True, "chars": chars, "chars_no_space": chars_no_space,
                    "words": words, "lines": lines, "bytes": bytes_utf8, "cn_chars": cn_chars})


# ========== 📚 学习工具 ==========
@app.route("/study")
@login_required
def study_page():
    """
    学习工具页面（URL: /study）。

    权限：需要登录
    功能：待办清单 + 抽认卡（间隔重复复习）。
    """
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
    """
    为 Vue 插件创建沙箱 wrapper HTML 文件。

    通过 CDN 引入 Vue 3 运行时，加载 .vue 文件后解析 template/script/style，
    在沙箱模式下渲染。

    Args:
        plugin_dir: 插件目录路径
        plugin_name: 插件名称（用于标题）
        version: Vue 版本（仅用于兼容，默认 "3"）
    """
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
def api_admin_plugin_marketplace_list():
    """获取插件市场列表（含管理标记：作者或管理员可编辑/删除）"""
    username = session.get("username", "")
    is_admin = (session.get("permission") == "administrator")
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
                    "can_manage": is_admin or (r["uploader"] == username),
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
def api_admin_plugin_marketplace_delete(plugin_id):
    """删除插件市场中的插件（数据库 + 文件）—— 作者或管理员"""
    conn = get_db()
    username = session.get("username", "")
    is_admin = (session.get("permission") == "administrator")
    plugin_name = None
    if conn:
        try:
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            cursor.execute(
                "SELECT plugin_name, uploader FROM plugin_marketplace WHERE id=%s", (plugin_id,)
            )
            row = cursor.fetchone()
            if row:
                # 权限检查：管理员 或 插件作者
                if not is_admin and row["uploader"] != username:
                    cursor.close()
                    conn.close()
                    return jsonify({"ok": False, "error": "无权删除此插件"}), 403
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


# ---------- 插件市场编辑（作者/管理员） ----------
@app.route("/api/admin/plugins/marketplace/<int:plugin_id>", methods=["PUT"])
@login_required
def api_admin_plugin_marketplace_update(plugin_id):
    """修改插件信息或替换文件 — 作者或管理员"""
    username = session.get("username", "")
    is_admin = (session.get("permission") == "administrator")

    conn = get_db()
    if not conn:
        return jsonify({"ok": False, "error": "数据库不可用"}), 500

    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute(
            "SELECT * FROM plugin_marketplace WHERE id=%s", (plugin_id,)
        )
        row = cursor.fetchone()
        if not row:
            cursor.close()
            conn.close()
            return jsonify({"ok": False, "error": "未找到该插件"}), 404

        # 权限检查
        if not is_admin and row["uploader"] != username:
            cursor.close()
            conn.close()
            return jsonify({"ok": False, "error": "无权修改此插件"}), 403

        plugin_name = row["plugin_name"]
        plugin_dir = os.path.join(MARKETPLACE_DIR, plugin_name)

        # 1. 更新元信息（manifest + DB）
        display_name = (request.form.get("display_name") or row["display_name"]).strip()
        description = (request.form.get("description") or row.get("description", "")).strip()
        version = (request.form.get("version") or row["version"]).strip()
        author = (request.form.get("author") or row.get("author", "")).strip()
        icon = (request.form.get("icon") or row.get("icon", "🧩")).strip()

        # 更新 manifest
        manifest_path = os.path.join(plugin_dir, "plugin.json")
        manifest = {}
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
            except Exception:
                pass
        manifest["display_name"] = display_name
        manifest["description"] = description
        manifest["version"] = version
        manifest["author"] = author
        manifest["icon"] = icon
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        # 更新数据库
        cursor.execute("""
            UPDATE plugin_marketplace
            SET display_name=%s, description=%s, version=%s, author=%s, icon=%s, updated_at=CURRENT_TIMESTAMP
            WHERE id=%s
        """, (display_name, description, version, author, icon, plugin_id))
        conn.commit()

        # 2. 可选：替换文件
        file_replaced = False
        file = request.files.get("file")
        if file and file.filename:
            filename = file.filename
            ext = os.path.splitext(filename)[1].lower()
            if ext not in (".html", ".vue"):
                cursor.close()
                conn.close()
                return jsonify({"ok": False, "error": "仅支持 .html 或 .vue 文件"}), 400

            file.seek(0, 2)
            size = file.tell()
            file.seek(0)
            if size > 5 * 1024 * 1024:
                cursor.close()
                conn.close()
                return jsonify({"ok": False, "error": "文件不能超过 5MB"}), 400

            content = file.read()
            try:
                content_str = content.decode("utf-8")
            except UnicodeDecodeError:
                cursor.close()
                conn.close()
                return jsonify({"ok": False, "error": "文件编码必须是 UTF-8"}), 400

            # 安全扫描
            for pattern in ("{{", "}}", "{%", "%}"):
                if pattern in content_str:
                    cursor.close()
                    conn.close()
                    return jsonify({"ok": False, "error": f"文件包含不安全的模板语法: {pattern}"}), 400

            dest_path = os.path.join(plugin_dir, "index" + ext)
            with open(dest_path, "wb") as f:
                f.write(content)

            # 文件类型变了？更新 DB
            new_file_type = "html" if ext == ".html" else "vue"
            if new_file_type != row["file_type"]:
                cursor.execute(
                    "UPDATE plugin_marketplace SET file_type=%s WHERE id=%s",
                    (new_file_type, plugin_id)
                )
                conn.commit()

            # Vue 文件需要重建 wrapper
            if new_file_type == "vue":
                _create_vue_wrapper(plugin_dir, plugin_name, version)

            file_replaced = True

        cursor.close()
        conn.close()

        log_msg = f"插件: {display_name}"
        if file_replaced:
            log_msg += " (已替换文件)"
        write_log("插件市场编辑", f"{log_msg}, 操作者: {username}")

        return jsonify({
            "ok": True,
            "message": "插件已更新" + ("（含文件）" if file_replaced else ""),
            "plugin": {
                "id": plugin_id,
                "name": plugin_name,
                "display_name": display_name,
                "description": description,
                "version": version,
                "author": author,
                "icon": icon,
                "file_replaced": file_replaced,
            }
        })

    except Exception as e:
        return jsonify({"ok": False, "error": f"更新失败: {str(e)}"}), 500


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
    """公开 API：获取插件市场列表（作者和管理员可编辑/删除自己的插件）"""
    username = session.get("username", "")
    is_admin = (session.get("permission") == "administrator")
    result = []
    conn = get_db()
    if conn:
        try:
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            cursor.execute(
                "SELECT id, plugin_name, display_name, description, version, "
                "author, file_type, icon, uploader, created_at "
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
                    "uploader": r["uploader"],
                    "created_at": r["created_at"].strftime("%Y-%m-%d %H:%M") if r.get("created_at") else "",
                    "preview_url": f"/plugin-market/{r['id']}",
                    "can_manage": is_admin or (r["uploader"] == username),
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
    """
    启动时自动加载所有已发现的插件。

    遍历 plugins 目录下的所有插件 manifest，依次调用 load_plugin。
    单个插件加载失败不阻塞整体启动。
    """
    discovered = plugins.discover_plugins()
    for p in discovered:
        try:
            plugins.load_plugin(p["name"])
        except Exception:
            pass


# ---------- 启动 ----------
# ---------- 路由：安全响应中心（SRC） ----------

# 漏洞类型列表
VULN_TYPES = [
    "SQL 注入", "XSS 跨站脚本", "CSRF 跨站请求伪造", "SSRF 服务端请求伪造",
    "文件包含漏洞", "命令注入", "代码注入",
    "权限绕过", "未授权访问", "潜在信息泄露", "逻辑漏洞",
    "弱口令", "会话固定", "点击劫持", "CORS 配置错误",
    "目录遍历", "XXE 外部实体注入", "反序列化漏洞", "命令注入", "URL跳转漏洞",
    "任意文件下载漏洞", "任意文件上传漏洞", "信息泄露漏洞", "权限绕过漏洞",
    "暴力破解", "任意账号注册/登录", "拒绝服务", "CORS绕过",
    "JSONP劫持", "明文传输", "组件安全漏洞", "HTTP明文传输漏洞"
]

SEVERITY_LEVELS = ["critical", "high", "medium", "low", "info"]
SEVERITY_LABELS = {
    "critical": "🔴 严重", "high": "🟠 高危", "medium": "🟡 中危",
    "low": "🟢 低危", "info": "ℹ️ 信息"
}
STATUS_LABELS = {
    "pending": "待审核", "reviewing": "审核中", "accepted": "已接受",
    "resolved": "已修复", "closed": "已关闭", "duplicate": "重复报告"
}


@app.route("/src")
@login_required
def src_submit():
    """
    安全响应中心 - 漏洞提交页面（URL: /src）。

    权限：任何登录用户
    功能：提交漏洞报告（标题/类型/严重等级/影响URL/描述等）。
    """
    """安全响应中心 - 漏洞提交页面（任何登录用户可访问）"""
    return render_template("src_submit.html",
                           username=session["username"],
                           permission=session["permission"],
                           vuln_types=VULN_TYPES,
                           severity_levels=SEVERITY_LEVELS,
                           severity_labels=SEVERITY_LABELS)


@app.route("/src/my")
@login_required
def src_my_reports():
    """
    我的漏洞报告列表（URL: /src/my）。

    权限：任何登录用户
    功能：显示当前用户提交的所有漏洞报告及当前审核状态。
    """
    """我的漏洞报告列表"""
    return render_template("src_my.html",
                           username=session["username"],
                           permission=session["permission"],
                           status_labels=STATUS_LABELS,
                           severity_labels=SEVERITY_LABELS)


@app.route("/src/admin")
@login_required
@admin_required
def src_admin():
    """
    安全响应中心管理后台（URL: /src/admin）。

    权限：仅管理员
    功能：审核/处理漏洞报告，更新状态和添加备注。
    """
    """安全响应中心管理后台（仅管理员）"""
    return render_template("src_admin.html",
                           username=session["username"],
                           permission=session["permission"],
                           vuln_types=VULN_TYPES,
                           severity_levels=SEVERITY_LEVELS,
                           severity_labels=SEVERITY_LABELS,
                           status_labels=STATUS_LABELS)


@app.route("/src/rules")
@login_required
def src_rules():
    """
    安全响应中心 - 规则页面（URL: /src/rules）。

    权限：任何登录用户
    功能：展示漏洞报告规则、评分标准等信息。
    """
    """安全响应中心 - 规则页面（任何登录用户可访问）"""
    return render_template("src_rules.html",
                           username=session["username"],
                           permission=session["permission"])


@app.route("/api/src/submit", methods=["POST"])
@login_required
def api_src_submit():
    """
    提交漏洞报告 API（URL: /api/src/submit, POST）。

    权限：任何登录用户
    功能：校验必填字段/漏洞类型/严重等级/附件 URL 白名单，写入 src_reports 表。
    """
    """提交漏洞报告"""
    _init_db_once()
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    vuln_type = (data.get("vuln_type") or "").strip()
    severity = (data.get("severity") or "medium").strip()
    affected_url = (data.get("affected_url") or "").strip()
    description = (data.get("description") or "").strip()
    steps = (data.get("steps_to_reproduce") or "").strip()
    impact = (data.get("impact") or "").strip()
    attachment = (data.get("attachment") or "").strip()
    wechat_contact = (data.get("wechat_contact") or "").strip()

    # 校验必填字段
    if not title or not affected_url or not description:
        return jsonify({"error": "漏洞标题、受影响URL和描述为必填项"}), 400
    if vuln_type not in VULN_TYPES:
        return jsonify({"error": "无效的漏洞类型"}), 400
    if severity not in SEVERITY_LEVELS:
        return jsonify({"error": "无效的严重等级"}), 400
    if len(title) > 500:
        return jsonify({"error": "标题长度不能超过 500 字符"}), 400

    # 附件 URL 白名单校验
    if attachment:
        if not attachment.startswith(("http://", "https://", "/static/", "/uploads/")):
            return jsonify({"error": "附件链接格式无效"}), 400

    conn = get_db()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO src_reports (username, title, vuln_type, severity, affected_url,
                                     description, steps_to_reproduce, impact, attachment, wechat_contact)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (session["username"], title, vuln_type, severity, affected_url,
              description, steps, impact, attachment or None, wechat_contact or None))
        conn.commit()
        report_id = cursor.lastrowid
        cursor.close()
        conn.close()
        return jsonify({"ok": True, "id": report_id, "message": "漏洞报告已提交，感谢您的贡献！"})
    except Exception as e:
        return jsonify({"error": f"提交失败: {str(e)}"}), 500


@app.route("/api/src/reports")
@login_required
def api_src_reports():
    """
    获取漏洞报告列表（URL: /api/src/reports, GET）。

    权限：管理员可看全部，普通用户只看自己的。
    功能：支持按 status 过滤。
    """
    """获取漏洞报告列表（管理员看全部，普通用户看自己的）"""
    conn = get_db()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        is_admin = session.get("permission") == "administrator"
        status_filter = request.args.get("status", "").strip()

        if is_admin:
            if status_filter and status_filter in STATUS_LABELS:
                cursor.execute(
                    "SELECT id, username, title, vuln_type, severity, status, created_at, updated_at "
                    "FROM src_reports WHERE status=%s ORDER BY created_at DESC",
                    (status_filter,)
                )
            else:
                cursor.execute(
                    "SELECT id, username, title, vuln_type, severity, status, created_at, updated_at "
                    "FROM src_reports ORDER BY created_at DESC"
                )
        else:
            if status_filter and status_filter in STATUS_LABELS:
                cursor.execute(
                    "SELECT id, username, title, vuln_type, severity, status, created_at, updated_at "
                    "FROM src_reports WHERE username=%s AND status=%s ORDER BY created_at DESC",
                    (session["username"], status_filter)
                )
            else:
                cursor.execute(
                    "SELECT id, username, title, vuln_type, severity, status, created_at, updated_at "
                    "FROM src_reports WHERE username=%s ORDER BY created_at DESC",
                    (session["username"],)
                )

        reports = []
        for row in cursor.fetchall():
            reports.append({
                "id": row[0], "username": row[1], "title": row[2],
                "vuln_type": row[3], "severity": row[4], "status": row[5],
                "created_at": str(row[6]) if row[6] else "",
                "updated_at": str(row[7]) if row[7] else "",
            })
        cursor.close()
        conn.close()
        return jsonify({"reports": reports, "is_admin": is_admin})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/src/report/<int:report_id>")
@login_required
def api_src_report_detail(report_id):
    """获取单个漏洞报告详情"""
    conn = get_db()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        is_admin = session.get("permission") == "administrator"
        if is_admin:
            cursor.execute(
                "SELECT * FROM src_reports WHERE id=%s", (report_id,)
            )
        else:
            cursor.execute(
                "SELECT * FROM src_reports WHERE id=%s AND username=%s",
                (report_id, session["username"])
            )
        row = cursor.fetchone()
        if not row:
            cursor.close()
            conn.close()
            return jsonify({"error": "报告不存在或无权查看"}), 404

        cols = [d[0] for d in cursor.description]
        r = dict(zip(cols, row))
        # 转换 datetime
        for k in ("created_at", "updated_at"):
            if r.get(k):
                r[k] = str(r[k])
        cursor.close()
        conn.close()
        return jsonify({"report": r, "is_admin": is_admin})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/src/report/<int:report_id>/update", methods=["POST"])
@login_required
@admin_required
def api_src_report_update(report_id):
    """管理员更新报告状态/添加备注"""
    data = request.get_json(silent=True) or {}
    new_status = (data.get("status") or "").strip()
    admin_notes = (data.get("admin_notes") or "").strip()

    if new_status and new_status not in STATUS_LABELS:
        return jsonify({"error": "无效的状态值"}), 400

    conn = get_db()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        updates = []
        params = []
        if new_status:
            updates.append("status=%s")
            params.append(new_status)
        if admin_notes:
            updates.append("admin_notes=%s")
            params.append(admin_notes)
        updates.append("reviewed_by=%s")
        params.append(session["username"])
        params.append(report_id)

        sql = f"UPDATE src_reports SET {', '.join(updates)} WHERE id=%s"
        cursor.execute(sql, params)
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"ok": True, "message": "报告状态已更新"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/src/stats")
@login_required
@admin_required
def api_src_stats():
    """获取 SRC 统计数据（管理员）"""
    conn = get_db()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM src_reports")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT status, COUNT(*) FROM src_reports GROUP BY status")
        by_status = {row[0]: row[1] for row in cursor.fetchall()}
        cursor.execute("SELECT severity, COUNT(*) FROM src_reports GROUP BY severity")
        by_severity = {row[0]: row[1] for row in cursor.fetchall()}
        cursor.close()
        conn.close()
        return jsonify({
            "total": total,
            "by_status": by_status,
            "by_severity": by_severity,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------- API：管理员审核密码重置申请 ----------
@app.route("/api/admin/reset_requests")
@login_required
@admin_required
def api_admin_reset_requests():
    """获取待审核的密码重置申请列表"""
    conn = get_db()
    if not conn:
        return jsonify({"error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, username, request_reason, request_status, created_at
            FROM password_reset_tokens
            WHERE request_status IN ('pending', 'approved', 'rejected')
            ORDER BY FIELD(request_status, 'pending', 'approved', 'rejected'), created_at DESC
            LIMIT 50
        """)
        cols = [d[0] for d in cursor.description]
        rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
        cursor.close(); conn.close()
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = str(r["created_at"])
        return jsonify({"ok": True, "requests": rows})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/reset_requests/<int:req_id>/approve", methods=["POST"])
@login_required
@admin_required
def api_admin_reset_approve(req_id):
    """管理员审核通过，生成令牌"""
    conn = get_db()
    if not conn:
        return jsonify({"ok": False, "error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, request_status FROM password_reset_tokens WHERE id=%s", (req_id,)
        )
        row = cursor.fetchone()
        if not row:
            cursor.close(); conn.close()
            return jsonify({"ok": False, "error": "申请不存在"})
        if row[2] != "pending":
            cursor.close(); conn.close()
            return jsonify({"ok": False, "error": f"申请状态不是待审核"})
        token = uuid.uuid4().hex
        expires = datetime.now() + timedelta(minutes=30)
        cursor.execute(
            "UPDATE password_reset_tokens SET token=%s, request_status='approved', expires_at=%s WHERE id=%s",
            (token, expires, req_id)
        )
        conn.commit()
        username = row[1]
        cursor.close(); conn.close()
        write_log("管理员重置审核通过", f"用户名: {username}, 操作人: {session['username']}")
        return jsonify({"ok": True, "message": "已通过", "token": token, "username": username})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/admin/reset_requests/<int:req_id>/reject", methods=["POST"])
@login_required
@admin_required
def api_admin_reset_reject(req_id):
    """管理员拒绝密码重置申请"""
    conn = get_db()
    if not conn:
        return jsonify({"ok": False, "error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE password_reset_tokens SET request_status='rejected' WHERE id=%s AND request_status='pending'",
            (req_id,)
        )
        conn.commit()
        affected = cursor.rowcount
        cursor.close(); conn.close()
        if affected:
            write_log("管理员重置审核拒绝", f"申请ID: {req_id}, 操作人: {session['username']}")
            return jsonify({"ok": True, "message": "已拒绝"})
        return jsonify({"ok": False, "error": "申请不存在或已处理"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500



# ========== 新功能模块：生活实用 / 办公效率 / 娱乐资讯 / 工具增强 ==========

# ---------- 数据库初始化：生活实用模块 ----------
def _init_life_tables():
    """
    创建生活实用模块的数据库表。

    包含：记账(expenses)、习惯(habits/habit_logs)、书签(bookmarks)、
    RSS(rss_feeds)、番茄钟(pomodoro_sessions)、签到(checkins)。
    所有 CREATE TABLE IF NOT EXISTS 保证幂等。
    """
    conn = get_db()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        # 记账表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                amount DECIMAL(10,2) NOT NULL,
                category VARCHAR(20) DEFAULT '其他',
                note VARCHAR(200),
                expense_date DATE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_exp_user (username),
                INDEX idx_exp_date (expense_date)
            )
        """)
        # 习惯表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS habits (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                name VARCHAR(100) NOT NULL,
                icon VARCHAR(10) DEFAULT '✅',
                color VARCHAR(7) DEFAULT '#3b82f6',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_hab_user (username)
            )
        """)
        # 习惯日志表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS habit_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                habit_id INT NOT NULL,
                log_date DATE NOT NULL,
                completed TINYINT DEFAULT 0,
                note VARCHAR(200),
                UNIQUE KEY uk_habit_date (habit_id, log_date)
            )
        """)
        # 书签表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bookmarks (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                title VARCHAR(200) NOT NULL,
                url VARCHAR(2000) NOT NULL,
                favicon VARCHAR(2000),
                category VARCHAR(50) DEFAULT '未分类',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_bm_user (username)
            )
        """)
        # RSS 订阅表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rss_feeds (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                title VARCHAR(200) NOT NULL,
                url VARCHAR(2000) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_rss_user (username)
            )
        """)
        # 番茄钟会话表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pomodoro_sessions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                task_name VARCHAR(200) DEFAULT '未命名任务',
                duration INT NOT NULL COMMENT '实际专注秒数',
                planned_duration INT NOT NULL COMMENT '计划秒数',
                completed TINYINT DEFAULT 1 COMMENT '0=中断 1=完成',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_ps_user (username, created_at)
            )
        """)
        # 签到打卡表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS checkins (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                checkin_date DATE NOT NULL,
                mood VARCHAR(10) DEFAULT '😊',
                note VARCHAR(200) DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uk_checkin (username, checkin_date),
                INDEX idx_c_user (username)
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
    except pymysql.MySQLError as e:
        print(f"  生活实用模块数据库表初始化失败: {e}")


def _init_forum_tables():
    """
    创建论坛模块的数据库表并插入预设版块。

    包含：版块(forum_categories)、帖子(forum_posts)、回复(forum_replies)、
    点赞(forum_likes)、通知(forum_notifications)。
    预设 5 个默认版块：校友动态、活动通知、互助问答、职业发展、随便聊聊。
    重试机制：死锁（1213）时自动重试最多 2 次。
    """
    global _forum_tables_done
    if _forum_tables_done:
        return
    for attempt in range(3):
        try:
            conn = get_db()
            if not conn:
                return
            cursor = conn.cursor()
            # 版块表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS forum_categories (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(50) NOT NULL UNIQUE,
                    icon VARCHAR(5) DEFAULT '📌',
                    sort_order INT DEFAULT 0,
                    description VARCHAR(200) DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # 帖子表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS forum_posts (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    category_id INT NOT NULL,
                    username VARCHAR(50) NOT NULL,
                    title VARCHAR(200) NOT NULL,
                    content TEXT NOT NULL,
                    is_pinned TINYINT DEFAULT 0,
                    is_locked TINYINT DEFAULT 0,
                    view_count INT DEFAULT 0,
                    reply_count INT DEFAULT 0,
                    like_count INT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_fp_cat (category_id),
                    INDEX idx_fp_user (username),
                    INDEX idx_fp_created (created_at)
                )
            """)
            # 回复表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS forum_replies (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    post_id INT NOT NULL,
                    username VARCHAR(50) NOT NULL,
                    content TEXT NOT NULL,
                    like_count INT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_fr_post (post_id),
                    INDEX idx_fr_user (username)
                )
            """)
            # 点赞表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS forum_likes (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(50) NOT NULL,
                    target_type ENUM('post', 'reply') NOT NULL,
                    target_id INT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_like (username, target_type, target_id)
                )
            """)
            # 通知表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS forum_notifications (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(50) NOT NULL,
                    type VARCHAR(20) NOT NULL COMMENT 'reply or like',
                    post_id INT,
                    post_title VARCHAR(200) DEFAULT '',
                    from_user VARCHAR(50) NOT NULL,
                    content_preview VARCHAR(100) DEFAULT '',
                    is_read TINYINT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_fn_user (username, is_read),
                    INDEX idx_fn_created (created_at)
                )
            """)
            # 预设版块
            default_categories = [
                ("🎓", "校友动态", 1, "校友近况、班级新闻、母校发展"),
                ("📢", "活动通知", 2, "聚会、讲座、返校日活动发布"),
                ("❓", "互助问答", 3, "学习、工作、生活中的问题求助"),
                ("💼", "职业发展", 4, "招聘内推、行业交流、创业分享"),
                ("🎉", "随便聊聊", 5, "灌水八卦，轻松交流"),
            ]
            for icon, name, order, desc in default_categories:
                cursor.execute(
                    "INSERT IGNORE INTO forum_categories (icon, name, sort_order, description) VALUES (%s,%s,%s,%s)",
                    (icon, name, order, desc)
                )
            conn.commit()
            cursor.close()
            conn.close()
            _forum_tables_done = True
            return
        except pymysql.MySQLError as e:
            if e.args[0] == 1213 and attempt < 2:  # 死锁，重试
                time.sleep(0.5 * (attempt + 1))
                continue
            print(f"  论坛模块数据库表初始化失败: {e}")
            return


def _init_session_tables():
    """
    创建多用户在线会话追踪表。

    包含：active_sessions（活跃会话）、session_events（会话事件日志）。
    兼容旧表：尝试添加 allow_multi_login 列到 user_profiles。
    """
    conn = get_db()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS active_sessions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_key VARCHAR(64) NOT NULL UNIQUE COMMENT 'Flask session 唯一标识',
                username VARCHAR(50) NOT NULL,
                ip_address VARCHAR(45) NOT NULL,
                user_agent VARCHAR(500) DEFAULT '',
                login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                is_active TINYINT DEFAULT 1,
                INDEX idx_username (username),
                INDEX idx_last_activity (last_activity),
                INDEX idx_is_active (is_active)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_events (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_key VARCHAR(64) NOT NULL,
                username VARCHAR(50) NOT NULL,
                event_type VARCHAR(20) NOT NULL COMMENT 'login, heartbeat, logout, timeout, kicked',
                ip_address VARCHAR(45),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_session (session_key),
                INDEX idx_username (username),
                INDEX idx_created (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        # 兼容旧表：添加 allow_multi_login 列
        try:
            cursor.execute("ALTER TABLE user_profiles ADD COLUMN allow_multi_login TINYINT DEFAULT 1")
            conn.commit()
        except Exception:
            pass
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"  会话表初始化失败: {e}")


def _init_confession_tables():
    """
    创建匿名树洞模块的数据库表。

    包含：anonymous_posts（匿名帖子）、anonymous_replies（回复）、
    anonymous_likes（点赞）。支持死锁重试。
    兼容旧表：尝试添加 username 列。
    """
    global _confession_tables_done
    if _confession_tables_done:
        return
    for attempt in range(3):
        try:
            conn = get_db()
            if not conn:
                return
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS anonymous_posts (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(50) NOT NULL DEFAULT '',
                    nickname VARCHAR(20) NOT NULL,
                    content TEXT NOT NULL,
                    emoji VARCHAR(5) DEFAULT '💬',
                    like_count INT DEFAULT 0,
                    reply_count INT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_ap_created (created_at)
                )
            """)
            # 确保 username 列存在（兼容旧表）
            try:
                cursor.execute("ALTER TABLE anonymous_posts ADD COLUMN username VARCHAR(50) NOT NULL DEFAULT ''")
                conn.commit()
            except Exception:
                pass  # 列已存在
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS anonymous_replies (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    post_id INT NOT NULL,
                    nickname VARCHAR(20) NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_ar_post (post_id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS anonymous_likes (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    post_id INT NOT NULL,
                    username VARCHAR(50) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_alike (post_id, username)
                )
            """)
            conn.commit()
            cursor.close()
            conn.close()
            _confession_tables_done = True
            return
        except pymysql.MySQLError as e:
            if e.args[0] == 1213 and attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            print(f"  树洞模块数据库表初始化失败: {e}")
            return


def _init_alumni_stories_tables():
    """
    创建校友故事/回忆录模块的数据库表。

    包含：alumni_stories（故事）、alumni_story_comments（评论）、
    alumni_story_likes（点赞）。支持死锁重试。
    状态流转：pending -> approved/rejected。
    """
    global _alumni_stories_tables_done
    if _alumni_stories_tables_done:
        return
    for attempt in range(3):
        try:
            conn = get_db()
            if not conn:
                return
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alumni_stories (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    username VARCHAR(50) NOT NULL,
                    title VARCHAR(200) NOT NULL,
                    content TEXT NOT NULL,
                    cover_image VARCHAR(500) DEFAULT '',
                    status ENUM('pending','approved','rejected') DEFAULT 'pending',
                    reviewer VARCHAR(50) DEFAULT NULL,
                    review_note VARCHAR(200) DEFAULT '',
                    view_count INT DEFAULT 0,
                    like_count INT DEFAULT 0,
                    comment_count INT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    reviewed_at TIMESTAMP NULL,
                    INDEX idx_as_status (status, created_at),
                    INDEX idx_as_user (username)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alumni_story_comments (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    story_id INT NOT NULL,
                    username VARCHAR(50) NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_asc_story (story_id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alumni_story_likes (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    story_id INT NOT NULL,
                    username VARCHAR(50) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY uk_asl (story_id, username)
                )
            """)
            conn.commit()
            cursor.close()
            conn.close()
            _alumni_stories_tables_done = True
            return
        except pymysql.MySQLError as e:
            if e.args[0] == 1213 and attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            print(f"  校友故事数据库表初始化失败: {e}")
            return


def _init_pet_tables():
    """
    创建虚拟宠物模块的所有数据库表。

    包含：pets（宠物属性）、pet_logs（行为日志）、pet_achievements（成就）、
    pet_inventory（物品库存）、pet_visits（串门记录）、
    pet_gifts（赠礼记录）、pet_diary（宠物日记）。
    宠物 2.0 字段（性格/进化/硬币/装扮等）通过 _ensure_column 增量添加。
    """
    conn = get_db()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pets (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL UNIQUE,
                pet_name VARCHAR(30) DEFAULT '小可爱',
                pet_type VARCHAR(20) DEFAULT 'cat',
                hunger INT DEFAULT 100,
                happiness INT DEFAULT 100,
                energy INT DEFAULT 100,
                level INT DEFAULT 1,
                xp INT DEFAULT 0,
                hatched TINYINT DEFAULT 0,
                last_fed TIMESTAMP NULL,
                last_played TIMESTAMP NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
        """)
        # 新增字段（宠物2.0）
        _ensure_column(cursor, "pets", "personality", "VARCHAR(20) DEFAULT NULL")
        _ensure_column(cursor, "pets", "evolution_stage", "INT DEFAULT 0")
        _ensure_column(cursor, "pets", "coins", "INT DEFAULT 0")
        _ensure_column(cursor, "pets", "mood", "VARCHAR(50) DEFAULT '开心'")
        _ensure_column(cursor, "pets", "accessories", "TEXT")
        _ensure_column(cursor, "pets", "visit_count", "INT DEFAULT 0")
        _ensure_column(cursor, "pets", "action_count", "INT DEFAULT 0")
        _ensure_column(cursor, "pets", "feed_count", "INT DEFAULT 0")
        _ensure_column(cursor, "pets", "play_count", "INT DEFAULT 0")
        _ensure_column(cursor, "pets", "sleep_count", "INT DEFAULT 0")
        _ensure_column(cursor, "pets", "last_slept", "TIMESTAMP NULL")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pet_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                action VARCHAR(20) NOT NULL,
                detail VARCHAR(100) DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_pl_user (username, created_at)
            )
        """)
        # 新表：成就
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pet_achievements (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                achievement_key VARCHAR(50) NOT NULL,
                unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_pa (username, achievement_key),
                INDEX idx_pa_user (username)
            )
        """)
        # 新表：装扮/物品库存
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pet_inventory (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                item_type VARCHAR(20) NOT NULL DEFAULT 'accessory',
                item_key VARCHAR(50) NOT NULL,
                quantity INT DEFAULT 1,
                INDEX idx_pi_user (username)
            )
        """)
        # 新表：串门记录
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pet_visits (
                id INT AUTO_INCREMENT PRIMARY KEY,
                visitor VARCHAR(50) NOT NULL,
                host VARCHAR(50) NOT NULL,
                message VARCHAR(200) DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_pv_host (host),
                INDEX idx_pv_visitor (visitor)
            )
        """)
        # 新表：赠礼记录
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pet_gifts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                sender VARCHAR(50) NOT NULL,
                receiver VARCHAR(50) NOT NULL,
                item_key VARCHAR(50) NOT NULL,
                message VARCHAR(200) DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_pg_receiver (receiver),
                INDEX idx_pg_sender (sender)
            )
        """)
        # 新表：宠物日记
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pet_diary (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                event_type VARCHAR(30) NOT NULL,
                detail VARCHAR(200) DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_pd_user (username, created_at)
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
    except pymysql.MySQLError as e:
        print(f"  宠物表初始化失败: {e}")


def _ensure_column(cursor, table, column, definition):
    """
    安全添加数据库列：如果列不存在则 ALTER TABLE ADD COLUMN。

    不存在的列执行 ALTER TABLE，已存在的列静默忽略。
    用于渐进式 schema 迁移，兼容新旧版本的代码。

    Args:
        cursor: 数据库游标
        table: 表名
        column: 列名
        definition: SQL 列定义（如 "VARCHAR(20) DEFAULT NULL"）
    """
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    except pymysql.MySQLError:
        pass  # 列已存在，忽略


# ---------- 天气 ----------
# 和风天气 API 配置
QWEATHER_KEY = "0983383148ea4af799eb535dd1a03ca9"
QWEATHER_HOST = "https://n478m2kuuf.re.qweatherapi.com"

# 常用城市 -> Location ID 映射表（无需联网查询）
QWEATHER_CITY_MAP = {
    "北京": "101010100", "朝阳": "101010300", "海淀": "101010200", "丰台": "101010900",
    "上海": "101020100", "浦东": "101020600", "闵行": "101020200",
    "广州": "101280101", "深圳": "101280601",
    "重庆": "101040100", "万州": "101041300", "永川": "101040200", "合川": "101040300",
    "成都": "101270101", "绵阳": "101270401",
    "杭州": "101210101", "宁波": "101210401", "温州": "101210701",
    "南京": "101190101", "苏州": "101190401", "无锡": "101190201",
    "武汉": "101200101", "宜昌": "101200901",
    "西安": "101110101", "咸阳": "101110200",
    "长沙": "101250101", "株洲": "101250301",
    "天津": "101030100", "滨海": "101031100",
    "郑州": "101180101", "洛阳": "101180901",
    "济南": "101120101", "青岛": "101120201",
    "合肥": "101220101", "芜湖": "101220301",
    "福州": "101230101", "厦门": "101230201",
    "沈阳": "101070101", "大连": "101070201",
    "哈尔滨": "101050101", "齐齐哈尔": "101050201",
    "长春": "101060101", "吉林": "101060201",
    "石家庄": "101090101", "唐山": "101090501",
    "太原": "101100101", "大同": "101100201",
    "兰州": "101160101", "天水": "101160901",
    "昆明": "101290101", "大理": "101290201",
    "贵阳": "101260101", "遵义": "101260201",
    "南宁": "101300101", "桂林": "101300501",
    "海口": "101310101", "三亚": "101310201",
    "拉萨": "101140101", "日喀则": "101140201",
    "乌鲁木齐": "101130101", "克拉玛依": "101130201",
    "西宁": "101150101", "银川": "101170101",
    "呼和浩特": "101080101", "包头": "101080201",
    "南昌": "101240101", "九江": "101240201",
    "澳门": "101330101", "香港": "101320101",
    "台北": "101340101", "高雄": "101340201",
}

@app.route("/weather")
def weather_page():
    """
    天气预报页面（URL: /weather）。

    权限：任意用户
    功能：调用和风天气 API 显示实时天气和 3 天预报。
    """
    _init_life_tables()
    return render_template("weather.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

def _qweather_get(endpoint, params):
    """
    封装和风天气 API 请求。

    自动附加 QWEATHER_KEY，超时 8 秒，返回 code=200 时返回 data，否则返回 None。
    """
    params["key"] = QWEATHER_KEY
    try:
        resp = requests.get(f"{QWEATHER_HOST}{endpoint}", params=params, timeout=8)
        data = resp.json()
        if data.get("code") == "200":
            return data
        return None
    except Exception:
        return None

def _qweather_lookup(city_name):
    """
    城市搜索：先查本地映射表 QWEATHER_CITY_MAP，失败则调用和风城市搜索 API。

    Returns:
        tuple (location_id, city_name, adm2) 或 (None, original_name, "")
    """
    # 1. 先从本地映射表查找
    stripped = city_name.strip()
    if stripped in QWEATHER_CITY_MAP:
        return QWEATHER_CITY_MAP[stripped], stripped, ""

    # 2. 尝试 API 城市搜索
    data = _qweather_get("/v2/city/lookup", {"location": stripped})
    if data and data.get("location"):
        loc = data["location"][0]
        return loc["id"], loc["name"], loc.get("adm2", "")
    return None, stripped, ""

@app.route("/api/weather")
def api_weather():
    """和风天气 API 获取天气"""
    city = request.args.get("city", "重庆")
    try:
        # 1. 城市搜索
        loc_id, city_name, adm2 = _qweather_lookup(city)
        if not loc_id:
            return jsonify({"error": f"未找到城市「{city}」"}), 404

        # 2. 获取实时天气 + 3天预报
        now_data = _qweather_get("/v7/weather/now", {"location": loc_id})
        forecast_data = _qweather_get("/v7/weather/3d", {"location": loc_id})

        if not now_data or not now_data.get("now"):
            return jsonify({"error": "天气数据获取失败"}), 500

        now = now_data["now"]

        # 3. 组装前端期望的格式
        result = {
            "city": adm2 if adm2 else city_name,
            "current": {
                "temp": now.get("temp", "--"),
                "condition": now.get("text", ""),
                "humidity": now.get("humidity", "--"),
                "wind": now.get("windSpeed", "--"),
                "feelsLike": now.get("feelsLike", now.get("temp", "--")),
                "icon": now.get("icon", "100"),
                "windDir": now.get("windDir", ""),
                "windScale": now.get("windScale", ""),
                "vis": now.get("vis", ""),
                "pressure": now.get("pressure", ""),
                "precip": now.get("precip", "0.0"),
            },
            "forecast": [],
        }

        if forecast_data and forecast_data.get("daily"):
            for day in forecast_data["daily"]:
                result["forecast"].append({
                    "date": day.get("fxDate", ""),
                    "condition": day.get("textDay", ""),
                    "high": day.get("tempMax", "--"),
                    "low": day.get("tempMin", "--"),
                    "iconDay": day.get("iconDay", ""),
                    "iconNight": day.get("iconNight", ""),
                    "sunrise": day.get("sunrise", ""),
                    "sunset": day.get("sunset", ""),
                    "moonPhase": day.get("moonPhase", ""),
                })

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": f"天气数据获取失败: {str(e)}"}), 500

# ---------- 记账 ----------
@app.route("/expenses")
@login_required
def expenses_page():
    _init_life_tables()
    return render_template("expenses.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

@app.route("/api/expenses", methods=["GET", "POST"])
@login_required
def api_expenses():
    username = session["username"]
    conn = get_db()
    if request.method == "GET":
        month = request.args.get("month", datetime.date.today().strftime("%Y-%m"))
        cursor = conn.cursor()
        cursor.execute("SELECT id, amount, category, note, expense_date FROM expenses WHERE username=%s AND DATE_FORMAT(expense_date, '%%Y-%%m')=%s ORDER BY expense_date DESC, id DESC", (username, month))
        rows = cursor.fetchall()
        cursor.close(); conn.close()
        return jsonify({"expenses": [{"id": r[0], "amount": float(r[1]), "category": r[2], "note": r[3], "date": str(r[4])} for r in rows]})
    else:
        data = request.get_json() or {}
        amount = data.get("amount")
        category = data.get("category", "其他")
        note = data.get("note", "")
        date = data.get("date", datetime.date.today().isoformat())
        if not amount:
            return jsonify({"ok": False, "error": "金额不能为空"}), 400
        cursor = conn.cursor()
        cursor.execute("INSERT INTO expenses (username, amount, category, note, expense_date) VALUES (%s,%s,%s,%s,%s)", (username, amount, category, note, date))
        conn.commit(); cursor.close(); conn.close()
        return jsonify({"ok": True})

@app.route("/api/expenses/<int:eid>", methods=["PUT", "DELETE"])
@login_required
def api_expense_item(eid):
    username = session["username"]
    conn = get_db()
    if request.method == "DELETE":
        cursor = conn.cursor()
        cursor.execute("DELETE FROM expenses WHERE id=%s AND username=%s", (eid, username))
        conn.commit(); cursor.close(); conn.close()
        return jsonify({"ok": True})
    else:
        data = request.get_json() or {}
        cursor = conn.cursor()
        cursor.execute("UPDATE expenses SET amount=%s, category=%s, note=%s, expense_date=%s WHERE id=%s AND username=%s", (data.get("amount"), data.get("category"), data.get("note"), data.get("date"), eid, username))
        conn.commit(); cursor.close(); conn.close()
        return jsonify({"ok": True})

@app.route("/api/expenses/stats")
@login_required
def api_expenses_stats():
    username = session["username"]
    month = request.args.get("month", datetime.date.today().strftime("%Y-%m"))
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT category, SUM(amount) as total FROM expenses WHERE username=%s AND DATE_FORMAT(expense_date, '%%Y-%%m')=%s GROUP BY category", (username, month))
    rows = cursor.fetchall()
    cursor.close(); conn.close()
    return jsonify({"stats": [{"category": r[0], "total": float(r[1])} for r in rows]})

# ---------- 习惯追踪 ----------
@app.route("/habits")
@login_required
def habits_page():
    _init_life_tables()
    return render_template("habits.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

@app.route("/api/habits", methods=["GET", "POST"])
@login_required
def api_habits():
    username = session["username"]
    conn = get_db()
    if request.method == "GET":
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, icon, color FROM habits WHERE username=%s ORDER BY id", (username,))
        rows = cursor.fetchall()
        habits = []
        for r in rows:
            cursor.execute("SELECT log_date, completed FROM habit_logs WHERE habit_id=%s AND log_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) ORDER BY log_date", (r[0],))
            logs = [{"date": str(l[0]), "completed": bool(l[1])} for l in cursor.fetchall()]
            habits.append({"id": r[0], "name": r[1], "icon": r[2], "color": r[3], "logs": logs})
        cursor.close(); conn.close()
        return jsonify({"habits": habits})
    else:
        data = request.get_json() or {}
        name = data.get("name", "").strip()
        if not name:
            return jsonify({"ok": False, "error": "名称不能为空"}), 400
        icon = data.get("icon", "✅")
        color = data.get("color", "#3b82f6")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO habits (username, name, icon, color) VALUES (%s,%s,%s,%s)", (username, name, icon, color))
        conn.commit()
        hid = cursor.lastrowid
        cursor.close(); conn.close()
        return jsonify({"ok": True, "id": hid})

@app.route("/api/habits/<int:hid>", methods=["PUT", "DELETE"])
@login_required
def api_habit_item(hid):
    username = session["username"]
    conn = get_db()
    if request.method == "DELETE":
        cursor = conn.cursor()
        cursor.execute("DELETE FROM habit_logs WHERE habit_id=%s", (hid,))
        cursor.execute("DELETE FROM habits WHERE id=%s AND username=%s", (hid, username))
        conn.commit(); cursor.close(); conn.close()
        return jsonify({"ok": True})
    else:
        data = request.get_json() or {}
        cursor = conn.cursor()
        cursor.execute("UPDATE habits SET name=%s, icon=%s, color=%s WHERE id=%s AND username=%s", (data.get("name"), data.get("icon"), data.get("color"), hid, username))
        conn.commit(); cursor.close(); conn.close()
        return jsonify({"ok": True})

@app.route("/api/habit_logs", methods=["POST"])
@login_required
def api_habit_logs():
    data = request.get_json() or {}
    habit_id = data.get("habit_id")
    date = data.get("date", datetime.date.today().isoformat())
    completed = data.get("completed", True)
    if not habit_id:
        return jsonify({"ok": False, "error": "缺少 habit_id"}), 400
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO habit_logs (habit_id, log_date, completed) VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE completed=VALUES(completed)", (habit_id, date, 1 if completed else 0))
    conn.commit(); cursor.close(); conn.close()
    return jsonify({"ok": True})

# ---------- 番茄钟 ----------
@app.route("/pomodoro")
def pomodoro_page():
    _init_life_tables()
    return render_template("pomodoro_enhanced.html", username=session.get("username", ""), permission=session.get("permission", "guest"))


# ========== 番茄钟 API ==========

@app.route("/api/pomodoro/sessions", methods=["GET", "POST"])
@login_required
def api_pomodoro_sessions():
    username = session["username"]
    conn = get_db()
    if request.method == "GET":
        period = request.args.get("period", "today")
        cursor = conn.cursor()
        if period == "today":
            cursor.execute(
                "SELECT id, task_name, duration, planned_duration, completed, created_at FROM pomodoro_sessions WHERE username=%s AND DATE(created_at)=CURDATE() ORDER BY created_at DESC",
                (username,)
            )
        elif period == "week":
            cursor.execute(
                "SELECT id, task_name, duration, planned_duration, completed, created_at FROM pomodoro_sessions WHERE username=%s AND created_at >= DATE_SUB(CURDATE(), INTERVAL 7 DAY) ORDER BY created_at DESC",
                (username,)
            )
        else:
            cursor.execute(
                "SELECT id, task_name, duration, planned_duration, completed, created_at FROM pomodoro_sessions WHERE username=%s ORDER BY created_at DESC LIMIT 100",
                (username,)
            )
        rows = cursor.fetchall()
        cursor.close(); conn.close()
        sessions = []
        for r in rows:
            sessions.append({
                "id": r[0], "task_name": r[1], "duration": r[2],
                "planned_duration": r[3], "completed": bool(r[4]),
                "created_at": str(r[5])
            })
        return jsonify({"sessions": sessions})
    else:
        data = request.get_json() or {}
        task_name = sanitize_input(data.get("task_name", "未命名任务"), 200)
        duration = data.get("duration", 0)
        planned_duration = data.get("planned_duration", duration)
        completed = 1 if data.get("completed", True) else 0
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO pomodoro_sessions (username, task_name, duration, planned_duration, completed) VALUES (%s,%s,%s,%s,%s)",
            (username, task_name, duration, planned_duration, completed)
        )
        conn.commit(); cursor.close(); conn.close()
        return jsonify({"ok": True, "id": cursor.lastrowid})


@app.route("/api/pomodoro/stats")
@login_required
def api_pomodoro_stats():
    username = session["username"]
    conn = get_db()
    cursor = conn.cursor()
    # Today stats
    cursor.execute(
        "SELECT COUNT(*), COALESCE(SUM(duration), 0) FROM pomodoro_sessions WHERE username=%s AND DATE(created_at)=CURDATE() AND completed=1",
        (username,)
    )
    today_row = cursor.fetchone()
    today_count = today_row[0] if today_row else 0
    today_minutes = round((today_row[1] if today_row else 0) / 60, 1)

    # Week data for chart (last 7 days)
    cursor.execute(
        "SELECT DATE(created_at) as d, COUNT(*) as cnt, COALESCE(SUM(duration), 0) as secs FROM pomodoro_sessions WHERE username=%s AND created_at >= DATE_SUB(CURDATE(), INTERVAL 6 DAY) AND completed=1 GROUP BY DATE(created_at) ORDER BY d",
        (username,)
    )
    week_rows = cursor.fetchall()
    week_map = {}
    for r in week_rows:
        week_map[str(r[0])] = {"count": r[1], "minutes": round(r[2] / 60, 1)}

    from datetime import date, timedelta
    today_date = date.today()
    week_data = []
    for i in range(6, -1, -1):
        d = (today_date - timedelta(days=i)).isoformat()
        if d in week_map:
            week_data.append({"date": d, "count": week_map[d]["count"], "minutes": week_map[d]["minutes"]})
        else:
            week_data.append({"date": d, "count": 0, "minutes": 0})

    # Streak: consecutive days with at least 1 completed session
    streak = 0
    cursor.execute(
        "SELECT DISTINCT DATE(created_at) as d FROM pomodoro_sessions WHERE username=%s AND completed=1 ORDER BY d DESC",
        (username,)
    )
    streak_rows = cursor.fetchall()
    check_date = today_date
    streak_set = set(str(r[0]) for r in streak_rows) if streak_rows else set()
    if today_date.isoformat() not in streak_set:
        check_date = today_date - timedelta(days=1)
    while check_date.isoformat() in streak_set:
        streak += 1
        check_date -= timedelta(days=1)

    cursor.close(); conn.close()
    return jsonify({
        "today_count": today_count,
        "today_minutes": today_minutes,
        "week_data": week_data,
        "streak": streak
    })


@app.route("/api/pomodoro/leaderboard")
@login_required
def api_pomodoro_leaderboard():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT username, COUNT(*) as cnt, COALESCE(SUM(duration), 0) as secs FROM pomodoro_sessions WHERE completed=1 AND created_at >= DATE_SUB(CURDATE(), INTERVAL 7 DAY) GROUP BY username ORDER BY secs DESC LIMIT 5"
    )
    rows = cursor.fetchall()
    cursor.close(); conn.close()
    leaderboard = []
    for r in rows:
        leaderboard.append({
            "username": r[0],
            "count": r[1],
            "minutes": round(r[2] / 60, 1)
        })
    return jsonify({"leaderboard": leaderboard})


# ---------- 签到打卡 ----------
@app.route("/checkin")
@login_required
def checkin_page():
    _init_life_tables()
    return render_template("checkin.html", username=session.get("username", ""), permission=session.get("permission", "guest"))


@app.route("/api/checkin/status")
@login_required
def api_checkin_status():
    """获取今日签到状态 + 年度签到日期"""
    username = session["username"]
    year = request.args.get("year", type=int) or datetime.utcnow().year
    conn = get_db()
    cursor = conn.cursor()
    # 今日是否已签到
    today = datetime.utcnow().strftime("%Y-%m-%d")
    cursor.execute("SELECT mood, note FROM checkins WHERE username=%s AND checkin_date=%s", (username, today))
    today_row = cursor.fetchone()
    # 年度所有签到日期
    cursor.execute(
        "SELECT checkin_date, mood FROM checkins WHERE username=%s AND YEAR(checkin_date)=%s ORDER BY checkin_date",
        (username, year)
    )
    rows = cursor.fetchall()
    cursor.close(); conn.close()

    dates = [{"date": str(r[0]), "mood": r[1]} for r in rows]
    checked_today = today_row is not None
    today_mood = today_row[0] if today_row else None
    today_note = today_row[1] if today_row else None

    # 计算连续签到天数
    streak = 0
    if checked_today:
        streak = 1
        check_date = datetime.utcnow() - timedelta(days=1)
        date_set = {r[0] for r in rows}
        while check_date.strftime("%Y-%m-%d") in date_set:
            streak += 1
            check_date -= timedelta(days=1)

    return jsonify({
        "checked_today": checked_today,
        "today_mood": today_mood,
        "today_note": today_note,
        "streak": streak,
        "dates": dates,
        "total": len(rows)
    })


@app.route("/api/checkin", methods=["POST"])
@login_required
def api_checkin():
    """执行签到"""
    username = session["username"]
    data = request.get_json() or {}
    mood = data.get("mood", "😊")
    note = sanitize_input(data.get("note", ""), 200)
    today = datetime.utcnow().strftime("%Y-%m-%d")

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO checkins (username, checkin_date, mood, note) VALUES (%s, %s, %s, %s)",
            (username, today, mood, note)
        )
        conn.commit()
    except pymysql.IntegrityError:
        return jsonify({"error": "今日已签到"}), 409
    finally:
        cursor.close(); conn.close()

    # 计算连续签到天数
    conn2 = get_db()
    cur2 = conn2.cursor()
    cur2.execute("SELECT checkin_date FROM checkins WHERE username=%s ORDER BY checkin_date", (username,))
    rows = cur2.fetchall()
    cur2.close(); conn2.close()

    date_set = {r[0] for r in rows}
    streak = 1
    check_date = datetime.utcnow() - timedelta(days=1)
    while check_date.strftime("%Y-%m-%d") in date_set:
        streak += 1
        check_date -= timedelta(days=1)

    return jsonify({
        "ok": True,
        "streak": streak,
        "date": today,
        "mood": mood
    })


# ---------- 书签管理 ----------
@app.route("/bookmarks")
@login_required
def bookmarks_page():
    _init_life_tables()
    return render_template("bookmarks.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

@app.route("/api/bookmarks", methods=["GET", "POST"])
@login_required
def api_bookmarks():
    username = session["username"]
    conn = get_db()
    if request.method == "GET":
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, url, favicon, category FROM bookmarks WHERE username=%s ORDER BY category, id", (username,))
        rows = cursor.fetchall()
        cursor.close(); conn.close()
        return jsonify({"bookmarks": [{"id": r[0], "title": r[1], "url": r[2], "favicon": r[3], "category": r[4]} for r in rows]})
    else:
        data = request.get_json() or {}
        title = data.get("title", "").strip()
        url = data.get("url", "").strip()
        if not title or not url:
            return jsonify({"ok": False, "error": "标题和URL不能为空"}), 400
        if not url.startswith("http"):
            url = "https://" + url
        category = data.get("category", "未分类")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO bookmarks (username, title, url, category) VALUES (%s,%s,%s,%s)", (username, title, url, category))
        conn.commit()
        bid = cursor.lastrowid
        cursor.close(); conn.close()
        return jsonify({"ok": True, "id": bid})

@app.route("/api/bookmarks/<int:bid>", methods=["PUT", "DELETE"])
@login_required
def api_bookmark_item(bid):
    username = session["username"]
    conn = get_db()
    if request.method == "DELETE":
        cursor = conn.cursor()
        cursor.execute("DELETE FROM bookmarks WHERE id=%s AND username=%s", (bid, username))
        conn.commit(); cursor.close(); conn.close()
        return jsonify({"ok": True})
    else:
        data = request.get_json() or {}
        cursor = conn.cursor()
        cursor.execute("UPDATE bookmarks SET title=%s, url=%s, category=%s WHERE id=%s AND username=%s", (data.get("title"), data.get("url"), data.get("category"), bid, username))
        conn.commit(); cursor.close(); conn.close()
        return jsonify({"ok": True})

# ---------- 文件格式转换 ----------
@app.route("/converter")
@login_required
def converter_page():
    return render_template("converter.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

@app.route("/api/converter", methods=["POST"])
@login_required
def api_converter():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "请上传文件"}), 400
    file = request.files["file"]
    target = request.form.get("target", "txt")
    filename = file.filename or "untitled"
    try:
        content = file.read()
        result = ""
        result_name = ""
        mime = "text/plain"
        # 图片格式转换
        if target in ("png", "jpg", "jpeg", "webp", "gif", "bmp"):
            img = Image.open(io.BytesIO(content))
            buf = io.BytesIO()
            fmt = "JPEG" if target in ("jpg", "jpeg") else target.upper()
            if fmt == "JPEG":
                img = img.convert("RGB")
            img.save(buf, format=fmt)
            result = buf.getvalue()
            base = os.path.splitext(filename)[0]
            result_name = f"{base}.{target}"
            mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif", "bmp": "image/bmp"}
            mime = mime_map.get(target, "application/octet-stream")
        # CSV → JSON
        elif target == "json" and filename.lower().endswith(".csv"):
            import csv as _csv
            text = content.decode("utf-8", errors="replace")
            reader = _csv.DictReader(io.StringIO(text))
            result = json.dumps([row for row in reader], ensure_ascii=False, indent=2).encode("utf-8")
            base = os.path.splitext(filename)[0]
            result_name = f"{base}.json"
            mime = "application/json"
        # JSON → CSV
        elif target == "csv" and filename.lower().endswith(".json"):
            data = json.loads(content.decode("utf-8", errors="replace"))
            if isinstance(data, dict):
                data = [data]
            if data:
                import csv as _csv
                buf = io.StringIO()
                writer = _csv.DictWriter(buf, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)
                result = buf.getvalue().encode("utf-8")
                base = os.path.splitext(filename)[0]
                result_name = f"{base}.csv"
                mime = "text/csv"
        # 文本 → 其他编码
        elif target in ("utf8", "gbk", "gb2312"):
            text = content.decode("utf-8", errors="replace")
            result = text.encode(target if target != "utf8" else "utf-8")
            result_name = filename + f".{target}"
        else:
            return jsonify({"ok": False, "error": f"不支持的转换类型: {target}"}), 400
        
        # 返回文件
        import base64 as _b64
        return jsonify({
            "ok": True,
            "filename": result_name,
            "data": _b64.b64encode(result).decode(),
            "mime": mime
        })
    except Exception as e:
        return jsonify({"ok": False, "error": f"转换失败: {str(e)}"}), 500

# ---------- PDF 工具箱 ----------
@app.route("/pdf_tools")
@login_required
def pdf_tools_page():
    return render_template("pdf_tools.html", username=session.get("username", ""), permission=session.get("permission", "guest"))


@app.route("/api/pdf/merge", methods=["POST"])
@login_required
def api_pdf_merge():
    try:
        from PyPDF2 import PdfReader, PdfWriter
    except ImportError:
        return jsonify({"ok": False, "error": "PyPDF2 未安装，请联系管理员"}), 500

    files = request.files.getlist("files")
    if not files or len(files) < 2:
        return jsonify({"ok": False, "error": "请至少上传 2 个 PDF 文件"}), 400

    writer = PdfWriter()
    total_pages = 0
    for f in files:
        if f.filename and not f.filename.lower().endswith(".pdf"):
            return jsonify({"ok": False, "error": f"文件 {f.filename} 不是 PDF 格式"}), 400
        try:
            reader = PdfReader(f.stream)
            if len(reader.pages) == 0:
                return jsonify({"ok": False, "error": f"文件 {f.filename} 为空或已损坏"}), 400
            for page in reader.pages:
                writer.add_page(page)
            total_pages += len(reader.pages)
        except Exception as e:
            return jsonify({"ok": False, "error": f"读取 {f.filename} 失败: {str(e)}"}), 400

    import uuid, os
    os.makedirs("/tmp/pdf_tools", exist_ok=True)
    filename = f"{uuid.uuid4().hex}.pdf"
    filepath = os.path.join("/tmp/pdf_tools", filename)
    with open(filepath, "wb") as out:
        writer.write(out)

    return jsonify({
        "ok": True,
        "filename": filename,
        "info": f"共合并 {len(files)} 个文件，{total_pages} 页"
    })


@app.route("/api/pdf/split", methods=["POST"])
@login_required
def api_pdf_split():
    try:
        from PyPDF2 import PdfReader, PdfWriter
    except ImportError:
        return jsonify({"ok": False, "error": "PyPDF2 未安装，请联系管理员"}), 500

    if "file" not in request.files:
        return jsonify({"ok": False, "error": "请上传 PDF 文件"}), 400
    file = request.files["file"]
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return jsonify({"ok": False, "error": "请上传有效的 PDF 文件"}), 400

    page_range_str = request.form.get("page_range", "").strip()
    if not page_range_str:
        return jsonify({"ok": False, "error": "请输入页码范围"}), 400

    # Parse page range like "1-3,5,7-9"
    try:
        reader = PdfReader(file.stream)
        total_pages = len(reader.pages)
        if total_pages == 0:
            return jsonify({"ok": False, "error": "PDF 文件为空"}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"读取 PDF 失败: {str(e)}"}), 400

    # Parse ranges
    selected_pages = set()
    parts = [p.strip() for p in page_range_str.split(",") if p.strip()]
    for part in parts:
        if "-" in part:
            try:
                start, end = part.split("-", 1)
                start, end = int(start.strip()), int(end.strip())
                if start < 1 or end > total_pages or start > end:
                    return jsonify({"ok": False, "error": f"页码范围 {part} 超出范围 (1-{total_pages})"}), 400
                for i in range(start, end + 1):
                    selected_pages.add(i)
            except ValueError:
                return jsonify({"ok": False, "error": f"无法解析页码范围: {part}"}), 400
        else:
            try:
                p = int(part)
                if p < 1 or p > total_pages:
                    return jsonify({"ok": False, "error": f"页码 {p} 超出范围 (1-{total_pages})"}), 400
                selected_pages.add(p)
            except ValueError:
                return jsonify({"ok": False, "error": f"无法解析页码: {part}"}), 400

    if not selected_pages:
        return jsonify({"ok": False, "error": "未选择任何有效页面"}), 400

    writer = PdfWriter()
    sorted_pages = sorted(selected_pages)
    for p in sorted_pages:
        writer.add_page(reader.pages[p - 1])  # 0-indexed

    import uuid, os
    os.makedirs("/tmp/pdf_tools", exist_ok=True)
    filename = f"{uuid.uuid4().hex}.pdf"
    filepath = os.path.join("/tmp/pdf_tools", filename)
    with open(filepath, "wb") as out:
        writer.write(out)

    return jsonify({
        "ok": True,
        "filename": filename,
        "info": f"提取了 {len(sorted_pages)} 页 (页码: {','.join(str(p) for p in sorted_pages)})"
    })


@app.route("/api/pdf/compress", methods=["POST"])
@login_required
def api_pdf_compress():
    try:
        from PyPDF2 import PdfReader, PdfWriter
    except ImportError:
        return jsonify({"ok": False, "error": "PyPDF2 未安装，请联系管理员"}), 500

    if "file" not in request.files:
        return jsonify({"ok": False, "error": "请上传 PDF 文件"}), 400
    file = request.files["file"]
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return jsonify({"ok": False, "error": "请上传有效的 PDF 文件"}), 400

    try:
        reader = PdfReader(file.stream)
        if len(reader.pages) == 0:
            return jsonify({"ok": False, "error": "PDF 文件为空"}), 400
        writer = PdfWriter()
        for page in reader.pages:
            page.compress_content_streams()
            writer.add_page(page)
    except Exception as e:
        return jsonify({"ok": False, "error": f"压缩失败: {str(e)}"}), 500

    import uuid, os
    os.makedirs("/tmp/pdf_tools", exist_ok=True)
    filename = f"{uuid.uuid4().hex}.pdf"
    filepath = os.path.join("/tmp/pdf_tools", filename)
    with open(filepath, "wb") as out:
        writer.write(out)

    original_size = os.path.getsize(filepath)
    import math
    def fmt(size):
        if size < 1024: return f"{size} B"
        if size < 1024*1024: return f"{size/1024:.1f} KB"
        return f"{size/(1024*1024):.1f} MB"

    return jsonify({
        "ok": True,
        "filename": filename,
        "info": f"压缩后大小: {fmt(original_size)} · 共 {len(reader.pages)} 页"
    })


@app.route("/api/pdf/extract_text", methods=["POST"])
@login_required
def api_pdf_extract_text():
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        return jsonify({"ok": False, "error": "PyPDF2 未安装，请联系管理员"}), 500

    if "file" not in request.files:
        return jsonify({"ok": False, "error": "请上传 PDF 文件"}), 400
    file = request.files["file"]
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return jsonify({"ok": False, "error": "请上传有效的 PDF 文件"}), 400

    try:
        reader = PdfReader(file.stream)
        pages_text = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                pages_text.append(text.strip())
        full_text = "\n\n".join(pages_text)
        chars = len(full_text)
    except Exception as e:
        return jsonify({"ok": False, "error": f"提取文本失败: {str(e)}"}), 500

    return jsonify({
        "ok": True,
        "text": full_text,
        "pages": len(reader.pages),
        "chars": chars
    })


@app.route("/api/pdf/download/<filename>")
@login_required
def api_pdf_download(filename):
    from werkzeug.utils import secure_filename
    safe_name = secure_filename(filename)
    filepath = os.path.join("/tmp/pdf_tools", safe_name)
    if not os.path.exists(filepath):
        return jsonify({"ok": False, "error": "文件不存在或已过期"}), 404
    try:
        from flask import send_file
        response = send_file(filepath, as_attachment=True, download_name=safe_name, mimetype="application/pdf")
        # Schedule cleanup after response
        import threading
        def cleanup():
            try:
                import time
                time.sleep(5)
                os.remove(filepath)
            except Exception:
                pass
        threading.Thread(target=cleanup, daemon=True).start()
        return response
    except Exception as e:
        return jsonify({"ok": False, "error": f"下载失败: {str(e)}"}), 500


# ---------- RSS 阅读器 ----------
@app.route("/rss")
@login_required
def rss_page():
    _init_life_tables()
    return render_template("rss_reader.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

@app.route("/api/rss/fetch", methods=["POST"])
@login_required
def api_rss_fetch():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"ok": False, "error": "URL不能为空"}), 400
    try:
        import feedparser
        feed = feedparser.parse(url)
        if feed.bozo and not feed.entries:
            return jsonify({"ok": False, "error": "无法解析该RSS源"}), 400
        entries = []
        for e in feed.entries[:30]:
            entries.append({
                "title": e.get("title", ""),
                "link": e.get("link", ""),
                "summary": (e.get("summary", "") or e.get("description", ""))[:300],
                "published": e.get("published", "") or e.get("updated", ""),
            })
        return jsonify({"ok": True, "feed_title": feed.feed.get("title", url), "entries": entries})
    except ImportError:
        # 无 feedparser 时用 xml.etree 简单解析
        try:
            import xml.etree.ElementTree as ET
            resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            root = ET.fromstring(resp.content)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            entries = []
            # RSS 2.0
            for item in root.iter("item"):
                entries.append({
                    "title": (item.findtext("title") or "").strip(),
                    "link": (item.findtext("link") or "").strip(),
                    "summary": ((item.findtext("description") or "")[:300]).strip(),
                    "published": (item.findtext("pubDate") or "").strip(),
                })
            # Atom
            if not entries:
                for entry in root.findall(".//atom:entry", ns):
                    entries.append({
                        "title": (entry.findtext("atom:title", "", ns) or "").strip(),
                        "link": (entry.find(".//atom:link[@rel='alternate']", ns) or entry.find("atom:link", ns) or {}).get("href", ""),
                        "summary": ((entry.findtext("atom:summary", "", ns) or entry.findtext("atom:content", "", ns))[:300]).strip(),
                        "published": (entry.findtext("atom:updated", "", ns) or entry.findtext("atom:published", "", ns) or "").strip(),
                    })
            feed_title = root.findtext(".//channel/title") or url
            return jsonify({"ok": True, "feed_title": feed_title, "entries": entries[:30]})
        except Exception as e:
            return jsonify({"ok": False, "error": f"解析失败: {str(e)}"}), 500

@app.route("/api/rss/feeds", methods=["GET", "POST"])
@login_required
def api_rss_feeds():
    username = session["username"]
    conn = get_db()
    if request.method == "GET":
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, url FROM rss_feeds WHERE username=%s ORDER BY id", (username,))
        rows = cursor.fetchall()
        cursor.close(); conn.close()
        return jsonify({"feeds": [{"id": r[0], "title": r[1], "url": r[2]} for r in rows]})
    else:
        data = request.get_json() or {}
        title = data.get("title", "").strip()
        url = data.get("url", "").strip()
        if not title or not url:
            return jsonify({"ok": False, "error": "标题和URL不能为空"}), 400
        cursor = conn.cursor()
        cursor.execute("INSERT INTO rss_feeds (username, title, url) VALUES (%s,%s,%s)", (username, title, url))
        conn.commit(); cursor.close(); conn.close()
        return jsonify({"ok": True})

@app.route("/api/rss/feeds/<int:fid>", methods=["DELETE"])
@login_required
def api_rss_feed_item(fid):
    username = session["username"]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM rss_feeds WHERE id=%s AND username=%s", (fid, username))
    conn.commit(); cursor.close(); conn.close()
    return jsonify({"ok": True})

# ---------- 每日一言 ----------
@app.route("/daily_quote")
def daily_quote_page():
    return render_template("daily_quote.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

@app.route("/api/daily_quote")
def api_daily_quote():
    try:
        resp = requests.get("https://v1.hitokoto.cn/?c=a&c=b&c=c&c=d&c=e&c=f&c=g&c=h&c=i&c=j&c=k&c=l", timeout=5)
        data = resp.json()
        return jsonify({"ok": True, "text": data.get("hitokoto", ""), "author": data.get("from_who") or "佚名", "source": data.get("from", "")})
    except Exception:
        # 本地备用
        quotes = [
            {"text": "路漫漫其修远兮，吾将上下而求索。", "author": "屈原", "source": "《离骚》"},
            {"text": "天行健，君子以自强不息。", "author": "佚名", "source": "《周易》"},
            {"text": "长风破浪会有时，直挂云帆济沧海。", "author": "李白", "source": "《行路难》"},
            {"text": "宝剑锋从磨砺出，梅花香自苦寒来。", "author": "佚名", "source": "《警世贤文》"},
            {"text": "人生自古谁无死，留取丹心照汗青。", "author": "文天祥", "source": "《过零丁洋》"},
            {"text": "非淡泊无以明志，非宁静无以致远。", "author": "诸葛亮", "source": "《诫子书》"},
            {"text": "海内存知己，天涯若比邻。", "author": "王勃", "source": "《送杜少府之任蜀州》"},
            {"text": "会当凌绝顶，一览众山小。", "author": "杜甫", "source": "《望岳》"},
        ]
        import random as _rand
        q = _rand.choice(quotes)
        return jsonify({"ok": True, **q})

# ---------- 小游戏 ----------
@app.route("/games")
def games_page():
    return render_template("games.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

# ---------- 二维码生成 ----------
@app.route("/qrcode")
@login_required
def qrcode_page():
    return render_template("qrcode.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

@app.route("/api/qrcode", methods=["POST"])
@login_required
def api_qrcode():
    data = request.get_json() or {}
    text = data.get("text", "").strip()
    size = int(data.get("size", 300))
    if not text:
        return jsonify({"ok": False, "error": "内容不能为空"}), 400
    try:
        import qrcode as _qr
        qr = _qr.QRCode(box_size=max(4, min(20, size // 25)), border=2)
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        # Resize to exact requested pixel size
        img = img.resize((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        import base64 as _b64
        return jsonify({"ok": True, "qrcode": _b64.b64encode(buf.getvalue()).decode()})
    except ImportError:
        return jsonify({"ok": False, "error": "qrcode 库未安装"}), 500

# ---------- 图片压缩 ----------
@app.route("/image_compress")
@login_required
def image_compress_page():
    return render_template("image_compress.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

@app.route("/api/image_compress", methods=["POST"])
@login_required
def api_image_compress():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "请上传图片"}), 400
    file = request.files["file"]
    quality = int(request.form.get("quality", 70))
    max_width = int(request.form.get("max_width", 1920))
    try:
        file_data = file.read()
        original_size = len(file_data)
        img = Image.open(io.BytesIO(file_data))
        # 保存原始格式（resize 后会丢失）
        original_format = img.format or "JPEG"
        # 缩放
        w, h = img.size
        if w > max_width:
            ratio = max_width / w
            img = img.resize((max_width, int(h * ratio)), Image.LANCZOS)
        # 压缩
        buf = io.BytesIO()
        if original_format == "PNG":
            img.save(buf, format="PNG", optimize=True)
        else:
            if img.mode in ("RGBA", "LA", "P"):
                img = img.convert("RGBA")
                img.save(buf, format="PNG", optimize=True)
            else:
                img = img.convert("RGB")
                img.save(buf, format="JPEG", quality=quality, optimize=True)
        compressed = buf.getvalue()
        import base64 as _b64
        mime_type = "image/png" if original_format == "PNG" or img.mode in ("RGBA", "LA", "P") else "image/jpeg"
        return jsonify({
            "ok": True,
            "original_size": original_size,
            "compressed_size": len(compressed),
            "compressed": _b64.b64encode(compressed).decode(),
            "mime_type": mime_type,
            "ratio": round((1 - len(compressed)/max(original_size,1)) * 100, 1)
        })
    except Exception as e:
        return jsonify({"ok": False, "error": f"压缩失败: {str(e)}"}), 500

# ---------- API 测试器 ----------
@app.route("/api_tester")
@login_required
def api_tester_page():
    return render_template("api_tester.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

@app.route("/api/api_tester/proxy", methods=["POST"])
@login_required
def api_api_tester_proxy():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    method = data.get("method", "GET").upper()
    headers = data.get("headers", {})
    body = data.get("body", "")
    if not url:
        return jsonify({"ok": False, "error": "URL不能为空"}), 400
    if not url.startswith("http"):
        url = "https://" + url
    try:
        req_headers = {"User-Agent": "Mozilla/5.0"}
        if isinstance(headers, dict):
            req_headers.update(headers)
        kwargs = {"timeout": 15, "headers": req_headers, "allow_redirects": True}
        if method in ("POST", "PUT", "PATCH"):
            if body:
                kwargs["data"] = body
        resp = requests.request(method, url, **kwargs)
        return jsonify({
            "ok": True,
            "status": resp.status_code,
            "headers": dict(resp.headers),
            "body": resp.text[:5000]
        })
    except Exception as e:
        return jsonify({"ok": False, "error": f"请求失败: {str(e)}"}), 500


# ---------- Markdown 编辑器 ----------
@app.route("/markdown")
@login_required
def markdown_page():
    return render_template("markdown.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

# ---------- 单位换算 ----------
@app.route("/unit_converter")
@login_required
def unit_converter_page():
    return render_template("unit_converter.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

# ---------- 文本差异对比 ----------
@app.route("/text_diff")
@login_required
def text_diff_page():
    return render_template("text_diff.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

# ---------- JWT 解码器 ----------
@app.route("/jwt_decoder")
@login_required
def jwt_decoder_page():
    return render_template("jwt_decoder.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

# ---------- 倒计时纪念日 ----------
@app.route("/countdown")
@login_required
def countdown_page():
    return render_template("countdown.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

# ---------- SQL 格式化器 ----------
@app.route("/sql_formatter")
@login_required
def sql_formatter_page():
    return render_template("sql_formatter.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

# ---------- 模拟数据生成器 ----------
@app.route("/mock_data")
@login_required
def mock_data_page():
    return render_template("mock_data.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

# ---------- 随机工具 ----------
@app.route("/random_tools")
@login_required
def random_tools_page():
    return render_template("random_tools.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

# ---------- Git 命令手册 ----------
@app.route("/git_cheatsheet")
@login_required
def git_cheatsheet_page():
    return render_template("git_cheatsheet.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

# ---------- 密码强度分析 ----------
@app.route("/password_analyzer")
@login_required
def password_analyzer_page():
    return render_template("password_analyzer.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

# ---------- 格式转换器 ----------
@app.route("/file_converter")
@login_required
def file_converter_page():
    return render_template("file_converter.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

# ---------- 摩尔斯电码 ----------
@app.route("/morse_code")
@login_required
def morse_code_page():
    return render_template("morse_code.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

# ---------- 身份证 & 银行卡工具 ----------
@app.route("/idcard_tools")
@login_required
def idcard_tools_page():
    return render_template("idcard_tools.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

# ---------- Cron 表达式解析 ----------
@app.route("/cron_parser")
@login_required
def cron_parser_page():
    return render_template("cron_parser.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

# ---------- UA 解析器 ----------
@app.route("/ua_parser")
@login_required
def ua_parser_page():
    return render_template("ua_parser.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

# ---------- 代码格式化/压缩 ----------
@app.route("/code_formatter")
@login_required
def code_formatter_page():
    return render_template("code_formatter.html", username=session.get("username", ""), permission=session.get("permission", "guest"))


# ==============================================================
#  信息门户 & 校友录
# ==============================================================

# ---- 信息门户主页 ----
@app.route("/portal")
@login_required
def portal_page():
    """
    信息门户页面（URL: /portal）。

    权限：需要登录
    功能：聚合展示最新公告、热门帖子、近期活动、校友统计等。
    """
    _init_forum_tables()
    return render_template("portal.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

# ---- 门户 API：聚合数据 ----
@app.route("/api/portal/summary")
@login_required
def api_portal_summary():
    conn = get_db()
    cursor = conn.cursor()

    # 最新公告（置顶+公告标记）
    cursor.execute("""
        SELECT p.id, p.title, p.content, p.username, p.created_at, c.icon as cat_icon, c.name as cat_name
        FROM forum_posts p JOIN forum_categories c ON p.category_id=c.id
        WHERE p.is_announcement=1 OR p.is_pinned=1
        ORDER BY p.is_announcement DESC, p.created_at DESC LIMIT 5
    """)
    announcements = [{"id": r[0], "title": r[1], "content": r[2][:120], "username": r[3], "created_at": str(r[4]), "cat_icon": r[5], "cat_name": r[6]} for r in cursor.fetchall()]

    # 最新帖子
    cursor.execute("""
        SELECT p.id, p.title, p.content, p.username, p.created_at, c.icon, c.name, p.reply_count
        FROM forum_posts p JOIN forum_categories c ON p.category_id=c.id
        ORDER BY p.created_at DESC LIMIT 10
    """)
    latest_posts = [{"id": r[0], "title": r[1], "content": r[2][:100], "username": r[3], "created_at": str(r[4]), "cat_icon": r[5], "cat_name": r[6], "reply_count": r[7]} for r in cursor.fetchall()]

    # 近期活动（calendar_events 中 category='event' 的）
    today = __import__('datetime').date.today().isoformat()
    cursor.execute("""
        SELECT id, title, description, event_date, event_time, username, category
        FROM calendar_events WHERE event_date >= %s AND category='event'
        ORDER BY event_date ASC LIMIT 8
    """, (today,))
    events = [{"id": r[0], "title": r[1], "description": (r[2] or "")[:100], "event_date": str(r[3]), "event_time": str(r[4]) if r[4] else "", "username": r[5], "category": r[6]} for r in cursor.fetchall()]

    # 校友统计
    cursor.execute("SELECT COUNT(*) FROM user_profiles WHERE graduation_year IS NOT NULL AND public_profile=1")
    alumni_count = cursor.fetchone()[0]

    cursor.close(); conn.close()
    return jsonify({"announcements": announcements, "latest_posts": latest_posts, "events": events, "alumni_count": alumni_count})

# ---- 校友录主页 ----
@app.route("/alumni")
@login_required
def alumni_page():
    """
    校友录页面（URL: /alumni）。

    权限：需要登录
    功能：按毕业年份搜索校友，查看公开资料。
    """
    _init_reset_table()
    return render_template("alumni.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

# ---- 校友录 API：列表 ----
@app.route("/api/alumni/list")
@login_required
def api_alumni_list():
    page = request.args.get("page", 1, type=int)
    per_page = 20
    grad_year = request.args.get("year", type=int)
    keyword = request.args.get("keyword", "").strip()
    offset_val = (page - 1) * per_page

    conn = get_db()
    cursor = conn.cursor()
    where = "WHERE up.public_profile=1"
    params = []

    if grad_year:
        where += " AND up.graduation_year=%s"
        params.append(grad_year)
    if keyword:
        where += " AND (up.username LIKE %s OR up.nickname LIKE %s OR up.city LIKE %s OR up.class_name LIKE %s)"
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw, kw])

    cursor.execute(f"SELECT COUNT(*) FROM user_profiles up {where}", params)
    total = cursor.fetchone()[0]
    total_pages = max(1, (total + per_page - 1) // per_page) if total > 0 else 1

    cursor.execute(f"""
        SELECT up.username, up.nickname, up.graduation_year, up.class_name, up.city, up.bio
        FROM user_profiles up {where}
        ORDER BY up.graduation_year DESC, up.class_name, up.username
        LIMIT %s OFFSET %s
    """, params + [per_page, offset_val])
    rows = cursor.fetchall()
    alumni = [{
        "username": r[0], "nickname": r[1] or r[0], "graduation_year": r[2],
        "class_name": r[3] or "", "city": r[4] or "",
        "bio": (r[5] or "")[:80],
        "avatar": (r[1] or r[0])[0].upper()
    } for r in rows]

    cursor.close(); conn.close()
    return jsonify({"alumni": alumni, "total": total, "page": page, "total_pages": total_pages})

# ---- 校友录 API：统计 ----
@app.route("/api/alumni/stats")
@login_required
def api_alumni_stats():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT graduation_year, COUNT(*) FROM user_profiles WHERE graduation_year IS NOT NULL AND public_profile=1 GROUP BY graduation_year ORDER BY graduation_year DESC")
    year_stats = [{"year": r[0], "count": r[1]} for r in cursor.fetchall()]
    cursor.execute("SELECT COUNT(*) FROM user_profiles WHERE public_profile=1")
    total = cursor.fetchone()[0]
    cursor.close(); conn.close()
    return jsonify({"year_stats": year_stats, "total": total})

# ---- 校友录 API：更新自己的资料 ----
@app.route("/api/alumni/profile", methods=["GET", "POST"])
@login_required
def api_alumni_profile():
    username = session["username"]
    conn = get_db()

    if request.method == "GET":
        cursor = conn.cursor()
        cursor.execute("SELECT nickname, graduation_year, class_name, major, city, occupation, wechat, bio, public_profile FROM user_profiles WHERE username=%s", (username,))
        r = cursor.fetchone()
        cursor.close(); conn.close()
        if r:
            return jsonify({"nickname": r[0], "graduation_year": r[1], "class_name": r[2], "major": r[3], "city": r[4], "occupation": r[5], "wechat": r[6], "bio": r[7], "public_profile": bool(r[8])})
        return jsonify({"nickname": username, "public_profile": True})

    # POST 更新
    data = request.get_json() or {}
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO user_profiles (username, nickname, graduation_year, class_name, major, city, occupation, wechat, bio, public_profile)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            nickname=VALUES(nickname), graduation_year=VALUES(graduation_year), class_name=VALUES(class_name),
            major=VALUES(major), city=VALUES(city), occupation=VALUES(occupation), wechat=VALUES(wechat),
            bio=VALUES(bio), public_profile=VALUES(public_profile)
    """, (
        username,
        data.get("nickname", username),
        data.get("graduation_year"),
        data.get("class_name", ""),
        data.get("major", ""),
        data.get("city", ""),
        data.get("occupation", ""),
        data.get("wechat", ""),
        data.get("bio", ""),
        1 if data.get("public_profile", True) else 0
    ))
    conn.commit()
    cursor.close(); conn.close()
    _log_activity_local(username, "alumni_profile", 3)
    return jsonify({"ok": True})

# ---- 公告管理（仅管理员的 forum 帖子标记为公告） ----
@app.route("/api/portal/announce", methods=["POST"])
@login_required
def api_portal_announce():
    if session.get("permission") != "administrator":
        return jsonify({"ok": False, "error": "仅管理员可操作"}), 403
    data = request.get_json() or {}
    pid = data.get("post_id")
    val = data.get("announce", True)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE forum_posts SET is_announcement=%s WHERE id=%s", (1 if val else 0, pid))
    conn.commit(); cursor.close(); conn.close()
    return jsonify({"ok": True})


# ==============================================================
# ====== 校友故事/回忆录 ======
# ==============================================================

@app.route("/alumni_stories")
@login_required
def alumni_stories_page():
    """
    校友故事/回忆录页面（URL: /alumni_stories）。

    权限：需要登录
    功能：发布/浏览校友故事，支持评论和点赞。新故事需管理员审核。
    """
    _init_alumni_stories_tables()
    return render_template("alumni_stories.html", username=session.get("username", ""), permission=session.get("permission", "guest"))


@app.route("/api/alumni_stories", methods=["GET", "POST"])
@login_required
def api_alumni_stories():
    username = session["username"]
    permission = session.get("permission", "guest")
    conn = get_db()

    if request.method == "GET":
        page = request.args.get("page", 1, type=int)
        per_page = 12
        offset_val = (page - 1) * per_page
        status_filter = request.args.get("status", "approved")
        # Non-admin can only see approved
        if permission != "administrator":
            status_filter = "approved"

        cursor = conn.cursor()
        where = "WHERE status=%s"
        params = [status_filter]
        if status_filter == "my":
            where = "WHERE username=%s"
            params = [username]

        cursor.execute(f"SELECT COUNT(*) FROM alumni_stories {where}", params)
        total = cursor.fetchone()[0]
        cursor.execute(
            f"SELECT id, username, title, content, cover_image, status, view_count, like_count, comment_count, created_at FROM alumni_stories {where} ORDER BY id DESC LIMIT %s OFFSET %s",
            params + [per_page, offset_val]
        )
        rows = cursor.fetchall()
        cursor.close(); conn.close()
        stories = [{
            "id": r[0], "username": r[1], "title": r[2], "excerpt": (r[3] or "")[:150],
            "cover_image": r[4], "status": r[5], "view_count": r[6],
            "like_count": r[7], "comment_count": r[8], "created_at": str(r[9])
        } for r in rows]
        total_pages = max(1, (total + per_page - 1) // per_page)
        return jsonify({"stories": stories, "total": total, "page": page, "total_pages": total_pages})

    else:  # POST
        data = request.get_json() or {}
        title = sanitize_input(data.get("title", ""), 200)
        content = sanitize_input(data.get("content", ""), 50000)
        if not title or not content:
            conn.close()
            return jsonify({"error": "标题和内容不能为空"}), 400
        cover_image = data.get("cover_image", "")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO alumni_stories (username, title, content, cover_image) VALUES (%s, %s, %s, %s)",
            (username, title, content, cover_image)
        )
        conn.commit()
        sid = cursor.lastrowid
        cursor.close(); conn.close()
        return jsonify({"ok": True, "id": sid})


@app.route("/api/alumni_stories/<int:sid>")
@login_required
def api_alumni_story_detail(sid):
    username = session["username"]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, title, content, cover_image, status, view_count, like_count, comment_count, created_at, reviewer, review_note FROM alumni_stories WHERE id=%s", (sid,))
    row = cursor.fetchone()
    if not row:
        cursor.close(); conn.close()
        return jsonify({"error": "故事不存在"}), 404

    story = {
        "id": row[0], "username": row[1], "title": row[2], "content": row[3],
        "cover_image": row[4], "status": row[5], "view_count": row[6],
        "like_count": row[7], "comment_count": row[8], "created_at": str(row[9]),
        "reviewer": row[10], "review_note": row[11]
    }

    # Increment view count (only once per session)
    view_key = f"viewed_story_{sid}"
    if view_key not in session:
        cursor.execute("UPDATE alumni_stories SET view_count = view_count + 1 WHERE id=%s", (sid,))
        conn.commit()
        session[view_key] = True
        story["view_count"] += 1

    # Comments
    cursor.execute("SELECT id, username, content, created_at FROM alumni_story_comments WHERE story_id=%s ORDER BY id ASC", (sid,))
    story["comments"] = [{"id": r[0], "username": r[1], "content": r[2], "created_at": str(r[3])} for r in cursor.fetchall()]

    # Like status
    cursor.execute("SELECT id FROM alumni_story_likes WHERE story_id=%s AND username=%s", (sid, username))
    story["liked"] = cursor.fetchone() is not None

    cursor.close(); conn.close()
    return jsonify({"story": story})


@app.route("/api/alumni_stories/<int:sid>", methods=["PUT", "DELETE"])
@login_required
def api_alumni_story_edit(sid):
    username = session["username"]
    conn = get_db()
    if request.method == "DELETE":
        cursor = conn.cursor()
        cursor.execute("DELETE FROM alumni_stories WHERE id=%s AND username=%s", (sid, username))
        conn.commit(); cursor.close(); conn.close()
        return jsonify({"ok": True})
    else:
        data = request.get_json() or {}
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE alumni_stories SET title=%s, content=%s, cover_image=%s, status='pending' WHERE id=%s AND username=%s",
            (data.get("title"), data.get("content"), data.get("cover_image", ""), sid, username)
        )
        conn.commit(); cursor.close(); conn.close()
        return jsonify({"ok": True})


@app.route("/api/alumni_stories/<int:sid>/comments", methods=["POST"])
@login_required
def api_alumni_story_comment(sid):
    username = session["username"]
    data = request.get_json() or {}
    content = sanitize_input(data.get("content", ""), 2000)
    if not content:
        return jsonify({"error": "评论不能为空"}), 400
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO alumni_story_comments (story_id, username, content) VALUES (%s, %s, %s)", (sid, username, content))
    cursor.execute("UPDATE alumni_stories SET comment_count = comment_count + 1 WHERE id=%s", (sid,))
    conn.commit()
    cid = cursor.lastrowid
    cursor.close(); conn.close()
    return jsonify({"ok": True, "id": cid})


@app.route("/api/alumni_stories/<int:sid>/like", methods=["POST"])
@login_required
def api_alumni_story_like(sid):
    username = session["username"]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM alumni_story_likes WHERE story_id=%s AND username=%s", (sid, username))
    existing = cursor.fetchone()
    if existing:
        cursor.execute("DELETE FROM alumni_story_likes WHERE id=%s", (existing[0],))
        cursor.execute("UPDATE alumni_stories SET like_count = GREATEST(like_count - 1, 0) WHERE id=%s", (sid,))
        conn.commit()
        cursor.execute("SELECT like_count FROM alumni_stories WHERE id=%s", (sid,))
        new_count = cursor.fetchone()[0]
        cursor.close(); conn.close()
        return jsonify({"liked": False, "like_count": new_count})
    else:
        cursor.execute("INSERT INTO alumni_story_likes (story_id, username) VALUES (%s, %s)", (sid, username))
        cursor.execute("UPDATE alumni_stories SET like_count = like_count + 1 WHERE id=%s", (sid,))
        conn.commit()
        cursor.execute("SELECT like_count FROM alumni_stories WHERE id=%s", (sid,))
        new_count = cursor.fetchone()[0]
        cursor.close(); conn.close()
        return jsonify({"liked": True, "like_count": new_count})


@app.route("/api/admin/alumni_stories")
@login_required
def api_admin_alumni_stories():
    if session.get("permission") != "administrator":
        return jsonify({"error": "仅管理员可访问"}), 403
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, title, content, cover_image, status, created_at FROM alumni_stories WHERE status='pending' ORDER BY id ASC")
    rows = cursor.fetchall()
    cursor.close(); conn.close()
    return jsonify({"stories": [{"id": r[0], "username": r[1], "title": r[2], "excerpt": (r[3] or "")[:200], "cover_image": r[4], "status": r[5], "created_at": str(r[6])} for r in rows]})


@app.route("/api/admin/alumni_stories/<int:sid>/review", methods=["POST"])
@login_required
def api_admin_review_story(sid):
    if session.get("permission") != "administrator":
        return jsonify({"error": "仅管理员可访问"}), 403
    data = request.get_json() or {}
    action = data.get("action", "approve")
    note = data.get("note", "")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE alumni_stories SET status=%s, reviewer=%s, review_note=%s, reviewed_at=NOW() WHERE id=%s",
        (action, session["username"], note, sid)
    )
    conn.commit(); cursor.close(); conn.close()
    return jsonify({"ok": True})


# ==============================================================
#  虚拟宠物 (Virtual Pet)
# ==============================================================

@app.route("/pet")
@login_required
def pet_page():
    """
    虚拟宠物页面（URL: /pet）。

    权限：需要登录
    功能：领养/喂养/玩耍/睡觉/进化/串门，包含完整的宠物养成系统。
    """
    _init_pet_tables()
    return render_template("pet.html", username=session.get("username", ""), permission=session.get("permission", "guest"))


@app.route("/api/pet/hatch", methods=["POST"])
@login_required
def api_pet_hatch():
    username = session["username"]
    _init_pet_tables()
    data = request.get_json() or {}
    pet_type = sanitize_input(data.get("pet_type", "cat"), 20)
    if pet_type not in ("cat", "dog", "rabbit", "panda"):
        return jsonify({"ok": False, "error": "无效的宠物类型"}), 400
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM pets WHERE username=%s", (username,))
    if cursor.fetchone():
        cursor.close(); conn.close()
        return jsonify({"ok": False, "error": "你已经有一只宠物了"}), 400
    now = datetime.utcnow()
    cursor.execute(
        "INSERT INTO pets (username, pet_name, pet_type, hatched, last_fed) VALUES (%s,%s,%s,1,NOW())",
        (username, "小可爱", pet_type)
    )
    conn.commit()
    cursor.execute(
        "INSERT INTO pet_logs (username, action, detail) VALUES (%s,%s,%s)",
        (username, "hatch", f"孵化了{pet_type}宠物")
    )
    conn.commit()
    cursor.close(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/pet/rename", methods=["POST"])
@login_required
def api_pet_rename():
    username = session["username"]
    _init_pet_tables()
    data = request.get_json() or {}
    pet_name = sanitize_input(data.get("pet_name", ""), 30)
    pet_type = sanitize_input(data.get("pet_type", ""), 20)
    if pet_name and not pet_name.strip():
        return jsonify({"ok": False, "error": "名字不能为空"}), 400
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM pets WHERE username=%s", (username,))
    if not cursor.fetchone():
        cursor.close(); conn.close()
        return jsonify({"ok": False, "error": "你还没有宠物"}), 400
    updates = []
    values = []
    if pet_name and pet_name.strip():
        updates.append("pet_name=%s")
        values.append(pet_name.strip())
    if pet_type and pet_type.strip():
        if pet_type not in ("cat", "dog", "rabbit", "panda"):
            cursor.close(); conn.close()
            return jsonify({"ok": False, "error": "无效的宠物类型"}), 400
        updates.append("pet_type=%s")
        values.append(pet_type.strip())
    if not updates:
        cursor.close(); conn.close()
        return jsonify({"ok": False, "error": "没有要更新的内容"}), 400
    values.append(username)
    cursor.execute(f"UPDATE pets SET {', '.join(updates)} WHERE username=%s", values)
    conn.commit()
    cursor.execute(
        "INSERT INTO pet_logs (username, action, detail) VALUES (%s,%s,%s)",
        (username, "rename", f"重命名为{pet_name.strip() if pet_name else ''}" + (f" 类型:{pet_type}" if pet_type and pet_type.strip() else ""))
    )
    conn.commit()
    cursor.close(); conn.close()
    return jsonify({"ok": True})


# ==============================================================
#  宠物 2.0：进化系统
# ==============================================================

# 进化配置：每种宠物 3 个阶段
EVOLUTION_CONFIG = {
    "cat": [
        {"stage": 0, "emoji": "🐱", "name": "幼猫", "min_level": 1},
        {"stage": 1, "emoji": "😺", "name": "成猫", "min_level": 10},
        {"stage": 2, "emoji": "🦁", "name": "狮猫", "min_level": 25},
    ],
    "dog": [
        {"stage": 0, "emoji": "🐶", "name": "幼犬", "min_level": 1},
        {"stage": 1, "emoji": "🐕", "name": "成犬", "min_level": 10},
        {"stage": 2, "emoji": "🐺", "name": "狼犬", "min_level": 25},
    ],
    "rabbit": [
        {"stage": 0, "emoji": "🐰", "name": "幼兔", "min_level": 1},
        {"stage": 1, "emoji": "🐇", "name": "成兔", "min_level": 10},
        {"stage": 2, "emoji": "🦄", "name": "月兔", "min_level": 25},
    ],
    "panda": [
        {"stage": 0, "emoji": "🐼", "name": "幼熊猫", "min_level": 1},
        {"stage": 1, "emoji": "🐻", "name": "成熊猫", "min_level": 10},
        {"stage": 2, "emoji": "🐲", "name": "龙猫", "min_level": 25},
    ],
}

def _get_evolution(pet_type, level):
    """
    根据宠物类型和等级返回当前进化阶段信息。

    进化阶段配置在 EVOLUTION_CONFIG 中，每种宠物 3 个阶段：
    幼年 -> 成年 -> 终极形态（对应 level 1/10/25）。

    Args:
        pet_type: 宠物类型（cat/dog/rabbit/panda）
        level: 当前等级

    Returns:
        dict: {stage: int, emoji: str, name: str, min_level: int}
    """
    stages = EVOLUTION_CONFIG.get(pet_type, EVOLUTION_CONFIG["cat"])
    current = stages[0]
    for s in stages:
        if level >= s["min_level"]:
            current = s
    return current

def _get_evolution_stage(pet_type, level):
    """返回进化阶段编号"""
    return _get_evolution(pet_type, level)["stage"]


# ==============================================================
#  宠物 2.0：成就系统
# ==============================================================

ACHIEVEMENTS = {
    "first_feed": {"name": "初次喂食", "desc": "第一次喂食宠物", "icon": "🍖"},
    "feed_10": {"name": "小吃货", "desc": "喂食10次", "icon": "🍗"},
    "feed_50": {"name": "美食家", "desc": "喂食50次", "icon": "🍕"},
    "feed_100": {"name": "大胃王", "desc": "喂食100次", "icon": "🎂"},
    "first_play": {"name": "初次玩耍", "desc": "第一次和宠物玩耍", "icon": "🎾"},
    "play_10": {"name": "玩乐达人", "desc": "玩耍10次", "icon": "⚽"},
    "play_50": {"name": "运动健将", "desc": "玩耍50次", "icon": "🏆"},
    "first_sleep": {"name": "初次安睡", "desc": "第一次哄宠物睡觉", "icon": "💤"},
    "sleep_10": {"name": "好梦连连", "desc": "睡觉10次", "icon": "🌙"},
    "level_5": {"name": "初露锋芒", "desc": "宠物升到5级", "icon": "⭐"},
    "level_10": {"name": "小有成就", "desc": "宠物升到10级", "icon": "🌟"},
    "level_25": {"name": "一代宗师", "desc": "宠物升到25级", "icon": "👑"},
    "evolution_1": {"name": "蜕变", "desc": "宠物第一次进化", "icon": "🦋"},
    "evolution_2": {"name": "究极进化", "desc": "宠物完全体进化", "icon": "✨"},
    "visit_1": {"name": "初次串门", "desc": "第一次拜访别人的宠物", "icon": "🚪"},
    "visit_10": {"name": "社交达人", "desc": "拜访10次", "icon": "🤝"},
    "coins_100": {"name": "小财主", "desc": "攒够100硬币", "icon": "💰"},
    "coins_500": {"name": "百万富翁", "desc": "攒够500硬币", "icon": "💎"},
}

def _check_achievements(username, conn=None):
    """
    检查并解锁宠物成就，返回新解锁的成就列表。

    根据宠物当前的 level/xp/进化阶段/喂食/玩耍/睡眠次数/串门/硬币等数据，
    检查 ACHIEVEMENTS 字典中的所有成就是否满足条件。
    新解锁的成就写入 pet_achievements 表和 pet_diary。

    Args:
        username: 用户名
        conn: 可选的数据库连接（复用已有连接避免重复创建）

    Returns:
        list[str]: 新解锁的成就 key 列表
    """
    close_conn = False
    if not conn:
        conn = get_db()
        close_conn = True
    cursor = conn.cursor()
    cursor.execute("""
        SELECT hunger, happiness, energy, level, xp, evolution_stage, coins,
               action_count, feed_count, play_count, sleep_count, visit_count
        FROM pets WHERE username=%s
    """, (username,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        if close_conn: conn.close()
        return []
    level = row[3]; evo_stage = row[5]; coins = row[6]
    feed_count = row[8]; play_count = row[9]; sleep_count = row[10]; visit_count = row[11]

    cursor.execute("SELECT achievement_key FROM pet_achievements WHERE username=%s", (username,))
    unlocked = set(r[0] for r in cursor.fetchall())

    checks = {
        "first_feed": feed_count >= 1,
        "feed_10": feed_count >= 10,
        "feed_50": feed_count >= 50,
        "feed_100": feed_count >= 100,
        "first_play": play_count >= 1,
        "play_10": play_count >= 10,
        "play_50": play_count >= 50,
        "first_sleep": sleep_count >= 1,
        "sleep_10": sleep_count >= 10,
        "level_5": level >= 5,
        "level_10": level >= 10,
        "level_25": level >= 25,
        "evolution_1": evo_stage >= 1,
        "evolution_2": evo_stage >= 2,
        "visit_1": visit_count >= 1,
        "visit_10": visit_count >= 10,
        "coins_100": coins >= 100,
        "coins_500": coins >= 500,
    }

    new_achievements = []
    for key, met in checks.items():
        if met and key not in unlocked:
            cursor.execute(
                "INSERT INTO pet_achievements (username, achievement_key) VALUES (%s,%s)",
                (username, key)
            )
            new_achievements.append(key)
            ach = ACHIEVEMENTS.get(key, {})
            cursor.execute(
                "INSERT INTO pet_diary (username, event_type, detail) VALUES (%s,%s,%s)",
                (username, "achievement", f"解锁成就：{ach.get('name', key)} {ach.get('icon', '')}")
            )

    conn.commit()
    cursor.close()
    if close_conn: conn.close()
    return new_achievements


# ==============================================================
#  宠物 2.0：性格系统
# ==============================================================

def _calc_personality(feed_n, play_n, sleep_n):
    """
    根据行动比例计算宠物性格。

    需要至少 20 次行动才能确定性格。
    喂食最多 -> 贪吃，玩耍最多 -> 活泼，睡觉最多 -> 慵懒。

    Args:
        feed_n: 喂食次数
        play_n: 玩耍次数
        sleep_n: 睡觉次数

    Returns:
        str 或 None: "贪吃" / "活泼" / "慵懒" / None（不足 20 次）
    """
    total = feed_n + play_n + sleep_n
    if total < 20:
        return None
    if feed_n >= play_n and feed_n >= sleep_n:
        return "贪吃"
    if play_n >= feed_n and play_n >= sleep_n:
        return "活泼"
    if sleep_n >= feed_n and sleep_n >= play_n:
        return "慵懒"
    return "均衡"


# ==============================================================
#  宠物 2.0：对话系统
# ==============================================================

DIALOGUE_POOL = {
    "happy": [
        "今天心情真好呀～", "主人抱抱！💕", "嘻嘻，好开心！",
        "想出去玩！", "主人最好了！", "今天天气真好~",
    ],
    "hungry": [
        "肚子咕咕叫了...", "有没有好吃的呀？🥺", "主人我饿了！",
        "该喂食了吧...", "再不吃东西我要晕了...",
    ],
    "tired": [
        "有点困了...💤", "zzz...好想睡一觉", "今天玩太累了...",
        "能让我休息一下吗？", "眼皮好重...",
    ],
    "bored": [
        "好无聊啊...", "没人陪我玩...", "主人你在干嘛？",
        "来玩玩嘛～", "给我点事情做吧！",
    ],
    "sick": [
        "不太舒服...😷", "需要照顾...", "感觉不太好...", "主人帮帮我...",
    ],
}

PERSONALITY_DIALOGUE = {
    "贪吃": {
        "all": ["今天吃什么？😋", "零食呢零食呢？", "我觉得还能再吃一点！", "好香啊！"],
    },
    "活泼": {
        "all": ["快来玩！🏃", "我跑得快不快？", "嘿嘿，追不上我吧！", "今天也要元气满满！"],
    },
    "慵懒": {
        "all": ["嗯...再睡五分钟...", "躺着真舒服～", "别动我，我正舒服呢...", "今天只想宅着..."],
    },
    "均衡": {
        "all": ["今天也很棒！", "主人陪我一起吧~", "感觉不错！", "每天都开心！"],
    },
}

import random as _random

def _get_dialogue(hunger, happiness, energy, personality):
    """
    根据宠物当前状态返回一句随机对话。

    根据饥饿/快乐/精力值和性格，从 DIALOGUE_POOL 或 PERSONALITY_DIALOGUE 中随机选取。
    状态越差（hunger < 30/energy < 30/happiness < 30），触发对应主题的对话。

    Args:
        hunger: 饥饿值 (0-100)
        happiness: 快乐值 (0-100)
        energy: 精力值 (0-100)
        personality: 性格（"贪吃"/"活泼"/"慵懒" 等或 None）

    Returns:
        str: 对话文本
    """
    lines = []
    if hunger < 30:
        lines += DIALOGUE_POOL["hungry"]
    elif hunger < 50:
        lines += DIALOGUE_POOL["hungry"][:2]
    if energy < 30:
        lines += DIALOGUE_POOL["tired"]
    if happiness < 30:
        lines += DIALOGUE_POOL["bored"]
    if hunger < 20 and energy < 20:
        lines += DIALOGUE_POOL["sick"]
    if not lines:
        lines = DIALOGUE_POOL["happy"]
    if personality and personality in PERSONALITY_DIALOGUE:
        lines += PERSONALITY_DIALOGUE[personality]["all"]
    return _random.choice(lines)


# ==============================================================
#  宠物 2.0：装扮商店配置
# ==============================================================

ACCESSORY_SHOP = {
    "hat_magic": {"name": "魔法帽", "emoji": "🎩", "cost": 30, "position": "top"},
    "glasses": {"name": "圆眼镜", "emoji": "👓", "cost": 20, "position": "eyes"},
    "scarf": {"name": "围巾", "emoji": "🧣", "cost": 25, "position": "neck"},
    "ribbon": {"name": "蝴蝶结", "emoji": "🎀", "cost": 15, "position": "top"},
    "crown": {"name": "皇冠", "emoji": "👑", "cost": 100, "position": "top"},
    "wings": {"name": "天使翅膀", "emoji": "🪽", "cost": 80, "position": "side"},
    "bowtie": {"name": "领结", "emoji": "🎀", "cost": 15, "position": "neck"},
    "monocle": {"name": "单片镜", "emoji": "🧐", "cost": 40, "position": "eyes"},
    "halo": {"name": "光环", "emoji": "😇", "cost": 60, "position": "top"},
}


# ==============================================================
#  宠物 2.0：修改 API（覆盖旧端点）
# ==============================================================

@app.route("/api/pet")
@login_required
def api_pet_v2():
    username = session["username"]
    _init_pet_tables()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pets WHERE username=%s", (username,))
    row = cursor.fetchone()
    if not row:
        cursor.close(); conn.close()
        return jsonify({"has_pet": False})
    hunger = row[4]; happiness = row[5]; energy = row[6]
    level = row[7]; xp = row[8]; hatched = row[9]
    last_fed = row[10]; last_played = row[11]
    personality = row[14] if len(row) > 14 else None
    evolution_stage = row[15] if len(row) > 15 else 0
    coins_val = row[16] if len(row) > 16 else 0
    mood = row[17] if len(row) > 17 else "开心"
    visit_count = row[18] if len(row) > 18 else 0
    action_count = row[19] if len(row) > 19 else 0
    feed_count = row[20] if len(row) > 20 else 0
    play_count = row[21] if len(row) > 21 else 0
    sleep_count = row[22] if len(row) > 22 else 0
    accessories_str = row[24] if len(row) > 24 else "[]"
    last_slept = row[23] if len(row) > 23 else None
    now = datetime.utcnow()
    if hatched:
        if last_fed:
            elapsed = (now - last_fed).total_seconds() / 3600.0
            hunger = max(0, int(hunger - elapsed * 5))
        if last_played:
            elapsed = (now - last_played).total_seconds() / 3600.0
            happiness = max(0, int(happiness - elapsed * 3))
        # 精力恢复：优先基于睡眠时间（快），否则基于玩耍时间（慢）
        recovery_elapsed = None
        if last_slept:
            recovery_elapsed = (now - last_slept).total_seconds() / 3600.0
            energy = min(100, int(energy + recovery_elapsed * 8))
        elif last_played:
            recovery_elapsed = (now - last_played).total_seconds() / 3600.0
            energy = min(100, int(energy + recovery_elapsed * 5))
        if recovery_elapsed is not None:
            cursor.execute(
                "UPDATE pets SET hunger=%s, happiness=%s, energy=%s, updated_at=NOW() WHERE username=%s",
                (hunger, happiness, energy, username)
            )
            conn.commit()
    cursor.execute(
        "SELECT action, detail, created_at FROM pet_logs WHERE username=%s ORDER BY created_at DESC LIMIT 10",
        (username,)
    )
    logs = [{"action": l[0], "detail": l[1], "created_at": l[2].strftime("%m-%d %H:%M") if l[2] else ""} for l in cursor.fetchall()]
    cursor.execute("SELECT achievement_key FROM pet_achievements WHERE username=%s", (username,))
    achievements = [r[0] for r in cursor.fetchall()]
    cursor.execute("SELECT item_key FROM pet_inventory WHERE username=%s AND item_type='accessory'", (username,))
    owned_accessories = [r[0] for r in cursor.fetchall()]
    cursor.close(); conn.close()
    pet_type = row[3]
    evo = _get_evolution(pet_type, level)
    dialogue = _get_dialogue(hunger, happiness, energy, personality)
    try:
        accessories_list = json.loads(accessories_str) if accessories_str else []
    except (json.JSONDecodeError, TypeError):
        accessories_list = []
    return jsonify({
        "has_pet": True,
        "pet": {
            "pet_name": row[2],
            "pet_type": pet_type,
            "hunger": max(0, min(100, hunger)),
            "happiness": max(0, min(100, happiness)),
            "energy": max(0, min(100, energy)),
            "level": max(1, level),
            "xp": max(0, min(99, xp)),
            "hatched": bool(hatched),
            "personality": personality or "",
            "evolution_stage": evolution_stage,
            "evolution": {"stage": evo["stage"], "emoji": evo["emoji"], "name": evo["name"]},
            "coins": max(0, coins_val),
            "mood": mood,
            "accessories": accessories_list,
            "owned_accessories": owned_accessories,
            "visit_count": visit_count,
            "dialogue": dialogue,
            "achievements": achievements,
        },
        "logs": logs
    })


@app.route("/api/pet/dialogue")
@login_required
def api_pet_dialogue():
    """获取一句宠物对话"""
    username = session["username"]
    _init_pet_tables()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT hunger, happiness, energy, personality FROM pets WHERE username=%s", (username,))
    row = cursor.fetchone()
    cursor.close(); conn.close()
    if not row:
        return jsonify({"dialogue": "你还没有宠物哦~"})
    hunger, happiness, energy = row[0] or 100, row[1] or 100, row[2] or 100
    personality = row[3]
    return jsonify({"dialogue": _get_dialogue(hunger, happiness, energy, personality)})


@app.route("/api/pet/action", methods=["POST"])
@login_required
def api_pet_action_v2():
    username = session["username"]
    _init_pet_tables()
    data = request.get_json() or {}
    action = sanitize_input(data.get("action", ""), 10)
    valid_actions = {"feed": "喂食", "play": "玩耍", "sleep": "睡觉"}
    if action not in valid_actions:
        return jsonify({"ok": False, "error": "无效的动作"}), 400
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pets WHERE username=%s", (username,))
    row = cursor.fetchone()
    if not row:
        cursor.close(); conn.close()
        return jsonify({"ok": False, "error": "你还没有宠物"}), 400
    hunger = row[4]; happiness = row[5]; energy = row[6]
    level = row[7]; xp = row[8]
    personality = row[14] if len(row) > 14 else None
    evolution_stage = row[15] if len(row) > 15 else 0
    coins_val = row[16] if len(row) > 16 else 0
    action_count = (row[19] or 0) if len(row) > 19 else 0
    feed_count = (row[20] or 0) if len(row) > 20 else 0
    play_count = (row[21] or 0) if len(row) > 21 else 0
    sleep_count = (row[22] or 0) if len(row) > 22 else 0
    now = datetime.utcnow()
    if action == "feed":
        if hunger >= 95:
            cursor.close(); conn.close()
            return jsonify({"ok": False, "error": "宠物已经吃饱了！"})
        hunger = min(100, hunger + 30)
        happiness = min(100, happiness + 5)
        feed_count += 1
        cursor.execute("UPDATE pets SET hunger=%s, happiness=%s, last_fed=NOW(), feed_count=%s, updated_at=NOW() WHERE username=%s",
                       (hunger, happiness, feed_count, username))
    elif action == "play":
        if energy < 10:
            cursor.close(); conn.close()
            return jsonify({"ok": False, "error": "宠物太累了，让它休息吧！"})
        if happiness >= 95:
            cursor.close(); conn.close()
            return jsonify({"ok": False, "error": "宠物已经玩够了！"})
        happiness = min(100, happiness + 30)
        hunger = max(0, hunger - 10)
        energy = max(0, energy - 15)
        play_count += 1
        cursor.execute("UPDATE pets SET happiness=%s, hunger=%s, energy=%s, last_played=NOW(), play_count=%s, updated_at=NOW() WHERE username=%s",
                       (happiness, hunger, energy, play_count, username))
    elif action == "sleep":
        if energy >= 95:
            cursor.close(); conn.close()
            return jsonify({"ok": False, "error": "宠物还不困！"})
        energy = min(100, energy + 40)
        sleep_count += 1
        cursor.execute("UPDATE pets SET energy=%s, sleep_count=%s, last_slept=NOW(), updated_at=NOW() WHERE username=%s",
                       (energy, sleep_count, username))
    xp += 10
    level_up = False
    while xp >= 100:
        level += 1
        xp -= 100
        level_up = True
    level = max(1, level)
    xp = max(0, xp)

    # 检查进化
    old_evolution_stage = evolution_stage
    evolution_stage = _get_evolution_stage(row[3], level)
    evolution_triggered = evolution_stage > old_evolution_stage

    # 硬币奖励
    coins_val += 1

    # 检查性格
    action_count += 1
    new_personality = _calc_personality(feed_count, play_count, sleep_count)

    cursor.execute(
        "UPDATE pets SET xp=%s, level=%s, evolution_stage=%s, coins=%s, action_count=%s, personality=%s WHERE username=%s",
        (xp, level, evolution_stage, coins_val, action_count, new_personality or personality, username)
    )
    conn.commit()

    # 写日记
    if level_up:
        cursor.execute(
            "INSERT INTO pet_diary (username, event_type, detail) VALUES (%s,%s,%s)",
            (username, "level_up", f"升到 Lv.{level}！")
        )
    if evolution_triggered:
        evo = _get_evolution(row[3], level)
        cursor.execute(
            "INSERT INTO pet_diary (username, event_type, detail) VALUES (%s,%s,%s)",
            (username, "evolution", f"进化成{evo['emoji']} {evo['name']}！")
        )
    cursor.execute(
        "INSERT INTO pet_logs (username, action, detail) VALUES (%s,%s,%s)",
        (username, action, f"执行了{valid_actions[action]}")
    )
    conn.commit()

    # 检查成就
    new_achievements = _check_achievements(username, conn)

    cursor.close(); conn.close()
    return jsonify({
        "ok": True,
        "level_up": level_up,
        "evolution": evolution_triggered,
        "evolution_info": _get_evolution(row[3], level) if evolution_triggered else None,
        "coins_earned": 1,
        "new_achievements": [ACHIEVEMENTS.get(k, {"name": k, "icon": "🏆"}) for k in new_achievements],
        "personality": new_personality,
    })


# ==============================================================
#  宠物 2.0：装扮 API
# ==============================================================

@app.route("/api/pet/shop")
@login_required
def api_pet_shop():
    """
    获取宠物装扮商店列表（URL: /api/pet/shop, GET）。

    权限：需要登录
    功能：返回所有可购买的装扮、用户当前硬币数、已拥有和已装备的物品。
    """
    """装扮商店列表"""
    username = session["username"]
    _init_pet_tables()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT item_key FROM pet_inventory WHERE username=%s AND item_type='accessory'", (username,))
    owned = set(r[0] for r in cursor.fetchall())
    cursor.execute("SELECT accessories, coins FROM pets WHERE username=%s", (username,))
    row = cursor.fetchone()
    cursor.close(); conn.close()
    coins = row[1] if row else 0
    try:
        equipped = json.loads(row[0]) if row and row[0] else []
    except (json.JSONDecodeError, TypeError):
        equipped = []
    items = []
    for key, info in ACCESSORY_SHOP.items():
        items.append({
            "key": key,
            "name": info["name"],
            "emoji": info["emoji"],
            "cost": info["cost"],
            "owned": key in owned,
            "equipped": key in equipped,
        })
    return jsonify({"items": items, "coins": coins, "equipped": equipped})


@app.route("/api/pet/shop/buy", methods=["POST"])
@login_required
def api_pet_shop_buy():
    """购买装扮"""
    username = session["username"]
    _init_pet_tables()
    data = request.get_json() or {}
    item_key = sanitize_input(data.get("item_key", ""), 50)
    if item_key not in ACCESSORY_SHOP:
        return jsonify({"ok": False, "error": "商品不存在"}), 400
    item = ACCESSORY_SHOP[item_key]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT coins FROM pets WHERE username=%s", (username,))
    row = cursor.fetchone()
    if not row:
        cursor.close(); conn.close()
        return jsonify({"ok": False, "error": "你还没有宠物"}), 400
    coins = row[0] or 0
    if coins < item["cost"]:
        cursor.close(); conn.close()
        return jsonify({"ok": False, "error": f"硬币不足！需要{item['cost']}枚，你只有{coins}枚"}), 400
    cursor.execute("SELECT id FROM pet_inventory WHERE username=%s AND item_key=%s", (username, item_key))
    if cursor.fetchone():
        cursor.close(); conn.close()
        return jsonify({"ok": False, "error": "你已经拥有这个装扮了"}), 400
    cursor.execute("UPDATE pets SET coins = coins - %s WHERE username=%s", (item["cost"], username))
    cursor.execute(
        "INSERT INTO pet_inventory (username, item_type, item_key) VALUES (%s,%s,%s)",
        (username, "accessory", item_key)
    )
    cursor.execute(
        "INSERT INTO pet_diary (username, event_type, detail) VALUES (%s,%s,%s)",
        (username, "shop", f"购买了{item['emoji']} {item['name']}")
    )
    conn.commit()
    cursor.close(); conn.close()
    # 检查成就
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT coins FROM pets WHERE username=%s", (username,))
    coins_now = cursor.fetchone()[0]
    cursor.close(); conn.close()
    _check_achievements(username)
    return jsonify({"ok": True, "coins_left": coins_now})


@app.route("/api/pet/accessory/equip", methods=["POST"])
@login_required
def api_pet_accessory_equip():
    """装备/卸下装扮"""
    username = session["username"]
    _init_pet_tables()
    data = request.get_json() or {}
    item_key = sanitize_input(data.get("item_key", ""), 50)
    equip = data.get("equip", True)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT accessories FROM pets WHERE username=%s", (username,))
    row = cursor.fetchone()
    if not row:
        cursor.close(); conn.close()
        return jsonify({"ok": False, "error": "你还没有宠物"}), 400
    try:
        acc = json.loads(row[0]) if row[0] else []
    except (json.JSONDecodeError, TypeError):
        acc = []
    if equip:
        if item_key not in acc:
            acc.append(item_key)
    else:
        if item_key in acc:
            acc.remove(item_key)
    cursor.execute("UPDATE pets SET accessories=%s WHERE username=%s", (json.dumps(acc), username))
    conn.commit()
    cursor.close(); conn.close()
    return jsonify({"ok": True, "equipped": acc})


# ==============================================================
#  宠物 2.0：社交 API
# ==============================================================

@app.route("/api/pet/community")
@login_required
def api_pet_community():
    """
    获取宠物社区列表（URL: /api/pet/community, GET）。

    权限：需要登录
    功能：返回所有用户的宠物列表，按等级和硬币数排序。
    """
    """宠物社区：所有用户的宠物列表 + 排行榜"""
    _init_pet_tables()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.username, p.pet_name, p.pet_type, p.level, p.hunger, p.happiness,
               p.energy, p.evolution_stage, p.coins, p.personality, p.visit_count, p.action_count
        FROM pets p
        INNER JOIN users u ON p.username = u.user_name
        WHERE p.hatched = 1
        ORDER BY p.level DESC, p.coins DESC
        LIMIT 50
    """)
    rows = cursor.fetchall()
    cursor.close(); conn.close()
    pets = []
    for r in rows:
        username2 = r[0]
        pet_type = r[2]; level = r[3]
        evo = _get_evolution(pet_type, level)
        pets.append({
            "username": username2,
            "pet_name": r[1],
            "pet_type": pet_type,
            "level": level,
            "hunger": r[4],
            "happiness": r[5],
            "energy": r[6],
            "evolution_emoji": evo["emoji"],
            "evolution_name": evo["name"],
            "coins": r[8],
            "personality": r[9] or "",
            "visit_count": r[10],
            "action_count": r[11],
        })
    return jsonify({"pets": pets})


@app.route("/api/pet/visit/<host_username>")
@login_required
def api_pet_visit(host_username):
    """访问别人的宠物"""
    visitor = session["username"]
    host = sanitize_input(host_username, 50)
    if host == visitor:
        return jsonify({"ok": False, "error": "这是你自己的宠物！去宠物页面看看吧~"}), 400
    _init_pet_tables()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.* FROM pets p
        INNER JOIN users u ON p.username = u.user_name
        WHERE p.username=%s AND p.hatched=1
    """, (host,))
    row = cursor.fetchone()
    if not row:
        cursor.close(); conn.close()
        return jsonify({"ok": False, "error": "该用户还没有宠物"}), 404
    pet_type = row[3]; level = row[7]
    evo = _get_evolution(pet_type, level)
    try:
        acc = json.loads(row[18]) if len(row) > 18 and row[18] else []
    except (json.JSONDecodeError, TypeError):
        acc = []
    # 记录访问
    cursor.execute(
        "INSERT INTO pet_visits (visitor, host, message) VALUES (%s,%s,%s)",
        (visitor, host, f"{visitor} 来串门啦！")
    )
    # 增加被访问次数
    cursor.execute("UPDATE pets SET visit_count = visit_count + 1 WHERE username=%s", (host,))
    conn.commit()
    # 写日记
    cursor.execute(
        "INSERT INTO pet_diary (username, event_type, detail) VALUES (%s,%s,%s)",
        (host, "visit", f"{visitor} 来串门了！")
    )
    conn.commit()
    # 最近来访
    cursor.execute(
        "SELECT visitor, message, created_at FROM pet_visits WHERE host=%s ORDER BY created_at DESC LIMIT 5",
        (host,)
    )
    recent_visits = [{"visitor": v[0], "message": v[1], "time": v[2].strftime("%m-%d %H:%M") if v[2] else ""} for v in cursor.fetchall()]
    cursor.close(); conn.close()
    # 检查主人成就
    _check_achievements(host)
    return jsonify({
        "ok": True,
        "pet": {
            "pet_name": row[2],
            "pet_type": pet_type,
            "level": level,
            "hunger": row[4],
            "happiness": row[5],
            "energy": row[6],
            "evolution_emoji": evo["emoji"],
            "evolution_name": evo["name"],
            "personality": (row[14] if len(row) > 14 else None) or "",
            "coins": row[16] if len(row) > 16 else 0,
            "accessories": acc,
            "visit_count": row[19] if len(row) > 19 else 0,
        },
        "recent_visits": recent_visits
    })


@app.route("/api/pet/gift", methods=["POST"])
@login_required
def api_pet_gift():
    """赠送礼物给别人的宠物"""
    sender = session["username"]
    _init_pet_tables()
    data = request.get_json() or {}
    receiver = sanitize_input(data.get("receiver", ""), 50)
    item_key = sanitize_input(data.get("item_key", ""), 50)
    message = sanitize_input(data.get("message", ""), 200)
    if not receiver or not item_key:
        return jsonify({"ok": False, "error": "参数不完整"}), 400
    if receiver == sender:
        return jsonify({"ok": False, "error": "不能送给自己！"}), 400
    conn = get_db()
    cursor = conn.cursor()
    # 特殊礼物：硬币
    if item_key == "coins":
        amount = data.get("amount", 10)
        amount = max(1, min(100, int(amount)))
        cursor.execute("SELECT coins FROM pets WHERE username=%s", (sender,))
        row = cursor.fetchone()
        if not row or row[0] < amount:
            cursor.close(); conn.close()
            return jsonify({"ok": False, "error": "硬币不足！"}), 400
        cursor.execute("UPDATE pets SET coins = coins - %s WHERE username=%s", (amount, sender))
        cursor.execute("UPDATE pets SET coins = coins + %s WHERE username=%s", (amount, receiver))
        cursor.execute(
            "INSERT INTO pet_gifts (sender, receiver, item_key, message) VALUES (%s,%s,%s,%s)",
            (sender, receiver, f"coins_{amount}", message or f"送了你{amount}枚硬币！")
        )
    else:
        # 送装扮
        if item_key not in ACCESSORY_SHOP:
            cursor.close(); conn.close()
            return jsonify({"ok": False, "error": "物品不存在"}), 400
        cursor.execute("SELECT id FROM pet_inventory WHERE username=%s AND item_key=%s", (sender, item_key))
        if not cursor.fetchone():
            cursor.close(); conn.close()
            return jsonify({"ok": False, "error": "你没有这个物品！"}), 400
        cursor.execute("DELETE FROM pet_inventory WHERE username=%s AND item_key=%s LIMIT 1", (sender, item_key))
        cursor.execute(
            "INSERT INTO pet_inventory (username, item_type, item_key) VALUES (%s,%s,%s)",
            (receiver, "accessory", item_key)
        )
        cursor.execute(
            "INSERT INTO pet_gifts (sender, receiver, item_key, message) VALUES (%s,%s,%s,%s)",
            (sender, receiver, item_key, message or "送你一个小礼物！")
        )
        item = ACCESSORY_SHOP[item_key]
        cursor.execute(
            "INSERT INTO pet_diary (username, event_type, detail) VALUES (%s,%s,%s)",
            (receiver, "gift", f"{sender} 送了{item['emoji']} {item['name']}！")
        )
    conn.commit()
    cursor.close(); conn.close()
    return jsonify({"ok": True})


# ==============================================================
#  宠物 2.0：小游戏 API
# ==============================================================

@app.route("/api/pet/game/score", methods=["POST"])
@login_required
def api_pet_game_score():
    """小游戏提交分数，兑换硬币"""
    username = session["username"]
    _init_pet_tables()
    data = request.get_json() or {}
    score = data.get("score", 0)
    score = max(0, min(99999, int(score)))
    coins_earned = max(1, score // 10)  # 每10分换1硬币
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM pets WHERE username=%s", (username,))
    if not cursor.fetchone():
        cursor.close(); conn.close()
        return jsonify({"ok": False, "error": "你还没有宠物"}), 400
    cursor.execute("UPDATE pets SET coins = coins + %s WHERE username=%s", (coins_earned, username))
    cursor.execute(
        "INSERT INTO pet_diary (username, event_type, detail) VALUES (%s,%s,%s)",
        (username, "game", f"小游戏得分{score}，赚了{coins_earned}硬币！")
    )
    conn.commit()
    cursor.execute("SELECT coins FROM pets WHERE username=%s", (username,))
    total_coins = cursor.fetchone()[0]
    cursor.close(); conn.close()
    _check_achievements(username)
    return jsonify({"ok": True, "coins_earned": coins_earned, "total_coins": total_coins})


# ==============================================================
#  宠物 2.0：日记 API
# ==============================================================

@app.route("/api/pet/diary")
@login_required
def api_pet_diary():
    """
    获取宠物日记（URL: /api/pet/diary, GET）。

    权限：需要登录
    功能：返回最近 30 条宠物日记条目（升级/进化/串门/成就等事件）。
    """
    """宠物日记"""
    username = session["username"]
    _init_pet_tables()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT event_type, detail, created_at FROM pet_diary WHERE username=%s ORDER BY created_at DESC LIMIT 30",
        (username,)
    )
    entries = []
    for r in cursor.fetchall():
        entries.append({
            "event_type": r[0],
            "detail": r[1],
            "time": r[2].strftime("%m-%d %H:%M") if r[2] else "",
        })
    cursor.close(); conn.close()
    return jsonify({"entries": entries})


# ==============================================================
#  宠物 2.0：成就列表 API
# ==============================================================

@app.route("/api/pet/achievements/list")
@login_required
def api_pet_achievements_list():
    """获取所有成就及解锁状态"""
    username = session["username"]
    _init_pet_tables()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT achievement_key FROM pet_achievements WHERE username=%s", (username,))
    unlocked = set(r[0] for r in cursor.fetchall())
    cursor.close(); conn.close()
    all_ach = []
    for key, info in ACHIEVEMENTS.items():
        all_ach.append({
            "key": key,
            "name": info["name"],
            "desc": info["desc"],
            "icon": info["icon"],
            "unlocked": key in unlocked,
        })
    return jsonify({"achievements": all_ach})


def _log_activity_local(username, action, points):
    try:
        ac = get_db()
        if ac:
            acu = ac.cursor()
            acu.execute("INSERT INTO activity_log (username, action, points) VALUES (%s,%s,%s)", (username, action, points))
            ac.commit(); acu.close(); ac.close()
    except Exception:
        pass


# ==============================================================
#  仪表盘公告栏 API
# ==============================================================

@app.route("/api/announcements", methods=["GET"])
@login_required
def api_announcements_list():
    """获取所有活跃公告（所有登录用户可见）"""
    _init_announcement_table()
    conn = get_db()
    if not conn:
        return jsonify({"announcements": []})
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, content, created_by, created_at
            FROM dashboard_announcements
            WHERE is_active=1
            ORDER BY created_at DESC
        """)
        rows = cursor.fetchall()
        cursor.close(); conn.close()
        announcements = [{"id": r[0], "content": r[1], "created_by": r[2], "created_at": str(r[3])} for r in rows]
        return jsonify({"announcements": announcements})
    except Exception:
        return jsonify({"announcements": []})


@app.route("/api/announcements", methods=["POST"])
@login_required
def api_announcements_create():
    """发布公告（仅管理员）"""
    if session.get("permission") != "administrator":
        return jsonify({"ok": False, "error": "仅管理员可操作"}), 403
    data = request.get_json() or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"ok": False, "error": "公告内容不能为空"}), 400
    _init_announcement_table()
    conn = get_db()
    if not conn:
        return jsonify({"ok": False, "error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO dashboard_announcements (content, created_by) VALUES (%s, %s)",
            (content, session["username"])
        )
        conn.commit()
        new_id = cursor.lastrowid
        cursor.close(); conn.close()
        return jsonify({"ok": True, "id": new_id})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/announcements/<int:aid>", methods=["DELETE"])
@login_required
def api_announcements_delete(aid):
    """删除公告（仅管理员）——软删除（is_active=0）"""
    if session.get("permission") != "administrator":
        return jsonify({"ok": False, "error": "仅管理员可操作"}), 403
    _init_announcement_table()
    conn = get_db()
    if not conn:
        return jsonify({"ok": False, "error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE dashboard_announcements SET is_active=0 WHERE id=%s", (aid,))
        conn.commit(); cursor.close(); conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ==============================================================
# ====== 投诉建议箱 ======
# ==============================================================

@app.route("/api/complaint/submit", methods=["POST"])
@login_required
def api_complaint_submit():
    """提交投诉建议"""
    _init_complaints_table()
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    content = (data.get("content") or "").strip()
    if not title or not content:
        return jsonify({"ok": False, "error": "标题和内容不能为空"}), 400
    if len(title) > 200:
        return jsonify({"ok": False, "error": "标题不能超过200字"}), 400
    if len(content) > 5000:
        return jsonify({"ok": False, "error": "内容不能超过5000字"}), 400
    conn = get_db()
    if not conn:
        return jsonify({"ok": False, "error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO complaints (username, title, content) VALUES (%s, %s, %s)",
            (session["username"], title, content)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"ok": True, "message": "投诉已提交，管理员将尽快处理"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/complaint/list", methods=["GET"])
@login_required
def api_complaint_list():
    """查看投诉列表（仅管理员）"""
    if session.get("permission") != "administrator":
        return jsonify({"ok": False, "error": "仅管理员可查看"}), 403
    _init_complaints_table()
    conn = get_db()
    if not conn:
        return jsonify({"ok": False, "error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute(
            "SELECT id, username, title, content, is_read, reply, status, created_at "
            "FROM complaints ORDER BY created_at DESC"
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        for r in rows:
            r["created_at"] = str(r["created_at"]) if r["created_at"] else ""
        return jsonify({"ok": True, "complaints": rows, "total": len(rows)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/complaint/my", methods=["GET"])
@login_required
def api_complaint_my():
    """查看自己的投诉及管理员回复"""
    _init_complaints_table()
    conn = get_db()
    if not conn:
        return jsonify({"ok": False, "error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute(
            "SELECT id, title, content, is_read, reply, status, created_at "
            "FROM complaints WHERE username=%s ORDER BY created_at DESC",
            (session["username"],)
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        for r in rows:
            r["created_at"] = str(r["created_at"]) if r["created_at"] else ""
        return jsonify({"ok": True, "complaints": rows, "total": len(rows)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/complaint/read/<int:cid>", methods=["POST"])
@login_required
def api_complaint_mark_read(cid):
    """标记投诉为已读（仅管理员）"""
    if session.get("permission") != "administrator":
        return jsonify({"ok": False, "error": "仅管理员可操作"}), 403
    conn = get_db()
    if not conn:
        return jsonify({"ok": False, "error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE complaints SET is_read=1 WHERE id=%s", (cid,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/complaint/delete/<int:cid>", methods=["DELETE"])
@login_required
def api_complaint_delete(cid):
    """删除投诉（仅管理员）"""
    if session.get("permission") != "administrator":
        return jsonify({"ok": False, "error": "仅管理员可操作"}), 403
    conn = get_db()
    if not conn:
        return jsonify({"ok": False, "error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM complaints WHERE id=%s", (cid,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"ok": True, "message": "已删除"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/complaint/reply/<int:cid>", methods=["POST"])
@login_required
def api_complaint_reply(cid):
    """回复投诉（仅管理员）"""
    if session.get("permission") != "administrator":
        return jsonify({"ok": False, "error": "仅管理员可操作"}), 403
    data = request.get_json(silent=True) or {}
    reply = (data.get("reply") or "").strip()
    if not reply:
        return jsonify({"ok": False, "error": "回复内容不能为空"}), 400
    conn = get_db()
    if not conn:
        return jsonify({"ok": False, "error": "数据库连接失败"}), 500
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE complaints SET reply=%s, status='replied' WHERE id=%s",
            (reply, cid)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"ok": True, "message": "回复成功"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ==============================================================
# ====== 匿名树洞 ======
# ==============================================================

@app.route("/confession")
@login_required
def confession_page():
    """
    匿名树洞页面（URL: /confession）。

    权限：需要登录
    功能：匿名发帖/回复/点赞，使用随机昵称保护隐私。
    """
    _init_confession_tables()
    return render_template("confession_wall.html", username=session.get("username", ""), permission=session.get("permission", "guest"))


@app.route("/api/confession/posts", methods=["GET", "POST"])
@login_required
def api_confession_posts():
    username = session["username"]
    conn = get_db()
    if request.method == "GET":
        page = request.args.get("page", 1, type=int)
        per_page = 15
        offset_val = (page - 1) * per_page
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM anonymous_posts")
        total = cursor.fetchone()[0]
        cursor.execute(
            "SELECT id, username, nickname, content, emoji, like_count, reply_count, created_at FROM anonymous_posts ORDER BY id DESC LIMIT %s OFFSET %s",
            (per_page, offset_val)
        )
        rows = cursor.fetchall()
        # Get replies
        post_ids = [r[0] for r in rows]
        replies_map = {}
        if post_ids:
            cursor.execute(
                "SELECT post_id, id, nickname, content, created_at FROM anonymous_replies WHERE post_id IN ({}) ORDER BY id ASC".format(
                    ','.join(['%s'] * len(post_ids))
                ), post_ids)
            for rr in cursor.fetchall():
                if rr[0] not in replies_map:
                    replies_map[rr[0]] = []
                replies_map[rr[0]].append({
                    "id": rr[1], "nickname": rr[2], "content": rr[3], "created_at": str(rr[4])
                })
        cursor.close()
        # Check user likes
        conn2 = get_db()
        cur2 = conn2.cursor()
        cur2.execute(
            "SELECT post_id FROM anonymous_likes WHERE username=%s AND post_id IN ({})".format(
                ','.join(['%s'] * len(post_ids)) if post_ids else '0'
            ),
            [username] + (post_ids if post_ids else [0])
        )
        liked_set = {r[0] for r in cur2.fetchall()}
        cur2.close(); conn2.close()

        posts = [{
            "id": r[0], "nickname": r[2], "content": r[3], "emoji": r[4],
            "like_count": r[5], "reply_count": r[6], "created_at": str(r[7]),
            "replies": replies_map.get(r[0], []),
            "liked": r[0] in liked_set,
            "is_owner": r[1] == username or session.get("permission") == "administrator"
        } for r in rows]
        conn.close()
        return jsonify({"posts": posts, "total": total, "has_more": offset_val + per_page < total})

    else:  # POST
        data = request.get_json() or {}
        content = sanitize_input(data.get("content", ""), 2000)
        if not content:
            conn.close()
            return jsonify({"error": "内容不能为空"}), 400
        emoji = data.get("emoji", "💬")
        nickname = data.get("nickname", generate_nickname())
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO anonymous_posts (username, nickname, content, emoji) VALUES (%s, %s, %s, %s)",
            (username, nickname, content, emoji)
        )
        conn.commit()
        pid = cursor.lastrowid
        cursor.close(); conn.close()
        return jsonify({"ok": True, "id": pid, "nickname": nickname})


@app.route("/api/confession/posts/<int:pid>/replies", methods=["GET", "POST"])
@login_required
def api_confession_replies(pid):
    conn = get_db()
    if request.method == "GET":
        cursor = conn.cursor()
        cursor.execute("SELECT id, nickname, content, created_at FROM anonymous_replies WHERE post_id=%s ORDER BY id ASC", (pid,))
        rows = cursor.fetchall()
        cursor.close(); conn.close()
        return jsonify({"replies": [{"id": r[0], "nickname": r[1], "content": r[2], "created_at": str(r[3])} for r in rows]})
    else:  # POST
        data = request.get_json() or {}
        content = sanitize_input(data.get("content", ""), 1000)
        if not content:
            conn.close()
            return jsonify({"error": "回复不能为空"}), 400
        nickname = data.get("nickname", generate_nickname())
        cursor = conn.cursor()
        cursor.execute("INSERT INTO anonymous_replies (post_id, nickname, content) VALUES (%s, %s, %s)", (pid, nickname, content))
        cursor.execute("UPDATE anonymous_posts SET reply_count = reply_count + 1 WHERE id=%s", (pid,))
        conn.commit()
        rid = cursor.lastrowid
        cursor.close(); conn.close()
        return jsonify({"ok": True, "id": rid, "nickname": nickname})


@app.route("/api/confession/posts/<int:pid>/like", methods=["POST"])
@login_required
def api_confession_like(pid):
    username = session["username"]
    conn = get_db()
    cursor = conn.cursor()
    # Toggle like
    cursor.execute("SELECT id FROM anonymous_likes WHERE post_id=%s AND username=%s", (pid, username))
    existing = cursor.fetchone()
    if existing:
        cursor.execute("DELETE FROM anonymous_likes WHERE id=%s", (existing[0],))
        cursor.execute("UPDATE anonymous_posts SET like_count = GREATEST(like_count - 1, 0) WHERE id=%s", (pid,))
        conn.commit()
        cursor.execute("SELECT like_count FROM anonymous_posts WHERE id=%s", (pid,))
        new_count = cursor.fetchone()[0]
        cursor.close(); conn.close()
        return jsonify({"liked": False, "like_count": new_count})
    else:
        cursor.execute("INSERT INTO anonymous_likes (post_id, username) VALUES (%s, %s)", (pid, username))
        cursor.execute("UPDATE anonymous_posts SET like_count = like_count + 1 WHERE id=%s", (pid,))
        conn.commit()
        cursor.execute("SELECT like_count FROM anonymous_posts WHERE id=%s", (pid,))
        new_count = cursor.fetchone()[0]
        cursor.close(); conn.close()
        return jsonify({"liked": True, "like_count": new_count})


@app.route("/api/confession/posts/<int:pid>", methods=["DELETE"])
@login_required
def api_confession_delete(pid):
    """删除树洞帖子：本人或管理员可删"""
    username = session["username"]
    is_admin = session.get("permission") == "administrator"
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM anonymous_posts WHERE id=%s", (pid,))
    row = cursor.fetchone()
    if not row:
        cursor.close(); conn.close()
        return jsonify({"error": "帖子不存在"}), 404
    if not is_admin and row[0] != username:
        cursor.close(); conn.close()
        return jsonify({"error": "无权删除此帖子"}), 403
    # 删除关联的回复和点赞
    cursor.execute("DELETE FROM anonymous_replies WHERE post_id=%s", (pid,))
    cursor.execute("DELETE FROM anonymous_likes WHERE post_id=%s", (pid,))
    cursor.execute("DELETE FROM anonymous_posts WHERE id=%s", (pid,))
    conn.commit()
    cursor.close(); conn.close()
    return jsonify({"ok": True})


# ---- 随机昵称生成 ----
def generate_nickname():
    """
    生成随机匿名昵称（形容词 + 名词）。

    用于匿名树洞帖子，每次生成不同组合。

    Returns:
        str: 如 "快乐的小树"
    """
    adjectives = ["快乐的","安静的","勇敢的","温柔的","调皮的","可爱的","酷酷的","暖暖的","潇洒的","憨憨的"]
    nouns = ["小树","星星","月亮","微风","小雨","阳光","猫咪","兔子","熊猫","海豚"]
    return random.choice(adjectives) + random.choice(nouns)


# ==============================================================
# ====== 校友社区论坛 ======
# ==============================================================

@app.route("/forum")
@login_required
def forum_page():
    """
    校友社区论坛首页（URL: /forum）。

    权限：需要登录
    功能：展示各版块最新帖子，支持发帖/回复/点赞/通知。
    """
    _init_forum_tables()
    return render_template("forum.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

# ---- 版块 ----
@app.route("/api/forum/categories")
@login_required
def api_forum_categories():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, icon, description, sort_order FROM forum_categories ORDER BY sort_order")
    rows = cursor.fetchall()
    cursor.close(); conn.close()
    cats = [{"id": r[0], "name": r[1], "icon": r[2], "description": r[3], "sort_order": r[4]} for r in rows]
    # 统计每个版块的帖子数
    conn2 = get_db()
    cur2 = conn2.cursor()
    cur2.execute("SELECT category_id, COUNT(*) FROM forum_posts GROUP BY category_id")
    counts = dict(cur2.fetchall())
    cur2.close(); conn2.close()
    for cat in cats:
        cat["post_count"] = counts.get(cat["id"], 0)
    return jsonify({"categories": cats})

# ---- 帖子列表 ----
@app.route("/api/forum/posts", methods=["GET", "POST"])
@login_required
def api_forum_posts():
    username = session["username"]
    permission = session.get("permission", "guest")
    conn = get_db()

    if request.method == "GET":
        cat_id = request.args.get("category_id", type=int)
        page = request.args.get("page", 1, type=int)
        per_page = 15
        offset_val = (page - 1) * per_page
        keyword = request.args.get("keyword", "").strip()

        cursor = conn.cursor()
        where = "WHERE 1=1"
        params = []

        if cat_id:
            where += " AND p.category_id=%s"
            params.append(cat_id)
        if keyword:
            where += " AND (p.title LIKE %s OR p.content LIKE %s)"
            params.extend([f"%{keyword}%", f"%{keyword}%"])

        # 总数
        cursor.execute(f"SELECT COUNT(*) FROM forum_posts p {where}", params)
        total = cursor.fetchone()[0]
        total_pages = max(1, (total + per_page - 1) // per_page) if total > 0 else 1

        # 分页查询（置顶优先，按时间倒序）
        order = "ORDER BY p.is_pinned DESC, p.created_at DESC"
        cursor.execute(
            f"SELECT p.id, p.category_id, p.username, p.title, p.content, p.is_pinned, p.is_locked, "
            f"p.view_count, p.reply_count, p.like_count, p.created_at "
            f"FROM forum_posts p {where} {order} LIMIT %s OFFSET %s",
            params + [per_page, offset_val]
        )
        rows = cursor.fetchall()
        posts = []
        for r in rows:
            posts.append({
                "id": r[0], "category_id": r[1], "username": r[2], "title": r[3],
                "content": r[4][:200], "is_pinned": bool(r[5]), "is_locked": bool(r[6]),
                "view_count": r[7], "reply_count": r[8], "like_count": r[9],
                "created_at": str(r[10]),
            })
        cursor.close(); conn.close()
        return jsonify({"posts": posts, "total": total, "page": page, "total_pages": total_pages})

    else:  # POST — 发帖
        data = request.get_json() or {}
        title = data.get("title", "").strip()
        content = data.get("content", "").strip()
        cat_id = data.get("category_id", 0)
        if not title or not content or not cat_id:
            return jsonify({"ok": False, "error": "标题、内容和版块不能为空"}), 400
        if len(title) > 200:
            return jsonify({"ok": False, "error": "标题不能超过200字"}), 400
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO forum_posts (category_id, username, title, content) VALUES (%s,%s,%s,%s)",
            (cat_id, username, title, content)
        )
        conn.commit()
        pid = cursor.lastrowid
        cursor.close(); conn.close()
        # 记活跃分
        try:
            ac = get_db()
            if ac:
                acu = ac.cursor()
                acu.execute("INSERT INTO activity_log (username, action, points) VALUES (%s,%s,%s)", (username, "forum_post", 5))
                ac.commit(); acu.close(); ac.close()
        except Exception:
            pass
        return jsonify({"ok": True, "id": pid})

# ---- 帖子详情 ----
@app.route("/api/forum/posts/<int:pid>", methods=["GET", "PUT", "DELETE"])
@login_required
def api_forum_post_item(pid):
    username = session["username"]
    permission = session.get("permission", "guest")
    conn = get_db()

    if request.method == "GET":
        cursor = conn.cursor()
        cursor.execute(
            "SELECT p.id, p.category_id, p.username, p.title, p.content, p.is_pinned, p.is_locked, "
            "p.view_count, p.reply_count, p.like_count, p.created_at, "
            "c.name as cat_name, c.icon as cat_icon "
            "FROM forum_posts p JOIN forum_categories c ON p.category_id=c.id "
            "WHERE p.id=%s", (pid,)
        )
        r = cursor.fetchone()
        if not r:
            cursor.close(); conn.close()
            return jsonify({"ok": False, "error": "帖子不存在"}), 404
        post = {
            "id": r[0], "category_id": r[1], "username": r[2], "title": r[3],
            "content": r[4], "is_pinned": bool(r[5]), "is_locked": bool(r[6]),
            "view_count": r[7], "reply_count": r[8], "like_count": r[9],
            "created_at": str(r[10]), "cat_name": r[11], "cat_icon": r[12],
        }
        # 当前用户是否已点赞
        cursor.execute("SELECT 1 FROM forum_likes WHERE username=%s AND target_type='post' AND target_id=%s", (username, pid))
        post["liked"] = cursor.fetchone() is not None

        # 更新浏览量（同一会话内不重复计数）
        viewed_key = f"_viewed_{pid}"
        if not session.get(viewed_key):
            cursor.execute("UPDATE forum_posts SET view_count = view_count + 1 WHERE id=%s", (pid,))
            conn.commit()
            session[viewed_key] = True
            post["view_count"] += 1

        # 回复列表
        cursor.execute(
            "SELECT r.id, r.username, r.content, r.like_count, r.created_at FROM forum_replies r WHERE r.post_id=%s ORDER BY r.created_at ASC",
            (pid,)
        )
        replies = []
        for r2 in cursor.fetchall():
            # 每个回复的点赞状态
            cursor.execute("SELECT 1 FROM forum_likes WHERE username=%s AND target_type='reply' AND target_id=%s", (username, r2[0]))
            replies.append({
                "id": r2[0], "username": r2[1], "content": r2[2], "like_count": r2[3],
                "created_at": str(r2[4]),
                "liked": cursor.fetchone() is not None,
            })
        post["replies"] = replies
        cursor.close(); conn.close()
        return jsonify({"post": post})

    elif request.method == "PUT":  # 编辑
        data = request.get_json() or {}
        cursor = conn.cursor()
        if permission == "administrator":
            cursor.execute("UPDATE forum_posts SET title=%s, content=%s, category_id=%s WHERE id=%s",
                           (data.get("title"), data.get("content"), data.get("category_id", 0), pid))
        else:
            cursor.execute("UPDATE forum_posts SET title=%s, content=%s WHERE id=%s AND username=%s",
                           (data.get("title"), data.get("content"), pid, username))
        conn.commit()
        affected = cursor.rowcount
        cursor.close(); conn.close()
        if affected == 0:
            return jsonify({"ok": False, "error": "无权限或帖子不存在"}), 403
        return jsonify({"ok": True})

    else:  # DELETE
        cursor = conn.cursor()
        if permission == "administrator":
            cursor.execute("DELETE FROM forum_posts WHERE id=%s", (pid,))
        else:
            cursor.execute("DELETE FROM forum_posts WHERE id=%s AND username=%s", (pid, username))
        affected = cursor.rowcount
        if affected > 0:
            cursor.execute("DELETE FROM forum_replies WHERE post_id=%s", (pid,))
            cursor.execute("DELETE FROM forum_likes WHERE target_type='post' AND target_id=%s", (pid,))
        conn.commit()
        cursor.close(); conn.close()
        if affected == 0:
            return jsonify({"ok": False, "error": "无权限或帖子不存在"}), 403
        return jsonify({"ok": True})

# ---- 置顶/取消置顶 ----
@app.route("/api/forum/posts/<int:pid>/pin", methods=["POST"])
@login_required
def api_forum_post_pin(pid):
    if session.get("permission") != "administrator":
        return jsonify({"ok": False, "error": "仅管理员可操作"}), 403
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT is_pinned FROM forum_posts WHERE id=%s", (pid,))
    r = cursor.fetchone()
    if not r:
        cursor.close(); conn.close()
        return jsonify({"ok": False, "error": "帖子不存在"}), 404
    new_val = 0 if r[0] else 1
    cursor.execute("UPDATE forum_posts SET is_pinned=%s WHERE id=%s", (new_val, pid))
    conn.commit(); cursor.close(); conn.close()
    return jsonify({"ok": True, "is_pinned": bool(new_val)})

# ---- 锁定/解锁 ----
@app.route("/api/forum/posts/<int:pid>/lock", methods=["POST"])
@login_required
def api_forum_post_lock(pid):
    if session.get("permission") != "administrator":
        return jsonify({"ok": False, "error": "仅管理员可操作"}), 403
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT is_locked FROM forum_posts WHERE id=%s", (pid,))
    r = cursor.fetchone()
    if not r:
        cursor.close(); conn.close()
        return jsonify({"ok": False, "error": "帖子不存在"}), 404
    new_val = 0 if r[0] else 1
    cursor.execute("UPDATE forum_posts SET is_locked=%s WHERE id=%s", (new_val, pid))
    conn.commit(); cursor.close(); conn.close()
    return jsonify({"ok": True, "is_locked": bool(new_val)})

# ---- 回帖 ----
@app.route("/api/forum/replies", methods=["POST"])
@login_required
def api_forum_reply():
    username = session["username"]
    data = request.get_json() or {}
    post_id = data.get("post_id")
    content = data.get("content", "").strip()
    if not post_id or not content:
        return jsonify({"ok": False, "error": "内容不能为空"}), 400

    conn = get_db()
    cursor = conn.cursor()
    # 检查是否锁定
    cursor.execute("SELECT is_locked, username, title FROM forum_posts WHERE id=%s", (post_id,))
    post = cursor.fetchone()
    if not post:
        cursor.close(); conn.close()
        return jsonify({"ok": False, "error": "帖子不存在"}), 404
    if post[0] and session.get("permission") != "administrator":
        cursor.close(); conn.close()
        return jsonify({"ok": False, "error": "帖子已锁定，无法回复"}), 403

    cursor.execute("INSERT INTO forum_replies (post_id, username, content) VALUES (%s,%s,%s)",
                   (post_id, username, content))
    cursor.execute("UPDATE forum_posts SET reply_count = reply_count + 1 WHERE id=%s", (post_id,))
    conn.commit()
    rid = cursor.lastrowid

    # 通知帖主（不通知自己）
    if post[1] != username:
        cursor.execute(
            "INSERT INTO forum_notifications (username, type, post_id, post_title, from_user, content_preview) VALUES (%s,%s,%s,%s,%s,%s)",
            (post[1], "reply", post_id, post[2], username, content[:80])
        )
    conn.commit()
    cursor.close(); conn.close()

    # 记活跃分
    # noinspection PyBroadException
    try:
        ac = get_db()
        if ac:
            acu = ac.cursor()
            acu.execute("INSERT INTO activity_log (username, action, points) VALUES (%s,%s,%s)", (username, "forum_reply", 2))
            ac.commit(); acu.close(); ac.close()
    except Exception:
        pass
    return jsonify({"ok": True, "id": rid})

# ---- 删除回复 ----
@app.route("/api/forum/replies/<int:rid>", methods=["DELETE"])
@login_required
def api_forum_reply_item(rid):
    username = session["username"]
    permission = session.get("permission", "guest")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT post_id, username FROM forum_replies WHERE id=%s", (rid,))
    r = cursor.fetchone()
    if not r:
        cursor.close(); conn.close()
        return jsonify({"ok": False, "error": "回复不存在"}), 404
    post_id = r[0]
    if permission != "administrator" and r[1] != username:
        cursor.close(); conn.close()
        return jsonify({"ok": False, "error": "无权限"}), 403
    cursor.execute("DELETE FROM forum_replies WHERE id=%s", (rid,))
    cursor.execute("UPDATE forum_posts SET reply_count = GREATEST(reply_count - 1, 0) WHERE id=%s", (post_id,))
    cursor.execute("DELETE FROM forum_likes WHERE target_type='reply' AND target_id=%s", (rid,))
    conn.commit(); cursor.close(); conn.close()
    return jsonify({"ok": True})

# ---- 点赞/取消点赞 ----
@app.route("/api/forum/like", methods=["POST"])
@login_required
def api_forum_like():
    username = session["username"]
    data = request.get_json() or {}
    target_type = data.get("target_type")  # 'post' or 'reply'
    target_id = data.get("target_id")
    if target_type not in ("post", "reply") or not target_id:
        return jsonify({"ok": False, "error": "参数错误"}), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM forum_likes WHERE username=%s AND target_type=%s AND target_id=%s",
                   (username, target_type, target_id))
    existing = cursor.fetchone()

    if existing:
        # 取消点赞
        cursor.execute("DELETE FROM forum_likes WHERE id=%s", (existing[0],))
        table = "forum_posts" if target_type == "post" else "forum_replies"
        col = "like_count"
        cursor.execute(f"UPDATE {table} SET {col} = GREATEST({col} - 1, 0) WHERE id=%s", (target_id,))
        conn.commit(); cursor.close(); conn.close()
        return jsonify({"ok": True, "liked": False})

    # 点赞
    cursor.execute("INSERT INTO forum_likes (username, target_type, target_id) VALUES (%s,%s,%s)",
                   (username, target_type, target_id))
    table = "forum_posts" if target_type == "post" else "forum_replies"
    cursor.execute(f"UPDATE {table} SET like_count = like_count + 1 WHERE id=%s", (target_id,))

    # 通知（帖子点赞通知帖主，回复点赞通知回复者）
    if target_type == "post":
        cursor.execute("SELECT username, title FROM forum_posts WHERE id=%s", (target_id,))
        target = cursor.fetchone()
        if target and target[0] != username:
            cursor.execute(
                "INSERT INTO forum_notifications (username, type, post_id, post_title, from_user) VALUES (%s,%s,%s,%s,%s)",
                (target[0], "like", target_id, target[1], username)
            )
    else:
        cursor.execute("SELECT r.username, r.content, r.post_id FROM forum_replies r WHERE r.id=%s", (target_id,))
        target = cursor.fetchone()
        if target and target[0] != username:
            cursor.execute(
                "INSERT INTO forum_notifications (username, type, post_id, post_title, from_user, content_preview) VALUES (%s,%s,%s,%s,%s,%s)",
                (target[0], "like", target[2], "", username, (target[1] or "")[:80])
            )

    conn.commit(); cursor.close(); conn.close()
    return jsonify({"ok": True, "liked": True})

# ---- 论坛通知 ----
@app.route("/api/forum/notifications")
@login_required
def api_forum_notifications():
    username = session["username"]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, type, post_id, post_title, from_user, content_preview, is_read, created_at "
        "FROM forum_notifications WHERE username=%s ORDER BY created_at DESC LIMIT 50",
        (username,)
    )
    rows = cursor.fetchall()
    cursor.close(); conn.close()
    notifs = [{
        "id": r[0], "type": r[1], "post_id": r[2], "post_title": r[3],
        "from_user": r[4], "content_preview": r[5], "is_read": bool(r[6]),
        "created_at": str(r[7]),
    } for r in rows]
    unread = sum(1 for n in notifs if not n["is_read"])
    return jsonify({"notifications": notifs, "unread": unread})

@app.route("/api/forum/notifications/read", methods=["POST"])
@login_required
def api_forum_notifications_read():
    username = session["username"]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE forum_notifications SET is_read=1 WHERE username=%s AND is_read=0", (username,))
    conn.commit(); cursor.close(); conn.close()
    return jsonify({"ok": True})


# ---------- Vue3 SPA 入口 ----------
@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    """
    JSON API 登出（URL: /api/auth/logout, POST）。

    权限：已登录用户
    功能：清除 session + 标记数据库会话为非活跃，返回 JSON。
    """
    """JSON API 登出"""
    ip = request.remote_addr or "0.0.0.0"
    # 标记数据库会话为非活跃
    session_manager.logout_session(
        session_key=session.get("session_key", ""),
        username=session.get("username", ""),
        ip=ip,
        reason="api_logout"
    )
    session.clear()
    return jsonify({"ok": True, "message": "已退出登录"})
@app.route("/vue3")

# ========== Vue3 SPA 端点 ==========

def vue3_spa():
    """Vue3 + Element Plus 单页应用入口"""
    _init_db_once()
    if "csrf_token" not in session:
        session["csrf_token"] = os.urandom(32).hex()
    # 检查是否已登录，传递给前端
    logged_in = "username" in session
    return render_template("vue3_app.html",
                           csrf_token=session.get("csrf_token", ""),
                           logged_in=logged_in)


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    """
    JSON API 登录（URL: /api/auth/login, POST）— 供 Vue3 SPA 使用。

    权限：未登录用户
    功能：与表单登录相同逻辑，返回 JSON 响应。受速率限制和防爆破保护。
    """
    """JSON API 登录 — 供 Vue3 SPA 使用"""
    _init_db_once()
    if "csrf_token" not in session:
        session["csrf_token"] = os.urandom(32).hex()

    client_ip = request.remote_addr or "unknown"
    _limit, _window = RATE_LIMITS["login"]
    if not rate_limiter.check((client_ip, "login"), max_requests=_limit, window=_window):
        return jsonify({"ok": False, "error": "请求过于频繁，请稍后再试"}), 429

    data = request.get_json(silent=True) or {}
    username = sanitize_input((data.get("username") or "").strip(), 50)
    password = (data.get("password") or "").strip()
    captcha_input = (data.get("captcha") or "").strip().lower()

    if not username or not password:
        return jsonify({"ok": False, "error": "用户名和密码不能为空"}), 400

    ok, err_msg = _verify_captcha(captcha_input)
    if not ok:
        return jsonify({"ok": False, "error": err_msg}), 400

    # 登录防爆破检查（文件持久化，多 worker 共享）
    if not rate_limiter.check((username, "login_fail"), max_requests=5, window=300):
        return jsonify({"ok": False, "error": "账户已被锁定，请 5 分钟后重试"}), 429

    conn = get_db()
    if not conn:
        return jsonify({"ok": False, "error": "数据库连接失败"}), 500

    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT User_Password, Access_Permission FROM users WHERE User_Name = %s",
            (username,)
        )
        result = cursor.fetchone()
        cursor.close()
        conn.close()

        if result:
            pwd_valid = safe_check_password_hash(result[0], password)
            if not pwd_valid:
                pwd_valid = (result[0] == password)
            if pwd_valid:
                session["username"] = username
                session["permission"] = result[1]
                session["csrf_token"] = os.urandom(32).hex()
                # 注册数据库会话（多用户同时在线追踪）
                session["session_key"] = uuid.uuid4().hex
                session_manager.register_session(
                    session_key=session["session_key"],
                    username=username,
                    ip=client_ip,
                    user_agent=request.headers.get("User-Agent", "")[:500]
                )
                if result[0] == password:
                    # 升级密码为 hash
                    try:
                        conn2 = get_db()
                        cur2 = conn2.cursor()
                        hashed = generate_password_hash(password)
                        cur2.execute("UPDATE users SET User_Password=%s WHERE User_Name=%s", (hashed, username))
                        conn2.commit()
                        cur2.close()
                        conn2.close()
                    except Exception:
                        pass
                record_activity(username, "登录", 1)
                avatar_url = f"/api/avatar/{username}" if username else ""
                return jsonify({
                    "ok": True,
                    "username": username,
                    "permission": result[1],
                    "avatar": avatar_url,
                })
            else:
                # 密码错误
                return jsonify({"ok": False, "error": "用户名或密码错误"}), 401
        # 登录失败（用户名不存在）
        return jsonify({"ok": False, "error": "用户名或密码错误"}), 401
    except pymysql.MySQLError as e:
        return jsonify({"ok": False, "error": f"数据库错误: {str(e)}"}), 500


@app.route("/api/auth/register", methods=["POST"])
def api_register():
    """
    JSON API 注册（URL: /api/auth/register, POST）— 供 Vue3 SPA 使用。

    权限：未登录用户
    功能：与表单注册相同逻辑，返回 JSON 响应。受速率限制和密码复杂度校验。
    """
    """JSON API 注册 — 供 Vue3 SPA 使用"""
    _init_db_once()
    if "csrf_token" not in session:
        session["csrf_token"] = os.urandom(32).hex()

    client_ip = request.remote_addr or "unknown"
    _limit, _window = RATE_LIMITS["register"]
    if not rate_limiter.check((client_ip, "register"), max_requests=_limit, window=_window):
        return jsonify({"ok": False, "error": "请求过于频繁"}), 429

    data = request.get_json(silent=True) or {}
    captcha_input = (data.get("captcha") or "").strip().lower()
    ok, err_msg = _verify_captcha(captcha_input)
    if not ok:
        return jsonify({"ok": False, "error": err_msg}), 400

    username = sanitize_input((data.get("username") or "").strip(), 50)
    password = (data.get("password") or "").strip()
    confirm = (data.get("confirm") or "").strip()
    admin_pwd = (data.get("admin_pwd") or "").strip()

    if not username or not password or not confirm:
        return jsonify({"ok": False, "error": "所有字段不能为空"}), 400
    if password != confirm:
        return jsonify({"ok": False, "error": "两次密码不一致"}), 400
    if len(password) < 8:
        return jsonify({"ok": False, "error": "密码长度不能少于8位"}), 400
    if not re.search(r"[A-Za-z]", password):
        return jsonify({"ok": False, "error": "密码必须包含至少一个字母"}), 400
    if not re.search(r"[0-9]", password):
        return jsonify({"ok": False, "error": "密码必须包含至少一个数字"}), 400

    permission = "administrator" if hmac.compare_digest(admin_pwd, ADMIN_SECRET) else "guest"

    conn = get_db()
    if not conn:
        return jsonify({"ok": False, "error": "数据库连接失败"}), 500

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE User_Name = %s", (username,))
        if cursor.fetchone()[0] > 0:
            cursor.close(); conn.close()
            return jsonify({"ok": False, "error": "用户名已存在，请更换"}), 409

        hashed_pw = generate_password_hash(password)
        cursor.execute(
            "INSERT INTO users (User_Name, User_Password, Access_Permission) VALUES (%s, %s, %s)",
            (username, hashed_pw, permission)
        )
        conn.commit()
        cursor.close(); conn.close()
        write_log("用户注册", f"用户名: {username}, 权限: {permission}")
        return jsonify({"ok": True, "message": f"注册成功！权限: {'管理员' if permission == 'administrator' else '访客'}"})
    except pymysql.IntegrityError:
        return jsonify({"ok": False, "error": "用户名已存在"}), 409
    except pymysql.MySQLError as e:
        return jsonify({"ok": False, "error": f"注册失败: {str(e)}"}), 500


@app.route("/api/auth/status")
def api_auth_status():
    """
    返回当前登录状态（URL: /api/auth/status, GET）— 供 Vue3 SPA 初始化时检查。

    权限：任意用户
    功能：检查 session 中是否有 username，返回 logged_in/username/permission/avatar。
    """
    """返回当前登录状态 — 供 Vue3 SPA 初始化时检查"""
    if "username" in session:
        return jsonify({
            "logged_in": True,
            "username": session["username"],
            "permission": session.get("permission", "guest"),
            "avatar": f"/api/avatar/{session['username']}" if session.get("username") else "",
        })
    return jsonify({"logged_in": False})


@app.route("/api/auth/forgot_password", methods=["POST"])
def api_forgot_password():
    """
    JSON API 忘记密码（URL: /api/auth/forgot_password, POST）— 供 Vue3 SPA 使用。

    权限：未登录用户
    功能：验证用户名存在后，插入重置申请到 reset_requests 表（待管理员审核）。
          受速率限制（3 次/5 分钟）。
    """
    """JSON API 忘记密码 — 供 Vue3 SPA 使用"""
    _init_db_once()
    if "csrf_token" not in session:
        session["csrf_token"] = os.urandom(32).hex()

    client_ip = request.remote_addr or "unknown"
    if not rate_limiter.check((client_ip, "forgot"), max_requests=3, window=300):
        return jsonify({"ok": False, "error": "请求过于频繁，请5分钟后再试"}), 429

    data = request.get_json(silent=True) or {}
    captcha_input = (data.get("captcha") or "").strip().lower()
    ok, err_msg = _verify_captcha(captcha_input)
    if not ok:
        return jsonify({"ok": False, "error": err_msg}), 400

    username = sanitize_input((data.get("username") or "").strip(), 50)
    email = sanitize_input((data.get("email") or "").strip(), 200)

    if not username:
        return jsonify({"ok": False, "error": "用户名不能为空"}), 400

    conn = get_db()
    if not conn:
        return jsonify({"ok": False, "error": "数据库连接失败"}), 500

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE User_Name = %s", (username,))
        if cursor.fetchone()[0] == 0:
            cursor.close(); conn.close()
            return jsonify({"ok": False, "error": "用户名不存在"}), 404

        cursor.execute(
            "INSERT INTO reset_requests (username, email, status, created_at) VALUES (%s, %s, %s, NOW())",
            (username, email, "pending")
        )
        conn.commit()
        cursor.close(); conn.close()
        write_log("密码重置申请", f"用户名: {username}, 邮箱: {email}")
        return jsonify({"ok": True, "message": "申请已提交，请等待管理员审核"})
    except pymysql.MySQLError as e:
        return jsonify({"ok": False, "error": f"提交失败: {str(e)}"}), 500


# ---------- 启动 ----------
def _kill_orphan_port(port: int):
    """
    杀掉占用指定端口的本用户残留进程，防止启动时端口冲突。

    通过 lsof 查找占用端口的 PID，过滤掉自身后发送 SIGKILL。
    不阻塞启动（清理失败不影响主流程）。

    Args:
        port: 要清理的端口号
    """
    import subprocess
    import signal
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True, timeout=5
        )
        pids = result.stdout.strip().split()
        if not pids:
            return
        # 过滤：只杀当前用户的进程
        my_pid = os.getpid()
        killed = 0
        for pid_str in pids:
            try:
                pid = int(pid_str)
                if pid == my_pid:
                    continue  # 不要杀自己
                os.kill(pid, signal.SIGKILL)
                killed += 1
            except (ProcessLookupError, PermissionError):
                pass
        if killed:
            print(f"  [清理] 已终止 {killed} 个占用端口 {port} 的残留进程")
    except Exception:
        pass  # 清理失败不阻塞启动

if __name__ == "__main__":

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
        print(f"  局域网访问: http://192.168.3.204:5800")
    print(f"  调试模式: {'开启' if os.environ.get('FLASK_DEBUG') else '关闭'}")
    print("=" * 50)
    
    # 启动后台会话清理线程
    def _session_cleanup_loop():
        import threading
        def _loop():
            while True:
                time.sleep(session_manager.CLEANUP_INTERVAL)
                try:
                    session_manager.cleanup_expired_sessions()
                except Exception:
                    pass
        t = threading.Thread(target=_loop, daemon=True)
        t.start()
    _session_cleanup_loop()
    
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    _init_plugins()
    
    # ---- 服务器选择 ----
    # WAITRESS_ENABLED=0 可强制回退到 Werkzeug 开发服务器
    # WAITRESS_THREADS=8  线程池大小（默认 8）
    use_waitress = os.environ.get("WAITRESS_ENABLED", "1") == "1"
    
    if use_waitress:
        try:

            
            threads = int(os.environ.get("WAITRESS_THREADS", "8"))
            

            print(f"  服务器引擎: Waitress {pkg_version('waitress')}")
            print(f"  线程池大小: {threads}")
            print(f"  最大连接数: {os.environ.get('WAITRESS_CONNECTION_LIMIT', '100')}")
            print("=" * 50)
            
            # 清理残留进程，防止端口占用
            _kill_orphan_port(4444)
            
            waitress.serve(
                app,
                host="0.0.0.0",
                port=4444,
                threads=threads,
                connection_limit=int(os.environ.get("WAITRESS_CONNECTION_LIMIT", "100")),
                channel_timeout=int(os.environ.get("WAITRESS_TIMEOUT", "60")),
                # 隐藏服务器标识
                ident=None,
                clear_untrusted_proxy_headers=True
            )
        except ImportError:
            print("  Waitress 未安装，回退到 Werkzeug 开发服务器")
            use_waitress = False
    
    if not use_waitress:
        # Werkzeug 开发服务器回退
        # 不泄露服务器类型/版本

        werkzeug.serving.WSGIRequestHandler.version_string = lambda self: ""
        werkzeug.serving.WSGIRequestHandler.sys_version = ''
        app.run(host="0.0.0.0", port=4444, debug=debug_mode, threaded=True)
