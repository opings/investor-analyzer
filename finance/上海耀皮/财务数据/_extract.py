#!/usr/bin/env python3
"""上海耀皮(600819) 年报三表提取器 —— 一手 PDF 文本层 → _extract_json/fy<YYYY>.json

管线：
  pypdf extract_text(extraction_mode="layout")   ← 保列位（nil 短横 "-" 才不会吞列）
    → 分节（合并资产负债表/合并利润表/合并现金流量表，止于对应「母公司…」）
    → 逐行取数字 token（含 "-" nil 占位）+ 字符右边界
    → 概念锚定匹配（CONCEPTS 正则表，跨行断名用 前/后 行拼接候选）
    → 每年输出 {IS,BS,CF: {concept: [本期, 上期]}}

为什么概念锚定而非「解析全部行」：
  年报三表跨 20 年科目名多次改版（2007 营业税金及附加→2018 税金及附加；
  2019 减值移位；2019 新租赁准则加使用权资产…），逐行全解析要维护巨大别名表；
  锚定「我要的概念」+ 下游勾稽校验兜底，更稳且可审计。

用法：python3 _extract.py [年份...]      默认 2006-2025（2006 取 2007 年报上年列）
"""
import json
import os
import re
import sys

from pypdf import PdfReader

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
PDF_DIR = os.path.join(ROOT, "report", "上海耀皮")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_extract_json")

# ---------------------------------------------------------------- 基础工具

# 附注引用两种写法，都必须在取数前抹掉：
#   ① 七（61） / 十九（1）        —— 带括号（2017 年后）
#   ② 五、10.7 / 五、48.1        —— 「章、条」式（2012-2016）。**这种最阴**：
#      "10.7" 会被当成一个合法小数金额，把本期/上期整体右移一列，
#      于是「营业总收入」读成 10.70、真营收挤到上期列，且表内勾稽仍可能局部自洽。
NOTE_RE = re.compile(
    r"[一二三四五六七八九十]+\s*[（(]\s*[^）)]{0,10}\s*[）)]"
    r"|[一二三四五六七八九十]+\s*、\s*\d+(?:\.\d+)?\s*[、.]?"
)
# 数字 token。**顺序敏感**：金额（千分位 + 恰好 2 位小数）必须排第一位。
# 相邻两列常常紧贴无空格（"5,641,566,721.755,635,853,311.66"），
# 若用宽松的 (?:\.\d+)? 会贪成 "5,641,566,721.755" —— 小数点后多吞一位，
# 金额悄悄变错还不报错。锁死 \.\d{2} 后，前列吃到 ...721.75、后列从 5,635... 重新起。
TOKEN_RE = re.compile(
    r"-?\d{1,3}(?:,\d{3})+\.\d{2}"      # 1,234,567.89 标准金额
    r"|-?\d{1,3}(?:,\d{3})+"            # 1,234,567    千分位整数
    r"|-?\d+\.\d+"                      # 0.17225      每股收益/比率
    r"|-?\d{4,}"                        # 无千分位长整数
    r"|(?<![\d.,])-(?![\d])"            # 独立短横 = nil 占位（保列位）
)


def norm_label(s: str) -> str:
    s = s.replace("（", "(").replace("）", ")").replace("：", ":")
    s = s.replace("“", '"').replace("”", '"').replace("－", "-").replace("．", ".")
    return re.sub(r"[\s　]+", "", s)


def page_lines(pdf_path):
    """返回 [(page_idx, line_str), ...]，并附带每页所用模式。

    默认用 layout 模式（保列位，nil 短横 "-" 才不会吞列）；但 **旋转页**（横排报表页）
    layout 模式会静默截断（pypdf 只打一句 "Rotated text discovered. Output will be
    incomplete."）——FY2011 整份 142 页只抽出 3093 行、三表全丢就是这么来的。
    故按页比对两种模式的产出量，layout 明显偏少时回退 plain（列位信息随之丢失，
    该页的单值行只能靠下游「上期列 vs 上一年本年列」互证兜底）。
    """
    reader = PdfReader(pdf_path)
    out, modes = [], {}
    for i, pg in enumerate(reader.pages):
        try:
            lay = pg.extract_text(extraction_mode="layout") or ""
        except Exception:
            lay = ""
        plain = pg.extract_text() or ""
        if len(lay.strip()) < 0.6 * len(plain.strip()):
            txt, modes[i] = plain, "plain"
        else:
            txt, modes[i] = lay, "layout"
        for ln in txt.split("\n"):
            if ln.strip():
                out.append((i, ln))
    page_lines.modes = modes
    return out


# ---------------------------------------------------------------- 分节

SECTIONS = {
    "BS": ("合并资产负债表", ("母公司资产负债表",)),
    "IS": ("合并利润表", ("母公司利润表",)),
    "CF": ("合并现金流量表", ("母公司现金流量表",)),
}
# 每节必须出现的「锚点词」，用来在多个同名标题里挑出真正的报表节
SECTION_ANCHOR = {"BS": "资产总计", "IS": "营业利润", "CF": "经营活动产生的现金流量净额"}


# 报表节最长行数：三表正文 40-90 行；超出必是把附注/会计政策正文卷进来了
MAX_SECTION_LINES = 260
# 兜底终止词：即使「母公司X表」缺失，遇到下一张报表/附注标题也停
STOP_KWS = ("所有者权益变动表", "股东权益变动表", "财务报表附注", "重要会计政策")


def slice_section(lines, kind):
    """取『合并X表』正文节。

    关键教训：不能用「数字最多」挑段——会计政策/附注正文动辄几千行、
    夹带零散数字，token 总数远超真报表。改用：标题行必须**精确等于**表名
    （正文里提到表名的句子不会精确相等）+ 命中锚点 + 段长封顶 + 取文档序最早。
    """
    start_kw, end_kws = SECTIONS[kind]
    anchor = SECTION_ANCHOR[kind]
    starts = [i for i, (_, ln) in enumerate(lines) if norm_label(ln) == start_kw]
    if not starts:  # 退化：标题与日期同行等情形
        starts = [i for i, (_, ln) in enumerate(lines)
                  if norm_label(ln).startswith(start_kw) and len(norm_label(ln)) <= len(start_kw) + 14]
    for s in starts:
        e = min(len(lines), s + MAX_SECTION_LINES)
        for j in range(s + 1, e):
            nl = norm_label(lines[j][1])
            if any(k in nl for k in end_kws) or any(k in nl for k in STOP_KWS):
                e = j
                break
        seg = lines[s:e]
        # 锚点在**去掉数字后再拼接**的段文本里找：layout 模式下长科目名会断行，
        # 且金额就插在断点中间（'…现金流量净  688,189,877.32  674,963,717.62' / '额'），
        # 只拼不去数字仍然匹配不上——FY2013/2018-2023 的 CF 就是这样被漏判的。
        if anchor in "".join(norm_label(TOKEN_RE.sub(" ", ln)) for _, ln in seg):
            return seg          # 文档序最早的合格段 = 报表正文
    return []


# ---------------------------------------------------------------- 行解析

DROP_RE = re.compile(
    r"年年?度报告|编制单位|单位:元|币种|^项目附注|^项目本期|^项目年初|公司负责人|公司法定代表人"
    r"|主管会计工作负责人|会计机构负责人|^\d+/\d+$|^第\d+页|同一控制下企业合并"
)


def parse_row(line: str):
    """一行 → (label_text, [(value|None, right_edge_char_pos), ...])"""
    s = NOTE_RE.sub(lambda m: " " * len(m.group(0)), line)
    toks = []
    for m in TOKEN_RE.finditer(s):
        raw = m.group(0)
        val = None if raw == "-" else float(raw.replace(",", ""))
        toks.append((val, m.end()))
    label = NOTE_RE.sub(" ", line)
    label = TOKEN_RE.sub(" ", label)
    label = norm_label(label)
    # 抹掉尾部残留的附注号碎片：2012-2016 年报附注写作「五、11」「五、10.7、11」，
    # NOTE_RE 吃掉前半后可能剩下 ".11" 之类，粘在科目名尾巴上
    # （'固定资产.11' 就匹配不上 ^固定资产$，该科目 4 个年份整列变空还不报错）。
    label = re.sub(r"[.、,\d]+$", "", label) if re.search(r"[一-龥)]", label) else label
    return label, toks


def column_centers(rows):
    """用「两 token 行」的右边界估计两列的字符位置中心。"""
    c1, c2 = [], []
    for _, toks, _idx in rows:
        if len(toks) == 2:
            c1.append(toks[0][1])
            c2.append(toks[1][1])
    if not c1:
        return None
    c1.sort(); c2.sort()
    return c1[len(c1) // 2], c2[len(c2) // 2]


# ---------------------------------------------------------------- 概念表
# 每项: concept -> 正则(匹配 norm_label 后的标签)。顺序敏感：先匹配到的行优先占用。

IS_CONCEPTS = [
    ("营业总收入",        r"^一?[、.]?营业总收入"),
    ("营业收入",          r"^其中:营业收入|^一?[、.]?营业收入(?!总)"),
    ("营业总成本",        r"^二?[、.]?营业总成本"),
    ("营业成本",          r"^其中:营业成本|^减:营业成本"),
    ("税金及附加",        r"^营业税金及附加|^税金及附加"),
    ("销售费用",          r"^销售费用"),
    ("管理费用",          r"^管理费用"),
    ("研发费用",          r"^研发费用"),
    ("财务费用",          r"^财务费用"),
    ("利息费用",          r"^其中:利息费用"),
    ("利息收入(财费)",     r"^利息收入$"),
    ("资产减值损失",       r"^资产减值损失"),
    ("信用减值损失",       r"^信用减值损失"),
    ("其他收益",          r"^加:其他收益|^其他收益$"),
    ("投资收益",          r"^投资收益|^加:投资收益"),
    ("公允价值变动收益",    r"^公允价值变动收益|^加:公允价值变动收益"),
    ("资产处置收益",       r"^资产处置收益"),
    ("营业利润",          r"^三?[、.]?营业利润"),
    ("营业外收入",        r"^加:营业外收入|^营业外收入"),
    ("营业外支出",        r"^减:营业外支出|^营业外支出"),
    ("利润总额",          r"^四?[、.]?利润总额"),
    ("所得税费用",        r"^减:所得税费用|^所得税费用"),
    ("净利润",            r"^五?[、.]?净利润"),
    ("归母净利润",        r"归属于母公司(股东|所有者)的净利"),
    ("少数股东损益",       r"^\d?\.?少数股东损益|^少数股东损益"),
    ("综合收益总额",       r"^七?[、.]?综合收益总额"),
    ("归母综合收益总额",    r"归属于母公司(所有者|股东)的综合收益总额"),
    ("少数股东综合收益总额", r"归属于少数股东的综合收益总额"),
    ("基本每股收益",       r"^\(一\)基本每股收益"),
    ("稀释每股收益",       r"^\(二\)稀释每股收益"),
]

BS_CONCEPTS = [
    ("货币资金",          r"^货币资金"),
    ("交易性金融资产",     r"^交易性金融资产"),
    ("应收票据",          r"^应收票据"),
    ("应收账款",          r"^应收账款"),
    ("应收款项融资",       r"^应收款项融资"),
    ("预付款项",          r"^预付款项"),
    ("其他应收款",        r"^其他应收款"),
    ("存货",              r"^存货"),
    ("合同资产",          r"^合同资产"),
    ("一年内到期的非流动资产", r"^一年内到期的非流动资产"),
    ("其他流动资产",       r"^其他流动资产"),
    ("流动资产合计",       r"^流动资产合计"),
    ("可供出售金融资产",    r"^可供出售金融资产"),
    ("其他权益工具投资",    r"^其他权益工具投资"),
    ("其他非流动金融资产",  r"^其他非流动金融资产"),
    ("长期应收款",        r"^长期应收款"),
    ("长期股权投资",       r"^长期股权投资"),
    ("投资性房地产",       r"^投资性房地产"),
    ("固定资产",          r"^固定资产$|^固定资产净额"),
    ("在建工程",          r"^在建工程"),
    ("工程物资",          r"^工程物资"),
    ("固定资产清理",       r"^固定资产清理"),
    ("使用权资产",        r"^使用权资产"),
    ("无形资产",          r"^无形资产"),
    ("开发支出",          r"^开发支出"),
    ("商誉",              r"^商誉"),
    ("长期待摊费用",       r"^长期待摊费用"),
    ("递延所得税资产",     r"^递延所得税资产"),
    ("其他非流动资产",     r"^其他非流动资产"),
    ("非流动资产合计",     r"^非流动资产合计"),
    ("资产总计",          r"^资产总计"),
    ("短期借款",          r"^短期借款"),
    ("应付票据",          r"^应付票据"),
    ("应付账款",          r"^应付账款"),
    ("预收款项",          r"^预收款项"),
    ("合同负债",          r"^合同负债"),
    ("应付职工薪酬",       r"^应付职工薪酬"),
    ("应交税费",          r"^应交税费"),
    ("应付利息",          r"^其中:应付利息|^应付利息"),
    ("应付股利",          r"^应付股利"),
    ("其他应付款",        r"^其他应付款"),
    ("一年内到期的非流动负债", r"^一年内到期的非流动负债"),
    ("其他流动负债",       r"^其他流动负债"),
    ("流动负债合计",       r"^流动负债合计"),
    ("长期借款",          r"^长期借款"),
    ("应付债券",          r"^应付债券"),
    ("租赁负债",          r"^租赁负债"),
    ("长期应付款",        r"^长期应付款$"),
    ("专项应付款",        r"^专项应付款"),
    ("预计负债",          r"^预计负债"),
    ("递延收益",          r"^递延收益"),
    ("递延所得税负债",     r"^递延所得税负债"),
    ("其他非流动负债",     r"^其他非流动负债"),
    ("非流动负债合计",     r"^非流动负债合计"),
    ("负债合计",          r"^负债合计"),
    # 2007-2010 年报权益节用「股东权益」系命名（股本 / 股东权益合计 / 负债和股东权益合计），
    # 2011 起才改用「实收资本(或股本) / 所有者权益合计 / 负债和所有者权益总计」
    ("实收资本(股本)",     r"^实收资本|^股本$"),
    ("其他权益工具",       r"^其他权益工具$"),
    ("资本公积",          r"^资本公积"),
    ("库存股",            r"^减:库存股"),
    ("其他综合收益",       r"^其他综合收益"),
    ("专项储备",          r"^专项储备"),
    ("盈余公积",          r"^盈余公积"),
    ("未分配利润",        r"^未分配利润"),
    ("外币报表折算差额",    r"^外币报表折算差额"),
    ("归母所有者权益合计",  r"归属于母公司所有者权益|^\(或股东权益\)合计"),
    ("少数股东权益",       r"^少数股东权益"),
    ("所有者权益合计",     r"^所有者权益\(?或?股?东?权?益?\)?合计|^股东权益合计$"),
    ("负债和所有者权益总计", r"^负债和所有者权益|^负债和股东权益合计|^股东权益\)总计"),
]

CF_CONCEPTS = [
    ("销售商品提供劳务收到的现金", r"^销售商品、?提供劳务收到的现金"),
    ("收到的税费返还",       r"^收到的税费返还"),
    ("收到其他与经营活动有关的现金", r"^收到其他与经营活动有关的现金|^收到的其他与经营活动有关的现金"),
    ("经营活动现金流入小计",  r"^经营活动现金流入小计"),
    ("购买商品接受劳务支付的现金", r"^购买商品、?接受劳务支付的现金"),
    ("支付给职工的现金",     r"^支付给职工(以及|及)为职工支付的现金"),
    ("支付的各项税费",       r"^支付的各项税费"),
    ("支付其他与经营活动有关的现金", r"^支付其他与经营活动有关的现金|^支付的其他与经营活动有关的现金"),
    ("经营活动现金流出小计",  r"^经营活动现金流出小计"),
    ("经营活动现金流量净额",  r"^经营活动产生的现金流量净额"),
    ("收回投资收到的现金",    r"^收回投资(收到|所收到)的现金"),
    ("取得投资收益收到的现金", r"^取得投资收益(收到|所收到)的现金"),
    ("处置长期资产收回现金净额", r"^处置固定资产、?无形资产和其他长期资产(收回|而收回)的现金净额|资产收回的现金净额$"),
    ("处置子公司收到的现金净额", r"^处置子公司及其他营业单位收到的现金净额"),
    ("收到其他与投资活动有关的现金", r"^收到其他与投资活动有关的现金|^收到的其他与投资活动有关的现金"),
    ("投资活动现金流入小计",  r"^投资活动现金流入小计"),
    ("购建长期资产支付的现金", r"^购建固定资产、?无形资产和其他长期资产支付的现金|资产支付的现金$"),
    ("投资支付的现金",       r"^投资支付的现金"),
    ("取得子公司支付的现金净额", r"^取得子公司及其他营业单位支付的现金净额"),
    ("支付其他与投资活动有关的现金", r"^支付其他与投资活动有关的现金|^支付的其他与投资活动有关的现金"),
    ("投资活动现金流出小计",  r"^投资活动现金流出小计"),
    ("投资活动现金流量净额",  r"^投资活动产生的现金流量净额"),
    ("吸收投资收到的现金",    r"^吸收投资(收到|所收到)的现金"),
    ("子公司吸收少数股东投资", r"^其中:子公司吸收少数股东投资收到的现金"),
    ("取得借款收到的现金",    r"^取得借款(收到|所收到)的现金"),
    ("发行债券收到的现金",    r"^发行债券收到的现金"),
    ("收到其他与筹资活动有关的现金", r"^收到其他与筹资活动有关的现金|^收到的其他与筹资活动有关的现金"),
    ("筹资活动现金流入小计",  r"^筹资活动现金流入小计"),
    ("偿还债务支付的现金",    r"^偿还债务支付的现金"),
    ("分配股利利润或偿付利息支付的现金", r"^分配股利、?利润或偿付利息支付的现金|^利、?利润或偿付利息支付的现金"),
    ("子公司支付给少数股东的股利", r"^其中:子公司支付给少数股东的股利"),
    ("支付其他与筹资活动有关的现金", r"^支付其他与筹资活动有关的现金|^支付的其他与筹资活动有关的现金"),
    ("筹资活动现金流出小计",  r"^筹资活动现金流出小计"),
    ("筹资活动现金流量净额",  r"^筹资活动产生的现金流量净额"),
    ("汇率变动影响",         r"^四?[、.]?汇率变动对现金|汇率变动对现金及现金等价物的影响"),
    ("现金及现金等价物净增加额", r"^五?[、.]?现金及现金等价物净增加额"),
    ("期初现金余额",         r"^加:期初现金及现金等价物余额"),
    ("期末现金余额",         r"^六?[、.]?期末现金及现金等价物余额"),
]

CONCEPTS = {"IS": IS_CONCEPTS, "BS": BS_CONCEPTS, "CF": CF_CONCEPTS}


def extract_section(lines, kind):
    seg = slice_section(lines, kind)
    if not seg:
        return {}, [f"{kind}: 未找到分节"]

    rows = []          # (label, toks, idx)
    plain = []         # 无数字行的 label，供跨行拼接
    for idx, (_, ln) in enumerate(seg):
        label, toks = parse_row(ln)
        if DROP_RE.search(label):
            plain.append((idx, ""))
            continue
        if toks:
            rows.append([label, toks, idx])
        else:
            plain.append((idx, label))

    plain_map = dict(plain)
    centers = column_centers(rows)
    warns = []

    # 结构兜底：合并报表只有**两个**金额列（本期/上期），多出来的 token 必是
    # 左侧附注列残留（NOTE_RE 没吃干净的写法），一律砍掉左边、保留最右两个。
    # 不用「按版面位置过滤」：老年报（2007-2010）layout 字宽被拉得极散，
    # 合法的本期列数字也可能落在左边界外，按位置筛会误删真金额、整列左移。
    for r in rows:
        if len(r[1]) > 2:
            r[1] = r[1][-2:]

    SCAN = 6   # 最多跨看几行（页眉/页码/附注号会夹在标签碎片之间）

    def ctx_back(idx, k):
        """向前累积最多 k 个「无数字」行拼成前缀。

        页眉、页码、附注号（已被置空或识别为碎片）**跳过但不中断**——
        FY2011 的标签尾巴常被一整套页眉页码隔在下一页开头；
        遇到另一个「有数字的行」才停（那是上一个科目，不属于本标签）。
        """
        parts, i, got, steps = [], idx - 1, 0, 0
        while i >= 0 and got < k and steps < SCAN:
            if i not in plain_map:
                break                      # 撞到另一个有数字的行，停
            s = plain_map[i]
            if s and not NOTE_FRAG_RE.match(s):
                parts.append(s)
                got += 1
            i -= 1
            steps += 1
        return "".join(reversed(parts))

    def ctx_fwd(idx, k):
        parts, i, got, steps = [], idx + 1, 0, 0
        while i < len(seg) and got < k and steps < SCAN:
            if i not in plain_map:
                break
            s = plain_map[i]
            if s and not NOTE_FRAG_RE.match(s):
                parts.append(s)
                got += 1
            i += 1
            steps += 1
        return "".join(parts)

    def variants(label, idx):
        """候选标签串。

        三种断行都要覆盖：
          ① 标签在数字行上（常态）
          ② 标签**尾巴**落到下一行（'…所有者权益' / '(或股东权益)合计 <数字>'）→ 需向前拼
          ③ 标签整体在前几行、数字**单独成行**（FY2011 旋转页 plain 模式：
             '销售商品、提供劳务' / '收到的现金' / '<数字> <数字>'）→ 需向前累积多行
        故按「上下文由窄到宽」生成候选，先窄后宽以降低误配。
        """
        v = [label]
        for k in (1, 2, 3, 4):
            b = ctx_back(idx, k)
            if b:
                v.append(b + label)
        for k in (1, 2):
            f = ctx_fwd(idx, k)
            if f:
                v.append(label + f)
                b1 = ctx_back(idx, 1)
                if b1:
                    v.append(b1 + label + f)
        return [x for x in v if x]

    compiled = [(c, re.compile(p)) for c, p in CONCEPTS[kind]]

    def self_matches_any(label):
        """该行**自身**标签是否已经是一个完整科目名。"""
        return any(rx.search(label) for _, rx in compiled)

    # 预合并：**一行被拆成两行、两个金额各挂一行**的版式。
    # FY2008 现金流量表实例：
    #   '购建固定资产、无形资产和其他长期资产支付的   724,915,398.54'   ← 上期列
    #   '现金                                     660,059,186.75'   ← 本期列
    # 长科目名换行后，本期金额的纵坐标落在第二行，于是被拆到两行里；
    # 两行各自都有数字，前后文拼接（只跨「无数字行」）根本够不着，
    # 结果该科目整列丢失，而勾稽遇 None 会跳过、不报错。
    # 合并条件：本行标签不成词 + 下一行紧邻 + 拼起来正好成词 + 合并后不超两个金额。
    merged, i = [], 0
    while i < len(rows):
        cur_r = rows[i]
        if (i + 1 < len(rows) and not self_matches_any(cur_r[0])
                and rows[i + 1][2] == cur_r[2] + 1
                and len(cur_r[1]) + len(rows[i + 1][1]) <= 2
                and self_matches_any(cur_r[0] + rows[i + 1][0])):
            nxt = rows[i + 1]
            toks = sorted(cur_r[1] + nxt[1], key=lambda t: t[1])   # 按列位排序 → [本期, 上期]
            merged.append([cur_r[0] + nxt[0], toks, cur_r[2]])
            i += 2
            continue
        merged.append(cur_r)
        i += 1
    rows = merged

    out, used = {}, set()

    # —— 第 1 遍（严格）：只用行**自身**标签匹配。
    # 必须先跑这遍：报表里空科目行（"合同资产"/"应付债券"/"专项储备"…）极多，
    # 若一上来就允许向前拼多行上下文，空科目名会被拼到**下一个有数字的行**头上，
    # 于是「合同资产」吃掉「其他流动资产」的数、整列系统性串位。
    for concept, rx in compiled:
        for ri, (label, toks, idx) in enumerate(rows):
            if ri in used:
                continue
            if rx.search(label):
                out[concept] = assign_columns(toks, centers, kind, concept, warns)
                used.add(ri)
                break

    # —— 第 2 遍（断行修复）：只处理**自身标签不构成任何完整科目**的孤儿碎片。
    # 这类行才是真的跨行断名：'(或股东权益)合计 <数字>'、
    # 或 FY2011 旋转页里标签在前几行、数字独占一行（自身标签为空）。
    #
    # 关键：**按行驱动、且上下文由窄到宽逐步放大，一匹配上就停**。
    # 不能按概念驱动、直接拿最宽上下文去撞——FY2011 里空科目「收到其他与投资活动
    # 有关的现金」紧挨在「投资活动现金流入小计」前面，拼 4 行会得到
    # "收到其他与投资活动有关的现金投资活动现金流入小计"，前者的正则从头就能命中，
    # 于是把后者的数抢走。**离数字最近的那个标签才是这行的主人**，所以从 k=1 起试。
    for ri, (label, toks, idx) in enumerate(rows):
        if ri in used or self_matches_any(label):
            continue
        # 断行方向随抽取模式而反：
        #   layout 模式（多数年份）——数字留在标签**首行**，尾巴换到下一行
        #       '所有者权益(或股东权 <数字> <数字>' / '益)合计'      → 需向**后**拼
        #   plain 模式（FY2011 旋转页）——标签占前几行，数字**独占一行**（本行标签为空）
        #       '投资活动现金流入' / '小计' / '<数字> <数字>'         → 需向**前**拼
        # 两向都试，k 由窄到宽，取「匹配贴到串尾且最长」的概念。
        # 用**本行标签是否为空**判断该往哪个方向拼——这是两种抽取模式的可靠判别：
        #   标签非空 = layout 模式的标签**首行**（数字就在这行），尾巴在下一行 → 向后拼
        #   标签为空 = plain 模式的**纯数字行**，标签整个在上面几行         → 向前拼
        # 必须定死方向优先级，不能两向一起打分：FY2011 里
        # '经营活动现金流出小计' 与 '经营活动产生的现金流量净额' 前后紧挨，
        # 纯数字行两向都能匹配上，按「匹配更长」挑会挑中后者，净额被流出小计的数覆盖。
        label_empty = (not label) or bool(NOTE_FRAG_RE.match(label))
        hit = None
        for k in (1, 2, 3, 4):
            back, fwd = ctx_back(idx, k), ctx_fwd(idx, k)
            ordered = []
            if label_empty:
                if back:
                    ordered.append(back + label)
            else:
                if fwd:
                    ordered.append(label + fwd)
                if back:
                    ordered.append(back + label)
                if back and fwd:
                    ordered.append(back + label + fwd)
            for cand in ordered:
                best = None
                for concept, rx in compiled:
                    if concept in out:
                        continue
                    m = rx.search(cand)
                    if not m:
                        continue
                    # 越贴近串尾、匹配越长 = 越可能是这行真正的科目
                    score = (m.end() == len(cand), m.end() - m.start())
                    if best is None or score > best[0]:
                        best = (score, concept)
                if best:
                    hit = best[1]
                    break
            if hit:
                break
        if hit:
            out[hit] = assign_columns(toks, centers, kind, hit, warns)
            used.add(ri)
    return out, warns


def assign_columns(toks, centers, kind, concept, warns):
    """把该行的 token 放进两列。2 token → 按顺序；1 token → 按右边界靠近哪一列。"""
    if len(toks) >= 2:
        return [toks[0][0], toks[1][0]]
    if len(toks) == 1:
        v, pos = toks[0]
        if centers is None:
            warns.append(f"{kind}/{concept}: 单值行且无列中心，置于本期列")
            return [v, None]
        d1, d2 = abs(pos - centers[0]), abs(pos - centers[1])
        if d1 <= d2:
            warns.append(f"{kind}/{concept}: 单值行→判为本期列(pos={pos},c={centers})")
            return [v, None]
        warns.append(f"{kind}/{concept}: 单值行→判为上期列(pos={pos},c={centers})")
        return [None, v]
    return [None, None]


# ---------------------------------------------------------------- 主流程

# ---------------------------------------------------------------- 主要会计数据锚点
# 年报「近三年主要会计数据和财务指标」= 公司自家披露值，用来独立核对三表解析结果；
# 且**扣非归母净利只在这张表里有**（利润表无此行）。

# ⚠️ 顺序敏感：扣非必须排在归母**前面**。两行标签高度相似
# （"归属于上市公司股东…的净利润" vs "归属于上市公司股东…的扣除非经常性损益…的净利润"），
# 归母的宽松正则会先把扣非那行吃掉。先匹配更специфic的扣非、占用该行，归母才落到自己行上。
# 各年标签跨 2-3 行断开，且「本期比上年增减」列可能是"不适用"三个字**插在标签中间**
# （FY2024: "归属于上市公司股东" + "的扣除非经常性损益不适用" + "的净利润"），
# 故正则一律留 .{0,8} 的空隙，且候选串要包含 前+本+后 三行拼接。
ANCHOR_CONCEPTS = [
    # 各年行名有别：营业收入/营业总收入、总资产/资产总额、
    # 归属于…的净资产 / 所有者权益(或股东权益) / 归属于…的所有者权益
    ("营业收入",       r"^营业(总)?收入(不适用)?$|^营业(总)?收入\d"),
    ("利润总额",       r"^利润总额"),
    ("扣非归母净利润",  r"扣除非经常性损益.{0,8}的净利润|的?扣除.{0,4}非经常性损益的净利润"),
    ("归母净利润",     r"归属于上市公司股东.{0,8}的净利润"),
    ("经营现金流量净额", r"^经营活动产生的现金.{0,6}流?量?净额"),
    ("归母净资产",     r"归属于上市公司股东.{0,8}的净资产|^所有者权益\(或股东权益\)$"
                      r"|归属于上市公司股东的所有者权益"),
    ("总资产",         r"^总资产|^资产总额"),
    ("扣非加权ROE",    r"扣除非经常性损益后的加权"),
    ("加权平均ROE",    r"^加权平均净资产收益率"),
]
# 这些概念并非每年都在「主要会计数据」表里列示（如 2010-2024 多数年份无「利润总额」行），
# 缺失属正常，不计为警告。
ANCHOR_OPTIONAL = {"利润总额", "扣非加权ROE", "加权平均ROE"}

# 增减%列取不到值时，各年分别写作「不适用」或一个半角「/」；两者都会插进断开的标签里。
# 半角 / 只在两侧非数字时才剔（避免动到页码 "5/139"）；全角 ／（"元／股"）不受影响。
# 附注号碎片（"五、51、" / "(1)" / 纯页码），拼标签时要跳过
NOTE_FRAG_RE = re.compile(r"^(?:[一二三四五六七八九十]+、\d*、?|\(\d+\)|\d+|附注)$")
FILLER_RE = re.compile(r"不适用|√适用|□适用|增加个百分点|减少个百分点|个百分点|(?<!\d)/(?!\d)")
ANCHOR_START = re.compile(r"主要会计数据和财务指标|近三年主要会计数据")
ANCHOR_STOP = re.compile(r"非经常性损益项目和金额|采用公允价值计量|境内外会计准则")


def extract_anchors(lines):
    """抓「主要会计数据」表：每概念取前两个数字 = [本年, 上年]。"""
    s = None
    for i, (_, ln) in enumerate(lines):
        if ANCHOR_START.search(norm_label(ln)):
            s = i
            break
    if s is None:
        return {}, ["ANCHOR: 未找到主要会计数据表"]
    e = min(len(lines), s + 90)
    for j in range(s + 1, e):
        if ANCHOR_STOP.search(norm_label(lines[j][1])):
            e = j
            break
    seg = lines[s:e]
    rows, plain = [], {}
    for idx, (_, ln) in enumerate(seg):
        label, toks = parse_row(ln)
        if toks:
            rows.append([label, toks, idx])
        else:
            plain[idx] = label
    out, used, warns = {}, set(), []
    for concept, pat in ANCHOR_CONCEPTS:
        rx = re.compile(pat)
        for ri, (label, toks, idx) in enumerate(rows):
            if ri in used:
                continue
            # 「不适用」是**增减%列的单元格取值**，排版上会插进断开的标签中间
            # （FY2016: "归属于上市公司股" + 不适用 + "东的净利润" —— 连"股东"都被劈开），
            # 先剔除这类填充词，标签碎片才能拼回原样。
            lb = FILLER_RE.sub("", label)
            p1 = FILLER_RE.sub("", plain.get(idx - 1, ""))
            n1 = FILLER_RE.sub("", plain.get(idx + 1, ""))
            n2 = FILLER_RE.sub("", plain.get(idx + 2, ""))
            cands = [lb, lb + n1, p1 + lb, p1 + lb + n1,
                     lb + n1 + n2, p1 + lb + n1 + n2]
            if any(rx.search(c) for c in cands if c):
                vals = [t[0] for t in toks][:2]
                while len(vals) < 2:
                    vals.append(None)
                out[concept] = vals
                used.add(ri)
                break
        else:
            if concept not in ANCHOR_OPTIONAL:
                warns.append(f"ANCHOR/{concept}: 未匹配")
    return out, warns


def pdf_for(year):
    p = os.path.join(PDF_DIR, f"上海耀皮-{year}.pdf")
    if not os.path.exists(p):
        raise SystemExit(f"缺 PDF: {p}")
    return p


def extract_year(year):
    lines = page_lines(pdf_for(year))
    res, warns = {}, []
    for kind in ("IS", "BS", "CF"):
        d, w = extract_section(lines, kind)
        res[kind] = d
        warns += w
    a, w = extract_anchors(lines)
    res["ANCHOR"] = a
    warns += w
    return res, warns


def main():
    years = sys.argv[1:] or [str(y) for y in range(2007, 2026)]
    os.makedirs(OUT_DIR, exist_ok=True)
    for y in years:
        res, warns = extract_year(y)
        with open(os.path.join(OUT_DIR, f"fy{y}.json"), "w", encoding="utf-8") as f:
            json.dump({"year": int(y), "data": res, "warns": warns}, f,
                      ensure_ascii=False, indent=1)
        n = {k: len(v) for k, v in res.items()}
        print(f"FY{y}: IS={n['IS']} BS={n['BS']} CF={n['CF']} ANCHOR={n['ANCHOR']}  警告 {len(warns)}")
        for w in warns:
            print(f"    ⚠️ {w}")


if __name__ == "__main__":
    main()
