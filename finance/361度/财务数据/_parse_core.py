#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""361度（01361.HK）三表解析内核 —— 文本层 / 列几何 / 标签归一 / 定位 / 取行。

被 `_build_from_pdf.py` 引入。列几何与标签归一沿用本库已验证的中文港股管线
（`finance/安踏体育/财务数据/_build_from_pdf.py`），本文件只记 **361度 特有**的坑。

本公司报表体例与安踏/特步的三处结构性差异（改动前先读）：

  ① **分区小计是「无标签裸数字行」**：361度 资负表不印「流動資產合計」这类小计标签，
     小计直接印成一行纯数字。故不能按标签定位分区，改为：按**分区标题行**
     （非流動資產 / 流動資產 / 流動負債 / 非流動負債 / 資本及儲備）切区，
     取区内**最后一个无标签数字行**作该区小计。
     ⚠️ 用「第一个」会错：招股书非流动区内有两个无标签行（固定資產小計 19,272
     与 非流動資產小計 20,266），第一个是子项小计不是区小计。

  ② **没有「資產總值」行**：报表走「非流動+流動−流動負債=流動資產淨值 →
     總資產減流動負債 → −非流動負債 = 資產淨值」这条链，全表无总资产单行。
     故总资产/总负债须由分区小计派生（见 `_build_from_pdf.py` 的恒等派生），
     不可用「總資產減流動負債」冒充总资产。

  ③ **列不能按年份归一**：2011 年财政年度结算日由 6月30日 改为 12月31日
     （过渡期 = 2011-07-01~2011-12-31 共 6 个月，见 2011年报附註1）。过渡期报告的
     两列表头**同为「二零一一年」**（左=止六個月、右=止年度），按年份做 key 会
     整列覆盖。故本内核一律按**列下标**返回值，由 `_build_from_pdf.py` 的
     `COLMAP` 显式声明每份 PDF 每张表的列→期间映射。
"""
import os
import re
import subprocess
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
PDF_DIR = os.path.join(ROOT, "report", "361度")
CACHE = os.path.join(HERE, ".txtcache")
PDFTOTEXT = "/opt/homebrew/bin/pdftotext"


# ─────────────────────────── 文本层 ───────────────────────────

def ensure_text(name):
    """PDF → 文本（带缓存）。返回行列表（不按 \f 切页，行号连续）。"""
    os.makedirs(CACHE, exist_ok=True)
    txt = os.path.join(CACHE, f"{name}.txt")
    if not os.path.exists(txt):
        pdf = os.path.join(PDF_DIR, f"{name}.pdf")
        if not os.path.exists(pdf):
            raise SystemExit(f"🔴 缺一手 PDF: {pdf}")
        subprocess.run([PDFTOTEXT, "-layout", pdf, txt], check=True,
                       stderr=subprocess.DEVNULL)
    with open(txt, encoding="utf-8", errors="replace") as f:
        return f.read().replace("\f", "\n").splitlines()


# ─────────────────────────── 列几何 ───────────────────────────

CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
            "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
YEAR_TOK = re.compile(r"二[零〇一二三四五六七八九]{3}年")

# 数字 token 三形态：括号负数 / 普通数 / 空值（破折号·不適用）
#   ⚠️ 括号内允许空格；token 尾部绝不能放 `\s*`（会吞下一列的空格令 end 右移）
#   ⚠️「不適用」必须当占位空值 token —— FY2009 摊薄 EPS 上年列印的就是「不適用」，
#      不识别会少一个 token、右锚整体左移，把附註编号当成数值。
NUM_RE = re.compile(
    r"\(\s*(?P<d1>-?[\d][\d,]*(?:\.\d+)?)\s*\)"
    r"|(?P<d2>-?[\d][\d,]*(?:\.\d+)?)"
    r"|(?P<na>N/A|不適用|不适用)"
    r"|(?P<dash>[–—－])"
)


def disp_col(s, idx):
    """字符下标 idx 处的**显示列**（CJK 全角算 2 列）。

    pdftotext -layout 按显示宽度对齐、Python 下标按字符数 —— 混用会让含中文的
    标签与右对齐的数字列整体错位。
    """
    w = 0
    for ch in s[:idx]:
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def cn_year(tok):
    m = YEAR_TOK.search(tok)
    if not m:
        return None
    d = m.group()
    return 2000 + CN_DIGIT[d[1]] * 100 + CN_DIGIT[d[2]] * 10 + CN_DIGIT[d[3]]


def tok_value(m):
    if m.group("dash") is not None or m.group("na") is not None:
        return None
    if m.group("d1") is not None:
        return -float(m.group("d1").replace(",", ""))
    return float(m.group("d2").replace(",", ""))


def tok_end(m):
    """归列用的结束位置（字符下标）——取数字本体末尾，忽略右括号，正负数才同列。"""
    for g in ("d1", "d2", "na", "dash"):
        if m.group(g) is not None:
            return m.end(g)
    return m.end()


BULLET = re.compile(r"^(\s*)[—–－](?=\s*[一-鿿])")
# 数字千分位逗号**两侧混进空格** —— 2012/2013/2024 年报的字距排版产物，
# 如 2024 年报营业额印成 `10,073 ,510`。不清理会被切成两个 token（10073 与 510），
# 右锚左移一位 → 该列整行取到错数（实证：2024 营业额被读成 0.51 百万，真值 10,073.5）。
# 只吃「逗号紧邻」的 1-2 个空格，两列之间的大段空白与列几何不受影响。
SPLIT_NUM = [(re.compile(r"(?<=\d)\s{1,2}(?=,\d)"), ""),
             (re.compile(r"(?<=,)\s{1,2}(?=\d)"), "")]


def strip_bullet(raw):
    """行首当**项目符号**用的破折号换成等宽空格（全角=2 显示列，用 2 空格保位）+ 数字缝合。

    「— 物業、廠房及設備 …… 246,627」里的 `—` 会被 NUM_RE 当空值 token，
    于是标签算成它前面的空白 → 整行被丢弃（固定资产两个子项就是这么丢的）。
    """
    raw = BULLET.sub(lambda m: m.group(1) + "  ", raw)
    for pat, rep in SPLIT_NUM:
        raw = pat.sub(rep, raw)
    return raw


def row_tokens(raw):
    return [(tok_value(m), m.start(), disp_col(raw, tok_end(m)))
            for m in NUM_RE.finditer(raw)]


def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def find_year_columns(lines, start, lookahead=14):
    """标题后找中文年份表头行 → ([(年, 显示列)], 表头行号)。

    ⚠️ 返回值只用来定**列位置与列数**；年份**不当 key**（坑③：过渡期两列同年）。
    """
    for i in range(start, min(start + lookahead, len(lines))):
        found = [(cn_year(m.group()), disp_col(lines[i], m.end()))
                 for m in YEAR_TOK.finditer(lines[i])]
        found = [(y, c) for y, c in found if y]
        if len(found) >= 2:
            return found, i
    return None, None


def detect_scale(lines, start, lookahead=16):
    """单位探测 → (系数→百万元, 单位名)。先去空格：招股书把单位排成「人 民 幣 千 元」。"""
    blob = re.sub(r"\s+", "", "".join(lines[start:start + lookahead]))
    if "人民幣千元" in blob or "千元" in blob:
        return 0.001, "人民幣千元"
    if "百萬元" in blob or "百万元" in blob:
        return 1.0, "人民幣百萬元"
    return None, None


def gap_samples(lines, start, end, n_cols):
    """采样「恰好 n 个 token」行的列间距 → [(行号, 间距)]。

    不能用表头年份间距 ——「二零二五年」是全角文本，与右对齐数字列不同宽。
    """
    out = []
    if n_cols < 2:
        return out
    for i in range(start, min(end, len(lines))):
        toks = row_tokens(strip_bullet(lines[i]))
        if len(toks) != n_cols:
            continue
        ends = [t[2] for t in toks]
        d = [ends[k + 1] - ends[k] for k in range(len(ends) - 1)]
        if all(6 <= x <= 44 for x in d) and (max(d) - min(d)) <= 5:
            out.append((i, _median(d)))
    return out


def local_delta(samples, i, win=40, fallback=None):
    """第 i 行附近的列间距中位数 —— 一张表跨页且两页列宽不同时，全局中位数会整页失配。"""
    near = [g for idx, g in samples if abs(idx - i) <= win]
    return _median(near) or fallback


def shape_samples(lines, start, end, n_cols):
    """采样「恰好 n 个 token」行的**相对列形状** → [(行号, [0, d1, …, d(n-1)])]，
    其中 dk = 该行最右 token 到往左第 k 列的显示列距离。

    这是本内核归列的**主依据**，优于表头位置也优于等距假设：

    · **相对量、与缩进无关** —— 同一张表跨页、两页整体缩进不同（2025 年报综合财务
      状况表第 2 页右移 6 列），绝对列中心会整页失配，相对形状不会。
    · **不假设等距** —— 招股书会计师报告 5 列的真实形状是 [0,14,30,43,60]，
      等距 k×16 = [0,16,32,48,64] 在第 3 列就偏 5 列。
    · **也不照抄表头形状** —— 表头「二零零六年」是全角文本，形状只是近似：
      按跨距缩放后为 [0,16,30.5,47.3,61]，与真实形状在第 3 列差 4.3，
      刚好越过容差 → FY2007 整列被丢（实证：经营现金流、经营所得现金等 5 行）。

    只取 token 数**恰好等于列数**的行（多一个 token 通常是附註编号或页码），
    再逐位取中位数即得稳健形状。
    """
    out = []
    if n_cols < 2:
        return out
    for i in range(start, min(end, len(lines))):
        toks = row_tokens(strip_bullet(lines[i]))
        if len(toks) != n_cols:
            continue
        ends = [t[2] for t in toks]
        dist = [ends[-1] - e for e in reversed(ends)]      # [0, d1, …]
        if all(6 <= dist[k + 1] - dist[k] <= 44 for k in range(n_cols - 1)):
            out.append((i, dist))
    return out


def local_shape(samples, i, n, win=40):
    """第 i 行邻域内的相对形状（逐位中位数）。样本不足返回 None。"""
    near = [v for idx, v in samples if abs(idx - i) <= win]
    if len(near) < 3:
        near = [v for _, v in samples]
    if len(near) < 3:
        return None
    return [_median([v[k] for v in near]) for k in range(n)]


def header_shape(header_cols, n, d, span_data=None):
    """把表头列位置的**形状**（各列到最右列的距离）按数据实测列距缩放。

    返回 [0, s1, …, s(n-1)]：往左第 k 列相对最右列应退多少显示列。

    ⚠️ 为什么不能一律用等距 `k*d`：招股书会计师报告是 **5 列且列距不均匀**
       （表头 71/89/111/130/151，间距 18/22/19/21）。等距右走每往左一列累积一次误差，
       走到第 2 列就偏出容差 —— 实证：合并现金流量表 FY2007 整列被丢
       （「經營活動(所用)/產生的現金淨額」−52,540 取不到，该年经营现金流成空）。
    ⚠️ 也不能直接拿表头间距当数据间距：「二零零六年」是全角文本，与右对齐的数字列
       不同宽（安踏实测表头 18 / 数据 13）。故只借表头的**形状**、尺度仍用实测的 d。
       n=2 时本函数退化为 [0, d]，与原等距实现逐位相同。
    """
    if n < 2:
        return [0.0]
    span = header_cols[-1] - header_cols[0]
    if span <= 0:
        return [k * d for k in range(n)]
    scale = (span_data if span_data else (n - 1) * d) / span
    return [(header_cols[-1] - header_cols[n - 1 - k]) * scale for k in range(n)]


def assign_by_anchor(ends, anchor, n, shape, t2):
    """以 anchor 为最右列、按 shape 往左走，返回 {列下标: token下标}。"""
    out = {}
    for k in range(n):
        want = anchor - shape[k]
        cand = [j for j, e in enumerate(ends) if abs(e - want) <= t2]
        if cand:
            out[n - 1 - k] = min(cand, key=lambda j: abs(ends[j] - want))
    return out


def best_anchor(ends, n, shape, t2):
    """在末尾若干个 token 位置里挑**填满列数最多**的那个作右锚（并列取最靠右）。

    ⚠️ 为什么不能无条件用「本行最右 token」：部分年报把**页码印在同一文本行的
       右边距**。过渡期年报实测：
           `按金、預付款項及其他應收款項  16  794,684  305,316  67`   ← 末尾 67 是页码
       以 67 为锚只能填 1 列（且末列取到页码 0.067，真值 305.3 百万）；
       以 305,316 为锚能填满 2 列 —— 故用「填满列数」自校验即可分辨，
       无需猜哪个 token 是页码。
    ⚠️ 也不能改用「全块最右位置的中位数」：很多行合法地只有左列有值（右列留空
       且不印破折号），中位数会被拽向左，实测把 244 条勾稽打到只剩 153 条。
    """
    best = None
    for j in range(len(ends) - 1, max(-1, len(ends) - 4), -1):
        fill = assign_by_anchor(ends, ends[j], n, shape, t2)
        if best is None or len(fill) > len(best[1]):
            best = (ends[j], fill)
    return best


# ─────────────────────────── 标签归一 ───────────────────────────

def norm_label(s):
    """剥英文 / 阿拉伯数字 / 点引线 / 空格，统一标点。

    必须连数字一起剥：招股书标签带点引线「銷 售 成 本. . . .」与附註编号；
    中文标签只用汉字数字，故剥阿拉伯数字安全。
    """
    s = re.sub(r"[A-Za-z&'\.,%\d]+", "", s)
    s = re.sub(r"\s+", "", s)
    s = (s.replace("（", "(").replace("）", ")")
           .replace("╱", "/").replace("／", "/")      # 两种全角斜杠都要归一
           .replace("、", "").replace("，", "")
           .replace("－", "-").replace("　", "")
           .replace("「", "").replace("」", ""))
    for _ in range(3):                       # 附註编号剥净后残留的空括号
        s2 = re.sub(r"\(\s*\)", "", s)
        if s2 == s:
            break
        s = s2
    return s.strip("-—–·:：")


# 页眉页脚 / 签署页 / 附註指引 —— 不是科目（会被右锚钓上页码）
JUNK = re.compile(
    r"有限公司$|年報|第.{0,8}頁|附註構成|已獲董事會批准|董事$|年度$|"
    r"^於.{0,12}(日|止)$|^人民幣|^附註$|^以人民幣列示$"
)


# 资负表分区标题 —— 这些行**无数值**，走纯文本分支，故在那里顺手记下当前分区。
# 「流動資產淨值/淨額」带数值，走不到这里，不会被误判成分区标题。
SECTION = [
    ("NCA", re.compile(r"^非流動資產$")),
    ("CA", re.compile(r"^流動資產$")),
    ("CL", re.compile(r"^流動負債$")),
    ("NCL", re.compile(r"^非流動負債$")),
    ("EQ", re.compile(r"^(資本及儲備|權益)$")),
]
# 「链式行」—— 分区小计之后的跨区汇总行。分区小计只在它们之前找（坑①的收尾判据）
CHAIN = re.compile(r"^(流動資產(淨值|淨額)|流動(負債)?淨值|總?資產(總額)?減流動負債"
                   r"|資產(淨值|淨額)|權益總額|負債總額)$")


def parse_block(lines, hdr, end, cols, scale, tol=4):
    """解析 (hdr, end) 区间 → [(候选标签列表, {列下标: 值}, 是否无标签行, 分区)]。

    候选标签有多个，因为标签会**跨行折行**：cands = [本行片段, 上一无数字行+片段,
    上两行+片段]，由别名层决定哪个有意义；片段优先，正常单行表不受影响。

    「无标签行」= 有数值但标签为空/非中文 —— 在 361度 报表里这就是**分区小计**
    （坑①），必须保留而不是丢弃。
    """
    n = len(cols)
    samples = gap_samples(lines, hdr + 1, end, n)
    delta = _median([g for _, g in samples])
    shapes = shape_samples(lines, hdr + 1, end, n)
    out, prev, sec = [], [], ""
    for i in range(hdr + 1, min(end, len(lines))):
        raw = strip_bullet(lines[i])
        if not raw.strip():
            prev = []
            continue
        toks = row_tokens(raw)
        if not toks:
            p = norm_label(raw)
            if p and not JUNK.search(p):
                for key, pat in SECTION:
                    if pat.match(p):
                        sec = key
                        break
                prev = (prev + [p])[-2:]
            continue
        d = local_delta(samples, i, fallback=delta)
        if not d:
            prev = []
            continue
        # 形状优先级：① 实测相对形状 ② 表头形状按跨距缩放 ③ 等距 —— 依次兜底
        shape = local_shape(shapes, i, n)
        if shape is None:
            shape = header_shape(cols, n, d)
        t2 = max(tol, int(d * 0.3))
        vals, used = {}, []
        if len(toks) == 1:
            v, st0, e = toks[0]
            j = min(range(n), key=lambda k: abs(e - cols[k]))
            if abs(e - cols[j]) <= max(tol + 4, d // 2 + 2):
                vals[j] = None if v is None else v * scale
                used.append(st0)
        else:
            ends = [t[2] for t in toks]
            _anchor, fill = best_anchor(ends, n, shape, t2)
            for ci, j in fill.items():
                v = toks[j][0]
                vals[ci] = None if v is None else v * scale
                used.append(toks[j][1])
        if not vals:
            prev = []
            continue
        label = norm_label(raw[:min(used)])
        bare = not label or not re.search(r"[一-鿿]", label)
        if not bare and JUNK.search(label):
            prev = []
            continue
        cands = [label]
        if not bare and prev:
            cands.append(prev[-1] + label)
            if len(prev) > 1:
                cands.append(prev[-2] + prev[-1] + label)
        prev = []
        cands = [re.sub(r"[(\[]+$", "", c) for c in cands]
        out.append((cands, vals, bare, sec))
    return out


# ─────────────────────────── 定位三表 ───────────────────────────

# ⚠️ 标题行**不是**「整行只有表名」：
#   · FY2011-06 把标题印成「綜合」换行「收益表      截至二零一一年六月三十日止年度」
#   · 2016 年报印成「綜合損益表        止年度（以人民幣列示）」
#   故允许表名后跟期间/单位残句，但**禁止句中出现 。或 ：** —— 否则
#   「收益表中扣除。」「綜合資產負債表內的存貨包括：」这类散文句会被当成正表标题。
_NAME = {
    "is": r"(損益表|收益表)",
    "bs": r"(財務狀況表|資產負債表)",
    "cf": r"現金流量表",
}
TITLE = {k: re.compile(rf"^\s*(綜合|合併)?\s*{v}(（續）)?\s*[^。：]*$"
                       rf"|^\s*\d+\.\s*(合併|綜合)\s*{v}\s*$")
         for k, v in _NAME.items()}
# 表体终止：遇权益变动表 / 母公司单表 / 附註 / 其他全面收入表 / 会计师报告下一张编号表 即停
#
# ⚠️ 招股书会计师报告的编号标题（「2.   合併資產負債表」）必须列入终止锚：
#    该报告里**损益表 5 列、资产负债表 4 列**，不截断会让资负表的行按 5 列几何归位，
#    整段左移一列（实证：存貨 2006 被读成 0.011 —— 那其实是附註编号 11）。
#
# ⚠️ **母公司单表紧跟在合并资负表之后**（FY2009-FY2011 年报体例），科目名几乎一样、
#    且标题被排版切成「資產」换行「負債表」——按标题根本拦不住。真正可靠的终止锚是
#    合并表尾部的**签署块**「董事會於…批准及授權刊發」/「…已獲董事會批准及授權刊發」。
#    不拦会把母公司的流動資產/流動負債小计覆盖掉合并数（FY2011 母公司净资产 11.77 亿
#    vs 合并 42.79 亿，差 3.6 倍）。
#
# ⚠️ 招股书用的是「財務資料附註」「重大會計政策」（年报是「財務報表附註」「重要會計政策」），
#    一字之差。漏掉会让表体多吃 400 行附注 —— 附注里的小表污染列距/跨距采样，
#    进而让正表某一列整列落空（实证：招股书合并现金流量表 FY2007 列被丢）。
STOP = re.compile(
    r"(綜合|合併)權益變動表|財務(報表|資料)附註|重[要大]會計政策|主要會計政策"
    r"|(綜合|合併)損益及其他全面收(益|入)表|(綜合|合併)全面收入表"
    r"|批准及授權刊發|附註構成本財務報表"
    r"|^\s*\d+\.\s*(合併|綜合)(損益表|收益表|資產負債表|財務狀況表|權益變動表|現金流量表)\s*$"
)
SKIP_LINE = re.compile(r"\.{4,}|目錄|第\s*\d+\s*至|包括|呈列|計入|附註\d")


def _has_year_header(lines, i, look=14):
    return any(len(YEAR_TOK.findall(lines[j])) >= 2
               for j in range(i, min(i + look, len(lines))))


def find_titles(lines, kind, lo=0, hi=None):
    """返回该表标题所在行号列表（要求其后不远处带年份表头、且非目录/散文行）。"""
    hi = len(lines) if hi is None else hi
    return [i for i in range(lo, min(hi, len(lines)))
            if TITLE[kind].search(lines[i]) and not SKIP_LINE.search(lines[i])
            and _has_year_header(lines, i)]


def block_end(lines, start, hard):
    for i in range(start + 6, min(hard, len(lines))):
        if STOP.search(lines[i]):
            return i
    return min(hard, len(lines))


# 正表骨架 —— 用于把「前部摘要表」从真正的财务报表里分开
SKELETON = {
    "is": ("毛利", "經營"),
    "bs": ("存貨", "流動"),
    "cf": ("經營活動", "投資活動", "融資活動"),
}


def _skeleton_hit(lines, i, kind, span=90):
    blob = "".join(lines[i:i + span])
    return sum(1 for k in SKELETON[kind] if k in blob)


def locate_three(lines):
    """在一份 PDF 里定位**经审核正表**三元组 → (is起, bs起, cf起)。

    ⚠️ 只按标题取会拿到**前部的摘要/备考表**：2011 过渡期年报因财政年度变更，
       在管理层讨论段落前印了一套「截至二零一零年及二零一一年十二月三十一日止年度」
       的**未经审核 12 个月日历年对比**（营业额 5,568.7 百万），与后面**经审核的
       6 个月正表**（营业额 2,382.8 百万）差 2.3 倍。2012/2013 年报同样有前部摘要。
    故三重判据：① 位置过半（正表在核数师报告之后）② 标题三元组有序且间距合理
                ③ 骨架词覆盖。
    """
    A, B, C = (find_titles(lines, k) for k in ("is", "bs", "cf"))
    n = len(lines)
    best = None
    for a in A:
        if a < n * 0.25:
            continue
        bs = [b for b in B if 5 < b - a < 300]
        cs0 = [c for c in C if c > a]
        if not bs or not cs0:
            continue
        b = min(bs)
        cs = [c for c in C if 5 < c - b < 420]
        if not cs:
            continue
        c = min(cs)
        score = sum(_skeleton_hit(lines, x, k)
                    for x, k in ((a, "is"), (b, "bs"), (c, "cf")))
        if best is None or score > best[0]:
            best = (score, a, b, c)
    return best[1:] if best else None
