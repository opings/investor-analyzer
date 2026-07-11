#!/usr/bin/env python3
"""google(Alphabet) 三表构建器 —— 从 SEC XBRL companyfacts(公司自报·一手)解析.

数据源(一手·机读):
  _xbrl/companyfacts-Alphabet-CIK1652044.json   (Alphabet Inc. · 覆盖 2013-2025)
  _xbrl/companyfacts-GoogleInc-CIK1288776.json   (Google Inc. 旧主体 · 覆盖 2007-2014)
  两主体在 2013/2014 重叠 —— 取「当年自身年报原始披露值」(fy==该年,详见 annual_original)。

覆盖:2007-2025(XBRL 起于 2007)。2001-2006 + 上市前无 XBRL,另由 _build_early_from_10k.py 从 S-1/早期 10-K 转录。
单位:百万美元(USD millions,= XBRL 原值 / 1e6);符号:CSV 惯例 流出/费用/减项=负数。
校验:每年三表勾稽自洽,不过打印残差(不静默)。
"""
import json
import os
import csv

DIR = os.path.dirname(os.path.abspath(__file__))
XBRL = os.path.join(DIR, "_xbrl")
FILES = ["companyfacts-Alphabet-CIK1652044.json", "companyfacts-GoogleInc-CIK1288776.json"]
YEARS = list(range(2002, 2026))  # 2002..2025 (2002-06 早年从 HTML 转录, 2007+ XBRL)

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
    ("研发开支 Research and development", ["ResearchAndDevelopmentExpense"], -1),
    ("销售及营销开支 Sales and marketing", ["SellingAndMarketingExpense"], -1),
    ("行政管理开支 General and administrative", ["GeneralAndAdministrativeExpense"], -1),
    ("总成本及开支 Total costs and expenses", ["CostsAndExpenses"], -1),
    ("经营利润 Income from operations", ["OperatingIncomeLoss"], 1),
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
    ("非流动有价证券 Non-marketable/LT securities",
     ["MarketableSecuritiesNoncurrent", "LongTermInvestments"]),
    ("物业及设备净额 Property and equipment, net",
     ["PropertyPlantAndEquipmentNet",
      "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization"]),
    ("经营租赁使用权资产 Operating lease right-of-use assets", ["OperatingLeaseRightOfUseAsset"]),
    ("商誉 Goodwill", ["Goodwill"]),
    ("资产总计 Total assets", ["Assets"]),
    ("应付账款 Accounts payable", ["AccountsPayableCurrent"]),
    ("流动负债合计 Total current liabilities", ["LiabilitiesCurrent"]),
    ("长期债务 Long-term debt", ["LongTermDebtNoncurrent", "LongTermDebt"]),
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
    ("折旧 Depreciation (& impairment of PP&E)", ["Depreciation"], 1),
    ("无形资产摊销 Amortization of intangibles",
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
    # 报表以百万为最小刻度;近似整数则取整
    if abs(m - round(m)) < 0.5:
        return str(int(round(m)))
    return f"{m:.1f}"


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

# ---- 叠加早年 2002-2006(从一手 HTML 财报转录·见 _early_2002_2006.py·毛口径 incl-SBC) ----
from _early_2002_2006 import EARLY, EARLY_EPS


def _overlay(table, early_dict, scale):
    for label, yrvals in early_dict.items():
        d = table.setdefault(label, {})
        for y, v in yrvals.items():
            d[y] = v * scale


_overlay(inc_all, EARLY["利润表"], 1000.0)   # 千美元 -> 美元
_overlay(inc_all, EARLY_EPS, 1.0)            # 每股值不缩放
_overlay(bal_table, EARLY["资产负债表"], 1000.0)
_overlay(cf_table, EARLY["现金流量表"], 1000.0)


# ================= 勾稽校验 =================
def g(table, label, yr):
    return table.get(label, {}).get(yr)


print("=" * 70)
print("勾稽自洽校验(单位:百万美元;残差 = 应等式两边之差)")
print("=" * 70)

print("\n--- 利润表: 除税前 + 所得税 + 终止经营 = 净利 ---")
for y in YEARS:
    pre = g(inc_table, "除税前利润 Income before income taxes", y)
    tax = g(inc_table, "所得税 Provision for income taxes", y)
    disc = g(inc_table, "终止经营净利(Motorola) Discontinued operations, net of tax", y) or 0
    ni = g(inc_table, "净利润 Net income", y)
    if None in (pre, tax, ni):
        print(f"  {y}: 数据缺 pre={pre} tax={tax} ni={ni}")
        continue
    resid = (pre + tax + disc - ni) / M
    flag = "OK" if abs(resid) < 2 else f"❌ 残差 {resid:.1f}"
    dtag = " (含Motorola终止经营)" if disc else ""
    print(f"  {y}: {flag}{dtag}")

print("\n--- 利润表: 收益 + 总成本及开支(负) = 经营利润 ---")
for y in YEARS:
    rev = g(inc_table, "收益 Revenues", y)
    tce = g(inc_table, "总成本及开支 Total costs and expenses", y)
    op = g(inc_table, "经营利润 Income from operations", y)
    if None in (rev, tce, op):
        print(f"  {y}: 数据缺 rev={rev} tce={tce} op={op}")
        continue
    resid = (rev + tce - op) / M
    flag = "OK" if abs(resid) < 2 else f"❌ 残差 {resid:.1f}"
    print(f"  {y}: {flag}")

print("\n--- 资产负债表: 资产 = 负债 + 权益 ---")
for y in YEARS:
    a = g(bal_table, "资产总计 Total assets", y)
    le = g(bal_table, "负债及权益合计 Total liabilities & equity", y)
    liab = g(bal_table, "负债合计 Total liabilities", y)
    eq = g(bal_table, "股东权益合计 Total stockholders' equity", y)
    parts = []
    if a is not None and le is not None:
        parts.append(f"A-（L&E）={ (a-le)/M:.1f}")
    if a is not None and liab is not None and eq is not None:
        parts.append(f"A-L-E={ (a-liab-eq)/M:.1f}")
    print(f"  {y}: {'; '.join(parts) if parts else '数据缺'}")

print("\n--- 现金流量表: 经营+投资+融资+汇率 = 现金净变动 ---")
for y in YEARS:
    op = g(cf_table, "经营活动现金流量净额 Net cash from operating", y)
    inv = g(cf_table, "投资活动现金流量净额 Net cash from investing", y)
    fin = g(cf_table, "融资活动现金流量净额 Net cash from financing", y)
    fx = g(cf_table, "汇率变动影响 Effect of exchange rate on cash", y)
    chg = g(cf_table, "现金净变动 Net increase(decrease) in cash", y)
    if None in (op, inv, fin, chg):
        print(f"  {y}: 数据缺 op={op} inv={inv} fin={fin} chg={chg}")
        continue
    fxv = fx or 0
    resid = (op + inv + fin + fxv - chg) / M
    flag = "OK" if abs(resid) < 2 else f"❌ 残差 {resid:.1f}(可能口径含受限现金)"
    print(f"  {y}: {flag}")

# ================= 缺失报告 =================
report_missing("利润表", inc_labels, inc_all)
report_missing("资产负债表", bal_labels, bal_table)
report_missing("现金流量表", cf_labels, cf_table)

# ================= 写出 CSV =================
SRC = "SEC XBRL companyfacts(Alphabet CIK1652044 + Google Inc CIK1288776·公司自报一手)"
SRC2 = SRC + " + 2002-06 一手 HTML 转录(S-1/FY2004/FY2006/FY2007 10-K)"
write_csv(os.path.join(DIR, "利润表.csv"),
          f"# 单位: 百万美元(USD millions), 费用/减项=负数, 覆盖2002-2025, 来源: {SRC2}",
          inc_labels, inc_all, inc_unit_map)
write_csv(os.path.join(DIR, "资产负债表.csv"),
          f"# 单位: 百万美元(USD millions), 覆盖2002-2025, 来源: {SRC2}",
          bal_labels, bal_table)
write_csv(os.path.join(DIR, "现金流量表.csv"),
          f"# 单位: 百万美元(USD millions), 流出=负数, 覆盖2002-2025, 来源: {SRC2}",
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
PLx = {
    "营业收入": _ser(inc_all, "收益 Revenues"),
    "营业成本": _ser(inc_all, "销售成本 Cost of revenues"),
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
    w.writerow(["# 派生比率(比率=小数,FCF=百万美元,周转=天); 通用底 scripts/derived.py + google 定制层; 覆盖2002-2025"])
    w.writerow(["科目"] + [str(y) for y in YEARS])
    for name, vals, fmt in ratio_rows:
        w.writerow([name] + [fmt_ratio(v, fmt) for v in vals])
print("✅ 已写出 财务比率.csv (" + str(len(ratio_rows)) + " 行)")
if unmatched:
    print("  derived 未匹配(google 无此科目属正常):", "、".join(sorted(set(unmatched))))
