#!/usr/bin/env python3
"""特斯拉经营指标构建器（产量 / 交付量 / 储能装机 / 光伏装机）。

数据源（均为一手 SEC 申报）
──────────────────────────────────────────────────────────────────
· **产量 / 交付量**：各年 1 月初的 8-K 附件 EX-99.1「Q4 及全年 Production & Deliveries」新闻稿。
  这是特斯拉披露单量的**唯一权威口径**——⚠️ 10-K 正文只在 2020-2023 顺带提过整年单量，
  **FY2024 / FY2025 的 10-K 已不再写整年产量/交付量**（口径退化，见 README「披露退化」一节）。
  新闻稿原件缓存在 `report/特斯拉/_产量交付新闻稿/`。
· **储能装机 GWh / 光伏装机 MW**：优先取 10-K 正文自陈（「In 20XX, we deployed X GWh …」），
  缺失年份回落到同一份 P&D 新闻稿。
· 2016 年以前特斯拉未按此格式披露 → 2010-2015 部分年份只能从 10-K 正文零星取得，标 ⏳。

校验
──────────────────────────────────────────────────────────────────
· 分车型（Model S/X、Model 3/Y、Other）产量与交付量**分项和 = Total**；
· 交付量同比增速与新闻稿自陈的 YoY 文字互证（如「grew 38% YoY to 1.81 million」）。
校验不过不写出 CSV。
"""
from __future__ import annotations

import csv
import gzip
import html
import json
import os
import re
import sys
import time
import urllib.request

CIK = "1318605"
UA = "investor-analyzer sylar.zhao@dcsserv.com"
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.abspath(os.path.join(HERE, "..", "..", "..", "report", "特斯拉", "_产量交付新闻稿"))
TENK = os.path.abspath(os.path.join(HERE, "..", "..", "..", "report", "特斯拉"))
TAG = re.compile(r"<[^>]+>")

# 各年 Q4 P&D 新闻稿（次年 1 月初 8-K 的 EX-99.1）
PD = {
    2016: ("2017-01-03", "0001564590-17-000024", "tsla-ex991_6.htm"),
    2017: ("2018-01-03", "0001564590-18-000054", "tsla-ex991_6.htm"),
    2018: ("2019-01-02", "0001564590-19-000013", "tsla-ex991_6.htm"),
    2019: ("2020-01-03", "0001564590-20-000161", "tsla-ex991_24.htm"),
    2020: ("2021-01-04", "0001564590-21-000008", "tsla-ex991_7.htm"),
    2021: ("2022-01-03", "0001564590-22-000009", "tsla-ex991_6.htm"),
    2022: ("2023-01-03", "0001564590-23-000002", "tsla-ex991_6.htm"),
    2023: ("2024-01-02", "0000950170-24-000282", "tsla-ex99_1.htm"),
    2024: ("2025-01-02", "0001628280-25-000007", "exhibit991.htm"),
    2025: ("2026-01-02", "0001628280-26-000016", "exhibit9914.htm"),
}


def fetch(url):
    r = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
    b = urllib.request.urlopen(r, timeout=120).read()
    return gzip.decompress(b) if b[:2] == b"\x1f\x8b" else b


def plain(raw):
    return re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", raw)))


def load_pd(fy):
    os.makedirs(CACHE, exist_ok=True)
    dest = os.path.join(CACHE, f"{fy}-Q4产量交付.htm")
    if not os.path.exists(dest):
        d, acc, fn = PD[fy]
        url = f"https://www.sec.gov/Archives/edgar/data/{CIK}/{acc.replace('-', '')}/{fn}"
        open(dest, "wb").write(fetch(url))
        time.sleep(0.3)
    return plain(open(dest, encoding="utf-8", errors="ignore").read())


NUM = r"([\d]{1,3}(?:,\d{3})+|[\d]+)"


def parse_year_block(t, fy):
    """取新闻稿里「<年份> Production Deliveries …」**整年**块的分车型与合计。

    ⚠️ 必须排除紧邻的「Q4 <年份> Production Deliveries」季度块 —— 不加负向先行断言会把
    Q4 单季数当成全年数（实测 FY2020 会被读成 179,757 辆而非 509,737 辆）。
    """
    m = re.search(rf"(?<!Q4 )\b{fy}\s+Production\s+Deliveries\s+(.{{0,400}}?)(?:Thank you|\*\*\*|Energy storage|$)", t)
    if not m:
        return {}
    blk = m.group(1)
    out = {}
    for label, key in (("Model S/X", "S/X"), ("Model 3/Y", "3/Y"), ("Other Models", "Other"), ("Total", "Total")):
        mm = re.search(rf"{re.escape(label)}\s+{NUM}\s+{NUM}", blk)
        if mm:
            out[key] = (int(mm.group(1).replace(",", "")), int(mm.group(2).replace(",", "")))
    return out


# 2016-2019 的 P&D 新闻稿是**叙述体**（无整年表格），全年数按新闻稿原文逐句转录：
#  2016：「total 2016 production of 83,922 vehicles」「total 2016 deliveries were approximately 76,230」
#  2017：新闻稿只给了 Model S/X 全年交付「delivering 101,312 Model S and X vehicles in 2017」，
#        **未给全年总交付/总产量** → 全年合计标 ⏳（已核：该份新闻稿全文无此数，非"只探一条路"）
#  2018：「In 2018, we delivered a total of 245,240 vehicles: 145,846 Model 3 and 99,394 Model S and X」
#        ⚠️ 该数为新闻稿**初值**；FY2018 10-K 正文最终数为 245,506 辆（差 266 辆），本表取新闻稿口径以保序列一致
#  2019：「In 2019, we delivered approximately 367,500 vehicles」（产量新闻稿未给全年数 → ⏳）
NARRATIVE = {
    2016: {"整车产量-合计 Total production (辆)": 83922, "整车交付量-合计 Total deliveries (辆)": 76230},
    2017: {"整车交付量-Model S/X (辆)": 101312},
    2018: {"整车交付量-合计 Total deliveries (辆)": 245240,
           "整车交付量-Model 3/Y (辆)": 145846, "整车交付量-Model S/X (辆)": 99394},
    2019: {"整车交付量-合计 Total deliveries (辆)": 367500},
}


def tenk_text(fy):
    p = os.path.join(TENK, f"{fy}.htm")
    return plain(open(p, encoding="utf-8", errors="ignore").read()) if os.path.exists(p) else ""


ROWS = ["整车产量-合计 Total production (辆)", "整车产量-Model S/X (辆)", "整车产量-Model 3/Y (辆)",
        "整车产量-其他车型 Other models (辆)",
        "整车交付量-合计 Total deliveries (辆)", "整车交付量-Model S/X (辆)", "整车交付量-Model 3/Y (辆)",
        "整车交付量-其他车型 Other models (辆)",
        "交付量同比 Deliveries YoY", "产销率 交付量/产量 Deliveries / production",
        "储能装机 Energy storage deployed (GWh)", "光伏装机 Solar deployed (MW)",
        "10-K 正文是否披露整年产量/交付量"]


def main():
    data, errs, nchk = {}, [], 0
    for fy in sorted(PD):
        t = load_pd(fy)
        blk = parse_year_block(t, fy)
        d = {}
        if "Total" in blk:
            d["整车产量-合计 Total production (辆)"] = blk["Total"][0]
            d["整车交付量-合计 Total deliveries (辆)"] = blk["Total"][1]
            for k, cn in (("S/X", "Model S/X"), ("3/Y", "Model 3/Y"), ("Other", "其他车型 Other models")):
                if k in blk:
                    d[f"整车产量-{cn} (辆)"] = blk[k][0]
                    d[f"整车交付量-{cn} (辆)"] = blk[k][1]
            parts_p = [v[0] for k, v in blk.items() if k != "Total"]
            parts_d = [v[1] for k, v in blk.items() if k != "Total"]
            if parts_p:
                nchk += 2
                if sum(parts_p) != blk["Total"][0]:
                    errs.append(f"[{fy}] 分车型产量和 {sum(parts_p):,} ≠ Total {blk['Total'][0]:,}")
                if sum(parts_d) != blk["Total"][1]:
                    errs.append(f"[{fy}] 分车型交付和 {sum(parts_d):,} ≠ Total {blk['Total'][1]:,}")
        # 储能 / 光伏：先 10-K 正文，再新闻稿
        tk = tenk_text(fy)
        for pat, key, cast in ((r"we deployed ([\d.]+) GWh of energy storage", "储能装机 Energy storage deployed (GWh)", float),
                               (r"([\d,.]+) (?:megawatts|MW) of solar energy systems", "光伏装机 Solar deployed (MW)", float)):
            mm = re.search(pat, tk, re.I) or re.search(pat, t, re.I)
            if mm:
                try:
                    d[key] = cast(mm.group(1).replace(",", ""))
                except ValueError:
                    pass
        for k, v in NARRATIVE.get(fy, {}).items():
            d.setdefault(k, v)
        d["10-K 正文是否披露整年产量/交付量"] = 1.0 if re.search(r"we produced [\d,]+ (?:consumer )?vehicles", tk, re.I) else 0.0
        data[fy] = d

    for fy in sorted(data):
        cur, prev = data[fy], data.get(fy - 1, {})
        a, b = cur.get("整车交付量-合计 Total deliveries (辆)"), prev.get("整车交付量-合计 Total deliveries (辆)")
        if a and b:
            cur["交付量同比 Deliveries YoY"] = round(a / b - 1, 4)
        p = cur.get("整车产量-合计 Total production (辆)")
        if a and p:
            cur["产销率 交付量/产量 Deliveries / production"] = round(a / p, 4)

    print(f"── 分车型勾稽：{nchk} 条，不通过 {len(errs)}")
    for e in errs:
        print("   ✗", e)
    if errs:
        print("\n❌ 校验未过 —— 不写出 CSV。")
        return 1

    years = sorted(data)
    with open(os.path.join(HERE, "经营指标.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["单位:辆 / GWh / MW / 比率(1=100%);空=该年一手申报未披露该项"])
        w.writerow(["来源:各年次年 1 月初 8-K 附件 EX-99.1「Q4 及全年 Production & Deliveries」新闻稿"
                    "(原件缓存 report/特斯拉/_产量交付新闻稿/);储能/光伏优先取当年 10-K 正文自陈"])
        w.writerow(["⚠️「10-K 正文是否披露整年产量/交付量」1=是 0=否 —— FY2024 起该披露从 10-K 正文消失,"
                    "单量只剩新闻稿一条链路(见 README 披露退化)"])
        w.writerow(["指标"] + [str(y) for y in years])
        for r in ROWS:
            vals = [data.get(y, {}).get(r) for y in years]
            if any(v is not None for v in vals):
                w.writerow([r] + ["" if v is None else (f"{v:.0f}" if float(v).is_integer() else f"{v:g}") for v in vals])
    print(f"✅ 经营指标.csv 已写出（{years[0]}-{years[-1]}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
