# 电子宠物 2.0 创新升级计划

> **目标：** 将基础电子宠物升级为社交互动 + 成长进化 + 宠物对话 + 趣味交互四合一完整系统

**架构：** 后端新增 4 张表（成就/库存/串门/赠礼/日记），扩展 pets 表 8 个字段，新增 12 个 API 端点。前端完全重写 pet.html，分 Tab 展示。

**技术栈：** Flask + pymysql + Jinja2 + Canvas + CSS 动画（无外部库）

---

## Phase 1: 数据库扩展

### Task 1: 扩展 pets 表字段
**文件：** `app.py` → `_init_pet_tables()` 函数

新增字段：
- `personality` VARCHAR(20) — 性格（贪吃/活泼/慵懒/均衡）
- `evolution_stage` INT DEFAULT 0 — 进化阶段（0=幼体,1=成体,2=完全体）
- `coins` INT DEFAULT 0 — 宠物币
- `mood` VARCHAR(50) DEFAULT '开心' — 心情文字
- `accessories` TEXT DEFAULT '[]' — 装扮列表 JSON
- `visit_count` INT DEFAULT 0 — 被访问次数
- `action_count` INT DEFAULT 0 — 总行动次数
- `feed_count` INT DEFAULT 0 — 喂食次数
- `play_count` INT DEFAULT 0 — 玩耍次数
- `sleep_count` INT DEFAULT 0 — 睡觉次数

### Task 2: 创建新表
- `pet_achievements` — 成就
- `pet_inventory` — 物品库存
- `pet_visits` — 串门记录
- `pet_gifts` — 赠礼记录
- `pet_diary` — 宠物日记

---

## Phase 2: 宠物进化系统

### Task 3: 进化阶段配置 + 检测逻辑
- 定义进化表：每种宠物 3 阶段 emoji/名字
- Lv.10 → 成体，Lv.20 → 完全体
- 进化时记录日记 + 弹出特效

### Task 4: 性格系统
- 行动 20 次后根据喂食/玩耍/睡觉比例判定性格
- 性格影响对话内容池

---

## Phase 3: 成就系统

### Task 5: 成就定义 + 检查逻辑
- 预定义 15+ 成就（首次喂食、喂食100次、升到10级、串门10次等）
- 每次操作后检查并解锁

---

## Phase 4: 宠物对话

### Task 6: 对话系统
- 根据饥饿/快乐/精力 + 性格返回 context-aware 对话
- 点击宠物弹出对话气泡

---

## Phase 5: 趣味交互

### Task 7: 接食物小游戏（Canvas）
- 食物从顶部掉落，左右移动篮子接住
- 得分换硬币

### Task 8: 装扮商店
- 用硬币购买帽子/眼镜/围巾等
- 宠物展示界面显示装扮

---

## Phase 6: 社交互动

### Task 9: 串门 + 排行榜
- 查看所有用户的宠物列表
- 访问他人宠物并留言
- 宠物排行榜（等级/硬币）

### Task 10: 赠礼系统
- 赠送库存物品或硬币
- 接收方收到通知

---

## Phase 7: 宠物日记

### Task 11: 自动日记
- 里程碑事件自动记录（孵化、进化、成就解锁、被访问、收礼）

---

## Phase 8: 前端重写

### Task 12: 全新 pet.html
- Tab 布局（我的宠物 / 小游戏 / 装扮 / 串门 / 日记）
- 对话气泡组件
- 进化动画
- 成就展示

### Task 13: 侧边栏宠物小窗
- 全局底部或侧边栏显示宠物状态摘要
