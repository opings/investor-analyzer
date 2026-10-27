# -*- coding: utf-8 -*-
"""泡泡玛特(09992.HK) 股东回报两口径 → 写 股东回报.csv。

为什么单列: `财务比率.csv` 的「分红率%(归母)」是年内已付口径(现金流量表), 与按财政年度的宣派口径
有跨年时间差, 爆发年两者可差数倍(见 财报阅读规则.md 期间/时点口径约定·时点性轴)。本表把两个口径分开放:
  ① 宣派口径(按财政年度): 每股末期股息 + 宣派总额 ← 各财年年报董事会报告/股息附注, 均为
     「按财务报表批准日已发行股本计算」的总额, 派息记录日前股本变动会令实付额不同
  ② 已付口径(按现金流期间): 已付股息 / 回购自身股份 / 上市所得款项 ← 年度与 H1 构建脚本内存表(不读 CSV)

宣派数据来源(各财年当年年报):
  FY2020 report/泡泡玛特/泡泡玛特-2020.pdf 附注 10: 每股 14.94 分, 合共 209,402 千元(自股份溢价派付)
  FY2021 report/泡泡玛特/泡泡玛特-2021.pdf: 每股 15.24 分, 合共 213,655 千元
  FY2022 report/泡泡玛特/泡泡玛特-2022.pdf: 每股 8.70 分, 合共 118,980 千元
  FY2023 report/泡泡玛特/泡泡玛特-2023.pdf: 每股 28.21 分, 合共 378,840 千元
  FY2024 report/泡泡玛特/泡泡玛特-2024.pdf: 每股 81.46 分, 合共 1,093,916 千元
  FY2025 report/泡泡玛特/泡泡玛特-2025.pdf 附注 12: 每股 2.3817 元, 合共 3,193,962 千元
  上市至今各年均未宣派中期股息(2025、2026 中报明示不派; 更早年度年报未见中期股息)
实付核对: 2026 中报附注 11 —— 2026H1 派付 3,149,378 千元(每股 2.3817 元), 已扣除股份奖励计划持股应占 23,318 千元。
"""
import csv
import importlib.util
import os

OUT = os.path.dirname(os.path.abspath(__file__))

宣派 = [
    # (财年, 每股末期股息 人民币分, 宣派总额 千元, 出处)
    (2020, 14.94, 209402, "2020 年报附注 10"),
    (2021, 15.24, 213655, "2021 年报股息附注"),
    (2022, 8.70, 118980, "2022 年报股息附注"),
    (2023, 28.21, 378840, "2023 年报股息附注"),
    (2024, 81.46, 1093916, "2024 年报股息附注"),
    (2025, 238.17, 3193962, "2025 年报附注 12"),
]
合理性带宽 = 0.05  # 次期实付 vs 本财年宣派: 股本变动导致的差异, 超过 ±5% 视为转录错


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(OUT, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def row(table, key):
    hits = [vals for k, vals in table if k == key]
    if len(hits) != 1:
        raise KeyError(f"找不到唯一科目: {key}")
    return hits[0]


def main():
    annual = load("popmart_annual_build", "_build_from_pdf.py")
    h1 = load("popmart_h1_build", "_build_h1_from_pdf.py")
    years = annual.YEARS
    div_paid = row(annual.现金流量表, "已付股息 Dividends paid")
    buyback = row(annual.现金流量表, "回购自身股份 Purchase of own shares")
    ipo = row(annual.现金流量表, "上市所得款项(净) IPO net proceeds")
    parent = row(annual.利润表, "归母溢利 Attributable to parent")
    i26 = h1.H1_PERIODS.index("2026H1")
    div_26h1 = row(h1.现金流量表_H1, "已付股息")[i26]
    bb_26h1 = row(h1.现金流量表_H1, "股份回购付款")[i26]

    # 现金口径序列: 2019-2025 年度 + 2026H1
    periods = [str(y) for y in years if y >= 2019] + ["2026H1"]
    paid = [div_paid[years.index(y)] for y in years if y >= 2019] + [div_26h1]
    bb = [buyback[years.index(y)] or 0 for y in years if y >= 2019] + [bb_26h1]
    ipo_vals = [ipo[years.index(y)] or 0 for y in years if y >= 2019] + [0]
    for label, vals in (("已付股息", paid), ("回购", bb)):
        if any(v is None for v in vals):
            raise ValueError(f"{label} 序列有空值: {vals}")

    # 合理性检查: 次期实付 ≈ 本财年宣派
    errors = []
    next_paid = {fy: paid[periods.index(str(fy + 1))] if str(fy + 1) in periods else div_26h1 for fy, *_ in 宣派}
    checks = []
    for fy, _, total, _ in 宣派:
        actual = -next_paid[fy]
        diff = actual / total - 1
        checks.append((fy, total, actual, diff))
        if abs(diff) > 合理性带宽:
            errors.append(f"FY{fy} 宣派 {total} vs 次期实付 {actual}: 偏离 {diff:+.1%} 超出 ±{合理性带宽:.0%}")
    if errors:
        print("❌ 股东回报合理性检查失败, 不写出 CSV:")
        for e in errors:
            print(f"  {e}")
        return

    path = os.path.join(OUT, "股东回报.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["# 泡泡玛特 股东回报两口径 · 单位: 人民币千元(每股为人民币分) · 宣派来源各财年年报, 已付来源年度/H1 现金流量表 · 构建: _build_shareholder_returns.py"])
        w.writerow(["=== ① 宣派口径(按财政年度) ==="])
        w.writerow(["财年", "每股末期股息(人民币分)", "宣派总额(按年报批准日股本)", "归母溢利", "宣派派息率%", "次期实付(现金流·已扣奖励计划持股应占)", "实付÷宣派-1 %", "出处"])
        for (fy, per_share, total, src), (_, _, actual, diff) in zip(宣派, checks):
            w.writerow([fy, per_share, total, parent[years.index(fy)], round(total / parent[years.index(fy)] * 100, 1),
                        actual, round(diff * 100, 1), src])
        w.writerow(["=== ② 已付口径(按现金流期间·负数=流出) ==="])
        w.writerow(["期间", "已付股息", "回购自身股份", "上市所得款项(净)", "股息+回购合计", "2021 年起累计股息+回购"])
        cum = 0
        for p, d, b, i in zip(periods, paid, bb, ipo_vals):
            total = d + b
            if p >= "2021":
                cum += total
            w.writerow([p, d, b, i, total, cum if p >= "2021" else ""])
    print("✅ 股东回报合理性检查通过(次期实付与宣派偏离均在 ±5% 内):")
    for fy, total, actual, diff in checks:
        print(f"  FY{fy}: 宣派 {total} / 实付 {actual} / {diff:+.1%}")
    print(f"已写出 股东回报.csv → {OUT}")


if __name__ == "__main__":
    main()
