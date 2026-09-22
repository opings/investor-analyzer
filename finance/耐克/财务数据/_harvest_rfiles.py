#!/usr/bin/env python3
"""抓取 NIKE 各财年 10-K 的 SEC 渲染报表 R*.htm（= 该次申报自身的 as-reported 印刷报表）。

产出 `_rfiles/<财年>.json`：
  {"key":"2026","cik":320187,"acc":"...","statements":{
     "IS":{"file":"R3.htm","unit":"...","periods":[...],"months":[...],
           "rows":[{"label":..., "tag":"us-gaap_RevenueFrom...", "vals":[v0,v1,v2]}, ...]}}}

沿用 Disney / 特斯拉 `_harvest_rfiles.py` 的做法，三个已踩过的坑照搬：
① 空值单元格是 `<td class="text">&#xA0;</td>` —— **必须占位 None**，否则整行数值左移一列。
② 每行 `onclick="top.Show.showAR(this,'defref_us-gaap_XXX',...)"` 里带**该行的 XBRL tag** ——
   按 tag 归一比按印刷标签归一稳（NIKE 16 年里同一行的英文措辞改过多次，
   例如 "Revenues" ↔ "Total revenues"、FY2019 起收入行换成 ASC606 的
   `RevenueFromContractWithCustomerExcludingAssessedTax`）。
③ `class="fn"` 格按**内容**判：空 / 含 `[` 的脚注上标 → 丢弃；含数字 → 当数据列。
   （Disney 实证：一刀切丢弃会整整少一年数据，一刀切保留会让整行错位。）

## NIKE 特有

- **单 CIK 320187**，无 Disney 那种三 CIK 配对问题。
- **财年 5 月 31 日结束**：FY2026 = 2025-06-01 ~ 2026-05-31。R 文件里的期间日期是
  「May 31, 2026」，**年份即财年**，不需要像日历年公司那样跨年映射。
- **R*.htm 自 FY2011 10-K 起可得**（FY2010 那份只有 R*.xml、FilingSummary 里
  HtmlFileName 为空 —— 实测 `index.json` 里 0 个 R*.htm）。故 FY2010 及更早走
  `_parse_legacy.py` 文本/HTML 轨。
- FY2011 的 10-K 带 FY2009-2011 三年利润表 → 与 legacy 轨有 **3 年重叠**，
  构成倒锁链的锚（见 `_build_from_filings.py`）。
"""
import html
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

UA = "investor-analyzer sylar.zhao@dcsserv.com"
CIK = 320187
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_rfiles")

# 财年 -> accession。XBRL 渲染报表自 FY2011 10-K 起可得。
FILINGS = {
    "2011": "0001193125-11-194791",
    "2012": "0001193125-12-312306",
    "2013": "0000320187-13-000092",
    "2014": "0000320187-14-000097",
    "2015": "0000320187-15-000113",
    "2016": "0000320187-16-000336",
    "2017": "0000320187-17-000090",
    "2018": "0000320187-18-000142",
    "2019": "0000320187-19-000051",
    "2020": "0000320187-20-000047",
    "2021": "0000320187-21-000028",
    "2022": "0000320187-22-000038",
    "2023": "0000320187-23-000039",
    "2024": "0000320187-24-000044",
    "2025": "0000320187-25-000047",
    "2026": "0000320187-26-000088",
}

TAGRE = re.compile(r"<[^>]+>")
DATE = re.compile(r"^[A-Z][a-z]{2}\.? \d{1,2}, (19|20)\d\d$")


def get(url):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": UA}), timeout=300).read()


def txt(x):
    x = re.sub(r"<br\s*/?>", " ", x, flags=re.I)
    return re.sub(r"\s+", " ", html.unescape(TAGRE.sub("", x)).replace("\xa0", " ")).strip()


def parse_r(raw):
    """→ (unit, periods, months, rows)。months[i] = 第 i 列的「N Months Ended」期长。"""
    s = raw.decode("utf-8", "ignore")
    m = re.search(r'<table[^>]*class="report"[^>]*>(.*?)</table>', s, re.S | re.I)
    if not m:
        return None
    unit, periods, months, rows = "", [], [], []
    trs = re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S | re.I)

    def spans(cells, skip_title):
        out, i = [], 0
        for k, (kind, attr, c) in enumerate(cells):
            if skip_title and k == 0 and "tl" in ((re.search(r'class="([^"]*)"', attr) or ["", ""])[1]):
                continue
            n = int((re.search(r'colspan="?(\d+)"?', attr) or [0, "1"])[1])
            out.append((txt(c), i, n))
            i += n
        return out

    raw_months, period_spans = [], []
    for tr in trs[:4]:
        cells = re.findall(r"<t([hd])([^>]*)>(.*?)</t[hd]>", tr, re.S | re.I)
        if not cells or not all(c[0].lower() == "h" for c in cells):
            continue
        sp = spans(cells, skip_title=True)
        grp = [(lab, i, n) for lab, i, n in sp if re.match(r"^\d+\s+Months\s+Ended$", lab)]
        if grp and not raw_months:
            width = max(i + n for _, i, n in grp)
            raw_months = [None] * width
            for lab, i, n in grp:
                for j in range(i, i + n):
                    raw_months[j] = int(re.match(r"^(\d+)", lab).group(1))
            continue
        dates = [(lab, i, n) for lab, i, n in sp if DATE.match(lab)]
        if dates and not period_spans:
            period_spans = dates
    if raw_months and period_spans:
        months = [raw_months[i] if i < len(raw_months) else None for _, i, _ in period_spans]

    for tr in trs:
        cells = re.findall(r"<t([hd])([^>]*)>(.*?)</t[hd]>", tr, re.S | re.I)
        if not cells:
            continue
        if all(c[0].lower() == "h" for c in cells):
            labs = [txt(c[2]) for c in cells]
            if DATE.match(labs[0]):
                cand = [x for x in labs if x]
            else:
                if "$" in labs[0] or "shares" in labs[0].lower() or "Thousands" in labs[0] or "Millions" in labs[0]:
                    unit = labs[0]
                cand = [x for x in labs[1:] if x]
            cand = [x for x in cand if not re.match(r"^\d+ Months Ended$", x)]
            if cand and any(re.search(r"\b(19|20)\d\d\b", x) for x in cand) and len(cand) > len(periods):
                periods = cand
            continue
        label = txt(cells[0][2])
        if not label:
            continue
        mt = re.search(r"defref_([A-Za-z0-9_\-]+)", cells[0][2])
        tag = mt.group(1) if mt else ""
        vals = []
        for kind, attr, c in cells[1:]:
            cls = (re.search(r'class="([^"]*)"', attr) or ["", ""])[1]
            t = txt(c)
            is_fn = bool(re.search(r"\bfn\b", cls))
            if is_fn and (not t or "[" in t):          # 脚注上标（[1] / [1],[2]）
                continue
            if "num" in cls or (is_fn and re.search(r"\d", t)):
                neg = t.startswith("(") or t.startswith("$ (")
                d = re.sub(r"[^0-9.]", "", t)
                vals.append(None if d in ("", ".") else (-float(d) if neg else float(d)))
            else:                                       # ← 坑①：空值/文本一律占位 None
                vals.append(None)
        rows.append({"label": label, "tag": tag, "vals": vals})
    n = len(periods)
    if n:                                               # ← 坑③：统一右对齐
        for r in rows:
            v = r["vals"]
            r["vals"] = v[-n:] if len(v) >= n else [None] * (n - len(v)) + v
    if len(months) != n:
        months = []
    return unit, periods, months, rows


def classify(short):
    """把 FilingSummary 的 ShortName 归到各槽位。返回 None = 不抓。

    🔴 顺序有讲究：**附注明细类判断必须排在正表之前**。
    例如「Operating Segments and Related Information - Accounts Receivable Net,
    Inventories and Property Plant and Equipment Net by Operating Segments (Detail)」
    含 "balance sheet" 之外的 BS 科目名，但它是分部附注不是资产负债表。
    """
    s = " ".join(short.lower().split())
    if "(tables)" in s or "(policies)" in s:
        return None

    # —— 附注明细（先判）——
    # FY2019-2023 这张表叫「Revenues (Details)」，FY2024 起改名
    # 「REVENUES - Schedule of Disaggregation of Revenue (Details)」——两种都要认，
    # 否则 FY2019-2023 的渠道(批发/DTC)拆分整整 5 年会静默落空
    # （第一版 classify 就漏了前一种，靠 harvest 产出表里 DISAG 只有 FY2024+ 才发现）。
    if "disaggregation of revenue" in s or re.match(r"^revenues \(detail", s):
        return "DISAG"          # 按渠道(批发/DTC)×品类×分部拆收入
    if "revenues by major product line" in s:
        return "PROD"           # 按产品线(鞋/服/装备)×分部拆收入
    if "accounts receivable" in s and "operating segment" in s:
        return "SEGBS"          # 分部的应收/存货/PPE
    if "long-lived assets by geographic" in s:
        return "GEOPPE"
    if ("information by operating segment" in s or "by operating segments (detail" in s) \
            and "parenthetical" not in s:
        return "SEG"
    if "operating segments and related information - additional information" in s \
            or "segment information - additional information" in s:
        return "SEGADD"
    if s.startswith("inventories") and "detail" in s:
        return "INV"
    if "property" in s and "equipment" in s and ("(detail" in s):
        return "PPE"
    if "accrued liabilities" in s and "(detail" in s:
        return "ACCR"
    if "supplier finance" in s and "(detail" in s:
        return "SUPF"           # 🔴 供应商融资计划余额（表外杠杆，FY2023 起才强制披露）
    if ("severance" in s or "restructur" in s) and "(detail" in s and "additional" not in s:
        return "RESTR"
    if "leases - additional information" in s:
        return "LEASEADD"
    if "leases - maturities" in s:
        return "LEASEMAT"
    # 「Earnings Per Share - Additional Information (Detail)」只有反稀释期权数，
    # 加权平均股数在**主调节表**里 —— 不排除 additional 就会抓错那张
    # （实测 FY2015/FY2018 抓回来只有 0.1 / 42.9 这种反稀释期权数）。
    if "earnings per share" in s and "(detail" in s and "additional" not in s:
        return "EPS"
    if "long-term debt" in s and "(detail" in s and "additional" not in s and "maturities" not in s:
        return "DEBT"
    if "common stock and stock-based compensation" in s and "(detail" in s:
        return "SBC"
    if "(detail" in s or "(parenthetical)" in s:
        return None

    # —— 正表 ——
    if "statements of income" in s or "statement of income" in s or "statements of operations" in s:
        return "IS"
    if "comprehensive income" in s or "comprehensive loss" in s:
        return "CI"
    if "balance sheet" in s:
        return "BS"
    if "cash flow" in s:
        return "CF"
    if "shareholders' equity" in s or "stockholders' equity" in s:
        return "EQ"
    return None


def main():
    os.makedirs(OUT, exist_ok=True)
    force = "--force" in sys.argv
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    for key in sorted(FILINGS):
        if only and key not in only:
            continue
        acc = FILINGS[key]
        dest = os.path.join(OUT, f"{key}.json")
        if os.path.exists(dest) and not force:
            print(f"SKIP {key}")
            continue
        base = f"https://www.sec.gov/Archives/edgar/data/{CIK}/{acc.replace('-', '')}"
        try:
            root = ET.fromstring(get(base + "/FilingSummary.xml"))
        except Exception as e:
            print(f"FAIL {key}: FilingSummary {e}")
            continue
        time.sleep(0.3)
        found = {}
        for r in root.iter("Report"):
            sn = (r.findtext("ShortName") or "").strip()
            fn = (r.findtext("HtmlFileName") or "").strip()
            k = classify(sn) if fn else None
            if k and k not in found:
                found[k] = (fn, sn)
        out = {"key": key, "cik": CIK, "acc": acc, "statements": {}}
        for k, (fn, sn) in sorted(found.items()):
            try:
                p = parse_r(get(base + "/" + fn))
            except Exception as e:
                print(f"  !! {key}/{k} {fn}: {e}")
                continue
            time.sleep(0.2)
            if not p:
                print(f"  !! {key}/{k} {fn}: no report table")
                continue
            unit, periods, months, rows = p
            out["statements"][k] = {"file": fn, "short": sn, "unit": unit,
                                    "periods": periods, "months": months, "rows": rows}
        json.dump(out, open(dest, "w"), ensure_ascii=False, indent=1)
        print(f"OK {key}: " + ", ".join(f"{k}({len(v['periods'])}p,{len(v['rows'])}r)"
                                        for k, v in sorted(out["statements"].items())))


if __name__ == "__main__":
    main()
