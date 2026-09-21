#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""361度 公司特有经营指标 —— 从年报**附註**解析（正表之外的关键变量）。

为什么这些指标单列：361度 的生意特征全在正表之外
  · **预收款项/合约负债**印在「應付賬款及其他應付款項」附註里，正表看不到。
    它常年只有营收的约 1%，说明本公司**不是先款后货**——与白酒那类蓄水池模型相反，
    渠道议价权判断必须靠它而不是靠资产负债表正表。
  · **应收账款 ECL 拨备 / 逾期结构**印在「財務風險管理」附註里。本公司应收周转
    约 200 天（见 财务比率.csv），这一块是整份报表里最大的风险科目，只看正表净额
    会把「已计提三成拨备的逾期款」当成正常应收。
  · **供应商预付款**印在应收附註 (b) 项，是「垃圾筐科目」排雷的直接入口。

解析后逐项打印，缺失标空（不猜数）。
"""
import csv
import os
import re
import sys

from _parse_core import ensure_text, NUM_RE, tok_value
from _build_from_pdf import PERIODS, OWNER, FILES, assemble

HERE = os.path.dirname(os.path.abspath(__file__))

NUM = r"([\d,]+(?:\.\d+)?)"
# 标签后紧跟的附註编号「（附註15(b)）」——先剥掉，否则它会被当成第一个金额
NOTEREF = re.compile(r"（[^）]*附註[^）]*）|\(\s*附註[^)]*\)|（附註\s*[\d()a-z]+\s*）")


def _f(s):
    return float(s.replace(",", ""))


def cells(line):
    """行内金额按出现顺序 → [float|None]（破折号=该期未披露，占位不塌陷）。

    ⚠️ 必须用内核的 NUM_RE，不能自写「≥4 位或带逗号」的正则：
       那样会把 3 位小额整个滤掉 → **列位左移一格**。实证：过渡期年报
       「預收款項  447  3,049」的本期值 447 被滤掉，结果把上年的 3,049 记成了本期。
    """
    line = NOTEREF.sub(" ", line)
    return [tok_value(m) for m in NUM_RE.finditer(line)]


# ── ① 附註表行：按**标签**定位，取该行第一个金额（= 本期列）──
# 标签与金额之间常夹「（附註15(b)）」这类尾注，故用 `.*?` 不用 `\s+`
LINE_ITEMS = [
    ("预收款项及合约负债", re.compile(r"^\s*(?:預收款項|合約負債)(?:（[^）]*）)?\s*(?:（[^）]*）)?\s")),
    ("应付账款(纯贸易)", re.compile(r"^\s*應付賬款(?:（[^）]*）)?\s")),
    ("应收账款ECL拨备", re.compile(r"^\s*減[：:]\s*(?:預期信貸虧損撥備|呆賬撥備)")),
]

# ── ② MD&A / 附註自陈句：正则直接带出金额（单位随句式）──
SENTENCES = [
    ("供应商预付款", re.compile(rf"供應商預付款項約人民幣\s*{NUM}\s*元"), 1e-6),
    ("已背书终止确认票据", re.compile(rf"背書(?:若干)?銀行承兌票據合共人民幣\s*{NUM}\s*元"), 1e-6),
    ("电商收入", re.compile(rf"電子商務業務.{{0,40}}?(?:收益|收入)"
                        rf".{{0,16}}?人民幣\s*{NUM}\s*百萬元"), 1.0),
]


def extract(name, take=0):
    """take = 本期列在行内金额里的下标（招股书 4 列、年报 2 列，本期均在最左 → 0）。"""
    lines = ensure_text(name)
    out = {}
    for item, pat in LINE_ITEMS:
        for ln in lines:
            if not pat.match(ln):
                continue
            v = cells(ln)
            if len(v) > take:
                out[item] = None if v[take] is None else abs(v[take]) * 0.001  # 附註=千元
                break
    for item, pat, scale in SENTENCES:
        for ln in lines:
            m = pat.search(ln)
            if m:
                out[item] = _f(m.group(1)) * scale
                break
    return out


def main():
    cols = {}
    for name in FILES:
        if name == "361度-招股说明书":
            # 招股书会计师报告 4 列 = FY2006 / FY2007 / FY2008 / 9M2009，逐列取
            for idx, per in enumerate(["FY2006/6", "FY2007/6", "FY2008/6"]):
                cols[per] = extract(name, take=idx)
            continue
        per = next((p for p, o in OWNER.items() if o == name), None)
        if per is None:
            continue
        cols[per] = extract(name)

    # ── 派生：拨备率 = ECL拨备 ÷ (应收账款净额 + ECL拨备)。
    #    年报只在近两年用自陈句给这个比率，自己算可覆盖全序列，且口径写死在这里。
    data, _c, _u = assemble()
    ar_net = data["bs"].get("应收账款", {})
    ar_old = data["bs"].get("应收账款及应收票据-合并口径", {})
    ar_old2 = data["bs"].get("贸易及其他应收款项-合并口径", {})
    for per in PERIODS:
        prov = cols.get(per, {}).get("应收账款ECL拨备")
        net = ar_net.get(per) or ar_old.get(per) or ar_old2.get(per)
        if prov is not None and net:
            cols.setdefault(per, {})["应收账款拨备率(派生)"] = prov / (net + prov)

    order = ([r[0] for r in LINE_ITEMS] + ["应收账款拨备率(派生)"]
             + [s[0] for s in SENTENCES])
    print(f"{'指标':22s}" + "".join(f"{p:>10s}" for p in PERIODS))
    for item in order:
        vals = [cols.get(p, {}).get(item) for p in PERIODS]
        print(f"{item:22s}" + "".join(
            f"{'—' if v is None else format(v, '.1f'):>10s}" for v in vals))

    path = os.path.join(HERE, "经营指标.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write("# 361度 公司特有经营指标 · 单位：人民币百万元（拨备率为小数）；空=该期年报未披露\n")
        f.write("# 来源：各期年报**附註**与 MD&A 自陈句（_build_extras.py 逐条正则抽取）\n")
        f.write("# 🔴「预收款项及合约负债」常年仅约营收 1% —— 本公司**不是先款后货**模式，"
                "不可套用白酒那套「合同负债=蓄水池」的读法\n")
        f.write("# 🔴「已背书终止确认票据」是表外或有负债（全面追索基准），"
                "不在资产负债表内，但发行银行违约时集团仍有结算责任\n")
        w = csv.writer(f)
        w.writerow(["指标"] + PERIODS)
        for item in order:
            vals = [cols.get(p, {}).get(item) for p in PERIODS]
            if all(v is None for v in vals):
                continue
            w.writerow([item] + ["" if v is None else f"{v:.4f}".rstrip("0").rstrip(".")
                                 for v in vals])
    print(f"\n✅ 经营指标.csv 已写出")


if __name__ == "__main__":
    main()
