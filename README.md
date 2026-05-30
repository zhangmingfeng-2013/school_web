# School_Web — 多功能校园 Web 工具箱

> 基于 Flask + Vue 3 构建的集成式 Web 应用平台，融合用户管理、系统监控、数据库工具、网络诊断、文件管理、毕业相册等模块。

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![License](https://img.shields.io/badge/License-GPLv2-green.svg)
![Platform](https://img.shields.io/badge/Platform-macOS/Linux-orange.svg)

---

## 目录

- [项目简介](#项目简介)
- [功能总览](#功能总览)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [配置说明](#配置说明)
- [API 概览](#api-概览)
- [安全管理](#安全管理)
- [开发指南](#开发指南)
- [部署建议](#部署建议)
- [常见问题](#常见问题)
- [联系方式](#联系方式)

---

## 项目简介

School_Web 是一个面向校园场景的 Web 多功能平台，采取前后端分离架构。它将日常校园管理、系统运维、班级互动等功能整合到同一套系统内，既可作为班级门户，也可用作内网工具箱。

**设计理念**
- **模块化** — 各功能独立，松耦合，可插拔
- **安全优先** — 内置速率限制、CSRF/XSS/SQL 注入防护、验证码、会话管理
- **低门槛** — 单 Flask 后端入口，Vue 3 前端，快速部署即可用

**适用场景**
- 班级管理系统（学生信息、成绩、活动）
- 校园信息平台（通知、资源共享）
- 毕业纪念展示（相册、寄语墙、大事记）
- 系统运维工具箱（监控、数据库、网络诊断）
- 开发者内网工具集

---

## 功能总览

### 🔐 用户管理与认证

| 功能 | 说明 |
|------|------|
| 注册/登录 | 支持管理员密钥注册管理员账号；集成图形验证码防自动化攻击 |
| 密码安全 | PBKDF2 哈希存储；旧版明文密码自动升级；密码强度校验（8位+字母+数字） |
| 防爆破 | 5次登录失败后锁定 15 分钟，自动记日志 |
| 会话管理 | 2 分钟无操作自动登出；登录时重新生成会话 ID 防固定攻击 |
| 密码找回 | 邮箱/安全问题重置密码 |
| 权限分级 | 管理员（全部功能） / 访客（基础功能） |

### 🛡️ 安全防护

- **IP 速率限制** — 默认 40 次 / 15 秒，超限封禁 240 秒；支持白名单、动态调整
- **验证码门禁** — 敏感操作前置验证码二次确认
- **CSRF / XSS / SQL 注入防护** — 令牌验证 + 输入清洗 + 参数化查询
- **安全响应头** — CSP / HSTS / X-Frame-Options / X-XSS-Protection / Referrer-Policy / Permissions-Policy
- **路径穿越防护** — 文件操作限制在用户主目录内
- **密码脱敏** — 查询结果中密码字段自动隐藏

### 🖥️ 系统监控（管理员）

实时监控 CPU / 内存 / 磁盘 / 网络，每 5 秒自动刷新。配套管理后台含 IP 统计、封禁/白名单管理、速率配置动态调节。

### 🗄️ 数据库工具

可视化表结构和数据浏览，支持增删改查（需二次验证码确认）、CSV 导出、密码脱敏、参数化查询防注入。

### 🌐 网络工具

- **IP 查询** — 域名解析、本地 IP、公网 IP
- **端口扫描** — 多线程，自定义端口范围（上限 200 个），结果可视化
- **OS 检测** — 基于 HTTP Server / RDP 等服务指纹推测目标系统
- **Ping 测试** — 连通性 + 延迟 + 丢包率

### 📁 文件管理器

目录浏览（限制在用户主目录）、上传（50 MB 限制）、下载、删除、重命名、预览（图片/文本/PDF）、拖拽上传、批量操作。

### 🎓 毕业相册（Vue 3 前端）

**核心**
- 图片上传（10 MB）/ 查看 / 点赞 / 评论 / 分享
- 标签筛选、弹幕互动、幻灯片轮播
- 数据统计（上传/评论/点赞排行）

**扩展组件**
- 大事记时间轴 · 同学录 · 寄语墙 · 标签系统
- 毕业歌单（投票） · 留言板 · 倒计时 · 聊天组件
- 瀑布流图片网格 · 统计图表

### 🧮 计算器

标准计算器 · 科学计算器（三角/指数/对数/阶乘） · 网络计算器（IP/子网掩码/网关）

### 💬 即时通讯 & 📝 备忘录

多人聊天室 + 消息历史；富文本笔记 + 保存/加载/导出/搜索。

---

## 技术栈

**后端**
| 技术 | 用途 |
|------|------|
| Flask 3.0+ | Web 框架 |
| PyMySQL 1.0+ | MySQL 数据库连接 |
| psutil | 系统资源监控 |
| Pillow | 图形验证码生成 |
| Werkzeug | 密码哈希（PBKDF2）、WSGI 工具 |
| Gunicorn | 生产环境 WSGI 服务器 |

**前端**
| 技术 | 用途 |
|------|------|
| Vue 3 (Composition API) | 前端框架 |
| Vite 5 | 构建工具 |
| Vue Router 4 | 路由管理 |
| Pinia 2 | 状态管理 |

**第三方集成**
Prism.js（代码高亮） · Font Awesome（图标） · Monaco Editor · Pyodide（浏览器内 Python）

---

## 快速开始

### 环境要求

| 依赖 | 版本建议 |
|------|----------|
| Python | 3.8+（推荐 3.10+） |
| Node.js | 16+（推荐 18+） |
| MySQL | 5.7+（推荐 8.0+） |

### 后端部署

```bash
# 1. 克隆
git clone https://gitee.com/zhang-mingfeng9773_admin_admin/tool-box-hub.git
cd School_Web

# 2. 虚拟环境（推荐）
python -m venv venv
source venv/bin/activate    # Linux/macOS
venv\Scripts\activate       # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置数据库
# 编辑 app.py 中的 DB_CONFIG，修改密码和数据库名

# 5. 建库建表（在 MySQL 中执行）
CREATE DATABASE IF NOT EXISTS sample;
USE sample;

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    User_Name VARCHAR(50) NOT NULL UNIQUE,
    User_Password VARCHAR(255) NOT NULL,
    Access_Permission VARCHAR(20) DEFAULT 'guest',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

# 6. 启动
python app.py
```

访问 `http://127.0.0.1:5800` 即可使用。

> 账户注册：普通注册为访客，填入管理员密钥（默认 `asdfghjkl;'`）即可注册为管理员。

### 前端（毕业相册）部署

```bash
cd frontend
npm install

# 开发模式（热更新）
npm run dev          # → http://localhost:3000

# 生产构建
npm run build        # → dist/，Flask 自动托管
npm run preview      # 预览构建产物
```

### Docker 部署

```bash
docker-compose up -d
```

参照根目录下的 `Dockerfile` 和 `docker-compose.yml`。

---

## 项目结构

```
School_Web/
├── app.py                    # Flask 主应用（单一入口）
├── session_manager.py        # 会话持久化管理
├── requirements.txt          # Python 依赖
├── gunicorn_config.py        # Gunicorn 配置
├── start_gunicorn.sh         # 生产启动脚本
│
├── frontend/                 # Vue 3 前端
│   ├── src/
│   │   ├── components/       # 16 个 Vue 组件（相册/聊天/时间轴/寄语墙…）
│   │   ├── App.vue           # 根组件
│   │   ├── main.js           # 入口
│   │   ├── api.js            # API 封装
│   │   └── style.css         # 全局样式
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
│
├── templates/                # Flask Jinja2 模板（~30 个页面）
├── static/                   # 静态资源
│   ├── avatars/              # 用户头像
│   ├── albums/               # 相册图片
│   └── projects/             # 项目文件
│
├── plugins/                  # 插件目录
├── i18n/                     # 国际化资源
├── .workflow/                # 工作流配置
├── backups/                  # 自动备份
│
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── 启动.sh                   # macOS 快速启动脚本
└── 安全措施清单.md            # 安全审计清单
```

---

## 配置说明

主要配置项集中在 `app.py` 顶部，支持通过环境变量覆盖：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FLASK_DEBUG` | `0` | 调试模式开关 |
| `ADMIN_SECRET` | `asdfghjkl;'` | 管理员注册密钥 |
| `SECRET_KEY` | 随机生成 | Flask 会话密钥 |

### 速率限制（管理后台可动态调整）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `RATE_LIMIT` | 40 | 时间窗口内最大请求数 |
| `RATE_WINDOW` | 15 秒 | 时间窗口 |
| `BLOCK_DURATION` | 240 秒 | 封禁时长 |
| `BLOCK_PROBE_LIMIT` | 200 | 封禁期间试探阈值 |
| `BLOCK_EXTEND` | 300 秒 | 试探超限追加时长 |

### 文件上传限制

```python
MAX_ALBUM_IMAGE_SIZE = 10 * 1024 * 1024   # 相册 10 MB
MAX_FILE_SIZE        = 50 * 1024 * 1024   # 文件管理器 50 MB
```

### 会话

```python
SESSION_IDLE_TIMEOUT          = 120   # 秒，无操作超时
PERMANENT_SESSION_LIFETIME    = 2 小时
```

---

## API 概览

### 认证

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | `/api/register` | 注册 | 公开 |
| POST | `/api/login` | 登录 | 公开 |
| GET  | `/api/logout` | 登出 | 已登录 |
| POST | `/api/change_password` | 修改密码 | 已登录 |
| POST | `/api/reset_password` | 重置密码 | 公开 |
| GET  | `/api/captcha` | 图形验证码 | 公开 |

### 相册

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET/POST | `/api/album/images` | 图片列表 / 上传 | 登录/管理员 |
| PUT/DELETE | `/api/album/images/<id>` | 修改 / 删除 | 管理员 |
| GET/POST/DELETE | `/api/album/images/<id>/like` | 点赞/取消 | 登录 |
| GET/POST | `/api/album/images/<id>/comments` | 评论列表/添加 | 登录 |
| GET/POST | `/api/album/images/<id>/tags` | 标签列表/设置 | 登录 |
| GET/POST | `/api/album/images/<id>/danmaku` | 弹幕列表/添加 | 登录 |
| GET/POST | `/api/album/images/<id>/share` | 分享链接 | 登录 |
| GET | `/api/album/images/<id>/download` | 下载 | 登录 |

### 系统管理（管理员）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/admin/ip_stats` | IP 访问统计 |
| DELETE | `/api/admin/ip_stats` | 清除统计 |
| GET/POST/DELETE | `/api/admin/whitelist` | 白名单管理 |
| POST | `/api/admin/manual_block` | 手动封禁 |
| POST | `/api/admin/batch` | 批量操作 |
| GET/POST | `/api/admin/rate_config` | 速率配置 R/W |
| GET | `/api/system_info` | 系统资源信息 |

### 数据库（管理员）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/db/tables` | 表列表 |
| POST | `/api/db/query` | 查询 |
| POST | `/api/db/update` | 更新（增删改） |

### 文件 / 网络工具

见 `app.py` 中的 `/api/files/*` 和 `/api/tools/*` 路由组。

---

## 安全管理

项目内置多层安全防护，详见 [`安全措施清单.md`](安全措施清单.md)：

- ✅ **速率限制** — 按 IP 统计，超限封禁
- ✅ **CSRF 保护** — 所有表单 + AJAX 需令牌
- ✅ **XSS 过滤** — 输入清洗 + 输出转义 + CSP
- ✅ **SQL 注入防护** — 参数化查询（禁止拼接 SQL）
- ✅ **会话安全** — HttpOnly Cookie、登录时刷新 SESSION ID、超时自动登出
- ✅ **文件安全** — 类型/大小/路径多重校验、路径穿越防护
- ✅ **安全响应头** — CSP / HSTS / X-Frame-Options / X-Content-Type-Options 等
- ✅ **密码安全** — Werkzeug PBKDF2 哈希、版本自动升级、强度校验

---

## 开发指南

### 本地开发

```bash
pip install -r requirements.txt
cd frontend && npm install

export FLASK_DEBUG=1
python app.py &               # 后端 :5800
cd frontend && npm run dev    # 前端 :3000（热更新）
```

### 代码规范

- Python 遵循 PEP 8
- Vue / JS 使用 ESLint
- 提交信息清晰，包含改动摘要
- 新增功能建议写单元测试

### 添加新功能模块

1. 在 `app.py` 中新增路由和视图函数
2. 创建对应的 Jinja2 模板（`templates/`）或 Vue 组件（`frontend/src/components/`）
3. 在模板中集成权限校验
4. 更新本 README 的功能列表

### 数据库主表结构

**users** — `id / User_Name / User_Password / Access_Permission / created_at`
**album_images** — `id / name / filename / category / uploader / upload_time / likes`
**album_comments** — `id / image_id / user / content / comment_time`
**album_likes** — `id / image_id / user`

其余相册相关的表（classmates / wishes / timeline / songs / tags 等）随功能扩展按需创建。

---

## 部署建议

### 生产环境

推荐使用 Gunicorn + Nginx 反向代理：

```bash
gunicorn -w 4 app:app -b 0.0.0.0:5800
```

Nginx 参考配置见下方；完整配置见 `gunicorn_config.py`。

```nginx
server {
    listen 80;
    server_name your-domain.com;
    client_max_body_size 100M;

    location / {
        proxy_pass http://127.0.0.1:5800;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static {
        alias /path/to/School_Web/static;
        expires 30d;
    }
}
```

### HTTPS（Let's Encrypt + Certbot）

```bash
certbot --nginx -d your-domain.com
certbot renew --dry-run  # 验证续期
```

### Systemd 服务

参照 `/etc/systemd/system/school-web.service` 模板，设置 WorkingDirectory、User、ExecStart 后：

```bash
sudo systemctl daemon-reload
sudo systemctl enable school-web
sudo systemctl start school-web
```

---

## 常见问题

**Q: 数据库连不上？**
检查 MySQL 是否运行、`app.py` 中 `DB_CONFIG` 的用户名/密码/数据库名是否准确、`sample` 数据库和 `users` 表是否已创建。

**Q: 验证码图片不显示？**
确认 `Pillow` 已安装，浏览器无 CSP 拦截，检查 `static/` 路径配置。

**Q: 上传图片失败？**
文件是否超过 10 MB？格式是否属于 jpg/png/gif/webp/bmp？`static/albums` 目录是否有写权限？

**Q: 正常请求被速率限制封了？**
把 IP 加到白名单（管理后台 → IP 管理），或调大 `RATE_LIMIT` / `RATE_WINDOW`。

**Q: 前端 `npm run build` 报错？**
Node.js 版本是否 ≥ 16？尝试删除 `node_modules` 和 `package-lock.json` 后重新 `npm install`。

---

## 联系方式

- 项目地址：<https://gitee.com/zhang-mingfeng9773_admin_admin/tool-box-hub>
- 提交 Issue：<https://gitee.com/zhang-mingfeng9773_admin_admin/tool-box-hub/issues>
- 📱 电话 / 微信：+86 151 2346 9773（工作日 20:00-21:00，周六 14:00-21:00/22:00，周日全天除凌晨）
- 💬 QQ：503175021
- 💬 微信：wxid_6t5bmudk2gnr12

如果这个项目有帮助到你，欢迎 ⭐ Star！ ❤️

---

## License

GNU General Public License v2.0 — 详见 [LICENSE](LICENSE)。

*最后更新：2026-05-28*
