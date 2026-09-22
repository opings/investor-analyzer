#!/usr/bin/env python3
"""NIKE 派生比率构建器：从 `利润表.csv` / `资产负债表.csv` / `现金流量表.csv` /
`分部营收.csv` / `分产品与渠道营收.csv` 算出 `财务比率.csv`（年报不直接给这些）。

全部为**派生值**，不是财报原文。分子分母口径逐行写在行名里。

## 🔴 拆股复权因子是**从数据里推出来的**，不是手抄的

NIKE 各年 10-K 印的 EPS / 加权股数都按**该次申报时点的股本基准**追溯调整过，
所以 `利润表.csv` 里那两行**不可跨年相减**。要跨年比，得先复权到同一基准。

复权因子的求法：拿**相邻两份申报里同一个财年的股数**相除。
比值 ≈2 就说明这两份申报之间发生了一次 2-for-1 拆股。实测链条：

    FY1995 股数：FY1995 的 10-K 印 73.503 → FY1996 的 10-K 印 147.006 → FY1997 的 10-K 印 294.012

—— 两次翻倍，对应 1995-10 与 1996-10 两次拆股。全序列共探到 5 次（见运行输出）。
这么做的好处是**不依赖记忆里的拆股日期表**：因子由本库自己的数字互证得出，
拆股日期记错也不会污染数据。
"""
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FY = list(range(1993, 2027))


def load(name):
    """→ {行名: {fy: 值}}"""
    path = os.path.join(HERE, name)
    rows = list(csv.reader(open(path)))
    hdr = next(r for r in rows if r and r[0] in ("科目", "分部"))
    cols = {i: int(c[2:]) for i, c in enumerate(hdr) if c.startswith("FY")}
    out = {}
    for r in rows:
        if not r or r is hdr or r[0].startswith("#") or r[0] in ("数据来源", "财年", "来源申报"):
            continue
        d = {}
        for i, fy in cols.items():
            if i < len(r) and r[i]:
                try:
                    d[fy] = float(r[i])
                except ValueError:
                    pass
        if d:
            out[r[0]] = d
    return out


def g(t, name, fy):
    return t.get(name, {}).get(fy)


def s(*vals):
    """求和，全 None 返回 None（区分「都没有」与「加起来是 0」）。"""
    v = [x for x in vals if x is not None]
    return sum(v) if v else None


def div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


# ── 拆股复权因子（从股数序列自证）──────────────────────────────────────────
def split_factors():
    """→ ({fy: 相对最新基准的复权倍数}, [探到的拆股发生在哪两份申报之间])"""
    books = {}
    for fy in range(2011, 2027):
        p = os.path.join(HERE, "_rfiles", f"{fy}.json")
        if os.path.exists(p):
            books[fy] = ("R", json.load(open(p))["statements"])
    for fy in range(1995, 2011):
        p = os.path.join(HERE, "_legacy", f"{fy}.json")
        if os.path.exists(p):
            books[fy] = ("L", json.load(open(p))["statements"])

    def shares(ffy, target):
        track, sts = books[ffy]
        for key in ("IS", "EPS"):
            st = sts.get(key)
            if not st:
                continue
            years = st["years"] if track == "L" else [
                int(re.search(r"(19|20)\d\d", p).group()) for p in st["periods"]]
            if target not in years:
                continue
            i = years.index(target)
            sc = st.get("scale", 1.0) if track == "L" else (
                1.0 if "shares in millions" in (st.get("unit") or "").lower() else
                (1e-3 if "shares in thousands" in (st.get("unit") or "").lower() else 1.0))
            for r in st["rows"]:
                lab = re.sub(r"\s+", " ", r["label"]).strip().lower()
                if re.match(r"^(average number of common|(weighted )?average common shares"
                            r"|basic \(in shares\)|weighted average common shares outstanding)", lab):
                    v = r["vals"][i] if i < len(r["vals"]) else None
                    if v is not None:
                        return v * sc
        return None

    ffys = sorted(books)
    ratios, events = {}, []
    for a, b in zip(ffys, ffys[1:]):
        common = [y for y in FY if shares(a, y) and shares(b, y)]
        if not common:
            ratios[b] = 1.0
            continue
        y = common[-1]
        r = shares(b, y) / shares(a, y)
        k = round(r)
        ratios[b] = float(k) if k >= 2 and abs(r - k) < 0.02 else 1.0
        if ratios[b] >= 2:
            events.append((a, b, y, round(r, 4)))
    # 某财年的复权倍数 = 它之后所有申报里发生过的拆股连乘
    fac = {}
    for fy in FY:
        m = 1.0
        for ffy, r in ratios.items():
            if ffy > fy:
                m *= r
        fac[fy] = m
    return fac, events


def main():
    I, B, C = load("利润表.csv"), load("资产负债表.csv"), load("现金流量表.csv")
    SEGR = load("分部营收.csv")
    PC = load("分产品与渠道营收.csv")
    fac, events = split_factors()
    print("探到的拆股（在这两份 10-K 之间发生）：")
    for a, b, y, r in events:
        print(f"  FY{a} 10-K → FY{b} 10-K：同一个 FY{y} 的股数 ×{r}")
    print("复权倍数（相对 FY2026 股本基准）：",
          {y: fac[y] for y in (1993, 1996, 1997, 2007, 2008, 2012, 2013, 2015, 2016, 2026)})

    R = {}                                   # 行名 -> {fy: 值}

    def put(name, fn):
        R[name] = {}
        for fy in FY:
            v = fn(fy)
            if v is not None:
                R[name][fy] = v

    rev = lambda y: g(I, "营业收入 Revenues", y)                                  # noqa: E731
    ni = lambda y: g(I, "净利润 Net income", y)                                   # noqa: E731
    cogs = lambda y: g(I, "营业成本 Cost of sales", y)                            # noqa: E731
    sga = lambda y: g(I, "销售及管理费用合计 Total selling and administrative expense", y)  # noqa: E731
    pbt = lambda y: g(I, "税前利润 Income before income taxes", y)                  # noqa: E731
    ocf = lambda y: g(C, "经营活动现金流净额 Cash provided (used) by operations", y)  # noqa: E731
    capex = lambda y: g(C, "资本开支 Additions to property, plant and equipment", y)  # noqa: E731
    eq = lambda y: g(B, "股东权益合计 Total shareholders' equity", y)               # noqa: E731
    ta = lambda y: g(B, "总资产 TOTAL ASSETS", y)                                  # noqa: E731

    # ① 盈利能力 ——「毛利」FY1993-FY2002 的利润表没有印，这里按 营收−成本 派生
    put("毛利(派生·FY2002前财报未印此行) Gross profit(mn)",
        lambda y: None if rev(y) is None or cogs(y) is None else rev(y) - cogs(y))
    put("毛利率 Gross margin", lambda y: div(R["毛利(派生·FY2002前财报未印此行) Gross profit(mn)"].get(y), rev(y)))
    put("需求创造(营销)费用率 Demand creation / revenue",
        lambda y: div(g(I, "  需求创造费用 Demand creation expense", y), rev(y)))
    put("运营管理费用率 Operating overhead / revenue",
        lambda y: div(g(I, "  运营管理费用 Operating overhead expense", y), rev(y)))
    put("销售及管理费用率 SG&A / revenue", lambda y: div(sga(y), rev(y)))
    put("EBIT(派生=税前+利息费用净额) EBIT(mn)",
        lambda y: None if pbt(y) is None else
        pbt(y) + (g(I, "利息费用净额(费用为正) Interest expense (income), net", y) or 0.0))
    put("EBIT利润率 EBIT margin", lambda y: div(R["EBIT(派生=税前+利息费用净额) EBIT(mn)"].get(y), rev(y)))
    put("净利率 Net margin", lambda y: div(ni(y), rev(y)))
    put("实际所得税率 Effective tax rate",
        lambda y: div(g(I, "所得税 Income taxes", y), pbt(y)))

    # ② 回报
    put("ROE(净利/平均净资产) Return on equity",
        lambda y: div(ni(y), None if eq(y) is None or eq(y - 1) is None else (eq(y) + eq(y - 1)) / 2))
    put("ROA(净利/平均总资产) Return on assets",
        lambda y: div(ni(y), None if ta(y) is None or ta(y - 1) is None else (ta(y) + ta(y - 1)) / 2))

    # ③ 三大前提
    put("现金含量 经营现金流/净利", lambda y: div(ocf(y), ni(y)))
    put("capex/净利 Capex / net income",
        lambda y: div(None if capex(y) is None else abs(capex(y)), ni(y)))
    put("capex/经营现金流 Capex / OCF",
        lambda y: div(None if capex(y) is None else abs(capex(y)), ocf(y)))
    put("capex/营收 Capex / revenue",
        lambda y: div(None if capex(y) is None else abs(capex(y)), rev(y)))
    put("自由现金流 FCF = OCF − capex(mn)",
        lambda y: None if ocf(y) is None or capex(y) is None else ocf(y) + capex(y))
    put("应收账款增速−营收增速(pp) ΔAR% − ΔRev%",
        lambda y: None if None in (g(B, "应收账款净额 Accounts receivable, net", y),
                                   g(B, "应收账款净额 Accounts receivable, net", y - 1),
                                   rev(y), rev(y - 1)) or rev(y - 1) == 0 else
        (g(B, "应收账款净额 Accounts receivable, net", y) /
         g(B, "应收账款净额 Accounts receivable, net", y - 1) - rev(y) / rev(y - 1)) * 100)

    # ④ 周转（分母用当年，口径统一）
    put("应收账款周转天数 DSO",
        lambda y: div(g(B, "应收账款净额 Accounts receivable, net", y), rev(y)) and
        div(g(B, "应收账款净额 Accounts receivable, net", y), rev(y)) * 365)
    put("存货周转天数 DIO",
        lambda y: None if div(g(B, "存货 Inventories", y), cogs(y)) is None else
        div(g(B, "存货 Inventories", y), cogs(y)) * 365)
    put("应付账款周转天数 DPO",
        lambda y: None if div(g(B, "应付账款 Accounts payable", y), cogs(y)) is None else
        div(g(B, "应付账款 Accounts payable", y), cogs(y)) * 365)
    put("现金转换周期 CCC = DSO+DIO−DPO",
        lambda y: None if None in (R["应收账款周转天数 DSO"].get(y), R["存货周转天数 DIO"].get(y),
                                   R["应付账款周转天数 DPO"].get(y)) else
        R["应收账款周转天数 DSO"][y] + R["存货周转天数 DIO"][y] - R["应付账款周转天数 DPO"][y])

    # ⑤ 资产结构
    put("现金及短投/总资产 Cash & ST investments / assets",
        lambda y: div(s(g(B, "货币资金 Cash and equivalents", y),
                        g(B, "短期投资 Short-term investments", y)), ta(y)))
    put("存货/总资产 Inventories / assets", lambda y: div(g(B, "存货 Inventories", y), ta(y)))
    put("应收账款/总资产 AR / assets",
        lambda y: div(g(B, "应收账款净额 Accounts receivable, net", y), ta(y)))
    put("固定资产/总资产 PP&E / assets",
        lambda y: div(g(B, "固定资产净额 Property, plant and equipment, net", y), ta(y)))
    put("使用权资产/总资产 ROU assets / assets",
        lambda y: div(g(B, "使用权资产 Operating lease right-of-use assets, net", y), ta(y)))
    put("商誉+无形/总资产 Goodwill & intangibles / assets",
        lambda y: div(s(g(B, "商誉 Goodwill", y),
                        g(B, "可辨认无形资产净额 Identifiable intangible assets, net", y),
                        g(B, "无形资产及商誉(仅FY1995-2002合并列示) Identifiable intangible assets and goodwill", y)), ta(y)))
    put("资产负债率 Liabilities / assets",
        lambda y: None if ta(y) is None or eq(y) is None else (ta(y) - eq(y)) / ta(y))

    # ⑥ 杠杆
    put("有息负债(含租赁负债)合计 Interest-bearing debt incl. leases(mn)",
        lambda y: s(g(B, "长期债务 Long-term debt", y),
                    g(B, "一年内到期长期债务 Current portion of long-term debt", y),
                    g(B, "短期借款 Notes payable", y),
                    g(B, "租赁负债(流动) Current portion of operating lease liabilities", y),
                    g(B, "租赁负债(非流动) Operating lease liabilities", y)))
    # 🔴 租赁负债算不算「有息负债」是个口径选择，会直接翻转「净现金/净负债」的结论：
    #    FY2026 含租赁时净现金 −20 亿(看着像净负债)，剔掉租赁则是 +11 亿(净现金)。
    #    两个口径都列出来，读的人自己选，不在这里替读者做判断。
    put("有息债务(不含租赁负债) Interest-bearing debt excl. leases(mn)",
        lambda y: s(g(B, "长期债务 Long-term debt", y),
                    g(B, "一年内到期长期债务 Current portion of long-term debt", y),
                    g(B, "短期借款 Notes payable", y)))
    put("净现金(不含租赁负债口径) Net cash excl. leases(mn)",
        lambda y: None if s(g(B, "货币资金 Cash and equivalents", y),
                            g(B, "短期投资 Short-term investments", y)) is None else
        s(g(B, "货币资金 Cash and equivalents", y), g(B, "短期投资 Short-term investments", y))
        - (R["有息债务(不含租赁负债) Interest-bearing debt excl. leases(mn)"].get(y) or 0.0))
    put("有息负债/净资产 Debt / equity",
        lambda y: div(R["有息负债(含租赁负债)合计 Interest-bearing debt incl. leases(mn)"].get(y), eq(y)))
    put("净现金(现金+短投−有息负债) Net cash(mn)",
        lambda y: None if s(g(B, "货币资金 Cash and equivalents", y),
                            g(B, "短期投资 Short-term investments", y)) is None else
        s(g(B, "货币资金 Cash and equivalents", y), g(B, "短期投资 Short-term investments", y))
        - (R["有息负债(含租赁负债)合计 Interest-bearing debt incl. leases(mn)"].get(y) or 0.0))

    # ⑦ 股东回报（金额取现金流量表，均为流出、此处转成正数）
    div_paid = lambda y: (lambda v: None if v is None else abs(v))(                    # noqa: E731
        g(C, "已付股息 Dividends — common and preferred", y))
    buyback = lambda y: (lambda v: None if v is None else abs(v))(                     # noqa: E731
        g(C, "回购股票 Repurchase of common stock", y))
    put("已付股息 Dividends paid(mn)", div_paid)
    put("回购金额 Buybacks(mn)", buyback)
    put("分红率(已付股息/净利) Payout ratio (cash paid)", lambda y: div(div_paid(y), ni(y)))
    put("回购率(回购/净利) Buyback / net income", lambda y: div(buyback(y), ni(y)))
    put("股东总回报率((股息+回购)/净利) Total payout / net income",
        lambda y: div(s(div_paid(y), buyback(y)), ni(y)))
    put("股东总回报/经营现金流 Total payout / OCF", lambda y: div(s(div_paid(y), buyback(y)), ocf(y)))
    cum_d, cum_b, cum_i = {}, {}, {}
    ad = ab = ai = 0.0
    for y in FY:
        ad += div_paid(y) or 0.0
        ab += buyback(y) or 0.0
        ai += g(C, "行权所得 Proceeds from exercise of stock options", y) or 0.0
        cum_d[y], cum_b[y], cum_i[y] = ad, ab, ai
    put("累计已付股息(FY1993起) Cumulative dividends(mn)", lambda y: cum_d.get(y))
    put("累计回购(FY1993起) Cumulative buybacks(mn)", lambda y: cum_b.get(y))
    put("累计行权所得(FY1993起·唯一的股权融资来源) Cumulative option proceeds(mn)",
        lambda y: cum_i.get(y))
    put("累计给股东净额(股息+回购−行权所得) Cumulative net to shareholders(mn)",
        lambda y: None if y not in cum_d else cum_d[y] + cum_b[y] - cum_i[y])

    # ⑧ 拆股复权后的每股口径（跨年可比）
    put("拆股复权因子(相对FY2026) Split factor", lambda y: fac.get(y))
    put("【复权】基本EPS(美元·FY2026股本口径)",
        lambda y: div(g(I, "基本EPS(as-reported·拆股基准随年变) Basic EPS", y), fac.get(y)))
    put("【复权】摊薄EPS(美元·FY2026股本口径)",
        lambda y: div(g(I, "摊薄EPS(as-reported·拆股基准随年变) Diluted EPS", y), fac.get(y)))
    put("【复权】基本加权股数(百万股·FY2026股本口径)",
        lambda y: None if g(I, "基本股数(百万股·as-reported) Basic shares", y) is None else
        g(I, "基本股数(百万股·as-reported) Basic shares", y) * fac.get(y, 1.0))

    # ⑨ 运动服饰特有 —— 这几条是「财报关注要点.md」核心跟踪变量的数据落点
    put("存货/营收 Inventories / revenue", lambda y: div(g(B, "存货 Inventories", y), rev(y)))
    put("DTC(直营)占比 NIKE Direct / total revenue",
        lambda y: div(g(PC, "直营 NIKE Direct", y), rev(y)))
    put("批发占比 Wholesale / total revenue",
        lambda y: div(g(PC, "批发 Wholesale", y), rev(y)))
    put("大中华占比 Greater China / total revenue",
        lambda y: div(g(SEGR, "大中华 Greater China", y), rev(y)))
    put("北美占比 North America / total revenue",
        lambda y: div(g(SEGR, "北美 North America", y), rev(y)))
    put("鞋类占比 Footwear / total revenue", lambda y: div(g(PC, "鞋类 Footwear", y), rev(y)))

    path = os.path.join(HERE, "财务比率.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# 单位: 比率为倍数(1=100%)、天数为天、金额为百万美元、EPS 为美元/股；"
                    "空 = 所需分项该年不可得。**全部为派生值**，年报不直接给。"])
        w.writerow(["# 分母口径写在行名里。ROE/ROA 用期初期末平均净资产/总资产，"
                    "故 FY1993(无期初数)为空。EBIT 为派生(税前+利息费用净额)，"
                    "与分部表里 NIKE 自己披露的 EBIT 口径一致但不逐年等同。"])
        w.writerow(["# 🔴【复权】三行已按本库自证的拆股链折算到 FY2026 股本口径，"
                    "跨年比每股数据请用这三行，**不要用 利润表.csv 的 as-reported EPS/股数**。"])
        w.writerow(["科目"] + [f"FY{y}" for y in FY])
        for name, d in R.items():
            row = [name]
            for y in FY:
                v = d.get(y)
                row.append("" if v is None else
                           (f"{v:.4f}".rstrip("0").rstrip(".") if abs(v) < 100 else f"{v:.1f}"))
            if any(x for x in row[1:]):
                w.writerow(row)
    print(f"写出 财务比率.csv（{len(R)} 行 × {len(FY)} 年）")


if __name__ == "__main__":
    main()
