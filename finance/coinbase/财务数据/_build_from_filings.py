#!/usr/bin/env python3
"""Coinbase Global, Inc.(NASDAQ: COIN, CIK 1679788)三表构建器。

数据源(一手·双轨互证):
  ①转录轨(canonical):report/coinbase/ 一手申报印刷报表逐行转录 ——
     424B4(2021-04-14 直接上市最终招股说明书,FY2019/FY2020 两年经审计财务的唯一真源)
     + 10-K FY2021/FY2022/FY2023/FY2024/FY2025(各年主表)
     取数政策 = **各年取「当年自身年报原始披露值」(as-reported)**;后续年报的重述值
     不覆盖 canonical,而是单独落 `重述与口径变更.csv`(见下「三大口径断点」)。
  ②XBRL 轨(独立核):_xbrl/companyfacts-CIK0001679788.json(SEC 机读·公司自报)
     逐格与转录轨比对(容差 0),不一致即报错。

单位:千美元(USD thousands,与申报印刷口径一致);**费用/流出 = 负数**。
年份序列 2019-2025(七年):
  起点 = 424B4 披露的最早经审计年度 = FY2019。Coinbase 上市时为 EGC,招股书只列
  两年(FY2019/FY2020)而非三年;FY2018 三表全表**实证不可得**——全库仅存 3 个
  期初余额点(2018-12-31 现金 1,987,139 / 权益 500,071 / 未确认税务利益 6,605),
  已落 `重述与口径变更.csv` 备注,不构造 FY2018 列。

⚠️ 三大口径断点(使跨年直接相减失效,勾稽按「每份申报自身presentation」内部闭合):
  A. SAB 121 → SAB 122(2024-12-31 追溯采用):2022/2023 资产负债表曾把
     「保管客户加密资产/负债」总额计入表内(2023 达 192,583,060),FY2024 10-K
     追溯剔除 → 2023 总资产 206,982,953 变 14,753,901。
  B. 客户托管资金流(2021→2022 重分类):FY2021 10-K 把「客户托管资金负债变动」
     放**经营**活动(2021 经营现金流 10,730,031);FY2022 起改放**融资**活动
     (2021 重述为 4,038,172,差额恰为 6,691,859)。→ 现金含量口径反转。
  C. 支付稳定币改记现金等价物(FY2025 自愿变更·追溯):USDC/EURC/PYUSD 由
     ASC 310 应收改列 Cash and cash equivalents,2023/2024 现金与借贷科目被追溯重列
     (2024 现金 8,543,903 → 9,308,266)。对总资产/权益/净利/EPS 无影响。
  另:ASU 2023-08(2024-01-01 采用·累积影响法非追溯)把自持加密资产由
     「成本减减值」改为**公允价值**,期初留存收益 +561,489 —— 2023 及以前的
     加密资产相关损益行与 2024 起**不可比**(利润表口径断点,但净利未被重述)。

勾稽(任一不过 → 不写出 CSV):
  利润表:总收入=净收入+其他收入;总收入+总经营费用=经营利润;
          经营利润+线下各项=税前;税前+所得税=净利(逐年)
  资产负债表:流动资产分项和=流动资产合计;总资产=流动+非流动;
          总资产=总负债+夹层(可转优先股)+权益;权益分项和=权益合计
  现金流量表:三活动+汇率=现金净变动;年初+净变动+汇率=年末;
          年末现金=(现金+受限现金+客户托管现金)对账表
  分部:各年收入拆分和=利润表总收入(按类型/按地区两套各自平)
"""
import csv
import json
import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(DIR)))
YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025]
N = len(YEARS)

# 各年 canonical 来源(as-reported)
SOURCE = {
    2019: "424B4(2021-04-14) F-4/F-6/F-8",
    2020: "424B4(2021-04-14) F-4/F-6/F-8",
    2021: "10-K FY2021 P117/118/121",
    2022: "10-K FY2022 P127/129/131",
    2023: "10-K FY2023 P125/126/129",
    2024: "10-K FY2024 P120/121/124",
    2025: "10-K FY2025 P116/117/120",
}


def R(*vals):
    """按 YEARS 顺序给值;None = 该年申报无此科目(留空)。"""
    assert len(vals) == N, f"需 {N} 个值,给了 {len(vals)}"
    return {y: v for y, v in zip(YEARS, vals) if v is not None}


# ============================================================
# ① 利润表(千美元;费用/流出=负;None=该年 presentation 无此行)
#    ⚠️ 收入/总费用/经营利润/净利 七年**从未被重述**(XBRL 已证),故此表跨年可比;
#       仅「经营费用明细」与「线下明细」的拆分粒度逐年变化(as-reported)。
# ============================================================
INCOME_ROWS = [
    ("净收入 Net revenue",
     R(482_949, 1_141_167, 7_354_753, 3_148_815, 2_926_540, 6_293_246, 6_883_438)),
    ("其他收入 Other revenue",
     R(50_786, 136_314, 484_691, 45_393, 181_843, 270_782, 297_887)),
    ("总收入 Total revenue",
     R(533_735, 1_277_481, 7_839_444, 3_194_208, 3_108_383, 6_564_028, 7_181_325)),
    # --- 经营费用(负) ---
    ("交易费用 Transaction expense",
     R(-82_055, -135_514, -1_267_924, -629_880, -420_705, -897_707, -1_020_230)),
    ("技术与开发 Technology and development",
     R(-185_044, -271_732, -1_291_561, -2_326_354, -1_324_541, -1_468_252, -1_670_605)),
    ("销售与营销 Sales and marketing",
     R(-24_150, -56_782, -663_689, -510_089, -332_312, -654_444, -1_058_577)),
    ("一般及行政 General and administrative",
     R(-231_929, -279_880, -909_392, -1_600_586, -1_041_308, -1_300_257, -1_619_642)),
    # ⚠️ 2021/2022 as-reported 把加密资产减值并在「其他经营费用净额」内,未单列;
    #    FY2023 10-K 才把该行拆出(并追溯拆了 2021/2022 比较列)。此处按 as-reported。
    ("加密资产减值净额 Crypto asset impairment, net(仅 FY2023 as-reported 单列)",
     R(None, None, None, None, 34_675, None, None)),
    ("经营性加密资产损益净额 (Losses) gains on crypto held for operations(ASU2023-08 后)",
     R(None, None, None, None, None, 71_725, -20_704)),
    ("重组 Restructuring",
     R(-10_140, None, None, -40_703, -142_594, None, None)),
    ("其他经营费用净额 Other operating expense, net",
     R(-46_200, -124_622, -630_308, -796_804, -43_260, -7_933, -356_126)),
    ("总经营费用 Total operating expenses",
     R(-579_518, -868_530, -4_762_874, -5_904_416, -3_270_045, -4_256_868, -5_745_884)),
    ("经营利润 Operating income (loss)",
     R(-45_783, 408_951, 3_076_570, -2_710_208, -161_662, 2_307_160, 1_435_441)),
    # --- 经营线以下(负=费用/损失) ---
    ("利息费用 Interest expense",
     R(None, None, None, -88_901, -82_766, -80_645, -85_413)),
    ("投资性加密资产损益净额 (Losses) gains on crypto held for investment(ASU2023-08 后)",
     R(None, None, None, None, None, 687_055, -528_857)),
    ("其他收入(费用)净额 Other income (expense), net",
     R(367, 248, -49_623, -265_473, 167_583, 29_074, 700_894)),
    ("税前利润 Income (loss) before income taxes",
     R(-45_416, 409_199, 3_026_947, -3_064_582, -76_845, 2_942_644, 1_522_065)),
    ("所得税(费用)收益 (Provision for) benefit from income taxes",
     R(15_029, -86_882, 597_173, 439_633, 171_716, -363_578, -261_738)),
    ("净利润 Net income (loss)",
     R(-30_387, 322_317, 3_624_120, -2_624_949, 94_871, 2_579_066, 1_260_327)),
    # --- 每股 ---
    ("归属普通股股东净利-基本 Net income attributable to common - Basic",
     R(-30_387, 108_256, 3_096_958, -2_624_949, 94_752, 2_577_755, 1_260_327)),
    ("归属普通股股东净利-稀释 Net income attributable to common - Diluted",
     R(-30_387, 127_471, 3_190_404, -2_631_179, 94_751, 2_591_248, 1_277_314)),
    ("每股收益-基本(美元) EPS Basic",
     R(-0.50, 1.58, 17.47, -11.81, 0.40, 10.42, 4.85)),
    ("每股收益-稀释(美元) EPS Diluted",
     R(-0.50, 1.40, 14.50, -11.83, 0.37, 9.48, 4.45)),
    ("加权平均股数-基本(千股) WA shares Basic",
     R(61_317, 68_671, 177_319, 222_314, 235_796, 247_374, 260_088)),
    ("加权平均股数-稀释(千股) WA shares Diluted",
     R(61_317, 91_209, 219_965, 222_338, 254_391, 273_377, 287_209)),
    # --- 综合收益 ---
    ("外币折算调整(税后) Translation adjustment, net of tax",
     R(-43, 6_977, -9_651, -35_211, 8_336, -19_781, 55_024)),
    ("综合收益 Comprehensive income (loss)",
     R(-30_430, 329_294, 3_614_469, -2_660_160, 103_207, 2_559_285, 1_315_351)),
]

# ============================================================
# ② 资产负债表(千美元;负债/权益为正列示;None=该年无此行)
#    ⚠️ 2022/2023 含 SAB 121 保管客户加密资产总额(断点 A)
# ============================================================
BS_ROWS = [
    ("【资产】现金及现金等价物 Cash and cash equivalents",
     R(548_945, 1_061_850, 7_123_478, 4_425_021, 5_139_351, 8_543_903, 11_285_452)),
    ("受限现金(及等价物) Restricted cash (and cash equivalents)",
     R(34_122, 30_787, 30_951, 25_873, 22_992, 38_519, 334_318)),
    ("USDC(2019-2024 单列·FY2025 起并入现金等价物)",
     R(88_429, 48_938, 100_096, 861_149, 576_028, 1_241_808, None)),
    ("客户托管资金 Customer custodial funds",
     R(1_201_350, 3_763_392, 10_526_233, 5_041_119, 4_570_845, 6_158_949, 5_347_428)),
    ("保管客户加密资产 Safeguarding customer crypto assets(SAB121·仅2022-2023)",
     R(None, None, None, 75_413_188, 192_583_060, None, None)),
    ("经营用加密资产 Crypto assets held for operations",
     R(None, None, None, None, None, 82_781, 120_831)),
    ("贷款应收 Loan receivables",
     R(None, None, None, None, None, 475_370, 1_354_692)),
    ("作为抵押品的加密资产 Crypto assets held as collateral",
     R(None, None, None, None, None, 767_484, 822_827)),
    ("借入的加密资产 Crypto assets borrowed",
     R(None, None, None, None, None, 261_052, 318_849)),
    ("应收账款净额 Accounts receivable, net",
     R(17_496, None, None, None, None, 265_251, 307_119)),
    ("应收账款及贷款净额 Accounts and loans receivable, net(合并列示年份)",
     R(None, 189_471, 396_025, 404_376, 361_715, None, None)),
    ("可交易投资 Marketable investments",
     R(None, None, None, None, None, None, 309_765)),
    ("应收所得税 Income tax receivable",
     R(74_171, None, 61_231, 60_441, 63_726, None, None)),
    ("预付费用及其他流动资产 Prepaid expenses and other current assets",
     R(22_433, 39_510, 135_849, 217_048, 148_814, 277_536, 187_164)),
    ("流动资产合计 Total current assets",
     R(1_986_946, 5_133_948, 18_373_863, 86_448_215, 203_466_531, 18_112_653, 20_388_445)),
    ("持有的加密资产 Crypto assets held(ASU2023-08 前合并列示)",
     R(33_932, 316_094, 988_193, 424_393, 449_925, None, None)),
    ("投资用加密资产 Crypto assets held for investment(ASU2023-08 后·公允价值)",
     R(None, None, None, None, None, 1_552_995, 1_998_871)),
    ("战略投资 Strategic investments",
     R(None, None, None, None, None, None, 622_985)),
    ("递延所得税资产 Deferred tax assets",
     R(None, None, None, None, 1_272_233, 941_298, 570_819)),
    ("租赁使用权资产 Lease right-of-use assets",
     R(123_386, 100_845, 98_385, 69_357, 12_737, None, None)),
    ("固定资产净额 Property and equipment, net / Software and equipment, net",
     R(47_117, 49_250, 59_230, 171_853, 192_550, 200_080, 264_573)),
    ("商誉 Goodwill",
     R(54_696, 77_212, 625_758, 1_073_906, 1_139_670, 1_139_670, 4_168_967)),
    ("无形资产净额 Intangible assets, net",
     R(70_137, 60_825, 176_689, 135_429, 86_422, 46_804, 1_397_794)),
    ("其他非流动资产 Other non-current assets",
     R(75_555, 117_240, 952_307, 1_401_720, 362_885, 548_451, 259_378)),
    ("总资产 Total assets",
     R(2_391_769, 5_855_414, 21_274_425, 89_724_873, 206_982_953, 22_541_951, 29_671_832)),
    # --- 负债 ---
    ("【负债】应付客户托管资金 Custodial funds due to customers / Customer custodial fund liabilities",
     R(1_106_815, 3_849_468, 10_480_612, 4_829_587, 4_570_845, 6_158_949, 5_347_428)),
    ("保管客户加密负债 Safeguarding customer crypto liabilities(SAB121·仅2022-2023)",
     R(None, None, None, 75_413_188, 192_583_060, None, None)),
    ("应付账款 Accounts payable",
     R(None, 12_031, 39_833, 56_043, 39_294, 63_316, 117_605)),
    ("应付账款及应计费用 Accounts payable and accrued expenses(2019 合并列示)",
     R(45_453, None, None, None, None, None, None)),
    ("应计费用及其他流动负债 Accrued expenses and other current liabilities",
     R(None, 88_783, 439_559, 331_236, 447_050, 626_820, 687_676)),
    ("其他流动负债 Other current liabilities(2019 单列)",
     R(47_401, None, None, None, None, None, None)),
    ("加密资产借款 Crypto asset borrowings",
     R(None, 271_303, 426_665, 151_505, 62_980, 300_110, None)),
    ("短期借款 Short-term borrowings",
     R(None, None, None, None, None, None, 452_105)),
    ("长期债务-一年内到期 Current portion of long-term debt",
     R(None, None, None, None, None, None, 1_269_585)),
    ("应返还抵押品义务 Obligation to return collateral",
     R(None, None, None, None, None, 792_125, 826_883)),
    ("租赁负债-流动 Lease liabilities, current",
     R(23_775, 25_270, 32_366, 33_734, 10_902, None, None)),
    ("流动负债合计 Total current liabilities",
     R(1_223_444, 4_246_855, 11_419_035, 80_815_293, 197_714_131, 7_941_320, 8_701_282)),
    ("租赁负债-非流动 Lease liabilities, non-current",
     R(106_542, 82_508, 74_078, 42_044, 3_821, None, None)),
    ("长期债务 Long-term debt",
     R(None, None, 3_384_795, 3_393_448, 2_979_957, 4_234_081, 5_937_034)),
    ("其他非流动负债 Other non-current liabilities",
     R(None, None, 14_828, 19_531, 3_395, 89_708, 240_458)),
    ("总负债 Total liabilities",
     R(1_329_986, 4_329_363, 14_892_736, 84_270_316, 200_701_304, 12_265_109, 14_878_774)),
    # --- 夹层 + 权益 ---
    ("可转换优先股(夹层) Convertible preferred stock",
     R(564_697, 562_467, None, None, None, None, None)),
    ("普通股面值 Common stock (Class A+B, par)",
     R(0, 0, 2, 2, 2, 2, 3)),
    ("资本公积 Additional paid-in capital",
     R(93_820, 231_024, 2_034_658, 3_767_686, 4_491_571, 5_365_990, 8_566_854)),
    ("累计其他综合收益(损失) AOCI",
     R(-721, 6_256, -3_395, -38_606, -30_270, -50_051, 4_973)),
    ("留存收益 Retained earnings",
     R(403_987, 726_304, 4_350_424, 1_725_475, 1_820_346, 4_960_901, 6_221_228)),
    ("股东权益合计 Total stockholders' / shareholders' equity",
     R(497_086, 963_584, 6_381_689, 5_454_557, 6_281_649, 10_276_842, 14_793_058)),
    ("负债+夹层+权益合计 Total L + mezzanine + E",
     R(2_391_769, 5_855_414, 21_274_425, 89_724_873, 206_982_953, 22_541_951, 29_671_832)),
]

# ============================================================
# ③ 现金流量表(千美元;流出=负;None=该年 presentation 无此行)
#    ⚠️ 断点 B(客户托管资金 经营→融资)与断点 C(稳定币改现金)使
#       「经营/投资/融资净额」跨年不可比 —— 已在 `重述与口径变更.csv` 全列;
#       本表 canonical = 当年原披露值,可比口径见 财务比率.csv 派生行。
# ============================================================
CF_ROWS = [
    ("【经营】净利润 Net income (loss)",
     R(-30_387, 322_317, 3_624_120, -2_624_949, 94_871, 2_579_066, 1_260_327)),
    ("折旧与摊销 Depreciation and amortization",
     R(16_878, 30_962, 63_651, 154_069, 139_642, 127_518, 188_428)),
    ("股权薪酬费用 Stock-based compensation expense",
     R(31_147, 70_548, 820_685, 1_565_823, 780_668, 912_838, 839_440)),
    ("重组相关股权薪酬 Restructuring stock-based compensation",
     R(None, None, None, None, 84_042, None, None)),
    ("减值费用(合并列示) Impairment expense",
     R(2_252, 8_355, 329_652, None, None, None, None)),
    ("加密资产减值费用 Crypto asset impairment expense(ASU2023-08 前)",
     R(None, None, None, 757_257, 96_783, None, None)),
    ("投资减值费用 Investment impairment expense",
     R(None, None, None, 101_445, 29_375, 18_717, None)),
    ("其他减值费用 Other impairment expense",
     R(None, None, None, 26_518, 18_793, None, None)),
    ("递延所得税 Deferred income taxes",
     R(-20_903, 474, -558_329, -468_035, -216_334, 151_315, 238_308)),
    ("经营性加密资产损益 (Gains) losses on crypto held for operations",
     R(None, None, None, None, None, -71_725, 20_704)),
    ("投资性加密资产损益 (Gains) losses on crypto held for investment",
     R(None, None, None, None, None, -687_055, 528_857)),
    # 2024 as-reported 无此行(并入「其他经营活动净额 4,172」);FY2025 比较列才单列 11,553
    ("投资(收益)损失净额 (Gains) losses on investments, net",
     R(245, 150, -20_138, 3_056, -50_121, None, -680_520)),
    ("债务清偿收益净额 Gains on extinguishment of long-term debt, net",
     R(None, None, None, None, -117_383, None, None)),
    ("加密资产已实现损益 Realized (gain) loss on crypto assets(ASU2023-08 前)",
     R(5_662, -23_682, -178_234, -36_666, -145_594, None, None)),
    ("加密资产作为收入收取(非现金) Crypto assets received as revenue(ASU2023-08 前)",
     R(-11_408, -94_158, -1_015_920, -470_591, -460_878, None, None)),
    ("以加密资产支付费用(非现金) Crypto asset payments for expenses(ASU2023-08 前)",
     R(11_622, 40_205, 815_783, 383_221, 298_255, None, None)),
    ("交易损失及坏账计提 Provision for transaction losses and doubtful accounts",
     R(-4_679, -2_966, 22_390, -13_051, 11_059, None, None)),
    ("非现金租赁费用 Non-cash lease expense",
     R(13_323, 25_012, 34_542, 31_123, 40_429, None, None)),
    ("衍生品公允价值(收益)损失 Fair value (gain) loss on derivatives",
     R(None, 5_254, -32_056, 7_410, -41_033, None, None)),
    ("外汇未实现(收益)损失 Unrealized (gain) loss on foreign exchange",
     R(-3_106, 1_057, -14_944, 28_516, 17_190, None, None)),
    ("处置固定资产(收益)损失 Loss (gain) on disposal of property and equipment",
     R(9_073, 355, 1_425, -58, None, None, None)),
    ("或有对价公允价值变动 Change in fair value of contingent consideration",
     R(None, 3_281, -924, -8_312, None, None, None)),
    ("债务折价及发行费摊销 Amortization of debt discount and issuance costs",
     R(None, None, 5_031, 9_253, None, None, None)),
    ("其他经营活动净额 Other operating activities, net",
     R(None, None, None, None, 16_981, 4_172, 62_246)),
    # --- 营运资本变动:2019-2022 与 2025 印刷逐项;2023/2024 印刷单行小计 ---
    ("营运资本:USDC",
     R(35_303, 37_936, -77_471, -848_138, None, None, None)),
    ("营运资本:应收账款(及贷款) Accounts (and loans) receivable",
     R(30_703, -157_156, -8_016, -141_023, None, None, -1_983)),
    ("营运资本:在途存款/客户托管资金在途 Deposits / customer custodial funds in transit",
     R(None, None, None, 28_952, None, None, 57_152)),
    ("营运资本:所得税净额 Income taxes, net",
     R(-1_912, 86_791, -62_145, 1_906, None, None, -147_449)),
    ("营运资本:其他流动及非流动资产 Other current and non-current assets",
     R(-38_594, -48_677, -20_060, 19_237, None, None, -47_228)),
    ("营运资本:应付客户托管资金(**经营口径**·仅 2019-2021 as-reported) Custodial funds due to customers",
     R(-130_122, 2_710_522, 6_691_859, None, None, None, None)),
    ("营运资本:应付账款(及应计费用) Accounts payable (and accrued expenses)",
     R(-788, 20_837, 27_330, 18_612, None, None, None)),
    ("营运资本:租赁负债 Lease liabilities",
     R(-11_025, -24_998, -20_596, -10_223, None, None, None)),
    ("营运资本:其他流动及非流动负债 Other current and non-current liabilities",
     R(16_122, -8_349, 302_396, -100_771, None, None, 108_101)),
    ("营运资本变动合计(印刷单行·仅 2023/2024) Net changes in operating assets and liabilities",
     R(None, None, None, None, 326_206, -478_002, None)),
    ("经营活动现金流净额(当年原披露) Net cash provided by (used in) operating activities",
     R(-80_594, 3_004_070, 10_730_031, -1_585_419, 922_951, 2_556_844, 2_426_383)),
    # --- 投资 ---
    ("【投资】购建固定资产 Purchase of property and equipment",
     R(-33_521, -9_913, -2_910, -2_933, None, None, None)),
    ("处置固定资产所得 Proceeds from sale of property and equipment",
     R(2_293, None, 31, 83, None, None, None)),
    ("资本化内部开发软件(现金) Capitalized internal-use software development costs",
     R(-6_950, -8_889, -22_073, -61_038, -63_202, None, None)),
    ("业务并购净现金 Business combinations, net of cash acquired",
     R(-5_698, 33_615, -70_911, -186_150, -30_730, None, -742_038)),
    ("购买投资 Purchase of investments",
     R(-7_938, -10_329, -326_513, -63_048, -11_822, None, -377_426)),
    ("处置/结算投资 Dispositions / settlement of investments",
     R(374, 303, 5_159, 1_551, None, None, 490_298)),
    ("资产收购 Asset acquisition",
     R(-55_389, None, None, None, None, None, None)),
    ("购买人才团队 Purchase of assembled workforce",
     R(None, None, -60_800, None, None, None, None)),
    ("发放贷款 Loans originated (fiat / all)",
     R(None, None, -336_189, -207_349, -586_691, -1_700_055, -12_453_223)),
    ("贷款回收 Proceeds from repayment of loans",
     R(None, None, 124_520, 327_539, 513_698, 1_488_500, 11_664_530)),
    ("质押抵押品 Assets pledged as collateral",
     R(None, None, None, -41_630, -27_899, None, -16_009)),
    ("质押抵押品返还 Assets pledged as collateral returned",
     R(None, None, None, None, 68_338, None, 16_188)),
    ("购买加密资产 Purchase of crypto assets held(ASU2023-08 前)",
     R(-271_266, -528_080, -3_009_086, -1_400_032, -277_367, None, None)),
    ("处置加密资产 Disposal of crypto assets held(ASU2023-08 前)",
     R(272_742, 574_115, 2_574_032, 969_185, 461_325, None, None)),
    ("购买投资用加密资产 Purchases of crypto assets held for investment",
     R(None, None, None, None, None, None, -787_821)),
    ("处置投资用加密资产 Dispositions of crypto assets held for investment",
     R(None, None, None, None, None, None, 266_546)),
    ("加密期货合约结算 Settlement of crypto futures contract",
     R(None, None, None, None, -43_339, None, None)),
    ("其他投资活动净额 Other investing activities, net",
     R(None, None, None, None, 3_081, -70_830, -110_595)),
    ("投资活动现金流净额(当年原披露) Net cash provided by (used in) investing activities",
     R(-105_353, 50_822, -1_124_740, -663_822, 5_392, -282_385, -2_049_550)),
    # --- 融资 ---
    ("【融资】期权行权发行普通股净额 Issuance of common stock upon exercise of stock options, net",
     R(4_353, 20_731, 217_064, 51_497, 47_944, 126_140, 78_286)),
    ("回购股权激励支付现金 Cash paid to repurchase equity awards",
     R(-20_958, -1_930, None, None, None, None, None)),
    ("认股权证行权 Issuance of shares from exercise of warrants",
     R(None, None, 433, None, None, None, None)),
    ("ESPP 所得 Proceeds received under the ESPP",
     R(None, None, 19_889, 20_848, 16_297, None, None)),
    ("股权激励净额结算代缴税款 Taxes paid related to net share settlement of equity awards",
     R(None, None, -262_794, -351_867, -277_798, -117_225, -402_791)),
    ("发行可转换优先票据净额 Issuance of convertible senior notes, net",
     R(None, None, 1_403_753, None, None, 1_246_025, 2_957_135)),
    ("发行高级票据净额 Issuance of senior notes, net",
     R(None, None, 1_976_011, None, None, None, None)),
    ("购买上限看涨期权 Purchases of capped calls",
     R(None, None, -90_131, None, None, -104_110, -224_250)),
    ("偿还长期债务 Repayment of long-term debt",
     R(None, None, None, None, -303_533, None, None)),
    ("回购普通股 Repurchase of common stock",
     R(None, None, None, None, None, None, -790_195)),
    # ⚠️ 2021 as-reported 该项在**经营**活动(见上「营运资本:应付客户托管资金」);
    #    FY2022 起改列融资 —— 断点 B。
    ("客户托管资金负债变动(**融资口径**·2022 起) Customer custodial (cash) fund liabilities",
     R(None, None, None, -5_562_558, -274_822, 1_638_087, -936_205)),
    ("收取客户抵押品 Customer / fiat collateral received",
     R(None, None, None, None, 66_014, 567_806, 871_389)),
    ("返还客户抵押品 Customer / fiat collateral returned",
     R(None, None, None, None, -64_952, -544_228, -891_967)),
    ("短期借款所得 Proceeds from short-term borrowings",
     R(None, None, 20_000, 190_956, 31_640, None, 626_428)),
    ("短期借款偿还 Repayments of short-term borrowings",
     R(None, None, None, -191_073, -52_122, None, -580_664)),
    ("其他融资活动净额 Other financing activities, net",
     R(None, None, None, 3_679, None, 16_426, 33_116)),
    ("融资活动现金流净额(当年原披露) Net cash provided by (used in) financing activities",
     R(-16_605, 18_801, 3_284_225, -5_838_518, -811_332, 2_828_921, 740_282)),
    # --- 汇总 ---
    ("现金净增(减) Net increase (decrease) in cash",
     R(-202_552, 3_073_693, 12_889_516, -8_087_759, 117_011, 5_103_380, 1_117_115)),
    ("汇率影响 Effect of exchange rates on cash",
     R(-170, -2_081, -64_883, -163_257, 8_772, -48_367, 92_850)),
    ("期初现金(含受限及客户托管现金) Cash, beginning of period",
     R(1_987_139, 1_784_417, 4_856_029, 17_680_662, 9_429_646, 9_555_429, 15_683_455)),
    ("期末现金(含受限及客户托管现金) Cash, end of period",
     R(1_784_417, 4_856_029, 17_680_662, 9_429_646, 9_555_429, 14_610_442, 16_893_420)),
    # --- 期末现金对账表(附注) ---
    ("对账:现金及现金等价物 Recon: Cash and cash equivalents",
     R(548_945, 1_061_850, 7_123_478, 4_425_021, 5_139_351, 8_543_903, 11_285_452)),
    ("对账:受限现金 Recon: Restricted cash",
     R(34_122, 30_787, 30_951, 25_873, 22_992, 38_519, 334_318)),
    ("对账:客户托管现金 Recon: Customer custodial cash",
     R(1_201_350, 3_763_392, 10_526_233, 4_978_752, 4_393_086, 6_028_020, 5_273_650)),
    # --- 补充披露 ---
    ("补充:已付利息 Cash paid for interest",
     R(0, 0, 3_793, 82_399, 76_142, None, None)),
    ("补充:已付所得税 Cash paid for income taxes",
     R(2_165, 62_060, 68_614, 35_888, 39_122, None, None)),
]

# ============================================================
# ④ 分部/收入拆分(千美元)——Coinbase 单一经营分部(CODM 按合并口径),
#    故「分部」= **按收入类型 + 按地区** 两套拆分(年报 REVENUE 附注)
# ============================================================
SEG_TYPE_ROWS = [
    ("交易收入-消费者(2019-2022 称 Retail) Consumer/Retail, net",
     R(432_919, 1_040_246, 6_490_992, 2_236_900, 1_429_490, 3_430_322, 3_322_835)),
    ("交易收入-机构 Institutional, net",
     R(30_086, 55_928, 346_274, 119_344, 90_164, 345_598, 479_667)),
    ("交易收入-其他 Other transaction revenue, net",
     R(None, None, None, None, None, 210_193, 252_888)),
    ("交易收入合计 Total transaction revenue",
     R(463_005, 1_096_174, 6_837_266, 2_356_244, 1_519_654, 3_986_113, 4_055_390)),
    # ⚠️ 2021 as-reported(FY2021 10-K)无「稳定币」行,利息 25,835 / 其他 69,179;
    #    FY2023 10-K 追溯把 2021 拆成 稳定币 9,882 / 利息 15,953 / 其他 132,304(合计不变)。
    ("订阅与服务-稳定币 Stablecoin revenue",
     R(None, None, None, 245_710, 694_247, 910_464, 1_348_821)),
    ("订阅与服务-区块链奖励 Blockchain rewards",
     R(188, 10_413, 223_055, 275_507, 330_885, 705_757, 677_405)),
    ("订阅与服务-利息(及融资费)收入 Interest (and finance fee) income",
     R(14_414, 5_535, 25_835, 81_246, 173_914, 265_799, 247_047)),
    ("订阅与服务-托管费 Custodial fee revenue",
     R(3_009, 18_561, 136_293, 79_847, 69_501, None, None)),
    ("订阅与服务-Earn 活动 Earn campaign revenue",
     R(117, 7_720, 63_125, None, None, None, None)),
    ("订阅与服务-其他 Other subscription and services revenue",
     R(2_216, 2_764, 69_179, 110_261, 138_339, 425_113, 554_775)),
    ("订阅与服务合计 Total subscription and services revenue",
     R(19_944, 44_993, 517_487, 792_571, 1_406_886, 2_307_133, 2_828_048)),
    ("净收入合计 Total net revenue",
     R(482_949, 1_141_167, 7_354_753, 3_148_815, 2_926_540, 6_293_246, 6_883_438)),
    ("其他收入-加密资产销售 Crypto asset sales revenue",
     R(39_863, 133_688, 482_550, 625, 16, None, None)),
    ("其他收入-公司利息及其他 Corporate interest and other income",
     R(10_923, 2_626, 2_141, 44_768, 181_827, 270_782, 297_887)),
    ("其他收入合计 Total other revenue",
     R(50_786, 136_314, 484_691, 45_393, 181_843, 270_782, 297_887)),
    ("总收入 Total revenue",
     R(533_735, 1_277_481, 7_839_444, 3_194_208, 3_108_383, 6_564_028, 7_181_325)),
]

SEG_GEO_ROWS = [
    ("美国 U.S.",
     R(None, None, 6_339_270, 2_684_425, 2_725_620, 5_460_820, 6_010_607)),
    ("美国以外 International / Rest of the World",
     R(None, None, 1_500_174, 509_783, 382_763, 1_103_208, 1_170_718)),
    ("总收入 Total revenue",
     R(None, None, 7_839_444, 3_194_208, 3_108_383, 6_564_028, 7_181_325)),
]

# ============================================================
# ⑤ XBRL 独立核对表:(tag, 转录行名, 符号flip, 取哪个 fy 的申报值)
#    fy=None 表示「取该年自身年报(as-reported)」= min(fy) 中等于当年+1 的那份
# ============================================================
XBRL_CHECKS = [
    ("Revenues", "总收入 Total revenue", 1),
    ("OperatingExpenses", "总经营费用 Total operating expenses", -1),
    ("OperatingIncomeLoss", "经营利润 Operating income (loss)", 1),
    ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
     "税前利润 Income (loss) before income taxes", 1),
    ("IncomeTaxExpenseBenefit", "所得税(费用)收益 (Provision for) benefit from income taxes", -1),
    ("NetIncomeLoss", "净利润 Net income (loss)", 1),
    ("EarningsPerShareBasic", "每股收益-基本(美元) EPS Basic", 1),
    ("EarningsPerShareDiluted", "每股收益-稀释(美元) EPS Diluted", 1),
]
XBRL_CHECKS_BS = [
    ("Assets", "总资产 Total assets", 1),
    ("Liabilities", "总负债 Total liabilities", 1),
    ("StockholdersEquity", "股东权益合计 Total stockholders' / shareholders' equity", 1),
    ("CashAndCashEquivalentsAtCarryingValue", "【资产】现金及现金等价物 Cash and cash equivalents", 1),
    ("RetainedEarningsAccumulatedDeficit", "留存收益 Retained earnings", 1),
    ("Goodwill", "商誉 Goodwill", 1),
    ("LongTermDebtNoncurrent", "长期债务 Long-term debt", 1),
]
XBRL_CHECKS_CF = [
    ("NetCashProvidedByUsedInOperatingActivities",
     "经营活动现金流净额(当年原披露) Net cash provided by (used in) operating activities", 1),
    ("NetCashProvidedByUsedInInvestingActivities",
     "投资活动现金流净额(当年原披露) Net cash provided by (used in) investing activities", 1),
    ("NetCashProvidedByUsedInFinancingActivities",
     "融资活动现金流净额(当年原披露) Net cash provided by (used in) financing activities", 1),
    ("CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
     "期末现金(含受限及客户托管现金) Cash, end of period", 1),
    ("ShareBasedCompensation", "股权薪酬费用 Stock-based compensation expense", 1),
    ("DepreciationDepletionAndAmortization", "折旧与摊销 Depreciation and amortization", 1),
]

ERRORS = []


def err(msg):
    ERRORS.append(msg)


def d(rows):
    return {name: vals for name, vals in rows}


# ============================================================
# 勾稽校验
# ============================================================
def close(a, b, tol=1):
    return abs(a - b) <= tol


def check_income():
    m = d(INCOME_ROWS)
    for y in YEARS:
        g = lambda k: m[k].get(y)
        # 总收入 = 净收入 + 其他收入
        if not close(g("净收入 Net revenue") + g("其他收入 Other revenue"),
                     g("总收入 Total revenue")):
            err(f"[利润表{y}] 净收入+其他收入 ≠ 总收入")
        # 经营费用分项和 = 总经营费用
        parts = ["交易费用 Transaction expense", "技术与开发 Technology and development",
                 "销售与营销 Sales and marketing", "一般及行政 General and administrative",
                 "加密资产减值净额 Crypto asset impairment, net(仅 FY2023 as-reported 单列)",
                 "经营性加密资产损益净额 (Losses) gains on crypto held for operations(ASU2023-08 后)",
                 "重组 Restructuring", "其他经营费用净额 Other operating expense, net"]
        s = sum(m[p].get(y, 0) for p in parts)
        if not close(s, g("总经营费用 Total operating expenses")):
            err(f"[利润表{y}] 经营费用分项和 {s:,} ≠ 总经营费用 {g('总经营费用 Total operating expenses'):,}")
        # 总收入 + 总经营费用 = 经营利润
        if not close(g("总收入 Total revenue") + g("总经营费用 Total operating expenses"),
                     g("经营利润 Operating income (loss)")):
            err(f"[利润表{y}] 总收入+总经营费用 ≠ 经营利润")
        # 经营利润 + 线下 = 税前
        below = ["利息费用 Interest expense",
                 "投资性加密资产损益净额 (Losses) gains on crypto held for investment(ASU2023-08 后)",
                 "其他收入(费用)净额 Other income (expense), net"]
        s2 = g("经营利润 Operating income (loss)") + sum(m[b].get(y, 0) for b in below)
        if not close(s2, g("税前利润 Income (loss) before income taxes")):
            err(f"[利润表{y}] 经营利润+线下 {s2:,} ≠ 税前 {g('税前利润 Income (loss) before income taxes'):,}")
        # 税前 + 所得税 = 净利
        if not close(g("税前利润 Income (loss) before income taxes")
                     + g("所得税(费用)收益 (Provision for) benefit from income taxes"),
                     g("净利润 Net income (loss)")):
            err(f"[利润表{y}] 税前+所得税 ≠ 净利")
        # 综合收益 = 净利 + 折算调整
        if not close(g("净利润 Net income (loss)") + g("外币折算调整(税后) Translation adjustment, net of tax"),
                     g("综合收益 Comprehensive income (loss)")):
            err(f"[利润表{y}] 净利+折算调整 ≠ 综合收益")


def check_bs():
    m = d(BS_ROWS)
    CUR = ["【资产】现金及现金等价物 Cash and cash equivalents",
           "受限现金(及等价物) Restricted cash (and cash equivalents)",
           "USDC(2019-2024 单列·FY2025 起并入现金等价物)",
           "客户托管资金 Customer custodial funds",
           "保管客户加密资产 Safeguarding customer crypto assets(SAB121·仅2022-2023)",
           "经营用加密资产 Crypto assets held for operations",
           "贷款应收 Loan receivables",
           "作为抵押品的加密资产 Crypto assets held as collateral",
           "借入的加密资产 Crypto assets borrowed",
           "应收账款净额 Accounts receivable, net",
           "应收账款及贷款净额 Accounts and loans receivable, net(合并列示年份)",
           "可交易投资 Marketable investments",
           "应收所得税 Income tax receivable",
           "预付费用及其他流动资产 Prepaid expenses and other current assets"]
    NONCUR = ["持有的加密资产 Crypto assets held(ASU2023-08 前合并列示)",
              "投资用加密资产 Crypto assets held for investment(ASU2023-08 后·公允价值)",
              "战略投资 Strategic investments",
              "递延所得税资产 Deferred tax assets",
              "租赁使用权资产 Lease right-of-use assets",
              "固定资产净额 Property and equipment, net / Software and equipment, net",
              "商誉 Goodwill", "无形资产净额 Intangible assets, net",
              "其他非流动资产 Other non-current assets"]
    CURL = ["【负债】应付客户托管资金 Custodial funds due to customers / Customer custodial fund liabilities",
            "保管客户加密负债 Safeguarding customer crypto liabilities(SAB121·仅2022-2023)",
            "应付账款 Accounts payable",
            "应付账款及应计费用 Accounts payable and accrued expenses(2019 合并列示)",
            "应计费用及其他流动负债 Accrued expenses and other current liabilities",
            "其他流动负债 Other current liabilities(2019 单列)",
            "加密资产借款 Crypto asset borrowings",
            "短期借款 Short-term borrowings",
            "长期债务-一年内到期 Current portion of long-term debt",
            "应返还抵押品义务 Obligation to return collateral",
            "租赁负债-流动 Lease liabilities, current"]
    NONCURL = ["租赁负债-非流动 Lease liabilities, non-current",
               "长期债务 Long-term debt",
               "其他非流动负债 Other non-current liabilities"]
    EQ = ["普通股面值 Common stock (Class A+B, par)", "资本公积 Additional paid-in capital",
          "累计其他综合收益(损失) AOCI", "留存收益 Retained earnings"]
    for y in YEARS:
        s = sum(m[k].get(y, 0) for k in CUR)
        if not close(s, m["流动资产合计 Total current assets"][y]):
            err(f"[资产负债表{y}] 流动资产分项和 {s:,} ≠ 合计 {m['流动资产合计 Total current assets'][y]:,}")
        tot = m["流动资产合计 Total current assets"][y] + sum(m[k].get(y, 0) for k in NONCUR)
        if not close(tot, m["总资产 Total assets"][y]):
            err(f"[资产负债表{y}] 流动+非流动 {tot:,} ≠ 总资产 {m['总资产 Total assets'][y]:,}")
        sl = sum(m[k].get(y, 0) for k in CURL)
        if not close(sl, m["流动负债合计 Total current liabilities"][y]):
            err(f"[资产负债表{y}] 流动负债分项和 {sl:,} ≠ 合计 {m['流动负债合计 Total current liabilities'][y]:,}")
        totl = m["流动负债合计 Total current liabilities"][y] + sum(m[k].get(y, 0) for k in NONCURL)
        if not close(totl, m["总负债 Total liabilities"][y]):
            err(f"[资产负债表{y}] 流动+非流动负债 {totl:,} ≠ 总负债 {m['总负债 Total liabilities'][y]:,}")
        se = sum(m[k].get(y, 0) for k in EQ)
        eqtot = m["股东权益合计 Total stockholders' / shareholders' equity"][y]
        if not close(se, eqtot):
            err(f"[资产负债表{y}] 权益分项和 {se:,} ≠ 权益合计 {eqtot:,}")
        lhs = (m["总负债 Total liabilities"][y]
               + m["可转换优先股(夹层) Convertible preferred stock"].get(y, 0)
               + m["股东权益合计 Total stockholders' / shareholders' equity"][y])
        if not close(lhs, m["总资产 Total assets"][y]):
            err(f"[资产负债表{y}] 总负债+夹层+权益 {lhs:,} ≠ 总资产 {m['总资产 Total assets'][y]:,}")
        if not close(m["负债+夹层+权益合计 Total L + mezzanine + E"][y], m["总资产 Total assets"][y]):
            err(f"[资产负债表{y}] 印刷「负债+夹层+权益合计」≠ 总资产")


def check_cf():
    m = d(CF_ROWS)
    for y in YEARS:
        o = m["经营活动现金流净额(当年原披露) Net cash provided by (used in) operating activities"][y]
        i = m["投资活动现金流净额(当年原披露) Net cash provided by (used in) investing activities"][y]
        f = m["融资活动现金流净额(当年原披露) Net cash provided by (used in) financing activities"][y]
        net = m["现金净增(减) Net increase (decrease) in cash"][y]
        fx = m["汇率影响 Effect of exchange rates on cash"][y]
        beg = m["期初现金(含受限及客户托管现金) Cash, beginning of period"][y]
        end = m["期末现金(含受限及客户托管现金) Cash, end of period"][y]
        if not close(o + i + f, net):
            err(f"[现金流{y}] 经营+投资+融资 {o+i+f:,} ≠ 现金净增 {net:,}")
        if not close(beg + net + fx, end):
            err(f"[现金流{y}] 期初+净增+汇率 {beg+net+fx:,} ≠ 期末 {end:,}")
        rec = (m["对账:现金及现金等价物 Recon: Cash and cash equivalents"][y]
               + m["对账:受限现金 Recon: Restricted cash"][y]
               + m["对账:客户托管现金 Recon: Customer custodial cash"][y])
        if not close(rec, end):
            err(f"[现金流{y}] 期末现金对账表 {rec:,} ≠ 期末现金 {end:,}")
    # 经营活动:净利+调整项+营运资本变动 = 经营现金流净额
    mi = d(INCOME_ROWS)
    ADJ = [k for k, _ in CF_ROWS]
    for y in YEARS:
        idx0 = ADJ.index("【经营】净利润 Net income (loss)")
        idx1 = ADJ.index("经营活动现金流净额(当年原披露) Net cash provided by (used in) operating activities")
        s = sum(m[k].get(y, 0) for k in ADJ[idx0:idx1])
        if not close(s, m["经营活动现金流净额(当年原披露) Net cash provided by (used in) operating activities"][y]):
            err(f"[现金流{y}] 经营段分项和 {s:,} ≠ 经营净额 "
                f"{m['经营活动现金流净额(当年原披露) Net cash provided by (used in) operating activities'][y]:,}")
        # 净利须与利润表一致
        if not close(m["【经营】净利润 Net income (loss)"][y], mi["净利润 Net income (loss)"][y]):
            err(f"[现金流{y}] 现金流净利 ≠ 利润表净利")
    # 投资/融资分项和
    for seg, start, endk in [("投资", "【投资】购建固定资产 Purchase of property and equipment",
                              "投资活动现金流净额(当年原披露) Net cash provided by (used in) investing activities"),
                             ("融资", "【融资】期权行权发行普通股净额 Issuance of common stock upon exercise of stock options, net",
                              "融资活动现金流净额(当年原披露) Net cash provided by (used in) financing activities")]:
        i0, i1 = ADJ.index(start), ADJ.index(endk)
        for y in YEARS:
            s = sum(m[k].get(y, 0) for k in ADJ[i0:i1])
            if not close(s, m[endk][y]):
                err(f"[现金流{y}] {seg}段分项和 {s:,} ≠ {seg}净额 {m[endk][y]:,}")


def check_seg():
    mi = d(INCOME_ROWS)
    mt = d(SEG_TYPE_ROWS)
    for y in YEARS:
        tr = sum(mt[k].get(y, 0) for k in
                 ["交易收入-消费者(2019-2022 称 Retail) Consumer/Retail, net",
                  "交易收入-机构 Institutional, net", "交易收入-其他 Other transaction revenue, net"])
        if not close(tr, mt["交易收入合计 Total transaction revenue"][y]):
            err(f"[分部-类型{y}] 交易收入分项和 {tr:,} ≠ 合计 {mt['交易收入合计 Total transaction revenue'][y]:,}")
        ss = sum(mt[k].get(y, 0) for k in
                 ["订阅与服务-稳定币 Stablecoin revenue", "订阅与服务-区块链奖励 Blockchain rewards",
                  "订阅与服务-利息(及融资费)收入 Interest (and finance fee) income",
                  "订阅与服务-托管费 Custodial fee revenue", "订阅与服务-Earn 活动 Earn campaign revenue",
                  "订阅与服务-其他 Other subscription and services revenue"])
        if not close(ss, mt["订阅与服务合计 Total subscription and services revenue"][y]):
            err(f"[分部-类型{y}] 订阅服务分项和 {ss:,} ≠ 合计 {mt['订阅与服务合计 Total subscription and services revenue'][y]:,}")
        if not close(mt["交易收入合计 Total transaction revenue"][y]
                     + mt["订阅与服务合计 Total subscription and services revenue"][y],
                     mt["净收入合计 Total net revenue"][y]):
            err(f"[分部-类型{y}] 交易+订阅 ≠ 净收入合计")
        orv = sum(mt[k].get(y, 0) for k in
                  ["其他收入-加密资产销售 Crypto asset sales revenue",
                   "其他收入-公司利息及其他 Corporate interest and other income"])
        if not close(orv, mt["其他收入合计 Total other revenue"][y]):
            err(f"[分部-类型{y}] 其他收入分项和 {orv:,} ≠ 合计 {mt['其他收入合计 Total other revenue'][y]:,}")
        if not close(mt["净收入合计 Total net revenue"][y] + mt["其他收入合计 Total other revenue"][y],
                     mt["总收入 Total revenue"][y]):
            err(f"[分部-类型{y}] 净收入+其他 ≠ 总收入")
        if not close(mt["总收入 Total revenue"][y], mi["总收入 Total revenue"][y]):
            err(f"[分部-类型{y}] 分部总收入 ≠ 利润表总收入")
    mg = d(SEG_GEO_ROWS)
    for y in YEARS:
        if y not in mg["总收入 Total revenue"]:
            continue
        s = mg["美国 U.S."][y] + mg["美国以外 International / Rest of the World"][y]
        if not close(s, mg["总收入 Total revenue"][y]):
            err(f"[分部-地区{y}] 美国+海外 {s:,} ≠ 总收入 {mg['总收入 Total revenue'][y]:,}")
        if not close(mg["总收入 Total revenue"][y], mi["总收入 Total revenue"][y]):
            err(f"[分部-地区{y}] 分部总收入 ≠ 利润表总收入")


def check_xbrl():
    """XBRL 独立核:取「当年自身年报」(fy = 该年,因 10-K 的 fy 等于报告年)的值。"""
    p = os.path.join(DIR, "_xbrl", "companyfacts-CIK0001679788.json")
    if not os.path.exists(p):
        err("[XBRL] companyfacts 快照缺失,无法独立核")
        return
    gaap = json.load(open(p))["facts"]["us-gaap"]
    from datetime import date

    def asrep(tag, yr):
        """返回该年「自身年报」披露值(fy == yr 的 10-K)。"""
        if tag not in gaap:
            return None
        for unit, items in gaap[tag]["units"].items():
            for it in items:
                if it.get("form") != "10-K" or it.get("fp") != "FY" or it.get("fy") != yr:
                    continue
                if not it.get("end", "").startswith(str(yr)):
                    continue
                if it.get("start"):
                    y0 = date(*map(int, it["start"].split("-")))
                    y1 = date(*map(int, it["end"].split("-")))
                    if not (350 <= (y1 - y0).days <= 380):
                        continue
                return it["val"]
        return None

    checked = 0
    for rows, checks in [(INCOME_ROWS, XBRL_CHECKS), (BS_ROWS, XBRL_CHECKS_BS),
                         (CF_ROWS, XBRL_CHECKS_CF)]:
        m = d(rows)
        for tag, rowname, flip in checks:
            for y in YEARS:
                v = asrep(tag, y)
                if v is None:
                    continue          # 该年无自身 10-K(2019/2020)或该 tag 未标
                mine = m[rowname].get(y)
                if mine is None:
                    continue
                # EPS 类单位是 USD/share,不乘 1000
                scale = 1 if "EPS" in rowname or "每股收益" in rowname else 1000
                exp = mine * flip * scale
                if abs(exp - v) > (0.005 if scale == 1 else 1):
                    err(f"[XBRL核] {tag}@{y}: 转录 {mine:,} (×{flip}) → {exp:,.0f} ≠ XBRL {v:,}")
                checked += 1
    print(f"    XBRL 独立核对格数: {checked}")


# ============================================================
# 写出
# ============================================================
def write_csv(path, header_note, rows, extra_head=None):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([header_note])
        if extra_head:
            for h in extra_head:
                w.writerow([h])
        w.writerow(["科目"] + [str(y) for y in YEARS])
        for name, vals in rows:
            w.writerow([name] + [("" if y not in vals else vals[y]) for y in YEARS])
    print(f"    → {os.path.relpath(path, REPO)}")


def build_ratios():
    """派生比率 + 可比口径行(用于跨年比较,绕开三大口径断点)。"""
    mi, mb, mc = d(INCOME_ROWS), d(BS_ROWS), d(CF_ROWS)
    seg = d(SEG_TYPE_ROWS)

    def g(m, k, y):
        return m[k].get(y)

    rows = []

    def add(name, fn, pct=False, nd=1):
        vals = {}
        for y in YEARS:
            try:
                v = fn(y)
            except (TypeError, ZeroDivisionError, KeyError):
                v = None          # 该年缺输入项 → 留空,不编造
            if v is not None:
                vals[y] = round(v * (100 if pct else 1), nd)
        rows.append((name, vals))

    rev = lambda y: g(mi, "总收入 Total revenue", y)
    ni = lambda y: g(mi, "净利润 Net income (loss)", y)
    oi = lambda y: g(mi, "经营利润 Operating income (loss)", y)
    eq = lambda y: g(mb, "股东权益合计 Total stockholders' / shareholders' equity", y)

    # --- 可比口径:剔除 SAB121 保管客户加密资产 ---
    def comp_assets(y):
        a = g(mb, "总资产 Total assets", y)
        s = mb["保管客户加密资产 Safeguarding customer crypto assets(SAB121·仅2022-2023)"].get(y, 0)
        return a - s
    rows.append(("【可比】总资产(剔除SAB121保管客户加密资产)",
                 {y: comp_assets(y) for y in YEARS}))

    def comp_liab(y):
        l = g(mb, "总负债 Total liabilities", y)
        s = mb["保管客户加密负债 Safeguarding customer crypto liabilities(SAB121·仅2022-2023)"].get(y, 0)
        return l - s
    rows.append(("【可比】总负债(剔除SAB121保管客户加密负债)",
                 {y: comp_liab(y) for y in YEARS}))

    # --- 可比口径:经营现金流 = 各年**最新重述基准**(同时消解断点 B 与 C) ---
    #   2019:无任何申报按新基准重述过 → 本库自算(as-reported 80,594 亏 − 经营内
    #        客户托管资金流 -130,122 = +49,528);标「自算」不冒充申报值。
    #   2020/2021:FY2022 10-K 重述值(客户托管资金移出经营)。
    #   2022  :从未被重述,as-reported 即最新。
    #   2023/2024:FY2025 10-K 重述值(再叠加稳定币改现金等价物)。
    #   2025  :as-reported。
    COMP_OCF = {2019: 49_528,        # 自算
                2020: 293_548,       # FY2022 重述
                2021: 4_038_172,     # FY2022 重述
                2022: -1_585_419,    # 未被重述
                2023: 673_376,       # FY2025 重述
                2024: 3_103_935,     # FY2025 重述
                2025: 2_426_383}     # as-reported

    def comp_ocf(y):
        return COMP_OCF[y]
    rows.append(("【可比】经营现金流净额(各年最新重述基准·2019 为本库自算)", dict(COMP_OCF)))

    add("营业利润率 Operating margin %", lambda y: oi(y) / rev(y), pct=True)
    add("净利率 Net margin %", lambda y: ni(y) / rev(y), pct=True)
    add("ROE %(净利/期末权益)", lambda y: ni(y) / eq(y), pct=True)
    add("ROE %(净利/期初期末平均权益)",
        lambda y: None if y == YEARS[0] else ni(y) / ((eq(y) + eq(y - 1)) / 2), pct=True)
    add("现金含量(可比经营现金流/净利)",
        lambda y: None if ni(y) <= 0 else comp_ocf(y) / ni(y), nd=2)
    add("现金含量(原披露经营现金流/净利)",
        lambda y: None if ni(y) <= 0 else
        g(mc, "经营活动现金流净额(当年原披露) Net cash provided by (used in) operating activities", y) / ni(y), nd=2)
    add("股权薪酬/总收入 SBC/Revenue %",
        lambda y: g(mc, "股权薪酬费用 Stock-based compensation expense", y) / rev(y), pct=True)
    add("股权薪酬/经营现金流(可比) SBC/OCF %",
        lambda y: None if comp_ocf(y) <= 0 else g(mc, "股权薪酬费用 Stock-based compensation expense", y) / comp_ocf(y), pct=True)
    # 现金资本开支:2019-2023 现金流量表单列;2024/2025 已并入「其他投资活动净额」不再单列
    K_PPE = "【投资】购建固定资产 Purchase of property and equipment"
    K_SW = "资本化内部开发软件(现金) Capitalized internal-use software development costs"

    def cash_capex(y):
        a, b = mc[K_PPE].get(y), mc[K_SW].get(y)
        if a is None and b is None:
            return None            # 2024/2025:现金流量表不再单列 → 不可得,不编造
        return -((a or 0) + (b or 0))
    add("现金资本开支(购建固定资产+资本化软件·现金流量表单列年份)", cash_capex, nd=0)
    add("现金资本开支/净利 %",
        lambda y: None if (cash_capex(y) is None or ni(y) <= 0) else cash_capex(y) / ni(y), pct=True)
    # 附注口径(含资本化股权薪酬)——2023-2025 附注「资本化内部开发软件新增额」
    NOTE_SW_ADD = {2023: 112_000, 2024: 110_500, 2025: 138_300}
    rows.append(("资本化内部开发软件新增额(附注·含资本化SBC·2023-2025)", dict(NOTE_SW_ADD)))
    rows.append(("附注软件新增额/净利 %(2023-2025)",
                 {y: round(NOTE_SW_ADD[y] / ni(y) * 100, 1) for y in NOTE_SW_ADD if ni(y) > 0}))
    add("交易收入占净收入 % Transaction rev / Net rev",
        lambda y: seg["交易收入合计 Total transaction revenue"][y] / seg["净收入合计 Total net revenue"][y], pct=True)
    add("订阅与服务收入占净收入 % Subscription&services / Net rev",
        lambda y: seg["订阅与服务合计 Total subscription and services revenue"][y]
        / seg["净收入合计 Total net revenue"][y], pct=True)
    add("稳定币收入占净收入 % Stablecoin / Net rev",
        lambda y: seg["订阅与服务-稳定币 Stablecoin revenue"][y] / seg["净收入合计 Total net revenue"][y], pct=True)
    add("美国收入占比 % U.S. revenue share",
        lambda y: d(SEG_GEO_ROWS)["美国 U.S."][y] / d(SEG_GEO_ROWS)["总收入 Total revenue"][y], pct=True)
    # 债务与流动性
    add("长期债务(含一年内到期)",
        lambda y: (g(mb, "长期债务 Long-term debt", y) or 0)
        + (g(mb, "长期债务-一年内到期 Current portion of long-term debt", y) or 0), nd=0)
    add("公司自有现金(现金+受限+USDC,不含客户托管)",
        lambda y: (g(mb, "【资产】现金及现金等价物 Cash and cash equivalents", y)
                   + g(mb, "受限现金(及等价物) Restricted cash (and cash equivalents)", y)
                   + (mb["USDC(2019-2024 单列·FY2025 起并入现金等价物)"].get(y, 0))), nd=0)
    add("自有现金/长期债务 倍数",
        lambda y: None if ((g(mb, "长期债务 Long-term debt", y) or 0)
                           + (g(mb, "长期债务-一年内到期 Current portion of long-term debt", y) or 0)) == 0 else
        (g(mb, "【资产】现金及现金等价物 Cash and cash equivalents", y)
         + g(mb, "受限现金(及等价物) Restricted cash (and cash equivalents)", y)
         + (mb["USDC(2019-2024 单列·FY2025 起并入现金等价物)"].get(y, 0)))
        / ((g(mb, "长期债务 Long-term debt", y) or 0)
           + (g(mb, "长期债务-一年内到期 Current portion of long-term debt", y) or 0)), nd=2)
    add("资产负债率 %(可比口径)", lambda y: comp_liab(y) / comp_assets(y), pct=True)
    add("商誉/权益 % Goodwill / Equity", lambda y: g(mb, "商誉 Goodwill", y) / eq(y), pct=True)
    add("商誉+无形/权益 % (Goodwill+Intangibles) / Equity",
        lambda y: (g(mb, "商誉 Goodwill", y) + g(mb, "无形资产净额 Intangible assets, net", y)) / eq(y), pct=True)
    # 利润链纵深
    add("留存收益/权益 % Retained earnings / Equity",
        lambda y: g(mb, "留存收益 Retained earnings", y) / eq(y), pct=True)
    # 股东回报
    add("回购普通股(现金流出)",
        lambda y: -(g(mc, "回购普通股 Repurchase of common stock", y)) if
        mc["回购普通股 Repurchase of common stock"].get(y) is not None else None, nd=0)
    return rows


# ============================================================
# ⑥ 重述与口径变更登记册(每行 = 一处「同一年在不同申报里数不一样」或口径定义变更)
#    17 处报表重述由 XBRL companyfacts 跨 fy 比对**机器侦测**得出(见 _restate_detect)
# ============================================================
RESTATE_ROWS = [
    # 断点, 受影响年, 科目, 原披露(来源), 重述后(来源), 差额, 原因
    ("A SAB121→122", "2023", "总资产 Total assets",
     "206,982,953 (10-K FY2023)", "14,753,901 (10-K FY2024)", "-192,229,052",
     "SEC 2025-01-30 发 SAB 122 废止 SAB 121,追溯剔除表内「保管客户加密资产/负债」总额"),
    ("A SAB121→122", "2023", "总负债 Total liabilities",
     "200,701,304 (10-K FY2023)", "8,472,252 (10-K FY2024)", "-192,229,052", "同上"),
    ("A SAB121→122", "2022", "总资产/总负债(表内保管客户加密)",
     "89,724,873 / 84,270,316 含 75,413,188", "FY2024 起不再于表内列示", "-75,413,188",
     "SAB 121 仅 2022-2023 两年适用;2021 及以前未追溯纳入"),
    ("B 客户托管资金 经营→融资", "2020", "经营活动现金流净额",
     "3,004,070 (10-K FY2021)", "293,548 (10-K FY2022)", "-2,710,522",
     "客户托管资金负债变动由**经营**重分类至**融资**;现金含量口径反转"),
    ("B 客户托管资金 经营→融资", "2021", "经营活动现金流净额",
     "10,730,031 (10-K FY2021)", "4,038,172 (10-K FY2022)", "-6,691,859", "同上"),
    ("B 客户托管资金 经营→融资", "2020", "融资活动现金流净额",
     "18,801 (10-K FY2021)", "2,729,323 (10-K FY2022)", "+2,710,522", "同上(对侧)"),
    ("B 客户托管资金 经营→融资", "2021", "融资活动现金流净额",
     "3,284,225 (10-K FY2021)", "9,976,084 (10-K FY2022)", "+6,691,859", "同上(对侧)"),
    ("C 稳定币改记现金等价物", "2024", "现金及现金等价物",
     "8,543,903 (10-K FY2024)", "9,308,266 (10-K FY2025)", "+764,363",
     "FY2025 自愿变更会计政策:USDC/EURC/PYUSD 由 ASC 310 应收改列现金等价物,追溯适用"),
    ("C 稳定币改记现金等价物", "2023", "现金及现金等价物",
     "5,139,351 (10-K FY2023/FY2024)", "5,489,100 (10-K FY2025)", "+349,749", "同上"),
    ("C 稳定币改记现金等价物", "2024", "经营活动现金流净额",
     "2,556,844 (10-K FY2024)", "3,103,935 (10-K FY2025)", "+547,091",
     "稳定币借贷改按加密借贷政策 → 营运资本变动移入投资活动「发放贷款」"),
    ("C 稳定币改记现金等价物", "2023", "经营活动现金流净额",
     "922,951 (10-K FY2023/FY2024)", "673,376 (10-K FY2025)", "-249,575", "同上"),
    ("C 稳定币改记现金等价物", "2024", "投资活动现金流净额",
     "-282,385 (10-K FY2024)", "-201,003 (10-K FY2025)", "+81,382", "同上(对侧)"),
    ("C 稳定币改记现金等价物", "2023", "投资活动现金流净额",
     "5,392 (10-K FY2023/FY2024)", "-206,176 (10-K FY2025)", "-211,568", "同上(对侧)"),
    ("C 稳定币改记现金等价物", "2024", "融资活动现金流净额",
     "2,828,921 (10-K FY2024)", "2,903,078 (10-K FY2025)", "+74,157", "同上(对侧)"),
    ("C 稳定币改记现金等价物", "2023", "融资活动现金流净额",
     "-811,332 (10-K FY2023/FY2024)", "-838,205 (10-K FY2025)", "-26,873", "同上(对侧)"),
    ("C 稳定币改记现金等价物", "2024", "期末现金(含受限及客户托管)",
     "14,610,442 (10-K FY2024)", "15,683,455 (10-K FY2025)", "+1,073,013", "同上"),
    ("C 稳定币改记现金等价物", "2023", "期末现金(含受限及客户托管)",
     "9,555,429 (10-K FY2023/FY2024)", "9,925,812 (10-K FY2025)", "+370,383", "同上"),
    ("C 稳定币改记现金等价物", "2022", "期末现金(含受限及客户托管)",
     "9,429,646 (10-K FY2022/23/24)", "10,288,045 (10-K FY2025)", "+858,399", "同上"),
    # --- 非报表重述,但同样破坏跨年可比的口径/定义变更 ---
    ("D ASU 2023-08(2024-01-01 采用·累积影响法)", "2024 期初", "留存收益",
     "—", "+561,489 累积影响调整", "+561,489",
     "自持加密资产由「成本减减值」改按**公允价值**计量;**非追溯** → 2023 及以前"
     "的加密资产损益行与 2024 起不可比(投资用加密资产期初另 +717,373)"),
    ("E 关键指标定义变更", "2021/2023", "MTU 月度交易用户",
     "11.4M(2021·Q4 均值口径) / 7.0M(2023·Q4 均值)",
     "11.2M(2021·FY2022 修订) / 7.4M(2023·FY2024 改年度均值)", "—",
     "① 数值被静默下修(11.4→11.2);② 口径由「Q4 各月均值」改为「全年各季均值」;"
     "公司自陈「非重大的口径修订一般不回溯更新已披露指标」→ 跨年报直接相减会错"),
    ("E 关键指标定义变更", "2024", "Adjusted EBITDA(非GAAP)",
     "964M(10-K FY2023)", "978M(10-K FY2024·recast)", "+14M",
     "FY2024 Q1 修订 Adjusted EBITDA 定义并重述上年可比数"),
    ("E 关键指标定义变更", "2025", "Trading Volume 交易量",
     "1,162B(10-K FY2024·2024年)", "1,189B(10-K FY2025·2024年 recast)", "+27B",
     "2025Q4 重定义:加入「路由至平台外撮合」交易额的一半,上期重述"),
    ("E 关键指标定义变更", "2023", "Verified Users / Assets on Platform 停披露",
     "2022 年报仍披露(110M / 80B)", "2023Q1 起停披露 Verified Users;AOP 停后于 FY2024 恢复",
     "—", "公司主动删减关键指标口径(AOP 恢复时定义已改:剔除客户自持私钥资产)"),
    ("F 数据可得性边界", "2018", "三表全表",
     "—", "实证不可得", "—",
     "Coinbase 上市时为 EGC,424B4 招股书只列 FY2019/FY2020 两年经审计财务(非三年);"
     "FY2018 全库仅 3 个期初余额点:现金 1,987,139 / 权益 500,071 / 未确认税务利益 6,605"),
]

METRIC_ROWS = [
    ("MTU 月度交易用户(百万·各年报 as-reported·⚠️口径见重述表 E)",
     R(1.0, 2.8, 11.4, 8.3, 7.0, 8.4, 9.2)),
    ("MTU 月度交易用户(百万·全年各季均值口径·可比)",
     R(1.1, 1.9, 8.4, None, 7.4, 8.4, 9.2)),
    ("Assets on Platform 平台资产(十亿美元·年末)",
     R(17, 90, 278, 80, 191, 404, 376)),
    ("Trading Volume 交易量(十亿美元·⚠️2025Q4 重定义)",
     R(80, 193, 1_671, 830, 468, 1_162, 1_221)),
    ("Adjusted EBITDA(非GAAP·百万美元·⚠️2024 改定义)",
     R(24, 527, 4_090, -371, 964, 3_348, 2_808)),
    ("员工数(年末) Employees",
     R(None, 1_249, 3_730, 4_510, 3_416, 3_772, 4_951)),
    ("单一交易对手收入占比 %(最大客户·年报披露)",
     R(None, None, None, None, 22, 14, 19)),
    ("自持投资用加密资产(千美元·2024 起公允价值)",
     R(33_932, 316_094, 988_193, 424_393, 449_925, 1_552_995, 1_998_871)),
    ("比特币占交易量 % Bitcoin share of Trading Volume",
     R(None, None, None, None, None, 33, 29)),
    ("以太坊占交易量 % Ethereum share of Trading Volume",
     R(None, None, None, None, None, 13, 16)),
    # ⚠️ USDT 占比一年腰斩,与 2025-03「有意的定价调整·演进稳定币战略」同期
    #    (公司称该调整致稳定币交易对成交额减少 1,010 亿美元)。Coinbase 从 USDT 只收
    #    交易费、无储备分成(分成仅存于 Circle/USDC 共同创办型安排),故有动机导流至 USDC。
    ("USDT 占交易量 % USDT share of Trading Volume",
     R(None, None, None, None, None, 12, 6)),
    ("其他币种占交易量 % Other crypto assets share",
     R(None, None, None, None, None, 42, 49)),
]


def write_restate():
    p = os.path.join(DIR, "重述与口径变更.csv")
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Coinbase 重述与口径变更登记册 —— 单位千美元(除注明);"
                    "A/B/C 三处报表重述由 XBRL companyfacts 跨 fy 机器侦测(17 处)+ 印刷报表核对"])
        w.writerow(["⚠️ 本表存在的意义:三表 CSV 取「各年 as-reported」,跨年直接相减会踩这些断点"])
        w.writerow(["断点", "受影响年份", "科目/指标", "原披露值(来源)", "重述/变更后(来源)",
                    "差额", "原因"])
        for r in RESTATE_ROWS:
            w.writerow(list(r))
    print(f"    → {os.path.relpath(p, REPO)}")


def main():
    print("Coinbase 三表构建 —— 勾稽校验中…")
    check_income()
    check_bs()
    check_cf()
    check_seg()
    check_xbrl()

    if ERRORS:
        print(f"\n❌ 勾稽/核对失败 {len(ERRORS)} 项,**不写出 CSV**:")
        for e in ERRORS:
            print("   -", e)
        sys.exit(1)
    print("✅ 全部勾稽 + XBRL 独立核通过\n写出 CSV:")

    unit = "单位:千美元(USD thousands);费用/流出=负数;空=该年申报 presentation 无此科目"
    src = "各年 canonical 来源(as-reported):" + " | ".join(f"{y}={SOURCE[y]}" for y in YEARS)
    brk = ("⚠️ 三大口径断点见 重述与口径变更.csv:A=SAB121→122(2022-2023 表内保管客户加密资产)"
           " B=客户托管资金流经营↔融资重分类(2020/2021) C=支付稳定币改记现金等价物(2023/2024 追溯)")

    write_csv(os.path.join(DIR, "利润表.csv"), unit, INCOME_ROWS,
              [src, "注:收入/总费用/经营利润/净利 七年从未被重述(XBRL 已证),跨年可比;"
                    "经营费用与线下明细的拆分粒度逐年变化(as-reported)"])
    write_csv(os.path.join(DIR, "资产负债表.csv"), unit, BS_ROWS, [src, brk])
    write_csv(os.path.join(DIR, "现金流量表.csv"), unit, CF_ROWS, [src, brk])
    write_csv(os.path.join(DIR, "分部营收.csv"),
              "单位:千美元;Coinbase 为单一经营分部(CODM 按合并口径),故「分部」=按收入类型 + 按地区两套拆分",
              SEG_TYPE_ROWS + [("—— 按地区 ——", {})] + SEG_GEO_ROWS, [src])
    write_csv(os.path.join(DIR, "财务比率.csv"),
              "派生指标(从三表算·年报不直接给);比率单位 %,倍数无单位,金额千美元",
              build_ratios(),
              ["【可比】开头的行 = 绕开三大口径断点后的可比序列,跨年比较请用这些行",
               "现金含量(可比)= 各年最新重述基准的经营现金流 ÷ 净利(净利为负的年份留空)"])
    write_restate()
    write_csv(os.path.join(DIR, "经营指标.csv"),
              "公司关键业务指标(年报 MD&A「Key Business Metrics」+ Item 1);单位见行名",
              METRIC_ROWS,
              [src, "⚠️ MTU / Adjusted EBITDA / Trading Volume 三项定义均被改过,"
                    "跨年报直接相减会错 —— 详见 重述与口径变更.csv 断点 E"])
    print("\n完成。")


if __name__ == "__main__":
    main()
