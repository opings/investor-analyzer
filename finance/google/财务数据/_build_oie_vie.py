#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""年度 OI&E 拆解 + 股权投资 + VIE 构建器 → OI&E与股权投资-年度.csv

为什么迟到（2026-09-13 补建）：
  本库对 **2026 中期** 已做 OI&E 七项拆解（`中期财务-2026.csv`），但**年度序列没做**——
  `利润表.csv` 里 FY2025 的 OI&E 只有一个合计数 29,787，是个黑箱，
  看不出其中 24,080（81%）是**股权证券公允价值重估**。
  年度与中期口径不对称，导致「报告净利被股权重估污染」这条判断在年度层面无法验证。
  同时 10-K Note 5（VIE）内容此前完全未入库。

数据来源（全部一手·FY2025 10-K）：
  · Note 7 OI&E「Components of OI&E were as follows」七项拆解（FY2023–FY2025）
  · MD&A 非上市股权账面值（measurement alternative）与权益法投资账面值
  · Note 5 Variable Interest Entities（并表/未并表 VIE、NCI/RNCI）
  · Note 16 Subsequent Event（2026-01 未实现收益）+ Note 5（2026-02 Waymo 融资轮）

⚠️ 手工转录附注表格，每年更新前须人工复核（关键词见 KEYWORDS）。
"""
import csv, os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "OI&E与股权投资-年度.csv")
KEYWORDS = ("Components of OI&E were as follows / carrying value of our non-marketable equity securities / "
            "Variable Interest Entities / Subsequent Event")

# ── Note 7：OI&E 七项拆解（百万美元）────────────────────────────────────
OIE = {
    "利息收入 Interest income":                                    {"2023": 3865, "2024": 4482, "2025": 4337},
    "利息费用 Interest expense":                                   {"2023": -308, "2024": -268, "2025": -736},
    "汇兑损益 Foreign currency exchange gain(loss), net":           {"2023": -1238, "2024": -409, "2025": -382},
    "债务证券损益 Gain(loss) on debt securities, net":               {"2023": -1215, "2024": -1043, "2025": 540},
    "🔴股权证券损益 Gain(loss) on equity securities, net":           {"2023": 392, "2024": 3714, "2025": 24080},
    "权益法损益及减值 Income(loss) from equity method investments":   {"2023": -628, "2024": -188, "2025": 281},
    "其他 Other":                                                  {"2023": 556, "2024": 1137, "2025": 1667},
}
OIE_TOTAL = {"2023": 1424, "2024": 7425, "2025": 29787}
CAP_INT = {"2023": 181, "2024": 194, "2025": 447}          # 利息费用中已资本化部分
PBT = {"2023": 85717, "2024": 119815, "2025": 158826}       # 对照 利润表.csv
NI = {"2023": 73795, "2024": 100118, "2025": 132170}

# ── 股权投资账面（十亿→百万美元）──────────────────────────────────────
NONMKT = {"2024": 35200, "2025": 64100}     # 计量替代法·非上市股权
EQMETHOD = {"2024": 2000, "2025": 2500}     # 权益法投资（约数）

# ── Note 5：VIE（百万美元）────────────────────────────────────────────
VIE = {
    "并表VIE·仅可用于清偿该VIE义务的资产": {"2024": 8700, "2025": 5600},
    "并表VIE·债权人仅对该VIE有追索权的负债": {"2024": 2300, "2025": 2000},
    "非控股权益 NCI 合计":                 {"2024": 4200, "2025": 3400},
    "其中:可赎回非控股权益 RNCI":           {"2024": 1100, "2025": 841},
    "未并表VIE·未来出资承诺":              {"2024": 1500, "2025": 1100},
}


def main():
    errs, nchk = [], 0
    years = ["2023", "2024", "2025"]

    # 勾稽①：七项之和 = OI&E 合计
    for y in years:
        nchk += 1
        s = sum(v[y] for v in OIE.values())
        if s != OIE_TOTAL[y]:
            errs.append(f"[{y}] OI&E 七项之和 {s} ≠ 合计 {OIE_TOTAL[y]}")

    # 勾稽②：OI&E 合计 = 利润表.csv 同年值
    inc = list(csv.reader(open(os.path.join(HERE, "利润表.csv"), encoding="utf-8")))
    hdr = next(r for r in inc if r and r[0].strip() in ("科目", "指标"))
    im = {c.strip(): i for i, c in enumerate(hdr)}
    row = next(r for r in inc if r and r[0].startswith("其他收入(支出)净额"))
    for y in years:
        nchk += 1
        v = int(row[im[y]])
        if v != OIE_TOTAL[y]:
            errs.append(f"[{y}] 本表 OI&E {OIE_TOTAL[y]} ≠ 利润表.csv {v}")

    # 勾稽③：RNCI ≤ NCI
    for y in ("2024", "2025"):
        nchk += 1
        if VIE["其中:可赎回非控股权益 RNCI"][y] > VIE["非控股权益 NCI 合计"][y]:
            errs.append(f"[{y}] RNCI 超过 NCI")

    if errs:
        print(f"❌ 校验不通过 {len(errs)}:")
        for e in errs:
            print("   ✗", e)
        return 1

    rows = [
        ["单位:百万美元(USD millions);费用/流出=负数"],
        ["来源:FY2025 10-K Note 7(OI&E 七项拆解) / MD&A(股权投资账面) / Note 5(VIE) / Note 16(期后事项)"],
        [f"⚠️ 手工转录附注,每年更新前人工 grep 复核:{KEYWORDS}"],
        ["🔴 本表 2026-09-13 补建 —— 此前本库只对**2026 中期**做了 OI&E 拆解(`中期财务-2026.csv`),"
         "**年度序列无拆解**:`利润表.csv` 里 FY2025 的 OI&E 只有合计 29,787 一个黑箱数,"
         "看不出其中 24,080(81%)是股权公允价值重估 → 「报告净利被污染」这条判断在年度层面无从验证"],
        [],
        ["【A · OI&E 七项拆解（Note 7 原表）】"],
        ["科目"] + years,
    ]
    for k, v in OIE.items():
        rows.append([k] + [v[y] for y in years])
    rows.append(["=OI&E 合计 Other income(expense), net"] + [OIE_TOTAL[y] for y in years])
    rows.append(["备注:利息费用中已资本化部分(不在上行)"] + [CAP_INT[y] for y in years])

    rows += [
        [],
        ["【B · 派生：口径污染度】"],
        ["指标"] + years,
        ["股权证券损益 ÷ OI&E"] +
        [f"{OIE['🔴股权证券损益 Gain(loss) on equity securities, net'][y] / OIE_TOTAL[y] * 100:.1f}%" for y in years],
        ["股权证券损益 ÷ 除税前利润"] +
        [f"{OIE['🔴股权证券损益 Gain(loss) on equity securities, net'][y] / PBT[y] * 100:.1f}%" for y in years],
        ["OI&E ÷ 除税前利润（整体污染度）"] + [f"{OIE_TOTAL[y] / PBT[y] * 100:.1f}%" for y in years],
        ["剔除股权证券损益后的除税前利润"] +
        [PBT[y] - OIE['🔴股权证券损益 Gain(loss) on equity securities, net'][y] for y in years],
        ["剔除后除税前利润同比"] + [""] +
        [f"{(PBT[y] - OIE['🔴股权证券损益 Gain(loss) on equity securities, net'][y]) / (PBT[p] - OIE['🔴股权证券损益 Gain(loss) on equity securities, net'][p]) * 100 - 100:+.1f}%"
         for y, p in (("2024", "2023"), ("2025", "2024"))],
        ["对照:报告除税前利润同比"] + [""] +
        [f"{PBT[y] / PBT[p] * 100 - 100:+.1f}%" for y, p in (("2024", "2023"), ("2025", "2024"))],
        [f"🔑 读法:2025 报告除税前 {PBT['2025']/PBT['2024']*100-100:+.1f}%,剔除股权重估后仅 "
         f"{(PBT['2025']-OIE['🔴股权证券损益 Gain(loss) on equity securities, net']['2025'])/(PBT['2024']-OIE['🔴股权证券损益 Gain(loss) on equity securities, net']['2024'])*100-100:+.1f}%"
         " —— **报告增速的一半以上由公允价值变动贡献**(该行由脚本计算,勿手写)"],

        [],
        ["【C · 股权投资账面价值】"],
        ["项目", "2024", "2025", "变动"],
        ["非上市股权(计量替代法·平时按成本·仅观察到交易时重估)", NONMKT["2024"], NONMKT["2025"],
         f"{NONMKT['2025'] / NONMKT['2024'] * 100 - 100:+.1f}%"],
        ["权益法投资(约数)", EQMETHOD["2024"], EQMETHOD["2025"],
         f"{EQMETHOD['2025'] / EQMETHOD['2024'] * 100 - 100:+.1f}%"],
        ["⚠️ 计量替代法=平时不动、只在出现同一发行人的可观察交易时才重估 → "
         "**账面跳升与损益跳升同源且不可预测**,不是经营成果"],

        [],
        ["【D · VIE（Note 5）】此前本库零覆盖"],
        ["项目", "2024", "2025"],
    ]
    for k, v in VIE.items():
        rows.append([k, v["2024"], v["2025"]])
    rows += [
        ["⚠️ NCI 与 RNCI **计入资本公积(APIC)**,不单列权益行 —— 看权益结构时勿漏"],
        ["⚠️ 未并表 VIE 敞口 = 当前账面 + 未来出资承诺;另有数据中心租赁(融资租赁)与信用背书(按信用衍生品核算)"],

        [],
        ["【E · 期后事项】"],
        ["日期", "事项", "金额", "说明"],
        ["2026-01", "非上市投资确认未实现收益", 32000,
         "🔴 Note 16 原文「approximately $32.0 billion of unrealized gains in our non-marketable investments… "
         "**subject to change as we finalize related valuations**」"
         "(译:就非上市投资确认约 320 亿美元未实现收益……**该金额在估值最终确定前仍可能变动**)。"
         "⚠️ 经济内容已被 `中期财务-2026.csv` 的 H1 2026 股权证券损益 135,946 涵盖,本行记的是**最早披露时点与其不确定性警示**"],
        ["2026-02", "Waymo(并表 VIE)宣布融资轮", 16000,
         "🔴 Note 5 原文「Waymo, a consolidated VIE, announced an investment round of $16.0 billion, "
         "**the significant majority of which was funded by Alphabet**」"
         "(译:并表 VIE Waymo 宣布 160 亿美元融资轮,**其中绝大部分由 Alphabet 出资**)。"
         "外部方投资按**权益交易**核算并确认非控股权益。"
         "⚠️ 本库此前对该轮零记录,Waymo 仅作为「Other Bets 亏损扩大」出现"],

        [],
        ["🚨 **两个「320 亿」不可混淆**(同在 FY2025 10-K 内):"],
        ["  (a) Wiz 收购对价 $32.0B —— **全现金**,2025-03 签约、2026-03-11 交割(见 `中期财务-2026.csv` 单项事实段)"],
        ["  (b) 2026-01 非上市投资未实现收益 $32.0B —— **非现金**、未实现、且估值未最终确定"],
    ]

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)

    print(f"── OI&E/股权投资/VIE 校验：{nchk} 条，不通过 0")
    print("✅ OI&E与股权投资-年度.csv 已写出（FY2023–FY2025 拆解 + 股权账面 + VIE + 期后事项）")
    eq = OIE['🔴股权证券损益 Gain(loss) on equity securities, net']
    print(f"\n🔴 FY2025 股权证券损益 {eq['2025']:,} 百万 = OI&E 的 {eq['2025']/OIE_TOTAL['2025']*100:.0f}%、"
          f"除税前利润的 {eq['2025']/PBT['2025']*100:.1f}%")
    print(f"🔴 剔除后除税前利润同比 +{(PBT['2025']-eq['2025'])/(PBT['2024']-eq['2024'])*100-100:.1f}% "
          f"vs 报告口径 +{PBT['2025']/PBT['2024']*100-100:.1f}%")
    print(f"🔴 非上市股权账面 {NONMKT['2024']:,} → {NONMKT['2025']:,} 百万（{NONMKT['2025']/NONMKT['2024']*100-100:+.0f}%）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
