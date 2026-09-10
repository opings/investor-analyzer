#!/usr/bin/env python3
"""特斯拉固定资产明细构建器 —— 新车型与算力投入的**先行指标**。

为什么单独建这张表
──────────────────────────────────────────────────────────────────
三表只给「固定资产净额」一个数，看不出钱花在哪。而附注明细里有两行直接对应
「下一轮增长的两个启动条件」（公司自陈：autonomy + next generation platform）：
  · **Tooling（模具）** —— 模具是**车型专用**的，新车型投产前必然先资本化模具
    → 交付量下滑而 Tooling 仍高增，只能是为**还没上市的车**花的钱
  · **AI infrastructure** —— 自有数据中心等算力资产，自动驾驶投入的直接度量
  · **Construction in progress（在建工程）** —— 含「AI-related assets **not yet placed in service**」
    → 在建工程转入 Tooling / AI infrastructure 并伴随折旧跳升 = 产线或算力**实际上线**的机械信号

🚨 口径断点 L：AI infrastructure 是 FY2024 才新拆的类别，且**追溯重分类**
──────────────────────────────────────────────────────────────────
FY2023 10-K 无此行；FY2024 10-K 新增该行并把 2023 比较列**重分类了 15.10 亿美元**：
    计算机设备 −1,390 / 机器设备 −63 / 租赁改良 −32 / 模具 −18 / 土地建筑 −7 = **−1,510**
    → AI infrastructure **+1,510**，**毛值合计 41,782 不变**（纯重分类，已逐格核平）
本表按纪律保留 2023 的 **as-reported** 列，另设 `2023*FY2024重列` 列，使 AI infrastructure
序列（2023→2025）可连续使用。**跨年比这两行时必须用重列口径，不能混。**

数据来源：各年 10-K「Property, plant and equipment, net, consisted of the following」附注。
单位统一千美元（附注印刷为百万，×1000）。

校验：① 分项和 = 毛值合计；② 毛值 − 累计折旧 = 净额；
      ③ **净额 = `资产负债表.csv` 的固定资产净额**（跨表交叉核）；④ 重列列的分项和 = 原列毛值合计。
不通过不写出。
"""
from __future__ import annotations

import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
K = 1000  # 百万 → 千美元

# 各年 as-reported（百万美元）：机器设备 / 土地建筑 / AI基建 / 模具 / 租赁改良 / 计算机 / 在建工程 / 毛值 / 累计折旧 / 净额
PPE = {
    2018: (6329, 4047, None, 1398, 961, 487, 807, 14029, 2699, 11330),
    2019: (7167, 3024, None, 1493, 1087, 595, 764, 14130, 3734, 10396),
    2020: (8493, 3662, None, 1811, 1421, 856, 1621, 17864, 5117, 12747),
    2021: (9953, 4675, None, 2188, 1826, 1414, 5559, 25615, 6731, 18884),
    2022: (13558, 7751, None, 2579, 2366, 2072, 4263, 32589, 9041, 23548),
    2023: (16372, 9505, None, 3147, 3168, 3799, 5791, 41782, 12057, 29725),
    2024: (18339, 10677, 5152, 3883, 3688, 2902, 6783, 51424, 15588, 35836),
    2025: (20864, 11837, 6816, 4868, 4439, 3206, 8786, 60816, 20173, 40643),
}
# FY2024 10-K 对 2023 的重列（断点 L）
PPE_2023_RESTATED = (16309, 9498, 1510, 3129, 3136, 2409, 5791, 41782, 12057, 29725)
# 折旧费用（仅固定资产，非全部 D&A）—— 各年附注「Depreciation expense during the years ended…」
DEP_EXPENSE = {2018: 1110, 2019: 1370, 2020: 1570, 2021: 1910, 2022: 2420, 2023: 3330, 2024: 4120, 2025: 5030}

LABELS = ["机器设备/车辆/办公家具 Machinery, equipment, vehicles and office furniture",
          "土地与建筑 Land and buildings",
          "🔑AI 基础设施 AI infrastructure(自有数据中心等·FY2024 新拆)",
          "🔑模具 Tooling(车型专用·新车型先行指标)",
          "租赁改良 Leasehold improvements",
          "计算机设备与软件 Computer equipment, hardware and software",
          "🔑在建工程 Construction in progress(含尚未投用的 AI 资产)",
          "固定资产毛值 Gross PP&E", "减:累计折旧 Accumulated depreciation", "固定资产净额 PP&E, net"]
DERIVED = ["折旧费用(当年) Depreciation expense",
           "—— 派生 ——",
           "模具同比 Tooling YoY", "AI 基础设施同比 AI infrastructure YoY", "在建工程同比 CIP YoY",
           "在建工程÷毛值 CIP / gross PP&E", "累计折旧÷毛值(资产年龄代理) Accum. dep / gross",
           "折旧费用÷毛值 Depreciation / gross"]


def read_bs():
    rows = list(csv.reader(open(os.path.join(HERE, "资产负债表.csv"), encoding="utf-8")))
    cols = rows[2][1:]
    tbl = {r[0]: dict(zip(cols, r[1:])) for r in rows[3:]}
    key = "固定资产净额 Property, plant and equipment, net"
    if key not in tbl:
        return None
    return {int(y): (float(v) if v else None) for y, v in tbl[key].items() if v}


def main():
    bs = read_bs()
    if bs is None:
        print("❌ 资产负债表.csv 表头行号不对：找不到「固定资产净额」行")
        return 1

    errs, nchk = [], 0
    years = sorted(PPE)
    data = {}
    for y in years:
        v = PPE[y]
        d = {LABELS[i]: (None if v[i] is None else v[i] * K) for i in range(10)}
        d["减:累计折旧 Accumulated depreciation"] = v[8] * K   # 表中以正数列示（印刷带括号）
        d["折旧费用(当年) Depreciation expense"] = DEP_EXPENSE.get(y, 0) * K or None
        data[y] = d

        parts = [v[i] for i in range(7) if v[i] is not None]
        nchk += 3
        if sum(parts) != v[7]:
            errs.append(f"[{y}] 分项和 {sum(parts):,} ≠ 毛值合计 {v[7]:,}")
        if v[7] - v[8] != v[9]:
            errs.append(f"[{y}] 毛值−累计折旧 {v[7]-v[8]:,} ≠ 净额 {v[9]:,}")
        if y in bs and bs[y] is not None and abs(v[9] * K - bs[y]) > 1000:
            errs.append(f"[{y}] 附注净额 {v[9]*K:,.0f} ≠ 资产负债表固定资产净额 {bs[y]:,.0f}")

    # 重列列
    r = PPE_2023_RESTATED
    nchk += 2
    if sum(x for x in r[:7] if x is not None) != r[7]:
        errs.append("[2023*重列] 分项和 ≠ 毛值合计")
    if r[7] != PPE[2023][7]:
        errs.append("[2023*重列] 毛值合计与原列不一致 —— 重分类应不改变毛值")
    data["2023*"] = {LABELS[i]: (None if r[i] is None else r[i] * K) for i in range(10)}
    data["2023*"]["减:累计折旧 Accumulated depreciation"] = r[8] * K

    # 派生
    cols = [str(y) for y in years]
    cols.insert(cols.index("2023") + 1, "2023*")
    for i, c in enumerate(cols):
        d = data[int(c) if c != "2023*" else "2023*"]
        gross = d["固定资产毛值 Gross PP&E"]
        for src, dst in (("🔑模具 Tooling(车型专用·新车型先行指标)", "模具同比 Tooling YoY"),
                         ("🔑AI 基础设施 AI infrastructure(自有数据中心等·FY2024 新拆)", "AI 基础设施同比 AI infrastructure YoY"),
                         ("🔑在建工程 Construction in progress(含尚未投用的 AI 资产)", "在建工程同比 CIP YoY")):
            # 同比用「可比口径」：AI/模具在 2024 起对 2023* 重列列比
            prev_c = None
            if c not in ("2023*",) and i > 0:
                prev_c = "2023*" if cols[i - 1] == "2023*" else cols[i - 1]
                if c == "2024":
                    prev_c = "2023*"
            if prev_c:
                pv = data[int(prev_c) if prev_c != "2023*" else "2023*"].get(src)
                cv = d.get(src)
                if pv and cv:
                    d[dst] = cv / pv - 1
        if gross:
            d["在建工程÷毛值 CIP / gross PP&E"] = d["🔑在建工程 Construction in progress(含尚未投用的 AI 资产)"] / gross
            d["累计折旧÷毛值(资产年龄代理) Accum. dep / gross"] = d["减:累计折旧 Accumulated depreciation"] / gross
            if d.get("折旧费用(当年) Depreciation expense"):
                d["折旧费用÷毛值 Depreciation / gross"] = d["折旧费用(当年) Depreciation expense"] / gross

    print(f"── 固定资产明细校验：{nchk} 条，不通过 {len(errs)}")
    for e in errs:
        print("   ✗", e)
    if errs:
        print("\n❌ 校验未过 —— 不写出 CSV。")
        return 1

    def fmt(v):
        if v is None:
            return ""
        return f"{v:.0f}" if abs(v) >= 1000 else f"{v:.4f}"

    with open(os.path.join(HERE, "固定资产明细.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["单位:千美元(附注印刷为百万,×1000);累计折旧以正数列示;比率为倍数(1=100%);空=该年附注无此类别"])
        w.writerow(["🔑 为什么看这张表:Tooling(车型专用模具)=**新车型先行指标**;AI infrastructure=**自动驾驶投入直接度量**;"
                    "在建工程含「尚未投用的 AI 资产」,转固+折旧跳升=产线/算力**实际上线**的机械信号"])
        w.writerow(["🚨 断点 L:AI infrastructure 为 FY2024 新拆类别并**追溯重分类 2023 年 15.10 亿**"
                    "(计算机设备−1,390/机器设备−63/租赁改良−32/模具−18/土地建筑−7,毛值合计不变)。"
                    "本表保留 2023 as-reported,另设 `2023*` 重列列 —— **跨年比 AI 基建与模具必须用 2023* 口径**"])
        w.writerow(["来源:各年 10-K「Property, plant and equipment, net, consisted of the following」附注;"
                    "净额已与 资产负债表.csv 逐年交叉核对"])
        w.writerow(["科目"] + cols)
        for r_ in LABELS + DERIVED:
            if r_.startswith("——"):
                w.writerow([r_])
                continue
            vals = [data[int(c) if c != "2023*" else "2023*"].get(r_) for c in cols]
            if any(v is not None for v in vals):
                w.writerow([r_] + [fmt(v) for v in vals])

    print(f"✅ 固定资产明细.csv 已写出（{cols[0]}-{cols[-1]}，含 2023* 重列列）")
    for y in (2024, 2025):
        d = data[y]
        print(f"   FY{y}: 模具 {d['🔑模具 Tooling(车型专用·新车型先行指标)']/1e6:.2f}十亿({d.get('模具同比 Tooling YoY', 0):+.1%}) | "
              f"AI基建 {d['🔑AI 基础设施 AI infrastructure(自有数据中心等·FY2024 新拆)']/1e6:.2f}十亿"
              f"({d.get('AI 基础设施同比 AI infrastructure YoY', 0):+.1%}) | "
              f"在建工程 {d['🔑在建工程 Construction in progress(含尚未投用的 AI 资产)']/1e6:.2f}十亿"
              f"({d.get('在建工程同比 CIP YoY', 0):+.1%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
