#!/usr/bin/env python3
"""独立核 · XBRL companyfacts 轨：拿 SEC 机读接口（公司自报 XBRL·一手非第三方）逐格核三表 CSV。

为什么还要这一轨：R 轨是 SEC 把同一份 XBRL **渲染成 HTML** 后再由本库解析的——解析器若在
列对齐 / 正负号 / 单位上出错，勾稽未必能抓到（错位的两列常常各自自洽）。companyfacts 是**同一批
事实的另一种表示**（JSON·带期间起止日期·带申报流水号），不经过任何 HTML 表格，二者独立。

判据：对每个财年，只取**该财年自己那份 10-K**（accession 与 `_harvest_rfiles.FILINGS` 相同）申报的值，
期间 = 截至该年 6 月 30 日的 12 个月（流量）或 6 月 30 日时点（存量），与 CSV as-reported 值比。
覆盖 FY2009-2026（companyfacts 只回溯到 FY2009 那份 10-K 的比较期；FY2009/FY2010 用各自 10-K）。

用法：python3 _xcheck_xbrl.py      （首次会下载 companyfacts 到 _xbrl/，之后读缓存）
"""
import csv
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
XDIR = os.path.join(HERE, "_xbrl")
UA = "InvestorResearch admin@example.com"
CIK = 789019

# 财年 → 该年 10-K accession（FY2009/FY2010 无 R 文件但有 XBRL 事实）
ACC = {
    2009: "0001193125-09-158735", 2010: "0001193125-10-171791",
    2011: "0001193125-11-200680", 2012: "0001193125-12-316848", 2013: "0001193125-13-310206",
    2014: "0001193125-14-289961", 2015: "0001193125-15-272806", 2016: "0001193125-16-662209",
    2017: "0001564590-17-014900", 2018: "0001564590-18-019062", 2019: "0001564590-19-027952",
    2020: "0001564590-20-034944", 2021: "0001564590-21-039151", 2022: "0001564590-22-026876",
    2023: "0000950170-23-035122", 2024: "0000950170-24-087843", 2025: "0000950170-25-100235",
    2026: "0001193125-26-323660",
}

# (CSV 文件, CSV 行名, [XBRL 概念], 存量?)
CHECKS = [
    ("利润表.csv", "营业收入 Revenue",
     ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"], False),
    ("利润表.csv", "营业成本 Cost of revenue", ["CostOfGoodsAndServicesSold", "CostOfRevenue"], False),
    ("利润表.csv", "研发费用 Research and development", ["ResearchAndDevelopmentExpense"], False),
    ("利润表.csv", "营业利润 Operating income", ["OperatingIncomeLoss"], False),
    ("利润表.csv", "所得税 Provision for income taxes", ["IncomeTaxExpenseBenefit"], False),
    ("利润表.csv", "净利润 Net income", ["NetIncomeLoss"], False),
    ("资产负债表.csv", "总资产 Total assets", ["Assets"], True),
    ("资产负债表.csv", "股东权益合计 Total stockholders' equity", ["StockholdersEquity"], True),
    ("资产负债表.csv", "应收账款净额 Accounts receivable, net", ["AccountsReceivableNetCurrent"], True),
    ("资产负债表.csv", "固定资产净额 Property and equipment, net", ["PropertyPlantAndEquipmentNet"], True),
    ("现金流量表.csv", "经营活动现金流净额 Net cash from operations",
     ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"], False),
    # ⚠️ XBRL 的 Payments* 概念**正数 = 流出**，CSV 流出为负 → 比较前翻号（拼多多建库踩过同一坑）
    ("现金流量表.csv", "资本开支 Additions to property and equipment", ["-PaymentsToAcquirePropertyPlantAndEquipment"], False),
]


def load_facts():
    os.makedirs(XDIR, exist_ok=True)
    p = os.path.join(XDIR, "companyfacts.json")
    if not os.path.exists(p):
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK:010d}.json"
        raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120).read()
        open(p, "wb").write(raw)
    return json.load(open(p))["facts"]["us-gaap"]


def read_csv(name):
    with open(os.path.join(HERE, name)) as f:
        rows = list(csv.reader(f))
    h = next(i for i, r in enumerate(rows) if r and r[0] == "科目")
    years = [int(c[2:]) for c in rows[h][1:]]
    out = {}
    for r in rows[h + 2:]:
        if r:
            out[r[0]] = {y: (float(v) if v else None) for y, v in zip(years, r[1:])}
    return out


def xval(facts, concepts, fy, instant):
    end = f"{fy}-06-30"
    start = f"{fy - 1}-07-01"
    for c0 in concepts:
        sign, c = (-1.0, c0[1:]) if c0.startswith("-") else (1.0, c0)
        for u in facts.get(c, {}).get("units", {}).values():
            for f in u:
                if f.get("accn") != ACC[fy] or f.get("end") != end:
                    continue
                if not instant and f.get("start") != start:
                    continue
                if instant and "start" in f:
                    continue
                return sign * f["val"] / 1e6, c
    return None, None


def main():
    facts = load_facts()
    cache = {}
    ok = bad = miss = 0
    for fn, row, concepts, instant in CHECKS:
        if fn not in cache:
            cache[fn] = read_csv(fn)
        series = cache[fn].get(row)
        if series is None:
            print(f"❌ CSV 无此行（探针失败）：{fn} / {row}")
            return 1
        for fy in sorted(ACC):
            a = series.get(fy)
            x, c = xval(facts, concepts, fy, instant)
            if a is None or x is None:
                miss += 1
                print(f"  ·  FY{fy} {row[:20]}: CSV={a} XBRL={x}（缺一边，不计）")
                continue
            if abs(a - x) <= 0.5:
                ok += 1
            else:
                bad += 1
                print(f"  ❌ FY{fy} {row[:20]}: CSV={a:g} XBRL({c})={x:g} 差 {a - x:g}")
    print(f"\nXBRL 独立核：一致 {ok} 格 · 不一致 {bad} 格 · 缺一边 {miss} 格")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
