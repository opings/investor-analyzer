#!/usr/bin/env python3
"""抓取 Disney 各财年 10-K / 10-Q 的 SEC 渲染报表 R*.htm（= 该次申报自身的 as-reported 印刷报表）。

产出 `_rfiles/<key>.json`：
  {"key":"2025","cik":1744489,"acc":"...","statements":{
     "IS":{"file":"R2.htm","unit":"...","periods":[...],
           "rows":[{"label":..., "tag":"us-gaap_Revenues", "vals":[v0,v1,v2]}, ...]}}}

沿用特斯拉 `_harvest_rfiles.py` 的做法，两个已踩过的坑照搬：
① 空值单元格是 `<td class="text">&#xA0;</td>` —— **必须占位 None**，否则整行数值左移一列。
② 每行 `onclick="top.Show.showAR(this,'defref_us-gaap_XXX',...)"` 里带**该行的 XBRL tag** ——
   按 tag 归一比按印刷标签归一稳（Disney 17 年里同一行的英文措辞改过多次，
   例如 "Revenues" ↔ "Total revenues"、"Service" 拆分口径变过）。
③ 部分年度报表多出一个**前导脚注列**（首格恒空）→ 统一右对齐到 len(periods)。

🔴 ④ **Disney 新坑（特斯拉那版没有的）**：`class="fn"` 在 Disney 的 R 文件里**有两种含义**，
   必须按内容分辨，不能一刀切：
   · FY2019+ ——  fn 是**空脚注标记列**，夹在数值列之间（不是前导也不是末尾）：
       [1]nump 94,425(FY25) [2]nump 91,361(FY24) [3]fn '' [4]nump 88,898(FY23) [5]fn ''
     沿用「右对齐取末 N 格」会取到 [fn, 88898, fn] → 整行错位，且**看起来像有值**
     （FY2025 营收被读成 88,898，那其实是 FY2023 的数）。
   · FY2011 ——  fn 却装着**真数据**：
       [1]nump '$ 3,185'(FY2011) [2]fn '$ 2,722'(FY2010)
     若无差别丢弃 fn，**整整一年的资产负债表数据会消失**，且残存的那个值会被
     右对齐推进上一年的槽位 —— FY2011 的现金会被记成 FY2010 的。
   **对策：fn 格按内容判 —— 空 / `[n]` 形态的脚注上标 → 丢弃；含数字 → 当数据列。**
   （这坑是被 `重述与口径变更` 那张表逮出来的：FY2010 的十几个科目"被后续年报重述"，
     而重述值恰好等于 FY2011 的当年值 —— 那不是重述，是错列。）

Disney 特有：三 CIK（29082 / 1001039 / 1744489），accession 与 CIK 必须配对，
否则 Archives 路径 404。CIK 归属见本文件 FILINGS 表。
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
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_rfiles")

# key -> (cik, accession)。XBRL 渲染报表自 FY2009 10-K 起可得（更早的年报走 _build_early.py 文本解析轨）。
FILINGS = {
    "2009": (1001039, "0001193125-09-245848"),
    "2010": (1001039, "0001193125-10-268910"),
    "2011": (1001039, "0001193125-11-321340"),
    "2012": (1001039, "0001193125-12-479027"),
    "2013": (1001039, "0001001039-13-000164"),
    "2014": (1001039, "0001001039-14-000228"),
    "2015": (1001039, "0001001039-15-000255"),
    "2016": (1001039, "0001001039-16-000516"),
    "2017": (1001039, "0001001039-17-000198"),
    "2018": (1001039, "0001001039-18-000187"),
    "2019": (1744489, "0001744489-19-000225"),
    "2020": (1744489, "0001744489-20-000197"),
    "2021": (1744489, "0001744489-21-000220"),
    "2022": (1744489, "0001744489-22-000213"),
    "2023": (1744489, "0001744489-23-000216"),
    "2024": (1744489, "0001744489-24-000276"),
    "2025": (1744489, "0001744489-25-000155"),
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
    """→ (unit, periods, months, rows)。

    `months[i]` = 第 i 列的「N Months Ended」期长。
    🔴 **为什么必须要它**：FY2012/FY2013 的利润表 R 文件把**8 个季度列**和 3 个年度列
    混排在同一张表里（periods 长度 11），且季度列里也有 9 月末的日期
    （Q4 的「3 Months Ended Sep. 29, 2012」）。只按日期年份认列，年度值会被季度值顶掉；
    「取最后一个匹配列」能蒙对但是启发式。读表头 colspan 分组才是确定性做法。
    """
    s = raw.decode("utf-8", "ignore")
    m = re.search(r'<table[^>]*class="report"[^>]*>(.*?)</table>', s, re.S | re.I)
    if not m:
        return None
    unit, periods, months, rows = "", [], [], []
    trs = re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S | re.I)

    # --- 表头两行：期长分组行 + 期间日期行。两行的 colspan 都按**原始单元格空间**计，
    #     该空间含 fn 脚注列，故 sum(colspan) 通常 > len(periods)。
    #     做法：先把期长铺进原始空间，再按期间各自的起始偏移取回每个期间的期长。
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
            # 坑④判据：fn 格里含 `[` 即脚注上标（可能是 `[1]`，也可能是 `[1],[2]` 多引用），
            # 真金额永远不含方括号。早先只认单个 `[n]`，结果 `[1],[2]` 被剥成数字 12
            # 当成数据列插进去 —— FY2011/12/13 的「Total assets」整行因此右移一格。
            if is_fn and (not t or "[" in t):
                continue
            if "num" in cls or (is_fn and re.search(r"\d", t)):
                neg = t.startswith("(") or t.startswith("$ (")
                d = re.sub(r"[^0-9.]", "", t)
                vals.append(None if d in ("", ".") else (-float(d) if neg else float(d)))
            else:                                 # ← 坑①：空值/文本一律占位 None
                vals.append(None)
        rows.append({"label": label, "tag": tag, "vals": vals})
    n = len(periods)
    if n:                                          # ← 坑③：统一右对齐
        for r in rows:
            v = r["vals"]
            r["vals"] = v[-n:] if len(v) >= n else [None] * (n - len(v)) + v
    if len(months) != n:                           # 对不上就不给（下游按缺失处理，不猜）
        months = []
    return unit, periods, months, rows


def classify(short):
    """把 FilingSummary 的 ShortName 归到 IS / BS / CF / CI / EQ / SEG。"""
    s = short.lower()
    if "(tables)" in s or "(policies)" in s:
        return None
    keep = ("financial information by operating segment" in s
            or "reconciliation of segment operating income" in s)
    if ("parenthetical" in s or "(detail" in s) and not keep:
        return None
    if "balance sheet" in s:
        return "BS"
    if "cash flow" in s:
        return "CF"
    if "comprehensive income" in s or "comprehensive loss" in s:
        return "CI"
    if "statements of income" in s or "statement of income" in s \
       or "statements of operations" in s or "statement of operations" in s:
        return "IS"
    if "equity" in s and "statement" in s:
        return "EQ"
    # 分部数字在「Financial Information by Operating Segments (Detail)」里，
    # 不在正文三表；(Parenthetical) 是脚注不要。
    if "financial information by operating segment" in s and "parenthetical" not in s:
        return "SEG"
    # 「分部经营利润 → 税前利润」的调节表。**这张表不抓，总部费用与并购无形摊销
    #   就只能从税前利润倒挤**，而倒挤会把「公司总部费用」「TFCF/Hulu 并购无形摊销」
    #   「已含在分部利润里的权益法收益」三样混成一个数（实测差 2,073）。
    if "reconciliation of segment operating income" in s and "footnote" not in s:
        return "REC"
    return None


def main():
    os.makedirs(OUT, exist_ok=True)
    force = "--force" in sys.argv
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    for key in sorted(FILINGS):
        if only and key not in only:
            continue
        cik, acc = FILINGS[key]
        dest = os.path.join(OUT, f"{key}.json")
        if os.path.exists(dest) and not force:
            print(f"SKIP {key}")
            continue
        base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}"
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
        st = {}
        for k, (fn, sn) in found.items():
            p = parse_r(get(f"{base}/{fn}"))
            time.sleep(0.3)
            if p:
                st[k] = {"file": fn, "short": sn, "unit": p[0],
                         "periods": p[1], "months": p[2], "rows": p[3]}
        json.dump({"key": key, "cik": cik, "acc": acc, "statements": st},
                  open(dest, "w"), ensure_ascii=False, indent=1)
        print(f"OK {key}: " + " ".join(
            f"{k}({len(v['rows'])}r,{len(v['periods'])}p,m{len(set(v['months'])) if v['months'] else '?'})"
            for k, v in sorted(st.items())))


if __name__ == "__main__":
    main()
