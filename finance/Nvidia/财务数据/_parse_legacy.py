#!/usr/bin/env python3
"""解析 NVIDIA 前 R 文件时代（FY1999-FY2011）10-K 与 IPO 招股书的三表，输出与 `_rfiles/` 同构的 JSON。

为什么单开这一轨：SEC 只对 **FY2012 起**的 NVIDIA 10-K 预渲染 R*.htm（FY2010、FY2011 两份只有旧版
R*.xml——FilingSummary 里只有 XmlFileName、没有 HtmlFileName；FY2009 及更早连 FilingSummary 都没有）。

两种载体统一成同一种行结构 `[{label, vals}]`，列以**键**标识（不是裸年份）：
  · **FY1999-FY2001** —— 纯文本（FY1999/2000 为整份 SGML 申报 `.txt`，FY2001 为 `d10k405.txt`），
    三表在 SGML `<TABLE>` 块里，**定宽空白分列**。
  · **FY2002-FY2011** —— HTML 主文档，`$` / 数字 / `)` 被拆进相邻 `<td>`，须先拼再抽。
  · **招股书**（1999-01-21 定稿 424B4）—— 纯文本，同 FY1999 版式。

解析内核沿用微软 / 耐克 `_parse_legacy.py`（按列位置归列不按出现顺序右对齐、点引线等宽替换、
续行合并、HTML 数值列从数据行统计不从表头坐标推、`--`/`—` = 本年无此项 ≠ 0）。

## NVIDIA 特有的四处差异（都踩实了才写在这里）

① **财年口径换过一次 → 列键不是裸年份**。公司 1993-1997 年财年 = 日历年（截至 12 月 31 日）；
   **1998 年 1 月单独一个过渡月**；1998-02-01 起改为截至 1 月最后一个周日的 52/53 周财年（FY1999 起）。
   ⇒ **不存在完整的「FY1998」**。FY1999 / FY2000 两份 10-K 表头里的「1998」一律是过渡月
   （利润表 / 现金流 = 1998 年 1 月单月；资产负债表 = 1998-01-31 时点），本脚本映射为键 `1998-01`。
② **招股书一张表里年份 token 重复**：五年摘要 9 列 = 1993（4-05 成立起）/1994/1995/1996/1997/
   **1997-01 对比月**/1998-01 过渡月/9 个月（1997-09-28）/9 个月（1998-10-25）。按位置归不了键 →
   对招股书的每张表**显式指定列键**，并断言解析出的年份 token 序列与预期一字不差（对不上就拒绝写出）。
③ **HTML 表头年份不是单独一格**：FY2002 起印「Year Ended January 27, 2002」或「January 31, 2010」，
   微软那版只认纯 4 位年份格，会判「无年份」整表丢弃 → 改为认「(月 日,) 年」结尾的格。
④ **续行合并要认括号开头的续行**：招股书版式把「Gross profit」与「(loss)........ 数字」拆成两行、
   「Income (loss) / before income / tax expense / (benefit)」拆成四行 —— 微软版 CONT 只认小写开头，
   会把「(loss)」「(benefit)」当成新行、金额挂到错误标签下。
"""
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))   # …/investor-analyzer
REPORT = os.path.join(ROOT, "report", "Nvidia")
OUT = os.path.join(HERE, "_legacy")

FILINGS = {"1999": "1999.txt", "2000": "2000.txt", "2001": "2001.txt"}
FILINGS.update({str(fy): f"{fy}.htm" for fy in range(2002, 2012)})
FILINGS["prospectus"] = "招股说明书.txt"
# 2006-11-29 的 10-K/A：重述 FY2004-FY2006 三年合并报表（期权授予问题·Note 2）。只进重述台账，不当 as-reported
FILINGS["2006A"] = "2006-A.htm"
# 1998-03-06 首版 S-1：上市前年份的**第二个独立印刷处**（只进交叉核 / 重述台账）。
# ⚠️ 它的 CY1997 与定稿招股书不同（净亏损 2,691 vs 3,589 千美元——定稿前补记了期权补偿），不是解析错
FILINGS["s1"] = "招股说明书-S-1-19980306.txt"

TAG = re.compile(r"<[^>]+>")
NIL = re.compile(r"^(--+|—|–|-)$")
YEAR = re.compile(r"^(19|20)\d\d(\s*\(\d\))?$")
# ③ HTML 表头格：「2002」「January 27, 2002」「Year Ended January 27, 2002」「January 31, 2010 (1)」
# FY2011 现金流量表印「January 30 , 2011」（逗号前有空格）——第一版不认，静默丢了 FY2011 整列
HDRYEAR = re.compile(r"^(?:(?:years?|month|nine months|twelve months)\s+ended\s+)?"
                     r"(?:[a-z]+\.?\s+\d{1,2}\s*,\s*)?((?:19|20)\d\d)(?:\s*\(\d\))?$", re.I)
NUMTOK = re.compile(r"\(?\$?\s?-?[\d,]+(?:\.\d+)?\)?%?")

TITLES = {
    "IS": r"STATEMENTS?\s+OF\s+(INCOME|OPERATIONS)\b",
    "BS": r"BALANCE\s+SHEETS?\b",
    "CF": r"STATEMENTS?\s+OF\s+CASH\s+FLOWS?\b",
    # 「Selected (Consolidated) Financial Data」五年摘要：**上市前 1993-1994 两年的唯一数据源**（招股书），
    # 也是 FY1999-2010 各年的第二个独立印刷处（交叉核用，不进 as-reported）
    "SUM": r"SELECTED\s+(CONSOLIDATED\s+)?FINANCIAL\s+DATA",
}

MINSCORE = {"IS": 4, "BS": 4, "CF": 3, "SUM": 3}
MAXYEARS = {"IS": 4, "BS": 3, "CF": 4, "SUM": 6}
ANCHORS = {
    "IS": ["revenue", "cost of revenue", "gross profit", "research and development",
           "sales, general and administrative", "operating income", "income before income tax",
           "income tax", "net income", "per share"],
    "BS": ["total current assets", "accounts payable", "accrued liabilities", "total current liabilities",
           "retained earnings", "accumulated deficit", "total stockholders", "accounts receivable", "inventor",
           "property and equipment"],
    "CF": ["operating activities", "investing activities", "financing activities", "depreciation",
           "end of period", "end of year", "property and equipment", "beginning of"],
    "SUM": ["revenue", "net income", "total assets", "stockholders' equity", "per share", "working capital",
            "gross profit", "income (loss)"],
}
ANTI = {
    "IS": ["pro forma", "quarterly", "percentage of", "percent of", "as a percentage"],
    "BS": ["pro forma", "quarterly", "selected", "percent"],
    "CF": ["pro forma", "quarterly", "selected"],
    "SUM": ["pro forma", "quarter ended"],
}

# ② 招股书各表的显式列键 + 预期年份 token 序列（对不上即拒绝）
PROSPECTUS_COLS = {
    "SUM": ([1993, 1994, 1995, 1996, 1997, 1997, 1998, 1997, 1998],
            ["1993", "1994", "1995", "1996", "1997", "1997-01对比月", "1998-01", "9M1997", "9M1998"]),
    "IS": ([1995, 1996, 1997, 1997, 1998, 1997, 1998],
           ["1995", "1996", "1997", "1997-01对比月", "1998-01", "9M1997", "9M1998"]),
    "BS": ([1996, 1997, 1998, 1998], ["1996", "1997", "1998-01", "1998-10"]),
    # 五年摘要下半张「Balance Sheet Data」：**1993-1995 年末资产负债的唯一来源**（只有 4 行）
    "SUMBS": ([1993, 1994, 1995, 1996, 1997, 1998, 1998],
              ["1993", "1994", "1995", "1996", "1997", "1998-01", "1998-10"]),
    "CF": ([1995, 1996, 1997, 1997, 1998, 1997, 1998],
           ["1995", "1996", "1997", "1997-01对比月", "1998-01", "9M1997", "9M1998"]),
}
PROSPECTUS_MAX = {"SUM": 9, "IS": 7, "BS": 4, "CF": 7, "SUMBS": 7}


def year_key(y):
    """10-K 表头年份 → 列键。① 1998 只可能是过渡月（不存在完整 FY1998）。"""
    return "1998-01" if y == 1998 else str(y)


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


# ④ 续行：**不以大写字母开头**（小写 / 「(loss)」/ 「$3,506,」/ 「10,000,000 shares」/ 「25, 1998」）
#    或以「月份 + 日期」开头（「January 31, 1998 and October」）。
#    第一版只认小写开头 → 应收账款「less allowances of $100,」+「$3,506, at December 31, 1997,」+ … 四行
#    拆成四个标签，金额挂在「25, 1998, respectively」名下，应收账款整行取不到（C0 抓出）。
MONTHS = r"(January|February|March|April|May|June|July|August|September|October|November|December)"
CONT = re.compile(r"^([^A-Z]|" + MONTHS + r"\s+\d)")


def merge_wraps(rows):
    """标签折行、金额印在最后一行 → 合并成一行（前一行须无值、且不以冒号结尾）。"""
    out = []
    for r in rows:
        if out and CONT.match(r["label"]) and all(v is None for v in out[-1]["vals"]) \
                and not any(out[-1].get("dash") or []) and not out[-1]["label"].endswith(":"):
            prev = out.pop()
            r = dict(r, label=f"{prev['label']} {r['label']}")
        out.append(r)
    return out


def unit_scale(text):
    low = text.lower()
    if "in thousands" in low:
        return 1e-3
    if "in millions" in low:
        return 1.0
    return None


# ───────────────────── 文本轨（FY1999-2001 + 招股书）─────────────────────
# 「$ (.07)」这类无整数位的每股数：小数点前可以没有数字（招股书 / FY1999-2000 版式全是这种写法）。
# 🔴 必须以数字开头：第一版写 `[\d,]+`，一个孤立的逗号也算 token —— FY1999「(expense),」行尾逗号被当成数值、
#    标签被截成「…(expense) net」，营业外那行整行取不到（C4 抓出）
VALTOK = re.compile(r"(?<![\w.])(\(?\$?\s?(?:\d[\d,]*(?:\.\d+)?|\.\d+)\)?|--+|—)(?![\w])")


def parse_txt_table(block, head, maxcols):
    lines = block.expandtabs(8).split("\n")
    hdr_i, cols = None, []
    for i, ln in enumerate(lines[:25]):
        toks = [(m.group(), m.start(), m.end()) for m in re.finditer(r"\b(19|20)\d\d\b", ln)]
        if len(toks) >= 2 and not re.search(r"\d[,.]\d", ln):
            hdr_i, cols = i, toks
            break
    if hdr_i is None or len(cols) > maxcols:
        return None
    years = [int(t[0]) for t in cols]
    ends = [t[2] for t in cols]
    cut = cols[0][1] - 3
    # 招股书五年摘要首列「December 31, 1993」比数值列宽，标签区截断点取该行首个年份所在词组左缘
    m0 = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+"
                   + str(years[0]), lines[hdr_i])
    if m0 and m0.start() < cut:
        cut = m0.start() - 1
    scale = unit_scale(block) or unit_scale(head)          # 单位行可能在表外
    if scale is None:
        return None
    rows, prev_head = [], ""
    for ln in lines[hdr_i + 1:]:
        raw = strip_leaders(ln.rstrip())
        if not raw.strip() or set(raw.strip()) <= set("-=_ "):
            continue
        if raw.strip().startswith("<") and raw.strip().endswith(">"):   # <S> <C> 之类 SGML 标记行
            continue
        # 标签折行里的日期「January 31, 1998」——年份不是数值（招股书普通股那行就被截走过一个 1,998）。
        # 🔴 VALTOK 的组会带前导空格（「 1998」），判年份前必须 strip，否则 fullmatch 恒不中、过滤形同虚设
        mm = [m for m in VALTOK.finditer(raw) if m.end() >= cut
              and not (re.fullmatch(r"(19|20)\d\d", m.group().strip().rstrip(",;"))
                       and re.search(r"(\d{1,2},|\bin|\band|\bat)\s*$", raw[:m.start()]))]
        toks = [(m.group(), m.end()) for m in mm]
        # 标签区止于「截断点」与「第一个数值 token 起点」中较小者（FY2001 无标签总资产行「$1,016,427」
        # 跨过截断点，第一版把「$1」留在了标签里）
        lab_end = min([cut] + [m.start() + (len(m.group()) - len(m.group().lstrip())) for m in mm])
        label = re.sub(r"[.\s$]+$", "", clean(raw[:lab_end] if len(raw) > lab_end else raw))
        label = re.sub(r"^- +", "", label)
        if not toks:
            if label:
                rows.append({"label": label, "vals": [None] * len(years)})
                if label.endswith(":"):
                    prev_head = label
            continue
        if not label and prev_head:
            label = prev_head.rstrip(":") + " 合计"
        vals = [None] * len(years)
        dash = [False] * len(years)          # ① 「--」= 本行在该列为零（行存在、数为零），与「无此行」区分
        if len(toks) == len(years):
            for j, (tok, _) in enumerate(toks):
                vals[j] = tonum(tok)
                dash[j] = bool(NIL.match(tok.strip()))
        else:
            for tok, e in toks:
                j = min(range(len(ends)), key=lambda k: abs(ends[k] - e))
                if vals[j] is None and not dash[j]:
                    vals[j] = tonum(tok)
                    dash[j] = bool(NIL.match(tok.strip()))
        rows.append({"label": label, "vals": vals, "dash": dash})
        if label.endswith(":"):
            prev_head = label
    return scale, years, merge_wraps(rows)


def parse_txt(key, path):
    s = open(path, encoding="latin-1", errors="ignore").read()
    blocks = [(m.start(), m.group(1)) for m in re.finditer(r"<TABLE>(.*?)</TABLE>", s, re.S | re.I)]
    pros = key == "prospectus"
    out = {}
    for slot, pat in TITLES.items():
        best, bestsc = None, 0
        maxc = PROSPECTUS_MAX[slot] if pros else MAXYEARS[slot]
        for pos, b in blocks:
            # 五年摘要的标题与表格之间隔着一两段「应与……一并阅读」说明，窗口放宽到 3000 字符
            win = 3000 if slot == "SUM" else 450
            head = s[max(0, pos - max(600, win)):pos]
            if not re.search(pat, head[-win:], re.I):
                continue
            sc = score(b, slot)
            if sc < MINSCORE[slot] or sc <= bestsc:
                continue
            p = parse_txt_table(b, head, maxc)
            if not p:
                continue
            if pros:
                exp_years, _ = PROSPECTUS_COLS[slot]
                if p[1] != exp_years:
                    continue
            best, bestsc = p, sc
        if not best:
            continue
        scale, years, rows = best
        if pros:
            keys = PROSPECTUS_COLS[slot][1]
        else:
            keys = [year_key(y) for y in years]
            if len(set(keys)) != len(keys):
                raise SystemExit(f"❌ {key} {slot} 列键重复 {keys} —— 年份 token 重复，须显式指定列键")
        out[slot] = {"scale": scale, "years": keys, "rows": rows, "src": "txt"}
    if key in ("prospectus", "s1"):
        # 五年摘要下半张资产负债摘要：标题在上一张表之前，按「Balance Sheet Data + Total assets」认表
        for pos, b in blocks:
            if "balance sheet data" in b.lower() and "total assets" in b.lower():
                p = parse_txt_table(b, s[max(0, pos - 600):pos], PROSPECTUS_MAX["SUMBS"])
                if not p:
                    continue
                if pros and p[1] == PROSPECTUS_COLS["SUMBS"][0]:
                    out["SUMBS"] = {"scale": p[0], "years": PROSPECTUS_COLS["SUMBS"][1], "rows": p[2], "src": "txt"}
                    break
                if not pros and p[1] == [1993, 1994, 1995, 1996, 1997]:
                    out["SUMBS"] = {"scale": p[0], "years": [str(y) for y in p[1]], "rows": p[2], "src": "txt"}
                    break
    # 资产负债表在 FY1999 版式里被拆成两个 <TABLE>（资产 / 负债及权益），第二块无表头年份 → 接到第一块后
    if "BS" in out and not any(re.search(r"total stockholders", r["label"], re.I) for r in out["BS"]["rows"]):
        out["BS"] = stitch_bs(s, blocks, out["BS"])
    if "BS" in out:
        out["BS"]["rows"] = name_bs_totals(out["BS"]["rows"])
    return out


def name_bs_totals(rows):
    """文本版式资产负债表的两条合计不印标签：「总资产」紧跟非流动资产之后、「负债及权益合计」紧跟权益合计之后。
    解析时它们被命名成「<段首> 合计」（如「Current assets 合计」，名不副实）→ 按位置改成真名。"""
    out, seen_tca, seen_teq, seen_liab = [], False, False, False
    for r in rows:
        lab = r["label"].lower()
        if "total current assets" in lab:
            seen_tca = True
        if re.search(r"liabilities and (stockholders|shareholders)", lab) or lab.startswith("current liabilities"):
            seen_liab = True
        if re.search(r"total (stockholders|shareholders)'? equity", lab):
            seen_teq = True
        if r["label"].endswith(" 合计") or r["label"] == "负债与权益合计(无标签行)":
            if seen_teq:
                r = dict(r, label="Total liabilities and stockholders' equity (无标签合计行)")
            elif seen_tca and not seen_liab:
                r = dict(r, label="Total assets (无标签合计行)")
        out.append(r)
    return out


def stitch_bs(s, blocks, bs):
    """FY1999 资产负债表：第一块到「总资产」止，紧跟的第二块是负债与权益（只有 <S><C> 标记、无表头）。"""
    n = len(bs["years"])
    for k, (pos, b) in enumerate(blocks):
        if "total current assets" in b.lower() and k + 1 < len(blocks):
            nb = blocks[k + 1][1]
            if "total stockholders" not in nb.lower():
                continue
            lines = nb.expandtabs(8).split("\n")
            first = [ln for ln in lines if VALTOK.search(strip_leaders(ln)) and re.search(r"[A-Za-z]", ln)]
            if not first:
                continue
            # 以第一块的数值列右端位置为准（两块的列宽一致）
            ref = [ln for ln in b.expandtabs(8).split("\n") if re.search(r"\b(19|20)\d\d\b", ln)]
            ends = [m.end() for m in re.finditer(r"\b(19|20)\d\d\b", ref[-1])] if ref else []
            if len(ends) != n:
                continue
            # 数值右对齐到表头年份末端、最宽「$113,332」8 字符 → 截断点 = 最左年份末端 − 9
            # （第一版 −12 把「Capital lease obligations, less current portion」截成「…portio」）
            cut = min(ends) - 9
            rows = []
            for ln in lines:
                raw = strip_leaders(ln.rstrip())
                if not raw.strip() or set(raw.strip()) <= set("-=_ ") or raw.strip().startswith("<"):
                    continue
                toks = [(m.group(), m.end()) for m in VALTOK.finditer(raw) if m.end() >= cut]
                label = re.sub(r"[.\s$]+$", "", clean(raw[:cut] if len(raw) > cut else raw))
                vals, dash = [None] * n, [False] * n
                for tok, e in toks:
                    j = min(range(n), key=lambda q: abs(ends[q] - e))
                    if vals[j] is None and not dash[j]:
                        vals[j] = tonum(tok)
                        dash[j] = bool(NIL.match(tok.strip()))
                if not label and toks:
                    label = "负债与权益合计(无标签行)"
                if label:
                    rows.append({"label": label, "vals": vals, "dash": dash})
            out = dict(bs)
            out["rows"] = bs["rows"] + merge_wraps(rows)
            return out
    return bs


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


PURENUM = re.compile(r"\(?\$?\s?(?:\d[\d,]*(?:\.\d+)?|\.\d+)\)?")


def header_years(grid):
    """③ 前 8 行里找出 ≥2 个「(月 日,) 年」格的那一行；表头被拆成「January 31,」/「2010」两行时也认。"""
    for cells in grid[:8]:
        ys = [int(HDRYEAR.match(t).group(1)) for c, n, t in cells if t and HDRYEAR.match(t)]
        if len(ys) >= 2:
            return ys
    return []


def parse_html_table(table_html, head, maxcols):
    grid = grid_rows(table_html)
    if not grid:
        return None
    flat = clean(table_html)
    scale = unit_scale(flat[:500]) or unit_scale(clean(head)[-300:])
    years = header_years(grid)
    if not years or len(years) > maxcols:
        return None
    cnt = {}
    for cells in grid:
        for c, n, t in cells:
            if t and t not in ("$", "(", ")") and PURENUM.fullmatch(t.replace(" ", "")) and not YEAR.match(t):
                cnt[c] = cnt.get(c, 0) + 1
    if len(cnt) < len(years):
        return None
    ranked = sorted(cnt, key=lambda c: (-cnt[c], c))
    # 🔴 列数闸：第 N+1 多的数值列若与第 N 列同量级，说明表头少认了一个年份——宁可拒绝，不许静默丢列
    # （FY2011 现金流量表实证：3 列数据只认出 2 个年份，丢掉的那列不报错，剩下两列看起来完全正常）
    if len(ranked) > len(years) and cnt[ranked[len(years)]] >= 0.5 * cnt[ranked[len(years) - 1]]:
        print(f"  ⚠️ 列数闸拒绝：识别出 {len(years)} 个年份 {years}，但数值列 {len(ranked)} 列"
              f"（第 {len(years)+1} 列 {cnt[ranked[len(years)]]} 格）", file=sys.stderr)
        return None
    vcols = sorted(ranked[:len(years)])
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
        if not label and prev_head and any(texts.get(vc) and PURENUM.fullmatch(texts[vc].replace(" ", ""))
                                           for vc in (c for c, n, t in cells)):
            label = prev_head.rstrip(":") + " 合计"
        if not label or YEAR.match(label) or HDRYEAR.match(label):
            continue
        vals, dash = [], []
        for vc in vcols:
            t = texts.get(vc, "")
            # 「—」可能落在数值列左右相邻的格里（$ 符号格 / 括号格），在 vc-1..vc+1 里找
            nil_here = any(NIL.match(texts.get(c2, "") or "x") for c2 in (vc - 1, vc, vc + 1))
            if not t or t in ("$", "(", ")") or NIL.match(t):
                vals.append(None)
                dash.append(bool(nil_here))
                continue
            if not PURENUM.fullmatch(t.replace(" ", "")):
                vals.append(None)
                dash.append(False)
                continue
            neg = t.startswith("(") or texts.get(vc - 1, "") == "(" or texts.get(vc + 1, "") == ")"
            v = tonum(t)
            vals.append(-abs(v) if (neg and v is not None) else v)
            dash.append(False)
        rows.append({"label": label, "vals": vals, "dash": dash})
    return scale, years, merge_wraps(rows)


def parse_html(key, path):
    s = open(path, encoding="utf-8", errors="ignore").read()
    tables = [(m.start(), m.group(1)) for m in re.finditer(r"<table[^>]*>(.*?)</table>", s, re.S | re.I)]
    out = {}
    for slot, pat in TITLES.items():
        best, bestsc = None, 0
        for pos, t in tables:
            head = s[max(0, pos - (8000 if slot == "SUM" else 2500)):pos]
            hflat = clean(head)[-(1500 if slot == "SUM" else 260):]
            flat = clean(t)
            if not (re.search(pat, hflat, re.I) or re.search(pat, flat[:200], re.I)):
                continue
            sc = score(flat, slot) if slot == "SUM" else score(hflat[-120:] + " " + flat, slot)
            if sc < MINSCORE[slot] or sc <= bestsc:
                continue
            p = parse_html_table(t, head, MAXYEARS[slot])
            if p and p[0]:
                best, bestsc = p, sc
        if best:
            scale, years, rows = best
            keys = [year_key(y) for y in years]
            out[slot] = {"scale": scale, "years": keys, "rows": rows, "src": "htm"}
    if "BS" in out:                     # FY2002-2007 HTML 版式「总资产」同样不印标签
        out["BS"]["rows"] = name_bs_totals(out["BS"]["rows"])
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    only = [a for a in sys.argv[1:]]
    for key in FILINGS:
        if only and key not in only:
            continue
        path = os.path.join(REPORT, FILINGS[key])
        if not os.path.exists(path):
            print(f"MISS {key}: {path}")
            continue
        got = parse_txt(key, path) if path.endswith(".txt") else parse_html(key, path)
        json.dump({"key": key, "statements": got},
                  open(os.path.join(OUT, f"{key}.json"), "w"), ensure_ascii=False, indent=1)
        print(f"{key}: " + (", ".join(
            f"{k}(cols={v['years']},scale={v['scale']},rows={len(v['rows'])})"
            for k, v in sorted(got.items())) or "NOTHING"))


if __name__ == "__main__":
    main()
