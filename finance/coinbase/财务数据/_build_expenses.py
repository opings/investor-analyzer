#!/usr/bin/env python3
"""Coinbase 费用构成 + 中期损益 构建器(转录固化 + 勾稽 + 写 CSV)。

与 `_build_from_filings.py`(年度三表)分工:
  本脚本只管两件事,都是三表 CSV 里**没有**的维度 ——
    ① 费用构成.csv     —— 费用「按性质」拆解(员工/托管/摊销/客服/USDC奖励…) + 股权薪酬按费用行分布
    ② 利润表-中期.csv  —— 季度/半年损益(2026H1 转亏的归因链),年度 CSV 只到 FY2025

真源(全部一手 SEC 申报,`report/coinbase/`):
  10-K FY2025(2025.htm)  Note 17 ASU2024-03 费用按性质(2023/24/25 三列) · Note 16 SBC按费用行 · MD&A 交易费用分项
  10-K FY2024(2024.htm)  MD&A 交易费用分项(2024/2023·新列示) —— 2023 分项取此处
  10-K FY2023(2023.htm)  Note SBC按费用行(2021/22/23) · MD&A 交易费用分项(旧列示·含「矿工费」单列)
  10-K FY2021(2021.htm)  Note SBC按费用行(2019/20/21)
  10-Q 2026Q1 / 2026Q2   中期损益 + Note 17 费用按性质 + Note 16 SBC + 无形摊销按费用行 + Adjusted EBITDA 对账

⚠️ 三处必须写在脸上的口径事实(不写则后人必踩):
  1. **断点 G**(本次新发现,已登记 重述与口径变更.csv):FY2024 10-K 把 2023 的 33,000
     从「其他经营费用净额」静默重分类进「一般及行政」(43,260→10,260 / 1,041,308→1,074,308),
     **公司未给任何说明**。总经营费用 3,270,045 不变 → 「总费用零重述」仍成立,但分项层被改过。
     本表 2023 列用**最新列示**(G&A 1,074,308),故与 利润表.csv 的 as-reported 差 33,000。
  2. **费用按性质拆解仅 2023 起可得**:ASU 2024-03 披露首见于 10-K FY2025(带 2023/2024 比较列)。
     已实证 10-K FY2023 全文无 Employee-related / Website hosting / USDC rewards 任一行
     → 2019-2022 **实证不可得**(非「只探一条路」),留空不构造。
  3. **股权薪酬两口径**:本表用**附注口径**(按费用行分布·含重组内 SBC);
     财务比率.csv 的「SBC/收入」用**现金流量表加回口径**(不含重组内 SBC)。
     2023 差额 84,042 全为重组内 SBC;2019 差额 20,736 申报未解释 → 两口径都保留,勿混用。

中期表另注:2025 各列取自 **2026 年 10-Q 的比较列**,已按 2026Q1 收入列示变更重分类
(自有支付稳定币收入 净收入→其他收入,Q2 23,600 / H1 47,100),与 2025 年当期 10-Q 原披露不同。

勾稽(任一不过 → 不写出 CSV):
  费用构成:四大费用行各自「分项和 = 合计」 · 合计 = 利润表.csv 对应年(2023 G&A 走断点 G 例外)
           · SBC 按费用行和 = SBC 合计(7 年) · USDC奖励/稳定币收入 分母取 分部营收.csv
  中期:各期「分项和 = 合计」 · 收入−总费用 = 经营利润 · 经营利润+线下各项 = 税前 · 税前+税 = 净利
       · **Q1+Q2 = H1 逐行**(2026 与 2025 各 30+ 行) · SBC按行和 = SBC合计 · 无形摊销按行和 = 合计
       · Adjusted EBITDA 由净利+7 项加回复算 = 申报印刷值
"""
import csv
import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(DIR)))

ERRORS = []


def err(msg):
    ERRORS.append(msg)


def close(a, b, tol=1):
    return a is not None and b is not None and abs(a - b) <= tol


# ============================================================
# ① 费用构成(年度轴) —— 费用一律**正数**(本表是成本拆解,与利润表「费用=负」相反)
# ============================================================
YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]


def A(**kw):
    """按年给值;缺年 = 该年申报无此披露(留空)。"""
    return {int(k[1:]): v for k, v in kw.items()}


# --- 费用按性质(ASU 2024-03·10-K FY2025 Note 17·仅 2023-2025) ---
TD_NATURE = [
    ("员工相关 Employee-related", A(y2023=936_881, y2024=1_036_656, y2025=1_052_597)),
    ("网站托管与基础设施 Website hosting and infrastructure",
     A(y2023=192_009, y2024=228_392, y2025=322_125)),
    ("摊销折旧与减值 Amortization, depreciation, and impairment",
     A(y2023=131_611, y2024=122_595, y2025=157_067)),
    ("其他(合同资源/咨询/办公场地) Other", A(y2023=64_040, y2024=80_609, y2025=138_816)),
]
TD_TOTAL = A(y2023=1_324_541, y2024=1_468_252, y2025=1_670_605)

SM_NATURE = [
    ("USDC 奖励 USDC rewards", A(y2023=34_944, y2024=224_255, y2025=441_347)),
    ("营销项目 Marketing programs", A(y2023=134_018, y2024=247_087, y2025=402_555)),
    ("员工相关 Employee-related", A(y2023=143_762, y2024=151_036, y2025=136_229)),
    ("其他(合同资源/差旅/软件/摊销) Other", A(y2023=19_588, y2024=32_066, y2025=78_446)),
]
SM_TOTAL = A(y2023=332_312, y2024=654_444, y2025=1_058_577)

GA_NATURE = [
    ("员工相关 Employee-related", A(y2023=571_083, y2024=606_554, y2025=664_761)),
    ("专业服务 Professional services", A(y2023=182_908, y2024=202_956, y2025=292_599)),
    ("客户支持(不含员工与专业服务) Customer support",
     A(y2023=48_804, y2024=124_940, y2025=224_193)),
    ("其他(税费牌照/合同资源/公共政策/法律和解/差旅) Other",
     A(y2023=271_513, y2024=365_807, y2025=438_089)),
]
# ⚠️ 2023 = 1,074,308 为**最新列示**(断点 G);利润表.csv as-reported 为 1,041,308
GA_TOTAL = A(y2023=1_074_308, y2024=1_300_257, y2025=1_619_642)

# --- 交易费用分项(10-K FY2025/FY2024 MD&A·五分类新列示) ---
TXN_NATURE = [
    ("区块链奖励费 Blockchain rewards fees",
     A(y2023=229_851, y2024=455_946, y2025=427_506)),
    ("交易返佣与佣金 Transaction rebates and commissions",
     A(y2023=6_876, y2024=122_372, y2025=221_471)),
    ("支付处理与账户验证 Payment processing and account verification",
     A(y2023=76_795, y2024=150_897, y2025=194_587)),
    ("交易冲正损失 Transaction reversal losses",
     A(y2023=51_501, y2024=79_639, y2025=132_671)),
    # 2023: 区块链交易费 55,467 + 其他 215(FY2024 10-K 两行,新版并入「其他」)
    ("其他(含区块链交易费/矿工费) Other", A(y2023=55_682, y2024=88_853, y2025=43_995)),
]
TXN_TOTAL = A(y2023=420_705, y2024=897_707, y2025=1_020_230)

# --- 交易费用分项(10-K FY2023 MD&A 旧列示·2021-2023·与上表不可接续) ---
TXN_OLD = [
    ("[旧列示]区块链奖励费", A(y2021=146_769, y2022=202_480, y2023=229_851)),
    ("[旧列示]支付处理与账户验证", A(y2021=341_013, y2022=194_044, y2023=73_816)),
    ("[旧列示]交易冲正损失", A(y2021=233_832, y2022=93_886, y2023=51_501)),
    ("[旧列示]矿工费 Miner fees", A(y2021=542_889, y2022=131_714, y2023=49_789)),
    ("[旧列示]其他", A(y2021=3_421, y2022=7_756, y2023=15_748)),
]
TXN_OLD_TOTAL = A(y2021=1_267_924, y2022=629_880, y2023=420_705)

# --- 股权薪酬按费用行(各年 10-K SBC 附注·全 7 年) ---
SBC_BY_LINE = [
    ("技术与开发内 SBC in Technology and development",
     A(y2019=25_220, y2020=36_869, y2021=571_861, y2022=1_093_983,
       y2023=476_478, y2024=564_726, y2025=498_235)),
    ("销售与营销内 SBC in Sales and marketing",
     A(y2019=970, y2020=1_566, y2021=32_944, y2022=76_153,
       y2023=59_000, y2024=69_460, y2025=57_692)),
    ("一般及行政内 SBC in General and administrative",
     A(y2019=24_699, y2020=34_190, y2021=215_880, y2022=395_687,
       y2023=245_190, y2024=278_652, y2025=283_513)),
    ("重组内 SBC in Restructuring", A(y2019=994, y2023=84_042)),
]
SBC_TOTAL = A(y2019=51_883, y2020=72_625, y2021=820_685, y2022=1_565_823,
              y2023=864_710, y2024=912_838, y2025=839_440)
# 资本化进「软件与设备」的 SBC(不进费用):2021/2022 附注仅给到十万位
SBC_CAP = A(y2021=3_500, y2022=118_000, y2023=53_617, y2024=48_068, y2025=50_380)

# --- 勾稽用外部锚(取自本目录既有 CSV·避免两处各写一份) ---
IS_TOTAL_OPEX = A(y2019=579_518, y2020=868_530, y2021=4_762_874, y2022=5_904_416,
                  y2023=3_270_045, y2024=4_256_868, y2025=5_745_884)
IS_REVENUE = A(y2019=533_735, y2020=1_277_481, y2021=7_839_444, y2022=3_194_208,
               y2023=3_108_383, y2024=6_564_028, y2025=7_181_325)
# 利润表.csv as-reported 的 G&A(用于验证断点 G 差额恰为 33,000)
GA_AS_REPORTED_2023 = 1_041_308
STABLECOIN_REV = A(y2022=245_710, y2023=694_247, y2024=910_464, y2025=1_348_821)
OPERATING_INCOME = A(y2019=-45_783, y2020=408_951, y2021=3_076_570, y2022=-2_710_208,
                     y2023=-161_662, y2024=2_307_160, y2025=1_435_441)
EMPLOYEES = A(y2020=1_249, y2021=3_730, y2022=4_510, y2023=3_416, y2024=3_772, y2025=4_951)
RESTRUCTURING = A(y2019=10_140, y2022=40_703, y2023=142_594)


def build_expense_rows():
    rows = []

    def blk(title, items, total, total_name):
        rows.append((title, {}))
        rows.extend(items)
        rows.append((total_name, total))

    blk("—— 技术与开发·按性质(ASU 2024-03·2023 起可得) ——",
        TD_NATURE, TD_TOTAL, "技术与开发合计 Total technology and development")
    blk("—— 销售与营销·按性质 ——",
        SM_NATURE, SM_TOTAL, "销售与营销合计 Total sales and marketing")
    blk("—— 一般及行政·按性质(⚠️2023 为最新列示·断点 G) ——",
        GA_NATURE, GA_TOTAL, "一般及行政合计 Total general and administrative")
    blk("—— 交易费用·按性质(FY2025/FY2024 五分类列示) ——",
        TXN_NATURE, TXN_TOTAL, "交易费用合计 Total transaction expense")
    blk("—— 交易费用·FY2023 旧列示(与上表不可接续·矿工费当年单列) ——",
        TXN_OLD, TXN_OLD_TOTAL, "[旧列示]交易费用合计")
    blk("—— 股权薪酬 SBC·按费用行(附注口径·含重组内 SBC) ——",
        SBC_BY_LINE, SBC_TOTAL, "股权薪酬合计(附注口径) Total SBC expense")
    rows.append(("其中:资本化进软件与设备的 SBC(不进费用·2021/22 附注仅到十万位)", SBC_CAP))

    # --- 派生 ---
    rows.append(("—— 派生:人的成本有多大 ——", {}))

    def dget(items, name, y):
        for n, v in items:
            if n.startswith(name):
                return v.get(y)
        return None

    emp = {}
    for y in YEARS:
        parts = [dget(TD_NATURE, "员工相关", y), dget(SM_NATURE, "员工相关", y),
                 dget(GA_NATURE, "员工相关", y)]
        if all(p is not None for p in parts):
            emp[y] = sum(parts)
    rows.append(("员工相关成本合计(技开+销营+行政三行内) Employee-related total", emp))

    sbc_in3 = {}
    for y in YEARS:
        parts = [dget(SBC_BY_LINE, "技术与开发内", y), dget(SBC_BY_LINE, "销售与营销内", y),
                 dget(SBC_BY_LINE, "一般及行政内", y)]
        if all(p is not None for p in parts):
            sbc_in3[y] = sum(parts)
    rows.append(("其中:股权薪酬(三费用行内·不含重组) SBC in the three lines", sbc_in3))
    rows.append(("其中:现金员工成本(员工相关−股权薪酬)",
                 {y: emp[y] - sbc_in3[y] for y in emp if y in sbc_in3}))
    rows.append(("重组费用(离职补偿等·亦为人的成本) Restructuring", RESTRUCTURING))

    def pct(name, num, den, nd=1):
        vals = {}
        for y in YEARS:
            a, b = num.get(y), den.get(y)
            if a is not None and b:
                vals[y] = round(a / b * 100, nd)
        rows.append((name, vals))

    pct("员工相关/总经营费用 %", emp, IS_TOTAL_OPEX)
    pct("员工相关/总收入 %", emp, IS_REVENUE)
    pct("股权薪酬占员工相关成本 % SBC / Employee-related", sbc_in3, emp)
    rows.append(("员工数(年末·经营指标.csv) Employees", EMPLOYEES))
    rows.append(("人均员工成本(千美元/人·名义·分母=年末人数·公司不披露平均人数)",
                 {y: round(emp[y] / EMPLOYEES[y], 1)
                  for y in emp if EMPLOYEES.get(y)}))

    rows.append(("—— 派生:稳定币这条腿的返利成本率与净贡献 ——", {}))
    usdc = dict(SM_NATURE[0][1])
    rows.append(("稳定币收入(分部营收.csv) Stablecoin revenue", dict(STABLECOIN_REV)))
    pct("USDC 奖励/稳定币收入 %(给客户返利吃掉稳定币收入的比例)", usdc, STABLECOIN_REV)
    # ⚠️ 「毛贡献」= 稳定币收入 − 付给客户的 USDC 奖励;**未分摊**该腿应负担的合规/托管/技术等成本,
    #    公司不按业务线披露成本 → 只能算到这一层,不可当作该腿的经营利润
    net_leg = {y: STABLECOIN_REV[y] - usdc[y] for y in YEARS
               if y in STABLECOIN_REV and y in usdc}
    rows.append(("稳定币腿毛贡献(稳定币收入 − USDC奖励·未分摊其他成本)", net_leg))
    op = {y: v for y, v in OPERATING_INCOME.items() if v and v > 0}
    pct("稳定币腿毛贡献/经营利润 %(经营利润为负的年份留空)", net_leg, op)

    return rows


def check_expenses():
    def s(items, y):
        vals = [v.get(y) for _, v in items]
        return sum(v for v in vals if v is not None) if any(
            v is not None for v in vals) else None

    for tag, items, total in [
        ("技术与开发", TD_NATURE, TD_TOTAL), ("销售与营销", SM_NATURE, SM_TOTAL),
        ("一般及行政", GA_NATURE, GA_TOTAL), ("交易费用", TXN_NATURE, TXN_TOTAL),
        ("交易费用[旧]", TXN_OLD, TXN_OLD_TOTAL), ("SBC按行", SBC_BY_LINE, SBC_TOTAL),
    ]:
        for y, t in total.items():
            got = s(items, y)
            if not close(got, t):
                err(f"[分项和]{tag}@{y}: 分项和 {got:,} ≠ 合计 {t:,}")

    # 合计 ↔ 利润表.csv(2023 G&A 走断点 G 例外,差额必须恰为 33,000)
    for y in (2023, 2024, 2025):
        got = TXN_TOTAL[y] + TD_TOTAL[y] + SM_TOTAL[y] + GA_TOTAL[y]
        base = IS_TOTAL_OPEX[y]
        if y == 2023:
            # 2023 总费用另含 加密资产减值(-34,675 贷方) / 重组 142,594 / 其他经营 10,260(最新列示)
            expect = base + 34_675 - 142_594 - 10_260
            if not close(got, expect):
                err(f"[四行和]2023: {got:,} ≠ 总费用还原 {expect:,}")
            if GA_TOTAL[2023] - GA_AS_REPORTED_2023 != 33_000:
                err("[断点G]2023 G&A 最新列示 − as-reported ≠ 33,000")
        elif y == 2024:
            expect = base + 71_725 - 7_933      # 加密经营损益为收益(+71,725) / 其他经营 7,933
            if not close(got, expect):
                err(f"[四行和]2024: {got:,} ≠ 总费用还原 {expect:,}")
        else:
            expect = base - 20_704 - 356_126    # 2025 加密经营损失 20,704 / 其他经营 356,126
            if not close(got, expect):
                err(f"[四行和]2025: {got:,} ≠ 总费用还原 {expect:,}")

    # 交易费用两版列示总额必须一致(2023 同时出现在新旧两表)
    if not close(TXN_TOTAL[2023], TXN_OLD_TOTAL[2023]):
        err("[两版列示]2023 交易费用合计新旧不一致")


# ============================================================
# ② 中期损益(季度/半年轴) —— 沿用利润表.csv 符号:费用/流出 = 负数
# ============================================================
PERIODS = ["2025Q1", "2025Q2", "2025H1", "2026Q1", "2026Q2", "2026H1"]


def P(*vals):
    assert len(vals) == len(PERIODS), f"需 {len(PERIODS)} 个值,给了 {len(vals)}"
    return {p: v for p, v in zip(PERIODS, vals) if v is not None}


INTERIM_ROWS = [
    ("净收入 Net revenue",
     P(1_936_821, 1_396_513, 3_333_334, 1_339_348, 1_154_301, 2_493_649)),
    ("其中:交易收入 Transaction revenue",
     P(1_262_208, 764_270, 2_026_478, 755_825, 599_156, 1_354_981)),
    ("其中:订阅与服务收入 Subscription and services",
     P(674_613, 632_243, 1_306_856, 583_523, 555_145, 1_138_668)),
    ("其中:稳定币收入 Stablecoin revenue",
     P(274_037, 308_914, 582_951, 305_435, 292_147, 597_582)),
    ("其他收入 Other revenue",
     P(97_474, 100_695, 198_169, 73_634, 65_767, 139_401)),
    ("总收入 Total revenue",
     P(2_034_295, 1_497_208, 3_531_503, 1_412_982, 1_220_068, 2_633_050)),
    # --- 经营费用(负) ---
    ("交易费用 Transaction expense",
     P(-303_026, -245_261, -548_287, -195_859, -189_790, -385_649)),
    ("技术与开发 Technology and development",
     P(-355_368, -387_322, -742_690, -525_648, -472_848, -998_496)),
    ("销售与营销 Sales and marketing",
     P(-247_283, -236_245, -483_528, -266_726, -239_843, -506_569)),
    ("一般及行政 General and administrative",
     P(-394_346, -353_707, -748_053, -376_094, -356_924, -733_018)),
    ("经营性加密资产损益净额 (Losses) gains on crypto held for operations",
     P(-34_365, 8_702, -25_663, -35_151, -31_719, -66_870)),
    ("重组 Restructuring", P(None, None, None, None, -52_408, -52_408)),
    ("其他经营(费用)收入净额 Other operating (expense) income, net",
     P(5_899, -308_025, -302_126, -34_925, 9_976, -24_949)),
    ("总经营费用 Total operating expenses",
     P(-1_328_489, -1_521_858, -2_850_347, -1_434_403, -1_333_556, -2_767_959)),
    ("经营利润 Operating income (loss)",
     P(705_806, -24_650, 681_156, -21_421, -113_488, -134_909)),
    # --- 经营线以下 ---
    ("利息费用 Interest expense",
     P(-20_511, -20_535, -41_046, -22_569, -22_516, -45_085)),
    ("投资性加密资产损益净额 (Losses) gains on crypto held for investment",
     P(-596_651, 362_053, -234_598, -482_356, -209_499, -691_855)),
    ("其他收入(费用)净额 Other income (expense), net",
     P(-6_188, 1_506_905, 1_500_717, 61_641, -49_908, 11_733)),
    ("税前利润 Income (loss) before income taxes",
     P(82_456, 1_823_773, 1_906_229, -464_705, -395_411, -860_116)),
    ("所得税(费用)收益 (Provision for) benefit from income taxes",
     P(-16_848, -394_873, -411_721, 70_588, 35_943, 106_531)),
    ("净利润 Net income (loss)",
     P(65_608, 1_428_900, 1_494_508, -394_117, -359_468, -753_585)),
    ("每股收益-基本(美元) EPS Basic", P(0.26, 5.60, 5.87, -1.49, -1.36, -2.85)),
    ("每股收益-稀释(美元) EPS Diluted", P(0.24, 5.14, 5.39, -1.49, -1.36, -2.85)),
    ("加权平均股数-基本(千股) WA shares Basic",
     P(253_878, 255_188, 254_537, 264_775, 263_412, 264_128)),
]

# --- 中期·费用按性质(10-Q Note 17 ASU 2024-03·正数) ---
INTERIM_NATURE = [
    ("技开-员工相关 Employee-related",
     P(232_348, 245_571, 477_919, 348_123, 302_527, 650_650)),
    ("技开-网站托管与基础设施", P(67_247, 76_336, 143_583, 90_639, 89_301, 179_940)),
    ("技开-摊销折旧与减值", P(32_012, 34_585, 66_597, 47_913, 47_078, 94_991)),
    ("技开-其他", P(23_761, 30_830, 54_591, 38_973, 33_942, 72_915)),
    ("销营-USDC 奖励 USDC rewards",
     P(100_034, 102_521, 202_555, 113_427, 119_108, 232_535)),
    ("销营-营销项目 Marketing programs",
     P(104_970, 90_022, 194_992, 83_907, 59_690, 143_597)),
    ("销营-员工相关", P(33_456, 32_319, 65_775, 39_378, 29_787, 69_165)),
    ("销营-其他(含 Deribit 无形摊销)", P(8_823, 11_383, 20_206, 30_014, 31_258, 61_272)),
    ("行政-员工相关", P(163_137, 147_752, 310_889, 193_361, 171_876, 365_237)),
    ("行政-专业服务 Professional services",
     P(58_176, 71_010, 129_186, 49_624, 54_934, 104_558)),
    ("行政-客户支持(不含员工与专业服务)", P(70_455, 54_764, 125_219, 33_265, 28_053, 61_317)),
    ("行政-其他", P(102_578, 80_181, 182_759, 99_844, 102_061, 201_906)),
    ("交易-区块链奖励费", P(120_021, 89_157, 209_178, 64_133, 53_102, 117_235)),
    ("交易-交易返佣与佣金", P(59_585, 86_862, 146_447, 29_026, 36_763, 65_789)),
    ("交易-支付处理与账户验证", P(64_645, 41_332, 105_977, 40_175, 42_349, 82_524)),
    ("交易-交易冲正损失", P(46_844, 20_855, 67_699, 33_999, 20_057, 54_056)),
    ("交易-其他(含预测市场交易所费)", P(11_931, 7_055, 18_986, 28_526, 37_519, 66_045)),
]

# --- 中期·SBC 按费用行 / 无形摊销按费用行 / D&A / Adjusted EBITDA ---
INTERIM_SBC = [
    ("SBC-技术与开发内", P(108_092, 117_240, 225_332, 160_641, 152_917, 313_558)),
    ("SBC-销售与营销内", P(14_905, 14_533, 29_438, 14_811, 12_601, 27_412)),
    ("SBC-一般及行政内", P(67_732, 64_387, 132_119, 72_603, 72_823, 145_426)),
]
INTERIM_SBC_TOTAL = P(190_729, 196_160, 386_889, 248_055, 238_341, 486_396)
INTERIM_AMORT = [
    ("无形摊销-技术与开发内", P(1_724, 1_973, 3_697, 15_784, 15_356, 31_140)),
    ("无形摊销-销售与营销内", P(0, 0, 0, 18_019, 17_774, 35_793)),
    ("无形摊销-一般及行政内", P(3_381, 3_317, 6_698, 1_809, 1_714, 3_523)),
]
INTERIM_AMORT_TOTAL = P(5_105, 5_290, 10_395, 35_612, 34_844, 70_456)
INTERIM_DA = P(33_333, 33_901, 67_234, 68_006, 64_403, 132_409)
INTERIM_EBITDA = P(929_868, 512_065, 1_441_933, 303_250, 207_810, 511_060)
# 数据泄露事件(2025-05)净损失/(回收) —— 坐在「其他经营费用净额」内
DATA_THEFT = P(0, 306_654, 306_654, 8_610, -33_854, -25_244)


def build_interim_rows():
    rows = list(INTERIM_ROWS)
    rows.append(("—— 费用按性质(10-Q Note 17·ASU 2024-03·正数) ——", {}))
    rows.extend(INTERIM_NATURE)
    rows.append(("—— 股权薪酬按费用行(10-Q Note 16·正数) ——", {}))
    rows.extend(INTERIM_SBC)
    rows.append(("股权薪酬合计 Total SBC expense", INTERIM_SBC_TOTAL))
    rows.append(("—— 无形资产摊销按费用行(10-Q 商誉与无形附注·正数) ——", {}))
    rows.extend(INTERIM_AMORT)
    rows.append(("无形摊销合计 Total amortization of intangibles", INTERIM_AMORT_TOTAL))
    rows.append(("折旧与摊销合计 D&A(Adjusted EBITDA 对账口径)", INTERIM_DA))
    rows.append(("数据泄露事件净损失/(回收)(在「其他经营费用净额」内)", DATA_THEFT))
    rows.append(("Adjusted EBITDA(非GAAP·⚠️定义被改过·见重述表 E)", INTERIM_EBITDA))

    # --- 派生 ---
    rows.append(("—— 派生:亏在哪 / 费用刚性 ——", {}))
    m = {n: v for n, v in rows if v}

    def g(name, p):
        return m.get(name, {}).get(p)

    emp = {}
    for p in PERIODS:
        parts = [g("技开-员工相关 Employee-related", p), g("销营-员工相关", p),
                 g("行政-员工相关", p)]
        if all(x is not None for x in parts):
            emp[p] = sum(parts)
    rows.append(("员工相关成本合计(三费用行内)", emp))
    rows.append(("其中:股权薪酬(三费用行内)", dict(INTERIM_SBC_TOTAL)))
    rows.append(("其中:现金员工成本",
                 {p: emp[p] - INTERIM_SBC_TOTAL[p] for p in emp}))

    def add(name, fn, nd=1):
        vals = {}
        for p in PERIODS:
            try:
                v = fn(p)
            except (TypeError, ZeroDivisionError, KeyError):
                v = None
            if v is not None:
                vals[p] = round(v, nd)
        rows.append((name, vals))

    rev = lambda p: g("总收入 Total revenue", p)
    opex = lambda p: -g("总经营费用 Total operating expenses", p)
    add("员工相关/总经营费用 %", lambda p: emp[p] / opex(p) * 100)
    add("员工相关/总收入 %", lambda p: emp[p] / rev(p) * 100)
    add("股权薪酬占员工相关成本 %", lambda p: INTERIM_SBC_TOTAL[p] / emp[p] * 100)
    add("USDC 奖励/稳定币收入 %",
        lambda p: g("销营-USDC 奖励 USDC rewards", p)
        / g("其中:稳定币收入 Stablecoin revenue", p) * 100)
    # 稳定币腿毛贡献:未分摊该腿应负担的合规/托管/技术成本(公司不按业务线披露)→ 不是该腿的经营利润
    leg = lambda p: (g("其中:稳定币收入 Stablecoin revenue", p)
                     - g("销营-USDC 奖励 USDC rewards", p))
    add("稳定币腿毛贡献(稳定币收入 − USDC奖励·未分摊其他成本)", leg, nd=0)
    add("剔除稳定币腿毛贡献后的经营利润(亏损)",
        lambda p: g("经营利润 Operating income (loss)", p) - leg(p), nd=0)

    # 剔除数据泄露事件后的「核心经营费用/利润」—— 该事件 2025 计 306,654 费用、2026 转为回收
    #   DATA_THEFT>0 = 净损失(压低经营利润) → 核心费用 = 报告费用 − DT;核心利润 = 报告利润 + DT
    #   (自洽:收入 − 核心费用 = 报告利润 + DT ✓)
    add("核心总经营费用(剔数据泄露事件)", lambda p: opex(p) - DATA_THEFT[p], nd=0)
    add("核心经营利润(剔数据泄露事件)",
        lambda p: g("经营利润 Operating income (loss)", p) + DATA_THEFT[p], nd=0)
    # 净亏归因:各项占净利(亏)的比例,只对亏损期有意义
    add("投资性加密资产损失占净亏 %",
        lambda p: (-g("投资性加密资产损益净额 (Losses) gains on crypto held for investment", p)
                   / -g("净利润 Net income (loss)", p) * 100)
        if g("净利润 Net income (loss)", p) < 0 else None)
    add("经营亏损占净亏 %",
        lambda p: (-g("经营利润 Operating income (loss)", p)
                   / -g("净利润 Net income (loss)", p) * 100)
        if g("净利润 Net income (loss)", p) < 0 else None)
    return rows


def check_interim():
    m = {n: v for n, v in INTERIM_ROWS}

    def g(name, p):
        return m[name].get(p)

    for p in PERIODS:
        # 收入
        if not close(g("净收入 Net revenue", p) + g("其他收入 Other revenue", p),
                     g("总收入 Total revenue", p)):
            err(f"[中期]{p}: 净收入+其他 ≠ 总收入")
        if not close(g("其中:交易收入 Transaction revenue", p)
                     + g("其中:订阅与服务收入 Subscription and services", p),
                     g("净收入 Net revenue", p)):
            err(f"[中期]{p}: 交易+订阅 ≠ 净收入")
        # 经营费用分项和
        parts = ["交易费用 Transaction expense", "技术与开发 Technology and development",
                 "销售与营销 Sales and marketing", "一般及行政 General and administrative",
                 "经营性加密资产损益净额 (Losses) gains on crypto held for operations",
                 "重组 Restructuring",
                 "其他经营(费用)收入净额 Other operating (expense) income, net"]
        tot = sum(m[k].get(p, 0) for k in parts)
        if not close(tot, g("总经营费用 Total operating expenses", p)):
            err(f"[中期]{p}: 经营费用分项和 {tot:,} ≠ 总经营费用 "
                f"{g('总经营费用 Total operating expenses', p):,}")
        # 经营利润 / 税前 / 净利
        if not close(g("总收入 Total revenue", p) + g("总经营费用 Total operating expenses", p),
                     g("经营利润 Operating income (loss)", p)):
            err(f"[中期]{p}: 总收入+总费用 ≠ 经营利润")
        pre = (g("经营利润 Operating income (loss)", p)
               + g("利息费用 Interest expense", p)
               + g("投资性加密资产损益净额 (Losses) gains on crypto held for investment", p)
               + g("其他收入(费用)净额 Other income (expense), net", p))
        if not close(pre, g("税前利润 Income (loss) before income taxes", p)):
            err(f"[中期]{p}: 经营利润+线下各项 {pre:,} ≠ 税前 "
                f"{g('税前利润 Income (loss) before income taxes', p):,}")
        if not close(g("税前利润 Income (loss) before income taxes", p)
                     + g("所得税(费用)收益 (Provision for) benefit from income taxes", p),
                     g("净利润 Net income (loss)", p)):
            err(f"[中期]{p}: 税前+所得税 ≠ 净利")

    # Q1 + Q2 = H1(逐行·两年各一套)
    allrows = (INTERIM_ROWS + INTERIM_NATURE + INTERIM_SBC + INTERIM_AMORT
               + [("SBC合计", INTERIM_SBC_TOTAL), ("无形摊销合计", INTERIM_AMORT_TOTAL),
                  ("D&A", INTERIM_DA), ("AdjEBITDA", INTERIM_EBITDA),
                  ("数据泄露", DATA_THEFT)])
    n_add = 0
    for name, v in allrows:
        if name.startswith(("每股收益", "加权平均股数")):
            continue          # 每股/股数不可加总
        for yr in ("2025", "2026"):
            q1, q2, h1 = v.get(f"{yr}Q1"), v.get(f"{yr}Q2"), v.get(f"{yr}H1")
            if q1 is None and q2 is None:
                continue
            got = (q1 or 0) + (q2 or 0)
            if h1 is None:
                err(f"[Q1+Q2=H1]{yr} {name}: 有季度值但缺 H1")
            elif not close(got, h1):
                err(f"[Q1+Q2=H1]{yr} {name}: {got:,} ≠ H1 {h1:,}")
            else:
                n_add += 1

    # SBC / 无形摊销 分项和 = 合计
    for tag, items, total in [("SBC", INTERIM_SBC, INTERIM_SBC_TOTAL),
                              ("无形摊销", INTERIM_AMORT, INTERIM_AMORT_TOTAL)]:
        for p in PERIODS:
            got = sum(v.get(p, 0) for _, v in items)
            if not close(got, total[p]):
                err(f"[中期分项]{tag}@{p}: {got:,} ≠ {total[p]:,}")

    # 费用按性质 分项和 = 利润表对应费用行
    grp = {"技开-": "技术与开发 Technology and development",
           "销营-": "销售与营销 Sales and marketing",
           "行政-": "一般及行政 General and administrative",
           "交易-": "交易费用 Transaction expense"}
    for pre, line in grp.items():
        for p in PERIODS:
            got = sum(v.get(p, 0) for n, v in INTERIM_NATURE if n.startswith(pre))
            if not close(got, -m[line][p]):
                err(f"[中期按性质]{pre}@{p}: 分项和 {got:,} ≠ {line} {-m[line][p]:,}")

    # Adjusted EBITDA 复算(申报口径:净利 + 8 项加回)
    #   本表符号为「费用=负」,申报表加回项为正 → 除 D&A/SBC/数据泄露(已按申报符号存)外一律取负号
    for p in PERIODS:
        calc = (g("净利润 Net income (loss)", p)
                - g("所得税(费用)收益 (Provision for) benefit from income taxes", p)
                - g("利息费用 Interest expense", p)
                + INTERIM_DA[p]
                + INTERIM_SBC_TOTAL[p]
                + DATA_THEFT[p]
                - g("投资性加密资产损益净额 "
                    "(Losses) gains on crypto held for investment", p)
                - m["重组 Restructuring"].get(p, 0)
                - g("其他收入(费用)净额 Other income (expense), net", p))
        if not close(calc, INTERIM_EBITDA[p], tol=2):
            err(f"[AdjEBITDA]{p}: 复算 {calc:,} ≠ 申报 {INTERIM_EBITDA[p]:,}")

    print(f"    中期 Q1+Q2=H1 通过行数: {n_add}")


# ============================================================
# ③ 中期现金流量表 —— 10-Q 现金流量表为「年初至今累计」,无季度单列 → 轴 = Q1/H1
#    符号 = 申报印刷口径(流出/减项 = 负)
# ============================================================
CFP = ["2025Q1", "2025H1", "2026Q1", "2026H1"]


def C(*vals):
    assert len(vals) == len(CFP), f"需 {len(CFP)} 个值,给了 {len(vals)}"
    return {p: v for p, v in zip(CFP, vals) if v is not None}


# 经营段(None = 该期申报未单列该行,被并入相邻「其他」行)
CF_OP = [
    ("净利润 Net (loss) income", C(65_608, 1_494_508, -394_117, -753_585)),
    ("折旧与摊销 Depreciation and amortization", C(33_333, 67_234, 68_006, 132_409)),
    ("股权薪酬费用 Stock-based compensation expense",
     C(190_729, 386_889, 248_055, 486_396)),
    ("递延所得税 Deferred income taxes", C(-54_540, 399_971, -77_176, -109_875)),
    ("经营性加密资产损失净额 Losses on crypto held for operations",
     C(34_365, 25_663, 35_151, 66_870)),
    ("投资性加密资产损失净额 Losses on crypto held for investment",
     C(596_651, 234_598, 482_356, 691_855)),
    ("投资损益净额(损失正/收益负) Losses (gains) on investments, net",
     C(-3_327, -1_475_448, -46_797, 11_381)),
    ("其他经营活动净额 Other operating activities, net",
     C(80_956, 48_582, 23_480, 55_689)),
    ("营运资本-所得税净额(仅半年报单列) Income taxes, net",
     C(None, -125_633, None, -41_799)),
    ("营运资本-经营性加密资产(仅半年报单列) Crypto assets held for operations",
     C(None, -84_762, None, -24_055)),
    ("营运资本-其他流动及非流动资产", C(-78_696, 45_910, -25_346, -59_171)),
    ("营运资本-其他流动及非流动负债", C(-12_385, 75_260, -130_868, -76_061)),
]
CF_OP_TOTAL = C(852_694, 1_092_772, 182_744, 380_054)

CF_INV = [
    ("发放贷款 Loans originated", C(-1_937_709, -4_596_581, -3_011_186, -5_862_479)),
    ("收回贷款 Proceeds from repayment of loans",
     C(2_013_905, 4_322_454, 2_964_795, 5_665_796)),
    ("购买投资用加密资产 Purchases of crypto held for investment",
     C(-153_337, -464_082, -82_979, -166_597)),
    ("处置投资用加密资产 Dispositions of crypto held for investment",
     C(17_107, 80_781, 18_880, 33_865)),
    ("购买投资 Purchase of investments", C(-27_227, -91_349, -217_490, -251_562)),
    ("处置投资 Dispositions of investments", C(5_140, 5_735, 128_997, 153_555)),
    # ⚠️ 季报把「业务合并」单列、半年报并入本行 → Q1 列已按半年报列示口径合并,以保可加性
    ("其他投资活动净额(含业务合并·Q1 列为合并后) Other investing activities, net",
     C(-43_214, -69_787, -40_081, -73_132)),
]
CF_INV_TOTAL = C(-125_335, -812_829, -239_064, -500_554)

CF_FIN = [
    ("偿还长期债务 Repayment of long-term debt", C(None, None, None, -1_273_013)),
    ("回购普通股 Repurchase of common stock", C(None, None, -1_062_234, -1_243_488)),
    ("客户托管资金负债变动 Customer custodial fund liabilities",
     C(-818_487, -1_140_867, 149_814, -1_026_160)),
    ("收到客户抵押品 Customer collateral received", C(111_994, 109_399, 7_504, 11_371)),
    ("返还客户抵押品 Return of customer collateral",
     C(-105_329, -112_650, -1_337, -3_729)),
    ("员工股权净额结算代缴税款 Taxes paid re: net share settlement",
     C(-100_303, -201_381, -118_925, -224_319)),
    ("短期借款收到 Proceeds from short-term borrowings",
     C(194_893, 278_162, 243_529, 500_918)),
    ("短期借款偿还 Repayments of short-term borrowings",
     C(-208_004, -305_084, -101_932, -345_927)),
    ("其他融资活动净额 Other financing activities, net",
     C(18_323, 60_560, 18_674, 31_120)),
]
CF_FIN_TOTAL = C(-906_913, -1_311_861, -864_907, -3_573_227)

CF_NET = C(-179_554, -1_031_918, -921_227, -3_693_727)
CF_FX = C(1_655, 79_845, -38_171, -47_265)
CF_BEGIN = C(15_683_456, 15_683_456, 16_893_420, 16_893_420)
CF_END = C(15_505_557, 14_731_383, 15_934_022, 13_152_428)
CF_END_PARTS = [
    ("其中-现金及现金等价物 Cash and cash equivalents",
     C(9_969_393, 9_367_889, 10_205_022, 8_614_065)),
    ("其中-受限现金 Restricted cash", C(339_090, 337_786, 294_807, 275_815)),
    ("其中-客户托管现金 Customer custodial cash",
     C(5_197_074, 5_025_708, 5_434_193, 4_262_548)),
]
CF_SUPP = [
    ("补充披露-借入加密资产 Crypto assets borrowed",
     C(465_262, 588_999, 1_229_303, 1_893_298)),
    ("补充披露-归还借入加密资产 Crypto assets borrowed repaid",
     C(440_796, 638_262, 1_250_883, 1_912_389)),
    ("补充披露-收到客户加密资产抵押品", C(779_893, 1_507_022, 1_441_176, 2_653_573)),
    ("补充披露-返还客户加密资产抵押品", C(797_722, 1_354_794, 986_628, 1_394_501)),
    ("备查-业务合并净现金流出(仅季报单列·半年报并入其他投资)",
     C(-16_683, None, -22_085, None)),
]
# 年度库锚:2025 年末现金(含受限及客户托管)= 2026 期初,须逐位相同
ANNUAL_END_CASH_2025 = 16_893_420


def build_cf_rows():
    rows = []
    rows.append(("—— 经营活动 ——", {}))
    rows.extend(CF_OP)
    rows.append(("经营活动现金流净额 Net cash provided by operating activities",
                 CF_OP_TOTAL))
    rows.append(("—— 投资活动 ——", {}))
    rows.extend(CF_INV)
    rows.append(("投资活动现金流净额 Net cash used in investing activities",
                 CF_INV_TOTAL))
    rows.append(("—— 融资活动 ——", {}))
    rows.extend(CF_FIN)
    rows.append(("融资活动现金流净额 Net cash used in financing activities",
                 CF_FIN_TOTAL))
    rows.append(("—— 现金对账 ——", {}))
    rows.append(("现金净变动 Net decrease in cash", CF_NET))
    rows.append(("汇率影响 Effect of exchange rates", CF_FX))
    rows.append(("期初现金(含受限及客户托管) Cash, beginning of period", CF_BEGIN))
    rows.append(("期末现金(含受限及客户托管) Cash, end of period", CF_END))
    rows.extend(CF_END_PARTS)
    rows.append(("—— 补充披露(非现金/大额周转) ——", {}))
    rows.extend(CF_SUPP)

    rows.append(("—— 派生:工资是谁掏的 / 债是加还是减 ——", {}))

    def add(name, fn, nd=1):
        vals = {}
        for p in CFP:
            try:
                v = fn(p)
            except (TypeError, ZeroDivisionError, KeyError):
                v = None
            if v is not None:
                vals[p] = round(v, nd)
        rows.append((name, vals))

    sbc = dict(CF_OP[2][1])
    add("股权薪酬/经营活动现金流 %(>100% 即「若薪酬须付现则经营现金流为负」)",
        lambda p: sbc[p] / CF_OP_TOTAL[p] * 100)
    add("经营活动现金流 − 股权薪酬(假想:薪酬全部付现)",
        lambda p: CF_OP_TOTAL[p] - sbc[p], nd=0)
    st_net = {p: CF_FIN[6][1][p] + CF_FIN[7][1][p] for p in CFP}
    rows.append(("短期借款净额(收到−偿还) Net short-term borrowings", st_net))
    add("有息债务净变动(长期偿还 + 短期净额;负=净还款)",
        lambda p: CF_FIN[0][1].get(p, 0) + st_net[p], nd=0)
    add("还给股东与员工的现金(回购 + 代缴税款)",
        lambda p: CF_FIN[1][1].get(p, 0) + CF_FIN[5][1][p], nd=0)
    return rows


def check_cf():
    for tag, items, total in [("经营", CF_OP, CF_OP_TOTAL), ("投资", CF_INV, CF_INV_TOTAL),
                              ("融资", CF_FIN, CF_FIN_TOTAL)]:
        for p in CFP:
            got = sum(v[p] for _, v in items if p in v)
            if not close(got, total[p]):
                err(f"[中期CF]{tag}段@{p}: 分项和 {got:,} ≠ 段净额 {total[p]:,}")

    for p in CFP:
        if not close(CF_OP_TOTAL[p] + CF_INV_TOTAL[p] + CF_FIN_TOTAL[p], CF_NET[p]):
            err(f"[中期CF]{p}: 三段和 ≠ 现金净变动")
        if not close(CF_BEGIN[p] + CF_NET[p] + CF_FX[p], CF_END[p]):
            err(f"[中期CF]{p}: 期初+净变动+汇率 ≠ 期末")
        parts = sum(v[p] for _, v in CF_END_PARTS)
        if not close(parts, CF_END[p]):
            err(f"[中期CF]{p}: 期末现金三项和 {parts:,} ≠ 期末 {CF_END[p]:,}")

    # 跨表:现金流量表内的净利/SBC/D&A/加密投资损失 = 利润表-中期.csv 对应格
    mi = {n: v for n, v in INTERIM_ROWS}
    pairs = [(CF_OP[0][1], mi["净利润 Net income (loss)"], "净利"),
             (CF_OP[1][1], INTERIM_DA, "折旧与摊销"),
             (CF_OP[2][1], INTERIM_SBC_TOTAL, "股权薪酬")]
    for a, b, tag in pairs:
        for p in CFP:
            if p in a and p in b and not close(a[p], b[p]):
                err(f"[跨表]{tag}@{p}: 现金流量表 {a[p]:,} ≠ 利润表-中期 {b[p]:,}")
    for p in CFP:
        inv = mi["投资性加密资产损益净额 (Losses) gains on crypto held for investment"][p]
        if not close(CF_OP[5][1][p], -inv):
            err(f"[跨表]加密投资损失@{p}: 现金流量表加回 {CF_OP[5][1][p]:,} ≠ 利润表 {-inv:,}")

    # 跨源:2026 期初现金 = 年度库 2025 年末现金,须逐位相同
    for p in ("2026Q1", "2026H1"):
        if CF_BEGIN[p] != ANNUAL_END_CASH_2025:
            err(f"[跨源]{p} 期初现金 {CF_BEGIN[p]:,} ≠ 年度库 2025 年末 "
                f"{ANNUAL_END_CASH_2025:,}")


# ============================================================
# 写出
# ============================================================
def write_csv(path, cols, head_notes, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        for h in head_notes:
            w.writerow([h])
        w.writerow(["科目"] + [str(c) for c in cols])
        for name, vals in rows:
            w.writerow([name] + [("" if c not in vals else vals[c]) for c in cols])
    print(f"    → {os.path.relpath(path, REPO)}")


def main():
    print("Coinbase 费用构成 + 中期损益 + 中期现金流 —— 勾稽校验中…")
    check_expenses()
    check_interim()
    check_cf()
    if ERRORS:
        print(f"\n❌ 勾稽失败 {len(ERRORS)} 项,**不写出 CSV**:")
        for e in ERRORS:
            print("   -", e)
        sys.exit(1)
    print("✅ 全部勾稽通过\n写出 CSV:")

    write_csv(
        os.path.join(DIR, "费用构成.csv"), YEARS,
        ["单位:千美元(USD thousands);**本表费用一律正数**(成本拆解表,与利润表「费用=负」相反);"
         "空=该年申报无此披露",
         "来源:费用按性质=10-K FY2025 Note 17(ASU 2024-03·含 2023/2024 比较列) | "
         "交易费用分项=10-K FY2025/FY2024 MD&A(新列示)与 10-K FY2023 MD&A(旧列示) | "
         "SBC按费用行=10-K FY2025/FY2023/FY2021 的 SBC 附注",
         "⚠️ 断点 G(见 重述与口径变更.csv):2023 一般及行政本表用**最新列示 1,074,308**,"
         "利润表.csv 为 as-reported 1,041,308,差 33,000 系 FY2024 10-K 从「其他经营费用净额」"
         "静默重分类进 G&A(公司未给说明)",
         "⚠️ 费用按性质仅 2023 起可得:ASU 2024-03 披露首见 10-K FY2025;已实证 10-K FY2023 "
         "全文无 Employee-related/Website hosting/USDC rewards 任一行 → 2019-2022 实证不可得,不构造",
         "⚠️ 股权薪酬两口径勿混:本表=附注口径(按费用行·含重组内 SBC);"
         "财务比率.csv 的 SBC/收入=现金流量表加回口径(不含重组内 SBC);2023 差 84,042 即重组内 SBC",
         "⚠️ 交易费用「旧列示」块(2021-2023)与「新列示」块不可接续:2023 同年两版总额相同(420,705)"
         "但分项口径不同(矿工费 49,789 与其他 15,748 在新版重组为 区块链交易费/返佣/其他)"],
        build_expense_rows())

    write_csv(
        os.path.join(DIR, "利润表-中期.csv"), PERIODS,
        ["单位:千美元(USD thousands);损益行沿用利润表.csv 符号(费用/流出=负);"
         "「按性质/SBC/无形摊销」块为正数;空=该期无此科目",
         "来源:10-Q 2026Q1(acc 0001679788-26-000054)· 10-Q 2026Q2(acc 0001679788-26-000088);"
         "落档 report/coinbase/_中期报告/",
         "⚠️ 2025 各列取自**2026 年 10-Q 的比较列**,已按 2026Q1 收入列示变更重分类"
         "(自有支付稳定币收入 净收入→其他收入:Q1 23,500 / Q2 23,600 / H1 47,100),"
         "与 2025 年当期 10-Q 原披露**不同**;亦已含断点 C(稳定币改记现金等价物)追溯影响",
         "⚠️ 本表只有 2026H1 及其同期;2025Q3 10-Q 已落档但未转录(⏳),故**不构成完整季度序列**,"
         "不可用于判断「Q4 收入是否异常集中」",
         "⚠️ Adjusted EBITDA 为公司自定义非 GAAP 且定义被改过(见 重述与口径变更.csv 断点 E);"
         "2026Q2 起公司已停披露 Trading Volume 关键指标",
         "读法:净亏损的主因看「投资性加密资产损失占净亏 %」(公允价值重估·不耗现金);"
         "费用刚性看「核心经营费用(剔数据泄露事件)」同比 —— 不剔该事件会把 2026 费用误读成同比下降"],
        build_interim_rows())

    write_csv(
        os.path.join(DIR, "现金流量表-中期.csv"), CFP,
        ["单位:千美元(USD thousands);符号=申报印刷口径(流出/减项=负);"
         "空=该期申报未单列该行(被并入相邻「其他」行)",
         "来源:10-Q 2026Q1 / 2026Q2。**10-Q 现金流量表为「年初至今累计」,无季度单列** → "
         "轴只有 Q1 与 H1,Q2 单季现金流公司未披露(不倒算)",
         "⚠️ 2025 各列取自 2026 年 10-Q 的比较列,**已被断点 C(支付稳定币改记现金等价物)大幅重述**:"
         "H1 2025 经营现金流原披露 145,747 → 重述后 1,092,772(+947,025·7.5 倍);"
         "发放贷款 -955,488 → -4,596,581;收回贷款 588,004 → 4,322,454。"
         "**任何引用 2025 年当期 10-Q 原披露经营现金流的分析都会得出相反量级**",
         "⚠️ 另叠加断点 H(2026Q1 起·追溯):客户抵押品收/返由**总额改净额**列示,"
         "H1 2025 两行各调 ±312,510(融资段净额不受影响)",
         "⚠️ 季报与半年报的行粒度不同:①季报单列「业务合并」、半年报并入「其他投资活动净额」"
         "(本表 Q1 列已按半年报口径合并以保可加性,原单列值见「备查-业务合并」行);"
         "②「所得税净额」「经营性加密资产」两个营运资本行仅半年报单列 → **不可用 Q1 逐行倒算 Q2**",
         "⚠️ 期初现金印刷差异:2025 期初本表 15,683,456(10-Q)vs 年度库 15,683,455(10-K FY2025),"
         "差 1 千美元,两份一手申报本身不一致,未作调整",
         "读法:回答「是否借钱发工资」看三行 —— 经营活动现金流净额(正=经营自给)、"
         "有息债务净变动(负=净还款)、股权薪酬/经营活动现金流 %(>100% = 靠发股票才使现金流为正)"],
        build_cf_rows())
    print("\n完成。")


if __name__ == "__main__":
    main()
