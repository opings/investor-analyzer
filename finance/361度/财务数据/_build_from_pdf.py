#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""361度（01361.HK）三表构建器 —— 从一手财报 PDF 解析 + 勾稽校验 + 写 CSV。

真源：report/361度/
  · 361度-招股说明书.pdf            → FY2006/6 · FY2007/6 · FY2008/6（附錄一 畢馬威會計師報告）
  · 361度-FY2009-06 ~ FY2011-06    → 止 6 月 30 日的财政年度
  · 361度-FY2011-12-过渡期.pdf      → 2011H2（2011-07-01~2011-12-31 共 6 个月）
  · 361度-2012 ~ 2025.pdf          → 止 12 月 31 日的财政年度

🔴 **本公司的财政年度结算日变更过**（2011 年报附註 1「更改財政年度結算日」）：
   由 6 月 30 日改为 12 月 31 日，中间夹一个 **6 个月过渡期**。故本库的期间轴
   **不是一条年度序列**，而是三段：

       FY2006/6 … FY2011/6   （12 个月·止 6 月 30 日）
       2011H2                （ 6 个月·2011-07-01 ~ 2011-12-31）
       2012 … 2025           （12 个月·止 12 月 31 日）

   **2011H2 是 6 个月，任何同比/复合增速计算都必须先把它排除或年化**，
   直接接进年度序列会凭空造出一次腰斩再翻倍。CSV 列名已把这件事写在名字里。

用法：
    python3 _build_from_pdf.py            # 全量重建（校验通过才写 CSV）
    python3 _build_from_pdf.py --check    # 只跑校验，不写文件
"""
import csv
import os
import re
import sys

from _parse_core import (ensure_text, locate_three, find_year_columns,
                         detect_scale, parse_block, block_end, norm_label,
                         find_titles, CHAIN)

HERE = os.path.dirname(os.path.abspath(__file__))

# ─────────────────────────── 期间轴 ───────────────────────────

JUN_FY = [f"FY{y}/6" for y in range(2006, 2012)]      # 12个月·止6月30日
STUB = "2011H2"                                       # 6个月过渡期
DEC_FY = [str(y) for y in range(2012, 2026)]          # 12个月·止12月31日
PERIODS = JUN_FY + [STUB] + DEC_FY
ANNUAL = JUN_FY + DEC_FY                              # 仅 12 个月期间（增速/比率用）

DROP = ("9M2008", "9M2009")                           # 招股书里的九个月期间·不入库

# 每份 PDF 每张表的**列下标 → 期间**（列数不符即报错，绝不静默错位）
COLMAP = {
    "361度-招股说明书": {
        "is": ["FY2006/6", "FY2007/6", "FY2008/6", "9M2008", "9M2009"],
        "bs": ["FY2006/6", "FY2007/6", "FY2008/6", "9M2009"],
        "cf": ["FY2006/6", "FY2007/6", "FY2008/6", "9M2008", "9M2009"],
    },
    "361度-FY2009-06": {k: ["FY2009/6", "FY2008/6"] for k in ("is", "bs", "cf")},
    "361度-FY2010-06": {k: ["FY2010/6", "FY2009/6"] for k in ("is", "bs", "cf")},
    "361度-FY2011-06": {k: ["FY2011/6", "FY2010/6"] for k in ("is", "bs", "cf")},
    # 过渡期报告：左列=6个月，右列=止 2011-06-30 的年度（资负表右列=2011-06-30 时点）
    "361度-FY2011-12-过渡期": {k: [STUB, "FY2011/6"] for k in ("is", "bs", "cf")},
    "361度-2012": {k: ["2012", STUB] for k in ("is", "bs", "cf")},
}
for _y in range(2013, 2026):
    COLMAP[f"361度-{_y}"] = {k: [str(_y), str(_y - 1)] for k in ("is", "bs", "cf")}

FILES = ["361度-招股说明书", "361度-FY2009-06", "361度-FY2010-06", "361度-FY2011-06",
         "361度-FY2011-12-过渡期"] + [f"361度-{y}" for y in range(2012, 2026)]

# 每个期间的**权威来源**（其本期列）
OWNER = {
    "FY2006/6": "361度-招股说明书", "FY2007/6": "361度-招股说明书",
    "FY2008/6": "361度-招股说明书",
    "FY2009/6": "361度-FY2009-06", "FY2010/6": "361度-FY2010-06",
    "FY2011/6": "361度-FY2011-06", STUB: "361度-FY2011-12-过渡期",
}
for _y in range(2012, 2026):
    OWNER[str(_y)] = f"361度-{_y}"


# ─────────────────────────── 别名层 ───────────────────────────
# 每项 = (规范科目, [正则...])。跨年代科目改名在同一项里并列；
# **口径确有变化的不合并**（如应收款项的拆行），分行存。

IS_SPEC = [
    ("营业额",        [r"^營業額$", r"^收益$"]),
    ("销售成本",       [r"^銷售成本$"]),
    ("毛利",          [r"^毛利$"]),
    ("其他收益",       [r"^其他收益$"]),
    # 「其他淨收入/虧損」逐年换 8 种写法（其他虧損 / 其他淨收益/(虧損) / 其他淨(虧損)/收入 …），
    # 且 2017 年报把标签折行、片段只剩「(虧損)」—— 故用**不锚定首尾**的 `其他淨` 接住折行候选
    ("其他净收入",      [r"^其他淨?(收入|收益|虧損)", r"^其他淨\(", r"其他淨(收入|收益|虧損)"]),
    ("销售及分销开支",   [r"^銷售及分銷開支$"]),
    ("行政开支",       [r"^行政開支$"]),
    # 2019 起单列（此前并在行政开支内）；名称在「金融資產減值虧損 / 貿易應收款項減值虧損 /
    # 貿易應收款項預期信貸虧損撥備」间反复改，且 2024 折行只剩「(撥備)/撥回」
    ("预期信贷亏损拨备",  [r"預期信貸虧損", r"金融資產減值虧損", r"貿易應收款項減值虧損"]),
    ("经营溢利",       [r"^經營(盈利|溢利)$"]),
    # 融资史的一次性项：2012-2015 可换股债券、2016-2021 优先无抵押票据
    ("可换股债券衍生工具公允值变动", [r"可換股債券內(含|嵌)衍生工具公平值"]),
    ("购回可换股债券损益", [r"^購回可換股債券之(虧損|收益)"]),
    ("购回优先票据损益",  [r"^(購回|贖回)優先無抵押票據之"]),
    ("财务成本",       [r"^財務成本$"]),
    ("除税前溢利",      [r"^除(稅|所得稅)前(盈利|溢利)$", r"除稅前(盈利|溢利)$"]),
    ("所得税",        [r"^所得稅$", r"^所得稅開支$"]),
    ("本期溢利",       [r"^年內溢利$", r"^年度/期間盈利$", r"^期內/年內溢利$",
                       r"^期內溢利$", r"^年內/期內溢利$"]),
    ("股东应占溢利",    [r"^本公司權益持有人$"]),
    ("非控股权益应占溢利", [r"^非控股權益$", r"^少數股東權益$"]),
    ("每股盈利-基本",   [r"^基本\(分\)$", r"^基本及攤薄\(人民幣分\)$", r"^基本$",
                       r"每股基本盈利\(人民幣\)$", r"^\(人民幣\)$"]),
    ("每股盈利-摊薄",   [r"^攤薄\(分\)$", r"^攤薄$"]),
]

# (规范科目, [正则], 分区)。分区为 "" 表示不限区（标签本身唯一）
BS_SPEC = [
    ("物业厂房及设备",    [r"^物業廠房及設備$"], "NCA"),
    ("租赁土地权益",     [r"^於經營租賃下持作自用租賃土地中的權益$", r"^租賃土地中的權益$"], "NCA"),
    ("使用权资产",      [r"^使用權資產$"], "NCA"),
    ("无形资产",       [r"^無形資產$"], "NCA"),
    ("商誉",          [r"^商譽$"], "NCA"),
    ("其他金融资产",     [r"^其他金融資產$"], "NCA"),
    ("按金及预付款项-非流动", [r"^按金及預付款項$", r"^按金預付款項及其他應收款項$"], "NCA"),
    ("递延税项资产",     [r"^遞延稅項資產$"], "NCA"),
    ("非流动资产合计",    ["__SUB__"], "NCA"),

    ("存货",          [r"^存貨$"], "CA"),
    # 🔴 应收款项**三代口径**，分三组存、不并成一条序列（并了会造出假跳水）：
    #    FY2006-FY2010  合并一行「貿易及其他應收款項」/「應收賬款及其他應收款項」（含按金预付）
    #    FY2011         「應收賬款及應收票據」+「按金預付款項及其他應收款項」
    #    2011H2-2025    「應收賬款(貿易應收款項)」+「應收票據」+「按金預付款項及其他應收款項」
    #    实证：FY2011 年报的 FY2010 比较列 895.698+219.038 = 1,114.736 = FY2010 年报的合并行 ✓
    ("贸易及其他应收款项-合并口径", [r"^貿易及其他應收款項$", r"^應收賬款及其他應收款項$"], "CA"),
    ("应收账款及应收票据-合并口径", [r"^應收賬款及應收票據$"], "CA"),
    ("应收账款",       [r"^應收賬款$", r"^貿易應收款項$"], "CA"),
    ("应收票据",       [r"^應收票據$"], "CA"),
    ("按金预付款项及其他应收款项", [r"^按金預付款項及其他應收款項$"], "CA"),
    ("应收关连方款项",    [r"^應收關連方款項$", r"^應收關連人士款項$"], "CA"),
    # 2016 年报把标签印成「已抵押銀行存款及」（后接「受限制…」折行）→ 不能尾锚
    ("已抵押银行存款",    [r"^已抵押銀行存款"], "CA"),
    ("银行存款",       [r"^銀行存款$", r"^定期存款$"], "CA"),
    ("现金及现金等价物",   [r"^現金及現金等價物$"], "CA"),
    ("流动资产合计",     ["__SUB__"], "CA"),

    ("贸易及其他应付款项",  [r"^(貿易|應付賬款)及其他應付款項$", r"^貿易應付款項及其他應付款項$"], "CL"),
    ("合约负债",       [r"^合約負債$"], "CL"),
    ("银行贷款-流动",    [r"^銀行貸款$"], "CL"),
    ("其他贷款-流动",    [r"^其他貸款$"], "CL"),
    # 计息借贷 = 优先无抵押票据（2016 发行 / 2019-2021 陆续购回赎回）—— 9 份年报都有，
    # 漏掉会把 2016-2021 的杠杆史整段抹平
    ("计息借贷-流动",    [r"^計息借貸$"], "CL"),
    ("可换股债券-流动",   [r"^可換股債券$"], "CL"),
    ("租赁负债-流动",    [r"^租賃負債$"], "CL"),
    ("应付股东款项",     [r"^應付(貴公司|本公司)一(位|名)股東款項$"], "CL"),
    ("本期税项",       [r"^(本期|即期)稅項$"], "CL"),
    ("流动负债合计",     ["__SUB__"], "CL"),

    ("流动资产净值",     [r"^流動資產(淨值|淨額)$"], ""),
    ("总资产减流动负债",   [r"^總?資產(總額)?減流動負債$"], ""),

    ("银行贷款-非流动",   [r"^銀行貸款$"], "NCL"),
    ("计息借贷-非流动",   [r"^計息借貸$"], "NCL"),
    ("可换股债券-非流动",  [r"^可換股債券$"], "NCL"),
    ("租赁负债-非流动",   [r"^租賃負債$"], "NCL"),
    ("递延税项负债",     [r"^遞延稅項負債$"], "NCL"),
    ("非流动负债合计",    ["__SUB__"], "NCL"),

    ("资产净值",       [r"^(資產淨值|資產淨額|淨資產)$"], ""),
    ("股本",          [r"^股本$"], ""),
    ("储备",          [r"^儲備$"], ""),
    ("股东应占权益",     [r"^本公司權益持有人應佔權益總額$"], ""),
    ("非控股权益",      [r"^非控股權益$"], "EQ"),
    ("权益总额",       [r"^權益總額$"], ""),
]

CF_SPEC = [
    ("除税前溢利",      [r"^除(稅|所得稅)前(盈利|溢利)$"]),
    ("折旧",         [r"^物業廠房及設備折舊$", r"^折舊$"]),
    ("使用权资产折旧",   [r"^使用權資產折舊$"]),
    ("土地租赁款项摊销",  [r"^(持作自用的)?土地租賃款項攤銷$", r"^租賃款項攤銷$"]),
    ("无形资产摊销",    [r"^無形資產攤銷$"]),
    ("股权结算股份支付",  [r"購股權開支$", r"以股份為基礎的支付開支$", r"基於股份.*支付開支$"]),
    # ⚠️ 这两行是**不同的小计**，必须分开：「營運資金變動前的經營溢利/利潤」在营运资金
    #    变动之前，「經營所得現金」在之后。早年报表两行都印，合成一条会串值
    #    （实证：FY2008 经营所得现金 14.9 被 215.7 覆盖，差 14 倍）
    ("营运资金变动前经营溢利", [r"^營運資金變動前的?經營(溢利|利潤)$"]),
    ("经营所得现金",    [r"^經營.{0,8}(所得|產生|所用).{0,6}現金$"]),
    ("已付所得税",     [r"^已付.*所得稅$"]),
    ("经营活动现金净额",  [r"^經營活動.*現金淨額$"]),
    ("购建物业厂房设备",  [r"^購買(物業廠房及設備|固定資產).*款項?$", r"^購買物業廠房及設備$"]),
    ("出售物业厂房设备所得", [r"^出售(物業廠房及設備|固定資產)所得款項$"]),
    ("购买无形资产",    [r"^購買無形資產.*款項?$"]),
    ("收购业务付款",    [r"^收購業務", r"^收購附屬公司付款"]),
    ("已抵押银行存款变动", [r"^已抵押銀行存款[(（]?(增加|減少)"]),
    ("存入银行定期存款",  [r"^存入銀行(固定|定期)存款"]),
    ("提取银行定期存款",  [r"^(增加|提取).{0,6}銀行(固定|定期)存款"]),
    ("已收利息",      [r"^已收利息$"]),
    ("投资活动现金净额",  [r"^投資活動.*現金淨額$"]),
    ("发行股份所得",    [r"^已?發行新?股.*所得款項", r"^根據購股權發行股份所得款項$",
                      r"^行使購股權所收現金$"]),
    ("购回股份付款",    [r"^購回股份付款$"]),
    ("银行贷款所得",    [r"^(新的)?銀行貸款.{0,3}所得款項$"]),
    ("偿还银行贷款",    [r"^償還銀行貸款$"]),
    # ⚠️ 现金流量表里「購回優先無抵押票據」出现两次：经营调整段的**损益**（把非现金
    #    利得/亏损从除税前溢利剔出）与融资段的**付款**。只写前缀会先命中损益行，
    #    把 +55.1 / −52.6 这类利得当成融资现金流（实测 2016-2021 四年全错）。
    ("购回优先票据损益调整", [r"^(購回|贖回)優先無抵押票據之(虧損|收益)"]),
    ("发行优先票据所得",  [r"^(發行)?優先無抵押票據(之)?所得款項$", r"^發行優先無抵押票據$"]),
    ("购回赎回优先票据付款", [r"^購回優先無抵押票據之付款$", r"^贖回優先無抵押票據$",
                       r"^購回優先無抵押票據$"]),
    ("发行可换股债券所得", [r"^發行可換股債券的所得款項$"]),
    ("购回可换股债券付款", [r"^購回可換股債券$"]),
    ("非控股权益注资",   [r"注資.*所得款項$", r"^非控股權益持有人向一間附屬公司注資$",
                      r"^附屬公司非控股權益注資$", r"^從非控股權益收取的出資$",
                      r"^非全資擁有附屬公司一名非控股股東注入資本$", r"^來自投資者之所得款項$"]),
    ("收购非控股权益付款", [r"^收購非控股權益", r"^與非控股(股東|權益)的股權交易付款$",
                      r"^就收購非控股權益已付代價$"]),
    ("已付利息",      [r"^已付利息$"]),
    ("已付股息",      [r"^向股東派付股息$", r"^已付股息$"]),
    ("已付非控股权益股息", [r"^向非控股權益派付股息$"]),
    ("融资活动现金净额",  [r"^融資活動.*現金淨額$"]),
    ("现金净变动",     [r"^現金及現金等價物.*(增加|減少).*淨額$"]),
    # 早年把两个日期并印在标签里（「於二零零八年╱二零零七年七月一日的」共 15 字），
    # 故前缀放宽到 24 字；再加一个裸标签兜底（FY2009 年报标签折行后只剩后半截）
    ("期初现金",      [r"^於.{0,24}的現金及現金等價物$", r"^現金及現金等價物$"]),
    ("汇率影响",      [r"^[匯滙㶅]率變動(的|之)影響$", r"^滙兌調整$"]),
    ("期末现金",      [r"^於.{0,24}的現金及現金等價物$", r"^現金及現金等價物$"]),
]


# ─────────────────────────── 取数 ───────────────────────────

def _match(cands, pats):
    return any(p.search(c) for c in cands for p in pats)


def pick_flat(rows, spec):
    """按别名层挑（损益 / 现金流）。同名取第一次出现。

    ⚠️「期初现金」与「期末现金」正则几乎同形（同为「於X月X日的現金及現金等價物」），
       故按**出现顺序**分配：第一次=期初、第二次=期末。
    """
    out = {}
    compiled = [(n, [re.compile(p) for p in ps]) for n, ps in spec]
    for cands, vals, bare, _sec in rows:
        if bare:
            continue
        for name, pats in compiled:
            if name in out or not _match(cands, pats):
                continue
            # 「期末现金」与「期初现金」正则同形 → 先来的那次归期初。
            # 「汇率影响」在现金流量表里出现**两次**：一次在经营调整段（把汇兑差额
            # 从除税前溢利里剔出），一次在表底（期初→期末的桥）。勾稽要的是表底那次，
            # 故同样以「期初现金已取到」为闸（2013-2025 全部命中过此坑）。
            if name in ("期末现金", "汇率影响") and "期初现金" not in out:
                continue
            out[name] = vals
            break
    return out


def pick_bs(rows, spec):
    """分区版：分区小计取「该区内、首个链式行之前的**最后一个**无标签数字行」。

    坑①：361度 资负表的分区小计印成无标签裸数字行；且非流动区内可能有两个
    （固定資產子小计 + 区小计），故取**最后一个**；而「流動資產淨值」等链式行
    之后的裸数字是页眉页脚（如页码 361），必须排除。
    """
    subs, seen_chain = {}, set()
    for cands, vals, bare, sec in rows:
        if not sec:
            continue
        if not bare and CHAIN.match(cands[0]):
            seen_chain.add(sec)
            continue
        if bare and sec not in seen_chain:
            subs[sec] = vals

    out = {}
    compiled = [(n, ps, w) for n, ps, w in spec]
    for name, pats, where in compiled:
        if pats == ["__SUB__"]:
            if where in subs:
                out[name] = subs[where]
            continue
        rx = [re.compile(p) for p in pats]
        for cands, vals, bare, sec in rows:
            if bare or (where and sec != where):
                continue
            if _match(cands, rx):
                out[name] = vals
                break
    return out


EPS_ITEMS = ("每股盈利-基本", "每股盈利-摊薄")


def fix_eps(lines, s, e, picked, scale):
    """EPS 不是「千元/百万元」口径 —— 撤销整表单位系数，并分辨「分」与「元」。

    FY2009-2025 年报按**分**印（63.3 分），招股书按**元**印（0.243 元）；
    不看单位直接采数会差 100 倍。
    """
    # ⚠️ 单位写在**全角**括号里（「基本（分）」），不做全角归一就永远探不到「分」
    #    —— 会让 FY2009-2020 的 EPS 整段差 100 倍（20.1 分被当成 20.1 元）。
    blob = "".join(lines[s:min(e, len(lines))]).replace("（", "(").replace("）", ")")
    blob = re.sub(r"\s+", "", blob)
    m = re.search(r"每股(基本)?盈利", blob)
    cents = False
    if m:
        ctx = blob[m.start():m.start() + 140]
        cents = "(分)" in ctx or "人民幣分" in ctx
    factor = (0.01 if cents else 1.0) / (scale or 1.0)
    for k in EPS_ITEMS:
        if k in picked:
            picked[k] = {i: (None if v is None else v * factor)
                         for i, v in picked[k].items()}
    return "人民幣分" if cents else "人民幣元"


def extract(name):
    """一份 PDF → {'is': {科目: {期间: 值}}, 'bs': …, 'cf': …}。"""
    lines = ensure_text(name)
    if name == "361度-招股说明书":
        pos = {}
        for k in ("is", "bs", "cf"):
            hits = [i for i in find_titles(lines, k)
                    if re.match(r"^\s*\d+\.", lines[i])]
            if not hits:
                raise SystemExit(f"🔴 招股书未定位 {k}")
            pos[k] = hits[0]
        a, b, c = pos["is"], pos["bs"], pos["cf"]
    else:
        loc = locate_three(lines)
        if not loc:
            raise SystemExit(f"🔴 {name} 三表定位失败")
        a, b, c = loc

    out, units = {}, {}
    for key, spec, s, hard in (("is", IS_SPEC, a, b),
                               ("bs", BS_SPEC, b, c),
                               ("cf", CF_SPEC, c, c + 420)):
        e = block_end(lines, s, hard)
        cols, hdr = find_year_columns(lines, s)
        scale, _u = detect_scale(lines, s)
        if not cols or scale is None:
            raise SystemExit(f"🔴 {name} {key}：表头或单位缺失")
        want = COLMAP[name][key]
        if len(cols) != len(want):
            raise SystemExit(
                f"🔴 {name} {key}：检出 {len(cols)} 列 {[y for y, _ in cols]}，"
                f"COLMAP 声明 {len(want)} 列 {want} —— 拒绝猜测")
        rows = parse_block(lines, hdr, e, [cc for _, cc in cols], scale)
        picked = pick_bs(rows, spec) if key == "bs" else pick_flat(rows, spec)
        if key == "is":
            units["eps"] = fix_eps(lines, s, e, picked, scale)
        out[key] = {item: {want[i]: v for i, v in vals.items()
                           if want[i] not in DROP}
                    for item, vals in picked.items()}
    return out, units


# ─────────────────────────── 汇总 ───────────────────────────

SOURCE_OF = {}
DERIVED = []


def assemble():
    """每个期间取自**其权威来源的本期列**；其余列留作跨源交叉核。"""
    data = {"is": {}, "bs": {}, "cf": {}}
    cross = {"is": {}, "bs": {}, "cf": {}}      # (科目, 期间) -> [(来源, 值)]
    units = {}
    for name in FILES:
        got, u = extract(name)
        units[name] = u
        for st in ("is", "bs", "cf"):
            for item, vals in got[st].items():
                for per, v in vals.items():
                    if OWNER.get(per) == name:
                        data[st].setdefault(item, {})[per] = v
                        SOURCE_OF[(st, item, per)] = name
                    else:
                        cross[st].setdefault((item, per), []).append((name, v))
    derive(data)
    return data, cross, units


NCL_ITEMS = ("银行贷款-非流动", "租赁负债-非流动", "递延税项负债")


def derive(data):
    """恒等派生：361度 报表**不印总资产/总负债行**（坑②），按分区小计补。"""
    # FY2006-FY2009 无非控股权益，当年损益表**不设**「應佔：」分配段 → 股东应占溢利 = 本期溢利。
    # 这不是猜数：是同表内恒等关系，且**仅在非控股权益整行不存在时**套用；
    # 一旦某期出现非控股权益（FY2010 起），立即停用、只取报表印出数。
    is_ = data["is"]
    for per in PERIODS:
        if is_.get("股东应占溢利", {}).get(per) is not None:
            continue
        if is_.get("非控股权益应占溢利", {}).get(per):
            continue
        v = is_.get("本期溢利", {}).get(per)
        if v is not None:
            is_.setdefault("股东应占溢利", {})[per] = v
            SOURCE_OF[("is", "股东应占溢利", per)] = "恒等派生(=本期溢利·当期无非控股权益)"
            DERIVED.append(f"{per} 股东应占溢利 = 本期溢利（该期损益表无「應佔：」分配段）")

    bs = data["bs"]
    for per in PERIODS:
        # 非流动负债只有一项时报表不印小计行（FY2006-2011H2 仅递延税项负债）→ 按分项求和。
        # 刻意**不**用「总资产减流动负债 − 资产净值」倒算：那会让下游同名勾稽变成恒真。
        if bs.get("非流动负债合计", {}).get(per) is None:
            parts = [bs.get(k, {}).get(per) for k in NCL_ITEMS]
            parts = [p for p in parts if p is not None]
            if parts:
                bs.setdefault("非流动负债合计", {})[per] = sum(parts)
                SOURCE_OF[("bs", "非流动负债合计", per)] = "恒等派生(非流动负债各分项求和)"
                DERIVED.append(f"{per} 非流动负债合计 = 分项求和（该期报表无小计行）")

        nca = bs.get("非流动资产合计", {}).get(per)
        ca = bs.get("流动资产合计", {}).get(per)
        cl = bs.get("流动负债合计", {}).get(per)
        ncl = bs.get("非流动负债合计", {}).get(per)
        if nca is not None and ca is not None:
            bs.setdefault("资产总值", {})[per] = nca + ca
            SOURCE_OF[("bs", "资产总值", per)] = "恒等派生(非流动+流动)"
        if cl is not None:
            tot = cl + (ncl or 0.0)
            bs.setdefault("负债总值", {})[per] = tot
            SOURCE_OF[("bs", "负债总值", per)] = "恒等派生(流动负债+非流动负债)"
            if ncl is None:
                DERIVED.append(f"{per} 负债总值仅含流动负债（该期无非流动负债小计行）")


# ─────────────────────────── 校验 ───────────────────────────

TOL = 0.6          # 百万元。早年源为千元、四舍五入到 3 位小数，给 60 万容差

# ────────── 已判读的口径断点（跨源差异白名单）──────────
# 跨源交叉核把「本期列」与「另一份报告的比较列」逐格对照。差异 ≠ 解析错，也可能是
# 公司**真的重列**。下面每一条都已回一手核实并有**算术佐证**；
# 未列入此表的新差异 = 需要人判读的新情况，会单独列出。
KNOWN_RECAST = {
    # ① 2019 年报把「金融資產減值虧損」从行政开支拆成单独一行，2018 比较列同步重列。
    #    佐证：543.511(重列后行政开支) + 1.200(拆出的减值) = 544.711(2018 年报原行政开支) ✓
    ("is", "行政开支", "2018"): "2019起ECL自行政开支拆出单列·543.5+1.2=544.7 ✓",
    # ② FY2011 年报印合并行「應收賬款及應收票據」，过渡期年报起拆成两行。
    #    佐证：1,558.558(应收账款) + 23.100(应收票据) = 1,581.658 ✓（已分行存）
    ("bs", "应收账款及应收票据-合并口径", "FY2011/6"): "2011H2起拆为应收账款+应收票据·1558.6+23.1=1581.7 ✓",
    # ③ 2019 年报把递延税项资产与负债**净额**列示(41.310)，2020 年报改**总额**列示
    #    (资产 60.419 / 负债 19.109)。差额恒为 19.109，资产净值不变 ✓
    ("bs", "递延税项资产", "2019"): "2020起递延税项由净额改总额列示(+19.109)",
    ("bs", "非流动资产合计", "2019"): "同上·+19.109",
    ("bs", "总资产减流动负债", "2019"): "同上·+19.109",
    ("bs", "非流动负债合计", "2019"): "同上·+19.109",
    # ④ 2021 年报把 2.174「就購買土地使用權支付的按金」由经营重分类到投资，两侧恰好抵消
    ("cf", "经营所得现金", "2020"): "2021起土地使用权按金由经营改列投资(±2.174)",
    ("cf", "经营活动现金净额", "2020"): "同上·±2.174",
    ("cf", "投资活动现金净额", "2020"): "同上·±2.174",
    # ⑤ 2022 年报把非控股权益往来（应收 6.290 / 应付 0.710）轧差为 7.000 并全部列入融资
    ("cf", "投资活动现金净额", "2021"): "2022起非控股权益往来轧差改列融资(−6.290)",
    ("cf", "融资活动现金净额", "2021"): "同上·+6.290",
    # ⑥ 2015 年报把「非即期預付款項減少」并入购建 PPE 一行。
    #    佐证：−135.046(购建) + 20.475(非即期预付款减少) = −114.571 ✓
    ("cf", "购建物业厂房设备", "2014"): "2015起非即期预付款项变动并入购建PPE·−135.046+20.475=−114.571 ✓",
}


def g(data, st, item, per):
    return data.get(st, {}).get(item, {}).get(per)


def close(a, b, tol=TOL):
    return a is not None and b is not None and abs(a - b) <= tol


def validate(data, cross):
    errs, warns, n = [], [], 0

    for per in PERIODS:
        rev = g(data, "is", "营业额", per)
        cos = g(data, "is", "销售成本", per)
        gp = g(data, "is", "毛利", per)
        if None not in (rev, cos, gp):
            n += 1
            if not close(rev - abs(cos), gp):
                errs.append(f"[损益 {per}] 营收−|成本|={rev-abs(cos):.1f} ≠ 毛利 {gp:.1f}")

        pbt = g(data, "is", "除税前溢利", per)
        tax = g(data, "is", "所得税", per)
        pft = g(data, "is", "本期溢利", per)
        if None not in (pbt, tax, pft):
            n += 1
            if not close(pbt - abs(tax), pft):
                errs.append(f"[损益 {per}] 除税前−|税|={pbt-abs(tax):.1f} ≠ 本期溢利 {pft:.1f}")

        sh = g(data, "is", "股东应占溢利", per)
        nci = g(data, "is", "非控股权益应占溢利", per)
        if None not in (sh, nci, pft):
            n += 1
            if not close(sh + nci, pft):
                errs.append(f"[损益 {per}] 股东{sh:.1f}+非控股{nci:.1f} ≠ 本期溢利 {pft:.1f}")

        # ── 资产负债表链 ──
        nca = g(data, "bs", "非流动资产合计", per)
        ca = g(data, "bs", "流动资产合计", per)
        cl = g(data, "bs", "流动负债合计", per)
        ncl = g(data, "bs", "非流动负债合计", per)
        nwc = g(data, "bs", "流动资产净值", per)
        tamcl = g(data, "bs", "总资产减流动负债", per)
        na = g(data, "bs", "资产净值", per)
        if None not in (ca, cl, nwc):
            n += 1
            if not close(ca - cl, nwc):
                errs.append(f"[资负 {per}] 流动资产−流动负债={ca-cl:.1f} ≠ 流动资产净值 {nwc:.1f}")
        if None not in (nca, nwc, tamcl):
            n += 1
            if not close(nca + nwc, tamcl):
                errs.append(f"[资负 {per}] 非流动{nca:.1f}+净流动{nwc:.1f} ≠ 总资产减流动负债 {tamcl:.1f}")
        if None not in (tamcl, na):
            n += 1
            if not close(tamcl - (ncl or 0.0), na):
                errs.append(f"[资负 {per}] 总资产减流动负债−非流动负债 ≠ 资产净值 {na:.1f}")

        cap = g(data, "bs", "股本", per)
        res = g(data, "bs", "储备", per)
        she = g(data, "bs", "股东应占权益", per)
        nci_b = g(data, "bs", "非控股权益", per)
        teq = g(data, "bs", "权益总额", per)
        if None not in (cap, res, she):
            n += 1
            if not close(cap + res, she):
                errs.append(f"[资负 {per}] 股本+储备={cap+res:.1f} ≠ 股东应占权益 {she:.1f}")
        if None not in (she, nci_b, teq):
            n += 1
            if not close(she + nci_b, teq):
                errs.append(f"[资负 {per}] 股东权益+非控股={she+nci_b:.1f} ≠ 权益总额 {teq:.1f}")
        if None not in (teq, na):
            n += 1
            if not close(teq, na):
                errs.append(f"[资负 {per}] 权益总额 {teq:.1f} ≠ 资产净值 {na:.1f}")

        # ── 现金流 ──
        op = g(data, "cf", "经营活动现金净额", per)
        iv = g(data, "cf", "投资活动现金净额", per)
        fi = g(data, "cf", "融资活动现金净额", per)
        ch = g(data, "cf", "现金净变动", per)
        if None not in (op, iv, fi, ch):
            n += 1
            if not close(op + iv + fi, ch):
                errs.append(f"[现金 {per}] 经营+投资+融资={op+iv+fi:.1f} ≠ 净变动 {ch:.1f}")
        b0 = g(data, "cf", "期初现金", per)
        fx = g(data, "cf", "汇率影响", per) or 0.0
        b1 = g(data, "cf", "期末现金", per)
        if None not in (b0, ch, b1):
            n += 1
            if not close(b0 + ch + fx, b1):
                errs.append(f"[现金 {per}] 期初{b0:.1f}+净变{ch:.1f}+汇率{fx:.1f} ≠ 期末 {b1:.1f}")

        # ── 跨表 ──
        cash_bs = g(data, "bs", "现金及现金等价物", per)
        if None not in (cash_bs, b1):
            n += 1
            if not close(cash_bs, b1):
                warns.append(f"[跨表 {per}] 资负现金 {cash_bs:.1f} vs 现金流期末 {b1:.1f}")
        pbt_cf = g(data, "cf", "除税前溢利", per)
        if None not in (pbt, pbt_cf):
            n += 1
            if not close(pbt, pbt_cf):
                errs.append(f"[跨表 {per}] 损益除税前 {pbt:.1f} ≠ 现金流起点 {pbt_cf:.1f}")

    # ── 跨源交叉核：本期列 vs 另一份报告的比较列 ──
    xn, xdiff, xknown = 0, [], []
    for st in ("is", "bs", "cf"):
        for (item, per), lst in cross[st].items():
            base = g(data, st, item, per)
            if base is None:
                continue
            for src, v in lst:
                if v is None:
                    continue
                xn += 1
                if abs(v - base) <= TOL:
                    continue
                line = f"[交叉 {st}·{item}·{per}] 权威 {base:.1f} vs {src} 比较列 {v:.1f}"
                why = KNOWN_RECAST.get((st, item, per))
                (xknown if why else xdiff).append(f"{line}  ← {why}" if why else line)
    return errs, warns, n, xn, xdiff, xknown


# ─────────────────────────── 写出 ───────────────────────────

HEAD = {
    "is": "# 利润表（361度 01361.HK）· 单位：人民币百万元（每股盈利=人民币元）；负数=减项；空=该期财报无此科目",
    "bs": "# 资产负债表（361度 01361.HK）· 单位：人民币百万元；空=该期财报无此科目",
    "cf": "# 现金流量表（361度 01361.HK）· 单位：人民币百万元；负数=流出；空=该期财报无此科目",
}
NOTE = ("# 🔴 期间轴三段：FY2006/6–FY2011/6 为止6月30日的财政年度；2011H2 为 6 个月过渡期"
        "（2011-07-01~2011-12-31，财政年度结算日变更）；2012 起为止12月31日的财政年度。"
        "2011H2 是半年数，不可直接接入年度序列做同比/复合增速。")
SRC = "# 来源：report/361度/ 招股说明书(FY2006-FY2008) + 各期年报逐行解析（_build_from_pdf.py）"

ORDER = {"is": [n for n, _ in IS_SPEC],
         "bs": [n for n, _, _ in BS_SPEC] + ["资产总值", "负债总值"],
         "cf": [n for n, _ in CF_SPEC]}
FILENAME = {"is": "利润表.csv", "bs": "资产负债表.csv", "cf": "现金流量表.csv"}


def write_csv(data):
    for st in ("is", "bs", "cf"):
        path = os.path.join(HERE, FILENAME[st])
        with open(path, "w", newline="", encoding="utf-8") as f:
            f.write(HEAD[st] + "\n" + NOTE + "\n" + SRC + "\n")
            w = csv.writer(f)
            w.writerow(["科目"] + PERIODS)
            for item in ORDER[st]:
                vals = data[st].get(item)
                if not vals or all(v is None for v in vals.values()):
                    continue
                row = [item]
                for per in PERIODS:
                    v = vals.get(per)
                    row.append("" if v is None else f"{v:.3f}".rstrip("0").rstrip("."))
                w.writerow(row)
        print(f"  ✅ {FILENAME[st]}")


def coverage(data):
    """每个期间缺哪些核心科目 —— 防「勾稽全过」其实是「值缺失所以没查」。"""
    core = {"is": ["营业额", "销售成本", "毛利", "经营溢利", "除税前溢利", "所得税",
                   "本期溢利", "股东应占溢利"],
            "bs": ["流动资产合计", "流动负债合计", "非流动资产合计", "资产净值",
                   "权益总额", "现金及现金等价物", "存货"],
            "cf": ["经营活动现金净额", "投资活动现金净额", "融资活动现金净额",
                   "现金净变动", "期初现金", "期末现金"]}
    out = []
    for per in PERIODS:
        miss = [f"{st}·{it}" for st, items in core.items() for it in items
                if g(data, st, it, per) is None]
        if miss:
            out.append(f"{per}: 缺 {', '.join(miss)}")
    return out


def main():
    check_only = "--check" in sys.argv
    data, cross, units = assemble()
    errs, warns, n, xn, xdiff, xknown = validate(data, cross)
    gaps = coverage(data)

    print(f"\n勾稽校验：{n} 条恒等式 · 跨源交叉核 {xn} 格")
    if xknown:
        print(f"已判读的口径断点（{len(xknown)} 处·均有算术佐证）：")
        for d in xknown:
            print(f"  ◻ {d}")
    for w in warns:
        print(f"  🟡 {w}")
    for d in xdiff:
        print(f"  🟡 未判读差异 {d}")
    for e in errs:
        print(f"  🔴 {e}")
    if DERIVED:
        print(f"恒等派生 {len(DERIVED)} 处（见 README）")
    print("核心科目缺失：" + ("无" if not gaps else ""))
    for gp in gaps:
        print(f"  ⏳ {gp}")

    if errs:
        raise SystemExit(f"\n🔴 {len(errs)} 条勾稽不过 —— 按纪律不写出 CSV")
    print(f"\n✅ 勾稽全部通过（{n} 条）")
    if not check_only:
        write_csv(data)
        from _build_ratios import build_ratios   # 延迟导入：避免与本模块循环
        build_ratios(data)


if __name__ == "__main__":
    main()
