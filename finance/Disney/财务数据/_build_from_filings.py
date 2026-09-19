#!/usr/bin/env python3
"""Disney 三表构建器：把 `_rfiles/`（FY2011-2025 的 SEC 渲染报表）与
`_legacy/`（FY1993-2010 的 10-K 文本/HTML 解析候选）合成
`利润表.csv` / `资产负债表.csv` / `现金流量表.csv`，勾稽不过不写出。

## 两条数据轨 + 一条锁定链

| 轨 | 覆盖 | 载体 | 归一方式 |
|---|---|---|---|
| R 轨 | FY2009-2025 | 各年 10-K 的 R*.htm | **按 XBRL tag** 归一（措辞改过多次，tag 稳） |
| Legacy 轨 | FY1993-2010 | 10-K 正文 txt / htm | 按标签正则归一 |

R 文件每份带 3 年利润表/现金流、2 年资产负债表，所以 FY2011 那份就把 FY2009-2010
的利润表捎回来了。Legacy 轨同理层层重叠 —— 由此得到**倒锁链**：

    已可信年份(R 轨 seed) ──► 用它去核 legacy 候选表的重叠年
                              ──► 对得上才采纳该表带来的更早年份 ──► 继续往回

🔴 **为什么非这么做不可**：Disney 老 10-K 里「CONSOLIDATED STATEMENTS OF INCOME」
这串字出现 6-8 次（目录、附注、pro forma、分部表、并购对价表都含它）。纯靠标签锚点
打分挑表**实证会挑错**：FY2010 挑中并购对价的 Estimated Fair Value 表、
FY2000 挑中 pro forma 五年表、FY1997 挑中分部季度表。拿已知值去对，才挑得准。

## 口径声明（取数当场固定，事后查不出来）

- **期间**：全部为**财年全年**（12 Months Ended）。R 文件 FY2012/FY2013 的利润表
  把 8 个季度列与 3 个年度列混排，靠 `months==12` 过滤，不靠列位置猜。
- **主体**：合并口径；归母 = `NetIncomeLoss`（Net income attributable to Disney）。
- **来源年份**：每个财年取**该财年自己那份 10-K 的当年列**（as-reported），
  不用后一年年报的比较列覆盖；比较列另存 `重述与口径变更.csv` 供追溯。
- **单位**：百万美元。⚠️ FY1993-FY1997 印刷口径保留一位小数，本库按原样保留。
"""
import csv
import json
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RDIR = os.path.join(HERE, "_rfiles")
LDIR = os.path.join(HERE, "_legacy")

# ── 概念定义 ────────────────────────────────────────────────────────────────
# (CSV 行名, [R 轨 XBRL tag], [Legacy 轨标签正则])  —— 顺序即 CSV 行序
IS_CONCEPTS = [
    ("营业收入 Revenues",
     ["us-gaap_Revenues", "us-gaap_SalesRevenueNet",
      "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax"],
     [r"^revenues?$", r"^revenues?\s*合计$", r"^total revenues$"]),
    ("  服务收入 Service revenues", ["DIM:Service:us-gaap_Revenues"], []),
    ("  产品收入 Product revenues", ["DIM:Product:us-gaap_Revenues"], []),
    ("总成本及费用 Total costs and expenses",
     ["us-gaap_CostsAndExpenses"],
     [r"^costs? and expenses$", r"^costs? and expenses\s*合计$"]),
    ("  服务成本 Cost of services", ["DIM:Service:us-gaap_CostOfGoodsAndServicesSold"], []),
    ("  产品成本 Cost of products", ["DIM:Product:us-gaap_CostOfGoodsAndServicesSold"], []),
    ("  销售及管理费用 SG&A", ["us-gaap_SellingGeneralAndAdministrativeExpense"], []),
    ("  折旧与摊销 D&A", ["us-gaap_DepreciationDepletionAndAmortization"], []),
    ("重组及减值 Restructuring and impairment",
     ["us-gaap_RestructuringSettlementAndImpairmentProvisions",
      "us-gaap_RestructuringCharges"],
     [r"restructuring and impairment", r"^restructuring charges$"]),
    ("出售业务收益 Gain on sale of businesses", [],
     [r"gains? on sale.*(business|equity investment)", r"gains? on sales of equity"]),
    ("其他收入(支出)净额 Other income (expense), net",
     ["us-gaap_NonoperatingIncomeExpense"],
     [r"^other \(?(income|expense)\)?\s*/?\s*\(?(income|expense)?\)?$"]),
    # ⚠️ FY1993-FY1995 的利润表**没有「净利息」这条线**：它把 G&A / 利息支出 / 投资与利息收入
    #    三项并列在「Corporate Activities」段下、各自印正数。把其中的「Interest expense」
    #    当成「净利息费用」会既错口径又错符号，故那三年单列下面两行、净利息留空。
    ("利息支出净额 Interest expense, net",
     ["us-gaap_InterestIncomeExpenseNonoperatingNet", "us-gaap_InterestExpense"],
     [r"^net interest expense"]),
    ("  利息支出(毛·仅FY1993-96) Interest expense", [], [r"^interest expense$"]),
    ("  投资与利息收入(仅FY1993-96) Investment and interest income", [],
     [r"^investment and interest income$"]),
    ("权益法投资收益 Equity in income of investees",
     ["us-gaap_IncomeLossFromEquityMethodInvestments"],
     [r"equity in the (income|loss) of investees"]),
    # FY1997 印的是「Income before taxes」（没有 income 二字）→ 正则要放宽，否则那年税前为空
    ("税前利润 Income before income taxes",
     ["us-gaap_IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
      "us-gaap_IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
     [r"^income (from continuing operations )?before (income )?taxes"]),
    ("所得税 Income taxes",
     ["us-gaap_IncomeTaxExpenseBenefit"],
     [r"^income taxes$"]),
    ("终止经营损益 Discontinued operations, net of tax",
     ["us-gaap_IncomeLossFromDiscontinuedOperationsNetOfTax"],
     [r"^discontinued operations, net of tax$"]),
    # ⚠️ 会计变更累积影响在 FY1993 被拆成 3 个子行（开办费 / 退休后福利 / 所得税），
    #    逐行去捞只会捞到其中一条。改为**从「会计变更前利润」与「归母净利」反推总额**。
    ("会计变更前利润 Income before cumulative effect", [],
     [r"^income before (the )?cumulative effect"]),
    # ⚠️ 只认**税后**的「cumulative effect」。FY1996 利润表里的「Accounting change (300)」
    #    位置在**营业利润之上**（已含在税前利润 2,061 内），若一并当税后项再减一次
    #    会让利润链凭空差 300 —— 这不是解析错，是同名不同位。
    ("会计变更累积影响 Cumulative effect of accounting changes", [],
     [r"^cumulative effect of accounting changes?$"]),
    # 30 年里这一行印过：Net income / NET INCOME / Net income (loss) / **Net (loss) income**
    # （FY2001 是亏损年，括号在前）。只认 `^net income$` 会让 FY2001 整张利润表失去核心科目，
    # 转而被一张 pro forma 表（营收 25,256 而非真值 25,269）顶替。
    ("净利润 Net income", ["us-gaap_ProfitLoss"],
     [r"^net \(loss\) income$", r"^net income \(loss\)$", r"^net (income|loss)$"]),
    # ⚠️ 两个 NCI tag 含义不同：NetIncomeLossAttributableToNoncontrollingInterest 是**总额**，
    #    IncomeLossFromContinuingOperations…NoncontrollingEntity 只是**持续经营部分**。
    #    FY2019 两者差 58（终止经营那部分的少数股东损益）→ 总额必须排在前面。
    ("少数股东损益 Noncontrolling interests",
     ["us-gaap_NetIncomeLossAttributableToNoncontrollingInterest",
      "us-gaap_IncomeLossFromContinuingOperationsAttributableToNoncontrollingEntity"],
     [r"^minority interests$", r"net income attributable to noncontrolling"]),
    # 标签在 FY2010/FY2011 是「…attributable to **The Walt Disney Company**」，
    # FY2012 起才简写成「…attributable to Disney」——两种都要认。
    ("归母净利 Net income attributable to Disney",
     ["us-gaap_NetIncomeLoss"],
     [r"net income attributable to (the walt )?disney"]),
    ("摊薄EPS Diluted EPS", ["us-gaap_EarningsPerShareDiluted"], []),
    ("摊薄股数(百万) Diluted shares",
     ["us-gaap_WeightedAverageNumberOfDilutedSharesOutstanding"], []),
]

BS_CONCEPTS = [
    ("货币资金 Cash and cash equivalents", ["us-gaap_CashAndCashEquivalentsAtCarryingValue"],
     [r"^cash and cash equivalents$"]),
    ("应收账款 Receivables", ["us-gaap_ReceivablesNetCurrent", "us-gaap_AccountsReceivableNetCurrent"],
     [r"^receivables$", r"^receivables, net$"]),
    ("存货 Inventories", ["us-gaap_InventoryNet"], [r"^inventories$", r"^merchandise inventories$"]),
    # 「垃圾筐」科目（规则 Step 3.0 第 6 条要对的那几个）：假利润找不到现金归宿时常藏这里
    ("其他流动资产 Other current assets", ["us-gaap_OtherAssetsCurrent"],
     [r"^other current assets$"]),
    ("流动资产合计 Total current assets", ["us-gaap_AssetsCurrent"], [r"^total current assets$"]),
    ("影视内容成本 Produced and licensed content costs",
     ["dis_ProducedAndLicensedContentCosts", "dis_ProducedAndLicensedContentCostsNoncurrent",
      "us-gaap_FilmAndTelevisionCosts", "dis_FilmAndTelevisionCosts",
      "LBL:^produced and licensed content costs$"],
     [r"^film and television costs$", r"produced and licensed content"]),
    # PPE 明细：`在建工程(Projects in progress)`是 `财报关注要点-行业模板` 明示的藏雷点
    #（长期挂账不转固 = 推迟折旧/虚增资产），Disney 在 PPE 内单列，故一并落库。
    # FY2024/2025 把原值行改成公司自定义 tag（dis_ParksResortsAndOtherPropertyGross…），
    # 只认 us-gaap_PropertyPlantAndEquipmentGross 会让最近两年这一行为空。
    ("  房产设备原值 Attractions, buildings and equipment",
     ["us-gaap_PropertyPlantAndEquipmentGross",
      "dis_ParksResortsAndOtherPropertyGrossExcludingProjectsAndLand",
      "LBL:^attractions, buildings and equipment$"],
     [r"^attractions, buildings and equipment$"]),
    ("  累计折旧 Accumulated depreciation",
     ["us-gaap_AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment"],
     [r"^accumulated depreciation$"]),
    ("  在建工程 Projects in progress",
     ["us-gaap_ConstructionInProgressGross"], [r"^projects in progress$"]),
    ("  土地 Land", ["us-gaap_Land"], [r"^land$"]),
    ("固定资产净额 Parks, resorts and other property, net",
     ["us-gaap_PropertyPlantAndEquipmentNet"], []),
    ("商誉 Goodwill", ["us-gaap_Goodwill"], [r"^goodwill$"]),
    ("无形资产 Intangible assets, net",
     ["us-gaap_IntangibleAssetsNetExcludingGoodwill", "us-gaap_FiniteLivedIntangibleAssetsNet"],
     [r"^intangible assets, net$"]),
    ("其他非流动资产 Other assets", ["us-gaap_OtherAssetsNoncurrent"], [r"^other assets$"]),
    ("资产总计 Total assets", ["us-gaap_Assets"], [r"^total assets$"]),
    ("流动负债合计 Total current liabilities", ["us-gaap_LiabilitiesCurrent"],
     [r"^total current liabilities$"]),
    ("递延收入 Deferred revenue", ["us-gaap_DeferredRevenueCurrent", "us-gaap_ContractWithCustomerLiabilityCurrent"],
     [r"^deferred revenue", r"unearned royalt"]),
    ("短期借款 Borrowings current", ["us-gaap_LongTermDebtCurrent", "us-gaap_DebtCurrent"],
     [r"current portion of borrowings"]),
    ("长期借款 Borrowings long-term", ["us-gaap_LongTermDebtNoncurrent"],
     [r"^borrowings$", r"^long-?term borrowings$"]),
    ("负债合计 Total liabilities", ["us-gaap_Liabilities"], [r"^total liabilities$"]),
    ("归母权益 Total Disney shareholders' equity",
     ["us-gaap_StockholdersEquity"], [r"total disney shareholders.? equity"]),
    ("少数股东权益 Noncontrolling interests",
     ["us-gaap_MinorityInterest"], [r"^noncontrolling interests$"]),
    ("权益合计 Total equity",
     ["us-gaap_StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
     [r"^total equity$"]),
    ("负债与权益总计 Total liabilities and equity",
     ["us-gaap_LiabilitiesAndStockholdersEquity"], [r"^total liabilities and equity$"]),
]

CF_CONCEPTS = [
    ("经营活动现金流净额 Cash provided by operations",
     ["us-gaap_NetCashProvidedByUsedInOperatingActivities",
      "us-gaap_NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
     [r"cash provided by operations$", r"cash provided by continuing operations"]),
    ("  折旧摊销 Depreciation and amortization",
     ["us-gaap_DepreciationDepletionAndAmortization", "us-gaap_DepreciationAmortizationAndAccretionNet"],
     [r"^depreciation and amortization$"]),
    ("资本开支 Investments in parks, resorts and other property",
     ["us-gaap_PaymentsToAcquirePropertyPlantAndEquipment"],
     [r"investments in parks, resorts", r"investments in theme parks"]),
    # ⚠️ 小计行的措辞 30 年里换过多种：「Cash used in / used by / (used) provided by
    #    investing activities」，老年份还可能是**无标签小计**（合成成「… 合计」）。
    #    按 cash 后面的词去匹配会漏（FY2000 是 "used by"），改成按**行尾**匹配。
    ("投资活动现金流净额 Cash used in investing activities",
     ["us-gaap_NetCashProvidedByUsedInInvestingActivities",
      "us-gaap_NetCashProvidedByUsedInInvestingActivitiesContinuingOperations"],
     [r"investing activities(\s*合计)?$"]),
    ("分红支付 Dividends", ["us-gaap_PaymentsOfDividends", "us-gaap_PaymentsOfDividendsCommonStock"],
     [r"^dividends$", r"^commercial paper.*dividends$"]),
    ("回购股份 Repurchases of common stock",
     ["us-gaap_PaymentsForRepurchaseOfCommonStock"], [r"repurchases of common stock"]),
    ("融资活动现金流净额 Cash provided by (used in) financing activities",
     ["us-gaap_NetCashProvidedByUsedInFinancingActivities",
      "us-gaap_NetCashProvidedByUsedInFinancingActivitiesContinuingOperations"],
     [r"financing activities(\s*合计)?$"]),
    # FY2019 起（福克斯交易）现金流量表多出**独立的终止经营段**（经营 622 + 投资 10,978
    # + 融资 −626 = 10,974）。不单列它，「经营+投资+融资+汇率=净变动」会差整整 10,974。
    ("终止经营现金流 Cash from discontinued operations",
     ["us-gaap_NetCashProvidedByUsedInDiscontinuedOperations"],
     [r"cash (used in|provided by) discontinued operations"]),
    # FY2006-FY2008 的列报把终止经营现金流**分三行**列、没有合计行
    # （FY2007：经营 23 + 投资 −3 + 融资 78 = 98）→ 单列后在勾稽里相加。
    ("  终止经营-经营 Discontinued ops operating", [],
     [r"operating activities of discontinued operations"]),
    ("  终止经营-投资 Discontinued ops investing", [],
     [r"investing activities of discontinued operations"]),
    ("  终止经营-融资 Discontinued ops financing", [],
     [r"financing activities of discontinued operations"]),
    ("汇率对现金影响 Impact of exchange rates on cash",
     ["us-gaap_EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations",
      "us-gaap_EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
      "us-gaap_EffectOfExchangeRateOnCashAndCashEquivalents",
      "us-gaap_EffectOfExchangeRateOnCashAndCashEquivalentsContinuingOperations"],
     [r"impact of exchange rates on cash", r"effect of exchange rate"]),
    ("现金净变动 Change in cash and cash equivalents",
     ["us-gaap_CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
      "us-gaap_CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseExcludingExchangeRateEffect",
      "us-gaap_CashAndCashEquivalentsPeriodIncreaseDecrease"],
     [r"(increase|decrease) in cash and cash equivalents"]),
    # ⚠️ 期初/期末现金在 R 文件里**共用同一个 tag**（us-gaap_CashCashEquivalents…），
    #    只能靠 label 区分 → 用 LBL: 前缀走标签匹配。
    # FY2004 采用 FIN 46R 首次并表欧洲迪士尼/香港迪士尼，带入现金 274 单列在净变动之后；
    # 不认这一行，「期初+净变动=期末」会差 274。
    ("初次并表带入现金 Cash from initial consolidation", [],
     [r"due to the initial consolidation"]),
    ("期初现金 Cash at beginning of year", ["LBL:beginning of (the )?year"],
     [r"beginning of (the )?year"]),
    ("期末现金 Cash at end of year", ["LBL:end of (the )?year"], [r"end of (the )?year"]),
]

CONCEPTS = {"IS": IS_CONCEPTS, "BS": BS_CONCEPTS, "CF": CF_CONCEPTS}


# ── R 轨 ────────────────────────────────────────────────────────────────────
def fy_of_period(p):
    """'Sep. 27, 2025' → 2025。Disney 财年末恒在 9 月末/10 月初，故 = 日期的年份。"""
    m = re.search(r"\b((?:19|20)\d\d)\b", p)
    return int(m.group(1)) if m else None


def load_r():
    """→ {(filing_key, kind): {fy: {concept: val}}}。保留 filing **与报表** 两个维度：
    · filing 维度 —— 区分「该财年自己那份 10-K」(as-reported) 与「后续年报比较列」(可能已重述)
    · kind 维度   —— 保证一个财年的一张表整张来自同一份年报，见 resolve() 的说明
    """
    out = {}
    for f in sorted(os.listdir(RDIR)):
        if not f.endswith(".json"):
            continue
        d = json.load(open(os.path.join(RDIR, f)))
        key = int(d["key"])
        for kind in ("IS", "BS", "CF"):
            per_filing = defaultdict(dict)
            st = d["statements"].get(kind)
            if not st:
                continue
            periods, months = st["periods"], st.get("months") or []
            # 选列：利润表/现金流只要 12 个月列；资产负债表是时点，全要
            idxs = []
            for i, p in enumerate(periods):
                if kind in ("IS", "CF") and months and months[i] != 12:
                    continue
                idxs.append(i)
            # 同一财年可能有多列（FY2012 里 Q4 与全年同为 Sep.29,2012）→ 12 个月过滤后应唯一
            seen = {}
            for i in idxs:
                fy = fy_of_period(periods[i])
                if fy is not None:
                    seen[fy] = i          # 若仍重复，后出现的（年度列在后）胜出
            dim = ""
            for r in st["rows"]:
                tag, lab = r["tag"], r["label"]
                if tag in ("srt_ProductOrServiceAxis", "us-gaap_StatementClassOfStockAxis"):
                    dim = lab             # 维度分段开始（Service / Product）
                    continue
                for name, tags, _ in CONCEPTS[kind]:
                    hit = False
                    for t in tags:
                        if t.startswith("DIM:"):
                            _, want_dim, want_tag = t.split(":", 2)
                            hit = (dim == want_dim and tag == want_tag)
                        elif t.startswith("LBL:"):
                            hit = (not dim and re.search(t[4:], lab, re.I) is not None)
                        else:
                            hit = (tag == t and not dim)
                        if hit:
                            break
                    if not hit:
                        continue
                    for fy, i in seen.items():
                        v = r["vals"][i] if i < len(r["vals"]) else None
                        if v is not None and name not in per_filing[fy]:
                            per_filing[fy][name] = v
                    break
            out[(key, kind)] = dict(per_filing)
    return out


# ── Legacy 轨 ───────────────────────────────────────────────────────────────
def legacy_rows_to_facts(cand, kind):
    """一张候选表 → {fy: {concept: val}}。

    列对齐纪律：只接受 `len(vals) == len(periods)`，或多出来时取**末 N 个**
    （老文本行首偶尔混入「575.4 million shares」这类嵌在标签里的数）。
    其余一律跳过 —— **不猜**，反正错了也会被后面的重叠年核对打掉。
    """
    periods = [int(y) for y in cand["periods"] if y.isdigit()]
    # 🔴 真报表的比较期最多 3 年（资产负债表 2 年）。期间数超了的是
    #    「Selected Financial Data 五年摘要」或 pro forma 表 —— 它们也含
    #    「Cash provided by operations」这类行，会被误当成现金流量表选中，
    #    而且因为覆盖 5 个年份，在 resolve 里还会**压过真报表**去供给更早的年份。
    #    （实证：FY1993/95/97/99 的现金流一度全被五年摘要表顶掉，只剩 3 个科目。）
    if not periods or len(periods) > MAXP[kind]:
        return {}
    n = len(periods)
    facts = defaultdict(dict)
    for r in cand["rows"]:
        # ⚠️ label 与 full 必须**分别**匹配：拼成一个串后 `^…$` 锚点永远落空
        #    （"revenues | revenues" 匹配不上 `^revenues?$`）——这个 bug 曾让
        #    legacy 轨的营收/净利/总资产整片为空，而现金流因用的是非锚定正则照常通过，
        #    所以只从「某几行没出来」看不出是正则写法坏了。
        texts = [r["label"].lower(), (r.get("full") or "").lower()]
        vals = r["vals"]
        if len(vals) > n:
            vals = vals[-n:]
        elif len(vals) != n:
            continue
        # 🔴 小计行优先匹配「净额/合计」类概念。
        #    实证：FY1997 投资活动的小计行 label 是折行标签
        #    「Investments in theme parks, resorts and othe…」、full 才是
        #    「INVESTING ACTIVITIES 合计」。概念按声明顺序匹配时，**资本开支**
        #    （正则含 `investments in theme parks`）会先把它吃掉，
        #    投资活动净额于是整年为空，下游只好去借后一年的比较列。
        is_total = any(t.strip().endswith("合计") for t in texts)
        ordered = CONCEPTS[kind]
        if is_total:
            tot = [c for c in ordered if any(k in c[0] for k in ("净额", "合计", "总计"))]
            ordered = tot + [c for c in ordered if c not in tot]
        for name, _, pats in ordered:
            if not pats or not any(re.search(p, t) for p in pats for t in texts):
                continue
            for fy, v in zip(periods, vals):
                if v is not None and name not in facts[fy]:
                    facts[fy][name] = v
            break
    return dict(facts)


# 各报表允许的最大比较期数（超出即判为五年摘要/pro forma，不是真报表）
MAXP = {"IS": 3, "BS": 2, "CF": 3}

# 「这张表算不算解析出来了」的核心科目：齐了才认它是 as-reported 的合格来源
CORE = {
    "IS": ["营业收入 Revenues", "净利润 Net income"],
    "BS": ["资产总计 Total assets", "负债与权益总计 Total liabilities and equity"],
    "CF": ["经营活动现金流净额 Cash provided by operations",
           "投资活动现金流净额 Cash used in investing activities",
           "融资活动现金流净额 Cash provided by (used in) financing activities"],
}

ANCHOR_CONCEPTS = {
    "IS": ["营业收入 Revenues", "净利润 Net income", "归母净利 Net income attributable to Disney"],
    "BS": ["资产总计 Total assets", "货币资金 Cash and cash equivalents"],
    "CF": ["经营活动现金流净额 Cash provided by operations",
           "资本开支 Investments in parks, resorts and other property"],
}


def close(a, b):
    """老申报保留一位小数、新申报取整，容差按量级给。"""
    if a is None or b is None:
        return False
    return abs(abs(a) - abs(b)) <= max(1.0, abs(b) * 0.005)


def pick_candidate(cands, kind, trusted):
    """用已可信值去对候选表的重叠年，挑出最像「那张表」的候选。

    🔴 **「对不上」不等于「解析错」**：同一年在自己年报与后续年报里本来就可能不同
    （Disney FY2005 营收 as-reported 31,944 → FY2007 年报重述为 31,374；
      FY2000 经营现金流 6,434 → FY2001 采用 SOP 00-2 后重述为 3,755，差 42%）。
    若把任何不一致都当冲突，**as-reported 的正确表反而会被否掉**，
    下游只好去借后续年报的比较列 —— 那正好把「as-reported 优先」这条口径废掉。

    所以只把**量级级别的差异**（比值在 0.4~2.5 之外）当作「挑错了表」的信号，
    介于其间的差异当作重述、不计冲突；细粒度的正确性交给下游 132 条勾稽与分部闸门。
    """
    best, best_key = None, (-1, -1, 1, -1)
    for c in cands:
        facts = legacy_rows_to_facts(c, kind)
        hit = miss = 0
        for fy, kv in facts.items():
            for name in ANCHOR_CONCEPTS[kind]:
                t, v = trusted.get(fy, {}).get(name), kv.get(name)
                if t is None or v is None or t == 0:
                    continue
                if close(v, t):
                    hit += 1
                elif abs(t) >= 500 and not (0.4 <= abs(v) / abs(t) <= 2.5):
                    # ⚠️ 绝对值小的科目不做比值判定：FY2001 净利 as-reported 与重述值
                    #    都只有几十到一百多（百万美元），比值天然不稳，
                    #    照判会把**真的利润表**当成挑错表否掉（实证：FY2001 因此退回借用）。
                    miss += 1
        # 🔴 排序键的次序很要紧：**先看核心科目齐不齐，再看重叠年命中多少**。
        #    反过来排会挑中「锚点碰巧多对上几个、却缺净利润/三条现金流线」的残表，
        #    逼得下游去借后一年的比较列（实证：一度让 FY2005/06/08/09 的利润表
        #    和 FY1995-99 的现金流表全部退回借用）。
        #    `hit>0 且 miss==0` 是硬门槛，在门槛之内按完整度优先是安全的。
        core = sum(1 for cc in CORE[kind] if any(cc in kv for kv in facts.values()))
        key = (core, hit, -miss, len(facts))
        if facts and miss == 0 and key > best_key:
            best, best_key = (c, facts, hit, miss), key
    if best:
        return best
    # 全部候选都有量级级冲突（极少见）→ 退回行数最多的那张，并在日志里标出待人核
    for c in cands:
        facts = legacy_rows_to_facts(c, kind)
        if facts:
            return (c, facts, 0, -1)
    return None


def bs_structural(cand):
    """资产负债表的三个合计**靠结构定位，不靠标签**。

    🔴 Disney 的资产负债表（1993-2010 全era）**没有「Total assets」这一行** ——
       合计是无标签行，我的解析器只能按最近段首合成出「…合计」这种名字
       （FY2005 实证：总资产 53,158 被命名成「Parks, resorts and other property, at cost 合计」）。
       靠标签正则去捞，捞到的会是别的小计。

    定位规则（三条同时成立才采信）：
      · 「负债与权益」段的起点 = 第一行 full 含 "liabilities and"（段首被拼进了 full）
      · 资产总计   = 该起点**之前**最后一个合计行
      · 负债与权益总计 = 全表**最后**一个合计行
      · 归母权益   = 最后一个合计行**之前**的那个合计行
    闸门：资产总计 必须等于 负债与权益总计，否则整张表判废（返回空）。
    """
    rows = cand["rows"]
    periods = [int(y) for y in cand["periods"] if y.isdigit()]
    if not periods or not rows:
        return {}
    n = len(periods)

    def is_total(r):
        return r["label"].endswith("合计") or r["label"] == "(无标签小计)"

    iliab = None
    for i, r in enumerate(rows):
        if "liabilities and" in (r.get("full") or "").lower():
            iliab = i
            break
    tot_idx = [i for i, r in enumerate(rows) if is_total(r) and len(r["vals"]) == n]
    if not tot_idx:
        return {}
    ta_i = max([i for i in tot_idx if iliab is None or i < iliab], default=None)
    tle_i = tot_idx[-1]
    eq_i = max([i for i in tot_idx if i < tle_i], default=None)
    if ta_i is None or ta_i == tle_i:
        return {}
    ta, tle = rows[ta_i]["vals"], rows[tle_i]["vals"]
    if not all(close(a, b) for a, b in zip(ta, tle) if a is not None and b is not None):
        return {}                      # 资产 ≠ 负债+权益 → 表选错了，判废
    out = defaultdict(dict)
    for j, fy in enumerate(periods):
        if ta[j] is not None:
            out[fy]["资产总计 Total assets"] = ta[j]
            out[fy]["负债与权益总计 Total liabilities and equity"] = tle[j]
        if eq_i is not None and eq_i != ta_i and rows[eq_i]["vals"][j] is not None:
            out[fy]["归母权益 Total Disney shareholders' equity"] = rows[eq_i]["vals"][j]
    return dict(out)


def load_legacy(trusted):
    """从 FY2010 往回走，逐年用重叠年锁定候选表。

    → ({(src_fy, kind): {data_fy: {concept: val}}}, 日志)
    **保留 src_fy 维度**：同一个财年会出现在自己那份 10-K 和后面 1-2 份的比较列里，
    两者可能不同（重述）。合成时才按 as-reported 优先级定夺，这里不提前合并。
    """
    got, log = {}, []
    for fy in range(2010, 1992, -1):
        p = os.path.join(LDIR, f"{fy}.json")
        if not os.path.exists(p):
            continue
        d = json.load(open(p))
        for kind in ("IS", "BS", "CF"):
            cands = d["statements"].get(kind) or []
            picked = pick_candidate(cands, kind, trusted)
            if not picked:
                log.append(f"FY{fy} {kind}: ❌ 无可用候选（{len(cands)} 张）")
                continue
            c, facts, hit, miss = picked
            if kind == "BS":
                for y, kv in bs_structural(c).items():
                    facts.setdefault(y, {}).update(kv)
            log.append(f"FY{fy} {kind}: 选中 {len(c['rows'])}行/s{c['score']} "
                       f"期间{c['periods']} 重叠核对 命中{hit} 冲突{miss}"
                       + ("  ⚠️无重叠可核" if hit == 0 else ""))
            got[(fy, kind)] = facts
            for y, kv in facts.items():
                for name, v in kv.items():
                    trusted.setdefault(y, {}).setdefault(name, v)
    return got, log


# ── 合成：as-reported 优先 + 重述留痕 ──────────────────────────────────────
def resolve(sources):
    """sources = {(src_fy, kind): {data_fy: {concept: val}}}

    🔴 **按「财年 × 报表」整张定源，不逐科目东拼西凑。**

    为什么：逐科目补缺会把**两种列报混进同一年**。实证——FY2005 自己那份 10-K 的
    利润表没有「终止经营」这一行（那是 FY2007 年报追溯重分类后才出现的），
    逐科目补缺就把 FY2007 口径的 109 塞进了 FY2005 的 as-reported 利润表，
    于是「税前+税+少数股东+会计变更 = 归母」这条链差 109 —— 而**每个数字本身都是真的**。

    定源规则：候选 = 覆盖该 (财年, 报表) 的全部年报。
      ① 先只看**齐核心科目**的候选，其中取 gap 最小者 —— 即该财年自己那份优先（as-reported）；
      ② 若无候选齐核心科目，才退到覆盖数最多者，并记进「非 as-reported」清单如实交代。
      同一概念各源不一致 → 记 restate。
    """
    by = defaultdict(list)                        # (data_fy, kind) -> [(gap, src_fy, kv)]
    for (src_fy, kind), data in sources.items():
        for data_fy, kv in data.items():
            if kv:
                by[(data_fy, kind)].append((abs(src_fy - data_fy), src_fy, kv))
    final, restate, picks = defaultdict(dict), [], []
    for (fy, kind), lst in sorted(by.items()):
        full = [x for x in lst if all(c in x[2] for c in CORE[kind])]
        if full:
            full.sort(key=lambda x: (x[0], x[1]))
        else:
            lst.sort(key=lambda x: (-len(x[2]), x[0], x[1]))
        gap, src_fy, kv = (full or lst)[0]
        picks.append((fy, kind, src_fy, len(kv), gap != 0))
        for name, v in kv.items():
            final[fy][name] = v
            final[fy].setdefault("_src", {})[name] = src_fy
        for g2, s2, kv2 in lst[1:]:
            for name, v in kv2.items():
                if name in kv and not close(v, kv[name]):
                    restate.append((fy, name, kv[name], src_fy, v, s2))
    return dict(final), restate, picks


# 定义上恒为减项的科目：各年印刷时正负不一（FY1993-95/FY2000 印正数、FY2019 的分产品
# 成本也印正数），不归一会让同一行在时间轴上符号跳变，做比率时静默出错。
ALWAYS_NEGATIVE = [
    "总成本及费用 Total costs and expenses",
    "  服务成本 Cost of services",
    "  产品成本 Cost of products",
    "  销售及管理费用 SG&A",
    "  折旧与摊销 D&A",
    "  利息支出(毛·仅FY1993-96) Interest expense",
    "资本开支 Investments in parks, resorts and other property",
]


def normalize(final):
    """符号 / 口径归一。

    ① **所得税与少数股东损益的符号跨 era 不一致**：R 轨（FY2011+）印的是括号负数，
       老申报（FY1993-2010）印的是正数减项。不归一的话「税前+所得税=净利」
       这条勾稽会在 era 交界处整片失败，而**每一边各自都是自洽的**——
       所以不能靠勾稽发现，只能显式判。做法：两种符号都试，取能让恒等式成立的那个。
    ② **FY2008 以前 Disney 没有「归母净利」这一行**（少数股东损益已在净利之上扣除），
       此时 归母 = 净利，并记一条口径说明，而不是留空。
    """
    notes = []
    for fy, kv in final.items():
        net = kv.get("净利润 Net income")
        att = kv.get("归母净利 Net income attributable to Disney")
        kv["_era"] = "B" if (net is not None and att is not None and not close(net, att)) else "A"
        # 会计变更累积影响：有「会计变更前利润」就用它与净利反推总额（子行拆分不可靠）
        bce = kv.get("会计变更前利润 Income before cumulative effect")
        if bce is not None and net is not None and not close(bce, net):
            kv["会计变更累积影响 Cumulative effect of accounting changes"] = net - bce
        if att is None and net is not None:
            kv["归母净利 Net income attributable to Disney"] = att = net
            notes.append(f"FY{fy} 归母净利 = 报表「Net income」行（该年利润表无单独归母行，"
                         f"少数股东损益在净利之上扣除 = era A 列报）")
        # 🔴 少数股东损益在 era B 从**两个已确立的合计反推**，不从 tag 取。
        #    原因：FY2019 起 Disney 把 NCI 拆成「持续经营 −472」+「终止经营 58」两行，
        #    任取一行都不是总额（差 58）；而 归母 − 净利 = −530 是精确的。
        if kv["_era"] == "B":
            kv["少数股东损益 Noncontrolling interests"] = att - net
        else:
            nci = kv.get("少数股东损益 Noncontrolling interests")
            pre = kv.get("税前利润 Income before income taxes")
            if None not in (nci, pre, att):
                others = sum(x for k, x in kv.items()
                             if k in ("所得税 Income taxes",
                                      "终止经营损益 Discontinued operations, net of tax",
                                      "会计变更累积影响 Cumulative effect of accounting changes")
                             and isinstance(x, (int, float)))
                if close(pre + others - abs(nci), att):
                    kv["少数股东损益 Noncontrolling interests"] = -abs(nci)
        # 所得税符号归一：老申报印正数减项，R 轨印括号负数；两边**各自自洽**，
        # 所以跨 era 拼起来时不能靠勾稽发现，必须显式判。
        pre = kv.get("税前利润 Income before income taxes")
        tax = kv.get("所得税 Income taxes")
        target = net if kv["_era"] == "B" else att
        if None not in (pre, tax, target):
            others = sum(x for k, x in kv.items()
                         if k in (["终止经营损益 Discontinued operations, net of tax",
                                   "会计变更累积影响 Cumulative effect of accounting changes"]
                                  + ([] if kv["_era"] == "B"
                                     else ["少数股东损益 Noncontrolling interests"]))
                         and isinstance(x, (int, float)))
            if not close(pre + others + tax, target) and close(pre + others - abs(tax), target):
                kv["所得税 Income taxes"] = -abs(tax)
        for k in ALWAYS_NEGATIVE:
            if isinstance(kv.get(k), (int, float)) and kv[k] > 0:
                kv[k] = -kv[k]
        # FY1993-FY1996 没有「净利息」这条线，只有并列的利息支出与投资收益，且**都印正数**
        # （投资收益在 Corporate Activities 段里以括号表示「冲减费用」，解析成了负数）。
        # 归一成「支出为负、收入为正」后相加得净额 —— 结果与次年年报的比较列逐年吻合
        # （FY1995: −178.3+68 = −110.3 vs FY1997 年报印 −110；FY1996: −479+41 = −438 vs 印 −438）。
        ie = kv.get("  利息支出(毛·仅FY1993-96) Interest expense")
        ii = kv.get("  投资与利息收入(仅FY1993-96) Investment and interest income")
        if ii is not None and ii < 0:
            kv["  投资与利息收入(仅FY1993-96) Investment and interest income"] = ii = -ii
        if kv.get("利息支出净额 Interest expense, net") is None and None not in (ie, ii):
            kv["利息支出净额 Interest expense, net"] = ie + ii
            notes.append(f"FY{fy} 利息支出净额 = 利息支出 + 投资与利息收入（该年利润表"
                         f"无净额行，两项并列在 Corporate Activities 段下）")

    # FY2016 及以前，现金流量表的「期末现金」与资产负债表「货币资金」是同一个口径，
    # 可以互补缺口。FY2017 起 Disney 按 ASU 2016-18 把**受限现金**并入现金流量表口径
    # （FY2017 期末 4,064 vs 资产负债表 4,017），两者不再相等 → 这条填充只用到 2016。
    for fy, kv in final.items():
        if fy <= 2016 and kv.get("期末现金 Cash at end of year") is None \
                and kv.get("货币资金 Cash and cash equivalents") is not None:
            kv["期末现金 Cash at end of year"] = kv["货币资金 Cash and cash equivalents"]
            notes.append(f"FY{fy} 期末现金 ← 资产负债表货币资金（该年现金流量表未解析出此行；"
                         f"FY2016 及以前两者同口径）")

    # 现金链补齐：期末现金(FY_N) 恒等于 期初现金(FY_N+1) —— 用这条把两端的缺口互补，
    # 再由「期末−期初−初次并表」反推缺失的净变动，让那条勾稽由「数据不全」变成真检验。
    for fy in sorted(final):
        cur, nxt = final[fy], final.get(fy + 1)
        if nxt is not None:
            if cur.get("期末现金 Cash at end of year") is None \
                    and nxt.get("期初现金 Cash at beginning of year") is not None:
                cur["期末现金 Cash at end of year"] = nxt["期初现金 Cash at beginning of year"]
            if nxt.get("期初现金 Cash at beginning of year") is None \
                    and cur.get("期末现金 Cash at end of year") is not None:
                nxt["期初现金 Cash at beginning of year"] = cur["期末现金 Cash at end of year"]
    for fy, kv in final.items():
        b, e = kv.get("期初现金 Cash at beginning of year"), kv.get("期末现金 Cash at end of year")
        if kv.get("现金净变动 Change in cash and cash equivalents") is None and None not in (b, e):
            kv["现金净变动 Change in cash and cash equivalents"] = \
                e - b - (kv.get("初次并表带入现金 Cash from initial consolidation") or 0.0)
    return notes


# ── 勾稽闸门 ────────────────────────────────────────────────────────────────
def checks(final):
    """→ [(fy, 名称, 状态, 说明)]；状态 ✅/❌/—(数据不全)。"""
    out = []

    def g(kv, k):
        return kv.get(k)

    for fy in sorted(final):
        kv = final[fy]
        def rec(name, a, b, tol=None):
            if a is None or b is None:
                out.append((fy, name, "—", "数据不全"))
                return
            d = abs(a - b)
            lim = tol if tol is not None else max(1.0, abs(b) * 0.005)
            out.append((fy, name, "✅" if d <= lim else "❌", f"差 {a - b:,.1f}"))

        # 利润链分 era 走（两种列报下 NCI 扣除的位置不同）：
        #   era A（FY2008 及以前）：税前 + 税 + NCI + 终止经营 + 会计变更 = 报表 Net income（= 归母）
        #   era B（FY2009 起·ASC810）：税前 + 税 + 终止经营 = Net income(含NCI)，再 + NCI = 归母
        pre = g(kv, "税前利润 Income before income taxes")
        att = g(kv, "归母净利 Net income attributable to Disney")
        net = g(kv, "净利润 Net income")
        keys = ["所得税 Income taxes",
                "终止经营损益 Discontinued operations, net of tax",
                "会计变更累积影响 Cumulative effect of accounting changes"]
        if kv.get("_era") != "B":
            keys.append("少数股东损益 Noncontrolling interests")
        chain = (pre + sum(g(kv, k) or 0.0 for k in keys)) if pre is not None else None
        rec("利润链→" + ("净利润(含少数股东)" if kv.get("_era") == "B" else "归母净利"),
            chain, net if kv.get("_era") == "B" else att)

        ta = g(kv, "资产总计 Total assets")
        tle = g(kv, "负债与权益总计 Total liabilities and equity")
        rec("资产=负债+权益", ta, tle)

        op = g(kv, "经营活动现金流净额 Cash provided by operations")
        iv = g(kv, "投资活动现金流净额 Cash used in investing activities")
        fi = g(kv, "融资活动现金流净额 Cash provided by (used in) financing activities")
        fx = g(kv, "汇率对现金影响 Impact of exchange rates on cash") or 0.0
        dc = (g(kv, "终止经营现金流 Cash from discontinued operations")
              or sum(g(kv, k) or 0.0 for k in ("  终止经营-经营 Discontinued ops operating",
                                               "  终止经营-投资 Discontinued ops investing",
                                               "  终止经营-融资 Discontinued ops financing")))
        chg = g(kv, "现金净变动 Change in cash and cash equivalents")
        s = (op + iv + fi + fx + dc) if None not in (op, iv, fi) else None
        rec("经营+投资+融资+终止经营+汇率=现金净变动", s, chg)

        b, e = g(kv, "期初现金 Cash at beginning of year"), g(kv, "期末现金 Cash at end of year")
        ic = g(kv, "初次并表带入现金 Cash from initial consolidation") or 0.0
        rec("期初+净变动=期末", (b + chg + ic) if None not in (b, chg) else None, e)
    return out


# ── 输出 ───────────────────────────────────────────────────────────────────
def fmt(v):
    if v is None:
        return ""
    return f"{v:.1f}".rstrip("0").rstrip(".") if abs(v - round(v)) > 1e-9 else f"{round(v):d}"


def write_csv(path, header_notes, concepts, final, fys):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        for nline in header_notes:
            w.writerow([nline])
        w.writerow(["科目"] + [str(y) for y in fys])
        for name, _, _ in concepts:
            row = [name] + [fmt(final.get(y, {}).get(name)) for y in fys]
            if any(c for c in row[1:]):
                w.writerow(row)


UNIT = ("单位:百万美元(USD millions);费用/减项=负数;空=该年申报 presentation 无此科目(不补0)。"
        "⚠️FY1993-FY1997 印刷口径保留一位小数,本库原样保留。"
        "财年=截至 9 月末/10 月初的 52/53 周,FY2025 截至 2025-09-27。")


def main():
    sources = load_r()
    trusted = {}
    for (key, kind) in sorted(sources, reverse=True):
        for fy, kv in sources[(key, kind)].items():
            for name, v in kv.items():
                trusted.setdefault(fy, {}).setdefault(name, v)
    legacy, log = load_legacy(trusted)
    sources.update(legacy)

    final, restate, picks = resolve(sources)
    notes = normalize(final)
    res = checks(final)
    borrowed = [p for p in picks if p[4] and 1993 <= p[0] <= 2025]

    fys = [y for y in sorted(final) if 1993 <= y <= 2025]

    print("── Legacy 倒锁链 ──")
    for line in log:
        print("  " + line)

    bad = [r for r in res if r[2] == "❌"]
    miss = [r for r in res if r[2] == "—"]
    print(f"\n── 勾稽 ── 通过 {len([r for r in res if r[2]=='✅'])} / "
          f"失败 {len(bad)} / 数据不全 {len(miss)}")
    for fy, name, st, why in bad:
        print(f"  ❌ FY{fy} {name}: {why}")

    if borrowed:
        print(f"\n── ⚠️ 非 as-reported（该年自己那份年报里这张表没解析出来，"
              f"改用后续年报比较列）{len(borrowed)} 处 ──")
        for fy, kind, src_fy, n, _ in borrowed:
            print(f"  FY{fy} {kind} ← FY{src_fy} 年报比较列（{n} 个科目）")

    if notes:
        print("\n── 口径说明 ──")
        for n in notes[:6]:
            print("  " + n)
        if len(notes) > 6:
            print(f"  …共 {len(notes)} 条")

    print(f"\n── 重述（自己那份 vs 后续年报比较列不一致）{len(restate)} 处 ──")
    for fy, name, v0, s0, v1, s1 in restate[:12]:
        print(f"  FY{fy} {name}: FY{s0}报 {v0:,.1f} → FY{s1}报 {v1:,.1f}")
    if len(restate) > 12:
        print(f"  …共 {len(restate)} 处")

    if bad and "--force" not in sys.argv:
        print("\n🚫 勾稽未全过，按规则不写出 CSV（加 --force 可强制）")
        return

    src = {"IS": ("利润表.csv", IS_CONCEPTS), "BS": ("资产负债表.csv", BS_CONCEPTS),
           "CF": ("现金流量表.csv", CF_CONCEPTS)}
    prov = ("各年 as-reported 来源:FY1993-FY2010=各年 10-K 正文(txt/HTML)解析,"
            "FY2011-FY2025=各年 10-K 的 SEC 渲染报表 R*.htm(按 XBRL tag 归一);"
            "三 CIK:29082(FY1993-95)/1001039(FY1996-2018)/1744489(FY2019-25)。"
            "每财年优先取该财年自己那份 10-K 的当年列;重述见 重述与口径变更.csv")
    for kind, (fname, con) in src.items():
        write_csv(os.path.join(HERE, fname), [UNIT, prov], con, final, fys)
        print(f"写出 {fname}")

    with open(os.path.join(HERE, "重述与口径变更.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["财年", "科目", "as-reported值", "来源年报", "后续年报值", "后续年报"])
        for fy, name, v0, s0, v1, s1 in sorted(restate):
            w.writerow([fy, name, fmt(v0), f"FY{s0}", fmt(v1), f"FY{s1}"])
    print("写出 重述与口径变更.csv")


if __name__ == "__main__":
    main()
