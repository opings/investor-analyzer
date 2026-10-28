# -*- coding: utf-8 -*-
"""泡泡玛特(09992.HK) 净利 → 经营现金流 拆解 → 写 经营现金流拆解.csv, 内置勾稽(容差 0)。

为什么单列: 现金含量 2025 全年 0.84、2026H1 0.71(`财务比率.csv` `财务比率-H1.csv`), 只看这一个比值
分不出差额是营运资金(存货)还是税的时间差。拆成三段:
  净利 →(+所得税开支) 除所得税前溢利 →(+非现金调整 +营运资金变动) 经营所得现金 →(+已收利息 +已付所得税) 经营现金流
「税前现金含量」= 经营所得现金 ÷ 除所得税前溢利, 不受交税时点影响。

数据来源:
  ① 2024 / 2025「除所得税前溢利 → 经营所得现金」对账 ← report/泡泡玛特/泡泡玛特-2025.pdf 附注 34(a)(P342);
     中报没有这张对账表, H1 只能拆到「税前一段 / 税」
  ②③ 三段序列(年度 2017-2025、H1 2020H1-2026H1)← 年度 / H1 构建脚本的内存表(不读它们写出的 CSV)
  ④ 税的时间差 ← 同上两脚本的损益、现金流与资产负债表(即期所得税负债、递延所得税资产 / 负债)

勾稽(容差 0, 空值跳过并计数):
  - ① 每年: 除税前溢利 + 非现金调整 + 营运资金变动 = 经营所得现金; 两端分别 = 年度损益表 / 现金流量表
  - ②③ 每期: 净利 = 除税前溢利 + 所得税开支; 经营所得现金 + 已收利息 + 已付所得税 = 经营现金流
  - ④ 2026H1: 实付税 − 税费 = 递延所得税净额增加 + 即期所得税负债减少(余差 0);
     2025 年余差 1 千元, 年报未拆(当年有业务合并, 附注 36), 只列不断言
  - `--mutate` 对 ① 的转录格逐格 +1 重跑全部勾稽, 报被捕获比例
"""
import csv
import importlib.util
import os
import sys

OUT = os.path.dirname(os.path.abspath(__file__))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(OUT, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


年度 = load("popmart_annual_build", "_build_from_pdf.py")
中期 = load("popmart_h1_build", "_build_h1_from_pdf.py")


# ====== ① 除所得税前溢利 → 经营所得现金 (2025 年报附注 34(a) P342, 2024 / 2025 两列) ======
YEARS_34A = [2024, 2025]
税前_34A = [4365812, 17036622]
非现金调整_34A = [
    ("按公允价值计入损益的金融资产公允价值变动", [23382, -85978]),
    ("以股份为基础的报酬", [94817, 76629]),
    ("分占合营企业及联营公司业绩", [-48188, -69653]),
    ("物业、厂房及设备折旧", [286481, 398202]),
    ("无形资产摊销", [124024, 127050]),
    ("处置租赁装修及其他设备的亏损", [655, 148]),
    ("使用权资产折旧", [452318, 592713]),
    ("金融资产减值拨备", [3446, 11805]),
    ("存货减值亏损", [14432, 21183]),
    ("业务合并时重新计量前合营企业 50% 权益的收益", [None, -42165]),
    ("财务收入净额", [-163352, -76495]),
    ("外汇损益", [16053, 264591]),
]
营运资金变动_34A = [
    ("存货", [-634245, -3932264]),
    ("贸易应收款项", [-157982, -442970]),
    ("预付款项及其他应收款项", [-110692, -821231]),
    ("贸易应付款项及应付授权费", [715141, 917857]),
    ("其他应付款项", [364407, 758209]),
    ("合约负债", [76434, 203801]),
    ("受限制银行存款", [-7490, -233274]),
]
经营所得现金_34A = [5415453, 14704780]


# ====== 两个构建脚本的科目名 ======
科目 = {
    "annual": {
        "净利": "年内溢利 Profit for the year",
        "税前": "除所得税前溢利 Profit before income tax",
        "所得税": "所得税开支 Income tax expense",
        "经营所得现金": "经营所得现金 Cash generated from operations",
        "已收利息": "已收利息 Interest received",
        "已付所得税": "已付所得税 Income tax paid",
        "经营现金流": "经营活动所得现金净额 Net cash from operating",
        "递延税资产": "递延所得税资产 Deferred income tax assets",
        "递延税负债": "递延所得税负债 Deferred income tax liabilities",
        "即期税负债": "即期所得税负债 Current income tax liabilities",
    },
    "h1": {
        "净利": "期内溢利 Profit for the period",
        "税前": "除所得税前溢利 Profit before income tax",
        "所得税": "所得税开支 Income tax expense",
        "经营所得现金": "经营所得现金 Cash generated from operations",
        "已收利息": "已收利息",
        "已付所得税": "已付所得税",
        "经营现金流": "经营活动所得现金净额 Net cash from operating",
        "递延税资产": "递延所得税资产",
        "递延税负债": "递延所得税负债",
        "即期税负债": "即期所得税负债",
    },
}


def cell(table, key, idx):
    for row_key, row_vals in table:
        if row_key == key:
            return row_vals[idx]
    raise KeyError(f"表内无科目: {key}")


def add(*vs):
    return None if any(v is None for v in vs) else sum(vs)


def ratio(a, b):
    return "" if a is None or not b else f"{a / b:.3f}"


def 三段(kind):
    """返回 (期间列表, {行名: [各期值]})。"""
    if kind == "annual":
        periods, pl, cf = 年度.YEARS, 年度.利润表, 年度.现金流量表
    else:
        periods, pl, cf = 中期.H1_PERIODS, 中期.利润表_H1, 中期.现金流量表_H1
    k = 科目[kind]
    rows = {
        "净利": [cell(pl, k["净利"], i) for i in range(len(periods))],
        "除所得税前溢利": [cell(pl, k["税前"], i) for i in range(len(periods))],
        "所得税开支": [cell(pl, k["所得税"], i) for i in range(len(periods))],
        "经营所得现金": [cell(cf, k["经营所得现金"], i) for i in range(len(periods))],
        "已收利息": [cell(cf, k["已收利息"], i) for i in range(len(periods))],
        "已付所得税": [cell(cf, k["已付所得税"], i) for i in range(len(periods))],
        "经营现金流": [cell(cf, k["经营现金流"], i) for i in range(len(periods))],
    }
    return periods, rows


def 税差():
    """2025(2024 年末 → 2025 年末)与 2026H1(2025 年末 → 2026-06-30)的税时间差。"""
    ka, kh = 科目["annual"], 科目["h1"]
    ya, ph = 年度.YEARS, 中期.H1_PERIODS

    def a_bs(key, year):
        return cell(年度.资产负债表, ka[key], ya.index(year)) or 0

    def h_bs(key, period):
        return cell(中期.资产负债表_H1, kh[key], ph.index(period)) or 0

    def build(np_, ocf, paid, exp, dta0, dta1, dtl0, dtl1, cur0, cur1):
        diff = paid - exp
        递延净增 = (dta1 - dtl1) - (dta0 - dtl0)
        即期减少 = cur0 - cur1
        return {
            "所得税开支(税费)": exp, "已付所得税(实付)": paid, "实付税 − 税费(正 = 多付)": diff,
            "递延所得税资产净额增加(已扣递延所得税负债变动)": 递延净增, "即期所得税负债减少(负 = 增加)": 即期减少,
            "余差(汇兑 / 业务合并等·报表未拆)": diff - 递延净增 - 即期减少,
            "即期所得税负债·期初": cur0, "即期所得税负债·期末": cur1,
            "递延所得税资产净额·期初": dta0, "递延所得税资产净额·期末": dta1,
            "现金含量": ratio(ocf, np_), "现金含量(若实付税 = 税费)": ratio(ocf + diff, np_),
        }

    i25 = ya.index(2025)
    j26 = ph.index("2026H1")
    return {
        "2025": build(
            cell(年度.利润表, ka["净利"], i25), cell(年度.现金流量表, ka["经营现金流"], i25),
            -cell(年度.现金流量表, ka["已付所得税"], i25), -cell(年度.利润表, ka["所得税"], i25),
            a_bs("递延税资产", 2024), a_bs("递延税资产", 2025), a_bs("递延税负债", 2024), a_bs("递延税负债", 2025),
            a_bs("即期税负债", 2024), a_bs("即期税负债", 2025)),
        "2026H1": build(
            cell(中期.利润表_H1, kh["净利"], j26), cell(中期.现金流量表_H1, kh["经营现金流"], j26),
            -cell(中期.现金流量表_H1, kh["已付所得税"], j26), -cell(中期.利润表_H1, kh["所得税"], j26),
            a_bs("递延税资产", 2025), h_bs("递延税资产", "2026H1"), a_bs("递延税负债", 2025), h_bs("递延税负债", "2026H1"),
            a_bs("即期税负债", 2025), h_bs("即期税负债", "2026H1")),
    }


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

    ka = 科目["annual"]
    for i, y in enumerate(YEARS_34A):
        nc = sum(v[i] or 0 for _, v in 非现金调整_34A)
        wc = sum(v[i] or 0 for _, v in 营运资金变动_34A)
        j = 年度.YEARS.index(y)
        eq(f"[{y}] 附注 34(a): 税前 + 非现金调整 + 营运资金变动 = 经营所得现金", 税前_34A[i] + nc + wc, 经营所得现金_34A[i])
        eq(f"[{y}] 附注 34(a) 税前 = 年度损益表", 税前_34A[i], cell(年度.利润表, ka["税前"], j))
        eq(f"[{y}] 附注 34(a) 经营所得现金 = 年度现金流量表", 经营所得现金_34A[i], cell(年度.现金流量表, ka["经营所得现金"], j))

    for kind in ("annual", "h1"):
        periods, r = 三段(kind)
        for i, p in enumerate(periods):
            eq(f"[{p}] 净利 = 税前 + 所得税开支", add(r["除所得税前溢利"][i], r["所得税开支"][i]), r["净利"][i])
            eq(f"[{p}] 经营所得现金 + 已收利息 + 已付所得税 = 经营现金流",
               add(r["经营所得现金"][i], r["已收利息"][i], r["已付所得税"][i]), r["经营现金流"][i])

    t = 税差()["2026H1"]
    eq("[2026H1] 实付税 − 税费 = 递延所得税净额增加 + 即期所得税负债减少",
       t["实付税 − 税费(正 = 多付)"], t["递延所得税资产净额增加(已扣递延所得税负债变动)"] + t["即期所得税负债减少(负 = 增加)"])
    return errors, stats


# ====== 变异对照: ① 的转录格逐格 +1 看勾稽能否抓到 ======
def mutation_test():
    targets = [("税前_34A", y, 税前_34A, i) for i, y in enumerate(YEARS_34A)]
    targets += [("经营所得现金_34A", y, 经营所得现金_34A, i) for i, y in enumerate(YEARS_34A)]
    for block in (非现金调整_34A, 营运资金变动_34A):
        for k, vals in block:
            targets += [(k, y, vals, i) for i, y in enumerate(YEARS_34A) if vals[i] is not None]
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
def write_csv():
    path = os.path.join(OUT, "经营现金流拆解.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["# 泡泡玛特 净利 → 经营现金流 拆解 · 单位: 人民币千元(比率除外) · 构建: _build_cash_bridge.py"])
        w.writerow(["# 三段: 净利 →(+所得税开支) 除所得税前溢利 →(+非现金调整 +营运资金变动) 经营所得现金 →(+已收利息 +已付所得税) 经营现金流; 流出为负"])

        w.writerow(["=== ① 除所得税前溢利 → 经营所得现金(2025 年报附注 34(a) P342; 中报无此表) ==="])
        w.writerow(["科目"] + [str(y) for y in YEARS_34A])
        w.writerow(["除所得税前溢利"] + 税前_34A)
        for k, vals in 非现金调整_34A:
            w.writerow([f"  {k}"] + ["" if v is None else v for v in vals])
        w.writerow(["非现金调整合计"] + [sum(v[i] or 0 for _, v in 非现金调整_34A) for i in range(len(YEARS_34A))])
        for k, vals in 营运资金变动_34A:
            w.writerow([f"  {k}"] + vals)
        w.writerow(["营运资金变动合计"] + [sum(v[i] for _, v in 营运资金变动_34A) for i in range(len(YEARS_34A))])
        w.writerow(["经营所得现金"] + 经营所得现金_34A)

        for kind, title in (("annual", "② 三段序列·年度(年度构建脚本)"), ("h1", "③ 三段序列·H1(H1 构建脚本·半年口径不年化)")):
            periods, r = 三段(kind)
            w.writerow([f"=== {title} ==="])
            w.writerow(["科目"] + [str(p) for p in periods])
            for k in ("净利", "除所得税前溢利", "所得税开支", "经营所得现金", "已收利息", "已付所得税", "经营现金流"):
                w.writerow([k] + ["" if v is None else v for v in r[k]])
            n = len(periods)
            w.writerow(["现金含量(经营现金流 ÷ 净利)"] + [ratio(r["经营现金流"][i], r["净利"][i]) for i in range(n)])
            w.writerow(["税前现金含量(经营所得现金 ÷ 除所得税前溢利)"]
                       + [ratio(r["经营所得现金"][i], r["除所得税前溢利"][i]) for i in range(n)])
            w.writerow(["实付税 − 税费(正 = 多付)"]
                       + [add(r["所得税开支"][i], -r["已付所得税"][i]) if r["已付所得税"][i] is not None else ""
                          for i in range(n)])

        t = 税差()
        w.writerow(["=== ④ 税的时间差: 实付税 − 税费 = 递延所得税资产净额增加 + 即期所得税负债减少 + 余差 ==="])
        w.writerow(["科目", "2025", "2026H1"])
        for k in t["2025"]:
            w.writerow([k, t["2025"][k], t["2026H1"][k]])
    return path


def main():
    if "--mutate" in sys.argv:
        mutation_test()
        return
    errors, stats = check()
    if errors:
        print("❌ 经营现金流拆解勾稽失败, 不写出 CSV:")
        for e in errors:
            print(f"  {e}")
        return
    write_csv()
    residual = 税差()["2025"]["余差(汇兑 / 业务合并等·报表未拆)"]
    print(f"✅ 经营现金流拆解勾稽全部通过: 执行 {stats['executed']} 条, 跳过 {stats['skipped']} 条 (容差 0); "
          f"2025 年税差余差 {residual} 千元(只列不断言); 已写出 经营现金流拆解.csv")


if __name__ == "__main__":
    main()
