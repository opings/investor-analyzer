#!/usr/bin/env python3
"""运营指标构建器 → 运营指标.csv

指标：活跃商家数 · 每活跃商家交易服务收入（至今按年披露）；
      GMV · 年活跃买家 · Q4 平均月活（FY2018–FY2021 20-F 披露，FY2022 20-F 起停披）。

为什么建：2026-09-15 版 `分析.md` 写「公司不披露 GMV / 月活 / 商家数」「20-F 未披露商家数
（grep 实证无具体计数）」——2026-11-21 回源发现是**假阴性**：20-F 每年都披露活跃商家数，
FY2022 起另披每活跃商家交易服务收入；GMV / 买家 / 月活则是 FY2022 年报起**停止披露**。
「披露黑箱」的准确形态是「主动收窄」，不是「从未披露」。

真源：report/拼多多/<FY>.htm（20-F FY2018–FY2025）正文，**正则抽原句，不手抄**。
口径（FY2025 20-F INTRODUCTION 原文定义）：
  活跃商家 = 期内至少有一单发往买家的**商家账户**（按账户计；退货/退款单也算），
             范围是 "our platforms"（拼多多与 Temu 两个平台合计，未分拆）
  每活跃商家交易服务收入 = 公司自陈（应 ≈ 交易服务收入 ÷ 活跃商家数，见校验 T）
  Q4 平均月活 = 当年 10–12 月三个月的平均月活跃用户

校验（不过不写出）：
  P 探针：每份 20-F 必须命中预期句式——防「正则没对上 = 静默零」
  X 跨年一致：后一年 20-F 里的比较数 = 当年 20-F 原披露（侦测重述）
  T 勾稽：每活跃商家交易服务收入 × 活跃商家数 ≈ 分部营收.csv 交易服务
         （容差 0.5%：商家数只印到 0.1 百万，2021 年 11.5 百万的舍入上限即 0.43%）

运行：只依赖 lxml。`python3 _build_kpi.py [20-F目录] [输出CSV]`——两个可选参数只供变异对照
（把 20-F 副本改坏后指过去跑，不碰本目录 CSV）。
"""
from __future__ import annotations

import csv
import os
import re
import sys

import lxml.html

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT = (sys.argv[1] if len(sys.argv) > 1
          else os.path.abspath(os.path.join(HERE, "..", "..", "..", "report", "拼多多")))
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "运营指标.csv")
FYS = [str(y) for y in range(2018, 2026)]
YEARS = [str(y) for y in range(2017, 2026)]
T_TOL = 0.005

NUM = r"(\d[\d,]*(?:\.\d+)?)"
YLIST = r"((?:\d{4}, )*\d{4},? and \d{4})"

PAT = {
    # FY2018–FY2021："In 2018, our platform had 3.6 million active merchants" / "In 2021, we had 11.5 million active merchants"
    "merchants_a": re.compile(r"In (\d{4}), (?:our platform had|we had) " + NUM + r" million active merchants"),
    # FY2022–FY2025："the number of our active merchants increased from 15.8 million in 2024 to 16.8 million in 2025"
    "merchants_b": re.compile(r"number of our active merchants (?:increased|decreased) from " + NUM
                              + r" million in (\d{4}) to " + NUM + r" million in (\d{4})"),
    "arpu": re.compile(r"Average transaction services revenues per active merchant (?:increased|decreased) from RMB"
                       + NUM + r" in (\d{4}) to RMB" + NUM + r"(?: \(US\$[\d,.]+\))? in (\d{4})"),
    "buyers": re.compile(r"In " + YLIST + r", the number of active buyers on our platform (?:reached|was) "
                         r"((?:[\d.]+ million,? )+and [\d.]+ million)"),
    "gmv": re.compile(r"GMV in " + YLIST + r" was ((?:RMB[\d,.]+ billion(?: \(US\$[\d,.]+ billion\))?,? )+"
                      r"and RMB[\d,.]+ billion)"),
    "mau": re.compile(r"(?:For the three months of October to December of|"
                      r"In the three months ended December 31,) (\d{4}),? the average monthly active users "
                      r"on our platform was " + NUM + r" million"),
}

# P 探针：每份 20-F 必须给出**它自己那一年**的这些指标。只要求「命中某句式 ≥1 次」不够——
# FY2023 年报里商家数有两句（2022→2023、2021→2022），删掉前一句后句式照样命中，
# 2023 年的值会静默改取 FY2024 的比较数（2026-11-21 变异 K3 实测）。
EXPECT = {fy: (["活跃商家", "年活跃买家", "GMV", "Q4月活"] if fy <= "2021" else ["活跃商家", "每商家收入"])
          for fy in FYS}


def f(s):
    return float(s.replace(",", ""))


def years_of(s):
    return re.findall(r"\d{4}", s)


def load_text(fy):
    doc = lxml.html.fromstring(open(os.path.join(REPORT, f"{fy}.htm"), "rb").read())
    for bad in doc.xpath("//script|//style"):
        bad.drop_tree()
    return " ".join(doc.text_content().split())


def annual_row(fn, prefix):
    with open(os.path.join(HERE, fn), encoding="utf-8") as fh:
        rows = list(csv.reader(ln for ln in fh if not ln.startswith("#")))
    hdr = rows[0]
    for r in rows[1:]:
        if r and r[0].startswith(prefix):
            return {y: (float(v) if v.strip() else None) for y, v in zip(hdr[1:], r[1:])}
    raise KeyError(f"{fn} 探针「{prefix}」未找到——表头/科目名可能变了")


def main():
    obs = {k: {} for k in ("活跃商家", "每商家收入", "年活跃买家", "GMV", "Q4月活")}  # 指标 → 年 → [(值, 来源FY)]
    fails, n = [], 0

    def add(metric, yr, val, fy):
        obs[metric].setdefault(yr, []).append((val, fy))

    for fy in FYS:
        text = load_text(fy)
        hit = {k: list(p.finditer(text)) for k, p in PAT.items()}
        for m in hit["merchants_a"]:
            add("活跃商家", m.group(1), f(m.group(2)), fy)
        for m in hit["merchants_b"]:
            add("活跃商家", m.group(2), f(m.group(1)), fy)
            add("活跃商家", m.group(4), f(m.group(3)), fy)
        for m in hit["arpu"]:
            add("每商家收入", m.group(2), f(m.group(1)), fy)
            add("每商家收入", m.group(4), f(m.group(3)), fy)
        for m in hit["buyers"]:
            ys, vs = years_of(m.group(1)), re.findall(r"([\d.]+) million", m.group(2))
            if len(ys) != len(vs):
                fails.append(f"P FY{fy} 年活跃买家年份数 {len(ys)} ≠ 数值数 {len(vs)}")
            for y, v in zip(ys, vs):
                add("年活跃买家", y, f(v), fy)
        for m in hit["gmv"]:
            ys, vs = years_of(m.group(1)), re.findall(r"RMB([\d,.]+) billion", m.group(2))
            if len(ys) != len(vs):
                fails.append(f"P FY{fy} GMV 年份数 {len(ys)} ≠ 数值数 {len(vs)}")
            for y, v in zip(ys, vs):
                add("GMV", y, f(v), fy)
        for m in hit["mau"]:
            add("Q4月活", m.group(1), f(m.group(2)), fy)
        for metric in EXPECT[fy]:
            n += 1
            if not any(src_fy == fy for _, src_fy in obs[metric].get(fy, [])):
                fails.append(f"P FY{fy} 年报未给出当年 {metric}（句式变了或该指标停披）")

    # X 跨年一致 + 取「当年 20-F 当年数」（当年无 20-F 时取最早一份载有该年的 20-F，记来源）
    val, src = {}, {}
    for metric, by_year in obs.items():
        for yr, lst in by_year.items():
            n += 1
            if len({v for v, _ in lst}) > 1:
                fails.append(f"X {metric} {yr}: 各份 20-F 给值不一 {lst}")
            own = [v for v, fy in lst if fy == yr]
            pick = own[0] if own else sorted(lst, key=lambda t: t[1])[0][0]
            val[(metric, yr)] = pick
            src[(metric, yr)] = f"FY{yr}" if own else f"FY{sorted(lst, key=lambda t: t[1])[0][1]}比较数"

    # T 勾稽：每商家收入 × 商家数 ≈ 交易服务收入
    ts = annual_row("分部营收.csv", "交易服务")
    rev = annual_row("利润表.csv", "收益合计")
    t_ratio = {}
    for yr in YEARS:
        a, m_ = val.get(("每商家收入", yr)), val.get(("活跃商家", yr))
        if a is None or m_ is None or not ts.get(yr):
            continue
        n += 1
        implied = a * m_ * 1e6 / 1000  # 千元
        t_ratio[yr] = implied / ts[yr] * 100
        if abs(implied / ts[yr] - 1) > T_TOL:
            fails.append(f"T {yr}: 每商家收入×商家数 {implied:,.0f} vs 交易服务 {ts[yr]:,.0f} 千元 "
                         f"(偏差 {implied / ts[yr] * 100 - 100:+.2f}%)")

    print(f"校验 {n} 式，未通过 {len(fails)} 式")
    for x in fails:
        print("  ❌", x)
    if fails:
        print("🛑 不写出 运营指标.csv")
        return 1

    def row(name, metric, fmt):
        return [name] + [("" if (metric, y) not in val else fmt(val[(metric, y)])) for y in YEARS]

    def srow(name, metric):
        return [name] + [src.get((metric, y), "") for y in YEARS]

    take = [""] * len(YEARS)
    for i, y in enumerate(YEARS):
        g = val.get(("GMV", y))
        if g and rev.get(y):
            take[i] = f"{rev[y] * 1000 / (g * 1e9) * 100:.2f}"

    out = [
        ["# 单位:见各行;来源:20-F FY2018-FY2025 正文原句正则抽取(report/拼多多/<FY>.htm);生成器 _build_kpi.py"],
        ["# 口径:活跃商家=期内至少一单发往买家的商家账户(按账户计·含退货退款单·拼多多+Temu 合计未分拆);"
         "Q4月活=当年10-12月平均月活"],
        ["# 🔴 GMV/年活跃买家/Q4月活:FY2018-FY2021 20-F 披露,FY2022 20-F 起停披;活跃商家与每商家交易服务收入至今按年披露"],
        ["# 取数:当年 20-F 当年数;2017 年(无 20-F)取 FY2018 20-F 比较数;各份 20-F 互为比较数处逐一核过一致(校验 X)"],
        ["指标"] + YEARS,
        row("活跃商家数(百万·账户口径)", "活跃商家", lambda v: f"{v:.1f}"),
        row("每活跃商家交易服务收入(元)", "每商家收入", lambda v: f"{v:.0f}"),
        row("年活跃买家(百万)", "年活跃买家", lambda v: f"{v:.1f}"),
        row("GMV(十亿元)", "GMV", lambda v: f"{v:.1f}"),
        row("Q4平均月活(百万)", "Q4月活", lambda v: f"{v:.1f}"),
        ["派生:营收÷GMV(%)·货币化率"] + take,
        ["派生:每商家收入×商家数÷交易服务收入(%)·校验T"]
        + [("" if y not in t_ratio else f"{t_ratio[y]:.2f}") for y in YEARS],
        srow("_来源:活跃商家", "活跃商家"),
        srow("_来源:每商家收入", "每商家收入"),
        srow("_来源:年活跃买家", "年活跃买家"),
        srow("_来源:GMV", "GMV"),
        srow("_来源:Q4月活", "Q4月活"),
    ]
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        for r in out:
            if len(r) == 1 and r[0].startswith("#"):
                fh.write(r[0] + "\n")
            else:
                w.writerow(r)
    print(f"✅ 运营指标.csv 已写出（{YEARS[0]}–{YEARS[-1]}）")
    for y in YEARS:
        print(f"   {y}: 商家 {val.get(('活跃商家', y), '—')}  每商家 {val.get(('每商家收入', y), '—')}  "
              f"买家 {val.get(('年活跃买家', y), '—')}  GMV {val.get(('GMV', y), '—')}  "
              f"月活 {val.get(('Q4月活', y), '—')}  T={t_ratio.get(y, '—')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
