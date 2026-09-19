#!/usr/bin/env python3
"""FY2026 中期（Q1-Q3 10-Q）→ `中期财务-2026.csv` / `分部营收-中期2026.csv`。

## 为什么单独一张表、不并进年度三表

FY2026 尚未结束（Q4 要到 2026-11 才披露），把未完整财年的数并进年度序列会污染同比。
本表只放**本期累计**与**单季**两种口径，并在每行标清是哪一种。

## 口径声明（三轴逐项填死）

- **期间**：Disney 的 10-Q 同时给「3 Months Ended」与「Nine/Six Months Ended」两组列。
  本表两组都取，行名后缀标 `(单季)` / `(累计)`。
  🔴 **跨口径比较是本库最高发的错法** —— 单季数拿去跟累计数比同比。行名标死即为防此。
- **主体**：合并口径；归母 = `NetIncomeLoss`。
- **时点**：资产负债表为期末时点数（Q3 = 2026-06-27）。
- **可比性**：FY2026 各季与 FY2025 同期可比（列报未变）；与年度序列不可直接连线。
"""
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _harvest_rfiles as H                                     # noqa: E402
import _build_from_filings as B                                 # noqa: E402

QUARTERS = {
    "2026Q1": (1744489, "0001744489-26-000019", "2025-12-27"),
    "2026Q2": (1744489, "0001744489-26-000037", "2026-03-28"),
    "2026Q3": (1744489, "0001744489-26-000057", "2026-06-27"),
}
OUT = os.path.join(HERE, "_rfiles_q")


def harvest():
    os.makedirs(OUT, exist_ok=True)
    import time
    import xml.etree.ElementTree as ET
    for key, (cik, acc, _) in QUARTERS.items():
        dest = os.path.join(OUT, f"{key}.json")
        if os.path.exists(dest) and "--force" not in sys.argv:
            continue
        base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}"
        root = ET.fromstring(H.get(base + "/FilingSummary.xml"))
        time.sleep(0.3)
        found = {}
        for r in root.iter("Report"):
            sn = (r.findtext("ShortName") or "").strip()
            fn = (r.findtext("HtmlFileName") or "").strip()
            k = H.classify(sn) if fn else None
            if k and k not in found:
                found[k] = (fn, sn)
        st = {}
        for k, (fn, sn) in found.items():
            p = H.parse_r(H.get(f"{base}/{fn}"))
            time.sleep(0.3)
            if p:
                st[k] = {"file": fn, "short": sn, "unit": p[0],
                         "periods": p[1], "months": p[2], "rows": p[3]}
        json.dump({"key": key, "cik": cik, "acc": acc, "statements": st},
                  open(dest, "w"), ensure_ascii=False, indent=1)
        print(f"OK {key}: " + " ".join(
            f"{k}({len(v['rows'])}r,{len(v['periods'])}p,月长{sorted(set(v['months'])) if v['months'] else '?'})"
            for k, v in sorted(st.items())))


def build():
    # (列名, quarter_key, 该列要的期长月数 或 None=资产负债表时点)
    cols, data = [], {}
    for key in ("2026Q1", "2026Q2", "2026Q3"):
        p = os.path.join(OUT, f"{key}.json")
        if not os.path.exists(p):
            continue
        d = json.load(open(p))
        for kind in ("IS", "CF", "BS"):
            st = d["statements"].get(kind)
            if not st:
                continue
            periods, months = st["periods"], st.get("months") or []
            for i, per in enumerate(periods):
                if kind == "BS":
                    if i != 0:                       # 只要本期末那一列
                        continue
                    label, tagm = f"{key} 期末", None
                else:
                    m = months[i] if i < len(months) else None
                    if m is None:
                        continue
                    y = B.fy_of_period(per)
                    fy = "FY2026" if (y == 2026 or (y == 2025 and "Dec" in per)) else "FY2025"
                    # Q1 的「3 个月」即「本期累计」，不重复出两列
                    if key == "2026Q1" and m == 3:
                        label = f"{fy} Q1(单季=累计)"
                    else:
                        label = f"{fy} {key[-2:]}(单季)" if m == 3 else f"{fy} 截至{key[-2:]}(累计{m}个月)"
                    tagm = m
                if label not in cols:
                    cols.append(label)
                for r in st["rows"]:
                    tag, lab = r["tag"], r["label"]
                    for name, tags, _pats in B.CONCEPTS[kind]:
                        hit = any((t == tag) or (t.startswith("LBL:") and re.search(t[4:], lab, re.I))
                                  for t in tags if not t.startswith("DIM:"))
                        if not hit:
                            continue
                        v = r["vals"][i] if i < len(r["vals"]) else None
                        if v is not None:
                            data.setdefault(name, {}).setdefault(label, v)
                        break
    order = [n for kind in ("IS", "BS", "CF") for n, _, _ in B.CONCEPTS[kind]]
    seen, rows = set(), []
    for n in order:
        if n in data and n not in seen:
            seen.add(n)
            rows.append([n] + [B.fmt(data[n].get(c)) for c in cols])
    with open(os.path.join(HERE, "中期财务-2026.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["单位:百万美元(USD millions);费用/减项=负数。FY2026 Q1-Q3 来自三份 10-Q 的 "
                    "SEC 渲染报表(按 XBRL tag 归一)。"])
        w.writerow(["🔴 列名已标死**单季/累计**两种期间口径 —— 单季数与累计数不可互比;"
                    "FY2026 未完整结束(Q4 于 2026-11 披露),本表不并入年度序列。"])
        w.writerow(["科目"] + cols)
        w.writerows(rows)
    print(f"写出 中期财务-2026.csv（{len(rows)} 行 × {len(cols)} 列）")
    print("  列：" + " | ".join(cols))


def build_segments():
    """FY2026 中期分部营收/经营利润。口径 = FY2023 起的娱乐/体育/体验三分部。"""
    import _build_segments as S
    _, segs = S.era_of(2025)
    cols, rev, oi = [], {}, {}
    for key in ("2026Q1", "2026Q2", "2026Q3"):
        p = os.path.join(OUT, f"{key}.json")
        if not os.path.exists(p):
            continue
        st = json.load(open(p))["statements"].get("SEG")
        if not st:
            continue
        periods, months = st["periods"], st.get("months") or []
        for i, per in enumerate(periods):
            m = months[i] if i < len(months) else None
            if m is None:
                continue
            y = B.fy_of_period(per)
            fy = "FY2026" if (y == 2026 or (y == 2025 and "Dec" in per)) else "FY2025"
            if key == "2026Q1" and m == 3:
                label = f"{fy} Q1(单季=累计)"
            else:
                label = f"{fy} {key[-2:]}(单季)" if m == 3 else f"{fy} 截至{key[-2:]}(累计{m}个月)"
            if label not in cols:
                cols.append(label)
            seg = ""
            for r in st["rows"]:
                tag, lab, vals = r["tag"], r["label"], r["vals"]
                if (not tag or tag.endswith("Axis")) and all(v is None for v in vals):
                    seg = lab
                    continue
                if not seg or "|" in seg:
                    continue
                name = next((n for n, pat in segs + [S.ELIM]
                             if re.search(pat, seg.strip().lower())), None)
                if not name:
                    continue
                v = vals[i] if i < len(vals) else None
                if v is None:
                    continue
                (rev if tag in S.REV_TAGS else oi if tag in S.OI_TAGS else {}) \
                    .setdefault(name, {}).setdefault(label, v)
    names = [n for n, _ in segs] + [S.ELIM[0]]
    with open(os.path.join(HERE, "分部营收-中期2026.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["单位:百万美元。FY2026 Q1-Q3 分部营收与分部经营利润(娱乐/体育/体验三分部口径)。"
                    "列名已标死单季/累计,不可互比。"])
        w.writerow(["指标"] + cols)
        for n in names:
            if n in rev:
                w.writerow([f"营收·{n}"] + [B.fmt(rev[n].get(c)) for c in cols])
        for n in names:
            if n in oi:
                w.writerow([f"分部经营利润·{n}"] + [B.fmt(oi[n].get(c)) for c in cols])
    print(f"写出 分部营收-中期2026.csv（{len(cols)} 列）")


if __name__ == "__main__":
    harvest()
    build()
    build_segments()
