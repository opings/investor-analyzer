#!/usr/bin/env python3
"""通用派生比率计算器 —— 从任一公司 finance/<公司>/财务数据/{利润表,资产负债表,现金流量表}.csv
读三表, 算全套「财务比率.csv 模板项」并打印。跨会计准则(港股 IFRS 中文 / A 股 CAS)靠科目别名层,
比率本身单位无关(千元/元/亿元皆可, 因均为同单位量之比)。

用法:
    python3 scripts/derived.py <公司>              # 打印全套派生比率
    python3 scripts/derived.py <公司> --check       # 与现有 财务比率.csv 对照, 报缺失/差异

设计原则:
  - **只读打印**(不写盘): 避免与各公司自己的 _build_from_pdf.py 争夺 财务比率.csv 写权(双写者冲突)。
    要落盘请把本文逻辑并进该公司的 _build_from_pdf.py(单一写者), 或人工核验后另议。
  - 科目符号约定差异: A 股营业成本=正数、港股销售成本=负数 → 统一取 abs。
  - 找不到的科目 → 该比率标 n/a + 末尾列出「未匹配科目」, 不静默出错。
"""
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 科目别名(前缀匹配·先港股后A股都覆盖)。取第一个命中的行。
ALIASES = {
    "营收":   ["营业总收入", "营业收入", "收益 Revenue", "收益", "营业额"],
    "成本":   ["营业成本", "销售成本", "减：营业成本"],
    "毛利":   ["毛利 ", "毛利"],
    "净利润": ["净利润 ", "净利润", "四、净利润", "五、净利润", "年内溢利"],
    "归母":   ["归属于母公司股东的净利润", "归属于母公司所有者的净利润", "归属于上市公司股东的净利润",
              "母公司拥有人应占溢利", "归母净利润"],
    "扣非归母": ["扣除非经常性损益后的净利润", "归属于母公司股东的扣除非经常性损益的净利润",
              "扣非归母", "扣非净利润"],
    "税前":   ["利润总额", "三、利润总额", "除税前溢利", "税前利润"],
    "所得税": ["所得税费用", "减：所得税费用", "所得税开支"],
    "应收":   ["应收账款", "贸易应收款项及应收票据", "应收票据及应收账款", "应收账款及应收票据"],
    "存货":   ["存货"],
    "应付":   ["应付账款", "应付票据及应付账款", "贸易应付款项及应付票据"],
    "预付":   ["预付款项", "预付账款"],
    "PPE":    ["固定资产", "物业、厂房及设备"],
    "资产总计": ["资产总计", "资产总额"],  # 勿加"总资产"——会误配「总资产减流动负债」
    "非流动资产总额": ["非流动资产总额", "非流动资产合计"],
    "流动资产总额": ["流动资产总额", "流动资产合计"],
    "权益合计": ["所有者权益合计", "股东权益合计", "所有者权益（或股东权益）合计", "权益总额"],
    "归母权益": ["归属于母公司所有者权益合计", "归属于母公司股东权益合计", "归属于母公司股东的权益合计",
              "母公司拥有人应占权益"],
    "OCF":    ["经营活动产生的现金流量净额", "经营活动现金流量净额", "经营活动所得现金流量净额"],
    "capex":  ["购建固定资产、无形资产和其他长期资产支付的现金", "购买物业厂房设备项目", "购建固定资产"],
    "分红":   ["分配股利、利润或偿付利息支付的现金", "已付股息", "分配股利"],
}
# 现金及金融资产类(求和·尽力而为)
CASH_KEYS = ["货币资金", "现金及银行结余", "现金及现金等价物", "交易性金融资产", "FVTPL金融资产",
             "长期银行存款", "结构性存款", "债权投资", "其他债权投资"]


def load_table(path):
    """读一张三表 CSV → (years:list[int], rows:dict{科目全名: [float|None]})。跳过注释行, 以「科目」行为表头。"""
    with open(path, encoding="utf-8-sig") as f:  # utf-8-sig 兼容带 BOM 的 CSV(长电等)
        raw = list(csv.reader(f))
    hdr_i = next((i for i, r in enumerate(raw) if r and r[0].strip().startswith("科目")), None)
    if hdr_i is None:
        raise ValueError(f"未找到表头(科目行): {path}")
    years = [int(y) for y in raw[hdr_i][1:] if y.strip().isdigit()]
    rows = {}
    for r in raw[hdr_i + 1:]:
        if not r or not r[0].strip():
            continue
        vals = []
        for v in r[1:1 + len(years)]:
            v = v.strip().replace(",", "")
            try:
                vals.append(float(v))
            except ValueError:
                vals.append(None)
        rows[r[0].strip()] = vals
    return years, rows


def pick(rows, key, unmatched):
    """按别名前缀取一行; 记未匹配。"""
    for name in ALIASES[key]:
        for k, v in rows.items():
            if k.startswith(name):
                return v
    unmatched.append(key)
    return None


def main():
    if len(sys.argv) < 2:
        print("用法: python3 scripts/derived.py <公司> [--check]", file=sys.stderr)
        sys.exit(1)
    company = sys.argv[1]
    base = os.path.join(ROOT, "finance", company, "财务数据")
    if not os.path.isdir(base):
        print(f"[derived] 找不到 {base}", file=sys.stderr)
        sys.exit(1)

    tables = {}
    for fn in ["利润表.csv", "资产负债表.csv", "现金流量表.csv"]:
        p = os.path.join(base, fn)
        if not os.path.exists(p):
            print(f"[derived] 缺 {fn}", file=sys.stderr)
            sys.exit(1)
        y, r = load_table(p)
        tables[fn] = (y, r)
    years = tables["利润表.csv"][0]
    N = len(years)
    PL = tables["利润表.csv"][1]
    BS = tables["资产负债表.csv"][1]
    CF = tables["现金流量表.csv"][1]
    unmatched = []

    def g(rows, key):
        return pick(rows, key, unmatched)

    rev, cos = g(PL, "营收"), g(PL, "成本")
    gross = pick(PL, "毛利", [])  # 无毛利行(A股常见)则 gp() 从 营收-abs(成本) 算, 不报未匹配
    npr, parent, kf = g(PL, "净利润"), g(PL, "归母"), g(PL, "扣非归母")
    ar, inv, ap, prepay, ppe = g(BS, "应收"), g(BS, "存货"), g(BS, "应付"), g(BS, "预付"), g(BS, "PPE")
    eq_total, eq_parent = g(BS, "权益合计"), g(BS, "归母权益")
    ocf, capex, div = g(CF, "OCF"), g(CF, "capex"), g(CF, "分红")

    ta_line = pick(BS, "资产总计", [])  # 无此行(港股)则 ta() 回退 非流动+流动, 不报未匹配
    nca, ca = pick(BS, "非流动资产总额", []), pick(BS, "流动资产总额", [])

    def val(row, i):
        return None if row is None or row[i] is None else row[i]

    def ta(i):  # 总资产: 优先「资产总计」, 退回 非流动+流动
        if ta_line and ta_line[i] is not None:
            return ta_line[i]
        if nca and ca and nca[i] is not None and ca[i] is not None:
            return nca[i] + ca[i]
        return None

    def gp(i):  # 毛利: 优先取行, 否则 营收 - abs(成本)
        if gross and gross[i] is not None:
            return gross[i]
        if rev and cos and rev[i] is not None and cos[i] is not None:
            return rev[i] - abs(cos[i])
        return None

    def avg(row, i):
        if row is None or row[i] is None:
            return None
        if i == 0 or row[i - 1] is None:
            return row[i]
        return (row[i] + row[i - 1]) / 2

    def cashfin(i):
        s, found = 0, False
        for k, v in BS.items():
            if any(k.startswith(ck) for ck in CASH_KEYS) and v[i] is not None:
                s += v[i]
                found = True
        return s if found else None

    def d(a, b):  # 安全除
        if a is None or b in (None, 0):
            return None
        return a / b

    def days(bal_avg, base_flow):
        if bal_avg is None or base_flow in (None, 0):
            return None
        return 365 * bal_avg / abs(base_flow)

    R = []  # (指标, [每年值], 格式)
    R.append(("毛利率 Gross margin", [d(gp(i), val(rev, i)) for i in range(N)], "pct"))
    R.append(("净利率 Net margin", [d(val(npr, i), val(rev, i)) for i in range(N)], "pct"))
    R.append(("ROE(期末·归母) Return on equity", [d(val(parent, i), val(eq_parent or eq_total, i)) for i in range(N)], "pct"))
    R.append(("归母/净利 Parent/Net", [d(val(parent, i), val(npr, i)) for i in range(N)], "pct"))
    if kf:
        R.append(("扣非净利率 Adj net margin", [d(val(kf, i), val(rev, i)) for i in range(N)], "pct"))
    else:
        R.append(("扣非净利率 Adj net margin", [None] * N, "na"))  # 港股无扣非线, 需在该公司 build 里估
    R.append(("应收账款周转天数 AR days", [days(avg(ar, i), val(rev, i)) for i in range(N)], "day"))
    R.append(("存货周转天数 Inv days", [days(avg(inv, i), val(cos, i) if cos else None) for i in range(N)], "day"))
    R.append(("应付账款周转天数 AP days", [days(avg(ap, i), val(cos, i) if cos else None) for i in range(N)], "day"))
    R.append(("现金及金融资产/总资产 Cash&fin/TA", [d(cashfin(i), ta(i)) for i in range(N)], "pct"))
    R.append(("固定资产PPE/总资产 PPE/TA", [d(val(ppe, i), ta(i)) for i in range(N)], "pct"))
    R.append(("存货/总资产 Inv/TA", [d(val(inv, i), ta(i)) for i in range(N)], "pct"))
    rp = [(val(ar, i) or 0) + (val(prepay, i) or 0) if (ar or prepay) else None for i in range(N)]
    R.append(("(应收+预付)/总资产 Recv/TA", [d(rp[i], ta(i)) for i in range(N)], "pct"))
    R.append(("资产负债率 Liab/TA", [d(ta(i) - val(eq_total, i), ta(i)) if ta(i) is not None and val(eq_total, i) is not None else None for i in range(N)], "pct"))
    R.append(("经营现金流/净利 OCF/NP", [d(val(ocf, i), val(npr, i)) for i in range(N)], "x"))
    R.append(("Capex/净利 Capex/NP", [d(abs(val(capex, i)) if val(capex, i) is not None else None, val(npr, i)) for i in range(N)], "x"))
    R.append(("当年分红率 Payout", [d(abs(val(div, i)) if val(div, i) is not None else None, val(parent, i)) for i in range(N)], "pct"))

    # 打印
    print(f"# {company} 派生比率(通用 derived.py·只读) · 年份 {years[0]}-{years[-1]}")
    w = 9
    hdr = "指标".ljust(30) + "".join(str(y).rjust(w) for y in years)
    print(hdr)
    print("-" * len(hdr))
    for name, vals, fmt in R:
        cells = []
        for v in vals:
            if v is None:
                cells.append("—".rjust(w))
            elif fmt == "pct":
                cells.append(f"{v*100:.1f}%".rjust(w))
            elif fmt == "day":
                cells.append(f"{v:.1f}".rjust(w))
            else:  # x
                cells.append(f"{v:.2f}".rjust(w))
        print(name.ljust(30) + "".join(cells))

    if unmatched:
        print("\n⚠️ 未匹配科目(相关比率为 —, 需补别名或该公司科目命名特殊):", "、".join(sorted(set(unmatched))))
    if "分配股利、利润或偿付利息" in str(ALIASES["分红"]) and div is not None:
        print("注: A股「分配股利利润或偿付利息支付的现金」含付息, 分红率偏高, 精确分红另查分红预案。")
    print("注: 扣非——A股取财报披露值; 港股IFRS无标准扣非线, 应在该公司 _build_from_pdf.py 里估算(剔投资类非经常)。")


if __name__ == "__main__":
    main()
