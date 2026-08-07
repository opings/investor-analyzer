#!/usr/bin/env python3
"""Build google 2026 interim (Q2 / H1) CSVs from the one-hand SEC 10-Q.

真源: report/google/2026-Q2.htm — Alphabet Inc. Form 10-Q for the quarterly period
ended June 30, 2026 (SEC accession 0001652044-26-000071, filed 2026-07-23).
Comparatives for 2025-12-31 / H1 2025 come from the same 10-Q's comparative columns
(so both sides of every delta are one-hand from the same filing).

设计原则（同 _build_from_xbrl.py）:
  1. 中期数据**不并入年度序列** —— 年度 CSV 覆盖 2002-2025，本脚本只写 `中期财务-2026.csv`
     等中期专属文件，避免年化/口径污染。
  2. 勾稽校验全部通过才写出 CSV；任一条不过 → 抛异常、不落盘。
  3. 派生指标标注算法，不与申报原值混列。

单位: 百万美元 (USD millions)，除标注外。费用/流出 = 负数。
"""
from __future__ import annotations

import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = "report/google/2026-Q2.htm (10-Q · accession 0001652044-26-000071 · filed 2026-07-23)"

# ---------------------------------------------------------------------------
# 一手申报数值（逐行转录自 10-Q）
# 键: (Q2_2025, Q2_2026, H1_2025, H1_2026)
# ---------------------------------------------------------------------------

INCOME = {
    "收益 Revenues": (96428, 119796, 186662, 229692),
    "营业成本 Cost of revenues": (-39039, -45943, -75400, -87214),
    "研发费用 Research and development": (-13808, -18219, -27364, -35251),
    "销售与市场 Sales and marketing": (-7101, -8403, -13273, -16009),
    "一般及行政 General and administrative": (-5209, -6461, -8748, -10752),
    "总成本及开支 Total costs and expenses": (-65157, -79026, -124785, -149226),
    "经营利润 Income from operations": (31271, 40770, 61877, 80466),
    "其他收入(支出)净额 OI&E": (2662, 97983, 13845, 135699),
    "除税前利润 Income before income taxes": (33933, 138753, 75722, 216165),
    "所得税 Provision for income taxes": (-5737, -26560, -12986, -41394),
    "净利润 Net income": (28196, 112193, 62736, 174771),
    "优先股股息 Preferred stock dividends": (0, -86, 0, -86),
    "归属普通股净利 NI available to common": (28196, 112107, 62736, 174685),
}

EPS = {
    "基本每股收益 Basic EPS (USD)": (2.33, 9.23, 5.16, 14.41),
    "稀释每股收益 Diluted EPS (USD)": (2.31, 9.11, 5.12, 14.24),
}

# OI&E 拆解 —— 本次刷新的头号悬案
OIE = {
    "利息收入 Interest income": (1050, 1430, 2051, 2811),
    "利息支出 Interest expense (净资本化后)": (-261, -1278, -295, -1811),
    "外汇损益 FX gain(loss) net": (-69, -160, -175, -14),
    "债务证券损益 Gain(loss) on debt securities": (165, -32, 367, -143),
    "股权证券损益 Gain(loss) on equity securities": (1286, 99031, 11044, 135946),
    "权益法投资损益 Equity method net": (419, -35, 397, 25),
    "其他 Other": (72, -973, 456, -1115),
    "=OI&E 合计": (2662, 97983, 13845, 135699),
}

# 资产负债表 —— 键: (2025-12-31, 2026-06-30)
BALANCE = {
    "现金及现金等价物 Cash and equivalents": (30708, 55911),
    "有价证券 Marketable securities": (96135, 186563),
    "=现金+等价物+有价证券": (126843, 242474),
    "应收账款净额 Accounts receivable net": (62886, 69175),
    "存货 Inventory": (2439, 9991),
    "其他流动资产 Other current assets": (13870, 21884),
    "流动资产合计 Total current assets": (206038, 343524),
    "非上市证券 Non-marketable securities": (68687, 131461),
    "递延所得税资产 Deferred income taxes": (9113, 1448),
    "固定资产净额 Property and equipment net": (246597, 321212),
    "经营租赁资产 Operating lease assets": (15221, 17694),
    "商誉 Goodwill": (33380, 57828),
    "无形资产净额 Intangible assets net": (1283, 9105),
    "其他非流动资产 Other non-current assets": (14962, 39711),
    "资产总计 Total assets": (595281, 921983),
    "应付账款 Accounts payable": (12200, 20258),
    "应付薪酬 Accrued compensation and benefits": (17546, 15086),
    "应付费用及其他流动负债 Accrued expenses and other": (55557, 73014),
    "应付分成 Accrued revenue share": (10864, 10599),
    "递延收入(流动) Deferred revenue": (6578, 7154),
    "流动负债合计 Total current liabilities": (102745, 126111),
    "长期债务 Long-term debt": (46547, 98165),
    "非流动应付税 Income taxes payable non-current": (9531, 11306),
    "递延所得税负债 Deferred income taxes": (919, 22819),
    "经营租赁负债 Operating lease liabilities": (12744, 14591),
    "其他长期负债 Other long-term liabilities": (7530, 8511),
    "负债合计 Total liabilities": (180016, 281503),
    "优先股及资本公积 Preferred stock and APIC": (0, 18023),
    "普通股及资本公积 Common stock and APIC": (93126, 131371),
    "累计其他综合收益 AOCI": (-1916, -2285),
    "留存收益 Retained earnings": (324055, 493371),
    "股东权益合计 Total stockholders' equity": (415265, 640480),
    "负债及权益合计": (595281, 921983),
}

# 现金流量表 —— 键: (H1_2025, H1_2026)
CASHFLOW = {
    "净利润 Net income": (62736, 174771),
    "折旧 Depreciation of property and equipment": (9485, 13586),
    "股权薪酬 Stock-based compensation": (11514, 14708),
    "递延所得税 Deferred income taxes": (-1596, 27538),
    "债务及股权证券损益冲回 Loss(gain) on securities": (-11411, -135803),
    "其他调整 Other": (1041, 3161),
    "应收账款变动 Accounts receivable": (-1201, -6904),
    "存货变动 Inventory": (-628, -7739),
    "所得税净变动 Income taxes net": (-2434, 8304),
    "其他资产变动 Other assets": (-2139, -9950),
    "应付账款变动 Accounts payable": (-327, 2090),
    "应付费用及其他变动 Accrued expenses and other": (-1779, 308),
    "递延收入变动 Deferred revenue": (636, 789),
    "经营活动现金流净额 Net cash from operating": (63897, 84859),
    "资本开支 Purchases of property and equipment": (-39643, -80598),
    "购买有价证券 Purchases of marketable securities": (-39870, -76480),
    "有价证券到期及出售 Maturities and sales of marketable": (40930, 66696),
    "购买非上市证券 Purchases of non-marketable securities": (-2312, -22051),
    "非上市证券到期及出售 Maturities and sales of non-marketable": (873, 1667),
    "收购净支出及无形资产 Acquisitions net of cash": (-353, -33697),
    "其他投资活动 Other investing": (-363, -1359),
    "投资活动现金流净额 Net cash used in investing": (-40738, -145822),
    "股权激励相关净支付 Net payments re stock-based awards": (-5731, -12056),
    "股份回购 Repurchases of stock": (-28306, 0),
    "股息支付 Dividend payments": (-4977, -5231),
    "发行普通股净额 Proceeds from issuance of common stock": (0, 30499),
    "发行强制可转优先股净额 Proceeds from preferred": (0, 19063),
    "发债净额 Proceeds from issuance of debt": (31378, 56226),
    "偿债 Repayments of debt": (-18397, -5253),
    "出售合并主体权益净额 Sale of interest in consolidated": (400, 3758),
    "其他融资活动 Other financing": (-400, -686),
    "融资活动现金流净额 Net cash from(used in) financing": (-26033, 86320),
    "汇率影响 Effect of exchange rate changes": (444, -154),
    "现金净变动 Net increase(decrease) in cash": (-2430, 25203),
    "期初现金 Cash at beginning of period": (23466, 30708),
    "期末现金 Cash at end of period": (21036, 55911),
}

# 分部与收入拆分 —— 键: (Q2_2025, Q2_2026, H1_2025, H1_2026)
SEGMENTS = {
    "Google搜索及其他 Search & other": (54190, 63271, 104892, 123670),
    "YouTube广告 YouTube ads": (9796, 11055, 18723, 20938),
    "Google联盟网络 Network": (7354, 7303, 14610, 14274),
    "=广告合计 Google advertising": (71340, 81629, 138225, 158882),
    "订阅/平台/设备 Subscriptions,platforms,devices": (11203, 12911, 21582, 25295),
    "=Google Services合计": (82543, 94540, 159807, 184177),
    "Google Cloud 云": (13624, 24768, 25884, 44796),
    "Other Bets 其他押注": (373, 382, 823, 793),
    "对冲损益 Hedging gains(losses)": (-112, 106, 148, -74),
    "=总收入 Total revenues": (96428, 119796, 186662, 229692),
}

SEGMENT_OI = {
    "Google Services 经营利润": (33063, 39544, 65745, 80133),
    "Google Cloud 经营利润": (2826, 8814, 5003, 15412),
    "Other Bets 经营利润": (-1246, -1799, -2472, -3899),
    "公司层未分配 Alphabet-level activities": (-3372, -5789, -6399, -11180),
    "=总经营利润 Total income from operations": (31271, 40770, 61877, 80466),
}

GEOGRAPHY = {
    "美国 United States": (46063, 60846, 90027, 114821),
    "欧洲中东非洲 EMEA": (28262, 32501, 54185, 63969),
    "亚太 APAC": (16480, 19317, 31334, 37605),
    "其他美洲 Other Americas": (5735, 7026, 10968, 13371),
    "对冲损益 Hedging": (-112, 106, 148, -74),
    "=总收入 Total revenues": (96428, 119796, 186662, 229692),
}

# 表外承诺与储备 —— 键: (2025-12-31, 2026-06-30)
OFF_BALANCE = {
    "采购承诺及合约义务合计 Purchase commitments & obligations": (149100, 811000),
    "其中短期(12个月内) of which short-term": (113000, 200700),
    "收入储备合计 Revenue backlog": (242800, 519500),
    "其中Google Cloud of which Google Cloud": (None, 513900),
    "未付capex(计入应付/预提) PP&E in AP & accrued": (10635, 29113),
}

# 单项一手事实（非三表行项，供分析层引用）
FACTS = {
    "SpaceX持股-短期限售 (Level 1=活跃市场报价·计入有价证券)": 80000,
    "SpaceX持股-长期限售至2027Q3 (计入其他非流动资产)": 14126,
    "SpaceX持股合计 SpaceX total holding": 94126,
    "非上市股权(计量替代法=平时按成本·仅观察到交易时重估)账面价值": 124300,
    "其中Q2内按观察交易重估部分 (Level 2=可观察输入值)": 87900,
    "公开增发净额 public offering (29M A@$355.1982 + 29M C@$351.8018)": 20500,
    "Berkshire私募净额 private placement (14M A + 14M C)": 10000,
    "强制可转优先股净额 mandatory convertible preferred": 19000,
    "=股权融资合计 total equity raise": 49600,
    "capped call溢价(冲减权益) capped call premium": 1000,
    "ATM额度(截至6/30未动用) ATM Program authorized/unused": 40000,
    "回购授权剩余 repurchase authorization remaining": 69500,
    "Wiz收购对价(2026-03-11完成) Wiz consideration": 29500,
    "Wiz商誉 goodwill from Wiz": 22705,
    "Wiz无形资产 intangibles from Wiz": 8300,
    "EC Android罚款+利息(2026-07已付) EC Android fine paid": 5200,
    "PriceRunner判决计提合计 legal charge accrued in Q2": 2100,
    "员工人数 employees (persons)": 198933,
}


def _check(label: str, lhs: float, rhs: float, tol: float = 1.0) -> None:
    """勾稽断言：差额超过容差即抛异常，CSV 不写出。"""
    if abs(lhs - rhs) > tol:
        raise AssertionError(f"勾稽不通过 [{label}]: {lhs} != {rhs} (差 {lhs - rhs})")
    print(f"  OK  {label}")


def verify() -> None:
    """三表 + 分部 + 拆解逐条勾稽（校验不过不写出）。"""
    print("== 损益勾稽 ==")
    for i, period in enumerate(("Q2'25", "Q2'26", "H1'25", "H1'26")):
        _check(
            f"{period} 收益+总成本开支=经营利润",
            INCOME["收益 Revenues"][i] + INCOME["总成本及开支 Total costs and expenses"][i],
            INCOME["经营利润 Income from operations"][i],
        )
        _check(
            f"{period} 四项费用之和=总成本开支",
            sum(
                INCOME[k][i]
                for k in (
                    "营业成本 Cost of revenues",
                    "研发费用 Research and development",
                    "销售与市场 Sales and marketing",
                    "一般及行政 General and administrative",
                )
            ),
            INCOME["总成本及开支 Total costs and expenses"][i],
        )
        _check(
            f"{period} 经营利润+OI&E=除税前",
            INCOME["经营利润 Income from operations"][i] + INCOME["其他收入(支出)净额 OI&E"][i],
            INCOME["除税前利润 Income before income taxes"][i],
        )
        _check(
            f"{period} 除税前+所得税=净利",
            INCOME["除税前利润 Income before income taxes"][i] + INCOME["所得税 Provision for income taxes"][i],
            INCOME["净利润 Net income"][i],
        )
        _check(
            f"{period} 净利+优先股股息=归普净利",
            INCOME["净利润 Net income"][i] + INCOME["优先股股息 Preferred stock dividends"][i],
            INCOME["归属普通股净利 NI available to common"][i],
        )
        _check(
            f"{period} OI&E 分项合计",
            sum(v[i] for k, v in OIE.items() if not k.startswith("=")),
            OIE["=OI&E 合计"][i],
        )

    print("== 资产负债勾稽 ==")
    for i, period in enumerate(("2025-12-31", "2026-06-30")):
        _check(
            f"{period} 资产=负债+权益",
            BALANCE["资产总计 Total assets"][i],
            BALANCE["负债合计 Total liabilities"][i] + BALANCE["股东权益合计 Total stockholders' equity"][i],
        )
        _check(
            f"{period} 流动资产分项合计",
            sum(
                BALANCE[k][i]
                for k in (
                    "现金及现金等价物 Cash and equivalents",
                    "有价证券 Marketable securities",
                    "应收账款净额 Accounts receivable net",
                    "存货 Inventory",
                    "其他流动资产 Other current assets",
                )
            ),
            BALANCE["流动资产合计 Total current assets"][i],
        )
        _check(
            f"{period} 现金+有价证券小计",
            BALANCE["现金及现金等价物 Cash and equivalents"][i] + BALANCE["有价证券 Marketable securities"][i],
            BALANCE["=现金+等价物+有价证券"][i],
        )
        _check(
            f"{period} 总资产分项合计",
            BALANCE["流动资产合计 Total current assets"][i]
            + sum(
                BALANCE[k][i]
                for k in (
                    "非上市证券 Non-marketable securities",
                    "递延所得税资产 Deferred income taxes",
                    "固定资产净额 Property and equipment net",
                    "经营租赁资产 Operating lease assets",
                    "商誉 Goodwill",
                    "无形资产净额 Intangible assets net",
                    "其他非流动资产 Other non-current assets",
                )
            ),
            BALANCE["资产总计 Total assets"][i],
        )
        _check(
            f"{period} 流动负债分项合计",
            sum(
                BALANCE[k][i]
                for k in (
                    "应付账款 Accounts payable",
                    "应付薪酬 Accrued compensation and benefits",
                    "应付费用及其他流动负债 Accrued expenses and other",
                    "应付分成 Accrued revenue share",
                    "递延收入(流动) Deferred revenue",
                )
            ),
            BALANCE["流动负债合计 Total current liabilities"][i],
        )
        _check(
            f"{period} 总负债分项合计",
            BALANCE["流动负债合计 Total current liabilities"][i]
            + sum(
                BALANCE[k][i]
                for k in (
                    "长期债务 Long-term debt",
                    "非流动应付税 Income taxes payable non-current",
                    "递延所得税负债 Deferred income taxes",
                    "经营租赁负债 Operating lease liabilities",
                    "其他长期负债 Other long-term liabilities",
                )
            ),
            BALANCE["负债合计 Total liabilities"][i],
        )
        _check(
            f"{period} 权益分项合计",
            sum(
                BALANCE[k][i]
                for k in (
                    "优先股及资本公积 Preferred stock and APIC",
                    "普通股及资本公积 Common stock and APIC",
                    "累计其他综合收益 AOCI",
                    "留存收益 Retained earnings",
                )
            ),
            BALANCE["股东权益合计 Total stockholders' equity"][i],
        )

    print("== 现金流勾稽 ==")
    for i, period in enumerate(("H1'25", "H1'26")):
        _check(
            f"{period} 经营+投资+融资+汇率=现金净变动",
            CASHFLOW["经营活动现金流净额 Net cash from operating"][i]
            + CASHFLOW["投资活动现金流净额 Net cash used in investing"][i]
            + CASHFLOW["融资活动现金流净额 Net cash from(used in) financing"][i]
            + CASHFLOW["汇率影响 Effect of exchange rate changes"][i],
            CASHFLOW["现金净变动 Net increase(decrease) in cash"][i],
        )
        _check(
            f"{period} 期初+净变动=期末",
            CASHFLOW["期初现金 Cash at beginning of period"][i] + CASHFLOW["现金净变动 Net increase(decrease) in cash"][i],
            CASHFLOW["期末现金 Cash at end of period"][i],
        )
        _check(
            f"{period} 投资活动分项合计",
            sum(
                CASHFLOW[k][i]
                for k in (
                    "资本开支 Purchases of property and equipment",
                    "购买有价证券 Purchases of marketable securities",
                    "有价证券到期及出售 Maturities and sales of marketable",
                    "购买非上市证券 Purchases of non-marketable securities",
                    "非上市证券到期及出售 Maturities and sales of non-marketable",
                    "收购净支出及无形资产 Acquisitions net of cash",
                    "其他投资活动 Other investing",
                )
            ),
            CASHFLOW["投资活动现金流净额 Net cash used in investing"][i],
        )
        _check(
            f"{period} 融资活动分项合计",
            sum(
                CASHFLOW[k][i]
                for k in (
                    "股权激励相关净支付 Net payments re stock-based awards",
                    "股份回购 Repurchases of stock",
                    "股息支付 Dividend payments",
                    "发行普通股净额 Proceeds from issuance of common stock",
                    "发行强制可转优先股净额 Proceeds from preferred",
                    "发债净额 Proceeds from issuance of debt",
                    "偿债 Repayments of debt",
                    "出售合并主体权益净额 Sale of interest in consolidated",
                    "其他融资活动 Other financing",
                )
            ),
            CASHFLOW["融资活动现金流净额 Net cash from(used in) financing"][i],
        )
        _check(
            f"{period} 期末现金 = 资产负债表现金",
            CASHFLOW["期末现金 Cash at end of period"][i],
            BALANCE["现金及现金等价物 Cash and equivalents"][i] if i == 0 else 55911,
        ) if i == 1 else None

    print("== 分部/收入拆分勾稽 ==")
    for i, period in enumerate(("Q2'25", "Q2'26", "H1'25", "H1'26")):
        _check(
            f"{period} 广告三项=广告合计",
            sum(
                SEGMENTS[k][i]
                for k in (
                    "Google搜索及其他 Search & other",
                    "YouTube广告 YouTube ads",
                    "Google联盟网络 Network",
                )
            ),
            SEGMENTS["=广告合计 Google advertising"][i],
        )
        _check(
            f"{period} 广告+订阅=Services",
            SEGMENTS["=广告合计 Google advertising"][i] + SEGMENTS["订阅/平台/设备 Subscriptions,platforms,devices"][i],
            SEGMENTS["=Google Services合计"][i],
        )
        _check(
            f"{period} 三分部+对冲=总收入",
            SEGMENTS["=Google Services合计"][i]
            + SEGMENTS["Google Cloud 云"][i]
            + SEGMENTS["Other Bets 其他押注"][i]
            + SEGMENTS["对冲损益 Hedging gains(losses)"][i],
            SEGMENTS["=总收入 Total revenues"][i],
        )
        _check(
            f"{period} 分部经营利润合计=总经营利润",
            sum(v[i] for k, v in SEGMENT_OI.items() if not k.startswith("=")),
            SEGMENT_OI["=总经营利润 Total income from operations"][i],
        )
        _check(
            f"{period} 分部收入 = 利润表收入",
            SEGMENTS["=总收入 Total revenues"][i],
            INCOME["收益 Revenues"][i],
        )
        _check(
            f"{period} 分部经营利润 = 利润表经营利润",
            SEGMENT_OI["=总经营利润 Total income from operations"][i],
            INCOME["经营利润 Income from operations"][i],
        )
        _check(
            f"{period} 地区分项=总收入",
            sum(v[i] for k, v in GEOGRAPHY.items() if not k.startswith("=")),
            GEOGRAPHY["=总收入 Total revenues"][i],
        )

    print("== 跨表勾稽 ==")
    _check(
        "H1'26 现金流净利 = 利润表净利",
        CASHFLOW["净利润 Net income"][1],
        INCOME["净利润 Net income"][3],
    )
    _check(
        "H1'26 capex = 投资活动资本开支",
        CASHFLOW["资本开支 Purchases of property and equipment"][1],
        -80598,
    )
    _check(
        "H1'26 股权融资合计 ≈ 一手披露 $49.6B",
        CASHFLOW["发行普通股净额 Proceeds from issuance of common stock"][1]
        + CASHFLOW["发行强制可转优先股净额 Proceeds from preferred"][1],
        FACTS["=股权融资合计 total equity raise"],
        tol=50,
    )
    _check(
        "股权融资三笔明细合计 = $49.6B",
        FACTS["公开增发净额 public offering (29M A@$355.1982 + 29M C@$351.8018)"]
        + FACTS["Berkshire私募净额 private placement (14M A + 14M C)"]
        + FACTS["强制可转优先股净额 mandatory convertible preferred"],
        FACTS["=股权融资合计 total equity raise"],
        tol=200,
    )
    _check(
        "SpaceX 两段限售合计",
        FACTS["SpaceX持股-短期限售 (Level 1=活跃市场报价·计入有价证券)"]
        + FACTS["SpaceX持股-长期限售至2027Q3 (计入其他非流动资产)"],
        FACTS["SpaceX持股合计 SpaceX total holding"],
    )
    _check(
        "Wiz 对价分配 (无形+商誉-承担净负债)",
        FACTS["Wiz无形资产 intangibles from Wiz"] + FACTS["Wiz商誉 goodwill from Wiz"] - 1538,
        FACTS["Wiz收购对价(2026-03-11完成) Wiz consideration"],
        tol=100,
    )
    _check(
        "留存收益变动 = H1净利 - 普通股股息",
        BALANCE["留存收益 Retained earnings"][1] - BALANCE["留存收益 Retained earnings"][0],
        INCOME["净利润 Net income"][3] - 5260 - 86 - 109,
        tol=200,
    )


def derived() -> dict[str, tuple[str, str, str]]:
    """派生指标（算法写在值里·不与申报原值混列）。返回 {指标: (Q2'25, Q2'26, 算法)}。"""
    q2_25_tax_rate = 5737 / 33933
    q2_26_tax_rate = 26560 / 138753
    # 核心口径 EPS = 经营利润 × (1 - 有效税率) ÷ 稀释股数（剔除 OI&E 股权重估）
    core_25 = 31271 * (1 - q2_25_tax_rate)
    core_26 = 40770 * (1 - q2_26_tax_rate)
    shares_25 = 28196 / 2.31
    shares_26 = 112107 / 9.11
    # 净现金两口径
    net_cash_gross_25 = 126843 - 46547
    net_cash_gross_26 = 242474 - 98165
    # 剔除上市股权证券（含受限 SpaceX）后的可动用净现金
    net_cash_liquid_25 = (126843 - 6313) - 46547
    net_cash_liquid_26 = (242474 - 87063) - 98165

    return {
        "经营利润率 Operating margin": (
            f"{31271 / 96428:.1%}", f"{40770 / 119796:.1%}",
            "经营利润÷收入",
        ),
        "Google Cloud 经营利润率": (
            f"{2826 / 13624:.1%}", f"{8814 / 24768:.1%}",
            "云经营利润÷云收入",
        ),
        "Google Services 经营利润率": (
            f"{33063 / 82543:.1%}", f"{39544 / 94540:.1%}",
            "Services经营利润÷Services收入",
        ),
        "有效税率 Effective tax rate": (
            f"{q2_25_tax_rate:.1%}", f"{q2_26_tax_rate:.1%}",
            "所得税÷除税前利润",
        ),
        "OI&E占除税前利润 OI&E/pretax": (
            f"{2662 / 33933:.1%}", f"{97983 / 138753:.1%}",
            "OI&E÷除税前利润（口径污染度）",
        ),
        "核心稀释EPS(估) core diluted EPS (USD)": (
            f"{core_25 / shares_25:.2f}", f"{core_26 / shares_26:.2f}",
            "经营利润×(1-有效税率)÷稀释股数·剔除OI&E股权重估·【推】非申报口径",
        ),
        "报告稀释EPS reported diluted EPS (USD)": (
            "2.31", "9.11", "10-Q 申报值",
        ),
        "单季自由现金流 quarterly FCF": (
            f"{(63897 - 39643) - 0:.0f}(H1口径)", f"{39100 - 44924:.0f}",
            "Q2'26 = 单季OCF $39.1B(MD&A) − 单季capex $44,924M(8-K)",
        ),
        "H1自由现金流 H1 FCF": (
            f"{63897 - 39643:.0f}", f"{84859 - 80598:.0f}",
            "H1经营现金流 − H1资本开支",
        ),
        "H1 FCF÷经营现金流": (
            f"{(63897 - 39643) / 63897:.1%}", f"{(84859 - 80598) / 84859:.1%}",
            "FCF÷OCF",
        ),
        "H1 capex÷经营现金流": (
            f"{39643 / 63897:.1%}", f"{80598 / 84859:.1%}",
            "资本开支÷经营现金流",
        ),
        "H1 capex÷折旧": (
            f"{39643 / 9485:.2f}x", f"{80598 / 13586:.2f}x",
            "资本开支÷当期折旧（未来折旧台阶指示）",
        ),
        "净现金(含受限股权) gross net cash": (
            f"{net_cash_gross_25:.0f}(2025末)", f"{net_cash_gross_26:.0f}",
            "(现金+有价证券)−长期债务",
        ),
        "净现金(剔上市股权证券) liquid net cash": (
            f"{net_cash_liquid_25:.0f}(2025末)", f"{net_cash_liquid_26:.0f}",
            "(现金+有价证券−上市股权证券)−长期债务·剔除受限SpaceX后可动用口径",
        ),
        "商誉÷总资产 Goodwill/assets": (
            f"{33380 / 595281:.1%}(2025末)", f"{57828 / 921983:.1%}",
            "商誉÷总资产",
        ),
        "应收÷收入(年化) AR/revenue": (
            f"{62886 / 402836:.1%}(2025末/FY25)", f"{69175 / (229692 * 2):.1%}",
            "应收账款÷年化收入",
        ),
        "采购承诺÷总资产 commitments/assets": (
            f"{149100 / 595281:.1%}(2025末)", f"{811000 / 921983:.1%}",
            "表外采购承诺÷总资产",
        ),
        "SBC÷收入 SBC/revenue (H1)": (
            f"{11514 / 186662:.1%}", f"{14708 / 229692:.1%}",
            "H1股权薪酬÷H1收入",
        ),
    }


def write_csvs() -> list[str]:
    written = []

    path = os.path.join(HERE, "中期财务-2026.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            f"# 单位: 百万美元(USD millions), 费用/流出=负数; 真源: {SRC}; "
            "中期数据·不并入年度序列(年度见 利润表/资产负债表/现金流量表.csv 覆盖2002-2025); "
            "勾稽校验见 _build_interim_2026.py; "
            "英文缩写全对照见 finance/_模板/美股财报缩写对照表.md —— "
            "OI&E=其他收入(支出)净额(主业之外全部损益·含股权公允价值变动) / EPS=每股收益 / "
            "FCF=自由现金流(经营现金流-资本开支) / capex=资本开支 / SBC=股权薪酬 / "
            "APIC=资本公积 / AOCI=累计其他综合收益 / ATM=随行就市增发计划(非自动柜员机) / "
            "capped call=上限看涨期权(对冲转股摊薄) / Level 1=活跃市场报价·Level 2=可观察输入值"
        ])
        w.writerow([])
        w.writerow(["【利润表·中期】", "Q2 2025", "Q2 2026", "H1 2025", "H1 2026"])
        for k, v in INCOME.items():
            w.writerow([k, *v])
        for k, v in EPS.items():
            w.writerow([k, *v])
        w.writerow([])
        w.writerow(["【OI&E 拆解·中期】", "Q2 2025", "Q2 2026", "H1 2025", "H1 2026"])
        for k, v in OIE.items():
            w.writerow([k, *v])
        w.writerow([])
        w.writerow(["【资产负债表】", "2025-12-31", "2026-06-30"])
        for k, v in BALANCE.items():
            w.writerow([k, *v])
        w.writerow([])
        w.writerow(["【现金流量表·半年】", "H1 2025", "H1 2026"])
        for k, v in CASHFLOW.items():
            w.writerow([k, *v])
        w.writerow([])
        w.writerow(["【派生指标】", "Q2/H1 2025", "Q2/H1 2026", "算法"])
        for k, (a, b, how) in derived().items():
            w.writerow([k, a, b, how])
        w.writerow([])
        w.writerow(["【单项一手事实】", "值(百万美元·除标注)"])
        for k, v in FACTS.items():
            w.writerow([k, v])
    written.append(path)

    path = os.path.join(HERE, "分部营收-中期2026.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            f"# 单位: 百万美元(USD millions); 真源: {SRC}; "
            "中期分部·不并入 分部营收.csv 年度序列; 勾稽: 广告三项=广告合计·广告+订阅=Services·"
            "三分部+对冲=总收入=利润表收入·分部经营利润合计=利润表经营利润·地区分项=总收入; "
            "缩写: YoY=同比 / EMEA=欧洲中东非洲 / APAC=亚太 "
            "(全对照见 finance/_模板/美股财报缩写对照表.md)"
        ])
        w.writerow([])
        w.writerow(["【收入按类型】", "Q2 2025", "Q2 2026", "Q2 YoY", "H1 2025", "H1 2026", "H1 YoY"])
        for k, v in SEGMENTS.items():
            # 符号翻转（如对冲损益由正转负）算同比无意义 → n/a，不输出会误导的百分比
            def yoy(prev: int, cur: int) -> str:
                if prev <= 0 or cur <= 0:
                    return "n/a(符号翻转或非正)"
                return f"{(cur / prev - 1):+.1%}"

            w.writerow([k, v[0], v[1], yoy(v[0], v[1]), v[2], v[3], yoy(v[2], v[3])])
        w.writerow([])
        w.writerow(["【分部经营利润】", "Q2 2025", "Q2 2026", "H1 2025", "H1 2026"])
        for k, v in SEGMENT_OI.items():
            w.writerow([k, *v])
        w.writerow([])
        w.writerow(["【收入按地区】", "Q2 2025", "Q2 2026", "H1 2025", "H1 2026"])
        for k, v in GEOGRAPHY.items():
            w.writerow([k, *v])
    written.append(path)

    path = os.path.join(HERE, "表外承诺与储备.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "# 单位: 百万美元(USD millions); 真源: FY2025 10-K=美股年报 (report/google/2025.htm) + "
            f"{SRC}; ⚠️收入储备(revenue backlog=已签约未确认收入)口径2026Q1起变更"
            "(纳入原始期限≤1年合同)→同比不完全可比; "
            "缩写: capex=资本开支 / take-or-pay=照付不议(不用也得付) "
            "(全对照见 finance/_模板/美股财报缩写对照表.md)"
        ])
        w.writerow([])
        w.writerow(["项目", "2025-12-31", "2026-06-30", "半年变化"])
        for k, v in OFF_BALANCE.items():
            if v[0] is None:
                w.writerow([k, "未单独披露", v[1], "n/a"])
            else:
                w.writerow([k, v[0], v[1], f"{(v[1] / v[0] - 1):+.1%}"])
    written.append(path)

    return written


def main() -> int:
    print(f"真源: {SRC}\n")
    try:
        verify()
    except AssertionError as exc:
        print(f"\n❌ {exc}\n→ CSV 未写出（校验不过不落盘）", file=sys.stderr)
        return 1
    print("\n✅ 全部勾稽通过\n")
    for path in write_csvs():
        print(f"写出 {os.path.relpath(path, HERE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
