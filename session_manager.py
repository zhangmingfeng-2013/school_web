"""
会话管理器 — 数据库驱动的多用户在线追踪
===========================================

设计目的：
  替代原有的内存 ip_last_active 方案（每个 worker 进程独立维护），
  解决 Gunicorn 多 worker 进程间状态不共享的问题。

核心表结构：
  active_sessions  — 追踪每个登录会话（session_key 唯一，同用户可多条）
  session_events   — 审计日志：login / heartbeat / logout / kicked / timeout / self_end

使用模式：
  Flask before_request 钩子调用 track_session_activity() 更新活跃时间。
  前端 JS 心跳定期调用 heartbeat() 保持会话。
  管理员可 kick_session() 强制踢出，用户可 end_session() 自行结束。

会话生命周期：
  login → register_session() 注册
  请求 → update_activity() 或 heartbeat() 续期
  idle > 30min → cleanup_expired_sessions() 标记过期
  logout → logout_session() 标记非活跃
  admin kick → kick_session() 标记非活跃
"""
import os
import pymysql

# ---------- 配置 ----------

# 数据库配置：未设置 DB_PASSWORD 时使用空占位值，
# 连接会失败并返回 None，由调用方优雅降级，不阻断应用启动
_sm_db_password = os.environ.get("DB_PASSWORD")
if not _sm_db_password:
    _sm_db_password = ""
    import logging as _sm_logging
    _sm_logging.getLogger(__name__).warning(
        "未设置环境变量 DB_PASSWORD，数据库将不可用。请在 .env 或部署环境中设置 DB_PASSWORD"
    )

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": os.environ.get("DB_USER", "root"),
    "password": _sm_db_password,
    "database": os.environ.get("DB_NAME", "sample"),
    "connect_timeout": 5,   # 连接超时 5 秒，避免阻塞
    "autocommit": True,     # 自动提交，无需手动 commit
}

SESSION_IDLE_TIMEOUT = 300  # 5 分钟无活动 → 视为离线
CLEANUP_INTERVAL = 300       # 每 5 分钟清理一次过期会话（由 app.py 定时器触发）


# ---------- 内部函数 ----------

def _get_conn():
    """
    获取数据库连接。

    Returns:
        pymysql.Connection | None: 连接对象，失败返回 None。

    设计说明：
    每调用一次就创建新连接，用完即关。简单可靠，适合中等并发。
    高并发场景可改为连接池（如 DBUtils.PooledDB）。
    """
    try:
        return pymysql.connect(**DB_CONFIG)
    except Exception:
        return None


# =============================================================================
#  会话生命周期管理
# =============================================================================

def register_session(session_key, username, ip, user_agent=""):
    """
    用户登录时注册新会话。

    Args:
        session_key: Flask session 唯一标识（UUID hex）。
        username:   登录用户名。
        ip:         客户端 IP 地址。
        user_agent: 浏览器 User-Agent 字符串。

    Returns:
        bool: 注册成功返回 True。

    执行流程：
      1. 标记该 session_key 的旧记录为非活跃（幂等，应对重复登录）。
      2. INSERT ... ON DUPLICATE KEY UPDATE 确保写入。
      3. 记录 'login' 事件到 session_events 审计表。
    """
    conn = _get_conn()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        # 标记该 session_key 的旧记录为非活跃（如果有）
        cursor.execute(
            "UPDATE active_sessions SET is_active=0 WHERE session_key=%s",
            (session_key,)
        )
        # 插入新会话记录（ON DUPLICATE KEY UPDATE 保证幂等）
        cursor.execute(
            """INSERT INTO active_sessions
               (session_key, username, ip_address, user_agent, login_time, last_activity, is_active)
               VALUES (%s, %s, %s, %s, NOW(), NOW(), 1)
               ON DUPLICATE KEY UPDATE
               username=%s, ip_address=%s, user_agent=%s, last_activity=NOW(), is_active=1""",
            (session_key, username, ip, user_agent,
             username, ip, user_agent)
        )
        # 记录登录事件（审计日志）
        cursor.execute(
            "INSERT INTO session_events (session_key, username, event_type, ip_address) VALUES (%s, %s, 'login', %s)",
            (session_key, username, ip)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"  register_session 失败: {e}")
        return False


def update_activity(session_key, username, ip):
    """
    更新会话最后活跃时间（每次 HTTP 请求调用，不含前端心跳）。

    Args:
        session_key: Flask session 标识。
        username:    当前用户名。
        ip:          客户端 IP。

    特殊处理：
      如果 UPDATE 影响 0 行（多个 worker 中某个 worker 首次见到该 session），
      自动补充一条 INSERT，保证追踪不丢失。
    """
    conn = _get_conn()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE active_sessions SET last_activity=NOW(), ip_address=%s WHERE session_key=%s AND is_active=1",
            (ip, session_key)
        )
        if cursor.rowcount == 0:
            # 会话不存在（可能是新 worker 第一次见到），兜底注册
            cursor.execute(
                """INSERT INTO active_sessions
                   (session_key, username, ip_address, last_activity, is_active)
                   VALUES (%s, %s, %s, NOW(), 1)
                   ON DUPLICATE KEY UPDATE last_activity=NOW(), is_active=1""",
                (session_key, username, ip)
            )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception:
        pass


def heartbeat(session_key, username, ip):
    """
    前端心跳：更新活跃时间 + 记录心跳事件。

    由前端 JS 每 60 秒调用一次 /api/heartbeat。
    同时返回当前在线人数给前端更新 UI。

    Returns:
        bool: 心跳成功返回 True。
    """
    conn = _get_conn()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE active_sessions SET last_activity=NOW(), ip_address=%s WHERE session_key=%s AND is_active=1",
            (ip, session_key)
        )
        # 记录心跳事件（用于审计和活跃度分析）
        cursor.execute(
            "INSERT INTO session_events (session_key, username, event_type, ip_address) VALUES (%s, %s, 'heartbeat', %s)",
            (session_key, username, ip)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Exception:
        return False


def logout_session(session_key, username, ip, reason="logout"):
    """
    用户主动登出 / 超时登出 / API 登出。

    Args:
        session_key: 要终止的会话标识。
        username:    用户名（用于审计日志）。
        ip:          客户端 IP。
        reason:      登出原因：'logout' | 'timeout' | 'api_logout'。
    """
    conn = _get_conn()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE active_sessions SET is_active=0 WHERE session_key=%s",
            (session_key,)
        )
        cursor.execute(
            "INSERT INTO session_events (session_key, username, event_type, ip_address) VALUES (%s, %s, %s, %s)",
            (session_key, username, reason, ip)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception:
        pass


# =============================================================================
#  会话管理（管理员 / 用户自管理）
# =============================================================================

def kick_session(session_key, admin_username):
    """
    管理员强制踢出指定用户的会话。

    Args:
        session_key:     要踢出的会话标识。
        admin_username:  操作的管理员用户名（用于审计）。

    Returns:
        (bool, str): (是否成功, 消息)。
    """
    conn = _get_conn()
    if not conn:
        return False, "数据库连接失败"
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT username FROM active_sessions WHERE session_key=%s AND is_active=1",
            (session_key,)
        )
        row = cursor.fetchone()
        if not row:
            cursor.close()
            conn.close()
            return False, "会话不存在或已离线"
        target_user = row[0]
        cursor.execute(
            "UPDATE active_sessions SET is_active=0 WHERE session_key=%s",
            (session_key,)
        )
        cursor.execute(
            "INSERT INTO session_events (session_key, username, event_type, ip_address) VALUES (%s, %s, 'kicked', '')",
            (session_key, target_user)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return True, f"已踢出用户 {target_user}"
    except Exception as e:
        return False, str(e)


def end_session(session_key, username):
    """
    用户自行终止某个会话（只能终止自己的其他设备，不能终止当前设备）。

    Args:
        session_key: 要终止的会话标识。
        username:    当前用户。

    Returns:
        (bool, str): (是否成功, 消息)。
    """
    conn = _get_conn()
    if not conn:
        return False, "数据库连接失败"
    try:
        cursor = conn.cursor()
        # 先查出会话所属用户
        cursor.execute(
            "SELECT username FROM active_sessions WHERE session_key=%s AND is_active=1",
            (session_key,)
        )
        row = cursor.fetchone()
        if not row:
            cursor.close()
            conn.close()
            return False, "会话不存在或已离线"
        if row[0] != username:
            cursor.close()
            conn.close()
            # 安全：不允许跨用户终止他人会话
            return False, "只能终止自己的会话"
        cursor.execute(
            "UPDATE active_sessions SET is_active=0 WHERE session_key=%s",
            (session_key,)
        )
        cursor.execute(
            "INSERT INTO session_events (session_key, username, event_type, ip_address) VALUES (%s, %s, 'self_end', '')",
            (session_key, username)
        )
        conn.commit()
        cursor.close()
        conn.close()
        return True, "会话已终止"
    except Exception as e:
        return False, str(e)


def kick_user_sessions(username, except_session_key=None):
    """
    踢出用户的所有活跃会话（用于 allow_multi_login 关闭时强制单设备登录）。

    Args:
        username:            要踢出的用户名。
        except_session_key:  保留的会话（当前登录的会话）。

    行为：
      如果 except_session_key 为 None，则踢出全部会话。
      否则保留 except_session_key 对应会话，踢出其余所有。
    """
    conn = _get_conn()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        if except_session_key:
            cursor.execute(
                "UPDATE active_sessions SET is_active=0 WHERE username=%s AND is_active=1 AND session_key!=%s",
                (username, except_session_key)
            )
        else:
            cursor.execute(
                "UPDATE active_sessions SET is_active=0 WHERE username=%s AND is_active=1",
                (username,)
            )
        kicked = cursor.rowcount
        if kicked:
            # 审计日志记录保留的会话 key（若有）
            cursor.execute(
                "INSERT INTO session_events (session_key, username, event_type, ip_address) VALUES (%s, %s, 'kicked_multi', '')",
                (except_session_key or '', username)
            )
        conn.commit()
        cursor.close()
        conn.close()
        if kicked:
            print(f"  [多登录限制] 踢出用户 {username} 的 {kicked} 个旧会话")
    except Exception:
        pass


# =============================================================================
#  查询函数
# =============================================================================

def get_active_sessions(include_idle=True):
    """
    获取当前所有活跃会话列表。

    Args:
        include_idle: True 返回所有 is_active=1 的（含空闲）；False 只返回 30 分钟内有活动的。

    Returns:
        list[dict]: 每个会话含 id / session_key / username / ip / user_agent /
                    login_time / last_activity / idle_seconds / idle_str。
    """
    conn = _get_conn()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        if include_idle:
            # 管理员视图：显示所有标记为活跃的
            cursor.execute("""
                SELECT id, session_key, username, ip_address, user_agent,
                       login_time, last_activity,
                       TIMESTAMPDIFF(SECOND, last_activity, NOW()) AS idle_seconds
                FROM active_sessions
                WHERE is_active=1
                ORDER BY last_activity DESC
            """)
        else:
            # 普通用户视图：只显示 30 分钟内有活动的
            cutoff = SESSION_IDLE_TIMEOUT
            cursor.execute("""
                SELECT id, session_key, username, ip_address, user_agent,
                       login_time, last_activity,
                       TIMESTAMPDIFF(SECOND, last_activity, NOW()) AS idle_seconds
                FROM active_sessions
                WHERE is_active=1 AND last_activity >= NOW() - INTERVAL %s SECOND
                ORDER BY last_activity DESC
            """, (cutoff,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return [
            {
                "id": r[0],
                "session_key": r[1],
                "username": r[2],
                "ip": r[3],
                "user_agent": r[4],
                "login_time": r[5].strftime("%Y-%m-%d %H:%M:%S") if r[5] else "",
                "last_activity": r[6].strftime("%Y-%m-%d %H:%M:%S") if r[6] else "",
                "idle_seconds": r[7],
                # 友好格式：<60s 显示秒，否则显示 XmYs
                "idle_str": f"{r[7]}s" if r[7] < 60 else f"{r[7]//60}m{r[7]%60}s"
            }
            for r in rows
        ]
    except Exception:
        return []


def get_online_count():
    """
    获取当前在线用户数（按 username 去重，只统计 30 分钟内有活动的）。

    Returns:
        int: 在线用户数。
    """
    conn = _get_conn()
    if not conn:
        return 0
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(DISTINCT username) FROM active_sessions
            WHERE is_active=1 AND last_activity >= NOW() - INTERVAL %s SECOND
        """, (SESSION_IDLE_TIMEOUT,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row[0] if row else 0
    except Exception:
        return 0


def get_user_sessions(username):
    """
    获取指定用户的所有活跃会话（用于设备管理弹窗）。

    Args:
        username: 用户名。

    Returns:
        list[dict]: 同 get_active_sessions 格式。
    """
    conn = _get_conn()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, session_key, username, ip_address, user_agent,
                   login_time, last_activity,
                   TIMESTAMPDIFF(SECOND, last_activity, NOW()) AS idle_seconds
            FROM active_sessions
            WHERE username=%s AND is_active=1
            ORDER BY last_activity DESC
        """, (username,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return [
            {
                "id": r[0],
                "session_key": r[1],
                "username": r[2],
                "ip": r[3],
                "user_agent": r[4],
                "login_time": r[5].strftime("%Y-%m-%d %H:%M:%S") if r[5] else "",
                "last_activity": r[6].strftime("%Y-%m-%d %H:%M:%S") if r[6] else "",
                "idle_seconds": r[7],
                "idle_str": f"{r[7]}s" if r[7] < 60 else f"{r[7]//60}m{r[7]%60}s"
            }
            for r in rows
        ]
    except Exception:
        return []


def get_session_last_activity(session_key):
    """
    获取单个会话的最后活跃时间（用于空闲超时检查）。

    Args:
        session_key: 会话标识。

    Returns:
        datetime.datetime | None: 最后活跃时间，不存在返回 None。
    """
    conn = _get_conn()
    if not conn:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT last_activity FROM active_sessions WHERE session_key=%s AND is_active=1",
            (session_key,)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row and row[0]:
            return row[0]
        return None
    except Exception:
        return None


def get_active_ips():
    """
    获取当前活跃的 IP 列表（用于系统监控页面，替代旧的内存 ip_last_active）。

    Returns:
        dict[str, float]: {ip_address: last_active_timestamp}。
        只统计 30 分钟内有活动的 IP，按 IP 去重取最近活跃时间。
    """
    conn = _get_conn()
    if not conn:
        return {}
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ip_address, MAX(last_activity) AS last_active
            FROM active_sessions
            WHERE is_active=1 AND last_activity >= NOW() - INTERVAL %s SECOND
            GROUP BY ip_address
        """, (SESSION_IDLE_TIMEOUT,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        import datetime as dt
        result = {}
        for r in rows:
            if r[1]:
                result[r[0]] = r[1].timestamp() if hasattr(r[1], 'timestamp') else r[1]
        return result
    except Exception:
        return {}


def get_user_allow_multi_login(username):
    """
    查询用户是否允许多设备同时在线。

    Args:
        username: 用户名。

    Returns:
        bool: True 允许多设备，False 强制单设备。
              默认 True（DB 无记录或故障时均返回 True）。
    """
    conn = _get_conn()
    if not conn:
        return True  # DB 故障时默认允许，避免误伤
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT allow_multi_login FROM user_profiles WHERE username=%s",
            (username,)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row and row[0] is not None:
            return bool(row[0])
        return True  # 未设置则默认允许
    except Exception:
        return True


# =============================================================================
#  维护函数
# =============================================================================

def cleanup_expired_sessions():
    """
    清理过期会话（标记为非活跃）。

    由 app.py 的后台定时器每 5 分钟调用一次。
    将 last_activity 超过 30 分钟的会话 is_active 设为 0。
    """
    conn = _get_conn()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE active_sessions SET is_active=0
            WHERE is_active=1 AND last_activity < NOW() - INTERVAL %s SECOND
        """, (SESSION_IDLE_TIMEOUT,))
        cleaned = cursor.rowcount
        conn.commit()
        cursor.close()
        conn.close()
        if cleaned:
            print(f"  [会话清理] 标记 {cleaned} 个过期会话")
    except Exception:
        pass


def is_session_valid(session_key):
    """
    检查会话是否仍然有效（未被管理员踢出或过期标记）。

    由 Flask before_request 钩子 check_kicked() 调用。
    每次请求都检查，如果被踢出则清空 session 并重定向到登录页。

    Args:
        session_key: 会话标识。

    Returns:
        bool: True 有效，False 已被终止。
              DB 故障时返回 True（fail-open，避免误伤正常用户）。
    """
    conn = _get_conn()
    if not conn:
        return True  # DB 故障时允许通过，避免全员被迫登出
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT is_active FROM active_sessions WHERE session_key=%s",
            (session_key,)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row is None:
            return True  # 新会话（DB 尚未写入），允许通过
        return bool(row[0])
    except Exception:
        return True
