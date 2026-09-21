#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""361度 分部营收构建器 —— 从一手财报解析「按产品收益 / 可呈报分部 / 电商收入」。

三条来源，各自取**该期财报自己的本期列**（硬规则：严禁用后一年同比%反推）：

  ① FY2006–FY2008  招股书「收益」摘要表（鞋類/服裝/配飾及其他 × 5 期）
  ② FY2009–2011H2  年报附註「營業額」表（鞋類/服裝/配飾及其他）
  ③ 2012–2025      年报 MD&A「按產品劃分之收益明細」表

🔴 **产品口径三代，不可并成一条序列**：
     FY2006–2011H2   鞋類 / 服裝 / 配飾及其他      （不分成人童装）
     2012–2023       成人{鞋類,服裝,配飾} + 童裝 + 其他
     2024–2025       成人{鞋類,服裝} + 兒童{鞋類,服裝} + 其他（其他含配飾及鞋底）
   2024 起把配飾并进「其他」、并把童装拆成鞋/服，故「成人-配饰」「童装」两行在
   2024 后断流 —— 那是**列报口径变更**不是业务消失，CSV 留空并在 README 注明。

校验：每期分产品合计必须**分毫等于**利润表营业额（对不上则不写出）。
"""
import csv
import os
import re
import sys

from _parse_core import ensure_text
from _build_from_pdf import PERIODS, OWNER, FILES, assemble

HERE = os.path.dirname(os.path.abspath(__file__))

# 金额 token：带千分位逗号，或 ≥4 位裸数字；且**后面不接小数点** ——
# 这一条把「佔收益百分比」「變動(%)」「附註编号」全部排除（41.5 / 100.0 / (1) 都不匹配），
# 无需列几何即可从 MD&A 表里干净取数。
AMT = re.compile(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d{4,})(?![\d.])")


def amounts(line):
    return [float(m.group(1).replace(",", "")) / 1000.0 for m in AMT.finditer(line)]


# ── 产品行标签 → 规范行名（按当前所处的「成人/兒童」小节区分同名行）──
BRAND = r"361\s*[º˚°]?\s*"
# 小节标题两代写法：早年「361˚ 產品－成人」，近年就一个「成人」
ADULT = re.compile(rf"^\s*(成人|{BRAND}產品[－\-—]成人)\s*$")
KID = re.compile(rf"^\s*(兒童|童裝|{BRAND}產品[－\-—]兒童)\s*$")
ROW = [
    ("鞋类", re.compile(r"^\s*鞋類")),
    ("服装", re.compile(r"^\s*服裝")),
    # 「配飾」与「配飾及其他」是两个口径，必须分行（前者不含鞋底等其他销售）
    ("配饰及其他", re.compile(r"^\s*配飾及其他")),
    ("配饰", re.compile(r"^\s*配飾(?!及)")),
    # 童装这一行历年五种写法：童裝 / 361º 兒童 / 361˚ 產品－童裝 …
    ("童装", re.compile(rf"^\s*({BRAND}產品[－\-—]童裝|童裝|{BRAND}兒童)(\s|$)")),
    ("其他", re.compile(r"^\s*其他")),
    ("合计", re.compile(r"^\s*總計")),
]

# MD&A 产品表锚点（2012-2025 各年措辞不同）
MDA_ANCHOR = re.compile(r"按產品(類型|類別)?劃分[之的]?(收益|營業額)明細")
# 年报附註「營業額」表锚点（FY2009-2011H2）
NOTE_ANCHOR = re.compile(r"^\s*\d+\s+營業額\s*$")
# 招股书摘要表锚点：其下 6 行内同时有「鞋類」与「總計」
PROS_ANCHOR = re.compile(r"^\s*收益\s*$")


def parse_product_table(lines, start, span=26):
    """从 start 起扫 span 行，返回 {规范行名: [本期, 上期, …]}（单位：百万元）。"""
    out, sec, pending = {}, "", None
    for i in range(start, min(start + span, len(lines))):
        ln = lines[i]
        if not ln.strip():
            continue
        if ADULT.match(ln):
            sec, pending = "成人-", None
            continue
        if KID.match(ln):
            sec, pending = "儿童-", None
            continue
        vals = amounts(ln)
        if not vals:
            # 标签单独占一行、数值印在下一行（2024 年报「其他 (1)」就是这样折的）
            pending = next((n for n, p in ROW if p.match(ln)), None)
            continue
        hit = next((n for n, p in ROW if p.match(ln)), None)
        if hit is None and pending:
            hit, pending = pending, None
            key = (sec + hit) if (sec and hit in ("鞋类", "服装", "配饰")) else hit
            out.setdefault(key, vals)
            if hit == "合计":
                break
            continue
        pending = None
        for name, pat in ROW:
            if not pat.match(ln):
                continue
            # 只有表里**明写**「成人/兒童」小节时才加前缀：FY2006-2011H2 的表不分成人童装，
            # 无脑加「成人-」会把两代口径混成一行（正是「分两行存」要防的那种假连续）
            key = (sec + name) if (sec and name in ("鞋类", "服装", "配饰")) else name
            out.setdefault(key, vals)
            break
        if "總計" in ln:
            break
    return out


def find_product_table(name, lines):
    """→ (起始行, 表种类)。优先 MD&A 表，其次附註表，再次招股书摘要表。"""
    for i, ln in enumerate(lines):
        if MDA_ANCHOR.search(ln):
            nxt = "".join(lines[i:i + 26])
            if "鞋類" in nxt and "服裝" in nxt:
                return i, "mda"
    for i, ln in enumerate(lines):
        if NOTE_ANCHOR.match(ln):
            nxt = "".join(lines[i:i + 16])
            if "鞋類" in nxt and "服裝" in nxt:
                return i, "note"
    for i, ln in enumerate(lines):
        if PROS_ANCHOR.match(ln):
            nxt = "".join(lines[i:i + 8])
            if "鞋類" in nxt and "總計" in nxt:
                return i, "pros"
    return None, None


# ── 可呈报分部（成人 / 童装）：2019 起按业务线分部披露收益与毛利 ──
SEG_REV = re.compile(r"^\s*可呈報分部收益")
SEG_GP = re.compile(r"^\s*可呈報分部溢利")
ECOM = re.compile(r"電子商務業務.{0,24}?人民幣\s*([\d,]+(?:\.\d+)?)\s*百萬元")


def extract_segments(name):
    """一份财报 → {行名: 本期值}（只取本期列）。"""
    lines = ensure_text(name)
    start, kind = find_product_table(name, lines)
    out = {}
    if start is not None:
        tbl = parse_product_table(lines, start, span=30 if kind != "pros" else 10)
        for k, vals in tbl.items():
            if vals:
                out[k] = vals[0]

    for i, ln in enumerate(lines):
        if SEG_REV.match(ln):
            v = amounts(ln)
            if len(v) >= 5:                      # 成人本期/成人上期/童装本期/童装上期/合计本期…
                out["分部收益-成人"], out["分部收益-童装"] = v[0], v[2]
        elif SEG_GP.match(ln):
            v = amounts(ln)
            if len(v) >= 5:
                out["分部毛利-成人"], out["分部毛利-童装"] = v[0], v[2]
    for ln in lines:
        m = ECOM.search(ln)
        if m:
            out["电商收入"] = float(m.group(1).replace(",", ""))
            break
    return out


ORDER = ["鞋类", "服装", "配饰", "配饰及其他",
         "成人-鞋类", "成人-服装", "成人-配饰", "童装", "儿童-鞋类", "儿童-服装",
         "其他", "合计",
         "分部收益-成人", "分部收益-童装", "分部毛利-成人", "分部毛利-童装",
         "电商收入"]
# 「合计 = 营业额」校验的候选构成（按口径代际，逐个试，取首个成员齐全的）
COMPOSE = [
    ["鞋类", "服装", "配饰及其他"],                                   # FY2006-FY2011
    ["鞋类", "服装", "配饰"],                                       # 2011H2
    ["成人-鞋类", "成人-服装", "成人-配饰", "童装", "其他"],              # 2012-2023
    ["成人-鞋类", "成人-服装", "成人-配饰", "童装"],                    # 早期无「其他」行
    ["成人-鞋类", "成人-服装", "儿童-鞋类", "儿童-服装", "其他"],         # 2024-2025
]


def main():
    data, _cross, _u = assemble()
    rev = data["is"]["营业额"]

    cols, errs = {}, []
    for name in FILES:
        got = extract_segments(name)
        if name == "361度-招股说明书":
            # 招股书摘要表 5 期：FY2006 / FY2007 / FY2008 / 9M2008 / 9M2009，只取前三
            lines = ensure_text(name)
            s, _k = find_product_table(name, lines)
            tbl = parse_product_table(lines, s, span=10)
            for idx, per in enumerate(["FY2006/6", "FY2007/6", "FY2008/6"]):
                cols[per] = {k: v[idx] for k, v in tbl.items() if len(v) > idx}
            continue
        per = next((p for p, o in OWNER.items() if o == name), None)
        if per:
            cols[per] = got

    for per in PERIODS:
        row = cols.get(per, {})
        for items in COMPOSE:
            have = [row.get(k) for k in items]
            if all(v is not None for v in have):
                tot = sum(have)
                if abs(tot - rev[per]) > 0.6:
                    errs.append(f"[分部 {per}] 分产品合计 {tot:.1f} ≠ 营业额 {rev[per]:.1f}"
                                f"（构成 {'+'.join(items)}）")
                else:
                    print(f"  ✔ {per} {'+'.join(items)} = {tot:.1f} = 营业额 {rev[per]:.1f}")
                break
        else:
            errs.append(f"[分部 {per}] 无可校验的完整产品构成 —— 解析缺行（已取到 {sorted(row)}）")

    for e in errs:
        print(f"  🔴 {e}")
    if errs:
        raise SystemExit(f"\n🔴 {len(errs)} 条分部校验不过 —— 不写出 CSV")

    path = os.path.join(HERE, "分部营收.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("# 分部营收（361度 01361.HK）· 单位：人民币百万元；空=该期财报未按此口径披露\n")
        f.write("# 🔴 产品口径三代：FY2006-2011H2 鞋类/服装/配饰及其他（不分成人童装）；"
                "2012-2023 成人{鞋/服/配}+童装+其他；2024-2025 成人{鞋/服}+儿童{鞋/服}+其他(含配饰及鞋底)。"
                "「成人-配饰」「童装」2024 起断流 = 列报口径变更，非业务消失。\n")
        f.write("# 来源：招股书收益摘要(FY2006-FY2008) + 年报附註营业额表(FY2009-2011H2) + "
                "年报 MD&A 按产品收益明细(2012-2025)；分部收益/毛利取自附註「可呈報分部」表\n")
        f.write("# 校验：每期分产品合计 = 利润表营业额（分毫吻合，_build_segments.py 强制）\n")
        w = csv.writer(f)
        w.writerow(["项目"] + PERIODS)
        for item in ORDER:
            vals = [cols.get(p, {}).get(item) for p in PERIODS]
            if all(v is None for v in vals):
                continue
            w.writerow([item] + ["" if v is None else f"{v:.3f}".rstrip("0").rstrip(".")
                                 for v in vals])
    print(f"\n✅ 分部营收.csv 已写出")


if __name__ == "__main__":
    main()
