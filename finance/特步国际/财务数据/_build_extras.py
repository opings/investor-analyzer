#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""特步国际「附注层」构建器 —— 正表之外、但判生意质量必需的三张表。

为什么要单独一支：`_build_from_pdf.py` 解析的是三张正表，而本公司的两个关键
判断**都不在正表里**——

  ① **港股无「扣非」线**：政府补贴 / 可换股债券公允价值变动 / 处置收益 全部塞在
     利润表一行「其他收益」里。不拆开就无法判「大额非经常性损益撑起净利」这条
     通用红旗（`财报阅读规则.md` Step 3.1）。→ `其他收益构成.csv`
  ② **应收账款占营收三成以上**是本公司区别于同业的结构特征，而「拨备够不够、
     账龄在往哪走」只在附注里。→ `应收账款质量.csv`
  ③ 门店数是行业块列明的核心跟踪变量，但只印在 MD&A 散文里、逐年换措辞。
     → `门店数.csv`（**断言式**：数字写在脚本里，脚本回原文校验它确实印在所引页上，
     校验不过即报错——避免手抄进 CSV 后无从复核）

取数原则同三表：**只取当年年报的当年列**，比较列仅作交叉核（`--xcheck`）。

用法：
    python3 _build_extras.py            # 全部重建（校验通过才写出）
    python3 _build_extras.py --xcheck   # 另跑跨年交叉核，只打印不写出
"""
import csv
import os
import re
import sys

import _parse_core as pc

HERE = os.path.dirname(os.path.abspath(__file__))

# ─────────────────────── 通用：在附注里切出一个「块」 ───────────────────────

NEXT_NOTE = re.compile(r"^\s{0,10}\d{1,2}\.\s+[A-Z]")
BLOCK_END = re.compile(r"unfulfilled conditions|^\s*Notes?:\s*$")
# 应收账款专用的额外终止锚：「下一个带字母的子附注」。不收这一条，账龄表 (b) 会
# 一路吃到票据到期表 (d)，而两张表都印「Within 3 months / 3 to 6 months」，
# 后者把前者覆盖掉（FY2016 实证：账龄和 16.71 亿 vs 应收净额 19.16 亿）。
# ⚠️ 不能设成全局终止锚 —— 其他收益那张表的块起点在 (i) Revenue 之前，
#    全局启用会把块砍在 (i) 上、永远走不到 (ii)。
SUBNOTE_END = re.compile(r"^\s{0,24}\([a-z]\)\s+[A-Z]")
CAPTION = re.compile(r"^(other income and gains|product categories|revenue|group)$")


def _find_block(name, head_pat, extra_end=None):
    """在 PDF 文本层里找到附注标题行，返回该标题之后的行切片。

    `head_pat` 须能整行匹配附注小标题（如 "(ii) Other income and gains"）。
    返回 [(页号, 行切片)]，可能多于一处（正文 + 目录/MD&A），由调用方打分挑。
    """
    out = []
    for pi, lines in enumerate(pc.pages(name), 1):
        for i, raw in enumerate(lines):
            if not head_pat.search(" ".join(raw.split())):
                continue
            end = len(lines)
            for j in range(i + 1, len(lines)):
                if (NEXT_NOTE.match(lines[j]) or BLOCK_END.search(lines[j])
                        or (extra_end and extra_end.search(lines[j]))):
                    end = j
                    break
            out.append((pi, lines[i:end]))
    return out


def _rows_in_note(lines, frm, cols, note_col, tol):
    """附注块专用取行 —— 与 `_parse_core._rows_in` 的差别只有一处：**折行标签合并
    不限行数、不看首字母大小写**。

    正表里科目名最多折一行、且续行以小写开头，核心解析器按那个假设写。附注里
    不成立：「Dividend income derived from an equity investment / designated at
    fair value through other comprehensive income / ("FVOCI")」折**三行**，
    而「("FVPL") and structured bank deposits」续行以左括号开头。沿用正表规则会把
    这些行的标签读成残句，别名层全部配不上。
    """
    out, pending = [], []
    for i in range(frm, len(lines)):
        raw = lines[i]
        if not raw.strip():
            pending = []
            continue
        vals = [None] * len(cols)
        first, got = None, False
        for m in pc.NUM_RE.finditer(raw):
            p = pc.disp_col(raw, pc.tok_end(m))
            if note_col is not None and abs(p - note_col) <= 7:
                if first is None:
                    first = pc.tok_start(m)
                continue
            d = [abs(p - c) for c in cols]
            j = d.index(min(d))
            if d[j] > tol:
                continue
            if first is None:
                first = pc.tok_start(m)
            if vals[j] is None:
                vals[j] = pc.tok_value(m)
                got = True
        frag = raw[:first] if first is not None else raw
        if not got:
            lb = pc.norm_label(frag)
            # 表内小标题（FY2018 在子表里又印了一行 "Other income and gains"）
            # 不是科目名，混进 pending 会污染下一行的标签
            if lb and not pc.JUNK.search(lb) and not CAPTION.search(lb):
                pending.append(frag.strip())
            continue
        label = pc.norm_label(" ".join(pending + [frag]))
        # 裸的子附注号「(a)」「(c)」：核心解析器只剥 "note 5" 那种带字的，剥不掉它。
        # 不剥则标签变成 "bills receivable (c)"，别名层整行配不上（FY2025 实证：
        # 应收票据序列只剩 2009/2011/2013 三年）
        label = re.sub(r"\s*\([a-z]\)\s*$", "", label).strip()
        pending = []
        if label and not pc.JUNK.search(label):
            out.append((label, vals, ""))
    return out


def _parse_block(block, want_years, sub_pat=None):
    """块内取 (标签 → {年: 值})。只保留 want_years 里的列。

    `sub_pat` = 子标题（如「Other income and gains」）。年份表头相对子标题的位置
    **两种都存在**：2019 起每个子表自带表头（在子标题**下方**），2009/招股书则是
    整个附注共用一个表头（在子标题**上方**）。故先从子标题往下找表头，找不到再
    退回从块首找 —— 两种版式都吃得下。
    """
    sub = 0
    if sub_pat is not None:
        for i, raw in enumerate(block):
            if sub_pat.search(" ".join(raw.split())):
                sub = i
                break
    anchors, note_col, hdr, _ = pc.col_anchors(block, sub, lookahead=12)
    if not anchors:
        anchors, note_col, hdr, _ = pc.col_anchors(block, 0, lookahead=12)
    if not anchors:
        return None
    cols = [c for _, c in anchors]
    gap = (min(cols[k + 1] - cols[k] for k in range(len(cols) - 1))
           if len(cols) > 1 else 20)
    tol = max(6, gap * 0.45)
    rows = _rows_in_note(block, max(hdr + 1, sub + 1), cols, note_col, tol)
    out = {}
    for label, vals, _sec in rows:
        got = {y: v for (y, _c), v in zip(anchors, vals)
               if v is not None and y in want_years}
        if got:
            out.setdefault(label, {}).update(got)
    return out


# ═══════════════════════ A. 其他收益构成 ═══════════════════════

# 附注级标题（块的起点）与子标题（行的起点）——两层都要，原因见 `_parse_block`
OTHER_NOTE = re.compile(r"^\d{1,2}\.\s*revenue, other income and gains", re.I)
OTHER_SUB = re.compile(r"^(\(\s*ii\s*\))?\s*other income and gains", re.I)

# 别名层：18 份年报 + 招股书里同一个概念的不同印法 → 统一科目名
OTHER_ALIAS = [
    ("政府补贴 Subsidy income",
     r"^subsidy income"),
    ("租金收入 Rental income",
     r"^rental income"),
    ("特许权使用费收入 Royalty income",
     r"^royalty income"),
    ("利息及存款投资收益 Interest/deposit income",
     r"^interest income|^(net )?income derived from|^bank interest"),
    ("FVOCI 股息收入 Dividend income",
     r"^dividend income"),
    ("可换股债券衍生部分公允价值变动 CB derivative FV",
     r"fair value (gain|loss).*(derivative component|xtep convertible)"),
    ("K-Swiss 可换股债券公允价值变动 K-Swiss CB FV",
     r"fair value.*k-?swiss convertible"),
    ("KP 可换股债券公允价值变动 KP CB FV (FVPL)",
     r"fair value gain on financial assets at fair value"),
    ("优先股衍生部分公允价值变动 Preferred-share derivative FV",
     r"fair value gain on derivative component of preferred"),
    ("处置附属公司/投资物业收益 Disposal gains",
     r"^gain on disposal|^gain on bargain purchase"),
    ("供应商罚款 Penalty charged to suppliers",
     r"^penalty charged"),
    ("废料销售 Scrap sales",
     r"^scrap sales"),
    # 2021 年一场火灾的三条相关项（年报脚注 2 自陈）——不并进「其他」，
    # 否则那年的「其他」会凭空胖一块、看不出是一次性事件
    ("火灾报废(2021) Write-off from fire",
     r"^write off of"),
    ("火灾保险赔付(2021) Insurance claims",
     r"^insurance claims"),
    ("其他 Others",
     r"^others$|^other$"),
]
OTHER_ORDER = [n for n, _ in OTHER_ALIAS]


def _alias(label, table):
    for name, pat in table:
        if re.search(pat, label, re.I):
            return name
    return None


def build_other_income(xcheck=False):
    data = {}          # 科目 → {年: 值(千元)}
    unmapped = []
    xdiff = []

    for year in pc.AR_YEARS + ["P"]:
        if year == "P":
            name, want = pc.PROSPECTUS, set(pc.PRE_IPO)
        else:
            name, want = f"特步国际-{year}", {year, year - 1}
        best = None
        for _pi, block in _find_block(name, OTHER_NOTE):
            got = _parse_block(block, want, OTHER_SUB)
            if not got:
                continue
            mapped = sum(1 for lb in got if _alias(lb, OTHER_ALIAS))
            if best is None or mapped > best[0]:
                best = (mapped, got)
        if not best:
            raise SystemExit(f"🔴 {name}: 未定位到「其他收益」附注")
        for label, byyear in best[1].items():
            key = _alias(label, OTHER_ALIAS)
            if key is None:
                unmapped.append((name, label))
                continue
            for y, v in byyear.items():
                if year == "P" or y == year:
                    # 累加不覆盖：2021 火灾把「报废」印成 PPE / 存货两行，
                    # 都归到同一科目，直接赋值会丢掉其中一行、总额勾稽即崩
                    d = data.setdefault(key, {})
                    d[y] = d.get(y, 0) + v
                elif xcheck:
                    xdiff.append((name, key, y, v))

    if unmapped:
        print("⚠️  未映射标签（须补别名层）：")
        for n, lb in unmapped:
            print(f"    {n}: {lb}")
        raise SystemExit("🔴 有未映射标签，不写出")

    # ── 校验：各项之和 == 利润表「其他收益」（单位：百万元）──
    inc = _read_csv("利润表.csv")
    bad = []
    for y in pc.ALL_YEARS:
        tot = sum(v for d in data.values() for yy, v in d.items() if yy == y)
        ref = inc.get("其他收益", {}).get(y)
        if ref is None:
            continue
        if abs(tot / 1000.0 - ref) > 0.0011:
            bad.append((y, tot / 1000.0, ref))
    if bad:
        for y, a, b in bad:
            print(f"🔴 {y} 其他收益分项和 {a:.3f} ≠ 利润表 {b:.3f}（百万元）")
        raise SystemExit("🔴 其他收益勾稽不过，不写出")

    if xcheck:
        print(f"\n[其他收益] 跨年交叉核：{len(xdiff)} 个比较列读数")
        for name, key, y, v in xdiff:
            main = data.get(key, {}).get(y)
            if main is not None and abs(main - v) > 0.5:
                print(f"    ⚠️ {name} 比较列 {key} {y}: {v} vs 当年报 {main}")
        return

    rows = [[k] + [_fmt(data.get(k, {}).get(y), 1000.0) for y in pc.ALL_YEARS]
            for k in OTHER_ORDER if k in data]
    # 派生：占除税前溢利比（判「非经常性损益撑利润」用）
    pbt = inc.get("除税前溢利", {})
    subsidy = data.get("政府补贴 Subsidy income", {})
    fv_keys = [k for k in data if "公允价值变动" in k]
    r_sub, r_fv, r_nonop = [], [], []
    for y in pc.ALL_YEARS:
        p = pbt.get(y)
        s = subsidy.get(y)
        f = sum(data[k][y] for k in fv_keys if y in data[k])
        r_sub.append(_fmt(round(s / 1000.0 / p, 4) if p and s else None))
        r_fv.append(_fmt(round(f / 1000.0 / p, 4) if p and f else None))
        r_nonop.append(_fmt(round((s / 1000.0 + f / 1000.0) / p, 4)
                            if p and s else None))
    rows.append(["政府补贴/除税前溢利 Subsidy/PBT"] + r_sub)
    rows.append(["公允价值类合计/除税前溢利 FV/PBT"] + r_fv)
    rows.append(["(补贴+公允价值)/除税前溢利"] + r_nonop)

    _write_csv(
        "其他收益构成.csv",
        ["# 其他收益构成（特步国际 01368.HK）· 单位：人民币百万元（比率为小数）"
         "——与三表同单位，原因见 _build_extras.py 的 _fmt() 注释",
         "# 来源：各年年报「收入、其他收益及收益净额」附注（2005-2007 取招股书附錄一"
         "会计师报告附注 5）；只取当年年报当年列",
         "# ⚠️ 港股 IFRS **无「扣非」线** —— 本表是判「非经常性损益撑利润」的替代口径",
         "# ⚠️ 2023 列为 as-reported（含 KP Global）；FY2024 年报把 2023 重述为持续经营"
         "口径 276,224，两者不同轴",
         "# 校验：各分项之和 == 利润表.csv「其他收益」（已通过）"],
        ["科目"] + [str(y) for y in pc.ALL_YEARS], rows)
    print(f"✅ 其他收益构成.csv  {len(rows)} 行 × {len(pc.ALL_YEARS)} 年")


# ═══════════════════════ B. 应收账款质量 ═══════════════════════

AR_HEAD = re.compile(
    r"^\d{0,2}\.?\s*Trade and bills receivables$|^\d{0,2}\.?\s*Trade receivables$",
    re.I)

AR_ALIAS = [
    ("应收贸易账款-总额 Gross trade receivables", r"^trade receivables$"),
    ("减值拨备 Impairment allowance",
     r"^less:? (provision for impaired|impairment of trade)"),
    ("应收票据 Bills receivable", r"^bills receivables?$"),
]
AGE_ALIAS = [
    ("账龄-3个月内 Within 3 months", r"^within 3 months$"),
    ("账龄-3至6个月 3 to 6 months", r"^(3|4) to 6 months$"),
    ("账龄-6至9个月 6 to 9 months", r"^6 to 9 months$"),
    ("账龄-9个月以上 Over 9 months", r"^over 9 months$"),
    ("账龄-6个月以上 Over 6 months", r"^over 6 months$"),
]
# ⚠️ 措辞逐年换：2013-2016 印 "aged analysis"、2018 起印 "ageing analysis"，
#    且尾巴由 "net of provision" 变 "net of impairment"。只写 `aged?` 会漏掉后半段
#    十年（实证：账龄序列一度只剩 2013-2016）
AGE_HEAD = re.compile(
    r"age(d|ing)? analysis of the trade receivables.*invoice date", re.I)


# 中期时点（2026-06-30，未经审核）—— 应收账款是**时点**科目，与各年 12-31 的时点数
# 同轴可比（不是期间流量，不存在「半年当全年比」的问题）。数字取自
# 《二零二六年度中期业绩公布》内含之中期报告 P65 附注 12（cninfo 1225500649）。
# ⚠️ 中报**不入 `report/`**（本库只收招股书 + 年报），故脚本无法回原文校验，
#    只能校验算术（总额−拨备=净额、账龄和=净额）。年报出来后此列应被 FY2026 覆盖。
INTERIM = {
    "col": "2026H1",
    "应收贸易账款-总额 Gross trade receivables": 5095384,
    "减值拨备 Impairment allowance": -431040,
    "应收贸易账款-净额 Net": 4664344,
    "应收票据 Bills receivable": 498790,
    "账龄-3个月内 Within 3 months": 2210211,
    "账龄-3至6个月 3 to 6 months": 1476632,
    "账龄-6至9个月 6 to 9 months": 839189,
    "账龄-9个月以上 Over 9 months": 138312,
}


def _check_interim():
    g = INTERIM["应收贸易账款-总额 Gross trade receivables"]
    p = INTERIM["减值拨备 Impairment allowance"]
    n = INTERIM["应收贸易账款-净额 Net"]
    ages = sum(v for k, v in INTERIM.items() if k.startswith("账龄"))
    if g + p != n or ages != n:
        raise SystemExit(f"🔴 中期列算术不平：{g}+{p}={g+p} / 账龄和 {ages} / 净额 {n}")


def build_ar_quality():
    _check_interim()
    main, aging = {}, {}
    for year in pc.AR_YEARS:
        name, want = f"特步国际-{year}", {year}
        best = None
        for _pi, block in _find_block(name, AR_HEAD, SUBNOTE_END):
            got = _parse_block(block, want)
            if not got:
                continue
            mapped = sum(1 for lb in got if _alias(lb, AR_ALIAS))
            if best is None or mapped > best[0]:
                best = (mapped, got)
        if best:
            for label, byyear in best[1].items():
                key = _alias(label, AR_ALIAS)
                if key and year in byyear:
                    main.setdefault(key, {})[year] = byyear[year]
        # 账龄表（另一个块，标题是散文句）
        for _pi, block in _find_block(name, AGE_HEAD, SUBNOTE_END):
            got = _parse_block(block, want)
            if not got:
                continue
            for label, byyear in got.items():
                key = _alias(label, AGE_ALIAS)
                if key and year in byyear:
                    aging.setdefault(key, {})[year] = byyear[year]

    # ── 校验 1：总额 − 拨备 = 净额（净额与资产负债表对齐）──
    bs = _read_csv("资产负债表.csv")
    net_bs = bs.get("应收贸易账款", {})
    bad = []
    for y in pc.AR_YEARS:
        g = main.get("应收贸易账款-总额 Gross trade receivables", {}).get(y)
        p = main.get("减值拨备 Impairment allowance", {}).get(y)
        n = net_bs.get(y)
        if g is None or p is None or n is None:
            continue
        if abs((g + p) / 1000.0 - n) > 0.002:      # 拨备已带负号
            bad.append(("净额", y, (g + p) / 1000.0, n))
    # ── 校验 2：账龄各档之和 = 应收净额 ──
    for y in pc.AR_YEARS:
        s = sum(d[y] for d in aging.values() if y in d)
        n = net_bs.get(y)
        if not s or n is None:
            continue
        if abs(s / 1000.0 - n) > 0.002:
            bad.append(("账龄和", y, s / 1000.0, n))
    if bad:
        for k, y, a, b in bad:
            print(f"🔴 {y} {k} {a:.3f} ≠ 资产负债表应收净额 {b:.3f}（百万元）")
        raise SystemExit("🔴 应收账款勾稽不过，不写出")

    years = [y for y in pc.AR_YEARS
             if any(y in d for d in list(main.values()) + list(aging.values()))]
    order = ([n for n, _ in AR_ALIAS] + ["应收贸易账款-净额 Net"]
             + [n for n, _ in AGE_ALIAS])
    main["应收贸易账款-净额 Net"] = {y: net_bs[y] * 1000 for y in years
                                    if y in net_bs}
    src = {**main, **aging}
    # 中期列并进来（时点同轴）
    IC = INTERIM["col"]
    for k, v in INTERIM.items():
        if k != "col":
            src.setdefault(k, {})[IC] = v
            (aging if k.startswith("账龄") else main).setdefault(k, {})[IC] = v
    cols = years + [IC]
    rows = [[k] + [_fmt(src.get(k, {}).get(y), 1000.0) for y in cols]
            for k in order if k in src]
    # 派生：拨备率 + 3 个月以上账龄占比（判「账龄在往哪走」）
    gross = main.get("应收贸易账款-总额 Gross trade receivables", {})
    prov = main.get("减值拨备 Impairment allowance", {})
    r_rate, r_old = [], []
    for y in cols:
        g, p = gross.get(y), prov.get(y)
        r_rate.append(_fmt(round(-p / g, 4) if g and p else None))
        tot = sum(d[y] for d in aging.values() if y in d)
        old = sum(d[y] for k, d in aging.items()
                  if y in d and "3个月内" not in k)
        r_old.append(_fmt(round(old / tot, 4) if tot else None))
    rows.append(["拨备率 Allowance/Gross"] + r_rate)
    rows.append(["3个月以上账龄占比 >3M share of net"] + r_old)

    _write_csv(
        "应收账款质量.csv",
        ["# 应收账款质量（特步国际 01368.HK）· 单位：人民币百万元（比率为小数）"
         "——与三表同单位，原因见 _build_extras.py 的 _fmt() 注释",
         "# 来源：各年年报「应收贸易账款及应收票据」附注；只取当年年报当年列",
         "# ⚠️ 账龄按**发票日期、减值后净额**列示；分档口径 2018 年前为「3 个月内 / "
         "4-6 个月 / 6 个月以上」，2018 年起细分到 9 个月，故两段不可直接接续",
         "# ⚠️ 末列 2026H1 = 2026-06-30 **未经审核**时点数（中期业绩公布内含中期报告 "
         "P65 附注 12 · cninfo 1225500649）。应收是时点科目、与各年 12-31 同轴可比；"
         "中报不入 report/，故该列只过算术校验、无法回原文复核",
         "# 校验：总额 − 拨备 = 资产负债表应收净额；账龄各档之和 = 应收净额（已通过）"],
        ["科目"] + [str(y) for y in years] + [INTERIM["col"]], rows)
    print(f"✅ 应收账款质量.csv  {len(rows)} 行 × {len(years)} 年 + 中期列")


# ═══════════════════════ C. 门店数 ═══════════════════════

# 断言式：(年, 指标, 值, 引用页) —— 脚本回原文校验「该页确实印着这个数」。
# 只录**年报自陈的 12 月 31 日时点数**；「约 7,000」「逾 6,200」这类约数不录
# （宁缺勿凑：约数与时点数混在一条序列里会造出假的增减）。
STORE_FACTS = [
    (2009, "特步品牌门店(内地及海外)", 6533, 32),
    (2018, "特步品牌门店(内地及海外)", 6230, 27),
    (2019, "特步品牌门店(内地及海外)", 6379, 32),
    (2020, "特步品牌门店(内地及海外)", 6021, 18),
    (2021, "特步品牌门店(内地及海外)", 6151, 30),
    (2022, "特步成人门店(内地及海外)", 6313, 26),
    (2023, "特步成人门店(内地及海外)", 6571, 20),
    (2024, "特步成人门店(内地及海外)", 6382, 24),
    (2025, "特步成人门店(内地及海外)", 6357, 19),
    (2022, "特步儿童门店(内地)", 1520, 27),
    (2023, "特步儿童门店(内地)", 1703, 21),
    (2024, "特步儿童门店(内地)", 1584, 25),
    # 🔴 2025 缺一格不是漏抄：FY2025 年报把童装品牌由「Xtep Kids」改名「X Young」，
    #    同时**不再披露其门店数**（全文无 kids/X Young 门店数句；只给成人 6,357、
    #    索康尼 175）。跟踪了三年的指标被停披露，属「指标被改定义或停披露」形态。
    (2023, "索康尼门店(内地)", 110, 22),
    (2024, "索康尼门店(内地)", 145, 26),
    (2025, "索康尼门店(内地)", 175, 22),
]


def build_stores():
    years = sorted({y for y, *_ in STORE_FACTS})
    metrics, bad = [], []
    for year, metric, val, page in STORE_FACTS:
        if metric not in metrics:
            metrics.append(metric)
        txt = "\n".join(pc.pages(f"特步国际-{year}")[page - 1])
        if f"{val:,}" not in txt and str(val) not in txt:
            bad.append((year, metric, val, page))
    if bad:
        for y, m, v, p in bad:
            print(f"🔴 {y} {m}={v} 在 p{p} 原文中查无此数")
        raise SystemExit("🔴 门店数断言校验不过，不写出")

    idx = {(y, m): v for y, m, v, _ in STORE_FACTS}
    rows = [[m] + [_fmt(idx.get((y, m))) for y in years] for m in metrics]
    _write_csv(
        "门店数.csv",
        ["# 门店数（特步国际 01368.HK）· 单位：家 · 时点 = 各年 12 月 31 日",
         "# 来源：各年年报「管理层讨论与分析 / 业务回顾」散文句（非附注表格）；"
         "脚本逐条回原文校验数字确实印在所引页上",
         "# ⚠️ 只录年报自陈的时点数；「约 7,000 家」「逾 6,200 家」这类约数不录 —— "
         "约数与时点数混成一条序列会造出假的增减。故 2010-2017 留空 = 未给时点数，"
         "**不是没有门店**",
         "# ⚠️ 2022 年起口径由「特步品牌」细分为「特步成人 / 特步少年」，两段不可直接接续",
         "# 引用页 = PDF 物理页：" + " · ".join(
             f"{y}p{p}" for y, _m, _v, p in STORE_FACTS)],
        ["指标"] + [str(y) for y in years], rows)
    print(f"✅ 门店数.csv  {len(rows)} 行 × {len(years)} 年")


# ═══════════════════════ 小工具 ═══════════════════════


def _fmt(v, scale=1.0):
    """写出值。`scale` 用于把附注原始口径（RMB'000）换成本目录统一的百万元。

    🔴 **为什么必须跟三表统一到百万元**：`scripts/prose_audit.py` 的单位探测
    **先读 `财务数据/README.md` 的「单位」行、再退回 CSV 首行注释**，也就是同一个
    目录里的所有 CSV 共用 README 声明的那一个单位。本文件若留在千元，
    prose_audit 会把 316（千元）当成 316 百万 = 3.16 亿去比对 —— 既造假阳性，
    也会让真正的量级漂移被错误的基准掩盖。一个目录只用一个单位。
    """
    if v is None:
        return ""
    v = v / scale if scale != 1.0 else v
    if isinstance(v, float) and abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    # 6 位小数再去尾零：同一个格式串要同时装下 301.084（百万元）和 0.0303（比率），
    # 位数给少了会把比率截成 0.03
    return f"{v:.6f}".rstrip("0").rstrip(".")


def _read_csv(fn):
    out = {}
    with open(os.path.join(HERE, fn), encoding="utf-8") as f:
        rows = [r for r in csv.reader(f) if r and not r[0].startswith("#")]
    years = [int(y) for y in rows[0][1:]]
    for r in rows[1:]:
        out[r[0]] = {y: float(v) for y, v in zip(years, r[1:]) if v != ""}
    return out


def _write_csv(fn, comments, header, rows):
    with open(os.path.join(HERE, fn), "w", encoding="utf-8", newline="") as f:
        for c in comments:
            f.write(c + "\n")
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


if __name__ == "__main__":
    xc = "--xcheck" in sys.argv
    build_other_income(xcheck=xc)
    if not xc:
        build_ar_quality()
        build_stores()
