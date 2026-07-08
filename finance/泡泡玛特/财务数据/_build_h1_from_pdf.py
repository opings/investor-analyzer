# -*- coding: utf-8 -*-
"""泡泡玛特(09992.HK) 中报 H1 三表数据 + 派生比率 → 写 -H1.csv, 内置勾稽自洽校验。

独立于年度 `_build_from_pdf.py`, 输出 `利润表-H1.csv` / `资产负债表-H1.csv` / `现金流量表-H1.csv` /
`财务比率-H1.csv`, 覆盖 6 个 H1 (2020H1-2025H1)。

数据血缘:
  2020-H1 列 ← report/泡泡玛特/招股说明书.pdf 附录一 P I-4~I-13 (2020-06-30 未审)
  2021-H1 列 ← report/泡泡玛特/2021-H1.pdf 中报正文 P39-47
  2022-H1 列 ← report/泡泡玛特/2022-H1.pdf 中报正文 P42-51
  2023-H1 列 ← report/泡泡玛特/2023-H1.pdf 中报正文 P44-53
  2024-H1 列 ← report/泡泡玛特/2024-H1.pdf 中报正文 P47-55
  2025-H1 列 ← report/泡泡玛特/2025-H1.pdf 中报正文 P52-60

口径:
  - 单位 = 人民币千元 (RMB'000)
  - 半年 CF/PL 是"截至 6-30 止六个月", 半年 BS 是"6-30 快照"
  - 2020H1 EPS 招股书原始给的是 1.22 元 = 122 分, 与其他 H1 单位统一
  - 财务比率里"周转天数"用 H1 期间天数 182 半年口径; ROE/现金含量等不年化, 反映半年真实值
"""
import csv
import os

H1_PERIODS = ["2020H1", "2021H1", "2022H1", "2023H1", "2024H1", "2025H1"]
OUT = os.path.dirname(os.path.abspath(__file__))
H1_DAYS = 182  # 半年天数


# ====== 中期简明综合损益表 (H1) ======
利润表_H1 = [
    ("收益 Revenue",                                    [817791, 1772577, 2358818, 2813812, 4557831, 13876276]),
    ("销售成本 Cost of sales",                          [-284352, -655512, -988411, -1115452, -1638726, -4115212]),
    ("毛利 Gross profit",                               [533439, 1117065, 1370407, 1698360, 2919105, 9761064]),
    ("经销及销售开支 Distribution and selling expenses",[-223030, -419780, -693230, -878319, -1353206, -3192590]),
    ("一般及行政开支 G&A expenses",                     [-125397, -239673, -322679, -331252, -434410, -770405]),
    ("金融资产减值(-)/拨回(+)",                          [977, -3296, 80, -95, -2589, -746]),
    ("其他收入 Other income",                            [31369, 25425, 24335, 37433, 31586, 67232]),
    ("其他收益/(亏损)-净",                              [-8990, 6946, 67144, 11635, -34069, 179186]),
    ("经营溢利 Operating profit",                       [208368, 486687, 446057, 537762, 1126417, 6043741]),
    ("财务收入 Finance income",                          [699, 13888, 22992, 79613, 105993, 93870]),
    ("财务开支 Finance expenses",                       [-4624, -8160, -15981, -16174, -22218, -28364]),
    ("可换股优先股公平值变动",                          [-6436, None, None, None, None, None]),
    ("权益法投资溢利",                                   [-1125, 4140, 4868, 17346, 18246, 47625]),
    ("除所得税前溢利 Profit before income tax",         [196882, 496555, 457936, 618547, 1228438, 6156872]),
    ("所得税开支 Income tax expense",                   [-55598, -137757, -124991, -141305, -264296, -1475159]),
    ("期内溢利 Profit for the period",                  [141284, 358798, 332945, 477242, 964142, 4681713]),
    ("归母溢利 Attributable to parent",                 [141358, 358742, 332820, 476575, 921333, 4574368]),
    ("非控股权益溢利 Non-controlling interests",        [-74, 56, 125, 667, 42809, 107345]),
    ("每股基本盈利(人民币分) Basic EPS RMB cents",       [122, 26.04, 24.18, 35.46, 69.49, 344.17]),
]


# ====== 中期简明综合资产负债表 (H1 期末快照·6-30) ======
资产负债表_H1 = [
    # ---- 非流动资产 ----
    ("物业厂房设备 PPE",                                [135222, 270221, 403986, 499814, 627083, 941575]),
    ("无形资产 Intangible assets",                     [85271, 90206, 119378, 122354, 123135, 207473]),
    ("使用权资产 Right-of-use assets",                 [209420, 380204, 640044, 630452, 789368, 1366773]),
    ("权益法投资 Equity method investments",            [45979, 54205, 67969, 102225, 112928, 107024]),
    ("FVTPL金融资产(非流动)",                           [None, 83974, 471235, 462037, 429972, 421934]),
    ("预付款项及其他非流动资产",                        [13697, 52342, 14676, 79430, 122746, 127886]),
    ("递延所得税资产",                                   [22344, 25881, 30633, 89971, 96906, 333432]),
    ("非流动资产合计",                                   [511933, 957033, 1747921, 1986283, 2302138, 3506097]),
    # ---- 流动资产 ----
    ("贸易应收款",                                       [41374, 135390, 132442, 208911, 263722, 971579]),
    ("其他应收款 (独立列示)",                            [69014, 117509, 197104, 174190, None, None]),
    ("存货",                                             [224050, 315962, 957448, 758774, 916686, 2273691]),
    ("预付款项及其他流动资产",                          [117569, 304613, 374916, 364863, 497621, 748214]),
    ("FVTPL金融资产(流动)",                             [None, 39959, 13926, 10701, 7409, 11393]),
    ("受限现金(流动)",                                   [3548, 3230, 3494, 22011, 19954, 79994]),
    ("定期存款(3-12个月)",                              [None, 4263666, 4087243, 4066222, 3401275, 1843017]),
    ("现金及等价物",                                     [821686, 1503622, 1075380, 1473382, 3608674, 11922694]),
    ("流动资产合计",                                     [1277241, 6683951, 6841953, 7079054, 8715341, 17850582]),
    ("总资产",                                           [1789174, 7640984, 8589874, 9065337, 11017479, 21356679]),
    # ---- 权益 ----
    ("股本",                                             [86, 923, 920, 891, 882, 882]),
    ("股份奖励计划持股",                                 [None, -16, -15, -13, -11, -8]),
    ("其他储备",                                         [675439, 5014059, 4984732, 4556606, 4159062, 3213856]),
    ("保留盈利",                                         [564426, 1298094, 2126511, 2745926, 4239103, 10969312]),
    ("归母权益",                                         [1239951, 6313060, 7112148, 7303410, 8399036, 14184042]),
    ("非控股权益",                                       [1828, 1617, 2035, 2568, 53621, 245532]),
    ("总权益",                                           [1241779, 6314677, 7114183, 7305978, 8452657, 14429574]),
    # ---- 非流动负债 ----
    ("应付授权费(非流动)",                              [36132, 24694, 28160, 12223, 14188, 7647]),
    ("租赁负债(非流动)",                                [100134, 209447, 421409, 385774, 466001, 996260]),
    ("递延所得税负债",                                   [None, None, None, 15667, 16290, None]),
    ("非流动负债合计",                                   [136266, 234141, 449569, 413664, 496479, 1003907]),
    # ---- 流动负债 ----
    ("贸易应付款",                                       [77191, 222935, 308470, 349477, 555137, 1627664]),
    ("应付授权费(流动)",                                [22699, 58831, 106465, 160710, 273026, 546245]),
    ("其他应付款",                                       [105982, 399279, 196189, 351438, 535472, 1445057]),
    ("合约负债(预收)",                                   [58343, 156428, 93331, 92531, 151536, 855216]),
    ("借款(流动)",                                       [None, None, None, None, None, None]),
    ("租赁负债(流动)",                                   [111052, 181412, 256051, 292116, 356175, 414939]),
    ("即期所得税负债",                                   [35862, 73281, 65616, 99423, 196997, 1034077]),
    ("流动负债合计",                                     [411129, 1092166, 1026122, 1345695, 2068343, 5923198]),
    # ---- 总负债 & 总权益+负债 ----
    ("总负债",                                           [547395, 1326307, 1475691, 1759359, 2564822, 6927105]),
    ("总权益及负债",                                     [1789174, 7640984, 8589874, 9065337, 11017479, 21356679]),
]


# ====== 中期简明综合现金流量表 (H1) ======
现金流量表_H1 = [
    # ---- 经营活动 ----
    ("经营所得现金 Cash generated from operations",     [219855, 554706, 523391, 1113479, 1908029, 6975420]),
    ("已收利息",                                         [699, 13888, 1811, 76715, 191283, 191679]),
    ("已付所得税",                                       [-98363, -126937, -151624, -97857, -194041, -1189626]),
    ("经营活动所得现金净额 Net cash from operating",     [122191, 441657, 373578, 1092337, 1905271, 5977473]),
    # ---- 投资活动 ----
    ("购买 PPE",                                         [-56700, -114350, -135860, -186617, -157858, -353623]),
    ("购买无形资产",                                     [-16827, -12460, -26253, -27462, -28587, -20900]),
    ("购买 FVTPL 金融资产",                              [-225000, -1017806, -1084688, -861298, -946588, -3092500]),
    ("存入定期存款",                                     [None, None, None, None, -3534913, -3946911]),
    ("定期存款净变(存入-赎回, 2021-2023 中报合并列示)",  [None, -4263666, -3985022, 289998, None, None]),
    ("赎回定期存款",                                     [None, None, None, None, 4027140, 5470472]),
    ("处置 FVTPL 所得款项",                              [275000, 882445, 1010949, 867141, 956534, 3106184]),
    ("处置 PPE/无形/使用权资产所得",                     [0, 15930, 4951, 272, 2240, 5373]),
    ("按公平值计入损益的金融资产投资收入(旧格式)",       [1102, 11500, 6021, None, None, None]),
    ("于一家联营公司的投资",                            [-27424, None, None, None, None, None]),
    ("收到合营企业股息",                                 [None, None, None, None, 15623, None]),
    ("收购附属公司现金流入净额",                        [1590, None, None, None, None, 65995]),
    ("投资活动净额 Net cash from investing",             [-48259, -4498407, -4209902, 82034, 333591, 1234090]),
    # ---- 融资活动 ----
    ("租赁负债付款",                                     [-56495, -94201, -139351, -192416, -249860, -263592]),
    ("已付股息",                                         [0, -26797, -221202, -118995, -373025, -1083288]),
    ("股份回购付款",                                     [None, None, -120008, -246876, -78031, None]),
    ("偿还借款",                                         [None, None, None, None, -15058, None]),
    ("非控股权益注资",                                   [None, None, None, None, None, 33663]),
    ("收购附属公司非控股权益",                          [None, None, None, None, None, -46760]),
    ("已付非控股股东股息",                              [None, None, None, None, None, -44974]),
    ("上市开支付款",                                     [-119, None, None, None, None, None]),
    ("股东注资",                                         [398375, None, None, None, None, None]),
    ("视作分派予当时股东",                              [-4566, None, None, None, None, None]),
    ("发行可换股可赎回优先股",                          [86561, None, None, None, None, None]),
    ("融资活动净额 Net cash from financing",             [423756, -120998, -480561, -558287, -715974, -1404951]),
    # ---- 现金总变动 ----
    ("现金及等价物增加/(减少)净额",                     [497688, -4177748, -4316885, 616084, 1522888, 5806612]),
    ("期初现金及等价物",                                 [324614, 5680235, 5264710, 685314, 2077927, 6109017]),
    ("汇兑损益",                                         [-616, 1135, 127555, 171984, 7859, 7065]),
    ("期末现金及等价物",                                 [821686, 1503622, 1075380, 1473382, 3608674, 11922694]),
]


# ====== 勾稽自洽校验 (None-safe) ======
def value(table, key, idx):
    for row_key, row_vals in table:
        if row_key == key:
            return row_vals[idx]
    return None


def _need(*vs):
    return all(v is not None for v in vs)


def check():
    errors = []
    skipped = []
    for i, p in enumerate(H1_PERIODS):
        # 1) 毛利 = 收益 - 销售成本
        rev = value(利润表_H1, "收益 Revenue", i)
        cost = value(利润表_H1, "销售成本 Cost of sales", i)
        gp = value(利润表_H1, "毛利 Gross profit", i)
        if _need(rev, cost, gp) and abs(rev + cost - gp) > 1:
            errors.append(f"[{p}] 毛利勾稽失败: {rev}+{cost} vs {gp}")

        # 2) 净利 = 除税前 + 所得税
        pretax = value(利润表_H1, "除所得税前溢利 Profit before income tax", i)
        tax = value(利润表_H1, "所得税开支 Income tax expense", i)
        pat = value(利润表_H1, "期内溢利 Profit for the period", i)
        if _need(pretax, tax, pat) and abs(pretax + tax - pat) > 1:
            errors.append(f"[{p}] 净利勾稽失败: {pretax}+{tax} vs {pat}")

        # 3) 归母 + 非控股 = 净利
        parent = value(利润表_H1, "归母溢利 Attributable to parent", i)
        nci = value(利润表_H1, "非控股权益溢利 Non-controlling interests", i)
        if _need(parent, nci, pat) and abs(parent + nci - pat) > 1:
            errors.append(f"[{p}] 归母+非控股 vs 净利: {parent}+{nci} vs {pat}")

        # 4) 非流动+流动=总资产
        nca = value(资产负债表_H1, "非流动资产合计", i)
        ca = value(资产负债表_H1, "流动资产合计", i)
        ta = value(资产负债表_H1, "总资产", i)
        if _need(nca, ca, ta) and abs(nca + ca - ta) > 1:
            errors.append(f"[{p}] 总资产勾稽失败: {nca}+{ca}={nca+ca} vs {ta}")

        # 5) 非流动负债+流动负债=总负债
        ncl = value(资产负债表_H1, "非流动负债合计", i)
        cl = value(资产负债表_H1, "流动负债合计", i)
        tl = value(资产负债表_H1, "总负债", i)
        if _need(ncl, cl, tl) and abs(ncl + cl - tl) > 1:
            errors.append(f"[{p}] 总负债勾稽失败: {ncl}+{cl}={ncl+cl} vs {tl}")

        # 6) 归母权益+非控股权益=总权益
        eq_parent = value(资产负债表_H1, "归母权益", i)
        eq_nci = value(资产负债表_H1, "非控股权益", i)
        te = value(资产负债表_H1, "总权益", i)
        if _need(eq_parent, eq_nci, te) and abs(eq_parent + eq_nci - te) > 1:
            errors.append(f"[{p}] 总权益勾稽失败: {eq_parent}+{eq_nci}={eq_parent+eq_nci} vs {te}")

        # 7) 资产 = 负债+权益
        if _need(ta, tl, te) and abs(ta - tl - te) > 1:
            errors.append(f"[{p}] 资产=负债+权益 失败: 资产{ta} vs 负债+权益={tl+te}")

        # 8) 期初+净变+汇率=期末
        beg = value(现金流量表_H1, "期初现金及等价物", i)
        net = value(现金流量表_H1, "现金及等价物增加/(减少)净额", i)
        fx = value(现金流量表_H1, "汇兑损益", i)
        end = value(现金流量表_H1, "期末现金及等价物", i)
        if _need(beg, net, fx, end) and abs(beg + net + fx - end) > 1:
            errors.append(f"[{p}] 现金勾稽失败: {beg}+{net}+{fx}={beg+net+fx} vs {end}")

        # 9) 经营+投资+融资=净变动
        op = value(现金流量表_H1, "经营活动所得现金净额 Net cash from operating", i)
        inv = value(现金流量表_H1, "投资活动净额 Net cash from investing", i)
        fin = value(现金流量表_H1, "融资活动净额 Net cash from financing", i)
        if _need(op, inv, fin, net) and abs(op + inv + fin - net) > 1:
            errors.append(f"[{p}] 三大活动加总失败: 经营{op}+投资{inv}+融资{fin}={op+inv+fin} vs {net}")

        # 10) CF 期末 = BS 现金
        bs_cash = value(资产负债表_H1, "现金及等价物", i)
        if _need(end, bs_cash) and abs(end - bs_cash) > 1:
            errors.append(f"[{p}] CF期末{end} != BS现金{bs_cash}")

    return errors, skipped


# ====== 派生比率 (半年口径, 不年化) ======
def build_ratios():
    def get(t, k, i):
        for rk, rv in t:
            if rk == k:
                return rv[i]
        return None

    def rate(num, den, mul=1):
        if num is None or den is None or den == 0:
            return ""
        return round(num / den * mul, 2)

    def add(*vs):
        if any(v is None for v in vs):
            return None
        return sum(vs)

    rows = []
    for i, p in enumerate(H1_PERIODS):
        rev = get(利润表_H1, "收益 Revenue", i)
        gp = get(利润表_H1, "毛利 Gross profit", i)
        op = get(利润表_H1, "经营溢利 Operating profit", i)
        pat = get(利润表_H1, "期内溢利 Profit for the period", i)
        parent_pat = get(利润表_H1, "归母溢利 Attributable to parent", i)
        ds = get(利润表_H1, "经销及销售开支 Distribution and selling expenses", i)
        ga = get(利润表_H1, "一般及行政开支 G&A expenses", i)
        op_cf = get(现金流量表_H1, "经营活动所得现金净额 Net cash from operating", i)
        capex_ppe = get(现金流量表_H1, "购买 PPE", i)
        capex_intang = get(现金流量表_H1, "购买无形资产", i)
        capex = add(capex_ppe, capex_intang)
        divid = get(现金流量表_H1, "已付股息", i)
        ta = get(资产负债表_H1, "总资产", i)
        te = get(资产负债表_H1, "总权益", i)
        eq_parent = get(资产负债表_H1, "归母权益", i)
        tl = get(资产负债表_H1, "总负债", i)
        ar = get(资产负债表_H1, "贸易应收款", i)
        inv = get(资产负债表_H1, "存货", i)
        ap = get(资产负债表_H1, "贸易应付款", i)
        goods_cost = get(利润表_H1, "销售成本 Cost of sales", i)
        goods_cost = -goods_cost if goods_cost is not None else None
        cash = get(资产负债表_H1, "现金及等价物", i)
        td = get(资产负债表_H1, "定期存款(3-12个月)", i)
        cash_td = add(cash, td) if td is not None else cash
        contract_liab = get(资产负债表_H1, "合约负债(预收)", i)

        row = {
            "期间": p,
            "毛利率%": rate(gp, rev, 100),
            "经营利润率%": rate(op, rev, 100),
            "净利率%": rate(pat, rev, 100),
            "销售费用率%": rate(-ds if ds is not None else None, rev, 100),
            "管理费用率%": rate(-ga if ga is not None else None, rev, 100),
            "半年ROE-归母%(不年化)": rate(parent_pat, eq_parent, 100),
            "资产负债率%": rate(tl, ta, 100),
            "现金含量(经营现金/净利)": rate(op_cf, pat),
            "H1 capex(PPE+无形) k RMB": capex if capex is not None else "",
            "capex/净利%(H1口径)": rate(capex, pat, 100),
            "capex/经营现金%(H1口径)": rate(capex, op_cf, 100),
            "应收周转天数(H1·182天)": rate(ar, rev, H1_DAYS),
            "存货周转天数(H1·182天)": rate(inv, goods_cost, H1_DAYS),
            "应付周转天数(H1·182天)": rate(ap, goods_cost, H1_DAYS),
            "现金+定存/总资产%": rate(cash_td, ta, 100),
            "存货/总资产%": rate(inv, ta, 100),
            "H1已付股息 k RMB": divid if divid is not None else "",
            "半年分红率%(归母)": rate(-divid if divid is not None else None, parent_pat, 100),
            "合约负债/H1营收%": rate(contract_liab, rev, 100),
            "应收/H1营收%": rate(ar, rev, 100),
        }
        rows.append(row)
    return rows


# ====== 写 CSV ======
def write_csv(name, table, header):
    path = os.path.join(OUT, name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([f"# 单位: 人民币千元 (RMB'000), 中报 H1 序列 (半年口径), 泡泡玛特(09992.HK)"])
        w.writerow(header)
        for row_key, row_vals in table:
            out_row = [row_key] + ["" if v is None else v for v in row_vals]
            w.writerow(out_row)


def write_ratios(rows):
    path = os.path.join(OUT, "财务比率-H1.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["# H1 派生比率, 从 H1 三表算出, 半年口径(不年化), 单位见字段名"])
        w.writerow(list(rows[0].keys()))
        for r in rows:
            w.writerow(r.values())


def main():
    errors, skipped = check()
    if errors:
        print("❌ H1 勾稽校验失败,不写出 CSV:")
        for e in errors:
            print(f"  {e}")
        return
    print(f"✅ H1 勾稽校验全部通过 ({len(H1_PERIODS)} 个 H1 × 10 条勾稽 = 60 条)")
    header = ["科目"] + H1_PERIODS
    write_csv("利润表-H1.csv", 利润表_H1, header)
    write_csv("资产负债表-H1.csv", 资产负债表_H1, header)
    write_csv("现金流量表-H1.csv", 现金流量表_H1, header)
    rows = build_ratios()
    write_ratios(rows)
    print(f"已写出 4 个 -H1.csv → {OUT}")


if __name__ == "__main__":
    main()
