#!/usr/bin/env python3
"""NSG 应收明细生成器 —— 从 有報 附注「売上債権及びその他の債権」解析，产出 `应收明细.csv`

**为什么单建一张表**：NSG 的 IFRS 连结资产负债表把应收合并成一行
「売上債権及びその他の債権」，颗粒度不够做「应收增速 vs 营收增速」这条排雷比对。
但**附注里是拆开的**——外部顾客应收 / 坏账准备 / 其他债权 / 预付款及未收收益 各自成行。
（建库首轮曾把这条标成「⏳待补·颗粒度不足」，其实只是没往附注里翻。）

用法：python3 _build_receivables.py [--write]
"""
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
PDF_DIR = os.path.join(ROOT, "report", "NSG板硝子")

sys.path.insert(0, HERE)
from _extract import label_key, label_of, norm, page_lines, parse_cells  # noqa: E402

# 附注标题行形如「21. 売上債権及びその他の債権」——注記号逐年变，故不写死号码。
HEAD = re.compile(r"^\d{1,2}\.?売上債権及びその他の債権$")
ROWS = [
    ("外部顧客売上債権", r"^外部顧客に対する売上債権$"),
    ("貸倒引当金", r"^貸倒引当金$"),
    ("貸倒引当金控除後売上債権", r"^貸倒引当金控除後"),
    ("工事未収入金", r"^工事未収入金$"),
    ("関連当事者売上債権", r"^関連当事者に対する売上債権$"),
    ("関連当事者貸付金", r"^関連当事者に対する貸付金$"),
    ("その他の債権", r"^その他の債権$"),
    ("前払金及び未収収益", r"^前払金及び未収収益$"),
    ("流動", r"^流動$"),
    ("非流動", r"^非流動$"),
]


def main():
    write = "--write" in sys.argv
    data = {}
    for fn in sorted(os.listdir(PDF_DIR)):
        if not fn.endswith(".pdf"):
            continue
        fy = int(re.search(r"FY(\d{4})", fn).group(1))
        lines = page_lines(os.path.join(PDF_DIR, fn))
        start = next((i for i, (_, ln) in enumerate(lines) if HEAD.match(norm(ln))), None)
        if start is None:
            continue
        got = {}
        for _, ln in lines[start:start + 40]:
            lb = label_key(label_of(ln))
            cells = [c for c in parse_cells(ln) if c is not None]
            if not cells:
                continue
            for key, pat in ROWS:
                if key not in got and re.search(pat, lb):
                    got[key] = cells[0]      # 列序 cur_first：当期末在左
                    break
        if got:
            data[fy] = got

    years = sorted(data)
    if not years:
        print("🔴 未解析到附注")
        return
    print(f"=== 应收明细：FY{years[0]}/3–FY{years[-1]}/3 共 {len(years)} 年 ===")

    # 校验：外部顾客应收 + 坏账准备 = 扣除后；各项合计 = 流動 + 非流動
    bad = 0
    for y in years:
        g = data[y]
        a, b, c = g.get("外部顧客売上債権"), g.get("貸倒引当金"), g.get("貸倒引当金控除後売上債権")
        if None not in (a, b, c) and abs(a + b - c) > 2:
            print(f"  🔴 FY{y}/3 外部応収+坏账准备≠扣除后：{a:,.0f}{b:+,.0f} vs {c:,.0f}")
            bad += 1
        parts = [g.get(k) for k in ("貸倒引当金控除後売上債権", "工事未収入金",
                                    "関連当事者売上債権", "関連当事者貸付金",
                                    "その他の債権", "前払金及び未収収益")]
        tot = [g.get(k) for k in ("流動", "非流動")]
        if all(v is not None for v in parts) and all(v is not None for v in tot):
            if abs(sum(parts) - sum(tot)) > 2:
                print(f"  🔴 FY{y}/3 明细和 {sum(parts):,.0f} vs 流動+非流動 {sum(tot):,.0f}")
                bad += 1
    if not bad:
        print("  ✅ 表内勾稽全部通过（外部応収+坏账=扣除后；明细和=流動+非流動）")

    if not write:
        print("（未写·加 --write 落盘）")
        return
    out = [["科目"] + [f"FY{y}/3" for y in years]]
    for key, _ in ROWS:
        line = [key]
        got = False
        for y in years:
            v = data[y].get(key)
            got = got or v is not None
            line.append("" if v is None else f"{round(v):d}")
        if got:
            out.append(line)
    with open(os.path.join(HERE, "应收明细.csv"), "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(out)
    print(f"已写出 应收明细.csv：{len(out) - 1} 行 × {len(years)} 年")


if __name__ == "__main__":
    main()
