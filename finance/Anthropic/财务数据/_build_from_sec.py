#!/usr/bin/env python3
"""Anthropic, PBC（拟 Nasdaq: ANT·未上市）财务数据建库

一手真源（report/Anthropic/）：
  - 招股说明书-S-1-20261026.htm   SEC Form S-1，2026-10-26 公开递交（accession 0001628280-26-067168，
      受理 2026-10-26 09:00:11 美东），**初步招股书**：发行股数、价格区间、2026Q3 金额均留空待修订。
      F 页：FY2023/FY2024 经 Grant Thornton 审计、FY2025 经 Ernst & Young 审计（两份报告均 2026-06-01，
      拆股部分双签 2026-09-30）；2026-06-30 资产负债表与 H1 两期利润表/现金流**未经审计**。
      MD&A 另给 2025Q1-2026Q2 六个单季利润表（未经审计）与非 GAAP 调节。

口径要点（务必与 README.md 同步）：
  1. 单位：百万美元（USD millions）；股数单位见各行（千股 / 股）。
  2. 符号：费用/减项/流出 = 负数；所得税以对净利的影响记（费用为负）。
  3. 利润表按「费用性质」列报（公司 2025 年由职能法改为性质法并追溯重分类，F-14 附注 1）——
     **利润表本身没有营业成本/毛利行**；职能口径（营业成本/研发/销售/管理）只在附注 8 补充披露，
     落 `费用按职能.csv`，毛利率由此派生。
  4. 净亏损被「可转债公允价值变动」主导：可转债选用公允价值法（ASC 825），公司估值越高、亏损越大，
     非现金。看经营看「经营利润」与「调整后」口径，不看净利（README 顶部警告）。
  5. 股数/每股数已按 2026-09-17 A/N 类 10:1 拆股（T 类 1:1000 反向拆股）追溯调整（附注 1）。
  6. FY2023 资产负债表：S-1 只列报 2024/2025 年末，2023 年末除权益变动表外不可得 → 不建列。

写出前跑全部勾稽，任一不过则 SystemExit(1)、不写出 CSV。
`--mutate`：逐格 +1 重跑全部勾稽，统计「改了也没有任何一条勾稽报错」的格子（= 单源未交叉核），
            用来证明闸门真的在看这些数（见 memory: verify-gate-tolerance-mutation-test）。
"""
import copy
import csv
import pathlib
import sys

OUT = pathlib.Path(__file__).parent
SRC = "SEC Form S-1(2026-10-26, accession 0001628280-26-067168)"

T = {}          # 表名 -> {"cols": [...], "rows": [[科目, [值...]], ...], "header": str, "file": str|None}
STATS = {"run": 0, "skipped": []}


def table(name, cols, rows, header, file=None):
    T[name] = {"cols": cols, "rows": [[k, list(v)] for k, v in rows], "header": header, "file": file}


def g(tname, row, col):
    t = T[tname]
    j = t["cols"].index(col)
    for k, vals in t["rows"]:
        if k == row:
            return vals[j]
    raise KeyError(f"{tname}: 无此科目 {row}")


def rowv(tname, row):
    for k, vals in T[tname]["rows"]:
        if k == row:
            return vals
    raise KeyError(f"{tname}: 无此科目 {row}")


def lv(tname, row, when):
    """长表取值：科目 + 时点/期间（第 2 列）定位一行，返回「值」列。勾稽一律经由 T 取数，变异对照才看得见。"""
    for k, vals in T[tname]["rows"]:
        if k == row and vals[1] == when:
            return vals[0]
    raise KeyError(f"{tname}: 无此科目 {row} @ {when}")


Y = ["2023", "2024", "2025"]
H = ["2025H1", "2026H1"]
Q = ["2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2"]
P5 = Y + H                                   # 年度 + 半年度（职能拆分 / 收入拆分 / 客户集中用）

# ====================================================================== 利润表（年度·经审计）
# 源：F-7 Consolidated Statements of Operations（table idx 108）；F-8 综合亏损表（idx 109）
IS_ROWS = [
    ("营业收入 Revenue",                                        [41, 386, 4585]),
    ("算力与基础设施 Compute and infrastructure",                 [-433, -2522, -7326]),
    ("人员开支 Personnel",                                       [-95, -454, -1839]),
    ("Bartz和解费用 Bartz settlement",                           [0, 0, -1500]),
    ("销售营销与合作伙伴 Sales, marketing, and partnerships",       [-2, -43, -568]),
    ("其他运营与行政 Other operating and administrative",          [-62, -347, -1412]),
    ("经营费用合计 Total operating expenses",                     [-592, -3366, -12645]),
    ("经营利润 Operating loss",                                  [-551, -2980, -8060]),
    ("利息收入 Interest income",                                 [69, 106, 431]),
    ("可转债等公允价值变动 Change in FV of convertible notes, derivative liabilities, and SAFEs",
                                                               [-1045, -5434, -34308]),
    ("其他收入(支出)净额 Other income (expense), net",             [-2, 0, -8]),
    ("其他收支合计 Total other income (expense), net",             [-978, -5328, -33885]),
    ("除税前利润 Loss before provision for income taxes",          [-1529, -8308, -41945]),
    ("所得税(费用为负) Provision for income taxes",                [-2, -1, -20]),
    ("净利润 Net loss",                                          [-1531, -8309, -41965]),
    ("其他综合收益-可供出售证券未实现损益 OCI AFS",                   [0, 0, 4]),
    ("其他综合收益-外币折算 OCI FX",                               [0, 0, 1]),
    ("综合收益 Comprehensive loss",                              [-1531, -8309, -41960]),
    ("每股基本及摊薄亏损(美元) EPS basic and diluted",               [-1.42, -5.43, -23.04]),
    ("加权平均股数(千股) Weighted-average shares (thousands)",      [1076881, 1528995, 1821085]),
    ("[补充] 股权激励费用(利润表口径·含回购溢价) SBC expense",         [29, 192, 1165]),
    ("[补充] 其中现金回购溢价计入股权激励 SBC from repurchase premium", [0, 0, 7]),
    ("[补充] 非现金慈善捐赠(捐赠匹配计划) Non-cash charitable contributions", [0, 0, 541]),
    ("[补充] 特定按市值计量金融工具公允价值变动 Change in FV of certain MTM instruments", [0, 0, 3]),
    ("[补充] 广告费用 Advertising expense",                       [None, 33, 147]),
    ("[补充] 无形资产摊销 Intangible amortization",                [0, 3, 13]),
    ("[补充] 固定资产折旧 Depreciation",                           [1, 3, 10]),
    ("[补充] 401k 雇主匹配 401(k) matching",                      [2, 7, 15]),
    ("[非GAAP·公司口径] 调整后经营利润 Adjusted operating income (loss)", [-522, -2788, -4854]),
    ("[非GAAP·公司口径] 调整后净利润 Adjusted net income (loss)",   [-457, -2683, -4448]),
]
table("IS", Y, IS_ROWS,
      f"# 单位: 百万美元(USD millions), 费用/减项=负数, 覆盖2023-2025(经审计·2023/2024 Grant Thornton·2025 EY), "
      f"来源: {SRC} F-7/F-8 + 附注 1/6/10/13 + MD&A 非GAAP 调节; ⚠️ 利润表按费用性质列报、无营业成本/毛利行(职能口径见 费用按职能.csv); "
      f"⚠️ 净利润被可转债公允价值变动主导(非现金), 看经营用「经营利润」; 股数已按 2026-09-17 十拆一追溯",
      "利润表.csv")

# ====================================================================== 中期利润表 + 现金流（H1·未经审计）
IIS_ROWS = [
    ("营业收入 Revenue",                                        [1163, 16286]),
    ("算力与基础设施 Compute and infrastructure",                 [-2334, -8945]),
    ("人员开支 Personnel",                                       [-538, -3152]),
    ("Bartz和解费用 Bartz settlement",                           [0, 0]),
    ("销售营销与合作伙伴 Sales, marketing, and partnerships",       [-120, -3168]),
    ("其他运营与行政 Other operating and administrative",          [-306, -1714]),
    ("经营费用合计 Total operating expenses",                     [-3298, -16979]),
    ("经营利润 Operating loss",                                  [-2135, -693]),
    ("利息收入 Interest income",                                 [115, 1111]),
    ("可转债等公允价值变动 Change in FV of convertible notes, derivative liabilities, and SAFEs",
                                                               [-10942, -72388]),
    ("其他收入(支出)净额 Other income (expense), net",             [0, -8757]),
    ("其他收支合计 Total other income (expense), net",             [-10827, -80034]),
    ("除税前利润 Loss before provision for income taxes",          [-12962, -80727]),
    ("所得税(费用为负) Provision for income taxes",                [-7, -21]),
    ("净利润 Net loss",                                          [-12969, -80748]),
    ("其他综合收益-可供出售证券未实现损益 OCI AFS",                   [0, -49]),
    ("其他综合收益-外币折算 OCI FX",                               [1, -9]),
    ("综合收益 Comprehensive loss",                              [-12968, -80806]),
    ("每股基本及摊薄亏损(美元) EPS basic and diluted",               [-7.25, -39.88]),
    ("加权平均股数(千股) Weighted-average shares (thousands)",      [1788731, 2024973]),
    ("[其他收支拆分] 票据购买协议初始确认及公允价值变动 Recognition and change in FV of NPAs", [0, -9405]),
    ("[其他收支拆分] 收购尾款负债公允价值变动 Change in FV of holdback liability", [0, -39]),
    ("[其他收支拆分] 认股权利公允价值变动 Change in FV of warrant rights", [0, 724]),
    ("[其他收支拆分] 其他 Other",                                 [0, -37]),
    ("[补充] 股权激励费用(利润表口径·含回购溢价) SBC expense",         [286, 2185]),
    ("[补充] 非现金慈善捐赠(捐赠匹配计划) Non-cash charitable contributions", [0, 126]),
    ("[补充] 特定按市值计量金融工具公允价值变动 Change in FV of certain MTM instruments", [0, 8720]),
    ("[补充] 无形资产摊销 Intangible amortization",                [4, 27]),
    ("[补充] 固定资产折旧 Depreciation",                           [4, 35]),
    ("[补充] 401k 雇主匹配 401(k) matching",                      [7, 20]),
    ("[非GAAP·公司口径] 调整后经营利润 Adjusted operating income (loss)", [-1849, 1618]),
    ("[非GAAP·公司口径] 调整后净利润 Adjusted net income (loss)",   [-1741, 2671]),
]
ICF_ROWS = [
    ("[现金流] 净利润 Net loss",                                  [-12969, -80748]),
    ("[现金流] 股权激励 Stock-based compensation",                 [279, 2185]),
    ("[现金流] 折旧摊销 Depreciation and amortization",            [14, 97]),
    ("[现金流] 可转债等公允价值变动 Change in FV of convertible notes etc.", [10942, 72388]),
    ("[现金流] 捐赠匹配负债 Donation matching program liability",   [0, 126]),
    ("[现金流] 其他金融工具确认及公允价值变动 Other financial instruments", [0, 8720]),
    ("[现金流] 其他 Other",                                      [5, -7]),
    ("[现金流] 应收账款变动 Accounts receivable",                   [-384, -4982]),
    ("[现金流] 预付及其他资产变动 Prepaid expenses and other assets", [212, 2094]),
    ("[现金流] 应付应计及其他负债变动 AP, accrued and other liabilities", [257, 2679]),
    ("[现金流] 租赁负债变动 Lease liabilities",                     [7, -3]),
    ("[现金流] 合同负债变动 Deferred revenue",                      [124, 1380]),
    ("[现金流] 经营活动现金流净额 Net cash from operating",          [-1513, 3929]),
    ("[现金流] 购建物业设备(capex) Purchases of property and equipment", [-18, -482]),
    ("[现金流] 购买短期投资 Purchases of short-term investments",    [0, -18972]),
    ("[现金流] 出售及到期短期投资 Sales and maturities of short-term investments", [0, 2610]),
    ("[现金流] 其他投资活动 Other investing activities",            [-31, -337]),
    ("[现金流] 投资活动现金流净额 Net cash used in investing",       [-49, -17181]),
    ("[现金流] 发行优先股净额 Proceeds from RCPS, net",              [3549, 110432]),
    ("[现金流] 融资租赁本金偿还 Principal payments for finance leases", [0, -4]),
    ("[现金流] 发行可转债收现 Issuance of convertible notes for cash", [1300, 0]),
    ("[现金流] 发行普通股收现 Proceeds from issuance of common stock", [49, 355]),
    ("[现金流] 回购普通股 Repurchase of common stock",              [-149, 0]),
    ("[现金流] 发行SAFE收现 Issuance of SAFEs for cash",            [0, 0]),
    ("[现金流] 支付发行费用 Payment of deferred offering costs",     [0, -9]),
    ("[现金流] 融资活动现金流净额 Net cash from financing",          [4749, 110774]),
    ("[现金流] 汇率影响 Effect of exchange rate changes",           [1, -5]),
    ("[现金流] 现金净变动 Net increase in cash",                    [3188, 97517]),
    ("[现金流] 期初现金及受限现金 Cash beginning of period",         [3154, 17401]),
    ("[现金流] 期末现金及受限现金 Cash end of period",               [6342, 114918]),
    ("[现金流补充] 已付所得税 Cash paid for income taxes",           [7, 34]),
    ("[现金流补充] 已购未付物业设备 PP&E acquired but not yet paid",  [1, 148]),
    ("[非现金] 可转债转优先股 Conversion of convertible notes into RCPS", [8168, 5499]),
    ("[非现金] 票据购买协议转G-2优先股 Conversion of NPAs into Series G-2", [0, 11810]),
    ("[非现金] 捐赠匹配结算发行N类股 Class N issued for donation matching", [0, 667]),
    ("[非现金] 收购发行股权 Equity issued in business acquisitions", [0, 534]),
    ("[非现金] 经营租赁换入使用权资产 ROU from operating leases",    [1, 963]),
    ("[非现金] 融资租赁换入使用权资产 ROU from finance leases",      [0, 445]),
]
table("IIS", H, IIS_ROWS + ICF_ROWS,
      f"# 单位: 百万美元(USD millions), 费用/减项/流出=负数; 期间轴: 半年累计(H1)·**未经审计**; 来源: {SRC} F-7/F-12/F-13 + 附注 8/10 + MD&A; "
      f"⚠️ 2026H1 净亏损含可转债公允价值变动 -72,388 与票据购买协议初始确认及变动 -9,405(均非现金); 2026H1 融资含 G/H 轮优先股",
      "中期财务-2026.csv")

# ====================================================================== 单季利润表（MD&A·未经审计）
QIS_ROWS = [
    ("营业收入 Revenue",                                        [376, 787, 1382, 2040, 4731, 11555]),
    ("算力与基础设施 Compute and infrastructure",                 [-944, -1390, -2047, -2945, -3387, -5558]),
    ("人员开支 Personnel",                                       [-218, -320, -489, -812, -1295, -1857]),
    ("Bartz和解费用 Bartz settlement",                           [0, 0, -1500, 0, 0, 0]),
    ("销售营销与合作伙伴 Sales, marketing, and partnerships",       [-24, -96, -202, -246, -1033, -2135]),
    ("其他运营与行政 Other operating and administrative",          [-125, -181, -233, -873, -683, -1031]),
    ("经营费用合计 Total operating expenses",                     [-1311, -1987, -4471, -4876, -6398, -10581]),
    ("经营利润 Operating income (loss)",                          [-935, -1200, -3089, -2836, -1667, 974]),
    ("利息收入 Interest income",                                 [51, 64, 124, 192, 349, 762]),
    ("可转债等公允价值变动 Change in FV of convertible notes, derivative liabilities, and SAFEs",
                                                               [-5701, -5241, -9165, -14201, -12791, -59597]),
    ("其他收入(支出)净额 Other income (expense), net",             [0, 0, -3, -5, -309, -8448]),
    ("其他收支合计 Total other income (expense), net",             [-5650, -5177, -9044, -14014, -12751, -67283]),
    ("除税前利润 Loss before provision for income taxes",          [-6585, -6377, -12133, -16850, -14418, -66309]),
    ("所得税(费用为负) Provision for income taxes",                [-7, 0, -5, -8, -21, 0]),
    ("净利润 Net loss",                                          [-6592, -6377, -12138, -16858, -14439, -66309]),
    ("[补充] 股权激励费用 SBC expense",                            [105, 181, 305, 574, 924, 1261]),
    ("[补充] 非现金慈善捐赠 Non-cash charitable contributions",     [0, 0, 0, 541, 126, 0]),
    ("[补充] 特定按市值计量金融工具公允价值变动 Change in FV of certain MTM instruments", [0, 0, 0, 3, 288, 8432]),
    ("[非GAAP·公司口径] 调整后经营利润 Adjusted operating income (loss)", [-830, -1019, -1284, -1721, -617, 2235]),
    ("[非GAAP·公司口径] 调整后净利润 Adjusted net income (loss)",   [-786, -955, -1168, -1539, -310, 2981]),
]
table("QIS", Q, QIS_ROWS,
      f"# 单位: 百万美元(USD millions), 费用/减项=负数; 期间轴: **单季**(MD&A Quarterly Results·未经审计); 来源: {SRC} MD&A 季度表(table idx 62/64/65); "
      f"⚠️ 2026Q3 金额 S-1 留空待修订(未披露); 2026Q2 股权激励公司写「$1.3 billion」, 本表取非GAAP调节表精确值 1,261",
      "利润表-季度.csv")

# ====================================================================== 费用按职能（附注 8 补充披露）
FN_ROWS = [
    ("营业收入 Revenue",                                        [41, 386, 4585, 1163, 16286]),
    ("营业成本(职能口径) Cost of revenue",                        [-26, -752, -2773, -1019, -2380]),
    ("研发(职能口径) Research and development",                   [-422, -2275, -6338, -1850, -9741]),
    ("销售及市场(职能口径) Sales and marketing",                   [-76, -163, -911, -239, -3808]),
    ("Bartz和解费用 Bartz settlement",                           [0, 0, -1500, 0, 0]),
    ("管理费用(职能口径) General and administrative",              [-68, -176, -1123, -190, -1050]),
    ("经营费用合计 Total operating expenses",                     [-592, -3366, -12645, -3298, -16979]),
]
table("FN", P5, FN_ROWS,
      f"# 单位: 百万美元(USD millions), 费用=负数; 期间轴: 年度(2023-2025 经审计) + 半年累计(H1·未经审计); 来源: {SRC} 附注 8 Supplemental Operating Expense Information(table idx 146); "
      f"口径: 营业成本≈服务客户负载的算力与基础设施+少量人员与分摊; 研发含训练/研究/内部使用的算力; 销售及市场含免费用户算力与渠道费; "
      f"⚠️ 这是公司对同一笔费用的另一种切法(性质法见 利润表.csv), 两者合计相等; 毛利率仅能由本表派生",
      "费用按职能.csv")

# ====================================================================== 资产负债表（年度·经审计）+ 中期
BS_KEYS = [
    "货币资金 Cash and cash equivalents",
    "短期投资 Short-term investments",
    "应收账款净额 Accounts receivable, net",
    "预付及其他流动资产 Prepaid expenses and other current assets",
    "流动资产合计 Total current assets",
    "受限现金 Restricted cash",
    "物业设备净额 Property and equipment, net",
    "经营租赁使用权资产 Operating lease right-of-use assets",
    "商誉 Goodwill",
    "其他非流动资产 Other assets, noncurrent",
    "资产总计 Total assets",
    "应付应计及其他流动负债 Accounts payable, accrued expenses, and other current liabilities",
    "经营租赁负债-流动 Operating lease liabilities, current",
    "合同负债(递延收入) Deferred revenue",
    "流动负债合计 Total current liabilities",
    "经营租赁负债-非流动 Operating lease liabilities, noncurrent",
    "可转换票据(公允价值) Convertible notes payable",
    "其他非流动负债 Other noncurrent liabilities",
    "负债合计 Total liabilities",
    "可赎回可转换优先股 Redeemable convertible preferred stock",
    "资本公积 Additional paid-in capital",
    "累计其他综合收益 Accumulated other comprehensive income (loss)",
    "累计亏损 Accumulated deficit",
    "股东权益(亏绌)合计 Total stockholders' deficit",
    "负债+优先股+权益合计 Total liabilities, RCPS, and stockholders' deficit",
    "[附] 优先股清算优先权 Aggregate liquidation preference",
    "[附] 优先股已发行股数(千股) RCPS shares outstanding (thousands)",
    "[附] A类普通股已发行股数(千股) Class A shares outstanding (thousands)",
    "[附] N类普通股已发行股数(千股) Class N shares outstanding (thousands)",
    "[附注8] 预付费用-流动 Prepaid expenses current",
    "[附注8] 其他-流动 Other current",
    "[附注8] 预付费用-非流动 Prepaid expenses noncurrent",
    "[附注8] 其他-非流动 Other noncurrent",
    "[附注8] 云服务商应付款 Cloud service provider payables",
    "[附注8] 应计法律费用 Accrued legal expenses",
    "[附注8] 捐赠匹配负债 Donation matching program liability",
    "[附注8] 其他应付应计 Other",
    "[附注8] 其中:应付账款 Of which accounts payable",
    "[附注6] 租赁物业改良 Leasehold improvements",
    "[附注6] 服务器网络及基础设施设备 Servers, networking, and infrastructure equipment",
    "[附注6] 在建工程 Construction in progress",
    "[附注6] 其他物业设备 Other assets",
    "[附注6] 物业设备原值合计 Total property and equipment, gross",
    "[附注6] 累计折旧 Accumulated depreciation",
    "[附注5] 无形资产净额 Intangible assets, net",
    "[附注1] 坏账准备 Allowance for credit losses",
    "[附注3] 现金等价物 Total cash equivalents",
    "[附注3] 短期投资摊余成本 Short-term investments amortized cost",
    "[附注4] 认股权利(公允价值) Warrant rights",
    "[附注4] 票据购买协议资产(公允价值) Note purchase agreements",
]
BS_VALS = {   # 2024-12-31, 2025-12-31, 2026-06-30
    "货币资金 Cash and cash equivalents": [3141, 17388, 112389],
    "短期投资 Short-term investments": [0, 2889, 19262],
    "应收账款净额 Accounts receivable, net": [95, 909, 5833],
    "预付及其他流动资产 Prepaid expenses and other current assets": [2076, 2560, 496],
    "流动资产合计 Total current assets": [5312, 23746, 137980],
    "受限现金 Restricted cash": [13, 13, 2529],
    "物业设备净额 Property and equipment, net": [19, 146, 1187],
    "经营租赁使用权资产 Operating lease right-of-use assets": [35, 126, 1157],
    "商誉 Goodwill": [0, 154, 576],
    "其他非流动资产 Other assets, noncurrent": [2373, 476, 3929],
    "资产总计 Total assets": [7752, 24661, 147358],
    "应付应计及其他流动负债 Accounts payable, accrued expenses, and other current liabilities": [333, 2511, 5422],
    "经营租赁负债-流动 Operating lease liabilities, current": [13, 37, 148],
    "合同负债(递延收入) Deferred revenue": [28, 269, 1650],
    "流动负债合计 Total current liabilities": [374, 2817, 7220],
    "经营租赁负债-非流动 Operating lease liabilities, noncurrent": [39, 80, 931],
    "可转换票据(公允价值) Convertible notes payable": [14116, 41677, 108566],
    "其他非流动负债 Other noncurrent liabilities": [150, 823, 750],
    "负债合计 Total liabilities": [14679, 45397, 117467],
    "可赎回可转换优先股 Redeemable convertible preferred stock": [2874, 29769, 157510],
    "资本公积 Additional paid-in capital": [239, 1644, 5336],
    "累计其他综合收益 Accumulated other comprehensive income (loss)": [0, 5, -53],
    "累计亏损 Accumulated deficit": [-10040, -52154, -132902],
    "股东权益(亏绌)合计 Total stockholders' deficit": [-9801, -50505, -127619],
    "负债+优先股+权益合计 Total liabilities, RCPS, and stockholders' deficit": [7752, 24661, 147358],
    "[附] 优先股清算优先权 Aggregate liquidation preference": [2874, 24646, 136286],
    "[附] 优先股已发行股数(千股) RCPS shares outstanding (thousands)": [220219, 544322, 853394],
    "[附] A类普通股已发行股数(千股) Class A shares outstanding (thousands)": [1779060, 1901267, 2157398],
    "[附] N类普通股已发行股数(千股) Class N shares outstanding (thousands)": [0, 0, 30643],
    "[附注8] 预付费用-流动 Prepaid expenses current": [2073, 2537, 258],
    "[附注8] 其他-流动 Other current": [3, 23, 238],
    "[附注8] 预付费用-非流动 Prepaid expenses noncurrent": [2364, 104, 222],
    "[附注8] 其他-非流动 Other noncurrent": [9, 372, 3707],
    "[附注8] 云服务商应付款 Cloud service provider payables": [302, 947, 2810],
    "[附注8] 应计法律费用 Accrued legal expenses": [2, 775, 1309],
    "[附注8] 捐赠匹配负债 Donation matching program liability": [0, 541, 0],
    "[附注8] 其他应付应计 Other": [29, 248, 1303],
    "[附注8] 其中:应付账款 Of which accounts payable": [313, 284, 766],
    "[附注6] 租赁物业改良 Leasehold improvements": [16, 51, 58],
    "[附注6] 服务器网络及基础设施设备 Servers, networking, and infrastructure equipment": [0, 34, 618],
    "[附注6] 在建工程 Construction in progress": [4, 63, 536],
    "[附注6] 其他物业设备 Other assets": [3, 10, 22],
    "[附注6] 物业设备原值合计 Total property and equipment, gross": [23, 158, 1234],
    "[附注6] 累计折旧 Accumulated depreciation": [-4, -12, -47],
    "[附注5] 无形资产净额 Intangible assets, net": [5, 20, 109],
    "[附注1] 坏账准备 Allowance for credit losses": [5, 17, 71],
    "[附注3] 现金等价物 Total cash equivalents": [3029, 16459, 108897],
    "[附注3] 短期投资摊余成本 Short-term investments amortized cost": [0, 2885, 19306],
    "[附注4] 认股权利(公允价值) Warrant rights": [0, 345, 1069],
    "[附注4] 票据购买协议资产(公允价值) Note purchase agreements": [0, 0, 2405],
}
table("BS", ["2024", "2025"], [(k, BS_VALS[k][:2]) for k in BS_KEYS],
      f"# 单位: 百万美元(USD millions)(股数行单位见行名); 时点: 年末(2024-12-31/2025-12-31·经审计); 来源: {SRC} F-5/F-6 + 附注 1/3/4/5/6/8; "
      f"⚠️ S-1 未列报 2023 年末资产负债表; ⚠️ 「可转换票据」按公允价值计量(本金远低于账面, 见 可转债与公允价值.csv); "
      f"⚠️ 优先股列在负债与权益之间(夹层), 股东权益为负是优先股账面+可转债公允价值累计亏损所致",
      "资产负债表.csv")
table("IBS", ["2025-12-31", "2026-06-30"], [(k, BS_VALS[k][1:]) for k in BS_KEYS],
      f"# 单位: 百万美元(USD millions)(股数行单位见行名); 时点: 2025-12-31(经审计) / 2026-06-30(**未经审计**); 来源: {SRC} F-5/F-6 + 附注; "
      f"⚠️ 2026-06-30 现金暴增来自 G/H 轮优先股融资(现金流量表融资活动), 不是经营所得",
      "中期资产负债表-2026.csv")

# ====================================================================== 现金流量表（年度·经审计）
CF_ROWS = [
    ("净利润 Net loss",                                          [-1531, -8309, -41965]),
    ("股权激励 Stock-based compensation",                         [29, 192, 1158]),
    ("折旧摊销 Depreciation and amortization",                    [3, 21, 40]),
    ("可转债等公允价值变动 Change in FV of convertible notes etc.",  [1045, 5434, 34308]),
    ("捐赠匹配负债 Donation matching program liability",           [0, 0, 541]),
    ("其他金融工具确认及公允价值变动 Other financial instruments",    [0, 0, 0]),
    ("其他 Other",                                              [0, 7, 11]),
    ("应收账款变动 Accounts receivable",                           [-10, -90, -834]),
    ("预付及其他资产变动 Prepaid expenses and other assets",         [-1253, -3190, 1771]),
    ("应付应计及其他负债变动 AP, accrued and other liabilities",     [84, 222, 2079]),
    ("租赁负债变动 Lease liabilities",                             [-1, 0, 13]),
    ("合同负债变动 Deferred revenue",                              [7, 21, 241]),
    ("经营活动现金流净额 Net cash from operating",                  [-1627, -5692, -2637]),
    ("购建物业设备(capex) Purchases of property and equipment",     [-2, -15, -131]),
    ("购买短期投资 Purchases of short-term investments",            [0, 0, -3082]),
    ("出售及到期短期投资 Sales and maturities of short-term investments", [0, 0, 213]),
    ("其他投资活动 Other investing activities",                    [0, -7, -77]),
    ("投资活动现金流净额 Net cash used in investing",               [-2, -22, -3077]),
    ("发行优先股净额 Proceeds from RCPS, net",                     [445, 1188, 16548]),
    ("融资租赁本金偿还 Principal payments for finance leases",      [0, 0, 0]),
    ("发行可转债收现 Issuance of convertible notes for cash",        [1750, 6050, 3450]),
    ("发行普通股收现 Proceeds from issuance of common stock",        [3, 10, 111]),
    ("回购普通股 Repurchase of common stock",                      [0, 0, -149]),
    ("发行SAFE收现 Issuance of SAFEs for cash",                    [122, 0, 0]),
    ("支付发行费用 Payment of deferred offering costs",             [0, 0, 0]),
    ("融资活动现金流净额 Net cash from financing",                  [2320, 7248, 19960]),
    ("汇率影响 Effect of exchange rate changes",                   [0, 0, 1]),
    ("现金净变动 Net increase in cash",                            [691, 1534, 14247]),
    ("期初现金及受限现金 Cash beginning of year",                    [929, 1620, 3154]),
    ("期末现金及受限现金 Cash end of year",                         [1620, 3154, 17401]),
    ("[补充] 已付所得税 Cash paid for income taxes",                [0, 0, 8]),
    ("[补充] 已购未付物业设备 PP&E acquired but not yet paid",       [0, 1, 10]),
    ("[非现金] 可转债转优先股 Conversion of convertible notes into RCPS", [0, 0, 10347]),
    ("[非现金] SAFE转优先股 Conversion of SAFEs into RCPS",          [1, 134, 0]),
    ("[非现金] 认股权利 Warrant rights",                           [0, 0, 345]),
    ("[非现金] 收购发行股权 Equity issued in business acquisition",  [0, 0, 136]),
    ("[非现金] 经营租赁换入使用权资产 ROU from operating leases",     [38, 8, 82]),
]
table("CF", Y, CF_ROWS,
      f"# 单位: 百万美元(USD millions), 流出=负数, 覆盖2023-2025(经审计); 来源: {SRC} F-12/F-13 + 附注 8 补充现金流; "
      f"⚠️ 现金含受限现金; ⚠️ 2024 经营现金流大额流出主要是预付云托管服务(预付及其他资产变动), 2025 消耗该预付后回流",
      "现金流量表.csv")

# ====================================================================== 权益变动（夹层优先股 + 股东权益）
EQ_ROWS = [
    ("[优先股] 期初账面 RCPS beginning",                           [1106, 1552, 2874, 2874, 29769]),
    ("[优先股] 发行(净额) Issuance, net",                          [445, 1188, 16548, 3549, 122242]),
    ("[优先股] 其中票据购买协议结算转入 Of which NPA settlement",       [0, 0, 0, 0, 11810]),
    ("[优先股] 可转债转入 Conversion of convertible notes",          [0, 0, 10347, 8168, 5499]),
    ("[优先股] SAFE转入 Conversion of SAFEs",                       [1, 134, 0, 0, 0]),
    ("[优先股] 期末账面 RCPS ending",                              [1552, 2874, 29769, 14591, 157510]),
    ("[优先股] 期初股数(千股) Shares beginning",                    [136005, 175764, 220219, 220219, 544322]),
    ("[优先股] 发行股数(千股) Shares issued",                       [39670, 39979, 155830, 63610, 285187]),
    ("[优先股] 转换取得股数(千股) Shares from conversions",           [89, 4476, 168273, 147533, 23885]),
    ("[优先股] 期末股数(千股) Shares ending",                       [175764, 220219, 544322, 431362, 853394]),
    ("[A类股] 期初股数(千股) Class A beginning",                    [1738823, 1754153, 1779060, 1779060, 1901267]),
    ("[A类股] 行权及授予股数(千股) Option exercises and grants",       [15330, 24907, 141542, 83704, 229818]),
    ("[A类股] 回购注销(千股) Repurchased",                          [0, 0, -27942, -27942, 0]),
    ("[A类股] 收购发行(千股) Issued in acquisitions",                [0, 0, 8607, 0, 26313]),
    ("[A类股] 期末股数(千股) Class A ending",                       [1754153, 1779060, 1901267, 1834822, 2157398]),
    ("[资本公积] 期初 APIC beginning",                              [5, 37, 239, 239, 1644]),
    ("[资本公积] 行权及售股 Option exercises and sales",             [3, 10, 111, 49, 355]),
    ("[资本公积] 股权激励 Stock-based compensation",                 [29, 192, 1158, 279, 2185]),
    ("[资本公积] 收购发行股权 Equity issued in acquisitions",          [0, 0, 136, 0, 534]),
    ("[资本公积] 捐赠匹配结算发行N类股 Class N for donation matching", [0, 0, 0, 0, 667]),
    ("[资本公积] 其他 Other",                                      [0, 0, 0, 0, -49]),
    ("[资本公积] 期末 APIC ending",                                 [37, 239, 1644, 567, 5336]),
    ("[累计亏损] 期初 Accumulated deficit beginning",                [-200, -1731, -10040, -10040, -52154]),
    ("[累计亏损] 净亏损 Net loss",                                  [-1531, -8309, -41965, -12969, -80748]),
    ("[累计亏损] 回购公允价值 Repurchase at fair value",              [0, 0, -149, -149, 0]),
    ("[累计亏损] 期末 Accumulated deficit ending",                   [-1731, -10040, -52154, -23158, -132902]),
    ("[其他综合收益] 期末 AOCI ending",                              [0, 0, 5, 1, -53]),
    ("[股东权益] 期末合计 Total stockholders' deficit ending",         [-1694, -9801, -50505, -22590, -127619]),
]
table("EQ", P5, EQ_ROWS,
      f"# 单位: 百万美元(USD millions), 股数单位千股; 期间轴: 年度(2023-2025) + 半年累计(2025H1/2026H1); 来源: {SRC} F-9~F-11 权益变动表; "
      f"⚠️ 2026H1 优先股发行 122,242 中 11,810 为票据购买协议(Google/Amazon 2026 NPA)公允价值结算转入·非现金(现金流量表收现 110,432)",
      "权益变动.csv")

# ====================================================================== 收入拆分（附注 2 + 附注 1 渠道）
REV_ROWS = [
    ("[地区] 美国 United States",                                [34, 263, 3362, 820, 11763]),
    ("[地区] 国际 International",                                [7, 123, 1223, 343, 4523]),
    ("[地区] 合计 Total",                                        [41, 386, 4585, 1163, 16286]),
    ("[计费方式] 按用量(token)计费 Consumption-based",             [39, 288, 3796, 983, 13064]),
    ("[计费方式] 订阅 Subscription-based",                        [2, 98, 789, 180, 3222]),
    ("[计费方式] 合计 Total",                                     [41, 386, 4585, 1163, 16286]),
    ("[渠道] 经云服务商市场(CSP marketplace)收入占比 Share via CSP marketplaces", [0.11, 0.32, 0.47, 0.44, 0.48]),
    ("[客户层级] TTM收入≥10万美元客户贡献收入(约数) Revenue from customers ≥$100K TTM", [37, 220, 3500, 870, 12000]),
    ("[客户层级] TTM收入≥10万美元客户贡献收入占比(约数) Share of revenue",  [0.90, 0.57, 0.76, 0.75, 0.74]),
]
table("REV", P5, REV_ROWS,
      f"# 单位: 百万美元(USD millions)·占比行=小数; 期间轴: 年度 + 半年累计; 来源: {SRC} 附注 2(地区按客户账单地址·计费方式) + 附注 1(CSP 渠道占比) + MD&A(客户层级·公司写「approximately」); "
      f"⚠️ 公司只有一个经营分部(附注 14), 无分部利润; 「客户层级」行为公司自述约数, 未经审计",
      "分部营收.csv")

# ====================================================================== 客户集中与经营指标（时点 / 期间混合 → 长表）
OPS = [
    # 科目, 值, 时点或期间, 单位, 出处
    ("[集中度] 客户A占收入 Customer A revenue share", 0.12, "2025", "小数", "附注1"),
    ("[集中度] 客户B占收入 Customer B revenue share", 0.12, "2025", "小数", "附注1"),
    ("[集中度] 客户B占收入 Customer B revenue share", 0.18, "2025H1", "小数", "附注1"),
    ("[集中度] 客户C占收入 Customer C revenue share", 0.43, "2023", "小数", "附注1"),
    ("[集中度] 客户C占收入 Customer C revenue share", 0.11, "2026H1", "小数", "附注1"),
    ("[集中度] 客户D占收入 Customer D revenue share", 0.11, "2023", "小数", "附注1"),
    ("[集中度] 客户A占应收 Customer A AR share", 0.13, "2025-12-31", "小数", "附注1"),
    ("[集中度] 客户A占应收 Customer A AR share", 0.13, "2026-06-30", "小数", "附注1"),
    ("[集中度] 客户C占应收 Customer C AR share", 0.10, "2026-06-30", "小数", "附注1"),
    ("[集中度] 经云服务商市场的应收占比 AR via CSP marketplaces", 0.42, "2024-12-31", "小数", "附注1"),
    ("[集中度] 经云服务商市场的应收占比 AR via CSP marketplaces", 0.60, "2025-12-31", "小数", "附注1"),
    ("[集中度] 经云服务商市场的应收占比 AR via CSP marketplaces", 0.58, "2026-06-30", "小数", "附注1"),
    ("[集中度] 前五大以外客户收入占比 Revenue outside top five", 0.64, "2026Q1", "小数·约数", "MD&A"),
    ("[集中度] 前五大以外客户收入占比 Revenue outside top five", 0.79, "2026Q3", "小数·约数", "MD&A"),
    ("[客户] TTM收入≥10万美元客户数 Customers ≥$100K TTM", 20, "2023-12-31", "家·约数", "MD&A"),
    ("[客户] TTM收入≥10万美元客户数 Customers ≥$100K TTM", 200, "2024-12-31", "家·约数", "MD&A"),
    ("[客户] TTM收入≥10万美元客户数 Customers ≥$100K TTM", 400, "2025-03-31", "家·约数", "MD&A"),
    ("[客户] TTM收入≥10万美元客户数 Customers ≥$100K TTM", 600, "2025-06-30", "家·下限(more than)", "MD&A"),
    ("[客户] TTM收入≥10万美元客户数 Customers ≥$100K TTM", 950, "2025-09-30", "家·下限(more than)", "MD&A"),
    ("[客户] TTM收入≥10万美元客户数 Customers ≥$100K TTM", 1500, "2025-12-31", "家·约数", "MD&A"),
    ("[客户] TTM收入≥10万美元客户数 Customers ≥$100K TTM", 6000, "2026-06-30", "家·下限(more than)", "MD&A"),
    ("[客户] TTM收入≥10万美元客户数 Customers ≥$100K TTM", 11900, "2026-09-30", "家·下限(more than)", "MD&A"),
    ("[客户] TTM收入≥100万美元客户数 Customers ≥$1M TTM", 1900, "2026-09-30", "家·下限(more than)", "MD&A"),
    ("[客户] TTM收入≥1000万美元客户数 Customers ≥$10M TTM", 250, "2026-09-30", "家·约数", "MD&A"),
    ("[客户] TTM收入<10万美元客户数 Customers <$100K TTM", 40000000, "2026-09-30止TTM", "个·约数", "MD&A"),
    ("[客户] 同时使用平台与自有应用的≥10万客户占比 Using platform and app", 0.30, "2025Q4", "小数·约数", "MD&A"),
    ("[客户] 同时使用平台与自有应用的≥10万客户占比 Using platform and app", 0.50, "2026Q3", "小数·下限(over)", "MD&A"),
    ("[客户] 净收入留存率 Net Revenue Retention", 9.00, "2026-09-30", "倍(约900%)·公司定义", "MD&A"),
    ("[收入质量] 违反使用政策或商业条款客户收入占比-下限 Revenue from violating customers (low)", 0.05, "2026前三季", "小数·公司估计", "MD&A"),
    ("[收入质量] 违反使用政策或商业条款客户收入占比-上限 Revenue from violating customers (high)", 0.07, "2026前三季", "小数·公司估计", "MD&A"),
    ("[收入质量] 近六个月新发布模型版本贡献收入占比 Revenue from model versions released in prior 6 months", 0.80, "2026Q3", "小数·下限(over)", "MD&A"),
    ("[合同] 剩余履约义务 Remaining performance obligations", 10800, "2026-06-30", "百万美元", "附注2"),
    ("[合同] 剩余履约义务12个月内确认比例 RPO within 12 months", 0.75, "2026-06-30", "小数·约数", "附注2"),
    ("[合同负债滚动] 期初递延收入转收入 Revenue from opening deferred revenue", -7, "2024", "百万美元", "附注2"),
    ("[合同负债滚动] 新增预收 Amounts billed in advance", 28, "2024", "百万美元", "附注2"),
    ("[合同负债滚动] 期初递延收入转收入 Revenue from opening deferred revenue", -28, "2025", "百万美元", "附注2"),
    ("[合同负债滚动] 新增预收 Amounts billed in advance", 269, "2025", "百万美元", "附注2"),
    ("[合同负债滚动] 期初递延收入转收入 Revenue from opening deferred revenue", -196, "2026H1", "百万美元", "附注2"),
    ("[合同负债滚动] 新增预收 Amounts billed in advance", 1577, "2026H1", "百万美元", "附注2"),
    ("[合同负债滚动] 期末 Deferred revenue ending", 7, "2023-12-31", "百万美元", "附注2"),
    ("[员工] 员工人数 Employees", 5300, "2026-09-30", "人·约数", "Business"),
    ("[员工] TTM人均收入 TTM revenue per employee", 1.4, "2025-09-30", "百万美元", "MD&A"),
    ("[员工] TTM人均收入 TTM revenue per employee", 6.6, "2026-09-30", "百万美元·下限(over)", "MD&A"),
    ("[员工] 员工人数同比增幅 Headcount growth YoY", 1.70, "2026-09-30", "小数·约数", "MD&A"),
    ("[员工] TTM收入同比增幅 TTM revenue growth YoY", 12.00, "2026-09-30", "小数·约数", "MD&A"),
    ("[公司自述] 2026年9月代码库提交由Claude编写的比例 Codebase contributions written by Claude", 0.90, "2026-09", "小数·下限(over)", "MD&A/Business"),
]
table("OPS", ["值", "时点或期间", "单位", "出处"],
      [(k, [v, t, u, s]) for k, v, t, u, s in OPS],
      f"# 长表: 每行一个指标在一个时点/期间的值; 来源: {SRC} 附注 1/2 + MD&A + Business; "
      f"⚠️ 「MD&A/Business」行为公司经营指标(未经审计·多为约数或下限), 只证明公司这么说; 客户 A-D 为匿名编号(同一字母跨期指同一客户, 未披露身份)",
      "客户与经营指标.csv")

# ====================================================================== 可转债、票据购买协议与 Level 3 公允价值
L3_ROWS = [
    ("[可转换票据] 期初 Beginning",                                [1678, 14116, 41677]),
    ("[可转换票据] 新增 Additions",                                [5900, 3450, 0]),
    ("[可转换票据] 转股 Conversion",                               [0, -10347, -5499]),
    ("[可转换票据] 公允价值变动 Change in fair value",                [6538, 34458, 72388]),
    ("[可转换票据] 期末 Ending",                                   [14116, 41677, 108566]),
    ("[衍生负债] 期初 Beginning",                                  [1110, 150, 0]),
    ("[衍生负债] 新增 Additions",                                  [150, 0, 0]),
    ("[衍生负债] 公允价值变动及结算 Change in FV and settlement",      [-1110, -150, 0]),
    ("[衍生负债] 期末 Ending",                                     [150, 0, 0]),
    ("[SAFE] 期初 Beginning",                                     [128, 0, 0]),
    ("[SAFE] 转股 Conversion",                                    [-134, 0, 0]),
    ("[SAFE] 公允价值变动 Change in fair value",                     [6, 0, 0]),
    ("[SAFE] 期末 Ending",                                        [0, 0, 0]),
    ("[认股权利·资产] 期初 Beginning",                              [0, 0, 345]),
    ("[认股权利·资产] 新增 Additions",                              [0, 345, 0]),
    ("[认股权利·资产] 公允价值变动 Change in fair value",             [0, 0, 724]),
    ("[认股权利·资产] 期末 Ending",                                 [0, 345, 1069]),
    ("[票据购买协议·资产] 期初 Beginning",                           [0, 0, 0]),
    ("[票据购买协议·资产] 新增 Additions",                           [0, 0, 2348]),
    ("[票据购买协议·资产] 公允价值变动 Change in fair value",          [0, 0, -11753]),
    ("[票据购买协议·资产] 结算 Settlement",                          [0, 0, 11810]),
    ("[票据购买协议·资产] 期末 Ending",                              [0, 0, 2405]),
    ("[捐赠匹配负债] 期初 Beginning",                               [0, 0, 541]),
    ("[捐赠匹配负债] 新增 Additions",                               [0, 541, 0]),
    ("[捐赠匹配负债] 公允价值变动 Change in fair value",              [0, 0, 126]),
    ("[捐赠匹配负债] 结算 Settlement",                              [0, 0, -667]),
    ("[捐赠匹配负债] 期末 Ending",                                  [0, 541, 0]),
    ("[收购尾款负债] 期初 Beginning",                               [0, 0, 28]),
    ("[收购尾款负债] 新增 Additions",                               [0, 25, 0]),
    ("[收购尾款负债] 公允价值变动 Change in fair value",              [0, 3, 30]),
    ("[收购尾款负债] 期末 Ending",                                  [0, 28, 58]),
    ("[未偿票据·2026-06-30] Amazon 2023 NPA 本金 Principal",        [None, None, 2186]),
    ("[未偿票据·2026-06-30] Amazon 2024 NPA 本金 Principal",        [None, None, 4017]),
    ("[未偿票据·2026-06-30] 本金合计 Total principal",              [None, None, 6203]),
    ("[未偿票据·2026-06-30] 可转N类股数(股) Class N issuable",       [None, None, 1840444962]),
    ("[未偿票据·2026-06-30] Amazon 2023 NPA 可转股数(股)",           [None, None, 1044716970]),
    ("[未偿票据·2026-06-30] Amazon 2024 NPA 可转股数(股)",           [None, None, 795727992]),
    ("[未动用额度·2026-06-30] Google 2026 NPA",                    [None, None, 20000]),
    ("[未动用额度·2026-06-30] Amazon 2026 NPA",                    [None, None, 15000]),
    ("[未动用额度·2026-06-30] Broadcom 基础设施伙伴 2026 NPA(仅限付租)", [None, None, 42000]),
    ("[未动用额度·2026-06-30] 合计 Total",                          [None, None, 77000]),
    ("[循环信贷] 承诺额度 Revolving commitments",                    [None, 3250, 3250]),
    ("[循环信贷] 已开备用信用证 Standby letters of credit",            [None, 4, 78]),
    ("[循环信贷] 已提款 Borrowings drawn",                           [None, 0, 0]),
]
table("L3", ["2024", "2025", "2026H1"], L3_ROWS,
      f"# 单位: 百万美元(USD millions)(股数行单位见行名); 期间轴: 滚动行=年度/半年累计·「未偿票据/未动用额度」行=2026-06-30 时点·循环信贷行=期末时点; "
      f"来源: {SRC} 附注 4 Level 3 滚动表(table idx 129) + 附注 9 + MD&A Convertible Notes(table idx 66/67); "
      f"⚠️ 2026-06-30 可转换票据公允价值 108,566 对应本金仅 6,203(全部为 Amazon 不计息展期票据, IPO 时按 $2.0928/$5.0478 转 N 类股、受 Amazon 12% 持股上限约束); "
      f"⚠️ 收购尾款负债 2026H1 公允价值变动: 本表(附注4滚动)30 vs 附注8其他收支 39 —— 申报人两处差 9, 照录不抹平; "
      f"循环信贷 2026-09 已扩至 150 亿美元(期后事项, 见 或有事项与其他.csv)",
      "可转债与公允价值.csv")

# ====================================================================== 优先股各系列（附注 10）
PREF = [
    # 系列, 原始发行价(美元), [股数(千)@2024,2025,2026-06], [账面@...], [清算优先权@...], 表决权
    ("A",   2.57,   [48574, 48574, 48574],   [125, 125, 125],     [125, 125, 125],     "有"),
    ("B",   11.23,  [87430, 87430, 87430],   [982, 982, 982],     [982, 982, 982],     "无"),
    ("C-1", 11.23,  [26397, 26397, 26397],   [296, 296, 296],     [296, 296, 296],     "有"),
    ("C-2", 11.23,  [13362, 13362, 13362],   [150, 150, 150],     [150, 150, 150],     "无"),
    ("D-1", 30.00,  [35013, 35013, 35013],   [1042, 1042, 1042],  [1051, 1051, 1051],  "有"),
    ("D-2", 27.00,  [4444, 4444, 4444],      [133, 133, 133],     [120, 120, 120],     "有"),
    ("D-3", 30.00,  [4999, 4999, 4999],      [146, 146, 146],     [150, 150, 150],     "无"),
    ("E-1", 56.09,  [0, 63610, 63610],       [0, 3549, 3549],     [0, 3568, 3568],     "有"),
    ("E-2", 20.93,  [0, 95282, 95282],       [0, 4728, 4728],     [0, 1994, 1994],     "无"),
    ("E-3", 56.09,  [0, 12664, 12664],       [0, 856, 856],       [0, 710, 710],       "无"),
    ("E-4", 50.48,  [0, 15343, 15343],       [0, 986, 986],       [0, 774, 774],       "无"),
    ("E-5", 53.28,  [0, 24244, 24244],       [0, 1598, 1598],     [0, 1292, 1292],     "无"),
    ("F-1", 140.97, [0, 92220, 92220],       [0, 12999, 12999],   [0, 13000, 13000],   "有"),
    ("F-2", 20.93,  [0, 20740, 20740],       [0, 2179, 2179],     [0, 434, 434],       "无"),
    ("G-1", 259.14, [0, 0, 90510],           [0, 0, 23454],       [0, 0, 23455],       "有"),
    ("G-2", 259.14, [0, 0, 83929],           [0, 0, 33558],       [0, 0, 21749],       "无"),
    ("G-3", 20.93,  [0, 0, 20563],           [0, 0, 4571],        [0, 0, 430],         "无"),
    ("G-4", 233.22, [0, 0, 3322],            [0, 0, 928],         [0, 0, 775],         "无"),
    ("H-1", 589.01, [0, 0, 77638],           [0, 0, 45728],       [0, 0, 45729],       "有"),
    ("H-2", 589.01, [0, 0, 33110],           [0, 0, 19502],       [0, 0, 19502],       "无"),
]
PREF_ROWS = []
for s, oip, sh, cv, lp, vote in PREF:
    PREF_ROWS.append((f"[{s}] 已发行股数(千股) Shares outstanding", sh))
    PREF_ROWS.append((f"[{s}] 账面价值 Net carrying value", cv))
    PREF_ROWS.append((f"[{s}] 清算优先权 Liquidation preference", lp))
    PREF_ROWS.append((f"[{s}] 原始发行价(美元·拆股前优先股口径) OIP", [oip, oip, oip]))
PREF_ROWS += [
    ("[合计] 已发行股数(千股) Total shares", [220219, 544322, 853394]),
    ("[合计] 账面价值 Total carrying value", [2874, 29769, 157510]),
    ("[合计] 清算优先权 Total liquidation preference", [2874, 24646, 136286]),
    ("[合计] 按转换比例折合普通股(千股) As-converted common shares", [2202194, None, 8558869]),
]
table("PREF", ["2024-12-31", "2025-12-31", "2026-06-30"], PREF_ROWS,
      f"# 单位: 百万美元(USD millions); 股数=千股; 原始发行价为美元/优先股股(转换比例约 10:1, D 系列因反稀释调整约 10.4-10.6:1); 来源: {SRC} 附注 10(table idx 147/148/149) + 附注 12; "
      f"表决权: 有=可转A类(有表决权)·无=可转N类(无表决权, 主要为战略伙伴); ⚠️ 账面≠清算优先权: 由可转债转来的系列按转股时票据公允价值入账(如 E-2/F-2/G-3 账面远高于清算优先权); "
      f"「折合普通股」2026-06-30 取附注 12 反稀释表口径(2024 同口径, 2025 年末附注未单列 → 空)",
      "优先股明细.csv")

# ====================================================================== 融资轮次（Item 15 未登记证券销售 + 附注）
ROUNDS = [
    # 科目, 值, 时间, 单位, 备注
    ("[C轮] 每股价格", 11.2261, "2023-03~2023-06", "美元", "C-1/C-2 共 39,669,823 股"),
    ("[C轮] 募资额", 445.3, "2023-03~2023-06", "百万美元", "现金"),
    ("[D轮] 每股价格", 30.0045, "2024-01~2024-05", "美元", "D-1/D-3 共 39,978,675 股·54 名投资者"),
    ("[D轮] 募资额", 1199.5, "2024-01~2024-05", "百万美元", "另 SAFE 转 D-1 33,328 股、转 D-2 4,443,769 股(@$27.0041)"),
    ("[E轮] 每股价格", 56.0865, "2025-01~2025-03", "美元", "E-1 共 63,610,106 股·72 名投资者"),
    ("[E轮] 募资额", 3567.7, "2025-01~2025-03", "百万美元", "现金; 同期 Amazon/Google 票据转 E-2~E-5"),
    ("[F轮] 每股价格", 140.9676, "2025-08~2025-09", "美元", "F-1 共 92,219,720 股·202 名投资者"),
    ("[F轮] 募资额", 13000.0, "2025-08~2025-09", "百万美元", "现金; 同期 Amazon 展期票据转 F-2 20,739,866 股(@$20.9280)"),
    ("[B轮旧股] 自美国政府回购并转售股数", 4453900, "2025-10", "股", "前持有人在第三方诉讼中被没收; @$140.9676 转售 9 名投资者·公司无净收益"),
    ("[G轮] 每股价格", 259.1364, "2026-01~2026-05", "美元", "G-1 90,510,425 股(261 名)+G-2 83,928,770 股(5 名)"),
    ("[G轮] G-1募资额", 23454.5, "2026-01~2026-02", "百万美元", "现金"),
    ("[G轮] G-2募资额", 21700.0, "2026-01~2026-05", "百万美元", "含 Google 38.6M 股≈100 亿、Amazon 19.3M 股≈50 亿(随 2026 NPA 签订)"),
    ("[H轮] 每股价格", 589.0095, "2026-05~2026-06", "美元", "H-1 77,637,878 股(305 名)+H-2 33,110,291 股(11 名)"),
    ("[H轮] H-1募资额", 45729.4, "2026-05~2026-06", "百万美元", "现金"),
    ("[H轮] H-2募资额", 19500.0, "2026-05~2026-06", "百万美元", "含 Google 100 亿、Amazon 50 亿"),
    ("[累计] 截至2026-06-30累计融资(公司口径)", 141100.0, "2026-06-30", "百万美元", "公司自述「raised an aggregate of $141.1 billion of capital」·构成未拆"),
    ("[可转债] 2023-11至申报日发行本金", 10200.0, "2023-11~2026-10", "百万美元", "两名投资者(Google/Amazon)"),
    ("[老股转让] 2026-04 要约收购成交股数", 179883540, "2026-04", "股", "第三方买方@$25.9136(=G 轮价÷10)·成交 46.6 亿美元·Dario/Daniela Amodei、CFO Rao 等卖出"),
    ("[老股转让] 2026-04 要约收购成交额", 4661.4, "2026-04", "百万美元", "公司未收款"),
    ("[公司回购] 2025-06 要约回购股数", 27942000, "2025-06", "股", "@$5.61(高于当时公允价值, 溢价 7 百万计股权激励)·Dario/Daniela Amodei 卖出"),
    ("[公司回购] 2025-06 要约回购金额", 156.7, "2025-06", "百万美元", "现金流量表记 149(公允价值部分)"),
]
table("ROUNDS", ["值", "时间", "单位", "备注"],
      [(k, [v, t, u, n]) for k, v, t, u, n in ROUNDS],
      f"# 长表; 来源: {SRC} Item 15 Recent Sales of Unregistered Securities + 附注 10/16 + Certain Relationships(要约收购); "
      f"⚠️ 每股价格为优先股口径(拆股前·A/N 类 10:1 拆股后每股普通股约为其 1/10); 本表不推算公司估值",
      "融资轮次.csv")

# ====================================================================== 算力与基础设施承诺（附注 7/13/16/17 + MD&A Contractual Obligations）
COMMIT = [
    # 科目, 金额(百万美元), 时点/期间, 性质, 出处
    ("[承诺总量] 不可撤销采购承诺(期限>1年) Non-cancelable purchase commitments", 54559, "2025-12-31", "固定/最低付款", "附注13"),
    ("[承诺总量] 固定或最低保证采购承诺 Fixed or minimum guaranteed commitments", 265600, "2026-06-30", "固定/最低付款·1-20年", "附注13"),
    ("[承诺总量] 已签未起租的租赁 Leases not yet commenced", 50200, "2025-12-31", "未折现", "附注7"),
    ("[承诺总量] 已签未起租的租赁 Leases not yet commenced", 321400, "2026-06-30", "未折现·2026-2028 起租·最长20年", "附注7"),
    ("[承诺总量] 2026-01-01至2026-06-01新签及修订(最低付款) New and amended agreements", 417000, "2026-01~2026-06-01", "最低付款·与上两行有重叠", "附注16"),
    ("[承诺总量] 已扩展协议预计付款(2028-2031交付·下限) Expanded agreements low", 125000, "2026-06-01", "估计·条款未定", "附注16"),
    ("[承诺总量] 已扩展协议预计付款(2028-2031交付·上限) Expanded agreements high", 150000, "2026-06-01", "估计·条款未定", "附注16"),
    ("[承诺总量] 2026-06-30后新签及修订(最低付款) New agreements after 2026-06-30", 245000, "2026-07~2026-10-26", "最低付款·2026-2036起·最长20年", "附注17"),
    ("[承诺总量] 2026-06-30后短期协议最低不可撤销付款 Short-term agreements", 21000, "2026-07~2026-10-26", "最低付款", "附注17"),
    ("[具名] Microsoft Azure 最低消费承诺", 44900, "2026-11~2033-05", "不论实际用量·不可撤销", "MD&A"),
    ("[具名] Google 最低消费承诺", 114500, "2026-04~2033-07", "不足额须补差(true-up)·不可撤销", "MD&A"),
    ("[具名] Google等TPU供应商追加算力(2028-2031交付·下限)", 125000, "2028~2031", "估计·未计入承诺表", "MD&A"),
    ("[具名] Google等TPU供应商追加算力(2028-2031交付·上限)", 150000, "2028~2031", "估计·未计入承诺表", "MD&A"),
    ("[具名] Amazon 最低消费承诺", 110000, "2026-05~2036-04", "不足额须补差(true-up)·不可撤销", "MD&A"),
    ("[具名] SpaceXAI(原 X.AI) NVIDIA GPU 算力(上限)", 120500, "至2029", "满载约31亿美元/月(预计2026-12满载)·初始不可撤销期至2027-01/2027-03后任一方90天通知可终止", "MD&A"),
    ("[具名] SpaceXAI 满载月费", 3100, "2026-12起", "每月", "MD&A"),
    ("[具名] AMD Helios(MI450)初始批次(若全部采购·下限)", 20000, "2027起", "未计入承诺表·无固定金额", "MD&A"),
    ("[具名] Nscale NVIDIA GPU 服务(上限)", 44600, "至2033", "交付验收后计费", "MD&A"),
    ("[具名] Lambda NVIDIA GPU(合计)", 41300, "至2034", "交付验收后计费", "MD&A"),
    ("[具名] Lambda 其中2026-08协议", 34900, "至2034", "Lambda 未及时取得场地租约则任一方可终止", "MD&A"),
    ("[具名] Broadcom 五年期设备主租约(TPU)租金合计(不含利息)", 161200, "2026起", "融资租赁·两家特殊目的子公司签约·母公司担保·交叉违约", "MD&A"),
    ("[担保] 数据中心开发商担保及成本补偿最高额", 800, "2026-06-30", "或有·计提不重大", "附注13"),
    ("[担保] 数据中心电力购买合同担保最高额", 500, "2026-03", "或有", "附注16"),
    ("[担保] 为 Broadcom 租约存入托管账户", 2500, "2026-04", "受限现金", "附注16"),
    ("[担保] 可能被要求追加的受限现金上限", 10000, "2026-06-30", "或有", "附注8"),
    ("[其他] 权益法投资未出资承诺", 265, "2026-06-30", "承诺总额 325", "附注3"),
    ("[其他] 数据中心(待建)租约", None, "2026-03签·2027起租", "20年·金额未单列", "附注16"),
]
table("COMMIT", ["金额", "时点或期间", "性质", "出处"],
      [(k, [v, t, n, s]) for k, v, t, n, s in COMMIT],
      f"# 长表; 单位: 百万美元(USD millions); 来源: {SRC} 附注 3/7/8/13/16/17 + MD&A Contractual Obligations / Infrastructure Service Arrangements; "
      f"⚠️ 各行口径与时点不同、互有重叠(附注 16 的 4,170 亿与附注 7/13 的 2026-06-30 存量重叠), **不可直接相加**; "
      f"⚠️ S-1 的「承诺总表」与「合计承诺额」留空待修订; 具名合同金额为 MD&A 原文, 多为「最低」或「上限」",
      "算力承诺.csv")

# ====================================================================== 到期排期（附注 5/7/13）
SCHED_COLS = ["2026", "2027", "2028", "2029", "2030", "此后", "合计"]
SCHED_ROWS = [
    ("[采购承诺@2025-12-31] 不可撤销采购承诺", [7059, 11128, 10832, 8304, 5428, 11808, 54559]),
    ("[经营租赁@2025-12-31] 未折现付款", [45, 35, 22, 4, 4, 39, 149]),
    ("[经营租赁@2026-06-30] 未折现付款", [52, 109, 194, 162, 173, 911, 1601]),
    ("[融资租赁@2026-06-30] 未折现付款", [62, 106, 106, 106, 106, 37, 523]),
    ("[无形资产摊销@2025-12-31] 预计摊销", [15, 2, 1, 1, 1, 0, 20]),
]
SCHED_EXTRA = [
    ("[经营租赁@2025-12-31] 减:利息", -32), ("[经营租赁@2025-12-31] 租赁负债现值", 117),
    ("[经营租赁@2026-06-30] 减:利息", -522), ("[经营租赁@2026-06-30] 租赁负债现值", 1079),
    ("[融资租赁@2026-06-30] 减:利息", -80), ("[融资租赁@2026-06-30] 租赁负债现值", 443),
    ("[融资租赁@2026-06-30] 计入流动负债", 86), ("[融资租赁@2026-06-30] 计入非流动负债", 357),
]
table("SCHED", SCHED_COLS, SCHED_ROWS + [(k, [None] * 6 + [v]) for k, v in SCHED_EXTRA],
      f"# 单位: 百万美元(USD millions); 列=付款年度(2026 列@2026-06-30 指 2026 下半年); 来源: {SRC} 附注 5/7/13(table idx 134/139/165); "
      f"⚠️ 2026-06-30 的采购承诺只给总额约 2,656 亿美元、未给分年排期; 已签未起租租赁(2026-06-30 约 3,214 亿)不在租赁到期表内",
      "到期与承诺排期.csv")

# ====================================================================== 股权激励与稀释（附注 10/12 + 期后）
DIL = [
    # 科目, 值, 时点/期间, 单位, 出处
    ("[期权] 未行权数", 532827, "2023-12-31", "千股", "附注10"),
    ("[期权] 未行权数", 1736780, "2024-12-31", "千股", "附注10"),
    ("[期权] 未行权数", 1982743, "2025-12-31", "千股", "附注10"),
    ("[期权] 未行权数", 1797066, "2026-06-30", "千股", "附注10"),
    ("[期权] 加权平均行权价", 2.89, "2026-06-30", "美元", "附注10"),
    ("[期权] 内在价值", 98205, "2026-06-30", "百万美元", "附注10"),
    ("[期权] 内在价值", 31415, "2025-12-31", "百万美元", "附注10"),
    ("[期权] 未确认费用", 3200, "2025-12-31", "百万美元·约1.5年", "附注10"),
    ("[期权] 未确认费用", 2800, "2026-06-30", "百万美元·约1.2年", "附注10"),
    ("[RSU] 未归属数", 621041, "2025-12-31", "千股", "附注10"),
    ("[RSU] 未归属数", 1049631, "2026-06-30", "千股", "附注10"),
    ("[RSU] 加权平均授予日公允价值", 25.34, "2026-06-30", "美元", "附注10"),
    ("[RSU] 若业绩条件成立应累计确认的费用(IPO时一次性补提)", 671, "2025-12-31", "百万美元", "附注10"),
    ("[RSU] 若业绩条件成立应累计确认的费用(IPO时一次性补提)", 2900, "2026-06-30", "百万美元", "附注10"),
    ("[RSU] 届时剩余未确认费用", 5200, "2025-12-31", "百万美元", "附注10"),
    ("[RSU] 届时剩余未确认费用", 23700, "2026-06-30", "百万美元·约2.1年", "附注10"),
    ("[RSU] 未确认费用总额", 26600, "2026-06-30", "百万美元", "MD&A"),
    ("[RSU] 2026-06-30后新授予(IPO生效即满足业绩条件)", 91, "2026-07~2026-10", "百万股", "附注17"),
    ("[RSU] 2026-06-30后新授予授予日公允价值合计", 5800, "2026-07~2026-10", "百万美元", "附注17"),
    ("[RSA] 未确认费用", 325, "2026-06-30", "百万美元·约2.7年", "附注10"),
    ("[反稀释] 优先股折合普通股", 8558869, "2026H1", "千股", "附注12"),
    ("[反稀释] 可转债折合普通股", 1840445, "2026H1", "千股", "附注12"),
    ("[反稀释] RSA", 13529, "2026H1", "千股", "附注12"),
    ("[反稀释] 期权", 1797066, "2026H1", "千股", "附注12"),
    ("[反稀释] 收购尾款", 1590, "2026H1", "千股", "附注12"),
    ("[反稀释] 合计(不含RSU 1,049.6M)", 12211499, "2026H1", "千股", "附注12"),
    ("[反稀释] 合计(不含RSU 621.0M)", 9526778, "2025", "千股", "附注12"),
    ("[反稀释] 优先股折合普通股", 5465695, "2025", "千股", "附注12"),
    ("[反稀释] 可转债折合普通股", 2046074, "2025", "千股", "附注12"),
    ("[反稀释] RSA", 27, "2025", "千股", "附注12"),
    ("[反稀释] 期权", 1982743, "2025", "千股", "附注12"),
    ("[反稀释] 收购尾款", 1596, "2025", "千股", "附注12"),
    ("[反稀释] 捐赠匹配负债", 30643, "2025", "千股", "附注12"),
    ("[预留] 股权计划可供授予股数", 569059, "2026-06-30", "千股", "附注10"),
    ("[预留] 股权计划可供授予股数", 287571, "2025-12-31", "千股", "附注10"),
    ("[基本股数] 加权平均股数", 2024973, "2026H1", "千股", "F-7"),
    ("[公益] 捐赠匹配计划预留股数", 964341, "2025-12-31", "千股", "附注10"),
    ("[公益] 捐赠匹配计划预留股数", 933698, "2026-06-30", "千股", "附注10"),
    ("[公益] 捐赠匹配费用(2025全年)", 541, "2025", "百万美元·约占经营费用4%", "MD&A"),
    ("[公益] 捐赠匹配费用(2026Q3·2026-08认捐)", 2000, "2026Q3", "百万美元", "附注17"),
    ("[公益] 2026-10为结算捐赠匹配发行N类股", 28.0, "2026-10", "百万股·约数", "附注17"),
    ("[公益] 注入 Anthropic Public Benefit Fund 的N类股", 846840960, "2026-10", "股·占2026-06-30完全稀释股本5%(假设Amazon票据全部转股)", "Prospectus Summary"),
    ("[公益] 此后每次股价较前一里程碑涨50%可再注入的上限", 0.02, "IPO后", "占当时流通股(含期权RSU等)比例·董事会酌定", "Prospectus Summary"),
    ("[公益] 联合创始人承诺捐出个人股权比例", 0.80, "—", "小数·各自承诺", "Prospectus Summary"),
    ("[计划] 2026 股权激励计划初始预留", 2950.0, "IPO生效前一日", "百万股", "附注17"),
    ("[计划] 2026 员工持股购买计划初始预留", 160.0, "IPO生效前一日", "百万股", "附注17"),
]
table("DIL", ["值", "时点或期间", "单位", "出处"],
      [(k, [v, t, u, s]) for k, v, t, u, s in DIL],
      f"# 长表; 来源: {SRC} 附注 10/12/17 + MD&A Critical Accounting Estimates + Prospectus Summary; "
      f"⚠️ RSU 以「IPO 或控制权变更」为业绩条件, 截至 2026-06-30 一分未确认; IPO 生效当季将一次性补提累计费用(2026-06-30 测算约 29 亿美元, 期后新授予另计); "
      f"⚠️ Public Benefit Fund 持股法律上流通、会计上不算流通(全资子公司持有), 不进 EPS 分母",
      "股权激励与稀释.csv")

# ====================================================================== 或有事项、税务与其他（附注 9/11/13/16/17）
OTHER = [
    ("[诉讼] Bartz 版权集体诉讼和解金额", 1500, "2025Q3计提·2026-07法院批准", "百万美元(另加孳息)", "附注13"),
    ("[诉讼] Bartz 2025年已付", 300, "2025", "百万美元", "附注13"),
    ("[诉讼] Bartz 负债-流动", 750, "2025-12-31", "百万美元", "附注13"),
    ("[诉讼] Bartz 负债-非流动", 450, "2025-12-31", "百万美元", "附注13"),
    ("[诉讼] Bartz 负债-流动", 1200, "2026-06-30", "百万美元·约数", "附注13"),
    ("[诉讼] 应计法律费用合计", 1309, "2026-06-30", "百万美元", "附注8"),
    ("[累计亏损] 其中2023年以来可转债与衍生负债公允价值变动累计", 113200, "2026-06-30", "百万美元·MD&A 取一位小数(1,132亿)", "MD&A Liquidity"),
    ("[税务] 联邦净经营亏损结转", 8200, "2025-12-31", "百万美元·不过期", "附注11"),
    ("[税务] 州净经营亏损结转", 4200, "2025-12-31", "百万美元·2033起到期", "附注11"),
    ("[税务] 联邦研发抵免结转", 656, "2025-12-31", "百万美元·2042起到期", "附注11"),
    ("[税务] 加州研发抵免结转", 343, "2025-12-31", "百万美元·不过期", "附注11"),
    ("[税务] 递延所得税资产估值备抵", 3422, "2025-12-31", "百万美元·全额备抵", "附注11"),
    ("[税务] 未确认税收利益", 293, "2025-12-31", "百万美元", "附注11"),
    ("[税务] 2025 税率调节:按市值计量项不可扣除", 7192, "2025", "百万美元·-17.1%", "附注11"),
    ("[信贷] 修订后循环信贷额度", 15000, "2026-09-04", "百万美元·2031-09到期·最低流动性契约50亿", "附注17/MD&A"),
    ("[信贷] 原循环信贷最低流动性契约", 500, "2025-05~2026-09", "百万美元", "附注9"),
    ("[AMD] AMD 承诺认购N类股上限", 5000, "2026-07", "百万美元·按GPU交付里程碑分批·首个预计2027", "附注17/MD&A"),
    ("[Google] IPO同步私募认购N类股期权上限", 10000, "2026-03签", "百万美元·行使则等额减少Google 2026 NPA额度", "MD&A"),
    ("[持股上限] Amazon 转股后持股上限", 0.12, "—", "占资本(as-converted 含期权等)·Amazon 可豁免", "MD&A"),
    ("[持股上限] Google 2026 NPA 持股上限", 0.1499, "—", "占发行后 as-converted 资本·Google 可豁免", "MD&A"),
    ("[LTBT] 公司向长期利益信托拨款", 2.7, "2023", "百万美元", "Certain Relationships"),
    ("[LTBT] 公司向长期利益信托拨款", 0.9, "2025", "百万美元", "Certain Relationships"),
    ("[LTBT] 公司向长期利益信托拨款", 8.4, "2026前三季", "百万美元", "Certain Relationships"),
    ("[收购] Stainless Software 对价", 306, "2026-05-18", "百万美元·商誉253", "附注15"),
    ("[收购] Bun(Codeblog Corp.)对价", 171, "2025-12-02", "百万美元·商誉154", "附注15"),
    ("[收购] 2026H1 其他收购对价合计", 260, "2026H1", "百万美元", "附注15"),
    ("[收购] Coefficient Bio 对价(A类股)", 15.4, "2026-04", "百万股", "附注16"),
    ("[投资] 中型企业 AI 服务新实体(Ode with Anthropic)投资承诺", 325, "2026-05", "百万美元", "附注16/MD&A"),
]
table("OTHER", ["值", "时点或期间", "单位", "出处"],
      [(k, [v, t, u, s]) for k, v, t, u, s in OTHER],
      f"# 长表; 来源: {SRC} 附注 8/9/11/13/15/16/17 + MD&A + Certain Relationships; ⚠️ 诉讼除 Bartz 外均未计提、未给金额区间(附注 13)",
      "或有事项与其他.csv")


# ====================================================================== 勾稽校验
def checks():
    errs = []

    def eq(label, a, b, tol=0):
        if a is None or b is None:
            STATS["skipped"].append(label)
            return
        STATS["run"] += 1
        if abs(a - b) > tol + 1e-9:
            errs.append(f"{label}: {a} != {b} (差 {round(a - b, 4)})")

    def chain(t, cols, prefix=""):
        """利润表链条：分项=费用合计 → 经营利润 → 其他收支 → 税前 → 净利。"""
        for c in cols:
            p = lambda k: g(t, k, c)
            eq(f"{t}{c} 经营费用合计", sum(p(k) for k in (
                "算力与基础设施 Compute and infrastructure", "人员开支 Personnel", "Bartz和解费用 Bartz settlement",
                "销售营销与合作伙伴 Sales, marketing, and partnerships",
                "其他运营与行政 Other operating and administrative")), p("经营费用合计 Total operating expenses"))
            op = [r for r in ("经营利润 Operating loss", "经营利润 Operating income (loss)")
                  if any(k == r for k, _ in T[t]["rows"])][0]
            eq(f"{t}{c} 经营利润", p("营业收入 Revenue") + p("经营费用合计 Total operating expenses"), p(op))
            eq(f"{t}{c} 其他收支合计", p("利息收入 Interest income")
               + p("可转债等公允价值变动 Change in FV of convertible notes, derivative liabilities, and SAFEs")
               + p("其他收入(支出)净额 Other income (expense), net"), p("其他收支合计 Total other income (expense), net"))
            eq(f"{t}{c} 除税前", p(op) + p("其他收支合计 Total other income (expense), net"),
               p("除税前利润 Loss before provision for income taxes"))
            eq(f"{t}{c} 净利", p("除税前利润 Loss before provision for income taxes")
               + p("所得税(费用为负) Provision for income taxes"), p("净利润 Net loss"))

    chain("IS", Y)
    chain("IIS", H)
    chain("QIS", Q)

    # 综合收益
    for t, cols in (("IS", Y), ("IIS", H)):
        for c in cols:
            eq(f"{t}{c} 综合收益", g(t, "净利润 Net loss", c) + g(t, "其他综合收益-可供出售证券未实现损益 OCI AFS", c)
               + g(t, "其他综合收益-外币折算 OCI FX", c), g(t, "综合收益 Comprehensive loss", c))
            # EPS = 净利 / 加权股数（四舍五入到分）
            eps = g(t, "净利润 Net loss", c) * 1000 / g(t, "加权平均股数(千股) Weighted-average shares (thousands)", c)
            eq(f"{t}{c} EPS", round(eps, 2), g(t, "每股基本及摊薄亏损(美元) EPS basic and diluted", c))
            # 非GAAP 调节（公司口径）：经营利润 + SBC + 非现金捐赠 - Bartz
            adj = (g(t, "经营利润 Operating loss", c) + g(t, "[补充] 股权激励费用(利润表口径·含回购溢价) SBC expense", c)
                   + g(t, "[补充] 非现金慈善捐赠(捐赠匹配计划) Non-cash charitable contributions", c)
                   - g(t, "Bartz和解费用 Bartz settlement", c))
            eq(f"{t}{c} 调整后经营利润", adj, g(t, "[非GAAP·公司口径] 调整后经营利润 Adjusted operating income (loss)", c))
            adjn = (g(t, "净利润 Net loss", c) + g(t, "[补充] 股权激励费用(利润表口径·含回购溢价) SBC expense", c)
                    + g(t, "[补充] 非现金慈善捐赠(捐赠匹配计划) Non-cash charitable contributions", c)
                    - g(t, "Bartz和解费用 Bartz settlement", c)
                    - g(t, "可转债等公允价值变动 Change in FV of convertible notes, derivative liabilities, and SAFEs", c)
                    + g(t, "[补充] 特定按市值计量金融工具公允价值变动 Change in FV of certain MTM instruments", c))
            eq(f"{t}{c} 调整后净利润", adjn, g(t, "[非GAAP·公司口径] 调整后净利润 Adjusted net income (loss)", c))
    for c in Q:
        adj = (g("QIS", "经营利润 Operating income (loss)", c) + g("QIS", "[补充] 股权激励费用 SBC expense", c)
               + g("QIS", "[补充] 非现金慈善捐赠 Non-cash charitable contributions", c)
               - g("QIS", "Bartz和解费用 Bartz settlement", c))
        eq(f"QIS{c} 调整后经营利润", adj, g("QIS", "[非GAAP·公司口径] 调整后经营利润 Adjusted operating income (loss)", c))
        adjn = (g("QIS", "净利润 Net loss", c) + g("QIS", "[补充] 股权激励费用 SBC expense", c)
                + g("QIS", "[补充] 非现金慈善捐赠 Non-cash charitable contributions", c)
                - g("QIS", "Bartz和解费用 Bartz settlement", c)
                - g("QIS", "可转债等公允价值变动 Change in FV of convertible notes, derivative liabilities, and SAFEs", c)
                + g("QIS", "[补充] 特定按市值计量金融工具公允价值变动 Change in FV of certain MTM instruments", c))
        eq(f"QIS{c} 调整后净利润", adjn, g("QIS", "[非GAAP·公司口径] 调整后净利润 Adjusted net income (loss)", c))

    # 单季 → 年度 / 半年：每个利润表科目四季之和 = 年度，两季之和 = H1
    for k, _ in QIS_ROWS:
        if k.startswith("[") or "Operating income" in k:
            continue
        eq(f"四季合计=2025年 {k}", sum(g("QIS", k, c) for c in Q[:4]), g("IS", k, "2025"))
        eq(f"两季合计=2025H1 {k}", sum(g("QIS", k, c) for c in Q[:2]), g("IIS", k, "2025H1"))
        eq(f"两季合计=2026H1 {k}", sum(g("QIS", k, c) for c in Q[4:]), g("IIS", k, "2026H1"))
    for a, b in (("经营利润 Operating income (loss)", "经营利润 Operating loss"),):
        eq("四季合计=2025年 经营利润", sum(g("QIS", a, c) for c in Q[:4]), g("IS", b, "2025"))
        eq("两季合计=2026H1 经营利润", sum(g("QIS", a, c) for c in Q[4:]), g("IIS", b, "2026H1"))
    for k_q, k_y in (("[补充] 股权激励费用 SBC expense", "[补充] 股权激励费用(利润表口径·含回购溢价) SBC expense"),
                     ("[补充] 非现金慈善捐赠 Non-cash charitable contributions",
                      "[补充] 非现金慈善捐赠(捐赠匹配计划) Non-cash charitable contributions"),
                     ("[补充] 特定按市值计量金融工具公允价值变动 Change in FV of certain MTM instruments",
                      "[补充] 特定按市值计量金融工具公允价值变动 Change in FV of certain MTM instruments"),
                     ("[非GAAP·公司口径] 调整后经营利润 Adjusted operating income (loss)",
                      "[非GAAP·公司口径] 调整后经营利润 Adjusted operating income (loss)"),
                     ("[非GAAP·公司口径] 调整后净利润 Adjusted net income (loss)",
                      "[非GAAP·公司口径] 调整后净利润 Adjusted net income (loss)")):
        eq(f"四季合计=2025年 {k_q}", sum(g("QIS", k_q, c) for c in Q[:4]), g("IS", k_y, "2025"))
        eq(f"两季合计=2025H1 {k_q}", sum(g("QIS", k_q, c) for c in Q[:2]), g("IIS", k_y, "2025H1"))
        eq(f"两季合计=2026H1 {k_q}", sum(g("QIS", k_q, c) for c in Q[4:]), g("IIS", k_y, "2026H1"))

    # 其他收支拆分（附注 8）= 利润表其他收入
    eq("2026H1 其他收支拆分合计", sum(g("IIS", k, "2026H1") for k, _ in IIS_ROWS if k.startswith("[其他收支拆分]")),
       g("IIS", "其他收入(支出)净额 Other income (expense), net", "2026H1"))
    eq("2026H1 NPA 其他收支 = Level3 新增+公允价值变动",
       g("L3", "[票据购买协议·资产] 新增 Additions", "2026H1") + g("L3", "[票据购买协议·资产] 公允价值变动 Change in fair value", "2026H1"),
       g("IIS", "[其他收支拆分] 票据购买协议初始确认及公允价值变动 Recognition and change in FV of NPAs", "2026H1"))
    eq("2026H1 认股权利 其他收支 = Level3", g("L3", "[认股权利·资产] 公允价值变动 Change in fair value", "2026H1"),
       g("IIS", "[其他收支拆分] 认股权利公允价值变动 Change in FV of warrant rights", "2026H1"))
    eq("2026H1 现金流其他金融工具 = -(NPA+尾款+认股权利)",
       -(g("IIS", "[其他收支拆分] 票据购买协议初始确认及公允价值变动 Recognition and change in FV of NPAs", "2026H1")
         + g("IIS", "[其他收支拆分] 收购尾款负债公允价值变动 Change in FV of holdback liability", "2026H1")
         + g("IIS", "[其他收支拆分] 认股权利公允价值变动 Change in FV of warrant rights", "2026H1")),
       g("IIS", "[现金流] 其他金融工具确认及公允价值变动 Other financial instruments", "2026H1"))
    eq("2026H1 特定MTM(非GAAP) = 现金流其他金融工具",
       g("IIS", "[补充] 特定按市值计量金融工具公允价值变动 Change in FV of certain MTM instruments", "2026H1"),
       g("IIS", "[现金流] 其他金融工具确认及公允价值变动 Other financial instruments", "2026H1"))

    # 职能口径 = 性质口径
    for c in P5:
        eq(f"职能{c} 合计", sum(g("FN", k, c) for k, _ in FN_ROWS[1:6]), g("FN", "经营费用合计 Total operating expenses", c))
        src_t, col = ("IS", c) if c in Y else ("IIS", c)
        eq(f"职能{c} 合计=利润表", g("FN", "经营费用合计 Total operating expenses", c),
           g(src_t, "经营费用合计 Total operating expenses", col))
        eq(f"职能{c} 收入=利润表", g("FN", "营业收入 Revenue", c), g(src_t, "营业收入 Revenue", col))
        eq(f"职能{c} Bartz=利润表", g("FN", "Bartz和解费用 Bartz settlement", c), g(src_t, "Bartz和解费用 Bartz settlement", col))

    # 资产负债表
    for t, cols in (("BS", ["2024", "2025"]), ("IBS", ["2025-12-31", "2026-06-30"])):
        for c in cols:
            p = lambda k: g(t, k, c)
            eq(f"{t}{c} 流动资产", p("货币资金 Cash and cash equivalents") + p("短期投资 Short-term investments")
               + p("应收账款净额 Accounts receivable, net") + p("预付及其他流动资产 Prepaid expenses and other current assets"),
               p("流动资产合计 Total current assets"))
            eq(f"{t}{c} 资产总计", p("流动资产合计 Total current assets") + p("受限现金 Restricted cash")
               + p("物业设备净额 Property and equipment, net") + p("经营租赁使用权资产 Operating lease right-of-use assets")
               + p("商誉 Goodwill") + p("其他非流动资产 Other assets, noncurrent"), p("资产总计 Total assets"))
            eq(f"{t}{c} 流动负债", p("应付应计及其他流动负债 Accounts payable, accrued expenses, and other current liabilities")
               + p("经营租赁负债-流动 Operating lease liabilities, current") + p("合同负债(递延收入) Deferred revenue"),
               p("流动负债合计 Total current liabilities"))
            eq(f"{t}{c} 负债合计", p("流动负债合计 Total current liabilities")
               + p("经营租赁负债-非流动 Operating lease liabilities, noncurrent")
               + p("可转换票据(公允价值) Convertible notes payable") + p("其他非流动负债 Other noncurrent liabilities"),
               p("负债合计 Total liabilities"))
            eq(f"{t}{c} 股东权益", p("资本公积 Additional paid-in capital")
               + p("累计其他综合收益 Accumulated other comprehensive income (loss)") + p("累计亏损 Accumulated deficit"),
               p("股东权益(亏绌)合计 Total stockholders' deficit"))
            eq(f"{t}{c} 负债+优先股+权益", p("负债合计 Total liabilities")
               + p("可赎回可转换优先股 Redeemable convertible preferred stock")
               + p("股东权益(亏绌)合计 Total stockholders' deficit"),
               p("负债+优先股+权益合计 Total liabilities, RCPS, and stockholders' deficit"))
            eq(f"{t}{c} 资产=负债+优先股+权益", p("资产总计 Total assets"),
               p("负债+优先股+权益合计 Total liabilities, RCPS, and stockholders' deficit"))
            eq(f"{t}{c} 预付及其他流动(附注8)", p("[附注8] 预付费用-流动 Prepaid expenses current") + p("[附注8] 其他-流动 Other current"),
               p("预付及其他流动资产 Prepaid expenses and other current assets"))
            eq(f"{t}{c} 其他非流动(附注8)", p("[附注8] 预付费用-非流动 Prepaid expenses noncurrent") + p("[附注8] 其他-非流动 Other noncurrent"),
               p("其他非流动资产 Other assets, noncurrent"))
            eq(f"{t}{c} 应付应计(附注8)", p("[附注8] 云服务商应付款 Cloud service provider payables")
               + p("[附注8] 应计法律费用 Accrued legal expenses") + p("[附注8] 捐赠匹配负债 Donation matching program liability")
               + p("[附注8] 其他应付应计 Other"),
               p("应付应计及其他流动负债 Accounts payable, accrued expenses, and other current liabilities"))
            eq(f"{t}{c} 物业设备原值(附注6)", p("[附注6] 租赁物业改良 Leasehold improvements")
               + p("[附注6] 服务器网络及基础设施设备 Servers, networking, and infrastructure equipment")
               + p("[附注6] 在建工程 Construction in progress") + p("[附注6] 其他物业设备 Other assets"),
               p("[附注6] 物业设备原值合计 Total property and equipment, gross"))
            eq(f"{t}{c} 物业设备净额(附注6)", p("[附注6] 物业设备原值合计 Total property and equipment, gross")
               + p("[附注6] 累计折旧 Accumulated depreciation"), p("物业设备净额 Property and equipment, net"))
            eq(f"{t}{c} 可转债=Level3期末", p("可转换票据(公允价值) Convertible notes payable"),
               g("L3", "[可转换票据] 期末 Ending", {"2024": "2024", "2025": "2025", "2025-12-31": "2025",
                                                "2026-06-30": "2026H1"}[c]))
            eq(f"{t}{c} 优先股=明细合计", p("可赎回可转换优先股 Redeemable convertible preferred stock"),
               g("PREF", "[合计] 账面价值 Total carrying value", {"2024": "2024-12-31", "2025": "2025-12-31",
                                                            "2025-12-31": "2025-12-31", "2026-06-30": "2026-06-30"}[c]))
            eq(f"{t}{c} 清算优先权=明细合计", p("[附] 优先股清算优先权 Aggregate liquidation preference"),
               g("PREF", "[合计] 清算优先权 Total liquidation preference", {"2024": "2024-12-31", "2025": "2025-12-31",
                                                                     "2025-12-31": "2025-12-31", "2026-06-30": "2026-06-30"}[c]))
            eq(f"{t}{c} 优先股股数=明细合计", p("[附] 优先股已发行股数(千股) RCPS shares outstanding (thousands)"),
               g("PREF", "[合计] 已发行股数(千股) Total shares", {"2024": "2024-12-31", "2025": "2025-12-31",
                                                            "2025-12-31": "2025-12-31", "2026-06-30": "2026-06-30"}[c]))
    # 两张资产负债表 2025-12-31 必须一致
    for k in BS_KEYS:
        eq(f"BS2025=IBS2025-12-31 {k}", g("BS", k, "2025"), g("IBS", k, "2025-12-31"))
    # 公允价值层级（附注 4）
    eq("2025 公允价值资产合计", 16455 + 4 + 123 + 2114 + 652 + g("BS", "[附注4] 认股权利(公允价值) Warrant rights", "2025"), 19693)
    eq("2025 短期投资=附注3", 123 + 2114 + 652, g("BS", "短期投资 Short-term investments", "2025"))
    eq("2026-06 短期投资=附注3", 1589 + 14785 + 2888, g("IBS", "短期投资 Short-term investments", "2026-06-30"))
    eq("2026-06 公允价值资产合计", 108603 + (18 + 264 + 4 + 8 + 1589 + 14785 + 2888)
       + g("IBS", "[附注4] 认股权利(公允价值) Warrant rights", "2026-06-30")
       + g("IBS", "[附注4] 票据购买协议资产(公允价值) Note purchase agreements", "2026-06-30"), 131633)
    eq("2026-06 公允价值负债合计", 58 + g("IBS", "可转换票据(公允价值) Convertible notes payable", "2026-06-30"), 108624)
    eq("2025 公允价值负债合计", g("BS", "[附注8] 捐赠匹配负债 Donation matching program liability", "2025")
       + g("BS", "可转换票据(公允价值) Convertible notes payable", "2025") + 28, 42246)
    eq("2025 到期结构=现金等价物+短投摊余", 18632 + 712, g("BS", "[附注3] 现金等价物 Total cash equivalents", "2025")
       + g("BS", "[附注3] 短期投资摊余成本 Short-term investments amortized cost", "2025"))
    eq("2026-06 到期结构=现金等价物+短投摊余", 120668 + 7535, g("IBS", "[附注3] 现金等价物 Total cash equivalents", "2026-06-30")
       + g("IBS", "[附注3] 短期投资摊余成本 Short-term investments amortized cost", "2026-06-30"))

    # 现金流量表
    def cf_chain(t, cols, pre):
        for c in cols:
            p = lambda k: g(t, pre + k, c)
            ops = ("净利润 Net loss", "股权激励 Stock-based compensation", "折旧摊销 Depreciation and amortization",
                   "可转债等公允价值变动 Change in FV of convertible notes etc.",
                   "捐赠匹配负债 Donation matching program liability",
                   "其他金融工具确认及公允价值变动 Other financial instruments", "其他 Other",
                   "应收账款变动 Accounts receivable", "预付及其他资产变动 Prepaid expenses and other assets",
                   "应付应计及其他负债变动 AP, accrued and other liabilities", "租赁负债变动 Lease liabilities",
                   "合同负债变动 Deferred revenue")
            eq(f"{t}{c} 经营现金流", sum(p(k) for k in ops), p("经营活动现金流净额 Net cash from operating"))
            inv = ("购建物业设备(capex) Purchases of property and equipment", "购买短期投资 Purchases of short-term investments",
                   "出售及到期短期投资 Sales and maturities of short-term investments", "其他投资活动 Other investing activities")
            eq(f"{t}{c} 投资现金流", sum(p(k) for k in inv), p("投资活动现金流净额 Net cash used in investing"))
            fin = ("发行优先股净额 Proceeds from RCPS, net", "融资租赁本金偿还 Principal payments for finance leases",
                   "发行可转债收现 Issuance of convertible notes for cash", "发行普通股收现 Proceeds from issuance of common stock",
                   "回购普通股 Repurchase of common stock", "发行SAFE收现 Issuance of SAFEs for cash",
                   "支付发行费用 Payment of deferred offering costs")
            eq(f"{t}{c} 融资现金流", sum(p(k) for k in fin), p("融资活动现金流净额 Net cash from financing"))
            eq(f"{t}{c} 现金净变动", p("经营活动现金流净额 Net cash from operating") + p("投资活动现金流净额 Net cash used in investing")
               + p("融资活动现金流净额 Net cash from financing") + p("汇率影响 Effect of exchange rate changes"),
               p("现金净变动 Net increase in cash"))
            eq(f"{t}{c} 期初+净变动=期末", p("期初现金及受限现金 Cash beginning of " + ("year" if t == "CF" else "period"))
               + p("现金净变动 Net increase in cash"), p("期末现金及受限现金 Cash end of " + ("year" if t == "CF" else "period")))
    cf_chain("CF", Y, "")
    cf_chain("IIS", H, "[现金流] ")
    for c in Y:
        eq(f"CF{c} 净利=利润表", g("CF", "净利润 Net loss", c), g("IS", "净利润 Net loss", c))
        eq(f"CF{c} 公允价值变动=利润表", g("CF", "可转债等公允价值变动 Change in FV of convertible notes etc.", c),
           -g("IS", "可转债等公允价值变动 Change in FV of convertible notes, derivative liabilities, and SAFEs", c))
        eq(f"CF{c} 股权激励(现金流)+回购溢价=利润表口径", g("CF", "股权激励 Stock-based compensation", c)
           + g("IS", "[补充] 其中现金回购溢价计入股权激励 SBC from repurchase premium", c),
           g("IS", "[补充] 股权激励费用(利润表口径·含回购溢价) SBC expense", c))
        eq(f"CF{c} 股权激励=权益变动表", g("CF", "股权激励 Stock-based compensation", c), g("EQ", "[资本公积] 股权激励 Stock-based compensation", c))
        eq(f"CF{c} 折旧摊销>=折旧+无形摊销", min(0, g("CF", "折旧摊销 Depreciation and amortization", c)
           - g("IS", "[补充] 固定资产折旧 Depreciation", c) - g("IS", "[补充] 无形资产摊销 Intangible amortization", c)), 0)
    for c in H:
        eq(f"IIS{c} 现金流净利=利润表", g("IIS", "[现金流] 净利润 Net loss", c), g("IIS", "净利润 Net loss", c))
        eq(f"IIS{c} 公允价值变动=利润表", g("IIS", "[现金流] 可转债等公允价值变动 Change in FV of convertible notes etc.", c),
           -g("IIS", "可转债等公允价值变动 Change in FV of convertible notes, derivative liabilities, and SAFEs", c))
        eq(f"IIS{c} 股权激励=权益变动表", g("IIS", "[现金流] 股权激励 Stock-based compensation", c),
           g("EQ", "[资本公积] 股权激励 Stock-based compensation", c))
    eq("2025H1 利润表股权激励-现金流=回购溢价7", g("IIS", "[补充] 股权激励费用(利润表口径·含回购溢价) SBC expense", "2025H1")
       - g("IIS", "[现金流] 股权激励 Stock-based compensation", "2025H1"), 7)
    eq("2026H1 利润表股权激励=现金流", g("IIS", "[补充] 股权激励费用(利润表口径·含回购溢价) SBC expense", "2026H1"),
       g("IIS", "[现金流] 股权激励 Stock-based compensation", "2026H1"))
    # 期末现金及受限现金 = 资产负债表 货币资金 + 受限现金
    for c_cf, t, c_bs in (("2024", "BS", "2024"), ("2025", "BS", "2025")):
        eq(f"CF{c_cf} 期末现金=资产负债表", g("CF", "期末现金及受限现金 Cash end of year", c_cf),
           g(t, "货币资金 Cash and cash equivalents", c_bs) + g(t, "受限现金 Restricted cash", c_bs))
    eq("IIS2026H1 期末现金=资产负债表", g("IIS", "[现金流] 期末现金及受限现金 Cash end of period", "2026H1"),
       g("IBS", "货币资金 Cash and cash equivalents", "2026-06-30") + g("IBS", "受限现金 Restricted cash", "2026-06-30"))
    eq("CF 年度期初衔接 2024=2023期末", g("CF", "期初现金及受限现金 Cash beginning of year", "2024"), g("CF", "期末现金及受限现金 Cash end of year", "2023"))
    eq("CF 年度期初衔接 2025=2024期末", g("CF", "期初现金及受限现金 Cash beginning of year", "2025"), g("CF", "期末现金及受限现金 Cash end of year", "2024"))
    eq("IIS 2025H1期初=2024期末", g("IIS", "[现金流] 期初现金及受限现金 Cash beginning of period", "2025H1"), g("CF", "期末现金及受限现金 Cash end of year", "2024"))
    eq("IIS 2026H1期初=2025期末", g("IIS", "[现金流] 期初现金及受限现金 Cash beginning of period", "2026H1"), g("CF", "期末现金及受限现金 Cash end of year", "2025"))
    # 资产负债表变动 vs 现金流（应收、合同负债：年度可直接对）
    eq("2025 应收变动≈现金流(含坏账)", g("BS", "应收账款净额 Accounts receivable, net", "2024") - g("BS", "应收账款净额 Accounts receivable, net", "2025"),
       g("CF", "应收账款变动 Accounts receivable", "2025"), tol=20)   # 差额=坏账计提20(附注1), 现金流中计入「其他」
    eq("2025 合同负债变动=现金流", g("BS", "合同负债(递延收入) Deferred revenue", "2025") - g("BS", "合同负债(递延收入) Deferred revenue", "2024"),
       g("CF", "合同负债变动 Deferred revenue", "2025"))
    # 源表本身差 1（资产负债表 269→1,650 增 1,381、现金流 1,380）：资产负债表与附注 2 滚动表 269−196+1,577=1,650 自洽，
    # 差额应是收购带入或汇率，非转录错——显式放宽到 1，并在 README 记录
    eq("2026H1 合同负债变动=现金流", g("IBS", "合同负债(递延收入) Deferred revenue", "2026-06-30") - g("IBS", "合同负债(递延收入) Deferred revenue", "2025-12-31"),
       g("IIS", "[现金流] 合同负债变动 Deferred revenue", "2026H1"), tol=1)

    # 权益变动表
    for c in P5:
        p = lambda k: g("EQ", k, c)
        eq(f"EQ{c} 优先股滚动", p("[优先股] 期初账面 RCPS beginning") + p("[优先股] 发行(净额) Issuance, net")
           + p("[优先股] 可转债转入 Conversion of convertible notes") + p("[优先股] SAFE转入 Conversion of SAFEs"),
           p("[优先股] 期末账面 RCPS ending"))
        eq(f"EQ{c} 优先股股数滚动", p("[优先股] 期初股数(千股) Shares beginning") + p("[优先股] 发行股数(千股) Shares issued")
           + p("[优先股] 转换取得股数(千股) Shares from conversions"), p("[优先股] 期末股数(千股) Shares ending"))
        eq(f"EQ{c} A类股数滚动", p("[A类股] 期初股数(千股) Class A beginning") + p("[A类股] 行权及授予股数(千股) Option exercises and grants")
           + p("[A类股] 回购注销(千股) Repurchased") + p("[A类股] 收购发行(千股) Issued in acquisitions"),
           p("[A类股] 期末股数(千股) Class A ending"))
        eq(f"EQ{c} 资本公积滚动", p("[资本公积] 期初 APIC beginning") + p("[资本公积] 行权及售股 Option exercises and sales")
           + p("[资本公积] 股权激励 Stock-based compensation") + p("[资本公积] 收购发行股权 Equity issued in acquisitions")
           + p("[资本公积] 捐赠匹配结算发行N类股 Class N for donation matching") + p("[资本公积] 其他 Other"),
           p("[资本公积] 期末 APIC ending"))
        eq(f"EQ{c} 累计亏损滚动", p("[累计亏损] 期初 Accumulated deficit beginning") + p("[累计亏损] 净亏损 Net loss")
           + p("[累计亏损] 回购公允价值 Repurchase at fair value"), p("[累计亏损] 期末 Accumulated deficit ending"))
        eq(f"EQ{c} 股东权益合计", p("[资本公积] 期末 APIC ending") + p("[其他综合收益] 期末 AOCI ending")
           + p("[累计亏损] 期末 Accumulated deficit ending"), p("[股东权益] 期末合计 Total stockholders' deficit ending"))
        src_t, col = ("IS", c) if c in Y else ("IIS", c)
        eq(f"EQ{c} 净亏损=利润表", p("[累计亏损] 净亏损 Net loss"), g(src_t, "净利润 Net loss", col))
        cft, cfc, pre = ("CF", c, "") if c in Y else ("IIS", c, "[现金流] ")
        eq(f"EQ{c} 优先股现金部分=现金流", p("[优先股] 发行(净额) Issuance, net") - p("[优先股] 其中票据购买协议结算转入 Of which NPA settlement"),
           g(cft, pre + "发行优先股净额 Proceeds from RCPS, net", cfc))
        eq(f"EQ{c} 行权售股=现金流", p("[资本公积] 行权及售股 Option exercises and sales"), g(cft, pre + "发行普通股收现 Proceeds from issuance of common stock", cfc))
    for c_eq, t, c_bs in (("2024", "BS", "2024"), ("2025", "BS", "2025"), ("2026H1", "IBS", "2026-06-30")):
        eq(f"EQ{c_eq} 期末优先股=资产负债表", g("EQ", "[优先股] 期末账面 RCPS ending", c_eq), g(t, "可赎回可转换优先股 Redeemable convertible preferred stock", c_bs))
        eq(f"EQ{c_eq} 期末资本公积=资产负债表", g("EQ", "[资本公积] 期末 APIC ending", c_eq), g(t, "资本公积 Additional paid-in capital", c_bs))
        eq(f"EQ{c_eq} 期末累计亏损=资产负债表", g("EQ", "[累计亏损] 期末 Accumulated deficit ending", c_eq), g(t, "累计亏损 Accumulated deficit", c_bs))
        eq(f"EQ{c_eq} 期末股东权益=资产负债表", g("EQ", "[股东权益] 期末合计 Total stockholders' deficit ending", c_eq), g(t, "股东权益(亏绌)合计 Total stockholders' deficit", c_bs))
        eq(f"EQ{c_eq} 期末A类股数=资产负债表", g("EQ", "[A类股] 期末股数(千股) Class A ending", c_eq),
           g(t, "[附] A类普通股已发行股数(千股) Class A shares outstanding (thousands)", c_bs))
        eq(f"EQ{c_eq} 期末优先股股数=资产负债表", g("EQ", "[优先股] 期末股数(千股) Shares ending", c_eq),
           g(t, "[附] 优先股已发行股数(千股) RCPS shares outstanding (thousands)", c_bs))
    eq("EQ 期初衔接 2024=2023期末", g("EQ", "[优先股] 期初账面 RCPS beginning", "2024"), g("EQ", "[优先股] 期末账面 RCPS ending", "2023"))
    eq("EQ 期初衔接 2025=2024期末", g("EQ", "[资本公积] 期初 APIC beginning", "2025"), g("EQ", "[资本公积] 期末 APIC ending", "2024"))
    eq("EQ 期初衔接 2026H1=2025期末", g("EQ", "[累计亏损] 期初 Accumulated deficit beginning", "2026H1"), g("EQ", "[累计亏损] 期末 Accumulated deficit ending", "2025"))
    eq("EQ 2026H1 NPA结算=Level3结算", g("EQ", "[优先股] 其中票据购买协议结算转入 Of which NPA settlement", "2026H1"),
       g("L3", "[票据购买协议·资产] 结算 Settlement", "2026H1"))
    eq("EQ 2026H1 NPA结算=非现金披露", g("EQ", "[优先股] 其中票据购买协议结算转入 Of which NPA settlement", "2026H1"),
       g("IIS", "[非现金] 票据购买协议转G-2优先股 Conversion of NPAs into Series G-2", "2026H1"))
    for c in ("2025", "2026H1"):
        cft, pre = ("CF", "") if c == "2025" else ("IIS", "[现金流] ")
        k_nc = "[非现金] 可转债转优先股 Conversion of convertible notes into RCPS"
        eq(f"EQ{c} 可转债转入=非现金披露", g("EQ", "[优先股] 可转债转入 Conversion of convertible notes", c),
           g(cft, k_nc, c))
        eq(f"EQ{c} 可转债转入=Level3转股", g("EQ", "[优先股] 可转债转入 Conversion of convertible notes", c),
           -g("L3", "[可转换票据] 转股 Conversion", c))
    eq("EQ2024 SAFE转入=非现金披露", g("EQ", "[优先股] SAFE转入 Conversion of SAFEs", "2024"), g("CF", "[非现金] SAFE转优先股 Conversion of SAFEs into RCPS", "2024"))
    eq("EQ2024 SAFE转入=Level3", g("EQ", "[优先股] SAFE转入 Conversion of SAFEs", "2024"), -g("L3", "[SAFE] 转股 Conversion", "2024"))
    eq("EQ2026H1 捐赠匹配N类股=Level3结算", g("EQ", "[资本公积] 捐赠匹配结算发行N类股 Class N for donation matching", "2026H1"),
       -g("L3", "[捐赠匹配负债] 结算 Settlement", "2026H1"))
    eq("EQ2026H1 收购发行=非现金披露", g("EQ", "[资本公积] 收购发行股权 Equity issued in acquisitions", "2026H1"),
       g("IIS", "[非现金] 收购发行股权 Equity issued in business acquisitions", "2026H1"))

    # Level 3 滚动
    for c in ("2024", "2025", "2026H1"):
        p = lambda k: g("L3", k, c)
        for inst, parts in (("可转换票据", ("期初 Beginning", "新增 Additions", "转股 Conversion", "公允价值变动 Change in fair value")),
                            ("衍生负债", ("期初 Beginning", "新增 Additions", "公允价值变动及结算 Change in FV and settlement")),
                            ("SAFE", ("期初 Beginning", "转股 Conversion", "公允价值变动 Change in fair value")),
                            ("认股权利·资产", ("期初 Beginning", "新增 Additions", "公允价值变动 Change in fair value")),
                            ("票据购买协议·资产", ("期初 Beginning", "新增 Additions", "公允价值变动 Change in fair value", "结算 Settlement")),
                            ("捐赠匹配负债", ("期初 Beginning", "新增 Additions", "公允价值变动 Change in fair value", "结算 Settlement")),
                            ("收购尾款负债", ("期初 Beginning", "新增 Additions", "公允价值变动 Change in fair value"))):
            eq(f"L3{c} {inst}滚动", sum(p(f"[{inst}] {x}") for x in parts), p(f"[{inst}] 期末 Ending"))
    for a, b in (("2024", "2025"), ("2025", "2026H1")):
        for inst in ("可转换票据", "衍生负债", "认股权利·资产", "捐赠匹配负债", "收购尾款负债"):
            eq(f"L3 {inst} {b}期初={a}期末", g("L3", f"[{inst}] 期初 Beginning", b), g("L3", f"[{inst}] 期末 Ending", a))
    # 利润表公允价值变动 = 可转债 + SAFE + 衍生负债（2024/2025）；2026H1 只有可转债
    eq("2024 利润表公允价值变动=Level3", -(g("L3", "[可转换票据] 公允价值变动 Change in fair value", "2024")
       + g("L3", "[SAFE] 公允价值变动 Change in fair value", "2024")
       + g("L3", "[衍生负债] 公允价值变动及结算 Change in FV and settlement", "2024")),
       g("IS", "可转债等公允价值变动 Change in FV of convertible notes, derivative liabilities, and SAFEs", "2024"))
    eq("2025 利润表公允价值变动=Level3", -(g("L3", "[可转换票据] 公允价值变动 Change in fair value", "2025")
       + g("L3", "[衍生负债] 公允价值变动及结算 Change in FV and settlement", "2025")),
       g("IS", "可转债等公允价值变动 Change in FV of convertible notes, derivative liabilities, and SAFEs", "2025"))
    eq("2026H1 利润表公允价值变动=Level3", -g("L3", "[可转换票据] 公允价值变动 Change in fair value", "2026H1"),
       g("IIS", "可转债等公允价值变动 Change in FV of convertible notes, derivative liabilities, and SAFEs", "2026H1"))
    eq("2024 收现发债=票据新增+衍生负债新增", g("L3", "[可转换票据] 新增 Additions", "2024") + g("L3", "[衍生负债] 新增 Additions", "2024"),
       g("CF", "发行可转债收现 Issuance of convertible notes for cash", "2024"))
    eq("2025 收现发债=票据新增", g("L3", "[可转换票据] 新增 Additions", "2025"), g("CF", "发行可转债收现 Issuance of convertible notes for cash", "2025"))
    eq("2025 捐赠匹配新增=现金流", g("L3", "[捐赠匹配负债] 新增 Additions", "2025"), g("CF", "捐赠匹配负债 Donation matching program liability", "2025"))
    eq("2026H1 捐赠匹配变动=现金流", g("L3", "[捐赠匹配负债] 公允价值变动 Change in fair value", "2026H1"),
       g("IIS", "[现金流] 捐赠匹配负债 Donation matching program liability", "2026H1"))
    eq("2025 认股权利新增=非现金披露", g("L3", "[认股权利·资产] 新增 Additions", "2025"), g("CF", "[非现金] 认股权利 Warrant rights", "2025"))
    eq("2025 认股权利=资产负债表", g("L3", "[认股权利·资产] 期末 Ending", "2025"), g("BS", "[附注4] 认股权利(公允价值) Warrant rights", "2025"))
    eq("2026H1 认股权利=资产负债表", g("L3", "[认股权利·资产] 期末 Ending", "2026H1"), g("IBS", "[附注4] 认股权利(公允价值) Warrant rights", "2026-06-30"))
    eq("2026H1 NPA资产=资产负债表", g("L3", "[票据购买协议·资产] 期末 Ending", "2026H1"),
       g("IBS", "[附注4] 票据购买协议资产(公允价值) Note purchase agreements", "2026-06-30"))
    eq("2025 捐赠匹配=资产负债表", g("L3", "[捐赠匹配负债] 期末 Ending", "2025"), g("BS", "[附注8] 捐赠匹配负债 Donation matching program liability", "2025"))
    eq("2026-06 未偿票据本金合计", g("L3", "[未偿票据·2026-06-30] Amazon 2023 NPA 本金 Principal", "2026H1")
       + g("L3", "[未偿票据·2026-06-30] Amazon 2024 NPA 本金 Principal", "2026H1"), g("L3", "[未偿票据·2026-06-30] 本金合计 Total principal", "2026H1"))
    eq("2026-06 未偿票据可转股数合计", g("L3", "[未偿票据·2026-06-30] Amazon 2023 NPA 可转股数(股)", "2026H1")
       + g("L3", "[未偿票据·2026-06-30] Amazon 2024 NPA 可转股数(股)", "2026H1"), g("L3", "[未偿票据·2026-06-30] 可转N类股数(股) Class N issuable", "2026H1"))
    eq("2026-06 Amazon 2023 本金/转股价≈股数", round(g("L3", "[未偿票据·2026-06-30] Amazon 2023 NPA 本金 Principal", "2026H1") / 2.0928),
       round(g("L3", "[未偿票据·2026-06-30] Amazon 2023 NPA 可转股数(股)", "2026H1") / 1e6), tol=1)   # 本金取整到百万
    eq("2026-06 Amazon 2024 本金/转股价≈股数", round(g("L3", "[未偿票据·2026-06-30] Amazon 2024 NPA 本金 Principal", "2026H1") / 5.0478),
       round(g("L3", "[未偿票据·2026-06-30] Amazon 2024 NPA 可转股数(股)", "2026H1") / 1e6), tol=1)
    eq("2026-06 可转债折合股数=反稀释表", round(g("L3", "[未偿票据·2026-06-30] 可转N类股数(股) Class N issuable", "2026H1") / 1000),
       lv("DIL", "[反稀释] 可转债折合普通股", "2026H1"))
    eq("2026-06 未动用 NPA 合计", g("L3", "[未动用额度·2026-06-30] Google 2026 NPA", "2026H1")
       + g("L3", "[未动用额度·2026-06-30] Amazon 2026 NPA", "2026H1")
       + g("L3", "[未动用额度·2026-06-30] Broadcom 基础设施伙伴 2026 NPA(仅限付租)", "2026H1"),
       g("L3", "[未动用额度·2026-06-30] 合计 Total", "2026H1"))

    # 优先股明细
    for c in ("2024-12-31", "2025-12-31", "2026-06-30"):
        for metric, total in (("已发行股数(千股) Shares outstanding", "[合计] 已发行股数(千股) Total shares"),
                              ("账面价值 Net carrying value", "[合计] 账面价值 Total carrying value"),
                              ("清算优先权 Liquidation preference", "[合计] 清算优先权 Total liquidation preference")):
            eq(f"PREF{c} {metric}合计", sum(g("PREF", f"[{s}] {metric}", c) for s, *_ in PREF), g("PREF", total, c))
    eq("PREF 2026-06 折合普通股=反稀释表", g("PREF", "[合计] 按转换比例折合普通股(千股) As-converted common shares", "2026-06-30"),
       lv("DIL", "[反稀释] 优先股折合普通股", "2026H1"))

    # 收入拆分
    for c in P5:
        src_t, col = ("IS", c) if c in Y else ("IIS", c)
        eq(f"REV{c} 地区合计", g("REV", "[地区] 美国 United States", c) + g("REV", "[地区] 国际 International", c), g("REV", "[地区] 合计 Total", c))
        eq(f"REV{c} 计费合计", g("REV", "[计费方式] 按用量(token)计费 Consumption-based", c)
           + g("REV", "[计费方式] 订阅 Subscription-based", c), g("REV", "[计费方式] 合计 Total", c))
        eq(f"REV{c} 地区合计=利润表", g("REV", "[地区] 合计 Total", c), g(src_t, "营业收入 Revenue", col))
        eq(f"REV{c} 计费合计=利润表", g("REV", "[计费方式] 合计 Total", c), g(src_t, "营业收入 Revenue", col))
        # 客户层级收入占比（公司约数：允许 1.5pp）
        eq(f"REV{c} ≥10万客户收入/营收≈占比", round(g("REV", "[客户层级] TTM收入≥10万美元客户贡献收入(约数) Revenue from customers ≥$100K TTM", c)
                                            / g("REV", "[地区] 合计 Total", c), 3),
           g("REV", "[客户层级] TTM收入≥10万美元客户贡献收入占比(约数) Share of revenue", c), tol=0.015)
    # 合同负债滚动
    dr = lambda k, t: lv("OPS", k, t)
    eq("合同负债滚动2024", dr("[合同负债滚动] 期末 Deferred revenue ending", "2023-12-31")
       + dr("[合同负债滚动] 期初递延收入转收入 Revenue from opening deferred revenue", "2024")
       + dr("[合同负债滚动] 新增预收 Amounts billed in advance", "2024"), g("BS", "合同负债(递延收入) Deferred revenue", "2024"))
    eq("合同负债滚动2025", g("BS", "合同负债(递延收入) Deferred revenue", "2024")
       + dr("[合同负债滚动] 期初递延收入转收入 Revenue from opening deferred revenue", "2025")
       + dr("[合同负债滚动] 新增预收 Amounts billed in advance", "2025"), g("BS", "合同负债(递延收入) Deferred revenue", "2025"))
    eq("合同负债滚动2026H1", g("IBS", "合同负债(递延收入) Deferred revenue", "2025-12-31")
       + dr("[合同负债滚动] 期初递延收入转收入 Revenue from opening deferred revenue", "2026H1")
       + dr("[合同负债滚动] 新增预收 Amounts billed in advance", "2026H1"), g("IBS", "合同负债(递延收入) Deferred revenue", "2026-06-30"))
    eq("合同负债2023年末=现金流衔接", dr("[合同负债滚动] 期末 Deferred revenue ending", "2023-12-31")
       + g("CF", "合同负债变动 Deferred revenue", "2024"), g("BS", "合同负债(递延收入) Deferred revenue", "2024"))

    # 排期
    for k, _ in SCHED_ROWS:
        vals = rowv("SCHED", k)
        eq(f"排期合计 {k}", sum(vals[:6]), vals[6])
    sx = lambda k: rowv("SCHED", k)[6]
    eq("经营租赁@2025 现值", sx("[经营租赁@2025-12-31] 未折现付款") + sx("[经营租赁@2025-12-31] 减:利息"), sx("[经营租赁@2025-12-31] 租赁负债现值"))
    eq("经营租赁@2026-06 现值", sx("[经营租赁@2026-06-30] 未折现付款") + sx("[经营租赁@2026-06-30] 减:利息"), sx("[经营租赁@2026-06-30] 租赁负债现值"))
    eq("融资租赁@2026-06 现值", sx("[融资租赁@2026-06-30] 未折现付款") + sx("[融资租赁@2026-06-30] 减:利息"), sx("[融资租赁@2026-06-30] 租赁负债现值"))
    eq("融资租赁@2026-06 流动+非流动", sx("[融资租赁@2026-06-30] 计入流动负债") + sx("[融资租赁@2026-06-30] 计入非流动负债"), sx("[融资租赁@2026-06-30] 租赁负债现值"))
    eq("经营租赁@2025 现值=资产负债表", sx("[经营租赁@2025-12-31] 租赁负债现值"), g("BS", "经营租赁负债-流动 Operating lease liabilities, current", "2025")
       + g("BS", "经营租赁负债-非流动 Operating lease liabilities, noncurrent", "2025"))
    eq("经营租赁@2026-06 现值=资产负债表", sx("[经营租赁@2026-06-30] 租赁负债现值"), g("IBS", "经营租赁负债-流动 Operating lease liabilities, current", "2026-06-30")
       + g("IBS", "经营租赁负债-非流动 Operating lease liabilities, noncurrent", "2026-06-30"))
    eq("采购承诺@2025 合计=算力承诺表", sx("[采购承诺@2025-12-31] 不可撤销采购承诺"),
       lv("COMMIT", "[承诺总量] 不可撤销采购承诺(期限>1年) Non-cancelable purchase commitments", "2025-12-31"))
    eq("无形资产摊销@2025 合计=无形资产净额", sx("[无形资产摊销@2025-12-31] 预计摊销"), g("BS", "[附注5] 无形资产净额 Intangible assets, net", "2025"))
    eq("SpaceXAI 满载月费×(2027-01~2029-05·29个月)≤上限", min(0, lv("COMMIT", "[具名] SpaceXAI(原 X.AI) NVIDIA GPU 算力(上限)", "至2029")
       - 29 * lv("COMMIT", "[具名] SpaceXAI 满载月费", "2026-12起")), 0)   # 只防量级错: 月费×满载月数不得超过上限
    eq("Lambda 8月协议≤Lambda合计", min(0, lv("COMMIT", "[具名] Lambda NVIDIA GPU(合计)", "至2034")
       - lv("COMMIT", "[具名] Lambda 其中2026-08协议", "至2034")), 0)
    eq("扩展协议估计: 附注16=MD&A(下限)", lv("COMMIT", "[承诺总量] 已扩展协议预计付款(2028-2031交付·下限) Expanded agreements low", "2026-06-01"),
       lv("COMMIT", "[具名] Google等TPU供应商追加算力(2028-2031交付·下限)", "2028~2031"))
    eq("扩展协议估计: 附注16=MD&A(上限)", lv("COMMIT", "[承诺总量] 已扩展协议预计付款(2028-2031交付·上限) Expanded agreements high", "2026-06-01"),
       lv("COMMIT", "[具名] Google等TPU供应商追加算力(2028-2031交付·上限)", "2028~2031"))
    eq("Broadcom 托管存款≈受限现金增量", lv("COMMIT", "[担保] 为 Broadcom 租约存入托管账户", "2026-04"),
       g("IBS", "受限现金 Restricted cash", "2026-06-30") - g("IBS", "受限现金 Restricted cash", "2025-12-31"), tol=20)

    # 股权激励与稀释
    dil = lambda k, t: lv("DIL", k, t)
    eq("反稀释2026H1 合计", sum(dil(k, "2026H1") for k in ("[反稀释] 优先股折合普通股", "[反稀释] 可转债折合普通股",
                                                          "[反稀释] RSA", "[反稀释] 期权", "[反稀释] 收购尾款")),
       dil("[反稀释] 合计(不含RSU 1,049.6M)", "2026H1"))
    eq("RSU 2026-06 累计+未确认=总额", dil("[RSU] 若业绩条件成立应累计确认的费用(IPO时一次性补提)", "2026-06-30")
       + dil("[RSU] 届时剩余未确认费用", "2026-06-30"), dil("[RSU] 未确认费用总额", "2026-06-30"))
    eq("期权2026-06=反稀释表", dil("[期权] 未行权数", "2026-06-30"), dil("[反稀释] 期权", "2026H1"))
    eq("加权股数=利润表", dil("[基本股数] 加权平均股数", "2026H1"), g("IIS", "加权平均股数(千股) Weighted-average shares (thousands)", "2026H1"))
    eq("捐赠匹配2025=利润表补充", dil("[公益] 捐赠匹配费用(2025全年)", "2025"),
       g("IS", "[补充] 非现金慈善捐赠(捐赠匹配计划) Non-cash charitable contributions", "2025"))
    eq("捐赠匹配预留减少=2026Q1发行N类股", dil("[公益] 捐赠匹配计划预留股数", "2025-12-31")
       - dil("[公益] 捐赠匹配计划预留股数", "2026-06-30"), g("IBS", "[附] N类普通股已发行股数(千股) Class N shares outstanding (thousands)", "2026-06-30"))
    eq("反稀释2025 合计", sum(dil(k, "2025") for k in ("[反稀释] 优先股折合普通股", "[反稀释] 可转债折合普通股", "[反稀释] RSA",
                                                       "[反稀释] 期权", "[反稀释] 收购尾款", "[反稀释] 捐赠匹配负债")),
       dil("[反稀释] 合计(不含RSU 621.0M)", "2025"))
    eq("反稀释2025 期权=期末未行权", dil("[反稀释] 期权", "2025"), dil("[期权] 未行权数", "2025-12-31"))
    eq("反稀释2025 捐赠匹配=2026Q1结算发行N类股", dil("[反稀释] 捐赠匹配负债", "2025"),
       g("IBS", "[附] N类普通股已发行股数(千股) Class N shares outstanding (thousands)", "2026-06-30"))
    # 公益基金注入股数 = 2026-06-30 完全稀释股本 × 5%（假设 Amazon 票据全部转股）——反推公司口径的完全稀释股本
    fd = (g("IBS", "[附] A类普通股已发行股数(千股) Class A shares outstanding (thousands)", "2026-06-30")
          + g("IBS", "[附] N类普通股已发行股数(千股) Class N shares outstanding (thousands)", "2026-06-30")
          + dil("[反稀释] 优先股折合普通股", "2026H1") + dil("[反稀释] 可转债折合普通股", "2026H1")
          + dil("[期权] 未行权数", "2026-06-30") + dil("[RSU] 未归属数", "2026-06-30")
          + dil("[公益] 捐赠匹配计划预留股数", "2026-06-30") + dil("[预留] 股权计划可供授予股数", "2026-06-30"))
    eq("公益基金注入股数=完全稀释股本×5%(千股·取整误差1)", round(fd * 0.05),
       round(dil("[公益] 注入 Anthropic Public Benefit Fund 的N类股", "2026-10") / 1000), tol=1)
    # 优先股原始发行价（两位小数）↔ 融资轮次每股价格（四位小数）
    rnd = lambda k: lv("ROUNDS", k, [v[1] for kk, v in T["ROUNDS"]["rows"] if kk == k][0])
    for s, k in (("C-1", "[C轮] 每股价格"), ("D-1", "[D轮] 每股价格"), ("E-1", "[E轮] 每股价格"), ("F-1", "[F轮] 每股价格"),
                 ("G-1", "[G轮] 每股价格"), ("G-2", "[G轮] 每股价格"), ("H-1", "[H轮] 每股价格"), ("H-2", "[H轮] 每股价格")):
        eq(f"{s} 原始发行价=融资轮次价格", g("PREF", f"[{s}] 原始发行价(美元·拆股前优先股口径) OIP", "2026-06-30"), round(rnd(k), 2))
    for s in ("E-2", "F-2", "G-3"):   # Amazon 票据按 $20.9280 转股
        eq(f"{s} 原始发行价=Amazon转股价", g("PREF", f"[{s}] 原始发行价(美元·拆股前优先股口径) OIP", "2026-06-30"), 20.93)
    for s, k in (("E-1", "[E轮] 募资额"), ("F-1", "[F轮] 募资额"), ("G-1", "[G轮] G-1募资额"), ("H-1", "[H轮] H-1募资额")):
        p = rnd({"E-1": "[E轮] 每股价格", "F-1": "[F轮] 每股价格", "G-1": "[G轮] 每股价格", "H-1": "[H轮] 每股价格"}[s])
        eq(f"{s} 募资额=股数×价格", round(g("PREF", f"[{s}] 已发行股数(千股) Shares outstanding", "2026-06-30") * p / 1000, 1), rnd(k), tol=0.2)
        eq(f"{s} 募资额≈账面(净额·差为发行费)", rnd(k), g("PREF", f"[{s}] 账面价值 Net carrying value", "2026-06-30"), tol=20)
    eq("G-2 募资额=股数×价格(约数)", round(g("PREF", "[G-2] 已发行股数(千股) Shares outstanding", "2026-06-30") * rnd("[G轮] 每股价格") / 1000),
       rnd("[G轮] G-2募资额"), tol=50)
    eq("H-2 募资额=股数×价格(约数)", round(g("PREF", "[H-2] 已发行股数(千股) Shares outstanding", "2026-06-30") * rnd("[H轮] 每股价格") / 1000),
       rnd("[H轮] H-2募资额"), tol=50)
    eq("2026-04 要约收购成交额=股数×价格", round(rnd("[老股转让] 2026-04 要约收购成交股数") * 25.9136 / 1e6, 1),
       rnd("[老股转让] 2026-04 要约收购成交额"), tol=0.1)
    eq("2025-06 回购金额=股数×价格", round(rnd("[公司回购] 2025-06 要约回购股数") * 5.61 / 1e6, 1), rnd("[公司回购] 2025-06 要约回购金额"), tol=0.1)
    eq("2025-06 回购股数=权益变动表", round(rnd("[公司回购] 2025-06 要约回购股数") / 1000), -g("EQ", "[A类股] 回购注销(千股) Repurchased", "2025"))
    eq("2025-06 回购:金额-公允价值部分=股权激励溢价", round(rnd("[公司回购] 2025-06 要约回购金额")) + g("CF", "回购普通股 Repurchase of common stock", "2025"),
       g("IS", "[补充] 其中现金回购溢价计入股权激励 SBC from repurchase premium", "2025"), tol=1)
    # 公司口径累计融资 1,411 亿 = 2022 年末优先股账面 + 2023 起优先股/可转债/SAFE 收现（不含期权行权）
    cum = (g("EQ", "[优先股] 期初账面 RCPS beginning", "2023")
           + sum(g("CF", k, c) for c in Y for k in ("发行优先股净额 Proceeds from RCPS, net", "发行可转债收现 Issuance of convertible notes for cash",
                                                    "发行SAFE收现 Issuance of SAFEs for cash"))
           + g("IIS", "[现金流] 发行优先股净额 Proceeds from RCPS, net", "2026H1") + g("IIS", "[现金流] 发行可转债收现 Issuance of convertible notes for cash", "2026H1"))
    eq("公司口径累计融资≈2022末优先股+2023起优先股/可转债/SAFE收现(公司取一位小数)", cum, rnd("[累计] 截至2026-06-30累计融资(公司口径)"), tol=50)
    # 期权滚动（附注 10 table idx 151：授予 / 行权 / 注销三项未入长表，作常数）
    eq("期权滚动 2023→2024", dil("[期权] 未行权数", "2023-12-31") + 1279562 - 24907 - 50702, dil("[期权] 未行权数", "2024-12-31"))
    eq("期权滚动 2024→2025", dil("[期权] 未行权数", "2024-12-31") + 550591 - 141478 - 163150, dil("[期权] 未行权数", "2025-12-31"))
    eq("期权滚动 2025→2026-06", dil("[期权] 未行权数", "2025-12-31") + 90419 - 227942 - 48154, dil("[期权] 未行权数", "2026-06-30"))
    eq("RSU滚动 2025→2026-06", dil("[RSU] 未归属数", "2025-12-31") + 451891 - 23301, dil("[RSU] 未归属数", "2026-06-30"))

    # 或有事项与 Bartz
    oth = lambda k, t: lv("OTHER", k, t)
    eq("Bartz 已付+流动+非流动=和解额", oth("[诉讼] Bartz 2025年已付", "2025") + oth("[诉讼] Bartz 负债-流动", "2025-12-31")
       + oth("[诉讼] Bartz 负债-非流动", "2025-12-31"), oth("[诉讼] Bartz 版权集体诉讼和解金额", "2025Q3计提·2026-07法院批准"))
    eq("Bartz 和解额=利润表", oth("[诉讼] Bartz 版权集体诉讼和解金额", "2025Q3计提·2026-07法院批准"),
       -g("IS", "Bartz和解费用 Bartz settlement", "2025"))
    eq("Bartz 和解额=单季计提(2025Q3)", oth("[诉讼] Bartz 版权集体诉讼和解金额", "2025Q3计提·2026-07法院批准"),
       -g("QIS", "Bartz和解费用 Bartz settlement", "2025Q3"))
    eq("应计法律费用2026-06=资产负债表附注8", oth("[诉讼] 应计法律费用合计", "2026-06-30"),
       g("IBS", "[附注8] 应计法律费用 Accrued legal expenses", "2026-06-30"))
    eq("应计法律费用2025≥Bartz流动负债", min(0, g("BS", "[附注8] 应计法律费用 Accrued legal expenses", "2025")
                                     - oth("[诉讼] Bartz 负债-流动", "2025-12-31")), 0)
    eq("Bartz 2026-06 流动负债≤应计法律费用", min(0, oth("[诉讼] 应计法律费用合计", "2026-06-30")
                                       - oth("[诉讼] Bartz 负债-流动", "2026-06-30")), 0)
    eq("捐赠匹配2025费用=附注8负债", g("IS", "[补充] 非现金慈善捐赠(捐赠匹配计划) Non-cash charitable contributions", "2025"),
       g("BS", "[附注8] 捐赠匹配负债 Donation matching program liability", "2025"))

    # 必填锚科目（防「锚为空 → 勾稽静默全过」）
    for t, k in (("IS", "营业收入 Revenue"), ("IS", "净利润 Net loss"), ("IIS", "营业收入 Revenue"), ("QIS", "营业收入 Revenue"),
                 ("BS", "资产总计 Total assets"), ("IBS", "资产总计 Total assets"), ("CF", "经营活动现金流净额 Net cash from operating"),
                 ("FN", "营业成本(职能口径) Cost of revenue"), ("EQ", "[优先股] 期末账面 RCPS ending"), ("L3", "[可转换票据] 期末 Ending")):
        for c, v in zip(T[t]["cols"], rowv(t, k)):
            if v is None:
                errs.append(f"必填锚科目为空: {t} {k} {c}")
    return errs


# ====================================================================== 派生比率
def r4(x):
    return None if x is None else round(x, 4)


def safe_div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def ratios():
    rows = []
    rev = lambda c: g("IS", "营业收入 Revenue", c)
    for label, fn in (
        ("毛利率(职能口径) Gross margin (functional)", lambda c: 1 + g("FN", "营业成本(职能口径) Cost of revenue", c) / rev(c)),
        ("算力与基础设施/营收 Compute/Revenue", lambda c: -g("IS", "算力与基础设施 Compute and infrastructure", c) / rev(c)),
        ("人员开支/营收 Personnel/Revenue", lambda c: -g("IS", "人员开支 Personnel", c) / rev(c)),
        ("销售营销与合作伙伴/营收 SM&P/Revenue", lambda c: -g("IS", "销售营销与合作伙伴 Sales, marketing, and partnerships", c) / rev(c)),
        ("其他运营与行政/营收 Other opex/Revenue", lambda c: -g("IS", "其他运营与行政 Other operating and administrative", c) / rev(c)),
        ("研发(职能)/营收 R&D/Revenue", lambda c: -g("FN", "研发(职能口径) Research and development", c) / rev(c)),
        ("销售及市场(职能)/营收 S&M/Revenue", lambda c: -g("FN", "销售及市场(职能口径) Sales and marketing", c) / rev(c)),
        ("管理费用(职能)/营收 G&A/Revenue", lambda c: -g("FN", "管理费用(职能口径) General and administrative", c) / rev(c)),
        ("经营利润率 Operating margin", lambda c: g("IS", "经营利润 Operating loss", c) / rev(c)),
        ("[非GAAP·公司口径] 调整后经营利润率 Adjusted operating margin",
         lambda c: g("IS", "[非GAAP·公司口径] 调整后经营利润 Adjusted operating income (loss)", c) / rev(c)),
        ("净利率(GAAP·被公允价值变动主导) Net margin", lambda c: g("IS", "净利润 Net loss", c) / rev(c)),
        ("股权激励/营收 SBC/Revenue", lambda c: g("IS", "[补充] 股权激励费用(利润表口径·含回购溢价) SBC expense", c) / rev(c)),
        ("营收同比 Revenue growth", lambda c: None if c == "2023" else rev(c) / rev(Y[Y.index(c) - 1]) - 1),
        ("算力与基础设施同比 Compute growth", lambda c: None if c == "2023" else
            g("IS", "算力与基础设施 Compute and infrastructure", c) / g("IS", "算力与基础设施 Compute and infrastructure", Y[Y.index(c) - 1]) - 1),
        ("国际收入占比 International share", lambda c: g("REV", "[地区] 国际 International", c) / rev(c)),
        ("订阅收入占比 Subscription share", lambda c: g("REV", "[计费方式] 订阅 Subscription-based", c) / rev(c)),
        ("经营现金流/营收 OCF/Revenue", lambda c: g("CF", "经营活动现金流净额 Net cash from operating", c) / rev(c)),
        ("Capex/营收 Capex/Revenue", lambda c: -g("CF", "购建物业设备(capex) Purchases of property and equipment", c) / rev(c)),
    ):
        rows.append((label, [r4(fn(c)) for c in Y]))
    # 金额型派生
    ocf = rowv("CF", "经营活动现金流净额 Net cash from operating")
    capex = rowv("CF", "购建物业设备(capex) Purchases of property and equipment")
    rows.append(("[金额] 自由现金流 FCF = OCF + capex(百万美元)", [o + c for o, c in zip(ocf, capex)]))
    rows.append(("[金额] 毛利(职能口径·百万美元) Gross profit", [rev(c) + g("FN", "营业成本(职能口径) Cost of revenue", c) for c in Y]))
    rows.append(("[金额] 剔除可转债公允价值变动的税前利润(百万美元) Pre-tax ex-FV change",
                 [g("IS", "除税前利润 Loss before provision for income taxes", c)
                  - g("IS", "可转债等公允价值变动 Change in FV of convertible notes, derivative liabilities, and SAFEs", c) for c in Y]))
    rows.append(("现金含量 OCF/净利润(净利为负·不适用)", [None, None, None]))
    rows.append(("ROE(股东权益为负·不适用)", [None, None, None]))
    # 资产负债表比率（只 2024/2025 年末）
    bs = lambda k, c: None if c == "2023" else g("BS", k, c)
    ta = lambda c: bs("资产总计 Total assets", c)
    for label, k in (("现金及短投/总资产 Cash+STI/Assets", None),
                     ("应收/总资产 AR/Assets", "应收账款净额 Accounts receivable, net"),
                     ("预付及其他(流动+非流动)/总资产 Prepaid+other/Assets", None),
                     ("物业设备/总资产 PP&E/Assets", "物业设备净额 Property and equipment, net"),
                     ("商誉/总资产 Goodwill/Assets", "商誉 Goodwill")):
        vals = []
        for c in Y:
            if c == "2023":
                vals.append(None)
                continue
            if label.startswith("现金"):
                num = bs("货币资金 Cash and cash equivalents", c) + bs("短期投资 Short-term investments", c)
            elif label.startswith("预付"):
                num = bs("预付及其他流动资产 Prepaid expenses and other current assets", c) + bs("其他非流动资产 Other assets, noncurrent", c)
            else:
                num = bs(k, c)
            vals.append(r4(num / ta(c)))
        rows.append((label, vals))
    rows.append(("资产负债率(含可转债公允价值) Liabilities/Assets", [None] + [r4(bs("负债合计 Total liabilities", c) / ta(c)) for c in Y[1:]]))
    rows.append(("资产负债率(剔可转债) Liabilities ex-notes/Assets",
                 [None] + [r4((bs("负债合计 Total liabilities", c) - bs("可转换票据(公允价值) Convertible notes payable", c)) / ta(c)) for c in Y[1:]]))
    rows.append(("期末应收÷全年营收 AR/Revenue", [None] + [r4(bs("应收账款净额 Accounts receivable, net", c) / rev(c)) for c in Y[1:]]))
    rows.append(("期末合同负债÷全年营收 Deferred revenue/Revenue",
                 [None] + [r4(bs("合同负债(递延收入) Deferred revenue", c) / rev(c)) for c in Y[1:]]))
    rows.append(("应收周转天数(期末口径) DSO end-of-period",
                 [None] + [round(bs("应收账款净额 Accounts receivable, net", c) / rev(c) * 365, 1) for c in Y[1:]]))
    rows.append(("应收周转天数(平均口径·仅2025) DSO average", [None, None,
                 round((g("BS", "应收账款净额 Accounts receivable, net", "2024") + g("BS", "应收账款净额 Accounts receivable, net", "2025"))
                       / 2 / rev("2025") * 365, 1)]))
    # 股东回报画像（2023 起·现金流口径）
    fin_in = [g("CF", "发行优先股净额 Proceeds from RCPS, net", c) + g("CF", "发行可转债收现 Issuance of convertible notes for cash", c)
              + g("CF", "发行普通股收现 Proceeds from issuance of common stock", c) + g("CF", "发行SAFE收现 Issuance of SAFEs for cash", c) for c in Y]
    rows.append(("[股东回报] 当年外部融资收现(百万美元) External financing inflow", fin_in))
    acc = []
    s = 0
    for v in fin_in:
        s += v
        acc.append(s)
    rows.append(("[股东回报] 2023起累计外部融资收现(百万美元) Cumulative since 2023", acc))
    rows.append(("[股东回报] 现金分红(百万美元) Dividends", [0, 0, 0]))
    rows.append(("[股东回报] 回购(百万美元) Repurchases", [-g("CF", "回购普通股 Repurchase of common stock", c) for c in Y]))
    return rows


def interim_ratios():
    cols = H + Q
    rows = []

    def col_val(k_iis, k_qis, c):
        return g("IIS", k_iis, c) if c in H else g("QIS", k_qis, c)

    def rev(c):
        return col_val("营业收入 Revenue", "营业收入 Revenue", c)

    for label, ki, kq in (
        ("算力与基础设施/营收 Compute/Revenue", "算力与基础设施 Compute and infrastructure", "算力与基础设施 Compute and infrastructure"),
        ("人员开支/营收 Personnel/Revenue", "人员开支 Personnel", "人员开支 Personnel"),
        ("销售营销与合作伙伴/营收 SM&P/Revenue", "销售营销与合作伙伴 Sales, marketing, and partnerships", "销售营销与合作伙伴 Sales, marketing, and partnerships"),
        ("其他运营与行政/营收 Other opex/Revenue", "其他运营与行政 Other operating and administrative", "其他运营与行政 Other operating and administrative"),
    ):
        rows.append((label, [r4(-col_val(ki, kq, c) / rev(c)) for c in cols]))
    rows.append(("经营利润率 Operating margin", [r4(col_val("经营利润 Operating loss", "经营利润 Operating income (loss)", c) / rev(c)) for c in cols]))
    rows.append(("[非GAAP·公司口径] 调整后经营利润率 Adjusted operating margin",
                 [r4(col_val("[非GAAP·公司口径] 调整后经营利润 Adjusted operating income (loss)",
                             "[非GAAP·公司口径] 调整后经营利润 Adjusted operating income (loss)", c) / rev(c)) for c in cols]))
    rows.append(("股权激励/营收 SBC/Revenue",
                 [r4(col_val("[补充] 股权激励费用(利润表口径·含回购溢价) SBC expense", "[补充] 股权激励费用 SBC expense", c) / rev(c)) for c in cols]))
    rows.append(("毛利率(职能口径·仅半年) Gross margin (functional)",
                 [r4(1 + g("FN", "营业成本(职能口径) Cost of revenue", c) / rev(c)) for c in H] + [None] * len(Q)))
    rows.append(("研发(职能)/营收(仅半年) R&D/Revenue",
                 [r4(-g("FN", "研发(职能口径) Research and development", c) / rev(c)) for c in H] + [None] * len(Q)))
    rows.append(("营收同比(半年) Revenue growth YoY", [None, r4(rev("2026H1") / rev("2025H1") - 1)] + [None] * len(Q)))
    rows.append(("营收同比(单季) Revenue growth YoY", [None, None, None, None, None, None,
                                                r4(rev("2026Q1") / rev("2025Q1") - 1), r4(rev("2026Q2") / rev("2025Q2") - 1)]))
    rows.append(("营收环比(单季) Revenue growth QoQ", [None, None, None] + [r4(rev(Q[i]) / rev(Q[i - 1]) - 1) for i in range(1, len(Q))]))
    rows.append(("算力与基础设施同比(单季) Compute growth YoY", [None] * 6 + [
        r4(g("QIS", "算力与基础设施 Compute and infrastructure", "2026Q1") / g("QIS", "算力与基础设施 Compute and infrastructure", "2025Q1") - 1),
        r4(g("QIS", "算力与基础设施 Compute and infrastructure", "2026Q2") / g("QIS", "算力与基础设施 Compute and infrastructure", "2025Q2") - 1)]))
    ocf = [g("IIS", "[现金流] 经营活动现金流净额 Net cash from operating", c) for c in H]
    capex = [g("IIS", "[现金流] 购建物业设备(capex) Purchases of property and equipment", c) for c in H]
    rows.append(("[金额] 自由现金流 FCF = OCF + capex(百万美元·仅半年)", [o + c for o, c in zip(ocf, capex)] + [None] * len(Q)))
    rows.append(("经营现金流/营收(仅半年) OCF/Revenue", [r4(o / rev(c)) for o, c in zip(ocf, H)] + [None] * len(Q)))
    rows.append(("[金额] 经营现金流中营运资本贡献(百万美元·仅半年) Working capital in OCF",
                 [sum(g("IIS", k, c) for k in ("[现金流] 应收账款变动 Accounts receivable", "[现金流] 预付及其他资产变动 Prepaid expenses and other assets",
                                               "[现金流] 应付应计及其他负债变动 AP, accrued and other liabilities", "[现金流] 租赁负债变动 Lease liabilities",
                                               "[现金流] 合同负债变动 Deferred revenue")) for c in H] + [None] * len(Q)))
    rows.append(("[金额] 剔除可转债与票据购买协议公允价值变动的税前利润(百万美元) Pre-tax ex-FV",
                 [g("IIS", "除税前利润 Loss before provision for income taxes", c)
                  - g("IIS", "可转债等公允价值变动 Change in FV of convertible notes, derivative liabilities, and SAFEs", c)
                  + g("IIS", "[补充] 特定按市值计量金融工具公允价值变动 Change in FV of certain MTM instruments", c) for c in H]
                 + [g("QIS", "除税前利润 Loss before provision for income taxes", c)
                    - g("QIS", "可转债等公允价值变动 Change in FV of convertible notes, derivative liabilities, and SAFEs", c)
                    + g("QIS", "[补充] 特定按市值计量金融工具公允价值变动 Change in FV of certain MTM instruments", c) for c in Q]))
    # 时点比率（期末余额列于当季：2025-12-31 → 2025Q4，2026-06-30 → 2026Q2 / 2026H1）
    ib = lambda k: g("IBS", k, "2026-06-30")
    yb = lambda k: g("IBS", k, "2025-12-31")
    rows.append(("期末应收÷当季收入(时点·列于当季) AR/quarter revenue",
                 [None] * 5 + [r4(yb("应收账款净额 Accounts receivable, net") / rev("2025Q4")), None,
                               r4(ib("应收账款净额 Accounts receivable, net") / rev("2026Q2"))]))
    rows.append(("期末合同负债÷当季收入(时点·列于当季) Deferred revenue/quarter revenue",
                 [None] * 5 + [r4(yb("合同负债(递延收入) Deferred revenue") / rev("2025Q4")), None,
                               r4(ib("合同负债(递延收入) Deferred revenue") / rev("2026Q2"))]))
    rows.append(("[金额] 半年利息收入年化÷期初期末现金及短投均值(仅2026H1) Interest yield annualized",
                 [None, r4(g("IIS", "利息收入 Interest income", "2026H1") * 2
                           / ((yb("货币资金 Cash and cash equivalents") + yb("短期投资 Short-term investments")
                               + ib("货币资金 Cash and cash equivalents") + ib("短期投资 Short-term investments")) / 2))]
                 + [None] * len(Q)))
    rows.append(("期末现金及短投÷总资产(2026-06-30·列于2026H1)",
                 [None, r4((ib("货币资金 Cash and cash equivalents") + ib("短期投资 Short-term investments")) / ib("资产总计 Total assets"))] + [None] * len(Q)))
    rows.append(("资产负债率(剔可转债)(2026-06-30·列于2026H1)",
                 [None, r4((ib("负债合计 Total liabilities") - ib("可转换票据(公允价值) Convertible notes payable")) / ib("资产总计 Total assets"))] + [None] * len(Q)))
    return cols, rows


# ====================================================================== 写出
def write(path, header, cols, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([header])
        w.writerow(["科目"] + cols)
        for name, vals in rows:
            w.writerow([name] + ["" if v is None else v for v in vals])
    print(f"  ✓ {path.name}")


def mutate():
    """逐格 +1（比例行 +0.01），重跑勾稽，统计改了也不报错的格子。"""
    base = copy.deepcopy(T)
    covered, uncovered = 0, []
    for tname, t in base.items():
        for i, (k, vals) in enumerate(t["rows"]):
            for j, v in enumerate(vals):
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    continue
                T[tname]["rows"][i][1][j] = v + (0.01 if isinstance(v, float) and abs(v) < 20 else 1)
                STATS["run"] = 0
                try:
                    errs = checks()
                except Exception:          # 改坏导致取数异常也算「被发现」
                    errs = ["exception"]
                T[tname]["rows"][i][1][j] = v
                if errs:
                    covered += 1
                else:
                    uncovered.append(f"{tname}:{k}@{t['cols'][j]}")
    total = covered + len(uncovered)
    print(f"变异对照：数值格 {total} 个，被勾稽捕获 {covered} 个（{covered / total:.1%}），未被任何勾稽覆盖 {len(uncovered)} 个")
    by_t = {}
    for u in uncovered:
        by_t.setdefault(u.split(":")[0], 0)
        by_t[u.split(":")[0]] += 1
    for k, v in sorted(by_t.items()):
        print(f"  · {k}: 未覆盖 {v}")
    return uncovered


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
    if "--mutate" in sys.argv:
        unc = mutate()
        if "--list" in sys.argv:
            for u in unc:
                print("    -", u)
        return
    for name, t in T.items():
        if t["file"]:
            write(OUT / t["file"], t["header"], t["cols"], t["rows"])
    write(OUT / "财务比率.csv",
          f"# 派生比率(比率=小数·[金额]行=百万美元); 由本目录 利润表/资产负债表/现金流量表/费用按职能/分部营收 派生; 覆盖2023-2025(资产负债表比率仅2024/2025年末); "
          f"⚠️ 净利润被可转债公允价值变动主导、股东权益为负 → 现金含量与 ROE 不适用(留空); 毛利率为职能口径派生(公司利润表无毛利行)",
          Y, ratios())
    cols, rows = interim_ratios()
    write(OUT / "中期比率-2026.csv",
          f"# 派生比率(比率=小数·[金额]行=百万美元); 期间轴: 半年累计(2025H1/2026H1) + 单季(2025Q1-2026Q2)——**跨列比较前先认期间**; "
          f"由 中期财务-2026.csv / 利润表-季度.csv / 费用按职能.csv / 中期资产负债表-2026.csv 派生; 毛利率与现金流只在半年列(单季无职能拆分与现金流量表)",
          cols, rows)


if __name__ == "__main__":
    main()
