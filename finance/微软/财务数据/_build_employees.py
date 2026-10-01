#!/usr/bin/env python3
"""员工人数序列：FY1982-1993 取年报五年摘要（`_scans/*.json` 的 Number of employees 行，**按最新一份覆盖该年的
年报**取——五年摘要会被后一年改印的只有拆股/重分类类项目，员工数不受影响，仍逐年互核），
FY1994 起取各年 10-K 正文 Item 1「As of June 30, YYYY, we employed approximately N people」句。

校验：①FY1994-2026 每份 10-K 都必须抓到恰好一个「截至该财年 6 月 30 日」的员工数；
②扫描件五年摘要里同一年被多份年报印出时必须一致；③10-K 句子里的日期年份必须等于该份申报的财年
（防止抓到「As of June 30, 2025」这类比较句）。
"""
import csv
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
REPORT = os.path.join(ROOT, "report", "微软")
SDIR = os.path.join(HERE, "_scans")

PAT = re.compile(r"(?:as of|at) june 30,? ((?:19|20)\d\d),? (?:we|microsoft|the company) (?:employed|had) "
                 r"(?:approximately |a total of |about )?([\d,]+) (?:full-time )?(?:people|employees|persons)", re.I)


def text_of(fy):
    p = os.path.join(REPORT, f"{fy}.txt" if fy <= 2001 else f"{fy}.htm")
    raw = open(p, encoding="latin-1", errors="ignore").read()
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw)).replace("\xa0", " "))


def main():
    emp, src, bad = {}, {}, []
    # 1) 扫描件五年摘要
    seen = {}
    for name in sorted(os.listdir(SDIR)):
        d = json.load(open(os.path.join(SDIR, name)))
        st = d["statements"].get("SUM")
        if not st:
            continue
        for r in st["rows"]:
            if re.match(r"number of employees", r["label"], re.I):
                for y, v in zip(st["years"], r["vals"]):
                    if v is not None:
                        seen.setdefault(y, []).append((v, name))
    for y, lst in sorted(seen.items()):
        vals = {v for v, _ in lst}
        if len(vals) > 1:
            bad.append(f"FY{y} 五年摘要多份年报所印员工数不一致：{lst}")
        last = sorted(lst, key=lambda x: x[1])[-1]
        emp[y], src[y] = last[0], f"{last[1].replace('.json', '')}年报五年摘要"
    # 2) 10-K 正文
    for fy in range(1994, 2027):
        t = text_of(fy)
        hits = [(int(m.group(1)), int(m.group(2).replace(",", ""))) for m in PAT.finditer(t)]
        own = sorted({h for h in hits if h[0] == fy})
        if len(own) != 1:
            bad.append(f"FY{fy} 10-K 员工句命中 {own}（全部命中 {hits[:4]}）")
            continue
        emp[fy], src[fy] = own[0][1], f"FY{fy} 10-K Item 1"
    for fy in sorted(emp):
        if fy <= 1993 and fy not in seen:
            bad.append(f"FY{fy} 缺")
    if bad:
        print("🔴 员工数校验未过：")
        for b in bad:
            print("  " + b)
        if "--force" not in sys.argv:
            return 1
    years = sorted(emp)
    with open(os.path.join(HERE, "员工人数.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# 单位: 人 | 时点 = 财年末 6 月 30 日 | FY1982-1993 取年报五年摘要（多份年报互核一致）、"
                    "FY1994 起取 10-K Item 1 自陈句 | 公司自陈「approximately」约数"])
        w.writerow(["科目"] + [f"FY{y}" for y in years])
        w.writerow(["数据来源"] + [src[y] for y in years])
        w.writerow(["员工人数 Employees"] + [str(int(emp[y])) for y in years])
    print(f"✅ 员工人数 FY{years[0]}-FY{years[-1]} 共 {len(years)} 年")
    return 0


if __name__ == "__main__":
    sys.exit(main())
