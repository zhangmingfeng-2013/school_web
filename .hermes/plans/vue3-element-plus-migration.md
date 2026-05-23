# Vue3 + Element Plus 全面迁移计划

## 架构变更

从 **Flask Jinja2 服务端渲染** 改为 **Vue3 SPA + Flask REST API** 前后端分离架构。

```
之前: Browser → Flask render_template() → HTML
之后: Browser → Vue3 SPA → Axios → Flask REST API → JSON
```

## 当前项目规模
- 77 个 Jinja2 模板
- 291 个路由 (页面路由 + API路由)
- 11198 行 app.py

## 迁移策略

### Phase 1: 基础设施 (核心框架)
1. 创建 Vue3 项目结构 (使用 CDN 引入方式，兼容现有 Flask 服务)
2. 配置 Vue Router (客户端路由)
3. 集成 Element Plus CDN
4. 创建 App.vue 主布局 (替代 base.html)
5. 实现主题切换 (亮/暗)
6. 实现语言切换 (i18n)
7. 实现登录/注册页面
8. 实现通知系统

### Phase 2: 核心页面
9. 仪表盘 (dashboard)
10. 聊天 (chat + AI chat)
11. 个人资料 (profile)
12. 管理后台 (admin)

### Phase 3: 功能页面 (社区类)
13. 校友纪念相册 (album)
14. 论坛 (forum)
15. 信息门户 (portal)
16. 校友名录 (alumni)
17. 校友故事 (alumni_stories)
18. 表白墙 (confession_wall)

### Phase 4: 工具页面
19. 电子宠物 (pet)
20. 番茄钟 (pomodoro)
21. 签到 (checkin)
22. 习惯追踪 (habits)
23. 记账 (expenses)
24. 书签 (bookmarks)
25. 学习工具 (study)
26. 日历 (calendar)
27. 便签 (notes)

### Phase 5: 开发者工具
28. 网络工具 (network_tools)
29. 数据库查询 (db_query)
30. 系统监控 (system_monitor)
31. API测试 (api_tester)
32. 文件管理 (file_manager)
33. 备份管理 (backup)
34. 日志查看 (logs)
35. 实用工具集 (utils)

### Phase 6: 小工具
36-55. 其他小工具页面

### Phase 7: 其他
56. 关于作者 (author)
57. 捐赠 (donate)
58. 插件市场 (marketplace)
59. 安全报告 (src)
60. 天气 (weather)

## 技术选型
- Vue 3 (CDN: unpkg/vue@3)
- Element Plus (CDN: unpkg/element-plus)
- Vue Router 4 (CDN)
- Axios (CDN)
- Pinia (状态管理, CDN)

## 关键决策
- 使用 CDN 引入而非构建工具 (兼容现有 Flask 静态文件服务)
- SPA 模式下所有路由指向同一个 HTML 入口文件
- API 前缀统一为 /api/
- 保持现有 Flask session 认证机制
- CSRF token 通过 meta 标签传递
