#!/usr/bin/env python3
"""Build google 2026 interim CSVs (Q2/H1 + Q3/9M) from the one-hand SEC 10-Qs.

真源(两份 10-Q;每份的对比列取自同一份申报,故每个同比两端同源):
  Q2 申报: report/google/2026-Q2.htm — 10-Q, quarter ended 2026-06-30 (accession 0001652044-26-000071, filed 2026-07-23)
  Q3 申报: report/google/2026-Q3.htm — 10-Q, quarter ended 2026-09-30 (accession 0001652044-26-000084, filed 2026-10-29)
另引: 2026Q1 10-Q(单季现金流推算)、FY2025 10-K(2025-12-31 表外与租赁)、2025 年三份 10-Q(单季序列与 2025-09-30 应收)、
      Q3 业绩 8-K(单季现金流抽查);年度值经 现金流量表.csv / 分部营收.csv 链式读取(读不到即失败)。

设计原则(同 _build_from_xbrl.py):
  1. 中期数据**不并入年度序列** —— 年度 CSV 覆盖 1999-2025,本脚本只写中期专属文件,避免年化/口径污染。
  2. 勾稽全部通过才写出 CSV;任一条不过 → 抛异常、不落盘。**默认容差 0**,只有两类显式放宽并写明原因:
     (a) 跨申报的期间相加(9M = H1 + Q3 等):三列各自独立四舍五入到百万 → 容差 1;
     (b) 申报正文舍入到 0.1B 的金额与表格精确值互核 → 容差 = 舍入半宽 × 项数。
  3. 派生指标一律从本文件数据计算(不手抄常数),算法写在 CSV「算法」列。
  4. `--mutate`:把每个转录格 ±1(每股收益 ±0.01)后重跑全部勾稽,报告被拦下的比例与漏网清单(检验勾稽本身的覆盖面)。

单位: 百万美元 (USD millions),除标注外。费用/流出 = 负数。
"""
from __future__ import annotations

import contextlib
import csv
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_Q2 = "report/google/2026-Q2.htm (10-Q · accession 0001652044-26-000071 · filed 2026-07-23)"
SRC_Q3 = "report/google/2026-Q3.htm (10-Q · accession 0001652044-26-000084 · filed 2026-10-29)"

P_Q2 = ("Q2 2025", "Q2 2026", "H1 2025", "H1 2026")
P_Q3 = ("Q3 2025", "Q3 2026", "9M 2025", "9M 2026")
D_Q2 = ("2025-12-31", "2026-06-30")
D_Q3 = ("2025-12-31", "2026-09-30")

# ---------------------------------------------------------------------------
# 一手申报数值(逐行转录)。*_Q2 键: (Q2'25, Q2'26, H1'25, H1'26);*_Q3 键: (Q3'25, Q3'26, 9M'25, 9M'26)
# ---------------------------------------------------------------------------

REV, COR, RD, SM, GA, TCE = ("收益 Revenues", "营业成本 Cost of revenues", "研发费用 Research and development",
                             "销售与市场 Sales and marketing", "一般及行政 General and administrative",
                             "总成本及开支 Total costs and expenses")
OI, OIE_L, PRETAX, TAX, NI, PREF, NIC = ("经营利润 Income from operations", "其他收入(支出)净额 OI&E",
                                         "除税前利润 Income before income taxes", "所得税 Provision for income taxes",
                                         "净利润 Net income", "优先股股息 Preferred stock dividends",
                                         "归属普通股净利 NI available to common")

INCOME_Q2 = {
    REV: (96428, 119796, 186662, 229692),
    COR: (-39039, -45943, -75400, -87214),
    RD: (-13808, -18219, -27364, -35251),
    SM: (-7101, -8403, -13273, -16009),
    GA: (-5209, -6461, -8748, -10752),
    TCE: (-65157, -79026, -124785, -149226),
    OI: (31271, 40770, 61877, 80466),
    OIE_L: (2662, 97983, 13845, 135699),
    PRETAX: (33933, 138753, 75722, 216165),
    TAX: (-5737, -26560, -12986, -41394),
    NI: (28196, 112193, 62736, 174771),
    PREF: (0, -86, 0, -86),
    NIC: (28196, 112107, 62736, 174685),
}
INCOME_Q3 = {
    REV: (102346, 127577, 289007, 357269),
    COR: (-41369, -51419, -116768, -138633),
    RD: (-15151, -20640, -42515, -55891),
    SM: (-7205, -8804, -20478, -24813),
    GA: (-7393, -6138, -16141, -16890),
    TCE: (-71118, -87001, -195902, -236227),
    OI: (31228, 40576, 93105, 121042),
    OIE_L: (12759, -8221, 26604, 127478),
    PRETAX: (43987, 32355, 119709, 248520),
    TAX: (-9008, -5887, -21994, -47281),
    NI: (34979, 26468, 97715, 201239),
    PREF: (0, -298, 0, -384),
    NIC: (34979, 26170, 97715, 200855),
}

# 每股收益与股数(Note 12)。稀释分子 = 归普净利 + 优先股股息加回(假设转换法,仅在有稀释作用时加回)
EPS_B, EPS_D, SH_B, SH_D, ADDBACK, DNUM = ("基本每股收益 Basic EPS (USD)", "稀释每股收益 Diluted EPS (USD)",
                                           "基本股数(百万) Basic shares", "稀释股数(百万) Diluted shares",
                                           "稀释分子·优先股股息加回 if-converted add-back",
                                           "稀释分子 Diluted numerator")
EPS_Q2 = {
    EPS_B: (2.33, 9.23, 5.16, 14.41),
    EPS_D: (2.31, 9.11, 5.12, 14.24),
    SH_B: (12122, 12151, 12153, 12125),
    SH_D: (12198, 12309, 12245, 12274),
    ADDBACK: (0, 86, 0, 86),          # Q2'26 与 H1'26 优先股有稀释作用(转换股 16 / 8 百万股计入稀释股数)
    DNUM: (28196, 112193, 62736, 174771),
}
EPS_Q3 = {
    EPS_B: (2.89, 2.14, 8.06, 16.51),
    EPS_D: (2.87, 2.12, 7.99, 16.33),
    SH_B: (12086, 12256, 12130, 12169),
    SH_D: (12203, 12368, 12230, 12324),
    ADDBACK: (0, 0, 0, 384),          # Q3'26 反稀释(不加回、转换股 0);9M'26 有稀释作用(加回 384、转换股 24 百万股)
    DNUM: (34979, 26170, 97715, 201239),
}

OIE_ROWS = ("利息收入 Interest income", "利息支出 Interest expense (净资本化后)", "外汇损益 FX gain(loss) net",
            "债务证券损益 Gain(loss) on debt securities", "股权证券损益 Gain(loss) on equity securities",
            "权益法投资损益 Equity method net", "其他 Other")
OIE_TOTAL = "=OI&E 合计"
OIE_EQ = OIE_ROWS[4]
OIE_Q2 = dict(zip(OIE_ROWS + (OIE_TOTAL,), (
    (1050, 1430, 2051, 2811), (-261, -1278, -295, -1811), (-69, -160, -175, -14), (165, -32, 367, -143),
    (1286, 99031, 11044, 135946), (419, -35, 397, 25), (72, -973, 456, -1115), (2662, 97983, 13845, 135699))))
OIE_Q3 = dict(zip(OIE_ROWS + (OIE_TOTAL,), (
    (1076, 1768, 3128, 4579), (-143, -967, -438, -2778), (-143, 22, -318, 7), (122, -383, 489, -526),
    (10734, -8664, 21778, 127282), (-30, -143, 367, -118), (1143, 146, 1598, -968), (12759, -8221, 26604, 127478))))

# 股权证券损益拆分(Note 3「Gains and Losses on Equity Securities」原表)
EG_GAIN, EG_LOSS, EG_NM, EG_MKT, EG_REAL, EG_TOT = (
    "非上市(计量替代法)未实现收益·毛额 Gross unrealized gain",
    "非上市(计量替代法)未实现损失(含减值) Gross unrealized loss",
    "=非上市(计量替代法)未实现净收益 Unrealized net, non-marketable",
    "上市及其他股权未实现净收益 Unrealized net, marketable and other",
    "已出售股权的已实现净收益 Realized net",
    "=股权证券损益合计 Total gain(loss) on equity securities")
EQUITY_GAINS_Q2 = {EG_GAIN: (670, 77544, 10374, 114161), EG_LOSS: (-454, -190, -853, -582),
                   EG_NM: (216, 77354, 9521, 113579), EG_MKT: (853, 21399, 1088, 21531),
                   EG_REAL: (217, 278, 435, 836), EG_TOT: (1286, 99031, 11044, 135946)}
EQUITY_GAINS_Q3 = {EG_GAIN: (10583, 3386, 20924, 117203), EG_LOSS: (-346, -359, -1188, -887),
                   EG_NM: (10237, 3027, 19736, 116316), EG_MKT: (447, -12436, 1447, 9377),
                   EG_REAL: (50, 745, 595, 1589), EG_TOT: (10734, -8664, 21778, 127282)}

# 计量替代法非上市股权账面构成(Note 3);附注原文:期末主要为「一家私营公司」的投资
NM_COST, NM_UP, NM_DOWN, NM_CARRY, NM_EQM, NM_TOT = (
    "初始成本 Total initial cost", "累计向上调整 Cumulative upward adjustments",
    "累计向下调整(含减值) Cumulative downward adjustments",
    "=计量替代法账面价值 Carrying value (measurement alternative)",
    "权益法投资及其他 Equity method investments and other", "=非上市证券合计 Total non-marketable securities")
NONMKT_Q2 = {NM_COST: (28429, 47642), NM_UP: (44485, 85732), NM_DOWN: (-8820, -9115),
             NM_CARRY: (64094, 124259), NM_EQM: (4593, 7202), NM_TOT: (68687, 131461)}
NONMKT_Q3 = {NM_COST: (28429, 48595), NM_UP: (44485, 88784), NM_DOWN: (-8820, -9210),
             NM_CARRY: (64094, 128169), NM_EQM: (4593, 7061), NM_TOT: (68687, 135230)}

# 上市股权证券(Note 3 公允价值表:Level 1 + Level 2);剔除它才得「可动用净现金」
MK_L1, MK_L2, MK_TOT = ("上市股权证券·Level 1", "上市股权证券·Level 2", "=上市股权证券(计入有价证券)")
MKT_EQUITY = {  # 键: (2025-12-31, 2026-06-30, 2026-09-30)
    MK_L1: (4402, 86049, 89919),
    MK_L2: (1911, 1014, 465),
    MK_TOT: (6313, 87063, 90384),
}

BS_ROWS = ("现金及现金等价物 Cash and equivalents", "有价证券 Marketable securities", "=现金+等价物+有价证券",
           "应收账款净额 Accounts receivable net", "存货 Inventory", "其他流动资产 Other current assets",
           "流动资产合计 Total current assets", "非上市证券 Non-marketable securities",
           "递延所得税资产 Deferred income taxes", "固定资产净额 Property and equipment net",
           "经营租赁资产 Operating lease assets", "商誉 Goodwill", "无形资产净额 Intangible assets net",
           "其他非流动资产 Other non-current assets", "资产总计 Total assets", "应付账款 Accounts payable",
           "应付薪酬 Accrued compensation and benefits", "应付费用及其他流动负债 Accrued expenses and other",
           "应付分成 Accrued revenue share", "递延收入(流动) Deferred revenue", "流动负债合计 Total current liabilities",
           "长期债务 Long-term debt", "非流动应付税 Income taxes payable non-current",
           "递延所得税负债 Deferred income taxes", "经营租赁负债 Operating lease liabilities",
           "其他长期负债 Other long-term liabilities", "负债合计 Total liabilities",
           "优先股及资本公积 Preferred stock and APIC", "普通股及资本公积 Common stock and APIC",
           "累计其他综合收益 AOCI", "留存收益 Retained earnings", "股东权益合计 Total stockholders' equity",
           "负债及权益合计")
(B_CASH, B_MKT, B_CMS, B_AR, B_INV, B_OCA, B_TCA, B_NMS, B_DTA, B_PPE, B_OLA, B_GW, B_INT, B_ONCA, B_TA,
 B_AP, B_ACC, B_AEX, B_ARS, B_DR, B_TCL, B_LTD, B_ITP, B_DTL, B_OLL, B_OLTL, B_TL, B_PREF, B_COM, B_AOCI,
 B_RE, B_TE, B_TLE) = BS_ROWS
BALANCE_Q2 = dict(zip(BS_ROWS, (
    (30708, 55911), (96135, 186563), (126843, 242474), (62886, 69175), (2439, 9991), (13870, 21884),
    (206038, 343524), (68687, 131461), (9113, 1448), (246597, 321212), (15221, 17694), (33380, 57828),
    (1283, 9105), (14962, 39711), (595281, 921983), (12200, 20258), (17546, 15086), (55557, 73014),
    (10864, 10599), (6578, 7154), (102745, 126111), (46547, 98165), (9531, 11306), (919, 22819),
    (12744, 14591), (7530, 8511), (180016, 281503), (0, 18023), (93126, 131371), (-1916, -2285),
    (324055, 493371), (415265, 640480), (595281, 921983))))
BALANCE_Q3 = dict(zip(BS_ROWS, (
    (30708, 56334), (96135, 208764), (126843, 265098), (62886, 72784), (2439, 13308), (13870, 23475),
    (206038, 374665), (68687, 135230), (9113, 1458), (246597, 372827), (15221, 20273), (33380, 58117),
    (1283, 8817), (14962, 31925), (595281, 1003312), (12200, 21975), (17546, 17729), (55557, 74317),
    (10864, 11051), (6578, 9429), (102745, 134501), (46547, 125102), (9531, 12219), (919, 27833),
    (12744, 16815), (7530, 9293), (180016, 325763), (0, 18023), (93126, 147068), (-1916, -4326),
    (324055, 516784), (415265, 677549), (595281, 1003312))))

CF_ROWS = ("净利润 Net income", "折旧 Depreciation of property and equipment", "股权薪酬 Stock-based compensation",
           "递延所得税 Deferred income taxes", "债务及股权证券损益冲回 Loss(gain) on securities", "其他调整 Other",
           "应收账款变动 Accounts receivable", "存货变动 Inventory", "所得税净变动 Income taxes net",
           "其他资产变动 Other assets", "应付账款变动 Accounts payable", "应付费用及其他变动 Accrued expenses and other",
           "递延收入变动 Deferred revenue", "经营活动现金流净额 Net cash from operating",
           "资本开支 Purchases of property and equipment", "购买有价证券 Purchases of marketable securities",
           "有价证券到期及出售 Maturities and sales of marketable",
           "购买非上市证券 Purchases of non-marketable securities",
           "非上市证券到期及出售 Maturities and sales of non-marketable",
           "收购净支出及无形资产 Acquisitions net of cash", "其他投资活动 Other investing",
           "投资活动现金流净额 Net cash used in investing",
           "股权激励相关净支付 Net payments re stock-based awards", "股份回购 Repurchases of stock",
           "股息支付 Dividend payments", "发行普通股净额 Proceeds from issuance of common stock",
           "发行强制可转优先股净额 Proceeds from preferred", "发债净额 Proceeds from issuance of debt",
           "偿债 Repayments of debt", "出售合并主体权益净额 Sale of interest in consolidated",
           "其他融资活动 Other financing", "融资活动现金流净额 Net cash from(used in) financing",
           "汇率影响 Effect of exchange rate changes", "现金净变动 Net increase(decrease) in cash",
           "期初现金 Cash at beginning of period", "期末现金 Cash at end of period",
           "补充:计入应付/预提的物业设备 PP&E in AP & accrued(期末)")
C_NI, C_DEP, C_SBC = CF_ROWS[0], CF_ROWS[1], CF_ROWS[2]
C_OCF, C_CAPEX, C_INV = CF_ROWS[13], CF_ROWS[14], CF_ROWS[21]
C_REP, C_DIV, C_COMMON, C_PREFI = CF_ROWS[23], CF_ROWS[24], CF_ROWS[25], CF_ROWS[26]
C_FIN, C_FX, C_NET, C_BEG, C_END, C_UNPAID = CF_ROWS[31], CF_ROWS[32], CF_ROWS[33], CF_ROWS[34], CF_ROWS[35], CF_ROWS[36]
CASHFLOW_Q2 = dict(zip(CF_ROWS, (  # 键: (H1'25, H1'26)
    (62736, 174771), (9485, 13586), (11514, 14708), (-1596, 27538), (-11411, -135803), (1041, 3161),
    (-1201, -6904), (-628, -7739), (-2434, 8304), (-2139, -9950), (-327, 2090), (-1779, 308), (636, 789),
    (63897, 84859), (-39643, -80598), (-39870, -76480), (40930, 66696), (-2312, -22051), (873, 1667),
    (-353, -33697), (-363, -1359), (-40738, -145822), (-5731, -12056), (-28306, 0), (-4977, -5231), (0, 30499),
    (0, 19063), (31378, 56226), (-18397, -5253), (400, 3758), (-400, -686), (-26033, 86320), (444, -154),
    (-2430, 25203), (23466, 30708), (21036, 55911), (10635, 29113))))
CASHFLOW_Q3 = dict(zip(CF_ROWS, (  # 键: (9M'25, 9M'26)
    (97715, 201239), (15096, 21955), (17882, 23338), (7130, 33077), (-22266, -126755), (843, 4825),
    (-3582, -10821), (-1154, -10959), (-3292, 4602), (-2906, -17757), (-771, 1925), (6299, -860), (1317, 3340),
    (112311, 127149), (-63596, -131953), (-60834, -116467), (61301, 88516), (-3312, -24160), (1196, 1875),
    (-1425, -34103), (-1845, -879), (-68515, -217171), (-9001, -17424), (-39810, 0), (-7513, -8167), (0, 42870),
    (0, 19063), (38002, 85222), (-26094, -8879), (400, 3758), (-400, -686), (-44416, 115757), (244, -109),
    (-376, 25626), (23466, 30708), (23090, 56334), (14574, 35921))))

SEG_ROWS = ("Google搜索及其他 Search & other", "YouTube广告 YouTube ads", "Google联盟网络 Network",
            "=广告合计 Google advertising", "订阅/平台/设备 Subscriptions,platforms,devices", "=Google Services合计",
            "Google Cloud 云", "Other Bets 其他押注", "对冲损益 Hedging gains(losses)", "=总收入 Total revenues")
S_SEARCH, S_YT, S_NET, S_ADS, S_SUBS, S_SERV, S_CLOUD, S_OB, S_HEDGE, S_TOT = SEG_ROWS
SEGMENTS_Q2 = dict(zip(SEG_ROWS, (
    (54190, 63271, 104892, 123670), (9796, 11055, 18723, 20938), (7354, 7303, 14610, 14274),
    (71340, 81629, 138225, 158882), (11203, 12911, 21582, 25295), (82543, 94540, 159807, 184177),
    (13624, 24768, 25884, 44796), (373, 382, 823, 793), (-112, 106, 148, -74), (96428, 119796, 186662, 229692))))
SEGMENTS_Q3 = dict(zip(SEG_ROWS, (
    (56567, 63350, 161459, 187020), (10261, 11207, 28984, 32145), (7354, 7455, 21964, 21729),
    (74182, 82012, 212407, 240894), (12870, 14290, 34452, 39585), (87052, 96302, 246859, 280479),
    (15157, 30709, 41041, 75505), (344, 372, 1167, 1165), (-207, 194, -60, 120), (102346, 127577, 289007, 357269))))

SOI_ROWS = ("Google Services 经营利润", "Google Cloud 经营利润", "Other Bets 经营利润",
            "公司层未分配 Alphabet-level activities", "=总经营利润 Total income from operations")
O_SERV, O_CLOUD, O_OB, O_ALPHA, O_TOT = SOI_ROWS
SEGMENT_OI_Q2 = dict(zip(SOI_ROWS, ((33063, 39544, 65745, 80133), (2826, 8814, 5003, 15412),
                                    (-1246, -1799, -2472, -3899), (-3372, -5789, -6399, -11180),
                                    (31271, 40770, 61877, 80466))))
SEGMENT_OI_Q3 = dict(zip(SOI_ROWS, ((33527, 39157, 99272, 119290), (3594, 11121, 8597, 26533),
                                    (-1426, -2047, -3898, -5946), (-4467, -7655, -10866, -18835),
                                    (31228, 40576, 93105, 121042))))
# 分部费用补充披露(Q3 申报 Note 15;Q2 申报未转录)
SC_ROWS = ("Services·员工薪酬 employee compensation", "Services·其他成本及费用 other costs and expenses",
           "=Services 成本及费用合计", "Cloud·员工薪酬 employee compensation",
           "Cloud·其他成本及费用(含 TPU 存货及相关成本) other costs and expenses", "=Cloud 成本及费用合计")
SEGMENT_COSTS_Q3 = dict(zip(SC_ROWS, ((11070, 12280, 33713, 36761), (42455, 44865, 113874, 124428),
                                      (53525, 57145, 147587, 161189), (5586, 7081, 16515, 20457),
                                      (5977, 12507, 15929, 28515), (11563, 19588, 32444, 48972))))

GEO_ROWS = ("美国 United States", "欧洲中东非洲 EMEA", "亚太 APAC", "其他美洲 Other Americas",
            "对冲损益 Hedging", "=总收入 Total revenues")
GEOGRAPHY_Q2 = dict(zip(GEO_ROWS, ((46063, 60846, 90027, 114821), (28262, 32501, 54185, 63969),
                                   (16480, 19317, 31334, 37605), (5735, 7026, 10968, 13371),
                                   (-112, 106, 148, -74), (96428, 119796, 186662, 229692))))
GEOGRAPHY_Q3 = dict(zip(GEO_ROWS, ((48758, 67681, 138785, 182502), (29911, 32695, 84096, 96664),
                                   (17819, 19906, 49153, 57511), (6065, 7101, 17033, 20472),
                                   (-207, 194, -60, 120), (102346, 127577, 289007, 357269))))

# 长期债务(Q3 申报 Note 6 原表)—— 键: (2025-12-31, 2026-09-30)
DEBT_ROWS = ("2016 美元票据(2026 到期)", "2020 美元票据", "2025 美元票据", "2025 欧元票据", "2026 美元票据",
             "2026 英镑票据", "2026 瑞郎票据", "2026 欧元票据", "2026 加元票据", "2026 日元票据",
             "2026 澳元票据(Q3 新发·固定 A$3.3B + 浮动 A$2.3B)", "其他长期债务 Other long-term debt",
             "=面值合计 Total face value", "未摊销折价及发行费用", "公允价值套期调整", "减:一年内到期部分",
             "=长期债务 Total long-term debt")
DEBT_Q3 = dict(zip(DEBT_ROWS, (
    (2000, 0), (9000, 9000), (22500, 22500), (15585, 15057), (0, 45000), (0, 7287), (0, 3671), (0, 10228),
    (0, 6001), (0, 3659), (0, 3861), (0, 1221), (49085, 127485), (-542, -1110), (0, -257), (-1996, -1016),
    (46547, 125102))))

# 股东权益变动·Q3 单季(Q3 申报权益变动表;期初 = Q2 申报 6/30 资产负债表 → 跨申报衔接)
# 列: (优先股及资本公积, 普通股及资本公积, AOCI, 留存收益, 权益合计)
EQ_ROWS = ("期初 2026-06-30", "发行普通股(含 ATM)", "股权薪酬", "限制性股票归属代扣税及其他",
           "普通股股息及股息等价物(宣派)", "优先股股息(宣派及计提)", "净利润", "其他综合收益", "期末 2026-09-30")
EQUITY_ROLL_Q3 = dict(zip(EQ_ROWS, (
    (18023, 131371, -2285, 493371, 640480), (0, 12372, 0, 0, 12372), (0, 8681, 0, 0, 8681),
    (0, -5413, 0, 0, -5413), (0, 57, 0, -2757, -2700), (0, 0, 0, -298, -298), (0, 0, 0, 26468, 26468),
    (0, 0, -2041, 0, -2041), (18023, 147068, -4326, 516784, 677549))))

# 单季序列(搜索 / 云 / 云经营利润)—— 2024-2025 各季取 2025 年三份 10-Q(本期列或对比列,见出处),
# 2026Q1 取 2026Q1 10-Q;2026Q2 / Q3 直接用本文件 SEGMENTS_Q2 / SEGMENTS_Q3。Q4 = 年度(分部营收.csv)− 9M。
QUARTERLY = {  # 季度: (搜索及其他, 云收入, 云经营利润, 出处)
    "Q1 2024": (46156, 9574, 900, "2025Q1 10-Q 对比列"),
    "Q2 2024": (48509, 10347, 1172, "2025Q2 10-Q 对比列"),
    "Q3 2024": (49385, 11353, 1947, "2025Q3 10-Q 对比列"),
    "Q1 2025": (50702, 12260, 2177, "2025Q1 10-Q"),
    "Q2 2025": (54190, 13624, 2826, "2025Q2 10-Q"),
    "Q3 2025": (56567, 15157, 3594, "2025Q3 10-Q"),
    "Q1 2026": (60399, 20028, 6598, "2026Q1 10-Q"),
}
NINE_MONTHS = {"9M 2024": (144050, 31274, 4019, "2025Q3 10-Q 对比列"),
               "9M 2025": (161459, 41041, 8597, "2025Q3 10-Q")}
OVERLAP_Q1_2025 = (50702, 12260, 2177)   # 同一季在 2026Q1 10-Q 对比列中的值(查追溯重列)

# 变现指标(MD&A Monetization Metrics,同比变动 %;各申报原表整数)
MONETIZATION = {  # 期: (付费点击, 每次点击费用 CPC, 联盟展示量, 每次展示费用)
    "FY 2025": (6, 7, -7, 7),       # FY2025 10-K
    "Q1 2026": (13, 5, -9, 6),      # 2026Q1 10-Q
    "Q2 2026": (13, 3, -12, 13),    # 2026Q2 10-Q
    "H1 2026": (13, 4, -10, 10),    # 2026Q2 10-Q
    "Q3 2026": (8, 4, -14, 14),     # 2026Q3 10-Q
    "9M 2026": (11, 4, -11, 11),    # 2026Q3 10-Q
}

# 表外承诺与储备 —— 键: (2025-12-31, 2026-06-30, 2026-09-30);数值 = 百万美元;字符串 = 未披露/口径说明
OB_PC, OB_PC_ST, OB_PC_MY, OB_BL, OB_BL_CLOUD, OB_BL_CRUX = (
    "采购承诺及合约义务合计 Purchase commitments & obligations", "其中短期(12个月内) of which short-term",
    "其中多年期(技术基建/存货/能源/内容·Note 10) of which multi-year",
    "收入储备合计 Revenue backlog", "其中Google Cloud of which Google Cloud",
    "其中与 Crux AI(权益法合营·关联方)多年商业协议 of which Crux AI")
OB_LEASE, OB_STL, OB_UNPAID = ("尚未起租的租赁付款(未入表) Leases not yet commenced",
                               "短期租赁不可撤销承诺(期限≤12月·不入表) Short-term lease commitment",
                               "未付capex(计入应付/预提) PP&E in AP & accrued")
OB_CD, OB_FB, OB_FB_CRUX, OB_FG_EN, OB_FG_TPU, OB_FG = (
    "数据中心信用背书·已执行(信用衍生品·最大潜在付款) Backstops executed (credit derivatives)",
    "已签约、待落实的未来信用背书 Future backstops agreed",
    "其中对 Crux AI of which Crux AI (related party)",
    "财务担保·能源设备采购(最大潜在付款) Guarantees: energy equipment",
    "财务担保·TPU 回购义务(最大潜在付款) Guarantees: TPU repurchase",
    "=财务担保合计 Financial guarantees total")
OB_EQF, OB_EQF_PVT = ("股权投资未来出资承诺 Future funding commitments (equity investments)",
                      "其中对一家私营公司的里程碑式出资(权益衍生品·至2030)")
OB_LC = "备用信用证(担保长期供应协议履约·含于多年期承诺) Standby letters of credit"
OFF_BALANCE = {
    OB_PC: (149100, 811000, 924400),
    OB_PC_ST: (113000, 200700, 213400),
    OB_PC_MY: ("10-K 未单列", 707000, 802100),
    OB_LC: ("未披露", "未披露", 4500),
    OB_BL: (242800, 519500, 567700),
    OB_BL_CLOUD: ("未单独披露", 513900, 560800),
    OB_BL_CRUX: ("—", "未披露", 16800),
    OB_LEASE: (58500, 85200, 130500),
    OB_STL: ("5800(含于上行)", 5800, 6000),
    OB_UNPAID: (15090, 29113, 35921),
    OB_CD: (16900, 43800, 48000),
    OB_FB: ("年报未披露", 24100, 27700),
    OB_FB_CRUX: ("—", "未披露", 10000),
    OB_FG_EN: (5700, 7600, 16200),
    OB_FG_TPU: ("—", "未披露", 6600),
    OB_FG: (5700, 7600, 22800),
    OB_EQF: (1100, 21900, 21900),
    OB_EQF_PVT: ("—", 20000, 20000),
}
CREDIT_DERIV_NOTIONAL_Q3 = 48012   # Note 3 衍生品名义金额表(精确值)vs MD&A「$48.0 billion」

# 单季推算用:2026Q1 10-Q 现金流量表两列(Q1'25 / Q1'26);2025Q2 / Q3 10-Q 资产负债表应收
Q1_OCF = (36150, 45790)
Q1_CAPEX = (17197, 35674)
AR_2025_06_30 = 55048
AR_2025_09_30 = 57148
# Q3 业绩 8-K(Ex. 99.1 现金流量表单季列)—— 用于抽查「9M − H1」推出的单季值
EIGHT_K_Q3 = {"Q3'25 OCF": 48414, "Q3'26 OCF": 42290, "Q3'25 capex": 23953, "Q3'26 capex": 51355}

# 单项一手事实(非三表行项,供分析层引用)—— (事实, 值, 时点/期间, 出处)
FACTS = [
    ("SpaceX持股-短期限售 (Level 1·计入有价证券)", 80000, "2026-06-30", "Q2 10-Q Note 3"),
    ("SpaceX持股-长期限售至2027Q3 (计入其他非流动资产)", 14126, "2026-06-30", "Q2 10-Q Note 3"),
    ("SpaceX持股合计 SpaceX total holding", 94126, "2026-06-30", "Q2 10-Q Note 3(两段相加)"),
    ("SpaceX持股-短期限售 (Level 1·计入有价证券;长期限售段脚注本季不再出现)", 75200, "2026-09-30", "Q3 10-Q Note 3"),
    ("非上市股权(计量替代法)账面价值", 124300, "2026-06-30", "Q2 10-Q Note 3 正文"),
    ("其中Q2内按观察交易重估部分 (主要为 Level 2=可观察输入值)", 87900, "Q2 2026", "Q2 10-Q Note 3"),
    ("非上市股权(计量替代法)账面价值", 128200, "2026-09-30", "Q3 10-Q Note 3 正文"),
    ("其中Q3内重估部分 (主要为 Level 3=依赖不可观察输入值)", 8800, "Q3 2026", "Q3 10-Q Note 3"),
    ("公开增发净额 public offering (29M A@$355.1982 + 29M C@$351.8018)", 20500, "2026-06-04", "Q2 10-Q Note 11"),
    ("Berkshire私募净额 private placement (14M A + 14M C)", 10000, "2026-06-04", "Q2 10-Q Note 11"),
    ("强制可转优先股净额 mandatory convertible preferred", 19000, "2026-06-05", "Q2 10-Q Note 11"),
    ("=股权融资合计 total equity raise(现金流量表精确值)", 49562, "H1 2026", "Q2 10-Q 现金流量表"),
    ("capped call溢价(冲减权益) capped call premium", 1000, "2026-06", "Q2 10-Q Note 11"),
    ("ATM额度 ATM Program authorized", 40000, "2026-06-01", "Q2 10-Q Note 11"),
    ("ATM·Class A 发行股数(百万股)", 12, "Q3 2026", "Q3 10-Q Note 11"),
    ("ATM·Class A 净额", 4300, "Q3 2026", "Q3 10-Q Note 11"),
    ("ATM·Class C 发行股数(百万股)", 24, "Q3 2026", "Q3 10-Q Note 11"),
    ("ATM·Class C 净额", 8100, "Q3 2026", "Q3 10-Q Note 11"),
    ("ATM剩余额度 ATM remaining", 27600, "2026-09-30", "Q3 10-Q Note 11"),
    ("回购授权剩余 repurchase authorization remaining(2026 前三季零回购)", 69500, "2026-09-30", "Q3 10-Q Note 11"),
    ("优先股现金股息(Series A/B 各 117)", 234, "Q3 2026", "Q3 10-Q Note 11"),
    ("Wiz收购对价(2026-03-11完成) Wiz consideration", 29500, "2026-03-11", "Q3 10-Q Note 8"),
    ("Wiz商誉 goodwill from Wiz", 22705, "2026-03-11", "Q3 10-Q Note 8"),
    ("Wiz无形资产 intangibles from Wiz", 8300, "2026-03-11", "Q3 10-Q Note 8"),
    ("Wiz承担净负债 net liabilities assumed", -1538, "2026-03-11", "Q3 10-Q Note 8"),
    ("Wiz购买价合计 total purchase price", 29467, "2026-03-11", "Q3 10-Q Note 8"),
    ("EC Android罚款+利息(2026-07已付) EC Android fine paid", 5200, "2026-07", "Q3 10-Q Note 10"),
    ("PriceRunner判决计提合计 legal charge accrued in Q2", 2100, "Q2 2026", "Q2 10-Q MD&A"),
    ("EU DMA 两项不合规决定罚款计提(€430M Play + €460M Search·已上诉)", 1000, "Q3 2026", "Q3 10-Q Note 10"),
    ("应计罚款及和解(流动) Accrued fines and settlements", 13807, "2026-09-30", "Q3 10-Q Note 7"),
    ("应收坏账准备 allowance for credit losses", 1200, "2026-09-30", "Q3 10-Q Note 7(2025 年末 924、6/30 995)"),
    ("少数股东权益(含可赎回;计入普通股及资本公积) NCI", 6900, "2026-09-30", "Q3 10-Q Note 7(2025 年末 3,400)"),
    ("Crux AI:Blackstone 未来出资上限", 5000, "2026-05 签约", "Q3 10-Q Note 3"),
    ("Crux AI:Google 未来数据中心与能源背书上限", 10000, "2026-05 签约", "Q3 10-Q Note 3 / Note 5"),
    ("利息资本化 interest capitalized", 405, "Q3 2026", "Q3 10-Q Note 7(Q3'25 为 130;9M'26 约 1,000)"),
    ("短期租赁费用 short-term lease cost", 109, "Q3 2026", "Q3 10-Q Note 4(Q3'25 为 11)"),
    ("股权薪酬费用合计 total SBC expense", 8700, "Q3 2026", "Q3 10-Q Note 13(Q3'25 为 6,400)"),
    ("未确认股权薪酬成本(加权 2.8 年确认) unrecognized SBC", 61800, "2026-09-30", "Q3 10-Q Note 13"),
    ("递延收入合计 total deferred revenue", 12600, "2026-09-30", "Q3 10-Q Note 2(2025 年末 8,600)"),
    ("Q3 新发美元票据(固定 23.8B + 浮动 1.3B;加权票息 5.55%·约 15 年)", 25100, "Q3 2026", "Q3 10-Q Note 6"),
    ("Q3 发债净额(正文) notes net proceeds", 28700, "Q3 2026", "Q3 10-Q MD&A"),
    ("循环信贷额度(未提用) revolving credit facilities", 10000, "2026-09-30", "Q3 10-Q Note 6"),
    ("员工人数 employees (persons)", 198933, "2026-06-30", "Q2 10-Q MD&A"),
    ("员工人数 employees (persons)", 204757, "2026-09-30", "Q3 10-Q MD&A"),
]


def F(label: str, when: str):
    for k, v, w, _ in FACTS:
        if k == label and w == when:
            return v
    raise KeyError(f"FACTS 缺 {label} @ {when}")


DATA = {
    "INCOME_Q2": INCOME_Q2, "INCOME_Q3": INCOME_Q3, "EPS_Q2": EPS_Q2, "EPS_Q3": EPS_Q3,
    "OIE_Q2": OIE_Q2, "OIE_Q3": OIE_Q3, "EQUITY_GAINS_Q2": EQUITY_GAINS_Q2, "EQUITY_GAINS_Q3": EQUITY_GAINS_Q3,
    "NONMKT_Q2": NONMKT_Q2, "NONMKT_Q3": NONMKT_Q3, "MKT_EQUITY": MKT_EQUITY,
    "BALANCE_Q2": BALANCE_Q2, "BALANCE_Q3": BALANCE_Q3, "CASHFLOW_Q2": CASHFLOW_Q2, "CASHFLOW_Q3": CASHFLOW_Q3,
    "SEGMENTS_Q2": SEGMENTS_Q2, "SEGMENTS_Q3": SEGMENTS_Q3, "SEGMENT_OI_Q2": SEGMENT_OI_Q2,
    "SEGMENT_OI_Q3": SEGMENT_OI_Q3, "SEGMENT_COSTS_Q3": SEGMENT_COSTS_Q3, "GEOGRAPHY_Q2": GEOGRAPHY_Q2,
    "GEOGRAPHY_Q3": GEOGRAPHY_Q3, "DEBT_Q3": DEBT_Q3, "EQUITY_ROLL_Q3": EQUITY_ROLL_Q3,
    "QUARTERLY": QUARTERLY, "NINE_MONTHS": NINE_MONTHS, "MONETIZATION": MONETIZATION, "OFF_BALANCE": OFF_BALANCE,
}


# ---------------------------------------------------------------------------
# 链式读取年度 CSV(读不到行或缺年份即失败,防表头偏移致静默全空)
# ---------------------------------------------------------------------------
def annual_row(fn: str, label: str, years: tuple[str, ...]) -> dict[str, float]:
    with open(os.path.join(HERE, fn), encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    for i, r in enumerate(rows):
        if r and r[0] == label:
            for j in range(i, -1, -1):
                if rows[j] and (rows[j][0] == "科目" or rows[j][0].startswith("【")):
                    got = dict(zip(rows[j][1:], r[1:]))
                    miss = [y for y in years if not got.get(y)]
                    if miss:
                        raise AssertionError(f"链式读取缺值: {fn}「{label}」缺 {miss}")
                    return {y: float(got[y]) for y in years}
    raise AssertionError(f"链式读取失败: {fn} 找不到行「{label}」")


ANNUAL_CF = {k: annual_row("现金流量表.csv", k, ("2025",)) for k in
             ("经营活动现金流量净额 Net cash from operating", "资本开支 Purchases of property and equipment")}
ANNUAL_SEG = {k: annual_row("分部营收.csv", k, ("2024", "2025")) for k in
              ("Google搜索及其他 Search & other", "Google Cloud 云", "Google Cloud 经营利润")}
FY_OCF_2025 = ANNUAL_CF["经营活动现金流量净额 Net cash from operating"]["2025"]
FY_CAPEX_2025 = -ANNUAL_CF["资本开支 Purchases of property and equipment"]["2025"]
FY_SEG = {y: (ANNUAL_SEG["Google搜索及其他 Search & other"][y], ANNUAL_SEG["Google Cloud 云"][y],
              ANNUAL_SEG["Google Cloud 经营利润"][y]) for y in ("2024", "2025")}


# ---------------------------------------------------------------------------
# 勾稽闸门
# ---------------------------------------------------------------------------
class Gate:
    def __init__(self, quiet: bool = False) -> None:
        self.n = 0
        self.quiet = quiet

    def eq(self, label: str, lhs: float, rhs: float, tol: float = 0) -> None:
        self.n += 1
        if abs(lhs - rhs) > tol + 1e-9:
            raise AssertionError(f"勾稽不通过 [{label}]: {lhs} != {rhs} (差 {lhs - rhs})")
        if not self.quiet:
            print(f"  OK  {label}")


def _sum(table: dict, rows, i: int) -> float:
    return sum(table[r][i] for r in rows)


def check_filing(g: Gate, D: dict, tag: str, periods, dates) -> None:
    """单份 10-Q 的表内勾稽(两份申报同一套)。"""
    inc, eps, oie = D[f"INCOME_{tag}"], D[f"EPS_{tag}"], D[f"OIE_{tag}"]
    eg, nm = D[f"EQUITY_GAINS_{tag}"], D[f"NONMKT_{tag}"]
    bs, cf = D[f"BALANCE_{tag}"], D[f"CASHFLOW_{tag}"]
    seg, soi, geo = D[f"SEGMENTS_{tag}"], D[f"SEGMENT_OI_{tag}"], D[f"GEOGRAPHY_{tag}"]
    for i, p in enumerate(periods):
        r = {k: v[i] for k, v in inc.items()}
        g.eq(f"{tag} {p} 收益+总成本开支=经营利润", r[REV] + r[TCE], r[OI])
        g.eq(f"{tag} {p} 四项费用之和=总成本开支", r[COR] + r[RD] + r[SM] + r[GA], r[TCE])
        g.eq(f"{tag} {p} 经营利润+OI&E=除税前", r[OI] + r[OIE_L], r[PRETAX])
        g.eq(f"{tag} {p} 除税前+所得税=净利", r[PRETAX] + r[TAX], r[NI])
        g.eq(f"{tag} {p} 净利+优先股股息=归普净利", r[NI] + r[PREF], r[NIC])
        g.eq(f"{tag} {p} OI&E 七项合计", _sum(oie, OIE_ROWS, i), oie[OIE_TOTAL][i])
        g.eq(f"{tag} {p} OI&E 拆解合计=利润表 OI&E", oie[OIE_TOTAL][i], r[OIE_L])
        # 每股收益:两位小数四舍五入后须与申报值完全相等
        g.eq(f"{tag} {p} 基本EPS=归普净利÷基本股数", round(r[NIC] / eps[SH_B][i], 2), eps[EPS_B][i])
        g.eq(f"{tag} {p} 稀释分子=归普净利+优先股加回", r[NIC] + eps[ADDBACK][i], eps[DNUM][i])
        g.eq(f"{tag} {p} 稀释EPS=稀释分子÷稀释股数", round(eps[DNUM][i] / eps[SH_D][i], 2), eps[EPS_D][i])
        g.eq(f"{tag} {p} 优先股加回 ≤ 当期优先股股息", min(eps[ADDBACK][i], -r[PREF]), eps[ADDBACK][i])
        # Note 3 股权损益
        g.eq(f"{tag} {p} 非上市未实现 毛收益+毛损失=净额", eg[EG_GAIN][i] + eg[EG_LOSS][i], eg[EG_NM][i])
        g.eq(f"{tag} {p} 股权损益三块之和=合计", eg[EG_NM][i] + eg[EG_MKT][i] + eg[EG_REAL][i], eg[EG_TOT][i])
        g.eq(f"{tag} {p} Note 3 股权损益合计 = OI&E 拆解行", eg[EG_TOT][i], oie[OIE_EQ][i])
        # 分部 / 地区
        g.eq(f"{tag} {p} 广告三项=广告合计", seg[S_SEARCH][i] + seg[S_YT][i] + seg[S_NET][i], seg[S_ADS][i])
        g.eq(f"{tag} {p} 广告+订阅=Services", seg[S_ADS][i] + seg[S_SUBS][i], seg[S_SERV][i])
        g.eq(f"{tag} {p} 三分部+对冲=总收入", seg[S_SERV][i] + seg[S_CLOUD][i] + seg[S_OB][i] + seg[S_HEDGE][i],
             seg[S_TOT][i])
        g.eq(f"{tag} {p} 分部收入 = 利润表收入", seg[S_TOT][i], r[REV])
        g.eq(f"{tag} {p} 分部经营利润合计", _sum(soi, SOI_ROWS[:4], i), soi[O_TOT][i])
        g.eq(f"{tag} {p} 分部经营利润 = 利润表经营利润", soi[O_TOT][i], r[OI])
        g.eq(f"{tag} {p} 地区分项=总收入", _sum(geo, GEO_ROWS[:5], i), geo[GEO_ROWS[5]][i])
        g.eq(f"{tag} {p} 地区对冲 = 分部对冲", geo[GEO_ROWS[4]][i], seg[S_HEDGE][i])
        g.eq(f"{tag} {p} 地区合计 = 利润表收入", geo[GEO_ROWS[5]][i], r[REV])
    for j, d in enumerate(dates):
        b = {k: v[j] for k, v in bs.items()}
        g.eq(f"{tag} {d} 资产=负债+权益", b[B_TA], b[B_TL] + b[B_TE])
        g.eq(f"{tag} {d} 负债及权益合计=资产", b[B_TLE], b[B_TA])
        g.eq(f"{tag} {d} 现金+有价证券小计", b[B_CASH] + b[B_MKT], b[B_CMS])
        g.eq(f"{tag} {d} 流动资产分项合计", b[B_CASH] + b[B_MKT] + b[B_AR] + b[B_INV] + b[B_OCA], b[B_TCA])
        g.eq(f"{tag} {d} 总资产分项合计", b[B_TCA] + b[B_NMS] + b[B_DTA] + b[B_PPE] + b[B_OLA] + b[B_GW]
             + b[B_INT] + b[B_ONCA], b[B_TA])
        g.eq(f"{tag} {d} 流动负债分项合计", b[B_AP] + b[B_ACC] + b[B_AEX] + b[B_ARS] + b[B_DR], b[B_TCL])
        g.eq(f"{tag} {d} 总负债分项合计", b[B_TCL] + b[B_LTD] + b[B_ITP] + b[B_DTL] + b[B_OLL] + b[B_OLTL], b[B_TL])
        g.eq(f"{tag} {d} 权益分项合计", b[B_PREF] + b[B_COM] + b[B_AOCI] + b[B_RE], b[B_TE])
        g.eq(f"{tag} {d} 计量替代法账面 = 成本+向上−向下", nm[NM_COST][j] + nm[NM_UP][j] + nm[NM_DOWN][j],
             nm[NM_CARRY][j])
        g.eq(f"{tag} {d} 非上市证券合计 = 资产负债表", nm[NM_CARRY][j] + nm[NM_EQM][j], b[B_NMS])
        g.eq(f"{tag} {d} Note 3 非上市合计行", nm[NM_TOT][j], b[B_NMS])
    cf_periods = periods[2:]
    for i, p in enumerate(cf_periods):
        c = {k: v[i] for k, v in cf.items()}
        g.eq(f"{tag} {p} 经营活动分项合计=经营现金流", sum(c[k] for k in CF_ROWS[:13]), c[C_OCF])
        g.eq(f"{tag} {p} 投资活动分项合计", sum(c[k] for k in CF_ROWS[14:21]), c[C_INV])
        g.eq(f"{tag} {p} 融资活动分项合计", sum(c[k] for k in CF_ROWS[22:31]), c[C_FIN])
        g.eq(f"{tag} {p} 经营+投资+融资+汇率=现金净变动", c[C_OCF] + c[C_INV] + c[C_FIN] + c[C_FX], c[C_NET])
        g.eq(f"{tag} {p} 期初+净变动=期末", c[C_BEG] + c[C_NET], c[C_END])
        g.eq(f"{tag} {p} 现金流净利 = 利润表净利", c[C_NI], inc[NI][2 + i])
    g.eq(f"{tag} 期末现金 = 资产负债表现金({dates[1]})", cf[C_END][1], bs[B_CASH][1])
    g.eq(f"{tag} 期初现金 = 2025 年末资产负债表现金", cf[C_BEG][1], bs[B_CASH][0])


def check_cross(g: Gate, D: dict) -> None:
    """跨申报勾稽:同一时点/期间在两份申报中的值,以及 9M = H1 + Q3。"""
    for k in BS_ROWS:
        g.eq(f"跨申报 2025-12-31「{k}」Q2 申报 = Q3 申报", D["BALANCE_Q2"][k][0], D["BALANCE_Q3"][k][0])
    for k in (NM_COST, NM_UP, NM_DOWN, NM_CARRY, NM_EQM, NM_TOT):
        g.eq(f"跨申报 2025-12-31 Note 3「{k}」", D["NONMKT_Q2"][k][0], D["NONMKT_Q3"][k][0])
    g.eq("跨申报 期初现金(2025 年末)", D["CASHFLOW_Q2"][C_BEG][1], D["CASHFLOW_Q3"][C_BEG][1])
    # 9M = H1 + Q3(三列独立舍入 → 容差 1)
    pairs = (("INCOME", INCOME_Q2.keys()), ("OIE", OIE_ROWS + (OIE_TOTAL,)), ("SEGMENTS", SEG_ROWS),
             ("SEGMENT_OI", SOI_ROWS), ("GEOGRAPHY", GEO_ROWS))
    for tbl, rows in pairs:
        for k in rows:
            for yr, (h, q, n) in (("2025", (2, 0, 2)), ("2026", (3, 1, 3))):
                g.eq(f"跨申报 {yr} 9M=H1+Q3「{tbl}·{k}」",
                     D[f"{tbl}_Q2"][k][h] + D[f"{tbl}_Q3"][k][q], D[f"{tbl}_Q3"][k][n], tol=1)
    # Note 3 股权损益:只有「合计」跨期可加 —— 分项按附注定义不可加(已实现 = 售价 − 「期初」账面,
    # 9M 的「期初」是 1/1、Q3 的「期初」是 7/1,同一笔出售在两种期间口径下拆分不同)
    for yr, (h, q, n) in (("2025", (2, 0, 2)), ("2026", (3, 1, 3))):
        g.eq(f"跨申报 {yr} 9M=H1+Q3 股权证券损益合计",
             D["EQUITY_GAINS_Q2"][EG_TOT][h] + D["EQUITY_GAINS_Q3"][EG_TOT][q], D["EQUITY_GAINS_Q3"][EG_TOT][n])
    # 单季现金流(9M − H1)与 8-K 单季列抽查
    cf2, cf3 = D["CASHFLOW_Q2"], D["CASHFLOW_Q3"]
    g.eq("Q3'25 OCF(9M−H1) = 8-K", cf3[C_OCF][0] - cf2[C_OCF][0], EIGHT_K_Q3["Q3'25 OCF"], tol=1)
    g.eq("Q3'26 OCF(9M−H1) = 8-K", cf3[C_OCF][1] - cf2[C_OCF][1], EIGHT_K_Q3["Q3'26 OCF"], tol=1)
    g.eq("Q3'25 capex(9M−H1) = 8-K", cf2[C_CAPEX][0] - cf3[C_CAPEX][0], EIGHT_K_Q3["Q3'25 capex"], tol=1)
    g.eq("Q3'26 capex(9M−H1) = 8-K", cf2[C_CAPEX][1] - cf3[C_CAPEX][1], EIGHT_K_Q3["Q3'26 capex"], tol=1)
    g.eq("Q2'26 capex(H1−Q1) = 8-K 披露 $44,924M", -cf2[C_CAPEX][1] - Q1_CAPEX[1], 44924)
    # Q3 权益变动表:期初 = Q2 申报 6/30 资产负债表;期末 = Q3 申报 9/30;逐列滚动
    er = D["EQUITY_ROLL_Q3"]
    for col, (bsrow, nm_) in enumerate(((B_PREF, "优先股及资本公积"), (B_COM, "普通股及资本公积"),
                                        (B_AOCI, "AOCI"), (B_RE, "留存收益"), (B_TE, "权益合计"))):
        g.eq(f"Q3 权益变动 期初 {nm_} = Q2 申报 6/30", er[EQ_ROWS[0]][col], D["BALANCE_Q2"][bsrow][1])
        g.eq(f"Q3 权益变动 {nm_} 逐项滚动", sum(er[k][col] for k in EQ_ROWS[:-1]), er[EQ_ROWS[-1]][col])
        g.eq(f"Q3 权益变动 期末 {nm_} = Q3 申报 9/30", er[EQ_ROWS[-1]][col], D["BALANCE_Q3"][bsrow][1])
    for k in EQ_ROWS:
        g.eq(f"Q3 权益变动「{k}」四列之和=合计", sum(er[k][:4]), er[k][4])
    g.eq("Q3 权益变动 净利 = Q3 利润表净利", er["净利润"][3], D["INCOME_Q3"][NI][1])
    g.eq("Q3 权益变动 优先股股息 = 利润表优先股股息", er["优先股股息(宣派及计提)"][3], D["INCOME_Q3"][PREF][1])
    # 发行普通股:Q3 现金流(9M − H1)≈ ATM 两笔净额(正文各舍入 0.1B → 容差 100)
    g.eq("Q3 普通股发行现金(9M−H1) ≈ ATM Class A + Class C 净额",
         cf3[C_COMMON][1] - cf2[C_COMMON][1], F("ATM·Class A 净额", "Q3 2026") + F("ATM·Class C 净额", "Q3 2026"),
         tol=100)
    g.eq("ATM 剩余 = 额度 − 已发行(正文 0.1B 精度)",
         F("ATM额度 ATM Program authorized", "2026-06-01") - F("ATM·Class A 净额", "Q3 2026")
         - F("ATM·Class C 净额", "Q3 2026"), F("ATM剩余额度 ATM remaining", "2026-09-30"))
    # 9M 股息支付 = Note 12 普通股已分配(7,933)+ 优先股现金股息(234)
    g.eq("9M'26 股息支付 = 普通股已分配 7,933 + 优先股现金股息", -cf3[C_DIV][1],
         7933 + F("优先股现金股息(Series A/B 各 117)", "Q3 2026"))
    # 长期债务 Note 6
    db = D["DEBT_Q3"]
    for j, d in enumerate(D_Q3):
        g.eq(f"Note 6 {d} 各批票据之和=面值合计", sum(db[k][j] for k in DEBT_ROWS[:12]), db[DEBT_ROWS[12]][j])
        g.eq(f"Note 6 {d} 面值−折价−套期调整−一年内到期=长期债务", sum(db[k][j] for k in DEBT_ROWS[12:16]),
             db[DEBT_ROWS[16]][j])
        g.eq(f"Note 6 {d} 长期债务 = 资产负债表", db[DEBT_ROWS[16]][j], D["BALANCE_Q3"][B_LTD][j])
    # 上市股权证券(Note 3 Level 1 + Level 2)
    mk = D["MKT_EQUITY"]
    for j, d in enumerate(("2025-12-31", "2026-06-30", "2026-09-30")):
        g.eq(f"{d} 上市股权证券 L1+L2=合计", mk[MK_L1][j] + mk[MK_L2][j], mk[MK_TOT][j])
    g.eq("上市股权证券 ≤ 有价证券(6/30)", min(mk[MK_TOT][1], D["BALANCE_Q2"][B_MKT][1]), mk[MK_TOT][1])
    g.eq("上市股权证券 ≤ 有价证券(9/30)", min(mk[MK_TOT][2], D["BALANCE_Q3"][B_MKT][1]), mk[MK_TOT][2])
    # 分部费用补充披露(Q3):收入 − 成本费用 = 分部经营利润
    sc, s3, o3 = D["SEGMENT_COSTS_Q3"], D["SEGMENTS_Q3"], D["SEGMENT_OI_Q3"]
    for i, p in enumerate(P_Q3):
        g.eq(f"Q3 {p} Services 薪酬+其他=合计", sc[SC_ROWS[0]][i] + sc[SC_ROWS[1]][i], sc[SC_ROWS[2]][i])
        g.eq(f"Q3 {p} Cloud 薪酬+其他=合计", sc[SC_ROWS[3]][i] + sc[SC_ROWS[4]][i], sc[SC_ROWS[5]][i])
        g.eq(f"Q3 {p} Services 收入−成本=经营利润", s3[S_SERV][i] - sc[SC_ROWS[2]][i], o3[O_SERV][i])
        g.eq(f"Q3 {p} Cloud 收入−成本=经营利润", s3[S_CLOUD][i] - sc[SC_ROWS[5]][i], o3[O_CLOUD][i])
    # 表外:分项与合计(正文 0.1B 精度的金额按 0.1B 整数核)
    ob = D["OFF_BALANCE"]
    g.eq("9/30 财务担保 = 能源设备 + TPU 回购", ob[OB_FG_EN][2] + ob[OB_FG_TPU][2], ob[OB_FG][2])
    g.eq("9/30 背书合计 75.7B = 已执行 48.0B + 待落实 27.7B", ob[OB_CD][2] + ob[OB_FB][2], 75700)
    g.eq("9/30 信用衍生品 MD&A 48.0B ≈ Note 3 名义金额", ob[OB_CD][2], CREDIT_DERIV_NOTIONAL_Q3, tol=50)
    g.eq("9/30 VIE 支持承诺 31.9B = 股权出资 21.9B + Crux 背书 10.0B", ob[OB_EQF][2] + ob[OB_FB_CRUX][2], 31900)
    g.eq("9/30 收入储备 Cloud ≤ 合计", min(ob[OB_BL_CLOUD][2], ob[OB_BL][2]), ob[OB_BL_CLOUD][2])
    g.eq("9/30 未付 capex = 现金流量表补充披露", ob[OB_UNPAID][2], cf3[C_UNPAID][1])
    g.eq("6/30 未付 capex = 现金流量表补充披露", ob[OB_UNPAID][1], cf2[C_UNPAID][1])
    for j, d in enumerate(("2025-12-31", "2026-06-30", "2026-09-30")):
        g.eq(f"{d} 短期采购承诺 ≤ 合计", min(ob[OB_PC_ST][j], ob[OB_PC][j]), ob[OB_PC_ST][j])


def check_quarterly(g: Gate, D: dict) -> None:
    """单季序列:跨申报重叠相等、Q1+Q2+Q3=9M、Q4 由年度推算;变现指标与搜索增速自洽。"""
    q, nine = D["QUARTERLY"], D["NINE_MONTHS"]
    s2, s3, o2, o3 = D["SEGMENTS_Q2"], D["SEGMENTS_Q3"], D["SEGMENT_OI_Q2"], D["SEGMENT_OI_Q3"]
    q26 = {"Q2 2026": (s2[S_SEARCH][1], s2[S_CLOUD][1], o2[O_CLOUD][1]),
           "Q3 2026": (s3[S_SEARCH][1], s3[S_CLOUD][1], o3[O_CLOUD][1])}
    for idx, nm_ in enumerate(("搜索", "云收入", "云经营利润")):
        g.eq(f"重叠 Q1 2025 {nm_}:2025Q1 10-Q = 2026Q1 10-Q 对比列", q["Q1 2025"][idx], OVERLAP_Q1_2025[idx])
        g.eq(f"重叠 Q2 2025 {nm_}:2025Q2 10-Q = 2026Q2 10-Q 对比列", q["Q2 2025"][idx],
             (s2[S_SEARCH][0], s2[S_CLOUD][0], o2[O_CLOUD][0])[idx])
        g.eq(f"重叠 Q3 2025 {nm_}:2025Q3 10-Q = 2026Q3 10-Q 对比列", q["Q3 2025"][idx],
             (s3[S_SEARCH][0], s3[S_CLOUD][0], o3[O_CLOUD][0])[idx])
        g.eq(f"重叠 9M 2025 {nm_}:2025Q3 10-Q = 2026Q3 10-Q 对比列", nine["9M 2025"][idx],
             (s3[S_SEARCH][2], s3[S_CLOUD][2], o3[O_CLOUD][2])[idx])
        g.eq(f"重叠 H1 2026 {nm_}:Q1 + Q2 = Q2 申报 H1", q["Q1 2026"][idx] + q26["Q2 2026"][idx],
             (s2[S_SEARCH][3], s2[S_CLOUD][3], o2[O_CLOUD][3])[idx], tol=1)
        for yr, nine_v in (("2024", nine["9M 2024"][idx]), ("2025", nine["9M 2025"][idx]),
                           ("2026", (s3[S_SEARCH][3], s3[S_CLOUD][3], o3[O_CLOUD][3])[idx])):
            qs = [q[f"Q{n} {yr}"][idx] if f"Q{n} {yr}" in q else q26[f"Q{n} {yr}"][idx] for n in (1, 2, 3)]
            g.eq(f"{yr} {nm_} Q1+Q2+Q3 = 9M", sum(qs), nine_v, tol=1)
    m = D["MONETIZATION"]
    search_yoy = {"FY 2025": FY_SEG["2025"][0] / FY_SEG["2024"][0] - 1,
                  "Q1 2026": q["Q1 2026"][0] / q["Q1 2025"][0] - 1,
                  "Q2 2026": s2[S_SEARCH][1] / s2[S_SEARCH][0] - 1, "H1 2026": s2[S_SEARCH][3] / s2[S_SEARCH][2] - 1,
                  "Q3 2026": s3[S_SEARCH][1] / s3[S_SEARCH][0] - 1, "9M 2026": s3[S_SEARCH][3] / s3[S_SEARCH][2] - 1}
    for p, (clk, cpc, _, _) in m.items():
        # 点击 × CPC 只覆盖点击驱动收入、两项又各自取整 → 与搜索收入同比容差 1.5pp(只拦转录错位,如 8 记成 18)
        g.eq(f"{p} 付费点击×CPC ≈ 搜索收入同比", (1 + clk / 100) * (1 + cpc / 100) - 1, search_yoy[p], tol=0.015)


def verify(D: dict, quiet: bool = False) -> int:
    g = Gate(quiet)
    if not quiet:
        print("== Q2 申报表内勾稽 ==")
    check_filing(g, D, "Q2", P_Q2, D_Q2)
    if not quiet:
        print("== Q3 申报表内勾稽 ==")
    check_filing(g, D, "Q3", P_Q3, D_Q3)
    if not quiet:
        print("== 跨申报 / 附注 / 表外勾稽 ==")
    check_cross(g, D)
    if not quiet:
        print("== 单季序列与变现指标 ==")
    check_quarterly(g, D)
    return g.n


# ---------------------------------------------------------------------------
# ±1 变异:检验勾稽本身覆盖了多少转录格
# ---------------------------------------------------------------------------
def mutate_report() -> int:
    total, caught, missed = 0, 0, []
    for tname, table in DATA.items():
        for row, vals in table.items():
            for idx, v in enumerate(vals):
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    continue
                for delta in ((0.01, -0.01) if isinstance(v, float) else (1, -1)):
                    new_vals = tuple(x + delta if j == idx else x for j, x in enumerate(vals))
                    mutated = {**DATA, tname: {**table, row: new_vals}}
                    total += 1
                    try:
                        with contextlib.redirect_stdout(io.StringIO()):
                            verify(mutated, quiet=True)
                    except AssertionError:
                        caught += 1
                    else:
                        missed.append(f"{tname}「{row}」[{idx}] {delta:+}")
    print(f"±1 变异 {total} 次,被勾稽拦下 {caught} 次,覆盖率 {caught / total:.1%}")
    print(f"漏网 {len(missed)} 处(这些格只能靠回源核对):")
    for x in missed:
        print("   ", x)
    return 0


# ---------------------------------------------------------------------------
# 派生指标(全部从上方数据计算)
# ---------------------------------------------------------------------------
def pct(x: float) -> str:
    return f"{x:.1%}"


def single_quarter_cf() -> dict[str, tuple[int, int]]:
    """单季经营现金流与资本开支(正数)。Q4'25 = FY2025 − 9M'25;Q1 取 2026Q1 10-Q;Q2 = H1 − Q1;Q3 = 9M − H1。"""
    c2, c3 = CASHFLOW_Q2, CASHFLOW_Q3
    return {
        "Q2 2025": (c2[C_OCF][0] - Q1_OCF[0], -c2[C_CAPEX][0] - Q1_CAPEX[0]),
        "Q3 2025": (c3[C_OCF][0] - c2[C_OCF][0], c2[C_CAPEX][0] - c3[C_CAPEX][0]),
        "Q4 2025": (int(FY_OCF_2025) - c3[C_OCF][0], int(FY_CAPEX_2025) + c3[C_CAPEX][0]),
        "Q1 2026": (Q1_OCF[1], Q1_CAPEX[1]),
        "Q2 2026": (c2[C_OCF][1] - Q1_OCF[1], -c2[C_CAPEX][1] - Q1_CAPEX[1]),
        "Q3 2026": (c3[C_OCF][1] - c2[C_OCF][1], c2[C_CAPEX][1] - c3[C_CAPEX][1]),
    }


def derived_quarter() -> list[list[str]]:
    """单季口径:列 = Q2'25, Q2'26, Q3'25, Q3'26。"""
    cols = (("Q2", 0), ("Q2", 1), ("Q3", 0), ("Q3", 1))
    inc = {"Q2": INCOME_Q2, "Q3": INCOME_Q3}
    eps = {"Q2": EPS_Q2, "Q3": EPS_Q3}
    seg = {"Q2": SEGMENTS_Q2, "Q3": SEGMENTS_Q3}
    soi = {"Q2": SEGMENT_OI_Q2, "Q3": SEGMENT_OI_Q3}
    oie = {"Q2": OIE_Q2, "Q3": OIE_Q3}
    cf = single_quarter_cf()
    cf_cols = ("Q2 2025", "Q2 2026", "Q3 2025", "Q3 2026")
    out = []

    def row(name, fn, how):
        out.append([name] + [fn(t, i) for t, i in cols] + [how])

    etr = lambda t, i: -inc[t][TAX][i] / inc[t][PRETAX][i]  # noqa: E731
    row("经营利润率 Operating margin", lambda t, i: pct(inc[t][OI][i] / inc[t][REV][i]), "经营利润÷收入")
    row("Google Cloud 经营利润率", lambda t, i: pct(soi[t][O_CLOUD][i] / seg[t][S_CLOUD][i]), "云经营利润÷云收入")
    row("Google Services 经营利润率", lambda t, i: pct(soi[t][O_SERV][i] / seg[t][S_SERV][i]),
        "Services经营利润÷Services收入")
    row("有效税率 Effective tax rate", lambda t, i: pct(etr(t, i)), "所得税÷除税前利润")
    row("OI&E占除税前利润 OI&E/pretax", lambda t, i: pct(inc[t][OIE_L][i] / inc[t][PRETAX][i]),
        "OI&E÷除税前利润(口径污染度;负值=OI&E 为净损失)")
    row("股权证券损益 ÷ 经营利润", lambda t, i: f"{oie[t][OIE_EQ][i] / inc[t][OI][i]:.2f}x",
        "Note 3 股权证券损益÷经营利润(正=抬高报告净利,负=压低)")

    def core_eps(t, i, rate):
        return (inc[t][OI][i] * (1 - rate) + inc[t][PREF][i]) / eps[t][SH_D][i]

    row("核心稀释EPS(估) core diluted EPS (USD)", lambda t, i: f"{core_eps(t, i, etr(t, i)):.2f}",
        "(经营利润×(1−当期有效税率)−优先股股息)÷稀释股数·剔除OI&E·【推】非申报口径;"
        "2026-10-29 起扣优先股股息、改用 Note 12 稀释股数(旧版以「归普净利÷稀释EPS」倒推股数)")
    row("核心稀释EPS(估·按去年同期有效税率) @prior-year tax rate",
        lambda t, i: f"{core_eps(t, i, etr(t, 0)):.2f}",
        "敏感性对照:当期有效税率被股权证券未实现损益按法定税率计提的递延税扭曲(Q2 抬高、Q3 压低,10-Q 原文),"
        "改用去年同季税率;核心 EPS 同比在两行之间")
    row("报告稀释EPS reported diluted EPS (USD)", lambda t, i: f"{eps[t][EPS_D][i]:.2f}", "10-Q 申报值")

    def yoy_row(name, fn, how):
        out.append([name, "", f"{fn('Q2', 1) / fn('Q2', 0) - 1:+.1%}", "", f"{fn('Q3', 1) / fn('Q3', 0) - 1:+.1%}", how])

    yoy_row("收入同比 revenue YoY", lambda t, i: inc[t][REV][i], "本季÷去年同季−1(同一份 10-Q 两列)")
    yoy_row("经营利润同比 operating income YoY", lambda t, i: inc[t][OI][i], "同上")
    yoy_row("报告净利同比 net income YoY", lambda t, i: inc[t][NI][i], "同上;含 OI&E 股权重估,不能当经营成绩读")
    yoy_row("报告稀释EPS同比", lambda t, i: eps[t][EPS_D][i], "同上")
    yoy_row("核心稀释EPS同比(当期税率)", lambda t, i: core_eps(t, i, etr(t, i)), "核心 EPS 两期均按各自当期有效税率")
    yoy_row("核心稀释EPS同比(按去年同期税率)", lambda t, i: core_eps(t, i, etr(t, 0)), "两期均按去年同季税率")
    sq = {c: cf[c] for c in cf_cols}
    out.append(["单季经营现金流 quarterly OCF"] + [str(sq[c][0]) for c in cf_cols]
               + ["Q2 = H1 − Q1(2026Q1 10-Q 两列);Q3 = 9M − H1(两份 10-Q);Q3 两格与 8-K 单季列一致"])
    out.append(["单季资本开支 quarterly capex"] + [str(sq[c][1]) for c in cf_cols] + ["同上"])
    out.append(["单季自由现金流 quarterly FCF"] + [str(sq[c][0] - sq[c][1]) for c in cf_cols]
               + ["单季 OCF − 单季 capex"])
    out.append(["单季 capex÷经营现金流"] + [pct(sq[c][1] / sq[c][0]) for c in cf_cols] + ["资本开支÷经营现金流"])
    oi_q = (INCOME_Q2[OI][0], INCOME_Q2[OI][1], INCOME_Q3[OI][0], INCOME_Q3[OI][1])
    out.append(["单季经营现金流÷经营利润 quarterly OCF/OI"]
               + [f"{sq[c][0] / o:.2f}" for c, o in zip(cf_cols, oi_q)] + ["单季 OCF ÷ 单季经营利润"])
    dep_q = (None, None, CASHFLOW_Q3[C_DEP][0] - CASHFLOW_Q2[C_DEP][0], CASHFLOW_Q3[C_DEP][1] - CASHFLOW_Q2[C_DEP][1])
    out.append(["单季折旧 quarterly depreciation"] + ["", "", str(dep_q[2]), str(dep_q[3])]
               + ["Q3 = 9M − H1(Q2 单季需 Q1 折旧,未转录)"])
    out.append(["单季 capex÷折旧"] + ["", "", f"{sq['Q3 2025'][1] / dep_q[2]:.2f}x", f"{sq['Q3 2026'][1] / dep_q[3]:.2f}x"]
               + ["单季资本开支÷单季折旧(未来折旧台阶指示)"])
    return out


def derived_cumulative() -> list[list[str]]:
    """累计口径:列 = H1'25, H1'26, 9M'25, 9M'26。"""
    cfs = ((CASHFLOW_Q2, 0), (CASHFLOW_Q2, 1), (CASHFLOW_Q3, 0), (CASHFLOW_Q3, 1))
    revs = (INCOME_Q2[REV][2], INCOME_Q2[REV][3], INCOME_Q3[REV][2], INCOME_Q3[REV][3])
    out = []

    def row(name, fn, how):
        out.append([name] + [fn(c, i) for c, i in cfs] + [how])

    row("累计自由现金流 FCF", lambda c, i: str(c[C_OCF][i] + c[C_CAPEX][i]), "经营现金流 − 资本开支")
    row("FCF÷经营现金流", lambda c, i: pct((c[C_OCF][i] + c[C_CAPEX][i]) / c[C_OCF][i]), "FCF÷OCF")
    ois = (INCOME_Q2[OI][2], INCOME_Q2[OI][3], INCOME_Q3[OI][2], INCOME_Q3[OI][3])
    out.append(["经营现金流÷经营利润 OCF/OI"] + [f"{c[C_OCF][i] / o:.2f}" for (c, i), o in zip(cfs, ois)]
               + ["累计 OCF ÷ 累计经营利润(核心利润的现金含量;报告净利含未实现股权重估,不作分母)"])
    row("capex÷经营现金流", lambda c, i: pct(-c[C_CAPEX][i] / c[C_OCF][i]), "资本开支÷经营现金流")
    row("capex÷折旧", lambda c, i: f"{-c[C_CAPEX][i] / c[C_DEP][i]:.2f}x", "资本开支÷当期折旧(未来折旧台阶指示)")
    out.append(["SBC÷收入 SBC/revenue"] + [pct(c[C_SBC][i] / r) for (c, i), r in zip(cfs, revs)]
               + ["现金流量表股权薪酬÷收入"])
    row("股东现金流净额(回购+股息−普通股发行−优先股发行)",
        lambda c, i: str(-c[C_REP][i] - c[C_DIV][i] - c[C_COMMON][i] - c[C_PREFI][i]),
        "正=净返还股东,负=净向股东融资;不含股权激励代扣税净支付(该项 9M'26 为 −17,424,ATM 明示主要用于覆盖它)")
    row("其中:股份回购", lambda c, i: str(-c[C_REP][i]), "现金流量表")
    row("其中:股息(普通股 + 优先股)", lambda c, i: str(-c[C_DIV][i]), "现金流量表")
    row("其中:股权融资(普通股 + 优先股)", lambda c, i: str(c[C_COMMON][i] + c[C_PREFI][i]), "现金流量表")
    return out


def derived_quarter_series() -> list[list[str]]:
    """单季现金流序列 + TTM:列 = Q3'25, Q4'25, Q1'26, Q2'26, Q3'26。"""
    cf = single_quarter_cf()
    cols = ("Q3 2025", "Q4 2025", "Q1 2026", "Q2 2026", "Q3 2026")
    ttm_ocf = sum(cf[c][0] for c in cols[1:])
    ttm_capex = sum(cf[c][1] for c in cols[1:])
    return [
        ["单季经营现金流"] + [str(cf[c][0]) for c in cols] + [str(ttm_ocf), "Q4'25 = FY2025(现金流量表.csv)− 9M'25"],
        ["单季资本开支"] + [str(cf[c][1]) for c in cols] + [str(ttm_capex), "同上"],
        ["单季自由现金流"] + [str(cf[c][0] - cf[c][1]) for c in cols] + [str(ttm_ocf - ttm_capex), "OCF − capex"],
        ["capex÷经营现金流"] + [pct(cf[c][1] / cf[c][0]) for c in cols] + [pct(ttm_capex / ttm_ocf), "资本开支÷经营现金流"],
    ]


def derived_point() -> list[list[str]]:
    """时点口径:列 = 2025-12-31, 2026-06-30, 2026-09-30。"""
    bs = ((BALANCE_Q3, 0), (BALANCE_Q2, 1), (BALANCE_Q3, 1))
    ob = OFF_BALANCE
    out = []

    def row(name, fn, how):
        out.append([name] + [fn(b, i, j) for j, (b, i) in enumerate(bs)] + [how])

    row("净现金(含受限股权) gross net cash", lambda b, i, j: str(b[B_CMS][i] - b[B_LTD][i]), "(现金+有价证券)−长期债务")
    row("净现金(剔上市股权证券) liquid net cash",
        lambda b, i, j: str(b[B_CMS][i] - MKT_EQUITY[MK_TOT][j] - b[B_LTD][i]),
        "(现金+有价证券−上市股权证券[Note 3])−长期债务·剔除受限SpaceX后可动用口径;6/30 另有 14,126 SpaceX 长期限售在其他非流动资产,本来就不在分子里")
    row("商誉÷总资产 Goodwill/assets", lambda b, i, j: pct(b[B_GW][i] / b[B_TA][i]), "商誉÷总资产")
    row("采购承诺÷总资产 commitments/assets", lambda b, i, j: pct(ob[OB_PC][j] / b[B_TA][i]),
        "表外采购承诺÷总资产;⚠️ 9/30 起部分长期供应协议按合同上限价量列示(此前按最低量价),见 表外承诺与储备.csv 表头")
    row("(背书+担保)÷总资产 contingent/assets",
        lambda b, i, j: pct((ob[OB_CD][j] + (ob[OB_FB][j] if isinstance(ob[OB_FB][j], int) else 0) + ob[OB_FG][j])
                            / b[B_TA][i]),
        "(已执行背书+待落实背书+财务担保)÷总资产;2025 年末无待落实背书披露")
    row("存货 inventory", lambda b, i, j: str(b[B_INV][i]), "资产负债表")
    row("上市股权证券÷总资产", lambda b, i, j: pct(MKT_EQUITY[MK_TOT][j] / b[B_TA][i]), "Note 3 上市股权证券÷总资产")
    row("非上市证券÷总资产", lambda b, i, j: pct(b[B_NMS][i] / b[B_TA][i]), "非上市证券(主要为一家私营公司)÷总资产")
    nm_carry = (NONMKT_Q3[NM_CARRY][0], NONMKT_Q2[NM_CARRY][1], NONMKT_Q3[NM_CARRY][1])
    nm_up = (NONMKT_Q3[NM_UP][0], NONMKT_Q2[NM_UP][1], NONMKT_Q3[NM_UP][1])
    out.append(["累计向上调整÷计量替代法账面(账面中「重估出来」的部分)"]
               + [pct(u / c) for u, c in zip(nm_up, nm_carry)] + ["Note 3"])
    return out


def derived_receivables() -> list[list[str]]:
    """应收同轴比较:同一日期的上年同期 vs 本期。"""
    ar_h1 = (AR_2025_06_30 / (INCOME_Q2[REV][2] * 2), BALANCE_Q2[B_AR][1] / (INCOME_Q2[REV][3] * 2))
    ar_9m = (AR_2025_09_30 / (INCOME_Q3[REV][2] * 4 / 3), BALANCE_Q3[B_AR][1] / (INCOME_Q3[REV][3] * 4 / 3))
    return [
        ["应收÷年化收入(6/30·H1×2)", pct(ar_h1[0]), pct(ar_h1[1]),
         "2025-06-30 应收 55,048(2025Q2 10-Q)÷(H1'25×2) vs 2026-06-30;两端同轴"],
        ["应收÷年化收入(9/30·9M×4/3)", pct(ar_9m[0]), pct(ar_9m[1]),
         "2025-09-30 应收 57,148(2025Q3 10-Q)÷(9M'25×4/3) vs 2026-09-30;两端同轴"],
        ["应收同比 vs 收入同比(6/30)", f"应收 {BALANCE_Q2[B_AR][1] / AR_2025_06_30 - 1:+.1%}",
         f"H1收入 {INCOME_Q2[REV][3] / INCOME_Q2[REV][2] - 1:+.1%}", "应收 2026-06-30 vs 2025-06-30;收入 H1 同比"],
        ["应收同比 vs 收入同比(9/30)", f"应收 {BALANCE_Q3[B_AR][1] / AR_2025_09_30 - 1:+.1%}",
         f"9M收入 {INCOME_Q3[REV][3] / INCOME_Q3[REV][2] - 1:+.1%}", "应收 2026-09-30 vs 2025-09-30;收入 9M 同比"],
    ]


def write_csvs() -> list[str]:
    written = []
    path = os.path.join(HERE, "中期财务-2026.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            f"# 单位: 百万美元(USD millions), 费用/流出=负数; 真源: Q2/H1 列 = {SRC_Q2}; Q3/9M 列 = {SRC_Q3}; "
            "2025-12-31 两份申报一致(脚本逐行核对); 中期数据·不并入年度序列(年度见 利润表/资产负债表/现金流量表.csv 覆盖1999-2025); "
            "勾稽校验见 _build_interim_2026.py(默认容差 0;跨申报期间相加容差 1); "
            "英文缩写全对照见 finance/_模板/美股财报缩写对照表.md —— "
            "OI&E=其他收入(支出)净额(主业之外全部损益·含股权公允价值变动) / EPS=每股收益 / "
            "FCF=自由现金流(经营现金流-资本开支) / capex=资本开支 / SBC=股权薪酬 / "
            "APIC=资本公积 / AOCI=累计其他综合收益 / ATM=随行就市增发计划(非自动柜员机) / "
            "capped call=上限看涨期权(对冲转股摊薄) / Level 1=活跃市场报价·Level 2=可观察输入值·Level 3=依赖不可观察输入值"
        ])
        flow_hdr = list(P_Q2 + P_Q3)
        w.writerow([])
        w.writerow(["【利润表·中期】", *flow_hdr])
        for k in INCOME_Q2:
            w.writerow([k, *INCOME_Q2[k], *INCOME_Q3[k]])
        for k in EPS_Q2:
            w.writerow([k, *EPS_Q2[k], *EPS_Q3[k]])
        w.writerow([])
        w.writerow(["【OI&E 拆解·中期】", *flow_hdr])
        for k in OIE_Q2:
            w.writerow([k, *OIE_Q2[k], *OIE_Q3[k]])
        w.writerow([])
        w.writerow(["【股权证券损益拆分·Note 3】(⚠️ 分项跨期不可相加:已实现=售价−「期初」账面,9M 与 Q3 的期初不同;只有合计行可加)",
                    *flow_hdr])
        for k in EQUITY_GAINS_Q2:
            w.writerow([k, *EQUITY_GAINS_Q2[k], *EQUITY_GAINS_Q3[k]])
        w.writerow([])
        w.writerow(["【计量替代法非上市股权账面构成·Note 3】", "2025-12-31", "2026-06-30", "2026-09-30"])
        for k in NONMKT_Q2:
            w.writerow([k, NONMKT_Q2[k][0], NONMKT_Q2[k][1], NONMKT_Q3[k][1]])
        w.writerow([])
        w.writerow(["【上市股权证券·Note 3 公允价值表】", "2025-12-31", "2026-06-30", "2026-09-30"])
        for k, v in MKT_EQUITY.items():
            w.writerow([k, *v])
        w.writerow([])
        w.writerow(["【资产负债表】", "2025-12-31", "2026-06-30", "2026-09-30"])
        for k in BS_ROWS:
            w.writerow([k, BALANCE_Q2[k][0], BALANCE_Q2[k][1], BALANCE_Q3[k][1]])
        w.writerow([])
        w.writerow(["【现金流量表·累计】", "H1 2025", "H1 2026", "9M 2025", "9M 2026"])
        for k in CF_ROWS:
            w.writerow([k, *CASHFLOW_Q2[k], *CASHFLOW_Q3[k]])
        w.writerow([])
        w.writerow(["【长期债务·Q3 10-Q Note 6】", "2025-12-31", "2026-09-30"])
        for k, v in DEBT_Q3.items():
            w.writerow([k, *v])
        w.writerow([])
        w.writerow(["【股东权益变动·Q3 单季(期初=Q2 申报 6/30)】", "优先股及资本公积", "普通股及资本公积", "AOCI",
                    "留存收益", "权益合计"])
        for k, v in EQUITY_ROLL_Q3.items():
            w.writerow([k, *v])
        w.writerow([])
        w.writerow(["【派生·单季】", "Q2 2025", "Q2 2026", "Q3 2025", "Q3 2026", "算法"])
        w.writerows(derived_quarter())
        w.writerow([])
        w.writerow(["【派生·累计】", "H1 2025", "H1 2026", "9M 2025", "9M 2026", "算法"])
        w.writerows(derived_cumulative())
        w.writerow([])
        w.writerow(["【派生·单季现金流序列】", "Q3 2025", "Q4 2025", "Q1 2026", "Q2 2026", "Q3 2026", "近四季 TTM", "算法"])
        w.writerows(derived_quarter_series())
        w.writerow([])
        w.writerow(["【派生·时点】", "2025-12-31", "2026-06-30", "2026-09-30", "算法"])
        w.writerows(derived_point())
        w.writerow([])
        w.writerow(["【派生·应收同轴】", "2025 同日", "2026", "算法"])
        w.writerows(derived_receivables())
        w.writerow([])
        w.writerow(["【单项一手事实】", "值(百万美元·除标注)", "时点/期间", "出处"])
        for k, v, when, src in FACTS:
            w.writerow([k, v, when, src])
    written.append(path)

    path = os.path.join(HERE, "分部营收-中期2026.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            f"# 单位: 百万美元(USD millions); 真源: Q2/H1 列 = {SRC_Q2}; Q3/9M 列 = {SRC_Q3}; 单季序列另引 2025 年三份 10-Q 与 2026Q1 10-Q; "
            "中期分部·不并入 分部营收.csv 年度序列; 勾稽: 广告三项=广告合计·广告+订阅=Services·"
            "三分部+对冲=总收入=利润表收入·分部经营利润合计=利润表经营利润·地区分项=总收入·9M=H1+Q3·Q1+Q2+Q3=9M; "
            "缩写: YoY=同比 / EMEA=欧洲中东非洲 / APAC=亚太 / CPC=每次点击费用 "
            "(全对照见 finance/_模板/美股财报缩写对照表.md)"
        ])

        def yoy(prev: float, cur: float) -> str:
            # 符号翻转(如对冲损益由负转正)算同比无意义 → n/a,不输出会误导的百分比
            if prev <= 0 or cur <= 0:
                return "n/a(符号翻转或非正)"
            return f"{(cur / prev - 1):+.1%}"

        w.writerow([])
        w.writerow(["【收入按类型】", "Q2 2025", "Q2 2026", "Q2 YoY", "H1 2025", "H1 2026", "H1 YoY",
                    "Q3 2025", "Q3 2026", "Q3 YoY", "9M 2025", "9M 2026", "9M YoY"])
        for k in SEG_ROWS:
            a, b = SEGMENTS_Q2[k], SEGMENTS_Q3[k]
            w.writerow([k, a[0], a[1], yoy(a[0], a[1]), a[2], a[3], yoy(a[2], a[3]),
                        b[0], b[1], yoy(b[0], b[1]), b[2], b[3], yoy(b[2], b[3])])
        w.writerow([])
        w.writerow(["【分部经营利润】", *P_Q2, *P_Q3])
        for k in SOI_ROWS:
            w.writerow([k, *SEGMENT_OI_Q2[k], *SEGMENT_OI_Q3[k]])
        w.writerow([])
        w.writerow(["【分部费用补充披露·Q3 10-Q Note 15】", *P_Q3])
        for k, v in SEGMENT_COSTS_Q3.items():
            w.writerow([k, *v])
        w.writerow([])
        w.writerow(["【收入按地区】", *P_Q2, *P_Q3])
        for k in GEO_ROWS:
            w.writerow([k, *GEOGRAPHY_Q2[k], *GEOGRAPHY_Q3[k]])

        # 单季序列
        quarters = ["Q1 2024", "Q2 2024", "Q3 2024", "Q4 2024", "Q1 2025", "Q2 2025", "Q3 2025", "Q4 2025",
                    "Q1 2026", "Q2 2026", "Q3 2026"]
        series = {k: v[:3] for k, v in QUARTERLY.items()}
        series["Q2 2026"] = (SEGMENTS_Q2[S_SEARCH][1], SEGMENTS_Q2[S_CLOUD][1], SEGMENT_OI_Q2[O_CLOUD][1])
        series["Q3 2026"] = (SEGMENTS_Q3[S_SEARCH][1], SEGMENTS_Q3[S_CLOUD][1], SEGMENT_OI_Q3[O_CLOUD][1])
        for yr in ("2024", "2025"):
            nine = NINE_MONTHS[f"9M {yr}"]
            series[f"Q4 {yr}"] = tuple(int(FY_SEG[yr][n]) - nine[n] for n in range(3))
        w.writerow([])
        w.writerow(["【单季序列·搜索与云】(Q4 = 年度 − 9M;2024-2025 各季取 2025 年 10-Q,2026Q1 取 2026Q1 10-Q)", *quarters])
        names = ("Google搜索及其他 单季收入", "Google Cloud 单季收入", "Google Cloud 单季经营利润")
        for n, nm_ in enumerate(names):
            w.writerow([nm_] + [series[q][n] for q in quarters])

        def lag(q: str, back: int) -> str | None:
            qi = quarters.index(q) - back
            return quarters[qi] if qi >= 0 else None

        for n, nm_ in ((0, "搜索 单季同比"), (1, "云 单季同比")):
            w.writerow([nm_] + [f"{series[q][n] / series[lag(q, 4)][n] - 1:+.1%}" if lag(q, 4) else "" for q in quarters])
        w.writerow(["搜索 两年复合(本季÷两年前同季−1)"]
                   + [f"{series[q][0] / series[lag(q, 8)][0] - 1:+.1%}" if lag(q, 8) else "" for q in quarters])
        w.writerow(["搜索 环比"] + [f"{series[q][0] / series[lag(q, 1)][0] - 1:+.1%}" if lag(q, 1) else "" for q in quarters])
        w.writerow(["云 单季经营利润率"] + [f"{series[q][2] / series[q][1]:.1%}" for q in quarters])

        w.writerow([])
        w.writerow(["【变现指标·同比变动 %(MD&A Monetization Metrics)】", *MONETIZATION])
        for n, nm_ in enumerate(("搜索及其他·付费点击 paid clicks", "搜索及其他·每次点击费用 CPC",
                                 "联盟网络·展示量 impressions", "联盟网络·每次展示费用 cost-per-impression")):
            w.writerow([nm_] + [MONETIZATION[p][n] for p in MONETIZATION])
    written.append(path)

    path = os.path.join(HERE, "表外承诺与储备.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            f"# 单位: 百万美元(USD millions); 真源: FY2025 10-K=美股年报 (report/google/2025.htm) + {SRC_Q2} + {SRC_Q3}; "
            "⚠️ 口径断点①收入储备 2026Q1 起纳入原始期限≤1年合同(量级小:2026Q1 10-Q 披露截至 2026-03-31 该部分约 $7.3B); "
            "⚠️ 口径断点②采购承诺:FY2025 10-K 与 2026Q2 10-Q 均称可变条款协议「不超出最低数量/价格估计」;"
            "2026Q3 10-Q Note 10 改称部分长期供应协议「按合同上限价格与数量列示」,MD&A 删去「最低」一句 —— "
            "6/30→9/30 的增量含计量口径变化,10-Q 未量化其影响,不可全部视为新签; "
            "多年期承诺 6/30 的 707,000 为「固定或保证」口径、9/30 的 802,100 为上限口径且含 4,500 备用信用证; "
            "租赁:2025 年末未起租租赁含短期 5,800 + 长期 52,700(10-K);6/30 的 85,200 不含当月另签的短期租赁(不可撤销约 5,800·Q3 起租);"
            "9/30 该短期租赁已起租并于 9 月修订,剩余不可撤销约 6,000(Note 4);未付capex 2025-12-31 取 FY2025 10-K; "
            "缩写: capex=资本开支 / take-or-pay=照付不议(不用也得付) "
            "(全对照见 finance/_模板/美股财报缩写对照表.md)"
        ])
        w.writerow([])
        w.writerow(["项目", "2025-12-31", "2026-06-30", "2026-09-30", "季度变化(6/30→9/30)"])
        for k, v in OFF_BALANCE.items():
            chg = f"{(v[2] / v[1] - 1):+.1%}" if all(isinstance(x, int) for x in v[1:]) else "n/a"
            w.writerow([k, *v, chg])
        cont = [OFF_BALANCE[OB_CD][j] + (OFF_BALANCE[OB_FB][j] if isinstance(OFF_BALANCE[OB_FB][j], int) else 0)
                + OFF_BALANCE[OB_FG][j] for j in range(3)]
        w.writerow(["=或有承诺合计(已执行背书+待落实背书+财务担保)", *cont, f"{cont[2] / cont[1] - 1:+.1%}"])
    written.append(path)
    return written


def main() -> int:
    if "--mutate" in sys.argv:
        verify(DATA, quiet=True)
        return mutate_report()
    print(f"真源: {SRC_Q2}\n      {SRC_Q3}\n")
    try:
        n = verify(DATA)
    except AssertionError as exc:
        print(f"\n❌ {exc}\n→ CSV 未写出（校验不过不落盘）", file=sys.stderr)
        return 1
    print(f"\n✅ 全部勾稽通过（{n} 条）\n")
    for path in write_csvs():
        print(f"写出 {os.path.relpath(path, HERE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
