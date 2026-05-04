# School_Web - 多功能工具箱 Web 应用

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![License](https://img.shields.io/badge/License-GPLv2-green.svg)
![Platform](https://img.shields.io/badge/Platform-macOS%20|%20Linux%20|%20Windows-orange.svg)

> 基于 Flask + Vue 3 构建的集成式 Web 工具箱应用，提供用户管理、系统监控、数据库操作、文件管理、毕业相册等丰富功能。

---

## 📋 目录

- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [API 接口文档](#api-接口文档)
- [配置说明](#配置说明)
- [使用指南](#使用指南)
- [安全特性](#安全特性)
- [开发指南](#开发指南)
- [部署建议](#部署建议)
- [更新日志](#更新日志)
- [许可证](#许可证)

---

## ✨ 功能特性

### 🔐 用户管理与认证系统

| 功能 | 描述 |
|------|------|
| 用户注册 | 支持管理员密钥注册管理员账号，普通注册为访客账号 |
| 安全登录 | 集成图形验证码，防止自动化攻击 |
| 密码安全 | 密码使用 Werkzeug PBKDF2 哈希加密存储 |
| 登录防爆破 | 5次登录失败后账号锁定15分钟 |
| 会话管理 | 支持安全的会话存储，2分钟无操作自动登出 |
| 密码修改 | 支持验证码验证，管理员可修改任意用户密码 |

### 🛡️ 安全防护机制

- **IP 速率限制**：可配置请求数（默认40次/15秒）和封禁时长（默认240秒）
- **IP 白名单**：支持手动添加/移除白名单 IP，免受速率限制
- **全站验证码门禁**：敏感操作前需完成验证码验证
- **CSRF 令牌保护**：所有表单提交均需验证 CSRF 令牌
- **安全响应头**：配置 CSP、HSTS、X-Frame-Options、X-XSS-Protection 等安全头
- **输入清洗**：自动过滤 HTML/JS 标签，防止 XSS 攻击
- **SQL 注入防护**：使用参数化查询，禁止直接拼接 SQL

### 🖥️ 系统管理（管理员专属）

| 功能 | 描述 |
|------|------|
| 实时系统监控 | CPU、内存、磁盘、网络使用情况实时展示，每5秒自动刷新 |
| 管理后台仪表盘 | IP 访问统计、封禁状态一览、速率配置管理 |
| 日志管理 | 系统操作日志的查看与清空 |
| IP 管理 | 支持封禁、解封、白名单操作，支持批量操作 |
| 速率配置 | 动态调整速率限制参数，无需重启服务 |

### 🗄️ 数据库工具

- **可视化查询**：支持查看数据库表结构和数据
- **数据管理**：支持增删改查操作
- **安全验证**：数据库操作需二次验证码确认
- **密码脱敏**：查询结果中密码字段自动脱敏显示

### 🌐 网络工具

| 功能 | 描述 |
|------|------|
| IP 查询 | 支持域名解析、本地 IP、公网 IP 查询 |
| 端口扫描 | 多线程端口扫描，支持自定义端口范围（最多200个端口） |
| 操作系统检测 | 通过端口服务特征（HTTP Server、RDP等）推测目标 OS |

### 📁 文件管理器

- **目录浏览**：安全的文件系统导航（限制在用户主目录，防止路径穿越）
- **文件操作**：上传（50MB限制）、下载、删除
- **二次验证**：访问需密码验证，增强安全性

### 🎓 毕业相册（Vue 3 前端）

#### 核心功能
- **图片管理**：上传（10MB限制）、查看、下载、删除图片
- **互动功能**：点赞、评论、分享链接生成（无需登录即可访问）
- **数据统计**：上传排行、评论排行、点赞排行

#### 扩展功能
| 模块 | 描述 |
|------|------|
| 大事记时间轴 | 记录班级重要时间节点和事件 |
| 同学录 | 班级同学信息管理，包含头像、生日、联系方式等 |
| 寄语墙 | 支持匿名/实名发布毕业寄语 |
| 标签系统 | 照片标签分类管理，支持筛选 |
| 毕业歌单 | 歌曲推荐与投票功能 |
| 弹幕功能 | 图片弹幕互动 |

### 🧮 工具集

| 工具 | 描述 |
|------|------|
| 标准计算器 | 基础数学运算：加减乘除、百分比、倒数等 |
| 科学计算器 | 三角函数、指数、对数、阶乘等高级运算 |
| 网络计算器 | IP 地址、子网掩码、网关计算 |
| 备忘录 | 支持文本编辑的笔记记录工具 |

---

## 🛠️ 技术栈

### 后端技术栈

| 技术 | 版本 | 用途 | 说明 |
|------|------|------|------|
| Flask | 3.0+ | Web 框架 | 轻量级 Python Web 框架 |
| PyMySQL | 1.0+ | MySQL 数据库连接 | 纯 Python MySQL 驱动 |
| psutil | 5.0+ | 系统资源监控 | 获取 CPU、内存、磁盘、网络信息 |
| Pillow | 9.0+ | 图形验证码生成 | 生成带干扰线和噪点的验证码图片 |
| Werkzeug | 3.0+ | 密码哈希、WSGI 工具 | PBKDF2 密码哈希算法 |
| requests | 2.0+ | HTTP 请求 | 用于公网 IP 查询等外部 API 调用 |
| flask-cors | 4.0+ | 跨域资源共享 | 支持前后端分离架构 |

### 前端技术栈

| 技术 | 版本 | 用途 | 说明 |
|------|------|------|------|
| Vue | 3.4+ | 前端框架 | 渐进式 JavaScript 框架 |
| Vite | 5.0+ | 构建工具 | 快速冷启动、热模块替换 |
| Vue Router | 4.3+ | 路由管理 | Vue 官方路由库 |
| Pinia | 2.1+ | 状态管理 | Vue 官方状态管理库 |

---

## � 快速开始

### 环境要求

| 依赖 | 版本要求 | 说明 |
|------|----------|------|
| Python | 3.8+ | 后端运行环境 |
| Node.js | 16+ | 前端构建环境 |
| MySQL | 5.7+ | 数据库 |

### 后端部署步骤

1. **克隆项目**：
```bash
git clone <repository-url>
cd School_Web
```

2. **安装 Python 依赖**：
```bash
pip install -r requirements.txt
```

3. **配置数据库连接**：
编辑 `app.py` 文件，修改数据库配置：
```python
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "your_database_password",
    "database": "your_database_name"
}
```

4. **创建数据库和用户表**：
```sql
CREATE DATABASE IF NOT EXISTS sample;
USE sample;

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    User_Name VARCHAR(50) NOT NULL UNIQUE,
    User_Password VARCHAR(255) NOT NULL,
    Access_Permission VARCHAR(20) DEFAULT 'guest',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

5. **启动服务**：
```bash
python app.py
```

服务启动后访问地址：
- 本地访问：http://127.0.0.1:5800
- 局域网访问：http://192.168.x.x:5800

### 前端部署步骤（毕业相册）

1. **进入前端目录**：
```bash
cd frontend
```

2. **安装 Node.js 依赖**：
```bash
npm install
```

3. **开发模式运行**（热更新）：
```bash
npm run dev
```

4. **构建生产版本**：
```bash
npm run build
```

构建产物将输出到 `frontend/dist/` 目录，Flask 会自动提供这些静态文件。

---

## �📁 项目结构

```
School_Web/                              # 项目根目录
├── app.py                               # Flask 主应用入口
├── requirements.txt                     # Python 依赖列表
├── .secret_key                          # Flask 密钥（首次运行自动生成）
├── rate_config.json                     # 速率限制配置（自动生成）
├── ip_whitelist.json                    # IP 白名单配置（自动生成）
├── frontend/                            # Vue 3 前端项目
│   ├── src/
│   │   ├── components/                  # Vue 组件目录
│   │   │   ├── Classmates.vue           # 同学录组件
│   │   │   ├── CountDown.vue            # 倒计时组件
│   │   │   ├── Danmaku.vue              # 弹幕组件
│   │   │   ├── ImageDetailModal.vue     # 图片详情弹窗
│   │   │   ├── ImageGrid.vue            # 图片网格展示
│   │   │   ├── MessageBoard.vue         # 留言板组件
│   │   │   ├── MusicPlayer.vue          # 音乐播放器组件
│   │   │   ├── Playlist.vue             # 歌单组件
│   │   │   ├── Slideshow.vue            # 幻灯片组件
│   │   │   ├── StatsChart.vue           # 统计图表组件
│   │   │   ├── TagFilter.vue            # 标签过滤器组件
│   │   │   ├── Timeline.vue             # 时间轴组件
│   │   │   ├── TopBar.vue               # 顶部导航栏组件
│   │   │   ├── UploadModal.vue          # 上传弹窗组件
│   │   │   └── WishWall.vue             # 寄语墙组件
│   │   ├── App.vue                      # 根组件（入口）
│   │   ├── main.js                      # 入口文件
│   │   ├── api.js                       # API 请求封装
│   │   └── style.css                    # 全局样式
│   ├── dist/                            # 构建输出目录
│   ├── index.html                       # HTML 模板
│   ├── package.json                     # Node.js 依赖配置
│   └── vite.config.js                   # Vite 构建配置
├── templates/                           # Flask Jinja2 模板
│   ├── admin_dashboard.html             # 管理后台仪表盘
│   ├── album_vue3.html                  # 相册入口页面
│   ├── base.html                        # 基础模板（继承用）
│   ├── calculator.html                  # 标准计算器页面
│   ├── calculator_net.html              # 网络计算器页面
│   ├── calculator_sci.html              # 科学计算器页面
│   ├── change_password.html             # 修改密码页面
│   ├── dashboard.html                   # 用户仪表盘
│   ├── db_captcha.html                  # 数据库操作验证码页面
│   ├── db_query.html                    # 数据库查询页面
│   ├── db_update.html                   # 数据库管理页面
│   ├── file_manager.html                # 文件管理器页面
│   ├── fm_password.html                 # 文件管理器密码验证页面
│   ├── global_captcha.html              # 全局验证码页面
│   ├── login.html                       # 登录页面
│   ├── logout_confirm.html              # 登出确认页面
│   ├── logs.html                        # 日志查看页面
│   ├── network_tools.html               # 网络工具页面
│   ├── notes.html                       # 备忘录页面
│   ├── register.html                    # 注册页面
│   └── system_monitor.html              # 系统监控页面
├── static/                              # 静态资源目录
│   ├── albums/                          # 相册图片存储
│   └── projects/                        # 项目文件存储
└── __pycache__/                         # Python 编译缓存（自动生成）
```

---

## 🔌 API 接口文档

### 相册相关接口

| 接口路径 | HTTP 方法 | 功能描述 | 权限要求 |
|----------|----------|----------|----------|
| `/api/album/images` | GET | 获取图片列表 | 登录用户 |
| `/api/album/images` | POST | 上传图片 | 管理员/教师 |
| `/api/album/images/<int:id>` | PUT | 修改图片名称 | 管理员 |
| `/api/album/images/<int:id>` | DELETE | 删除图片 | 管理员 |
| `/api/album/images/<int:id>/like` | GET | 获取点赞状态 | 登录用户 |
| `/api/album/images/<int:id>/like` | POST | 点赞图片 | 登录用户 |
| `/api/album/images/<int:id>/like` | DELETE | 取消点赞 | 登录用户 |
| `/api/album/images/<int:id>/download` | GET | 下载图片 | 登录用户 |
| `/api/album/images/<int:id>/share` | GET | 获取分享链接 | 登录用户 |
| `/api/album/images/<int:id>/share` | POST | 生成分享链接 | 登录用户 |
| `/api/album/images/<int:id>/comments` | GET | 获取图片评论 | 登录用户 |
| `/api/album/images/<int:id>/comments` | POST | 添加图片评论 | 登录用户 |
| `/api/album/images/<int:id>/tags` | GET | 获取图片标签 | 登录用户 |
| `/api/album/images/<int:id>/tags` | POST | 设置图片标签 | 登录用户 |
| `/api/album/images/<int:id>/danmaku` | GET | 获取图片弹幕 | 登录用户 |
| `/api/album/images/<int:id>/danmaku` | POST | 添加弹幕 | 登录用户 |

### 相册扩展功能接口

| 接口路径 | HTTP 方法 | 功能描述 | 权限要求 |
|----------|----------|----------|----------|
| `/api/album/events` | GET | 获取大事记列表 | 公开 |
| `/api/album/events` | POST | 添加大事记 | 管理员 |
| `/api/album/events/<int:id>` | DELETE | 删除大事记 | 管理员 |
| `/api/album/classmates` | GET | 获取同学录列表 | 公开 |
| `/api/album/classmates` | POST | 添加同学录 | 登录用户 |
| `/api/album/classmates/<int:id>` | DELETE | 删除同学录 | 管理员 |
| `/api/album/wishes` | GET | 获取寄语列表 | 公开 |
| `/api/album/wishes` | POST | 添加寄语 | 登录用户 |
| `/api/album/wishes/<int:id>` | DELETE | 删除寄语 | 管理员/本人 |
| `/api/album/tags` | GET | 获取标签列表 | 公开 |
| `/api/album/tags` | POST | 添加标签 | 登录用户 |
| `/api/album/tags/<int:id>` | DELETE | 删除标签 | 登录用户 |
| `/api/album/playlist` | GET | 获取歌单列表 | 公开 |
| `/api/album/playlist` | POST | 添加歌曲 | 登录用户 |
| `/api/album/playlist/<int:id>/vote` | POST | 投票歌曲 | 登录用户 |
| `/api/album/playlist/<int:id>` | DELETE | 删除歌曲 | 管理员 |
| `/api/album/comments` | GET | 获取总体留言 | 登录用户 |
| `/api/album/comments` | POST | 添加总体留言 | 登录用户 |
| `/api/album/comments/<int:id>` | DELETE | 删除总体留言 | 管理员/本人 |
| `/api/album/stats` | GET | 获取统计数据 | 登录用户 |
| `/api/album/me` | GET | 获取当前用户信息 | 登录用户 |

### 管理后台接口

| 接口路径 | HTTP 方法 | 功能描述 | 权限要求 |
|----------|----------|----------|----------|
| `/api/admin/ip_stats` | GET | 获取 IP 访问统计 | 管理员 |
| `/api/admin/ip_stats` | DELETE | 清除 IP 统计 | 管理员 |
| `/api/admin/unblock` | POST | 解封指定 IP | 管理员 |
| `/api/admin/whitelist` | GET | 获取白名单列表 | 管理员 |
| `/api/admin/whitelist` | POST | 添加 IP 到白名单 | 管理员 |
| `/api/admin/whitelist` | DELETE | 从白名单移除 IP | 管理员 |
| `/api/admin/manual_block` | POST | 手动封禁 IP | 管理员 |
| `/api/admin/batch` | POST | 批量操作（白名单/封禁） | 管理员 |
| `/api/admin/rate_config` | GET | 获取速率限制配置 | 管理员 |
| `/api/admin/rate_config` | POST | 修改速率限制配置 | 管理员 |

### 系统信息接口

| 接口路径 | HTTP 方法 | 功能描述 | 权限要求 |
|----------|----------|----------|----------|
| `/api/system_info` | GET | 获取系统资源信息 | 管理员 |
| `/api/captcha` | GET | 获取图形验证码 | 公开 |

---

## ⚙️ 配置说明

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `FLASK_DEBUG` | `0` | 是否开启调试模式（1=开启，0=关闭） |
| `ADMIN_SECRET` | `asdfghjkl;'` | 管理员注册密钥 |

### 速率限制参数

可在管理后台动态调整，无需重启服务：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `RATE_LIMIT` | 40 | 时间窗口内最大请求数 |
| `RATE_WINDOW` | 15 | 时间窗口（秒） |
| `BLOCK_DURATION` | 240 | 封禁时长（秒） |
| `BLOCK_PROBE_LIMIT` | 200 | 封禁期间试探阈值 |
| `BLOCK_EXTEND` | 300 | 试探超限时追加封禁时长（秒） |

### 数据库配置

```python
# app.py 中的数据库配置
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "your_password",
    "database": "sample"
}
```

---

## 📖 使用指南

### 注册账号

1. 访问 http://localhost:5800/register
2. 填写用户名和密码（密码需至少8位，包含字母和数字）
3. 如需注册管理员账号，填写管理员密钥（默认：`asdfghjkl;'`）
4. 点击注册完成账号创建

### 登录系统

1. 访问 http://localhost:5800/
2. 输入用户名和密码
3. 输入图形验证码
4. 点击登录进入系统

### 权限说明

| 权限等级 | 可访问功能 |
|----------|------------|
| **管理员** | 所有功能：系统监控、数据库管理、文件管理、日志查看、相册管理等 |
| **访客** | 基础功能：相册浏览、计算器、备忘录 |

### 毕业相册使用指南

#### 上传图片
1. 登录后访问 `/album` 进入相册首页
2. 点击上传按钮，选择图片文件（支持 jpg、png、gif、webp、bmp）
3. 填写图片名称和分类
4. 点击上传完成

#### 互动功能
1. 点击图片查看详情
2. 点击点赞按钮为图片点赞
3. 在评论框输入评论并发送
4. 点击分享按钮生成公开分享链接

#### 管理功能
1. **同学录管理**：点击同学录标签，添加或删除同学信息
2. **寄语墙**：发布匿名或实名寄语
3. **歌单管理**：添加歌曲并投票
4. **标签管理**：创建和管理图片标签

### 系统监控使用指南

1. 访问 `/system_monitor`（需管理员权限）
2. 查看 CPU、内存、磁盘、网络的实时使用情况
3. 数据每5秒自动刷新

### 数据库工具使用指南

1. 访问 `/db_query`（需非访客权限）
2. 输入验证码完成安全验证
3. 选择数据库表查看数据
4. 访问 `/db_update` 进行数据增删改操作

---

## 🔒 安全特性

### 认证安全

- 使用图形验证码防止自动化攻击
- 登录失败5次后账号锁定15分钟
- 密码使用 Werkzeug PBKDF2 哈希加密
- 支持旧版明文密码自动升级为哈希存储

### 请求安全

- CSRF 令牌验证
- IP 速率限制防止暴力攻击
- 输入清洗过滤 HTML/JS 标签
- 参数化查询防止 SQL 注入
- 安全响应头配置（CSP、HSTS、X-Frame-Options 等）

### 文件安全

- 文件路径安全检查，防止路径穿越攻击
- 文件大小限制（相册10MB，文件管理器50MB）
- 文件类型验证（通过文件魔数检测）
- 文件上传需管理员权限

### 会话安全

- 会话超时自动登出（2分钟无操作）
- Session Cookie 设置 HttpOnly 和 SameSite 属性
- 定期更换 CSRF 令牌

---

## 🛠️ 开发指南

### 开发环境搭建

1. **安装依赖**：
```bash
pip install -r requirements.txt
cd frontend && npm install
```

2. **配置开发环境**：
```bash
export FLASK_DEBUG=1
```

3. **启动后端**：
```bash
python app.py
```

4. **启动前端开发服务器**：
```bash
cd frontend && npm run dev
```

### 代码规范

- Python 代码遵循 PEP 8 规范
- JavaScript/Vue 代码使用 ESLint 检查
- 变量命名使用下划线命名法（Python）或驼峰命名法（JavaScript）
- 函数和方法命名清晰，避免使用缩写

### 测试建议

1. **功能测试**：测试各个功能模块是否正常工作
2. **安全测试**：测试 SQL 注入、XSS、CSRF 等安全漏洞
3. **性能测试**：测试速率限制、系统监控等功能
4. **兼容性测试**：测试不同浏览器和设备的兼容性

---

## 📦 部署建议

### 生产环境部署

1. **使用 Gunicorn 作为 WSGI 服务器**：
```bash
pip install gunicorn
gunicorn -w 4 app:app -b 0.0.0.0:5800
```

2. **配置 Nginx 反向代理**：
```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://127.0.0.1:5800;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

3. **启用 HTTPS**：
```bash
# 使用 Let's Encrypt 获取 SSL 证书
certbot --nginx -d your-domain.com
```

### Docker 部署（可选）

创建 `Dockerfile`：
```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5800

CMD ["gunicorn", "-w", "4", "app:app", "-b", "0.0.0.0:5800"]
```

---

## 📝 更新日志

### v1.0.0（2024年）
- 初始版本发布
- 集成用户认证系统
- 实现系统监控功能
- 数据库工具模块
- 网络工具模块
- 文件管理器模块
- 毕业相册模块（Vue 3）
- 计算器工具（标准/科学/网络）
- 备忘录功能
- 安全防护机制（速率限制、CSRF、XSS防护）

---

## 📄 许可证

MIT License

Copyright (c) 2024 School_Web

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

## 📧 联系方式

如有问题或建议，请通过以下方式联系：

- 项目地址：<repository-url>
- 提交 Issue：<issues-url>
