# investor-analyzer

个人投研知识库 + 分析助手。核心理念：**数据沉淀 > 一次性结论**，**只要事实、不要传闻**，**不预测、只归纳**。

把大V的文章/持仓、公司的财报/公告、造假公司的处罚决定书喂进来，沉淀成结构化知识库；
之后所有分析（估值、点评、复盘、风险预警）都基于**已沉淀的库**，而非临时抓取。

整个系统由三大模块组成，全部以 **markdown 知识库 + `.claude/skills/` 编排** 实现，外加两个行情/公告 Python 脚本。

---

## 三大模块

### 模块一 · 大V理念蒸馏
把投资大V的原始数据蒸馏成「投资人画像」，再用其视角点评/对比标的、复盘历史判断。

- **知识库**：`gurus/<slug>/`（每位大V一目录，`profile / current-view / style / coverage / posts / holdings / calls`）
  - 花名册：`gurus/INDEX.md`（中文名→slug 映射 + 是否已沉淀。**查询类 skill 第一步必读**）
  - 已沉淀：`tangchao`(老唐 2016–2025 全量)、`duanyongping`(段永平《投资问答录》426 页)；其余 13 位为骨架待 ingest
- **skill**
  - `ingest-guru` — 喂单篇文章/帖子/持仓 → 归档
  - `ingest-book` — 跨会话读整本大V合集 PDF（2000+ 页）→ 增量沉淀
  - ~~`backtest-call`~~ — **已删除**·待重新设计
  - ~~`guru-view`~~ — **已删除**·待重新设计
  - `guru-query` — **通用**大V视角查询·覆盖所有已沉淀大V（老唐 / 段永平·未来新增大V通过更新 description + 建 `routes.md`/`discipline.md`·**不再建专属 skill**）。原 `tangchao` / `duanyongping` 两个专属 skill 已于 2026-07-03 抽象合并（路由/纪律迁到 `gurus/<slug>/{routes.md, discipline.md}`）。

### 模块二 · 财报分析 + 风险预警
按唐朝价值投资体系拆财报、建公司「事实编年」，并从造假案例反向蒸馏出预警特征。

- **知识库**
  - `knowledge/companies/<公司>/` — 公司**事实编年**（时间·主体·事件，只记客观事实，不写判断）。**唯一花名册 `companies/INDEX.md`**（公司全集 single source），监控子集 `_watchlist.md`（家数以表为准，勿写死）
  - `knowledge/造假案例库/<公司>/` — 63 个财务造假案例（中A股 54 + 美 6 + 日 2…）+ `造假模式库.md`
  - `report/` — 各案例/公司的**源文档**（年报 PDF、处罚决定书、做空报告等，约 1.3G，不入 git）；`report/daily/` 存每日日报
- **skill**
  - `company-analysis` — 财报数据提取→补进 `finance/` 估值库→刷新买卖点（强制「先提取再结论」，不编数据）
  - `daily-news` — 每日扫监控清单公司的新闻/公告，事实核验后追加进事实编年并出日报（见下「每日哨兵」）
  - `ingest-fraud-case` — 录入造假案例并蒸馏特征，增量喂养 `造假模式库.md`

### 模块三 · 公司客观分析 + 估值现算

把"公司客观长什么样"沉淀进库，估值/买卖点等主观决策现算不沉淀（2026-06-30 客观/主观分层改版）。

- **知识库**：`finance/<公司>/` — 公司客观分析三件套（`财务数据/<csv>` + `分析.md` + `财报关注要点.md`，canonical 客观数据）
- **skill**
  - `company-analysis` — 财报分析流程（从零建库 / 增量更新；产出三件套·客观层落盘）
  - ~~`valuation-method`~~ — **已删除**·待重新设计

---

## 目录结构

```
investor-analyzer/
├── knowledge/
│   ├── gurus/<slug>/          # 模块一：大V画像（INDEX.md 为花名册，_模板 为模板）
│   ├── companies/<公司>/      # 模块二：公司事实编年（INDEX.md + _watchlist.md + _模板）
│   └── 造假案例库/<公司>/      # 模块二：造假案例 + 造假模式库.md
├── finance/<公司>/            # 模块三：唐朝估值法估值库（canonical，_模板 为模板）
├── report/                    # 源文档（PDF/决定书，~1.3G 不入 git）+ report/daily/ 日报
├── scripts/
│   ├── quote.py               # 区间行情（A股/港股/指数，前复权可复现·原供 backtest-call）
│   ├── notices.py             # 巨潮(cninfo)一手公告拉取，给 daily-news
│   ├── fetch_fundamentals.py  # 近 10 年年报季报三表 CSV 下载（akshare），建分析事实底座
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
headless 跑 `daily-news` skill：拉一手公告 → 逐家核验 → 重大事件写进事实编年 → 产出 `report/daily/<日期>.md`。
日志在 `report/daily/_logs/`。手动测试：`bash scripts/daily-news.sh`。

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
- **职责不越界**：客观事实进 `companies/`，估值数字与个人判断（评级/能力圈/最高仓位/买卖点）进 `finance/<公司>/分析.md`，大V观点进 `gurus/`，三套花名册共用同一套中文公司名以防漂移
- **事实与判断分层**：`companies/` 只记发生了什么（零判断）；`finance/<公司>/分析.md` 记当前怎么看（财报来了会被 `company-analysis` 重刷）；`finance/<公司>/观点变更.md` 记看法怎么变（**只增不改**的历史，刷新 `分析.md` 时不动它，可回头算自己的胜率）。组合级（仓位加总/买入排队/成交流水）进入实盘阶段再建 `finance/组合/`
- **数据可信优先**：子代理抓老财报易出数字错误，入库前务必 QC（已知口径坑：归母 vs 扣非）

## 版本控制约定

仓库托管在 `opings/investor-analyzer`（private）。**只入库蒸馏后的成果与可复用逻辑，不入库源档、工作文件、机器专属配置。**
判断规则（已写进 `.gitignore`，新增内容前对照一下，别手滑把下面这些 `git add` 进来）：

| 入库 ✅ | 不入库 ❌（保留本地） |
|---|---|
| 蒸馏知识：`gurus/*/`（profile/current-view/style/calls/成品 `posts/*.md`）、`companies/*/`、`造假案例库/*/`（含决定书/SEC 源页 `.html`，作一手证据）、`finance/*/`（分析 `.md` + 估值 `.xlsx`） | **源文档**：`report/**` 的 PDF/年报/决定书等二进制（~1.3G）——只留蒸馏后的文本 |
| 可复用逻辑：`.claude/skills/`、`scripts/quote.py`、`scripts/notices.py`、`scripts/requirements.txt` | **ingest 工作/状态文件**：`*-DRAFT.md`、`READING_STATE.md`（跨会话阅读进度，本地 WIP） |
| 数据产出：`report/daily/` 日报 | **机器专属自动化**：`scripts/daily-news.sh`、`scripts/com.investor.daily-news.plist`（写死本机绝对路径，别人 clone 后需自行配 launchd） |
| | `scripts/.venv/`（用 `requirements.txt` 重建） |

**底线**：任何含本机绝对路径（`/Users/<用户名>/...`）或个人密钥的内容都不该入库——历史已审计为零泄露，保持下去。
新增大类文件前若拿不准，先 `git status` 看一眼会带进什么。
