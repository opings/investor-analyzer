#!/usr/bin/env python3
"""NIKE 三表构建器：把 `_rfiles/`（FY2011-2026 的 SEC 渲染报表）与
`_legacy/`（FY1995-2010 的 10-K 文本/HTML 解析结果）合成
`利润表.csv` / `资产负债表.csv` / `现金流量表.csv` / `重述与口径变更.csv`，
**勾稽不过不写出**。

## 两条数据轨

| 轨 | 覆盖财年 | 载体 | 归一方式 | 采集器 |
|---|---|---|---|---|
| R 轨 | FY2011-2026 | 各年 10-K 的 R*.htm | **按 XBRL tag** 归一（措辞改过多次，tag 稳） | `_harvest_rfiles.py` |
| Legacy 轨 | FY1995-2010 | 10-K 正文 txt / htm | 按标签正则归一 | `_parse_legacy.py` |

每份 10-K 带 **3 年利润表/现金流 + 2 年资产负债表**，所以：
- FY1995 那份把 **FY1993 / FY1994** 的利润表与现金流捎回来了 → 序列起点 = **FY1993**；
- FY2011 那份带 FY2009-2011 → 与 Legacy 轨**重叠 2 年**，构成倒锁链的锚。

## 口径声明（取数当场固定，事后查不出来）

- **期间**：全部为**财年全年**（12 Months Ended）。NIKE 财年 **5 月 31 日**结束，
  FY2026 = 2025-06-01 ~ 2026-05-31。R 轨用 `months==12` 过滤，不靠列位置猜。
- **主体**：合并口径。NIKE **无少数股东权益**（三表里没有 NCI 行），
  故「净利润」= 「归母净利」。美股无「扣非」法定口径，本库不造扣非行；
  一次性项目（重组 / 商誉减值 / 无形减值 / 终止经营 / 会计变更累积影响）各自单列。
- **来源年份**：每个财年取**该财年自己那份 10-K 的当年列**（as-reported）。
  🔴 **有自家申报的年份，空格就是空格，不去别的申报补**——空白代表「那份申报没列这一行」，
  是信息不是窟窿。实证：FY2002 的资产负债表把无形与商誉**合并成一行**列示，
  若允许从 FY2003 的比较列补出「商誉」「无形资产」两个拆开的行，
  资产分项和会**凭空多出 438.7**（同一笔钱被合并行和拆分行各记一次），
  且两个数字各自都是真的、来源也都是一手年报。只有 FY1993 / FY1994
  （EDGAR 无自家 10-K）才用 FY1995 10-K 的比较列。
  后续年报的比较列一律只进 `重述与口径变更.csv` 供追溯。
- **单位**：**百万美元**。按各表**自陈单位**换算，不硬编码 ——
  FY1995-FY1997 的 10-K 印千美元；**FY2013 那一份的现金流量表印的是「原始美元」**
  （表头只有 `(USD $)`、没有 "In Millions"，同一份申报里利润表和资产负债表却都是百万），
  照百万处理会让 FY2013 经营现金流差 10⁶ 倍。
- **符号**：利润表费用为正、现金流量表流出为负。
  🔴 利息那一行 30 年里**措辞翻转过，含义跟着翻**：FY1995-2003「Interest expense」
  （正=费用）、FY2006-2007「Interest (income) expense, net」（正=费用）、
  **FY2008「Interest income, net」（正=收益！）**、FY2009 同名但印成 `(9.5)`、
  FY2010+「Interest expense (income), net」（正=费用）。
  照搬印刷数会让 FY2008 的利润链差 **−138.4**（= 2×77.1 的净利息收益被当成费用）。
  故按标签措辞判符号（`sign_flip`），并由利润链勾稽 C3 当守门人。
- 🔴 **每股数据不可跨年直接比**：NIKE 历史多次 2-for-1 拆股，**各年 10-K 的 EPS / 股数
  都是按该次申报时点的股本基准追溯调整过的**。实证：FY1995 的 10-K 印 FY1995 EPS
  **5.44**、股数 73,503 千股；FY1997 的 10-K 印同一个 FY1995 EPS **1.36**、股数
  294,012 千股（4 倍 = 1995-10 与 1996-04 两次 2-for-1）。本表按 as-reported 原样保留，
  跨年比较用 `财务比率.csv` 的拆股归一口径。
"""
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RDIR = os.path.join(HERE, "_rfiles")
LDIR = os.path.join(HERE, "_legacy")

RYEARS = list(range(2011, 2027))
LYEARS = list(range(1995, 2011))
ALL_FY = list(range(1993, 2027))
NO_OWN_FILING = (1993, 1994)     # EDGAR 最早申报 1995-01-17，这两年只能用比较列
TOL = 0.6                        # 勾稽容差（百万美元）

M, PS, SH = "money", "pershare", "shares"

# ── 概念定义 ────────────────────────────────────────────────────────────────
# (CSV 行名, [XBRL tag], [标签正则], 求和?, 量纲)
# tag 与标签正则**两轨都试**：先 tag（R 轨稳），再标签（legacy 轨 / R 轨同 tag 多行时）。
IS_CONCEPTS = [
    ("营业收入 Revenues",
     ["us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax",
      "us-gaap_SalesRevenueNet", "us-gaap_Revenues"], [r"^revenues$"], False, M),
    ("营业成本 Cost of sales",
     ["us-gaap_CostOfGoodsAndServicesSold", "us-gaap_CostOfRevenue",
      "us-gaap_CostOfGoodsSold"], [r"^costs? of sales$"], False, M),
    ("毛利 Gross profit", ["us-gaap_GrossProfit"], [r"^gross margin$"], False, M),
    ("  需求创造费用 Demand creation expense",
     ["us-gaap_MarketingAndAdvertisingExpense"], [r"^demand creation expense$"], False, M),
    ("  运营管理费用 Operating overhead expense",
     ["us-gaap_GeneralAndAdministrativeExpense"], [r"^operating overhead expense$"], False, M),
    ("销售及管理费用合计 Total selling and administrative expense",
     ["us-gaap_SellingGeneralAndAdministrativeExpense"],
     [r"^(total )?selling and administrative( expense)?$"], False, M),
    ("总成本及费用(仅FY1995-2001版式) Total costs and expenses", [],
     [r"^(total costs and expenses|costs and expenses 合计)$"], False, M),
    ("重组费用 Restructuring charges",
     ["us-gaap_RestructuringCharges",
      "us-gaap_RestructuringSettlementAndImpairmentProvisions"],
     [r"^restructuring charges?\b"], False, M),
    ("商誉减值 Goodwill impairment",
     ["us-gaap_GoodwillImpairmentLoss"], [r"^goodwill impairment"], False, M),
    ("无形及其他资产减值 Intangible and other asset impairment",
     ["us-gaap_ImpairmentOfIntangibleAssetsExcludingGoodwill"],
     [r"^intangible and other asset impairment"], False, M),
    ("利息费用净额(费用为正) Interest expense (income), net",
     ["us-gaap_InterestIncomeExpenseNonoperatingNet", "us-gaap_InterestExpense"],
     [r"^interest (expense|income)", r"^interest \(income\) expense"], False, M),
    ("其他(收入)支出净额(支出为正) Other (income) expense, net",
     ["us-gaap_OtherNonoperatingIncomeExpense", "nke_OtherIncomeExpenseNet"],
     [r"^other \(?(income|expense)\)?", r"^other income/expense"], False, M),
    ("税前利润 Income before income taxes",
     ["us-gaap_IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
      "us-gaap_IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
     [r"^income before income taxes"], False, M),
    ("所得税 Income taxes",
     ["us-gaap_IncomeTaxExpenseBenefit"],
     [r"^income tax(es)?( expense)?( \(note)?"], False, M),
    # FY2012-FY2014：Umbro / Cole Haan 出售 → 终止经营单列，净利 ≠ 税前−所得税
    ("持续经营净利(仅FY2012-2014) Net income from continuing operations",
     ["us-gaap_IncomeLossFromContinuingOperations"], [], False, M),
    ("终止经营损益(仅FY2012-2014) Net income (loss) from discontinued operations",
     ["us-gaap_IncomeLossFromDiscontinuedOperationsNetOfTax"], [], False, M),
    # FY2002-FY2005：税后还有一条「会计变更累积影响」
    ("会计变更前利润(仅FY2002-2005) Income before cumulative effect", [],
     [r"^income before cumulative effect"], False, M),
    ("会计变更累积影响(减项为正·仅FY2002-2005) Cumulative effect of accounting change", [],
     [r"^cumulative effect of accounting change"], False, M),
    ("净利润 Net income", ["us-gaap_NetIncomeLoss"], [r"^net income$"], False, M),
    ("基本EPS(as-reported·拆股基准随年变) Basic EPS",
     ["us-gaap_EarningsPerShareBasic"],
     [r"^basic earnings per common share", r"^net income per common share",
      r"^basic \(in dollars per share\)$"], False, PS),
    ("摊薄EPS(as-reported·拆股基准随年变) Diluted EPS",
     ["us-gaap_EarningsPerShareDiluted"],
     [r"^diluted earnings per common share", r"^diluted \(in dollars per share\)$"], False, PS),
    # FY1998-FY2010 的利润表**不印加权平均股数**，只印 EPS —— 股数在 EPS 附注
    # 「Determination of shares」调节表里（由 `_parse_legacy.py` 的 EPS 槽位抓回，
    #  经 FALLBACK["IS"] 兜底）。标签在这 13 年里有 average / weighted average 两种写法。
    ("基本股数(百万股·as-reported) Basic shares",
     ["us-gaap_WeightedAverageNumberOfSharesOutstandingBasic"],
     [r"^average number of common and common equivalent shares",
      r"^(weighted )?average common shares outstanding$"], False, SH),
    ("摊薄股数(百万股·as-reported) Diluted shares",
     ["us-gaap_WeightedAverageNumberOfDilutedSharesOutstanding"],
     [r"^diluted (weighted )?average common shares outstanding$"], False, SH),
    ("每股宣派股息(as-reported) Dividends declared per share",
     ["us-gaap_CommonStockDividendsPerShareDeclared"],
     [r"^dividends declared per common share"], False, PS),
]

BS_CONCEPTS = [
    ("货币资金 Cash and equivalents",
     ["us-gaap_CashAndCashEquivalentsAtCarryingValue"], [r"^cash and equivalents$"], False, M),
    ("短期投资 Short-term investments",
     ["us-gaap_DebtSecuritiesAvailableForSaleExcludingAccruedInterestCurrent",
      "us-gaap_AvailableForSaleSecuritiesDebtSecuritiesCurrent",
      "us-gaap_AvailableForSaleSecuritiesCurrent",
      "us-gaap_ShortTermInvestments", "us-gaap_OtherShortTermInvestments"],
     [r"^short-term investments"], False, M),
    ("应收账款净额 Accounts receivable, net",
     ["us-gaap_AccountsReceivableNetCurrent"], [r"^accounts receivable"], False, M),
    ("存货 Inventories",
     ["us-gaap_InventoryFinishedGoodsNetOfReserves", "us-gaap_InventoryNet"],
     [r"^inventories"], False, M),
    # scope 第 6 项：把可匹配行限制在「流动资产合计」之前 —— 同名行在非流动负债还有一条
    ("递延所得税(流动) Deferred income taxes (current)",
     ["us-gaap_DeferredTaxAssetsNetCurrent"], [r"^deferred income taxes \(note"], False, M,
     ("before", r"^total current assets$")),
    ("应收所得税(仅FY1999-2000) Income taxes receivable", [],
     [r"^income taxes receivable$"], False, M),
    ("预付及其他流动资产 Prepaid expenses and other current assets",
     ["us-gaap_PrepaidExpenseAndOtherAssetsCurrent"], [r"^prepaid expenses"], False, M),
    ("终止经营资产(仅FY2012-2013) Assets of discontinued operations",
     ["us-gaap_AssetsOfDisposalGroupIncludingDiscontinuedOperationCurrent"], [], False, M),
    ("流动资产合计 Total current assets",
     ["us-gaap_AssetsCurrent"], [r"^total current assets$"], False, M),
    ("固定资产净额 Property, plant and equipment, net",
     ["us-gaap_PropertyPlantAndEquipmentNet"],
     [r"^property, plant and equipment, net"], False, M),
    ("使用权资产 Operating lease right-of-use assets, net",
     ["us-gaap_OperatingLeaseRightOfUseAsset"], [], False, M),
    ("可辨认无形资产净额 Identifiable intangible assets, net",
     ["us-gaap_IntangibleAssetsNetExcludingGoodwill"],
     [r"^identifiable intangible assets, net"], False, M),
    ("商誉 Goodwill", ["us-gaap_Goodwill"], [r"^goodwill \(note"], False, M),
    ("无形资产及商誉(仅FY1995-2002合并列示) Identifiable intangible assets and goodwill", [],
     [r"^identifiable intangible assets and goodwill"], False, M),
    ("递延所得税及其他资产 Deferred income taxes and other assets",
     ["us-gaap_DeferredIncomeTaxesAndOtherAssetsNoncurrent"],
     [r"^deferred income taxes and other assets", r"^other assets$"], False, M),
    ("总资产 TOTAL ASSETS", ["us-gaap_Assets"], [r"^total assets$"], False, M),
    ("一年内到期长期债务 Current portion of long-term debt",
     ["us-gaap_LongTermDebtCurrent"], [r"^current portion of long-term debt"], False, M),
    ("短期借款 Notes payable",
     ["us-gaap_NotesPayableCurrent", "us-gaap_ShortTermBorrowings",
      "us-gaap_OtherShortTermBorrowings"], [r"^notes payable"], False, M),
    ("应付账款 Accounts payable",
     ["us-gaap_AccountsPayableCurrent"], [r"^accounts payable"], False, M),
    ("租赁负债(流动) Current portion of operating lease liabilities",
     ["us-gaap_OperatingLeaseLiabilityCurrent"], [], False, M),
    ("应计负债 Accrued liabilities",
     ["us-gaap_AccruedLiabilitiesCurrent"], [r"^accrued liabilities"], False, M),
    ("应交所得税 Income taxes payable",
     ["us-gaap_AccruedIncomeTaxesCurrent"], [r"^income taxes payable"], False, M),
    ("终止经营负债(仅FY2012-2013) Liabilities of discontinued operations",
     ["us-gaap_LiabilitiesOfDisposalGroupIncludingDiscontinuedOperationCurrent"], [], False, M),
    ("流动负债合计 Total current liabilities",
     ["us-gaap_LiabilitiesCurrent"], [r"^total current liabilities$"], False, M),
    ("长期债务 Long-term debt",
     ["us-gaap_LongTermDebtNoncurrent"], [r"^long-term debt"], False, M),
    ("租赁负债(非流动) Operating lease liabilities",
     ["us-gaap_OperatingLeaseLiabilityNoncurrent"], [], False, M),
    ("递延所得税及其他负债 Deferred income taxes and other liabilities",
     ["us-gaap_DeferredIncomeTaxesAndOtherLiabilitiesNoncurrent"],
     [r"^deferred income taxes and other liabilities"], False, M),
    # FY1995-FY1996 把上面这项拆成两行单列 → 各自单独成行，勾稽 B4 三项相加。
    # FY1996 把非流动那笔就叫「Deferred income taxes (Note 6)」（与流动那行同名），
    # 故这里必须限定在「流动负债合计」之后才能采到。
    ("非流动递延所得税(仅FY1995-1996单列) Non-current deferred income taxes", [],
     [r"^non-current deferred income taxes", r"^deferred income taxes \(note"], False, M,
     ("after", r"^total current liabilities$")),
    ("其他非流动负债(仅FY1995-1996单列) Other non-current liabilities", [],
     [r"^other (non-current )?liabilities"], False, M,
     ("after", r"^total current liabilities$")),
    ("可赎回优先股 Redeemable preferred stock",
     ["us-gaap_TemporaryEquityCarryingAmountAttributableToParent"],
     [r"^redeemable preferred stock"], False, M),
    # 🔴 股本印成 Class A / Class B **两行**（R 轨两行同一个 tag CommonStockValue，
    #    legacy 轨两行标签都以 Class 开头）→ 必须求和；取第一行只会拿到 Class A
    #    （FY2026 的 Class A 是 0.0，权益明细和会差 3.0 而且看起来"就是 0"）。
    ("股本(Class A+B) Common stock at stated value",
     ["us-gaap_CommonStockValue"], [r"^class [ab]\b"], True, M),
    ("超面值缴入资本 Capital in excess of stated value",
     ["us-gaap_AdditionalPaidInCapitalCommonStock"],
     [r"^capital in excess of stated value$"], False, M),
    ("未确认股权激励 Unearned stock compensation", [],
     [r"^unearned stock compensation$"], False, M),
    ("累计其他综合收益 Accumulated other comprehensive income (loss)",
     ["us-gaap_AccumulatedOtherComprehensiveIncomeLossNetOfTax"],
     [r"^accumulated other comprehensive", r"^foreign currency translation adjustment"], False, M),
    ("留存收益 Retained earnings (deficit)",
     ["us-gaap_RetainedEarningsAccumulatedDeficit"], [r"^retained earnings"], False, M),
    ("股东权益合计 Total shareholders' equity",
     ["us-gaap_StockholdersEquity"], [r"^total shareholders. equity$"], False, M),
    ("负债和股东权益合计 TOTAL LIABILITIES AND SHAREHOLDERS' EQUITY",
     ["us-gaap_LiabilitiesAndStockholdersEquity"],
     [r"^total liabilities and shareholders. equity$"], False, M),
]

CF_CONCEPTS = [
    ("净利润 Net income", ["us-gaap_NetIncomeLoss"], [r"^net income$"], False, M),
    ("折旧(与摊销) Depreciation (and amortization)",
     ["us-gaap_DepreciationDepletionAndAmortization",
      "us-gaap_DepreciationAmortizationAndAccretionNet", "us-gaap_Depreciation"],
     [r"^depreciation( and amortization)?$"], False, M),
    ("递延所得税 Deferred income taxes",
     ["us-gaap_DeferredIncomeTaxExpenseBenefit"], [r"^deferred income taxes"], False, M),
    ("股权激励费用 Stock-based compensation",
     ["us-gaap_ShareBasedCompensation"], [r"^stock-based compensation"], False, M),
    ("资产减值及其他 Impairment and other",
     ["us-gaap_AssetImpairmentCharges"],
     [r"^impairment of goodwill, intangibles and other assets"], False, M),
    ("摊销及其他 Amortization and other", ["nke_AmortizationAndOther"],
     [r"^amortization and other$"], False, M),
    ("出售业务损益 Net gain on divestitures",
     ["us-gaap_DiscontinuedOperationGainLossOnDisposalOfDiscontinuedOperationNetOfTax"],
     [r"^gain on divestitures"], False, M),
    ("汇兑调整 Net foreign currency adjustments",
     ["us-gaap_ForeignCurrencyTransactionGainLossUnrealized"], [], False, M),
    ("应收账款变动 (Increase) decrease in accounts receivable",
     ["us-gaap_IncreaseDecreaseInAccountsReceivable"], [r"in accounts receivable"], False, M),
    ("存货变动 (Increase) decrease in inventories",
     ["us-gaap_IncreaseDecreaseInInventories"], [r"in inventor(y|ies)$"], False, M),
    ("预付及其他变动 (Increase) decrease in prepaid expenses and other",
     ["us-gaap_IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets"],
     [r"in prepaid", r"in other current assets"], False, M),
    ("应付及应计变动 Increase (decrease) in accounts payable and accrued",
     ["us-gaap_IncreaseDecreaseInAccountsPayableAndOtherOperatingLiabilities",
      "us-gaap_IncreaseDecreaseInAccountsPayableAndAccruedLiabilities"],
     [r"in accounts payable, accrued liabilities"], False, M),
    ("经营活动现金流净额 Cash provided (used) by operations",
     ["us-gaap_NetCashProvidedByUsedInOperatingActivities"],
     [r"^cash .*by operations$"], False, M),
    ("购买短期投资 Purchases of short-term investments",
     ["us-gaap_PaymentsToAcquireAvailableForSaleSecuritiesDebt",
      "us-gaap_PaymentsToAcquireShortTermInvestments",
      "us-gaap_PaymentsToAcquireAvailableForSaleSecurities"],
     [r"^purchases of short-term investments$"], False, M),
    ("短期投资到期 Maturities of short-term investments",
     ["us-gaap_ProceedsFromMaturitiesPrepaymentsAndCallsOfAvailableForSaleSecurities",
      "us-gaap_ProceedsFromSaleMaturityAndCollectionsOfInvestments"],
     [r"^maturities (and sales )?of short-term investments$"], False, M),
    ("短期投资出售 Sales of short-term investments",
     ["us-gaap_ProceedsFromSaleOfAvailableForSaleSecuritiesDebt",
      "us-gaap_ProceedsFromSaleOfAvailableForSaleSecurities"],
     [r"^sales of short-term investments$"], False, M),
    ("资本开支 Additions to property, plant and equipment",
     ["us-gaap_PaymentsToAcquirePropertyPlantAndEquipment"],
     [r"^additions to property, plant and equipment"], False, M),
    ("处置固定资产 Disposals of property, plant and equipment",
     ["us-gaap_ProceedsFromSaleOfPropertyPlantAndEquipment"],
     [r"^disposals of property, plant and equipment$"], False, M),
    ("收购子公司 Acquisition of subsidiary, net of cash acquired",
     ["us-gaap_PaymentsToAcquireBusinessesNetOfCashAcquired"],
     [r"^acquisition of subsidiar"], False, M),
    ("出售业务所得 Proceeds from divestitures",
     ["us-gaap_ProceedsFromDivestitureOfBusinesses"],
     [r"^proceeds from divestitures"], False, M),
    ("其他投资活动 Other investing activities",
     ["us-gaap_PaymentsForProceedsFromOtherInvestingActivities"],
     [r"^increase in other assets", r"^settlement of net investment hedges$"], False, M),
    ("投资活动现金流净额 Cash provided (used) by investing activities",
     ["us-gaap_NetCashProvidedByUsedInInvestingActivities"],
     [r"^cash .*by investing activities$"], False, M),
    ("长期债务发行 Proceeds from issuance of long-term debt",
     ["us-gaap_ProceedsFromIssuanceOfLongTermDebt"],
     [r"^proceeds from (long-term debt issuance|issuance of long-term debt)$",
      r"^additions to long-term debt$"], False, M),
    ("长期债务偿还 Repayment of borrowings",
     ["us-gaap_RepaymentsOfDebt", "us-gaap_RepaymentsOfLongTermDebt"],
     [r"^reductions in long-term debt"], False, M),
    ("短期借款变动 Increase (decrease) in notes payable",
     ["us-gaap_ProceedsFromRepaymentsOfNotesPayable",
      "us-gaap_ProceedsFromRepaymentsOfShortTermDebt"], [r"in notes payable$"], False, M),
    ("行权所得 Proceeds from exercise of stock options",
     ["us-gaap_ProceedsFromIssuanceOrSaleOfEquity",
      "us-gaap_ProceedsFromStockOptionsExercised"],
     [r"^proceeds from exercise of (stock )?options"], False, M),
    ("回购股票 Repurchase of common stock",
     ["us-gaap_PaymentsForRepurchaseOfCommonStock"],
     [r"^repurchase of (common )?stock$"], False, M),
    ("已付股息 Dividends — common and preferred",
     ["us-gaap_PaymentsOfDividendsCommonStock", "us-gaap_PaymentsOfDividends"],
     [r"^dividends\s*[-—–]*\s*common and preferred$"], False, M),
    ("其他融资活动 Other financing activities",
     ["us-gaap_ProceedsFromPaymentsForOtherFinancingActivities",
      "us-gaap_ExcessTaxBenefitFromShareBasedCompensationFinancingActivities"],
     [r"^excess tax benefits from share-based payment arrangements$",
      r"^income tax benefit from exercise of stock options$"], False, M),
    ("融资活动现金流净额 Cash provided (used) by financing activities",
     ["us-gaap_NetCashProvidedByUsedInFinancingActivities"],
     [r"^cash .*by financing activities$"], False, M),
    ("汇率影响 Effect of exchange rate changes",
     ["us-gaap_EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
      "us-gaap_EffectOfExchangeRateOnCashAndCashEquivalents"],
     [r"^effect of exchange rate changes"], False, M),
    # FY1997-1999 独有的**第五个**现金流构成项：部分子公司此前按滞后期并表，
    # 1996 年 5 月起改为与母公司同期，差出来的一个月现金活动单列一行（FY1997: +43.0）。
    # 漏掉它，FY1997 的「经营+投资+融资+汇率=净变动」就差 43.0 —— 而四个总额各自都对。
    ("子公司并表期间调整(仅FY1997-1999) Effect of May 1996 cash flow activity", [],
     [r"^effect of may 1996 cash flow activity"], False, M),
    # 🔴 R 轨里「现金净变动 / 期初 / 期末」三行**共用同一个 tag**
    #    （CashCashEquivalents…IncludingExchangeRateEffect 系列），
    #    按 tag 取只会拿到第一行 → 三行读成同一个数。故这三行一律**按标签**取。
    ("现金净变动 Net increase (decrease) in cash and equivalents", [],
     [r"^net .*in cash and equivalents$"], False, M),
    ("期初现金 Cash and equivalents, beginning of year", [],
     [r"^cash and equivalents, beginning of year$"], False, M),
    ("期末现金 Cash and equivalents, end of year", [],
     [r"^cash and equivalents, end of year"], False, M),
    ("已付利息 Interest, net of capitalized interest",
     ["us-gaap_InterestPaidNet"],
     [r"^interest, net of capitalized interest$",
      r"^interest \(net of amount capitalized\)$", r"^interest$"], False, M),
    ("已付所得税 Income taxes paid", ["us-gaap_IncomeTaxesPaidNet"],
     [r"^income taxes$"], False, M),
    ("已宣派未付股息 Dividends declared and not paid",
     ["us-gaap_DividendsPayableCurrentAndNoncurrent"],
     [r"^dividends declared and not paid$"], False, M),
]

SPEC = {"IS": IS_CONCEPTS, "BS": BS_CONCEPTS, "CF": CF_CONCEPTS}
# 每张表除自身外还去哪些附注表兜底取值（FY2011-2018 的利润表不印加权股数，
# 它在「Earnings Per Share - Reconciliation…(Detail)」那张附注表里）
FALLBACK = {"IS": ["EPS"], "BS": [], "CF": []}


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


# ── 符号归一（利息 / 其他 两行）────────────────────────────────────────────
INT_ROW = "利息费用净额(费用为正) Interest expense (income), net"
OTH_ROW = "其他(收入)支出净额(支出为正) Other (income) expense, net"


def resolve_is_signs(d, fy):
    """把「利息」「其他」两行统一成**费用为正**，判据用**该份申报自己的利润链**，
    不用标签措辞。返回 (d, 说明)；解不出来就原样返回并记 "未解"。

    🔴 **为什么不能靠标签**：同一个标签 `Interest income, net` 在
    **FY2008 的 10-K 里正数=收益**（77.1 要加进税前），在 **FY2009 的 10-K 里
    正数=费用**（印成 `(9.5)` 才表示收益）。两份申报、同一措辞、相反约定 ——
    任何基于措辞的规则都必然在其中一年出错（第一版就是这么在 FY2009 差了 −19.0，
    恰好 = 2×9.5）。

    利润链本身是确定性的仲裁器：
      · FY2002+ 版式： 残差 = 毛利 − SG&A − 重组 − 商誉减值 − 无形减值 − 税前
      · FY1995-2001 版式： 残差 = 总成本及费用 − 营业成本 − SG&A − 重组
    残差就是「利息 + 其他」在费用为正口径下的应有之和。四种符号组合里取对上的那个。
    组合按 (+,+) → (+,−) → (−,+) → (−,−) 固定顺序试，保证可复现。

    独立校验仍在：C7 会拿**别的申报**印的同一年同一行来对，符号若还错，
    那边会呈现「数值相等、符号相反」。
    """
    i0, o0 = d.get(INT_ROW), d.get(OTH_ROW)
    if i0 is None and o0 is None:
        return d, ""
    gp, pbt = d.get("毛利 Gross profit"), d.get("税前利润 Income before income taxes")
    tce = d.get("总成本及费用(仅FY1995-2001版式) Total costs and expenses")
    cogs = d.get("营业成本 Cost of sales")
    sga = d.get("销售及管理费用合计 Total selling and administrative expense")
    restr = d.get("重组费用 Restructuring charges") or 0.0
    if gp is not None and pbt is not None and sga is not None:
        resid = (gp - sga - restr
                 - (d.get("商誉减值 Goodwill impairment") or 0.0)
                 - (d.get("无形及其他资产减值 Intangible and other asset impairment") or 0.0)
                 - pbt)
    elif tce is not None and cogs is not None and sga is not None:
        resid = tce - cogs - sga - restr
    else:
        return d, "未解(链不全)"
    a, b = (i0 or 0.0), (o0 or 0.0)
    for si, so in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        if abs(si * a + so * b - resid) <= TOL:
            out = dict(d)
            if i0 is not None:
                out[INT_ROW] = si * i0
            if o0 is not None:
                out[OTH_ROW] = so * o0
            return out, f"{'+' if si > 0 else '-'}{'+' if so > 0 else '-'}"
    return d, f"未解(残差{resid:.1f} vs 印刷{a:.1f}/{b:.1f})"


# ── 取值 ────────────────────────────────────────────────────────────────────
def table_scales(st, track):
    """→ {money, pershare, shares} 三个乘数，把该表换算到「百万美元 / 百万股 / 原样」。"""
    if track == "L":
        s = st["scale"]
        return {M: s, SH: s, PS: 1.0}
    u = norm(st.get("unit"))
    ushare = u
    u = re.sub(r"shares in (millions|thousands)", " ", u)      # 先摘掉股数那句
    money = 1.0 if "in millions" in u else (1e-3 if "in thousands" in u else 1e-6)
    if "shares in millions" in ushare:
        shares = 1.0
    elif "shares in thousands" in ushare:
        shares = 1e-3
    else:
        shares = money
    return {M: money, SH: shares, PS: 1.0}


def col_index(st, fy, track):
    """该表里「财年 fy」是第几列；找不到返回 None。"""
    if track == "L":
        return st["years"].index(fy) if fy in st["years"] else None
    for i, p in enumerate(st["periods"]):
        m = re.search(r"\b((19|20)\d\d)\b", p)
        if m and int(m.group(1)) == fy:
            if st["months"] and st["months"][i] not in (12, None):
                continue                     # 只要年度列（12 Months Ended）
            return i
    return None


def row_window(st, scope):
    """把可匹配行限制在一个区间内。scope = ("before"|"after", 锚行正则)。

    🔴 为什么需要：老资产负债表里「Deferred income taxes (Note 6)」**出现两次** ——
    一次在流动资产、一次在非流动负债（FY1996 分别是 93,120 与 1,883）。
    纯按标签取第一条，非流动那笔就永远采不到，资产负债表两侧差 1.88 百万
    （数额很小，但它是"某一整行从未进过库"的信号，不是舍入）。
    """
    n = len(st["rows"])
    if not scope:
        return 0, n
    mode, pat = scope
    for i, r in enumerate(st["rows"]):
        if re.search(pat, norm(r["label"])):
            return (0, i) if mode == "before" else (i + 1, n)
    return 0, n


def pick(st, tags, pats, fy, track, do_sum, kind, scope=None):
    """先按 tag 取（R 轨稳），再按标签正则取（legacy 轨 / 同 tag 多行时）。"""
    if not st:
        return None
    idx = col_index(st, fy, track)
    if idx is None:
        return None
    sc = table_scales(st, track)[kind]
    lo, hi = row_window(st, scope)
    rows = st["rows"][lo:hi]

    def val(row):
        v = row["vals"][idx] if idx < len(row["vals"]) else None
        return None if v is None else v * sc

    if tags:
        hits = [r for r in rows if r.get("tag") in tags and val(r) is not None]
        if hits:
            if do_sum:
                return sum(val(r) for r in hits)
            for t in tags:                   # tag 列表有优先级
                for r in hits:
                    if r.get("tag") == t:
                        return val(r)
    for pat in pats:
        hits = [r for r in rows if re.search(pat, norm(r["label"])) and val(r) is not None]
        if hits:
            return sum(val(r) for r in hits) if do_sum else val(hits[0])
    return None


def load():
    out = {}
    for fy in RYEARS:
        p = os.path.join(RDIR, f"{fy}.json")
        if os.path.exists(p):
            out[("R", fy)] = json.load(open(p))["statements"]
    for fy in LYEARS:
        p = os.path.join(LDIR, f"{fy}.json")
        if os.path.exists(p):
            out[("L", fy)] = json.load(open(p))["statements"]
    return out


def extract(books, track, ffy, key, fy):
    """从「(track, ffy) 这份申报」里读出「财年 fy」的一整套科目值（已做符号归一）。"""
    d = {}
    for c in SPEC[key]:
        name, tags, pats, s, kd = c[0], c[1], c[2], c[3], c[4]
        scope = c[5] if len(c) > 5 else None
        for k in [key] + FALLBACK[key]:
            v = pick(books[(track, ffy)].get(k), tags, pats, fy, track, s, kd, scope)
            if v is not None:
                d[name] = v
                break
    note = ""
    if key == "IS" and d:
        d, note = resolve_is_signs(d, fy)
    return d, note


def has_year(books, track, ffy, key, fy):
    st = books[(track, ffy)].get(key)
    return bool(st) and col_index(st, fy, track) is not None


def build(books, key):
    """→ (data[row_name][fy], origin[fy], rest[], signnote[fy])"""
    data = {c[0]: {} for c in SPEC[key]}
    origin, rest, signnote = {}, [], {}
    # 1) as-reported：每个财年只取「自家那份 10-K 的当年列」
    for fy in ALL_FY:
        for track in ("R", "L"):
            if (track, fy) not in books:
                continue
            d, note = extract(books, track, fy, key, fy)
            for name, v in d.items():
                data[name][fy] = v
            if d:
                origin[fy] = f"{track}{fy}自身"
                signnote[fy] = note
            break
    # 2) 只给「没有自家申报」的年份补洞（FY1993/FY1994）；其余年份的空白保留
    for fy in NO_OWN_FILING:
        for (track, ffy) in sorted(books, key=lambda k: k[1]):
            if not has_year(books, track, ffy, key, fy):
                continue
            d, note = extract(books, track, ffy, key, fy)
            for name, v in d.items():
                data[name].setdefault(fy, v)
            origin.setdefault(fy, f"{track}{ffy}比较列")
            signnote.setdefault(fy, note)
            break
    # 3) 重述追溯：同一财年在**别的**申报里印的值 vs as-reported 值
    for fy in ALL_FY:
        if "自身" not in origin.get(fy, ""):
            continue
        for (track, ffy) in sorted(books, key=lambda k: k[1]):
            if ffy == fy or not has_year(books, track, ffy, key, fy):
                continue
            d, _ = extract(books, track, ffy, key, fy)
            for c in SPEC[key]:
                name, kd = c[0], c[4]
                a, v = data[name].get(fy), d.get(name)
                if a is None or v is None:
                    continue
                if abs(a - v) > max(TOL if kd == M else 0.005, abs(a) * 0.003):
                    rest.append((key, name, fy, round(a, 3), round(v, 3),
                                 f"{track}{ffy}", round(v - a, 3)))
    return data, origin, rest, signnote


# ── 勾稽 ────────────────────────────────────────────────────────────────────
def g(d, name, fy, dflt=0.0):
    v = d.get(name, {}).get(fy)
    return dflt if v is None else v


def has(d, name, fy):
    return d.get(name, {}).get(fy) is not None


# 每张表的「必填项」：只要该财年有这张表的任何数据，这些行就必须有值。
# 🔴 为什么单设这一条：所有比例式勾稽都写成「某个锚科目存在才开查」，
#    于是**锚科目本身丢失时，整张表的检查会静默全部跳过**。
#    实证：解析器把 `Revenues` 误并进单位说明行后，FY1993-1996 与 FY2002-2010
#    的营收整段为空，而勾稽照报「全过」—— 因为 C1/C3 都挂在 `has(营业收入)` 下面。
#    闸门不能以「被检查的东西存在」为前提。
REQUIRED = {
    "IS": ["营业收入 Revenues", "税前利润 Income before income taxes",
           "所得税 Income taxes", "净利润 Net income"],
    "BS": ["总资产 TOTAL ASSETS", "流动资产合计 Total current assets",
           "流动负债合计 Total current liabilities", "股东权益合计 Total shareholders' equity",
           "货币资金 Cash and equivalents", "存货 Inventories",
           "应收账款净额 Accounts receivable, net"],
    "CF": ["经营活动现金流净额 Cash provided (used) by operations",
           "投资活动现金流净额 Cash provided (used) by investing activities",
           "融资活动现金流净额 Cash provided (used) by financing activities",
           "期末现金 Cash and equivalents, end of year",
           "资本开支 Additions to property, plant and equipment"],
}


def check_required(built):
    bad = []
    for key, req in REQUIRED.items():
        d = built[key][0]
        for fy in ALL_FY:
            if not any(d[c[0]].get(fy) is not None for c in SPEC[key]):
                continue                      # 该年整张表都没有 → 不是缺项问题
            for name in req:
                if d.get(name, {}).get(fy) is None:
                    bad.append((fy, f"C0 {key} 必填项缺失: {name[:20]}", 0))
    return bad


def check(I, B, C):
    bad = []
    R = "营业收入 Revenues"
    GP = "毛利 Gross profit"
    PBT = "税前利润 Income before income taxes"
    NI = "净利润 Net income"
    CONT = "持续经营净利(仅FY2012-2014) Net income from continuing operations"
    DISC = "终止经营损益(仅FY2012-2014) Net income (loss) from discontinued operations"
    CUMB = "会计变更前利润(仅FY2002-2005) Income before cumulative effect"
    CUM = "会计变更累积影响(减项为正·仅FY2002-2005) Cumulative effect of accounting change"
    TCE = "总成本及费用(仅FY1995-2001版式) Total costs and expenses"
    SGA = "销售及管理费用合计 Total selling and administrative expense"
    INT = "利息费用净额(费用为正) Interest expense (income), net"
    OTH = "其他(收入)支出净额(支出为正) Other (income) expense, net"
    for fy in ALL_FY:
        # ── 利润表 ──
        if has(I, R, fy):
            if has(I, GP, fy):
                dv = g(I, R, fy) - g(I, "营业成本 Cost of sales", fy) - g(I, GP, fy)
                if abs(dv) > TOL:
                    bad.append((fy, "C1 营收−成本=毛利", round(dv, 2)))
            base = CONT if has(I, CONT, fy) else (CUMB if has(I, CUMB, fy) else NI)
            if has(I, PBT, fy) and has(I, base, fy):
                dv = g(I, PBT, fy) - g(I, "所得税 Income taxes", fy) - g(I, base, fy)
                if abs(dv) > TOL:
                    bad.append((fy, f"C2 税前−所得税={base[:6]}", round(dv, 2)))
            if has(I, GP, fy):
                dv = (g(I, GP, fy) - g(I, SGA, fy)
                      - g(I, "重组费用 Restructuring charges", fy)
                      - g(I, "商誉减值 Goodwill impairment", fy)
                      - g(I, "无形及其他资产减值 Intangible and other asset impairment", fy)
                      - g(I, INT, fy) - g(I, OTH, fy) - g(I, PBT, fy))
                if abs(dv) > TOL:
                    bad.append((fy, "C3a 毛利−费用=税前", round(dv, 2)))
            elif has(I, TCE, fy):
                dv = g(I, R, fy) - g(I, TCE, fy) - g(I, PBT, fy)
                if abs(dv) > TOL:
                    bad.append((fy, "C3b 营收−总成本=税前", round(dv, 2)))
                dv2 = (g(I, "营业成本 Cost of sales", fy) + g(I, SGA, fy) + g(I, INT, fy)
                       + g(I, OTH, fy) + g(I, "重组费用 Restructuring charges", fy)
                       - g(I, TCE, fy))
                if abs(dv2) > TOL:
                    bad.append((fy, "C3c 各项和=总成本", round(dv2, 2)))
            if has(I, CONT, fy):
                dv = g(I, CONT, fy) + g(I, DISC, fy) - g(I, NI, fy)
                if abs(dv) > TOL:
                    bad.append((fy, "C4a 持续+终止=净利", round(dv, 2)))
            if has(I, CUMB, fy):
                dv = g(I, CUMB, fy) - g(I, CUM, fy) - g(I, NI, fy)
                if abs(dv) > TOL:
                    bad.append((fy, "C4b 变更前−累积影响=净利", round(dv, 2)))
            if has(I, "  需求创造费用 Demand creation expense", fy):
                dv = (g(I, "  需求创造费用 Demand creation expense", fy)
                      + g(I, "  运营管理费用 Operating overhead expense", fy) - g(I, SGA, fy))
                if abs(dv) > TOL:
                    bad.append((fy, "C5 需求创造+运营管理=SG&A", round(dv, 2)))
            # C6 EPS 自洽：净利(或持续经营净利) ÷ 基本股数 ≈ 基本EPS（2% 容差）
            #    这条是**单位与拆股基准的守门人**——EPS 量纲错、股数漏乘 scale 都在这里现形
            bs = g(I, "基本股数(百万股·as-reported) Basic shares", fy)
            be = g(I, "基本EPS(as-reported·拆股基准随年变) Basic EPS", fy)
            # 分子要跟印出来的那个 EPS 对齐：FY2012-2014 印的是**持续经营** EPS、
            # FY2002-2005 印的是**会计变更前** EPS（`— before accounting change`），
            # 直接拿净利去除会在 FY2003 差 1.008/股（净利 474 已扣掉 266.1 的变更影响）。
            num = (g(I, CONT, fy) if has(I, CONT, fy)
                   else (g(I, CUMB, fy) if has(I, CUMB, fy) else g(I, NI, fy)))
            if bs and be and num:
                if abs(num / bs / be - 1) > 0.02:
                    bad.append((fy, "C6 净利÷股数≈EPS", round(num / bs - be, 3)))
        # ── 资产负债表 ──
        TA = "总资产 TOTAL ASSETS"
        TCA = "流动资产合计 Total current assets"
        TCL = "流动负债合计 Total current liabilities"
        TE = "股东权益合计 Total shareholders' equity"
        if has(B, TA, fy):
            dv = (g(B, "货币资金 Cash and equivalents", fy)
                  + g(B, "短期投资 Short-term investments", fy)
                  + g(B, "应收账款净额 Accounts receivable, net", fy)
                  + g(B, "存货 Inventories", fy)
                  + g(B, "递延所得税(流动) Deferred income taxes (current)", fy)
                  + g(B, "应收所得税(仅FY1999-2000) Income taxes receivable", fy)
                  + g(B, "预付及其他流动资产 Prepaid expenses and other current assets", fy)
                  + g(B, "终止经营资产(仅FY2012-2013) Assets of discontinued operations", fy)
                  - g(B, TCA, fy))
            if abs(dv) > TOL:
                bad.append((fy, "B1 流动资产明细和", round(dv, 2)))
            dv = (g(B, TCA, fy)
                  + g(B, "固定资产净额 Property, plant and equipment, net", fy)
                  + g(B, "使用权资产 Operating lease right-of-use assets, net", fy)
                  + g(B, "可辨认无形资产净额 Identifiable intangible assets, net", fy)
                  + g(B, "商誉 Goodwill", fy)
                  + g(B, "无形资产及商誉(仅FY1995-2002合并列示) Identifiable intangible assets and goodwill", fy)
                  + g(B, "递延所得税及其他资产 Deferred income taxes and other assets", fy)
                  - g(B, TA, fy))
            if abs(dv) > TOL:
                bad.append((fy, "B2 资产分项和=总资产", round(dv, 2)))
            dv = (g(B, "一年内到期长期债务 Current portion of long-term debt", fy)
                  + g(B, "短期借款 Notes payable", fy)
                  + g(B, "应付账款 Accounts payable", fy)
                  + g(B, "租赁负债(流动) Current portion of operating lease liabilities", fy)
                  + g(B, "应计负债 Accrued liabilities", fy)
                  + g(B, "应交所得税 Income taxes payable", fy)
                  + g(B, "终止经营负债(仅FY2012-2013) Liabilities of discontinued operations", fy)
                  - g(B, TCL, fy))
            if abs(dv) > TOL:
                bad.append((fy, "B3 流动负债明细和", round(dv, 2)))
            dv = (g(B, TCL, fy) + g(B, "长期债务 Long-term debt", fy)
                  + g(B, "租赁负债(非流动) Operating lease liabilities", fy)
                  + g(B, "递延所得税及其他负债 Deferred income taxes and other liabilities", fy)
                  + g(B, "非流动递延所得税(仅FY1995-1996单列) Non-current deferred income taxes", fy)
                  + g(B, "其他非流动负债(仅FY1995-1996单列) Other non-current liabilities", fy)
                  + g(B, "可赎回优先股 Redeemable preferred stock", fy)
                  + g(B, TE, fy) - g(B, TA, fy))
            if abs(dv) > TOL:
                bad.append((fy, "B4 负债+权益=总资产", round(dv, 2)))
            dv = (g(B, "股本(Class A+B) Common stock at stated value", fy)
                  + g(B, "超面值缴入资本 Capital in excess of stated value", fy)
                  + g(B, "未确认股权激励 Unearned stock compensation", fy)
                  + g(B, "累计其他综合收益 Accumulated other comprehensive income (loss)", fy)
                  + g(B, "留存收益 Retained earnings (deficit)", fy) - g(B, TE, fy))
            if abs(dv) > TOL:
                bad.append((fy, "B5 权益明细和", round(dv, 2)))
            TLE = "负债和股东权益合计 TOTAL LIABILITIES AND SHAREHOLDERS' EQUITY"
            if has(B, TLE, fy) and abs(g(B, TA, fy) - g(B, TLE, fy)) > TOL:
                bad.append((fy, "B6 两侧合计相等", round(g(B, TA, fy) - g(B, TLE, fy), 2)))
        # ── 现金流量表 ──
        OP = "经营活动现金流净额 Cash provided (used) by operations"
        NET = "现金净变动 Net increase (decrease) in cash and equivalents"
        END = "期末现金 Cash and equivalents, end of year"
        if has(C, OP, fy):
            dv = (g(C, OP, fy)
                  + g(C, "投资活动现金流净额 Cash provided (used) by investing activities", fy)
                  + g(C, "融资活动现金流净额 Cash provided (used) by financing activities", fy)
                  + g(C, "汇率影响 Effect of exchange rate changes", fy)
                  + g(C, "子公司并表期间调整(仅FY1997-1999) Effect of May 1996 cash flow activity", fy)
                  - g(C, NET, fy))
            if abs(dv) > TOL:
                bad.append((fy, "F1 经营+投资+融资+汇率=净变动", round(dv, 2)))
            dv = (g(C, "期初现金 Cash and equivalents, beginning of year", fy)
                  + g(C, NET, fy) - g(C, END, fy))
            if abs(dv) > TOL:
                bad.append((fy, "F2 期初+净变动=期末", round(dv, 2)))
            if has(I, NI, fy) and has(C, NI, fy) and abs(g(C, NI, fy) - g(I, NI, fy)) > TOL:
                bad.append((fy, "F3 CF净利=IS净利", round(g(C, NI, fy) - g(I, NI, fy), 2)))
            if has(B, "货币资金 Cash and equivalents", fy):
                dv = g(C, END, fy) - g(B, "货币资金 Cash and equivalents", fy)
                if abs(dv) > TOL:
                    bad.append((fy, "F4 期末现金=BS货币资金", round(dv, 2)))
    return bad


# ── 写出 ────────────────────────────────────────────────────────────────────
HEADER_NOTE = {
    "IS": "单位: 百万美元(US$ mn)，EPS 为美元/股、股数为百万股 | 财年截至 5 月 31 日 | "
          "as-reported(各财年取自家 10-K 当年列) | 费用为正 | "
          "EPS/股数是该次申报的拆股基准、不可跨年直接比(见 财务比率.csv 拆股归一列) | 空=该期财报无此科目",
    "BS": "单位: 百万美元(US$ mn) | 时点 = 财年末 5 月 31 日 | as-reported | 空=该期财报无此科目",
    "CF": "单位: 百万美元(US$ mn) | 财年全年 | 流出为负 | as-reported | 空=该期财报无此科目",
}
FILE = {"IS": "利润表.csv", "BS": "资产负债表.csv", "CF": "现金流量表.csv"}


def fmt(v, kind=M):
    """按量纲定小数位：金额/股数 1 位，**每股数据 2 位**。

    ⚠️ 统一用「小于 100 就多留小数」这种按数值大小定位数的写法会出事：
    EPS 5.44 会被截成 5.4（丢掉分），而利息费用 25.739 又留了 3 位假精度。
    位数该由**量纲**决定，不由数值大小决定。
    """
    if v is None:
        return ""
    if kind == PS:
        return f"{v:.2f}"
    return f"{round(v, 1):g}"


def write_csv(key, data, origin):
    path = os.path.join(HERE, FILE[key])
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"# {HEADER_NOTE[key]}"])
        w.writerow(["科目"] + [f"FY{y}" for y in ALL_FY])
        w.writerow(["数据来源"] + [origin.get(y, "") for y in ALL_FY])
        for c in SPEC[key]:
            row = [fmt(data[c[0]].get(y), c[4]) for y in ALL_FY]
            if any(row):
                w.writerow([c[0]] + row)
    print(f"  写出 {FILE[key]}")


def check_signs(rests, data_is):
    """C7 —— 符号的**独立**校验（利润链已被用来定符号，不能再当校验）。

    判据：若别的申报印的同一年同一行，其值 ≈ **本库值的相反数**（相对差 <1%，
    且绝对值 > TOL），说明本库那一年的符号站错了边。真正的重述会改数值大小，
    不会精确地只翻符号。
    """
    bad = []
    for key, name, fy, a, v, src, _ in rests:
        if key != "IS" or name not in (INT_ROW, OTH_ROW):
            continue
        if abs(a) > TOL and abs(v + a) < max(TOL, abs(a) * 0.01):
            bad.append((fy, f"C7 {name[:10]}符号与{src}相反", round(v, 2)))
    return bad


def main():
    books = load()
    print(f"载入申报 {len(books)} 份："
          f"R轨 {sum(1 for k in books if k[0] == 'R')} + Legacy轨 {sum(1 for k in books if k[0] == 'L')}")
    built, rests, notes = {}, [], {}
    for key in ("IS", "BS", "CF"):
        d, o, r, sn = build(books, key)
        built[key] = (d, o)
        rests += r
        if key == "IS":
            notes = sn
        n = sum(1 for y in ALL_FY if any(d[c[0]].get(y) is not None for c in SPEC[key]))
        print(f"{key}: 覆盖 {n} 个财年，重述/口径差异 {len(r)} 处")
    unresolved = sorted(y for y, t in notes.items() if t.startswith("未解"))
    flipped = sorted(y for y, t in notes.items() if t in ("-+", "+-", "--"))
    print(f"符号归一：需翻符号的财年 {flipped or '无'}；未解 {unresolved or '无'}")

    bad = (check_required(built)
           + check(built["IS"][0], built["BS"][0], built["CF"][0])
           + check_signs(rests, built["IS"][0]))
    if bad:
        print(f"\n🔴 勾稽未过 {len(bad)} 条（不写出 CSV）：")
        for fy, nm, dv in bad[:80]:
            print(f"  FY{fy} {nm}: 差 {dv}")
        if "--force" not in sys.argv:
            sys.exit(1)
    else:
        print("\n✅ 勾稽全过")

    for key in ("IS", "BS", "CF"):
        write_csv(key, *built[key])

    rp = os.path.join(HERE, "重述与口径变更.csv")
    with open(rp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# 同一财年 as-reported 值 vs 其他申报所印值的差异（金额单位: 百万美元）。"
                    "差异来源 = 重述 / 列报口径变更 / 终止经营重分类 / 拆股基准变化，"
                    "不是解析错——本库一律以 as-reported 为准，本表仅供追溯。"])
        w.writerow(["表", "科目", "财年", "as-reported值", "其他申报值", "来源申报", "差额"])
        for r in sorted(rests, key=lambda x: (x[2], x[0], x[1])):
            w.writerow(r)
    print(f"  写出 重述与口径变更.csv（{len(rests)} 条）")


if __name__ == "__main__":
    main()
