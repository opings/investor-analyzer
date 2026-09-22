#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""特步国际（01368.HK）三表构建器 —— 一手财报 PDF → 别名层 → 勾稽校验 → CSV。

真源：report/特步国际/
  · 特步国际-招股说明书.pdf        → 2005 / 2006 / 2007（附錄一 会计师报告，上市前三年）
  · 特步国际-YYYY.pdf(2008-2025)  → 各年三表；**本年列为准**，上年比较列用于跨年交叉核

为什么源在港交所披露易而非巨潮：cninfo 港股镜像对本公司**不全** —— 2008 整年无记录
（招股书缺），FY2008/2009/2010/2011/2019 只有「业绩公布」没有年报全文。

解析细节与三个已固化的坑见 `_parse_core.py` 顶部注释（标题跨行 / 装饰字体 +31
编码偏移 / 表尾靠分页符收 + 骨架覆盖度挑表）。

用法：
    python3 _build_from_pdf.py            # 全量重建（校验通过才写 CSV）
    python3 _build_from_pdf.py --check    # 只跑校验，不写文件
    python3 _build_from_pdf.py --miss     # 列出未进别名层的标签（按出现次数排序）
"""
import csv
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _parse_core as pc  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
YEARS = pc.ALL_YEARS                       # 2005–2025
SCALE = 1000.0                             # RMB'000 → 人民币百万元
NO_SCALE = {"每股盈利-基本", "每股盈利-摊薄"}   # 本就是「人民币分」，不缩放

# ───────────────────────── 别名层 ─────────────────────────
# key = 归一后的英文标签（见 _parse_core.norm_label）；value = 规范中文科目。
# 资产负债表的 key 前缀 "节区|" —— 计息银行借贷 / 租赁负债 / 定期存款 / 可换股债券
# 等在流动与非流动两节**同名**，不带节区会互相覆盖。

IS_MAP = {
    "revenue": "营业额",
    "cost of sales": "销售成本",
    "gross profit": "毛利",
    "other income and gains": "其他收益",
    "other income and gains net": "其他收益",
    "selling and distribution costs": "销售及分销开支",
    "selling and distribution expenses": "销售及分销开支",
    "general and administrative expenses": "行政开支",
    "other operating expenses": "其他经营开支",
    "operating profit": "经营溢利",
    "finance costs": "净融资收入",
    "finance costs net": "净融资收入",
    "net finance costs": "净融资收入",
    "net finance cost": "净融资收入",
    "net finance income": "净融资收入",
    "net finance income/(cost)": "净融资收入",
    "finance income/(costs) net": "净融资收入",
    "share of profits of associates": "分占联营公司损益",
    "share of losses of associates": "分占联营公司损益",
    "share of profits/(losses) of associates": "分占联营公司损益",
    "profit before tax": "除税前溢利",
    "profit before tax from continuing operations": "除税前溢利",
    "tax": "税项",
    "income tax expense": "税项",
    "profit for the year from continuing operations": "持续经营业务溢利",
    "loss for the year from a discontinued operation": "非持续经营业务损益",
    "profit for the year": "年内溢利",
    "ordinary equity holders of the company": "股东应占溢利",
    "non-controlling interests": "非控股权益应占溢利",
    "non-controlling interest": "非控股权益应占溢利",
    "dividend": "股息",
    "dividends": "股息",
    "- basic rmb": "每股盈利-基本",
    "basic (rmb cents)": "每股盈利-基本",
    "- basic (rmb cents)": "每股盈利-基本",
    "basic - for profit for the year rmb": "每股盈利-基本",
    "- diluted rmb": "每股盈利-摊薄",
    "diluted (rmb cents)": "每股盈利-摊薄",
    "- diluted (rmb cents)": "每股盈利-摊薄",
    "diluted - for profit for the year rmb": "每股盈利-摊薄",
}

BS_MAP = {
    # ── 非流动资产
    "非流动资产|property plant and equipment": "物业厂房及设备",
    "非流动资产|investment properties": "投资物业",
    "非流动资产|right-of-use assets": "使用权资产",
    "非流动资产|prepaid land lease payments": "土地使用权预付款项",
    "非流动资产|deposits for acquisition of land use rights": "购地预付款项",
    "非流动资产|deposit paid for acquisition of land use rights": "购地预付款项",
    "非流动资产|deposits paid for acquisitions of land use rights": "购地预付款项",
    "非流动资产|deposits paid for acquisition of items of property plant and equipment":
        "购建设备预付款项",
    "非流动资产|goodwill": "商誉",
    "非流动资产|intangible assets": "无形资产",
    "非流动资产|investments in associates": "联营公司投资",
    "非流动资产|available-for-sale investments": "其他投资-非流动",
    "非流动资产|available-for-sale investment": "其他投资-非流动",
    # ⚠️ FVOCI 与 FVTPL 是两行、都在非流动节，归一到同名会互相覆盖
    #    （FY2024 实证：282.2 与 1046.1 撞名，后者吞掉前者）
    "非流动资产|equity investments designated at fair value through other":
        "FVOCI权益投资-非流动",
    "非流动资产|equity investments designated at fair value through other comprehensive income":
        "FVOCI权益投资-非流动",
    "非流动资产|financial assets at fair value through profit or loss":
        "FVTPL金融资产-非流动",
    "非流动资产|structured bank deposits": "结构性存款-非流动",
    "非流动资产|derivative financial instruments": "衍生金融工具-非流动",
    "非流动资产|deferred tax assets": "递延税项资产",
    "非流动资产|pledged bank deposits": "已抵押存款-非流动",
    "非流动资产|pledged deposits": "已抵押存款-非流动",
    "非流动资产|time deposits": "定期存款-非流动",
    "非流动资产|term deposits": "定期存款-非流动",
    "非流动资产|non-current time deposits": "定期存款-非流动",
    "非流动资产|deposits": "按金及其他应收款项-非流动",
    "非流动资产|deposits and other assets": "按金及其他应收款项-非流动",
    "非流动资产|deposits and other asset": "按金及其他应收款项-非流动",
    "非流动资产|deposits and other receivables": "按金及其他应收款项-非流动",
    "非流动资产|prepayments deposits and other asset": "按金及其他应收款项-非流动",
    "非流动资产|prepayments deposits and other receivables": "按金及其他应收款项-非流动",
    "非流动资产|prepayment deposits and other asset": "按金及其他应收款项-非流动",
    "非流动资产|prepayments other receivables and other asset": "按金及其他应收款项-非流动",
    "非流动资产|prepayments other receivables and other assets": "按金及其他应收款项-非流动",
    "非流动资产|total non-current assets": "非流动资产合计",
    # ── 流动资产
    "流动资产|inventories": "存货",
    "流动资产|trade receivables": "应收贸易账款",
    "流动资产|receivables": "应收贸易账款",
    "流动资产|bills receivables": "应收票据",
    "流动资产|bills receivable": "应收票据",
    "流动资产|trade and bills receivables": "应收贸易账款及票据",
    "流动资产|prepayments deposits and other receivables": "预付款项按金及其他应收款项",
    "流动资产|prepayments other receivables and other assets": "预付款项按金及其他应收款项",
    "流动资产|prepayments other receivables and other asset": "预付款项按金及其他应收款项",
    "流动资产|prepayments deposits other receivables and other asset":
        "预付款项按金及其他应收款项",
    "流动资产|prepayments deposits and other asset": "预付款项按金及其他应收款项",
    "流动资产|prepayment deposits and other asset": "预付款项按金及其他应收款项",
    "流动资产|deposits and other receivables": "预付款项按金及其他应收款项",
    "流动资产|tax recoverable": "可收回税项",
    "流动资产|available-for-sale investments": "其他投资-流动",
    "流动资产|available-for-sale investment": "其他投资-流动",
    "流动资产|financial assets at fair value through profit or loss": "FVTPL金融资产-流动",
    "流动资产|structured bank deposits": "结构性存款-流动",
    "流动资产|equity investments designated at fair value through other":
        "FVOCI权益投资-流动",
    "流动资产|derivative financial instruments": "衍生金融工具-流动",
    "流动资产|pledged bank deposits": "已抵押存款-流动",
    "流动资产|pledged deposits": "已抵押存款-流动",
    "流动资产|time deposits": "定期存款-流动",
    "流动资产|term deposits": "定期存款-流动",
    "流动资产|cash and cash equivalents": "现金及现金等价物",
    "流动资产|cash and bank balances": "现金及现金等价物",
    "流动资产|total current assets": "流动资产合计",
    # ── 流动负债
    "流动负债|trade payables": "应付贸易账款",
    "流动负债|bills payable": "应付票据",
    "流动负债|trade and bills payables": "应付贸易账款及票据",
    "流动负债|deposits received other payables and accruals": "其他应付款项及应计费用",
    "流动负债|other payables and accruals": "其他应付款项及应计费用",
    "流动负债|other payables": "其他应付款项及应计费用",
    "流动负债|accruals": "其他应付款项及应计费用",
    "流动负债|interest-bearing bank borrowings": "计息银行借贷-流动",
    "流动负债|bank borrowings": "计息银行借贷-流动",
    "流动负债|lease liabilities": "租赁负债-流动",
    "流动负债|tax payable": "应付税项",
    "流动负债|dividend payable": "应付股息",
    "流动负债|due to a director": "应付董事款项",
    "流动负债|due to related parties": "应付关联方款项",
    "流动负债|deferred subsidies": "递延补贴-流动",
    "流动负债|deferred subsidy": "递延补贴-流动",
    # ⚠️ 两只可换股债券并存（特步 CB / K-Swiss CB），归一到同名会互相覆盖
    #    FY2023 实证：非流动 460.4、流动 418.8，撞名后跨年交叉核显示为「两值对调」
    "流动负债|xtep convertible bonds": "可换股债券-特步-流动",
    "流动负债|k-swiss convertible bonds": "可换股债券-KSwiss-流动",
    "流动负债|convertible bonds": "可换股债券-特步-流动",
    "流动负债|derivative financial instruments": "衍生金融工具负债-流动",
    "流动负债|total current liabilities": "流动负债合计",
    "流动负债|net current assets": "流动资产净值",
    "流动负债|net current liabilities": "流动资产净值",
    "流动负债|total assets less current liabilities": "资产总值减流动负债",
    # ── 非流动负债
    "非流动负债|interest-bearing bank borrowings": "计息银行借贷-非流动",
    "非流动负债|bank borrowings": "计息银行借贷-非流动",
    "非流动负债|lease liabilities": "租赁负债-非流动",
    "非流动负债|deferred tax liabilities": "递延税项负债",
    "非流动负债|deferred subsidies": "递延补贴-非流动",
    "非流动负债|deferred subsidy": "递延补贴-非流动",
    "非流动负债|xtep convertible bonds": "可换股债券-特步-非流动",
    "非流动负债|k-swiss convertible bonds": "可换股债券-KSwiss-非流动",
    "非流动负债|convertible bonds": "可换股债券-特步-非流动",
    "非流动负债|preferred shares": "优先股",
    "非流动负债|derivative component of preferred shares": "优先股衍生部分",
    "非流动负债|derivative financial instruments": "衍生金融工具负债-非流动",
    "非流动负债|other payables": "其他非流动负债",
    "非流动负债|other liabilities": "其他非流动负债",
    "非流动负债|total non-current liabilities": "非流动负债合计",
    "非流动负债|net assets": "资产净值",
    # ── 权益
    "权益|share capital": "股本",
    "权益|issued capital": "股本",
    "权益|issued share capital": "股本",
    "权益|treasury shares": "库存股",
    "权益|equity component of convertible bonds": "可换股债券权益部分",
    "权益|reserves": "储备",
    "权益|other reserves": "储备",
    "权益|non-controlling interests": "非控股权益",
    "权益|non-controlling interest": "非控股权益",
    "权益|total equity": "权益总值",
    "权益|net assets": "资产净值",
}

CF_MAP = {
    "profit before tax": "除税前溢利",
    "depreciation": "折旧",
    "depreciation of property plant and equipment and investment properties": "折旧",
    "depreciation property plant and equipment and investment properties": "折旧",
    "depreciation of right-of-use assets": "使用权资产折旧",
    "depreciation of right-of-use assets/amortisation of prepaid land lease payments":
        "使用权资产折旧",
    "amortisation of prepaid land lease payments": "土地使用权摊销",
    "amortisation of intangible assets": "无形资产摊销",
    "equity-settled share option expense": "股份支付开支",
    "equity-settled share award expense": "股份支付开支",
    "equity-settled share award scheme expense": "股份支付开支",
    "equity-settled share awards expense": "股份支付开支",
    "provision for inventories": "存货拨备",
    "provision/(write-back of provision) for inventories": "存货拨备",
    "cash generated from operations": "经营产生的现金",
    "cash generated from/(used in) operations": "经营产生的现金",
    "interest received": "已收利息",
    "overseas taxes paid": "已付所得税",
    "overseas taxes refunded/(paid)": "已付所得税",
    "net cash flows from operating activities": "经营活动现金净额",
    "net cash inflow from operating activities": "经营活动现金净额",
    "net cash inflow/(outflow) from operating activities": "经营活动现金净额",
    "purchases of items of property plant and equipment": "购建物业厂房设备",
    "additions of intangible assets": "购买无形资产",
    "additions to intangible assets": "购买无形资产",
    "additions of investments in associates": "投资联营公司",
    "net cash flows used in investing activities": "投资活动现金净额",
    "net cash flows from/(used in) investing activities": "投资活动现金净额",
    "net cash outflow from investing activities": "投资活动现金净额",
    "net cash used in investing activities": "投资活动现金净额",
    "new bank loans": "新增银行贷款",
    "new bank loans net of bank charges on syndicated loans": "新增银行贷款",
    "new bank loans net of bank charges on a syndicated loan": "新增银行贷款",
    "new bank loans and bank advances for discounted bills": "新增银行贷款",
    "new bank loans and bank advances for discounted bills net of bank charges on a syndicated loan":
        "新增银行贷款",
    "repayment of bank loans": "偿还银行贷款",
    "repayment of bank loans and settlement of bank advances for discounted bills":
        "偿还银行贷款",
    "dividends paid": "已付股东股息",
    "dividend paid": "已付股东股息",
    "interest paid": "已付利息",
    "lease payments": "租赁付款",
    "principal elements of lease payments": "租赁付款",
    "repurchase of shares": "购回股份",
    "repurchase of shares under share award scheme": "购回股份",
    "net proceeds from placing of shares": "配售股份所得净额",
    "net proceeds from issue of ordinary shares": "发行股份所得净额",
    "net cash flows used in financing activities": "融资活动现金净额",
    "net cash flows from/(used in) financing activities": "融资活动现金净额",
    "net cash flows from financing activities": "融资活动现金净额",
    "net cash inflow from financing activities": "融资活动现金净额",
    "net increase/(decrease) in cash and cash equivalents": "现金净变动",
    "increase/(decrease) in cash and cash equivalents": "现金净变动",
    "net increase in cash and cash equivalents": "现金净变动",
    "net decrease in cash and cash equivalents": "现金净变动",
    "net (decrease)/increase in cash and cash equivalents": "现金净变动",
    "increase in cash and cash equivalents": "现金净变动",
    "decrease in cash and cash equivalents": "现金净变动",
    "cash and cash equivalents at beginning of year": "期初现金",
    "cash and cash equivalent at beginning of year": "期初现金",
    "effect of foreign exchange rate changes net": "汇率影响",
    "cash and cash equivalents at end of year": "期末现金",
}

MAPS = {"IS": IS_MAP, "BS": BS_MAP, "CF": CF_MAP}

# 正则兜底（精确字典未命中时才用）。
# ⚠️ 为什么需要：EPS 行印成「Basic / — For profit for the year」或
#   「EARNINGS PER SHARE ATTRIBUTABLE TO … / — Basic (RMB cents)」两段，
#   解析器的折行合并会把上一行的长标题接到前面，精确 key 必然落空。
#   但「— For profit from continuing operations」那两行**没有** basic/diluted 前缀
#   （它们紧跟在空行后，pending 已清空），故不会误配 —— 这正是本兜底安全的前提。
IS_RE = [
    (re.compile(r"(^|\s)-?\s*basic\b.*\brmb"), "每股盈利-基本"),
    (re.compile(r"(^|\s)-?\s*diluted\b.*\brmb"), "每股盈利-摊薄"),
]
RE_MAPS = {"IS": IS_RE, "BS": [], "CF": []}


def resolve(kind, label, sec):
    """标签 → 规范科目：先精确字典，再正则兜底；都不中返回 None。"""
    hit = MAPS[kind].get(key_of(kind, label, sec))
    if hit:
        return hit
    for pat, canon in RE_MAPS[kind]:
        if pat.search(label):
            return canon
    return None

# CSV 行序（别名层可能给出同名多行，这里定顺序 + 决定哪些进表）
IS_ORDER = ["营业额", "销售成本", "毛利", "其他收益", "销售及分销开支", "行政开支",
            "其他经营开支", "经营溢利", "净融资收入", "分占联营公司损益",
            "除税前溢利", "税项", "持续经营业务溢利", "非持续经营业务损益",
            "年内溢利", "股东应占溢利", "非控股权益应占溢利", "股息",
            "每股盈利-基本", "每股盈利-摊薄"]
BS_ORDER = ["物业厂房及设备", "投资物业", "使用权资产", "土地使用权预付款项",
            "购地预付款项", "购建设备预付款项", "商誉", "无形资产", "联营公司投资",
            "其他投资-非流动",
            "FVOCI权益投资-非流动", "FVTPL金融资产-非流动", "结构性存款-非流动",
            "衍生金融工具-非流动", "已抵押存款-非流动", "定期存款-非流动",
            "按金及其他应收款项-非流动", "递延税项资产", "非流动资产合计",
            "存货", "应收贸易账款", "应收票据", "应收贸易账款及票据",
            "预付款项按金及其他应收款项", "可收回税项", "其他投资-流动",
            "FVOCI权益投资-流动", "FVTPL金融资产-流动", "结构性存款-流动",
            "衍生金融工具-流动", "已抵押存款-流动", "定期存款-流动",
            "现金及现金等价物", "流动资产合计",
            "应付贸易账款", "应付票据", "应付贸易账款及票据", "其他应付款项及应计费用",
            "计息银行借贷-流动", "租赁负债-流动",
            "可换股债券-特步-流动", "可换股债券-KSwiss-流动",
            "衍生金融工具负债-流动", "递延补贴-流动", "应付税项", "应付股息",
            "应付董事款项", "应付关联方款项",
            "流动负债合计", "流动资产净值", "资产总值减流动负债",
            "计息银行借贷-非流动", "租赁负债-非流动",
            "可换股债券-特步-非流动", "可换股债券-KSwiss-非流动",
            "优先股", "优先股衍生部分", "衍生金融工具负债-非流动",
            "递延税项负债", "递延补贴-非流动",
            "其他非流动负债", "非流动负债合计", "资产净值",
            "股本", "库存股", "可换股债券权益部分", "储备", "非控股权益", "权益总值"]
CF_ORDER = ["除税前溢利", "折旧", "使用权资产折旧", "土地使用权摊销", "无形资产摊销",
            "股份支付开支", "存货拨备", "经营产生的现金", "已收利息", "已付所得税",
            "经营活动现金净额", "购建物业厂房设备", "购买无形资产", "投资联营公司",
            "投资活动现金净额", "新增银行贷款", "偿还银行贷款", "已付利息",
            "租赁付款", "购回股份", "配售股份所得净额", "发行股份所得净额",
            "已付股东股息", "融资活动现金净额", "现金净变动", "期初现金", "汇率影响",
            "期末现金"]
ORDERS = {"IS": IS_ORDER, "BS": BS_ORDER, "CF": CF_ORDER}


def key_of(kind, label, sec):
    return f"{sec}|{label}" if kind == "BS" else label


def collect(kind):
    """→ (data{科目:{年:值}}, xcheck[...], missed{标签:次数}, restate_years[...])"""
    data = defaultdict(dict)
    seen = defaultdict(lambda: defaultdict(list))   # 科目→年→[(来源, 值)]
    missed = defaultdict(int)
    restate_years = []
    # home = 该源「有权作为主值」的年份集合。招股书管 2005-2007，各年年报只管自己那年。
    srcs = ([(pc.PROSPECTUS, set(pc.PRE_IPO))]
            + [(f"特步国际-{y}", {y}) for y in pc.AR_YEARS])
    for src, home in srcs:
        got = pc.statement(src, kind)
        if not got:
            print(f"🔴 {src} 未定位到 {kind}")
            continue
        anchors, rows, restated = got
        if restated:
            restate_years.append((src, len(restated)))
        for label, vals, sec in rows:
            canon = resolve(kind, label, sec)
            if not canon:
                missed[key_of(kind, label, sec)] += 1
                continue
            for (yr, _), v in zip(anchors, vals):
                if v is None or yr not in YEARS:
                    continue
                val = v if canon in NO_SCALE else v / SCALE
                seen[canon][yr].append((src, yr in home, val))
    # 🔴 主值**只取当年年报的当年列**（招股书管 2005-2007），不拿别年年报的比较列兜底。
    #    理由：比较列可能是**重述后**口径 —— 特步 FY2024 把 FY2023 重述成「持续经营」
    #    口径（营收 143.46 亿 → 127.43 亿，差 16.03 亿 = KP Global）。拿它兜底会把
    #    as-reported 序列和 restated 序列缝在一起，勾稽照样能平、却是两套口径的嵌合体。
    #    比较列一律降级为**跨年交叉核**证据。
    xcheck = []
    for canon, byyear in seen.items():
        for yr, recs in byyear.items():
            prim = [r for r in recs if r[1]]
            if not prim:
                continue
            chosen = prim[0]
            data[canon][yr] = chosen[2]
            for src, is_home, v in recs:
                if not is_home and abs(v - chosen[2]) > max(0.05, abs(chosen[2]) * 0.005):
                    xcheck.append((kind, canon, yr, chosen[2], v, src))
    return data, xcheck, missed, restate_years


# ───────────────────────── 勾稽校验 ─────────────────────────


def near(a, b, tol=0.6):
    return a is not None and b is not None and abs(a - b) <= tol


def check(IS, BS, CF):
    """每年逐条验；返回 [(年, 条目, 说明)] 失败列表。"""
    bad = []
    for y in YEARS:
        g = lambda d, k: d.get(k, {}).get(y)  # noqa: E731
        # 损益：营业额 − |销售成本| = 毛利
        rev, cos, gp = g(IS, "营业额"), g(IS, "销售成本"), g(IS, "毛利")
        if None not in (rev, cos, gp) and not near(rev - abs(cos), gp):
            bad.append((y, "损益·毛利", f"{rev}−|{cos}|≠{gp}"))
        # 损益：除税前 + 税项 = 持续经营溢利（无拆分年则 = 年内溢利）
        pbt, tax = g(IS, "除税前溢利"), g(IS, "税项")
        tgt = g(IS, "持续经营业务溢利") or g(IS, "年内溢利")
        if None not in (pbt, tax, tgt) and not near(pbt + tax, tgt):
            bad.append((y, "损益·净利", f"{pbt}+{tax}≠{tgt}"))
        # 损益：持续 + 非持续 = 年内溢利
        con, dis, pfy = (g(IS, "持续经营业务溢利"), g(IS, "非持续经营业务损益"),
                         g(IS, "年内溢利"))
        if None not in (con, dis, pfy) and not near(con + dis, pfy):
            bad.append((y, "损益·终止经营", f"{con}+{dis}≠{pfy}"))
        # 资产负债：非流动 + 流动 − 流动负债 − 非流动负债 = 资产净值
        nca, ca = g(BS, "非流动资产合计"), g(BS, "流动资产合计")
        cl, ncl, na = g(BS, "流动负债合计"), g(BS, "非流动负债合计"), g(BS, "资产净值")
        if None not in (nca, ca, cl, ncl, na) and not near(nca + ca - cl - ncl, na):
            bad.append((y, "资产负债·净资产", f"{nca}+{ca}−{cl}−{ncl}≠{na}"))
        # 资产负债：权益构成合计 = 权益总值
        eq = g(BS, "权益总值")
        if eq is not None:
            parts = [g(BS, k) for k in ("股本", "库存股", "可换股债券权益部分",
                                        "储备", "非控股权益")]
            s = sum(p for p in parts if p is not None)
            if not near(s, eq, max(0.6, abs(eq) * 0.001)):
                bad.append((y, "资产负债·权益", f"Σ{s:.1f}≠{eq}"))
        if None not in (na, eq) and not near(na, eq):
            bad.append((y, "资产负债·净资产=权益", f"{na}≠{eq}"))
        # 现金流：经营 + 投资 + 融资 = 现金净变动
        o, i, f = (g(CF, "经营活动现金净额"), g(CF, "投资活动现金净额"),
                   g(CF, "融资活动现金净额"))
        nc = g(CF, "现金净变动")
        if None not in (o, i, f, nc) and not near(o + i + f, nc):
            bad.append((y, "现金流·净变动", f"{o}+{i}+{f}≠{nc}"))
        # 现金流：期初 + 净变动 + 汇率 = 期末
        b, fx, e = g(CF, "期初现金"), g(CF, "汇率影响"), g(CF, "期末现金")
        if None not in (b, nc, e):
            if not near(b + nc + (fx or 0), e):
                bad.append((y, "现金流·期末", f"{b}+{nc}+{fx or 0}≠{e}"))
    return bad


# ───────────────────────── 写出 ─────────────────────────

HEAD = {
    "IS": "利润表", "BS": "资产负债表", "CF": "现金流量表",
}


def write_csv(kind, data):
    path = os.path.join(HERE, f"{HEAD[kind]}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        f.write(f"# {HEAD[kind]}（特步国际 01368.HK）· 单位：人民币百万元"
                f"（每股盈利为人民币分）；负数=流出/减项；空=该期财报无此科目\n")
        f.write("# 来源：report/特步国际/ 招股说明书(2005-2007) + 各年年报(2008-2025)"
                " 逐行解析；本年年报本年列为准，上年比较列作跨年交叉核\n")
        w.writerow(["科目"] + [str(y) for y in YEARS])
        for k in ORDERS[kind]:
            if k not in data:
                continue
            row = [k]
            for y in YEARS:
                v = data[k].get(y)
                row.append("" if v is None else
                           (f"{v:.4f}".rstrip("0").rstrip(".") if k in NO_SCALE
                            else f"{v:.3f}".rstrip("0").rstrip(".")))
            w.writerow(row)
    return path


# ───────────────────────── 派生比率 ─────────────────────────


def ser(data, key):
    """某科目按 YEARS 顺序取成序列（缺年为 None）。"""
    d = data.get(key, {})
    return [d.get(y) for y in YEARS]


def add(*seqs):
    out = []
    for i in range(len(YEARS)):
        vals = [s[i] for s in seqs if s[i] is not None]
        out.append(sum(vals) if vals else None)
    return out


def sub(a, b):
    return [None if a[i] is None else a[i] - (b[i] or 0) for i in range(len(YEARS))]


def div(a, b):
    return [None if (a[i] is None or not b[i]) else a[i] / b[i]
            for i in range(len(YEARS))]


def _running(a):
    """逐年累计（None 当 0 累加，但首个非空之前保持 None —— 上市前没有这回事）。"""
    out, tot, started = [], 0.0, False
    for v in a:
        if v is not None:
            tot += v
            started = True
        out.append(tot if started else None)
    return out


def build_ratios(IS, BS, CF):
    """通用底(scripts/derived.py) + 特步定制层 → 财务比率.csv。

    把特步的港股科目名**映射**成 derived.py 别名层已识别的通用名再调用 ——
    适配放在自己这一侧，不动被多家共用的公共引擎（沿用 finance/安踏体育 的做法）。
    """
    sys.path.insert(0, os.path.join(pc.ROOT, "scripts"))
    import derived

    # 归母：2011 年前与 2024 年起财报**不印**「应占」拆分行（这两段非控股权益为零：
    # FY2025 五年摘要自陈 2024/2025 非控股权益为「—」）。故缺行时用「年内溢利 − 非控股
    # 权益应占溢利」补全，而不是留空 —— 留空会让 ROE / 归母占比整段断线。
    parent = ser(IS, "股东应占溢利")
    npr = ser(IS, "年内溢利")
    nci = ser(IS, "非控股权益应占溢利")
    parent = [parent[i] if parent[i] is not None else
              (None if npr[i] is None else npr[i] - (nci[i] or 0))
              for i in range(len(YEARS))]

    ar = add(ser(BS, "应收贸易账款"), ser(BS, "应收票据"),
             ser(BS, "应收贸易账款及票据"))
    ap = add(ser(BS, "应付贸易账款"), ser(BS, "应付票据"),
             ser(BS, "应付贸易账款及票据"))
    ta = add(ser(BS, "非流动资产合计"), ser(BS, "流动资产合计"))  # 特步 BS 不印「资产总值」
    eq = ser(BS, "权益总值")
    parent_eq = sub(eq, ser(BS, "非控股权益"))
    capex = add(ser(CF, "购建物业厂房设备"), ser(CF, "购买无形资产"))

    PL = {
        "营业收入": ser(IS, "营业额"), "营业成本": ser(IS, "销售成本"),
        "毛利": ser(IS, "毛利"), "销售费用": ser(IS, "销售及分销开支"),
        "管理费用": ser(IS, "行政开支"), "净利润": npr, "归母净利润": parent,
        "利润总额": ser(IS, "除税前溢利"), "所得税费用": ser(IS, "税项"),
    }
    BS_ = {
        "应收账款": ar, "存货": ser(BS, "存货"), "应付账款": ap,
        "固定资产": ser(BS, "物业厂房及设备"), "资产总计": ta,
        "非流动资产合计": ser(BS, "非流动资产合计"),
        "流动资产合计": ser(BS, "流动资产合计"),
        "权益总额": eq, "归母权益": parent_eq,
        "预付款项": ser(BS, "预付款项按金及其他应收款项"),
        "现金及现金等价物": ser(BS, "现金及现金等价物"),
        "定期存款-流动": ser(BS, "定期存款-流动"),
        "定期存款-非流动": ser(BS, "定期存款-非流动"),
        "质押存款-流动": ser(BS, "已抵押存款-流动"),
        "质押存款-非流动": ser(BS, "已抵押存款-非流动"),
        "结构性存款": add(ser(BS, "结构性存款-流动"), ser(BS, "结构性存款-非流动")),
        "FVTPL金融资产": add(ser(BS, "FVTPL金融资产-流动"),
                           ser(BS, "FVTPL金融资产-非流动")),
    }
    CF_ = {
        "经营活动现金流量净额": ser(CF, "经营活动现金净额"),
        "购建固定资产": capex, "已付股息": ser(CF, "已付股东股息"),
    }
    common, unmatched = derived.compute_common_ratios(PL, BS_, CF_)
    rows = [(n, v) for n, v, _ in common]

    # ── 特步定制层 ──
    rev = PL["营业收入"]
    # 有息负债：银行借贷 + **两只可换股债券**（漏掉 CB 会低估杠杆，特步 CB 余额可达十亿级）
    borrow = add(ser(BS, "计息银行借贷-流动"), ser(BS, "计息银行借贷-非流动"),
                 ser(BS, "可换股债券-特步-流动"), ser(BS, "可换股债券-特步-非流动"),
                 ser(BS, "可换股债券-KSwiss-流动"), ser(BS, "可换股债券-KSwiss-非流动"))
    cashlike = add(BS_["现金及现金等价物"], BS_["定期存款-流动"], BS_["定期存款-非流动"],
                   BS_["质押存款-流动"], BS_["质押存款-非流动"],
                   BS_["结构性存款"], BS_["FVTPL金融资产"])
    netcash = [None if (cashlike[i] is None and borrow[i] is None)
               else (cashlike[i] or 0) - (borrow[i] or 0) for i in range(len(YEARS))]
    assoc = ser(IS, "分占联营公司损益")
    pbt = ser(IS, "除税前溢利")
    wc = add(ar, ser(BS, "存货"))

    # 股东回报画像：**累计**已付股息 vs **累计**股权融资净额（发行+配售−回购）。
    # 单年分红率答不了「上市以来公司到底给了股东多少、又从股东那里拿了多少」，
    # 而这正是判「给股东 / 套现 / 混合」的算术依据，故做成逐年累计的跑动值。
    div_paid = [None if v is None else -v for v in ser(CF, "已付股东股息")]
    eq_raise = add(ser(CF, "发行股份所得净额"), ser(CF, "配售股份所得净额"),
                   ser(CF, "购回股份"))
    cum_div = _running(div_paid)
    cum_eq = _running(eq_raise)

    rows += [
        ("经营溢利率 Operating margin", div(ser(IS, "经营溢利"), rev)),
        ("有息负债(含可换股债券)/总资产 Debt/TA", div(borrow, ta)),
        ("净现金 Net cash(百万元)", netcash),
        ("净现金/总资产 Net cash/TA", div(netcash, ta)),
        # 硬规则 5 监控读数：权益法联营收益占除税前溢利。占比抬升即触发「同量级检验」
        ("分占联营损益/除税前溢利 Assoc/PBT", div(assoc, pbt)),
        ("(应收+票据+存货)/营收 Working capital/Revenue", div(wc, rev)),
        ("持续经营业务溢利率 Continuing op margin",
         div(ser(IS, "持续经营业务溢利"), rev)),
        ("累计已付股息 Cumulative dividends paid(百万元)", cum_div),
        ("累计股权融资净额 Cumulative equity raised, net(百万元)", cum_eq),
        ("累计分红/累计股权融资 Dividends/Equity raised", div(cum_div, cum_eq)),
    ]
    rows = [(n, v) for n, v in rows if any(x is not None for x in v)]

    path = os.path.join(HERE, "财务比率.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["# 财务比率（特步国际 01368.HK）· 派生自本目录三表，非财报直接披露"])
        w.writerow(["# 通用底 = scripts/derived.py compute_common_ratios()；其余为特步定制层"])
        w.writerow(["# 比率为小数（0.44 = 44%）；天数为天；标(百万元)者为金额"])
        w.writerow(["# ⚠️ 总资产：特步资产负债表不印「资产总值」行，此处 = 非流动资产合计 + 流动资产合计"])
        w.writerow(["# ⚠️ 归母：2011 年前与 2024 年起财报不印「应占」拆分行（该两段非控股权益为零），"
                    "已用「年内溢利 − 非控股权益应占溢利」补全"])
        w.writerow(["# ⚠️ 2024/2025 营收与利润为**持续经营**口径（KP Global 已终止经营），"
                    "与 2023 及以前的 as-reported 口径不可直接比 —— 见 README 口径断点表"])
        w.writerow(["# ⚠️ 分红率分母用「已付股东股息」(现金流量表·年内实付)，与「宣派」口径有跨年时间差"])
        w.writerow(["指标"] + [str(y) for y in YEARS])
        for name, vals in rows:
            w.writerow([name] + ["" if v is None else
                                 f"{v:.4f}".rstrip("0").rstrip(".") for v in vals])
    print(f"写出 {path}（{len(rows)} 指标 × {len(YEARS)} 年）")
    if unmatched:
        print(f"  ⚠️ derived 未匹配科目：{sorted(set(unmatched))}")


def main():
    args = set(sys.argv[1:])
    out = {}
    allx, allmiss, restates = [], defaultdict(int), []
    for kind in ("IS", "BS", "CF"):
        d, x, miss, rs = collect(kind)
        out[kind] = d
        allx += x
        restates += [(kind,) + r for r in rs]
        for k, v in miss.items():
            allmiss[f"{kind}|{k}"] += v

    if "--miss" in args:
        for k, v in sorted(allmiss.items(), key=lambda kv: -kv[1])[:80]:
            print(f"{v:3d}  {k}")
        return

    bad = check(out["IS"], out["BS"], out["CF"])
    print(f"勾稽校验：{'✅ 全部通过' if not bad else f'🔴 {len(bad)} 条不平'}")
    for y, item, msg in bad:
        print(f"  🔴 {y} {item}: {msg}")
    print(f"跨年交叉核：{len(allx)} 处本年报本年列 vs 次年报比较列不一致")
    for rec in allx[:40]:
        print(f"  ⚠️ {rec[0]} {rec[1]} {rec[2]}: 主={rec[3]} vs {rec[5]}={rec[4]}")
    if restates:
        print(f"重述标记：{restates}")

    if bad:
        print("🔴 校验不过 —— 不写出 CSV（先回查 PDF）")
        return 1
    if "--check" in args:
        print("（--check 模式，未写文件）")
        return 0
    for kind in ("IS", "BS", "CF"):
        print("写出", write_csv(kind, out[kind]))
    build_ratios(out["IS"], out["BS"], out["CF"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
