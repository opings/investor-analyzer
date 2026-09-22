#!/usr/bin/env python3
"""NIKE 表外与股东回报承诺构建器 → `表外承诺与回购计划.csv`。

抓三类**三张表上看不到**、但直接决定风险判断的东西：

1. **供应商融资计划（Supplier Finance Program）余额** —— 应付账款被第三方金融机构
   提前付给供应商、NIKE 到期再还。它记在应付账款里、不计入有息负债，
   但本质是**带期限的表外融资**；余额骤降会一次性抽走经营现金流。
   FY2023 起 ASU 2022-04 才强制披露，更早年份**不是零、是未披露**。
2. **银行保函与信用证** —— 或有负债。
3. **回购计划授权额度与已执行进度** —— 「授权 ≠ 已执行」。NIKE 的回购从
   FY2024 的 42.5 亿降到 FY2026 的 1.46 亿（见 现金流量表.csv），
   而授权额度一直挂在那里；只看授权会严重高估未来回购。

⚠️ **采购承诺（product purchase obligations）**：SEC 在 2021 年取消了
「契约义务表」的强制格式后，NIKE 各年的披露位置与措辞不断变，
本脚本只在能确证的年份取值，取不到的年份**留空并标 ⏳待补**，不猜。
"""
import csv
import html
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
REPORT = os.path.join(ROOT, "report", "耐克")
FY = list(range(2011, 2027))

# ⚠️ 同一件事各年措辞不同、单位在 million / billion 之间来回换 ——
#    正则一律写成「量 + 单位」两个捕获组，由 `to_bn()` 统一折成十亿美元。
#    实证：银行保函 FY2022 印 "outstanding totaling $289 million"、
#    FY2026 印 "of approximately $1.3 billion"；回购进度 FY2022 印
#    "under this program"、FY2026 印 "under the Share Repurchase Program"。
#    只写一种写法 = 只有最新那年有数（第一版就是这样，16 年里只填上 FY2026 一格）。
PATTERNS = {
    "银行保函与信用证 Bank guarantees & LCs":
        r"bank guarantees and letters of credit (?:of approximately|outstanding totaling|outstanding of approximately)"
        r"\s*\$\s?([\d.,]+)\s*(billion|million)",
    "回购计划授权总额 Repurchase program authorized":
        r"[Bb]oard of [Dd]irectors (?:approved|authorized) a (?:new )?(?:four|three)-year,?\s*"
        r"\$\s?([\d.,]+)\s*(billion|million) (?:share repurchase|program to repurchase)",
    "产品采购承诺 Product purchase obligations":
        r"product purchase obligations of approximately \$\s?([\d.,]+)\s*(billion|million)",
    "其他采购承诺 Other purchase obligations":
        r"[Oo]ther[^.]{0,40}purchase obligations of approximately \$\s?([\d.,]+)\s*(billion|million)",
    "本计划累计已回购 Cumulative repurchased under program":
        r"for a total approximate cost of \$\s?([\d.,]+)\s*(billion|million) under (?:this|the Share Repurchase)",
    "本计划剩余额度 Remaining authorization":
        r"approximately \$\s?([\d.,]+)\s*(billion|million) of the Company's Class B Common Stock remains available",
}


def to_bn(num, unit):
    v = float(num.replace(",", ""))
    return v if unit.lower().startswith("b") else v / 1000.0


def text(fy):
    for ext in ("htm", "txt"):
        p = os.path.join(REPORT, f"{fy}.{ext}")
        if os.path.exists(p):
            s = open(p, encoding="utf-8", errors="ignore").read()
            return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s)))
    return ""


def supplier_finance():
    """供应商融资计划余额 —— 走 XBRL（`_rfiles/*.json` 的 SUPF 槽位），不走正文正则。"""
    import json
    out = {}
    for ffy in FY:
        p = os.path.join(HERE, "_rfiles", f"{ffy}.json")
        if not os.path.exists(p):
            continue
        st = json.load(open(p))["statements"].get("SUPF")
        if not st:
            continue
        sc = 1.0 if "in billions" in (st.get("unit") or "").lower() else 1e-3
        for i, per in enumerate(st["periods"]):
            m = re.search(r"\b((19|20)\d\d)\b", per)
            if not m:
                continue
            y = int(m.group(1))
            for r in st["rows"]:
                if r["tag"] == "us-gaap_SupplierFinanceProgramObligationCurrent":
                    v = r["vals"][i] if i < len(r["vals"]) else None
                    if v is not None:
                        out.setdefault(y, v * sc)
    return out


def main():
    data = {k: {} for k in PATTERNS}
    for fy in FY:
        t = text(fy)
        if not t:
            continue
        for name, pat in PATTERNS.items():
            m = re.search(pat, t)
            if m:
                data[name][fy] = to_bn(m.group(1), m.group(2))
    data["供应商融资计划余额(十亿美元) Supplier finance obligations"] = supplier_finance()

    path = os.path.join(HERE, "表外承诺与回购计划.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# 单位: 十亿美元 | 时点 = 财年末 5 月 31 日 | 来源 = 各年 10-K 正文/附注 | "
                    "🔴 空 = **该年未披露或披露措辞不同，尚未确证**，不是零 —— "
                    "SEC 2021 年取消契约义务表强制格式后，NIKE 各年披露位置与措辞不断变；"
                    "供应商融资计划自 FY2023(ASU 2022-04)起才强制披露 | "
                    "🔴「回购授权」≠「已执行」：实际回购金额看 现金流量表.csv 的『回购股票』行 | "
                    "🔴「本计划累计已回购」**每换一期回购计划就归零重算**"
                    "（$12bn 计划 FY2015-2018 → $15bn 计划 FY2019-2022 → $18bn 计划 FY2023 起），"
                    "所以这一行不是单调累计序列，跨计划年份直接相减无意义"])
        w.writerow(["项目"] + [f"FY{y}" for y in FY])
        for name, d in data.items():
            row = [name] + [("" if d.get(y) is None else f"{d[y]:g}") for y in FY]
            if any(row[1:]):
                w.writerow(row)
    print(f"写出 表外承诺与回购计划.csv")
    for name, d in data.items():
        print(f"  {name[:34]:36s} 覆盖 {sorted(d)}")


if __name__ == "__main__":
    main()
