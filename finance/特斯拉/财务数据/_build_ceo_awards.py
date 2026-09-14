#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CEO 薪酬与里程碑构建器 → CEO薪酬与里程碑.csv

为什么要有这张表：
  跟踪变量 9 的 A1 信号（「里程碑首次判定为 probable」）是本库定义的**最硬的下一轮增长启动判据**
  —— 有审计、有费用后果、公司无自由裁量。但在本表建立之前，这组数据**只活在 prose 里**：
  里程碑清单、授予股数、调整后 EBITDA、累计交付全部无 CSV 落点，既无法校验也无从逐季更新。
  另：调整后 EBITDA 是**派生指标**，按铁律必须回流 财务数据/。

数据来源（全部一手）：
  · 2026Q2 10-Q（acc 0001628280-26-049270）Note 9 "Equity Incentive Plans" —— 12 个运营里程碑全表、
    Adjusted EBITDA 定义、probable 判定、已/未确认 SBC、确认期
  · 2026Q2 10-Q Note 3 "Acquisition" —— 2026Q2 AI 硬件公司资产收购
  · 2026Q2 10-Q / FY2025 10-K 封面页 —— 在外股本（⚠️ 封面日口径，非期末）
  · 利润表.csv / 现金流量表.csv / 经营指标.csv / 单位经济-汽车.csv —— 调整后 EBITDA 与累计交付派生

⚠️ 金额为手工转录 10-Q 附注叙述，每季更新前须人工 grep 复核（关键词见 KEYWORDS）。
"""
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "CEO薪酬与里程碑.csv")

KEYWORDS = ("operational milestones generally required / considered probable of achievement / "
            "unrecognized stock-based compensation expense / shares of the registrant's common stock outstanding")

# ── 12 个运营里程碑（2026Q2 10-Q Note 9 原表逐行转录）──────────────────────────
# (编号, 类别, 门槛描述, 门槛数值, 单位)
MILESTONES = [
    (1,  "产品/交付", "20 million Tesla vehicles delivered",      20_000_000, "辆"),
    (2,  "产品/软件", "10 million active FSD subscriptions",      10_000_000, "个活跃订阅"),
    (3,  "产品/机器人", "1 million bots delivered",                1_000_000, "台"),
    (4,  "产品/Robotaxi", "1 million Robotaxis in commercial operation", 1_000_000, "台"),
    (5,  "财务", "$50 billion of Adjusted EBITDA",                50_000, "百万美元"),
    (6,  "财务", "$80 billion of Adjusted EBITDA",                80_000, "百万美元"),
    (7,  "财务", "$130 billion of Adjusted EBITDA",              130_000, "百万美元"),
    (8,  "财务", "$210 billion of Adjusted EBITDA",              210_000, "百万美元"),
    (9,  "财务", "$300 billion of Adjusted EBITDA",              300_000, "百万美元"),
    (10, "财务", "$400 billion of Adjusted EBITDA(需三个不重叠期间)", 400_000, "百万美元"),
    (11, "财务", "$400 billion of Adjusted EBITDA(需三个不重叠期间)", 400_000, "百万美元"),
    (12, "财务", "$400 billion of Adjusted EBITDA(需三个不重叠期间)", 400_000, "百万美元"),
]

# 截至 2026-06-30 的 probable 判定（10-Q 原文：只有 #1 被判 probable）
PROBABLE_20260630 = {1: "probable"}

# 本库可核验的当前读数（None = 公司零量化披露 ⏳）
CURRENT_READING = {
    1: ("累计交付(本库可核验下限)", None),   # 运行时派生
    2: (None, None), 3: (None, None), 4: (None, None),
}


def load(fn):
    with open(os.path.join(HERE, fn), encoding="utf-8") as f:
        return [r for r in csv.reader(f)]


def ymap(rows):
    for r in rows:
        if r and r[0].strip() in ("科目", "指标"):
            return {c.strip(): i for i, c in enumerate(r) if c.strip()}
    return {}


def num(rows, m, key, y):
    for r in rows:
        if r and key in r[0]:
            if y in m and m[y] < len(r):
                s = r[m[y]].strip().replace(",", "")
                if s:
                    try:
                        return float(s)
                    except ValueError:
                        return None
    return None


def main():
    inc, cf, met = load("利润表.csv"), load("现金流量表.csv"), load("经营指标.csv")
    ue = load("单位经济-汽车.csv")
    mi, mc, mm = ymap(inc), ymap(cf), ymap(met)

    # 探针自检：上游注释行数变了会导致表头行号漂移（本库踩过的坑）
    for nm, rows, m, probe in (("利润表.csv", inc, mi, "归母净利润"),
                               ("现金流量表.csv", cf, mc, "数字资产损益"),
                               ("经营指标.csv", met, mm, "整车交付量-合计")):
        if not m or not any(probe in r[0] for r in rows if r):
            print(f"❌ {nm} 表头/探针行「{probe}」未找到——注释行数可能变了")
            return 1

    errs, nchk = [], 0

    # ── 调整后 EBITDA（10-Q Note 9 官方定义）────────────────────────────────
    # = 归母净利 + 利息费用 + 所得税 + 折旧摊销及减值 + 股份支付 + 数字资产损益
    # ⚠️ 官方口径是「紧邻判定日的连续四个季度(TTM)」；本表按**财政年度**计算，
    #    只在 12-31 判定日与 TTM 一致，年中判定日会不同。
    ebitda = {}
    years = [y for y in sorted(mi, key=lambda x: (not x.isdigit(), x)) if y.isdigit()]
    for y in years:
        ni = num(inc, mi, "归母净利润", y)
        ie = num(inc, mi, "利息费用 Interest expense", y)
        tax = num(inc, mi, "所得税 Provision", y)
        da = num(inc, mi, "备忘-折旧摊销及减值", y)
        sbc = num(inc, mi, "备忘-股份支付", y)
        dig = num(cf, mc, "数字资产损益", y)
        if ni is None or da is None or sbc is None:
            continue
        # 利息费用/所得税在库内按「费用=负数」存储 → 加回取绝对值
        v = ni + abs(ie or 0) + abs(tax or 0) + da + sbc + (dig or 0)
        ebitda[y] = v
        nchk += 1
        if da < 0 or sbc < 0:
            errs.append(f"[{y}] D&A/SBC 备忘行应为正数（取自现金流加回项）")

    # 复核锚点：FY2025 应约等于 145–147 亿美元（10-Q 口径交叉验）
    nchk += 1
    if "2025" in ebitda and not (14_000_000 <= ebitda["2025"] <= 15_200_000):
        errs.append(f"FY2025 调整后 EBITDA {ebitda['2025']:,.0f} 千美元 超出 140–152 亿区间，请回查口径")

    # ── 累计交付（本库可核验下限）──────────────────────────────────────────
    dv, missing_yrs = {}, []
    for y in [c for c in mm if c.isdigit()]:
        v = num(met, mm, "整车交付量-合计", y)
        if v is None:
            missing_yrs.append(y)
        else:
            dv[y] = v
    h1_2026 = None
    for r in ue:
        if r and r[0].strip() == "交付量(辆)":
            hdr = next(x for x in ue if x and x[0].strip() == "指标")
            j = {c.strip(): i for i, c in enumerate(hdr)}
            if "2026H1" in j and j["2026H1"] < len(r):
                h1_2026 = float(r[j["2026H1"]])
    cum = sum(dv.values()) + (h1_2026 or 0)
    nchk += 1
    if h1_2026 is None:
        errs.append("单位经济-汽车.csv 未取到 2026H1 交付量")

    gap = MILESTONES[0][3] - cum

    # ── 写出 ──────────────────────────────────────────────────────────────
    rows = [
        ["单位:股数为股;金额为千美元(USD thousands);交付量为辆。空=一手申报无此披露"],
        ["来源:2026Q2 10-Q(acc 0001628280-26-049270) Note 9 Equity Incentive Plans / Note 3 Acquisition;"
         "在外股本取 10-K/10-Q **封面页**;调整后 EBITDA 与累计交付由本库三表+经营指标派生"],
        [f"⚠️ 手工转录附注叙述,每季更新前人工 grep 复核关键词(⚠️**检索串须用英文原文搜,勿译后搜**):{KEYWORDS}"],
        ["   上述四个检索串字面义依次为:「一般需达成的运营里程碑」/「被认定为很可能达成」/"
         "「未确认的股份支付费用」/「注册人在外流通普通股股数」"],
        ["🔴 调整后 EBITDA 官方定义(10-Q 原文):归母净利 **before** 利息费用/所得税/折旧摊销及减值/股份支付/数字资产损益,"
         "且取**紧邻判定日的连续四个季度(TTM)**。本表按财政年度算,仅在 12-31 判定日与 TTM 一致"],
        [],
        ["【A · 2025 CEO Performance Award 的 12 个运营里程碑】(每个 tranche 需同时达成「市值里程碑」+「任一运营里程碑」)"],
        ["里程碑#", "类别", "门槛(10-Q 原文)", "门槛数值", "单位",
         "probable判定@2026-06-30", "本库可核验当前读数", "缺口/说明"],
    ]
    for n, cat, desc, thr, unit in MILESTONES:
        prob = PROBABLE_20260630.get(n, "not probable")
        if n == 1:
            reading = f"{cum:.0f}"
            note = f"距门槛尚缺约 {gap:,.0f} 辆;⚠️本读数为**下限**——2017 年及 2016 年前交付量不在本库 ⏳"
        elif n == 5:
            reading = f"{ebitda.get('2025', 0) / 1000:.0f}" if ebitda.get("2025") else ""
            note = ("🔑 **最低的一档财务里程碑**:需 FY2025 水平的 %.1f 倍。"
                    "⚠️ 该指标已连跌两年(2023 峰值 %.0f → 2025 %.0f 百万美元,-%.0f%%),方向与门槛相反"
                    % (thr / (ebitda["2025"] / 1000), ebitda["2023"] / 1000, ebitda["2025"] / 1000,
                       (1 - ebitda["2025"] / ebitda["2023"]) * 100)
                    if ebitda.get("2025") and ebitda.get("2023") else "")
        elif cat == "财务":
            reading = f"{ebitda.get('2025', 0) / 1000:.0f}" if ebitda.get("2025") else ""
            note = ("需 FY2025 水平的 %.1f 倍" % (thr / (ebitda["2025"] / 1000))) if ebitda.get("2025") else ""
        else:
            reading = ""
            note = "🔴 公司**零量化披露** ⏳ —— 该里程碑无任何可核验进度读数"
        rows.append([n, cat, desc, thr, unit, prob, reading, note])

    rows += [
        [],
        ["【B · 奖励本体与股本】"],
        ["项目", "值", "日期/期间", "来源与说明"],
        ["2025 CEO Performance Award 授予股数", 423_700_000, "2025-09-03 授予",
         "10-Q 附注 9 原文「approximately 423.7 million shares of performance-based restricted stock」"
         "(译:约 4.237 亿股业绩型限制性股票);2025-11-06 股东批准=**会计授予日**"],
        ["├ 分 tranche 数", 12, "—", "每个 tranche = 市值里程碑 + 任一运营里程碑"],
        ["├ 已确认 SBC(2026Q2 单季)", 267_000, "2026Q2", "计入销售及行政费用(SG&A)"],
        ["├ 已确认 SBC(2026H1)", 527_000, "2026H1",
         "⚠️ 同期公司**全部** SBC 为 2,181,000 千美元 → 该奖励只解释其中约 24%,"
         "勿把 H1 股份支付同比 +80.5% 整体归因于 CEO 薪酬方案"],
        ["├ 未确认 SBC(已判 probable 部分)", 9_820_000, "截至 2026-06-30", "预计在约 **9.2 年**内确认"],
        ["├ 未确认 SBC(未判 probable 部分·下限)", 105_820_000, "截至 2026-06-30", "区间下限"],
        ["├ 未确认 SBC(未判 probable 部分·上限)", 120_370_000, "截至 2026-06-30", "区间上限"],
        ["└ 确认期", None, "约 7.5 或 10 年", "自 2025 CEO Performance Award **会计**授予日起算"],
        ["", "", "", ""],
        ["🔴 2025 CEO Interim Award 授予股数", 96_000_000, "2025-08-03 授予",
         "**已于 2026-04-21 全部作废(forfeited)**"],
        ["└ 作废原因", None, "2026-04-21 董事会认定",
         "特拉华最高法院推翻 Chancery 撤销令、**恢复 2018 CEO Performance Award**(2026-03-18 Chancery 最终命令)"
         "→ 构成 Tornetta Decision Event → 依「no double dip」原则立即作废。"
         "⚠️ 作废前**从未确认任何 SBC**"],
        ["", "", "", ""],
        ["2018 CEO Performance Award 本季行权期权数", 304_000_000, "2026Q2",
         "净额结算抵扣行权价约 17,500,000 股;授予日公允价值此前已全部确认→无增量 SBC"],
        ["└ 净额结算股数", 17_500_000, "2026Q2", "同上"],
        ["", "", "", ""],
        ["在外股本(shares outstanding)", 3_752_431_984, "截至 **2026-01-23**",
         "FY2025 10-K **封面页**。⚠️ 封面日口径 ≠ 2025-12-31 期末口径"],
        ["在外股本(shares outstanding)", 3_949_547_394, "截至 **2026-07-16**",
         "2026Q2 10-Q **封面页**。⚠️ 封面日口径 ≠ 2026-06-30 期末口径。"
         f"两个封面日之间增加 {3_949_547_394 - 3_752_431_984:,} 股"],
        ["", "", "", ""],
        ["🟡 AI 硬件公司资产收购(对价)", 1_950_000, "2026Q2",
         "10-Q Note 3:以 **Tesla 普通股与股权奖励**支付;其中 1,730,000 千美元附服务/业绩条件"
         "(取决于技术能否成功部署)、222,000 千美元分配至专利及已开发技术无形资产。"
         "⚠️ 2026Q2 未确认相关 SBC——业绩条件被判定为 **improbable**。公司未披露标的名称"],
        [],
        ["【C · 调整后 EBITDA 年度序列(按官方定义派生·财政年度口径)】"],
        ["年份"] + [y for y in years if y in ebitda],
        ["调整后 EBITDA(千美元)"] + [f"{ebitda[y]:.0f}" for y in years if y in ebitda],
        ["距里程碑#5($500亿)倍数"] + [f"{50_000_000 / ebitda[y]:.2f}" if ebitda[y] > 0 else ""
                                  for y in years if y in ebitda],
    ]

    print(f"── CEO薪酬与里程碑校验：{nchk} 条，不通过 {len(errs)}")
    for e in errs:
        print("   ✗", e)
    if errs:
        return 1

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)

    print(f"✅ CEO薪酬与里程碑.csv 已写出（12 个里程碑 + 奖励本体 + 调整后 EBITDA {len(ebitda)} 年）")
    print(f"   FY2025 调整后 EBITDA = {ebitda['2025']:,.0f} 千美元（约 {ebitda['2025'] / 100000:.1f} 亿美元）"
          f"；里程碑#5 需其 {50_000_000 / ebitda['2025']:.1f} 倍")
    print(f"   累计交付(本库可核验下限) = {cum:,.0f} 辆；距 2,000 万辆尚缺 {gap:,.0f} 辆")
    if missing_yrs:
        print(f"   ⏳ 交付量缺年：{'/'.join(sorted(missing_yrs))}（故累计为下限，非全量）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
