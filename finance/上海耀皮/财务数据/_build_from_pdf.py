#!/usr/bin/env python3
"""上海耀皮(600819) 三表 + 比率 CSV 生成器 —— _extract_json/fy*.json → CSV

年份口径
  2006      = FY2007 年报「上年列」。2006 年报本身按**旧准则**《企业会计制度》编制，
              科目结构与 CAS2006 不可比；FY2007 年报的比较列已追溯重述为新准则
              （该年报「前三年主要会计数据」表同时列了 2006 调整后/调整前两栏，
               调整后营收 1,889,832,097.03 与本库取值一致，可互证）。
  2007-2025 = 各年年报**本年列**（as-reported，不被后续年度追溯调整覆盖）。

三重校验（①③ 全过才写出 CSV；② 只报告不拦截）
  ① 表内勾稽：损益 / 资产负债 / 现金流 各自恒等式 + 跨年现金连续性
  ② 跨源互证：年报 Y「上年列」 vs 年报 Y-1「本年列」——不等 = 追溯重述 或 解析错，
     逐条列出人工判性质（本公司已知重述见 KNOWN_RESTATEMENTS）
  ③ 锚点核验：年报自家「主要会计数据」披露值 vs 本库三表取值（每年 5 项）

用法：python3 _build_from_pdf.py [--write]     不带 --write 只跑校验不落盘
"""
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
JDIR = os.path.join(HERE, "_extract_json")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import derived  # noqa: E402  通用派生比率底（单一写者架构：本 build 调它 + 加定制行）

FIRST_RESTATED_YEAR = 2006
YEARS = list(range(2006, 2026))
TOL = 1.0        # 元。解析值本应精确相等，留 1 元容分位舍入


# ---------------------------------------------------------------- 已知口径事实
# 【FY2007 净利润印刷错误】年报利润表印 122,187,403.66，但同页两条恒等式都指向
# 112,187,403.66：利润总额 139,617,031.04 − 所得税 27,429,627.38 = 112,187,403.66；
# 归母 125,916,107.23 + 少数 −13,728,703.57 = 112,187,403.66。FY2008 年报比较列
# 亦作 112,187,403.66。故判定为该年年报笔误（十位数 1→2），本库取自洽值并留痕。
OVERRIDES = {
    (2007, "IS", "净利润"): (112187403.66, "FY2007 年报利润表印 122,187,403.66 系笔误；"
                                          "两条恒等式与 FY2008 比较列均为 112,187,403.66"),
}

# 【FY2007 摘要页 vs 审计报表内部打架】年报「前三年主要会计数据」页列
# 总资产 5,220,766,837.41 / 所有者权益(归母) 2,080,434,570.60，
# 均较审计后资产负债表高 38,760.20 元。同一份年报内两处不一致，以**审计报表**为准。
KNOWN_ANCHOR_EXC = {
    (2007, "总资产"): "摘要页较审计 BS 高 38,760.20 元（年报内部不一致，以审计报表为准）",
    (2007, "归母净资产"): "摘要页较审计 BS 高 38,760.20 元（同上）",
}

# 【FY2013 追溯重述】FY2014 年报因**同一控制下企业合并**追溯重述 2013 比较数
# （FY2014 所有者权益变动表：上年期末余额 3,604,097,740.37 + 同一控制下企业合并
#  319,634,525.26），并因准则修订把「其他非流动负债」中的递延收益单独列报、
# 其他综合收益从资本公积拆出（后两项只动列报、不动总资产/负债/净资产/净利润）。
# 本库 2013 列取 as-reported（FY2013 自身年报），重述后口径见 README。
KNOWN_RESTATEMENTS = {2013: "FY2014 年报因同一控制下企业合并追溯重述（另含递延收益/其他综合收益列报调整）"}


def load():
    d = {}
    for y in range(2007, 2026):
        with open(os.path.join(JDIR, f"fy{y}.json"), encoding="utf-8") as f:
            d[y] = json.load(f)["data"]
    return d


RAW = load()


def cur(y, kind, concept):
    v = RAW.get(y, {}).get(kind, {}).get(concept)
    return v[0] if v else None


def prev(y, kind, concept):
    v = RAW.get(y, {}).get(kind, {}).get(concept)
    return v[1] if v and len(v) > 1 else None


def val(year, kind, concept):
    """本库 canonical 取值。"""
    if (year, kind, concept) in OVERRIDES:
        return OVERRIDES[(year, kind, concept)][0]
    if year == FIRST_RESTATED_YEAR:
        return prev(2007, kind, concept)
    return cur(year, kind, concept)


def anchor(y, key):
    v = RAW.get(y, {}).get("ANCHOR", {}).get(key)
    return v[0] if v else None


def anchor_val(year, key):
    """摘要口径取值。2006 走 FY2007 摘要表的**上年（调整后）**列，与三表同源同口径。"""
    if year == FIRST_RESTATED_YEAR:
        v = RAW.get(2007, {}).get("ANCHOR", {}).get(key)
        return v[1] if v and len(v) > 1 else None
    return anchor(year, key)


# ---------------------------------------------------------------- 行定义
# (提取概念键, CSV 科目名)。CSV 用年报全称，且与 scripts/derived.py 的别名层对齐，
# 使通用派生比率能直接前缀匹配到行。

IS_ROWS = [
    # 缩进保留层级可读性；但**不要**加「其中：」前缀——scripts/derived.py 的别名层
    # 是按行名**前缀**匹配的，"其中：营业成本" 会匹配不上 "营业成本"，通用比率里
    # 毛利率/存货周转等会整列变空。
    ("营业总收入", "营业总收入"), ("营业收入", "  营业收入"),
    ("营业总成本", "营业总成本"), ("营业成本", "  营业成本"),
    ("税金及附加", "  税金及附加"), ("销售费用", "  销售费用"), ("管理费用", "  管理费用"),
    ("研发费用", "  研发费用"), ("财务费用", "  财务费用"),
    ("利息费用", "    其中：利息费用"), ("利息收入(财费)", "    其中：利息收入"),
    ("资产减值损失", "资产减值损失"), ("信用减值损失", "信用减值损失"),
    ("其他收益", "其他收益"), ("投资收益", "投资收益"),
    ("公允价值变动收益", "公允价值变动收益"), ("资产处置收益", "资产处置收益"),
    ("营业利润", "营业利润"), ("营业外收入", "营业外收入"), ("营业外支出", "营业外支出"),
    ("利润总额", "利润总额"), ("所得税费用", "所得税费用"), ("净利润", "净利润"),
    ("归母净利润", "归属于母公司股东的净利润"), ("少数股东损益", "少数股东损益"),
    ("综合收益总额", "综合收益总额"),
    ("归母综合收益总额", "  归属于母公司所有者的综合收益总额"),
    ("少数股东综合收益总额", "  归属于少数股东的综合收益总额"),
    ("基本每股收益", "基本每股收益(元/股)"), ("稀释每股收益", "稀释每股收益(元/股)"),
]

BS_ROWS = [
    ("货币资金", "货币资金"), ("交易性金融资产", "交易性金融资产"), ("应收票据", "应收票据"),
    ("应收账款", "应收账款"), ("应收款项融资", "应收款项融资"), ("预付款项", "预付款项"),
    ("其他应收款", "其他应收款"), ("存货", "存货"), ("合同资产", "合同资产"),
    ("一年内到期的非流动资产", "一年内到期的非流动资产"), ("其他流动资产", "其他流动资产"),
    ("流动资产合计", "流动资产合计"),
    ("可供出售金融资产", "可供出售金融资产"), ("其他权益工具投资", "其他权益工具投资"),
    ("其他非流动金融资产", "其他非流动金融资产"), ("长期应收款", "长期应收款"),
    ("长期股权投资", "长期股权投资"), ("投资性房地产", "投资性房地产"),
    ("固定资产", "固定资产"), ("在建工程", "在建工程"), ("工程物资", "工程物资"),
    ("固定资产清理", "固定资产清理"), ("使用权资产", "使用权资产"),
    ("无形资产", "无形资产"), ("开发支出", "开发支出"), ("商誉", "商誉"),
    ("长期待摊费用", "长期待摊费用"), ("递延所得税资产", "递延所得税资产"),
    ("其他非流动资产", "其他非流动资产"), ("非流动资产合计", "非流动资产合计"),
    ("资产总计", "资产总计"),
    ("短期借款", "短期借款"), ("应付票据", "应付票据"), ("应付账款", "应付账款"),
    ("预收款项", "预收款项"), ("合同负债", "合同负债"), ("应付职工薪酬", "应付职工薪酬"),
    ("应交税费", "应交税费"), ("应付利息", "  其中：应付利息"), ("应付股利", "  其中：应付股利"),
    ("其他应付款", "其他应付款"), ("一年内到期的非流动负债", "一年内到期的非流动负债"),
    ("其他流动负债", "其他流动负债"), ("流动负债合计", "流动负债合计"),
    ("长期借款", "长期借款"), ("应付债券", "应付债券"), ("租赁负债", "租赁负债"),
    ("长期应付款", "长期应付款"), ("专项应付款", "专项应付款"), ("预计负债", "预计负债"),
    ("递延收益", "递延收益"), ("递延所得税负债", "递延所得税负债"),
    ("其他非流动负债", "其他非流动负债"), ("非流动负债合计", "非流动负债合计"),
    ("负债合计", "负债合计"),
    ("实收资本(股本)", "实收资本(或股本)"), ("其他权益工具", "其他权益工具"),
    ("资本公积", "资本公积"), ("库存股", "减：库存股"), ("其他综合收益", "其他综合收益"),
    ("专项储备", "专项储备"), ("盈余公积", "盈余公积"), ("未分配利润", "未分配利润"),
    ("外币报表折算差额", "外币报表折算差额"),
    ("归母所有者权益合计", "归属于母公司所有者权益合计"), ("少数股东权益", "少数股东权益"),
    ("所有者权益合计", "所有者权益合计"), ("负债和所有者权益总计", "负债和所有者权益总计"),
]

CF_ROWS = [
    ("销售商品提供劳务收到的现金", "销售商品、提供劳务收到的现金"),
    ("收到的税费返还", "收到的税费返还"),
    ("收到其他与经营活动有关的现金", "收到其他与经营活动有关的现金"),
    ("经营活动现金流入小计", "经营活动现金流入小计"),
    ("购买商品接受劳务支付的现金", "购买商品、接受劳务支付的现金"),
    ("支付给职工的现金", "支付给职工以及为职工支付的现金"),
    ("支付的各项税费", "支付的各项税费"),
    ("支付其他与经营活动有关的现金", "支付其他与经营活动有关的现金"),
    ("经营活动现金流出小计", "经营活动现金流出小计"),
    ("经营活动现金流量净额", "经营活动产生的现金流量净额"),
    ("收回投资收到的现金", "收回投资收到的现金"),
    ("取得投资收益收到的现金", "取得投资收益收到的现金"),
    ("处置长期资产收回现金净额", "处置固定资产、无形资产和其他长期资产收回的现金净额"),
    ("处置子公司收到的现金净额", "处置子公司及其他营业单位收到的现金净额"),
    ("收到其他与投资活动有关的现金", "收到其他与投资活动有关的现金"),
    ("投资活动现金流入小计", "投资活动现金流入小计"),
    ("购建长期资产支付的现金", "购建固定资产、无形资产和其他长期资产支付的现金"),
    ("投资支付的现金", "投资支付的现金"),
    ("取得子公司支付的现金净额", "取得子公司及其他营业单位支付的现金净额"),
    ("支付其他与投资活动有关的现金", "支付其他与投资活动有关的现金"),
    ("投资活动现金流出小计", "投资活动现金流出小计"),
    ("投资活动现金流量净额", "投资活动产生的现金流量净额"),
    ("吸收投资收到的现金", "吸收投资收到的现金"),
    ("子公司吸收少数股东投资", "  其中：子公司吸收少数股东投资收到的现金"),
    ("取得借款收到的现金", "取得借款收到的现金"),
    ("发行债券收到的现金", "发行债券收到的现金"),
    ("收到其他与筹资活动有关的现金", "收到其他与筹资活动有关的现金"),
    ("筹资活动现金流入小计", "筹资活动现金流入小计"),
    ("偿还债务支付的现金", "偿还债务支付的现金"),
    ("分配股利利润或偿付利息支付的现金", "分配股利、利润或偿付利息支付的现金"),
    ("子公司支付给少数股东的股利", "  其中：子公司支付给少数股东的股利、利润"),
    ("支付其他与筹资活动有关的现金", "支付其他与筹资活动有关的现金"),
    ("筹资活动现金流出小计", "筹资活动现金流出小计"),
    ("筹资活动现金流量净额", "筹资活动产生的现金流量净额"),
    ("汇率变动影响", "汇率变动对现金及现金等价物的影响"),
    ("现金及现金等价物净增加额", "现金及现金等价物净增加额"),
    ("期初现金余额", "加：期初现金及现金等价物余额"),
    ("期末现金余额", "期末现金及现金等价物余额"),
]


# ---------------------------------------------------------------- ① 表内勾稽

def s(*xs):
    vs = [x for x in xs if x is not None]
    return sum(vs) if vs else None


def chk(errs, year, name, lhs, rhs, tol=TOL):
    if lhs is None or rhs is None:
        return
    if abs(lhs - rhs) > tol:
        errs.append(f"FY{year} 勾稽✗ {name}: {lhs:,.2f} vs {rhs:,.2f} 差 {lhs - rhs:,.2f}")


def check_internal(year, errs):
    V = lambda k, c: val(year, k, c)
    chk(errs, year, "营业利润+营业外收入-营业外支出=利润总额",
        s(V("IS", "营业利润"), V("IS", "营业外收入")) - (V("IS", "营业外支出") or 0),
        V("IS", "利润总额"))
    chk(errs, year, "利润总额-所得税=净利润",
        (V("IS", "利润总额") or 0) - (V("IS", "所得税费用") or 0), V("IS", "净利润"))
    chk(errs, year, "归母+少数=净利润",
        s(V("IS", "归母净利润"), V("IS", "少数股东损益")), V("IS", "净利润"))
    chk(errs, year, "营业总收入=营业收入", V("IS", "营业总收入"), V("IS", "营业收入"))

    chk(errs, year, "流动+非流动=资产总计",
        s(V("BS", "流动资产合计"), V("BS", "非流动资产合计")), V("BS", "资产总计"))
    chk(errs, year, "流动负债+非流动负债=负债合计",
        s(V("BS", "流动负债合计"), V("BS", "非流动负债合计")), V("BS", "负债合计"))
    chk(errs, year, "归母权益+少数股东权益=所有者权益合计",
        s(V("BS", "归母所有者权益合计"), V("BS", "少数股东权益")), V("BS", "所有者权益合计"))
    chk(errs, year, "负债+权益=负债和所有者权益总计",
        s(V("BS", "负债合计"), V("BS", "所有者权益合计")), V("BS", "负债和所有者权益总计"))
    chk(errs, year, "资产总计=负债和所有者权益总计",
        V("BS", "资产总计"), V("BS", "负债和所有者权益总计"))

    chk(errs, year, "经营流入-流出=经营净额",
        (V("CF", "经营活动现金流入小计") or 0) - (V("CF", "经营活动现金流出小计") or 0),
        V("CF", "经营活动现金流量净额"))
    chk(errs, year, "投资流入-流出=投资净额",
        (V("CF", "投资活动现金流入小计") or 0) - (V("CF", "投资活动现金流出小计") or 0),
        V("CF", "投资活动现金流量净额"))
    chk(errs, year, "筹资流入-流出=筹资净额",
        (V("CF", "筹资活动现金流入小计") or 0) - (V("CF", "筹资活动现金流出小计") or 0),
        V("CF", "筹资活动现金流量净额"))
    chk(errs, year, "三净额+汇率=净增加额",
        s(V("CF", "经营活动现金流量净额"), V("CF", "投资活动现金流量净额"),
          V("CF", "筹资活动现金流量净额"), V("CF", "汇率变动影响")),
        V("CF", "现金及现金等价物净增加额"))
    chk(errs, year, "期初+净增=期末",
        s(V("CF", "期初现金余额"), V("CF", "现金及现金等价物净增加额")),
        V("CF", "期末现金余额"))


# 每年都必须取到的核心行。勾稽恒等式遇 None 会**跳过**而非报错，
# 所以单个明细科目整列丢失（如「固定资产」2012-2015 因附注号残留匹配不上）
# 能一路瞒过 ①③——必须单独设完整性闸。
REQUIRED = [
    ("IS", "营业总收入"), ("IS", "营业成本"), ("IS", "营业利润"), ("IS", "利润总额"),
    ("IS", "净利润"), ("IS", "归母净利润"),
    ("BS", "货币资金"), ("BS", "应收账款"), ("BS", "存货"), ("BS", "固定资产"),
    ("BS", "在建工程"), ("BS", "流动资产合计"), ("BS", "非流动资产合计"), ("BS", "资产总计"),
    ("BS", "流动负债合计"), ("BS", "非流动负债合计"), ("BS", "负债合计"),
    ("BS", "实收资本(股本)"), ("BS", "归母所有者权益合计"), ("BS", "少数股东权益"),
    ("BS", "所有者权益合计"), ("BS", "负债和所有者权益总计"), ("BS", "短期借款"),
    ("CF", "销售商品提供劳务收到的现金"), ("CF", "经营活动现金流量净额"),
    ("CF", "投资活动现金流量净额"), ("CF", "筹资活动现金流量净额"),
    ("CF", "购建长期资产支付的现金"), ("CF", "期末现金余额"),
]


def check_required(errs):
    for kind, c in REQUIRED:
        missing = [y for y in YEARS if val(y, kind, c) is None]
        if missing:
            errs.append(f"完整性✗ {kind}/{c} 缺 {len(missing)} 年：{missing}")


def check_continuity(errs, noted):
    for y in YEARS[:-1]:
        a, b = val(y, "CF", "期末现金余额"), val(y + 1, "CF", "期初现金余额")
        if a is None or b is None or abs(a - b) <= TOL:
            continue
        line = f"FY{y}→{y+1} 现金连续性 期末 {a:,.2f} vs 次年期初 {b:,.2f} 差 {b - a:,.2f}"
        if y in KNOWN_RESTATEMENTS:
            # 追溯重述会把被合并方的期初现金并进次年比较期，断点是**预期的**
            noted.append(line + f"  ← 已知：{KNOWN_RESTATEMENTS[y]}（并入被合并方期初现金）")
        else:
            errs.append(line.replace("现金连续性", "现金连续性✗"))


# ---------------------------------------------------------------- ② 跨源互证

XSRC = [("IS", "营业收入"), ("IS", "归母净利润"), ("IS", "净利润"),
        ("BS", "资产总计"), ("BS", "归母所有者权益合计"), ("BS", "负债合计"),
        ("CF", "经营活动现金流量净额")]


def check_cross_source():
    out = []
    for y in range(2008, 2026):
        for kind, c in XSRC:
            a, b = prev(y, kind, c), val(y - 1, kind, c)
            if a is None or b is None or abs(a - b) <= TOL:
                continue
            out.append((y - 1, kind, c, b, a, a - b))
    return out


# ---------------------------------------------------------------- ③ 锚点核验

ANCHOR_MAP = [("营业收入", "IS", "营业收入"), ("归母净利润", "IS", "归母净利润"),
              ("经营现金流量净额", "CF", "经营活动现金流量净额"),
              ("归母净资产", "BS", "归母所有者权益合计"), ("总资产", "BS", "资产总计")]


def check_anchors():
    bad, noted = [], []
    for y in range(2007, 2026):
        for ak, kind, c in ANCHOR_MAP:
            av, tv = anchor(y, ak), val(y, kind, c)
            if av is None or tv is None or abs(av - tv) <= TOL:
                continue
            line = f"FY{y} {ak}: 摘要 {av:,.2f} vs 三表 {tv:,.2f} 差 {av - tv:,.2f}"
            (noted if (y, ak) in KNOWN_ANCHOR_EXC else bad).append(
                line + (f"  ← 已知：{KNOWN_ANCHOR_EXC[(y, ak)]}" if (y, ak) in KNOWN_ANCHOR_EXC else ""))
    return bad, noted


# ---------------------------------------------------------------- 输出

def write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def fmt(v, nd=2):
    return "" if v is None else f"{v:.{nd}f}"


def build_table(kind, rowdefs):
    return [[disp] + [fmt(val(y, kind, key)) for y in YEARS] for key, disp in rowdefs]


def main():
    write = "--write" in sys.argv
    errs, noted_cont = [], []
    for y in YEARS:
        check_internal(y, errs)
    check_continuity(errs, noted_cont)
    check_required(errs)
    bad_anchor, noted_anchor = check_anchors()
    diffs = check_cross_source()

    print(f"=== ① 表内勾稽 + 完整性 + 跨年连续性：{len(errs)} 处不平"
          f"（另 {len(noted_cont)} 处已知重述断点）")
    for e in errs + noted_cont:
        print("   " + e)
    print(f"=== ③ 锚点核验：{len(bad_anchor)} 处未解释不符（另 {len(noted_anchor)} 处已知口径差）")
    for e in bad_anchor + noted_anchor:
        print("   " + e)
    print(f"=== ② 跨源互证（上年列 vs 本库该年值）：{len(diffs)} 处差异")
    for y, kind, c, b, a, d in diffs:
        tag = f"  ← 已知：{KNOWN_RESTATEMENTS[y]}" if y in KNOWN_RESTATEMENTS else "  ⚠️未解释"
        print(f"   FY{y} {kind}/{c}: 本库(as-reported) {b:,.2f} → 次年比较列 {a:,.2f} 差 {d:,.2f}{tag}")

    if errs or bad_anchor:
        print("\n🔴 校验未通过，不写出 CSV（先回查 PDF）")
        return 1
    print(f"\n✅ ①③ 全过（{len(OVERRIDES)} 处 OVERRIDE、{len(KNOWN_ANCHOR_EXC)} 处已知锚点差已留痕）")
    if not write:
        print("（未加 --write，仅校验）")
        return 0

    header = ["科目"] + [str(y) for y in YEARS]
    is_rows = build_table("IS", IS_ROWS)
    # 扣非归母只在「主要会计数据」摘要里有，利润表无此行 → 追加为末行
    is_rows.append(["扣非归母净利润(摘要披露)"] +
                   [fmt(anchor_val(y, "扣非归母净利润")) for y in YEARS])
    bs_rows = build_table("BS", BS_ROWS)
    cf_rows = build_table("CF", CF_ROWS)
    write_csv(os.path.join(HERE, "利润表.csv"), header, is_rows)
    write_csv(os.path.join(HERE, "资产负债表.csv"), header, bs_rows)
    write_csv(os.path.join(HERE, "现金流量表.csv"), header, cf_rows)

    # ---- 财务比率：通用底(scripts/derived.py) + 本公司定制层
    def as_dict(rows):
        return {r[0].strip(): [None if c == "" else float(c) for c in r[1:]] for r in rows}

    PL, BS, CF = as_dict(is_rows), as_dict(bs_rows), as_dict(cf_rows)
    common, unmatched = derived.compute_common_ratios(PL, BS, CF)

    def fmt_ratio(v, f):
        """derived 返回的是**分数**，fmt 只是显示提示 —— 落 CSV 必须按提示换算，
        否则毛利率会写成 0.18 而不是 18.35，与其他公司库的 CSV 口径不一致。"""
        if v is None:
            return ""
        if f == "pct":
            return f"{v * 100:.2f}"
        if f == "day":
            return f"{v:.1f}"
        return f"{v:.3f}"

    ratio_rows = [[n + ("(%)" if f == "pct" else "")] + [fmt_ratio(v, f) for v in vals]
                  for n, vals, f in common]

    def series(fn):
        return [fn(i) for i in range(len(YEARS))]

    def get(tbl, name):
        return tbl.get(name, [None] * len(YEARS))

    ni = get(PL, "净利润")
    parent = get(PL, "归属于母公司股东的净利润")
    minor = get(PL, "少数股东损益")
    kf = get(PL, "扣非归母净利润(摘要披露)")
    eq_min = get(BS, "少数股东权益")
    eq_tot = get(BS, "所有者权益合计")
    ta = get(BS, "资产总计")
    sb = get(BS, "短期借款")
    ny = get(BS, "一年内到期的非流动负债")
    lb = get(BS, "长期借款")
    bd = get(BS, "应付债券")
    lease = get(BS, "租赁负债")
    cash = get(BS, "货币资金")
    cip = get(BS, "在建工程")
    fa = get(BS, "固定资产")
    div_paid = get(CF, "分配股利、利润或偿付利息支付的现金")
    div_minor = get(CF, "其中：子公司支付给少数股东的股利、利润")
    int_exp = get(PL, "其中：利息费用")

    def d(a, b, k=100.0):
        return [None if (a[i] is None or not b[i]) else a[i] / b[i] * k for i in range(len(YEARS))]

    def add(a):
        return [None if all(x[i] is None for x in a) else sum((x[i] or 0) for x in a)
                for i in range(len(YEARS))]

    ib = add([sb, ny, lb, bd, lease])
    custom = [
        ("少数股东损益/净利润(%·少数股东leak)", d(minor, ni)),
        ("少数股东权益/所有者权益合计(%)", d(eq_min, eq_tot)),
        ("扣非归母/归母净利润(%)", d(kf, parent)),
        ("有息负债(短借+一年内+长借+应付债券+租赁负债,元)", ib),
        ("有息负债/总资产(%)", d(ib, ta)),
        ("货币资金-有息负债(净现金,元)", [None if (cash[i] is None or ib[i] is None)
                                    else cash[i] - ib[i] for i in range(len(YEARS))]),
        ("在建工程/固定资产(%)", d(cip, fa)),
        # 通用底的「当年分红率」分子用现金流量表「分配股利、利润或偿付利息支付的现金」，
        # 该行**含付息、且含子公司付给少数股东的股利**，对本公司(有息负债重、少数股东占两成)
        # 高估尤其明显。这里剔掉两块给个更贴近母公司派现的估算值；
        # 精确派现仍以分红预案公告为准（本行仅供量级参考）。
        # 只在**利息费用有单独披露的年份**（2018 起，此前财务费用不拆分）才给值：
        # 缺了利息这一大块的年份若照算，会把付息当成分红、数量级整个错，
        # 早年凭空多出上亿"分红"——宁可留空也不给会被误读的数。
        ("母公司现金分红(剔付息与少数股东·估算,元)",
         [None if (div_paid[i] is None or int_exp[i] is None) else
          div_paid[i] - int_exp[i] - (div_minor[i] or 0) for i in range(len(YEARS))]),
    ]
    ratio_rows += [[n] + [fmt(v, 2) for v in vals] for n, vals in custom]
    write_csv(os.path.join(HERE, "财务比率.csv"), header, ratio_rows)
    if unmatched:
        print(f"⚠️ derived 未匹配科目：{unmatched}")
    print("已写出 利润表.csv / 资产负债表.csv / 现金流量表.csv / 财务比率.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
