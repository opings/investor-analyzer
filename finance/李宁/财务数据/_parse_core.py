#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""李宁三表解析内核 —— 文本层 / 列几何 / 标签归一 / 定位 / 取行。

被 `_build_from_pdf.py` 引入。独立成文件是因为「解析」与「别名层+校验+写出」
是两件事：解析规则稳定后基本不动，别名层会随年份科目改名而增补。

数据源 25 年跨三套报表命名习惯，本文件处理的是**版式**，不是科目名（科目名归
别名层）。侦察阶段实测、必须固化的六个坑（改动前先读）：

  ① **三代表名**。利润表：`Consolidated Profit and Loss Account`(2004) →
     `Consolidated Income Statement`(2005-2024) → `CONSOLIDATED STATEMENT OF
     PROFIT OR LOSS`(2025)。现金流表：`Cash Flow Statement`(2004-2010) →
     `Statement of Cash Flows`(2011+)。招股书用 `Combined ...`。
     只认一代 = 整年整表丢失。

  ② **字间随机插空格**。2005/2008 年报印成 `C ons olidate d Income St atement`、
     `As a t 31 December 2005`。这不是文件坏，是字体 kerning 落到文本层。
     故标题候选一律追加「去掉全部空格」变体。

  ③ **标题跨行印**。2024 年报把 `CONSOLIDATED` 与 `INCOME STATEMENT` 印成两行。
     故标题匹配按 1-4 行窗口拼接后再比。

  ④ **首尾锚定（fullmatch 语义）是刻意的**。只在尾部锚定会把散文句钓上来 ——
     招股书 p171「The following is a summary of the combined profit and loss
     accounts of the Group...」若被当成正表，会因所在节行数更多而在打分中胜出。

  ⑤ **必须排除「本公司」单体表**。2025 年报附注 40 是 `STATEMENT OF FINANCIAL
     POSITION AND RESERVE MOVEMENT OF THE COMPANY`（母公司单体），早年亦有
     `Balance Sheet of the Company`。当成合并表取走 = 主体口径整张错。

  ⑥ **表尾靠分页符收**。靠「下一张表的标题」收尾会漏（标题可能正是 ②③ 的形态），
     一路吃进权益变动表和附注。故按 \f 分页收集，命中该表终止锚即停，最多跨 3 页。
"""
import os
import re
import subprocess
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
PDF_DIR = os.path.join(ROOT, "report", "李宁")
CACHE = os.path.join(HERE, ".txtcache")
PDFTOTEXT = "/opt/homebrew/bin/pdftotext"

# 上市 2004-06-28（招股书 p168「dealings … expected to commence … 28 June, 2004」）。
# 招股书附录一会计师报告（PwC，2004-06-15）给 2001/2002/2003 三年 → 序列起点 2001。
PRE_IPO = [2001, 2002, 2003]
AR_YEARS = list(range(2004, 2026))
ALL_YEARS = PRE_IPO + AR_YEARS
PROSPECTUS = "李宁-招股说明书"


def ar_name(y):
    return f"李宁-{y}"


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
YEAR_RE = re.compile(r"(?<![\d,.])(19[89]\d|20[0-2]\d)(?![\d,.%])")


def disp_col(s, idx):
    """字符下标 idx 处的**显示列**（CJK 全角算 2 列）。

    pdftotext -layout 按显示宽度对齐、Python 下标按字符数 —— 混用会让含中文的
    行与右对齐的数字列整体错位（2007/2008 年报中英混排，必踩）。
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
    """装饰字体编码偏移 —— 可见字节 +31 还原（空格不动）。

    李宁 25 份里暂未实测到此形态，保留是**廉价保险**：同代港股年报（特步
    2011/2012）确有，且一旦出现是整表静默丢失、不报错。
    """
    return "".join(chr(ord(c) + 31) if 33 <= ord(c) < 96 else c for c in s)


def norm_label(s):
    for k, v in LIG.items():
        s = s.replace(k, v)
    s = re.sub(r"(\s*\.){3,}", " ", s)              # 点引线 "Revenue . . . ."
    s = re.sub(r"[^0-9A-Za-z\s/&'()-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    s = re.sub(r"^\(?[a-z]\)\s+", "", s)            # 招股书小节号 "(a) Combined ..."
    s = re.sub(r"^[ivx]+\.\s+", "", s)              # 罗马小节号
    # 行首印刷页码：2006 年报把页码 74 印在现金流合计行左边
    # (`74 net cash generated from/(used in) in investing activities`)，
    # 不剥掉就没法用 `^net cash` 锚定合计行、从而与明细行区分。
    s = re.sub(r"^\d{1,3}\s+(?=[a-z])", "", s)
    s = re.sub(r"\s*\(?notes?\s*\d*[a-z]?\)?$", "", s).strip()
    # ⚠️ 顺序要紧：先剥掉被吃进标签尾的负数左括号，再剥尾随数字。
    # 反过来会让 `Cost of sales   25   (4,886,440)` 的标签停在 `cost of sales 25 (`——
    # 尾随数字正则因末尾是「(」而不匹配，附注号 25 就永久粘在科目名上（2011 年报实测）。
    s = s.rstrip("( ").strip()                      # 负数左括号被吃进标签尾
    s = re.sub(r"\s+\d{1,3}\s*$", "", s).strip()    # 尾随附注号 / 行末印刷页码(可达 3 位)
    s = s.rstrip("( ").strip()
    return s


def despace(s):
    """去掉全部空格 —— 坑②（2005/2008 字间随机插空格）的通用解药。

    比对科目名时必须两路都试：`gr oss pr ofit` 只有去空格后才等于 `grossprofit`。
    """
    return re.sub(r"\s+", "", s)


def label_variants(s):
    """一个标签的可比形态：原样 + 去空格。别名层与骨架打分都用它。"""
    n = norm_label(s) if not s.islower() or " " in s else s
    return (n, despace(n))


# 页眉/页脚/表头噪声行 —— 不是科目
JUNK = re.compile(
    r"^(notes?|rmb|year ended|as at|annual report|li ning|continued|"
    r"attributable to|earnings per share|to profit or loss|of the company|"
    r"appendix|accountants|section ii|expressed in|all amounts in|"
    r"restated|reclassified|continuing operations|discontinued operations|"
    r"the (consolidated )?financial statements on pages|"   # 董事会批准语被当成科目行
    r"\d{1,3}$)"
    r"|annual report \d{4}|li ning company limited"
)


# ─────────────────────────── 定位三表 ───────────────────────────

# 坑① 三代表名 + 招股书 combined 口径；坑④ 首尾锚定
TITLE_PAT = {
    "IS": re.compile(
        r"^(consolidated|combined) ?"
        r"(profit ?and ?loss ?accounts?"
        r"|income ?statements?"
        r"|statements? ?of ?profit ?or ?loss)$"),
    "BS": re.compile(
        r"^(consolidated|combined) ?"
        r"(balance ?sheets?"
        r"|statements? ?of ?financial ?position)$"),
    "CF": re.compile(
        r"^(consolidated|combined) ?"
        r"(cash ?flow ?statements?"
        r"|statements? ?of ?cash ?flows?)$"),
}
# 坑⑤ 母公司单体表 / 附注里的同名表 —— 命中即弃
EXCLUDE_TITLE = re.compile(
    r"of ?the ?company|company ?only|reserve ?movement|notes? ?to")

# 正表骨架 —— 选表按覆盖度打分，防「行数最多者胜」挑中摘要节或衍生表
SKELETON = {
    "IS": ("revenue|turnover", "cost of sales|costs of sales", "gross profit",
           "profit for the year|profit after taxation"),
    "BS": ("total assets|total current assets", "inventories",
           "total equity|owners' equity|total liabilities"),
    "CF": ("operating activities", "investing activities", "financing activities",
           "end of"),
}
# 每张表的终止锚（命中后于本页末收尾）
TERMINAL = {
    "IS": re.compile(r"^(- )?diluted|^profit for the year$|^profit attributable"
                     r"|^basic earnings per|^dividends$"),
    # ⚠️ **不要**把 `^total equity$` 当资产负债表终止锚。李宁用的 IFRS 版式顺序是
    # 资产 → 权益 → 负债，「Total equity」印在第 1 页末尾、负债段整个在第 2 页。
    # 以它收表 → 20 个年份的负债段全部丢失（实测：total liabilities 只剩 9 年有值），
    # 勾稽第三条「资产 = 负债 + 权益」与有息负债排雷直接做不了。
    "BS": re.compile(r"^total equity and liabilities$|^total liabilities and equity$"
                     r"|^total liabilities$"),
    "CF": re.compile(r"cash and cash equivalents at (the )?end of (the )?"
                     r"(year|period|financial year)"),
}
OTHER_TITLE = re.compile(
    r"consolidated statements? of changes in equity|consolidatedstatementofchanges"
    r"|combined statements? of changes in owners' equity"
    r"|notes to (the )?(consolidated|combined)? ?(financial statements|accounts)"
    r"|notestofinancial")


# 页眉页脚碎片 —— 会插在跨行标题中间把它切断
FURNITURE = re.compile(
    r"annual report( \d{4})?|li ning company limited|li ning"
    r"|appendix [ivx]+|accountants'? report|\b\d{1,3}\b")


def _strip_furniture(s):
    return re.sub(r"\s+", " ", FURNITURE.sub(" ", s)).strip()


def _cands(lines, i, n=4):
    """第 i 行起最多 n 行拼接 → 归一候选。

    变体矩阵：原串 / +31 解码串（保险）× 含页眉 / 剥页眉（坑③ 跨行标题被页眉
    切断）× 保留空格 / 去掉全部空格（坑② 字间插空格）。
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
    """返回 [(页号, 页内行号)]，即该表标题出现处（排除目录页与单体表）。"""
    pgs = pages(name)
    hits = []
    for pi, lines in enumerate(pgs):
        for i in range(len(lines)):
            raw = " ".join(lines[i].split())
            if not raw:
                continue
            cands = _cands(lines, i)
            if not any(TITLE_PAT[kind].search(c) for c in cands):
                continue
            # 坑⑤：标题行前后 2 行内出现「of the company」等 → 单体表，弃
            ctx = norm_label(" ".join(lines[max(0, i - 2):i + 3]))
            if EXCLUDE_TITLE.search(ctx):
                continue
            # 目录页特征：行首挂页码。
            # ⚠️ 不要再按「行尾挂页码」滤 —— 2018 年报把印刷页码排在标题同一行最右
            # (`CONSOLIDATED BALANCE SHEET            99`)，那条规则会把三张正表
            # 全部误杀。目录页改由后续 col_anchors（无年份表头）+ 骨架打分淘汰。
            if re.match(r"^\d{1,3}\s+\D", raw):
                continue
            hits.append((pi, i))
            break
    return hits


# 表头行允许出现的词 —— 除年份外，真表头只会有这些
HDR_OK = re.compile(
    r"\b(notes?|rmb|hk|usd|000|as|at|of|the|year|years|ended|ending|end|"
    r"december|january|restated|reclassified|unaudited|audited|section|ii|i|"
    r"and|to|continuing|operations|group|company)\b")


def _header_like(line):
    """这行是不是「年份表头」而不是恰好含年份的散文？

    招股书 p172 的散文「December, 2001, 2002 and 2003 prepared on the basis as
    set out in Note 1 of Section II」含两个年份，会冒充表头把整张表打空。
    判据：剥掉年份、数字、标点与表头常用词后，剩余字母内容必须很短。
    """
    s = YEAR_RE.sub(" ", line)
    s = re.sub(r"[^A-Za-z\s]", " ", s).lower()
    s = HDR_OK.sub(" ", s)
    return len(re.sub(r"\s+", "", s)) <= 12


def col_anchors(lines, start, lookahead=14):
    """标题后找年份表头行 → ([(year, 显示列)], Notes 列, 表头行号)。

    **不要求年份两两不同**：IAS 1 重述年是三栏式（2013 年报印 `Note 2013 2012
    2012`，第三栏是 1 January 的期初重述列）。要求不同 = 整张表定位失败。
    重复年份在取数时按「第一个等于目标年的列」消解。
    """
    for i in range(start, min(start + lookahead, len(lines))):
        ys = [(int(m.group(1)), disp_col(lines[i], m.end(1)))
              for m in YEAR_RE.finditer(lines[i])]
        if len(ys) < 2 or not _header_like(lines[i]):
            continue
        note_col = None
        first_amt = min(c for _, c in ys)
        for k in range(max(0, i - 2), min(i + 3, len(lines))):
            m = re.search(r"\bNotes?\b", lines[k])
            if m:
                c = disp_col(lines[k], m.end())
                # ⚠️ 附注列必须**紧贴第一个金额列的左侧**才可信。
                # 2011 年报把表头的 "Note" 字样排在页面最左（第 6 列），而真正的
                # 附注号在第 69 列。误取 6 的后果不是少认一个附注号，而是：行首的
                # 项目符号「–」（第 3 列）落进「附注列 ±7」被当成附注 →
                # `first` 指向行首 → 标签被截成空串 → **整行静默丢弃**
                # （2011 保留溢利 2,730,169 千元就是这么没的，靠「资负⑤ 权益
                #  分项之和 = 权益总额」才发现）。
                if 3 <= first_amt - c <= 45:
                    note_col = c
                break
        return ys, note_col, i
    return None, None, None


# 小节标题（自成一行、无数字）—— 它**不是**上一行折行，不能并进下一行标签
SECTION_HEAD = re.compile(
    r"^(assets|liabilities|equity|capital and reserves|non-current\b|current\b|"
    r"cash flows? (from|used in)\b|continuing operations|discontinued operations|"
    r"total\b)")


def _indent(s):
    return disp_col(s, len(s) - len(s.lstrip()))


def _rows_in(lines, frm, cols, note_col, tol):
    """逐行取数。

    **标签折行**（招股书 / 早年年报常见）：
        Net cash generated from
          operating activities          29,312   43,057   87,464
    数字在续行上，只取续行会得到「operating activities」——三条现金流小计的尾巴
    一模一样，别名层无从区分。故当上一行「无任何数字 + 缩进更浅 + 不是小节标题」
    时，把它并到本行标签前面。缩进判据是关键：小节标题（`Cash flows from
    operating activities`）与其下的科目行**同级或更浅**，折行头则一定更浅于续行。
    """
    out = []
    head = None          # 当前「分组表头」：(归一标签, 缩进)
    for i in range(frm, len(lines)):
        raw = lines[i]
        if not raw.strip():
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
        label = norm_label(raw[:first] if first is not None else raw)

        # ── 分组表头 + 「- 子项」结构 ──────────────────────────────────
        # 2006-2011 资产负债表把保留溢利拆成母行无数字、子行带数字：
        #     Retained earnings
        #       - proposed final dividend       115,941
        #       - others                      1,295,899
        # 子行标签只剩「- others」，无从归属；而母行与子行之间**隔着空行**，
        # 靠「看上一行」的折行合并够不着（空行即断）。故单独记一个 head：
        # 凡无数字、非噪声、非小节标题的行都当候选表头，随后缩进更深的「- 子项」
        # 一律冠以该表头。漏掉它 → 2006-2011 权益分项之和少 651~2,730 百万元
        # （由「资负⑤ 权益分项之和 = 权益总额」这条漏抓探测器逮出）。
        if not got:
            if label and not JUNK.search(label) and not SECTION_HEAD.search(label):
                head = (label, _indent(raw))
            else:
                head = None
            continue
        if not (label and not JUNK.search(label)):
            continue
        # 子项的结构信号在不同年份长得不一样，两种都要认：
        #   2008/2011：母行与子项同缩进或略深，靠 en-dash 前缀区分
        #              `Retained profits` / `– Proposed final dividend`
        #   2006/2007：子项**没有破折号**，只靠缩进更深区分
        #              `Retained profits` / `   Proposed final dividend`
        # 只认其中一种，另一批年份就整条漏抓（实测 2006/2007 各漏 651/1,114 百万）。
        prefixed = False
        if head and (label.startswith("-") or _indent(raw) > head[1]):
            tail = label.lstrip("- ").strip()
            label = head[0] + (" - " if label.startswith("-") else " ") + tail
            prefixed = True
        elif not label.startswith("-"):
            head = None

        if prefixed:
            out.append((label, vals))
            continue

        # 向上最多并 2 行折行头
        parts, k = [label], i - 1
        while k >= frm and len(parts) < 3:
            prev = lines[k]
            if not prev.strip():
                break
            if NUM_RE.search(prev):
                break
            pl = norm_label(prev)
            if (not pl or JUNK.search(pl) or SECTION_HEAD.search(pl)
                    or prev.rstrip().endswith((":", "."))
                    or _indent(prev) >= _indent(raw)):
                break
            parts.insert(0, pl)
            k -= 1
        out.append((" ".join(parts), vals))
    return out


def _skel_score(kind, rows):
    """骨架覆盖度。两路都比（原样 + 去空格）—— 坑②：2005 的 `gr oss pr ofit`
    只有去空格后才等于 `grossprofit`，否则真表打分为 0、输给摘要节。"""
    labels = " | ".join(l for l, _ in rows)
    flat = despace(labels)
    n = 0
    for pat in SKELETON[kind]:
        if re.search(pat, labels) or re.search(despace(pat), flat):
            n += 1
    return n


def statement(name, kind, max_pages=3):
    """取某份 PDF 的某张表 → (anchors, rows)。

    选表按 (骨架覆盖度, 行数) 排序 —— 坑④：纯按行数会挑中摘要节。
    """
    pgs = pages(name)
    best, best_key = None, (-1, -1)
    for pi, li in find_title_pages(name, kind):
        anchors, note_col, hdr = col_anchors(pgs[pi], li)
        if not anchors:
            continue
        cols = [c for _, c in anchors]
        gap = (min(cols[k + 1] - cols[k] for k in range(len(cols) - 1))
               if len(cols) > 1 else 20)
        tol = max(6, gap * 0.45)
        rows = _rows_in(pgs[pi], hdr + 1, cols, note_col, tol)
        done = any(TERMINAL[kind].search(l) for l, _ in rows)
        # 续页：表未收尾则继续吃，遇到别的表标题即止
        p = pi + 1
        while not done and p < len(pgs) and p - pi < max_pages:
            txt = norm_label(" ".join(pgs[p][:12]))
            if OTHER_TITLE.search(txt) or OTHER_TITLE.search(txt.replace(" ", "")):
                break
            a2, n2, h2 = col_anchors(pgs[p], 0)
            if a2 and [y for y, _ in a2] == [y for y, _ in anchors]:
                c2 = [c for _, c in a2]
                more = _rows_in(pgs[p], h2 + 1, c2, n2, tol)
            else:
                more = _rows_in(pgs[p], 0, cols, note_col, tol)
            if not more:
                break
            rows.extend(more)
            done = any(TERMINAL[kind].search(l) for l, _ in more)
            p += 1
        key = (_skel_score(kind, rows), len(rows))
        if key > best_key:
            best, best_key = (anchors, rows), key
    return best
