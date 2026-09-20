#!/usr/bin/env python3
"""「分部经营利润 → 税前利润」调节表 → `分部调节表.csv`（FY2011-FY2025）。

## 为什么必须单独建这张表

不建它，「分部经营利润合计」与「税前利润」之间那一大块就只能**从税前利润倒挤**，
而倒挤出来的是一个把三样东西混在一起的数（FY2025 实测倒挤 −3,719）：

| 真实科目 | FY2025 |
|---|---|
| 公司总部及未分配费用 Corporate and unallocated shared expenses | −1,646 |
| **TFCF 与 Hulu 并购无形资产摊销** | −1,576 |
| 已含在分部利润内的权益法收益调整（506 移出、295 移入、9 防重复） | ≈ −497 |

**三者性质完全不同**：第一项是真·运营开销；第二项是 2019 年福克斯交易与 Hulu 收购的
**购买法会计产物**（逐年递减、与当期经营无关）；第三项只是口径搬家。
把它们叫成「总部成本」会让读者以为 Disney 每年有 37 亿的总部开销，实际只有 16 亿。

## 数据位置（两个时代不同）

- **FY2021-FY2025**：10-K 有独立的 `Reconciliation of Segment Operating Income to
  Income before Income Taxes (Details)` 报表 → `_rfiles/<fy>.json` 的 `REC`。
- **FY2011-FY2020**：没有独立报表，调节项直接排在分部表里 → 同一 JSON 的 `SEG`。
"""
import csv
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
RDIR = os.path.join(HERE, "_rfiles")

# (CSV 行名, 标签正则)。按**非维度行**（尚未进入任何分部轴上下文）匹配。
CONCEPTS = [
    ("分部经营利润合计 Segment Operating Income", r"^segment operating income"),
    ("公司总部及未分配费用 Corporate and unallocated shared expenses",
     r"^corporate and unallocated shared expense"),
    ("权益法投资收益(调节口径) Equity in the income of investees",
     r"^equity in the income of investees$"),
    ("重组及减值 Restructuring and impairment charges",
     r"^restructuring and impairment charges$"),
    ("其他收入(支出)净额 Other income (expense), net", r"^other income.?\(?expense\)?"),
    ("利息支出净额 Interest expense, net", r"^(net )?interest expense"),
    ("TFCF与Hulu并购无形摊销 TFCF and Hulu acquisition amortization",
     r"^tfcf and hulu acquisition amortization"),
    ("印度合资权益法损益 India JV equity loss", r"^india joint venture$"),
    ("= 税前利润 Income before income taxes",
     r"^income (from continuing operations )?before income taxes"),
]


def fy_of(p):
    m = re.search(r"\b((?:19|20)\d\d)\b", p)
    return int(m.group(1)) if m else None


def main():
    data, notes = {}, []
    for f in sorted(os.listdir(RDIR)):
        if not f.endswith(".json"):
            continue
        d = json.load(open(os.path.join(RDIR, f)))
        key = int(d["key"])
        st = d["statements"].get("REC") or d["statements"].get("SEG")
        if not st:
            continue
        src = "REC" if d["statements"].get("REC") else "SEG"
        periods, months = st["periods"], st.get("months") or []
        col = None
        for i, p in enumerate(periods):
            if months and months[i] != 12:
                continue
            if fy_of(p) == key:
                col = i
        if col is None:
            continue
        seg_ctx = ""
        for r in st["rows"]:
            tag, lab, vals = r["tag"], r["label"].strip().lower(), r["vals"]
            # 分部轴上下文一旦开始，后面的同名行是分部内的拆分，不是调节项
            if (not tag or tag.endswith("Axis")) and all(v is None for v in vals):
                seg_ctx = lab
            if seg_ctx and "india" not in seg_ctx:
                continue
            for name, pat in CONCEPTS:
                if not re.search(pat, lab):
                    continue
                v = vals[col] if col < len(vals) else None
                if v is not None:
                    data.setdefault(name, {}).setdefault(key, v)
                break
        notes.append(f"FY{key} ← {src}")

    fys = sorted({y for kv in data.values() for y in kv})
    with open(os.path.join(HERE, "分部调节表.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["单位:百万美元(USD millions);减项=负数。"
                    "「分部经营利润合计 → 税前利润」的调节，取自各年 10-K 的分部附注。"])
        w.writerow(["🔴 不要把「公司总部及未分配费用」与「TFCF与Hulu并购无形摊销」混成一个数 —— "
                    "前者是运营开销，后者是 2019 年福克斯交易与 Hulu 收购的购买法会计产物(逐年递减)。"
                    "从税前利润倒挤会把两者连同权益法口径搬家一起混在一起。"])
        w.writerow(["科目"] + [str(y) for y in fys])
        for name, _ in CONCEPTS:
            if name not in data:
                continue
            row = [name] + [(f"{data[name][y]:.0f}" if y in data[name] else "") for y in fys]
            if any(row[1:]):
                w.writerow(row)
    print("写出 分部调节表.csv  " + " ".join(notes))

    # 自检：调节链是否配平（FY2021+ 有独立 REC 表的年份）
    print("\n配平自检（分部利润 + 各调节项 = 税前利润）：")
    for y in fys:
        def g(n):
            return data.get(n, {}).get(y)
        parts = [g(n) for n, _ in CONCEPTS[:-1]]
        pre = g("= 税前利润 Income before income taxes")
        if pre is None or parts[0] is None:
            continue
        s = sum(p for p in parts if p is not None)
        print(f"  FY{y}: 合计 {s:>8,.0f} vs 税前 {pre:>8,.0f}  差 {s-pre:>7,.0f}"
              + ("  ✅" if abs(s - pre) <= 1 else "  ← 差额=已含在分部利润内的权益法收益等口径搬家"))


if __name__ == "__main__":
    main()
