# -*- coding: utf-8 -*-
"""泡泡玛特(09992.HK) 递延所得税资产构成 → 写 递延所得税资产构成.csv。

为什么单列: 2025 年递延所得税资产由 1.47 亿跳到 17.54 亿(`资产负债表.csv`), 2026-07 版分析挂了「追附注 ⏳」。
数据来源: report/泡泡玛特/泡泡玛特-2025.pdf 附注 19 遞延所得稅(P316), 2025 与 2024 两列。
勾稽: 各项加总 = 递延所得税资产总值; 总值 + 抵销递延所得税负债 = 净额; 净额 = 年度资产负债表「递延所得税资产」
(从年度构建脚本内存表取, 不读 CSV)。容差 0。
"""
import csv
import importlib.util
import os

OUT = os.path.dirname(os.path.abspath(__file__))
YEARS = [2024, 2025]
构成 = [
    ("租赁负债", [241140, 729438]),
    ("税项亏损", [40163, 14842]),
    ("减值亏损", [11292, 18524]),
    ("集团间销售未变现溢利", [86201, 1602765]),
    ("应计开支及其他", [16017, 103258]),
    ("递延所得税资产总值", [394813, 2468827]),
    ("抵销递延所得税负债", [-247784, -715276]),
    ("递延所得税资产净额", [147029, 1753551]),
]


def main():
    spec = importlib.util.spec_from_file_location("popmart_annual_build", os.path.join(OUT, "_build_from_pdf.py"))
    annual = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(annual)
    bs_rows = [vals for k, vals in annual.资产负债表 if k.startswith("递延所得税资产 ")]
    if len(bs_rows) != 1:
        raise KeyError("年度资产负债表找不到唯一的「递延所得税资产」行")

    d = dict(构成)
    errors, executed = [], 0
    for i, y in enumerate(YEARS):
        checks = [
            ("各项加总 = 总值", sum(vals[i] for _, vals in 构成[:5]), d["递延所得税资产总值"][i]),
            ("总值 + 抵销 = 净额", d["递延所得税资产总值"][i] + d["抵销递延所得税负债"][i], d["递延所得税资产净额"][i]),
            ("净额 = 年度资产负债表", d["递延所得税资产净额"][i], bs_rows[0][annual.YEARS.index(y)]),
        ]
        for label, a, b in checks:
            executed += 1
            if a != b:
                errors.append(f"[{y}] {label}: {a} vs {b}")
    if errors:
        print("❌ 递延所得税资产勾稽失败, 不写出 CSV:")
        for e in errors:
            print(f"  {e}")
        return

    path = os.path.join(OUT, "递延所得税资产构成.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["# 泡泡玛特 递延所得税资产构成 · 单位: 人民币千元 · 来源: 2025 年报附注 19(P316) · 构建: _build_dta.py"])
        w.writerow(["科目"] + [str(y) for y in YEARS] + ["2025 占总值%"])
        for k, vals in 构成:
            share = round(vals[1] / d["递延所得税资产总值"][1] * 100, 1) if k not in ("抵销递延所得税负债", "递延所得税资产净额") else ""
            w.writerow([k] + vals + [share])
    print(f"✅ 递延所得税资产勾稽全部通过: 执行 {executed} 条 (容差 0); 已写出 递延所得税资产构成.csv")


if __name__ == "__main__":
    main()
