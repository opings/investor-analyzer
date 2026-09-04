#!/usr/bin/env python3
"""AGC(5201) 三表 + 分部 + 长期序列 CSV 生成器 —— _extract_json/fy*.json → CSV

年份口径
  IFRS 全表（FY2012-FY2025）：各年取**该年有報的「当期」列**（as-reported）；
    FY2012 = FY2013 有報的「前期」列（IFRS 移行日 2012-01-01，该年为 IFRS 比较期）。
  JGAAP 长期序列（FY2009-FY2012）：取自有報「主要な経営指標等の推移」5 年表（人工提取层，
    页码可引、并用两份有報重叠年互证）——**JGAAP 与 IFRS 不可直接同比**，CSV 分段标注。

单位：百万円（年报原始口径）。△ 已在提取层转成负号。

用法：python3 _build_from_pdf.py [--write]
"""
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
JDIR = os.path.join(HERE, "_extract_json")

IFRS_YEARS = list(range(2012, 2026))
TOL = 1.0          # 百万円；解析值应精确相等

# AGC 报告分部数逐年变（FY2013-2021 为 4 个；近年拆成 6 个）。
# CSV 按**历年并集**出行，未披露的年份留空——留空 = 该年未按此分部列报，不是没有该业务。
SEG_ALL = ["ガラス", "建築ガラス", "オートモーティブ", "電子", "化学品",
           "ライフサイエンス", "セラミックス・その他"]
SEG_ITEMS_OUT = ["外部売上高", "セグメント間売上高", "売上高計", "セグメント利益",
                 "減価償却費", "減損損失", "資本的支出"]
# 分部表按百万円四舍五入列示，各分部相加与合計可差几个百万——非解析错
SEG_TOL = 20.0


# 🚨 分部口径断点：FY2022 起 AGC 把 4 分部拆成 6 分部——
#    ガラス → 建築ガラス + オートモーティブ；化学品 → 化学品 + ライフサイエンス
#    （FY2022 有報同时列了两套：旧口径 化学品 793,159 = 新口径 化学品 655,013 + ライフサイエンス 138,146）。
#    所以**「化学品」这个名字在断点两侧不是同一个东西**，直接拉一条时间序列会得出
#    「化学品收入 2022 年突然掉 17%」的假象。CSV 按两套口径分组出行，各自标注可用年份。
SCHEMA_OLD, SCHEMA_NEW = 4, 6
SEG_OLD = ["ガラス", "電子", "化学品", "セラミックス・その他"]
SEG_NEW = ["建築ガラス", "オートモーティブ", "電子", "化学品", "ライフサイエンス",
           "セラミックス・その他"]
SEG_ITEMS_OUT = ["外部売上高", "セグメント間売上高", "売上高計", "セグメント利益",
                 "減価償却費", "減損損失", "資本的支出"]
SEG_TOL = 20.0     # 分部表按百万円四舍五入，分部相加与合計可差几个百万——非解析错


def seg_block(y, n):
    """取该年、该口径(n 个分部)的**当期**块。

    换口径那年（FY2022）报告里有 3 块：[前期旧, 当期旧, 当期新]——
    取「最后一个 _n 匹配的块」即为当期。FY2012 特例走 FY2013 报告的第一块（前期）。
    """
    if y == 2012:
        blocks = (RAW.get(2013) or {}).get("data", {}).get("SEG") or []
        cand = [b for b in blocks if b.get("_n") == n]
        return cand[0] if cand else None
    blocks = (RAW.get(y) or {}).get("data", {}).get("SEG") or []
    cand = [b for b in blocks if b.get("_n") == n]
    return cand[-1] if cand else None


def seg_val(y, item, name, n):
    b = seg_block(y, n)
    if not b or item not in b:
        return None
    return b[item].get(name)


def load():
    d = {}
    for fn in os.listdir(JDIR):
        if not fn.startswith("fy") or not fn.endswith(".json"):
            continue
        j = json.load(open(os.path.join(JDIR, fn), encoding="utf-8"))
        y = j.get("year")
        if str(y).isdigit():
            # 有報 优先于 決算短信（同年两份时取有報：审计过 + 附注全）
            prev = d.get(int(y))
            if prev is None or "有価証券報告書" in j.get("src", ""):
                d[int(y)] = j
    return d


RAW = load()


def cell(rep_year, kind, concept, col):
    j = RAW.get(rep_year)
    if not j:
        return None
    v = j["data"].get(kind, {}).get(concept)
    if not v or len(v) <= col:
        return None
    return v[col]


def val(year, kind, concept):
    """canonical：FY2012 走 FY2013 有報前期列，其余走当年报告当期列。"""
    if year == 2012:
        return cell(2013, kind, concept, 0)
    return cell(year, kind, concept, 1)


# ---------------------------------------------------------------- 行定义

IS_ROWS = [
    ("売上高", "売上高"), ("売上原価", "売上原価"), ("売上総利益", "売上総利益"),
    ("販売費及び一般管理費", "販売費及び一般管理費"),
    ("持分法による投資損益", "持分法による投資損益"),
    ("営業利益", "営業利益"),
    ("その他収益", "その他収益"), ("その他費用", "その他費用"),
    ("事業利益", "事業利益"),
    ("金融収益", "金融収益"), ("金融費用", "金融費用"),
    ("税引前利益", "税引前利益"), ("法人所得税費用", "法人所得税費用"),
    ("当期純利益", "当期純利益"),
    ("親会社所有者帰属当期純利益", "親会社の所有者に帰属する当期純利益"),
    ("非支配持分帰属当期純利益", "非支配持分に帰属する当期純利益"),
    ("基本的1株当たり当期純利益", "基本的1株当たり当期純利益(円)"),
    ("希薄化後1株当たり当期純利益", "希薄化後1株当たり当期純利益(円)"),
]

BS_ROWS = [
    ("現金及び現金同等物", "現金及び現金同等物"), ("営業債権", "営業債権"),
    ("棚卸資産", "棚卸資産"), ("その他の債権", "その他の債権"),
    ("その他の流動資産", "その他の流動資産"), ("流動資産合計", "流動資産合計"),
    ("有形固定資産", "有形固定資産"), ("のれん", "のれん"), ("無形資産", "無形資産"),
    ("持分法投資", "持分法で会計処理されている投資"),
    ("その他の金融資産", "その他の金融資産"), ("繰延税金資産", "繰延税金資産"),
    ("その他の非流動資産", "その他の非流動資産"),
    ("非流動資産合計", "非流動資産合計"), ("資産合計", "資産合計"),
    ("営業債務", "営業債務"), ("短期有利子負債", "短期有利子負債"),
    ("1年内返済予定長期有利子負債", "1年内返済予定の長期有利子負債"),
    ("その他の債務", "その他の債務"), ("流動負債合計", "流動負債合計"),
    ("長期有利子負債", "長期有利子負債"), ("繰延税金負債", "繰延税金負債"),
    ("退職給付に係る負債", "退職給付に係る負債"),
    ("非流動負債合計", "非流動負債合計"), ("負債合計", "負債合計"),
    ("資本金", "資本金"), ("資本剰余金", "資本剰余金"), ("利益剰余金", "利益剰余金"),
    ("自己株式", "自己株式"), ("その他の資本の構成要素", "その他の資本の構成要素"),
    ("親会社所有者帰属持分合計", "親会社の所有者に帰属する持分合計"),
    ("非支配持分", "非支配持分"), ("資本合計", "資本合計"),
    ("負債及び資本合計", "負債及び資本合計"),
]

CF_ROWS = [
    ("税引前利益_CF", "税引前利益(CF起点)"),
    ("減価償却費及び償却費", "減価償却費及び償却費"),
    ("減損損失_CF", "減損損失"),
    ("営業CF小計", "営業活動CF小計"),
    ("法人所得税の支払額", "法人所得税の支払額"),
    ("営業活動によるキャッシュフロー", "営業活動によるキャッシュ・フロー"),
    ("capex", "有形固定資産及び無形資産の取得による支出(capex)"),
    ("有形固定資産の売却収入", "有形固定資産の売却による収入"),
    ("投資活動によるキャッシュフロー", "投資活動によるキャッシュ・フロー"),
    ("配当金の支払額", "配当金の支払額"),
    ("財務活動によるキャッシュフロー", "財務活動によるキャッシュ・フロー"),
    ("換算差額", "現金及び現金同等物に係る換算差額"),
    ("売却目的保有資産の現金増減", "売却目的で保有する資産に含まれる現金及び現金同等物の増減額"),
    ("現金及び現金同等物の増減額", "現金及び現金同等物の増減額"),
    ("現金及び現金同等物の期首残高", "現金及び現金同等物の期首残高"),
    ("現金及び現金同等物の期末残高", "現金及び現金同等物の期末残高"),
]


# ------------------------------------------------- JGAAP 长期序列（人工提取层）
# 来源：AGC-FY2013-有価証券報告書.pdf P5「(1)連結経営指標等 / 日本基準」第85-89期
#      （本文件把印刷值原样录入，便于逐格回查；FY2012/FY2013 两年用
#        AGC-FY2016-有価証券報告書.pdf P5 的同一张表独立互证，见 check_jgaap）
JGAAP = {
    #        FY2009      FY2010      FY2011      FY2012      FY2013
    "売上高":        {2009: 1148198, 2010: 1288947, 2011: 1214672, 2012: 1189956, 2013: 1320006},
    "経常利益":      {2009: 87207, 2010: 226806, 2011: 166739, 2012: 86621, 2013: 63143},
    "当期純利益":    {2009: 19985, 2010: 123184, 2011: 95290, 2012: 43790, 2013: 10333},
    "純資産額":      {2009: 808312, 2010: 849815, 2011: 850460, 2012: 996949, 2013: 1151870},
    "総資産額":      {2009: 1781875, 2010: 1764038, 2011: 1691556, 2012: 1899373, 2013: 2119664},
    "自己資本比率(%)": {2009: 42.36, 2010: 45.82, 2011: 47.73, 2012: 49.59, 2013: 51.50},
    "自己資本利益率(%)": {2009: 2.69, 2010: 15.76, 2011: 11.80, 2012: 5.01, 2013: 1.02},
    "営業CF":        {2009: 180683, 2010: 285669, 2011: 152223, 2012: 170165, 2013: 167377},
    "投資CF":        {2009: -115563, 2010: -124644, 2011: -123581, 2012: -157407, 2013: -147957},
    "財務CF":        {2009: -30092, 2010: -100797, 2011: -60833, 2012: -5305, 2013: -31584},
    "従業員数(名)":  {2009: 47618, 2010: 50399, 2011: 50957, 2012: 49961, 2013: 51448},
}
# FY2016 有報 P5 同表（第88/89期）——独立互证用
JGAAP_XCHK = {"売上高": {2012: 1189956, 2013: 1320006},
              "経常利益": {2012: 86621, 2013: 63143},
              "当期純利益": {2012: 43790, 2013: 10333},
              "総資産額": {2012: 1899373, 2013: 2119664}}


# ---------------------------------------------------------------- 校验

def s(*xs):
    v = [x for x in xs if x is not None]
    return sum(v) if v else None


def chk(errs, y, name, lhs, rhs, tol=TOL):
    if lhs is None or rhs is None:
        return
    if abs(lhs - rhs) > tol:
        errs.append(f"FY{y} 勾稽✗ {name}: {lhs:,.0f} vs {rhs:,.0f} 差 {lhs - rhs:,.0f}")


def check_internal(y, errs):
    V = lambda k, c: val(y, k, c)
    # 损益（IFRS：売上原価/販管費/その他費用/金融費用/法人所得税費用 均以负数列示）
    chk(errs, y, "売上高+売上原価=売上総利益",
        s(V("IS", "売上高"), V("IS", "売上原価")), V("IS", "売上総利益"))
    chk(errs, y, "売上総利益+販管費+持分法=営業利益",
        s(V("IS", "売上総利益"), V("IS", "販売費及び一般管理費"),
          V("IS", "持分法による投資損益")), V("IS", "営業利益"))
    chk(errs, y, "営業利益+その他収益+その他費用=事業利益",
        s(V("IS", "営業利益"), V("IS", "その他収益"), V("IS", "その他費用")),
        V("IS", "事業利益"))
    chk(errs, y, "事業利益+金融収益+金融費用=税引前利益",
        s(V("IS", "事業利益"), V("IS", "金融収益"), V("IS", "金融費用")),
        V("IS", "税引前利益"))
    chk(errs, y, "税引前利益+法人所得税費用=当期純利益",
        s(V("IS", "税引前利益"), V("IS", "法人所得税費用")), V("IS", "当期純利益"))
    chk(errs, y, "親会社帰属+非支配持分帰属=当期純利益",
        s(V("IS", "親会社所有者帰属当期純利益"), V("IS", "非支配持分帰属当期純利益")),
        V("IS", "当期純利益"))
    # 财政状态
    chk(errs, y, "流動+非流動=資産合計",
        s(V("BS", "流動資産合計"), V("BS", "非流動資産合計")), V("BS", "資産合計"))
    chk(errs, y, "流動負債+非流動負債=負債合計",
        s(V("BS", "流動負債合計"), V("BS", "非流動負債合計")), V("BS", "負債合計"))
    chk(errs, y, "親会社帰属持分+非支配持分=資本合計",
        s(V("BS", "親会社所有者帰属持分合計"), V("BS", "非支配持分")), V("BS", "資本合計"))
    chk(errs, y, "負債+資本=負債及び資本合計",
        s(V("BS", "負債合計"), V("BS", "資本合計")), V("BS", "負債及び資本合計"))
    chk(errs, y, "資産合計=負債及び資本合計",
        V("BS", "資産合計"), V("BS", "負債及び資本合計"))
    # 现金流
    # AGC 现金流量表按千円计算、按百万円列示，四项相加与「増減額」常有 1-3 百万円的
    # **印刷舍入残差**（FY2014 差 1、FY2015 差 3，逐行核对确认无遗漏科目）→ 容差 10。
    # 「期首+増減=期末」不受影响，仍按 1 百万円严格校验。
    chk(errs, y, "営業+投資+財務+換算差額+売却目的保有現金=増減額",
        s(V("CF", "営業活動によるキャッシュフロー"), V("CF", "投資活動によるキャッシュフロー"),
          V("CF", "財務活動によるキャッシュフロー"), V("CF", "換算差額"),
          V("CF", "売却目的保有資産の現金増減")),
        V("CF", "現金及び現金同等物の増減額"), tol=10.0)
    chk(errs, y, "期首+増減額=期末",
        s(V("CF", "現金及び現金同等物の期首残高"), V("CF", "現金及び現金同等物の増減額")),
        V("CF", "現金及び現金同等物の期末残高"))
    # 现金流量表期末现金 应等于 财政状态表现金
    chk(errs, y, "CF期末現金=BS現金及び現金同等物",
        V("CF", "現金及び現金同等物の期末残高"), V("BS", "現金及び現金同等物"))


REQUIRED = [("IS", "売上高"), ("IS", "営業利益"), ("IS", "事業利益"), ("IS", "当期純利益"),
            ("IS", "親会社所有者帰属当期純利益"),
            ("BS", "資産合計"), ("BS", "資本合計"), ("BS", "親会社所有者帰属持分合計"),
            ("BS", "有形固定資産"), ("BS", "現金及び現金同等物"),
            ("CF", "営業活動によるキャッシュフロー"), ("CF", "capex"),
            ("CF", "現金及び現金同等物の期末残高")]


def check_required(errs):
    for kind, c in REQUIRED:
        miss = [y for y in IFRS_YEARS if val(y, kind, c) is None]
        if miss:
            errs.append(f"完整性✗ {kind}/{c} 缺 {len(miss)} 年：{miss}")


def check_continuity(errs):
    for y in IFRS_YEARS[:-1]:
        a = val(y, "CF", "現金及び現金同等物の期末残高")
        b = val(y + 1, "CF", "現金及び現金同等物の期首残高")
        if a is not None and b is not None and abs(a - b) > TOL:
            errs.append(f"FY{y}→{y+1} 现金连续性✗ 期末 {a:,.0f} vs 次年期首 {b:,.0f}")


XSRC = [("IS", "売上高"), ("IS", "営業利益"), ("IS", "親会社所有者帰属当期純利益"),
        ("BS", "資産合計"), ("BS", "資本合計"),
        ("CF", "営業活動によるキャッシュフロー")]


def check_cross_source():
    """报告 Y+1 的「前期」列 vs 本库 Y 年值。IFRS 下 AGC 未见重述，应逐格相等。"""
    out = []
    for y in IFRS_YEARS[:-1]:
        for kind, c in XSRC:
            a, b = cell(y + 1, kind, c, 0), val(y, kind, c)
            if a is None or b is None or abs(a - b) <= TOL:
                continue
            out.append(f"FY{y} {kind}/{c}: 本库 {b:,.0f} → 次年报告前期列 {a:,.0f} 差 {a - b:,.0f}")
    return out


def check_jgaap():
    """JGAAP 人工提取层 vs FY2016 有報同表 独立互证。"""
    bad = []
    for metric, ys in JGAAP_XCHK.items():
        for y, v in ys.items():
            mine = JGAAP.get(metric, {}).get(y)
            if mine is None or abs(mine - v) > TOL:
                bad.append(f"JGAAP {metric} FY{y}: 本库 {mine} vs FY2016有報 {v}")
    return bad


def check_segments(errs):
    """① 各分部外部売上高之和 ≈ 連結売上高；② 分部利益之和 ≈ 合計列。两套口径分别验。"""
    for y in IFRS_YEARS:
        for n in (SCHEMA_OLD, SCHEMA_NEW):
            b = seg_block(y, n)
            if not b:
                continue
            if not b.get("_schema_ok"):
                errs.append(f"FY{y} 分部✗ 未识别 schema（分部数 {b.get('_n')}）")
                continue
            if b.get("_hdr_missing"):
                errs.append(f"FY{y} 分部✗ 表头缺名 {b['_hdr_missing']}")
            names = b.get("_names") or []
            ext = b.get("外部売上高") or {}
            tot = s(*[ext.get(x) for x in names])
            rev = val(y, "IS", "売上高")
            if tot and rev and abs(tot - rev) > SEG_TOL:
                errs.append(f"FY{y}[{n}分部] 外部売上高合计 {tot:,.0f} vs 売上高 {rev:,.0f} "
                            f"差 {tot-rev:,.0f}")
            prof = b.get("セグメント利益") or {}
            ptot = s(*[prof.get(x) for x in names])
            # 与「合計」列比，不与「連結財務諸表計上額」比——
            # 两者之差正是**調整額**（全社费用/内部消去），本就不该为零。
            psum = prof.get("_合計")
            if ptot is not None and psum is not None and abs(ptot - psum) > SEG_TOL:
                errs.append(f"FY{y}[{n}分部] 分部利益合计 {ptot:,.0f} vs 合計列 {psum:,.0f}")


# ---------------------------------------------------------------- 输出

def fmt(v, nd=0):
    return "" if v is None else f"{v:.{nd}f}"


def write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main():
    write = "--write" in sys.argv
    errs = []
    for y in IFRS_YEARS:
        check_internal(y, errs)
    check_required(errs)
    check_continuity(errs)
    check_segments(errs)
    diffs = check_cross_source()
    jbad = check_jgaap()

    print(f"载入报告年份：{sorted(RAW)}")
    print(f"=== ① 表内勾稽 + 完整性 + 连续性 + 分部：{len(errs)} 处不平")
    for e in errs:
        print("   " + e)
    print(f"=== ② 跨源互证（次年前期列 vs 本库）：{len(diffs)} 处差异")
    for e in diffs:
        print("   " + e)
    print(f"=== ③ JGAAP 人工层互证（FY2013有報 vs FY2016有報）：{len(jbad)} 处不符")
    for e in jbad:
        print("   " + e)

    if errs or jbad:
        print("\n🔴 校验未通过，不写出 CSV")
        return 1
    print("\n✅ 校验通过")
    if not write:
        print("（未加 --write，仅校验）")
        return 0

    hdr = ["科目"] + [str(y) for y in IFRS_YEARS]
    write_csv(os.path.join(HERE, "利润表.csv"), hdr,
              [[d] + [fmt(val(y, "IS", c)) for y in IFRS_YEARS] for c, d in IS_ROWS])
    write_csv(os.path.join(HERE, "资产负债表.csv"), hdr,
              [[d] + [fmt(val(y, "BS", c)) for y in IFRS_YEARS] for c, d in BS_ROWS])
    write_csv(os.path.join(HERE, "现金流量表.csv"), hdr,
              [[d] + [fmt(val(y, "CF", c)) for y in IFRS_YEARS] for c, d in CF_ROWS])

    # 分部：两套口径分组出行。行名带 [旧4分部]/[新6分部] 前缀，
    # 提醒「化学品」「ガラス」在断点两侧定义不同、不可直接拉一条线。
    seg_rows = []
    for tag, n, names in (("旧4分部", SCHEMA_OLD, SEG_OLD), ("新6分部", SCHEMA_NEW, SEG_NEW)):
        for item in SEG_ITEMS_OUT:
            for name in names:
                vals = [seg_val(y, item, name, n) for y in IFRS_YEARS]
                if all(v is None for v in vals):
                    continue
                seg_rows.append([f"[{tag}]{name}_{item}"] + [fmt(v) for v in vals])
    write_csv(os.path.join(HERE, "分部营收.csv"), hdr, seg_rows)

    # 长期序列（JGAAP + IFRS 分段）
    long_years = list(range(2009, 2026))
    lh = ["指标(口径)"] + [str(y) for y in long_years]
    lrows = []
    for m in ["売上高", "経常利益", "当期純利益", "純資産額", "総資産額",
              "自己資本比率(%)", "自己資本利益率(%)", "営業CF", "投資CF", "財務CF",
              "従業員数(名)"]:
        nd = 2 if "%" in m else 0
        lrows.append([f"[日本基準]{m}"] +
                     [fmt(JGAAP.get(m, {}).get(y), nd) for y in long_years])
    for concept, disp in [("売上高", "売上高"), ("営業利益", "営業利益"),
                          ("事業利益", "事業利益"), ("当期純利益", "当期純利益"),
                          ("親会社所有者帰属当期純利益", "親会社帰属当期純利益")]:
        lrows.append([f"[IFRS]{disp}"] +
                     [fmt(val(y, "IS", concept)) if y in IFRS_YEARS else "" for y in long_years])
    for concept, disp in [("資産合計", "総資産"), ("親会社所有者帰属持分合計", "親会社帰属持分"),
                          ("資本合計", "資本合計")]:
        lrows.append([f"[IFRS]{disp}"] +
                     [fmt(val(y, "BS", concept)) if y in IFRS_YEARS else "" for y in long_years])
    for concept, disp in [("営業活動によるキャッシュフロー", "営業CF"), ("capex", "capex")]:
        lrows.append([f"[IFRS]{disp}"] +
                     [fmt(val(y, "CF", concept)) if y in IFRS_YEARS else "" for y in long_years])
    write_csv(os.path.join(HERE, "长期业绩序列.csv"), lh, lrows)

    print("已写出 利润表.csv / 资产负债表.csv / 现金流量表.csv / 分部营收.csv / 长期业绩序列.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
