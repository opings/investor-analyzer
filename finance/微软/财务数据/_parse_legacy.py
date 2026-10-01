#!/usr/bin/env python3
"""解析 Microsoft 前 R 文件时代（FY1994-FY2010）10-K 的三表，输出与 `_rfiles/` 同构的 JSON。

为什么要单开这一轨：SEC 只对 **FY2011 起**的 Microsoft 10-K 预渲染 R*.htm
（实测 FY2010 那份只有旧版 R*.xml、FY2009 及更早连 FilingSummary 都没有）。

两个时代两种载体，统一成同一种行结构 `[{label, vals}]`：
  · **FY1994-FY2001** —— 纯文本全文申报（`{accession}.txt`），三表在 EX-13（致股东年报）或
    正文的 SGML `<TABLE>` 块里，**定宽空白分列**。
  · **FY2002-FY2010** —— HTML 主文档，`$` / 数字 / `)` 被拆进相邻 `<td>`，须先拼再抽。

解析内核沿用耐克 `_parse_legacy.py`（已踩过的坑见那边 docstring：按列位置归列不按出现顺序右对齐、
点引线等宽替换、续行合并、HTML 数值列从数据行统计不从表头坐标推、`--`/`—`=本年无此项≠0）。

## Microsoft 特有的四处差异（都踩实了才写在这里）

① **单位说明行在 `<TABLE>` 外面**：FY1994 起的文本版式是
   `INCOME STATEMENTS` / `(In millions, except earnings per share)` / `<TABLE>`，
   单位不在表块内 —— 只看表块会判「单位未知」整张表丢弃。故单位**表块内 + 表前 600 字符**都看。
② **年份列方向会翻**：FY1994-FY2008 前后的报表按**升序**印（1992 1993 1994），
   FY2009 起改为**降序**（2009 2008 2007）。一律按表头年份 token 的实际位置定列，**不假设方向**。
③ **同一份申报里「像利润表」的表不止一张**：FY2002-FY2005 紧跟真利润表之后有一张
   SFAS 123 **备考（pro forma）利润表**（Reported / Pro Forma 两列一组，表头仍是三个年份），
   FY1994 年报里三表后面还跟着给图表用的小表（`NET REVENUES / NET INCOME / EPS` 三列）。
   → 表前标题必须命中 + 反锚（pro forma / quarterly / selected / percent）+ 最低锚行命中数。
④ **同名行**：利润表里「Basic」出现两次（EPS 与加权股数）、资产负债表里「Deferred income taxes」
   在流动资产与非流动资产各一次、「Other」出现多次 —— 由构建器按「在哪个小标题/合计之后」限定窗口取，
   这里只负责把每行原样带出（含段首小标题行）。
"""
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))   # …/investor-analyzer
REPORT = os.path.join(ROOT, "report", "微软")
OUT = os.path.join(HERE, "_legacy")

FILINGS = {fy: f"{fy}.txt" for fy in range(1994, 2002)}
FILINGS.update({fy: f"{fy}.htm" for fy in range(2002, 2011)})

TAG = re.compile(r"<[^>]+>")
NIL = re.compile(r"^(--+|—|–|-)$")
# 年份表头格可带脚注号：FY2004 10-K 印「2002 (1)」「2003 (1)」「2004」——脚注 (1) 说明
# 2002/2003 两年**按 SFAS 123 公允价值法追溯重述**（股权激励费用化）。严格匹配 4 位数字
# 会让表头只剩 1 个年份 → 整份申报三表全丢（第一版 FY2004 = NOTHING 就是这么来的）。
YEAR = re.compile(r"^(19|20)\d\d(\s*\(\d\))?$")
NUMTOK = re.compile(r"\(?\$?\s?-?[\d,]+(?:\.\d+)?\)?%?")

TITLES = {
    "IS": r"INCOME\s+STATEMENTS?\b",
    "BS": r"BALANCE\s+SHEETS?\b",
    "CF": r"CASH\s+FLOWS?\s+STATEMENTS?\b",
    # 「Selected Financial Data」五年摘要：FY1994 年报里叫「SELECTED FIVE-YEAR FINANCIAL DATA」。
    # **它是 FY1990-FY1993 那几年的第二个独立印刷源**（另一个是当年致股东年报扫描件），
    # 用来核扫描件转录 —— 不进三表 as-reported。
    "SUM": r"SELECTED\s+(FIVE-YEAR\s+)?FINANCIAL\s+DATA",
}

MINSCORE = {"IS": 4, "BS": 4, "CF": 3, "SUM": 3}
MAXYEARS = {"IS": 3, "BS": 3, "CF": 3, "SUM": 6}
ANCHORS = {
    "IS": ["revenue", "cost of revenue", "operating income", "income before income taxes",
           "provision for income taxes", "net income", "research and development",
           "sales and marketing", "general and administrative", "earnings per share"],
    "BS": ["total current assets", "total assets", "accounts payable", "retained earnings",
           "retained deficit", "total liabilities and stockholders", "total stockholders",
           "total current liabilities", "accounts receivable"],
    "CF": ["net cash from operations", "financing", "investing", "additions to property",
           "end of year", "end of period", "net change in cash", "common stock repurchased",
           "depreciation"],
    "SUM": ["net revenues", "revenue", "net income", "total assets", "stockholders' equity",
            "earnings per share", "working capital", "cash and short-term investments"],
}
# 反锚：命中即不是正表（SUM 槽位本身就是摘要，豁免 selected）
ANTI = {
    "IS": ["pro forma", "quarterly", "selected", "percent of", "as reported"],
    "BS": ["pro forma", "quarterly", "selected", "percent"],
    "CF": ["pro forma", "quarterly", "selected"],
    "SUM": ["pro forma", "quarter ended"],
}


# ───────────────────────── 通用 ─────────────────────────
def clean(x):
    return re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", x)).replace("\xa0", " ")).strip()


def tonum(t):
    t = t.strip()
    if not t or NIL.match(t):
        return None
    neg = t.startswith("(") or t.startswith("$(") or t.startswith("$ (")
    d = re.sub(r"[^0-9.]", "", t)
    if d in ("", "."):
        return None
    try:
        v = float(d)
    except ValueError:
        return None
    return -v if neg else v


def strip_leaders(line):
    """点引线**等宽**替换成空格（只吃 3 个以上连续点；小数点与 'Note 13.' 不动）。"""
    return re.sub(r"\.{3,}", lambda m: " " * len(m.group()), line)


def score(text, key):
    low = text.lower()
    if any(a in low for a in ANTI[key]):
        return 0
    return sum(1 for a in ANCHORS[key] if a in low)


CONT = re.compile(r"^([a-z]|\d+\)|\)|\([Nn]ote|of \$)")


def merge_wraps(rows):
    """标签折行、金额印在第二行 → 合并（判据见耐克版 docstring）。"""
    out = []
    for r in rows:
        if out and CONT.match(r["label"]) and all(v is None for v in out[-1]["vals"]) \
                and not out[-1]["label"].endswith(":"):
            prev = out.pop()
            r = {"label": f"{prev['label']} {r['label']}", "vals": r["vals"]}
        out.append(r)
    return out


def unit_scale(text):
    low = text.lower()
    if "in thousands" in low:
        return 1e-3
    if "in millions" in low:
        return 1.0
    return None


# ───────────────────── 文本轨（FY1994-2001）─────────────────────
VALTOK = re.compile(r"(?<![\w.])(\(?\$?\s?[\d,]+(?:\.\d+)?\)?|--+|—)(?![\w])")


def parse_txt_table(block, head):
    lines = block.expandtabs(8).split("\n")
    hdr_i, cols = None, []
    for i, ln in enumerate(lines[:25]):
        toks = [(m.group(), m.start(), m.end()) for m in re.finditer(r"\b(19|20)\d\d\b", ln)]
        if len(toks) >= 2 and not re.search(r"\d[,.]\d", ln):
            hdr_i, cols = i, toks
            break
    if hdr_i is None:
        return None
    years = [int(t[0]) for t in cols]
    ends = [t[2] for t in cols]
    cut = cols[0][1] - 3
    scale = unit_scale(block) or unit_scale(head)          # ← 差异①：单位行在表外
    if scale is None:
        return None
    rows, prev_head = [], ""
    for ln in lines[hdr_i + 1:]:
        raw = strip_leaders(ln.rstrip())
        if not raw.strip() or set(raw.strip()) <= set("-=_ "):
            continue
        if raw.strip().startswith("<") and raw.strip().endswith(">"):   # <S> <C> 之类 SGML 标记行
            continue
        toks = [(m.group(), m.end()) for m in VALTOK.finditer(raw) if m.end() >= cut]
        label = re.sub(r"[.\s$(]+$", "", clean(raw[:cut] if len(raw) > cut else raw))
        label = re.sub(r"^- +", "", label)
        if not toks:
            if label:
                rows.append({"label": label, "vals": [None] * len(years)})
                if label.endswith(":") or not re.search(r"[a-z]", label[1:] if label else ""):
                    prev_head = label
            continue
        if not label and prev_head:
            label = prev_head.rstrip(":") + " 合计"
        vals = [None] * len(years)
        if len(toks) == len(years):
            for j, (tok, _) in enumerate(toks):
                vals[j] = tonum(tok)
        else:
            for tok, e in toks:
                j = min(range(len(ends)), key=lambda k: abs(ends[k] - e))
                if vals[j] is None:
                    vals[j] = tonum(tok)
        rows.append({"label": label, "vals": vals})
        if label.endswith(":"):
            prev_head = label
    return scale, years, merge_wraps(rows)


def parse_txt(fy, path):
    s = open(path, encoding="latin-1", errors="ignore").read()
    blocks = [(m.start(), m.group(1)) for m in re.finditer(r"<TABLE>(.*?)</TABLE>", s, re.S | re.I)]
    out = {}
    for key, pat in TITLES.items():
        best, bestsc = None, 0
        for pos, b in blocks:
            head = s[max(0, pos - 600):pos]
            # 标题须在表前最近的那段文字里（只看 <TABLE> 前 600 字符的**最后一个**非空段）
            if not re.search(pat, head[-450:], re.I):
                continue
            sc = score(b, key)
            if sc < MINSCORE[key] or sc <= bestsc:
                continue
            p = parse_txt_table(b, head)
            if p and len(p[1]) <= MAXYEARS[key]:
                best, bestsc = p, sc
        if best:
            scale, years, rows = best
            out[key] = {"scale": scale, "years": years, "rows": rows, "src": "txt"}
    return out


# ───────────────────── HTML 轨（FY2002-2010）─────────────────────
def grid_rows(table_html):
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.S | re.I):
        cells, col = [], 0
        for kind, attr, c in re.findall(r"<t([hd])([^>]*)>(.*?)</t[hd]>", tr, re.S | re.I):
            n = int((re.search(r'colspan="?(\d+)"?', attr) or [0, "1"])[1])
            cells.append((col, n, clean(c)))
            col += n
        if cells:
            out.append(cells)
    return out


PURENUM = re.compile(r"\(?\$?\s?[\d,]+(?:\.\d+)?\)?")


def parse_html_table(table_html, head):
    grid = grid_rows(table_html)
    if not grid:
        return None
    flat = clean(table_html)
    scale = unit_scale(flat[:400]) or unit_scale(clean(head)[-300:])
    years = []
    for cells in grid[:8]:
        ys = [t for c, n, t in cells if YEAR.match(t)]
        if len(ys) >= 2:
            years = [int(t[:4]) for t in ys]
            break
    if not years:
        return None
    cnt = {}
    for cells in grid:
        for c, n, t in cells:
            if t and t not in ("$", "(", ")") and PURENUM.fullmatch(t.replace(" ", "")) and not YEAR.match(t):
                cnt[c] = cnt.get(c, 0) + 1
    if len(cnt) < len(years):
        return None
    vcols = sorted(sorted(cnt, key=lambda c: (-cnt[c], c))[:len(years)])
    rows = []
    prev_head = ""
    for cells in grid:
        texts = {c: t for c, n, t in cells}
        label = ""
        for c, n, t in cells:
            if t and not NUMTOK.fullmatch(t.replace(" ", "")) and t not in ("$", ")", "(") and not NIL.match(t):
                label = t
                break
        if label.endswith(":"):
            prev_head = label
        # 无标签合计行（FY2002 利润表「Basic earnings per share:」段下那行只印 $1.45 不印标签）
        # → 与文本轨一致命名为「<段首> 合计」，不能丢（丢了 FY2002 的报告 EPS 就没了）
        if not label and prev_head and any(texts.get(vc) and PURENUM.fullmatch(texts[vc].replace(" ", ""))
                                           for vc in (c for c, n, t in cells)):
            label = prev_head.rstrip(":") + " 合计"
        if not label or YEAR.match(label):
            continue
        vals = []
        for vc in vcols:
            t = texts.get(vc, "")
            if not t or t in ("$", "(", ")") or NIL.match(t):
                vals.append(None)
                continue
            if not PURENUM.fullmatch(t.replace(" ", "")):
                vals.append(None)
                continue
            neg = t.startswith("(") or texts.get(vc - 1, "") == "(" or texts.get(vc + 1, "") == ")"
            v = tonum(t)
            vals.append(-abs(v) if (neg and v is not None) else v)
        rows.append({"label": label, "vals": vals})
    return scale, years, merge_wraps(rows)


def parse_html(fy, path):
    s = open(path, encoding="utf-8", errors="ignore").read()
    tables = [(m.start(), m.group(1)) for m in re.finditer(r"<table[^>]*>(.*?)</table>", s, re.S | re.I)]
    out = {}
    for key, pat in TITLES.items():
        best, bestsc = None, 0
        for pos, t in tables:
            head = s[max(0, pos - 2500):pos]
            hflat = clean(head)[-260:]
            flat = clean(t)
            if not (re.search(pat, hflat, re.I) or re.search(pat, flat[:200], re.I)):
                continue
            sc = score(flat, key) if key == "SUM" else score(hflat[-120:] + " " + flat, key)
            if sc < MINSCORE[key] or sc <= bestsc:
                continue
            p = parse_html_table(t, head)
            if p and p[0] and len(p[1]) <= MAXYEARS[key]:
                best, bestsc = p, sc
        if best:
            scale, years, rows = best
            out[key] = {"scale": scale, "years": years, "rows": rows, "src": "htm"}
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    only = [int(a) for a in sys.argv[1:] if a.isdigit()]
    for fy in sorted(FILINGS):
        if only and fy not in only:
            continue
        path = os.path.join(REPORT, FILINGS[fy])
        if not os.path.exists(path):
            print(f"MISS FY{fy}: {path}")
            continue
        got = parse_txt(fy, path) if path.endswith(".txt") else parse_html(fy, path)
        json.dump({"key": str(fy), "statements": got},
                  open(os.path.join(OUT, f"{fy}.json"), "w"), ensure_ascii=False, indent=1)
        print(f"FY{fy}: " + (", ".join(
            f"{k}(years={v['years']},scale={v['scale']},rows={len(v['rows'])})"
            for k, v in sorted(got.items())) or "NOTHING"))


if __name__ == "__main__":
    main()
