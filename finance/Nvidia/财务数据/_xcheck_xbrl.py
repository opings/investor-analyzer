#!/usr/bin/env python3
"""XBRL 独立核：SEC companyfacts API（`_xbrl/companyfacts.json`）vs 三表 CSV（R / L 轨产物）。

为什么是独立通道：R 文件是 SEC 对 XBRL 实例的**渲染**（带渲染错——见 `_build_from_filings.py` R_SIGN_FIX），
companyfacts 是 SEC 从同一批申报**抽取的事实库**，取数路径不同；L 轨（FY2010-2011）则是从 HTML 印刷件解析，
与 XBRL 完全无关——三条路对上一个数，才算这个数被独立确认。

取数规则（防 `min(fy)` 陷阱，记忆 xbrl-multi-tag-concept-drift）：只取 **accession = 该财年自家 10-K、
end = 该财年末日** 的事实（= 该财年自家年报的原始申报值），不取后续年报的重列值。期间类事实另要求
end−start > 300 天（排除季度值）。

🔴 **不能按 companyfacts 的 `fy` 字段选**：FY2014 那份 10-K（0001045810-14-000030）的事实在 companyfacts 里
被标成 fy=2013（申报自身 dei:DocumentFiscalYearFocus 填错）。第一版按 fy 选，FY2014 整年 16 格「缺一边」，
FY2013 却抓到 FY2014 年报的**比较列**（存货 412.467 ≠ as-reported 419.686）——一个 filer 错同时制造了
假缺失和假不一致。按 accession 选则两者都消失。
"""
import csv
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FY_END = {2010: "2010-01-31", 2011: "2011-01-30", 2012: "2012-01-29", 2013: "2013-01-27", 2014: "2014-01-26",
          2015: "2015-01-25", 2016: "2016-01-31", 2017: "2017-01-29", 2018: "2018-01-28", 2019: "2019-01-27",
          2020: "2020-01-26", 2021: "2021-01-31", 2022: "2022-01-30", 2023: "2023-01-29", 2024: "2024-01-28",
          2025: "2025-01-26", 2026: "2026-01-25"}
# 各财年自家 10-K 的 accession（data.sec.gov/submissions，2026-11-09 拉取；与 report/Nvidia/_下载清单.tsv 一致）
ACCN = {2010: "0001045810-10-000006", 2011: "0001045810-11-000015", 2012: "0001045810-12-000013",
        2013: "0001045810-13-000008", 2014: "0001045810-14-000030", 2015: "0001045810-15-000036",
        2016: "0001045810-16-000205", 2017: "0001045810-17-000027", 2018: "0001045810-18-000010",
        2019: "0001045810-19-000023", 2020: "0001045810-20-000010", 2021: "0001045810-21-000010",
        2022: "0001045810-22-000036", 2023: "0001045810-23-000017", 2024: "0001045810-24-000029",
        2025: "0001045810-25-000023", 2026: "0001045810-26-000021"}

# (CSV 文件, CSV 行名, [候选 tag], 是否期间类)
CHECKS = [
    ("利润表.csv", "营业收入 Revenue", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"], True),
    ("利润表.csv", "营业成本 Cost of revenue", ["CostOfRevenue", "CostOfGoodsAndServicesSold"], True),
    ("利润表.csv", "毛利 Gross profit", ["GrossProfit"], True),
    ("利润表.csv", "研发费用 Research and development", ["ResearchAndDevelopmentExpense"], True),
    ("利润表.csv", "营业利润 Operating income", ["OperatingIncomeLoss"], True),
    ("利润表.csv", "所得税 Income tax expense (benefit)", ["IncomeTaxExpenseBenefit"], True),
    ("利润表.csv", "净利润 Net income", ["NetIncomeLoss"], True),
    ("利润表.csv", "摊薄EPS(as-reported·拆股基准随年变) Diluted EPS", ["EarningsPerShareDiluted"], True),
    ("资产负债表.csv", "现金及现金等价物 Cash and cash equivalents", ["CashAndCashEquivalentsAtCarryingValue"], False),
    ("资产负债表.csv", "应收账款净额 Accounts receivable, net", ["AccountsReceivableNetCurrent"], False),
    ("资产负债表.csv", "存货 Inventories", ["InventoryNet"], False),
    ("资产负债表.csv", "总资产 Total assets", ["Assets"], False),
    ("资产负债表.csv", "股东权益合计 Total shareholders' equity", ["StockholdersEquity"], False),
    ("现金流量表.csv", "经营活动现金流净额 Net cash from operating activities", ["NetCashProvidedByUsedInOperatingActivities"], True),
    ("现金流量表.csv", "投资活动现金流净额 Net cash from investing activities", ["NetCashProvidedByUsedInInvestingActivities"], True),
    ("现金流量表.csv", "融资活动现金流净额 Net cash from financing activities", ["NetCashProvidedByUsedInFinancingActivities"], True),
    # —— 现金流明细（全格变异里「不在任何勾稽等式」的那批：靠这条独立通道补确认）
    ("现金流量表.csv", "折旧及摊销 Depreciation and amortization", ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization"], True),
    ("现金流量表.csv", "股权激励费用 Stock-based compensation", ["ShareBasedCompensation"], True),
    ("现金流量表.csv", "递延所得税 Deferred income taxes", ["DeferredIncomeTaxExpenseBenefit"], True),
    ("现金流量表.csv", "应收账款变动 Change in accounts receivable", ["IncreaseDecreaseInAccountsReceivable"], True),
    ("现金流量表.csv", "存货变动 Change in inventories", ["IncreaseDecreaseInInventories"], True),
    ("现金流量表.csv", "应付账款变动 Change in accounts payable", ["IncreaseDecreaseInAccountsPayable"], True),
    ("现金流量表.csv", "资本开支(购置固定资产及无形资产) Purchases of property and equipment and intangible assets",
     ["PaymentsToAcquireProductiveAssets", "PaymentsToAcquirePropertyPlantAndEquipment"], True),
    ("现金流量表.csv", "购买有价证券 Purchases of marketable securities",
     ["PaymentsToAcquireAvailableForSaleSecuritiesDebt", "PaymentsToAcquireMarketableSecurities"], True),
    ("现金流量表.csv", "收购业务(扣除取得现金) Acquisitions, net of cash acquired", ["PaymentsToAcquireBusinessesNetOfCashAcquired"], True),
    ("现金流量表.csv", "Groq 交易(仅FY2026单列) Groq, Inc.", ["PaymentsToAcquireBusinessTwoNetOfCashAcquired"], True),
    ("现金流量表.csv", "购买非上市权益证券(FY2025起单列) Purchases of non-marketable equity securities",
     ["PaymentsToAcquireEquitySecuritiesFvNi"], True),
    ("现金流量表.csv", "投资损益(收益为负) (Gains) losses on investments", ["GainLossOnInvestments"], True),
    ("现金流量表.csv", "员工股票计划所得 Proceeds related to employee stock plans", ["ProceedsFromStockPlans", "ProceedsFromStockOptionsExercised"], True),
    ("现金流量表.csv", "回购普通股 Repurchases of common stock", ["PaymentsForRepurchaseOfCommonStock"], True),
    ("现金流量表.csv", "RSU 代扣个税 Payments related to employee stock plan taxes", ["PaymentsRelatedToTaxWithholdingForShareBasedCompensation"], True),
    ("现金流量表.csv", "支付股息 Dividends paid", ["PaymentsOfDividends"], True),
    ("现金流量表.csv", "发债所得 Proceeds from issuance of debt", ["ProceedsFromDebtNetOfIssuanceCosts", "ProceedsFromConvertibleDebt"], True),
    ("现金流量表.csv", "偿还债务 Repayment of debt", ["RepaymentsOfDebt", "RepaymentsOfConvertibleDebt"], True),
    ("现金流量表.csv", "支付所得税(净额) Cash paid for income taxes, net", ["IncomeTaxesPaidNet"], True),
    ("现金流量表.csv", "支付利息 Cash paid for interest", ["InterestPaidNet"], True),
]
# CSV 符号 = −XBRL：XBRL 里「增加 / 支付 / 收益」记正数，现金流量表印刷为流出（负）或从净利中扣减
NEG_IN_CSV = {"应收账款变动 Change in accounts receivable", "存货变动 Change in inventories",
              "资本开支(购置固定资产及无形资产) Purchases of property and equipment and intangible assets",
              "购买有价证券 Purchases of marketable securities", "收购业务(扣除取得现金) Acquisitions, net of cash acquired",
              "Groq 交易(仅FY2026单列) Groq, Inc.",
              "购买非上市权益证券(FY2025起单列) Purchases of non-marketable equity securities",
              "投资损益(收益为负) (Gains) losses on investments", "回购普通股 Repurchases of common stock",
              "RSU 代扣个税 Payments related to employee stock plan taxes", "支付股息 Dividends paid",
              "偿还债务 Repayment of debt"}
# 明细行：CSV 有值而 XBRL 没有（公司自定义 tag 不进 companyfacts，如 FY2013-2023 资本开支用 nvda_ 标签）只计数不报错
DETAIL = {c[1] for c in CHECKS[16:]}
# XBRL 事实与印刷件**等绝对值、符号相反**——已回 10-K 印刷件仲裁，CSV = 印刷（XBRL 头几年 filer 标注符号错）。
# 只在「绝对值相等」时放行；绝对值不等照样报错。
XBRL_SIGN_KNOWN = {
    ("应收账款变动 Change in accounts receivable", 2010): "FY2010 10-K 印刷件 (56,741)；XBRL 事实 −56,741（增加应收本应记正）",
    ("存货变动 Change in inventories", 2010): "FY2010 10-K 印刷件 204,656；XBRL 事实 +204,656（存货减少本应记负）",
    ("应收账款变动 Change in accounts receivable", 2011): "FY2013 10-K 比较列印 26,341（与 FY2011 自家 HTML 同）；XBRL 事实 +26,341",
    ("存货变动 Change in inventories", 2011): "FY2013 10-K 比较列印 (14,128)（与 FY2011 自家 HTML 同）；XBRL 事实 −14,128",
    ("支付所得税(净额) Cash paid for income taxes, net", 2013):
        "FY2013 10-K 印刷件「Cash (received) paid for income taxes, net (38,608)」= 退税；XBRL 事实 +38,608",
}


def read_csv(fn):
    rows = list(csv.reader(open(os.path.join(HERE, fn))))
    hdr = next(i for i, r in enumerate(rows) if r and r[0] == "科目")
    years = [int(y[2:]) for y in rows[hdr][1:]]
    out = {}
    for r in rows[hdr + 1:]:
        out[r[0]] = {y: (float(v) if v not in ("",) and r[0] != "数据来源" else None)
                     for y, v in zip(years, r[1:]) if r[0] != "数据来源"}
    return out


def facts_for(cf, tag, fy, duration):
    node = cf["facts"].get("us-gaap", {}).get(tag)
    if not node:
        return []
    out = []
    for unit, arr in node["units"].items():
        for f in arr:
            if f.get("accn") != ACCN[fy] or f.get("end") != FY_END[fy]:
                continue
            if duration:
                if "start" not in f:
                    continue
                d = (dt.date.fromisoformat(f["end"]) - dt.date.fromisoformat(f["start"])).days
                if d < 300:
                    continue
            out.append((unit, f["val"], f.get("accn")))
    return out


def main():
    cf = json.load(open(os.path.join(HERE, "_xbrl", "companyfacts.json")))
    tables = {fn: read_csv(fn) for fn in {c[0] for c in CHECKS}}
    ok = bad = miss = dmiss = sign_known = 0
    confirmed = []
    for fn, row, tags, dur in CHECKS:
        for fy in sorted(FY_END):
            v = tables[fn].get(row, {}).get(fy)
            hits = []
            for t in tags:
                hits = facts_for(cf, t, fy, dur)
                if hits:
                    break
            if row in DETAIL and (v is None or not hits):
                if v is not None:
                    dmiss += 1
                continue
            if v is None or not hits:
                miss += 1
                print(f"  缺一边 FY{fy} {row[:20]}: CSV={v} XBRL={'有' if hits else '无'}")
                continue
            unit, xv, accn = hits[0]
            xv = xv if unit != "USD" else xv / 1e6
            if row in NEG_IN_CSV:
                xv = -xv
            tol = (0.0005 if unit == "USD" else 0.005) + 1e-9
            if abs(xv - v) <= tol:
                ok += 1
                confirmed.append((row, fy))
            elif (row, fy) in XBRL_SIGN_KNOWN and abs(abs(xv) - abs(v)) <= tol:
                sign_known += 1
                confirmed.append((row, fy))
            else:
                bad += 1
                print(f"  ❌ FY{fy} {row[:28]}: CSV {v} vs XBRL {xv} ({accn})")
    print(f"XBRL 独立核：一致 {ok} 格 / XBRL 符号标反·已回印刷件仲裁 {sign_known} 格 / 不一致 {bad} 格 / "
          f"核心科目缺一边 {miss} 格（明细行 CSV 有值、XBRL 无同义 us-gaap 事实 {dmiss} 格，多为 nvda_ 自定义 tag）")
    fy26 = sorted(r[:16] for r, y in confirmed if y == 2026 and r in DETAIL)
    print(f"FY2026 现金流明细经 XBRL 独立确认 {len(fy26)} 项：" + "、".join(fy26))
    return 1 if (bad or miss) else 0


if __name__ == "__main__":
    sys.exit(main())
