#!/usr/bin/env python3
"""NIKE 分部层构建器：从 `_rfiles/` 的分部附注表抽出

  · `分部营收.csv`        —— 各分部营收（地区 / 品牌 / 总部）
  · `分部经营利润.csv`    —— 各分部 EBIT（NIKE 分部不披露分部净利，只披露 EBIT）
  · `分产品与渠道营收.csv` —— 鞋 / 服 / 装备 与 批发 / DTC 两个切口

**勾稽不过不写出**。

## 🔴 分部口径在 30 年里改过三次，跨年比必须先看口径列

| 期间 | NIKE 品牌地区划分 | 非 NIKE 品牌 |
|---|---|---|
| FY2011-FY2014 | 北美 / 西欧 / 中东欧 / 大中华 / 日本 / 新兴市场（**6 区**） | 「其他业务 Other Businesses」（含 Converse + Cole Haan + Umbro + Hurley） |
| FY2015-FY2017 | 同上 6 区 | 「Converse」单列（Cole Haan / Umbro 已于 FY2013 出售） |
| FY2018-FY2026 | 北美 / EMEA / 大中华 / 亚太拉美（**4 区**） | Converse |

FY2018 那次把「西欧 + 中东欧」并成 EMEA、「日本 + 新兴市场」并成亚太拉美，
所以 **FY2017 与 FY2018 之间的地区序列不可直接连**（本表按口径原样分行列示，
不做人工拼接；要长序列请自行按「西欧+中东欧≈EMEA」近似，并知道这不精确
—— 中东与非洲原本散在「新兴市场」里）。

## 维度标签在 XBRL 里的写法也一年一个样

同一个「北美」在各年 R 文件里印过：`NIKE Brand | North America`（FY2011-2017）、
`North America | NIKE Brand | Operating Segments`（FY2019-2021）、
`NORTH AMERICA | NIKE Brand | Operating Segments`（FY2022-2024）、
`Operating Segments | NIKE Brand | NORTH AMERICA`（FY2025-2026），
还有带脚注的 `ASIA PACIFIC & LATIN AMERICA(1)`。
故归一靠**关键词命中 + 优先级**，不靠位置、不靠精确串匹配。
优先级里地区词排在品牌词前面 —— 否则 `NIKE Brand | North America` 会先撞上
「NIKE 品牌合计」，把一个地区的钱记进合计行。
"""
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RDIR = os.path.join(HERE, "_rfiles")
FY_ALL = list(range(2009, 2027))     # FY2011 那份带 FY2009-2011 三年
TOL = 3.0                            # 分部加总容差（百万美元）

# 归一优先级：**地区在前、品牌在后**（见文件头说明）
SEG_RULES = [
    ("北美 North America",                      [r"north america"]),
    ("西欧 Western Europe",                     [r"western europe"]),
    ("中东欧 Central & Eastern Europe",         [r"central & eastern europe", r"central and eastern europe"]),
    ("EMEA 欧洲中东非洲",                        [r"europe, middle east & africa", r"emea"]),
    ("大中华 Greater China",                    [r"greater china"]),
    ("日本 Japan",                              [r"\bjapan\b"]),
    ("新兴市场 Emerging Markets",                [r"emerging markets"]),
    ("亚太拉美 Asia Pacific & Latin America",    [r"asia pacific & latin america", r"asia pacific and latin america"]),
    ("全球品牌部门 Global Brand Divisions",      [r"global brand division"]),
    ("其他业务(FY2011-2014) Other Businesses",   [r"other businesses"]),
    ("Converse",                                [r"\bconverse\b"]),
    ("公司总部 Corporate",                      [r"\bcorporate\b"]),
    ("NIKE品牌合计 NIKE Brand",                  [r"nike brand"]),
]
SEG_ORDER = [k for k, _ in SEG_RULES]
NIKE_REGIONS = SEG_ORDER[:8]
# 「NIKE 品牌合计」应当 = 各地区 + 全球品牌部门
NIKE_PARTS = NIKE_REGIONS + ["全球品牌部门 Global Brand Divisions"]

CHANNEL_RULES = [
    ("批发 Wholesale",   [r"sales to wholesale", r"wholesale customers"]),
    ("直营 NIKE Direct", [r"direct to consumer", r"nike direct"]),
]
PRODUCT_RULES = [
    ("鞋类 Footwear",  [r"^footwear$"]),
    ("服装 Apparel",   [r"^apparel$"]),
    ("装备 Equipment", [r"^equipment$"]),
    ("其他 Other",     [r"^other$"]),
]

REV_TAGS = ("us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax",
            "us-gaap_SalesRevenueNet", "us-gaap_Revenues")
EBIT_TAGS = ("nke_EarningsBeforeInterestAndTaxes",
             "us-gaap_OperatingIncomeLoss")
INV_TAGS = ("us-gaap_InventoryFinishedGoodsNetOfReserves", "us-gaap_InventoryNet")
DA_TAGS = ("us-gaap_DepreciationDepletionAndAmortization", "us-gaap_Depreciation")
CAPEX_TAGS = ("us-gaap_PaymentsToAcquirePropertyPlantAndEquipment",)


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def classify(label, rules):
    l = norm(label)
    l = re.sub(r"\(\d+\)", "", l)          # 去掉 `ASIA PACIFIC & LATIN AMERICA(1)` 的脚注号
    for name, pats in rules:
        if any(re.search(p, l) for p in pats):
            return name
    return None


def is_dim_row(row):
    """维度头行：本身没有数值，且标签像个维度名（含 `|`，或命中某条归一规则）。"""
    if any(v is not None for v in row["vals"]):
        return False
    lab = row["label"]
    if lab.endswith("[Line Items]") or lab.endswith("[Abstract]"):
        return False
    return "|" in lab or classify(lab, SEG_RULES) or classify(lab, CHANNEL_RULES) \
        or classify(lab, PRODUCT_RULES)


def col_of(st, fy):
    for i, p in enumerate(st["periods"]):
        m = re.search(r"\b((19|20)\d\d)\b", p)
        if m and int(m.group(1)) == fy and (not st["months"] or st["months"][i] in (12, None)):
            return i
    return None


def walk(st, fy, rules):
    """→ {归一后的维度名: {tag: 值}}；维度头行之前的行归入 "__TOTAL__"。"""
    idx = col_of(st, fy)
    if idx is None:
        return {}
    out, cur = {}, "__TOTAL__"
    for r in st["rows"]:
        if is_dim_row(r):
            cur = classify(r["label"], rules) or "__SKIP__"
            continue
        v = r["vals"][idx] if idx < len(r["vals"]) else None
        if v is None or cur == "__SKIP__":
            continue
        out.setdefault(cur, {}).setdefault(r["tag"], v)
    return out


def take(bucket, tags):
    for t in tags:
        if t in bucket:
            return bucket[t]
    return None


def build():
    rev, ebit, inv, da, capex = {}, {}, {}, {}, {}
    chan, prod = {}, {}
    for fy in FY_ALL:
        for ffy in range(max(fy, 2011), 2027):        # 该财年优先取自家申报
            p = os.path.join(RDIR, f"{ffy}.json")
            if not os.path.exists(p):
                continue
            sts = json.load(open(p))["statements"]
            seg = sts.get("SEG")
            if not seg or col_of(seg, fy) is None:
                continue
            w = walk(seg, fy, SEG_RULES)
            for k, b in w.items():
                key = "合计 Total" if k == "__TOTAL__" else k
                for store, tags in ((rev, REV_TAGS), (ebit, EBIT_TAGS), (inv, INV_TAGS),
                                    (da, DA_TAGS), (capex, CAPEX_TAGS)):
                    v = take(b, tags)
                    if v is not None:
                        store.setdefault(key, {}).setdefault(fy, v)
            break
        # 渠道 / 产品：DISAG（FY2019+）优先，PROD（FY2011-2019）兜底
        for src, rules, store in (("DISAG", CHANNEL_RULES, chan),
                                  ("DISAG", PRODUCT_RULES, prod),
                                  ("PROD", PRODUCT_RULES, prod)):
            for ffy in range(max(fy, 2011), 2027):
                p = os.path.join(RDIR, f"{ffy}.json")
                if not os.path.exists(p):
                    continue
                st = json.load(open(p))["statements"].get(src)
                if not st or col_of(st, fy) is None:
                    continue
                w = walk(st, fy, rules)
                for k, b in w.items():
                    if k == "__TOTAL__":
                        continue
                    v = take(b, REV_TAGS)
                    if v is not None:
                        store.setdefault(k, {}).setdefault(fy, v)
                break
    return rev, ebit, inv, da, capex, chan, prod


def check(rev, ebit, chan, prod):
    bad = []
    tot = rev.get("合计 Total", {})
    nb = rev.get("NIKE品牌合计 NIKE Brand", {})
    for fy in FY_ALL:
        if fy not in tot:
            continue
        # S1 NIKE 品牌各地区 + 全球品牌部门 = NIKE 品牌合计
        parts = [rev.get(k, {}).get(fy) for k in NIKE_PARTS]
        if nb.get(fy) is not None and any(p is not None for p in parts):
            s = sum(p for p in parts if p is not None)
            if abs(s - nb[fy]) > TOL:
                bad.append((fy, "S1 NIKE各地区+全球品牌部门=NIKE品牌合计", round(s - nb[fy], 1)))
        # S2 NIKE 品牌 + 其他品牌 + 总部 = 合计
        other = sum(rev.get(k, {}).get(fy) or 0.0
                    for k in ("其他业务(FY2011-2014) Other Businesses", "Converse",
                              "公司总部 Corporate"))
        if nb.get(fy) is not None:
            s = nb[fy] + other
            if abs(s - tot[fy]) > TOL:
                bad.append((fy, "S2 NIKE品牌+其他+总部=合计营收", round(s - tot[fy], 1)))
        # S3 渠道拆分合计 = 总营收（FY2019+ 才有）
        cs = [chan.get(k, {}).get(fy) for k in ("批发 Wholesale", "直营 NIKE Direct")]
        oth = prod.get("其他 Other", {}).get(fy) or 0.0
        if all(x is not None for x in cs):
            if abs(sum(cs) + oth - tot[fy]) > TOL:
                bad.append((fy, "S3 批发+直营+其他=合计营收", round(sum(cs) + oth - tot[fy], 1)))
        # S4 产品拆分合计 = 总营收（FY2014 起「其他」并入产品表，四项即全公司）
        ps = [prod.get(k, {}).get(fy) for k in
              ("鞋类 Footwear", "服装 Apparel", "装备 Equipment", "其他 Other")]
        if all(x is not None for x in ps):
            if abs(sum(ps) - tot[fy]) > TOL:
                bad.append((fy, "S4 鞋+服+装备+其他=合计营收", round(sum(ps) - tot[fy], 1)))
        # S4b FY2009-FY2013 的产品表**只覆盖 NIKE 品牌**（且不含全球品牌部门），
        #     所以那几年要换一条对法。不设这条，那 5 年的产品拆分等于没被任何勾稽验过。
        elif all(x is not None for x in ps[:3]) and nb.get(fy) is not None:
            s = sum(ps[:3]) + (rev.get("全球品牌部门 Global Brand Divisions", {}).get(fy) or 0.0)
            if abs(s - nb[fy]) > TOL:
                bad.append((fy, "S4b 鞋+服+装备+全球品牌部门=NIKE品牌合计", round(s - nb[fy], 1)))
        # S5 各分部 EBIT 合计 = 税前利润 + 利息净额
        parts_e = [ebit.get(k, {}).get(fy) for k in
                   NIKE_PARTS + ["其他业务(FY2011-2014) Other Businesses", "Converse",
                                 "公司总部 Corporate"]]
        te = ebit.get("合计 Total", {}).get(fy)
        if te is not None and any(p is not None for p in parts_e):
            s = sum(p for p in parts_e if p is not None)
            if abs(s - te) > TOL:
                bad.append((fy, "S5 各分部EBIT和=EBIT合计", round(s - te, 1)))
    return bad


def cross_check_with_is(rev):
    """S6 —— 分部营收合计必须等于**利润表**的营收（跨文件勾稽，不是表内自洽）。"""
    path = os.path.join(HERE, "利润表.csv")
    if not os.path.exists(path):
        return [(0, "S6 缺 利润表.csv，无法跨表核", 0)]
    rows = list(csv.reader(open(path)))
    hdr = rows[1]
    isrev = {}
    for r in rows:
        if r and r[0].startswith("营业收入"):
            for i, c in enumerate(hdr):
                if c.startswith("FY") and r[i]:
                    isrev[int(c[2:])] = float(r[i])
    bad = []
    for fy, v in rev.get("合计 Total", {}).items():
        if fy in isrev and abs(v - isrev[fy]) > TOL:
            bad.append((fy, "S6 分部合计营收=利润表营收", round(v - isrev[fy], 1)))
    return bad


def write(name, header, order, store, extra=None):
    path = os.path.join(HERE, name)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"# {header}"])
        w.writerow(["分部"] + [f"FY{y}" for y in FY_ALL])
        for k in order:
            if k not in store:
                continue
            w.writerow([k] + [("" if store[k].get(y) is None else f"{store[k][y]:g}")
                              for y in FY_ALL])
        for k in sorted(set(store) - set(order)):
            w.writerow([k] + [("" if store[k].get(y) is None else f"{store[k][y]:g}")
                              for y in FY_ALL])
        if extra:
            for row in extra:
                w.writerow(row)
    print(f"  写出 {name}")


# ── 老口径分部（FY1997-FY2009，来自 `_legacy/`）──────────────────────────────
LDIR = os.path.join(HERE, "_legacy")
OLD_SEG_RULES = [
    ("美国 United States",                 [r"^united states$"]),
    # 这一格的名字改过三次：Europe(FY1998-2000) → EMEA(FY2001-2002) →
    # Europe, Middle East and Africa(FY2003-2009)。只认 `^europe` 会漏掉 EMEA 那两年，
    # 而那两年恰好每年少 25 亿美元营收（FY2001 差 −6774.5 就是这么来的：
    # 少的不只是欧洲，是「欧洲」这一行整条没进来）。
    ("欧洲/EMEA Europe (FY2002起含中东非洲)", [r"^(europe|emea)"]),
    # FY2002 那份印的是「Asia/ Pacific」（斜杠后**多一个空格**）。写死 `asia[ /]pacific`
    # 会在这一年落空，然后被 FY2003 的比较列顶上 —— 而 FY2003 把 FY2002 亚太
    # 重述下调了 69.5（重分类进 Other）。于是本该是 as-reported 的 1211.7 变成重述后的
    # 1142.2，分部合计比利润表少 69.5。**一个空格 = 一次静默换源。**
    ("亚太 Asia Pacific",                  [r"^asia\s*/?\s*pacific$"]),
    ("美洲(除美国) Americas",               [r"^americas$"]),
    ("其他品牌 Other brands",               [r"^other brands$", r"^other$"]),
    ("公司总部 Corporate",                  [r"^corporate$"]),
]
OLD_SEG_ORDER = [k for k, _ in OLD_SEG_RULES]
# 段首行同样一年一个写法。🔴 FY2001-2002 的利润段叫「**Management** Pre-tax Income」
# ——NIKE 那两年披露的是管理口径税前利润（与 GAAP 税前有差异），本表原样保留、不换算。
SECTION_RULES = [
    ("营收", [r"^net revenue$"]),
    ("利润", [r"^contribution profit$", r"^(management )?pre-tax income$",
              r"^earnings before interest and taxes$"]),
    ("资产", [r"^assets$", r"^total assets$"]),
    ("资本开支", [r"^additions to long-lived assets$", r"^capital expenditures$"]),
    ("折旧", [r"^depreciation$"]),
    ("应收账款", [r"^accounts receivable, net$"]),
    ("存货", [r"^inventories$"]),
]


def build_old_segments():
    """→ {"营收": {分部: {fy: 值}}, "利润": {...}, …}

    🔴 老分部表**同一个地区名在一张表里出现好几次**（营收段一次、利润段一次、
    资产段一次…），只按标签取会全部撞在第一段上。必须按「段首行」切段后再取。
    """
    out = {}
    for ffy in range(1995, 2011):
        p = os.path.join(LDIR, f"{ffy}.json")
        if not os.path.exists(p):
            continue
        st = json.load(open(p))["statements"].get("SEG")
        if not st:
            continue
        sec = None
        for r in st["rows"]:
            lab = norm(r["label"])
            hit = next((n for n, pats in SECTION_RULES if any(re.match(x, lab) for x in pats)), None)
            if hit and all(v is None for v in r["vals"]):
                sec = hit
                continue
            if sec is None:
                continue
            seg = next((n for n, pats in OLD_SEG_RULES if any(re.match(x, lab) for x in pats)), None)
            if not seg:
                continue
            for i, fy in enumerate(st["years"]):
                v = r["vals"][i] if i < len(r["vals"]) else None
                if v is None:
                    continue
                # as-reported：该财年优先用自家申报；否则用离它最近的那份
                cur = out.setdefault(sec, {}).setdefault(seg, {})
                if fy not in cur or ffy == fy:
                    cur[fy] = v * st["scale"]
    return out


def check_old_segments(old, isrev):
    bad = []
    for fy, tot in isrev.items():
        parts = [old.get("营收", {}).get(k, {}).get(fy) for k in OLD_SEG_ORDER[:5]]
        if all(p is None for p in parts):
            continue
        s = sum(p for p in parts if p is not None)
        if abs(s - tot) > TOL:
            bad.append((fy, "S7 老口径分部营收和=利润表营收", round(s - tot, 1)))
    return bad


# ── 长期摘要（FY1988-FY1992 的唯一来源）─────────────────────────────────────
SUM_KEEP = [
    ("营业收入 Revenues", r"^revenues$"),
    ("毛利 Gross margin", r"^gross margin$"),
    ("毛利率% Gross margin %", r"^gross margin %$"),
    ("净利润 Net income", r"^net income$"),
    ("经营现金流 Cash flow from operations", r"^cash flow from operations$"),
    ("货币资金 Cash and equivalents", r"^cash and equivalents$"),
    ("存货 Inventories", r"^inventories$"),
    ("营运资本 Working capital", r"^working capital$"),
    ("总资产 Total assets", r"^total assets$"),
    ("长期债务 Long-term debt", r"^long-term debt$"),
    ("股东权益 Common shareholders' equity", r"^common shareholders. equity$"),
    ("地区营收·美国 United States", r"^united states$"),
    ("地区营收·欧洲 Europe", r"^europe$"),
    ("地区营收·亚太 Asia/Pacific", r"^asia[ /]pacific$"),
    ("地区营收·加拿大拉美及其他", r"^canada, latin america, and other$"),
]


def build_summary():
    """从各年 10-K 的「Selected Financial Data」抽长期序列。

    只用来补 **FY1988-FY1992** —— 那 5 年 EDGAR 上没有 NIKE 的任何申报
    （最早一份是 1995-01-17 的 10-Q），三表也捎不回来。
    FY1993 起的年份同样抽出来，但只作**独立交叉核**用（应与 利润表/资产负债表 对得上）。
    ⚠️ 股价行（High / Low / Year-end stock price）一律不收：
    老版式印的是 `80-5/8` 这种分数报价，任何数值解析都会把它读错（实测 5/8 被读成 8）。
    """
    out, src = {}, {}
    for ffy in (1996, 1997, 1995, 1998):      # FY1996 那份覆盖 1988-1996，最全，排第一
        p = os.path.join(LDIR, f"{ffy}.json")
        if not os.path.exists(p):
            continue
        st = json.load(open(p))["statements"].get("SUM")
        if not st:
            continue
        for r in st["rows"]:
            lab = norm(r["label"])
            name = next((n for n, pat in SUM_KEEP if re.match(pat, lab)), None)
            if not name:
                continue
            for i, fy in enumerate(st["years"]):
                v = r["vals"][i] if i < len(r["vals"]) else None
                if v is None:
                    continue
                sc = 1.0 if "%" in name else st["scale"]
                out.setdefault(name, {}).setdefault(fy, v * sc)
                src.setdefault(fy, ffy)
    return out, src


def cross_check_summary(summ):
    """长期摘要 vs 三表：重叠年份必须对上（这是对最老那批数据的独立验证）。"""
    bad = []
    for csvname, pairs in (("利润表.csv", [("营业收入 Revenues", "营业收入 Revenues"),
                                           ("净利润 Net income", "净利润 Net income")]),
                           ("资产负债表.csv", [("总资产 Total assets", "总资产 TOTAL ASSETS"),
                                              ("存货 Inventories", "存货 Inventories"),
                                              ("股东权益 Common shareholders' equity",
                                               "股东权益合计 Total shareholders' equity")])):
        path = os.path.join(HERE, csvname)
        if not os.path.exists(path):
            continue
        rows = list(csv.reader(open(path)))
        hdr = rows[1]
        for sname, cname in pairs:
            ref = {}
            for r in rows:
                if r and r[0] == cname:
                    for i, c in enumerate(hdr):
                        if c.startswith("FY") and r[i]:
                            ref[int(c[2:])] = float(r[i])
            for fy, v in summ.get(sname, {}).items():
                if fy in ref and abs(v - ref[fy]) > max(TOL, abs(ref[fy]) * 0.002):
                    bad.append((fy, f"S8 长期摘要「{sname[:8]}」≠三表", round(v - ref[fy], 1)))
    return bad


def is_revenue():
    path = os.path.join(HERE, "利润表.csv")
    rows = list(csv.reader(open(path)))
    hdr = rows[1]
    out = {}
    for r in rows:
        if r and r[0].startswith("营业收入"):
            for i, c in enumerate(hdr):
                if c.startswith("FY") and r[i]:
                    out[int(c[2:])] = float(r[i])
    return out


def main():
    rev, ebit, inv, da, capex, chan, prod = build()
    old = build_old_segments()
    summ, summ_src = build_summary()
    bad = (check(rev, ebit, chan, prod) + cross_check_with_is(rev)
           + check_old_segments(old, is_revenue()) + cross_check_summary(summ))
    if bad:
        print(f"🔴 分部勾稽未过 {len(bad)} 条（不写出）：")
        for fy, nm, dv in bad[:60]:
            print(f"  FY{fy} {nm}: 差 {dv}")
        if "--force" not in sys.argv:
            sys.exit(1)
    else:
        print("✅ 分部勾稽全过")

    # ⚠️ 不能写成 ["合计","NIKE品牌合计"] + SEG_ORDER —— SEG_ORDER 末尾本来就有
    #    「NIKE品牌合计」，那样会让它在 CSV 里出现两行（同样的数，看着像两个分部）。
    order = ["合计 Total"] + [k for k in SEG_ORDER if k != "NIKE品牌合计 NIKE Brand"]
    order.insert(1, "NIKE品牌合计 NIKE Brand")
    write("分部营收.csv",
          "单位: 百万美元 | 财年截至 5 月 31 日 | as-reported | "
          "🔴 地区口径 FY2018 起从 6 区并成 4 区(西欧+中东欧→EMEA、日本+新兴市场→亚太拉美)，"
          "FY2017 与 FY2018 之间不可直接连 | 非 NIKE 品牌 FY2011-2014 叫「其他业务」(含 Cole Haan/Umbro/Hurley)、"
          "FY2015 起才是纯 Converse | 空=该年该口径不存在",
          order, rev)
    write("分部经营利润.csv",
          "单位: 百万美元 | 分部利润口径 = EBIT(税息前利润)，NIKE 不披露分部净利 | "
          "「全球品牌部门」与「公司总部」为**净成本中心**故常年为负 | as-reported | "
          "地区口径断点同 分部营收.csv",
          order, ebit)
    prod_chan = {}
    prod_chan.update({k: v for k, v in prod.items()})
    prod_chan.update({k: v for k, v in chan.items()})
    write("分产品与渠道营收.csv",
          "单位: 百万美元 | 两个互相独立的切口: ①按产品(鞋/服/装备/其他) ②按渠道(批发/直营) | "
          "🔴 渠道拆分自 FY2019 采用 ASC606 后才披露，更早年份为空(不是零) | "
          "🔴 FY2009-FY2013 的产品拆分**只覆盖 NIKE 品牌本体**(不含全球品牌部门、不含其他业务)，"
          "三项之和 ≠ 合计营收；FY2014 起才是全公司口径 | as-reported",
          [k for k, _ in PRODUCT_RULES] + [k for k, _ in CHANNEL_RULES], prod_chan)

    # 分部存货/折旧/capex 合并成一张更实用的表
    merged = {}
    for pref, store in (("存货", inv), ("折旧摊销", da), ("资本开支", capex)):
        for k, v in store.items():
            merged[f"{pref}·{k}"] = v
    write("分部存货与资本开支.csv",
          "单位: 百万美元 | 存货=财年末时点，折旧摊销/资本开支=财年全年 | as-reported | "
          "行名前缀标指标，后缀标分部",
          [f"{p}·{k}" for p in ("存货", "折旧摊销", "资本开支") for k in order], merged)

    # 老口径分部（FY1997-FY2009）单独成表 —— 与新表**不可拼接**，故不混在一张里
    global FY_ALL
    keep = FY_ALL
    FY_ALL = list(range(1997, 2011))
    oldmerged = {}
    for sec in ("营收", "利润", "资产", "资本开支", "折旧"):
        for k, v in old.get(sec, {}).items():
            oldmerged[f"{sec}·{k}"] = v
    write("分部营收-老口径FY1997-2009.csv",
          "单位: 百万美元 | 🔴 **老口径**: 美国 / 欧洲(FY2002 起改称 EMEA) / 亚太 / 美洲 / 其他品牌 —— "
          "与 分部营收.csv 的 FY2011 起口径(6 区或 4 区)**不是一回事，不可拼接**。"
          "利润口径 FY1998-2001 叫 Contribution Profit、FY2002-2009 叫 Pre-tax Income(均为税前、已扣总部费用前) | "
          "FY2010 的分部附注未解析到(R 轨已覆盖 FY2009-2010，见 分部营收.csv) | as-reported",
          [f"{s}·{k}" for s in ("营收", "利润", "资产", "资本开支", "折旧") for k in OLD_SEG_ORDER],
          oldmerged)

    FY_ALL = list(range(1988, 1999))
    write("长期摘要FY1988-1998.csv",
          "单位: 百万美元(比率为%) | 来源 = 各年 10-K 的「Selected Financial Data」八年摘要表 | "
          "🔴 **FY1988-FY1992 是本库这 5 年的唯一数据源** —— EDGAR 上 NIKE 最早的申报是 "
          "1995-01-17 的 10-Q，那 5 年没有自家 10-K、三表也捎不回来 | "
          "FY1993 起的年份与 利润表.csv / 资产负债表.csv 重叠，已做交叉核(S8) | "
          "⚠️ 不收股价行(老版式印 `80-5/8` 分数报价，数值解析必错)",
          [n for n, _ in SUM_KEEP], summ,
          extra=[[], ["# 各财年取自哪一份 10-K 的摘要表："],
                 ["财年"] + [f"FY{y}" for y in range(1988, 1999)],
                 ["来源申报"] + [f"FY{summ_src[y]}10-K" if y in summ_src else ""
                                for y in range(1988, 1999)]])
    FY_ALL = keep


if __name__ == "__main__":
    main()
