#!/usr/bin/env python3
"""NVIDIA 三表构建器：三条数据轨合成 `利润表.csv` / `资产负债表.csv` / `现金流量表.csv` /
`过渡期-1998年1月.csv` / `重述与口径变更.csv`，**勾稽不过不写出**。

## 三条数据轨

| 轨 | 覆盖 | 载体 | 归一方式 | 采集器 |
|---|---|---|---|---|
| R 轨 | FY2012-2026（含比较列 FY2010-2011） | 各年 10-K 的 R*.htm | **只按 XBRL tag**（同 tag 多行者再按标签消歧） | `_harvest_rfiles.py` |
| L 轨 | FY1999-2011（含比较列 1996-1998-01） + FY2006 10-K/A | 10-K 正文 txt / htm | **只按标签正则** | `_parse_legacy.py` |
| P 轨 | 1993-1997 + 1998-01 过渡月（上市前） | 1999-01-21 定稿招股书 424B4 | **只按标签正则** | `_parse_legacy.py` |

## 口径声明（取数当场固定，事后查不出来）

- **期间**：年度列全部为**财年全年**。FY1993-FY1997 财年 = 日历年（截至 12-31；FY1993 = 1993-04-05 成立起）；
  **1998-01 是一个月的过渡期**（公司把财年截止日改到 1 月最后一个周日），**不存在完整 FY1998**；
  FY1999 起为 52/53 周财年（FY2026 = 2025-01-27 ~ 2026-01-25）。过渡月单列 `过渡期-1998年1月.csv`，
  不进年度三表（`scripts/derived.py` 按位置读列，表头里放非年份列会让整行左移）。
- **主体**：合并口径（FY2001 起「NVIDIA Corporation and Subsidiaries」）。**无少数股东权益**，净利 = 归母净利。
  美股无「扣非」法定口径，本库不造扣非行；一次性项目（收购终止费用 / 诉讼和解 / 重组 / 期权置换 / 在研技术…）各自单列。
- **来源年份**：每个财年取**该财年自己那份年报的当年列**（as-reported）。例外只有上市前（FY1993-1997 + 过渡月）取招股书。
  后续年报的比较列与 FY2006 10-K/A 重述值一律只进 `重述与口径变更.csv`。
- **单位**：**百万美元**。按各表**自陈单位**换算（千美元来源保留 3 位小数）。
- **符号**：利润表费用为正、营业外按印刷符号（收益为正、费用为负）；现金流量表流出为负。
- **每股数据不可跨年直接比**：各年 EPS / 股数按**该次申报时点**的股本基准（拆股多次，见 `财务比率.csv` 复权行）。
"""
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RDIR = os.path.join(HERE, "_rfiles")
LDIR = os.path.join(HERE, "_legacy")

PRE = ["1993", "1994", "1995", "1996", "1997"]
YEARS = PRE + [str(y) for y in range(1999, 2027)]        # 年度列（无 1998）
TRANS = "1998-01"
RYEARS = [str(y) for y in range(2012, 2027)]
LKEYS = [str(y) for y in range(1999, 2012)] + ["2006A"]

M, PS, SH = "money", "pershare", "shares"
EPS0 = 1e-6          # 默认容差 = 0（浮点噪声级）；需要放宽的地方逐条写明（见 TOL_OVERRIDE）

# ── 概念定义 ────────────────────────────────────────────────────────────────
# (CSV 行名, [XBRL tag（~开头为正则）], [L/P 轨标签正则], [R 轨同 tag 多行消歧标签正则], 求和?, 量纲, 窗口)
OPEX = ("between", r"^operating expenses:?$", r"^total operating expenses$")
NONOP = ("between", r"^(operating income( \(loss\))?|income( \(loss\))? from operations)$",
         r"^income( \(loss\))? before")

IS_CONCEPTS = [
    ("营业收入 Revenue",
     ["us-gaap_Revenues", "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap_SalesRevenueNet"],
     [r"^total revenues?$", r"^revenues?$"], [], False, M, None),
    ("  产品收入(仅FY1995-2001) Product revenue", [], [r"^product$"], [], False, M, None),
    ("  授权费收入(仅FY1995-1999) Royalty revenue", [], [r"^royalty$"], [], False, M, None),
    ("营业成本 Cost of revenue", ["us-gaap_CostOfRevenue", "us-gaap_CostOfGoodsAndServicesSold"],
     [r"^cost of revenues?$"], [], False, M, None),
    ("期权置换相关营业成本(仅FY2003) Cost of revenue related to stock option exchange", [],
     [r"^cost of revenue related to stock option exchange"], [], False, M, None),
    ("毛利 Gross profit", ["us-gaap_GrossProfit"], [r"^gross profit( \(loss\))?$"], [], False, M, None),
    ("研发费用 Research and development", ["us-gaap_ResearchAndDevelopmentExpense"],
     [r"^research and development$"], [], False, M, OPEX),
    ("销售、一般及管理费用 Sales, general and administrative", ["us-gaap_SellingGeneralAndAdministrativeExpense"],
     [r"^sales, general and? administrative$"], [], False, M, OPEX),
    ("商誉及购入无形资产摊销(仅FY2002) Amortization of goodwill and purchased intangible assets", [],
     [r"^amortization of goodwill( and purchased intangible assets)?$"], [], False, M, OPEX),
    ("收购相关费用(仅FY2002) Acquisition related charges", [], [r"^acquisition related charges$"], [], False, M, OPEX),
    ("停用物业(仅FY2002) Discontinued use of property", [], [r"^discontinued use of property$"], [], False, M, OPEX),
    ("期权置换费用(仅FY2003) Stock option exchange", [], [r"^stock option exchange"], [], False, M, OPEX),
    ("购入在研技术 In-process research and development", ["us-gaap_ResearchAndDevelopmentInProcess"],
     [r"^in-process research and development$"], [], False, M, OPEX),
    ("和解费用(仅FY2006) Settlement costs", [], [r"^settlement costs$"], [], False, M, OPEX),
    ("重组及其他费用 Restructuring charges and other", ["us-gaap_RestructuringCharges"],
     [r"^restructuring charges and other$"], [], False, M, OPEX),
    ("诉讼和解 Legal settlement", ["us-gaap_LitigationSettlementGross"], [r"^legal settlement$"], [], False, M, OPEX),
    ("收购终止费用(仅FY2023) Acquisition termination cost", ["nvda_BusinessCombinationAdvancedConsiderationWrittenOff"],
     [], [], False, M, None),
    ("营业费用合计 Total operating expenses", ["us-gaap_OperatingExpenses"], [r"^total operating expenses$"],
     [], False, M, None),
    ("营业利润 Operating income", ["us-gaap_OperatingIncomeLoss"],
     [r"^operating income( \(loss\))?$", r"^income( \(loss\))? from operations$"], [], False, M, None),
    ("利息收入 Interest income", ["us-gaap_InvestmentIncomeInterest"], [r"^interest income$"], [], False, M, NONOP),
    ("利息费用 Interest expense", ["us-gaap_InterestExpense", "us-gaap_InterestExpenseNonoperating"],
     [r"^interest expense$"], [], False, M, NONOP),
    ("其他营业外净额 Other, net", ["us-gaap_OtherNonoperatingIncomeExpense"],
     [r"^other, net$", r"^other income \(expense\), net$", r"^other (income|expense), net$"], [], False, M, NONOP),
    ("可转债赎回费用(仅FY2004) Convertible debenture redemption expense", [],
     [r"^convertible debenture redemption expense$"], [], False, M, NONOP),
    ("利息及其他净额(单行版式·FY1993-2000/FY2003) Interest and other income (expense), net", [],
     [r"^interest and other income( \(expense\))?, net$"], [], False, M, NONOP),
    ("营业外收支合计(FY2016起印刷) Total other income (expense)", ["us-gaap_NonoperatingIncomeExpense"],
     [], [], False, M, None),
    ("税前利润 Income before income tax",
     ["~^us-gaap_IncomeLossFromContinuingOperationsBeforeIncomeTaxes"],
     [r"^income( \(loss\))? before (income )?tax"], [], False, M, None),
    ("所得税 Income tax expense (benefit)", ["us-gaap_IncomeTaxExpenseBenefit"],
     [r"^income tax(es| expense)( \(benefit\))?$"], [], False, M, None),
    ("会计原则变更前利润(FY2007-2009版式) Income before change in accounting principle", [],
     [r"^income( \(loss\))? before change in accounting principle$"], [], False, M,
     ("before", r"^net income( \(loss\))?$")),
    ("会计原则变更累积影响(仅FY2007) Cumulative effect of change in accounting principle", [],
     [r"^cumulative effect of change in accounting principle, net of tax$"], [], False, M,
     ("before", r"^net income( \(loss\))?$")),
    ("净利润 Net income", ["us-gaap_NetIncomeLoss"], [r"^net income( \(loss\))?$"], [], False, M, None),
    ("基本EPS(as-reported·拆股基准随年变) Basic EPS", ["us-gaap_EarningsPerShareBasic"],
     [r"^basic net income( \(loss\))? per share"], [], False, PS, None),
    ("摊薄EPS(as-reported·拆股基准随年变) Diluted EPS", ["us-gaap_EarningsPerShareDiluted"],
     [r"^diluted net income( \(loss\))? per share"], [], False, PS, None),
    ("基本股数(百万股·as-reported) Basic shares", ["us-gaap_WeightedAverageNumberOfSharesOutstandingBasic"],
     [r"^(weighted average )?shares used in basic per share computation"], [], False, SH, None),
    ("摊薄股数(百万股·as-reported) Diluted shares", ["us-gaap_WeightedAverageNumberOfDilutedSharesOutstanding"],
     [r"^(weighted average )?shares used in diluted per share computation"], [], False, SH, None),
    ("每股股息(as-reported) Cash dividends per share",
     ["us-gaap_CommonStockDividendsPerShareDeclared", "us-gaap_CommonStockDividendsPerShareCashPaid"],
     [], [], False, PS, None),
]

# FY2008 10-K 印「Current assets :」（冒号前有空格）——第一版锚不上，流动递延所得税整格漏取（B1 抓出）
CA = ("between", r"^current assets\s*:?$", r"^total current assets$")
NCA = ("between", r"^total current assets$", r"^total assets")
CL = ("between", r"^current liabilities\s*:?$", r"^total current liabilities$")
NCL = ("between", r"^total current liabilities$", r"^(total liabilities$|commitments|stockholders|shareholders)")
EQ = ("after", r"^(stockholders|shareholders)'? equity:?$|^commitments and contingencies")

BS_CONCEPTS = [
    ("现金及现金等价物 Cash and cash equivalents", ["us-gaap_CashAndCashEquivalentsAtCarryingValue"],
     [r"^cash and cash equivalents$"], [], False, M, None),
    ("受限现金(仅FY2001-2003) Restricted cash", [], [r"^restricted cash$"], [], False, M, CA),
    # FY2026 改用自定义 tag（含上市权益证券）；FY2027 起季报拆「债券 / 权益」两行——口径见 README
    ("有价证券 Marketable securities",
     ["us-gaap_MarketableSecuritiesCurrent", "nvda_MarketableSecuritiesAndEquitySecuritiesFVNI"],
     [r"^marketable securities$"], [], False, M, None),
    # FY2027 起 10-Q 把有价证券拆成「债券 / 上市权益」两行（年度序列 FY2026 及以前不出现）
    ("有价债券(FY2027起季报单列) Marketable debt securities", ["us-gaap_DebtSecuritiesCurrent"], [], [], False, M, None),
    ("上市权益证券(FY2027起季报单列) Marketable equity securities", ["us-gaap_EquitySecuritiesFvNi"], [], [], False, M, None),
    ("应收账款净额 Accounts receivable, net", ["us-gaap_AccountsReceivableNetCurrent"],
     [r"^accounts receivable"], [], False, M, None),
    ("存货 Inventories", ["us-gaap_InventoryNet"], [r"^inventor(y|ies)$"], [], False, M, None),
    ("预付及递延所得税(仅FY2002-2003) Prepaid and deferred taxes", [], [r"^prepaid and deferred taxes$"],
     [], False, M, CA),
    ("递延所得税资产(流动·FY2004-2016) Deferred income taxes (current)", ["us-gaap_DeferredTaxAssetsNetCurrent"],
     [r"^deferred income taxes$"], [], False, M, CA),
    ("预付及其他流动资产 Prepaid expenses and other current assets", ["us-gaap_PrepaidExpenseAndOtherAssetsCurrent"],
     [r"^prepaid expenses and other( current assets)?$"], [], False, M, None),
    ("流动资产合计 Total current assets", ["us-gaap_AssetsCurrent"], [r"^total current assets$"], [], False, M, None),
    ("固定资产净额 Property and equipment, net", ["us-gaap_PropertyPlantAndEquipmentNet"],
     [r"^property and equipment, net$"], [], False, M, None),
    ("经营租赁资产(FY2020起) Operating lease assets", ["us-gaap_OperatingLeaseRightOfUseAsset"], [], [], False, M, None),
    ("商誉 Goodwill", ["us-gaap_Goodwill"], [r"^goodwill$"], [], False, M, None),
    ("商誉及无形资产净额(仅FY2002合并列示) Goodwill and intangible assets, net", [],
     [r"^goodwill and intangible assets, net$"], [], False, M, None),
    ("无形资产净额 Intangible assets, net", ["us-gaap_IntangibleAssetsNetExcludingGoodwill"],
     [r"^intangible assets, net$"], [], False, M, None),
    ("递延所得税资产(非流动) Deferred income tax assets",
     ["us-gaap_DeferredTaxAssetsGrossNoncurrent", "us-gaap_DeferredIncomeTaxAssetsNet"],
     [r"^deferred income taxes$"], [], False, M, NCA),
    ("预付及递延所得税-非流动(仅FY2002-2003) Prepaid and deferred taxes (noncurrent)", [],
     [r"^prepaid and deferred taxes$"], [], False, M, NCA),
    ("非上市权益证券(FY2026起单列) Non-marketable equity securities",
     ["us-gaap_EquitySecuritiesFVNINoncurrent", "nvda_NonMarketableSecurities"], [], [], False, M, None),
    ("其他资产 Other assets", ["us-gaap_OtherAssetsNoncurrent"], [r"^deposits and other assets$", r"^other assets$"],
     [], False, M, None),
    ("总资产 Total assets", ["us-gaap_Assets"], [r"^total assets"], [], False, M, None),
    ("应付账款 Accounts payable", ["us-gaap_AccountsPayableCurrent"], [r"^accounts payable$"], [], False, M, None),
    ("应计及其他流动负债 Accrued and other current liabilities", ["us-gaap_AccruedLiabilitiesCurrent"],
     [r"^accrued liabilities( and other)?( current liabilities)?$", r"^accrued and other current liabilities$"],
     [], False, M, None),
    ("信贷额度借款(仅FY1999-2000) Line of credit", [], [r"^line of credit$"], [], False, M, CL),
    ("短期债务(FY2021起) Short-term debt", ["us-gaap_DebtCurrent"], [], [], False, M, None),
    ("可转债-流动(FY2016-2019) Convertible short-term debt", ["us-gaap_ConvertibleDebtCurrent"], [], [], False, M, None),
    ("应付可转债利息(仅FY2002-2004) Interest payable on convertible debenture", [],
     [r"^interest payable on convertible debenture$"], [], False, M, CL),
    ("一年内到期融资租赁 Current portion of capital lease obligations", [],
     [r"^current portion of (note and )?capital lease obligations$"], [], False, M, CL),
    # 微软 Xbox 预付款：FY2001 自家 10-K 列非流动，FY2002 10-K 起（含 FY2001 比较列）改列流动负债
    ("递延收入-流动(仅FY2002-2003) Deferred revenue (current)", [], [r"^deferred revenue$"], [], False, M, CL),
    ("流动负债合计 Total current liabilities", ["us-gaap_LiabilitiesCurrent"], [r"^total current liabilities$"],
     [], False, M, None),
    ("递延收入-非流动(仅FY2001-2003) Deferred revenue", [], [r"^deferred revenue$"], [], False, M, NCL),
    ("长期应付款-专利授权(仅FY2000) Long-term payable", [], [r"^long-term payable$"], [], False, M, NCL),
    ("长期债务 Long-term debt", ["us-gaap_LongTermDebtNoncurrent", "us-gaap_LongTermDebt"],
     [r"^long-term debt$", r"^long-term convertible debenture$"], [], False, M, None),
    ("可转债-非流动(仅FY2016) Convertible long-term debt", ["us-gaap_ConvertibleDebtNoncurrent"], [], [], False, M, None),
    ("长期融资租赁 Capital lease obligations, long term", ["us-gaap_CapitalLeaseObligationsNoncurrent"],
     [r"^capital lease obligations, (less current portion|long term)"], [], False, M, None),
    ("递延所得税负债(仅FY2004-2006) Deferred income tax liabilities", [], [r"^deferred income tax liabilities$"],
     [], False, M, NCL),
    ("长期经营租赁负债(FY2020起) Long-term operating lease liabilities", ["us-gaap_OperatingLeaseLiabilityNoncurrent"],
     [], [], False, M, None),
    ("其他长期负债 Other long-term liabilities", ["us-gaap_OtherLiabilitiesNoncurrent"],
     [r"^(other )?long-term liabilities$"], [], False, M, None),
    ("负债合计(FY2016起印刷) Total liabilities", ["us-gaap_Liabilities"], [r"^total liabilities$"], [], False, M, None),
    ("可转债转换义务-夹层权益(FY2016-2018) Convertible debt conversion obligation",
     ["us-gaap_TemporaryEquityValueExcludingAdditionalPaidInCapital"], [], [], False, M, None),
    ("优先股 Preferred stock", ["us-gaap_PreferredStockValueOutstanding"],
     [r"^(convertible )?preferred stock"], [], False, M, EQ),
    ("普通股面值 Common stock", ["us-gaap_CommonStockValue"], [r"^common stock"], [], False, M, EQ),
    ("资本公积 Additional paid-in capital", ["us-gaap_AdditionalPaidInCapital"], [r"^additional paid-in capital$"],
     [], False, M, EQ),
    ("库存股 Treasury stock", ["us-gaap_TreasuryStockValue"], [r"^treasury stock"], [], False, M, EQ),
    ("递延补偿(仅FY1999-2007) Deferred compensation", [], [r"^deferred (stock-based )?compensation$"], [], False, M, EQ),
    ("其他综合收益累计 Accumulated other comprehensive income (loss)",
     ["us-gaap_AccumulatedOtherComprehensiveIncomeLossNetOfTax"],
     [r"^(accumulated )?other comprehensive (income|loss)( \(loss\))?(, net)?$"], [], False, M, EQ),
    ("留存收益(累计亏损) Retained earnings (accumulated deficit)", ["us-gaap_RetainedEarningsAccumulatedDeficit"],
     [r"^retained earnings( \(accumulated deficit\))?$", r"^accumulated deficit$"], [], False, M, EQ),
    ("股东权益合计 Total shareholders' equity", ["us-gaap_StockholdersEquity"],
     [r"^total (stockholders|shareholders)[’']? equity$"], [], False, M, None),
    ("负债及股东权益合计 Total liabilities and shareholders' equity", ["us-gaap_LiabilitiesAndStockholdersEquity"],
     [r"^total liabilities(, convertible debt conversion obligation)? and (stockholders|shareholders)[’']? equity"],
     [], False, M, None),
]

OPS = ("before", r"^net cash (provided by|used in|provided by \(used in\)|\(used in\) provided by) operating activities")
INV = ("between", r"^net cash (provided by|used in|provided by \(used in\)|\(used in\) provided by) operating activities",
       r"^net cash (provided by|used in|provided by \(used in\)|\(used in\) provided by) investing activities")
# 起锚 = 投资小计 **或** 融资段标题：FY1995-2000 投资段不印小计，只以投资小计起锚时融资窗口为空 →
# IPO 所得 / 员工股票计划所得整段取不到、被「其他融资项目」吸收（勾稽照过；累计股东回报行全 0 才现形）
FIN = ("between", r"^net cash (provided by|used in|provided by \(used in\)|\(used in\) provided by) investing activities"
                  r"|^cash flows (from|provided by|used in|provided by \(used in\)) financing activities",
       r"^net cash (provided by|used in|provided by \(used in\)|\(used in\) provided by) financing activities")

CF_CONCEPTS = [
    ("净利润 Net income", ["us-gaap_NetIncomeLoss"], [r"^net income( \(loss\))?$"], [], False, M, OPS),
    ("折旧及摊销 Depreciation and amortization",
     ["us-gaap_DepreciationDepletionAndAmortization", "us-gaap_DepreciationAndAmortization"],
     [r"^depreciation( and amortization)?$"], [], False, M, OPS),
    ("股权激励费用 Stock-based compensation", ["us-gaap_ShareBasedCompensation"],
     [r"^stock[- ]based compensation( expense)?( related to employees)?$", r"^share-based compensation$"],
     [], False, M, OPS),
    ("期权回购相关股权激励(仅FY2010) Stock-based compensation related to stock option purchase",
     ["us-gaap_StockOptionPlanExpense"], [r"^stock-based compensation expense related to stock option purchase$"],
     [], False, M, OPS),
    ("递延补偿摊销(仅FY1996-2004) Amortization of deferred compensation", [],
     [r"^amortization of deferred compensation$"], [], False, M, OPS),
    ("递延所得税 Deferred income taxes", ["us-gaap_DeferredIncomeTaxExpenseBenefit"], [r"^deferred income taxes$"],
     [], False, M, OPS),
    ("投资损益(收益为负) (Gains) losses on investments", ["us-gaap_GainLossOnInvestments"], [], [], False, M, OPS),
    ("收购终止费用(仅FY2023) Acquisition termination cost", ["nvda_BusinessCombinationAdvancedConsiderationWrittenOff"],
     [], [], False, M, OPS),
    ("应收账款变动 Change in accounts receivable", ["us-gaap_IncreaseDecreaseInAccountsReceivable"],
     [r"^accounts receivable$"], [], False, M, OPS),
    ("存货变动 Change in inventories", ["us-gaap_IncreaseDecreaseInInventories"], [r"^inventor(y|ies)$"],
     [], False, M, OPS),
    ("应付账款变动 Change in accounts payable", ["us-gaap_IncreaseDecreaseInAccountsPayable"],
     [r"^accounts payable$"], [], False, M, OPS),
    ("经营活动现金流净额 Net cash from operating activities", ["us-gaap_NetCashProvidedByUsedInOperatingActivities"],
     [OPS[1]], [], False, M, None),
    ("购买有价证券 Purchases of marketable securities",
     ["us-gaap_PaymentsToAcquireMarketableSecurities", "us-gaap_PaymentsToAcquireAvailableForSaleSecuritiesDebt",
      "nvda_PaymentsToAcquireMarketableDebtAndEquitySecurities"],
     [r"^purchases? of marketable securities$"], [], True, M, INV),
    ("有价证券出售及到期 Proceeds from sales and maturities of marketable securities",
     ["us-gaap_ProceedsFromSaleAndMaturityOfMarketableSecurities",
      "us-gaap_ProceedsFromMaturitiesPrepaymentsAndCallsOfAvailableForSaleSecurities",
      "us-gaap_ProceedsFromSaleOfAvailableForSaleSecuritiesDebt", "us-gaap_ProceedsFromSaleOfAvailableForSaleSecurities"],
     [r"^(proceeds from )?(sales and )?maturities of marketable securities$",
      r"^proceeds from sales of marketable securities$"], [], True, M, INV),
    ("资本开支(购置固定资产及无形资产) Purchases of property and equipment and intangible assets",
     ["us-gaap_PaymentsToAcquirePropertyPlantAndEquipment", "nvda_PurchasesOfPropertyAndEquipmentAndIntangibleAssets",
      "us-gaap_PaymentsToAcquireProductiveAssets"],
     [r"^purchases? (of|related to) property and equipment",
      r"^cash flows used in investing activities-+ purchases of property and equipment$"], [], False, M, None),
    ("收购业务(扣除取得现金) Acquisitions, net of cash acquired", ["us-gaap_PaymentsToAcquireBusinessesNetOfCashAcquired"],
     [r"^acquisition of businesses", r"^business acquisition$", r"^purchase of certain assets from various businesses$"],
     [], True, M, INV),
    ("Groq 交易(仅FY2026单列) Groq, Inc.", ["us-gaap_PaymentsToAcquireBusinessTwoNetOfCashAcquired"], [], [], False, M, None),
    ("购买非上市权益证券(FY2025起单列) Purchases of non-marketable equity securities",
     ["us-gaap_PaymentsToAcquireEquitySecuritiesFvNi"], [], [], False, M, None),
    ("投资活动现金流净额 Net cash from investing activities", ["us-gaap_NetCashProvidedByUsedInInvestingActivities"],
     [INV[2]], [], False, M, None),
    ("员工股票计划所得 Proceeds related to employee stock plans",
     ["us-gaap_ProceedsFromStockOptionsExercised", "nvda_Netproceedspaymentsrelatedtoemployeestockplans",
      "us-gaap_ProceedsFromStockPlans"],
     [r"^(proceeds from issuance of )?common stock (issued )?under (employee )?stock (option )?plans$"],
     [], False, M, FIN),
    ("回购普通股 Repurchases of common stock", ["us-gaap_PaymentsForRepurchaseOfCommonStock"],
     [r"^payments (for|related to) (stock )?repurchases?( of common stock)?$", r"^stock repurchase$"],
     [], False, M, FIN),
    ("RSU 代扣个税 Payments related to employee stock plan taxes",
     ["us-gaap_PaymentsRelatedToTaxWithholdingForShareBasedCompensation"], [], [], False, M, None),
    ("支付股息 Dividends paid", ["us-gaap_PaymentsOfDividends"], [], [], False, M, None),
    ("发债所得 Proceeds from issuance of debt", ["us-gaap_ProceedsFromDebtNetOfIssuanceCosts", "us-gaap_ProceedsFromConvertibleDebt"],
     [r"^convertible (notes|debenture)[-,]? ?net of issuance costs$"], [], False, M, FIN),
    ("偿还债务 Repayment of debt", ["us-gaap_RepaymentsOfDebt", "us-gaap_RepaymentsOfConvertibleDebt"],
     [r"^redemption of convertible debenture$"], [], False, M, FIN),
    ("公开发行股票所得(仅FY1999-2003) Sale of common stock under public offering", [],
     [r"^sale of common stock under public offering", r"^net proceeds from sale of common stock$"], [], False, M, FIN),
    ("融资活动现金流净额 Net cash from financing activities", ["us-gaap_NetCashProvidedByUsedInFinancingActivities"],
     [FIN[2]], [], False, M, None),
    ("现金净变动 Change in cash and cash equivalents",
     ["us-gaap_CashAndCashEquivalentsPeriodIncreaseDecrease",
      "~^us-gaap_CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecrease"],
     [r"^change in cash and cash equivalents$"], [], False, M, None),
    ("期初现金 Cash and cash equivalents at beginning of period", [],
     [r"^cash and cash equivalents at beginning of"], [r"beginning of period"], False, M, None),
    ("期末现金 Cash and cash equivalents at end of period", [],
     [r"^cash and cash equivalents at end of"], [r"end of period"], False, M, None),
    ("支付所得税(净额) Cash paid for income taxes, net", ["us-gaap_IncomeTaxesPaidNet"],
     [r"^cash paid( \(refund\))? for (income )?taxes"], [], False, M, None),
    ("支付利息 Cash paid for interest", ["us-gaap_InterestPaidNet"], [r"^cash paid for interest$"], [], False, M, None),
]
SPEC = {"IS": IS_CONCEPTS, "BS": BS_CONCEPTS, "CF": CF_CONCEPTS}

# 现金流各段「未单列项合计」= 印刷小计 − 已单列明细（解析完整性另由 check_cf_raw 用原始行验）
CF_RESID = {
    "OPS": ("其他经营调整及营运资本(未单列项合计) Other operating items", "经营活动现金流净额 Net cash from operating activities",
            ["净利润 Net income", "折旧及摊销 Depreciation and amortization", "股权激励费用 Stock-based compensation",
             "期权回购相关股权激励(仅FY2010) Stock-based compensation related to stock option purchase",
             "递延补偿摊销(仅FY1996-2004) Amortization of deferred compensation", "递延所得税 Deferred income taxes",
             "投资损益(收益为负) (Gains) losses on investments", "收购终止费用(仅FY2023) Acquisition termination cost",
             "应收账款变动 Change in accounts receivable", "存货变动 Change in inventories",
             "应付账款变动 Change in accounts payable"]),
    "INV": ("其他投资项目(未单列项合计) Other investing items", "投资活动现金流净额 Net cash from investing activities",
            ["购买有价证券 Purchases of marketable securities",
             "有价证券出售及到期 Proceeds from sales and maturities of marketable securities",
             "资本开支(购置固定资产及无形资产) Purchases of property and equipment and intangible assets",
             "收购业务(扣除取得现金) Acquisitions, net of cash acquired", "Groq 交易(仅FY2026单列) Groq, Inc.",
             "购买非上市权益证券(FY2025起单列) Purchases of non-marketable equity securities"]),
    "FIN": ("其他融资项目(未单列项合计) Other financing items", "融资活动现金流净额 Net cash from financing activities",
            ["员工股票计划所得 Proceeds related to employee stock plans", "回购普通股 Repurchases of common stock",
             "RSU 代扣个税 Payments related to employee stock plan taxes", "支付股息 Dividends paid",
             "发债所得 Proceeds from issuance of debt", "偿还债务 Repayment of debt",
             "公开发行股票所得(仅FY1999-2003) Sale of common stock under public offering"]),
}


def norm(s):
    s = re.sub(r"\s+", " ", (s or "")).strip().lower()
    return s.replace("’", "'")


# 概念级符号约定：按性质恒为费用的行统一取负（R 轨渲染常不套 negatedLabel——FY2015 利息费用渲染成 +46,133，
# 印刷件为 (46,133)；不归一则 C4「营业利润+营业外=税前」差 2×利息）
SIGN = {"利息费用 Interest expense": "neg"}

# ── R 轨申报渲染的符号错（SEC 渲染未套用 negatedLabel）——只收「双证」的 ─────────────────
# (申报键, 表, tag, 证据)。①该申报自身的段算术只在翻号后成立（F0）；②10-K 印刷件（report/Nvidia/<年>.htm）印负数。
R_SIGN_FIX = [
    ("2015", "CF", "us-gaap_IncreaseDecreaseInOtherNoncurrentLiabilities",
     "R 文件三列渲染 +41,073 / +37,788 / −69,052，FY2015 10-K 印刷件为 (41,073) / (37,788) / 69,052——三列全部反号"
     "（整行未套 negatedLabel）；翻号后经营段原始行和 = 印刷小计 905,656（F0 差额恰为 2×41.073）"),
    ("2016", "CF", "us-gaap_IncreaseDecreaseInOtherNoncurrentLiabilities",
     "R 文件三列渲染 +97 / +41 / +38，FY2016 10-K 印刷件为 (97) / (41) / (38)；翻号后经营段原始行和 = 1,175（F0 差额恰为 2×97）"),
]
ERRATA_LOG = []


def apply_sign_fix(out):
    for key, stmt, tag, why in R_SIGN_FIX:
        st = out.get(("R", key), {}).get(stmt)
        if not st:
            raise SystemExit(f"❌ R_SIGN_FIX 目标申报不存在：R{key} {stmt}")
        hit = [r for r in st["rows"] if r.get("tag") == tag]
        if len(hit) != 1:
            raise SystemExit(f"❌ R_SIGN_FIX 目标行不唯一/不存在：R{key} {stmt} {tag}（{len(hit)} 行）")
        r = hit[0]
        if not any(v is not None and v > 0 for v in r["vals"]):
            raise SystemExit(f"❌ R_SIGN_FIX 目标行已非正数——源文件或解析器变了，先复核：R{key} {tag} {r['vals']}")
        r["vals"] = [None if v is None else -v for v in r["vals"]]
        ERRATA_LOG.append((f"R{key}", stmt, r["label"], tag, why))


# ── 读申报 ──────────────────────────────────────────────────────────────────
def load():
    out = {}
    for k in RYEARS:
        p = os.path.join(RDIR, f"{k}.json")
        if os.path.exists(p):
            out[("R", k)] = json.load(open(p))["statements"]
    apply_sign_fix(out)
    for k in LKEYS + ["prospectus", "s1"]:
        p = os.path.join(LDIR, f"{k}.json")
        if os.path.exists(p):
            out[("L" if k not in ("prospectus", "s1") else "P", k)] = json.load(open(p))["statements"]
    return out


def src_label(src, slot):
    if src[1] == "prospectus":
        return "招股书" + slot
    if src[1] == "s1":
        return "首版S-1" + slot
    return f"{src[0]}{src[1]}"


def table_scales(st, track):
    if track in ("L", "P"):
        s = st["scale"]
        return {M: s, SH: s, PS: 1.0}
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
    return {M: money, SH: shares, PS: 1.0}


def col_index(st, key, track):
    if track in ("L", "P"):
        return st["years"].index(key) if key in st["years"] else None
    for i, p in enumerate(st["periods"]):
        m = re.search(r"\b((19|20)\d\d)\b", p)
        if m and m.group(1) == key:
            if st["months"] and st["months"][i] not in (12, None):
                continue
            return i
    return None


def row_window(rows, scope):
    """把可匹配行限制在一个区间内。🔴 锚行找不到 → 空窗口，不是全表（微软实证：退回全表会抓错段）。"""
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
    if not tag:
        return False
    for t in tags:
        if t.startswith("~"):
            if re.search(t[1:], tag):
                return True
        elif tag == t:
            return True
    return False


def pick(st, c, key, track):
    name, tags, lpats, rpats, do_sum, kind, scope = c
    if not st:
        return None
    idx = col_index(st, key, track)
    if idx is None:
        return None
    sc = table_scales(st, track)
    rows = st["rows"]

    def val(row):
        v = row["vals"][idx] if idx < len(row["vals"]) else None
        if v is None:
            # L/P 轨：行存在、该列印「--」/「—」= 零（1993-1994 营收、1995-1997 所得税均如此）
            dash = row.get("dash") or []
            return 0.0 if (idx < len(dash) and dash[idx]) else None
        return v * sc[kind]

    if track == "R":
        if tags:
            hits = [r for r in rows if tag_hit(r.get("tag"), tags) and val(r) is not None]
            if rpats:
                for pat in rpats:
                    hh = [r for r in hits if re.search(pat, norm(r["label"]))]
                    if hh:
                        return sum(val(r) for r in hh) if do_sum else val(hh[0])
                return None
            if hits:
                if do_sum:
                    return sum(val(r) for r in hits)
                for t in tags:
                    for r in hits:
                        if tag_hit(r.get("tag"), [t]):
                            return val(r)
            return None
        for pat in rpats:
            hh = [r for r in rows if re.search(pat, norm(r["label"])) and val(r) is not None]
            if hh:
                return val(hh[0])
        return None
    lo, hi = row_window(rows, scope)
    win = rows[lo:hi]
    if do_sum:
        seen, tot = set(), None
        for pat in lpats:
            for r in win:
                if id(r) in seen or val(r) is None or not re.search(pat, norm(r["label"])):
                    continue
                seen.add(id(r))
                tot = (tot or 0.0) + val(r)
        return tot
    for pat in lpats:
        hh = [r for r in win if re.search(pat, norm(r["label"])) and val(r) is not None]
        if hh:
            return val(hh[0])
    return None


SLOT_STMT = {"IS": "IS", "BS": "BS", "CF": "CF", "SUM": "IS", "SUMBS": "BS"}


def extract(books, src, slot, key):
    track = src[0]
    st = books[src].get(slot)
    d = {}
    for c in SPEC[SLOT_STMT[slot]]:
        v = pick(st, c, key, track)
        if v is not None:
            if SIGN.get(c[0]) == "neg":
                v = -abs(v)
            d[c[0]] = v
    return d


# ── 来源规则 ────────────────────────────────────────────────────────────────
def own_source(books, stmt, key):
    """as-reported 来源 → (轨, 申报键, 表槽位)。上市前取招股书；其余取自家年报。"""
    P = ("P", "prospectus")
    if key == TRANS:
        return (P, stmt)
    if key in PRE:
        if stmt == "IS":
            return (P, "SUM") if key in ("1993", "1994") else (P, "IS")
        if stmt == "BS":
            return (P, "SUMBS") if key in ("1993", "1994", "1995") else (P, "BS")
        if stmt == "CF":
            return (P, "CF") if key in ("1995", "1996", "1997") else None
    for tr in ("R", "L"):
        s = (tr, key)
        if s in books and books[s].get(stmt) and col_index(books[s][stmt], key, tr) is not None:
            return (s, stmt)
    return None


XMATCH = {"IS": 0, "BS": 0, "CF": 0}
CONFIRMED = set()   # (表, 科目, 期间)：另有一份申报印出同值的格（独立印刷处二次确认）


def half_up(x, u):
    import math
    q = abs(x) / u
    r = math.floor(q + 0.5 + 1e-9) * u
    return r if x >= 0 else -r


def build(books, stmt, keys):
    data = {c[0]: {} for c in SPEC[stmt]}
    origin, rest = {}, []
    for key in keys:
        osrc = own_source(books, stmt, key)
        if not osrc:
            continue
        src, slot = osrc
        d = extract(books, src, slot, key)
        for name, v in d.items():
            data[name][key] = v
        if d:
            if src[1] == "prospectus":
                origin[key] = "招股书" + ("五年摘要" if slot in ("SUM", "SUMBS") else "报表")
            else:
                origin[key] = f"{src[0]}{src[1]}自身"
    # 重述追溯：同一期间在**别的**申报里印的值 vs as-reported
    for key in keys:
        osrc = own_source(books, stmt, key)
        if not osrc:
            continue
        u_own = table_scales(books[osrc[0]][osrc[1]], osrc[0][0])[M]
        for src in sorted(books, key=lambda k: (k[1] not in ("prospectus", "s1"), k[1], k[0])):
            for slot in ([stmt] + (["SUM"] if stmt == "IS" else ["SUMBS"] if stmt == "BS" else [])):
                if (src, slot) == osrc:
                    continue
                st = books[src].get(slot)
                if not st or col_index(st, key, src[0]) is None:
                    continue
                d = extract(books, src, slot, key)
                u_oth = table_scales(st, src[0])[M]
                for c in SPEC[stmt]:
                    name, kd = c[0], c[5]
                    a, v = data[name].get(key), d.get(name)
                    if a is None or v is None:
                        continue
                    tol = 1e-6 if kd != PS else 0.005
                    same = abs(a - v) <= tol
                    # 精度不同的两次印刷（FY2015 千美元 → FY2016 起百万）：按较粗一方的精度比（四舍五入·半数进位，
                    # 不用 Python round 的银行家舍入）
                    coarse = kd == M and u_oth > u_own and abs(half_up(a, u_oth) - v) <= tol
                    if same or coarse:
                        XMATCH[stmt] += 1
                        CONFIRMED.add((stmt, name, key))
                    else:
                        rest.append((stmt, name, key, round(a, 4), round(v, 4), src_label(src, slot), round(v - a, 4)))
    return data, origin, rest


# ── 勾稽 ────────────────────────────────────────────────────────────────────
def g(d, name, key, dflt=0.0):
    v = d.get(name, {}).get(key)
    return dflt if v is None else v


def has(d, name, key):
    return d.get(name, {}).get(key) is not None


RUN = []          # 每条被实际执行的勾稽 (键, 代码)——条数本身是指标
SKIP = []         # 因缺值未执行的勾稽 (键, 代码, 缺的项)

# 源表自身不配平之处（逐条写明出处；没有登记的一律容差 0）
TOL_OVERRIDE = {}


def chk(bad, key, code, dv, tol=None):
    t = TOL_OVERRIDE.get((key, code.split(" ")[0]), EPS0) if tol is None else tol
    RUN.append((key, code.split(" ")[0]))
    if abs(dv) > t:
        bad.append((key, code, round(dv, 4)))


REQUIRED = {
    "IS": ["营业收入 Revenue", "营业利润 Operating income", "税前利润 Income before income tax", "净利润 Net income"],
    "BS": ["现金及现金等价物 Cash and cash equivalents", "总资产 Total assets",
           "股东权益合计 Total shareholders' equity"],
    "CF": ["经营活动现金流净额 Net cash from operating activities", "投资活动现金流净额 Net cash from investing activities",
           "融资活动现金流净额 Net cash from financing activities", "期末现金 Cash and cash equivalents at end of period",
           "净利润 Net income"],
}
# 完整报表年份（有完整三表）的额外必填项；1993-1995 只有招股书摘要，不要求
FULL_IS = ["营业成本 Cost of revenue", "毛利 Gross profit", "研发费用 Research and development",
           "销售、一般及管理费用 Sales, general and administrative", "所得税 Income tax expense (benefit)",
           "基本EPS(as-reported·拆股基准随年变) Basic EPS", "摊薄EPS(as-reported·拆股基准随年变) Diluted EPS",
           "基本股数(百万股·as-reported) Basic shares"]
FULL_BS = ["流动资产合计 Total current assets", "应收账款净额 Accounts receivable, net", "存货 Inventories",
           "固定资产净额 Property and equipment, net", "应付账款 Accounts payable", "流动负债合计 Total current liabilities",
           "资本公积 Additional paid-in capital", "留存收益(累计亏损) Retained earnings (accumulated deficit)"]
FULL_CF = ["折旧及摊销 Depreciation and amortization", "资本开支(购置固定资产及无形资产) Purchases of property and equipment and intangible assets",
           "现金净变动 Change in cash and cash equivalents", "期初现金 Cash and cash equivalents at beginning of period"]


def check_required(I, B, C, keys):
    bad = []
    for stmt, d, req, full, full_from in (("IS", I, REQUIRED["IS"], FULL_IS, "1995"),
                                          ("BS", B, REQUIRED["BS"], FULL_BS, "1996"),
                                          ("CF", C, REQUIRED["CF"], FULL_CF, "1995")):
        for key in keys:
            if not any(v.get(key) is not None for v in d.values()):
                continue
            need = list(req) + (full if (key == TRANS or (key >= full_from)) else [])
            for name in need:
                if not has(d, name, key):
                    bad.append((key, f"C0 {stmt} 必填项缺失: {name[:30]}", 0))
    return bad


IS_OPEX = [c[0] for c in IS_CONCEPTS if c[6] == OPEX] + ["收购终止费用(仅FY2023) Acquisition termination cost"]
IS_NONOP = [c[0] for c in IS_CONCEPTS if c[6] == NONOP]


def check(I, B, C, keys):
    bad = []
    R_, COST, COST2, GP = "营业收入 Revenue", "营业成本 Cost of revenue", \
        "期权置换相关营业成本(仅FY2003) Cost of revenue related to stock option exchange", "毛利 Gross profit"
    OPX, OI, PBT, TAX, NI = "营业费用合计 Total operating expenses", "营业利润 Operating income", \
        "税前利润 Income before income tax", "所得税 Income tax expense (benefit)", "净利润 Net income"
    BEF = "会计原则变更前利润(FY2007-2009版式) Income before change in accounting principle"
    CUM = "会计原则变更累积影响(仅FY2007) Cumulative effect of change in accounting principle"
    TOTNON = "营业外收支合计(FY2016起印刷) Total other income (expense)"
    for k in keys:
        # —— 利润表
        if has(I, R_, k) and has(I, GP, k):
            chk(bad, k, "C1 营收−成本=毛利", g(I, R_, k) - g(I, COST, k) - g(I, COST2, k) - g(I, GP, k))
        if has(I, "  产品收入(仅FY1995-2001) Product revenue", k):
            chk(bad, k, "C1b 产品+授权费=营收", g(I, "  产品收入(仅FY1995-2001) Product revenue", k)
                + g(I, "  授权费收入(仅FY1995-1999) Royalty revenue", k) - g(I, R_, k))
        items = sum(g(I, n, k) for n in IS_OPEX)
        if has(I, OPX, k):
            chk(bad, k, "C2 费用明细和=营业费用合计", items - g(I, OPX, k))
        if has(I, GP, k) and has(I, OI, k):
            chk(bad, k, "C3 毛利−营业费用=营业利润", g(I, GP, k) - items - g(I, OI, k))
        elif has(I, R_, k) and has(I, OI, k) and has(I, OPX, k):
            chk(bad, k, "C3' 营收−营业费用合计=营业利润(摘要年份无成本行)", g(I, R_, k) - g(I, COST, k) - g(I, OPX, k)
                - g(I, OI, k))
        non = sum(g(I, n, k) for n in IS_NONOP)
        if has(I, OI, k) and has(I, PBT, k):
            chk(bad, k, "C4 营业利润+营业外=税前", g(I, OI, k) + non - g(I, PBT, k))
        if has(I, TOTNON, k):
            chk(bad, k, "C4b 营业外明细和=营业外合计", non - g(I, TOTNON, k))
        if has(I, PBT, k) and has(I, NI, k):
            if has(I, BEF, k):
                chk(bad, k, "C5 税前−所得税=变更前利润", g(I, PBT, k) - g(I, TAX, k) - g(I, BEF, k))
                chk(bad, k, "C5b 变更前利润+累积影响=净利", g(I, BEF, k) + g(I, CUM, k) - g(I, NI, k))
            else:
                chk(bad, k, "C5 税前−所得税=净利", g(I, PBT, k) - g(I, TAX, k) - g(I, NI, k))
        bsh = I.get("基本股数(百万股·as-reported) Basic shares", {}).get(k)
        beps = I.get("基本EPS(as-reported·拆股基准随年变) Basic EPS", {}).get(k)
        if bsh and beps is not None and has(I, NI, k):
            implied = g(I, NI, k) / bsh
            # EPS 印两位小数：|隐含−印刷| ≤ 0.005 + 1% 视为一致（单位 / 拆股基准的守门人，不是精度闸）
            chk(bad, k, "C6 净利÷基本股数≈基本EPS", max(0.0, abs(implied - beps) - 0.005 - abs(beps) * 0.01))
        # —— 资产负债表
        TA, TCA, TCL, TE = "总资产 Total assets", "流动资产合计 Total current assets", \
            "流动负债合计 Total current liabilities", "股东权益合计 Total shareholders' equity"
        TL, TLE, TEMP = "负债合计(FY2016起印刷) Total liabilities", \
            "负债及股东权益合计 Total liabilities and shareholders' equity", \
            "可转债转换义务-夹层权益(FY2016-2018) Convertible debt conversion obligation"
        bnames = [c[0] for c in BS_CONCEPTS]
        i_tca, i_ta, i_tcl, i_tl = bnames.index(TCA), bnames.index(TA), bnames.index(TCL), bnames.index(TL)
        i_eq0 = bnames.index("优先股 Preferred stock")
        ca_items = [n for n in bnames[:i_tca]]
        nca_items = [n for n in bnames[i_tca + 1:i_ta]]
        cl_items = [n for n in bnames[i_ta + 1:i_tcl]]
        ncl_items = [n for n in bnames[i_tcl + 1:i_tl]]
        eq_items = [n for n in bnames[i_eq0:bnames.index(TE)]]
        if has(B, TCA, k):
            chk(bad, k, "B1 流动资产明细和=合计", sum(g(B, n, k) for n in ca_items) - g(B, TCA, k))
            if has(B, TA, k):
                chk(bad, k, "B2 流动+非流动=总资产", g(B, TCA, k) + sum(g(B, n, k) for n in nca_items) - g(B, TA, k))
        if has(B, TCL, k):
            chk(bad, k, "B3 流动负债明细和=合计", sum(g(B, n, k) for n in cl_items) - g(B, TCL, k))
            tl = g(B, TCL, k) + sum(g(B, n, k) for n in ncl_items)
            if has(B, TL, k):
                chk(bad, k, "B4 流动+非流动负债=负债合计", tl - g(B, TL, k))
            if has(B, TE, k):
                chk(bad, k, "B6 负债+夹层+权益=总资产", tl + g(B, TEMP, k) + g(B, TE, k) - g(B, TA, k))
        if has(B, TE, k) and any(has(B, n, k) for n in eq_items):
            chk(bad, k, "B5 权益明细和=权益合计", sum(g(B, n, k) for n in eq_items) - g(B, TE, k))
        if has(B, TLE, k):
            chk(bad, k, "B7 负债及权益合计=总资产", g(B, TLE, k) - g(B, TA, k))
        # —— 现金流量表
        OCF, ICF, FCF = "经营活动现金流净额 Net cash from operating activities", \
            "投资活动现金流净额 Net cash from investing activities", "融资活动现金流净额 Net cash from financing activities"
        CHG, BEG, END = "现金净变动 Change in cash and cash equivalents", \
            "期初现金 Cash and cash equivalents at beginning of period", "期末现金 Cash and cash equivalents at end of period"
        if has(C, OCF, k) and has(C, CHG, k):
            chk(bad, k, "F1 经营+投资+融资=现金净变动", g(C, OCF, k) + g(C, ICF, k) + g(C, FCF, k) - g(C, CHG, k))
        if has(C, BEG, k) and has(C, END, k):
            chk(bad, k, "F2 期初+净变动=期末", g(C, BEG, k) + g(C, CHG, k) - g(C, END, k))
        if has(C, NI, k) and has(I, NI, k):
            chk(bad, k, "F3 现金流量表净利=利润表净利", g(C, NI, k) - g(I, NI, k))
        if has(C, END, k) and has(B, "现金及现金等价物 Cash and cash equivalents", k):
            chk(bad, k, "F4 期末现金=资产负债表现金", g(C, END, k) - g(B, "现金及现金等价物 Cash and cash equivalents", k))
    return bad


FIN_HEAD = r"^cash flows (from|provided by|used in|provided by \(used in\)) financing activities"


def cf_sections(rows):
    """→ {段: (起, 止(不含), 小计行号或 None)}。小计行缺失时（FY1995-2000 投资段只印「标题 + 一行购置固定资产」、
    不印小计）以下一段标题为界。"""
    def find(pat, lo):
        return next((i for i in range(lo, len(rows)) if re.search(pat, norm(rows[i]["label"]))), None)
    out = {}
    o = find(OPS[1], 0)
    if o is None:
        return out
    out["OPS"] = (0, o, o)
    i = find(INV[2], o + 1)
    if i is not None:
        out["INV"] = (o + 1, i, i)
        nxt = i + 1
    else:
        h = find(FIN_HEAD, o + 1)
        if h is None:
            return out
        out["INV"] = (o + 1, h, None)
        nxt = h
    f = find(FIN[2], nxt)
    if f is not None:
        out["FIN"] = (nxt, f, f)
    return out


def section_sum(rows, lo, hi, idx):
    s, n = 0.0, 0
    for r in rows[lo:hi]:
        v = r["vals"][idx] if idx < len(r["vals"]) else None
        if v is not None:
            s += v
            n += 1
    return s, n


DERIVED_LOG = []   # (期间, 科目, 说明)——非印刷值（由同表原始行算出）必须留痕


def fill_unprinted_icf(books, C, keys):
    """FY1995-2000 投资段无小计：投资活动净额 = 该段各行之和（各期只有购置固定资产一行）。"""
    ICF = "投资活动现金流净额 Net cash from investing activities"
    for key in keys:
        if C[ICF].get(key) is not None:
            continue
        osrc = own_source(books, "CF", key)
        if not osrc:
            continue
        src, slot = osrc
        st = books[src].get(slot)
        idx = col_index(st, key, src[0])
        secs = cf_sections(st["rows"])
        if "INV" in secs and secs["INV"][2] is None:
            lo, hi, _ = secs["INV"]
            s, n = section_sum(st["rows"], lo, hi, idx)
            if n:
                C[ICF][key] = s * table_scales(st, src[0])[M]
                DERIVED_LOG.append((key, ICF, f"申报未印投资段小计，取该段 {n} 行之和"))


def check_cf_raw(books, keys):
    """解析完整性闸：每份 as-reported 现金流量表里，原始行（不经概念映射）分段求和 = 印刷的段小计。
    概念映射之外的行也参与求和——证明「未单列项合计」那一行是真的『其余各行之和』而非解析漏行。"""
    bad = []
    for key in keys:
        osrc = own_source(books, "CF", key)
        if not osrc:
            continue
        src, slot = osrc
        st = books[src].get(slot)
        idx = col_index(st, key, src[0])
        sc = table_scales(st, src[0])[M]
        rows = st["rows"]
        secs = cf_sections(rows)
        for sec in ("OPS", "INV", "FIN"):
            if sec not in secs:
                bad.append((key, f"F0 {sec} 段边界找不到", 0))
                continue
            lo, hi, ti = secs[sec]
            if ti is None:            # 无小计的段只能靠 fill_unprinted_icf 取和，无可比对象
                continue
            s, n = section_sum(rows, lo, hi, idx)
            tot = rows[ti]["vals"][idx]
            dv = s - (tot or 0.0)
            chk(bad, key, f"F0 原始行{sec}段和=段小计", dv * sc)
            if abs(dv * sc) > EPS0:
                # 嫌疑探测：差额恰为某一行的 2 倍 → 该行符号渲染错（未套 negatedLabel），回印刷件核后进 R_SIGN_FIX
                for r in rows[lo:hi]:
                    v = r["vals"][idx] if idx < len(r["vals"]) else None
                    if v is not None and abs(2 * v - dv) < 1e-6:
                        print(f"   ↳ 嫌疑：{key} {sec}「{r['label'][:50]}」({r.get('tag', '')}) 值 {v} 翻号即平")
    return bad


# ── 写出 ────────────────────────────────────────────────────────────────────
HEADER_NOTE = {
    "IS": "# 单位: 百万美元(US$ mn)，EPS 为美元/股、股数为百万股 | 财年截至 1 月最后一个周日(FY1999 起；FY1993-1997 为日历年·FY1993 自 1993-04-05 成立起) | "
          "**无 FY1998**(1998-01 一个月过渡期见 过渡期-1998年1月.csv) | as-reported(各财年取自家年报当年列；FY1993-1997 取招股书) | "
          "费用为正、营业外按印刷符号 | 千美元来源年份保留 3 位小数 | EPS/股数是该次申报的拆股基准、不可跨年直接比 | 空=该期财报无此科目",
    "BS": "# 单位: 百万美元(US$ mn) | 各财年末时点(FY1999 起为 1 月最后一个周日；FY1993-1997 为 12-31) | **无 FY1998 列**(1998-01-31 余额见 过渡期-1998年1月.csv) | "
          "as-reported(各财年取自家年报当年列；FY1993-1997 取招股书，其中 FY1993-1995 只有五年摘要 4 行) | 千美元来源年份保留 3 位小数 | 空=该期财报无此科目",
    "CF": "# 单位: 百万美元(US$ mn) | 财年全年 | 流出为负 | **无 FY1998**(过渡月见 过渡期-1998年1月.csv) | as-reported(FY1995-1997 取招股书) | "
          "「未单列项合计」= 印刷段小计 − 已单列明细(原始行分段和另有勾稽 F0) | FY2020 起现金口径含受限现金(tag 改为 CashCashEquivalentsRestrictedCash…) | 空=该期财报无此科目",
}
FILE = {"IS": "利润表.csv", "BS": "资产负债表.csv", "CF": "现金流量表.csv"}


def fmt(v, kind=M):
    if v is None:
        return ""
    if kind == PS:
        return f"{v:.2f}"
    r = round(v, 3)
    if abs(r - round(r)) < 1e-9:
        return str(int(round(r)))
    return f"{r:.3f}".rstrip("0").rstrip(".")


def add_cf_resid(C, keys):
    out = dict(C)
    order = []
    for sec, (rname, tot, items) in CF_RESID.items():
        out[rname] = {}
        for k in keys:
            if C.get(tot, {}).get(k) is None:
                continue
            if not any(C.get(n, {}).get(k) is not None for n in items):
                continue
            out[rname][k] = C[tot][k] - sum((C.get(n, {}).get(k) or 0.0) for n in items)
        order.append((tot, rname))
    return out, order


def write_csv(stmt, data, origin, keys, fname=None, note=None, cf_order=None):
    kinds = {c[0]: c[5] for c in SPEC[stmt]}
    names = [c[0] for c in SPEC[stmt]]
    if cf_order:
        for tot, rname in cf_order:
            names.insert(names.index(tot), rname)
            kinds[rname] = M
    path = os.path.join(HERE, fname or FILE[stmt])
    with open(path, "w", newline="") as f:
        f.write((note or HEADER_NOTE[stmt]) + "\n")
        w = csv.writer(f)
        w.writerow(["科目"] + [("FY" + k) if k != TRANS else "1998年1月(过渡月)" for k in keys])
        w.writerow(["数据来源"] + [origin.get(k, "") for k in keys])
        for n in names:
            vals = [data.get(n, {}).get(k) for k in keys]
            if all(v is None for v in vals):
                continue
            w.writerow([n] + [fmt(v, kinds.get(n, M)) for v in vals])
    return path


def unit_of(books, stmt, key):
    """该格在源表里的印刷精度（百万美元）：千美元来源 0.001，百万来源 1。"""
    osrc = own_source(books, stmt, key)
    if not osrc:
        return None
    src, slot = osrc
    return table_scales(books[src][slot], src[0])[M]


def mutate(books, I, B, C, allkeys):
    """闸门对照组（记忆 verify-gate-tolerance-mutation-test 升级版）：逐格 +1 个印刷单位，重跑全部勾稽，
    报被捕获 / 未覆盖。未覆盖 = 不在任何勾稽等式里的格（单一来源附属行），须逐类确认是预期的。"""
    caught, miss = 0, {}
    base = {"IS": I, "BS": B, "CF": C}
    kinds = {c[0]: c[5] for s in SPEC for c in SPEC[s]}
    for stmt, d in base.items():
        for name, vv in d.items():
            if kinds.get(name) != M:
                continue
            for key, v in vv.items():
                if v is None:
                    continue
                u = unit_of(books, stmt, key)
                if not u:
                    continue
                dd = dict(d)
                dd[name] = dict(vv)
                dd[name][key] = v + u
                args = {"IS": I, "BS": B, "CF": C}
                args[stmt] = dd
                saved = list(RUN)
                b = check(args["IS"], args["BS"], args["CF"], [key])
                RUN[:] = saved
                if b:
                    caught += 1
                else:
                    miss.setdefault((stmt, name), []).append(key)
    tot = caught + sum(len(v) for v in miss.values())
    print(f"全格变异：{tot} 格中被捕获 {caught}（{caught / tot:.1%}），未覆盖 {tot - caught}")
    # 第二道防线：未覆盖格是否有另一份申报印出同值（跨申报独立印刷确认）
    lone = []
    n_conf = 0
    for (stmt, name), ks in sorted(miss.items(), key=lambda kv: -len(kv[1])):
        conf = [k for k in ks if (stmt, name, k) in CONFIRMED]
        n_conf += len(conf)
        rest = [k for k in ks if k not in conf]
        lone += [(stmt, name, k) for k in rest]
        print(f"   未覆盖 {stmt} {name[:44]}: {len(ks)} 格（跨申报同值确认 {len(conf)}）")
    print(f"未覆盖格中：跨申报同值确认 {n_conf} 格 / **既无勾稽又无第二处印刷** {len(lone)} 格：")
    for stmt, name, k in lone:
        print(f"     {stmt} FY{k} {name[:50]}")


def main():
    books = load()
    allkeys = YEARS + [TRANS]
    built = {s: build(books, s, allkeys) for s in ("IS", "BS", "CF")}
    I, B, C = built["IS"][0], built["BS"][0], built["CF"][0]
    fill_unprinted_icf(books, C, allkeys)
    if "--mutate" in sys.argv:
        mutate(books, I, B, C, allkeys)
        return 0
    bad = check_required(I, B, C, allkeys) + check(I, B, C, allkeys) + check_cf_raw(books, allkeys)
    n_run = len(RUN)
    by_code = {}
    for k, code in RUN:
        by_code[code] = by_code.get(code, 0) + 1
    print(f"勾稽执行 {n_run} 条：" + "，".join(f"{c}×{n}" for c, n in sorted(by_code.items())))
    print(f"跨申报同值确认：IS {XMATCH['IS']} 格 / BS {XMATCH['BS']} 格 / CF {XMATCH['CF']} 格")
    if bad:
        print(f"❌ 勾稽不通过 {len(bad)} 条（不写出 CSV）：")
        for b in bad:
            print("   ", b)
        return 1
    C2, cf_order = add_cf_resid(C, allkeys)
    for stmt, data in (("IS", I), ("BS", B), ("CF", C2)):
        write_csv(stmt, data, built[stmt][1], YEARS, cf_order=cf_order if stmt == "CF" else None)
    # 过渡月：三表合一张
    with open(os.path.join(HERE, "过渡期-1998年1月.csv"), "w", newline="") as f:
        f.write("# 1998 年 1 月单月过渡期(财年截止日由 12-31 改为 1 月最后一个周日) | 单位: 百万美元(千美元来源·3 位小数) | "
                "来源: 招股书报表(1999-01-21 定稿 424B4)，FY1999 / FY2000 10-K 比较列同值交叉核见 重述与口径变更.csv | "
                "利润表 / 现金流 = 1998-01-01~01-31 单月；资产负债 = 1998-01-31 时点\n")
        w = csv.writer(f)
        w.writerow(["表", "科目", "1998年1月"])
        for stmt, data in (("利润表", I), ("资产负债表", B), ("现金流量表", C2)):
            kinds = {c[0]: c[5] for c in SPEC[{"利润表": "IS", "资产负债表": "BS", "现金流量表": "CF"}[stmt]]}
            for n, vv in data.items():
                if vv.get(TRANS) is not None:
                    w.writerow([stmt, n, fmt(vv[TRANS], kinds.get(n, M))])
    # 重述台账
    rest = built["IS"][2] + built["BS"][2] + built["CF"][2]
    with open(os.path.join(HERE, "重述与口径变更.csv"), "w", newline="") as f:
        f.write("# 同一期间：as-reported(自家年报/招股书) vs 其他申报所印值。**本库一律以 as-reported 为准**，本表仅供追溯 | "
                "单位: 百万美元(EPS 美元/股·股数百万股) | 差异=其他申报−as-reported | L2006A = 2006-11-29 期权授予重述 10-K/A | "
                "EPS/股数差异多为拆股基准不同，非重述\n")
        w = csv.writer(f)
        w.writerow(["表", "科目", "期间", "as-reported", "其他申报所印", "其他申报", "差异"])
        for r in sorted(rest, key=lambda x: (x[0], x[2], x[1], x[5])):
            w.writerow(list(r))
    print(f"✅ 写出 利润表/资产负债表/现金流量表/过渡期/重述台账（重述与口径差异 {len(rest)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
