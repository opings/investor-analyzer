#!/usr/bin/env python3
"""成本构成 → `成本构成.csv`：把「按功能列的成本」拆成「按性质能看出来的部分」。

## 为什么需要这张表

Disney 利润表**按功能**列成本：服务成本 / 产品成本 / SG&A / 折旧摊销。
**「内容摊销多少、折旧多少、人工多少」在利润表上一个都看不到。**
本表把三个附注里能取到的性质拆分归集到一处：

| 能取到 | 来源 | 说明 |
|---|---|---|
| **内容成本摊销**（自制 / 授权版权） | `Amortization of Produced and Licensed Content Costs` 附注 | FY2025 是**可识别的最大单项成本**，主要计入「服务成本」 |
| **折旧** 与 **无形资产摊销**（含 TFCF/Hulu 并购部分） | `Capital Expenditures, Depreciation and Amortization by Segment` 附注 | 两者合计 = 利润表「折旧与摊销」行 |
| **分部折旧 / 分部资本开支** | 同上 | 看重资产压在哪个分部 |

⚠️ **取不到的**：**人工成本金额公司不披露**（美国 GAAP 不强制按性质列报）。
只有员工人数与定性描述（体验分部的成本构成以 operating labor 打头）。
**不要凭人数去估人工成本** —— 本库对此一律标 ⏳。

## 数据位置（两个时代不同）

- **FY2021-FY2025**：10-K 有独立的 `Capital Expenditures, Depreciation and Amortization
  by Segment (Details)` 报表 → `_rfiles/<fy>.json` 的 `CAPDA`。
- **FY2011-FY2020**：这些行直接排在分部表里 → 同一 JSON 的 `SEG`。
- **内容摊销**：`AMORT`，FY2020 起（ASU 2019-02 改变列报后才有此表）。
"""
import csv
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
RDIR = os.path.join(HERE, "_rfiles")


def fy_of(p):
    m = re.search(r"\b((?:19|20)\d\d)\b", p)
    return int(m.group(1)) if m else None


def col_of(st, key):
    periods, months = st["periods"], st.get("months") or []
    for i, p in enumerate(periods):
        if months and months[i] != 12:
            continue
        if fy_of(p) == key:
            return i
    return None


# 内容摊销（AMORT 表）：(CSV 行名, 维度上下文正则 或 None, 标签正则)
# ⚠️ 自制内容的「单独变现 / 组合变现」两档挂在 dis_MonetizationStrategyAxis 维度下，
#    行标签与上面那条合计行**同名**，只能靠维度上下文区分。
AMORT_ROWS = [
    ("内容成本摊销合计 Total produced and licensed content", None,
     r"^amortization of produced and licensed content"),
    ("  自制内容摊销 Produced content", None, r"^amortization of produced content costs$"),
    ("    其中:单独变现 Monetized individually", r"monetized individually",
     r"^amortization of produced content costs$"),
    ("    其中:组合变现 Monetized as a group", r"monetized as a group",
     r"^amortization of produced content costs$"),
    ("  授权节目版权摊销 Licensed programming rights", None,
     r"^amortization of licensed television and programming rights"),
]

# 折旧/摊销/资本开支（CAPDA 或 SEG 表）：(CSV 行名, 分部上下文正则 或 None=非维度行, 标签正则)
CAPDA_ROWS = [
    ("折旧 Depreciation expense", None, r"^depreciation expense$"),
    ("无形资产摊销 Amortization of intangible assets", None,
     r"^amortization of intangible assets$"),
    ("  其中:TFCF与Hulu并购无形 TFCF and Hulu", r"tfcf and hulu",
     r"^amortization of intangible assets$"),
    ("资本开支合计 Capital expenditures", None, r"^capital expenditures$"),
    ("  分部折旧:娱乐 Entertainment", r"^entertainment segment$", r"^depreciation expense$"),
    ("  分部折旧:体育 Sports", r"^sports segment$", r"^depreciation expense$"),
    ("  分部折旧:体验-国内 Experiences Domestic", r"experiences segment \| domestic",
     r"^depreciation expense$"),
    ("  分部折旧:体验-国际 Experiences Intl", r"experiences segment \| international",
     r"^depreciation expense$"),
    ("  分部折旧:公司总部 Corporate", r"^corporate$", r"^depreciation expense$"),
    ("  分部资本开支:娱乐 Entertainment", r"^entertainment segment$", r"^capital expenditures$"),
    ("  分部资本开支:体育 Sports", r"^sports segment$", r"^capital expenditures$"),
    ("  分部资本开支:体验-国内 Experiences Domestic", r"experiences segment \| domestic",
     r"^capital expenditures$"),
    ("  分部资本开支:体验-国际 Experiences Intl", r"experiences segment \| international",
     r"^capital expenditures$"),
    ("  分部资本开支:公司总部 Corporate", r"^corporate$", r"^capital expenditures$"),
]


def scan(st, key, rows_spec, data):
    col = col_of(st, key)
    if col is None:
        return
    ctx = ""
    for r in st["rows"]:
        tag, lab, vals = r["tag"], r["label"].strip().lower(), r["vals"]
        if (not tag or tag.endswith("Axis")) and all(v is None for v in vals):
            ctx = lab
            continue
        for name, ctx_pat, lab_pat in rows_spec:
            if not re.search(lab_pat, lab):
                continue
            if ctx_pat is None:
                if ctx:                      # 要非维度行，但已进入分部上下文 → 跳过
                    continue
            elif not re.search(ctx_pat, ctx):
                continue
            v = vals[col] if col < len(vals) else None
            if v is not None:
                data.setdefault(name, {}).setdefault(key, v)
            break


def content_spend():
    """内容**支出**（不是摊销）——只在 MD&A 正文的滚动表里，没有独立 R 报表，故从正文抽。

    🔴 为什么必须单列：内容支出走**经营活动**，既不在资本开支里、其摊销也不在利润表
    「折旧与摊销」行里。只看 capex 或只看 D&A，都会完全看不到 Disney 最大的那条投资腿。
    """
    import html as _h
    out = {}
    for fy in range(2020, 2026):
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))),
                         "report", "Disney", f"{fy}.htm")
        if not os.path.exists(p):
            continue
        raw = open(p, "rb").read().decode("utf-8", "ignore")
        raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
        t = re.sub(r"\s+", " ", _h.unescape(re.sub(r"<[^>]+>", " ", raw)))
        m = re.search(r"Spending:\s*Licensed programming and rights\s+([\d,]+)\s+([\d,]+)\s+"
                      r"Produced content\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)", t)
        if not m:
            continue
        n = [float(x.replace(",", "")) for x in m.groups()]
        # 列序：本年/上年 × (授权, 自制, 合计)
        for i, y in enumerate((fy, fy - 1)):
            out.setdefault("  内容支出-授权节目与版权 Licensed programming & rights", {})[y] = n[i]
            out.setdefault("  内容支出-自制内容 Produced content", {})[y] = n[2 + i]
            out.setdefault("内容支出合计 Total content spend", {})[y] = n[4 + i]
    return out


def load_is():
    rows = list(csv.reader(open(os.path.join(HERE, "利润表.csv"))))
    h = next(r for r in rows if r and r[0] == "科目")
    ys = [int(x) for x in h[1:]]
    out = {}
    for r in rows:
        if not r or r[0] == "科目" or r[0].startswith(("单位", "各年")):
            continue
        out[r[0].strip()] = {y: (float(v) if v else None) for y, v in zip(ys, r[1:])}
    return out


def main():
    IS = load_is()
    data = {}
    for f in sorted(os.listdir(RDIR)):
        if not f.endswith(".json"):
            continue
        d = json.load(open(os.path.join(RDIR, f)))
        key = int(d["key"])
        if d["statements"].get("AMORT"):
            scan(d["statements"]["AMORT"], key, AMORT_ROWS, data)
        capda = d["statements"].get("CAPDA") or d["statements"].get("SEG")
        if capda:
            scan(capda, key, CAPDA_ROWS, data)

    def isline(k, y):
        # ⚠️ 利润表 CSV 的子项行名带前导空格（缩进层级），load_is 已 strip，
        #    这里查表也必须 strip，否则「  服务成本」永远匹配不上 → 整片功能拆分为空。
        k = k.strip()
        for kk, v in IS.items():
            if kk.startswith(k):
                return v.get(y)

    fys = sorted({y for kv in list(data.values()) + list(content_spend().values())
                  for y in kv if 2011 <= y <= 2025})
    out = []
    out.append(("── 按功能（利润表原样） ──", {}))
    for lbl, k in [("总成本及费用 Total costs and expenses", "总成本及费用"),
                   ("  服务成本 Cost of services", "  服务成本"),
                   ("  产品成本 Cost of products", "  产品成本"),
                   ("  销售及管理费用 SG&A", "  销售及管理费用"),
                   ("  折旧与摊销 D&A", "  折旧与摊销")]:
        out.append((lbl, {y: isline(k, y) for y in fys}))
    cs = content_spend()
    out.append(("── 内容：支出 vs 摊销（支出走经营活动，两者都不在 capex 与 D&A 行里）──", {}))
    for name in ("内容支出合计 Total content spend",
                 "  内容支出-授权节目与版权 Licensed programming & rights",
                 "  内容支出-自制内容 Produced content"):
        if name in cs:
            out.append((name, cs[name]))
    for name, _, _ in AMORT_ROWS:
        if name in data:
            out.append((name, data[name]))
    tot = data.get("内容成本摊销合计 Total produced and licensed content", {})
    out.append(("内容摊销÷总成本及费用%", {
        y: tot[y] / abs(isline("总成本及费用", y)) * 100
        for y in fys if y in tot and isline("总成本及费用", y)}))
    for name, _, _ in CAPDA_ROWS:
        if name in data:
            out.append((name, data[name]))

    with open(os.path.join(HERE, "成本构成.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["单位:百万美元(USD millions);比率行为%。利润表**按功能**列成本，"
                    "本表把附注里能取到的**按性质**拆分归集到一处。"])
        w.writerow(["🔴 ⏳ **人工成本金额公司不披露**（美国 GAAP 不强制按性质列报）——"
                    "只有员工人数与定性描述。**不要凭人数估人工成本。**"
                    "内容摊销为附注口径、主要计入「服务成本」；折旧+无形摊销合计 = 利润表「折旧与摊销」行。"])
        w.writerow(["科目"] + [str(y) for y in fys])
        for name, kv in out:
            if not kv:
                w.writerow([name] + [""] * len(fys))
                continue
            row = [name] + [(f"{kv[y]:.1f}".rstrip("0").rstrip(".") if y in kv and kv[y] is not None
                             else "") for y in fys]
            if any(row[1:]):
                w.writerow(row)
    print(f"写出 成本构成.csv（{len(fys)} 年）")

    print("\n自检：折旧 + 无形摊销 = 利润表「折旧与摊销」行？")
    for y in fys:
        dep = data.get("折旧 Depreciation expense", {}).get(y)
        amo = data.get("无形资产摊销 Amortization of intangible assets", {}).get(y)
        da = isline("  折旧与摊销", y)
        if None in (dep, amo, da):
            continue
        print(f"  FY{y}: {dep:,.0f} + {amo:,.0f} = {dep+amo:,.0f} vs 利润表 {abs(da):,.0f}"
              + ("  ✅" if abs(dep + amo - abs(da)) <= 1 else "  ❌"))


if __name__ == "__main__":
    main()
