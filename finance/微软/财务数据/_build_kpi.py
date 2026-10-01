#!/usr/bin/env python3
"""公司自陈经营指标（FY2012-2026）：云收入 / 云毛利率 / Azure 增速 / 折旧年限变更 → `经营指标(公司口径).csv`。

为什么单建：这几项是理解 Microsoft 当下生意的核心读数，但**全是公司自定义口径**——
  ① 云收入：FY2014-2021 叫 Commercial cloud、FY2022 起改叫 Microsoft Cloud，定义改过至少两次
     （FY2019 10-K 把 LinkedIn 商业部分并入并追溯重述；FY2023、FY2025 10-K 又各小幅重述上一年）；
  ② 云毛利率、Azure 增速：只在 MD&A 正文以百分比出现，无 XBRL、无绝对额（Azure 收入从未单独披露）；
  ③ 折旧年限：FY2021、FY2023 两次延长服务器/网络设备折旧年限，是毛利率与利润的会计估计变更来源。
所以每一项都同时留**原文锚句**与**交叉核**，不做跨口径拼接。

数据源：`_rfiles/<FY>.json` 的「Revenue Classified by Significant Product and Service Offerings (Parenthetical)」
（云收入·XBRL·每份 10-K 三年）+ `report/微软/<FY>.htm` MD&A 正文。
校验（不过不写出）：
  - 云收入：XBRL 当年值 = 正文「… was / increased X% to $Y billion」的 Y（有句子的年份全核）；
    正文增速 X% ≈ 同一份 10-K 当年 ÷ 比较年 − 1（±1pp）；
  - 云毛利率：正文「增减 N 点至 X%」→ 上一年 = X ∓ N，须等于上一份 10-K 自陈水平（否则=重述，列出）；
  - MUST：各指标在应有年份必须取到值。
"""
import csv
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
RDIR = os.path.join(HERE, "_rfiles")
FILINGS = list(range(2014, 2027))


def text(fy):
    p = os.path.join(ROOT, "report", "微软", f"{fy}.htm")
    if not os.path.exists(p):
        p = os.path.join(ROOT, "report", "微软", f"{fy}.txt")      # FY1994-2001 为纯文本全文申报
    raw = open(p, encoding="utf-8", errors="ignore").read()
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw)).replace("\xa0", " "))


def cloud_xbrl(sfy):
    """→ {fy: 百万美元}（该份 10-K 的三个全年列）"""
    d = json.load(open(os.path.join(RDIR, f"{sfy}.json")))
    t = next((v for k, v in d["details"].items()
              if re.search(r"significant product and service offerings \(parenthetical\)", k, re.I)), None)
    if not t:
        return {}
    rows = t["rows"]
    i0 = next((i for i, r in enumerate(rows) if re.search(r"^(commercial|microsoft) cloud$", r["label"].strip(), re.I)), None)
    if i0 is None:
        return {}
    rv = next((r for r in rows[i0 + 1:i0 + 4] if r["label"].strip().lower() in ("revenue", "revenues")), None)
    out = {}
    for j, p in enumerate(t["periods"]):
        m = re.match(r"Jun\. 30, (\d{4})$", p.strip())
        if m and rv and j < len(rv["vals"]) and rv["vals"][j] is not None:
            out[int(m.group(1))] = rv["vals"][j]        # 季度列也叫 Jun. 30 —— 全年列在后，后者覆盖前者
    return out


GM_PAT = re.compile(r"(?:Microsoft|commercial) cloud gross margin percentage (increased|decreased)( slightly)?"
                    r"(?: (\d+) points?)? to (\d{2})%", re.I)
AZ_PATS = [r"Azure(?: and other cloud services)? revenue (?:grew|increased) (\d+)%",
           r"Azure\W{1,4}\(\W?Azure\W?\)\W? revenue grew (\d+)%",
           r"Azure revenue growth (?:of|was) (\d+)%",
           r"Azure growth of (\d+)%"]
CLOUD_TXT = [r"(?:Microsoft|commercial) cloud revenue[^.]{0,200}?(?:increased (\d+)% to|was) \$ ?([\d.]+) billion"]
LIFE_PAT = re.compile(r"increase the estimated useful (?:life|lives) of (?:both )?server(?: equipment)?(?: and network equipment)? "
                      r"from (\w+) years to (\w+) years(?: and increase the estimated useful life of network equipment "
                      r"from (\w+) years to (\w+) years)?", re.I)
EFFECT_PAT = re.compile(r"the effect of this change in estimate for fiscal year (\d{4}) was an increase in operating income "
                        r"of \$ ?([\d.]+) billion and net income of \$ ?([\d.]+) billion, or \$ ?([\d.]+) per", re.I)
WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}

# 附注/MD&A 正文里以「$X billion」自陈、XBRL 表里没有单独一行的数（AI 基建与税务敞口相关）
# (键, 中文名, 申报, 正则, [(组号, 时点/期间)])
TEXT_FACTS = [
    ("comp_recv", "代采购服务器组件形成的其他应收(流动·在其他流动资产内)", 2026,
     r"the current portion of other receivables related to activities to facilitate the purchase of server components "
     r"was \$ ?([\d.]+) billion and \$ ?([\d.]+) billion", [(1, "2026-06-30"), (2, "2025-06-30")]),
    ("restricted_inv", "供应商协议项下的受限投资(短期投资+股权及其他投资内)", 2026,
     r"restricted investments pursuant to a supplier agreement were \$ ?([\d.]+) billion, with \$ ?([\d.]+) billion included "
     r"in short-term investments and \$ ?([\d.]+) billion included in equity and other investments",
     [(1, "2026-06-30 合计"), (2, "2026-06-30 其中短期投资"), (3, "2026-06-30 其中股权及其他投资")]),
    ("other_inv_up", "其他投资活动用现同比增加额(公司自陈主因：为代采购组件)", 2026,
     r"a \$([\d.]+) billion increase in cash used in other investing primarily to facilitate the purchase of components",
     [(1, "FY2026 较 FY2025")]),
    ("lt_ar", "长期应收账款净额(在其他长期资产内)", 2026,
     r"long-term accounts receivable, net of allowance for doubtful accounts, was \$ ?([\d.]+) billion and \$ ?([\d.]+) billion",
     [(1, "2026-06-30"), (2, "2025-06-30")]),
    ("irs_nopa", "IRS 拟调整通知(NOPA·2004-2013 税年·转让定价)追缴税款(不含罚款利息)", 2026,
     r"the IRS is seeking an additional tax payment of \$ ?([\d.]+) billion plus penalties and interest",
     [(1, "2023-09-26 收到·至 2026-06-30 未决")]),
    # 期权费用：FY2004 10-K 自 2003-07-01 起按 SFAS 123 追溯（FY2002-2003 已重述·见 重述与口径变更.csv），
    # FY2000-2001 未重述、只自陈「若重述」的数 —— as-reported 的 FY1996-2003 净利都不含期权费用（APB 25 内在价值法）
    ("sfas123_pro", "若按 SFAS 123 计期权费用的营业利润/净利(公司自陈·未重述年份)", 2004,
     r"If fiscal 2000 had been restated, the operating income and net income would have been \$([\d,]+) million and "
     r"\$([\d,]+) million\. If fiscal 2001 had been restated, the operating income and net income would have been "
     r"\$([\d,]+) million and \$([\d,]+) million",
     [(1, "FY2000 营业利润"), (2, "FY2000 净利"), (3, "FY2001 营业利润"), (4, "FY2001 净利")], 1.0),
    ("sfas123_cost", "按 SFAS 123 确认的股权激励费用(追溯口径)", 2004,
     r"Total compensation cost recognized in income for stock-based employee compensation awards was \$([\d.]+) billion "
     r"in fiscal 2002, \$([\d.]+) billion in fiscal 2003, and \$([\d.]+) billion in fiscal 2004",
     [(1, "FY2002"), (2, "FY2003"), (3, "FY2004")]),
    # FY1999 第四季度两项会计估计/准则变更（FY1999 10-K MD&A 自陈）
    ("fy99_rev", "FY1999 Q4 收入确认变更(SOP 98-9 + Windows 生命周期 2→3 年)对报告收入的净增加", 1999,
     r"The net impact of these changes was to increase reported revenue \$(\d+) million in the fourth quarter of 1999",
     [(1, "FY1999 Q4")], 1.0),
    ("fy99_ret", "FY1999 Q4 下调未来退货估计(渠道变化·冲减退货准备)", 1999,
     r"the estimate for future product returns was reduced by \$(\d+) million in the fourth quarter of fiscal 1999",
     [(1, "FY1999 Q4")], 1.0),
    ("fy99_reclass", "FY1999 10-K 把支持/咨询/MSN 接入/培训认证收款改列收入(此前冲减费用)", 1999,
     r"Revenue from these activities was \$(\d+) million, \$(\d+) million, and \$([\d.]+) billion in 1997, 1998, and 1999",
     [(1, "FY1997"), (2, "FY1998")], 1.0),
]


# MD&A「Contractual Obligations」表（FY2016 起逐年都有；FY2023 起期间列压缩为「一年内 / 以后 / 合计」三列）
CO_ROWS = [
    ("principal", "长期债务本金 Principal payments", r"Principal payments"),
    ("interest", "长期债务利息 Interest payments", r"Interest payments"),
    ("construction", "建造承诺 Construction commitments", r"Construction commitments"),
    ("op_lease", "经营租赁(FY2018 起含利息) Operating leases", r"Operating leases(?:, including imputed interest)?"),
    ("fin_lease", "融资(资本)租赁(含利息) Finance/Capital leases", r"(?:Finance|Capital) leases, including imputed interest"),
    ("lease_all", "经营+融资租赁合计(含利息·FY2022 起合并列示) Operating and finance leases", r"Operating and finance leases, including imputed interest"),
    ("transition_tax", "TCJA 一次性过渡税 Transition tax", r"Transition tax"),
    ("purchase", "采购承诺(主要为数据中心·含未结订单与照付不议) Purchase commitments", r"Purchase commitments"),
    ("other_lt", "其他长期负债 Other long-term liabilities", r"Other long-term liabilities"),
]
NUM = r"\$? ?([\d,]+)"


def contractual_obligations(s):
    """→ ({键: [各列值]}, 列头) ；表找不到返回 (None, None)。最后一列 = Total。"""
    t = text(s)
    m = re.search(r"outstanding contractual obligations as of June 30, (\d{4}): \(In millions\) ((?:\d{4}(?:-\d{4})? )+)Thereafter Total", t)
    if not m or int(m.group(1)) != s:
        return None, None
    heads = m.group(2).split() + ["Thereafter", "Total"]
    seg = t[m.end(): m.end() + 3000]
    seg = seg[: seg.find("( a)") if "( a)" in seg else seg.find("(a) Refer") if "(a) Refer" in seg else len(seg)]
    nums = " ".join([NUM] * len(heads))
    out = {}
    for key, _, pat in CO_ROWS:
        mm = re.search(pat + r"(?: \(\s*\w\s*\))? " + nums, seg)
        if mm:
            out[key] = [float(mm.group(i + 1).replace(",", "")) for i in range(len(heads))]
    mt = re.search(r"Total(?: contractual obligations)? " + nums, seg)
    if mt:
        out["total"] = [float(mt.group(i + 1).replace(",", "")) for i in range(len(heads))]
    return out, heads


def first(pats, t):
    best = None
    for p in pats:
        m = re.search(p, t, re.I)
        if m and (best is None or m.start() < best.start()):
            best = m
    return best


def main():
    bad, notes = [], []
    views = {s: cloud_xbrl(s) for s in FILINGS}
    asrep = {s: views[s].get(s) for s in FILINGS}
    # FY2012-2013：FY2014 10-K 的比较列（该口径起点；更早 10-K 无此指标）
    first_seen = {fy: v for fy, v in views[2014].items() if fy < 2014}
    restated = {}                                         # fy -> [(申报, 值)]，只记与 as-reported 不同的
    for s in FILINGS:
        for fy, v in views[s].items():
            base = asrep.get(fy, first_seen.get(fy))
            if fy != s and base is not None and abs(v - base) > 0.5:
                restated.setdefault(fy, []).append((s, v))
    gm, gm_chg, az, cloud_txt = {}, {}, {}, {}
    life, effect = [], {}
    for s in FILINGS:
        t = text(s)
        m = first(CLOUD_TXT, t)
        if m:
            cloud_txt[s] = (float(m.group(2)) * 1000, int(m.group(1)) if m.group(1) else None, m.group(0)[:160])
        m = GM_PAT.search(t)
        if m:
            gm[s] = int(m.group(4))
            sign = 1 if m.group(1).lower() == "increased" else -1
            gm_chg[s] = (sign * int(m.group(3)) if m.group(3) else None, m.group(0))
        m = first(AZ_PATS, t)
        if m:
            az[s] = (int(m.group(1)), m.group(0))
        for m in LIFE_PAT.finditer(t):
            rec = (s, WORDS.get(m.group(1).lower(), m.group(1)), WORDS.get(m.group(2).lower(), m.group(2)),
                   WORDS.get((m.group(3) or "").lower(), m.group(3)), WORDS.get((m.group(4) or "").lower(), m.group(4)))
            if rec not in life:
                life.append(rec)
        for m in EFFECT_PAT.finditer(t):
            effect[int(m.group(1))] = (float(m.group(2)) * 1000, float(m.group(3)) * 1000, float(m.group(4)), s)

    # ── 校验 ──
    for s, (v, g, sent) in cloud_txt.items():
        if asrep.get(s) is None or abs(v - asrep[s]) > 50:
            bad.append(f"FY{s} 云收入 正文 {v:g} ≠ XBRL {asrep.get(s)}：{sent}")
        if g is not None and views[s].get(s - 1):
            calc = (views[s][s] / views[s][s - 1] - 1) * 100
            if abs(calc - g) > 1.0:
                bad.append(f"FY{s} 云收入增速 正文 {g}% ≠ 同申报计算 {calc:.1f}%")
    for s, (chg, sent) in gm_chg.items():
        if chg is None or (s - 1) not in gm:
            continue
        implied = gm[s] - chg
        if implied != gm[s - 1]:
            notes.append(f"FY{s} 10-K 云毛利率「{sent}」→ 隐含 FY{s - 1} = {implied}%，与 FY{s - 1} 10-K 自陈 {gm[s - 1]}% 不同（重述）")
    MUST = [("云收入 as-reported", asrep, range(2014, 2027)),
            ("云毛利率", gm, range(2020, 2027)),
            ("Azure 增速", az, list(range(2016, 2027)))]
    for nm, d, yrs in MUST:
        miss = [y for y in yrs if d.get(y) is None]
        if miss:
            bad.append(f"MUST 缺格：{nm} @ {miss}")
    facts = []
    for spec in TEXT_FACTS:
        key, nm, s, pat, groups = spec[:5]
        sc = spec[5] if len(spec) > 5 else 1000.0          # 默认原文为十亿美元；第 6 项给 1.0 = 原文已是百万美元
        m = re.search(pat, text(s), re.I)
        if not m:
            bad.append(f"附注自陈数「{nm}」在 FY{s} 10-K 正文未找到")
            continue
        for gi, when in groups:
            facts.append((nm, when, float(m.group(gi).replace(",", "")) * sc, f"FY{s} 10-K", m.group(0)[:220]))
    # 交叉核：FY1999 10-K 自陈的改列收入额 = 重述表里 FY1997/1998 营收的重述差额（同一件事的两处印刷）
    rest = {}
    with open(os.path.join(HERE, "重述与口径变更.csv")) as f:
        for r in csv.reader(f):
            if len(r) >= 7 and r[0] == "IS" and r[1] == "营业收入 Revenue" and r[5] == "L1999":
                rest[int(r[2])] = float(r[6])
    for nm, when, v, *_ in facts:
        if nm.startswith("FY1999 10-K 把支持") and abs(rest.get(int(when[2:]), -1) - v) > 0.5:
            bad.append(f"FY1999 改列收入 {when} 自陈 {v:g} ≠ 重述表营收差额 {rest.get(int(when[2:]))}")
    # 回购拆分：现金流量表「回购股票」= 回购计划内回购 + 为员工股票归属代扣个税而回购的股份（后者实为股权激励的现金成本）
    wh = {}
    WH = re.compile(r"excludes shares repurchased to settle employee tax withholding related to the vesting of stock awards "
                    r"of \$ ?([\d.]+) billion, \$ ?([\d.]+) billion,? and \$ ?([\d.]+) billion for fiscal years (\d{4}), (\d{4}),? and (\d{4})", re.I)
    for s in range(2016, 2027):
        m = WH.search(text(s))
        if m:
            for i in range(3):
                y = int(m.group(4 + i))
                v = float(m.group(1 + i)) * 1000
                if y in wh and abs(wh[y][0] - v) > 50:
                    bad.append(f"代扣个税回购 FY{y}：FY{wh[y][1]} 10-K 印 {wh[y][0]:g}、FY{s} 10-K 印 {v:g}")
                wh.setdefault(y, (v, s))
    for y in range(2019, 2027):
        if y not in wh:
            bad.append(f"MUST 缺格：代扣个税回购 FY{y}")
    for y, (v, s) in sorted(wh.items()):
        facts.append(("为员工股票归属代扣个税而回购的股份(含在现金流量表「回购股票」内)", f"FY{y}", v, f"FY{s} 10-K 股东权益附注",
                      "The above table excludes shares repurchased to settle employee tax withholding related to the vesting of stock awards"))
    # 合同义务表：每列分项和 = 合计（不过 = 某行没抓到）
    co = {}
    for s in range(2016, 2027):
        tab, heads = contractual_obligations(s)
        if not tab or "total" not in tab:
            bad.append(f"FY{s} 合同义务表未找到或无合计行")
            continue
        for j, h in enumerate(heads):
            sm = sum(v[j] for k, v in tab.items() if k != "total")
            if abs(sm - tab["total"][j]) > 1:
                bad.append(f"FY{s} 合同义务表「{h}」列分项和 {sm:g} ≠ 合计 {tab['total'][j]:g}（{sorted(tab)}）")
        co[s] = tab
    rs = {k: v for k, v in ((f[1], f[2]) for f in facts if f[0].startswith("供应商协议"))}
    if rs and abs(rs.get("2026-06-30 其中短期投资", 0) + rs.get("2026-06-30 其中股权及其他投资", 0)
                  - rs.get("2026-06-30 合计", 0)) > 50:
        bad.append(f"受限投资分项和 ≠ 合计：{rs}")
    if sorted(effect) != [2021, 2023]:
        bad.append(f"折旧年限变更影响句：期望 FY2021、FY2023 两次，实得 {sorted(effect)}")
    # 年限句：FY2021 变更在 FY2021 10-K 自陈、FY2023 变更在 FY2022 10-K 首次自陈（2022-07 评估）——两句都必须取到
    if not any(x[0] == 2021 for x in life) or not any(x[0] == 2022 for x in life):
        bad.append(f"折旧年限句缺失：{life}")
    if bad:
        print("🔴 经营指标校验未过（不写出）：")
        for b in bad:
            print("  " + b)
        return 1

    years = list(range(2012, 2027))
    p = os.path.join(HERE, "经营指标(公司口径).csv")
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# 单位: 百万美元 / % | ⚠️ 全部为**公司自定义口径**（非 GAAP 科目、定义多次变更），只能在同一定义内比较 | "
                    "云收入 = XBRL 附注括注表（FY2012-2013 取 FY2014 10-K 比较列）；云毛利率与 Azure 增速 = MD&A 正文自陈 | "
                    "已校验：云收入 XBRL = 正文金额、正文增速 = 同申报计算值(±1pp)"])
        w.writerow(["科目"] + [f"FY{y}" for y in years])
        w.writerow(["云收入(as-reported·各年自家10-K) Commercial cloud→Microsoft Cloud revenue"] +
                    [f"{(asrep.get(y) if asrep.get(y) is not None else first_seen.get(y, '')):g}"
                     if (asrep.get(y) is not None or first_seen.get(y) is not None) else "" for y in years])
        for s in sorted({s for v in restated.values() for s, _ in v}):
            w.writerow([f"  云收入·FY{s} 10-K 重述的比较值"] +
                        [next((f"{v:g}" for ss, v in restated.get(y, []) if ss == s), "") for y in years])
        w.writerow(["云毛利率(%)(MD&A 自陈) cloud gross margin percentage"] + [str(gm.get(y, "")) for y in years])
        w.writerow(["Azure 收入增速(%)(MD&A 自陈·FY2022 起口径为 Azure and other cloud services)"] +
                    [str(az[y][0]) if y in az else "" for y in years])
        w.writerow([])
        w.writerow(["# 云收入口径定义沿革（10-K 原文要点）"])
        w.writerow(["申报", "名称", "定义/变更"])
        w.writerow(["FY2014-2015 10-K", "Commercial Cloud", "Office 365 commercial、Azure、Dynamics CRM Online 等商业云服务"])
        w.writerow(["FY2016-2018 10-K", "commercial cloud", "primarily comprises Office 365 commercial, Azure, Dynamics Online/365, and other cloud properties"])
        w.writerow(["FY2019 10-K", "commercial cloud", "并入 the commercial portion of LinkedIn，并追溯重述（FY2018 23.2→26.6 十亿美元、FY2017 14.9→16.2）"])
        w.writerow(["FY2022 10-K", "Microsoft Cloud", "更名；Azure and other cloud services, Office 365 Commercial, the commercial portion of LinkedIn, Dynamics 365, and other commercial cloud properties"])
        w.writerow(["FY2023 / FY2025 10-K", "Microsoft Cloud", "各小幅重述上一年（见上方「重述的比较值」行）；10-K 未说明原因"])
        w.writerow([])
        w.writerow(["# 原文锚句（逐年·供回源核对）"])
        w.writerow(["申报", "指标", "原文"])
        for s in FILINGS:
            if s in cloud_txt:
                w.writerow([f"FY{s}", "云收入", cloud_txt[s][2]])
            if s in gm_chg:
                w.writerow([f"FY{s}", "云毛利率", gm_chg[s][1]])
            if s in az:
                w.writerow([f"FY{s}", "Azure 增速", az[s][1]])
        w.writerow([])
        w.writerow(["# 云毛利率跨申报一致性（机械比对）"])
        for n in notes or ["各年「增减 N 点」隐含的上一年水平与上一份 10-K 自陈一致（无重述）"]:
            w.writerow([n])
        w.writerow([])
        w.writerow(["# 服务器/网络设备折旧年限变更（会计估计变更·未来适用法·不追溯）"])
        w.writerow(["生效财年", "服务器年限 前→后", "网络设备年限 前→后", "当年营业利润增加(百万美元)", "当年净利增加(百万美元)",
                    "每股增加(美元)", "出处"])
        life_by_eff = {2021: next((x for x in life if x[0] == 2021), None), 2023: next((x for x in life if x[0] == 2022), None)}
        for eff in (2021, 2023):
            oi, ni, ps, src = effect[eff]
            lf = life_by_eff[eff]
            srv = f"{lf[1]}→{lf[2]}" if lf else "?"
            net = f"{lf[3]}→{lf[4]}" if lf and lf[3] else srv
            w.writerow([f"FY{eff}", srv, net, f"{oi:g}", f"{ni:g}", f"{ps:.2f}", f"FY{src} 10-K 附注 1 / MD&A"])
    with open(os.path.join(HERE, "附注自陈数.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# 单位: 百万美元（原文以十亿美元一位小数自陈·已×1000·精度 ±50 百万）| 10-K 正文/附注以句子给出、XBRL 表无单独行的数 | "
                    "每行附原文锚句供回源 | 已校验：受限投资两分项和 = 合计"])
        w.writerow(["项目", "时点/期间", "值", "出处", "原文锚句"])
        for row in facts:
            w.writerow([row[0], row[1], f"{row[2]:g}", row[3], row[4]])
    print(f"✅ 附注自陈数.csv 写出（{len(facts)} 项）")
    yrs_co = sorted(co)
    with open(os.path.join(HERE, "合同义务.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# 单位: 百万美元 | 时点 = 财年末 | 来源：各年 10-K MD&A「Contractual Obligations」表（未来应付·未折现·**多数不在资产负债表内**："
                    "采购承诺、建造承诺、已签未起租租赁、未来利息均为表外）| 已校验：每份申报每列分项和 = 合计 | "
                    "⚠️ 列示口径有变：FY2016-2017 经营租赁不含利息、FY2018 起含；FY2022 起经营与融资租赁合并一行；FY2018-2021 单列 TCJA 过渡税"])
        w.writerow(["科目"] + [f"FY{y}" for y in yrs_co])
        for key, nm, _ in CO_ROWS + [("total", "合同义务合计 Total", None)]:
            line = [f"{co[y][key][-1]:g}" if key in co[y] else "" for y in yrs_co]
            if any(line):
                w.writerow([nm] + line)
        for key, nm in (("total", "  其中一年内到期·合计"), ("purchase", "  其中一年内到期·采购承诺"),
                        ("lease_all", "  其中一年内到期·租赁(合并列示年份)")):
            line = [f"{co[y][key][0]:g}" if key in co[y] else "" for y in yrs_co]
            if any(line):
                w.writerow([nm] + line)
    print(f"✅ 合同义务.csv 写出（FY{yrs_co[0]}-FY{yrs_co[-1]}）")
    print(f"✅ 经营指标(公司口径).csv 写出：云收入 {len(asrep)} 年 + 重述 {sum(len(v) for v in restated.values())} 处、"
          f"云毛利率 {len(gm)} 年、Azure 增速 {len(az)} 年、折旧年限变更 {len(effect)} 次")
    for n in notes:
        print("  ℹ️ " + n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
