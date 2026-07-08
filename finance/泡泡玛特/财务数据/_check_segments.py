# -*- coding: utf-8 -*-
"""泡泡玛特 分部营收.csv 勾稽自查(方案X·当年年报当年列)。
验证四组:①IP(2022-25:Σ艺术家单IP+其他=小计;小计+授权+外采+其他=总计)②区域(两分/四分=总计)
③渠道(全公司/内地/PRC 各口径和=对应总)④线上明细(各年Σ=渠道对应线上)。手工表无构建脚本,本脚本防手误。"""
import csv
import os
import re

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "分部营收.csv")
rows = []
with open(path, encoding="utf-8-sig") as f:
    for line in f:
        rows.append(next(csv.reader([line.rstrip("\n")])))

D = {}
for r in rows:
    if not r or not r[0] or r[0].startswith("#") or r[0].startswith("===") or r[0] in ("IP", "区域", "渠道", "平台", "指标"):
        continue
    vals = []
    for i in range(1, 7):
        c = r[i].strip() if i < len(r) else ""
        m = re.match(r"[-+]?[\d.]+", c)
        vals.append(float(m.group()) if m else None)
    if r[0].strip() not in D:  # 保留第一个同名行(IP块"总计"优先于区域块)
        D[r[0].strip()] = vals


def g(prefix):
    for k, v in D.items():
        if k.startswith(prefix):
            return v
    return [None] * 6


TOL = 1.0
YS = ["2020", "2021", "2022", "2023", "2024", "2025"]
errs = []


def chk(label, a, b, yi):
    if a is None or b is None:
        return
    if abs(a - b) > TOL:
        errs.append(f"{label} {YS[yi]}: {a:.0f} ≠ {b:.0f} (差{a-b:+.0f})")


# ① IP:2022-2025
artist_ips = ["THE MONSTERS", "SKULLPANDA", "MOLLY", "DIMOO", "CRYBABY", "HIRONO",
              "HACIPUPU", "Twinkle", "PINO JELLY", "Zsiga", "Sweet Bean", "PUCKY", "BOBO&COCO", "Bunny"]
sub = g("艺术家IP小计")
other = g("其他艺术家IP")
lic = g("授权IP")
ext = g("外采")
oth = g("其他 Others")
tot = g("总计 Total") if False else g("总计")  # IP区块总计
tot_ip = g("总计")
for yi in range(2, 6):
    s_ip = sum((g(n)[yi] or 0) for n in artist_ips) + (other[yi] or 0)
    chk("IP Σ艺术家=小计", s_ip, sub[yi], yi)
    s_all = (sub[yi] or 0) + (lic[yi] or 0) + (ext[yi] or 0) + (oth[yi] or 0)
    chk("IP 四类=总计", s_all, tot_ip[yi], yi)
# 2020-2021 旧口径:自主产品+外采+其他=总计
selfp = g("自主产品合计")
for yi in (0, 1):
    chk("IP 自主+外采+其他=总计", (selfp[yi] or 0) + (ext[yi] or 0) + (oth[yi] or 0), tot_ip[yi], yi)

# ② 区域
nd = g("中国内地(两分")
hw = g("港澳台及海外")
prc = g("中国PRC含港澳台")
ap = g("亚太")
am = g("美洲")
eu = g("欧洲及其他")
rtot = g("总计 Total")
# 用区域块的总计(第二个"总计")——区域总计与IP总计同值,直接用 tot_ip
for yi in (2, 3, 4):
    chk("区域两分=总计", (nd[yi] or 0) + (hw[yi] or 0), tot_ip[yi], yi)
chk("区域四分=总计", (prc[5] or 0) + (ap[5] or 0) + (am[5] or 0) + (eu[5] or 0), tot_ip[5], 5)

# ③ 渠道
r_ret = g("零售店(全公司")
r_on = g("线上(全公司")
r_robo = g("机器人商店(全公司")
r_ws = g("批发及其他(全公司")
for yi in (0, 1):
    chk("渠道全公司=总计", (r_ret[yi] or 0) + (r_on[yi] or 0) + (r_robo[yi] or 0) + (r_ws[yi] or 0), tot_ip[yi], yi)
nd_off = g("中国内地-线下")
nd_on = g("中国内地-线上")
nd_ws = g("中国内地-批发")
for yi in (2, 3, 4):
    chk("渠道内地=区域内地", (nd_off[yi] or 0) + (nd_on[yi] or 0) + (nd_ws[yi] or 0), nd[yi], yi)
p_ret = g("中国PRC-线下零售")
p_robo = g("中国PRC-线下机器人")
p_on = g("中国PRC-线上")
p_ws = g("中国PRC-批发")
chk("渠道PRC=区域PRC", (p_ret[5] or 0) + (p_robo[5] or 0) + (p_on[5] or 0) + (p_ws[5] or 0), prc[5], 5)

# ④ 线上平台明细 = 对应线上总
plat = ["泡泡玛特抽盒机", "天猫", "京东", "抖音", "其他线上"]
for yi in range(6):
    sp = sum((g(p)[yi] or 0) for p in plat)
    if yi in (0, 1):
        chk("线上明细=全公司线上", sp, r_on[yi], yi)
    elif yi in (2, 3, 4):
        chk("线上明细=内地线上", sp, nd_on[yi], yi)
    else:
        chk("线上明细=PRC线上", sp, p_on[yi], yi)

if errs:
    print("⚠️ 勾稽不通过:")
    for e in errs:
        print("  ✗ " + e)
else:
    print("✅ 泡泡玛特分部营收.csv 全部勾稽通过(IP/区域/渠道/线上明细 · 方案X当年报口径)")
