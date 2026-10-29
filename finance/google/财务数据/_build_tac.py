#!/usr/bin/env python3
"""google TAC(流量获取成本)构建器 → TAC流量获取成本.csv

TAC = 付给分销伙伴(浏览器/手机厂商/运营商的默认搜索入口,如 Apple)与联盟网络伙伴(第三方网站)的分成,计入营业成本。
它是 Google 的「获客成本」(行业块:获客成本 vs 用户增长),也是美国搜索案救济(独家默认协议)直接作用的科目。

真源:各年自家 10-K MD&A「Cost of revenues」表本年列(as-reported);2026 取 2026Q2 / Q3 10-Q。单位:百万美元。
  2012–2013 为 Google 分部口径(当年营业成本按 Google / Motorola Mobile 分列,TAC 只属 Google 分部);
  FY2016–FY2018 10-K 另列「TAC to distribution partners」,FY2019 起不再按伙伴类型拆分 → 本表只列总额。

校验(任一不过 → 不写出):
  T1 TAC + 其他营业成本 = 营业成本合计(2014–2025、Q2/H1/Q3/9M 2026)
  T2 营业成本合计 = 利润表.csv「销售成本」(年度)/ 中期财务-2026.csv「营业成本」(中期)
  T3 TAC 率(本表算 = TAC ÷ 广告收入)与公司披露的 TAC rate 一致(一位小数披露容差 0.06pp;整数披露容差 0.6pp)
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "TAC流量获取成本.csv")

# 期: (TAC, 其他营业成本, 营业成本合计)  —— 各年自家 10-K 本年列;2012-2013 其他/合计不适用(分部口径)
TAC = {
    "2012": (10956, None, None), "2013": (12258, None, None),
    "2014": (13497, 12194, 25691), "2015": (14343, 13821, 28164), "2016": (16793, 18345, 35138),
    "2017": (21672, 23911, 45583), "2018": (26726, 32823, 59549), "2019": (30089, 41807, 71896),
    "2020": (32778, 51954, 84732), "2021": (45566, 65373, 110939), "2022": (48955, 77248, 126203),
    "2023": (50886, 82446, 133332), "2024": (54900, 91406, 146306), "2025": (59926, 102609, 162535),
    "Q2 2025": (14705, 24334, 39039), "Q2 2026": (16179, 29764, 45943),
    "H1 2025": (28453, 46947, 75400), "H1 2026": (31407, 55807, 87214),
    "Q3 2025": (14876, 26493, 41369), "Q3 2026": (16366, 35053, 51419),
    "9M 2025": (43329, 73439, 116768), "9M 2026": (47773, 90860, 138633),
}
# 公司披露的 TAC rate(%·各期自家申报原文;精度 = 小数位数)
DISCLOSED = {
    "2012": (25.1, 1), "2013": (24.2, 1),          # 2013 原文分母为「Google 分部广告收入」
    "2017": (23, 0), "2018": (23, 0), "2019": (22.3, 1), "2020": (22.3, 1), "2021": (21.8, 1),
    "2022": (21.8, 1), "2023": (21.4, 1), "2024": (20.7, 1), "Q2 2025": (20.6, 1), "Q2 2026": (19.8, 1),
    # Q2 10-Q 原文「from 20.6% to 19.8% from the three and six months」→ H1 两期与 Q2 同值
    "H1 2025": (20.6, 1), "H1 2026": (19.8, 1),
    "Q3 2025": (20.1, 1), "Q3 2026": (20.0, 1), "9M 2025": (20.4, 1), "9M 2026": (19.8, 1),
}
# 中期广告收入(2026Q2 / Q3 10-Q Note 2:Search & other + YouTube ads + Network)
AD_INTERIM = {"Q2 2025": 54190 + 9796 + 7354, "Q2 2026": 63271 + 11055 + 7303,
              "H1 2025": 104892 + 18723 + 14610, "H1 2026": 123670 + 20938 + 14274,
              "Q3 2025": 56567 + 10261 + 7354, "Q3 2026": 63350 + 11207 + 7455,
              "9M 2025": 161459 + 28984 + 21964, "9M 2026": 187020 + 32145 + 21729}
INTERIM = tuple(AD_INTERIM)

FAIL = []


def chk(tag, resid, tol):
    if abs(resid) > tol:
        FAIL.append(f"{tag}: 残差 {resid:.3f}")


def read_row(fn, prefix):
    with open(os.path.join(HERE, fn), encoding="utf-8") as f:
        rr = list(csv.reader(f))
    for i, r in enumerate(rr):
        if r and r[0].startswith(prefix):
            for j in range(i, -1, -1):           # 向上找最近的表头行(首格为「科目」或以【开头的段表头)
                if rr[j] and (rr[j][0] == "科目" or rr[j][0].startswith("【")):
                    return dict(zip(rr[j][1:], r[1:]))
    return None


cor_annual = read_row("利润表.csv", "销售成本 Cost of revenues")
ad_annual = read_row("分部营收.csv", "=广告合计")
cor_mid = read_row("中期财务-2026.csv", "营业成本")
for nm, d, need in (("利润表.csv 销售成本", cor_annual, [str(y) for y in range(2014, 2026)]),
                    ("分部营收.csv 广告合计", ad_annual, [str(y) for y in range(2017, 2026)]),
                    ("中期财务-2026.csv 营业成本", cor_mid, list(INTERIM))):
    if d is None:
        FAIL.append(f"链式读取失败:{nm} 行找不到")
    else:
        miss = [k for k in need if not d.get(k)]
        if miss:
            FAIL.append(f"链式读取缺值:{nm} 缺 {miss}")

rate = {}
for p, (tac, other, total) in TAC.items():
    if other is not None:
        chk(f"{p} T1 TAC+其他=合计", tac + other - total, 0.5)
        src = cor_mid if p in INTERIM else cor_annual
        if src and src.get(p):
            chk(f"{p} T2 合计=利润表营业成本", total - abs(float(src[p])), 0.5)
    ad = AD_INTERIM.get(p) or (float(ad_annual[p]) if ad_annual and ad_annual.get(p) else None)
    if ad:
        rate[p] = tac / ad * 100
for p, (v, dp) in DISCLOSED.items():
    if p in rate:
        chk(f"{p} T3 TAC率 本表{rate[p]:.2f}% vs 披露{v}%", rate[p] - v, 0.06 if dp == 1 else 0.6)

print(f"TAC 校验:不通过 {len(FAIL)}")
if FAIL:
    for x in FAIL:
        print("  🔴", x)
    if "--force" not in sys.argv:
        print("不写出 TAC流量获取成本.csv")
        sys.exit(1)

cols = list(TAC)
with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["# 单位: 百万美元(TAC率=%); 真源: 各年自家 10-K MD&A「Cost of revenues」表本年列 + 2026Q2 / Q3 10-Q; "
                "TAC=付给分销伙伴(默认搜索入口)与联盟网络伙伴的分成,计入营业成本; 2012-2013 为 Google 分部口径; "
                "TAC率=TAC÷广告收入(2017 起由本表按 分部营收.csv 算,并与公司披露值逐期互核,见 _build_tac.py T3)"])
    w.writerow(["科目"] + cols)
    w.writerow(["TAC 流量获取成本 Traffic acquisition costs"] + [str(TAC[c][0]) for c in cols])
    w.writerow(["其他营业成本 Other cost of revenues"] + [str(TAC[c][1]) if TAC[c][1] is not None else "" for c in cols])
    w.writerow(["=营业成本合计 Total cost of revenues"] + [str(TAC[c][2]) if TAC[c][2] is not None else "" for c in cols])
    w.writerow(["TAC率(本表算·TAC÷广告收入) TAC rate computed %"] + [f"{rate[c]:.2f}" if c in rate else "" for c in cols])
    w.writerow(["TAC率(公司披露) TAC rate disclosed %"] + [str(DISCLOSED[c][0]) if c in DISCLOSED else "" for c in cols])
    w.writerow(["TAC ÷ 营业成本合计 %"] + [f"{TAC[c][0] / TAC[c][2] * 100:.2f}" if TAC[c][2] else "" for c in cols])
print("✅ 已写出 TAC流量获取成本.csv")
