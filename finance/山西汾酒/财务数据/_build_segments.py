# -*- coding: utf-8 -*-
"""山西汾酒 分部营收.csv 生成器（从 _extract_json/ 奇数年年报 MD&A 分部表）。

口径说明（写入 README）：
  - 按地区（省内/省外）：全 20 年口径稳定 → 省外占比 = 全国化主线指标；
    奇数年取该年年报本年值；偶数年若相邻奇数年年报分部表印有上年绝对值则回填（2020/2024 有），
    其余偶数年年报仅印同比%，按「分部必须当年一手绝对值」纪律不反推、留空。
  - 按产品：口径历经多代变化（白酒/配制酒 → 中高价/低价白酒 → 汾酒/系列酒/配制酒 →
    中高价酒类/其他酒类 → 汾酒/其他酒类），跨代不可拼接，稀疏矩阵如实呈现。
  - 按渠道：2020 起可得（2021/2023/2025 年报两列）。
  - 单位 = 人民币元。渠道/部分地区数源自年报万元表 ×10000（精度止于万元，见各年 JSON _说明）。
"""
import csv
import json
import os

YEARS = list(range(2006, 2026))
OUT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(OUT, "_extract_json")

ROWS = [
    ("按地区|省内", "按地区", ["省内"]),
    ("按地区|省外", "按地区", ["省外"]),
    ("按产品|白酒(口径I·07-13)", "按产品", ["白酒"]),
    ("按产品|配制酒", "按产品", ["配制酒"]),
    ("按产品|其他(产品档)", "按产品", ["其他"]),
    ("按产品|中高价白酒(口径II·14-17)", "按产品", ["中高价白酒"]),
    ("按产品|低价白酒(口径II·14-17)", "按产品", ["低价白酒"]),
    ("按产品|汾酒(口径III/V·19-21,24-25)", "按产品", ["汾酒"]),
    ("按产品|系列酒(口径III·19-21)", "按产品", ["系列酒"]),
    ("按产品|中高价酒类(口径IV·22-23)", "按产品", ["中高价酒类"]),
    ("按产品|其他酒类(口径IV/V·22-25)", "按产品", ["其他酒类"]),
    ("按产品|主营小计", "按产品", ["小计", "合计"]),
    ("按渠道|直销(含团购)", "按渠道", ["直销（含团购）", "直销(含团购)"]),
    ("按渠道|电商", "按渠道", ["电商"]),
    ("按渠道|直销团购电商(合并口径24-25)", "按渠道", ["直销、团购、电商"]),
    ("按渠道|批发代理", "按渠道", ["批发代理"]),
]


def load(y):
    p = os.path.join(SRC, f"fenjiu_extract_{y}.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


JS = {y: load(y) for y in YEARS}


def seg_value(year, dim, names, period):
    j = JS.get(year)
    if not j:
        return None
    seg = (j.get("分部营收") or {}).get(dim) or {}
    for name in names:
        for k, v in seg.items():
            if k.replace(" ", "") == name.replace(" ", "") and isinstance(v, dict):
                return v.get(period)
    return None


def cell(year, dim, names):
    if year % 2 == 1:  # 奇数年：该年年报本年值
        return seg_value(year, dim, names, "本年")
    # 偶数年：次年(奇数)年报分部表的上年绝对值（仅部分年份印了）
    return seg_value(year + 1, dim, names, "上年")


def main():
    table = []
    for label, dim, names in ROWS:
        vals = [cell(y, dim, names) for y in YEARS]
        if all(v is None for v in vals):
            continue
        table.append((label, vals))
    # 派生：省外占比 =省外/(省内+省外)
    sn = dict(table).get("按地区|省内")
    sw = dict(table).get("按地区|省外")
    if sn and sw:
        ratio = [round(w / (n + w) * 100, 2) if (n is not None and w is not None and (n + w)) else None
                 for n, w in zip(sn, sw)]
        idx = [i for i, (l, _) in enumerate(table) if l == "按地区|省外"][0]
        table.insert(idx + 1, ("按地区|省外占比(%·派生·全国化指标)", ratio))

    path = os.path.join(OUT, "分部营收.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["维度|科目"] + [str(y) for y in YEARS])
        for label, vals in table:
            w.writerow([label] + ["" if v is None else v for v in vals])
    print(f"✅ 分部营收.csv ({len(table)} 行 × {len(YEARS)} 年)")
    # 勾稽：奇数年 省内+省外 vs 产品档合计（若同年两档都有）
    for y in range(2007, 2026, 2):
        n = cell(y, "按地区", ["省内"])
        w_ = cell(y, "按地区", ["省外"])
        prods = [cell(y, "按产品", [nm]) for nm in
                 ["白酒", "配制酒", "其他", "中高价白酒", "低价白酒", "汾酒", "系列酒", "中高价酒类", "其他酒类"]]
        psum = sum(p for p in prods if p is not None)
        if n is not None and w_ is not None and psum:
            diff = abs((n + w_) - psum)
            flag = "✅" if diff < max(200000, psum * 0.001) else f"⚠️ 差 {diff:,.0f}"
            print(f"  {y}: 地区和 {(n+w_)/1e8:.2f}亿 vs 产品和 {psum/1e8:.2f}亿 {flag}")


if __name__ == "__main__":
    main()
