#!/usr/bin/env python3
"""FY2027 中期（本财年 Q1 / Q2 10-Q）关键三表行 → `中期财务-FY2027.csv`，勾稽不过不写出。

- **中期数据独立成表·不并入年度序列**（年度序列止于 FY2026），避免年化 / 期间轴污染（记忆 google-alphabet-us-build）。
- 概念定义**复用** `_build_from_filings.py`（同一套 tag 映射，单一真相）；每列取自 10-Q 的 R 文件自身列。
- 期间轴（取数当场声明）：Q1 = 3 个月截至 2026-04-26；Q2 = 3 个月截至 2026-07-26；H1 = 6 个月截至 2026-07-26；
  对比列 = 同一份 10-Q 的上年同期列（两端同源）；资产负债表 = 2026-07-26 时点（对比 2026-01-25）。
"""
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _build_from_filings as B  # noqa: E402

import json  # noqa: E402

COLS = [  # (列名, 申报, 表, 期间截止日前缀, 期长月数 or None)
    ("FY2027Q1(3个月·截至2026-04-26)", "2027Q1", "IS", "Apr. 26, 2026", 3),
    ("FY2026Q1(3个月·截至2025-04-27·同表对比)", "2027Q1", "IS", "Apr. 27, 2025", 3),
    ("FY2027Q2(3个月·截至2026-07-26)", "2027Q2", "IS", "Jul. 26, 2026", 3),
    ("FY2026Q2(3个月·截至2025-07-27·同表对比)", "2027Q2", "IS", "Jul. 27, 2025", 3),
    ("FY2027H1(6个月·截至2026-07-26)", "2027Q2", "IS", "Jul. 26, 2026", 6),
    ("FY2026H1(6个月·截至2025-07-27·同表对比)", "2027Q2", "IS", "Jul. 27, 2025", 6),
    ("FY2027H1(6个月·截至2026-07-26)", "2027Q2", "CF", "Jul. 26, 2026", 6),
    ("FY2026H1(6个月·截至2025-07-27·同表对比)", "2027Q2", "CF", "Jul. 27, 2025", 6),
    ("2026-07-26 时点", "2027Q2", "BS", "Jul. 26, 2026", None),
    ("2026-01-25 时点(同表对比)", "2027Q2", "BS", "Jan. 25, 2026", None),
]


def one_col(st, prefix, months):
    for i, p in enumerate(st["periods"]):
        if p.startswith(prefix) and (months is None or not st["months"] or st["months"][i] == months):
            rows = [{"label": r["label"], "tag": r.get("tag"), "vals": [r["vals"][i] if i < len(r["vals"]) else None]}
                    for r in st["rows"]]
            return {"unit": st["unit"], "periods": ["Jan. 1, 2099"], "months": [12] if months else [], "rows": rows}
    return None


def main():
    books = {k: json.load(open(os.path.join(HERE, "_rfiles", f"{k}.json")))["statements"] for k in ("2027Q1", "2027Q2")}
    data, bad = {}, []
    for col, fk, stmt, prefix, months in COLS:
        st = one_col(books[fk][stmt], prefix, months)
        if st is None:
            bad.append((col, stmt, "列找不到"))
            continue
        for c in B.SPEC[stmt]:
            v = B.pick(st, c, "2099", "R")
            if v is not None:
                if B.SIGN.get(c[0]) == "neg":
                    v = -abs(v)
                data.setdefault((stmt, c[0]), {})[col] = v
    g = lambda s, n, c: data.get((s, n), {}).get(c)
    # 勾稽（默认容差 0）
    for col, fk, stmt, prefix, months in COLS:
        if stmt == "IS":
            R_, C_, GP = g("IS", "营业收入 Revenue", col), g("IS", "营业成本 Cost of revenue", col), g("IS", "毛利 Gross profit", col)
            OPX, OI = g("IS", "营业费用合计 Total operating expenses", col), g("IS", "营业利润 Operating income", col)
            NON, PBT = g("IS", "营业外收支合计(FY2016起印刷) Total other income (expense)", col), g("IS", "税前利润 Income before income tax", col)
            TAX, NI = g("IS", "所得税 Income tax expense (benefit)", col), g("IS", "净利润 Net income", col)
            for nm, dv in (("营收−成本=毛利", R_ - C_ - GP), ("毛利−营业费用=营业利润", GP - OPX - OI),
                           ("营业利润+营业外=税前", OI + NON - PBT), ("税前−所得税=净利", PBT - TAX - NI)):
                if abs(dv) > 1e-6:
                    bad.append((col, nm, dv))
        if stmt == "BS":
            TA, TCA = g("BS", "总资产 Total assets", col), g("BS", "流动资产合计 Total current assets", col)
            TL, TE = g("BS", "负债合计(FY2016起印刷) Total liabilities", col), g("BS", "股东权益合计 Total shareholders' equity", col)
            if None in (TA, TL, TE) or abs(TL + TE - TA) > 1e-6:
                bad.append((col, "负债+权益=总资产", (TA, TL, TE)))
            # 流动资产明细和 = 合计（第一版漏收 10-Q 新拆的「有价债券 / 上市权益证券」两个 tag，差 769 亿也照样写出——补闸）
            names = [c[0] for c in B.BS_CONCEPTS]
            ca = [n for n in names[:names.index("流动资产合计 Total current assets")]]
            s = sum(g("BS", n, col) or 0.0 for n in ca)
            if TCA is None or abs(s - TCA) > 1e-6:
                bad.append((col, "流动资产明细和=合计", (s, TCA)))
            nca = names[names.index("流动资产合计 Total current assets") + 1:names.index("总资产 Total assets")]
            s2 = TCA + sum(g("BS", n, col) or 0.0 for n in nca)
            if abs(s2 - TA) > 1e-6:
                bad.append((col, "流动+非流动=总资产", (s2, TA)))
        if stmt == "CF":
            o, i_, f = (g("CF", n, col) for n in ("经营活动现金流净额 Net cash from operating activities",
                                                 "投资活动现金流净额 Net cash from investing activities",
                                                 "融资活动现金流净额 Net cash from financing activities"))
            ch = g("CF", "现金净变动 Change in cash and cash equivalents", col)
            if None in (o, i_, f, ch) or abs(o + i_ + f - ch) > 1e-6:
                bad.append((col, "经营+投资+融资=现金净变动", (o, i_, f, ch)))
    # 跨申报：Q1 单季（2027Q1 10-Q）+ Q2 单季（2027Q2 10-Q）= H1（2027Q2 10-Q）。
    # 显式容差 ±1（百万）：Q1、Q2、H1 三个数分别在两份 10-Q 里各自按百万取整（实测营收 81,615+96,221=177,836 vs
    # H1 177,837；净利 58,321+59,688=118,009 vs 118,010）——源表舍入，不是转录错（R 文件机读、无人工转录环节）
    for n in ("营业收入 Revenue", "毛利 Gross profit", "营业利润 Operating income", "净利润 Net income"):
        q1, q2, h1 = (g("IS", n, c) for c in ("FY2027Q1(3个月·截至2026-04-26)", "FY2027Q2(3个月·截至2026-07-26)",
                                               "FY2027H1(6个月·截至2026-07-26)"))
        if None in (q1, q2, h1) or abs(q1 + q2 - h1) > 1.0 + 1e-6:
            bad.append(("跨申报", f"Q1+Q2=H1 {n}", (q1, q2, h1)))
    if bad:
        print(f"❌ 中期勾稽不通过 {len(bad)} 条（不写出）：")
        for b in bad:
            print("   ", b)
        return 1
    cols = []
    for col, *_ in COLS:
        if col not in cols:
            cols.append(col)
    with open(os.path.join(HERE, "中期财务-FY2027.csv"), "w", newline="") as f:
        f.write("# 单位: 百万美元(EPS 美元/股) | 本财年两份 10-Q(FY2027 Q1 截至 2026-04-26 / Q2 截至 2026-07-26)的 R 文件 | **独立成表·不并入年度序列** | "
                "对比列取同一份 10-Q 的上年同期列(两端同源) | 闸: 利润链 / 负债+权益=总资产 / 三段=净变动 / Q1+Q2=H1(跨申报)\n")
        w = csv.writer(f)
        w.writerow(["表", "科目"] + cols)
        for (stmt, n), vv in data.items():
            if all(vv.get(c) is None for c in cols):
                continue
            w.writerow([{"IS": "利润表", "BS": "资产负债表", "CF": "现金流量表"}[stmt], n] +
                       [B.fmt(vv.get(c), B.PS if "EPS" in n else B.M) for c in cols])
    print(f"✅ 写出 中期财务-FY2027.csv（{len(data)} 行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
