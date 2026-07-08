# -*- coding: utf-8 -*-
"""泡泡玛特(09992.HK) 三表数据 + 派生比率 → 写 CSV,内置勾稽自洽校验(校验不过不写出)。

数据血缘:
  2017-2019 列 ← report/泡泡玛特/招股说明书.pdf **附录一会计师报告 P I-4 ~ I-13**
                 (2017/2018/2019 综合损益表 P I-4~5, 综合资产负债表 P I-6~7,
                  综合权益变动表 P I-9~11, 综合现金流量表 P I-13~14)
                 —— 附录一是经罗兵咸永道审计的**完整拆分版**(权益法/FVTPL/递延所得税/
                  租赁流动非流动拆分/合计项/CF 细分), 优于招股书概要 P11-19 的合并粒度
  2020 列  ← report/泡泡玛特/2020.pdf (损益 P136 / 资产负债 P138 / 现金流 P142)
  2021 列  ← report/泡泡玛特/2021.pdf (损益 P164 / 资产负债 P166 / 现金流 P171)
  2022 列  ← report/泡泡玛特/2022.pdf (损益 P177 / 资产负债 P179 / 现金流 P184) + 2023 报对照列
  2023 列  ← report/泡泡玛特/2023.pdf (损益 P179 / 资产负债 P181 / 现金流 P186) + 2024 报对照列
  2024 列  ← report/泡泡玛特/2024.pdf (损益 P187 / 资产负债 P189 / 现金流 P194) + 2025 报对照列
  2025 列  ← report/泡泡玛特/2025.pdf (损益 P217 / 资产负债 P219 / 现金流 P224)

口径:
  - 单位 = 人民币千元 (RMB'000, 年报/招股书原始口径)
  - 资产/负债/权益 = 全部正数 (与年报呈现一致)
  - 现金流量表 = 流出/减项用负数, 流入/加项用正数
  - None = 该年报/招股书未拆此科目 (CSV 留空)
  - 2020 年报"其他应收款"独立列示;2022 年报及以后合并入"预付款项及其他应收款项"

上市背景:
  - 2020-12-11 港交所上市, 发行价 HKD38.5 × 135,715,200 新股, 净募集 RMB50.7 亿
  - 2020 融资活动净额巨大(+48.7 亿)是上市募资, 非经营常态
  - 招股书聆讯後资料集 2020-11-22 递交 · 2020-12-11 港交所披露 (announcementId=1208889245, 623 页)
"""
import csv
import os

YEARS = [2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025]
OUT = os.path.dirname(os.path.abspath(__file__))


# ====== 综合损益及其他全面收益表 ======
# 前三列(2017/2018/2019) = 招股书附录一 P I-4~5 综合全面收益表; 后六列 = 各年报
利润表 = [
    ("收益 Revenue",                                    [158074, 514511, 1683434, 2513471, 4490651, 4617324, 6301002, 13037749, 37120052]),
    ("销售成本 Cost of sales",                          [-82820, -216486, -593100, -919363, -1732027, -1962781, -2436931, -4329984, -10355136]),
    ("毛利 Gross profit",                               [75254, 298025, 1090334, 1594108, 2758624, 2654543, 3864071, 8707765, 26764916]),
    ("经销及销售开支 Distribution and selling expenses",[-51047, -125721, -363819, -630069, -1106078, -1470753, -2004706, -3650464, -8082433]),
    ("一般及行政开支 G&A expenses",                     [-20897, -43599, -142468, -279967, -557509, -686280, -707300, -947093, -1770114]),
    ("金融资产减值(-)/拨回(+) Impairment of financial assets", [-344, -270, -3086, 398, -1435, -4500, -745, -3446, -11805]),
    ("其他收入 Other income",                            [1362, 5484, 17013, 45420, 54425, 45572, 74900, 84288, 149921]),
    ("其他收益/(亏损)-净 Other gains/(losses)-net",     [51, -305, 820, -11107, 1785, 44798, 4426, -36778, -160011]),
    ("经营溢利 Operating profit",                       [4379, 133614, 598794, 718783, 1149812, 583380, 1230646, 4154272, 16890474]),
    ("财务收入 Finance income",                          [9, 142, 424, 1953, 28609, 67682, 184217, 212335, 158966]),
    ("财务开支 Finance expenses",                       [-1764, -2455, -5813, -10946, -21246, -38579, -32337, -48983, -82471]),
    ("可换股优先股公平值变动 FVC of convertible pref shares", [None, None, None, -6260, None, None, None, None, None]),
    ("权益法投资溢利 Share of profit from equity method",[-351, 959, 4970, 3873, 14016, 27046, 33229, 48188, 69653]),
    ("除所得税前溢利 Profit before income tax",         [2273, 132260, 598375, 707403, 1171191, 639529, 1415755, 4365812, 17036622]),
    ("所得税开支 Income tax expense",                   [-704, -32739, -147257, -184091, -316624, -163728, -326984, -1057467, -4024580]),
    ("年内溢利 Profit for the year",                    [1569, 99521, 451118, 523312, 854567, 475801, 1088771, 3308345, 13012042]),
    ("归母溢利 Attributable to parent",                 [1569, 99521, 451118, 523505, 854339, 475660, 1082344, 3125473, 12775689]),
    ("非控股权益溢利 Non-controlling interests",        [0, 0, 0, -193, 228, 141, 6427, 182872, 236353]),
    ("经调整净利(Non-IFRS) Adjusted net profit",         [1671, 100303, 469123, 591000, 1001635, 573540, 1190519, 3403162, 13083646]),
    ("每股基本盈利(元) Basic EPS RMB",                 [0.01, 0.86, 3.91, 0.44, 0.62, 0.35, 0.79, 2.28, 9.32]),
]


# ====== 综合资产负债表 (全部正数呈现) ======
# 前三列(2017/2018/2019) = 招股书附录一 P I-6~7 综合资产负债表(经审计,完整拆分版); 后六列 = 各年报
# ⚠️ 修正: 招股书概要 P14 里"应付授权费"是合并值(非流动+流动), 之前误当"流动"填入; 附录一给出拆分版
# ⚠️ 修正: 招股书概要 P14 里"租赁负债"也是合并值, 附录一给出流动/非流动拆分
资产负债表 = [
    # ---- 非流动资产 ----
    ("物业厂房设备 PPE",                                [12096, 35874, 103559, 238325, 366281, 448884, 653278, 739378, 1417556]),
    ("无形资产 Intangible assets",                     [2580, 17641, 18620, 92731, 134032, 146507, 115888, 135400, 208665]),
    ("使用权资产 Right-of-use assets",                 [35078, 70816, 178938, 287799, 609517, 701627, 726053, 927558, 2791171]),
    ("权益法投资 Equity method investments",            [10839, 11798, 22101, 50380, 61539, 83333, 107001, 136783, 128124]),
    ("FVTPL金融资产(非流动) Financial assets FVTPL non-current", [None, None, None, 16900, 328688, 459034, 471769, 411880, 356906]),
    ("预付款项及其他非流动资产 Prepayments non-current",[316, 3903, 10443, 6177, 30727, 44165, 127989, 136563, 274473]),
    ("受限现金(非流动) Restricted cash non-current",   [None, None, None, None, None, None, None, None, 256265]),
    ("递延所得税资产 Deferred income tax assets",       [15569, 7766, 16219, 23087, 35553, 80977, 83416, 147029, 1753551]),
    ("非流动资产合计 Total non-current assets",         [76478, 147798, 349880, 715399, 1566337, 1964527, 2285394, 2634591, 7186711]),
    # ---- 流动资产 ----
    ("贸易应收款 Trade receivables",                    [5489, 14295, 45636, 78334, 171334, 194369, 321337, 477723, 921240]),
    ("其他应收款 Other receivables (独立列示)",          [11279, 23759, 59696, 90781, 154939, 187831, None, None, None]),
    ("存货 Inventories",                                [15540, 29061, 96302, 225369, 788829, 866985, 904708, 1524521, 5472839]),
    ("预付款项及其他流动资产 Prepayments other current",[19901, 40777, 140353, 177918, 353580, 298722, 467561, 576594, 1283154]),
    ("FVTPL金融资产(流动) Financial assets FVTPL current", [None, 50303, 50000, None, 20544, 12829, 8415, 11434, 9743]),
    ("受限现金(流动) Restricted cash current",         [None, None, None, 3263, 3353, 13265, 18159, 25649, 2658]),
    ("定期存款(3-12个月) Term deposits 3-12M",         [None, None, None, None, None, 4356220, 3885362, 3511143, 3449922]),
    ("现金及等价物 Cash and cash equivalents",           [13592, 96802, 324614, 5680235, 5264710, 685314, 2077927, 6109017, 13775087]),
    ("流动资产合计 Total current assets",                [65801, 254997, 716601, 6255900, 6757289, 6615535, 7683469, 12236081, 24914643]),
    # ---- 总资产 ----
    ("总资产 Total assets",                             [142279, 402795, 1066481, 6971299, 8323626, 8580062, 9968863, 14870672, 32101354]),
    # ---- 权益 ----
    ("股本 Share capital",                              [0, 0, 82, 923, 923, 908, 885, 882, 882]),
    ("股份奖励计划持股 Shares held for share award",     [None, None, None, -16, -15, -14, -12, -9, -7]),
    ("其他储备 Other reserves",                         [75889, 126800, 169631, 5189115, 5023583, 4693043, 4438448, 4280527, 3123058]),
    ("保留盈利 Retained earnings",                      [2935, 92030, 423068, 939352, 1793691, 2269351, 3330606, 6402105, 19153802]),
    ("归母权益 Equity attributable to parent",          [78824, 218830, 592781, 6129374, 6818182, 6963288, 7769927, 10683505, 22277735]),
    ("非控股权益 Non-controlling interests",            [0, 0, 0, 1628, 1824, 2037, 10455, 201134, 374632]),
    ("总权益 Total equity",                             [78824, 218830, 592781, 6131002, 6820006, 6965325, 7780382, 10884639, 22652367]),
    # ---- 非流动负债 ----
    ("应付授权费(非流动) License fees payables non-current",[0, 3804, 1318, 27934, 46371, 21306, 14807, 14536, 5525]),
    ("租赁负债(非流动) Lease liabilities non-current",   [19436, 35287, 90812, 147050, 364543, 447564, 425954, 601469, 2275301]),
    ("递延所得税负债 Deferred income tax liabilities",  [None, None, None, None, None, 15120, 14419, None, None]),
    ("非流动负债合计 Total non-current liabilities",    [19436, 39091, 92130, 174984, 410914, 483990, 455180, 616005, 2280826]),
    # ---- 流动负债 ----
    ("贸易应付款 Trade payables",                       [6359, 29256, 49406, 115804, 266098, 259006, 444944, 1010109, 1858216]),
    ("应付授权费(流动) License fees payables current",  [773, 3377, 15177, 58880, 86004, 133517, 179393, 341835, 437247]),
    ("其他应付款 Other payables",                       [16599, 49746, 122050, 202297, 266902, 308791, 514841, 904274, 1777317]),
    ("合约负债(预收) Contract liabilities",             [695, 10039, 35167, 83941, 119624, 88797, 112143, 188577, 393119]),
    ("借款(流动) Borrowing current",                    [None, None, None, None, None, None, 15058, None, None]),
    ("租赁负债(流动) Lease liabilities current",       [19296, 40011, 92586, 144724, 256909, 293567, 351799, 363092, 586274]),
    ("即期所得税负债 Current income tax liabilities",   [297, 12445, 67184, 59667, 97169, 47069, 115123, 562141, 2115988]),
    ("流动负债合计 Total current liabilities",          [44019, 144874, 381570, 665313, 1092706, 1130747, 1733301, 3370028, 7168161]),
    # ---- 总负债 & 总权益+负债 ----
    ("总负债 Total liabilities",                        [63455, 183965, 473700, 840297, 1503620, 1614737, 2188481, 3986033, 9448987]),
    ("总权益及负债 Total equity and liabilities",       [142279, 402795, 1066481, 6971299, 8323626, 8580062, 9968863, 14870672, 32101354]),
]


# ====== 综合现金流量表 ======
# 前三列(2017/2018/2019) = 招股书附录一 P I-13~14 综合现金流量表(经审计, 细分完整); 后六列 = 各年报
# ⚠️ 附录一"其他投资活动净" 2017 = 处置PPE 78; 2018 = 0; 2019 = 于合营企业投资 -2,746
# ⚠️ 附录一"其他融资活动净" 2017 = 0; 2018 = 一家集团公司当时股东注资 39,703; 2019 = 股东注资 168,554 + 视作分派 -168,093 + 上市开支 -272 = 189
现金流量表 = [
    # ---- 经营活动 ----
    ("经营所得现金 Cash generated from operations",     [15512, 187644, 603437, 899881, 1042075, 1133500, 2143208, 5415453, 14704780]),
    ("已收利息 Interest received",                      [10, 143, 424, 1953, 28609, 1656, 109457, 227247, 237628]),
    ("已付所得税 Income tax paid",                      [-15, -12787, -100972, -198476, -291587, -244134, -262069, -688480, -4077256]),
    ("经营活动所得现金净额 Net cash from operating",     [15507, 175000, 502889, 703358, 779097, 891022, 1990596, 4954220, 10865152]),
    # ---- 投资活动 ----
    ("购买 FVTPL 金融资产 Purchases of FVTPL assets",  [-37000, -140000, -255000, -230500, -1272757, -1515016, -812601, -4351977, -11344669]),
    ("购买物业厂房设备 Purchases of PPE",               [-11555, -35470, -104951, -175984, -287502, -266132, -324179, -372668, -985250]),
    ("购买无形资产 Purchases of intangibles",           [-2735, -15552, -12551, -47608, -46246, -81491, -68287, -144022, -186287]),
    ("处置 FVTPL 金融资产所得 Proceeds from FVTPL",     [42328, 90512, 256981, 281653, 950988, 1443524, 810236, 4386142, 11486858]),
    ("存入定期存款 Placement of term deposits",         [None, None, None, None, None, -4290194, -8528257, -4945685, -5593675]),
    ("赎回定期存款 Redemption of term deposits",        [None, None, None, None, None, None, 9140811, 5413742, 5576234]),
    ("其他投资活动净流入/(流出) Other investing net",   [78, 0, -2746, -45596, 7513, 10902, 15264, 22475, 57893]),
    ("投资活动所用/(所得)现金净额 Net cash from investing",[-8884, -100510, -118267, -216935, -648002, -4698408, 233940, 8957, -988896]),
    # ---- 融资活动 ----
    ("租赁负债付款 Payment of lease liabilities",       [-17602, -30985, -75773, -147995, -220126, -323041, -384999, -505104, -608288]),
    ("已付股息 Dividends paid",                         [0, 0, -80000, -377580, -208834, -220086, -121609, -378015, -1083288]),
    ("回购自身股份 Purchase of own shares",             [None, None, None, None, None, -634310, -333709, -78031, None]),
    ("上市所得款项(净) IPO net proceeds",                [None, None, None, 4910712, None, None, None, None, None]),
    ("其他融资活动净流出/(流入) Other financing net",   [0, 39703, 189, 485237, -6867, None, -1240, 2647, -75984]),
    ("融资活动所得/(所用)现金净额 Net cash from financing",[-17602, 8718, -155584, 4870374, -435827, -1177437, -841557, -958503, -1767352]),
    # ---- 现金总变动 ----
    ("现金及等价物增加/(减少)净额 Net increase in cash",[-10979, 83208, 229038, 5356797, -304732, -4984823, 1382979, 4004674, 8108904]),
    ("年初现金及等价物 Cash beginning",                 [24571, 13592, 96802, 324614, 5680235, 5264710, 685314, 2077927, 6109017]),
    ("汇兑损益 Exchange gains/(losses) on cash",        [0, 2, -1226, -1176, -110793, 405427, 9634, 26416, -442834]),
    ("年末现金及等价物 Cash end",                       [13592, 96802, 324614, 5680235, 5264710, 685314, 2077927, 6109017, 13775087]),
]


# ====== 勾稽自洽校验 (None-safe: 缺项则跳过该条勾稽,不当 0) ======
def value(table, key, idx):
    for row_key, row_vals in table:
        if row_key == key:
            return row_vals[idx]
    return None


def _need(*vs):
    return all(v is not None for v in vs)


def check():
    errors = []
    skipped = []
    for i, y in enumerate(YEARS):
        # 1) 损益: 毛利 = 收益 - 销售成本
        rev = value(利润表, "收益 Revenue", i)
        cost = value(利润表, "销售成本 Cost of sales", i)
        gp = value(利润表, "毛利 Gross profit", i)
        if _need(rev, cost, gp):
            if abs(rev + cost - gp) > 1:
                errors.append(f"[{y}] 毛利勾稽失败: 收益+成本={rev+cost}, 毛利={gp}, 差={rev+cost-gp}")

        # 2) 损益: 净利 = 除税前 + 所得税
        pretax = value(利润表, "除所得税前溢利 Profit before income tax", i)
        tax = value(利润表, "所得税开支 Income tax expense", i)
        pat = value(利润表, "年内溢利 Profit for the year", i)
        if _need(pretax, tax, pat):
            if abs(pretax + tax - pat) > 1:
                errors.append(f"[{y}] 净利勾稽失败: 税前{pretax}+税{tax}={pretax+tax}, 净利={pat}")

        # 3) 损益: 归母 + 非控股 = 净利
        parent = value(利润表, "归母溢利 Attributable to parent", i)
        nci = value(利润表, "非控股权益溢利 Non-controlling interests", i)
        if _need(parent, nci, pat):
            if abs(parent + nci - pat) > 1:
                errors.append(f"[{y}] 归母+非控股={parent+nci}, 净利={pat}")

        # 4) 资产: 总资产=非流动+流动
        nca = value(资产负债表, "非流动资产合计 Total non-current assets", i)
        ca = value(资产负债表, "流动资产合计 Total current assets", i)
        ta = value(资产负债表, "总资产 Total assets", i)
        if _need(nca, ca, ta):
            if abs(nca + ca - ta) > 1:
                errors.append(f"[{y}] 总资产勾稽失败: 非流动{nca}+流动{ca}={nca+ca}, 总资产={ta}")
        elif ta is not None:
            skipped.append(f"[{y}] #4(非流动+流动=总资产) skip")

        # 5) 负债: 总负债=非流动负债+流动负债
        ncl = value(资产负债表, "非流动负债合计 Total non-current liabilities", i)
        cl = value(资产负债表, "流动负债合计 Total current liabilities", i)
        tl = value(资产负债表, "总负债 Total liabilities", i)
        if _need(ncl, cl, tl):
            if abs(ncl + cl - tl) > 1:
                errors.append(f"[{y}] 总负债勾稽失败: 非流动{ncl}+流动{cl}={ncl+cl}, 总负债={tl}")
        elif tl is not None:
            skipped.append(f"[{y}] #5(非流动负债+流动负债=总负债) skip")

        # 6) 权益: 归母 + 非控股 = 总权益
        eq_parent = value(资产负债表, "归母权益 Equity attributable to parent", i)
        eq_nci = value(资产负债表, "非控股权益 Non-controlling interests", i)
        te = value(资产负债表, "总权益 Total equity", i)
        if _need(eq_parent, eq_nci, te):
            if abs(eq_parent + eq_nci - te) > 1:
                errors.append(f"[{y}] 总权益勾稽失败: 归母{eq_parent}+非控股{eq_nci}={eq_parent+eq_nci}, 总权益={te}")

        # 7) 资产 = 负债 + 权益
        if _need(ta, tl, te):
            if abs(ta - tl - te) > 1:
                errors.append(f"[{y}] 资产=负债+权益 勾稽失败: 资产{ta} vs 负债+权益={tl+te}")

        # 8) 现金流: 年初+净变+汇率=年末
        beg = value(现金流量表, "年初现金及等价物 Cash beginning", i)
        net = value(现金流量表, "现金及等价物增加/(减少)净额 Net increase in cash", i)
        fx = value(现金流量表, "汇兑损益 Exchange gains/(losses) on cash", i)
        end = value(现金流量表, "年末现金及等价物 Cash end", i)
        if _need(beg, net, fx, end):
            if abs(beg + net + fx - end) > 1:
                errors.append(f"[{y}] 现金勾稽失败: 期初{beg}+净变{net}+汇率{fx}={beg+net+fx}, 期末{end}")

        # 9) 现金流: 经营+投资+融资=净变动
        op = value(现金流量表, "经营活动所得现金净额 Net cash from operating", i)
        inv = value(现金流量表, "投资活动所用/(所得)现金净额 Net cash from investing", i)
        fin = value(现金流量表, "融资活动所得/(所用)现金净额 Net cash from financing", i)
        if _need(op, inv, fin, net):
            if abs(op + inv + fin - net) > 1:
                errors.append(f"[{y}] 三大活动加总失败: 经营{op}+投资{inv}+融资{fin}={op+inv+fin}, 净变动{net}")

        # 10) CF 年末 vs BS 现金
        bs_cash = value(资产负债表, "现金及等价物 Cash and cash equivalents", i)
        if _need(end, bs_cash):
            if abs(end - bs_cash) > 1:
                errors.append(f"[{y}] CF年末现金{end} != BS现金{bs_cash}")

    return errors, skipped


# ====== 派生比率 (None-safe: 缺项则该比率留空) ======
def build_ratios():
    def get(t, k, i):
        for rk, rv in t:
            if rk == k:
                return rv[i]
        return None

    def rate(num, den, mul=1):
        if num is None or den is None or den == 0:
            return ""
        return round(num / den * mul, 2)

    def add(*vs):
        if any(v is None for v in vs):
            return None
        return sum(vs)

    rows = []
    for i, y in enumerate(YEARS):
        rev = get(利润表, "收益 Revenue", i)
        gp = get(利润表, "毛利 Gross profit", i)
        op = get(利润表, "经营溢利 Operating profit", i)
        pat = get(利润表, "年内溢利 Profit for the year", i)
        parent_pat = get(利润表, "归母溢利 Attributable to parent", i)
        adj_np = get(利润表, "经调整净利(Non-IFRS) Adjusted net profit", i)
        ds = get(利润表, "经销及销售开支 Distribution and selling expenses", i)
        ga = get(利润表, "一般及行政开支 G&A expenses", i)
        op_cf = get(现金流量表, "经营活动所得现金净额 Net cash from operating", i)
        capex_ppe = get(现金流量表, "购买物业厂房设备 Purchases of PPE", i)
        capex_intang = get(现金流量表, "购买无形资产 Purchases of intangibles", i)
        capex = add(capex_ppe, capex_intang)
        divid = get(现金流量表, "已付股息 Dividends paid", i)
        buyback = get(现金流量表, "回购自身股份 Purchase of own shares", i)
        ta = get(资产负债表, "总资产 Total assets", i)
        te = get(资产负债表, "总权益 Total equity", i)
        eq_parent = get(资产负债表, "归母权益 Equity attributable to parent", i)
        tl = get(资产负债表, "总负债 Total liabilities", i)
        ar = get(资产负债表, "贸易应收款 Trade receivables", i)
        inv = get(资产负债表, "存货 Inventories", i)
        ap = get(资产负债表, "贸易应付款 Trade payables", i)
        goods_cost = get(利润表, "销售成本 Cost of sales", i)
        goods_cost = -goods_cost if goods_cost is not None else None
        cash = get(资产负债表, "现金及等价物 Cash and cash equivalents", i)
        td = get(资产负债表, "定期存款(3-12个月) Term deposits 3-12M", i)
        cash_td = add(cash, td) if td is not None else cash
        ppe = get(资产负债表, "物业厂房设备 PPE", i)
        rou = get(资产负债表, "使用权资产 Right-of-use assets", i)
        intang = get(资产负债表, "无形资产 Intangible assets", i)
        contract_liab = get(资产负债表, "合约负债(预收) Contract liabilities", i)

        row = {
            "年份": y,
            "毛利率%": rate(gp, rev, 100),
            "经营利润率%": rate(op, rev, 100),
            "净利率%": rate(pat, rev, 100),
            "非IFRS经调整净利率%": rate(adj_np, rev, 100),
            "销售费用率%": rate(-ds if ds is not None else None, rev, 100),
            "管理费用率%": rate(-ga if ga is not None else None, rev, 100),
            "ROE-归母%(期末口径)": rate(parent_pat, eq_parent, 100),
            "资产负债率%": rate(tl, ta, 100),
            "现金含量(经营现金/净利)": rate(op_cf, pat),
            "资本开支(PPE+无形) k RMB": capex if capex is not None else "",
            "capex/净利%": rate(capex, pat, 100),
            "capex/经营现金%": rate(capex, op_cf, 100),
            "归母/净利%": rate(parent_pat, pat, 100),
            "应收周转天数": rate(ar, rev, 365),
            "存货周转天数": rate(inv, goods_cost, 365),
            "应付周转天数": rate(ap, goods_cost, 365),
            "现金+定存/总资产%": rate(cash_td, ta, 100),
            "存货/总资产%": rate(inv, ta, 100),
            "PPE/总资产%": rate(ppe, ta, 100),
            "使用权资产/总资产%": rate(rou, ta, 100),
            "无形资产/总资产%": rate(intang, ta, 100),
            "已付股息 k RMB": divid if divid is not None else "",
            "股份回购 k RMB": buyback if buyback is not None else "",
            "分红率%(归母)": rate(-divid if divid is not None else None, parent_pat, 100),
            "合约负债/营收%": rate(contract_liab, rev, 100),
            "应收/营收%": rate(ar, rev, 100),
        }
        rows.append(row)
    return rows


# ====== 写 CSV ======
def write_csv(name, table, header):
    path = os.path.join(OUT, name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([f"# 单位: 人民币千元 (RMB'000), 来源: 招股书附录一会计师报告(2017-2019,经审计) + 一手年报 PDF(2020-2025), 泡泡玛特(09992.HK)"])
        w.writerow(header)
        for row_key, row_vals in table:
            out_row = [row_key] + ["" if v is None else v for v in row_vals]
            w.writerow(out_row)


def write_ratios(rows):
    path = os.path.join(OUT, "财务比率.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["# 派生比率, 从三表算出, 单位见字段名; 空值 = 数据缺失无法算"])
        w.writerow(list(rows[0].keys()))
        for r in rows:
            w.writerow(r.values())


def main():
    errors, skipped = check()
    if errors:
        print("❌ 勾稽校验失败,不写出 CSV:")
        for e in errors:
            print(f"  {e}")
        return
    print(f"✅ 勾稽校验全部通过 ({len(YEARS)} 年 × 10 条勾稽 = 90 条)")
    if skipped:
        print(f"ℹ️  跳过 {len(skipped)} 条 (数据缺失, 非勾稽失败):")
        for s in skipped:
            print(f"    {s}")
    header = ["科目"] + [str(y) for y in YEARS]
    write_csv("利润表.csv", 利润表, header)
    write_csv("资产负债表.csv", 资产负债表, header)
    write_csv("现金流量表.csv", 现金流量表, header)
    rows = build_ratios()
    write_ratios(rows)
    print(f"已写出 4 个 CSV → {OUT}")


if __name__ == "__main__":
    main()
