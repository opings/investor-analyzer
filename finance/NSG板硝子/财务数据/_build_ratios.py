#!/usr/bin/env python3
"""NSG 派生比率生成器 —— 从本目录三表 CSV 计算，产出 `财务比率.csv`

不用通用 scripts/derived.py 的原因：NSG 跨**两套准则**（FY2011/3 及以前 JGAAP、
FY2012/3 起 IFRS），同一概念在两段的科目名完全不同；且 NSG 的核心变量是
**有利子負債 / 净负债 / 净负债权益比**（皮尔金顿收购留下的债务是这家公司二十年的主线），
通用脚本不算这几项。

单位：百万円（与三表同）。比率为百分数或倍数，单位在行名里标。
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    """读 CSV → {行名前缀: {年: 值}}；行名取「（」前那段（日文科目名）。"""
    path = os.path.join(HERE, name)
    with open(path, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    years = rows[0][1:]
    out = {}
    for r in rows[1:]:
        key = r[0].split("（")[0]
        out[key] = {y: (float(v) if v not in ("", None) else None)
                    for y, v in zip(years, r[1:])}
    return years, out


def g(tbl, keys, y):
    """按 keys 顺序取第一个有值的（跨准则别名层）。"""
    for k in keys:
        v = tbl.get(k, {}).get(y)
        if v is not None:
            return v
    return None


def main():
    write = "--write" in sys.argv
    years, IS = load("利润表.csv")
    _, BS = load("资产负债表.csv")
    _, CF = load("现金流量表.csv")

    def calc(y):
        rev = g(IS, ["売上高"], y)
        cost = g(IS, ["売上原価"], y)
        op = g(IS, ["営業利益"], y)
        pretax = g(IS, ["税引前利益", "税金等調整前当期純利益"], y)
        prof = g(IS, ["親会社所有者帰属当期利益", "当期純利益"], y)
        fincost = g(IS, ["金融費用"], y)
        ta = g(BS, ["資産合計"], y)
        eq = g(BS, ["親会社所有者帰属持分合計", "純資産合計"], y)
        cash = g(BS, ["現金及び現金同等物", "現金及び預金"], y)
        inv = g(BS, ["棚卸資産"], y)
        # 有利子負債：IFRS 段两行；JGAAP 段四行（短期借入+一年内償還社債+社債+長期借入）
        ifrs_debt = [g(BS, ["社債及び借入金_流動"], y), g(BS, ["社債及び借入金_非流動"], y)]
        jg_debt = [g(BS, ["短期借入金"], y), g(BS, ["一年内償還予定社債"], y),
                   g(BS, ["社債"], y), g(BS, ["長期借入金"], y)]
        parts = ifrs_debt if any(v is not None for v in ifrs_debt) else jg_debt
        debt = sum(v for v in parts if v is not None) if any(
            v is not None for v in parts) else None
        pension = g(BS, ["退職給付引当金"], y)
        ocf = g(CF, ["営業活動によるキャッシュフロー"], y)
        capex_t = g(CF, ["有形固定資産取得"], y)
        capex_i = g(CF, ["無形資産取得"], y)
        capex = None
        if capex_t is not None or capex_i is not None:
            capex = abs(capex_t or 0) + abs(capex_i or 0)
        d = {}
        # 毛利率：IFRS 段成本为负、JGAAP 段为正 → 一律取 abs
        if rev and cost is not None:
            d["毛利率%"] = (rev - abs(cost)) / rev * 100
        if rev and op is not None:
            d["営業利益率%"] = op / rev * 100
        if rev and prof is not None:
            d["純利益率%"] = prof / rev * 100
        if eq and prof is not None:
            d["ROE%"] = prof / eq * 100
        if ta and eq:
            d["自己資本比率%"] = eq / ta * 100
        if debt is not None:
            d["有利子負債"] = debt
            if cash is not None:
                d["ネット有利子負債"] = debt - cash
                if eq:
                    d["ネットD/Eレシオ(倍)"] = (debt - cash) / eq
            if ta:
                d["有利子負債/総資産%"] = debt / ta * 100
        if pension is not None and eq:
            d["退職給付負債/自己資本%"] = pension / eq * 100
        if ocf is not None and prof:
            d["営業CF/純利益(倍)"] = ocf / prof
        if capex is not None:
            d["capex"] = capex
            if ocf:
                d["capex/営業CF%"] = capex / ocf * 100
            if rev:
                d["capex/売上高%"] = capex / rev * 100
        if ocf is not None and capex is not None:
            d["フリーCF"] = ocf - capex
        if op is not None and fincost is not None and fincost != 0:
            d["営業利益/金融費用(倍)"] = op / abs(fincost)
        if rev and inv is not None:
            d["棚卸資産/売上高%"] = inv / rev * 100
        return d

    per = {y: calc(y) for y in years}
    keys = []
    for y in years:
        for k in per[y]:
            if k not in keys:
                keys.append(k)
    order = ["毛利率%", "営業利益率%", "純利益率%", "ROE%", "自己資本比率%",
             "有利子負債", "ネット有利子負債", "ネットD/Eレシオ(倍)", "有利子負債/総資産%",
             "退職給付負債/自己資本%", "営業利益/金融費用(倍)",
             "営業CF/純利益(倍)", "capex", "capex/営業CF%", "capex/売上高%", "フリーCF",
             "棚卸資産/売上高%"]
    keys = [k for k in order if k in keys] + [k for k in keys if k not in order]

    def fmt(v):
        if v is None:
            return ""
        return f"{v:.2f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{round(v):d}"

    out = [["指标"] + years]
    for k in keys:
        out.append([k] + [fmt(per[y].get(k)) for y in years])
    if write:
        with open(os.path.join(HERE, "财务比率.csv"), "w", encoding="utf-8",
                  newline="") as f:
            csv.writer(f).writerows(out)
        print(f"已写出 财务比率.csv：{len(keys)} 项 × {len(years)} 年")
    else:
        for r in out:
            print(",".join(r))


if __name__ == "__main__":
    main()
