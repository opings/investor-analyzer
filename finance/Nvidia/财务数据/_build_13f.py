#!/usr/bin/env python3
"""NVIDIA 自己报的 13F-HR（美股 13(f) 证券持仓）→ `上市权益持仓-13F.csv`；闸不过不写出。

为什么要这张表：10-Q / 8-K 只给「上市权益证券」合计数（中期财务 CSV），不逐家披露；13F 是公司自己向 SEC 报的逐只持仓
（发行人 / CUSIP / 股数 / 季末市值），可看出生态投资里哪些已经上市、仓位在增还是在减。
口径（取数当场声明）：
- **时点** = 日历季末（06-30 / 09-30），**不是**财季末（07-26 / 10-25）——与 10-Q 的上市权益证券余额不可直接相减；
- **范围** = SEC 13(f) 清单内的证券（美股上市普通股 / ADR 等），**不含**未注册认股权证、可转换优先股、可转债、非上市股权；
- **市值** = 申报原值（美元·2023 起按美元报），本表换算百万美元保留一位小数；股数 = sshPrnamt（SH）。
闸：每份申报 逐只市值和 = 汇总页 tableValueTotal（美元·容差 0）、只数 = tableEntryTotal、非修正申报（isAmendment=false）、
报告期 = 文件名时点；两季同一 CUSIP 的发行人名一致。
"""
import csv
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "report", "Nvidia")
FILES = [("2026-06-30", "13F-HR-20260630.txt", "06-30-2026"), ("2026-09-30", "13F-HR-20260930.txt", "09-30-2026")]
NS = "{http://www.sec.gov/edgar/document/thirteenf/informationtable}"
CN = {"COHERENT CORP": "Coherent(光通信器件)", "COREWEAVE INC": "CoreWeave(AI 云)", "GENERATE BIOMEDICINES INC": "Generate Biomedicines(AI 制药)",
      "INTEL CORP": "Intel", "NEBIUS GROUP N.V.": "Nebius(AI 云)", "NOKIA CORP": "Nokia(ADR)",
      "SPACE EXPLORATION TECHN CORP": "SpaceX(A 类普通股)", "SYNOPSYS INC": "Synopsys(EDA)"}


def parse(fn, period):
    s = open(os.path.join(REPORT, fn), encoding="utf-8").read()
    bad = []
    tag = lambda t: (re.search(rf"<{t}>([^<]+)</{t}>", s) or [None, None])[1]
    if tag("periodOfReport") != period:
        bad.append((fn, "报告期", tag("periodOfReport")))
    if tag("isAmendment") != "false":
        bad.append((fn, "非修正申报", tag("isAmendment")))
    n_tot, v_tot = int(tag("tableEntryTotal")), int(tag("tableValueTotal"))
    m = re.search(r"(<informationTable\b.*?</informationTable>)", s, flags=re.S)
    root = ET.fromstring(m.group(1))
    rows = []
    for it in root.findall(f"{NS}infoTable"):
        g = lambda p: it.findtext(f"{NS}{p}")
        if it.findtext(f"{NS}shrsOrPrnAmt/{NS}sshPrnamtType") != "SH" or g("putCall"):
            bad.append((fn, "非普通股数 / 含期权行", g("nameOfIssuer")))
        rows.append({"issuer": g("nameOfIssuer"), "class": g("titleOfClass"), "cusip": g("cusip"), "value": int(g("value")),
                     "shares": int(it.findtext(f"{NS}shrsOrPrnAmt/{NS}sshPrnamt"))})
    if len(rows) != n_tot or sum(r["value"] for r in rows) != v_tot:
        bad.append((fn, "逐只和 = 汇总页", (len(rows), n_tot, sum(r["value"] for r in rows), v_tot)))
    return rows, v_tot, bad


def main():
    data, bad, totals = {}, [], {}
    for col, fn, period in FILES:
        rows, vt, b = parse(fn, period)
        bad += b
        totals[col] = vt
        for r in rows:
            key = r["cusip"]
            if key in data and data[key]["issuer"] != r["issuer"]:
                bad.append(("CUSIP 发行人名不一致", key))
            data.setdefault(key, {"issuer": r["issuer"], "class": r["class"]})[col] = (r["value"], r["shares"])
    if any(r["issuer"] not in CN for r in data.values()):
        bad.append(("新发行人缺中文名(补 CN 映射)", [r["issuer"] for r in data.values() if r["issuer"] not in CN]))
    if bad:
        print(f"❌ 13F 闸不通过 {len(bad)} 条（不写出）：")
        for b in bad:
            print("   ", b)
        return 1
    cols = [c for c, _, _ in FILES]
    with open(os.path.join(HERE, "上市权益持仓-13F.csv"), "w", newline="") as f:
        f.write("# 单位: 市值 百万美元(一位小数·申报原值为美元) / 股数 股 | 来源: NVIDIA 自报 13F-HR(report/Nvidia/13F-HR-*.txt) | "
                "时点 = 日历季末(非财季末·与 10-Q 上市权益证券余额不可直接相减) | 范围 = SEC 13(f) 清单证券(不含认股权证 / 可转换优先股 / "
                "可转债 / 非上市股权) | 闸: 逐只市值和 = 汇总页 tableValueTotal(容差 0)·只数 = tableEntryTotal·非修正申报 | "
                "「派生·股数变化」= 后季 − 前季(正 = 增持)\n")
        w = csv.writer(f)
        w.writerow(["发行人", "证券类别", "CUSIP"] + [f"{c} 市值" for c in cols] + [f"{c} 股数" for c in cols] + ["派生·股数变化(09-30 − 06-30)"])
        for cusip, r in sorted(data.items(), key=lambda kv: -kv[1].get(cols[-1], (0, 0))[0]):
            vals = [f"{r[c][0] / 1e6:.1f}" if c in r else "" for c in cols]
            shs = [str(r[c][1]) if c in r else "" for c in cols]
            chg = str(r[cols[1]][1] - r[cols[0]][1]) if all(c in r for c in cols) else ""
            w.writerow([CN[r["issuer"]], r["class"], cusip] + vals + shs + [chg])
        w.writerow(["合计(汇总页 tableValueTotal)", "", ""] + [f"{totals[c] / 1e6:.1f}" for c in cols] + ["", "", ""])
    print(f"✅ 写出 上市权益持仓-13F.csv（{len(data)} 只 × {len(cols)} 季；逐只和 = 汇总页）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
