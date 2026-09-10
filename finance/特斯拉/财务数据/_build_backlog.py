#!/usr/bin/env python3
"""特斯拉「在手订单与预收」构建器 —— 前瞻性最强的一张表。

为什么重要
──────────────────────────────────────────────────────────────────
三张报表都是**后视镜**。剩余履约义务（RPO）与客户预付是财报里**唯二指向未来**的硬数字：
  · **能源分部 RPO** —— 储能这条增长曲线还有没有订单支撑
  · **汽车监管积分合约 RPO** —— 占 2025 归母净利 52.5% 的那块政策租金还能收多久

⚠️ 三条口径限制（不读会严重误用）
──────────────────────────────────────────────────────────────────
1. **RPO 只含「原始预期期限 > 1 年」的合约**。公司对 ≤1 年的合约用了实务简化处理不披露，
   所以 **RPO ≠ 全部在手订单**，短期/现货订单完全不在里面。不可当作完整订单簿。
2. **只有金额、没有对应 GWh**。因此**算不出在手订单的隐含单价** —— 这恰恰是判断
   「新签订单是否在降价」最直接的指标，而它从外部无法获得 ⏳。
3. **汽车监管积分 RPO 的披露自 FY2024 才出现**（FY2023 10-K 无此段），故 2023 列为空。

数据来源（全部一手，逐年跨申报核对一致）
──────────────────────────────────────────────────────────────────
各年 10-K 收入确认附注的原文句：
  「total transaction price allocated to performance obligations that were unsatisfied or
   partially unsatisfied for contracts with an original expected length of more than one
   year was $X. Of this amount, we expect to recognize $Y in the next 12 months」
分别出现在**汽车/监管积分**与**能源**两节，靠所在章节区分（两处金额完全不同，勿混）。

校验：未来 12 个月可确认额 ≤ RPO 总额；派生覆盖倍数为正。不通过不写出。
"""
from __future__ import annotations

import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# ── 一手转录（千美元）。每格出处 = 该年 10-K 收入确认附注
# 能源分部 RPO：FY2023 10-K「$3.43 billion / $1.05 billion」；FY2024「$7.18B / $4.51B」；FY2025「$10.42B / $4.96B」
ENERGY_RPO = {2023: 3430000, 2024: 7180000, 2025: 10420000}
ENERGY_RPO_12M = {2023: 1050000, 2024: 4510000, 2025: 4960000}
# 汽车监管积分合约 RPO：FY2024 10-K「$4.68B / $863M」；FY2025「$841M / $738M」（FY2023 10-K 无此段）
REGC_RPO = {2024: 4680000, 2025: 841000}
REGC_RPO_12M = {2024: 863000, 2025: 738000}
# 能源客户预付形成的递延收入（合同付款条款）：各年 10-K 同一附注
ENERGY_DEFREV = {2022: 863000, 2023: 1600000, 2024: 1770000, 2025: 2040000}
# 当年从上年末递延收入余额确认的收入
ENERGY_DEFREV_RECOG = {2023: 571000, 2024: 1270000, 2025: 1450000}
# 能源租赁/PPA 相关递延收入（另一笔，规模小且逐年下降 —— 与 SolarCity 遗留租赁资产退场一致）
ENERGY_LEASE_DEFREV = {2022: 191000, 2023: 181000, 2024: 164000, 2025: 151000}

YEARS = [2022, 2023, 2024, 2025]

ROWS = [
    "【能源】RPO 剩余履约义务(>1年期合约)",
    "【能源】其中:未来12个月预计确认",
    "【能源】客户预付形成的递延收入",
    "【能源】当年自上年末递延收入余额确认的收入",
    "【能源】租赁/PPA 递延收入(SolarCity 遗留·逐年退场)",
    "【汽车】监管积分合约 RPO(>1年期)",
    "【汽车】其中:未来12个月预计确认",
    "—— 派生 ——",
    "【能源】RPO ÷ 当年能源分部收入(订单覆盖倍数)",
    "【能源】未来12个月可确认额 ÷ 当年能源收入(次年可见度)",
    "【能源】RPO 同比",
    "【汽车】监管积分 RPO ÷ 当年监管积分收入",
    "【汽车】监管积分 RPO 同比",
]


def read_csv(name, hdr):
    rows = list(csv.reader(open(os.path.join(HERE, name), encoding="utf-8")))
    cols = rows[hdr][1:]
    return {r[0]: dict(zip(cols, r[1:])) for r in rows[hdr + 1:]}


def num(tbl, key, col):
    s = tbl.get(key, {}).get(col, "")
    return float(s) if s not in ("", None) else None


def main():
    seg = read_csv("分部营收.csv", 3)
    pol = read_csv("政策补贴与积分.csv", 6)
    for nm, tbl, probe in (("分部营收.csv", seg, "能源发电与储存 Energy generation and storage"),
                           ("政策补贴与积分.csv", pol, "【收入侧】汽车监管积分收入 Automotive regulatory credits (revenue)")):
        if probe not in tbl:
            print(f"❌ {nm} 表头行号(hdr)不对：找不到探针行「{probe}」")
            return 1

    data, errs, nchk = {}, [], 0
    for y in YEARS:
        d = {}
        d["【能源】RPO 剩余履约义务(>1年期合约)"] = ENERGY_RPO.get(y)
        d["【能源】其中:未来12个月预计确认"] = ENERGY_RPO_12M.get(y)
        d["【能源】客户预付形成的递延收入"] = ENERGY_DEFREV.get(y)
        d["【能源】当年自上年末递延收入余额确认的收入"] = ENERGY_DEFREV_RECOG.get(y)
        d["【能源】租赁/PPA 递延收入(SolarCity 遗留·逐年退场)"] = ENERGY_LEASE_DEFREV.get(y)
        d["【汽车】监管积分合约 RPO(>1年期)"] = REGC_RPO.get(y)
        d["【汽车】其中:未来12个月预计确认"] = REGC_RPO_12M.get(y)

        erev = num(seg, "能源发电与储存 Energy generation and storage", str(y))
        rc = num(pol, "【收入侧】汽车监管积分收入 Automotive regulatory credits (revenue)", str(y))
        rpo, rpo12 = ENERGY_RPO.get(y), ENERGY_RPO_12M.get(y)
        if rpo and erev:
            d["【能源】RPO ÷ 当年能源分部收入(订单覆盖倍数)"] = rpo / erev
        if rpo12 and erev:
            d["【能源】未来12个月可确认额 ÷ 当年能源收入(次年可见度)"] = rpo12 / erev
        if rpo and ENERGY_RPO.get(y - 1):
            d["【能源】RPO 同比"] = rpo / ENERGY_RPO[y - 1] - 1
        if REGC_RPO.get(y) and rc:
            d["【汽车】监管积分 RPO ÷ 当年监管积分收入"] = REGC_RPO[y] / rc
        if REGC_RPO.get(y) and REGC_RPO.get(y - 1):
            d["【汽车】监管积分 RPO 同比"] = REGC_RPO[y] / REGC_RPO[y - 1] - 1
        data[y] = d

        # 校验：未来 12 个月可确认额不得超过 RPO 总额
        for tag, tot, part in (("能源", rpo, rpo12), ("汽车监管积分", REGC_RPO.get(y), REGC_RPO_12M.get(y))):
            if tot and part:
                nchk += 1
                if part > tot:
                    errs.append(f"[{y}] {tag} 未来12个月 {part:,.0f} > RPO 总额 {tot:,.0f}")

    # 完整性自检
    MUST = {"【能源】RPO 剩余履约义务(>1年期合约)": (2023, 2024, 2025),
            "【能源】RPO ÷ 当年能源分部收入(订单覆盖倍数)": (2023, 2024, 2025),
            "【汽车】监管积分合约 RPO(>1年期)": (2024, 2025),
            "【汽车】监管积分 RPO ÷ 当年监管积分收入": (2024, 2025)}
    missing = [f"{r}@{y}" for r, ys in MUST.items() for y in ys if data.get(y, {}).get(r) is None]
    if missing:
        print(f"❌ 完整性自检未过：{len(missing)} 个必需值为空")
        for m in missing:
            print("   ✗", m)
        return 1
    nchk += sum(len(v) for v in MUST.values())

    print(f"── 在手订单表校验：{nchk} 条（含完整性自检），不通过 {len(errs)}")
    for e in errs:
        print("   ✗", e)
    if errs:
        return 1

    def fmt(v):
        if v is None:
            return ""
        return f"{v:.4f}" if abs(v) < 100 else f"{v:.0f}"

    with open(os.path.join(HERE, "在手订单与预收.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["单位:金额千美元;倍数与同比为倍数(1=100%);空=该年一手申报未披露"])
        w.writerow(["🔑 三张报表都是后视镜,本表是财报里**唯二指向未来**的硬数字(RPO + 客户预付)"])
        w.writerow(["⚠️ 口径限制:① RPO **只含原始预期期限>1年的合约**(≤1年公司用实务简化不披露)→ **不是完整订单簿**;"
                    "② **只有金额、无对应 GWh** → **算不出在手订单隐含单价**(判断新签单是否降价的最直接指标,外部不可得 ⏳);"
                    "③ 汽车监管积分 RPO 的披露自 FY2024 才出现,2023 无"])
        w.writerow(["来源:各年 10-K 收入确认附注原文「…for contracts with an original expected length of more than "
                    "one year was $X. Of this amount, we expect to recognize $Y in the next 12 months」;"
                    "汽车与能源两节各有一处、金额不同,勿混。逐年跨申报核对一致"])
        w.writerow(["科目"] + [str(y) for y in YEARS])
        for r in ROWS:
            if r.startswith("——"):
                w.writerow([r])
                continue
            vals = [data.get(y, {}).get(r) for y in YEARS]
            if any(v is not None for v in vals):
                w.writerow([r] + [fmt(v) for v in vals])
    print("✅ 在手订单与预收.csv 已写出（2022-2025）")
    print(f"   能源 RPO：{ENERGY_RPO[2023]/1e6:.2f} → {ENERGY_RPO[2024]/1e6:.2f} → {ENERGY_RPO[2025]/1e6:.2f} 十亿美元")
    print(f"   汽车监管积分 RPO：{REGC_RPO[2024]/1e6:.2f} → {REGC_RPO[2025]/1e6:.2f} 十亿美元 "
          f"（{REGC_RPO[2025]/REGC_RPO[2024]-1:+.1%}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
