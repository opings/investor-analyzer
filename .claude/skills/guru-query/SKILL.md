---
name: guru-query
description: |
  用某大V视角查询——覆盖所有已沉淀大V·**一个 skill 服务所有大V**·避免每加一位建一个 skill 的膨胀。
  本 skill 是"查询逻辑"·大V特有的路由/纪律/方法论**在 `gurus/<slug>/routes.md` + `discipline.md`**。
  
  触发词（提到任一即强制激活·不要从训练数据回答）——
  【老唐/唐朝】唐朝/老唐/唐朝大哥/唐兄/唐书房/唐书院/手把手教你读财报/价值投资实战手册/巴芒演义/投资研习录/老唐估值法/五段估值法/三年后25-30倍PE/至简三板斧/15-25-50三区/资本永不眠/三大前提/周期股席勒法/笋子粽子瘫子/理性外推/对折买入大法/散打巴菲特/经典陪读/维斯科陪读/投资的底层逻辑/唐九条/三大V型反转/核心五观/规范动作论/正面我赢反面不输/关注波不要关注波动/告别篇/关闭实盘/60魔咒/市场先生/后腿鹅/珍爱生命远离杠杆/不可思量/没操作是最难的操作/滚动三年首亏/宏观必须承受微观才可努力/回购就是帮股东买入/投资圣经/书房外传/糖指数/理性外推/茅台五大护城河/2024表现/2025表现·
  
  【段永平】段永平/大道无形我有型/大道/阿段/投资问答录/投资逻辑篇/毛估估/苹果毛估估模板/买股票就是买公司/现金流折现思维/不懂不碰/能力圈/stop doing list/不为清单/做对的事情/本分/平常心/只需富一次/不做空/不借钱不用margin/持有就是买入/right business+people+price/卖put是投资·段永平怎么看 苹果/茅台/网易/拼多多/泡泡玛特/GE·
  
  强制走本 skill 查询·**不要从训练数据回答**！骨架大V（⚪）返"未沉淀·无法查询"。
---

# guru-query · 通用大V视角查询

> **一个 skill 服务所有大V**·避免每加一位大V建一个 skill 的膨胀（原 `tangchao` / `duanyongping` 两个专属 skill 已于 2026-07-03 抽象合并至此·备份在 `/tmp/`）。
> **本 skill 只做"查询逻辑"**·大V特有的**路由表 / 稳定方法论 / 调用纪律**全部在 `knowledge/gurus/<slug>/routes.md` + `discipline.md`·随大V数据同目录·内聚。

## 何时激活

当用户提到某位已沉淀大V的**昵称 / 代表作 / 代表方法 / 代表金句** + 询问观点/立场/估值/持仓/复盘等场景时·**强制激活本 skill·不要从训练数据回答**。

具体触发词见 description。**未来 ingest 新大V → 更新 description 追加该大V别名 + 建 `gurus/<slug>/routes.md` + `discipline.md`·本 skill 逻辑无需改动**。

## 已沉淀大V列表

以 `knowledge/gurus/INDEX.md` 为花名册**唯一权威**（第一步必读）。当前已沉淀 ✓：

- **`tangchao`**（老唐 / 唐朝）· 2016-2025 · 1137 篇 / 16000+ 页 · 有 `routes.md` + `discipline.md`
- **`duanyongping`**（段永平 / 大道 / 阿段）· 2010-2020 · 《投资问答录·投资逻辑篇》426 页 · 有 `routes.md` + `discipline.md`

骨架 ⚪（13 位·未 ingest）：warren-buffett / charlie-munger / ben-graham / phil-fisher / peter-lynch / mohnish-pabrai / rakesh-jhunjhunwala / bill-ackman / cathie-wood / aswath-damodaran / michael-burry / nassim-taleb / stanley-druckenmiller

---

## 工作流

### Step 0 · 大V身份映射

1. Read `knowledge/gurus/INDEX.md` 花名册·把用户输入的中文名/别名映射到目录 slug
2. INDEX 里查不到 → 该大V**未收录**·**不臆造目录**·告知用户
3. 状态 = ⚪ 骨架 → 直接返"**该大V知识库尚未录入·无法基于已沉淀观点查询**"·**不硬答**（不拿模板/训练数据作答）
4. 状态 = ✓ 已沉淀 → 进 Step 1

### Step 1 · 读大V特有的路由 + 纪律

**必读两个数据文件**（在 `knowledge/gurus/<slug>/` 下）：

1. Read `routes.md` —— 该大V的路由表 + 稳定方法论 + 知识库路径
2. Read `discipline.md` —— 该大V的调用纪律 + 避坑清单 + 观点演化清单

**为什么必读**：不同大V的路由不同（老唐 150+ 条 · 段永平 20+ 条）·纪律也不同（老唐按年、段按议题；老唐有金句出处表·段有"泡泡玛特库外二手"提示）。硬编在通用 skill 里会失真。

### Step 2 · 按路由查对应 KB 文件

根据 `routes.md` 的映射表·按用户问题类型查具体文件：

- **当前立场** → `current-view.md`（收敛快照·优先读）
- **风格演化** → `style.md` 对应年份/议题
- **具体标的观点** → grep `posts/YYYY.md` + `calls/YYYY-calls.md`
- **持仓** → `holdings/YYYY-持仓变化.md`
- **覆盖热力图** → `coverage.md`（引用前必查·防落在空洞时段硬答）

**先查 `coverage.md`**·落在 ✗ 空洞时段 → 主动声明"该时段无数据"·不用邻近时段硬答。

### Step 3 · 按 discipline.md 纪律输出

回答时**必守大V特有的 discipline.md 纪律**（如老唐必带 #N + 日期·段按议题引用不按年）。输出必带：

- **视角明确标识**："老唐（截至 2024 末）说..."/"段永平（按议题·2013 章节）说..."·非"事实上..."
- **出处**（#N + 日期 / 章节 / 文件路径）·让用户可回溯原文
- **保守措辞**：用"更可能"、"倾向于"·不用"会"、"一定"

---

## 跨大V通用铁律（大V特有的另在 discipline.md）

1. **不从训练数据回答**·必须查 `gurus/<slug>/`·查不到就说没有
2. **骨架大V不硬答**·先查 INDEX 状态（⚪ → 直接返"未沉淀"）
3. **不替大V发表新观点**·只呈现已沉淀内容
4. **视角必带标识**·"老唐说" ≠ 事实·"段永平说" ≠ 现在还这么看
5. **落在空洞时段先声明**（先查 `coverage.md`）
6. **保守措辞** + **观点带时间戳**·防止过期观点被误用
7. **原文出处必带**·方便用户回溯 KB

---

## 与其他 skill 的分工

| skill | 定位 | 与本 skill 的关系 |
|---|---|---|
| `ingest-guru` / `ingest-book` | 写入大V库（把原始材料结构化到 `gurus/<slug>/`）| **上游数据源**·本 skill 读取产物 |
| ~~`backtest-call`~~ | **已删除**·待重新设计（2026-07-03）| — |
| `company-analysis` | 建/刷新 `finance/<公司>/` 客观事实底座 | 独立·不依赖本 skill |
| `daily-news` | 每日新闻核验·喂事实编年 | 独立·可能提示"结合大V视角复盘"→ 引导用户调本 skill |

---

## 新增大V的流程（无需改本 skill）

想 ingest 新大V（如巴菲特）时：

1. `ingest-book` / `ingest-guru` 走 Phase 0-2·沉淀到 `gurus/<slug>/`（profile / style / current-view / coverage / posts / calls / holdings / playbook）
2. **在 `gurus/<slug>/` 下建 `routes.md` + `discipline.md`**（参考 tangchao / duanyongping 的结构）
3. **更新 `gurus/INDEX.md`**：把该大V从 ⚪ 骨架 → ✓ 已沉淀
4. **更新本 skill 的 description**：追加该大V的触发词（昵称 + 代表作 + 代表方法 + 代表金句）
5. **无需其他改动**·本 skill 会自动能查

这就是"抽象化"的核心价值：**新增大V = 建两个数据文件 + 更新一次 description·不再建 skill 目录**。

---

## 关联

- `knowledge/gurus/INDEX.md`：花名册·slug 映射唯一权威·第一步必读
- `knowledge/gurus/<slug>/routes.md`：大V特有路由 + 稳定方法论
- `knowledge/gurus/<slug>/discipline.md`：大V特有调用纪律 + 避坑
- 上游：`ingest-guru`（单篇归档）· `ingest-book`（整本 PDF 流水线）
- ~~下游：`backtest-call`~~（已删除·待重新设计）
