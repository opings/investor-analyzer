#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prose 数字体检 —— `分析.md` 正文数字 vs `财务数据/*.csv` 真值

服务于 company-analysis skill「定性结论出处体检 gate · 硬约束 4（prose 数字 == CSV）」。
该硬约束原先只写「自检一次」，没有工具；同一 gate 的硬约束 3（绝对化词 ban-list）
早已机械化。本脚本给硬约束 4 补上同级的机械查。

用法:
    python3 scripts/prose_audit.py              # 全库扫
    python3 scripts/prose_audit.py 五粮液        # 单家
    python3 scripts/prose_audit.py --quiet      # 只打命中
退出码: 0 = 无命中；1 = 有命中（可作 gate）

能查什么 / 查不到什么（重要，别误以为跑过就安全）:
    ✅ 量级漂移 —— prose 写 8.6 亿、CSV 真值 86.19 亿（÷10 / ÷100 级别的单位错读）
    ❌ 口径错   —— 单季当累计、已付当宣派、当年数用后一年同比反推。这类数字量级是对的，
                  任何量级探针都查不出来。口径靠 Step 2 清单表的「口径」列声明，不靠本脚本。

设计要点（v1 踩过的坑，别改回去）:
    拿「本库任意 CSV 单元格」当比对池会失效 —— 池子太大，任何数都能找到近邻，
    五粮液已知错（8.6 亿 实为 86.19 亿）会被静默放过。
    必须按科目定域：只在「同一句里点名的那个科目」那一行里比。
    且科目归属要取**数字左边最近的**科目名，不是全行最长匹配
    （「利息收入 1.0 亿 > 利息费用 0.68 亿」——1.0 属于利息收入，不属于利息费用）。
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
                drift = [k for k in (10, 100) if hit(v * k, pairs)]
                if drift:
                    yr, real = nearest(v * drift[0], pairs)
                    found.append((lineno, key, m.group(0), drift[0], yr, real,
                                  line.strip()[:70]))
    return found


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    quiet = "--quiet" in sys.argv
    targets = args or sorted(
        d for d in os.listdir(FINANCE)
        if os.path.isdir(os.path.join(FINANCE, d)) and not d.startswith("_")
    )
    total = 0
    for comp in targets:
        hits = audit(comp)
        if not hits:
            if not quiet:
                print(f"  ✅ {comp}")
            continue
        total += len(hits)
        print(f"\n🔴 {comp} · {len(hits)} 处疑似量级漂移")
        for lineno, key, tok, mult, yr, real, ctx in hits:
            print(f"   L{lineno:<5} [{key}] prose={tok:<10} "
                  f"CSV {yr} = {real:,.2f} 亿（×{mult}）")
            print(f"          | {ctx}")
    tail = "（0 = 通过）" if total == 0 else "　⚠️ 逐条回源核对，勿批量改数"
    print(f"\n合计 {total} 处待人审{tail}")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
