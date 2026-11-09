#!/usr/bin/env python3
"""NVIDIA 比率层 → `财务比率.csv` = 通用底（`scripts/derived.py`，不改共享脚本，在此做内存别名适配）+ 定制层。

读上游 CSV（构建器读构建器产物）→ 探针行 + 必需值完整性自检（记忆 chained-builder-silent-truncation）。

## 拆股复权因子：从数据自证，再与公司自陈逐次对账（多一次、少一次都失败）
拿「后一份申报比较列印的同一财年基本股数 ÷ 该财年 as-reported 基本股数」，比值落在 1 / 1.5 / 2 / 4 / 10 附近即判定倍数
（数据来自 `重述与口径变更.csv` 的「基本股数」行）。公司自陈拆股：2000-06 一拆二、2001-09 一拆二、2006-04 一拆二、
2007-09 三拆二、2021-07 一拆四、2024-06 一拆十（FY2001 / FY2002 / FY2007 / FY2008 / FY2022 / FY2025 各份 10-K 股东权益附注）。
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import derived  # noqa: E402

# 公司自陈的拆股（申报对：前一份 → 后一份）与倍数
STATED_SPLITS = {("2000", "2001"): 2.0, ("2001", "2002"): 2.0, ("2006", "2007"): 2.0,
                 ("2007", "2008"): 1.5, ("2021", "2022"): 4.0, ("2024", "2025"): 10.0}


def read(fn, probe):
    rows = list(csv.reader(open(os.path.join(HERE, fn))))
    hdr = next((i for i, r in enumerate(rows) if r and r[0] == "科目"), None)
    if hdr is None:
        raise SystemExit(f"❌ {fn} 找不到表头行")
    years = [h[2:] for h in rows[hdr][1:]]
    data = {}
    for r in rows[hdr + 1:]:
        if not r or r[0] == "数据来源":
            continue
        data[r[0]] = [float(v) if v not in ("",) else None for v in r[1:1 + len(years)]]
    if probe not in data:
        raise SystemExit(f"❌ {fn} 探针行「{probe}」找不到——上游行名变了")
    return years, data


def main():
    yI, I = read("利润表.csv", "营业收入 Revenue")
    yB, B = read("资产负债表.csv", "总资产 Total assets")
    yC, C = read("现金流量表.csv", "经营活动现金流净额 Net cash from operating activities")
    if not (yI == yB == yC):
        raise SystemExit("❌ 三表年份列不一致")
    Y = yI
    N = len(Y)
    # —— 通用底：内存别名适配（不改 scripts/derived.py）
    PL = dict(I)
    PL["归属于母公司股东的净利润(=净利润·无少数股东)"] = I["净利润 Net income"]
    PL["所得税费用"] = I["所得税 Income tax expense (benefit)"]
    PL["管理费用(=SG&A合并)"] = I["销售、一般及管理费用 Sales, general and administrative"]
    BS = dict(B)
    BS["资产总计"] = B["总资产 Total assets"]
    BS["交易性金融资产(=有价证券)"] = B["有价证券 Marketable securities"]
    CF = dict(C)
    CF["capex"] = C["资本开支(购置固定资产及无形资产) Purchases of property and equipment and intangible assets"]
    CF["已付股息"] = C.get("支付股息 Dividends paid", [None] * N)
    common, unmatched = derived.compute_common_ratios(PL, BS, CF)
    rows = []
    for name, vals, fmt in common:
        if name.startswith("销售费用率"):
            continue                                   # NVIDIA 只印 SG&A 合并行，单列销售费用率无意义
        if name.startswith("管理/行政费用率"):
            name = "销售及一般管理费用率(SG&A合并) SG&A ratio"
        if name.startswith("扣非净利率"):
            continue                                   # 美股无扣非口径
        rows.append((name, vals))
    g = lambda d, k, i: (d.get(k) or [None] * N)[i]

    def div(a, b):
        return None if a is None or b in (None, 0) else a / b

    R_, OI, NI, PBT, TAX = ("营业收入 Revenue", "营业利润 Operating income", "净利润 Net income",
                            "税前利润 Income before income tax", "所得税 Income tax expense (benefit)")
    OCF = "经营活动现金流净额 Net cash from operating activities"
    CAPEX = "资本开支(购置固定资产及无形资产) Purchases of property and equipment and intangible assets"
    SBC = "股权激励费用 Stock-based compensation"
    BUY, DIV, RSU = "回购普通股 Repurchases of common stock", "支付股息 Dividends paid", \
        "RSU 代扣个税 Payments related to employee stock plan taxes"
    # —— 定制层
    rows.append(("营业利润率 Operating margin", [div(g(I, OI, i), g(I, R_, i)) for i in range(N)]))
    rows.append(("有效税率 Effective tax rate", [div(g(I, TAX, i), g(I, PBT, i)) for i in range(N)]))
    rows.append(("营收增速(as-reported相邻两年·跨FY1997→FY1999为13个月间隔) Revenue growth",
                 [None] + [div(g(I, R_, i), g(I, R_, i - 1)) - 1 if div(g(I, R_, i), g(I, R_, i - 1)) is not None else None
                           for i in range(1, N)]))
    fcf = [None if g(C, OCF, i) is None or g(C, CAPEX, i) is None else g(C, OCF, i) + g(C, CAPEX, i) for i in range(N)]
    rows.append(("自由现金流(经营−资本开支·百万美元) FCF", fcf))
    rows.append(("FCF/净利 FCF/Net income", [div(fcf[i], g(I, NI, i)) for i in range(N)]))
    rows.append(("股权激励/营收 SBC/Revenue", [div(g(C, SBC, i), g(I, R_, i)) for i in range(N)]))
    rows.append(("FCF−股权激励(百万美元) FCF minus SBC",
                 [None if fcf[i] is None or g(C, SBC, i) is None else fcf[i] - g(C, SBC, i) for i in range(N)]))
    sh = [None if g(C, BUY, i) is None and g(C, DIV, i) is None else -((g(C, BUY, i) or 0) + (g(C, DIV, i) or 0)) for i in range(N)]
    rows.append(("回购+分红现金支出(百万美元) Buybacks+dividends paid", sh))
    rows.append(("(回购+分红)/FCF Shareholder payout/FCF", [div(sh[i], fcf[i]) for i in range(N)]))
    rows.append(("RSU代扣个税/(回购+分红) RSU tax/(buyback+div)",
                 [div(-(g(C, RSU, i) or 0), sh[i]) if g(C, RSU, i) is not None else None for i in range(N)]))
    # 股东回报画像（累计·上市后 FY1999 起）：给出去的（回购+分红+RSU 代扣个税回购）vs 拿进来的（IPO/增发 + 员工股票计划）
    ISSUE = ["员工股票计划所得 Proceeds related to employee stock plans",
             "公开发行股票所得(仅FY1999-2003) Sale of common stock under public offering"]
    cum_out, cum_in, co, ci = [], [], 0.0, 0.0
    for i in range(N):
        if int(Y[i]) >= 1999:
            co += -((g(C, BUY, i) or 0) + (g(C, DIV, i) or 0))
            ci += sum(g(C, k, i) or 0 for k in ISSUE)
        cum_out.append(co if int(Y[i]) >= 1999 else None)
        cum_in.append(ci if int(Y[i]) >= 1999 else None)
    rows.append(("累计回购+分红现金(FY1999起·百万美元) Cumulative buybacks+dividends", cum_out))
    rows.append(("累计股票发行所得(IPO/增发+员工计划·FY1999起·百万美元) Cumulative equity issuance", cum_in))
    cum_rsu, cr = [], 0.0
    for i in range(N):
        if int(Y[i]) >= 1999:
            cr += -(g(C, RSU, i) or 0)
        cum_rsu.append(cr if int(Y[i]) >= 1999 else None)
    rows.append(("累计 RSU 代扣个税(FY1999起·百万美元) Cumulative RSU tax withholding", cum_rsu))
    debt = [sum(x for x in (g(B, "长期债务 Long-term debt", i), g(B, "短期债务(FY2021起) Short-term debt", i),
                            g(B, "可转债-流动(FY2016-2019) Convertible short-term debt", i),
                            g(B, "可转债-非流动(仅FY2016) Convertible long-term debt", i)) if x is not None) for i in range(N)]
    cashmk = [None if g(B, "现金及现金等价物 Cash and cash equivalents", i) is None else
              g(B, "现金及现金等价物 Cash and cash equivalents", i) + (g(B, "有价证券 Marketable securities", i) or 0)
              for i in range(N)]
    rows.append(("现金及有价证券(百万美元) Cash+marketable securities", cashmk))
    rows.append(("有息债务(不含租赁·百万美元) Debt excl. leases", [d if d else None for d in debt]))
    rows.append(("净现金(现金及有价证券−有息债务) Net cash", [None if cashmk[i] is None else cashmk[i] - debt[i] for i in range(N)]))
    rows.append(("资本开支/营收 Capex/Revenue", [div(-g(C, CAPEX, i) if g(C, CAPEX, i) is not None else None, g(I, R_, i)) for i in range(N)]))
    rows.append(("资本开支/折旧摊销 Capex/D&A", [div(-g(C, CAPEX, i) if g(C, CAPEX, i) is not None else None,
                                                g(C, "折旧及摊销 Depreciation and amortization", i)) for i in range(N)]))
    gains = "投资损益(收益为负) (Gains) losses on investments"
    rows.append(("投资收益/税前利润 Investment gains/PBT", [div(-g(C, gains, i) if g(C, gains, i) is not None else None, g(I, PBT, i))
                                                       for i in range(N)]))
    # —— 承诺/营收（读附注产物·探针）
    cy, Cm = read("采购与云服务承诺.csv", "存货采购及长期供应与产能义务 Inventory purchase / supply & capacity obligations")
    supply = Cm["存货采购及长期供应与产能义务 Inventory purchase / supply & capacity obligations"]
    sup = {y: v for y, v in zip(cy, supply)}
    rows.append(("存货采购及供应产能义务/营收 Supply obligations/Revenue", [div(sup.get(Y[i]), g(I, R_, i)) for i in range(N)]))
    # —— 拆股链自证
    led = list(csv.reader(open(os.path.join(HERE, "重述与口径变更.csv"))))
    shares = {}
    for r in led:
        if len(r) >= 6 and r[1].startswith("基本股数") and r[0] == "IS":
            per, asrep, oth, src = r[2], float(r[3]), float(r[4]), r[5]
            nxt = src.lstrip("LR")
            if per.isdigit() and nxt.isdigit() and int(nxt) == int(per) + 1:
                shares[(per, nxt)] = oth / asrep
    found = {}
    for (per, nxt), ratio in shares.items():
        for k in (1.5, 2.0, 4.0, 10.0):
            if abs(ratio / k - 1) < 0.06:
                found[(per, nxt)] = k
    if found != STATED_SPLITS:
        print("❌ 数据自证的拆股链与公司自陈不一致：")
        print("   自证:", sorted(found.items()))
        print("   自陈:", sorted(STATED_SPLITS.items()))
        return 1
    fac = {}
    cum = 1.0
    for y in reversed(Y):
        fac[y] = cum
        for (a, b), k in STATED_SPLITS.items():
            if a == y or (y == "1997" and a == "1999"):
                pass
        # 进入更早一年前，若 (该年, 后一年) 之间有拆股，则更早年份的因子再乘倍数
        prev = Y[Y.index(y) - 1] if Y.index(y) > 0 else None
        if prev:
            for (a, b), k in STATED_SPLITS.items():
                if a == prev and b == y:
                    cum *= k
    rows.append(("🔴复权倍数(相对FY2026股本基准·数据自证=公司自陈6次·累计480) Split factor", [fac[y] for y in Y]))
    deps = g(I, "摊薄EPS(as-reported·拆股基准随年变) Diluted EPS", 0)
    rows.append(("🔴摊薄EPS(复权至FY2026股本基准) Diluted EPS split-adjusted",
                 [None if g(I, "摊薄EPS(as-reported·拆股基准随年变) Diluted EPS", i) is None else
                  g(I, "摊薄EPS(as-reported·拆股基准随年变) Diluted EPS", i) / fac[Y[i]] for i in range(N)]))
    rows.append(("🔴摊薄股数(复权·百万股) Diluted shares split-adjusted",
                 [None if g(I, "摊薄股数(百万股·as-reported) Diluted shares", i) is None else
                  g(I, "摊薄股数(百万股·as-reported) Diluted shares", i) * fac[Y[i]] for i in range(N)]))
    # MUST：近年关键格必须有值
    must = ["毛利率 Gross margin", "营业利润率 Operating margin", "经营现金流/净利 OCF/Net profit", "自由现金流(经营−资本开支·百万美元) FCF"]
    names = {n: v for n, v in rows}
    miss = [f"{m}@FY{Y[i]}" for m in must for i in range(N) if int(Y[i]) >= 1999 and names[m][i] is None]
    if miss:
        print("❌ 必需格缺失：", miss[:10])
        return 1
    with open(os.path.join(HERE, "财务比率.csv"), "w", newline="") as f:
        f.write("# 派生(本脚本从三表 + 附注产物计算·非年报直接给出) | 比率为小数(0.6=60%)，金额为百万美元 | 通用底 = scripts/derived.py(别名在本脚本内存适配·共享脚本未改)，"
                "定制层见各行名 | 无 FY1998(过渡月) | 周转天数/年均 ROE 的 FY1999 期初取 FY1997 年末(差一个月) | EPS/股数复权见 🔴 行\n")
        w = csv.writer(f)
        w.writerow(["科目"] + [f"FY{y}" for y in Y])
        for n, v in rows:
            w.writerow([n] + ["" if x is None else (f"{x:.4f}" if abs(x) < 50 else f"{x:.1f}") for x in v])
    print(f"✅ 写出 财务比率.csv（{len(rows)} 行）| derived 未匹配: {sorted(set(unmatched)) or '无'} | 拆股链自证 = 自陈 {len(found)} 次")
    return 0


if __name__ == "__main__":
    sys.exit(main())
