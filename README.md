# School_Web - 多功能 Web 工具箱应用

> 基于 Flask + Vue 3 构建的集成式 Web 应用平台，提供用户管理、系统监控、数据库操作、网络工具、文件管理、毕业相册等全方位功能模块。

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![License](https://img.shields.io/badge/License-GPLv2-green.svg)
![Platform](https://img.shields.io/badge/Platform-macOS-orange.svg)
![Gitee Stars](https://gitee.com/zhang-mingfeng9773_admin_admin/tool-box-hub/badge/star.svg?theme=dark)
![Gitee Forks](https://gitee.com/zhang-mingfeng9773_admin_admin/tool-box-hub/badge/fork.svg?theme=dark)

***

## 📖 目录导航

<details>
<summary>点击展开/折叠完整目录</summary>

- [项目简介](#-项目简介)
  - [设计理念](#设计理念)
  - [适用场景](#适用场景)
- [功能特性](#-功能特性)
  - [🔐 用户管理与认证系统](#-用户管理与认证系统)
  - [🛡️ 安全防护机制](#️-安全防护机制)
  - [🖥️ 系统管理](#️-系统管理)
  - [🗄️ 数据库工具](#️-数据库工具)
  - [🌐 网络工具](#-网络工具)
  - [📁 文件管理器](#-文件管理器)
  - [🎓 毕业相册](#-毕业相册)
  - [🧮 计算器工具集](#-计算器工具集)
  - [💬 即时通讯](#-即时通讯)
  - [📝 备忘录](#-备忘录)
- [技术栈](#️-技术栈)
  - [后端技术栈](#后端技术栈)
  - [前端技术栈](#前端技术栈)
  - [第三方库](#第三方库)
  - [开发工具](#开发工具)
  - [运行环境要求](#运行环境要求)
- [项目结构](#-项目结构)
- [快速开始](#-快速开始)
  - [环境要求](#环境要求)
  - [后端部署步骤](#后端部署步骤)
  - [前端部署步骤](#前端部署步骤)
  - [Docker 部署](#docker-部署)
- [详细功能介绍](#-详细功能介绍)
  - [🔐 用户认证系统](#-用户认证系统-1)
  - [🖥️ 系统监控](#️-系统监控-1)
  - [🎓 毕业相册](#-毕业相册-1)
  - [🌐 网络工具](#-网络工具-1)
  - [📁 文件管理器](#-文件管理器-1)
  - [🗄️ 数据库工具](#️-数据库工具-1)
- [🔌 API 接口文档](#-api-接口文档)
  - [认证接口](#认证接口)
  - [相册接口](#相册接口)
  - [系统管理接口](#系统管理接口)
  - [数据库接口](#数据库接口)
  - [文件管理接口](#文件管理接口)
  - [网络工具接口](#网络工具接口)
- [🔒 安全特性](#-安全特性)
  - [认证安全](#认证安全)
  - [请求安全](#请求安全)
  - [文件安全](#文件安全)
  - [会话安全](#会话安全)
  - [安全响应头配置](#安全响应头配置)
  - [CSRF 防护](#csrf-防护)
  - [XSS 防护](#xss-防护)
  - [SQL 注入防护](#sql-注入防护)
  - [路径穿越防护](#路径穿越防护)
- [⚙️ 配置说明](#️-配置说明)
  - [环境变量](#环境变量)
  - [速率限制参数](#速率限制参数)
  - [数据库配置](#数据库配置)
  - [文件上传限制](#文件上传限制)
  - [会话配置](#会话配置)
  - [CSP 配置](#csp-配置)
- [📖 使用指南](#-使用指南)
  - [注册账号](#注册账号)
  - [登录系统](#登录系统)
  - [权限说明](#权限说明)
  - [毕业相册使用指南](#毕业相册使用指南)
  - [系统监控使用指南](#系统监控使用指南)
  - [数据库工具使用指南](#数据库工具使用指南)
  - [网络工具使用指南](#网络工具使用指南)
  - [文件管理器使用指南](#文件管理器使用指南)
- [🛠️ 开发指南](#️-开发指南)
  - [开发环境搭建](#开发环境搭建)
  - [代码规范](#代码规范)
  - [数据库表结构](#数据库表结构)
  - [扩展开发](#扩展开发)
  - [测试建议](#测试建议)
- [📦 部署建议](#-部署建议)
  - [生产环境部署](#生产环境部署)
  - [Nginx 反向代理](#nginx-反向代理)
  - [HTTPS 配置](#https-配置)
  - [Systemd 服务配置](#systemd-服务配置)
  - [负载均衡](#负载均衡)
- [❓ 常见问题](#-常见问题)
- [📝 更新日志](#-更新日志)
- [🤝 贡献指南](#-贡献指南)
- [📞 联系方式](#-联系方式)
- [🌟 致谢](#-致谢)
- [📚 参考资料](#-参考资料)

</details>

***

## 📖 项目简介

School_Web 是一个功能丰富的 Web 应用平台，专为校园场景设计。它集成了用户认证、系统监控、数据库管理、文件操作、网络工具、毕业相册等多种功能于一体，采用现代的前后端分离架构，使用 Flask 作为后端框架，Vue 3 作为前端框架，提供了出色的用户体验和开发体验。

### 设计理念

- **模块化设计**：各个功能模块相互独立，可单独扩展，降低耦合度
- **安全优先**：内置多种安全机制，保护系统和用户数据，防范常见 Web 攻击
- **用户友好**：直观的界面设计，简单易用，降低学习成本
- **可扩展性**：支持插件式开发，方便添加新功能，适应不同场景需求
- **高性能**：采用异步处理和缓存策略，提升系统响应速度
- **可维护性**：清晰的代码结构和完善的文档，便于后续维护和升级

### 适用场景

- 🎓 班级管理系统：学生信息管理、成绩统计、班级活动组织
- 🏫 校园信息平台：校园新闻发布、通知推送、资源共享
- 📸 毕业纪念展示：毕业相册、寄语墙、同学录、大事记时间轴
- 🖥️ 系统管理工具：服务器监控、日志分析、性能优化
- 🔧 开发者工具箱：数据库管理、网络诊断、文件操作、计算器
- 💬 即时通讯平台：班级群聊、实时消息推送、文件共享
- 📊 数据可视化平台：实时数据展示、统计分析、报表生成

***

## ✨ 功能特性

### 🔐 用户管理与认证系统

| 功能 | 描述 |
|------|------|
| 🔑 用户注册 | 支持管理员密钥注册管理员账号，普通注册为访客账号，密码强度校验 |
| 🛡️ 安全登录 | 集成图形验证码，防止自动化攻击，支持记住登录状态 |
| 🔒 密码安全 | 密码使用 Werkzeug PBKDF2 哈希加密存储，防止泄露 |
| 🚫 登录防爆破 | 5次登录失败后账号锁定15分钟，自动记录失败日志 |
| ⏱️ 会话管理 | 支持安全的会话存储，2分钟无操作自动登出，保障账户安全 |
| 🔐 密码修改 | 支持验证码验证，管理员可修改任意用户密码，旧版密码自动升级 |
| 📧 忘记密码 | 通过邮箱或安全问题重置密码，保障账户找回 |
| 👤 个人资料 | 用户可编辑个人信息和头像，支持自定义昵称和签名 |

**功能亮点：**
- 密码强度校验：至少8位，包含字母和数字
- 旧版明文密码自动升级为 PBKDF2 哈希存储
- 登录失败次数实时统计，自动解锁机制
- 会话超时自动登出，防止账户被他人使用

### 🛡️ 安全防护机制

- **IP 速率限制**：可配置请求数（默认40次/15秒）和封禁时长（默认240秒）
- **IP 白名单**：支持手动添加/移除白名单 IP，免受速率限制
- **全站验证码门禁**：敏感操作前需完成验证码验证
- **CSRF 令牌保护**：所有表单提交均需验证 CSRF 令牌
- **安全响应头**：配置 CSP、HSTS、X-Frame-Options、X-XSS-Protection 等安全头
- **输入清洗**：自动过滤 HTML/JS 标签，防止 XSS 攻击
- **SQL 注入防护**：使用参数化查询，禁止直接拼接 SQL
- **会话固定防护**：登录时重新生成会话 ID
- **文件上传安全**：文件大小、类型、路径多重校验
- **密码脱敏**：查询结果中密码字段自动脱敏显示

### 🖥️ 系统管理（管理员专属）

| 功能 | 描述 |
|------|------|
| 📊 实时系统监控 | CPU、内存、磁盘、网络使用情况实时展示，每5秒自动刷新 |
| 📈 管理后台仪表盘 | IP 访问统计、封禁状态一览、速率配置管理 |
| 📝 日志管理 | 系统操作日志的查看与清空，支持按时间筛选 |
| 🔒 IP 管理 | 支持封禁、解封、白名单操作，支持批量操作 |
| ⚡ 速率配置 | 动态调整速率限制参数，无需重启服务 |
| ℹ️ 系统信息 | 显示操作系统、主机名、运行时间等信息 |

**监控指标：**
- CPU 使用率、负载情况
- 内存使用情况（总内存、已用内存、可用内存）
- 磁盘使用情况（总空间、已用空间、可用空间、使用率）
- 网络流量统计（发送/接收字节数、数据包数）

### 🗄️ 数据库工具

- **可视化查询**：支持查看数据库表结构和数据
- **数据管理**：支持增删改查操作，二次验证码确认
- **密码脱敏**：查询结果中密码字段自动脱敏显示
- **表结构查看**：查看字段类型、长度、是否为空等信息
- **数据导出**：支持导出查询结果为 CSV 格式
- **批量操作**：支持批量插入、更新、删除
- **事务管理**：支持事务回滚，保障数据一致性

**安全特性：**
- 数据库操作需二次验证码确认
- 参数化查询防止 SQL 注入
- 敏感字段自动脱敏
- 操作日志完整记录

### 🌐 网络工具

| 功能 | 描述 |
|------|------|
| 🔍 IP 查询 | 支持域名解析、本地 IP、公网 IP 查询 |
| 🚪 端口扫描 | 多线程端口扫描，支持自定义端口范围（最多200个端口） |
| 💻 操作系统检测 | 通过端口服务特征（HTTP Server、RDP等）推测目标 OS |
| 📡 Ping 测试 | 测试网络连通性和延迟 |

**功能特点：**
- 端口扫描采用多线程，提高扫描速度
- 智能 OS 检测算法，基于服务特征识别
- 支持 CIDR 格式 IP 范围扫描
- 扫描结果可视化展示

### 📁 文件管理器

- **目录浏览**：安全的文件系统导航（限制在用户主目录，防止路径穿越）
- **文件操作**：上传（50MB限制）、下载、删除、重命名
- **二次验证**：访问需密码验证，增强安全性
- **文件预览**：支持图片、文本、PDF 等常见格式预览
- **批量操作**：支持批量删除、批量下载文件
- **拖拽上传**：支持拖拽文件上传，操作更便捷

**安全特性：**
- 路径穿越防护
- 文件大小和类型限制
- 上传文件自动重命名，防止覆盖
- 操作日志记录

### 🎓 毕业相册（Vue 3 前端）

#### 核心功能

- **图片管理**：上传（10MB限制）、查看、下载、删除图片
- **互动功能**：点赞、评论、分享链接生成（无需登录即可访问）
- **数据统计**：上传排行、评论排行、点赞排行
- **标签系统**：照片标签分类管理，支持筛选
- **弹幕功能**：图片弹幕互动，增加趣味性
- **幻灯片**：图片轮播展示，适合班级展示

#### 扩展功能

| 模块 | 描述 |
|------|------|
| 📅 大事记时间轴 | 记录班级重要时间节点和事件 |
| 👥 同学录 | 班级同学信息管理，包含头像、生日、联系方式等 |
| 💌 寄语墙 | 支持匿名/实名发布毕业寄语 |
| 🏷️ 标签系统 | 照片标签分类管理，支持筛选 |
| 🎵 毕业歌单 | 歌曲推荐与投票功能 |
| 💬 弹幕功能 | 图片弹幕互动 |
| 🎬 幻灯片 | 图片轮播展示 |
| 📝 留言板 | 班级留言和互动 |

#### 特色组件

- `ImageGrid` - 图片网格展示组件，支持瀑布流布局
- `ImageDetailModal` - 图片详情弹窗组件，包含点赞、评论、分享功能
- `Classmates` - 同学录组件，支持添加、编辑、删除同学信息
- `Timeline` - 时间轴组件，按时间顺序展示重要事件
- `WishWall` - 寄语墙组件，支持随机颜色卡片布局
- `TagFilter` - 标签过滤组件，快速筛选图片
- `MusicPlayer` - 音乐播放器组件，支持播放列表
- `Playlist` - 歌单组件，支持投票排序
- `Danmaku` - 弹幕组件，支持滚动弹幕
- `CountDown` - 倒计时组件，毕业倒计时
- `StatsChart` - 统计图表组件，数据可视化
- `Chat` - 聊天组件，实时通讯
- `TopBar` - 顶部导航栏组件
- `UploadModal` - 上传弹窗组件，支持拖拽上传
- `Slideshow` - 幻灯片组件，支持自动播放

### 🧮 计算器工具集

| 工具 | 描述 |
|------|------|
| 🔢 标准计算器 | 基础数学运算：加减乘除、百分比、倒数等 |
| 📐 科学计算器 | 三角函数、指数、对数、阶乘等高级运算 |
| 🌐 网络计算器 | IP 地址、子网掩码、网关计算 |

### 💬 即时通讯

- 支持实时聊天功能
- 支持多人聊天室
- 支持消息历史记录
- 支持文件传输
- 支持表情和富文本
- 支持在线状态显示

### 📝 备忘录

- 支持文本编辑的笔记记录工具
- 支持富文本格式
- 支持保存和加载
- 支持导出为文件
- 支持搜索和筛选

***

## 🛠️ 技术栈

### 后端技术栈

| 技术 | 版本 | 用途 | 说明 |
|------|------|------|------|
| Flask | 3.0+ | Web 框架 | 轻量级 Python Web 框架，提供路由、模板、会话等功能 |
| PyMySQL | 1.0+ | MySQL 数据库连接 | 纯 Python MySQL 驱动，支持连接池 |
| psutil | 5.0+ | 系统资源监控 | 获取 CPU、内存、磁盘、网络信息 |
| Pillow | 9.0+ | 图形验证码生成 | 生成带干扰线和噪点的验证码图片 |
| Werkzeug | 3.0+ | 密码哈希、WSGI 工具 | PBKDF2 密码哈希算法，安全的密码存储 |
| requests | 2.0+ | HTTP 请求 | 用于公网 IP 查询等外部 API 调用 |
| flask-cors | 4.0+ | 跨域资源共享 | 支持前后端分离架构，允许跨域请求 |

### 前端技术栈

| 技术 | 版本 | 用途 | 说明 |
|------|------|------|------|
| Vue | 3.4+ | 前端框架 | 渐进式 JavaScript 框架，Composition API |
| Vite | 5.0+ | 构建工具 | 快速冷启动、热模块替换、极速构建 |
| Vue Router | 4.3+ | 路由管理 | Vue 官方路由库，支持历史模式和哈希模式 |
| Pinia | 2.1+ | 状态管理 | Vue 官方状态管理库，替代 Vuex |

### 第三方库

| 库 | 用途 | 说明 |
|------|------|------|
| Prism.js | 代码高亮 | 支持 Python 语法高亮显示 |
| Font Awesome | 图标库 | 丰富的图标集合 |
| Pyodide | Python 运行时 | 在浏览器中运行 Python 代码 |
| Monaco Editor | 代码编辑器 | 轻量级代码编辑器组件 |

### 开发工具

- **Git** - 版本控制
- **npm** - Node.js 包管理器
- **pip** - Python 包管理器
- **Gunicorn** - WSGI 服务器
- **Nginx** - 反向代理服务器

### 运行环境要求

| 依赖 | 版本要求 | 说明 |
|------|----------|------|
| Python | 3.8+ | 后端运行环境，推荐 Python 3.10+ |
| Node.js | 16+ | 前端构建环境，推荐 Node.js 18+ |
| MySQL | 5.7+ | 数据库，推荐 MySQL 8.0+ |
| 浏览器 | 现代浏览器 | Chrome、Firefox、Safari、Edge |

***

## 📁 项目结构

```
School_Web/                              # 项目根目录
├── app.py                               # Flask 主应用入口
├── requirements.txt                     # Python 依赖列表
├── LICENSE                              # GPLv2 许可证
├── .gitignore                           # Git 忽略文件
├── .secret_key                          # Flask 密钥（首次运行自动生成）
├── rate_config.json                     # 速率限制配置（自动生成）
├── ip_whitelist.json                    # IP 白名单配置（自动生成）
│
├── frontend/                            # Vue 3 前端项目
│   ├── src/
│   │   ├── components/                  # Vue 组件目录
│   │   │   ├── Chat.vue                 # 聊天组件
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
│   │   ├── index.html
│   │   └── assets/
│   │       ├── index-*.js
│   │       └── index-*.css
│   ├── index.html                       # HTML 模板
│   ├── package.json                     # Node.js 依赖配置
│   ├── package-lock.json                # 依赖版本锁定
│   └── vite.config.js                   # Vite 构建配置
│
├── templates/                           # Flask Jinja2 模板
│   ├── base.html                        # 基础模板（继承用）
│   ├── login.html                       # 登录页面
│   ├── register.html                    # 注册页面
│   ├── dashboard.html                   # 用户仪表盘
│   ├── admin_dashboard.html             # 管理后台仪表盘
│   ├── album_vue3.html                  # 相册入口页面
│   ├── system_monitor.html              # 系统监控页面
│   ├── network_tools.html               # 网络工具页面
│   ├── db_query.html                    # 数据库查询页面
│   ├── db_update.html                   # 数据库管理页面
│   ├── db_captcha.html                  # 数据库操作验证码页面
│   ├── global_captcha.html              # 全局验证码页面
│   ├── file_manager.html                # 文件管理器页面
│   ├── fm_password.html                 # 文件管理器密码验证页面
│   ├── calculator.html                  # 标准计算器页面
│   ├── calculator_sci.html              # 科学计算器页面
│   ├── calculator_net.html              # 网络计算器页面
│   ├── notes.html                       # 备忘录页面
│   ├── change_password.html             # 修改密码页面
│   ├── forgot_password.html             # 忘记密码页面
│   ├── reset_password.html              # 重置密码页面
│   ├── logout_confirm.html              # 登出确认页面
│   ├── logs.html                        # 日志查看页面
│   ├── profile.html                     # 个人资料页面
│   ├── author.html                      # 作者页面
│   ├── donate.html                      # 捐赠页面
│   └── chat_standalone.html             # 独立聊天页面
│
├── static/                              # 静态资源目录
│   ├── avatars/                         # 用户头像存储
│   │   └── 铭_150_667eea_fff.png
│   ├── img/                             # 图片资源
│   │   └── avatar_ming.png
│   ├── albums/                          # 相册图片存储
│   ├── projects/                        # 项目文件存储
│   ├── donate_wx.jpg                    # 微信捐赠二维码
│   └── donate_zfb.jpg                   # 支付宝捐赠二维码
│
├── __pycache__/                         # Python 编译缓存（自动生成）
│   └── app.cpython-*.pyc
│
└── .idea/                               # IDEA 编辑器配置
    ├── .gitignore
    ├── School_Web.iml
    ├── misc.xml
    ├── modules.xml
    └── vcs.xml
```

***

## 🚀 快速开始

### 环境要求

| 依赖 | 版本要求 | 说明 |
|------|----------|------|
| Python | 3.8+ | 后端运行环境，推荐 Python 3.10+ |
| Node.js | 16+ | 前端构建环境，推荐 Node.js 18+ |
| MySQL | 5.7+ | 数据库，推荐 MySQL 8.0+ |

### 后端部署步骤

1. **克隆项目**：

```bash
git clone https://gitee.com/zhang-mingfeng9773_admin_admin/tool-box-hub.git
cd School_Web
```

2. **创建虚拟环境（推荐）**：

```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
# 或
venv\Scripts\activate     # Windows
```

3. **安装 Python 依赖**：

```bash
pip install -r requirements.txt
```

4. **配置数据库连接**：

编辑 [app.py](file:///Users/zhangmingfeng/School_Web/app.py) 文件，修改数据库配置：

```python
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "你的MySQL数据库root的密码",
    "database": "sample"
}
```

5. **创建数据库和用户表**：

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

6. **启动服务**：

```bash
python app.py
```

服务启动后访问地址：

- 本地访问：<http://127.0.0.1:5800>
- 局域网访问：<http://192.168.x.x:5800>

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

开发服务器会在 <http://localhost:3000> 启动。

4. **构建生产版本**：

```bash
npm run build
```

构建产物将输出到 `frontend/dist/` 目录，Flask 会自动提供这些静态文件。

5. **预览生产构建**：

```bash
npm run preview
```

### Docker 部署

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

创建 `docker-compose.yml`：

```yaml
version: '3'
services:
  web:
    build: .
    ports:
      - "5800:5800"
    depends_on:
      - db
    environment:
      - FLASK_DEBUG=0
  db:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: your_password
      MYSQL_DATABASE: sample
    volumes:
      - mysql_data:/var/lib/mysql
    ports:
      - "3306:3306"

volumes:
  mysql_data:
```

启动服务：

```bash
docker-compose up -d
```

***

## 📖 详细功能介绍

### 🔐 用户认证系统

#### 注册流程

1. 用户访问注册页面
2. 填写用户名、密码、确认密码
3. 可选填写管理员密钥以获取管理员权限
4. 系统验证输入有效性
5. 密码使用 Werkzeug PBKDF2 进行哈希加密
6. 用户信息保存到数据库
7. 自动跳转到登录页面

#### 登录流程

1. 用户访问登录页面
2. 输入用户名、密码、图形验证码
3. 系统验证验证码有效性
4. 验证用户名和密码
5. 检查登录失败次数（超过5次锁定15分钟）
6. 验证成功后创建会话
7. 跳转到用户仪表盘

#### 密码安全

- 使用 PBKDF2 算法进行密码哈希
- 盐值自动生成并存储
- 支持旧版明文密码自动升级为哈希存储
- 密码长度至少8位，必须包含字母和数字

### 🖥️ 系统监控

系统监控页面展示以下信息：

- **系统信息**：
  - 操作系统版本
  - 主机名
  - 运行时间
  - 处理器信息
- **资源使用**：
  - CPU 使用率
  - 内存使用情况（总内存、已用内存、可用内存）
  - 磁盘使用情况（总空间、已用空间、可用空间、使用率）
  - 网络流量统计（发送/接收字节数、数据包数）
- **数据刷新**：每5秒自动刷新一次

### 🎓 毕业相册

#### 图片上传

1. 点击上传按钮打开上传弹窗
2. 选择图片文件（支持 jpg、png、gif、webp、bmp）
3. 填写图片名称和分类
4. 点击上传
5. 系统验证文件类型和大小（最大10MB）
6. 文件保存到服务器
7. 图片信息记录到数据库

#### 图片互动

- **点赞**：点击心形图标为图片点赞，再次点击取消点赞
- **评论**：在评论框输入评论并发送，支持回复评论
- **分享**：生成公开分享链接，访问者无需登录即可查看
- **标签**：为图片添加标签，方便分类和筛选

#### 同学录

- 添加同学信息：姓名、昵称、头像、生日、电话、邮箱、座右铭、兴趣、未来计划
- 支持编辑和删除同学信息（仅管理员）
- 按姓名排序展示

#### 寄语墙

- 支持发布实名或匿名寄语
- 寄语内容可包含文字和表情
- 每个寄语卡片有随机背景颜色
- 支持删除自己的寄语（管理员可删除任意寄语）

#### 时间轴

- 记录班级重要事件
- 按时间顺序展示
- 包含事件标题、描述、日期
- 管理员可添加和删除事件

### 🌐 网络工具

#### IP 查询

- 支持域名解析：输入域名，返回 IP 地址
- 本地 IP：显示服务器的本地 IP 地址
- 公网 IP：显示服务器的公网 IP 地址

#### 端口扫描

- 多线程端口扫描，提高扫描速度
- 支持自定义端口范围（最多200个端口）
- 显示开放端口和对应的服务
- 扫描结果可视化展示

#### 操作系统检测

- 通过端口服务特征推测目标操作系统
- 基于 HTTP Server、RDP 等服务指纹
- 返回可能的操作系统类型

#### Ping 测试

- 测试网络连通性和延迟
- 显示丢包率和平均延迟
- 支持自定义 ping 次数

### 📁 文件管理器

#### 目录浏览

- 安全的文件系统导航
- 限制在用户主目录，防止路径穿越
- 支持文件夹展开和收起

#### 文件操作

- 上传：支持拖拽上传，最大50MB
- 下载：点击文件下载
- 删除：删除文件（需二次确认）
- 重命名：修改文件名

#### 文件预览

- 支持图片预览（jpg、png、gif、webp、bmp）
- 支持文本预览（txt、md、py、js 等）
- 支持 PDF 预览

### 🗄️ 数据库工具

#### 数据查询

- 选择数据库表
- 查看表结构和数据
- 支持分页查询
- 支持排序和过滤

#### 数据管理

- 增删改查操作
- 二次验证码确认
- 密码脱敏显示
- 导出为 CSV 格式

#### 表结构查看

- 查看字段类型、长度、是否为空
- 查看主键和外键
- 查看索引信息

***

## 🔌 API 接口文档

### 认证接口

| 接口路径 | HTTP 方法 | 功能描述 | 权限要求 |
|----------|-----------|----------|----------|
| `/api/register` | POST | 用户注册 | 公开 |
| `/api/login` | POST | 用户登录 | 公开 |
| `/api/logout` | GET | 用户登出 | 登录用户 |
| `/api/change_password` | POST | 修改密码 | 登录用户 |
| `/api/reset_password` | POST | 重置密码 | 公开 |
| `/api/captcha` | GET | 获取图形验证码 | 公开 |

### 相册接口

| 接口路径 | HTTP 方法 | 功能描述 | 权限要求 |
|----------|-----------|----------|----------|
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

### 系统管理接口

| 接口路径 | HTTP 方法 | 功能描述 | 权限要求 |
|----------|-----------|----------|----------|
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
| `/api/system_info` | GET | 获取系统资源信息 | 管理员 |

### 数据库接口

| 接口路径 | HTTP 方法 | 功能描述 | 权限要求 |
|----------|-----------|----------|----------|
| `/api/db/tables` | GET | 获取数据库表列表 | 管理员 |
| `/api/db/query` | POST | 执行数据库查询 | 管理员 |
| `/api/db/update` | POST | 执行数据库更新 | 管理员 |

### 文件管理接口

| 接口路径 | HTTP 方法 | 功能描述 | 权限要求 |
|----------|-----------|----------|----------|
| `/api/files/list` | GET | 获取文件列表 | 非访客 |
| `/api/files/upload` | POST | 上传文件 | 非访客 |
| `/api/files/download/<path:filepath>` | GET | 下载文件 | 非访客 |
| `/api/files/delete` | POST | 删除文件 | 非访客 |

### 网络工具接口

| 接口路径 | HTTP 方法 | 功能描述 | 权限要求 |
|----------|-----------|----------|----------|
| `/api/tools/ip` | GET | 获取 IP 信息 | 登录用户 |
| `/api/tools/scan` | POST | 端口扫描 | 登录用户 |
| `/api/tools/ping` | POST | Ping 测试 | 登录用户 |

***

## 🔒 安全特性

### 认证安全

- 使用图形验证码防止自动化攻击
- 登录失败5次后账号锁定15分钟
- 密码使用 Werkzeug PBKDF2 哈希加密
- 支持旧版明文密码自动升级为哈希存储
- 会话超时自动登出（2分钟无操作）
- 密码强度校验（至少8位，包含字母和数字）

### 请求安全

- CSRF 令牌验证
- IP 速率限制防止暴力攻击
- 输入清洗过滤 HTML/JS 标签
- 参数化查询防止 SQL 注入
- 安全响应头配置（CSP、HSTS、X-Frame-Options 等）
- 路径穿越防护（文件路径安全检查）

### 文件安全

- 文件路径安全检查，防止路径穿越攻击
- 文件大小限制（相册10MB，文件管理器50MB）
- 文件类型验证（通过文件扩展名和魔数检测）
- 文件上传需管理员权限
- 上传文件自动重命名，防止覆盖

### 会话安全

- 会话超时自动登出（2分钟无操作）
- Session Cookie 设置 HttpOnly 和 SameSite 属性
- 定期更换 CSRF 令牌
- 持久化的 Session ID（使用文件存储）
- 登录时重新生成会话 ID，防止会话固定攻击

### 安全响应头配置

```
Content-Security-Policy: default-src 'self' 'unsafe-inline' 'unsafe-eval'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://connect.qq.com https://cdn.bootcdn.net; style-src 'self' 'unsafe-inline' https://cdn.bootcdn.net https://cdn.jsdelivr.net; font-src 'self' https://cdn.bootcdn.net; img-src 'self' data: blob: *; connect-src 'self' *; frame-ancestors 'self'; form-action 'self'
X-Content-Type-Options: nosniff
X-Frame-Options: SAMEORIGIN
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
Strict-Transport-Security: max-age=31536000; includeSubDomains
```

### CSRF 防护

- 所有表单提交均需验证 CSRF 令牌
- CSRF 令牌定期更换
- 令牌与用户会话绑定
- AJAX 请求需携带 CSRF 令牌

### XSS 防护

- 输入内容自动过滤 HTML/JS 标签
- 输出到页面时进行 HTML 转义
- 内容安全策略（CSP）限制脚本来源
- 使用参数化查询防止注入

### SQL 注入防护

- 所有数据库查询使用参数化查询
- 禁止直接拼接 SQL 语句
- 输入内容类型校验
- 敏感操作二次验证

### 路径穿越防护

- 文件路径规范化处理
- 限制访问目录范围
- 检查路径是否在允许的范围内
- 禁止访问系统敏感文件

***

## ⚙️ 配置说明

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `FLASK_DEBUG` | `0` | 是否开启调试模式（1=开启，0=关闭） |
| `ADMIN_SECRET` | `asdfghjkl;'` | 管理员注册密钥 |
| `SECRET_KEY` | 随机生成 | Flask 会话密钥 |

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

# 相册数据库配置（默认与主配置相同）
ALBUM_DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "your_password",
    "database": "sample"
}
```

### 文件上传限制

```python
# 相册图片大小限制（字节）
MAX_ALBUM_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB

# 文件管理器文件大小限制（字节）
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
```

### 会话配置

```python
# 要先导入必要库
import datetime

# 会话超时时间（秒）
SESSION_IDLE_TIMEOUT = 120  # 2分钟

# 会话持久化时间
PERMANENT_SESSION_LIFETIME = datetime.timedelta(hours=2)
```

### CSP 配置

内容安全策略（CSP）限制资源加载来源：

- **脚本来源**：`'self'`、`'unsafe-inline'`、`'unsafe-eval'`、`https://connect.qq.com`、`https://cdn.bootcdn.net`
- **样式来源**：`'self'`、`'unsafe-inline'`、`https://cdn.bootcdn.net`、`https://cdn.jsdelivr.net`
- **字体来源**：`'self'`、`https://cdn.bootcdn.net`
- **图片来源**：`'self'`、`data:`、`blob:`、`*`
- **连接来源**：`'self'`、`*`
- **框架来源**：`'self'`
- **表单提交**：`'self'`

***

## 📖 使用指南

### 注册账号

1. 访问 <http://localhost:5800/register>
2. 填写用户名和密码（密码需至少8位，包含字母和数字）
3. 如需注册管理员账号，填写管理员密钥（默认：`asdfghjkl;'`）
4. 点击注册完成账号创建

### 登录系统

1. 访问 <http://localhost:5800/>
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

### 网络工具使用指南

1. 访问 `/network_tools`（需管理员权限）
2. 选择需要使用的网络工具
3. 填写相关参数
4. 查看结果

### 文件管理器使用指南

1. 访问 `/file_manager`（需非访客权限）
2. 输入密码完成安全验证
3. 浏览文件目录
4. 进行文件上传、下载、删除等操作

***

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
- Git 提交信息清晰明确
- 添加适当的注释和文档字符串

### 数据库表结构

#### 用户表（users）

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| id | INT | PRIMARY KEY, AUTO_INCREMENT | 用户 ID |
| User_Name | VARCHAR(50) | NOT NULL, UNIQUE | 用户名 |
| User_Password | VARCHAR(255) | NOT NULL | 密码（PBKDF2 哈希） |
| Access_Permission | VARCHAR(20) | DEFAULT 'guest' | 权限等级 |
| created_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时间 |

#### 相册图片表（album_images）

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| id | INT | PRIMARY KEY, AUTO_INCREMENT | 图片 ID |
| name | VARCHAR(255) | NOT NULL | 图片名称 |
| filename | VARCHAR(255) | NOT NULL | 文件名 |
| category | VARCHAR(50) | DEFAULT NULL | 分类 |
| uploader | VARCHAR(50) | NOT NULL | 上传者 |
| upload_time | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 上传时间 |
| likes | INT | DEFAULT 0 | 点赞数 |

#### 相册评论表（album_comments）

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| id | INT | PRIMARY KEY, AUTO_INCREMENT | 评论 ID |
| image_id | INT | NOT NULL | 图片 ID |
| user | VARCHAR(50) | NOT NULL | 评论者 |
| content | TEXT | NOT NULL | 评论内容 |
| comment_time | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 评论时间 |

#### 相册点赞表（album_likes）

| 字段名 | 类型 | 约束 | 说明 |
|--------|------|------|------|
| id | INT | PRIMARY KEY, AUTO_INCREMENT | 点赞 ID |
| image_id | INT | NOT NULL | 图片 ID |
| user | VARCHAR(50) | NOT NULL | 点赞者 |

### 扩展开发

#### 添加新功能模块

1. 在 [app.py](file:///Users/zhangmingfeng/School_Web/app.py) 中添加新的路由和接口
2. 创建对应的 HTML 模板
3. 添加静态资源（CSS、JS、图片等）
4. 更新权限验证逻辑

#### 添加新的 API 接口

1. 在对应的路由函数中添加新的处理逻辑
2. 添加权限验证
3. 实现业务逻辑
4. 返回 JSON 响应

#### 添加新的 Vue 组件

1. 在 `frontend/src/components/` 目录下创建新的 `.vue` 文件
2. 编写组件模板、脚本和样式
3. 在 [App.vue](file:///Users/zhangmingfeng/School_Web/frontend/src/App.vue) 中注册组件
4. 添加路由配置

### 测试建议

1. **功能测试**：测试各个功能模块是否正常工作
2. **安全测试**：测试 SQL 注入、XSS、CSRF 等安全漏洞
3. **性能测试**：测试速率限制、系统监控等功能
4. **兼容性测试**：测试不同浏览器和设备的兼容性
5. **边界测试**：测试边界情况和异常处理
6. **负载测试**：测试高并发情况下的系统表现

***

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

3. **启用 HTTPS**：

```bash
# 使用 Let's Encrypt 获取 SSL 证书
certbot --nginx -d your-domain.com
```

### Nginx 反向代理

#### 基础配置

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

#### 静态文件缓存

```nginx
location /static {
    alias /path/to/School_Web/static;
    expires 30d;
    add_header Cache-Control "public, immutable";
}
```

### HTTPS 配置

1. **安装 Certbot**：

```bash
sudo apt-get install certbot python3-certbot-nginx
```

2. **获取证书**：

```bash
sudo certbot --nginx -d your-domain.com
```

3. **自动续期**：

```bash
sudo certbot renew --dry-run
```

### Systemd 服务配置

创建 `/etc/systemd/system/school-web.service`：

```ini
[Unit]
Description=School Web Application
After=network.target

[Service]
Type=notify
User=your_user
WorkingDirectory=/path/to/School_Web
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/gunicorn -w 4 app:app -b 0.0.0.0:5800
Restart=always

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable school-web
sudo systemctl start school-web
```

### 负载均衡

#### Nginx 负载均衡配置

```nginx
upstream school_web {
    server 127.0.0.1:5800;
    server 127.0.0.1:5801;
    server 127.0.0.1:5802;
}

server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://school_web;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

***

## ❓ 常见问题

### 数据库连接失败

**问题**：启动时提示数据库连接失败

**解决方案**：

1. 检查 MySQL 服务是否启动
2. 确认 [app.py](file:///Users/zhangmingfeng/School_Web/app.py) 中的数据库配置正确
3. 检查用户名和密码是否正确
4. 确认数据库已创建

### 验证码不显示

**问题**：登录页面验证码图片不显示

**解决方案**：

1. 检查 Pillow 是否正确安装
2. 确认静态文件路径配置正确
3. 查看浏览器控制台是否有错误

### 文件上传失败

**问题**：上传图片时提示上传失败

**解决方案**：

1. 检查文件大小是否超过限制（10MB）
2. 确认文件格式是否支持（jpg、png、gif、webp、bmp）
3. 检查 `static/albums` 目录是否有写权限

### 速率限制误封

**问题**：正常访问也被限制

**解决方案**：

1. 将 IP 添加到白名单
2. 调整速率限制参数
3. 检查是否有多个请求同时发送

### 前端构建错误

**问题**：执行 `npm run build` 时出错

**解决方案**：

1. 确保 Node.js 版本满足要求（16+）
2. 删除 `node_modules` 和 `package-lock.json`，重新安装
3. 检查 [vite.config.js](file:///Users/zhangmingfeng/School_Web/frontend/vite.config.js) 配置是否正确

### 会话超时频繁

**问题**：用户频繁被登出

**解决方案**：

1. 调整 `SESSION_IDLE_TIMEOUT` 参数
2. 检查浏览器 Cookie 设置
3. 确认 HTTPS 配置正确

### Pyodide 加载失败

**问题**：Python IDE 页面无法加载 Pyodide

**解决方案**：

1. 检查网络连接是否正常
2. 确认 CDN 地址可访问
3. 检查浏览器是否支持 WebAssembly

### 端口扫描无结果

**问题**：端口扫描没有返回任何结果

**解决方案**：

1. 确认目标 IP 或域名正确
2. 检查防火墙设置
3. 确认端口范围设置合理

***

## 📝 更新日志

### v1.0.0（2025年5月5日发布）

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
- 管理后台
- 同学录功能
- 寄语墙功能
- 时间轴功能
- 标签系统
- 歌单功能
- 弹幕功能
- 聊天功能
- 捐赠页面
- 个人资料页面

***

## 🤝 贡献指南

欢迎贡献！请遵循以下步骤：

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 提交 Pull Request

### 代码审查

所有提交的代码都会经过审查，确保：

- 符合代码规范
- 有适当的测试
- 不引入安全漏洞
- 与现有功能兼容

### 贡献者权益

- 贡献者将被添加到贡献者列表中
- 重大贡献者将获得项目维护者权限
- 所有贡献者都将受到社区尊重

***

## 📞 联系方式

如有问题或建议，请通过以下方式联系：

- 🌐 项目地址：<https://gitee.com/zhang-mingfeng9773_admin_admin/tool-box-hub>
- 🐛 提交 Issue：<https://gitee.com/zhang-mingfeng9773_admin_admin/tool-box-hub/issues>
- 👤 作者页面：访问应用内的作者页面
- 💰 捐赠：访问应用内的捐赠页面
- 📱 电话: +86 151 2346 9773(微信同号, 周一至周五 20:00-21:00, 周六 14:00-21:00/22:00, 周日全天除凌晨)
- 💬 QQ: 503175021
- 💬 微信(WeChat): wxid_6t5bmudk2gnr12

🚀 如果这个项目对你有帮助，别忘了点个 Star ⭐！你的支持是我持续优化升级的动力！ ❤️

***

## 🌟 致谢

感谢所有为本项目做出贡献的人！

- Flask 社区
- Vue.js 社区
- Open Source 开发者
- 所有贡献者

特别感谢：

- 提供灵感和建议的用户
- 报告 Bug 和改进建议的贡献者
- 帮助测试和文档的贡献者

***

## 📚 参考资料

- [Flask 官方文档](https://flask.palletsprojects.com/)
- [Vue.js 官方文档](https://vuejs.org/)
- [Vite 官方文档](https://vitejs.dev/)
- [PyMySQL 文档](https://pymysql.readthedocs.io/)
- [psutil 文档](https://psutil.readthedocs.io/)
- [Pillow 文档](https://pillow.readthedocs.io/)
- [Werkzeug 文档](https://werkzeug.palletsprojects.com/)
- [GPLv2 许可证](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html)

***

*最后更新：2026-05-17*
