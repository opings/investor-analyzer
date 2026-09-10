#!/usr/bin/env python3
"""特斯拉「政策相关损益」构建器 —— 监管积分收入 + IRA 制造税收抵免。

为什么单独一张表（不并进 分部营收.csv）
──────────────────────────────────────────────────────────────────
`分部营收.csv` 由 `_build_from_filings.py` 从各年 10-K 的 **SEC 渲染报表 R*.htm** 机器生成、
并受分部勾稽约束；而本表的两类数字**只出现在 10-K 正文与会计政策附注的叙述里**（不在任何
结构化报表行项中），血缘不同。混进同一张机器生成的表会同时破坏构建器与数据血缘纪律，
故独立成表，由 `分部营收.csv` 表头交叉指引。

两类政策相关损益的**性质与落点完全不同，不可混谈**
──────────────────────────────────────────────────────────────────
| | 汽车监管积分 | IRA 制造税收抵免 |
|---|---|---|
| 谁掏钱 | **其他车企**（法规造出的合规市场） | **美国纳税人**（税收支出） |
| 进哪 | **收入**（利润表单列一行） | **冲减营业成本**（不进收入，只让成本变小） |
| 可见性 | 利润表可见 | **报表看不见**，只在正文附注披露金额 |

数据来源（均为一手 10-K，已跨申报交叉核）
──────────────────────────────────────────────────────────────────
· **监管积分收入**：各年 10-K「Revenue by source」收入拆分表 + MD&A 分部收入表。
  2018 取自 FY2018 10-K（千美元口径）；2019 起取自各年 10-K（百万口径 ×1000）。
  跨申报核验：同一年份在 2–3 份 10-K 的比较列中数值一致（如 2021 的 1,465 在 FY2021/22/23 三份中一致）。
· **制造抵免**：各年 10-K 会计政策附注「cost of ... revenue benefits from manufacturing credits earned,
  amounting to $X, $Y and $Z」。
  - **首次量化披露在 FY2024 10-K**（给出 2024 与 2023 两年）；FY2025 10-K 给出 2025/2024/2023 三年。
  - 跨申报核验：**FY2024 与 FY2025 两份 10-K 对 2023、2024 的金额完全一致**（汽车 359/625、能源 115/756）。
  - FY2023 10-K 只作定性表述（「benefits from manufacturing credits earned」）**未给金额**；
    FY2021/FY2022 10-K **零次提及** —— 与 IRA「effective for taxable years beginning after
    December 31, 2022」一致，故 2022 及以前结构性为无（表中留空，非缺失）。
  - ⚠️ **精度**：FY2025 的能源抵免印为「$1.12 **billion**」（三位有效数字），其余年份印为精确百万数。
    故 2025 能源抵免的末位精度低于其他格。

派生口径
──────────────────────────────────────────────────────────────────
能源板块毛利、总营收、归母净利来自本目录既有 CSV（`分部营收.csv` / `利润表.csv`），
不重复录入。「剔除制造抵免后的能源毛利率」= (能源毛利 − 能源抵免) ÷ 能源收入
——因为报告口径的能源成本**已被抵免冲减过**，要还原真实经营毛利必须把抵免加回成本。

校验：抵免加回后的毛利率必须低于报告毛利率；政策合计不得超过对应年份的营业收入。
不通过不写出 CSV。
"""
from __future__ import annotations

import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# ── 一手转录（千美元）────────────────────────────────────────────
# 汽车监管积分收入：各年 10-K 收入拆分表
REG_CREDIT = {
    2018: 418618,      # FY2018 10-K 收入拆分表（该年印刷单位为千美元）
    2019: 594000, 2020: 1580000, 2021: 1465000, 2022: 1776000,
    2023: 1790000, 2024: 2763000, 2025: 1993000,
}
# IRA 制造税收抵免（冲减营业成本）：FY2024 / FY2025 10-K 会计政策附注
MFG_AUTO = {2023: 359000, 2024: 625000, 2025: 565000}
MFG_ENERGY = {2023: 115000, 2024: 756000, 2025: 1120000}   # 2025 原文印「$1.12 billion」

ROWS = [
    "【收入侧】汽车监管积分收入 Automotive regulatory credits (revenue)",
    "【成本侧】IRA 制造抵免-汽车 Manufacturing credits, automotive (cost offset)",
    "【成本侧】IRA 制造抵免-能源 Manufacturing credits, energy (cost offset)",
    "【成本侧】IRA 制造抵免合计 Manufacturing credits, total",
    "政策相关合计(监管积分+制造抵免) Policy-related total",
    "—— 派生 ——",
    "能源板块毛利(报告口径) Energy gross profit, as reported",
    "能源板块毛利率(报告口径) Energy gross margin, as reported",
    "能源抵免÷能源板块毛利 Energy credits / energy gross profit",
    "能源板块毛利率(剔除制造抵免) Energy gross margin, ex-credits",
    "监管积分÷归母净利 Regulatory credits / net income",
    "政策相关合计÷归母净利 Policy-related total / net income",
]


def read_csv(name, hdr):
    rows = list(csv.reader(open(os.path.join(HERE, name), encoding="utf-8")))
    years = rows[hdr][1:]
    return {r[0]: dict(zip(years, r[1:])) for r in rows[hdr + 1:]}


def num(tbl, key, y):
    s = tbl.get(key, {}).get(str(y), "")
    return float(s) if s not in ("", None) else None


def main():
    # ⚠️ hdr = 表头行的 0-based 行号；改了上游 CSV 的注释行数就要同步改这里。
    # 曾发生：分部营收.csv 加了一行注释后，本脚本仍按旧偏移读取 → 能源毛利全部取到 None，
    # 派生行被「全空则不写」的过滤器静默丢弃，而校验仍显示「0 不通过」。故下方加探针自检。
    seg = read_csv("分部营收.csv", 3)
    inc = read_csv("利润表.csv", 2)
    for nm, tbl, probe in (("分部营收.csv", seg, "能源发电与储存 Energy generation and storage"),
                           ("利润表.csv", inc, "营业收入 Total revenues")):
        if probe not in tbl:
            print(f"❌ {nm} 表头行号(hdr)不对：找不到探针行「{probe}」——注释行数可能变了")
            return 1

    data, errs, nchk = {}, [], 0
    years = sorted(set(REG_CREDIT) | set(MFG_AUTO))
    for y in years:
        d = {}
        rc = REG_CREDIT.get(y)
        ma, me = MFG_AUTO.get(y), MFG_ENERGY.get(y)
        d["【收入侧】汽车监管积分收入 Automotive regulatory credits (revenue)"] = rc
        d["【成本侧】IRA 制造抵免-汽车 Manufacturing credits, automotive (cost offset)"] = ma
        d["【成本侧】IRA 制造抵免-能源 Manufacturing credits, energy (cost offset)"] = me
        mt = None if (ma is None and me is None) else (ma or 0) + (me or 0)
        d["【成本侧】IRA 制造抵免合计 Manufacturing credits, total"] = mt
        d["政策相关合计(监管积分+制造抵免) Policy-related total"] = None if rc is None else rc + (mt or 0)

        erev = num(seg, "能源发电与储存 Energy generation and storage", y)
        ecost = num(seg, "【成本】能源发电与储存 Energy generation and storage", y)
        ni = num(inc, "归母净利润 Net income (loss) attributable to common stockholders", y)
        rev = num(inc, "营业收入 Total revenues", y)
        egp = None if (erev is None or ecost is None) else erev - ecost
        d["能源板块毛利(报告口径) Energy gross profit, as reported"] = egp
        d["能源板块毛利率(报告口径) Energy gross margin, as reported"] = None if not erev else egp / erev
        d["能源抵免÷能源板块毛利 Energy credits / energy gross profit"] = None if (me is None or not egp) else me / egp
        d["能源板块毛利率(剔除制造抵免) Energy gross margin, ex-credits"] = (
            None if (me is None or not erev or egp is None) else (egp - me) / erev)
        d["监管积分÷归母净利 Regulatory credits / net income"] = None if (rc is None or not ni or ni <= 0) else rc / ni
        pt = d["政策相关合计(监管积分+制造抵免) Policy-related total"]
        d["政策相关合计÷归母净利 Policy-related total / net income"] = None if (pt is None or not ni or ni <= 0) else pt / ni
        data[y] = d

        # 校验
        if me is not None and egp is not None and erev:
            nchk += 1
            if d["能源板块毛利率(剔除制造抵免) Energy gross margin, ex-credits"] >= d["能源板块毛利率(报告口径) Energy gross margin, as reported"]:
                errs.append(f"[{y}] 剔除抵免后毛利率未低于报告毛利率（抵免加回方向错）")
        if pt is not None and rev:
            nchk += 1
            if pt > rev:
                errs.append(f"[{y}] 政策相关合计 {pt:,.0f} 超过营业收入 {rev:,.0f}")
        if me is not None and egp is not None:
            nchk += 1
            if me > egp:
                errs.append(f"[{y}] 能源抵免 {me:,.0f} 超过能源板块毛利 {egp:,.0f}（数值或口径有误）")

    # 完整性自检：派生行必须真的算出来了。「0 条错误」不等于「输出完整」——
    # 若上游取数失败，派生值全为 None，会被「全空则不写」的过滤器静默丢掉。
    MUST = {"能源板块毛利(报告口径) Energy gross profit, as reported": (2023, 2024, 2025),
            "能源抵免÷能源板块毛利 Energy credits / energy gross profit": (2023, 2024, 2025),
            "能源板块毛利率(剔除制造抵免) Energy gross margin, ex-credits": (2023, 2024, 2025),
            "政策相关合计÷归母净利 Policy-related total / net income": (2023, 2024, 2025)}
    missing = [f"{r}@{y}" for r, ys in MUST.items() for y in ys if data.get(y, {}).get(r) is None]
    if missing:
        print(f"❌ 完整性自检未过：{len(missing)} 个必需派生值为空（上游取数失败）")
        for m in missing[:10]:
            print("   ✗", m)
        return 1
    nchk += len(missing) or sum(len(v) for v in MUST.values())

    print(f"── 政策表校验：{nchk} 条（含完整性自检），不通过 {len(errs)}")
    for e in errs:
        print("   ✗", e)
    if errs:
        print("\n❌ 校验未过 —— 不写出 CSV。")
        return 1

    def fmt(v):
        if v is None:
            return ""
        if abs(v) < 1:
            return f"{v:.4f}"
        return f"{v:.0f}" if abs(v - round(v)) < 1e-6 else f"{v:.4f}"

    with open(os.path.join(HERE, "政策补贴与积分.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["单位:金额为千美元(USD thousands);比率为倍数(1=100%);空=该年一手申报未披露或该项目当年尚不存在"])
        w.writerow(["🔴 两类政策损益性质不同不可混谈:【收入侧】监管积分=**其他车企**掏钱买合规额度,进利润表收入行;"
                    "【成本侧】IRA 制造抵免=**美国纳税人**掏钱,**冲减营业成本、报表上看不见**,只在 10-K 正文附注披露金额"])
        w.writerow(["来源:监管积分=各年 10-K「Revenue by source」收入拆分表;制造抵免=FY2024/FY2025 10-K 会计政策附注。"
                    "跨申报核验:FY2024 与 FY2025 两份 10-K 对 2023/2024 抵免金额完全一致"])
        w.writerow(["⚠️ 制造抵免 2022 及以前结构性为无(IRA 对 2022-12-31 后开始的税年生效,FY2021/FY2022 10-K 零次提及);"
                    "FY2023 10-K 仅定性提及未给金额,首次量化披露在 FY2024 10-K"])
        w.writerow(["⚠️ 精度:FY2025 能源抵免原文印「$1.12 billion」(三位有效数字),其余年份印精确百万数"])
        w.writerow(["⚠️ 报告口径的能源营业成本**已被抵免冲减过**,故「剔除制造抵免后的能源毛利率」= (能源毛利−能源抵免)÷能源收入"])
        w.writerow(["科目"] + [str(y) for y in years])
        for r in ROWS:
            if r.startswith("——"):
                w.writerow([r])
                continue
            vals = [data.get(y, {}).get(r) for y in years]
            if any(v is not None for v in vals):
                w.writerow([r] + [fmt(v) for v in vals])
    print(f"✅ 政策补贴与积分.csv 已写出（{years[0]}-{years[-1]}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
