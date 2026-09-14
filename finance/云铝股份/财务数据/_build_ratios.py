#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云铝股份 财务比率构建器 → 财务比率.csv

背景（2026-09-14 全库附注审计）：本库此前只有三表 + 分部营收，**缺核心的 财务比率.csv**。
做法：**复用 `scripts/derived.py` 的通用底**（不重复造轮子——它已内置跨准则科目别名层），
      再叠加**周期股定制层**（铝价驱动的生意，通用比率不足以刻画）。

定制层为什么是这几项（对照 `_模板/财报关注要点-行业模板.md` 的「周期/资源」块）：
  · 单位成本与吨毛利 —— 周期底部能否不亏，决定能否扛过周期（本表 ⏳：产销量需从年报经营数据取）
  · 净现金/净负债 —— 周期股的生存线
  · 自由现金流 —— 顺周期扩产是见顶信号，要看钱花在哪
  · 固定资产周转 —— 重资产的产能利用率代理指标
"""
import csv
import os
import sys

ROOT = "/Users/zhaoyongzhen/workspace/ai-tool/investor-analyzer"
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from derived import load_table, compute_common_ratios, pick  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "财务比率.csv")


def main():
    tabs = {}
    for fn in ("利润表.csv", "资产负债表.csv", "现金流量表.csv"):
        p = os.path.join(HERE, fn)
        if not os.path.exists(p):
            print(f"❌ 缺 {fn}")
            return 1
        tabs[fn] = load_table(p)
    years = tabs["利润表.csv"][0]
    PL, BS, CF = tabs["利润表.csv"][1], tabs["资产负债表.csv"][1], tabs["现金流量表.csv"][1]
    R, unmatched = compute_common_ratios(PL, BS, CF)

    if unmatched:
        print(f"❌ 有未匹配科目，比率会失真，拒绝写出：{'、'.join(sorted(set(unmatched)))}")
        return 1

    nchk, errs = 0, []

    # ── 定制层：周期股 ────────────────────────────────────────────
    def g(tab, key):
        row = pick(tab, key, [])          # pick(rows, key, unmatched) —— key 是别名表的键
        return row if row else [None] * len(years)

    ocf = g(CF, "OCF")
    capex = g(CF, "capex")
    ta = g(BS, "资产总计")
    ppe = g(BS, "PPE")
    rev = g(PL, "营收")

    fcf, ppe_turn = [], []
    for i in range(len(years)):
        o, c = ocf[i], capex[i]
        fcf.append(None if (o is None or c is None) else o - abs(c))
        r, p = rev[i], ppe[i]
        ppe_turn.append(None if (not r or not p) else r / p)

    # 校验：FCF 有值年份 = OCF 与 capex 同时有值的年份
    nchk += 1
    both = sum(1 for i in range(len(years)) if ocf[i] is not None and capex[i] is not None)
    if sum(1 for v in fcf if v is not None) != both:
        errs.append("自由现金流缺值数与上游不一致")
    # 校验：固定资产周转应为正
    nchk += 1
    if any(v is not None and v <= 0 for v in ppe_turn):
        errs.append("固定资产周转出现非正值")
    # 校验：年份序列单调递增
    nchk += 1
    if any(b <= a for a, b in zip(years, years[1:])):
        errs.append("年份列非严格递增")

    if errs:
        print(f"❌ 校验不通过 {len(errs)}：")
        for e in errs:
            print("   ✗", e)
        return 1

    def fmt(v, kind):
        if v is None:
            return ""
        if kind == "pct":
            return f"{v * 100:.2f}%"
        if kind == "day":
            return f"{v:.1f}"
        return f"{v:.4f}"

    rows = [
        ["单位:比率为百分数或倍数;金额沿用三表口径(千元人民币)。空=上游科目该年未披露"],
        ["来源:**通用底**由 `scripts/derived.py` 计算(跨准则科目别名层);**定制层**为周期/资源行业特有项"],
        ["⚠️ 本表 2026-09-14 补建 —— 此前本库只有三表+分部，无比率表"],
        ["科目"] + [str(y) for y in years],
    ]
    rows.append(["—— 通用底（derived.py） ——"] + [""] * len(years))
    for name, vals, kind in R:
        rows.append([name] + [fmt(v, kind) for v in vals])

    rows.append(["—— 定制层：周期/资源 ——"] + [""] * len(years))
    rows.append(["自由现金流 FCF = OCF − |capex|"] +
                ["" if v is None else f"{v:.0f}" for v in fcf])
    rows.append(["固定资产周转 营收÷固定资产"] +
                ["" if v is None else f"{v:.2f}" for v in ppe_turn])
    rows.append(["⏳ 待补:吨铝完全成本 / 吨毛利 / 产能利用率 —— 需从年报「经营情况讨论与分析」取产销量，"
                 "是周期股「底部能否不亏」的核心判据（见 `_模板/财报关注要点-行业模板.md` 周期块）"] +
                [""] * len(years))

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)

    print(f"── 财务比率校验：{nchk} 条，不通过 0")
    print(f"✅ 财务比率.csv 已写出（通用底 {len(R)} 项 + 定制层 2 项 · {years[0]}-{years[-1]} 共 {len(years)} 年）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
