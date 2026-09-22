#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""特步国际 分部营收.csv —— 从一手年报附注解析「按产品」与「按品牌分部」两路。

两路数据在年报里分处两个附注：
  · 按产品（鞋类/服装/配饰）—— 收入附注，**全年份可得**
  · 按品牌分部（大众运动 Xtep / 专业运动 Saucony+Merrell / Athleisure K-Swiss+Palladium）
    —— 经营分部附注，**2019 年起**才有（此前单一分部，无需拆）

🔴 取数纪律（`财报阅读规则.md` 硬规则 1-2）：
  1. 一律取**当年年报的当年列**，严禁用后一年年报的同比 % 反推。
     故每份年报只认它自己那一年，比较列不采。
  2. 落库后跑三重勾稽：分产品和 = 分品牌和 = 利润表营业额（各自差异 <3%）。
     ⚠️ 只对其中一路 = 没跑（贵州茅台实证：分产品那路全过、分渠道那路整体左移一列
     且连续 6 年「渠道和 = 下一年营收」，因为从没对过）。本脚本三路都跑。

⚠️ Athleisure 口径断点：KP Global 于 2024-11-30 出售给控股股东关联方，FY2024 起列为
   终止经营，分部附注**不再包含 Athleisure**。故 2024/2025 的分部和 = 持续经营营业额，
   与 2023 及以前的 as-reported 口径不可直接比。

用法：python3 _build_segments.py [--check]
"""
import csv
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _parse_core as pc  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
YEARS = pc.ALL_YEARS

PROD = ("Footwear", "Apparel", "Accessories")
PROD_CN = {"Footwear": "鞋类", "Apparel": "服装", "Accessories": "配饰"}
# 分部表头关键词 → 规范名（Total 列不入库，仅用于校验）
# ⚠️ 只用**单词**锚（professional / athleisure），不用词组 —— 表头名跨行印：
#    "Professional" 在上一行、"sports" 在下一行，词组正则必然落空。
SEG_CN = [
    (re.compile(r"\bmass\b", re.I), "大众运动(特步主品牌)"),
    (re.compile(r"professional", re.I), "专业运动(索康尼+迈乐)"),
    (re.compile(r"athleisure", re.I), "Athleisure(K-Swiss+Palladium)"),
]

# 千元级整数（≥5 位）**或**破折号占位。
# ⚠️ 破折号必须一起捕：招股书配饰行 2005 年印「—」，只扫数字会让整行左移一列，
#    2006 年配饰取到 2007 的 18,177（分产品和 500.7 vs 营业额 483.6 即由此而来）。
#    这是本库 [[wide-csv-column-alignment]] 记过的同型坑。
TOK = re.compile(r"(?<![\d,.])(\d[\d,]{4,})(?![\d,.])|(?P<dash>[–—-])(?=\s|$)")


def _nums(line):
    """→ [值 or None]，破折号占位保留为 None 以**保住列位**。"""
    s = re.sub(r"(\s*\.){3,}", "  ", line)          # 去点引线
    out = []
    for m in TOK.finditer(s):
        out.append(None if m.group("dash") else float(m.group(1).replace(",", "")))
    return out


def products(name, year):
    """按产品营收（RMB'000 → 百万元）。取附注里三行齐全、且和≈营业额的那一组。"""
    lines = pc.ensure_text(name).splitlines()
    best = None
    for i, ln in enumerate(lines):
        if not re.match(r"^\s*Footwear\b", ln):
            continue
        got, ok = {}, True
        for k, tag in enumerate(PROD):
            if i + k >= len(lines):
                ok = False
                break
            m = re.match(rf"^\s*{tag}\b", lines[i + k])
            if not m:
                ok = False
                break
            v = _nums(lines[i + k])
            if not v or v[0] is None:
                ok = False
                break
            got[PROD_CN[tag]] = v[0] / 1000.0     # 当年列 = 第一个 token
        if ok and len(got) == 3:
            s = sum(got.values())
            if best is None or s > best[1]:
                best = (got, s)
    return best[0] if best else None


def segments(name, year):
    """按品牌分部营收（RMB'000 → 百万元）。取**第一处**「Sales to external customers」
    —— 分部附注先印本年表、再印上年表，第一处即本年。"""
    lines = pc.ensure_text(name).splitlines()
    for i, ln in enumerate(lines):
        if "Sales to external customers" not in ln:
            continue
        vals = _nums(ln)
        if len(vals) < 2:
            continue
        # 向上找表头（最多 14 行）。表头名跨行且乱序出现，故**按显示列排序**定列序，
        # 不能按出现先后 —— "Professional" 印在 "Mass market" 的上一行。
        found = {}
        for k in range(max(0, i - 14), i):
            for pat, cn in SEG_CN:
                m = pat.search(lines[k])
                if m and cn not in found:
                    found[cn] = pc.disp_col(lines[k], m.start())
        names = [cn for cn, _ in sorted(found.items(), key=lambda kv: kv[1])]
        if not names:
            continue
        # 末列是 Total；分部数应 = len(vals) − 1
        if len(names) != len(vals) - 1:
            return {"__warn__": f"{year} 分部名 {names} 与列数 {len(vals)} 不符"}
        return {n: v / 1000.0 for n, v in zip(names, vals)}
    return None


def seg_results(name, year):
    """按品牌分部**经营溢利**（RMB'000 → 百万元），与 segments() 同一张表同一套表头。

    🔴 这一路必须独立定列序，**不能照搬营收行的列序** —— 两者在同一年可以不同：
       FY2023 报表里营收行是「大众 / 专业 / Athleisure」，而 Segment results 行印成
       「1,891,009 / (183,894) / 8,414」，中间那列是 Athleisure、第三列才是专业运动
       （可用 FY2024 年报的 2023 比较列 8,414 独立验证）。照搬列序会把专业运动那年的
       经营溢利读成 −1.84 亿、实为 +0.08 亿。
    """
    lines = pc.ensure_text(name).splitlines()
    for i, ln in enumerate(lines):
        if not re.match(r"^\s*Segment results\b", ln):
            continue
        vals = _nums_signed(ln)
        if len(vals) < 2:
            continue
        found = {}
        for k in range(max(0, i - 16), i):
            for pat, cn in SEG_CN:
                m = pat.search(lines[k])
                if m and cn not in found:
                    found[cn] = pc.disp_col(lines[k], m.start())
        names = [cn for cn, _ in sorted(found.items(), key=lambda kv: kv[1])]
        if not names or len(names) != len(vals) - 1:
            continue
        return {n: v / 1000.0 for n, v in zip(names, vals)}
    return None


NEG = re.compile(r"\((\d[\d,]{4,})\)|(?<![\d,.(])(\d[\d,]{4,})(?![\d,.])")


def _nums_signed(line):
    """同 `_nums`，但认括号负数 —— 分部经营溢利会是负的（新品牌培育期常年亏）。"""
    out = []
    for m in NEG.finditer(re.sub(r"(\s*\.){3,}", "  ", line)):
        if m.group(1):
            out.append(-float(m.group(1).replace(",", "")))
        else:
            out.append(float(m.group(2).replace(",", "")))
    return out


def unallocated(name):
    """分部表里的「Corporate and other unallocated expenses」（本年表在前，取第一处）。"""
    for ln in pc.ensure_text(name).splitlines():
        if re.match(r"^\s*Corporate and other unallocated", ln):
            v = _nums_signed(ln)
            if v:
                return v[0] / 1000.0
    return None


def main():
    rev, oper = {}, {}
    with open(os.path.join(HERE, "利润表.csv"), encoding="utf-8") as f:
        for row in csv.reader(l for l in f if not l.startswith("#")):
            if row and row[0] == "科目":
                hdr = row[1:]
            elif row and row[0] == "营业额":
                rev = {int(hdr[i]): float(v) for i, v in enumerate(row[1:]) if v}
            elif row and row[0] == "经营溢利":
                oper = {int(hdr[i]): float(v) for i, v in enumerate(row[1:]) if v}

    data, warn, una = {}, [], {}
    srcs = [(pc.PROSPECTUS, y) for y in pc.PRE_IPO] + \
           [(f"特步国际-{y}", y) for y in pc.AR_YEARS]
    for src, y in srcs:
        if src == pc.PROSPECTUS:
            continue
        p = products(src, y)
        if p:
            for k, v in p.items():
                data.setdefault(k, {})[y] = v
        s = segments(src, y)
        if s and "__warn__" in s:
            warn.append(s["__warn__"])
        elif s:
            for k, v in s.items():
                data.setdefault(k, {})[y] = v
        sr = seg_results(src, y)
        if sr:
            for k, v in sr.items():
                data.setdefault("经营溢利-" + k, {})[y] = v
            una[y] = unallocated(src)
    # 招股书三年（上市前）只有按产品，且是**三列一张表**，与年报的「当年列」取法不同。
    # ⚠️ 不能复用 products()：那个函数要求当年列非空，而招股书配饰 2005 年印的是「—」，
    #    会被判失败。这里按列位取，破折号照样占位（保住列对齐）。
    for i, ln in enumerate(pc.ensure_text(pc.PROSPECTUS).splitlines()):
        if not re.match(r"^\s*Footwear\b", ln):
            continue
        lines = pc.ensure_text(pc.PROSPECTUS).splitlines()
        rows3 = [_nums(lines[i + k]) for k in range(3)]
        labels_ok = all(re.match(rf"^\s*{t}\b", lines[i + k])
                        for k, t in enumerate(PROD))
        # 只认「恰好三列且都是千元级绝对值」的那张表 —— 招股书里还有一张
        # 「金额 + 占比%」交替印的表（Footwear 294,817 99.1 441,948 91.4 …），
        # 列数会是 6，靠这个条件排除。
        if not labels_ok or len(rows3[0]) != 3:
            continue
        for ci, yy in enumerate(pc.PRE_IPO):
            for ri, tag in enumerate(PROD):
                if ci < len(rows3[ri]) and rows3[ri][ci] is not None:
                    data.setdefault(PROD_CN[tag], {})[yy] = rows3[ri][ci] / 1000.0
        break

    # ── 三重勾稽：分产品和 / 分品牌和 / 利润表营业额 ──
    prod_keys = list(PROD_CN.values())
    seg_keys = [cn for _, cn in SEG_CN]
    bad = []
    for y in YEARS:
        r = rev.get(y)
        if not r:
            continue
        ps = sum(data.get(k, {}).get(y, 0) for k in prod_keys)
        ss = sum(data.get(k, {}).get(y, 0) for k in seg_keys)
        if ps and abs(ps - r) / r > 0.03:
            bad.append(f"{y} 分产品和 {ps:.1f} vs 营业额 {r:.1f}")
        if ss and abs(ss - r) / r > 0.03:
            bad.append(f"{y} 分品牌和 {ss:.1f} vs 营业额 {r:.1f}")
        if ps and ss and abs(ps - ss) / max(ps, ss) > 0.03:
            bad.append(f"{y} 分产品和 {ps:.1f} vs 分品牌和 {ss:.1f}")
        # 第四路：分部经营溢利和 + 未分配开支 == 利润表经营溢利（**恒等式，不是近似**）
        rs = sum(data.get("经营溢利-" + k, {}).get(y, 0) for k in seg_keys)
        if rs and y in una and una[y] is not None and y in oper:
            if abs(rs + una[y] - oper[y]) > 0.01:
                bad.append(f"{y} 分部经营溢利和 {rs:.3f} + 未分配 {una[y]:.3f} "
                           f"≠ 利润表经营溢利 {oper[y]:.3f}")
    for w in warn:
        print("⚠️", w)
    print(f"四路勾稽：{'✅ 全部通过' if not bad else f'🔴 {len(bad)} 条不平'}")
    for b in bad:
        print("  🔴", b)
    if bad:
        return 1
    if "--check" in set(sys.argv[1:]):
        return 0

    order = prod_keys + seg_keys + ["经营溢利-" + k for k in seg_keys]
    path = os.path.join(HERE, "分部营收.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        f.write("# 分部营收（特步国际 01368.HK）· 单位：人民币百万元\n")
        f.write("# 来源：各年年报附注（收入附注=按产品；经营分部附注=按品牌分部）；"
                "一律取当年年报当年列，禁用后一年同比%反推\n")
        f.write("# 按品牌分部 2019 年起披露（此前单一分部）；Athleisure 2024 年起"
                "因 KP Global 出售列终止经营而退出分部表\n")
        f.write("# 「经营溢利-」开头的行 = 分部经营溢利（Segment results），"
                "2020 年起披露；新品牌培育期为负\n")
        f.write("# 勾稽：分产品和 = 分品牌和 = 利润表营业额（各自差异 <3%）；"
                "分部经营溢利和 + 未分配开支 == 利润表经营溢利（恒等式）——四路都跑通才写出\n")
        w.writerow(["分部"] + [str(y) for y in YEARS])
        for k in order:
            if k not in data:
                continue
            w.writerow([k] + ["" if data[k].get(y) is None else
                              f"{data[k][y]:.3f}".rstrip("0").rstrip(".")
                              for y in YEARS])
    print("写出", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
