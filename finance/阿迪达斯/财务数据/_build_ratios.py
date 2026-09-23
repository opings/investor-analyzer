#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阿迪达斯 财务比率.csv 生成器 —— 纯派生，只读本目录三表 CSV，不新增取数。

年报不直接给这些比率；全部由 `_build_from_pdf.py` 写出的三表算得。
口径写在行名里（分母是谁、含不含租赁负债、已付还是宣派）。

⚠️ 跨年读这张表前必看 README「口径断点清单」：
   · 2005 Salomon / 2016-17 TaylorMade 等 / 2021 Reebok 剥离 → 营收口径三次收窄（as-reported 不可直接连比）
   · 2019 首次适用 IFRS 16 → 总资产、资产负债率、折旧摊销跳升有相当部分是会计准则
   · 2018 已付利息由经营活动改列融资活动 → 经营现金流跨 2017/2018 不可比
   · 2006-06 1:4 拆股 → EPS 跨 2005/2006 不可直接比，用本表【复权】行
"""
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SPLIT_2006 = 4.0  # 2006-06-06 一拆四；2006 年以前的每股数据须 ÷4 才能与之后可比


def load(name):
    """读三表 CSV → {科目: {年: 值}}，跳过注释行与「数据来源」行。"""
    path = os.path.join(HERE, name)
    out, years = {}, []
    with open(path, encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row or row[0].startswith("#"):
                continue
            if row[0] == "科目":
                years = [int(y) for y in row[1:]]
                continue
            if row[0] == "数据来源":
                continue
            out[row[0]] = {y: (float(v) if v not in ("", None) else None)
                           for y, v in zip(years, row[1:])}
    return out, years


IS, YEARS = load("利润表.csv")
BS, _ = load("资产负债表.csv")
CF, _ = load("现金流量表.csv")


def g(tbl, row, y):
    return tbl.get(row, {}).get(y)


def s(*vals):
    """求和：全 None 返回 None，否则把 None 当 0（用于「科目并集」型合计）。"""
    vs = [v for v in vals if v is not None]
    return sum(vs) if vs else None


def div(a, b):
    if a is None or b in (None, 0):
        return None
    return a / b


def avg(tbl, row, y):
    """期初期末平均（首年无期初 → None）。"""
    cur, prev = g(tbl, row, y), g(tbl, row, y - 1)
    if cur is None or prev is None:
        return None
    return (cur + prev) / 2


R = {}


def put(name, fn):
    R[name] = {y: fn(y) for y in YEARS}


# ── 盈利能力 ─────────────────────────────────────────────────────
put("毛利率 Gross margin", lambda y: div(g(IS, "毛利", y), g(IS, "营业收入", y)))
put("经营利润率 Operating margin", lambda y: div(g(IS, "经营利润", y), g(IS, "营业收入", y)))
put("净利率(归母/营收) Net margin", lambda y: div(g(IS, "归母净利润", y), g(IS, "营业收入", y)))
put("实际所得税率 Effective tax rate", lambda y: div(g(IS, "所得税", y), g(IS, "税前利润", y)))
put("营销及销售点费用率 Marketing & POS / revenue",
    lambda y: div(g(IS, "营销及销售点费用", y), g(IS, "营业收入", y)))
put("分销及销售费用率 Distribution & selling / revenue",
    lambda y: div(g(IS, "分销及销售费用", y), g(IS, "营业收入", y)))
put("一般及管理费用率 G&A / revenue", lambda y: div(g(IS, "一般及管理费用", y), g(IS, "营业收入", y)))
put("ROE(归母净利/平均归母权益) Return on equity",
    lambda y: div(g(IS, "归母净利润", y), avg(BS, "归母股东权益", y)))
put("ROA(合并净利/平均总资产) Return on assets",
    lambda y: div(g(IS, "合并净利润", y), avg(BS, "资产总计", y)))

# ── 利润链纵深（差额越小 = 利润越干净）───────────────────────────
put("归母/合并净利 Attributable to shareholders / net income",
    lambda y: div(g(IS, "归母净利润", y), g(IS, "合并净利润", y)))
put("持续经营净利/合并净利 Continuing ops / net income",
    lambda y: div(g(IS, "持续经营净利润", y), g(IS, "合并净利润", y)))

# ── 利润为真（前提①）───────────────────────────────────────────
put("现金含量 经营现金流/合并净利",
    lambda y: div(g(CF, "经营活动现金流净额", y), g(IS, "合并净利润", y)))
put("现金含量 经营现金流/归母净利",
    lambda y: div(g(CF, "经营活动现金流净额", y), g(IS, "归母净利润", y)))


def _ar(y):
    """应收账款：1994-1997 年报把应收与其他流动资产合并列示，不可比 → 留空。"""
    return g(BS, "应收账款", y)


def _yoy(tbl, row, y):
    cur, prev = g(tbl, row, y), g(tbl, row, y - 1)
    if cur is None or prev in (None, 0):
        return None
    return cur / prev - 1


put("应收账款增速−营收增速(pp) ΔAR% − ΔRev%",
    lambda y: None if _yoy(BS, "应收账款", y) is None or _yoy(IS, "营业收入", y) is None
    else (_yoy(BS, "应收账款", y) - _yoy(IS, "营业收入", y)) * 100)
put("应收账款周转天数 DSO", lambda y: div(avg(BS, "应收账款", y), g(IS, "营业收入", y)) and
    div(avg(BS, "应收账款", y), g(IS, "营业收入", y)) * 365)
put("存货周转天数 DIO", lambda y: div(avg(BS, "存货", y), g(IS, "营业成本", y)) and
    div(avg(BS, "存货", y), g(IS, "营业成本", y)) * 365)
put("应付账款周转天数 DPO", lambda y: div(avg(BS, "应付账款", y), g(IS, "营业成本", y)) and
    div(avg(BS, "应付账款", y), g(IS, "营业成本", y)) * 365)
put("现金转换周期 CCC = DSO+DIO−DPO",
    lambda y: None if None in (R["应收账款周转天数 DSO"][y], R["存货周转天数 DIO"][y],
                               R["应付账款周转天数 DPO"][y])
    else R["应收账款周转天数 DSO"][y] + R["存货周转天数 DIO"][y] - R["应付账款周转天数 DPO"][y])

# ── 维持利润要不要大钱（前提②）─────────────────────────────────
put("capex(购置PP&E)/合并净利 Capex / net income",
    lambda y: div(-g(CF, "购置物业厂房及设备", y) if g(CF, "购置物业厂房及设备", y) is not None else None,
                  g(IS, "合并净利润", y)))
put("capex/经营现金流 Capex / OCF",
    lambda y: div(-g(CF, "购置物业厂房及设备", y) if g(CF, "购置物业厂房及设备", y) is not None else None,
                  g(CF, "经营活动现金流净额", y)))
put("capex/营收 Capex / revenue",
    lambda y: div(-g(CF, "购置物业厂房及设备", y) if g(CF, "购置物业厂房及设备", y) is not None else None,
                  g(IS, "营业收入", y)))
put("自由现金流 FCF = 经营现金流 − capex(€mn)",
    lambda y: None if g(CF, "经营活动现金流净额", y) is None or g(CF, "购置物业厂房及设备", y) is None
    else round(g(CF, "经营活动现金流净额", y) + g(CF, "购置物业厂房及设备", y), 1))
put("折旧摊销/营收 D&A / revenue", lambda y: div(g(CF, "折旧摊销", y), g(IS, "营业收入", y)))

# ── 资产结构画像（轻/重资产）─────────────────────────────────────
for label, row in (("现金及短期金融资产", None), ("存货", "存货"), ("应收账款", "应收账款"),
                   ("固定资产", "物业厂房及设备"), ("使用权资产", "使用权资产"),
                   ("商誉", "商誉"), ("递延所得税资产", "递延所得税资产")):
    if row is None:
        put(f"{label}/总资产",
            lambda y: div(s(g(BS, "货币资金", y), g(BS, "短期金融资产", y)), g(BS, "资产总计", y)))
    else:
        put(f"{label}/总资产", (lambda r: lambda y: div(g(BS, r, y), g(BS, "资产总计", y)))(row))
put("商标+其他无形/总资产",
    lambda y: div(s(g(BS, "商标", y), g(BS, "其他无形资产", y), g(BS, "商誉及其他无形资产", y)),
                  g(BS, "资产总计", y)))

# ── 杠杆 ─────────────────────────────────────────────────────────
put("资产负债率 Liabilities / assets",
    lambda y: None if g(BS, "资产总计", y) is None
    else div(g(BS, "资产总计", y) - s(g(BS, "权益合计", y),
                                    None if g(BS, "权益合计", y) is not None else g(BS, "归母股东权益", y),
                                    None if g(BS, "权益合计", y) is not None else g(BS, "少数股东权益", y)),
             g(BS, "资产总计", y)))
put("有息负债(不含租赁负债)(€mn)",
    lambda y: s(g(BS, "短期借款", y), g(BS, "长期借款", y)))
put("有息负债(含租赁负债)(€mn)",
    lambda y: s(g(BS, "短期借款", y), g(BS, "长期借款", y),
                g(BS, "流动租赁负债", y), g(BS, "非流动租赁负债", y)))
put("净现金(现金+短期金融资产−有息负债不含租赁)(€mn)",
    lambda y: None if R["有息负债(不含租赁负债)(€mn)"][y] is None
    else round(s(g(BS, "货币资金", y), g(BS, "短期金融资产", y)) - R["有息负债(不含租赁负债)(€mn)"][y], 1))
put("有息负债(不含租赁)/归母权益 Debt / equity",
    lambda y: div(R["有息负债(不含租赁负债)(€mn)"][y], g(BS, "归母股东权益", y)))
put("流动比率 Current ratio", lambda y: div(g(BS, "流动资产合计", y), g(BS, "流动负债合计", y)))

# ── 股东回报画像 ────────────────────────────────────────────────
put("已付股息(€mn)", lambda y: None if g(CF, "支付股东股利", y) is None else -g(CF, "支付股东股利", y))
put("回购金额(€mn)", lambda y: None if g(CF, "回购库存股", y) is None else -g(CF, "回购库存股", y))
put("分红率(年内已付股息/上年归母净利) Payout ratio (cash paid)",
    lambda y: None if g(CF, "支付股东股利", y) is None or g(IS, "归母净利润", y - 1) in (None, 0)
    else -g(CF, "支付股东股利", y) / g(IS, "归母净利润", y - 1))
put("股东总回报((股息+回购)/经营现金流)",
    lambda y: None if g(CF, "支付股东股利", y) is None or g(CF, "经营活动现金流净额", y) in (None, 0)
    else (-g(CF, "支付股东股利", y) - (g(CF, "回购库存股", y) or 0)) / g(CF, "经营活动现金流净额", y))


def _cum(row):
    acc, out = 0.0, {}
    for y in YEARS:
        v = R[row].get(y)
        if v is not None:
            acc += v
        out[y] = round(acc, 1)
    return out


R["累计已付股息(1994起·€mn)"] = _cum("已付股息(€mn)")
R["累计回购(1994起·€mn)"] = _cum("回购金额(€mn)")
R["累计给股东(股息+回购·€mn)"] = {y: round(R["累计已付股息(1994起·€mn)"][y]
                                     + R["累计回购(1994起·€mn)"][y], 1) for y in YEARS}

# ── 拆股复权（2006-06 一拆四）────────────────────────────────────
R["拆股复权因子(相对2006后股本)"] = {y: (1 / SPLIT_2006 if y <= 2005 else 1.0) for y in YEARS}
for src, dst in (("基本每股收益", "【复权】基本EPS(€/股·2006后股本口径)"),
                 ("稀释每股收益", "【复权】稀释EPS(€/股·2006后股本口径)")):
    R[dst] = {y: (None if g(IS, src, y) is None
                  else round(g(IS, src, y) * R["拆股复权因子(相对2006后股本)"][y], 2)) for y in YEARS}


def fmt(v):
    if v is None:
        return ""
    return round(v, 4) if abs(v) < 1000 else round(v, 1)


def main():
    path = os.path.join(HERE, "财务比率.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["# 单位：比率为倍数(1=100%)、天数为天、金额为 € 百万、EPS 为 €/股；"
                    "空 = 所需分项该年不可得。**全部为派生值**，年报不直接给。"])
        w.writerow(["# 分母口径写在行名里。ROE/ROA 用期初期末平均，故 1994(无期初)为空；"
                    "1994-1997 年报未单列应收账款（与其他流动资产合并），故 DSO 等自 1999 起。"])
        w.writerow(["# 🔴 跨年读之前必看 README「口径断点清单」："
                    "2005/2016-17/2021 三次业务剥离令营收口径收窄；2019 首次适用 IFRS 16；"
                    "2018 已付利息改列融资活动；2006-06 一拆四（每股数据请用【复权】两行）。"])
        w.writerow(["科目"] + [str(y) for y in YEARS])
        for name, ser in R.items():
            if not any(ser.get(y) is not None for y in YEARS):
                continue
            w.writerow([name] + [fmt(ser.get(y)) for y in YEARS])
    print(f"已写出 财务比率.csv（{len(R)} 行 × {len(YEARS)} 年）")


if __name__ == "__main__":
    main()
