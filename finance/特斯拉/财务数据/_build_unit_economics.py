#!/usr/bin/env python3
"""特斯拉储能「单位经济」构建器 —— 判断「量增价减」性质的唯一量化抓手。

要回答的问题
──────────────────────────────────────────────────────────────────
「量增价减」有两种完全不同的性质，报表毛利率看不出来，必须拆到单位口径：
  · **良性顺价传导**：单位成本跌得比单位收入快 → 单位毛利扩大（规模效应，成本红利传导给客户）
  · **不良价格压力**：单位收入跌得比单位成本快 → 单位毛利收缩
本表把「单位收入 / 单位成本 / 单位毛利」三条曲线并排放，并算出两者跌幅之比。

⚠️ 度量污染（务必先读，否则会得出错误结论）
──────────────────────────────────────────────────────────────────
分子 = **能源发电与储存分部**的收入/成本（含光伏发电、Powerwall、Megapack、分部内服务）；
分母 = **仅储能**的装机 GWh（公司只披露一个合计数，不拆 Megapack 与 Powerwall）。
因此本表**不是 Megapack 的 ASP**，只是一个受污染的代理指标：
  · Powerwall 的每 kWh 单价远高于 Megapack → 两者 mix 一变，比值就动；
  · 光伏收入的增减也会推动比值，而与储能定价无关。
→ **只可做同比/环比方向判断，绝不可作绝对定价水平使用，更不可与行业 $/kWh 直接比绝对值。**

数据来源（全部一手）
──────────────────────────────────────────────────────────────────
· 分部收入/成本：年度取 `分部营收.csv`（各年 10-K）；季度/半年取 `中期财务-2026.csv`（10-Q）
· 装机 GWh：`经营指标.csv`（年度）+ 各季产量交付新闻稿（季度，见 QUARTER_GWH 常量，逐条标出处）

校验：季度装机之和 = 年度装机；分部毛利 = 收入 − 成本。不通过不写出。
"""
from __future__ import annotations

import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# 季度储能装机（GWh）—— 来源：各季 8-K EX-99.1 产量交付新闻稿，原件缓存 report/特斯拉/_产量交付新闻稿/
QUARTER_GWH = {
    "2024Q1": 4.053, "2024Q2": 9.4, "2024Q3": 6.9, "2024Q4": 11.0,
    "2025Q1": 10.4, "2025Q2": 9.6, "2025Q3": 12.5, "2025Q4": 14.2,
    "2026Q1": 8.8, "2026Q2": 13.5,
}
HALF_GWH = {
    "2024H1": QUARTER_GWH["2024Q1"] + QUARTER_GWH["2024Q2"],
    "2025H1": QUARTER_GWH["2025Q1"] + QUARTER_GWH["2025Q2"],
    "2026H1": QUARTER_GWH["2026Q1"] + QUARTER_GWH["2026Q2"],
}
ANNUAL_GWH_KEY = "储能装机 Energy storage deployed (GWh)"

# 同比配对（本期 → 去年同期）
YOY = [("FY2024", "FY2023"), ("FY2025", "FY2024"),
       ("2026H1", "2025H1"), ("2026Q1", "2025Q1"), ("2026Q2", "2025Q2")]


def read_csv(name, hdr):
    rows = list(csv.reader(open(os.path.join(HERE, name), encoding="utf-8")))
    cols = rows[hdr][1:]
    return {r[0]: dict(zip(cols, r[1:])) for r in rows[hdr + 1:]}


def num(tbl, key, col):
    s = tbl.get(key, {}).get(col, "")
    return float(s) if s not in ("", None) else None


def main():
    # ⚠️ hdr = 表头行的 0-based 行号。各 CSV 的注释行数不同，改注释行数就要同步改这里
    seg = read_csv("分部营收.csv", 3)        # 3 行注释 + 「科目」行
    met = read_csv("经营指标.csv", 3)        # 3 行注释 + 「指标」行
    itm = read_csv("中期财务-2026.csv", 3)   # 3 行注释 + 「科目」行
    for nm, tbl, probe in (("分部营收.csv", seg, "能源发电与储存 Energy generation and storage"),
                           ("经营指标.csv", met, ANNUAL_GWH_KEY),
                           ("中期财务-2026.csv", itm, "【分部】能源发电与储存-收入")):
        if probe not in tbl:
            print(f"❌ {nm} 表头行号(hdr)不对：找不到探针行「{probe}」——注释行数可能变了")
            return 1

    P = {}   # 期间 → (收入千美元, 成本千美元, 装机GWh)
    errs, nchk = [], 0

    # 年度
    for y in (2023, 2024, 2025):
        rev = num(seg, "能源发电与储存 Energy generation and storage", str(y))
        cost = num(seg, "【成本】能源发电与储存 Energy generation and storage", str(y))
        gwh = num(met, ANNUAL_GWH_KEY, str(y))
        if None in (rev, cost, gwh):
            continue
        P[f"FY{y}"] = (rev, cost, gwh)
        # 校验：四个季度装机之和 = 年度装机
        qs = [QUARTER_GWH.get(f"{y}Q{i}") for i in (1, 2, 3, 4)]
        if all(q is not None for q in qs):
            nchk += 1
            if abs(sum(qs) - gwh) > 0.15:
                errs.append(f"[FY{y}] 四季装机和 {sum(qs):.2f} ≠ 年度装机 {gwh:.2f}")

    # 季度 / 半年（分部数字在 中期财务-2026.csv 的【分部】行）
    for col in ("2026Q1", "2025Q1", "2026Q2", "2025Q2", "2026H1", "2025H1"):
        rev = num(itm, "【分部】能源发电与储存-收入", col)
        cost = num(itm, "【分部】能源发电与储存-成本", col)
        gwh = QUARTER_GWH.get(col) or HALF_GWH.get(col)
        if None in (rev, cost, gwh):
            continue
        P[col] = (rev, cost, gwh)
        nchk += 1
        if rev <= 0 or cost <= 0:
            errs.append(f"[{col}] 分部收入或成本非正，符号口径可能有误")

    # 半年 = 两季之和 的一致性
    for h, (a, b) in (("2026H1", ("2026Q1", "2026Q2")), ("2025H1", ("2025Q1", "2025Q2"))):
        if all(k in P for k in (h, a, b)):
            nchk += 2
            if abs(P[a][0] + P[b][0] - P[h][0]) > 1000:
                errs.append(f"[{h}] 两季收入和 ≠ 半年收入")
            if abs(P[a][2] + P[b][2] - P[h][2]) > 0.05:
                errs.append(f"[{h}] 两季装机和 ≠ 半年装机")

    print(f"── 单位经济校验：{nchk} 条，不通过 {len(errs)}")
    for e in errs:
        print("   ✗", e)
    if errs:
        print("\n❌ 校验未过 —— 不写出 CSV。")
        return 1

    order = ["FY2023", "FY2024", "FY2025", "2025Q1", "2026Q1", "2025Q2", "2026Q2", "2025H1", "2026H1"]
    order = [k for k in order if k in P]

    ROWS = ["储能装机 GWh", "分部收入(千美元)", "分部成本(千美元)", "分部毛利(千美元)",
            "单位收入 收入÷GWh", "单位成本 成本÷GWh", "单位毛利 毛利÷GWh", "分部毛利率"]
    data = {}
    for k in order:
        rev, cost, gwh = P[k]
        data[k] = {"储能装机 GWh": gwh, "分部收入(千美元)": rev, "分部成本(千美元)": cost,
                   "分部毛利(千美元)": rev - cost,
                   "单位收入 收入÷GWh": rev / gwh, "单位成本 成本÷GWh": cost / gwh,
                   "单位毛利 毛利÷GWh": (rev - cost) / gwh, "分部毛利率": (rev - cost) / rev}

    # 同比表
    yoy_rows = []
    for cur, pri in YOY:
        if cur not in P or pri not in P:
            continue
        rc, cc, gc = P[cur]
        rp, cp, gp = P[pri]
        ur, up = rc / gc, rp / gp
        cr, cpu = cc / gc, cp / gp
        gr, gpu = (rc - cc) / gc, (rp - cp) / gp
        drev, dcost = ur / up - 1, cr / cpu - 1
        # 「价跌 ÷ 成本跌」倍数：>1 = 价格跌得更快（不良）；<1 = 成本跌得更快（良性）
        ratio = (drev / dcost) if (dcost < 0 and drev < 0) else None
        yoy_rows.append({
            "对比": f"{pri}→{cur}", "装机量同比": gc / gp - 1,
            "单位收入同比": drev, "单位成本同比": dcost, "单位毛利同比": gr / gpu - 1,
            "价跌÷成本跌(>1=价格跌得更快)": ratio,
            "性质判定": ("良性:成本跌得更快" if (drev < 0 and dcost < 0 and ratio is not None and ratio < 1)
                     else "不良:价格跌得更快" if (drev < 0 and dcost < 0 and ratio is not None and ratio >= 1)
                     else "价升" if drev > 0 else "成本升" if dcost > 0 else "—"),
        })

    def fmt(v, pct=False):
        if v is None:
            return ""
        if pct:
            return f"{v:.2%}"
        return f"{v:.0f}" if abs(v) >= 1000 else f"{v:.2f}"

    with open(os.path.join(HERE, "单位经济-储能.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["单位:装机 GWh;金额千美元;单位收入/成本/毛利 = 千美元÷GWh(即「千美元/GWh」);比率为倍数(1=100%)"])
        w.writerow(["🔴 度量污染必读:分子是**整个能源分部**(含光伏+Powerwall+Megapack+分部内服务),"
                    "分母只有**储能 GWh**(公司不拆 Megapack 与 Powerwall)。"
                    "→ 本表**不是 Megapack ASP**,只可做同比方向判断,**不可与行业 $/kWh 比绝对值**"])
        w.writerow(["来源:分部收入/成本=分部营收.csv(年度,各年10-K) + 中期财务-2026.csv(季度/半年,10-Q);"
                    "装机 GWh=经营指标.csv(年度) + 各季 8-K EX-99.1 产量交付新闻稿(季度)"])
        w.writerow(["【水平表】"])
        w.writerow(["指标"] + order)
        for r in ROWS:
            w.writerow([r] + [fmt(data[k].get(r), pct=(r == "分部毛利率")) for k in order])
        w.writerow([])
        w.writerow(["【同比表】「价跌÷成本跌」>1 = 单位收入跌幅大于单位成本跌幅 = 单位毛利被压缩"])
        hdr = ["对比", "装机量同比", "单位收入同比", "单位成本同比", "单位毛利同比",
               "价跌÷成本跌(>1=价格跌得更快)", "性质判定"]
        w.writerow(hdr)
        for row in yoy_rows:
            w.writerow([row["对比"]] + [fmt(row[h], pct=True) for h in hdr[1:5]]
                       + [fmt(row[hdr[5]])] + [row["性质判定"]])

    print(f"✅ 单位经济-储能.csv 已写出（{len(order)} 个期间 · {len(yoy_rows)} 组同比）")
    for row in yoy_rows:
        print(f"   {row['对比']:<16} 量 {row['装机量同比']:+7.1%} | 单位收入 {row['单位收入同比']:+7.1%} | "
              f"单位成本 {row['单位成本同比']:+7.1%} | 单位毛利 {row['单位毛利同比']:+8.1%} | {row['性质判定']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
