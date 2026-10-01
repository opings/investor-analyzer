#!/usr/bin/env python3
"""Microsoft 三表构建器：三条数据轨合成 `利润表.csv` / `资产负债表.csv` / `现金流量表.csv` /
`营运资本变动表FY1983-1988.csv` / `重述与口径变更.csv`，**勾稽不过不写出**。

## 三条数据轨

| 轨 | 覆盖财年 | 载体 | 归一方式 | 采集器 |
|---|---|---|---|---|
| R 轨 | FY2011-2026（含比较列 FY2009-2010） | 各年 10-K 的 R*.htm | **只按 XBRL tag**（少数同 tag 多行者再按标签消歧） | `_harvest_rfiles.py` |
| L 轨 | FY1994-2010（含比较列 FY1992-1993） | 10-K 正文 txt / htm | **只按标签正则** | `_parse_legacy.py` |
| S 轨 | FY1982-1993 | 招股书（重排版文本）+ FY1986-1993 致股东年报（原件扫描） | **只按标签正则** | 人工按页图转录 → `_scans/*.json` |

🔴 **R 轨只认 tag、L/S 轨只认标签**：同一个印刷标签在不同年代指不同的东西——
「Unearned revenue」在 FY1997-1999 现金流量表里是**递延额（毛额）**、在 FY2019+ 是**净变动**；
「Total operating expenses」在 FY1997-2010 **含**营业成本、在 FY2011+ **不含**；
「Other expenses」在 FY1997-1999 是营业费用、在 FY1994 是营业外支出。混用两套规则必然在某一年错位。

## 口径声明（取数当场固定，事后查不出来）

- **期间**：全部为**财年全年**（截至 6 月 30 日）。FY2026 = 2025-07-01 ~ 2026-06-30。R 轨按 months==12 过滤。
- **主体**：合并口径。Microsoft **无少数股东权益**，净利 = 归母净利。美股无「扣非」法定口径，本库不造扣非行；
  一次性项目（商誉减值 / 减值整合重组 / 诉讼 / 遣散 / 会计变更累积影响 / 购入在研技术 / 出售子公司收益）各自单列。
- **来源年份**：每个财年取**该财年自己那份年报的当年列**（as-reported）。例外只有两类，均在「数据来源」行写明：
  ① FY1982-1985（上市前）取招股书；② FY1987-1988 现金流量表取 FY1989 年报比较列（那两年自家年报只有营运资本变动表）。
  后续年报的比较列一律只进 `重述与口径变更.csv`。
- **单位**：**百万美元**。按各表**自陈单位**换算（FY1982-1992 印千美元、FY1993 起百万）；千美元来源保留 3 位小数。
- **符号**：利润表费用为正、营业外净额按印刷符号（收益为正）；现金流量表流出为负。
- **每股数据不可跨年直接比**：各年年报 EPS / 股数按**该次申报时点**的股本基准追溯调整过（拆股 9 次）。
  SFAS 128（FY1998）之前印的是「primary EPS」（分母含普通股等价物），单列一行，不与 basic 混。
"""
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RDIR = os.path.join(HERE, "_rfiles")
LDIR = os.path.join(HERE, "_legacy")
SDIR = os.path.join(HERE, "_scans")

RYEARS = list(range(2011, 2027))
LYEARS = list(range(1994, 2011))
SYEARS = list(range(1986, 1994))
ALL_FY = list(range(1982, 2027))
TOL = 0.6          # 勾稽容差（百万美元）——百万取整的年份
TOL_K = 0.0015     # 千美元来源年份的容差（百万美元 = 1.5 千美元，容舍入）

M, PS, SH, CNT = "money", "pershare", "shares", "count"

# 例外来源：(表, 财年) → (轨, 申报键)
SPECIAL_SOURCE = {}
for _fy in (1982, 1983, 1984, 1985):
    SPECIAL_SOURCE[("IS", _fy)] = ("S", "prospectus")
for _fy in (1984, 1985):
    SPECIAL_SOURCE[("BS", _fy)] = ("S", "prospectus")
for _fy in (1987, 1988):
    SPECIAL_SOURCE[("CF", _fy)] = ("S", "1989")

# ── 概念定义 ────────────────────────────────────────────────────────────────
# (CSV 行名, [XBRL tag], [L/S 轨标签正则], [R 轨同 tag 多行时的消歧标签正则], 求和?, 量纲, 窗口)
# 窗口 = None | ("before", 正则) | ("after", 正则) | ("between", 起正则, 止正则)
# 起锚含「营收/毛利」：扫描件转录只录有数的行、没有「Operating expenses:」这类段首行；
# 费用项在任何版式里都排在营收（与毛利）之后、营业利润之前
OPEX = ("between", r"^(operating expenses|costs and expenses|net revenues?|revenues?|gross (profit|margin))",
        r"^(total (operating expenses|costs? and expenses)|operating income|income from operations)$")
NONOP = ("after", r"^(operating income|income from operations)$")

IS_CONCEPTS = [
    ("营业收入 Revenue",
     ["us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap_Revenues",
      "us-gaap_SalesRevenueNet"],
     [r"^net revenues?$", r"^revenues?$", r"^total revenue$"],
     [r"^total revenue$", r"^revenue$"], False, M, None),
    ("  产品收入 Product revenue",
     ["us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap_Revenues",
      "us-gaap_SalesRevenueGoodsNet"], [], [r"^product$"], False, M, None),
    ("  服务及其他收入 Service and other revenue",
     ["us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap_Revenues",
      "us-gaap_SalesRevenueServicesNet", "msft_SalesRevenueServicesAndOtherNet"], [], [r"^service and other$"], False, M, None),
    ("营业成本 Cost of revenue",
     ["us-gaap_CostOfGoodsAndServicesSold", "us-gaap_CostOfRevenue"],
     [r"^cost of revenues?$", r"^total cost of revenue$"],
     [r"^total cost of revenue$", r"^cost of revenue$"], False, M, None),
    ("  产品成本 Product cost of revenue",
     ["us-gaap_CostOfGoodsAndServicesSold", "us-gaap_CostOfRevenue", "us-gaap_CostOfGoodsSold"],
     [], [r"^product$"], False, M, None),
    ("  服务及其他成本 Service and other cost of revenue",
     ["us-gaap_CostOfGoodsAndServicesSold", "us-gaap_CostOfRevenue", "us-gaap_CostOfServices",
      "msft_CostOfServicesAndOther"], [], [r"^service and other$"], False, M, None),
    ("毛利 Gross margin", ["us-gaap_GrossProfit"], [r"^gross (profit|margin)$"], [], False, M, None),
    ("研发费用 Research and development", ["us-gaap_ResearchAndDevelopmentExpense"],
     [r"^research and development$"], [], False, M, OPEX),
    ("销售及市场费用 Sales and marketing", ["us-gaap_SellingAndMarketingExpense"],
     [r"^sales and marketing$"], [], False, M, OPEX),
    ("一般及管理费用 General and administrative", ["us-gaap_GeneralAndAdministrativeExpense"],
     [r"^general and administrative$"], [], False, M, OPEX),
    ("购入在研技术(仅FY1997-1998) Acquired in-process technology", [],
     [r"^acquired in-process technology$"], [], False, M, OPEX),
    ("其他营业费用(仅FY1997-1999) Other expenses (operating)", [],
     [r"^other expenses$"], [], False, M, ("before", r"^total (operating expenses|costs? and expenses)$")),
    ("员工遣散(仅FY2009) Employee severance", [], [r"^employee severance$"], [], False, M, OPEX),
    ("商誉减值 Goodwill impairment", ["us-gaap_GoodwillImpairmentLoss"],
     [r"^goodwill impairment$"], [], False, M, None),
    # FY2014 叫「Integration and restructuring」(tag BusinessCombinationIntegrationRelatedCosts)、
    # FY2015-2017 叫「Impairment, integration, and restructuring」(Nokia 手机业务减值+裁员)
    ("减值整合及重组 Impairment, integration, and restructuring",
     ["us-gaap_RestructuringSettlementAndImpairmentProvisions", "us-gaap_RestructuringCharges",
      "us-gaap_BusinessCombinationIntegrationRelatedCosts", "us-gaap_RestructuringCostsAndAssetImpairmentCharges",
      "~ImpairmentIntegrationAndRestructuring"],
     [r"^(impairment, )?integration,? and restructuring$"], [], False, M, None),
    # 「Total operating expenses」两种含义 → 构建后按该申报自身算术判定落到哪一行（见 classify_opex）
    ("营业费用合计(不含营业成本) Total operating expenses (excl. cost of revenue)",
     ["us-gaap_OperatingExpenses"], [r"^total operating expenses$"], [], False, M, None),
    ("成本及费用合计(含营业成本) Total costs and expenses (incl. cost of revenue)",
     ["us-gaap_CostsAndExpenses"], [r"^total costs? and expenses$"], [], False, M, None),
    ("营业利润 Operating income", ["us-gaap_OperatingIncomeLoss"],
     [r"^operating income$", r"^income from operations$"], [], False, M, None),
    ("利息收入(净额)(仅FY1991-1998) Interest income (net)", [],
     [r"^interest income\s*([-—–]+|-- )\s*net$", r"^interest income\s*--\s*net$", r"^interest income$"],
     [], False, M, NONOP),
    ("投资收益(仅FY1999-2008) Investment income", [],
     [r"^investment income(/\(loss\))?( and other)?$"], [], False, M, NONOP),
    ("非持续项目(仅FY1994-1996) Noncontinuing items", [], [r"^noncontinuing items$"], [], False, M, NONOP),
    ("出售收益(仅FY1999-2000) Gain on sale(s)", [],
     [r"^gain on sales?( of softimage.*)?$"], [], False, M, NONOP),
    ("权益法投资损失及其他(仅FY2000-2005) Losses on equity investees and other", [],
     [r"^losses on equity investees( and other)?$"], [], False, M, NONOP),
    ("诉讼费用(仅FY1994) Litigation charge", [], [r"^litigation charge$"], [], False, M, NONOP),
    ("股票期权计划费用(仅FY1987-1990) Stock option program expense", [],
     [r"^stock option (program expense|bonus)$"], [], False, M, NONOP),
    ("营业外收支净额 Other income (expense), net",
     ["us-gaap_NonoperatingIncomeExpense", "us-gaap_OtherNonoperatingIncomeExpense"],
     [r"^other income( \(expense\))?(, net)?$", r"^non-?operating income( \(loss\))?$",
      r"^nonoperating expense$", r"^other( expenses?)?$"], [], False, M, NONOP),
    ("税前利润 Income before income taxes",
     ["us-gaap_IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
      "us-gaap_IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
      "us-gaap_IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterest"],
     [r"^income before income taxes"], [], False, M, None),
    ("所得税 Provision for income taxes", ["us-gaap_IncomeTaxExpenseBenefit"],
     [r"^provision for income taxes"], [], False, M, None),
    ("会计变更前利润(仅FY2000-2002版式) Income before accounting change", [],
     [r"^income before (cumulative effect of )?accounting change$"], [], False, M, None),
    ("会计变更累积影响(仅FY2001) Cumulative effect of accounting change", [],
     [r"^cumulative effect of accounting change"], [], False, M,
     ("before", r"^net income$")),
    ("净利润 Net income", ["us-gaap_NetIncomeLoss"], [r"^net income$"], [], False, M, None),
    ("优先股股息(仅FY1997-2000) Preferred stock dividends", [],
     [r"^preferred stock dividends$"], [], False, M, ("after", r"^net income$")),
    ("归属普通股净利(仅FY1997-1999) Net income available for common shareholders", [],
     [r"^net income available for common"], [], False, M, None),
    ("每股收益(SFAS128前·primary·as-reported) Net income per share (primary)", [],
     [r"^(net income per share|earnings per share)(\s*\(\d\))?$"], [], False, PS, None),
    # FY2001-2002 版式：「Basic earnings per share:」段下「Before accounting change / Cumulative effect /
    # (无标签合计行)」——报告 EPS 是合计行；FY1998+ 其余年份是「Earnings per share:」段下的「Basic」
    ("基本EPS(as-reported·拆股基准随年变) Basic EPS", ["us-gaap_EarningsPerShareBasic"],
     [r"^basic$", (r"^basic earnings per share( \(\d\))? 合计$", None)], [], False, PS, ("after", r"^earnings per share")),
    ("摊薄EPS(as-reported·拆股基准随年变) Diluted EPS", ["us-gaap_EarningsPerShareDiluted"],
     [r"^diluted$", (r"^diluted earnings per share( \(\d\))? 合计$", None)], [], False, PS, ("after", r"^earnings per share")),
    ("加权股数(SFAS128前·含等价物·百万股) Average shares (primary)", [],
     [r"^(weighted )?average (common and common equivalent )?shares outstanding(\s*\(\d\))?$",
      r"^shares used in computing net income per share$"], [], False, SH, None),
    ("基本股数(百万股·as-reported) Basic shares", ["us-gaap_WeightedAverageNumberOfSharesOutstandingBasic"],
     [r"^basic$"], [], False, SH, ("after", r"^weighted average shares outstanding")),
    ("摊薄股数(百万股·as-reported) Diluted shares", ["us-gaap_WeightedAverageNumberOfDilutedSharesOutstanding"],
     [r"^diluted$"], [], False, SH, ("after", r"^weighted average shares outstanding")),
    ("每股宣派股息(as-reported) Cash dividends declared per share",
     ["us-gaap_CommonStockDividendsPerShareDeclared"],
     # FY2005 10-K 利润表印「per share」、FY2006 起印「per common share」——只认后者会漏掉 FY2005（含 3 美元特别股息）
     [r"^cash dividends declared per (common )?share$"], [], False, PS, None),
]

CA = ("before", r"^total current assets$")
NCA = ("between", r"^total current assets$", r"^total assets$")
CL = ("between", r"^(total assets|liabilities and stockholders|current liabilities)", r"^total current liabilities$")
NCL = ("between", r"^total current liabilities$", r"^(total liabilities$|commitments|stockholders)")
# 起锚含「Total current liabilities」：扫描件与早年版式没有「Stockholders' equity:」段首行
EQ = ("after", r"^(stockholders' equity|commitments and contingencies|total liabilities$|total current liabilities$)")

BS_CONCEPTS = [
    ("现金及现金等价物 Cash and cash equivalents", ["us-gaap_CashAndCashEquivalentsAtCarryingValue"],
     [r"^cash and (cash )?equivalents$", r"^of which: cash and equivalents"], [], False, M, None),
    ("短期投资 Short-term investments",
     ["us-gaap_ShortTermInvestments", "us-gaap_AvailableForSaleSecuritiesCurrent",
      "us-gaap_AvailableForSaleSecuritiesDebtSecuritiesCurrent", "us-gaap_MarketableSecuritiesCurrent"],
     [r"^short-term investments", r"^of which: short-term investments"], [], False, M, CA),
    ("现金及短期投资合计 Cash, cash equivalents, and short-term investments",
     ["us-gaap_CashCashEquivalentsAndShortTermInvestments"],
     [r"^cash and short-term investments", r"^total cash, cash equivalents,? and short-term investments$"],
     [], False, M, CA),
    ("应收账款净额 Accounts receivable, net", ["us-gaap_AccountsReceivableNetCurrent"],
     [r"^(trade )?accounts receivable"], [], False, M, CA),
    ("存货 Inventories", ["us-gaap_InventoryNet"], [r"^inventories"], [], False, M, CA),
    ("递延所得税资产(流动) Deferred income taxes (current)",
     ["us-gaap_DeferredTaxAssetsNetCurrent", "us-gaap_DeferredTaxAssetsLiabilitiesNetCurrent"],
     [r"^deferred income taxes$"], [], False, M, CA),
    ("其他流动资产 Other current assets", ["us-gaap_OtherAssetsCurrent", "us-gaap_PrepaidExpenseAndOtherAssetsCurrent"],
     [r"^other current assets$", r"^other$"], [], False, M, CA),
    ("流动资产合计 Total current assets", ["us-gaap_AssetsCurrent"], [r"^total current assets$"], [], False, M, None),
    ("固定资产净额 Property and equipment, net", ["us-gaap_PropertyPlantAndEquipmentNet"],
     [r"^property(, plant,?)? and equipment"], [], False, M, NCA),
    ("经营租赁使用权资产 Operating lease right-of-use assets", ["us-gaap_OperatingLeaseRightOfUseAsset"],
     [r"^operating lease right-of-use assets$"], [], False, M, NCA),
    ("股权及其他投资 Equity (and other) investments",
     ["us-gaap_LongTermInvestments", "us-gaap_EquitySecuritiesFvNiAndWithoutReadilyDeterminableFairValue",
      "msft_EquityInvestments"],
     [r"^equity (and other )?investments$"], [], False, M, NCA),
    ("商誉 Goodwill", ["us-gaap_Goodwill"], [r"^goodwill$"], [], False, M, NCA),
    ("无形资产净额 Intangible assets, net",
     ["us-gaap_FiniteLivedIntangibleAssetsNet", "us-gaap_IntangibleAssetsNetExcludingGoodwill"],
     [r"^intangible assets,? net$"], [], False, M, NCA),
    ("知识产权(仅FY1988) Intellectual property rights, net", [],
     [r"^intellectual property rights"], [], False, M, NCA),
    ("递延所得税资产(非流动) Deferred income taxes (non-current asset)",
     ["us-gaap_DeferredTaxAssetsNetNoncurrent", "us-gaap_DeferredIncomeTaxAssetsNet"],
     [r"^deferred income taxes$"], [], False, M, NCA),
    ("其他长期资产 Other long-term assets", ["us-gaap_OtherAssetsNoncurrent"],
     [r"^other (long-term )?assets$"], [], False, M, NCA),
    ("总资产 Total assets", ["us-gaap_Assets"], [r"^total assets$"], [], False, M, None),
    ("应付账款 Accounts payable", ["us-gaap_AccountsPayableCurrent"], [r"^accounts payable$"], [], False, M, CL),
    ("短期借款/商业票据 Short-term debt", ["us-gaap_CommercialPaper", "us-gaap_ShortTermBorrowings"],
     [r"^short-term (debt|borrowings)$"], [], False, M, CL),
    ("应付票据(仅FY1987-1992) Notes payable", [], [r"^notes payable$"], [], False, M, CL),
    # FY2012 这一行的 tag 是 ConvertibleDebtCurrent（2013 年到期的可转债 12.5 亿）
    ("一年内到期长期债务 Current portion of long-term debt", ["us-gaap_LongTermDebtCurrent", "us-gaap_ConvertibleDebtCurrent"],
     [r"^current portion of long-term debt$"], [], False, M, CL),
    ("应付薪酬 Accrued compensation", ["us-gaap_EmployeeRelatedLiabilitiesCurrent"],
     [r"^accrued compensation"], [], False, M, CL),
    ("客户押金(及递延收入·仅FY1984-1992) Customer deposits", [], [r"^customer deposits"], [], False, M, CL),
    ("应付版税及佣金(仅FY1984-1987) Royalties and commissions payable", [],
     [r"^royalties and commissions payable$"], [], False, M, CL),
    ("递延所得税负债(流动·仅招股书期) Deferred income taxes (current liability)", [],
     [r"^deferred income taxes \(current\)$"], [], False, M, CL),
    ("应交所得税(流动) Income taxes payable (current)",
     ["us-gaap_AccruedIncomeTaxesCurrent", "us-gaap_TaxesPayableCurrent"],
     [r"^(short-term )?income taxes( payable)?$"], [], False, M, CL),
    ("短期递延收入 Short-term unearned revenue",
     ["us-gaap_ContractWithCustomerLiabilityCurrent", "us-gaap_DeferredRevenueCurrent"],
     [r"^(short-term )?unearned revenues?$"], [], False, M, CL),
    ("证券借贷应付款 Securities lending payable",
     ["us-gaap_DepositsReceivedForSecuritiesLoanedAtCarryingValue", "us-gaap_SecuritiesLoaned"],
     [r"^securities lending payable$"], [], False, M, CL),
    ("其他流动负债 Other current liabilities", ["us-gaap_OtherLiabilitiesCurrent"],
     [r"^other current liabilities$", r"^other$"], [], False, M, CL),
    ("流动负债合计 Total current liabilities", ["us-gaap_LiabilitiesCurrent"],
     [r"^total current liabilities$"], [], False, M, None),
    ("长期债务 Long-term debt", ["us-gaap_LongTermDebtNoncurrent"], [r"^long-term debt$"], [], False, M, NCL),
    ("资本租赁义务(仅FY1986-1987) Capital lease obligations", [],
     [r"^(long-term portion of )?capital lease obligations$"], [], False, M, NCL),
    ("长期应交所得税 Long-term income taxes", ["us-gaap_AccruedIncomeTaxesNoncurrent"],
     [r"^long-term income taxes$"], [], False, M, NCL),
    ("长期递延收入 Long-term unearned revenue",
     ["us-gaap_ContractWithCustomerLiabilityNoncurrent", "us-gaap_DeferredRevenueNoncurrent"],
     [r"^long-term unearned revenue$"], [], False, M, NCL),
    ("递延所得税负债(非流动) Deferred income taxes (non-current liability)",
     ["us-gaap_DeferredTaxLiabilitiesNoncurrent", "us-gaap_DeferredIncomeTaxLiabilitiesNet"],
     [r"^deferred income taxes$"], [], False, M, NCL),
    ("经营租赁负债(非流动) Operating lease liabilities", ["us-gaap_OperatingLeaseLiabilityNoncurrent"],
     [r"^operating lease liabilities$"], [], False, M, NCL),
    ("其他长期负债 Other long-term liabilities", ["us-gaap_OtherLiabilitiesNoncurrent"],
     [r"^other long-term liabilities$"], [], False, M, NCL),
    ("负债合计 Total liabilities", ["us-gaap_Liabilities"], [r"^total liabilities$"], [], False, M, None),
    # FY1995-1997 资产负债表在负债与权益之间印两行「夹层」：少数股东权益 + 认沽权证（公司为回购计划
    # 卖出的、以自家股票为标的的 put warrants，赎回义务列在权益之外）
    ("少数股东权益(仅FY1995-1997) Minority interest", ["us-gaap_MinorityInterest"],
     [r"^minority interest$"], [], False, M, None),
    ("认沽权证(仅FY1995-2000) Put warrants", [], [r"^put warrants$"], [], False, M, None),
    ("可转换优先股(仅FY1984-1986·FY1997-1999) Convertible preferred stock",
     ["us-gaap_PreferredStockValue"], [r"^convertible preferred stock"], [], False, M, EQ),
    # FY2011-2012 用单数 CommonStockIncludingAdditionalPaidInCapital、FY2013 起复数 CommonStocks…
    ("普通股及资本公积 Common stock and paid-in capital",
     ["us-gaap_CommonStocksIncludingAdditionalPaidInCapital", "us-gaap_CommonStockIncludingAdditionalPaidInCapital"],
     [r"^common stock and paid-in capital"], [], False, M, EQ),
    ("普通股面值(仅FY1984-1989) Common stock", [], [r"^common stock$"], [], False, M, EQ),
    ("资本公积(仅FY1984-1989) Paid-in capital", [], [r"^paid-in capital$"], [], False, M, EQ),
    # FY1999-2012 留存收益一行**含**累计其他综合收益（印「Retained earnings (deficit), including accumulated
    # other comprehensive income of $X」），FY2011-2012 的 tag 是 msft_RetainedEarningsAccumulatedDeficitAnd
    # AccumulatedOtherComprehensiveIncome…；FY2013 起两项分列。跨年比留存收益前先看这一点。
    ("留存收益 Retained earnings (deficit)",
     ["us-gaap_RetainedEarningsAccumulatedDeficit",
      "~^msft_RetainedEarningsAccumulatedDeficitAndAccumulatedOtherComprehensive"],
     [r"^retained (earnings|deficit)"], [], False, M, EQ),
    ("累计其他综合收益 Accumulated other comprehensive income (loss)",
     ["us-gaap_AccumulatedOtherComprehensiveIncomeLossNetOfTax"],
     [r"^accumulated other comprehensive"], [], False, M, EQ),
    ("外币折算调整(仅FY1984-1989) Translation adjustment", [], [r"^translation adjustment$"], [], False, M, EQ),
    ("股东权益合计 Total stockholders' equity", ["us-gaap_StockholdersEquity"],
     [r"^total stockholders. equity$"], [], False, M, None),
    ("负债和股东权益合计 Total liabilities and stockholders' equity",
     ["us-gaap_LiabilitiesAndStockholdersEquity"],
     [r"^total liabilities and stockholders. equity$"], [], False, M, None),
]

OPS = ("before", r"^net cash (from|provided by|from \(used in\)) operations")
FIN = ("between", r"^net cash (from|provided by) operations", r"^net cash .*financing$")
INV = ("between", r"^net cash .*financing$", r"^net cash .*invest(ing|ments)$")

CF_CONCEPTS = [
    ("净利润 Net income", ["us-gaap_NetIncomeLoss", "us-gaap_ProfitLoss"], [r"^net income$"], [], False, M, None),
    ("会计变更累积影响(加回·仅FY2001) Cumulative effect of accounting change, net of tax", [],
     [r"^cumulative effect of accounting change"], [], False, M, OPS),
    ("折旧摊销及其他 Depreciation, amortization, and other",
     ["msft_DepreciationAmortizationAndOther", "us-gaap_DepreciationDepletionAndAmortization",
      "us-gaap_DepreciationAmortizationAndOther", "us-gaap_DepreciationAndAmortization"],
     [r"^depreciation(,| and) amortization", r"^depreciation$"], [], False, M, OPS),
    ("商誉减值(现金流加回) Goodwill impairment", ["us-gaap_GoodwillImpairmentLoss"],
     [r"^goodwill impairment$"], [], False, M, OPS),
    ("资产减值(现金流加回) Asset impairments", ["us-gaap_AssetImpairmentCharges"],
     [r"^asset impairments?$"], [], False, M, OPS),
    ("购入在研技术核销(仅FY1997-1998) Write-off of acquired in-process technology", [],
     [r"^write-off of acquired in-process technology$"], [], False, M, OPS),
    ("出售收益(仅FY1999-2000) Gain on sale(s)", [],
     [r"^gain on sales?( of softimage.*)?$"], [], False, M, OPS),
    ("股权激励费用 Stock-based compensation",
     ["us-gaap_ShareBasedCompensation", "us-gaap_AllocatedShareBasedCompensationExpense"],
     [r"^stock-based compensation( expense)?$"], [], False, M, OPS),
    ("投资及衍生品已确认净损益 Net recognized (gains) losses on investments and derivatives",
     ["msft_GainLossOnInvestmentsAndDerivativeInstruments", "us-gaap_GainLossOnInvestmentsAndDerivativeInstruments",
      "us-gaap_GainLossOnInvestments"],
     [r"^net recognized \(?(gains|losses)"], [], False, M, OPS),
    ("股权激励超额税收利益(经营段) Excess tax benefits from stock-based compensation (operating)",
     ["us-gaap_ExcessTaxBenefitFromShareBasedCompensationOperatingActivities"],
     [r"^excess tax benefits? from stock-based (compensation|payment arrangements)$"], [], False, M, OPS),
    ("股票期权税收利益(经营段·仅FY2000-2005) Stock option income tax benefits (operating)", [],
     [r"^stock option income tax benefits$"], [], False, M, OPS),
    ("递延所得税 Deferred income taxes",
     ["us-gaap_DeferredIncomeTaxExpenseBenefit", "us-gaap_DeferredIncomeTaxesAndTaxCredits"],
     [r"^deferred income taxes$"], [], False, M, OPS),
    ("递延收入新增(毛额) Deferral of unearned revenue", ["us-gaap_IncreaseDecreaseInDeferredRevenue"],
     [r"^deferral of unearned revenue$", r"^unearned revenue$"], [], False, M, OPS),
    ("递延收入确认 Recognition of unearned revenue", ["us-gaap_RecognitionOfDeferredRevenue"],
     [r"^recognition of unearned revenue"], [], False, M, OPS),
    ("递延收入净变动(FY2019起) Unearned revenue (net change)",
     ["us-gaap_IncreaseDecreaseInContractWithCustomerLiability"], [], [], False, M, OPS),
    ("流动负债变动(早年合并口径) Current liabilities", [],
     [r"^current liabilities(, excluding notes payable)?$"], [], False, M, OPS),
    ("应收账款变动 Accounts receivable", ["us-gaap_IncreaseDecreaseInAccountsReceivable"],
     [r"^accounts receivable$"], [], False, M, OPS),
    ("存货变动 Inventories", ["us-gaap_IncreaseDecreaseInInventories"], [r"^inventories$"], [], False, M, OPS),
    ("其他流动资产变动 Other current assets",
     ["us-gaap_IncreaseDecreaseInOtherCurrentAssets", "us-gaap_IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets"],
     [r"^other current assets$"], [], False, M, OPS),
    ("其他长期资产变动 Other long-term assets", ["us-gaap_IncreaseDecreaseInOtherNoncurrentAssets"],
     [r"^other long-term assets$"], [], False, M, OPS),
    ("应付账款变动 Accounts payable", ["us-gaap_IncreaseDecreaseInAccountsPayable"],
     [r"^accounts payable$"], [], False, M, OPS),
    ("应交所得税变动 Income taxes",
     ["us-gaap_IncreaseDecreaseInIncomeTaxesPayableNetOfIncomeTaxesReceivable",
      "us-gaap_IncreaseDecreaseInAccruedIncomeTaxesPayable", "us-gaap_IncreaseDecreaseInIncomeTaxes"],
     [r"^income taxes$"], [], False, M, OPS),
    ("其他流动负债变动 Other current liabilities", ["us-gaap_IncreaseDecreaseInOtherCurrentLiabilities"],
     [r"^other current liabilities$"], [], False, M, OPS),
    ("其他长期负债变动 Other long-term liabilities", ["us-gaap_IncreaseDecreaseInOtherNoncurrentLiabilities"],
     [r"^other long-term liabilities$"], [], False, M, OPS),
    ("经营活动现金流净额 Net cash from operations",
     ["us-gaap_NetCashProvidedByUsedInOperatingActivities",
      "us-gaap_NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
     [r"^net cash (from|provided by) operations$"], [], False, M, None),
    # —— 融资 ——
    ("短期借款净额(≤90天) Short-term debt, maturities of 90 days or less, net",
     ["us-gaap_ProceedsFromRepaymentsOfShortTermDebtMaturingInThreeMonthsOrLess",
      "us-gaap_ProceedsFromRepaymentsOfCommercialPaper"],
     [r"^short-term (debt|borrowings).*90 days or less"], [], False, M, FIN),
    ("发行债务所得 Proceeds from issuance of debt",
     ["us-gaap_ProceedsFromDebtMaturingInMoreThanThreeMonths", "us-gaap_ProceedsFromIssuanceOfLongTermDebt",
      "us-gaap_ProceedsFromIssuanceOfDebt", "msft_ProceedsFromShortAndLongTermBorrowings"],
     [r"^proceeds from issuance of debt"], [], False, M, FIN),
    ("偿还债务 Repayments of debt",
     ["us-gaap_RepaymentsOfDebtMaturingInMoreThanThreeMonths", "us-gaap_RepaymentsOfLongTermDebt",
      "us-gaap_RepaymentsOfDebt", "msft_RepaymentsOfShortTermAndLongTermBorrowings"],
     [r"^repayments of debt"], [], False, M, FIN),
    ("应付票据变动(仅FY1987-1992) Notes payable", [], [r"^notes payable$"], [], False, M, FIN),
    ("债务置换溢价(仅FY2020-2021) Cash premium on debt exchange",
     ["us-gaap_PaymentsOfDebtExtinguishmentCosts", "us-gaap_PaymentsOfDebtRestructuringCosts"],
     [r"^cash premium on debt exchange$"], [], False, M, FIN),
    ("发行股票 Common stock issued", ["us-gaap_ProceedsFromIssuanceOfCommonStock"],
     [r"^common stock issued$"], [], False, M, FIN),
    ("回购股票 Common stock repurchased", ["us-gaap_PaymentsForRepurchaseOfCommonStock"],
     [r"^common stock repurchased( and retired)?$"], [], False, M, FIN),
    ("支付普通股股息 Common stock cash dividends paid",
     ["us-gaap_PaymentsOfDividendsCommonStock", "us-gaap_PaymentsOfDividends"],
     [r"^common stock (cash )?dividends?( paid)?$"], [], False, M, FIN),
    ("发行优先股(仅FY1997) Preferred stock issued", [], [r"^preferred stock issued$"], [], False, M, FIN),
    ("支付优先股股息(仅FY1997-1999) Preferred stock dividends", ["us-gaap_PaymentsOfDividendsPreferredStockAndPreferenceStock"],
     [r"^preferred stock dividends$"], [], False, M, FIN),
    ("认沽权证净额(仅FY1995-2001) Put warrants, net", [],
     [r"^put warrant proceeds$", r"^sales/\(repurchases\) of put warrants$", r"^repurchases of put warrants$"],
     [], False, M, FIN),
    ("股票期权税收利益(融资段) Stock option income tax benefits (financing)",
     ["us-gaap_ExcessTaxBenefitFromShareBasedCompensationFinancingActivities"],
     [r"^stock option income tax benefits$", r"^income tax benefits? related to stock options$",
      r"^excess tax benefits? from stock-based (compensation|payment arrangements)$"], [], False, M, FIN),
    ("其他融资活动 Other financing", ["us-gaap_ProceedsFromPaymentsForOtherFinancingActivities"],
     [r"^other(, net)?$"], [], False, M, FIN),
    ("融资活动现金流净额 Net cash from (used in) financing",
     ["us-gaap_NetCashProvidedByUsedInFinancingActivities",
      "us-gaap_NetCashProvidedByUsedInFinancingActivitiesContinuingOperations"],
     [r"^net cash .*financing$"], [], False, M, None),
    # —— 投资 ——
    ("资本开支 Additions to property and equipment", ["us-gaap_PaymentsToAcquirePropertyPlantAndEquipment"],
     [r"^additions to property(, plant,?)? and equipment"], [], False, M, INV),
    ("收购公司及无形资产 Acquisition of companies, net of cash acquired, and purchases of intangible and other assets",
     ["msft_AcquisitionsNetofCashAcquiredAndPurchasesOfIntangibleandOtherAssets",
      "msft_AcquisitionsNetOfCashAcquiredAndPurchasesOfIntangibleAndOtherAssets",
      "us-gaap_PaymentsToAcquireBusinessesNetOfCashAcquired"],
     [r"^acquisitions? of companies", r"^cash portion of webtv purchase price$",
      r"^acquisition of intellectual property rights$", r"^investment in the santa cruz operation"],
     [], True, M, INV),
    ("股权投资及其他(仅FY1995-1998) Equity investments and other", [],
     [r"^equity investments and other$"], [], False, M, INV),
    ("出售Softimage所得(仅FY1999) Cash proceeds from sale of Softimage", [],
     [r"^cash proceeds from sale of softimage"], [], False, M, INV),
    ("购买投资 Purchases of investments", ["us-gaap_PaymentsToAcquireInvestments"],
     [r"^purchases of investments$"], [], False, M, INV),
    ("投资到期 Maturities of investments",
     ["us-gaap_ProceedsFromMaturitiesPrepaymentsAndCallsOfAvailableForSaleSecurities",
      "us-gaap_ProceedsFromSaleMaturityAndCollectionsOfInvestments"],
     [r"^maturities of investments$"], [], False, M, INV),
    ("出售投资 Sales of investments",
     ["us-gaap_ProceedsFromSaleOfAvailableForSaleSecurities", "us-gaap_ProceedsFromSaleOfAvailableForSaleSecuritiesDebt",
      "us-gaap_ProceedsFromSaleAndMaturityOfOtherInvestments", "msft_ProceedsFromInvestments"],
     [r"^sales of investments$"], [], False, M, INV),
    ("短期投资净额(仅FY1987-1996) Short-term investments, net", [],
     [r"^short-term investments$"], [], False, M, INV),
    ("证券借贷应付款变动 Securities lending payable",
     ["us-gaap_IncreaseDecreaseInCollateralHeldUnderSecuritiesLending",
      "us-gaap_IncreaseDecreaseInCashCollateralForLoanedSecurities"],
     [r"^(net proceeds from )?securities lending( payable)?$"], [], False, M, INV),
    ("其他投资活动 Other investing",
     ["us-gaap_PaymentsForProceedsFromOtherInvestingActivities"],
     [r"^other investing$", r"^other assets$", r"^other(, net)?$"], [], False, M, INV),
    ("投资活动现金流净额 Net cash from (used in) investing",
     ["us-gaap_NetCashProvidedByUsedInInvestingActivities",
      "us-gaap_NetCashProvidedByUsedInInvestingActivitiesContinuingOperations"],
     [r"^net cash .*invest(ing|ments)$"], [], False, M, None),
    # FY2022 起 tag 变成 …RestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations → 按前缀认
    ("汇率影响 Effect of exchange rates", ["~^us-gaap_EffectOfExchangeRateOnCash"],
     [r"^effect of (foreign )?exchange rate"], [], False, M, None),
    # 🔴 R 轨里「净变动 / 期初 / 期末」三行常共用 tag → 一律按标签取（R 轨也用标签）
    ("现金净变动 Net change in cash and cash equivalents", [],
     [r"^net change in cash and (cash )?equivalents"], [r"^net change in cash and (cash )?equivalents"], False, M, None),
    ("期初现金 Cash and cash equivalents, beginning of period", [],
     [r"^cash and (cash )?equivalents,? (at )?beginning of (year|period)$"],
     [r"^cash and (cash )?equivalents,? (at )?beginning of (year|period)$"], False, M, None),
    ("期末现金 Cash and cash equivalents, end of period", [],
     [r"^cash and (cash )?equivalents,? (at )?end of (year|period)"],
     [r"^cash and (cash )?equivalents,? (at )?end of (year|period)"], False, M, None),
    ("支付利息(脚注·FY1987-1990) Interest paid (footnote)", [],
     [r"^interest paid \(footnote"], [], False, M, None),
    ("支付所得税(脚注·FY1987-1990) Income taxes paid (footnote)", [],
     [r"^income taxes paid \(footnote"], [], False, M, None),
]

SPEC = {"IS": IS_CONCEPTS, "BS": BS_CONCEPTS, "CF": CF_CONCEPTS}

# R 轨维度块：FY2018 起利润表把产品/服务拆分印在表尾的**维度块**里——
#   「Product」(tag srt_ProductOrServiceAxis·无数值) → 「Revenue」「Cost of revenue」
#   「Service and Other」→「Revenue」「Cost of revenue」
# 块内行与正表行**共用同一个 tag**。故：正表概念只认块外行；分项概念只认指定块内的指定行。
# (FY2016-2017 版式是正表里直接印「Product / Service and other / Total revenue」三行，走 rpats。)
R_BLOCK = {
    "  产品收入 Product revenue": (r"^product$", r"^revenue$"),
    "  服务及其他收入 Service and other revenue": (r"^service and other$", r"^revenue$"),
    "  产品成本 Product cost of revenue": (r"^product$", r"^cost of revenue$"),
    "  服务及其他成本 Service and other cost of revenue": (r"^service and other$", r"^cost of revenue$"),
}


def r_blocks(rows):
    """给 R 文件每一行标注所属维度块（块首 = tag 以 Axis/Member 结尾或标签以 [Member] 结尾的无值行）。"""
    out, cur = [], None
    for r in rows:
        tag = r.get("tag") or ""
        if (tag.endswith("Axis") or tag.endswith("Member") or r["label"].endswith("[Member]")) \
                and all(v is None for v in r["vals"]):
            cur = norm(r["label"])
            out.append(("HEAD", cur))
            continue
        out.append(cur)
    return out
# R 轨：这些概念**只能**靠「tag + 消歧标签」同时命中，绝不能退化为「同 tag 第一行」
# （产品/服务分项与总收入共用一个 tag，取第一行会把「产品收入」当成总收入）
STRICT_R = {"营业收入 Revenue", "  产品收入 Product revenue", "  服务及其他收入 Service and other revenue",
            "营业成本 Cost of revenue", "  产品成本 Product cost of revenue",
            "  服务及其他成本 Service and other cost of revenue"}


def norm(s):
    s = re.sub(r"\s+", " ", (s or "")).strip().lower()
    return s.replace("’", "'")


# ── 申报自身的印刷错误（filer errata）─────────────────────────────────────────
# (轨, 申报键, 表, 行标签正则, 财年, 印刷值, 订正值, 证据)
# 只收「有双证」的：①该申报自己的分项和/合计关系只在订正值下成立；②后续申报的比较列印的是订正值。
FILER_ERRATA = [
    ("L", "2002", "CF", r"^maturities of investments$", 2002, 8.654, 8654.0,
     "FY2002 10-K 现金流量表把 8,654 印成「8.654」(小数点代替千分位逗号)；"
     "①投资段 −770−89,386+8,654+70,657 = −10,845 与印刷合计相等；②FY2003 10-K 比较列印 8,654"),
]
ERRATA_LOG = []


def apply_errata(books):
    for tr, key, stn, pat, fy, printed, fixed, why in FILER_ERRATA:
        st = books.get((tr, key), {}).get(stn)
        if not st:
            raise SystemExit(f"❌ errata 目标申报不存在：{tr}{key} {stn}")
        i = col_index(st, fy, tr)
        hit = [r for r in st["rows"] if re.search(pat, norm(r["label"]))]
        if i is None or not hit:
            raise SystemExit(f"❌ errata 目标行不存在：{tr}{key} {stn} {pat} FY{fy}")
        r = hit[0]
        sc = table_scales(st, tr)[M]
        cur = r["vals"][i] * sc
        if abs(cur - printed) > 1e-9:
            raise SystemExit(f"❌ errata 印刷值不符（{cur} ≠ {printed}）——源文件或解析器变了，先复核再改")
        r["vals"][i] = fixed / sc
        ERRATA_LOG.append((stn, r["label"], fy, printed, fixed, f"{tr}{key}", why))


# ── 读申报 ──────────────────────────────────────────────────────────────────
def load():
    out = {}
    for fy in RYEARS:
        p = os.path.join(RDIR, f"{fy}.json")
        if os.path.exists(p):
            out[("R", str(fy))] = json.load(open(p))["statements"]
    for fy in LYEARS:
        p = os.path.join(LDIR, f"{fy}.json")
        if os.path.exists(p):
            out[("L", str(fy))] = json.load(open(p))["statements"]
    for name in [str(y) for y in SYEARS] + ["prospectus"]:
        p = os.path.join(SDIR, f"{name}.json")
        if os.path.exists(p):
            out[("S", name)] = json.load(open(p))["statements"]
    return out


def table_scales(st, track):
    if track in ("L", "S"):
        s = st["scale"]
        return {M: s, SH: s, PS: 1.0, CNT: 1.0}
    u = norm(st.get("unit"))
    ushare = u
    u = re.sub(r"shares in (millions|thousands)", " ", u)
    money = 1.0 if "in millions" in u else (1e3 if "in billions" in u else (1e-3 if "in thousands" in u else 1e-6))
    if "shares in millions" in ushare:
        shares = 1.0
    elif "shares in thousands" in ushare:
        shares = 1e-3
    else:
        shares = money
    return {M: money, SH: shares, PS: 1.0, CNT: 1.0}


def col_index(st, fy, track):
    if track in ("L", "S"):
        return st["years"].index(fy) if fy in st["years"] else None
    for i, p in enumerate(st["periods"]):
        m = re.search(r"\b((19|20)\d\d)\b", p)
        if m and int(m.group(1)) == fy:
            if st["months"] and st["months"][i] not in (12, None):
                continue
            return i
    return None


def row_window(rows, scope):
    """把可匹配行限制在一个区间内。

    🔴 **锚行找不到 → 空窗口，不是全表**。第一版找不到锚就退回全表，于是 FY1998-2003
    利润表里「Weighted average shares outstanding」段不存在（那几年利润表不印股数），
    「基本股数」概念的窗口退化成全表、抓到了 EPS 段的「Basic 1.54」——净利÷股数 = 5,000+ 倍 EPS，
    靠 C6 才现形。闸门不能以「锚存在」为前提，取数也不能。
    """
    n = len(rows)
    if not scope:
        return 0, n
    if scope[0] == "between":
        lo = None
        for i, r in enumerate(rows):
            if re.search(scope[1], norm(r["label"])):
                lo = i + 1
                break
        if lo is None:
            return 0, 0
        hi = n
        for i in range(lo, n):
            if re.search(scope[2], norm(rows[i]["label"])):
                hi = i
                break
        return lo, hi
    mode, pat = scope
    for i, r in enumerate(rows):
        if re.search(pat, norm(r["label"])):
            return (0, i) if mode == "before" else (i + 1, n)
    return 0, 0


def tag_hit(tag, tags):
    """tag 列表里以 ~ 开头的是正则（Microsoft 自定义 tag 名很长、R 文件里被截断显示）。"""
    if not tag:
        return False
    for t in tags:
        if t.startswith("~"):
            if re.search(t[1:], tag):
                return True
        elif tag == t:
            return True
    return False


def row_scale(row, sc_tab, kind, track):
    """S 轨可逐行覆盖量纲：shares=千股→百万股 / shares_mn=百万股 / pershare / count / mn（脚注百万美元）。"""
    if track != "S":
        return sc_tab[kind]
    rk = row.get("kind")
    if rk == "shares":
        return 1e-3
    if rk in ("shares_mn", "pershare", "count", "mn"):
        return 1.0
    return sc_tab[kind]


def pick(st, c, fy, track):
    name, tags, lpats, rpats, do_sum, kind, scope = c
    if not st:
        return None
    idx = col_index(st, fy, track)
    if idx is None:
        return None
    sc = table_scales(st, track)
    rows = st["rows"]

    def val(row):
        v = row["vals"][idx] if idx < len(row["vals"]) else None
        return None if v is None else v * row_scale(row, sc, kind, track)

    if track == "R":
        blocks = r_blocks(rows)
        if name in R_BLOCK:
            bpat, lpat = R_BLOCK[name]
            hh = [r for r, b in zip(rows, blocks) if isinstance(b, str) and re.search(bpat, b)
                  and re.search(lpat, norm(r["label"])) and tag_hit(r.get("tag"), tags) and val(r) is not None]
            if hh:
                return val(hh[0])
        face = [r for r, b in zip(rows, blocks) if b is None]       # 只认正表（块外）行
        rows = face
        if tags:
            hits = [r for r in rows if tag_hit(r.get("tag"), tags) and val(r) is not None]
            if rpats:
                for pat in rpats:
                    hh = [r for r in hits if re.search(pat, norm(r["label"]))]
                    if hh:
                        return sum(val(r) for r in hh) if do_sum else val(hh[0])
                if name in STRICT_R:
                    return None
            if hits:
                if do_sum:
                    return sum(val(r) for r in hits)
                for t in tags:
                    for r in hits:
                        if tag_hit(r.get("tag"), [t]):
                            return val(r)
            return None
        # 无 tag 的概念（现金期初/期末/净变动）在 R 轨按标签取
        for pat in rpats:
            hh = [r for r in rows if re.search(pat, norm(r["label"])) and val(r) is not None]
            if hh:
                return val(hh[0])
        return None
    # L / S 轨：只按标签。模式可写成 (正则, 窗口) 元组覆盖概念级窗口（None = 全表）
    def window_for(p):
        sc_ = p[1] if isinstance(p, tuple) else scope
        lo, hi = row_window(rows, sc_)
        return rows[lo:hi], (p[0] if isinstance(p, tuple) else p)

    if do_sum:
        # 求和概念取**所有模式命中行的并集**（第一版命中第一个模式就返回，FY1989 投资段
        # 「购入知识产权」与「投资 SCO」两行只加了前一行，投资明细和差 19.9 = SCO 那一行）
        seen, tot = set(), None
        for p in lpats:
            win, pat = window_for(p)
            for r in win:
                if id(r) in seen or val(r) is None or not re.search(pat, norm(r["label"])):
                    continue
                seen.add(id(r))
                tot = (tot or 0.0) + val(r)
        return tot
    for p in lpats:
        win, pat = window_for(p)
        hh = [r for r in win if re.search(pat, norm(r["label"])) and val(r) is not None]
        if hh:
            return val(hh[0])
    return None


def extract(books, src, key, fy):
    track = src[0]
    st = books[src].get(key)
    d = {}
    for c in SPEC[key]:
        v = pick(st, c, fy, track)
        if v is not None:
            d[c[0]] = v
    if key == "IS" and d:
        d = classify_opex(d)
    return d


# ── 「营业费用合计」两种含义的判定 ──────────────────────────────────────────
OPX_EX = "营业费用合计(不含营业成本) Total operating expenses (excl. cost of revenue)"
OPX_IN = "成本及费用合计(含营业成本) Total costs and expenses (incl. cost of revenue)"
OPEX_ITEMS = ["研发费用 Research and development", "销售及市场费用 Sales and marketing",
              "一般及管理费用 General and administrative", "购入在研技术(仅FY1997-1998) Acquired in-process technology",
              "其他营业费用(仅FY1997-1999) Other expenses (operating)", "员工遣散(仅FY2009) Employee severance",
              "商誉减值 Goodwill impairment", "减值整合及重组 Impairment, integration, and restructuring"]


def classify_opex(d):
    """按该申报**自己的数**判「营业费用合计」含不含营业成本，不按标签措辞。
    FY1997-2010 的「Total operating expenses」含营业成本、FY1989-1996 与 FY2011+ 不含 ——
    同一个标签、两种口径；判据 = 合计 − 各费用项 ≈ 0（不含）还是 ≈ 营业成本（含）。"""
    tot = d.get(OPX_EX)
    if tot is None:
        return d
    items = sum(d.get(k) or 0.0 for k in OPEX_ITEMS)
    cost = d.get("营业成本 Cost of revenue") or 0.0
    tol = max(TOL, abs(tot) * 1e-6)
    if cost and abs(tot - items - cost) <= tol and abs(tot - items) > tol:
        out = dict(d)
        out[OPX_IN] = out.pop(OPX_EX)
        return out
    return d


def has_year(books, src, key, fy):
    st = books[src].get(key)
    return bool(st) and col_index(st, fy, src[0]) is not None


def own_source(books, key, fy):
    """as-reported 来源：特例表 → 自家 R → 自家 L → 自家 S。"""
    if (key, fy) in SPECIAL_SOURCE:
        s = SPECIAL_SOURCE[(key, fy)]
        return s if s in books and has_year(books, s, key, fy) else None
    for tr in ("R", "L", "S"):
        s = (tr, str(fy))
        if s in books and has_year(books, s, key, fy):
            return s
    return None


XMATCH = {"IS": 0, "BS": 0, "CF": 0}   # 跨申报交叉核：另一份申报印出**同值**的格数（独立印刷处二次确认）


def build(books, key):
    data = {c[0]: {} for c in SPEC[key]}
    origin, rest = {}, []
    for fy in ALL_FY:
        src = own_source(books, key, fy)
        if not src:
            continue
        d = extract(books, src, key, fy)
        for name, v in d.items():
            data[name][fy] = v
        if d:
            tag = "招股书" if src[1] == "prospectus" else f"{src[0]}{src[1]}"
            origin[fy] = f"{tag}自身" if src[1] in (str(fy), "prospectus") else f"{tag}比较列"
    # 重述追溯：同一财年在**别的**申报里印的值 vs as-reported
    for fy in ALL_FY:
        src0 = own_source(books, key, fy)
        if not src0:
            continue
        for src in sorted(books, key=lambda k: (k[1] != "prospectus", k[1], k[0])):
            if src == src0 or not has_year(books, src, key, fy):
                continue
            d = extract(books, src, key, fy)
            for c in SPEC[key]:
                name, kd = c[0], c[5]
                a, v = data[name].get(fy), d.get(name)
                if a is None or v is None:
                    continue
                tol = TOL if kd == M else 0.005
                if abs(a - v) > max(tol, abs(a) * 0.003):
                    tag = "招股书" if src[1] == "prospectus" else f"{src[0]}{src[1]}"
                    rest.append((key, name, fy, round(a, 3), round(v, 3), tag, round(v - a, 3)))
                else:
                    XMATCH[key] += 1
    return data, origin, rest


# ── 勾稽 ────────────────────────────────────────────────────────────────────
def g(d, name, fy, dflt=0.0):
    v = d.get(name, {}).get(fy)
    return dflt if v is None else v


def has(d, name, fy):
    return d.get(name, {}).get(fy) is not None


def tol_for(fy):
    return TOL_K if fy <= 1992 else TOL


RUN = []   # 每条被**实际执行**的勾稽 (财年, 代码) —— 条数本身是指标（记忆 chained-builder-silent-truncation）


def chk(bad, fy, code, dv, tol):
    RUN.append((fy, code.split(" ")[0]))
    if abs(dv) > tol:
        bad.append((fy, code, round(dv, 3)))


REQUIRED = {
    "IS": ["营业收入 Revenue", "营业成本 Cost of revenue", "营业利润 Operating income",
           "税前利润 Income before income taxes", "所得税 Provision for income taxes", "净利润 Net income"],
    "BS": ["总资产 Total assets", "流动资产合计 Total current assets", "流动负债合计 Total current liabilities",
           "股东权益合计 Total stockholders' equity", "应收账款净额 Accounts receivable, net",
           "固定资产净额 Property and equipment, net", "应付账款 Accounts payable"],
    "CF": ["经营活动现金流净额 Net cash from operations", "投资活动现金流净额 Net cash from (used in) investing",
           "融资活动现金流净额 Net cash from (used in) financing", "期末现金 Cash and cash equivalents, end of period",
           "资本开支 Additions to property and equipment", "净利润 Net income"],
}


def check_required(built):
    """C0：只要某年有该表任何数据，核心科目就必须有值（锚科目丢失时其余勾稽会静默全过——耐克实证）。"""
    bad = []
    for key, req in REQUIRED.items():
        d = built[key][0]
        for fy in ALL_FY:
            if not any(d[c[0]].get(fy) is not None for c in SPEC[key]):
                continue
            for name in req:
                if d.get(name, {}).get(fy) is None:
                    bad.append((fy, f"C0 {key} 必填项缺失: {name[:24]}", 0))
        # 现金类：BS 必须有「现金及短投合计」或「现金」之一
        if key == "BS":
            for fy in ALL_FY:
                if not any(d[c[0]].get(fy) is not None for c in SPEC[key]):
                    continue
                if not (has(d, "现金及短期投资合计 Cash, cash equivalents, and short-term investments", fy)
                        or has(d, "现金及现金等价物 Cash and cash equivalents", fy)):
                    bad.append((fy, "C0 BS 必填项缺失: 现金", 0))
    return bad


def check(I, B, C):
    bad = []
    R, COST, GP = "营业收入 Revenue", "营业成本 Cost of revenue", "毛利 Gross margin"
    OI, PBT, TAX, NI = "营业利润 Operating income", "税前利润 Income before income taxes", \
        "所得税 Provision for income taxes", "净利润 Net income"
    BEF = "会计变更前利润(仅FY2000-2002版式) Income before accounting change"
    CUM = "会计变更累积影响(仅FY2001) Cumulative effect of accounting change"
    NONOP_ITEMS = ["利息收入(净额)(仅FY1991-1998) Interest income (net)", "投资收益(仅FY1999-2008) Investment income",
                   "非持续项目(仅FY1994-1996) Noncontinuing items",
                   "出售收益(仅FY1999-2000) Gain on sale(s)",
                   "权益法投资损失及其他(仅FY2000-2005) Losses on equity investees and other",
                   "诉讼费用(仅FY1994) Litigation charge",
                   "股票期权计划费用(仅FY1987-1990) Stock option program expense",
                   "营业外收支净额 Other income (expense), net"]
    for fy in ALL_FY:
        T = tol_for(fy)
        if has(I, R, fy):
            if has(I, GP, fy):
                dv = g(I, R, fy) - g(I, COST, fy) - g(I, GP, fy)
                chk(bad, fy, "C1 营收−成本=毛利", dv, T)
            for a, b, tot, nm in (("  产品收入 Product revenue", "  服务及其他收入 Service and other revenue", R, "C7 产品+服务收入=营收"),
                                  ("  产品成本 Product cost of revenue", "  服务及其他成本 Service and other cost of revenue",
                                   COST, "C8 产品+服务成本=营业成本")):
                if has(I, a, fy) or has(I, b, fy):
                    dv = g(I, a, fy) + g(I, b, fy) - g(I, tot, fy)
                    chk(bad, fy, nm, dv, T)
            items = sum(g(I, k, fy) for k in OPEX_ITEMS)
            if has(I, OPX_EX, fy):
                dv = items - g(I, OPX_EX, fy)
                chk(bad, fy, "C3a 费用项和=营业费用合计(不含成本)", dv, T)
                base = g(I, GP, fy) if has(I, GP, fy) else g(I, R, fy) - g(I, COST, fy)
                dv = base - g(I, OPX_EX, fy) - g(I, OI, fy)
                chk(bad, fy, "C3b 毛利−营业费用=营业利润", dv, T)
            elif has(I, OPX_IN, fy):
                dv = g(I, COST, fy) + items - g(I, OPX_IN, fy)
                chk(bad, fy, "C3c 成本+费用项=成本及费用合计", dv, T)
                dv = g(I, R, fy) - g(I, OPX_IN, fy) - g(I, OI, fy)
                chk(bad, fy, "C3d 营收−成本及费用=营业利润", dv, T)
            else:
                dv = g(I, R, fy) - g(I, COST, fy) - items - g(I, OI, fy)
                chk(bad, fy, "C3e 营收−成本−费用项=营业利润(无合计行)", dv, T)
            dv = g(I, OI, fy) + sum(g(I, k, fy) for k in NONOP_ITEMS) - g(I, PBT, fy)
            chk(bad, fy, "C4 营业利润+营业外=税前", dv, T)
            base = BEF if has(I, BEF, fy) else NI
            dv = g(I, PBT, fy) - g(I, TAX, fy) - g(I, base, fy)
            chk(bad, fy, f"C5 税前−所得税={base[:5]}", dv, T)
            if has(I, BEF, fy):
                dv = g(I, BEF, fy) + g(I, CUM, fy) - g(I, NI, fy)
                chk(bad, fy, "C5b 变更前+累积影响=净利", dv, T)
            # C6 EPS 自洽（单位与拆股基准的守门人）
            for eps_row, sh_row in (("基本EPS(as-reported·拆股基准随年变) Basic EPS", "基本股数(百万股·as-reported) Basic shares"),
                                    ("每股收益(SFAS128前·primary·as-reported) Net income per share (primary)",
                                     "加权股数(SFAS128前·含等价物·百万股) Average shares (primary)")):
                e, s = g(I, eps_row, fy), g(I, sh_row, fy)
                # 分子：有优先股股息的年份（FY1997-2000）EPS 按「归属普通股净利」算
                num = g(I, NI, fy) - g(I, "优先股股息(仅FY1997-2000) Preferred stock dividends", fy)
                if e and s and num:
                    chk(bad, fy, f"C6 净利÷股数≈EPS({eps_row[:4]})", num / s / e - 1, 0.03)
        # ── 资产负债表 ──
        TA, TCA, TCL, TE = "总资产 Total assets", "流动资产合计 Total current assets", \
            "流动负债合计 Total current liabilities", "股东权益合计 Total stockholders' equity"
        if has(B, TA, fy):
            T = tol_for(fy)
            cash_tot = "现金及短期投资合计 Cash, cash equivalents, and short-term investments"
            cash_part = (g(B, cash_tot, fy) if has(B, cash_tot, fy)
                         else g(B, "现金及现金等价物 Cash and cash equivalents", fy) + g(B, "短期投资 Short-term investments", fy))
            if has(B, cash_tot, fy) and has(B, "现金及现金等价物 Cash and cash equivalents", fy) \
                    and has(B, "短期投资 Short-term investments", fy):
                dv = g(B, "现金及现金等价物 Cash and cash equivalents", fy) + g(B, "短期投资 Short-term investments", fy) - g(B, cash_tot, fy)
                chk(bad, fy, "B0 现金+短投=合计", dv, T)
            dv = (cash_part + g(B, "应收账款净额 Accounts receivable, net", fy) + g(B, "存货 Inventories", fy)
                  + g(B, "递延所得税资产(流动) Deferred income taxes (current)", fy)
                  + g(B, "其他流动资产 Other current assets", fy) - g(B, TCA, fy))
            chk(bad, fy, "B1 流动资产明细和", dv, T)
            nca = ["固定资产净额 Property and equipment, net", "经营租赁使用权资产 Operating lease right-of-use assets",
                   "股权及其他投资 Equity (and other) investments", "商誉 Goodwill", "无形资产净额 Intangible assets, net",
                   "知识产权(仅FY1988) Intellectual property rights, net",
                   "递延所得税资产(非流动) Deferred income taxes (non-current asset)", "其他长期资产 Other long-term assets"]
            dv = g(B, TCA, fy) + sum(g(B, k, fy) for k in nca) - g(B, TA, fy)
            chk(bad, fy, "B2 资产分项和=总资产", dv, T)
            cl = ["应付账款 Accounts payable", "短期借款/商业票据 Short-term debt", "应付票据(仅FY1987-1992) Notes payable",
                  "一年内到期长期债务 Current portion of long-term debt", "应付薪酬 Accrued compensation",
                  "客户押金(及递延收入·仅FY1984-1992) Customer deposits",
                  "应付版税及佣金(仅FY1984-1987) Royalties and commissions payable",
                  "递延所得税负债(流动·仅招股书期) Deferred income taxes (current liability)",
                  "应交所得税(流动) Income taxes payable (current)", "短期递延收入 Short-term unearned revenue",
                  "证券借贷应付款 Securities lending payable", "其他流动负债 Other current liabilities"]
            dv = sum(g(B, k, fy) for k in cl) - g(B, TCL, fy)
            chk(bad, fy, "B3 流动负债明细和", dv, T)
            ncl = ["长期债务 Long-term debt", "资本租赁义务(仅FY1986-1987) Capital lease obligations",
                   "长期应交所得税 Long-term income taxes", "长期递延收入 Long-term unearned revenue",
                   "递延所得税负债(非流动) Deferred income taxes (non-current liability)",
                   "经营租赁负债(非流动) Operating lease liabilities", "其他长期负债 Other long-term liabilities"]
            tl = g(B, TCL, fy) + sum(g(B, k, fy) for k in ncl)
            if has(B, "负债合计 Total liabilities", fy):
                dv = tl - g(B, "负债合计 Total liabilities", fy)
                chk(bad, fy, "B4a 负债分项和=负债合计", dv, T)
            mezz = g(B, "少数股东权益(仅FY1995-1997) Minority interest", fy) + g(B, "认沽权证(仅FY1995-2000) Put warrants", fy)
            dv = tl + mezz + g(B, TE, fy) - g(B, TA, fy)
            chk(bad, fy, "B4 负债+权益=总资产", dv, T)
            eq = ["可转换优先股(仅FY1984-1986·FY1997-1999) Convertible preferred stock",
                  "普通股及资本公积 Common stock and paid-in capital", "普通股面值(仅FY1984-1989) Common stock",
                  "资本公积(仅FY1984-1989) Paid-in capital", "留存收益 Retained earnings (deficit)",
                  "累计其他综合收益 Accumulated other comprehensive income (loss)",
                  "外币折算调整(仅FY1984-1989) Translation adjustment"]
            dv = sum(g(B, k, fy) for k in eq) - g(B, TE, fy)
            chk(bad, fy, "B5 权益明细和", dv, T)
            TLE = "负债和股东权益合计 Total liabilities and stockholders' equity"
            if has(B, TLE, fy):
                chk(bad, fy, "B6 两侧合计相等", g(B, TA, fy) - g(B, TLE, fy), T)
        # ── 现金流量表 ──
        OP, INVN, FINN = "经营活动现金流净额 Net cash from operations", \
            "投资活动现金流净额 Net cash from (used in) investing", "融资活动现金流净额 Net cash from (used in) financing"
        NET, BEG, END, FX = "现金净变动 Net change in cash and cash equivalents", \
            "期初现金 Cash and cash equivalents, beginning of period", \
            "期末现金 Cash and cash equivalents, end of period", "汇率影响 Effect of exchange rates"
        if has(C, OP, fy):
            T = tol_for(fy)
            names = [c[0] for c in CF_CONCEPTS]
            i_op, i_fin, i_inv = names.index(OP), names.index(FINN), names.index(INVN)
            op_items = names[1:i_op]
            dv = g(C, "净利润 Net income", fy) + sum(g(C, k, fy) for k in op_items) - g(C, OP, fy)
            chk(bad, fy, "F0 经营明细和=经营净额", dv, T)
            dv = sum(g(C, k, fy) for k in names[i_op + 1:i_fin]) - g(C, FINN, fy)
            chk(bad, fy, "F0b 融资明细和=融资净额", dv, T)
            dv = sum(g(C, k, fy) for k in names[i_fin + 1:i_inv]) - g(C, INVN, fy)
            chk(bad, fy, "F0c 投资明细和=投资净额", dv, T)
            s3 = g(C, OP, fy) + g(C, INVN, fy) + g(C, FINN, fy)
            if has(C, NET, fy):
                ok_ex = abs(s3 - g(C, NET, fy)) <= T                     # 净变动不含汇率（老版式）
                ok_in = abs(s3 + g(C, FX, fy) - g(C, NET, fy)) <= T      # 净变动含汇率（新版式）
                chk(bad, fy, "F1 经营+投资+融资(+汇率)=净变动",
                    0.0 if (ok_ex or ok_in) else s3 + g(C, FX, fy) - g(C, NET, fy), T)
                fx_add = g(C, FX, fy) if (ok_ex and not ok_in) else 0.0
                dv = g(C, BEG, fy) + g(C, NET, fy) + fx_add - g(C, END, fy)
                chk(bad, fy, "F2 期初+净变动(+汇率)=期末", dv, T)
            else:
                dv = g(C, BEG, fy) + s3 + g(C, FX, fy) - g(C, END, fy)
                chk(bad, fy, "F2' 期初+三项+汇率=期末", dv, T)
            if has(I, NI, fy) and has(C, "净利润 Net income", fy):
                chk(bad, fy, "F3 CF净利=IS净利", g(C, "净利润 Net income", fy) - g(I, NI, fy), T)
            if has(B, "现金及现金等价物 Cash and cash equivalents", fy) and fy not in RESTRICTED_CASH_YEARS:
                dv = g(C, END, fy) - g(B, "现金及现金等价物 Cash and cash equivalents", fy)
                chk(bad, fy, "F4 期末现金=BS现金", dv, T)
    return bad


# 若某年起现金流量表口径含受限现金（ASU 2016-18），F4 不适用——Microsoft 至今未在报表单列受限现金，留空集
RESTRICTED_CASH_YEARS = set()


# ── 写出 ────────────────────────────────────────────────────────────────────
HEADER_NOTE = {
    "IS": "单位: 百万美元(US$ mn)，EPS 为美元/股、股数为百万股 | 财年截至 6 月 30 日 | as-reported(各财年取自家年报当年列；"
          "FY1982-1985 取招股书) | 费用为正、营业外按印刷符号 | 千美元来源年份保留 3 位小数 | "
          "EPS/股数是该次申报的拆股基准、不可跨年直接比(见 财务比率.csv 复权列) | 空=该期财报无此科目",
    "BS": "单位: 百万美元(US$ mn) | 时点 = 财年末 6 月 30 日 | as-reported(FY1984-1985 取招股书) | "
          "FY1989-2008 资产负债表只印「现金及短期投资」合并行——拆分取现金流量表期末现金 | 空=该期财报无此科目",
    "CF": "单位: 百万美元(US$ mn) | 财年全年 | 流出为负 | as-reported(FY1987-1988 取 FY1989 年报按 SFAS 95 重编的比较列；"
          "更早年份无现金流量表、见 营运资本变动表FY1983-1988.csv) | 空=该期财报无此科目",
}
FILE = {"IS": "利润表.csv", "BS": "资产负债表.csv", "CF": "现金流量表.csv"}


def fmt(v, kind=M):
    if v is None:
        return ""
    if kind == PS:
        return f"{v:.2f}"
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return s


def write_csv(key, data, origin):
    years = [y for y in ALL_FY if any(data[c[0]].get(y) is not None for c in SPEC[key])]
    path = os.path.join(HERE, FILE[key])
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"# {HEADER_NOTE[key]}"])
        w.writerow(["科目"] + [f"FY{y}" for y in years])
        w.writerow(["数据来源"] + [origin.get(y, "") for y in years])
        for c in SPEC[key]:
            row = [fmt(data[c[0]].get(y), c[5]) for y in years]
            if any(row):
                w.writerow([c[0]] + row)
    print(f"  写出 {FILE[key]}（FY{years[0]}-FY{years[-1]}，{len(years)} 年）")


# ── 营运资本变动表（SFAS 95 之前·FY1983-1988）────────────────────────────────
SCFP_ROWS = [
    ("净利润 Net income", [r"^net income$"]),
    ("折旧(及摊销) Depreciation (and amortization)", [r"^depreciation"]),
    ("其他(经营段) Other (operations)", [r"^other \(operations\)$"]),
    ("经营提供营运资本合计 Total from operations", [r"^total from operations$"]),
    ("发行普通股 Common stock issued", [r"^common stock issued$"]),
    ("股票期权税收利益 Income tax benefit related to stock options", [r"^income tax benefits? related to stock options$"]),
    ("长期借款/义务 Long-term borrowings / obligations", [r"^long-term (borrowings|obligations)$"]),
    ("营运资本来源合计 Total working capital provided", [r"^total working capital provided$"]),
    ("固定资产增加(资本开支) Additions to property and equipment", [r"^additions to property"]),
    ("购入知识产权 Acquisition of intellectual property rights", [r"^acquisition of intellectual property rights$"]),
    ("偿还长期债务 Reduction of long-term debt", [r"^reduction of long-term debt$"]),
    ("股东借款净额 Loans to stockholders—net", [r"^loans to stockholders"]),
    ("购买库存股 Purchase of treasury stock", [r"^purchase of treasury stock$"]),
    ("外币折算调整 Translation adjustment", [r"^translation adjustment$"]),
    ("其他(运用段) Other (used)", [r"^other \(used\)$"]),
    ("营运资本运用合计 Total working capital used", [r"^total working capital used$"]),
    ("营运资本增加 Increase in working capital", [r"^increase in working capital$"]),
    ("Δ现金及短期投资 Cash and short-term investments", [r"^δ cash and short-term investments$"]),
    ("Δ应收账款 Accounts receivable", [r"^δ (trade )?accounts receivable$"]),
    ("Δ存货 Inventories", [r"^δ inventories$"]),
    ("Δ其他流动资产 Other current assets", [r"^δ other current assets$"]),
    ("Δ流动负债(增加为负) Current liabilities—(increase) decrease", [r"^δ current liabilities"]),
    ("  其中Δ应付账款 Accounts payable", [r"^δ accounts payable"]),
    ("  其中Δ应付票据 Notes payable", [r"^δ notes payable"]),
    ("  其中Δ应交所得税 Income taxes payable", [r"^δ income taxes payable"]),
    ("  其中Δ其他流动负债 Other current liabilities", [r"^δ other current liabilities"]),
]
SCFP_SRC = {1983: "prospectus", 1984: "prospectus", 1985: "prospectus", 1986: "1986", 1987: "1987", 1988: "1988"}


def build_scfp(books):
    data, origin, bad = {}, {}, []
    for fy, key in SCFP_SRC.items():
        st = books.get(("S", key), {}).get("SCFP")
        if not st or fy not in st["years"]:
            bad.append((fy, "SCFP 缺表", 0))
            continue
        i = st["years"].index(fy)
        d = {}
        for name, pats in SCFP_ROWS:
            for r in st["rows"]:
                if any(re.search(p, norm(r["label"])) for p in pats) and r["vals"][i] is not None:
                    d[name] = d.get(name, 0.0) + r["vals"][i] * st["scale"]
                    break
        data[fy] = d
        origin[fy] = "招股书自身" if key == "prospectus" else f"S{key}自身"
        T = TOL_K
        g2 = lambda k: d.get(k) or 0.0
        dv = g2("净利润 Net income") + g2("折旧(及摊销) Depreciation (and amortization)") + g2("其他(经营段) Other (operations)") \
            - g2("经营提供营运资本合计 Total from operations")
        chk(bad, fy, "W1 净利+折旧+其他=经营提供", dv, T)
        prov = ["经营提供营运资本合计 Total from operations", "发行普通股 Common stock issued",
                "股票期权税收利益 Income tax benefit related to stock options", "长期借款/义务 Long-term borrowings / obligations"]
        dv = sum(g2(k) for k in prov) - g2("营运资本来源合计 Total working capital provided")
        chk(bad, fy, "W2 来源合计", dv, T)
        used = ["固定资产增加(资本开支) Additions to property and equipment", "购入知识产权 Acquisition of intellectual property rights",
                "偿还长期债务 Reduction of long-term debt", "股东借款净额 Loans to stockholders—net",
                "购买库存股 Purchase of treasury stock", "外币折算调整 Translation adjustment", "其他(运用段) Other (used)"]
        dv = sum(g2(k) for k in used) - g2("营运资本运用合计 Total working capital used")
        chk(bad, fy, "W3 运用合计", dv, T)
        dv = g2("营运资本来源合计 Total working capital provided") - g2("营运资本运用合计 Total working capital used") \
            - g2("营运资本增加 Increase in working capital")
        chk(bad, fy, "W4 来源−运用=增加", dv, T)
        elem = ["Δ现金及短期投资 Cash and short-term investments", "Δ应收账款 Accounts receivable", "Δ存货 Inventories",
                "Δ其他流动资产 Other current assets", "Δ流动负债(增加为负) Current liabilities—(increase) decrease",
                "  其中Δ应付账款 Accounts payable", "  其中Δ应付票据 Notes payable",
                "  其中Δ应交所得税 Income taxes payable", "  其中Δ其他流动负债 Other current liabilities"]
        dv = sum(g2(k) for k in elem) - g2("营运资本增加 Increase in working capital")
        chk(bad, fy, "W5 要素变动和=增加", dv, T)
    return data, origin, bad


def write_scfp(data, origin):
    years = sorted(data)
    path = os.path.join(HERE, "营运资本变动表FY1983-1988.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# 单位: 百万美元(千美元来源·保留 3 位小数) | Statements of Changes in Financial Position（营运资本口径·"
                    "SFAS 95 之前）| ⚠️ 不是现金流量表：「经营提供」= 净利+折旧(营运资本口径)、不扣营运资本占用 | "
                    "FY1983-1985 取招股书、FY1986-1988 取各自年报 | 资本开支一行可与 现金流量表.csv 的资本开支衔接(口径近似)"])
        w.writerow(["科目"] + [f"FY{y}" for y in years])
        w.writerow(["数据来源"] + [origin.get(y, "") for y in years])
        for name, _ in SCFP_ROWS:
            row = [fmt(data[y].get(name)) for y in years]
            if any(row):
                w.writerow([name] + row)
    print(f"  写出 营运资本变动表FY1983-1988.csv（{len(years)} 年）")


def main():
    books = load()
    apply_errata(books)
    print("载入申报：" + ", ".join(f"{t}轨 {sum(1 for k in books if k[0] == t)}" for t in ("R", "L", "S"))
          + f" | 申报印刷错误订正 {len(ERRATA_LOG)} 处")
    built, rests = {}, []
    for key in ("IS", "BS", "CF"):
        d, o, r = build(books, key)
        built[key] = (d, o)
        rests += r
        n = sum(1 for y in ALL_FY if any(d[c[0]].get(y) is not None for c in SPEC[key]))
        print(f"{key}: 覆盖 {n} 个财年，跨申报同值确认 {XMATCH[key]} 格，重述/口径差异 {len(r)} 处")
    scfp, scfp_o, scfp_bad = build_scfp(books)

    bad = check_required(built) + check(built["IS"][0], built["BS"][0], built["CF"][0]) + scfp_bad
    # 覆盖闸：每个有数据的财年，核心勾稽都必须**真的执行过**——「0 条不通过」在没跑的时候最容易成立
    from collections import Counter
    cnt = Counter(code for _, code in RUN)
    print(f"执行勾稽 {len(RUN)} 次：" + " ".join(f"{k}×{v}" for k, v in sorted(cnt.items())))
    core = {"IS": ["C4", "C5"], "BS": ["B1", "B2", "B3", "B4", "B5"], "CF": ["F0", "F0b", "F0c", "F3"]}
    ran = set(RUN)
    for key, codes in core.items():
        d = built[key][0]
        yrs = [y for y in ALL_FY if any(d[c[0]].get(y) is not None for c in SPEC[key])]
        for y in yrs:
            for c in codes:
                if (y, c) not in ran:
                    bad.append((y, f"覆盖闸 {key} 核心勾稽 {c} 未执行", 0))
        print(f"  {key} 核心勾稽 {'/'.join(codes)} 覆盖 FY{yrs[0]}-FY{yrs[-1]} 共 {len(yrs)} 年")
    if bad:
        print(f"\n🔴 勾稽未过 {len(bad)} 条（不写出 CSV）：")
        for fy, nm, dv in bad[:150]:
            print(f"  FY{fy} {nm}: 差 {dv}")
        if "--force" not in sys.argv:
            sys.exit(1)
    else:
        print("\n✅ 勾稽全过")
    for key in ("IS", "BS", "CF"):
        write_csv(key, *built[key])
    write_scfp(scfp, scfp_o)
    rp = os.path.join(HERE, "重述与口径变更.csv")
    with open(rp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# 同一财年 as-reported 值 vs 其他申报所印值的差异（金额单位: 百万美元）。差异来源 = 重述 / 重分类 / "
                    "会计准则追溯调整 / 拆股基准变化，不是解析错——本库一律以 as-reported 为准，本表仅供追溯。"])
        w.writerow(["表", "科目", "财年", "as-reported值", "其他申报值", "来源申报", "差额"])
        for r in sorted(rests, key=lambda x: (x[2], x[0], x[1], x[5])):
            w.writerow(r)
        w.writerow([])
        w.writerow(["# 申报自身印刷错误（已在构建时订正，订正依据见末列）"])
        w.writerow(["表", "印刷标签", "财年", "印刷值", "订正值", "申报", "证据"])
        for r in ERRATA_LOG:
            w.writerow(r)
    print(f"  写出 重述与口径变更.csv（{len(rests)} 条 + 印刷错误订正 {len(ERRATA_LOG)} 条）")


if __name__ == "__main__":
    main()
