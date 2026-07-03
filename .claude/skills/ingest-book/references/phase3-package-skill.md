# ingest-book · Phase 3：建 routes.md + discipline.md（一个 guru 累积 ≥3 年笔记后·30 分钟）

> ⚠️ **2026-07-03 抽象化改版**：原 Phase 3 "打包专属 skill"（每位 guru 一个 `.claude/skills/<slug>/SKILL.md`）已废弃·统一改为**通用 `guru-query` skill + 大V特有 `routes.md` + `discipline.md`**。原专属 skill（tangchao / duanyongping）已删除·数据迁到 `gurus/<slug>/`。

## 3.1 触发条件

- 单一 guru 累积至少 3 年完整年度笔记（或议题合集足够密集）
- 或用户明确说"想能直接问 XX 怎么看 YY"
- 数据厚度足够支撑"调用查询比训练记忆更准"

## 3.2 现在要建的两个文件（数据·不是 skill）

路径：`knowledge/gurus/<slug>/routes.md` + `knowledge/gurus/<slug>/discipline.md`（**跟大V数据同目录·内聚**）

### `routes.md` 骨架（"用户问什么 → 读哪个文件"路由）

```markdown
# <大V昵称>（<slug>）· 路由表 + 稳定方法论

> 由通用 `guru-query` skill 读取。调用纪律见同目录 [[discipline.md]]。

## 触发词（提到即应查询该大V视角）

- **昵称**：<昵称> / <别名 1> / <别名 2>
- **代表作**：<书名 1> / <书名 2>
- **代表方法**：<方法名 1> / <方法名 2>
- **代表金句**：<金句 1> / <金句 2>

## 知识库路径

`knowledge/gurus/<slug>/`（结构：profile / style / current-view / coverage / posts / calls / holdings / playbook）

## 检索路由表

| 用户问题 | 查询路径 |
|---|---|
| 该大V当前立场 | `current-view.md` |
| 估值方法 | `playbook.md` §1 + `current-view.md` "估值方法" |
| 选股标准 | `playbook.md` §2 + `current-view.md` "选股标准" |
| 具体标的观点 | `posts/YYYY.md` + `calls/YYYY-calls.md` |
| 持仓历史 | `holdings/YYYY-持仓变化.md` |
| 某年表现 | `posts/YYYY.md` 年度总结 |
| 某金句出处 | grep `posts/` + 给出 #N + 日期 |
| ...（大V特有的问答映射，越具体越准）| |

## 稳定方法论（不会变·可直接引用）

<大V的估值公式 / 选股框架 / 风险纪律等·可直接答不必查 KB 的部分>
```

### `discipline.md` 骨架（"回答时要遵守什么规范"纪律）

```markdown
# <大V昵称>（<slug>）· 调用纪律 + 避坑

> 由通用 `guru-query` skill 读取。跨大V通用铁律见 `.claude/skills/guru-query/SKILL.md`。

## 铁律 N 条（该大V专属）

1. 必须给出**具体文章 #N + 日期**（或章节名·若按议题归档）
2. 区分已验证 / 已打脸 / 待验证判断（调用 `calls/` 时）
3. 不要混用不同年份的观点（列演化清单）
4. 优先引用最新一年·除非用户问"最初怎么说"
5. 引用金句必须给出处（列金句 → 出处对照表）
6. ...（该大V特有的·如段永平"按议题非按年"·"泡泡玛特库外二手"）

## 观点演化清单（不要混用）

- <议题 1>：<年份> <立场 A> → <年份> <立场 B>
- <议题 2>：...

## 引用金句必带出处

| 金句 | 出处 |
|---|---|
| ... | #N（YYYY-MM-DD） |

## 不要做的事

- ❌ 从训练数据回答该大V观点
- ❌ 无引用地给金句
- ❌ 把别的投资人的话归到该大V名下
- ❌ 混用不同年份观点
- ❌ 落在无数据时段硬答（先查 coverage.md）

## 典型问答示例
（示范正确的引用纪律·让 guru-query 有参考）
```

## 3.3 建完后要做的两件事

1. **更新 `gurus/INDEX.md`**：把该大V从 `⚪ 骨架` 移到 `✓ 已沉淀` 表
2. **更新 `.claude/skills/guru-query/SKILL.md` 的 description**：追加该大V的触发词（昵称 + 代表作 + 代表方法 + 代表金句）到 description 里·让 skill 自动识别

**不需要新建 skill 目录**·这是抽象化后的核心价值。

## 3.4 关键约束（继承自原版）

⚠️ **反面教材**：不要把大段**业绩/持仓数据**内嵌进 `routes.md`（会与 `current-view.md`/`holdings/` 双写、必然 drift）。`routes.md` 是**路由指引 + 稳定方法论**·**不是数据仓库**。会变的数据（业绩/持仓/估值锚）只写指针·让 `guru-query` 按需读 KB 文件。tangchao / duanyongping 的 routes.md 是好范本。

## 3.5 验证

- 用户输入触发词 → `guru-query` 自动激活 → Read `gurus/<slug>/routes.md` + `discipline.md` → 按路由查 KB → 输出带出处
- 抽 5 个典型问题测试 `guru-query` 回答是否引用具体出处
- 落在 coverage.md 空洞时段·测试是否主动声明"无数据"

## 3.6 迁移历史（2026-07-03 抽象化）

原 Phase 3 "打包专属 skill" 已废弃。原 `tangchao` / `duanyongping` skill 结构 → 拆分：
- 路由表（150+ 条）+ 知识库路径 + 稳定方法论 → 迁到 `gurus/<slug>/routes.md`
- 调用纪律 + 避坑清单 + 观点演化 + 金句出处 → 迁到 `gurus/<slug>/discipline.md`
- 触发词 → 迁到 `guru-query` skill 的 description（列所有已沉淀大V别名）
- 版本记录 → 保留在 `routes.md` 底部

新增大V走本 Phase 时·直接建 routes.md + discipline.md·不建 skill 目录。
