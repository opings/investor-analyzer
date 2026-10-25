#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prose 数字体检 —— `分析.md` 正文数字 vs `财务数据/*.csv` 真值

服务于 company-analysis skill「定性结论出处体检 gate · 硬约束 4（prose 数字 == CSV）」。
该硬约束原先只写「自检一次」，没有工具；同一 gate 的硬约束 3（绝对化词 ban-list）
早已机械化。本脚本给硬约束 4 补上同级的机械查。

用法:
    python3 scripts/prose_audit.py                  # 全库扫
    python3 scripts/prose_audit.py 五粮液            # 单家
    python3 scripts/prose_audit.py --quiet          # 只打命中
    python3 scripts/prose_audit.py 五粮液 --ratios   # 另列「比例措辞」待人审清单
    python3 scripts/prose_audit.py --selftest       # 对照组：已知答案过一遍检测器
退出码: 0 = 无命中；1 = 有量级漂移命中（可作 gate）。比例措辞清单不计入退出码。

能查什么 / 查不到什么（重要，别误以为跑过就安全）:
    ✅ 量级漂移（双向）—— prose 写 8.6 亿、CSV 真值 86.19 亿（少写一位），
                  或写成 862 亿（多写一位）。×10 / ×100 两档、两个方向都查。
                  「多写」方向带两道防误报过滤：只跟本行点名年份 ±1 的列比、「累计 / 合计」分句不查
                  （所以累计数多写一位报不出来——见 DRIFT 处注释）。
    📋 比例措辞（--ratios）—— 两成 / 两倍 / 翻倍 / 四分之三 / 88.9% / 近两百亿 这类。
                  分子分母藏在句子里，脚本判不了对错：只列清单 + 本行的 CSV 指针，逐条人工用 CSV 算一遍。
                  扫 分析.md 与 财报关注要点.md（后者本不该有数字，列出来的要么是规则门槛、要么该删）。
    ❌ 错了但不是 10 / 100 倍 —— 有意不报：对不上的数常是另一个量（合计、他年、派生），全报会淹没真问题。
    ❌ 科目换了叫法 —— 只认 CSV 行首的科目名（CSV 叫「合同负债」、正文写「预收款」就对不上号）。
    ❌ 口径错   —— 单季当累计、已付当宣派、当年数用后一年同比反推。这类数字量级是对的，
                  任何量级探针都查不出来。口径靠 Step 2 清单表的「口径」列声明，不靠本脚本。

设计要点（踩过的坑，别改回去）:
    拿「本库任意 CSV 单元格」当比对池会失效 —— 池子太大，任何数都能找到近邻，
    五粮液已知错（8.6 亿 实为 86.19 亿）会被静默放过。
    必须按科目定域：只在「同一句里点名的那个科目」那一行里比。
    且科目归属要取**数字左边最近的**科目名，不是全行最长匹配
    （「利息收入 1.0 亿 > 利息费用 0.68 亿」——1.0 属于利息收入，不属于利息费用）。
    v1 只查「少写」一个方向（五粮液那次是少写）。同一类单位错读两个方向都会发生，
    单向查等于把另一半设成合法 —— 2026-10-25 补上「多写」。「多写」不加过滤会被长序列老年份与
    累计数淹没，故加年份 / 累计两道过滤；「少写」方向一行不动 —— 历史真错（五粮液合同负债、
    茅台直销那次）用修复前的 git 快照回放，新旧版命中逐条一致。
    v1 只认「阿拉伯数字 + 亿」。spacex 2026-10-24 本脚本报 0，把比例措辞逐条对 CSV 却又抓出 5 处错
    （全部商誉占总资产的比例被说成 Cursor 一家的、1.76 倍写成「约两倍」、「逐季翻倍」实为两季合计
    2.7 倍……）—— 这类措辞量级探针看不见，故加 --ratios 清单。
"""
import csv
import os
import re
import sys
import glob

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINANCE = os.path.join(REPO, "finance")

# 「1,234.5 亿」/「86 亿」——允许千分位逗号，要求「亿」紧跟
NUM = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*亿")
# 科目名取行首标签的中日文部分（去掉英文尾巴，如「归母溢利 Attributable to parent」）
# 必须收假名：日股行名如「現金及び現金同等物（现金及现金等价物）」，
# 只认 一-龥 会在「び」处断成「現金及」这种残键，进而乱匹配。
ZH_LABEL = re.compile(r"[一-龥][一-龥぀-ヿ（）()/·+\-]{1,29}")
# 括号内的中文别名（日股行名把中译名放在括号里），单独登记为一个键
ALIAS = re.compile(r"（([一-龥][^（）]{1,19})）")
TOL = 0.02          # 2% 容差：prose 多为四舍五入到一位小数
MIN_KEY_LEN = 2     # 科目名至少 2 字，防「水」「税」这类单字乱匹配

# 结构性行名，不是科目，匹配上纯属噪声
JUNK_LABEL = {"其中", "其他", "合计", "小计", "总计", "减", "加", "注", "科目", "年份"}
# 紧跟在科目名后面、把它变成「另一个量」的修饰词 —— 命中则不归属
# （「存货减值 3.05 亿」里的 3.05 不是存货余额；「合同负债波动」仍是合同负债，故不含「波动」）
MODIFIER = ("减值", "跌价", "准备", "计提", "周转", "占比", "增速", "率", "损失", "收益")

UNIT_SCALE = [      # 按优先级匹配，先命中先用
    ("百万", 1e6), ("千元", 1e3), ("'000", 1e3), ("万元", 1e4),
    ("亿", 1e8), ("million", 1e6), ("元", 1.0), ("円", 1.0),
]

# 量级漂移：prose 数 × k ≈ CSV 真值 即报。两个方向都查（v1 只有前两档）
DRIFT = ((10, "少写一位"), (100, "少写两位"), (0.1, "多写一位"), (0.01, "多写两位"))
# 「多写」方向另加两道过滤（「少写」方向保持 v1 行为不变）——
# 两个方向的误报率天生不对称：正文引的多是最近年份 = 增长序列里最大的数，它的 1/10、1/100
# 在 30–45 年长序列的老年份里几乎总能撞上一个；累计 / 合计数也只会比单年大。
# 2026-10-25 全库实测：不加过滤时「多写」方向 23 处命中只有 1 处是真错（其余 22 处是老年份巧合与累计数），
# 「少写」方向只有 2 处。
#   ① 只跟「本行点名年份 ±1」的 CSV 列比（行里没写年份才退回全部列）。
#      ±1 给财年标注错位留：日股 FY2026/3 ≈ 2025 自然年、「2025末」≈「2026 年初」。
#   ② 数字所在分句带「累计 / 合计」类词时不查。
YEAR = re.compile(r"(?:19|20)\d{2}")
YEAR_SLACK = 1
CUMULATIVE = re.compile(r"累计|合计|总计|共计|累积|之和")
CLAUSE_END = re.compile(r"[；;。|]")

# --ratios：量级检查看不见的数字措辞，只列清单、不判对错
RATIO_FILES = ("分析.md", "财报关注要点.md")
RATIO = re.compile(
    r"[一二两三四五六七八九十几数]+成[半多以上下内左右]*(?![本长功立为熟绩员型品就果分色效])"  # 两成 / 三成以上（排除「统一成本」）
    r"|[一二两三四五六七八九十百千万]分之[一二两三四五六七八九十百]+"   # 四分之三 / 百分之三十
    r"|翻[一二两三四五六七八九十几数]?[倍番]"                          # 翻倍 / 翻番 / 翻两番
    r"|(?:\d+(?:\.\d+)?|[一二两三四五六七八九十几数]+)\s*倍"           # 3.7 倍 / 两倍 / 数倍
    r"|\d+(?:\.\d+)?\s*(?:%|％|个百分点|pp)"                          # 88.9% / 3 个百分点 / 6.5pp
    r"|过半|一半|近半|大半|绝大部分|绝大多数"
    r"|[一二两三四五六七八九十百千几数]+万?亿"                         # 中文数字金额：近两百亿 / 数十亿
)
EN_QUOTE = re.compile(r'"[^"\n]*[A-Za-z]{2,}[^"\n]*"')   # 英文原文引文另有逐字核对，不列
CSV_PTR = re.compile(r"[^\s`/（）()，、；：]+\.csv")


def detect_scale(company, csv_path):
    """单位声明的真源是 财务数据/README.md（`**单位/符号**：...`），
    CSV 首行注释为备选，都没有则按「元」。返回「换算到 1 元」的乘数。"""
    readme = os.path.join(FINANCE, company, "财务数据", "README.md")
    for src in (readme, csv_path):
        if not os.path.exists(src):
            continue
        with open(src, encoding="utf-8", errors="replace") as fh:
            head = "".join(fh.readline() for _ in range(12)) if src.endswith(".md") \
                else fh.readline()
        seg = head
        if src.endswith(".md"):
            m = re.search(r"单位[/／符号]*[^\n]{0,120}", head)
            seg = m.group(0) if m else ""
        elif not seg.lstrip("﻿").startswith(("#", '"#')):
            seg = ""      # 首行是 `科目,2006,...` 之类，不含单位信息
        for token, mult in UNIT_SCALE:
            if token in seg:
                return mult
    return 1.0


def load_rows(company):
    """{科目名: [(年份, 亿元值), ...]}"""
    out = {}
    for path in sorted(glob.glob(os.path.join(FINANCE, company, "财务数据", "*.csv"))):
        scale = detect_scale(company, path)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                rows = list(csv.reader(fh))
        except Exception:
            continue
        years = []
        for r in rows[:3]:                       # 表头行：找 4 位年份或 FYxxxx
            if r and re.search(r"(19|20)\d{2}", " ".join(r[1:])):
                years = [c.strip() for c in r[1:]]
                break
        for r in rows:
            if not r or not r[0].strip():
                continue
            m = ZH_LABEL.match(r[0].strip().lstrip("﻿"))
            if not m or len(m.group(0)) < MIN_KEY_LEN:
                continue
            key = m.group(0)
            if key in JUNK_LABEL:
                continue
            pairs = []
            for i, c in enumerate(r[1:]):
                c = c.strip().replace(",", "")
                if not re.fullmatch(r"-?\d+(\.\d+)?", c or ""):
                    continue
                v = abs(float(c)) * scale / 1e8
                if v > 0:
                    pairs.append((years[i] if i < len(years) else "?", v))
            if not pairs:
                continue
            for k in {key} | {a for a in ALIAS.findall(key) if a not in JUNK_LABEL}:
                out.setdefault(k, []).extend(pairs)
    return out


def nearest(v, pairs):
    """返回该科目行里与 v 最接近的 (年份, 值)"""
    return min(pairs, key=lambda p: abs(p[1] - v)) if pairs else None


def hit(v, pairs):
    return any(abs(v - p[1]) <= TOL * max(v, p[1]) for p in pairs)


def year_of(label):
    """CSV 列名里的四位年份（「2025末」「FY2026/3」「2026前三季」→ 2025 / 2026 / 2026），没有则 None"""
    m = YEAR.search(label)
    return m.group(0) if m else None


def audit(company):
    md = os.path.join(FINANCE, company, "分析.md")
    if not os.path.exists(md):
        return []
    rows = load_rows(company)
    if not rows:
        return []
    keys = sorted(rows, key=len, reverse=True)
    found = []
    with open(md, encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            # 本行所有科目出现位置 → 供「取数字左边最近的那个」用
            occ = []
            for k in keys:
                start = 0
                while (i := line.find(k, start)) != -1:
                    if not any(o <= i < o + len(kk) for o, kk in occ):   # 不被更长科目吃掉
                        occ.append((i, k))
                    start = i + 1
            if not occ:
                continue
            occ.sort()
            named = {str(int(y) + d) for y in YEAR.findall(line)          # 本行点名的年份 ±1
                     for d in range(-YEAR_SLACK, YEAR_SLACK + 1)}
            for m in NUM.finditer(line):
                v = float(m.group(1).replace(",", ""))
                if v <= 0:
                    continue
                left = [o for o in occ if o[0] < m.start()]
                if not left:
                    continue
                pos, key = left[-1]                 # 数字左边最近的科目
                after = line[pos + len(key):m.start()]
                # 科目后紧跟修饰词 → 说的是另一个量（存货减值 ≠ 存货余额）
                if after.lstrip("：: ").startswith(MODIFIER):
                    continue
                pairs = rows[key]
                # 中间隔着一个**已对上 CSV** 的数 → 该科目已被它认领，本数另有所指
                # （「存货 23.8 亿占总资产…；已计提减值 3.05 亿」——3.05 不归存货）
                # 中间的数若同样对不上，则视为同一序列，继续归属
                # （「2020 8.6→2021 13.1→2023 6.9」整条都是合同负债，全部要报）
                if any(hit(float(g.replace(",", "")), pairs)
                       for g in NUM.findall(after)):
                    continue
                if hit(v, pairs):
                    continue                        # 本库对得上，放过
                # 「多写」方向：只跟本行点名年份 ±1 的列比，累计 / 合计分句不查
                near = [p for p in pairs if not named or year_of(p[0]) in named]
                if CUMULATIVE.search(CLAUSE_END.split(line[:m.start()])[-1]):
                    near = []
                drift = [(k, label, pairs if k > 1 else near) for k, label in DRIFT]
                drift = [d for d in drift if hit(v * d[0], d[2])]
                if drift:
                    k, label, pool = drift[0]
                    yr, real = nearest(v * k, pool)
                    found.append((lineno, key, m.group(0), label, yr, real,
                                  line.strip()[:70]))
    return found


def ratio_phrases(company):
    """--ratios：[(文件, 行号, 措辞, 本行 CSV 指针, 上下文)] —— 只列不判，逐条人工用 CSV 算一遍"""
    out = []
    for name in RATIO_FILES:
        path = os.path.join(FINANCE, company, name)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as fh:
            for lineno, line in enumerate(fh, 1):
                text = EN_QUOTE.sub(" ", line.rstrip("\n"))
                ptrs = sorted(set(CSV_PTR.findall(line)))
                for m in RATIO.finditer(text):
                    ctx = text[max(0, m.start() - 30): m.end() + 12].strip()
                    out.append((name, lineno, m.group(0), ptrs, ctx))
    return out


def print_ratios(company):
    items = ratio_phrases(company)
    if not items:
        return
    bare = sum(1 for it in items if not it[3])
    print(f"\n📋 {company} · 比例措辞 {len(items)} 处待人审（其中本行无 CSV 指针 {bare} 处）"
          "—— 量级检查看不见，逐条用 CSV 算一遍")
    for name, lineno, phrase, ptrs, ctx in items:
        where = "、".join(ptrs) if ptrs else "⚠️ 本行无 CSV 指针"
        print(f"   {name} L{lineno:<5} [{phrase}] → {where}")
        print(f"          | …{ctx}…")


def selftest():
    """对照组：造一家假公司（CSV 合同负债 = 86.19 亿），已知答案逐条过检测器。
    检测器被改坏（方向漏了、正则吞了）靠这里抓，不靠在真库上碰运气。"""
    import tempfile
    global FINANCE
    drift_cases = [
        ("合同负债 86.2 亿", None),             # 写对了
        ("合同负债 8.6 亿", "少写一位"),        # 五粮液 2026-09 原型
        ("合同负债 0.86 亿", "少写两位"),
        ("合同负债 862 亿", "多写一位"),        # v1 漏掉的方向
        ("合同负债 8619 亿", "多写两位"),
        ("合同负债 50 亿", None),               # 错了但不是 10/100 倍：设计上不报
        ("2025 年合同负债 862 亿", "多写一位"),   # 点名年份 = CSV 列年份
        ("2026 年初合同负债 862 亿", "多写一位"), # 点名年份 ±1 仍算（财年标注错位）
        ("2019 年合同负债 862 亿", None),         # 「多写」只跟点名年份 ±1 比：不拿远年份凑
        ("2019 年合同负债 8.6 亿", "少写一位"),   # 「少写」保持 v1：不按年份过滤
        ("五年累计合同负债 862 亿", None),        # 累计分句不查「多写」
    ]
    ratio_line = ('客户占三成以上，约为应收的两倍，商誉四分之三来自收购，收入翻倍、增速 88.9%，'
                  '投入近两百亿美元；原文 "revenue grew 12.5% year over year" —— 译文：略；'
                  '半成品与统一成本口径不算')
    ratio_want = ["三成以上", "两倍", "四分之三", "翻倍", "88.9%", "两百亿"]
    saved, failed = FINANCE, 0
    with tempfile.TemporaryDirectory() as tmp:
        FINANCE = tmp
        try:
            data = os.path.join(tmp, "对照公司", "财务数据")
            os.makedirs(data)
            with open(os.path.join(data, "README.md"), "w", encoding="utf-8") as fh:
                fh.write("**单位/符号**：亿元\n")
            with open(os.path.join(data, "资产负债表.csv"), "w", encoding="utf-8") as fh:
                fh.write("科目,2025\n合同负债,86.19\n")
            md = os.path.join(tmp, "对照公司", "分析.md")
            for line, want in drift_cases:
                with open(md, "w", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                hits = audit("对照公司")
                got = hits[0][3] if hits else None
                failed += got != want
                print(f"  {'✅' if got == want else '❌'} {line:<14} 预期 {want or '不报'}，实得 {got or '不报'}")
            with open(md, "w", encoding="utf-8") as fh:
                fh.write(ratio_line + "\n")
            got = [p for _, _, p, _, _ in ratio_phrases("对照公司")]
            failed += got != ratio_want
            print(f"  {'✅' if got == ratio_want else '❌'} 比例措辞清单 预期 {ratio_want}，实得 {got}")
        finally:
            FINANCE = saved
    print(f"\n对照组：{'全部符合' if not failed else f'{failed} 项不符 —— 检测器坏了，先修它'}")
    return 1 if failed else 0


def main():
    if "--selftest" in sys.argv:
        return selftest()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    quiet = "--quiet" in sys.argv
    show_ratios = "--ratios" in sys.argv
    targets = args or sorted(
        d for d in os.listdir(FINANCE)
        if os.path.isdir(os.path.join(FINANCE, d)) and not d.startswith("_")
    )
    total = 0
    for comp in targets:
        hits = audit(comp)
        if hits:
            total += len(hits)
            print(f"\n🔴 {comp} · {len(hits)} 处疑似量级漂移")
            for lineno, key, tok, label, yr, real, ctx in hits:
                print(f"   L{lineno:<5} [{key}] prose={tok:<10} "
                      f"CSV {yr} = {real:,.2f} 亿（prose {label}）")
                print(f"          | {ctx}")
        elif not quiet:
            print(f"  ✅ {comp}")
        if show_ratios:
            print_ratios(comp)
    tail = "（0 = 通过）" if total == 0 else "　⚠️ 逐条回源核对，勿批量改数"
    print(f"\n量级漂移合计 {total} 处待人审{tail}")
    if show_ratios:
        print("比例措辞清单不计入上面的合计与退出码 —— 它判不了对错，须逐条人工核完")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
