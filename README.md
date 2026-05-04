# School_Web - 多功能工具箱

一个功能丰富的 Web 应用集成平台，基于 Flask + Vue 3 构建。

## 功能特性

### 用户管理
- 用户注册与登录（支持图形验证码）
- 权限分级：管理员（administrator）和访客（guest）
- 登录防爆破机制（5次错误锁定15分钟）
- 密码修改（支持验证码验证）

### 安全防护
- IP 速率限制（可配置请求数和封禁时长）
- IP 白名单管理
- 全站验证码门禁
- CSRF 令牌保护
- 安全响应头（CSP、HSTS、X-Frame-Options 等）
- 输入清洗（防止 XSS）

### 系统管理（管理员）
- 系统监控面板（CPU、内存、磁盘、网络）
- 管理后台仪表盘
- 日志查看与清空
- IP 统计与管理（封禁/解封/白名单）
- 速率限制配置动态调整

### 数据库工具
- 可视化数据库查询
- 数据库表数据增删改查
- 数据库操作需二次验证码确认

### 网络工具
- IP 地址查询
- 端口扫描
- 操作系统检测

### 文件管理器
- 目录浏览
- 文件上传/下载/删除
- 密码二次验证保护

### 毕业相册（Vue 3 前端）
- 图片上传与管理
- 图片点赞、评论、分享链接
- 大事记时间轴
- 同学录
- 毕业寄语墙
- 照片标签管理
- 毕业歌单
- 弹幕功能
- 数据统计图表

### 其他工具
- 计算器（标准/科学/网络计算）
- 备忘录

## 技术栈

### 后端
- **Flask 3** - Web 框架
- **PyMySQL** - MySQL 数据库连接
- **psutil** - 系统信息获取
- **Pillow** - 图形验证码生成
- **Werkzeug** - 密码哈希

### 前端
- **Vue 3** - 渐进式 JavaScript 框架
- **Vite 5** - 构建工具
- **Vue Router** - 路由管理
- **Pinia** - 状态管理

## 项目结构

```
School_Web/
├── app.py              # Flask 主应用
├── requirements.txt    # Python 依赖
├── frontend/           # Vue 3 前端
│   ├── src/
│   │   ├── components/ # Vue 组件
│   │   ├── App.vue     # 根组件
│   │   ├── main.js     # 入口文件
│   │   └── api.js      # API 封装
│   ├── dist/           # 构建输出
│   ├── package.json
│   └── vite.config.js
├── templates/          # Flask 模板
├── static/            # 静态文件
│   ├── albums/        # 相册图片
│   └── projects/      # 项目文件
└── .secret_key        # Flask 密钥（自动生成）
```

## 安装部署

### 环境要求
- Python 3.8+
- Node.js 16+
- MySQL 5.7+

### 后端部署

1. 安装 Python 依赖：
```bash
pip install -r requirements.txt
```

2. 配置数据库连接（编辑 `app.py` 中的 `DB_CONFIG`）：
```python
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "your_password",
    "database": "your_database"
}
```

3. 启动服务：
```bash
python app.py
```

服务启动后访问：
- 本地：http://127.0.0.1:5800
- 局域网：http://192.168.x.x:5800

### 前端部署（毕业相册）

1. 进入前端目录：
```bash
cd frontend
```

2. 安装依赖：
```bash
npm install
```

3. 开发模式：
```bash
npm run dev
```

4. 构建生产版本：
```bash
npm run build
```

## 使用指南

### 注册账号
访问注册页面创建账号。提供管理员密钥（默认：`asdfghjkl;'`）可注册为管理员账号，否则为访客账号。

### 权限说明
- **管理员**：可访问所有功能，包括系统监控、数据库管理、文件管理、日志查看等
- **访客**：可使用相册、计算器、备忘录等基础功能

### 相册功能
1. 登录后访问 `/album` 进入相册
2. 管理员可上传图片、管理同学录、发布寄语、添加歌单
3. 所有用户可点赞、评论、浏览

## 主要路由

| 路由 | 功能 | 权限 |
|------|------|------|
| `/` | 登录页面 | 公开 |
| `/register` | 注册页面 | 公开 |
| `/dashboard` | 用户仪表盘 | 登录 |
| `/album` | 毕业相册 | 登录 |
| `/db_query` | 数据库查询 | 非访客 |
| `/db_update` | 数据库管理 | 管理员 |
| `/system_monitor` | 系统监控 | 管理员 |
| `/network_tools` | 网络工具 | 管理员 |
| `/file_manager` | 文件管理 | 非访客 |
| `/admin` | 管理后台 | 管理员 |
| `/logs` | 日志查看 | 管理员 |
| `/calculator` | 标准计算器 | 登录 |
| `/calculator/sci` | 科学计算器 | 登录 |
| `/calculator/net` | 网络计算器 | 登录 |
| `/notes` | 备忘录 | 登录 |
| `/change_password` | 修改密码 | 登录 |

## 配置说明

### 环境变量
- `FLASK_DEBUG=1` - 开启调试模式
- `ADMIN_SECRET` - 管理员注册密钥

### 速率限制配置
在管理后台可动态调整：
- 请求数限制（默认40）
- 时间窗口（默认15秒）
- 封禁时长（默认240秒）
- 试探检测阈值（默认200次）
- 追加封禁时长（默认300秒）

## 注意事项

1. 首次运行会自动生成 `.secret_key` 文件用于会话加密
2. IP 白名单和速率配置会持久化到 JSON 文件
3. 数据库需提前创建对应表结构
4. 生产环境请修改 `SECRET_KEY` 和数据库密码
5. 文件上传大小限制为 10MB，相册图片建议压缩后上传

## 许可证

MIT License
