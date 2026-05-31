"""
会话管理器 — 数据库驱动的多用户在线追踪
替代原有的内存 ip_last_active 方案，解决 Gunicorn 多 worker 进程间状态不共享的问题
"""
import os
import pymysql

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASSWORD", "root@123456"),
    "database": os.environ.get("DB_NAME", "sample"),
    "connect_timeout": 5,
    "autocommit": True,
}

SESSION_IDLE_TIMEOUT = 1800  # 30 分钟无活动视为离线
CLEANUP_INTERVAL = 300       # 5 分钟清理一次过期会话


def _get_conn():
    """获取数据库连接"""
    try:
        return pymysql.connect(**DB_CONFIG)
    except Exception:
        return None


def register_session(session_key, username, ip, user_agent=""):
    """用户登录时注册新会话"""
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
        # 插入新会话记录
        cursor.execute(
            """INSERT INTO active_sessions 
               (session_key, username, ip_address, user_agent, login_time, last_activity, is_active)
               VALUES (%s, %s, %s, %s, NOW(), NOW(), 1)
               ON DUPLICATE KEY UPDATE 
               username=%s, ip_address=%s, user_agent=%s, last_activity=NOW(), is_active=1""",
            (session_key, username, ip, user_agent,
             username, ip, user_agent)
        )
        # 记录事件
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
    """更新会话最后活跃时间（每次请求调用，不含心跳）"""
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
            # 会话不存在（可能是新 worker 第一次见到），注册
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
    """前端心跳：更新活跃时间 + 记录心跳事件"""
    conn = _get_conn()
    if not conn:
        return False
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE active_sessions SET last_activity=NOW(), ip_address=%s WHERE session_key=%s AND is_active=1",
            (ip, session_key)
        )
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
    """用户主动登出"""
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


def kick_session(session_key, admin_username):
    """管理员踢出用户"""
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


def get_active_sessions(include_idle=True):
    """获取当前活跃会话列表"""
    conn = _get_conn()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        if include_idle:
            cursor.execute("""
                SELECT id, session_key, username, ip_address, user_agent, 
                       login_time, last_activity,
                       TIMESTAMPDIFF(SECOND, last_activity, NOW()) AS idle_seconds
                FROM active_sessions 
                WHERE is_active=1
                ORDER BY last_activity DESC
            """)
        else:
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
                "idle_str": f"{r[7]}s" if r[7] < 60 else f"{r[7]//60}m{r[7]%60}s"
            }
            for r in rows
        ]
    except Exception:
        return []


def get_online_count():
    """获取当前在线用户数（按 username 去重，只统计 30 分钟内有活动的）"""
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


def cleanup_expired_sessions():
    """清理过期会话（标记为非活跃）"""
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
    """检查会话是否仍然有效（未被踢出）"""
    conn = _get_conn()
    if not conn:
        return True  # DB 故障时允许通过
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
            return True  # 新会话，允许
        return bool(row[0])
    except Exception:
        return True


def get_session_last_activity(session_key):
    """获取会话最后活跃时间（用于空闲超时检查）"""
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


def get_user_sessions(username):
    """获取指定用户的所有活跃会话"""
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


def end_session(session_key, username):
    """用户自行终止某个会话（只能终止自己的）"""
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
        if row[0] != username:
            cursor.close()
            conn.close()
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
    """踢出用户的所有活跃会话（用于 allow_multi_login=0 时强制单会话）"""
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


def get_active_ips():
    """获取当前活跃的 IP 列表（用于系统监控，替代内存 ip_last_active）"""
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
        # 返回 {ip: last_active_timestamp}
        import datetime as dt
        result = {}
        for r in rows:
            if r[1]:
                result[r[0]] = r[1].timestamp() if hasattr(r[1], 'timestamp') else r[1]
        return result
    except Exception:
        return {}


def get_user_allow_multi_login(username):
    """查询用户是否允许多设备同时在线"""
    conn = _get_conn()
    if not conn:
        return True  # DB 故障时默认允许
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
        return True  # 默认允许
    except Exception:
        return True
