#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""李宁三表构建器 —— 别名层 + 勾稽校验 + 跨年交叉核 + 写出 CSV。

    python3 _build_from_pdf.py            # 校验 + 写出
    python3 _build_from_pdf.py --check    # 只校验不写（gate 用）
    python3 _build_from_pdf.py --xcheck   # 附跨年交叉核明细

数据血缘
--------
  2001-2003  `report/李宁/李宁-招股说明书.pdf` 附录一会计师报告（PwC，2004-06-15）
             —— 上市前三年经审计「综合」数（combined），上市 2004-06-28 前唯一真源
  2004-2025  `report/李宁/李宁-YYYY.pdf` 各年年报，**一律取该年年报的本年列**
             （as-reported）。比较列只用于跨年交叉核，不入 CSV。

为什么不取比较列：比较列是重述后的。本库实测李宁至少 4 处重述（见 README
「口径断点」），如 FY2013 年报把 2012 营收由 6,738,911 改列为 6,676,441 千元、
FY2015 年报把 2014 营收由 6,727,601 改列为 6,047,195 千元（终止经营重分类）。
混用两种列会让序列既不是 as-reported 也不是 like-for-like。

单位：原始报表一律 RMB'000，本文件统一 ÷1000 换算为**人民币百万元**（与同业
`finance/安踏体育` 对齐，便于横比）。负数 = 流出/减项，空 = 该期财报无此科目。
"""
import csv
import os
import re
import sys

import _parse_core as C

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

SCALE = 1000.0          # RMB'000 → RMB 百万元

# 记录「按恒等式补出、非报表原印」的格，供校验跳过自证式检查、供 README 标注
DERIVED = set()


# ───────────────────── 别名层：中文科目 ← 英文标签正则 ─────────────────────
#
# mode: "first" 取首个命中行（默认）；"sum" 把全部命中行相加
#   —— "sum" 是必需的：2010-2017 资产负债表把非流动与流动的 `Borrowings` 印成
#      两行同名，取首个只拿到非流动那半截。
#
# 注意：正则一律用 re.search（非 fullmatch）。原因有三 ——
#   ① 2008 起明细行带前导 `- `（`- purchases of property plant and equipment`）
#   ② 2006 现金流有一行被印刷页码污染（`74 net cash generated from/(used in) in
#      investing activities`）
#   ③ 2005/2008 字间插空格，需靠 despace 变体命中（见 C.despace）

IS_PICK = [
    ("营业额",            [r"^(turnover|revenue)$"], "first"),
    ("销售成本",          [r"^costs? of sales$"], "first"),
    ("毛利",              [r"^gross profit$"], "first"),
    ("其他收入及收益净额", [r"^other income and other gains", r"^other income( - net)?$",
                          r"^other revenue$"], "first"),
    ("销售及分销开支",    [r"^(selling and )?distribution (expenses|costs)$"], "first"),
    ("行政开支",          [r"^administrative expenses$"], "first"),
    ("其他经营开支",      [r"^other operating (expenses|income/\(expenses\))$"], "first"),
    ("金融资产减值拨备净额", [r"expected credit loss allowance",
                            r"^reversal of impairment losses on financial assets"], "first"),
    ("经营溢利",          [r"^operating (profit|loss|\(loss\)/profit|profit/\(loss\))$"], "first"),
    # ⚠️ 必须**强制要求行尾是 net**。多数年份同时印 `Finance income` /
    #    `Finance expenses` / `Finance income - net` 三行，取首个会拿到**毛额**
    #    （2025 取到 296,709 而净额只有 33,118）。这种错三表勾稽一条都拦不住，
    #    只有新增的「损益④ 经营+财务净额+应占联营 = 除税前」能逮到。
    #    全 25 年逐年确认过：每年都印了 net 行，故不需要毛额兜底。
    ("财务收入净额",      [r"^finance .*net$"], "first"),
    # sum：AR2025（安永房式）把应占损益拆成 associates 208,823 + joint ventures
    # 49,074 两行；取首个只拿 208,823，与「除税前 = 经营 + 财务净额 + 应占」差
    # 49,074 千元。2024 年及以前是合并一行，sum 对单行等价、无副作用。
    ("应占联营合营溢利",  [r"^share of (profit|loss)"], "sum"),
    ("除税前溢利",        [r"^(profit|loss|\(loss\)/profit|profit/\(loss\)) before (income tax|taxation|tax)$"], "first"),
    ("所得税开支",        [r"^(income tax expense|taxation)$"], "first"),
    ("持续经营溢利",      [r"for the year from continuing operations$",
                          r"^profit from continuing operations$"], "first"),
    ("终止经营溢利",      [r"for the year from discontinued operations$",
                          r"^profit from discontinued operations$"], "first"),
    # ⚠️ mode="last"：2016 利润表里 `profit for the year` 出现 **3 次** ——
    #    首个 132,157 是「终止经营业务」内部的拆分项（132,157 + 处置收益 313,201
    #    = 终止经营溢利 445,358），真正的年内溢利总额 700,869 印在最后。
    #    取 first 会把一个子项当成全年净利（实测差 568,712 千元）。合计行永远在
    #    组成项之后，故 last 是结构性正确的选择。
    ("年内溢利",          [r"^(profit|loss|\(loss\)/profit|profit/\(loss\)) for the y ?ear$",
                          r"^profit after taxation$"], "last"),
    # 反过来这两行必须 first：2015 表内「溢利归属」与「全面收益总额归属」两段
    # 同名，母公司应占分别是 14,309 与 13,319，后者是全面收益不是溢利。
    ("母公司拥有人应占溢利", [r"^e ?quity holders of the company$",
                            r"^owners of the (parent|company)$"], "first"),
    ("非控股权益应占溢利", [r"^(non-controlling|minor ?ity) interests$"], "first"),
]

BS_PICK = [
    ("物业、厂房及设备",  [r"^property plant and equipmen ?t$"], "first"),
    ("使用权资产",        [r"^right-of-use assets$"], "first"),
    ("投资物业",          [r"^investment properties$"], "first"),
    ("土地使用权",        [r"^land use rights$"], "first"),
    ("无形资产",          [r"^intangible assets$"], "first"),
    ("以权益法入账的投资", [r"^investments accounted for using the equity method$",
                          r"^investment in an? associates?$", r"^investment in associates$"], "first"),
    ("递延所得税资产",    [r"^deferred income tax assets$"], "first"),
    ("非流动资产总额",    [r"^total non-current assets$"], "first"),
    ("存货",              [r"^inventories$"], "first"),
    ("贸易应收款项",      [r"^trade receivables$", r"^accounts (and not ?es )?receivable$"], "first"),
    # sum：2010 起把「其他应收款及预付款项」拆成非流动 + 流动两行同名（2019 起
    # 又改叫 other receivables / other assets）。只取首个 = 只拿到非流动那半截。
    ("其他应收款及预付款项", [r"^other receivables( and prepayments)?( - current portion)?$"], "sum"),
    ("受限制银行存款",    [r"^restricted bank deposits$", r"^pledged bank deposits$"], "first"),
    # ⚠️ `( - current portion)?` 不能省：2024 年报把存款印成 `term bank deposits`
    #    + `term bank deposits - current portion`，漏掉后缀那行 → 2023 年定期存款
    #    只算到 9,037 而真值 12,531 百万元（跨年交叉核逮到的，差 3,494）。
    ("定期/长期银行存款", [r"^(short-term|long-term|term|time) (bank )?deposits( - current portion)?$",
                          r"^fixed deposits held at banks$",
                          r"^bank deposits with the maturity over one year$"], "sum"),
    ("现金及现金等价物",  [r"^cash and cash equivalents$", r"^cash at banks? and in hand$"], "first"),
    ("流动资产总额",      [r"^total current assets$"], "first"),
    ("资产总计",          [r"^total assets$"], "first"),
    ("股本",              [r"^ordinary shares$", r"^share capital$", r"^issued capital$"], "first"),
    ("股份溢价",          [r"^share premium$"], "first"),
    # 2001-2005 只印一行合并的 `Reserves`（**含股份溢价与保留溢利**），2006 起才
    # 拆成 share premium / other reserves / retained earnings 三行。两代口径不可
    # 并入同一行：曾把 2005 的合并储备 1,052 百万当「其他储备」，与 2006 年报的
    # 2005 比较列 159 百万相差 893 —— 那不是重述，是我把两个不同的量画上了等号。
    ("储备合计(旧版式)",  [r"^reser ?ves$"], "first"),
    ("其他储备",          [r"^other reserves$"], "first"),
    ("持作限制性股份计划之股份", [r"^shares held for restricted share award scheme$",
                              r"^treasury shares$"], "sum"),
    # sum：2006-2011 把保留溢利拆成「- proposed final dividend」「- others」两行
    # （母行不带数字，已由 _parse_core 的分组表头机制冠回「retained earnings - …」）。
    # 科目名两代：2006-2011 叫 `Retained profits`，2012 起叫 `Retained earnings`。
    ("保留溢利/累计亏损", [r"^retained (earnings|profits)( .*)?$", r"^accumulated deficit$",
                          r"^\(accumulated deficit\)/retained earnings$",
                          r"^retained earnings/\(accumulated deficit\)$"], "sum"),
    ("非控股权益",        [r"^non-controlling interests in equity$",
                          r"^minority interests( in equity)?$"], "first"),
    # 招股书(2001-2003)与 2004 年报用旧版式：只印「Owners'/Shareholders' equity」
    # （**不含**少数股东权益）+ 单列 minority interests，**没有 Total equity 行**。
    # 两者必须分开映射，否则「负债+权益=资产」恒差一个少数股东权益（实测
    # 2001 差 16.197、2002 差 17.295、2003 差 15.869 百万元）。
    ("母公司拥有人应占权益", [r"^(owners'|shareholders') equity$"], "first"),
    ("权益总额",          [r"^total equity$"], "first"),
    ("贸易应付款项",      [r"^trade payables$"], "first"),
    ("其他应付款项及应计费用", [r"^other payables and accruals$"], "first"),
    ("合同负债",          [r"^contract liabilities$"], "first"),
    ("借款",              [r"^borrowings$", r"^short-term borrowings$"], "sum"),
    ("可换股债券",        [r"^convertible bonds$"], "sum"),
    ("租赁负债",          [r"^lease liabilities( - current portion)?$"], "sum"),
    ("特许权使用费应付款", [r"^lic[eo]nce fees payable( -? ?current portion)?$"], "sum"),
    ("递延所得税负债",    [r"^deferred income tax liabilities$"], "first"),
    ("流动负债总额",      [r"^total current liabilities$"], "first"),
    ("非流动负债总额",    [r"^total non-current liabilities$"], "first"),
    ("负债总额",          [r"^total liabilities$"], "first"),
]

CF_PICK = [
    ("经营所得现金(税前)", [r"^cash (inflow )?(generated from|used in|\(used in\)/generated from"
                           r"|generated from/\(used in\)) operations$"], "first"),
    ("已付所得税",        [r"^income tax \(?paid\)?", r"^income tax received/\(paid\)$"], "first"),
    # ⚠️ 三条合计必须 `^net cash` 锚定行首。2019-2021 现金流表里有明细行
    #    `- net cash used in other investing activities`，它排在合计行**前面**，
    #    不锚行首就会被抢先命中：2021 取到 −7,441 而真值 −6,538,700，
    #    「经营+投资+融资 = 净变动」因此差 6,531,259 千元。
    #    （2006 年报把印刷页码印在合计行左边，已由 norm_label 剥掉行首数字。）
    # 行名须命中 scripts/derived.py 的科目别名表（前缀匹配），否则通用底算不出
    # OCF/capex 相关比率。「经营活动所得现金净额」「购买物业厂房设备」是别名表里
    # 已有的写法，别改成同义但不在表里的说法。
    ("经营活动所得现金净额", [r"^net cash .*operating activities$"], "first"),
    ("投资活动所得现金净额", [r"^net cash .*investing activities$"], "first"),
    ("融资活动所得现金净额", [r"^net cash .*financing activities$"], "first"),
    ("购买物业厂房设备",  [r"purchases? of property plant and equipment$"], "first"),
    ("购买无形资产",      [r"purchases? of intangible assets$"], "first"),
    ("购买土地使用权",    [r"purchases? of land use rights$"], "first"),
    ("已付利息",          [r"^-? ?interest paid$"], "first"),
    ("已付股息",          [r"^-? ?dividends paid$",
                          r"^- dividends paid to equity holders of the company$"], "first"),
    ("现金净变动",        [r"^(net )?(increase|decrease|\(decrease\)/increase"
                          r"|increase/\(decrease\)|decrease/\(increase\))"
                          r".*in cash and cash equivalents$"], "first"),
    ("期初现金",          [r"^c ?ash and cash equivalents at beginning of (the )?year$"], "first"),
    # 2015-2017 把「划归持作出售组别的现金」单列在期末现金之前，它是现金余额
    # 调节链的一环（2015 −176,693 / 2016 −204,314 千元）。不纳入 →「期初+净变动
    # +汇率=期末」必不平，且差额正好等于它。
    ("划归持作出售之现金", [r"^cash of disposal group classified as held for sale$"], "first"),
    # 2005 年报把汇率行印成 `e xchange difference`（既无 "on cash…" 尾巴、
    # 字间还插了空格）→ 漏掉它，「期初+净变动+汇率=期末」差 2,775 千元。
    ("汇率影响",          [r"^e ?xchange .*on cash and cash equivalents$",
                          r"^e ?xchange (difference|differences|losses|gains)$",
                          r"^effect of foreign exchange rate changes"], "first"),
    ("期末现金",          [r"^c ?ash and cash equivalents at end of (the )?year$"], "first"),
]

PICKS = {"IS": IS_PICK, "BS": BS_PICK, "CF": CF_PICK}


# ───────────────────────────── 取数 ─────────────────────────────

def _match(label, pats):
    """标签是否命中任一 pattern。两路都比：原样 + 去空格（坑②字间插空格）。"""
    flat = C.despace(label)
    for p in pats:
        if re.search(p, label) or re.search(C.despace(p), flat):
            return True
    return False


def extract(name, kind, want_year):
    """从某份 PDF 的某张表取 want_year 那一列 → {中文科目: 百万元}。

    重复年份（IAS 1 三栏式，2013 年报印 `2013 2012 2012`）取**第一个**等于
    want_year 的列 —— 第二个 2012 是 1 January 期初重述列，不是本年列。
    """
    got = C.statement(name, kind)
    if not got:
        raise SystemExit(f"🔴 {name}/{kind} 未定位到正表")
    anchors, rows = got
    idx = next((i for i, (y, _) in enumerate(anchors) if y == want_year), None)
    if idx is None:
        raise SystemExit(f"🔴 {name}/{kind} 表头无 {want_year} 列（实际 {[y for y,_ in anchors]}）")
    out, hits = {}, {}
    for zh, pats, mode in PICKS[kind]:
        vals = [r[1][idx] for r in rows
                if _match(r[0], pats) and idx < len(r[1]) and r[1][idx] is not None]
        if not vals:
            continue
        v = {"sum": sum(vals), "last": vals[-1]}.get(mode, vals[0])
        out[zh] = v / SCALE
        hits[zh] = [r[0] for r in rows if _match(r[0], pats)]

    # ── 旧版式利润表（2001-2004）的主体口径翻转 ──────────────────────────
    # 旧版（HK GAAP 时期）列报顺序是：
    #     Profit before taxation / Taxation / **Profit after taxation**
    #     / Minority interests (扣减) / **Profit for the year**
    # 即 `Profit after taxation` 才是**集团**净利，`Profit for the year` 是扣掉
    # 少数股东后的**归母**，Minority interests 印成负的扣减行。
    # 新版（2005 起）反过来：`Profit for the year` 是集团总额，下面才是
    #     Attributable to: Equity holders of the Company / Non-controlling interests
    # 不分辨就会把归母当集团净利（2004 实测差 1,339 千元 = 少数股东损益），
    # 且 2001-2004 的 ROE/净利率分母全错。
    if kind == "IS" and any(_match(r[0], [r"^profit after taxation$"]) for r in rows):
        def pick(pats, take_last=False):
            vs = [r[1][idx] for r in rows
                  if _match(r[0], pats) and idx < len(r[1]) and r[1][idx] is not None]
            return (vs[-1] if take_last else vs[0]) / SCALE if vs else None
        grp = pick([r"^profit after taxation$"])
        par = pick([r"^profit for the y ?ear$"], take_last=True)
        mi = pick([r"^minor ?ity interests$"])
        if grp is not None:
            out["年内溢利"] = grp
        if par is not None:
            out["母公司拥有人应占溢利"] = par
        if mi is not None:
            out["非控股权益应占溢利"] = -mi       # 扣减行 → 归属份额，翻正负号

    # 母公司拥有人应占权益：2005 年起的版式不印这一小计行（只印 Total equity +
    # 非控股权益）。IFRS 下「权益总额 = 母公司应占 + 非控股」是**恒等式**不是估算，
    # 故在未印出时按恒等式补出，供 ROE(归母) 等派生使用；README 已标注该行来源。
    # 两代版式各缺一行，用 IFRS 恒等式「权益总额 = 母公司应占 + 非控股」互补：
    #   2005 起只印 Total equity（缺母公司应占小计）
    #   2001-2004 只印 Owners' equity（缺权益总额）
    # 这是恒等式不是估算；补出的格记进 DERIVED，README 标注，且不参与自证式校验。
    if kind == "BS":
        nci = out.get("非控股权益") or 0.0
        if "母公司拥有人应占权益" not in out and out.get("权益总额") is not None:
            out["母公司拥有人应占权益"] = out["权益总额"] - nci
            DERIVED.add((kind, want_year, "母公司拥有人应占权益"))
        elif "权益总额" not in out and out.get("母公司拥有人应占权益") is not None:
            out["权益总额"] = out["母公司拥有人应占权益"] + nci
            DERIVED.add((kind, want_year, "权益总额"))
    return out, hits


# ───────────────────────────── 勾稽校验 ─────────────────────────────

TOL = 0.55      # 百万元。原始数千元取整 ÷1000 后，合计行可有 ±0.5 级舍入残差


def _chk(fails, year, tag, lhs, rhs, a, b):
    if a is None or b is None:
        return None
    if abs(a - b) > TOL:
        fails.append(f"{year} {tag}: {lhs}={a:,.3f} vs {rhs}={b:,.3f} 差 {a-b:,.3f}")
        return False
    return True


def validate(year, IS, BS, CF, fails):
    n = 0
    g = lambda d, k: d.get(k)

    # ---- 损益：成本为负数，故毛利 = 营业额 + 销售成本 ----
    if g(IS, "营业额") is not None and g(IS, "销售成本") is not None:
        n += 1; _chk(fails, year, "损益①", "营业额+销售成本", "毛利",
                     IS["营业额"] + IS["销售成本"], g(IS, "毛利"))
    # 损益②：**必须把终止经营那一段算进来**。2015/2016 有终止经营业务，
    # 「除税前 + 所得税」只等于**持续经营**溢利；不加 终止经营溢利 会分别差
    # 104,559 / 445,358 千元，看着像解析错，其实是列报结构。
    if g(IS, "除税前溢利") is not None and g(IS, "所得税开支") is not None:
        cont = IS["除税前溢利"] + IS["所得税开支"]
        if g(IS, "持续经营溢利") is not None:
            n += 1; _chk(fails, year, "损益②a", "除税前+所得税", "持续经营溢利",
                         cont, IS["持续经营溢利"])
        n += 1; _chk(fails, year, "损益②b", "持续经营+终止经营", "年内溢利",
                     cont + (g(IS, "终止经营溢利") or 0.0), g(IS, "年内溢利"))
    # 损益④ 经营溢利 → 除税前 的桥。这条是**毛额/净额混淆探测器**：
    # 「财务收入净额」若误取成 Finance income 毛额，前面三条勾稽全都照样平
    # （它们不碰这一段），只有这条会炸。2025 实测差 263,591 千元 = 财务费用毛额。
    if (g(IS, "经营溢利") is not None and g(IS, "除税前溢利") is not None
            and g(IS, "财务收入净额") is not None):
        n += 1; _chk(fails, year, "损益④", "经营+财务净额+应占联营", "除税前溢利",
                     IS["经营溢利"] + IS["财务收入净额"] + (g(IS, "应占联营合营溢利") or 0.0),
                     IS["除税前溢利"])

    if g(IS, "母公司拥有人应占溢利") is not None and g(IS, "非控股权益应占溢利") is not None:
        n += 1; _chk(fails, year, "损益③", "母公司应占+非控股", "年内溢利",
                     IS["母公司拥有人应占溢利"] + IS["非控股权益应占溢利"], g(IS, "年内溢利"))

    # ---- 资产负债 ----
    if g(BS, "非流动资产总额") is not None and g(BS, "流动资产总额") is not None:
        n += 1; _chk(fails, year, "资负①", "非流动+流动资产", "资产总计",
                     BS["非流动资产总额"] + BS["流动资产总额"], g(BS, "资产总计"))
    # 资负②：权益口径要按版式取。新版式印 Total equity（已含非控股）；
    # 旧版式（招股书 2001-2003 / 2004 年报）只印 Owners' equity（不含非控股）
    # 并把 minority interests 单列 —— 此时权益总额 = 母公司应占 + 非控股。
    eq = g(BS, "权益总额")
    if eq is None and g(BS, "母公司拥有人应占权益") is not None:
        eq = BS["母公司拥有人应占权益"] + (g(BS, "非控股权益") or 0.0)
    if g(BS, "负债总额") is not None and eq is not None:
        n += 1; _chk(fails, year, "资负②", "负债+权益", "资产总计",
                     BS["负债总额"] + eq, g(BS, "资产总计"))
    # 资负⑤ 权益构成：把抓到的权益分项加总，必须等于权益总额。
    # 这条是**漏抓探测器** —— 前面几条勾稽只对小计，某个权益分项整行没抓到也照样
    # 平账；只有把分项加起来对小计，漏抓才会现形。
    comp = [g(BS, k) for k in ("股本", "股份溢价", "储备合计(旧版式)", "其他储备",
                               "持作限制性股份计划之股份", "保留溢利/累计亏损",
                               "非控股权益")]
    eq_tot = g(BS, "权益总额")
    if eq_tot is None and g(BS, "母公司拥有人应占权益") is not None:
        eq_tot = BS["母公司拥有人应占权益"] + (g(BS, "非控股权益") or 0.0)
    if eq_tot is not None and any(c is not None for c in comp):
        n += 1; _chk(fails, year, "资负⑤", "权益分项之和", "权益总额",
                     sum(c for c in comp if c is not None), eq_tot)

    # 资负④只在**两个数都是报表原印**时才有判别力；母公司应占权益若是按恒等式
    # 补出的，这条就是自证，跑了也证明不了任何事。
    if (g(BS, "权益总额") is not None and g(BS, "母公司拥有人应占权益") is not None
            and ("BS", year, "母公司拥有人应占权益") not in DERIVED):
        n += 1; _chk(fails, year, "资负④", "母公司应占+非控股", "权益总额",
                     BS["母公司拥有人应占权益"] + (g(BS, "非控股权益") or 0.0),
                     BS["权益总额"])
    if g(BS, "流动负债总额") is not None and g(BS, "非流动负债总额") is not None:
        n += 1; _chk(fails, year, "资负③", "流动+非流动负债", "负债总额",
                     BS["流动负债总额"] + BS["非流动负债总额"], g(BS, "负债总额"))

    # ---- 现金流 ----
    if all(g(CF, k) is not None for k in ("经营活动所得现金净额", "投资活动所得现金净额",
                                          "融资活动所得现金净额")):
        n += 1; _chk(fails, year, "现流①", "经营+投资+融资", "现金净变动",
                     CF["经营活动所得现金净额"] + CF["投资活动所得现金净额"]
                     + CF["融资活动所得现金净额"],
                     g(CF, "现金净变动"))
    if g(CF, "期初现金") is not None and g(CF, "现金净变动") is not None:
        n += 1; _chk(fails, year, "现流②", "期初+净变动+汇率+持作出售", "期末现金",
                     CF["期初现金"] + CF["现金净变动"] + (g(CF, "汇率影响") or 0.0)
                     + (g(CF, "划归持作出售之现金") or 0.0),
                     g(CF, "期末现金"))

    # ---- 跨表：现金流表期末现金 == 资产负债表现金及现金等价物 ----
    if g(CF, "期末现金") is not None and g(BS, "现金及现金等价物") is not None:
        n += 1; _chk(fails, year, "跨表①", "CF期末现金", "BS现金及等价物",
                     CF["期末现金"], BS["现金及现金等价物"])
    return n


# ───────────────────────────── 主流程 ─────────────────────────────

def build():
    data = {"IS": {}, "BS": {}, "CF": {}}
    hits_log = {}
    for kind in ("IS", "BS", "CF"):
        for y in C.PRE_IPO:
            data[kind][y], _ = extract(C.PROSPECTUS, kind, y)
        for y in C.AR_YEARS:
            data[kind][y], h = extract(C.ar_name(y), kind, y)
            if y == C.AR_YEARS[-1]:
                hits_log[kind] = h
    return data, hits_log


def cross_check(data):
    """第三轨：AR(Y) 本年列 vs AR(Y+1) 上年比较列。差异 = 解析错 **或** 真重述。"""
    diffs = []
    cells = 0
    for kind in ("IS", "BS", "CF"):
        for y in C.AR_YEARS[:-1]:
            try:
                prior, _ = extract(C.ar_name(y + 1), kind, y)
            except SystemExit:
                continue
            cur = data[kind][y]
            for k, v in cur.items():
                if k not in prior:
                    continue
                cells += 1
                if abs(v - prior[k]) > max(TOL, abs(v) * 0.0005):
                    diffs.append((kind, y, k, v, prior[k]))
    return cells, diffs


# ───────────────────────── 分部（分产品）营收 ─────────────────────────
#
# 披露位置：MD&A 的「Revenue breakdown by product category」（非财务报表附注）。
# 三代叫法：Accessories(2004-2007) / Equipment/accessories(2008-2019) /
#           Equipment and accessories(2020-)。
#
# ⚠️ **不能无条件用「分产品和 = 营业额」当 gate**：2008-2015 年报按品牌分层披露
#    （李宁 / 红双喜 / Lotto / 其他），其中 **2015 只有李宁品牌拆了产品、集团合计
#    没拆**（李宁品牌 6,971,894 vs 集团 7,089,495）。硬套等式会把这一年判成解析
#    错而丢掉。做法：取「和最大的那一组三元组」，并把 **覆盖率 = 分产品和÷营业额**
#    作为一行写进 CSV —— 让口径缺口显性可见，而不是藏起来或伪装成完整。
# 标签只锚**尾部**：MD&A 是两栏排版，左栏的饼图标签（如「51.0% 42.7%」）会被
# pdftotext 串进同一物理行、粘在科目名前面（2007/2009 实测），首尾全锚会丢行。
SEG_PAT = {
    "鞋类": r"footwear$",
    "服装": r"apparel$",
    "器材及配件": r"(equipment[ /]?(and )?)?accessories$",
}
SEG_PAGE = re.compile(
    r"breakdown\b.{0,24}by (brand and )?product category"     # 2004-2006 写作
    r"|revenue by product category", re.I)                    # "Breakdown of turnover by …"


def extract_segment(year, revenue):
    """取某年分产品营收 → (dict, 李宁品牌收入 or None)。单位百万元。"""
    name = C.ar_name(year)
    pgs = C.pages(name)
    best, brand = None, None
    for pi, lines in enumerate(pgs):
        if not SEG_PAGE.search("\n".join(lines)):
            continue
        anchors, note_col, hdr = C.col_anchors(lines, 0, lookahead=len(lines))
        if not anchors:
            continue
        idx = next((i for i, (y, _) in enumerate(anchors) if y == year), None)
        if idx is None:
            continue
        cols = [c for _, c in anchors]
        gap = (min(cols[k + 1] - cols[k] for k in range(len(cols) - 1))
               if len(cols) > 1 else 20)
        rows = C._rows_in(lines, hdr + 1, cols, note_col, max(6, gap * 0.45))
        # ── 选组用**算术约束**，不用行序 ────────────────────────────────
        # 这一页按品牌分块（李宁 / 红双喜 / Lotto / 其他 / 合计），而两栏排版会让
        # 行序错乱、个别行丢失。与其猜分块边界，不如把页内全部候选值列出来，
        # 取「鞋+服+器材 = 当年营业额」的那一组——这组合唯一且自证。
        # 找不到相等组合的年份（2011-2017 集团合计未拆产品）退回「和最大且不超过
        # 营业额」的组合，由覆盖率行如实标出缺口。
        cand = {zh: [] for zh in SEG_PAT}
        for lab, vals in rows:
            v = vals[idx] if idx < len(vals) else None
            if v is None or v <= 0:
                continue
            for zh, pat in SEG_PAT.items():
                # 走 _match（原样 + 去空格两路）：2005 年报把科目印成
                # `Fo otwear` / `Acc essories`，单路匹配整年抽不到。
                if _match(lab, [pat]):
                    cand[zh].append(v / SCALE)
        if not all(cand.values()):
            continue
        exact, fallback = None, None
        for fv in cand["鞋类"]:
            for av in cand["服装"]:
                for ev in cand["器材及配件"]:
                    s = fv + av + ev
                    t = {"鞋类": fv, "服装": av, "器材及配件": ev}
                    if revenue and abs(s - revenue) <= max(0.5, revenue * 0.001):
                        exact = t
                    if revenue and s <= revenue * 1.001 and (
                            fallback is None or s > sum(fallback.values())):
                        fallback = t
        best = exact or fallback
        # 曾想顺手记「李宁品牌收入」，但两栏排版下「第一个 Total 行」在 2006/2007/
        # 2009 分别取到 3,168 / 104 / 190 百万——全是别的品牌块的合计。定位不住就
        # 不记：**错的数比没有数更糟**。品牌口径缺口已由覆盖率行如实反映
        # （2011-2017 <100% 即「该年只有李宁品牌拆了产品」）。
        if best:
            break
    return best, None


def build_segments(data, years):
    seg = {}
    for y in years:
        if y in C.PRE_IPO:                 # 招股书按产品拆的口径与年报不同，不混入
            continue
        s, _ = extract_segment(y, data["IS"][y].get("营业额"))
        if s:
            seg[y] = s
    order = ["鞋类", "服装", "器材及配件"]
    path = os.path.join(HERE, "分部营收.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("# 分部营收（李宁 02331.HK）· 单位：人民币百万元 · 来源：各年年报 MD&A"
                "「Revenue breakdown by product category」，取该年年报本年列\n")
        f.write("# ⚠️「分产品合计÷营业额」是**口径覆盖率**：<100% 表示该年年报只对"
                "部分品牌拆了产品（2008-2015 按品牌分层披露，2015 仅李宁品牌有产品拆分）\n")
        w = csv.writer(f)
        ys = [y for y in years if y in seg]
        w.writerow(["科目"] + [str(y) for y in ys])
        for zh in order:
            w.writerow([zh] + [f"{seg[y].get(zh, ''):.3f}".rstrip("0").rstrip(".")
                               if seg[y].get(zh) is not None else "" for y in ys])
        w.writerow(["分产品合计"] + [f"{sum(seg[y].values()):.3f}".rstrip("0").rstrip(".")
                                   for y in ys])
        w.writerow(["分产品合计÷营业额"] + [
            f"{sum(seg[y].values()) / data['IS'][y]['营业额']:.4f}" for y in ys])
    cov = {y: sum(seg[y].values()) / data["IS"][y]["营业额"] for y in ys}
    full = [y for y in ys if abs(cov[y] - 1) <= 0.005]
    part = [(y, cov[y]) for y in ys if abs(cov[y] - 1) > 0.005]
    print(f"  ✅ 写出 分部营收.csv（{len(ys)} 年；合计=营业额 {len(full)} 年）")
    for y, c in part:
        print(f"     ℹ️ {y} 覆盖率 {c:.1%}（该年年报按品牌分层，集团合计未拆产品）")
    return ys, part


def build_ratios(data, years):
    """通用底(scripts/derived.py) + 李宁定制层 → 财务比率.csv。

    单一写者架构：本文件是 财务比率.csv 的唯一写者，derived.py 只提供通用底。
    """
    import derived

    def tbl(kind):
        keys = [zh for zh, _, _ in PICKS[kind]]
        if kind == "BS":
            keys += ["母公司拥有人应占权益"]
        return {k: [data[kind][y].get(k) for y in years] for k in keys}

    PL, BS_, CF_ = tbl("IS"), tbl("BS"), tbl("CF")
    common, unmatched = derived.compute_common_ratios(PL, BS_, CF_)
    rows = [(n, v) for n, v, _ in common]

    # ── 李宁定制层（运动服饰/品牌零售特有）──────────────────────────
    def col(t, k):
        return t.get(k) or [None] * len(years)

    rev = col(PL, "营业额")
    opp = col(PL, "经营溢利")
    ocf = col(CF_, "经营活动所得现金净额")
    inv, ar, ap = col(BS_, "存货"), col(BS_, "贸易应收款项"), col(BS_, "贸易应付款项")
    ta = col(BS_, "资产总计")
    borrow, cb, lease = col(BS_, "借款"), col(BS_, "可换股债券"), col(BS_, "租赁负债")
    cash, dep, rest = (col(BS_, "现金及现金等价物"), col(BS_, "定期/长期银行存款"),
                       col(BS_, "受限制银行存款"))

    def z(row, i):
        return 0.0 if row[i] is None else row[i]

    def ratio(num, den):
        return [None if (num[i] is None or not den[i]) else num[i] / den[i]
                for i in range(len(years))]

    debt = [z(borrow, i) + z(cb, i) for i in range(len(years))]
    debt_all = [debt[i] + z(lease, i) for i in range(len(years))]
    netcash = [z(cash, i) + z(dep, i) + z(rest, i) - debt[i] for i in range(len(years))]
    wc = [None if (inv[i] is None or ar[i] is None) else
          z(inv, i) + z(ar, i) - z(ap, i) for i in range(len(years))]

    rows += [
        ("经营利润率 Operating margin", ratio(opp, rev)),
        ("经营现金流/营收 OCF/Revenue", ratio(ocf, rev)),
        ("有息负债(含租赁)/总资产 Debt/TA", ratio(debt_all, ta)),
        ("净现金(现金+存款−借款−可换债)/总资产", ratio(netcash, ta)),
        ("营运资本占用(存货+应收−应付)/营收", ratio(wc, rev)),
    ]

    path = os.path.join(HERE, "财务比率.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("# 财务比率（李宁 02331.HK）· 派生自本目录三表；比率为小数(0.49=49%)，"
                "天数为日；空=所需科目该年缺失\n")
        f.write("# 通用底 = scripts/derived.py compute_common_ratios()；"
                "其余为李宁定制层（运动服饰/品牌零售）\n")
        w = csv.writer(f)
        w.writerow(["指标"] + [str(y) for y in years])
        for name, vals in rows:
            w.writerow([name] + ["" if v is None else f"{v:.4f}".rstrip("0").rstrip(".")
                                 for v in vals])
    print(f"  ✅ 写出 财务比率.csv（通用底 {len(common)} 项 + 定制层 5 项）")
    if unmatched:
        print(f"  ⚠️ derived 未匹配科目：{sorted(set(unmatched))}")
    return sorted(set(unmatched))


def main():
    check_only = "--check" in sys.argv
    do_x = "--xcheck" in sys.argv

    data, hits = build()
    years = C.ALL_YEARS

    fails, n = [], 0
    for y in years:
        n += validate(y, data["IS"][y], data["BS"][y], data["CF"][y], fails)

    print(f"=== 勾稽校验：{n} 条，失败 {len(fails)} 条 ===")
    for f in fails:
        print("  🔴", f)

    cells, diffs = (0, [])
    if do_x or not check_only:
        cells, diffs = cross_check(data)
        print(f"\n=== 跨年交叉核：{cells} 格，不一致 {len(diffs)} 格 ===")
        for kind, y, k, a, b in diffs:
            print(f"  ⚠️ {kind} {y} {k}: AR{y}本年列={a:,.3f} vs AR{y+1}上年列={b:,.3f} "
                  f"差 {a-b:,.3f}")

    if fails:
        print("\n🔴 勾稽未通过 —— 按铁律不写出 CSV。")
        return 1
    if check_only:
        print("\n✅ 校验通过（--check 模式，未写出）")
        return 0

    for kind, fname, title in (("IS", "利润表.csv", "利润表"),
                               ("BS", "资产负债表.csv", "资产负债表"),
                               ("CF", "现金流量表.csv", "现金流量表")):
        order = [zh for zh, _, _ in PICKS[kind]]
        path = os.path.join(HERE, fname)
        with open(path, "w", newline="", encoding="utf-8") as f:
            f.write(f"# {title}（李宁 02331.HK）· 单位：人民币百万元；"
                    "负数=流出/减项；空=该期财报无此科目\n")
            f.write("# 来源：report/李宁/ 招股说明书(2001-2003)+各年年报(2004-2025) 逐行解析；"
                    "各年取该年年报本年列(as-reported)，比较列仅用于跨年交叉核\n")
            w = csv.writer(f)
            w.writerow(["科目"] + [str(y) for y in years])
            for zh in order:
                row = [zh]
                for y in years:
                    v = data[kind][y].get(zh)
                    row.append("" if v is None else f"{v:.3f}".rstrip("0").rstrip("."))
                if any(c != "" for c in row[1:]):
                    w.writerow(row)
        print(f"  ✅ 写出 {fname}")

    build_ratios(data, years)
    build_segments(data, years)
    return 0


if __name__ == "__main__":
    sys.exit(main())
