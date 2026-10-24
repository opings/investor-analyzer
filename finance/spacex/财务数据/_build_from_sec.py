#!/usr/bin/env python3
"""SpaceX (Space Exploration Technologies Corp., Nasdaq: SPCX) 三表建库

一手真源（均在 report/spacex/）：
  - 招股说明书-424B4-20260612.htm  SEC 424B4，2026-06-12 定价招股书
      F 页经审计年度三表 FY2023/2024/2025 + 附注（分部/商誉/PP&E/重组）
  - 2026-Q2.htm                    SEC 10-Q，2026-08-04，期间 2026-06-30（上市后首份定期报告）
  - 2026-Q3.htm                    SEC 10-Q，2026-10-22，期间 2026-09-30（Cursor 并表后首期）
  - 2026-Q3-业绩稿-EX99.htm         8-K EX-99.1，2026-10-20 Q3 业绩稿（仅作跨源核对）

口径要点（务必与 README.md 同步）：
  1. 报告主体 = SpaceX + xAI + X 的**追溯合并**结果。SpaceX 于 2026-02-02 收购 xAI，
     xAI 于 2025-03-28 收购 X Holdings，两笔均为同一控制下重组（Musk 控股），
     按历史账面价值追溯重述所有列报期间，且「constitutes a change in reporting entity」
     （译：构成报告主体的变更；招股书 F-11 Note 1）。故 2023-2025 序列**不是**历史上独立 SpaceX 的经营结果。
     2026-07-06 Mesh Optical、2026-08-14 Cursor 按购买法自交割日起并表。
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
# 源：Q2 10-Q（2026-08-04·H1 与 Q2 单季）+ Q3 10-Q（2026-10-22·Q3 单季与前三季）
# 期间轴：H1 / 单季 / 前三季 三种期间并列，跨列比较前先认清期间（见 README 口径约定）
INTERIM_COLS = ["2025H1", "2026H1", "2026Q2", "2025Q3", "2026Q3", "2025前三季", "2026前三季"]
INTERIM_IS = [
    ("营业收入 Revenue",                              [8138, 12508, 7814, 5576, 14575, 13714, 27083]),
    ("营业成本 Cost of revenue",                      [-4244, -5883, -3495, -2705, -5478, -6949, -11361]),
    ("研发开支 Research and development",             [-3515, -7062, -3548, -2291, -4596, -5806, -11658]),
    ("销售及行政管理 SG&A",                           [-1099, -1658, -912, -575, -1707, -1674, -3365]),
    ("重组费用(冲回) Restructuring charges (credits)", [-194, 9, -2, -278, -3, -472, 6]),
    ("减值 Impairment",                               [-29, 0, 0, 0, 0, -29, 0]),
    ("总成本及开支 Total costs and expenses",          [-9081, -14594, -7957, -5849, -11784, -14930, -26378]),
    ("经营利润 Income (loss) from operations",         [-943, -2086, -143, -273, 2791, -1216, 705]),
    ("利息支出 Interest expense",                     [-858, -1293, -629, -514, -675, -1372, -1968]),
    ("利息收入 Interest income",                      [215, 553, 340, 155, 873, 370, 1426]),
    ("其他收入(支出)净额 Other income (expense) net",   [202, -1962, -86, 140, 1025, 342, -937]),
    ("除税前利润 Income (loss) before income taxes",   [-1384, -4788, -518, -492, 4014, -1876, -774]),
    ("所得税 Provision for (benefit from) income taxes", [-152, -29, -23, -562, 390, -714, 361]),
    ("净利润 Net income (loss)",                      [-1536, -4817, -541, -1054, 4404, -2590, -413]),
    ("归属股东净利润 Net income (loss) attributable to shareholders", [-1536, -5488, -541, -1054, 4404, -2590, -1084]),
    ("每股基本盈利(美元) Basic EPS",                   [-0.53, -1.12, -0.09, -0.36, 0.37, -0.89, -0.15]),
    ("每股摊薄盈利(美元) Diluted EPS",                 [-0.53, -1.12, -0.09, -0.36, 0.35, -0.89, -0.15]),
    ("基本加权平均股数(百万) Basic WAS",               [2902, 4879, 5864, 2941, 11942, 2915, 7274]),
    ("摊薄加权平均股数(百万) Diluted WAS",             [2902, 4879, 5864, 2941, 12475, 2915, 7274]),
    # ---- 补充：费用构成与非 GAAP（分部附注 / PP&E 附注 / 无形资产附注 / MD&A 非 GAAP 调节表）
    ("[补充] 折旧摊销 D&A",                            [2970, 5290, 2848, 1814, 3644, 4784, 8934]),
    ("[补充] 其中:固定资产折旧 Depreciation",           [None, None, None, 1595, 3351, 4142, 8415]),
    ("[补充] 其中:无形资产摊销 Amortization",           [None, None, None, 219, 293, 642, 519]),
    ("[补充] 股权激励(不含收购相关) SBC ex-acquisitions", [694, 1470, 831, 350, 1146, 1044, 2616]),
    ("[补充] 收购相关股权激励 SBC related to acquisitions", [0, 0, 0, 0, 1217, 0, 1217]),
    ("[补充] 收购相关费用(计入销管) Acquisition-related costs", [0, 0, 0, 0, 8, 0, 8]),
    ("[非GAAP·公司口径] 调整后EBITDA Adjusted EBITDA",  [2944, 4665, 3538, 2169, 8809, 5113, 13474]),
]
# 现金流量表只有累计期间（H1 / 前三季），单季列 = 前三季 − H1（脚本派生，写出时标注）；Q2 单季不可得留空
CF_ROWS = [  # (科目, [2025H1, 2026H1], [2025前三季, 2026前三季])
    ("经营活动现金流净额 Net cash from operating",            [351, 3466],       [4120, 13097]),
    ("  其中:应收账款变动 Change in accounts receivable",     [-470, -2003],     [-934, -2882]),
    ("  其中:存货变动 Change in inventory",                   [-360, -827],      [-378, -1381]),
    ("  其中:应付账款变动 Change in accounts payable",        [309, -88],        [668, -970]),
    ("  其中:合同负债变动 Change in deferred revenue",        [680, 2169],       [404, 4922]),
    ("  其中:债务清偿损失(非现金加回) Loss on debt extinguishment", [0, 1545],  [0, 1545]),
    ("购建固定资产 Capex",                                  [-6965, -28476],   [-13846, -48069]),
    ("产品返利收到 Proceeds from product rebates",           [0, 1195],         [0, 1372]),
    ("购买金融资产 Purchases of marketable securities",      [-601, -13630],    [-601, -46834]),
    ("金融资产到期 Maturities of marketable securities",     [543, 7248],       [548, 9158]),
    ("无形资产购买(频谱信托付款等) Payments for intangible assets", [0, -856],  [0, -866]),
    ("收购取得现金 Cash received from acquisition of businesses", [0, 0],      [0, 514]),
    ("投资活动现金流净额 Net cash used in investing",         [-6032, -34487],   [-12997, -84611]),
    ("取得借款 Proceeds from debt and other financings",     [10943, 51812],    [10947, 51834]),
    ("偿还借款 Repayments on debt and other financings",     [-5990, -39396],   [-6014, -39845]),
    ("债务清偿溢价 Payment of debt extinguishment premium",   [0, -1153],        [0, -1153]),
    ("发行股本净额 Proceeds from issuance of capital stock",  [5047, 8319],      [5299, 8319]),
    ("回购普通股及优先股 Repurchase of common and RCPS",      [-520, -4426],     [-525, -4426]),
    ("IPO募资净额 Proceeds from IPO net",                    [0, 85675],        [0, 85675]),
    ("融资活动现金流净额 Net cash from financing",            [9199, 100291],    [9440, 99819]),
    ("汇率影响 Effect of exchange rate changes",              [75, -42],         [69, -43]),
    ("现金净变动 Net change in cash",                        [3593, 69228],     [632, 28262]),
]
CF_BEGIN = {"2025": 11501, "2026": 25124}                    # 期初现金及受限现金（年初）
CF_END_H1 = [15094, 94352]
CF_END_9M = [12133, 53386]
# 补充披露（非现金/已付）：H1 与前三季原值，不做单季派生
CF_SUPP = [  # (科目, [2025H1, 2026H1], [2025前三季, 2026前三季])
    ("[补充] 已付利息(净额) Cash paid for interest net",       [603, 1667],       [695, 2078]),
    ("[补充] 已购未付固定资产(计入应付及预提) PP&E in AP and accrued", [4260, 5513], [3573, 11827]),
    ("[补充] 以其他融资购置的固定资产 PP&E financed by other financings", [0, 3921], [0, 3921]),
    ("[补充] 以发行股份收购业务 Acquisition of businesses through issuance of shares", [0, 0], [0, 42723]),
]
# 时点数（资产负债表）：2025-12-31 / 2026-06-30 / 2026-09-30
INTERIM_BS_COLS = ["2025-12-31", "2026-06-30", "2026-09-30"]
INTERIM_BS = [
    ("货币资金 Cash and cash equivalents",            [24747, 93522, 51294]),
    ("金融资产 Marketable securities",                [0, 6487, 38561]),
    ("应收账款净额 Accounts receivable net",           [1579, 3596, 4772]),
    ("存货 Inventory",                                [2416, 2718, 2891]),
    ("预付及其他流动资产 Prepaid and other current",    [2210, 1724, 3457]),
    ("流动资产合计 Total current assets",              [30952, 108047, 100975]),
    ("固定资产净额 PP&E net",                         [42602, 65736, 89483]),
    ("融资租赁使用权资产 Finance lease ROU",           [1260, 1118, 1040]),
    ("无形资产净额 Intangible assets net",             [1548, 1318, 6354]),
    ("数字资产 Digital assets",                       [1637, 1098, 1573]),
    ("商誉 Goodwill",                                 [11809, 11645, 48423]),
    ("递延所得税资产 Deferred tax assets",             [141, 354, 388]),
    ("其他资产 Other assets",                         [2130, 3454, 5809]),
    ("资产总计 Total assets",                         [92079, 192770, 254045]),
    ("应付账款 Accounts payable",                     [11792, 8243, 13259]),
    ("合同负债-流动 Deferred revenue current",         [6111, 7977, 10784]),
    ("有息负债及租赁-流动 Debt and leases current",     [928, 2525, 2698]),
    ("应计及其他流动负债 Accrued and other current",    [2569, 2377, 5997]),
    ("流动负债合计 Total current liabilities",         [21400, 21122, 32738]),
    ("合同负债-非流动 Deferred revenue non-current",    [6005, 6309, 6736]),
    ("有息负债及租赁-非流动 Debt and leases non-current", [21968, 36839, 36146]),
    ("其他非流动负债 Other liabilities",               [1381, 1276, 1657]),
    ("负债合计 Total liabilities",                    [50754, 65546, 77277]),
    ("可赎回可转换优先股 Redeemable convertible preferred", [38752, 0, 0]),
    ("股东权益合计 Total shareholders' equity",        [2573, 127224, 176768]),
    ("负债+优先股+权益 Total L, RCPS and equity",       [92079, 192770, 254045]),
    ("其中:关联方有息负债 Related-party debt (incl.)",  [4507, 13329, 12897]),
    ("其中:受限现金(预付及其他流动+其他资产) Restricted cash", [377, 830, 2092]),
    # 分部商誉：Q2 10-Q / Q3 10-Q Note 6 正文（Q2 称 AI 分部，Q3 更名 SI）；Space 分部无商誉
    ("其中:商誉-Connectivity 分部 Goodwill-Connectivity", [513, 515, 515]),
    ("其中:商誉-SI 分部(原 AI) Goodwill-SI",            [11296, 11130, 47908]),
    # 股数：12-31 取资产负债表正表（B 类正表 644、股本附注 643，取正表）；06-30 取 Q3 10-Q 股本附注期初余额
    ("A 类普通股流通股数(百万股) Class A shares outstanding", [1952, 7607, 8240]),
    ("B 类普通股流通股数(百万股) Class B shares outstanding", [644, 5569, 5339]),
    ("C 类普通股流通股数(百万股) Class C shares outstanding(IPO 时并入 A 类)", [482, 0, 0]),
]

# ------------------------------------------------------ 固定资产明细
# 源：招股书 PP&E 附注（table idx 71，2024/2025）+ Q2 10-Q Note 5（2026-06-30）+ Q3 10-Q Note 5（2026-09-30）
# 均为**原值（gross）**，累计折旧单列；净额须与资产负债表「固定资产净额」一致
PPE_COLS = ["2024-12-31", "2025-12-31", "2026-06-30", "2026-09-30"]
PPE = [
    ("服务器及网络设备 Servers and networking equipment", [6892, 22694, 34771, 43206]),
    ("卫星 Satellites",                                  [7591, 11949, 13788, 14738]),
    ("机器设备 Machinery and equipment",                  [5343, 6343, 9453, 11014]),
    ("数据中心基础设施 Data center infrastructure",        [224, 2960, 3991, 6333]),
    ("发射场 Launch sites",                              [2121, 2404, 3118, 3175]),
    ("土地房屋及改良 Land, buildings and improvements",     [913, 1876, 2958, 5167]),
    ("飞行器硬件 Flight vehicle hardware",                [1577, 1689, 1557, 1625]),
    ("租赁资产改良 Leasehold improvements",               [1019, 784, 881, 1002]),
    ("在建工程 Construction-in-progress",                 [3007, 4604, 12554, 23745]),
    ("固定资产原值 Gross PP&E",                          [28687, 55303, 83071, 110005]),
    ("减:累计折旧 Accumulated depreciation",              [-7540, -12701, -17335, -20522]),
    ("固定资产净额 Net PP&E",                            [21147, 42602, 65736, 89483]),
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
# 中期/季度（期末时点数标注「期末」）；Q1 = H1 − Q2 派生（10-Q 只给 Q2 与 H1），已与招股书 Q1 原值交叉核对
OPS_I_COLS = ["2025Q1", "2025Q2", "2025H1", "2025Q3", "2025前三季",
              "2026Q1", "2026Q2", "2026H1", "2026Q3", "2026前三季"]
OPS_I = [
    # Q3 10-Q 起更名为「Starlink consumer subscribers」，业绩稿 Note 2 称即原「Starlink Subscribers」、定义未变（不含签约管理的企业与政府客户）
    ("Starlink 消费者订阅数(百万,期末) Starlink consumer subscribers", [5.0, 6.0, 6.0, 7.2, 7.2, 10.3, 12.0, 12.0, 13.6, 13.6]),
    ("Starlink 消费者ARPU(美元/月) Starlink consumer ARPU",          [86, 85, 85, 83, 84, 66, 66, 66, 69, 67]),
    ("Falcon 发射次数 Falcon launches",                [36, 45, 81, 43, 124, 40, 37, 77, 33, 110]),
    ("其中客户发射 customer launches",                 [12, 9, 21, 15, 36, 7, 10, 17, 12, 29]),
    ("其中内部发射 internal launches",                 [24, 36, 60, 28, 88, 33, 27, 60, 21, 81]),
    ("Starship 发射次数 Starship launches",            [2, 1, 3, 1, 4, 0, 1, 1, 2, 3]),
    ("入轨质量(公吨) Mass to orbit",                   [450, 652, 1102, 525, 1627, 556, 485, 1041, 476, 1517]),
    ("其中客户载荷(公吨) customer payloads",           [75, 88, 163, 111, 274, 45, 87, 132, 119, 251]),
    ("其中内部载荷(公吨) internal payloads",           [375, 563, 938, 415, 1353, 511, 397, 908, 358, 1266]),
    ("算力铭牌功率(GW,期末) Nameplate compute",          [None, 0.4, 0.4, 0.6, 0.6, 1.0, 1.4, 1.4, 1.7, 1.7]),
]

# ------------------------------------------------------ 分部·季度与前三季
# 源：Q2 10-Q 分部附注（2025Q2、2026Q2 三个月列）+ Q3 10-Q 分部附注（2025Q3、2026Q3、前三季）
#     + 两份 10-Q 的非 GAAP 分部调节表；2026Q3 起 AI 分部更名 SI（Super Intelligence），口径连续
# 2026Q1 = 2026H1（Q2 10-Q）− 2026Q2，脚本派生；校验其合计 == 招股书 Q1 原值（收入 4,694 / 经营亏损 1,943）
SEGQ_COLS = ["2025Q2", "2025Q3", "2026Q1", "2026Q2", "2026Q3", "2025前三季", "2026前三季"]
SEGQ = [
    ("Space-发射服务 Launch Services",           [490, 1000, 330, 648, 1130, 2056, 2108]),
    ("Space-发射及开发 Launch & Development",     [256, 666, 289, 314, 637, 1221, 1240]),
    ("Connectivity-消费者 Consumer",             [1721, 1986, 2148, 2485, 3121, 5198, 7754]),
    ("Connectivity-企业及政府 Enterprise & Gov",  [867, 1111, 1109, 1806, 2127, 2961, 5042]),
    ("SI-广告 Advertising",                      [426, 454, 343, 367, 538, 1323, 1248]),
    ("SI-方案及基础设施 SI Solutions & Infra",     [311, 359, 475, 2194, 7022, 955, 9691]),
    ("[收入] Space",                             [746, 1666, 619, 962, 1767, 3277, 3348]),
    ("[收入] Connectivity",                      [2588, 3097, 3257, 4291, 5248, 8159, 12796]),
    ("[收入] SI",                                [737, 813, 818, 2561, 7560, 2278, 10939]),
    ("[收入] 合计 Total",                        [4071, 5576, 4694, 7814, 14575, 13714, 27083]),
    ("[经营利润] Space",                         [-369, 259, -662, -542, -7, -181, -1211]),
    ("[经营利润] Connectivity",                  [923, 1190, 1188, 1656, 2367, 3147, 5211]),
    ("[经营利润] SI",                            [-1524, -1722, -2469, -1257, 431, -4182, -3295]),
    ("[经营利润] 合计 Total",                    [-970, -273, -1943, -143, 2791, -1216, 705]),
    ("[资本开支] Space",                         [946, 1113, 1052, 1174, 1606, 2818, 3832]),
    ("[资本开支] Connectivity",                  [1130, 1007, 1332, 1367, 1543, 2951, 4242]),
    ("[资本开支] SI",                            [749, 4760, 7723, 15828, 16444, 8077, 39995]),
    ("[资本开支] 合计 Total",                    [2825, 6880, 10107, 18369, 19593, 13846, 48069]),
    ("[折旧摊销] Space",                         [146, 264, 166, 158, 185, 572, 509]),
    ("[折旧摊销] Connectivity",                  [569, 628, 783, 805, 986, 1706, 2574]),
    ("[折旧摊销] SI",                            [811, 922, 1493, 1885, 2473, 2506, 5851]),
    ("[折旧摊销] 合计 Total",                    [1526, 1814, 2442, 2848, 3644, 4784, 8934]),
    ("[股权激励·不含收购] Space",                 [125, 151, 145, 179, 179, 383, 503]),
    ("[股权激励·不含收购] Connectivity",          [91, 105, 116, 136, 146, 270, 398]),
    ("[股权激励·不含收购] SI",                    [247, 94, 378, 516, 821, 391, 1715]),
    ("[股权激励·不含收购] 合计 Total",            [463, 350, 639, 831, 1146, 1044, 2616]),
    ("[收购相关股权激励] SI",                     [0, 0, 0, 0, 1217, 0, 1217]),
    ("[收购相关费用] SI",                         [0, 0, 0, 0, 8, 0, 8]),
    ("[重组费用(冲回为负)] SI",                   [190, 278, -11, 2, 3, 472, -6]),
    ("[减值] Space",                             [5, 0, 0, 0, 0, 29, 0]),
    ("[分部调整后EBITDA·非GAAP] Space",           [-93, 674, -351, -205, 357, 803, -199]),
    ("[分部调整后EBITDA·非GAAP] Connectivity",    [1583, 1923, 2087, 2597, 3499, 5123, 8183]),
    ("[分部调整后EBITDA·非GAAP] SI",              [-276, -428, -609, 1146, 4953, -813, 5490]),
    ("[分部调整后EBITDA·非GAAP] 合计 Total",      [1214, 2169, 1127, 3538, 8809, 5113, 13474]),
]

STATS = {"run": 0, "skipped": []}
D = {name: vals for name, vals in INCOME}
B = {name: vals for name, vals in BALANCE}
C = {name: vals for name, vals in CASHFLOW}
S = {name: vals for name, vals in SEGMENT}


# ---------------------------------------------------------------- 勾稽校验
def checks():
    errs = []

    # 默认容差 0：2026-10-24 对照组实测，容差 1 会放过「转录差 1」的错（改坏 4 个数各 +1 全部通过）；
    # 只在源表四舍五入确有差异处显式给容差（跨申报 2025 分部、入轨质量分项、派生 Q3 capex）
    def eq(label, a, b, tol=0):
        if a is None or b is None:
            STATS["skipped"].append(label)     # 空值跳过要可见：防「锚科目为空 → 校验静默全过」
            return
        STATS["run"] += 1
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

    # ================= 中期（Q2 10-Q + Q3 10-Q）=================
    ii = {k: v for k, v in INTERIM_IS}
    ib = {k: v for k, v in INTERIM_BS}
    sq = {k: v for k, v in SEGQ}
    ix = {c: n for n, c in enumerate(INTERIM_COLS)}
    for j, col in enumerate(INTERIM_COLS):
        eq(f"{col} 总成本及开支", sum(ii[k][j] for k in (
            "营业成本 Cost of revenue", "研发开支 Research and development",
            "销售及行政管理 SG&A", "重组费用(冲回) Restructuring charges (credits)",
            "减值 Impairment")), ii["总成本及开支 Total costs and expenses"][j])
        eq(f"{col} 经营利润", ii["营业收入 Revenue"][j] + ii["总成本及开支 Total costs and expenses"][j],
           ii["经营利润 Income (loss) from operations"][j])
        eq(f"{col} 除税前利润", ii["经营利润 Income (loss) from operations"][j] + ii["利息支出 Interest expense"][j]
           + ii["利息收入 Interest income"][j] + ii["其他收入(支出)净额 Other income (expense) net"][j],
           ii["除税前利润 Income (loss) before income taxes"][j])
        eq(f"{col} 净利润", ii["除税前利润 Income (loss) before income taxes"][j]
           + ii["所得税 Provision for (benefit from) income taxes"][j], ii["净利润 Net income (loss)"][j])
        # 非 GAAP 调节：调整后 EBITDA = 经营利润 + D&A + 股权激励(含收购相关) + 收购费用 + 重组费用 + 减值
        eq(f"{col} 调整后EBITDA调节", ii["经营利润 Income (loss) from operations"][j]
           + ii["[补充] 折旧摊销 D&A"][j] + ii["[补充] 股权激励(不含收购相关) SBC ex-acquisitions"][j]
           + ii["[补充] 收购相关股权激励 SBC related to acquisitions"][j]
           + ii["[补充] 收购相关费用(计入销管) Acquisition-related costs"][j]
           - ii["重组费用(冲回) Restructuring charges (credits)"][j] - ii["减值 Impairment"][j],
           ii["[非GAAP·公司口径] 调整后EBITDA Adjusted EBITDA"][j])
        dep, amo = ii["[补充] 其中:固定资产折旧 Depreciation"][j], ii["[补充] 其中:无形资产摊销 Amortization"][j]
        if dep is not None:
            eq(f"{col} 折旧+摊销=D&A", dep + amo, ii["[补充] 折旧摊销 D&A"][j])
    # 期间轴：H1(Q2 10-Q) + Q3(Q3 10-Q) = 前三季(Q3 10-Q)——跨申报文件衔接
    for k, v in INTERIM_IS:
        if k.startswith(("每股", "基本加权", "摊薄加权")):
            continue
        for y in ("2025", "2026"):
            h1, q3, n9 = v[ix[f"{y}H1"]], v[ix[f"{y}Q3"]], v[ix[f"{y}前三季"]]
            if None not in (h1, q3, n9):
                eq(f"{y} {k} H1+Q3=前三季", h1 + q3, n9)
    # 跨源：招股书 2026Q1 + Q2 10-Q 的 Q2 单季 = Q2 10-Q 的 H1
    for k, q1 in (("营业收入 Revenue", 4694), ("经营利润 Income (loss) from operations", -1943),
                  ("净利润 Net income (loss)", -4276)):
        eq(f"跨源 2026Q1(招股书)+Q2=H1 {k}", q1 + ii[k][ix["2026Q2"]], ii[k][ix["2026H1"]])
    # 现金流：三段 + 汇率 = 净变动；期初 + 净变动 = 期末（H1 与前三季各一遍）
    cf = {k: (h1, n9) for k, h1, n9 in CF_ROWS}
    for j, y in enumerate(("2025", "2026")):
        for p, label, end in ((0, "H1", CF_END_H1[j]), (1, "前三季", CF_END_9M[j])):
            def g(k):
                return cf[k][p][j]
            eq(f"{y}{label} 现金流三段+汇率=净变动", g("经营活动现金流净额 Net cash from operating")
               + g("投资活动现金流净额 Net cash used in investing") + g("融资活动现金流净额 Net cash from financing")
               + g("汇率影响 Effect of exchange rate changes"), g("现金净变动 Net change in cash"))
            eq(f"{y}{label} 期初+净变=期末", CF_BEGIN[y] + g("现金净变动 Net change in cash"), end)
        # 派生 Q3 单季 capex == 分部季度表 capex（现金流量表只有累计期间）
        q3_capex = -(cf["购建固定资产 Capex"][1][j] - cf["购建固定资产 Capex"][0][j])
        # 2025：前三季 13,846 − H1 6,965 = 6,881，Q3 10-Q 分部表单季列 6,880（跨申报四舍五入）→ 容差 1
        eq(f"{y}Q3 派生capex==分部季度capex", q3_capex, sq["[资本开支] 合计 Total"][SEGQ_COLS.index(f"{y}Q3")], tol=1)
        eq(f"{y}前三季 capex==分部前三季", -cf["购建固定资产 Capex"][1][j],
           sq["[资本开支] 合计 Total"][SEGQ_COLS.index(f"{y}前三季")])
        eq(f"{y}H1 capex==分部营收.csv H1", -cf["购建固定资产 Capex"][0][j], S["[资本开支] 合计 Total"][3 + j])

    # 中期资产负债表恒等式（三个时点）+ 现金口径衔接
    for j in range(len(INTERIM_BS_COLS)):
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
        eq(f"{INTERIM_BS_COLS[j]} 流动负债合计", sum(ib[k][j] for k in (
            "应付账款 Accounts payable", "合同负债-流动 Deferred revenue current",
            "有息负债及租赁-流动 Debt and leases current", "应计及其他流动负债 Accrued and other current")),
           ib["流动负债合计 Total current liabilities"][j])
        eq(f"{INTERIM_BS_COLS[j]} 负债合计", sum(ib[k][j] for k in (
            "流动负债合计 Total current liabilities", "合同负债-非流动 Deferred revenue non-current",
            "有息负债及租赁-非流动 Debt and leases non-current", "其他非流动负债 Other liabilities")),
           ib["负债合计 Total liabilities"][j])
        eq(f"{INTERIM_BS_COLS[j]} 资产=负债+优先股+权益",
           ib["负债合计 Total liabilities"][j]
           + ib["可赎回可转换优先股 Redeemable convertible preferred"][j]
           + ib["股东权益合计 Total shareholders' equity"][j],
           ib["资产总计 Total assets"][j])
        eq(f"{INTERIM_BS_COLS[j]} 货币资金+受限现金==现金流量表口径",
           ib["货币资金 Cash and cash equivalents"][j]
           + ib["其中:受限现金(预付及其他流动+其他资产) Restricted cash"][j], [25124, 94352, 53386][j])
        eq(f"{INTERIM_BS_COLS[j]} 分部商誉加总==商誉",
           ib["其中:商誉-Connectivity 分部 Goodwill-Connectivity"][j]
           + ib["其中:商誉-SI 分部(原 AI) Goodwill-SI"][j], ib["商誉 Goodwill"][j])
    # 商誉变动表（Q3 10-Q Note 6）：年初 + 企业合并 + 汇兑 = 09-30 资产负债表（企业合并 36,807 中 Cursor 36,646、Mesh Optical 158，余 3 未拆）
    eq("2026前三季 商誉变动表==资产负债表", ib["商誉 Goodwill"][0] + 36807 - 193, ib["商誉 Goodwill"][2])

    # 分部·季度：三分部加总 / 产品线加总 / 分部调整后 EBITDA 调节
    for j, col in enumerate(SEGQ_COLS):
        for metric in ("[收入]", "[经营利润]", "[资本开支]", "[折旧摊销]", "[股权激励·不含收购]",
                       "[分部调整后EBITDA·非GAAP]"):
            eq(f"{col} {metric} 三分部加总",
               sum(sq[f"{metric} {s}"][j] for s in ("Space", "Connectivity", "SI")), sq[f"{metric} 合计 Total"][j])
        eq(f"{col} Space 产品线", sq["Space-发射服务 Launch Services"][j]
           + sq["Space-发射及开发 Launch & Development"][j], sq["[收入] Space"][j])
        eq(f"{col} Connectivity 产品线", sq["Connectivity-消费者 Consumer"][j]
           + sq["Connectivity-企业及政府 Enterprise & Gov"][j], sq["[收入] Connectivity"][j])
        eq(f"{col} SI 产品线", sq["SI-广告 Advertising"][j]
           + sq["SI-方案及基础设施 SI Solutions & Infra"][j], sq["[收入] SI"][j])
        eq(f"{col} Space 调整后EBITDA调节", sq["[经营利润] Space"][j] + sq["[折旧摊销] Space"][j]
           + sq["[股权激励·不含收购] Space"][j] + sq["[减值] Space"][j], sq["[分部调整后EBITDA·非GAAP] Space"][j])
        eq(f"{col} Connectivity 调整后EBITDA调节", sq["[经营利润] Connectivity"][j]
           + sq["[折旧摊销] Connectivity"][j] + sq["[股权激励·不含收购] Connectivity"][j],
           sq["[分部调整后EBITDA·非GAAP] Connectivity"][j])
        eq(f"{col} SI 调整后EBITDA调节", sq["[经营利润] SI"][j] + sq["[折旧摊销] SI"][j]
           + sq["[股权激励·不含收购] SI"][j] + sq["[收购相关股权激励] SI"][j] + sq["[收购相关费用] SI"][j]
           + sq["[重组费用(冲回为负)] SI"][j], sq["[分部调整后EBITDA·非GAAP] SI"][j])
    # 2026：Q1(派生) + Q2 + Q3 = 前三季
    for k, v in SEGQ:
        eq(f"2026 {k} Q1+Q2+Q3=前三季", v[2] + v[3] + v[4], v[6])
    # 季度表合计 == 中期利润表（收入 / 经营利润 / D&A）
    for col in ("2026Q2", "2025Q3", "2026Q3", "2025前三季", "2026前三季"):
        jq, ji = SEGQ_COLS.index(col), ix[col]
        eq(f"{col} 季度表收入==利润表", sq["[收入] 合计 Total"][jq], ii["营业收入 Revenue"][ji])
        eq(f"{col} 季度表经营利润==利润表", sq["[经营利润] 合计 Total"][jq],
           ii["经营利润 Income (loss) from operations"][ji])
        eq(f"{col} 季度表D&A==利润表补充", sq["[折旧摊销] 合计 Total"][jq], ii["[补充] 折旧摊销 D&A"][ji])
    # 跨申报：分部营收.csv 的 H1(Q2 10-Q) + 季度表 Q3(Q3 10-Q) = 季度表前三季(Q3 10-Q)；2025 年各分部容差 2（申报间四舍五入）
    H1MAP = [("[收入] Space", "[收入] Space"), ("[收入] Connectivity", "[收入] Connectivity"),
             ("[收入] SI", "[收入] AI"), ("[经营利润] Space", "[经营利润] Space"),
             ("[经营利润] Connectivity", "[经营利润] Connectivity"), ("[经营利润] SI", "[经营利润] AI"),
             ("[资本开支] SI", "[资本开支] AI"), ("[折旧摊销] SI", "[折旧摊销] AI"),
             ("[股权激励·不含收购] Space", "[股权激励] Space"), ("[股权激励·不含收购] SI", "[股权激励] AI"),
             ("SI-方案及基础设施 SI Solutions & Infra", "AI-AI方案及算力 AI Solutions & Infra"),
             ("Connectivity-消费者 Consumer", "Connectivity-消费者 Consumer")]
    for kq, kh in H1MAP:
        for y, jh in (("2025", 3), ("2026", 4)):
            eq(f"跨申报 {y} {kq} H1+Q3=前三季", S[kh][jh] + sq[kq][SEGQ_COLS.index(f"{y}Q3")],
               sq[kq][SEGQ_COLS.index(f"{y}前三季")], tol=2)
        eq(f"2026Q1派生+Q2==H1 {kq}", sq[kq][2] + sq[kq][3], S[kh][4])

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
    eq("跨表 2026-09-30 固定资产净额", pp["固定资产净额 Net PP&E"][3], ib["固定资产净额 PP&E net"][2])

    # 经营指标：入轨质量分项 = 合计（招股书注明有四舍五入，容差放宽到 2 吨）
    oy = {k: v for k, v in OPS_Y}
    for i in range(3):
        eq(f"{YEARS[i]} 入轨质量分项", oy["入轨质量-客户载荷(公吨) customer payloads"][i]
           + oy["入轨质量-内部载荷(公吨) internal payloads"][i],
           oy["入轨质量-合计(公吨) Mass to orbit total"][i], tol=2)

    # 经营指标中期：Q1+Q2=H1、H1+Q3=前三季；客户+内部=合计
    oi = {k: v for k, v in OPS_I}
    oc = {n: i for i, n in enumerate(OPS_I_COLS)}
    FLOWS = ("Falcon 发射次数 Falcon launches", "其中客户发射 customer launches", "其中内部发射 internal launches",
             "Starship 发射次数 Starship launches", "入轨质量(公吨) Mass to orbit",
             "其中客户载荷(公吨) customer payloads", "其中内部载荷(公吨) internal payloads")
    for k in FLOWS:
        for y in ("2025", "2026"):
            eq(f"{y} {k} Q1+Q2=H1", oi[k][oc[f"{y}Q1"]] + oi[k][oc[f"{y}Q2"]], oi[k][oc[f"{y}H1"]])
            eq(f"{y} {k} H1+Q3=前三季", oi[k][oc[f"{y}H1"]] + oi[k][oc[f"{y}Q3"]], oi[k][oc[f"{y}前三季"]])
    for j, col in enumerate(OPS_I_COLS):
        eq(f"{col} 客户+内部=Falcon合计",
           oi["其中客户发射 customer launches"][j] + oi["其中内部发射 internal launches"][j],
           oi["Falcon 发射次数 Falcon launches"][j])
        # 10-Q 注明入轨质量各分项四舍五入后可能不等于合计，容差 2 吨
        eq(f"{col} 客户+内部载荷=入轨质量",
           oi["其中客户载荷(公吨) customer payloads"][j] + oi["其中内部载荷(公吨) internal payloads"][j],
           oi["入轨质量(公吨) Mass to orbit"][j], tol=2)
    # 跨源独立核：招股书正文「2026Q1 发射 40 枚 Falcon」与「入轨 556 吨」vs 由 10-Q 的 Q2/H1 反推
    eq("跨源 2026Q1 Falcon 发射数", oi["Falcon 发射次数 Falcon launches"][oc["2026Q1"]], 40)
    eq("跨源 2026Q1 入轨质量", oi["入轨质量(公吨) Mass to orbit"][oc["2026Q1"]], 556)
    # 跨源：Q3 业绩稿「Total launches」= Falcon + Starship（全部 Starship 计为内部发射）
    for col, total in (("2025Q3", 44), ("2026Q2", 38), ("2026Q3", 35), ("2025前三季", 128), ("2026前三季", 113)):
        eq(f"跨源 业绩稿总发射 {col}", oi["Falcon 发射次数 Falcon launches"][oc[col]]
           + oi["Starship 发射次数 Starship launches"][oc[col]], total)
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


def interim_rows():
    """中期财务：利润表行 + 现金流行（单季列 = 前三季 − H1 派生；Q2 单季现金流不可得留空）+ FCF + 补充披露。"""
    rows = list(INTERIM_IS)
    for k, h1, n9 in CF_ROWS:
        rows.append((k, [h1[0], h1[1], None, n9[0] - h1[0], n9[1] - h1[1], n9[0], n9[1]]))
    rows.append(("期末现金及受限现金 Cash end of period",
                 [CF_END_H1[0], CF_END_H1[1], None, CF_END_9M[0], CF_END_9M[1], CF_END_9M[0], CF_END_9M[1]]))
    cf = {k: (h1, n9) for k, h1, n9 in CF_ROWS}
    o, c = cf["经营活动现金流净额 Net cash from operating"], cf["购建固定资产 Capex"]
    f_h1 = [o[0][j] + c[0][j] for j in range(2)]
    f_9m = [o[1][j] + c[1][j] for j in range(2)]
    rows.append(("自由现金流 FCF = OCF - Capex",
                 [f_h1[0], f_h1[1], None, f_9m[0] - f_h1[0], f_9m[1] - f_h1[1], f_9m[0], f_9m[1]]))
    for k, h1, n9 in CF_SUPP:
        rows.append((k, [h1[0], h1[1], None, None, None, n9[0], n9[1]]))
    return rows


def interim_ratios():
    """中期派生比率：只在期间轴一致的列上算（单季 ÷ 单季、前三季 ÷ 前三季）。"""
    ii = dict(INTERIM_IS)
    sq = dict(SEGQ)
    ib = dict(INTERIM_BS)
    cols = ["2025Q3", "2026Q2", "2026Q3", "2025前三季", "2026前三季"]
    ji = [INTERIM_COLS.index(x) for x in cols]
    jq = [SEGQ_COLS.index(x) for x in cols]

    def r(v):
        return None if v is None else round(v, 4)

    def by_is(fn):
        return [r(fn(j)) for j in ji]

    def by_seg(fn):
        return [r(fn(q)) for q in jq]

    rev = ii["营业收入 Revenue"]
    rows = [
        ("毛利率 Gross margin", by_is(lambda j: 1 + ii["营业成本 Cost of revenue"][j] / rev[j])),
        ("经营利润率 Operating margin", by_is(lambda j: ii["经营利润 Income (loss) from operations"][j] / rev[j])),
        ("研发费用率 R&D ratio", by_is(lambda j: -ii["研发开支 Research and development"][j] / rev[j])),
        ("销售及管理费用率 SG&A ratio", by_is(lambda j: -ii["销售及行政管理 SG&A"][j] / rev[j])),
        ("折旧摊销/营收 D&A/Revenue", by_is(lambda j: ii["[补充] 折旧摊销 D&A"][j] / rev[j])),
        ("股权激励(含收购相关)/营收 SBC incl. acquisitions/Revenue",
         by_is(lambda j: (ii["[补充] 股权激励(不含收购相关) SBC ex-acquisitions"][j]
                          + ii["[补充] 收购相关股权激励 SBC related to acquisitions"][j]) / rev[j])),
        ("Capex/营收 Capex/Revenue", by_seg(lambda q: sq["[资本开支] 合计 Total"][q] / sq["[收入] 合计 Total"][q])),
        ("[非GAAP对照] 折旧摊销占调整后EBITDA比",
         by_is(lambda j: ii["[补充] 折旧摊销 D&A"][j] / ii["[非GAAP·公司口径] 调整后EBITDA Adjusted EBITDA"][j])),
    ]
    for seg in ("Space", "Connectivity", "SI"):
        rows.append((f"[分部]{seg} 经营利润率 Op margin",
                     by_seg(lambda q, s=seg: sq[f"[经营利润] {s}"][q] / sq[f"[收入] {s}"][q])))
        rows.append((f"[分部]{seg} Capex/收入 Capex/Rev",
                     by_seg(lambda q, s=seg: sq[f"[资本开支] {s}"][q] / sq[f"[收入] {s}"][q])))
    rows.append(("[分部]SI 经营利润率·加回收购相关股权激励(派生对照)",
                 by_seg(lambda q: (sq["[经营利润] SI"][q] + sq["[收购相关股权激励] SI"][q]) / sq["[收入] SI"][q])))
    # 现金流比率：单季列 = 前三季 − H1 派生；Q2 单季无现金流
    cf = {k: (h1, n9) for k, h1, n9 in CF_ROWS}

    def cf_val(k, col):
        h1, n9 = cf[k]
        y = 0 if col.startswith("2025") else 1
        if col.endswith("Q3"):
            return n9[y] - h1[y]
        if col.endswith("前三季"):
            return n9[y]
        return None

    capex_ocf = []
    for col in cols:
        o, cpx = cf_val("经营活动现金流净额 Net cash from operating", col), cf_val("购建固定资产 Capex", col)
        capex_ocf.append(None if o is None else r(-cpx / o))
    rows.append(("Capex/经营现金流 Capex/OCF(单季列为派生)", capex_ocf))
    # 回款与预收（期末余额 ÷ 当季收入，只在单季列）
    bs_at = {"2026Q2": 1, "2026Q3": 2}
    rows.append(("期末应收账款÷当季收入(单季口径)",
                 [r(ib["应收账款净额 Accounts receivable net"][bs_at[c]] / rev[INTERIM_COLS.index(c)])
                  if c in bs_at else None for c in cols]))
    rows.append(("期末合同负债÷当季收入(单季口径)",
                 [r((ib["合同负债-流动 Deferred revenue current"][bs_at[c]]
                     + ib["合同负债-非流动 Deferred revenue non-current"][bs_at[c]]) / rev[INTERIM_COLS.index(c)])
                  if c in bs_at else None for c in cols]))
    # 商誉结构（期末时点，列于当季列）
    rows.append(("期末商誉÷总资产(时点·列于当季)",
                 [r(ib["商誉 Goodwill"][bs_at[c]] / ib["资产总计 Total assets"][bs_at[c]])
                  if c in bs_at else None for c in cols]))
    rows.append(("期末SI分部商誉÷商誉(时点·列于当季)",
                 [r(ib["其中:商誉-SI 分部(原 AI) Goodwill-SI"][bs_at[c]] / ib["商誉 Goodwill"][bs_at[c]])
                  if c in bs_at else None for c in cols]))
    return cols, rows


def main():
    errs = checks()
    if errs:
        print(f"✗ 勾稽校验未通过（{len(errs)} 条），不写出 CSV：")
        for e in errs:
            print("   -", e)
        raise SystemExit(1)
    print(f"✓ 勾稽校验全部通过：执行 {STATS['run']} 条，因空值跳过 {len(STATS['skipped'])} 条")
    for s in STATS["skipped"]:
        print("    · 跳过:", s)

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
          f"年度来自招股书分部附注, H1 来自 10-Q; {src}; "
          "⚠️ AI 分部自 2026Q3 更名 SI(Super Intelligence)、口径连续; 单季与前三季见 分部营收-季度.csv", SEG_COLS, SEGMENT)
    write(OUT / "分部营收-季度.csv",
          "# 单位: 百万美元(USD millions); 来源: Q2 10-Q(2026-08-04) 分部附注三个月列 + Q3 10-Q(2026-10-22) 分部附注 "
          "+ 两份 10-Q 非 GAAP 分部调节表; ⚠️ 2026Q1 列 = 2026H1(Q2 10-Q) − 2026Q2 **派生**, 合计已与招股书 Q1 原值"
          "(收入 4,694 / 经营亏损 1,943)核对一致; SI = 原 AI 分部(2026Q3 更名, 含 2026-07-06 起的 Mesh Optical 与 "
          "2026-08-14 起的 Cursor); 「股权激励·不含收购」与「收购相关股权激励」为两份 10-Q 的分列口径; "
          "调整后EBITDA 为公司非 GAAP 口径(加回折旧摊销与全部股权激励)",
          SEGQ_COLS, SEGQ)
    write(OUT / "中期财务-2026.csv",
          "# 单位: 百万美元(USD millions), 费用/减项=负数, 所得税收益=正数; 来源: Q2 10-Q(2026-08-04)·Q3 10-Q(2026-10-22); "
          "期间轴: H1 / 单季(2026Q2·2025Q3·2026Q3) / 前三季——**跨列比较前先认期间**; "
          "⚠️ 现金流量表只有累计期间: 单季(Q3)列 = 前三季 − H1 **派生**, 2026Q2 单季现金流不可得留空; "
          "补充披露的「已购未付固定资产」为期末余额(非期间流量); IPO 于 2026-06-15 交割故 H1 含巨额一次性融资项",
          INTERIM_COLS, interim_rows())
    write(OUT / "中期资产负债表-2026.csv",
          "# 单位: 百万美元(USD millions), 股数=百万股; 时点数; 来源: Q2 10-Q(2026-08-04)·Q3 10-Q(2026-10-22); "
          "受限现金 = 预付及其他流动资产 + 其他资产中的受限现金(与现金流量表期末口径衔接); "
          "分部商誉取两份 10-Q Note 6 正文(Space 分部无商誉); 2026 前三季商誉变动 = 企业合并 36,807 "
          "(Cursor 36,646 + Mesh Optical 158 + 其他 3·10-Q 未拆) + 汇兑 −193, 无减值",
          INTERIM_BS_COLS, INTERIM_BS)
    icols, irows = interim_ratios()
    write(OUT / "中期比率-2026.csv",
          "# 派生比率(比率=小数); 由 中期财务-2026.csv / 分部营收-季度.csv / 中期资产负债表-2026.csv 派生; "
          "只在期间一致的列上计算(单季÷单季、前三季÷前三季); Capex/OCF 单季列的 OCF 为 前三季−H1 派生; "
          "「SI 经营利润率·加回收购相关股权激励」仅为剔除 Cursor 收购股权激励影响的对照, 非公司披露口径",
          icols, irows)

    write(OUT / "固定资产明细.csv",
          "# 单位: 百万美元(USD millions); **原值(gross)**, 累计折旧单列; "
          "来源: 招股书 PP&E 附注(2024/2025) + Q2 10-Q Note 5(2026-06-30) + Q3 10-Q Note 5(2026-09-30); "
          "净额已与资产负债表跨表核对一致 || "
          "折旧年限(招股书会计政策附注): 服务器及网络设备 5-6年 · 卫星 3-5年 · 机器设备 3-10年 · "
          "飞行器硬件 5-25次飞行(按次而非按年) · 数据中心基础设施 20-25年 · 发射场 7-20年 · "
          "房屋及改良 30年 · 租赁资产改良 取7-20年与租期孰短 || "
          "在建工程口径(Q3 10-Q Note 5原文): 主要为**尚未投用的服务器及网络设备与数据中心基础设施**; "
          "Q3 资本化利息 119、前三季 139",
          PPE_COLS, PPE)

    # ---- 派生回流：折旧测算（分析过程算出，按项目纪律回写 财务数据/）
    # 口径：以 2026-09-30 **原值**为基数 ÷ 招股书披露的折旧年限区间 → 年化折旧区间
    # 局限：① 附注只给**合计**累计折旧、未按类别拆分，故无法按净值测算，用原值会高估已折旧殆尽的老资产
    #       ② 飞行器硬件按**飞行次数**折旧(5-25次)，非按年，无法年化 → 单列不参与合计
    #       ③ 土地不计提折旧，但「土地房屋及改良」未拆分土地 → 该行为上限
    #       ④ 在建工程尚未投用、当前不计提 → 单列为「尚未启动的折旧池」
    pp = dict(PPE)
    j930 = PPE_COLS.index("2026-09-30")
    LIVES = [
        ("服务器及网络设备", "服务器及网络设备 Servers and networking equipment", 5, 6),
        ("卫星", "卫星 Satellites", 3, 5),
        ("机器设备", "机器设备 Machinery and equipment", 3, 10),
        ("数据中心基础设施", "数据中心基础设施 Data center infrastructure", 20, 25),
        ("发射场", "发射场 Launch sites", 7, 20),
        ("土地房屋及改良(含不折旧的土地·上限)", "土地房屋及改良 Land, buildings and improvements", 30, 30),
        ("租赁资产改良", "租赁资产改良 Leasehold improvements", 7, 20),
    ]
    dep_rows = []
    tot_g = tot_hi = tot_lo = 0
    for name, key, lo_y, hi_y in LIVES:
        gross = pp[key][j930]
        hi = round(gross / lo_y)   # 年限下限 → 年折旧上限
        lo = round(gross / hi_y)
        mid = round(gross / ((lo_y + hi_y) / 2))
        dep_rows.append((name, [gross, lo_y, hi_y, lo, hi, mid]))
        tot_g += gross
        tot_hi += hi
        tot_lo += lo
    dep_rows.append(("【小计】可年化折旧资产", [tot_g, "", "", tot_lo, tot_hi,
                     round(sum(r[1][5] for r in dep_rows))]))
    dep_rows.append(("飞行器硬件(按5-25次飞行折旧·不可年化)", [pp["飞行器硬件 Flight vehicle hardware"][j930], "", "", "", "", ""]))
    dep_rows.append(("在建工程(尚未投用·当前不计提)", [pp["在建工程 Construction-in-progress"][j930], "", "", "", "", ""]))
    dep_rows.append(("固定资产原值合计 Gross PP&E", [pp["固定资产原值 Gross PP&E"][j930], "", "", "", "", ""]))
    ii = dict(INTERIM_IS)
    dep_q3 = ii["[补充] 其中:固定资产折旧 Depreciation"][INTERIM_COLS.index("2026Q3")]
    dep_9m = ii["[补充] 其中:固定资产折旧 Depreciation"][INTERIM_COLS.index("2026前三季")]
    dep_rows.append(("【对照】2026Q3 实际固定资产折旧×4(年化)", ["", "", "", "", "", dep_q3 * 4]))
    dep_rows.append(("【对照】2026H1 实际固定资产折旧×2(年化·前三季−Q3)", ["", "", "", "", "", (dep_9m - dep_q3) * 2]))
    dep_rows.append(("【对照】FY2025 实际折旧摊销 D&A(含无形摊销)", ["", "", "", "", "", 6701]))
    write(OUT / "折旧测算.csv",
          "# **派生估算·非披露值**; 单位: 百万美元(USD millions), 年限=年; "
          "基数=2026-09-30 固定资产**原值**(见 固定资产明细.csv), 年限=招股书会计政策附注披露区间; "
          "局限: 累计折旧未按类别披露故按原值测算(高估老资产) · 飞行器硬件按飞行次数折旧不可年化 · "
          "土地不折旧但未单独拆分 · 在建工程尚未投用不计提; 对照行的「实际折旧」取 Q3 10-Q Note 5 固定资产折旧费用(不含无形摊销)",
          ["原值(2026-09-30)", "年限下限", "年限上限", "年化折旧(按年限上限)",
           "年化折旧(按年限下限)", "年化折旧(按年限中值)"], dep_rows)

    # ---- 会计估计敏感性（424B4 关键会计估计·原文披露值，非派生）
    SENS_COLS = ["FY2025", "2026Q1", "原文要点"]
    SENS = [
        ("卫星平均可用寿命每变动一年 → 经营利润影响(百万美元)", [480, 170,
         "If the average useful life of our satellite assets had been changed by one year, it would have an approximately "
         "$480 million and $170 million impact on our operating income"]),
        ("飞行器与航天器估计飞行次数 ±5 次 → 经营利润影响", ["不重大", "不重大",
         "five more or fewer flights ... would not be material"]),
    ]
    write(OUT / "会计估计敏感性.csv",
          "# 来源: 424B4 关键会计估计章节(原文披露值·非派生); 单位: 百万美元(USD millions); "
          "Q2/Q3 10-Q 称除云服务与企业合并外会计政策无重大变化、未披露新的敏感性; "
          "同业先例(Alphabet 服务器年限 2021/2023 两次延长的影响额)见 finance/google/财务数据/PPE明细.csv「会计估计变更」段",
          SENS_COLS, SENS)

    # ---- 关联交易明细（招股书「CERTAIN RELATIONSHIPS AND RELATED PERSON TRANSACTIONS」章节 + 10-Q Note 17）
    # 口径：Item 404 of Reg S-K，覆盖 2023-01-01 起、金额 >$120,000 且关联方有直接/间接重大利益的交易。
    # 因 xAI Merger 采同一控制追溯合并，本章节亦纳入 xAI / X Holdings 在合并前签订且仍在存续的协议。
    RPT_COLS = ["2023", "2024", "2025", "2026年1-4月", "2026Q3", "2026前三季", "2026-09-30时点", "合同总额/备注"]
    RPT_OLD = [
        ("【Valor·董事 Antonio Gracias 关联】设备租赁1-合同总额", [None, None, None, None, 6986]),
        ("【Valor】设备租赁2-合同总额",                          [None, None, None, None, 6633]),
        ("【Valor】设备租赁3-合同总额",                          [None, None, None, None, 6587]),
        ("【Valor】三份租赁合同总额合计",                        [None, None, None, None, 20206]),
        ("【Valor】已付租金",                                   [None, None, 885, 1917, None]),
        ("【Valor】X API 服务收入(公司收)",                      [None, 1, 1, 0.1, None]),
        ("【Tesla】SpaceX 采购商品及服务",                       [11, 4, 147, 4.0, None]),
        ("【Tesla】xAI 采购商品及服务",                          [None, 191, 506, 303, "2026年1-4月含4月Megapack 269"]),
        ("【Tesla】xAI 自 Tesla 确认收入",                       [None, None, 2, 1, None]),
        ("【Tesla】X 平台广告收入(公司收)",                      [None, 0.5, 4, 0.1, None]),
        ("【Tesla】飞机使用费(公司收)",                          [1, 1, 2, 0, None]),
        ("【The Boring Co·Musk 关联】X 办公室租金",              [None, 0.1, 1, 0.3, None]),
        ("【The Boring Co】隧道建设支出",                        [None, None, 1, None, None]),
        ("【Musk Industries LLC】xAI 房产租金",                  [None, 0.5, 2, 1, None]),
        ("【Musk 持有的安保公司】安保服务支出",                   [2, 3, 4, 2, None]),
        ("【Craft Aviation·Musk 关联】飞机维护支出",              [1, 1, 3, 3, None]),
        ("【Musk 私人飞机】公司报销",                            [0.1, 3, 2, 0.2, None]),
        ("【Shotwell/Johnsen 共有飞机】公司承担运维",             [3, 3, 3, 1, None]),
    ]
    RPT = [(k, v[:4] + [None, None, None] + v[4:]) for k, v in RPT_OLD]
    RPT += [
        ("【Tesla】Megapack 采购(10-Q·计入固定资产)",            [None, None, None, None, 151, 480, None, None]),
        ("【Valor】失败售后租回利息支出(10-Q)",                   [None, None, None, None, 351, 864, None, None]),
        ("【Valor】失败售后租回债务余额(期末·10-Q)",             [None, None, None, None, None, None, 12897, None]),
        ("【The Boring Co·CEO 拥有控制性表决权】公允价值未实现收益(计入其他收入)",
         [None, None, None, None, 561, 561, None, "9 月 TBC 新一轮融资后按可观察价格重估·公允价值选择权"]),
        ("【关联方】其他资产中的关联方余额(期末·10-Q 未说明构成)", [None, None, None, None, None, None, 570, None]),
    ]
    write(OUT / "关联交易.csv",
          "# 单位: 百万美元(USD millions); 来源: 424B4「CERTAIN RELATIONSHIPS AND RELATED PERSON TRANSACTIONS」章节"
          "(2023—2026年1-4月) + Q3 10-Q Note 8 / Note 17(2026Q3·前三季·09-30); "
          "口径=Item 404 Reg S-K(2023-01-01 起·>$120,000·关联方有重大利益), 含 xAI/X 合并前签订且仍存续的协议; "
          "⚠️ **定价公允性表述不对称**: Tesla 类交易招股书明写「on terms no less favorable to SpaceX than those "
          "generally available to unaffiliated third parties」, **Valor 三份设备租赁无任何公允性表述**, 仅列金额; "
          "⚠️ Valor 租赁由 SpaceX 或其子公司**提供付款与履约担保**, 会计上被判定为**失败的售后租回**故全额计为债务; "
          "⚠️ 关联交易审批政策(审计委员会审议+关联方回避)为「**将在本次发行完成时采纳**」, 即 Valor 三笔签署时该政策尚不存在; "
          "Q3 10-Q 称其余与 Tesla 及其他关联方的交易金额不重大",
          RPT_COLS, RPT)

    # ---- 或有事项与未反映的重大承诺
    CONT_COLS = ["金额", "币种", "状态/时点"]
    CONT = [
        ("诉讼损失计提-2025-12-31(424B4 经审计附注)", [530, "USD-M", "计入应计及其他流动负债与其他负债"]),
        ("诉讼损失计提-2026-03-31(424B4 中期附注)",   [399, "USD-M", ""]),
        ("诉讼损失计提-2026-06-30(Q2 10-Q)",          [354, "USD-M", ""]),
        ("诉讼损失计提-2026-09-30(Q3 10-Q)",          [350, "USD-M", "⚠️ Q3 10-Q 将 2025-12-31 比较数写作 399, 与 424B4 经审计附注 530 不符; 399 实为 424B4 所载 2026-03-31 数【疑·申报人比较列笔误或口径变动, 以经审计 530 为准】"]),
        ("EC DSA 罚款(X/xAI/Musk 本人)",              [120, "EUR-M", "2025-12-05 终局决定; 2026-02-16 上诉欧盟普通法院; 2026-07~08 美国、爱尔兰等多方申请介入, 09-22 各方就介入申请提交意见; 待决"]),
        ("Vidstream 专利-陪审团判赔",                  [105, "USD-M", "2025-04-16 判决; X Corp. 上诉、Vidstream 交叉上诉, 联邦巡回法院待决"]),
        ("Vidstream 专利-判决前利息",                  [67, "USD-M", "2025-11 追加"]),
        ("SDBN 荷兰 GDPR 集体诉讼",                    [None, "EUR/人250-2500", "称代表1100万荷兰用户; 2026-02-04 法院不准以集体诉讼推进·拟中止待欧盟法院裁决; 03-04 X 方提交支持中止的意见"]),
        ("SOMI 荷兰 GDPR/DSA 集体诉讼",                [None, "未定", "称代表约780万荷兰X用户; 2026-05-27 法院认定 SOMI 满足多数受理要件但未证明财务保障要件; 06-24 补充材料、07-29 X 方回应; 待裁"]),
        ("Grok 图像生成相关诉讼",                      [None, "未定", "加州北区多起拟制集体诉讼(09-28 法院驳回移送德州与中止动议) + 阿肯色西区个人诉讼(10-02 原告申请 JPML 合并) + 巴尔的摩市(已撤回对 SpaceX 母公司起诉·X/SpaceXAI 申请驳回) + 弗吉尼亚州总检察长 10-19 违规通知"]),
        ("Grok.com 跟踪技术隐私集体诉讼",              [None, "未定", "2026-05-14 起诉 SpaceXAI LLC; 08-10 申请驳回起诉; 08-13 法院驳回移送德州动议"]),
        ("NAACP《清洁空气法》诉讼(COLOSSUS II 燃气轮机)", [None, "未定", "2026-04-14 起诉 X.AI Corp. 与 MZX Tech; 05-06 申请初步禁令停运; 10-19 地区法院准许美国政府介入但未准驳回"]),
        ("SaS 专利诉讼(X Corp.)",                      [None, "未定", "2025-09 起诉; X Corp. 申请复审(IPR), 2026-07-14 两项复审均获立案"]),
        ("孟菲斯算力设施施工纠纷-公司主张",            [500, "USD-M(以上)", "2026-08 SpaceXAI 等起诉 Darana Hybrid 等违约及欺诈, 主张损失逾 500"]),
        ("孟菲斯算力设施施工纠纷-对方反诉及留置权",     [569, "USD-M(约)", "被告否认并反诉, 登记施工留置权约 569"]),
        ("密西西比环境质量部雨水许可违规(MZX Tech)",   [6.1, "USD-M(初步)", "2026-08 违规通知, 三处工地; 公司协商统一和解令"]),
        ("NMPA 音乐版权诉讼",                          [None, "—", "2026-07-16 双方约定撤回全部诉求·结案"]),
        ("信用证(以受限现金担保)",                     [1470, "USD-M", "2026-09-30"]),
        ("担保债券(工伤自保及政府许可等)",             [470, "USD-M", "2026-09-30"]),
        ("不可撤销合同承诺(主要为 SI 基础设施与第三方云容量)", [37840, "USD-M", "2026-09-30(06-30 为 27,955); 其中 2027 年 25,569; 分年见 到期与承诺排期.csv"]),
        ("【未反映·股本】EchoStar 频谱交易-对价股数(百万股)", [261.79, "Class A 百万股", "总对价约 196 亿: 约 111 亿股权(固定价 $42.40/股, 于第二步交割时发行) + 最多 85 亿用于清偿 EchoStar 指定债务; 第一步交割 2026-05-22(牌照入信托); 公司预计第二步 2027-11-30; 信用协议付款 2026 全年 1,241(截至 09-30 已付 856)、2027 年 828, 若延至 2028-11-30 需再付 827"]),
        ("【未反映·对价未披露】800 MHz 频谱牌照组合", [None, "—", "2026-10-08 签约, 最多 14 MHz 成对频谱; 预计 2027 上半年交割"]),
        ("【已完成·已入表】Cursor(Anysphere) 收购-购买对价", [42474, "USD-M", "2026-08-14 交割; 2.71 亿股 × $141.29 = 38,293 + 替代奖励 4,181; 8-K 口径共发行 389,289,254 股 + 已归属 RSU 1,752,426 股; 另 23,376 股权奖励归属交割后服务、计入未来股权激励; 商誉 36,646(暂估·全部归 SI)"]),
        ("【已完成·已入表】Mesh Optical 收购-购买对价",   [249, "USD-M", "2026-07-06 交割, 全部以 A 类股支付, 商誉 158"]),
    ]
    ib = dict(INTERIM_BS)
    j930b = INTERIM_BS_COLS.index("2026-09-30")
    sh_ab = ib["A 类普通股流通股数(百万股) Class A shares outstanding"][j930b] + ib["B 类普通股流通股数(百万股) Class B shares outstanding"][j930b]
    write(OUT / "或有事项与承诺.csv",
          "# 来源: 424B4 法律或有事项附注 + 招股书「本招股书未反映」段落 + Q2/Q3 10-Q Note 6/9/16/20 + Q3 业绩稿(800 MHz); "
          "⚠️ 截至 2026-09-30 仍未反映在股数中的只剩 EchoStar 一项(Cursor 已于 08-14 交割入表); "
          f"其约 2.618 亿股相对 2026-09-30 A+B 流通股 {sh_ab} 百万股约 {261.79 / sh_ab:.1%}【推·派生】",
          CONT_COLS, CONT)

    # ---- 合同储备(backlog) 与 客户集中度（10-Q Note 3 收入附注 + Note 17 关联方）
    BL_COLS = ["2025Q2", "2026Q2", "2025H1", "2026H1", "2025Q3", "2026Q3", "2025前三季", "2026前三季",
               "2026-06-30时点", "2026-09-30时点"]
    rev_of = {"2025Q2": 4071, "2026Q2": 7814, "2025H1": 8138, "2026H1": 12508,
              "2025Q3": 5576, "2026Q3": 14575, "2025前三季": 13714, "2026前三季": 27083}
    si_infra = {"2026Q2": 2194, "2026H1": 2669, "2026Q3": 7022, "2026前三季": 9691}
    cust_a = {"2025Q2": 0.167, "2026Q2": 0.183, "2025H1": 0.199, "2026H1": 0.179,
              "2025Q3": 0.239, "2026Q3": 0.166, "2025前三季": 0.216, "2026前三季": 0.173}
    cust_b = {"2026Q2": 0.195, "2026H1": 0.122, "2026Q3": 0.345, "2026前三季": 0.242}

    def per(d):
        return [d.get(c) for c in BL_COLS]

    b_amt = {c: round(v * rev_of[c]) for c, v in cust_b.items()}
    a_amt = {c: round(v * rev_of[c]) for c, v in cust_a.items()}
    BACKLOG = [
        ("合同储备 Backlog 总额",                    per({"2026-06-30时点": 47461, "2026-09-30时点": 62959})),
        ("其中:已列为合同负债 of which deferred revenue", per({"2026-06-30时点": 14286, "2026-09-30时点": 17520})),
        ("合同储备-1年内确认占比",                     per({"2026-06-30时点": 0.56, "2026-09-30时点": 0.67})),
        ("合同储备-1至3年确认占比",                    per({"2026-06-30时点": 0.34, "2026-09-30时点": 0.27})),
        ("合同储备-3年以上确认占比",                   per({"2026-06-30时点": 0.10, "2026-09-30时点": 0.06})),
        ("合同负债(递延收入)总额",                     per({"2026-06-30时点": 14286, "2026-09-30时点": 17520})),
        ("客户A占合并收入比(横跨全部分部)",             per(cust_a)),
        ("客户B占合并收入比(仅AI/SI分部)",             per(cust_b)),
        ("[派生] 客户A收入额(占比×当期收入)",           per(a_amt)),
        ("[派生] 客户B收入额(占比×当期收入)",           per(b_amt)),
        ("[派生] 客户B占SI方案及基础设施收入比",        per({c: round(b_amt[c] / si_infra[c], 3) for c in cust_b})),
        ("单一客户占应收账款比(期末·10-Q 未具名)",      per({"2026-09-30时点": 0.277})),
        ("[派生] 该客户应收额(占比×期末应收)",          per({"2026-09-30时点": round(0.277 * 4772)})),
        ("关联方债务-Valor设备租赁(失败售后租回)",       per({"2026-06-30时点": 13329, "2026-09-30时点": 12897})),
        ("关联方利息支出-Valor",                      per({"2026Q2": 327, "2026H1": 513, "2026Q3": 351, "2026前三季": 864})),
        # 派生：Q3 单季利息 ×4 ÷ 期初期末平均余额（两端余额量级相近，平均法误差小）；对照 SpaceX Notes 实际利率 6.072%、
        # 10-Q 所述其他融资加权固定利率 6.3%（10-Q 未说明后者是否涵盖 Valor 失败售后租回）
        ("[派生] Valor 融资隐含年化利息成本(Q3 利息×4÷平均余额)",
         per({"2026Q3": round(351 * 4 / ((13329 + 12897) / 2), 3)})),
    ]
    write(OUT / "合同储备与客户集中.csv",
          "# 单位: 百万美元(USD millions), 占比=小数; 来源: Q2 10-Q(2026-08-04)·Q3 10-Q(2026-10-22) 收入附注 + 关联方附注 Note 17; "
          "口径: Backlog=已达成可执行合同中尚未履约部分的交易价格, **不含**按交付即确认的部分/非重大选择权/受约束的可变对价; "
          "客户A/B 公司**未具名**(客户B 2025 年各期不足 10% 故空白); 「单一客户占应收」10-Q 未说明是否即客户A或B; "
          "关联方债务对手方=Valor Equity Partners(董事 Antonio Gracias 为其创始人兼CEO/CIO), "
          "该等设备租赁被判定为**失败的售后租回**故全额计为债务",
          BL_COLS, BACKLOG)

    # ---- 债务明细（Q3 10-Q Note 9）
    DEBT_COLS = ["2025-12-31本金", "2025-12-31账面净额", "2026-09-30本金", "2026-09-30账面净额"]
    DEBT = [
        ("SpaceX Notes(2026-06 发行五档·加权票息5.855%·实际利率6.072%·2031-2056 到期)", [None, None, 25000, 24855]),
        ("X 2027/2030 Notes(3.875%/5.000%)",            [27, 27, 27, 27]),
        ("X B-1 Term Loan(SOFR+6.50%·2026-03-02 提前偿还)", [6504, 6224, None, None]),
        ("X B-3 Term Loan(固定9.50%·2026-03-02 提前偿还)",  [5966, 5912, None, None]),
        ("xAI Fixed Rate Term Loan(12.50%·2026-03-02 提前偿还)", [995, 991, None, None]),
        ("xAI Floating Rate Term Loan(SOFR+7.25%·2026-03-02 提前偿还)", [995, 955, None, None]),
        ("xAI 12.5% Secured Senior Notes(2026-03-05 提前偿还)", [3000, 2988, None, None]),
        ("Other financings(含 Valor 失败售后租回; 10-Q 称「各类其他融资安排」加权固定利率 2025末5.5%/2026-09-30 6.3%, 未说明是否涵盖失败售后租回)", [4562, 4562, 12979, 12979]),
        ("有息债务合计 Total debt",                      [22049, 21659, 38006, 37861]),
        ("融资租赁负债 Finance lease liability",          [1237, 1237, 983, 983]),
        ("有息负债及融资租赁合计",                        [23286, 22896, 38989, 38844]),
        ("其中:一年内到期",                              [928, 928, 2698, 2698]),
        ("其中:一年以上",                                [22358, 21968, 36291, 36146]),
        ("其中:关联方 Valor(失败售后租回·账面)",          [None, 4507, None, 12897]),
        ("[公允价值·Level II] SpaceX Notes",              [None, None, None, 22932]),
        ("[未提用授信] SpaceX Credit Facility(2026-05 增至 5,000·2031-05-19 到期)", [1500, None, 5000, None]),
        ("[未提用授信] xAI 循环授信",                     [None, None, 250, None]),
    ]
    write(OUT / "债务明细.csv",
          "# 单位: 百万美元(USD millions); 来源: Q3 10-Q Note 9(两个时点均取该附注) + 资产负债表; "
          "2026-03 以 200 亿过桥贷款提前偿还 X/xAI 高息债(提前还款罚金 425 + 221 + 518, 清偿损失 1,526), "
          "2026-06 以 SpaceX Notes 偿还过桥贷款(清偿损失 18); 截至 2026-09-30 **无浮动利率债务**; "
          "SpaceX Notes 契约限制新增担保负债超过合并总资产 7.5%",
          DEBT_COLS, DEBT)

    # ---- 到期与承诺排期（Q2/Q3 10-Q Note 9 / Note 16）
    SCH_COLS = ["2026剩余", "2027", "2028", "2029", "2030", "以后", "合计"]
    SCHED = [
        ("债务本金到期(2026-09-30)",                    [495, 2425, 2867, 3422, 3597, 25200, 38006]),
        ("不可撤销合同承诺(2026-09-30)",                [2309, 25569, 4637, 2071, 1221, 2033, 37840]),
        ("不可撤销合同承诺(2026-06-30·Q2 10-Q)",         [2728, 22244, 2172, 809, 2, 0, 27955]),
    ]
    write(OUT / "到期与承诺排期.csv",
          "# 单位: 百万美元(USD millions); 来源: Q3 10-Q Note 9(债务本金到期) / Q2·Q3 10-Q Note 16(不可撤销合同承诺: "
          "主要为 SI 基础设施投资与第三方云容量安排, 亦含 EchoStar 频谱交易的现金与股份承诺); "
          "06-30 口径的「2026剩余」为六个月、09-30 口径为三个月",
          SCH_COLS, SCHED)

    # ---- 派生回流：SI(原 AI) 分部折旧情景（在建工程转固后的年化折旧）
    # 已知（一手）：2026-09-30 在建工程 23,745；服务器 43,206(5-6y)；数据中心基础设施 6,333(20-25y)
    #              SI 分部 Q3-2026 折旧摊销 2,473（年化 9,892·含 Cursor 无形资产摊销）；SI 分部 Q3 单季资本开支 16,444
    # 未知（须假设·10-Q 未披露）：① 在建工程中 SI 占比 ② 转固后在「服务器 5.5y」与「数据中心基建 22.5y」间的分配
    sq = dict(SEGQ)
    CIP = pp["在建工程 Construction-in-progress"][j930]
    SERV = pp["服务器及网络设备 Servers and networking equipment"][j930]
    SERV_PREV = pp["服务器及网络设备 Servers and networking equipment"][PPE_COLS.index("2026-06-30")]
    DCI = pp["数据中心基础设施 Data center infrastructure"][j930]
    SI_DA_Q3 = sq["[折旧摊销] SI"][SEGQ_COLS.index("2026Q3")]
    SI_DA_FY25 = 3568
    SERV_L, DC_L = 5.5, 22.5
    #   路径A 资产类别法 = 服务器/5.5 + 数据中心基建/22.5（不含机器设备与无形摊销归属 SI 的部分）
    run_a = round(SERV / SERV_L + DCI / DC_L)
    #   路径B 分部实际法 = 服务器期末值/5.5 + (Q3 实际年化 − Q3 服务器平均基数折旧年化)
    serv_avg = (SERV_PREV + SERV) / 2
    other_si = round(SI_DA_Q3 * 4 - serv_avg / SERV_L)     # 机器设备+数据中心+无形摊销中归 SI 的部分（含 Cursor 无形资产摊销）
    run_b = round(SERV / SERV_L + other_si)
    SCEN = [("低", 0.70, 0.30), ("中", 0.85, 0.60), ("高", 1.00, 0.90)]
    ai_rows = [
        ("[输入·一手] 在建工程总额 CIP(2026-09-30)", [CIP, CIP, CIP]),
        ("[输入·一手] 服务器及网络设备(在役·2026-09-30)", [SERV, SERV, SERV]),
        ("[输入·一手] SI分部 2026Q3 折旧摊销×4(年化)", [SI_DA_Q3 * 4] * 3),
        ("[输入·一手] AI分部 FY2025 折旧摊销", [SI_DA_FY25] * 3),
        ("[假设] 在建工程中 SI 占比", [s[1] for s in SCEN]),
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
        ("【结果】转固后 SI 分部年化折旧-下限(路径A)", lo_t),
        ("【结果】转固后 SI 分部年化折旧-上限(路径B)", hi_t),
        ("[对照] 相对 FY2025 实际的倍数-下限", [round(v / SI_DA_FY25, 2) for v in lo_t]),
        ("[对照] 相对 FY2025 实际的倍数-上限", [round(v / SI_DA_FY25, 2) for v in hi_t]),
    ]
    write(OUT / "折旧测算-AI分部.csv",
          "# **派生情景估算·非披露值·非预测**; 单位: 百万美元(USD millions); "
          "口径: 假设自 2026-09-30 起**资本开支归零**、仅现有在役资产 + 在建工程转固 → 故为**下限/地板值**; "
          "两项关键假设(10-Q 未披露): 在建工程中 SI 占比 · 转固后在服务器(5.5年)与数据中心基建(22.5年)间的分配; "
          "路径B 的「其他」部分含 2026-08 起 Cursor 无形资产摊销; "
          f"参考: SI 分部 2026Q3 单季资本开支 {sq['[资本开支] SI'][SEGQ_COLS.index('2026Q3')]:,} —— 只要投入不停, 实际值必高于本表",
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
          "# 经营(非财务)指标; 来源: Q2 10-Q(2026-08-04)·Q3 10-Q(2026-10-22) Key Business Metrics + 招股书(2026Q1); "
          "Q1 列由 H1−Q2 反推, 已与招股书「2026Q1 发射 40 枚 Falcon」「入轨 556 吨」交叉核对一致; "
          "「Starlink 消费者订阅数/ARPU」即原「Starlink 订阅数/ARPU」(Q3 10-Q 更名·定义未变·不含签约管理的企业与政府客户); "
          "Starship 发射全部计为内部发射, 业绩稿「总发射」= Falcon + Starship; 入轨质量分项四舍五入后可能与合计差 1-2 吨",
          OPS_I_COLS, OPS_I)


if __name__ == "__main__":
    main()
