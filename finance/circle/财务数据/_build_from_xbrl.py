#!/usr/bin/env python3
"""circle (Circle Internet Group, CRCL) 财务数据构建器 —— 双轨:
①转录轨(canonical): 一手 SEC 申报印刷报表逐行转录(report/circle/)
   - FY2020-2021: S-4/A 2022-11-14 (SPAC 注册·后撤回·Circle Internet Financial Limited 主体)
   - FY2022:      S-1/424B4 2025-06-05 (IPO 招股书)
   - FY2023-2025: 10-K FY2025 (2026-03-09; 2023 BS 取自 424B4)
②XBRL 轨(独立核): _xbrl/companyfacts-CIK0001876042.json (仅覆盖 FY2023-2025 年度)
   → FY2020-2022 为转录单轨(S-1/S-4 无 XBRL), 复核靠勾稽 + 跨源衔接(2021末现金=2022初现金)。

单位: 千美元 (USD thousands·与申报印刷一致); 费用/流出 = 负数; EPS = 美元/股。
勾稽校验不过 → 不写出 CSV。改数/补年份 → 改本脚本重跑。
"""
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import derived  # noqa: E402  通用比率底

YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
N = len(YEARS)
_ = None  # 该期无此科目/未披露

# ============================================================
# 利润表 (signed: 收入+、成本费用−、收益+、损失−、税负−)
# ============================================================
IS_ROWS = [
    ("储备收入 Reserve income (2020-21列名为 Reserve interest income)", [4435, 28464, 735885, 1430606, 1661084, 2636822]),
    ("交易与财资服务收入 Transaction and Treasury services (2020-21旧口径)", [2589, 47547, _, _, _, _]),
    ("其他收入 Other revenue", [8417, 8866, 36167, 19860, 15169, 109820]),
    ("营业总收入 Total revenue and reserve income", [15441, 84877, 772052, 1450466, 1676253, 2746642]),
    ("分销与交易成本 Distribution and transaction costs (2020-21为 Reserve income sharing and transaction costs)", [-2826, -11890, -286953, -719806, -1010811, -1661549]),
    ("交易与财资服务成本 Transaction and Treasury services costs (2020-21旧口径)", [-785, -30731, _, _, _, _]),
    ("其他成本 Other costs", [_, _, -22401, -7918, -6553, -2102]),
    ("分销交易及其他成本合计 Total distribution, transaction and other costs", [-3611, -42621, -309354, -727724, -1017364, -1663651]),
    ("薪酬费用 Compensation expenses", [-18932, -68170, -212961, -296055, -263410, -844878]),
    ("一般及行政费用 General and administrative expenses", [-13916, -31125, -82272, -100128, -137283, -190272]),
    ("折旧摊销费用 Depreciation and amortization expenses", [-4500, -3945, -13277, -34887, -50854, -76627]),
    ("IT基础设施成本 IT infrastructure costs", [-3716, -5379, -11835, -20722, -27109, -36638]),
    ("营销费用 Marketing expenses", [-400, -13697, -78839, -36544, -17326, -25718]),
    ("无形资产出售收益 Gain on sale of intangible assets", [_, _, _, 21634, _, _]),
    ("SPAC合并终止费用 Merger termination expenses (Concord)", [_, _, -44194, _, _, _]),
    ("数字资产损益及减值 Digital assets (losses)/gains and impairment", [-1256, -6038, -57436, 13488, 4251, -5293]),
    ("营业费用合计 Total operating expenses", [-42720, -128354, -500814, -453214, -491731, -1179426]),
    ("持续经营营业利润 Operating income (loss) from continuing operations", [-30890, -86098, -38116, 269528, 167158, -96435]),
    ("其他收益(费用)净额 Other income (expense), net", [13692, -417761, -720393, 49421, 54416, -6458]),
    ("除税前利润 Net income (loss) from continuing operations before income taxes", [-17198, -503859, -758509, 318949, 221574, -102893]),
    ("所得税(费用)收益 Income tax (expense) benefit", [-115, -4854, -3263, -47400, -64583, 33375]),
    ("持续经营净利润 Net income (loss) from continuing operations", [-17313, -508713, -761772, 271549, 156991, -69518]),
    ("终止经营净损益 Income (loss) from discontinued operations", [21103, 507, -7075, -3987, -1324, 0]),
    ("——其中 Circle Trade (终止经营)", [-58, 1650, _, _, _, _]),
    ("——其中 Circle Invest (终止经营·2020含处置收益0.6M)", [730, 28, _, _, _, _]),
    ("——其中 Poloniex (终止经营)", [20431, -1171, _, _, _, _]),
    ("净利润 Net income (loss)", [3790, -508206, -768847, 267562, 155667, -69518]),
    ("少数股东损益 Net loss attributable to noncontrolling interests", [_, _, _, _, _, -10]),
    ("归母净利润 Net income (loss) attributable to common stockholders", [3790, -508206, -768847, 267562, 155667, -69508]),
    ("——外币折算差异(OCI) FX translation adjustment, net of tax", [165, 137, 625, 1460, -1899, 10904]),
    ("——AFS债券未实现损益(OCI) Unrealized g/(l) on AFS debt securities, net of tax", [0, 120, 1175, -1069, -226, 0]),
    ("——可转债信用风险未实现损益(OCI) Unrealized g/(l) on convertible notes – credit risk, net of tax", [0, 4972, -3155, 1182, 840, -49]),
    ("OCI合计 Total other comprehensive income (loss), net of tax", [165, 5229, -1355, 1573, -1285, 10855]),
    ("OCI归少数股东 OCI attributable to NCI", [_, _, _, _, _, -16]),
    ("OCI归母 OCI attributable to common stockholders", [165, 5229, -1355, 1573, -1285, 10871]),
    ("全面收益(归母) Comprehensive income (loss) attributable to common stockholders", [3955, -502977, -770202, 269135, 154382, -58637]),
    ("基本每股收益(美元) Basic EPS", [0.00, -11.46, -16.48, 0.95, 0.33, -0.44]),
    ("稀释每股收益(美元) Diluted EPS", [0.00, -11.46, -16.48, 0.78, 0.30, -0.44]),
    ("基本每股收益-持续经营(美元) Basic EPS - continuing ops", [0.00, -11.47, -16.33, 0.95, 0.33, -0.44]),
    ("加权平均股数-基本(千股) Weighted-avg shares basic", [36089.496, 44347.508, 46663, 47265, 54413, 158699]),
    ("加权平均股数-稀释(千股) Weighted-avg shares diluted", [51850.396, 44347.508, 46663, 67549, 73042, 158699]),
]

# ============================================================
# 资产负债表 (资产+、负债+、权益按印刷符号; 2022 = 部分列
#   —— BS 全表无一手披露, 仅权益表/现金流表尾注可得科目)
# ============================================================
BS_ROWS = [
    ("现金及现金等价物 Cash and cash equivalents", [26421, 161564, 664650, 368623, 750981, 1526046]),
    ("隔离现金-公司自持稳定币 Segregated for corporate-held stablecoins", [_, _, 5311, 275809, 294493, 822963]),
    ("隔离现金-稳定币持有人 Segregated for the benefit of stablecoin holders", [_, _, 35987965, 24346152, 43918572, 75067932]),
    ("隔离现金-客户及稳定币持有人(2020-21合并口径) Segregated for customers and stablecoin holders", [4024735, 42470603, _, _, _, _]),
    ("短期投资 Short-term investments", [13631, 0, _, _, _, _]),
    ("AFS债券-流动 Available-for-sale debt securities, current", [_, _, _, 152183, 0, _]),
    ("应收账款净额 Accounts receivable, net", [1590, 22703, _, 1940, 6418, 62866]),
    ("稳定币应收净额 Stablecoins (USDC) receivable, net", [_, 154837, _, 22559, 6957, 0]),
    ("客户数字资产保障资产 Assets related to safeguarding obligations", [67598, 738365, _, _, _, _]),
    ("待收处置对价-流动 Divestment consideration receivable, current", [3000, 1000, _, _, _, _]),
    ("预付及其他流动资产 Prepaid expenses and other current assets", [5922, 23163, _, 146645, 187528, 321660]),
    ("流动资产合计 Total current assets", [4142897, 43572235, _, 25313911, 45164949, 77801467]),
    ("受限现金 Restricted cash", [961, 20959, 15914, 3575, 3558, 2792]),
    ("待收处置对价-非流动 Divestment consideration receivable, non-current", [2000, 1000, _, _, _, _]),
    ("AFS债券-非流动 Available-for-sale debt securities, non-current", [_, _, _, 87940, 0, _]),
    ("投资 Investments (2020-21列名 Long-term investments)", [2307, 28233, _, 75874, 84114, 84265]),
    ("固定资产净额 Fixed assets, net", [443, 1225, _, 2619, 18682, 22791]),
    ("数字资产 Digital assets", [4665, 242073, _, 11339, 31330, 86515]),
    ("商誉 Goodwill", [24014, 24014, _, 169544, 169544, 265742]),
    ("无形资产净额 Intangible assets, net", [3462, 6606, _, 327381, 331394, 411146]),
    ("递延税资产净额 Deferred tax assets, net", [_, _, _, 0, 10223, 11110]),
    ("其他非流动资产 Other non-current assets", [_, _, _, 4400, 20615, 27379]),
    ("资产总计 Total assets", [4180749, 43896345, _, 25996583, 45834409, 78713207]),
    ("应付账款及应计费用 Accounts payable and accrued expenses", [23678, 53343, _, 152586, 287007, 360609]),
    ("递延收入(单列期) Deferred revenue", [888, 415, _, _, _, _]),
    ("借款-流动 Loans payable, current", [1758, 24039, _, _, _, _]),
    ("可转债-流动 Convertible debt, current", [10740, 0, _, _, 0, 36821]),
    ("收购应付-流动 Acquisition payables, current", [2371, 0, _, _, _, _]),
    ("USDC借入 USDC borrowed", [_, 154837, _, _, _, _]),
    ("归还数字资产抵押义务 Obligations to return digital asset collateral", [_, 191810, _, 4662, _, _]),
    ("客户数字资产保障义务 Obligations related to safeguarding digital assets", [67598, 738365, _, _, _, _]),
    ("稳定币持有人存款 Deposits from stablecoin holders (2020-21含客户存款)", [4021292, 42316946, _, 24276065, 43727363, 74912567]),
    ("其他流动负债 Other current liabilities (2024含归还抵押义务570·10-K口径)", [_, _, _, 4225, 16597, 18398]),
    ("流动负债合计 Total current liabilities", [4128325, 43479755, _, 24437538, 44030967, 75328395]),
    ("可转债-非流动 Convertible debt, non-current", [19874, 904122, _, 58487, 40717, 0]),
    ("借款-非流动 Loans payable, non-current", [24800, 0, _, _, _, _]),
    ("递延租金 Deferred rent", [411, 301, _, _, _, _]),
    ("递延税负债净额 Deferred tax liabilities, net", [4733, 0, _, 19616, 29559, 28702]),
    ("收购应付-非流动 Acquisition payables, non-current", [9905, 0, _, _, _, _]),
    ("权证负债 Warrant liability", [212, 1349, _, 1642, 1591, 0]),
    ("其他非流动负债 Other non-current liabilities", [_, _, _, 8569, 21281, 25337]),
    ("非流动负债合计 Total non-current liabilities", [59935, 905772, _, 88314, 93148, 54039]),
    ("负债合计 Total liabilities", [4188260, 44385527, _, 24525852, 44124115, 75382434]),
    ("可赎回可转优先股(夹层) Redeemable convertible preferred stock", [279002, 279226, 1131260, 1131260, 1139765, 0]),
    ("普通股/A类普通股 Common / Class A common stock", [4, 5, 5, 6, 6, 24]),
    ("B类普通股 Class B common stock", [_, _, _, _, _, 2]),
    ("库存股 Treasury stock at cost", [-2877, -2877, -2877, -2877, -2877, -2721]),
    ("资本公积 Additional paid-in capital", [91798, 113103, 1399612, 1723020, 1792969, 4610216]),
    ("累计亏损 Accumulated deficit", [-374920, -883350, -1652197, -1385607, -1223213, -1292709]),
    ("累计其他全面收益 Accumulated other comprehensive income (loss)", [-518, 4711, 3356, 4929, 3644, 14515]),
    ("归母权益 Total stockholders' equity attributable to common stockholders", [-286513, -768408, -252101, 339471, 570529, 3329327]),
    ("少数股东权益 Noncontrolling interests", [_, _, _, _, _, 1446]),
    ("股东权益合计 Total stockholders' equity (deficit)", [-286513, -768408, -252101, 339471, 570529, 3330773]),
]

# ============================================================
# 现金流量表 (流入+、流出−)
# ============================================================
CF_ROWS = [
    ("净利润 Net income (loss) (2026中报起为持续经营净利)", [3790, -508206, -768847, 267562, 155667, -69518]),
    ("折旧摊销 Depreciation and amortization", [4500, 3945, 13277, 34887, 50854, 76627]),
    ("AFS债券溢折价摊销 Accretion of premium on AFS debt securities", [0, 11112, -353422, -7738, -2268, 0]),
    ("数字资产已实现/未实现损益 Realized & unrealized (gains) losses on digital assets", [_, _, 269277, -13010, -12878, -18223]),
    ("数字资产减值损失 Digital assets impairment loss", [1256, 38256, _, _, _, _]),
    ("可转债/权证/内嵌衍生品公允价值变动 Change in FV of convertible debt, warrants & embedded derivatives", [3701, 389908, 486938, -25343, -10024, 71422]),
    ("服务取得数字资产 Digital assets received for services", [-791, -3377, -7235, -4476, -1500, -28567]),
    ("服务取得股权证券 Equity securities received for services", [-421, -791, _, _, _, -3302]),
    ("递延税 Deferred taxes", [4187, -4733, -786, -32893, -2806, -2153]),
    ("AFS债券及战略投资已实现/未实现损益 (gains) losses on AFS & strategic investments", [-13390, -4630, 26877, 1749, -434, -294]),
    ("长期资产出售损益 (Gains) losses on sale of long-lived assets", [_, _, _, -21521, 73, 22]),
    ("债务清偿收益 Gain on extinguishment of debt", [-33158, 0, _, _, _, _]),
    ("SPAC终止对价股份 Shares issued for merger termination", [_, _, 15520, _, _, _]),
    ("汇率重计量损益 Foreign currency remeasurement losses (gains)", [_, _, _, 1428, -565, 7790]),
    ("股权激励费用 Stock-based compensation", [3583, 20824, 69266, 107999, 50134, 566177]),
    ("普通股权证计提 Provision for warrants in common stock", [_, _, _, _, _, 23592]),
    ("Circle基金会捐赠 Charitable contributions to Circle Foundation", [_, _, _, _, _, 23149]),
    ("其他非现金及一次性项目 Other non-cash & one-off items (2020-21含多笔处置/抵押收益·归并明细见脚本注记)", [-2310, -28410, 5547, 3383, 887, 4936]),
    ("经营性资产负债变动-应收账款 Accounts receivable", [-676, -21113, 18735, 2244, -4569, -39379]),
    ("经营性资产负债变动-预付及其他流动资产 Prepaid & other current assets", [-859, -14304, -77571, -51161, -21764, -146502]),
    ("经营性资产负债变动-应付及应计 Accounts payable and accrued expenses", [15532, 29667, 227300, -123833, 132878, 81237]),
    ("经营性资产负债变动-其他流动负债/递延收入 Other current liabilities / deferred revenue", [133, -473, 2431, 291, 10891, -4885]),
    ("经营活动现金流量净额 Net cash provided by (used in) operating activities", [-14923, -92325, -72693, 139568, 344576, 542129]),
    ("购买AFS债券 Purchase of AFS debt securities", [0, -15695264, -102850973, -311639, -99313, 0]),
    ("出售/到期AFS债券 Sales and maturities of AFS securities", [0, 15676545, 94442236, 8827550, 341561, 0]),
    ("业务/资产处置收回 Proceeds from divestitures (Poloniex/Circle Invest/discontinued)", [10858, 3000, 1000, _, _, _]),
    ("权益法关联方并入取得现金 Cash acquired from acquisition of equity method affiliate (Centre)", [_, _, _, 1629, _, _]),
    ("出售股权证券/投资收回 Proceeds from sale of equity securities & investments", [_, 25988, _, 1107, 739, 1426]),
    ("购买投资 Purchase of investments", [_, -24022, -16032, -2661, -4265, -9291]),
    ("并购净现金流出 Business combinations & acquisition consideration, net of cash", [-21846, -12305, -43456, _, _, -7734]),
    ("出售数字资产收回/购买 Proceeds from sale / (purchase) of digital assets", [-3906, 5080, 0, 27301, 4805, 196]),
    ("资本化软件开发支出 Capitalization of software development costs", [-3177, -6813, -18315, -32862, -39098, -56200]),
    ("购置长期资产 Purchase of long-lived / fixed assets", [0, -1059, -3050, -654, -18128, -12432]),
    ("其他投资活动 Other investing (fixed asset sales)", [137, 0, _, _, _, _]),
    ("投资活动现金流量净额 Net cash provided by (used in) investing activities", [-17934, -28850, -8488590, 8509771, 186301, -84035]),
    ("稳定币持有人存款净变动 Net changes in deposits held for stablecoin holders (2020-21含客户存款)", [3499489, 38283027, 2176756, -20322155, 19452147, 31139764]),
    ("购买库存股 Purchase of treasury stock", [_, _, 0, -8745, 0, 0]),
    ("IPO及增发净募资 Proceeds from IPO & follow-on offering, net", [_, _, _, _, _, 1013097]),
    ("发行优先股 Proceeds from issuance of preferred stock (Series F)", [_, _, 400999, _, _, _]),
    ("发行可转债 Issuance of convertible notes", [0, 451025, _, _, _, _]),
    ("借款净变动 Loans (Genesis/PPP proceeds & repayments)", [26758, -12488, _, _, _, _]),
    ("RSU结算代扣税款 Payment of withholding taxes on RSU settlement", [_, _, _, _, _, -269732]),
    ("少数股东注资 Capital contribution from noncontrolling interest", [_, _, _, _, _, 1472]),
    ("资本化交易成本 Capitalized transaction costs", [_, _, _, 0, -3870, 0]),
    ("行权发行普通股 Proceeds from exercise of stock options / common stock", [689, 482, 486, 1037, 1614, 51759]),
    ("融资活动现金流量净额 Net cash provided by (used in) financing activities", [3526936, 38722046, 2578241, -20329863, 19449891, 31936360]),
    ("汇率变动影响 Effect of exchange rate changes", [165, 137, 3620, 1097, -7099, 57675]),
    ("现金等价物中AFS债券未实现损益 Unrealized g/(l) on AFS debt securities classified as cash equivalents", [_, _, 136, -254, -224, 0]),
    ("现金及受限隔离现金净变动 Net increase (decrease) in cash, restricted & segregated cash", [3494244, 38601008, -5979286, -11679681, 19973445, 32452129]),
    ("期初现金及受限隔离现金 Beginning of period", [557874, 4052118, 42653126, 36673840, 24994159, 44967604]),
    ("期末现金及受限隔离现金 End of period", [4052118, 42653126, 36673840, 24994159, 44967604, 77419733]),
    ("——期末构成: 现金及现金等价物", [26421, 161564, 664650, 368623, 750981, 1526046]),
    ("——期末构成: 受限现金", [961, 20959, 15914, 3575, 3558, 2792]),
    ("——期末构成: 隔离现金-公司自持稳定币", [_, _, 5311, 275809, 294493, 822963]),
    ("——期末构成: 隔离现金-稳定币持有人(2020-21含客户)", [4024736, 42470603, 35987965, 24346152, 43918572, 75067932]),
    ("补充披露: 已付所得税现金 Cash paid for income taxes", [0, 30, 7424, 81037, 75579, 13330]),
    ("补充披露: 已付利息现金 Cash paid for interest", [380, 0, 350, 253, 258, 180]),
    ("非现金: 可转债转股 Conversion of convertible debt", [_, _, _, 0, 14967, 89003]),
    ("非现金: 并购/资产收购股份对价 Non-cash consideration for acquisitions", [_, _, -141618, -209938, 0, -92294]),
    ("非现金: 资本化股权激励(内部开发软件) Capitalized SBC related to internally developed software", [_, _, 6262, 13118, 13646, 86905]),
    ("非现金: 优先股转普通股(IPO) Preferred converted to common at IPO", [_, _, _, _, _, 1140502]),
]

# 2020/2021 现金流适配注记(转录归并):
#  - 「可转债/权证/内嵌衍生品公允价值变动」2020=3489+212+0-(-174)…实为 3,489(可转债)+212(权证)=3,701;
#    2021=436,803(可转债)+1,137(权证)-48,032(内嵌)=389,908 —— 按 2022+ 合并口径归并转录。
#  - 「AFS债券及战略投资已实现/未实现损益」2020=-169(已实现)-13,221(未实现)=-13,390;
#    2021=-18,010+13,380=-4,630。
#  - 「其他非现金及一次性项目」= S-4 未单列进上述行的全部剩余调整项之和(勾稽闭环于 check_cf):
#    2020 = -2,877(库存股收益)-77(SeriesE权证到期)-625(Circle Invest出售收益)+769(权益法损失)
#           -174(可转债溢价摊销净额)+698(债务利息资本化)-24(递延租金) = -2,310;
#    2021 = -1,650(Circle Trade对价股权)+11,892(数字资产付链上费)-1,060(平台清退收益)-7,337(出售数字资产收益)
#           -32,218(数字资产抵押相关收益)+537(权益法损失)+668(可转债溢价摊销净额)+868(债务利息资本化)
#           -110(递延租金) = -28,410。
#  - 「并购净现金流出」2020=Poloniex 20,746+SeedInvest 1,100=21,846;
#    2021=SeedInvest 2,400+Poloniex 9,905=12,305。
#  - 「业务/资产处置收回」2020=Poloniex 10,000+Circle Invest 100+投资出售 758=10,858。
#  - 「借款净变动」2020=Genesis 25,000+PPP 1,758=26,758; 2021=-1,758(PPP偿还)-10,730(可转债偿还)=-12,488。

# ============================================================
# 分部/收入拆分 (千美元; 三个披露口径时代)
# ============================================================
SEG_ROWS = [
    ("— 10-K FY2025 口径 (Note 11 Revenue by Product and Service) —", [_, _, _, _, _, _]),
    ("储备收入 Reserve income", [_, _, _, 1430606, 1661084, 2636822]),
    ("订阅与服务收入 Subscription and services", [_, _, _, 6992, 6054, 84783]),
    ("交易收入 Transaction revenue", [_, _, _, 546, 2852, 24335]),
    ("其他 Other", [_, _, _, 12322, 6263, 702]),
    ("其他收入合计 Total other revenue", [_, _, _, 19860, 15169, 109820]),
    ("— S-1/424B4 口径 (2022-2024·Table 12.1) —", [_, _, _, _, _, _]),
    ("储备收入 Reserve income (S-1)", [_, _, 735885, 1430606, 1661084, _]),
    ("交易服务 Transaction services (S-1)", [_, _, 21885, 9896, 6013, _]),
    ("财资服务 Treasury services (S-1)", [_, _, 7509, 0, 0, _]),
    ("集成服务 Integration services (S-1)", [_, _, 1022, 6990, 6000, _]),
    ("其他 Other (S-1)", [_, _, 5751, 2974, 3156, _]),
    ("— S-4/A 口径 (2020-2021·利润表收入行) —", [_, _, _, _, _, _]),
    ("交易与财资服务 Transaction and Treasury services (S-4)", [2589, 47547, _, _, _, _]),
    ("储备利息收入 Reserve interest income (S-4)", [4435, 28464, _, _, _, _]),
    ("其他收入 Other revenue (S-4)", [8417, 8866, _, _, _, _]),
    ("营业总收入 Total revenue and reserve income", [15441, 84877, 772052, 1450466, 1676253, 2746642]),
]

# ============================================================
# USDC 运营指标 (百万美元/%/百万钱包; 来源: S-1 + 10-K MD&A 关键运营指标表)
# ============================================================
USDC_YEARS = [2022, 2023, 2024, 2025]
USDC_ROWS = [
    ("USDC流通量-期末(百万美元) USDC in circulation, EOP", [44554, 24412, 43857, 75266]),
    ("USDC流通量-期均(百万美元) USDC in circulation, average", [49861, 30467, 33342, 64870]),
    ("USDC铸造量(百万美元) USDC minted", [167609, 95833, 141342, 257465]),
    ("USDC赎回量(百万美元) USDC redeemed", [-165471, -115975, -121897, -226056]),
    ("储备收益率 Reserve return rate", [0.015, 0.047, 0.050, 0.041]),
    ("平台上USDC-期末(百万美元) USDC on platform, EOP", [537, 525, 2236, 12503]),
    ("平台上USDC日加权占比 Daily wtd-avg % of USDC on platform", [0.018, 0.020, 0.022, 0.111]),
    ("稳定币市占率-期末 Stablecoin market share, EOP (2022-24按S-1口径/2025按10-K口径)", [0.34, 0.20, 0.24, 0.28]),
    ("有效钱包数-期末(百万) Meaningful wallets (>$10 USDC), EOP", [1.76, 2.78, 4.26, 6.80]),
    ("公司自持USDC-期末(百万美元) Corporate-held USDC, EOP", [5.3, 275.8, 294.5, 823.0]),
    ("被冻结代币-期末(百万美元) Access denied tokens, EOP", [6.2, 77.7, 91.8, 116.8]),
    ("储备构成-银行现金(百万美元) Reserves: cash at banks, FV", [_, _, 6407, 9016]),
    ("储备构成-Circle Reserve Fund(百万美元·贝莱德USDXX)", [_, _, 37514, 66317]),
    ("储备构成-银行现金平均收益率", [_, _, 0.0396, 0.0338]),
    ("储备构成-Circle Reserve Fund平均收益率", [_, _, 0.0509, 0.0415]),
    ("链上交易量(万亿美元) USDC onchain transaction volume", [_, _, _, 11.9]),
]
# 季度储备收益率 (S-1 印刷: 1Q22-1Q25; 2Q26/2Q25 来自 10-Q FY2026Q2)
QTR_RETURN = [
    ("1Q22", 0.0014, 0.0009, 0.0029), ("2Q22", 0.0061, 0.0071, 0.0104),
    ("3Q22", 0.0206, 0.0215, 0.0261), ("4Q22", 0.0335, 0.0362, 0.0399),
    ("1Q23", 0.0424, 0.0450, 0.0459), ("2Q23", 0.0466, 0.0497, 0.0504),
    ("3Q23", 0.0516, 0.0524, 0.0527), ("4Q23", 0.0519, 0.0532, 0.0528),
    ("1Q24", 0.0513, 0.0531, 0.0523), ("2Q24", 0.0517, 0.0532, 0.0525),
    ("3Q24", 0.0511, 0.0528, 0.0500), ("4Q24", 0.0449, 0.0468, 0.0440),
    ("1Q25", 0.0416, 0.0433, 0.0421), ("2Q25", 0.0410, None, None),
    ("2Q26", 0.0350, None, None),
]

# ============================================================
# 分销成本 (百万美元; 两申报口径并存·见 README)
# ============================================================
DIST_ROWS = [
    ("分销与交易成本合计(千美元·利润表行) Distribution and transaction costs", [-2826, -11890, -286953, -719806, -1010811, -1661549]),
    ("其中Coinbase协议成本(百万美元·S-1口径) Coinbase distribution costs per S-1", [_, _, 248.1, 691.3, 907.9, _]),
    ("其中Coinbase协议成本(百万美元·10-K口径) Coinbase distribution costs per 10-K", [_, _, _, _, 924.5, 1400.0]),
    ("Binance协议(百万美元) Binance: 2024一次性预付60.3; 2025较2024增量+152.1(水平未披露)", [_, _, _, _, 60.3, _]),
]

# ============================================================
# 2026 中期 (10-Q; 千美元)
# ============================================================
H1_COLS = ["2025H1", "2025Q2", "2026Q1", "2026Q2", "2026H1"]
H1_ROWS = [
    ("储备收入 Reserve income", [1192185, 634274, 652508, 667733, 1320241]),
    ("其他收入 Other revenue", [44466, 23804, 41625, 33582, 75207]),
    ("营业总收入 Total revenue and reserve income", [1236651, 658078, 694133, 701315, 1395448]),
    ("分销交易及其他成本合计", [-754589, -406942, -406781, -412470, -819251]),
    ("营业费用合计", [-714704, -576718, -242350, -254486, -496836]),
    ("持续经营营业利润", [-232642, -325582, 45002, 34359, 79361]),
    ("归母净利润 Net income (loss) attributable to common stockholders", [-417309, -482100, 55253, 48221, 103474]),
    ("经营活动现金流量净额 (H1口径)", [303716, _, _, _, 538505]),
    ("USDC流通量-期末(百万美元)", [61333, 61333, _, 73269, 73269]),
    ("USDC流通量-期均(百万美元)", [57574, 61039, _, 76524, 75865]),
    ("储备收益率", [0.042, 0.041, _, 0.035, 0.035]),
    ("平台上USDC-期末(百万美元)", [6040, 6040, _, 12442, 12442]),
    ("平台上USDC日加权占比", [0.066, 0.074, _, 0.195, 0.183]),
    ("RLDC(百万美元·公司披露) Revenue less distribution costs", [482, 251, _, 289, 576]),
    ("Adjusted EBITDA(百万美元·公司口径非GAAP)", [248, 126, _, 143, 295]),
    ("稳定币持有人存款-期末(千美元) Deposits from stablecoin holders", [_, _, _, 72927544, 72927544]),
]
# 2026Q1 列 = H1 − Q2 派生(利润表行), 与 10-Q Q1 印刷一致性由 XBRL 季度值旁证; USDC 指标 Q1 未单列(_)。

# ============================================================
# 季度经营 (业绩稿 8-K Ex-99.1 印刷; 摘要块=百万美元/比率, 精确块=千美元)
# ============================================================
QTR_COLS = ["2024Q2", "2024Q3", "2024Q4", "2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2"]
QTR_ROWS = [
    ("储备收入(百万美元)", [423, 445, 433, 558, 634, 711, 733, 653, 668]),
    ("其他收入(百万美元)", [7, 1, 2, 21, 24, 29, 37, 42, 34]),
    ("营业总收入(百万美元)", [430, 446, 435, 579, 658, 740, 770, 694, 701]),
    ("分销交易及其他成本合计(百万美元)", [248, 258, 305, 348, 407, 448, 461, 407, 412]),
    ("RLDC 收入减分销成本(百万美元)", [182, 188, 131, 231, 251, 292, 309, 287, 289]),
    ("RLDC率", [0.42, 0.42, 0.30, 0.40, 0.38, 0.39, 0.40, 0.41, 0.41]),
    ("净储备利差率 Net reserve margin", [0.42, 0.42, 0.30, 0.38, 0.36, 0.37, 0.37, 0.38, 0.39]),
    ("持续经营净利/归母(千美元·2025Q4起扣NCI后归母)", [32923, 70996, 4433, 64791, -482100, 214385, 133416, 55253, 48221]),
    ("SBC股权激励费用(千美元)", [16749, 12763, 11142, 12716, 434966, 59081, 59414, 51836, 53599]),
    ("折旧摊销(千美元)", [12632, 13122, 13507, 13880, 14209, 23002, 25536, 26767, 29896]),
    ("Adjusted EBITDA-旧定义(千美元·公司口径)", [82603, 93285, 32725, 122439, 125833, 166461, 167482, 140813, 135841]),
    ("Adjusted EBITDA-新定义(千美元·2026Q1起启用·含SBC相关payroll税加回)", [_, _, _, _, 132997, 171476, 175910, 151401, 143478]),
    ("USDC流通量-期末(百万美元·已披露季度)", [_, _, 43857, 59976, 61333, _, 75266, _, 73269]),
]


def check_qtr():
    ni = V(QTR_ROWS, "持续经营净利/归母")
    chk(eq(sum(ni[3:7]), -69508), "QTR 2025四季净利加总≠年报归母-69,508")
    chk(eq(ni[7] + ni[8], 103474), "QTR 2026H1净利加总≠10-Q 103,474")
    rev = V(QTR_ROWS, "营业总收入(百万美元)")
    chk(eq(sum(rev[3:7]), 2747, tol=1), "QTR 2025四季营收加总≠2,747百万")
    resv = V(QTR_ROWS, "储备收入(百万美元)")
    chk(eq(sum(resv[3:7]), 2637, tol=1), "QTR 2025四季储备收入加总≠2,637百万")


# ============================================================
# 员工数
# ============================================================
EMP_ROWS = [
    ("员工总数(约) Employees (approx.)", {"2025": 1100}),
]

# ============================================================
# 勾稽校验
# ============================================================
FAIL = []


def V(rows, label_prefix):
    for lb, vals in rows:
        if lb.startswith(label_prefix):
            return vals
    raise KeyError(label_prefix)


def chk(cond, msg):
    if not cond:
        FAIL.append(msg)


def eq(a, b, tol=0):
    if a is None or b is None:
        return True  # 缺项不勾
    return abs(a - b) <= tol


def check_is():
    rev_r = V(IS_ROWS, "储备收入")
    rev_t = V(IS_ROWS, "交易与财资服务收入")
    rev_o = V(IS_ROWS, "其他收入")
    rev = V(IS_ROWS, "营业总收入")
    c_d = V(IS_ROWS, "分销与交易成本")
    c_t = V(IS_ROWS, "交易与财资服务成本")
    c_o = V(IS_ROWS, "其他成本")
    c = V(IS_ROWS, "分销交易及其他成本合计")
    opex = V(IS_ROWS, "营业费用合计")
    op = V(IS_ROWS, "持续经营营业利润")
    oth = V(IS_ROWS, "其他收益(费用)净额")
    pre = V(IS_ROWS, "除税前利润")
    tax = V(IS_ROWS, "所得税(费用)收益")
    netc = V(IS_ROWS, "持续经营净利润")
    disc = V(IS_ROWS, "终止经营净损益")
    net = V(IS_ROWS, "净利润 Net income")
    nci = V(IS_ROWS, "少数股东损益")
    attr = V(IS_ROWS, "归母净利润")
    oci = V(IS_ROWS, "OCI合计")
    oci_attr = V(IS_ROWS, "OCI归母")
    comp = V(IS_ROWS, "全面收益(归母)")
    opex_items = [V(IS_ROWS, p) for p in ["薪酬费用", "一般及行政费用", "折旧摊销费用", "IT基础设施成本",
                                          "营销费用", "无形资产出售收益", "SPAC合并终止费用", "数字资产损益及减值"]]
    oci_items = [V(IS_ROWS, p) for p in ["——外币折算差异", "——AFS债券未实现损益", "——可转债信用风险未实现损益"]]
    disc_items = [V(IS_ROWS, p) for p in ["——其中 Circle Trade", "——其中 Circle Invest", "——其中 Poloniex"]]
    for i, y in enumerate(YEARS):
        chk(eq(sum(x[i] or 0 for x in (rev_r, rev_t, rev_o)), rev[i]), f"IS{y} 收入分项≠合计")
        chk(eq(sum(x[i] or 0 for x in (c_d, c_t, c_o)), c[i]), f"IS{y} 成本分项≠合计")
        chk(eq(sum(x[i] or 0 for x in opex_items), opex[i]), f"IS{y} 营业费用分项≠合计")
        chk(eq(rev[i] + c[i] + opex[i], op[i]), f"IS{y} 收入+成本+费用≠营业利润")
        chk(eq(op[i] + oth[i], pre[i]), f"IS{y} 营业利润+其他≠税前")
        chk(eq(pre[i] + tax[i], netc[i]), f"IS{y} 税前+税≠持续净利")
        chk(eq(netc[i] + disc[i], net[i]), f"IS{y} 持续+终止≠净利")
        chk(eq(net[i] - (nci[i] or 0), attr[i]), f"IS{y} 净利−少数股东≠归母")
        chk(eq(sum(x[i] or 0 for x in oci_items), oci[i]), f"IS{y} OCI分项≠合计")
        chk(eq(attr[i] + oci_attr[i], comp[i]), f"IS{y} 归母+OCI归母≠全面收益")
        if y in (2020, 2021):
            chk(eq(sum(x[i] or 0 for x in disc_items), disc[i]), f"IS{y} 终止经营分项≠合计")


def check_bs():
    get = lambda p: V(BS_ROWS, p)
    ca_items = ["现金及现金等价物", "隔离现金-公司自持稳定币", "隔离现金-稳定币持有人", "隔离现金-客户及稳定币持有人",
                "短期投资", "AFS债券-流动", "应收账款净额", "稳定币应收净额", "客户数字资产保障资产",
                "待收处置对价-流动", "预付及其他流动资产"]
    nca_items = ["受限现金", "待收处置对价-非流动", "AFS债券-非流动", "投资 Investments", "固定资产净额",
                 "数字资产 Digital assets", "商誉", "无形资产净额", "递延税资产净额", "其他非流动资产"]
    cl_items = ["应付账款及应计费用", "递延收入(单列期)", "借款-流动", "可转债-流动", "收购应付-流动",
                "USDC借入", "归还数字资产抵押义务", "客户数字资产保障义务", "稳定币持有人存款", "其他流动负债"]
    ncl_items = ["可转债-非流动", "借款-非流动", "递延租金", "递延税负债净额", "收购应付-非流动",
                 "权证负债", "其他非流动负债"]
    eq_items = ["普通股/A类普通股", "B类普通股", "库存股", "资本公积", "累计亏损", "累计其他全面收益"]
    for i, y in enumerate(YEARS):
        if y == 2022:
            continue  # BS 全表无一手披露, 只存部分科目, 不做恒等式勾稽
        chk(eq(sum(V(BS_ROWS, p)[i] or 0 for p in ca_items), get("流动资产合计")[i]), f"BS{y} 流动资产分项≠合计")
        chk(eq(get("流动资产合计")[i] + sum(V(BS_ROWS, p)[i] or 0 for p in nca_items), get("资产总计")[i]), f"BS{y} 资产分项≠总计")
        chk(eq(sum(V(BS_ROWS, p)[i] or 0 for p in cl_items), get("流动负债合计")[i]), f"BS{y} 流动负债分项≠合计")
        chk(eq(sum(V(BS_ROWS, p)[i] or 0 for p in ncl_items), get("非流动负债合计")[i]), f"BS{y} 非流动负债分项≠合计")
        chk(eq(get("流动负债合计")[i] + get("非流动负债合计")[i], get("负债合计")[i]), f"BS{y} 负债分节≠合计")
        chk(eq(sum(V(BS_ROWS, p)[i] or 0 for p in eq_items), get("归母权益")[i]), f"BS{y} 权益分项≠归母权益")
        chk(eq(get("归母权益")[i] + (get("少数股东权益")[i] or 0), get("股东权益合计")[i]), f"BS{y} 归母+NCI≠权益合计")
        chk(eq(get("负债合计")[i] + get("可赎回可转优先股(夹层)")[i] + get("股东权益合计")[i], get("资产总计")[i]),
            f"BS{y} 负债+夹层+权益≠资产")


def check_cf():
    get = lambda p: V(CF_ROWS, p)
    ocf = get("经营活动现金流量净额")
    icf = get("投资活动现金流量净额")
    fcf = get("融资活动现金流量净额")
    fx = get("汇率变动影响")
    afs = get("现金等价物中AFS债券未实现损益")
    dlt = get("现金及受限隔离现金净变动")
    beg = get("期初现金及受限隔离现金")
    end = get("期末现金及受限隔离现金")
    for i, y in enumerate(YEARS):
        chk(eq(ocf[i] + icf[i] + fcf[i] + fx[i] + (afs[i] or 0), dlt[i]), f"CF{y} 三活动+汇率≠净变动")
        chk(eq(beg[i] + dlt[i], end[i]), f"CF{y} 期初+净变动≠期末")
        comp = sum((V(CF_ROWS, p)[i] or 0) for p in ["——期末构成: 现金及现金等价物", "——期末构成: 受限现金",
                                                     "——期末构成: 隔离现金-公司自持稳定币", "——期末构成: 隔离现金-稳定币持有人"])
        chk(eq(comp, end[i], tol=1), f"CF{y} 期末构成≠期末合计")  # 2020 印刷层 1 千美元差(4,024,736 vs BS 4,024,735)
        if i > 0:
            chk(eq(end[i - 1], beg[i]), f"CF{y} 期初≠上年期末")
    # 经营段分项 = 净额 (「其他非现金及一次性项目」为 S-4 未单列项归并行, 此式即其构造校验)
    op_items = ["净利润 Net income", "折旧摊销 Depreciation", "AFS债券溢折价摊销", "数字资产已实现/未实现损益",
                "数字资产减值损失", "可转债/权证/内嵌衍生品公允价值变动", "服务取得数字资产", "服务取得股权证券",
                "递延税 Deferred taxes", "AFS债券及战略投资已实现/未实现损益", "长期资产出售损益", "债务清偿收益",
                "SPAC终止对价股份", "汇率重计量损益", "股权激励费用", "普通股权证计提", "Circle基金会捐赠",
                "其他非现金及一次性项目", "经营性资产负债变动-应收账款", "经营性资产负债变动-预付及其他流动资产",
                "经营性资产负债变动-应付及应计", "经营性资产负债变动-其他流动负债/递延收入"]
    for i, y in enumerate(YEARS):
        s = sum((V(CF_ROWS, p)[i] or 0) for p in op_items)
        chk(eq(s, ocf[i]), f"CF{y} 经营段分项和({s})≠经营净额({ocf[i]})")
    inv_items = ["购买AFS债券", "出售/到期AFS债券", "业务/资产处置收回", "权益法关联方并入取得现金",
                 "出售股权证券/投资收回", "购买投资 Purchase", "并购净现金流出", "出售数字资产收回/购买",
                 "资本化软件开发支出", "购置长期资产", "其他投资活动"]
    for i, y in enumerate(YEARS):
        s = sum((V(CF_ROWS, p)[i] or 0) for p in inv_items)
        chk(eq(s, icf[i]), f"CF{y} 投资段分项和({s})≠投资净额({icf[i]})")
    fin_items = ["稳定币持有人存款净变动", "购买库存股", "IPO及增发净募资", "发行优先股", "发行可转债",
                 "借款净变动", "RSU结算代扣税款", "少数股东注资", "资本化交易成本", "行权发行普通股"]
    for i, y in enumerate(YEARS):
        s = sum((V(CF_ROWS, p)[i] or 0) for p in fin_items)
        chk(eq(s, fcf[i]), f"CF{y} 融资段分项和({s})≠融资净额({fcf[i]})")
    # 与 BS 衔接: 期末构成 vs BS 对应行 (2020 有 1 千美元印刷差)
    for i, y in enumerate(YEARS):
        bs_cash = V(BS_ROWS, "现金及现金等价物")[i]
        chk(eq(V(CF_ROWS, "——期末构成: 现金及现金等价物")[i], bs_cash, tol=0), f"CF{y} 现金构成≠BS现金")


def check_seg():
    for i, y in enumerate(YEARS):
        tot = V(SEG_ROWS, "营业总收入")[i]
        if y >= 2023:
            s = V(SEG_ROWS, "储备收入 Reserve income")[i] + V(SEG_ROWS, "其他收入合计")[i]
            chk(eq(s, tot), f"SEG{y} 10-K口径 储备+其他≠总收入")
            s2 = sum(V(SEG_ROWS, p)[i] for p in ["订阅与服务收入", "交易收入", "其他 Other"])
            chk(eq(s2, V(SEG_ROWS, "其他收入合计")[i]), f"SEG{y} 其他收入分项≠合计")
        if 2022 <= y <= 2024:
            s = sum(V(SEG_ROWS, p)[i] or 0 for p in ["储备收入 Reserve income (S-1)", "交易服务", "财资服务",
                                                     "集成服务", "其他 Other (S-1)"])
            chk(eq(s, tot), f"SEG{y} S-1口径分项≠总收入")
        if y <= 2021:
            s = sum(V(SEG_ROWS, p)[i] for p in ["交易与财资服务 Transaction", "储备利息收入", "其他收入 Other revenue (S-4)"])
            chk(eq(s, tot), f"SEG{y} S-4口径分项≠总收入")


def check_h1():
    for lb, vals in H1_ROWS:
        d = dict(zip(H1_COLS, vals))
        if lb.startswith(("储备收入", "其他收入", "营业总收入", "分销交易", "营业费用", "持续经营营业利润", "归母净利润")):
            if all(d[k] is not None for k in ("2026Q1", "2026Q2", "2026H1")):
                chk(eq(d["2026Q1"] + d["2026Q2"], d["2026H1"]), f"H1 2026 {lb}: Q1+Q2≠H1")
    rev = dict(zip(H1_COLS, V(H1_ROWS, "营业总收入")))
    c = dict(zip(H1_COLS, V(H1_ROWS, "分销交易及其他成本合计")))
    ox = dict(zip(H1_COLS, V(H1_ROWS, "营业费用合计")))
    op = dict(zip(H1_COLS, V(H1_ROWS, "持续经营营业利润")))
    for k in ("2025H1", "2025Q2", "2026Q2", "2026H1"):
        chk(eq(rev[k] + c[k] + ox[k], op[k]), f"H1 {k} 收入+成本+费用≠营业利润")


# ============================================================
# XBRL 独立核 (FY2023-2025 年度值; val 单位=美元 → /1000 对比)
# ============================================================
XBRL_MAP = [
    # (us-gaap concept, 表, 科目前缀, 期间类型 dur/inst)
    ("Revenues", IS_ROWS, "营业总收入", "dur"),
    ("RevenueFromContractWithCustomerExcludingAssessedTax", IS_ROWS, "其他收入", "dur"),
    ("OperatingIncomeLoss", IS_ROWS, "持续经营营业利润", "dur"),
    ("IncomeTaxExpenseBenefit", IS_ROWS, "所得税(费用)收益", "dur-neg"),
    ("ProfitLoss", IS_ROWS, "净利润 Net income", "dur"),
    ("NetIncomeLoss", IS_ROWS, "归母净利润", "dur"),
    ("Assets", BS_ROWS, "资产总计", "inst"),
    ("Liabilities", BS_ROWS, "负债合计", "inst"),
    ("StockholdersEquity", BS_ROWS, "归母权益", "inst"),
    ("Goodwill", BS_ROWS, "商誉", "inst"),
    ("CashAndCashEquivalentsAtCarryingValue", BS_ROWS, "现金及现金等价物", "inst"),
    ("NetCashProvidedByUsedInOperatingActivities", CF_ROWS, "经营活动现金流量净额", "dur"),
    ("NetCashProvidedByUsedInInvestingActivities", CF_ROWS, "投资活动现金流量净额", "dur"),
    ("NetCashProvidedByUsedInFinancingActivities", CF_ROWS, "融资活动现金流量净额", "dur"),
    ("ShareBasedCompensation", CF_ROWS, "股权激励费用", "dur"),
]


def check_xbrl():
    path = os.path.join(HERE, "_xbrl", "companyfacts-CIK0001876042.json")
    with open(path) as f:
        facts = json.load(f)["facts"]["us-gaap"]
    n_checked = 0
    for concept, rows, prefix, kind in XBRL_MAP:
        c = facts.get(concept)
        if not c:
            FAIL.append(f"XBRL 缺概念 {concept}")
            continue
        items = c["units"].get("USD", [])
        mine = V(rows, prefix)
        for i, y in enumerate(YEARS):
            if y < 2023 or mine[i] is None:
                continue
            want = None
            for it in items:
                if it.get("form") not in ("10-K", "10-K/A"):
                    continue
                if kind.startswith("dur"):
                    if it.get("start") == f"{y}-01-01" and it.get("end") == f"{y}-12-31":
                        want = it["val"]
                else:
                    if it.get("end") == f"{y}-12-31" and it.get("start") is None:
                        want = it["val"]
            if want is None:
                continue  # 该概念该年未打 10-K 标签, 不算失败
            w = want / 1000.0
            if kind == "dur-neg":
                w = -w  # XBRL 税费为正数; 本库税负=负
            n_checked += 1
            chk(eq(round(w), round(mine[i]), tol=1), f"XBRL {concept} {y}: 申报{w:,.0f} ≠ 转录{mine[i]:,.0f}")
    print(f"XBRL 独立核: {n_checked} 格比对")


# ============================================================
# 财务比率 (通用底 derived + circle 定制层)
# ============================================================
def build_ratios():
    PL = {lb: vals for lb, vals in IS_ROWS}
    BS = {lb: vals for lb, vals in BS_ROWS}
    CF = {lb: vals for lb, vals in CF_ROWS}
    common, _unmatched = derived.compute_common_ratios(PL, BS, CF)
    rows = [(c[0], [round(x, 4) if isinstance(x, float) else x for x in c[1]])
            for c in common if any(x is not None for x in c[1])]

    def col(rowlist, prefix):
        return V(rowlist, prefix)

    rev = col(IS_ROWS, "营业总收入")
    cst = col(IS_ROWS, "分销交易及其他成本合计")
    resv = col(IS_ROWS, "储备收入")
    dist = col(IS_ROWS, "分销与交易成本")
    net = col(IS_ROWS, "净利润 Net income")
    ocf = col(CF_ROWS, "经营活动现金流量净额")
    sbc = col(CF_ROWS, "股权激励费用")
    sbc_cap = col(CF_ROWS, "非现金: 资本化股权激励(内部开发软件)")
    capex_sw = col(CF_ROWS, "资本化软件开发支出")
    capex_ll = col(CF_ROWS, "购置长期资产")
    cash = col(BS_ROWS, "现金及现金等价物")
    corp_st = col(BS_ROWS, "隔离现金-公司自持稳定币")
    conv_c = col(BS_ROWS, "可转债-流动")
    conv_nc = col(BS_ROWS, "可转债-非流动")
    loans_c = col(BS_ROWS, "借款-流动")
    loans_nc = col(BS_ROWS, "借款-非流动")
    ta = col(BS_ROWS, "资产总计")
    seg_hold = col(BS_ROWS, "隔离现金-稳定币持有人")
    seg_old = col(BS_ROWS, "隔离现金-客户及稳定币持有人")

    def z(v):
        return v or 0

    rldc = [rev[i] + cst[i] if rev[i] is not None else None for i in range(N)]
    rows += [
        ("—— circle 定制层 ——", [None] * N),
        ("RLDC 收入减分销成本(千美元) Revenue less distribution costs", rldc),
        ("RLDC率 RLDC margin", [round(rldc[i] / rev[i], 4) if rldc[i] is not None else None for i in range(N)]),
        ("分销与交易成本/储备收入 Distribution cost / reserve income", [round(-dist[i] / resv[i], 4) if dist[i] else None for i in range(N)]),
        ("储备收入/总营收 Reserve income concentration", [round(resv[i] / rev[i], 4) for i in range(N)]),
        ("储备收益率(公司披露) Reserve return rate", [None, None, 0.015, 0.047, 0.050, 0.041]),
        ("SBC股权激励费用(千美元·费用化) Stock-based compensation expensed", sbc),
        ("SBC资本化(千美元) SBC capitalized to software", sbc_cap),
        ("SBC费用化/总营收 SBC / revenue", [round(sbc[i] / rev[i], 4) if sbc[i] else None for i in range(N)]),
        ("Capex(千美元·软件资本化+长期资产) Capex", [-(z(capex_sw[i]) + z(capex_ll[i])) or None for i in range(N)]),
        ("Capex/经营现金流 Capex / OCF", [round((z(capex_sw[i]) + z(capex_ll[i])) / -ocf[i], 4) if ocf[i] and ocf[i] > 0 else None for i in range(N)]),
        ("公司净现金(千美元·现金+自持稳定币现金−可转债−借款·不含储备) Corporate net cash", [
            z(cash[i]) + z(corp_st[i]) - z(conv_c[i]) - z(conv_nc[i]) - z(loans_c[i]) - z(loans_nc[i])
            if cash[i] is not None and YEARS[i] != 2022 else None for i in range(N)]),  # 2022 BS不全·负债未知不算
        ("储备资产/总资产 Segregated reserve assets / total assets", [
            round((z(seg_hold[i]) + z(seg_old[i])) / ta[i], 4) if ta[i] else None for i in range(N)]),
        ("Adjusted EBITDA(千美元·公司口径非GAAP·2022-23为S-1百万位约值)", [None, None, 96000, 395000, 284871, 582215]),
        ("IPO+增发净募资(千美元·2025) IPO + follow-on net proceeds", [None] * 5 + [1013097]),
        ("累计分红+回购(千美元·上市以来) Dividends + buybacks since IPO", [None] * 5 + [0]),
    ]
    return rows


# ============================================================
# 写出
# ============================================================
def write_csv(name, header_comment, cols, rows):
    path = os.path.join(HERE, name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write(header_comment.rstrip("\n") + "\n")
        w = csv.writer(f)
        w.writerow(["科目"] + cols)
        for lb, vals in rows:
            out = []
            for v in vals:
                if v is None:
                    out.append("")
                elif isinstance(v, float) and not v.is_integer():
                    out.append(f"{v}")
                else:
                    out.append(f"{int(v)}")
            w.writerow([lb] + out)
    print(f"写出 {name}: {len(rows)} 行")


def main():
    check_is()
    check_bs()
    check_cf()
    check_seg()
    check_h1()
    check_qtr()
    check_xbrl()
    if FAIL:
        print("\n❌ 勾稽/独立核未过, 拒绝写出:")
        for m in FAIL:
            print("  -", m)
        sys.exit(1)
    print("✅ 勾稽全平 (利润表/资产负债表/现金流量表/分部/中期 + XBRL 独立核)")

    ycols = [str(y) for y in YEARS]
    write_csv("利润表.csv",
              "# 单位:千美元(USD thousands·与SEC申报印刷一致);费用/损失=负数;EPS=美元/股;覆盖2020-2025;"
              "来源:一手申报印刷报表逐行转录(S-4/A 2022-11-14→FY2020-21·424B4 2025-06-05→FY2022·10-K FY2025→FY2023-25·report/circle/);"
              "FY2023-25 经 SEC XBRL companyfacts 逐格独立核;2020-21与2022+收入/成本列报口径不同(断点见README)",
              ycols, IS_ROWS)
    write_csv("资产负债表.csv",
              "# 单位:千美元;覆盖2020-2025;2022列=部分科目(FY2022资产负债表全表无一手披露·仅权益表+现金流尾注可得,恒等式勾稽跳过该年);"
              "2024列取10-K口径(归还抵押义务570并入其他流动负债);来源同利润表",
              ycols, BS_ROWS)
    write_csv("现金流量表.csv",
              "# 单位:千美元;流入+/流出−;覆盖2020-2025;稳定币持有人存款变动列在融资活动(美国同业惯例);"
              "2020-21 若干 S-4 单列项按 2022+ 口径归并(归并规则见脚本内注记·分项和=净额勾稽闭环);来源同利润表",
              ycols, CF_ROWS)
    write_csv("分部营收.csv",
              "# 单位:千美元;收入拆分三个披露口径时代并存(S-4 2020-21 / S-1 2022-24 / 10-K 2023-25),重叠年份互证一致;"
              "单一可报告分部(CODM合并审阅·10-K Note2),无地理收入拆分",
              ycols, SEG_ROWS)
    write_csv("USDC运营.csv",
              "# 公司披露运营指标(10-K/S-1 MD&A);单位见各行;市占率口径:S-1=占全部法币稳定币/10-K=占流通>1亿美元的美元法币稳定币(CoinMarketCap);"
              "USDC流通量排除tokens-allowed-but-not-issued/被冻结/待销毁,含公司自持",
              [str(y) for y in USDC_YEARS], USDC_ROWS)
    # 季度储备收益率块追加到 USDC运营.csv
    with open(os.path.join(HERE, "USDC运营.csv"), "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([])
        w.writerow(["季度", "储备收益率", "季均SOFR", "季均3个月美债"])
        for q, r, s, t in QTR_RETURN:
            w.writerow([q, r, "" if s is None else s, "" if t is None else t])
    print("追加 季度储备收益率块 → USDC运营.csv")
    write_csv("分销成本.csv",
              "# 分销成本抽取;Coinbase金额两口径并存:S-1(2022-24)与10-K(2024-25)对2024年披露值不同(907.9 vs 924.5百万·协议范围口径差异,README详述);"
              "Binance 2024-11协议一次性预付60.3百万+按月激励费(水平未披露·2025较2024增量+152.1百万)",
              ycols, DIST_ROWS)
    write_csv("中期-2026H1.csv",
              "# 单位:千美元(标注除外);来源:10-Q FY2026Q1/Q2(未经审计);2026Q1利润表列=H1−Q2派生;"
              "2026-06-30 USDC流通量73,269百万美元较2025年末75,266百万美元回落",
              H1_COLS, H1_ROWS)
    write_csv("季度经营.csv",
              "# 季度序列;来源:业绩稿 8-K Ex-99.1 印刷(Q2'25/FY25/Q2'26 三稿拼接·SEC Archives)+10-Q;"
              "摘要行=百万美元(业绩稿四舍五入·季加总与年报差≤1属舍入),净利/SBC/D&A/EBITDA=千美元(对账表精确值);"
              "2024Q4 RLDC率跌到30%=Binance一次性预付60.3百万美元所致;Adjusted EBITDA为公司口径非GAAP",
              QTR_COLS, QTR_ROWS)
    ratio_rows = build_ratios()
    write_csv("财务比率.csv",
              "# 派生比率(比率=小数;金额行=千美元);通用底 scripts/derived.py + circle 定制层;"
              "无毛利概念→RLDC(收入减分销成本)为本行业类毛利线;US GAAP无扣非披露→扣非行n/a;"
              "2020-22权益为负/净利为负年份的ROE与现金含量比率无意义,以RLDC/EBITDA与OCF绝对值观察;上市以来分红=0",
              ycols, ratio_rows)
    # 员工数
    with open(os.path.join(HERE, "员工数.csv"), "w", newline="", encoding="utf-8") as f:
        f.write("# 来源:10-K FY2025 Item 1 Human Capital(约数);2020-2024未披露年度员工数(S-1未给整数·标待补)\n")
        w = csv.writer(f)
        w.writerow(["科目", "2025"])
        w.writerow(["员工总数(约) Employees (approx.)", 1100])
    print("写出 员工数.csv")


if __name__ == "__main__":
    main()
