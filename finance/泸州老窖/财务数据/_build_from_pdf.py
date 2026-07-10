# -*- coding: utf-8 -*-
"""泸州老窖(000568) 三表 + 派生比率 → 写 CSV,内置勾稽自洽校验(校验不过不写出)。

数据血缘(2006-2025 · 20 年 · 全部 CAS2006 体系·重述口径):
  主数据源 = 奇数年年报(2007/09/11/13/15/17/19/21/23/25)的「本年列 + 上年比较列」,
  每份年报出 2 年(本年=奇数年·来自该年年报;上年=偶数年·来自次年年报的上年比较列),
  10 份年报接续覆盖 2006-2025 全部 20 年。原始逐年提取 JSON 存 _extract_json/(从一手财报 PDF 图像逐行提取)。

  为什么偶数年用「次年年报上年比较列」而非该年年报本年列:
  保证跨年口径一致(重述后口径)。已用「偶数年该年年报本年列」交叉核验(见 _extract_json/*偶数年):
    - 2008/10/12/14/18/20/22/24:本年列 = 次年上年列,完全一致(无重述,跳读无损)
    - 2006:老准则(企业会计制度)→ CAS2006 追溯重述(2007 年报),用重述口径(与 2007+ 可比)
    - 2016:营改增(2016-05 全面营改增)→ 2017 年报按新口径重述 2016(营收 83.04→86.27 亿),用重述口径
  → 结论:统一采用「次年年报上年列(重述口径)」使 2006-2025 序列内部可比。

口径:
  - 单位 = 人民币元(年报原始口径),精确到分
  - 资产负债权益 = 正数;现金流量表流出/减项 = 负数、流入/加项 = 正数;None = 该期无此科目(CSV 留空)

会计准则/披露沿革(影响科目一致性):
  - 2006: 企业会计制度(老准则)末年 → 本库 2006 用 2007 年报追溯重述的 CAS2006 口径
  - 2007: CAS2006 新准则首年
  - 2016-05: 全面营改增 → 2017 年报重述 2016(价税分离,营收口径变化)
  - 2018: 「研发费用」首次独立列示
  - 2019: 新金融工具准则 →「应收款项融资」「其他权益工具投资」「信用减值损失」独立
  - 2020: 新收入准则 →「预收款项」切换为「合同负债」
  - 2021: 新租赁准则 →「使用权资产」「租赁负债」
"""
import csv
import json
import os
import sys

YEARS = list(range(2006, 2026))
OUT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(OUT, "_extract_json")
ODD = [y for y in YEARS if y % 2 == 1]

TABLES = ["利润表", "资产负债表", "现金流量表"]


def to_num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return None


def norm(s):
    return s.replace(" ", "").replace("（", "(").replace("）", ")").replace("、", "")


def flatten(fd):
    """把 4 种提取结构统一拍平成 {table: {科目: {"本年":x, "上年":y}}}"""
    out = {}
    for table in TABLES:
        out[table] = {}
        raw = fd.get(table, {})
        # 结构3: table 值是 {"本年":{科目:值},"上年":{科目:值}} (2017)
        if raw and set(raw.keys()) <= {"本年", "上年"} and all(isinstance(v, dict) for v in raw.values()):
            for period in ("本年", "上年"):
                for subj, val in raw.get(period, {}).items():
                    out[table].setdefault(subj, {})[period] = to_num(val)
            continue
        for subj, val in raw.items():  # 结构1数组/结构2内嵌/偶数年单值
            if isinstance(val, list):
                out[table][subj] = {"本年": to_num(val[0]), "上年": to_num(val[1]) if len(val) > 1 else None}
            elif isinstance(val, dict):
                out[table][subj] = {"本年": to_num(val.get("本年")), "上年": to_num(val.get("上年"))}
            else:
                out[table][subj] = {"本年": to_num(val), "上年": None}
        raw_prior = fd.get(table + "_上年")  # 结构4: 2021 上年在 table_上年
        if raw_prior:
            for subj, val in raw_prior.items():
                out[table].setdefault(subj, {})["上年"] = to_num(val)
    return out


def load_flat(year):
    p = os.path.join(SRC, f"lzlj_extract_{year}.json")
    with open(p, encoding="utf-8") as f:
        return flatten(json.load(f))


FLATS = {y: load_flat(y) for y in YEARS}

# 标准科目表(顺序 = CSV 行序)
IS = ["营业总收入", "营业收入", "营业总成本", "营业成本", "税金及附加", "销售费用", "管理费用",
      "研发费用", "财务费用", "利息费用", "利息收入", "其他收益", "投资收益", "公允价值变动收益",
      "信用减值损失", "资产减值损失", "资产处置收益", "营业利润", "营业外收入", "营业外支出",
      "利润总额", "所得税费用", "净利润", "归母净利润", "少数股东损益", "基本每股收益"]
BS = ["货币资金", "交易性金融资产", "应收票据", "应收账款", "应收款项融资", "预付款项", "其他应收款",
      "存货", "其他流动资产", "流动资产合计", "可供出售金融资产", "长期股权投资", "其他权益工具投资",
      "投资性房地产", "固定资产", "在建工程", "使用权资产", "无形资产", "商誉", "长期待摊费用",
      "递延所得税资产", "其他非流动资产", "非流动资产合计", "资产总计", "短期借款", "应付票据",
      "应付账款", "预收款项", "合同负债", "应付职工薪酬", "应交税费", "其他应付款",
      "一年内到期的非流动负债", "其他流动负债", "流动负债合计", "长期借款", "应付债券", "租赁负债",
      "递延收益", "递延所得税负债", "其他非流动负债", "非流动负债合计", "负债合计", "股本",
      "资本公积", "盈余公积", "未分配利润", "其他综合收益", "归母权益合计", "少数股东权益",
      "所有者权益合计"]
CF = ["销售商品、提供劳务收到的现金", "收到的税费返还", "收到其他与经营活动有关的现金",
      "经营活动现金流入小计", "购买商品、接受劳务支付的现金", "支付给职工及为职工支付的现金",
      "支付的各项税费", "支付其他与经营活动有关的现金", "经营活动现金流出小计",
      "经营活动产生的现金流量净额", "收回投资收到的现金", "取得投资收益收到的现金",
      "处置固定资产、无形资产等收回的现金净额", "投资活动现金流入小计",
      "购建固定资产、无形资产等支付的现金", "投资支付的现金", "取得子公司收到/支付的现金净额",
      "投资活动现金流出小计", "投资活动产生的现金流量净额", "吸收投资收到的现金",
      "取得借款收到的现金", "收到其他与筹资活动有关的现金", "筹资活动现金流入小计",
      "偿还债务支付的现金", "分配股利、利润或偿付利息支付的现金", "支付其他与筹资活动有关的现金",
      "筹资活动现金流出小计", "筹资活动产生的现金流量净额", "汇率变动对现金及现金等价物的影响",
      "现金及现金等价物净增加额", "期初现金及现金等价物余额", "期末现金及现金等价物余额"]

ALIAS = {
    "税金及附加": ["税金及附加(营业税金及附加)", "营业税金及附加"],
    "取得子公司收到/支付的现金净额": ["取得子公司及其他营业单位支付的现金净额",
                          "处置子公司及其他营业单位收到的现金净额"],
}


def value_for_year(table, std_subj, year):
    """重述口径:奇数年取该年报本年列;偶数年取次年(奇数)年报上年比较列。"""
    if year % 2 == 1:
        fd, period = FLATS.get(year), "本年"
    else:
        fd, period = FLATS.get(year + 1), "上年"
    if fd is None:
        return None
    cands = [std_subj] + ALIAS.get(std_subj, [])
    for cand in cands:
        for k, v in fd[table].items():
            if norm(k) == norm(cand):
                return v.get(period)
    return None


def build_table(std_list, table_name):
    return [(s, [value_for_year(table_name, s, y) for y in YEARS]) for s in std_list]


利润表 = build_table(IS, "利润表")
资产负债表 = build_table(BS, "资产负债表")
现金流量表 = build_table(CF, "现金流量表")


def dget(table, key, i):
    for k, vs in table:
        if k == key:
            return vs[i]
    return None


def check_year(i, year):
    errors = []
    营业利润 = dget(利润表, "营业利润", i)
    营外收 = dget(利润表, "营业外收入", i)
    营外支 = dget(利润表, "营业外支出", i)
    利润总额 = dget(利润表, "利润总额", i)
    所得税 = dget(利润表, "所得税费用", i)
    净利润 = dget(利润表, "净利润", i)
    归母 = dget(利润表, "归母净利润", i)
    少数 = dget(利润表, "少数股东损益", i)
    if None not in (营业利润, 营外收, 营外支, 利润总额):
        if abs(营业利润 + 营外收 - 营外支 - 利润总额) > 100:
            errors.append(f"{year} 利润总额勾稽: {营业利润+营外收-营外支:.2f} vs {利润总额:.2f}")
    if None not in (利润总额, 所得税, 净利润):
        if abs(利润总额 - 所得税 - 净利润) > 100:
            errors.append(f"{year} 净利润勾稽: {利润总额-所得税:.2f} vs {净利润:.2f}")
    if None not in (归母, 少数, 净利润):
        if abs(归母 + 少数 - 净利润) > 100:
            errors.append(f"{year} 归母+少数 vs 净利润: {归母+少数:.2f} vs {净利润:.2f}")
    资产 = dget(资产负债表, "资产总计", i)
    负债 = dget(资产负债表, "负债合计", i)
    权益 = dget(资产负债表, "所有者权益合计", i)
    归母权益 = dget(资产负债表, "归母权益合计", i)
    少数权益 = dget(资产负债表, "少数股东权益", i)
    if None not in (资产, 负债, 权益):
        if abs(资产 - 负债 - 权益) > 100:
            errors.append(f"{year} 资产=负债+权益: {资产:.2f} vs {负债+权益:.2f}")
    if None not in (归母权益, 少数权益, 权益):
        if abs(归母权益 + 少数权益 - 权益) > 100:
            errors.append(f"{year} 归母+少数权益 vs 合计")
    经营 = dget(现金流量表, "经营活动产生的现金流量净额", i)
    投资 = dget(现金流量表, "投资活动产生的现金流量净额", i)
    筹资 = dget(现金流量表, "筹资活动产生的现金流量净额", i)
    汇率 = dget(现金流量表, "汇率变动对现金及现金等价物的影响", i)
    净增 = dget(现金流量表, "现金及现金等价物净增加额", i)
    期初 = dget(现金流量表, "期初现金及现金等价物余额", i)
    期末 = dget(现金流量表, "期末现金及现金等价物余额", i)
    if None not in (经营, 投资, 筹资, 净增):
        if abs(经营 + 投资 + 筹资 + (汇率 or 0) - 净增) > 1000:
            errors.append(f"{year} 现金流三项+汇率 vs 净增: {经营+投资+筹资+(汇率 or 0):.2f} vs {净增:.2f}")
    if None not in (期初, 净增, 期末):
        if abs(期初 + 净增 - 期末) > 100:
            errors.append(f"{year} 期初+净增 vs 期末: {期初+净增:.2f} vs {期末:.2f}")
    return errors


def pct(num, den):
    return round(num / den * 100, 2) if (num is not None and den) else None


def ratio_row(name, fn):
    return (name, [fn(i) for i in range(len(YEARS))])


def build_ratios():
    R = []
    g = lambda t, k, i: dget(t, k, i)
    R.append(ratio_row("毛利率(%)", lambda i: pct(
        (g(利润表, "营业收入", i) or 0) - (g(利润表, "营业成本", i) or 0), g(利润表, "营业收入", i))))
    R.append(ratio_row("净利率(%)", lambda i: pct(g(利润表, "净利润", i), g(利润表, "营业收入", i))))
    R.append(ratio_row("归母净利率(%)", lambda i: pct(g(利润表, "归母净利润", i), g(利润表, "营业收入", i))))
    R.append(ratio_row("ROE(归母÷期末归母权益,%)", lambda i: pct(g(利润表, "归母净利润", i), g(资产负债表, "归母权益合计", i))))
    R.append(ratio_row("销售费用率(%)", lambda i: pct(g(利润表, "销售费用", i), g(利润表, "营业收入", i))))
    R.append(ratio_row("管理费用率(%)", lambda i: pct(g(利润表, "管理费用", i), g(利润表, "营业收入", i))))
    R.append(ratio_row("研发费用率(%)", lambda i: pct(g(利润表, "研发费用", i), g(利润表, "营业收入", i))))
    R.append(ratio_row("税金及附加/营收(%·消费税等)", lambda i: pct(g(利润表, "税金及附加", i), g(利润表, "营业收入", i))))
    R.append(ratio_row("经营现金流/净利润(现金含量)", lambda i: round(
        g(现金流量表, "经营活动产生的现金流量净额", i) / g(利润表, "净利润", i), 3)
        if (g(现金流量表, "经营活动产生的现金流量净额", i) is not None and g(利润表, "净利润", i)) else None))
    R.append(ratio_row("销售收现/营收", lambda i: round(
        g(现金流量表, "销售商品、提供劳务收到的现金", i) / g(利润表, "营业收入", i), 3)
        if (g(现金流量表, "销售商品、提供劳务收到的现金", i) is not None and g(利润表, "营业收入", i)) else None))
    R.append(ratio_row("capex/净利润(%)", lambda i: pct(
        -(g(现金流量表, "购建固定资产、无形资产等支付的现金", i) or 0), g(利润表, "净利润", i))))
    R.append(ratio_row("(合同负债+预收)/营收(%·蓄水池)", lambda i: pct(
        (g(资产负债表, "合同负债", i) or 0) + (g(资产负债表, "预收款项", i) or 0), g(利润表, "营业收入", i))))
    R.append(ratio_row("应收账款/营收(%)", lambda i: pct(g(资产负债表, "应收账款", i), g(利润表, "营业收入", i))))
    R.append(ratio_row("资产负债率(%)", lambda i: pct(g(资产负债表, "负债合计", i), g(资产负债表, "资产总计", i))))
    R.append(ratio_row("归母/净利润(%·少数股东leak)", lambda i: pct(g(利润表, "归母净利润", i), g(利润表, "净利润", i))))
    R.append(ratio_row("存货周转天数", lambda i: round(
        365 * g(资产负债表, "存货", i) / g(利润表, "营业成本", i), 1)
        if (g(资产负债表, "存货", i) is not None and g(利润表, "营业成本", i)) else None))
    R.append(ratio_row("应收账款周转天数", lambda i: round(
        365 * (g(资产负债表, "应收账款", i) or 0) / g(利润表, "营业收入", i), 1)
        if g(利润表, "营业收入", i) else None))
    R.append(ratio_row("分配股利利润偿息/归母(%·含息近似分红率)", lambda i: pct(
        -(g(现金流量表, "分配股利、利润或偿付利息支付的现金", i) or 0), g(利润表, "归母净利润", i))))
    R.append(ratio_row("货币资金/总资产(%)", lambda i: pct(g(资产负债表, "货币资金", i), g(资产负债表, "资产总计", i))))
    R.append(ratio_row("存货/总资产(%)", lambda i: pct(g(资产负债表, "存货", i), g(资产负债表, "资产总计", i))))
    R.append(ratio_row("固定资产/总资产(%)", lambda i: pct(g(资产负债表, "固定资产", i), g(资产负债表, "资产总计", i))))

    # ── 通用底补漏 ← scripts/derived.py（追加本公司尚无的通用比率·单一逻辑·跨公司复用·不改上面已核验的定制行）
    # 本文件比率存百分数(×100)、天数存原值 → 按 derived 的 fmt 把分数换算成本文件口径
    import sys
    scripts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(OUT))), "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import derived
    common, _ = derived.compute_common_ratios(dict(利润表), dict(资产负债表), dict(现金流量表))
    cd = {name: (vals, fmt) for name, vals, fmt in common}

    def _conv(vals, fmt):
        if fmt == "pct":
            return [round(v * 100, 2) if v is not None else None for v in vals]
        if fmt == "day":
            return [round(v, 1) if v is not None else None for v in vals]
        return [round(v, 2) if v is not None else None for v in vals]

    for src, out_label in [
        ("ROE(年均) Return on avg equity", "ROE(归母÷年均归母权益,%)"),
        ("应付账款周转天数 AP turnover days", "应付账款周转天数"),
        ("(应收+预付)/总资产 Receivables&prepay/TA", "(应收+预付)/总资产(%)"),
    ]:
        if src in cd:
            vals, fmt = cd[src]
            R.append((out_label, _conv(vals, fmt)))

    return R


def write_csv(table, filename):
    path = os.path.join(OUT, filename)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["科目"] + [str(y) for y in YEARS])
        for k, vs in table:
            w.writerow([k] + ["" if v is None else v for v in vs])
    print(f"  ✅ {filename} ({len(table)} 行 × {len(YEARS)} 年)")


def cross_check():
    """交叉核验:偶数年该年年报本年列(solo) vs 已采用的次年上年列。打印差异摘要。"""
    print("\n=== 交叉核验(偶数年 solo 本年列 vs 采用的重述口径)===")
    KEY = [("利润表", "营业收入"), ("利润表", "归母净利润"), ("资产负债表", "资产总计"),
           ("现金流量表", "经营活动产生的现金流量净额")]
    for y in range(2006, 2025, 2):
        solo = FLATS[y]
        diffs = []
        for table, subj in KEY:
            adopted = value_for_year(table, subj, y)
            sv = None
            for k, v in solo[table].items():
                if norm(k) == norm(subj):
                    sv = v.get("本年")
                    break
            if adopted is not None and sv is not None and abs(adopted - sv) > 1:
                diffs.append(f"{subj}(采用{adopted/1e8:.2f}亿/原始{sv/1e8:.2f}亿)")
        note = "老准则" if y == 2006 else ("营改增重述" if y == 2016 else "")
        print(f"  {y}: " + ("✅一致" if not diffs else f"⚠️{note} " + "; ".join(diffs)))


def main():
    all_err = []
    for i, y in enumerate(YEARS):
        all_err += check_year(i, y)
    if all_err:
        print("❌ 勾稽校验未通过,不写出 CSV:")
        for e in all_err:
            print("   " + e)
        sys.exit(1)
    print(f"✅ 勾稽校验全部通过({len(YEARS)} 年 × 6-7 项)")
    write_csv(利润表, "利润表.csv")
    write_csv(资产负债表, "资产负债表.csv")
    write_csv(现金流量表, "现金流量表.csv")
    write_csv(build_ratios(), "财务比率.csv")
    cross_check()


if __name__ == "__main__":
    main()
