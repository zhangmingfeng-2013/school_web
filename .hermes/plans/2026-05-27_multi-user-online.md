# 多用户同时在线功能 — 实现计划

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 将 School_Web 从单用户（按 IP 追踪）升级为真正的多用户同时在线系统，支持独立会话、在线状态追踪、管理员会话管理。

**Architecture:** MySQL 数据库驱动的会话追踪 + 前端心跳轮询。用 `active_sessions` 表替代内存 `ip_last_active` 字典，解决 Gunicorn 多 worker 进程间状态不共享的根本问题；前端每 60 秒发送心跳保持会话活跃；管理员可查看/踢出在线用户。

**Tech Stack:** Flask + PyMySQL + Jinja2 模板 + 原生 JavaScript（无额外依赖）

---

## 现状问题分析

| 问题 | 根因 | 影响 |
| IP 追踪不适用于多人 | `ip_last_active[ip]` 只按 IP 不按用户 | 同一 NAT/路由器下多人互相覆盖 |
| 多 worker 状态不一致 | Gunicorn gthread 多进程，`ip_last_active` 是模块级变量 | 不同 worker 看到不同的在线列表 |
| 空闲超时误清 session | `check_session_idle_timeout()` 按 IP 清除 | 用户 A 的 session 可能因用户 B 活动被清 |
| 无在线用户列表 | 只能按 IP 看，不显示用户名 | 管理员无法知道谁在线 |
| 无法踢人 | 无 session 管理机制 | 无法强制登出恶意用户 |

---

## 数据库变更

### 新建表: `active_sessions`

```mysql
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 新建表: `session_events`

```mysql
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 扩展表: `user_profiles`

```mysql
-- 添加多设备同时登录开关
ALTER TABLE user_profiles ADD COLUMN allow_multi_login TINYINT DEFAULT 1;
```

---

## 实现任务

### Task 1: 创建数据库表 `active_sessions` 和 `session_events`

**目标:** 在 `_init_db_once()` 中新增两张表的初始化逻辑

**文件:** 
- 修改: `app.py` — `_init_db_once()` 函数

**步骤:**

1. 在 `_init_db_once()` 函数中添加 `_init_session_tables()` 调用
2. 新增 `_init_session_tables()` 函数，执行 `CREATE TABLE IF NOT EXISTS`

```python
def _init_session_tables():
    """创建会话追踪表"""
    conn = get_db()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS active_sessions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_key VARCHAR(64) NOT NULL UNIQUE,
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
                event_type VARCHAR(20) NOT NULL,
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
```

3. 在 `_init_db_once()` 中 `_init_db_done = True` 之前添加 `_init_session_tables()`

**验证:** 重启应用，检查 MySQL 中表是否创建成功

---

### Task 2: 新建会话管理工具模块

**目标:** 创建 `session_manager.py`，封装所有会话追踪的数据库操作

**文件:**
- 创建: `session_manager.py`

```python
"""
会话管理器 — 数据库驱动的多用户在线追踪
替代原有的内存 ip_last_active 方案
"""
import os
import time
import pymysql

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASSWORD", ""),
    "database": os.environ.get("DB_NAME", "school_web"),
    "charset": "utf8mb4",
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
    """更新会话最后活跃时间（每次请求或心跳调用）"""
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
    """获取当前在线用户数（按 username 去重）"""
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
            print(f"  会话清理: 标记 {cleaned} 个过期会话")
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
```

**验证:** 导入模块，手动调用各函数验证数据库读写

---

### Task 3: 在 Flask app 中分配 session_key 并集成会话管理

**目标:** 为每个浏览器会话生成唯一 `session_key`，在 `before_request` 中更新活跃状态

**文件:**
- 修改: `app.py` — 多处改动

**步骤:**

#### 3a. 导入 session_manager

在 `app.py` 顶部添加:
```python
import session_manager
```

#### 3b. 新增 `before_request` — 分配 session_key

在现有 `before_request` 函数之后添加:

```python
@app.before_request
def assign_session_key():
    """为每个浏览器会话分配唯一 session_key，用于数据库会话追踪"""
    if "session_key" not in session:
        session["session_key"] = uuid.uuid4().hex
```

#### 3c. 新增 `before_request` — 更新会话活跃状态

```python
@app.before_request
def track_session_activity():
    """每次请求更新数据库中的会话活跃时间"""
    if "username" not in session:
        return None
    # 排除静态资源和 API 心跳本身
    path = request.path
    if path.startswith("/static/") or path.startswith("/assets/") or path == "/api/heartbeat":
        return None
    
    session_key = session.get("session_key")
    username = session.get("username")
    ip = request.remote_addr or "0.0.0.0"
    
    if session_key and username:
        session_manager.update_activity(session_key, username, ip)
```

#### 3d. 新增 `before_request` — 检查是否被踢出

```python
@app.before_request  
def check_kicked():
    """检查当前会话是否被管理员踢出"""
    if "username" not in session:
        return None
    path = request.path
    if path in ("/", "/login", "/register", "/logout"):
        return None
    if path.startswith("/static/") or path.startswith("/assets/"):
        return None
    
    session_key = session.get("session_key")
    if session_key and not session_manager.is_session_valid(session_key):
        username = session.get("username", "")
        session.clear()
        flash("您的会话已被管理员终止", "warning")
        return redirect(url_for("login"))
```

#### 3e. 修改 `check_session_idle_timeout()` — 改为 session 级别

将原来的 IP 级超时改为 session 级:

```python
@app.before_request
def check_session_idle_timeout():
    """基于 session_key 的会话空闲超时检测（替代原 IP 级检测）"""
    skip_prefixes = ("/static/", "/assets/", "/favicon.ico", "/share/", "/plugin-market/")
    path = request.path
    if any(path.startswith(p) for p in skip_prefixes):
        return None
    if path in ("/", "/login", "/register", "/logout"):
        return None
    
    if "username" not in session:
        return None
    
    # 使用数据库检查（不依赖内存 ip_last_active）
    # 心跳机制由前端处理，这里做保险兜底
    session_key = session.get("session_key")
    if session_key and not session_manager.is_session_valid(session_key):
        session.clear()
        flash("会话已过期，请重新登录", "warning")
        return redirect(url_for("login"))
```

**注意:** 旧的 `ip_last_active` 逻辑需要保留但降级为 `# 已弃用，由 session_manager 替代` 注释状态，后续 Task 统一清理。

#### 3f. 修改 `login()` — 注册会话

在登录成功处（`session["username"] = username` 之后）添加:

```python
# 注册数据库会话
session["session_key"] = uuid.uuid4().hex  # 每次登录生成新 key
session_manager.register_session(
    session_key=session["session_key"],
    username=username,
    ip=request.remote_addr or "0.0.0.0",
    user_agent=request.headers.get("User-Agent", "")[:500]
)
```

#### 3g. 修改 `logout()` — 注销会话

在 `session.clear()` 之前添加:

```python
session_manager.logout_session(
    session_key=session.get("session_key", ""),
    username=session.get("username", ""),
    ip=request.remote_addr or "0.0.0.0",
    reason="logout"
)
```

**验证:** 登录 → 查看 `active_sessions` 表有新记录 → 登出 → 记录标记 `is_active=0`

---

### Task 4: 添加心跳 API 和在线统计 API

**目标:** 提供前端心跳端点和在线统计 API

**文件:**
- 修改: `app.py`

**步骤:**

#### 4a. 心跳 API

```python
@app.route("/api/heartbeat", methods=["POST"])
@login_required
def api_heartbeat():
    """前端心跳：保持会话活跃"""
    ok = session_manager.heartbeat(
        session_key=session.get("session_key", ""),
        username=session.get("username", ""),
        ip=request.remote_addr or "0.0.0.0"
    )
    online_count = session_manager.get_online_count()
    return jsonify({"ok": ok, "online_count": online_count})
```

#### 4b. 在线用户统计 API（替代旧 `api_system_users` 的用户部分）

```python
@app.route("/api/online_users", methods=["GET"])
@login_required
def api_online_users():
    """返回当前在线用户列表"""
    sessions = session_manager.get_active_sessions(include_idle=False)
    # 汇总：同一用户可能有多个 session
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
```

#### 4c. 管理员：获取所有活跃会话

```python
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
```

#### 4d. 管理员：踢出会话

```python
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
```

**验证:** 
- `curl -X POST /api/heartbeat` 返回 ok:true
- `curl /api/online_users` 返回在线用户列表

---

### Task 5: 前端 — 添加心跳轮询

**目标:** 在关键页面添加心跳 JavaScript，保持会话活跃

**文件:**
- 修改: `templates/base.html`（所有页面继承）

**步骤:**

在 `base.html` 的 `</body>` 之前添加心跳脚本:

```html
<script nonce="{{ csp_nonce }}">
(function() {
    'use strict';
    // 仅已登录用户发送心跳
    if (!document.querySelector('[data-logged-in]')) {
        // 通过检查页面是否有登录态元素来判断
        var heartbeatActive = false;
        
        // 每 60 秒发送一次心跳
        function sendHeartbeat() {
            fetch('/api/heartbeat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': '{{ csrf_token }}'
                },
                credentials: 'same-origin'
            }).then(function(r) { return r.json(); })
              .then(function(data) {
                  if (data.ok) {
                      // 更新在线人数（如果页面上有显示）
                      var el = document.getElementById('online-count');
                      if (el && data.online_count !== undefined) {
                          el.textContent = data.online_count;
                      }
                  }
              }).catch(function() {});
        }
        
        // 页面可见时才发心跳
        document.addEventListener('visibilitychange', function() {
            if (!document.hidden) {
                sendHeartbeat();
            }
        });
        
        // 初始延迟 10 秒后开始（等页面加载完）
        setTimeout(function() {
            sendHeartbeat();
            setInterval(sendHeartbeat, 60000); // 60 秒一次
        }, 10000);
    }
})();
</script>
```

**验证:** 打开 DevTools Network 面板，确认每 60 秒看到 `/api/heartbeat` 请求

---

### Task 6: 前端 — 仪表盘显示在线人数

**目标:** 在仪表盘页面显示当前在线用户数

**文件:**
- 修改: `templates/dashboard.html`

**步骤:**

在仪表盘顶部（用户名旁边）添加在线人数显示:

```html
<!-- 在 dashboard.html 顶部用户名区添加 -->
<div class="text-center mb-2" style="font-size:.85rem;color:#666;">
    🟢 {{ _('online_users') }}: <strong id="online-count">--</strong>
</div>
```

在页面底部添加初始化 JS:

```html
<script nonce="{{ csp_nonce }}">
// 页面加载时获取在线人数
fetch('/api/online_users', { credentials: 'same-origin' })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.ok) {
            document.getElementById('online-count').textContent = data.online_count;
        }
    });
</script>
```

---

### Task 7: 管理员面板 — 会话管理页面

**目标:** 为管理员提供查看和踢出在线会话的界面

**文件:**
- 创建: `templates/admin_sessions.html`
- 修改: `app.py` — 添加路由

**步骤:**

#### 7a. 创建模板

```html
{% extends "base.html" %}
{% block title %}会话管理 - 管理员{% endblock %}
{% block content %}
<div class="container mt-4">
    <h3>🔍 在线会话管理</h3>
    <p class="text-muted small">实时查看所有活跃会话，可踢出异常用户</p>
    
    <div class="table-responsive mt-3">
        <table class="table table-sm table-hover" id="sessionsTable">
            <thead style="background:#f8f9fa;">
                <tr>
                    <th>用户名</th>
                    <th>IP 地址</th>
                    <th>登录时间</th>
                    <th>最后活跃</th>
                    <th>空闲</th>
                    <th>操作</th>
                </tr>
            </thead>
            <tbody id="sessionsBody">
                <tr><td colspan="6" class="text-center text-muted">加载中...</td></tr>
            </tbody>
        </table>
    </div>
    
    <button class="btn btn-outline-primary btn-sm mt-2" onclick="refreshSessions()">🔄 刷新</button>
    <small class="text-muted ms-2">每 30 秒自动刷新</small>
</div>

<script nonce="{{ csp_nonce }}">
var autoRefresh;

function refreshSessions() {
    fetch('/api/admin/sessions', { credentials: 'same-origin' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var tbody = document.getElementById('sessionsBody');
            if (!data.ok || !data.sessions) {
                tbody.innerHTML = '<tr><td colspan="6" class="text-center text-danger">加载失败</td></tr>';
                return;
            }
            if (data.sessions.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">暂无活跃会话</td></tr>';
                return;
            }
            tbody.innerHTML = data.sessions.map(function(s) {
                var currentUser = '{{ username }}';
                var isSelf = s.username === currentUser;
                var badge = s.idle_seconds < 120 
                    ? '<span class="badge bg-success">在线</span>' 
                    : (s.idle_seconds < 600 
                        ? '<span class="badge bg-warning text-dark">空闲</span>' 
                        : '<span class="badge bg-secondary">离开</span>');
                var kickBtn = isSelf 
                    ? '<button class="btn btn-sm btn-outline-secondary" disabled>自己</button>'
                    : '<button class="btn btn-sm btn-outline-danger" onclick="kickSession(\'' + s.session_key + '\', \'' + s.username + '\')">踢出</button>';
                return '<tr>' +
                    '<td><strong>' + s.username + '</strong> ' + badge + '</td>' +
                    '<td><code>' + s.ip + '</code></td>' +
                    '<td>' + s.login_time + '</td>' +
                    '<td>' + s.last_activity + '</td>' +
                    '<td>' + s.idle_str + '</td>' +
                    '<td>' + kickBtn + '</td>' +
                    '</tr>';
            }).join('');
        });
}

function kickSession(sessionKey, username) {
    if (!confirm('确定要踢出用户 ' + username + ' 吗？')) return;
    fetch('/api/admin/sessions/kick', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_key: sessionKey }),
        credentials: 'same-origin'
    }).then(function(r) { return r.json(); })
      .then(function(data) {
          alert(data.message);
          refreshSessions();
      });
}

refreshSessions();
autoRefresh = setInterval(refreshSessions, 30000);

// 页面离开时清理定时器
window.addEventListener('beforeunload', function() {
    clearInterval(autoRefresh);
});
</script>
{% endblock %}
```

#### 7b. 添加路由

```python
@app.route("/admin/sessions")
@login_required
@admin_required
def admin_sessions():
    return render_template("admin_sessions.html",
                           username=session["username"],
                           permission=session["permission"])
```

#### 7c. 在管理员仪表盘添加入口

在 `templates/admin_dashboard.html` 或 `templates/dashboard.html` 的管理员区域添加链接:

```html
<a href="/admin/sessions" class="btn btn-outline-info btn-sm">
    🔍 会话管理
</a>
```

**验证:** 管理员账号登录 → 访问 `/admin/sessions` → 看到在线用户列表 → 点击踢出

---

### Task 8: 清理旧代码 + 定期清理任务

**目标:** 清理 `ip_last_active` 旧逻辑，添加后台清理线程

**文件:**
- 修改: `app.py`

**步骤:**

#### 8a. 注释旧 `ip_last_active` 相关代码

- `check_session_idle_timeout()` 中 IP 超时检测逻辑 → 标记为 `# [已弃用]`
- `ip_last_active` 字典声明 → 保留但注释说明
- `logout()` 中的 `ip_last_active.pop()` → 移除

#### 8b. 添加后台清理线程

在 `if __name__ == "__main__":` 之前，应用启动后:

```python
def start_session_cleanup():
    """后台定期清理过期会话"""
    import threading
    def _cleanup_loop():
        while True:
            time.sleep(session_manager.CLEANUP_INTERVAL)
            try:
                session_manager.cleanup_expired_sessions()
            except Exception:
                pass
    t = threading.Thread(target=_cleanup_loop, daemon=True)
    t.start()

# 在 if __name__ == "__main__": 中，app.run() 之前调用
start_session_cleanup()
```

**验证:** 等待 5 分钟后检查数据库，过期会话应被标记为 `is_active=0`

---

## 执行顺序

```
Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7 → Task 8
  │                                                         │
  └── 数据库基础设施 ──→ 核心逻辑 ──→ API ──→ 前端 ──→ 管理员界面 ──→ 收尾清理
```

---

## 风险与注意事项

1. **多 worker 下 DB 连接竞争**: `session_manager` 每次操作都 `_get_conn()` → 用完 `close()`，避免连接池耗尽
2. **心跳频率**: 60 秒足以保持 30 分钟超时窗口内的活跃状态
3. **向后兼容**: 旧的 `ip_last_active` 逻辑保留但降级，不影响现有功能
4. **数据库压力**: 每次请求和心跳都写 DB，但 School_Web 是中小规模应用，MySQL 完全能承受
5. **session_key 唯一性**: 使用 `uuid.uuid4().hex` 生成，碰撞概率极低

---

## 未来可扩展

- WebSocket/SSE 实时推送在线状态变更
- 用户可配置是否允许多设备同时登录
- 登录设备管理（手机/电脑标识）
- 异地登录检测和通知
