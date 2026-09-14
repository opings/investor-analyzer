#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""受限净资产与分红能力构建器 → 受限净资产.csv

为什么重要：watchlist 把「拼多多首次分红/回购信号」列为跟踪项，但此前本库只把它当**管理层意愿**问题。
20-F Note 18「Restricted Net Assets」说明它同时是一个**法定能力**问题——
境内主体只能从**按中国会计准则**确定的留存收益中分红，且实缴资本与法定公积不可分配。
本表把「受限规模 / 占权益比」量化，供判断分红空间。

数据来源（全部一手·20-F Note 18「Restricted Net Assets」）：
  FY2023 / FY2024 / FY2025 三份 20-F 各自的当年披露。

⚠️ 手工转录附注叙述，每年更新前须人工 grep 复核（关键词见 KEYWORDS）。
"""
import csv, os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "受限净资产.csv")
KEYWORDS = "restricted net assets of the Company / general reserve fund / not distributable as cash dividends"

# 单位：千元人民币 / 千美元（20-F 原文口径）
RNA = {
    "2023": {"RMB": 80_755_482, "USD": 11_374_172},
    "2024": {"RMB": 104_359_403, "USD": 14_297_180},
    "2025": {"RMB": 125_917_402, "USD": 18_005_949},
}


def main():
    errs, nchk = [], 0
    years = ["2023", "2024", "2025"]

    bs = list(csv.reader(open(os.path.join(HERE, "资产负债表.csv"), encoding="utf-8")))
    hdr = next(r for r in bs if r and r[0].strip() in ("科目", "指标"))
    m = {c.strip(): i for i, c in enumerate(hdr)}
    for probe in ("股东权益合计", "留存收益"):
        if not any(probe in r[0] for r in bs if r):
            print(f"❌ 资产负债表.csv 探针「{probe}」未找到——表头/科目名可能变了")
            return 1

    def get(key, y):
        r = next(r for r in bs if r and key in r[0])
        return float(r[m[y]])

    eq = {y: get("股东权益合计", y) for y in years}
    re_ = {y: get("留存收益", y) for y in years}

    # 校验①：受限净资产不应超过股东权益
    for y in years:
        nchk += 1
        if RNA[y]["RMB"] > eq[y]:
            errs.append(f"[{y}] 受限净资产 {RNA[y]['RMB']:,.0f} 超过股东权益 {eq[y]:,.0f}")
    # 校验②：受限净资产应逐年增长（法定公积只增不减·除非分配或减资）
    for a, b in (("2023", "2024"), ("2024", "2025")):
        nchk += 1
        if RNA[b]["RMB"] < RNA[a]["RMB"]:
            errs.append(f"[{a}→{b}] 受限净资产下降，需核对是否发生分配或减资")
    # 校验③：美元折算率应在合理区间（6.0–7.5）
    for y in years:
        nchk += 1
        fx = RNA[y]["RMB"] / RNA[y]["USD"]
        if not (6.0 <= fx <= 7.5):
            errs.append(f"[{y}] 隐含汇率 {fx:.4f} 超出 6.0–7.5，转录可能有误")

    if errs:
        print(f"❌ 校验不通过 {len(errs)}：")
        for e in errs:
            print("   ✗", e)
        return 1

    rows = [
        ["单位:千元(人民币 RMB / 美元 USD),与 20-F 原文口径一致;占比为派生"],
        ["来源:FY2023/FY2024/FY2025 三份 20-F 各自的 Note「Restricted Net Assets」当年披露"],
        [f"⚠️ 手工转录附注叙述,每年更新前人工 grep 复核:{KEYWORDS}"],
        ["🔴 本表 2026-09-14 补建 —— 此前本库把「首次分红/回购」只当**管理层意愿**问题，"
         "漏掉了它同时是**法定能力**问题:境内主体只能从**按中国会计准则**确定的留存收益分红，"
         "且实缴资本与法定公积**不可作现金股利分配**"],
        [],
        ["【A · 受限净资产规模】"],
        ["项目"] + years,
        ["受限净资产(千元人民币)"] + [RNA[y]["RMB"] for y in years],
        ["受限净资产(千美元·原文折算)"] + [RNA[y]["USD"] for y in years],
        ["隐含折算汇率"] + [f"{RNA[y]['RMB'] / RNA[y]['USD']:.4f}" for y in years],
        ["同比"] + [""] + [f"{RNA[b]['RMB'] / RNA[a]['RMB'] * 100 - 100:+.1f}%"
                          for a, b in (("2023", "2024"), ("2024", "2025"))],
        [],
        ["【B · 派生:占比与可分配空间】"],
        ["指标"] + years,
        ["股东权益合计(千元人民币)"] + [f"{eq[y]:.0f}" for y in years],
        ["🔴 受限净资产 ÷ 股东权益"] + [f"{RNA[y]['RMB'] / eq[y] * 100:.1f}%" for y in years],
        ["留存收益(US GAAP 口径·千元人民币)"] + [f"{re_[y]:.0f}" for y in years],
        ["受限净资产 ÷ 留存收益(US GAAP)"] + [f"{RNA[y]['RMB'] / re_[y] * 100:.1f}%" for y in years],
        ["⚠️ **不可用 US GAAP 留存收益推算可分配额**:20-F 明示「U.S. GAAP 合并报表的经营成果与境内主体的"
         "**法定报表**不同」,分红上限按**中国会计准则**的法定报表定，本库无该口径数据 ⏳"],
        [],
        ["【C · 法定限制条款(20-F 原文要点)】"],
        ["条款", "内容"],
        ["分红来源限制", "境内子公司、VIE 及其子公司**只能从按中国会计准则确定的留存收益**中分红"],
        ["法定公积金", "外商投资企业须将**年度税后利润的至少 10%** 计提一般准备金，"
                      "直至累计达**注册资本的 50%**；该准备金**只能用于特定用途、不可作现金股利分配**"],
        ["其他两项基金", "企业发展基金、职工福利及奖励基金——由董事会**酌情**计提（非强制）"],
        ["受限范围", "包含境内子公司的**实缴资本与法定公积**，以及**VIE 的全部权益**（按中国会计准则确定）"],
        ["外汇管制", "外汇及其他法规**可能进一步限制** VIE 以股利、借款、垫款形式向母公司转移资金"],
        ["传导路径", "开曼母公司分红能力 ← 依赖境内子公司的股利 + VIE 支付的**许可费与服务费**"],
        [],
        ["【D · 分红/回购现状】"],
        ["项目", "状态", "说明"],
        ["普通股现金股利", "无", "截至 FY2025 20-F 未见普通股现金股利披露"],
        ["普通股回购", "无", "20-F 中 repurchase 相关表述均指**可转债**回售/赎回（2024 Notes、2025 Notes），非股份回购"],
        ["⚠️ 读法", "—", "因此 watchlist 的「首次分红/回购信号」须**双条件**看:"
                        "①管理层意愿 ②受限净资产占比下降或公司披露法定可分配额。"
                        "**只看前者会高估分红空间**"],
    ]

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)

    print(f"── 受限净资产校验：{nchk} 条，不通过 0")
    print("✅ 受限净资产.csv 已写出（FY2023–FY2025）")
    for y in years:
        print(f"   {y}: 受限 RMB {RNA[y]['RMB'] / 1e5:>8.1f} 亿 = 股东权益的 {RNA[y]['RMB'] / eq[y] * 100:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
