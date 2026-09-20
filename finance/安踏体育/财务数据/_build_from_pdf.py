#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安踏体育（02020.HK）三表构建器 —— 从一手财报 PDF 解析 + 勾稽校验 + 写 CSV。

真源：report/安踏体育/
  · 安踏体育-招股说明书.pdf   → 2004 / 2005 / 2006（附錄一 畢馬威會計師報告，上市前三年）
  · 安踏体育-YYYY.pdf(2007-2025) → 各年三表（本年列），上年比较列用于跨年交叉核

解析法（不依赖任何二手源）：
  1. poppler `pdftotext -layout` 抽文本（保留列位置）
  2. 自动定位「綜合損益表 → 綜合財務狀況表 → 綜合現金流量表」三元组
  3. 按**显示列**（CJK 全角算 2 列）归列；以最右 token 锚定、按列间距 delta 左行
     —— 绝对列位置在本类 PDF 抖动可达 ±9，相对间距稳定
  4. 标签归一（剥英文/去空格/统一标点）→ 别名层 → 规范科目
  5. 勾稽校验：损益 / 资产负债 / 现金流 / 跨年交叉核，**不过不写出**

用法：
    python3 _build_from_pdf.py            # 全量重建（校验通过才写 CSV）
    python3 _build_from_pdf.py --check    # 只跑校验，不写文件
    python3 _build_from_pdf.py --dump 2015 利润表   # 打印某年某表解析明细
"""
import csv
import json
import os
import re
import subprocess
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))          # finance/安踏体育/财务数据
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # 仓库根
PDF_DIR = os.path.join(ROOT, "report", "安踏体育")
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(OUT_DIR, ".txtcache")
PDFTOTEXT = "/opt/homebrew/bin/pdftotext"

AR_YEARS = list(range(2007, 2026))
PRE_IPO = [2004, 2005, 2006]          # 来自招股书附錄一
ALL_YEARS = PRE_IPO + AR_YEARS

# ─────────────────────────── 文本层 ───────────────────────────

def ensure_text(name):
    """PDF → 文本（带缓存）。返回行列表。"""
    os.makedirs(CACHE, exist_ok=True)
    txt = os.path.join(CACHE, f"{name}.txt")
    if not os.path.exists(txt):
        pdf = os.path.join(PDF_DIR, f"{name}.pdf")
        if not os.path.exists(pdf):
            raise SystemExit(f"🔴 缺一手 PDF: {pdf}")
        subprocess.run([PDFTOTEXT, "-layout", pdf, txt], check=True,
                       stderr=subprocess.DEVNULL)
    with open(txt, encoding="utf-8", errors="replace") as f:
        return f.readlines()


# ─────────────────────────── 列几何 ───────────────────────────

CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
            "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
YEAR_TOK = re.compile(r"二[零〇一二三四五六七八九]{3}年")
# 数字 token 三形态：括号负数 / 普通数 / 空值破折号
#   ⚠️ 括号内允许空格 —— 2008-2009 年报印成「(3,401,702 )」，紧贴式正则匹配不到，
#      会退化成把裸数字当**正数**读（当年销售成本/税项曾整列符号翻转）。
#   ⚠️ token 尾部绝不能放 `\s*`：会把与下一列之间的空格吞进 token，令 end 右移、整行错列。
#   ⚠️ 定位一律用**数字本身**的结束列（d1/d2），不用右括号 —— 正负数才对齐到同一列。
#   ⚠️ 「N/A」「不適用」也必须当成**占位的空值 token**：2007 年报摊薄每股盈利那行
#      上年列印的是 N/A，不识别就会少一个 token、右锚整体左移，把附註编号 12 当成数值
#      （曾把 2007 摊薄 EPS 记成 0.12，真值 0.2521）。
NUM_RE = re.compile(
    r"\(\s*(?P<d1>-?[\d][\d,]*(?:\.\d+)?)\s*\)"     # (1,234) / (1,234 )
    r"|(?P<d2>-?[\d][\d,]*(?:\.\d+)?)"              # 1,234
    r"|(?P<na>N/A|不適用|不适用)"                      # 空值：不适用
    r"|(?P<dash>[–—－])"                             # 空值：半/全角破折号
)


def disp_col(s, idx):
    """字符下标 idx 处的**显示列**（CJK 全角算 2 列）。

    pdftotext -layout 按显示宽度对齐，Python 下标按字符数 —— 混用会让含中文的
    表头与右对齐的数字列整体错位。
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
    """把一个 NUM_RE 匹配转成 (值 or None)。括号形态 = 负数；dash/na = 空值。"""
    if m.group("dash") is not None or m.group("na") is not None:
        return None
    if m.group("d1") is not None:
        return -float(m.group("d1").replace(",", ""))
    return float(m.group("d2").replace(",", ""))


def tok_end(m):
    """token 用于归列的结束位置（字符下标）——取数字本体的末尾，忽略右括号。"""
    for g in ("d1", "d2", "na", "dash"):
        if m.group(g) is not None:
            return m.end(g)
    return m.end()


def find_year_columns(lines, start, lookahead=14):
    for i in range(start, min(start + lookahead, len(lines))):
        found = [(cn_year(m.group()), disp_col(lines[i], m.end()))
                 for m in YEAR_TOK.finditer(lines[i])]
        found = [(y, c) for y, c in found if y]
        if len(found) >= 2:
            return found, i
    return None, None


def detect_scale(lines, start, lookahead=16):
    """单位探测。⚠️ 必须先去空格 —— 招股书把单位排成「（百 萬 元）」（字间加空格）。"""
    blob = re.sub(r"\s+", "", "".join(lines[start:start + lookahead]))
    if "千元" in blob:
        return 0.001, "人民幣千元"
    if "百萬元" in blob or "百万元" in blob:
        return 1.0, "人民幣百萬元"
    return None, None


BULLET = re.compile(r"^(\s*)[—–－](?=\s*[一-鿿])")


def strip_bullet(raw):
    """把行首当**项目符号**用的破折号换成等宽空格。

    「— 折舊 …… 4,522」里的 `—` 会被 NUM_RE 当成「空值」token，于是标签被算成
    它前面的空白 → 整行被丢弃（招股书的折旧/摊销调整项就是这么丢的）。
    破折号是全角（2 显示列），换成 2 个空格可保持列位置不变。
    """
    return BULLET.sub(lambda m: m.group(1) + "  ", raw)


def row_tokens(raw):
    """→ [(值 or None, 起始字符下标, 结束显示列), ...]"""
    return [(tok_value(m), m.start(), disp_col(raw, tok_end(m)))
            for m in NUM_RE.finditer(raw)]


def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def gap_samples(lines, start, end, n_years):
    """采样「恰好 n 个 token」行的列间距 → [(行号, 间距), ...]。

    不能用表头年份间距 ——「二零二五年」是全角文本，与右对齐数字列不同宽
    （实测表头间距 18、数据间距 13）。
    """
    out = []
    if n_years < 2:
        return out
    for i in range(start, min(end, len(lines))):
        toks = row_tokens(strip_bullet(lines[i].rstrip("\n")))
        if len(toks) != n_years:
            continue
        ends = [t[2] for t in toks]
        d = [ends[k + 1] - ends[k] for k in range(len(ends) - 1)]
        if all(6 <= x <= 40 for x in d) and (max(d) - min(d)) <= 4:
            out.append((i, _median(d)))
    return out


def estimate_delta(lines, start, end, n_years):
    s = gap_samples(lines, start, end, n_years)
    return _median([g for _, g in s])


def local_delta(samples, i, win=30, fallback=None):
    """取第 i 行附近的列间距中位数。

    ⚠️ 一张表可能**跨页且两页列宽不同**（2007 年报中英双语现金流量表：
    第一页间距 ~14、第二页 ~23）。用全局中位数会让另一页整页归列失败、
    整段科目静默丢值，故必须按局部窗口估计。
    """
    near = [g for idx, g in samples if abs(idx - i) <= win]
    return _median(near) or fallback


# ─────────────────────────── 标签归一 ───────────────────────────

def norm_label(s):
    """剥英文（双语年报左英右中）与阿拉伯数字、去空格、统一标点。

    必须连数字一起剥：2007 年报英文标签里嵌着数字（"at 1 January" /
    "at 31 December"），残留会让「於一月一日的現金及現金等價物」变成
    「1於一月一日的…」而匹配不上别名。中文标签只用汉字数字，故剥阿拉伯数字安全。
    """
    s = re.sub(r"[A-Za-z&'\.,%\d]+", "", s)
    s = re.sub(r"\s+", "", s)
    s = (s.replace("（", "(").replace("）", ")")
           .replace("╱", "/").replace("、", "").replace("，", "")
           .replace("－", "-").replace("　", ""))
    # 剥掉附註编号残留的空括号：「收入 1(a)」去掉字母数字后剩「收入()」
    for _ in range(3):
        s2 = re.sub(r"\(\s*\)", "", s)
        if s2 == s:
            break
        s = s2
    s = s.strip("-—–·:：")
    return s


def parse_block(lines, hdr, end, year_cols, scale, delta, tol=4):
    """解析 (hdr, end) 行，返回 [(候选标签列表, {year: value}), ...]（保留出现顺序）。

    候选标签有多个，因为标签会**跨行折行**（招股书尤甚，如
    「經 營 活動（所 用） 所 得」换行后才是「現金淨額 …数字」）：
      cands = [本行片段, 上一无数字行+片段, 上两行+片段]
    由别名层去决定哪个候选有意义；片段优先，故正常单行表不受影响。
    """
    years = [y for y, _ in year_cols]
    centers = {y: c for y, c in year_cols}
    samples = gap_samples(lines, hdr + 1, end, len(years))
    out = []
    prev = []                      # 最近的若干「无数字」行（已归一）
    for i in range(hdr + 1, min(end, len(lines))):
        raw = strip_bullet(lines[i].rstrip("\n"))
        if not raw.strip():
            prev = []
            continue
        toks = row_tokens(raw)
        if not toks:
            p = norm_label(raw)
            if p:
                prev = (prev + [p])[-2:]
            continue
        # ① 先归列，确定哪些 token 属于「数值列」
        d = local_delta(samples, i, fallback=delta)
        vals, used = {}, []
        if len(toks) == 1 and d:
            v, st0, e = toks[0]
            best = min(years, key=lambda y: abs(e - centers[y]))
            if abs(e - centers[best]) <= max(tol + 4, d // 2 + 2):
                vals[best] = None if v is None else v * scale
                used.append(st0)
        elif d:
            ends = [t[2] for t in toks]
            anchor = ends[-1]
            t2 = max(tol, int(d * 0.25))
            for k, y in enumerate(reversed(years)):
                want = anchor - k * d
                cand = [j for j, e in enumerate(ends) if abs(e - want) <= t2]
                if not cand:
                    continue
                j = min(cand, key=lambda j: abs(ends[j] - want))
                v = toks[j][0]
                vals[y] = None if v is None else v * scale
                used.append(toks[j][1])
        if not vals:
            prev = []
            continue

        # ② 标签 = **最左数值列之前**的文本。不可用 toks[0]：附註编号、以及
        #    双语年报英文标签里嵌的数字（"at 1 January"）都会提前截断标签。
        label = norm_label(raw[:min(used)])
        if not label or not re.search(r"[一-鿿]", label):
            prev = []
            continue
        cands = [label]
        if prev:
            cands.append(prev[-1] + label)
            if len(prev) > 1:
                cands.append(prev[-2] + prev[-1] + label)
        prev = []
        # 去掉标签尾巴上的「(」——2009 年报把负号左括号排在数字列最左，
        # 会被切进标签（曾产出「銷售成本(」这种伪科目名）
        cands = [re.sub(r"[(\[]+$", "", c) for c in cands]
        out.append((cands, vals))
    return out


# ─────────────────────────── 定位 ───────────────────────────

TITLE = {
    "利润表": re.compile(r"(綜合|合併)(全面收益表|損益表|損益及其他全面收益表|收益表|損益賬)"),
    "资产负债表": re.compile(r"(綜合|合併)(財務狀況表|資產負債表)"),
    "现金流量表": re.compile(r"(綜合|合併)現金流量表"),
}
SKIP_LINE = re.compile(r"\.{4,}|目錄|第\s*\d+\s*至")
EQUITY_STMT = re.compile(r"(綜合|合併)權益變動表")
NOTES_STMT = re.compile(r"(綜合)?財務報表附註|重要會計政策|主要會計政策")
# 2007/2008 年报在**合并**资产负债表之后紧接着印一张「公司資產負債表」(母公司口径)，
# 科目名几乎一样 —— 不截断的话会被当成同一张表的后续行，个别科目（流動資產淨值等）
# 取到母公司数（曾把 2006 合并流动资产净值 −27.3 取成母公司 3364.6）。
COMPANY_BS = re.compile(r"^\s*公司資產負債表|公司資產負債表\s*$")


def _has_year_header(lines, i, look=14):
    return any(len(YEAR_TOK.findall(lines[j])) >= 2
               for j in range(i, min(i + look, len(lines))))


def locate_three(lines):
    """返回 (损益起, 资产负债起, 现金流起)；标题行须在其后不远处带年份表头。"""
    def hits(key):
        return [i for i, ln in enumerate(lines)
                if TITLE[key].search(ln) and not SKIP_LINE.search(ln)
                and _has_year_header(lines, i)]
    A, B, C = hits("利润表"), hits("资产负债表"), hits("现金流量表")
    n = len(lines)
    for a in A:
        if a < n * 0.2:
            continue
        bs = [b for b in B if 5 < b - a < 220]
        if not bs:
            continue
        b = min(bs)
        cs = [c for c in C if 5 < c - b < 320]
        if not cs:
            continue
        return a, b, min(cs)
    return None


def block_end(lines, start, hard_limit):
    """表体结束：遇到权益变动表 / 公司(母公司)资产负债表 / 附註 就停。"""
    for i in range(start + 6, min(hard_limit, len(lines))):
        ln = lines[i]
        if EQUITY_STMT.search(ln) or NOTES_STMT.search(ln) or COMPANY_BS.search(ln):
            return i
    return min(hard_limit, len(lines))


# ─────────────────────────── 别名层 ───────────────────────────
# 每项 = (规范科目, [正则...], 取第几次出现)
# 取「第几次出现」而非全文唯一匹配，是因为同一标签会在表内重复：
#   · 借貸 / 定期存款 在流动与非流动各出现一次（0=流动，1=非流动）
#   · 本公司股東/非控股權益 在「溢利分配」与「全面收益分配」各一次（取 0=溢利分配）
#   · 2007 年报在合并表之后还印了一张公司层资产负债表（取 0=合并表）

IS_SPEC = [
    ("营业额",              [r"^營業額$", r"^收益$", r"^收入$"], 0),
    ("销售成本",            [r"^銷售成本"], 0),
    ("毛利",               [r"^毛利$"], 0),
    ("其他收益",            [r"^其他收益$"], 0),
    ("其他净收入",           [r"^其他淨收入$", r"^其他淨損失$", r"^其他淨\(?損失\)?/收入$",
                            r"^其他淨收入/\(損失\)$", r"^\(\)/其他淨\(損失\)/收入$"], 0),
    ("销售及分销开支",        [r"^銷售及分銷開支"], 0),
    ("行政开支",            [r"^行政開支"], 0),
    # 招股书 2004 为亏损年，标题印成「經營（虧損）溢利」等，故容忍 (虧損) 中缀
    ("经营溢利",            [r"^經營(\(虧損\))?溢利$"], 0),
    ("净融资收入",           [r"^淨融資", r"^融資收入/\(成本\)淨額$", r"^財務開支$"], 0),
    ("分占联营公司损益",      [r"^分佔聯營公司(淨)?溢利$"], 0),
    ("分占合营公司损益",      [r"^分佔合營公司(虧損|溢利|\(虧損\)/溢利|溢利/\(虧損\))$"], 0),
    ("Amer上市权益摊薄利得",  [r"上市事項權益攤薄所致的利得$"], 0),
    ("Amer配售权益摊薄利得",  [r"配售事項權益攤薄所致的利得$"], 0),
    ("可换股债券购回利得",     [r"^由購回及註銷"], 0),
    ("持续经营业务溢利",      [r"^來自持續經營業務之溢利$"], 0),
    ("非持续经营业务损益",     [r"^來自非持續經營業務之虧損$"], 0),
    ("除税前溢利",           [r"^除稅前(\(虧損\))?溢利$"], 0),
    ("税项",                [r"^稅項$", r"^所得稅$"], 0),
    ("年内溢利",             [r"^年內(\(虧損\))?溢利$"], 0),
    ("股东应占溢利",          [r"^本公司股東$"], 0),
    ("非控股权益应占溢利",     [r"^非控股權益$", r"^少數股東權益\(?$"], 0),
    ("每股盈利-基本",         [r"^基本$", r"^基本\(人民幣[分元]\)$"], 0),
    ("每股盈利-摊薄",         [r"^攤薄$", r"^攤薄\(人民幣[分元]\)$"], 0),
]

BS_SPEC = [
    # ── 非流动资产区 ──
    ("物业厂房及设备",        [r"^物業廠房及設備$"], "NCA"),
    ("在建工程",             [r"^在建工程$"], "NCA"),
    ("使用权资产",            [r"^使用權資產$"], "NCA"),
    ("租赁预付款项",          [r"^租賃預付款項$"], "NCA"),
    # ⚠️ 2016-2018 年「土地使用權預付款項」与「購買其他非流動資產預付款項」**并存**，
    #    合成一条会漏掉后者（2016 漏 245.9）。2019 起两者并为一行，归入前者。
    ("土地使用权预付款项",     [r"^土地使用權預付款項$", r"^土地使用權及其他非流動資產購買預付款項$"], "NCA"),
    ("购买其他非流动资产预付款项", [r"^購買其他非流動資產預付款項$"], "NCA"),
    ("无形资产",             [r"^無形資產$"], "NCA"),
    ("联营公司投资",          [r"^聯營公司投資$"], "NCA"),
    ("合营公司投资",          [r"^合營公司投資$"], "NCA"),
    ("其他投资-非流动",        [r"^其他投資$", r"^其他金融資產$"], "NCA"),
    ("已抵押存款-非流动",      [r"^已抵押存款$"], "NCA"),
    ("定期存款-非流动",        [r"^存款期超過三個月的銀行定期存款$", r"^定期存款$"], "NCA"),
    ("递延税项资产",          [r"^遞延稅項資產$"], "NCA"),
    ("其他非流动资产",        [r"^其他非流動資產$"], "NCA"),
    ("非流动资产合计",        [r"^非流動資產合計$"], "NCA"),

    # ── 流动资产区 ──
    ("存货",                [r"^存貨$"], "CA"),
    # ⚠️ 口径断点：2007-2017 印「應收貿易賬款及其他應收款項」合并一行；
    #    2018 起拆成「應收貿易賬款」+「其他應收款項」两行
    #    （2017 合并 3,732.7 = 纯贸易 2,088.7 + 其他 1,644.0 ✓）。
    #    故**分两行存**，不并成一条时间序列 —— 合并会凭空制造一次 −44% 的假跳水。
    ("应收贸易账款及其他应收款项", [r"^應收貿易賬款及其他應收款項$"], "CA"),
    ("应收贸易账款",          [r"^應收貿易賬款$"], "CA"),
    # 2018-2019 单列「其他應收款項」（2020 起并入「其他流動資產」）
    ("其他应收款项",          [r"^其他應收款項$"], "CA"),
    ("其他流动资产",          [r"^其他流動資產$"], "CA"),
    ("应收关联方款项",         [r"^應收關聯方款項$", r"^應收關連人士款項$"], "CA"),
    ("其他投资-流动",          [r"^其他投資$", r"^其他金融資產$"], "CA"),
    ("已抵押存款-流动",        [r"^已抵押存款$"], "CA"),
    ("定期存款-流动",          [r"^存款期超過三個月的銀行定期存款$", r"^定期存款$"], "CA"),
    ("现金及现金等价物",       [r"^現金及現金等價物$"], "CA"),
    ("流动资产合计",          [r"^流動資產合計$"], "CA"),
    ("资产总值",             [r"^資產總值$"], "ANY"),

    # ── 流动负债区 ──
    ("借贷-流动",            [r"^借貸$", r"^銀行貸款$", r"^銀行貸款\(無抵押\)$"], "CL"),
    # 同上：应付侧也在 2018 年拆行（2017 合并 3,977.7 = 纯应付 2,531.0 + 票据及其他 1,446.7）
    ("应付贸易账款及其他应付款项", [r"^應付貿易賬款及其他應付款項$"], "CL"),
    ("应付贸易账款",          [r"^應付貿易賬款$"], "CL"),
    ("应付票据及其他应付款项",  [r"^應付票據款項及其他應付款項$"], "CL"),
    ("即期应付税项",          [r"^即期應付稅項$"], "CL"),
    ("应付关联方款项",         [r"^應付關聯方款項$", r"^應付關連人士款項$"], "CL"),
    ("租赁负债-流动",          [r"^租賃負債$"], "CL"),
    ("其他流动负债",          [r"^其他流動負債$"], "CL"),
    ("流动负债合计",          [r"^流動負債合計$"], "CL"),
    ("流动资产净值",          [r"^流動資產/?\(?負債\)?淨值$", r"^流動資產淨值$"], "ANY"),
    ("资产总值减流动负债",     [r"^資產總值減流動負債$"], "ANY"),

    # ── 非流动负债区 ──
    ("借贷-非流动",           [r"^借貸$", r"^銀行貸款$"], "NCL"),
    ("租赁负债-非流动",        [r"^租賃負債$"], "NCL"),
    ("递延税项负债",          [r"^遞延稅項負債$"], "NCL"),
    ("非流动负债合计",        [r"^非流動負債合計$"], "NCL"),

    # ── 权益区 ──
    # 招股书(2004-06)印「負債總額」「權益總值」；当时无非控股权益，权益总值即股东权益
    ("负债总值",             [r"^負債總值$", r"^負債總額$"], "ANY"),
    ("资产净值",             [r"^資產淨值$", r"^權益總值$"], "ANY"),
    ("股本",                [r"^股本$"], "EQ"),
    ("储备",                [r"^儲備$"], "EQ"),
    ("股东应占权益",          [r"^本公司股東應佔權益總值$", r"^本公司權益持有人應佔權益總值$",
                             r"^權益總值$"], "ANY"),
    ("非控股权益",           [r"^非控股權益$", r"^少數股東權益$"], "EQ"),
    ("负债及权益总值",        [r"^負債及權益總值$"], "ANY"),
]

CF_SPEC = [
    ("除税前溢利",           [r"^除稅前(\(虧損\))?溢利$"], 0),
    ("折旧",                [r"^折舊$", r"^物業廠房及設備折舊$"], 0),
    ("使用权资产折旧",        [r"^使用權資產折舊$"], 0),
    ("无形资产摊销",          [r"^無形資產攤銷$"], 0),
    # 招股书里这些标题折行，故同时容忍「…（所用）產生的 / 現款」拼接后的形态
    ("经营产生的现金",        [r"^經營產生的現金$", r"^經營業務.*產生的?(現金|現款)$",
                             r"^經營業務所得現金$", r"經營業務\(所用\)產生的現款$"], 0),
    ("已付所得税",           [r"^已付所得稅$"], 0),
    ("已收利息",             [r"^已收利息$"], 0),
    ("经营活动现金净额",       [r"^經營活動(所得|產生|所產生)現金淨額$",
                             r"經營活動\(所用\)所得現金淨額$", r"^經營活動.*現金淨額$"], 0),
    ("购建物业厂房设备",       [r"^購買物業廠房及設備所付(的)?款項", r"購買物業廠房及設備所付的款項$"], 0),
    ("支付在建工程",          [r"^支付在建工程款項$"], 0),
    ("购买无形资产",          [r"^購買無形資產所付(的)?款項$"], 0),
    ("投资活动现金净额",       [r"^投資活動.*現金淨額"], 0),
    ("已付股东股息",          [r"^已付本公司股東之股息$", r"^已付股息$"], 0),
    ("融资活动现金净额",       [r"^融資活動.*現金淨額"], 0),
    ("现金净变动",            [r"^現金及現金等價物.*(增加|減少).*淨額"], 0),
    ("期初现金",             [r"^於一月一日的現金及現金等價物$"], 0),
    # 招股书用的是罕见字「㶅」(U+3D85)，非「匯/滙」—— 漏掉会让 2005 现金勾稽差 1.18 百万
    ("汇率影响",             [r"^[匯滙㶅]率變動之影響"], 0),
    ("期末现金",             [r"^於十二月三十一日的現金及現金等價物$"], 0),
]


def pick(rows, spec):
    """按别名层从 [(候选标签, {year:val})] 里挑出规范科目 → {科目: {year: val}}。"""
    out = {}
    for name, pats, occ in spec:
        rx = [re.compile(p) for p in pats]
        seen = 0
        for cands, vals in rows:
            if any(r.search(c) for c in cands for r in rx):
                if seen == occ:
                    out[name] = vals
                    break
                seen += 1
    return out


# ────────── 资产负债表的「分区」定位 ──────────
# 同一个科目名会在**流动与非流动两区各出现一次**（已抵押存款 / 存款期超過三個月的
# 銀行定期存款 / 其他投資 / 借貸 …）。只按「第几次出现」取会出事：
# 2025 年「定期存款」非流动 17,853、流动 24,275，取第 0 次就漏掉 242.75 亿流动定存；
# 而 2008-2018 年这些科目**只在流动区**出现，第 0 次又变成流动 —— 同一个 occ 下标
# 在不同年份指向不同区。故必须按小计行把表切成区，再在指定区内找。
SECT_MARKERS = [
    ("NCA", r"^非流動資產合計$"),
    ("CA", r"^流動資產合計$"),
    ("TA", r"^資產總值$"),
    ("CL", r"^流動負債合計$"),
    ("NCL", r"^非流動負債合計$"),
]


def bs_sections(rows):
    """→ {区名: (起, 止)}，下标是 rows 的区间（左闭右开）。缺某小计行则该区为空。"""
    idx = {}
    for key, pat in SECT_MARKERS:
        rx = re.compile(pat)
        for i, (cands, _) in enumerate(rows):
            if any(rx.search(c) for c in cands):
                idx.setdefault(key, i)
    n = len(rows)
    nca, ca = idx.get("NCA"), idx.get("CA")
    ta, cl, ncl = idx.get("TA"), idx.get("CL"), idx.get("NCL")
    sec = {}
    sec["NCA"] = (0, nca + 1) if nca is not None else (0, 0)
    sec["CA"] = (nca + 1, ca + 1) if (nca is not None and ca is not None) else (0, 0)
    start_cl = (ta + 1) if ta is not None else (ca + 1 if ca is not None else 0)
    sec["CL"] = (start_cl, cl + 1) if cl is not None else (0, 0)
    sec["NCL"] = (cl + 1, ncl + 1) if (cl is not None and ncl is not None) else (0, 0)
    tail = max([v[1] for v in sec.values()] + [0])
    sec["EQ"] = (tail, n)
    sec["ANY"] = (0, n)
    return sec


def pick_bs(rows, spec):
    """分区版 pick：spec 每项 = (科目, [正则], 区名)。区内找不到则留空。"""
    sec = bs_sections(rows)
    out = {}
    for name, pats, where in spec:
        rx = [re.compile(p) for p in pats]
        lo, hi = sec.get(where, sec["ANY"])
        for cands, vals in rows[lo:hi]:
            if any(r.search(c) for c in cands for r in rx):
                out[name] = vals
                break
    return out


# ─────────────────────────── 抽取 ───────────────────────────

EPS_ITEMS = ("每股盈利-基本", "每股盈利-摊薄")


def fix_eps(lines, s, e, picked_is, stmt_scale):
    """每股盈利要单独换算 —— 它不是「千元/百万元」口径。

    两件事：
      ① 撤销整表单位系数（EPS 是每股金额，被 ×0.001 会变成 0.1987 这种废数）
      ② 分辨「人民幣分」与「人民幣元」：2018-2020 年报按**分**印（198.70 分 =
         1.9870 元），2021 起按元印（1.92）。不看单位行直接采数会差 100 倍。
    """
    idx = None
    for i in range(s, min(e, len(lines))):
        if "每股盈利" in lines[i]:
            idx = i
            break
    cents = False
    if idx is not None:
        ctx = "".join(lines[max(s, idx - 5): idx + 5])
        cents = "人民幣分" in re.sub(r"\s+", "", ctx)
    factor = (0.01 if cents else 1.0) / (stmt_scale or 1.0)
    for k in EPS_ITEMS:
        if k in picked_is:
            picked_is[k] = {y: (None if v is None else v * factor)
                            for y, v in picked_is[k].items()}
    return "人民幣分" if cents else "人民幣元"


def parse_statement(lines, s, e):
    """解析单张表 → [(规范化标签, {year: val})]；返回 (rows, 单位名)。"""
    cols, hdr = find_year_columns(lines, s)
    scale, uname = detect_scale(lines, s)
    if not cols or scale is None:
        return None, None
    delta = estimate_delta(lines, hdr + 1, e, len(cols))
    if delta is None:
        return None, None
    return parse_block(lines, hdr, e, cols, scale, delta), uname


def extract_annual(year):
    """一份年报 → {'is':{科目:{年:值}}, 'bs':..., 'cf':...}（含本年列与上年比较列）。"""
    lines = ensure_text(f"安踏体育-{year}")
    loc = locate_three(lines)
    if not loc:
        raise SystemExit(f"🔴 {year} 年报三表定位失败")
    a, b, c = loc
    out, units = {}, {}
    for key, spec, s, e in (
        ("is", IS_SPEC, a, b),
        ("bs", BS_SPEC, b, block_end(lines, b, c)),
        ("cf", CF_SPEC, c, block_end(lines, c, c + 400)),
    ):
        rows, uname = parse_statement(lines, s, e)
        if rows is None:
            raise SystemExit(f"🔴 {year} {key} 表解析失败（表头/单位/列距缺失）")
        out[key] = pick_bs(rows, spec) if key == "bs" else pick(rows, spec)
        units[key] = uname
        if key == "is":
            sc, _ = detect_scale(lines, s)
            units["eps"] = fix_eps(lines, s, e, out[key], sc)
    return out, units


# ⚠️ 必须锚到附錄一「會計師報告·B 財務資料」里的**编号标题**（形如「1.   合併損益表」）。
# 招股书正文另有一节「合併損益表資料概要」(摘要·单位百万元·只列大项)，
# 若用宽松的「合併損益表」去匹配会先命中那一节 —— 拿到的是摘要不是正表。
PROSP_TITLES = {
    "is": re.compile(r"^\s*\d+\.\s*合併損益表\s*$"),
    "bs": re.compile(r"^\s*\d+\.\s*合併資產負債表\s*$"),
    "cf": re.compile(r"^\s*\d+\.\s*合併現金流量表\s*$"),
}


def extract_prospectus():
    """招股书附錄一（畢馬威會計師報告）→ 2004/2005/2006 三表。"""
    lines = ensure_text("安踏体育-招股说明书")
    pos = {}
    for key, rx in PROSP_TITLES.items():
        for i, ln in enumerate(lines):
            # 会计师报告正文里的表标题行形如「1.   合併損益表」，且其后带年份表头
            if rx.search(ln) and _has_year_header(lines, i) and not SKIP_LINE.search(ln):
                pos[key] = i
                break
    missing = [k for k in PROSP_TITLES if k not in pos]
    if missing:
        raise SystemExit(f"🔴 招股书未定位到: {missing}")
    a, b, c = pos["is"], pos["bs"], pos["cf"]
    out, units = {}, {}
    for key, spec, s, e in (
        ("is", IS_SPEC, a, b),
        ("bs", BS_SPEC, b, block_end(lines, b, c)),
        ("cf", CF_SPEC, c, block_end(lines, c, c + 400)),
    ):
        rows, uname = parse_statement(lines, s, e)
        if rows is None:
            raise SystemExit(f"🔴 招股书 {key} 表解析失败")
        out[key] = pick_bs(rows, spec) if key == "bs" else pick(rows, spec)
        units[key] = uname
        if key == "is":
            sc, _ = detect_scale(lines, s)
            units["eps"] = fix_eps(lines, s, e, out[key], sc)
    return out, units


# ─────────────────────────── 汇总 ───────────────────────────

SOURCE_OF = {}     # (表, 科目, 年) -> 取自哪份文件（血缘留痕）


def assemble():
    """按「每年取自其本年年报的本年列」汇总；招股书补 2004-2006。

    同时留下 comparative[(表,科目,年)] = 值，供跨年交叉核：
    年份 Y 的数在 AR(Y) 是本年列、在 AR(Y+1) 是上年比较列，两者应一致。
    """
    data = {"is": {}, "bs": {}, "cf": {}}       # 表 -> 科目 -> {年: 值}
    comparative = {"is": {}, "bs": {}, "cf": {}}
    units_seen = {}

    prosp, punits = extract_prospectus()
    units_seen["招股说明书"] = punits
    for st in ("is", "bs", "cf"):
        for item, vals in prosp[st].items():
            for y, v in vals.items():
                if y in PRE_IPO:
                    data[st].setdefault(item, {})[y] = v
                    SOURCE_OF[(st, item, y)] = "招股说明书"

    for year in AR_YEARS:
        ann, aunits = extract_annual(year)
        units_seen[str(year)] = aunits
        for st in ("is", "bs", "cf"):
            for item, vals in ann[st].items():
                for y, v in vals.items():
                    if y == year:                       # 本年列 = 权威
                        data[st].setdefault(item, {})[y] = v
                        SOURCE_OF[(st, item, y)] = f"{year}年报"
                    elif y == year - 1:                 # 上年比较列 = 交叉核用
                        comparative[st].setdefault(item, {})[y] = v
    derive_identities(data)
    return data, comparative, units_seen


DERIVED_NOTE = []


def derive_identities(data):
    """按报表内恒等式补两处「该年度报表体例下根本不存在的行」。

    2004-2008 年安踏没有非控股权益，故当年三表：
      · 损益表在「年內溢利」后**不设**「溢利分配為」段 → 股东应占溢利 = 年内溢利
      · 资产负债表**不印**「資產淨值」「負債總值」行（直接 資產總值減流動負債 → 權益）
        → 资产净值 = 股东应占权益
    这不是「猜数」：是同一张表内的恒等关系，且仅在**非控股权益整行不存在**时套用；
    一旦某年出现非控股权益（2009 起），立即不再推导、只用报表印出的数。
    每一处推导都登记进 SOURCE_OF 与 DERIVED_NOTE，CSV 血缘可追。
    """
    for y in ALL_YEARS:
        nci_is = data["is"].get("非控股权益应占溢利", {}).get(y)
        if data["is"].get("股东应占溢利", {}).get(y) is None and not nci_is:
            v = data["is"].get("年内溢利", {}).get(y)
            if v is not None:
                data["is"].setdefault("股东应占溢利", {})[y] = v
                SOURCE_OF[("is", "股东应占溢利", y)] = "恒等推导(=年内溢利·当年无非控股权益)"
                DERIVED_NOTE.append(f"{y} 股东应占溢利 = 年内溢利（当年损益表无「溢利分配」段）")

        nci_bs = data["bs"].get("非控股权益", {}).get(y)
        if data["bs"].get("资产净值", {}).get(y) is None and not nci_bs:
            v = data["bs"].get("股东应占权益", {}).get(y)
            if v is not None:
                data["bs"].setdefault("资产净值", {})[y] = v
                SOURCE_OF[("bs", "资产净值", y)] = "恒等推导(=股东应占权益·当年无非控股权益)"
                DERIVED_NOTE.append(f"{y} 资产净值 = 股东应占权益（当年资负表无「資產淨值」行）")


# ─────────────────────────── 校验 ───────────────────────────

# ────────── 已判读的口径断点（跨年差异白名单）──────────
# 跨年交叉核会把「本年报本年列 vs 次年年报上年比较列」逐格对照。差异并不等于解析错，
# 也可能是公司**真的重列/改口径**。下面这些已逐条回一手核实、并有算术佐证；
# 未列入此表的新差异 = 需要人判读的新情况，会被单独标红。
KNOWN_RECAST = {
    # ① 2007 全表重列：2008 年报把上海锋线（2008-05/06 出售）改列为「非持續經營業務」，
    #    2007 比较列上方明印「重列」二字。营收差 193.7 即上海锋线当年收入。
    #    现金流另叠一层列报变更：2007 年报把 −106,318 千元「滙兌差異調整」放在
    #    经营活动内，2008 年报改列到表底「滙率變動之影響」——故经营/汇率两行同步移位。
    ("is", "营业额", 2007): "2007重列·上海锋线转非持续经营",
    ("is", "销售成本", 2007): "2007重列·上海锋线转非持续经营",
    ("is", "毛利", 2007): "2007重列·上海锋线转非持续经营",
    ("is", "其他收益", 2007): "2007重列·上海锋线转非持续经营",
    ("is", "销售及分销开支", 2007): "2007重列·上海锋线转非持续经营",
    ("is", "行政开支", 2007): "2007重列·上海锋线转非持续经营",
    ("is", "经营溢利", 2007): "2007重列·上海锋线转非持续经营",
    ("is", "净融资收入", 2007): "2007重列·融资收入/成本列报口径变更",
    ("is", "除税前溢利", 2007): "2007重列·上海锋线转非持续经营",
    ("cf", "经营产生的现金", 2007): "2007重列·汇兑差异调整由经营内移至表底(+106.3·与下行同源)",
    ("cf", "经营活动现金净额", 2007): "2007重列·汇兑差异调整由经营内移至表底",
    ("cf", "投资活动现金净额", 2007): "2007重列·上海锋线转非持续经营",
    ("cf", "现金净变动", 2007): "2007重列·汇兑差异列报变更",
    ("cf", "汇率影响", 2007): "2007重列·汇兑差异由经营内移至表底(−106.3)",
    # ② 2015 起「其他收益」与「其他淨損失」合并为「其他淨收入」一行
    #    2014 比较：97.3(其他收益) + (−11.3)(其他淨損失) = 86.0 ✓
    ("is", "其他净收入", 2014): "2015起其他收益与其他净损益合并列报",
    # ③ 2018 起应收/应付拆行（已分两行存，此处仅余合并行的对照差）
    ("bs", "应付贸易账款及其他应付款项", 2017): "2018起拆行·纯应付1,446.7+票据及其他2,531.0=3,977.7 ✓",
    # ④ 2019 起 IFRS16：土地使用权预付款项部分转入使用权资产
    ("bs", "土地使用权预付款项", 2018): "2019采用IFRS16·租赁类资产重分类",
    # ⑤ 2020 起「借貸」= 銀行貸款 + 應付票據款項(融資性質)
    #    2019 比较：1,358.9 + 1,200.0 = 2,558.9 ✓
    ("bs", "借贷-流动", 2019): "2020起借贷口径并入融资性应付票据·1,358.9+1,200.0=2,558.9 ✓",
}


def _g(data, st, item, y):
    return data.get(st, {}).get(item, {}).get(y)


def approx(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol


def validate(data, comparative):
    """三表勾稽 + 跨年交叉核。返回 (errors, warnings, stats)。

    容差：单位换算后统一以「人民币百万元」计，早年千元源四舍五入到 3 位小数，
    故给 0.6 百万元（=60 万）的容差，足以吸收印刷取整而不放过真实错位。
    """
    errs, warns, known = [], [], []
    TOL = 0.6
    checked = 0

    for y in ALL_YEARS:
        rev = _g(data, "is", "营业额", y)
        cos = _g(data, "is", "销售成本", y)
        gp = _g(data, "is", "毛利", y)
        if None not in (rev, cos, gp):
            checked += 1
            if not approx(rev - abs(cos), gp, TOL):
                errs.append(f"[损益 {y}] 营收−|成本| = {rev - abs(cos):.1f} ≠ 毛利 {gp:.1f}")

        pbt = _g(data, "is", "除税前溢利", y)
        tax = _g(data, "is", "税项", y)
        pft = _g(data, "is", "年内溢利", y)
        if None not in (pbt, tax, pft):
            checked += 1
            if not approx(pbt + tax, pft, TOL):
                # 2008/2009 有非持续经营业务，需并入
                disc = _g(data, "is", "非持续经营业务损益", y) or 0
                if not approx(pbt + tax + disc, pft, TOL):
                    errs.append(f"[损益 {y}] 除税前{pbt:.1f}+税项{tax:.1f}(+非持续{disc:.1f})"
                                f" ≠ 年内溢利 {pft:.1f}")

        sh = _g(data, "is", "股东应占溢利", y)
        nci = _g(data, "is", "非控股权益应占溢利", y)
        if None not in (sh, nci, pft):
            checked += 1
            if not approx(sh + nci, pft, TOL):
                errs.append(f"[损益 {y}] 股东{sh:.1f}+非控股{nci:.1f} ≠ 年内溢利 {pft:.1f}")

        ta = _g(data, "bs", "资产总值", y)
        tl = _g(data, "bs", "负债总值", y)
        na = _g(data, "bs", "资产净值", y)
        if None not in (ta, tl, na):
            checked += 1
            if not approx(tl + na, ta, TOL):
                errs.append(f"[资负 {y}] 负债{tl:.1f}+净值{na:.1f} ≠ 资产总值 {ta:.1f}")

        nca = _g(data, "bs", "非流动资产合计", y)
        ca = _g(data, "bs", "流动资产合计", y)
        if None not in (nca, ca, ta):
            checked += 1
            if not approx(nca + ca, ta, TOL):
                errs.append(f"[资负 {y}] 非流动{nca:.1f}+流动{ca:.1f} ≠ 资产总值 {ta:.1f}")

        cap = _g(data, "bs", "股本", y)
        res = _g(data, "bs", "储备", y)
        eq = _g(data, "bs", "股东应占权益", y)
        if None not in (cap, res, eq):
            checked += 1
            if not approx(cap + res, eq, TOL):
                errs.append(f"[资负 {y}] 股本{cap:.1f}+储备{res:.1f} ≠ 股东权益 {eq:.1f}")

        nci_bs = _g(data, "bs", "非控股权益", y)
        if None not in (eq, nci_bs, na):
            checked += 1
            if not approx(eq + nci_bs, na, TOL):
                errs.append(f"[资负 {y}] 股东权益{eq:.1f}+非控股{nci_bs:.1f} ≠ 资产净值 {na:.1f}")

        # 分区构成校验：抓到的明细之和不得超过小计，且残差不得过大。
        # 这是防「某个分项被静默漏抓」的守门员 —— 曾因只按出现次序取数而漏掉
        # 2025 年流动「定期存款」242.75 亿（小计仍对得上，光看勾稽发现不了）。
        for tot_item, parts, cap in (
            ("流动资产合计", ["存货", "应收贸易账款及其他应收款项", "应收贸易账款",
                          "其他应收款项", "其他流动资产", "应收关联方款项",
                          "其他投资-流动", "已抵押存款-流动",
                          "定期存款-流动", "现金及现金等价物"], 0.02),
            ("非流动资产合计", ["物业厂房及设备", "在建工程", "使用权资产", "租赁预付款项",
                           "土地使用权预付款项", "购买其他非流动资产预付款项", "无形资产",
                           "联营公司投资", "合营公司投资",
                           "其他投资-非流动", "已抵押存款-非流动", "定期存款-非流动",
                           "递延税项资产", "其他非流动资产"], 0.02),
        ):
            tot = _g(data, "bs", tot_item, y)
            if tot is None or tot <= 0:
                continue
            got = sum(v for p in parts if (v := _g(data, "bs", p, y)) is not None)
            checked += 1
            resid = tot - got
            if resid < -TOL:
                errs.append(f"[构成 {y}] {tot_item} 明细之和 {got:.1f} > 小计 {tot:.1f}"
                            f"（重复计入 {-resid:.1f}）")
            elif resid > tot * cap:
                errs.append(f"[构成 {y}] {tot_item} 小计 {tot:.1f} − 已抓明细 {got:.1f}"
                            f" = 残差 {resid:.1f}（{resid/tot:.1%} > {cap:.0%}）—— 疑漏抓分项")

        op = _g(data, "cf", "经营活动现金净额", y)
        iv = _g(data, "cf", "投资活动现金净额", y)
        fi = _g(data, "cf", "融资活动现金净额", y)
        ch = _g(data, "cf", "现金净变动", y)
        if None not in (op, iv, fi, ch):
            checked += 1
            if not approx(op + iv + fi, ch, TOL):
                errs.append(f"[现流 {y}] 经营{op:.1f}+投资{iv:.1f}+融资{fi:.1f}"
                            f" = {op+iv+fi:.1f} ≠ 净变动 {ch:.1f}")

        beg = _g(data, "cf", "期初现金", y)
        fx = _g(data, "cf", "汇率影响", y) or 0
        end = _g(data, "cf", "期末现金", y)
        if None not in (beg, ch, end):
            checked += 1
            if not approx(beg + ch + fx, end, TOL):
                errs.append(f"[现流 {y}] 期初{beg:.1f}+净变动{ch:.1f}+汇率{fx:.1f}"
                            f" = {beg+ch+fx:.1f} ≠ 期末 {end:.1f}")

    # 跨年交叉核：AR(Y) 本年列 vs AR(Y+1) 上年比较列
    xchecked, xdiff = 0, 0
    for st in ("is", "bs", "cf"):
        for item, yv in comparative[st].items():
            for y, cv in yv.items():
                base = _g(data, st, item, y)
                if base is None or cv is None:
                    continue
                xchecked += 1
                if not approx(base, cv, max(TOL, abs(base) * 0.005)):
                    xdiff += 1
                    reason = KNOWN_RECAST.get((st, item, y))
                    msg = (f"[跨年 {st} {item} {y}] 本年列 {base:.1f} vs 次年比较列 {cv:.1f}"
                           f"（差 {cv - base:+.1f}）")
                    if reason:
                        known.append(msg + " ✔已判读：" + reason)
                    else:
                        warns.append(msg + " 🔴 未判读 —— 须回一手核实是重列还是解析错")
    return errs, warns, known, {"勾稽条数": checked, "跨年核对数": xchecked,
                                "跨年不一致": xdiff, "已判读": len(known)}


# ─────────────── 完整性自检（防「静默丢值」）───────────────
# 教训：构建器最危险的失败不是报错，而是某科目全年 None 却照常写出 CSV、
# 校验仍报 0 错（因为校验只检查「有值的那些」）。故必须独立检查必需科目的覆盖率。

REQUIRED = {
    "is": ["营业额", "销售成本", "毛利", "经营溢利", "除税前溢利", "税项",
           "年内溢利", "股东应占溢利"],
    # 元组 = 「任一存在即可」，用于口径在中途拆行的科目
    "bs": ["资产总值", "非流动资产合计", "流动资产合计", "流动负债合计",
           "资产净值", "股本", "储备", "股东应占权益", "存货",
           ("应收贸易账款", "应收贸易账款及其他应收款项"),
           ("应付贸易账款", "应付贸易账款及其他应付款项"),
           "现金及现金等价物"],
    "cf": ["经营活动现金净额", "投资活动现金净额", "融资活动现金净额",
           "现金净变动", "期初现金", "期末现金", "购建物业厂房设备"],
}
# 上市前（招股书 2004-2006）当时无非控股权益、损益表不设「溢利分配」段，
# 故这些科目在该三年确实不存在于报表 —— 按年代豁免，不当缺失。
EXEMPT_PRE_IPO = {("is", "股东应占溢利")}


def completeness(data):
    """返回 [(表, 科目, 缺失年份列表)]；必需科目缺年即视为硬错。

    ⚠️ 这一步独立于勾稽校验：勾稽只检查「有值的那些」是否自洽，
    某科目整列为空时勾稽照样报 0 错 —— 静默丢值只能靠本检查逮住。
    """
    gaps = []
    for st, items in REQUIRED.items():
        for item in items:
            alts = item if isinstance(item, tuple) else (item,)
            years = ALL_YEARS
            if any((st, a) in EXEMPT_PRE_IPO for a in alts):
                years = [y for y in ALL_YEARS if y not in PRE_IPO]
            miss = [y for y in years
                    if all(data.get(st, {}).get(a, {}).get(y) is None for a in alts)]
            if miss:
                gaps.append((st, "/".join(alts), miss))
    return gaps


# ─────────────────────────── 写出 ───────────────────────────

SHEETS = [
    ("利润表.csv", "is", IS_SPEC),
    ("资产负债表.csv", "bs", BS_SPEC),
    ("现金流量表.csv", "cf", CF_SPEC),
]
HEAD_NOTE = "单位：人民币百万元；负数=流出/减项；空=该期财报无此科目"


# ─────────────────────────── 派生比率 ───────────────────────────

def _series(data, st, item):
    d = data.get(st, {}).get(item, {})
    return [d.get(y) for y in ALL_YEARS]


def _add(*rows):
    """逐年相加，全 None 则该年 None（不把缺失当 0）。"""
    out = []
    for i in range(len(ALL_YEARS)):
        vals = [r[i] for r in rows if r[i] is not None]
        out.append(sum(vals) if vals else None)
    return out


def build_ratios(data):
    """通用底(scripts/derived.py) + 安踏定制层 → 财务比率.csv。

    本函数把安踏的港股科目名**映射**成 derived.py 别名层已识别的通用名再调用，
    而不是去改那个被多家公司共用的引擎 —— 适配放在自己这一侧，别动公共设施。
    """
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import derived

    # 应收「合并口径」：2018 年把「應收貿易賬款及其他應收款項」拆成两行、2020 年
    # 「其他應收款項」又更名「其他流動資產」。三段拼起来才是同一口径的连续序列，
    # 直接用拆分后的纯贸易应收会在 2017→2018 凭空掉 44%。
    ar_merged = _add(_series(data, "bs", "应收贸易账款及其他应收款项"),
                     _series(data, "bs", "应收贸易账款"),
                     _series(data, "bs", "其他应收款项"),
                     _series(data, "bs", "其他流动资产"))
    ap_merged = _add(_series(data, "bs", "应付贸易账款及其他应付款项"),
                     _series(data, "bs", "应付贸易账款"),
                     _series(data, "bs", "应付票据及其他应付款项"))
    capex_all = _add(_series(data, "cf", "购建物业厂房设备"),
                     _series(data, "cf", "支付在建工程"))

    PL = {
        "营业收入": _series(data, "is", "营业额"),
        "营业成本": _series(data, "is", "销售成本"),
        "毛利": _series(data, "is", "毛利"),
        "销售费用": _series(data, "is", "销售及分销开支"),
        "管理费用": _series(data, "is", "行政开支"),
        "净利润": _series(data, "is", "年内溢利"),
        "归母净利润": _series(data, "is", "股东应占溢利"),
        "利润总额": _series(data, "is", "除税前溢利"),
        "所得税费用": _series(data, "is", "税项"),
    }
    BS_ = {
        "应收账款": ar_merged,
        "存货": _series(data, "bs", "存货"),
        "应付账款": ap_merged,
        "固定资产": _series(data, "bs", "物业厂房及设备"),
        "资产总计": _series(data, "bs", "资产总值"),
        "非流动资产合计": _series(data, "bs", "非流动资产合计"),
        "流动资产合计": _series(data, "bs", "流动资产合计"),
        "权益总额": _series(data, "bs", "资产净值"),
        "归母权益": _series(data, "bs", "股东应占权益"),
        # 现金类(供「现金及金融资产/总资产」求和)
        "现金及现金等价物": _series(data, "bs", "现金及现金等价物"),
        "定期存款-流动": _series(data, "bs", "定期存款-流动"),
        "定期存款-非流动": _series(data, "bs", "定期存款-非流动"),
        "质押存款-流动": _series(data, "bs", "已抵押存款-流动"),
        "质押存款-非流动": _series(data, "bs", "已抵押存款-非流动"),
    }
    CF_ = {
        "经营活动现金流量净额": _series(data, "cf", "经营活动现金净额"),
        "购建固定资产": capex_all,
        "已付股息": _series(data, "cf", "已付股东股息"),
    }
    common, unmatched = derived.compute_common_ratios(PL, BS_, CF_)
    rows = [(n, v) for n, v, _ in common]

    # ── 安踏定制层 ──
    rev = PL["营业收入"]
    op = _series(data, "is", "经营溢利")
    parent = PL["归母净利润"]
    assoc = _series(data, "is", "分占联营公司损益")
    jv = _series(data, "is", "分占合营公司损益")
    oneoff = _add(_series(data, "is", "Amer上市权益摊薄利得"),
                  _series(data, "is", "Amer配售权益摊薄利得"),
                  _series(data, "is", "可换股债券购回利得"))
    ta = BS_["资产总计"]
    borrow = _add(_series(data, "bs", "借贷-流动"), _series(data, "bs", "借贷-非流动"))
    cashlike = _add(BS_["现金及现金等价物"], BS_["定期存款-流动"], BS_["定期存款-非流动"],
                    BS_["质押存款-流动"], BS_["质押存款-非流动"])

    def ratio(a, b):
        return [None if (a[i] is None or not b[i]) else a[i] / b[i]
                for i in range(len(ALL_YEARS))]

    # 经调整股东应占溢利 = 股东应占溢利 − 分占联营/合营 − 联营相关一次性利得
    # （对齐公司 2026 中期报告注(9) 自陈口径；本库按同一定义回算历年）
    adj = []
    for i in range(len(ALL_YEARS)):
        p = parent[i]
        if p is None:
            adj.append(None)
            continue
        adj.append(p - (assoc[i] or 0) - (jv[i] or 0) - (oneoff[i] or 0))

    netcash = [None if (cashlike[i] is None and borrow[i] is None)
               else (cashlike[i] or 0) - (borrow[i] or 0)
               for i in range(len(ALL_YEARS))]

    rows += [
        ("经营溢利率 Operating margin", ratio(op, rev)),
        ("经调整股东应占溢利率(剔联营及一次性) Adj parent margin", ratio(adj, rev)),
        ("经调整股东应占溢利 Adj parent profit(百万元)", adj),
        ("有息负债/总资产 Borrowings/TA", ratio(borrow, ta)),
        ("净现金 Net cash(百万元)", netcash),
        ("净现金/总资产 Net cash/TA", ratio(netcash, ta)),
        # 注：「现金+存款/总资产」与通用底的「现金及金融资产/总资产」同源同值，不重复出行
    ]
    # 整行全空的指标不写出（港股无「扣非归母」线 → 通用底那行必然全空，
    # 本库改用定制层的「经调整股东应占溢利率」表达同一诉求）
    rows = [(n, v) for n, v in rows if any(x is not None for x in v)]

    path = os.path.join(OUT_DIR, "财务比率.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["# 财务比率（安踏体育 02020.HK）· 派生自本目录三表，非财报直接披露"])
        w.writerow(["# 通用底 = scripts/derived.py compute_common_ratios()；其余为安踏定制层"])
        w.writerow(["# 比率为小数（0.62 = 62%）；天数为天；标(百万元)者为金额"])
        w.writerow(["# ⚠️ 应收/应付口径：2018 年拆行、2020 年更名，已按「贸易+其他」合并成连续口径"])
        w.writerow(["# ⚠️ 分红率分母用「已付股东股息」(现金流量表·年内实付)，与「宣派」口径有跨年时间差"])
        w.writerow(["指标"] + [str(y) for y in ALL_YEARS])
        for name, vals in rows:
            w.writerow([name] + ["" if v is None else f"{v:.4f}".rstrip("0").rstrip(".")
                                 for v in vals])
    print(f"  ✅ 写出 财务比率.csv（{len(rows)} 指标 × {len(ALL_YEARS)} 年）")
    if unmatched:
        print(f"  ⚠️ derived 未匹配科目：{sorted(set(unmatched))}")


def write_csvs(data):
    for fname, st, spec in SHEETS:
        path = os.path.join(OUT_DIR, fname)
        order = [name for name, _, _ in spec if name in data[st]]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([f"# {fname[:-4]}（安踏体育 02020.HK）· {HEAD_NOTE}"])
            w.writerow(["# 来源：report/安踏体育/ 招股说明书(2004-2006) + 各年年报(2007-2025) 逐行解析"])
            w.writerow(["科目"] + [str(y) for y in ALL_YEARS])
            for item in order:
                row = [item]
                for y in ALL_YEARS:
                    v = data[st][item].get(y)
                    row.append("" if v is None else f"{v:.3f}".rstrip("0").rstrip("."))
                w.writerow(row)
        print(f"  ✅ 写出 {fname}（{len(order)} 科目 × {len(ALL_YEARS)} 年）")


# ─────────────────────────── 分部营收 ───────────────────────────

CAT_ROWS = ["鞋類", "服裝", "配飾"]
CAT_NAME = {"鞋類": "鞋类", "服裝": "服装", "配飾": "配饰"}
BRANDS = [("安踏品牌", "安踏品牌"), ("FILA品牌", "FILA品牌"),
          ("其他品牌", "所有其他品牌"), ("未分配項目", "总部及未分配")]


def extract_categories(lines, year, rev_target):
    """按品类（鞋/服/配）营收：取「收入」附註里的本年+上年两列。

    ⚠️ 同一份年报里「鞋類」会出现在多张表：MD&A 摘要表（金额+占比%+上年+上年%+增速，
    5 列）、产能表、以及附註里的收入拆分表。只认第一张会取到 MD&A 那张而错得离谱
    （2022 曾算出合计 176.4 vs 营收 53,651）。故**逐个候选试，直到三项之和 = 营收**。
    """
    for i, ln in enumerate(lines):
        if not re.match(r"^\s*鞋類\s", ln):
            continue
        toks = row_tokens(strip_bullet(ln.rstrip("\n")))
        if len(toks) < 2:
            continue
        cols, hdr = None, None
        for j in range(i - 1, max(i - 26, 0), -1):     # 往回找年份表头
            c, h = find_year_columns(lines, j, lookahead=2)
            if c:
                cols, hdr = c, h
                break
        if not cols or year not in [y for y, _ in cols]:
            continue
        scale, _u = detect_scale(lines, max(hdr - 4, 0), lookahead=12)
        if scale is None:
            scale = 1.0 if year >= 2020 else 0.001
        delta = estimate_delta(lines, i, i + 6, len(cols))
        rows = parse_block(lines, hdr, i + 6, cols, scale, delta)
        got = {}
        for cands, vals in rows:
            for k in CAT_ROWS:
                if any(c == k for c in cands) and k not in got:
                    got[k] = vals.get(year)
        if len(got) == 3 and all(v is not None for v in got.values()):
            if rev_target and abs(sum(got.values()) - rev_target) <= 1.5:
                return got          # 只有加总吻合营收才认，否则继续找下一张表

    # 回退读法：2009-2013 年报只在 MD&A 给「品类 金额 占比% 上年金额 上年占比% 增速%」
    # 这种混排表，没有干净的附註拆分表。此时取每行**第一个**数字（本年金额），
    # 仍以「三项之和 = 营收」裁决，对不上就不采。
    for i, ln in enumerate(lines):
        if not re.match(r"^\s*鞋類\s", ln):
            continue
        got = {}
        for j in range(i, min(i + 8, len(lines))):
            m = re.match(r"^\s*(鞋類|服裝|配飾)\s", lines[j])
            if not m:
                continue
            toks = row_tokens(strip_bullet(lines[j].rstrip("\n")))
            if toks and toks[0][0] is not None and m.group(1) not in got:
                got[m.group(1)] = toks[0][0]
        if len(got) == 3:
            for scale in (1.0, 0.001):
                s = sum(v * scale for v in got.values())
                if rev_target and abs(s - rev_target) <= 1.5:
                    return {k: v * scale for k, v in got.items()}
    return {}


# 分部附註里要抓的三行：(输出前缀, 行标题正则, 校验用的损益表科目, 相对容差)
#   收入/毛利：分部之和应与损益表**分毫吻合** → 容差取 0（仅留取整余量）
#   業績：分部业绩合计与「经营溢利」之间**可能夹着对账项**（如 2020 年的
#        「處置合營公司部分權益之利得 14」），并非解析错，故允许 5% 以内残差并记录。
#        5% 仍足以挡住读错列（读错列的偏差是量级性的）。
SEG_ROWS = [
    ("收入", r"來自外部客戶的(收入|收益)|對外銷售|外部客戶", "营业额", 0.0),
    ("毛利", r"^\s*(分部)?毛利\s", "毛利", 0.0),
    ("业绩", r"^\s*(分部)?業績\s", "经营溢利", 0.05),
]


def extract_brands(lines, year, targets):
    """按品牌分部的 收入 / 毛利 / 业绩（= 分部经营利润）。

    分部附註的版式**逐年不同**：
      · 2021-2025：每个分部一列（安踏/FILA/其他/未分配/總計），左侧是年份小标题
      · 2019-2020：每个分部**两列**（本年、上年），即 8 个数字一行
    与其逐年硬编版式，不如**穷举几种读法、用「各分部之和 = 损益表对应科目」裁决**
    —— 读对了才会加总吻合，读错了必然对不上，校验即选择器。

    targets = {"营业额": x, "毛利": y, "经营溢利": z}（来自已建利润表）。
    「業績」行加总含「總部及未分配」列（常为负），故其校验目标是经营溢利本身。
    """
    def try_map(vals, order, scale, target, tol_frac=0.0):
        n = len(order)
        cands = []
        if len(vals) >= n:
            cands.append(vals[:n])                       # 每分部一列
        if len(vals) >= 2 * n:
            cands.append(vals[0:2 * n:2])                # 每分部两列(本年/上年)，取本年
        tol = max(1.5, abs(target or 0) * tol_frac)
        best = None
        for picked in cands:
            # 「總部及未分配」一列常印破折号（=零），不能因为它是 None 就否掉整个读法
            scaled = [(0.0 if v is None else v * scale) for v in picked]
            if not target:
                continue
            diff = abs(sum(scaled) - target)
            if diff <= tol and (best is None or diff < best[0]):
                best = (diff, dict(zip(order, scaled)))
        return best

    out, resid = {}, {}
    for i, ln in enumerate(lines):
        if "安踏品牌" not in ln or "FILA" not in ln:
            continue
        names = sorted((ln.index(k), d) for k, d in BRANDS if k in ln)
        order = [d for _, d in names]
        if len(order) < 3:
            continue
        for tag, pat, tkey, tf in SEG_ROWS:
            if tag in out:
                continue
            rx = re.compile(pat)
            for j in range(i + 1, min(i + 26, len(lines))):
                if not rx.search(lines[j]):
                    continue
                vals = [v for v, _s, _e in row_tokens(strip_bullet(lines[j].rstrip("\n")))]
                for scale in (1.0, 0.001):
                    got = try_map(vals, order, scale, targets.get(tkey), tf)
                    if got:
                        out[tag] = got[1]
                        resid[tag] = got[0]
                        break
                if tag in out:
                    break
        if "收入" in out:
            break
    return out, resid


def build_segments(data):
    """写 分部营收.csv：按品类（全期可得）+ 按品牌（分部披露起）。"""
    cats, brands, notes = {}, {}, []
    rev = {y: data["is"]["营业额"].get(y) for y in ALL_YEARS}
    for year in AR_YEARS:
        lines = ensure_text(f"安踏体育-{year}")
        c = extract_categories(lines, year, rev.get(year))
        if c:
            cats[year] = c
        tg = {"营业额": rev.get(year),
              "毛利": data["is"].get("毛利", {}).get(year),
              "经营溢利": data["is"].get("经营溢利", {}).get(year)}
        b, rs = extract_brands(lines, year, tg)
        if b:
            brands[year] = b
            for tag, d in rs.items():
                if d > 1.5:      # 与损益表科目的残差（多为分部对账项），留痕不掩盖
                    notes.append(f"ℹ️ {year} 分品牌{tag}合计与损益表口径差 {d:.0f} 百万元"
                                 f"（分部对账项，非解析错）")

    # 校验：分部之和 ≈ 损益表收入（百万取整容差 1.5）
    # ⚠️ extract_categories 走 parse_block，单位换算已在其内部完成 —— 此处**不可再乘**
    bad = []
    for y, c in sorted(cats.items()):
        s = sum(v for v in c.values() if v is not None)
        if rev.get(y) and abs(s - rev[y]) > 1.5:
            notes.append(f"🔴 {y} 分品类合计 {s:.1f} ≠ 营收 {rev[y]:.1f} —— 疑取错表，本年不采")
            bad.append(y)
    for y in bad:
        cats.pop(y, None)
    # 分部三行各自的加总校验（收入/毛利对分部合计，业绩含未分配列对经营溢利）
    for y, b in sorted(brands.items()):
        for tag, _pat, tkey, tf in SEG_ROWS:
            d = b.get(tag)
            if not d:
                continue
            tgt = data["is"].get(tkey, {}).get(y)
            s = sum(v for v in d.values() if v is not None)
            if tgt and abs(s - tgt) > max(1.5, abs(tgt) * tf):
                notes.append(f"🔴 {y} 分品牌{tag}合计 {s:.1f} ≠ {tkey} {tgt:.1f}")

    path = os.path.join(OUT_DIR, "分部营收.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["# 分部数据（安踏体育 02020.HK）· 单位：人民币百万元"])
        w.writerow(["# 来源：各年年报「收入及分部報告」附註；按品牌分部自公司开始披露之年起"])
        w.writerow(["# 校验：收入/毛利各分部合计 = 利润表同名科目；业绩合计(含总部未分配) = 经营溢利"])
        w.writerow(["# 「业绩」= 分部经营利润（公司口径「分部業績」），未分配项目多为负数"])
        w.writerow(["分部"] + [str(y) for y in ALL_YEARS])

        def emit(label, getter):
            row = [label]
            for y in ALL_YEARS:
                v = getter(y)
                row.append("" if v is None else f"{v:.3f}".rstrip("0").rstrip("."))
            w.writerow(row)

        for k in CAT_ROWS:
            def g(y, k=k):
                c = cats.get(y)
                return None if not c else c.get(k)
            emit("按品类·" + CAT_NAME[k], g)
        for tag, _pat, _t, _tf in SEG_ROWS:
            for _key, disp in BRANDS:
                def g(y, disp=disp, tag=tag):
                    b = (brands.get(y) or {}).get(tag)
                    return None if not b else b.get(disp)
                emit(f"按品牌{tag}·{disp}", g)
    nb = {t: sum(1 for b in brands.values() if t in b) for t, _p, _k, _f in SEG_ROWS}
    print(f"  ✅ 写出 分部营收.csv（品类 {len(cats)} 年 · 品牌 收入{nb['收入']}/毛利{nb['毛利']}/业绩{nb['业绩']} 年）")
    for n in notes:
        print("   " + n)
    return notes


# ─────────────────────────── main ───────────────────────────

def main():
    args = sys.argv[1:]
    if "--dump" in args:
        i = args.index("--dump")
        year, which = args[i + 1], (args[i + 2] if len(args) > i + 2 else None)
        d, u = (extract_prospectus() if year == "招股书" else extract_annual(int(year)))
        for st in ("is", "bs", "cf"):
            if which and which != st:
                continue
            print(f"\n## {year} {st} · 单位 {u[st]}")
            for item, vals in d[st].items():
                print(f"  {item:22s} {vals}")
        return

    print("# 安踏体育三表构建 —— 从一手财报 PDF 解析")
    data, comparative, units = assemble()

    gaps = completeness(data)
    errs, warns, known, stats = validate(data, comparative)

    print(f"\n## 勾稽校验：{stats['勾稽条数']} 条")
    if errs:
        print(f"🔴 勾稽不平 {len(errs)} 条：")
        for e in errs:
            print("   " + e)
    else:
        print("   ✅ 全部通过")

    print(f"\n## 完整性自检（必需科目 × {len(ALL_YEARS)} 年）")
    if gaps:
        print(f"🔴 必需科目有缺年 {len(gaps)} 项：")
        for st, item, miss in gaps:
            print(f"   {st} {item}: 缺 {miss}")
    else:
        print("   ✅ 必需科目全年齐备")

    if DERIVED_NOTE:
        print(f"\n## 恒等式推导（非报表印出行·已登记血缘）{len(DERIVED_NOTE)} 处")
        for n in DERIVED_NOTE:
            print("   · " + n)

    print(f"\n## 跨年交叉核：{stats['跨年核对数']} 格，不一致 {stats['跨年不一致']} 格"
          f"（已判读 {stats['已判读']} · 待判读 {len(warns)}）")
    for k in known:
        print("   ✔ " + k)
    for w in warns:
        print("   ⚠️ " + w)

    if errs or gaps:
        raise SystemExit("\n🔴 校验未通过 —— 按纪律不写出 CSV。先回查 PDF / 修别名层。")
    if "--check" in args:
        print("\n(--check 模式，不写文件)")
        return
    print("\n## 写出")
    write_csvs(data)
    build_ratios(data)
    build_segments(data)
    print("\n✅ 完成")


if __name__ == "__main__":
    main()
