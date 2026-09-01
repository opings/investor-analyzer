#!/usr/bin/env python3
"""NSG 分部数据生成器 —— 从 有価証券報告書 的「報告セグメントごとの実績」注记解析

产出 `分部营收.csv`：报告分部 × 年 × 指标（外部売上高 / 分部间 / 分部利益 / 折旧 / 减值 / capex）。

三个必须专门处理的点：
  1) **行名与数字错行**：分部利益那行的行名被拆成两半、数字**夹在中间**
     （'個別開示項目前営業利益' / 数字 / '（セグメント利益）（△は損失）'），
     按"行首标签"取会整行丢失，必须向前拼纯文字行。
  2) **分部名逐期变过**：FY2012/3 叫「機能性ガラス事業」，后改「高機能ガラス事業」；
     JGAAP 段（FY2011/3 及以前）是完全不同的一套（硝子・建材/情報電子/硝子繊維）。
     本脚本按**表头文本**逐年读分部名，不写死。
  3) **ピルキントン買収に係る償却費**：早年单列一行（全数摊在「その他」），
     是收购对价分摊(PPA)的无形资产摊销——把它并进分部利润会看不出主业真实盈利。

用法：python3 _build_segments.py [--write]
"""
import csv
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
PDF_DIR = os.path.join(ROOT, "report", "NSG板硝子")

sys.path.insert(0, HERE)
from _extract import (CELL_RE, NILS, TOKEN_RE, label_key, label_of, norm,  # noqa: E402
                      page_lines, parse_cells, to_num)

# 分部信息分**两张表**印，必须分别锚定：
#   A 表「報告セグメントごとの実績」= 收入 + 分部利润
#   B 表「…個別開示項目前営業利益までの主な項目」= 折旧/摊销/减值/研发费 等按分部拆分
# 早期只按 A 表标题开一个 60 行窗口去抓折旧，会**滑进下一期的 B 表**、把两期数据混在一起
# （実測 FY2012-FY2021 的 減価償却費 全部串成了次年数）。
# ⚠️ B 表的标题被折成两行，「…までの主な項目」落在**第二行**，而年度写在第一行。
#    锚在第二行会取不到年度、整块被丢；必须锚在含年度的那半句
#    「連結損益計算書に計上された個別開示」。
#   ⚠️ B 表标题的措辞**逐年变过**，不能锚死一句：
#      FY2015/3「…における、**上記以外の**連結損益計算書に計上**される**、個別開示項目前営業利益までの…」
#      FY2020/3「…において、連結損益計算書に計上**された**個別開示項目前営業利益までの…」
#      锚 `計上された個別開示` 会漏掉 FY2012–FY2019 全部（实测折旧/摊销/减值/研发四行整段为空，
#      当时误判成「早年未披露」——其实一直都在，是正则没够到）。
#      改锚 `連結損益計算書に計上`：非标题处的同句（如「連結損益計算書に計上された法人所得税」）
#      因取不到「(当|前)連結会計年度…自YYYY年」而 period=None，会被自动丢弃，不会误收。
BLOCK_RE = re.compile(r"報告セグメントごとの実績|連結損益計算書に計上")
# ⚠️ 表头里分部名是**竖排折行**的：一行 '建築用 自動車用 高機能 その他 合計'、
#    下一行 'ガラス事業 ガラス事業 ガラス事業'。拼起来是
#    '建築用自動車用高機能その他合計ガラス事業ガラス事業ガラス事業' ——
#    完整名「建築用ガラス事業」在文本里**根本不连续**，按全名匹配一个都找不到
#    （実測分部数恒为 2 = 只认出 その他/合計）。故只匹配**前缀短名**。
SEG_NAMES = ["建築用", "自動車用", "高機能", "機能性"]
ROWS = [
    # A 表
    ("外部売上高", r"^外部顧客への売上高"),
    ("セグメント間売上高", r"^セグメント間売上高"),
    ("セグメント売上高計", r"^セグメント売上高計"),
    ("PPA償却前セグメント利益", r"^ピルキントン買収に係る償却費控除"),
    ("ピルキントン買収償却費", r"^ピルキントン買収に係る償却費$"),
    ("個別開示項目前営業利益", r"^個別開示項目前営業利益"),
    ("個別開示項目収益", r"^個別開示項目収益"),
    ("個別開示項目費用", r"^個別開示項目費用"),
    # B 表
    ("減価償却費_有形", r"^減価償却費"),
    ("償却費_無形", r"^償却費"),
    ("減損損失", r"^減損損失"),
    ("研究開発費", r"^研究開発費"),
]


def parse_block(lines, i, end):
    """解析 [i, end) 区间内的一个分部表。返回 (期别, 分部名列表, {指标: [值…]})。

    ⚠️ 窗口上界必须卡在**下一个块标题**，不能用固定行数：A 表只有十来行，
    开 60 行窗口会滑进紧随其后的 B 表、把两张表的行混进同一块
    （実測 FY2012-FY2021 的折旧/研发全部串成了相邻期的数）。
    """
    win = lines[i:end]
    # 期别只从**块标题行本身**取（可跨到下一行，标题偶有折行）——
    # 若从整个窗口的拼接文本里搜，会串到相邻块的年度上、把两期数据张冠李戴。
    title = norm(lines[i][1]) + (norm(lines[i + 1][1]) if i + 1 < len(lines) else "")
    m = re.search(r"(当|前)連結会計年度.{0,8}?自(\d{4})年", title)
    period = int(m.group(2)) + 1 if m else None      # 财年末 = 起始年+1（3 月决算）
    head = "".join(norm(ln) for _, ln in win[:12])
    seen, cols = set(), []
    for n in SEG_NAMES:
        if n in head:
            k = "高機能" if n == "機能性" else n
            if k not in seen:
                seen.add(k)
                cols.append(n)
    cols = cols + ["その他", "合計"]
    out, pend = {}, []
    for _, ln in win:
        lb = label_key(label_of(ln))
        cells = parse_cells(ln)
        if not any(c is not None for c in cells):
            if lb:
                pend.append(lb)
                pend[:] = pend[-3:]
            continue
        cands = [lb] + ["".join(pend[-k:]) + lb for k in range(1, len(pend) + 1)]
        for key, pat in ROWS:
            if key in out:
                continue
            if any(re.search(pat, c) for c in cands):
                out[key] = cells
                break
        pend = []
    return period, cols, out


def main():
    write = "--write" in sys.argv
    data, colmap, warns = {}, {}, []
    for fn in sorted(os.listdir(PDF_DIR)):
        if not fn.endswith(".pdf"):
            continue
        fy = int(re.search(r"FY(\d{4})", fn).group(1))
        lines = page_lines(os.path.join(PDF_DIR, fn))
        starts = [i for i, (_, ln) in enumerate(lines) if BLOCK_RE.search(norm(ln))]
        for bi, i in enumerate(starts):
            end = starts[bi + 1] if bi + 1 < len(starts) else min(len(lines), i + 60)
            period, cols, rows = parse_block(lines, i, min(end, i + 60))
            if period is None or not rows:
                continue
            # 只收该报告的**当期**块；前期块用于交叉校验。
            # A/B 两张表分别命中，同一 (期,标签) 下**合并**而非互相覆盖。
            tag = "当期" if period == fy else "前期"
            key = (period, tag)
            slot = data.setdefault(key, {})
            for k, v in rows.items():
                slot.setdefault(k, v)
            colmap.setdefault(period, cols)
    years = sorted({p for p, t in data if t == "当期"})
    if not years:
        print("🔴 未解析到任何分部块")
        return

    # 校验：各分部外部売上高之和 ≈ 合計列
    print("=== 分部勾稽（各分部外部売上高之和 vs 合計列）===")
    bad = 0
    for y in years:
        rows, cols = data[(y, "当期")], colmap[y]
        v = rows.get("外部売上高")
        if not v or len(v) != len(cols):
            print(f"  ⏳ FY{y}/3 外部売上高 列数 {len(v) if v else 0} vs 分部数 {len(cols)}")
            bad += 1
            continue
        s = sum(x for x in v[:-1] if x is not None)
        if abs(s - (v[-1] or 0)) > 2:
            print(f"  🔴 FY{y}/3 分部和 {s:,.0f} vs 合計 {v[-1]:,.0f}")
            bad += 1
    if not bad:
        print(f"  ✅ FY{years[0]}/3–FY{years[-1]}/3 共 {len(years)} 年全部相等")

    # 校验：当期块 vs 次年报告的前期块（同一年两份独立来源）
    print("\n=== 分部跨源互证（该年当期块 vs 次年报告前期块）===")
    diffs = 0
    for y in years:
        a, b = data.get((y, "当期")), data.get((y, "前期"))
        if not a or not b:
            continue
        for k in a:
            if k not in b or len(a[k]) != len(b[k]):
                continue
            for x, z in zip(a[k], b[k]):
                if x is not None and z is not None and abs(x - z) > 2:
                    print(f"  ⚠️ FY{y}/3 {k}: {x:,.0f} vs 次年前期块 {z:,.0f}")
                    diffs += 1
    if not diffs:
        print("  ✅ 0 处差异")

    if not write:
        print("\n（未写·加 --write 落盘）")
        return
    # 输出：行 = 分部×指标，列 = 年
    allcols = []
    for y in years:
        for c in colmap[y]:
            k = c.replace("機能性", "高機能")
            if k not in allcols:
                allcols.append(k)
    out = [["分部", "指标"] + [f"FY{y}/3" for y in years]]
    for seg in allcols:
        for key, _ in ROWS:
            line, got = [seg, key], False
            for y in years:
                rows, cols = data[(y, "当期")], colmap[y]
                norm_cols = [c.replace("機能性", "高機能") for c in cols]
                v = ""
                if key in rows and len(rows[key]) == len(cols) and seg in norm_cols:
                    x = rows[key][norm_cols.index(seg)]
                    if x is not None:
                        v = f"{round(x):d}"
                        got = True
                line.append(v)
            if got:
                out.append(line)
    with open(os.path.join(HERE, "分部营收.csv"), "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(out)
    print(f"\n已写出 分部营收.csv：{len(out) - 1} 行 × {len(years)} 年")


if __name__ == "__main__":
    main()
