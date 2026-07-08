# -*- coding: utf-8 -*-
"""三环集团 分部营收.csv 勾稽自查:每年 分产品和 ≈ 分地区和 ≈ 分销售和 ≈ 合计营收。
手工维护的分部表无自动构建脚本,用本脚本防手误(如曾出现的 2021 直销 53.83→53.81)。
容差 0.02 亿(各科目四舍五入到亿元,累计舍入)。空格=当年年报未披露该维度,跳过该维度勾稽。"""
import csv
import os
import re

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "分部营收.csv")


def num(cell):
    m = re.match(r"[-+]?\d+\.?\d*", cell.strip())
    return float(m.group()) if m else None


rows = []
with open(path, encoding="utf-8") as f:
    for line in f:
        if line.startswith("#"):
            continue
        rows.append(next(csv.reader([line.rstrip("\n")])))

# 列:0年份 1通信 2电子 3半导体 4压缩机 5其他 6境内 7境外 8直销 9分销 10合计
TOL = 0.02
allok = True
print("年份   分产品和 / 分地区和 / 分销售和  vs 合计")
for r in rows[1:]:
    if not r or not r[0] or r[0].startswith("2025-H1"):
        continue
    y = r[0]
    prod = [num(r[i]) for i in (1, 2, 3, 4, 5) if i < len(r) and num(r[i]) is not None]
    geo = [num(r[i]) for i in (6, 7) if i < len(r) and num(r[i]) is not None]
    chan = [num(r[i]) for i in (8, 9) if i < len(r) and num(r[i]) is not None]
    total = num(r[10]) if len(r) > 10 else None
    sp, sg, sc = sum(prod), sum(geo), sum(chan)
    parts = []
    for label, s, has in (("产品", sp, prod), ("地区", sg, geo), ("销售", sc, chan)):
        if not has:
            parts.append(f"{label}=—")
            continue
        ok = total is not None and abs(s - total) <= TOL
        allok = allok and ok
        parts.append(f"{label}={s:.2f}{'✓' if ok else f'✗(合计{total})'}")
    print(f"{y}: " + " · ".join(parts) + f"  [合计{total}]")

print("\n✅ 全表分维度勾稽自洽" if allok else "\n⚠️ 存在不自洽,请核对")
