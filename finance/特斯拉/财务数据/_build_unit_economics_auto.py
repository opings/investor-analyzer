#!/usr/bin/env python3
"""特斯拉汽车「单车经济」构建器 —— 与 `_build_unit_economics.py`（储能）同构。

为什么必须拆到单车口径
──────────────────────────────────────────────────────────────────
汽车板块的报告毛利率被**两块非造车损益**垫着：
  · **监管积分**（近乎零成本，进收入）—— 2025 占汽车板块毛利 16.1%
  · **汽车租赁**（口径不同，收入分期确认）
所以「汽车板块毛利率 17.8%」既不是造车的真实盈利能力，也无法跨年比较。
本表只用**整车销售**（Automotive sales）这一条腿 ÷ 交付量，得到干净的单车 ASP / 成本 / 毛利。

⚠️ 两条口径限制
──────────────────────────────────────────────────────────────────
1. **分子已剔除租赁**：「Automotive sales」不含以经营租赁入账的车（那部分进「Automotive leasing」）。
   而分母用的是**全部交付量**（公司不单独披露非租赁交付台数，只给租赁占比的整数百分比）。
   → 真实单车 ASP 比本表**略高**（租赁占比 1%~5%，见「租赁交付占比」行）。同比方向不受影响。
2. **不含监管积分**。要看含积分的板块口径，用 `分部营收.csv`；要看积分的独立影响，用 `政策补贴与积分.csv`。

数据来源（全部一手）
──────────────────────────────────────────────────────────────────
· 整车销售收入/成本：年度取 `分部营收.csv`（各年 10-K）；季度/半年取 `中期财务-2026.csv`（10-Q）
· 交付量与租赁占比：各季 8-K EX-99.1 产量交付新闻稿（QUARTER_DELIV 常量，逐条出处见 report/特斯拉/_产量交付新闻稿/）

校验：四季交付之和 = 年度交付；两季 = 半年；单车毛利 = 单车收入 − 单车成本。不通过不写出。
"""
from __future__ import annotations

import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# 各季交付量（辆）与「按经营租赁入账」占比 —— 来源：各季 8-K EX-99.1 产量交付新闻稿
QUARTER_DELIV = {
    "2024Q1": (386810, 0.02), "2024Q2": (443956, 0.02), "2024Q3": (462890, 0.03), "2024Q4": (495570, 0.05),
    "2025Q1": (336681, 0.04), "2025Q2": (384122, 0.02), "2025Q3": (497099, 0.02), "2025Q4": (418227, 0.03),
    "2026Q1": (358023, 0.01), "2026Q2": (480126, 0.02),
}
HALF = {"2025H1": ("2025Q1", "2025Q2"), "2026H1": ("2026Q1", "2026Q2")}
ANNUAL_DELIV_KEY = "整车交付量-合计 Total deliveries (辆)"
YOY = [("FY2023", "FY2022"), ("FY2024", "FY2023"), ("FY2025", "FY2024"),
       ("2026H1", "2025H1"), ("2026Q1", "2025Q1"), ("2026Q2", "2025Q2")]


def read_csv(name, hdr):
    rows = list(csv.reader(open(os.path.join(HERE, name), encoding="utf-8")))
    cols = rows[hdr][1:]
    return {r[0]: dict(zip(cols, r[1:])) for r in rows[hdr + 1:]}


def num(tbl, key, col):
    s = tbl.get(key, {}).get(col, "")
    return float(s) if s not in ("", None) else None


def main():
    seg = read_csv("分部营收.csv", 3)
    met = read_csv("经营指标.csv", 3)
    itm = read_csv("中期财务-2026.csv", 3)
    pol = read_csv("政策补贴与积分.csv", 6)
    for nm, tbl, probe in (("分部营收.csv", seg, "汽车销售 Automotive sales"),
                           ("经营指标.csv", met, ANNUAL_DELIV_KEY),
                           ("中期财务-2026.csv", itm, "【分部】汽车销售-收入"),
                           ("政策补贴与积分.csv", pol, "【收入侧】汽车监管积分收入 Automotive regulatory credits (revenue)")):
        if probe not in tbl:
            print(f"❌ {nm} 表头行号(hdr)不对：找不到探针行「{probe}」")
            return 1

    P, errs, nchk = {}, [], 0

    # 年度
    for y in (2020, 2021, 2022, 2023, 2024, 2025):
        rev = num(seg, "汽车销售 Automotive sales", str(y))
        cost = num(seg, "【成本】汽车销售 Automotive sales", str(y))
        dl = num(met, ANNUAL_DELIV_KEY, str(y))
        if None in (rev, cost, dl):
            continue
        lease = [QUARTER_DELIV.get(f"{y}Q{i}") for i in (1, 2, 3, 4)]
        lp = (sum(q[0] * q[1] for q in lease) / sum(q[0] for q in lease)) if all(lease) else None
        P[f"FY{y}"] = (rev, cost, dl, lp)
        if all(lease):
            nchk += 1
            if abs(sum(q[0] for q in lease) - dl) > 1:
                errs.append(f"[FY{y}] 四季交付和 {sum(q[0] for q in lease):,} ≠ 年度交付 {dl:,.0f}")

    # 季度 / 半年
    for col in ("2025Q1", "2026Q1", "2025Q2", "2026Q2", "2025H1", "2026H1"):
        rev = num(itm, "【分部】汽车销售-收入", col)
        cost = num(itm, "【分部】汽车销售-成本", col)
        if col in QUARTER_DELIV:
            dl, lp = QUARTER_DELIV[col]
        else:
            a, b = HALF[col]
            dl = QUARTER_DELIV[a][0] + QUARTER_DELIV[b][0]
            lp = (QUARTER_DELIV[a][0] * QUARTER_DELIV[a][1] + QUARTER_DELIV[b][0] * QUARTER_DELIV[b][1]) / dl
        if None in (rev, cost):
            continue
        P[col] = (rev, cost, dl, lp)

    for h, (a, b) in HALF.items():
        if all(k in P for k in (h, a, b)):
            nchk += 2
            if abs(P[a][0] + P[b][0] - P[h][0]) > 1000:
                errs.append(f"[{h}] 两季整车销售收入和 ≠ 半年")
            if abs(P[a][2] + P[b][2] - P[h][2]) > 1:
                errs.append(f"[{h}] 两季交付和 ≠ 半年交付")

    print(f"── 单车经济校验：{nchk} 条，不通过 {len(errs)}")
    for e in errs:
        print("   ✗", e)
    if errs:
        print("\n❌ 校验未过 —— 不写出 CSV。")
        return 1

    order = [k for k in ["FY2020", "FY2021", "FY2022", "FY2023", "FY2024", "FY2025",
                         "2025Q1", "2026Q1", "2025Q2", "2026Q2", "2025H1", "2026H1"] if k in P]

    # 监管积分对「汽车板块」毛利的贡献（年度/半年）—— 供对照
    def credits_share(k):
        y = k[2:] if k.startswith("FY") else None
        rc = num(pol, "【收入侧】汽车监管积分收入 Automotive regulatory credits (revenue)", y) if y else \
            num(itm, "【分部】汽车监管积分-收入", k)
        arev = num(seg, "汽车板块合计 Total automotive revenues", y) if y else num(itm, "【分部】汽车板块-收入", k)
        acost = num(seg, "【成本】汽车板块合计 Total automotive", y) if y else num(itm, "【分部】汽车板块-成本", k)
        if None in (rc, arev, acost) or arev == acost:
            return None, None, None
        agp = arev - acost
        # 监管积分近乎零成本 → 剔除后的板块毛利率
        return rc / agp, agp / arev, (agp - rc) / (arev - rc)

    ROWS = ["交付量(辆)", "其中:按经营租赁入账占比", "整车销售收入(千美元)", "整车销售成本(千美元)",
            "整车销售毛利(千美元)", "单车 ASP(美元)", "单车成本(美元)", "单车毛利(美元)", "整车销售毛利率",
            "—— 对照:含监管积分的板块口径 ——",
            "汽车板块毛利率(报告口径)", "监管积分÷汽车板块毛利", "汽车板块毛利率(剔除监管积分)"]
    data = {}
    for k in order:
        rev, cost, dl, lp = P[k]
        sh, gm, gm_ex = credits_share(k)
        data[k] = {"交付量(辆)": dl, "其中:按经营租赁入账占比": lp,
                   "整车销售收入(千美元)": rev, "整车销售成本(千美元)": cost, "整车销售毛利(千美元)": rev - cost,
                   "单车 ASP(美元)": rev * 1000 / dl, "单车成本(美元)": cost * 1000 / dl,
                   "单车毛利(美元)": (rev - cost) * 1000 / dl, "整车销售毛利率": (rev - cost) / rev,
                   "汽车板块毛利率(报告口径)": gm, "监管积分÷汽车板块毛利": sh,
                   "汽车板块毛利率(剔除监管积分)": gm_ex}

    yoy_rows = []
    for cur, pri in YOY:
        if cur not in P or pri not in P:
            continue
        rc, cc, gc, _ = P[cur]
        rp, cp, gp, _ = P[pri]
        a_cur, a_pri = rc * 1000 / gc, rp * 1000 / gp
        c_cur, c_pri = cc * 1000 / gc, cp * 1000 / gp
        g_cur, g_pri = (rc - cc) * 1000 / gc, (rp - cp) * 1000 / gp
        yoy_rows.append({"对比": f"{pri}→{cur}", "交付量同比": gc / gp - 1,
                         "单车 ASP 同比": a_cur / a_pri - 1, "单车成本同比": c_cur / c_pri - 1,
                         "单车毛利同比": g_cur / g_pri - 1,
                         "判定": ("量价齐升" if gc > gp and a_cur > a_pri else
                                "以价换量" if gc > gp and a_cur < a_pri else
                                "量价双缩" if gc < gp and a_cur < a_pri else "量缩价升")})

    def fmt(v, pct=False):
        if v is None:
            return ""
        return f"{v:.2%}" if pct else (f"{v:.0f}" if abs(v) >= 1000 else f"{v:.4f}")

    PCT = {"其中:按经营租赁入账占比", "整车销售毛利率", "汽车板块毛利率(报告口径)",
           "监管积分÷汽车板块毛利", "汽车板块毛利率(剔除监管积分)"}
    with open(os.path.join(HERE, "单位经济-汽车.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["单位:交付量辆;金额千美元;单车指标美元/辆;比率为倍数(1=100%)"])
        w.writerow(["🔴 为什么要拆:汽车板块报告毛利率被**监管积分**(近乎零成本)与**汽车租赁**(口径不同)垫着，"
                    "既非造车真实盈利能力、也不可跨年比。本表只用「整车销售」一条腿 ÷ 交付量"])
        w.writerow(["⚠️ 分子已剔除租赁车(它们进 Automotive leasing)，分母用全部交付量(公司不披露非租赁交付台数)"
                    "→ 真实单车 ASP 比本表**略高**，幅度见「按经营租赁入账占比」行；同比方向不受影响"])
        w.writerow(["来源:整车销售收入/成本=分部营收.csv(年度) + 中期财务-2026.csv(季度/半年);"
                    "交付量与租赁占比=各季 8-K EX-99.1 产量交付新闻稿"])
        w.writerow(["【水平表】"])
        w.writerow(["指标"] + order)
        for r in ROWS:
            if r.startswith("——"):
                w.writerow([r])
                continue
            vals = [data[k].get(r) for k in order]
            if any(v is not None for v in vals):
                w.writerow([r] + [fmt(v, pct=(r in PCT)) for v in vals])
        w.writerow([])
        w.writerow(["【同比表】"])
        hdr = ["对比", "交付量同比", "单车 ASP 同比", "单车成本同比", "单车毛利同比", "判定"]
        w.writerow(hdr)
        for row in yoy_rows:
            w.writerow([row["对比"]] + [fmt(row[h], pct=True) for h in hdr[1:5]] + [row["判定"]])

    print(f"✅ 单位经济-汽车.csv 已写出（{len(order)} 个期间 · {len(yoy_rows)} 组同比）")
    for row in yoy_rows:
        print(f"   {row['对比']:<16} 交付 {row['交付量同比']:+7.1%} | ASP {row['单车 ASP 同比']:+7.1%} | "
              f"单车成本 {row['单车成本同比']:+7.1%} | 单车毛利 {row['单车毛利同比']:+8.1%} | {row['判定']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
