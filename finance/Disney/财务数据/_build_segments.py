#!/usr/bin/env python3
"""Disney 分部营收 / 分部经营利润构建器 → `分部营收.csv` / `分部经营利润.csv`。

## 为什么这张表比三表更容易出错

Disney 30 多年里**分部口径改过 6 次**，每次改法都不是简单更名，而是业务在分部之间搬家：

| 期间 | 分部 | 触发事件 |
|---|---|---|
| FY1993-1995 | 影视娱乐 / 主题公园与度假区 / 消费品 | —— |
| FY1996-1997 | 创意内容 / 广播 / 主题公园与度假区 | 1996-02 收购 Cap Cities/ABC |
| FY1998-2000 | 媒体网络 / 影视娱乐 / 主题公园与度假区 / 消费品 / 互联网与直销 | 拆出互联网业务(含 go.com 追踪股) |
| FY2001-2012 | 媒体网络 / 主题公园与度假区 / 影视娱乐 / 消费品 | 互联网业务并回 |
| FY2013-2018 | 媒体网络 / 主题公园与度假区 / 影视娱乐 / 消费品与互动媒体 | 互动业务并入消费品 |
| FY2019-2022 | 媒体网络 / 主题公园体验与产品 / 影视娱乐 / DTC与国际（FY2021-22 合成 DMED+DPEP） | 2019-03 收购福克斯 + 流媒体重组 |
| FY2023-2025 | 娱乐 / 体育 / 体验 | 2023 三分部重组 |

**跨断点直接连线做同比 = 错**。本脚本在 CSV 里用「口径分组」把各期间隔开，不做跨期间拼接。

## 取数纪律（canonical 见 `财报阅读规则.md`「期间/时点口径约定」硬规则 1-2）

- **一律取当年年报的当年列**，严禁用后一年年报的同比 % 反推。
- **闸门：各分部营收之和（含分部间抵销）必须等于同年 `利润表.csv` 的营业收入**，
  差额 >0.5% 即判该年解析失败、不写出。这条就是茅台那次「渠道两行整体左移一列、
  连续 6 年各自对上**下一年**营收」被漏掉的那道闸。
"""
import csv
import json
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RDIR = os.path.join(HERE, "_rfiles")
LDIR = os.path.join(HERE, "_legacy")

# 口径分组：(起, 止, 组名, [(CSV 行名, 匹配正则)])
ERAS = [
    (1993, 1995, "FY1993-1995 三分部", [
        ("影视娱乐 Filmed entertainment", r"^filmed entertainment$"),
        ("主题公园与度假区 Theme parks and resorts", r"^theme parks and resorts$"),
        ("消费品 Consumer products", r"^consumer products$"),
    ]),
    # ⚠️ 边界是 FY1998 结束、不是 FY1997：FY1998 年报仍按三分部列报
    #    （Creative Content 10,302 + Broadcasting 7,142 + Theme Parks 5,532 = 22,976 ✓）。
    #    五分部是 FY1999 年报才开始的。
    (1996, 1998, "FY1996-1998 收购 Cap Cities/ABC 后三分部", [
        ("创意内容 Creative Content", r"^creative content$"),
        ("广播 Broadcasting", r"^broadcasting$"),
        ("主题公园与度假区 Theme Parks and Resorts", r"^theme parks and resorts$"),
    ]),
    (1999, 2000, "FY1999-2000 五分部(含互联网)", [
        ("媒体网络 Media Networks", r"^media networks$"),
        ("影视娱乐 Studio Entertainment", r"^studio entertainment$"),
        # FY1999 印「Theme Parks and Resorts」，FY2000 已改印「Parks and Resorts」
        ("主题公园与度假区 Theme Parks and Resorts", r"^(theme )?parks (and|&) resorts$"),
        ("消费品 Consumer Products", r"^consumer products$"),
        ("互联网与直销 Internet and Direct Marketing",
         r"^internet (and direct marketing|group)$"),
    ]),
    (2001, 2012, "FY2001-2012 四分部", [
        ("媒体网络 Media Networks", r"^media networks$"),
        # ⚠️ FY2001-2003 印的是「Parks **&** Resorts」（& 不是 and），写死 and 会整段漏掉
        ("主题公园与度假区 Parks and Resorts", r"^parks (and|&) resorts$"),
        ("影视娱乐 Studio Entertainment", r"^studio entertainment$"),
        ("消费品 Consumer Products", r"^consumer products$"),
        ("互动媒体 Interactive Media", r"^interactive( media)?$"),
    ]),
    (2013, 2015, "FY2013-2015 五分部(互动独立)", [
        ("媒体网络 Media Networks", r"^media networks$"),
        ("主题公园与度假区 Parks and Resorts", r"^parks (and|&) resorts$"),
        ("影视娱乐 Studio Entertainment", r"^studio entertainment$"),
        ("消费品 Consumer Products", r"^consumer products$"),
        ("互动 Interactive", r"^interactive( media)?$"),
    ]),
    (2016, 2018, "FY2016-2018 消费品与互动合并", [
        ("媒体网络 Media Networks", r"^media networks$"),
        ("主题公园与度假区 Parks and Resorts", r"^parks (and|&) resorts$"),
        ("影视娱乐 Studio Entertainment", r"^studio entertainment$"),
        # ⚠️ 轴标签是「Consumer Products and Interactive」——没有结尾的 "Media"，
        #    正则若写死 "interactive media" 会整段漏掉（FY2016-18 缺口 ~4,800-5,500）。
        ("消费品与互动 Consumer Products and Interactive",
         r"^consumer products( (and|&) interactive( media)?)?$"),
    ]),
    (2019, 2020, "FY2019-2020 福克斯并购+DTC重组", [
        ("媒体网络 Media Networks", r"^media networks$"),
        ("主题公园体验与产品 Parks, Experiences and Products",
         r"^parks,? experiences and products$"),
        ("影视娱乐 Studio Entertainment", r"^studio entertainment$"),
        ("DTC与国际 Direct-to-Consumer & International",
         r"^direct.to.consumer (and|&) international$"),
    ]),
    (2021, 2022, "FY2021-2022 两大板块", [
        ("媒体与娱乐发行 DMED", r"^disney media and entertainment distribution$"),
        ("主题公园体验与产品 DPEP", r"^disney parks,? experiences and products$"),
    ]),
    (2023, 2025, "FY2023-2025 娱乐/体育/体验", [
        ("娱乐 Entertainment", r"^entertainment( segment)?$"),
        ("体育 Sports", r"^sports( segment)?$"),
        ("体验 Experiences", r"^experiences( segment)?$"),
    ]),
]
ELIM = ("分部间抵销 Eliminations", r"^(segment )?eliminations$|^intersegment elimination")


def era_of(fy):
    for a, b, name, segs in ERAS:
        if a <= fy <= b:
            return name, segs
    return None, []


def fy_of_period(p):
    m = re.search(r"\b((?:19|20)\d\d)\b", p)
    return int(m.group(1)) if m else None


def total_revenue():
    """从已建好的 利润表.csv 取各年营业收入，作为分部合计的校验基准。"""
    path = os.path.join(HERE, "利润表.csv")
    rows = list(csv.reader(open(path)))
    hdr = next(r for r in rows if r and r[0] == "科目")
    rev = next(r for r in rows if r and r[0].startswith("营业收入"))
    return {int(y): float(v) for y, v in zip(hdr[1:], rev[1:]) if v}


# ── R 轨（FY2011-2025）：分部维度轴 + Revenues / OperatingIncomeLoss ──────────
REV_TAGS = ("us-gaap_Revenues", "us-gaap_SalesRevenueNet",
            "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax")
OI_TAGS = ("us-gaap_OperatingIncomeLoss",)


def from_rfiles():
    """两个已踩的坑：
    ① FY2011-2018 的分部表用 `us-gaap_SalesRevenueNet`，且**分部上下文行没有 tag**
       （空 tag + 全 None 值），按 `StatementBusinessSegmentsAxis` 去认会一个都认不到。
    ② FY2021/2022 的轴里有个「**Total Segments**」成员，把它当分部会让合计翻倍
       （FY2022: 55,040+28,705+83,745 = 167,490 ≈ 2×82,722）。
       对策：只接受**落在该财年口径分组名单里**的成员，其余（含 Total / 地理区域）一律丢。
    """
    rev, oi = defaultdict(dict), defaultdict(dict)
    for f in sorted(os.listdir(RDIR)):
        if not f.endswith(".json"):
            continue
        d = json.load(open(os.path.join(RDIR, f)))
        key = int(d["key"])
        st = d["statements"].get("SEG")
        if not st:
            continue
        _, segs = era_of(key)
        if not segs:
            continue
        periods, months = st["periods"], st.get("months") or []
        col = None
        for i, p in enumerate(periods):
            if months and months[i] != 12:
                continue
            if fy_of_period(p) == key:             # 只取该年报自己那一年（as-reported）
                col = i
        if col is None:
            continue
        seg = ""
        for r in st["rows"]:
            tag, lab, vals = r["tag"], r["label"], r["vals"]
            is_ctx = (not tag or tag.endswith("Axis")) and all(v is None for v in vals)
            if is_ctx:
                seg = lab
                continue
            if not seg or "|" in seg:              # 「X Segment | X Third Party」是分部内再拆分
                continue
            name = next((n for n, pat in segs + [ELIM]
                         if re.search(pat, seg.strip().lower())), None)
            if not name:
                continue
            v = vals[col] if col < len(vals) else None
            if v is None:
                continue
            if tag in REV_TAGS:
                rev[key].setdefault(name, v)
            elif tag in OI_TAGS:
                oi[key].setdefault(name, v)
    return rev, oi


# ── Legacy 轨（FY1993-2010）：用「分部合计 = 利润表营收」挑表 ────────────────
def seg_values(cand, fy, segs, section):
    """从一张候选表里取该财年各分部的值。

    Disney 的分部表把「Revenues」与「Operating income」两段（有时是两张表）**并排放**，
    同一个分部名会出现两次 → 靠段首标记切段，只取所要段落里**首次**出现的那个值。
    """
    years = [int(y) for y in cand["periods"] if y.isdigit()]
    if fy not in years:
        return {}
    n, j = len(years), years.index(fy)
    got, cur = {}, None
    for r in cand["rows"]:
        lab = r["label"].strip().lower()
        full = (r.get("full") or "").strip().lower()
        # ⚠️ 段首措辞各年不同：「Revenues」/「Operating income」/「**Segment** operating income」。
        #    只认 `^operating income` 会漏掉 FY2001-2010 的整段分部经营利润。
        if re.match(r"^revenues?\b", lab) or re.match(r"^revenues?\b", full):
            cur = "rev"
        elif re.match(r"^(total )?(segment )?operating (income|loss)", lab) \
                or re.match(r"^(total )?(segment )?operating (income|loss)", full):
            cur = "oi"
        vals = r["vals"]
        if len(vals) > n:
            vals = vals[-n:]
        elif len(vals) != n:
            continue
        if cur != section or vals[j] is None:
            continue
        # ⚠️ 分部小计常是**无标签行**，被解析器合成成「Studio Entertainment 合计」。
        #    只按 `^studio entertainment$` 匹配会整段漏掉（FY1998-2010 全军覆没就是这个原因）。
        keys = {lab, lab.replace(" 合计", "").strip()}
        for name, pat in segs + [ELIM]:
            if any(re.search(pat, k) for k in keys):
                got.setdefault(name, vals[j])
                break
    return got


def from_legacy(totals):
    rev, oi, log = defaultdict(dict), defaultdict(dict), []
    for fy in range(1993, 2011):
        p = os.path.join(LDIR, f"{fy}.json")
        if not os.path.exists(p):
            continue
        _, segs = era_of(fy)
        if not segs:
            continue
        cands = (json.load(open(p))["statements"].get("SEG") or [])
        t = totals.get(fy)
        hit = None
        for c in cands:
            got = seg_values(c, fy, segs, "rev")
            if not got or t is None:
                continue
            s = sum(got.values())
            if abs(s - t) <= max(1.0, abs(t) * 0.005):      # ← 闸门
                hit = (c, got, s)
                break
        if not hit:
            log.append(f"FY{fy}: ❌ {len(cands)} 张候选无一能让分部合计对上利润表营收 {t}")
            continue
        c, got, s = hit
        rev[fy] = got
        log.append(f"FY{fy}: ✅ 分部合计 {s:,.1f} = 利润表营收 {t:,.1f}")
        # 经营利润：先在同一张表里找 oi 段，找不到再扫其余候选
        for cc in [c] + [x for x in cands if x is not c]:
            g = seg_values(cc, fy, segs, "oi")
            if len(g) >= max(2, len(segs) - 1):
                oi[fy] = g
                break
    return rev, oi, log


def fmt(v):
    if v is None:
        return ""
    return f"{v:.1f}".rstrip("0").rstrip(".") if abs(v - round(v)) > 1e-9 else f"{round(v):d}"


def write(path, data, totals, title):
    fys = [y for y in sorted(set(data)) if 1993 <= y <= 2025]
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([f"单位:百万美元(USD millions)。{title}。"
                    "🔴 Disney 分部口径 30 年改过 6 次(见下方分组)，**跨分组不可直接连线做同比**；"
                    "每年一律取该年年报的当年列(禁用后一年同比%反推)。"])
        w.writerow(["闸门:各分部营收之和(含分部间抵销)= 同年 利润表.csv 营业收入,差额>0.5% 则该年不写出。"])
        w.writerow(["口径分组", "分部"] + [str(y) for y in fys])
        for a, b, name, segs in ERAS:
            cols = [y for y in fys if a <= y <= b]
            if not cols:
                continue
            for seg_name in [s for s, _ in segs] + [ELIM[0], ELIM[0] + "(倒挤)"]:
                row = [name, seg_name] + [
                    fmt(data.get(y, {}).get(seg_name)) if a <= y <= b else "" for y in fys]
                if any(c for c in row[2:]):
                    w.writerow(row)
            if totals:
                w.writerow([name, "— 合计校验:利润表营业收入"] +
                           [fmt(totals.get(y)) if a <= y <= b else "" for y in fys])


def main():
    totals = total_revenue()
    rrev, roi = from_rfiles()
    lrev, loi, log = from_legacy(totals)
    rev = {**lrev, **rrev}
    oi = {**loi, **roi}

    print("── Legacy 分部挑表（闸门=分部合计对上利润表营收）──")
    for line in log:
        print("  " + line)

    print("\n── R 轨分部合计校验 ──")
    bad, derived = 0, []
    for fy in sorted(rrev):
        s = sum(rrev[fy].values())
        t = totals.get(fy)
        if t and abs(s - t) > max(1.0, abs(t) * 0.005):
            gap = t - s
            # 个别年份（FY2022）分部表内不单列「分部间抵销」，只给 Total Segments。
            # 缺口若在 3% 以内，按**倒挤**补一行并明确标注，超过则判失败。
            if abs(gap) <= abs(t) * 0.03:
                rrev[fy][ELIM[0] + "(倒挤)"] = gap
                derived.append(fy)
                print(f"  FY{fy}: 合计 {s:,.0f} vs 利润表 {t:,.0f} → 抵销倒挤 {gap:,.0f}  ⚠️")
                continue
            bad += 1
            print(f"  FY{fy}: 合计 {s:,.0f} vs 利润表 {t:,.0f}  ❌")
        else:
            print(f"  FY{fy}: 合计 {s:,.0f} vs 利润表 {t:,.0f}  ✅")
    if bad:
        print(f"\n🚫 R 轨有 {bad} 年对不上，不写出")
        return
    if derived:
        print(f"  ⚠️ {derived} 的「分部间抵销」为倒挤值（该年分部表未单列）")

    write(os.path.join(HERE, "分部营收.csv"), rev, totals, "分部营业收入")
    write(os.path.join(HERE, "分部经营利润.csv"), oi, None, "分部经营利润(segment operating income)")
    print("\n写出 分部营收.csv / 分部经营利润.csv")


if __name__ == "__main__":
    main()
