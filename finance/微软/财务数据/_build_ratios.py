#!/usr/bin/env python3
"""财务比率层（FY1982-2026）：通用底（scripts/derived.py）+ Microsoft 定制层 → `财务比率.csv`；
另出 `同口径增速.csv`（分部 / 产品线：只用**同一份 10-K** 的本年与比较年）。全部为派生值，**校验不过不写出**。

## 为什么增速不用相邻两年的 as-reported 相除
as-reported 序列跨重述断点不可比：FY2018 10-K 按 ASC 606 全面追溯，FY2017 营收从 899.5 亿改成 965.7 亿——
直接拿 FY2018 as-reported ÷ FY2017 as-reported 得 +22.7%，同口径（同一份 10-K 两列）只有 +14.3%。
所以「增速」一律 = 本年自家 10-K 的本年列 ÷ **同一份 10-K** 的上年比较列 − 1。

## 拆股复权：从数据自证，再与公司自陈对账
相邻两份年报对**同一财年**印的股数之比 = 两次申报之间发生的拆股倍数（无股数行时用「净利 ÷ EPS」的隐含股数，
可抵消净利重述，如 FY2004 10-K 按 SFAS 123 追溯调减 FY2002-2003 净利）。推出的拆股链必须与 10-K 自陈的
拆股记录逐次相符（FY1994/1995/1997/1998/1999/2000/2003 10-K 原文 + FY1987、FY1990 年报股数翻倍），否则失败。

## 校验
- 探针行：读入的每个 CSV 行名必须存在（防上游改名后静默取空）；
- MUST：关键比率在应有年份必须有值（防「取不到 → 全空 → 不写」的静默截断，记忆 chained-builder-silent-truncation）；
- 拆股链 = 自陈清单；同口径增速表每份申报每年的合计 = 该申报合并营收。
"""
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, HERE)
import derived                    # noqa: E402
import _build_from_filings as bf  # noqa: E402

Y = list(range(1982, 2027))
NI = "净利润 Net income"
REV = "营业收入 Revenue"
OI = "营业利润 Operating income"
OCF = "经营活动现金流净额 Net cash from operations"
SH_ROWS = ["摊薄股数(百万股·as-reported) Diluted shares", "加权股数(SFAS128前·含等价物·百万股) Average shares (primary)",
           "基本股数(百万股·as-reported) Basic shares"]
EPS_ROWS = ["摊薄EPS(as-reported·拆股基准随年变) Diluted EPS",
            "每股收益(SFAS128前·primary·as-reported) Net income per share (primary)",
            "基本EPS(as-reported·拆股基准随年变) Basic EPS"]
DPS = "每股宣派股息(as-reported) Cash dividends declared per share"

# 公司自陈的拆股（申报间隔 → 倍数, 原文出处）。FY1987、FY1990 两次在扫描年报里（无文本层），以股数翻倍为证
DISCLOSED = {
    ("S1986", "S1987"): (2.0, "1987-09 一拆二：FY1987 年报全部股数/EPS 较 FY1986 年报同年翻倍/减半（扫描件数据自证）"),
    ("S1989", "S1990"): (2.0, "1990-04 一拆二：FY1990 年报股数较 FY1989 年报同年翻倍（扫描件数据自证）"),
    ("S1990", "S1991"): (1.5, "1991-06 三拆二：FY1995 10-K 附件「three-for-two stock splits in 1991 and 1992」"),
    ("S1991", "S1992"): (1.5, "1992-06 三拆二：同上"),
    ("S1993", "L1994"): (2.0, "1994-05 一拆二：FY1994 10-K 附件「2-for-1 stock split in May 1994」"),
    ("L1996", "L1997"): (2.0, "1996-12 一拆二：FY1997 10-K 附件「2-for-1 stock splits in May 1994 and November 1996」、FY2000 10-K 写作 December 1996"),
    ("L1997", "L1998"): (2.0, "1998-02 一拆二：FY1998 10-K「In February 1998, outstanding shares of common stock were split two-for-one」"),
    ("L1998", "L1999"): (2.0, "1999-03 一拆二：FY1999 10-K「During March 1999, outstanding shares of common stock were split two-for-one」"),
    ("L2002", "L2003"): (2.0, "2003-02 一拆二：FY2003 10-K Note 2「In February 2003, outstanding shares of our common stock were split two-for-one」"),
}


# ═════════════════════════ 读 CSV ═════════════════════════
def load(name, need=()):
    with open(os.path.join(HERE, name)) as f:
        rows = list(csv.reader(f))
    h = next(i for i, r in enumerate(rows) if r and r[0] == "科目")
    years = [int(c[2:]) for c in rows[h][1:] if c.startswith("FY")]
    out = {}
    for r in rows[h + 1:]:
        if not r or not r[0].strip():
            break                                   # 空行之后是附表（定义沿革/锚句），不是本表
        if r[0] == "数据来源":
            continue
        d = {}
        for y, v in zip(years, r[1:]):
            try:
                d[y] = float(v)
            except ValueError:
                pass
        out[r[0]] = d
    miss = [n for n in need if n not in out]
    if miss:
        raise SystemExit(f"❌ 探针行缺失 {name}：{miss}（上游 CSV 改了行名？）")
    return out


def g(t, row, y):
    return t.get(row, {}).get(y)


def div(a, b):
    return None if a is None or b in (None, 0) else a / b


def add(*xs):
    return None if any(x is None for x in xs) else sum(xs)


# ═════════════════════════ 拆股链 ═════════════════════════
def filing_order(books):
    order = [("S", "prospectus")] + [("S", str(y)) for y in bf.SYEARS] + \
            [("L", str(y)) for y in bf.LYEARS] + [("R", str(y)) for y in bf.RYEARS]
    return [s for s in order if s in books and books[s].get("IS")]


def is_years(books, src):
    st = books[src]["IS"]
    if src[0] in ("L", "S"):
        return list(st["years"])
    return [y for y in range(1980, 2027) if bf.col_index(st, y, "R") is not None]


def label(src):
    return "招股书" if src[1] == "prospectus" else f"{src[0]}{src[1]}"


def pair_ratio(da, db):
    """相邻两份申报（a 早 b 晚）对同一财年的股本口径之比 b/a。→ [(年, 方法, 比值, 容差)]"""
    out = []
    for y in sorted(set(da) & set(db), reverse=True):
        A, B = da[y], db[y]
        got = None
        for nm in SH_ROWS:                                           # ① 同名股数行
            if A.get(nm) and B.get(nm):
                got = (y, f"股数·{nm[:6]}", B[nm] / A[nm], 0.02)
                break
        if not got:
            for nm in EPS_ROWS:                                      # ② 同名 EPS → 隐含股数 = 净利÷EPS
                if A.get(nm) and B.get(nm) and A.get(NI) and B.get(NI):
                    tol = 0.006 / min(abs(A[nm]), abs(B[nm])) + 0.01
                    got = (y, f"净利÷EPS·{nm[:6]}", (B[NI] / B[nm]) / (A[NI] / A[nm]), tol)
                    break
        if not got:                                                  # ③ 跨口径（SFAS 128：primary ↔ diluted）
            sa = next((A[n] for n in SH_ROWS if A.get(n)), None)
            sb = next((B[n] for n in SH_ROWS if B.get(n)), None)
            if sa and sb:
                got = (y, "股数·跨口径", sb / sa, 0.05)
            else:
                ea = next((A[n] for n in EPS_ROWS if A.get(n)), None)
                eb = next((B[n] for n in EPS_ROWS if B.get(n)), None)
                if ea and eb and A.get(NI) and B.get(NI):
                    got = (y, "净利÷EPS·跨口径", (B[NI] / eb) / (A[NI] / ea), 0.006 / min(abs(ea), abs(eb)) + 0.05)
        if got:
            out.append(got)
    return out


def split_chain(books):
    order = filing_order(books)
    data = {s: {y: bf.extract(books, s, "IS", y) for y in is_years(books, s)} for s in order}
    gaps, bad = [], []
    for a, b in zip(order, order[1:]):
        cands = pair_ratio(data[a], data[b])
        if not cands:
            bad.append(f"{label(a)}→{label(b)}：无共同年份可比股本")
            continue
        ks = set()
        for y, how, r, tol in cands:
            k = min((1.0, 1.5, 2.0, 3.0), key=lambda x: abs(r / x - 1))
            if abs(r / k - 1) > tol:
                bad.append(f"{label(a)}→{label(b)} FY{y} {how} 比值 {r:.4f} 不接近任何拆股倍数")
            ks.add(k)
        if len(ks) > 1:
            bad.append(f"{label(a)}→{label(b)} 各年推出的倍数不一致：{sorted(ks)} {cands}")
        k = max(ks)
        gaps.append((a, b, k, cands[0]))
    found = {(label(a), label(b)): k for a, b, k, _ in gaps if k != 1.0}
    want = {key: v[0] for key, v in DISCLOSED.items()}
    if found != want:
        bad.append(f"推出的拆股链 ≠ 公司自陈：多出 {set(found.items()) - set(want.items())}、"
                   f"缺少 {set(want.items()) - set(found.items())}")
    idx = {s: i for i, s in enumerate(order)}
    fac = {}
    for y in Y:
        src = bf.own_source(books, "IS", y)
        if src is None:
            continue
        m = 1.0
        for a, b, k, _ in gaps:
            if idx[a] >= idx[src]:
                m *= k
        fac[y] = m
    return fac, gaps, bad


# ═════════════════════════ 每股股息（宣派·各年自家 10-K）═════════════════════════
def dps_series(books):
    """每股宣派股息 as-reported（首次派息 = FY2003 每股 0.08）。取数优先级（均为**自家** 10-K）：
      ① 利润表「Cash dividends declared per (common) share」行（FY2005-2018 印在利润表）；
      ② FY2011+ R 文件「Dividends Declared (Detail)」全年列（季度列也叫 Jun. 30，全年列在后 → 取最后一个匹配）；
      ③ 五年摘要（只剩 FY2003-2004 需要它）。
    🔴 旧版 FY2004/FY2005 10-K 五年摘要的年份表头被解析错位（FY2005 表把 FY2003/2004 的 0.08/0.16 记到 2004/2005 列），
       所以每个值都要求**另一份申报的利润表或股息附注**印出同值，否则失败——不能单靠一张摘要表。"""
    import json
    detail = {}                                               # 申报 → {财年: 值}
    for fy in bf.RYEARS:
        d = json.load(open(os.path.join(bf.RDIR, f"{fy}.json")))
        t = next((v for k, v in d["details"].items() if re.search(r"^dividends declared \(detail", k, re.I)), None)
        if not t:
            continue
        row = next((r for r in t["rows"] if re.search(r"dividends? per share", r["label"], re.I)), None)
        if not row:
            continue
        for y in (fy - 2, fy - 1, fy):
            cols = [i for i, p in enumerate(t["periods"]) if re.match(rf"Jun\. 30, {y}$", p.strip())]
            if cols and cols[-1] < len(row["vals"]) and row["vals"][cols[-1]] is not None:
                detail.setdefault(("R", str(fy)), {})[y] = row["vals"][cols[-1]]
    # 股东权益变动表里同一份申报也印一次（R 文件该表无期间表头，三行按年份先后排 → 最后一行 = 本年）。
    # 只给**最新一年**当佐证用：最新年份没有后一份申报可比，同一份 10-K 两处独立印刷是能拿到的最强证据
    eq_own = {}
    for fy in bf.RYEARS:
        st = books.get(("R", str(fy)), {}).get("EQ")
        rows = [r for r in (st or {}).get("rows", []) if re.search(r"^cash dividends declared per common share$",
                                                                   bf.norm(r["label"])) and r["vals"] and r["vals"][0] is not None]
        if rows:
            eq_own[fy] = rows[-1]["vals"][0]
    is_dps = {}                                               # 申报 → {财年: 利润表 DPS}
    for s in filing_order(books):
        for y in is_years(books, s):
            v = bf.extract(books, s, "IS", y).get(DPS)
            if v is not None:
                is_dps.setdefault(s, {})[y] = v
    out, src, bad = {}, {}, []
    for fy in range(2003, 2027):
        own = bf.own_source(books, "IS", fy)
        cands = [(is_dps.get(own, {}).get(fy), "利润表"), (detail.get(own, {}).get(fy), "股息附注")]
        if fy <= 2004:
            st = books.get(own, {}).get("SUM")
            if st and fy in st["years"]:
                i = st["years"].index(fy)
                r = next((r for r in st["rows"] if re.search(r"cash dividends (declared )?per (common )?share", r["label"], re.I)
                          and i < len(r["vals"]) and r["vals"][i] is not None), None)
                cands.append((r["vals"][i] if r else None, "五年摘要"))
        v, how = next(((v, h) for v, h in cands if v is not None), (None, None))
        if v is None:
            bad.append(f"FY{fy} 每股股息：自家 10-K 取不到")
            continue
        others = [(s, x) for tab in (is_dps, detail) for s, d in tab.items() if s != own and fy in d for x in (d[fy],)]
        if fy == max(bf.RYEARS) and fy in eq_own:
            others.append((("EQ", str(fy)), eq_own[fy]))
        if not any(abs(x - v) <= 0.005 for _, x in others):
            bad.append(f"FY{fy} 每股股息 {v}（{label(own)}{how}）无其他申报同值佐证：{others}")
        conflict = [(label(s), x) for s, x in others if abs(x - v) > 0.005]
        if conflict:
            bad.append(f"FY{fy} 每股股息 {v} 与其他申报不一致：{conflict}")
        out[fy], src[fy] = v, f"{label(own)}{how}"
    return out, src, bad


# ═════════════════════════ 同口径增速 ═════════════════════════
def same_filing_growth(books, key, rows):
    """→ {row: {fy: 本年自家申报本年列 ÷ 同一份申报上年列 − 1}}"""
    out = {r: {} for r in rows}
    for y in Y:
        src = bf.own_source(books, key, y)
        if not src or not bf.has_year(books, src, key, y - 1):
            continue
        cur, prev = bf.extract(books, src, key, y), bf.extract(books, src, key, y - 1)
        for r in rows:
            if cur.get(r) is not None and prev.get(r):
                out[r][y] = cur[r] / prev[r] - 1 if prev[r] > 0 else None
    return out


def views_growth():
    """分部 / 产品线：每份 10-K 自身年 vs 同一份 10-K 的上年比较列。"""
    def read(name, ncols):
        rows = []
        with open(os.path.join(HERE, name)) as f:
            rd = csv.reader(f)
            for r in rd:
                if not r or r[0].startswith("#"):
                    if rows and not r:
                        break
                    continue
                if r[0].startswith("申报"):
                    continue
                rows.append(r[:ncols])
        return rows

    seg = read("分部-各申报口径.csv", 5)
    prod = read("分产品营收-各申报口径.csv", 4)
    out = []
    for kind, rows, has_oi in (("分部", seg, True), ("产品线", prod, False)):
        tab = {}
        for r in rows:
            s, fy, nm = int(r[0][2:]), int(r[1][2:]), r[2]
            rv = float(r[3]) if r[3] else None
            oi = float(r[4]) if has_oi and r[4] else None
            tab[(s, fy, nm)] = (rv, oi)
        for (s, fy, nm), (rv, oi) in sorted(tab.items()):
            if fy != s:
                continue
            prv, poi = tab.get((s, s - 1, nm), (None, None))
            out.append((kind, s, nm, rv, prv, div(rv, prv) - 1 if div(rv, prv) is not None and prv > 0 else None,
                        oi, poi, div(oi, poi) - 1 if div(oi, poi) is not None and poi > 0 else None,
                        div(oi, rv)))
    return out


# ═════════════════════════ 主流程 ═════════════════════════
def main():
    I = load("利润表.csv", [REV, "营业成本 Cost of revenue", OI, NI, "税前利润 Income before income taxes",
                           "所得税 Provision for income taxes", "研发费用 Research and development",
                           "销售及市场费用 Sales and marketing", "一般及管理费用 General and administrative",
                           "营业外收支净额 Other income (expense), net"] + SH_ROWS + EPS_ROWS + [DPS])
    B = load("资产负债表.csv", ["现金及现金等价物 Cash and cash equivalents", "短期投资 Short-term investments",
                             "现金及短期投资合计 Cash, cash equivalents, and short-term investments",
                             "应收账款净额 Accounts receivable, net", "存货 Inventories", "应付账款 Accounts payable",
                             "固定资产净额 Property and equipment, net", "总资产 Total assets",
                             "股东权益合计 Total stockholders' equity", "流动资产合计 Total current assets",
                             "流动负债合计 Total current liabilities", "短期借款/商业票据 Short-term debt",
                             "一年内到期长期债务 Current portion of long-term debt", "长期债务 Long-term debt",
                             "应付票据(仅FY1987-1992) Notes payable", "资本租赁义务(仅FY1986-1987) Capital lease obligations",
                             "商誉 Goodwill", "无形资产净额 Intangible assets, net", "股权及其他投资 Equity (and other) investments",
                             "短期递延收入 Short-term unearned revenue", "长期递延收入 Long-term unearned revenue"])
    C = load("现金流量表.csv", [OCF, "资本开支 Additions to property and equipment", "支付普通股股息 Common stock cash dividends paid",
                             "回购股票 Common stock repurchased", "发行股票 Common stock issued",
                             "股权激励费用 Stock-based compensation", "折旧摊销及其他 Depreciation, amortization, and other", NI])
    PPE = load("固定资产明细.csv", ["折旧费用(年度) Depreciation expense"])
    LS = load("租赁与承诺.csv", ["融资租赁负债合计 Finance lease liabilities", "经营租赁负债合计 Operating lease liabilities",
                               "🔴 已签未起租租赁合计(主要为数据中心) Leases not yet commenced",
                               "新增融资租赁使用权资产(非现金取得·不在资本开支内) ROU assets obtained · finance"])
    UE = load("递延收入与RPO.csv", ["剩余履约义务 RPO(总)", "剩余履约义务 RPO(商业客户)"])
    SR = load("分部营收.csv", ["G6·Productivity and Business Processes", "G6·Intelligent Cloud", "G6·More Personal Computing"])
    SO = load("分部经营利润.csv", ["G6·Productivity and Business Processes", "G6·Intelligent Cloud", "G6·More Personal Computing"])
    EMP = load("员工人数.csv", ["员工人数 Employees"])
    OA = load("OpenAI敞口.csv", ["调整后净利润(非GAAP) Adjusted net income", "净利润(报告) Net income"])
    OIE = load("营业外收支明细.csv", ["利息费用 Interest expense", "利息及股息收入 Interest and dividends income"])

    books = bf.load()
    bf.apply_errata(books)
    fac, gaps, bad = split_chain(books)

    # ── 通用底（derived.py）：把本库行名适配成它认的别名 ──
    def lst(t, row):
        return [g(t, row, y) for y in Y]

    def cash_sti(y):
        tot = g(B, "现金及短期投资合计 Cash, cash equivalents, and short-term investments", y)
        if tot is not None:
            return tot
        a, b = g(B, "现金及现金等价物 Cash and cash equivalents", y), g(B, "短期投资 Short-term investments", y)
        return add(a, b)

    PL = {"营业收入": lst(I, REV), "营业成本": lst(I, "营业成本 Cost of revenue"), "毛利": lst(I, "毛利 Gross margin"),
          "销售费用": lst(I, "销售及市场费用 Sales and marketing"), "管理费用": lst(I, "一般及管理费用 General and administrative"),
          "研发费用": lst(I, "研发费用 Research and development"), "净利润": lst(I, NI),
          "归母净利润": lst(I, NI),                       # 无少数股东损益：报告净利即归属普通股东口径
          "税前利润": lst(I, "税前利润 Income before income taxes"), "所得税费用": lst(I, "所得税 Provision for income taxes")}
    BSd = {"应收账款": lst(B, "应收账款净额 Accounts receivable, net"), "存货": lst(B, "存货 Inventories"),
           "应付账款": lst(B, "应付账款 Accounts payable"), "固定资产": lst(B, "固定资产净额 Property and equipment, net"),
           "资产总计": lst(B, "总资产 Total assets"), "股东权益合计": lst(B, "股东权益合计 Total stockholders' equity"),
           "流动资产合计": lst(B, "流动资产合计 Total current assets"),
           "货币资金": [cash_sti(y) for y in Y]}       # 现金及短期投资合计（只给这一行，免得与分项重复相加）
    CFd = {"经营活动现金流净额": lst(C, OCF), "capex": lst(C, "资本开支 Additions to property and equipment"),
           "已付股息": lst(C, "支付普通股股息 Common stock cash dividends paid")}
    common, unmatched = derived.compute_common_ratios(PL, BSd, CFd)
    unmatched = [u for u in unmatched if u not in ("扣非归母", "预付")]   # 美股无扣非；无单列预付（含在其他流动资产）
    if unmatched:
        bad.append(f"通用底别名未匹配：{unmatched}")

    R = []                                     # (行名, {fy: v}, 格式) 格式 ∈ r(比率 4 位) / m(金额 1 位) / e(每股 4 位) / x(倍数)

    def put(name, fn, kind="r"):
        d = {}
        for y in Y:
            try:
                v = fn(y)
            except (TypeError, ZeroDivisionError):
                v = None
            if v is not None:
                d[y] = v
        R.append((name, d, kind))
        return d

    for name, vals, f in common:
        if any(v is not None for v in vals):
            R.append((name if name != "当年分红率 Payout ratio" else "当年分红率(已付股息÷净利) Payout ratio",
                      {y: v for y, v in zip(Y, vals) if v is not None}, "r"))

    rev = lambda y: g(I, REV, y)                                                       # noqa: E731
    ni = lambda y: g(I, NI, y)                                                         # noqa: E731
    ocf = lambda y: g(C, OCF, y)                                                       # noqa: E731
    capex = lambda y: None if g(C, "资本开支 Additions to property and equipment", y) is None else \
        -g(C, "资本开支 Additions to property and equipment", y)                       # noqa: E731  转为正数
    sbc = lambda y: g(C, "股权激励费用 Stock-based compensation", y)                    # noqa: E731

    # ① 增长（同一份年报本年 ÷ 上年比较列）
    gi = same_filing_growth(books, "IS", [REV, OI, NI])
    gc = same_filing_growth(books, "CF", [OCF])
    R.append(("营收增速(同一份年报本年÷上年) Revenue growth, same-filing basis", gi[REV], "r"))
    R.append(("营业利润增速(同一份年报) Operating income growth", gi[OI], "r"))
    R.append(("净利润增速(同一份年报) Net income growth", gi[NI], "r"))
    R.append(("经营现金流增速(同一份年报) OCF growth", gc[OCF], "r"))
    # 同口径链式指数：把每年「同一份年报」的增速连乘 → 任两年之比 = 跨重述断点的同口径累计增长
    for key, src, nm in ((REV, gi, "营收"), (OI, gi, "营业利润"), (NI, gi, "净利润"), (OCF, gc, "经营现金流")):
        idx, v = {}, 1.0
        base = 1986 if key != OCF else 1987
        idx[base] = 1.0
        for y in range(base + 1, 2027):
            if src[key].get(y) is None:
                break
            v *= 1 + src[key][y]
            idx[y] = v
        R.append((f"{nm}同口径链式指数(FY{base}=1·同一份年报增速连乘) {nm} chained index", idx, "x"))
    adj = lambda y: g(OA, "调整后净利润(非GAAP) Adjusted net income", y)              # noqa: E731
    put("调整后净利增速(剔除OpenAI·公司非GAAP口径·FY2025起) Adjusted NI growth ex-OpenAI",
        lambda y: div(adj(y), adj(y - 1)) - 1 if div(adj(y), adj(y - 1)) is not None else None)

    # ② 利润率与税
    put("营业利润率 Operating margin", lambda y: div(g(I, OI, y), rev(y)))
    put("营业外收支/税前利润 Non-operating share of pre-tax income",
        lambda y: div(g(I, "营业外收支净额 Other income (expense), net", y), g(I, "税前利润 Income before income taxes", y)))
    put("实际所得税率(派生=所得税÷税前) Effective tax rate",
        lambda y: div(g(I, "所得税 Provision for income taxes", y), g(I, "税前利润 Income before income taxes", y)))
    put("调整后净利率(剔除OpenAI) Adjusted net margin ex-OpenAI", lambda y: div(adj(y), rev(y)))
    for seg, short in (("Productivity and Business Processes", "生产力与业务流程"), ("Intelligent Cloud", "智能云"),
                       ("More Personal Computing", "更多个人计算")):
        put(f"分部经营利润率·{short}(as-reported·FY2020/FY2025 重划) {seg} margin",
            lambda y, s=seg: div(g(SO, f"G6·{s}", y), g(SR, f"G6·{s}", y)))

    # ③ 现金与资本开支
    put("自由现金流 FCF = 经营现金流 − 资本开支(mn)", lambda y: add(ocf(y), -capex(y)) if capex(y) is not None else None, "m")
    put("FCF/净利 FCF / net income", lambda y: div(add(ocf(y), -capex(y)), ni(y)) if capex(y) is not None else None)
    put("资本开支/营收 Capex / revenue", lambda y: div(capex(y), rev(y)))
    put("资本开支/经营现金流 Capex / OCF", lambda y: div(capex(y), ocf(y)))
    put("资本开支/折旧摊销及其他(现金流量表口径) Capex / D&A and other",
        lambda y: div(capex(y), g(C, "折旧摊销及其他 Depreciation, amortization, and other", y)), "x")
    put("资本开支/折旧费用(附注口径·FY2011起) Capex / depreciation expense",
        lambda y: div(capex(y), g(PPE, "折旧费用(年度) Depreciation expense", y)), "x")
    put("折旧费用/营收(附注口径·FY2011起) Depreciation / revenue",
        lambda y: div(g(PPE, "折旧费用(年度) Depreciation expense", y), rev(y)))
    KPI = load("经营指标(公司口径).csv", ["云收入(as-reported·各年自家10-K) Commercial cloud→Microsoft Cloud revenue"])
    put("云收入/营收(公司自定义口径·定义多次变更) Commercial/Microsoft Cloud share of revenue",
        lambda y: div(g(KPI, "云收入(as-reported·各年自家10-K) Commercial cloud→Microsoft Cloud revenue", y), rev(y)))
    fin_new = lambda y: g(LS, "新增融资租赁使用权资产(非现金取得·不在资本开支内) ROU assets obtained · finance", y)  # noqa: E731
    put("资本开支+新增融资租赁(派生·非公司口径·FY2019起)(mn) Capex + finance-lease ROU obtained",
        lambda y: add(capex(y), fin_new(y)), "m")
    put("(资本开支+新增融资租赁)/营收", lambda y: div(add(capex(y), fin_new(y)), rev(y)))
    put("(资本开支+新增融资租赁)/经营现金流", lambda y: div(add(capex(y), fin_new(y)), ocf(y)))
    put("股权激励/营收 SBC / revenue", lambda y: div(sbc(y), rev(y)))
    put("股权激励/净利 SBC / net income", lambda y: div(sbc(y), ni(y)))
    put("FCF − 股权激励(mn) FCF less SBC", lambda y: add(ocf(y), -capex(y), -sbc(y)) if capex(y) is not None else None, "m")

    # ④ 资产负债与承诺
    debt = lambda y: sum(v or 0.0 for v in (                                           # noqa: E731
        g(B, "短期借款/商业票据 Short-term debt", y), g(B, "一年内到期长期债务 Current portion of long-term debt", y),
        g(B, "长期债务 Long-term debt", y), g(B, "应付票据(仅FY1987-1992) Notes payable", y),
        g(B, "资本租赁义务(仅FY1986-1987) Capital lease obligations", y))) if g(B, "总资产 Total assets", y) else None
    put("有息债务合计(短借+一年内到期+长期债务+早年应付票据/资本租赁)(mn) Debt", debt, "m")
    put("净现金(现金及短期投资 − 有息债务)(mn) Net cash", lambda y: add(cash_sti(y), -debt(y)), "m")
    lease_liab = lambda y: add(g(LS, "融资租赁负债合计 Finance lease liabilities", y),        # noqa: E731
                               g(LS, "经营租赁负债合计 Operating lease liabilities", y))
    put("租赁负债合计(融资+经营·表内·FY2019起)(mn) Lease liabilities", lease_liab, "m")
    put("净现金(再扣表内租赁负债·FY2019起)(mn) Net cash after lease liabilities",
        lambda y: add(cash_sti(y), -debt(y), -lease_liab(y)), "m")
    nc = lambda y: g(LS, "🔴 已签未起租租赁合计(主要为数据中心) Leases not yet commenced", y)  # noqa: E731
    put("已签未起租租赁/营收(表外·FY2018起) Leases not yet commenced / revenue", lambda y: div(nc(y), rev(y)))
    put("已签未起租租赁/经营现金流 Leases not yet commenced / OCF", lambda y: div(nc(y), ocf(y)), "x")
    put("RPO/营收(FY2018起) RPO / revenue", lambda y: div(g(UE, "剩余履约义务 RPO(总)", y), rev(y)), "x")

    # 收现近似（美股间接法无「销售商品收到的现金」行）= 营收 + 递延收入净增 − 应收增加；FY1998 起有递延收入现金流行
    def d_unearned(y):
        net = g(C, "递延收入净变动(FY2019起) Unearned revenue (net change)", y)
        if net is not None:
            return net
        a, b = g(C, "递延收入新增(毛额) Deferral of unearned revenue", y), g(C, "递延收入确认 Recognition of unearned revenue", y)
        return add(a, b)
    put("收现近似/营收(派生=营收+递延收入净增+应收变动·间接法·FY1998起) Cash collected proxy / revenue",
        lambda y: div(add(rev(y), d_unearned(y), g(C, "应收账款变动 Accounts receivable", y)), rev(y)))
    put("利息及股息收入/平均(现金+短期投资)(FY2011起) Yield on cash & ST investments",
        lambda y: div(g(OIE, "利息及股息收入 Interest and dividends income", y),
                      None if cash_sti(y) is None or cash_sti(y - 1) is None else (cash_sti(y) + cash_sti(y - 1)) / 2))
    put("递延收入(短+长)/营收 Unearned revenue / revenue",
        lambda y: div(add(g(B, "短期递延收入 Short-term unearned revenue", y) or 0.0,
                          g(B, "长期递延收入 Long-term unearned revenue", y) or 0.0)
                      if g(B, "短期递延收入 Short-term unearned revenue", y) is not None else None, rev(y)))
    put("(商誉+无形资产)/总资产 Goodwill & intangibles / TA",
        lambda y: div((g(B, "商誉 Goodwill", y) or 0.0) + (g(B, "无形资产净额 Intangible assets, net", y) or 0.0),
                      g(B, "总资产 Total assets", y)) if g(B, "商誉 Goodwill", y) is not None else None)
    put("股权及其他投资/总资产 Equity investments / TA",
        lambda y: div(g(B, "股权及其他投资 Equity (and other) investments", y), g(B, "总资产 Total assets", y)))
    put("流动比率 Current ratio", lambda y: div(g(B, "流动资产合计 Total current assets", y),
                                              g(B, "流动负债合计 Total current liabilities", y)), "x")
    put("利息保障倍数(营业利润÷利息费用·FY2011起) Interest coverage",
        lambda y: div(g(I, OI, y), -g(OIE, "利息费用 Interest expense", y)) if g(OIE, "利息费用 Interest expense", y) else None, "x")

    # ⑤ 股东回报（金额取正数）
    bb = lambda y: None if g(C, "回购股票 Common stock repurchased", y) is None else -g(C, "回购股票 Common stock repurchased", y)  # noqa: E731
    iss = lambda y: g(C, "发行股票 Common stock issued", y)                                                       # noqa: E731
    dv = lambda y: -(g(C, "支付普通股股息 Common stock cash dividends paid", y) or 0.0)                          # noqa: E731
    put("回购金额(现金流量表口径·含代扣个税回购)(mn) Buybacks", bb, "m")
    wh = {}
    with open(os.path.join(HERE, "附注自陈数.csv")) as f:
        for r in csv.reader(f):
            if r and r[0].startswith("为员工股票归属代扣个税"):
                wh[int(r[1][2:])] = float(r[2])
    if not wh:
        bad.append("探针：附注自陈数.csv 无「代扣个税回购」行")
    put("  其中：为员工股票归属代扣个税回购(FY2017起·附注自陈)(mn) Withholding repurchases", lambda y: wh.get(y), "m")
    put("  其中：回购计划内回购(派生=回购−代扣个税)(mn) Program repurchases", lambda y: add(bb(y), -wh[y]) if y in wh else None, "m")
    put("(股权激励+代扣个税回购)/营收 SBC incl. withholding / revenue",
        lambda y: div(add(sbc(y), wh[y]), rev(y)) if y in wh else None)
    put("净回购(回购 − 发行股票)(mn) Net buybacks", lambda y: add(bb(y), -iss(y)) if iss(y) is not None else None, "m")
    put("股东回报合计(已付股息+回购)(mn) Dividends + buybacks", lambda y: add(dv(y), bb(y)), "m")
    put("(股息+回购)/净利", lambda y: div(add(dv(y), bb(y)), ni(y)))
    put("(股息+回购)/FCF", lambda y: div(add(dv(y), bb(y)), add(ocf(y), -capex(y))) if capex(y) is not None else None)
    cum = {"ni": 0.0, "dv": 0.0, "bb": 0.0, "iss": 0.0}
    cums = {k: {} for k in cum}
    for y in range(1987, 2027):
        cum["ni"] += g(C, NI, y) or 0.0
        cum["dv"] += dv(y)
        cum["bb"] += bb(y) or 0.0
        cum["iss"] += iss(y) or 0.0
        for k in cum:
            cums[k][y] = cum[k]
    R.append(("累计净利(FY1987起·现金流量表口径)(mn) Cumulative net income", cums["ni"], "m"))
    R.append(("累计已付股息(FY1987起)(mn)", cums["dv"], "m"))
    R.append(("累计回购(FY1987起)(mn)", cums["bb"], "m"))
    R.append(("累计发行股票(FY1987起·期权行权与员工持股)(mn)", cums["iss"], "m"))
    e86 = g(B, "股东权益合计 Total stockholders' equity", 1986)
    put("股东权益较FY1986末增加(mn) Equity change since FY1986",
        lambda y: g(B, "股东权益合计 Total stockholders' equity", y) - e86 if y >= 1987 else None, "m")
    put("留存缺口(权益增加 − 累计[净利−股息−回购+发行])(mn)：股权激励摊销/期权税收利益/OCI 等",
        lambda y: (g(B, "股东权益合计 Total stockholders' equity", y) - e86)
        - (cums["ni"][y] - cums["dv"][y] - cums["bb"][y] + cums["iss"][y]) if y >= 1987 else None, "m")

    # ⑥ 每股（复权到 FY2026 股本基准）
    R.append(("复权倍数(as-reported 每股数据 ÷ 此数 = FY2026 股本基准) Split factor", fac, "x"))

    def eps_as_rep(y):
        return g(I, EPS_ROWS[0], y) if g(I, EPS_ROWS[0], y) is not None else g(I, EPS_ROWS[1], y)

    def sh_as_rep(y):
        for nm in SH_ROWS[:2]:
            if g(I, nm, y) is not None:
                return g(I, nm, y)
        # FY1998-2000 自家 10-K 利润表不印股数 → 净利 ÷ 摊薄 EPS 的隐含股数（EPS 两位小数·误差 <0.6%）
        return div(ni(y), eps_as_rep(y))

    put("🔴【复权】EPS(FY1997前=primary·FY1998起=摊薄) Split-adjusted EPS",
        lambda y: div(eps_as_rep(y), fac.get(y)), "e")
    put("🔴【复权】加权股数(百万股·FY1997前=primary·FY1998起=摊薄·FY1998-2000 未印→净利÷EPS 隐含) Split-adjusted shares",
        lambda y: sh_as_rep(y) * fac[y] if sh_as_rep(y) is not None and y in fac else None, "m")
    dps, _, bad_dps = dps_series(books)
    bad += bad_dps
    adj_sh = R[-1][1]
    put("🔴【复权】每股宣派股息(FY2003 首次派息·FY2005 含每股 3 美元特别股息) Split-adjusted DPS",
        lambda y: div(dps.get(y), fac.get(y)), "e")
    put("每股股息增速 DPS growth", lambda y: div(dps.get(y), dps.get(y - 1)) - 1 if div(dps.get(y), dps.get(y - 1)) else None)
    put("复权股数同比变化 Share count change", lambda y: div(adj_sh.get(y), adj_sh.get(y - 1)) - 1
        if div(adj_sh.get(y), adj_sh.get(y - 1)) is not None else None)

    # ⑦ 人效（员工为期末约数）
    emp = lambda y: g(EMP, "员工人数 Employees", y)                                    # noqa: E731
    put("人均营收(千美元/人) Revenue per employee", lambda y: div(rev(y) * 1000, emp(y)) if rev(y) else None, "m")
    put("人均营业利润(千美元/人) Operating income per employee",
        lambda y: div(g(I, OI, y) * 1000, emp(y)) if g(I, OI, y) is not None else None, "m")

    # ── MUST：这些格必须有值 ──
    names = {n: d for n, d, _ in R}
    MUST = [("毛利率 Gross margin", range(1982, 2027)), ("营业利润率 Operating margin", range(1982, 2027)),
            ("ROE(年均) Return on avg equity", range(1985, 2027)),
            ("经营现金流/净利 OCF/Net profit", range(1987, 2027)),
            ("自由现金流 FCF = 经营现金流 − 资本开支(mn)", range(1987, 2027)),
            ("营收增速(同一份年报本年÷上年) Revenue growth, same-filing basis", range(1983, 2027)),
            ("净现金(现金及短期投资 − 有息债务)(mn) Net cash", range(1984, 2027)),
            ("🔴【复权】EPS(FY1997前=primary·FY1998起=摊薄) Split-adjusted EPS", range(1982, 2027)),
            ("🔴【复权】加权股数(百万股·FY1997前=primary·FY1998起=摊薄·FY1998-2000 未印→净利÷EPS 隐含) Split-adjusted shares",
             range(1982, 2027)),
            ("人均营收(千美元/人) Revenue per employee", range(1982, 2027)),
            ("资本开支+新增融资租赁(派生·非公司口径·FY2019起)(mn) Capex + finance-lease ROU obtained", range(2019, 2027)),
            ("RPO/营收(FY2018起) RPO / revenue", range(2018, 2027)),
            ("分部经营利润率·智能云(as-reported·FY2020/FY2025 重划) Intelligent Cloud margin", range(2016, 2027)),
            ("资本开支/折旧费用(附注口径·FY2011起) Capex / depreciation expense", range(2011, 2027)),
            ("🔴【复权】每股宣派股息(FY2003 首次派息·FY2005 含每股 3 美元特别股息) Split-adjusted DPS", range(2003, 2027))]
    for nm, yrs in MUST:
        miss = [y for y in yrs if names.get(nm, {}).get(y) is None]
        if miss:
            bad.append(f"MUST 缺格：{nm} @ {miss}")
    # 同口径增速表自洽：每份申报每年分部和/产品线和 = 该申报的合并营收（_build_notes 已校验原表，这里校验读入没截断）
    vg = views_growth()
    for kind, lo in (("分部", 2011), ("产品线", 2011)):
        got = sorted({s for k, s, *_ in vg if k == kind})
        if got != list(range(lo, 2027)):
            bad.append(f"同口径增速·{kind} 申报覆盖 {got[:3]}…{got[-3:]} ≠ FY{lo}-FY2026")

    if bad:
        print(f"🔴 比率层校验未过 {len(bad)} 条（不写出）：")
        for b in bad:
            print("  " + b)
        return 1

    def fmt(v, kind):
        if v is None:
            return ""
        if kind == "r":
            return f"{v:.4f}"
        if kind == "e":
            return f"{v:.4f}"
        if kind == "x":
            return f"{v:.2f}" if abs(v) >= 10 else f"{v:.3f}"
        return f"{v:.1f}"

    with open(os.path.join(HERE, "财务比率.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# 单位: 比率为小数(1=100%)、倍数为倍、金额为百万美元、人效为千美元/人、EPS/股息为美元/股；空 = 所需分项该年不可得。"
                    "**全部为派生值**（年报不直接给），分母口径写在行名里。ROE/ROA 用期初期末平均，故首年为空。"])
        w.writerow(["# 增速一律 = 本年自家 10-K 的本年列 ÷ 同一份 10-K 的上年比较列 − 1（跨 ASC 606 / SFAS 123 等追溯重述断点仍同口径）。"
                    "分部与产品线的同口径增速见 同口径增速.csv。"])
        w.writerow(["# 🔴【复权】行已按本库自证的拆股链折算到 FY2026 股本基准（9 次拆股·累计 ×288），跨年比每股数据只用这几行，"
                    "**不要用 利润表.csv 的 as-reported EPS/股数**。拆股链与公司自陈逐次对账见 README。"])
        w.writerow(["科目"] + [f"FY{y}" for y in Y])
        for name, d, kind in R:
            line = [fmt(d.get(y), kind) for y in Y]
            if any(line):
                w.writerow([name] + line)
    with open(os.path.join(HERE, "同口径增速.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# 单位: 百万美元 / 小数(1=100%) | 本年 = 该 10-K 的本年列，上年 = **同一份 10-K** 的上年比较列 | "
                    "用途：分部重划（FY2020、FY2025）与产品线更名/重划后仍能算同口径增速 | 源：分部-各申报口径.csv、分产品营收-各申报口径.csv"])
        w.writerow(["类别", "申报(10-K 财年)", "名称(该申报印刷名)", "本年营收", "上年营收(同申报)", "营收增速",
                    "本年经营利润", "上年经营利润(同申报)", "经营利润增速", "经营利润率"])
        for kind, s, nm, rv, prv, gr, oi, poi, go, mg in vg:
            w.writerow([kind, f"FY{s}", nm, fmt(rv, "m"), fmt(prv, "m"), fmt(gr, "r"),
                        fmt(oi, "m"), fmt(poi, "m"), fmt(go, "r"), fmt(mg, "r")])
    print(f"✅ 财务比率.csv 写出（{sum(1 for _, d, _ in R if d)} 行 × {len(Y)} 年）；同口径增速.csv 写出（{len(vg)} 行）")
    print("拆股链（相邻两份年报对同一财年的股本之比）：")
    for a, b, k, c in gaps:
        if k != 1.0:
            print(f"  {label(a)} → {label(b)}：×{k:g}（FY{c[0]} {c[1]} 比值 {c[2]:.4f}）｜{DISCLOSED[(label(a), label(b))][1]}")
    print("复权倍数抽样：", {y: fac.get(y) for y in (1982, 1986, 1987, 1990, 1991, 1992, 1993, 1994, 1997, 1998, 1999, 2002, 2003, 2026)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
