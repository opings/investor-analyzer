#!/usr/bin/env python3
"""google PP&E 明细构建器 → PPE明细.csv(在建工程 = 模板列出的重资产「藏雷点」必查项)

真源:各年自家 10-K「Property and Equipment」附注表的**本年列**(as-reported);2026-06-30 / 09-30 取 2026Q2 / Q3 10-Q。
单位:百万美元。

列报口径两代(FY2024 10-K 起换表):
  旧(FY2012-FY2023 10-K):土地及建筑 / IT 资产 / 在建工程 / 租赁改良 / 家具 → 原值合计 → 减累计折旧 → 净额
  新(FY2024 10-K 起):技术基础设施 / 办公空间 / 公司及其他 → 在用资产 → 减累计折旧 → **加尚未投入使用资产** → 净额
  FY2024 10-K 用新口径回溯重列了 2023(本表单列一列「2023(新口径重列)」作衔接,两口径原值相等已勾稽)。
  ⚠️「尚未投入使用资产」≈ 旧口径「在建工程」,但新口径按「是否已可供使用」划分(含组装中的服务器),非逐项同义。

校验(任一不过 → 不写出):
  P1 分项和 = 原值合计(旧)/ 在用资产合计(新)
  P2 原值 − 累计折旧 = 净额(旧);在用 − 累计折旧 + 尚未投入使用 = 净额(新)
  P3 净额 = 资产负债表.csv 同年「物业及设备净额」(2026-06-30 / 09-30 对 中期财务-2026.csv 资产负债表段,按表头取列)
  P4 2023 两口径衔接:新口径(在用 + 尚未投入使用)= 旧口径原值合计
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "PPE明细.csv")

# ---- 旧口径(各年自家 10-K 本年列) ----
OLD = {  # 年: (土地及建筑, IT资产, 在建工程, 租赁改良, 家具, 原值合计, 累计折旧, 净额)
    2012: (6257, 7717, 2240, 1409, 74, 17697, 5843, 11854),
    2013: (7488, 9094, 5602, 1576, 77, 23837, 7313, 16524),
    2014: (13326, 10918, 6555, 1868, 79, 32746, 8863, 23883),
    2015: (16518, 13645, 7324, 2576, 83, 40146, 11130, 29016),
    2016: (19804, 16084, 8166, 3415, 58, 47527, 13293, 34234),
    2017: (23183, 21429, 10491, 4496, 48, 59647, 17264, 42383),
    2018: (30179, 30119, 16838, 5310, 61, 82507, 22788, 59719),
    2019: (39865, 36840, 21036, 6310, 156, 104207, 30561, 73646),
    2020: (49732, 45906, 23111, 7516, 197, 126462, 41713, 84749),
    2021: (58881, 55606, 23171, 9146, 208, 147012, 49414, 97599),
    2022: (66897, 66267, 27657, 10575, 314, 171710, 59042, 112668),
    2023: (74083, 80594, 35229, 11425, 472, 201803, 67458, 134345),
}
# ---- 新口径(FY2024 10-K 起本年列;"2023R" = FY2024 10-K 对 2023 的回溯重列;"2026H1" / "2026Q3" = 2026Q2 / Q3 10-Q) ----
NEW = {  # 期: (技术基础设施, 办公空间, 公司及其他, 在用合计, 累计折旧, 尚未投入使用, 净额)
    "2023R": (112504, 40435, 13728, 166667, 67458, 35136, 134345),
    "2024": (139596, 43714, 16519, 199829, 79390, 50597, 171036),
    "2025": (203679, 48348, 14463, 266490, 98485, 78592, 246597),
    "2026H1": (247177, 50635, 6498, 304310, 105912, 122814, 321212),
    "2026Q3": (282842, 51101, 7157, 341100, 113543, 145270, 372827),
}
INTERIM_COLS = {"2026H1": "2026-06-30", "2026Q3": "2026-09-30"}  # NEW 键 → 中期财务-2026.csv 资产负债表段列名


def _row_vals(path, label_prefix, header_row=1):
    with open(path, encoding="utf-8") as f:
        rr = list(csv.reader(f))
    for i, r in enumerate(rr):
        if r and r[0].startswith(label_prefix):
            hdr = rr[header_row] if header_row is not None else None
            return hdr, r
    return None, None


FAIL = []


def chk(tag, resid):
    # 原表为百万取整、各行独立舍入,合计与分项可差 ±1~2。实例:FY2021 10-K 原值 147,012 − 累计折旧 49,414 = 97,598,
    # 原表净额印 97,599;FY2022 10-K 回溯重列时把 2021 在建工程改为 23,172、原值改为 147,013 抹平。本表保留当年原表数
    if abs(resid) > 2:
        FAIL.append(f"{tag}: 残差 {resid}")


# P1/P2
for y, (lb, it, cip, lhi, ff, gross, acc, net) in OLD.items():
    chk(f"{y} P1 旧口径分项和=原值", lb + it + cip + lhi + ff - gross)
    chk(f"{y} P2 原值−累计折旧=净额", gross - acc - net)
for p, (ti, off, corp, ins, acc, nyis, net) in NEW.items():
    chk(f"{p} P1 新口径分项和=在用合计", ti + off + corp - ins)
    chk(f"{p} P2 在用−累计折旧+尚未投入使用=净额", ins - acc + nyis - net)
# P4 衔接
chk("2023 P4 新口径(在用+尚未投入使用)=旧口径原值", NEW["2023R"][3] + NEW["2023R"][5] - OLD[2023][5])
chk("2023 P4 两口径累计折旧一致", NEW["2023R"][4] - OLD[2023][6])
# P3 对资产负债表(链式读取 → 必需值完整性自检,防表头偏移致静默全空)
hdr, row = _row_vals(os.path.join(HERE, "资产负债表.csv"), "物业及设备净额")
if row is None:
    FAIL.append("P3 资产负债表.csv 找不到「物业及设备净额」行(行名变了?)")
else:
    bs = {int(hdr[i]): float(row[i]) for i in range(1, len(hdr)) if i < len(row) and row[i] and hdr[i].isdigit()}
    need = list(OLD) + [2024, 2025]
    miss = [y for y in need if y not in bs]
    if miss:
        FAIL.append(f"P3 资产负债表.csv 缺年份 {miss}")
    for y in OLD:
        if y in bs:
            chk(f"{y} P3 净额=资产负债表", OLD[y][7] - bs[y])
    for y in (2024, 2025):
        if y in bs:
            chk(f"{y} P3 净额=资产负债表", NEW[str(y)][6] - bs[y])
with open(os.path.join(HERE, "中期财务-2026.csv"), encoding="utf-8") as f:
    mid_rows = list(csv.reader(f))
mid = None
for i, r in enumerate(mid_rows):
    if r and r[0].startswith("固定资产净额"):
        for j in range(i, -1, -1):   # 向上找本段表头(以【开头),按列名取值,不靠列序号
            if mid_rows[j] and mid_rows[j][0].startswith("【"):
                mid = dict(zip(mid_rows[j][1:], r[1:]))
                break
        break
if mid is None:
    FAIL.append("P3 中期财务-2026.csv 找不到「固定资产净额」行或其段表头")
else:
    for key, col in INTERIM_COLS.items():
        if not mid.get(col):
            FAIL.append(f"P3 中期财务-2026.csv 资产负债表段缺列 {col}")
        else:
            chk(f"{key} P3 净额=中期资产负债表({col})", NEW[key][6] - float(mid[col]))

n_chk = len(OLD) * 2 + len(NEW) * 2 + 2 + len(OLD) + 2 + len(INTERIM_COLS)
print(f"PPE 明细校验 {n_chk} 条,不通过 {len(FAIL)}")
if FAIL:
    for x in FAIL:
        print("  🔴", x)
    if "--force" not in sys.argv:
        print("不写出 PPE明细.csv")
        sys.exit(1)

# ---- 写出 ----
cols = [str(y) for y in OLD] + ["2023(新口径重列)", "2024", "2025", "2026-06-30", "2026-09-30"]
ncol = {"2023(新口径重列)": "2023R", "2024": "2024", "2025": "2025", "2026-06-30": "2026H1", "2026-09-30": "2026Q3"}


def old_line(name, idx):
    return [name] + [str(OLD[y][idx]) for y in OLD] + [""] * (len(cols) - len(OLD))


def new_line(name, idx):
    return [name] + [""] * len(OLD) + [str(NEW[ncol[c]][idx]) for c in cols[len(OLD):]]


def ratio_line(name, f):
    vals = []
    for c in cols:
        if c.isdigit() and int(c) in OLD:
            v = OLD[int(c)]
            vals.append(f"{v[2] / v[7]:.4f}" if f == "cip_net" else f"{v[2] / v[5]:.4f}")
        else:
            v = NEW[ncol[c]]
            vals.append(f"{v[5] / v[6]:.4f}" if f == "cip_net" else f"{v[5] / (v[3] + v[5]):.4f}")
    return [name] + vals


with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["# 单位: 百万美元; 真源: 各年自家 10-K「Property and Equipment」附注本年列(as-reported) + 2026Q2 / Q3 10-Q; "
                "FY2024 10-K 起换列报口径(见 _build_ppe.py 文档串);「2023(新口径重列)」列 = FY2024 10-K 对 2023 的回溯重列,供跨口径衔接; "
                "⚠️ FY2025 10-K 又把 2024 在用资产的三分项重新归类(技术基础设施 141,852 / 办公 45,403 / 公司及其他 12,574,合计不变),本表 2024 列取 FY2024 10-K 原表; "
                "2026-06-30「公司及其他」骤降主因 GFiber 待剥离:约 71 亿美元 PP&E 转入持有待售(计入其他流动资产)、停止折旧(2026Q2 10-Q;"
                "2026Q3 10-Q 同述,预计 2026 年底交割); 2026Q3 10-Q:9/30 技术基础设施中仍约六成为服务器与网络设备"])
    w.writerow(["科目"] + cols)
    w.writerow(["【旧口径·FY2012-FY2023 10-K】"] + [""] * len(cols))
    for i, nm in enumerate(["土地及建筑 Land and buildings", "IT 资产 Information technology assets",
                            "在建工程 Construction in progress", "租赁改良 Leasehold improvements",
                            "家具 Furniture and fixtures", "=原值合计 Property and equipment, gross",
                            "减:累计折旧 Accumulated depreciation", "=净额 Property and equipment, net"]):
        w.writerow(old_line(nm, i))
    w.writerow(["【新口径·FY2024 10-K 起】"] + [""] * len(cols))
    for i, nm in enumerate(["技术基础设施 Technical infrastructure(FY2025 10-K:约六成为服务器与网络设备)",
                            "办公空间 Office space", "公司及其他 Corporate and other assets",
                            "=在用资产 Property and equipment, in service", "减:累计折旧 Accumulated depreciation",
                            "加:尚未投入使用 Assets not yet in service", "=净额 Property and equipment, net"]):
        w.writerow(new_line(nm, i))
    w.writerow(["【派生】"] + [""] * len(cols))
    w.writerow(ratio_line("在建(旧)/尚未投入使用(新) ÷ 净额 —— 已付钱、未开始折旧的部分占比", "cip_net"))
    w.writerow(ratio_line("在建(旧)/尚未投入使用(新) ÷ 原值(新口径=在用+尚未投入使用)", "cip_gross"))
    # 会计估计变更:折旧年限两度延长(各年 10-K「Use of Estimates」原文;变更前 服务器 3 年→2021 起 4 年→2023 起 6 年,
    # 部分网络设备 3 年→2021 起 5 年→2023 起 6 年;FY2025 10-K 与 2026Q2 10-Q 未再调整)
    w.writerow(["【会计估计变更·折旧年限(FY2021 / FY2023 10-K 原文)】"] + [""] * len(cols))
    EST = {"服务器估计使用年限·变更后(年)": {2021: 4, 2023: 6},
           "部分网络设备估计使用年限·变更后(年)": {2021: 5, 2023: 6},
           "变更当年减少折旧(百万美元)": {2021: 2600, 2023: 3900},
           "变更当年增加净利(百万美元)": {2021: 2000, 2023: 3000}}
    for nm, d in EST.items():
        w.writerow([nm] + [str(d[int(c)]) if c.isdigit() and int(c) in d else "" for c in cols])
print("✅ 已写出 PPE明细.csv")
