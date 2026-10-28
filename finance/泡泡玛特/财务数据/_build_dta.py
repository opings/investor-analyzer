# -*- coding: utf-8 -*-
"""泡泡玛特(09992.HK) 递延所得税 + 所得税税率对账 → 写 递延所得税资产构成.csv / 所得税税率对账.csv。

为什么单列: 2025 年递延所得税资产由 1.47 亿跳到 17.54 亿(`资产负债表.csv`), 2026-07 版分析挂了「追附注 ⏳」;
2026-10 拆现金含量时发现它和 2026H1 多付的税是同一件事的两头(`经营现金流拆解.csv` ④), 需要看它的来由、
对冲项、收回期限和未确认部分。

数据来源: report/泡泡玛特/泡泡玛特-2025.pdf
  - 附注 19(a) 递延所得税资产构成 + 按收回期限(P316); 变动表(P317), 其「於 2024 年 1 月 1 日」= 本表 2023 列;
    未确认递延所得税资产的税项亏损(P317 变动表下正文)
  - 附注 19(b) 递延所得税负债构成(P318); 变动表(P319), 同样含 2023 列
  - 附注 11 所得税开支与中国内地法定税率 25% 的对账(P289)

⚠️ 附注 19(P317)「未确认递延所得税资产」一句中英文都把 2025 年两个数印反了: 写「累计税项亏损 13,525,000 元、
   递延所得税资产 54,101,000 元」, 递延税比亏损还大不可能。同句 2024 年是亏损 580,000 元 → 递延税 145,000 元(25%),
   附注 11 对账表「未确认递延所得税资产的税项亏损」2025 年正是 13,525 千元 → 本表按「亏损 54,101 / 递延税 13,525」入库。

勾稽(容差 0, 空值跳过并计数):
  - 资产构成: 各项加总 = 总值; 总值 + 抵销 = 净额 = 年度资产负债表「递延所得税资产」(从年度构建脚本内存表取, 不读 CSV)
  - 负债构成: 各项加总 = 总额; 总额 + 抵销 = 年度资产负债表「递延所得税负债」(空 = 0); 两边抵销额相等
  - 变动表: 期初 + 计入损益 = 期末(逐项、逐年); 资产计入 − 负债扣除 = 年度资产负债表(资产 − 负债)净额变动
  - 收回期限: 12 个月内 + 超过 12 个月 = 净额
  - 未确认: 亏损 × 25%(四舍五入)= 未确认递延税; 2025 年 = 附注 11 对账表同名行
  - 税率对账: 税前 × 25%(四舍五入)= 按适用税率计算的税项; 各项加总 = 税收费用; 税前 / 税收费用 = 年度损益表
  - `--mutate` 逐格 +1 重跑全部勾稽, 报被捕获比例
"""
import csv
import importlib.util
import os
import sys

OUT = os.path.dirname(os.path.abspath(__file__))
YEARS = [2023, 2024, 2025]  # 2023 = 附注 19 变动表「於 2024 年 1 月 1 日」
资产项 = ["租赁负债", "税项亏损", "减值亏损", "集团间销售未变现溢利", "应计开支及其他"]
负债项 = ["使用权资产", "金融资产投资公允价值变动"]

# ====== 附注 19(a) 递延所得税资产(P316 构成 · P317 变动表期初) ======
资产构成 = [
    ("租赁负债", [194438, 241140, 729438]),
    ("税项亏损", [56725, 40163, 14842]),
    ("减值亏损", [6762, 11292, 18524]),
    ("集团间销售未变现溢利", [0, 86201, 1602765]),  # 2023 原文为「–」
    ("应计开支及其他", [8260, 16017, 103258]),
    ("递延所得税资产总值", [266185, 394813, 2468827]),
    ("抵销递延所得税负债", [-182769, -247784, -715276]),  # 2023 = 负债变动表使用权资产期初数(年报未印抵销额)
    ("递延所得税资产净额", [83416, 147029, 1753551]),
]
# ====== 附注 19(b) 递延所得税负债(P318 构成 · P319 变动表期初) ======
负债构成 = [
    ("使用权资产", [182769, 231889, 711343]),
    ("金融资产投资公允价值变动", [14419, 15895, 3933]),
    ("递延所得税负债总额", [197188, 247784, 715276]),
]
# ====== 变动表: 计入 / (扣除) 损益, 2024 与 2025 两年(P317 · P319) ======
变动_年份 = [2024, 2025]
资产变动 = [  # 计入损益为正
    ("减值亏损", [4530, 7232]),
    ("税项亏损", [-16562, -25321]),
    ("租赁负债", [46702, 488298]),
    ("应计开支及其他", [7757, 87241]),
    ("集团间销售未变现溢利", [86201, 1516564]),
    ("总计", [128628, 2074014]),
]
负债变动 = [  # 扣除损益为正
    ("使用权资产", [49120, 479454]),
    ("金融资产投资公允价值变动", [1476, -11962]),
    ("总计", [50596, 467492]),
]
# ====== 净额按收回期限(P316), 2024 与 2025 ======
收回期限 = [
    ("12 个月内收回", [121900, 1720614]),
    ("超过 12 个月后收回", [25129, 32937]),
]
# ====== 未确认递延所得税资产的累计税项亏损(P317 正文; 2025 年两数按印反订正), 2024 与 2025 ======
未确认 = [
    ("累计税项亏损", [580, 54101]),
    ("未确认的递延所得税资产", [145, 13525]),
]
# ====== 附注 11 所得税开支与 25% 法定税率的对账(P289), 2024 与 2025 ======
税率对账_年份 = [2024, 2025]
税率对账 = [
    ("除所得税前溢利", [4365812, 17036622]),
    ("按适用税率 25% 计算的税项", [1091453, 4259156]),
    ("其他司法权区不同税率的影响", [-14228, -239166]),
    ("未确认递延所得税资产的税项亏损", [144, 13525]),
    ("分占以权益法入账的投资的税项影响", [-12047, -17413]),
    ("不可扣税开支", [41253, 19662]),
    ("无须课税收入", [-49108, -11184]),
    ("税收费用", [1057467, 4024580]),
]

_年度模块 = None


def annual_module():
    """载入年度构建脚本(只取其内存中的表, 不读它写出的 CSV)。"""
    global _年度模块
    if _年度模块 is None:
        spec = importlib.util.spec_from_file_location("popmart_annual_build", os.path.join(OUT, "_build_from_pdf.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _年度模块 = mod
    return _年度模块


def annual(table_name, prefix, year):
    mod = annual_module()
    hits = [vals for k, vals in getattr(mod, table_name) if k.startswith(prefix + " ")]
    if len(hits) != 1:
        raise KeyError(f"年度{table_name}找不到唯一的「{prefix}」行 (命中 {len(hits)})")
    return hits[0][mod.YEARS.index(year)]


def row(block, key):
    for k, vals in block:
        if k == key:
            return vals
    raise KeyError(f"无此行: {key}")


def half_up_quarter(x):
    """x × 25% 四舍五入到整数(千元)。"""
    return (x * 25 + 50) // 100


# ====== 勾稽 (容差 0 · 空值计数) ======
def check():
    errors = []
    stats = {"executed": 0, "skipped": 0}

    def eq(label, a, b):
        if a is None or b is None:
            stats["skipped"] += 1
            return
        stats["executed"] += 1
        if a != b:
            errors.append(f"{label}: {a} vs {b} (差 {a - b:+})")

    a_total, a_off, a_net = row(资产构成, "递延所得税资产总值"), row(资产构成, "抵销递延所得税负债"), row(资产构成, "递延所得税资产净额")
    l_total = row(负债构成, "递延所得税负债总额")
    for i, y in enumerate(YEARS):
        eq(f"[{y}] 资产: 各项加总 = 总值", sum(row(资产构成, k)[i] for k in 资产项), a_total[i])
        eq(f"[{y}] 资产: 总值 + 抵销 = 净额", a_total[i] + a_off[i], a_net[i])
        eq(f"[{y}] 资产: 净额 = 年度资产负债表", a_net[i], annual("资产负债表", "递延所得税资产", y))
        eq(f"[{y}] 负债: 各项加总 = 总额", sum(row(负债构成, k)[i] for k in 负债项), l_total[i])
        eq(f"[{y}] 负债: 总额 + 抵销 = 年度资产负债表(空 = 0)",
           l_total[i] + a_off[i], annual("资产负债表", "递延所得税负债", y) or 0)

    for i, y in enumerate(变动_年份):
        j = YEARS.index(y)
        for k in 资产项:
            eq(f"[{y}] 资产变动 {k}: 期初 + 计入 = 期末", row(资产构成, k)[j - 1] + row(资产变动, k)[i], row(资产构成, k)[j])
        eq(f"[{y}] 资产变动: 各项加总 = 总计", sum(row(资产变动, k)[i] for k in 资产项), row(资产变动, "总计")[i])
        for k in 负债项:
            eq(f"[{y}] 负债变动 {k}: 期初 + 扣除 = 期末", row(负债构成, k)[j - 1] + row(负债变动, k)[i], row(负债构成, k)[j])
        eq(f"[{y}] 负债变动: 各项加总 = 总计", sum(row(负债变动, k)[i] for k in 负债项), row(负债变动, "总计")[i])
        bs_net = lambda yy: annual("资产负债表", "递延所得税资产", yy) - (annual("资产负债表", "递延所得税负债", yy) or 0)
        eq(f"[{y}] 资产计入 − 负债扣除 = 年度资产负债表净额变动",
           row(资产变动, "总计")[i] - row(负债变动, "总计")[i], bs_net(y) - bs_net(y - 1))
        eq(f"[{y}] 收回期限: 12 个月内 + 超过 12 个月 = 净额", sum(v[i] for _, v in 收回期限), a_net[j])
        eq(f"[{y}] 未确认: 亏损 × 25% = 递延税", half_up_quarter(row(未确认, "累计税项亏损")[i]), row(未确认, "未确认的递延所得税资产")[i])
    eq("[2025] 未确认递延税 = 附注 11 对账表同名行",
       row(未确认, "未确认的递延所得税资产")[变动_年份.index(2025)], row(税率对账, "未确认递延所得税资产的税项亏损")[税率对账_年份.index(2025)])

    for i, y in enumerate(税率对账_年份):
        pbt = row(税率对账, "除所得税前溢利")[i]
        eq(f"[{y}] 对账: 税前 × 25% = 按适用税率计算的税项", half_up_quarter(pbt), row(税率对账, "按适用税率 25% 计算的税项")[i])
        eq(f"[{y}] 对账: 各项加总 = 税收费用", sum(v[i] for _, v in 税率对账[1:-1]), row(税率对账, "税收费用")[i])
        eq(f"[{y}] 对账: 税前 = 年度损益表", pbt, annual("利润表", "除所得税前溢利", y))
        eq(f"[{y}] 对账: 税收费用 = 年度损益表所得税开支", row(税率对账, "税收费用")[i], -annual("利润表", "所得税开支", y))
    return errors, stats


# ====== 变异对照: 逐格 +1 看勾稽能否抓到 ======
def mutation_test():
    targets = []
    for bname, block, years in (("资产构成", 资产构成, YEARS), ("负债构成", 负债构成, YEARS), ("资产变动", 资产变动, 变动_年份),
                                ("负债变动", 负债变动, 变动_年份), ("收回期限", 收回期限, 变动_年份), ("未确认", 未确认, 变动_年份),
                                ("税率对账", 税率对账, 税率对账_年份)):
        for k, vals in block:
            targets += [(f"{bname} · {k}", y, vals, i) for i, y in enumerate(years) if vals[i] is not None]
    caught, missed = 0, []
    for name, y, holder, i in targets:
        original = holder[i]
        holder[i] = original + 1
        errors, _ = check()
        holder[i] = original
        if errors:
            caught += 1
        else:
            missed.append(f"{name} · {y}")
    print(f"变异对照: 共 {len(targets)} 个转录格逐格 +1, 被勾稽捕获 {caught} 个 ({caught / len(targets):.1%}), 未覆盖 {len(missed)} 个")
    for m in missed:
        print(f"  未覆盖: {m}")


# ====== 写出 ======
def pct(a, b):
    return "" if a is None or not b else round(a / b * 100, 1)


def write_dta_csv():
    a_total, a_net = row(资产构成, "递延所得税资产总值"), row(资产构成, "递延所得税资产净额")
    with open(os.path.join(OUT, "递延所得税资产构成.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["# 泡泡玛特 递延所得税资产构成 · 单位: 人民币千元 · 来源: 2025 年报附注 19(资产构成 P316 · 资产变动 P317 · 负债构成 P318 · 负债变动 P319) · 构建: _build_dta.py"])
        w.writerow(["# 2023 列 = 变动表「於 2024 年 1 月 1 日」;「集团间销售未变现溢利」2023 原文为「–」;2023 抵销额年报未印·取负债变动表使用权资产期初数·与年度资产负债表 2023 年末对平"])
        w.writerow(["# 2026 中报只披露净额(`资产负债表-H1.csv`)·不拆项"])
        w.writerow(["=== ① 递延所得税资产构成(抵销前) ==="])
        w.writerow(["科目"] + [str(y) for y in YEARS] + ["2025 占总值%"])
        for k, vals in 资产构成:
            share = pct(vals[-1], a_total[-1]) if k not in ("抵销递延所得税负债", "递延所得税资产净额") else ""
            w.writerow([k] + vals + [share])
        w.writerow(["=== ② 递延所得税负债构成(全部或大部分与资产抵销) ==="])
        w.writerow(["科目"] + [str(y) for y in YEARS])
        for k, vals in 负债构成:
            w.writerow([k] + vals)
        w.writerow(["递延所得税负债净额(资产负债表单列)"] + [row(负债构成, "递延所得税负债总额")[i] + row(资产构成, "抵销递延所得税负债")[i]
                                              for i in range(len(YEARS))])
        w.writerow(["=== ③ 年内计入 / (扣除) 损益 ==="])
        w.writerow(["科目"] + [str(y) for y in 变动_年份])
        for k, vals in 资产变动:
            w.writerow([f"资产·{k}"] + vals)
        for k, vals in 负债变动:
            w.writerow([f"负债·{k}"] + vals)
        w.writerow(["=== ④ 净额按收回期限(公司划分) ==="])
        w.writerow(["科目"] + [str(y) for y in 变动_年份])
        for k, vals in 收回期限:
            w.writerow([k] + vals)
        w.writerow(["=== ⑤ 未确认递延所得税资产的累计税项亏损(P317 正文·2025 年两数原文印反·已按 25% 比例与附注 11 订正) ==="])
        w.writerow(["科目"] + [str(y) for y in 变动_年份])
        for k, vals in 未确认:
            w.writerow([k] + vals)
        w.writerow(["=== ⑥ 派生 ==="])
        w.writerow(["科目"] + [str(y) for y in YEARS])
        w.writerow(["集团间销售未变现溢利 ÷ 递延所得税资产净额 %"] + [pct(row(资产构成, "集团间销售未变现溢利")[i], a_net[i]) for i in range(len(YEARS))])
        w.writerow(["租赁相关净额(租赁负债 − 使用权资产)"] + [row(资产构成, "租赁负债")[i] - row(负债构成, "使用权资产")[i] for i in range(len(YEARS))])


def write_rate_csv():
    pbt = row(税率对账, "除所得税前溢利")
    with open(os.path.join(OUT, "所得税税率对账.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["# 泡泡玛特 所得税开支与中国内地法定税率 25% 的对账 · 单位: 人民币千元 · 来源: 2025 年报附注 11(P289) · 构建: _build_dta.py"])
        w.writerow(["# 附注 11 另述: 已按第二支柱(全球最低税)规则作出若干即期所得税拨备·未单列金额"])
        w.writerow(["科目"] + [str(y) for y in 税率对账_年份] + ["2025 占税前溢利%"])
        for k, vals in 税率对账:
            share = pct(vals[-1], pbt[-1]) if k != "除所得税前溢利" else ""
            w.writerow([k] + vals + [share])
        w.writerow(["实际税率%(税收费用 ÷ 税前)"] + [round(row(税率对账, "税收费用")[i] / pbt[i] * 100, 2) for i in range(len(税率对账_年份))] + [""])


def main():
    if "--mutate" in sys.argv:
        mutation_test()
        return
    errors, stats = check()
    if errors:
        print("❌ 递延所得税 / 税率对账勾稽失败, 不写出 CSV:")
        for e in errors:
            print(f"  {e}")
        return
    write_dta_csv()
    write_rate_csv()
    print(f"✅ 递延所得税 / 税率对账勾稽全部通过: 执行 {stats['executed']} 条, 跳过 {stats['skipped']} 条 (容差 0); "
          f"已写出 递延所得税资产构成.csv / 所得税税率对账.csv")


if __name__ == "__main__":
    main()
