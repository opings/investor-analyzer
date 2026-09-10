#!/usr/bin/env python3
"""特斯拉 2026 年中期财务（Q1 / Q2 / H1 及 2025 同期）构建器。

来源：10-Q 2026Q1（acc 0001628280-26-026673）与 10-Q 2026Q2（acc 0001628280-26-049270）
      的 SEC 渲染报表 R*.htm（as-reported）。缓存 `_rfiles/2026Q1.json` / `_rfiles/2026Q2.json`。
单位：千美元（印刷为百万 → ×1000）；费用/流出 = 负数；资产负债表按印刷原值。
校验：营收+成本=毛利；毛利+经营费用=经营利润；经营利润+线下=税前；税前+所得税=净利；
      净利−少数股东=归母；Q1+Q2=H1（损益）；H1 现金流表与 Q1 现金流表期初现金一致。
      不通过不写出 CSV。
"""
from __future__ import annotations

import csv
import gzip
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harvest_rfiles import classify, parse_r  # noqa: E402

CIK = "1318605"
UA = "investor-analyzer sylar.zhao@dcsserv.com"
HERE = os.path.dirname(os.path.abspath(__file__))
RDIR = os.path.join(HERE, "_rfiles")
ACC = {"2026Q1": "0001628280-26-026673", "2026Q2": "0001628280-26-049270"}
SC = 1000.0                                   # 印刷百万 → 千美元


def get(u):
    r = urllib.request.Request(u, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
    b = urllib.request.urlopen(r, timeout=180).read()
    return gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b


def harvest(q):
    dest = os.path.join(RDIR, f"{q}.json")
    if os.path.exists(dest):
        return json.load(open(dest, encoding="utf-8"))
    base = f"https://www.sec.gov/Archives/edgar/data/{CIK}/{ACC[q].replace('-', '')}"
    root = ET.fromstring(get(base + "/FilingSummary.xml"))
    time.sleep(0.3)
    st = {}
    for r in root.iter("Report"):
        sn = (r.findtext("ShortName") or "").strip()
        fn = (r.findtext("HtmlFileName") or "").strip()
        k = classify(sn) if fn else None
        if k and k not in st:
            p = parse_r(get(f"{base}/{fn}"))
            time.sleep(0.3)
            if p:
                st[k] = {"file": fn, "short": sn, "unit": p[0], "periods": p[1], "rows": p[2]}
    d = {"fy": q, "acc": ACC[q], "statements": st}
    json.dump(d, open(dest, "w"), ensure_ascii=False, indent=1)
    return d


IS_MAP = [("us-gaap_Revenues", "营业收入 Total revenues", False),
          ("us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax", "营业收入 Total revenues", False),
          ("us-gaap_CostOfRevenue", "营业成本 Total cost of revenues", True),
          ("us-gaap_GrossProfit", "毛利 Gross profit", False),
          ("us-gaap_ResearchAndDevelopmentExpense", "研发费用 Research and development", True),
          ("us-gaap_SellingGeneralAndAdministrativeExpense", "销售及行政费用 Selling, general and administrative", True),
          ("tsla_RestructuringAndOtherExpenses", "重组及其他 Restructuring and other", True),
          ("us-gaap_OperatingExpenses", "经营费用合计 Total operating expenses", True),
          ("us-gaap_OperatingIncomeLoss", "经营利润 Income from operations", False),
          ("us-gaap_InvestmentIncomeInterest", "利息收入 Interest income", False),
          ("us-gaap_InterestExpenseNonoperating", "利息费用 Interest expense", False),
          ("us-gaap_InterestExpense", "利息费用 Interest expense", False),
          ("us-gaap_OtherNonoperatingIncomeExpense", "其他收入(费用)净额 Other income (expense), net", False),
          ("us-gaap_IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
           "税前利润 Income before income taxes", False),
          ("us-gaap_IncomeTaxExpenseBenefit", "所得税 Provision for income taxes", True),
          ("us-gaap_ProfitLoss", "净利润(含少数股东) Net income", False),
          ("us-gaap_NetIncomeLossAttributableToNoncontrollingInterest", "少数股东损益 NCI", False),
          ("us-gaap_NetIncomeLoss", "归母净利润 Net income attributable to common stockholders", False)]
CF_MAP = [("us-gaap_ProfitLoss", "净利润 Net income"),
          ("tsla_DepreciationAmortizationAndImpairment", "折旧摊销及减值 D&A and impairment"),
          ("us-gaap_ShareBasedCompensation", "股份支付 Stock-based compensation"),
          ("us-gaap_NetCashProvidedByUsedInOperatingActivities", "经营活动现金流净额 Net cash from operating activities"),
          ("us-gaap_PaymentsToAcquirePropertyPlantAndEquipment", "购建固定资产(capex) Purchases of property and equipment"),
          ("tsla_PaymentsToAcquireEquityMethodInvestments", "购买 SpaceX 股权 Purchase of SpaceX equity investment"),
          ("us-gaap_PaymentsToAcquireInvestments", "购买短期投资 Purchases of short-term investments"),
          ("us-gaap_NetCashProvidedByUsedInInvestingActivities", "投资活动现金流净额 Net cash from investing activities"),
          ("us-gaap_ProceedsFromIssuanceOfDebt", "发债所得 Proceeds from issuances of debt"),
          ("us-gaap_RepaymentsOfConvertibleDebt", "偿还债务 Repayments of debt"),
          ("us-gaap_NetCashProvidedByUsedInFinancingActivities", "融资活动现金流净额 Net cash from financing activities")]
BS_MAP = [("us-gaap_CashAndCashEquivalentsAtCarryingValue", "现金及现金等价物 Cash and cash equivalents"),
          ("us-gaap_ShortTermInvestments", "短期投资 Short-term investments"),
          ("us-gaap_AccountsReceivableNetCurrent", "应收账款净额 Accounts receivable, net"),
          ("us-gaap_InventoryNet", "存货 Inventory"),
          ("us-gaap_AssetsCurrent", "流动资产合计 Total current assets"),
          ("us-gaap_PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
           "固定资产净额 Property, plant and equipment, net"),
          ("us-gaap_PropertyPlantAndEquipmentNet", "固定资产净额 Property, plant and equipment, net"),
          ("us-gaap_Assets", "资产总计 Total assets"),
          ("us-gaap_LiabilitiesCurrent", "流动负债合计 Total current liabilities"),
          ("us-gaap_Liabilities", "负债合计 Total liabilities"),
          ("tsla_LongTermDebtAndFinanceLeasesCurrent", "债务及租赁负债-流动 Debt and finance leases, current"),
          ("tsla_LongTermDebtAndFinanceLeasesNoncurrent", "债务及租赁负债-非流动 Debt and finance leases, non-current"),
          ("us-gaap_StockholdersEquity", "归母股东权益 Total stockholders' equity"),
          ("us-gaap_CommonStockSharesOutstanding", "期末流通股数(千股) Shares outstanding")]


# 分部（10-Q 损益表尾部的 srt_ProductOrServiceAxis 维度块）
SEG_MEMBERS = {
    "automotive revenues": "汽车板块",
    "automotive sales": "汽车销售",
    "automotive regulatory credits": "汽车监管积分",
    "automotive leasing": "汽车租赁",
    "energy generation and storage": "能源发电与储存",
    "services and other": "服务及其他",
}
SEG_REV_TAG = {"us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax", "us-gaap_Revenues"}
SEG_COST_TAG = {"us-gaap_CostOfRevenue", "us-gaap_CostOfGoodsAndServicesSold"}


def pick_segments(rows, ncol):
    """→ {(中文分部名, '收入'|'成本'): [各列值]}。维度块以 Axis 行或 [Member] 标签分隔。"""
    out, member = {}, None
    for r in rows:
        lab = r["label"].strip()
        if r["tag"].endswith("Axis") or lab.endswith("[Member]"):
            member = SEG_MEMBERS.get(lab.replace("[Member]", "").strip().lower())
            continue
        if not member:
            continue
        vals = [r["vals"][i] if i < len(r["vals"]) else None for i in range(ncol)]
        if not any(v is not None for v in vals):
            continue
        kind = "收入" if r["tag"] in SEG_REV_TAG else ("成本" if r["tag"] in SEG_COST_TAG else None)
        if kind:
            out.setdefault((member, kind), vals)
    return out


def pick(rows, mapping, col):
    out = {}
    for r in rows:
        v = r["vals"][col] if col < len(r["vals"]) else None
        if v is None:
            continue
        for item in mapping:
            tag, canon, neg = (item + (False,))[:3] if len(item) == 2 else item
            if r["tag"] == tag:
                out.setdefault(canon, (-v if neg else v))
                break
    return out


def main():
    q1, q2 = harvest("2026Q1"), harvest("2026Q2")
    col = {}
    data = {}
    # 损益：Q1 表两列 = 2026Q1 / 2025Q1；Q2 表四列 = 2026Q2 / 2025Q2 / 2026H1 / 2025H1
    for label, st, c in (("2026Q1", q1["statements"]["IS"], 0), ("2025Q1", q1["statements"]["IS"], 1),
                         ("2026Q2", q2["statements"]["IS"], 0), ("2025Q2", q2["statements"]["IS"], 1),
                         ("2026H1", q2["statements"]["IS"], 2), ("2025H1", q2["statements"]["IS"], 3)):
        rows = [r for r in st["rows"] if not r["tag"].endswith(("Abstract", "Axis"))]
        cut = next((i for i, r in enumerate(st["rows"]) if r["tag"].endswith("Axis")), len(st["rows"]))
        rows = [r for r in st["rows"][:cut] if not r["tag"].endswith(("Abstract", "Axis"))]
        data.setdefault(label, {}).update({k: v * SC for k, v in pick(rows, IS_MAP, c).items()})
    # 分部：Q1 表两列 = 2026Q1 / 2025Q1；Q2 表四列 = 2026Q2 / 2025Q2 / 2026H1 / 2025H1
    for st, cols in ((q1["statements"]["IS"], ["2026Q1", "2025Q1"]),
                     (q2["statements"]["IS"], ["2026Q2", "2025Q2", "2026H1", "2025H1"])):
        segs = pick_segments(st["rows"], len(cols))
        for (member, kind), vals in segs.items():
            row = f"【分部】{member}-{kind}"
            for i, lab in enumerate(cols):
                if vals[i] is not None:
                    data.setdefault(lab, {}).setdefault(row, vals[i] * SC)

    # 现金流：Q1 表两列 = 2026Q1 / 2025Q1；Q2 表两列 = 2026H1 / 2025H1（10-Q 现金流为年初至今累计）
    for label, st, c in (("2026Q1", q1["statements"]["CF"], 0), ("2025Q1", q1["statements"]["CF"], 1),
                         ("2026H1", q2["statements"]["CF"], 0), ("2025H1", q2["statements"]["CF"], 1)):
        cut = next((i for i, r in enumerate(st["rows"]) if r["tag"].endswith("Axis")), len(st["rows"]))
        rows = [r for r in st["rows"][:cut] if not r["tag"].endswith(("Abstract", "Axis"))]
        data.setdefault(label, {}).update({k: v * SC for k, v in pick(rows, CF_MAP, c).items()})
    # 资产负债表时点：2026-03-31 / 2026-06-30 / 2025-12-31
    for label, st, c in (("2026Q1末", q1["statements"]["BS"], 0), ("2026Q2末", q2["statements"]["BS"], 0),
                         ("2025年末", q2["statements"]["BS"], 1)):
        cut = next((i for i, r in enumerate(st["rows"]) if r["tag"].endswith("Axis")), len(st["rows"]))
        rows = [r for r in st["rows"][:cut] if not r["tag"].endswith(("Abstract", "Axis"))]
        got = pick(rows, BS_MAP, c)
        data.setdefault(label, {}).update({k: (v * SC if "股数" not in k else v * SC) for k, v in got.items()})

    errs, n = [], 0

    def eq(tag, a, b, tol=1000.0):
        nonlocal n
        if a is None or b is None:
            return
        n += 1
        if abs(a - b) > tol:
            errs.append(f"{tag}: {a:,.0f} vs {b:,.0f}")

    g = dict.get
    for p in ("2026Q1", "2025Q1", "2026Q2", "2025Q2", "2026H1", "2025H1"):
        d = data[p]
        eq(f"[{p}] 营收+成本=毛利", (g(d, "营业收入 Total revenues") or 0) + (g(d, "营业成本 Total cost of revenues") or 0),
           g(d, "毛利 Gross profit"))
        eq(f"[{p}] 毛利+经营费用=经营利润", (g(d, "毛利 Gross profit") or 0) + (g(d, "经营费用合计 Total operating expenses") or 0),
           g(d, "经营利润 Income from operations"))
        eq(f"[{p}] 经营利润+线下=税前", (g(d, "经营利润 Income from operations") or 0)
           + sum(g(d, k) or 0 for k in ("利息收入 Interest income", "利息费用 Interest expense",
                                        "其他收入(费用)净额 Other income (expense), net")),
           g(d, "税前利润 Income before income taxes"))
        eq(f"[{p}] 税前+所得税=净利", (g(d, "税前利润 Income before income taxes") or 0)
           + (g(d, "所得税 Provision for income taxes") or 0), g(d, "净利润(含少数股东) Net income"))
        eq(f"[{p}] 净利−少数股东=归母", (g(d, "净利润(含少数股东) Net income") or 0) - (g(d, "少数股东损益 NCI") or 0),
           g(d, "归母净利润 Net income attributable to common stockholders"))
    for k in ("营业收入 Total revenues", "毛利 Gross profit", "净利润(含少数股东) Net income"):
        eq(f"[2026] Q1+Q2=H1 {k}", (g(data["2026Q1"], k) or 0) + (g(data["2026Q2"], k) or 0), g(data["2026H1"], k))
        eq(f"[2025] Q1+Q2=H1 {k}", (g(data["2025Q1"], k) or 0) + (g(data["2025Q2"], k) or 0), g(data["2025H1"], k))

    # 分部勾稽：三分部收入/成本之和 = 总额；汽车分项和 = 汽车板块合计
    for p in ("2026Q1", "2025Q1", "2026Q2", "2025Q2", "2026H1", "2025H1"):
        d = data[p]
        parts = [d.get(f"【分部】{m}-收入") for m in ("汽车板块", "能源发电与储存", "服务及其他")]
        if all(v is not None for v in parts):
            eq(f"[{p}] 三分部收入和=总营收", sum(parts), d.get("营业收入 Total revenues"))
        cparts = [d.get(f"【分部】{m}-成本") for m in ("汽车板块", "能源发电与储存", "服务及其他")]
        if all(v is not None for v in cparts):
            eq(f"[{p}] 三分部成本和=总成本", -sum(cparts), d.get("营业成本 Total cost of revenues"))
        auto = [d.get(f"【分部】{m}-收入") for m in ("汽车销售", "汽车监管积分", "汽车租赁")]
        if all(v is not None for v in auto):
            eq(f"[{p}] 汽车分项和=汽车板块合计", sum(auto), d.get("【分部】汽车板块-收入"))

    print(f"── 中期勾稽：{n} 条，不通过 {len(errs)}")
    for e in errs:
        print("   ✗", e)
    if errs:
        print("\n❌ 校验未过 —— 不写出 CSV。")
        return 1

    cols = ["2026Q1", "2025Q1", "2026Q2", "2025Q2", "2026H1", "2025H1", "2026Q1末", "2026Q2末", "2025年末"]
    seg_rows = [f"【分部】{m}-{k}" for m in ("汽车板块", "汽车销售", "汽车监管积分", "汽车租赁",
                                          "能源发电与储存", "服务及其他") for k in ("收入", "成本")]
    rows_order = [c for _, c, *_ in IS_MAP] + seg_rows + [c for _, c in CF_MAP] + [c for _, c in BS_MAP]
    rows_order = list(dict.fromkeys(rows_order))
    with open(os.path.join(HERE, "中期财务-2026.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["单位:千美元(印刷为百万,×1000);利润表/现金流:费用与流出=负数;资产负债表按印刷原值;空=该期未列示"])
        w.writerow(["来源:10-Q 2026Q1(0001628280-26-026673) + 10-Q 2026Q2(0001628280-26-049270) 的 SEC 渲染报表 R*.htm"])
        w.writerow(["⚠️ 10-Q 现金流量表为**年初至今累计**口径:Q2 单季现金流公司未单独披露,故本表现金流只有 Q1 与 H1 两列"])
        w.writerow(["科目"] + cols)
        for r in rows_order:
            vals = [data.get(c, {}).get(r) for c in cols]
            if any(v is not None for v in vals):
                w.writerow([r] + ["" if v is None else ("0" if abs(v) < 1e-9 else f"{v:.0f}") for v in vals])
    print("✅ 中期财务-2026.csv 已写出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
