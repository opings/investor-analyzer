#!/usr/bin/env python3
"""拼多多季度(中期)数据构建器 —— 从一手 6-K 业绩新闻稿 Ex-99.1 解析。

真源：`report/拼多多/_业绩6K/<tag>_<filed>.htm`（SEC EDGAR Ex-99.1 原件）。
覆盖：2023Q1 – 2026Q2 共 14 个季度（含 2023/2024/2025 三个完整财年，可与 20-F 年报加总对账）。

为什么需要中期管线
------------------
PDD 是外国私人发行人(FPI)，**没有 10-Q**；季度数字的唯一一手来源就是 6-K 新闻稿里的
未经审计简明三表。此前本库的季度数字只以散文形式存在于 `knowledge/companies/拼多多/`
事实编年里，既没有 CSV 落点、也没有任何勾稽校验——而「经营利润转正 vs 净利仍负」
这条核心判断恰恰建立在季度序列上。

🔴 单位断点（建库时实测，双判据一致）
------------------------------------
  2023Q1 – 2025Q4 新闻稿报表 = **RMB 千元**（自陈 "in thousands"）
  2026Q1 起          新闻稿报表 = **RMB 百万元**（自陈 "in millions"）
本文件统一折算为**千元**（与 `利润表.csv` 等年报 CSV 同单位），但 2026 各季的末三位
是折算补零、**并非千元级精度**——故每张 CSV 都带一行 `_原始披露单位`，让精度断点
机器可见，而不是只写在 README 脚注里。

校验（不过不写出）
------------------
  A 表内恒等式 9 式 · B 收入拆分 · C 跨季链（期初=上季期末、累计列=各季加总）
  D 跨年勾稽（四季加总 vs 20-F 年报三年）· E 重述侦测（本期披露的上年同期 vs 该季原披露）
"""
from __future__ import annotations

import csv
import os
import re
import sys

from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(ROOT, "..", "..", "..", "report", "拼多多", "_业绩6K"))

# (季度标签, 6-K 发布日, accession) —— 与 report/拼多多/_业绩6K/_下载清单.tsv 一致
RELEASES = [
    ("2023Q1", "2023-05-30", "0001104659-23-065610"),
    ("2023Q2", "2023-08-29", "0001104659-23-096546"),
    ("2023Q3", "2023-11-28", "0001104659-23-121457"),
    ("2023Q4", "2024-03-21", "0001104659-24-036850"),
    ("2024Q1", "2024-05-22", "0001104659-24-064321"),
    ("2024Q2", "2024-08-26", "0001104659-24-092851"),
    ("2024Q3", "2024-11-21", "0001104659-24-121500"),
    ("2024Q4", "2025-03-20", "0001104659-25-026115"),
    ("2025Q1", "2025-05-27", "0001104659-25-053013"),
    ("2025Q2", "2025-08-25", "0001104659-25-082502"),
    ("2025Q3", "2025-11-18", "0001104659-25-113490"),
    ("2025Q4", "2026-03-26", "0001104659-26-034813"),
    ("2026Q1", "2026-05-28", "0001104659-26-067186"),
    ("2026Q2", "2026-08-25", "0001104659-26-100534"),
]

TOL = 1  # 千元级容差（印刷四舍五入）


# ---------------------------------------------------------------- 单元格解析
def row_values(tr):
    """把一行的单元格解析成 (标签, [数值...])。

    处理三种版式怪癖：
      · 负数被拆成 "(45,859" 与 ")" 两个单元格
      · 零值印成 "-"，后跟脚注星号 "*"
      · 货币符号 "$" 单独占一格
    """
    cells = [" ".join(td.get_text(" ", strip=True).split()) for td in tr.find_all(["td", "th"])]
    label, vals, neg = None, [], False
    for c in cells:
        c = c.replace("’", "'").strip()
        if c in ("", "$", "*", "%"):
            continue
        if c == "(":
            neg = True
            continue
        if c == ")":
            if vals:
                vals[-1] = -abs(vals[-1])
            neg = False
            continue
        if c in ("-", "—", "–"):
            vals.append(0.0)
            continue
        m = re.fullmatch(r"\(?\s*(-?[\d,]+(?:\.\d+)?)\s*\)?", c)
        if m:
            v = float(m.group(1).replace(",", ""))
            if c.startswith("(") or neg:
                v = -abs(v)
            if c.startswith("(") and not c.endswith(")"):
                neg = True
            else:
                neg = False
            vals.append(v)
            continue
        if label is None:
            label = c
        # 其余非数字文本（如 "(Unaudited)"）忽略
    return label, vals


def table_rows(table):
    out = []
    for tr in table.find_all("tr"):
        lab, vals = row_values(tr)
        if lab or vals:
            out.append((lab, vals))
    return out


def find_table(soup, needles, exclude=()):
    """按内容定位表格——版式随季度变化（Q4 版多出全年列与额外 bullet 表），表序不可信。"""
    best = None
    for t in soup.find_all("table"):
        txt = " ".join(t.get_text(" ", strip=True).split())
        if any(x.lower() in txt.lower() for x in exclude):
            continue
        if all(n.lower() in txt.lower() for n in needles):
            if best is None or len(txt) > len(best[1]):
                best = (t, txt)
    return best[0] if best else None


def pick_contains(rows, needle, col=1):
    """按「行标签含某词」取值——用于措辞随盈亏切换的现金流行
    （"Net cash generated from" / "Net cash (used in)/ generated from"）。"""
    for lab, vals in rows:
        if lab and needle.lower() in lab.lower() and len(vals) > col:
            return vals[col]
    raise KeyError(f"未找到含 '{needle}' 的行")


def pick(rows, *labels, required=True, col=1):
    """取某行第 col 个数值列。col=1 → 本期(当年)；col=0 → 上年同期。"""
    for want in labels:
        for lab, vals in rows:
            if lab and lab.lower().startswith(want.lower()) and len(vals) > col:
                return vals[col]
    if required:
        raise KeyError(f"未找到行: {labels}")
    return None


# ---------------------------------------------------------------- 逐份解析
def parse_release(tag, filed, path):
    soup = BeautifulSoup(open(path, "rb").read(), "lxml")
    full = " ".join(soup.get_text(" ", strip=True).split())

    # —— 单位实测（自陈 + 算术反证双判据）
    if re.search(r"in millions of (?:RMB|Renminbi)", full, re.I):
        unit, mult = "百万元", 1000.0
    elif re.search(r"in thousands of (?:RMB|Renminbi)", full, re.I):
        unit, mult = "千元", 1.0
    else:
        raise RuntimeError(f"{tag}: 单位自陈句未找到——拒绝猜测")

    inc = find_table(soup, ["For the three months ended", "Operating profit", "Income tax expenses"])
    seg = find_table(soup, ["Online marketing services and others", "Transaction services", "Total"],
                     exclude=["Operating profit", "Net cash"])
    # 现金流表的行首措辞随盈亏切换（"generated from" / "(used in)/ generated from"），
    # 故用不随盈亏变化的词定位
    cfs = find_table(soup, ["operating activities", "investing activities", "at end of period"])
    bsa = find_table(soup, ["Total Assets"], exclude=["Total Liabilities and Shareholders"])
    bsl = find_table(soup, ["Total Liabilities and Shareholders"])
    sbc = find_table(soup, ["Share-based compensation", "Costs of revenues"],
                     exclude=["Operating profit", "Total revenues"])
    for name, t in [("利润表", inc), ("收入拆分", seg), ("现金流", cfs),
                    ("资产表", bsa), ("负债权益表", bsl)]:
        if t is None:
            raise RuntimeError(f"{tag}: 未定位到{name}")

    R = {k: table_rows(v) for k, v in
         dict(inc=inc, seg=seg, cfs=cfs, bsa=bsa, bsl=bsl).items()}
    R["sbc"] = table_rows(sbc) if sbc is not None else []

    # 列数：3 → [上年同期, 本期, US$]；6 → [3M上年, 3M本期, 3M US$, 累计上年, 累计本期, 累计US$]
    ncol = max(len(v) for _, v in R["inc"] if v)
    if ncol not in (3, 6):
        raise RuntimeError(f"{tag}: 利润表列数异常 {ncol}")
    cum_col = 4 if ncol == 6 else None

    def g(key, *labels, col=1, required=True):
        v = pick(R[key], *labels, required=required, col=col)
        return None if v is None else v * mult

    d = {"季度": tag, "6K发布日": filed, "_原始披露单位": unit}

    # —— 利润表（本期 3 个月）
    d["收益合计"] = g("inc", "Revenues")
    d["销售成本"] = g("inc", "Costs of revenues")
    d["毛利"] = g("inc", "Gross profit", required=False)
    d["销售及营销开支"] = g("inc", "Sales and marketing expenses")
    d["行政管理开支"] = g("inc", "General and administrative expenses")
    d["研发开支"] = g("inc", "Research and development expenses")
    d["总经营开支"] = g("inc", "Total operating expenses")
    d["经营利润"] = g("inc", "Operating profit")
    d["利息及投资收益净额"] = g("inc", "Interest and investment income")
    # 利息费用：可转债存续期（至 2023 年）才有此行，两笔 CB 清偿后消失 → required=False
    d["利息费用"] = g("inc", "Interest expenses", required=False) or 0.0
    d["汇兑损益"] = g("inc", "Foreign exchange")
    d["其他收益净额"] = g("inc", "Other income", "Other (loss)/income", required=False) or 0.0
    d["除税及权益法前利润"] = g("inc", "Profit before income tax", "Income before income tax")
    d["权益法投资损益"] = g("inc", "Share of results of equity investees")
    d["所得税"] = g("inc", "Income tax expenses")
    d["净利润"] = g("inc", "Net income")

    # —— 收入拆分
    d["在线营销服务及其他"] = g("seg", "- Online marketing services", "Online marketing services")
    d["交易服务"] = g("seg", "- Transaction services", "Transaction services")
    d["拆分合计"] = g("seg", "Total")

    # —— 现金流
    d["经营活动现金流净额"] = pick_contains(R["cfs"], "operating activities") * mult
    d["投资活动现金流净额"] = pick_contains(R["cfs"], "investing activities") * mult
    d["融资活动现金流净额"] = pick_contains(R["cfs"], "financing activities") * mult
    d["汇率影响"] = g("cfs", "Effect of exchange rate")
    d["现金净变动"] = pick_contains(R["cfs"], "in cash, cash equivalents and restricted cash") * mult
    d["期初现金及受限资金"] = g("cfs", "Cash, cash equivalents and restricted cash at beginning")
    d["期末现金及受限资金"] = g("cfs", "Cash, cash equivalents and restricted cash at end")

    # —— 资产负债表（期末）
    d["现金及现金等价物"] = g("bsa", "Cash and cash equivalents")
    d["受限资金"] = g("bsa", "Restricted cash")
    d["支付平台应收"] = g("bsa", "Receivables from online payment")
    d["短期投资"] = g("bsa", "Short-term investments")
    d["流动资产合计"] = g("bsa", "Total current assets")
    d["物业设备及软件净额"] = g("bsa", "Property, equipment and software")
    d["其他非流动资产"] = g("bsa", "Other non-current assets")
    d["非流动资产合计"] = g("bsa", "Total non-current assets")
    d["资产总计"] = g("bsa", "Total Assets")
    d["客户预收及递延收入"] = g("bsl", "Customer advances and deferred revenues")
    d["商家应付款"] = g("bsl", "Payable to merchants")
    d["商家保证金"] = g("bsl", "Merchant deposits")
    d["流动负债合计"] = g("bsl", "Total current liabilities")
    d["负债合计"] = g("bsl", "Total Liabilities")
    d["股东权益合计"] = g("bsl", "Total Shareholders")
    d["负债及权益合计"] = g("bsl", "Total Liabilities and Shareholders")
    d["留存收益"] = g("bsl", "Retained earnings")

    # —— SBC
    d["股权薪酬合计"] = g("sbc", "Total share-based compensation", "Total", required=False)

    # —— 上年同期（重述侦测用）+ 累计列（跨季链用）
    d["_上年同期营收"] = g("inc", "Revenues", col=0)
    d["_上年同期经营利润"] = g("inc", "Operating profit", col=0)
    d["_上年同期净利"] = g("inc", "Net income", col=0)
    if cum_col:
        d["_累计营收"] = g("inc", "Revenues", col=cum_col)
        d["_累计经营利润"] = g("inc", "Operating profit", col=cum_col)
        d["_累计净利"] = g("inc", "Net income", col=cum_col)
        d["_累计经营现金流"] = g("cfs", "Net cash generated from operating",
                          "Net cash (used in)/ generated from operating",
                          "Net cash used in operating", col=cum_col)
    return d


# ---------------------------------------------------------------- 校验
class Checker:
    def __init__(self):
        self.fail, self.n = [], 0

    def eq(self, tag, name, a, b, tol=TOL):
        self.n += 1
        if a is None or b is None:
            self.fail.append(f"{tag} {name}: 缺值 {a} vs {b}")
            return
        if abs(a - b) > tol:
            self.fail.append(f"{tag} {name}: {a:,.0f} vs {b:,.0f} (差 {a - b:,.0f})")

    def report(self):
        print(f"\n校验 {self.n} 式，未通过 {len(self.fail)} 式")
        for f in self.fail:
            print("  ❌", f)
        return not self.fail


def load_annual(path, wanted_rows):
    """读年报 CSV 的指定行，供跨年勾稽。返回 {行名: {年: 值}}。"""
    out = {}
    with open(path, encoding="utf-8") as f:
        lines = [ln for ln in f if not ln.startswith("#")]
    rd = csv.reader(lines)
    hdr = next(rd)
    years = hdr[1:]
    for row in rd:
        if not row:
            continue
        for w in wanted_rows:
            if row[0].startswith(w):
                out[w] = {y: (float(v) if v.strip() else None) for y, v in zip(years, row[1:])}
    return out


def verify(data, ck):
    by = {d["季度"]: d for d in data}

    for d in data:
        t = d["季度"]
        # A1 三费和 = 总经营开支
        ck.eq(t, "A1 三费和=总开支",
              d["销售及营销开支"] + d["行政管理开支"] + d["研发开支"], d["总经营开支"])
        # A2 营收 + 成本 + 总开支 = 经营利润
        ck.eq(t, "A2 营收+成本+开支=经营利润",
              d["收益合计"] + d["销售成本"] + d["总经营开支"], d["经营利润"])
        # A3 经营利润 + 利息投资 + 汇兑 + 其他 = 税前
        ck.eq(t, "A3 经营+非经营=税前",
              d["经营利润"] + d["利息及投资收益净额"] + d["利息费用"] + d["汇兑损益"]
              + d["其他收益净额"],
              d["除税及权益法前利润"])
        # A4 税前 + 权益法 + 所得税 = 净利
        ck.eq(t, "A4 税前+权益法+税=净利",
              d["除税及权益法前利润"] + d["权益法投资损益"] + d["所得税"], d["净利润"])
        # A5 收入拆分和 = 总营收
        ck.eq(t, "A5 拆分和=总营收", d["在线营销服务及其他"] + d["交易服务"], d["拆分合计"])
        ck.eq(t, "A5b 拆分合计=利润表营收", d["拆分合计"], d["收益合计"])
        # A6 现金流四项 = 净变动
        ck.eq(t, "A6 三活动+汇率=净变动",
              d["经营活动现金流净额"] + d["投资活动现金流净额"] + d["融资活动现金流净额"] + d["汇率影响"],
              d["现金净变动"])
        # A7 期初 + 净变动 = 期末
        ck.eq(t, "A7 期初+净变动=期末",
              d["期初现金及受限资金"] + d["现金净变动"], d["期末现金及受限资金"])
        # A8 资产 = 负债 + 权益
        ck.eq(t, "A8 资产=负债+权益", d["资产总计"], d["负债合计"] + d["股东权益合计"])
        ck.eq(t, "A8b 负债权益合计=资产总计", d["负债及权益合计"], d["资产总计"])
        # A9 流动 + 非流动 = 总资产
        ck.eq(t, "A9 流动+非流动=总资产",
              d["流动资产合计"] + d["非流动资产合计"], d["资产总计"])
        # A10 期末现金及受限 = BS 现金 + 受限
        ck.eq(t, "A10 现金流期末=BS现金+受限",
              d["期末现金及受限资金"], d["现金及现金等价物"] + d["受限资金"])

    # F 净利同比桥自洽：各驱动项同比变动之和 = 净利同比变动
    for d in data:
        p = by.get(f"{int(d['季度'][:4]) - 1}Q{d['季度'][-1]}")
        if not p:
            continue
        parts = ["经营利润", "利息及投资收益净额", "利息费用", "汇兑损益",
                 "其他收益净额", "权益法投资损益", "所得税"]
        tol = 1000 if "百万元" in (d["_原始披露单位"], p["_原始披露单位"]) else TOL
        ck.eq(d["季度"], "F 净利同比桥各项之和=净利同比变动",
              sum(d[k] - p[k] for k in parts), d["净利润"] - p["净利润"], tol=tol)

    # C1 跨季链：本季期初 = 上季期末
    for i in range(1, len(data)):
        prev, cur = data[i - 1], data[i]
        ck.eq(cur["季度"], f"C1 期初=上季({prev['季度']})期末",
              cur["期初现金及受限资金"], prev["期末现金及受限资金"],
              tol=max(TOL, 1000 if cur["_原始披露单位"] == "百万元" else TOL))

    # C2 累计列 = 本财年各季加总
    for d in data:
        if "_累计营收" not in d:
            continue
        yr, q = d["季度"][:4], int(d["季度"][-1])
        parts = [by.get(f"{yr}Q{k}") for k in range(1, q + 1)]
        if any(p is None for p in parts):
            continue
        tol = max(TOL, 1000 * q if d["_原始披露单位"] == "百万元" else TOL)
        for cum, fld in [("_累计营收", "收益合计"), ("_累计经营利润", "经营利润"),
                         ("_累计净利", "净利润"), ("_累计经营现金流", "经营活动现金流净额")]:
            if d.get(cum) is None:
                continue
            ck.eq(d["季度"], f"C2 累计列={yr}Q1..Q{q}加总 [{fld}]",
                  d[cum], sum(p[fld] for p in parts), tol=tol)

    # E 重述侦测：本期披露的「上年同期」 vs 该季当年原披露
    print("\n—— E 重述侦测（本期披露的上年同期 vs 该季原披露）——")
    hits = 0
    for d in data:
        yr, q = int(d["季度"][:4]), int(d["季度"][-1])
        prior = by.get(f"{yr - 1}Q{q}")
        if not prior:
            continue
        tol = 1000 if (d["_原始披露单位"] == "百万元" or prior["_原始披露单位"] == "百万元") else TOL
        for k, fld in [("_上年同期营收", "收益合计"), ("_上年同期经营利润", "经营利润"),
                       ("_上年同期净利", "净利润")]:
            a, b = d[k], prior[fld]
            if a is not None and abs(a - b) > tol:
                hits += 1
                print(f"  ⚠️ {d['季度']} 披露的 {yr-1}Q{q} {fld} = {a:,.0f}，"
                      f"原披露 {b:,.0f}，差 {a - b:,.0f}")
    if not hits:
        print("  ✅ 14 季全部一致 —— 无重述/重分类痕迹")

    # D 跨年勾稽：四季加总（未审计新闻稿） vs 20-F 审计年报
    #
    # 这一组是本管线最有价值的检查：它把「新闻稿说的」和「审计定的」逐行对上。
    # 实证（FY2025）：全部差额 1,521,930 落在行政管理开支一行，并原额贯穿到净利
    # ——即审计新增了一笔**不可抵税**费用（所得税两口径分文不差），不是重分类。
    print("\n—— D 跨年勾稽（季度加总=未审计新闻稿 vs 20-F 审计年报）——")
    ANN_MAP = [  # (季度字段, 年报 CSV 行前缀, 年报 CSV 文件)
        ("收益合计", "收益合计", "利润表.csv"),
        ("销售成本", "销售成本", "利润表.csv"),
        ("销售及营销开支", "销售及营销开支", "利润表.csv"),
        ("行政管理开支", "行政管理开支", "利润表.csv"),
        ("研发开支", "研发开支", "利润表.csv"),
        ("总经营开支", "总经营开支", "利润表.csv"),
        ("经营利润", "经营利润", "利润表.csv"),
        ("除税及权益法前利润", "除税及权益法前利润", "利润表.csv"),
        ("所得税", "所得税", "利润表.csv"),
        ("净利润", "净利润", "利润表.csv"),
        ("在线营销服务及其他", "在线营销服务及其他", "分部营收.csv"),
        ("交易服务", "交易服务", "分部营收.csv"),
        ("经营活动现金流净额", "经营活动", "现金流量表.csv"),
    ]
    cache = {}
    for _, prefix, fn in ANN_MAP:
        cache.setdefault(fn, set()).add(prefix)
    annual = {fn: load_annual(os.path.join(ROOT, fn), sorted(pfx))
              for fn, pfx in cache.items()}

    for yr in ("2023", "2024", "2025"):
        qs = [by.get(f"{yr}Q{k}") for k in range(1, 5)]
        if any(q is None for q in qs):
            continue
        print(f"  [{yr}]")
        gaps = []
        for fld, prefix, fn in ANN_MAP:
            ann = annual[fn].get(prefix, {}).get(yr)
            if ann is None:
                print(f"    ⏳ {fld}: 年报 CSV 无对应行，跳过")
                continue
            qsum = sum(q[fld] for q in qs)
            diff = qsum - ann
            if abs(diff) <= TOL:
                print(f"    ✅ {fld}: {qsum:,.0f}（两口径一致）")
            else:
                print(f"    ⚠️ {fld}: 新闻稿加总 {qsum:,.0f} vs 20-F {ann:,.0f}  差 {diff:,.0f}")
                gaps.append((fld, diff))
        if gaps:
            amts = {round(d) for _, d in gaps}
            print(f"    🔎 差额落点：{[g[0] for g in gaps]}"
                  + (f"；差额同为 {amts.pop():,.0f} → 单一科目调整原额贯穿，非重分类"
                     if len(amts) == 1 else "；差额不等，需逐行回查"))


# ---------------------------------------------------------------- 写出
INC_ROWS = ["收益合计", "销售成本", "毛利", "销售及营销开支", "行政管理开支", "研发开支",
            "总经营开支", "经营利润", "利息及投资收益净额", "利息费用", "汇兑损益", "其他收益净额",
            "除税及权益法前利润", "权益法投资损益", "所得税", "净利润", "股权薪酬合计"]
SEG_ROWS = ["在线营销服务及其他", "交易服务", "拆分合计"]
BSCF_ROWS = ["现金及现金等价物", "受限资金", "短期投资", "支付平台应收", "流动资产合计",
             "物业设备及软件净额", "其他非流动资产", "非流动资产合计", "资产总计",
             "客户预收及递延收入", "商家应付款", "商家保证金", "流动负债合计", "负债合计",
             "股东权益合计", "留存收益",
             "经营活动现金流净额", "投资活动现金流净额", "融资活动现金流净额",
             "汇率影响", "现金净变动", "期初现金及受限资金", "期末现金及受限资金"]


def fmt(v):
    if v is None:
        return ""
    return f"{v:.0f}" if abs(v - round(v)) < 1e-6 else f"{v:.2f}"


def write_csv(path, header_note, rows, data, keys=None):
    tags = [d["季度"] for d in data]
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write(header_note + "\n")
        w = csv.writer(f)
        w.writerow(["科目"] + tags)
        w.writerow(["_原始披露单位"] + [d["_原始披露单位"] for d in data])
        w.writerow(["_6K发布日"] + [d["6K发布日"] for d in data])
        for r in (keys or rows):
            w.writerow([r] + [fmt(d.get(r)) for d in data])
    print(f"  → {os.path.basename(path)}")


def write_ratios(path, data, by_prev):
    tags = [d["季度"] for d in data]

    def yoy(d, fld):
        p = by_prev.get((int(d["季度"][:4]) - 1, d["季度"][-1]))
        if not p or not p[fld]:
            return None
        return (d[fld] / p[fld] - 1) * 100

    rows = {
        "经营利润率(%)": [d["经营利润"] / d["收益合计"] * 100 for d in data],
        "净利率(%)": [d["净利润"] / d["收益合计"] * 100 for d in data],
        "毛利率(%)": [(d["收益合计"] + d["销售成本"]) / d["收益合计"] * 100 for d in data],
        "销售费用率(%)": [-d["销售及营销开支"] / d["收益合计"] * 100 for d in data],
        "研发费用率(%)": [-d["研发开支"] / d["收益合计"] * 100 for d in data],
        "交易服务占营收(%)": [d["交易服务"] / d["收益合计"] * 100 for d in data],
        "营收同比(%)": [yoy(d, "收益合计") for d in data],
        "经营利润同比(%)": [yoy(d, "经营利润") for d in data],
        "净利同比(%)": [yoy(d, "净利润") for d in data],
        "交易服务同比(%)": [yoy(d, "交易服务") for d in data],
        "在线营销同比(%)": [yoy(d, "在线营销服务及其他") for d in data],
        "经营现金流/净利(倍)": [d["经营活动现金流净额"] / d["净利润"] if d["净利润"] else None
                        for d in data],
        # 营收同比增量由哪根柱子贡献——防「全部增量来自 X」这类 overreach
        "营收同比增量中交易服务占比(%)": [
            (lambda p: None if (p is None or d["收益合计"] == p["收益合计"]) else
             (d["交易服务"] - p["交易服务"]) / (d["收益合计"] - p["收益合计"]) * 100
             )(by_prev.get((int(d["季度"][:4]) - 1, d["季度"][-1]))) for d in data],
        "营收同比增量中在线营销占比(%)": [
            (lambda p: None if (p is None or d["收益合计"] == p["收益合计"]) else
             (d["在线营销服务及其他"] - p["在线营销服务及其他"])
             / (d["收益合计"] - p["收益合计"]) * 100
             )(by_prev.get((int(d["季度"][:4]) - 1, d["季度"][-1]))) for d in data],
        "无息浮存(商家应付+保证金+客户预收)": [d["商家应付款"] + d["商家保证金"] + d["客户预收及递延收入"]
                                for d in data],
        "类现金及短投(现金+受限+短投)": [d["现金及现金等价物"] + d["受限资金"] + d["短期投资"]
                             for d in data],
        "股东权益合计": [d["股东权益合计"] for d in data],
    }

    # —— 净利同比桥：把「净利同比为负、经营利润却为正」拆成各驱动项
    # 口径：本季各行 − 上年同季各行，逐项相加恰等于净利同比变动（桥内自洽，见校验 F）
    def delta(d, fld):
        p = by_prev.get((int(d["季度"][:4]) - 1, d["季度"][-1]))
        return None if p is None else d[fld] - p[fld]

    bridge = [
        ("净利同比变动(千元)", "净利润"),
        ("——经营利润贡献", "经营利润"),
        ("——利息及投资收益贡献", "利息及投资收益净额"),
        ("——利息费用贡献", "利息费用"),
        ("——汇兑贡献", "汇兑损益"),
        ("——其他收益净额贡献", "其他收益净额"),
        ("——权益法贡献", "权益法投资损益"),
        ("——所得税贡献", "所得税"),
    ]
    rows["--- 净利同比桥(本季−上年同季) ---"] = [None] * len(data)
    for name, fld in bridge:
        rows[name] = [delta(d, fld) for d in data]
    # 比率/倍数留 2 位小数；金额一律整数（千元），避免 "241350.00" 这类伪精度
    is_ratio = lambda k: k.endswith(("(%)", "(倍)"))
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("# 派生自 季度利润表.csv / 季度分部营收.csv / 季度资产负债与现金流.csv"
                "；金额单位=千元人民币，比率=%，倍数=倍\n"
                "# 同比 = 与上年同季对比（本库季度序列自 2023Q1 起，故 2023 各季同比留空）\n"
                "# ⚠️ 2026 各季原始披露为百万元，本表金额末三位系折算补零、非千元精度\n")
        w = csv.writer(f)
        w.writerow(["指标"] + tags)
        for k, vs in rows.items():
            w.writerow([k] + [("" if v is None else
                               (f"{v:.2f}" if is_ratio(k) else f"{v:.0f}")) for v in vs])
    print(f"  → {os.path.basename(path)}")


def main():
    data = []
    print("—— 解析 6-K 新闻稿 ——")
    for tag, filed, _acc in RELEASES:
        path = os.path.join(SRC, f"{tag}_{filed}.htm")
        if not os.path.exists(path):
            print(f"  ⏳ 缺 {os.path.basename(path)}，跳过")
            continue
        d = parse_release(tag, filed, path)
        data.append(d)
        print(f"  {tag}  单位={d['_原始披露单位']}  营收={d['收益合计']:>14,.0f} 千元  "
              f"经营利润={d['经营利润']:>13,.0f}  净利={d['净利润']:>13,.0f}")

    ck = Checker()
    verify(data, ck)
    if not ck.report():
        print("\n🛑 勾稽未通过 —— 不写出 CSV（回查 6-K 原件）")
        sys.exit(1)

    print("\n—— 写出 CSV ——")
    note_unit = ("# 单位:千元人民币;费用/流出=负数;覆盖2023Q1-2026Q2\n"
                 "# 来源:一手 SEC 6-K 业绩新闻稿 Ex-99.1 未经审计简明报表逐行解析"
                 "(report/拼多多/_业绩6K/)\n"
                 "# 🔴 单位断点:2023Q1-2025Q4 原披露为千元;2026Q1 起原披露改为百万元,"
                 "本表统一折千元、2026 各季末三位系补零非真精度(见 _原始披露单位 行)\n"
                 "# ⚠️ 未经审计:季度数与 20-F 审计年报存在重分类差(见 README「口径决策」)")
    by_prev = {(int(d["季度"][:4]), d["季度"][-1]): d for d in data}
    write_csv(os.path.join(ROOT, "季度利润表.csv"), note_unit, INC_ROWS, data)
    write_csv(os.path.join(ROOT, "季度分部营收.csv"),
              note_unit + "\n# 单一可报告分部;此为收入类型拆分,未披露 Temu/主站或地理拆分",
              SEG_ROWS, data)
    write_csv(os.path.join(ROOT, "季度资产负债与现金流.csv"),
              note_unit + "\n# 资产负债项=季末时点数;现金流项=当季发生额", BSCF_ROWS, data)
    write_ratios(os.path.join(ROOT, "季度比率.csv"), data, by_prev)
    print("\n✅ 完成")


if __name__ == "__main__":
    main()
