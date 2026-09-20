#!/usr/bin/env python3
"""无形资产明细 → `无形资产明细.csv`（FY2011-FY2025）。

## 这张表要回答的问题：Disney 的 IP 在账上值多少

🔴 **答案是「只有买来的那部分在账上」。** 美国 GAAP 下**自创无形资产直接费用化**，
不资本化 —— 米老鼠、白雪公主、狮子王这些自己画出来的 IP，**账面价值接近零**。
表里「角色/系列无形资产、版权与商标」那一行的毛值，基本全是四笔并购的购买法产物：
皮克斯(2006)、漫威(2009)、卢卡斯影业(2012)、二十一世纪福克斯(2019)。

**不看这张表最容易犯的错**：以为资产负债表上的无形资产 + 商誉 ≈ Disney 的 IP 价值。
实际上两者关系相反 —— **账面上越值钱的 IP，越是买来的那些。**

⚠️ 另一条与本表配套的事实（不在数字里、在风险因素里）：
**版权会到期**。美国版权期为自取得日起 95 个日历年；FY2025 10-K 明确列示
《Steamboat Willie》(1928) 及该片中早期版本角色的版权**已到期**，
并称「As copyrights expire, we expect that revenues generated from such IP will be
negatively impacted to some extent」（译：随着版权陆续到期，我们预计由该等 IP
产生的收入将在一定程度上受到负面影响）。这是一条**时间驱动、不可逆**的护城河侵蚀。
"""
import csv
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
RDIR = os.path.join(HERE, "_rfiles")

# (CSV 行名, 维度上下文正则 或 None=合计层, 标签正则)
ROWS = [
    ("无形资产毛值合计 Gross", None, r"^intangible assets, gross"),
    ("  需摊销无形资产-毛值 Finite-lived, gross", None, r"^finite-lived intangible assets, gross$"),
    ("  需摊销无形资产-累计摊销 Accumulated amortization", None, r"^accumulated amortization$"),
    ("  需摊销无形资产-净值 Finite-lived, net", None, r"^finite-lived intangible assets, net$"),
    ("  无限寿命无形资产 Indefinite-lived", None, r"^other indefinite lived intangible assets$"),
    ("无形资产净值合计 Net", None, r"^intangible assets$"),
    ("── 按类别·毛值（两代列报都给） ──", None, r"^$"),
    # FY2013-FY2020 是**平铺**列报（每类只给毛值、无维度）；FY2021+ 改为按
    # us-gaap_FiniteLivedIntangibleAssetsByMajorClassAxis 维度拆，标签变成通用的
    # 「Finite-Lived Intangible Assets, Gross/Net」，靠维度上下文区分。两代都要认。
    ("  角色/系列·版权·商标-毛值 Character/franchise, gross", r"character/franchise",
     r"^finite-lived intangible assets, gross$"),
    ("  角色/系列·版权·商标-毛值 Character/franchise, gross", None,
     r"^character/franchise intangibles and copyrights"),
    ("  分发协议-毛值 Distribution agreements, gross", r"distribution agreement",
     r"^finite-lived intangible assets, gross$"),
    ("  分发协议-毛值 Distribution agreements, gross", None, r"^distribution agreements$"),
    ("  其他-毛值 Other, gross", r"^other intangible assets$",
     r"^finite-lived intangible assets, gross$"),
    ("  其他-毛值 Other, gross", None, r"^other amortizable intangible assets$"),
    ("── 按类别·净值（仅 FY2021 起列报） ──", None, r"^$"),
    ("  角色/系列·版权·商标-净值 Character/franchise, net", r"character/franchise",
     r"^finite-lived intangible assets, net$"),
    ("  分发协议-净值 Distribution agreements, net", r"distribution agreement",
     r"^finite-lived intangible assets, net$"),
    ("  其他-净值 Other, net", r"^other intangible assets$",
     r"^finite-lived intangible assets, net$"),
]


def fy_of(p):
    m = re.search(r"\b((?:19|20)\d\d)\b", p)
    return int(m.group(1)) if m else None


def main():
    data = {}
    for f in sorted(os.listdir(RDIR)):
        if not f.endswith(".json"):
            continue
        d = json.load(open(os.path.join(RDIR, f)))
        key = int(d["key"])
        st = d["statements"].get("INTAN")
        if not st:
            continue
        col = next((i for i, p in enumerate(st["periods"]) if fy_of(p) == key), None)
        if col is None:
            continue
        ctx = ""
        for r in st["rows"]:
            tag, lab, vals = r["tag"], r["label"].strip().lower(), r["vals"]
            if tag.endswith("Axis") or (not tag and all(v is None for v in vals)):
                ctx = lab
                continue
            if "lineitems" in tag.lower():
                continue
            for name, ctx_pat, lab_pat in ROWS:
                if not lab_pat or lab_pat == r"^$" or not re.search(lab_pat, lab):
                    continue
                if ctx_pat is None:
                    if ctx:
                        continue
                elif not re.search(ctx_pat, ctx):
                    continue
                v = vals[col] if col < len(vals) else None
                if v is not None:
                    data.setdefault(name, {}).setdefault(key, v)
                break

    # 商誉（从已建好的资产负债表取，便于同表对照）
    bs = list(csv.reader(open(os.path.join(HERE, "资产负债表.csv"))))
    h = next(r for r in bs if r and r[0] == "科目")
    bys = [int(x) for x in h[1:]]
    for k, name in (("商誉", "商誉 Goodwill（对照）"),
                    ("归母权益", "归母权益（对照）")):
        row = next((r for r in bs if r[0].strip().startswith(k)), None)
        if row:
            data[name] = {y: float(v) for y, v in zip(bys, row[1:]) if v}

    fys = sorted({y for kv in data.values() for y in kv if 2011 <= y <= 2025})
    seen, order = set(), []
    for n, _, _ in ROWS:                       # 同名行有两条 spec（两代列报），去重保序
        if n not in seen:
            seen.add(n)
            order.append(n)
    order += ["商誉 Goodwill（对照）", "归母权益（对照）", "（商誉+无形净值）÷归母权益%"]
    gw, intan, eq = (data.get("商誉 Goodwill（对照）", {}),
                     data.get("无形资产净值合计 Net", {}),
                     data.get("归母权益（对照）", {}))
    data["（商誉+无形净值）÷归母权益%"] = {
        y: (gw[y] + intan[y]) / eq[y] * 100
        for y in fys if y in gw and y in intan and y in eq and eq[y]}

    with open(os.path.join(HERE, "无形资产明细.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["单位:百万美元(USD millions);比率行为%。来源=各年 10-K「Detail of Certain "
                    "Balance Sheet Accounts - Intangible Assets」附注。"])
        w.writerow(["🔴 **账上的 IP 只有买来的那部分**：美国 GAAP 下自创无形资产直接费用化，"
                    "米老鼠这类自创 IP 账面价值接近零。「角色/系列·版权·商标」一行基本全是"
                    "皮克斯(2006)/漫威(2009)/卢卡斯(2012)/福克斯(2019) 四笔并购的购买法产物。"
                    "⚠️ 版权会到期：Steamboat Willie(1928) 及片中早期版本角色版权已到期"
                    "（美国版权期 95 个日历年）——见 FY2025 10-K 风险因素。"])
        w.writerow(["科目"] + [str(y) for y in fys])
        for name in order:
            kv = data.get(name)
            if name.startswith("──"):
                w.writerow([name] + [""] * len(fys))
                continue
            if not kv:
                continue
            row = [name] + [(f"{kv[y]:.1f}".rstrip("0").rstrip(".") if y in kv else "")
                            for y in fys]
            if any(row[1:]):
                w.writerow(row)
    print(f"写出 无形资产明细.csv（{len(fys)} 年）")

    print("\n自检：需摊销净值 + 无限寿命 = 无形资产净值合计？")
    for y in fys:
        a = data.get("  需摊销无形资产-净值 Finite-lived, net", {}).get(y)
        b = data.get("  无限寿命无形资产 Indefinite-lived", {}).get(y)
        t = intan.get(y)
        if None in (a, b, t):
            continue
        print(f"  FY{y}: {a:,.0f} + {b:,.0f} = {a+b:,.0f} vs 合计 {t:,.0f}"
              + ("  ✅" if abs(a + b - t) <= 1 else "  ❌"))


if __name__ == "__main__":
    main()
