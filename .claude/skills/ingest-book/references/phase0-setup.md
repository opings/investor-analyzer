# ingest-book · Phase 0：Setup（每本新书一次，~5 分钟）

## 0.1 评估文件 & 拆分

```bash
# 预览（不真拆）
~/.claude/bin/pdf-split <SRC_PDF> info 200

# 一次性全本拆完
~/.claude/bin/pdf-split <SRC_PDF> auto 200
```

**输出**：`/tmp/pdf-split/<basename-no-ext>/partN.pdf`

**约束**：每份 ≤95MB（Read 工具 100MB 上限，留 5MB 余量）。工具会自动警告 >95MB / 报错 >100MB。

依赖：`brew install poppler`

## 0.2 建立 / 更新 READING_STATE

per-guru 仪表板：`gurus/<昵称>/READING_STATE.md`

- 已有 guru：在文件中新增 `## [阅读中] YYYY.pdf` block
- 新 guru：从 `gurus/tangchao/READING_STATE.md` 复制模板，改 5 行字段

每个 book block 必须有：源路径 / 总页数 / DRAFT 路径 / 进度 / 上批末 / 下批起 / 待读 hint / 分卷状态 / 拆下一份命令 / last_session。

## 0.3 创建 DRAFT.md

路径：`gurus/<昵称>/posts/YYYY-DRAFT.md`

**精简 frontmatter 模板（12 行）**：

```yaml
---
year: 2017
source: /path/to/book.pdf (TOTAL 页 / 来源描述)
status: 阅读中
progress: 0/2258 (0%)
next_page: 1
next_file: /tmp/pdf-split/2017/part1.pdf 第 1 页 (= 2017.pdf 第 1 页)
next_read_cmd: Read /tmp/pdf-split/2017/part1.pdf pages 1-20
last_article: "(未开始)"
next_hint: "#1 第一篇"
splits: part1(1-200) part2(201-400) ... / partN-M 待拆
split_next_cmd: ~/.claude/bin/pdf-split /path/to/book.pdf 201 400 part2 (当 next_page 达 201 时)
last_session: YYYY-MM-DD
state_file: gurus/<昵称>/READING_STATE.md
---
```

DRAFT 主体起始 = "## 持仓变化时间线" + "## 已读文章笔记" 两个 section。
