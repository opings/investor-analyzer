# -*- coding: utf-8 -*-
"""山西汾酒 产销量.csv + 经销商.csv 生成器（从 _extract_json/fenjiu_volume_*.json）。

来源 = 各年年报「经营情况讨论与分析」产销量分析表 / 经销商表 / 前五名客户。
单位：产销量 = 千升（年报原口径）；经销商 = 户。
2019/2020 合并范围变化（收购集团酒类资产）产销量口径以各年年报原注为准。
"""
import csv
import json
import os

YEARS = list(range(2016, 2026))
OUT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(OUT, "_extract_json")


def load(name):
    p = os.path.join(SRC, name)
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


DATA = {}
DATA.update(load("fenjiu_volume_2016_2020.json"))
DATA.update(load("fenjiu_volume_2021_2025.json"))


def vol(year, field):
    d = DATA.get(str(year)) or {}
    pv = d.get("产销量")
    if not pv:
        return None
    # 单产品(酒类合并)或多产品——多产品时加总
    tot = 0.0
    has = False
    for prod, m in pv.items():
        if not isinstance(m, dict):
            continue
        v = m.get(field)
        if v is not None:
            tot += v
            has = True
    return round(tot, 2) if has else None


def dealer(year, *keys):
    d = (DATA.get(str(year)) or {}).get("经销商") or {}
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return None


def top5(year, key):
    d = (DATA.get(str(year)) or {}).get("前五名客户") or {}
    return d.get(key)


def main():
    rows_v = [
        ("生产量(千升)", [vol(y, "生产量") for y in YEARS]),
        ("销售量(千升)", [vol(y, "销售量") for y in YEARS]),
        ("库存量(千升·成品)", [vol(y, "库存量") for y in YEARS]),
    ]
    # 派生：产销率 = 销售/生产
    ratio = []
    for p, s in zip(rows_v[0][1], rows_v[1][1]):
        ratio.append(round(s / p * 100, 1) if (p and s is not None) else None)
    rows_v.append(("产销率(%·派生)", ratio))

    with open(os.path.join(OUT, "产销量.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["科目"] + [str(y) for y in YEARS])
        for k, vs in rows_v:
            if all(v is None for v in vs):
                continue
            w.writerow([k] + ["" if v is None else v for v in vs])
    print("✅ 产销量.csv")

    rows_d = [
        ("省内期末(户)", [dealer(y, "省内期末") for y in YEARS]),
        ("省外期末(户)", [dealer(y, "省外期末") for y in YEARS]),
        ("省内汾酒(户)", [dealer(y, "省内汾酒") for y in YEARS]),
        ("省外汾酒(户)", [dealer(y, "省外汾酒") for y in YEARS]),
        ("省内其他酒类(户)", [dealer(y, "省内其他") for y in YEARS]),
        ("省外其他酒类(户)", [dealer(y, "省外其他") for y in YEARS]),
        ("合计期末(户)", [dealer(y, "合计期末") for y in YEARS]),
        ("报告期增加(户)", [dealer(y, "增加") for y in YEARS]),
        ("报告期减少(户)", [dealer(y, "减少") for y in YEARS]),
        ("前五名客户占比(%)", [top5(y, "占比%") for y in YEARS]),
        ("前五名客户中关联方占比(%)", [top5(y, "关联方占比%") for y in YEARS]),
    ]
    # 合计派生（若原表未印合计）
    tot = []
    for i, y in enumerate(YEARS):
        c = rows_d[6][1][i]
        if c is None:
            parts = [r[1][i] for r in (rows_d[0], rows_d[1])]
            if all(p is not None for p in parts):
                c = sum(parts)
            else:
                parts4 = [r[1][i] for r in (rows_d[2], rows_d[3], rows_d[4], rows_d[5])]
                c = sum(parts4) if all(p is not None for p in parts4) else None
        tot.append(c)
    rows_d[6] = ("合计期末(户·原印或派生)", tot)

    with open(os.path.join(OUT, "经销商.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["科目"] + [str(y) for y in YEARS])
        for k, vs in rows_d:
            if all(v is None for v in vs):
                continue
            w.writerow([k] + ["" if v is None else v for v in vs])
    print("✅ 经销商.csv")


if __name__ == "__main__":
    main()
