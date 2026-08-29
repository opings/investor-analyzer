# -*- coding: utf-8 -*-
"""福耀玻璃 分部营收 + 产销量 → 写 CSV,内置勾稽(产品和=主营合计=国内+国外;对照利润表营收)。

数据血缘:
  - 机器解析 = _extract_json/segments.json(年报 MD&A「主营业务分产品/分地区」表,parse_seg.py 产出)
  - 人工提取 = 下方 MANUAL(2006/2007/2013/2014/2015 机器误抓或跨页断行,已逐行对照年报原文;
    2008-2012 分地区为「国内/北美/亚太」三分口径 → 国外 = 北美+亚太,亦人工录入)
  - 2017/2018 分产品、2017 分地区: 年报「主营业务分行业、分产品、分地区情况的说明 √不适用」
    且附注「分部信息 √不适用」——**该两年公司未披露分产品数据、2017 亦未披露分地区**(实证不可披露,留空)
  - 2006 为旧准则「主营业务收入」口径(≠重述后营业收入 39.35 亿);2013 抵销行原文作「抵消」
  - 产销量表 2015 年报起披露(2015/2016 表头「千吨」按同比链条实证为万吨口径归一,2015 原值 1,117.92 千吨)

口径: 收入/成本 = 元;抵销为负;毛利率 = 1 - 成本/收入(派生)。产销量: 汽玻=百万平方米,浮法=万吨。
"""
import csv
import json
import os
import sys

OUT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(OUT, "_extract_json")
YEARS = list(range(2006, 2026))

with open(os.path.join(SRC, "segments.json"), encoding="utf-8") as f:
    MACH = {int(k): v for k, v in json.load(f).items()}

# (收入, 成本);None=未披露。 抵销缺失时由 合计-(汽玻+浮法+其他) 派生。
MANUAL = {
    2006: {"汽车玻璃": (2888932685, 1832481075), "浮法玻璃": (1643491890, 1366802921),
           "其他": None, "抵销": (-648438314, -648438314), "合计": (3883986261, 2550845682),
           "国内": 2771116952, "国外": 1112869309},  # 国外=北美 556,758,822+亚太 556,110,487
    2007: {"汽车玻璃": (3554025844, 2289386634), "浮法玻璃": (2075186735, 1591353040),
           "其他": (160832425, 130610072), "抵销": (-830809591, -830809591),
           "合计": (4959235413, 3180540155),
           "国内": 3500825296, "国外": 1458410117},  # 北美 545,161,420+亚太 913,248,697
    2008: {"国内": 3898725594, "国外": 1717495702},  # 北美 662,666,429+亚太 1,054,829,273
    2009: {"国内": 4245223812, "国外": 1661368117},  # 北美 746,768,173+亚太 914,599,944
    2010: {"国内": 6004665134, "国外": 2360838437},  # 北美 838,608,925+亚太 1,522,229,512
    2011: {"国内": 6505695227, "国外": 3047029281},  # 北美 976,587,219+亚太 2,070,442,062
    2012: {"国内": 6739925446, "国外": 3330606188},
    2013: {"汽车玻璃": (10912029846, 6943570130), "浮法玻璃": (2238927048, 1687198231),
           "其他": (204356862, 133245935), "抵销": (-2079193222, -2079193222),
           "合计": (11276120534, 6684821074), "国内": 7609307642, "国外": 3666812892},
    2014: {"汽车玻璃": (12439376697, 7832729038), "浮法玻璃": (2129747849, 1526956611),
           "其他": (214754526, 142550055), "抵销": (-2127912207, -2127912207),
           "合计": (12655966865, 7374323497), "国内": 8350438760, "国外": 4305528105},
    2015: {"汽车玻璃": (13137756530, 8237716627), "浮法玻璃": (2485240231, 1877414538),
           "其他": (160815336, 92384142), "抵销": (-2511109145, -2511109145),
           "合计": (13272702952, 7696406162),
           "国内": 8795959672, "国外": 4476743280,
           "国内成本": 4956181093, "国外成本": 2740225069},
    2017: {},  # 年报未披露分产品/分地区(√不适用)
    2018: {"无分产品": True, "国内": 11571725502, "国外": 8312113472,
           "国内成本": 6348365851, "国外成本": 5140301233,
           "合计": (19883838974, 11488667084)},  # 2018 年报仅披露分地区,分产品√不适用
}

# 机器误抓「其他」行的年份覆盖(年报原文printed值,勾稽闭合验证)
OTHER_OVERRIDE = {
    2021: (1612900461, 1405097297),
    2024: (4004143315, 3014379757),
}

# 产销量(2015 起披露;2015/2016 浮法千吨→万吨归一)
VOLUMES = {
    2015: {"汽玻": (92.98, 92.01, 10.11), "浮法": (111.79, 104.40, 26.59)},
    2016: {"汽玻": (107.21, 105.93, 11.90), "浮法": (117.82, 114.97, 21.15)},
    2017: {"汽玻": (112.64, 112.64, 11.88), "浮法": (114.23, 110.11, 23.49)},
    2018: {"汽玻": (116.80, 117.66, 10.84), "浮法": (134.50, 118.83, 38.32)},
}


def get(year):
    """整合机器+人工 → {产品: (收,成), 合计, 国内, 国外, 国内成本, 国外成本}"""
    out = {}
    man = MANUAL.get(year)
    if man is not None and ("汽车玻璃" in man or "无分产品" in man or not man):
        d = man
        if not d:
            return {}
        for k in ("汽车玻璃", "浮法玻璃", "其他", "抵销", "合计"):
            out[k] = d.get(k)
        for k in ("国内", "国外", "国内成本", "国外成本"):
            if k in d:
                out[k] = d[k]
        return out
    m = MACH.get(year, {}).get("营收成本", {})
    for k in ("汽车玻璃", "浮法玻璃", "其他"):
        v = m.get(k)
        out[k] = tuple(v[:2]) if v and len(v) >= 2 else (tuple(v + [None]) if v else None)
    if year in OTHER_OVERRIDE:
        out["其他"] = OTHER_OVERRIDE[year]
    v = m.get("减:集团内部抵销")
    out["抵销"] = tuple(v[:2]) if v else None
    v = m.get("产品·合计") or m.get("地区·合计")
    out["合计"] = tuple(v[:2]) if v else None
    if "地区·国内" in m:
        out["国内"] = m["地区·国内"][0]
        out["国内成本"] = m["地区·国内"][1] if len(m["地区·国内"]) > 1 else None
    if "地区·国外" in m:
        out["国外"] = m["地区·国外"][0]
        out["国外成本"] = m["地区·国外"][1] if len(m["地区·国外"]) > 1 else None
    if man:  # 机器年补人工地区(2008-2012)
        for k in ("国内", "国外", "国内成本", "国外成本"):
            if k in man:
                out[k] = man[k]
    return out


DATA = {y: get(y) for y in YEARS}

# 抵销缺失 → 派生
for y, d in DATA.items():
    if not d or not d.get("合计"):
        continue
    if d.get("抵销") is None and d.get("汽车玻璃") and d.get("浮法玻璃"):
        srev = d["汽车玻璃"][0] + d["浮法玻璃"][0] + (d["其他"][0] if d.get("其他") else 0)
        scost = (d["汽车玻璃"][1] or 0) + (d["浮法玻璃"][1] or 0) + ((d["其他"][1] or 0) if d.get("其他") else 0)
        d["抵销"] = (d["合计"][0] - srev, d["合计"][1] - scost)

# ── 勾稽
ERR = []
for y, d in DATA.items():
    if not d or not d.get("合计"):
        continue
    tot_r, tot_c = d["合计"]
    if d.get("汽车玻璃") and d.get("浮法玻璃") and d.get("抵销"):
        sr = d["汽车玻璃"][0] + d["浮法玻璃"][0] + (d["其他"][0] if d.get("其他") else 0) + d["抵销"][0]
        if abs(sr - tot_r) > 2:
            ERR.append(f"[{y}] 产品收入和 {sr:,.0f} ≠ 合计 {tot_r:,.0f}")
        if tot_c is not None and d["汽车玻璃"][1] is not None:
            sc = d["汽车玻璃"][1] + d["浮法玻璃"][1] + ((d["其他"][1] or 0) if d.get("其他") else 0) + d["抵销"][1]
            if abs(sc - tot_c) > 2:
                ERR.append(f"[{y}] 产品成本和 {sc:,.0f} ≠ 合计 {tot_c:,.0f}")
    if d.get("国内") is not None and d.get("国外") is not None:
        if abs(d["国内"] + d["国外"] - tot_r) > 2:
            ERR.append(f"[{y}] 国内+国外 {d['国内']+d['国外']:,.0f} ≠ 合计 {tot_r:,.0f}")

# 对照利润表营收(主营合计应 ≤ 营收且差距小)
with open(os.path.join(OUT, "利润表.csv"), encoding="utf-8-sig") as f:
    rows = list(csv.reader(f))
rev_row = next(r for r in rows if r[0] == "营业收入")
hdr = rows[0][1:]
REV = {int(h): (float(v) if v else None) for h, v in zip(hdr, rev_row[1:])}
for y, d in DATA.items():
    if not d or not d.get("合计"):
        continue
    rev = REV.get(y)
    if rev:
        gap = rev - d["合计"][0]
        if y == 2006:
            continue  # 旧准则主营口径,已知差异
        if gap < -2 or gap / rev > 0.06:
            ERR.append(f"[{y}] 主营合计 {d['合计'][0]:,.0f} vs 营收 {rev:,.0f} 差 {gap/rev*100:.1f}%")

if ERR:
    print("❌ 分部勾稽未通过,不写出:")
    for e in ERR:
        print("   " + e)
    sys.exit(1)
print("✅ 分部勾稽通过(产品和=合计=国内+国外·对照营收)")


def w(v):
    return "" if v is None else v


def gm(rc):
    if not rc or rc[0] in (None, 0) or rc[1] is None:
        return None
    return round((1 - rc[1] / rc[0]) * 100, 2)


path = os.path.join(OUT, "分部营收.csv")
with open(path, "w", encoding="utf-8-sig", newline="") as f:
    cw = csv.writer(f)
    cw.writerow(["科目"] + [str(y) for y in YEARS])
    rows_def = [
        ("汽车玻璃收入", lambda d: d.get("汽车玻璃", (None,))[0] if d.get("汽车玻璃") else None),
        ("汽车玻璃成本", lambda d: d.get("汽车玻璃", (None, None))[1] if d.get("汽车玻璃") else None),
        ("汽车玻璃毛利率(%)", lambda d: gm(d.get("汽车玻璃"))),
        ("浮法玻璃收入", lambda d: d.get("浮法玻璃", (None,))[0] if d.get("浮法玻璃") else None),
        ("浮法玻璃成本", lambda d: d.get("浮法玻璃", (None, None))[1] if d.get("浮法玻璃") else None),
        ("浮法玻璃毛利率(%)", lambda d: gm(d.get("浮法玻璃"))),
        ("其他收入", lambda d: d.get("其他", (None,))[0] if d.get("其他") else None),
        ("其他成本", lambda d: d.get("其他", (None, None))[1] if d.get("其他") else None),
        ("集团内部抵销收入", lambda d: d.get("抵销", (None,))[0] if d.get("抵销") else None),
        ("主营合计收入", lambda d: d.get("合计", (None,))[0] if d.get("合计") else None),
        ("主营合计成本", lambda d: d.get("合计", (None, None))[1] if d.get("合计") else None),
        ("主营合计毛利率(%)", lambda d: gm(d.get("合计"))),
        ("国内收入", lambda d: d.get("国内")),
        ("国外收入", lambda d: d.get("国外")),
        ("国外收入占比(%)", lambda d: round(d["国外"] / d["合计"][0] * 100, 2)
            if d.get("国外") is not None and d.get("合计") else None),
        ("国内成本", lambda d: d.get("国内成本")),
        ("国外成本", lambda d: d.get("国外成本")),
        ("国内毛利率(%)", lambda d: round((1 - d["国内成本"] / d["国内"]) * 100, 2)
            if d.get("国内成本") is not None and d.get("国内") else None),
        ("国外毛利率(%)", lambda d: round((1 - d["国外成本"] / d["国外"]) * 100, 2)
            if d.get("国外成本") is not None and d.get("国外") else None),
    ]
    for name, fn in rows_def:
        cw.writerow([name] + [w(fn(DATA[y])) for y in YEARS])
print(f"  ✅ 分部营收.csv ({len(rows_def)} 行 × {len(YEARS)} 年)")

# ── 产销量.csv(2015 起)
VY = [y for y in YEARS if y >= 2015]
vol = dict(VOLUMES)
for y in VY:
    if y in vol:
        continue
    mv = MACH.get(y, {}).get("产销量", {})
    if mv:
        vol[y] = {"汽玻": (mv["汽车玻璃"]["产量"], mv["汽车玻璃"]["销量"], mv["汽车玻璃"]["库存"]),
                  "浮法": (mv["浮法玻璃"]["产量"], mv["浮法玻璃"]["销量"], mv["浮法玻璃"]["库存"])}
path = os.path.join(OUT, "产销量.csv")
with open(path, "w", encoding="utf-8-sig", newline="") as f:
    cw = csv.writer(f)
    cw.writerow(["科目"] + [str(y) for y in VY])
    for name, prod, idx in [("汽车玻璃产量(百万平方米)", "汽玻", 0), ("汽车玻璃销量(百万平方米)", "汽玻", 1),
                            ("汽车玻璃库存量(百万平方米)", "汽玻", 2), ("浮法玻璃产量(万吨)", "浮法", 0),
                            ("浮法玻璃销量(万吨)", "浮法", 1), ("浮法玻璃库存量(万吨)", "浮法", 2)]:
        cw.writerow([name] + [vol[y][prod][idx] if y in vol else "" for y in VY])
    # 分析派生指标回流: 汽玻均价 = 分部汽玻收入 ÷ 销量(百万平米);库存/销量比(sell-in 雷达)
    asp_row, inv_row = [], []
    for y in VY:
        d = DATA.get(y, {})
        rev = d.get("汽车玻璃", (None,))[0] if d.get("汽车玻璃") else None
        if y in vol and rev:
            asp_row.append(round(rev / (vol[y]["汽玻"][1] * 1e6), 2))
            inv_row.append(round(vol[y]["汽玻"][2] / vol[y]["汽玻"][1] * 100, 2))
        else:
            asp_row.append("")
            inv_row.append(round(vol[y]["汽玻"][2] / vol[y]["汽玻"][1] * 100, 2) if y in vol else "")
    cw.writerow(["汽车玻璃均价(元/平方米·派生=分部收入÷销量)"] + asp_row)
    cw.writerow(["汽车玻璃库存/销量(%·派生)"] + inv_row)
print(f"  ✅ 产销量.csv (8 行 × {len(VY)} 年·2015 年报起披露·含派生均价/库存销量比)")
