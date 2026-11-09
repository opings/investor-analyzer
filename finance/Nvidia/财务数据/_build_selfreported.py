#!/usr/bin/env python3
"""10-K / 10-Q **正文以句子给出**的关键数 → `附注自陈数.csv`（每行带原文锚句，可回溯）。

做法：把申报 HTML 转纯文本，用「锚句正则」定位句子并从句中**解析**数字（不手抄）；任一锚句找不到 → 不写出。
这些数不在三表里、也多不在 XBRL Detail 表里，但对判断生意至关重要（对华出口管制减记、回购授权、Groq 交易、
股权投资与承诺、为 OpenAI 租约提供的担保上限、AI 云伙伴云服务承诺……）。
"""
import csv
import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "report", "Nvidia")

# (科目, 期间/时点, 文件, 锚句正则——第一个捕获组为数, 单位)
ITEMS = [
    ("H20 对华出口许可要求导致的减记(过剩存货与采购义务)", "FY2026 Q1", "2026.htm",
     r"we incurred a \$\s?([\d.]+) billion charge in the first quarter of fiscal year 2026 associated with H20", "B"),
    ("H20 许可(2025-08 获批)项下 H20 收入", "FY2026", "2026.htm", r"We generated approximately \$\s?([\d.]+) million in H20 revenue", "M"),
    ("存货及过剩采购义务计提(含 H20 45 亿)", "FY2026 H1", "2027-Q2.htm",
     r"Provisions for inventory and excess inventory purchase obligations totaled \$\s?[\d.]+ billion and \$\s?([\d.]+) billion for the second quarter and first half of fiscal year 2026", "B"),
    ("H200 相关减记(过剩存货与采购义务)", "FY2027 H1", "2027-Q2.htm",
     r"we incurred a \$\s?([\d.]+) billion charge associated with H200 for excess inventory and purchase obligations", "B"),
    ("H200 对华许可出货入境美国须缴关税(%)", "2026-02 起", "2026.htm",
     r"any H200 shipped under the new licensing program will be subject to a (\d+) ?% tariff upon importation into the United States", "P"),
    ("新增回购授权(2025-08-26 董事会·无到期日)", "2025-08-26", "2026.htm",
     r"On August 26, 2025, our Board of Directors approved an additional \$\s?([\d.]+) billion in share repurchase authorization", "B"),
    ("当年回购金额(成交口径·非现金流量表付款口径)", "FY2026", "2026.htm",
     r"In fiscal year 2026, we repurchased \d+ million shares of our common stock for \$\s?([\d.]+) billion", "B"),
    ("当年回购股数(百万股)", "FY2026", "2026.htm", r"In fiscal year 2026, we repurchased (\d+) million shares of our common stock", "N"),
    ("当年回购金额(成交口径)", "FY2025", "2026.htm",
     r"we repurchased 282 million and 310 million shares of our common stock for \$\s?[\d.]+ billion and \$\s?([\d.]+) billion", "B"),
    ("剩余回购授权", "2026-01-25", "2026.htm",
     r"As of January 25, 2026, we were authorized, subject to certain specifications, to repurchase up to \$\s?([\d.]+) billion", "B"),
    ("剩余回购授权", "2026-07-26", "2027-Q2.htm",
     r"As of July 26, 2026, we were authorized, subject to certain specifications, to repurchase up to \$\s?([\d.]+) billion", "B"),
    ("Groq 交易·确认商誉(可抵税)", "2025-12", "2026.htm", r"We recorded \$\s?([\d.]+) billion of goodwill and a \$\s?[\d.]+ billion developed technology", "B"),
    ("Groq 交易·开发技术无形资产(5 年摊销)", "2025-12", "2026.htm", r"goodwill and a \$\s?([\d.]+) billion developed technology intangible asset", "B"),
    ("Groq 交易·交割时支付对价", "2025-12", "2026.htm", r"Total consideration consists of \$\s?([\d.]+) billion paid at closing", "B"),
    ("Groq 交易·一年内应付对价(含推算利息)", "2025-12", "2026.htm", r"paid at closing and \$\s?([\d.]+) billion, inclusive of imputed interest", "B"),
    ("股权投资余额(公司自陈·生态投资)", "2026-07-26", "2027-Q2.htm",
     r"These include equity investments of \$\s?([\d.]+) billion and equity investment commitments", "B"),
    ("股权投资承诺", "2026-07-26", "2027-Q2.htm", r"equity investment commitments of \$\s?([\d.]+) billion as of July 26, 2026", "B"),
    ("为 OpenAI 关联方 PORTS 园区租约提供担保·义务上限", "2026-08 签署", "2027-Q2.htm",
     r"with our obligation capped at \$\s?([\d.]+) billion in the aggregate", "B"),
    ("AI 云伙伴新模式下的云服务协议承诺(通常 6 年)", "2026-07-26", "2027-Q2.htm",
     r"Our commitments, which are typically six years in duration, totaled \$\s?([\d.]+) billion as of July 26, 2026", "B"),
    ("长期供应协议预付款(营运资本变动主因)", "FY2022", "2022.htm",
     r"Changes in working capital were primarily driven by prepayments of \$\s?([\d.]+) billion for long-term supply agreements", "B"),
    ("总部在美国以外客户的收入占比(%)", "FY2026", "2026.htm",
     r"Revenue from sales to customers headquartered outside of the United States accounted for (\d+) ?%", "P"),
    ("台湾总部客户的数据中心收入中归属美欧终端客户的估计占比(%)", "FY2026", "2026.htm",
     r"we estimate (\d+) ?% of Data Center revenue from Taiwan-headquartered customers was attributed to end customers based in the United States and Europe", "P"),
]
MULT = {"B": 1000.0, "M": 1.0, "N": 1.0, "P": 1.0}


def plain(path):
    s = open(path, encoding="utf-8", errors="ignore").read()
    s = re.sub(r"<ix:header>.*?</ix:header>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s).replace("\xa0", " ").replace("‑", "-")
    s = re.sub(r"\s+", " ", s).replace(" ,", ",").replace(" .", ".")
    return s


def main():
    cache, rows, bad = {}, [], []
    for name, per, fn, pat, u in ITEMS:
        if fn not in cache:
            cache[fn] = plain(os.path.join(REPORT, fn))
        m = re.search(pat, cache[fn])
        if not m:
            bad.append((name, per, fn))
            continue
        v = float(m.group(1).replace(",", "")) * MULT[u]
        lo = cache[fn].rfind(". ", 0, m.start()) + 2
        hi = cache[fn].find(". ", m.end())
        sent = cache[fn][lo:hi + 1].strip()
        rows.append((name, per, v, {"B": "百万美元", "M": "百万美元", "N": "百万股", "P": "%"}[u], fn, sent))
    if bad:
        print(f"❌ 锚句找不到 {len(bad)} 条（不写出）：")
        for b in bad:
            print("   ", b)
        return 1
    with open(os.path.join(HERE, "附注自陈数.csv"), "w", newline="") as f:
        f.write("# 10-K/10-Q 正文以句子给出的关键数(脚本按锚句从原文解析·非手抄) | 源文件在 report/Nvidia/ | 「原文锚句」列为英文原句，"
                "中文释义见「科目」列 | 十亿美元一位小数的原文 → 换算为百万美元\n")
        w = csv.writer(f)
        w.writerow(["科目", "期间/时点", "值", "单位", "来源文件", "原文锚句"])
        for r in rows:
            w.writerow([r[0], r[1], f"{r[2]:g}", r[3], r[4], r[5]])
    print(f"✅ 写出 附注自陈数.csv（{len(rows)} 条，全部锚句命中）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
