#!/usr/bin/env python3
"""拼多多(PDD Holdings Inc., NASDAQ: PDD)三表构建器。

数据源(一手·双轨互证):
  ①转录轨(canonical):report/拼多多/ 一手申报印刷报表逐行转录 ——
     F-1/424B4(2018-07-26,2016-2017 两年 + 2016 年末 BS 唯一真源)
     + 20-F FY2018/FY2020/FY2021/FY2022/FY2023/FY2024/FY2025(各年主表)
     取数政策 = 各年优先取「当年自身 20-F 原始披露值」。
  ②XBRL 轨(独立核):_xbrl/companyfacts-CIK0001737806.json(SEC 机读·公司自报)
     逐格与转录轨比对(容差 0),不一致即报错;2016 年 BS XBRL 不含·仅转录轨。

单位:千元人民币(RMB thousands,与 20-F 印刷口径一致);费用/流出 = 负数。
勾稽:利润表桥(毛利/营业/税前/净利)、BS(A=L+夹层+E·分节合计)、
     现金流(三活动+汇率=净变动·年初+净变=年末·投融资分项和=小计)、
     分部(拆分和=总收入/总成本)——任一不过,不写出 CSV。
"""
import csv
import json
import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(DIR)))
YEARS = list(range(2016, 2026))
N = len(YEARS)

# ============================================================
# ①转录轨(千元;费用/流出=负;None=该期无此科目)
#    来源注:F1=424B4(2018-07-26) F-页;20FYYYY=该财年 20-F F-页
# ============================================================


def R(*vals):
    assert len(vals) == N
    return {y: v for y, v in zip(YEARS, vals) if v is not None}


INCOME_ROWS = [
    # (行名, {年:值}, XBRL核对tag或None, 符号flip: XBRL值*flip==转录值)
    ("收益合计 Total revenues",
     R(504864, 1744076, 13119990, 30141886, 59491865, 93949939, 130557589, 247639205, 393836097, 431845713),
     "RevenueFromContractWithCustomerExcludingAssessedTax", 1),
    ("销售成本 Total costs of revenues",
     R(-577870, -722830, -2905249, -6338778, -19278641, -31718093, -31462298, -91723577, -153900374, -188801753),
     "CostOfRevenue", -1),
    ("毛利 Gross profit (2023起报表不再单列)",
     R(-73006, 1021246, 10214741, 23803108, 40213224, 62231846, 99095291, None, None, None),
     "GrossProfit", 1),
    ("销售及营销开支 Sales and marketing expenses",
     R(-168990, -1344582, -13441813, -27174249, -41194599, -44801720, -54343719, -82188870, -111300533, -125287932),
     "SellingAndMarketingExpense", -1),
    ("行政管理开支 General and administrative expenses",
     R(-14793, -133207, -6456612, -1296712, -1507297, -1540774, -3964935, -4075622, -7552967, -8157733),
     "GeneralAndAdministrativeExpense", -1),
    ("研发开支 Research and development expenses",
     R(-29421, -129181, -1116057, -3870358, -6891653, -8992590, -10384716, -10952374, -12659361, -16496164),
     "ResearchAndDevelopmentExpense", -1),
    ("长期投资减值(经营开支内) Impairment of a long-term investment",
     R(None, -10000, None, None, None, None, None, None, None, None), None, 1),
    ("总经营开支 Total operating expenses",
     R(-213204, -1616970, -21014482, -32341319, -49593549, -55335084, -68693370, -97216866, -131512861, -149941829),
     "OperatingExpenses", -1),
    ("经营利润 Operating profit/(loss)",
     R(-286210, -595724, -10799741, -8538211, -9380325, 6896762, 30401921, 58698762, 108422862, 93102131),
     "OperatingIncomeLoss", 1),
    ("利息及投资收益净额 Interest and investment income, net (2016-17为利息收入)",
     R(4460, 80783, 584940, 1541825, 2455366, 3061662, 3997100, 10238080, 20553493, 25583848),
     "InvestmentIncomeInterest", 1),
    ("利息费用 Interest expenses",
     R(None, None, None, -145858, -757336, -1231002, -51655, -43987, None, None), None, 1),
    ("汇兑损益 Foreign exchange gain/(loss)",
     R(475, -11547, 10037, 63179, 225197, 71750, -149710, 35721, 587866, -1966622),
     "ForeignCurrencyTransactionGainLossBeforeTax", 1),
    ("权证公允价值变动 Change in FV of warrant liability",
     R(-8668, None, None, None, None, None, None, None, None, None), None, 1),
    ("其他收益净额 Other income/(loss), net",
     R(-2034, 1373, -12361, 82786, 193702, 656255, 2221358, 2952579, 3119847, 2726933),
     "OtherNonoperatingIncomeExpense", 1),
    ("除税及权益法前利润 Profit/(loss) before income tax and equity investees",
     R(-291977, -525115, -10217125, -6996279, -7263396, 9455427, 36419014, 71881155, 132684068, 119446290),
     None, 1),  # 2016 无权益法·此行=税前;XBRL 2017+ 另核
    ("所得税 Income tax expenses",
     R(0, 0, 0, 0, 0, -1933585, -4725667, -11849904, -20266781, -21732756), None, 1),
    ("权益法投资损益 Share of results of equity investees",
     R(None, None, None, 28676, 83654, 246828, -155285, -4707, 17225, 129005),
     "IncomeLossFromEquityMethodInvestments", 1),
    ("净利润 Net income/(loss) (无少数股东·即归母)",
     R(-291977, -525115, -10217125, -6967603, -7179742, 7768670, 31538062, 60026544, 112434512, 97842539),
     "NetIncomeLoss", 1),
    ("优先股视同分配/(股东注资) Deemed distribution/(contribution)",
     R(-30430, 26413, -80496, None, None, None, None, None, None, None), None, 1),
    ("归属普通股股东净利润 Net income/(loss) attributable to ordinary shareholders",
     R(-322407, -498702, -10297621, -6967603, -7179742, 7768670, 31538062, 60026544, 112434512, 97842539),
     "NetIncomeLossAvailableToCommonStockholdersBasic", 1),
    ("——外币折算差异(OCI) FX translation difference",
     R(20001, -47681, 1058884, 412447, -2495958, -1472172, 5860304, 1332984, 2605982, -5476543),
     "OtherComprehensiveIncomeForeignCurrencyTransactionAndTranslationAdjustmentNetOfTaxPortionAttributableToParent", 1),
    ("——AFS债券未实现损益(OCI) Unrealized g/(l) on AFS debt securities",
     R(None, None, None, None, None, None, -18166, 68538, 494803, -232319),
     "OtherComprehensiveIncomeUnrealizedHoldingGainLossOnSecuritiesArisingDuringPeriodNetOfTax", 1),
    ("全面收益 Comprehensive income/(loss)",
     R(-271976, -572796, -9158241, -6555156, -9675700, 6296498, 37380200, 61428066, 115535297, 92133677),
     "ComprehensiveIncomeNetOfTax", 1),
]
EPS_ROWS = [  # 每股·元(1 ADS = 4 股普通股);股数=股
    ("每股基本盈利(元/股) Basic EPS",
     R(-0.18, -0.28, -3.47, -1.51, -1.51, 1.55, 6.24, 11.08, 20.31, 17.50), "EarningsPerShareBasic"),
    ("每股摊薄盈利(元/股) Diluted EPS",
     R(-0.18, -0.28, -3.47, -1.51, -1.51, 1.36, 5.48, 10.29, 19.00, 16.50), "EarningsPerShareDiluted"),
    ("加权平均股数-基本(股) Weighted avg shares basic",
     R(1815200000, 1764799346, 2968319549, 4627278394, 4768343300, 5012651334, 5057540124, 5416106022, 5536049000, 5590930000),
     "WeightedAverageNumberOfSharesOutstandingBasic"),
    ("加权平均股数-摊薄(股) Weighted avg shares diluted",
     R(1815200000, 1764799346, 2968319549, 4627278394, 4768343300, 5713764297, 5761291439, 5839629562, 5916592000, 5929576000),
     "WeightedAverageNumberOfDilutedSharesOutstanding"),
]

BALANCE_ROWS = [
    ("现金及现金等价物 Cash and cash equivalents",
     R(1319843, 3058152, 14160322, 5768186, 22421189, 6426715, 34326192, 59794469, 57768053, 108900587),
     "CashAndCashEquivalentsAtCarryingValue"),
    ("受限资金 Restricted cash",
     R(0, 9370849, 16379364, 27577671, 52422447, 59617256, 57974225, 61985436, 68426368, 73830824),
     "RestrictedCashCurrent"),
    ("应收在线支付平台款 Receivables from online payment platforms",
     R(10282, 88173, 247586, 1050974, 729548, 673737, 587696, 3914117, 3679309, 5109129), None),
    ("短期投资 Short-term investments",
     R(290000, 50000, 7630689, 35288827, 64551094, 86516618, 115112554, 157415365, 273791856, 313407682),
     "ShortTermInvestments"),
    ("应收关联方款 Amounts due from related parties (current)",
     R(92647, 442912, 1019033, 2365528, 4240069, 4250155, 6318830, 7428070, 7569180, 10205128), None),
    ("预付款项及其他流动资产 Prepayments and other current assets",
     R(40731, 127742, 953989, 950277, 5159531, 3424687, 2298379, 4213015, 4413466, 7526542),
     "PrepaidExpenseAndOtherAssetsCurrent"),
    ("流动资产合计 Total current assets",
     R(1753503, 13137828, 40390983, 73001463, 149523878, 160909168, 216617876, 294750472, 415648232, 518979892),
     "AssetsCurrent"),
    ("物业设备及软件净额 Property, equipment and software, net",
     R(2248, 9279, 29075, 41273, 202853, 2203323, 1044847, 979597, 879327, 1306044),
     "PropertyPlantAndEquipmentNet"),
    ("无形资产 Intangible assets",
     R(None, None, 2579338, 1994292, 1276751, 701220, 134002, 21148, 19170, 15387),
     "IntangibleAssetsNetExcludingGoodwill"),
    ("使用权资产 Right-of-use assets",
     R(None, None, None, 517188, 629827, 938537, 1416081, 4104889, 5064351, 4863332),
     "OperatingLeaseRightOfUseAsset"),
    ("递延所得税资产 Deferred tax assets",
     R(None, None, None, None, None, 31504, 1045030, 270738, 15998, 171959),
     "DeferredIncomeTaxAssetsNet"),
    ("长期投资 Long-term investment (2016仅F-1列示;2017起按FY2018口径并入其他非流动)",
     R(15000, None, None, None, None, None, None, None, None, None), None),
    ("关联方长期借款 Loan to a related party (non-current)",
     R(None, 162363, None, None, None, None, None, None, None, None), None),
    ("其他非流动资产 Other non-current assets",
     R(None, 5000, 182667, 503120, 7275305, 16425966, 16862117, 47951276, 83407238, 104707713),
     "OtherAssetsNoncurrent"),
    ("非流动资产合计 Total non-current assets",
     R(17248, 176642, 2791080, 3055873, 9384736, 20300550, 20502077, 53327648, 89386084, 111064435),
     "AssetsNoncurrent"),
    ("资产总计 Total Assets",
     R(1770751, 13314470, 43182063, 76057336, 158908614, 181209718, 237119953, 348078120, 505034316, 630044327),
     "Assets"),
    ("应付关联方款 Amounts due to related parties",
     R(24976, 76057, 478113, 1502892, 3385863, 1963007, 1676391, 1238776, 801859, 1086540), None),
    ("客户预收及递延收入 Customer advances and deferred revenues",
     R(2154, 56453, 191482, 605970, 2423190, 1166764, 1389655, 2144610, 2947041, 3378789), None),
    ("商家应付款 Payable to merchants",
     R(1116798, 9838519, 17275934, 29926488, 53833981, 62509714, 63316695, 74997252, 91655947, 107407160), None),
    ("应计费用及其他流动负债 Accrued expenses and other liabilities",
     R(41832, 360393, 2225667, 4877062, 11193372, 14085513, 20960723, 55351399, 69141831, 81657839),
     "AccountsPayableAndAccruedLiabilitiesCurrent"),
    ("商家保证金 Merchant deposits",
     R(219472, 1778085, 4188273, 7840912, 10926319, 13577552, 15058229, 16878746, 16460600, 17708197),
     "DepositLiabilityCurrent"),
    ("权证负债 Warrant liability",
     R(9064, None, None, None, None, None, None, None, None, None), None),
    ("短期借款 Short-term borrowings",
     R(None, None, None, 898748, 1866316, None, None, None, None, None), "OtherShortTermBorrowings"),
    ("可转债-流动 Convertible bonds, current portion",
     R(None, None, None, None, None, None, 13885751, 648570, 5309597, None), "ConvertibleDebtCurrent"),
    ("租赁负债-流动 Lease liabilities (current)",
     R(None, None, None, 115734, 253036, 427164, 602036, 1641548, 2105978, 2498643),
     "OperatingLeaseLiabilityCurrent"),
    ("流动负债合计 Total current liabilities",
     R(1414296, 12109507, 24359469, 45767806, 83882077, 93729714, 116889480, 152900901, 188422853, 213737168),
     "LiabilitiesCurrent"),
    ("可转债-非流动 Convertible bonds (non-current)",
     R(None, None, None, 5206682, 14432792, 11788907, 1575755, 5231523, None, None), None),
    ("租赁负债-非流动 Lease liabilities (non-current)",
     R(None, None, None, 428593, 414939, 544263, 870782, 2644260, 3191565, 2880152),
     "OperatingLeaseLiabilityNoncurrent"),
    ("递延所得税负债 Deferred tax liabilities",
     R(None, None, None, None, None, 31291, 13025, 59829, 106774, 41851),
     "DeferredIncomeTaxLiabilitiesNet"),
    ("其他非流动负债 Other non-current liabilities",
     R(None, None, None, 7389, 2918, 996, None, None, None, None), None),
    ("非流动负债合计 Total non-current liabilities",
     R(0, 0, 0, 5642664, 14850649, 12365457, 2459562, 7935612, 3298339, 2922003), None),
    ("负债合计 Total liabilities",
     R(1414296, 12109507, 24359469, 51410470, 98732726, 106095171, 119349042, 160836513, 191721192, 216659171),
     "Liabilities"),
    ("夹层权益(可赎回可转优先股) Mezzanine equity",
     R(782733, 2196921, None, None, None, None, None, None, None, None),
     "TemporaryEquityCarryingAmountAttributableToParent"),
    ("普通股(A类+B类·2021起仅A类) Ordinary shares",
     R(56, 54, 142, 148, 159, 161, 170, 177, 180, 182), None),
    ("资本公积 Additional paid-in capital",
     R(21531, 61326, 29114527, 41493949, 86698660, 95340819, 99250468, 107293091, 117829308, 125767661),
     "AdditionalPaidInCapital"),
    ("法定储备 Statutory reserves",
     R(None, None, None, None, None, None, 5000, 105982, 237680, 1338261),
     "StatutoryAccountingPracticesStatutoryCapitalAndSurplusBalance"),
    ("累计其他全面收益 Accumulated other comprehensive income/(loss)",
     R(24580, -23101, 1035783, 1448230, -1047728, -2519900, 3322238, 4723760, 7824545, 2115683),
     "AccumulatedOtherComprehensiveIncomeLossNetOfTax"),
    ("留存收益/(累计亏损) Retained earnings/(accumulated deficits)",
     R(-472445, -1030237, -11327858, -18295461, -25475203, -17706533, 15193035, 75118597, 187421411, 284163369),
     "RetainedEarningsAccumulatedDeficit"),
    ("股东权益合计 Total shareholders' equity/(deficits)",
     R(-426278, -991958, 18822594, 24646866, 60175888, 75114547, 117770911, 187241607, 313313124, 413385156),
     "StockholdersEquity"),
    ("负债、夹层及权益合计 Total liabilities, mezzanine equity and equity",
     R(1770751, 13314470, 43182063, 76057336, 158908614, 181209718, 237119953, 348078120, 505034316, 630044327),
     "LiabilitiesAndStockholdersEquity"),
]

CASHFLOW_ROWS = [
    # (行名, {年:值}, XBRL tag, flip: XBRL值*flip==转录值; Payments/Repayments类标签惯例正数=流出 → flip=-1)
    ("经营活动现金流量净额 Net cash from operating activities",
     R(879777, 9686328, 7767927, 14820976, 28196627, 28783011, 48507860, 94162531, 121929292, 106938690),
     "NetCashProvidedByUsedInOperatingActivities", 1),
    ("投资活动现金流量净额 Net cash from investing activities",
     R(-307301, 71651, -7548509, -28319678, -38357901, -35562365, -22361670, -55431278, -118356036, -43423236),
     "NetCashProvidedByUsedInInvestingActivities", 1),
    ("融资活动现金流量净额 Net cash from financing activities",
     R(486538, 1398860, 17344357, 15854731, 51798996, -1875154, 10079, -8960626, 1164, -5227353),
     "NetCashProvidedByUsedInFinancingActivities", 1),
    ("汇率变动影响 Exchange rate effect",
     R(20397, -47681, 546910, 450142, -139943, -145157, 100177, -291139, 840096, -1751111), None, 1),
    ("现金及受限现金净变动 Net increase/(decrease) in cash & restricted cash",
     R(1079411, 11109158, 18110685, 2806171, 41497779, -8799665, 26256446, 29479488, 4414516, 56536990),
     "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect", 1),
    ("年初现金及受限现金 Beginning balance",
     R(240432, 1319843, 12429001, 30539686, 33345857, 74843636, 66043971, 92300417, 121779905, 126194421), None, 1),
    ("年末现金及受限现金 Ending balance",
     R(1319843, 12429001, 30539686, 33345857, 74843636, 66043971, 92300417, 121779905, 126194421, 182731411),
     "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", 1),
    ("--- 补充:经营内关键非现金/调整项 ---", {}, None, 1),
    ("折旧及摊销 Depreciation and amortization",
     R(756, 2265, 497003, 637831, 651523, 1495380, 2224169, 786235, 708763, 601483),
     "DepreciationAndAmortization", 1),
    ("股权薪酬 Share-based compensation",
     R(4064, 13380, 6841573, 2557706, 3613043, 4774730, 7718365, 7078794, 9883564, 7936971),
     "ShareBasedCompensation", 1),
    ("投资公允价值变动(收益) Fair value change of investments",
     R(None, None, None, None, 104068, -22170, -242236, 1013475, 6816454, 10405890), None, 1),
    ("--- 投资活动分项 ---", {}, None, 1),
    ("资本开支(购置物业设备软件及无形) Purchase of property, equipment, software & intangibles",
     R(-2301, -8921, -27331, -27436, -43046, -3287232, -635716, -583879, -967137, -1145077), None, 1),
    ("购买短期投资(含定期存款/持有至到期) Purchase of short-term investments",
     R(-320000, -1393000, -7516370, -52451615, -86438068, -116639550, -160414453, -147131673, -210272769, -209632316),
     "PaymentsToAcquireShortTermInvestments", -1),
    ("出售/回收短期投资 Proceeds from short-term investments",
     R(30000, 1633000, 50000, 24797630, 55083390, 97547038, 141928351, 130317231, 147287723, 230909306),
     "ProceedsFromSaleOfShortTermInvestments", 1),
    ("购买长期投资(含长期定期存款) Purchase of long-term investments",
     R(-15000, None, -184637, -214100, -6722228, -13628052, -6795838, -25051222, -43847005, -42382910),
     "PaymentsToAcquireLongtermInvestments", -1),
    ("出售/回收长期投资 Proceeds from long-term investments",
     R(None, None, 5000, None, None, None, 7137814, None, 2000000, 709199), None, 1),
    ("购买AFS债券 Purchase of available-for-sale debt securities",
     R(None, None, None, None, None, None, -3581868, -17318333, -13732957, -28544366),
     "PaymentsToAcquireAvailableForSaleSecuritiesDebt", -1),
    ("出售AFS债券 Proceeds from AFS debt securities",
     R(None, None, None, None, None, None, None, 4206359, 1140417, 6862682),
     "ProceedsFromSaleOfAvailableForSaleSecuritiesDebt", 1),
    ("--- 融资活动分项 ---", {}, None, 1),
    ("IPO募资(净发行成本前) Proceeds from IPO",
     R(None, None, 11879944, None, None, None, None, None, None, None),
     "ProceedsFromIssuanceInitialPublicOffering", 1),
    ("IPO发行成本 IPO costs", R(None, None, -356313, None, None, None, None, None, None, None), None, 1),
    ("增发净额 Net proceeds from follow-on offerings",
     R(None, None, None, 7993828, 26805438, None, None, None, None, None), None, 1),
    ("私募配售 Proceeds from private placements",
     R(None, None, None, None, 11063339, None, None, None, None, None),
     "ProceedsFromIssuanceOfPrivatePlacement", 1),
    ("可转债发行净额 Net proceeds from convertible bonds",
     R(None, None, None, 6963881, 13024199, None, None, None, None, None), None, 1),
    ("可转债偿还/回购 Repayment or repurchase of convertible bonds",
     R(None, None, None, None, None, None, None, -8968817, -91, -5228716),
     "RepaymentsOfConvertibleDebt", -1),
    ("优先股发行 Proceeds from issuance of convertible preferred shares",
     R(511911, 1446906, 5824568, None, None, None, None, None, None, None),
     "ProceedsFromIssuanceOfConvertiblePreferredStock", 1),
    ("优先股发行成本 Costs for issuance of preferred shares",
     R(-7047, -15369, -3842, None, None, None, None, None, None, None),
     "PaymentsForRepurchaseOfRedeemableConvertiblePreferredStock", -1),
    ("回购B类普通股 Repurchase of Class B ordinary shares",
     R(None, -32677, None, None, None, None, None, None, None, None), None, 1),
    ("视同分配 Deemed distribution", R(-18326, None, None, None, None, None, None, None, None, None), None, 1),
    ("短期借款取得 Proceeds from short-term borrowings",
     R(None, None, None, 897022, 1828923, None, None, None, None, None), None, 1),
    ("短期借款偿还 Repayment of short-term borrowings",
     R(None, None, None, None, -922897, -1875472, None, None, None, None), None, 1),
    ("其他融资项 Others (financing)",
     R(None, None, None, None, -6, 318, 10079, 8191, 1255, 1363), None, 1),
    ("已付股息 Dividends paid (上市以来从未分红)",
     R(None, None, None, None, None, None, None, None, None, None), None, 1),
    ("--- 补充披露 ---", {}, None, 1),
    ("利息已收 Interest received",
     R(3992, 52150, 433390, 1211443, 1881812, 2936860, 3567738, 7273373, 9429226, 12323119), None, 1),
    ("所得税已付 Income taxes paid",
     R(None, None, None, None, None, None, 4881252, 5764435, 17492828, 21602615), None, 1),
]

SEGMENT_ROWS = [
    ("在线营销服务及其他 Online marketing services and others",
     R(None, None, 11515575, 26813641, 47953779, 72563402, 102721924, 153540553, 197934192, 217783028)),
    ("交易服务(佣金) Transaction services",
     R(None, None, 1604415, 3328245, 5787415, 14140449, 27626494, 94098652, 195901905, 214062685)),
    ("商品销售(1P自营) Merchandise sales",
     R(456588, 3385, 0, 0, 5750671, 7246088, 209171, 0, 0, 0)),
    ("平台服务(2016-17旧口径·营销+交易未拆分) Online marketplace services",
     R(48276, 1740691, None, None, None, None, None, None, None, None)),
    ("收益合计 Total revenues",
     R(504864, 1744076, 13119990, 30141886, 59491865, 93949939, 130557589, 247639205, 393836097, 431845713)),
    ("--- 销售成本拆分 ---", {}),
    ("支付处理费 Payment processing fees",
     R(None, None, -639290, -341879, -1545564, -3108086, -3450929, -6824386, -11355177, -14319278)),
    ("平台运营及其他成本 Costs of platform operation and others",
     R(None, None, -2265959, -5996899, -17733077, -28610007, -28011369, -84899191, -142545197, -174482475)),
    ("销售成本合计 Total costs of revenues",
     R(-577870, -722830, -2905249, -6338778, -19278641, -31718093, -31462298, -91723577, -153900374, -188801753)),
]

# ============================================================
# ②XBRL 轨:逐格独立核
# ============================================================
XBRL_PATH = os.path.join(DIR, "_xbrl", "companyfacts-CIK0001737806.json")
with open(XBRL_PATH) as f:
    GAAP = json.load(f)["facts"]["us-gaap"]


def xbrl_annual(tag, unit="CNY", instant=False):
    node = GAAP.get(tag)
    if not node:
        return {}
    cand = {}
    for r in node.get("units", {}).get(unit, []):
        if r.get("form") != "20-F":
            continue
        end = r.get("end", "")
        if not end.endswith("-12-31"):
            continue
        yr = int(end[:4])
        if instant:
            if r.get("start") is not None:
                continue
        else:
            s = r.get("start")
            if not s or s[5:7] != "01" or s[:4] != end[:4]:
                continue
        cand.setdefault(yr, []).append(r)
    return {yr: sorted(rs, key=lambda x: (x.get("fy", 9999), x.get("filed", "")))[0]["val"]
            for yr, rs in cand.items()}


def crosscheck(rows, instant, label, eps_mode=False):
    bad = 0
    for row in rows:
        name, vals, tag = row[0], row[1], row[2]
        flip = row[3] if len(row) > 3 else 1
        if not tag:
            continue
        unit = "CNY/shares" if (eps_mode and "EPS" in name) else ("shares" if "股数" in name else "CNY")
        xb = xbrl_annual(tag, unit=unit, instant=instant)
        for y, v in vals.items():
            if y not in xb:
                continue
            xv = xb[y] * flip
            tv = v if (eps_mode) else v * 1000  # 转录=千元, XBRL=元
            if eps_mode:
                if "EPS" in name:
                    ok = abs(xv - tv) < 0.005
                else:  # 股数:FY2024 20-F 按千股口径打 XBRL 标签 → 允许千倍匹配
                    ok = abs(xv - tv) < 1500000 or abs(xv * 1000 - tv) < 1500000
            else:
                ok = abs(xv - tv) < 500  # 元级容差
            if not ok:
                print(f"  ❌ {label}·{name[:30]} {y}: 转录={tv} vs XBRL={xv}")
                bad += 1
    return bad


print("=" * 72)
print("① XBRL 独立核(转录轨 vs SEC 机读·逐格)")
bad = 0
bad += crosscheck(INCOME_ROWS, instant=False, label="利润表")
bad += crosscheck([(n, v, t, 1) for n, v, t in EPS_ROWS], instant=False, label="EPS", eps_mode=True)
bad += crosscheck([(n, v, t, 1) for n, v, t in BALANCE_ROWS], instant=True, label="资产负债表")
bad += crosscheck(CASHFLOW_ROWS, instant=False, label="现金流")
print(f"  XBRL 核对不一致格数: {bad}")

# ============================================================
# ③勾稽自洽(逐年)
# ============================================================
def gv(rows, name_prefix, y):
    for row in rows:
        if row[0].startswith(name_prefix):
            return row[1].get(y)
    return None


def z(x):
    return 0 if x is None else x


print("\n② 勾稽自洽(千元·残差应=0)")
fails = 0
for y in YEARS:
    rev = gv(INCOME_ROWS, "收益合计", y)
    cos = gv(INCOME_ROWS, "销售成本", y)
    gp = gv(INCOME_ROWS, "毛利", y)
    opx = gv(INCOME_ROWS, "总经营开支", y)
    op = gv(INCOME_ROWS, "经营利润", y)
    r1 = (rev + cos - gp) if gp is not None else 0
    r2 = rev + cos + opx - op
    r3 = z(gv(INCOME_ROWS, "销售及营销", y)) + z(gv(INCOME_ROWS, "行政管理", y)) + \
        z(gv(INCOME_ROWS, "研发开支", y)) + z(gv(INCOME_ROWS, "长期投资减值", y)) - opx
    pre = gv(INCOME_ROWS, "除税及权益法前", y)
    r4 = op + z(gv(INCOME_ROWS, "利息及投资收益", y)) + z(gv(INCOME_ROWS, "利息费用", y)) + \
        z(gv(INCOME_ROWS, "汇兑损益", y)) + z(gv(INCOME_ROWS, "权证公允", y)) + \
        z(gv(INCOME_ROWS, "其他收益净额", y)) - pre
    ni = gv(INCOME_ROWS, "净利润", y)
    r5 = pre + z(gv(INCOME_ROWS, "所得税", y)) + z(gv(INCOME_ROWS, "权益法投资损益", y)) - ni
    r6 = ni + z(gv(INCOME_ROWS, "优先股视同分配", y)) - gv(INCOME_ROWS, "归属普通股股东", y)
    oci = z(gv(INCOME_ROWS, "——外币折算差异", y)) + z(gv(INCOME_ROWS, "——AFS债券未实现", y))
    r7 = ni + oci - gv(INCOME_ROWS, "全面收益", y)
    resid_is = [r1, r2, r3, r4, r5, r6, r7]

    tca = gv(BALANCE_ROWS, "流动资产合计", y)
    ra = sum(z(gv(BALANCE_ROWS, p, y)) for p in
             ["现金及现金等价物", "受限资金", "应收在线支付平台", "短期投资", "应收关联方", "预付款项"]) - tca
    tnca = gv(BALANCE_ROWS, "非流动资产合计", y)
    rb = sum(z(gv(BALANCE_ROWS, p, y)) for p in
             ["物业设备及软件", "无形资产", "使用权资产", "递延所得税资产", "长期投资 ", "关联方长期借款", "其他非流动资产"]) - tnca
    ta = gv(BALANCE_ROWS, "资产总计", y)
    rc = tca + tnca - ta
    tcl = gv(BALANCE_ROWS, "流动负债合计", y)
    rd = sum(z(gv(BALANCE_ROWS, p, y)) for p in
             ["应付关联方款", "客户预收", "商家应付款", "应计费用", "商家保证金", "权证负债", "短期借款",
              "可转债-流动", "租赁负债-流动"]) - tcl
    tncl = gv(BALANCE_ROWS, "非流动负债合计", y)
    re_ = sum(z(gv(BALANCE_ROWS, p, y)) for p in
              ["可转债-非流动", "租赁负债-非流动", "递延所得税负债", "其他非流动负债"]) - tncl
    tl = gv(BALANCE_ROWS, "负债合计", y)
    rf = tcl + tncl - tl
    eq = gv(BALANCE_ROWS, "股东权益合计", y)
    rg = sum(z(gv(BALANCE_ROWS, p, y)) for p in
             ["普通股", "资本公积", "法定储备", "累计其他全面收益", "留存收益"]) - eq
    rh = tl + z(gv(BALANCE_ROWS, "夹层权益", y)) + eq - gv(BALANCE_ROWS, "负债、夹层及权益合计", y)
    ri = gv(BALANCE_ROWS, "负债、夹层及权益合计", y) - ta
    resid_bs = [ra, rb, rc, rd, re_, rf, rg, rh, ri]

    o, i, fcf_, fx = (gv(CASHFLOW_ROWS, "经营活动", y), gv(CASHFLOW_ROWS, "投资活动", y),
                      gv(CASHFLOW_ROWS, "融资活动", y), gv(CASHFLOW_ROWS, "汇率变动", y))
    chg = gv(CASHFLOW_ROWS, "现金及受限现金净变动", y)
    rj = o + i + fcf_ + fx - chg
    rk = gv(CASHFLOW_ROWS, "年初现金", y) + chg - gv(CASHFLOW_ROWS, "年末现金", y)
    rl = gv(BALANCE_ROWS, "现金及现金等价物", y) + gv(BALANCE_ROWS, "受限资金", y) - gv(CASHFLOW_ROWS, "年末现金", y)
    resid_cf = [rj, rk, rl]

    seg = sum(z(gv(SEGMENT_ROWS, p, y)) for p in ["在线营销服务", "交易服务", "商品销售", "平台服务"]) - \
        gv(SEGMENT_ROWS, "收益合计", y)
    cs = gv(SEGMENT_ROWS, "支付处理费", y)
    rseg2 = (z(cs) + z(gv(SEGMENT_ROWS, "平台运营及其他", y)) - gv(SEGMENT_ROWS, "销售成本合计", y)) if cs is not None else 0

    allres = resid_is + resid_bs + resid_cf + [seg, rseg2]
    if any(abs(r) > 1 for r in allres):
        print(f"  {y}: ❌ IS={resid_is} BS={resid_bs} CF={resid_cf} SEG={[seg, rseg2]}")
        fails += 1
    else:
        print(f"  {y}: OK(利润表7式+资产负债表9式+现金流3式+分部2式 全平)")

if bad or fails:
    print(f"\n🛑 校验未过(XBRL不一致 {bad} 格 / 勾稽失败 {fails} 年)——不写出 CSV")
    sys.exit(1)

# ============================================================
# ④写出 CSV
# ============================================================
SRC = ("一手申报印刷报表逐行转录(F-1/424B4 2018-07-26 + 20-F FY2018-FY2025·report/拼多多/)"
       "·SEC XBRL companyfacts 逐格独立核通过")


def fmt(v):
    if v is None:
        return ""
    if isinstance(v, float) and abs(v) < 1000:
        return f"{v:.2f}"
    return str(int(v))


def write_csv(fname, comment, rows):
    with open(os.path.join(DIR, fname), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([comment])
        w.writerow(["科目"] + [str(y) for y in YEARS])
        for row in rows:
            name, vals = row[0], row[1]
            w.writerow([name] + [fmt(vals.get(y)) for y in YEARS])
    print(f"✅ {fname} ({len(rows)} 行)")


write_csv("利润表.csv",
          f"# 单位:千元人民币(RMB thousands·与20-F印刷一致);费用/损失=负数;EPS=元/股(1 ADS=4股);覆盖2016-2025;来源:{SRC}",
          INCOME_ROWS + [(n, v) for n, v, _t in EPS_ROWS])
write_csv("资产负债表.csv",
          f"# 单位:千元人民币;覆盖2016-2025(2016年末BS独家来自F-1);来源:{SRC}",
          BALANCE_ROWS)
write_csv("现金流量表.csv",
          f"# 单位:千元人民币;流出=负数;含投融资分项与补充披露;覆盖2016-2025;来源:{SRC}",
          CASHFLOW_ROWS)
write_csv("分部营收.csv",
          f"# 单位:千元人民币;单一可报告分部·此为收入类型拆分(20-F Revenues注/MD&A);未披露Temu/主站或地理拆分;覆盖2016-2025;来源:{SRC}",
          SEGMENT_ROWS)

# ============================================================
# ⑤财务比率(通用底 scripts/derived.py + 拼多多定制层)
# ============================================================
sys.path.insert(0, os.path.join(REPO, "scripts"))
import derived  # noqa: E402


def ser(rows, prefix):
    for row in rows:
        if row[0].startswith(prefix):
            return [row[1].get(y) for y in YEARS]
    return [None] * N


PLx = {
    "营业收入": ser(INCOME_ROWS, "收益合计"),
    "营业成本": ser(INCOME_ROWS, "销售成本"),
    "销售费用": ser(INCOME_ROWS, "销售及营销开支"),
    "管理费用": ser(INCOME_ROWS, "行政管理开支"),
    "研发费用": ser(INCOME_ROWS, "研发开支"),
    "净利润": ser(INCOME_ROWS, "净利润"),
    "归属于母公司股东的净利润": ser(INCOME_ROWS, "净利润"),  # 无少数股东
}
BSx = {
    "应收账款": ser(BALANCE_ROWS, "应收在线支付平台款"),  # PDD最接近贸易应收的行
    "应付账款": ser(BALANCE_ROWS, "商家应付款"),          # 最大无息占款行
    "预付款项": ser(BALANCE_ROWS, "预付款项及其他流动资产"),
    "固定资产": ser(BALANCE_ROWS, "物业设备及软件净额"),
    "资产总计": ser(BALANCE_ROWS, "资产总计"),
    "股东权益合计": ser(BALANCE_ROWS, "股东权益合计"),
    "现金及现金等价物": ser(BALANCE_ROWS, "现金及现金等价物"),
    "受限资金": ser(BALANCE_ROWS, "受限资金"),
    "交易性金融资产": ser(BALANCE_ROWS, "短期投资"),  # 计入现金及金融资产画像
}
CFx = {
    "经营活动现金流量净额": ser(CASHFLOW_ROWS, "经营活动现金流量净额"),
    "购建固定资产": ser(CASHFLOW_ROWS, "资本开支"),
    "已付股息": [None] * N,
}
common, unmatched = derived.compute_common_ratios(PLx, BSx, CFx)

rev = PLx["营业收入"]
ni = PLx["净利润"]
op = ser(INCOME_ROWS, "经营利润")
sbc = ser(CASHFLOW_ROWS, "股权薪酬")
ocf = CFx["经营活动现金流量净额"]
capex = CFx["购建固定资产"]
tax = ser(INCOME_ROWS, "所得税")
pre = ser(INCOME_ROWS, "除税及权益法前利润")
cash = BSx["现金及现金等价物"]
rc = BSx["受限资金"]
sti = BSx["交易性金融资产"]
onca = ser(BALANCE_ROWS, "其他非流动资产")
ta = BSx["资产总计"]
pm = ser(BALANCE_ROWS, "商家应付款")
md = ser(BALANCE_ROWS, "商家保证金")
ca = ser(BALANCE_ROWS, "客户预收及递延收入")
stb = ser(BALANCE_ROWS, "短期借款")
cb1 = ser(BALANCE_ROWS, "可转债-流动")
cb2 = ser(BALANCE_ROWS, "可转债-非流动")


def d(a, b):
    return a / b if (a is not None and b not in (None, 0)) else None


def zz(x):
    return 0 if x is None else x


fcf = [ocf[i] + capex[i] if (ocf[i] is not None and capex[i] is not None) else None for i in range(N)]
float_ = [zz(pm[i]) + zz(md[i]) + zz(ca[i]) for i in range(N)]
netcash = [zz(cash[i]) + zz(rc[i]) + zz(sti[i]) - zz(stb[i]) - zz(cb1[i]) - zz(cb2[i]) for i in range(N)]
fin_rows = ["IPO募资", "IPO发行成本", "增发净额", "私募配售", "可转债发行净额", "可转债偿还/回购",
            "优先股发行 ", "优先股发行成本", "回购B类普通股"]
fin_yearly = [sum(zz(ser(CASHFLOW_ROWS, p)[i]) for p in fin_rows) for i in range(N)]
cum_fin = []
_acc = 0
for v in fin_yearly:
    _acc += v
    cum_fin.append(_acc)
payout_yearly = [zz(ser(CASHFLOW_ROWS, "已付股息")[i]) + zz(ser(CASHFLOW_ROWS, "回购B类普通股")[i]) +
                 zz(ser(CASHFLOW_ROWS, "视同分配")[i]) for i in range(N)]
cum_payout = []
_acc2 = 0
for v in payout_yearly:
    _acc2 += v
    cum_payout.append(_acc2)
custom = [
    ("经营利润率 Operating margin", [d(op[i], rev[i]) for i in range(N)], "pct"),
    ("累计股权及可转债净融资(千元·含上市前优先股·截至该年末)", cum_fin, "mn"),
    ("累计分红+回购(千元·负=流出;含2017回购B类与视同分配)", cum_payout, "mn"),
    ("股权薪酬/营收 SBC/Revenue", [d(sbc[i], rev[i]) for i in range(N)], "pct"),
    ("自由现金流FCF(千元) OCF−Capex", fcf, "mn"),
    ("FCF/净利 FCF/Net income", [d(fcf[i], ni[i]) for i in range(N)], "x"),
    ("有效税率 Effective tax rate", [d(abs(tax[i]), pre[i]) if (tax[i] is not None and pre[i] and pre[i] > 0) else None
                                  for i in range(N)], "pct"),
    ("无息浮存(商家应付+保证金+客户预收)(千元)", float_, "mn"),
    ("无息浮存/营收 Float/Revenue", [d(float_[i], rev[i]) for i in range(N)], "pct"),
    ("类现金及投资(现金+受限+短投+其他非流动)(千元)【注:其他非流动以定期存款/HTM债券为主】",
     [zz(cash[i]) + zz(rc[i]) + zz(sti[i]) + zz(onca[i]) for i in range(N)], "mn"),
    ("净现金(现金+受限+短投−短借−可转债)(千元)", netcash, "mn"),
    ("净现金/总资产 Net cash/TA", [d(netcash[i], ta[i]) for i in range(N)], "pct"),
]


def fmt_ratio(v, f):
    if v is None:
        return ""
    if f in ("pct", "x"):
        return f"{v:.4f}"
    if f == "day":
        return f"{v:.3f}"
    if f == "mn":
        return f"{v:.0f}"
    return ""


rows = [(n, v, f) for (n, v, f) in common] + custom
with open(os.path.join(DIR, "财务比率.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["# 派生比率(比率=小数;金额行=千元;周转=天);通用底 scripts/derived.py + 拼多多定制层;覆盖2016-2025;"
                "US GAAP 无扣非披露线故扣非行 n/a(公司自报 Non-GAAP 净利未入库);上市以来分红=0故分红率行空"])
    w.writerow(["科目"] + [str(y) for y in YEARS])
    for name, vals, f_ in rows:
        w.writerow([name] + [fmt_ratio(v, f_) for v in vals])
print(f"✅ 财务比率.csv ({len(rows)} 行)")
if unmatched:
    print("  derived 未匹配(PDD 无此科目属正常):", "、".join(sorted(set(unmatched))))
print("\n全部完成:利润表/资产负债表/现金流量表/分部营收/财务比率 5 份 CSV")
