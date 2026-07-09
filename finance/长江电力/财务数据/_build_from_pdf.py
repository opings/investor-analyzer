# -*- coding: utf-8 -*-
"""长江电力(600900) 三表 + 派生比率 → 写 CSV,内置勾稽自洽校验(校验不过不写出)。

数据血缘(2006-2025 · 20 年):
  逐年本年列 —— 每年数据 = 该年年报「本年列」(该年实际披露的经营口径),
  原始逐年提取 JSON 存 _extract_json/cjdl_extract_YYYY.json(从一手财报 PDF pdftotext 文本逐行提取)。
  例外:2006 = 2007 年报的「上年比较列」(CAS2006 重述口径,优于 2006 年报老准则口径,与 2007+ 可比)。

  ⚠️ 资产注入追溯重述(长电核心特征·同一控制下企业合并权益结合法):
    2009(三峡工程)、2016(溪洛渡+向家坝)、2023(乌东德+白鹤滩)三次注入,当年年报会追溯重述上年比较列。
    本库用「逐年本年列」→ 台阶 = 真实的注入使公司规模跳升(2015→2016 资产翻倍、2022→2023 资产+75%)。
    注入年当年本年列 ≠ 上年本年列(口径差),这是真实的资产注入,不抹平。分析时在注入年标注。

口径:
  - 单位 = 人民币元(年报原始口径),精确到分
  - 资产负债权益 = 正数;现金流量表流出/减项 = 负数、流入/加项 = 正数;null = 该期无此科目(CSV 留空)

会计准则沿革(影响科目一致性):
  - 2006: 企业会计制度(老准则)→ 本库用 2007 年报追溯重述的 CAS2006 口径
  - 2007: CAS2006 新准则首年(公司无子公司,合并=母公司)
  - 2019: 新金融工具准则 →「可供出售金融资产」拆分为「其他权益工具投资/其他非流动金融资产/债权投资」
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
    return s.replace(" ", "").replace("（", "(").replace("）", ")").replace("、", "").replace(":", "").replace("：", "")


def load(year):
    p = os.path.join(SRC, f"cjdl_extract_{year}.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


DATA = {y: load(y) for y in YEARS}

# 标准科目表(顺序 = CSV 行序)
IS = ["营业总收入", "营业收入", "营业总成本", "营业成本", "税金及附加", "销售费用", "管理费用",
      "研发费用", "财务费用", "利息费用", "利息收入", "其他收益", "投资收益",
      "对联营合营企业投资收益", "公允价值变动收益", "信用减值损失", "资产减值损失",
      "资产处置收益", "营业利润", "营业外收入", "营业外支出", "利润总额", "所得税费用",
      "净利润", "归属于母公司股东的净利润", "少数股东损益", "基本每股收益"]
BS = ["货币资金", "交易性金融资产", "应收票据", "应收账款", "应收款项融资", "预付款项",
      "其他应收款", "存货", "其他流动资产", "流动资产合计", "可供出售金融资产", "债权投资",
      "长期股权投资", "其他权益工具投资", "其他非流动金融资产", "投资性房地产", "固定资产",
      "在建工程", "使用权资产", "无形资产", "开发支出", "商誉", "长期待摊费用",
      "递延所得税资产", "其他非流动资产", "非流动资产合计", "资产总计", "短期借款", "应付票据",
      "应付账款", "合同负债", "应付职工薪酬", "应交税费", "其他应付款",
      "一年内到期的非流动负债", "其他流动负债", "流动负债合计", "长期借款", "应付债券",
      "永续债", "租赁负债", "长期应付款", "预计负债", "递延收益", "递延所得税负债",
      "其他非流动负债", "非流动负债合计", "负债合计", "股本", "其他权益工具", "资本公积",
      "其他综合收益", "专项储备", "盈余公积", "未分配利润", "归属于母公司股东权益合计",
      "少数股东权益", "所有者权益合计"]
CF = ["销售商品、提供劳务收到的现金", "收到的税费返还", "收到其他与经营活动有关的现金",
      "经营活动现金流入小计", "购买商品、接受劳务支付的现金", "支付给职工及为职工支付的现金",
      "支付的各项税费", "支付其他与经营活动有关的现金", "经营活动现金流出小计",
      "经营活动产生的现金流量净额", "收回投资收到的现金", "取得投资收益收到的现金",
      "处置固定资产、无形资产等收回的现金净额", "处置子公司及其他营业单位收到的现金净额",
      "投资活动现金流入小计", "购建固定资产、无形资产等支付的现金", "投资支付的现金",
      "取得子公司及其他营业单位支付的现金净额", "投资活动现金流出小计",
      "投资活动产生的现金流量净额", "吸收投资收到的现金", "取得借款收到的现金",
      "收到其他与筹资活动有关的现金", "筹资活动现金流入小计", "偿还债务支付的现金",
      "分配股利、利润或偿付利息支付的现金", "支付其他与筹资活动有关的现金",
      "筹资活动现金流出小计", "筹资活动产生的现金流量净额", "汇率变动对现金及现金等价物的影响",
      "现金及现金等价物净增加额", "期初现金及现金等价物余额", "期末现金及现金等价物余额"]

ALIAS = {
    "归属于母公司股东的净利润": ["归属于母公司所有者的净利润", "归母净利润"],
    "归属于母公司股东权益合计": ["归属于母公司所有者权益合计", "归母权益合计",
                        "归属于母公司股东权益(或股东权益)合计"],
    "税金及附加": ["营业税金及附加"],
    "对联营合营企业投资收益": ["其中对联营企业和合营企业的投资收益"],
}


def val(table, std_subj, year):
    fd = DATA[year].get(table, {})
    cands = [std_subj] + ALIAS.get(std_subj, [])
    for cand in cands:
        for k, v in fd.items():
            if norm(k) == norm(cand):
                return to_num(v)
    return None


def build_table(std_list, table_name):
    return [(s, [val(table_name, s, y) for y in YEARS]) for s in std_list]


利润表 = build_table(IS, "利润表")
资产负债表 = build_table(BS, "资产负债表")
现金流量表 = build_table(CF, "现金流量表")


def dget(table, key, i):
    for k, vs in table:
        if k == key:
            return vs[i]
    return None


def check_year(i, y):
    e = []
    营 = dget(利润表, "营业利润", i)
    外收 = dget(利润表, "营业外收入", i)
    外支 = dget(利润表, "营业外支出", i)
    总 = dget(利润表, "利润总额", i)
    税 = dget(利润表, "所得税费用", i)
    净 = dget(利润表, "净利润", i)
    归 = dget(利润表, "归属于母公司股东的净利润", i)
    少 = dget(利润表, "少数股东损益", i)
    if None not in (营, 外收, 外支, 总) and abs(营 + 外收 - 外支 - 总) > 100:
        e.append(f"{y} 利润总额勾稽: {营+外收-外支:.0f} vs {总:.0f}")
    if None not in (总, 税, 净) and abs(总 - 税 - 净) > 100:
        e.append(f"{y} 净利润勾稽: {总-税:.0f} vs {净:.0f}")
    if None not in (归, 少, 净) and abs(归 + 少 - 净) > 100:
        e.append(f"{y} 归母+少数 vs 净利润: {归+少:.0f} vs {净:.0f}")
    资 = dget(资产负债表, "资产总计", i)
    负 = dget(资产负债表, "负债合计", i)
    权 = dget(资产负债表, "所有者权益合计", i)
    归权 = dget(资产负债表, "归属于母公司股东权益合计", i)
    少权 = dget(资产负债表, "少数股东权益", i)
    if None not in (资, 负, 权) and abs(资 - 负 - 权) > 100:
        e.append(f"{y} 资产=负债+权益: {资:.0f} vs {负+权:.0f}")
    if None not in (归权, 少权, 权) and abs(归权 + 少权 - 权) > 100:
        e.append(f"{y} 归母+少数权益 vs 合计: {归权+少权:.0f} vs {权:.0f}")
    经 = dget(现金流量表, "经营活动产生的现金流量净额", i)
    投 = dget(现金流量表, "投资活动产生的现金流量净额", i)
    筹 = dget(现金流量表, "筹资活动产生的现金流量净额", i)
    汇 = dget(现金流量表, "汇率变动对现金及现金等价物的影响", i)
    增 = dget(现金流量表, "现金及现金等价物净增加额", i)
    初 = dget(现金流量表, "期初现金及现金等价物余额", i)
    末 = dget(现金流量表, "期末现金及现金等价物余额", i)
    if None not in (经, 投, 筹, 增) and abs(经 + 投 + 筹 + (汇 or 0) - 增) > 1000:
        e.append(f"{y} 现金流三项+汇率 vs 净增: {经+投+筹+(汇 or 0):.0f} vs {增:.0f}")
    if None not in (初, 增, 末) and abs(初 + 增 - 末) > 100:
        e.append(f"{y} 期初+净增 vs 期末: {初+增:.0f} vs {末:.0f}")
    return e


def pct(num, den):
    return round(num / den * 100, 2) if (num is not None and den) else None


def rr(name, fn):
    return (name, [fn(i) for i in range(len(YEARS))])


def build_ratios():
    R = []
    g = lambda t, k, i: dget(t, k, i)
    R.append(rr("毛利率(%)", lambda i: pct((g(利润表, "营业收入", i) or 0) - (g(利润表, "营业成本", i) or 0), g(利润表, "营业收入", i))))
    R.append(rr("净利率(%)", lambda i: pct(g(利润表, "净利润", i), g(利润表, "营业收入", i))))
    R.append(rr("归母净利率(%)", lambda i: pct(g(利润表, "归属于母公司股东的净利润", i), g(利润表, "营业收入", i))))
    R.append(rr("ROE(归母÷归母权益,%)", lambda i: pct(g(利润表, "归属于母公司股东的净利润", i), g(资产负债表, "归属于母公司股东权益合计", i))))
    R.append(rr("财务费用/营收(%·高杠杆)", lambda i: pct(g(利润表, "财务费用", i), g(利润表, "营业收入", i))))
    R.append(rr("税金及附加/营收(%)", lambda i: pct(g(利润表, "税金及附加", i), g(利润表, "营业收入", i))))
    R.append(rr("投资收益/利润总额(%·参股贡献)", lambda i: pct(g(利润表, "投资收益", i), g(利润表, "利润总额", i))))
    R.append(rr("对联营合营投资收益/利润总额(%)", lambda i: pct(g(利润表, "对联营合营企业投资收益", i), g(利润表, "利润总额", i))))
    R.append(rr("营业外收入/利润总额(%·政策补偿)", lambda i: pct(g(利润表, "营业外收入", i), g(利润表, "利润总额", i))))
    R.append(rr("经营现金流/净利润(现金含量)", lambda i: round(g(现金流量表, "经营活动产生的现金流量净额", i) / g(利润表, "净利润", i), 3)
               if (g(现金流量表, "经营活动产生的现金流量净额", i) is not None and g(利润表, "净利润", i)) else None))
    R.append(rr("capex/净利润(%)", lambda i: pct(-(g(现金流量表, "购建固定资产、无形资产等支付的现金", i) or 0), g(利润表, "净利润", i))))
    R.append(rr("capex/经营现金流(%)", lambda i: pct(-(g(现金流量表, "购建固定资产、无形资产等支付的现金", i) or 0), g(现金流量表, "经营活动产生的现金流量净额", i))))
    R.append(rr("资产负债率(%)", lambda i: pct(g(资产负债表, "负债合计", i), g(资产负债表, "资产总计", i))))
    R.append(rr("有息负债/总资产(%)", lambda i: pct(
        (g(资产负债表, "短期借款", i) or 0) + (g(资产负债表, "长期借款", i) or 0) + (g(资产负债表, "应付债券", i) or 0) + (g(资产负债表, "一年内到期的非流动负债", i) or 0),
        g(资产负债表, "资产总计", i))))
    R.append(rr("归母/净利润(%·少数股东leak)", lambda i: pct(g(利润表, "归属于母公司股东的净利润", i), g(利润表, "净利润", i))))
    R.append(rr("固定资产/总资产(%)", lambda i: pct(g(资产负债表, "固定资产", i), g(资产负债表, "资产总计", i))))
    R.append(rr("长期股权投资/总资产(%)", lambda i: pct(g(资产负债表, "长期股权投资", i), g(资产负债表, "资产总计", i))))
    R.append(rr("应收账款/营收(%)", lambda i: pct(g(资产负债表, "应收账款", i), g(利润表, "营业收入", i))))
    R.append(rr("分配股利利润偿息/归母(%·含息近似分红率)", lambda i: pct(-(g(现金流量表, "分配股利、利润或偿付利息支付的现金", i) or 0), g(利润表, "归属于母公司股东的净利润", i))))
    return R


def write_csv(table, filename):
    path = os.path.join(OUT, filename)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["科目"] + [str(y) for y in YEARS])
        for k, vs in table:
            w.writerow([k] + ["" if v is None else v for v in vs])
    print(f"  ✅ {filename} ({len(table)} 行 × {len(YEARS)} 年)")


def main():
    all_err = []
    for i, y in enumerate(YEARS):
        all_err += check_year(i, y)
    if all_err:
        print("❌ 勾稽校验未通过,不写出 CSV:")
        for e in all_err:
            print("   " + e)
        sys.exit(1)
    print(f"✅ 勾稽校验全部通过({len(YEARS)} 年 × 7 项)")
    write_csv(利润表, "利润表.csv")
    write_csv(资产负债表, "资产负债表.csv")
    write_csv(现金流量表, "现金流量表.csv")
    write_csv(build_ratios(), "财务比率.csv")


if __name__ == "__main__":
    main()
