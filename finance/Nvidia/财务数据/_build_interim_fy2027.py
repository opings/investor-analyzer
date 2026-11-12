#!/usr/bin/env python3
"""FY2027 中期（本财年 Q1 / Q2 10-Q）关键三表行 → `中期财务-FY2027.csv`，勾稽不过不写出。

- **中期数据独立成表·不并入年度序列**（年度序列止于 FY2026），避免年化 / 期间轴污染（记忆 google-alphabet-us-build）。
- 概念定义**复用** `_build_from_filings.py`（同一套 tag 映射，单一真相）；每列取自 10-Q 的 R 文件自身列。
- 期间轴（取数当场声明）：Q1 = 3 个月截至 2026-04-26；Q2 = 3 个月截至 2026-07-26；H1 = 6 个月截至 2026-07-26；
  对比列 = 同一份 10-Q 的上年同期列（两端同源）；资产负债表 = 2026-07-26 时点（对比 2026-01-25）。
- **分业务**（2026-11-12 补）：10-Q「Segment Information」附注 R 表机读 —— 分部 / 市场平台 / 地区 / 直接客户集中度。
  ①市场平台 **FY2027 Q1 起改口径**（Data Center = Hyperscale + ACIE；Edge Computing），与年度 `市场平台营收.csv`
  的旧口径（游戏 / 专业可视化 / 汽车 / OEM）不可拼接；②**Q2 10-Q 把「一家公司」由 ACIE 改划 Hyperscale 并重列以前各期**
  ⇒ Hyperscale / ACIE 按申报拆成「Q1 10-Q 原报」与「Q2 10-Q 口径」两行，同一行不混口径；改划金额单列派生行，并与
  Q2 10-Q MD&A 表印的 Q1 重列值互核；③地区 = 直接客户总部所在地（FY2026 Q3 起），不是最终使用地；
  ④客户集中度 = 直接客户，各列「第 1/2/3」按该列自身排序，不同列不一定是同一家（公司各期用不同成员名）。
  闸：三路分拆（分部 / 市场平台 / 地区）各自合计 = 利润表营收（容差 0）· Q1+Q2=H1（±1）· R 表数 = 10-Q 正文句子里的数。
"""
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _build_from_filings as B  # noqa: E402
import _build_notes as N  # noqa: E402  R 文件维度块解析（blocks / find / norm，与年度附注层同一套）
import _build_selfreported as S  # noqa: E402  10-Q 正文纯文本（plain / REPORT，文字闸用）

import json  # noqa: E402

COLS = [  # (列名, 申报, 表, 期间截止日前缀, 期长月数 or None)
    ("FY2027Q1(3个月·截至2026-04-26)", "2027Q1", "IS", "Apr. 26, 2026", 3),
    ("FY2026Q1(3个月·截至2025-04-27·同表对比)", "2027Q1", "IS", "Apr. 27, 2025", 3),
    ("FY2027Q2(3个月·截至2026-07-26)", "2027Q2", "IS", "Jul. 26, 2026", 3),
    ("FY2026Q2(3个月·截至2025-07-27·同表对比)", "2027Q2", "IS", "Jul. 27, 2025", 3),
    ("FY2027H1(6个月·截至2026-07-26)", "2027Q2", "IS", "Jul. 26, 2026", 6),
    ("FY2026H1(6个月·截至2025-07-27·同表对比)", "2027Q2", "IS", "Jul. 27, 2025", 6),
    ("FY2027H1(6个月·截至2026-07-26)", "2027Q2", "CF", "Jul. 26, 2026", 6),
    ("FY2026H1(6个月·截至2025-07-27·同表对比)", "2027Q2", "CF", "Jul. 27, 2025", 6),
    ("2026-07-26 时点", "2027Q2", "BS", "Jul. 26, 2026", None),
    ("2026-01-25 时点(同表对比)", "2027Q2", "BS", "Jan. 25, 2026", None),
]


def one_col(st, prefix, months):
    for i, p in enumerate(st["periods"]):
        if p.startswith(prefix) and (months is None or not st["months"] or st["months"][i] == months):
            rows = [{"label": r["label"], "tag": r.get("tag"), "vals": [r["vals"][i] if i < len(r["vals"]) else None]}
                    for r in st["rows"]]
            return {"unit": st["unit"], "periods": ["Jan. 1, 2099"], "months": [12] if months else [], "rows": rows}
    return None


IS_COLS = [(c, fk, pre, mo) for c, fk, st, pre, mo in COLS if st == "IS"]   # Q1 / Q1对比 / Q2 / Q2对比 / H1 / H1对比
BS_COL_PREFIX = {"2026-07-26 时点": "Jul. 26, 2026", "2026-01-25 时点(同表对比)": "Jan. 25, 2026"}
SEG = [("compute & networking", "计算与网络 Compute & Networking"), ("graphics", "图形 Graphics")]
MKT = [("data center", "数据中心 Data Center"), ("hyperscale", "  其中 超大规模云 Hyperscale"),
       ("ai clouds, industrial, & enterprise", "  其中 AI 云·工业·企业 ACIE"), ("edge computing", "边缘计算 Edge Computing")]
GEO = [("united states", "美国 United States"), ("taiwan", "台湾 Taiwan"),
       ("china (including hong kong)", "中国(含香港) China incl. Hong Kong"), ("other", "其他 Other")]
REV_TAG, OI_TAG, PCT_TAG = "us-gaap_Revenues", "us-gaap_OperatingIncomeLoss", "us-gaap_ConcentrationRiskPercentage1"
RECON_TAGS = ("us-gaap_AllocatedShareBasedCompensationExpense", "nvda_UnallocatedCorporateOperatingExpendituresAndOtherExpenses",
              "nvda_AcquisitionRelatedAndOtherCosts")


def det_idx(det, prefix, months):
    for i, p in enumerate(det["periods"]):
        if p.startswith(prefix) and (months is None or not det["months"] or det["months"][i] == months):
            return i
    return None


def member_vals(det, i, tags):
    """→ {(成员键, tag): 值}。成员键 = 成员标签「|」后最末段（小写）；第一个成员块之前 = 'TOTAL'（合并数）。"""
    out = {}
    for mem, r in N.blocks(det):
        v = r["vals"][i] if i < len(r["vals"]) else None
        if v is None or r.get("tag") not in tags:
            continue
        key = "TOTAL" if mem == "TOTAL" else N.norm(mem.split("|")[-1])
        out.setdefault((key, r["tag"]), v)
    return out


def pct_list(det, i, member_pat):
    """某列里成员标签匹配 member_pat 的全部集中度 %，降序。"""
    vals = [r["vals"][i] for mem, r in N.blocks(det)
            if r.get("tag") == PCT_TAG and re.search(member_pat, mem, re.I) and i < len(r["vals"]) and r["vals"][i] is not None]
    return sorted(vals, reverse=True)


def pcts_in(s):
    return [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s?%", s)]


def business(full, g):
    """分部 / 市场平台 / 地区 / 客户集中度 → ([(表, 科目, {列: 值})], bad)。g(表, 科目, 列) = 已取三表值（营收 / 营业利润闸用）。"""
    rows, bad = [], []
    put = {}
    add = lambda t, n, c, v: put.setdefault((t, n), {}).__setitem__(c, v)
    q1c, q1p, q2c, q2p, h1c, h1p = (c for c, *_ in IS_COLS)
    rev = {c: g("IS", "营业收入 Revenue", c) for c, *_ in IS_COLS}
    oi = {c: g("IS", "营业利润 Operating income", c) for c, *_ in IS_COLS}
    t_seg, t_mkt, t_geo, t_con = "分部", "市场平台(FY2027新口径)", "地区(直接客户总部口径)", "客户集中度(%·直接客户)"
    mkt_q1orig = {}
    for col, fk, prefix, months in IS_COLS:
        b = full[fk]
        # ── 分部 ──
        det = N.find(b, r"Schedule of Reportable Segments")
        i = det_idx(det, prefix, months)
        mv = member_vals(det, i, (REV_TAG, OI_TAG))
        seg_rev = seg_oi = 0.0
        for key, name in SEG:
            add(t_seg, f"{name}·营收", col, mv[(key, REV_TAG)])
            add(t_seg, f"{name}·分部营业利润", col, mv[(key, OI_TAG)])
            seg_rev += mv[(key, REV_TAG)]
            seg_oi += mv[(key, OI_TAG)]
        if abs(seg_rev - rev[col]) > 1e-6:
            bad.append((col, "分部营收和=利润表营收", (seg_rev, rev[col])))
        if abs(mv[("TOTAL", OI_TAG)] - oi[col]) > 1e-6 or abs(mv[("operating segments", OI_TAG)] - seg_oi) > 1e-6:
            bad.append((col, "分部表合并营业利润=利润表 / 分部营业利润和=分部表小计", (mv[("TOTAL", OI_TAG)], oi[col], seg_oi)))
        unalloc = oi[col] - seg_oi
        add(t_seg, "未分配项(=合并营业利润−分部营业利润和·股权激励+未分配营业费用+收购相关)", col, unalloc)
        det_r = N.find(b, r"Schedule of Reconciling Items")
        ir = det_idx(det_r, prefix, months)
        recon = sum(r["vals"][ir] for mem, r in N.blocks(det_r)
                    if "corporate nonsegment" in N.norm(mem) and r.get("tag") in RECON_TAGS and r["vals"][ir] is not None)
        if abs(recon - unalloc) > 1e-6:
            bad.append((col, "未分配项=调节表(股权激励+未分配营业费用+收购相关)", (unalloc, recon)))
        # ── 市场平台（Hyperscale / ACIE 按申报分行：Q1 10-Q 原报 vs Q2 10-Q 口径） ──
        det = N.find(b, r"Schedule of Revenue by Market Platform")
        i = det_idx(det, prefix, months)
        mv = member_vals(det, i, (REV_TAG,))
        vals = {key: mv[(key, REV_TAG)] for key, _ in MKT}
        tag_cal = "(Q1 10-Q 原报)" if fk == "2027Q1" else "(Q2 10-Q 口径·一家公司由 ACIE 改划·可比期已重列)"
        for key, name in MKT:
            nm = name + (tag_cal if key in ("hyperscale", "ai clouds, industrial, & enterprise") else "")
            add(t_mkt, nm, col, vals[key])
        if fk == "2027Q1":
            mkt_q1orig[col] = vals
        if abs(vals["data center"] + vals["edge computing"] - rev[col]) > 1e-6:
            bad.append((col, "数据中心+边缘计算=利润表营收", (vals["data center"], vals["edge computing"], rev[col])))
        if abs(vals["hyperscale"] + vals["ai clouds, industrial, & enterprise"] - vals["data center"]) > 1e-6:
            bad.append((col, "Hyperscale+ACIE=数据中心", vals))
        # ── 地区（总部口径） ──
        det = N.find(b, r"Schedule of Revenue by Geographic Regions")
        i = det_idx(det, prefix, months)
        mv = member_vals(det, i, (REV_TAG,))
        s = 0.0
        for key, name in GEO:
            add(t_geo, name, col, mv[(key, REV_TAG)])
            s += mv[(key, REV_TAG)]
        if abs(s - rev[col]) > 1e-6:
            bad.append((col, "地区和=利润表营收", (s, rev[col])))
        add(t_geo, "派生·总部在美国以外的直接客户营收占比(%) = 1 − 美国 ÷ 营收", col,
            round((rev[col] - mv[("united states", REV_TAG)]) / rev[col] * 100, 1))
        # ── 直接客户占营收（各列自身排序） ──
        det = N.find(b, r"Segment Information - Concentration Risk")
        i = det_idx(det, prefix, months)
        for k, v in enumerate(pct_list(det, i, r"customer")):
            add(t_con, f"直接客户占营收·第{k + 1}大", col, v)
    # 跨申报 Q1+Q2=H1（±1·两份 10-Q 各自取整）——Hyperscale / ACIE 不在此闸（Q1 原报未含改划），见下方改划闸
    for (t, n), vv in put.items():
        if n.startswith("派生"):
            continue
        if t in (t_seg, t_geo) or (t == t_mkt and ("数据中心" in n or "边缘计算" in n)):
            a, b_, h = vv.get(q1c), vv.get(q2c), vv.get(h1c)
            if None in (a, b_, h) or abs(a + b_ - h) > 1.0 + 1e-6:
                bad.append(("跨申报", f"Q1+Q2=H1 {n}", (a, b_, h)))
    # 改划闸：Q2 10-Q 口径的「H1 − Q2」= Q1 重列值；它与 Q1 原报之差在 Hyperscale 与 ACIE 两行等额反向（±2）
    hs, ac = "hyperscale", "ai clouds, industrial, & enterprise"
    q2v = {c: {k: put[(t_mkt, nm + "(Q2 10-Q 口径·一家公司由 ACIE 改划·可比期已重列)")][c]
               for k, nm in MKT if k in (hs, ac)} for c in (q2c, q2p, h1c, h1p)}
    for qcol, q2col, h1col in ((q1c, q2c, h1c), (q1p, q2p, h1p)):
        d_hs = q2v[h1col][hs] - q2v[q2col][hs] - mkt_q1orig[qcol][hs]
        d_ac = q2v[h1col][ac] - q2v[q2col][ac] - mkt_q1orig[qcol][ac]
        if abs(d_hs + d_ac) > 2.0 + 1e-6 or d_hs <= 0:
            bad.append((qcol, "改划等额反向(Hyperscale 增 = ACIE 减)", (d_hs, d_ac)))
        add(t_mkt, "派生·Q2 10-Q 改划金额(ACIE→Hyperscale) = Q2 10-Q 口径(H1−Q2) − Q1 10-Q 原报·Hyperscale", qcol, d_hs)
    # 与 Q2 10-Q MD&A 表互核：MD&A 印本季 / 上季(重列) / 上年同季三列，上季列 = Q1 重列值
    txt2 = S.plain(os.path.join(S.REPORT, "2027-Q2.htm"))
    num = r"\$?\s?([\d,]+)"
    for key, label in ((hs, "Hyperscale"), (ac, r"AI Clouds, Industrial, & Enterprise"), ("data center", "Data Center"),
                       ("edge computing", "Edge Computing")):
        m = re.search(label + r"\s+" + r"\s+".join([num] * 3) + r"\s+(\d+)\s?%\s+(\d+)\s?%", txt2)
        if not m:
            bad.append(("MD&A", f"{label} 行找不到", None))
            continue
        cur, prev, yago = (float(x.replace(",", "")) for x in m.groups()[:3])
        q1_recast = (q2v[h1c][key] - q2v[q2c][key]) if key in (hs, ac) else None
        if key in (hs, ac):
            ok = cur == q2v[q2c][key] and yago == q2v[q2p][key] and abs(prev - q1_recast) <= 1.0 + 1e-6
        else:  # 数据中心 / 边缘计算不受改划影响：MD&A 上季列 = Q1 原报
            ok = cur == put[(t_mkt, dict(MKT)[key])][q2c] and prev == mkt_q1orig[q1c][key]
        if not ok:
            bad.append(("MD&A", f"{label} 本季/上季/上年同季", (cur, prev, yago, q1_recast)))
    # 文字闸：R 表数 = 10-Q 正文句子里的数（集中度 / 境外占比 / 应收集中度）
    txt1 = S.plain(os.path.join(S.REPORT, "2027-Q1.htm"))
    sent = {
        q1c: (txt1, r"For the first quarter of fiscal year 2027, three direct customers represented ([^.]*?) of total revenue"),
        q1p: (txt1, r"For the first quarter of fiscal year 2026, sales to two direct customers represented ([^.]*?) of total revenue"),
        q2c: (txt2, r"For the second quarter of fiscal year 2027, one direct customer represented ([^.]*?) of total revenue"),
        h1c: (txt2, r"For the first half of fiscal year 2027, three direct customers represented ([^.]*?) of total revenue"),
        q2p: (txt2, r"For the second quarter of fiscal year 2026, two direct customers represented ([^.]*?) of total revenue"),
        h1p: (txt2, r"For the first half of fiscal year 2026, two direct customers represented ([^.]*?) of total revenue"),
    }
    for col, (t, pat) in sent.items():
        m = re.search(pat, t)
        got = [put.get((t_con, f"直接客户占营收·第{k}大"), {}).get(col) for k in (1, 2, 3)]
        got = [v for v in got if v is not None]
        if not m or pcts_in(m.group(1)) != got:
            bad.append((col, "直接客户集中度 R 表 = 正文", (m and pcts_in(m.group(1)), got)))
    nonus = []
    m = re.search(r"headquartered outside of the United States accounted for (\d+) ?% of total revenue for the first quarter of "
                  r"fiscal year 2027 and (\d+) ?% of total revenue for the first quarter of fiscal year 2026", txt1)
    nonus += list(zip((q1c, q1p), m.groups())) if m else [("Q1", None)]
    m = re.search(r"headquartered outside of the United States accounted for (\d+) ?% and (\d+) ?% of total revenue for the second "
                  r"quarter and first half of fiscal year 2027, respectively, and (\d+) ?% and (\d+) ?% of total revenue", txt2)
    nonus += list(zip((q2c, h1c, q2p, h1p), m.groups())) if m else [("Q2", None)]
    for col, v in nonus:
        d = put.get((t_geo, "派生·总部在美国以外的直接客户营收占比(%) = 1 − 美国 ÷ 营收"), {}).get(col)
        if v is None or d is None or abs(float(v) - d) > 0.5 + 1e-9:
            bad.append((col, "境外总部客户占比：派生 = 正文(±0.5pp 取整)", (v, d)))
    # 应收集中度（时点·资产负债表列）
    b2 = full["2027Q2"]
    det = N.find(b2, r"Supplemental Financial Statement Information - Narrative")
    for col, prefix in BS_COL_PREFIX.items():
        i = det_idx(det, prefix, None)
        for k, v in enumerate(pct_list(det, i, r"A/R Customer")):
            add(t_con, f"直接客户占应收·第{k + 1}大", col, v)
    for col, pat in (("2026-07-26 时点", r"Five direct customers accounted for ([^.]*?) of our accounts receivable balance as of July 26, 2026"),
                     ("2026-01-25 时点(同表对比)", r"Three direct customers accounted for ([^.]*?) of our accounts receivable balance as of January 25, 2026")):
        m = re.search(pat, txt2)
        got = [put.get((t_con, f"直接客户占应收·第{k}大"), {}).get(col) for k in range(1, 6)]
        got = [v for v in got if v is not None]
        if not m or pcts_in(m.group(1)) != got:
            bad.append((col, "应收集中度 R 表 = 正文", (m and pcts_in(m.group(1)), got)))
    # ── 合同负债（递延收入）滚动表：Q2 10-Q 附注 6 个月列；期末余额落时点列，新增 / 确认落 H1 列 ──
    t_dr = "合同负债(递延收入·10-Q 附注滚动表)"
    det = N.find(b2, r"Schedule of Changes in Deferred Revenue")
    for col, prefix in ((h1c, "Jul. 26, 2026"), (h1p, "Jul. 27, 2025")):
        i = det_idx(det, prefix, 6)
        v = {}
        for mem, r in N.blocks(det):
            x = r["vals"][i] if i < len(r["vals"]) else None
            if x is not None:
                v.setdefault(r["tag"], []).append(x)
        beg, end_ = v["us-gaap_ContractWithCustomerLiability"]
        add_, rec = v["nvda_ContractWithCustomerLiabilityAdditions"][0], \
            v["nvda_ContractWithCustomerLiabilityRevenueRecognizedOpeningBalanceAndCurrentPeriodAdditions"][0]
        if abs(beg + add_ + rec - end_) > 1e-6:
            bad.append((col, "合同负债 期初+新增+确认=期末", (beg, add_, rec, end_)))
        add(t_dr, "本期新增 Deferred revenue additions", col, add_)
        add(t_dr, "本期确认收入(负数) Revenue recognized", col, rec)
        add(t_dr, "其中·客户预付款新增 additions from customer advances", col, v["nvda_ContractWithCustomerLiabilityAdditionsCustomerAdvances"][0])
        add(t_dr, "其中·来自客户预付款的确认收入(正数列示) revenue recognized from customer advances", col,
            v["nvda_ContractWithCustomerLiabilityRevenueRecognizedFromCustomerAdvances"][0])
        if col == h1c:
            add(t_dr, "期末余额 Balance at end of period", "2026-07-26 时点", end_)
            add(t_dr, "期末余额 Balance at end of period", "2026-01-25 时点(同表对比)", beg)
    # ── 派生（周转与承诺·2026-11-12）：公式与 财务比率.csv 年度同（365 × 平均余额 ÷ 全年流量），H1 = 2026-01-26 ~ 07-26 共 182 天 ──
    t_der = "派生(周转与承诺)"
    bs1, bs0 = "2026-07-26 时点", "2026-01-25 时点(同表对比)"
    inv1, inv0 = g("BS", "存货 Inventories", bs1), g("BS", "存货 Inventories", bs0)
    ar1, ar0 = g("BS", "应收账款净额 Accounts receivable, net", bs1), g("BS", "应收账款净额 Accounts receivable, net", bs0)
    cos_h1 = g("IS", "营业成本 Cost of revenue", h1c)
    if None in (inv1, inv0, ar1, ar0, cos_h1):
        bad.append(("派生", "周转天数缺科目", (inv1, inv0, ar1, ar0, cos_h1)))
    else:
        add(t_der, "派生·存货周转天数(H1) = 182 × 平均存货(2026-01-25 / 07-26) ÷ 营业成本 —— 年度同口径见 财务比率.csv", h1c,
            round(182 * (inv0 + inv1) / 2 / cos_h1, 1))
        add(t_der, "派生·应收账款周转天数(H1) = 182 × 平均应收 ÷ 营收 —— 与公司自陈 DSO(季末应收 ÷ 单季营收·附注自陈数.csv)公式不同", h1c,
            round(182 * (ar0 + ar1) / 2 / rev[h1c], 1))
    with open(os.path.join(HERE, "利润表.csv"), encoding="utf-8") as fr:   # 上游·年度 as-reported
        lines_is = [l for l in fr if not l.startswith("#")]
    hdr_is = next(csv.reader([lines_is[0]]))
    fy26_rev = float({r[0]: r for r in csv.reader(lines_is[1:]) if r}["营业收入 Revenue"][hdr_is.index("FY2026")])
    ttm = fy26_rev + rev[h1c] - rev[h1p]
    add(t_der, "派生·过去 12 个月营收(TTM·截至 2026-07-26) = FY2026 营收 + FY2027H1 − FY2026H1", bs1, ttm)
    pat_sup = next(it[3] for it in S.ITEMS if it[0] == "供应与产能承诺(10-Q 自陈·季末)" and it[1] == "2026-07-26")
    m = re.search(pat_sup, txt2)
    if not m:
        bad.append(("派生", "季末供应与产能承诺锚句找不到", None))
    else:
        sup = float(m.group(1)) * 1000
        add(t_der, "派生·供应与产能承诺(10-Q 自陈·季末) ÷ TTM 营收 —— 财报关注要点 跟踪变量 5 警戒线 >0.5", bs1, round(sup / ttm, 4))
    # 市场平台行序：数据中心 → Hyperscale(原报 / Q2 口径) → ACIE(原报 / Q2 口径) → 边缘计算 → 派生
    rank = lambda n: (4 if n.startswith("派生") else 0 if "数据中心" in n else 1 if "Hyperscale" in n else 2 if "ACIE" in n
                      else 3 if "边缘计算" in n else 5)
    for t in (t_seg, t_mkt, t_geo, t_con, t_dr, t_der):
        part = [(n, vv) for (tt, n), vv in put.items() if tt == t]
        if t == t_mkt:
            part.sort(key=lambda x: (rank(x[0]), "Q2 10-Q" in x[0]))
        rows += [(t, n, vv) for n, vv in part]
    return rows, bad


def main():
    full = {k: json.load(open(os.path.join(HERE, "_rfiles", f"{k}.json"))) for k in ("2027Q1", "2027Q2")}
    books = {k: full[k]["statements"] for k in full}
    data, bad = {}, []
    for col, fk, stmt, prefix, months in COLS:
        st = one_col(books[fk][stmt], prefix, months)
        if st is None:
            bad.append((col, stmt, "列找不到"))
            continue
        for c in B.SPEC[stmt]:
            v = B.pick(st, c, "2099", "R")
            if v is not None:
                if B.SIGN.get(c[0]) == "neg":
                    v = -abs(v)
                data.setdefault((stmt, c[0]), {})[col] = v
    g = lambda s, n, c: data.get((s, n), {}).get(c)
    # 勾稽（默认容差 0）
    for col, fk, stmt, prefix, months in COLS:
        if stmt == "IS":
            R_, C_, GP = g("IS", "营业收入 Revenue", col), g("IS", "营业成本 Cost of revenue", col), g("IS", "毛利 Gross profit", col)
            OPX, OI = g("IS", "营业费用合计 Total operating expenses", col), g("IS", "营业利润 Operating income", col)
            NON, PBT = g("IS", "营业外收支合计(FY2016起印刷) Total other income (expense)", col), g("IS", "税前利润 Income before income tax", col)
            TAX, NI = g("IS", "所得税 Income tax expense (benefit)", col), g("IS", "净利润 Net income", col)
            for nm, dv in (("营收−成本=毛利", R_ - C_ - GP), ("毛利−营业费用=营业利润", GP - OPX - OI),
                           ("营业利润+营业外=税前", OI + NON - PBT), ("税前−所得税=净利", PBT - TAX - NI)):
                if abs(dv) > 1e-6:
                    bad.append((col, nm, dv))
        if stmt == "BS":
            TA, TCA = g("BS", "总资产 Total assets", col), g("BS", "流动资产合计 Total current assets", col)
            TL, TE = g("BS", "负债合计(FY2016起印刷) Total liabilities", col), g("BS", "股东权益合计 Total shareholders' equity", col)
            if None in (TA, TL, TE) or abs(TL + TE - TA) > 1e-6:
                bad.append((col, "负债+权益=总资产", (TA, TL, TE)))
            # 流动资产明细和 = 合计（第一版漏收 10-Q 新拆的「有价债券 / 上市权益证券」两个 tag，差 769 亿也照样写出——补闸）
            names = [c[0] for c in B.BS_CONCEPTS]
            ca = [n for n in names[:names.index("流动资产合计 Total current assets")]]
            s = sum(g("BS", n, col) or 0.0 for n in ca)
            if TCA is None or abs(s - TCA) > 1e-6:
                bad.append((col, "流动资产明细和=合计", (s, TCA)))
            nca = names[names.index("流动资产合计 Total current assets") + 1:names.index("总资产 Total assets")]
            s2 = TCA + sum(g("BS", n, col) or 0.0 for n in nca)
            if abs(s2 - TA) > 1e-6:
                bad.append((col, "流动+非流动=总资产", (s2, TA)))
        if stmt == "CF":
            o, i_, f = (g("CF", n, col) for n in ("经营活动现金流净额 Net cash from operating activities",
                                                 "投资活动现金流净额 Net cash from investing activities",
                                                 "融资活动现金流净额 Net cash from financing activities"))
            ch = g("CF", "现金净变动 Change in cash and cash equivalents", col)
            if None in (o, i_, f, ch) or abs(o + i_ + f - ch) > 1e-6:
                bad.append((col, "经营+投资+融资=现金净变动", (o, i_, f, ch)))
    # 跨申报：Q1 单季（2027Q1 10-Q）+ Q2 单季（2027Q2 10-Q）= H1（2027Q2 10-Q）。
    # 显式容差 ±1（百万）：Q1、Q2、H1 三个数分别在两份 10-Q 里各自按百万取整（实测营收 81,615+96,221=177,836 vs
    # H1 177,837；净利 58,321+59,688=118,009 vs 118,010）——源表舍入，不是转录错（R 文件机读、无人工转录环节）
    for n in ("营业收入 Revenue", "毛利 Gross profit", "营业利润 Operating income", "净利润 Net income"):
        q1, q2, h1 = (g("IS", n, c) for c in ("FY2027Q1(3个月·截至2026-04-26)", "FY2027Q2(3个月·截至2026-07-26)",
                                               "FY2027H1(6个月·截至2026-07-26)"))
        if None in (q1, q2, h1) or abs(q1 + q2 - h1) > 1.0 + 1e-6:
            bad.append(("跨申报", f"Q1+Q2=H1 {n}", (q1, q2, h1)))
    # 派生（口径当场声明）：净现金两口径。上市权益证券多为战略持股、大部分处于锁定期（附注自陈数.csv），不是可动用现金；
    # 年度 财务比率.csv 的「净现金」按年报「Marketable securities」一行算——FY2026 10-K 把债券与上市权益证券合在这一行，
    # 10-Q 起才拆成两行，故另给「剔上市权益证券」口径。
    # 闸（跨文件·只读上游 资产负债表.csv，不读下游 财务比率.csv）：10-Q 对比列 2026-01-25 的「有价债券 + 上市权益证券」
    # 必须等于 FY2026 10-K 的「Marketable securities」一行，现金同理——拆分前后同一时点必须对得上。
    BS_COLS = ("2026-07-26 时点", "2026-01-25 时点(同表对比)")
    cash_n, debt_sec_n = "现金及现金等价物 Cash and cash equivalents", "有价债券(FY2027起季报单列) Marketable debt securities"
    eq_n, std_n, ltd_n = ("上市权益证券(FY2027起季报单列) Marketable equity securities", "短期债务(FY2021起) Short-term debt",
                          "长期债务 Long-term debt")
    derived = {}
    for c in BS_COLS:
        parts = [g("BS", n, c) for n in (cash_n, debt_sec_n, eq_n, std_n, ltd_n)]
        if None in parts:
            bad.append((c, "派生净现金缺科目", parts))
            continue
        cash, dsec, eq, std, ltd = parts
        derived[("含", c)] = cash + dsec + eq - std - ltd
        derived[("剔", c)] = cash + dsec - std - ltd
    with open(os.path.join(HERE, "资产负债表.csv"), encoding="utf-8") as fr:
        lines = [l for l in fr if not l.startswith("#")]
    hdr = next(csv.reader([lines[0]]))
    annual = {r[0]: r for r in csv.reader(lines[1:]) if r}
    ix = hdr.index("FY2026")
    a_cash = float(annual["现金及现金等价物 Cash and cash equivalents"][ix])
    a_mkt = float(annual["有价证券 Marketable securities"][ix])
    q_cash, q_dsec, q_eq = (g("BS", n, BS_COLS[1]) for n in (cash_n, debt_sec_n, eq_n))
    if None in (q_cash, q_dsec, q_eq) or abs(q_cash - a_cash) > 1e-6 or abs(q_dsec + q_eq - a_mkt) > 1e-6:
        bad.append(("跨文件", "10-Q 对比列(现金 / 债券+权益) = FY2026 10-K(现金 / Marketable securities)",
                    ((q_cash, q_dsec, q_eq), (a_cash, a_mkt))))
    biz, bad_biz = business(full, g)
    bad += bad_biz
    if bad:
        print(f"❌ 中期勾稽不通过 {len(bad)} 条（不写出）：")
        for b in bad:
            print("   ", b)
        return 1
    cols = []
    for col, *_ in COLS:
        if col not in cols:
            cols.append(col)
    with open(os.path.join(HERE, "中期财务-FY2027.csv"), "w", newline="") as f:
        f.write("# 单位: 百万美元(EPS 美元/股·集中度与占比为 %) | 本财年两份 10-Q(FY2027 Q1 截至 2026-04-26 / Q2 截至 2026-07-26)的 R 文件 | **独立成表·不并入年度序列** | "
                "对比列取同一份 10-Q 的上年同期列(两端同源) | 闸: 利润链 / 负债+权益=总资产 / 三段=净变动 / Q1+Q2=H1(跨申报) | "
                "「派生」两行 = 净现金两口径(上市权益证券多为锁定期战略持股，见 附注自陈数.csv) | "
                "分业务(分部 / 市场平台 / 地区 / 客户集中度)取 10-Q Segment Information 附注: 🔴 **市场平台 FY2027 Q1 起改口径**"
                "(数据中心 = Hyperscale + ACIE；边缘计算)，与年度 市场平台营收.csv 旧口径不可拼接；**Q2 10-Q 把一家公司由 ACIE 改划 Hyperscale 并重列可比期**，"
                "故 Hyperscale / ACIE 按申报分「Q1 10-Q 原报」「Q2 10-Q 口径」两行、改划金额单列派生行(与 Q2 10-Q MD&A 表 Q1 重列值互核)；"
                "地区 = 直接客户总部所在地；客户集中度 = 直接客户、各列按自身排序(不同列不一定同一家) | "
                "分业务闸: 分部和 = 市场平台和 = 地区和 = 利润表营收(容差 0)·Q1+Q2=H1(±1)·集中度与境外占比 R 表 = 10-Q 正文句子 | "
                "合同负债(递延收入)取 Q2 10-Q 附注 6 个月滚动表(含客户预付款)，闸: 期初+新增+确认=期末\n")
        w = csv.writer(f)
        w.writerow(["表", "科目"] + cols)
        for (stmt, n), vv in data.items():
            if all(vv.get(c) is None for c in cols):
                continue
            w.writerow([{"IS": "利润表", "BS": "资产负债表", "CF": "现金流量表"}[stmt], n] +
                       [B.fmt(vv.get(c), B.PS if "EPS" in n else B.M) for c in cols])
        for key, label in (("含", "派生·净现金(含上市权益证券) = 现金+有价债券+上市权益证券−短期债务−长期债务"),
                           ("剔", "派生·净现金(剔上市权益证券) = 现金+有价债券−短期债务−长期债务")):
            w.writerow(["派生", label] + [B.fmt(derived[(key, c)], B.M) if c in BS_COLS else "" for c in cols])
        for t, n, vv in biz:
            w.writerow([t, n] + [B.fmt(vv.get(c), B.M) for c in cols])
    print(f"✅ 写出 中期财务-FY2027.csv（{len(data)} 行 + 派生 2 行 + 分业务 {len(biz)} 行；10-Q 对比列债券+权益 = FY2026 10-K "
          f"Marketable securities；分部 / 市场平台 / 地区三路合计 = 营收；集中度 = 正文）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
