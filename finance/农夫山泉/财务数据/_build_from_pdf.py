# -*- coding: utf-8 -*-
"""农夫山泉 三表数据 + 派生比率 → 写 CSV，内置勾稽自洽校验(校验不过不写出)。

覆盖 2017-2025 全 9 年:
  2017/2018/2019 列 ← report/农夫山泉/招股说明书.pdf 附录一 会计师报告(安永审计)
                        损益 I-4(物理p313) / 全面收益 I-5 / 财务状况 I-6~I-7(p315-316)
                        权益变动 I-8~I-11 / 现金流 I-12~I-15(p417-455) / PPE附注14 I-63~I-65(p372-379)
  2025/2024 列 ← report/农夫山泉/2025.pdf (损益 P114 / 财务状况 P116-117 / 现金流 P120-121)
  2023/2022 列 ← report/农夫山泉/2023.pdf (P111 / P113-114 / P117-118)
  2021/2020 列 ← report/农夫山泉/2021.pdf (P104 / P106-107 / P110-111)

口径:
  - 单位 = 人民币千元 (RMB'000, 财报原始口径)
  - 资产负债权益 = 全部正数 (与财报呈现一致)
  - 现金流量表 = 流出/减项用负数, 流入/加项用正数
  - None = 该期财报无此科目 / 分类变动仅在出现的年份有值 (CSV 留空)

关键分类差异 (招股书 2017-2019 口径 vs 年报 2020-2025 口径, 按并集对齐留空):
  - 2017-2019 有「结构性存款(流动)」「现金及现金等价物(招股书口径)」「非控股权益」; 2020+ 无(留空)
  - 2020+ 有「长期银行存款(非流动)」「现金及银行结余」; 2017-2019 无(留空)
  - 2017-2018 存在非控股权益(38,033/44,219 千元), 2019 起清零 → 母公司应占溢利/权益 与合计分列
  - 跨边界连续性实证: 2019 年末现金 783,142 = 2020 年初现金 783,142 (招股书↔年报无缝衔接)

2025 年报口径变动:
  - 流动资产下「质押存款」改名「受限资金 Restricted cash」(本脚本统一作「受限资金/质押存款(流动)」)
  - FVTPL 流动金融资产位置从「质押存款上方」移到「现金及银行结余下方」
"""
import csv
import os

YEARS = [2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]
N = len(YEARS)
OUT = os.path.dirname(os.path.abspath(__file__))


# ====== 综合损益表 (含全面收益) ======  9 年: 2017 2018 2019 | 2020 2021 2022 2023 2024 2025
利润表 = [
    ("收益 Revenue",                                    [17491214, 20475045, 24021041, 22877297, 29696406, 33239187, 42667221, 42895992, 52552910]),
    ("销售成本 Cost of sales",                          [-7681940, -9554211, -10710410, -9368970, -12040188, -14143776, -17260392, -17980277, -20744806]),
    ("毛利 Gross profit",                               [9809274, 10920834, 13310631, 13508327, 17656218, 19095411, 25406829, 24915715, 31808104]),
    ("其他收入及收益 Other income and gains",           [402387, 533548, 773959, 640941, 873562, 1709159, 1841454, 2128940, 1719977]),
    ("销售及分销开支 Selling and distribution expenses",[-4889967, -5217524, -5816393, -5510507, -7233070, -7820691, -9283999, -9173297, -9800460]),
    ("行政开支 Administrative expenses",                [-859485, -1065167, -1382507, -1324448, -1750929, -1835125, -2162401, -1962470, -2452127]),
    ("其他开支 Other expenses",                         [-18858, -404340, -371405, -249097, -138536, -22394, -13946, -29561, -291002]),
    ("财务费用 Finance costs",                          [-8381, -4113, -15525, -78963, -52945, -76028, -99735, -91469, -66899]),
    ("除税前溢利 Profit before tax",                    [4434970, 4763238, 6498760, 6986253, 9354300, 11050332, 15688202, 15787858, 20917593]),
    ("所得税开支 Income tax expense",                   [-1049021, -1151526, -1544516, -1708827, -2192506, -2555082, -3608704, -3664554, -5049319]),
    ("年内溢利 Profit for the year",                    [3385949, 3611712, 4954244, 5277426, 7161794, 8495250, 12079498, 12123304, 15868274]),
    ("母公司拥有人应占溢利 Attributable to parent",     [3380409, 3606059, 4948568, 5277426, 7161794, 8495250, 12079498, 12123304, 15868274]),
    ("非控股权益应占溢利 NCI profit",                   [5540, 5653, 5676, None, None, None, None, None, None]),
    ("每股基本及摊薄盈利(元) Basic and diluted EPS",    [0.31, 0.33, 0.46, 0.48, 0.64, 0.76, 1.07, 1.078, 1.411]),
    ("其他全面(亏损)收益-汇兑差额 OCI Exchange diff",   [-2326, 285, 2396, -1302, -543, 1835, -340, 409, -50]),
    ("年内全面收益总额 Total comprehensive income",     [3383623, 3611997, 4956640, 5276124, 7161251, 8497085, 12079158, 12123713, 15868224]),
]


# ====== 综合财务状况表 (资产负债权益, 全部正数) ======
资产负债表 = [
    # 非流动资产
    ("物业、厂房及设备 Property, plant and equipment",         [8930732, 11088681, 12314346, 12591585, 12800140, 15397585, 17179628, 21083239, 24719336]),
    ("使用权资产 Right-of-use assets",                         [546377, 599817, 656421, 694565, 724242, 853488, 946979, 1026650, 1262195]),
    ("无形资产 Intangible assets",                             [36037, 63676, 59841, 57885, 65104, 58077, 74222, 71557, 80894]),
    ("递延税项资产 Deferred tax assets",                       [212946, 340767, 372789, 314633, 293090, 433105, 921333, 1087893, 1346932]),
    ("长期银行存款 Long-term bank deposits",                   [None, None, None, None, 1121461, 4101670, 1510722, 10630882, 11087643]),
    ("质押存款(非流动) Pledged deposits (non-current)",        [None, None, None, None, None, None, None, None, 20000]),
    ("其他非流动资产 Other non-current assets",                [39734, 16012, 20738, 9105, 56405, 49435, 42831, 188217, 88574]),
    ("非流动资产总额 Total non-current assets",                [9765826, 12108953, 13424135, 13667773, 15060442, 20893360, 20675715, 34088438, 38605574]),
    # 流动资产
    ("存货 Inventories",                                       [1442450, 1906335, 1762103, 1805454, 1809230, 2108372, 3091729, 5013047, 5846475]),
    ("贸易应收款项及应收票据 Trade and bills receivables",     [194069, 222651, 306003, 357564, 476276, 478587, 547021, 581372, 598151]),
    ("预付款项、其他应收款项及其他资产 Prepayments etc",       [568991, 1165323, 1021088, 909741, 558169, 560307, 694778, 1218292, 1377874]),
    ("结构性存款(流动·招股书口径) Structured deposits (cur)",  [2035000, 3600000, 200000, None, None, None, None, None, None]),
    ("受限资金/质押存款(流动) Restricted cash / Pledged dep",  [48959, 5634, None, None, 3648, 3059, 2677, 7677, 8126]),
    ("现金及现金等价物(招股书口径) Cash & cash equivalents",   [2562883, 1763664, 1083142, None, None, None, None, None, None]),
    ("现金及银行结余 Cash and bank balances",                  [None, None, None, 9118880, 14783577, 15211156, 24125210, 10722048, 11177574]),
    ("FVTPL金融资产(流动) Financial assets at FVTPL (current)",[4415, 177438, None, None, 204754, None, None, 1529438, 7555354]),
    ("流动资产总额 Total current assets",                      [6856767, 8841045, 4372336, 12191639, 17835654, 18361481, 28461415, 19071874, 26563554]),
    # 流动负债
    ("贸易应付款项及应付票据 Trade and bills payables",        [821043, 837328, 791462, 881800, 1153133, 1425069, 1770098, 1499397, 1654233]),
    ("其他应付款项及应计费用 Other payables and accruals",     [1991760, 2604345, 2855079, 3322040, 4487638, 6505820, 9288983, 9543746, 11961882]),
    ("合约负债 Contract liabilities",                          [1578017, 1995570, 2077549, 2247323, 2350952, 2677190, 3584921, 3565558, 4194560]),
    ("衍生金融工具(流动负债) Derivative financial instruments",[None, None, None, 7331, None, None, None, None, None]),
    ("计息借贷(流动) Interest-bearing borrowings (current)",   [50066, None, 1000000, 2413957, 2500108, 2425093, 3120619, 3625433, 4390000]),
    ("租赁负债(流动) Lease liabilities (current)",             [21259, 29027, 5941, 14068, 46721, 68678, 58030, 55705, 61838]),
    ("应付税项 Tax payables",                                  [734541, 697127, 711435, 938127, 1050359, 1499579, 2053907, 1694898, 2560299]),
    ("流动负债总额 Total current liabilities",                 [5196686, 6163397, 7441466, 9824646, 11588911, 14601429, 19876558, 19984737, 24822812]),
    ("流动资产/(负债)净额 Net current assets/(liabilities)",   [1660081, 2677648, -3069130, 2366993, 6246743, 3760052, 8584857, -912863, 1740742]),
    ("总资产减流动负债 Total assets less current liabilities", [11425907, 14786601, 10355005, 16034766, 21307185, 24653412, 29260572, 33175575, 40346316]),
    # 非流动负债
    ("递延收益 Deferred income",                               [229166, 208927, 248088, 267272, 264550, 291420, 303061, 319404, 359322]),
    ("递延税项负债 Deferred tax liabilities",                  [138, 145281, 194628, 233907, 257697, 246737, 355356, 503098, 476153]),
    ("租赁负债(非流动) Lease liabilities (non-current)",       [31135, 16628, 30421, 41305, 43304, 31179, 31250, 65909, 40861]),
    ("非流动负债总额 Total non-current liabilities",           [260439, 370836, 473137, 542484, 565551, 569336, 689667, 888411, 876336]),
    ("资产净额 Net assets",                                    [11165468, 14415765, 9881868, 15492282, 20741634, 24084076, 28570905, 32287164, 39469980]),
    # 权益
    ("股本 Share capital",                                     [360000, 360000, 360000, 1124647, 1124647, 1124647, 1124647, 1124647, 1124647]),
    ("储备 Reserves",                                          [10767435, 14011546, 9521868, 14367635, 19616987, 22959429, 27446258, 31162517, 38345333]),
    ("母公司拥有人应占权益 Equity attrib to parent",           [11127435, 14371546, 9881868, 15492282, 20741634, 24084076, 28570905, 32287164, 39469980]),
    ("非控股权益 Non-controlling interests",                   [38033, 44219, None, None, None, None, None, None, None]),
    ("权益总额 Total equity",                                  [11165468, 14415765, 9881868, 15492282, 20741634, 24084076, 28570905, 32287164, 39469980]),
]


# ====== 综合现金流量表 (流出用负数, 流入用正数) ======
现金流量表 = [
    # 经营活动 - 非现金调整
    ("除税前溢利 Profit before tax",                                  [4434970, 4763238, 6498760, 6986253, 9354300, 11050332, 15688202, 15787858, 20917593]),
    ("物业厂房及设备折旧 Depreciation of PPE",                        [1103867, 1326057, 1663650, 1871177, 2287083, 2358940, 2522236, 2727727, 3213368]),
    ("使用权资产折旧 Depreciation of right-of-use assets",            [38096, 52965, 57753, 41437, 83123, 119238, 97774, 135676, 160179]),
    ("无形资产摊销 Amortisation of intangible assets",                [17821, 15719, 12170, 12834, 7980, 8747, 11432, 11298, 19011]),
    ("FVTPL公平值(收益)/亏损 Fair value (gains)/loss on FVTPL",       [-1779, 14193, -35750, None, -4754, -2289, None, -9438, -45354]),
    ("出售FVTPL金融资产收益 Gains on disposal of FVTPL",              [None, None, None, None, None, None, None, -50952, -125904]),
    ("出售物业厂房设备项目亏损/(收益) Loss/(gain) disposal of PPE",   [7343, 7143, -35709, 2361, 9803, 14456, 5265, 9737, 18749]),
    ("出售使用权资产收益 Gain on disposal of ROU",                    [None, -1631, None, None, None, None, None, None, None]),
    ("出售无形资产项目亏损 Loss on disposal of intangibles",          [None, None, None, None, None, None, 199, None, 5]),
    ("出售衍生工具收益 Gain on disposal of derivative instruments",   [None, None, None, -3759, -7331, 634, None, None, None]),
    ("利息收入 Interest income",                                      [-136760, -205513, -216933, -147893, -330656, -623360, -991247, -866098, -579671]),
    ("贸易应收款项减值/(拨回) Impairment of trade receivables",       [4550, 1643, 5254, 2903, 11401, -3434, 4169, 2429, 4413]),
    ("存货减值 Impairment of inventories",                            [None, None, None, None, None, 16372, None, None, 82784]),
    ("预付款项等减值/(拨回) Impairment of financial assets in prep",  [-706, 5594, -9872, -960, -2654, -715, 2158, 2460, -2224]),
    ("出售附属公司收益 Gain on disposal of subsidiaries",             [None, None, -1580, -1621, None, None, None, None, None]),
    ("损益确认的递延收益 Deferred income recognised in P&L",          [-19566, -24184, -30299, -45597, -23785, -25799, -20505, -24314, -30367]),
    ("财务费用 Finance costs (add back)",                             [8381, 4113, 15525, 78963, 52945, 76028, 99735, 91469, 66899]),
    ("以股权结算的股份支付开支 Equity-settled SBC expenses",          [None, None, 156894, None, None, 101793, 25857, 5516, 76839]),
    ("外汇亏损/(收益) Foreign exchange loss/(gain)",                  [None, None, None, 241604, 115632, -386615, -46023, -75092, 147298]),
    ("经营资本变动前现金流 OP profit before working capital changes", [5456217, 5959337, 8079863, 9037702, 11553087, 12704328, 17399252, 17748276, 23923618]),
    # 营运资本变动
    ("存货增加 Increase in inventories",                              [-339659, -463514, 136590, -78113, -3776, -315514, -983357, -1921318, -916212]),
    ("贸易应收款项(增加)/减少 (Inc)/dec in trade receivables",         [-75717, -30185, -92480, -118753, -130113, 1123, -72603, -36780, -21192]),
    ("预付款项等(增加)/减少 (Inc)/dec in prepayments etc",            [-206885, -574071, 98485, 104157, 381622, -153, -177579, -530149, -164623]),
    ("FVTPL金融资产减少/(增加)(营运) Dec/(inc) in FVTPL (operating)", [16929, -187216, 213188, None, None, None, None, None, None]),
    ("贸易应付款项增加/(减少) Inc/(dec) in trade payables",           [-81398, 16285, -43055, 163003, 271333, 271936, 345029, -270701, 154836]),
    ("其他应付款项增加/(减少) Inc/(dec) in other payables",           [530575, 442995, 246501, 457073, 1063385, 1124862, 3178927, -152180, 2033975]),
    ("合约负债增加/(减少) Inc/(dec) in contract liabilities",         [141380, 417553, 81979, 170384, 103629, 326238, 907731, -19363, 629002]),
    ("质押存款(增加)/减少 (Inc)/dec in pledged deposits",             [38817, 43325, 5634, None, -3648, 589, 382, None, None]),
    ("受限资金增加 Increase in restricted cash",                      [None, None, None, None, None, None, None, -5000, -449]),
    ("衍生金融工具增加 Increase in derivative financial instruments", [None, None, None, 11090, None, None, None, None, None]),
    ("经营所得现金 Cash generated from operations",                   [5480259, 5624509, 8726705, 9746543, 13235519, 14113409, 20597782, 14812785, 25638955]),
    ("已付所得税 Income tax paid",                                    [-868741, -1175891, -1511211, -1386300, -2034681, -2308380, -3395627, -4041273, -4466550]),
    ("已收利息 Interest received",                                    [95438, 185287, 271870, 147893, 252269, 312530, 202485, 342220, 29967]),
    ("已付利息 Interest paid",                                        [-9556, -4179, -15525, -78963, -52837, -76049, -99703, -91588, -60720]),
    ("经营活动所得现金流量净额 Net cash from operating",              [4697400, 4629726, 7471839, 8429173, 11400270, 12041510, 17304937, 11022144, 21141652]),
    # 投资活动
    ("购买物业厂房设备项目 Purchases of PPE",                         [-2272876, -3336910, -3230597, -2236039, -2462418, -4193347, -4714113, -6405992, -6481304]),
    ("购买FVTPL金融资产 Purchases of FVTPL",                          [None, None, None, None, -200000, None, None, -15613000, -53758000]),
    ("销售FVTPL金融资产所得 Proceeds from sale of FVTPL",             [None, None, None, None, None, 207043, None, 14143952, 47903342]),
    ("结构性存款增加 Increase in structured deposits",                [-4240000, -6100000, -5700000, None, None, None, None, None, None]),
    ("结构性存款到期赎回 Redemption of structured deposits",          [3425000, 4535000, 9100000, 200000, None, None, None, None, None]),
    ("出售PPE所得款项 Proceeds from disposal of PPE",                 [31831, 43467, 375243, 74314, 11890, 79947, 26528, 40043, 27271]),
    ("购买无形资产 Purchases of intangibles",                         [-11070, -43881, -8628, -12030, -15199, -1720, -27776, -8633, -28353]),
    ("出售无形资产所得款项 Proceeds from disposal of intangibles",    [406, 523, 184, 1152, None, None, None, None, None]),
    ("购买使用权资产-土地 Purchases of land use rights",              [-88203, -70765, -73833, -31193, -10545, -156975, -120861, -46164, -286442]),
    ("出售使用权资产所得款项 Proceeds from disposal of ROU",          [6790, 3781, None, None, None, None, None, None, None]),
    ("收取政府补助 Receipt of government grants",                     [101890, 3945, 69460, 64781, 21063, 52669, 32146, 40657, 70285]),
    (">3月银行存款增加 Increase in bank deposits >3m",                [-2200000, -1000000, -3200000, -3090361, -13105840, -14683027, -26873541, -21493307, -8119152]),
    (">3月银行存款提取(含利息) Withdrawal of bank deposits >3m",     [600000, 2300000, 3300000, 300000, 10445298, 9269084, 17393803, 24840847, 9177938]),
    ("收购一家附属公司 Acquisition of a subsidiary",                  [None, -9234, None, None, None, None, None, None, None]),
    ("出售附属公司 Disposal of subsidiaries",                         [None, None, 11203, 72682, None, None, None, None, None]),
    ("投资活动所用现金流量净额 Net cash used in investing",            [-4646232, -3674074, 643032, -4656694, -5315751, -9426326, -14283814, -4501597, -11494415]),
    # 融资活动
    ("已付股息 Dividends paid",                                       [-367200, -367200, -9597600, -7979760, -1911899, -5059118, -7646313, -8434850, -8547314]),
    ("向非控股股东派付股息 Dividends to NCI",                         [None, None, -20000, None, None, None, None, None, None]),
    ("偿还计息借贷 Repayment of interest-bearing borrowings",         [-104500, -50000, None, -2850000, -2943957, -6563000, -13471835, -15739304, -16841182]),
    ("新计息借贷 New interest-bearing borrowings",                    [50000, None, 1000000, 4263957, 3030000, 6488006, 14167329, 16244237, 17605749]),
    ("发行H股所得款项 Proceeds from issuance of H shares",            [None, None, None, 8542860, None, None, None, None, None]),
    ("支付发行开支 Payment of issue expenses",                        [None, None, None, -228810, None, None, None, None, None]),
    ("租赁付款本金部分 Principal portion of lease payments",          [-22461, -44529, -49817, -32443, -67603, -81677, -80981, -135183, -130463]),
    ("一名股东注资 Capital injection by a shareholder",               [None, 100000, None, None, None, None, None, None, None]),
    ("视作向一名股东作出的分派 Deemed distribution to a shareholder", [None, -95000, None, None, None, None, None, None, None]),
    ("收购非控股权益 Acquisition of NCI",                             [None, None, -29385, None, None, None, None, None, None]),
    ("购回本公司股份 Repurchase of company shares",                   [None, None, None, None, None, -225401, None, None, -221552]),
    ("受限股份单位计划授股款项 Proceeds from award of restricted shares",[None, None, None, None, None, None, None, None, 76475]),
    ("出售没收受限制股份 Proceeds from disposal of forfeited shares", [None, None, None, None, None, None, 9746, 3324, None]),
    ("员工股权激励计划授股款项 Proceeds from employee incentive scheme",[None, None, None, None, None, 71408, None, None, None]),
    ("融资活动所得/(所用)现金流量净额 Net cash from/(used in) financing",[-444161, -456729, -8696802, 1715804, -1893459, -5369782, -7022054, -8061776, -8058287]),
    # 汇总
    ("现金及现金等价物增加/(减少)净额 Net inc/(dec) in cash",          [-392993, 498923, -581931, 5488283, 4191060, -2754598, -4000931, -1541229, 1588950]),
    ("年初现金及现金等价物 Cash at beginning of year",                [1256547, 862883, 1363664, 783142, 6055981, 10187896, 7821114, 3875720, 2416380]),
    ("外汇汇率变动的影响 Effect of foreign exchange rate changes",    [-671, 1858, 1409, -215444, -59145, 387816, 55537, 81889, -147581]),
    ("年末现金及现金等价物 Cash at end of year",                      [862883, 1363664, 783142, 6055981, 10187896, 7821114, 3875720, 2416380, 3857749]),
]


# ====== PPE 明细 (来源: 招股书附注14 I-63~I-65 / 年报附注14, 单位: 人民币千元, 期末账面净值) ======
PPE明细 = [
    ("楼宇 Buildings",                            [2580260, 2888515, 3122393, 3390528, 3418932, 3504416, 4206780, 4322939, 6189293]),
    ("机器 Machinery",                            [4614975, 5475336, 6380578, 6279031, 6535860, 7636991, 8692380, 10365932, 12386946]),
    ("傢俬装置及设备 Furniture/fixtures/equipment",[544836, 1256782, 1378957, 1543005, 1546253, 2375253, 2417634, 2701958, 2945599]),
    ("汽车 Motor vehicles",                       [71821, 92948, 88837, 82915, 87401, 117001, 159941, 211943, 210390]),
    ("租赁物业装修 Leasehold improvements",        [131401, 127885, 108242, 68100, 17562, 25909, 3422, 14304, 17041]),
    ("永久业权土地 Freehold land",                 [None, None, None, None, None, None, None, None, 70288]),
    ("在建工程 Construction in progress (CIP)",   [987439, 1247215, 1235339, 1228006, 1194132, 1738015, 1699471, 3466163, 2899779]),
    ("PPE 合计 Total PPE",                        [8930732, 11088681, 12314346, 12591585, 12800140, 15397585, 17179628, 21083239, 24719336]),
]


# ====== 分部营收 (来源: 招股书概要/业务 + 年报 MD&A 业务回顾, 单位: 人民币百万元) ======
分部营收 = [
    ("包装饮用水产品 Packaged drinking water",   [10120, 11780, 14346, 13966, 17058, 18263, 20262, 15952, 18709]),
    ("茶饮料产品 Tea beverage",                 [2597,  3036,  3138,  3088,  4579,  6906,  12659, 16745, 21596]),
    ("功能饮料产品 Functional beverage",         [2936,  3322,  3779,  2792,  3695,  3838,  4902,  4932,  5762]),
    ("果汁饮料产品 Juice beverage",              [1468,  1855,  2311,  1977,  2614,  2879,  3533,  4085,  5176]),
    ("其他产品(苏打/咖啡/植物蛋白/鲜果等) Other",[370,   482,   447,   1054,  1750,  1353,  1311,  1182,  1309]),
    ("分部合计 Total",                            [17491, 20475, 24021, 22877, 29696, 33239, 42667, 42896, 52553]),
]


# ====== 工具函数 ======
def find(table, name):
    """从表里取一行(整个 9 年数组)"""
    for k, v in table:
        if k.startswith(name):
            return v
    raise KeyError(name)


def z(x):
    """None 视作 0(用于含非控股权益的等式校验)"""
    return 0 if x is None else x


def safe_div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


# ====== 勾稽自洽校验 ======
def verify():
    errors = []
    for i, y in enumerate(YEARS):
        # 损益: 收益 - 销售成本 = 毛利
        rev = find(利润表, "收益 Revenue")[i]
        cos = find(利润表, "销售成本")[i]
        gp = find(利润表, "毛利")[i]
        if rev + cos != gp:
            errors.append(f"{y} 损益: 收益{rev} + 成本{cos} ≠ 毛利{gp} (差 {rev+cos-gp})")
        # 损益: 除税前 + 所得税 = 年内溢利
        pbt = find(利润表, "除税前溢利")[i]
        tax = find(利润表, "所得税开支")[i]
        npr = find(利润表, "年内溢利")[i]
        if pbt + tax != npr:
            errors.append(f"{y} 损益: 除税前{pbt} + 所得税{tax} ≠ 年内溢利{npr} (差 {pbt+tax-npr})")
        # 损益: 母公司应占 + 非控股应占 = 年内溢利
        parent = find(利润表, "母公司拥有人应占溢利")[i]
        nci_pl = find(利润表, "非控股权益应占溢利")[i]
        if parent + z(nci_pl) != npr:
            errors.append(f"{y} 损益: 母公司应占{parent} + 非控股{z(nci_pl)} ≠ 年内溢利{npr}")
        # 损益: 年内溢利 + OCI = 全面收益总额
        oci = find(利润表, "其他全面")[i]
        tci = find(利润表, "年内全面收益总额")[i]
        if npr + oci != tci:
            errors.append(f"{y} 损益: 年内溢利{npr} + OCI{oci} ≠ 全面收益{tci}")

        # 资产负债: 流动资产 - 流动负债 = 流动净额
        tnca = find(资产负债表, "非流动资产总额")[i]
        tca = find(资产负债表, "流动资产总额")[i]
        tcl = find(资产负债表, "流动负债总额")[i]
        tncl = find(资产负债表, "非流动负债总额")[i]
        na = find(资产负债表, "资产净额")[i]
        ncanet = find(资产负债表, "流动资产/(负债)净额")[i]
        if tca - tcl != ncanet:
            errors.append(f"{y} 资产负债: 流动资产{tca} - 流动负债{tcl} ≠ 流动净额{ncanet}")
        if tnca + ncanet - tncl != na:
            errors.append(f"{y} 资产负债: 非流动资产{tnca} + 流动净额{ncanet} - 非流动负债{tncl} ≠ 资产净额{na}")
        # 总资产 = 总负债 + 权益
        total_assets = tnca + tca
        total_liab = tcl + tncl
        eq = find(资产负债表, "权益总额")[i]
        if total_assets != total_liab + eq:
            errors.append(f"{y} 资产负债: 总资产{total_assets} ≠ 总负债{total_liab} + 权益{eq}")
        # 股本 + 储备 = 母公司应占权益; 母公司应占 + 非控股 = 权益总额
        sc = find(资产负债表, "股本")[i]
        res = find(资产负债表, "储备")[i]
        parent_eq = find(资产负债表, "母公司拥有人应占权益")[i]
        nci_eq = find(资产负债表, "非控股权益")[i]
        if sc + res != parent_eq:
            errors.append(f"{y} 资产负债: 股本{sc} + 储备{res} ≠ 母公司应占权益{parent_eq}")
        if parent_eq + z(nci_eq) != eq:
            errors.append(f"{y} 资产负债: 母公司应占{parent_eq} + 非控股{z(nci_eq)} ≠ 权益总额{eq}")

        # 现金流: 经营净额 = 经营所得现金 + 已付税 + 已收利息 + 已付利息
        cfo_gen = find(现金流量表, "经营所得现金")[i]
        tax_paid = find(现金流量表, "已付所得税")[i]
        int_recv = find(现金流量表, "已收利息")[i]
        int_paid = find(现金流量表, "已付利息")[i]
        ocf = find(现金流量表, "经营活动所得现金流量净额")[i]
        if cfo_gen + tax_paid + int_recv + int_paid != ocf:
            errors.append(f"{y} 现金流: 经营所得现金{cfo_gen} +税{tax_paid} +收息{int_recv} +付息{int_paid} ≠ 经营净额{ocf}")
        # 现金流: 经营 + 投资 + 融资 = 净变动
        icf = find(现金流量表, "投资活动所用现金流量净额")[i]
        fcf = find(现金流量表, "融资活动所得/(所用)现金流量净额")[i]
        netchg = find(现金流量表, "现金及现金等价物增加/(减少)净额")[i]
        if ocf + icf + fcf != netchg:
            errors.append(f"{y} 现金流: 经营{ocf} + 投资{icf} + 融资{fcf} ≠ 净变动{netchg}")
        # 现金流: 年初 + 净变动 + 汇兑 = 年末
        beg = find(现金流量表, "年初现金及现金等价物")[i]
        fx = find(现金流量表, "外汇汇率变动的影响")[i]
        end = find(现金流量表, "年末现金及现金等价物")[i]
        if beg + netchg + fx != end:
            errors.append(f"{y} 现金流: 年初{beg} + 净变{netchg} + 汇兑{fx} ≠ 年末{end}")

    # 年初年末连续性(含跨招股书→年报边界 2019年末=2020年初)
    end_arr = find(现金流量表, "年末现金及现金等价物")
    beg_arr = find(现金流量表, "年初现金及现金等价物")
    for i in range(1, N):
        if end_arr[i-1] != beg_arr[i]:
            errors.append(f"{YEARS[i]} 现金连续性: 上年末{end_arr[i-1]} ≠ 本年初{beg_arr[i]}")

    # 分部合计 ≈ 损益表营收 (百万取整, 容差 ±1 百万)
    rev_thousand = find(利润表, "收益 Revenue")
    for i, y in enumerate(YEARS):
        seg_total = find(分部营收, "分部合计")[i]
        rev_million = round(rev_thousand[i] / 1000)
        if abs(seg_total - rev_million) > 1:
            errors.append(f"{y} 分部合计{seg_total}百万 ≠ 损益表营收{rev_million}百万 (差 {seg_total-rev_million})")
        five = sum(find(分部营收, k)[i] for k in ["包装饮用水", "茶饮料", "功能饮料", "果汁饮料", "其他产品"])
        if abs(five - seg_total) > 1:
            errors.append(f"{y} 5 品类合计{five} ≠ 分部合计{seg_total}")

    # PPE 明细子科目相加 = PPE 合计 = 资产负债表「物业、厂房及设备」
    ppe_keys = ["楼宇", "机器", "傢俬", "汽车", "租赁", "永久业权", "在建工程"]
    for i, y in enumerate(YEARS):
        ppe_sum = sum((find(PPE明细, k)[i] or 0) for k in ppe_keys)
        ppe_total = find(PPE明细, "PPE 合计")[i]
        bs_ppe = find(资产负债表, "物业、厂房及设备")[i]
        if ppe_sum != ppe_total:
            errors.append(f"{y} PPE子科目合计{ppe_sum} ≠ PPE合计{ppe_total}")
        if ppe_total != bs_ppe:
            errors.append(f"{y} PPE明细合计{ppe_total} ≠ 资产负债表PPE{bs_ppe}")

    return errors


# ====== 派生比率 ======
def build_ratios():
    rev = find(利润表, "收益 Revenue")
    gp = find(利润表, "毛利")
    snd = find(利润表, "销售及分销开支")
    adm = find(利润表, "行政开支")
    npr = find(利润表, "年内溢利")
    eq = find(资产负债表, "权益总额")
    ar = find(资产负债表, "贸易应收款项及应收票据")
    inv = find(资产负债表, "存货")
    ocf = find(现金流量表, "经营活动所得现金流量净额")
    capex = find(现金流量表, "购买物业厂房设备项目")  # 负数, 取绝对值算比率

    rows = [
        ("毛利率 Gross margin",                              [safe_div(gp[i], rev[i]) for i in range(N)]),
        ("净利率 Net margin",                                [safe_div(npr[i], rev[i]) for i in range(N)]),
        ("销售费用率 S&D expense ratio",                     [safe_div(-snd[i], rev[i]) for i in range(N)]),
        ("行政费用率 Admin expense ratio",                   [safe_div(-adm[i], rev[i]) for i in range(N)]),
        ("ROE(期末) Return on year-end equity",              [safe_div(npr[i], eq[i]) for i in range(N)]),
        ("ROE(年均) Return on avg equity",                   [None] + [safe_div(npr[i], (eq[i]+eq[i-1])/2) for i in range(1, N)]),
        ("经营现金流/净利 OCF/Net profit",                   [safe_div(ocf[i], npr[i]) for i in range(N)]),
        ("Capex/净利 Capex/Net profit",                      [safe_div(-capex[i], npr[i]) for i in range(N)]),
        ("应收/营收 AR/Revenue",                             [safe_div(ar[i], rev[i]) for i in range(N)]),
        ("存货/营收 Inventory/Revenue",                      [safe_div(inv[i], rev[i]) for i in range(N)]),
        ("资产负债率 Liabilities/Total assets",              [safe_div(
            find(资产负债表, "流动负债总额")[i] + find(资产负债表, "非流动负债总额")[i],
            find(资产负债表, "非流动资产总额")[i] + find(资产负债表, "流动资产总额")[i]
        ) for i in range(N)]),
    ]
    return rows


# ====== 写 CSV ======
def write_csv(filename, rows, unit_note=""):
    path = os.path.join(OUT, filename)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if unit_note:
            w.writerow([f"# {unit_note}"])
        w.writerow(["科目"] + [str(y) for y in YEARS])
        for name, vals in rows:
            row = [name]
            for v in vals:
                if v is None:
                    row.append("")
                elif isinstance(v, float):
                    if abs(v) < 1:
                        row.append(f"{v:.4f}")
                    else:
                        row.append(f"{v:.3f}")
                else:
                    row.append(v)
            w.writerow(row)
    print(f"  ✅ {filename}")


# ====== main ======
if __name__ == "__main__":
    print("校验勾稽...")
    errs = verify()
    if errs:
        print(f"❌ 校验失败 ({len(errs)} 条), 不写出 CSV:")
        for e in errs:
            print(f"   {e}")
        raise SystemExit(1)
    print(f"✅ 三表勾稽全平 (9 年 × 多项校验, 含 NCI 分层 + 现金跨年连续性 + 招股书↔年报边界衔接)\n")

    print("写出 CSV:")
    write_csv("利润表.csv", 利润表, "单位: 人民币千元 (RMB'000), 来源: 招股书会计师报告(2017-2019)+一手年报(2020-2025)")
    write_csv("资产负债表.csv", 资产负债表, "单位: 人民币千元 (RMB'000), 资产负债权益全部正数, 来源: 招股书(2017-2019)+年报(2020-2025)")
    write_csv("现金流量表.csv", 现金流量表, "单位: 人民币千元 (RMB'000), 流出/减项=负数, 来源: 招股书(2017-2019)+年报(2020-2025)")
    write_csv("财务比率.csv", build_ratios(), "派生比率: 从一手三表计算, EPS/比率为小数")
    write_csv("分部营收.csv", 分部营收, "单位: 人民币百万元 (RMB million), 来源: 招股书概要(2017-2019)+年报 MD&A(2020-2025)")
    write_csv("PPE明细.csv", PPE明细, "单位: 人民币千元 (RMB'000), 期末账面净值, 来源: 招股书附注14(2017-2019)+年报附注14(2020-2025)")
    print("\n🎊 全部写出完成 (2017-2025 全 9 年)")
