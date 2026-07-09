# -*- coding: utf-8 -*-
"""农夫山泉 半年度(H1)序列 → 写 *-H1.csv，内置勾稽校验(不过不写出)。

数据血缘: report/农夫山泉/YYYY-H1.pdf 中期报告(未经审核·安永审阅)
  损益/全面收益 + 业务回顾(分部) + 财务状况表(关键行) + 现金流量表(关键行)。
  取「当期列」(H1 六个月 / 6-30 期末)，comparative 列用于交叉验(每期 OCF = 次期比较列, 已核)。

口径:
  - 单位: 利润表/资产负债表/现金流 = 人民币千元(RMB'000); 分部营收 = 人民币百万元。
  - 中报为「中期简明」condensed, 行项少于年报 → 资产负债表/现金流量表只取监控关键行(非全表)。
  - 2019 起无非控股权益 → 母公司应占 = 期内溢利。
  - 长期银行存款 2021/2022-H1 未单列(留空); 2023-2025-H1 取 BS/现金调节附注。
"""
import csv
import os

PERIODS = ["2021-H1", "2022-H1", "2023-H1", "2024-H1", "2025-H1"]
N = len(PERIODS)
OUT = os.path.dirname(os.path.abspath(__file__))

# ====== 中期简明综合损益表 (RMB'000, 当期六个月) ======
利润表 = [
    ("收益 Revenue",                                 [15174757, 16598761, 20462425, 22173084, 25622201]),
    ("销售成本 Cost of sales",                       [-5933765, -6761083, -8152496, -9140616, -10165771]),
    ("毛利 Gross profit",                            [9240992, 9837678, 12309929, 13032468, 15456430]),
    ("其他收入及收益净额 Other income & gains, net", [382387, 751368, 900521, 1039655, 807547]),
    ("销售及分销开支 Selling & distribution exp",    [-3554032, -3611520, -4695318, -4971457, -5010696]),
    ("行政开支 Administrative expenses",             [-662882, -876351, -958569, -913377, -1067728]),
    ("其他开支 Other expenses",                      [-55757, -9579, -2589, -5536, -127414]),
    ("财务费用 Finance costs",                       [-23930, -22341, -29670, -39438, -24563]),
    ("除税前溢利 Profit before tax",                 [5326778, 6069255, 7524304, 8142315, 10033576]),
    ("所得税开支 Income tax expense",                [-1313860, -1460930, -1748883, -1902736, -2411494]),
    ("母公司应占期内溢利 Profit attrib to parent",   [4012918, 4608325, 5775421, 6239579, 7622082]),
    ("每股基本及摊薄盈利(元) Basic&diluted EPS",     [0.36, 0.41, 0.51, 0.555, 0.677]),
]

# ====== 分部营收 (业务回顾·RMB million·当期六个月) ======
分部营收 = [
    ("包装饮用水产品 Packaged drinking water", [8919, 9349, 10442, 8531, 9443]),
    ("茶饮料产品 Tea beverage",               [2182, 3307, 5286, 8430, 10089]),
    ("功能饮料产品 Functional beverage",       [2004, 2023, 2457, 2550, 2898]),
    ("果汁饮料产品 Juice beverage",            [1224, 1275, 1686, 2114, 2564]),
    ("其他产品 Other",                        [846, 645, 591, 548, 629]),
    ("分部合计 Total",                        [15175, 16599, 20462, 22173, 25622]),
]

# ====== 中期简明综合财务状况表 (关键行·RMB'000·6-30 期末) ======
资产负债表 = [
    ("存货 Inventories",                              [1545858, 1722489, 2393212, 3336543, 5104288]),
    ("贸易应收款项及应收票据 Trade & bills recv",     [452085, 645382, 602567, 703194, 835572]),
    ("合约负债 Contract liabilities",                 [1440294, 1440978, 2559246, 2409942, 2897728]),
    ("现金及银行结余 Cash and bank balances",         [6515684, 18712379, 24645669, 16601323, 14905813]),
    ("长期银行存款 Long-term bank deposits",          [None, 1943455, 2827961, 10527397, 11504929]),
]

# ====== 中期简明综合现金流量表 (关键行·RMB'000·当期六个月) ======
现金流量表 = [
    ("存货(增加)/减少 (Inc)/dec in inventories",      [259596, 68648, -288542, -244814, -91255]),
    ("合约负债减少 Decrease in contract liabilities", [-807029, -909974, -117944, -1174979, -667765]),
    ("经营活动所得现金流量净额 Net cash from operating", [6585281, 5977699, 7992141, 5537057, 10406067]),
]


def find(table, name):
    for k, v in table:
        if k.startswith(name):
            return v
    raise KeyError(name)


def verify():
    errs = []
    for i, p in enumerate(PERIODS):
        rev = find(利润表, "收益")[i]
        cos = find(利润表, "销售成本")[i]
        gp = find(利润表, "毛利")[i]
        if rev + cos != gp:
            errs.append(f"{p} 收益{rev}+成本{cos}≠毛利{gp}")
        pbt = find(利润表, "除税前溢利")[i]
        tax = find(利润表, "所得税开支")[i]
        npr = find(利润表, "母公司应占期内溢利")[i]
        if pbt + tax != npr:
            errs.append(f"{p} 除税前{pbt}+税{tax}≠归母{npr}")
        # 除税前 = 毛利+其他收入-销售-行政-其他开支-财务费用
        calc = gp + find(利润表, "其他收入")[i] + find(利润表, "销售及分销")[i] + \
            find(利润表, "行政开支")[i] + find(利润表, "其他开支")[i] + find(利润表, "财务费用")[i]
        if calc != pbt:
            errs.append(f"{p} 损益逐项加总{calc}≠除税前{pbt}")
        # 分部合计 = 收益(百万取整, ±1); 5品类和 = 合计(±1 尾差)
        seg_total = find(分部营收, "分部合计")[i]
        if abs(seg_total - round(rev / 1000)) > 1:
            errs.append(f"{p} 分部合计{seg_total}≠营收百万{round(rev/1000)}")
        five = sum(find(分部营收, k)[i] for k in ["包装饮用水", "茶饮料", "功能饮料", "果汁饮料", "其他产品"])
        if abs(five - seg_total) > 1:
            errs.append(f"{p} 5品类和{five}≠分部合计{seg_total}(超±1尾差)")
    return errs


def write_csv(fn, rows, unit):
    with open(os.path.join(OUT, fn), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([f"# {unit}"])
        w.writerow(["科目"] + PERIODS)
        for name, vals in rows:
            row = [name]
            for v in vals:
                if v is None:
                    row.append("")
                elif isinstance(v, float):
                    row.append(f"{v:.4f}" if abs(v) < 1 else f"{v:.3f}")
                else:
                    row.append(v)
            w.writerow(row)
    print(f"  ✅ {fn}")


if __name__ == "__main__":
    print("校验 H1 勾稽...")
    e = verify()
    if e:
        print(f"❌ {len(e)} 条不平, 不写出:")
        for x in e:
            print("  ", x)
        raise SystemExit(1)
    print(f"✅ H1 勾稽全平 ({N} 期 × 收益/成本/毛利 + 除税前逐项 + 归母 + 分部)\n")
    print("写出 H1 CSV:")
    write_csv("利润表-H1.csv", 利润表, "单位: 人民币千元(RMB'000), 当期六个月, 来源: 中报 YYYY-H1.pdf")
    write_csv("分部营收-H1.csv", 分部营收, "单位: 人民币百万元, 当期六个月, 来源: 中报业务回顾")
    write_csv("资产负债表-H1.csv", 资产负债表, "单位: 人民币千元(RMB'000), 6-30 期末关键行, 来源: 中报财务状况表")
    write_csv("现金流量表-H1.csv", 现金流量表, "单位: 人民币千元(RMB'000), 当期六个月关键行, 来源: 中报现金流量表")
    print("\n🎊 H1 序列写出完成 (2021-H1 ~ 2025-H1)")
    # 参考派生(不写盘, 供核)
    print("\n参考: H1 毛利率 / 净利率 / OCF÷归母 / 存货(6-30,亿)")
    rev = find(利润表, "收益"); gp = find(利润表, "毛利"); npr = find(利润表, "母公司应占期内溢利")
    ocf = find(现金流量表, "经营活动所得现金流量净额"); inv = find(资产负债表, "存货")
    for i, p in enumerate(PERIODS):
        print(f"  {p}: 毛利率 {gp[i]/rev[i]*100:.1f}% · 净利率 {npr[i]/rev[i]*100:.1f}% · OCF÷归母 {ocf[i]/npr[i]:.2f} · 存货 {inv[i]/1e5:.1f}亿")
