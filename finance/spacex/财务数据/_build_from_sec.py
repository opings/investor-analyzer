#!/usr/bin/env python3
"""SpaceX (Space Exploration Technologies Corp., Nasdaq: SPCX) 三表建库

一手真源（均在 report/spacex/）：
  - 招股说明书-424B4-20260612.htm  SEC 424B4，2026-06-12 定价招股书
      F 页经审计年度三表 FY2023/2024/2025 + 附注（分部/商誉/PP&E/重组）
  - 2026-Q2.htm                    SEC 10-Q，2026-08-04，期间 2026-06-30（上市后首份定期报告）

口径要点（务必与 README.md 同步）：
  1. 报告主体 = SpaceX + xAI + X 的**追溯合并**结果。SpaceX 于 2026-02-02 收购 xAI，
     xAI 于 2025-03-28 收购 X Holdings，两笔均为同一控制下重组（Musk 控股），
     按历史账面价值追溯重述所有列报期间，且「constitutes a change in reporting entity」
     （招股书 F-11 Note 1）。故 2023-2025 序列**不是**历史上独立 SpaceX 的经营结果。
  2. 单位：百万美元（USD millions）。
  3. 符号约定：费用/减项 = 负数（与本库 google 等美股一致）。
  4. 股数/EPS 已按 2026-05-04 的 5:1 拆股追溯调整（招股书全文口径）。
  5. FY2023 资产负债表：招股书只列报 2025/2024 两年，2023 年末除少数附注项外不可得 → 留空。

写出前跑 CHECKS 全量勾稽，任一不过则 raise，不写出 CSV。
"""
import csv
import pathlib

OUT = pathlib.Path(__file__).parent
YEARS = [2023, 2024, 2025]

# ---------------------------------------------------------------- 利润表
# 源：招股书 F 页 Consolidated Statements of Operations（table idx 59）
INCOME = [
    ("营业收入 Revenue",                              [10387, 14015, 18674]),
    ("营业成本 Cost of revenue",                      [-6110, -7996, -9451]),
    ("研发开支 Research and development",             [-2105, -3464, -8643]),
    ("销售及行政管理 Selling, general and administrative", [-1665, -1813, -2644]),
    ("重组费用 Restructuring charges",                [-237, -213, -487]),
    ("减值 Impairment",                               [-3775, -63, -38]),
    ("总成本及开支 Total costs and expenses",          [-13892, -13549, -21263]),
    ("经营利润 Income (loss) from operations",         [-3505, 466, -2589]),
    ("利息支出 Interest expense",                     [-1693, -1580, -1945]),
    ("利息收入 Interest income",                      [249, 371, 492]),
    ("其他收入(支出)净额 Other income (expense) net",   [-42, 985, -177]),
    ("除税前利润 Income (loss) before income taxes",   [-4991, 242, -4219]),
    ("所得税 Provision for (benefit from) income taxes", [363, 549, -718]),
    ("净利润 Net income (loss)",                      [-4628, 791, -4937]),
    ("每股基本盈利(美元) Basic EPS",                   [-1.68, 0.01, -1.69]),
    ("每股摊薄盈利(美元) Diluted EPS",                 [-1.68, 0.00, -1.69]),
    ("基本加权平均股数(百万) Basic WAS",               [2759, 2848, 2926]),
    ("摊薄加权平均股数(百万) Diluted WAS",             [2759, 9956, 2926]),
]

# ---------------------------------------------------------- 资产负债表
# 源：招股书 F 页 Consolidated Balance Sheets（table idx 58），只列报 2025/2024
BALANCE = [
    ("货币资金 Cash and cash equivalents",            [None, 11385, 24747]),
    ("金融资产 Marketable securities",                [None, 800, 0]),
    ("应收账款净额 Accounts receivable net",           [None, 1052, 1579]),
    ("存货 Inventory",                                [None, 2003, 2416]),
    ("预付及其他流动资产 Prepaid and other current",    [None, 868, 2210]),
    ("流动资产合计 Total current assets",              [None, 16108, 30952]),
    ("固定资产净额 Property, plant and equipment net",  [None, 21147, 42602]),
    ("融资租赁使用权资产 Finance lease ROU assets",     [None, 1686, 1260]),
    ("无形资产净额 Intangible assets net",             [None, 2211, 1548]),
    ("数字资产 Digital assets",                       [None, 1749, 1637]),
    ("商誉 Goodwill",                                 [11418, 11129, 11809]),
    ("递延所得税资产 Deferred tax assets",             [None, 696, 141]),
    ("其他资产 Other assets",                         [None, 2336, 2130]),
    ("资产总计 Total assets",                         [None, 57062, 92079]),
    ("应付账款 Accounts payable",                     [None, 4413, 11792]),
    ("合同负债-流动 Deferred revenue current",         [None, 5498, 6111]),
    ("有息负债及租赁-流动 Debt and finance leases current", [None, 372, 928]),
    ("应计及其他流动负债 Accrued and other current",    [None, 1508, 2569]),
    ("流动负债合计 Total current liabilities",         [None, 11791, 21400]),
    ("合同负债-非流动 Deferred revenue non-current",    [None, 4681, 6005]),
    ("有息负债及租赁-非流动 Debt and finance leases non-current", [None, 13421, 21968]),
    ("其他非流动负债 Other liabilities",               [None, 1365, 1381]),
    ("负债合计 Total liabilities",                    [None, 31258, 50754]),
    ("可赎回可转换优先股 Redeemable convertible preferred stock", [None, 20941, 38752]),
    ("股东权益合计 Total shareholders' equity",        [None, 4863, 2573]),
    ("负债+优先股+权益 Total L, RCPS and equity",       [None, 57062, 92079]),
]

# ------------------------------------------------------ 现金流量表
# 源：招股书 F 页 Consolidated Statements of Cash Flows（table idx 62 + 63 续表）
CASHFLOW = [
    ("净利润 Net income (loss)",                      [-4628, 791, -4937]),
    ("折旧摊销 Depreciation and amortization",         [2635, 3824, 6701]),
    ("股权激励 Share-based compensation",              [679, 784, 1947]),
    ("无形资产减值 Intangible asset impairment",       [3775, 0, 0]),
    ("递延所得税 Deferred income taxes",               [-409, -675, 626]),
    ("数字资产未实现(收益)损失 Unrealized loss on digital assets", [0, -955, 112]),
    ("固定资产减值及处置损失 Impairment/loss on disposal of FA", [36, 135, 88]),
    ("债务折价及发行费摊销 Amortization of debt discount", [212, 84, 93]),
    ("其他 Other",                                    [214, 115, 66]),
    ("应收账款变动 Change in accounts receivable",      [345, -347, -543]),
    ("存货变动 Change in inventory",                   [-72, -309, -413]),
    ("预付及其他资产变动 Change in prepaid and other",   [41, -328, -673]),
    ("应付账款变动 Change in accounts payable",         [220, 472, 709]),
    ("合同负债变动 Change in deferred revenue",         [1695, 1876, 1929]),
    ("经营租赁负债变动 Operating lease liabilities net", [-15, -37, -56]),
    ("其他负债变动 Change in other liabilities",        [-208, 346, 1136]),
    ("经营活动现金流净额 Net cash from operating",       [4520, 5776, 6785]),
    ("购建固定资产 Purchases of PP&E (capex)",          [-4415, -11163, -20737]),
    ("资本化利息 Capitalized interest",                [0, 0, -169]),
    ("产品返利收到 Proceeds from product rebates",      [0, 0, 118]),
    ("购买金融资产 Purchases of marketable securities", [-3535, -3542, -611]),
    ("金融资产到期 Maturities of marketable securities", [2731, 3712, 548]),
    ("出售金融资产 Proceeds from sales of securities",  [333, 193, 1457]),
    ("对联营企业投资 Investments in unconsolidated affiliates", [0, 0, -86]),
    ("其他投资活动 Other investing activities net",     [19, 4, -95]),
    ("投资活动现金流净额 Net cash used in investing",    [-4867, -10796, -19575]),
    ("融资租赁本金偿还 Principal repayments finance leases", [0, -154, -295]),
    ("取得借款 Proceeds from debt",                    [0, 0, 16055]),
    ("债务发行费 Payment of debt issuance costs",       [0, 0, -66]),
    ("偿还借款 Repayments on debt",                    [-112, -77, -6858]),
    ("发行股本净额 Proceeds from issuance of capital stock", [774, 13101, 18807]),
    ("员工股权计划 Proceeds from employee equity plans", [141, 224, 328]),
    ("回购普通股及优先股 Repurchase of common and RCPS", [-170, -1021, -1125]),
    ("股权结算代扣税 Taxes paid on net share settlement", [-211, -243, -496]),
    ("融资活动现金流净额 Net cash from financing",       [422, 11830, 26350]),
    ("汇率影响 Effect of exchange rate changes",        [-2, 1, 63]),
    ("现金净变动 Net change in cash",                  [73, 6811, 13623]),
    ("期初现金及受限现金 Cash beginning of year",        [4617, 4690, 11501]),
    ("期末现金及受限现金 Cash end of year",             [4690, 11501, 25124]),
    ("已付利息(净额) Cash paid for interest net",       [1365, 1500, 1476]),
    ("已付所得税(净额) Cash paid for income taxes net", [45, 134, 154]),
    ("资本化股权激励 SBC capitalized in PP&E",          [108, 132, 154]),
    ("已购未付固定资产 PP&E in accounts payable",       [505, 2481, 7088]),
]

# ---------------------------------------------------------- 分部数据
# 源：招股书附注 Segment Information（table idx 110/111/112）+ 收入分解（idx 68）
#     中期分部来自 10-Q（table idx 47 = H1 2026, idx 49 = H1 2025）
SEG_COLS = ["2023", "2024", "2025", "2025H1", "2026H1"]
SEGMENT = [
    # ---- 收入分解（产品线）；H1 两列源自 10-Q「Revenue disaggregated by type and segment」
    ("Space-发射服务 Launch Services",        [1964, 2584, 2576, 1056, 978]),
    ("Space-发射及开发 Launch & Development",  [1593, 1212, 1510, 555, 603]),
    ("Connectivity-消费者 Consumer",          [2817, 4830, 7208, 3213, 4633]),
    ("Connectivity-企业及政府 Enterprise & Gov", [1052, 2769, 4179, 1849, 2915]),
    ("AI-广告 Advertising",                   [2323, 1728, 1844, 870, 710]),
    ("AI-AI方案及算力 AI Solutions & Infra",   [638, 892, 1357, 595, 2669]),
    # ---- 区域收入（招股书 F-59 附注）
    # ⚠️ 口径 = 「交易发起地的**注册地(country of domicile)**」，**不是用户所在地**；
    #    且为**合并口径**(Space+Connectivity+AI)，非 Starlink 单独。爱尔兰大概率是 EMEA 计费主体所在地。
    #    10-Q 未披露地理拆分，故 H1 两列留空。长期资产：2024/2025 年末「基本全部位于美国」。
    ("[区域收入] 美国 USA",                    [7473, 10008, 12966, None, None]),
    ("[区域收入] 爱尔兰 Ireland",               [1047, 1371, 1827, None, None]),
    ("[区域收入] 加拿大 Canada",                [447, 582, 764, None, None]),
    ("[区域收入] 其他 All Other",               [1420, 2054, 3117, None, None]),
    ("[区域收入] 合计 Total",                   [10387, 14015, 18674, None, None]),
    # ---- 分部收入
    ("[收入] Space",                          [3557, 3796, 4086, 1611, 1581]),
    ("[收入] Connectivity",                   [3869, 7599, 11387, 5062, 7548]),
    ("[收入] AI",                             [2961, 2620, 3201, 1465, 3379]),
    ("[收入] 合计 Total",                     [10387, 14015, 18674, 8138, 12508]),
    # ---- 分部经营利润
    ("[经营利润] Space",                      [-1, 21, -657, -439, -1204]),
    ("[经营利润] Connectivity",               [469, 2006, 4423, 1956, 2844]),
    ("[经营利润] AI",                         [-3973, -1561, -6355, -2460, -3726]),
    ("[经营利润] 合计 Total",                 [-3505, 466, -2589, -943, -2086]),
    # ---- 分部资本开支
    ("[资本开支] Space",                      [1497, 2032, 3832, 1705, 2226]),
    ("[资本开支] Connectivity",               [2455, 3498, 4178, 1944, 2699]),
    ("[资本开支] AI",                         [463, 5633, 12727, 3316, 23551]),
    ("[资本开支] 合计 Total",                 [4415, 11163, 20737, 6965, 28476]),
    # ---- 分部折旧摊销
    ("[折旧摊销] Space",                      [571, 637, 757, 308, 324]),
    ("[折旧摊销] Connectivity",               [884, 1508, 2376, 1078, 1588]),
    ("[折旧摊销] AI",                         [1180, 1679, 3568, 1584, 3378]),
    ("[折旧摊销] 合计 Total",                 [2635, 3824, 6701, 2970, 5290]),
    # ---- 分部股权激励
    ("[股权激励] Space",                      [427, 472, 515, 233, 324]),
    ("[股权激励] Connectivity",               [249, 296, 369, 166, 252]),
    ("[股权激励] AI",                         [3, 16, 1063, 295, 894]),
    ("[股权激励] 合计 Total",                 [679, 784, 1947, 694, 1470]),
]

# ------------------------------------------------------ 2026 中期财务
# 源：10-Q（2026-08-04），三表 H1 2026 vs H1 2025 + 时点资产负债表
INTERIM_COLS = ["2025H1", "2026H1"]
INTERIM_IS = [
    ("营业收入 Revenue",                              [8138, 12508]),
    ("营业成本 Cost of revenue",                      [-4244, -5883]),
    ("研发开支 Research and development",             [-3515, -7062]),
    ("销售及行政管理 SG&A",                           [-1099, -1658]),
    ("重组费用(冲回) Restructuring charges (credits)", [-194, 9]),
    ("减值 Impairment",                               [-29, 0]),
    ("总成本及开支 Total costs and expenses",          [-9081, -14594]),
    ("经营利润 Loss from operations",                 [-943, -2086]),
    ("利息支出 Interest expense",                     [-858, -1293]),
    ("利息收入 Interest income",                      [215, 553]),
    ("其他收入(支出)净额 Other income (expense) net",   [202, -1962]),
    ("除税前利润 Loss before income taxes",           [-1384, -4788]),
    ("所得税 Provision for income taxes",             [-152, -29]),
    ("净利润 Net loss",                               [-1536, -4817]),
    ("归属股东净利润 Net loss attributable to shareholders", [-1536, -5488]),
    ("每股基本及摊薄盈利(美元) Basic and diluted EPS",  [-0.53, -1.12]),
    ("加权平均股数(百万) Weighted average shares",     [2902, 4879]),
]
INTERIM_CF = [
    ("经营活动现金流净额 Net cash from operating",      [351, 3466]),
    ("购建固定资产 Capex",                            [-6965, -28476]),
    ("投资活动现金流净额 Net cash used in investing",   [-6032, -34487]),
    ("取得借款 Proceeds from debt",                   [10943, 51812]),
    ("偿还借款 Repayments on debt",                   [-5990, -39396]),
    ("债务清偿溢价 Payment of debt extinguishment premium", [0, -1153]),
    ("发行股本净额 Proceeds from issuance of capital stock", [5047, 8319]),
    ("回购普通股及优先股 Repurchase of common and RCPS", [-520, -4426]),
    ("IPO募资净额 Proceeds from IPO net",              [0, 85675]),
    ("融资活动现金流净额 Net cash from financing",      [9199, 100291]),
    ("现金净变动 Net change in cash",                  [3593, 69228]),
    ("期末现金及受限现金 Cash end of period",           [15094, 94352]),
    ("自由现金流 FCF = OCF - Capex",                  [-6614, -25010]),
]
# 时点数（资产负债表）：2025-12-31 vs 2026-06-30
INTERIM_BS_COLS = ["2025-12-31", "2026-06-30"]
INTERIM_BS = [
    ("货币资金 Cash and cash equivalents",            [24747, 93522]),
    ("金融资产 Marketable securities",                [0, 6487]),
    ("应收账款净额 Accounts receivable net",           [1579, 3596]),
    ("存货 Inventory",                                [2416, 2718]),
    ("预付及其他流动资产 Prepaid and other current",    [2210, 1724]),
    ("流动资产合计 Total current assets",              [30952, 108047]),
    ("固定资产净额 PP&E net",                         [42602, 65736]),
    ("融资租赁使用权资产 Finance lease ROU",           [1260, 1118]),
    ("无形资产净额 Intangible assets net",             [1548, 1318]),
    ("数字资产 Digital assets",                       [1637, 1098]),
    ("商誉 Goodwill",                                 [11809, 11645]),
    ("递延所得税资产 Deferred tax assets",             [141, 354]),
    ("其他资产 Other assets",                         [2130, 3454]),
    ("资产总计 Total assets",                         [92079, 192770]),
    ("应付账款 Accounts payable",                     [11792, 8243]),
    ("合同负债-流动 Deferred revenue current",         [6111, 7977]),
    ("有息负债及租赁-流动 Debt and leases current",     [928, 2525]),
    ("应计及其他流动负债 Accrued and other current",    [2569, 2377]),
    ("流动负债合计 Total current liabilities",         [21400, 21122]),
    ("合同负债-非流动 Deferred revenue non-current",    [6005, 6309]),
    ("有息负债及租赁-非流动 Debt and leases non-current", [21968, 36839]),
    ("其他非流动负债 Other liabilities",               [1381, 1276]),
    ("负债合计 Total liabilities",                    [50754, 65546]),
    ("可赎回可转换优先股 Redeemable convertible preferred", [38752, 0]),
    ("股东权益合计 Total shareholders' equity",        [2573, 127224]),
    ("负债+优先股+权益 Total L, RCPS and equity",       [92079, 192770]),
    ("其中:关联方有息负债 Related-party debt (incl.)",  [4507, 13329]),
]

# ------------------------------------------------------ 固定资产明细
# 源：招股书 PP&E 附注（table idx 71，2024/2025）+ 10-Q Note 5（2026-06-30）
# 均为**原值（gross）**，累计折旧单列；净额须与资产负债表「固定资产净额」一致
PPE_COLS = ["2024-12-31", "2025-12-31", "2026-06-30"]
PPE = [
    ("服务器及网络设备 Servers and networking equipment", [6892, 22694, 34771]),
    ("卫星 Satellites",                                  [7591, 11949, 13788]),
    ("机器设备 Machinery and equipment",                  [5343, 6343, 9453]),
    ("数据中心基础设施 Data center infrastructure",        [224, 2960, 3991]),
    ("发射场 Launch sites",                              [2121, 2404, 3118]),
    ("土地房屋及改良 Land, buildings and improvements",     [913, 1876, 2958]),
    ("飞行器硬件 Flight vehicle hardware",                [1577, 1689, 1557]),
    ("租赁资产改良 Leasehold improvements",               [1019, 784, 881]),
    ("在建工程 Construction-in-progress",                 [3007, 4604, 12554]),
    ("固定资产原值 Gross PP&E",                          [28687, 55303, 83071]),
    ("减:累计折旧 Accumulated depreciation",              [-7540, -12701, -17335]),
    ("固定资产净额 Net PP&E",                            [21147, 42602, 65736]),
]

# ---------------------------------------------------------- 经营指标
# 源：招股书「Key Business Metrics」（入轨质量/发射/ARPU）+ 10-Q 同名章节
OPS_Y = [
    ("入轨质量-合计(公吨) Mass to orbit total",       [1210, 1699, 2213]),
    ("入轨质量-客户载荷(公吨) customer payloads",      [205, 282, 312]),
    ("入轨质量-内部载荷(公吨) internal payloads",      [1005, 1418, 1901]),
    ("客户载荷占入轨质量比 customer share",            [None, None, None]),  # 派生，下方填
    ("Falcon 9 发射次数 Falcon 9 launches",           [None, None, 165]),
    ("其中复用助推器发射 flight-proven",               [None, None, 157]),
    ("Starlink ARPU(美元/月) Starlink ARPU",          [None, 91, 81]),
]
# 中期/季度（期末时点数标注「期末」）
OPS_I_COLS = ["2025Q1", "2025Q2", "2025H1", "2026Q1", "2026Q2", "2026H1"]
OPS_I = [
    ("Starlink 订阅数(百万,期末) Starlink subscribers", [5.0, 6.0, 6.0, 10.3, 12.0, 12.0]),
    ("Starlink ARPU(美元/月) Starlink ARPU",           [86, 85, 85, 66, 66, 66]),
    ("Falcon 发射次数 Falcon launches",                [36, 45, 81, 40, 37, 77]),
    ("其中客户发射 customer launches",                 [12, 9, 21, 7, 10, 17]),
    ("其中内部发射 internal launches",                 [24, 36, 60, 33, 27, 60]),
    ("Starship 发射次数 Starship launches",            [2, 1, 3, 0, 1, 1]),
    ("入轨质量(公吨) Mass to orbit",                   [450, None, None, 556, None, None]),
    ("算力铭牌功率(GW,期末) Nameplate compute draw",    [None, 0.4, 0.4, 1.0, 1.4, 1.4]),
]

D = {name: vals for name, vals in INCOME}
B = {name: vals for name, vals in BALANCE}
C = {name: vals for name, vals in CASHFLOW}
S = {name: vals for name, vals in SEGMENT}


# ---------------------------------------------------------------- 勾稽校验
def checks():
    errs = []

    def eq(label, a, b, tol=1):
        if a is None or b is None:
            return
        if abs(a - b) > tol:
            errs.append(f"{label}: {a} != {b} (差 {a - b})")

    for i, y in enumerate(YEARS):
        # 利润表：分项加总 = 总成本
        parts = sum(D[k][i] for k in (
            "营业成本 Cost of revenue", "研发开支 Research and development",
            "销售及行政管理 Selling, general and administrative",
            "重组费用 Restructuring charges", "减值 Impairment"))
        eq(f"{y} 总成本及开支", parts, D["总成本及开支 Total costs and expenses"][i])
        # 营收 - 总成本 = 经营利润
        eq(f"{y} 经营利润", D["营业收入 Revenue"][i] + D["总成本及开支 Total costs and expenses"][i],
           D["经营利润 Income (loss) from operations"][i])
        # 经营利润 + 利息 + 其他 = 税前
        eq(f"{y} 除税前利润",
           D["经营利润 Income (loss) from operations"][i] + D["利息支出 Interest expense"][i]
           + D["利息收入 Interest income"][i] + D["其他收入(支出)净额 Other income (expense) net"][i],
           D["除税前利润 Income (loss) before income taxes"][i])
        # 税前 + 所得税 = 净利
        eq(f"{y} 净利润", D["除税前利润 Income (loss) before income taxes"][i]
           + D["所得税 Provision for (benefit from) income taxes"][i],
           D["净利润 Net income (loss)"][i])
        # 利润表净利 = 现金流量表起点
        eq(f"{y} 三表衔接 净利", D["净利润 Net income (loss)"][i], C["净利润 Net income (loss)"][i])

        # 资产负债表恒等式
        if B["资产总计 Total assets"][i] is not None:
            eq(f"{y} 流动资产合计", sum(B[k][i] for k in (
                "货币资金 Cash and cash equivalents", "金融资产 Marketable securities",
                "应收账款净额 Accounts receivable net", "存货 Inventory",
                "预付及其他流动资产 Prepaid and other current")),
               B["流动资产合计 Total current assets"][i])
            eq(f"{y} 资产总计", sum(B[k][i] for k in (
                "流动资产合计 Total current assets", "固定资产净额 Property, plant and equipment net",
                "融资租赁使用权资产 Finance lease ROU assets", "无形资产净额 Intangible assets net",
                "数字资产 Digital assets", "商誉 Goodwill",
                "递延所得税资产 Deferred tax assets", "其他资产 Other assets")),
               B["资产总计 Total assets"][i])
            eq(f"{y} 流动负债合计", sum(B[k][i] for k in (
                "应付账款 Accounts payable", "合同负债-流动 Deferred revenue current",
                "有息负债及租赁-流动 Debt and finance leases current",
                "应计及其他流动负债 Accrued and other current")),
               B["流动负债合计 Total current liabilities"][i])
            eq(f"{y} 负债合计", sum(B[k][i] for k in (
                "流动负债合计 Total current liabilities", "合同负债-非流动 Deferred revenue non-current",
                "有息负债及租赁-非流动 Debt and finance leases non-current",
                "其他非流动负债 Other liabilities")),
               B["负债合计 Total liabilities"][i])
            eq(f"{y} 资产=负债+优先股+权益",
               B["负债合计 Total liabilities"][i]
               + B["可赎回可转换优先股 Redeemable convertible preferred stock"][i]
               + B["股东权益合计 Total shareholders' equity"][i],
               B["资产总计 Total assets"][i])

        # 现金流量表三段 + 汇率 = 净变动
        eq(f"{y} 现金净变动", sum(C[k][i] for k in (
            "经营活动现金流净额 Net cash from operating",
            "投资活动现金流净额 Net cash used in investing",
            "融资活动现金流净额 Net cash from financing",
            "汇率影响 Effect of exchange rate changes")),
           C["现金净变动 Net change in cash"][i])
        eq(f"{y} 期初+净变=期末", C["期初现金及受限现金 Cash beginning of year"][i]
           + C["现金净变动 Net change in cash"][i], C["期末现金及受限现金 Cash end of year"][i])

    # 现金流量表年度衔接
    for i in range(len(YEARS) - 1):
        eq(f"{YEARS[i]}期末=={YEARS[i+1]}期初", C["期末现金及受限现金 Cash end of year"][i],
           C["期初现金及受限现金 Cash beginning of year"][i + 1])

    # 分部：三分部加总 = 合计；产品线加总 = 分部收入
    for j, col in enumerate(SEG_COLS):
        for metric in ("[收入]", "[经营利润]", "[资本开支]", "[折旧摊销]", "[股权激励]"):
            parts = [S[f"{metric} {seg}"][j] for seg in ("Space", "Connectivity", "AI")]
            if any(p is None for p in parts):
                continue
            eq(f"{col} {metric} 分部加总", sum(parts), S[f"{metric} 合计 Total"][j])
    # 区域收入：四项加总 = 合计 = 利润表营收（只有年度三列）
    for j in range(3):
        eq(f"{SEG_COLS[j]} 区域收入加总", sum(S[f"[区域收入] {k}"][j] for k in (
            "美国 USA", "爱尔兰 Ireland", "加拿大 Canada", "其他 All Other")),
           S["[区域收入] 合计 Total"][j])
        eq(f"{SEG_COLS[j]} 区域收入==利润表", S["[区域收入] 合计 Total"][j], D["营业收入 Revenue"][j])

    for j in range(len(SEG_COLS)):  # 产品线：年度 3 列 + H1 2 列
        eq(f"{SEG_COLS[j]} Space 产品线加总",
           S["Space-发射服务 Launch Services"][j] + S["Space-发射及开发 Launch & Development"][j],
           S["[收入] Space"][j])
        eq(f"{SEG_COLS[j]} Connectivity 产品线加总",
           S["Connectivity-消费者 Consumer"][j] + S["Connectivity-企业及政府 Enterprise & Gov"][j],
           S["[收入] Connectivity"][j])
        eq(f"{SEG_COLS[j]} AI 产品线加总",
           S["AI-广告 Advertising"][j] + S["AI-AI方案及算力 AI Solutions & Infra"][j],
           S["[收入] AI"][j])

    # 分部收入/经营利润/资本开支/折旧 == 利润表&现金流量表
    for j, i in ((0, 0), (1, 1), (2, 2)):
        eq(f"{YEARS[i]} 分部收入==利润表", S["[收入] 合计 Total"][j], D["营业收入 Revenue"][i])
        eq(f"{YEARS[i]} 分部经营利润==利润表", S["[经营利润] 合计 Total"][j],
           D["经营利润 Income (loss) from operations"][i])
        eq(f"{YEARS[i]} 分部资本开支==现金流量表", -S["[资本开支] 合计 Total"][j],
           C["购建固定资产 Purchases of PP&E (capex)"][i])
        eq(f"{YEARS[i]} 分部折旧==现金流量表", S["[折旧摊销] 合计 Total"][j],
           C["折旧摊销 Depreciation and amortization"][i])
        eq(f"{YEARS[i]} 分部股权激励==现金流量表", S["[股权激励] 合计 Total"][j],
           C["股权激励 Share-based compensation"][i])

    # 中期：H1 利润表内部自洽 + 与分部/年报衔接
    ii = {k: v for k, v in INTERIM_IS}
    ic = {k: v for k, v in INTERIM_CF}
    ib = {k: v for k, v in INTERIM_BS}
    for j, col in enumerate(INTERIM_COLS):
        eq(f"{col} 总成本及开支", sum(ii[k][j] for k in (
            "营业成本 Cost of revenue", "研发开支 Research and development",
            "销售及行政管理 SG&A", "重组费用(冲回) Restructuring charges (credits)",
            "减值 Impairment")), ii["总成本及开支 Total costs and expenses"][j])
        eq(f"{col} 经营利润", ii["营业收入 Revenue"][j] + ii["总成本及开支 Total costs and expenses"][j],
           ii["经营利润 Loss from operations"][j])
        eq(f"{col} 除税前利润", ii["经营利润 Loss from operations"][j] + ii["利息支出 Interest expense"][j]
           + ii["利息收入 Interest income"][j] + ii["其他收入(支出)净额 Other income (expense) net"][j],
           ii["除税前利润 Loss before income taxes"][j])
        eq(f"{col} 净利润", ii["除税前利润 Loss before income taxes"][j]
           + ii["所得税 Provision for income taxes"][j], ii["净利润 Net loss"][j])
        eq(f"{col} FCF", ic["经营活动现金流净额 Net cash from operating"][j]
           + ic["购建固定资产 Capex"][j], ic["自由现金流 FCF = OCF - Capex"][j])
        # 中期收入/经营利润 == 分部表
        seg_j = 3 + j
        eq(f"{col} 收入==分部", ii["营业收入 Revenue"][j], S["[收入] 合计 Total"][seg_j])
        eq(f"{col} 经营利润==分部", ii["经营利润 Loss from operations"][j],
           S["[经营利润] 合计 Total"][seg_j])
        eq(f"{col} 资本开支==分部", -ic["购建固定资产 Capex"][j], S["[资本开支] 合计 Total"][seg_j])

    # 中期资产负债表恒等式
    for j in range(2):
        eq(f"{INTERIM_BS_COLS[j]} 流动资产合计", sum(ib[k][j] for k in (
            "货币资金 Cash and cash equivalents", "金融资产 Marketable securities",
            "应收账款净额 Accounts receivable net", "存货 Inventory",
            "预付及其他流动资产 Prepaid and other current")),
           ib["流动资产合计 Total current assets"][j])
        eq(f"{INTERIM_BS_COLS[j]} 资产总计", sum(ib[k][j] for k in (
            "流动资产合计 Total current assets", "固定资产净额 PP&E net",
            "融资租赁使用权资产 Finance lease ROU", "无形资产净额 Intangible assets net",
            "数字资产 Digital assets", "商誉 Goodwill",
            "递延所得税资产 Deferred tax assets", "其他资产 Other assets")),
           ib["资产总计 Total assets"][j])
        eq(f"{INTERIM_BS_COLS[j]} 资产=负债+优先股+权益",
           ib["负债合计 Total liabilities"][j]
           + ib["可赎回可转换优先股 Redeemable convertible preferred"][j]
           + ib["股东权益合计 Total shareholders' equity"][j],
           ib["资产总计 Total assets"][j])

    # 跨源：10-Q 的 2025-12-31 列 == 招股书 FY2025 年报列
    for k_bs, k_ann in (
        ("货币资金 Cash and cash equivalents", "货币资金 Cash and cash equivalents"),
        ("资产总计 Total assets", "资产总计 Total assets"),
        ("负债合计 Total liabilities", "负债合计 Total liabilities"),
        ("股东权益合计 Total shareholders' equity", "股东权益合计 Total shareholders' equity"),
        ("商誉 Goodwill", "商誉 Goodwill"),
    ):
        eq(f"跨源 2025-12-31 {k_bs}", ib[k_bs][0], B[k_ann][2])
    # 跨源：招股书 FY2025 期末现金+受限 vs 10-Q H1 期初
    eq("跨源 2026 期初现金", C["期末现金及受限现金 Cash end of year"][2], 25124)

    # 固定资产明细：九项加总 = 原值；原值 − 累计折旧 = 净额；净额跨表 == 资产负债表
    pp = {k: v for k, v in PPE}
    for j, col in enumerate(PPE_COLS):
        eq(f"{col} 固定资产原值分项加总", sum(pp[k][j] for k in (
            "服务器及网络设备 Servers and networking equipment", "卫星 Satellites",
            "机器设备 Machinery and equipment", "数据中心基础设施 Data center infrastructure",
            "发射场 Launch sites", "土地房屋及改良 Land, buildings and improvements",
            "飞行器硬件 Flight vehicle hardware", "租赁资产改良 Leasehold improvements",
            "在建工程 Construction-in-progress")), pp["固定资产原值 Gross PP&E"][j])
        eq(f"{col} 原值−累计折旧=净额",
           pp["固定资产原值 Gross PP&E"][j] + pp["减:累计折旧 Accumulated depreciation"][j],
           pp["固定资产净额 Net PP&E"][j])
    # 跨表：固定资产净额 == 资产负债表 / 中期资产负债表
    eq("跨表 2024 固定资产净额", pp["固定资产净额 Net PP&E"][0],
       B["固定资产净额 Property, plant and equipment net"][1])
    eq("跨表 2025 固定资产净额", pp["固定资产净额 Net PP&E"][1],
       B["固定资产净额 Property, plant and equipment net"][2])
    eq("跨表 2026-06-30 固定资产净额", pp["固定资产净额 Net PP&E"][2], ib["固定资产净额 PP&E net"][1])

    # 经营指标：入轨质量分项 = 合计（招股书注明有四舍五入，容差放宽到 2 吨）
    oy = {k: v for k, v in OPS_Y}
    for i in range(3):
        eq(f"{YEARS[i]} 入轨质量分项", oy["入轨质量-客户载荷(公吨) customer payloads"][i]
           + oy["入轨质量-内部载荷(公吨) internal payloads"][i],
           oy["入轨质量-合计(公吨) Mass to orbit total"][i], tol=2)

    # 经营指标中期：Q1+Q2=H1；客户+内部=合计
    oi = {k: v for k, v in OPS_I}
    for name, (q1, q2, h1, q1b, q2b, h1b) in [(k, v) for k, v in OPS_I]:
        if name.startswith(("Falcon", "其中", "Starship")):
            eq(f"2025 {name} Q1+Q2=H1", q1 + q2, h1)
            eq(f"2026 {name} Q1+Q2=H1", q1b + q2b, h1b)
    for j in range(6):
        eq(f"{OPS_I_COLS[j]} 客户+内部=Falcon合计",
           oi["其中客户发射 customer launches"][j] + oi["其中内部发射 internal launches"][j],
           oi["Falcon 发射次数 Falcon launches"][j])
    # 跨源独立核：招股书正文「2026Q1 发射 40 枚 Falcon」vs 由 10-Q 的 Q2/H1 反推
    eq("跨源 2026Q1 Falcon 发射数", oi["Falcon 发射次数 Falcon launches"][3], 40)
    # 跨源：10-Q 的 H1 分部收入 vs 招股书 Connectivity 订阅×ARPU 量级（只做方向性,不做等式）

    return errs


# ---------------------------------------------------------------- 派生比率
def ratios():
    rows = []

    def series(fn):
        out = []
        for i in range(len(YEARS)):
            try:
                v = fn(i)
            except (TypeError, ZeroDivisionError):
                v = None
            out.append(None if v is None else round(v, 4))
        return out

    rev = D["营业收入 Revenue"]
    rows.append(("毛利率 Gross margin", series(
        lambda i: (rev[i] + D["营业成本 Cost of revenue"][i]) / rev[i])))
    rows.append(("经营利润率 Operating margin", series(
        lambda i: D["经营利润 Income (loss) from operations"][i] / rev[i])))
    rows.append(("净利率 Net margin", series(lambda i: D["净利润 Net income (loss)"][i] / rev[i])))
    rows.append(("研发费用率 R&D ratio", series(
        lambda i: -D["研发开支 Research and development"][i] / rev[i])))
    rows.append(("销售及管理费用率 SG&A ratio", series(
        lambda i: -D["销售及行政管理 Selling, general and administrative"][i] / rev[i])))
    rows.append(("营收增速 Revenue growth", series(
        lambda i: None if i == 0 else rev[i] / rev[i - 1] - 1)))
    rows.append(("经营现金流/净利 OCF/Net income", series(
        lambda i: C["经营活动现金流净额 Net cash from operating"][i] / D["净利润 Net income (loss)"][i])))
    rows.append(("经营现金流/营收 OCF/Revenue", series(
        lambda i: C["经营活动现金流净额 Net cash from operating"][i] / rev[i])))
    rows.append(("Capex/经营现金流 Capex/OCF", series(
        lambda i: -C["购建固定资产 Purchases of PP&E (capex)"][i]
        / C["经营活动现金流净额 Net cash from operating"][i])))
    rows.append(("Capex/营收 Capex/Revenue", series(
        lambda i: -C["购建固定资产 Purchases of PP&E (capex)"][i] / rev[i])))
    rows.append(("自由现金流FCF(百万美元) OCF-Capex", series(
        lambda i: C["经营活动现金流净额 Net cash from operating"][i]
        + C["购建固定资产 Purchases of PP&E (capex)"][i])))
    rows.append(("折旧摊销/营收 D&A/Revenue", series(
        lambda i: C["折旧摊销 Depreciation and amortization"][i] / rev[i])))
    rows.append(("股权激励/营收 SBC/Revenue", series(
        lambda i: C["股权激励 Share-based compensation"][i] / rev[i])))
    rows.append(("合同负债合计(百万美元) Deferred revenue total", series(
        lambda i: B["合同负债-流动 Deferred revenue current"][i]
        + B["合同负债-非流动 Deferred revenue non-current"][i])))
    rows.append(("合同负债/营收 Deferred revenue/Revenue", series(
        lambda i: (B["合同负债-流动 Deferred revenue current"][i]
                   + B["合同负债-非流动 Deferred revenue non-current"][i]) / rev[i])))
    rows.append(("应收/营收 AR/Revenue", series(
        lambda i: B["应收账款净额 Accounts receivable net"][i] / rev[i])))
    rows.append(("有息负债合计(百万美元) Total debt", series(
        lambda i: B["有息负债及租赁-流动 Debt and finance leases current"][i]
        + B["有息负债及租赁-非流动 Debt and finance leases non-current"][i])))
    rows.append(("净现金(百万美元) Cash+MS-Debt", series(
        lambda i: B["货币资金 Cash and cash equivalents"][i] + B["金融资产 Marketable securities"][i]
        - B["有息负债及租赁-流动 Debt and finance leases current"][i]
        - B["有息负债及租赁-非流动 Debt and finance leases non-current"][i])))
    rows.append(("资产负债率 Liabilities/Total assets", series(
        lambda i: B["负债合计 Total liabilities"][i] / B["资产总计 Total assets"][i])))
    rows.append(("固定资产/总资产 PPE/TA", series(
        lambda i: B["固定资产净额 Property, plant and equipment net"][i]
        / B["资产总计 Total assets"][i])))
    rows.append(("商誉/总资产 Goodwill/TA", series(
        lambda i: B["商誉 Goodwill"][i] / B["资产总计 Total assets"][i])))
    rows.append(("利息保障(经营利润/利息支出) EBIT/Interest", series(
        lambda i: D["经营利润 Income (loss) from operations"][i] / -D["利息支出 Interest expense"][i])))
    # 公司自定义非 GAAP 口径（招股书 MD&A 披露值，原样录入，供对照用）
    adj_ebitda = [3821, 5350, 6584]
    rows.append(("[非GAAP·公司口径] 调整后EBITDA Adjusted EBITDA", adj_ebitda))
    rows.append(("[非GAAP对照] 调整后EBITDA中被加回的折旧摊销", series(
        lambda i: C["折旧摊销 Depreciation and amortization"][i])))
    rows.append(("[非GAAP对照] 折旧摊销占调整后EBITDA比", series(
        lambda i: C["折旧摊销 Depreciation and amortization"][i] / adj_ebitda[i])))
    # 分部派生
    for seg, j0 in (("Space", 0), ("Connectivity", 1), ("AI", 2)):
        rows.append((f"[分部]{seg} 经营利润率 Op margin", series(
            lambda i, s=seg: S[f"[经营利润] {s}"][i] / S[f"[收入] {s}"][i])))
        rows.append((f"[分部]{seg} Capex/收入 Capex/Rev", series(
            lambda i, s=seg: S[f"[资本开支] {s}"][i] / S[f"[收入] {s}"][i])))
    return rows


# ---------------------------------------------------------------- 写出
def write(path, header, cols, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([header])
        w.writerow(["科目"] + cols)
        for name, vals in rows:
            w.writerow([name] + ["" if v is None else v for v in vals])
    print(f"  ✓ {path.name}")


def main():
    errs = checks()
    if errs:
        print(f"✗ 勾稽校验未通过（{len(errs)} 条），不写出 CSV：")
        for e in errs:
            print("   -", e)
        raise SystemExit(1)
    print("✓ 勾稽校验全部通过")

    y = [str(x) for x in YEARS]
    src = ("来源: SEC 424B4 招股书(2026-06-12, F页经审计) + 10-Q(2026-08-04); "
           "报告主体=SpaceX+xAI+X 同一控制下追溯合并重述")
    write(OUT / "利润表.csv",
          f"# 单位: 百万美元(USD millions), 费用/减项=负数, 覆盖{y[0]}-{y[-1]}, {src}", y, INCOME)
    write(OUT / "资产负债表.csv",
          f"# 单位: 百万美元(USD millions), 覆盖{y[0]}-{y[-1]}"
          f"(2023年末除商誉外招股书未列报,留空), {src}", y, BALANCE)
    write(OUT / "现金流量表.csv",
          f"# 单位: 百万美元(USD millions), 流出=负数, 覆盖{y[0]}-{y[-1]}, {src}", y, CASHFLOW)
    write(OUT / "财务比率.csv",
          f"# 派生比率(比率=小数, 金额=百万美元); 由本目录三表派生; 覆盖{y[0]}-{y[-1]}", y, ratios())
    write(OUT / "分部营收.csv",
          f"# 单位: 百万美元(USD millions); 三报告分部 Space/Connectivity/AI + 六产品线; "
          f"年度来自招股书分部附注, H1 来自 10-Q; {src}", SEG_COLS, SEGMENT)
    write(OUT / "中期财务-2026.csv",
          "# 单位: 百万美元(USD millions), 费用/减项=负数; 来源: 10-Q(2026-08-04); "
          "IPO 于 2026-06 完成故 H1 含巨额一次性融资项",
          INTERIM_COLS, INTERIM_IS + INTERIM_CF)
    write(OUT / "中期资产负债表-2026.csv",
          "# 单位: 百万美元(USD millions); 时点数; 来源: 10-Q(2026-08-04)",
          INTERIM_BS_COLS, INTERIM_BS)

    write(OUT / "固定资产明细.csv",
          "# 单位: 百万美元(USD millions); **原值(gross)**, 累计折旧单列; "
          "来源: 招股书 PP&E 附注(2024/2025) + 10-Q Note 5(2026-06-30); "
          "净额已与资产负债表跨表核对一致 || "
          "折旧年限(招股书会计政策附注): 服务器及网络设备 5-6年 · 卫星 3-5年 · 机器设备 3-10年 · "
          "飞行器硬件 5-25次飞行(按次而非按年) · 数据中心基础设施 20-25年 · 发射场 7-20年 · "
          "房屋及改良 30年 · 租赁资产改良 取7-20年与租期孰短 || "
          "在建工程口径(10-Q Note 5原文): 主要为在建/扩建设施设备及**尚未投用的AI基础设施**",
          PPE_COLS, PPE)

    # ---- 派生回流：折旧测算（分析过程算出，按项目纪律回写 财务数据/）
    # 口径：以 2026-06-30 **原值**为基数 ÷ 招股书披露的折旧年限区间 → 年化折旧区间
    # 局限：① 附注只给**合计**累计折旧、未按类别拆分，故无法按净值测算，用原值会高估已折旧殆尽的老资产
    #       ② 飞行器硬件按**飞行次数**折旧(5-25次)，非按年，无法年化 → 单列不参与合计
    #       ③ 土地不计提折旧，但「土地房屋及改良」未拆分土地 → 该行为上限
    #       ④ 在建工程尚未投用、当前不计提 → 单列为「尚未启动的折旧池」
    LIVES = [
        ("服务器及网络设备", 34771, 5, 6),
        ("卫星", 13788, 3, 5),
        ("机器设备", 9453, 3, 10),
        ("数据中心基础设施", 3991, 20, 25),
        ("发射场", 3118, 7, 20),
        ("土地房屋及改良(含不折旧的土地·上限)", 2958, 30, 30),
        ("租赁资产改良", 881, 7, 20),
    ]
    dep_rows = []
    tot_g = tot_hi = tot_lo = 0
    for name, gross, lo_y, hi_y in LIVES:
        hi = round(gross / lo_y)   # 年限下限 → 年折旧上限
        lo = round(gross / hi_y)
        mid = round(gross / ((lo_y + hi_y) / 2))
        dep_rows.append((name, [gross, lo_y, hi_y, lo, hi, mid]))
        tot_g += gross
        tot_hi += hi
        tot_lo += lo
    dep_rows.append(("【小计】可年化折旧资产", [tot_g, "", "", tot_lo, tot_hi,
                     round(sum(r[1][5] for r in dep_rows))]))
    dep_rows.append(("飞行器硬件(按5-25次飞行折旧·不可年化)", [1557, "", "", "", "", ""]))
    dep_rows.append(("在建工程(尚未投用·当前不计提)", [12554, "", "", "", "", ""]))
    dep_rows.append(("固定资产原值合计 Gross PP&E", [83071, "", "", "", "", ""]))
    dep_rows.append(("【对照】H1-2026 实际折旧×2(年化)", ["", "", "", "", "", 10128]))
    dep_rows.append(("【对照】FY2025 实际折旧摊销 D&A", ["", "", "", "", "", 6701]))
    write(OUT / "折旧测算.csv",
          "# **派生估算·非披露值**; 单位: 百万美元(USD millions), 年限=年; "
          "基数=2026-06-30 固定资产**原值**(见 固定资产明细.csv), 年限=招股书会计政策附注披露区间; "
          "局限: 累计折旧未按类别披露故按原值测算(高估老资产) · 飞行器硬件按飞行次数折旧不可年化 · "
          "土地不折旧但未单独拆分 · 在建工程尚未投用不计提",
          ["原值(2026-06-30)", "年限下限", "年限上限", "年化折旧(按年限上限)",
           "年化折旧(按年限下限)", "年化折旧(按年限中值)"], dep_rows)

    # ---- 合同储备(backlog) 与 客户集中度（10-Q Note 3 收入附注 + Note 17 关联方）
    BL_COLS = ["2025Q2", "2026Q2", "2025H1", "2026H1", "2026-06-30时点"]
    BACKLOG = [
        ("合同储备 Backlog 总额",                    [None, None, None, None, 47461]),
        ("其中:已列为合同负债 of which deferred revenue", [None, None, None, None, 14286]),
        ("合同储备-1年内确认占比",                     [None, None, None, None, 0.56]),
        ("合同储备-1至3年确认占比",                    [None, None, None, None, 0.34]),
        ("合同储备-3年以上确认占比",                   [None, None, None, None, 0.10]),
        ("合同负债(递延收入)总额",                     [None, None, None, None, 14286]),
        ("客户A占合并收入比(横跨全部分部)",             [0.167, 0.183, 0.199, 0.179, None]),
        ("客户B占合并收入比(仅AI分部)",                [None, 0.195, None, 0.122, None]),
        ("[派生] 客户B收入额(占比×当期收入)",           [None, 1524, None, 1526, None]),
        ("[派生] 客户B占AI方案及算力收入比",            [None, 0.695, None, 0.572, None]),
        ("关联方债务-Valor设备租赁(失败售后租回)",       [None, None, None, None, 13329]),
        ("关联方利息支出-Valor",                      [None, 327, None, 513, None]),
    ]
    write(OUT / "合同储备与客户集中.csv",
          "# 单位: 百万美元(USD millions), 占比=小数; 来源: 10-Q(2026-08-04) 收入附注 + 关联方附注 Note 17; "
          "口径: Backlog=已达成可执行合同中尚未履约部分的交易价格, **不含**按交付即确认的部分/非重大选择权/受约束的可变对价; "
          "客户A/B 公司**未具名**; 关联方债务对手方=Valor Equity Partners(董事 Antonio Gracias 为其创始人兼CEO/CIO), "
          "该等设备租赁被判定为**失败的售后租回**故全额计为债务",
          BL_COLS, BACKLOG)

    # ---- 派生回流：AI 分部折旧情景（在建工程转固后的年化折旧）
    # 已知（一手）：2026-06-30 在建工程 12,554；服务器 34,771(5-6y)；数据中心基础设施 3,991(20-25y)
    #              AI 分部 H1-2026 折旧摊销 3,378（年化 6,756）；AI 分部 H1-2026 资本开支 23,551
    # 未知（须假设·10-Q 未披露）：① 在建工程中 AI 占比 ② 转固后在「服务器 5.5y」与「数据中心基建 22.5y」间的分配
    CIP = 12554
    SERV_L, DC_L = 5.5, 22.5
    # 在役基数运行率两条路径：
    #   路径A 资产类别法 = 服务器/5.5 + 数据中心基建/22.5（不含机器设备与无形摊销归属 AI 的部分）
    run_a = round(34771 / SERV_L + 3991 / DC_L)
    #   路径B 分部实际法 = 服务器期末值/5.5 + (H1实际年化 − H1服务器平均基数折旧年化)
    serv_avg = (22694 + 34771) / 2
    other_ai = round(3378 * 2 - serv_avg / SERV_L)     # 机器设备+数据中心+无形摊销中归 AI 的部分
    run_b = round(34771 / SERV_L + other_ai)
    SCEN = [("低", 0.70, 0.30), ("中", 0.85, 0.60), ("高", 1.00, 0.90)]
    ai_rows = [
        ("[输入·一手] 在建工程总额 CIP", [CIP, CIP, CIP]),
        ("[输入·一手] 服务器及网络设备(在役)", [34771, 34771, 34771]),
        ("[输入·一手] AI分部 H1-2026 折旧摊销×2(年化)", [6756, 6756, 6756]),
        ("[输入·一手] AI分部 FY2025 折旧摊销", [3568, 3568, 3568]),
        ("[假设] 在建工程中 AI 占比", [s[1] for s in SCEN]),
        ("[假设] 转固后归入服务器(5.5年)的比例", [s[2] for s in SCEN]),
        ("[派生] 在役基数运行率-路径A(资产类别法)", [run_a, run_a, run_a]),
        ("[派生] 在役基数运行率-路径B(分部实际法)", [run_b, run_b, run_b]),
    ]
    inc, lo_t, hi_t = [], [], []
    for _, ai_sh, serv_sh in SCEN:
        cip_ai = CIP * ai_sh
        add = round(cip_ai * serv_sh / SERV_L + cip_ai * (1 - serv_sh) / DC_L)
        inc.append(add)
        lo_t.append(run_a + add)
        hi_t.append(run_b + add)
    ai_rows += [
        ("[派生] 在建工程转固带来的年折旧增量", inc),
        ("【结果】转固后 AI 分部年化折旧-下限(路径A)", lo_t),
        ("【结果】转固后 AI 分部年化折旧-上限(路径B)", hi_t),
        ("[对照] 相对 FY2025 实际的倍数-下限", [round(v / 3568, 2) for v in lo_t]),
        ("[对照] 相对 FY2025 实际的倍数-上限", [round(v / 3568, 2) for v in hi_t]),
    ]
    write(OUT / "折旧测算-AI分部.csv",
          "# **派生情景估算·非披露值·非预测**; 单位: 百万美元(USD millions); "
          "口径: 假设自 2026-06-30 起**资本开支归零**、仅现有在役资产 + 在建工程转固 → 故为**下限/地板值**; "
          "两项关键假设(10-Q 未披露): 在建工程中 AI 占比 · 转固后在服务器(5.5年)与数据中心基建(22.5年)间的分配; "
          "参考: AI分部 H1-2026 单半年资本开支 23,551 —— 只要投入不停, 实际值必高于本表",
          ["情景-低", "情景-中", "情景-高"], ai_rows)

    # 经营指标：补派生行「客户载荷占入轨质量比」
    oy = dict(OPS_Y)
    ops_y = []
    for name, vals in OPS_Y:
        if name.startswith("客户载荷占"):
            vals = [round(oy["入轨质量-客户载荷(公吨) customer payloads"][i]
                          / oy["入轨质量-合计(公吨) Mass to orbit total"][i], 4)
                    for i in range(3)]
        ops_y.append((name, vals))
    write(OUT / "经营指标-年度.csv",
          f"# 经营(非财务)指标; 来源: 招股书 Key Business Metrics 章节; 覆盖{y[0]}-{y[-1]}", y, ops_y)
    write(OUT / "经营指标-中期.csv",
          "# 经营(非财务)指标; 来源: 10-Q(2026-08-04) Key Business Metrics + 招股书(2026Q1); "
          "2025Q1/2026Q1 的发射数由 H1−Q2 反推, 已与招股书正文「2026Q1 发射 40 枚 Falcon」交叉核对一致",
          OPS_I_COLS, OPS_I)


if __name__ == "__main__":
    main()
