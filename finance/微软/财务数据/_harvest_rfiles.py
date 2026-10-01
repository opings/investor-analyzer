#!/usr/bin/env python3
"""抓取 Microsoft 各财年 10-K 的 SEC 渲染报表 R*.htm（= 该次申报自身的 as-reported 印刷报表）。

产出 `_rfiles/<财年>.json`：
  {"key":"2026","cik":789019,"acc":"...",
   "statements":{"IS":{...},"BS":{...},"CF":{...},"CI":{...},"EQ":{...}},
   "details":{"<ShortName>":{"file":"R47.htm","unit":...,"periods":[...],"months":[...],"rows":[...]}, ...}}

与耐克 / Disney / 特斯拉的 `_harvest_rfiles.py` 同源，三个已踩过的坑照搬：
① 空值单元格是 `<td class="text">&#xA0;</td>` —— **必须占位 None**，否则整行数值左移一列。
② 每行 `onclick="top.Show.showAR(this,'defref_us-gaap_XXX',...)"` 里带**该行的 XBRL tag** ——
   按 tag 归一比按印刷标签归一稳。
③ `class="fn"` 格按**内容**判：空 / 含 `[` 的脚注上标 → 丢弃；含数字 → 当数据列。

## 与耐克那版的两处不同

- **附注明细表（Details）整批落盘**，按 FilingSummary 的 ShortName 作键，不再按槽位只挑几张。
  理由：记忆 `note-enumeration-audit`——「只取报表页 = 建了个半成品」。分部、地区、递延收入、
  RPO、租赁（含**已签未起租**）、所得税、回购、股息这些全在附注里；先全量落盘，
  下游构建器按 ShortName 正则各取所需，附注枚举也有了可复核的底稿。
  只跳过 `(Tables)` / `(Policies)` 两类（它们是正文文字块的表格化副本，不带数值列）。
- **财年 6 月 30 日结束**：R 文件期间日期印「Jun. 30, 2026」，**年份即财年**。

## Microsoft 特有

- 单 CIK 789019，EDGAR 无旧名（formerNames 为空）。
- R*.htm 自 **FY2011** 那份 10-K 起可得；FY2010 那份只有 R*.xml（旧版查看器），
  FY2009 及更早没有 FilingSummary —— 均走 `_parse_legacy.py`。
- 访问 www.sec.gov 必须带「机构名 + 邮箱样式」UA，否则 403；用 RFC 2606 保留域名，**不放任何真实邮箱**。
"""
import html
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

UA = "InvestorResearch admin@example.com"
CIK = 789019
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_rfiles")

# 财年 -> accession（来自 data.sec.gov/submissions，2026-10-01 拉取）
FILINGS = {
    "2011": "0001193125-11-200680",
    "2012": "0001193125-12-316848",
    "2013": "0001193125-13-310206",
    "2014": "0001193125-14-289961",
    "2015": "0001193125-15-272806",
    "2016": "0001193125-16-662209",
    "2017": "0001564590-17-014900",
    "2018": "0001564590-18-019062",
    "2019": "0001564590-19-027952",
    "2020": "0001564590-20-034944",
    "2021": "0001564590-21-039151",
    "2022": "0001564590-22-026876",
    "2023": "0000950170-23-035122",
    "2024": "0000950170-24-087843",
    "2025": "0000950170-25-100235",
    "2026": "0001193125-26-323660",
}

TAGRE = re.compile(r"<[^>]+>")
DATE = re.compile(r"^[A-Z][a-z]{2}\.? \d{1,2}, (19|20)\d\d$")


def get(url, tries=5):
    # 单个请求正常 ~1 秒；超时设 30 秒——实测 120 秒超时 × 4 次重试时，个别挂死的连接会让
    # 整份申报卡 8 分钟以上（并发 map 要等最慢那个），16 份要跑数小时。
    for k in range(tries):
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30).read()
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(2 * (k + 1))


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
            # 🔴 单列附注表的第二行表头是「Jun. 30, 2026 USD ($)」——它**以日期开头**、又含「$」。
            #    第一版把它当单位行，覆盖掉第一行的「… $ in Billions」→ 量纲丢失（3,291 亿美元的
            #    未起租租赁会被当成 329.1 美元），且它本身是期间却没进 periods → 整表取不到数。
            if DATE.match(labs[0]) or re.match(r"^[A-Z][a-z]{2}\.? \d{1,2}, (19|20)\d\d\b", labs[0]):
                cand = [x for x in labs if x]
            else:
                if "$" in labs[0] or "shares" in labs[0].lower() or "Thousands" in labs[0] or "Millions" in labs[0] \
                        or "Billions" in labs[0]:
                    # 只在尚无单位、或新行带量纲（in Millions/Billions/Thousands）时更新，不让后行覆盖前行
                    if not unit or re.search(r"in (Millions|Billions|Thousands)", labs[0], re.I):
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


def classify_statement(short):
    s = " ".join(short.lower().split())
    if "(parenthetical)" in s or "(detail" in s or "(table" in s or "(polic" in s:
        return None
    if s.startswith("income statements") or "statements of income" in s:
        return "IS"
    if "comprehensive income" in s:
        return "CI"
    if s.startswith("balance sheets"):
        return "BS"
    if s.startswith("cash flows statements") or "statements of cash flows" in s:
        return "CF"
    if "stockholders' equity statements" in s or "statements of stockholders" in s:
        return "EQ"
    return None


def keep_detail(short):
    s = " ".join(short.lower().split())
    if "(tables)" in s or "(policies)" in s:
        return False
    return "(detail" in s or "(parenthetical)" in s


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
        out = {"key": key, "cik": CIK, "acc": acc, "statements": {}, "details": {}}
        jobs = []
        for r in root.iter("Report"):
            sn = (r.findtext("ShortName") or "").strip()
            fn = (r.findtext("HtmlFileName") or "").strip()
            if not fn:
                continue
            slot = classify_statement(sn)
            if not slot and not keep_detail(sn):
                continue
            if slot and any(j[2] == slot for j in jobs):
                continue
            jobs.append((fn, sn, slot))

        # 单个请求实测约 1.4 秒；串行 16 份 × ~110 张要近一小时。并发 5 路（≈3-4 次/秒，
        # 低于 SEC 公平访问上限 10 次/秒）。结果按 FilingSummary 原顺序写回，可复现。
        def fetch(job):
            fn, sn, slot = job
            try:
                return job, parse_r(get(base + "/" + fn)), None
            except Exception as e:
                return job, None, e

        n_fail = 0
        with ThreadPoolExecutor(max_workers=5) as ex:
            results = list(ex.map(fetch, jobs))
        for (fn, sn, slot), p, err in results:
            if err is not None:
                print(f"  !! {key} {fn} {sn}: {err}", flush=True)
                n_fail += 1
                continue
            if not p:
                continue
            unit, periods, months, rows = p
            rec = {"file": fn, "short": sn, "unit": unit, "periods": periods, "months": months, "rows": rows}
            if slot:
                out["statements"][slot] = rec
            else:
                out["details"][sn] = rec
        json.dump(out, open(dest, "w"), ensure_ascii=False, indent=0)
        print(f"OK {key}: " + ", ".join(f"{k}({len(v['periods'])}p,{len(v['rows'])}r)"
                                        for k, v in sorted(out["statements"].items()))
              + f" | details {len(out['details'])} | fail {n_fail}", flush=True)


if __name__ == "__main__":
    main()
