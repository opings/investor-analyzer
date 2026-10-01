#!/usr/bin/env python3
"""附注层构建器（FY2011-2026 R 轨附注明细表 → 一组主题 CSV），**校验不过不写出**。

为什么单建这一层：记忆 `note-enumeration-audit` ——「只取报表页 = 建了个半成品」。
Microsoft 最该盯的东西几乎全在附注里：分部 / 产品线 / 地区、递延收入与 RPO（剩余履约义务）、
**已签未起租的数据中心租赁**、融资租赁、固定资产构成与折旧、营业外里的 OpenAI 权益法损益、
所得税（美国/境外）、回购与股息。

## 取数纪律
- **as-reported**：每个财年只取**该财年自己那份 10-K** 的当年列；FY2009/FY2010 无自家 R 文件，
  取 FY2011 10-K 的比较列并在「数据来源」标明（分部口径与其自家 10-K 相同：五大事业部）。
- **维度块**：附注表里的成员块（分部 / 产品线 / 地区 / 租赁类型）由「无值且 tag 以 Axis/Member 结尾
  或 tag 为空」的块首行界定（FY2011-2015 块首行 tag 为空，FY2016 起为 …Axis）。
- **量纲**：按表自陈单位换算到百万美元（`$ in Billions` → ×1000）。百分比/年限行不换算。
- **每张表都有算术闸**：分部和=利润表营收 / 产品线和=营收 / 地区和=营收 / 递延收入分部和=资产负债表 /
  固定资产分项和=原值、原值−累计折旧=净值=资产负债表 / 营业外分项和=利润表 / 美国+境外税前=税前 …
  另设 **MUST 探针**（必需格清单），缺格即失败——防「取不到数的格不参与校验、0 条不通过」的静默截断。
"""
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RDIR = os.path.join(HERE, "_rfiles")
YEARS = list(range(2011, 2027))
TOL = 1.0


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower().replace("’", "'")


def load():
    return {fy: json.load(open(os.path.join(RDIR, f"{fy}.json"))) for fy in YEARS}


def table(d, pats):
    for p in pats:
        for sn, t in d["details"].items():
            if re.search(p, sn, re.I):
                return t
    return None


def scale(t):
    u = (t.get("unit") or "").lower()
    if "in billions" in u:
        return 1000.0
    if "in thousands" in u:
        return 0.001
    return 1.0


def col(t, fy, months=12):
    """财年 fy 在表中的列号。months=12 只认 12 个月期间列；months=None 认时点列。

    🔴 FY2016-2018 的 R 文件期间表头里夹着脚注格「[1]」，期长映射（months）整体失效为空表。
    此时同一个「Jun. 30, FY」会出现两次：先是**第四季度**列、后是**全年**列（季度列在前）。
    第一版取第一个匹配 → 落到季度列（该格为空）→ 三年分部/产品线/地区全空，MUST 探针现形。
    改为：期长未知时取**最后一个**匹配列。
    """
    hits = []
    for i, p in enumerate(t["periods"]):
        m = re.search(r"\b((19|20)\d\d)\b", p)
        if not m or int(m.group(1)) != fy or not p.lower().startswith("jun"):
            continue
        mo = t["months"][i] if t.get("months") and i < len(t["months"]) else None
        if months == 12 and t.get("months") and mo not in (12,):
            continue
        hits.append(i)
    if not hits:
        return None
    return hits[-1] if (months == 12 and not t.get("months")) else hits[0]


def blocks(t):
    """→ [(块名或 None, 行)]。块首行（成员名）本身不输出。"""
    out, cur = [], None
    for r in t["rows"]:
        tag, lab = r.get("tag") or "", r["label"]
        if all(v is None for v in r["vals"]) and not re.match(r"^\[\d+\]$", lab) \
                and (tag.endswith("Axis") or tag.endswith("Member") or tag == ""):
            cur = lab
            continue
        out.append((cur, r))
    return out


def val(t, fy, row_pat, block=None, months=12, raw=False, tag_pat=None):
    """取一格：块 block（None=正表行；字符串=块名正则）× 行标签正则 × 财年。"""
    if not t:
        return None
    i = col(t, fy, months)
    if i is None:
        return None
    sc = 1.0 if raw else scale(t)
    for b, r in blocks(t):
        if block is None and b is not None:
            continue
        if block is not None and (b is None or not re.search(block, norm(b))):
            continue
        if row_pat and not re.search(row_pat, norm(r["label"])):
            continue
        if tag_pat and not re.search(tag_pat, r.get("tag") or ""):
            continue
        v = r["vals"][i] if i < len(r["vals"]) else None
        if v is not None:
            return v * sc
    return None


def block_names(t):
    seen = []
    for b, r in blocks(t):
        if b is not None and b not in seen:
            seen.append(b)
    return seen


def read_main(name):
    with open(os.path.join(HERE, name)) as f:
        rows = list(csv.reader(f))
    h = next(i for i, r in enumerate(rows) if r and r[0] == "科目")
    years = [int(c[2:]) for c in rows[h][1:]]
    out = {}
    for r in rows[h + 2:]:
        if r:
            out[r[0]] = {y: (float(v) if v else None) for y, v in zip(years, r[1:])}
    return out


def fmt(v, pct=False):
    if v is None:
        return ""
    if pct:
        return f"{v:.1f}"
    return str(int(round(v))) if abs(v - round(v)) < 1e-6 else f"{v:.1f}"


def write(name, header_note, years, rows, origin=None):
    """rows = [(行名, {fy: v}, 是否百分比)]"""
    p = os.path.join(HERE, name)
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"# {header_note}"])
        w.writerow(["科目"] + [f"FY{y}" for y in years])
        if origin:
            w.writerow(["数据来源"] + [origin.get(y, "") for y in years])
        for nm, d, pct in rows:
            line = [fmt(d.get(y), pct) for y in years]
            if any(line):
                w.writerow([nm] + line)
    print(f"  写出 {name}（{len(rows)} 行 × {len(years)} 年）")


# ═════════════════════════ 1. 分部 ═════════════════════════
SEG_TABLES = {
    "rev": [r"^segment revenue, cost of revenue, operating expenses and operating income",
            r"^segment revenue and operating income", r"^segment revenue and gross margin", r"^segment revenue \(detail"],
    "oi": [r"^segment revenue, cost of revenue, operating expenses and operating income",
           r"^segment revenue and operating income", r"^operating income \(loss\) by segment"],
}
REV_ROW = r"^(revenue|revenues|segment revenue)$"
OI_ROW = r"^(operating income( \(loss\))?)$"


def seg_name(b):
    # 「Operating Segments | Windows Division」/「Reportable Segments | Intelligent Cloud」→ 去掉成员前缀
    s = re.sub(r"^(operating segments|reportable segments|segment groups?)\s*\|\s*", "", b, flags=re.I)
    return s.strip()


def build_segment_views(R):
    """每份 10-K 的分部表**全部三年**（自身年 + 两年比较列）→ 长表。用于同一口径下的增速比较：
    分部口径重划（FY2020 / FY2025）后，as-reported 序列跨断点不可比，必须用后一份申报的重述列。"""
    out = []
    for sfy in YEARS:
        d = R[sfy]
        trev = table(d, SEG_TABLES["rev"])
        toi = table(d, SEG_TABLES["oi"])
        if not trev:
            continue
        for fy in (sfy - 2, sfy - 1, sfy):
            for b in block_names(trev):
                nm = seg_name(b)
                v = val(trev, fy, REV_ROW, block=re.escape(norm(b)) + "$")
                o = val(toi, fy, OI_ROW, block=re.escape(norm(b)) + "$") if toi else None
                if v is not None or o is not None:
                    out.append((sfy, fy, nm, v, o))
            if toi:
                for b in block_names(toi):
                    nm = seg_name(b)
                    if any(x[0] == sfy and x[1] == fy and x[2] == nm for x in out):
                        continue
                    o = val(toi, fy, OI_ROW, block=re.escape(norm(b)) + "$")
                    if o is not None:
                        out.append((sfy, fy, nm, None, o))
    return out


def build_segments(R, IS):
    rev, oi, origin, bad = {}, {}, {}, []
    src_of = {fy: fy for fy in YEARS}
    src_of.update({2009: 2011, 2010: 2011})
    for fy, sfy in sorted(src_of.items()):
        d = R[sfy]
        trev = table(d, SEG_TABLES["rev"])
        toi = table(d, SEG_TABLES["oi"])
        if not trev:
            bad.append((fy, "分部营收表缺失"))
            continue
        names = [b for b in block_names(trev)]
        got_r, got_o = {}, {}
        for b in names:
            nm = seg_name(b)
            v = val(trev, fy, REV_ROW, block=re.escape(norm(b)) + "$")
            if v is not None:
                got_r[nm] = v
            if toi:
                o = val(toi, fy, OI_ROW, block=re.escape(norm(b)) + "$")
                if o is not None:
                    got_o[nm] = o
        rev[fy], oi[fy] = got_r, got_o
        origin[fy] = f"R{sfy}自身" if sfy == fy else f"R{sfy}比较列"
    return rev, oi, origin, bad


# FY2014-2015：分部组（Devices and Consumer / Commercial）与其下子分部同表出现——只认**组**做合计校验
GROUP_2014 = {"devices and consumer", "commercial"}


def seg_check(rev, oi, IS, bad):
    R_IS = IS["营业收入 Revenue"]
    OI_IS = IS["营业利润 Operating income"]
    for fy, g in rev.items():
        names = list(g)
        lownames = {n.lower() for n in names}
        if GROUP_2014 <= lownames:                         # FY2014-2015：只加两个组 + 公司及其他
            keys = [n for n in names if n.lower() in GROUP_2014 or "corporate" in n.lower()]
        else:
            keys = names
        s = sum(g[k] for k in keys)
        if R_IS.get(fy) is None or abs(s - R_IS[fy]) > TOL:
            bad.append((fy, f"分部营收和 {s:g} ≠ 利润表营收 {R_IS.get(fy)}（{keys}）"))
        go = oi.get(fy, {})
        if go:
            # 经营利润块与营收块不一定同名：FY2009-2012 营收侧叫「Unallocated and other」、经营利润侧叫
            # 「Reconciling amounts」——两者都是公司层调节项。故经营利润取**全部块**之和（FY2014-2015 仍只取组）
            if GROUP_2014 <= lownames:
                okeys = [k for k in go if k.lower() in GROUP_2014 or "corporate" in k.lower()]
            else:
                okeys = list(go)
            so = sum(go[k] for k in okeys)
            if OI_IS.get(fy) is None or abs(so - OI_IS[fy]) > TOL:
                bad.append((fy, f"分部经营利润和 {so:g} ≠ 利润表营业利润 {OI_IS.get(fy)}（{okeys}）"))


# ═════════════════════════ 2. 产品线 / 地区 ═════════════════════════
def build_block_series(R, pats, row_pat, months=12):
    out, origin = {}, {}
    src_of = {fy: fy for fy in YEARS}
    src_of.update({2009: 2011, 2010: 2011})
    for fy, sfy in sorted(src_of.items()):
        t = table(R[sfy], pats)
        if not t:
            continue
        g = {}
        for b in block_names(t):
            v = val(t, fy, row_pat, block=re.escape(norm(b)) + "$", months=months)
            if v is not None:
                g[b] = v
        if not g:
            # FY2009-2012 地区表不是维度块，而是平铺行「United States / Other countries / Total」
            i = col(t, fy, months)
            if i is not None:
                for b, r in blocks(t):
                    lab = norm(r["label"])
                    if b is None and not re.search(r"^total$|line items|^revenue$", lab):
                        v = r["vals"][i] if i < len(r["vals"]) else None
                        if v is not None:
                            g[r["label"]] = v * scale(t)
        out[fy] = g
        origin[fy] = f"R{sfy}自身" if sfy == fy else f"R{sfy}比较列"
    return out, origin


def sum_check(series, total, label, bad, exclude=()):
    for fy, g in series.items():
        s = sum(v for k, v in g.items() if not any(re.search(x, k, re.I) for x in exclude))
        if total.get(fy) is None or abs(s - total[fy]) > TOL:
            bad.append((fy, f"{label}分项和 {s:g} ≠ 总额 {total.get(fy)}"))


def wide(series, order_hint=None):
    """仅大小写/空白不同的印刷名视为同一行（FY2026 10-K 把「Dynamics Products and Cloud Services」印成
    「Dynamics products and cloud services」——不合并会把同一产品线劈成两行）；行名取**最近一年**的印刷形式。
    名称真正改变的（Gaming→XBOX 等）不在这里合并，见 分产品营收-各申报口径.csv 的更名链。"""
    keys, disp = [], {}
    for fy in sorted(series):
        for k in series[fy]:
            nk = norm(k)
            if nk not in keys:
                keys.append(nk)
            disp[nk] = k
    out = []
    for nk in keys:
        d = {}
        for fy in series:
            hits = [v for k, v in series[fy].items() if norm(k) == nk]
            if len(hits) > 1:
                raise ValueError(f"FY{fy} 同一年出现两个仅大小写不同的行：{nk}")
            d[fy] = hits[0] if hits else None
        out.append((disp[nk], d, False))
    return out


def build_block_views(R, pats, row_pat):
    """每份 10-K 某张维度块表的三年全量 → [(申报财年, 财年, 块名, 值)] + 每份申报每年的合计行。"""
    out, totals = [], {}
    for sfy in YEARS:
        t = table(R[sfy], pats)
        if not t:
            continue
        for fy in (sfy - 2, sfy - 1, sfy):
            tot = val(t, fy, row_pat)
            if tot is not None:
                totals[(sfy, fy)] = tot
            for b in block_names(t):
                v = val(t, fy, row_pat, block=re.escape(norm(b)) + "$")
                if v is not None:
                    out.append((sfy, fy, b, v))
    return out, totals


def rename_chain(views):
    """机械判更名：上一份 10-K 印 A=x、这一份 10-K 对同一财年印 B=x，且 A 不再出现、B 之前没出现 → A 更名为 B。
    同名而值不同 → 重述。只比较「同一财年」在相邻两份申报里的数，不跨财年推断。"""
    by = {}
    for sfy, fy, nm, v in views:
        by.setdefault((sfy, fy), {})[nm] = v
    renames, restates = [], []
    filings = sorted({s for s, _ in by})
    for a, b in zip(filings, filings[1:]):
        for fy in (a, a - 1):
            old, new = by.get((a, fy), {}), by.get((b, fy), {})
            if not old or not new:
                continue
            on = {norm(k): (k, v) for k, v in old.items()}
            nn = {norm(k): (k, v) for k, v in new.items()}
            for k in on.keys() & nn.keys():
                if abs(on[k][1] - nn[k][1]) > TOL:
                    restates.append((b, fy, nn[k][0], on[k][1], nn[k][1]))
            gone = {k: on[k] for k in on.keys() - nn.keys()}
            came = {k: nn[k] for k in nn.keys() - on.keys()}
            for kc, (nmc, vc) in came.items():
                match = [nmo for ko, (nmo, vo) in gone.items() if abs(vo - vc) <= TOL]
                renames.append((b, fy, " / ".join(match) if match else "（无同值旧行：拆分/合并/新增）", nmc, vc))
    # 同一更名会在两个比较年各出现一次 → 按 (申报, 旧, 新) 去重
    seen, uniq = set(), []
    for r in renames:
        key = (r[0], r[2], r[3])
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq, restates


# ═════════════════════════ 3. 递延收入 / RPO ═════════════════════════
def build_unearned(R, BS, CF):
    rows = {k: {} for k in ("total", "rpo", "rpo_comm", "rpo_12m_pct", "deferral", "recognition")}
    seg = {}
    for fy in YEARS:
        d = R[fy]
        t = table(d, [r"^unearned revenue by segment"])
        if t:
            g = {}
            for b in block_names(t):
                v = val(t, fy, r"unearned revenue|^total$|contract with customer liability", block=re.escape(norm(b)) + "$", months=None)
                if v is not None:
                    g[seg_name(b)] = v
            tot = val(t, fy, r"unearned revenue|^total", months=None)
            seg[fy] = g
            rows["total"][fy] = tot
        t2 = table(d, [r"^unearned revenue - additional information"])
        if t2:
            rows["rpo"][fy] = val(t2, fy, r"^revenue allocated to remaining performance obligations$", months=None)
            rows["rpo_comm"][fy] = val(t2, fy, r"^revenue allocated to remaining performance obligations$",
                                       block=r"commercial", months=None)
        t3 = table(d, [r"^unearned revenue - remaining performance obligation"])
        if t3:
            rows["rpo_12m_pct"][fy] = val(t3, fy, r"percentage", months=None, raw=True)
        t4 = table(d, [r"^changes in unearned revenue"])
        if t4:
            rows["deferral"][fy] = val(t4, fy, r"^deferral of revenue", months=None)
            rows["recognition"][fy] = val(t4, fy, r"^recognition of unearned revenue", months=None)
    return rows, seg


# ═════════════════════════ 主流程 ═════════════════════════
def main():
    R = load()
    IS, BS, CF = read_main("利润表.csv"), read_main("资产负债表.csv"), read_main("现金流量表.csv")
    for probe, tab in (("营业收入 Revenue", IS), ("总资产 Total assets", BS), ("经营活动现金流净额 Net cash from operations", CF)):
        if probe not in tab:
            print(f"❌ 主表探针行缺失：{probe}（主表 CSV 表头行号或行名变了）")
            return 1
    bad = []

    # 1) 分部（FY2011+ R 轨；FY2009-2010 先取 R2011 比较列做校验，随后被**自家 10-K** 转录值覆盖）
    rev, oi, sorigin, b1 = build_segments(R, IS)
    bad += b1
    seg_check(rev, oi, IS, bad)
    # 1b) FY1997-2010 自家申报转录（_scans/segments_legacy.json）
    LEG = json.load(open(os.path.join(HERE, "_scans", "segments_legacy.json")))
    gen_of = {}
    for row in LEG["segments"]["rows"]:
        fy = row["fy"]
        rv = {k: v[0] for k, v in row["items"].items() if v[0] is not None}
        ov = {k: v[1] for k, v in row["items"].items() if v[1] is not None}
        if abs(sum(rv.values()) - row["total_rev"]) > TOL:
            bad.append((fy, f"转录分部营收和 {sum(rv.values())} ≠ 该附注合并 {row['total_rev']}"))
        if row["total_oi"] is not None and abs(sum(ov.values()) - row["total_oi"]) > TOL:
            bad.append((fy, f"转录分部经营利润和 {sum(ov.values())} ≠ 该附注合并 {row['total_oi']}"))
        own = "比较年" not in row["src"]
        if own:
            if abs(row["total_rev"] - IS["营业收入 Revenue"][fy]) > TOL:
                bad.append((fy, f"转录合并营收 {row['total_rev']} ≠ 利润表 {IS['营业收入 Revenue'][fy]}"))
            if row["total_oi"] is not None and abs(row["total_oi"] - IS["营业利润 Operating income"][fy]) > TOL:
                bad.append((fy, f"转录合并经营利润 {row['total_oi']} ≠ 利润表 {IS['营业利润 Operating income'][fy]}"))
        rev[fy], oi[fy] = rv, ov
        sorigin[fy] = row["src"]
        gen_of[fy] = row["gen"]
    for fy in YEARS:
        gen_of[fy] = "G4 五大事业部" if fy <= 2013 else ("G5 两组(设备与消费者·商业)" if fy <= 2015 else
                                                    "G6 生产力与业务流程·智能云·更多个人计算")
    # 产品组 / 渠道（FY1992-1998·MD&A 自陈·十亿美元两位小数→精度 ±5 百万/项）
    pg = {r["fy"]: (r["items"], r["src"], r["gen"]) for r in LEG["product_groups"]["rows"]}
    ch = {r["fy"]: (r["items"], r["src"]) for r in LEG["channels"]["rows"]}
    for fy, (items, src, gen) in pg.items():
        tot = IS["营业收入 Revenue"].get(fy)
        if tot is None or abs(sum(items.values()) - tot) > max(15, tot * 0.005):
            bad.append((fy, f"产品组和 {sum(items.values())} 与营收 {tot} 差超 0.5%"))
    for fy, (items, src) in ch.items():
        tot = IS["营业收入 Revenue"].get(fy)
        if tot is None or abs(sum(items.values()) - tot) > max(15, tot * 0.005):
            bad.append((fy, f"渠道和 {sum(items.values())} 与营收 {tot} 差超 0.5%"))

    # 2) 产品线
    PROD_PATS = [r"^revenue classified by significant product and service offerings \(detail"]
    prod, porigin = build_block_series(R, PROD_PATS, r"^(revenue|revenues)$")
    sum_check(prod, IS["营业收入 Revenue"], "产品线", bad)
    # 2b) 产品线「各申报口径」：每份 10-K 三年全量 + 每份申报每年自洽（分项和 = 该申报的合计行）
    pviews, ptotals = build_block_views(R, PROD_PATS, r"^(revenue|revenues)$")
    for (sfy, fy), tot in ptotals.items():
        s = sum(v for a, b_, _, v in pviews if a == sfy and b_ == fy)
        if abs(s - tot) > TOL:
            bad.append((fy, f"R{sfy} 产品线比较列和 {s:g} ≠ 该申报合计 {tot:g}"))
    for sfy in YEARS:
        if not any(a == sfy for a, _ in ptotals):
            bad.append((sfy, f"R{sfy} 产品线表合计行取不到（各申报口径长表会缺这一份）"))
    prenames, prestates = rename_chain(pviews)
    # 3) 地区营收 + 长期资产
    geo, gorigin = build_block_series(R, [r"^revenue classified by major geographic areas"], r"^(revenue|revenues)$")
    sum_check(geo, IS["营业收入 Revenue"], "地区营收", bad)
    lla, _ = build_block_series(R, [r"^long-lived assets"], r"long-lived assets|^total$|property", months=None)

    # 4) 递延收入 / RPO
    ue, ueseg = build_unearned(R, BS, CF)
    for fy, g in ueseg.items():
        bs = (BS["短期递延收入 Short-term unearned revenue"].get(fy) or 0) + (BS["长期递延收入 Long-term unearned revenue"].get(fy) or 0)
        s = sum(g.values())
        if abs(s - bs) > TOL:
            bad.append((fy, f"递延收入分部和 {s:g} ≠ 资产负债表短期+长期 {bs:g}"))

    # 5) 固定资产
    pp = {k: {} for k in ("land", "bld", "lease_imp", "comp", "furn", "cip", "gross", "accdep", "net",
                          "dep_exp", "capex_ap", "construct_commit")}
    for fy in YEARS:
        t = table(R[fy], [r"^components of property and equipment"])
        if t:
            pp["land"][fy] = val(t, fy, r"^land$", months=None)
            pp["bld"][fy] = val(t, fy, r"^buildings and improvements$", months=None)
            pp["lease_imp"][fy] = val(t, fy, r"^leasehold improvements$", months=None)
            pp["comp"][fy] = val(t, fy, r"^(computer equipment and software|servers, network equipment, and software)$", months=None)
            pp["furn"][fy] = val(t, fy, r"^furniture and equipment$", months=None)
            pp["cip"][fy] = val(t, fy, r"^construction in progress$", months=None)
            pp["gross"][fy] = val(t, fy, r"^total, at cost$", months=None)
            pp["accdep"][fy] = val(t, fy, r"^accumulated depreciation$", months=None)
            pp["net"][fy] = val(t, fy, r"^(total, net|property and equipment, net)$", months=None)
        t2 = table(R[fy], [r"^property and equipment - additional information"])
        if t2:
            pp["dep_exp"][fy] = val(t2, fy, r"^depreciation expense", months=12) or val(t2, fy, r"depreciation", months=12)
            pp["capex_ap"][fy] = val(t2, fy, r"remaining in accounts payable", months=None) \
                or val(t2, fy, r"remaining in accounts payable", months=12)
            pp["construct_commit"][fy] = val(t2, fy, r"^committed for construction", block=r"building", months=None) \
                or val(t2, fy, r"^committed for construction", months=None)
    for fy in YEARS:
        parts = [pp[k].get(fy) for k in ("land", "bld", "lease_imp", "comp", "furn", "cip")]
        g = pp["gross"].get(fy)
        if g is None:
            bad.append((fy, "固定资产原值缺"))
            continue
        if abs(sum(p or 0 for p in parts) - g) > TOL:
            bad.append((fy, f"固定资产分项和 {sum(p or 0 for p in parts):g} ≠ 原值 {g:g}"))
        net = g + (pp["accdep"].get(fy) or 0)
        if abs(net - (BS["固定资产净额 Property and equipment, net"].get(fy) or 0)) > TOL:
            bad.append((fy, f"固定资产 原值−累计折旧 {net:g} ≠ 资产负债表净额"))

    # 6) 租赁（ASC 842·FY2018 起附注口径；FY2018 10-K 首次按新准则披露）
    ls = {k: {} for k in ("op_rou", "op_liab", "fin_ppe_gross", "fin_ppe_net", "fin_liab", "op_cost", "fin_amort",
                          "fin_int", "not_commenced", "nc_op", "nc_fin", "op_rate", "fin_rate",
                          "rou_new_op", "rou_new_fin", "pay_op", "pay_fin_int", "pay_fin_prin")}
    for fy in YEARS:
        t = table(R[fy], [r"^supplemental balance sheet information related to leases"])
        if t:
            ls["op_rou"][fy] = val(t, fy, r"^operating lease right-of-use assets$", months=None)
            ls["op_liab"][fy] = val(t, fy, r"^total operating lease liabilities$", months=None)
            ls["fin_ppe_gross"][fy] = val(t, fy, r"^property and equipment, at cost$", block=r"^finance lease", months=None)
            ls["fin_ppe_net"][fy] = val(t, fy, r"^property and equipment, net$", block=r"^finance lease", months=None)
            ls["fin_liab"][fy] = val(t, fy, r"^total finance lease liabilities$", months=None)
            ls["op_rate"][fy] = val(t, fy, r"^operating leases$", months=None, raw=True,
                                    tag_pat=r"DiscountRate")
            ls["fin_rate"][fy] = val(t, fy, r"^finance leases$", months=None, raw=True, tag_pat=r"DiscountRate")
        t2 = table(R[fy], [r"^components of lease expense"])
        if t2:
            ls["op_cost"][fy] = val(t2, fy, r"^operating lease cost$")
            ls["fin_amort"][fy] = val(t2, fy, r"^amortization of right-of-use assets$")
            ls["fin_int"][fy] = val(t2, fy, r"^interest on lease liabilities$")
        # 租赁现金流补充表：新增使用权资产（非现金取得——**不在**现金流量表资本开支里）+ 三类租赁付款
        t4 = table(R[fy], [r"^supplemental cash flow information related to leases"])
        if t4:
            ls["rou_new_op"][fy] = val(t4, fy, r"^operating leases$", tag_pat=r"RightOfUseAsset")
            ls["rou_new_fin"][fy] = val(t4, fy, r"^finance leases$", tag_pat=r"RightOfUseAsset")
            ls["pay_op"][fy] = val(t4, fy, r"^operating cash flows from operating leases$")
            ls["pay_fin_int"][fy] = val(t4, fy, r"^operating cash flows from finance leases$")
            ls["pay_fin_prin"][fy] = val(t4, fy, r"^financing cash flows from finance leases$")
        t3 = table(R[fy], [r"^leases - additional information"])
        if t3:
            # 🔴 FY2019-2025 正文写「operating and finance leases … not yet commenced of $X billion and $Y billion,
            #    respectively」——两个数，分别挂在 Operating / Finance 两个块里；FY2026 改为一个合并数（两块印同值）。
            #    第一版只取第一个块 → FY2024 记成 86 亿（只是经营租赁），漏掉融资租赁 1,084 亿。
            op = val(t3, fy, r"not yet commenced", block=r"operating lease", months=None)
            fin = val(t3, fy, r"not yet commenced", block=r"finance lease", months=None)
            flat = val(t3, fy, r"not yet commenced", months=None)
            ls["nc_op"][fy], ls["nc_fin"][fy] = op, fin
            if op is not None and fin is not None:
                ls["not_commenced"][fy] = op if abs(op - fin) < 1e-6 else op + fin
                if abs(op - fin) < 1e-6:
                    ls["nc_op"][fy] = ls["nc_fin"][fy] = None          # 合并披露年份：不拆
            else:
                ls["not_commenced"][fy] = op if op is not None else (fin if fin is not None else flat)

    # 7) 营业外收支明细 + OpenAI
    oie = {k: {} for k in ("int_div", "int_exp", "inv_gain", "deriv", "fx", "other", "total", "openai")}
    for fy in YEARS:
        t = table(R[fy], [r"^components of other income \(expense\)"])
        if not t:
            continue
        oie["int_div"][fy] = val(t, fy, r"^(dividends and interest income|interest and dividends income)$")
        oie["int_exp"][fy] = val(t, fy, r"^interest expense$")
        oie["inv_gain"][fy] = val(t, fy, r"^net recognized gains? \(?losses?\)? on investments$|^net recognized gains on investments$")
        # FY2014 衍生品一行被放进「Other income (expense)」维度块里（不在正表行）→ 正表找不到再找块内
        oie["deriv"][fy] = val(t, fy, r"^net (gains|losses).*derivatives$") \
            if val(t, fy, r"^net (gains|losses).*derivatives$") is not None \
            else val(t, fy, r"^net (gains|losses).*derivatives$", block=r".")
        oie["fx"][fy] = val(t, fy, r"foreign currency")
        oie["other"][fy] = val(t, fy, r"^other(, net)?$")
        oie["total"][fy] = val(t, fy, r"^total$|^total other income")
        t2 = table(R[fy], [r"^other income \(expense\), net - additional information"])
        if t2:
            oie["openai"][fy] = val(t2, fy, r"net gains \(losses\) from investments", block=r"openai")
    for fy in YEARS:
        tot = oie["total"].get(fy)
        if tot is None:
            continue
        s = sum(oie[k].get(fy) or 0 for k in ("int_div", "int_exp", "inv_gain", "deriv", "fx", "other"))
        if abs(s - tot) > TOL:
            bad.append((fy, f"营业外分项和 {s:g} ≠ 合计 {tot:g}"))
        is_oie = IS["营业外收支净额 Other income (expense), net"].get(fy)
        if is_oie is not None and abs(tot - is_oie) > TOL:
            bad.append((fy, f"营业外附注合计 {tot:g} ≠ 利润表 {is_oie:g}"))

    # 8) 所得税
    tx = {k: {} for k in ("pbt_us", "pbt_foreign", "cur_fed", "cur_state", "cur_foreign", "cur_total",
                          "def_fed", "def_state", "def_foreign", "def_total", "prov", "etr", "utb",
                          "dta_net_va", "dtl", "net_dt", "dtl_dep", "dta_dep", "dta_rd")}
    for fy in YEARS:
        d = R[fy]
        t = table(d, [r"^income \(loss\) before income taxes|^income before income taxes"])
        if t:
            tx["pbt_us"][fy] = val(t, fy, r"^u\.s\.|^united states")
            # FY2011-2015 叫「International」、FY2016 起叫「Foreign」
            tx["pbt_foreign"][fy] = val(t, fy, r"^(foreign|international)$")
        t2 = table(d, [r"^provision for income taxes"])
        if t2:
            tx["cur_fed"][fy] = val(t2, fy, r"^(u\.s\. )?federal$", block=None) or val(t2, fy, r"federal", block=r"current")
            tx["cur_total"][fy] = val(t2, fy, r"^current taxes$|^total current")
            tx["def_total"][fy] = val(t2, fy, r"^deferred taxes$|^total deferred")
            tx["prov"][fy] = val(t2, fy, r"^provision for income taxes$|^total provision")
        t3 = table(d, [r"^difference between income taxes computed"])
        if t3:
            tx["etr"][fy] = val(t3, fy, r"^effective rate$|effective tax rate", raw=True)
        t4 = table(d, [r"^changes in (gross )?unrecognized tax benefits"])
        if t4:
            tx["utb"][fy] = val(t4, fy, r"^ending unrecognized tax benefits|^balance, end of year|^ending", months=12)
        # 递延所得税构成：FY2026 经营现金流里「递延所得税 +142 亿」的来源（折旧项递延所得税负债 57→177 亿）
        t5 = table(d, [r"^deferred income tax assets and liabilities \(detail"])
        if t5:
            tx["dta_net_va"][fy] = val(t5, fy, r"^deferred income tax assets, net of valuation allowance$", months=None)
            tx["dtl"][fy] = val(t5, fy, r"^(total )?deferred income tax liabilities$", months=None, tag_pat=r"Liabilities")
            tx["net_dt"][fy] = val(t5, fy, r"^net deferred income tax (assets|liabilities)", months=None)
            tx["dtl_dep"][fy] = val(t5, fy, r"^depreciation$", months=None, tag_pat=r"Liabilit")
            # FY2019-2020 折旧在**资产**侧（账面折旧快于税务）——之后翻到负债侧，翻面本身就是信号
            tx["dta_dep"][fy] = val(t5, fy, r"^depreciation( and amortization)?$", months=None, tag_pat=r"Assets")
            tx["dta_rd"][fy] = val(t5, fy, r"^capitalized research and development$", months=None)
    for fy in YEARS:
        a, b_ = tx["pbt_us"].get(fy), tx["pbt_foreign"].get(fy)
        pbt = IS["税前利润 Income before income taxes"].get(fy)
        # 两边缺一 = 校验没跑 → 直接判失败（第一版写成「两边都有才校验」，FY2011-2015 境外一行
        # 因标签叫 International 取不到，校验静默跳过五年）
        if a is None or b_ is None or abs(a + b_ - pbt) > TOL:
            bad.append((fy, f"美国+境外税前 {a}+{b_} ≠ 税前 {pbt:g}"))
        c_, d_ = tx["cur_total"].get(fy), tx["def_total"].get(fy)
        if c_ is not None and d_ is not None and abs(c_ + d_ - (tx["prov"].get(fy) or 0)) > TOL:
            bad.append((fy, f"当期+递延所得税 {c_ + d_:g} ≠ 所得税费用 {tx['prov'].get(fy)}"))
        if tx["prov"].get(fy) is not None and abs(tx["prov"][fy] - IS["所得税 Provision for income taxes"].get(fy)) > TOL:
            bad.append((fy, f"附注所得税 {tx['prov'][fy]:g} ≠ 利润表所得税"))
        a_, l_, n_ = tx["dta_net_va"].get(fy), tx["dtl"].get(fy), tx["net_dt"].get(fy)
        if None not in (a_, l_, n_) and abs(a_ + l_ - n_) > TOL:
            bad.append((fy, f"递延所得税 资产净额 {a_:g} + 负债 {l_:g} ≠ 净额 {n_:g}"))

    # 8a) 商誉按分部 + 累计减值（商誉减值风险要落到报告单元，不能只看合并数）
    gw = {}
    gw_imp = {}
    for fy in YEARS:
        t = table(R[fy], [r"^carrying amount of goodwill \(detail"])
        if t:
            g_ = {}
            for b in block_names(t):
                v = val(t, fy, r"^ending balance$|^balance, end of period$", block=re.escape(norm(b)) + "$", months=None)
                if v is not None:
                    g_[seg_name(b)] = v
            tot = val(t, fy, r"^ending balance$|^balance, end of period$", months=None)
            if g_:
                gw[fy] = g_
                # FY2014-2015 分部组与子分部同表（同 seg_check 的 GROUP_2014 处理）：只加两个组
                low = {k.lower() for k in g_}
                keys = [k for k in g_ if k.lower() in GROUP_2014] if GROUP_2014 <= low else list(g_)
                s_ = sum(g_[k] for k in keys)
                if tot is not None and abs(s_ - tot) > TOL:
                    bad.append((fy, f"商誉分部和 {s_:g} ≠ 合计 {tot:g}"))
                bsg = BS["商誉 Goodwill"].get(fy)
                if bsg is not None and abs(s_ - bsg) > TOL:
                    bad.append((fy, f"商誉分部和 {s_:g} ≠ 资产负债表商誉 {bsg:g}"))
        t2 = table(R[fy], [r"^goodwill - additional information"])
        if t2:
            v = val(t2, fy, r"^accumulated goodwill impairment", months=None, raw=True)
            if v is not None:
                gw_imp[fy] = v / 1e6 if v > 1e7 else v * scale(t2)
    # 动视暴雪收购日（2023-10-13）分配的商誉：FY2024 10-K 收购对价分配表
    act_gw = None
    t3 = table(R[2024], [r"^major classes of assets and liabilities allocated purchase price"])
    if t3:
        j = next((i for i, p in enumerate(t3["periods"]) if p.strip().startswith("Oct. 13, 2023")), None)
        if j is not None:
            for b, r in blocks(t3):
                if norm(r["label"]) == "goodwill" and j < len(r["vals"]) and r["vals"][j] is not None:
                    act_gw = r["vals"][j] * scale(t3)
                    break
    if act_gw is None:
        bad.append((2024, "动视暴雪收购对价分配表的商誉格取不到"))

    # 8b) 未起租租赁：XBRL 值 vs 10-K 正文句子（独立核·两种表示必须一致）
    import html as _html
    root = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
    for fy in range(2018, 2027):
        p = os.path.join(root, "report", "微软", f"{fy}.htm")
        if not os.path.exists(p):
            continue
        raw = open(p, encoding="utf-8", errors="ignore").read()
        t = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", raw)).replace("\xa0", " "))
        m = re.search(r"not yet commenced of \$ ?([\d.,]+) (billion|million)( and \$ ?([\d.,]+) (billion|million))?", t)
        if not m:
            bad.append((fy, "未起租租赁：10-K 正文句子未找到"))
            continue
        u = lambda x, s: float(x.replace(",", "")) * (1000 if s == "billion" else 1)
        txt_total = u(m.group(1), m.group(2)) + (u(m.group(4), m.group(5)) if m.group(4) else 0)
        if abs(txt_total - (ls["not_commenced"].get(fy) or 0)) > 1:
            bad.append((fy, f"未起租租赁 XBRL {ls['not_commenced'].get(fy)} ≠ 正文 {txt_total}"))

    # 9) 分部「各申报口径」长表 + 自洽校验（重述列也必须自洽，校验放在闸门之前）
    views = build_segment_views(R)
    for sfy in YEARS:
        trev = table(R[sfy], SEG_TABLES["rev"])
        for fy in (sfy - 2, sfy - 1, sfy):
            tot = val(trev, fy, REV_ROW)
            rows_v = [x for x in views if x[0] == sfy and x[1] == fy and x[3] is not None]
            if tot is None or not rows_v:
                continue
            names = {x[2].lower() for x in rows_v}
            keys = [x for x in rows_v if (x[2].lower() in GROUP_2014 or "corporate" in x[2].lower())] \
                if GROUP_2014 <= names else rows_v
            s = sum(x[3] for x in keys)
            if abs(s - tot) > TOL:
                bad.append((fy, f"R{sfy} 分部重述列和 {s:g} ≠ 该申报合并营收 {tot:g}"))

    # ── MUST 探针：这些格必须有值（缺 = 某张附注表取数整段失效）──
    MUST = [
        ("分部营收", lambda fy: rev.get(fy), YEARS + [2009, 2010]),
        ("产品线营收", lambda fy: prod.get(fy), YEARS),
        ("地区营收", lambda fy: geo.get(fy), YEARS),
        ("递延收入分部", lambda fy: ueseg.get(fy), YEARS),
        ("固定资产原值", lambda fy: pp["gross"].get(fy), YEARS),
        ("折旧费用", lambda fy: pp["dep_exp"].get(fy), YEARS),
        ("营业外合计", lambda fy: oie["total"].get(fy), YEARS),
        # RPO 随 ASC 606（FY2018 10-K 全面追溯采用）才披露；FY2016-2017 那张表只有 Windows 10 递延额
        ("RPO", lambda fy: ue["rpo"].get(fy), list(range(2018, 2027))),
        ("融资租赁负债", lambda fy: ls["fin_liab"].get(fy), list(range(2019, 2027))),
        ("新增融资租赁使用权资产", lambda fy: ls["rou_new_fin"].get(fy), list(range(2019, 2027))),
        ("融资租赁本金支付", lambda fy: ls["pay_fin_prin"].get(fy), list(range(2019, 2027))),
        ("未起租租赁", lambda fy: ls["not_commenced"].get(fy), list(range(2019, 2027))),
        ("美国税前", lambda fy: tx["pbt_us"].get(fy), YEARS),
        ("递延所得税·折旧项（资产侧或负债侧至少一侧）",
         lambda fy: tx["dtl_dep"].get(fy) if tx["dtl_dep"].get(fy) is not None else tx["dta_dep"].get(fy),
         list(range(2019, 2027))),
        ("递延所得税净额", lambda fy: tx["net_dt"].get(fy), list(range(2019, 2027))),
        ("商誉按分部", lambda fy: gw.get(fy), list(range(2016, 2027))),
    ]
    for nm, fn, yrs in MUST:
        miss = [fy for fy in yrs if not fn(fy)]
        if miss:
            bad.append((0, f"MUST 探针缺格：{nm} @ {miss}"))

    if bad:
        print(f"🔴 附注层校验未过 {len(bad)} 条（不写出）：")
        for fy, msg in bad[:120]:
            print(f"  FY{fy} {msg}")
        if "--force" not in sys.argv:
            return 1

    with open(os.path.join(HERE, "分部-各申报口径.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# 单位: 百万美元 | 每份 10-K 的分部表三年全量（自身年 + 两个比较年）| 用途：口径重划后用**同一份申报**的三年做同口径增速 "
                    "| 已校验：每份申报每年分部(或组)+公司及其他 = 该申报合并营收"])
        w.writerow(["申报(10-K 财年)", "财年", "分部", "营收", "经营利润"])
        for sfy, fy, nm, v, o in sorted(views, key=lambda x: (x[0], x[1])):
            w.writerow([f"FY{sfy}", f"FY{fy}", nm, fmt(v), fmt(o)])
    print(f"  写出 分部-各申报口径.csv（{len(views)} 行）")
    with open(os.path.join(HERE, "分产品营收-各申报口径.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["# 单位: 百万美元 | 每份 10-K 产品线附注三年全量（自身年 + 两个比较年）| 用途：产品线更名/重划后，"
                    "用**同一份申报**的本年与比较年算同口径增速 | 已校验：每份申报每年分项和 = 该申报合计行"])
        w.writerow(["申报(10-K 财年)", "财年", "产品线(印刷名)", "营收"])
        for sfy, fy, nm, v in sorted(pviews, key=lambda x: (x[0], x[1])):
            w.writerow([f"FY{sfy}", f"FY{fy}", nm, fmt(v)])
        w.writerow([])
        w.writerow(["# 更名/重划链（机械判定：相邻两份 10-K 对**同一财年**的印刷名与数值逐格比对）"])
        w.writerow(["申报(10-K 财年)", "比对财年", "上一份 10-K 的行", "这一份 10-K 的行", "这一份印的值"])
        for b_, fy, old, new, v in prenames:
            w.writerow([f"FY{b_}", f"FY{fy}", old, new, fmt(v)])
        w.writerow([])
        w.writerow(["# 同名行被后一份 10-K 改了数（重述）"])
        w.writerow(["申报(10-K 财年)", "财年", "产品线", "上一份 10-K 印的值", "这一份 10-K 印的值"])
        for b_, fy, nm, vo, vn in prestates:
            w.writerow([f"FY{b_}", f"FY{fy}", nm, fmt(vo), fmt(vn)])
    print(f"  写出 分产品营收-各申报口径.csv（{len(pviews)} 行 · 更名/新增 {len(prenames)} · 重述 {len(prestates)}）")

    def gwide(series):
        """行名加口径代前缀：同名分部跨代（如 G3 与 G4 都叫 Server and Tools）口径不同、不可连线。"""
        out = {}
        for fy in sorted(series):
            g = gen_of.get(fy, "?").split(" ")[0]
            for k, v in series[fy].items():
                out.setdefault(f"{g}·{k}", {})[fy] = v
        return [(n, d, False) for n, d in out.items()]

    yrs_s = sorted(rev)
    gen_row = ("口径代", {fy: None for fy in yrs_s}, False)
    note_gen = ("口径代：G1 FY1997-2000 三大分部 / G2 FY2001-2002 四分部(.NET 重组) / G3 FY2003-2006 七分部 / "
                "G4 FY2007-2013 五大事业部 / G5 FY2014-2015 两组+子分部 / G6 FY2016 起 PBP·IC·MPC（FY2020、FY2025 两次组内重划）")
    write("分部营收.csv", "单位: 百万美元 | as-reported（各财年取自家 10-K 分部附注；FY1997-1998 取 FY1999 10-K 比较列=重述收入口径）| "
          f"⚠️ {note_gen}；**跨代不可拼接**，同代内的重划年份用 分部-各申报口径.csv 做同口径比较 | "
          "已校验：各年分部(或组)+调节项 = 合并营收，自家申报年份 = 利润表营收", yrs_s, gwide(rev),
          {fy: f"{sorigin.get(fy, '')}｜{gen_of.get(fy, '')}" for fy in yrs_s})
    write("分部经营利润.csv", "单位: 百万美元 | 同 分部营收.csv 口径 | 已校验：分部(或组)+调节项 = 合并营业利润 "
          "（FY1997 附注未给经营利润；FY2014-2015 只有分部组的经营利润，子分部只到毛利）", sorted(oi), gwide(oi),
          {fy: f"{sorigin.get(fy, '')}｜{gen_of.get(fy, '')}" for fy in sorted(oi)})
    pg_rows = {}
    for fy, (items, src, gen) in pg.items():
        for k, v in items.items():
            pg_rows.setdefault(f"{gen.split(' ')[0]}·{k}", {})[fy] = v
    ch_rows = {}
    for fy, (items, src) in ch.items():
        for k, v in items.items():
            ch_rows.setdefault(f"渠道·{k}", {})[fy] = v
    yrs_pg = sorted(set(pg) | set(ch))
    write("分产品组与渠道营收FY1992-1998.csv", "单位: 百万美元 | SFAS 131 之前 10-K 在 MD&A 正文自陈的产品组与销售渠道营收"
          "（FY1995 起以十亿美元两位小数列示·已×1000·精度 ±5 百万/项）| G0a=操作系统/应用/硬件三组(FY1994 10-K)、"
          "G0b=平台/应用与内容两组(FY1995-1998 10-K) | 已校验：各组和、各渠道和与利润表营收差 <0.5%", yrs_pg,
          [(n, d, False) for n, d in list(pg_rows.items()) + list(ch_rows.items())],
          {fy: (pg.get(fy, (None, "", ""))[1] or ch.get(fy, (None, ""))[1]) for fy in yrs_pg})
    write("分产品营收.csv", "单位: 百万美元 | 「Revenue Classified by Significant Product and Service Offerings」附注 | "
          "⚠️ 产品线划分与命名多次变更（FY2025 起「Office」改称「Microsoft 365」），按印刷名逐行列示、不强行归并 | "
          "已校验：各年分项和 = 利润表营收", sorted(prod), wide(prod), porigin)
    write("地区营收.csv", "单位: 百万美元 | 按客户所在地 | 已校验：分项和 = 利润表营收", sorted(geo), wide(geo), gorigin)
    rows_ue = [("递延收入合计(附注) Unearned revenue", ue["total"], False),
               ("剩余履约义务 RPO(总)", ue["rpo"], False),
               ("剩余履约义务 RPO(商业客户)", ue["rpo_comm"], False),
               ("RPO 中 12 个月内确认占比(%)", ue["rpo_12m_pct"], True),
               ("本年递延新增 Deferral of revenue", ue["deferral"], False),
               ("本年确认 Recognition of unearned revenue", ue["recognition"], False)]
    rows_ue += [(f"  分部·{k}", {fy: ueseg[fy].get(k) for fy in ueseg}, False)
                for k in dict.fromkeys(k for fy in sorted(ueseg) for k in ueseg[fy])]
    write("递延收入与RPO.csv", "单位: 百万美元（RPO 原表以十亿美元列示·已×1000）| 时点 = 财年末 | 递延收入按分部为附注口径、"
          "合计 = 资产负债表短期+长期递延收入（已校验）| RPO 自 FY2016 起披露；12 个月占比为公司自陈约数",
          YEARS, rows_ue)
    names_pp = [("土地 Land", "land"), ("建筑及改良 Buildings and improvements", "bld"),
                ("租赁物改良 Leasehold improvements", "lease_imp"),
                ("服务器·网络设备·软件 Computer equipment / Servers, network equipment, and software", "comp"),
                ("家具及设备 Furniture and equipment", "furn"), ("在建工程 Construction in progress", "cip"),
                ("原值合计 Total, at cost", "gross"), ("累计折旧 Accumulated depreciation", "accdep"),
                ("折旧费用(年度) Depreciation expense", "dep_exp"),
                ("仍挂应付账款的资本开支(期末) Purchases of P&E remaining in accounts payable", "capex_ap"),
                ("已承诺的在建工程支出 Committed for construction", "construct_commit")]
    write("固定资产明细.csv", "单位: 百万美元（附注原以十亿美元列示的行已×1000）| 含融资租赁资产（Microsoft 把融资租赁使用权资产计入固定资产）| "
          "已校验：分项和 = 原值；原值 − 累计折旧 = 资产负债表净额 | ⚠️ FY2023 起服务器/网络设备折旧年限 4→6 年（会计估计变更·见 README）",
          YEARS, [(n, pp[k], False) for n, k in names_pp])
    names_ls = [("经营租赁使用权资产 Operating lease ROU assets", "op_rou"), ("经营租赁负债合计 Operating lease liabilities", "op_liab"),
                ("融资租赁资产原值(在固定资产内) Finance lease P&E, at cost", "fin_ppe_gross"),
                ("融资租赁资产净值(在固定资产内) Finance lease P&E, net", "fin_ppe_net"),
                ("融资租赁负债合计 Finance lease liabilities", "fin_liab"),
                ("经营租赁成本 Operating lease cost", "op_cost"), ("融资租赁使用权资产摊销 Finance lease ROU amortization", "fin_amort"),
                ("融资租赁利息 Interest on finance lease liabilities", "fin_int"),
                ("🔴 已签未起租租赁合计(主要为数据中心) Leases not yet commenced", "not_commenced"),
                ("  其中：经营租赁 operating", "nc_op"), ("  其中：融资租赁 finance", "nc_fin"),
                ("经营租赁加权折现率(%)", "op_rate"), ("融资租赁加权折现率(%)", "fin_rate"),
                ("新增经营租赁使用权资产(非现金取得) ROU assets obtained · operating", "rou_new_op"),
                ("新增融资租赁使用权资产(非现金取得·不在资本开支内) ROU assets obtained · finance", "rou_new_fin"),
                ("经营租赁付款(经营活动) Operating cash flows from operating leases", "pay_op"),
                ("融资租赁利息付款(经营活动) Operating cash flows from finance leases", "pay_fin_int"),
                ("融资租赁本金付款(融资活动) Financing cash flows from finance leases", "pay_fin_prin")]
    write("租赁与承诺.csv", "单位: 百万美元（「未起租」原以十亿美元列示·已×1000）| 时点项 = 财年末；成本项 = 财年全年 | "
          "ASC 842 自 FY2019（截至 2019-06-30）起执行，FY2018 10-K 已按新准则提前披露 | "
          "⚠️ 融资租赁负债列在资产负债表「其他流动负债 / 其他长期负债」内、**不在长期债务行**；已签未起租租赁**不在表内**",
          YEARS, [(n, ls[k], k.endswith("rate")) for n, k in names_ls])
    names_oie = [("利息及股息收入 Interest and dividends income", "int_div"), ("利息费用 Interest expense", "int_exp"),
                 ("投资已确认净损益 Net recognized gains (losses) on investments", "inv_gain"),
                 ("衍生品净损益 Net gains (losses) on derivatives", "deriv"),
                 ("外汇重估净损益 Net gains (losses) on foreign currency remeasurements", "fx"),
                 ("其他净额(含权益法投资损益) Other, net", "other"), ("营业外收支合计 Total", "total"),
                 ("  其中：OpenAI 相关投资净损益(附注自陈) Net gains (losses) from OpenAI", "openai")]
    write("营业外收支明细.csv", "单位: 百万美元 | 已校验：分项和 = 合计 = 利润表营业外收支净额 | "
          "OpenAI 一行仅 FY2026 10-K 起单独披露（FY2024-2025 为该 10-K 比较列）", YEARS,
          [(n, oie[k], False) for n, k in names_oie])
    names_tx = [("税前利润·美国 U.S.", "pbt_us"), ("税前利润·境外 Foreign", "pbt_foreign"),
                ("当期所得税合计 Current taxes", "cur_total"), ("递延所得税合计 Deferred taxes", "def_total"),
                ("所得税费用 Provision", "prov"), ("实际税率(%) Effective rate", "etr"),
                ("未确认税收利益(期末) Unrecognized tax benefits", "utb"),
                ("递延所得税资产(扣估值准备后·期末) DTA net of valuation allowance", "dta_net_va"),
                ("递延所得税负债合计(期末·负数) Deferred income tax liabilities", "dtl"),
                ("  其中：折旧(负债侧=税务折旧快于账面) Depreciation", "dtl_dep"),
                ("递延所得税资产中：折旧(及摊销)(资产侧=账面折旧快于税务) Depreciation (and amortization)", "dta_dep"),
                ("递延所得税资产中：资本化研发 Capitalized R&D", "dta_rd"),
                ("递延所得税净资产(期末) Net deferred income tax assets", "net_dt")]
    write("所得税.csv", "单位: 百万美元 | 已校验：美国+境外税前 = 利润表税前；当期+递延 = 所得税费用 = 利润表；"
          "递延所得税资产净额+负债 = 净额 | 实际税率为附注自陈 | 递延项为期末时点、其余为财年全年", YEARS,
          [(n, tx[k], k == "etr") for n, k in names_tx])
    gw_rows = [(f"商誉·{k}", {fy: gw[fy].get(k) for fy in gw}, False)
               for k in dict.fromkeys(k for fy in sorted(gw) for k in gw[fy])]
    gw_rows.append(("商誉合计(= 资产负债表·FY2014-2015 只加两个分部组)",
                    {fy: sum(v for k, v in gw[fy].items()
                             if not (GROUP_2014 <= {x.lower() for x in gw[fy]}) or k.lower() in GROUP_2014)
                     for fy in gw}, False))
    gw_rows.append(("累计商誉减值(期末·附注自陈) Accumulated goodwill impairment", gw_imp, False))
    gw_rows.append(("动视暴雪收购日分配商誉(2023-10-13·FY2024 10-K 对价分配表)", {2024: act_gw} if act_gw else {}, False))
    write("商誉按分部.csv", "单位: 百万美元 | 时点 = 财年末 | 分部为当年 10-K 口径（FY2016 起 G6 三分部；FY2020、FY2025 重划时商誉随之重分配）| "
          "已校验：分部和 = 合计 = 资产负债表商誉 | 年度减值测试日 5 月 1 日（10-K Note「Goodwill」）", sorted(gw), gw_rows)
    if bad:
        print("⚠️ --force 写出（含未过校验项）")
    else:
        print("✅ 附注层校验全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
