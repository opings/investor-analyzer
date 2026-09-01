#!/usr/bin/env python3
"""NSG(日本板硝子 5202) 日文财报提取器 —— 一手 有価証券報告書 → _extract_json/fy<YYYY>.json

管线：pypdf **layout** 模式抽文 → 页级分节 → 概念锚定（日文科目正则）→ {当期, 前期} 两列
      另抽「主要な経営指標等の推移」5 年表（SUM），供长期序列 + 跨报告互证。

与 AGC(5201) 提取器的**四处关键差异**（都实测过，照抄 AGC 会全错）：
  1) **列序相反且中途翻转**：NSG 的 IFRS 段（FY2012/3 起）是「当期在左、前期在右」；
     而 JGAAP 段（FY2011/3 及以前）是「前期在左、当期在右」——**同一家公司两个方向**。
     写死任何一种都会让半个序列整体错位一年。本库**逐节读表头**判定
     （当連結会計年度 与 前連結会計年度 谁先出现），不靠假设。
  2) **必须用 layout 模式**：plain 模式会把数字**从中间截断成两行**
     （実測 FY2012/3 非支配持分 '9,22' + 换行 + '2'）——静默丢一位数。
     layout 模式保住整格。AGC 恰好相反（AGC 的 layout 只抽得到页眉）。
  3) **注記番号写成括号形式** `売上高 (7) 552,223 577,069`：NSG 是当期在左，
     取前两个数会把 7 当成当期金额。必须**先剥 (数字)** 再取格。
     （AGC 是裸注記番号 + 当期在右，取尾二即可绕开。）
  4) **移行年 BS 有三列**：FY2012/3 有報的连结 BS 是「当期末 / 前期末 / **前期首(移行日)**」，
     三列而非两列。按「取前两格」处理正确（当期、前期），第三格丢弃。

日本财报通用坑（与 AGC 相同，不重复论证）：△/▲ 是负号；全角数字要归一；
nil「－」必须占位否则整行左移。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import warnings

warnings.filterwarnings("ignore")
import logging
logging.getLogger("pypdf").setLevel(logging.ERROR)

from pypdf import PdfReader

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
PDF_DIR = os.path.join(ROOT, "report", "NSG板硝子")
OUT_DIR = os.path.join(HERE, "_extract_json")

# ---------------------------------------------------------------- 数字 token
# 末尾负向断言：数字后紧跟日文量词时，它是**科目名的一部分**不是金额
# （'1年内返済予定の…' / '第159期' / '2025年3月31日'）。
CNT = r"(?![年月日株期回名件％%円銭ヶか])"
TOKEN_RE = re.compile(
    r"[△▲]\s*\d[\d,]*(?:\.\d+)?" + CNT
    + r"|-\s*\d[\d,]*(?:\.\d+)?" + CNT
    + r"|\d[\d,]*(?:\.\d+)?" + CNT
)
NILS = {"－", "-", "―", "—", "‐", "─"}
CELL_RE = re.compile(TOKEN_RE.pattern + r"|(?<![^\s　])[－―—‐─\-](?![^\s　])")

# 注記番号：NSG 写成 (7) / (29) 的括号形式，混在科目名与金额之间。
# 不剥掉它，「当期在左」的 NSG 取前两格会把注記号当金额。
NOTE_RE = re.compile(r"[(（]\s*\d{1,3}\s*[)）]|※\s*\d+|注\s*\d+")
# 〔外、平均臨時雇用者数〕的括号数字：5 年表里跟在従業員数后面，非独立指标
BRACKET_RE = re.compile(r"〔[^〕]*〕")

# ⚠️ 全角「－」**不能**并入本表转成 ASCII '-'：它在日文财报里是 **nil 占位符**（该期无此项），
#    转成 '-' 后既不是数字 token、又不在 nil 字符类里 → 整格被丢掉、后面的列全部左移一位。
#    実測 FY2019/3「米国連邦法人税率の変更に伴う調整額  －  △9,590」被读成当期 -9,590
#    （其实当期是 nil、-9,590 是前期），当年"税引前+税=当期利益"因此差 9,590。
#    （ASCII '-' 已单独加进 CELL_RE 的 nil 字符类兜底。）
FW = str.maketrans("０１２３４５６７８９（）：，．", "0123456789():,.")


def to_num(tok):
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


def norm(s):
    """全角→半角 + 去全部空白（用于科目名匹配）。"""
    return re.sub(r"[\s　\xa0]+", "", s.translate(FW))


def clean(line):
    """剥注記番号 + 全角归一，保留空白做分隔（用于取格）。"""
    return NOTE_RE.sub(" ", line.translate(FW).replace("\xa0", " "))


def parse_cells_typed(line):
    """按出现顺序返回 [(值, 是否带小数点)]，nil 位保留 (None, False)。

    「是否带小数点」是 JGAAP 段的关键判据：百万円金额一律**印成千分位整数**、
    構成比／百分比一律**印成一位小数**。所以「源串里有没有小数点」能精确切开两类列。
    ⚠️ 不能改用「值是否为整数」——構成比 `5.0` / `100.0` 在数值上也是整数，
    実測 経常利益行 `13,270 5.0 10,425 3.9` 会漏掉 5.0 那格。
    """
    out = []
    for m in CELL_RE.finditer(clean(line)):
        s = m.group(0)
        if s.strip() in NILS:
            out.append((None, False))
        else:
            out.append((to_num(s), "." in s))
    return out


def parse_cells(line):
    """按出现顺序返回单元格列表，nil 位保留 None（保列位）。"""
    return [v for v, _ in parse_cells_typed(line)]


# 行首的项目编号残渣：JGAAP 版报表用「Ⅰ 流動資産」「１．現金及び預金」编号，
# 数字被当作金额 token 抽走后会剩下一个孤零零的「.」——`^現金及び預金$` 就再也匹配不上
# （実測 FY2005 BS 只认出 11 行「合计」类科目，带编号的 12 行全丢）。
LEAD_JUNK = re.compile(r"^[.．、,;:・()（）Ⅰ-ⅹ①-⑳\-–—\s]+")
TAIL_JUNK = re.compile(r"[、,.．\s]+$")


PAREN_SUFFIX = re.compile(r"\([^()]{0,12}\)")
# 行名折行时括号会被**从中间截断**（'親会社の所有者に帰属する当期利益（△は損' + 换行 + '失）'），
# 拼回来的候选串带一个没闭合的左括号残尾，锚定式正则（带 $）必然失配。
PAREN_OPEN_TAIL = re.compile(r"\([^()]*$")


def label_of(line):
    """行 → 归一化科目名（去掉数字、nil、行首编号残渣与行尾注記逗号）。"""
    lb = TOKEN_RE.sub(" ", clean(line))
    for n in NILS:
        lb = lb.replace(n, " ")
    lb = norm(lb)
    return TAIL_JUNK.sub("", LEAD_JUNK.sub("", lb))


def label_key(lb):
    """概念匹配用的键：去掉括号补语（(△は損失) / (円) / (△は減少) …）。

    亏损年份的科目名会带「（△は損失）」后缀（`当期利益（△は損失）`），
    且 norm() 已把全角括号转半角——正则里写全角「（△は損失）」一条都匹配不上，
    写半角又得给每个科目都补一遍。统一在这里剥掉，概念表只写光科目名。
    実測：不剥的话 当期利益/営業利益/税引前利益 在多数亏损年整行丢失。
    """
    return TAIL_JUNK.sub("", PAREN_OPEN_TAIL.sub("", PAREN_SUFFIX.sub("", lb)))


PDFTOTEXT = shutil.which("pdftotext") or "/opt/homebrew/bin/pdftotext"

# 🚨 页码/页脚必须在抽文层就丢掉，否则会被当成**无名数字行**混进报表：
#   · 页码印成 '- 85 -' → 解析成一个 -85 的单元格、科目名为空
#     → 被"无名小计行"逻辑当成「流動資産合計」（実測 FY2020 流動資産合計 = -85）；
#     → 也会被"折行科目名"的第二遍匹配吃掉（実測 FY2013 当期利益 = -58 = 页码）。
#   · 页脚 '2020/06/29 10:18:07／19561062_日本板硝子株式会社_有価証券報告書（通常方式）'
#     里一串数字同理。
FOOTER_RE = re.compile(r"^\s*[-‐－―—]\s*\d+\s*[-‐－―—]\s*$"
                       r"|_有価証券報告書|有価証券報告書（通常方式）"
                       r"|^\s*\d+_有価証券報告書")


def page_lines(path):
    """抽文 → [(page_idx, line)]。**首选 poppler `pdftotext -layout`**，pypdf 只作兜底。

    为什么不用 pypdf：
      · **FY2001-FY2005（第135-139期）的 有報 用 pypdf 读出来是乱码**
        （CID 字体映射不被支持，'有価証券報告書' 抽成 'ɹ༗ɹ༗…'，日文全废、数字也残）。
        **同样这几份文件 poppler 能完整读出**——所以"文本层坏"其实是**读取器的问题**，
        换 poppler 就多拿回 5 个年份。（AGC 库当年把 FY2025 有報 判为"文本层损坏、
        改用決算短信"，很可能是同一个坑，值得回头用 poppler 复验。）
      · pypdf 的 plain 模式会把数字**从中间截断成两行**（FY2012 非支配持分 '9,22'+'2'）；
        layout 模式在部分年份直接抛 'unknown encoding'。poppler -layout 两个毛病都没有。
    """
    try:
        r = subprocess.run([PDFTOTEXT, "-layout", "-enc", "UTF-8", path, "-"],
                           capture_output=True, timeout=300)
        txt = r.stdout.decode("utf-8", "replace")
        if txt.strip():
            out = []
            for i, page in enumerate(txt.split("\f")):
                for ln in page.split("\n"):
                    if ln.strip() and not FOOTER_RE.search(ln):
                        out.append((i, ln))
            return out
    except Exception:
        pass
    # 兜底：poppler 不可用时退回 pypdf
    reader = PdfReader(path)
    out = []
    for i, pg in enumerate(reader.pages):
        try:
            t = pg.extract_text(extraction_mode="layout") or ""
        except Exception:
            t = ""
        if not t.strip():
            try:
                t = pg.extract_text() or ""
            except Exception:
                t = ""
        for ln in t.split("\n"):
            if ln.strip():
                out.append((i, ln))
    return out


# ---------------------------------------------------------------- 页级分节
# NSG **在 IFRS 下仍沿用日本基準的表名**「連結貸借対照表」「連結損益計算書」
# （不像多数 IFRS 公司改叫 財政状態計算書 / 純損益計算書）——按 AGC 的表名正则会一条都切不到。
#
# 🚨 表名必须按**行首结构标记**匹配（`①【連結損益計算書】` 这种带序号/方括号的标题行），
#    不能"页内任意位置出现表名即算"：MD&A（財政状態及び経営成績の分析）正文里
#    大量提到「連結損益計算書」，按页内包含判定会把十几页 MD&A 拉进报表节。
#    并且**标题必须到此为止**（其后只允许 `】` 或 `及び…】`）：
#    附注里的「(連結貸借対照表計上額が取得原価を超えるもの)」以「(連結貸借対照表」开头，
#    不收尾就会把有価証券/退職給付/税効果/セグメント 等整段附注页认成 BS（実測 FY2006 多认 8 页）。
TITLE_LINE = re.compile(r"^[①-⑨(（]?\d?[)）]?【?(?P<t>連結貸借対照表|連結財政状態計算書"
                        r"|連結損益計算書|連結純損益計算書|連結包括利益計算書"
                        r"|連結持分変動計算書|連結株主資本等変動計算書"
                        r"|連結キャッシュ・?フロー計算書)(?:】|及び[^】]*】|)$")
TITLE_KIND = {"連結貸借対照表": "BS", "連結財政状態計算書": "BS",
              "連結損益計算書": "IS", "連結純損益計算書": "IS",
              "連結包括利益計算書": "CI",
              "連結持分変動計算書": "EQ", "連結株主資本等変動計算書": "EQ",
              "連結キャッシュフロー計算書": "CF", "連結キャッシュ・フロー計算書": "CF"}
# 単体（提出会社のみ）报表 —— 必须排除，否则母公司数会盖掉合并数
SOLO_RE = re.compile(r"【財務諸表等】|主な資産及び負債の内容")
# 注記事項（連結貸借対照表関係）等：同名科目在附注里重复出现，会污染报表节
# ⚠️ 「注記事項」必须带方括号匹配：JGAAP 版报表的**列头**就写着「区分 注記/事項 金額…」，
#    normalize 后拼成「注記事項」——裸串匹配会把 CF 整张表当成附注页毙掉（実測 FY2006 CF 全丢）。
NOTE_SEC_RE = re.compile(r"連結貸借対照表関係|連結損益計算書関係|連結キャッシュ・?フロー計算書関係"
                         r"|【注記事項】|連結財務諸表注記|【?連結附属明細表】?")
# 🚨 IFRS 移行年的有報里同时印着**日本基準的「要約」连结报表**做准则调节
#    （FY2012/3 P16「②要約連結損益計算書及び要約連結包括利益計算書」）。
#    它长得像损益表却是 JGAAP 结构（営業外収益/経常利益/特別損益/少数株主利益）、
#    列序也是前期在左——误抓会让整年 IFRS 数被 JGAAP 数覆盖、且把列序判反。
JGAAP_MIX_RE = re.compile(r"要約連結|日本基準による|米国会計基準")
ANCHOR = {"BS": ["資産合計"], "IS": ["売上高"], "CF": ["営業活動によるキャッシュ"]}


def page_kinds(lines):
    """{page_idx: kind}；行首标题定归属，无标题页顺延（附注 / 単体 / 要約(JGAAP) 页切断）。"""
    by_page = {}
    for p, ln in lines:
        by_page.setdefault(p, []).append(ln)
    kinds, cur, since = {}, None, 0
    for p in sorted(by_page):
        raw = "".join(by_page[p])
        txt = norm(raw)
        if SOLO_RE.search(txt) or NOTE_SEC_RE.search(txt) or JGAAP_MIX_RE.search(txt):
            kinds[p] = None
            cur, since = None, 0
            continue
        hit = None
        for ln in by_page[p]:
            m = TITLE_LINE.match(norm(ln))
            if m:
                hit = TITLE_KIND.get(m.group("t").replace("・", ""))
                if hit is None:
                    hit = TITLE_KIND.get(m.group("t"))
                break
        if hit:
            cur, since = hit, 0
        else:
            since += 1
            if since > 3:
                cur = None
        kinds[p] = cur
    return kinds


def col_order(raw_lines):
    """判定该节的列序：'cur_first'（当期列在左）或 'prev_first'（前期列在左）。

    NSG 在 IFRS 移行（FY2012/3）时把列序**翻转**了，所以不能写死，必须读表头。

    ⚠️ 判据是表头词的**横向位置（x）**，不是它们在文本流里的先后。
    `-layout` 抽文会把同一表头的两个词拆到不同行、且顺序与视觉相反——
    実測 FY2022/3 有報：'前連結会計年度' 排在上一行、'当連結会計年度' 排在下一行，
    但 x 位置上 当(66) 在 前(86) 左边、数据也确实是当期在左。
    按"谁先出现"判会把该年整表读反一年。
    """
    x_cur = x_prev = None
    for ln in raw_lines:
        s = ln.translate(FW)
        if x_cur is None:
            i = s.find("当連結会計年度")
            if i >= 0:
                x_cur = i
        if x_prev is None:
            i = s.find("前連結会計年度")
            if i >= 0:
                x_prev = i
        if x_cur is not None and x_prev is not None:
            break
    if x_cur is None or x_prev is None:
        return None
    return "cur_first" if x_cur < x_prev else "prev_first"


def slice_section(lines, kind):
    """切出该表的页，并**只用锚定行所在页的表头**判列序。

    ⚠️ 列序必须在**锚定页**上判：目录页 / 経理の状況导语页也会被归到本节，
    它们里出现的「前連結会計年度」若排在前面，会把整节误判成 prev_first
    （実測 FY2012 IS 因此翻转、整表错位一年）。
    """
    kinds = page_kinds(lines)
    seg = [(p, ln) for p, ln in lines if kinds.get(p) == kind]
    if not seg:
        return [], None
    joined = "".join(norm(ln) for _, ln in seg)
    if not any(a in joined for a in ANCHOR[kind]):
        return [], None
    # 锚定页 = 含 ANCHOR 科目**且该行带数字**的第一页
    anchor_pg = None
    for p, ln in seg:
        lb = label_of(ln)
        if any(re.match("^" + a, lb) for a in ANCHOR[kind]) and \
                any(c is not None for c in parse_cells(ln)):
            anchor_pg = p
            break
    all_raw = [ln for _, ln in seg]
    if anchor_pg is None:
        return seg, col_order(all_raw)
    o = col_order([ln for p, ln in seg if p == anchor_pg])
    if o is None:  # 表头在上一页（跨页表）
        o = col_order([ln for p, ln in seg if p == anchor_pg - 1]) or col_order(all_raw)
    return seg, o


# ---------------------------------------------------------------- 概念表（IFRS 段）
# NSG 的 IFRS 损益表有两个自家特色行：
#   「個別開示項目」(exceptional items·英式列报) 夹在 個別開示項目前営業利益 与 営業利益 之间；
#   持分法投資利益 排在营业利益**之下**（AGC 排在之上、并进营业利益）——跨公司比营业利润率须注意。
IS_IFRS = [
    ("売上高", r"^売上高$|^売上収益$"),
    ("売上原価", r"^売上原価$"),
    ("売上総利益", r"^売上総利益$"),
    ("その他の収益", r"^その他の収益$"),
    ("販売費", r"^販売費$"),
    ("管理費", r"^管理費$"),
    ("販売費及び一般管理費", r"^販売費及び一般管理費$"),
    ("その他の費用", r"^その他の費用$"),
    ("個別開示項目前営業利益", r"^個別開示項目前営業利益"),
    # 「個別開示項目」(exceptional items) 是 NSG 的英式列报特色：重组/减值/处置等
    # 常年从这里走。FY2022/3 起由**单行拆成收益/費用两行**，且「営業利益」改名
    # 「個別開示項目後営業利益」——两套写法都得认，否则近年营业利润整列丢。
    ("個別開示項目", r"^個別開示項目$|^個別開示項目\("),
    ("個別開示項目収益", r"^個別開示項目収益"),
    ("個別開示項目費用", r"^個別開示項目費用"),
    ("営業利益", r"^営業(利益|損失)$|^営業利益又は損失|^個別開示項目後営業(利益|損失)$"),
    ("金融収益", r"^金融収益$"),
    ("金融費用", r"^金融費用$"),
    ("持分法適用会社金融債権減損", r"^持分法適用会社に対する金融債権の減損損失"),
    ("持分法による投資損益", r"^持分法による投資(利益|損益|損失)"),
    ("持分法投資その他損益", r"^持分法投資に関するその他の(利益|損益)"),
    # 🚨 亏损年份 NSG 直接把科目名改成「損失」（税引前**損失** / 当期**損失** /
    #    親会社の所有者に帰属する当期**損失**），不是加「（△は損失）」后缀。
    #    只写「利益」会在**恰恰是亏损的那些年**整行丢失——而 NSG 二十年里亏损年占一半，
    #    等于把最该看的年份挖空（実測 FY2013/FY2014/FY2021 三年税前与净利全丢）。
    ("税引前利益", r"^税引前(利益|損失)|^税引前当期(利益|損失)"),
    ("法人所得税", r"^法人所得税$|^法人所得税費用$"),
    # FY2018/3 独有的一次性税项：美国减税与就业法案(TCJA)导致递延税重估，
    # 单列一行 △9,590。漏掉它「税引前+税=当期利益」当年必差 9,590。
    ("米国連邦法人税率変更調整", r"^米国連邦法人税率の変更に伴う調整額"),
    ("当期利益", r"^当期(純)?(利益|損失)$"),
    ("非支配持分帰属当期利益", r"^非支配持分に帰属する当期(純)?(利益|損失)"),
    ("親会社所有者帰属当期利益", r"^親会社の所有者に帰属する当期(純)?(利益|損失)$"),
    ("基本的1株当たり当期利益", r"^基本的1株当たり当期(純)?(利益|損失)"),
    ("希薄化後1株当たり当期利益", r"^希薄化後1株当たり当期(純)?(利益|損失)"),
]

BS_IFRS = [
    ("のれん", r"^のれん$"),
    ("無形資産", r"^無形資産$"),
    ("有形固定資産", r"^有形固定資産$"),
    ("投資不動産", r"^投資不動産$"),
    ("持分法投資", r"^持分法で会計処理され(ている|る)投資$"),
    ("使用権資産", r"^使用権資産$"),
    ("繰延税金資産", r"^繰延税金資産$"),
    ("非流動資産合計", r"^非流動資産合計$"),
    ("棚卸資産", r"^棚卸資産$"),
    ("売上債権及びその他の債権", r"^売上債権及びその他の債権$"),
    ("現金及び現金同等物", r"^現金及び現金同等物$"),
    ("売却目的で保有する資産", r"^売却目的で保有する資産$"),
    ("流動資産合計", r"^流動資産合計$"),
    ("資産合計", r"^資産合計$"),
    ("社債及び借入金_流動", r"^社債及び借入金$"),
    ("仕入債務及びその他の債務", r"^仕入債務及びその他の債務$"),
    ("引当金_流動", r"^引当金$"),
    ("流動負債合計", r"^流動負債合計$"),
    ("社債及び借入金_非流動", r"^社債及び借入金$"),
    ("退職給付引当金", r"^退職給付引当金$|^退職給付に係る負債$"),
    ("繰延税金負債", r"^繰延税金負債$"),
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

CF_IFRS = [
    # 🚨 「営業活動による現金生成額」= 付息付税**前**的 cash generated from operations，
    #    与下面的「営業活動によるキャッシュ・フロー」（净额）**不是一回事**，两者差一整块
    #    利息+税（実測 FY2020：43,873 vs 30,444）。把前者当经营现金流会把经营质量拔高一档。
    ("営業活動による現金生成額", r"^営業活動による現金生成額"),
    ("利息の支払額", r"^利息の支払額$"),
    ("利息の受取額", r"^利息の受取額$"),
    ("法人所得税の支払額", r"^法人所得税の支払額$|^法人税等の支払額$"),
    ("営業活動によるキャッシュフロー", r"^営業活動によるキャッシュ・?フロー$"),
    ("投資活動によるキャッシュフロー", r"^投資活動によるキャッシュ・?フロー$"),
    ("財務活動によるキャッシュフロー", r"^財務活動によるキャッシュ・?フロー$"),
    # capex 被拆成有形/无形两行，只取一行会把资本开支系统性低估
    ("有形固定資産取得", r"^有形固定資産の取得による支出$|^有形固定資産及び無形資産の取得による支出$"),
    ("無形資産取得", r"^無形資産の取得による支出$|^無形固定資産の取得による支出$"),
    ("有形固定資産売却収入", r"^有形固定資産の売却による収入$"),
    ("配当金の支払額", r"^親会社の所有者への配当金の支払額$|^配当金の支払額$"),
    ("自己株式の取得", r"^自己株式の取得による支出$"),
    ("社債発行及び借入", r"^社債発行及び借入れ?による収入$"),
    ("社債償還及び返済", r"^社債償還及び借入金返済による支出$"),
    ("現金及び現金同等物の増減額", r"^現金及び現金同等物の(純)?増減額"),
    ("現金及び現金同等物の期首残高", r"^現金及び現金同等物の期首残高$"),
    ("換算差額", r"^現金及び現金同等物に係る換算差額$|^為替変動による現金及び現金同等物への影響額$"),
    ("超インフレの調整", r"^超インフレの調整"),
    # 只在个别年份出现、夹在「換算差額」与「期末残高」之间的一行（FY2013/3 △149）。
    # 漏掉它，那一年「期首+増減額+換算差額=期末」就差 149，看着像小舍入其实是缺科目。
    # 行名被折成三行、**数字夹在中间**（'…への振替に' / 数字 / '伴う現金及び…増減額'），
    # 所以正则只能锚定到数字行**之前**那半截，不能写全名。
    ("売却目的保有資産への振替に伴う現金増減", r"^売却目的で保有する資産(への振替|に含まれる現金)"),
    ("現金及び現金同等物の期末残高", r"^現金及び現金同等物の期末残高$"),
]

# ---------------------------------------------------------------- 概念表（JGAAP 段·FY2011/3 及以前）
# JGAAP 版报表**在金额列之间夹着「構成比／百分比（％）」列**：
#   '流動資産合計   167,724 39.3   288,732 48.4' → [前期額, 前期%, 当期額, 当期%]
# 判别法：百万円金额一律整数，構成比一律带小数 → **丢掉带小数的格**即可还原成纯金额列。
# 另有多层小计行（'減価償却累計額 67,857 39,439 69,198 38,378'、営業外収益明细+小计），
# 丢掉小数后仍是 4 格；本表**只收单层行**，不收那些行（避免静默取错格）。
IS_JGAAP = [
    ("売上高", r"^売上高$"),
    ("売上原価", r"^売上原価$"),
    ("売上総利益", r"^売上総利益$|^売上総損失"),
    ("販売費及び一般管理費", r"^販売費及び一般管理費$"),
    # 近年 JGAAP 版把盈亏两种情形写在同一行名里：「営業利益又は営業損失（△）」
    # 「経常利益又は経常損失（△）」「当期純利益又は当期純損失（△）」——
    # 只写 `^営業(利益|損失)$` 会在 FY2009-FY2011 这几年整行丢失。
    ("営業利益", r"^営業(利益|損失)(又は営業(損失|利益))?$"),
    ("経常利益", r"^経常(利益|損失)(又は経常(損失|利益))?$"),
    ("税金等調整前当期純利益", r"^税金等調整前当期純(利益|損失)"),
    ("少数株主損益調整前当期純利益", r"^少数株主損益調整前当期純(利益|損失)"),
    ("少数株主利益", r"^少数株主(利益|損失)$"),
    ("当期純利益", r"^当期純(利益|損失)(又は当期純(損失|利益))?(金額)?$"),
]
BS_JGAAP = [
    ("現金及び預金", r"^現金及び預金$"),
    ("受取手形及び売掛金", r"^受取手形及び売掛金$"),
    ("棚卸資産", r"^棚卸資産$"),
    ("流動資産合計", r"^流動資産合計$"),
    ("有形固定資産合計", r"^有形固定資産合計$"),
    ("無形固定資産", r"^無形固定資産(合計)?$"),
    ("投資その他の資産合計", r"^投資その他の資産合計$"),
    ("固定資産合計", r"^固定資産合計$"),
    ("資産合計", r"^資産合計$"),
    ("支払手形及び買掛金", r"^支払手形及び買掛金$"),
    ("短期借入金", r"^短期借入金$"),
    ("一年内償還予定社債", r"^一年内償還予定の社債$|^1年内償還予定の社債$"),
    ("流動負債合計", r"^流動負債合計$"),
    ("社債", r"^社債$"),
    ("長期借入金", r"^長期借入金$"),
    ("退職給付引当金", r"^退職給付引当金$"),
    ("固定負債合計", r"^固定負債合計$"),
    ("負債合計", r"^負債合計$"),
    ("少数株主持分", r"^少数株主持分$"),
    ("資本金", r"^資本金$"),
    ("資本剰余金", r"^資本剰余金$"),
    ("利益剰余金", r"^利益剰余金$"),
    ("純資産合計", r"^純資産合計$|^資本合計$"),
]
CF_JGAAP = [
    ("営業活動によるキャッシュフロー", r"^営業活動によるキャッシュ・?フロー$"),
    ("投資活動によるキャッシュフロー", r"^投資活動によるキャッシュ・?フロー$"),
    ("財務活動によるキャッシュフロー", r"^財務活動によるキャッシュ・?フロー$"),
    ("capex", r"^有形固定資産の取得による支出$"),
    ("現金及び現金同等物の期末残高", r"^現金及び現金同等物の期末残高$"),
    ("現金及び現金同等物の期首残高", r"^現金及び現金同等物の期首残高$"),
]

CONCEPTS = {
    "IFRS": {"IS": IS_IFRS, "BS": BS_IFRS, "CF": CF_IFRS},
    "JGAAP": {"IS": IS_JGAAP, "BS": BS_JGAAP, "CF": CF_JGAAP},
}
# BS 里「社債及び借入金」「引当金」在流動/非流動各出现一次，需按出现顺序区分
DUP_ORDER = {"社債及び借入金_流動": 0, "社債及び借入金_非流動": 1,
             "引当金_流動": 0}


def pick2(cells, order):
    """按列序取 (当期, 前期)。

    cur_first（NSG 的 IFRS 段）→ 前两格。移行年 BS 是三列
    （当期末/前期末/前期首(移行日)），取前两格正确、第三格丢弃。
    prev_first（JGAAP 段）→ **当期 = 末格、前期 = 倒数第二格**（不是首格）：
    JGAAP 行首常混进解析不掉的杂质（跨行的注記番号「※１、\\n６」、项目序号），
    从**右端**取两格能把杂质挡在左边；从左端取会把注記号当成前期金额。
    """
    vals = cells
    if not vals:
        return [None, None]
    if order == "prev_first":
        return [vals[-1], vals[-2] if len(vals) > 1 else None]
    return [vals[0], vals[1] if len(vals) > 1 else None]


# 🚨 JGAAP 损益表的**亏损行印的是无符号正数**，符号藏在**科目名**里
#    （FY2003/3：'当期純損失  2,278  0.8  3,152  1.1' —— 2,278 其实是 −2,278）。
#    而且盈亏两种情形**各占一行**、另一列填 nil：
#        経常利益   1,074  0.4    －    －
#        経常損失     －     －   1,572  0.6
#    照直读会得到「FY2003 経常利益 = +1,572」——**把亏损读成等额盈利，误差是两倍**。
#    做法：把成对的 利益/損失 行按列合并，来自「損失」行的正值取负；
#    「…利益又は…損失（△）」这种合并写法本身已带 △，不再取负。
JG_PL_PAIRS = [
    ("売上総利益", r"^売上総(利益|損失)"),
    ("営業利益", r"^営業(利益|損失)"),
    ("経常利益", r"^経常(利益|損失)"),
    ("税金等調整前当期純利益", r"^税金等調整前当期純(利益|損失)"),
    ("当期純利益", r"^当期純(利益|損失)"),
]


def merge_profit_loss(rows, order, out):
    for concept, pat in JG_PL_PAIRS:
        rx = re.compile(pat)
        merged = [None, None]
        for lb, cells, _i in rows:
            k = label_key(lb)
            if not rx.search(k):
                continue
            neg = "損失" in k and "又は" not in k
            vals = pick2(cells, order)
            for j in (0, 1):
                v = vals[j]
                if v is None or merged[j] is not None:
                    continue
                merged[j] = -v if (neg and v > 0) else v
        if merged[0] is not None or merged[1] is not None:
            out[concept] = merged


def detect_std(lines):
    """判准则：IFRS 段的连结 BS 有「非流動資産」，JGAAP 段有「固定資産合計」。"""
    t = "".join(norm(ln) for _, ln in lines)
    if "非流動資産合計" in t or "親会社の所有者に帰属する持分合計" in t:
        return "IFRS"
    return "JGAAP"


def extract_section(lines, kind, std):
    seg, order = slice_section(lines, kind)
    if not seg:
        return {}, [f"{kind}: 未找到分节"], None
    if order is None:
        order = "prev_first" if std == "JGAAP" else "cur_first"
    # rows = 带数字的行；plain = 纯文字行（可能是被折行的科目名上半截）
    rows, plain = [], {}
    for i, (_, ln) in enumerate(seg):
        typed = parse_cells_typed(ln)
        if std == "JGAAP":
            typed = [(v, d) for v, d in typed if not d]   # 丢掉構成比/百分比列
        cells = [v for v, _ in typed]
        lb = label_of(ln)
        if any(c is not None for c in cells):
            rows.append((lb, cells, i))
        elif lb:
            plain[i] = lb
    out, warns, used = {}, [], set()
    compiled = [(c, re.compile(p)) for c, p in CONCEPTS[std][kind]]

    def take(concept, ri):
        used.add(ri)
        out[concept] = pick2(rows[ri][1], order)

    # 第 1 遍：行自身标签
    for concept, rx in compiled:
        hits = [ri for ri, (lb, _c, _i) in enumerate(rows)
                if rx.search(label_key(lb)) and ri not in used]
        if not hits:
            continue
        idx = DUP_ORDER.get(concept, 0)
        pick = hits[idx] if idx < len(hits) else hits[0]
        # 同名科目出现多次、且**靠前那次当期为空**时，改用第一个当期有值的那次。
        # 実測 FY2007/3（会社法「純資産の部」过渡年）：同一张 BS 上并列印着旧的
        # 「資本の部」（只有前期数、当期全是 nil）和新的「純資産の部」（只有当期数），
        # 取第一个命中会拿到当期为空的旧表 → 純資産合計 整年为空。
        if pick2(rows[pick][1], order)[0] is None:
            alt = next((h for h in hits if pick2(rows[h][1], order)[0] is not None), None)
            if alt is not None:
                pick = alt
        take(concept, pick)
    # 第 2 遍：科目名被**折行**（数字行只剩后半截）→ 向前拼最近的纯文字行。
    # 実測 FY2006 P46：'税金等調整前当期純利' 独占一行、'益 11,424 11,535' 是下一行。
    for ri, (lb, _c, i) in enumerate(rows):
        if ri in used or any(rx.search(label_key(lb)) for _, rx in compiled):
            continue
        for k in (1, 2, 3):
            prev = "".join(plain.get(i - j, "") for j in range(k, 0, -1))
            if not prev:
                continue
            cand = label_key(prev + lb)
            hit = next((c for c, rx in compiled if c not in out and rx.search(cand)), None)
            if hit:
                take(hit, ri)
                break
    # 第 2.5 遍（仅 JGAAP 损益表）：**利益/損失 双行合并 + 符号还原**。
    if kind == "IS" and std == "JGAAP":
        merge_profit_loss(rows, order, out)
    # 第 3 遍（仅 IFRS BS）：**无名小计行**。
    # 🚨 NSG 的 IFRS 连结 BS 把「非流動資産合計/流動資産合計/流動負債合計/非流動負債合計」
    #    印成**没有科目名的裸数字行**（実測 FY2020：'541,108  516,288' 上面只有分块标题
    #    「非流動資産」）。按科目名找永远找不到 → 这四行会整列为空，
    #    "流動+非流動=資産合計" 之类勾稽全年全崩（差额恰等于合计本身）。
    #    做法：给每个裸数字行归到**最近的分块标题**，同一标题下取**最后一个**
    #    （流動資産块有两个小计：不含/含「売却目的で保有する資産」，合计是后者）。
    if kind == "BS" and std == "IFRS":
        blocks = {"非流動資産": "非流動資産合計", "流動資産": "流動資産合計",
                  "流動負債": "流動負債合計", "非流動負債": "非流動負債合計"}
        # 分块标题是**不带数字的纯文字行**，故必须把 rows 与 plain 按原始行号合并回放
        seq = [(i, lb, cells) for lb, cells, i in rows] + \
              [(i, lb, None) for i, lb in plain.items()]
        # 遇到大计行/资本段就**清空归属**，否则资本段里的无名小计行会顺延覆盖
        # 「非流動負債合計」（実測 FY2020 非流動負債合計被写成资本段的数、负债侧少 54 万百万円）
        resets = {"資産合計", "負債合計", "負債及び資本合計", "資本", "資本合計",
                  "親会社の所有者に帰属する持分", "親会社の所有者に帰属する持分合計"}
        cur_block = None
        for _i, lb, cells in sorted(seq):
            if lb in resets:
                cur_block = None
            if lb in blocks:
                cur_block = blocks[lb]
            elif cells is not None and lb == "" and cur_block \
                    and sum(c is not None for c in cells) >= 2:
                # ≥2 个数字才可能是小计（当期+前期）；单数字的无名行是页码/断行残片
                out[cur_block] = pick2(cells, order)     # 覆盖 → 保留该块最后一个小计
    return out, warns, order


# ---------------------------------------------------------------- 主要な経営指標等の推移（5 年表）
# 每份 有報 都印一张 5 年表。26 份报告 → 每个年份被 1~5 份报告独立印过，
# 是**跨报告互证**的天然素材（也是 JGAAP 段唯一的结构化长期序列来源）。
# ⚠️ 正则一律按 **norm() 之后**（全角括号已转半角、空白已去）写：
#    写成「（百万円）」会一条都匹配不上（実測：SUM 只抓到没有单位后缀的那几行）。
#    行名常被折成 2-3 行且**数字行夹在中间**（'親会社の所有者に帰属する当期利益' /
#    '（百万円） △49,838 …' / '（△は損失）'），故匹配对象是「前面纯文字行 + 本行残名」。
SUM_ITEMS = [
    ("売上高", r"^売上高|^売上収益"),
    ("経常損益", r"^経常(損益|利益)"),
    ("税引前損益", r"^税引前(利益|損益|当期利益)"),
    ("当期損益", r"^親会社の所有者に帰属する当期利益|^当期(純)?(利益|損益)"),
    ("包括利益", r"^親会社の所有者に帰属する当期包括|^包括利益"),
    ("純資産額", r"^親会社の所有者に帰属する持分|^純資産額"),
    ("総資産額", r"^総資産額"),
    ("1株当たり純資産", r"^1株当たり親会社所有者帰属持分|^1株当たり純資産額"),
    # 早年写「1株当たり当期純**損益**」（不是「利益」）——只写利益会让 FY2001/3 及以前整行丢失
    ("1株当たり当期損益", r"^親会社の所有者に帰属する基本的1株当たり|^1株当たり当期純(利益|損益|損失)"),
    ("希薄化後1株当たり当期損益", r"^親会社の所有者に帰属する希薄化後|^潜在株式調整後1株当たり"),
    ("自己資本比率", r"^親会社所有者帰属持分比率|^自己資本比率"),
    ("自己資本利益率", r"^親会社所有者帰属持分当期利益率|^自己資本利益率"),
    ("株価収益率", r"^株価収益率"),
    ("営業CF", r"^営業活動によるキャッシュ"),
    ("投資CF", r"^投資活動によるキャッシュ"),
    ("財務CF", r"^財務活動によるキャッシュ"),
    ("現金期末残高", r"^現金及び現金同等物の期末残高|^現金及び現金同等物"),
    ("従業員数", r"^従業員数"),
]


def extract_summary(lines):
    """抽 (1)連結経営指標等 的 5 年表。返回 {'cols': [...], 'rows': {item: [...]}}。

    两个必须挡住的坑：
      · (2)提出会社の経営指標等 是**単体**表（母公司口径），紧跟在后面且行名几乎一样，
        混进来会让 売上高 之类直接掉一个量级 → 见到该标题立即停。
      · 従業員数 行后面跟「〔外、平均臨時雇用者数〕」，括号里的数字不是新指标 → 先剥 〔〕。
    """
    # 定位表所在页
    pages = sorted({p for p, ln in lines if "主要な経営指標等の推移" in norm(ln)})
    if not pages:
        return None
    body = [(p, ln) for p, ln in lines if p in range(pages[0], pages[0] + 3)]
    # 截到「提出会社の経営指標等」为止
    cut = len(body)
    for i, (_, ln) in enumerate(body):
        if "提出会社の経営指標等" in norm(ln):
            cut = i
            break
    body = body[:cut]
    if not body:
        return None
    # ---- 列头 ----
    # 🚨 表头 token 必须按**横向位置 x 排序**，不能按文本流先后。
    #    実測 FY2013/3（IFRS 移行年）的 8 列表头被 poppler 拆成两行且顺序颠倒：
    #      第一行 = '第145期 第146期 移行日 第145期 第146期 第147期'
    #      第二行 = '回次 第143期 第144期'
    #    照文本顺序读会得到 145,146,移行日,145,146,147,143,144 —— 与数据列完全对不上。
    #    按 x 排序则还原成 143,144,145,146,移行日,145,146,147（与数据格一一对应）。
    # 表头扫描区间 = 「(1)連結経営指標等」标题行 → 第一条数据行（売上高）之间。
    # 起点必须卡在标题行上：同一页上方常有【表紙】「第140期（自 平成17年…）」之类的
    # 期号，x 位置很靠左，混进来会在列序最前面**多插一列**、导致整表列数与数据格数不符
    # → 该报告所有行被判定"列数不符"整体弃用（実測 FY2006/FY2007 两年因此全空）。
    hdr_start = 0
    for i, (_, ln) in enumerate(body):
        if re.search(r"連結経営指標等|主要な経営指標等の推移", norm(ln)):
            hdr_start = i
    hdr_end = len(body)
    for i, (_, ln) in enumerate(body):
        if i > hdr_start and re.match(r"^売上高|^売上収益", label_of(ln)) and \
                any(c is not None for c in parse_cells(ln)):
            hdr_end = i
            break
    marks, stds = [], []
    for _, ln in body[hdr_start:hdr_end]:
        s = ln.translate(FW).replace("\xa0", " ")
        for m in re.finditer(r"第\s*(\d+)\s*期|移行日", s):
            marks.append((m.start(), m.group(1) if m.group(1) else "移行日"))
        for m in re.finditer(r"日本基準|ＩＦＲＳ|IFRS|国際会計基準", s):
            stds.append((m.start(), "JGAAP" if m.group(0) == "日本基準" else "IFRS"))
    marks.sort(key=lambda t: t[0])
    stds.sort(key=lambda t: t[0])
    cols = []
    for x, k in marks:
        # 该列的准则 = x 最接近的那个准则标记（同一列上下对齐）；没有标记则留空
        std = min(stds, key=lambda t: abs(t[0] - x))[1] if stds else None
        cols.append({"期": k, "std": std})
    # ---- 数据行 ----
    # 行名常被折成 2-4 行、且数字行夹在中间。做法：把「上一条数据行之后的纯文字行」
    # 按**由近及远**逐段拼接（k=1,2,3,4），每次都用**锚定**正则试匹配。
    # 🚨 不能改用非锚定匹配图省事：pend 里必然混着上一行行名的尾巴
    #    （'…に帰属する当期利益（△は損失）（百万円）' + '包括利益又は親会社の所'），
    #    非锚定会让「当期損益」把「包括利益」那一行抢走 —— 実測 FY2013/FY2014 报告里
    #    当期損益被写成包括利益的数、包括利益被写成純資産額的数，整段串行。
    # 先把 body 拆成 (是否数据行, 标签, 单元格) 序列，**因为行名可能往后折**：
    #   実測第135期（最早那份）5 年表：
    #       '営業活動による        －  －  －  16,627  26,626'   ← 数据在这一行
    #       ' キャッシュ・フロー（百万円）'                        ← 行名的下半截在**后面**
    #   只往前拼（pend）永远拼不出「営業活動によるキャッシュ・フロー」，三条 CF 行整段丢失，
    #   进而让 FY2000/3 的回溯校验少一条可对的指标。故必须**前后都拼**。
    # 单位标记（百万円/円/％/倍/人）常**夹在行名中间**：
    #   '親会社の所有者に帰属する基本的１'
    #   '                    （円）   △551.75  62.04 …'   ← 数据行自身的"行名"只是「（円）」
    #   '株当たり当期利益（△は損失）'
    # 拼出来是「…基本的1」+「円)」+「株当たり当期利益」，中间那截单位把行名劈成两半、
    # 锚定正则永远对不上。先把单位标记剥掉，再前后拼，行名才能复原成连续串。
    UNIT = re.compile(r"[(（]?\s*(百万円|千円|円|％|%|倍|人|株)\s*[)）]?")
    seq = []
    for _, ln in body:
        n = norm(ln)
        if n.startswith("回次") or n.startswith("決算年月"):
            continue
        cells = parse_cells(BRACKET_RE.sub(" ", ln))
        seq.append((any(c is not None for c in cells),
                    UNIT.sub("", label_of(ln)), cells))
    rows = {}
    for i, (isdata, lb, cells) in enumerate(seq):
        if not isdata:
            continue
        back, fwd = [], []
        for j in range(i - 1, max(-1, i - 5), -1):     # 向前收纯文字行（由近及远）
            if seq[j][0]:
                break
            if seq[j][1]:
                back.insert(0, seq[j][1])
        for j in range(i + 1, min(len(seq), i + 5)):   # 向后收纯文字行
            if seq[j][0]:
                break
            if seq[j][1]:
                fwd.append(seq[j][1])
        # 🚨 候选顺序至关重要：**先往前拼，再自身，最后才往后拼**。
        #    往后拼有个陷阱——数据行下面那条纯文字行**往往是下一行的行名**，不是本行的续行。
        #    実測：経常利益行的下一条纯文字行是「税引前利益（△は損失）」，若先试往后拼，
        #    経常損益的数字会被登记成税引前損益（FY2010-FY2012 三年当期損益被写成経常/税前数）。
        #    往前拼则安全：前面那条纯文字行要么属于本行，要么是已被消费掉的上一行残尾。
        cands = [label_key("".join(back[-k:]) + lb) for k in range(1, len(back) + 1)]
        cands.append(label_key(lb))
        cands += [label_key(lb + "".join(fwd[:k])) for k in range(1, len(fwd) + 1)]
        # 行名被劈成「前半 + 数据行 + 后半」三段时（单位标记夹在中间），须前后一起拼才能复原
        cands += [label_key("".join(back[-b:]) + lb + "".join(fwd[:f]))
                  for b in range(1, len(back) + 1) for f in range(1, len(fwd) + 1)]
        hit = None
        for cand in cands:                       # 自身 → 往后拼 → 往前拼
            for key, pat in SUM_ITEMS:
                if key not in rows and re.search(pat, cand):
                    hit = key
                    break
            if hit:
                break
        if hit:
            rows[hit] = cells
    return {"kihon": cols, "rows": rows}


# ---------------------------------------------------------------- 分部
# NSG 报告分部：建築用ガラス / 自動車用ガラス / 高機能ガラス（+ その他 / 調整額）。
# JGAAP 段（事業の種類別セグメント情報）写「外部顧客に対する売上高」，
# IFRS 段写「外部顧客への売上高」——两种都要认，否则 FY2011/3 及以前分部整段丢。
SEG_HEAD_RE = re.compile(r"外部顧客への売上高|外部顧客に対する売上高|^外部売上高")
SEG_ITEMS = [
    ("外部売上高", r"^外部顧客への売上高|^外部顧客に対する売上高|^外部売上高|^売上高$"),
    ("セグメント間売上高", r"^セグメント間の(内部)?売上高|^部売上高又は振替"),
    ("売上高計", r"^計$|^合計$"),
    ("セグメント利益", r"^セグメント(利益|損益)|^営業利益"),
    ("減価償却費", r"^減価償却費"),
    ("減損損失", r"^減損損失"),
    ("資本的支出", r"^資本的支出|^設備投資額"),
    ("セグメント資産", r"^セグメント資産|^資産$"),
]


def extract_segments(lines):
    blocks = []
    for i, (_, ln) in enumerate(lines):
        if not SEG_HEAD_RE.search(norm(ln)):
            continue
        block, seen, pend = {}, set(), []
        for j in range(i, min(len(lines), i + 40)):
            raw = lines[j][1]
            cells = parse_cells(raw)
            lb = label_of(raw)
            if not any(c is not None for c in cells):
                if lb:
                    pend.append(lb)
                    pend[:] = pend[-3:]
                continue
            cand = "".join(pend) + lb
            for key, pat in SEG_ITEMS:
                if key in seen:
                    continue
                if (re.search(pat, lb) or re.search(pat, cand)) and len(cells) >= 4:
                    block[key] = cells
                    seen.add(key)
                    break
            pend = []
        if "外部売上高" in block:
            hdr = norm("".join(lines[k][1] for k in range(max(0, i - 20), i)))
            blocks.append({"cells": block, "_hdr": hdr[-400:]})
    return blocks


def extract_file(path):
    lines = page_lines(path)
    std = detect_std(lines)
    res, warns, orders = {}, [], {}
    for kind in ("IS", "BS", "CF"):
        d, w, o = extract_section(lines, kind, std)
        res[kind] = d
        orders[kind] = o
        warns += w
    res["SUM"] = extract_summary(lines)
    res["SEG"] = extract_segments(lines)
    res["_col_order"] = orders
    res["_std"] = std
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
        with open(os.path.join(OUT_DIR, f"fy{tag}.json"), "w", encoding="utf-8") as f:
            json.dump({"year": tag, "src": os.path.basename(p), "data": res,
                       "warns": warns}, f, ensure_ascii=False, indent=1)
        s = res["SUM"]
        print(f"FY{tag} [{res['_std']}]: IS={len(res['IS'])} BS={len(res['BS'])} "
              f"CF={len(res['CF'])} 列序={res['_col_order']} SEG块={len(res['SEG'])} "
              f"SUM={'x' if not s else str(len(s['rows'])) + '行/' + str(len(s['kihon'])) + '列'}")


if __name__ == "__main__":
    main()
