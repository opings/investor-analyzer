#!/usr/bin/env python3
"""解析 Disney 前 XBRL 时代（FY1993-FY2010）10-K 的三表，输出与 `_rfiles/` 同构的 JSON。

为什么要单开这一轨：SEC 只对 FY2011 起的 10-K 预渲染 R*.htm（FY2009/FY2010 的
FilingSummary.xml 里 Report 没有 HtmlFileName，更早的年份连 XBRL 都没有）。

两个时代两种载体，统一成同一种行结构 [{label, vals}]：
  · FY1993-FY2001 —— 纯文本申报，三表在 SGML `<TABLE>` 块里，定宽空白分列。
  · FY2002-FY2010 —— HTML 申报，`$` / 数字 / `)` 被拆进相邻 <td>，须先拼再抽。

三个 Disney 老报表特有的坑：
① **无标签小计行**：老式版式把「Revenues」当段首，下面三行分部，再跟一行**没有标签**的合计
   （见 FY1995 利润表）。直接丢掉这类行会丢掉营收合计 → 用「最近段首 + 合计」合成标签。
② **数字带一位小数**：FY1993-FY1997 单位是百万但保留一位小数（12,112.1），
   FY1998 起才取整。不要按整数正则抽。
③ **`--` / `—` 表示无此项**，不是 0；置 None，让下游勾稽自己判断。
"""
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))   # …/investor-analyzer
REPORT = os.path.join(ROOT, "report", "Disney")
OUT = os.path.join(HERE, "_legacy")

FILINGS = {fy: f"{fy}.txt" for fy in range(1993, 2002)}
FILINGS.update({fy: f"{fy}.htm" for fy in range(2002, 2011)})

TAG = re.compile(r"<[^>]+>")
# 数字：可带 $ 前缀、逗号千分位、一位及以上小数、括号负号（括号可能被拆到别的单元格）
NUM = re.compile(r"\(\s*\$?\s*([\d,]+(?:\.\d+)?)\s*\)|\$?\s*([\d,]+(?:\.\d+)?)")
NIL = re.compile(r"^\s*(--+|—|–|-)\s*$")

TITLES = {
    "IS": r"CONSOLIDATED\s+STATEMENTS?\s+OF\s+INCOME",
    "BS": r"CONSOLIDATED\s+BALANCE\s+SHEETS?",
    "CF": r"CONSOLIDATED\s+STATEMENTS?\s+OF\s+CASH\s+FLOWS?",
    # 分部：FY1998+ 是附注/MD&A 里的「Business Segments」表；
    # FY1993-1997 没有独立分部表 —— 利润表本身就是按分部列的，故也把 IS 的标题纳进来。
    "SEG": (r"Business\s+Segments|SEGMENT\s+INFORMATION|Segment\s+Information"
            r"|CONSOLIDATED\s+STATEMENTS?\s+OF\s+INCOME"),
}
# 判别「这张表是不是真的那张表」的锚行（防止抓到目录/附注/摘要表）
# ⚠️ Disney 老资产负债表**没有「Total assets」这一行**——合计是无标签行（见 FY1995：
#   "Other assets 1,223.6" 下面直接跟 "$14,605.8"）。锚点只能用确定会出现的科目名。
ANCHORS = {
    "IS": ["net income", "income taxes"],
    "BS": ["cash and cash equivalents", "retained earnings", "accounts payable",
           "total assets", "total liabilities and"],
    "CF": ["cash provided by operations", "cash provided by continuing operations",
           "net increase", "net decrease", "investing activities", "financing activities"],
    "SEG": ["media networks", "theme parks", "parks and resorts", "consumer products",
            "studio entertainment", "filmed entertainment", "creative content", "broadcasting"],
}


def is_year_header(line, ys):
    """年份表头行判据：≥2 个年份 token，且**整行没有千分位/小数形式的数字**。
    （"September 30   1995   1994" 里的 30 不是年份、也不带逗号小数 → 仍判表头；
      而 "Land 110.5 112.1" 带小数 → 数据行。）"""
    return len(ys) >= 2 and not re.search(r"\d[,.]\d", line)


def clean(x):
    return re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", x))).strip()


def nums_from(text):
    """从一段文本里抽出全部数值，保留顺序；`--`/`—` 记 None（无此项，非 0）。"""
    out = []
    for tok in re.split(r"\s{2,}|\|", text):
        t = tok.strip()
        if not t:
            continue
        if NIL.match(t):
            out.append(None)
    # 上面只处理了明确的 nil 标记；主抽取走整体正则
    out = []
    pos = 0
    for m in re.finditer(r"\(\s*\$?\s*[\d,]+(?:\.\d+)?\s*\)|—|--+|\$?\s*[\d,]+(?:\.\d+)?", text):
        tok = m.group(0)
        if re.match(r"^(—|--+)$", tok.strip()):
            out.append(None)
            continue
        neg = tok.strip().startswith("(")
        d = re.sub(r"[^0-9.]", "", tok)
        if d in ("", "."):
            continue
        try:
            v = float(d)
        except ValueError:
            continue
        out.append(-v if neg else v)
    return out


# ---------------------------------------------------------------- 文本申报 ----
def text_tables(raw, start):
    """返回 start 之后的第一个 SGML <TABLE> 块内容。"""
    m = re.compile(r"<TABLE>(.*?)</TABLE>", re.S | re.I).search(raw, start)
    return m.group(1) if m else None


def parse_text_block(block):
    """定宽文本块 → [(label, full, [vals])] + 期间年份。

    坑⑤ **多行标签**：老式版式把长科目名折行，数字只跟在第二行后面 ——
        Cash Provided by Operations Before Income
         Taxes                                  4,067.5  3,127.7
      只取第二行会得到标签 "Taxes"，概念匹配必然失手。
      对策：留一个 `pending`（上一条纯文字行），拼成 `full` 一并输出，
      让概念匹配对 label / full 两者都能命中。
    段首（`section`）只认**顶格且不含数字**的行，用于给无标签小计行命名（坑①）。
    """
    # 坑⑧ **无标签小计要归给「子段」而不是「大段」**：分部表长这样 ——
    #     Revenues                       ← 顶格大段
    #      Studio Entertainment          ← 缩进一级子段（本身不带数）
    #       Third parties      6,472
    #       Intersegment          76
    #                          6,548     ← 无标签小计，它属于 Studio Entertainment
    #   只用顶格 section 来命名，这行会变成「Revenues 合计」，分部就永远取不到。
    #   `sticky` = 最近一条纯文字行（任意缩进），**跨数值行保持**，专门给无标签小计命名。
    years, rows, section, pending, sticky = [], [], "", "", ""
    for line in block.split("\n"):
        ln = line.rstrip()
        if not ln.strip():
            continue
        if re.match(r"^\s*<[SC]>", ln) or "<CAPTION>" in ln.upper():
            continue
        if re.match(r"^[\s\-=_]*$", ln):            # 分隔线
            continue
        ys = re.findall(r"\b(19[89]\d|20[0-2]\d)\b", ln)
        if is_year_header(ln, ys):
            if len(ys) > len(years):
                years = ys
            continue
        indent = len(ln) - len(ln.lstrip())
        # 坑⑦ **点引导线**：FY1993/FY1994 的版式是
        #     `NET INCOME....................................... $  299.8  $  816.7`
        #   —— 点后只有**一个**空格，「≥2 空格」的分隔规则会切到 `$` 之后，
        #   标签变成 "NET INCOME....... $"，`^net income$` 永远匹配不上。
        #   先把 3 个以上的点归一成空格，后面的规则就统一了。
        ln = re.sub(r"\.{3,}", "   ", ln)
        # 坑⑥ **标签里可以有括号**：FY2000 的「Cash (used) provided by financing activities」
        #    若在第一个 `(` 处截断，标签只剩 "Cash"，融资那一行就永远匹配不上。
        #    定宽文本的真实分隔符是「≥2 个空格，且后面跟着一个数值 token」——按它切。
        msep = re.search(r"\s{2,}(?=\$|\(\s*\$?\s*\d|\d|—|--)", ln)
        cut = msep.start() if msep else len(ln)
        label = ln[:cut].strip().strip(" .")
        vals = nums_from(ln[cut:])
        if not vals:
            if label and not re.search(r"\d", label):
                if indent == 0:
                    section = label
                sticky = label
                pending = (pending + " " + label).strip() if pending else label
            continue
        full = (pending + " " + label).strip() if pending else label
        if not label:
            # 坑⑧续：无标签小计到底该归「子段」还是「大段」，光看缩进分不出来 ——
            #   分部表里  Revenues / Studio Entertainment / (小计)  该归子段；
            #   现金流里  INVESTING ACTIVITIES / Investments in …other / property / (小计)
            #   中间那两行其实是**一个折行标签**，小计该归大段。
            #   与其赌一个，不如**两个名字都给**：label 用子段、full 用大段，
            #   下游对 label 与 full 分别匹配，哪个对上算哪个。
            label = f"{sticky} 合计" if sticky else "(无标签小计)"
            full = f"{section} 合计" if section else label
        rows.append((label, full, vals))
        pending = ""
    return years, rows


# ---------------------------------------------------------------- HTML 申报 ----
def html_table_at(s, start):
    m = re.compile(r"<table[^>]*>(.*?)</table>", re.S | re.I).search(s, start)
    return (m.group(1), m.end()) if m else (None, None)


def parse_html_table(block):
    """HTML 表 → [(label, full, [vals])]；续行拼接同 parse_text_block（坑⑤）。"""
    years, rows, section, pending, sticky = [], [], "", "", ""
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", block, re.S | re.I):
        cells = [clean(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
        if not any(cells):
            continue
        joined = " ".join(c for c in cells if c)
        ys = re.findall(r"\b(19[89]\d|20[0-2]\d)\b", joined)
        if is_year_header(joined, ys):
            if len(ys) > len(years):
                years = ys
            continue
        # 第一个非空单元格作标签；若首格空而次格有字（缩进行），顺延
        label, rest = "", cells
        for i, c in enumerate(cells):
            if c and not re.match(r"^[\s$()—–,.\d]*$", c):
                label, rest = c, cells[i + 1:]
                break
        vals = nums_from(" ".join(rest))
        if not vals:
            if label:
                section = sticky = label
                pending = (pending + " " + label).strip() if pending else label
            continue
        full = (pending + " " + label).strip() if pending else label
        if not label:
            label = f"{sticky} 合计" if sticky else "(无标签小计)"   # 见坑⑧续
            full = f"{section} 合计" if section else label
        rows.append((label, full, vals))
        pending = ""
    return years, rows


# ------------------------------------------------------------------ 主流程 ----
def score(rows, kind):
    labs = " | ".join((l + " " + f).lower() for l, f, _ in rows)
    return sum(1 for a in ANCHORS[kind] if a in labs)


def extract(path, kind):
    """返回该文件里 kind 这张表的**全部候选**（按锚点分排序）。

    ⚠️ 不在这里定夺哪张是对的 —— 光靠标签锚点挑表会挑错（实证：FY2010 会挑中
    并购对价的「Estimated Fair Value」表、FY2000 挑中 pro forma 五年表、
    FY1997 挑中分部季度表）。定夺交给 `_build_from_filings.py`：
    它拿 R 文件已确立的可信值去对候选表的重叠年，对得上才采纳。
    """
    raw = open(path, "rb").read().decode("utf-8", "ignore")
    is_txt = path.endswith(".txt")
    cands = []
    seen_off = set()

    # 坑⑨ **靠标题定位在 HTML 里会漏**：标题常被 `<FONT>`/`<P>` 拆成几段，
    #   带标签的原文上跑 `SEGMENT\s+INFORMATION` 匹配不到（FY2006-2010 的分部表
    #   就这样整段消失，而它明明在文件里）。
    #   对策：**枚举全部表格**再按锚点打分，标题只当加分项、不当入场券。
    for tm in re.finditer(r"<TABLE[^>]*>" if is_txt else r"<table[^>]*>", raw, re.I):
        if is_txt:
            block = text_tables(raw, tm.start())
            if block is None:
                continue
            years, rows = parse_text_block(block)
        else:
            block, _ = html_table_at(raw, tm.start())
            if block is None:
                continue
            years, rows = parse_html_table(block)
        sc = score(rows, kind)
        if rows and sc >= 2:
            cands.append((sc, years, rows, tm.start()))
            seen_off.add(tm.start())

    for m in re.finditer(TITLES[kind], raw, re.I):
        if is_txt:
            block = text_tables(raw, m.end())
            if not block:
                continue
            years, rows = parse_text_block(block)
        else:
            # SEC 老 HTML 常因分页把一张报表拆进连续多个 <table>（FY2005 资产负债表
            # 的「Total assets」就掉在第二张里）→ 逐张往后**累加**，够锚点就停。
            cur, years, rows = m.end(), [], []
            for _ in range(4):
                block, nxt = html_table_at(raw, cur)
                if block is None:
                    break
                y, r = parse_html_table(block)
                if not r:
                    break
                if len(y) > len(years):
                    years = y
                rows = rows + r
                cur = nxt
                if score(rows, kind) >= 2:
                    break
        if rows:
            cands.append((score(rows, kind), years, rows, m.start()))
    # 两条路径（枚举全表 / 标题定位）可能各收到同一张表 → 按 (行数, 首行标签, 期间) 去重
    uniq, sig = [], set()
    for c in cands:
        k = (len(c[2]), c[2][0][0] if c[2] else "", tuple(c[1]))
        if k in sig:
            continue
        sig.add(k)
        uniq.append(c)
    # ⚠️ 别截太狠：FY1997 真正的合并利润表只有 11 行，若按 (分数, 行数) 排序后
    #    只留前 6 个，会被同分但 16-18 行的**错表**（分部表/季度表）全部挤掉。
    #    宁可多留，交给下游的重叠年核对 / 分部合计闸门去挑。
    uniq.sort(key=lambda c: (-c[0], -len(c[2])))
    return uniq[:24]


def main():
    os.makedirs(OUT, exist_ok=True)
    only = [int(a) for a in sys.argv[1:] if a.isdigit()]
    for fy in sorted(FILINGS):
        if only and fy not in only:
            continue
        path = os.path.join(REPORT, FILINGS[fy])
        if not os.path.exists(path):
            print(f"MISS {fy}: {path}")
            continue
        out = {"key": str(fy), "src": FILINGS[fy], "statements": {}}
        line = [f"{fy}:"]
        for kind in ("IS", "BS", "CF", "SEG"):
            cands = extract(path, kind)
            if not cands:
                line.append(f"{kind}(--)")
                continue
            out["statements"][kind] = [
                {"periods": years, "score": sc, "offset": off,
                 "rows": [{"label": l, "full": f, "vals": v} for l, f, v in rows]}
                for sc, years, rows, off in cands
            ]
            line.append(f"{kind}({len(cands)}候选:" +
                        ",".join(f"{len(c[2])}r/s{c[0]}" for c in cands) + ")")
        json.dump(out, open(os.path.join(OUT, f"{fy}.json"), "w"), ensure_ascii=False, indent=1)
        print(" ".join(line))


if __name__ == "__main__":
    main()
