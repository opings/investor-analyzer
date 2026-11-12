#!/usr/bin/env python3
"""10-K / 10-Q / 8-K / 公司新闻稿 / 对手方申报 **正文以句子给出**的关键数 → `附注自陈数.csv`（每行带原文锚句，可回溯）。

做法：把申报 HTML 转纯文本，用「锚句正则」定位句子并从句中**解析**数字（不手抄）；任一锚句找不到 → 不写出。
这些数不在三表里、也多不在 XBRL Detail 表里，但对判断生意至关重要（对华出口管制减记、回购授权、Groq 交易、
股权投资与承诺、为 OpenAI 租约提供的担保上限、AI 云伙伴云服务承诺、季末供应承诺、10-Q 之后的 8-K 收购……）。

公司新闻稿一类（nvidianews.nvidia.com）是**没有对应 8-K** 的资本配置与生态投资：2026-09-28 的 1,500 亿美元
回购授权、对 Meta / 联发科 / SB Energy 等的投资、对供应商的产能预留预付款——它们不在 EDGAR 的 8-K 里，
10-Q 也只给合计数、不逐家披露，漏读一手新闻稿就看不到（2026-11-09 补扫时发现，上一版事实编年一条都没收）。
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
    # 10-Q 只以句子给出季度间对比（年报承诺表在 采购与云服务承诺.csv，口径为 10-K 年末）
    ("供应与产能承诺(10-Q 自陈·季末)", "2026-04-26", "2027-Q2.htm",
     r"supply and capacity commitments from \$\s?([\d.]+) billion last quarter to \$\s?[\d.]+ billion as of July 26, 2026", "B"),
    ("供应与产能承诺(10-Q 自陈·季末)", "2026-07-26", "2027-Q2.htm",
     r"supply and capacity commitments from \$\s?[\d.]+ billion last quarter to \$\s?([\d.]+) billion as of July 26, 2026", "B"),
    ("投资承诺合计(须满足或有条件)", "2026-04-26", "2027-Q1.htm",
     r"Investment commitments were \$\s?([\d.]+) billion as of April 26, 2026", "B"),
    ("AI 云伙伴土地·电力·机房担保(最大敞口)", "2026-07-26", "2027-Q2.htm",
     r"Land, power, and shell guarantees for AI clouds \$\s?([\d.]+)", "B"),
    ("担保最大总敞口(含 SB Energy 担保)", "2026-07-26", "2027-Q2.htm",
     r"SB Energy Corp\. guarantees \$?\s?[\d.]+ Total \$\s?([\d.]+)", "B"),
    # 10-Q 之后的期后事件：8-K 原文（Item 8.01）
    ("Hugging Face 收购·向其股东支付的收购价(可调整)", "2026-09-02 签约", "8-K-20260902.htm",
     r"approximately \$\s?([\d.]+) billion purchase price payable to Hugging Face stockholders", "B"),
    ("Hugging Face 收购·加入员工的股权留任计划上限", "2026-09-02 签约", "8-K-20260902.htm",
     r"equity-based retention program of up to approximately \$\s?([\d.]+) billion", "B"),
    # 公司新闻稿（无对应 8-K）：资本配置
    ("新增回购授权(2026-09-28 董事会)", "2026-09-28", "新闻稿-20260928-回购授权.htm",
     r"authorized an additional \$\s?([\d.]+) billion under the company", "B"),
    ("剩余回购授权(含 2026-09-28 新增·公司预计 FY2028 前执行完)", "2026-09-28", "新闻稿-20260928-回购授权.htm",
     r"increasing the total remaining amount authorized to \$\s?([\d.]+) billion", "B"),
    # 公司新闻稿（无对应 8-K）：对部署 NVIDIA 基础设施一方 / 供应链伙伴的投资（10-Q 只给合计，不逐家披露）
    ("CoreWeave A 类普通股投资(每股 87.20 美元)", "2026-01-26 公告", "新闻稿-20260126-CoreWeave.htm",
     r"NVIDIA has invested \$\s?([\d.]+) billion in CoreWeave", "B"),
    ("Nebius 投资", "2026-03-11 公告", "新闻稿-20260311-Nebius.htm",
     r"NVIDIA will invest \$\s?([\d.]+) billion in Nebius", "B"),
    ("IREN 认股权对应投资上限(5 年·3,000 万股·行权价 70 美元)", "2026-05-07 公告", "新闻稿-20260507-IREN.htm",
     r"right to invest up to \$\s?([\d.]+) billion", "B"),
    ("NAVER 计划投资(以 NAVER 落实至少 90 亿美元项目融资为前提)", "2026-07-24 公告", "新闻稿-20260724-NAVER.htm",
     r"NVIDIA plans to invest \$\s?([\d.]+) billion into NAVER", "B"),
    ("SB Energy 股权投资(OpenAI 为园区客户·NVIDIA 另为其租约担保)", "2026-08-17 公告", "新闻稿-20260817-SBEnergy.htm",
     r"NVIDIA will invest \$\s?([\d.]+) billion in SB Energy", "B"),
    ("联发科可转债投资", "2026-08-31 公告", "新闻稿-20260831-MediaTek.htm",
     r"NVIDIA has also invested \$\s?([\d.]+) billion in convertible bonds issued by MediaTek", "B"),
    ("Meta 股票发行·NVIDIA 认购额(公司新闻稿)", "2026-10-26 公告", "新闻稿-20261026-Meta.htm",
     r"NVIDIA will invest \$\s?([\d.]+) billion in Meta", "B"),
    # 对手方申报：Meta 定价招股书（424B5）——NVIDIA 是三家「基石投资者」之一，意向不具约束力
    ("Meta 股票发行·NVIDIA/AMD/博通三家基石投资者合计认购意向上限(非约束)", "2026-10-28 定价", "对手方-Meta-424B5-20261028.htm",
     r"NVIDIA Corporation, Advanced Micro Devices, Inc\., and Broadcom Inc\. \(collectively, the .Cornerstone Investors.\) have, "
     r"severally and not jointly, indicated an interest in purchasing up to an aggregate of \$\s?([\d.]+) billion of shares of Class A common stock", "B"),
    # 公司新闻稿（无对应 8-K）：对供应商的产能预留预付款
    ("KYEC 产能预留预付款(美国测试产能)", "2026-10-21 公告", "新闻稿-20261021-供应链产能.htm",
     r"\$\s?([\d.]+) billion capacity reservation advance to KYEC will support new U\.S\. testing facilities", "B"),
    # 上市权益证券的锁定期（净现金口径用：锁定期内不能出售的战略持股不是可动用现金·见 中期财务-FY2027.csv 派生两行）
    ("上市权益证券中处于短期锁定期的部分", "2026-01-25", "2026.htm",
     r"The balance as of January 25, 2026 includes \$\s?([\d.]+) billion of investments which are subject to short-term lock-up restrictions", "B"),
    ("上市权益证券中处于短期锁定期的部分", "2026-07-26", "2027-Q2.htm",
     r"\$\s?42,783 \$\s?4,957 \(1\) Included \$\s?([\d.]+) billion of investments that are subject to short-term lock-up restrictions", "B"),
    ("锁定至 2027-12 的上市权益证券长期部分(列在「其他资产」)", "2026-01-25", "2026.htm",
     r"subject to lock-up restrictions through December 2027 of \$\s?([\d.]+) billion as of January 25, 2026", "B"),
    ("锁定至 2027-12 的上市权益证券长期部分(列在「其他资产」)", "2026-07-26", "2027-Q2.htm",
     r"subject to lock-up restrictions through December 2027 of \$\s?([\d.]+) billion as of July 26, 2026", "B"),
    # 公司新闻稿：算力融资平台（谅解备忘录·第三方资本目标，非 NVIDIA 出资额）
    # 新闻稿首句前无句号（前面是页头导航与脚本），按句号回溯会把整页页头截进锚句 → 第 6 项 "exact"：锚句 = 正则完整命中的那一句
    ("算力融资平台·拟调动第三方资本目标(谅解备忘录·非 NVIDIA 出资)", "2026-08-10 公告", "新闻稿-20260810-算力融资平台.htm",
     r"NVIDIA today announced strategic partnerships to establish independent compute financing platforms with Apollo, "
     r"BlackRock, Blackstone, Brookfield, Goldman Sachs and KKR to mobilize over \$\s?([\d.]+) billion of third-party capital "
     r"for the buildout of AI infrastructure over time\.", "B", "exact"),
    ("长期供应协议预付款(营运资本变动主因)", "FY2022", "2022.htm",
     r"Changes in working capital were primarily driven by prepayments of \$\s?([\d.]+) billion for long-term supply agreements", "B"),
    # SEC 意见函往来（CORRESP·2025-07-31 公司回函）：服务收入占比（财报关注要点.md 诚信记录引用）
    ("许可与其他服务收入占合并营收(%)·公司回复 SEC 意见函", "FY2025", "CORRESP-20250731.htm",
     r"the fiscal year 2025 revenue related to licensing and other services was approximately (\d+) ?% of our consolidated revenue", "P"),
    ("总部在美国以外客户的收入占比(%)", "FY2026", "2026.htm",
     r"Revenue from sales to customers headquartered outside of the United States accounted for (\d+) ?%", "P"),
    # 季中时点的应收集中度（中期表只有 2026-07-26 / 2026-01-25 两个时点列，04-26 只在 Q1 10-Q 正文）
    ("直接客户应收集中度·第一大(%·另两家见锚句)", "2026-04-26", "2027-Q1.htm",
     r"Three direct customers accounted for (\d+) ?%, \d+ ?%, and \d+ ?% of our accounts receivable balance as of April 26, 2026", "P"),
    ("台湾总部客户的数据中心收入中归属美欧终端客户的估计占比(%)", "FY2026", "2026.htm",
     r"we estimate (\d+) ?% of Data Center revenue from Taiwan-headquartered customers was attributed to end customers based in the United States and Europe", "P"),
    # FY2027 Q2 10-Q 承诺表（Note 10·十亿美元·表格行无句号 → exact：锚句 = 该表行）——2026-11-12 补：上一版只取了供应产能与股权投资承诺，
    # 漏了自用 / 为第三方的数据中心租约、云服务协议、资本开支与两张表的合计
    ("多年期云服务协议承诺(自用研发·未来付款合计)", "2026-07-26", "2027-Q2.htm",
     r"Cloud service agreements(?:\s+\$?\s?(?:—|[\d,]+)){6}\s+\$?\s?([\d,]+)", "B", "exact"),
    ("自用数据中心租约·尚未起租(未来付款合计·主要用于芯片与系统研发测试)", "2026-07-26", "2027-Q2.htm",
     r"Data center leases not commenced(?:\s+\$?\s?(?:—|[\d,]+)){6}\s+\$?\s?([\d,]+)", "B", "exact"),
    ("资本开支承诺(未来付款合计)", "2026-07-26", "2027-Q2.htm",
     r"Equity investments(?:\s+\$?\s?(?:—|[\d,]+)){6}\s+\$?\s?[\d,]+ Capital expenditures(?:\s+\$?\s?(?:—|[\d,]+)){6}\s+\$?\s?([\d,]+)",
     "B", "exact"),
    ("承诺合计(供应产能 + 云服务 + 自用租约 + 股权投资 + 资本开支)", "2026-07-26", "2027-Q2.htm",
     r"Capital expenditures(?:\s+\$?\s?(?:—|[\d,]+)){6}\s+\$?\s?[\d,]+ Total(?:\s+\$?\s?(?:—|[\d,]+)){6}\s+\$?\s?([\d,]+)", "B", "exact"),
    ("为第三方签订、预计转让的数据中心租约·尚未起租(约 15 年·预计 FY2028–2029 起租)", "2026-07-26", "2027-Q2.htm",
     r"Data center leases not commenced for third party(?:\s+\$?\s?(?:—|[\d,]+)){6}\s+\$?\s?([\d,]+)", "B", "exact"),
    ("附加承诺合计(AI 云伙伴协议 + 为第三方的数据中心租约)", "2026-07-26", "2027-Q2.htm",
     r"Data center leases not commenced for third party(?:\s+\$?\s?(?:—|[\d,]+)){6}\s+\$?\s?[\d,]+ Total(?:\s+\$?\s?(?:—|[\d,]+)){6}\s+\$?\s?([\d,]+)",
     "B", "exact"),
    # 业绩 8-K EX-99.2 CFO 书面评论（公司自陈 DSO；10-Q 不印 DSO）
    ("应收账款周转天数 DSO(公司自陈·CFO 评论)", "2026-01-25", "8-K-20260520-EX99.2-CFO评论.htm",
     r"days sales outstanding \(DSO\), down from (\d+) days sequentially", "D"),
    ("应收账款周转天数 DSO(公司自陈·CFO 评论)", "2026-04-26", "8-K-20260520-EX99.2-CFO评论.htm",
     r"Accounts receivable was \$\s?[\d.]+ billion with (\d+) days sales outstanding", "D"),
    ("应收账款周转天数 DSO(公司自陈·CFO 评论)", "2026-07-26", "8-K-20260826-EX99.2-CFO评论.htm",
     r"Accounts receivable was \$\s?[\d.]+ billion with (\d+) days sales outstanding", "D"),
    ("当季发往中国的数据中心 Hopper 产品占数据中心营收(%·上限·原文 less than)", "FY2027 Q2", "8-K-20260826-EX99.2-CFO评论.htm",
     r"Shipments of Data Center Hopper products to China during the quarter were less than (\d+) ?% of Data Center revenue", "P"),
    # 2026 DEF 14A 实益持股表（截至 2026-03-23·表格行无句号 → exact）——创始人 2026-11-11 辞任后其持股成为股东结构要素
    ("黄仁勋实益持股(含其信托与关联实体)", "2026-03-23", "DEF14A-20260512.htm", r"NEOs: Jen-Hsun Huang ([\d,]+) \(1\)", "SH", "exact"),
    ("黄仁勋实益持股占比(%)", "2026-03-23", "DEF14A-20260512.htm", r"NEOs: Jen-Hsun Huang [\d,]+ \(1\) — [\d,]+ ([\d.]+) ?%", "P", "exact"),
    ("董事及高管合计实益持股占比(%·14 人)", "2026-03-23", "DEF14A-20260512.htm",
     r"Directors and executive officers as a group \(14 persons\) [\d,]+ \(13\) [\d,]+ [\d,]+ ([\d.]+) ?%", "P", "exact"),
    ("5% 以上股东·BlackRock 持股占比(%)", "2026-03-23", "DEF14A-20260512.htm", r"BlackRock, Inc\. [\d,]+ \(14\) — [\d,]+ ([\d.]+) ?%", "P", "exact"),
    ("5% 以上股东·Vanguard 持股占比(%)", "2026-03-23", "DEF14A-20260512.htm",
     r"Vanguard Capital Management [\d,]+ \(15\) — [\d,]+ ([\d.]+) ?%", "P", "exact"),
]
MULT = {"B": 1000.0, "M": 1.0, "N": 1.0, "P": 1.0, "D": 1.0, "SH": 1e-6}


def plain(path):
    s = open(path, encoding="utf-8", errors="ignore").read()
    s = re.sub(r"<ix:header>.*?</ix:header>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s).replace("\xa0", " ").replace("‑", "-")
    s = re.sub(r"\s+", " ", s).replace(" ,", ",").replace(" .", ".")
    return s


def main():
    cache, rows, bad = {}, [], []
    for name, per, fn, pat, u, *opt in ITEMS:
        if fn not in cache:
            cache[fn] = plain(os.path.join(REPORT, fn))
        m = re.search(pat, cache[fn])
        if not m:
            bad.append((name, per, fn))
            continue
        v = float(m.group(1).replace(",", "")) * MULT[u]
        if opt and opt[0] == "exact":
            sent = m.group(0).strip()
        else:
            lo = cache[fn].rfind(". ", 0, m.start()) + 2
            hi = cache[fn].find(". ", m.end())
            sent = cache[fn][lo:hi + 1].strip()
        rows.append((name, per, v, {"B": "百万美元", "M": "百万美元", "N": "百万股", "P": "%", "D": "天", "SH": "百万股"}[u], fn, sent))
    # 算术闸（2026-11-12）：Q2 10-Q 两张承诺表「明细和 = 表印合计」——各行分别由不同锚句取数，合计行独立取，三方对上才写出
    if not bad:
        kv = {(r[0], r[1]): r[2] for r in rows}
        t = "2026-07-26"
        parts = [kv.get((n, t)) for n in ("供应与产能承诺(10-Q 自陈·季末)", "多年期云服务协议承诺(自用研发·未来付款合计)",
                                          "自用数据中心租约·尚未起租(未来付款合计·主要用于芯片与系统研发测试)", "股权投资承诺",
                                          "资本开支承诺(未来付款合计)")]
        tot = kv.get(("承诺合计(供应产能 + 云服务 + 自用租约 + 股权投资 + 资本开支)", t))
        if None in parts or tot is None or abs(sum(parts) - tot) > 1e-6:
            bad.append(("算术闸", "承诺表明细和 = 合计", (parts, tot)))
        parts2 = [kv.get((n, t)) for n in ("AI 云伙伴新模式下的云服务协议承诺(通常 6 年)",
                                           "为第三方签订、预计转让的数据中心租约·尚未起租(约 15 年·预计 FY2028–2029 起租)")]
        tot2 = kv.get(("附加承诺合计(AI 云伙伴协议 + 为第三方的数据中心租约)", t))
        if None in parts2 or tot2 is None or abs(sum(parts2) - tot2) > 1e-6:
            bad.append(("算术闸", "附加承诺表明细和 = 合计", (parts2, tot2)))
    if bad:
        print(f"❌ 锚句找不到或算术闸不过 {len(bad)} 条（不写出）：")
        for b in bad:
            print("   ", b)
        return 1
    with open(os.path.join(HERE, "附注自陈数.csv"), "w", newline="") as f:
        f.write("# 10-K/10-Q/8-K/公司新闻稿/对手方申报 正文以句子给出的关键数(脚本按锚句从原文解析·非手抄) | 源文件在 report/Nvidia/ | "
                "「原文锚句」列为英文原句，中文释义见「科目」列 | 十亿美元一位小数的原文 → 换算为百万美元 | "
                "新闻稿为公告口径(宣布/计划投资)，是否已交割以后续 10-Q/10-K 为准\n")
        w = csv.writer(f)
        w.writerow(["科目", "期间/时点", "值", "单位", "来源文件", "原文锚句"])
        for r in rows:
            w.writerow([r[0], r[1], f"{r[2]:g}", r[3], r[4], r[5]])
    print(f"✅ 写出 附注自陈数.csv（{len(rows)} 条，全部锚句命中）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
