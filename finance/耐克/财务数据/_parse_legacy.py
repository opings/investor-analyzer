#!/usr/bin/env python3
"""解析 NIKE 前 XBRL 时代（FY1995-FY2010）10-K 的三表，输出与 `_rfiles/` 同构的 JSON。

为什么要单开这一轨：SEC 只对 **FY2011 起**的 NIKE 10-K 预渲染 R*.htm
（实测 FY2010 那份 `index.json` 里 0 个 R*.htm、FilingSummary 的 HtmlFileName 全空）。

两个时代两种载体，统一成同一种行结构 `[{label, vals}]`：
  · **FY1995-FY2001** —— 纯文本申报，三表在 SGML `<TABLE>` 块里，**定宽空白分列**。
  · **FY2002-FY2010** —— HTML 申报，`$` / 数字 / `)` 被拆进相邻 `<td>`，须先拼再抽。

## 🔴 为什么两个时代都按「列位置」对齐，不按「数值出现顺序右对齐」

「把一行里抽到的数值右对齐到 N 个期间」是启发式：**只要某一年那一格整格空白
（没有任何 token），后面的数就会整体左移一位，而且看起来完全正常**。
本库已为这类静默错位付过代价（见记忆 `wide-csv-column-alignment`、
`segment-revenue-one-hand-current-year`：茅台分渠道两行整体左移一列，
每年"渠道和"精确等于**下一年**营收，连续 6 年没人发现）。

所以这里两条轨都先定出**年份列的位置**，再把每个数值 token 按位置投进去：
  · 文本轨 —— 用表头年份 token 的**字符区间**，数值按右端字符位就近归列（右对齐版式）。
  · HTML 轨 —— 把每行按 `colspan` **展开成网格**，数值落在稳定的网格列上。
空列因此留 `None`，不会顶掉邻列。

## 三个 NIKE 老报表特有的坑

① **单位在 FY1998 那次从「千美元」换成「百万美元」**（FY1995-1997 是 IN THOUSANDS，
   FY1998 起 IN MILLIONS）。解析时**按各年表头自陈**读单位，统一换算成百万美元后写出，
   不硬编码 —— 否则 FY1995-97 会整体大 1000 倍。
② **FY1995-1997 文本里 `$` 后紧跟一个填充 `0,`**（印刷对齐产物）：
   `$0,399,664` 实为 `$399,664`、`$0,031,943` 实为 `$31,943`。
   去掉逗号后转数恰好自洽（`0399664` → 399664），故不需特殊处理，
   **但不能按"逗号分组必须是 3 位"去校验**，那样会把整行判成脏数据。
③ **`--` / `---` / `—` 表示「本年无此项」，不是 0**（如 FY1997 无重组费用）→ 置 None，
   让下游勾稽自己判断；当成 0 会让"该年没有这项"与"该年这项为零"混同。
"""
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))   # …/investor-analyzer
REPORT = os.path.join(ROOT, "report", "耐克")
OUT = os.path.join(HERE, "_legacy")

FILINGS = {fy: f"{fy}.txt" for fy in range(1995, 2002)}
FILINGS.update({fy: f"{fy}.htm" for fy in range(2002, 2011)})

TAG = re.compile(r"<[^>]+>")
NIL = re.compile(r"^(--+|—|–)$")
YEAR = re.compile(r"^(19|20)\d\d$")
# 数值 token：可带 $、逗号千分位、小数、括号负号、末尾 %
NUMTOK = re.compile(r"\(?\$?\s?-?[\d,]+(?:\.\d+)?\)?%?")

TITLES = {
    "IS": r"CONSOLIDATED\s+STATEMENTS?\s+OF\s+INCOME",
    "BS": r"CONSOLIDATED\s+BALANCE\s+SHEETS?",
    "CF": r"CONSOLIDATED\s+STATEMENTS?\s+OF\s+CASH\s+FLOWS?",
    # EPS 附注（「Determination of shares」调节表）没有独立标题、就嵌在附注正文里，
    # 故只靠锚行认。**必须单独抓这张**：FY1998-FY2010 的利润表**不印加权平均股数**
    # （只印 EPS），股数全在这张附注表里。不抓 = 回购分析缺 13 年分母。
    "EPS": None,
    # 分部附注（FY1998-FY2010 的「Operating Segments」表）同样没有独立标题。
    # 这一轨把地区序列从 R 轨的 FY2009 起点往前接到 **FY1998**。
    # 🔴 老口径只有 4 个大区（美国 / EMEA / 亚太 / 美洲）+ 其他业务，
    #    与 FY2011 起的 6 区、FY2018 起的 4 区**都不是一回事**，只能分行并列、不可拼接。
    "SEG": None,
    # 「Selected Financial Data」五/八年摘要表。**它是 FY1988-FY1992 的唯一数据源**
    # （EDGAR 最早申报是 1995-01，那 5 年没有自家 10-K，三表也捎不回来），
    # 且自带 FY1988 起的**地区营收**与 ROE / 存货周转等公司自算比率。
    "SUM": None,
}

# 每个槽位的最低锚行命中数 + 年份列数上限。
# 🔴 少了这两道限制会抓错表：FY1995 的 MD&A 里有一张「金额 + 两列同比%」的表，
#    表头恰好被读成三个年份、且含 "United States" —— 只要 score>0 就会被当成分部表采纳，
#    于是 FY1995 的「美国营收」会变成 2,733,300 千美元旁边跟着两个 24 / −5（其实是百分比）。
MINSCORE = {"IS": 3, "BS": 3, "CF": 3, "EPS": 2, "SEG": 4, "SUM": 4}
MAXYEARS = {"IS": 3, "BS": 3, "CF": 3, "EPS": 3, "SEG": 3, "SUM": 12}
# 必含项：每个子列表至少命中一条。分部表**必须同时有「营收段」和「利润段」**——
# 光靠打分会被 MD&A 里同样含区域名和金额的「地区同比表」骗过去（FY2000 实测）。
REQUIRE = {
    "SEG": [["net revenue"],
            ["contribution profit", "pre-tax income", "before interest and taxes",
             "earnings before interest"]],
}
# 判别「这张表是不是真的那张表」的锚行（防抓到目录 / 附注 / 五年摘要 / 分部表）
ANCHORS = {
    "IS": ["revenues", "cost of sales", "costs of sales", "income before income taxes",
           "net income", "income taxes"],
    "BS": ["total current assets", "total assets", "accounts payable",
           "retained earnings", "total liabilities and"],
    "CF": ["cash provided by operations", "cash provided (used) by operations",
           "additions to property, plant and equipment",
           "cash and equivalents, end of year", "financing activities"],
    "EPS": ["determination of shares", "average common shares outstanding",
            "diluted average common shares outstanding",
            "diluted weighted average common shares outstanding",
            "assumed conversion"],
    # FY1998-FY2001 用「Europe / Asia/Pacific / Americas / Other brands + Contribution Profit」，
    # FY2002-FY2009 换成「Europe, Middle East and Africa … + Pre-tax Income」——两代措辞都要认。
    "SEG": ["europe, middle east and africa", "asia pacific", "asia/pacific", "americas",
            "united states", "other brands", "contribution profit",
            "before interest and taxes", "pre-tax income", "net revenue",
            "additions to long-lived assets"],
    "SUM": ["selected financial data", "market capitalization", "return on equity",
            "geographic revenues", "gross margin %", "inventory turns",
            "cash flow from operations"],
}


# ───────────────────────── 通用 ─────────────────────────
def clean(x):
    return re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", x))).strip()


def tonum(t):
    """'$0,399,664' → 399664.0 ; '(24,668)' → -24668.0 ; '--' → None"""
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
    """抹掉老式点引线：'Revenues.........  $8,995.1' → 'Revenues           $8,995.1'。

    🔴 **必须等宽替换**（点换成同样多的空格），不能压缩成两个空格。
    本表是定宽版式、纵刀（cut）按表头年份的字符位算 —— 把 44 个点压成 2 个空格
    会让整行左移 42 位，于是 `raw[:cut]` 一刀切到金额区中间，
    **标签里粘进金额**（实测 FY1997-2001 的 `Revenues $ 9,186,539 $ 6,470,625 $ 4,760,8`
    —— 注意最后一个数还被截断了，所以连"标签怪"都不会引起注意，
    它看着就像另一种版式）。
    ⚠️ 只吃 **3 个以上**连续点：金额里的小数点（8,995.1）和 'Note 13.' 不能动。
    """
    return re.sub(r"\.{3,}", lambda m: " " * len(m.group()), line)


def score(text, key):
    low = text.lower()
    for grp in REQUIRE.get(key, []):
        if not any(a in low for a in grp):
            return 0
    return sum(1 for a in ANCHORS[key] if a in low)


# 续行判据：小写字母开头 / `10)` 这种半截括注 / 落单的 `)` / `(Note 1)` 这种尾注。
# ⚠️ 不能放宽成任意 `(` 开头 —— `(Increase) decrease in inventory` 是**正经科目行**，
# 放宽会把它并进上一行。
# ⚠️ **不能加 re.I**：那会让 `[a-z]` 连大写一起吃，于是 `Revenues` 被判成续行、
#   并进上面的单位说明行（`(In millions, except per share data) Revenues`），
#   概念正则 `^revenues$` 全线失配 —— FY1993-1996 与 FY2002-2010 的营收整段消失。
#   只有 `(Note` 那一支需要大小写不敏感，故单独写成 `[Nn]ote`。
CONT = re.compile(r"^([a-z]|\d+\)|\)|\([Nn]ote)")


def merge_wraps(rows):
    """把「标签换行」的两行合成一行。

    老版式里长标签会折行，**金额印在第二行**，于是解析出「上一行全空 + 下一行标签是残句」：
      `Accounts receivable, less allowance for doubtful accounts`  [None, None]
      `of $32,663 and $28,291`                                     [1053237, 703682]
      `Average number of common and common`                        [None, None, None]
      `equivalent shares (Note 1)`                                 [73503, 75456, 77063]
      `Other income/expense, net (Notes 1, 9 and`                  [None, None, None]
      `10)`                                                        [32277, 36679, 11722]
    不合并的话，这些科目的**标签会对不上任何概念正则**、整行静默丢失
    （应收账款、加权股数、其他收支三项都会没）。
    判据取"下一行标签以小写字母 / `数字)` / `)` 开头" —— 段首标题（`Costs and expenses:`）
    一律大写开头，故不会被误并。

    ⚠️ 必须允许**连续多次**合并：FY1997 现金流表里那一行折了**三**行 ——
    `Effect of May 1996 cash flow activity for certain` / `subsidiaries` / `(Note 1) 43,004`。
    若要求"下一行必须有值才合并"，中间那行 `subsidiaries` 永远并不进去，
    最终标签只剩 `subsidiaries (Note 1)`，概念正则照样匹配不上，
    现金流勾稽差 43.0（而四个活动分类的合计各自都对）。
    """
    out = []
    for r in rows:
        if out and CONT.match(r["label"]) and all(v is None for v in out[-1]["vals"]) \
                and not out[-1]["label"].endswith(":"):
            prev = out.pop()
            r = {"label": f"{prev['label']} {r['label']}", "vals": r["vals"]}
        out.append(r)
    return out


# ───────────────────── 文本轨（FY1995-2001）─────────────────────
def unit_scale(block):
    """按表头自陈定单位 → 换算到「百万美元」的乘数。坑①。"""
    low = block.lower()
    if "in thousands" in low:
        return 1e-3
    if "in millions" in low:
        return 1.0
    return None


VALTOK = re.compile(r"(?<![\w.])(\(?\$?\s?[\d,]+(?:\.\d+)?\)?|--+|—)(?![\w])")


def parse_txt_table(block):
    """→ (scale, years, rows)。

    列定位分两刀：
    · **纵刀（cut）** —— 年份表头最左那个 token 的起始字符位。它左边的一切都是标签，
      右边才可能是金额。🔴 这刀是必须的：老版式把**附注号和括注写在标签里**
      （`Interest expense (Notes 3, 4 and 5)`、`less allowance for doubtful accounts
      of $32,663 and $28,291`、`Class A convertible - 25,895,and 26,679 shares
      outstanding`）。不切就会把附注号 3 / 备抵 32,663 / 股数 25,895 当成本年金额，
      而且**它们恰好落在第一列**、看起来完全像真数（实测 FY1995 利润表利息费用被读成 3.0）。
    · **横向归列** —— 金额右对齐印刷，故按 token 右端字符位就近匹配年份 token 右端；
      但**当 token 数恰好等于年份列数时改为按序对号**，因为定宽版式里混入制表符会让
      字符位整体漂移（实测 FY1995「负债和股东权益合计」那行有 \t，就近匹配把两个数
      都投进了第 2 列 → 本年合计变 None）。
    """
    lines = block.expandtabs(8).split("\n")
    # 1) 找年份表头行：该行 ≥2 个 4 位年份 token，且行内没有千分位/小数数字
    hdr_i, cols = None, []
    for i, ln in enumerate(lines[:20]):
        toks = [(m.group(), m.start(), m.end())
                for m in re.finditer(r"\b(19|20)\d\d\b", ln)]
        if len(toks) >= 2 and not re.search(r"\d[,.]\d", ln):
            hdr_i, cols = i, toks
            break
    if hdr_i is None:
        return None
    years = [int(t[0]) for t in cols]
    ends = [t[2] for t in cols]                      # 年份 token 右端字符位
    cut = cols[0][1] - 3                             # 纵刀：容 3 字符（金额比年份宽）
    scale = unit_scale(block)
    if scale is None:
        return None

    rows, prev_head = [], ""
    for ln in lines[hdr_i + 1:]:
        raw = strip_leaders(ln.rstrip())
        if not raw.strip() or set(raw.strip()) <= set("-=_ "):
            continue
        toks = [(m.group(), m.end()) for m in VALTOK.finditer(raw) if m.end() >= cut]
        # 🔴 尾部要连 `(` 和 `$` 一起削：金额是 `(229,985)` 时，**左括号在纵刀左边**、
        #    会留在标签尾巴上 → `Cash used by investing activities (`，
        #    于是任何以 `activities$` 收尾的概念正则全部落空（实测 FY1996 投资活动净额
        #    整行没采到，现金流勾稽差 229.99 —— 而那个差额恰好等于该行金额，
        #    看起来像"这一年没有投资活动"）。
        label = re.sub(r"[.\s$(]+$", "", clean(raw[:cut] if len(raw) > cut else raw))
        if not toks:
            if label:
                rows.append({"label": label, "vals": [None] * len(years)})
                if label.endswith(":"):
                    prev_head = label
            continue
        # 无标签小计行（老版式：段首 "Costs and expenses:" + 下面几行明细 + 一行裸合计）
        if not label and prev_head:
            label = prev_head.rstrip(":") + " 合计"
        vals = [None] * len(years)
        if len(toks) == len(years):                  # 计数匹配 → 按序对号（抗制表符漂移）
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
    s = open(path, encoding="utf-8", errors="ignore").read()
    blocks = re.findall(r"<TABLE>(.*?)</TABLE>", s, re.S | re.I)
    out = {}
    for key, pat in TITLES.items():
        best, bestsc = None, 0
        for i, b in enumerate(blocks):
            # 标题在 <TABLE> 之前的 400 字符内（NIKE 版式：标题 → <TABLE> → <CAPTION>）
            # pat 为 None = 这张表没有独立标题（如 EPS 附注），只靠锚行打分认
            if pat is not None:
                pos = s.find(b)
                head = s[max(0, pos - 400):pos]
                if not re.search(pat, head, re.I):
                    continue
            sc = score(b, key)
            if sc > bestsc and sc >= MINSCORE[key]:
                p = parse_txt_table(b)
                if p and len(p[1]) <= MAXYEARS[key]:
                    best, bestsc = p, sc
        if best:
            scale, years, rows = best
            out[key] = {"scale": scale, "years": years, "rows": rows, "src": "txt"}
    return out


# ───────────────────── HTML 轨（FY2002-2010）─────────────────────
def grid_rows(table_html):
    """把一张 HTML 表按 colspan 展开成网格 → [(label, {col: text})]。

    🔴 为什么要展开：NIKE 的 HTML 版式里标签格 colspan 在 2/3/4 之间变（缩进层级），
    若按「第几个 td」定位，缩进一变整行就错列。展开成网格后，年份列的网格坐标是稳定的。
    """
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.S | re.I):
        cells, col = [], 0
        for kind, attr, c in re.findall(r"<t([hd])([^>]*)>(.*?)</t[hd]>", tr, re.S | re.I):
            n = int((re.search(r'colspan="?(\d+)"?', attr) or [0, "1"])[1])
            cells.append((col, n, clean(c)))
            col += n
        if not cells:
            continue
        out.append(cells)
    return out


PURENUM = re.compile(r"\(?\$?\s?[\d,]+(?:\.\d+)?\)?")


def parse_html_table(table_html):
    """→ (scale, years, rows)。

    🔴 **数值列不能从表头年份格的网格坐标推**。NIKE 的 HTML 版式里，
    表头那行每个年份只占 1 个网格格（`c2:'2010' c5:'2009' c8:'2008'`），
    而数据行每年要占 3-4 格（`$` / 金额 / `)` / 间隔），于是数据落在
    `c3 / c7 / c11` —— 与表头坐标的偏移**逐列递增**（+1 / +2 / +3）。
    第一版按「表头列 ± 2 邻域搜」，第 2 列往左搜到 d=-2 就撞进**第 1 列的金额格**，
    于是整行右移一位、且 **FY2010 与 FY2009 印出两个一模一样的净利 1,906.7**
    —— 看起来像"两年没变"，不像解析错。

    改为**从数据行自己统计**：哪些网格列最常出现纯数值 token，取出现次数最高的 N 列
    （N = 年份个数）升序排列。这与表头/数据的 colspan 是否一致无关，是确定性做法。
    """
    grid = grid_rows(table_html)
    if not grid:
        return None
    flat = clean(table_html)
    scale = 1e-3 if "in thousands" in flat.lower() else (
        1.0 if "in millions" in flat.lower() else None)

    # 1) 年份表头：找含 ≥2 个 4 位年份单元格的行（只为拿年份，不拿坐标）
    years = []
    for cells in grid[:8]:
        ys = [t for c, n, t in cells if YEAR.match(t)]
        if len(ys) >= 2:
            years = [int(t) for t in ys]
            break
    if not years:
        return None

    # 2) 数值列 = 各网格列里「纯数值 token」出现次数最高的 len(years) 列
    cnt = {}
    for cells in grid:
        for c, n, t in cells:
            if t and t not in ("$", "(", ")") and PURENUM.fullmatch(t.replace(" ", "")):
                cnt[c] = cnt.get(c, 0) + 1
    if len(cnt) < len(years):
        return None
    vcols = sorted(sorted(cnt, key=lambda c: (-cnt[c], c))[:len(years)])

    rows = []
    for cells in grid:
        texts = {c: t for c, n, t in cells}
        # 标签 = 第一个非空、非数值的单元格
        label = ""
        for c, n, t in cells:
            if t and not NUMTOK.fullmatch(t.replace(" ", "")) and t not in ("$", ")", "("):
                label = t
                break
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
            # 负号括号被拆：左括号可能贴在金额里、右括号在后一格
            neg = t.startswith("(") or texts.get(vc - 1, "") == "(" \
                or texts.get(vc + 1, "") == ")"
            v = tonum(t)
            vals.append(-abs(v) if (neg and v is not None) else v)
        rows.append({"label": label, "vals": vals})
    return scale, years, merge_wraps(rows)


def parse_html(fy, path):
    s = open(path, encoding="utf-8", errors="ignore").read()
    tables = [(m.start(), m.group(1))
              for m in re.finditer(r"<table[^>]*>(.*?)</table>", s, re.S | re.I)]
    out = {}
    for key in TITLES:
        best, bestsc = None, 0
        for pos, t in tables:
            flat = clean(t)
            sc = score(flat, key)
            if sc < MINSCORE[key]:
                continue
            # 反锚：五年摘要 / 季度表不要（SUM 槽位本身就是要抓五年摘要，故豁免）
            low = flat.lower()
            if key != "SUM" and ("selected financial data" in low or "quarterly" in low):
                continue
            if sc > bestsc:
                p = parse_html_table(t)
                if p and p[0] and len(p[1]) <= MAXYEARS[key]:
                    best, bestsc = p, sc
        if best:
            scale, years, rows = best
            out[key] = {"scale": scale, "years": years, "rows": rows, "src": "htm"}
    return out


# ───────────────────────── 主流程 ─────────────────────────
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
        print(f"FY{fy}: " + ", ".join(
            f"{k}(years={v['years']},scale={v['scale']},rows={len(v['rows'])})"
            for k, v in sorted(got.items())) or "NOTHING")


if __name__ == "__main__":
    main()
