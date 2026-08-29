# -*- coding: utf-8 -*-
"""福耀玻璃(600660) 三表 + 派生比率 → 写 CSV,内置勾稽自洽校验(校验不过不写出)。

数据血缘(2006-2025 · 20 年):
  主数据源 = 年报「合并」三表文本解析(pypdf 文本层 → 确定性解析器 → _extract_json/fy*.json):
    - 奇数年 = 该年年报本年列;偶数年 = 次年年报上年比较列(重述口径,与泸州老窖建库同策略)
    - 例外: 2010 用 2010 年报本年列(标准格式科目更全;另与 2011 年报上年列交叉核验)
            2012 用 2013 年报上年列(2012 年报报表页无文本层,唯一可得文本源)
            2013 用 2013 年报本年列(as-reported;2014 年报因会计政策变更追溯调整了比较数,
              其资产负债表为三栏列报[2014末/2013调整/2012调整],与 2013 年报原值总资产差
              +80,209,399/+103,021,566 —— 归因⏳待补附注;IS/CF 比较列与原值一致,作交叉核验)
  锚点源 = 各年年报「主要会计数据」页(_extract_json/main_anchors.json):
    营收/归母/扣非/经营现金流净额/总资产/归母净资产 —— 每年用**该年自家年报**的披露值,
    与采用的三表值逐年核对(偶数年即为「本年列 vs 次年上年列」的跨源重述检测)。

报表版式沿革(影响解析与勾稽公式):
  - 2007-2010 年报: 标准 CAS 格式(era A: 资产减值损失在营业总成本内,正数)
  - 2011-2013 年报: 普华永道审计报表版式(era P: 合并/公司四列并排,无营业总收入/总成本行,
    现金流出为括号负数;权益中「外币报表折算差额」独立列示 → 并入「其他综合收益」行;
    无研发费用行[并在管理费用],无利息费用/利息收入拆分行)
  - 2014-2018 年报: 标准格式 era A(2014 年报资产负债表因追溯调整为三栏列报,见上)
  - 2019-2025 年报: 标准格式 era B(减值损失移营业利润上方,负数=损失;营业总成本不含减值)
  - 2015-03 H 股(3606.HK)上市:2015 吸收投资收到的现金 65.24 亿=H股募资;
    2024 年报披露 IFRS vs CAS 净利差异仅约 -58 万元(融德投资房产减值转回差异)
  - 2017 其他收益科目首年(政府补助,比较期不重述);2019 新金融工具准则(应收款项融资等,
    衔接法不重述比较期);2019 年报即列示使用权资产/租赁负债;2020 新收入准则(预收→合同负债)

口径:
  - 单位 = 人民币元(年报原始口径)
  - 资产/负债/权益 = 正数;利润表按财报印刷符号;现金流量表流出/减项 = 负数(标准格式源为正数,
    写出时对流出科目取负;PwC 源本身已是负数)
  - None = 该期财报无此科目(CSV 留空)
  - 2006 列 = 2007 年报追溯重述的 CAS2006 口径(2006 年报自身为旧准则,「主要会计数据」锚点
    与重述口径存在差异属预期: 归母 -674 万/总资产 -8,661 万,锚点检查对 2006 降级为警告)
"""
import csv
import itertools
import json
import os
import re
import sys

OUT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(OUT, "_extract_json")
ROOT = os.path.abspath(os.path.join(OUT, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

YEARS = list(range(2006, 2026))

# ── 来源映射: year → (json文件名, 列 0=本年 1=上年, era A/B/P)
SOURCES = {
    2006: ("fy2007", 1, "A"), 2007: ("fy2007", 0, "A"),
    2008: ("fy2009", 1, "A"), 2009: ("fy2009", 0, "A"),
    2010: ("fy2010", 0, "A"), 2011: ("fy2011_pwc", 0, "P"),
    2012: ("fy2013_pwc", 1, "P"), 2013: ("fy2013_pwc", 0, "P"),
    2014: ("fy2015", 1, "A"), 2015: ("fy2015", 0, "A"),
    2016: ("fy2017", 1, "A"), 2017: ("fy2017", 0, "A"),
    2018: ("fy2019", 1, "B"), 2019: ("fy2019", 0, "B"),
    2020: ("fy2021", 1, "B"), 2021: ("fy2021", 0, "B"),
    2022: ("fy2023", 1, "B"), 2023: ("fy2023", 0, "B"),
    2024: ("fy2025", 1, "B"), 2025: ("fy2025", 0, "B"),
}
# 双源交叉核验: year → (备源文件, 列, 参与核验的表)
CROSS_SRC = {
    2010: ("fy2011_pwc", 1, ("利润表", "资产负债表", "现金流量表")),
    2013: ("fy2014", 1, ("利润表", "现金流量表")),   # fy2014 BS=三栏调整数,不可比
    2014: ("fy2014", 0, ("利润表", "现金流量表")),
}
PWC_FILES = {"fy2011_pwc", "fy2013_pwc"}

# ── 标准科目表(顺序 = CSV 行序)
IS_ROWS = ["营业总收入", "营业收入", "营业总成本", "营业成本", "税金及附加", "销售费用",
           "管理费用", "研发费用", "财务费用", "利息费用", "利息收入", "其他收益", "投资收益",
           "其中:联营合营企业投资收益", "公允价值变动收益", "信用减值损失", "资产减值损失",
           "资产处置收益", "营业利润", "营业外收入", "营业外支出", "利润总额", "所得税费用",
           "净利润", "归母净利润", "少数股东损益", "综合收益总额", "归母综合收益总额",
           "基本每股收益(元/股)"]
BS_ROWS = ["货币资金", "交易性金融资产", "衍生金融资产", "应收票据", "应收账款", "应收款项融资",
           "预付款项", "应收利息", "应收股利", "其他应收款", "存货", "持有待售资产",
           "一年内到期的非流动资产", "其他流动资产", "流动资产合计", "可供出售金融资产",
           "长期应收款", "长期股权投资", "其他权益工具投资", "固定资产", "在建工程", "工程物资",
           "使用权资产", "无形资产", "开发支出", "商誉", "长期待摊费用", "递延所得税资产",
           "其他非流动资产", "非流动资产合计", "资产总计", "短期借款", "交易性金融负债",
           "衍生金融负债", "应付票据", "应付账款", "预收款项", "合同负债", "应付职工薪酬",
           "应交税费", "应付利息", "应付股利", "其他应付款", "持有待售负债",
           "一年内到期的非流动负债", "其他流动负债", "流动负债合计", "长期借款", "应付债券",
           "租赁负债", "长期应付款", "专项应付款", "预计负债", "递延收益", "递延所得税负债",
           "其他非流动负债", "非流动负债合计", "负债合计", "股本", "资本公积", "库存股",
           "其他综合收益", "专项储备", "盈余公积", "未分配利润", "归母权益合计", "少数股东权益",
           "所有者权益合计"]
CF_ROWS = ["销售商品、提供劳务收到的现金", "收到的税费返还", "收到其他与经营活动有关的现金",
           "经营活动现金流入小计", "购买商品、接受劳务支付的现金", "支付给职工及为职工支付的现金",
           "支付的各项税费", "支付其他与经营活动有关的现金", "经营活动现金流出小计",
           "经营活动产生的现金流量净额", "收回投资收到的现金", "取得投资收益收到的现金",
           "处置固定资产、无形资产等收回的现金净额", "处置子公司及其他营业单位收到的现金净额",
           "收到其他与投资活动有关的现金", "投资活动现金流入小计",
           "购建固定资产、无形资产等支付的现金", "投资支付的现金",
           "取得子公司及其他营业单位支付的现金净额", "支付其他与投资活动有关的现金",
           "投资活动现金流出小计", "投资活动产生的现金流量净额", "吸收投资收到的现金",
           "取得借款收到的现金", "发行债券收到的现金", "收到其他与筹资活动有关的现金",
           "筹资活动现金流入小计", "偿还债务支付的现金", "分配股利、利润或偿付利息支付的现金",
           "支付其他与筹资活动有关的现金", "筹资活动现金流出小计", "筹资活动产生的现金流量净额",
           "汇率变动对现金及现金等价物的影响", "现金及现金等价物净增加额",
           "期初现金及现金等价物余额", "期末现金及现金等价物余额"]
ALL_STD = set(IS_ROWS) | set(BS_ROWS) | set(CF_ROWS)

# ── 别名(std → 匹配后缀候选;匹配规则=草稿键规范化后以候选结尾,取最长命中)
ALIAS = {
    "营业总收入": ["营业总收入"],
    "营业收入": ["营业收入", "一营业收入"],
    "税金及附加": ["税金及附加", "营业税金及附加"],
    "财务费用": ["财务费用", "财务费用-净额"],
    "利息费用": ["其中利息费用"],
    "利息收入": ["利息收入"],
    "其他收益": ["加其他收益", "其他收益"],
    "投资收益": ["投资收益"],
    "其中:联营合营企业投资收益": ["对联营企业和合营企业的投资收益", "对合营企业的投资收益"],
    "公允价值变动收益": ["公允价值变动收益", "公允价值变动(损失)/收益", "公允价值变动收益/(损失)"],
    "信用减值损失": ["信用减值损失"],
    "资产减值损失": ["资产减值损失"],
    "资产处置收益": ["资产处置收益"],
    "营业利润": ["三营业利润", "二营业利润", "营业利润"],
    "营业外收入": ["营业外收入"],
    "营业外支出": ["营业外支出"],
    "利润总额": ["三利润总额", "四利润总额", "利润总额"],
    "所得税费用": ["所得税费用"],
    "净利润": ["五净利润", "四净利润"],
    "归母净利润": ["归属于母公司股东的净利润", "归属于母公司所有者的净利润"],
    "少数股东损益": ["少数股东损益"],
    "综合收益总额": ["综合收益总额", "七综合收益总额"],
    "归母综合收益总额": ["归属于母公司所有者的综合收益总额", "归属于母公司股东的综合收益总额"],
    "基本每股收益(元/股)": ["基本每股收益元/股", "基本每股收益人民币元", "基本每股收益"],
    # BS
    "交易性金融资产": ["交易性金融资产", "以公允价值计量且其变动计入当期损益的金融资产"],
    "衍生金融资产": ["衍生金融资产"],
    "应收款项融资": ["应收款项融资"],
    "应收利息": ["应收利息"],
    "应收股利": ["应收股利"],
    "一年内到期的非流动资产": ["一年内到期的非流动资产"],
    "持有待售资产": ["划分为持有待售的资产", "持有待售资产", "持有待售的资产"],
    "持有待售负债": ["划分为持有待售的负债", "持有待售负债", "持有待售的负债"],
    "可供出售金融资产": ["可供出售金融资产"],
    "长期应收款": ["长期应收款"],
    "其他权益工具投资": ["其他权益工具投资"],
    "工程物资": ["工程物资"],
    "使用权资产": ["使用权资产"],
    "开发支出": ["开发支出"],
    "交易性金融负债": ["交易性金融负债", "以公允价值计量且其变动计入当期损益的金融负债"],
    "衍生金融负债": ["衍生金融负债"],
    "应付利息": ["应付利息"],
    "应付股利": ["应付股利"],
    "专项应付款": ["专项应付款"],
    "预计负债": ["预计负债"],
    "递延收益": ["递延收益"],
    "股本": ["实收资本", "股东权益股本", "股本"],
    "库存股": ["减库存股", "库存股"],
    "其他综合收益": ["其他综合收益", "外币报表折算差额"],
    "专项储备": ["专项储备"],
    "一年内到期的非流动负债": ["一年内到期的非流动负债"],
    "归母权益合计": ["归属于母公司所有者权益合计", "归属于母公司股东权益合计"],
    "所有者权益合计": ["所有者权益合计", "股东权益合计"],
    # CF
    "支付给职工及为职工支付的现金": ["支付给职工及为职工支付的现金", "支付给职工以及为职工支付的现金"],
    "处置固定资产、无形资产等收回的现金净额": ["处置固定资产无形资产和其他长期资产收回的现金净额"],
    "购建固定资产、无形资产等支付的现金": ["购建固定资产无形资产和其他长期资产支付的现金"],
    "取得投资收益收到的现金": ["取得投资收益收到的现金", "取得投资收益所收到的现金"],
    "分配股利、利润或偿付利息支付的现金": ["分配股利利润或偿付利息支付的现金"],
    "经营活动产生的现金流量净额": ["经营活动产生的现金流量净额", "经营活动产生/使用的现金流量净额"],
    "投资活动产生的现金流量净额": ["投资活动产生的现金流量净额", "投资活动使用/产生的现金流量净额"],
    "筹资活动产生的现金流量净额": ["筹资活动产生的现金流量净额", "筹资活动使用的现金流量净额"],
    "现金及现金等价物净增加额": ["现金及现金等价物净增加额", "现金净增加/减少额"],
    "期初现金及现金等价物余额": ["期初现金及现金等价物余额", "年初现金及现金等价物余额", "年初现金余额"],
    "期末现金及现金等价物余额": ["期末现金及现金等价物余额", "年末现金及现金等价物余额", "年末现金余额"],
}

CF_OUTFLOW = {"购买商品、接受劳务支付的现金", "支付给职工及为职工支付的现金", "支付的各项税费",
              "支付其他与经营活动有关的现金", "经营活动现金流出小计",
              "购建固定资产、无形资产等支付的现金", "投资支付的现金",
              "取得子公司及其他营业单位支付的现金净额", "支付其他与投资活动有关的现金",
              "投资活动现金流出小计", "偿还债务支付的现金", "分配股利、利润或偿付利息支付的现金",
              "支付其他与筹资活动有关的现金", "筹资活动现金流出小计"}

# ── 人工覆盖(键损坏/跨行附注污染;值经小计恒等式/双源/准则事实验证;显式 None=该列确认无值)
OVERRIDES = {
    # 2011 年报 CF: 附注引用「附注五(51)、附注十四(6)」跨行,值挤到孤行「十四(6)(」/「十四(6)」
    (2011, "现金流量表", "经营活动产生的现金流量净额"): 1461998861.0,   # 流入-流出 ✓;主要会计数据锚点 ✓
    (2011, "现金流量表", "现金及现金等价物净增加额"): 653801647.0,      # 三净额合计 ✓;期初+净增=期末 ✓
    # 2013 年报 BS: 「附注五(10)、附注十四(3)」跨行,(3) 被误读为 -3,列序整体右移一位
    (2013, "资产负债表", "长期股权投资"): 130015622.0,                  # 原文四列第1列(2013合并) ✓
    (2012, "资产负债表", "长期股权投资"): 104267850.0,                  # 原文四列第2列(2012合并) ✓
    # 2017 其他收益(政府补助)首年科目,比较期不重述 → 2016 无值
    (2017, "利润表", "其他收益"): 188116808.0,                          # 营业利润恒等式 ✓
    (2016, "利润表", "其他收益"): None,
    # PwC 版式 EPS 行值与"不适用"文字粘连无法机器解析 → 取自利润表原文/主要会计数据页
    (2013, "利润表", "基本每股收益(元/股)"): 0.96,
    (2012, "利润表", "基本每股收益(元/股)"): 0.76,
    (2011, "利润表", "基本每股收益(元/股)"): 0.76,                      # 2011年报主要会计数据页
}

_SUFFIX_JUNK = re.compile(r"(附注[,，]?\d*|[一二三四五六七八九十]{1,3}[、.]?\(?\d*\)?|\(\d*\)?|\d+|[、,，(（)）])$")


def norm(s):
    s = s.replace("（", "(").replace("）", ")").replace("－", "-").replace("−", "-")
    s = re.sub(r"损失以.?[-—].?号填列|净亏损以.?[-—].?号填列|亏损以.?[-—].?号填列|亏损总额以.?[-—].?号填列", "", s)
    s = s.replace("(或股东权益)", "").replace("(或股本)", "")
    s = re.sub(r"[\s：:、，,。．\"'()（）]", "", s)
    s = re.sub(r"^-?\d+-", "", s)  # 页脚 -37- 前缀
    # 反复剥离尾部附注引用/编号垃圾(不动以汉字结尾的正常科目名)
    while True:
        new = _SUFFIX_JUNK.sub("", s)
        if new == s:
            break
        s = new
    return s


DATA = {}
for name in {v[0] for v in SOURCES.values()} | {v[0] for v in CROSS_SRC.values()}:
    with open(os.path.join(SRC, name + ".json"), encoding="utf-8") as f:
        DATA[name] = json.load(f)
with open(os.path.join(SRC, "main_anchors.json"), encoding="utf-8") as f:
    ANCHORS = {int(k): v for k, v in json.load(f).items()}

# 预规范化草稿键 + 每键归属唯一标准科目(全局最长后缀优先)
NORM_ALIAS = []  # (norm_alias, std) 按长度降序
for std in ALL_STD:
    for cand in ALIAS.get(std, [std]):
        NORM_ALIAS.append((norm(cand), std))
NORM_ALIAS.sort(key=lambda x: -len(x[0]))


def classify_key(nk):
    for na, std in NORM_ALIAS:
        if na and (nk == na or nk.endswith(na)):
            return std
    # 反向后缀: 草稿键是标准名的截断尾(跨页断名),要求足够长且唯一
    if len(nk) >= 8:
        hits = {std for na, std in NORM_ALIAS if len(na) > len(nk) and na.endswith(nk)}
        if len(hits) == 1:
            return hits.pop()
    return None


LOOKUP = {}  # (fname, table, std) → vals list
for fname, tables in DATA.items():
    if fname == "main_anchors":
        continue
    for table, rows in tables.items():
        if table not in ("利润表", "资产负债表", "现金流量表"):
            continue
        for key, vals in rows.items():
            std = classify_key(norm(key))
            if std is None or not isinstance(vals, list):
                continue
            k = (fname, table, std)
            if k in LOOKUP:
                continue  # 首见优先(续表重复)
            LOOKUP[k] = vals


def raw_lookup(fname, table, std, col):
    vals = LOOKUP.get((fname, table, std))
    if vals is None:
        return None
    if len(vals) >= 1 and vals[0] == "AMBIG":
        return ("AMBIG", vals[1] if len(vals) > 1 else None)
    v = vals[col] if col < len(vals) else None
    return v


def value_for(table, std, year):
    if (year, table, std) in OVERRIDES:
        return OVERRIDES[(year, table, std)]
    fname, col, _ = SOURCES[year]
    return raw_lookup(fname, table, std, col)


RAW = {"利润表": {}, "资产负债表": {}, "现金流量表": {}}
for table, rows in [("利润表", IS_ROWS), ("资产负债表", BS_ROWS), ("现金流量表", CF_ROWS)]:
    for std in rows:
        RAW[table][std] = [value_for(table, std, y) for y in YEARS]


# ── CF 符号规范化(先于 AMBIG 消解): 标准格式源的流出科目取负
for std in CF_ROWS:
    if std not in CF_OUTFLOW:
        continue
    for i, y in enumerate(YEARS):
        fname = SOURCES[y][0]
        v = RAW["现金流量表"][std][i]
        if isinstance(v, tuple) or v is None:
            continue
        if fname not in PWC_FILES and v > 0:
            RAW["现金流量表"][std][i] = -v


def g(table, std, i):
    v = RAW[table][std][i]
    return None if isinstance(v, tuple) else v


def sec_sum(table, comps, i):
    vals = [g(table, c, i) for c in comps]
    present = [v for v in vals if v is not None]
    return sum(present) if present else None


CF_IN_OP = ["销售商品、提供劳务收到的现金", "收到的税费返还", "收到其他与经营活动有关的现金"]
CF_OUT_OP = ["购买商品、接受劳务支付的现金", "支付给职工及为职工支付的现金", "支付的各项税费",
             "支付其他与经营活动有关的现金"]
CF_IN_INV = ["收回投资收到的现金", "取得投资收益收到的现金", "处置固定资产、无形资产等收回的现金净额",
             "处置子公司及其他营业单位收到的现金净额", "收到其他与投资活动有关的现金"]
CF_OUT_INV = ["购建固定资产、无形资产等支付的现金", "投资支付的现金",
              "取得子公司及其他营业单位支付的现金净额", "支付其他与投资活动有关的现金"]
CF_IN_FIN = ["吸收投资收到的现金", "取得借款收到的现金", "发行债券收到的现金",
             "收到其他与筹资活动有关的现金"]
CF_OUT_FIN = ["偿还债务支付的现金", "分配股利、利润或偿付利息支付的现金", "支付其他与筹资活动有关的现金"]
BS_CA = ["货币资金", "交易性金融资产", "衍生金融资产", "应收票据", "应收账款", "应收款项融资",
         "预付款项", "应收利息", "应收股利", "其他应收款", "存货", "持有待售资产",
         "一年内到期的非流动资产", "其他流动资产"]
BS_NCA = ["可供出售金融资产", "长期应收款", "长期股权投资", "其他权益工具投资", "固定资产",
          "在建工程", "工程物资", "使用权资产", "无形资产", "开发支出", "商誉", "长期待摊费用",
          "递延所得税资产", "其他非流动资产"]
BS_CL = ["短期借款", "交易性金融负债", "衍生金融负债", "应付票据", "应付账款", "预收款项",
         "合同负债", "应付职工薪酬", "应交税费", "应付利息", "应付股利", "其他应付款",
         "持有待售负债", "一年内到期的非流动负债", "其他流动负债"]
BS_NCL = ["长期借款", "应付债券", "租赁负债", "长期应付款", "专项应付款", "预计负债", "递延收益",
          "递延所得税负债", "其他非流动负债"]
BS_EQ = ["股本", "资本公积", "库存股", "其他综合收益", "专项储备", "盈余公积", "未分配利润"]

SECTIONS = [("现金流量表", CF_IN_OP, "经营活动现金流入小计"), ("现金流量表", CF_OUT_OP, "经营活动现金流出小计"),
            ("现金流量表", CF_IN_INV, "投资活动现金流入小计"), ("现金流量表", CF_OUT_INV, "投资活动现金流出小计"),
            ("现金流量表", CF_IN_FIN, "筹资活动现金流入小计"), ("现金流量表", CF_OUT_FIN, "筹资活动现金流出小计"),
            ("资产负债表", BS_CA, "流动资产合计"), ("资产负债表", BS_NCA, "非流动资产合计"),
            ("资产负债表", BS_CL, "流动负债合计"), ("资产负债表", BS_NCL, "非流动负债合计")]


def resolve_ambig():
    """单值行消解: 值必属 本年/上年 之一。按 (源文件, 所属小计节) 分组做子集分配 ——
    每列缺口 = 合计 − 已知项和;枚举 2^n 种列归属,唯一同时闭合两列缺口的组合胜出。
    汇率变动用「三净额+汇率=净增额」恒等式单独判。"""
    print("== AMBIG 消解 ==")
    pending = {}
    for table, rows in [("利润表", IS_ROWS), ("资产负债表", BS_ROWS), ("现金流量表", CF_ROWS)]:
        for std in rows:
            for i, y in enumerate(YEARS):
                v = RAW[table][std][i]
                if isinstance(v, tuple):
                    fname, col, _ = SOURCES[y]
                    val = v[1]
                    if val is not None and table == "现金流量表" and std in CF_OUTFLOW \
                            and fname not in PWC_FILES and val > 0:
                        val = -val
                    pending.setdefault((fname, table, std), {"val": val, "years": {}})
                    pending[(fname, table, std)]["years"][col] = i
    unresolved = dict(pending)

    def place(fname, table, std, chosen_col):
        info = unresolved.pop((fname, table, std))
        for col, i in info["years"].items():
            RAW[table][std][i] = info["val"] if col == chosen_col else None
        tag = YEARS[info["years"][chosen_col]] if chosen_col in info["years"] else "空(两列皆非)"
        print(f"  ✓ {std}@{fname}: {info['val']:,.0f} → {tag}")

    for _ in range(6):
        progressed = False
        # 按 (fname, 小计节) 分组
        groups = {}
        for (fname, table, std), info in unresolved.items():
            sec = next(((comps, total) for t, comps, total in SECTIONS if t == table and std in comps), None)
            if sec:
                groups.setdefault((fname, table, sec[1]), []).append((std, info, sec[0]))
        for (fname, table, total), members in groups.items():
            comps = members[0][2]
            # 该组涉及的年份集合(同文件两列)
            cols_years = {}
            for std, info, _ in members:
                for col, i in info["years"].items():
                    cols_years[col] = i
            if not cols_years:
                continue
            gaps = {}
            usable = True
            for col, i in cols_years.items():
                tot = g(table, total, i)
                known = sec_sum(table, [c for c in comps if c not in {m[0] for m in members}], i)
                if tot is None:
                    usable = False
                    break
                gaps[col] = tot - (known or 0)
            if not usable:
                continue
            # 枚举归属
            names = [m[0] for m in members]
            vals = {m[0]: m[1]["val"] for m in members}
            all_cols = sorted(cols_years)
            solutions = []
            for combo in itertools.product(all_cols, repeat=len(names)):
                sums = {c: 0.0 for c in all_cols}
                for nme, c in zip(names, combo):
                    sums[c] += vals[nme]
                if all(abs(sums[c] - gaps[c]) <= 2 for c in all_cols):
                    solutions.append(combo)
            if len(solutions) == 1:
                for nme, c in zip(names, solutions[0]):
                    place(fname, table, nme, c)
                progressed = True
        # 汇率变动特判
        for (fname, table, std), info in list(unresolved.items()):
            if std != "汇率变动对现金及现金等价物的影响":
                continue
            v = info["val"]
            oks = []
            for col, i in info["years"].items():
                net = g(table, "现金及现金等价物净增加额", i)
                three = sum(x for x in [g(table, "经营活动产生的现金流量净额", i),
                                        g(table, "投资活动产生的现金流量净额", i),
                                        g(table, "筹资活动产生的现金流量净额", i)] if x is not None)
                if net is None:
                    continue
                if abs(three + v - net) <= 2:
                    oks.append(col)
            if len(oks) == 1:
                place(fname, table, std, oks[0])
                progressed = True
        if not progressed:
            break
    for (fname, table, std), info in unresolved.items():
        for col, i in info["years"].items():
            RAW[table][std][i] = None
        print(f"  ✗ 未消解(置空,需人工): {fname} {table} {std} 候选={info['val']:,}")
    return len(unresolved)


UNRESOLVED_N = resolve_ambig()

# ── 勾稽校验
ERR, WARN = [], []


def ck(y, label, lhs, rhs, tol=2.0, warn_only=False):
    if lhs is None or rhs is None:
        return
    if abs(lhs - rhs) > tol:
        (WARN if warn_only else ERR).append(f"[{y}] {label}: {lhs:,.2f} vs {rhs:,.2f} (差 {lhs-rhs:,.2f})")


def rev(i):
    return g("利润表", "营业收入", i) if g("利润表", "营业收入", i) is not None else g("利润表", "营业总收入", i)


def check_year(i, y):
    era = SOURCES[y][2]
    G = lambda t, s: g(t, s, i)
    # —— 利润表
    if era in ("A", "B"):
        parts = ["营业成本", "税金及附加", "销售费用", "管理费用", "研发费用", "财务费用"]
        if era == "A":
            parts.append("资产减值损失")
        ck(y, "营业总成本构成", sec_sum("利润表", parts, i), G("利润表", "营业总成本"))
        adds = ["其他收益", "投资收益", "公允价值变动收益", "资产处置收益"]
        if era == "B":
            adds += ["信用减值损失", "资产减值损失"]
        lhs = (G("利润表", "营业总收入") or 0) - (G("利润表", "营业总成本") or 0) + (sec_sum("利润表", adds, i) or 0)
        ck(y, "营业利润", lhs, G("利润表", "营业利润"))
    else:  # PwC
        parts = ["营业成本", "税金及附加", "销售费用", "管理费用", "财务费用", "资产减值损失"]
        lhs = (rev(i) or 0) - (sec_sum("利润表", parts, i) or 0) \
            + (G("利润表", "公允价值变动收益") or 0) + (G("利润表", "投资收益") or 0)
        ck(y, "营业利润(PwC)", lhs, G("利润表", "营业利润"))
    ck(y, "利润总额", (G("利润表", "营业利润") or 0) + (G("利润表", "营业外收入") or 0) - (G("利润表", "营业外支出") or 0),
       G("利润表", "利润总额"))
    ck(y, "净利润", (G("利润表", "利润总额") or 0) - (G("利润表", "所得税费用") or 0), G("利润表", "净利润"))
    ck(y, "归母+少数", (G("利润表", "归母净利润") or 0) + (G("利润表", "少数股东损益") or 0), G("利润表", "净利润"))
    # —— 资产负债表
    ck(y, "流动资产合计", sec_sum("资产负债表", BS_CA, i), G("资产负债表", "流动资产合计"))
    ck(y, "非流动资产合计", sec_sum("资产负债表", BS_NCA, i), G("资产负债表", "非流动资产合计"))
    ck(y, "资产总计", (G("资产负债表", "流动资产合计") or 0) + (G("资产负债表", "非流动资产合计") or 0),
       G("资产负债表", "资产总计"))
    ck(y, "流动负债合计", sec_sum("资产负债表", BS_CL, i), G("资产负债表", "流动负债合计"))
    ck(y, "非流动负债合计", sec_sum("资产负债表", BS_NCL, i), G("资产负债表", "非流动负债合计"))
    ck(y, "负债合计", (G("资产负债表", "流动负债合计") or 0) + (G("资产负债表", "非流动负债合计") or 0),
       G("资产负债表", "负债合计"))
    eq = sec_sum("资产负债表", BS_EQ, i)
    if eq is not None and G("资产负债表", "库存股"):
        eq -= 2 * G("资产负债表", "库存股")
    ck(y, "归母权益构成", eq, G("资产负债表", "归母权益合计"))
    ck(y, "权益合计", (G("资产负债表", "归母权益合计") or 0) + (G("资产负债表", "少数股东权益") or 0),
       G("资产负债表", "所有者权益合计"))
    ck(y, "资产=负债+权益", G("资产负债表", "资产总计"),
       (G("资产负债表", "负债合计") or 0) + (G("资产负债表", "所有者权益合计") or 0))
    # —— 现金流量表
    for comps, total in [(CF_IN_OP, "经营活动现金流入小计"), (CF_OUT_OP, "经营活动现金流出小计"),
                         (CF_IN_INV, "投资活动现金流入小计"), (CF_OUT_INV, "投资活动现金流出小计"),
                         (CF_IN_FIN, "筹资活动现金流入小计"), (CF_OUT_FIN, "筹资活动现金流出小计")]:
        ck(y, total + "构成", sec_sum("现金流量表", comps, i), G("现金流量表", total))
    ck(y, "经营净额", (G("现金流量表", "经营活动现金流入小计") or 0) + (G("现金流量表", "经营活动现金流出小计") or 0),
       G("现金流量表", "经营活动产生的现金流量净额"))
    ck(y, "投资净额", (G("现金流量表", "投资活动现金流入小计") or 0) + (G("现金流量表", "投资活动现金流出小计") or 0),
       G("现金流量表", "投资活动产生的现金流量净额"))
    ck(y, "筹资净额", (G("现金流量表", "筹资活动现金流入小计") or 0) + (G("现金流量表", "筹资活动现金流出小计") or 0),
       G("现金流量表", "筹资活动产生的现金流量净额"))
    ck(y, "现金净增加", (G("现金流量表", "经营活动产生的现金流量净额") or 0)
       + (G("现金流量表", "投资活动产生的现金流量净额") or 0)
       + (G("现金流量表", "筹资活动产生的现金流量净额") or 0)
       + (G("现金流量表", "汇率变动对现金及现金等价物的影响") or 0),
       G("现金流量表", "现金及现金等价物净增加额"))
    ck(y, "期初+净增=期末", (G("现金流量表", "期初现金及现金等价物余额") or 0)
       + (G("现金流量表", "现金及现金等价物净增加额") or 0), G("现金流量表", "期末现金及现金等价物余额"))
    if i + 1 < len(YEARS):
        ck(y, f"期末现金={y+1}期初", g("现金流量表", "期末现金及现金等价物余额", i),
           g("现金流量表", "期初现金及现金等价物余额", i + 1))
    # —— 锚点(该年自家年报「主要会计数据」;2006 锚点=旧准则,降级警告)
    a = ANCHORS.get(y, {})
    warn_only = (y == 2006)
    amap = [("营业收入", None, None), ("归母净利润", "利润表", "归母净利润"),
            ("经营现金流净额", "现金流量表", "经营活动产生的现金流量净额"),
            ("总资产", "资产负债表", "资产总计"), ("归母净资产", "资产负债表", "归母权益合计")]
    for ak, t, s in amap:
        if ak not in a:
            continue
        mine = rev(i) if t is None else g(t, s, i)
        ck(y, f"锚点·{ak}", a[ak][0], mine, tol=2.0, warn_only=warn_only)


def cross_check():
    print("\n== 双源交叉核验 ==")
    KEY = [("利润表", "营业收入"), ("利润表", "净利润"), ("利润表", "归母净利润"),
           ("资产负债表", "资产总计"), ("资产负债表", "归母权益合计"), ("资产负债表", "存货"),
           ("资产负债表", "固定资产"), ("现金流量表", "经营活动产生的现金流量净额"),
           ("现金流量表", "期末现金及现金等价物余额")]
    for y, (fname, col, tables) in CROSS_SRC.items():
        i = YEARS.index(y)
        diffs = []
        for t, s in KEY:
            if t not in tables:
                continue
            adopted = g(t, s, i)
            alt = raw_lookup(fname, t, s, col)
            if isinstance(alt, tuple):
                alt = None
            if adopted is not None and alt is not None:
                if t == "现金流量表" and s in CF_OUTFLOW and fname not in PWC_FILES and alt > 0:
                    alt = -alt
                if abs(adopted - alt) > 2:
                    diffs.append(f"{s}: 采用{adopted:,.0f} vs 备源{alt:,.0f}")
        print(f"  {y} vs {fname}[{'本年' if col == 0 else '上年'}]{tables}: "
              + ("✅一致" if not diffs else "⚠️ " + "; ".join(diffs)))


# ── 派生比率
def pct(a, b):
    return round(a / b * 100, 2) if (a is not None and b) else None


def build_ratios():
    R = []
    idx = range(len(YEARS))
    IS, BS, CF = "利润表", "资产负债表", "现金流量表"

    def row(name, fn):
        R.append((name, [fn(i) for i in idx]))

    扣非 = [ANCHORS.get(y, {}).get("扣非归母", [None])[0] for y in YEARS]
    row("毛利率(%)", lambda i: pct((rev(i) or 0) - abs(g(IS, "营业成本", i) or 0), rev(i)))
    row("净利率(%)", lambda i: pct(g(IS, "净利润", i), rev(i)))
    row("归母净利率(%)", lambda i: pct(g(IS, "归母净利润", i), rev(i)))
    row("ROE(归母÷期末归母权益,%)", lambda i: pct(g(IS, "归母净利润", i), g(BS, "归母权益合计", i)))
    row("销售费用率(%)", lambda i: pct(g(IS, "销售费用", i), rev(i)))
    row("管理费用率(%)", lambda i: pct(g(IS, "管理费用", i), rev(i)))
    row("研发费用率(%)", lambda i: pct(g(IS, "研发费用", i), rev(i)))
    row("经营现金流/净利润(现金含量)", lambda i: round(g(CF, "经营活动产生的现金流量净额", i) / g(IS, "净利润", i), 3)
        if (g(CF, "经营活动产生的现金流量净额", i) is not None and g(IS, "净利润", i)) else None)
    row("销售收现/营收", lambda i: round(g(CF, "销售商品、提供劳务收到的现金", i) / rev(i), 3)
        if (g(CF, "销售商品、提供劳务收到的现金", i) is not None and rev(i)) else None)
    row("capex/净利润(%)", lambda i: pct(abs(g(CF, "购建固定资产、无形资产等支付的现金", i) or 0), g(IS, "净利润", i)))
    row("capex/经营现金流净额(%)", lambda i: pct(abs(g(CF, "购建固定资产、无形资产等支付的现金", i) or 0),
                                     g(CF, "经营活动产生的现金流量净额", i)))
    row("自由现金流(经营净额-capex,元)", lambda i: (g(CF, "经营活动产生的现金流量净额", i) or 0)
        - abs(g(CF, "购建固定资产、无形资产等支付的现金", i) or 0)
        if g(CF, "经营活动产生的现金流量净额", i) is not None else None)
    row("应收账款/营收(%)", lambda i: pct(g(BS, "应收账款", i), rev(i)))
    row("(应收账款+应收票据+应收款项融资)/营收(%)", lambda i: pct(
        (g(BS, "应收账款", i) or 0) + (g(BS, "应收票据", i) or 0) + (g(BS, "应收款项融资", i) or 0), rev(i)))
    row("资产负债率(%)", lambda i: pct(g(BS, "负债合计", i), g(BS, "资产总计", i)))
    row("有息负债(短借+一年内+长借+应付债券,元)", lambda i: sec_sum(BS, ["短期借款", "一年内到期的非流动负债",
                                                       "长期借款", "应付债券"], i))
    row("货币资金/总资产(%)", lambda i: pct(g(BS, "货币资金", i), g(BS, "资产总计", i)))
    row("固定资产+在建/总资产(%)", lambda i: pct((g(BS, "固定资产", i) or 0) + (g(BS, "在建工程", i) or 0),
                                      g(BS, "资产总计", i)))
    row("存货/总资产(%)", lambda i: pct(g(BS, "存货", i), g(BS, "资产总计", i)))
    row("存货周转天数", lambda i: round(365 * g(BS, "存货", i) / abs(g(IS, "营业成本", i)), 1)
        if (g(BS, "存货", i) is not None and g(IS, "营业成本", i)) else None)
    row("应收账款周转天数", lambda i: round(365 * (g(BS, "应收账款", i) or 0) / rev(i), 1) if rev(i) else None)
    row("应付账款周转天数", lambda i: round(365 * (g(BS, "应付账款", i) or 0) / abs(g(IS, "营业成本", i)), 1)
        if g(IS, "营业成本", i) else None)
    row("归母/净利润(%·少数股东leak)", lambda i: pct(g(IS, "归母净利润", i), g(IS, "净利润", i)))
    R.append(("扣非归母净利润(元·摘要披露)", 扣非))
    R.append(("扣非/归母(%·非经常leak)", [
        round(扣非[i] / g("利润表", "归母净利润", i) * 100, 2)
        if (扣非[i] is not None and g("利润表", "归母净利润", i)) else None for i in idx]))
    row("分配股利利润偿息/归母(%·含息近似)", lambda i: pct(abs(g(CF, "分配股利、利润或偿付利息支付的现金", i) or 0),
                                        g(IS, "归母净利润", i)))
    # 通用底补漏 ← scripts/derived.py
    try:
        import derived
        common, _ = derived.compute_common_ratios(dict(RAW["利润表"].items()), dict(RAW["资产负债表"].items()),
                                                  dict(RAW["现金流量表"].items()))
        cd = {name: (vals, fmt) for name, vals, fmt in common}

        def conv(vals, fmt):
            if fmt == "pct":
                return [round(v * 100, 2) if v is not None else None for v in vals]
            if fmt == "day":
                return [round(v, 1) if v is not None else None for v in vals]
            return [round(v, 2) if v is not None else None for v in vals]

        for src, out_label in [("ROE(年均) Return on avg equity", "ROE(归母÷年均归母权益,%)"),
                               ("(应收+预付)/总资产 Receivables&prepay/TA", "(应收+预付)/总资产(%)")]:
            if src in cd:
                vals, fmt = cd[src]
                R.append((out_label, conv(vals, fmt)))
    except Exception as e:
        print(f"  (derived.py 通用底跳过: {e})")
    return R


def write_csv(rows, filename):
    path = os.path.join(OUT, filename)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["科目"] + [str(y) for y in YEARS])
        for k, vs in rows:
            w.writerow([k] + ["" if (v is None or isinstance(v, tuple)) else v for v in vs])
    print(f"  ✅ {filename} ({len(rows)} 行 × {len(YEARS)} 年)")


def main():
    for i, y in enumerate(YEARS):
        check_year(i, y)
    if WARN:
        print("\n⚠️ 警告(不阻断):")
        for w in WARN:
            print("   " + w)
    if ERR:
        print(f"\n❌ 勾稽校验未通过({len(ERR)} 条),不写出 CSV:")
        for e in ERR:
            print("   " + e)
        sys.exit(1)
    if UNRESOLVED_N:
        print(f"\n❌ 存在 {UNRESOLVED_N} 个未消解 AMBIG,不写出 CSV")
        sys.exit(1)
    print(f"\n✅ 勾稽校验全部通过({len(YEARS)} 年 × ~24 项/年)")
    is_rows = [(k, RAW["利润表"][k]) for k in IS_ROWS]
    is_rows.append(("扣非归母净利润(摘要披露)", [ANCHORS.get(y, {}).get("扣非归母", [None])[0] for y in YEARS]))
    write_csv(is_rows, "利润表.csv")
    write_csv([(k, RAW["资产负债表"][k]) for k in BS_ROWS], "资产负债表.csv")
    write_csv([(k, RAW["现金流量表"][k]) for k in CF_ROWS], "现金流量表.csv")
    write_csv(build_ratios(), "财务比率.csv")
    cross_check()


if __name__ == "__main__":
    main()
