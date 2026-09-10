#!/usr/bin/env python3
"""抓取 Tesla 各年 10-K 的 SEC 渲染报表 R*.htm（= 该年申报自身的 as-reported 印刷三表）。

产出 `_rfiles/<fy>.json`：
  {"fy":2025,"acc":"...","statements":{"IS":{"file":"R5.htm","unit":"...","periods":[...],
     "rows":[{"label":..., "tag":"us-gaap_Revenues", "dim":false, "vals":[v0,v1,v2]}, ...]}}}

关键点（两个曾踩的坑）：
① 空值单元格是 `<td class="text">&#xA0;</td>` —— **必须占位为 None**，否则整行数值左移一列
   （曾致 FY2011「Fremont 工厂收购款」把 2010 列当成 2011 列，投资段勾稽差 65,210）。
② 每行的 `onclick="top.Show.showAR(this,'defref_us-gaap_XXX',...)"` 里带**该行的 XBRL tag** ——
   按 tag 归一比按印刷标签归一稳得多（15 年里同一行的英文措辞改过几十次）。
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
CIK = "1318605"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_rfiles")

ACCS = {
    2011: "0001193125-12-081990", 2012: "0001193125-13-096241", 2013: "0001193125-14-069681",
    2014: "0001564590-15-001031", 2015: "0001564590-16-013195", 2016: "0001564590-17-003118",
    2017: "0001564590-18-002956", 2018: "0001564590-19-003165", 2019: "0001564590-20-004475",
    2020: "0001564590-21-004599", 2021: "0000950170-22-000796", 2022: "0000950170-23-001409",
    2023: "0001628280-24-002390", 2024: "0001628280-25-003063", 2025: "0001628280-26-003952",
}
TAGRE = re.compile(r"<[^>]+>")
DATE = re.compile(r"^[A-Z][a-z]{2}\.? \d{1,2}, (19|20)\d\d$")


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=180).read()


def txt(x):
    x = re.sub(r"<br\s*/?>", " ", x, flags=re.I)
    return re.sub(r"\s+", " ", html.unescape(TAGRE.sub("", x)).replace("\xa0", " ")).strip()


def parse_r(raw):
    s = raw.decode("utf-8", "ignore")
    m = re.search(r'<table[^>]*class="report"[^>]*>(.*?)</table>', s, re.S | re.I)
    if not m:
        return None
    unit, periods, rows = "", [], []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S | re.I):
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
        tag = ""
        mt = re.search(r"defref_([A-Za-z0-9_\-]+)", cells[0][2])
        if mt:
            tag = mt.group(1)
        vals = []
        for kind, attr, c in cells[1:]:
            cls = (re.search(r'class="([^"]*)"', attr) or ["", ""])[1]
            t = txt(c)
            if "num" in cls:                       # nump = 正数, num = 括号负数
                neg = t.startswith("(") or t.startswith("$ (")
                d = re.sub(r"[^0-9.]", "", t)
                vals.append(None if d in ("", ".") else (-float(d) if neg else float(d)))
            elif "text" in cls:                    # ← 空值占位，必须补 None（坑①）
                vals.append(None)
            else:
                vals.append(None)
        rows.append({"label": label, "tag": tag, "vals": vals})
    # 坑③：FY2020/2021/2022 的部分报表多出一个**前导**脚注列（宽度 = 期间数+1，首格恒空）。
    # 若不右对齐，整行数值右移一位 —— FY2020 资产负债表现金会被读成 None、2019 值被当成 2020。
    # 统一右对齐到 len(periods)：多出的从左侧丢弃，不足的左侧补 None。
    n = len(periods)
    if n:
        for r in rows:
            v = r["vals"]
            r["vals"] = v[-n:] if len(v) >= n else [None] * (n - len(v)) + v
    return unit, periods, rows


def classify(short):
    s = short.lower()
    if "parenthetical" in s:
        return None
    if "balance sheet" in s and "component" not in s:
        return "BS"
    if "statements of operations" in s or "statement of operations" in s:
        return "IS"
    if "cash flow" in s:
        return "CF"
    if "comprehensive" in s:
        return "CI"
    return None


def main():
    os.makedirs(OUT, exist_ok=True)
    force = "--force" in sys.argv
    for fy, acc in sorted(ACCS.items()):
        dest = os.path.join(OUT, f"{fy}.json")
        if os.path.exists(dest) and not force:
            print(f"SKIP {fy}")
            continue
        base = f"https://www.sec.gov/Archives/edgar/data/{CIK}/{acc.replace('-', '')}"
        root = ET.fromstring(get(base + "/FilingSummary.xml"))
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
                st[k] = {"file": fn, "short": sn, "unit": p[0], "periods": p[1], "rows": p[2]}
        json.dump({"fy": fy, "acc": acc, "statements": st}, open(dest, "w"), ensure_ascii=False, indent=1)
        print(f"OK {fy}: " + " ".join(f"{k}({len(v['rows'])}r,{len(v['periods'])}p)" for k, v in sorted(st.items())))


if __name__ == "__main__":
    main()
