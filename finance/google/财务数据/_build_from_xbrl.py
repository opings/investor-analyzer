#!/usr/bin/env python3
"""google(Alphabet) 三表构建器 —— 从 SEC XBRL companyfacts(公司自报·一手)解析.

数据源(一手·机读):
  _xbrl/companyfacts-Alphabet-CIK1652044.json   (Alphabet Inc. · 覆盖 2013-2025)
  _xbrl/companyfacts-GoogleInc-CIK1288776.json   (Google Inc. 旧主体 · 覆盖 2007-2014)
  两主体在 2013/2014 重叠 —— 取「当年自身年报原始披露值」(fy==该年,详见 annual_original)。

覆盖:1999-2025。XBRL 起于 2007;1999-2006 无 XBRL,由 _early_1999_2006.py 从 424B4 定稿招股书 / S-1 /
早期 10-K 转录(1999-2000 为招股书五年表摘要级、2001 起有审计报表)。
单位:百万美元(USD millions,= XBRL 原值 / 1e6;千美元来源年份保留到千美元精度);符号:CSV 惯例 流出/费用/减项=负数。
校验:每年三表勾稽自洽 + 费用分项和 = 总成本 + 早年摘要两处出处互核;**任一不过即不写出 CSV**(--force 除外)。
"""
import json
import os
import csv
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
XBRL = os.path.join(DIR, "_xbrl")
FILES = ["companyfacts-Alphabet-CIK1652044.json", "companyfacts-GoogleInc-CIK1288776.json"]
YEARS = list(range(1999, 2026))  # 1999..2025 (1999-2006 早年从 HTML 转录, 2007+ XBRL)

_facts = []
for fn in FILES:
    with open(os.path.join(XBRL, fn)) as f:
        _facts.append(json.load(f))


def _gather(tag, unit):
    out = []
    for d in _facts:
        node = d["facts"].get("us-gaap", {}).get(tag)
        if not node:
            continue
        arr = node.get("units", {}).get(unit)
        if arr:
            out.extend(arr)
    return out


def annual_original(tag, unit="USD", instant=False):
    """year -> 原始披露值(10-K, 12 月末). 重叠年取 min(fy)=首次披露=当年自身年报."""
    cand = {}
    for r in _gather(tag, unit):
        if r.get("form") != "10-K":
            continue
        end = r.get("end", "")
        if len(end) < 7 or end[5:7] != "12":
            continue
        yr = int(end[:4])
        if instant:
            if r.get("start") is not None:
                continue
        else:
            start = r.get("start")
            if not start or start[5:7] != "01" or start[:4] != end[:4]:
                continue
        cand.setdefault(yr, []).append(r)
    out = {}
    for yr, recs in cand.items():
        recs.sort(key=lambda x: (x.get("fy", 9999), x.get("filed", "")))
        out[yr] = recs[0]["val"]
    return out


def series(candidates, unit="USD", instant=False):
    """按优先级合并候选 tag;每年取第一个有值的. 返回 (merged{yr:val}, used{yr:tag})."""
    merged, used = {}, {}
    for tag in candidates:
        s = annual_original(tag, unit, instant)
        for yr, v in s.items():
            if yr not in merged:
                merged[yr], used[yr] = v, tag
    return merged, used


# ---- 行定义: (中文名 English, [候选tag], 符号 flip: -1=费用取负, unit, instant) ----
M = 1e6  # 百万

INCOME = [
    ("收益 Revenues",
     ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"], 1),
    ("销售成本 Cost of revenues", ["CostOfRevenue"], -1),
    # FY2012/FY2013 10-K 利润表把营业成本分两行(Google / Motorola Mobile),XBRL 的 CostOfRevenue 只取到 Google 那行;
    # 营收却含 Motorola —— 不补这行,2012-2013 毛利率被高估(费用分项和校验抓出)
    ("销售成本·Motorola Mobile(仅2012-2013) Cost of revenues - Motorola Mobile", [], -1),
    ("研发开支 Research and development", ["ResearchAndDevelopmentExpense"], -1),
    ("销售及营销开支 Sales and marketing", ["SellingAndMarketingExpense"], -1),
    ("行政管理开支 General and administrative", ["GeneralAndAdministrativeExpense"], -1),
    # 2017-2019 利润表单列一行;2018-2019 用公司自定义标签、companyfacts 不收 → 下方从各年自家 10-K 原文补
    ("欧盟委员会罚款(仅2017-2019) European Commission fines", [], -1),
    # 其余各年利润表单列的一次性费用行(各年自家 10-K 原文;旧版漏收,费用分项和校验抓出)
    ("雅虎和解非经常性部分(仅2004) Non-recurring portion of settlement of disputes with Yahoo", [], -1),
    ("Google 基金会捐赠(仅2005) Contribution to Google Foundation", [], -1),
    ("司法部调查和解费用(仅2011) Charge related to the resolution of Department of Justice investigation", [], -1),
    ("总成本及开支 Total costs and expenses", ["CostsAndExpenses"], -1),
    ("经营利润 Income from operations", ["OperatingIncomeLoss"], 1),
    ("股权投资减值(仅2008·营业外) Impairment of equity investments", [], -1),
    ("其他收入(支出)净额 Other income(expense) net",
     ["NonoperatingIncomeExpense", "OtherNonoperatingIncomeExpense"], 1),
    ("除税前利润 Income before income taxes",
     ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"], 1),
    ("所得税 Provision for income taxes", ["IncomeTaxExpenseBenefit"], -1),
    ("持续经营净利 Net income from continuing operations",
     ["IncomeLossFromContinuingOperationsIncludingPortionAttributableToNoncontrollingInterest",
      "IncomeLossFromContinuingOperations"], 1),
    ("终止经营净利(Motorola) Discontinued operations, net of tax",
     ["IncomeLossFromDiscontinuedOperationsNetOfTax"], 1),
    ("净利润 Net income", ["NetIncomeLoss"], 1),
]
INCOME_EPS = [
    ("每股基本盈利(美元) Basic EPS", ["EarningsPerShareBasic"], 1, "USD/shares"),
    ("每股摊薄盈利(美元) Diluted EPS", ["EarningsPerShareDiluted"], 1, "USD/shares"),
]

BALANCE = [
    ("现金及现金等价物 Cash and cash equivalents", ["CashAndCashEquivalentsAtCarryingValue"]),
    ("短期有价证券 Marketable securities (current)",
     ["MarketableSecuritiesCurrent", "ShortTermInvestments", "AvailableForSaleSecuritiesCurrent"]),
    ("应收账款净额 Accounts receivable, net", ["AccountsReceivableNetCurrent"]),
    ("流动资产合计 Total current assets", ["AssetsCurrent"]),
    # 原表行名三代:Non-marketable equity securities(–2012)→ equity investments(2013-2014)→ investments(2015-2020)
    # → securities(2021 起);2008-2025 全部 = OtherLongTermInvestments(逐年对原表一致)。
    # 旧版候选 MarketableSecuritiesNoncurrent(附注小项,如 2024 仅 266)+ LongTermInvestments,行名也误作「有价证券」
    ("非上市证券投资 Non-marketable securities", ["OtherLongTermInvestments"]),
    ("物业及设备净额 Property and equipment, net",
     ["PropertyPlantAndEquipmentNet",
      "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization"]),
    ("经营租赁使用权资产 Operating lease right-of-use assets", ["OperatingLeaseRightOfUseAsset"]),
    ("商誉 Goodwill", ["Goodwill"]),
    ("资产总计 Total assets", ["Assets"]),
    ("应付账款 Accounts payable", ["AccountsPayableCurrent"]),
    ("流动负债合计 Total current liabilities", ["LiabilitiesCurrent"]),
    # 取资产负债表原表那一行(各年自家 10-K):2012-2024 原表「Long-term debt」含融资租赁 = LongTermDebtAndCapitalLeaseObligations,
    # 2010-2011 / 2025 用 LongTermDebtNoncurrent。旧版把 LongTermDebtNoncurrent(纯票据)放首位、LongTermDebt(含一年内到期)兜底,
    # 一行混三种口径:2013/2014/2017-2019 少计融资租赁、2020-2022 误含一年内到期部分、2023 取了 FY2024 10-K 重分类后的 11,870(原表 13,253)
    ("长期债务 Long-term debt", ["LongTermDebtAndCapitalLeaseObligations", "LongTermDebtNoncurrent"]),
    ("负债合计 Total liabilities", ["Liabilities"]),
    ("负债及权益合计 Total liabilities & equity", ["LiabilitiesAndStockholdersEquity"]),
    ("股东权益合计 Total stockholders' equity", ["StockholdersEquity"]),
]

CASHFLOW = [
    ("经营活动现金流量净额 Net cash from operating", ["NetCashProvidedByUsedInOperatingActivities"], 1),
    ("投资活动现金流量净额 Net cash from investing", ["NetCashProvidedByUsedInInvestingActivities"], 1),
    ("融资活动现金流量净额 Net cash from financing", ["NetCashProvidedByUsedInFinancingActivities"], 1),
    ("汇率变动影响 Effect of exchange rate on cash",
     ["EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
      "EffectOfExchangeRateOnCashAndCashEquivalents"], 1),
    ("现金净变动 Net increase(decrease) in cash",
     ["CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
      "CashAndCashEquivalentsPeriodIncreaseDecrease"], 1),
    ("--- 补充: 关键分项 ---", [], 1),
    # 原表那一行的口径随年份变(各年自家 10-K 现金流量表):2012-2013「折旧及摊销」/ 2014「折旧及处置损失」/
    # 2015-2022「折旧及减值」/ 2023 起「纯折旧」;2014-2022 在 XBRL 里是公司自定义 tag(companyfacts 不收)→ 下方从原文补
    ("折旧(原表口径·各年自家10-K) Depreciation as reported", ["Depreciation"], 1),
    # FY2023 10-K 起改列纯折旧,并把 2021-2022 回溯重列(PP&E 减值与无形资产摊销并入 Other);与上一行在 2021-2022 重叠,供跨断点衔接
    ("折旧(纯折旧·FY2023 10-K 起口径) Depreciation of property and equipment", [], 1),
    ("无形资产摊销(2014-2022 含减值·2023 起原表不再单列) Amortization of intangibles",
     ["AmortizationOfIntangibleAssets", "AmortizationOfAcquiredIntangibleAssets"], 1),
    ("股权薪酬 Share-based compensation", ["ShareBasedCompensation"], 1),
    ("资本开支 Purchases of property and equipment", ["PaymentsToAcquirePropertyPlantAndEquipment"], -1),
    ("股票回购 Repurchases of capital stock", ["PaymentsForRepurchaseOfCommonStock"], -1),
    ("已付股息 Dividends/other distributions",
     ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"], -1),
]


def fmt(v, unit="USD"):
    if v is None:
        return ""
    if unit == "USD/shares":
        return f"{v:.2f}"
    m = v / M
    # XBRL 年份为整百万;千美元来源年份(1999-2006)保留到千美元(3 位小数)——旧版一律四舍五入到百万,
    # 1999 年收入 22 万美元会被印成 0
    if abs(m - round(m)) < 1e-6:
        return str(int(round(m)))
    return f"{m:.3f}".rstrip("0").rstrip(".")


def build_table(rows, has_flip=True, has_unit=False):
    table = {}   # label -> {yr: raw_val}
    usage = {}
    for row in rows:
        label = row[0]
        cands = row[1]
        flip = row[2] if has_flip else 1
        unit = row[3] if has_unit else "USD"
        instant = (not has_flip)  # balance sheet uses instant
        if not cands:
            table[label] = {}
            continue
        merged, used = series(cands, unit=unit, instant=instant)
        table[label] = {yr: flip * merged[yr] for yr in merged}
        usage[label] = used
    return table, usage


def write_csv(path, header_comment, rows_labels, table, unit_row_map=None):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([header_comment])
        w.writerow(["科目"] + [str(y) for y in YEARS])
        for label in rows_labels:
            u = unit_row_map.get(label, "USD") if unit_row_map else "USD"
            vals = table.get(label, {})
            w.writerow([label] + [fmt(vals.get(y), u) for y in YEARS])


def report_missing(name, rows_labels, table):
    print(f"\n[{name}] 缺失/空覆盖检查:")
    for label in rows_labels:
        if label.startswith("---"):
            continue
        vals = table.get(label, {})
        miss = [y for y in YEARS if y not in vals]
        if miss:
            print(f"  ⚠ {label[:40]:40s} 缺 {miss}")


# ================= 构建 =================
inc_table, inc_use = build_table(INCOME, has_flip=True)
# EPS 单独(USD/shares)
eps_table = {}
eps_unit = {}
for label, cands, flip, unit in INCOME_EPS:
    merged, _ = series(cands, unit=unit, instant=False)
    eps_table[label] = merged
    eps_unit[label] = unit
inc_all = {**inc_table, **eps_table}
inc_labels = [r[0] for r in INCOME] + [r[0] for r in INCOME_EPS]
inc_unit_map = {r[0]: "USD/shares" for r in INCOME_EPS}

bal_table, _ = build_table([(r[0], r[1]) for r in BALANCE], has_flip=False)
bal_labels = [r[0] for r in BALANCE]

cf_table, _ = build_table(CASHFLOW, has_flip=True)
cf_labels = [r[0] for r in CASHFLOW]

# ---- 叠加早年 1999-2006(从一手 HTML 财报转录·见 _early_1999_2006.py·毛口径 incl-SBC) ----
from _early_1999_2006 import (EARLY, EARLY_EPS, PRE_IPO_BS_424B4, PRE_IPO_BS_FY2004_10K, CF2001_CASH,
                              SUMMARY_ONLY_BS_YEARS, EARLY_BALANCE_SUMMARY)


def _overlay(table, early_dict, scale):
    for label, yrvals in early_dict.items():
        d = table.setdefault(label, {})
        for y, v in yrvals.items():
            d[y] = v * scale


_overlay(inc_all, EARLY["利润表"], 1000.0)   # 千美元 -> 美元
_overlay(inc_all, EARLY_EPS, 1.0)            # 每股值不缩放
_overlay(bal_table, EARLY["资产负债表"], 1000.0)
_overlay(cf_table, EARLY["现金流量表"], 1000.0)
for _lab in EARLY_BALANCE_SUMMARY:          # 摘要行只在 1999-2003 有值,排在资产负债表末尾
    if _lab not in bal_labels:
        bal_labels.append(_lab)
# 孤儿行闸:早年模块的标签必须与行定义一字不差 —— 否则叠加进去的数据不会被写出(静默丢弃,改行名时最容易踩)
for _name, _labels, _early in (("利润表", inc_labels, {**EARLY["利润表"], **EARLY_EPS}),
                               ("资产负债表", bal_labels, EARLY["资产负债表"]),
                               ("现金流量表", cf_labels, EARLY["现金流量表"])):
    _orphans = [k for k in _early if k not in _labels]
    if _orphans:
        print(f"🔴 早年模块标签不在{_name}行定义里(会被静默丢弃):{_orphans}")
        sys.exit(1)
# 欧盟委员会罚款(百万美元·各年自家 10-K 利润表原文:FY2017 2,736 / FY2018 5,071 / FY2019 1,697)
EC_FINE = "欧盟委员会罚款(仅2017-2019) European Commission fines"
inc_table[EC_FINE].update({2017: -2736 * M, 2018: -5071 * M, 2019: -1697 * M})
# 其余一次性行(各年自家 10-K 利润表原文;千美元来源年份按千美元)
MOTO_COR = "销售成本·Motorola Mobile(仅2012-2013) Cost of revenues - Motorola Mobile"
ONE_OFF = {
    MOTO_COR: {2012: -3458 * M, 2013: -3865 * M},     # FY2012/FY2013 10-K(FY2013 10-K 季度表四季加总互证)
    "雅虎和解非经常性部分(仅2004) Non-recurring portion of settlement of disputes with Yahoo": {2004: -201000 * 1000.0},
    "Google 基金会捐赠(仅2005) Contribution to Google Foundation": {2005: -90000 * 1000.0},
    "司法部调查和解费用(仅2011) Charge related to the resolution of Department of Justice investigation": {2011: -500 * M},
}
IMPAIR = "股权投资减值(仅2008·营业外) Impairment of equity investments"
for _lab, _vals in ONE_OFF.items():
    inc_table[_lab].update(_vals)
inc_table[IMPAIR].update({2008: -1094757 * 1000.0})          # FY2008 10-K 利润表(千美元)
# 2007-2008 其他收入:两年都无自家年份 XBRL;FY2009 10-K 把这行打成 OtherNonoperatingIncome(后期该 tag 只是子项,不能进候选),
# 致 2007 缺、2008 落到 FY2010 10-K 的百万取整值 316 → 按各年自家 10-K 利润表原文(千美元)覆盖
inc_table["其他收入(支出)净额 Other income(expense) net"].update({2007: 589580 * 1000.0, 2008: 316384 * 1000.0})
# 现金流量表折旧/摊销(百万美元·各年自家 10-K 现金流量表 Adjustments 段本年列原文)
DEP_AS_REP = "折旧(原表口径·各年自家10-K) Depreciation as reported"
DEP_PURE = "折旧(纯折旧·FY2023 10-K 起口径) Depreciation of property and equipment"
AMORT = "无形资产摊销(2014-2022 含减值·2023 起原表不再单列) Amortization of intangibles"
cf_table[DEP_AS_REP].update({y: v * M for y, v in {
    2014: 3523, 2015: 4132, 2016: 5267, 2017: 6103, 2018: 8164, 2019: 10856, 2020: 12905,
    2021: 11555, 2022: 15287}.items()})          # 2021-2022 旧值 10,273/13,475 是 FY2023 10-K 回溯重列数,非当年原表
cf_table[AMORT].update({y: v * M for y, v in {
    2014: 1456, 2015: 931, 2016: 877, 2017: 812, 2018: 871, 2019: 925, 2020: 792, 2021: 886, 2022: 641}.items()})
_dep_x = annual_original("Depreciation")     # 2021-2022 = FY2023 10-K 回溯值,2023 起 = 当年原表
cf_table[DEP_PURE].update({y: v for y, v in _dep_x.items() if y >= 2021})
# 2015 EPS 分类别披露(Class C 获 5.22 亿美元调整款,XBRL 只有按类别维度值、companyfacts 不收)→ 取 Class A/B
# (FY2015 10-K 每股收益附注原文);Class C 为 基本 24.63 / 摊薄 24.34
inc_all["每股基本盈利(美元) Basic EPS"][2015] = 23.11
inc_all["每股摊薄盈利(美元) Diluted EPS"][2015] = 22.84


# ================= 勾稽校验(任一不过 → 不写出 CSV) =================
def g(table, label, yr):
    return table.get(label, {}).get(yr)


def tol(y):
    return 2e3 if y <= 2006 else 2e6     # 千美元来源年份容差 2 千美元、XBRL 年份 2 百万美元


FAIL, RUN = [], []


def chk(y, code, resid):
    RUN.append((y, code))
    if abs(resid) > tol(y):
        FAIL.append(f"{y} {code}: 残差 {resid / M:.3f} 百万美元")


print("=" * 70)
print("勾稽自洽校验(残差 = 应等式两边之差;任一不过不写出 CSV)")
print("=" * 70)
REV, TCE, OI_, OIE, PBT, TAX, NI_ = ("收益 Revenues", "总成本及开支 Total costs and expenses",
                                     "经营利润 Income from operations", "其他收入(支出)净额 Other income(expense) net",
                                     "除税前利润 Income before income taxes", "所得税 Provision for income taxes",
                                     "净利润 Net income")
EXP = ["销售成本 Cost of revenues", "研发开支 Research and development", "销售及营销开支 Sales and marketing",
       "行政管理开支 General and administrative", EC_FINE] + list(ONE_OFF)
DISC = "终止经营净利(Motorola) Discontinued operations, net of tax"
for y in YEARS:
    # C0 必填:收入 / 经营利润 / 税前 / 所得税 / 净利 / 总资产 / 权益(1999 起)、经营现金流(2001 起)
    for tab, lab in ((inc_table, REV), (inc_table, OI_), (inc_table, PBT), (inc_table, TAX), (inc_table, NI_),
                     (bal_table, "资产总计 Total assets"), (bal_table, "股东权益合计 Total stockholders' equity")):
        if g(tab, lab, y) is None:
            FAIL.append(f"{y} C0 必填缺:{lab}")
    if y >= 2001 and g(cf_table, "经营活动现金流量净额 Net cash from operating", y) is None:
        FAIL.append(f"{y} C0 必填缺:经营活动现金流量净额")
    rev, tce, op, pre, tax, ni = (g(inc_table, k, y) for k in (REV, TCE, OI_, PBT, TAX, NI_))
    if None not in (pre, tax, ni):
        chk(y, "C1 税前+所得税+终止经营=净利", pre + tax + (g(inc_table, DISC, y) or 0) - ni)
    if None not in (rev, tce, op):
        chk(y, "C2 收益+总成本=经营利润", rev + tce - op)
    exps = [g(inc_table, k, y) for k in EXP]
    if tce is not None and all(v is not None for v in exps[:4]):
        chk(y, "C3 费用分项和=总成本", sum(v or 0 for v in exps) - tce)
    oie = g(inc_table, OIE, y)
    if None not in (op, oie, pre):
        chk(y, "C4 经营利润+其他收入(+2008 股权投资减值)=税前", op + oie + (g(inc_table, IMPAIR, y) or 0) - pre)
    # 资产负债表
    a = g(bal_table, "资产总计 Total assets", y)
    le = g(bal_table, "负债及权益合计 Total liabilities & equity", y)
    liab = g(bal_table, "负债合计 Total liabilities", y)
    eq = g(bal_table, "股东权益合计 Total stockholders' equity", y)
    if y in SUMMARY_ONLY_BS_YEARS:
        pass                                            # 只有摘要四项:改做下方两处出处互核
    elif a is not None and le is not None:
        chk(y, "B1 资产=负债及权益合计", a - le)
    else:
        FAIL.append(f"{y} B1 资产负债表缺两侧合计(非摘要年份)")
    if a is not None and liab is not None and eq is not None:
        chk(y, "B2 资产=负债+权益", a - liab - eq)
    # 现金流量表
    cfv = [g(cf_table, k, y) for k in ("经营活动现金流量净额 Net cash from operating",
                                       "投资活动现金流量净额 Net cash from investing",
                                       "融资活动现金流量净额 Net cash from financing",
                                       "现金净变动 Net increase(decrease) in cash")]
    if None not in cfv:
        chk(y, "F1 经营+投资+融资+汇率=现金净变动",
            cfv[0] + cfv[1] + cfv[2] + (g(cf_table, "汇率变动影响 Effect of exchange rate on cash", y) or 0) - cfv[3])

# 早年摘要:两处出处互核(424B4 五年表 vs FY2004 10-K 五年表)+ 摘要 vs 审计全表(2002-2003)
for y, b in PRE_IPO_BS_FY2004_10K.items():
    for k in ("cash_sti", "ta", "ltl", "eq"):
        chk(y, f"S1 摘要两处出处一致({k})", (PRE_IPO_BS_424B4[y][k] - b[k]) * 1000)
for y in (2002, 2003):
    cs = g(bal_table, "现金及现金等价物 Cash and cash equivalents", y) + \
        g(bal_table, "短期有价证券 Marketable securities (current)", y)
    chk(y, "S2 摘要现金及短投=审计表现金+短期有价证券", PRE_IPO_BS_424B4[y]["cash_sti"] * 1000 - cs)
    chk(y, "S3 摘要总资产=审计表总资产", PRE_IPO_BS_424B4[y]["ta"] * 1000 - g(bal_table, "资产总计 Total assets", y))
chk(2001, "F2 期初现金+净变动=期末现金",
    (CF2001_CASH["begin"] + EARLY["现金流量表"]["现金净变动 Net increase(decrease) in cash"][2001]
     - CF2001_CASH["end"]) * 1000)

codes = {}
for y, c in RUN:
    codes.setdefault(c.split(" ")[0], []).append(y)
print("执行勾稽 " + str(len(RUN)) + " 次:" + " ".join(f"{c}×{len(v)}" for c, v in sorted(codes.items())))
c1 = sorted(y for y, c in RUN if c.startswith("C1"))
f1 = sorted(y for y, c in RUN if c.startswith("F1"))
print(f"  C1 覆盖 {c1[0]}-{c1[-1]} 共 {len(c1)} 年;F1 覆盖 {f1[0]}-{f1[-1]} 共 {len(f1)} 年")
if len(c1) != len(YEARS):
    FAIL.append(f"覆盖闸:C1 只覆盖 {len(c1)} 年 ≠ {len(YEARS)}")
if len(f1) != 2025 - 2001 + 1:
    FAIL.append(f"覆盖闸:F1 只覆盖 {len(f1)} 年 ≠ 2001-2025")

# ================= 缺失报告 =================
report_missing("利润表", inc_labels, inc_all)
report_missing("资产负债表", bal_labels, bal_table)
report_missing("现金流量表", cf_labels, cf_table)

if FAIL:
    print(f"\n🔴 勾稽未过 {len(FAIL)} 条:")
    for f_ in FAIL:
        print("  " + f_)
    if "--force" not in sys.argv:
        print("不写出 CSV(--force 可强制)")
        sys.exit(1)
else:
    print("\n✅ 勾稽全过")

# ================= 写出 CSV =================
SRC = "SEC XBRL companyfacts(Alphabet CIK1652044 + Google Inc CIK1288776·公司自报一手)"
SRC2 = SRC + " + 1999-2006 一手 HTML 转录(424B4 定稿招股书/S-1/FY2004/FY2006/FY2007 10-K)"
NOTE99 = "1999-2000 为招股书五年表摘要级(利润表全行、资产负债表仅摘要四项、无现金流量表)、2001 资产负债表仅摘要四项"
write_csv(os.path.join(DIR, "利润表.csv"),
          f"# 单位: 百万美元(USD millions), 费用/减项=负数, 覆盖1999-2025({NOTE99}), 来源: {SRC2}",
          inc_labels, inc_all, inc_unit_map)
write_csv(os.path.join(DIR, "资产负债表.csv"),
          f"# 单位: 百万美元(USD millions), 覆盖1999-2025({NOTE99}), 来源: {SRC2}",
          bal_labels, bal_table)
write_csv(os.path.join(DIR, "现金流量表.csv"),
          f"# 单位: 百万美元(USD millions), 流出=负数, 覆盖2001-2025(1999-2000 无现金流量表), 来源: {SRC2}",
          cf_labels, cf_table)
print("\n✅ 已写出 利润表.csv / 资产负债表.csv / 现金流量表.csv")

# ================= 派生财务比率(通用底 scripts/derived.py + google 定制层) =================
import sys
REPO = os.path.dirname(os.path.dirname(os.path.dirname(DIR)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import derived  # noqa: E402


def _ser(table, label):
    dd = table.get(label, {})
    return [dd.get(y) for y in YEARS]


# 适配层: 把 google 双语标签映射到 derived 期望的中文别名(不改共享 derived.py)
_cor = _ser(inc_all, "销售成本 Cost of revenues")
_moto = _ser(inc_all, MOTO_COR)
PLx = {
    "营业收入": _ser(inc_all, "收益 Revenues"),
    # 2012-2013 营业成本 = Google + Motorola Mobile 两行(营收含 Motorola,成本也必须含)
    "营业成本": [None if c is None else c + (m or 0) for c, m in zip(_cor, _moto)],
    "销售费用": _ser(inc_all, "销售及营销开支 Sales and marketing"),
    "管理费用": _ser(inc_all, "行政管理开支 General and administrative"),
    "研发费用": _ser(inc_all, "研发开支 Research and development"),
    "净利润": _ser(inc_all, "净利润 Net income"),
    "归属于母公司股东的净利润": _ser(inc_all, "净利润 Net income"),  # Alphabet 无重大少数股东权益(NCI≈0)
}
BSx = {
    "应收账款": _ser(bal_table, "应收账款净额 Accounts receivable, net"),
    "应付账款": _ser(bal_table, "应付账款 Accounts payable"),
    "固定资产": _ser(bal_table, "物业及设备净额 Property and equipment, net"),
    "资产总计": _ser(bal_table, "资产总计 Total assets"),
    "股东权益合计": _ser(bal_table, "股东权益合计 Total stockholders' equity"),
    "现金及现金等价物": _ser(bal_table, "现金及现金等价物 Cash and cash equivalents"),
    "交易性金融资产": _ser(bal_table, "短期有价证券 Marketable securities (current)"),  # 让 cashfin 计入
}
CFx = {
    "经营活动现金流量净额": _ser(cf_table, "经营活动现金流量净额 Net cash from operating"),
    "购建固定资产": _ser(cf_table, "资本开支 Purchases of property and equipment"),
    "已付股息": _ser(cf_table, "已付股息 Dividends/other distributions"),
}
common, unmatched = derived.compute_common_ratios(PLx, BSx, CFx)

# ---- google 定制层 ----
NY = len(YEARS)
rev = _ser(inc_all, "收益 Revenues")
ni = _ser(inc_all, "净利润 Net income")
tax = _ser(inc_all, "所得税 Provision for income taxes")
pretax = _ser(inc_all, "除税前利润 Income before income taxes")
ocf = _ser(cf_table, "经营活动现金流量净额 Net cash from operating")
capex = _ser(cf_table, "资本开支 Purchases of property and equipment")
sbc = _ser(cf_table, "股权薪酬 Share-based compensation")
buyback = _ser(cf_table, "股票回购 Repurchases of capital stock")
div = _ser(cf_table, "已付股息 Dividends/other distributions")


def _rat(a, b):
    return a / b if (a is not None and b not in (None, 0)) else None


fcf = [(ocf[i] - abs(capex[i])) if (ocf[i] is not None and capex[i] is not None) else None for i in range(NY)]
custom = [
    ("股权薪酬/营收 SBC/Revenue", [_rat(sbc[i], rev[i]) for i in range(NY)], "pct"),
    ("自由现金流FCF(百万美元) OCF−Capex", [(fcf[i] / M if fcf[i] is not None else None) for i in range(NY)], "mn"),
    ("FCF/净利 FCF/Net income", [_rat(fcf[i], ni[i]) for i in range(NY)], "x"),
    ("有效税率 Effective tax rate", [_rat(abs(tax[i]), pretax[i]) if tax[i] is not None else None for i in range(NY)], "pct"),
    ("资本回报(回购+分红)/净利 Capital return/NI",
     [_rat((abs(buyback[i]) if buyback[i] else 0) + (abs(div[i]) if div[i] else 0), ni[i]) for i in range(NY)], "pct"),
]


def fmt_ratio(v, fmt):
    if v is None:
        return ""
    if fmt in ("pct", "x"):
        return f"{v:.4f}"
    if fmt == "day":
        return f"{v:.3f}"
    if fmt == "mn":
        return f"{v:.0f}"
    return ""


ratio_rows = [(n, v, f) for (n, v, f) in common] + custom
with open(os.path.join(DIR, "财务比率.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["# 派生比率(比率=小数,FCF=百万美元,周转=天); 通用底 scripts/derived.py + google 定制层; 覆盖1999-2025(1999-2001 只有利润表与摘要级资产负债表)"])
    w.writerow(["科目"] + [str(y) for y in YEARS])
    for name, vals, fmt in ratio_rows:
        w.writerow([name] + [fmt_ratio(v, fmt) for v in vals])
print("✅ 已写出 财务比率.csv (" + str(len(ratio_rows)) + " 行)")
if unmatched:
    print("  derived 未匹配(google 无此科目属正常):", "、".join(sorted(set(unmatched))))
