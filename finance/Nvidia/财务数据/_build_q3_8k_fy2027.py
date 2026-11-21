#!/usr/bin/env python3
"""FY2027 Q3（截至 2026-10-25）**业绩 8-K 口径** → `中期财务-FY2027Q3-业绩8K.csv`；任一闸不过不写出。

为什么单独成表：Q3 10-Q **没有**与业绩 8-K 同日提交——2024-08 起连续 9 份定期报告（10-Q / 10-K）都与业绩 8-K 同日，
这是第一次分开；CFO 评论原文「We plan to file our 10-Q in the coming weeks.」。10-Q 出来前，8-K 三份附件是 Q3 唯一的
一手数字：EX-99.1 新闻稿（三表简表）、EX-99.2 CFO 评论（分部 / 市场平台十亿美元表、承诺 / 担保表 → 后者进 附注自陈数.csv）、
EX-99.3「补充财务信息」（10-Q 未出前的替代披露：有价证券明细、非上市权益滚动表、存货构成、地区、客户集中度句）。
⚠️ 这些附件是 furnished（未经 10-Q 审阅程序，8-K 自陈 unaudited）。**10-Q 出来后以 10-Q 为准**：R 文件机读进
`中期财务-FY2027.csv`，与本表逐格互核，差异进 `重述与口径变更.csv`。

期间轴（取数当场声明）：Q3 = 3 个月截至 2026-10-25（07-27 起 91 天）；前三季 = 9 个月截至 2026-10-25（01-26 起 273 天）；
对比列 = 同表上年同期；资产负债表 = 2026-10-25 时点（对比 2026-01-25）。CFO 评论表单位为十亿美元一位小数，单列一张。

闸（默认容差 0；放宽处写明理由）：
 A 表内：利润链；资产负债表各段明细和 = 合计、负债 + 权益 = 总资产；现金流三段明细和 = 小计、三段 = 净变动、
   期初 + 净变动 = 期末、期末现金 = 资产负债表现金；EPS × 股数 ≈ 净利（±0.5% 取整）。
 B 同一 8-K 两次印刷：EX-99.1 与 EX-99.3 的三表逐格相同。
 C 跨申报（Q2 10-Q）：2026-01-25 列逐格 = `中期财务-FY2027.csv` 同列；前三季 − Q3 = H1（同概念行·±1，两份申报各自取整）；
   Q3 期初现金 = 2026-07-26 现金；非上市权益滚动表 Q3 期初 = Q2 10-Q 滚动表期末（R 文件）、前三季期初 = 01-25 资产负债表行；
   01-25 存货构成 = FY2026 10-K（`存货构成.csv`）。
 D 附表：地区和 = 营收、地区 Q3 = 前三季 − H1（±1）；存货构成和 = 存货；滚动表 期初 + 各项 = 期末；有价证券明细
   行内公允价值 = 各「列示于」之和、列合计 = 合计行、「列示于有价债券 / 上市权益证券」= 资产负债表行。
 E CFO 十亿美元表：分部和 = 合计、Hyperscale + ACIE = 数据中心、数据中心 + 边缘 = 合计（±0.1）；合计 = 营收 ÷ 1000（±0.05）；
   上季列 = Q2 10-Q 百万数 ÷ 1000 四舍五入一位（容差 0）——顺带证明 Q3 期间没有再改划 Q2 的子平台归属。
 F 正文句（EX-99.3 / EX-99.1）：境外总部客户占比 = 1 − 美国 ÷ 营收（±0.5pp）；新闻稿「returned $28.1 billion」= 现金流回购 + 股息（±50）；
   毛利率 = 新闻稿非 GAAP 调节表印的 GAAP gross margin（±0.05pp）。
"""
import csv
import json
import os
import re
import sys
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _build_from_filings as B  # noqa: E402  fmt
import _build_notes as N  # noqa: E402  R 文件维度块（Q2 10-Q 滚动表期末）
import _build_selfreported as S  # noqa: E402  plain() / REPORT / ITEMS（承诺锚句）

PR, CFO, SUPP = "8-K-20261117-EX99.1-新闻稿.htm", "8-K-20261117-EX99.2-CFO评论.htm", "8-K-20261117-EX99.3-补充财务信息.htm"
Q3C, Q3P = "FY2027Q3(3个月·截至2026-10-25)", "FY2026Q3(3个月·截至2025-10-26·同表对比)"
N9C, N9P = "FY2027前三季(9个月·截至2026-10-25)", "FY2026前三季(9个月·截至2025-10-26·同表对比)"
BSC, BSP = "2026-10-25 时点", "2026-01-25 时点(同表对比)"
Q2B = "FY2027Q2(3个月·截至2026-07-26·CFO 表上季列)"
FLOW_COLS = (Q3C, Q3P, N9C, N9P)
COLS = (Q3C, Q3P, N9C, N9P, BSC, BSP, Q2B)
# 上游（Q2 10-Q 机读·只读）
I_Q2, I_H1, I_H1P = "FY2027Q2(3个月·截至2026-07-26)", "FY2027H1(6个月·截至2026-07-26)", "FY2026H1(6个月·截至2025-07-27·同表对比)"
I_BS2, I_BS0 = "2026-07-26 时点", "2026-01-25 时点(同表对比)"

NMS = "非上市证券(资产负债表行·原文 Non-marketable securities·含非上市债权) Non-marketable securities"
NMS_INTERIM = "非上市权益证券(FY2026起单列) Non-marketable equity securities"   # 中期表沿用年度概念名（同一行，见 README）

IS_SPEC = [("Revenue", "营业收入 Revenue"), ("Cost of revenue", "营业成本 Cost of revenue"), ("Gross profit", "毛利 Gross profit"),
           ("Research and development", "研发费用 Research and development"),
           ("Sales, general and administrative", "销售、一般及管理费用 Sales, general and administrative"),
           ("Total operating expenses", "营业费用合计 Total operating expenses"), ("Operating income", "营业利润 Operating income"),
           ("Other income, net", "营业外收支合计(FY2016起印刷) Total other income (expense)"),
           ("Income before income tax", "税前利润 Income before income tax"),
           ("Income tax expense", "所得税 Income tax expense (benefit)"), ("Net income", "净利润 Net income"),
           ("Basic", "基本EPS(as-reported·拆股基准随年变) Basic EPS"), ("Diluted", "摊薄EPS(as-reported·拆股基准随年变) Diluted EPS"),
           ("Basic", "基本股数(百万股·as-reported) Basic shares"), ("Diluted", "摊薄股数(百万股·as-reported) Diluted shares")]
BS_SPEC = [("Cash and cash equivalents", "现金及现金等价物 Cash and cash equivalents"),
           ("Marketable debt securities", "有价债券(FY2027起季报单列) Marketable debt securities"),
           ("Marketable equity securities", "上市权益证券(FY2027起季报单列) Marketable equity securities"),
           ("Accounts receivable, net", "应收账款净额 Accounts receivable, net"), ("Inventories", "存货 Inventories"),
           ("Prepaid expenses and other current assets", "预付及其他流动资产 Prepaid expenses and other current assets"),
           ("Total current assets", "流动资产合计 Total current assets"),
           ("Property and equipment, net", "固定资产净额 Property and equipment, net"),
           ("Operating lease assets", "经营租赁资产(FY2020起) Operating lease assets"), ("Goodwill", "商誉 Goodwill"),
           ("Intangible assets, net", "无形资产净额 Intangible assets, net"),
           ("Deferred income tax assets", "递延所得税资产(非流动) Deferred income tax assets"),
           ("Non-marketable securities", NMS), ("Other assets", "其他资产 Other assets"), ("Total assets", "总资产 Total assets"),
           ("Accounts payable", "应付账款 Accounts payable"),
           ("Accrued and other current liabilities", "应计及其他流动负债 Accrued and other current liabilities"),
           ("Short-term debt", "短期债务(FY2021起) Short-term debt"), ("Total current liabilities", "流动负债合计 Total current liabilities"),
           ("Long-term debt", "长期债务 Long-term debt"),
           ("Long-term operating lease liabilities", "长期经营租赁负债(FY2020起) Long-term operating lease liabilities"),
           ("Other long-term liabilities", "其他长期负债 Other long-term liabilities"),
           ("Total liabilities", "负债合计(FY2016起印刷) Total liabilities"),
           ("Shareholders' equity", "股东权益合计 Total shareholders' equity"),
           ("Total liabilities and shareholders' equity", "负债及股东权益合计 Total liabilities and shareholders' equity")]
CA = BS_SPEC[:6]
NCA = BS_SPEC[7:14]
CL = BS_SPEC[15:18]
NCL = BS_SPEC[19:22]
# (8-K 标签, 概念名, 是否与 Q2 10-Q 中期表同概念 → 参与「前三季 − Q3 = H1」闸)
CF_SPEC = [("Net income", "净利润 Net income", True),
           ("Stock-based compensation expense", "股权激励费用 Stock-based compensation", True),
           ("Depreciation and amortization", "折旧及摊销 Depreciation and amortization", True),
           ("Deferred income taxes", "递延所得税 Deferred income taxes", True),
           ("Losses from derivatives, net", "衍生品损失净额 Losses from derivatives, net", False),
           ("Gains from equity securities, net", "投资损益(收益为负) (Gains) losses on investments", True),
           ("Other", "其他(经营段) Other", False),
           ("Accounts receivable", "应收账款变动 Change in accounts receivable", True),
           ("Inventories", "存货变动 Change in inventories", True),
           ("Prepaid expenses and other assets", "预付及其他资产变动 Prepaid expenses and other assets", False),
           ("Accounts payable", "应付账款变动 Change in accounts payable", True),
           ("Accrued and other current liabilities", "应计及其他流动负债变动 Accrued and other current liabilities", False),
           ("Other long-term liabilities", "其他长期负债变动 Other long-term liabilities", False),
           ("Net cash provided by operating activities", "经营活动现金流净额 Net cash from operating activities", True),
           ("Proceeds from sales and maturities of debt securities", "出售及到期债券所得 Proceeds from sales and maturities of debt securities", False),
           ("Proceeds from sales of equity securities", "出售权益证券所得 Proceeds from sales of equity securities", False),
           ("Purchases of equity securities", "购买权益证券 Purchases of equity securities", False),
           ("Purchases of debt securities", "购买有价证券 Purchases of marketable securities", True),
           ("Purchases related to property and equipment and intangible assets",
            "资本开支(购置固定资产及无形资产) Purchases of property and equipment and intangible assets", True),
           ("Acquisitions, net of cash acquired and other", "收购及其他(扣除取得现金·8-K 合并印) Acquisitions, net of cash acquired and other", False),
           ("Net cash used in investing activities", "投资活动现金流净额 Net cash from investing activities", True),
           ("Proceeds related to issuance of debt, net of costs", "发债所得 Proceeds from issuance of debt", True),
           ("Proceeds related to employee stock plans", "员工股票计划所得 Proceeds related to employee stock plans", True),
           ("Payments related to repurchases of common stock", "回购普通股 Repurchases of common stock", True),
           ("Dividends paid", "支付股息 Dividends paid", True),
           ("Payments related to employee stock plan taxes", "RSU 代扣个税 Payments related to employee stock plan taxes", True),
           ("Groq, Inc.", "Groq 交易对价付款 Groq, Inc.", False),
           ("Repayment of debt", "偿还债务 Repayment of debt", False),
           ("Principal payments on property and equipment and intangible assets",
            "固定资产及无形资产本金付款 Principal payments on property and equipment and intangible assets", False),
           ("Other", "其他(融资段) Other", False),
           ("Net cash used in financing activities", "融资活动现金流净额 Net cash from financing activities", True),
           ("Change in cash and cash equivalents", "现金净变动 Change in cash and cash equivalents", True),
           ("Cash and cash equivalents at beginning of period", "期初现金 Cash and cash equivalents at beginning of period", False),
           ("Cash and cash equivalents at end of period", "期末现金 Cash and cash equivalents at end of period", False)]
OPS, INV, FIN = CF_SPEC[1:13], CF_SPEC[14:20], CF_SPEC[21:30]
GEO = [("United States", "美国 United States"), ("Taiwan", "台湾 Taiwan"),
       ("China (including Hong Kong)", "中国(含香港) China incl. Hong Kong"), ("Other", "其他 Other")]
VOID = {"br", "img", "hr", "meta", "link", "input", "col", "wbr"}


class Rows(HTMLParser):
    """表格行（非空单元格），文档顺序；display:none 与 script/style 丢弃。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell, self.in_cell, self.stack, self.hidden = [], None, [], False, [], 0

    def handle_starttag(self, tag, attrs):
        st = (dict(attrs).get("style") or "").replace(" ", "").lower()
        hide = tag in ("script", "style") or "display:none" in st
        if tag not in VOID:
            self.stack.append((tag, hide))
            self.hidden += hide
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell, self.in_cell = [], True

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                self.hidden -= sum(h for _, h in self.stack[i:])
                del self.stack[i:]
                break
        if tag in ("td", "th") and self.row is not None and self.in_cell:
            self.row.append(" ".join("".join(self.cell).split()))
            self.in_cell = False
        elif tag == "tr" and self.row is not None:
            cells = [c for c in self.row if c]
            if cells:
                self.rows.append(cells)
            self.row = None

    def handle_data(self, d):
        if self.in_cell and not self.hidden:
            self.cell.append(d.replace("\xa0", " "))


def rows_of(fn):
    p = Rows()
    p.feed(open(os.path.join(S.REPORT, fn), "rb").read().decode("utf-8", "replace"))
    return p.rows


NUM = re.compile(r"^\(?\$?\s?-?[\d,]+(?:\.\d+)?\)?$")


def nums(cells):
    """单元格 → 数值列表：'$' 与 '%' 单元格丢弃；'—' = 0；括号 = 负。"""
    out = []
    for c in cells:
        c = c.strip()
        if c in ("$", "%", ""):
            continue
        if c in ("—", "–", "-"):
            out.append(0.0)
            continue
        if NUM.match(c):
            neg = c.startswith("(") and c.endswith(")")
            v = float(c.strip("()$ ").replace(",", ""))
            out.append(-v if neg else v)
    return out


def take(rows, start, spec, ncols, bad, where):
    """自 start 起按 spec 顺序逐个找标签行（重复标签靠顺序消歧）→ ({概念: [值...]}, 末行下标)。"""
    out, i = {}, start
    for label, name, *_ in spec:
        while i < len(rows) and rows[i][0] != label:
            i += 1
        if i >= len(rows):
            bad.append((where, f"找不到行 {label}"))
            return out, i
        v = nums(rows[i][1:])
        if len(v) != ncols:
            bad.append((where, f"{label} 数值列数 {len(v)} ≠ {ncols}", rows[i]))
        out[name] = v[:ncols]
        i += 1
    return out, i


def statements(fn, bad):
    rows = rows_of(fn)
    # 利润表起点 = 「Revenue」且下一行是「Cost of revenue」（新闻稿开头的十亿美元摘要表也有 Revenue 行，下一行是 Gross margin）
    s_is = next(i for i, r in enumerate(rows[:-1]) if r[0] == "Revenue" and rows[i + 1][0] == "Cost of revenue")
    is_, e = take(rows, s_is, IS_SPEC, 4, bad, fn + "·IS")
    bs, e = take(rows, e, BS_SPEC, 2, bad, fn + "·BS")
    cf, e = take(rows, e, CF_SPEC, 4, bad, fn + "·CF")
    return rows, is_, bs, cf, e


def read_csv_table(path, must):
    """读上游 CSV（# 注释行跳过）→ {(第1列,第2列) 或 第1列: {列名: 值}}；must = [(键, 列名)] 缺任一即报（防表头偏移静默丢值）。"""
    with open(path, encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#")]
    rdr = list(csv.reader(lines))
    hdr = rdr[0]
    two = hdr[0] == "表"
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):   # 「数据来源」等文字行
            return None

    out = {}
    for r in rdr[1:]:
        if not r:
            continue
        key = (r[0], r[1]) if two else r[0]
        vals = r[2:] if two else r[1:]
        cols = hdr[2:] if two else hdr[1:]
        out[key] = {c: num(v) for c, v in zip(cols, vals)}
    missing = [(k, c) for k, c in must if out.get(k, {}).get(c) is None]
    return out, missing


def main():
    bad = []
    put = {}   # (表, 科目) → {列: 值}
    add = lambda t, n, c, v: put.setdefault((t, n), {}).__setitem__(c, v)

    # ── A/B：三表（EX-99.3 为主，EX-99.1 逐格互核） ──
    rows_s, IS, BS, CF, end_s = statements(SUPP, bad)
    _, IS1, BS1, CF1, _ = statements(PR, bad)
    for nm, a, b in (("IS", IS, IS1), ("BS", BS, BS1), ("CF", CF, CF1)):
        if a != b:
            diff = [(k, a.get(k), b.get(k)) for k in set(a) | set(b) if a.get(k) != b.get(k)]
            bad.append(("B·EX-99.1 vs EX-99.3", nm, diff[:5]))
    if bad:
        return report(bad)
    for name, v in IS.items():
        for c, x in zip(FLOW_COLS, v):
            add("利润表", name, c, x)
    for name, v in BS.items():
        for c, x in zip((BSC, BSP), v):
            add("资产负债表", name, c, x)
    for name, v in CF.items():
        for c, x in zip(FLOW_COLS, v):
            add("现金流量表", name, c, x)
    g = lambda t, n, c: put.get((t, n), {}).get(c)
    for c in FLOW_COLS:
        R_, C_, GP, RD, SGA, OPX, OI, NON, PBT, TAX, NI = (g("利润表", n, c) for _, n in IS_SPEC[:11])
        for nm, dv in (("营收−成本=毛利", R_ - C_ - GP), ("研发+销管=营业费用", RD + SGA - OPX), ("毛利−营业费用=营业利润", GP - OPX - OI),
                       ("营业利润+营业外=税前", OI + NON - PBT), ("税前−所得税=净利", PBT - TAX - NI)):
            if abs(dv) > 1e-6:
                bad.append(("A·利润链", c, nm, dv))
        eps, sh = g("利润表", IS_SPEC[11][1], c), g("利润表", IS_SPEC[13][1], c)
        if abs(eps * sh - NI) > 0.005 * NI:
            bad.append(("A·EPS×股数≈净利", c, eps, sh, NI))
        o, i_, f_ = (g("现金流量表", n, c) for n in (CF_SPEC[13][1], CF_SPEC[20][1], CF_SPEC[30][1]))
        for nm, part, sub in (("经营段", [CF_SPEC[0]] + OPS, o), ("投资段", INV, i_), ("融资段", FIN, f_)):
            s = sum(g("现金流量表", n, c) for _, n, _ in part)
            if abs(s - sub) > 1e-6:
                bad.append(("A·现金流明细和=小计", c, nm, s, sub))
        ch, beg, end = (g("现金流量表", n, c) for n in (CF_SPEC[31][1], CF_SPEC[32][1], CF_SPEC[33][1]))
        if abs(o + i_ + f_ - ch) > 1e-6 or abs(beg + ch - end) > 1e-6:
            bad.append(("A·三段=净变动 / 期初+净变动=期末", c, (o, i_, f_, ch, beg, end)))
        if abs(g("现金流量表", CF_SPEC[0][1], c) - NI) > 1e-6:
            bad.append(("A·现金流净利=利润表净利", c))
    for c in (BSC, BSP):
        ca = sum(g("资产负债表", n, c) for _, n in CA)
        ta = g("资产负债表", BS_SPEC[6][1], c) + sum(g("资产负债表", n, c) for _, n in NCA)
        cl = sum(g("资产负债表", n, c) for _, n in CL)
        tl = g("资产负债表", BS_SPEC[18][1], c) + sum(g("资产负债表", n, c) for _, n in NCL)
        TCA, TA, TCL, TL, TE, TLE = (g("资产负债表", BS_SPEC[k][1], c) for k in (6, 14, 18, 22, 23, 24))
        for nm, x, y in (("流动资产明细和=合计", ca, TCA), ("流动+非流动=总资产", ta, TA), ("流动负债明细和=合计", cl, TCL),
                         ("流动+非流动负债=负债合计", tl, TL), ("负债+权益=总资产", TL + TE, TA), ("负债及权益合计=总资产", TLE, TA)):
            if abs(x - y) > 1e-6:
                bad.append(("A·资产负债表", c, nm, x, y))
    for c_cf, c_bs in ((N9C, BSC), (Q3C, BSC)):
        if abs(g("现金流量表", CF_SPEC[33][1], c_cf) - g("资产负债表", BS_SPEC[0][1], c_bs)) > 1e-6:
            bad.append(("A·期末现金=资产负债表现金", c_cf))

    # ── C：跨申报（Q2 10-Q 机读的中期表·只读·MUST 防静默缺值） ──
    need = [(("利润表", n), col) for _, n in IS_SPEC[:11] for col in (I_H1, I_H1P)]
    need += [(("现金流量表", n), col) for _, n, same in CF_SPEC if same for col in (I_H1, I_H1P)]
    need += [(("资产负债表", n if n != NMS else NMS_INTERIM), I_BS0) for _, n in BS_SPEC if n not in (BS_SPEC[23][1],)]
    need += [(("资产负债表", "现金及现金等价物 Cash and cash equivalents"), I_BS2), (("资产负债表", "存货 Inventories"), I_BS2),
             (("资产负债表", "股东权益合计 Total shareholders' equity"), I_BS0)]
    seg_rows = [("分部", "计算与网络 Compute & Networking·营收"), ("分部", "图形 Graphics·营收"),
                ("市场平台(FY2027新口径)", "数据中心 Data Center"),
                ("市场平台(FY2027新口径)", "  其中 超大规模云 Hyperscale(Q2 10-Q 口径·一家公司由 ACIE 改划·可比期已重列)"),
                ("市场平台(FY2027新口径)", "  其中 AI 云·工业·企业 ACIE(Q2 10-Q 口径·一家公司由 ACIE 改划·可比期已重列)"),
                ("市场平台(FY2027新口径)", "边缘计算 Edge Computing")]
    need += [(k, I_Q2) for k in seg_rows] + [(("利润表", "营业收入 Revenue"), I_Q2)]
    need += [(("地区(直接客户总部口径)", n), col) for _, n in GEO for col in (I_H1, I_H1P)]
    need += [(("派生", "派生·净现金(含上市权益证券) = 现金+有价债券+上市权益证券−短期债务−长期债务"), I_BS0),
             (("派生", "派生·净现金(剔上市权益证券) = 现金+有价债券−短期债务−长期债务"), I_BS0)]
    itm, missing = read_csv_table(os.path.join(HERE, "中期财务-FY2027.csv"), need)
    if missing:
        bad.append(("C·上游中期表缺格(MUST)", missing[:5]))
        return report(bad)
    for _, n in IS_SPEC[:11]:
        for c9, c3, ch1 in ((N9C, Q3C, I_H1), (N9P, Q3P, I_H1P)):
            d = g("利润表", n, c9) - g("利润表", n, c3) - itm[("利润表", n)][ch1]
            if abs(d) > 1.0 + 1e-6:
                bad.append(("C·前三季−Q3=H1(利润表)", n, c9, d))
    # 现金流小计放宽到 ±2（显式）：两份申报的报表都按「已取整明细加总」印小计（表内明细和 = 小计逐格成立），各行 ±1 的取整差
    # 会累到小计上。实测：FY2026 前三季融资段 −2 = 员工股票计划 −1（643−274=369 vs 370）+ 股息 −1（−732+243=−489 vs −488）。
    # 明细行仍 ±1；小计被改动由 A 闸「明细和 = 小计」拦。
    subtot = {CF_SPEC[k][1] for k in (13, 20, 30, 31)}
    for _, n, same in CF_SPEC:
        if not same:
            continue
        tol = 2.0 if n in subtot else 1.0
        for c9, c3, ch1 in ((N9C, Q3C, I_H1), (N9P, Q3P, I_H1P)):
            d = g("现金流量表", n, c9) - g("现金流量表", n, c3) - itm[("现金流量表", n)][ch1]
            if abs(d) > tol + 1e-6:
                bad.append(("C·前三季−Q3=H1(现金流·同概念行)", n, c9, d))
    for _, n in BS_SPEC:
        if n == BS_SPEC[23][1]:
            continue
        up = itm[("资产负债表", n if n != NMS else NMS_INTERIM)][I_BS0]
        if abs(g("资产负债表", n, BSP) - up) > 1e-6:
            bad.append(("C·2026-01-25 列 = Q2 10-Q 同列", n, g("资产负债表", n, BSP), up))
    if abs(g("资产负债表", BS_SPEC[23][1], BSP) - itm[("资产负债表", "股东权益合计 Total shareholders' equity")][I_BS0]) > 1e-6:
        bad.append(("C·2026-01-25 股东权益", None))
    if abs(g("现金流量表", CF_SPEC[32][1], Q3C) - itm[("资产负债表", "现金及现金等价物 Cash and cash equivalents")][I_BS2]) > 1e-6:
        bad.append(("C·Q3 期初现金 = 2026-07-26 现金", None))

    # ── D：附表（EX-99.3） ──
    rs = rows_s[end_s:]
    # 有价证券明细（2026-10-25）：8 数行 = 成本/未实现利得/未实现损失/公允价值/现金等价物/有价债券/上市权益/其他资产；5 数行 = 公允价值起
    t_ms = "有价证券明细(2026-10-25·公允价值·EX-99.3)"
    ms_spec = [("Debt securities issued by the U.S. Treasury", "美国国债 U.S. Treasury"),
               ("Debt securities issued by U.S. government agencies", "美国政府机构债 U.S. government agencies"),
               ("Money market funds", "货币市场基金 Money market funds"),
               ("Publicly held equity securities (1) (2)", "上市权益证券·一级(活跃市场报价) Publicly held equity securities Level 1"),
               ("Publicly held equity securities (1) (3)", "上市权益证券·二级(未注册认股权证与可转换优先股) Publicly held equity securities Level 2"),
               ("Debt securities convertible into publicly held equity securities (1) (4)",
                "可转为上市股权的债券·二级(公允价值选择权) Debt securities convertible into publicly held equity securities"),
               ("Total", "合计 Total")]
    cols_ms = ("公允价值", "列示于·现金等价物", "列示于·有价债券", "列示于·上市权益证券", "列示于·其他资产")
    ms, debt_fv = {}, 0.0   # debt_fv = 有成本列（债券 / 货币基金）各行公允价值之和——合计行的成本+利得−损失只覆盖这几行
    j = next((k for k, r in enumerate(rs) if r[0] == ms_spec[0][0]), None)
    if j is None:
        bad.append(("D·有价证券明细", "找不到表"))
        return report(bad)
    for label, name in ms_spec:
        while j < len(rs) and rs[j][0] != label:
            j += 1
        if j >= len(rs):
            bad.append(("D·有价证券明细", f"找不到行 {label}"))
            return report(bad)
        v = nums(rs[j][1:])
        if len(v) == 8:
            target = debt_fv if label == "Total" else v[3]
            if abs(v[0] + v[1] + v[2] - target) > 1e-6:
                bad.append(("D·成本+利得−损失=公允价值(合计行对有成本列的各行)", label, v, target))
            if label != "Total":
                debt_fv += v[3]
            v = v[3:]
        if len(v) != 5:
            bad.append(("D·有价证券明细列数", label, v))
            return report(bad)
        ms[name] = v
        if abs(v[0] - sum(v[1:])) > 1e-6:
            bad.append(("D·公允价值=各列示之和", label, v))
        j += 1
    body = [n for _, n in ms_spec[:-1]]
    for k in range(5):
        if abs(sum(ms[n][k] for n in body) - ms["合计 Total"][k]) > 1e-6:
            bad.append(("D·有价证券明细列合计", cols_ms[k]))
    if abs(ms["合计 Total"][2] - g("资产负债表", BS_SPEC[1][1], BSC)) > 1e-6 or \
            abs(ms["合计 Total"][3] - g("资产负债表", BS_SPEC[2][1], BSC)) > 1e-6:
        bad.append(("D·明细「列示于」= 资产负债表 有价债券 / 上市权益证券", ms["合计 Total"]))
    if ms["合计 Total"][1] > g("资产负债表", BS_SPEC[0][1], BSC) + 1e-6:
        bad.append(("D·现金等价物 ≤ 现金及现金等价物", None))
    for name, v in ms.items():
        add(t_ms, f"{name}·公允价值", BSC, v[0])
    for k in range(1, 5):
        add(t_ms, f"合计·{cols_ms[k]}", BSC, ms["合计 Total"][k])
    # 非上市权益滚动表（Q3 / 前三季）
    t_nm = "非上市权益证券滚动表(EX-99.3)"
    nm_spec = [("Balance at beginning of period", "期初余额"), ("Net additions", "本期净增加"), ("Unrealized gains (1)", "未实现利得"),
               ("Reclassification (2)", "重分类(主要为被投方上市交易与被上市公司收购)"),
               ("Impairments and unrealized losses (1)", "减值及未实现损失"), ("Balance at end of period", "期末余额")]
    nm, _ = take(rs, 0, nm_spec, 2, bad, "D·滚动表")
    if len(nm) == len(nm_spec):
        for k, c in enumerate((Q3C, N9C)):
            vals = [nm[n][k] for _, n in nm_spec]
            if abs(sum(vals[:5]) - vals[5]) > 1e-6:
                bad.append(("D·滚动表 期初+各项=期末", c, vals))
            for (_, n), x in zip(nm_spec, vals):
                add(t_nm, n, c, x)
        if abs(nm["期初余额"][1] - g("资产负债表", NMS, BSP)) > 1e-6:
            bad.append(("C·滚动表前三季期初 = 2026-01-25 资产负债表行", nm["期初余额"][1]))
        q2 = json.load(open(os.path.join(HERE, "_rfiles", "2027Q2.json")))
        det = N.find(q2, r"Schedule of Carrying Value of Non-marketable Equity Securities")
        ends = {r["vals"][i] for r in det["rows"] if r["label"] == "Balance at end of period"
                for i, p in enumerate(det["periods"]) if p.startswith("Jul. 26, 2026") and i < len(r["vals"])}
        if ends != {nm["期初余额"][0]}:
            bad.append(("C·滚动表 Q3 期初 = Q2 10-Q 滚动表期末(R 文件)", nm["期初余额"][0], ends))
        add(t_nm, "派生·非上市债权等 = 资产负债表「非上市证券」− 非上市权益滚动表期末", BSC,
            g("资产负债表", NMS, BSC) - nm["期末余额"][1])
    # 存货构成
    t_inv = "存货构成(EX-99.3)"
    inv_spec = [("Raw materials", "原材料 Raw materials"), ("Work in process", "在制品 Work in process"),
                ("Finished goods", "产成品 Finished goods"), ("Total inventories (1)", "存货合计 Total inventories")]
    iv, _ = take(rs, 0, inv_spec, 2, bad, "D·存货构成")
    if len(iv) == len(inv_spec):
        ann, miss = read_csv_table(os.path.join(HERE, "存货构成.csv"),
                                   [(n, "FY2026") for _, n in inv_spec[:3]])
        if miss:
            bad.append(("C·存货构成.csv 缺 FY2026", miss))
        for k, c in enumerate((BSC, BSP)):
            if abs(sum(iv[n][k] for _, n in inv_spec[:3]) - iv[inv_spec[3][1]][k]) > 1e-6:
                bad.append(("D·存货构成和=合计", c))
            if abs(iv[inv_spec[3][1]][k] - g("资产负债表", "存货 Inventories", c)) > 1e-6:
                bad.append(("D·存货合计=资产负债表存货", c))
            for _, n in inv_spec:
                add(t_inv, n, c, iv[n][k])
        for _, n in inv_spec[:3]:
            if not miss and abs(iv[n][1] - ann[n]["FY2026"]) > 1e-6:
                bad.append(("C·2026-01-25 存货构成 = FY2026 10-K", n, iv[n][1], ann[n]["FY2026"]))
    # 地区（直接客户总部口径）
    t_geo = "地区(直接客户总部口径)"
    gv, _ = take(rs, 0, GEO + [("Total revenue", "合计")], 4, bad, "D·地区")
    if len(gv) == 5:
        for k, c in enumerate(FLOW_COLS):
            s = sum(gv[n][k] for _, n in GEO)
            if abs(s - gv["合计"][k]) > 1e-6 or abs(s - g("利润表", "营业收入 Revenue", c)) > 1e-6:
                bad.append(("D·地区和=营收", c, s))
            for _, n in GEO:
                add(t_geo, n, c, gv[n][k])
            add(t_geo, "派生·总部在美国以外的直接客户营收占比(%) = 1 − 美国 ÷ 营收", c,
                round((1 - gv[GEO[0][1]][k] / g("利润表", "营业收入 Revenue", c)) * 100, 1))
        for _, n in GEO:
            for c9, c3, ch1 in ((N9C, Q3C, I_H1), (N9P, Q3P, I_H1P)):
                d = put[(t_geo, n)][c9] - put[(t_geo, n)][c3] - itm[("地区(直接客户总部口径)", n)][ch1]
                if abs(d) > 1.0 + 1e-6:
                    bad.append(("C·地区 前三季−Q3=H1", n, c9, d))

    # ── F：正文句 ──
    txt = S.plain(os.path.join(S.REPORT, SUPP))
    m = re.search(r"headquartered outside of the United States accounted for (\d+) ?% and (\d+) ?% of total revenue for the third "
                  r"quarter and first nine months of fiscal year 2027, respectively, and (\d+) ?% and (\d+) ?% of total revenue", txt)
    if not m:
        bad.append(("F·境外占比句找不到", None))
    else:
        for c, v in zip((Q3C, N9C, Q3P, N9P), m.groups()):
            d = put.get((t_geo, "派生·总部在美国以外的直接客户营收占比(%) = 1 − 美国 ÷ 营收"), {}).get(c)
            if d is None or abs(float(v) - d) > 0.5 + 1e-9:
                bad.append(("F·境外占比 派生 = 正文(±0.5pp)", c, v, d))
    t_con = "客户集中度(%·直接客户·EX-99.3 正文句)"
    for col, pat, kind in ((Q3C, r"For the third quarter of fiscal year 2027, three direct customers represented ([^.]*?) of total revenue", "营收"),
                           (N9C, r"For the first nine months of fiscal year 2027, four direct customers represented ([^.]*?) of total revenue", "营收"),
                           (BSC, r"Two direct customers accounted for ([^.]*?) of our accounts receivable balance as of October 25, 2026", "应收")):
        m = re.search(pat, txt)
        if not m:
            bad.append(("F·集中度句找不到", col, kind))
            continue
        for k, v in enumerate(float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s?%", m.group(1))):
            add(t_con, f"直接客户占{kind}·第{k + 1}大", col, v)
    txt_pr = S.plain(os.path.join(S.REPORT, PR))
    m = re.search(r"During the third quarter of fiscal 2027, NVIDIA returned \$\s?([\d.]+) billion to shareholders", txt_pr)
    ret = -(g("现金流量表", "回购普通股 Repurchases of common stock", Q3C) + g("现金流量表", "支付股息 Dividends paid", Q3C))
    if not m or abs(float(m.group(1)) * 1000 - ret) > 50 + 1e-6:
        bad.append(("F·新闻稿股东回报 = 回购 + 股息", m and m.group(1), ret))
    m = re.search(r"GAAP gross margin ([\d.]+) ?% ([\d.]+) ?% ([\d.]+) ?% ([\d.]+) ?% ([\d.]+) ?%", txt_pr)
    t_der = "派生"
    if not m:
        bad.append(("F·新闻稿毛利率行找不到", None))
    else:
        printed = dict(zip((Q3C, "Q2", Q3P, N9C, N9P), (float(x) for x in m.groups())))
        for c in FLOW_COLS:
            gm = g("利润表", "毛利 Gross profit", c) / g("利润表", "营业收入 Revenue", c) * 100
            if abs(round(gm, 1) - printed[c]) > 0.05 + 1e-9:
                bad.append(("F·毛利率 = 新闻稿印", c, gm, printed[c]))
            add(t_der, "派生·毛利率(%) = 毛利 ÷ 营收", c, round(gm, 1))

    # ── E：CFO 评论十亿美元表 ──
    rc = rows_of(CFO)
    t_b = "分部与市场平台(十亿美元一位小数·EX-99.2 CFO 评论表)"
    seg_spec = [("Compute & Networking", "分部·计算与网络 Compute & Networking"), ("Graphics", "分部·图形 Graphics"),
                ("Total", "分部·合计")]
    mkt_spec = [("Data Center", "市场平台·数据中心 Data Center"), ("Hyperscale", "市场平台·  其中 超大规模云 Hyperscale"),
                ("AI Clouds, Industrial, & Enterprise", "市场平台·  其中 AI 云·工业·企业 ACIE"),
                ("Edge Computing", "市场平台·边缘计算 Edge Computing"), ("Total", "市场平台·合计")]
    i0 = next((k for k, r in enumerate(rc) if r[0] == "Revenue by Reportable Segments"), None)
    if i0 is None:
        bad.append(("E·CFO 分部表找不到", None))
        return report(bad)
    sv, e = take(rc, i0, seg_spec, None, [], "E")
    mv, _ = take(rc, e, mkt_spec, None, [], "E")
    bcols = (Q3C, Q2B, Q3P)
    sv = {k: v[:3] for k, v in sv.items()}
    mv = {k: v[:3] for k, v in mv.items()}
    if len(sv) != 3 or len(mv) != 5 or any(len(v) != 3 for v in list(sv.values()) + list(mv.values())):
        bad.append(("E·CFO 表行 / 列不全", sv, mv))
        return report(bad)
    rev_b = {Q3C: g("利润表", "营业收入 Revenue", Q3C), Q3P: g("利润表", "营业收入 Revenue", Q3P), Q2B: itm[("利润表", "营业收入 Revenue")][I_Q2]}
    for k, c in enumerate(bcols):
        S_, G_, T_ = (sv[n][k] for _, n in seg_spec)
        DC, HS, AC, ED, T2 = (mv[n][k] for _, n in mkt_spec)
        for nm_, x, y in (("分部和=合计", S_ + G_, T_), ("Hyperscale+ACIE=数据中心", HS + AC, DC), ("数据中心+边缘=合计", DC + ED, T2)):
            if abs(x - y) > 0.1 + 1e-9:
                bad.append(("E·" + nm_, c, x, y))
        for T in (T_, T2):
            if abs(T - rev_b[c] / 1000) > 0.05 + 1e-9:
                bad.append(("E·合计 = 营收÷1000", c, T, rev_b[c]))
        for (_, n), x in list(zip(seg_spec, (S_, G_, T_))) + list(zip(mkt_spec, (DC, HS, AC, ED, T2))):
            add(t_b, n, c, x)
    for (_, n_b), key in zip(seg_spec[:2] + mkt_spec[:4], seg_rows):
        src = sv if n_b.startswith("分部") else mv
        if abs(src[n_b][1] - round(itm[key][I_Q2] / 1000, 1)) > 1e-9:
            bad.append(("E·CFO 表上季列 = Q2 10-Q 百万数÷1000(未再改划)", n_b, src[n_b][1], itm[key][I_Q2]))

    # ── 派生（口径当场声明） ──
    bsv = lambda n, c: g("资产负债表", n, c)
    cash, dsec, eq, std, ltd = ("现金及现金等价物 Cash and cash equivalents", "有价债券(FY2027起季报单列) Marketable debt securities",
                                "上市权益证券(FY2027起季报单列) Marketable equity securities", "短期债务(FY2021起) Short-term debt",
                                "长期债务 Long-term debt")
    lab_in = "派生·净现金(含上市权益证券) = 现金+有价债券+上市权益证券−短期债务−长期债务"
    lab_ex = "派生·净现金(剔上市权益证券) = 现金+有价债券−短期债务−长期债务"
    lab_ex2 = "派生·净现金(再剔可转为上市股权的债券·Q3 新出现，见有价证券明细) = 剔上市权益证券口径 − 可转股债券公允价值"
    for c in (BSC, BSP):
        add(t_der, lab_in, c, bsv(cash, c) + bsv(dsec, c) + bsv(eq, c) - bsv(std, c) - bsv(ltd, c))
        add(t_der, lab_ex, c, bsv(cash, c) + bsv(dsec, c) - bsv(std, c) - bsv(ltd, c))
    for lab in (lab_in, lab_ex):
        if abs(put[(t_der, lab)][BSP] - itm[("派生", lab)][I_BS0]) > 1e-6:
            bad.append(("C·01-25 净现金两口径 = 中期表", lab))
    conv = ms.get("可转为上市股权的债券·二级(公允价值选择权) Debt securities convertible into publicly held equity securities", [0.0])[0]
    add(t_der, lab_ex2, BSC, put[(t_der, lab_ex)][BSC] - conv)
    inv_c, inv_0, inv_2 = bsv("存货 Inventories", BSC), bsv("存货 Inventories", BSP), itm[("资产负债表", "存货 Inventories")][I_BS2]
    ar_c, ar_0 = bsv("应收账款净额 Accounts receivable, net", BSC), bsv("应收账款净额 Accounts receivable, net", BSP)
    add(t_der, "派生·存货周转天数(前三季) = 273 × 平均存货(2026-01-25 / 10-25) ÷ 营业成本 —— H1 同口径见 中期财务-FY2027.csv", N9C,
        round(273 * (inv_0 + inv_c) / 2 / g("利润表", "营业成本 Cost of revenue", N9C), 1))
    add(t_der, "派生·存货周转天数(Q3 单季) = 91 × 平均存货(2026-07-26 / 10-25) ÷ 营业成本", Q3C,
        round(91 * (inv_2 + inv_c) / 2 / g("利润表", "营业成本 Cost of revenue", Q3C), 1))
    add(t_der, "派生·应收账款周转天数(前三季) = 273 × 平均应收 ÷ 营收 —— 与公司自陈 DSO(季末应收 ÷ 单季营收·附注自陈数.csv)公式不同", N9C,
        round(273 * (ar_0 + ar_c) / 2 / g("利润表", "营业收入 Revenue", N9C), 1))
    for c in (Q3C, N9C):
        gain = -g("现金流量表", "投资损益(收益为负) (Gains) losses on investments", c)
        add(t_der, "派生·权益证券净收益 ÷ 税前利润(%) —— 财报关注要点 跟踪变量 6 警戒线 >10%", c,
            round(gain / g("利润表", "税前利润 Income before income tax", c) * 100, 1))
    ann, miss = read_csv_table(os.path.join(HERE, "利润表.csv"), [("营业收入 Revenue", "FY2026")])
    if miss:
        bad.append(("C·利润表.csv 缺 FY2026 营收", miss))
        return report(bad)
    ttm = ann["营业收入 Revenue"]["FY2026"] + g("利润表", "营业收入 Revenue", N9C) - g("利润表", "营业收入 Revenue", N9P)
    add(t_der, "派生·过去 12 个月营收(TTM·截至 2026-10-25) = FY2026 营收 + FY2027 前三季 − FY2026 前三季", BSC, ttm)
    cfo_txt = S.plain(os.path.join(S.REPORT, CFO))
    for name_sr, lab in (("供应与产能承诺(CFO 自陈·季末)", "派生·供应与产能承诺(CFO 自陈·季末) ÷ TTM 营收 —— 跟踪变量 5 警戒线 >0.5"),
                         ("承诺合计(CFO 承诺表·供应产能 + 云服务 + 数据中心租约 + 股权投资 + 资本开支)", "派生·承诺合计(CFO 承诺表) ÷ TTM 营收")):
        pat = next((it[3] for it in S.ITEMS if it[0] == name_sr and it[1] == "2026-10-25"), None)
        m = re.search(pat, cfo_txt) if pat else None
        if not m:
            bad.append(("派生", f"{name_sr} 锚句找不到", None))
            continue
        add(t_der, lab, BSC, round(float(m.group(1).replace(",", "")) * 1000 / ttm, 4))
    if bad:
        return report(bad)

    # ── 写出 ──
    order = ["利润表", "现金流量表", "资产负债表", t_der, t_b, t_geo, t_con, t_inv, t_nm, t_ms]
    with open(os.path.join(HERE, "中期财务-FY2027Q3-业绩8K.csv"), "w", newline="") as f:
        f.write("# 单位: 百万美元(EPS 美元/股·股数百万股·占比 %·CFO 表十亿美元一位小数) | **FY2027 Q3 业绩 8-K 口径(10-Q 未出)**: "
                "EX-99.1 新闻稿 + EX-99.3 补充财务信息 + EX-99.2 CFO 评论表(2026-11-17·furnished·unaudited) | "
                "Q3 10-Q 未与业绩 8-K 同日提交(2024-08 起连续 9 份同日后首次分开·CFO 评论称 in the coming weeks)，**10-Q 出来后以 10-Q 为准、逐格互核** | "
                "独立成表·不并入年度序列，也不并入 中期财务-FY2027.csv(那张表只收 10-Q 的 R 文件) | "
                "闸: 利润链 / 资产负债表明细与平衡 / 现金流三段明细和与净变动 / EX-99.1 与 EX-99.3 逐格相同 / 01-25 列 = Q2 10-Q 同列 / "
                "前三季 − Q3 = H1(±1) / 地区和 = 营收 / 存货构成和 / 非上市权益滚动(期初 = Q2 10-Q 期末) / 有价证券明细列示 = 资产负债表 / "
                "CFO 表上季列 = Q2 10-Q | 「非上市证券」行 = 资产负债表原文 Non-marketable securities(含非上市债权；中期财务-FY2027.csv 同一行沿用年度概念名) | "
                "客户集中度 = 直接客户、各列按自身排序\n")
        w = csv.writer(f)
        w.writerow(["表", "科目"] + list(COLS))
        for t in order:
            for (tt, n), vv in put.items():
                if tt != t or all(vv.get(c) is None for c in COLS):
                    continue
                kind = B.PS if "EPS" in n else B.M
                w.writerow([t, n] + [("" if vv.get(c) is None else (f"{vv[c]:g}" if t in (t_b,) or "派生" in n or t == t_con
                                                                    else B.fmt(vv[c], kind))) for c in COLS])
    n_rows = sum(1 for (t, _), vv in put.items() if any(vv.get(c) is not None for c in COLS))
    print(f"✅ 写出 中期财务-FY2027Q3-业绩8K.csv（{n_rows} 行；A 表内 / B 两次印刷 / C 跨申报 / D 附表 / E CFO 表 / F 正文句 全过）")
    return 0


def report(bad):
    print(f"❌ Q3 8-K 闸不通过 {len(bad)} 条（不写出）：")
    for b in bad:
        print("   ", b)
    return 1


if __name__ == "__main__":
    sys.exit(main())
