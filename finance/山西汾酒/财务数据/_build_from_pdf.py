# -*- coding: utf-8 -*-
"""山西汾酒(600809) 三表 + 派生比率 → 写 CSV，内置勾稽自洽校验（校验不过不写出）。

数据血缘（2006-2025 · 20 年 · 全部 CAS2006 体系·重述口径）：
  主数据源 = 奇数年年报(2007/09/11/13/15/17/19/21/23/25)的「本年列 + 上年比较列」，
  每份年报出 2 年（本年=奇数年；上年=偶数年·取次年年报上年比较列=重述口径），
  10 份年报接续覆盖 2006-2025 全部 20 年。逐年提取 JSON 在 _extract_json/（从一手年报 PDF 文本层逐行提取）。

  为什么偶数年用「次年年报上年比较列」而非该年年报本年列：保证跨年口径一致（重述后口径）。
  已用「偶数年该年年报本年列」交叉核验（cross_check()），已知口径断点：
    - 2006：老准则《企业会计制度》→ 2007 年报按 CAS2006 追溯重述，本库采用重述口径
    - 2016：全面营改增（2016-05）→ 若 2017 年报重述则采用重述口径
    - 2018：2019 年同一控制下企业合并（收购汾酒集团酒类资产）→ 2019 年报追溯重述 2018，
            本库 2018 采用重述口径（与 2019+ 合并范围可比），原始披露值以 cross_check 留痕

口径：
  - 单位 = 人民币元（年报原始口径），精确到分
  - 资产负债/利润科目按报表原印符号；现金流量表各流入/流出行 = 报表原印正数，
    各「净额」「净增加额」行带实际符号
  - None/空 = 该期报表无此科目
  - 财务比率中 capex/净利润、分红率等取正数口径（流出金额绝对值 ÷ 分母）

校验（每年，全覆盖）：
  ① 损益：营业总成本 = 成本+税金+三费(+老准则期间的资产减值损失)；
          营业利润 = 营业总收入 − 营业总成本 + 各加项（自动识别减值损失新旧列报）；
          利润总额 = 营业利润 + 营业外收支；净利润 = 利润总额 − 所得税；归母+少数 = 净利润
  ② 资产负债（按 JSON 键序分桶）：流动资产合计=分项和；非流动资产合计=分项和；
          资产总计=流动+非流动；流动负债合计=分项和；非流动负债合计=分项和；
          负债合计=流动+非流动；归母权益=权益分项和(库存股为减项)；资产=负债+权益
  ③ 现金流（按键序分桶）：各流入/流出小计=分项和；各净额=流入−流出；
          经营+投资+筹资+汇率=净增加额；期初+净增=期末
"""
import csv
import json
import os
import re
import sys

YEARS = list(range(2006, 2026))
OUT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(OUT, "_extract_json")

TABLES = ["利润表", "资产负债表", "现金流量表"]
TOL = 1.0  # 元级容差（报表印到分，勾稽应分毫平）
TOL_LOOSE = 150.0  # 个别年份报表自身尾差


def to_num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return None


# 列表前缀两种形态：①「一、」「1.」「其中：」等标记+分隔符 ②「(一)」「(1)」括号标记（分隔符可无）
_PREFIX = re.compile(r"^(?:[(（](?:其中|加|减|[一二三四五六七八九十0-9]+)[)）]|(?:其中|加|减|其中之|[一二三四五六七八九十0-9]+)[、:：.．])")


def norm(s):
    s = s.replace(" ", "").replace("（", "(").replace("）", ")").replace("，", "")
    while True:  # 剥「一、」「其中：」「加：」等列表前缀（可叠加）
        m = _PREFIX.match(s)
        if not m:
            break
        s = s[m.end():]
    s = s.replace("、", "")
    s = re.sub(r"\([^()]*填列[^()]*\)", "", s)  # 剥「(净亏损以"－"号填列)」类注释后缀
    s = re.sub(r"\(元/股\)", "", s)
    s = s.replace("和其他长期资产", "等")  # 购建固定资产、无形资产和其他长期资产 → 等
    s = s.replace("(或股本)", "").replace("(或股东权益)", "")  # 实收资本(或股本)/所有者权益(或股东权益)
    s = s.replace("实收资本", "股本")
    return s


def load_raw(year):
    p = os.path.join(SRC, f"fenjiu_extract_{year}.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def flatten(fd):
    """统一为 {table: {科目: {"本年":x,"上年":y}}}（保持键序）"""
    out = {}
    for table in TABLES:
        out[table] = {}
        raw = fd.get(table, {}) or {}
        for subj, val in raw.items():
            if isinstance(val, dict):
                out[table][subj] = {"本年": to_num(val.get("本年")), "上年": to_num(val.get("上年"))}
            elif isinstance(val, list):
                out[table][subj] = {"本年": to_num(val[0]), "上年": to_num(val[1]) if len(val) > 1 else None}
            else:
                out[table][subj] = {"本年": to_num(val), "上年": None}
    # 主要会计数据（扣非）
    kf = (fd.get("主要会计数据") or {}).get("扣非归母净利润")
    if isinstance(kf, dict):
        out["扣非归母净利润"] = {"本年": to_num(kf.get("本年")), "上年": to_num(kf.get("上年"))}
    else:
        out["扣非归母净利润"] = {"本年": None, "上年": None}
    return out


RAWS = {y: load_raw(y) for y in YEARS}
FLATS = {y: flatten(RAWS[y]) for y in YEARS}

# ── 标准科目表（CSV 行序·并集） ─────────────────────────────────────────
IS = ["营业总收入", "营业收入", "营业总成本", "营业成本", "税金及附加", "销售费用", "管理费用",
      "研发费用", "财务费用", "利息费用", "利息收入", "资产减值损失", "信用减值损失", "其他收益",
      "投资收益", "公允价值变动收益", "资产处置收益", "营业利润", "营业外收入", "营业外支出",
      "利润总额", "所得税费用", "净利润", "归母净利润", "少数股东损益", "扣非归母净利润",
      "基本每股收益", "稀释每股收益"]
BS = ["货币资金", "交易性金融资产", "应收票据", "应收账款", "应收款项融资", "预付款项",
      "应收利息", "其他应收款", "存货", "一年内到期的非流动资产", "其他流动资产", "流动资产合计",
      "可供出售金融资产", "长期股权投资", "其他权益工具投资", "其他非流动金融资产", "投资性房地产",
      "固定资产", "在建工程", "工程物资", "使用权资产", "无形资产", "商誉", "长期待摊费用",
      "递延所得税资产", "其他非流动资产", "非流动资产合计", "资产总计",
      "短期借款", "应付票据", "应付账款", "预收款项", "合同负债", "应付职工薪酬", "应交税费",
      "应付利息", "应付股利", "其他应付款", "一年内到期的非流动负债", "其他流动负债", "流动负债合计",
      "长期借款", "应付债券", "租赁负债", "长期应付款", "预计负债", "递延收益", "递延所得税负债",
      "其他非流动负债", "非流动负债合计", "负债合计",
      "股本", "资本公积", "减:库存股", "其他综合收益", "专项储备", "盈余公积", "一般风险准备",
      "未分配利润", "归母权益合计", "少数股东权益", "所有者权益合计"]
CF = ["销售商品、提供劳务收到的现金", "收到的税费返还", "收到其他与经营活动有关的现金",
      "经营活动现金流入小计", "购买商品、接受劳务支付的现金", "支付给职工及为职工支付的现金",
      "支付的各项税费", "支付其他与经营活动有关的现金", "经营活动现金流出小计",
      "经营活动产生的现金流量净额",
      "收回投资收到的现金", "取得投资收益收到的现金", "处置固定资产、无形资产等收回的现金净额",
      "收到其他与投资活动有关的现金", "投资活动现金流入小计",
      "购建固定资产、无形资产等支付的现金", "投资支付的现金", "取得子公司收到/支付的现金净额",
      "支付其他与投资活动有关的现金", "投资活动现金流出小计", "投资活动产生的现金流量净额",
      "吸收投资收到的现金", "取得借款收到的现金", "收到其他与筹资活动有关的现金",
      "筹资活动现金流入小计", "偿还债务支付的现金", "分配股利、利润或偿付利息支付的现金",
      "支付其他与筹资活动有关的现金", "筹资活动现金流出小计", "筹资活动产生的现金流量净额",
      "汇率变动对现金及现金等价物的影响", "现金及现金等价物净增加额",
      "期初现金及现金等价物余额", "期末现金及现金等价物余额"]

ALIAS = {
    "税金及附加": ["营业税金及附加"],
    "归母净利润": ["归属于母公司所有者的净利润", "归属于母公司股东的净利润", "归属于上市公司股东的净利润"],
    "归母权益合计": ["归属于母公司所有者权益合计", "归属于母公司股东权益合计", "归属于母公司所有者权益(或股东权益)合计",
               "所有者权益(或股东权益)合计中归属于母公司部分"],
    "所有者权益合计": ["所有者权益(或股东权益)合计", "股东权益合计"],
    "减:库存股": ["库存股", "减库存股"],
    "处置固定资产、无形资产等收回的现金净额": ["处置固定资产、无形资产和其他长期资产收回的现金净额",
                              "处置固定资产、无形资产和其他长期资产所收回的现金净额"],
    "购建固定资产、无形资产等支付的现金": ["购建固定资产、无形资产和其他长期资产支付的现金",
                             "购建固定资产、无形资产和其他长期资产所支付的现金"],
    "取得子公司收到/支付的现金净额": ["取得子公司及其他营业单位支付的现金净额",
                          "处置子公司及其他营业单位收到的现金净额"],
    "现金及现金等价物净增加额": ["五、现金及现金等价物净增加额"],
    "资产处置收益": ["资产处置收益(损失以\"-\"号填列)"],
    "扣非归母净利润": ["归属于上市公司股东的扣除非经常性损益的净利润"],
    "营业收入": ["其中:营业收入", "主营业务收入"],
    "营业成本": ["其中:营业成本", "主营业务成本"],
}


def lookup(fd_table, std_subj):
    cands = [std_subj] + ALIAS.get(std_subj, [])
    for cand in cands:
        nc = norm(cand)
        for k, v in fd_table.items():
            if norm(k) == nc:
                return v
    return None


def value_for_year(table, std_subj, year):
    """重述口径：奇数年取该年报本年列；偶数年取次年(奇数)年报上年比较列。"""
    if std_subj == "扣非归母净利润":
        if year % 2 == 1:
            return FLATS[year]["扣非归母净利润"]["本年"]
        src = FLATS.get(year + 1)
        return src["扣非归母净利润"]["上年"] if src else None
    if year % 2 == 1:
        fd, period = FLATS.get(year), "本年"
    else:
        fd, period = FLATS.get(year + 1), "上年"
    if fd is None:
        return None
    v = lookup(fd[table], std_subj)
    return v.get(period) if v else None


def build_table(std_list, table_name):
    rows = []
    for s in std_list:
        if s == "扣非归母净利润":
            rows.append((s, [value_for_year("利润表", s, y) for y in YEARS]))
        else:
            rows.append((s, [value_for_year(table_name, s, y) for y in YEARS]))
    return rows


利润表 = build_table(IS, "利润表")
资产负债表 = build_table(BS, "资产负债表")
现金流量表 = build_table(CF, "现金流量表")


def dget(table, key, i):
    for k, vs in table:
        if k == key:
            return vs[i]
    return None


# ── 校验层 ──────────────────────────────────────────────────────────────

def seq_items(fd_table):
    """按 JSON 键序返回 [(norm名, 原名, {"本年","上年"})]"""
    return [(norm(k), k, v) for k, v in fd_table.items()]


# 「其中」类子项（已含于父项，不参与分桶加总）。新旧准则列报不同：
# 应付股利/应付利息 旧版为独立行、2019+ 新版是其他应付款的其中项 → 自适应判定
SUSPECT_SUBITEMS = {norm(x) for x in [
    "应付股利", "应付利息", "应收利息", "应收股利",
    "子公司支付给少数股东的股利、利润", "子公司吸收少数股东投资收到的现金",
    "利息费用", "利息收入", "对联营企业和合营企业的投资收益",
]}


def bucket_sum_ok(bucket, total, tol):
    """bucket = [(orig, signed_val)]。全和 → 剔「其中」前缀 → 再剔嫌疑子项，任一平即过。"""
    if total is None:
        return True
    vals_all = [v for _, v in bucket if v is not None]
    if abs(sum(vals_all) - total) <= tol:
        return True
    no_qz = [v for o, v in bucket if v is not None and not o.replace(" ", "").startswith("其中")]
    if abs(sum(no_qz) - total) <= tol:
        return True
    no_sus = [v for o, v in bucket
              if v is not None and not o.replace(" ", "").startswith("其中")
              and norm(o) not in SUSPECT_SUBITEMS]
    return abs(sum(no_sus) - total) <= tol


def bucket_check_bs(items, period, year, errors):
    """资产负债表按键序分桶：每遇合计行，检验 桶内和 == 合计（自适应剔「其中」子项）。"""
    markers = ("流动资产合计", "非流动资产合计", "流动负债合计", "非流动负债合计")
    bucket = []
    seen = {}
    for nk, orig, v in items:
        val = v.get(period)
        matched = next((m for m in markers if nk == norm(m)), None)
        if matched:
            if not bucket_sum_ok(bucket, val, TOL_LOOSE):
                ssum = sum(x for _, x in bucket if x is not None)
                errors.append(f"{year}[{period}] {matched} 分项和 {ssum:,.2f} ≠ 合计 {val:,.2f}")
            seen[matched] = val
            bucket = []
        elif nk in (norm("资产总计"), norm("负债合计")):
            seen[nk] = val
            bucket = []
        elif (nk.startswith(norm("归属于母公司")) and "合计" in nk) or nk == norm("归母权益合计"):
            if bucket and not bucket_sum_ok(bucket, val, TOL_LOOSE):
                ssum = sum(x for _, x in bucket if x is not None)
                errors.append(f"{year}[{period}] 归母权益 分项和 {ssum:,.2f} ≠ 合计 {val:,.2f}")
            seen["归母权益"] = val
            bucket = []
        elif nk in (norm("所有者权益合计"), norm("所有者权益(或股东权益)合计"), norm("股东权益合计")):
            seen["权益合计"] = val
            归母 = seen.get("归母权益")
            少数 = next((x for _, x in bucket if x is not None), None)
            if None not in (val, 归母) and 少数 is not None and abs(归母 + 少数 - val) > TOL:
                errors.append(f"{year}[{period}] 归母+少数 ≠ 权益合计")
            bucket = []
        elif nk in (norm("负债和所有者权益总计"), norm("负债和股东权益总计"), norm("负债及所有者权益总计"), norm("负债和所有者权益(或股东权益)总计")):
            bucket = []
        else:
            if val is not None:
                bucket.append((orig, -abs(val) if "库存股" in nk else val))
    # 结构性恒等式
    资产 = seen.get(norm("资产总计"))
    流动 = seen.get("流动资产合计")
    非流动 = seen.get("非流动资产合计")
    负债 = seen.get(norm("负债合计"))
    流负 = seen.get("流动负债合计")
    非流负 = seen.get("非流动负债合计")
    归母 = seen.get("归母权益")
    权益 = seen.get("权益合计")
    if None not in (流动, 非流动, 资产) and abs(流动 + 非流动 - 资产) > TOL:
        errors.append(f"{year}[{period}] 流动+非流动 ≠ 资产总计")
    if None not in (流负, 非流负, 负债) and abs(流负 + 非流负 - 负债) > TOL:
        errors.append(f"{year}[{period}] 流动负债+非流动负债 ≠ 负债合计")
    if None not in (资产, 负债, 权益) and abs(资产 - 负债 - 权益) > TOL:
        errors.append(f"{year}[{period}] 资产 ≠ 负债+权益: {资产:,.2f} vs {负债+权益:,.2f}")


def bucket_check_cf(items, period, year, errors):
    """现金流量表按键序分桶：小计=分项和；净额=流入−流出；总勾稽。"""
    subtotal_map = {}
    bucket = []
    last = {}
    for nk, orig, v in items:
        val = v.get(period)
        if "小计" in nk:
            if not bucket_sum_ok(bucket, val, TOL_LOOSE):
                ssum = sum(x for _, x in bucket if x is not None)
                errors.append(f"{year}[{period}] {orig} 分项和 {ssum:,.2f} ≠ 小计 {val:,.2f}")
            subtotal_map[nk] = val
            bucket = []
        elif "净额" in nk and "现金净额" not in nk:
            last[nk] = val
            bucket = []
        elif nk in (norm("汇率变动对现金及现金等价物的影响"), norm("现金及现金等价物净增加额"),
                    norm("期初现金及现金等价物余额"), norm("期末现金及现金等价物余额")):
            last[nk] = val
            bucket = []
        else:
            if val is not None:
                bucket.append((orig, val))

    def g(*names):
        for n in names:
            for k, v in list(subtotal_map.items()) + list(last.items()):
                if norm(n) in k or k in norm(n):
                    return v
        return None

    for act in ("经营", "投资", "筹资"):
        inflow = g(f"{act}活动现金流入小计")
        outflow = g(f"{act}活动现金流出小计")
        net = g(f"{act}活动产生的现金流量净额")
        if None not in (inflow, outflow, net) and abs(inflow - outflow - net) > TOL:
            errors.append(f"{year}[{period}] {act}净额 ≠ 流入−流出: {inflow-outflow:,.2f} vs {net:,.2f}")
    经营 = g("经营活动产生的现金流量净额")
    投资 = g("投资活动产生的现金流量净额")
    筹资 = g("筹资活动产生的现金流量净额")
    汇率 = g("汇率变动对现金及现金等价物的影响") or 0
    净增 = g("现金及现金等价物净增加额")
    期初 = g("期初现金及现金等价物余额")
    期末 = g("期末现金及现金等价物余额")
    if None not in (经营, 投资, 筹资, 净增) and abs(经营 + 投资 + 筹资 + 汇率 - 净增) > TOL_LOOSE:
        errors.append(f"{year}[{period}] 三净额+汇率 ≠ 净增: {经营+投资+筹资+汇率:,.2f} vs {净增:,.2f}")
    if None not in (期初, 净增, 期末) and abs(期初 + 净增 - 期末) > TOL:
        errors.append(f"{year}[{period}] 期初+净增 ≠ 期末: {期初+净增:,.2f} vs {期末:,.2f}")


def is_check(fd, period, year, errors):
    t = fd["利润表"]

    def gv(std):
        v = lookup(t, std)
        return v.get(period) if v else None

    总收入 = gv("营业总收入") or gv("营业收入")
    总成本 = gv("营业总成本")
    成本项 = [gv("营业成本"), gv("税金及附加"), gv("销售费用"), gv("管理费用"), gv("研发费用"), gv("财务费用")]
    减值 = gv("资产减值损失")
    信用减值 = gv("信用减值损失")
    加项其他 = [gv("其他收益"), gv("投资收益"), gv("公允价值变动收益"), gv("资产处置收益")]
    营业利润 = gv("营业利润")
    营外收 = gv("营业外收入")
    营外支 = gv("营业外支出")
    利润总额 = gv("利润总额")
    所得税 = gv("所得税费用")
    净利润 = gv("净利润")
    归母 = gv("归母净利润")
    少数 = gv("少数股东损益")

    减值在成本内 = False
    if 总成本 is not None:
        s = sum(x for x in 成本项 if x is not None)
        if abs(s - 总成本) <= TOL_LOOSE:
            减值在成本内 = False
        elif 减值 is not None and abs(s + 减值 - 总成本) <= TOL_LOOSE:
            减值在成本内 = True
        else:
            errors.append(f"{year}[{period}] 营业总成本 ≠ 分项和: {s:,.2f}(不含减值)/{(s+(减值 or 0)):,.2f}(含) vs {总成本:,.2f}")
    if None not in (总收入, 总成本, 营业利润):
        adds = sum(x for x in 加项其他 if x is not None)
        if not 减值在成本内:
            adds += (减值 or 0)
        adds += (信用减值 or 0)
        if abs(总收入 - 总成本 + adds - 营业利润) > TOL_LOOSE:
            errors.append(f"{year}[{period}] 营业利润重构 {总收入-总成本+adds:,.2f} ≠ {营业利润:,.2f}")
    if None not in (营业利润, 利润总额):
        if abs(营业利润 + (营外收 or 0) - (营外支 or 0) - 利润总额) > TOL:
            errors.append(f"{year}[{period}] 利润总额勾稽差")
    if None not in (利润总额, 所得税, 净利润) and abs(利润总额 - 所得税 - 净利润) > TOL:
        errors.append(f"{year}[{period}] 净利润勾稽差")
    if None not in (归母, 净利润):
        if abs(归母 + (少数 or 0) - 净利润) > TOL:
            errors.append(f"{year}[{period}] 归母+少数 ≠ 净利润")


def validate_all():
    errors = []
    for y in YEARS:
        if y % 2 == 0 and y != 2006:
            pass  # 偶数年 solo 文件只做交叉核验（其正确性由奇数年上年列+cross_check 保证）
        fd = FLATS[y]
        periods = ["本年"] if RAWS[y].get("solo") else ["本年", "上年"]
        for p in periods:
            if RAWS[y].get("solo"):
                # solo 文件仅关键科目，不做分桶全查（做恒等式抽查）
                t = fd["资产负债表"]
                a = lookup(t, "资产总计")
                l = lookup(t, "负债合计")
                e = lookup(t, "所有者权益合计")
                m = lookup(t, "少数股东权益")
                if a and l and e and None not in (a.get(p), l.get(p), e.get(p)):
                    diff = a[p] - l[p] - e[p]
                    # 2006 老准则：少数股东权益列于负债与股东权益之间（不含于权益合计）
                    mv = m.get(p) if m else None
                    if abs(diff) > TOL and not (mv is not None and abs(diff - mv) <= TOL):
                        errors.append(f"{y}[solo] 资产≠负债+权益(差 {diff:,.2f})")
                continue
            bucket_check_bs(seq_items(fd["资产负债表"]), p, y, errors)
            bucket_check_cf(seq_items(fd["现金流量表"]), p, y, errors)
            is_check(fd, p, y, errors)
    return errors


# ── 派生比率 ────────────────────────────────────────────────────────────

def pct(num, den):
    return round(num / den * 100, 2) if (num is not None and den) else None


def build_ratios():
    n = len(YEARS)

    def g(t, k, i):
        return dget(t, k, i)

    def yoy(key, i, table=None):
        table = table or 利润表
        cur, prev = g(table, key, i), (g(table, key, i - 1) if i > 0 else None)
        return pct(cur - prev, abs(prev)) if (cur is not None and prev) else None

    R = []
    R.append(("营收增速(%)", [yoy("营业收入", i) for i in range(n)]))
    R.append(("归母净利增速(%)", [yoy("归母净利润", i) for i in range(n)]))
    R.append(("扣非归母增速(%)", [yoy("扣非归母净利润", i) for i in range(n)]))
    R.append(("毛利率(%)", [pct((g(利润表, "营业收入", i) or 0) - (g(利润表, "营业成本", i) or 0),
                           g(利润表, "营业收入", i)) for i in range(n)]))
    R.append(("净利率(%)", [pct(g(利润表, "净利润", i), g(利润表, "营业收入", i)) for i in range(n)]))
    R.append(("归母净利率(%)", [pct(g(利润表, "归母净利润", i), g(利润表, "营业收入", i)) for i in range(n)]))
    R.append(("ROE(归母÷期末归母权益,%)", [pct(g(利润表, "归母净利润", i), g(资产负债表, "归母权益合计", i)) for i in range(n)]))

    def roe_avg(i):
        cur = g(资产负债表, "归母权益合计", i)
        prev = g(资产负债表, "归母权益合计", i - 1) if i > 0 else None
        ni = g(利润表, "归母净利润", i)
        if None in (cur, ni) or prev is None:
            return None
        return pct(ni, (cur + prev) / 2)
    R.append(("ROE(归母÷年均归母权益,%)", [roe_avg(i) for i in range(n)]))
    R.append(("销售费用率(%)", [pct(g(利润表, "销售费用", i), g(利润表, "营业收入", i)) for i in range(n)]))
    R.append(("管理费用率(%)", [pct(g(利润表, "管理费用", i), g(利润表, "营业收入", i)) for i in range(n)]))
    R.append(("研发费用率(%)", [pct(g(利润表, "研发费用", i), g(利润表, "营业收入", i)) for i in range(n)]))
    R.append(("税金及附加/营收(%·消费税雷达)", [pct(g(利润表, "税金及附加", i), g(利润表, "营业收入", i)) for i in range(n)]))
    R.append(("经营现金流/净利润(现金含量)", [
        round(g(现金流量表, "经营活动产生的现金流量净额", i) / g(利润表, "净利润", i), 3)
        if (g(现金流量表, "经营活动产生的现金流量净额", i) is not None and g(利润表, "净利润", i)) else None
        for i in range(n)]))
    R.append(("销售收现/营收", [
        round(g(现金流量表, "销售商品、提供劳务收到的现金", i) / g(利润表, "营业收入", i), 3)
        if (g(现金流量表, "销售商品、提供劳务收到的现金", i) is not None and g(利润表, "营业收入", i)) else None
        for i in range(n)]))
    R.append(("capex/净利润(%·正数口径)", [pct(abs(g(现金流量表, "购建固定资产、无形资产等支付的现金", i) or 0) or None,
                                    g(利润表, "净利润", i)) for i in range(n)]))
    R.append(("(合同负债+预收)/营收(%·蓄水池)", [pct((g(资产负债表, "合同负债", i) or 0) + (g(资产负债表, "预收款项", i) or 0),
                                       g(利润表, "营业收入", i)) for i in range(n)]))
    R.append(("应收账款/营收(%)", [pct(g(资产负债表, "应收账款", i), g(利润表, "营业收入", i)) for i in range(n)]))
    R.append(("(应收票据+应收款项融资)/营收(%·银票)", [pct((g(资产负债表, "应收票据", i) or 0) + (g(资产负债表, "应收款项融资", i) or 0) or None,
                                          g(利润表, "营业收入", i)) for i in range(n)]))
    R.append(("资产负债率(%)", [pct(g(资产负债表, "负债合计", i), g(资产负债表, "资产总计", i)) for i in range(n)]))
    R.append(("归母/净利润(%·少数股东leak)", [pct(g(利润表, "归母净利润", i), g(利润表, "净利润", i)) for i in range(n)]))
    R.append(("扣非/归母(%·非经常leak)", [pct(g(利润表, "扣非归母净利润", i), g(利润表, "归母净利润", i)) for i in range(n)]))
    R.append(("存货周转天数", [
        round(365 * g(资产负债表, "存货", i) / g(利润表, "营业成本", i), 1)
        if (g(资产负债表, "存货", i) is not None and g(利润表, "营业成本", i)) else None for i in range(n)]))
    R.append(("应收账款周转天数", [
        round(365 * (g(资产负债表, "应收账款", i) or 0) / g(利润表, "营业收入", i), 1)
        if g(利润表, "营业收入", i) else None for i in range(n)]))
    R.append(("应付账款周转天数", [
        round(365 * (g(资产负债表, "应付账款", i) or 0) / g(利润表, "营业成本", i), 1)
        if g(利润表, "营业成本", i) else None for i in range(n)]))
    R.append(("分配股利利润偿息/归母(%·正数口径·含息近似分红率)", [pct(abs(g(现金流量表, "分配股利、利润或偿付利息支付的现金", i) or 0) or None,
                                              g(利润表, "归母净利润", i)) for i in range(n)]))
    R.append(("货币资金/总资产(%)", [pct(g(资产负债表, "货币资金", i), g(资产负债表, "资产总计", i)) for i in range(n)]))
    R.append(("其他流动资产/总资产(%·大额定期存款所在)", [pct(g(资产负债表, "其他流动资产", i), g(资产负债表, "资产总计", i)) for i in range(n)]))
    R.append(("存货/总资产(%)", [pct(g(资产负债表, "存货", i), g(资产负债表, "资产总计", i)) for i in range(n)]))
    R.append(("固定资产/总资产(%)", [pct(g(资产负债表, "固定资产", i), g(资产负债表, "资产总计", i)) for i in range(n)]))
    R.append(("在建工程/总资产(%)", [pct(g(资产负债表, "在建工程", i), g(资产负债表, "资产总计", i)) for i in range(n)]))
    R.append(("(预付+其他应收)/总资产(%·垃圾筐雷达)", [pct((g(资产负债表, "预付款项", i) or 0) + (g(资产负债表, "其他应收款", i) or 0) or None,
                                          g(资产负债表, "资产总计", i)) for i in range(n)]))
    return R


def write_csv(table, filename):
    path = os.path.join(OUT, filename)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["科目"] + [str(y) for y in YEARS])
        for k, vs in table:
            if all(v is None for v in vs):
                continue  # 全年皆空的科目行不写出
            w.writerow([k] + ["" if v is None else v for v in vs])
    kept = sum(1 for _, vs in table if not all(v is None for v in vs))
    print(f"  ✅ {filename} ({kept} 行 × {len(YEARS)} 年)")


def cross_check():
    """交叉核验：偶数年该年年报本年列(solo) vs 已采用的次年上年列（重述口径）。"""
    print("\n=== 交叉核验（偶数年 solo 本年列 vs 采用的重述口径）===")
    KEY = [("利润表", "营业收入"), ("利润表", "归母净利润"), ("利润表", "净利润"),
           ("利润表", "扣非归母净利润"),
           ("资产负债表", "资产总计"), ("资产负债表", "负债合计"), ("资产负债表", "所有者权益合计"),
           ("资产负债表", "货币资金"), ("资产负债表", "存货"), ("资产负债表", "应收账款"),
           ("现金流量表", "经营活动产生的现金流量净额"), ("现金流量表", "销售商品、提供劳务收到的现金"),
           ("现金流量表", "期末现金及现金等价物余额")]
    for y in range(2006, 2025, 2):
        solo = FLATS.get(y)
        if solo is None:
            print(f"  {y}: ⏳ 无 solo 文件")
            continue
        diffs = []
        for table, subj in KEY:
            adopted = value_for_year(table, subj, y)
            if subj == "扣非归母净利润":
                sv = solo["扣非归母净利润"]["本年"]
            else:
                vv = lookup(solo[table], subj)
                sv = vv.get("本年") if vv else None
            if adopted is not None and sv is not None and abs(adopted - sv) > 1:
                diffs.append(f"{subj}(采用{adopted/1e8:.2f}亿/原始{sv/1e8:.2f}亿)")
        note = {"2006": "老准则→CAS2006 重述", "2016": "营改增", "2018": "同一控制合并追溯重述"}.get(str(y), "")
        print(f"  {y}: " + ("✅一致" if not diffs else f"⚠️ {note} " + "; ".join(diffs)))


def main():
    errs = validate_all()
    if errs:
        print(f"❌ 勾稽校验未通过（{len(errs)} 条），不写出 CSV：")
        for e in errs:
            print("   " + e)
        sys.exit(1)
    print(f"✅ 勾稽校验全部通过（奇数年双列全覆盖分桶 + 恒等式）")
    write_csv(利润表, "利润表.csv")
    write_csv(资产负债表, "资产负债表.csv")
    write_csv(现金流量表, "现金流量表.csv")
    write_csv(build_ratios(), "财务比率.csv")
    cross_check()


if __name__ == "__main__":
    main()
