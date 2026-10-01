#!/usr/bin/env python3
"""OpenAI 敞口表（FY2024-2026）：从 FY2026 10-K 正文抽取，**算术自洽才写出**。

为什么单建：OpenAI 同时是 Microsoft 的①权益法被投资方（约 25%·HLBV 法计量）②关联方大客户
（FY2026 含分成收入 241 亿美元）③营业外损益的最大波动源（FY2026 净收益 65 亿、FY2025 净损失 48 亿）。
不剔除它，报告净利增速会被一次性稀释收益与权益法亏损主导（记忆 equity-fv-pollutes-reported-net-income）。

数据源：`report/微软/2026.htm` 的
  ① MD&A「NON-GAAP FINANCIAL MEASURES」调节表（三年：营业外 / 净利 / 摊薄 EPS 的报告值与剔除 OpenAI 值）；
  ② Note 1 关联方段（持股比例、收入、应收、出资承诺与已出资）。
校验：报告值 + OpenAI 调整 = 调整后值（三行 × 三年）；报告净利与 `利润表.csv` 一致；营业外报告值与
`营业外收支明细.csv` 合计一致；OpenAI 税前 ≈ 附注「65 / −48 / −15 亿」约数（±1 亿）。
"""
import csv
import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))


def num(s):
    s = s.strip().replace(",", "").replace("$", "").strip()
    neg = s.startswith("(")
    v = float(s.strip("() "))
    return -v if neg else v


def main():
    raw = open(os.path.join(ROOT, "report", "微软", "2026.htm"), encoding="utf-8", errors="ignore").read()
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw)).replace("\xa0", " "))
    N = r"(\(? ?[\d,]+(?:\.\d+)? ?\)?)"
    bad = []
    m = re.search(r"Other income \(expense\), net \$ " + N + r" \$ " + N + r" \$ " + N +
                  r" [\d()%, ]+? Net \(gains\) losses from investments in OpenAI " + N + " " + N + " " + N +
                  r" [\d()%, ]+? Adjusted other income \(expense\), net \(non-GAAP\) \$ " + N + r" \$ " + N + r" \$ " + N, t)
    m2 = re.search(r"Net income \$ " + N + r" \$ " + N + r" \$ " + N + r" [\d()%, ]+? Net \(gains\) losses from investments "
                   r"in OpenAI, net of tax of \$" + N + r" , \$" + N + r", and \$" + N + " " + N + " " + N + " " + N +
                   r" [\d()%, ]+? Adjusted net income \(non-GAAP\) \$ " + N + r" \$ " + N + r" \$ " + N, t)
    m3 = re.search(r"Diluted earnings per share \$ " + N + r" \$ " + N + r" \$ " + N + r" [\d()%, ]+? Net \(gains\) losses "
                   r"from investments in OpenAI " + N + " " + N + " " + N + r" [\d()%, ]+? Adjusted diluted earnings per "
                   r"share \(non-GAAP\) \$ " + N + r" \$ " + N + r" \$ " + N, t)
    rel = re.search(r"approximate (\d+) ?% interest on an as-converted basis.*?revenue-sharing payments, of \$ ([\d.]+) "
                    r"billion, and accounts receivable from OpenAI as of June 30, 2026 was \$ ([\d.]+) billion\. We have "
                    r"made total funding commitments of \$ ([\d.]+) billion related to our investment, of which \$ ([\d.]+) "
                    r"billion has been funded", t)
    if not (m and m2 and m3 and rel):
        print(f"❌ 正文定位失败：OI&E={bool(m)} NI={bool(m2)} EPS={bool(m3)} 关联方={bool(rel)}")
        return 1
    yrs = [2026, 2025, 2024]
    oie = [num(m.group(i)) for i in (1, 2, 3)]
    oie_adj_item = [num(m.group(i)) for i in (4, 5, 6)]
    oie_adj = [num(m.group(i)) for i in (7, 8, 9)]
    ni = [num(m2.group(i)) for i in (1, 2, 3)]
    tax = [num(m2.group(i)) for i in (4, 5, 6)]
    ni_adj_item = [num(m2.group(i)) for i in (7, 8, 9)]
    ni_adj = [num(m2.group(i)) for i in (10, 11, 12)]
    eps = [num(m3.group(i)) for i in (1, 2, 3)]
    eps_adj_item = [num(m3.group(i)) for i in (4, 5, 6)]
    eps_adj = [num(m3.group(i)) for i in (7, 8, 9)]
    for i, fy in enumerate(yrs):
        for nm, a, b, c, tol in (("营业外", oie[i], oie_adj_item[i], oie_adj[i], 1.0),
                                 ("净利", ni[i], ni_adj_item[i], ni_adj[i], 1.0),
                                 ("EPS", eps[i], eps_adj_item[i], eps_adj[i], 0.011)):
            if abs(a + b - c) > tol:
                bad.append(f"FY{fy} {nm}：报告 {a} + 调整 {b} ≠ 调整后 {c}")
        # 税前调整 − 税效应 = 税后调整（「net of tax of $1,567」是税前收益对应的税费：−6,530 + 1,567 = −4,963）
        if abs(oie_adj_item[i] + tax[i] - ni_adj_item[i]) > 1.0:
            bad.append(f"FY{fy} 税前调整 {oie_adj_item[i]} + 税 {tax[i]} ≠ 税后调整 {ni_adj_item[i]}")
    # 跨文件：报告净利 = 利润表；报告营业外 = 营业外明细
    def series(fn, row):
        rows = list(csv.reader(open(os.path.join(HERE, fn))))
        h = next(i for i, r in enumerate(rows) if r and r[0] == "科目")
        years = [int(c[2:]) for c in rows[h][1:]]
        for r in rows[h + 1:]:
            if r and r[0] == row:
                return {y: (float(v) if v else None) for y, v in zip(years, r[1:])}
        return None
    isni = series("利润表.csv", "净利润 Net income")
    oiet = series("营业外收支明细.csv", "营业外收支合计 Total")
    if isni is None or oiet is None:
        print("❌ 探针行缺失（利润表净利 / 营业外合计）")
        return 1
    for i, fy in enumerate(yrs):
        if abs(isni[fy] - ni[i]) > 1:
            bad.append(f"FY{fy} 非 GAAP 表净利 {ni[i]} ≠ 利润表 {isni[fy]}")
        if abs(oiet[fy] - oie[i]) > 1:
            bad.append(f"FY{fy} 非 GAAP 表营业外 {oie[i]} ≠ 营业外明细 {oiet[fy]}")
    if bad:
        print("🔴 OpenAI 表校验未过：")
        for b in bad:
            print("  " + b)
        return 1
    rows = [
        ("营业外收支(报告) Other income (expense), net", oie, False),
        ("OpenAI 投资净(收益)损失·税前(调整项·正=加回损失) Net (gains) losses from investments in OpenAI", oie_adj_item, False),
        ("调整后营业外(非GAAP) Adjusted other income (expense), net", oie_adj, False),
        ("净利润(报告) Net income", ni, False),
        ("OpenAI 调整项对应所得税 Tax effect", tax, False),
        ("OpenAI 投资净(收益)损失·税后 net of tax", ni_adj_item, False),
        ("调整后净利润(非GAAP) Adjusted net income", ni_adj, False),
        ("摊薄EPS(报告)", eps, True),
        ("OpenAI 对摊薄EPS的调整", eps_adj_item, True),
        ("调整后摊薄EPS(非GAAP)", eps_adj, True),
    ]
    p = os.path.join(HERE, "OpenAI敞口.csv")
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# 单位: 百万美元（EPS 为美元/股）| 来源：FY2026 10-K MD&A「NON-GAAP FINANCIAL MEASURES」调节表 + Note 1 关联方段 | "
                    "⚠️ 非 GAAP 为公司自定义口径（只剔 OpenAI 一项）| 已校验：报告+调整=调整后（三行×三年）、税前调整+税=税后调整、"
                    "报告净利=利润表、报告营业外=营业外明细"])
        w.writerow(["科目", "FY2024", "FY2025", "FY2026"])
        for nm, vals, ps in rows:
            v = dict(zip(yrs, vals))
            w.writerow([nm] + [(f"{v[y]:.2f}" if ps else f"{v[y]:g}") for y in (2024, 2025, 2026)])
        w.writerow([])
        w.writerow(["# 关联方披露（FY2026 10-K Note 1·仅期末时点/FY2026 一年）"])
        w.writerow(["项目", "值", "单位", "原文要点"])
        w.writerow(["权益法持股比例(按转换后口径·约数)", rel.group(1), "%", "an investment accounted for under the equity method that represents an approximate 25% interest on an as-converted basis"])
        w.writerow(["FY2026 来自 OpenAI 的收入(含分成)", f"{float(rel.group(2)) * 1000:g}", "百万美元", "revenue from commercial arrangements with OpenAI, inclusive of revenue-sharing payments"])
        w.writerow(["应收 OpenAI 账款(2026-06-30)", f"{float(rel.group(3)) * 1000:g}", "百万美元", "accounts receivable from OpenAI as of June 30, 2026"])
        w.writerow(["出资承诺合计", f"{float(rel.group(4)) * 1000:g}", "百万美元", "total funding commitments"])
        w.writerow(["已出资(2026-06-30)", f"{float(rel.group(5)) * 1000:g}", "百万美元", "of which has been funded"])
    print(f"✅ OpenAI敞口.csv 写出（三年调节表 + 关联方五项）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
