#!/usr/bin/env python3
"""表外合约承诺 → `表外承诺.csv`（从 10-K Note「Commitments and Contingencies」解析）。

## 为什么必须单独建这张表

「维持当前利润要投入什么」这个问题，**只看资本开支会漏掉最大的一块**：

| 层 | FY2025/FY2026 量级 | 在哪张表上 |
|---|---|---|
| 资本开支 | FY2025 约 80 亿、FY2026 指引约 90 亿 | 现金流量表·投资活动 |
| 内容支出 | FY2026 指引约 240 亿（含体育版权） | 现金流量表·**经营活动**（不在资本开支里） |
| **合约承诺** | **总额约 1,041 亿** | 🔴 **表外**，只在附注 |

其中**体育版权承诺约 841 亿、占总承诺八成**，且未来五年每年都要付约 91-99 亿、
几乎不随收视率波动 —— **这是已经签字、不可调节的刚性支出**，
决定了 Disney 成本结构的下限。

⚠️ 年报另注明：**某些体育版权的付款按收入变动计，未包含在该表内** → 实际承诺更高。

## 解析方式

该承诺表在 SEC 渲染报表里不总是独立成表，故直接从 `report/Disney/<年>.htm`
正文（去标签后）用锚点定位 + 正则抽数，抽完做「分年合计 = 表内总计」自检。
"""
import csv
import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
REPORT = os.path.join(ROOT, "report", "Disney")

ANCHOR = r"Contractual commitments for sports programming rights"
# 表头形如：Fiscal Year: Sports Programming (1) Other Programming Other Total
ROW = re.compile(r"(20\d\d|Thereafter)\s+\$?\s*([\d,]+)\s+\$?\s*([\d,]+)\s+\$?\s*([\d,]+)\s+"
                 r"\$?\s*([\d,]+)")


def text_of(path):
    raw = open(path, "rb").read().decode("utf-8", "ignore")
    raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw)))


def parse(fy):
    path = os.path.join(REPORT, f"{fy}.htm")
    if not os.path.exists(path):
        return None
    t = text_of(path)
    m = re.search(ANCHOR, t)
    if not m:
        return None
    seg = t[m.start():m.start() + 1400]
    rows = []
    for mm in ROW.finditer(seg):
        label = mm.group(1)
        vals = [float(mm.group(i).replace(",", "")) for i in range(2, 6)]
        rows.append((label, vals))
    if not rows:
        return None
    # 末行若是合计（四个数之和与前面各行之和相等）则单独标出
    tot = re.search(r"\$\s*([\d,]+)\s+\$?\s*([\d,]+)\s+\$?\s*([\d,]+)\s+\$?\s*([\d,]+)\s*\(1\)",
                    seg)
    return rows, ([float(tot.group(i).replace(",", "")) for i in range(1, 5)] if tot else None)


def main():
    fy = int(sys.argv[1]) if len(sys.argv) > 1 else 2025
    got = parse(fy)
    if not got:
        print(f"FY{fy}: 未定位到承诺表")
        return
    rows, printed_tot = got
    cols = ["体育版权 Sports programming", "其他节目版权 Other programming",
            "其他(邮轮/创意人才等) Other", "合计 Total"]
    calc = [sum(v[i] for _, v in rows) for i in range(4)]

    with open(os.path.join(HERE, "表外承诺.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([f"单位:百万美元(USD millions)。来源=FY{fy} 10-K 附注 "
                    f"Commitments and Contingencies 的合约承诺分年表。"])
        w.writerow(["🔴 **这是表外承诺**，不在资产负债表上。体育版权占八成、未来五年每年约 91-99 亿"
                    "且几乎不随收视率波动——已签字、不可调节，决定成本结构下限。"
                    "⚠️ 年报注明：某些体育版权按收入变动计的付款**未包含在本表内**，实际承诺更高。"])
        w.writerow([f"付款所属财年（截至 FY{fy} 末）"] + cols)
        for label, vals in rows:
            w.writerow([("此后 Thereafter" if label == "Thereafter" else f"FY{label}")]
                       + [f"{v:.0f}" for v in vals])
        w.writerow(["合计 Total"] + [f"{v:.0f}" for v in calc])
    print(f"写出 表外承诺.csv（FY{fy}，{len(rows)} 个付款期间）")

    print("\n自检：")
    print(f"  分年各列相加   = {[f'{v:,.0f}' for v in calc]}")
    if printed_tot:
        ok = all(abs(a - b) <= 1 for a, b in zip(calc, printed_tot))
        print(f"  年报印的总计行 = {[f'{v:,.0f}' for v in printed_tot]}  "
              f"{'✅' if ok else '❌'}")
    ok2 = abs(sum(calc[:3]) - calc[3]) <= 1
    print(f"  三列之和 {sum(calc[:3]):,.0f} vs 合计列 {calc[3]:,.0f}  {'✅' if ok2 else '❌'}")


if __name__ == "__main__":
    main()
