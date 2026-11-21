#!/usr/bin/env python3
"""关联交易构建器 → 关联交易.csv（20-F Note「Related Party Transactions」）

为什么建：`分析.md` 5.1/5.2 一直写「腾讯是服务供应商、上海付费通是关联支付通道，金额与定价须每年盯」，
却没有一个数字落点。本表把 FY2025 20-F 附注 16 的金额正则抽出来，并与资产负债表闭合。

真源：report/拼多多/2025.htm（FY2025 20-F）附注 16，正则抽原句数字，不手抄。
  (b) 交易额：接受腾讯集团 / 付费通集团的服务（2023–2025）、向付费通提供服务（2023–2025）
  (c) 余额：应收腾讯（附注自陈主要是腾讯运营的在线支付平台在途款）/ 应收宁波和信（附注自陈为借款，
      宁波和信由公司一名高管控制）/ 应收付费通；应付腾讯 / 应付付费通（2024–2025 年末）

校验（不过不写出）：
  P 每个金额句式必须命中
  B 余额闭合：三家应收之和 = `资产负债表.csv` 应收关联方款；两家应付之和 = 应付关联方款（2024、2025 两年）

运行：只依赖 lxml。`python3 _build_related.py [20-F 路径] [输出CSV]`，两个可选参数只供变异对照。
"""
from __future__ import annotations

import csv
import os
import re
import sys

import lxml.html

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(
    os.path.join(HERE, "..", "..", "..", "report", "拼多多", "2025.htm"))
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "关联交易.csv")

N = r"\s*(\d[\d,]*|—|-)"  # 千元；"—" 记 0


def num(s):
    return 0.0 if s in ("—", "-") else float(s.replace(",", ""))


PAT = {
    # 交易额三年 + 美元一列："Services received from: Tencent Group 7,182,496 6,772,163 6,476,166 926,079 Fufeitong Group ..."
    "svc_recv": re.compile(r"Services received from:\s*Tencent Group" + N * 4 + r"\s*Fufeitong Group" + N * 4),
    "svc_prov": re.compile(r"Services provided to:\s*Fufeitong Group" + N * 4),
    # 余额两年 + 美元一列
    "due_from": re.compile(r"Amounts due from related parties:\s*Current:\s*Tencent Group\*" + N * 3
                           + r"\s*Ningbo Hexin Equity Investment Partnership \*\*" + N * 3
                           + r"\s*Fufeitong Group\*\*\*" + N * 3),
    "due_to": re.compile(r"Amounts due to related parties:\s*Current:\s*Tencent Group" + N * 3
                         + r"\s*Fufeitong Group" + N * 3),
}


def annual(prefix):
    with open(os.path.join(HERE, "资产负债表.csv"), encoding="utf-8") as fh:
        rows = list(csv.reader(ln for ln in fh if not ln.startswith("#")))
    hdr = rows[0]
    for r in rows[1:]:
        if r and r[0].startswith(prefix):
            return {y: (float(v) if v.strip() else None) for y, v in zip(hdr[1:], r[1:])}
    raise KeyError(f"资产负债表.csv 探针「{prefix}」未找到")


def main():
    doc = lxml.html.fromstring(open(SRC, "rb").read())
    for bad in doc.xpath("//script|//style"):
        bad.drop_tree()
    text = " ".join(doc.text_content().replace("​", " ").split())

    fails, n, m = [], 0, {}
    for k, p in PAT.items():
        n += 1
        hit = p.search(text)
        if not hit:
            fails.append(f"P 未命中句式 {k}")
            continue
        m[k] = [num(g) for g in hit.groups()]
    if fails:
        for x in fails:
            print("  ❌", x)
        print("🛑 不写出 关联交易.csv")
        return 1

    sr, sp, df, dt = m["svc_recv"], m["svc_prov"], m["due_from"], m["due_to"]
    tencent_svc = dict(zip(["2023", "2024", "2025"], sr[0:3]))
    fft_svc = dict(zip(["2023", "2024", "2025"], sr[4:7]))
    fft_prov = dict(zip(["2023", "2024", "2025"], sp[0:3]))
    due_from = {"腾讯": dict(zip(["2024", "2025"], df[0:2])),
                "宁波和信": dict(zip(["2024", "2025"], df[3:5])),
                "付费通": dict(zip(["2024", "2025"], df[6:8]))}
    due_to = {"腾讯": dict(zip(["2024", "2025"], dt[0:2])),
              "付费通": dict(zip(["2024", "2025"], dt[3:5]))}

    bs_from, bs_to = annual("应收关联方款"), annual("应付关联方款")
    for y in ("2024", "2025"):
        n += 2
        s_from = sum(v[y] for v in due_from.values())
        s_to = sum(v[y] for v in due_to.values())
        # 容差 0：同一份 20-F 里的千元整数应分文不差（容差 1 会放过「差 1」的抄录错，变异实测）
        if s_from != bs_from[y]:
            fails.append(f"B {y} 应收三家和 {s_from:,.0f} ≠ 资产负债表 {bs_from[y]:,.0f}")
        if s_to != bs_to[y]:
            fails.append(f"B {y} 应付两家和 {s_to:,.0f} ≠ 资产负债表 {bs_to[y]:,.0f}")

    print(f"校验 {n} 式，未通过 {len(fails)} 式")
    for x in fails:
        print("  ❌", x)
    if fails:
        print("🛑 不写出 关联交易.csv")
        return 1

    ni = {}
    with open(os.path.join(HERE, "利润表.csv"), encoding="utf-8") as fh:
        rows = list(csv.reader(ln for ln in fh if not ln.startswith("#")))
    hdr = rows[0]
    for r in rows[1:]:
        if r and r[0].startswith("净利润"):
            ni = {y: float(v) for y, v in zip(hdr[1:], r[1:]) if v.strip()}
            break

    yrs = ["2023", "2024", "2025"]
    fmt = lambda v: "" if v is None else f"{v:.0f}"
    out = [
        "# 单位:千元人民币;来源:FY2025 20-F 附注 16「Related Party Transactions」正则抽取(report/拼多多/2025.htm);生成器 _build_related.py",
        "# 关联方(附注原文):腾讯集团=公司股东;宁波和信=由公司一名高管控制的合伙企业;上海付费通及其子公司(付费通集团)=宁波和信持股 93.84%",
        "# 余额已与 资产负债表.csv 闭合:三家应收之和=应收关联方款、两家应付之和=应付关联方款(2024、2025)",
    ]
    rows_out = [
        ["指标"] + yrs,
        ["接受腾讯集团服务"] + [fmt(tencent_svc[y]) for y in yrs],
        ["接受付费通集团服务"] + [fmt(fft_svc[y]) for y in yrs],
        ["向付费通集团提供服务"] + [fmt(fft_prov[y]) for y in yrs],
        ["派生:接受腾讯服务÷净利(%)"] + [f"{tencent_svc[y] / ni[y] * 100:.2f}" for y in yrs],
        ["派生:接受付费通服务÷净利(%)"] + [f"{fft_svc[y] / ni[y] * 100:.2f}" for y in yrs],
        ["应收腾讯集团(附注:主要为腾讯运营的在线支付平台在途款)", ""] + [fmt(due_from["腾讯"][y]) for y in ("2024", "2025")],
        ["应收宁波和信(附注:对该合伙企业的借款)", ""] + [fmt(due_from["宁波和信"][y]) for y in ("2024", "2025")],
        ["应收付费通集团", ""] + [fmt(due_from["付费通"][y]) for y in ("2024", "2025")],
        ["应付腾讯集团", ""] + [fmt(due_to["腾讯"][y]) for y in ("2024", "2025")],
        ["应付付费通集团", ""] + [fmt(due_to["付费通"][y]) for y in ("2024", "2025")],
    ]
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        for ln in out:
            fh.write(ln + "\n")
        csv.writer(fh).writerows(rows_out)
    print("✅ 关联交易.csv 已写出")
    for r in rows_out[1:]:
        print("   ", r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
