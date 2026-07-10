#!/usr/bin/env python3
"""通用派生比率引擎（通用底）—— 从任一公司三表算「全公司共有」的派生比率。

两种用法:
  1. CLI 只读打印:  python3 scripts/derived.py <公司>
  2. **被各公司 _build_from_pdf.py import**（推荐·单一写者架构）:
        import derived
        common, _ = derived.compute_common_ratios(dict(利润表), dict(资产负债表), dict(现金流量表))
        rows = [(n, v) for n, v, f in common] + [本公司定制行...]   # 通用底 + 定制层
        write_csv("财务比率.csv", rows)

架构（呼应 finance/_模板/财务数据-README模板.md 规格）:
  - **通用底 = 本文件 compute_common_ratios()**: 全公司共有比率（毛利/净利/费用率/ROE/周转/资产结构%/
    OCF·Capex比/应收占营收/存货占营收/资产负债率/分红率/利润链纵深）。跨准则靠科目别名层, 单位无关。
  - **定制层 = 各公司 _build_from_pdf.py**: 行业特有（茅台消费税负担率、白酒合同负债蓄水池、
    港股扣非估算…）。derived 对扣非: 有 A股披露行则算, 否则标 n/a 由该公司 build 自估。
  - 输出唯一文件 财务比率.csv, 唯一写者 = 各公司 build（build 调本函数 + 加定制行）。
  - 符号约定: A股营业成本/费用=正数、港股=负数 → 派生一律取 abs。
"""
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 科目别名(前缀匹配·港股 IFRS 中文 / A股 CAS 都覆盖)。取第一个命中的行。
ALIASES = {
    "营收":   ["营业总收入", "营业收入", "收益 Revenue", "收益", "营业额"],
    "成本":   ["营业成本", "销售成本", "减：营业成本"],
    "毛利":   ["毛利 ", "毛利"],
    "销售费用": ["销售费用", "销售及分销开支", "减：销售费用"],
    "管理费用": ["管理费用", "行政开支", "减：管理费用"],  # 港股「行政开支」≈ A股「管理费用」
    "研发费用": ["研发费用", "减：研发费用", "研发开支"],
    "净利润": ["净利润 ", "净利润", "四、净利润", "五、净利润", "年内溢利"],
    "归母":   ["归属于母公司股东的净利润", "归属于母公司所有者的净利润", "归属于上市公司股东的净利润",
              "母公司拥有人应占溢利", "归母净利润"],
    "扣非归母": ["扣除非经常性损益后的净利润", "归属于母公司股东的扣除非经常性损益的净利润",
              "扣非归母", "扣非净利润"],
    "税前":   ["利润总额", "三、利润总额", "除税前溢利", "税前利润"],
    "所得税": ["所得税费用", "减：所得税费用", "所得税开支"],
    "应收":   ["应收账款", "贸易应收款项及应收票据", "贸易应收款", "应收票据及应收账款", "应收账款及应收票据"],
    "存货":   ["存货"],
    "应付":   ["应付账款", "应付票据及应付账款", "贸易应付款项及应付票据", "贸易应付款"],
    "预付":   ["预付款项", "预付账款"],
    "PPE":    ["固定资产", "物业、厂房及设备", "物业厂房设备", "物业厂房及设备"],
    "资产总计": ["资产总计", "资产总额"],  # 勿加"总资产"——会误配「总资产减流动负债」
    "非流动资产总额": ["非流动资产总额", "非流动资产合计"],
    "流动资产总额": ["流动资产总额", "流动资产合计"],
    "权益合计": ["所有者权益合计", "股东权益合计", "所有者权益（或股东权益）合计", "权益总额", "总权益"],
    "归母权益": ["归属于母公司所有者权益合计", "归属于母公司股东权益合计", "归属于母公司股东的权益合计",
              "母公司拥有人应占权益", "归母权益"],
    "OCF":    ["经营活动产生的现金流量净额", "经营活动现金流量净额", "经营活动所得现金流量净额",
              "经营活动所得现金净额"],
    "capex":  ["购建固定资产、无形资产和其他长期资产支付的现金", "购买物业厂房设备项目", "购买物业厂房设备",
              "购建固定资产"],
    "分红":   ["分配股利、利润或偿付利息支付的现金", "已付股息", "分配股利"],
}
# 现金及金融资产类(前缀·求和·尽力而为)
CASH_KEYS = ["货币资金", "现金及银行结余", "现金及现金等价物", "交易性金融资产", "FVTPL金融资产",
             "长期银行存款", "结构性存款", "受限资金", "质押存款", "受限现金", "定期存款",
             "债权投资", "其他债权投资"]


def load_table(path):
    """读一张三表 CSV → (years:list[int], rows:dict{科目全名: [float|None]})。跳过注释行, 以「科目」行为表头。"""
    with open(path, encoding="utf-8-sig") as f:  # utf-8-sig 兼容带 BOM 的 CSV
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
    """按别名前缀取一行; 未匹配则记入 unmatched。"""
    for name in ALIASES[key]:
        for k, v in rows.items():
            if k.startswith(name):
                return v
    unmatched.append(key)
    return None


def compute_common_ratios(PL, BS, CF):
    """**通用底**：从三表 dict 算全公司共有的派生比率。

    入参 PL/BS/CF = dict{科目全名: [每期值 float|None]}（各公司 build 传 dict(利润表) 等）。
    返回 (rows, unmatched):
      rows = [(名, [每期值 float|None], fmt)]; fmt ∈ pct/day/x/na（供 CLI 显示; 写 CSV 时取 [:2]）。
    """
    unmatched = []
    N = len(next(iter(PL.values()))) if PL else 0

    def g(rows, key):
        return pick(rows, key, unmatched)

    rev, cos = g(PL, "营收"), g(PL, "成本")
    gross = pick(PL, "毛利", [])            # 无毛利行(A股)则从 营收-abs(成本) 算, 不报未匹配
    snd, adm = pick(PL, "销售费用", []), pick(PL, "管理费用", [])
    rnd = pick(PL, "研发费用", [])          # 港股常不单列 → 无则不出该行
    npr, parent, kf = g(PL, "净利润"), g(PL, "归母"), g(PL, "扣非归母")
    ar, inv, ap, prepay, ppe = g(BS, "应收"), g(BS, "存货"), g(BS, "应付"), g(BS, "预付"), g(BS, "PPE")
    eq_total = g(BS, "权益合计")
    eq_parent = pick(BS, "归母权益", [])    # 可选, ROE 优先归母权益、退回总权益
    ocf, capex, div = g(CF, "OCF"), g(CF, "capex"), g(CF, "分红")
    ta_line = pick(BS, "资产总计", [])      # 无此行(港股)则回退 非流动+流动
    nca, ca = pick(BS, "非流动资产总额", []), pick(BS, "流动资产总额", [])
    eq_use = eq_parent or eq_total

    def val(row, i):
        return None if row is None or row[i] is None else row[i]

    def ta(i):
        if ta_line and ta_line[i] is not None:
            return ta_line[i]
        if nca and ca and nca[i] is not None and ca[i] is not None:
            return nca[i] + ca[i]
        return None

    def gp(i):
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

    def d(a, b):
        if a is None or b in (None, 0):
            return None
        return a / b

    def absr(row, i):  # 费用/capex 取绝对值(跨符号约定)
        v = val(row, i)
        return None if v is None else abs(v)

    def days(bal_avg, base_flow):
        if bal_avg is None or base_flow in (None, 0):
            return None
        return 365 * bal_avg / abs(base_flow)

    R = []
    # —— 基础
    R.append(("毛利率 Gross margin", [d(gp(i), val(rev, i)) for i in range(N)], "pct"))
    R.append(("净利率 Net margin", [d(val(npr, i), val(rev, i)) for i in range(N)], "pct"))
    R.append(("销售费用率 S&D exp ratio", [d(absr(snd, i), val(rev, i)) for i in range(N)], "pct"))
    R.append(("管理/行政费用率 Admin exp ratio", [d(absr(adm, i), val(rev, i)) for i in range(N)], "pct"))
    if rnd is not None:  # 港股多不单列研发 → 无则不出
        R.append(("研发费用率 R&D exp ratio", [d(absr(rnd, i), val(rev, i)) for i in range(N)], "pct"))
    R.append(("ROE(期末) Return on year-end equity", [d(val(parent, i), val(eq_use, i)) for i in range(N)], "pct"))
    R.append(("ROE(年均) Return on avg equity",
              [None] + [d(val(parent, i), (val(eq_use, i) + val(eq_use, i - 1)) / 2)
                        if val(eq_use, i) is not None and val(eq_use, i - 1) is not None else None
                        for i in range(1, N)], "pct"))
    R.append(("经营现金流/净利 OCF/Net profit", [d(val(ocf, i), val(npr, i)) for i in range(N)], "x"))
    R.append(("Capex/净利 Capex/Net profit", [d(absr(capex, i), val(npr, i)) for i in range(N)], "x"))
    R.append(("应收/营收 AR/Revenue", [d(val(ar, i), val(rev, i)) for i in range(N)], "pct"))
    R.append(("存货/营收 Inventory/Revenue", [d(val(inv, i), val(rev, i)) for i in range(N)], "pct"))
    R.append(("资产负债率 Liabilities/Total assets",
              [d(ta(i) - val(eq_total, i), ta(i)) if ta(i) is not None and val(eq_total, i) is not None else None
               for i in range(N)], "pct"))
    # —— 利润链纵深
    R.append(("归母/净利 Parent/Net profit", [d(val(parent, i), val(npr, i)) for i in range(N)], "pct"))
    if kf:
        R.append(("扣非净利率 Adj net margin", [d(val(kf, i), val(rev, i)) for i in range(N)], "pct"))
    else:
        R.append(("扣非净利率(估) Adj net margin est", [None] * N, "na"))  # 港股无扣非线, 该公司 build 自估
    # —— 周转效率(天·期初期末均值; 首期期末)
    R.append(("应收账款周转天数 AR turnover days", [days(avg(ar, i), val(rev, i)) for i in range(N)], "day"))
    R.append(("存货周转天数 Inventory turnover days", [days(avg(inv, i), val(cos, i) if cos else None) for i in range(N)], "day"))
    R.append(("应付账款周转天数 AP turnover days", [days(avg(ap, i), val(cos, i) if cos else None) for i in range(N)], "day"))
    # —— 资产结构画像(占总资产%)
    R.append(("现金及金融资产/总资产 Cash&financial/TA", [d(cashfin(i), ta(i)) for i in range(N)], "pct"))
    R.append(("固定资产PPE/总资产 PPE/TA", [d(val(ppe, i), ta(i)) for i in range(N)], "pct"))
    R.append(("存货/总资产 Inventory/TA", [d(val(inv, i), ta(i)) for i in range(N)], "pct"))
    rp = [((val(ar, i) or 0) + (val(prepay, i) or 0)) if (ar or prepay) else None for i in range(N)]
    R.append(("(应收+预付)/总资产 Receivables&prepay/TA", [d(rp[i], ta(i)) for i in range(N)], "pct"))
    # —— 股东回报
    R.append(("当年分红率 Payout ratio", [d(absr(div, i), val(parent, i)) for i in range(N)], "pct"))
    return R, unmatched


def main():
    if len(sys.argv) < 2:
        print("用法: python3 scripts/derived.py <公司>", file=sys.stderr)
        sys.exit(1)
    company = sys.argv[1]
    base = os.path.join(ROOT, "finance", company, "财务数据")
    if not os.path.isdir(base):
        print(f"[derived] 找不到 {base}", file=sys.stderr)
        sys.exit(1)
    tabs = {}
    for fn in ["利润表.csv", "资产负债表.csv", "现金流量表.csv"]:
        p = os.path.join(base, fn)
        if not os.path.exists(p):
            print(f"[derived] 缺 {fn}", file=sys.stderr)
            sys.exit(1)
        tabs[fn] = load_table(p)
    years = tabs["利润表.csv"][0]
    R, unmatched = compute_common_ratios(tabs["利润表.csv"][1], tabs["资产负债表.csv"][1], tabs["现金流量表.csv"][1])

    print(f"# {company} 通用派生比率(derived.py·只读) · {years[0]}-{years[-1]} · {len(R)} 项")
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
            else:
                cells.append(f"{v:.2f}".rjust(w))
        print(name.ljust(30) + "".join(cells))
    if unmatched:
        print("\n⚠️ 未匹配科目(相关比率为 —, 需补别名或该公司科目命名特殊):", "、".join(sorted(set(unmatched))))
    print("注: 这是【通用底】——各公司行业特有比率(消费税负担率/合同负债蓄水池/扣非估…)在该公司 _build_from_pdf.py 加。")
    print("注: A股分红行含付息, 分红率偏高; 扣非——A股取披露值、港股 n/a 由 build 自估。")


if __name__ == "__main__":
    main()
