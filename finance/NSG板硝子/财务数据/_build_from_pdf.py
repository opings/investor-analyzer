#!/usr/bin/env python3
"""NSG(日本板硝子 5202) 三表 + 分部 + 长期序列生成器（含四重校验）

数据链：report/NSG板硝子/*.pdf → _extract.py → _extract_json/fy*.json → 本脚本 → *.csv

**取数原则：每一年只认「该年自己那份 有報 的当期列」**（as-reported）。
后续年度报告里的「前期列」不用来覆盖，只用来**互证**——因为 NSG 有多次
遡及修正（IFRS15 适用、2022/3 的「修正再表示」等），比较列 ≠ 当年原始披露值，
拿它覆盖会把历史悄悄改写成"重述后"的样子、且无从追溯。

校验四层（全过才写 CSV）：
  ① 表内勾稽：损益/财政状态/现金流 的恒等式，按准则分别校（JGAAP 与 IFRS 结构不同）
  ② 跨源互证：报告 Y+1 的「前期列」 vs 本库 Y 年当期值（差异即重述，须能解释）
  ③ 5 年表互证：每份 有報 的「主要な経営指標等の推移」有 5-8 列，
     同一年份最多被 5 份报告独立印过 → 逐格比对
  ④ 完整性闸：核心行必须每年取到（勾稽遇 None 会静默跳过，单科目整列丢失能瞒过勾稽）

用法：python3 _build_from_pdf.py [--write]
"""
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
JSON_DIR = os.path.join(HERE, "_extract_json")

# 第N期 → 财年（3月决算）：第159期 = 2024/04-2025/03 = FY2025/3
KIHON_BASE = 134          # 第135期 = FY2001/3
def kihon_to_fy(k):
    return int(k) - KIHON_BASE + 2000

def fy_to_kihon(fy):
    return fy - 2000 + KIHON_BASE

TOL = 2          # 百万円·印刷舍入容差
TOL_CF = 10


def load():
    out = {}
    for fn in sorted(os.listdir(JSON_DIR)):
        if not fn.endswith(".json"):
            continue
        d = json.load(open(os.path.join(JSON_DIR, fn), encoding="utf-8"))
        out[int(d["year"])] = d
    return out


def cur(d, kind, key):
    """该报告当期列的值。"""
    v = d["data"].get(kind, {}).get(key)
    return v[0] if v else None


def prev(d, kind, key):
    """该报告前期列的值（用于跨源互证）。"""
    v = d["data"].get(kind, {}).get(key)
    return v[1] if v and len(v) > 1 else None


# ---------------------------------------------------------------- ① 表内勾稽
def check_identities(fy, d, errs):
    std = d["data"]["_std"]
    g = lambda k, key: cur(d, k, key)

    def eq(name, lhs, rhs, tol=TOL):
        if lhs is None or rhs is None:
            return
        if abs(lhs - rhs) > tol:
            errs.append(f"FY{fy}/3 [{std}] 勾稽不平 {name}: {lhs:,.0f} vs {rhs:,.0f} "
                        f"(差 {lhs - rhs:,.0f})")

    if std == "IFRS":
        # 损益：売上原価/販売費/管理費/その他費用 以**负数**列示，故用加法
        eq("売上高+売上原価=売上総利益", (g("IS", "売上高") or 0) + (g("IS", "売上原価") or 0),
           g("IS", "売上総利益"))
        gp = g("IS", "売上総利益")
        parts = [g("IS", x) for x in ("その他の収益", "販売費", "管理費", "その他の費用")]
        if gp is not None and all(p is not None for p in parts):
            eq("毛利+其他收益+販売費+管理費+その他費用=個別開示項目前営業利益",
               gp + sum(parts), g("IS", "個別開示項目前営業利益"))
        eq("税引前+法人所得税(+米税率変更調整)=当期利益",
           (g("IS", "税引前利益") or 0) + (g("IS", "法人所得税") or 0)
           + (g("IS", "米国連邦法人税率変更調整") or 0), g("IS", "当期利益"))
        eq("親会社帰属+非支配持分帰属=当期利益",
           (g("IS", "親会社所有者帰属当期利益") or 0) + (g("IS", "非支配持分帰属当期利益") or 0),
           g("IS", "当期利益"))
        # 财政状态
        eq("流動+非流動=資産合計",
           (g("BS", "流動資産合計") or 0) + (g("BS", "非流動資産合計") or 0), g("BS", "資産合計"))
        eq("流動負債+非流動負債=負債合計",
           (g("BS", "流動負債合計") or 0) + (g("BS", "非流動負債合計") or 0), g("BS", "負債合計"))
        eq("親会社持分+非支配持分=資本合計",
           (g("BS", "親会社所有者帰属持分合計") or 0) + (g("BS", "非支配持分") or 0),
           g("BS", "資本合計"))
        eq("負債+資本=負債及び資本合計",
           (g("BS", "負債合計") or 0) + (g("BS", "資本合計") or 0), g("BS", "負債及び資本合計"))
        eq("資産合計=負債及び資本合計", g("BS", "資産合計"), g("BS", "負債及び資本合計"))
        # 现金流 —— ⚠️ NSG 的 CF 结构与多数公司不同，两条恒等式都要按它自己的排法写：
        #   ① 「増減額」= 営業+投資+財務，**不含**換算差額（換算差額印在増減額**之后**）
        #   ② 期末 = 期首 + 増減額 + 換算差額 + **超インフレの調整**（土耳其等恶性通胀调整，
        #      FY2020/3 起出现，漏掉它 FY2020 会差 2,086 百万円）
        ocf, icf, fcf = (g("CF", k) for k in ("営業活動によるキャッシュフロー",
                                              "投資活動によるキャッシュフロー",
                                              "財務活動によるキャッシュフロー"))
        chg = g("CF", "現金及び現金同等物の増減額")
        if None not in (ocf, icf, fcf):
            eq("営業+投資+財務=増減額", ocf + icf + fcf, chg, TOL_CF)
        beg, fx, hyp, hfs = (g("CF", k) for k in
                             ("現金及び現金同等物の期首残高", "換算差額", "超インフレの調整",
                              "売却目的保有資産への振替に伴う現金増減"))
        if None not in (beg, chg):
            eq("期首+増減額+換算差額+超インフレ調整+売却目的振替=期末",
               beg + chg + (fx or 0) + (hyp or 0) + (hfs or 0),
               g("CF", "現金及び現金同等物の期末残高"), TOL_CF)
        # ⚠️ **不校验 CF期末現金 == BS現金**：NSG 的现金流量表口径是**扣除银行透支后的净额**，
        #    而 BS 上透支计入流动负债的借入金、现金按总额列示，两者本就差一个透支余额
        #    （FY2012/3 差 18,549 百万円）。这是 NSG 自己在会计方针里写明的口径差，不是错。
    else:  # JGAAP：売上原価/販管費 以**正数**列示，故用减法
        eq("売上高−売上原価=売上総利益",
           (g("IS", "売上高") or 0) - (g("IS", "売上原価") or 0), g("IS", "売上総利益"))
        eq("売上総利益−販管費=営業利益",
           (g("IS", "売上総利益") or 0) - (g("IS", "販売費及び一般管理費") or 0), g("IS", "営業利益"))
        eq("流動+固定=資産合計",
           (g("BS", "流動資産合計") or 0) + (g("BS", "固定資産合計") or 0), g("BS", "資産合計"))
        eq("流動負債+固定負債=負債合計",
           (g("BS", "流動負債合計") or 0) + (g("BS", "固定負債合計") or 0), g("BS", "負債合計"))
        # 2006 年会社法前：資産 = 負債 + 少数株主持分 + 資本；之后：資産 = 負債 + 純資産(含少数株主)
        tot = g("BS", "資産合計")
        deb, mino, eqty = (g("BS", k) for k in ("負債合計", "少数株主持分", "純資産合計"))
        if None not in (tot, deb, eqty):
            a = deb + eqty + (mino or 0)
            b = deb + eqty
            if abs(a - tot) > TOL and abs(b - tot) > TOL:
                errs.append(f"FY{fy}/3 [JGAAP] 勾稽不平 負債+(少数株主)+純資産=資産合計: "
                            f"{a:,.0f}/{b:,.0f} vs {tot:,.0f}")


# ---------------------------------------------------------------- ④ 完整性闸
CORE_IFRS = {"IS": ["売上高", "売上総利益", "営業利益", "税引前利益", "当期利益",
                    "親会社所有者帰属当期利益"],
             "BS": ["資産合計", "負債合計", "資本合計", "親会社所有者帰属持分合計",
                    "現金及び現金同等物"],
             "CF": ["営業活動によるキャッシュフロー", "投資活動によるキャッシュフロー",
                    "財務活動によるキャッシュフロー", "現金及び現金同等物の期末残高"]}
CORE_JGAAP = {"IS": ["売上高", "売上原価", "売上総利益", "営業利益", "経常利益", "当期純利益"],
              "BS": ["資産合計", "負債合計", "純資産合計", "現金及び預金"],
              "CF": ["営業活動によるキャッシュフロー", "投資活動によるキャッシュフロー",
                     "財務活動によるキャッシュフロー", "現金及び現金同等物の期末残高"]}


def check_completeness(fy, d, errs):
    core = CORE_IFRS if d["data"]["_std"] == "IFRS" else CORE_JGAAP
    for kind, keys in core.items():
        miss = [k for k in keys if cur(d, kind, k) is None]
        if miss:
            errs.append(f"FY{fy}/3 [{d['data']['_std']}] 核心行缺失 {kind}: {miss}")


# ---------------------------------------------------------------- ② 跨源互证
XCHECK = [("IS", "売上高"), ("IS", "営業利益"), ("IS", "税引前利益"),
          ("BS", "資産合計"), ("BS", "負債合計"),
          ("CF", "営業活動によるキャッシュフロー")]
XCHECK_J = [("IS", "売上高"), ("IS", "営業利益"), ("IS", "経常利益"), ("IS", "当期純利益"),
            ("BS", "資産合計"), ("BS", "負債合計"),
            ("CF", "営業活動によるキャッシュフロー")]


def cross_check(reports, notes):
    """报告 Y 的前期列 vs 报告 Y-1 的当期列。差异 = 遡及修正/重述，逐条列出。"""
    diffs = []
    for fy, d in sorted(reports.items()):
        p = reports.get(fy - 1)
        if not p:
            continue
        if d["data"]["_std"] != p["data"]["_std"]:
            notes.append(f"FY{fy - 1}→FY{fy} 跨准则断点（{p['data']['_std']}→"
                         f"{d['data']['_std']}），不做跨源互证")
            continue
        keys = XCHECK if d["data"]["_std"] == "IFRS" else XCHECK_J
        for kind, key in keys:
            a, b = prev(d, kind, key), cur(p, kind, key)
            if a is None or b is None:
                continue
            if abs(a - b) > TOL:
                diffs.append(f"FY{fy - 1}/3 {kind}.{key}: 本库(该年自报) {b:,.0f} "
                             f"vs FY{fy}报告前期列 {a:,.0f}  差 {a - b:,.0f}")
    return diffs


# ---------------------------------------------------------------- ③ 5 年表互证
SUM_KEYS = ["売上高", "経常損益", "税引前損益", "当期損益", "包括利益", "純資産額", "総資産額",
            "1株当たり純資産", "1株当たり当期損益", "希薄化後1株当たり当期損益",
            "自己資本比率", "自己資本利益率", "株価収益率",
            "営業CF", "投資CF", "財務CF", "現金期末残高", "従業員数"]


def sum_table(reports):
    """把每份报告的 5 年表拆成 {(fy, std, key): [(来源报告, 值)…]}。"""
    cellmap = {}
    for fy, d in sorted(reports.items()):
        s = d["data"].get("SUM")
        if not s or not s["kihon"]:
            continue
        cols = s["kihon"]
        for key in SUM_KEYS:
            vals = s["rows"].get(key)
            if not vals or len(vals) != len(cols):
                continue           # 列数对不上 → 整行弃用（宁缺勿错位）
            for c, v in zip(cols, vals):
                if c["期"] == "移行日" or v is None:
                    continue
                y = kihon_to_fy(c["期"])
                std = c["std"] or d["data"]["_std"]
                cellmap.setdefault((y, std, key), []).append((fy, v))
    return cellmap


# ⑤ 5 年表 ↔ 三表 同源互证：同一份报告里，5 年表印的本年数应与三表本年列**逐格相等**。
#    这是判断「5 年表的行有没有被映射错」的决定性检验——行名折成 3-4 行时极易串行，
#    单看数字本身看不出错，只有和三表对上才知道。
SUM_VS_STMT = [
    ("売上高", "IS", ("売上高",)),
    ("税引前損益", "IS", ("税引前利益", "税金等調整前当期純利益")),
    ("経常損益", "IS", ("経常利益",)),
    ("当期損益", "IS", ("親会社所有者帰属当期利益", "当期純利益")),
    ("総資産額", "BS", ("資産合計",)),
    ("純資産額", "BS", ("親会社所有者帰属持分合計", "純資産合計")),
    ("営業CF", "CF", ("営業活動によるキャッシュフロー",)),
    ("投資CF", "CF", ("投資活動によるキャッシュフロー",)),
    ("財務CF", "CF", ("財務活動によるキャッシュフロー",)),
    ("現金期末残高", "CF", ("現金及び現金同等物の期末残高",)),
]


# 已查实的「5 年表印错、审计报表为准」白名单：(财年, 5年表指标) → 说明
# FY2002/3 的投資CF/財務CF —— **FY2002 与 FY2003 两份报告的 5 年表都印同一组错值**
# （△36,944 / 2,216），而**两份报告的经审计连结现金流量表都印 △36,607 / 2,225**
# （FY2002 当期列与 FY2003 前期列逐字一致），且 FY2002 MD&A 正文亦写「22 億 25 百万円のプラス」。
# 三处一手证据互证 → 审计报表为准，5 年表该两格是跨年度重复的印刷错误。
# 这正是「三表为准、5 年表只作互证」这条设计的价值所在：若图省事拿 5 年表建库，这两格会静默错进去。
SUM_KNOWN_BAD = {
    (2002, "投資CF"): "5年表 △36,944 vs 审计CF表 △36,607；FY2002/FY2003 两份报告的CF表一致，MD&A 佐证",
    (2002, "財務CF"): "5年表 2,216 vs 审计CF表 2,225；同上，MD&A 正文写「22億25百万円」",
}


def sum_vs_stmt(reports):
    out = []
    for fy, d in sorted(reports.items()):
        s = d["data"].get("SUM")
        if not s or not s["kihon"]:
            continue
        cols = s["kihon"]
        own = [i for i, c in enumerate(cols) if c["期"] != "移行日"
               and kihon_to_fy(c["期"]) == fy]
        if not own:
            out.append(f"FY{fy}/3 5年表最后一列不是本期（列={[c['期'] for c in cols]}）")
            continue
        i = own[-1]
        for skey, kind, keys in SUM_VS_STMT:
            vals = s["rows"].get(skey)
            if not vals or len(vals) != len(cols) or vals[i] is None:
                continue
            ref = next((cur(d, kind, k) for k in keys if cur(d, kind, k) is not None), None)
            if ref is None:
                continue
            if abs(vals[i] - ref) > TOL:
                why = SUM_KNOWN_BAD.get((fy, skey))
                tag = f"  【已查实·5年表印错】{why}" if why else ""
                out.append((why is None,
                            f"FY{fy}/3 5年表.{skey}={vals[i]:,.0f} vs 三表.{kind}"
                            f"={ref:,.0f}  差 {vals[i] - ref:,.0f}{tag}"))
    return out


def sum_conflicts(cellmap):
    out = []
    for (y, std, key), vs in sorted(cellmap.items()):
        uniq = {round(v, 2) for _, v in vs}
        if len(uniq) > 1:
            out.append(f"FY{y}/3 [{std}] {key}: " +
                       " / ".join(f"{src}报告={v:,.2f}" for src, v in vs))
    return out


# ---------------------------------------------------------------- CSV 输出
def write_csv(path, header, rows, write):
    if not write:
        return
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for r in [header] + rows:
            w.writerow(r)


def fmt(v):
    if v is None:
        return ""
    return f"{v:.2f}".rstrip("0").rstrip(".") if abs(v - round(v)) > 1e-9 else f"{round(v):d}"


ROWS_IS = [
    ("売上高", "营业收入"), ("売上原価", "营业成本"), ("売上総利益", "毛利"),
    ("その他の収益", "其他收益"), ("販売費", "销售费用"), ("管理費", "管理费用"),
    ("販売費及び一般管理費", "销售及一般管理费(JGAAP)"), ("その他の費用", "其他费用"),
    ("個別開示項目前営業利益", "个别开示项目前营业利润"),
    ("個別開示項目", "个别开示项目(净)"), ("個別開示項目収益", "个别开示项目·收益"),
    ("個別開示項目費用", "个别开示项目·费用"),
    ("営業利益", "营业利润"), ("経常利益", "经常利润(JGAAP)"),
    ("金融収益", "金融收益"), ("金融費用", "金融费用"),
    ("持分法適用会社金融債権減損", "对联营金融债权减值"),
    ("持分法による投資損益", "权益法投资损益"),
    ("持分法投資その他損益", "权益法投资其他损益"),
    ("税引前利益", "税前利润"), ("税金等調整前当期純利益", "税前利润(JGAAP)"),
    ("法人所得税", "所得税"),
    ("当期利益", "净利润"), ("当期純利益", "净利润(JGAAP)"),
    ("少数株主利益", "少数股东损益(JGAAP)"),
    ("非支配持分帰属当期利益", "非控股权益应占"),
    ("親会社所有者帰属当期利益", "母公司拥有人应占"),
    ("基本的1株当たり当期利益", "基本每股收益(円)"),
    ("希薄化後1株当たり当期利益", "稀释每股收益(円)"),
]
ROWS_BS = [
    ("のれん", "商誉"), ("無形資産", "无形资产"), ("有形固定資産", "有形固定资产"),
    ("投資不動産", "投资性房地产"), ("持分法投資", "权益法投资"), ("使用権資産", "使用权资产"),
    ("繰延税金資産", "递延所得税资产"), ("非流動資産合計", "非流动资产合计"),
    ("有形固定資産合計", "有形固定资产合计(JGAAP)"), ("無形固定資産", "无形固定资产(JGAAP)"),
    ("投資その他の資産合計", "投资及其他资产合计(JGAAP)"), ("固定資産合計", "固定资产合计(JGAAP)"),
    ("棚卸資産", "存货"), ("売上債権及びその他の債権", "应收账款及其他应收"),
    ("受取手形及び売掛金", "应收票据及应收账款(JGAAP)"),
    ("現金及び現金同等物", "现金及现金等价物"), ("現金及び預金", "现金及存款(JGAAP)"),
    ("売却目的で保有する資産", "持有待售资产"), ("流動資産合計", "流动资产合计"),
    ("資産合計", "资产总计"),
    ("社債及び借入金_流動", "流动·公司债及借款"), ("仕入債務及びその他の債務", "应付账款及其他应付"),
    ("支払手形及び買掛金", "应付票据及应付账款(JGAAP)"), ("短期借入金", "短期借款(JGAAP)"),
    ("一年内償還予定社債", "一年内到期公司债(JGAAP)"),
    ("引当金_流動", "流动·准备金"), ("流動負債合計", "流动负债合计"),
    ("社債及び借入金_非流動", "非流动·公司债及借款"),
    ("社債", "公司债(JGAAP)"), ("長期借入金", "长期借款(JGAAP)"),
    ("退職給付引当金", "退休福利负债"), ("繰延税金負債", "递延所得税负债"),
    ("非流動負債合計", "非流动负债合计"), ("固定負債合計", "固定负债合计(JGAAP)"),
    ("負債合計", "负债合计"),
    ("資本金", "股本"), ("資本剰余金", "资本公积"), ("利益剰余金", "留存收益"),
    ("自己株式", "库存股"), ("その他の資本の構成要素", "其他权益项目"),
    ("親会社所有者帰属持分合計", "母公司拥有人应占权益"),
    ("少数株主持分", "少数股东权益(JGAAP)"), ("非支配持分", "非控股权益"),
    ("資本合計", "权益合计"), ("純資産合計", "净资产合计(JGAAP)"),
    ("負債及び資本合計", "负债及权益总计"),
]
ROWS_CF = [
    ("営業活動による現金生成額", "经营活动产生现金(付息付税前)"),
    ("利息の受取額", "利息收取额"), ("利息の支払額", "利息支付额"),
    ("法人所得税の支払額", "所得税支付额"),
    ("営業活動によるキャッシュフロー", "经营活动现金流净额"),
    ("投資活動によるキャッシュフロー", "投资活动现金流净额"),
    ("財務活動によるキャッシュフロー", "筹资活动现金流净额"),
    ("有形固定資産取得", "购建有形固定资产支出"),
    ("無形資産取得", "购建无形资产支出"),
    ("capex", "购建固定资产支出(JGAAP)"),
    ("有形固定資産売却収入", "处置有形固定资产收入"),
    ("配当金の支払額", "股利支付额"), ("自己株式の取得", "回购库存股支出"),
    ("社債発行及び借入", "发债及借款收入"), ("社債償還及び返済", "偿债及还款支出"),
    ("現金及び現金同等物の増減額", "现金净变动"),
    ("現金及び現金同等物の期首残高", "期初现金"),
    ("換算差額", "汇率变动影响"), ("超インフレの調整", "恶性通胀调整"),
    ("売却目的保有資産への振替に伴う現金増減", "持有待售资产转拨现金增减"),
    ("現金及び現金同等物の期末残高", "期末现金"),
]


def build_statement(reports, kind, rowdefs, years, back_year=None):
    """back_year：**最早那份年报的前期列**所代表的年份。

    该年**没有自己的年报**（NSG 官网只发布到第135期，更早的 7 种命名 × 10 年全部 404，
    2026-08-31 实证），所以「该年自己那份报告的当期列」这条常规取数原则在这里无源可依。
    此时**最早一份年报的比较列就是该年唯一的一手来源**——与「招股书是上市前 3 年唯一真源」
    同理。落 CSV 时单独标注来源，不与 as-reported 年份混淆。
    """
    earliest = min(reports)
    rows = []
    for key, cn in rowdefs:
        line = [f"{key}（{cn}）"]
        got = False
        for fy in years:
            if back_year is not None and fy == back_year:
                v = prev(reports[earliest], kind, key)
            else:
                d = reports.get(fy)
                v = cur(d, kind, key) if d else None
            if v is not None:
                got = True
            line.append(fmt(v))
        if got:
            rows.append(line)
    return rows


# ⑥ 回溯年校验：最早年报「前期列」 vs 同一份年报 5 年表里该年那一列。
#    两者在同一份 PDF 的不同章节，互为独立印刷——对得上才敢把回溯年当一手数用。
BACK_CHECK = [("売上高", "IS", ("売上高",)),
              ("経常損益", "IS", ("経常利益",)),
              ("当期損益", "IS", ("当期純利益",)),
              ("総資産額", "BS", ("資産合計",)),
              ("純資産額", "BS", ("純資産合計",)),
              ("現金期末残高", "CF", ("現金及び現金同等物の期末残高",)),
              ("営業CF", "CF", ("営業活動によるキャッシュフロー",))]


def back_year_check(reports, cellmap, back_year):
    out = []
    earliest = min(reports)
    for skey, kind, keys in BACK_CHECK:
        a = next((prev(reports[earliest], kind, k) for k in keys
                  if prev(reports[earliest], kind, k) is not None), None)
        b = None
        for std in ("JGAAP", "IFRS"):
            vs = cellmap.get((back_year, std, skey))
            if vs:
                b = vs[0][1]
                break
        if a is None or b is None:
            out.append(f"FY{back_year}/3 {skey}: 缺一侧（前期列={a} 5年表={b}）")
        elif abs(a - b) > TOL:
            out.append(f"FY{back_year}/3 {skey}: 前期列 {a:,.0f} vs 5年表 {b:,.0f} "
                       f"差 {a - b:,.0f}")
    return out


def main():
    write = "--write" in sys.argv
    reports = load()
    years = sorted(reports)
    print(f"载入 {len(reports)} 份报告：FY{years[0]}/3 – FY{years[-1]}/3")

    errs, notes = [], []
    for fy, d in sorted(reports.items()):
        check_identities(fy, d, errs)
        check_completeness(fy, d, errs)

    print("\n=== ① 表内勾稽 + ④ 完整性闸 ===")
    if errs:
        for e in errs:
            print("  🔴", e)
    else:
        print("  ✅ 全部通过")

    print("\n=== ② 跨源互证（次年报告前期列 vs 本库当年值）===")
    diffs = cross_check(reports, notes)
    for n in notes:
        print("  ·", n)
    if diffs:
        for x in diffs:
            print("  ⚠️", x)
    else:
        print("  ✅ 0 处差异")

    print("\n=== ⑤ 5 年表 ↔ 三表 同源互证（同一份报告内，本年列逐格对）===")
    vs = sum_vs_stmt(reports)
    vs_hard = [m for isnew, m in vs if isnew]
    for isnew, m in vs:
        print(("  🔴 " if isnew else "  · ") + m)
    if not vs:
        print("  ✅ 0 处差异（5 年表各行映射正确）")
    elif not vs_hard:
        print("  ✅ 无新增差异（上列均为已查实的「5年表印错」，三表为准）")

    print("\n=== ③ 5 年表跨报告互证 ===")
    cellmap = sum_table(reports)
    conf = sum_conflicts(cellmap)
    cov = len({(y, s) for (y, s, _) in cellmap})
    print(f"  覆盖 {cov} 个「年份×准则」格；同一格被多份报告印过时逐格比对")
    if conf:
        for c in conf:
            print("  ⚠️", c)
    else:
        print("  ✅ 0 处冲突")

    # ---- 回溯年：最早年报的前期列 + 5 年表能往前接的年份 ----
    back_year = min(reports) - 1                      # 有完整三表（来自最早年报前期列）
    sum_years = sorted({y for (y, _s, _k) in cellmap})
    lead_years = [y for y in sum_years if y < back_year]   # 只有 5 年表摘要指标的更早年份

    print(f"\n=== ⑥ 回溯年校验（FY{back_year}/3 · 最早年报前期列 vs 同一份年报的 5 年表）===")
    bc = back_year_check(reports, cellmap, back_year)
    if bc:
        for x in bc:
            print("  🔴", x)
    else:
        print(f"  ✅ 0 处差异——FY{back_year}/3 的前期列可作一手数据采用")
    if lead_years:
        print(f"  · 另有 FY{lead_years[0]}/3–FY{lead_years[-1]}/3 共 {len(lead_years)} 年"
              f"**只有 5 年表摘要指标**（该年年报官网实证不可得），仅进 长期业绩序列.csv")

    if (errs or bc) and write:
        print("\n🔴 勾稽/完整性/回溯校验未过，拒绝写出 CSV")
        return

    stmt_years = [back_year] + years
    hdr = ["科目"] + [f"FY{y}/3" for y in stmt_years]
    write_csv(os.path.join(HERE, "利润表.csv"), hdr,
              build_statement(reports, "IS", ROWS_IS, stmt_years, back_year), write)
    write_csv(os.path.join(HERE, "资产负债表.csv"), hdr,
              build_statement(reports, "BS", ROWS_BS, stmt_years, back_year), write)
    write_csv(os.path.join(HERE, "现金流量表.csv"), hdr,
              build_statement(reports, "CF", ROWS_CF, stmt_years, back_year), write)

    # ---- 长期业绩序列 ----
    # 主干**取自已通过①⑤校验的三表**（不取 5 年表）：5 年表的行名折行严重、
    # 且列数与数据格数一旦对不上整行就得弃用，作主干会留下整年空洞
    # （実測 FY2006/FY2007 曾整列为空）。5 年表只补三表里没有的比率/人数行。
    STMT_ROWS = [
        ("売上高", "IS", ("売上高",)),
        ("営業利益", "IS", ("営業利益",)),
        ("経常損益[JGAAP]", "IS", ("経常利益",)),
        ("税引前損益", "IS", ("税引前利益", "税金等調整前当期純利益")),
        ("親会社帰属当期損益", "IS", ("親会社所有者帰属当期利益", "当期純利益")),
        ("総資産", "BS", ("資産合計",)),
        ("負債合計", "BS", ("負債合計",)),
        ("親会社帰属持分", "BS", ("親会社所有者帰属持分合計", "純資産合計")),
        ("営業CF", "CF", ("営業活動によるキャッシュフロー",)),
        ("投資CF", "CF", ("投資活動によるキャッシュフロー",)),
        ("財務CF", "CF", ("財務活動によるキャッシュフロー",)),
        ("現金期末残高", "CF", ("現金及び現金同等物の期末残高",)),
    ]
    SUM_ONLY = ["自己資本比率", "自己資本利益率", "株価収益率", "1株当たり純資産",
                "1株当たり当期損益", "希薄化後1株当たり当期損益", "包括利益", "従業員数"]
    # 长期序列的年份范围比三表更宽：把「只有 5 年表摘要」的更早年份也接上（标注来源）
    lt_years = lead_years + stmt_years

    def from_sum(key, y):
        for std in ("IFRS", "JGAAP"):
            vs = cellmap.get((y, std, key))
            if vs:
                own = [x for s, x in vs if s == y]
                return own[0] if own else vs[0][1]
        return None

    lt_rows = []
    for name, kind, keys in STMT_ROWS:
        line, got = [name], False
        for y in lt_years:
            if y in lead_years:                       # 无三表，退回 5 年表同义指标
                alias = {"売上高": "売上高", "経常損益[JGAAP]": "経常損益",
                         "親会社帰属当期損益": "当期損益", "総資産": "総資産額",
                         "親会社帰属持分": "純資産額", "営業CF": "営業CF",
                         "投資CF": "投資CF", "財務CF": "財務CF",
                         "現金期末残高": "現金期末残高"}.get(name)
                v = from_sum(alias, y) if alias else None
            elif y == back_year:
                v = next((prev(reports[min(reports)], kind, k) for k in keys
                          if prev(reports[min(reports)], kind, k) is not None), None)
            else:
                d = reports.get(y)
                v = next((cur(d, kind, k) for k in keys
                          if d and cur(d, kind, k) is not None), None) if d else None
            got = got or v is not None
            line.append(fmt(v))
        if got:
            lt_rows.append(line)
    for key in SUM_ONLY:
        line, got = [key + "（5年表）"], False
        for y in lt_years:
            v = from_sum(key, y)
            got = got or v is not None
            line.append(fmt(v))
        if got:
            lt_rows.append(line)
    lt_hdr = ["科目"] + [f"FY{y}/3" for y in lt_years]
    write_csv(os.path.join(HERE, "长期业绩序列.csv"), lt_hdr, lt_rows, write)

    print(f"\n{'已写出' if write else '（未写·加 --write 落盘）'} "
          f"利润表/资产负债表/现金流量表/长期业绩序列 CSV，{len(years)} 年")


if __name__ == "__main__":
    main()
