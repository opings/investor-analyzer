#!/usr/bin/env python3
"""从已建好的三表派生 `财务比率.csv`（年报不直接给比率，全部在这里算）。

## 为什么不直接用 `scripts/derived.py` 的通用底

通用引擎的科目别名层是按 A 股 CAS / 港股 IFRS / 日股 JGAAP 的中文·日文科目名建的，
而 Disney 的列报有两个结构性差异，套上去会得到一串「—」或错值：

1. **没有「营业成本」这条线**：FY2018 及以前利润表只有一条
   「Total costs and expenses」（含销售成本+SG&A+折旧摊销），**算不出毛利率**。
   FY2019 起才按 Service / Product 拆出成本 → 毛利率**只有 FY2019 之后可比**。
2. **没有「营业利润」这条线**：Disney 的「Segment Operating Income」是分部口径、
   在公司总部费用与减值之前，与 A 股「营业利润」不是一回事 → 本表单列、不混用。

## 口径声明

- **ROE 用期初期末平均归母权益**（FY1993 无期初数据故留空）；分母 = 归母权益，分子 = 归母净利。
- **现金含量 = 经营活动现金流净额 ÷ 归母净利**。
  🔴 这条序列**跨两个口径断点不可直接连线**：FY1998（影视制作支出在经营/投资间重分类）、
  FY2001（采用 SOP 00-2，影视制作支出改列经营 → FY2000 经营现金流由 6,434 重述为 3,755）。
  断点两侧各自可比，跨断点不可比；重述值见 `重述与口径变更.csv`。
- **有息负债 = 短期借款 + 长期借款**（Disney 未单列其他有息项）。
- **资产负债率 = (资产总计 − 权益合计) ÷ 资产总计**；FY2008 及以前少数股东权益列在权益之外
  （夹层），此时用归母权益作分母基准并在下方注明。
"""
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    rows = list(csv.reader(open(os.path.join(HERE, name))))
    hdr = next(r for r in rows if r and r[0] == "科目")
    years = [int(y) for y in hdr[1:]]
    out = {}
    for r in rows:
        if not r or r[0] in ("科目",) or r[0].startswith(("单位", "各年")):
            continue
        out[r[0]] = {y: (float(v) if v else None) for y, v in zip(years, r[1:])}
    return years, out


def main():
    years, IS = load("利润表.csv")
    _, BS = load("资产负债表.csv")
    _, CF = load("现金流量表.csv")

    def g(tbl, key, y):
        for k in tbl:
            if k.strip().startswith(key):
                return tbl[k].get(y)
        return None

    def div(a, b):
        return (a / b) if (a is not None and b not in (None, 0)) else None

    def divpos(a, b):
        """分母必须为正才给值。

        🔴 分母为负时比率会**反向误导**：FY2001 归母净利 −158，「已付股利 ÷ 归母净利」
           会算出 −277%，读起来像「负分红」，其实那年照付了 438 百万股息。
           亏损年的这类比率没有意义，留空并在旁边看金额行。
        """
        return (a / b) if (a is not None and b is not None and b > 0) else None

    def amt(v):
        """0 是真实值（FY2021-2022 停发股息/停止回购），不能被 `or None` 吞成空。"""
        return None if v is None else abs(v)

    rows = []

    def add(name, fn, pct=False, dec=2):
        vals = []
        for y in years:
            v = fn(y)
            if v is None:
                vals.append("")
            else:
                vals.append(f"{v * 100:.1f}" if pct else f"{v:.{dec}f}")
        if any(vals):
            rows.append([name] + vals)

    rev = lambda y: g(IS, "营业收入", y)
    att = lambda y: g(IS, "归母净利", y)
    netp = lambda y: g(IS, "净利润", y)
    ocf = lambda y: g(CF, "经营活动现金流净额", y)
    capex = lambda y: g(CF, "资本开支", y)
    ta = lambda y: g(BS, "资产总计", y)
    eq = lambda y: g(BS, "权益合计", y) or g(BS, "归母权益", y)
    ateq = lambda y: g(BS, "归母权益", y)

    rows.append(["── 盈利能力 ──"] + [""] * len(years))
    add("毛利率%(仅FY2019起可算·之前无成本拆分)",
        lambda y: div((rev(y) or 0) - abs((g(IS, "  服务成本", y) or 0) + (g(IS, "  产品成本", y) or 0)),
                      rev(y)) if g(IS, "  服务成本", y) else None, pct=True)
    add("总成本费用率%", lambda y: div(abs(g(IS, "总成本及费用", y) or 0) or None, rev(y)), pct=True)
    add("税前利润率%", lambda y: div(g(IS, "税前利润", y), rev(y)), pct=True)
    add("归母净利率%", lambda y: div(att(y), rev(y)), pct=True)
    # 🔴 实际税率 = −所得税 ÷ 税前利润（本库所得税为负数=费用、正数=净收益）。
    #   **不能取 abs()**：那样会把「税收净收益」显示成「低税率」——FY2025 真实为
    #   **−11.9%**（税项是 +1,428 的净收益），取绝对值会印成 +11.9%，
    #   看起来只是税率低，完全掩盖「净利润大于税前利润」这个最关键的利润质量信号。
    #   税前亏损年该比率无意义，留空。
    add("实际税率%(负数=税收净收益·亏损年留空)",
        lambda y: (-(g(IS, "所得税", y)) / g(IS, "税前利润", y))
        if (g(IS, "所得税", y) is not None and (g(IS, "税前利润", y) or 0) > 0) else None,
        pct=True)
    add("ROE%(归母净利÷期初期末平均归母权益)",
        lambda y: div(att(y), (ateq(y) + ateq(y - 1)) / 2
                      if (ateq(y) is not None and ateq(y - 1) is not None) else None), pct=True)
    add("ROA%(归母净利÷期末总资产)", lambda y: div(att(y), ta(y)), pct=True)

    rows.append(["── 三大前提 ──"] + [""] * len(years))
    add("现金含量(经营现金流÷归母净利·亏损年留空)⚠️FY1998/FY2001 两处口径断点",
        lambda y: divpos(ocf(y), att(y)))
    add("资本开支÷归母净利(亏损年留空)", lambda y: divpos(amt(capex(y)), att(y)))
    add("资本开支÷经营现金流", lambda y: divpos(amt(capex(y)), ocf(y)))
    add("自由现金流(经营现金流+资本开支,百万美元)",
        lambda y: (ocf(y) + capex(y)) if None not in (ocf(y), capex(y)) else None, dec=0)
    add("自由现金流÷营收%",
        lambda y: div((ocf(y) + capex(y)) if None not in (ocf(y), capex(y)) else None, rev(y)), pct=True)

    rows.append(["── 资产结构(占总资产%) ──"] + [""] * len(years))
    for label, key in [("货币资金", "货币资金"), ("应收账款", "应收账款"), ("存货", "存货"),
                       ("影视内容成本", "影视内容成本"), ("固定资产净额", "固定资产净额"),
                       ("商誉", "商誉"), ("无形资产", "无形资产")]:
        add(f"{label}占总资产%", lambda y, k=key: div(g(BS, k, y), ta(y)), pct=True)
    add("商誉+无形资产占归母权益%",
        lambda y: div((g(BS, "商誉", y) or 0) + (g(BS, "无形资产", y) or 0) or None, ateq(y)), pct=True)

    rows.append(["── 杠杆与偿债 ──"] + [""] * len(years))
    ibd = lambda y: ((g(BS, "短期借款", y) or 0) + (g(BS, "长期借款", y) or 0)) or None
    add("有息负债(短期+长期借款,百万美元)", ibd, dec=0)
    add("资产负债率%", lambda y: div((ta(y) - eq(y)) if None not in (ta(y), eq(y)) else None, ta(y)),
        pct=True)
    add("有息负债÷归母权益%", lambda y: div(ibd(y), ateq(y)), pct=True)
    add("净有息负债(有息负债−货币资金,百万美元)",
        lambda y: (ibd(y) - g(BS, "货币资金", y)) if None not in (ibd(y), g(BS, "货币资金", y)) else None,
        dec=0)
    # ⚠️ 只在「净利息是净支出」的年份算。FY1993/1994/2014 是**净利息收入**
    #    （分别 +28.4 / +10 / +23），分母极小甚至性质相反，会算出 171 倍、533 倍这种
    #    看似安全实则无意义的数 —— 那些年根本不存在「利息覆盖」这个问题。
    def icov(y):
        pre, ie = g(IS, "税前利润", y), g(IS, "利息支出净额", y)
        if pre is None or ie is None or ie >= 0:
            return None
        return (pre + abs(ie)) / abs(ie)

    add("利息保障倍数((税前+利息费用)÷利息费用·净利息为收入的年份留空)", icov)

    rows.append(["── 周转效率(天) ──"] + [""] * len(years))
    add("应收账款周转天数", lambda y: div(g(BS, "应收账款", y), rev(y)) * 365
        if div(g(BS, "应收账款", y), rev(y)) else None, dec=0)
    add("存货周转天数(分母用总成本费用)",
        lambda y: div(g(BS, "存货", y), abs(g(IS, "总成本及费用", y) or 0) or None) * 365
        if div(g(BS, "存货", y), abs(g(IS, "总成本及费用", y) or 0) or None) else None, dec=0)

    rows.append(["── 股东回报 ──"] + [""] * len(years))
    div_paid = lambda y: amt(g(CF, "分红支付", y))
    buyback = lambda y: amt(g(CF, "回购股份", y))

    def payout_sum(y):
        a, b = div_paid(y), buyback(y)
        return None if (a is None and b is None) else (a or 0) + (b or 0)

    add("已付股利(百万美元·现金流量表口径)", div_paid, dec=0)
    add("回购股份(百万美元)", buyback, dec=0)
    # ⚠️ 口径 = **现金流量表「年内已付」**，不是「本财政年度宣派」。两者有跨年时间差，
    #    在停发/复发的转折年（Disney FY2020 停发、FY2024 复发）差异最大。
    add("分红率%(已付股利÷归母净利·亏损年留空)", lambda y: divpos(div_paid(y), att(y)), pct=True)
    add("分红+回购÷经营现金流%", lambda y: divpos(payout_sum(y), ocf(y)), pct=True)
    add("分红+回购÷自由现金流%",
        lambda y: divpos(payout_sum(y),
                         (ocf(y) + capex(y)) if None not in (ocf(y), capex(y)) else None), pct=True)

    rows.append(["── 利润链纵深 ──"] + [""] * len(years))
    add("归母÷净利%(少数股东权益 leak)", lambda y: div(att(y), netp(y)), pct=True)

    hdr_note = ("单位:比率为%或倍数(列名已标),金额行单位为百万美元。全部由 _build_ratios.py "
                "从 利润表/资产负债表/现金流量表.csv 派生,年报不直接给这些比率。")
    caveat = ("🔴 口径断点:① 毛利率仅 FY2019 起可算(此前利润表无成本拆分);"
              "② 现金含量序列跨 FY1998(影视制作支出经营↔投资重分类)与 FY2001(采用 SOP 00-2)"
              "两处断点不可直接连线;③ FY2008 及以前少数股东权益列在权益之外(夹层);"
              "④ FY2017 起现金口径含受限现金(ASU 2016-18)。")
    with open(os.path.join(HERE, "财务比率.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([hdr_note])
        w.writerow([caveat])
        w.writerow(["指标"] + [str(y) for y in years])
        w.writerows(rows)
    print(f"写出 财务比率.csv（{len([r for r in rows if not r[0].startswith('──')])} 个指标 × "
          f"{len(years)} 年）")


if __name__ == "__main__":
    main()
