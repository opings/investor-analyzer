#!/usr/bin/env python3
"""NVIDIA 附注层构建器：从各年 10-K（FY2012-FY2026）R 文件 Detail 表抽取分部 / 市场平台 / 地区 / 客户集中度 /
存货 / 供应与云服务承诺 / 非上市权益投资 / 股东回报 / 所得税，**每张表算术闸不过不写出**。

R 文件附注是「维度块」结构：无值行（tag 以 Axis / Member 结尾、或 tag 为空、或标签以 [Member] 结尾）开启一个成员块，
其后各行项属于该成员；第一个成员块之前的行 = 合并总数。成员标签在 FY2019 起常印成「Compute & Networking |
Operating Segments」（多轴叠加），FY2012-2013 的成员行**没有 tag**（只有标签）——两种都要认。

## 口径声明（取数当场固定）
- **期间**：财年全年（取 12 个月列）；时点项取该财年末。**来源年份 = 该财年自家 10-K 的当年列**（as-reported）；
  后续 10-K 的比较列只用于「各申报口径」核对与分部重划识别，不覆盖 as-reported。
- **主体**：合并口径。分部为管理层报告分部（ASC 280），**分部营业利润不含**股权激励、收购相关费用、部分 IP 相关
  费用等未分配项（在「All Other」）——分部利润之和 ≠ 合并营业利润，差额 = All Other。
- **单位**：百万美元；百分比为 %。
"""
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RDIR = os.path.join(HERE, "_rfiles")
FYS = [str(y) for y in range(2012, 2027)]


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower().replace("’", "'")


def scale_of(unit):
    u = norm(unit)
    if "in millions" in u:
        return 1.0
    if "in billions" in u:
        return 1e3
    if "in thousands" in u:
        return 1e-3
    return 1e-6          # FY2012 部分附注表单位行只印「(USD $)」= 美元


def is_member(r):
    tag = r.get("tag") or ""
    if any(v is not None for v in r["vals"]):
        return False
    if tag.endswith("LineItems") or tag.endswith("Abstract") or tag.endswith("Table"):
        return False
    return tag == "" or tag.endswith("Axis") or tag.endswith("Member") or r["label"].endswith("[Member]")


def blocks(det):
    """→ [(成员标签或 'TOTAL', 行)]。成员标签去掉「[Member]」。"""
    out, cur = [], "TOTAL"
    for r in det["rows"]:
        if is_member(r):
            cur = re.sub(r"\s*\[Member\]\s*", "", r["label"]).strip()
            continue
        out.append((cur, r))
    return out


FY_END = {2012: "Jan. 29, 2012", 2013: "Jan. 27, 2013", 2014: "Jan. 26, 2014", 2015: "Jan. 25, 2015",
          2016: "Jan. 31, 2016", 2017: "Jan. 29, 2017", 2018: "Jan. 28, 2018", 2019: "Jan. 27, 2019",
          2020: "Jan. 26, 2020", 2021: "Jan. 31, 2021", 2022: "Jan. 30, 2022", 2023: "Jan. 29, 2023",
          2024: "Jan. 28, 2024", 2025: "Jan. 26, 2025", 2026: "Jan. 25, 2026"}


def col_for(det, fy, months=12):
    """该财年列：优先「期间截止日 = 财年末日」（FY2025 承诺附注第一列是期后事项日 Feb. 05, 2025，按年份取会取错列）；
    再要求（期间类）期长 = months；时点类无 months。"""
    end = FY_END.get(int(fy)) if fy.isdigit() else None
    if end:
        for i, p in enumerate(det["periods"]):
            if p.startswith(end) and (not det["months"] or months is None or det["months"][i] == months):
                return i
    for i, p in enumerate(det["periods"]):
        m = re.search(r"\b((19|20)\d\d)\b", p)
        if not m or m.group(1) != fy:
            continue
        if det["months"]:
            if months is None or det["months"][i] == months:
                return i
            continue
        return i
    return None


def find(j, pat):
    hits = [k for k in j["details"] if re.search(pat, k, re.I)]
    return j["details"][hits[0]] if hits else None


def load():
    return {fy: json.load(open(os.path.join(RDIR, f"{fy}.json"))) for fy in FYS + ["2027Q1", "2027Q2"]
            if os.path.exists(os.path.join(RDIR, f"{fy}.json"))}


BAD, RUN = [], []


def chk(code, dv, tol=1e-6):
    RUN.append(code)
    if abs(dv) > tol:
        BAD.append((code, round(dv, 4)))


# ── 1. 分部（报告分部营收 / 营业利润 + All Other 调节） ─────────────────────────
GEN = {"gpu": "GPU", "psb": "PSB(专业解决方案)", "cpb": "CPB(消费产品·Tegra)", "tegra processor": "Tegra Processor",
       "compute & networking": "Compute & Networking(计算与网络)", "graphics": "Graphics(图形)", "all other": "All Other(未分配·调节项)"}
SEG_OF = {"gpu", "psb", "cpb", "tegra processor", "compute & networking", "graphics", "all other"}


def gen_of(fy):
    """G1 = GPU/PSB/CPB（FY2012 10-K 及更早）；G2 = GPU/Tegra Processor（FY2013 10-K 起，PSB 并入 GPU）；
    G3 = Compute & Networking/Graphics（FY2021 10-K 起）。按**该份 10-K 自己的成员名**判，不按年份猜。"""
    y = int(fy)
    return "G1" if y <= 2012 else ("G2" if y <= 2020 else "G3")


REV_TAGS = ("us-gaap_Revenues", "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax")


def seg_member(label):
    first = norm(label.split("|")[0])
    return first if first in SEG_OF else None


def segments(books):
    out = {}    # (行名) → {fy: v}
    for fy in FYS:
        j = books[fy]
        det = find(j, r"^Segment Information - Reportable Segments") or find(j, r"^Segment Information \(Details\)")
        if not det:
            BAD.append((f"分部表缺失 FY{fy}", 0))
            continue
        i = col_for(det, fy)
        sc = scale_of(det["unit"])
        tot_rev = tot_oi = None
        segs = {}
        for mem, r in blocks(det):
            v = r["vals"][i] if i is not None and i < len(r["vals"]) else None
            if v is None:
                continue
            v *= sc
            tag = r.get("tag")
            if mem == "TOTAL":
                if tag in REV_TAGS and tot_rev is None:
                    tot_rev = v
                if tag == "us-gaap_OperatingIncomeLoss" and tot_oi is None:
                    tot_oi = v
                continue
            sm = seg_member(mem)
            if not sm:
                continue
            if tag in REV_TAGS:
                segs.setdefault(sm, {})["rev"] = v
            elif tag == "us-gaap_OperatingIncomeLoss":
                segs.setdefault(sm, {})["oi"] = v
            elif tag in ("us-gaap_DepreciationAndAmortization", "us-gaap_DepreciationDepletionAndAmortization"):
                segs.setdefault(sm, {})["da"] = v
        # FY2026 表里「All Other」不在分部表、在调节项表：营业利润(合并) − 分部合计
        if "all other" not in segs and tot_oi is not None:
            rec = find(j, r"Reconciling Items")
            segs["all other"] = {"oi": tot_oi - sum(s.get("oi", 0) for k, s in segs.items())}
            if rec:
                segs["all other"]["_src"] = "调节项表"
        g = gen_of(fy)
        # MUST 探针：两个主分部的营收、营业利润与合并营收必须取到（第一版 FY2019-2022 营收整段为空、闸照样全过）
        main_segs = {"G1": ["gpu", "psb", "cpb"], "G2": ["gpu", "tegra processor"],
                     "G3": ["compute & networking", "graphics"]}[g]
        for sm in main_segs:
            for k in ("rev", "oi"):
                if segs.get(sm, {}).get(k) is None:
                    BAD.append((f"S0 FY{fy} 必需格缺失: {g}·{sm}·{k}", 0))
        if tot_rev is None:
            BAD.append((f"S0 FY{fy} 必需格缺失: 合并营收", 0))
        for sm, d in segs.items():
            for k, nm in (("rev", "营收"), ("oi", "营业利润"), ("da", "折旧摊销")):
                if k in d:
                    out.setdefault(f"{g}·{GEN[sm]}·{nm}", {})[fy] = d[k]
        # 闸：分部营收和 = 合并营收；分部营业利润和（含 All Other）= 合并营业利润
        if tot_rev is not None:
            chk(f"S1 FY{fy} 分部营收和=合并营收", sum(d.get("rev", 0) for d in segs.values()) - tot_rev)
        if tot_oi is not None:
            chk(f"S2 FY{fy} 分部营业利润和(含All Other)=合并营业利润", sum(d.get("oi", 0) for d in segs.values()) - tot_oi)
        out.setdefault("合并营收(分部表印)", {})[fy] = tot_rev
        out.setdefault("合并营业利润(分部表印)", {})[fy] = tot_oi
    return out


# ── 2. 市场平台营收（FY2016 起有表；Data Center FY2024 起拆 Compute / Networking） ──────────────
MKT = [("gaming", "Gaming(游戏)"), ("data center", "Data Center(数据中心)"), ("datacenter", "Data Center(数据中心)"),
       ("compute", "  其中 Compute(计算)"), ("networking", "  其中 Networking(网络)"),
       ("professional visualization", "Professional Visualization(专业可视化)"), ("automotive", "Automotive(汽车)"),
       ("oem and other", "OEM and Other(OEM及其他)"), ("oem & other", "OEM and Other(OEM及其他)"),
       ("oem & ip", "OEM & IP(OEM及授权·FY2014-2020口径)"), ("oem and ip", "OEM & IP(OEM及授权·FY2014-2020口径)")]


def markets(books):
    out, restate = {}, []
    for fy in FYS:
        det = find(books[fy], r"Revenue by Market")
        if not det:
            continue
        for fy2 in sorted({re.search(r"\b((19|20)\d\d)\b", p).group(1) for p in det["periods"]}):
            i = col_for(det, fy2)
            if i is None:
                continue
            sc = scale_of(det["unit"])
            tot, parts, sub = None, {}, {}
            for mem, r in blocks(det):
                v = r["vals"][i] if i < len(r["vals"]) else None
                if v is None or r.get("tag") not in ("us-gaap_Revenues", "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax"):
                    continue
                v *= sc
                if mem == "TOTAL":
                    tot = v if tot is None else tot
                    continue
                name = dict(MKT).get(norm(mem.split("|")[0]))
                if not name:
                    BAD.append((f"未识别的市场平台成员 FY{fy}:{mem}", 0))
                    continue
                (sub if name.startswith("  其中") else parts)[name] = v
            if fy2 == fy:
                for n, v in list(parts.items()) + list(sub.items()):
                    out.setdefault(n, {})[fy] = v
                if tot is not None:
                    chk(f"M1 FY{fy} 市场平台和=营收", sum(parts.values()) - tot)
                if sub:
                    chk(f"M2 FY{fy} Compute+Networking=Data Center", sum(sub.values()) - parts["Data Center(数据中心)"])
            else:
                restate.append((fy, fy2, parts, sub))
    # 比较列：较早年份按后一份 10-K 重述的口径（如 FY2024 10-K 把 FY2022-2023 的 Data Center 拆成 Compute/Networking）
    for fy, fy2, parts, sub in restate:
        for n, v in list(parts.items()) + list(sub.items()):
            if fy2 not in out.get(n, {}):
                out.setdefault(n + "【后续10-K比较列】", {}).setdefault(fy2, v)
    return out


# ── 3. 地区营收：🔴 两种口径（FY2026 Q3 起由「客户开票地」改「客户总部所在地」，并重列前期） ─────────────
REGION = {"united states": "美国 United States", "china": "中国(FY2012-2018 印「China」) China",
          "china (including hong kong)": "中国(含香港) China incl. Hong Kong",
          "taiwan, province of china": "台湾 Taiwan", "taiwan": "台湾 Taiwan",
          "other asia pacific": "其他亚太 Other Asia Pacific", "europe": "欧洲 Europe",
          "other americas": "其他美洲 Other Americas", "other countries": "其他国家 Other countries",
          "singapore": "新加坡 Singapore", "other": "其他 Other"}


def region_parts(det, fy2):
    i = col_for(det, fy2)
    if i is None:
        return None, {}
    sc = scale_of(det["unit"])
    tot, parts = None, {}
    for mem, r in blocks(det):
        v = r["vals"][i] if i < len(r["vals"]) else None
        if v is None or r.get("tag") not in REV_TAGS:
            continue
        v *= sc
        if mem == "TOTAL":
            tot = v if tot is None else tot
            continue
        if seg_member(mem):               # FY2012-2013 合表里的分部成员
            continue
        raw = norm(mem.split("|")[0])
        if raw not in REGION:
            BAD.append((f"未识别的地区成员 {fy2}:{mem}", 0))
            continue
        parts[REGION[raw]] = parts.get(REGION[raw], 0) + v
    return tot, parts


def regions(books):
    out = {}
    for fy in FYS:
        det = find(books[fy], r"Revenue and Long-lived Assets by Region") or \
            (find(books[fy], r"^Segment Information \(Details\)") if fy in ("2012", "2013") else None)
        if not det:
            continue
        basis = "总部口径" if int(fy) >= 2026 else "开票地口径"
        tot, parts = region_parts(det, fy)
        for k, v in parts.items():
            out.setdefault(f"【{basis}】{k}", {})[fy] = v
        if tot is not None and parts:
            chk(f"R1 FY{fy} 地区营收和=营收", sum(parts.values()) - tot)
        if fy == "2026":                  # FY2026 10-K 按总部口径重列 FY2024-2025
            for fy2 in ("2024", "2025"):
                t2, p2 = region_parts(det, fy2)
                for k, v in p2.items():
                    out.setdefault(f"【总部口径】{k}", {})[fy2] = v
                if t2 is not None and p2:
                    chk(f"R2 FY{fy2}(FY2026 10-K 重列) 地区营收和=营收", sum(p2.values()) - t2)
    return out


# ── 4. 采购与供应 / 云服务 / 投资承诺（表外·10-K「Commitments」附注） ─────────────────────
COMMIT_TAGS = {
    "us-gaap_PurchaseObligation": "采购义务合计(到期表·FY2022-2025) Total purchase obligations",
}


def commitments(books):
    out = {}
    for fy in FYS:
        j = books[fy]
        for name, det in j["details"].items():
            if not re.search(r"Commitment", name, re.I):
                continue
            i = col_for(det, fy, months=None)
            if i is None:
                continue
            sc = scale_of(det["unit"])
            for mem, r in blocks(det):
                v = r["vals"][i] if i < len(r["vals"]) else None
                tag = r.get("tag") or ""
                if v is None:
                    continue
                v *= sc
                m = norm(mem)
                if re.search(r"InventoryPurchaseObligation$", tag) or "InventoryPurchaseAndSupplyAgreement" in tag or \
                        (tag == "us-gaap_OtherCommitment" and "manufacturing production" in m):
                    out.setdefault("存货采购及长期供应与产能义务 Inventory purchase / supply & capacity obligations", {})[fy] = v
                elif tag.endswith("CapitalPurchaseObligations"):
                    out.setdefault("资本性采购义务(FY2012-2019) Capital purchase obligations", {})[fy] = v
                elif tag == "us-gaap_OtherCommitment" and "cloud service" in m:
                    out.setdefault("多年期云服务协议(FY2026 起单列) Multi-year cloud service agreements", {})[fy] = v
                elif tag == "us-gaap_OtherCommitment" and "license and service" in m:
                    out.setdefault("  其中 授权与服务(FY2025 自陈=多年期云服务协议) License and service", {})[fy] = v
                elif tag == "us-gaap_OtherCommitment" and "investment commitments" in m:
                    out.setdefault("投资承诺(FY2026 起单列) Investment commitments", {})[fy] = v
                elif tag == "us-gaap_OtherCommitment" and m == "other commitments":
                    out.setdefault("其他承诺(FY2026) Other commitments", {})[fy] = v
                elif tag == "us-gaap_OtherCommitment" and m == "total":
                    out.setdefault("其他非存货采购义务(FY2022-2025) Other non-inventory purchase obligations", {})[fy] = v
                elif tag == "us-gaap_PurchaseObligation" and m == "total" and r["label"].lower().startswith("total"):
                    out.setdefault(COMMIT_TAGS[tag], {})[fy] = v
                elif tag == "us-gaap_PurchaseObligation" and m == "total" and "other" in r["label"].lower():
                    out.setdefault("其他采购义务(FY2020-2021) Other purchase obligations", {})[fy] = v
                elif tag.endswith("PurchaseObligationSupplyAgreements") and m == "total":
                    out.setdefault("长期供应协议(含预付·FY2022-2023) Supply agreements", {})[fy] = v
                elif tag == "us-gaap_ProductWarrantyAccrual" and m == "total":
                    out.setdefault("产品保修准备 Warranty accrual", {})[fy] = v
    # 闸：FY2022-2025 到期表合计 = 存货供应义务 + 其他非存货采购义务
    for fy in ("2022", "2023", "2024", "2025"):
        tot = out.get(COMMIT_TAGS["us-gaap_PurchaseObligation"], {}).get(fy)
        a = out.get("存货采购及长期供应与产能义务 Inventory purchase / supply & capacity obligations", {}).get(fy)
        b = out.get("其他非存货采购义务(FY2022-2025) Other non-inventory purchase obligations", {}).get(fy)
        if None in (tot, a, b):
            BAD.append((f"K0 FY{fy} 承诺必需格缺失", 0))
            continue
        # 10-K 正文给的是十亿美元一位小数（30.8 / 14.3），到期表是百万：容差 = 正文舍入 0.05B×2
        chk(f"K1 FY{fy} 到期表合计≈存货供应义务+其他非存货义务", tot - a - b, tol=100.0)
    return out


# ── 写出 ────────────────────────────────────────────────────────────────────
def fmtv(v):
    if v is None:
        return ""
    r = round(v, 3)
    return str(int(round(r))) if abs(r - round(r)) < 1e-9 else f"{r:.3f}".rstrip("0").rstrip(".")


def write(fname, note, data, cols):
    with open(os.path.join(HERE, fname), "w", newline="") as f:
        f.write(note + "\n")
        w = csv.writer(f)
        w.writerow(["科目"] + [f"FY{c}" for c in cols])
        for name, vv in data.items():
            vals = [vv.get(c) for c in cols]
            if all(v is None for v in vals):
                continue
            w.writerow([name] + [fmtv(v) for v in vals])


# ── 5. 客户集中度（占合并营收 / 应收账款的百分比，公司自陈） ───────────────────────────
def concentration(books):
    rows = []
    for fy in FYS:
        for name, det in books[fy]["details"].items():
            if not re.search(r"Major Customer|Segment Information - Narrative|Balance Sheet Components - Narrative|Concentration",
                             name, re.I):
                continue
            i = col_for(det, fy, months=None)
            if i is None:
                i = col_for(det, fy)
            if i is None:
                continue
            for mem, r in blocks(det):
                if r.get("tag") != "us-gaap_ConcentrationRiskPercentage1":
                    continue
                v = r["vals"][i] if i < len(r["vals"]) else None
                if v is None:
                    continue
                rows.append((fy, re.sub(r"\s+", " ", mem), v, name))
    return rows


# ── 6. 存货构成（原材料 / 在制品 / 产成品；闸：和 = 资产负债表存货） ───────────────────────
def inventories(books):
    """按 tag 跨表扫：FY2012-2020 的存货构成合在「Balance Sheet Components (Details)」大表里，按表名找只拿到 FY2021 起；
    按标签找又会撞上「Work in-process」连字符写法（第一版 FY2021-2024 在制品整格漏取，I1 抓出）——tag 两头都不怕。"""
    out = {}
    tagmap = {"us-gaap_InventoryRawMaterialsNetOfReserves": "原材料 Raw materials",
              "us-gaap_InventoryRawMaterials": "原材料 Raw materials",
              "us-gaap_InventoryWorkInProcessNetOfReserves": "在制品 Work in process",
              "us-gaap_InventoryWorkInProcess": "在制品 Work in process",
              "us-gaap_InventoryFinishedGoodsNetOfReserves": "产成品 Finished goods",
              "us-gaap_InventoryFinishedGoods": "产成品 Finished goods"}
    for fy in FYS:
        parts, tot = {}, None
        for name, det in books[fy]["details"].items():
            i = col_for(det, fy, months=None)
            if i is None:
                continue
            sc = scale_of(det["unit"])
            got, gtot = {}, None
            for mem, r in blocks(det):
                if mem != "TOTAL":
                    continue
                v = r["vals"][i] if i < len(r["vals"]) else None
                if v is None:
                    continue
                if r.get("tag") in tagmap:
                    got[tagmap[r["tag"]]] = v * sc
                if r.get("tag") == "us-gaap_InventoryNet":
                    gtot = v * sc
            if len(got) >= 2 and not parts:
                parts, tot = got, gtot
        if not parts:
            continue
        for nm, v in parts.items():
            out.setdefault(nm, {})[fy] = v
        if tot is None:
            # 构成表不印合计时，与资产负债表存货（三表 CSV）比
            tot = BS_INV.get(fy)
        if tot is not None:
            out.setdefault("存货合计 Total inventories", {})[fy] = tot
            chk(f"I1 FY{fy} 存货构成和=存货合计", sum(parts.values()) - tot, tol=1e-6)
        else:
            BAD.append((f"I0 FY{fy} 存货合计缺失", 0))
    return out


def bs_inventories():
    """读三表 CSV 的存货行作 I1 的对照（构建器读另一构建器产物：探针行 + 必需值自检，记忆 chained-builder-silent-truncation）。"""
    rows = list(csv.reader(open(os.path.join(HERE, "资产负债表.csv"))))
    hdr = next((i for i, r in enumerate(rows) if r and r[0] == "科目"), None)
    if hdr is None:
        raise SystemExit("❌ 资产负债表.csv 找不到表头行「科目」")
    inv = next((r for r in rows[hdr + 1:] if r and r[0].startswith("存货 Inventories")), None)
    if inv is None:
        raise SystemExit("❌ 探针行「存货 Inventories」找不到——上游 CSV 表头/行名变了")
    out = {h[2:]: float(v) for h, v in zip(rows[hdr][1:], inv[1:]) if v}
    if not all(str(y) in out for y in range(2012, 2027)):
        raise SystemExit("❌ 资产负债表.csv 存货 FY2012-2026 有缺格")
    return out


BS_INV = {}


# ── 7. 非上市权益证券滚动表（FY2025 起附注单列） ────────────────────────────────────
def nonmarketable(books):
    out = {}
    names = [("balance at beginning", "期初余额 Balance at beginning"), ("net additions", "当期净增 Net additions"),
             ("unrealized gains", "公允调增(可观察价格) Unrealized gains"), ("reclassification", "重分类 Reclassification"),
             ("impairments", "减值及未实现损失 Impairments and unrealized losses"),
             ("balance at end", "期末余额 Balance at end")]
    # 只取 FY2026 10-K 的滚动表（FY2025 列为其比较列）：FY2025 10-K 同表行项拆法不同（表名还挂在公允价值附注下）
    for fy in ("2026",):
        det = find(books[fy], r"^Non-marketable Equity Securities - Carrying")
        if not det:
            BAD.append(("N0 FY2026 非上市权益滚动表缺失", 0))
            continue
        for fy2 in ("2025", "2026"):
            i = col_for(det, fy2)
            if i is None or (fy2 in out.get("期末余额 Balance at end", {})):
                continue
            vals = {}
            for mem, r in blocks(det):
                v = r["vals"][i] if i < len(r["vals"]) else None
                if v is None:
                    continue
                l = norm(r["label"])
                for k, nm in names:
                    if l.startswith(k):
                        vals[nm] = v * scale_of(det["unit"])
            for nm, v in vals.items():
                out.setdefault(nm, {})[fy2] = v
            if len(vals) >= 3:
                body = sum(v for nm, v in vals.items() if not nm.startswith("期末"))
                chk(f"N1 FY{fy2} 期初+变动=期末", body - vals.get("期末余额 Balance at end", 0))
    return out


# ── 8. 回购授权余额（Shareholders' Equity 附注） ────────────────────────────────────
def buyback_auth(books):
    out = {}
    for fy in FYS:
        for name, det in books[fy]["details"].items():
            if not re.search(r"Shareholders'? Equity|Stockholders'? Equity|Capital Return", name, re.I):
                continue
            for mem, r in blocks(det):
                if r.get("tag") != "us-gaap_StockRepurchaseProgramRemainingAuthorizedRepurchaseAmount1":
                    continue
                i = col_for(det, fy, months=None)
                if i is None:
                    i = col_for(det, fy)
                v = r["vals"][i] if (i is not None and i < len(r["vals"])) else None
                if v is not None and fy not in out.get("回购授权剩余额度(年末) Remaining repurchase authorization", {}):
                    out.setdefault("回购授权剩余额度(年末) Remaining repurchase authorization", {})[fy] = v * scale_of(det["unit"])
    return out


def main():
    books = load()
    BS_INV.update(bs_inventories())
    seg = segments(books)
    mkt = markets(books)
    reg = regions(books)
    com = commitments(books)
    conc = concentration(books)
    inv = inventories(books)
    nme = nonmarketable(books)
    print(f"附注勾稽执行 {len(RUN)} 条")
    if BAD:
        print(f"❌ 不通过 {len(BAD)} 条（不写出）：")
        for b in BAD:
            print("   ", b)
        return 1
    cols = FYS
    mcols = [str(y) for y in range(2014, 2027)]
    write("分部营收.csv",
          "# 单位: 百万美元 | as-reported(各财年取自家 10-K 当年列) | 行名前缀 = 分部口径代(G1 FY2012-2013: GPU/PSB/CPB; "
          "G2 FY2014-2020: GPU/Tegra Processor; G3 FY2021 起: Compute & Networking/Graphics)，**跨代不可拼接** | "
          "分部营业利润不含未分配项，All Other = 合并营业利润 − 分部合计(FY2026 表未单列，按差额计) | 闸: 分部营收和=合并营收、分部利润和=合并营业利润",
          seg, cols)
    write("市场平台营收.csv",
          "# 单位: 百万美元 | 公司自陈「按市场平台」口径(ASC 606 收入分解) | as-reported 取自家 10-K 当年列；"
          "「【后续10-K比较列】」行 = 自家 10-K 未单列、由后一份 10-K 比较列补出的重分类口径 | Data Center 自 FY2024 起拆 Compute/Networking | "
          "FY2020 及以前「OEM & IP」含英特尔专利授权费，FY2021 起改「OEM and Other」 | 闸: 各平台和=营收 | "
          "🔴 **FY2027 Q1 起公司改用新口径**(数据中心 = Hyperscale + ACIE「AI 云·工业·企业」；边缘计算 = PC / 游戏机 / 工作站 / "
          "AI-RAN 基站 / 机器人 / 汽车)，本表为旧口径、与新口径不可拼接；新口径季度数见 中期财务-FY2027.csv，FY2026 全年新口径值待 FY2027 10-K 比较列(⏳)",
          mkt, mcols)
    write("地区营收.csv",
          "# 单位: 百万美元 | 🔴 **两种口径不可拼接**：【开票地口径】= FY2012-2025 各年 10-K as-reported(客户开票地·billing location)；"
          "【总部口径】= FY2026 10-K 起(公司自陈「In the third quarter of fiscal year 2026, we changed to revenue based upon the location of "
          "our customers’ headquarters」——自 FY2026 第三季度起改按客户总部所在地)，并由 FY2026 10-K 重列 FY2024-2025 | 均非最终使用地 | "
          "地区划分逐年有变(新加坡等单列始于不同年份) | 闸: 各地区和=营收",
          reg, cols)
    write("采购与云服务承诺.csv",
          "# 单位: 百万美元 | 表外承诺(10-K「Commitments」附注·各财年末时点·as-reported) | 名目与范围逐年变：FY2021 及以前=存货采购义务；"
          "FY2022 起=存货采购及长期供应与产能义务(含产能预留)；FY2026 起改称「Manufacturing, supply, and capacity commitments」并把多年期云服务协议、"
          "投资承诺、其他承诺单列 | 「授权与服务」= FY2025 10-K 自陈「including $10.9 billion of multi-year cloud service agreements」 | "
          "闸: FY2022-2025 到期表合计≈两类义务之和(正文为十亿一位小数·容差 1 亿)",
          com, cols)
    write("存货构成.csv", "# 单位: 百万美元 | 各财年末 | as-reported 取自家 10-K 附注 | 闸: 原材料+在制品+产成品=存货合计", inv, cols)
    write("非上市权益投资.csv",
          "# 单位: 百万美元 | 非上市权益证券(计量替代法: 成本−减值±可观察交易价格调整) 滚动表 | FY2025-2026 **均取 FY2026 10-K 附注**(FY2025 列为比较列) | "
          "年末余额 = 资产负债表「非上市权益证券」(FY2026 单列) | 闸: 期初+各项变动=期末", nme, ["2025", "2026"])
    with open(os.path.join(HERE, "客户集中度.csv"), "w", newline="") as f:
        f.write("# 单位: % | 10-K 自陈的客户集中度(占合并营收或应收账款)；成员路径照 XBRL 原文 | **XBRL 标注始于 FY2019**，更早年份只在正文文字里"
                "(未入本表·⏳) | 直接客户 = 直接向 NVIDIA 下单者(ODM/OEM/分销/CSP…)，"
                "**间接客户(终端 CSP/AI 公司)集中度公司只给定性描述**——FY2026 10-K: 「We estimate that one AI research and deployment company "
                "contributed to a meaningful amount of our revenue purchasing cloud services from our customers in fiscal year 2026.」"
                "(译: 我们估计一家 AI 研究与部署公司通过向我们的客户购买云服务，在 FY2026 为我们贡献了可观收入)\n")
        w = csv.writer(f)
        w.writerow(["财年", "成员路径(XBRL 原文)", "占比%", "附注表"])
        for r in conc:
            w.writerow(["FY" + r[0], r[1], fmtv(r[2]), r[3]])
    print(f"✅ 写出 分部营收 / 市场平台营收 / 地区营收 / 采购与云服务承诺 / 存货构成 / 非上市权益投资 / 客户集中度（{len(conc)} 行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
