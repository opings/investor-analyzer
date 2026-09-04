#!/usr/bin/env python3
"""AGC(5201) 日文财报三表 + 分部提取器 —— 一手 有価証券報告書 / 決算短信 → _extract_json/fy<YYYY>.json

管线：pypdf **plain** 模式抽文 → 分节 → 概念锚定（日文科目正则）→ 每年 {前期, 当期} 两列

日本财报三个必须专门处理的坑（都实测过）：
  1) **△ 是负号**（日本会计惯例），不是装饰符。'△1,568,552' = -1,568,552；
     '△ 6,534'（△ 与数字之间有空格）也要认。漏了这条，成本/费用/亏损会**全部变正**。
  2) **列序与中国年报相反**：日文报表左列 = 前連結会計年度（上年），右列 = 当連結会計年度（本年）。
     按中国习惯默认「本年在前」会把每一年整体错位一年。
  3) **layout 模式对 AGC 的 PDF 失效**（只抽出页眉），必须用 plain 模式；
     因此没有列位信息，单值行靠「行内 token 顺序 + 下游勾稽」兜底。
"""
import json
import os
import re
import sys

from pypdf import PdfReader

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
PDF_DIR = os.path.join(ROOT, "report", "AGC旭硝子")
OUT_DIR = os.path.join(HERE, "_extract_json")

# 数字 token：可带 △/▲/- 负号，千分位，小数。
# 每个分支都必须以数字**开头或包含数字**——早期写成 [\d,]+ 会匹配到**单个逗号**，
# 归一后成空串，to_num 取 t[0] 直接崩。
# 末尾的负向断言：数字后面若紧跟日文量词（年/月/日/株/期…），它是**科目名的一部分**不是金额。
# 不加这条会出两类错：
#   「1年内返済予定の長期有利子負債」被吃掉开头的 1 → 科目名对不上、整行丢失；
#   「基本的1株当たり当期純利益」同理；表头的 2025年12月31日 也会混进金额。
CNT = r"(?![年月日株期回名件％%円銭])"
TOKEN_RE = re.compile(
    r"[△▲]\s*\d[\d,]*(?:\.\d+)?" + CNT
    + r"|-\s*\d[\d,]*(?:\.\d+)?" + CNT
    + r"|\d[\d,]*(?:\.\d+)?" + CNT
)
NILS = {"－", "-", "―", "—", "‐"}
# 单元格 = 数字 或 nil 占位符。分部表必须按「格」读：
# 「179 － 3,141 213 …」若把 － 丢掉，后面每一列都会左移一格（建築的数变成オート的数）。
# nil 占位符必须**独立成格**（两侧是空白或行首尾）才算——
# 否则会误吃科目名里的连字符（如「Low－E（低放射）ガラス」）。
CELL_RE = re.compile(TOKEN_RE.pattern + r"|(?<![^\s　])[－―—‐](?![^\s　])")


def parse_cells(line: str):
    """按出现顺序返回单元格列表，nil 位保留为 None（保列位用）。"""
    out = []
    for m in CELL_RE.finditer(line):
        s = m.group(0)
        out.append(None if s.strip() in NILS else to_num(s))
    return out


def to_num(tok: str):
    t = tok.replace(",", "").replace(" ", "").replace("　", "")
    if not t:
        return None
    neg = t[0] in "△▲-"
    if neg:
        t = t[1:]
    if not t or not re.fullmatch(r"\d+(?:\.\d+)?", t):
        return None
    v = float(t)
    return -v if neg else v


FW = str.maketrans("０１２３４５６７８９（）：，．", "0123456789():,.")


def norm(s: str) -> str:
    """全角→半角 + 去空白。

    早年有報用**全角数字**写科目名（'基本的１株当たり当期純利益'、'１年内返済予定…'），
    不归一就匹配不上半角写法的正则，该科目整列静默为空。
    """
    s = s.translate(FW)
    return re.sub(r"[\s　]+", "", s)


def page_lines(pdf_path):
    """AGC 的 PDF 必须用 plain 模式（layout 模式只抽得到页眉）。"""
    reader = PdfReader(pdf_path)
    out = []
    for i, pg in enumerate(reader.pages):
        try:
            t = pg.extract_text() or ""
        except Exception:
            t = ""
        for ln in t.split("\n"):
            if ln.strip():
                out.append((i, ln))
    return out


def parse_row(line: str):
    """一行 → (归一化科目名, [数值...])。△ 视为负号。"""
    toks = [m.group(0) for m in TOKEN_RE.finditer(line)]
    vals = [to_num(t) for t in toks]
    vals = [v for v in vals if v is not None]
    label = TOKEN_RE.sub(" ", line)
    for n in NILS:
        label = label.replace(n, " ")
    return norm(label), vals


# ---------------------------------------------------------------- 分节
# 有報与決算短信的表名一致；有報里还会出现「(1)連結財政状態計算書」等编号前缀。
SECTIONS = {
    "BS": (r"連結財政状態計算書", r"連結純損益計算書|連結損益計算書|連結包括利益計算書"),
    "IS": (r"連結純損益計算書|連結損益計算書", r"連結包括利益計算書|連結持分変動計算書"),
    "CF": (r"連結キャッシュ・?フロー計算書", r"連結財務諸表注記|セグメント情報|重要な会計方針"),
}
ANCHOR = {"BS": "資産合計", "IS": "売上高", "CF": "営業活動によるキャッシュ"}
MAX_SEC = 120


# 页级归属：AGC 的 PDF **把表名排在该页表体之后**（plain 抽文里标题行出现在数字之后），
# 所以「从标题往后切」会整段错开——BS 只切到负债那半页、CF 一条都切不到。
# 改为：先判定**每一页属于哪张表**（标题在页内任意位置即算），无标题页顺延前一页的归属。
PAGE_TITLES = [
    ("BS", re.compile(r"連結財政状態計算書")),
    ("IS", re.compile(r"連結純損益計算書|連結損益計算書")),
    ("CI", re.compile(r"連結包括利益計算書")),
    ("EQ", re.compile(r"連結持分変動計算書|連結株主資本等変動計算書")),
    ("CF", re.compile(r"連結キャッシュ・?フロー計算書")),
]
# 単体（個別）财务报表 —— 必须排除，否则会把母公司数当合并数
SOLO_RE = re.compile(r"^\(?[0-9１-９]?\)?貸借対照表$|^\(?[0-9１-９]?\)?損益計算書$"
                     r"|個別財務諸表|財務諸表等|^\(2\)主な資産")
# 🚨 IFRS 移行期（FY2013 有報）里同时印着**日本基準的「要約」连结报表**做准则调节。
# 那张表长得像损益表却是 JGAAP 结构（営業外収益/経常利益/特別損益/少数株主利益），
# 且 売上原価 以**正数**列示。误抓它会让 FY2012/FY2013 整段勾稽崩掉、
# 还会把 JGAAP 的営業利益 当成 IFRS 的営業利益（実測差 9,169 百万円）。
JGAAP_RE = re.compile(r"日本基準|要約連結|米国会計基準")


def page_kinds(lines):
    """返回 {page_idx: kind}。标题在页内任意位置即判定该页归属；无标题页顺延。"""
    by_page = {}
    for p, ln in lines:
        by_page.setdefault(p, []).append(ln)
    kinds, cur, solo, since = {}, None, False, 0
    for p in sorted(by_page):
        raw = "".join(by_page[p])
        txt = norm(raw)
        if SOLO_RE.search(txt):
            solo = True
        if JGAAP_RE.search(txt):
            # 日本基準/要約 页：既不归属任何 IFRS 表，也切断顺延
            kinds[p] = None
            cur, since = None, 0
            continue
        hit = None
        for k, rx in PAGE_TITLES:
            if rx.search(txt):
                hit = k
                break
        if hit:
            cur, solo, since = hit, False, 0
        else:
            since += 1
            # 有報 里报表之后紧跟大段附注，同名科目会重复出现。
            # 用【】小节标记 + 页数上限收口，避免把附注整段并进报表节。
            if "【" in raw or since > 3:
                cur = None
        kinds[p] = None if solo else cur
    return kinds


def slice_section(lines, kind):
    kinds = page_kinds(lines)
    seg = [(p, ln) for p, ln in lines if kinds.get(p) == kind]
    if not seg:
        return []
    if ANCHOR[kind] not in "".join(norm(ln) for _, ln in seg):
        return []
    return seg


# ---------------------------------------------------------------- 概念表（日文）

IS_CONCEPTS = [
    ("売上高", r"^売上高$|^売上収益$"),
    ("売上原価", r"^売上原価$"),
    ("売上総利益", r"^売上総利益$"),
    ("販売費及び一般管理費", r"^販売費及び一般管理費$"),
    # 早年有報写「持分法による投資利益」，近年写「…投資損益」——两种都要认
    ("持分法による投資損益", r"^持分法による投資(損益|利益)"),
    ("営業利益", r"^営業利益$|^営業利益\(.{0,12}\)$"),
    ("その他収益", r"^その他収益$"),
    ("その他費用", r"^その他費用$"),
    ("事業利益", r"^事業利益"),
    ("金融収益", r"^金融収益$"),
    ("金融費用", r"^金融費用$"),
    ("税引前利益", r"^税引前利益|^税引前当期利益"),
    ("法人所得税費用", r"^法人所得税費用$|^法人税等"),
    ("当期純利益", r"^当期純利益(\(.{0,12}\))?$"),
    ("親会社所有者帰属当期純利益", r"^親会社の所有者に帰属する当期純利益"),
    ("非支配持分帰属当期純利益", r"^非支配持分に帰属する当期純利益"),
    ("基本的1株当たり当期純利益", r"^基本的1株当たり当期純利益"),
    ("希薄化後1株当たり当期純利益", r"^希薄化後1株当たり当期純利益"),
]

BS_CONCEPTS = [
    ("現金及び現金同等物", r"^現金及び現金同等物$"),
    ("営業債権", r"^営業債権"),
    ("棚卸資産", r"^棚卸資産$"),
    ("その他の債権", r"^その他の債権$"),
    ("その他の流動資産", r"^その他の流動資産$"),
    ("流動資産合計", r"^流動資産合計$"),
    ("有形固定資産", r"^有形固定資産$"),
    ("のれん", r"^のれん$"),
    ("無形資産", r"^無形資産$"),
    ("持分法投資", r"^持分法で会計処理されている投資$"),
    ("その他の金融資産", r"^その他の金融資産$"),
    ("繰延税金資産", r"^繰延税金資産$"),
    ("その他の非流動資産", r"^その他の非流動資産$"),
    ("非流動資産合計", r"^非流動資産合計$"),
    ("資産合計", r"^資産合計$"),
    ("営業債務", r"^営業債務$"),
    ("短期有利子負債", r"^短期有利子負債$"),
    ("1年内返済予定長期有利子負債", r"^1年内返済予定の長期有利子負債$"),
    ("その他の債務", r"^その他の債務$"),
    ("流動負債合計", r"^流動負債合計$"),
    ("長期有利子負債", r"^長期有利子負債$"),
    ("繰延税金負債", r"^繰延税金負債$"),
    ("退職給付に係る負債", r"^退職給付に係る負債$"),
    ("非流動負債合計", r"^非流動負債合計$"),
    ("負債合計", r"^負債合計$"),
    ("資本金", r"^資本金$"),
    ("資本剰余金", r"^資本剰余金$"),
    ("利益剰余金", r"^利益剰余金$"),
    ("自己株式", r"^自己株式$"),
    ("その他の資本の構成要素", r"^その他の資本の構成要素$"),
    ("親会社所有者帰属持分合計", r"^親会社の所有者に帰属する持分合計$"),
    ("非支配持分", r"^非支配持分$"),
    ("資本合計", r"^資本合計$"),
    ("負債及び資本合計", r"^負債及び資本合計$"),
]

CF_CONCEPTS = [
    ("税引前利益_CF", r"^税引前利益"),
    ("減価償却費及び償却費", r"^減価償却費及び償却費$"),
    ("減損損失_CF", r"^減損損失$"),
    ("営業CF小計", r"^小計$"),
    ("法人所得税の支払額", r"^法人所得税の支払額$"),
    ("営業活動によるキャッシュフロー", r"^営業活動によるキャッシュ・?フロー$"),
    ("投資活動によるキャッシュフロー", r"^投資活動によるキャッシュ・?フロー$"),
    ("財務活動によるキャッシュフロー", r"^財務活動によるキャッシュ・?フロー$"),
    # 有報 用「有形固定資産及び無形資産の取得による支出」；短信 版可能简写
    ("capex", r"^有形固定資産及び無形資産の取得による支出$|^有形固定資産の取得による支出$"),
    ("有形固定資産の売却収入", r"^有形固定資産の売却による収入$"),
    ("配当金の支払額", r"^配当金の支払額$"),
    ("換算差額", r"^現金及び現金同等物に係る換算差額$"),
    # 近年新增的一行：持有待售资产里含的现金变动。它夹在「換算差額」与「増減額」之间，
    # 漏掉它会让「営業+投資+財務+換算差額 = 増減額」差 700 上下（FY2024 -707 / FY2025 +712）。
    ("売却目的保有資産の現金増減", r"^売却目的で保有する資産に含まれる現金及び現金同等物の増減額"),
    ("現金及び現金同等物の増減額", r"^現金及び現金同等物の増減額"),
    ("現金及び現金同等物の期首残高", r"^現金及び現金同等物の期首残高$"),
    ("現金及び現金同等物の期末残高", r"^現金及び現金同等物の期末残高$"),
]

CONCEPTS = {"IS": IS_CONCEPTS, "BS": BS_CONCEPTS, "CF": CF_CONCEPTS}


def extract_section(lines, kind):
    seg = slice_section(lines, kind)
    if not seg:
        return {}, [f"{kind}: 未找到分节"]
    rows, plain = [], {}
    for idx, (_, ln) in enumerate(seg):
        label, _nums = parse_row(ln)
        # 用 nil 感知的 parse_cells 而非 parse_row：某些年某行只有一列有数、另一列是「－」
        # （FY2024 短信「売却目的で保有する資産に含まれる現金…」即如此）。
        # 丢掉 nil 会让单值行无法判定属于前期还是当期。
        cells = parse_cells(ln)
        if any(c is not None for c in cells):
            rows.append([label, cells, idx])
        else:
            plain[idx] = label
    warns, out, used = [], {}, set()
    compiled = [(c, re.compile(p)) for c, p in CONCEPTS[kind]]

    def self_hit(lb):
        return any(rx.search(lb) for _, rx in compiled)

    # 第 1 遍：行自身标签
    for concept, rx in compiled:
        for ri, (label, vals, idx) in enumerate(rows):
            if ri in used:
                continue
            if rx.search(label):
                out[concept] = pick2(vals, kind, concept, warns)
                used.add(ri)
                break
    # 第 2 遍：标签断行（数字行自身不成词时，向前拼最近的无数字行）
    for ri, (label, vals, idx) in enumerate(rows):
        if ri in used or self_hit(label):
            continue
        for k in (1, 2, 3):
            prev = "".join(plain.get(idx - j, "") for j in range(k, 0, -1))
            if not prev:
                continue
            cand = prev + label
            hit = None
            for concept, rx in compiled:
                if concept in out:
                    continue
                if rx.search(cand):
                    hit = concept
                    break
            if hit:
                out[hit] = pick2(vals, kind, hit, warns)
                used.add(ri)
                break
    return out, warns


def pick2(vals, kind, concept, warns):
    """日文报表列序 = [前期, 当期]，取**最后两个**数字。

    有報 的行格式是「科目名 [注記番号] 前期 当期」——注記番号在最左边
    （'売上高 19 1,326,293 1,282,570'）。取前两个会把注記番号当成前期金额、
    整行右移一列（実測：その他収益 读成 [20, 15789]，20 是注記号）。
    決算短信 没有注記列、正好两个数，取最后两个与取前两个等价，故统一用尾二。
    """
    if len(vals) >= 2:
        return [vals[-2], vals[-1]]
    if len(vals) == 1:
        warns.append(f"{kind}/{concept}: 单值行（另一列连 nil 占位都没有），置于当期列")
        return [None, vals[0]]
    return [None, None]


# ---------------------------------------------------------------- 分部

# AGC 的**报告分部数逐年变过**（FY2013 是 4 个：ガラス/電子/化学品/セラミックス・その他；
# 近年 6 个：建築ガラス/オートモーティブ/電子/化学品/ライフサイエンス/セラミックス・その他）。
# 表头在 plain 抽文里被打散（'表計上額ガラス 電子 化学品'），按表头顺序读名字不可靠；
# 但**格数是确定的**：数据行 = n 个分部 + 合計 + 調整額 + 連結計上額 → n = len(cells) - 3。
# 故按格数选 schema，再用表头文本**逐名验证**（验不过则记警告，不硬塞）。
SEG_SCHEMAS = {
    4: ["ガラス", "電子", "化学品", "セラミックス・その他"],
    5: ["建築ガラス", "オートモーティブ", "電子", "化学品", "セラミックス・その他"],
    6: ["建築ガラス", "オートモーティブ", "電子", "化学品", "ライフサイエンス",
        "セラミックス・その他"],
}
SEG_ITEMS = [
    ("外部売上高", r"^外部顧客への売上高"),
    ("セグメント間売上高", r"^セグメント間の売上高"),
    ("売上高計", r"^計$"),
    ("セグメント利益", r"^セグメント利益又は損失|^セグメント利益"),
    ("減価償却費", r"^減価償却費及び償却費"),
    ("減損損失", r"^減損損失\(非金融資産\)|^減損損失"),
    ("資本的支出", r"^資本的支出"),
]


def extract_segments(lines):
    """分部表：一行 = 6 分部 + 合計 + 調整額 + 連結計上額（最多 9 格）。
    文档里前期表、当期表各一张，按出现顺序返回 [前期, 当期]。

    两个坑：
      · 行名会换行（'セグメント利益又は損失' / '(営業利益)' / 数字独占下一行）→ 需向前拼标签；
      · 行内有 nil（'179 － 3,141 …'）→ 必须用 parse_cells 保住空格位，否则整行左移。
    """
    blocks = []
    for i, (_, ln) in enumerate(lines):
        if "外部顧客への売上高" not in norm(ln):
            continue
        block, seen = {}, set()
        pend = []          # 累积的无数字行（可能是断开的行名）
        for j in range(i, min(len(lines), i + 45)):
            raw = lines[j][1]
            cells = parse_cells(raw)
            nums = [c for c in cells if c is not None]
            label = norm(TOKEN_RE.sub(" ", raw))
            for n in NILS:
                label = label.replace(n, "")
            if not nums:
                if label:
                    pend.append(label)
                    pend[:] = pend[-3:]
                continue
            cand = "".join(pend) + label      # 行名可能整段在前几行
            for key, pat in SEG_ITEMS:
                if key in seen:
                    continue
                if (re.search(pat, label) or re.search(pat, cand)) and len(cells) >= 6:
                    block[key] = cells
                    seen.add(key)
                    break
            pend = []
        if "外部売上高" not in block:
            continue
        n = len(block["外部売上高"]) - 3          # 减去 合計/調整額/連結計上額
        schema = SEG_SCHEMAS.get(n)
        hdr = norm("".join(lines[k][1] for k in range(max(0, i - 18), i)))
        named = {"_n": n, "_schema_ok": bool(schema), "_names": schema or []}
        if schema:
            missing = [s for s in schema if s.replace("・", "") not in hdr.replace("・", "")]
            named["_hdr_missing"] = missing
            for item, cells in block.items():
                for si, sname in enumerate(schema):
                    if si < len(cells):
                        named.setdefault(item, {})[sname] = cells[si]
                # 合計/連結列（末位）另存，供勾稽
                named.setdefault(item, {})["_連結"] = cells[-1] if cells else None
                named[item]["_合計"] = cells[n] if len(cells) > n else None
        blocks.append(named)
    return blocks


def extract_file(path):
    lines = page_lines(path)
    res, warns = {}, []
    for kind in ("IS", "BS", "CF"):
        d, w = extract_section(lines, kind)
        res[kind] = d
        warns += w
    res["SEG"] = extract_segments(lines)
    return res, warns


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    files = sys.argv[1:]
    if not files:
        files = sorted(f for f in os.listdir(PDF_DIR) if f.endswith(".pdf"))
    for fn in files:
        p = fn if os.path.isabs(fn) else os.path.join(PDF_DIR, fn)
        if not os.path.exists(p):
            print(f"缺文件 {p}")
            continue
        m = re.search(r"FY(\d{4})", os.path.basename(p))
        tag = m.group(1) if m else os.path.basename(p)
        try:
            res, warns = extract_file(p)
        except Exception as exc:
            print(f"FY{tag}: 🔴 解析失败 {exc}")
            continue
        # 同一年可能既有 決算短信 又有 有価証券報告書（有報审计过、附注全）——
        # 已写入有報版则不许被短信版覆盖（文件名排序恰好让短信排在后面，会反向覆盖）。
        outp = os.path.join(OUT_DIR, f"fy{tag}.json")
        if os.path.exists(outp) and "決算短信" in os.path.basename(p):
            try:
                old = json.load(open(outp, encoding="utf-8"))
                od = old.get("data", {})
                healthy = len(od.get("IS", {})) >= 15 and len(od.get("BS", {})) >= 25
                # 只有当已存在的有報版**解析健康**时才让它压过短信。
                # FY2025 的 EDINET 版有報 CID 字体映射损坏（日文全乱码、只有数字可读），
                # 解析出来近乎空——那种情况必须回退到短信，否则等于用坏文件覆盖好数据。
                if "有価証券報告書" in old.get("src", "") and healthy:
                    print(f"FY{tag}: 跳过短信（已有健康的有報版 {old['src']}）")
                    continue
                if "有価証券報告書" in old.get("src", ""):
                    print(f"FY{tag}: 有報版解析不健康（IS={len(od.get('IS', {}))} "
                          f"BS={len(od.get('BS', {}))}），改用短信")
            except Exception:
                pass
        with open(outp, "w", encoding="utf-8") as f:
            json.dump({"year": tag, "src": os.path.basename(p), "data": res,
                       "warns": warns}, f, ensure_ascii=False, indent=1)
        n = {k: (len(v) if isinstance(v, dict) else len(v)) for k, v in res.items()}
        print(f"FY{tag}: IS={n['IS']} BS={n['BS']} CF={n['CF']} SEG块={n['SEG']} 警告{len(warns)}")
        for w in warns[:6]:
            print(f"    ⚠️ {w}")


if __name__ == "__main__":
    main()
