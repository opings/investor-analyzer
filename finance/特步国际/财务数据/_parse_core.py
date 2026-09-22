#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""特步国际三表解析内核 —— 文本层 / 列几何 / 标签归一 / 定位 / 取行。

被 `_build_from_pdf.py` 引入。独立成文件是因为「解析」与「别名层+校验+写出」
是两件事：解析规则稳定后基本不动，别名层会随新年份科目改名而增补。

本文件踩过并已固化的三个坑（改动前先读）：

  ① **标题跨行印**：2015-2019 年报把 "CONSOLIDATED STATEMENT OF" 与
     "FINANCIAL POSITION" 印成两行 —— 单行正则会整张资产负债表漏配。
     故标题匹配一律按 1-3 行窗口拼接后再比。

  ② **装饰字体编码偏移**：2011/2012 年报的表标题在文本层是
     `$0/40-*%"5&%*/$0.&` —— 每个可见字节 **+31** 才是 `CONSOLIDATEDINCOME`。
     这不是文件坏，是该字体用了自定义编码；**数据行本身完全正常**。
     故标题候选须同时试原串与 +31 解码串，否则这两年整表丢失。

  ③ **表尾要靠分页符收**：靠"下一张表的标题"收尾会漏（标题可能正是 ① 或 ②
     的形态），一路吃进权益变动表和附注。故按 \f 分页收集，命中该表的终止锚
     即停，最多跨 3 页。
"""
import os
import re
import subprocess
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
PDF_DIR = os.path.join(ROOT, "report", "特步国际")
CACHE = os.path.join(HERE, ".txtcache")
PDFTOTEXT = "/opt/homebrew/bin/pdftotext"

PRE_IPO = [2005, 2006, 2007]
AR_YEARS = list(range(2008, 2026))
ALL_YEARS = PRE_IPO + AR_YEARS
PROSPECTUS = "特步国际-招股说明书"

# ─────────────────────────── 文本层 ───────────────────────────


def ensure_text(name):
    os.makedirs(CACHE, exist_ok=True)
    txt = os.path.join(CACHE, f"{name}.txt")
    if not os.path.exists(txt):
        pdf = os.path.join(PDF_DIR, f"{name}.pdf")
        if not os.path.exists(pdf):
            raise SystemExit(f"🔴 缺一手 PDF: {pdf}")
        subprocess.run([PDFTOTEXT, "-layout", pdf, txt], check=True,
                       stderr=subprocess.DEVNULL)
    with open(txt, encoding="utf-8", errors="replace") as f:
        return f.read()


def pages(name):
    """PDF 文本按 \f 切页 → [[行, ...], ...]（页内保留原始行，含列位置）。"""
    return [p.splitlines() for p in ensure_text(name).split("\f")]


# ─────────────────────────── 列几何 ───────────────────────────

NUM_RE = re.compile(
    r"\(\s*(?P<d1>[\d][\d,]*(?:\.\d+)?)\s*\)"      # (1,234) / (1,234 ) = 负数
    r"|(?P<d2>-?[\d][\d,]*(?:\.\d+)?)"             # 1,234
    r"|(?P<na>N/A|不適用)"
    r"|(?P<dash>[–—－](?=\s|$))"                     # 破折号 = 空值
)
YEAR_RE = re.compile(r"(?<![\d,.])(20[0-2]\d)(?![\d,.%])")


def disp_col(s, idx):
    """字符下标 idx 处的**显示列**（CJK 全角算 2 列）。

    pdftotext -layout 按显示宽度对齐、Python 下标按字符数 —— 混用会让含中文的
    行与右对齐的数字列整体错位（特步 2009/2010 年报中英混排，必踩）。
    """
    w = 0
    for ch in s[:idx]:
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def tok_value(m):
    if m.group("dash") is not None or m.group("na") is not None:
        return None
    if m.group("d1") is not None:
        return -float(m.group("d1").replace(",", ""))
    return float(m.group("d2").replace(",", ""))


def _tok_pos(m, which):
    for g in ("d1", "d2", "na", "dash"):
        if m.group(g) is not None:
            return getattr(m, which)(g)
    return getattr(m, which)()


def tok_end(m):
    return _tok_pos(m, "end")


def tok_start(m):
    return _tok_pos(m, "start")


# ─────────────────────────── 标签归一 ───────────────────────────

LIG = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
       "’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"}


def deshift(s):
    """坑②：装饰字体编码偏移 —— 可见字节 +31 还原（空格不动）。"""
    return "".join(chr(ord(c) + 31) if 33 <= ord(c) < 96 else c for c in s)


def norm_label(s):
    for k, v in LIG.items():
        s = s.replace(k, v)
    s = re.sub(r"(\s*\.){3,}", " ", s)              # 点引线 "Revenue . . . ."
    s = re.sub(r"[^0-9A-Za-z\s/&'()-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    s = re.sub(r"\s*\(?notes?\s*\d*[a-z]?\)?$", "", s).strip()
    # 尾随附注号：裸数字（"reserves 28"）或带子项（"reserves 29(a)" —— FY2009 实证，
    # 不剥就配不上别名层、整年权益缺行）
    s = re.sub(r"\s+\d{1,2}\s*\(\s*[a-z]\s*\)\s*$", "", s).strip()
    s = re.sub(r"\s+\d{1,2}\s*$", "", s).strip()
    s = s.rstrip("( ").strip()                      # 负数左括号被吃进标签尾
    return s


# 页眉/页脚/表头噪声行 —— 不是科目
JUNK = re.compile(
    r"^(notes?|rmb|year ended|annual report|xtep international|continued|"
    r"attributable to|earnings per share|to profit or loss|of the company|"
    r"directly recognised|exchange realignment on|\d{1,3}$)"
    r"|annual report \d{4}|xtep international holdings"
)


# ─────────────────────────── 定位三表 ───────────────────────────

# ⚠️ 首尾锚定（fullmatch 语义）是刻意的：标题必须**整行自成一句**。
# 只在尾部锚定会把散文句钓上来 —— 招股书「…summary consolidated income statements,
# balance sheets and cash flow information was derived from…」曾因此被当成正表，
# 且因行数更多而在打分中胜出，把「摘要节」当成了会计师报告正表。
TITLE_PAT = {
    "IS": re.compile(r"^consolidated ?income ?statements?$"),
    "BS": re.compile(r"^consolidated ?(statements? ?of ?financial ?position"
                     r"|balance ?sheets?)$"),
    "CF": re.compile(r"^consolidated ?(statements? ?of ?)?cash ?flows?"
                     r"( ?statements?)?$"),
}
# 正表骨架 —— 选表时优先按覆盖度打分，防「行数最多者胜」挑中衍生表
SKELETON = {
    "IS": ("revenue", "cost of sales", "gross profit", "profit for the year"),
    "BS": ("total current assets", "total current liabilities", "share capital",
           "reserves"),
    "CF": ("operating activities", "investing activities", "financing activities",
           "end of"),
}
# 每张表的终止锚（命中后于本页末收尾）
TERMINAL = {
    "IS": re.compile(r"^(- )?diluted|^profit for the year$|^profit attributable"),
    "BS": re.compile(r"^total equity$|^total equity and liabilities$"),
    "CF": re.compile(r"cash and cash equivalents at (the )?end of (the )?year"),
}
OTHER_TITLE = re.compile(
    r"consolidated statements? of changes in equity|consolidatedstatementofchanges"
    r"|notes to (the )?(consolidated )?financial statements|notestofinancial")


# 页眉页脚碎片 —— 会插在跨行标题中间把它切断
# （2012 年报印成 "Consolidated   ANNUAL REPORT 2012 / 86" 换行 "Income Statement"）
FURNITURE = re.compile(
    r"annual report( \d{4})?|xtep international holdings limited"
    r"|xtep international|\b\d{1,3}\b")


def _strip_furniture(s):
    return re.sub(r"\s+", " ", FURNITURE.sub(" ", s)).strip()


def _cands(lines, i, n=4):
    """第 i 行起最多 n 行拼接 → 归一候选。

    四种变体都要试：原串 / +31 解码串（坑②）× 含页眉 / 剥页眉（跨行标题被页眉切断）。
    再各加一个「去空格」变体 —— 坑② 解码后单词间无空格。
    """
    out, buf = [], ""
    for k in range(n):
        if i + k >= len(lines):
            break
        buf = (buf + " " + lines[i + k]).strip()
        for v in (buf, deshift(buf)):
            nv = norm_label(v)
            for w in (nv, _strip_furniture(nv)):
                out.append(w)
                out.append(w.replace(" ", ""))
    return out


def find_title_pages(name, kind):
    """返回 [(页号, 页内行号)]，即该表标题出现处（排除目录页）。"""
    pgs = pages(name)
    hits = []
    for pi, lines in enumerate(pgs):
        for i in range(len(lines)):
            raw = " ".join(lines[i].split())
            if not raw:
                continue
            matched = any(TITLE_PAT[kind].search(c) for c in _cands(lines, i))
            if not matched:
                continue
            # 目录页特征：行首/行尾挂页码
            if re.match(r"^\d{1,3}\s+\D", raw) or re.search(r"\s\d{2,3}$", raw):
                continue
            hits.append((pi, i))
            break
    return hits


JAN1 = re.compile(r"1\s+January", re.I)
RESTATED = re.compile(r"\(\s*restated\s*\)", re.I)


def col_anchors(lines, start, lookahead=14):
    """标题后找年份表头行 → ([(year, 显示列)], Notes 列, 表头行号, 重述列)。

    ⚠️ 三栏资产负债表：追溯重述那年（特步 FY2024）表头是
        「31 December 2024 | 31 December 2023 | 1 January 2023」，**2023 出现两次**。
       早先要求「年份互不相同」会把整张表拒掉。这里改为：读年份行**上方**的日期行，
       凡该列写「1 January YYYY」就归到 **YYYY-1**（1 月 1 日余额 = 上年 12 月 31 日），
       映射后再要求互不相同。这一栏是白捡的重述期初数。
    """
    for i in range(start, min(start + lookahead, len(lines))):
        ys = [(int(m.group(1)), disp_col(lines[i], m.end(1)))
              for m in YEAR_RE.finditer(lines[i])]
        if len(ys) < 2:
            continue
        # 上方日期行：定位每个「1 January」的显示列，归到最近的年份列
        jan_cols = []
        for k in range(max(0, i - 3), i):
            for m in JAN1.finditer(lines[k]):
                jan_cols.append(disp_col(lines[k], m.end()))
        if jan_cols:
            fixed = []
            for y, c in ys:
                near = any(abs(c - jc) <= 14 for jc in jan_cols)
                fixed.append((y - 1 if near else y, c))
            ys = fixed
        if len({y for y, _ in ys}) != len(ys):
            continue
        note_col = None
        for k in range(max(0, i - 2), min(i + 3, len(lines))):
            m = re.search(r"\bNotes?\b", lines[k])
            if m:
                note_col = disp_col(lines[k], m.end())
                break
        restated = [c for k in range(i, min(i + 3, len(lines)))
                    for c in [disp_col(lines[k], m.end())
                              for m in RESTATED.finditer(lines[k])]]
        return ys, note_col, i, restated
    return None, None, None, None


SECTION = [
    ("非流动资产", re.compile(r"^non-?current assets$")),
    ("流动资产", re.compile(r"^current assets$")),
    ("流动负债", re.compile(r"^current liabilities$")),
    ("非流动负债", re.compile(r"^non-?current liabilities$")),
    ("权益", re.compile(r"^(equity|capital and reserves)$")),
    ("经营", re.compile(r"cash flows? from operating activities|operating activities$")),
    ("投资", re.compile(r"cash flows? from investing activities|investing activities$")),
    ("融资", re.compile(r"cash flows? from financing activities|financing activities$")),
]


def _section_of(label, cur):
    for name, pat in SECTION:
        if pat.search(label):
            return name
    return cur


def _rows_in(lines, frm, cols, note_col, tol):
    """逐行取数 → [(标签, [值], 节区)]。

    **折行标签合并**：长科目名折到第二行、数值印在第二行时，第二行看上去是个
    独立行（如 "through other comprehensive income"），必须把上一行无数值的文字
    接回去，否则科目名残缺、别名层对不上。判据 = 本行以**小写字母或破折号**开头
    （英文续行 / 项目符号特征），而节标题是大写。

    **节区跟踪**：资产负债表里「计息银行借贷 / 租赁负债 / 定期存款 / 可换股债券」
    等在流动与非流动两节**同名**，不带节区就会互相覆盖。节标题本身无数值、
    会走 pending 分支，故在那里顺手记下当前节区。
    """
    out, pending, sec = [], None, ""
    for i in range(frm, len(lines)):
        raw = lines[i]
        if not raw.strip():
            pending = None
            continue
        vals = [None] * len(cols)
        first, got = None, False
        for m in NUM_RE.finditer(raw):
            p = disp_col(raw, tok_end(m))
            if note_col is not None and abs(p - note_col) <= 7:
                if first is None:
                    first = tok_start(m)
                continue
            d = [abs(p - c) for c in cols]
            j = d.index(min(d))
            if d[j] > tol:
                continue
            if first is None:
                first = tok_start(m)
            if vals[j] is None:
                vals[j] = tok_value(m)
                got = True
        frag = raw[:first] if first is not None else raw
        label = norm_label(frag)
        if not got:
            sec = _section_of(label, sec)
            pending = frag.strip() if label and not JUNK.search(label) else None
            continue
        head = frag.strip()[:1]
        if pending and (head.islower() or head in ("-", "–", "—")):
            label = norm_label(pending + " " + frag)
        pending = None
        if label and not JUNK.search(label):
            out.append((label, vals, sec))
    return out


def statement(name, kind, max_pages=3):
    """取某份 PDF 的某张表 → (anchors, rows, 重述列)。

    选表按 **骨架覆盖度优先、行数次之**（不是纯行数）—— 纯行数会挑中衍生表。
    """
    pgs = pages(name)
    best = None
    for pi, li in find_title_pages(name, kind):
        anchors, note_col, hdr, restated = col_anchors(pgs[pi], li)
        if not anchors:
            continue
        cols = [c for _, c in anchors]
        gap = (min(cols[k + 1] - cols[k] for k in range(len(cols) - 1))
               if len(cols) > 1 else 20)
        tol = max(6, gap * 0.45)
        rows = _rows_in(pgs[pi], hdr + 1, cols, note_col, tol)
        done = any(TERMINAL[kind].search(r[0]) for r in rows)
        # 续页：表未收尾则继续吃，遇到别的表标题即止
        p = pi + 1
        while not done and p < len(pgs) and p - pi < max_pages:
            txt = norm_label(" ".join(pgs[p][:12]))
            if OTHER_TITLE.search(txt) or OTHER_TITLE.search(txt.replace(" ", "")):
                break
            a2, n2, h2, _r2 = col_anchors(pgs[p], 0)
            if a2 and [y for y, _ in a2] == [y for y, _ in anchors]:
                c2 = [c for _, c in a2]
                more = _rows_in(pgs[p], h2 + 1, c2, n2, tol)
            else:
                more = _rows_in(pgs[p], 0, cols, note_col, tol)
            if not more:
                break
            rows.extend(more)
            done = any(TERMINAL[kind].search(r[0]) for r in more)
            p += 1
        labs = " || ".join(r[0] for r in rows)
        score = sum(1 for k in SKELETON[kind] if k in labs)
        if best is None or (score, len(rows)) > (best[0], len(best[3])):
            best = (score, anchors, restated, rows)
    return (best[1], best[3], best[2]) if best else None
