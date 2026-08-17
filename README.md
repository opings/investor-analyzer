# investor-analyzer

个人投研知识库 + 分析助手。核心理念：**数据沉淀 > 一次性结论**，**只要事实、不要传闻**，**不预测、只归纳**。

把大V的文章/持仓、公司的财报/公告、造假公司的处罚决定书喂进来，沉淀成结构化知识库；
之后所有分析（估值、点评、复盘、风险预警）都基于**已沉淀的库**，而非临时抓取。

整个系统由三大模块组成，全部以 **markdown 知识库 + `.claude/skills/` 编排** 实现，外加两个行情/公告 Python 脚本。

---

## 三大模块

本质是**分析一家公司**。按「判断的性质」正交切成三块——**客观事实 / 别人的观点 / 我的主观判断**，三者落盘纪律各不相同、互不越界。

### 模块一 · 客观分析（公司客观长什么样·零主观判断）
拿到任何一家公司，先建真实事实底座，再只回答「这家公司是什么样」——不碰「我懂不懂 / 值多少 / 买不买」。含正面（商业模式/生意质量）与反面（排雷与风险），产出对公司的客观认识 + 生意质量评级（好/平庸/差/回避）。

- **分析宪法**：`knowledge/frameworks/研究新公司-分析流程.md` — 我自己的价值投资分析主流程（去单一大V署名·事实底座三样 → 商业模式/排雷两块漏斗）
- **知识库**
  - `finance/<公司>/` — 公司客观分析三件套（`财务数据/<csv>` + `分析.md` + `财报关注要点.md`，canonical 客观数据；**不出现任何主观决策**）·已覆盖 A 股 / 港股 / 美股（`google` = Alphabet 年度 2002–2025 + **2026 中期(Q2 10-Q)**，SEC EDGAR + XBRL + 10-Q 管线跑通；`spacex` = 2026-06 刚 IPO，**首家「零份年报」建库**——底座 = 424B4 招股书 F 页经审计三年 + 上市后首份 10-Q，HTML 表格解析管线）
  - `knowledge/companies/<公司>/` — 公司**事实编年**（时间·主体·事件，只记客观事实，不写判断）。**唯一花名册 `companies/INDEX.md`**（公司全集 single source），监控子集 `_watchlist.md`（家数以表为准，勿写死）
  - `knowledge/fraud-cases/<公司>/` — 64 个财务造假案例（以中 A 股为主体，含美股/日股经典案例）+ `造假模式库.md`（排雷 = 客观分析的反面·反向蒸馏预警红旗）
  - `report/` — 各案例/公司的**源文档**（年报 PDF、处罚决定书、做空报告等，约 2.2G，不入 git）·仅源档柜
  - `knowledge/daily/` — 每日新闻哨兵输出的日报（`daily-news` skill 产出·蒸馏成果归 knowledge/）
- **skill**
  - `company-analysis` — 财报数据提取 → 建/刷新 `finance/` 客观三件套（强制「先提取再结论」，不编数据）
  - `daily-news` — 每日扫监控清单公司的新闻/公告，事实核验后追加进事实编年并出日报（见下「每日哨兵」）
  - `ingest-fraud-case` — 录入造假案例并蒸馏特征，增量喂养 `造假模式库.md`

### 模块二 · 大V理念蒸馏
把投资大V的原始数据蒸馏成「投资人画像」，再用其视角点评/对比标的、复盘历史判断。**大V是来源/灵感，不是我分析的招牌**——署名只留在本层。

- **知识库**：`gurus/<slug>/`（每位大V一目录，`profile / current-view / style / coverage / posts / holdings / calls`）
  - 花名册：`gurus/INDEX.md`（中文名→slug 映射 + 是否已沉淀。**查询类 skill 第一步必读**）
  - 已沉淀：`tangchao`(老唐 2016–2025 全量)、`duanyongping`(段永平《投资问答录》426 页)；其余 13 位为骨架待 ingest
- **skill**
  - `ingest-guru` — 喂单篇文章/帖子/持仓 → 归档
  - `ingest-book` — 跨会话读整本大V合集 PDF（2000+ 页）→ 增量沉淀
  - `guru-query` — **通用**大V视角查询·覆盖所有已沉淀大V（老唐 / 段永平·未来新增大V通过更新 description + 建 `routes.md`/`discipline.md`·**不再建专属 skill**）。原 `tangchao` / `duanyongping` 两个专属 skill 已于 2026-07-03 抽象合并（路由/纪律迁到 `gurus/<slug>/{routes.md, discipline.md}`）。
  - ~~`backtest-call`~~ / ~~`guru-view`~~ — **已删除**·待重新设计

### 模块三 · 主观分析（估值 / 能力圈 / 仓位 / 买卖点）
看懂公司之后的下游决策——关于**价格**（值多少）和**我自己**（懂不懂、敢押多少）。三轴正交：**评级**（公司好不好·属模块一） × **估值**（便宜不便宜） × **能力圈**（我懂不懂·定仓位上限）。

- **知识库**：`judgments/<公司>/`（2026-07-08 骨架已建·纯我的主观判断·**无大V署名·无客观数据双写**）
  - `估值.md` — 纯定稿台账(只增不改·每轮 append 一行:估值时间/P₀/P₁/g/P₃/r(合理PE)/总股本/买卖点市值与每股价;末行即现值)
  - `估值记录/YYYY-MM-DD/` — 每轮一个估值时间子目录:`推导.md`(完整推导·含「本估值的核心含义」必读段)+ `业务数据.html`(估值基石数据图·自包含 SVG)
  - `能力圈.md` — 我懂不懂 → 仓位上限(覆盖式)
  - `观点变更.md` — **append-only**·决策日志(同轮多修订各一行·末行标「定稿」)·可回算「我自己」的胜率
- **canonical**：`knowledge/frameworks/主观分析-workflow.md` — 六步骨架 + 估值公式菜单 + 双闸门 + 能力圈映射 + 结论矩阵(和 `研究新公司-分析流程.md` 客观 canonical 平级)
- **skill**：`judgment-flow` — 执行 workflow(Step 0-6·硬 gate 保 fresh 底座 + 双闸门·大V视角走 `guru-query` 现问现答不落盘)。触发词:`估一下 XX` / `跑 XX 主观` / `定 XX 买卖点` / `重估 XX` / `复评 XX` / `XX 现在便宜吗`
- **进度**：
  - **数据层部分落地** —— 已跑 4 家（`农夫山泉` / `泡泡玛特` / `贵州茅台` / `腾讯控股`）；其余 finance/ 客观已建的公司（五粮液/老窖/三环/云铝/华致/google/长江电力）主观判断待跑
  - **估值法菜单只上了 A 成长股 + E 归"太难"** —— B 周期股席勒法 / C 银行股 PB×ROE / D DCF 折现是 backlog(需要时加)
  - 组合级（仓位加总/买入排队/成交流水）进入实盘阶段再建
- **不做（明确 out of scope）**：大V回测 / 胜率复盘 / backtest-call —— 数据本质二手 + 幸存者偏差 + 老唐自反神化。原 `backtest-call` skill 已删·**不重建**。

---

## 目录结构

```
investor-analyzer/
├── knowledge/
│   ├── companies/<公司>/      # 模块一：公司事实编年（INDEX.md + _watchlist.md + _模板）
│   ├── fraud-cases/<公司>/    # 模块一：造假案例 + 造假模式库.md（排雷 = 客观分析的反面）
│   ├── frameworks/            # canonical：研究新公司-分析流程.md(客观) + 主观分析-workflow.md(主观)
│   └── daily/                 # 每日新闻哨兵输出的日报（含 _logs/ 不入 git）
├── finance/<公司>/            # 模块一：公司客观分析三件套（canonical 客观库·无主观决策·_模板 为模板）
├── gurus/<slug>/              # 模块二：大V画像（INDEX.md 为花名册，_模板 为模板）
├── judgments/<公司>/          # 模块三：主观层（估值.md 台账 + 估值记录/日期/{推导.md,业务数据.html} + 能力圈.md + 观点变更.md·由 judgment-flow skill 产出）
├── report/                    # 源文档（PDF/决定书，~2.2G 不入 git）·仅源档暂存柜
├── scripts/
│   ├── quote.py               # 区间行情（A股/港股/指数，前复权可复现）
│   ├── notices.py             # 巨潮(cninfo)一手公告拉取，给 daily-news
│   ├── derived.py             # 财务比率通用底（各 finance/<公司>/财务数据/财务比率.csv 生成器）
│   ├── _venv.py               # venv 自举封装，被各脚本调用自动激活 .venv（无需手动 activate）
│   ├── daily-news.sh          # 每日哨兵跑批（launchd 触发）— 本机专属，不入 git
│   ├── com.investor.daily-news.plist  # launchd 配置（工作日 16:00）— 本机专属，不入 git
│   ├── requirements.txt       # 行情脚本依赖（akshare）
│   └── .venv/                 # 脚本依赖，自举调用，无需手动激活（不入 git）

（注：clone 自 GitHub 时不含上面标「不入 git」的项 —— daily-news.sh / .plist / .venv，以及 report/ 下的 PDF 源档。）
└── .claude/skills/            # skill 集（按上面三模块组织，以目录实际为准）
```

## 每日新闻哨兵

`scripts/daily-news.sh` 由 launchd（`com.investor.daily-news.plist`，工作日 16:00）触发，
headless 跑 `daily-news` skill：拉一手公告 → 逐家核验 → 重大事件写进事实编年 → 产出 `knowledge/daily/<日期>.md`。
日志在 `knowledge/daily/_logs/`。手动测试：`bash scripts/daily-news.sh`。

> ⚠️ `daily-news.sh` 与 `.plist` 写死了本机绝对路径，属机器专属配置，**不入 git**（见「版本控制约定」）。
> 从 GitHub clone 下来**不含**这两个文件；要在新机器上启用哨兵，需按本机路径自行创建后 `launchctl load`。
> 可复用的哨兵逻辑（`scripts/notices.py` + `daily-news` skill）在仓库里，照常 clone 即得。

## 环境准备

行情/公告脚本依赖 akshare，已隔离在 `scripts/.venv`，脚本会**自举调用**（无需手动 `activate`）。
若 venv 损坏需重建：

```
python3 -m venv scripts/.venv
scripts/.venv/bin/pip install -r scripts/requirements.txt
```

## 设计原则

- **数据沉淀 > 一次性结论**：分析的输入应已在知识库里，避免临时抓
- **只要事实、不要传闻**：无一手/权威来源不入库；观点必带时间戳，否则无法复盘
- **不预测、只归纳**：工具只总结大V说过/做过什么，不替其发表新观点
- **职责不越界**：客观事实进 `companies/`；公司客观分析（商业模式/排雷/**生意质量评级**）进 `finance/<公司>/`；大V观点进 `gurus/`；**估值/能力圈/仓位/买卖点等主观判断进 `judgments/<公司>/`**（不落 `finance/`）；三套花名册共用同一套中文公司名以防漂移
- **事实与判断分层**：`companies/` 只记发生了什么（零判断）；`finance/<公司>/` 记公司客观长什么样（商业模式/排雷/生意质量，财报来了会被 `company-analysis` 重刷）；主观判断（估值/能力圈/仓位/买卖点）及其变更历史（`观点变更.md`·只增不改·可回头算自己胜率）落 `judgments/<公司>/`（估值台账 + 每轮估值记录目录 + 能力圈 + 观点变更·**大V视角审视走 `guru-query` 现问现答不落盘**）。组合级（仓位加总/买入排队/成交流水）进入实盘阶段再建
- **数据可信优先**：子代理抓老财报易出数字错误，入库前务必 QC（已知口径坑：归母 vs 扣非）

## 版本控制约定

仓库托管在 `opings/investor-analyzer`（private）。**只入库蒸馏后的成果与可复用逻辑，不入库源档、工作文件、机器专属配置。**
判断规则（已写进 `.gitignore`，新增内容前对照一下，别手滑把下面这些 `git add` 进来）：

| 入库 ✅ | 不入库 ❌（保留本地） |
|---|---|
| 蒸馏知识：`gurus/*/`（profile/current-view/style/calls/成品 `posts/*.md`）、`companies/*/`、`fraud-cases/*/`（含决定书/SEC 源页 `.html`，作一手证据）、`finance/*/`（客观三件套：`财务数据/*.csv` + `分析.md` + `财报关注要点.md`） | **`report/` 整个目录**：所有源档（PDF/年报/决定书/HTM/10-K.txt 等 ~2.2G）一律不入 git，纯本地"源档柜" |
| 可复用逻辑：`.claude/skills/`、`scripts/quote.py`、`scripts/notices.py`、`scripts/derived.py`、`scripts/requirements.txt` | **ingest 工作/状态文件**：`*-DRAFT.md`、`READING_STATE.md`（跨会话阅读进度，本地 WIP） |
| 数据产出：`knowledge/daily/` 日报（新闻哨兵的蒸馏成果·归 knowledge/） | **机器专属自动化**：`scripts/daily-news.sh`、`scripts/com.investor.daily-news.plist`（写死本机绝对路径，别人 clone 后需自行配 launchd） |
| | `scripts/.venv/`（用 `requirements.txt` 重建）；`gurus/*/_corpus/`（大V原始语料，只留蒸馏成品）；`finance/**/年报季报/`（源 PDF） |

**底线**：任何含本机绝对路径（`/Users/<用户名>/...`）或个人密钥的内容都不该入库——历史已审计为零泄露，保持下去。
新增大类文件前若拿不准，先 `git status` 看一眼会带进什么。
