---
name: ingest-book
description: 把投资大V的多年合集 PDF（典型 2000+ 页 / >500MB）按批阅读、增量沉淀到 knowledge/gurus/<昵称>/ 下。触发：用户提到要"读老唐 2017 / 把段永平 2020 录入 / 继续读到第几页"等多会话长 PDF 阅读任务；或在 knowledge/gurus/<昵称>/posts/ 下看到 *-DRAFT.md 文件需要续读。与 [[ingest-guru]] 区别：guru 处理单篇文章/帖子/持仓，book 处理跨会话的整本 PDF。
---

# ingest-book

把一本/一年的投资人合集 PDF → 增量笔记 → 结构化知识库的**多会话流水线**。

## 何时激活

- 用户提到要读 / 继续读某本 PDF（典型句式："读老唐 2017"、"继续读到第几页"、"把段永平 2020 录入"）
- `knowledge/gurus/<昵称>/posts/` 下有 `YYYY-DRAFT.md` 且 `status: 阅读中`
- 用户贴出一份大 PDF（>100MB）并希望系统性消化

**与 [[ingest-guru]] 的分工**：
- `ingest-guru`：单篇文章 / 单次持仓表 / 单次观点 → 一次性归档
- `ingest-book`：多年合集 PDF / 2000+ 页 / 需要跨多个会话 → 流水线处理

## 全流程 4 阶段

```
Phase 0: Setup      → 拆 PDF + 建状态文件        → references/phase0-setup.md
Phase 1: 迭代阅读   → 20 页一批，跨会话恢复       → 本文件（热路径，见下）
Phase 2: 整理沉淀   → DRAFT → posts/YYYY.md + style/playbook 增量 → references/phase2-consolidate.md
Phase 3: Skill 打包 → 累积 ≥3 年笔记后做 guru 专属 SKILL.md       → references/phase3-package-skill.md
```

> **Phase 1 是每会话高频执行的热路径，正文保留在本文件**。Phase 0/2/3 是低频步骤（每本/每年/每人一次），按需读对应 `references/` 文件，不必每次加载。

---

## Phase 1: 迭代阅读循环（每会话执行多次，可跨会话恢复）

### 1.1 会话启动 SOP（< 60 秒）

任何中断（compaction / 退出 / 切话题）后重新开始：

1. **Read** `knowledge/gurus/<昵称>/READING_STATE.md` → 选当前 `[阅读中]` 书
2. **Read** 对应 `posts/YYYY-DRAFT.md` 前 30 行（frontmatter）→ 拿 `next_read_cmd`
3. 直接执行 `next_read_cmd`

**不要做**：
- ❌ grep 整个 DRAFT 找位置（frontmatter 已给定位）
- ❌ Read DRAFT 全文（7000+ 行会爆 context）
- ❌ 问"上次读到哪了"（READING_STATE + frontmatter 已记录）

### 1.2 每批处理流程

```
Read part_N.pdf pages X-X+19     ← 20 页一批（约 5-8 篇文章）
       ↓
理解内容（识别文章边界、提取金句/数据/playbook）
       ↓
Edit DRAFT append:
  ### #N《文章标题》(YYYY-MM-DD) — ★ 简短标签

  #### 写作背景
  - 日期 / 起因 / 关联前文

  #### 正文要点
  1. ...（核心论点 / 数据 / 金句）

  #### 评论区精华
  1. **金句标题**（赞数 / 网友 → 大V 回应）

  #### playbook 沉淀
  - 与既有 playbook 关联 / 新工具 / 反向案例
       ↓
Edit DRAFT 持仓变化时间线表 append 行（如批中出现持仓动作）
       ↓
更新状态（3 处）:
  a) DRAFT frontmatter:
     - progress: X/TOTAL (X%)
     - next_page: X+20
     - next_file / next_read_cmd
     - last_article: "#N ..."
     - next_hint: "#N+1 ..."
     - last_session: today
  b) READING_STATE 对应 block 末尾 4 行同步
  c) 若 next_page 达 part 末尾 → 触发拆下一份:
     ~/.claude/bin/pdf-split <SRC> <next_start> <next_end> partN+1
       ↓
1-2 句报告本批关键收获
       ↓
直接读下一批（不问"继续吗"）
```

### 1.3 评论区策略

**详细记录所有金句 + 评论区时间线行**

- 评论区是大V独家披露的高浓度来源（如"爆仓后第一桶金=工作"类信息只在评论里）
- 每条金句格式：`**标题**（赞数 / 网友提问 → 大V 回应）`
- 评论区时间线行加 ` | #N 评论` 标记区分

### 1.4 何时停下问用户

仅以下 3 种情况停下：
1. 一份 part PDF 完整读完，确认是否拆下一份（或自动拆即可，无需停）
2. PDF 渲染异常 / 章节切换可能需要换策略
3. 用户主动打断

**绝不**在每批末尾问"继续吗"。已在用户 memory `feedback_pdf_reading_dont_ask` 记录。

### 1.5 nudge：每隔几批做一次小修

每 ~10 批（200 页）做一次轻量整理：
- 检查 DRAFT 是否有重复 section
- 时间线表是否被切断
- frontmatter 字段是否仍准确

---

## 其它阶段（按需读 references/）

- **Phase 0 Setup**（每本新书一次）：拆 PDF、建 READING_STATE、建 DRAFT → `references/phase0-setup.md`
- **Phase 2 整理沉淀**（每年读完一次）：DRAFT → posts/YYYY.md + style/playbook/current-view/coverage 增量 → `references/phase2-consolidate.md`
- **Phase 3 Skill 打包**（一个 guru ≥3 年后一次）：生成 guru 专属 SKILL.md → `references/phase3-package-skill.md`

---

## 关联 skills

- [[ingest-guru]]：单篇/单次的归档（本 skill 的对照）
- ~~[[guru-view]]~~：**已删除**·待重新设计
- ~~[[backtest-call]]~~：**已删除**·待重新设计
- `guru-query` 通用大V查询 skill：读取 Phase 2 产出的 `gurus/<slug>/routes.md` + `discipline.md`（原 Phase 3 "打包专属 skill" 已废弃·2026-07-03 抽象化·新增大V只需建两个数据文件 + 更新 guru-query description）

## 工具栈

| 工具 | 位置 | 用途 |
|------|------|------|
| `pdf-split` | `~/.claude/bin/pdf-split`（user-level）| PDF 按页拆分 |
| `READING_STATE.md` | `knowledge/gurus/<昵称>/`（项目内）| 阅读进度仪表板 |
| `YYYY-DRAFT.md` | `knowledge/gurus/<昵称>/posts/`（项目内）| 增量阅读笔记 |
| `posts/YYYY.md` | 整理后的最终笔记 | 知识库正式部分 |
| `style.md` / `playbook.md` | `knowledge/gurus/<昵称>/`（项目内）| 风格画像 / 工具箱（增量更新）|
| guru 专属 SKILL.md | `.claude/skills/<昵称>/`（项目内）| Phase 3 产出 |

---

## 关键约束（精简）

- **PDF**：单文件 Read 上限 100MB → 必须拆分；拆分粒度 200 页 → 80-95MB 安全区；Read 用 `pages` 参数（不是 limit/offset）。见用户 memory `feedback_pdf_reading_dont_ask`。
- **字符编码**：macOS bash 3.2 有 UTF-8 + 变量插值 bug；脚本中变量插值附近用 ASCII 标点（`()` 不 `（）`），正文中文不受影响。见 `~/.claude/bin/pdf-split` 顶部 NOTE。
- **流程**：不在批次末尾问"继续吗"；不读 7000+ 行 DRAFT 全文；跨会话恢复链 = READING_STATE → DRAFT frontmatter → next_read_cmd。
- **Bash**：遵循全局 `~/.claude/rules/bash-commands.md`（单命令、不复合、不用 cat/sed/awk）。

> 各 guru 的阅读进度（哪本读到哪）记录在各自的 `READING_STATE.md`，**不写进本 skill**。

---

## 更新记录

- 2026-05-16: v1 初版。基于唐朝 2016 完整读完 + 2017 进行中的实践提炼。落地工具：`~/.claude/bin/pdf-split` / `READING_STATE.md` per-guru 仪表板 / DRAFT frontmatter 标准化。
- 2026-06-21: v2 瘦身。按渐进披露把 Phase 0/2/3 拆到 `references/`，主文件只留热路径 Phase 1；删除会 drift 的「现状对照」进度表（进度归 READING_STATE）；约束清单精简、去掉与全局 rules 的重复。analyze-stock/compare-views 合并为 guru-view 后同步关联引用。
