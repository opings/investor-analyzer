# -*- coding: utf-8 -*-
"""泡泡玛特(09992.HK) 中报 H1 三表数据 + 派生比率 → 写 -H1.csv, 内置勾稽自洽校验。

独立于年度 `_build_from_pdf.py`, 输出 `利润表-H1.csv` / `资产负债表-H1.csv` / `现金流量表-H1.csv` /
`财务比率-H1.csv`, 覆盖 7 个 H1 (2020H1-2026H1)。

数据血缘:
  2020-H1 列 ← report/泡泡玛特/泡泡玛特-招股说明书.pdf 附录一 P I-4~I-13 (2020-06-30 未审)
  2021-H1 列 ← report/泡泡玛特/泡泡玛特-2021-H1.pdf 中报正文 P39-47
  2022-H1 列 ← report/泡泡玛特/泡泡玛特-2022-H1.pdf 中报正文 P42-51
  2023-H1 列 ← report/泡泡玛特/泡泡玛特-2023-H1.pdf 中报正文 P44-53
  2024-H1 列 ← report/泡泡玛特/泡泡玛特-2024-H1.pdf 中报正文 P47-55
  2025-H1 列 ← report/泡泡玛特/泡泡玛特-2025-H1.pdf 中报正文 P52-60
  2026-H1 列 ← report/泡泡玛特/泡泡玛特-2026-H1.pdf 中报正文 P63-70(损益 P63-64 · 资产负债 P65-66 · 现金流 P69-70)

口径:
  - 单位 = 人民币千元 (RMB'000)
  - 半年 CF/PL 是"截至 6-30 止六个月", 半年 BS 是"6-30 快照"
  - 每股盈利行单位 = 人民币分: 2020H1 招股书给 1.22 元 = 122 分; 2026 中报改以「元」列示且只到两位小数,
    3.80 元记 380 分(精度低于此前各期)
  - 财务比率里"周转天数"用 H1 期间天数 182 半年口径, 期末余额 ÷ 半年销售成本; 公司 MD&A 用平均余额,
    数值不同(2026H1 公司口径存货周转 201 天), 两者不可混比; ROE/现金含量等不年化, 反映半年真实值

勾稽:
  - 默认容差 0(源表是千元整数, 差 1 即转录错); 每期 21 条(表内逐行加总 + 跨表) + 跨源比对:
    ① 2026 中报的 2025H1 比较列 == 本表 2025H1 列(损益/现金流逐行)
    ② 2026 中报的 2025-12-31 比较列 == 年度 `_build_from_pdf.py` 的 2025 年末(资产负债逐行)
    ③ 各期 CF 期初现金 == 年度资产负债表上年末现金
  - 空值不当 0 硬算: 合计项缺失则该条计入「跳过」并打印条数
  - `--mutate` 逐格 +1 重跑全部勾稽, 报被捕获比例; `--mutate --list` 列出未被任何勾稽覆盖的格
"""
import csv
import importlib.util
import os
import sys

H1_PERIODS = ["2020H1", "2021H1", "2022H1", "2023H1", "2024H1", "2025H1", "2026H1"]
OUT = os.path.dirname(os.path.abspath(__file__))
H1_DAYS = 182  # 半年天数


# ====== 中期简明综合损益表 (H1) ======
利润表_H1 = [
    ("收益 Revenue",                                    [817791, 1772577, 2358818, 2813812, 4557831, 13876276, 17172921]),
    ("销售成本 Cost of sales",                          [-284352, -655512, -988411, -1115452, -1638726, -4115212, -5207181]),
    ("毛利 Gross profit",                               [533439, 1117065, 1370407, 1698360, 2919105, 9761064, 11965740]),
    ("经销及销售开支 Distribution and selling expenses",[-223030, -419780, -693230, -878319, -1353206, -3192590, -3931123]),
    ("一般及行政开支 G&A expenses",                     [-125397, -239673, -322679, -331252, -434410, -770405, -926526]),
    ("金融资产减值(-)/拨回(+)",                          [977, -3296, 80, -95, -2589, -746, 2651]),
    ("其他收入 Other income",                            [31369, 25425, 24335, 37433, 31586, 67232, 302837]),
    ("其他收益/(亏损)-净",                              [-8990, 6946, 67144, 11635, -34069, 179186, -688833]),
    ("经营溢利 Operating profit",                       [208368, 486687, 446057, 537762, 1126417, 6043741, 6724746]),
    ("财务收入 Finance income",                          [699, 13888, 22992, 79613, 105993, 93870, 92652]),
    ("财务开支 Finance expenses",                       [-4624, -8160, -15981, -16174, -22218, -28364, -81173]),
    ("可换股优先股公平值变动",                          [-6436, None, None, None, None, None, None]),
    ("权益法投资溢利",                                   [-1125, 4140, 4868, 17346, 18246, 47625, 30633]),
    ("除所得税前溢利 Profit before income tax",         [196882, 496555, 457936, 618547, 1228438, 6156872, 6766858]),
    ("所得税开支 Income tax expense",                   [-55598, -137757, -124991, -141305, -264296, -1475159, -1666548]),
    ("期内溢利 Profit for the period",                  [141284, 358798, 332945, 477242, 964142, 4681713, 5100310]),
    ("归母溢利 Attributable to parent",                 [141358, 358742, 332820, 476575, 921333, 4574368, 5038384]),
    ("非控股权益溢利 Non-controlling interests",        [-74, 56, 125, 667, 42809, 107345, 61926]),
    ("每股基本盈利(人民币分) Basic EPS RMB cents",       [122, 26.04, 24.18, 35.46, 69.49, 344.17, 380]),
]


# ====== 中期简明综合资产负债表 (H1 期末快照·6-30) ======
资产负债表_H1 = [
    # ---- 非流动资产 ----
    ("物业厂房设备 PPE",                                [135222, 270221, 403986, 499814, 627083, 941575, 1770206]),
    ("无形资产 Intangible assets",                     [85271, 90206, 119378, 122354, 123135, 207473, 236368]),
    ("使用权资产 Right-of-use assets",                 [209420, 380204, 640044, 630452, 789368, 1366773, 3602656]),
    ("受限现金(非流动)",                                 [None, None, None, None, None, None, 224018]),
    ("权益法投资 Equity method investments",            [45979, 54205, 67969, 102225, 112928, 107024, 159359]),
    ("FVTPL金融资产(非流动)",                           [None, 83974, 471235, 462037, 429972, 421934, 620762]),
    ("预付款项及其他非流动资产",                        [13697, 52342, 14676, 79430, 122746, 127886, 306974]),
    ("定期存款(一年以上)",                               [None, None, None, None, None, None, 201773]),
    ("递延所得税资产",                                   [22344, 25881, 30633, 89971, 96906, 333432, 1813681]),
    ("非流动资产合计",                                   [511933, 957033, 1747921, 1986283, 2302138, 3506097, 8935797]),
    # ---- 流动资产 ----
    ("贸易应收款",                                       [41374, 135390, 132442, 208911, 263722, 971579, 627306]),
    ("其他应收款 (独立列示)",                            [69014, 117509, 197104, 174190, None, None, None]),
    ("存货",                                             [224050, 315962, 957448, 758774, 916686, 2273691, 6101530]),
    ("预付款项及其他流动资产",                          [117569, 304613, 374916, 364863, 497621, 748214, 1388205]),
    ("FVTPL金融资产(流动)",                             [None, 39959, 13926, 10701, 7409, 11393, 9662]),
    ("受限现金(流动)",                                   [3548, 3230, 3494, 22011, 19954, 79994, 3384]),
    ("定期存款(3-12个月)",                              [None, 4263666, 4087243, 4066222, 3401275, 1843017, 1520187]),
    ("现金及等价物",                                     [821686, 1503622, 1075380, 1473382, 3608674, 11922694, 12442065]),
    ("流动资产合计",                                     [1277241, 6683951, 6841953, 7079054, 8715341, 17850582, 22092339]),
    ("总资产",                                           [1789174, 7640984, 8589874, 9065337, 11017479, 21356679, 31028136]),
    # ---- 权益 ----
    ("股本",                                             [86, 923, 920, 891, 882, 882, 875]),
    ("股份奖励计划持股",                                 [None, -16, -15, -13, -11, -8, -6]),
    ("其他储备",                                         [675439, 5014059, 4984732, 4556606, 4159062, 3213856, -1131526]),
    ("保留盈利",                                         [564426, 1298094, 2126511, 2745926, 4239103, 10969312, 24189681]),
    ("归母权益",                                         [1239951, 6313060, 7112148, 7303410, 8399036, 14184042, 23059024]),
    ("非控股权益",                                       [1828, 1617, 2035, 2568, 53621, 245532, 229451]),
    ("总权益",                                           [1241779, 6314677, 7114183, 7305978, 8452657, 14429574, 23288475]),
    # ---- 非流动负债 ----
    ("应付授权费(非流动)",                              [36132, 24694, 28160, 12223, 14188, 7647, 5275]),
    ("租赁负债(非流动)",                                [100134, 209447, 421409, 385774, 466001, 996260, 3061836]),
    ("递延所得税负债",                                   [None, None, None, 15667, 16290, None, None]),
    ("非流动负债合计",                                   [136266, 234141, 449569, 413664, 496479, 1003907, 3067111]),
    # ---- 流动负债 ----
    ("贸易应付款",                                       [77191, 222935, 308470, 349477, 555137, 1627664, 905150]),
    ("应付授权费(流动)",                                [22699, 58831, 106465, 160710, 273026, 546245, 513583]),
    ("其他应付款",                                       [105982, 399279, 196189, 351438, 535472, 1445057, 1451670]),
    ("合约负债(预收)",                                   [58343, 156428, 93331, 92531, 151536, 855216, 513419]),
    ("借款(流动)",                                       [None, None, None, None, None, None, None]),
    ("租赁负债(流动)",                                   [111052, 181412, 256051, 292116, 356175, 414939, 665736]),
    ("即期所得税负债",                                   [35862, 73281, 65616, 99423, 196997, 1034077, 622992]),
    ("流动负债合计",                                     [411129, 1092166, 1026122, 1345695, 2068343, 5923198, 4672550]),
    # ---- 总负债 & 总权益+负债 ----
    ("总负债",                                           [547395, 1326307, 1475691, 1759359, 2564822, 6927105, 7739661]),
    ("总权益及负债",                                     [1789174, 7640984, 8589874, 9065337, 11017479, 21356679, 31028136]),
]


# ====== 中期简明综合现金流量表 (H1) ======
现金流量表_H1 = [
    # ---- 经营活动 ----
    ("经营所得现金 Cash generated from operations",     [219855, 554706, 523391, 1113479, 1908029, 6975420, 6764282]),
    ("已收利息",                                         [699, 13888, 1811, 76715, 191283, 191679, 92716]),
    ("已付所得税",                                       [-98363, -126937, -151624, -97857, -194041, -1189626, -3219674]),
    ("经营活动所得现金净额 Net cash from operating",     [122191, 441657, 373578, 1092337, 1905271, 5977473, 3637324]),
    # ---- 投资活动 ----
    ("购买 PPE",                                         [-56700, -114350, -135860, -186617, -157858, -353623, -673560]),
    ("购买无形资产",                                     [-16827, -12460, -26253, -27462, -28587, -20900, -50579]),
    ("购买 FVTPL 金融资产",                              [-225000, -1017806, -1084688, -861298, -946588, -3092500, -8527543]),
    ("存入定期存款",                                     [None, None, None, None, -3534913, -3946911, -640149]),
    ("定期存款净变(存入-赎回, 2021-2023 中报合并列示)",  [None, -4263666, -3985022, 289998, None, None, None]),
    ("赎回定期存款",                                     [None, None, None, None, 4027140, 5470472, 2270316]),
    ("处置 FVTPL 所得款项",                              [275000, 882445, 1010949, 867141, 956534, 3106184, 8301150]),
    ("处置 PPE/无形/使用权资产所得",                     [0, 15930, 4951, 272, 2240, 5373, 4325]),
    ("按公平值计入损益的金融资产投资收入(旧格式)",       [1102, 11500, 6021, None, None, None, None]),
    ("于一家联营公司的投资",                            [-27424, None, None, None, None, None, None]),
    ("收到合营企业股息",                                 [None, None, None, None, 15623, None, None]),
    ("收购附属公司现金净额(流入+/流出-)",               [1590, None, None, None, None, 65995, -10894]),
    ("投资活动净额 Net cash from investing",             [-48259, -4498407, -4209902, 82034, 333591, 1234090, 673066]),
    # ---- 融资活动 ----
    ("租赁负债付款",                                     [-56495, -94201, -139351, -192416, -249860, -263592, -502889]),
    ("已付股息",                                         [0, -26797, -221202, -118995, -373025, -1083288, -3149378]),
    ("股份回购付款",                                     [None, None, -120008, -246876, -78031, None, -1545689]),
    ("偿还借款",                                         [None, None, None, None, -15058, None, None]),
    ("非控股权益注资",                                   [None, None, None, None, None, 33663, 514]),
    ("收购附属公司非控股权益",                          [None, None, None, None, None, -46760, None]),
    ("已付非控股股东股息",                              [None, None, None, None, None, -44974, -184823]),
    ("上市开支付款",                                     [-119, None, None, None, None, None, None]),
    ("股东注资",                                         [398375, None, None, None, None, None, None]),
    ("视作分派予当时股东",                              [-4566, None, None, None, None, None, None]),
    ("发行可换股可赎回优先股",                          [86561, None, None, None, None, None, None]),
    ("融资活动净额 Net cash from financing",             [423756, -120998, -480561, -558287, -715974, -1404951, -5382265]),
    # ---- 现金总变动 ----
    ("现金及等价物增加/(减少)净额",                     [497688, -4177748, -4316885, 616084, 1522888, 5806612, -1071875]),
    ("期初现金及等价物",                                 [324614, 5680235, 5264710, 685314, 2077927, 6109017, 13775087]),
    ("汇兑损益",                                         [-616, 1135, 127555, 171984, 7859, 7065, -261147]),
    ("期末现金及等价物",                                 [821686, 1503622, 1075380, 1473382, 3608674, 11922694, 12442065]),
]


# ====== 跨源比对用: 2026 中报里的比较列 ======
# ① 2025H1 比较列(2026 中报 P63/P69-70, 未经审核)—— 与本表 2025H1 列(取自 2025 中报)逐行比对
比较列_2025H1_损益 = {
    "收益 Revenue": 13876276,
    "销售成本 Cost of sales": -4115212,
    "毛利 Gross profit": 9761064,
    "经销及销售开支 Distribution and selling expenses": -3192590,
    "一般及行政开支 G&A expenses": -770405,
    "金融资产减值(-)/拨回(+)": -746,
    "其他收入 Other income": 67232,
    "其他收益/(亏损)-净": 179186,
    "经营溢利 Operating profit": 6043741,
    "财务收入 Finance income": 93870,
    "财务开支 Finance expenses": -28364,
    "权益法投资溢利": 47625,
    "除所得税前溢利 Profit before income tax": 6156872,
    "所得税开支 Income tax expense": -1475159,
    "期内溢利 Profit for the period": 4681713,
    "归母溢利 Attributable to parent": 4574368,
    "非控股权益溢利 Non-controlling interests": 107345,
}
比较列_2025H1_现金流 = {
    "经营所得现金 Cash generated from operations": 6975420,
    "已收利息": 191679,
    "已付所得税": -1189626,
    "经营活动所得现金净额 Net cash from operating": 5977473,
    "购买 PPE": -353623,
    "购买无形资产": -20900,
    "购买 FVTPL 金融资产": -3092500,
    "存入定期存款": -3946911,
    "赎回定期存款": 5470472,
    "处置 FVTPL 所得款项": 3106184,
    "处置 PPE/无形/使用权资产所得": 5373,
    "收购附属公司现金净额(流入+/流出-)": 65995,
    "投资活动净额 Net cash from investing": 1234090,
    "租赁负债付款": -263592,
    "已付股息": -1083288,
    "非控股权益注资": 33663,
    "收购附属公司非控股权益": -46760,
    "已付非控股股东股息": -44974,
    "融资活动净额 Net cash from financing": -1404951,
    "现金及等价物增加/(减少)净额": 5806612,
    "期初现金及等价物": 6109017,
    "汇兑损益": 7065,
    "期末现金及等价物": 11922694,
}
# ② 2025-12-31 比较列(2026 中报 P65-66, 经审核)—— 与年度 `_build_from_pdf.py` 的 2025 年末逐行比对
比较列_2025年末_资产负债 = {
    "物业厂房设备 PPE": 1417556,
    "无形资产 Intangible assets": 208665,
    "使用权资产 Right-of-use assets": 2791171,
    "受限现金(非流动)": 256265,
    "权益法投资 Equity method investments": 128124,
    "FVTPL金融资产(非流动)": 356906,
    "预付款项及其他非流动资产": 274473,
    "递延所得税资产": 1753551,
    "非流动资产合计": 7186711,
    "贸易应收款": 921240,
    "存货": 5472839,
    "预付款项及其他流动资产": 1283154,
    "FVTPL金融资产(流动)": 9743,
    "受限现金(流动)": 2658,
    "定期存款(3-12个月)": 3449922,
    "现金及等价物": 13775087,
    "流动资产合计": 24914643,
    "总资产": 32101354,
    "股本": 882,
    "股份奖励计划持股": -7,
    "其他储备": 3123058,
    "保留盈利": 19153802,
    "归母权益": 22277735,
    "非控股权益": 374632,
    "总权益": 22652367,
    "应付授权费(非流动)": 5525,
    "租赁负债(非流动)": 2275301,
    "非流动负债合计": 2280826,
    "贸易应付款": 1858216,
    "应付授权费(流动)": 437247,
    "其他应付款": 1777317,
    "合约负债(预收)": 393119,
    "租赁负债(流动)": 586274,
    "即期所得税负债": 2115988,
    "流动负债合计": 7168161,
    "总负债": 9448987,
    "总权益及负债": 32101354,
}

# 表内逐行加总的明细行(合计行除外)
BS_非流动资产明细 = ["物业厂房设备 PPE", "无形资产 Intangible assets", "使用权资产 Right-of-use assets",
                    "受限现金(非流动)", "权益法投资 Equity method investments", "FVTPL金融资产(非流动)",
                    "预付款项及其他非流动资产", "定期存款(一年以上)", "递延所得税资产"]
BS_流动资产明细 = ["贸易应收款", "其他应收款 (独立列示)", "存货", "预付款项及其他流动资产",
                  "FVTPL金融资产(流动)", "受限现金(流动)", "定期存款(3-12个月)", "现金及等价物"]
BS_归母权益明细 = ["股本", "股份奖励计划持股", "其他储备", "保留盈利"]
BS_非流动负债明细 = ["应付授权费(非流动)", "租赁负债(非流动)", "递延所得税负债"]
BS_流动负债明细 = ["贸易应付款", "应付授权费(流动)", "其他应付款", "合约负债(预收)", "借款(流动)",
                  "租赁负债(流动)", "即期所得税负债"]
PL_经营溢利明细 = ["毛利 Gross profit", "经销及销售开支 Distribution and selling expenses",
                  "一般及行政开支 G&A expenses", "金融资产减值(-)/拨回(+)", "其他收入 Other income",
                  "其他收益/(亏损)-净"]
PL_税前明细 = ["经营溢利 Operating profit", "财务收入 Finance income", "财务开支 Finance expenses",
              "可换股优先股公平值变动", "权益法投资溢利"]
CF_经营明细 = ["经营所得现金 Cash generated from operations", "已收利息", "已付所得税"]
CF_投资明细 = ["购买 PPE", "购买无形资产", "购买 FVTPL 金融资产", "存入定期存款",
              "定期存款净变(存入-赎回, 2021-2023 中报合并列示)", "赎回定期存款", "处置 FVTPL 所得款项",
              "处置 PPE/无形/使用权资产所得", "按公平值计入损益的金融资产投资收入(旧格式)",
              "于一家联营公司的投资", "收到合营企业股息", "收购附属公司现金净额(流入+/流出-)"]
CF_融资明细 = ["租赁负债付款", "已付股息", "股份回购付款", "偿还借款", "非控股权益注资", "收购附属公司非控股权益",
              "已付非控股股东股息", "上市开支付款", "股东注资", "视作分派予当时股东", "发行可换股可赎回优先股"]


# ====== 勾稽自洽校验 (容差 0 · 空值计数) ======
def value(table, key, idx):
    for row_key, row_vals in table:
        if row_key == key:
            return row_vals[idx]
    raise KeyError(f"表内无科目: {key}")


def line_sum(table, keys, idx):
    """明细行加总; 空值 = 该期报表无此行, 按 0 计(由合计行仲裁)。"""
    return sum(value(table, k, idx) or 0 for k in keys)


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


def annual_bs(h1_key, year):
    mod = annual_module()
    hits = [vals for k, vals in mod.资产负债表 if k == h1_key or k.startswith(h1_key + " ")]
    if len(hits) != 1:
        raise KeyError(f"年度资产负债表找不到唯一对应科目: {h1_key} (命中 {len(hits)})")
    return hits[0][mod.YEARS.index(year)]


def check():
    errors = []
    stats = {"executed": 0, "skipped": 0}

    def eq(label, a, b, tol=0):
        if a is None or b is None:
            stats["skipped"] += 1
            return
        stats["executed"] += 1
        if abs(a - b) > tol:
            errors.append(f"{label}: {a} vs {b} (差 {a - b:+})")

    for i, p in enumerate(H1_PERIODS):
        pl = lambda k: value(利润表_H1, k, i)
        bs = lambda k: value(资产负债表_H1, k, i)
        cf = lambda k: value(现金流量表_H1, k, i)

        # 损益
        eq(f"[{p}] 毛利 = 收益 + 销售成本", pl("收益 Revenue") + pl("销售成本 Cost of sales"), pl("毛利 Gross profit"))
        eq(f"[{p}] 经营溢利 = 毛利及各费用收益行加总", line_sum(利润表_H1, PL_经营溢利明细, i), pl("经营溢利 Operating profit"))
        eq(f"[{p}] 税前 = 经营溢利 + 财务收支 + 其他", line_sum(利润表_H1, PL_税前明细, i), pl("除所得税前溢利 Profit before income tax"))
        eq(f"[{p}] 净利 = 税前 + 所得税",
           pl("除所得税前溢利 Profit before income tax") + pl("所得税开支 Income tax expense"), pl("期内溢利 Profit for the period"))
        eq(f"[{p}] 归母 + 非控股 = 净利",
           pl("归母溢利 Attributable to parent") + pl("非控股权益溢利 Non-controlling interests"), pl("期内溢利 Profit for the period"))

        # 资产负债
        eq(f"[{p}] 非流动资产逐行加总", line_sum(资产负债表_H1, BS_非流动资产明细, i), bs("非流动资产合计"))
        eq(f"[{p}] 流动资产逐行加总", line_sum(资产负债表_H1, BS_流动资产明细, i), bs("流动资产合计"))
        eq(f"[{p}] 总资产 = 非流动 + 流动", bs("非流动资产合计") + bs("流动资产合计"), bs("总资产"))
        eq(f"[{p}] 归母权益逐行加总", line_sum(资产负债表_H1, BS_归母权益明细, i), bs("归母权益"))
        eq(f"[{p}] 总权益 = 归母 + 非控股", bs("归母权益") + bs("非控股权益"), bs("总权益"))
        eq(f"[{p}] 非流动负债逐行加总", line_sum(资产负债表_H1, BS_非流动负债明细, i), bs("非流动负债合计"))
        eq(f"[{p}] 流动负债逐行加总", line_sum(资产负债表_H1, BS_流动负债明细, i), bs("流动负债合计"))
        eq(f"[{p}] 总负债 = 非流动 + 流动", bs("非流动负债合计") + bs("流动负债合计"), bs("总负债"))
        eq(f"[{p}] 资产 = 负债 + 权益", bs("总负债") + bs("总权益"), bs("总资产"))
        eq(f"[{p}] 总权益及负债 = 总资产", bs("总权益及负债"), bs("总资产"))

        # 现金流
        eq(f"[{p}] 经营现金净额逐行加总", line_sum(现金流量表_H1, CF_经营明细, i), cf("经营活动所得现金净额 Net cash from operating"))
        eq(f"[{p}] 投资现金净额逐行加总", line_sum(现金流量表_H1, CF_投资明细, i), cf("投资活动净额 Net cash from investing"))
        eq(f"[{p}] 融资现金净额逐行加总", line_sum(现金流量表_H1, CF_融资明细, i), cf("融资活动净额 Net cash from financing"))
        eq(f"[{p}] 经营 + 投资 + 融资 = 净变动",
           cf("经营活动所得现金净额 Net cash from operating") + cf("投资活动净额 Net cash from investing")
           + cf("融资活动净额 Net cash from financing"), cf("现金及等价物增加/(减少)净额"))
        eq(f"[{p}] 期初 + 净变动 + 汇兑 = 期末",
           cf("期初现金及等价物") + cf("现金及等价物增加/(减少)净额") + cf("汇兑损益"), cf("期末现金及等价物"))
        eq(f"[{p}] CF 期末 = BS 现金", cf("期末现金及等价物"), bs("现金及等价物"))

        # 跨表: 期初现金 = 年度资产负债表上年末现金
        year = int(p[:4]) - 1
        eq(f"[{p}] CF 期初 = 年度 BS {year} 年末现金", cf("期初现金及等价物"), annual_bs("现金及等价物", year))

    # 跨源 ①: 2026 中报的 2025H1 比较列
    i25 = H1_PERIODS.index("2025H1")
    for k, v in 比较列_2025H1_损益.items():
        eq(f"[2025H1 比较列] 损益 {k}", v, value(利润表_H1, k, i25))
    for k, v in 比较列_2025H1_现金流.items():
        eq(f"[2025H1 比较列] 现金流 {k}", v, value(现金流量表_H1, k, i25))
    # 跨源 ②: 2026 中报的 2025-12-31 比较列 vs 年度 2025 年末
    for k, v in 比较列_2025年末_资产负债.items():
        eq(f"[2025-12-31 比较列] 资产负债 {k}", v, annual_bs(k, 2025))

    return errors, stats


# ====== 变异对照: 逐格 +1 看勾稽能否抓到 ======
def mutation_test(show_list=False):
    targets = []
    for tname, table in (("利润表_H1", 利润表_H1), ("资产负债表_H1", 资产负债表_H1), ("现金流量表_H1", 现金流量表_H1)):
        for row_key, row_vals in table:
            for i, v in enumerate(row_vals):
                if v is not None:
                    targets.append((tname, row_key, H1_PERIODS[i], row_vals, i))
    for dname, d in (("比较列_2025H1_损益", 比较列_2025H1_损益), ("比较列_2025H1_现金流", 比较列_2025H1_现金流),
                     ("比较列_2025年末_资产负债", 比较列_2025年末_资产负债)):
        for k in d:
            targets.append((dname, k, "-", d, k))

    caught, missed = 0, []
    for tname, row_key, period, holder, idx in targets:
        original = holder[idx]
        holder[idx] = original + 1
        errors, _ = check()
        holder[idx] = original
        if errors:
            caught += 1
        else:
            missed.append(f"{tname} · {row_key} · {period}")
    total = len(targets)
    print(f"变异对照: 共 {total} 个数值格逐格 +1, 被勾稽捕获 {caught} 个 ({caught / total:.1%}), 未覆盖 {len(missed)} 个")
    if show_list:
        for m in missed:
            print(f"  未覆盖: {m}")


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
        eq_parent = get(资产负债表_H1, "归母权益", i)
        tl = get(资产负债表_H1, "总负债", i)
        ar = get(资产负债表_H1, "贸易应收款", i)
        inv = get(资产负债表_H1, "存货", i)
        ap = get(资产负债表_H1, "贸易应付款", i)
        goods_cost = get(利润表_H1, "销售成本 Cost of sales", i)
        goods_cost = -goods_cost if goods_cost is not None else None
        cash = get(资产负债表_H1, "现金及等价物", i)
        td = get(资产负债表_H1, "定期存款(3-12个月)", i)
        td_long = get(资产负债表_H1, "定期存款(一年以上)", i)
        cash_td = (cash or 0) + (td or 0) + (td_long or 0) if cash is not None else None
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
        w.writerow(["# H1 派生比率, 从 H1 三表算出, 半年口径(不年化), 单位见字段名; 现金+定存含一年以上定期存款(2026H1 起单列)"])
        w.writerow(list(rows[0].keys()))
        for r in rows:
            w.writerow(r.values())


def main():
    if "--mutate" in sys.argv:
        mutation_test(show_list="--list" in sys.argv)
        return
    errors, stats = check()
    if errors:
        print("❌ H1 勾稽校验失败,不写出 CSV:")
        for e in errors:
            print(f"  {e}")
        return
    print(f"✅ H1 勾稽校验全部通过: 执行 {stats['executed']} 条, 因空值跳过 {stats['skipped']} 条 (容差 0)")
    header = ["科目"] + H1_PERIODS
    write_csv("利润表-H1.csv", 利润表_H1, header)
    write_csv("资产负债表-H1.csv", 资产负债表_H1, header)
    write_csv("现金流量表-H1.csv", 现金流量表_H1, header)
    rows = build_ratios()
    write_ratios(rows)
    print(f"已写出 4 个 -H1.csv → {OUT}")


if __name__ == "__main__":
    main()
