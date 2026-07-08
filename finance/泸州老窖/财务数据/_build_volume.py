# -*- coding: utf-8 -*-
"""白酒产销量(2020-2025·吨)→ 产销量.csv。数据源 _extract_json/lzlj_volume.json。
关键:区分"成品酒库存"(合计_库存量·需求信号)与"半成品含基酒库存"(浓香升值资产·扩产常态)。
分档(中高档/其他酒)上年值部分为同比反推(标注)。合计为年报权威直接值。"""
import csv
import json
import os

OUT = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(OUT, "_extract_json", "lzlj_volume.json"), encoding="utf-8") as f:
    D = json.load(f)

YEARS = list(range(2020, 2026))


def g(y, base):
    dd = D[str(y)]
    v = dd.get(base)
    if v is None:
        v = dd.get(base + "_回推")
    return v


def semi(y):
    node = D["期末库存量_成品酒与半成品"].get(str(y))
    return node["半成品酒含基础酒"] if node else None


ROWS = [
    ("合计生产量(吨)", lambda y: g(y, "合计_生产量")),
    ("合计销售量(吨)", lambda y: g(y, "合计_销售量")),
    ("合计库存量-成品酒(吨)", lambda y: g(y, "合计_库存量")),
    ("成品库存/销量(%)", lambda y: round(g(y, "合计_库存量") / g(y, "合计_销售量") * 100, 1)
     if g(y, "合计_销售量") else None),
    ("中高档酒销售量(吨·部分年反推)", lambda y: g(y, "中高档酒_销售量")),
    ("中高档酒库存量(吨·部分年反推)", lambda y: g(y, "中高档酒_库存量")),
    ("其他酒销售量(吨·部分年反推)", lambda y: g(y, "其他酒_销售量")),
    ("其他酒库存量(吨·部分年反推)", lambda y: g(y, "其他酒_库存量")),
    ("半成品(含基酒)库存量(吨)", semi),
]

path = os.path.join(OUT, "产销量.csv")
with open(path, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["科目"] + [str(y) for y in YEARS])
    for name, fn in ROWS:
        w.writerow([name] + ["" if fn(y) is None else fn(y) for y in YEARS])
print(f"✅ 产销量.csv ({len(ROWS)} 行 × {len(YEARS)} 年)")
print(f"   成品库存 2020={g(2020,'合计_库存量'):.0f} → 2025={g(2025,'合计_库存量'):.0f}吨")
print(f"   半成品(基酒) 2021={semi(2021):.0f} → 2025={semi(2025):.0f}吨")
