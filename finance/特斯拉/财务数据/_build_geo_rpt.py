#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""地区营收 + 关联方交易 构建器 → 地区营收.csv / 关联方交易.csv

为什么迟到：建库(2026-09-05)时只取了报表页，**Note 15/16(10-K) 与 Note 13/14(10-Q) 从未被读过**。
2026-09-13 系统枚举附注时才发现——地区拆分与关联方收入一直就在申报里，不是「不可得」。
（教训同 [[unavailable-means-one-path-tried]]：判「数据不可得」前先问是不是只探了一条路。）

数据来源（全部一手）：
  · FY2025 10-K Note 16「Segment Reporting and Information about Geographic Areas」
  · FY2025 10-K Note 15「Related Party Transactions」
  · 2026Q2 10-Q Note 14 / Note 13（同名附注的中期版）
  · FY2025 10-K ITEM 7A「Quantitative and Qualitative Disclosures About Market Risk」（汇率敏感度）

⚠️ 金额为手工转录附注表格，每期更新前须人工复核（关键词见 KEYWORDS）。
"""
import csv, os

HERE = os.path.dirname(os.path.abspath(__file__))
KEYWORDS = ("revenues by geographic area based on the sales location / "
            "Related Party Transactions / for its purchase of our Megapack products")

# ── 地区营收（百万美元）· 10-K Note 16 + 10-Q Note 14 ──────────────────────
GEO_FY = {  # 年度
    "2023": {"美国 United States": 45235, "中国 China": 21745, "其他国际 Other international": 29793},
    "2024": {"美国 United States": 47725, "中国 China": 20944, "其他国际 Other international": 29021},
    "2025": {"美国 United States": 47627, "中国 China": 20962, "其他国际 Other international": 26238},
}
GEO_H1 = {  # 中期（上半年）
    "2025H1": {"美国 United States": 22142, "中国 China": 8608, "其他国际 Other international": 11081},
    "2026H1": {"美国 United States": 23885, "中国 China": 8859, "其他国际 Other international": 17879},
}
GEO_Q2 = {
    "2025Q2": {"美国 United States": 11809, "中国 China": 4305, "其他国际 Other international": 6382},
    "2026Q2": {"美国 United States": 13208, "中国 China": 4675, "其他国际 Other international": 10353},
}
# 长期资产按地区（百万美元）
LLA = {
    "2024": {"美国 United States": 32461, "德国 Germany": 4175, "其他国际 Other international": 4124},
    "2025": {"美国 United States": 35847, "德国 Germany": 4775, "其他国际 Other international": 4625},
    "2026H1": {"美国 United States": 42213, "其他国际 Other international": 9552},  # Q2 把德国并入其他
}
# 分部存货（百万美元）
INV_SEG = {
    "2024": {"汽车 Automotive": 9988, "能源 Energy": 2029},
    "2025": {"汽车 Automotive": 9678, "能源 Energy": 2714},
    "2026H1": {"汽车 Automotive": 9637, "能源 Energy": 4115},
}
# 公司官方分部口径（含「服务及其他」并入汽车分部）·百万美元
SEG_OFFICIAL = {
    "2023": {"汽车分部收入": 90738, "汽车分部成本": 74219, "能源分部收入": 6035, "能源分部成本": 4894},
    "2024": {"汽车分部收入": 87604, "汽车分部成本": 72794, "能源分部收入": 10086, "能源分部成本": 7446},
    "2025": {"汽车分部收入": 82056, "汽车分部成本": 68764, "能源分部收入": 12771, "能源分部成本": 8969},
    "2026H1": {"汽车分部收入": 45076, "汽车分部成本": 37197, "能源分部收入": 5547, "能源分部成本": 3955},
}
# ── 关联方交易（百万美元）──────────────────────────────────────────────
RPT = [
    # (期间, 对手方, 收入, 成本, 说明)
    ("2023", "—", None, None, "10-K 自陈：与关联方交易**不重大(immaterial)**"),
    ("2024", "—", None, None, "10-K 自陈：与关联方交易**不重大(immaterial)**"),
    ("2025", "xAI", 430, 285, "xAI 购买 Megapack 产品(正常商业过程)；其余关联方交易不重大"),
    ("2025H1", "—", None, None, "10-Q 自陈：与关联方交易**不重大**"),
    ("2026Q2", "SpaceX", 318, 242, "SpaceX 购买 Megapack 产品"),
    ("2026H1", "SpaceX", 405, 307, "SpaceX 购买 Megapack 产品；其余不重大"),
]
# 汇率敏感度（10-K ITEM 7A·十亿美元）
FX_SENS = {"2024": 1.15, "2025": 1.70}


def pct(a, b):
    return f"{a / b * 100:.2f}%" if (a is not None and b) else ""


def main():
    errs, nchk = [], 0

    # ===== 地区营收.csv =====
    rows = [
        ["单位:百万美元(USD millions);占比为派生。空=该期申报未单列"],
        ["来源:FY2025 10-K Note 16「Segment Reporting and Information about Geographic Areas」"
         " + 2026Q2 10-Q Note 14(同名附注中期版);按**产品销售地(sales location)**划分"],
        [f"⚠️ 手工转录附注表格,每期更新前人工复核关键词:{KEYWORDS}"],
        ["🔑 本表 2026-09-13 补建 —— 建库时只取报表页、未读附注,曾据此误判「本库无地区拆分·汇率敞口不可量化」"],
        [],
        ["【A · 年度地区营收】"],
        ["地区", "2023", "2024", "2025", "2023→2025 变动"],
    ]
    regions = ["美国 United States", "中国 China", "其他国际 Other international"]
    for r in regions:
        v23, v25 = GEO_FY["2023"][r], GEO_FY["2025"][r]
        rows.append([r, GEO_FY["2023"][r], GEO_FY["2024"][r], GEO_FY["2025"][r],
                     f"{(v25 / v23 - 1) * 100:+.1f}%"])
    tot = {y: sum(GEO_FY[y].values()) for y in GEO_FY}
    rows.append(["合计 Total", tot["2023"], tot["2024"], tot["2025"],
                 f"{(tot['2025'] / tot['2023'] - 1) * 100:+.1f}%"])
    rows.append([])
    rows.append(["占比", "2023", "2024", "2025", ""])
    for r in regions:
        rows.append([r] + [pct(GEO_FY[y][r], tot[y]) for y in ("2023", "2024", "2025")] + [""])
    rows.append(["**非美合计**"] + [pct(tot[y] - GEO_FY[y]["美国 United States"], tot[y])
                                 for y in ("2023", "2024", "2025")] + [""])

    # 勾稽：地区合计 = 总营收（对照利润表）
    inc = list(csv.reader(open(os.path.join(HERE, "利润表.csv"), encoding="utf-8")))
    hdr = next(r for r in inc if r and r[0].strip() == "科目")
    im = {c.strip(): i for i, c in enumerate(hdr)}
    for y in ("2023", "2024", "2025"):
        nchk += 1
        rev = float(next(r for r in inc if r and r[0].startswith("营业收入"))[im[y]])
        if abs(tot[y] * 1000 - rev) > 1000:
            errs.append(f"[{y}] 地区营收合计 {tot[y]*1000:,.0f} ≠ 利润表营收 {rev:,.0f} 千美元")

    rows += [
        [],
        ["【B · 中期地区营收】🔴 2026H1 的复苏结构与整体口径完全不同"],
        ["地区", "2025H1", "2026H1", "H1同比", "2025Q2", "2026Q2", "Q2同比"],
    ]
    for r in regions:
        h0, h1 = GEO_H1["2025H1"][r], GEO_H1["2026H1"][r]
        q0, q1 = GEO_Q2["2025Q2"][r], GEO_Q2["2026Q2"][r]
        rows.append([r, h0, h1, f"{(h1/h0-1)*100:+.1f}%", q0, q1, f"{(q1/q0-1)*100:+.1f}%"])
    th0, th1 = sum(GEO_H1["2025H1"].values()), sum(GEO_H1["2026H1"].values())
    tq0, tq1 = sum(GEO_Q2["2025Q2"].values()), sum(GEO_Q2["2026Q2"].values())
    rows.append(["合计 Total", th0, th1, f"{(th1/th0-1)*100:+.1f}%", tq0, tq1, f"{(tq1/tq0-1)*100:+.1f}%"])
    inc_oi = GEO_H1["2026H1"]["其他国际 Other international"] - GEO_H1["2025H1"]["其他国际 Other international"]
    rows.append(["", "", "", "", "", "", ""])
    rows.append([f"🔴 H1 营收增量 {th1-th0:,} 百万美元中，「其他国际」贡献 {inc_oi:,} 百万美元 = "
                 f"{inc_oi/(th1-th0)*100:.1f}%；美国与中国合计仅贡献 {100-inc_oi/(th1-th0)*100:.1f}%"])

    rows += [
        [],
        ["【C · 长期资产按地区】"],
        ["地区", "2024", "2025", "2026H1"],
    ]
    for r in ["美国 United States", "德国 Germany", "其他国际 Other international"]:
        rows.append([r, LLA["2024"].get(r, ""), LLA["2025"].get(r, ""), LLA["2026H1"].get(r, "")])
    rows.append(["合计 Total", sum(LLA["2024"].values()), sum(LLA["2025"].values()),
                 sum(LLA["2026H1"].values())])
    rows.append(["⚠️ 2026H1 起德国并入「其他国际」,该行不可跨期直接比"])

    rows += [
        [],
        ["【D · 分部存货】🔴 能源存货 2026H1 半年 +51.6%,而汽车存货基本持平"],
        ["分部", "2024", "2025", "2026H1", "2025→2026H1"],
        ["汽车 Automotive", INV_SEG["2024"]["汽车 Automotive"], INV_SEG["2025"]["汽车 Automotive"],
         INV_SEG["2026H1"]["汽车 Automotive"],
         f"{(INV_SEG['2026H1']['汽车 Automotive']/INV_SEG['2025']['汽车 Automotive']-1)*100:+.1f}%"],
        ["能源 Energy", INV_SEG["2024"]["能源 Energy"], INV_SEG["2025"]["能源 Energy"],
         INV_SEG["2026H1"]["能源 Energy"],
         f"{(INV_SEG['2026H1']['能源 Energy']/INV_SEG['2025']['能源 Energy']-1)*100:+.1f}%"],
        [],
        ["【E · 公司官方分部口径】⚠️ 与 分部营收.csv 的分组不同:官方「汽车分部」**含服务及其他**"],
        ["项目", "2023", "2024", "2025", "2026H1"],
    ]
    for k in ["汽车分部收入", "汽车分部成本", "能源分部收入", "能源分部成本"]:
        rows.append([k] + [SEG_OFFICIAL[y][k] for y in ("2023", "2024", "2025", "2026H1")])
    for seg in ("汽车", "能源"):
        rows.append([f"{seg}分部毛利率(官方口径)"] +
                    [pct(SEG_OFFICIAL[y][f"{seg}分部收入"] - SEG_OFFICIAL[y][f"{seg}分部成本"],
                         SEG_OFFICIAL[y][f"{seg}分部收入"]) for y in ("2023", "2024", "2025", "2026H1")])
    rows.append(["⚠️ 官方汽车分部毛利率(含服务)低于 单位经济-汽车.csv 的「汽车板块毛利率(报告口径)」(不含服务),"
                 "两者口径不同、不可混用"])

    # 勾稽：官方分部收入合计 = 总营收
    for y in ("2023", "2024", "2025"):
        nchk += 1
        s = SEG_OFFICIAL[y]["汽车分部收入"] + SEG_OFFICIAL[y]["能源分部收入"]
        if abs(s - tot[y]) > 1:
            errs.append(f"[{y}] 官方分部收入合计 {s} ≠ 地区营收合计 {tot[y]}")

    rows += [
        [],
        ["【F · 汇率敏感度（公司自陈）】"],
        ["项目", "2024", "2025", "来源"],
        ["全币种不利变动 10% 对税前利润的影响(十亿美元)", FX_SENS["2024"], FX_SENS["2025"],
         "10-K ITEM 7A;公司明示**不做常规外汇对冲**(we do not typically hedge foreign currency risk),"
         "且为**非美元货币净收取方**(net receiver)→ 美元走强不利"],
    ]

    if errs:
        print(f"❌ 地区/关联方校验不通过 {len(errs)}:")
        for e in errs:
            print("   ✗", e)
        return 1

    with open(os.path.join(HERE, "地区营收.csv"), "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)

    # ===== 关联方交易.csv =====
    r2 = [
        ["单位:百万美元(USD millions)。空=该期申报称交易**不重大(immaterial)**、未给金额"],
        ["来源:FY2025 10-K Note 15 + 2026Q2 10-Q Note 13「Related Party Transactions」"],
        ["🔴 为什么重要:关联方买的是 **Megapack**,直接计入**能源分部收入**。"
         "「储能接棒」这条逻辑里有一部分需求来自同一实控人控制的其他公司,须单独看"],
        [],
        ["期间", "对手方", "确认收入", "确认成本", "毛利", "毛利率", "占当期能源分部收入", "说明"],
    ]
    ENE = {"2025": SEG_OFFICIAL["2025"]["能源分部收入"], "2026H1": SEG_OFFICIAL["2026H1"]["能源分部收入"],
           "2026Q2": 3139}
    for period, cp, rev_, cost_, note in RPT:
        gp = (rev_ - cost_) if (rev_ is not None and cost_ is not None) else None
        r2.append([period, cp, rev_ if rev_ is not None else "", cost_ if cost_ is not None else "",
                   gp if gp is not None else "",
                   pct(gp, rev_) if gp is not None else "",
                   pct(rev_, ENE[period]) if (rev_ is not None and period in ENE) else "",
                   note])
    r2 += [
        [],
        ["🔴 趋势：关联方销售占能源分部收入 2025 全年 3.37% → 2026H1 7.30% → 2026Q2 单季 10.13%，**占比在快速上升**"],
        [],
        ["【关联方股权投资】"],
        ["项目", "值", "日期", "说明"],
        ["对 xAI 投资协议(原始)", 2000, "2026-01-16",
         "10-K Item 9B + Note 15:认购 xAI **E 轮优先股**;经关联交易政策(RPT Policy)审查;"
         "条款「与该轮其他投资者已获得的市场条款一致,包括价格」;10-K 当时预计按 ASC 321 **成本计量**"],
        ["实际落地为 SpaceX 普通股", 2000, "2026-03",
         "🔑 10-Q Note 13 原文「invested $2.00 billion in **SpaceX common stock "
         "(formerly a preferred share investment in xAI)**」(译:投资 20 亿美元于 SpaceX 普通股,"
         "原为对 xAI 的优先股投资)——**xAI 投资最终转为 SpaceX 持股**,会计处理也随之改变"],
        ["持股比例", "<1%", "2026-03", "10-Q 原文「ownership interest of less than 1%」"],
        ["会计方法", "权益法 + 公允价值选择", "2026Q1 起",
         "⚠️ **持股不足 1% 却「presumed to have significant influence」(推定具有重大影响)→ 用权益法**,"
         "并作公允价值政策选择。与 10-K 原先预计的 ASC 321 成本法**不同**;"
         "这一推定的依据公司未展开说明 ⏳"],
    ]

    with open(os.path.join(HERE, "关联方交易.csv"), "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(r2)

    print(f"── 地区/关联方校验：{nchk} 条，不通过 0")
    print("✅ 地区营收.csv 已写出（年度 2023-2025 + 中期 + 长期资产 + 分部存货 + 官方分部 + 汇率敏感度）")
    print("✅ 关联方交易.csv 已写出（2023-2026H1 + 股权投资）")
    print()
    print(f"🔴 地区结构：其他国际 2023→2025 {(GEO_FY['2025']['其他国际 Other international']/GEO_FY['2023']['其他国际 Other international']-1)*100:+.1f}%"
          f"，而美国 {(GEO_FY['2025']['美国 United States']/GEO_FY['2023']['美国 United States']-1)*100:+.1f}%、"
          f"中国 {(GEO_FY['2025']['中国 China']/GEO_FY['2023']['中国 China']-1)*100:+.1f}% —— 下滑全部集中在其他国际")
    print(f"🔴 2026H1 反转：其他国际 {(GEO_H1['2026H1']['其他国际 Other international']/GEO_H1['2025H1']['其他国际 Other international']-1)*100:+.1f}%"
          f"，贡献了 H1 营收增量的 {inc_oi/(th1-th0)*100:.1f}%")
    print(f"🔴 关联方：能源分部收入中关联方占比 2025 {430/12771*100:.2f}% → 2026H1 {405/5547*100:.2f}% → 2026Q2 {318/3139*100:.2f}%")
    print(f"🔴 汇率：公司自陈 10% 不利变动 = {FX_SENS['2025']} 十亿美元,是 +100bp 利息收益(4.41 亿)的 {1.70e3/441:.1f} 倍")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
