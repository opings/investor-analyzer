#!/usr/bin/env python3
"""上海耀皮 分部营收 + 产销量 生成器 —— 年报 MD&A「主营业务分行业/分产品/分地区」+「产销量情况分析表」

口径要点
  · 单位一律**万元**（年报该表原始口径），产销量按年报所标单位（浮法=万吨，加工=万平方米）。
  · 产品分类**逐年变化**：2006-2013 只拆「浮法玻璃 / 加工玻璃」，
    2014 起把加工拆成「建筑加工玻璃 / 汽车加工玻璃」。CSV 按并集出行，缺的年份留空——
    留空 = 该年年报未按此口径披露，**不是**没有该业务。
  · 分产品各行合计需减「内部抵销」才等于主营业务收入（板块间互供原片）。

校验：分产品合计(减内部抵销) ≈ 分地区合计 ≈ 分行业「玻璃」合计，误差 >1% 报警。

用法：python3 _build_segments.py [--write]
"""
import csv
import os
import re
import sys

from pypdf import PdfReader

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
PDF_DIR = os.path.join(ROOT, "report", "上海耀皮")
YEARS = list(range(2006, 2026))

NUM = re.compile(r"-?\d{1,3}(?:,\d{3})+\.\d{2}|-?\d{1,3}(?:,\d{3})+|-?\d+\.\d+|-?\d+")

# 分产品行名（并集，含各年异名）。
# 一律**前缀**匹配、不加 $：表格同一行尾部常跟着「增加 3.79 个百分点」之类的说明文字，
# 抠掉数字后标签变成 '浮法玻璃增加个百分点'，用 ^…$ 会全部匹配失败。
# 标签在表格里会换行（'汽车加工' / '玻璃'），所以前缀只取到不会断的那一截
PRODUCTS = [
    ("建筑加工玻璃", r"^建筑加工|^建筑玻璃"),
    ("汽车加工玻璃", r"^汽车加工|^汽车玻璃"),
    ("浮法玻璃", r"^浮法玻璃|^平板玻璃"),
    ("加工玻璃(未拆分)", r"^加工玻璃"),
    ("内部抵销", r"内部抵销|内部抵消|合并抵消|合并抵销"),
    ("其他", r"^其他|^其它"),
]
# 分地区口径**分三段**：2006-2013 与 2023-2025 用「国内/国外」；
# 2014-2022 改按大区列示（华北/华东/…/国外）。后者的「国内」= 各大区之和。
DOMESTIC_REGIONS = ["华北地区", "华东地区", "华南地区", "华中地区",
                    "西南地区", "西北地区", "东北地区"]
REGIONS = ([("国内", r"^国内|^境内")] +
           [(r, "^" + r[:2]) for r in DOMESTIC_REGIONS] +
           # 2006-2009 年报把出口那一行叫「国际」，不是「国外」
           [("国外", r"^国外|^国际|^境外|^出口")])
VOLUMES = [("建筑加工玻璃", r"^建筑加工"), ("汽车加工玻璃", r"^汽车加工"),
           ("浮法玻璃", r"^浮法玻璃"), ("加工玻璃(未拆分)", r"^加工玻璃")]

SEC_PROD = re.compile(r"主营业务分产品情况|分产品情况|分行业或分产品|主营业务分行业、?产品情况表?")
SEC_REGION = re.compile(r"主营业务分地区情况|分地区情况")
SEC_VOL = re.compile(r"产销量情况分析表|生产量.*销售量.*库存量")
SEC_STOP = re.compile(r"成本分析表|重大采购合同|费用√适用|研发投入")
# 分产品表读到「分地区」就停；分地区表读到「产销量/销售模式」就停——
# 否则 span 会跨进下一张表，把别的表的行认成本表的行。
STOP_PROD = re.compile(r"主营业务分地区|分地区情况|产销量情况|成本分析表|分销售模式")
STOP_REGION = re.compile(r"产销量情况|成本分析表|重大采购合同|分销售模式|主营业务分产品")


def norm(s):
    s = s.replace("（", "(").replace("）", ")").replace("：", ":")
    return re.sub(r"[\s　]+", "", s)


_CACHE = {}


def page_texts(year):
    if year in _CACHE:
        return _CACHE[year]
    r = PdfReader(os.path.join(PDF_DIR, f"上海耀皮-{year}.pdf"))
    out = []
    for pg in r.pages:
        plain = pg.extract_text() or ""
        try:
            t = pg.extract_text(extraction_mode="layout") or ""
        except Exception:
            t = plain
        if len(t.strip()) < 0.6 * len(plain.strip()):
            t = plain
        out.append(t)
    _CACHE[year] = out
    return out


def nums(line):
    return [float(m.group(0).replace(",", "")) for m in NUM.finditer(line)]


RUNNING_RE = re.compile(r"^\d+/\d+$|^\d{1,3}$|年年度报告$|^上海耀皮玻璃集团股份有限公司|^上海耀华皮尔金顿玻璃股份有限公司")
_DOC = {}


def doc_lines(year):
    """全文档行流（去页眉页脚）——表格跨页时必须这样看。"""
    if year in _DOC:
        return _DOC[year]
    out = []
    for t in page_texts(year):
        for ln in t.split("\n"):
            if ln.strip() and not RUNNING_RE.search(norm(ln)):
                out.append(ln)
    _DOC[year] = out
    return out


UNIT_RE = re.compile(r"单位:?(万元|元)")


def unit_scale(lines, li):
    """从表头往上找最近的「单位:万元/元」。早年（2006-2008）该表用**元**，
    2010 起改用**万元**——不归一会差 4 个数量级。默认按万元。"""
    for j in range(li, max(-1, li - 8), -1):
        m = UNIT_RE.search(norm(lines[j]))
        if m:
            return 1.0 if m.group(1) == "万元" else 1e-4
    return 1.0


def scan(year, sec_re, items, ncols, span=40, need_header=True, stop_re=None):
    """在命中 sec_re 的段落里，按 items 的正则抓行，取每行前 ncols 个数字（金额归一到万元）。

    **必须先确认表头**：年报里「分产品情况」这个小标题出现两次——
    一次在「主营业务分行业/分产品/分地区」的**收入表**，一次在「成本分析表」下的
    **成本构成表**。只按标题定位会随机命中成本表，抓回来的「营业收入」其实是成本，
    金额小一截还不报错。判据：紧随其后的表头必须同时出现「营业收入」和「营业成本」，
    且不得出现「成本构成」。
    """
    stop = stop_re or SEC_STOP
    # **全文档拉平成一条行流**再扫：这些表经常跨页——FY2025 的「主营业务分产品情况」
    # 表头在 p15 末、数据行在 p16 头，按页扫两边都取不到。同时滤掉页眉页脚，
    # 免得它们把表格行流截断。
    for lines in (doc_lines(year),):
        for li, ln in enumerate(lines):
            if not sec_re.search(norm(ln)):
                continue
            if need_header:
                head = "".join(norm(x) for x in lines[li + 1: li + 6])
                # 2006-2009 年报这张表的列名是「主营业务收入/主营业务成本」，2010 起才叫「营业收入」
                if "成本构成" in head or not ("营业收入" in head or "主营业务收入" in head):
                    continue
            scale = unit_scale(lines, li)
            res = {}
            for j in range(li + 1, min(len(lines), li + span)):
                nl = norm(lines[j])
                if stop.search(nl):
                    break
                label = norm(NUM.sub(" ", lines[j])).strip()
                if "成本构成" in label:
                    break
                for name, pat in items:
                    if name in res:
                        continue
                    if re.search(pat, label):
                        v = nums(lines[j])
                        if len(v) >= ncols:
                            # 比率列（毛利率/增减%）不缩放，只缩放金额列
                            res[name] = [x * scale for x in v[:ncols]] if ncols <= 2 else v[:ncols]
                        break
            if res:
                return res
    return {}


def revenue_wan():
    """从 利润表.csv 读营业收入（元）→ 万元，用作分部数据的量级基准。"""
    p = os.path.join(HERE, "利润表.csv")
    out = {}
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8-sig") as f:
        raw = list(csv.reader(f))
    hdr = raw[0]
    years = [int(x) for x in hdr[1:] if x.strip().isdigit()]
    for r in raw[1:]:
        if r and r[0].strip() == "营业总收入":
            for i, y in enumerate(years):
                v = r[1 + i].strip()
                if v:
                    out[y] = float(v) / 1e4
            break
    return out


REV_WAN = revenue_wan()


def autoscale(year, d, warns, what):
    """按量级校正单位。年报早年该表用「元」、后来用「万元」，
    表头有时又在跨页处丢失，UNIT_RE 抓不到就会差 1e4 倍。
    以利润表营收（万元）为尺子：若解析总额≈营收的 1e4 倍，则整体除以 1e4。"""
    if not d or year not in REV_WAN or not REV_WAN[year]:
        return d
    tot = sum(abs(v[0]) for v in d.values())
    if not tot:
        return d
    ratio = tot / REV_WAN[year]
    if 3e3 < ratio < 3e5:
        warns.append(f"FY{year} {what} 按量级判定单位为「元」，已折算为万元（原始/营收={ratio:,.0f}）")
        return {k: [x / 1e4 for x in v] for k, v in d.items()}
    return d


derived_off = set()   # 内部抵销为倒推值的年份（写进 README 留痕）


def build():
    seg, reg, vol, warns = {}, {}, {}, []
    for y in YEARS:
        seg[y] = autoscale(y, scan(y, SEC_PROD, PRODUCTS, 2, stop_re=STOP_PROD), warns, "分产品")
        reg[y] = autoscale(y, scan(y, SEC_REGION, REGIONS, 1, stop_re=STOP_REGION), warns, "分地区")
        vol[y] = scan(y, SEC_VOL, VOLUMES, 3, need_header=False)
        # 大区口径的年份：把各大区加总成「国内」，让 CSV 跨年可比
        if "国内" not in reg[y] and any(k in reg[y] for k in DOMESTIC_REGIONS):
            reg[y]["国内"] = [sum(reg[y][k][0] for k in DOMESTIC_REGIONS if k in reg[y])]
        # 板块间互供原片要抵销。抵销行有的年份没抓到（各年叫法不一：
        # 内部抵销/合并抵消/减：内部抵销），此时按恒等式
        # 「分产品毛合计 − 抵销 = 分地区合计」倒推出来，并标记为派生值。
        gross = sum(v[0] for k, v in seg[y].items() if k != "内部抵销")
        r = sum(v[0] for k, v in reg[y].items() if k in ("国内", "国外"))
        if "内部抵销" not in seg[y] and gross and r and gross - r > 0.005 * gross:
            seg[y]["内部抵销"] = [gross - r, None]   # 成本端无从倒推，留空
            derived_off.add(y)
        off = abs(seg[y].get("内部抵销", [0])[0])   # 有的年份抵销列示为负数
        p = gross - off
        if p and r and abs(p - r) / max(p, r) > 0.01:
            warns.append(f"FY{y} 分产品合计(净) {p:,.2f} vs 分地区合计 {r:,.2f} 差 {p - r:,.2f} 万元")
        # 与利润表营收对表：主营业务收入应略低于营业收入（后者含其他业务收入）
        if r and y in REV_WAN and REV_WAN[y]:
            gap = (REV_WAN[y] - r) / REV_WAN[y]
            if not (-0.02 < gap < 0.20):
                warns.append(f"FY{y} 主营业务收入 {r:,.0f} vs 利润表营业收入 {REV_WAN[y]:,.0f} 万元，偏离 {gap:.1%}")
        if not seg[y]:
            warns.append(f"FY{y} 未抓到分产品表")
        if not reg[y]:
            warns.append(f"FY{y} 未抓到分地区表")
    return seg, reg, vol, warns


def main():
    seg, reg, vol, warns = build()
    for w in warns:
        print("⚠️ " + w)
    print(f"分产品覆盖 {sum(1 for y in YEARS if seg[y])}/20 年 · "
          f"分地区 {sum(1 for y in YEARS if reg[y])}/20 · 产销量 {sum(1 for y in YEARS if vol[y])}/20")
    for y in YEARS:
        print(f"  FY{y} 产品={ {k: v[0] for k, v in seg[y].items()} } 地区={ {k: v[0] for k, v in reg[y].items()} }")
    if "--write" not in sys.argv:
        print("（未加 --write，仅体检）")
        return 0

    hdr = ["科目"] + [str(y) for y in YEARS]
    rows = []
    for name, _ in PRODUCTS:
        if not any(name in seg[y] for y in YEARS):
            continue
        rows.append([f"{name}_营业收入(万元)"] +
                    [f"{seg[y][name][0]:.2f}" if name in seg[y] else "" for y in YEARS])
        rows.append([f"{name}_营业成本(万元)"] +
                    [f"{seg[y][name][1]:.2f}" if name in seg[y] and seg[y][name][1] is not None
                     else "" for y in YEARS])
        if name == "内部抵销":
            continue           # 抵销行算毛利率没有意义（且各年正负号列示不一）
        rows.append([f"{name}_毛利率(%)"] +
                    [f"{(1 - seg[y][name][1] / seg[y][name][0]) * 100:.2f}"
                     if name in seg[y] and seg[y][name][0] and seg[y][name][1] is not None
                     else "" for y in YEARS])
    for name, _ in REGIONS:
        rows.append([f"{name}_营业收入(万元)"] +
                    [f"{reg[y][name][0]:.2f}" if name in reg[y] else "" for y in YEARS])
    with open(os.path.join(HERE, "分部营收.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(hdr)
        w.writerows(rows)

    vrows = []
    for name, _ in VOLUMES:
        if not any(name in vol[y] for y in YEARS):
            continue
        for k, i in (("生产量", 0), ("销售量", 1), ("库存量", 2)):
            vrows.append([f"{name}_{k}"] +
                         [f"{vol[y][name][i]:.2f}" if name in vol[y] else "" for y in YEARS])
    if vrows:
        with open(os.path.join(HERE, "产销量.csv"), "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(hdr)
            w.writerows(vrows)
    print("已写出 分部营收.csv" + (" / 产销量.csv" if vrows else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
