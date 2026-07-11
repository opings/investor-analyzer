#!/usr/bin/env python3
"""google 分部/收入拆分 —— 从一手 10-K MD&A 收入明细 + 分部附注转录。

口径演变(故分段覆盖):
- 收入按类型 2017-2025: FY2019 10-K(2017-19) + FY2022 10-K(2020-22) + FY2025 10-K(2023-25)。
  2017-19 "Google other" == 2020-22 同名 == 2023-25 "订阅/平台/设备"(仅更名);
  2017-19 "Network Members' properties" == 2020+ "Google Network"。
- 分部经营利润 Services/Cloud/Other Bets 三分 2020 起(FY2022/FY2025 10-K);2017-19 为 Google+Other Bets 两分,未并入。
- 2016 及以前 = 单一 Google 广告段(websites/Network/Other),口径不同,未并入(见 README)。
单位:百万美元(与三表一致·10-K 原样)。勾稽:收入分项合计=总收入;分部经营利润合计=总经营利润。
"""
import csv
import os

DIR = os.path.dirname(os.path.abspath(__file__))
RY = list(range(2017, 2026))   # 收入按类型
OY = list(range(2020, 2026))   # 分部经营利润

# 收入按类型(百万美元)
REV = [
    ("Google搜索及其他 Search & other", {2017: 69811, 2018: 85296, 2019: 98115, 2020: 104062, 2021: 148951, 2022: 162450, 2023: 175033, 2024: 198084, 2025: 224532}),
    ("YouTube广告 YouTube ads", {2017: 8150, 2018: 11155, 2019: 15149, 2020: 19772, 2021: 28845, 2022: 29243, 2023: 31510, 2024: 36147, 2025: 40367}),
    ("Google联盟网络 Network", {2017: 17616, 2018: 20010, 2019: 21547, 2020: 23090, 2021: 31701, 2022: 32780, 2023: 31312, 2024: 30359, 2025: 29792}),
    ("=广告合计 Google advertising", {2017: 95577, 2018: 116461, 2019: 134811, 2020: 146924, 2021: 209497, 2022: 224473, 2023: 237855, 2024: 264590, 2025: 294691}),
    ("订阅/平台/设备 Subscriptions,platforms,devices", {2017: 10914, 2018: 14063, 2019: 17014, 2020: 21711, 2021: 28032, 2022: 29055, 2023: 34688, 2024: 40340, 2025: 48030}),
    ("=Google Services合计 Services total", {2020: 168635, 2021: 237529, 2022: 253528, 2023: 272543, 2024: 304930, 2025: 342721}),
    ("Google Cloud 云", {2017: 4056, 2018: 5838, 2019: 8918, 2020: 13059, 2021: 19206, 2022: 26280, 2023: 33088, 2024: 43229, 2025: 58705}),
    ("Other Bets 其他押注", {2017: 477, 2018: 595, 2019: 659, 2020: 657, 2021: 753, 2022: 1068, 2023: 1527, 2024: 1648, 2025: 1537}),
    ("对冲损益 Hedging gains(losses)", {2017: -169, 2018: -138, 2019: 455, 2020: 176, 2021: 149, 2022: 1960, 2023: 236, 2024: 211, 2025: -127}),
    ("=总收入 Total revenues", {2017: 110855, 2018: 136819, 2019: 161857, 2020: 182527, 2021: 257637, 2022: 282836, 2023: 307394, 2024: 350018, 2025: 402836}),
]
# 分部经营利润(百万美元)
OI = [
    ("Google Services 经营利润", {2020: 54606, 2021: 91855, 2022: 86572, 2023: 95858, 2024: 121263, 2025: 139404}),
    ("Google Cloud 经营利润", {2020: -5607, 2021: -3099, 2022: -2968, 2023: 1716, 2024: 6112, 2025: 13910}),
    ("Other Bets 经营利润", {2020: -4476, 2021: -5281, 2022: -6083, 2023: -4095, 2024: -4444, 2025: -7515}),
    ("公司层未分配 Corporate/Alphabet-level", {2020: -3299, 2021: -4761, 2022: -2679, 2023: -9186, 2024: -10541, 2025: -16760}),
    ("=总经营利润 Total operating income", {2020: 41224, 2021: 78714, 2022: 74842, 2023: 84293, 2024: 112390, 2025: 129039}),
]

d = dict


def g(rows, name, y):
    return d(rows).get(name, {}).get(y)


# ---- 勾稽 ----
print("勾稽: 收入分项合计 = 总收入")
for y in RY:
    parts = (g(REV, "=广告合计 Google advertising", y) + g(REV, "订阅/平台/设备 Subscriptions,platforms,devices", y)
             + g(REV, "Google Cloud 云", y) + g(REV, "Other Bets 其他押注", y) + g(REV, "对冲损益 Hedging gains(losses)", y))
    tot = g(REV, "=总收入 Total revenues", y)
    print(f"  {y}: 分项和 {parts} vs 总收入 {tot} -> {'OK' if parts == tot else '❌差'+str(parts-tot)}")

print("勾稽: 广告三项 = 广告合计")
for y in RY:
    adv = g(REV, "Google搜索及其他 Search & other", y) + g(REV, "YouTube广告 YouTube ads", y) + g(REV, "Google联盟网络 Network", y)
    tot = g(REV, "=广告合计 Google advertising", y)
    print(f"  {y}: {adv} vs {tot} -> {'OK' if adv == tot else '❌'}")

print("勾稽: 分部经营利润合计 = 总经营利润")
for y in OY:
    s = g(OI, "Google Services 经营利润", y) + g(OI, "Google Cloud 经营利润", y) + g(OI, "Other Bets 经营利润", y) + g(OI, "公司层未分配 Corporate/Alphabet-level", y)
    tot = g(OI, "=总经营利润 Total operating income", y)
    print(f"  {y}: {s} vs {tot} -> {'OK' if s == tot else '❌差'+str(s-tot)}")


# ---- 写 CSV ----
def cell(dv, y):
    return "" if y not in dv else str(dv[y])


with open(os.path.join(DIR, "分部营收.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["# 单位: 百万美元(USD millions); 来源: 10-K MD&A收入明细+分部附注(FY2019/FY2022/FY2025); 收入按类型2017-25, 分部经营利润2020-25; 2016及前单一广告段未并入(见README)"])
    w.writerow(["【收入按类型】"] + [str(y) for y in RY])
    for name, dv in REV:
        w.writerow([name] + [cell(dv, y) for y in RY])
    w.writerow([])
    w.writerow(["【分部经营利润】"] + [str(y) for y in OY])
    for name, dv in OI:
        w.writerow([name] + [cell(dv, y) for y in OY])
print("\n✅ 已写出 分部营收.csv")
