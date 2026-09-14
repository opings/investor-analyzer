#!/usr/bin/env python3
"""特斯拉(Tesla, Inc. · NASDAQ: TSLA · CIK 1318605)三表构建器。

数据血缘（唯一真源 = 一手 SEC 申报）
──────────────────────────────────────────────────────────────────
轨道①「印刷转录轨」= 各年 10-K 的 SEC 渲染报表 R*.htm —— 该年申报**自身**的 as-reported
    印刷行项，缓存在 `_rfiles/<fy>.json`（`_harvest_rfiles.py` 抓取）。覆盖 FY2011–FY2025。
    **按 XBRL tag 归一，不按印刷标签归一** —— 15 年里同一行的英文措辞改过几十次
    （"Net loss"→"Net income (loss)"→"Net income"；"Deferred revenue"→ContractWithCustomerLiability…），
    tag 才是稳定标识；presentation 真的换了科目（换 tag）就多一行，不强行归并。
轨道②「XBRL 独立核对轨」= `_xbrl/companyfacts-CIK0001318605.json`（SEC 机读·公司自报），
    按 accn 过滤到「该年自己的 10-K」，与轨道①逐格比对，容差 0。
前 XBRL 年份（FY2005–FY2010）从一手 HTM 转录（EARLY_* 常量，逐格标出处）：
    · FY2005/FY2006 → 424B4(2010-06-29) 五年 Selected Financial Data（仅损益·当年无营收）
    · FY2007        → 424B4 经审计损益表 + 现金流量表（该年**年末**资产负债表一手不可得）
    · FY2008/FY2009 → 424B4 经审计三表
    · FY2010        → 10-K FY2010 经审计三表

单位与符号
──────────────────────────────────────────────────────────────────
· 全表统一 **千美元 (USD thousands)**。
· ⚠️ 印刷口径 **FY2019 起由「千美元」改为「百万美元」** —— FY2019+ 的值 = 印刷百万数 ×1000，
  精度只到百万（末三位恒为 0）。这是印刷粒度本身，不是解析误差。
· **利润表 / 现金流量表**：费用 / 流出 / 减项 = 负数。
· **资产负债表**：按印刷原值（资产、负债、权益均为正；印刷带括号者为负，如累计亏损）。
· 空 = 该年申报 presentation 无此科目（不补 0、不外推）。

勾稽自洽校验（不通过则不写出 CSV）—— 见 check() / check_seg()
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RDIR = os.path.join(HERE, "_rfiles")
XBRL = os.path.join(HERE, "_xbrl", "companyfacts-CIK0001318605.json")

ACCS = {
    2011: "0001193125-12-081990", 2012: "0001193125-13-096241", 2013: "0001193125-14-069681",
    2014: "0001564590-15-001031", 2015: "0001564590-16-013195", 2016: "0001564590-17-003118",
    2017: "0001564590-18-002956", 2018: "0001564590-19-003165", 2019: "0001564590-20-004475",
    2020: "0001564590-21-004599", 2021: "0000950170-22-000796", 2022: "0000950170-23-001409",
    2023: "0001628280-24-002390", 2024: "0001628280-25-003063", 2025: "0001628280-26-003952",
}
SCALE = {fy: (1 if fy <= 2018 else 1000) for fy in ACCS}     # FY2019 起印刷改百万
YEARS = list(range(2005, 2026))

# ══════════════════════════════════════════════════════════════════
# 1. 利润表：tag → (canonical, 取负)
#    「取负」= 印刷为正数但经济含义是减项 → 存 −印刷值（税收优惠印刷为负 → 存正，符号自然翻转）
# ══════════════════════════════════════════════════════════════════
IS_TAGS = {
    "us-gaap_Revenues": ("营业收入 Total revenues", False),
    "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax": ("营业收入 Total revenues", False),
    "us-gaap_CostOfRevenue": ("营业成本 Total cost of revenues", True),
    "us-gaap_GrossProfit": ("毛利 Gross profit", False),
    "us-gaap_ResearchAndDevelopmentExpense": ("研发费用 Research and development", True),
    "us-gaap_SellingGeneralAndAdministrativeExpense": ("销售及行政费用 Selling, general and administrative", True),
    "tsla_RestructuringAndOtherExpenses": ("重组及其他 Restructuring and other", True),
    "us-gaap_OperatingExpenses": ("经营费用合计 Total operating expenses", True),
    "us-gaap_OperatingIncomeLoss": ("经营利润 Income (loss) from operations", False),
    "us-gaap_InvestmentIncomeInterest": ("利息收入 Interest income", False),
    "us-gaap_InterestExpense": ("利息费用 Interest expense", False),
    "us-gaap_InterestExpenseNonoperating": ("利息费用 Interest expense", False),
    "us-gaap_OtherNonoperatingIncomeExpense": ("其他收入(费用)净额 Other income (expense), net", False),
    "us-gaap_IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
        ("税前利润 Income (loss) before income taxes", False),
    "us-gaap_IncomeTaxExpenseBenefit": ("所得税 Provision for (benefit from) income taxes", True),
    "us-gaap_ProfitLoss": ("净利润(含少数股东) Net income (loss)", False),
    "us-gaap_NetIncomeLossAttributableToNoncontrollingInterest": ("少数股东损益 Net income (loss) attributable to NCI", False),
    "us-gaap_NetIncomeLossAvailableToCommonStockholdersBasic": ("归母净利润 Net income (loss) attributable to common stockholders", False),
    "tsla_BuyOutOfNoncontrollingInterest": ("减:买断非控股权益(EPS 分子调整) Buy-out of NCI", False),
    "us-gaap_EarningsPerShareBasic": ("每股收益-基本(美元)", False),
    "us-gaap_EarningsPerShareDiluted": ("每股收益-稀释(美元)", False),
    "us-gaap_WeightedAverageNumberOfSharesOutstandingBasic": ("加权平均股数-基本(千股)", False),
    "us-gaap_WeightedAverageNumberOfDilutedSharesOutstanding": ("加权平均股数-稀释(千股)", False),
}
# 早年合并列示为一行「basic and diluted」→ 同时写入 基本/稀释 两行
IS_TAGS_DUAL = {
    "us-gaap_IncomeLossFromContinuingOperationsPerBasicAndDilutedShare": ("每股收益-基本(美元)", "每股收益-稀释(美元)"),
    "us-gaap_EarningsPerShareBasicAndDiluted": ("每股收益-基本(美元)", "每股收益-稀释(美元)"),
    "tsla_WeightedAverageNumberOfSharesOutstandingBasicAndDiluted1": ("加权平均股数-基本(千股)", "加权平均股数-稀释(千股)"),
    "tsla_WeightedAverageNumberOfSharesOutstandingBasicAndDilutedOne": ("加权平均股数-基本(千股)", "加权平均股数-稀释(千股)"),
    "us-gaap_WeightedAverageNumberOfShareOutstandingBasicAndDiluted": ("加权平均股数-基本(千股)", "加权平均股数-稀释(千股)"),
}
# us-gaap_NetIncomeLoss 在损益表里的含义随年份变：2011-2015 = 净利(无少数股东)；2018+ = 归母净利
IS_SHARES = {"每股收益-基本(美元)", "每股收益-稀释(美元)"}          # 不乘 SCALE
IS_SHARE_CNT = {"加权平均股数-基本(千股)", "加权平均股数-稀释(千股)"}  # 乘 SCALE（股数与金额同印刷单位）
IS_ROWS = ["营业收入 Total revenues", "营业成本 Total cost of revenues", "毛利 Gross profit",
           "研发费用 Research and development", "销售及行政费用 Selling, general and administrative",
           "重组及其他 Restructuring and other", "经营费用合计 Total operating expenses",
           "经营利润 Income (loss) from operations", "利息收入 Interest income", "利息费用 Interest expense",
           "其他收入(费用)净额 Other income (expense), net", "税前利润 Income (loss) before income taxes",
           "所得税 Provision for (benefit from) income taxes", "净利润(含少数股东) Net income (loss)",
           "少数股东损益 Net income (loss) attributable to NCI",
           "归母净利润 Net income (loss) attributable to common stockholders",
           "减:买断非控股权益(EPS 分子调整) Buy-out of NCI",
           "每股收益-基本(美元)", "每股收益-稀释(美元)",
           "加权平均股数-基本(千股)", "加权平均股数-稀释(千股)",
           "备忘-股份支付 SBC(取自现金流量表)", "备忘-折旧摊销及减值 D&A(取自现金流量表)"]

# ══════════════════════════════════════════════════════════════════
# 2. 资产负债表：(tag, 维度成员关键词) → canonical。段属性用于分项勾稽
# ══════════════════════════════════════════════════════════════════
A_CUR, A_NON, L_CUR, L_NON, MEZ, EQ, TOT = "流动资产", "非流动资产", "流动负债", "非流动负债", "夹层", "权益", "合计"
BS_TAGS = {
    "us-gaap_CashAndCashEquivalentsAtCarryingValue": (A_CUR, "现金及现金等价物 Cash and cash equivalents"),
    "us-gaap_MarketableSecuritiesCurrent": (A_CUR, "短期投资 Short-term investments"),
    "us-gaap_ShortTermInvestments": (A_CUR, "短期投资 Short-term investments"),
    "us-gaap_RestrictedCashAndCashEquivalentsAtCarryingValue": (A_CUR, "受限现金-流动 Restricted cash, current"),
    "us-gaap_RestrictedCashCurrent": (A_CUR, "受限现金-流动 Restricted cash, current"),
    "us-gaap_RestrictedCashAndInvestmentsCurrent": (A_CUR, "受限现金-流动 Restricted cash, current"),
    "us-gaap_AccountsReceivableNetCurrent": (A_CUR, "应收账款净额 Accounts receivable, net"),
    "us-gaap_InventoryNet": (A_CUR, "存货 Inventory"),
    "us-gaap_PrepaidExpenseAndOtherAssetsCurrent": (A_CUR, "预付及其他流动资产 Prepaid expenses and other current assets"),
    "us-gaap_AssetsCurrent": (TOT, "流动资产合计 Total current assets"),

    "us-gaap_PropertySubjectToOrAvailableForOperatingLeaseNet@operating lease vehicles":
        (A_NON, "经营租赁车辆净额 Operating lease vehicles, net"),
    "us-gaap_PropertySubjectToOrAvailableForOperatingLeaseNet@solar energy systems":
        (A_NON, "太阳能/储能系统净额 Solar & energy generation and storage systems, net"),
    "us-gaap_PropertySubjectToOrAvailableForOperatingLeaseNet": (A_NON, "经营租赁车辆净额 Operating lease vehicles, net"),
    "us-gaap_DeferredCostsLeasingNetNoncurrent": (A_NON, "经营租赁车辆净额 Operating lease vehicles, net"),
    "tsla_LeasedAssetsNet": (A_NON, "太阳能/储能系统净额 Solar & energy generation and storage systems, net"),
    "us-gaap_PropertyPlantAndEquipmentNet": (A_NON, "固定资产净额 Property, plant and equipment, net"),
    "us-gaap_PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization":
        (A_NON, "固定资产净额 Property, plant and equipment, net"),
    "us-gaap_OperatingLeaseRightOfUseAsset": (A_NON, "经营租赁使用权资产 Operating lease ROU assets"),
    "tsla_DigitalAssetsNetNonCurrent": (A_NON, "数字资产 Digital assets"),
    "us-gaap_CryptoAssetFairValueNoncurrent": (A_NON, "数字资产 Digital assets"),
    "us-gaap_IntangibleAssetsNetExcludingGoodwill": (A_NON, "无形资产净额 Intangible assets, net"),
    "us-gaap_Goodwill": (A_NON, "商誉 Goodwill"),
    "us-gaap_DeferredIncomeTaxAssetsNet": (A_NON, "递延所得税资产 Deferred tax assets"),
    "us-gaap_LongTermAccountsNotesAndLoansReceivableNetNoncurrent": (A_NON, "MyPower客户应收票据 MyPower notes receivable"),
    "us-gaap_RestrictedCashAndCashEquivalentsNoncurrent": (A_NON, "受限现金-非流动 Restricted cash, non-current"),
    "us-gaap_RestrictedCashNoncurrent": (A_NON, "受限现金-非流动 Restricted cash, non-current"),
    "us-gaap_OtherAssetsNoncurrent": (A_NON, "其他非流动资产 Other non-current assets"),
    "us-gaap_Assets": (TOT, "资产总计 Total assets"),

    "us-gaap_AccountsPayableCurrent": (L_CUR, "应付账款 Accounts payable"),
    "us-gaap_AccruedLiabilitiesCurrent": (L_CUR, "应计负债及其他 Accrued liabilities and other"),
    "tsla_AccruedAndOtherCurrentLiabilities": (L_CUR, "应计负债及其他 Accrued liabilities and other"),
    "us-gaap_DeferredRevenueCurrent": (L_CUR, "递延收入-流动 Deferred revenue, current"),
    "us-gaap_ContractWithCustomerLiabilityCurrent": (L_CUR, "递延收入-流动 Deferred revenue, current"),
    "tsla_ResaleValueGuaranteesCurrentPortion": (L_CUR, "转售价值担保-流动 Resale value guarantees, current"),
    "us-gaap_CustomerDepositsCurrent": (L_CUR, "客户存款 Customer deposits"),
    "tsla_CustomerDepositsLiabilitiesCurrent": (L_CUR, "客户存款 Customer deposits"),
    "us-gaap_CustomerAdvancesCurrent": (L_CUR, "可退还预订金 Refundable reservation payments"),
    "us-gaap_CapitalLeaseObligationsCurrent": (L_CUR, "融资租赁负债-流动 Capital lease obligations, current"),
    "us-gaap_LongTermDebtCurrent": (L_CUR, "债务-流动 Debt, current portion"),
    "us-gaap_ConvertibleDebtCurrent": (L_CUR, "债务-流动 Debt, current portion"),
    "us-gaap_ConvertibleNotesPayableCurrent": (L_CUR, "债务-流动 Debt, current portion"),
    "us-gaap_LongTermDebtAndCapitalLeaseObligationsCurrent": (L_CUR, "债务及租赁负债-流动 Debt and capital/finance leases, current"),
    "tsla_LongTermDebtAndFinanceLeasesCurrent": (L_CUR, "债务及租赁负债-流动 Debt and capital/finance leases, current"),
    "us-gaap_DueToRelatedPartiesCurrent": (L_CUR, "太阳能债/关联方票据-流动 Solar bonds & related-party notes, current"),
    "us-gaap_LiabilitiesCurrent": (TOT, "流动负债合计 Total current liabilities"),

    "us-gaap_DerivativeLiabilitiesNoncurrent": (L_NON, "普通股认股权证负债 Common stock warrant liability"),
    "us-gaap_CapitalLeaseObligationsNoncurrent": (L_NON, "融资租赁负债-非流动 Capital lease obligations, non-current"),
    "us-gaap_LongTermDebtNoncurrent": (L_NON, "债务-非流动 Debt, non-current"),
    "us-gaap_ConvertibleDebtNoncurrent": (L_NON, "债务-非流动 Debt, non-current"),
    "us-gaap_ConvertibleLongTermNotesPayable": (L_NON, "债务-非流动 Debt, non-current"),
    "us-gaap_LongTermDebtAndCapitalLeaseObligations": (L_NON, "债务及租赁负债-非流动 Debt and capital/finance leases, non-current"),
    "tsla_LongTermDebtAndFinanceLeasesNoncurrent": (L_NON, "债务及租赁负债-非流动 Debt and capital/finance leases, non-current"),
    "tsla_ConvertibleSeniorNotesIssueToRelatedPartiesNonCurrent": (L_NON, "关联方可转债-非流动 Convertible notes to related parties, non-current"),
    "us-gaap_DueToRelatedPartiesNoncurrent": (L_NON, "太阳能债(关联方)-非流动 Solar bonds to related parties, non-current"),
    "us-gaap_DeferredRevenueNoncurrent": (L_NON, "递延收入-非流动 Deferred revenue, non-current"),
    "us-gaap_ContractWithCustomerLiabilityNoncurrent": (L_NON, "递延收入-非流动 Deferred revenue, non-current"),
    "tsla_ResaleValueGuarantee": (L_NON, "转售价值担保-非流动 Resale value guarantees, non-current"),
    "tsla_ResaleValueGuaranteesNoncurrentPortion": (L_NON, "转售价值担保-非流动 Resale value guarantees, non-current"),
    "us-gaap_OtherLiabilitiesNoncurrent": (L_NON, "其他长期负债 Other long-term liabilities"),
    "us-gaap_Liabilities": (TOT, "负债合计 Total liabilities"),

    "us-gaap_RedeemableNoncontrollingInterestEquityCarryingAmount": (MEZ, "夹层-可赎回非控股权益 Redeemable NCI"),
    "us-gaap_DebtInstrumentConvertibleCarryingAmountOfTheEquityComponent": (MEZ, "夹层-可转债权益成分 Convertible notes equity component"),
    "us-gaap_TemporaryEquityCarryingAmountAttributableToParent": (MEZ, "夹层-可转债权益成分 Convertible notes equity component"),

    "us-gaap_PreferredStockValue": (EQ, "优先股 Preferred stock"),
    "us-gaap_CommonStockValue": (EQ, "普通股 Common stock"),
    "us-gaap_AdditionalPaidInCapital": (EQ, "资本公积 Additional paid-in capital"),
    "us-gaap_AdditionalPaidInCapitalCommonStock": (EQ, "资本公积 Additional paid-in capital"),
    "us-gaap_AccumulatedOtherComprehensiveIncomeLossNetOfTax": (EQ, "累计其他综合收益 Accumulated OCI"),
    "us-gaap_RetainedEarningsAccumulatedDeficit": (EQ, "累计亏损/留存收益 Accumulated deficit / Retained earnings"),
    "us-gaap_StockholdersEquity": (TOT, "归母股东权益 Total stockholders' equity"),
    "us-gaap_MinorityInterest": (TOT, "非控股权益 Noncontrolling interests"),
    "us-gaap_LiabilitiesAndStockholdersEquity": (TOT, "负债和权益合计 Total liabilities and equity"),
}
BS_IGNORE = {"us-gaap_CommitmentsAndContingencies"}
BS_ROWS = ["现金及现金等价物 Cash and cash equivalents", "短期投资 Short-term investments",
           "受限现金-流动 Restricted cash, current", "应收账款净额 Accounts receivable, net", "存货 Inventory",
           "预付及其他流动资产 Prepaid expenses and other current assets", "流动资产合计 Total current assets",
           "经营租赁车辆净额 Operating lease vehicles, net",
           "太阳能/储能系统净额 Solar & energy generation and storage systems, net",
           "固定资产净额 Property, plant and equipment, net", "经营租赁使用权资产 Operating lease ROU assets",
           "数字资产 Digital assets", "无形资产净额 Intangible assets, net", "商誉 Goodwill",
           "递延所得税资产 Deferred tax assets", "MyPower客户应收票据 MyPower notes receivable",
           "受限现金-非流动 Restricted cash, non-current", "其他非流动资产 Other non-current assets",
           "资产总计 Total assets",
           "应付账款 Accounts payable", "应计负债及其他 Accrued liabilities and other",
           "递延开发补偿 Deferred development compensation", "递延收入-流动 Deferred revenue, current",
           "转售价值担保-流动 Resale value guarantees, current", "客户存款 Customer deposits",
           "可退还预订金 Refundable reservation payments", "融资租赁负债-流动 Capital lease obligations, current",
           "债务-流动 Debt, current portion", "债务及租赁负债-流动 Debt and capital/finance leases, current",
           "太阳能债/关联方票据-流动 Solar bonds & related-party notes, current", "流动负债合计 Total current liabilities",
           "普通股认股权证负债 Common stock warrant liability",
           "可转换优先股认股权证负债 Convertible preferred stock warrant liability",
           "融资租赁负债-非流动 Capital lease obligations, non-current", "债务-非流动 Debt, non-current",
           "债务及租赁负债-非流动 Debt and capital/finance leases, non-current",
           "关联方可转债-非流动 Convertible notes to related parties, non-current",
           "太阳能债(关联方)-非流动 Solar bonds to related parties, non-current",
           "递延收入-非流动 Deferred revenue, non-current", "转售价值担保-非流动 Resale value guarantees, non-current",
           "其他长期负债 Other long-term liabilities", "负债合计 Total liabilities",
           "夹层-可转换优先股 Convertible preferred stock (mezzanine)", "夹层-可赎回非控股权益 Redeemable NCI",
           "夹层-可转债权益成分 Convertible notes equity component",
           "优先股 Preferred stock", "普通股 Common stock", "资本公积 Additional paid-in capital",
           "累计其他综合收益 Accumulated OCI", "累计亏损/留存收益 Accumulated deficit / Retained earnings",
           "归母股东权益 Total stockholders' equity", "非控股权益 Noncontrolling interests",
           "权益合计 Total equity", "负债和权益合计 Total liabilities and equity"]

# ══════════════════════════════════════════════════════════════════
# 3. 现金流量表：tag → (段, canonical)。段用于「分项和 = 该段净额」勾稽
# ══════════════════════════════════════════════════════════════════
OP, INV, FIN, TAIL, SUP = "经营", "投资", "融资", "尾部", "补充"
CF_TAGS = {
    "us-gaap_NetIncomeLoss": (OP, "净利润 Net income (loss)"),
    "us-gaap_ProfitLoss": (OP, "净利润 Net income (loss)"),
    "us-gaap_DepreciationAndAmortization": (OP, "折旧摊销(及减值) Depreciation, amortization (and impairment)"),
    "tsla_DepreciationAmortizationAndImpairment": (OP, "折旧摊销(及减值) Depreciation, amortization (and impairment)"),
    "us-gaap_ShareBasedCompensation": (OP, "股份支付 Stock-based compensation"),
    "us-gaap_InventoryWriteDown": (OP, "存货(及采购承诺)减值 Inventory write-downs"),
    "us-gaap_DeferredIncomeTaxExpenseBenefit": (OP, "递延所得税 Deferred income taxes"),
    "tsla_AmortizationOfDebtDiscountLessCapitalizedInterest": (OP, "债务折价及发行费摊销 Amortization of debt discounts"),
    "us-gaap_AmortizationOfFinancingCostsAndDiscounts": (OP, "债务折价及发行费摊销 Amortization of debt discounts"),
    "us-gaap_AmortizationOfDebtDiscountPremium": (OP, "债务折价及发行费摊销 Amortization of debt discounts"),
    "us-gaap_ForeignCurrencyTransactionGainLossUnrealized": (OP, "外币交易损益 Foreign currency transaction (gain) loss"),
    "us-gaap_ForeignCurrencyTransactionGainLossRealized": (OP, "外币交易损益 Foreign currency transaction (gain) loss"),
    "us-gaap_ForeignCurrencyTransactionGainLossBeforeTax": (OP, "外币交易损益 Foreign currency transaction (gain) loss"),
    "tsla_GainOnDigitalAssets": (OP, "数字资产损益 Digital assets loss (gain), net"),
    "tsla_GainLossOnDigitalAssets": (OP, "数字资产损益 Digital assets loss (gain), net"),
    "tsla_NoncashInterestIncomeExpenseAndOtherOperatingActivities": (OP, "非现金利息及其他 Non-cash interest and other"),
    "us-gaap_UnrealizedGainLossOnDerivatives": (OP, "其他非现金调整项 Other non-cash adjustments"),
    "us-gaap_AccretionAmortizationOfDiscountsAndPremiumsInvestments": (OP, "其他非现金调整项 Other non-cash adjustments"),
    "tsla_GainOnExtinguishmentOfConvertibleNotesAndWarrants": (OP, "其他非现金调整项 Other non-cash adjustments"),
    "tsla_WriteOffOfLoanOriginationCosts": (OP, "其他非现金调整项 Other non-cash adjustments"),
    "us-gaap_GainLossOnSaleOfPropertyPlantEquipment": (OP, "其他非现金调整项 Other non-cash adjustments"),
    "us-gaap_GainLossOnDispositionOfProperty": (OP, "其他非现金调整项 Other non-cash adjustments"),
    "us-gaap_GainLossOnDispositionOfAssets1": (OP, "其他非现金调整项 Other non-cash adjustments"),
    "us-gaap_ExcessTaxBenefitFromShareBasedCompensationOperatingActivities": (OP, "其他非现金调整项 Other non-cash adjustments"),
    "us-gaap_AdjustmentsNoncashItemsToReconcileNetIncomeLossToCashProvidedByUsedInOperatingActivities": (OP, "其他非现金调整项 Other non-cash adjustments"),
    "us-gaap_OtherNoncashIncomeExpense": (OP, "其他非现金调整项 Other non-cash adjustments"),
    "tsla_GainsLossOnAcquisition": (OP, "其他非现金调整项 Other non-cash adjustments"),
    "tsla_OperatingCashFlowRelatedToRepaymentOfDiscountedConvertibleSeniorNotes": (OP, "其他非现金调整项 Other non-cash adjustments"),
    "tsla_OperatingCashFlowRelatedToRepaymentOfDiscountedConvertibleNotes": (OP, "其他非现金调整项 Other non-cash adjustments"),
    "us-gaap_IncreaseDecreaseInAccountsReceivable": (OP, "营运资金-应收账款 Accounts receivable"),
    "us-gaap_IncreaseDecreaseInInventories": (OP, "营运资金-存货 Inventory"),
    "tsla_IncreaseDecreaseInInventoriesAndPropertySubjectToOrAvailableForOperatingLease": (OP, "营运资金-存货及经营租赁车辆(合并列示年份) Inventories and operating lease vehicles"),
    "tsla_IncreaseDecreaseInOperatingLeaseVehicles": (OP, "营运资金-经营租赁车辆 Operating lease vehicles"),
    "us-gaap_IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets": (OP, "营运资金-预付及其他资产 Prepaid expenses and other assets"),
    "us-gaap_IncreaseDecreaseInOtherOperatingAssets": (OP, "营运资金-其他资产 Other assets"),
    "us-gaap_IncreaseDecreaseInOtherNoncurrentAssets": (OP, "营运资金-其他资产 Other assets"),
    "tsla_IncreaseDecreaseInOtherOperatingAssetsAndNotesReceivables": (OP, "营运资金-其他资产 Other assets"),
    "us-gaap_IncreaseDecreaseInNotesReceivables": (OP, "营运资金-其他资产 Other assets"),
    "us-gaap_IncreaseDecreaseInAccountsPayable": (OP, "营运资金-应付账款及应计负债 Accounts payable & accrued liabilities"),
    "us-gaap_IncreaseDecreaseInAccountsPayableAndAccruedLiabilities": (OP, "营运资金-应付账款及应计负债 Accounts payable & accrued liabilities"),
    "us-gaap_IncreaseDecreaseInAccruedLiabilities": (OP, "营运资金-应计负债 Accrued liabilities"),
    "us-gaap_IncreaseDecreaseInDeferredRevenue": (OP, "营运资金-递延收入 Deferred revenue"),
    "us-gaap_IncreaseDecreaseInContractWithCustomerLiability": (OP, "营运资金-递延收入 Deferred revenue"),
    "tsla_IncreaseDecreaseInDeferredDevelopmentCompensation": (OP, "营运资金-递延开发补偿 Deferred development compensation"),
    "tsla_IncreaseDecreaseInContractWithCustomerLiabilityCustomerDeposits": (OP, "营运资金-客户存款 Customer deposits"),
    "us-gaap_IncreaseDecreaseInDeferredRevenueAndCustomerAdvancesAndDeposits": (OP, "营运资金-预订金/客户存款 Reservation payments & customer deposits"),
    "tsla_IncreaseDecreaseInResaleValueGuarantee": (OP, "营运资金-转售价值担保 Resale value guarantee"),
    "us-gaap_IncreaseDecreaseInOtherNoncurrentLiabilities": (OP, "营运资金-其他长期负债 Other long-term liabilities"),
    "us-gaap_NetCashProvidedByUsedInOperatingActivities": (TOT, "经营活动现金流净额 Net cash from operating activities"),
    "us-gaap_NetCashProvidedByUsedInOperatingActivitiesContinuingOperations": (TOT, "经营活动现金流净额 Net cash from operating activities"),

    "us-gaap_PaymentsToAcquirePropertyPlantAndEquipment": (INV, "购建固定资产(capex) Purchases of property and equipment"),
    "tsla_PaymentsForSolarEnergySystemsNetOfSales": (INV, "购建太阳能系统 Purchases of solar energy systems"),
    "tsla_PaymentsForSolarEnergySystemsLeasedAndToBeLeased": (INV, "购建太阳能系统 Purchases of solar energy systems"),
    "tsla_PaymentsForSolarEnergySystems": (INV, "购建太阳能系统 Purchases of solar energy systems"),
    "us-gaap_PaymentsToAcquireInvestments": (INV, "购买投资 Purchases of investments"),
    "us-gaap_PaymentsToAcquireMarketableSecurities": (INV, "购买投资 Purchases of investments"),
    "us-gaap_ProceedsFromSaleMaturityAndCollectionsOfInvestments": (INV, "投资到期收回 Proceeds from maturities of investments"),
    "us-gaap_ProceedsFromSaleAndMaturityOfMarketableSecurities": (INV, "投资到期收回 Proceeds from maturities of investments"),
    "us-gaap_ProceedsFromMaturitiesPrepaymentsAndCallsOfAvailableForSaleSecurities": (INV, "投资到期收回 Proceeds from maturities of investments"),
    "us-gaap_ProceedsFromSaleOfShortTermInvestments": (INV, "出售投资收到 Proceeds from sales of investments"),
    "tsla_PurchaseOfDigitalAssets": (INV, "购买数字资产 Purchases of digital assets"),
    "tsla_ProceedsFromSalesOfDigitalAssets": (INV, "出售数字资产 Proceeds from sales of digital assets"),
    "us-gaap_PaymentsToAcquireIntangibleAssets": (INV, "购买无形资产 Purchase of intangible assets"),
    "tsla_PaymentsToAcquireOtherIndefiniteLivedIntangibleAssets": (INV, "购买无形资产 Purchase of intangible assets"),
    "tsla_GovernmentGrantReceipt": (INV, "收到政府补助 Receipt of government grants"),
    "us-gaap_PaymentsToAcquireBusinessesNetOfCashAcquired": (INV, "业务合并 Business combinations, net of cash acquired"),
    "us-gaap_PaymentsToAcquireAssetsInvestingActivities": (INV, "收购 Fremont 工厂 Fremont facility acquisition"),
    "tsla_IncreaseDecreaseInRestrictedCashAndCashEquivalents": (INV, "受限现金/DOE专户变动 Restricted cash & DOE account, net"),
    "us-gaap_IncreaseDecreaseInRestrictedCash": (INV, "受限现金/DOE专户变动 Restricted cash & DOE account, net"),
    "us-gaap_NetCashProvidedByUsedInInvestingActivities": (TOT, "投资活动现金流净额 Net cash from investing activities"),
    "us-gaap_NetCashProvidedByUsedInInvestingActivitiesContinuingOperations": (TOT, "投资活动现金流净额 Net cash from investing activities"),

    "us-gaap_ProceedsFromIssuanceOfDebt": (FIN, "发债/借款所得 Proceeds from issuances of debt"),
    "us-gaap_ProceedsFromConvertibleDebt": (FIN, "发债/借款所得 Proceeds from issuances of debt"),
    "tsla_ProceedsFromConvertibleAndOtherDebt": (FIN, "发债/借款所得 Proceeds from issuances of debt"),
    "us-gaap_ProceedsFromIssuanceOfLongTermDebt": (FIN, "发债/借款所得 Proceeds from issuances of debt"),
    "tsla_ProceedsFromIssuanceOfConvertibleNotesAndWarrants": (FIN, "发债/借款所得 Proceeds from issuances of debt"),
    "us-gaap_RepaymentsOfDebt": (FIN, "偿还债务 Repayments of debt"),
    "us-gaap_RepaymentsOfConvertibleDebt": (FIN, "偿还债务 Repayments of debt"),
    "tsla_RepaymentsOfConvertibleAndOtherDebt": (FIN, "偿还债务 Repayments of debt"),
    "us-gaap_RepaymentsOfLongTermDebt": (FIN, "偿还债务 Repayments of debt"),
    "us-gaap_RepaymentsOfRelatedPartyDebt": (FIN, "偿还关联方借款 Repayments of related-party borrowings"),
    "us-gaap_ProceedsFromIssuanceOfCommonStock": (FIN, "发行普通股所得 Proceeds from issuance of common stock"),
    "tsla_ProceedsFromIssuancePublicOffering": (FIN, "发行普通股所得 Proceeds from issuance of common stock"),
    "us-gaap_ProceedsFromIssuanceInitialPublicOffering": (FIN, "发行普通股所得 Proceeds from issuance of common stock"),
    "us-gaap_ProceedsFromIssuanceOfPrivatePlacement": (FIN, "定向增发所得 Proceeds from private placements"),
    "us-gaap_ProceedsFromIssuanceOfSharesUnderIncentiveAndShareBasedCompensationPlansIncludingStockOptions":
        (FIN, "期权行权及员工购股 Proceeds from stock option exercises"),
    "us-gaap_ExcessTaxBenefitFromShareBasedCompensationFinancingActivities": (FIN, "期权行权及员工购股 Proceeds from stock option exercises"),
    "us-gaap_FinanceLeasePrincipalPayments": (FIN, "融资/资本租赁本金支付 Principal payments on finance/capital leases"),
    "us-gaap_ProceedsFromRepaymentsOfLongTermDebtAndCapitalSecurities": (FIN, "融资/资本租赁本金支付 Principal payments on finance/capital leases"),
    "us-gaap_ProceedsFromRepaymentsOfSecuredDebt": (FIN, "抵押租赁借款(净) Collateralized lease borrowings (repayments)"),
    "us-gaap_ProceedsFromSecuredNotesPayable": (FIN, "抵押租赁借款(净) Collateralized lease borrowings (repayments)"),
    "us-gaap_ProceedsFromIssuanceOfWarrants": (FIN, "可转债对冲及权证 Convertible note hedges & warrants"),
    "us-gaap_PaymentsForHedgeFinancingActivities": (FIN, "可转债对冲及权证 Convertible note hedges & warrants"),
    "us-gaap_PaymentsForProceedsFromHedgeFinancingActivities": (FIN, "可转债对冲及权证 Convertible note hedges & warrants"),
    "us-gaap_ProceedsFromHedgeFinancingActivities": (FIN, "可转债对冲及权证 Convertible note hedges & warrants"),
    "us-gaap_PaymentsForRepurchaseOfWarrants": (FIN, "可转债对冲及权证 Convertible note hedges & warrants"),
    "tsla_SettlementPurchaseOfNoteHedge": (FIN, "可转债对冲及权证 Convertible note hedges & warrants"),
    "us-gaap_PaymentsOfDebtIssuanceCosts": (FIN, "发行费用 Debt & stock issuance costs"),
    "us-gaap_PaymentsOfFinancingCosts": (FIN, "发行费用 Debt & stock issuance costs"),
    "us-gaap_PaymentsOfStockIssuanceCosts": (FIN, "发行费用 Debt & stock issuance costs"),
    "us-gaap_PaymentOfFinancingAndStockIssuanceCosts": (FIN, "发行费用 Debt & stock issuance costs"),
    "us-gaap_PaymentsToMinorityShareholders": (FIN, "支付非控股权益分配 Distributions to NCI"),
    "us-gaap_ProceedsFromMinorityShareholders": (FIN, "非控股权益投入 Investments by NCI"),
    "tsla_PaymentsForBuyOutsOfNoncontrollingInterestsInSubsidiaries": (FIN, "买断非控股权益 Buy-outs of NCI"),
    "tsla_ProceedsReceivedFromDirectorsInShareholderSettlement": (FIN, "股东诉讼和解收付 Shareholder settlement"),
    "tsla_PaymentForLegalFees": (FIN, "股东诉讼和解收付 Shareholder settlement"),
    "us-gaap_ProceedsFromIssuanceOfConvertiblePreferredStock": (FIN, "发行可转换优先股 Proceeds from convertible preferred stock"),
    "us-gaap_NetCashProvidedByUsedInFinancingActivities": (TOT, "融资活动现金流净额 Net cash from financing activities"),
    "us-gaap_NetCashProvidedByUsedInFinancingActivitiesContinuingOperations": (TOT, "融资活动现金流净额 Net cash from financing activities"),

    "us-gaap_EffectOfExchangeRateOnCashAndCashEquivalents": (TAIL, "汇率影响 Effect of exchange rate changes"),
    "us-gaap_EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations":
        (TAIL, "汇率影响 Effect of exchange rate changes"),
    "us-gaap_CashAndCashEquivalentsPeriodIncreaseDecrease": (TAIL, "现金净变动 Net increase (decrease) in cash"),
    "us-gaap_CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect":
        (TAIL, "现金净变动 Net increase (decrease) in cash"),

    "us-gaap_InterestPaid": (SUP, "补充-已付利息 Cash paid for interest"),
    "us-gaap_InterestPaidNet": (SUP, "补充-已付利息 Cash paid for interest"),
    "us-gaap_IncomeTaxesPaid": (SUP, "补充-已付所得税 Cash paid for income taxes"),
    "us-gaap_NoncashOrPartNoncashAcquisitionValueOfAssetsAcquired1": (SUP, "补充-非现金:应付项下购建固定资产 PP&E in liabilities"),
    "tsla_NonCashEstimatedFairMarketValueOfManufacturingFacility": (SUP, "补充-非现金:build-to-suit 租赁设施 Build-to-suit facilities"),
    "us-gaap_BusinessCombinationConsiderationTransferredEquityInterestsIssuedAndIssuable": (SUP, "补充-非现金:业务合并发行权益 Equity issued in business combination"),
    "tsla_SharesIssuedInConnectionOfBusinessCombinationAndAssumedVestedAwards": (SUP, "补充-非现金:业务合并发行权益 Equity issued in business combination"),
    "us-gaap_ConversionOfStockAmountConverted1": (SUP, "补充-非现金:优先股转普通股 Conversion of preferred to common"),
    "us-gaap_DebtConversionConvertedInstrumentAmount1": (SUP, "补充-非现金:票据转优先股 Notes converted to preferred"),
    "tsla_StockIssuedDuringPeriodNetExerciseOfConvertibleSecuritiesAmount": (SUP, "补充-非现金:权证净行权发普通股 Stock issued on net exercise of warrants"),
    "tsla_IssuanceOfConvertiblePreferredStockWarrantAmount": (SUP, "补充-非现金:发行认股权证 Warrants issued"),
    "tsla_IssuanceOfCommonStockWarrantAmount": (SUP, "补充-非现金:发行认股权证 Warrants issued"),
    "tsla_DebtConversionConvertedInstrumentWarrantsOrOptionsIssuedAmountConverted": (SUP, "补充-非现金:可转换票据交换 Exchange of convertible notes"),
    "tsla_ExchangeOfAccruedInterestForConvertibleNotesPayable": (SUP, "补充-非现金:可转换票据交换 Exchange of convertible notes"),
}
# 现金期初/期末共用一个 tag，靠标签里的 beginning/end 区分
CF_CASH_TAGS = {"us-gaap_CashAndCashEquivalentsAtCarryingValue",
                "us-gaap_CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations"}
CF_ROWS = ["净利润 Net income (loss)", "折旧摊销(及减值) Depreciation, amortization (and impairment)",
           "股份支付 Stock-based compensation", "存货(及采购承诺)减值 Inventory write-downs",
           "债务折价及发行费摊销 Amortization of debt discounts", "递延所得税 Deferred income taxes",
           "外币交易损益 Foreign currency transaction (gain) loss", "数字资产损益 Digital assets loss (gain), net",
           "非现金利息及其他 Non-cash interest and other", "其他非现金调整项 Other non-cash adjustments",
           "营运资金-应收账款 Accounts receivable", "营运资金-存货 Inventory",
           "营运资金-存货及经营租赁车辆(合并列示年份) Inventories and operating lease vehicles",
           "营运资金-经营租赁车辆 Operating lease vehicles", "营运资金-预付及其他资产 Prepaid expenses and other assets",
           "营运资金-其他资产 Other assets", "营运资金-应付账款及应计负债 Accounts payable & accrued liabilities",
           "营运资金-应计负债 Accrued liabilities", "营运资金-递延收入 Deferred revenue",
           "营运资金-递延开发补偿 Deferred development compensation", "营运资金-客户存款 Customer deposits",
           "营运资金-预订金/客户存款 Reservation payments & customer deposits",
           "营运资金-转售价值担保 Resale value guarantee", "营运资金-其他长期负债 Other long-term liabilities",
           "经营活动现金流净额 Net cash from operating activities",
           "购建固定资产(capex) Purchases of property and equipment", "购建太阳能系统 Purchases of solar energy systems",
           "购买投资 Purchases of investments", "投资到期收回 Proceeds from maturities of investments",
           "出售投资收到 Proceeds from sales of investments", "购买数字资产 Purchases of digital assets",
           "出售数字资产 Proceeds from sales of digital assets", "购买无形资产 Purchase of intangible assets",
           "收到政府补助 Receipt of government grants", "业务合并 Business combinations, net of cash acquired",
           "收购 Fremont 工厂 Fremont facility acquisition", "受限现金/DOE专户变动 Restricted cash & DOE account, net",
           "投资活动现金流净额 Net cash from investing activities",
           "发债/借款所得 Proceeds from issuances of debt", "偿还债务 Repayments of debt",
           "偿还关联方借款 Repayments of related-party borrowings", "发行普通股所得 Proceeds from issuance of common stock",
           "定向增发所得 Proceeds from private placements", "发行可转换优先股 Proceeds from convertible preferred stock",
           "期权行权及员工购股 Proceeds from stock option exercises",
           "融资/资本租赁本金支付 Principal payments on finance/capital leases",
           "抵押租赁借款(净) Collateralized lease borrowings (repayments)",
           "可转债对冲及权证 Convertible note hedges & warrants", "发行费用 Debt & stock issuance costs",
           "支付非控股权益分配 Distributions to NCI", "非控股权益投入 Investments by NCI",
           "买断非控股权益 Buy-outs of NCI", "股东诉讼和解收付 Shareholder settlement",
           "融资活动现金流净额 Net cash from financing activities",
           "汇率影响 Effect of exchange rate changes", "现金净变动 Net increase (decrease) in cash",
           "期初现金 Cash at beginning of period", "期末现金 Cash at end of period",
           "补充-已付利息 Cash paid for interest", "补充-已付所得税 Cash paid for income taxes",
           "补充-非现金:应付项下购建固定资产 PP&E in liabilities",
           "补充-非现金:build-to-suit 租赁设施 Build-to-suit facilities",
           "补充-非现金:业务合并发行权益 Equity issued in business combination",
           "补充-非现金:优先股转普通股 Conversion of preferred to common",
           "补充-非现金:票据转优先股 Notes converted to preferred",
           "补充-非现金:权证净行权发普通股 Stock issued on net exercise of warrants",
           "补充-非现金:发行认股权证 Warrants issued",
           "补充-非现金:可转换票据交换 Exchange of convertible notes"]

# ══════════════════════════════════════════════════════════════════
# 4. 前 XBRL 年份手工转录（千美元）
# ══════════════════════════════════════════════════════════════════
def _is(rev, cost, gp, rd, sga, opex, opinc, ii, ie, oth, pbt, tax, ni, eps, sh):
    return {"营业收入 Total revenues": rev, "营业成本 Total cost of revenues": cost, "毛利 Gross profit": gp,
            "研发费用 Research and development": rd, "销售及行政费用 Selling, general and administrative": sga,
            "经营费用合计 Total operating expenses": opex, "经营利润 Income (loss) from operations": opinc,
            "利息收入 Interest income": ii, "利息费用 Interest expense": ie,
            "其他收入(费用)净额 Other income (expense), net": oth,
            "税前利润 Income (loss) before income taxes": pbt,
            "所得税 Provision for (benefit from) income taxes": tax,
            "净利润(含少数股东) Net income (loss)": ni,
            "归母净利润 Net income (loss) attributable to common stockholders": ni,
            "每股收益-基本(美元)": eps, "每股收益-稀释(美元)": eps,
            "加权平均股数-基本(千股)": sh, "加权平均股数-稀释(千股)": sh}


EARLY_IS = {   # 424B4 五年 Selected Financial Data(2005/2006) + 经审计损益表(2007-2009)；10-K FY2010(2010)
    2005: _is(None, None, None, -10009, -1820, -11829, -11829, 224, None, None, -11605, None, -11605, -4.00, 2901.993),
    2006: _is(None, None, None, -24995, -5436, -30431, -30431, 938, -423, 59, -29857, -100, -29957, -10.18, 2941.411),
    2007: _is(73, -9, 64, -62753, -17244, -79997, -79933, 1749, None, 137, -78047, -110, -78157, -22.69, 3443.806),
    2008: _is(14742, -15883, -1141, -53714, -23649, -77363, -78504, 529, -3747, -963, -82685, -97, -82782, -12.46, 6646.387),
    2009: _is(111943, -102408, 9535, -19282, -42150, -61432, -51897, 159, -2531, -1445, -55714, -26, -55740, -7.94, 7021.963),
    2010: _is(116744, -86013, 30731, -92996, -84573, -177569, -146838, 258, -992, -6583, -154155, -173, -154328, -3.04, 50718.302),
}
EARLY_BS = {   # 424B4 经审计资产负债表(2008/2009)；10-K FY2010(2010)。印刷原值
    2008: {"现金及现金等价物 Cash and cash equivalents": 9277, "应收账款净额 Accounts receivable, net": 3320,
           "存货 Inventory": 16650, "预付及其他流动资产 Prepaid expenses and other current assets": 2180,
           "流动资产合计 Total current assets": 31427, "固定资产净额 Property, plant and equipment, net": 18793,
           "受限现金-非流动 Restricted cash, non-current": 1220, "其他非流动资产 Other non-current assets": 259,
           "资产总计 Total assets": 51699,
           "应付账款 Accounts payable": 14184, "应计负债及其他 Accrued liabilities and other": 11145,
           "递延开发补偿 Deferred development compensation": 10173, "递延收入-流动 Deferred revenue, current": 4073,
           "融资租赁负债-流动 Capital lease obligations, current": 341,
           "可退还预订金 Refundable reservation payments": 48019, "流动负债合计 Total current liabilities": 87935,
           "可转换优先股认股权证负债 Convertible preferred stock warrant liability": 2074,
           "融资租赁负债-非流动 Capital lease obligations, non-current": 888,
           "债务-非流动 Debt, non-current": 54528, "其他长期负债 Other long-term liabilities": 4810,
           "负债合计 Total liabilities": 150235,
           "夹层-可转换优先股 Convertible preferred stock (mezzanine)": 101178,
           "普通股 Common stock": 7, "资本公积 Additional paid-in capital": 5193,
           "累计亏损/留存收益 Accumulated deficit / Retained earnings": -204914,
           "归母股东权益 Total stockholders' equity": -199714, "权益合计 Total equity": -199714,
           "负债和权益合计 Total liabilities and equity": 51699},
    2009: {"现金及现金等价物 Cash and cash equivalents": 69627, "应收账款净额 Accounts receivable, net": 3488,
           "存货 Inventory": 23222, "预付及其他流动资产 Prepaid expenses and other current assets": 4222,
           "流动资产合计 Total current assets": 100559, "固定资产净额 Property, plant and equipment, net": 23535,
           "受限现金-非流动 Restricted cash, non-current": 3580, "其他非流动资产 Other non-current assets": 2750,
           "资产总计 Total assets": 130424,
           "应付账款 Accounts payable": 15086, "应计负债及其他 Accrued liabilities and other": 14532,
           "递延开发补偿 Deferred development compensation": 156, "递延收入-流动 Deferred revenue, current": 1377,
           "融资租赁负债-流动 Capital lease obligations, current": 290,
           "可退还预订金 Refundable reservation payments": 26048, "流动负债合计 Total current liabilities": 57489,
           "可转换优先股认股权证负债 Convertible preferred stock warrant liability": 1734,
           "融资租赁负债-非流动 Capital lease obligations, non-current": 800,
           "递延收入-非流动 Deferred revenue, non-current": 1240, "其他长期负债 Other long-term liabilities": 3459,
           "负债合计 Total liabilities": 64722,
           "夹层-可转换优先股 Convertible preferred stock (mezzanine)": 319225,
           "普通股 Common stock": 7, "资本公积 Additional paid-in capital": 7124,
           "累计亏损/留存收益 Accumulated deficit / Retained earnings": -260654,
           "归母股东权益 Total stockholders' equity": -253523, "权益合计 Total equity": -253523,
           "负债和权益合计 Total liabilities and equity": 130424},
    2010: {"现金及现金等价物 Cash and cash equivalents": 99558, "受限现金-流动 Restricted cash, current": 73597,
           "应收账款净额 Accounts receivable, net": 6710, "存货 Inventory": 45182,
           "预付及其他流动资产 Prepaid expenses and other current assets": 10839,
           "流动资产合计 Total current assets": 235886,
           "经营租赁车辆净额 Operating lease vehicles, net": 7963,
           "固定资产净额 Property, plant and equipment, net": 114636,
           "受限现金-非流动 Restricted cash, non-current": 4867, "其他非流动资产 Other non-current assets": 22730,
           "资产总计 Total assets": 386082,
           "应付账款 Accounts payable": 28951, "应计负债及其他 Accrued liabilities and other": 20945,
           "递延收入-流动 Deferred revenue, current": 4635,
           "融资租赁负债-流动 Capital lease obligations, current": 279,
           "可退还预订金 Refundable reservation payments": 30755, "流动负债合计 Total current liabilities": 85565,
           "普通股认股权证负债 Common stock warrant liability": 6088,
           "融资租赁负债-非流动 Capital lease obligations, non-current": 496,
           "递延收入-非流动 Deferred revenue, non-current": 2783, "债务-非流动 Debt, non-current": 71828,
           "其他长期负债 Other long-term liabilities": 12274, "负债合计 Total liabilities": 179034,
           "普通股 Common stock": 95, "资本公积 Additional paid-in capital": 621935,
           "累计亏损/留存收益 Accumulated deficit / Retained earnings": -414982,
           "归母股东权益 Total stockholders' equity": 207048, "权益合计 Total equity": 207048,
           "负债和权益合计 Total liabilities and equity": 386082},
}
EARLY_CF = {   # 424B4 经审计现金流量表(2007-2009)；10-K FY2010(2010)。流出=负数
    2007: {"净利润 Net income (loss)": -78157, "折旧摊销(及减值) Depreciation, amortization (and impairment)": 2895,
           "股份支付 Stock-based compensation": 198,
           "经营活动现金流净额 Net cash from operating activities": -53469,
           "购建固定资产(capex) Purchases of property and equipment": -9802,
           "受限现金/DOE专户变动 Restricted cash & DOE account, net": 40,
           "投资活动现金流净额 Net cash from investing activities": -9762,
           "融资活动现金流净额 Net cash from financing activities": 45041,
           "现金净变动 Net increase (decrease) in cash": -18190,
           "期初现金 Cash at beginning of period": 35401, "期末现金 Cash at end of period": 17211,
           "补充-已付利息 Cash paid for interest": 9},
    2008: {"净利润 Net income (loss)": -82782, "折旧摊销(及减值) Depreciation, amortization (and impairment)": 4157,
           "股份支付 Stock-based compensation": 437, "存货(及采购承诺)减值 Inventory write-downs": 4297,
           "经营活动现金流净额 Net cash from operating activities": -52412,
           "购建固定资产(capex) Purchases of property and equipment": -10630,
           "受限现金/DOE专户变动 Restricted cash & DOE account, net": -960,
           "投资活动现金流净额 Net cash from investing activities": -11590,
           "融资活动现金流净额 Net cash from financing activities": 56068,
           "现金净变动 Net increase (decrease) in cash": -7934,
           "期初现金 Cash at beginning of period": 17211, "期末现金 Cash at end of period": 9277,
           "补充-已付利息 Cash paid for interest": 41},
    2009: {"净利润 Net income (loss)": -55740, "折旧摊销(及减值) Depreciation, amortization (and impairment)": 6940,
           "股份支付 Stock-based compensation": 1434, "存货(及采购承诺)减值 Inventory write-downs": 1353,
           "经营活动现金流净额 Net cash from operating activities": -80825,
           "购建固定资产(capex) Purchases of property and equipment": -11884,
           "受限现金/DOE专户变动 Restricted cash & DOE account, net": -2360,
           "投资活动现金流净额 Net cash from investing activities": -14244,
           "融资活动现金流净额 Net cash from financing activities": 155419,
           "现金净变动 Net increase (decrease) in cash": 60350,
           "期初现金 Cash at beginning of period": 9277, "期末现金 Cash at end of period": 69627,
           "补充-已付利息 Cash paid for interest": 70},
    2010: {"净利润 Net income (loss)": -154328, "折旧摊销(及减值) Depreciation, amortization (and impairment)": 10623,
           "股份支付 Stock-based compensation": 21156, "存货(及采购承诺)减值 Inventory write-downs": 951,
           "经营活动现金流净额 Net cash from operating activities": -127817,
           "购建固定资产(capex) Purchases of property and equipment": -40203,
           "收购 Fremont 工厂 Fremont facility acquisition": -65210,
           "受限现金/DOE专户变动 Restricted cash & DOE account, net": -74884,
           "投资活动现金流净额 Net cash from investing activities": -180297,
           "融资活动现金流净额 Net cash from financing activities": 338045,
           "现金净变动 Net increase (decrease) in cash": 29931,
           "期初现金 Cash at beginning of period": 69627, "期末现金 Cash at end of period": 99558,
           "补充-已付利息 Cash paid for interest": 1138},
}

# ══════════════════════════════════════════════════════════════════
# 5. 解析
# ══════════════════════════════════════════════════════════════════
def load(fy):
    return json.load(open(os.path.join(RDIR, f"{fy}.json"), encoding="utf-8"))


def split_dims(rows):
    """主表 / 维度块切分：第一处 tag 以 Axis 结尾 或 标签以 [Member] 结尾的行即分界。
    维度块行返回时附带其成员名（小写）。"""
    cut = len(rows)
    for i, r in enumerate(rows):
        if r["tag"].endswith("Axis") or r["label"].strip().endswith("[Member]"):
            cut = i
            break
    main = rows[:cut]
    dims, member = [], ""
    for r in rows[cut:]:
        if r["tag"].endswith("Axis") or r["label"].strip().endswith("[Member]"):
            member = r["label"].replace("[Member]", "").strip().lower()
            continue
        dims.append((member, r))
    return main, dims


# ── 逐份申报采集：每份 10-K 的 2-3 个期间列全收，为跨申报交叉核做准备 ──────────
# 只属于「分产品拆分」的 tag —— 它们在损益表主表里是收入/成本的**分行**，不是主表科目，
# 归 分部营收.csv；若误入利润表会与「Total revenues」重复相加（曾致 FY2018 营收翻倍）
SEG_ONLY_TAGS = {
    "us-gaap_SalesRevenueGoodsNet", "us-gaap_SalesRevenueServicesNet", "us-gaap_SalesRevenueEnergyServices",
    "us-gaap_OperatingLeasesIncomeStatementLeaseRevenue", "tsla_SalesRevenueAutomotive",
    "tsla_SalesRevenueServicesAndOtherNet", "tsla_AutomotiveSales", "tsla_AutomotiveSalesRevenue",
    "tsla_AutomotiveRegulatoryCredits", "tsla_AutomotiveLeasing", "tsla_AutomotiveRevenues",
    "us-gaap_CostOfGoodsSold", "us-gaap_CostOfServices", "us-gaap_CostOfServicesEnergyServices",
    "tsla_CostOfAutomotiveLeasing", "tsla_CostOfRevenuesAutomotive", "tsla_CostOfServicesAndOther",
    "tsla_AutomotiveCostOfRevenues", "us-gaap_CostOfGoodsAndServicesSold",
    "us-gaap_DirectCostsOfLeasedAndRentedPropertyOrEquipment",
}


def _map_is(r, member, main):
    tag = r["tag"]
    if member or tag in SEG_ONLY_TAGS:      # 分产品行归 分部营收.csv，不进利润表主表
        return None
    # RevenueFromContractWithCustomer… 在 FY2023+ 主表就是「总营收」行；
    # 在 FY2018-2022 主表另有 us-gaap_Revenues 作总额，它只是分行 → 排除
    if tag == "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax" and \
            any(x["tag"] == "us-gaap_Revenues" for x in main):
        return None
    if tag in IS_TAGS_DUAL:
        return ("__DUAL__" + tag, None, False)
    if tag == "us-gaap_NetIncomeLoss":
        # 该 tag 在损益表的含义随年变：同表若另有 ProfitLoss 行，它是「归母」，否则是「净利」
        has_pl = any(x["tag"] == "us-gaap_ProfitLoss" for x in main)
        return (("归母净利润 Net income (loss) attributable to common stockholders" if has_pl
                 else "净利润(含少数股东) Net income (loss)"), None, False)
    hit = IS_TAGS.get(tag)
    return (hit[0], None, hit[1]) if hit else None


def _map_bs(r, member, main):
    tag = r["tag"]
    if tag in BS_IGNORE:
        return None
    key = f"{tag}@{member}" if member else tag
    hit = BS_TAGS.get(key)
    if hit is None and member:
        for mk, mv in BS_TAGS.items():
            if mk.startswith(tag + "@") and mk.split("@", 1)[1] in member:
                hit = mv
                break
    if hit is None:
        hit = BS_TAGS.get(tag)
    return (hit[1], hit[0], False) if hit else None


def _map_cf(r, member, main):
    tag = r["tag"]
    if tag in CF_CASH_TAGS:                 # member 为合成的 @begin/@end
        return (("期末现金 Cash at end of period" if member == "@end"
                 else "期初现金 Cash at beginning of period"), TAIL, False)
    if member:
        return None
    hit = CF_TAGS.get(tag)
    return (hit[1], hit[0], False) if hit else None


MAPPERS = {"IS": _map_is, "BS": _map_bs, "CF": _map_cf}


def share_scale(unit_note):
    """股数印刷单位随年变：2011-2014「except Share data」=绝对股 / 2015-2018「shares in Thousands」
    / 2019+「shares in Millions」。本库股数统一 **千股**，故返回换算到千股的乘数。"""
    u = unit_note.lower()
    if "shares in millions" in u:
        return 1000.0
    if "shares in thousands" in u:
        return 1.0
    return 0.001          # 绝对股 → 千股


def collect(stmt):
    """逐份申报采集**印刷行**：raw[(tag,member)][会计年份][来源申报fy] = (印刷值, 金额单位, 股数单位)。

    交叉核放在「印刷行」这一层 —— filer 的错标（数量级、符号）就发生在具体某一行上；
    若先归并到 canonical 再比对，同一 canonical 在不同申报里由不同 tag 组合而成，比对会失真。
    """
    raw, meta = {}, {}
    for s_fy in sorted(ACCS):
        st = load(s_fy)["statements"][stmt]
        yrs = [int(p[-4:]) for p in st["periods"]]
        ss = share_scale(st.get("unit", ""))
        main, dims = split_dims(st["rows"])
        for order, (member, r) in enumerate([("", x) for x in main] + dims):
            tag = r["tag"]
            if not tag or tag.endswith(("Abstract", "Axis")):
                continue
            mem = member
            if stmt == "CF" and tag in CF_CASH_TAGS:
                # 期初现金与期末现金**共用同一 tag**，只能靠标签区分；不加后缀会互相覆盖
                mem = "@end" if re.search(r"end of (period|year)$", r["label"]) else "@begin"
            key = (tag, mem)
            # meta 按**来源申报**分别存：同一 tag 的含义可能依赖该申报自身的上下文
            meta.setdefault(key, {})[s_fy] = {"label": r["label"], "main": main, "order": order}
            for i2, y in enumerate(yrs):
                v = r["vals"][i2] if i2 < len(r["vals"]) else None
                if v is None:
                    continue
                raw.setdefault(key, {}).setdefault(y, {})[s_fy] = (v, SCALE[s_fy], ss)
    return raw, meta


EPS_TAGS = {"us-gaap_EarningsPerShareBasic", "us-gaap_EarningsPerShareDiluted",
            "us-gaap_EarningsPerShareBasicAndDiluted",
            "us-gaap_IncomeLossFromContinuingOperationsPerBasicAndDilutedShare"}
SHARECNT_TAGS = {"us-gaap_WeightedAverageNumberOfSharesOutstandingBasic",
                 "us-gaap_WeightedAverageNumberOfDilutedSharesOutstanding",
                 "us-gaap_WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
                 "tsla_WeightedAverageNumberOfSharesOutstandingBasicAndDiluted1",
                 "tsla_WeightedAverageNumberOfSharesOutstandingBasicAndDilutedOne"}

# 已查实的 filer 重复标注（同一印刷行被打了两个 tag，会在分项和里被计两次）。
# 每条都要有「后续申报独立证据 + 剔除后该段分项和恰好等于印刷净额」双重佐证才可入表。
KNOWN_FILER_DUPES = {
    # FY2021 10-K 把「Purchases of digital assets (1,500)」同时标到自定义 tag
    # tsla_PurchaseOfDigitalAssets 与 us-gaap_PaymentsToAcquireIntangibleAssets 上。
    # 证据①：FY2022 10-K 的 2021 比较列 = 数字资产 −1,500 / 无形资产 0（两者分开且无形为 0）；
    # 证据②：剔除该行后 FY2021 投资段分项和 = −7,868 = 印刷「投资活动现金流净额」，分毫不差。
    (2021, "CF", "us-gaap_PaymentsToAcquireIntangibleAssets"):
        "FY2021 申报把购买数字资产 1,500 重复标注到无形资产 tag→整行剔除(后续申报 + 分项勾稽双证)",
}


def repair(raw, stmt, disputes):
    """印刷行层交叉核：本年申报自身 vs 后续申报的比较列。三类分歧分别处置。

    比较用**印刷原值**（同一 tag 在不同申报可能印刷单位不同，先统一到千美元再比）。
    """
    fixed = {}
    for key, ys in raw.items():
        for y, srcs in ys.items():
            if (y, stmt, key[0]) in KNOWN_FILER_DUPES:
                disputes.append((stmt, key[0], y, srcs[y][0] * srcs[y][1], 0.0, 0, KNOWN_FILER_DUPES[(y, stmt, key[0])]))
                continue                    # 重复标注的印刷行 → 整行剔除，不进 canonical
            own = srcs.get(y)
            # 换算到本库单位再比：金额→千美元(×sc)、股数→千股(×ss)、每股金额→原值
            if key[0] in EPS_TAGS:
                vals = {s: v for s, (v, _sc, _ss) in srcs.items()}
            elif key[0] in SHARECNT_TAGS:
                vals = {s: v * ss for s, (v, _sc, ss) in srcs.items()}
            else:
                vals = {s: v * sc for s, (v, sc, _ss) in srcs.items()}
            val = vals.get(y, vals[min(vals)])
            others = {s: v for s, v in vals.items() if s != y}
            if y in vals and others:
                tol = 1000.0 if (SCALE.get(y) == 1000 or any(SCALE[s] == 1000 for s in others)) else 1.0
                o = vals[y]
                if not any(abs(v - o) <= tol for v in others.values()):
                    ov = list(others.values())
                    cons = ov[0]
                    label = f"{key[0]}{('@' + key[1]) if key[1] else ''}"
                    # 符号修正只要**任一**后续申报给出「等绝对值、反符号」即成立
                    # （该行同时被后续申报重述时，其余源可能既不同号也不同额，不必强求各源一致）
                    flip = next((v for v in ov if abs(abs(v) - abs(o)) <= tol and v * o < 0), None)
                    if flip is not None and abs(o) > tol:
                        disputes.append((stmt, label, y, o, flip, len(ov),
                                         "符号相反(本年申报 SEC 渲染未套用 negatedLabel)→按后续申报修正"))
                        val = flip
                    elif all(abs(v - cons) <= tol for v in ov):
                        if abs(o - 10 * cons) <= max(tol, abs(cons) * 1e-6):
                            disputes.append((stmt, label, y, o, cons, len(ov),
                                             "本年申报数量级错 10×(filer XBRL 错标)→按后续申报修正"))
                            val = cons
                        else:
                            disputes.append((stmt, label, y, o, cons, len(ov),
                                             "跨申报数值不一致(重述/追溯调整)→保留本年 as-reported"))
                    else:
                        disputes.append((stmt, label, y, o, cons, len(ov),
                                         "多份后续申报互不一致→保留本年 as-reported"))
            fixed.setdefault(key, {})[y] = (val, srcs)
    return fixed


def aggregate(stmt, fixed, meta):
    """把修正后的印刷行按 canonical 归并 → out[年份][canonical]；并回收段归属与未映射行。

    **as-reported 纪律**：某会计年份只采「该年自己那份 10-K 印刷了的行」；别的申报比较列里
    出现的同义 tag（如 NetCashProvidedByUsedInOperatingActivities vs …ContinuingOperations）
    不得再计入，否则同一科目会被重复相加。
    """
    mapper = MAPPERS[stmt]
    out, secs, unmapped = {}, {}, []
    # 按 (会计年份, 该年申报内的印刷顺序) 展开，保证「取首次」= 印刷表里的第一次出现
    items = []
    for key, ys in fixed.items():
        for y, (val, srcs) in ys.items():
            own = y if y in srcs else None
            if y in ACCS and own is None:
                continue                       # 该年自己那份申报没印这一行 → 不采
            s_fy = own if own is not None else min(srcs)
            m = meta[key].get(s_fy) or list(meta[key].values())[0]
            items.append((y, m["order"], key, val, srcs, m))
    seen_unmapped = set()
    for y, _order, key, val, srcs, m in sorted(items, key=lambda x: (x[0], x[1])):
        tag, member = key
        fake = {"tag": tag, "label": m["label"], "vals": []}
        hit = mapper(fake, member, m["main"])
        if hit is None:
            if tag == "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax":
                continue                      # FY2018-2022 主表内的分产品拆分行，归 分部营收.csv
            if not member and tag not in SEG_ONLY_TAGS and tag not in seen_unmapped:
                seen_unmapped.add(tag)
                unmapped.append((stmt, tag, m["label"][:48]))
            continue
        canon, sec, neg = hit
        if sec:
            secs.setdefault(canon, sec)
        d = out.setdefault(y, {})
        if canon.startswith("__DUAL__"):
            a, b = IS_TAGS_DUAL[canon[8:]]
            _v, _sc, ss = srcs[min(srcs, key=lambda k: abs(k - y))]
            for k in (a, b):
                d.setdefault(k, _v * (ss if k in IS_SHARE_CNT else 1))
            continue
        if canon in IS_SHARES:                       # 每股金额：不做单位换算
            _v, _sc, _ss = srcs[min(srcs, key=lambda k: abs(k - y))]
            d.setdefault(canon, _v)
            continue
        if canon in IS_SHARE_CNT:                    # 股数：按该申报的股数印刷单位换算到千股
            _v, _sc, ss = srcs[min(srcs, key=lambda k: abs(k - y))]
            d.setdefault(canon, _v * ss)
            continue
        v = -val if neg else val
        if stmt == "CF":                             # 同段多印刷行归同 canonical → 相加
            d[canon] = d.get(canon, 0.0) + v
        else:                                        # 利润表/资产负债表：一行一科目，取印刷首次
            d.setdefault(canon, v)
    return out, secs, unmapped


def build_stmt(stmt, disputes):
    raw, meta = collect(stmt)
    fixed = repair(raw, stmt, disputes)
    return aggregate(stmt, fixed, meta)


# ── 分部/分产品 ────────────────────────────────────────────────────
SEG_REV_TAGS = {
    "us-gaap_SalesRevenueGoodsNet": "汽车销售 Automotive sales",
    "tsla_AutomotiveSales": "汽车销售 Automotive sales",
    "tsla_AutomotiveSalesRevenue": "汽车销售 Automotive sales",
    "tsla_AutomotiveRegulatoryCredits": "汽车监管积分 Automotive regulatory credits",
    "us-gaap_OperatingLeasesIncomeStatementLeaseRevenue": "汽车租赁 Automotive leasing",
    "tsla_AutomotiveLeasing": "汽车租赁 Automotive leasing",
    "tsla_SalesRevenueAutomotive": "汽车板块合计 Total automotive revenues",
    "tsla_AutomotiveRevenues": "汽车板块合计 Total automotive revenues",
    "us-gaap_SalesRevenueEnergyServices": "能源发电与储存 Energy generation and storage",
    "tsla_SalesRevenueServicesAndOtherNet": "服务及其他 Services and other",
    "us-gaap_SalesRevenueServicesNet": "开发服务 Development services",
}
SEG_COST_TAGS = {
    "us-gaap_CostOfGoodsSold": "【成本】汽车销售 Automotive sales",
    "tsla_CostOfAutomotiveLeasing": "【成本】汽车租赁 Automotive leasing",
    "us-gaap_DirectCostsOfLeasedAndRentedPropertyOrEquipment": "【成本】汽车租赁 Automotive leasing",
    "tsla_CostOfRevenuesAutomotive": "【成本】汽车板块合计 Total automotive",
    "tsla_AutomotiveCostOfRevenues": "【成本】汽车板块合计 Total automotive",
    "us-gaap_CostOfServicesEnergyServices": "【成本】能源发电与储存 Energy generation and storage",
    "tsla_CostOfServicesAndOther": "【成本】服务及其他 Services and other",
    "us-gaap_CostOfServices": "【成本】开发服务 Development services",
}
# 2018+ 分产品走 srt_ProductOrServiceAxis：靠「成员名 + tag 属收入还是成本」定位
MEMBER2REV = {
    "automotive sales": "汽车销售 Automotive sales",
    "automotive regulatory credits": "汽车监管积分 Automotive regulatory credits",
    "automotive leasing": "汽车租赁 Automotive leasing",
    "automotive revenues": "汽车板块合计 Total automotive revenues",
    "energy generation and storage": "能源发电与储存 Energy generation and storage",
    "services and other": "服务及其他 Services and other",
}
DIM_REV_TAGS = {"us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap_Revenues",
                "us-gaap_OperatingLeasesIncomeStatementLeaseRevenue", "us-gaap_SalesTypeLeaseRevenue",
                "tsla_SalesRevenueAutomotive", "tsla_AutomotiveRevenues", "tsla_AutomotiveSales",
                "tsla_AutomotiveSalesRevenue", "tsla_AutomotiveRegulatoryCredits", "tsla_AutomotiveLeasing",
                "tsla_SalesRevenueServicesAndOtherNet", "us-gaap_SalesRevenueEnergyServices"}
DIM_COST_TAGS = {"us-gaap_CostOfGoodsAndServicesSold", "us-gaap_CostOfRevenue", "us-gaap_CostOfGoodsSold",
                 "us-gaap_DirectCostsOfLeasedAndRentedPropertyOrEquipment", "tsla_CostOfRevenuesAutomotive",
                 "tsla_AutomotiveCostOfRevenues", "tsla_CostOfAutomotiveLeasing", "tsla_CostOfServicesAndOther",
                 "us-gaap_CostOfServicesEnergyServices", "us-gaap_CostOfGoodsSoldSalesTypeLease"}
# tag 本身已指明科目的维度行（与所在成员无关）
DIM_TAG_SPECIFIC = {
    "tsla_AutomotiveSalesRevenue": "汽车销售 Automotive sales",
    "tsla_AutomotiveRegulatoryCredits": "汽车监管积分 Automotive regulatory credits",
    "tsla_AutomotiveLeasing": "汽车租赁 Automotive leasing",
    "us-gaap_OperatingLeasesIncomeStatementLeaseRevenue": "汽车租赁 Automotive leasing",
    "tsla_AutomotiveRevenues": "汽车板块合计 Total automotive revenues",
    "tsla_SalesRevenueAutomotive": "汽车板块合计 Total automotive revenues",
    "tsla_AutomotiveSales": "【成本】汽车销售 Automotive sales",          # FY2022 汽车销售**成本**
    "us-gaap_DirectCostsOfLeasedAndRentedPropertyOrEquipment": "【成本】汽车租赁 Automotive leasing",
    "tsla_CostOfAutomotiveLeasing": "【成本】汽车租赁 Automotive leasing",
    "tsla_AutomotiveCostOfRevenues": "【成本】汽车板块合计 Total automotive",
    "tsla_CostOfRevenuesAutomotive": "【成本】汽车板块合计 Total automotive",
}
REV2COST = {"汽车销售 Automotive sales": "【成本】汽车销售 Automotive sales",
            "汽车租赁 Automotive leasing": "【成本】汽车租赁 Automotive leasing",
            "汽车板块合计 Total automotive revenues": "【成本】汽车板块合计 Total automotive",
            "能源发电与储存 Energy generation and storage": "【成本】能源发电与储存 Energy generation and storage",
            "服务及其他 Services and other": "【成本】服务及其他 Services and other"}
SEG_ROWS = ["汽车销售 Automotive sales", "汽车监管积分 Automotive regulatory credits", "汽车租赁 Automotive leasing",
            "汽车板块合计 Total automotive revenues", "能源发电与储存 Energy generation and storage",
            "服务及其他 Services and other", "开发服务 Development services", "总营收 Total revenues",
            "【成本】汽车销售 Automotive sales", "【成本】汽车租赁 Automotive leasing",
            "【成本】汽车板块合计 Total automotive", "【成本】能源发电与储存 Energy generation and storage",
            "【成本】服务及其他 Services and other", "【成本】开发服务 Development services",
            "【成本】总成本 Total cost of revenues"]


def build_seg(fy):
    st = load(fy)["statements"]["IS"]
    main, dims = split_dims(st["rows"])
    sc, out = SCALE[fy], {}
    for r in main:                                  # 2011-2017：分产品在主表
        v = r["vals"][0] if r["vals"] else None
        if v is None:
            continue
        if r["tag"] in SEG_REV_TAGS:
            out.setdefault(SEG_REV_TAGS[r["tag"]], v * sc)
        if r["tag"] in SEG_COST_TAGS:
            out.setdefault(SEG_COST_TAGS[r["tag"]], v * sc)
        if r["tag"] in ("us-gaap_Revenues", "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax"):
            out.setdefault("总营收 Total revenues", v * sc)
        if r["tag"] == "us-gaap_CostOfRevenue":
            out.setdefault("【成本】总成本 Total cost of revenues", v * sc)
    for member, r in dims:                          # 2018+：srt_ProductOrServiceAxis 维度块
        v = r["vals"][0] if r["vals"] else None
        tag = r["tag"]
        if v is None:
            continue
        # ① tag 本身已指明科目的（tsla_ 自定义 tag / 租赁成本 tag）→ 与成员无关，直接落位
        if tag in DIM_TAG_SPECIFIC:
            out.setdefault(DIM_TAG_SPECIFIC[tag], v * sc)
            continue
        canon = MEMBER2REV.get(member)
        if not canon:
            continue
        # ② 通用 tag → 靠成员定位。注意「Automotive Revenues」成员下有 3 行成本：
        #    CostOfRevenue=汽车板块**合计**成本，CostOfGoodsAndServicesSold=汽车**销售**成本，
        #    DirectCostsOfLeased…=汽车**租赁**成本（已在 ① 处理）。不分辨会把销售成本当成合计。
        if tag in DIM_COST_TAGS:
            if canon == "汽车板块合计 Total automotive revenues":
                k = ("【成本】汽车板块合计 Total automotive" if tag == "us-gaap_CostOfRevenue"
                     else "【成本】汽车销售 Automotive sales")
            else:
                k = REV2COST.get(canon)
            if k:
                out.setdefault(k, v * sc)
        elif tag in DIM_REV_TAGS:
            out.setdefault(canon, v * sc)
    return out


# ══════════════════════════════════════════════════════════════════
# 6. 汇总 + 勾稽
# ══════════════════════════════════════════════════════════════════
def merge_all():
    disputes, UNMAP = [], []
    IS, _, u1 = build_stmt("IS", disputes)
    BS, SEC_BS, u2 = build_stmt("BS", disputes)
    CF, SEC_CF, u3 = build_stmt("CF", disputes)
    UNMAP += u1 + u2 + u3
    SEG = {fy: build_seg(fy) for fy in sorted(ACCS)}

    # 手工转录年份(FY2005-2010)与「后续申报比较列」交叉核：只核两者都有的格
    xcheck = []
    for early, tbl, name in ((EARLY_IS, IS, "利润表"), (EARLY_BS, BS, "资产负债表"), (EARLY_CF, CF, "现金流量表")):
        for y, d in early.items():
            got = tbl.get(y, {})
            for k, v in d.items():
                if v is None or k not in got or got[k] is None:
                    continue
                if abs(got[k] - v) > 1.0:
                    xcheck.append(f"[{y}] {name} {k}: 手工转录 {v:,.0f} vs 后续申报比较列 {got[k]:,.0f}")
    # 手工转录年份为 canonical（招股书/FY2010 10-K 是这些年的 as-reported 源）
    for y, d in EARLY_IS.items():
        IS[y] = dict(d)
    for y, d in EARLY_BS.items():
        BS[y] = dict(d)
    for y, d in EARLY_CF.items():
        CF[y] = dict(d)
    # 只在比较列里出现、且不在手工转录范围的年份 → 丢弃（非 as-reported）
    for tbl in (IS, BS, CF):
        for y in [k for k in tbl if k not in ACCS and k not in EARLY_IS]:
            del tbl[y]

    # 无少数股东的年份（2011-2015）损益表不单列「归母」行 → 归母 = 净利
    for y, d in IS.items():
        if d.get("归母净利润 Net income (loss) attributable to common stockholders") is None:
            ni = d.get("净利润(含少数股东) Net income (loss)")
            nci = d.get("少数股东损益 Net income (loss) attributable to NCI")
            if ni is not None:
                d["归母净利润 Net income (loss) attributable to common stockholders"] = ni - (nci or 0)
    for y, d in BS.items():
        if d.get("权益合计 Total equity") is None and d.get("归母股东权益 Total stockholders' equity") is not None:
            d["权益合计 Total equity"] = (d["归母股东权益 Total stockholders' equity"]
                                     + (d.get("非控股权益 Noncontrolling interests") or 0))
    for y in IS:
        for src, dst in (("股份支付 Stock-based compensation", "备忘-股份支付 SBC(取自现金流量表)"),
                         ("折旧摊销(及减值) Depreciation, amortization (and impairment)", "备忘-折旧摊销及减值 D&A(取自现金流量表)")):
            v = CF.get(y, {}).get(src)
            if v is not None:
                IS[y][dst] = v
    return IS, BS, CF, SEG, SEC_BS, SEC_CF, UNMAP, disputes, xcheck



def check(IS, BS, CF, SEC_BS, SEC_CF):
    errs, n = [], 0

    def eq(y, name, lhs, rhs, base=1.0):
        nonlocal n
        if lhs is None or rhs is None:
            return
        n += 1
        tol = base if y <= 2018 else 1000.0          # FY2019+ 印刷到百万 → 允许 ±1 百万舍入
        if abs(lhs - rhs) > tol:
            errs.append(f"[{y}] {name}: {lhs:,.0f} vs {rhs:,.0f} (差 {lhs - rhs:,.0f})")

    g = dict.get
    for y in sorted(IS):
        i = IS[y]
        eq(y, "营收+成本=毛利", (g(i, "营业收入 Total revenues") or 0) + (g(i, "营业成本 Total cost of revenues") or 0), g(i, "毛利 Gross profit"))
        parts = [g(i, k) for k in ("研发费用 Research and development", "销售及行政费用 Selling, general and administrative",
                                   "重组及其他 Restructuring and other") if g(i, k) is not None]
        eq(y, "经营费用分项和=合计", sum(parts), g(i, "经营费用合计 Total operating expenses"))
        eq(y, "毛利+经营费用=经营利润", (g(i, "毛利 Gross profit") or 0) + (g(i, "经营费用合计 Total operating expenses") or 0),
           g(i, "经营利润 Income (loss) from operations"))
        eq(y, "经营利润+线下=税前", (g(i, "经营利润 Income (loss) from operations") or 0)
           + sum(g(i, k) or 0 for k in ("利息收入 Interest income", "利息费用 Interest expense",
                                        "其他收入(费用)净额 Other income (expense), net")),
           g(i, "税前利润 Income (loss) before income taxes"))
        eq(y, "税前+所得税=净利", (g(i, "税前利润 Income (loss) before income taxes") or 0)
           + (g(i, "所得税 Provision for (benefit from) income taxes") or 0), g(i, "净利润(含少数股东) Net income (loss)"))
        if g(i, "少数股东损益 Net income (loss) attributable to NCI") is not None:
            eq(y, "净利−少数股东=归母", (g(i, "净利润(含少数股东) Net income (loss)") or 0)
               - g(i, "少数股东损益 Net income (loss) attributable to NCI"),
               g(i, "归母净利润 Net income (loss) attributable to common stockholders"))

    EARLY_SEC = {  # 手工转录年份的段归属
        **{k: A_CUR for k in ("现金及现金等价物 Cash and cash equivalents", "受限现金-流动 Restricted cash, current",
                              "应收账款净额 Accounts receivable, net", "存货 Inventory",
                              "预付及其他流动资产 Prepaid expenses and other current assets")},
        **{k: A_NON for k in ("经营租赁车辆净额 Operating lease vehicles, net", "固定资产净额 Property, plant and equipment, net",
                              "受限现金-非流动 Restricted cash, non-current", "其他非流动资产 Other non-current assets")},
        **{k: L_CUR for k in ("应付账款 Accounts payable", "应计负债及其他 Accrued liabilities and other",
                              "递延开发补偿 Deferred development compensation", "递延收入-流动 Deferred revenue, current",
                              "融资租赁负债-流动 Capital lease obligations, current", "可退还预订金 Refundable reservation payments")},
        **{k: L_NON for k in ("可转换优先股认股权证负债 Convertible preferred stock warrant liability",
                              "普通股认股权证负债 Common stock warrant liability",
                              "融资租赁负债-非流动 Capital lease obligations, non-current",
                              "债务-非流动 Debt, non-current", "递延收入-非流动 Deferred revenue, non-current",
                              "其他长期负债 Other long-term liabilities")},
        "夹层-可转换优先股 Convertible preferred stock (mezzanine)": MEZ,
        **{k: EQ for k in ("普通股 Common stock", "资本公积 Additional paid-in capital",
                           "累计亏损/留存收益 Accumulated deficit / Retained earnings")},
    }
    for y in sorted(BS):
        b, sec = BS[y], {**EARLY_SEC, **SEC_BS}     # SEC_BS: canonical → 段（跨年通用）
        s = lambda tgt: sum(v for k, v in b.items() if sec.get(k) == tgt)
        eq(y, "流动资产分项和=合计", s(A_CUR), g(b, "流动资产合计 Total current assets"))
        eq(y, "流动+非流动=总资产", (g(b, "流动资产合计 Total current assets") or 0) + s(A_NON), g(b, "资产总计 Total assets"))
        eq(y, "流动负债分项和=合计", s(L_CUR), g(b, "流动负债合计 Total current liabilities"))
        eq(y, "流动+非流动负债=负债合计", (g(b, "流动负债合计 Total current liabilities") or 0) + s(L_NON), g(b, "负债合计 Total liabilities"))
        eq(y, "负债+夹层+权益=总资产", (g(b, "负债合计 Total liabilities") or 0) + s(MEZ) + (g(b, "权益合计 Total equity") or 0),
           g(b, "资产总计 Total assets"))
        eq(y, "权益分项和=归母权益", s(EQ), g(b, "归母股东权益 Total stockholders' equity"))
        eq(y, "归母权益+非控股=权益合计", (g(b, "归母股东权益 Total stockholders' equity") or 0)
           + (g(b, "非控股权益 Noncontrolling interests") or 0), g(b, "权益合计 Total equity"))
        eq(y, "印刷负债和权益合计=总资产", g(b, "负债和权益合计 Total liabilities and equity"), g(b, "资产总计 Total assets"))

    for y in sorted(CF):
        c, sec = CF[y], SEC_CF                      # SEC_CF: canonical → 段（跨年通用）
        if y in ACCS:                               # 手工转录年份只录了骨架行，不做分项和校验
            for tgt, tot in ((OP, "经营活动现金流净额 Net cash from operating activities"),
                             (INV, "投资活动现金流净额 Net cash from investing activities"),
                             (FIN, "融资活动现金流净额 Net cash from financing activities")):
                eq(y, f"{tgt}段分项和=该段净额", sum(v for k, v in c.items() if sec.get(k) == tgt), g(c, tot))
        eq(y, "三段+汇率=现金净变动",
           sum(g(c, k) or 0 for k in ("经营活动现金流净额 Net cash from operating activities",
                                      "投资活动现金流净额 Net cash from investing activities",
                                      "融资活动现金流净额 Net cash from financing activities",
                                      "汇率影响 Effect of exchange rate changes")),
           g(c, "现金净变动 Net increase (decrease) in cash"))
        eq(y, "期初+净变动=期末", (g(c, "期初现金 Cash at beginning of period") or 0)
           + (g(c, "现金净变动 Net increase (decrease) in cash") or 0), g(c, "期末现金 Cash at end of period"))
        if y in IS:
            eq(y, "现金流净利=利润表净利", g(c, "净利润 Net income (loss)"), IS[y].get("净利润(含少数股东) Net income (loss)"))
    return errs, n


def check_seg(SEG, IS):
    errs, n = [], 0
    for y in sorted(SEG):
        s, tot = SEG[y], IS[y].get("营业收入 Total revenues")
        tol = 1.0 if y <= 2018 else 1000.0
        if tot is None:
            continue
        # 顶层口径随年变：有「汽车板块合计」的年份用它，早年（无该行）用汽车分项直接相加
        auto_parts = [s.get(k) for k in ("汽车销售 Automotive sales", "汽车监管积分 Automotive regulatory credits",
                                         "汽车租赁 Automotive leasing") if s.get(k) is not None]
        ta = s.get("汽车板块合计 Total automotive revenues")
        top = [ta] if ta is not None else auto_parts
        top += [s.get(k) for k in ("能源发电与储存 Energy generation and storage", "服务及其他 Services and other",
                                   "开发服务 Development services") if s.get(k) is not None]
        if top:
            n += 1
            if abs(sum(top) - tot) > tol:
                errs.append(f"[{y}] 分部收入和 {sum(top):,.0f} vs 总营收 {tot:,.0f}")
        if len(auto_parts) >= 2 and ta is not None:
            n += 1
            if abs(sum(auto_parts) - ta) > tol:
                errs.append(f"[{y}] 汽车分项和 {sum(auto_parts):,.0f} vs 汽车板块合计 {ta:,.0f}")
        # 分产品成本合计（有分项列示的年份）
        cparts = [s.get(k) for k in ("【成本】汽车板块合计 Total automotive", "【成本】能源发电与储存 Energy generation and storage",
                                     "【成本】服务及其他 Services and other", "【成本】开发服务 Development services")
                  if s.get(k) is not None]
        ctot = s.get("【成本】总成本 Total cost of revenues")
        if len(cparts) >= 2 and ctot is not None:
            n += 1
            if abs(sum(cparts) - ctot) > tol:
                errs.append(f"[{y}] 分部成本和 {sum(cparts):,.0f} vs 总成本 {ctot:,.0f}")
    return errs, n


# ══════════════════════════════════════════════════════════════════
# 7. XBRL 独立核对轨
# ══════════════════════════════════════════════════════════════════
PAIRS_D = [
    ("IS", "营业收入 Total revenues", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"], 1),
    ("IS", "营业成本 Total cost of revenues", ["CostOfRevenue"], -1),
    ("IS", "毛利 Gross profit", ["GrossProfit"], 1),
    ("IS", "研发费用 Research and development", ["ResearchAndDevelopmentExpense"], -1),
    ("IS", "销售及行政费用 Selling, general and administrative", ["SellingGeneralAndAdministrativeExpense"], -1),
    ("IS", "经营费用合计 Total operating expenses", ["OperatingExpenses"], -1),
    ("IS", "经营利润 Income (loss) from operations", ["OperatingIncomeLoss"], 1),
    ("IS", "利息收入 Interest income", ["InvestmentIncomeInterest"], 1),
    ("IS", "其他收入(费用)净额 Other income (expense), net", ["OtherNonoperatingIncomeExpense"], 1),
    ("IS", "税前利润 Income (loss) before income taxes",
     ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"], 1),
    ("IS", "所得税 Provision for (benefit from) income taxes", ["IncomeTaxExpenseBenefit"], -1),
    ("IS", "归母净利润 Net income (loss) attributable to common stockholders", ["NetIncomeLoss"], 1),
    ("IS", "净利润(含少数股东) Net income (loss)", ["ProfitLoss"], 1),
    ("IS", "少数股东损益 Net income (loss) attributable to NCI", ["NetIncomeLossAttributableToNoncontrollingInterest"], 1),
    ("CF", "经营活动现金流净额 Net cash from operating activities", ["NetCashProvidedByUsedInOperatingActivities"], 1),
    ("CF", "投资活动现金流净额 Net cash from investing activities", ["NetCashProvidedByUsedInInvestingActivities"], 1),
    ("CF", "融资活动现金流净额 Net cash from financing activities", ["NetCashProvidedByUsedInFinancingActivities"], 1),
    ("CF", "购建固定资产(capex) Purchases of property and equipment", ["PaymentsToAcquirePropertyPlantAndEquipment"], -1),
    ("CF", "股份支付 Stock-based compensation", ["ShareBasedCompensation"], 1),
    ("CF", "存货(及采购承诺)减值 Inventory write-downs", ["InventoryWriteDown"], 1),
]
PAIRS_I = [
    ("现金及现金等价物 Cash and cash equivalents", ["CashAndCashEquivalentsAtCarryingValue"], 1),
    ("应收账款净额 Accounts receivable, net", ["AccountsReceivableNetCurrent"], 1),
    ("存货 Inventory", ["InventoryNet"], 1),
    ("预付及其他流动资产 Prepaid expenses and other current assets", ["PrepaidExpenseAndOtherAssetsCurrent"], 1),
    ("流动资产合计 Total current assets", ["AssetsCurrent"], 1),
    ("资产总计 Total assets", ["Assets"], 1),
    ("应付账款 Accounts payable", ["AccountsPayableCurrent"], 1),
    ("流动负债合计 Total current liabilities", ["LiabilitiesCurrent"], 1),
    ("负债合计 Total liabilities", ["Liabilities"], 1),
    ("资本公积 Additional paid-in capital", ["AdditionalPaidInCapital", "AdditionalPaidInCapitalCommonStock"], 1),
    ("累计亏损/留存收益 Accumulated deficit / Retained earnings", ["RetainedEarningsAccumulatedDeficit"], 1),
    ("归母股东权益 Total stockholders' equity", ["StockholdersEquity"], 1),
    # ⚠️ 不核「权益合计」：FY2016 申报把**夹层的可赎回非控股权益(367,039)也算进了**
    #   StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest，与印刷资产负债表口径不符
    #   （印刷表里可赎回非控股权益在「负债与权益」之间的夹层，不进权益合计）。本库该行按印刷口径派生
    #   （归母 + 非控股），已由「负债+夹层+权益=总资产」勾稽证真，故不纳入 XBRL 逐格核对。
    ("非控股权益 Noncontrolling interests", ["MinorityInterest"], 1),
    ("负债和权益合计 Total liabilities and equity", ["LiabilitiesAndStockholdersEquity"], 1),
    ("商誉 Goodwill", ["Goodwill"], 1),
    ("无形资产净额 Intangible assets, net", ["IntangibleAssetsNetExcludingGoodwill"], 1),
    ("经营租赁使用权资产 Operating lease ROU assets", ["OperatingLeaseRightOfUseAsset"], 1),
    ("夹层-可赎回非控股权益 Redeemable NCI", ["RedeemableNoncontrollingInterestEquityCarryingAmount"], 1),
    ("固定资产净额 Property, plant and equipment, net",
     ["PropertyPlantAndEquipmentNet",
      "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization"], 1),
]


def xbrl_track(IS, BS, CF):
    gaap = json.loads(open(XBRL, encoding="utf-8").read())["facts"]["us-gaap"]

    def fact(accn, year, tags, instant):
        for t in tags:
            node = gaap.get(t)
            if not node:
                continue
            for unit, pts in node["units"].items():
                if unit != "USD":
                    continue
                for p in pts:
                    if p.get("accn") != accn:
                        continue
                    end, st0 = p["end"], p.get("start")
                    if instant and not st0 and end == f"{year}-12-31":
                        return p["val"] / 1000.0
                    if not instant and st0 and st0[:4] == year and st0[5:7] == "01" and end[:4] == year and end[5:7] == "12":
                        return p["val"] / 1000.0
        return None

    mism, n = [], 0
    for fy, accn in sorted(ACCS.items()):
        for src, canon, tags, sgn in PAIRS_D:
            x = fact(accn, str(fy), tags, False)
            ours = (IS if src == "IS" else CF)[fy].get(canon)
            if x is None or ours is None:
                continue
            n += 1
            if abs(ours - sgn * x) > 0.5:
                mism.append(f"[{fy}] {canon}: 转录 {ours:,.0f} vs XBRL {sgn * x:,.0f}")
        for canon, tags, sgn in PAIRS_I:
            x = fact(accn, str(fy), tags, True)
            ours = BS[fy].get(canon)
            if x is None or ours is None:
                continue
            n += 1
            if abs(ours - sgn * x) > 0.5:
                mism.append(f"[{fy}] {canon}: 转录 {ours:,.0f} vs XBRL {sgn * x:,.0f}")
    return mism, n


# ══════════════════════════════════════════════════════════════════
# 8. 输出
# ══════════════════════════════════════════════════════════════════
def fmt(v):
    if v is None:
        return ""
    if abs(v) < 1e-9:
        return "0"
    if abs(v - round(v)) < 1e-6:
        return f"{v:.0f}"
    return (f"{v:.4f}" if abs(v) < 1000 else f"{v:.1f}").rstrip("0").rstrip(".")


def write_csv(path, headers, rows, years, data):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for h in headers:
            w.writerow([h])
        w.writerow(["科目"] + [str(y) for y in years])
        for r in rows:
            vals = [data.get(y, {}).get(r) for y in years]
            if any(v is not None for v in vals):
                w.writerow([r] + [fmt(v) for v in vals])


# 拆股：2020-08-31 五股拆一(5:1)、2022-08-25 三股拆一(3:1)。
# 各年 as-reported 的每股数据只反映**该年申报时点**已发生的拆股 → 折算到 2025 股本口径的因子：
SPLIT_FACTOR = {y: (15 if y <= 2019 else 3 if y <= 2021 else 1) for y in YEARS}


def build_ratios(IS, BS, CF):
    """从三表派生比率（年报不直接给）。分母为 0 / 分项缺失时留空，不外推。"""
    R = {}

    def g(t, y, k):
        return t.get(y, {}).get(k)

    def put(y, k, v):
        if v is not None:
            R.setdefault(y, {})[k] = v

    def div(a, b):
        return None if (a is None or b in (None, 0)) else a / b

    for y in sorted(set(IS) | set(BS) | set(CF)):
        rev = g(IS, y, "营业收入 Total revenues")
        gp = g(IS, y, "毛利 Gross profit")
        op = g(IS, y, "经营利润 Income (loss) from operations")
        ni = g(IS, y, "归母净利润 Net income (loss) attributable to common stockholders")
        pbt = g(IS, y, "税前利润 Income (loss) before income taxes")
        tax = g(IS, y, "所得税 Provision for (benefit from) income taxes")
        cost = g(IS, y, "营业成本 Total cost of revenues")
        rd = g(IS, y, "研发费用 Research and development")
        sga = g(IS, y, "销售及行政费用 Selling, general and administrative")
        ocf = g(CF, y, "经营活动现金流净额 Net cash from operating activities")
        capex = g(CF, y, "购建固定资产(capex) Purchases of property and equipment")
        solar = g(CF, y, "购建太阳能系统 Purchases of solar energy systems") or 0
        sbc = g(CF, y, "股份支付 Stock-based compensation")
        ta = g(BS, y, "资产总计 Total assets")
        eq = g(BS, y, "归母股东权益 Total stockholders' equity")
        eq0 = g(BS, y - 1, "归母股东权益 Total stockholders' equity")
        tl = g(BS, y, "负债合计 Total liabilities")
        ar = g(BS, y, "应收账款净额 Accounts receivable, net")
        ar0 = g(BS, y - 1, "应收账款净额 Accounts receivable, net")
        inv = g(BS, y, "存货 Inventory")
        inv0 = g(BS, y - 1, "存货 Inventory")
        ap = g(BS, y, "应付账款 Accounts payable")
        ap0 = g(BS, y - 1, "应付账款 Accounts payable")
        cash = g(BS, y, "现金及现金等价物 Cash and cash equivalents")
        sti = g(BS, y, "短期投资 Short-term investments") or 0
        ppe = g(BS, y, "固定资产净额 Property, plant and equipment, net")
        gw = g(BS, y, "商誉 Goodwill")
        ppd = g(BS, y, "预付及其他流动资产 Prepaid expenses and other current assets")
        dr_c = g(BS, y, "递延收入-流动 Deferred revenue, current")
        dr_n = g(BS, y, "递延收入-非流动 Deferred revenue, non-current")
        dep_c = g(BS, y, "客户存款 Customer deposits")
        dep_r = g(BS, y, "可退还预订金 Refundable reservation payments")
        d_cur = g(BS, y, "债务及租赁负债-流动 Debt and capital/finance leases, current")
        d_non = g(BS, y, "债务及租赁负债-非流动 Debt and capital/finance leases, non-current")
        d_cur2 = g(BS, y, "债务-流动 Debt, current portion")
        d_non2 = g(BS, y, "债务-非流动 Debt, non-current")
        cl_c = g(BS, y, "融资租赁负债-流动 Capital lease obligations, current")
        cl_n = g(BS, y, "融资租赁负债-非流动 Capital lease obligations, non-current")

        put(y, "毛利率 Gross margin", div(gp, rev))
        put(y, "经营利润率 Operating margin", div(op, rev))
        put(y, "净利率(归母) Net margin", div(ni, rev))
        put(y, "研发费用率 R&D / revenue", None if rd is None else div(-rd, rev))
        put(y, "销售及行政费用率 SG&A / revenue", None if sga is None else div(-sga, rev))
        put(y, "实际所得税率 Effective tax rate", None if (tax is None or pbt in (None, 0)) else -tax / pbt)
        if eq is not None and eq0 is not None and ni is not None and (eq + eq0) > 0:
            put(y, "ROE(归母·平均净资产) Return on equity", ni / ((eq + eq0) / 2))
        put(y, "ROA(归母/期末总资产) Return on assets", div(ni, ta))
        put(y, "资产负债率 Liabilities / assets", div(tl, ta))
        put(y, "现金含量 经营现金流/归母净利", div(ocf, ni) if (ni or 0) > 0 else None)
        put(y, "capex/经营现金流 Capex / OCF", None if (capex is None or not ocf or ocf <= 0) else -(capex + solar) / ocf)
        put(y, "capex/营收 Capex / revenue", None if capex is None else div(-(capex + solar), rev))
        put(y, "capex/归母净利 Capex / net income", None if (capex is None or (ni or 0) <= 0) else -(capex + solar) / ni)
        put(y, "自由现金流 FCF = OCF + capex(千美元)", None if (ocf is None or capex is None) else ocf + capex + solar)
        put(y, "股份支付/营收 SBC / revenue", div(sbc, rev))
        put(y, "股份支付/归母净利 SBC / net income", None if (sbc is None or (ni or 0) <= 0) else sbc / ni)
        if ar is not None and ar0 is not None and rev:
            put(y, "应收账款周转天数 DSO", (ar + ar0) / 2 / rev * 365)
        if inv is not None and inv0 is not None and cost:
            put(y, "存货周转天数 DIO", (inv + inv0) / 2 / abs(cost) * 365)
        if ap is not None and ap0 is not None and cost:
            put(y, "应付账款周转天数 DPO", (ap + ap0) / 2 / abs(cost) * 365)
        put(y, "应收账款/营收 AR / revenue", div(ar, rev))
        put(y, "存货/营收 Inventory / revenue", div(inv, rev))
        # 「垃圾筐」科目监控：预付及其他流动资产是假利润常见藏身处（财报阅读规则 Step 3.0 第 6 条）。
        # 该科目 10-K 未单独拆分明细，故只能靠占营收比做鼓包探针。
        put(y, "预付及其他流动资产/营收 Prepaid & other current assets / revenue", div(ppd, rev))
        put(y, "现金及短投/总资产 Cash & ST investments / assets", None if cash is None else div(cash + sti, ta))
        put(y, "固定资产/总资产 PP&E / assets", div(ppe, ta))
        put(y, "商誉/归母净资产 Goodwill / equity", div(gw, eq))
        pre = sum(x for x in (dr_c, dr_n, dep_c, dep_r) if x is not None) or None
        put(y, "预收类负债(递延收入+客户存款)/营收 Deferred revenue & deposits / revenue", div(pre, rev))
        debt = sum(x for x in (d_cur, d_non, d_cur2, d_non2, cl_c, cl_n) if x is not None) or None
        put(y, "有息负债(债务及租赁)合计(千美元) Interest-bearing debt", debt)
        put(y, "有息负债/归母净资产 Debt / equity", div(debt, eq))
        put(y, "净现金(现金+短投−有息负债·千美元) Net cash", None if (cash is None or debt is None) else cash + sti - debt)
        f = SPLIT_FACTOR.get(y)
        for src, dst in (("每股收益-基本(美元)", "【复权】每股收益-基本(美元·2025股本口径)"),
                         ("每股收益-稀释(美元)", "【复权】每股收益-稀释(美元·2025股本口径)")):
            v = g(IS, y, src)
            put(y, dst, None if v is None else v / f)
        for src, dst in (("加权平均股数-基本(千股)", "【复权】加权平均股数-基本(千股·2025股本口径)"),
                         ("加权平均股数-稀释(千股)", "【复权】加权平均股数-稀释(千股·2025股本口径)")):
            v = g(IS, y, src)
            put(y, dst, None if v is None else v * f)
        put(y, "拆股复权因子(相对2025) Split factor", float(f))
    order = ["毛利率 Gross margin", "经营利润率 Operating margin", "净利率(归母) Net margin",
             "研发费用率 R&D / revenue", "销售及行政费用率 SG&A / revenue", "实际所得税率 Effective tax rate",
             "ROE(归母·平均净资产) Return on equity", "ROA(归母/期末总资产) Return on assets",
             "资产负债率 Liabilities / assets", "现金含量 经营现金流/归母净利",
             "capex/经营现金流 Capex / OCF", "capex/营收 Capex / revenue", "capex/归母净利 Capex / net income",
             "自由现金流 FCF = OCF + capex(千美元)", "股份支付/营收 SBC / revenue", "股份支付/归母净利 SBC / net income",
             "应收账款周转天数 DSO", "存货周转天数 DIO", "应付账款周转天数 DPO",
             "应收账款/营收 AR / revenue", "存货/营收 Inventory / revenue",
             "预付及其他流动资产/营收 Prepaid & other current assets / revenue",
             "现金及短投/总资产 Cash & ST investments / assets", "固定资产/总资产 PP&E / assets",
             "商誉/归母净资产 Goodwill / equity",
             "预收类负债(递延收入+客户存款)/营收 Deferred revenue & deposits / revenue",
             "有息负债(债务及租赁)合计(千美元) Interest-bearing debt", "有息负债/归母净资产 Debt / equity",
             "净现金(现金+短投−有息负债·千美元) Net cash",
             "【复权】每股收益-基本(美元·2025股本口径)", "【复权】每股收益-稀释(美元·2025股本口径)",
             "【复权】加权平均股数-基本(千股·2025股本口径)", "【复权】加权平均股数-稀释(千股·2025股本口径)",
             "拆股复权因子(相对2025) Split factor"]
    return R, order


UNIT = ("单位:千美元(USD thousands);空=该年申报 presentation 无此科目(不补0)。"
        "⚠️印刷口径 FY2019 起由千美元改为百万美元,故 FY2019+ 精度只到百万(末三位恒为0)")
LINEAGE = ("各年 as-reported 来源:FY2005/2006=424B4(2010-06-29)五年 Selected Financial Data | "
           "FY2007-2009=424B4 经审计三表 | FY2010=10-K FY2010 | FY2011-2025=各年自身 10-K 的 SEC 渲染报表 R*.htm(按 XBRL tag 归一)")


def main():
    IS, BS, CF, SEG, SEC_BS, SEC_CF, UNMAP, disputes, xcheck = merge_all()
    errs, nchk = check(IS, BS, CF, SEC_BS, SEC_CF)
    serrs, nseg = check_seg(SEG, IS)
    mism, nx = xbrl_track(IS, BS, CF)

    print(f"── 三表勾稽：{nchk} 条，不通过 {len(errs)}")
    for e in errs:
        print("   ✗", e)
    print(f"── 分部勾稽：{nseg} 条，不通过 {len(serrs)}")
    for e in serrs:
        print("   ✗", e)
    print(f"── XBRL 独立核对：{nx} 格，不一致 {len(mism)}")
    for m in mism:
        print("   ✗", m)
    print(f"── 手工转录年份 vs 后续申报比较列：不一致 {len(xcheck)}")
    for x in xcheck:
        print("   ✗", x)
    print(f"── 跨申报交叉核分歧：{len(disputes)} 处（明细见 重述与口径变更.csv）")
    for d in disputes:
        print(f"   • [{d[2]}] {d[0]}·{d[1]}: 本年 {d[3]:,.0f} / 后续 {d[4]:,.0f}（{d[5]} 份后续申报）→ {d[6]}")
    if UNMAP:
        print(f"── 未映射印刷行 {len(UNMAP)} 条：")
        for u in UNMAP:
            print("   ?", u)
    if errs or serrs or mism or UNMAP or xcheck:
        print("\n❌ 校验未全过 —— 按纪律不写出 CSV。")
        return 1

    ISY = [y for y in YEARS if y in IS]
    BSY = [y for y in YEARS if y in BS]
    CFY = [y for y in YEARS if y in CF]
    SEGY = sorted(SEG)
    write_csv(os.path.join(HERE, "利润表.csv"), [UNIT + ";费用/减项=负数", LINEAGE], IS_ROWS, ISY, IS)
    write_csv(os.path.join(HERE, "资产负债表.csv"),
              [UNIT + ";按印刷原值(资产/负债/权益均为正,印刷带括号者为负)", LINEAGE], BS_ROWS, BSY, BS)
    write_csv(os.path.join(HERE, "现金流量表.csv"), [UNIT + ";流出=负数", LINEAGE], CF_ROWS, CFY, CF)
    write_csv(os.path.join(HERE, "分部营收.csv"),
              [UNIT + ";分产品收入与成本均按印刷正值",
               "来源:各年 10-K 损益表分产品行(2011-2017 主表 / 2018+ srt_ProductOrServiceAxis 维度块)",
               "🔴 用本表算分板块毛利率前必读 政策补贴与积分.csv:2023 起 IRA 制造税收抵免**直接冲减营业成本**"
               "(2025 能源 11.20 亿/汽车 5.65 亿美元),故本表的成本行已被补贴压低、毛利率被高估。"
               "能源板块 2025 报告毛利率 29.8%,剔除抵免后 21.0%"],
              SEG_ROWS, SEGY, SEG)

    RAT, RROWS = build_ratios(IS, BS, CF)
    write_csv(os.path.join(HERE, "财务比率.csv"),
              ["单位:比率为倍数(1=100%)、天数为天、金额为千美元;空=所需分项该年不可得",
               "全部由三表派生(年报不直接给)。**复权行**已按 2020-08-31 的 5:1 与 2022-08-25 的 3:1 拆股折算到 2025 年股本口径",
               LINEAGE], RROWS, [y for y in YEARS if y in RAT], RAT)

    with open(os.path.join(HERE, "重述与口径变更.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["# 跨申报交叉核分歧登记：同一会计年份在「本年自己的 10-K」与「后续 10-K 的比较列」中数值不一致的全部落点。"])
        w.writerow(["# 检出方法=对每份 10-K 的 2-3 个期间列全量采集后按(科目,会计年份)比对；单位千美元。"])
        w.writerow(["# 处置=「修正」类已在三表 CSV 中采用后续申报值(本年申报自身是 SEC 渲染/filer 标注错误)；"
                    "「重述」类保留本年 as-reported，跨年比较时须注意。"])
        w.writerow(["报表", "科目", "会计年份", "本年申报值", "后续申报值", "后续申报份数", "判定与处置"])
        for d in sorted(disputes, key=lambda x: (x[2], x[0], x[1])):
            w.writerow([d[0], d[1], d[2], f"{d[3]:.0f}", f"{d[4]:.0f}", d[5], d[6]])

    print(f"\n✅ 全部校验通过 —— 利润表 {ISY[0]}-{ISY[-1]} · 资产负债表 {BSY[0]}-{BSY[-1]} · "
          f"现金流量表 {CFY[0]}-{CFY[-1]} · 分部营收 {SEGY[0]}-{SEGY[-1]} · 重述登记 {len(disputes)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
