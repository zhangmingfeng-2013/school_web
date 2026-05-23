# 8 Feature Implementation Plan — 多合一工具箱 Web 版

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Add 8 new features to the Flask web app: 校友故事, 匿名树洞, AI 写作助手, 智能翻译, 番茄钟增强, PDF 工具集, 签到打卡日历, 电子宠物.

**Architecture:** Single-file Flask app (app.py) with MySQL (two DBs: DB_CONFIG + ALBUM_DB_CONFIG). Each feature = new DB tables + Jinja2 template + JS logic + app.py routes. All follow existing patterns: CSP-safe event delegation, no inline styles, `@login_required` for API, `session["username"]` for identity.

**Tech Stack:** Flask 3.x + PyMySQL + Bootstrap 5 + Chart.js + OpenAI-compatible API (reused for AI features) + PyPDF2 (new pip dep for PDF)

---

## Dependency Graph

```
Phase 1 (no new tables, no new deps):
  ├── 3. AI 写作助手
  └── 4. 智能翻译

Phase 2 (new tables, simple CRUD):
  ├── 7. 签到打卡日历
  └── 2. 匿名树洞

Phase 3 (complex, approval workflow):
  └── 1. 校友故事/回忆录

Phase 4 (enhance existing):
  └── 5. 番茄钟增强

Phase 5 (external dep + UI heavy):
  ├── 6. PDF 工具集
  └── 8. 电子宠物
```

---

## Phase 1: AI 写作助手 + 智能翻译

### Feature 3: AI 写作助手 (`/ai_writing`)

**Concept:** User selects a writing mode (发言稿/活动通知/朋友圈/工作总结/邮件/自由), enters topic/requirements, AI generates the text. Reuses existing `ai_config` + `ai_conversations` table.

**No new DB tables needed.**

**Database changes:** None — reuses `ai_config` table (from get_album_db()).

**Template:** `templates/ai_writing.html`
- Mode selector (dropdown/cards): 发言稿 | 活动通知 | 朋友圈文案 | 工作总结 | 邮件 | 自由写作
- Topic input + requirement input (tone, length, key points)
- Output area with copy button, regenerate button
- Writing history sidebar (recent 10 generations)

**Route entries in app.py:**
```python
@app.route("/ai_writing")
@login_required
def ai_writing_page():
    return render_template("ai_writing.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

@app.route("/api/ai/writing", methods=["POST"])
@login_required
def api_ai_writing():
    # Reuses existing AI infrastructure: ai_config, _ai_decrypt, requests.post
    # Mode-specific system prompts:
    #   发言稿: "你是一位专业的演讲稿撰写人..."
    #   活动通知: "你是一位活动策划专家..."
    #   朋友圈: "你擅长写有趣的社交媒体文案..."
    #   工作总结: "你是一位职场写作专家..."
    #   邮件: "你是一位商务邮件撰写专家..."
    #   自由: generic assistant
    # Returns {"result": "generated text"}
```

**System prompts per mode:**
| Mode | System Prompt |
|---|---|
| 发言稿 | 你是一位专业的演讲稿撰写人。请根据用户提供的主题和要求，撰写一份正式、有条理、富有感染力的发言稿。注意使用恰当的称呼、过渡语和结束语。 |
| 活动通知 | 你是一位活动策划专家。请撰写一份清晰、吸引人的活动通知，包含活动主题、时间地点、议程亮点、参与方式等关键信息。 |
| 朋友圈文案 | 你擅长写生动有趣的社交媒体文案。请用轻松自然的语气撰写，适当使用emoji，让文案有互动感和分享欲。长度控制在朋友圈舒适阅读范围。 |
| 工作总结 | 你是一位职场写作专家。请根据用户提供的信息，撰写一份结构清晰的工作总结，突出成果、数据支撑、经验教训和下一步计划。 |
| 邮件 | 你是一位商务邮件撰写专家。请使用得体的商务语气，撰写格式规范的邮件，包含恰当的主题行、称呼和署名。 |
| 自由写作 | 你是一个创意写作助手。请根据用户的描述自由创作，不拘泥于特定格式。 |

**Frontend JS:**
- `data-csp-click="aiWritingGenerate"` on the generate button
- Calls `/api/ai/writing` POST with `{mode, topic, requirements}`
- Shows loading spinner, then renders markdown output
- Copy button uses `navigator.clipboard.writeText()`

---

### Feature 4: 智能翻译 (`/translator`)

**Concept:** Simple text translator using AI. Supports 中→英, 英→中, and other language pairs.

**No new DB tables needed.**

**Template:** `templates/translator.html`
- Source text textarea (left)
- Target text area (right, read-only)
- Language selector: 中→英 / 英→中 / 中→日 / 日→中 / 中→韩 / 自动检测→中
- Translate button + copy button + swap button

**Route entries in app.py:**
```python
@app.route("/translator")
@login_required
def translator_page():
    return render_template("translator.html", username=session.get("username", ""), permission=session.get("permission", "guest"))

@app.route("/api/translator", methods=["POST"])
@login_required
def api_translator():
    # Reuses AI infrastructure
    # System prompt: "你是一个专业翻译。请将以下文本翻译成{target_language}。只返回翻译结果，不要添加任何解释或注释。"
    # Returns {"translated": "translated text"}
```

**Language pairs mapping:**
```python
LANG_MAP = {
    "zh-en": "英文",
    "en-zh": "简体中文",
    "zh-ja": "日文",
    "ja-zh": "简体中文",
    "zh-ko": "韩文",
    "auto-zh": "简体中文",
}
```

---

## Phase 2: 签到打卡日历 + 匿名树洞

### Feature 7: 签到打卡日历 (`/checkin`)

**DB Table:** `checkins` (in main DB_CONFIG)
```sql
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
```

**Template:** `templates/checkin.html`
- GitHub-style contribution heatmap (current year, using CSS grid)
- Today's check-in button (disabled if already checked in)
- Mood selector (😊😄😢😡🤔😴)
- Optional note input
- Check-in streak counter ("连续签到 X 天!")
- Monthly calendar view below heatmap

**Route entries in app.py:**
```python
@app.route("/checkin")
@login_required
def checkin_page():
    _init_checkin_table()  # new init function
    return render_template("checkin.html", ...)

@app.route("/api/checkin/status")
@login_required
def api_checkin_status():
    # GET: returns today's checkin status + year checkin dates for heatmap
    # Returns {"checked_today": bool, "streak": int, "dates": ["2026-01-01", ...], "moods": {...}}

@app.route("/api/checkin", methods=["POST"])
@login_required
def api_checkin():
    # POST {mood, note} → INSERT INTO checkins
    # Returns {"streak": int, "date": "2026-05-23"}
```

**Heatmap rendering:** Pure CSS grid, no Chart.js needed. 7 rows (days of week) × 53 columns (weeks). Each cell colored by check-in count/darkness.

**Streak calculation:** Walk backwards from today, count consecutive days with records.

---

### Feature 2: 匿名树洞 (`/confession`)

**DB Tables:** (in main DB_CONFIG)
```sql
CREATE TABLE IF NOT EXISTS anonymous_posts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nickname VARCHAR(20) NOT NULL COMMENT '随机昵称',
    content TEXT NOT NULL,
    emoji VARCHAR(5) DEFAULT '💬',
    like_count INT DEFAULT 0,
    reply_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_ap_created (created_at)
)

CREATE TABLE IF NOT EXISTS anonymous_replies (
    id INT AUTO_INCREMENT PRIMARY KEY,
    post_id INT NOT NULL,
    nickname VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_ar_post (post_id)
)

CREATE TABLE IF NOT EXISTS anonymous_likes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    post_id INT NOT NULL,
    username VARCHAR(50) NOT NULL COMMENT '实际用户，防止刷赞',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_alike (post_id, username)
)
```

**Template:** `templates/confession_wall.html`
- Post form: textarea + emoji picker (10 emoji: 💬💔😂😢😡🎉🌟🔥💡👻)
- Card list with infinite scroll (load more)
- Each card: random nickname + emoji + content + time + like count + reply count
- Click card → expand replies
- Reply form at bottom of each card
- "换一个昵称" button (changes the random nickname for current session)

**Route entries in app.py:**
```python
@app.route("/confession")
@login_required
def confession_page():
    _init_confession_tables()
    return render_template("confession_wall.html", ...)

@app.route("/api/confession/posts", methods=["GET", "POST"])
@login_required
def api_confession_posts():
    # GET: paginated list (page param, 15 per page), returns posts + replies
    # POST: {content, emoji, nickname} → INSERT

@app.route("/api/confession/posts/<int:pid>/replies", methods=["GET", "POST"])
@login_required
def api_confession_replies(pid):
    # GET: replies for post
    # POST: {content, nickname} → INSERT

@app.route("/api/confession/posts/<int:pid>/like", methods=["POST"])
@login_required
def api_confession_like(pid):
    # Uses actual username to prevent multi-like
    # Toggle like → update like_count in anonymous_posts
```

**Nickname generation:** Random from adjective + noun pool:
```python
ADJECTIVES = ["快乐的","安静的","勇敢的","温柔的","调皮的","可爱的","酷酷的","暖暖的"]
NOUNS = ["小树","星星","月亮","微风","小雨","阳光","猫咪","兔子"]
# → "勇敢的小树", "温柔的猫咪", etc.
# Stored in session["confession_nickname"], regeneratable
```

---

## Phase 3: 校友故事/回忆录

### Feature 1: 校友故事/回忆录 (`/alumni_stories`)

**DB Tables:** (in main DB_CONFIG, reuses `forum_likes` pattern)
```sql
CREATE TABLE IF NOT EXISTS alumni_stories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL,
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    cover_image VARCHAR(500) DEFAULT '' COMMENT '封面图片路径',
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
    INDEX idx_as_user (username),
    INDEX idx_as_created (created_at)
)

CREATE TABLE IF NOT EXISTS alumni_story_comments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    story_id INT NOT NULL,
    username VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_asc_story (story_id)
)

CREATE TABLE IF NOT EXISTS alumni_story_likes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    story_id INT NOT NULL,
    username VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_asl (story_id, username)
)
```

**Template:** `templates/alumni_stories.html`
- Story list: cover cards with title, excerpt (first 100 chars), author, date, view/like/comment counts
- Filter: All / 已审核 (default public view)
- Sort: 最新 / 最热
- Admin view: pending review queue with approve/reject buttons
- Write page (modal or inline): title, cover image upload, rich text content (reuse markdown editor)
- Detail page: full article + comments + like button

**Route entries in app.py:**
```python
@app.route("/alumni_stories")
@login_required
def alumni_stories_page():
    _init_alumni_stories_tables()
    return render_template("alumni_stories.html", ...)

@app.route("/api/alumni_stories", methods=["GET", "POST"])
@login_required
def api_alumni_stories():
    # GET: list {page, status, sort} → paginated stories
    # POST: {title, content, cover_image} → INSERT (status='pending')

@app.route("/api/alumni_stories/<int:sid>")
@login_required
def api_alumni_story_detail(sid):
    # GET: full story + comments + like status
    # Increment view_count (avoid double count like forum fix)

@app.route("/api/alumni_stories/<int:sid>", methods=["PUT", "DELETE"])
@login_required
def api_alumni_story_edit(sid):
    # PUT: owner edit (title, content, cover_image)
    # DELETE: owner delete

@app.route("/api/alumni_stories/<int:sid>/comments", methods=["POST"])
@login_required
def api_alumni_story_comment(sid):
    # POST: {content} → INSERT, update comment_count

@app.route("/api/alumni_stories/<int:sid>/like", methods=["POST"])
@login_required
def api_alumni_story_like(sid):
    # Toggle like (uses forum_likes pattern)

@app.route("/api/admin/alumni_stories")
@login_required
def api_admin_alumni_stories():
    # Requires administrator permission
    # GET: pending stories list

@app.route("/api/admin/alumni_stories/<int:sid>/review", methods=["POST"])
@login_required
def api_admin_review_story(sid):
    # POST {action: "approve"|"reject", note: ""}
    # Update status, reviewer, review_note, reviewed_at
```

**Cover image upload:** Use existing upload directory pattern (e.g., `static/uploads/stories/`). Accept jpg/png/webp, max 2MB. Generate unique filename with UUID.

---

## Phase 4: 番茄钟增强

### Feature 5: 番茄钟增强 (`/pomodoro` — enhance existing)

**DB Table:** `pomodoro_sessions` (in main DB_CONFIG)
```sql
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
```

**Enhance existing `templates/pomodoro.html`:** Keep existing timer, add:
- Task name input before starting
- Today's stats: 已完成 X 个番茄 / 总专注 XX 分钟
- Session history list (today, this week)
- Weekly chart (bar chart with Chart.js — already loaded in base)
- Leaderboard (this week top 5 by total minutes)

**New route entries:**
```python
@app.route("/api/pomodoro/sessions", methods=["GET", "POST"])
@login_required
def api_pomodoro_sessions():
    # GET: list for current user {period: "today"|"week"|"all"}
    # POST: {task_name, duration, planned_duration, completed} → INSERT

@app.route("/api/pomodoro/stats")
@login_required
def api_pomodoro_stats():
    # Returns {today_count, today_minutes, week_data: [{date, count, minutes}], streak}

@app.route("/api/pomodoro/leaderboard")
@login_required
def api_pomodoro_leaderboard():
    # Returns top 5 this week: [{username, total_minutes, sessions_count}]
```

**Note:** Existing `_init_life_tables()` already handles expenses/habits/bookmarks/rss tables. Add `_init_pomodoro_table()` and call from `_init_life_tables()`.

---

## Phase 5: PDF 工具集 + 电子宠物

### Feature 6: PDF 工具集 (`/pdf_tools`)

**Dependency:** `pip install PyPDF2` (add to requirements)

**Template:** `templates/pdf_tools.html`
- Tab-based UI: Merge / Split / Compress / Extract Text
- Merge tab: file input (multiple), drag-and-drop reorder, merge button → download
- Split tab: file input, page range input (e.g., "1-3,5,7-10"), split button → download zip
- Compress tab: file input, quality slider, compress button → download
- Extract Text tab: file input, extract button → text output area + copy button

**Route entries in app.py:**
```python
@app.route("/pdf_tools")
@login_required
def pdf_tools_page():
    return render_template("pdf_tools.html", ...)

@app.route("/api/pdf/merge", methods=["POST"])
@login_required
def api_pdf_merge():
    # Accept multiple files, merge with PyPDF2.PdfMerger
    # Save to temp, return filename for download
    # Cleanup after 5 minutes via scheduled task or on next request

@app.route("/api/pdf/split", methods=["POST"])
@login_required
def api_pdf_split():
    # Accept file + page_ranges, split with PyPDF2
    # Return zip download

@app.route("/api/pdf/compress", methods=["POST"])
@login_required
def api_pdf_compress():
    # Accept file, compress with PyPDF2 page.compress_content_streams()
    # Return download

@app.route("/api/pdf/extract_text", methods=["POST"])
@login_required
def api_pdf_extract_text():
    # Accept file, extract text with PyPDF2
    # Return {"text": "extracted content"}

@app.route("/api/pdf/download/<filename>")
@login_required
def api_pdf_download(filename):
    # Serve temp file, then delete
    # Safety: validate filename (no path traversal)
```

**Security notes:**
- Use `werkzeug.utils.secure_filename()` for all uploads
- Store temp files in `/tmp/pdf_tools/` with UUID names
- File size limit: 20MB
- Cleanup old temp files periodically (>10 min old)

---

### Feature 8: 电子宠物 (`/pet`)

**DB Table:** `pets` (in main DB_CONFIG)
```sql
CREATE TABLE IF NOT EXISTS pets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    pet_name VARCHAR(30) DEFAULT '小可爱',
    pet_type VARCHAR(20) DEFAULT 'cat',
    hunger INT DEFAULT 100 COMMENT '0=starving 100=full',
    happiness INT DEFAULT 100 COMMENT '0=sad 100=happy',
    energy INT DEFAULT 100 COMMENT '0=exhausted 100=energetic',
    level INT DEFAULT 1,
    xp INT DEFAULT 0,
    hatched TINYINT DEFAULT 0 COMMENT '0=egg 1=hatched',
    last_fed TIMESTAMP NULL,
    last_played TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
)

CREATE TABLE IF NOT EXISTS pet_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL,
    action VARCHAR(20) NOT NULL COMMENT 'feed/play/sleep/hatch/levelup',
    detail VARCHAR(100) DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_pl_user (username, created_at)
)
```

**Template:** `templates/pet.html`
- Pet display area: CSS-based pet character (simple emoji + CSS animation, or SVG)
  - Egg state: 🥚 with gentle wobble animation
  - Cat: 🐱 with idle animation (tail wag, blink)
  - Dog: 🐶 with idle animation
  - Can switch pet type on rename
- Status bars: ❤️饥饿 | 😊快乐 | ⚡精力 (colored bars)
- Action buttons: 🍖喂食 | 🎾玩耍 | 💤睡觉
- Level and XP bar
- Activity log (last 10 actions)
- Pet name display (editable)

**Route entries in app.py:**
```python
@app.route("/pet")
@login_required
def pet_page():
    _init_pet_tables()
    return render_template("pet.html", ...)

@app.route("/api/pet")
@login_required
def api_pet():
    # GET: pet status (auto-decay stats based on time since last action)
    # If no pet → {has_pet: false, can_hatch: true}
    # Returns {has_pet, pet_name, pet_type, hunger, happiness, energy, level, xp, hatched, logs}

@app.route("/api/pet/hatch", methods=["POST"])
@login_required
def api_pet_hatch():
    # POST {pet_type: "cat"|"dog"|"rabbit"|"panda"} → CREATE pet with hatched=1

@app.route("/api/pet/action", methods=["POST"])
@login_required
def api_pet_action():
    # POST {action: "feed"|"play"|"sleep"}
    # feed: hunger +30 (max 100), happiness +5, energy +5
    # play: happiness +30 (max 100), hunger -10, energy -15
    # sleep: energy +40 (max 100), hunger -10
    # +10 XP per action, level up at 100 XP
    # Returns updated stats

@app.route("/api/pet/rename", methods=["POST"])
@login_required
def api_pet_rename():
    # POST {pet_name, pet_type} → UPDATE
```

**Stat decay system:**
```python
def calculate_decay(pet):
    """Calculate stat decay based on elapsed time."""
    now = datetime.utcnow()
    hours_since_fed = (now - pet['last_fed']).total_seconds() / 3600 if pet['last_fed'] else 0
    hours_since_play = (now - pet['last_played']).total_seconds() / 3600 if pet['last_played'] else 0

    # Hunger decays 5 per hour
    hunger_decay = int(hours_since_fed * 5)
    # Happiness decays 3 per hour
    happiness_decay = int(hours_since_play * 3)
    # Energy recovers 10 per hour (passive)
    energy_recovery = int(hours_since_fed * 10)

    pet['hunger'] = max(0, pet['hunger'] - hunger_decay)
    pet['happiness'] = max(0, pet['happiness'] - happiness_decay)
    pet['energy'] = min(100, pet['energy'] + energy_recovery)
    return pet
```

**Pet UI:** Use CSS-only animations + emoji characters. No external libraries needed. Example structure:
```html
<div class="pet-container">
    <div class="pet-character" id="petChar">🥚</div>
    <div class="pet-name">小可爱 Lv.1</div>
    <div class="stat-bars">
        <div class="stat-bar">❤️ <div class="bar-fill" id="hungerBar"></div></div>
        <div class="stat-bar">😊 <div class="bar-fill" id="happyBar"></div></div>
        <div class="stat-bar">⚡ <div class="bar-fill" id="energyBar"></div></div>
    </div>
    <div class="xp-bar">⭐ XP: <div class="bar-fill" id="xpBar"></div></div>
    <div class="pet-actions">
        <button class="btn-pet" data-csp-click="petAction" data-csp-args='["feed"]'>🍖 喂食</button>
        <button class="btn-pet" data-csp-click="petAction" data-csp-args='["play"]'>🎾 玩耍</button>
        <button class="btn-pet" data-csp-click="petAction" data-csp-args='["sleep"]'>💤 睡觉</button>
    </div>
</div>
```

---

## Navigation / Sidebar Integration

All new pages need entries in `templates/dashboard.html` sidebar:

```html
<!-- 校友社区 区块 (after /alumni and /forum) -->
<a href="/alumni_stories">📖 校友故事</a>
<a href="/confession">🌳 匿名树洞</a>

<!-- AI 工具 区块 (after chat) -->
<a href="/ai_writing">✍️ AI 写作</a>
<a href="/translator">🌐 智能翻译</a>

<!-- 个人工具 区块 (after pomodoro) -->
<a href="/checkin">📅 每日签到</a>

<!-- 工具集 区块 -->
<a href="/pdf_tools">📄 PDF 工具</a>

<!-- 趣味 区块 -->
<a href="/pet">🐾 电子宠物</a>
```

---

## Implementation Order & Task Count Estimate

| # | Feature | Tasks | New Tables | New Templates | Pip Deps | Risk |
| 3 | AI 写作助手 | ~12 tasks | 0 | 1 | 0 | Low |
| 4 | 智能翻译 | ~8 tasks | 0 | 1 | 0 | Low |
| 7 | 签到打卡日历 | ~15 tasks | 1 | 1 | 0 | Low |
| 2 | 匿名树洞 | ~18 tasks | 3 | 1 | 0 | Low |
| 1 | 校友故事 | ~25 tasks | 3 | 1 | 0 | Med (file upload) |
| 5 | 番茄钟增强 | ~12 tasks | 1 | 0 (enhance) | 0 | Low |
| 6 | PDF 工具集 | ~18 tasks | 0 | 1 | PyPDF2 | Med (file handling) |
| 8 | 电子宠物 | ~20 tasks | 2 | 1 | 0 | Med (complex UI) |
| **Total** | | **~128 tasks** | **10 tables** | **7 templates** | **1 dep** | |

---

## Key Pitfalls (based on existing codebase knowledge)

1. **CSP constraints:** No inline `style=""` attributes → use CSS classes. No `onclick=""` → use `data-csp-click`. JS innerHTML with inline styles will be silently blocked.
2. **Session permission check:** Use `session.get("permission") == "administrator"` NOT `session.get("is_admin")`.
3. **All API endpoints need `@login_required`** except render-template routes that don't access data.
4. **DB connection pattern:** Always `cursor.close(); conn.close()` after each query. Two DBs: `get_db()` for main, `get_album_db()` for album/chat/AI.
5. **AI features:** Reuse `_ai_decrypt()` and `ai_config` table from `get_album_db()`. The `/api/chat/ai/ask` pattern (lines 4343-4442) is the reference for AI calls.
6. **View count bug prevention:** Don't increment view_count on every GET — use the forum fix pattern (separate view tracking or only increment on first load).
7. **Table init:** Follow `_init_reset_table()`, `_init_life_tables()`, `_init_forum_tables()` patterns. Group related tables in one init function. Add calls to `_init_db_once()`.
8. **Column migration safety:** Follow the `try/except pass` pattern for adding columns to existing tables.
9. **JSON field values:** Python `True`/`False` goes to MySQL as 1/0 for TINYINT.
10. **File upload safety:** Always `secure_filename()`, validate extensions, store outside webroot or in static/uploads/.
