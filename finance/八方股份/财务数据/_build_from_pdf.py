#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""八方股份（603489）财务数据构建器 —— 从一手财报 PDF 解析三表 + 派生比率。

真源（唯一）：`report/八方股份/`
  - 八方股份-招股说明书.pdf   → 2016 / 2017 / 2018（上市前，独家）+ 2019H1
  - 八方股份-YYYY.pdf（年报）  → 每份含「本年 + 上年」两列
  - 八方股份-2026-Q2.pdf       → 2026 中期

设计要点（都是本库踩过的坑的直接反制）：
  1. **按页聚类定列**：pdftotext -layout 的列位逐页漂移，且「本年空/上年有值」的孤值行
     很常见（如 2025 年报「在建工程」「短期借款」）。若按出现顺序分列必整体错一年。
     故：每页用「满列行」的数字右端位置定出列心，再把每个数字归到最近列心。
  2. **多行标签**：标签换行时数字行前无文字，回取上一条纯文字行作标签。
  3. **多源交叉核**：同一年份在不同申报里重复出现（年报本年列 vs 次年年报上年列 vs
     招股书列）。全部采集后逐格比对，冲突必须显式报出，不静默取其一。
  4. **勾稽不过不写出**：三表各自恒等式 + 跨表衔接，任一不过直接退出码 1。

用法：
    python3 _build_from_pdf.py              # 校验 + 写出 CSV
    python3 _build_from_pdf.py --check      # 只校验与交叉核，不写文件
    python3 _build_from_pdf.py --unmatched  # 额外打印未命中别名表的原始标签
"""
from __future__ import annotations

import csv
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PDF_DIR = ROOT / "report" / "八方股份"
OUT_DIR = Path(__file__).resolve().parent
CACHE = OUT_DIR / ".txtcache"   # 目录名须与 .gitignore 的 finance/**/.txtcache/ 一致（缓存不入库）

UNIT = "元"  # 三表原始口径：人民币元

# ---------------------------------------------------------------- 文本提取

def pdf_text(stem: str) -> list[list[str]]:
    """PDF → 按页切分的行列表。pdftotext -layout 保留列位，\f 分页。"""
    CACHE.mkdir(exist_ok=True)
    txt = CACHE / f"{stem}.txt"
    if not txt.exists():
        pdf = PDF_DIR / f"{stem}.pdf"
        if not pdf.exists():
            sys.exit(f"[FATAL] 缺一手财报: {pdf}")
        subprocess.run(
            ["pdftotext", "-layout", str(pdf), str(txt)], check=True
        )
    pages = txt.read_text(encoding="utf-8").split("\f")
    return [p.splitlines() for p in pages]


# ---------------------------------------------------------------- 行解析

NUM = re.compile(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2,4}")
# 附注号形如「七、5」「七、76（1）」「十九、4」—— 带括号子号的变体也要剥掉，
# 否则剩一个 "七、76（1）" 当标签，整行漏读（实证：2019 年报「收到其他与经营活动有关的现金」）。
NOTE_REF = re.compile(r"[一二三四五六七八九十]+\s*、\s*[\d、\s]*(?:[（(]\s*\d+\s*[）)])?\s*$")
PAGE_MARK = re.compile(r"^\s*\d+\s*/\s*\d+\s*$|^\s*1-1-\d+\s*$")
RUNNING_HEAD = re.compile(r"年年度报告\s*$|年半年度报告\s*$|^\s*编制单位|^\s*单位：")
# 🔴 招股书表头用「2019.6.30 / 2018.12.31」做列名，NUM 会从中抠出 "6.30"/"2018.12" 四个
#    假数字 → 恰好等于列数、被当成满列行，既污染列心又被别名表当成「负债和股东权益」的值
#    （实证：2016/2017「负债和所有者权益总计」被读成 2,016.12 / 2,018.12）。
#    故取数前先把日期涂白 —— 用等长空格替换，列位不能变。
DATE_COL = re.compile(r"\d{4}\.\d{1,2}\.\d{1,2}")


def mask_dates(ln: str) -> str:
    return DATE_COL.sub(lambda m: " " * len(m.group()), ln)


def _clusters(ends: list[int], tol: int = 4) -> list[int]:
    """把数字右端位置聚成列位（升序）。只用于「整页无满列行」的段级兜底。"""
    out: list[list[int]] = []
    for e in sorted(ends):
        if out and e - out[-1][-1] <= tol:
            out[-1].append(e)
        else:
            out.append([e])
    return [round(sum(c) / len(c)) for c in out]


def parse_page(lines: list[str], ncols: int, fallback=None) -> list[tuple[str, list[float | None]]]:
    """解析一页，返回 [(标签, [各列值/None]), ...]。

    🔴 分列策略（这段是整个构建器最容易出错的地方，两类错都实际发生过）：
      - **满列行**（数字个数 == ncols）→ 直接按出现顺序填。永远对。
      - **缺列行**（本年空/上年有值，如 2025 年报「在建工程」「短期借款」）→ 必须靠列位判断，
        否则整格错一年。列位取**行号上最近的那条满列行**的右端位置。
    为什么不用「整页聚类」：同一页常并存两套列宽（利润表尾部的每股收益 0.46/0.14 右端 46/53，
    主表却在 48/64）。按全页聚类要么聚出 4 簇判成异常整页退化，要么按样本数裁成 2 簇、
    把每股收益吸到错列（实测：2025「基本每股收益」被写成上年的 0.27、中报写成 0.14）。
    「最近满列行」天然按子表分区，两类版式都对。
    """
    hits = []  # (行号, 原始行, [(end, value)])
    for i, ln in enumerate(lines):
        if PAGE_MARK.search(ln) or RUNNING_HEAD.search(ln):
            continue
        masked = mask_dates(ln)
        ms = list(NUM.finditer(masked))
        if ms:
            hits.append((i, masked, [(m.end(), m.group()) for m in ms]))

    full = [h for h in hits if len(h[2]) == ncols]

    def centers_for(i: int):
        """该行分列时参照的列位 = 行号上最近的满列行的右端位置（无则用段级兜底）。"""
        if not full:
            return fallback
        near = min(full, key=lambda h: abs(h[0] - i))
        return [e for e, _ in near[2]]

    out = []
    pending = ""
    hit_idx = {h[0]: h for h in hits}
    for i, ln in enumerate(lines):
        if PAGE_MARK.search(ln) or RUNNING_HEAD.search(ln):
            continue
        if i not in hit_idx:
            t = re.sub(r"\s+", "", ln)
            if t:
                pending = t
            continue
        _, raw, nums = hit_idx[i]
        head = raw[: raw.index(nums[0][1])]
        head = re.sub(r"\s+", "", NOTE_REF.sub("", head))
        # 🔴 招股书用「-」表示该年无金额，这些占位符落在数字之前会被当成标签的一部分
        #    （实证：'预计负债---' / '非流动负债合计---' / '投资性房地产-' 三行因此全年漏读，
        #      而 2016 非流动负债合计 3,653,400.00 的缺失又被「有 None 就跳过」的勾稽放行）。
        head = re.sub(r"[-—–‑]+$", "", head)
        # 🔴 标签碎片有三种落法，且同一份报告里混用：
        #    (a) 全在数字行之前的纯文字行 → head 为空，取 pending
        #    (b) 全在数字行行首        → head 自足
        #    (c) **跨行：开头在上一行、结尾在本行行首**（招股书「购建固定资产、无形资产」/
        #        「和其他长期资产支付的现 <数字>」；「现金及现金等价物净增加」/「额(净减少以…」）
        #    (c) 只取 head 会得到「和其他长期资产支付的现」这种无法匹配的残片，
        #    只取 pending+head 又会让 `^` 锚定的别名被上一行的小节标题（「流动资产：」）顶掉。
        #    故每行同时携带两个候选标签，pick() 命中任一即可。
        #    ⚠️ 拼接要有护栏：上一行也可能是「本身就没有数值的空行」而非续写。
        #    实证：「2.少数股东损益（…）」是空行，下一行是「六、其他综合收益的税后净额 <数字>」，
        #    无脑拼接会让「少数股东损益」吃到其他综合收益的值（差额恰为 OCI，2023-2025 三年全中）。
        #    判据：本行行首若带「一、/（一）/1./其中：/加：/减：」这类**新行开头标记**，就不是续写。
        opener = re.match(r"^(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十\d]+）|"
                          r"\d+[.．、]|其中：|加：|减：)", head)
        cands = [head or pending]
        if pending and head and not opener:
            cands.append(pending + head)
        labels = tuple(dict.fromkeys(x for x in cands if x))
        pending = ""
        row: list[float | None] = [None] * ncols
        if len(nums) == ncols:                      # 满列行：按顺序填，永远对
            for j, (_, v) in enumerate(nums):
                row[j] = float(v.replace(",", ""))
        else:                                        # 缺列行：靠最近满列行的列位判断归属
            cs = centers_for(i)
            if not cs or len(cs) != ncols:
                print(f"  [WARN] 定不出列位，跳过行: {labels} -> {[v for _, v in nums]}")
                continue
            for e, v in nums:
                j = min(range(ncols), key=lambda k: abs(cs[k] - e))
                row[j] = float(v.replace(",", ""))
        out.append((labels, row))
    return out


def take_section(pages, start_pat, end_pat, ncols, first_page=0):
    """从 pages 中切出一段（可跨页），解析成 [(标签, 各列值)]。

    两趟：先切出各页片段并汇总「段级列心」，再逐页解析——某页自己定不出列心时拿段级的兜底。
    """
    sp, ep = re.compile(start_pat), re.compile(end_pat)
    chunks, started = [], False
    for pno in range(first_page, len(pages)):
        lines = pages[pno]
        s = 0
        if not started:
            for i, ln in enumerate(lines):
                if sp.search(ln):
                    started, s = True, i
                    break
            if not started:
                continue
        e = len(lines)
        for i in range(s + 1, len(lines)):
            if ep.search(lines[i]):
                e = i
                break
        chunks.append(lines[s:e])
        if e < len(lines):
            break
    # 段级兜底列位：只在某页一条满列行都没有时才用（此时无从按「最近满列行」判断）
    all_ends = []
    for ch in chunks:
        for ln in ch:
            if PAGE_MARK.search(ln) or RUNNING_HEAD.search(ln):
                continue
            ms = list(NUM.finditer(mask_dates(ln)))
            if len(ms) == ncols:
                all_ends += [m.end() for m in ms]
    sec = _clusters(all_ends) if all_ends else None
    if sec and len(sec) != ncols:
        sec = None
    rows = []
    for ch in chunks:
        rows += parse_page(ch, ncols, fallback=sec)
    return rows


# ---------------------------------------------------------------- 别名表
# 每项：(canonical, [正则...])  —— 按 normalize 后的标签匹配，取段内首个命中行。

IS_ITEMS = [
    ("营业总收入", [r"^一、营业总收入", r"^营业收入$"]),
    ("营业收入", [r"^其中：营业收入", r"^营业收入$"]),
    ("营业总成本", [r"^二、营业总成本"]),
    ("营业成本", [r"^其中：营业成本", r"^减：营业成本", r"^营业成本$"]),
    ("税金及附加", [r"税金及附加$"]),
    ("销售费用", [r"^销售费用$"]),
    ("管理费用", [r"^管理费用$"]),
    ("研发费用", [r"^研发费用$"]),
    ("财务费用", [r"^财务费用$"]),
    ("其中：利息费用", [r"^其中：利息费用$", r"^利息费用$"]),
    ("其中：利息收入", [r"^利息收入$"]),
    ("其他收益", [r"^加：其他收益", r"^其他收益（"]),
    ("投资收益", [r"^投资收益", r"^投资收益\(", r"^投资收益（"]),
    ("公允价值变动收益", [r"公允价值变动收益"]),
    ("信用减值损失", [r"信用减值损失"]),
    ("资产减值损失", [r"资产减值损失"]),
    ("资产处置收益", [r"资产处置收益"]),
    ("营业利润", [r"^三、营业利润", r"^营业利润"]),
    ("营业外收入", [r"^加：营业外收入", r"^营业外收入"]),
    ("营业外支出", [r"^减：营业外支出", r"^营业外支出"]),
    ("利润总额", [r"^四、利润总额", r"^利润总额"]),
    ("所得税费用", [r"^减：所得税费用", r"^所得税费用"]),
    ("净利润", [r"^五、净利润", r"^净利润"]),
    ("归属于母公司股东的净利润", [r"归属于母公司股东的净利润", r"归属于母公司所有者的净利润"]),
    ("少数股东损益", [r"^2\.少数股东损益", r"^少数股东损益"]),
    ("其他综合收益的税后净额", [r"^六、其他综合收益的税后净额", r"^其他综合收益的税后"]),
    ("综合收益总额", [r"^七、综合收益总额", r"^综合收益总额"]),
    ("基本每股收益", [r"基本每股收益"]),
    # 下面两行利润表里没有，由 main() 从非经常性损益表填（空 pattern = 解析器不碰）
    ("非经常性损益合计", []),
    ("扣非归母净利润", []),
]

BS_ITEMS = [
    ("货币资金", [r"货币资金$"]),
    ("交易性金融资产", [r"交易性金融资产$"]),
    ("应收票据", [r"应收票据$"]),
    ("应收账款", [r"^应收账款$", r"应收账款$"]),
    ("应收款项融资", [r"应收款项融资$"]),
    ("预付款项", [r"预付款项$"]),
    ("其他应收款", [r"其他应收款$"]),
    ("存货", [r"存货$"]),
    ("其他流动资产", [r"其他流动资产$"]),
    ("流动资产合计", [r"流动资产合计$"]),
    ("债权投资", [r"债权投资$"]),
    ("投资性房地产", [r"投资性房地产$"]),
    ("固定资产", [r"固定资产$"]),
    ("在建工程", [r"在建工程$"]),
    ("使用权资产", [r"使用权资产$"]),
    ("无形资产", [r"无形资产$"]),
    ("开发支出", [r"^开发支出$"]),
    ("商誉", [r"^商誉$"]),
    ("长期待摊费用", [r"长期待摊费用$"]),
    ("递延所得税资产", [r"递延所得税资产$"]),
    ("其他非流动资产", [r"其他非流动资产$"]),
    ("非流动资产合计", [r"非流动资产合计$"]),
    ("资产总计", [r"资产总计$"]),
    ("短期借款", [r"短期借款$"]),
    ("应付票据", [r"应付票据$"]),
    ("应付账款", [r"应付账款$"]),
    ("预收款项", [r"预收款项$"]),
    ("合同负债", [r"合同负债$"]),
    ("应付职工薪酬", [r"应付职工薪酬$"]),
    ("应交税费", [r"应交税费$"]),
    ("其他应付款", [r"其他应付款$"]),
    ("一年内到期的非流动负债", [r"一年内到期的非流动负债$"]),
    ("其他流动负债", [r"其他流动负债$"]),
    ("流动负债合计", [r"流动负债合计$"]),
    ("长期借款", [r"^长期借款$"]),
    ("租赁负债", [r"租赁负债$"]),
    ("预计负债", [r"预计负债$"]),
    ("递延收益", [r"递延收益$"]),
    ("递延所得税负债", [r"递延所得税负债$"]),
    ("非流动负债合计", [r"非流动负债合计$"]),
    ("负债合计", [r"负债合计$"]),
    ("实收资本（股本）", [r"实收资本（或股本）$", r"^股本\(实收资本\)$", r"^股本$"]),
    ("资本公积", [r"资本公积$"]),
    ("减：库存股", [r"减：库存股$", r"^库存股$"]),
    ("其他综合收益", [r"^其他综合收益$"]),
    ("盈余公积", [r"盈余公积$"]),
    ("未分配利润", [r"未分配利润$"]),
    # ⚠️ 标签在不同年报里换行位置不同（2022 年报断成「所有者权益（或股东权」+「益）合计」），
    #    别名必须对截断宽容 —— 用前缀匹配而非全等。
    ("归属于母公司所有者权益合计", [r"^归属于母公司所有者权益", r"^归属于母公司所有者$"]),
    ("少数股东权益", [r"^少数股东权益$"]),
    ("所有者权益合计", [r"^所有者权益", r"^股东权益合计$"]),
    ("负债和所有者权益总计", [r"^负债和所有者权益", r"^负债和股东权益"]),
]

# ⚠️ 现金流量表标签换行位置逐年不同，且**断点可能落在数字行之前**：
#    2022 年报是「销售商品、提供劳务收到的  <数字>」/ 换行「现金」，
#    2025 年报是「销售商品、提供劳务收到的现金  <数字>」。
#    全等匹配会整段漏读（实证：2022 全年现金流量表 16 项静默兜底到 2023 年报上年列）。
#    故一律用**前缀**匹配；顺序靠 pick() 的文档序保证唯一。
CF_ITEMS = [
    # 招股书把断点放得更靠前（「销售商品、提供劳务收到」/ 换行「的现金」），前缀还要再短
    ("销售商品、提供劳务收到的现金", [r"^销售商品、提供劳务收到"]),
    ("收到的税费返还", [r"^收到的税费返还"]),
    ("收到其他与经营活动有关的现金", [r"^收到其他与经营活动有关"]),
    ("经营活动现金流入小计", [r"^经营活动现金流入小计"]),
    ("购买商品、接受劳务支付的现金", [r"^购买商品、接受劳务支付"]),
    ("支付给职工以及为职工支付的现金", [r"^支付给职工"]),
    ("支付的各项税费", [r"^支付的各项税费"]),
    ("支付其他与经营活动有关的现金", [r"^支付其他与经营活动有关"]),
    ("经营活动现金流出小计", [r"^经营活动现金流出小计"]),
    # 2022 年报把「量净额」也断到下一行 → 前缀只能截到「现金流」
    ("经营活动产生的现金流量净额", [r"^经营活动产生的现金流"]),
    ("收回投资收到的现金", [r"^收回投资收到的现金"]),
    ("取得投资收益收到的现金", [r"^取得投资收益收到的现金"]),
    ("处置固定资产等收回的现金净额", [r"^处置固定资产"]),
    ("收到其他与投资活动有关的现金", [r"^收到其他与投资活动有关"]),
    ("投资活动现金流入小计", [r"^投资活动现金流入小计"]),
    ("购建固定资产等支付的现金", [r"^购建固定资产"]),
    ("投资支付的现金", [r"^投资支付的现金"]),
    ("投资活动现金流出小计", [r"^投资活动现金流出小计"]),
    ("投资活动产生的现金流量净额", [r"^投资活动产生的现金流"]),
    ("吸收投资收到的现金", [r"^吸收投资收到的现金"]),
    ("取得借款收到的现金", [r"^取得借款收到的现金"]),
    ("收到其他与筹资活动有关的现金", [r"^收到其他与筹资活动有关"]),
    ("筹资活动现金流入小计", [r"^筹资活动现金流入小计"]),
    ("偿还债务支付的现金", [r"^偿还债务支付的现金"]),
    ("分配股利、利润或偿付利息支付的现金", [r"^分配股利、利润或偿付利"]),
    ("支付其他与筹资活动有关的现金", [r"^支付其他与筹资活动有关"]),
    ("筹资活动现金流出小计", [r"^筹资活动现金流出小计"]),
    ("筹资活动产生的现金流量净额", [r"^筹资活动产生的现金流"]),
    ("汇率变动对现金的影响", [r"^四、汇率变动对现金", r"^汇率变动对现金"]),
    ("现金及现金等价物净增加额", [r"^五、现金及现金等价物净增加", r"^现金及现金等价物净增加"]),
    ("期初现金及现金等价物余额", [r"^加：期初现金及现金等价", r"^加：年初现金及现金等价", r"^期初现金及现金等价"]),
    ("期末现金及现金等价物余额", [r"^六、期末现金及现金等价物余", r"^期末现金及现金等价物余"]),
]


# ---------------------------------------------------------------- 扣非归母
# A股利润表内**没有**扣非行（只在「主要会计数据」披露）。这里走两条独立路径再对撞：
#   路径①  非经常性损益项目和金额表的「合计」→ 扣非 = 归母净利 − 合计
#   路径②  主要会计数据表直接披露的扣非值（该表最左列恒为本年）
# 两条不等就是错，必须停。招股书那张表叫「非经常性损益净额」，4 列。

def nonrecurring():
    """返回 {year: [(源, 非经常性损益合计)]}。"""
    out = defaultdict(list)
    pages = pdf_text("八方股份-招股说明书")
    rows = take_section(
        pages, r"经注册会计师核验的非经常性损益明细表", r"最近一期末的主要资产情况", 4, first_page=310
    )
    for labels, vals in rows:
        if any(lb.startswith("非经常性损益净额") for lb in labels):
            for j, yr in enumerate(["2019H1", "2018", "2017", "2016"]):
                if yr != "2019H1" and vals[j] is not None:
                    out[yr].append(("招股书", vals[j]))
            break
    for y in ANNUAL:
        pages = pdf_text(f"八方股份-{y}")
        rows = take_section(pages, r"非经常性损益项目和金额", r"^\s*十一、|采用公允价值计量的项目", 3)
        for labels, vals in rows:
            if any(lb.startswith("合计") for lb in labels):
                for j, yr in enumerate([y, str(int(y) - 1), str(int(y) - 2)]):
                    if vals[j] is not None:
                        out[yr].append((f"{y}年报", vals[j]))
                break
    return out


def disclosed_kf():
    """路径②：主要会计数据表披露的扣非归母（该表最左列恒为本年）。返回 {year: 值}。

    ⚠️ 标签在年报里被切成 3-4 个碎片、数字夹在碎片中间（2019 年报：「归属于上市公司」/
    「股东的扣除非经」/ <数字行> /「常性损益的净利」/「润」）。故不按单行标签匹配，
    改用**上下文窗口**拼接判断；并排除同名的每股收益行、净资产收益率行。
    取文档序第一个命中 —— 主要会计数据表恒在分季度表之前。
    """
    out = {}
    TARGET = "股东的扣除非经常性损益的净利"
    for y in ANNUAL:
        pages = pdf_text(f"八方股份-{y}")
        flat = [ln for p in pages[:12] for ln in p]
        numline = [bool(NUM.findall(mask_dates(ln))) for ln in flat]
        for i, ln in enumerate(flat):
            if not numline[i]:
                continue
            # 本行标签 = 「上一条数字行之后到本行之前」+「本行之后到下一条数字行之前」的纯文字
            j = i - 1
            while j >= 0 and not numline[j]:
                j -= 1
            k = i + 1
            while k < len(flat) and not numline[k]:
                k += 1
            # 标签碎片可能落在三处：数字行之前、**数字行自己的行首**（2020/2022 版式）、数字行之后
            masked = mask_dates(ln)
            own = masked[: masked.index(NUM.findall(masked)[0])]
            s = re.sub(r"\s+", "",
                       "".join(flat[j + 1 : i]) + own + "".join(flat[i + 1 : k]))
            # 🔴 判据必须是**完整标签的连续子串**：只查「扣除非经」会误中归母净利那一行
            #    —— 它后面紧跟的正是扣非行的开头碎片（2019 实证，误差 8,562,827.07 = 非经常性损益额）
            if TARGET not in s or "每股收益" in s or "净资产收益率" in s:
                continue
            out[y] = float(NUM.findall(mask_dates(ln))[0].replace(",", ""))
            break  # 主要会计数据表恒在分季度表之前，取首个
    return out


def pick(rows, items, unmatched_sink=None):
    """按别名表从解析行里取值；同一 canonical 取首个命中。

    **两趟**：第 1 趟只认「本行自带的标签」，第 2 趟才允许用「上一行 + 本行」的拼接标签兜底。
    理由：拼接标签会让一个**本身没有数值的空行**去抢下一行的数（实证：2022 年报现金流量表里
    「偿还债务支付的现金」是空行，紧跟「分配股利、利润或偿付利息 <数字>」，一趟匹配会让前者
    吃掉后者的 2.40 亿，后者反而落空、被迫兜底到次年年报）。两趟后，真正属于某行的数先被
    它自己认领，拼接标签只用来救「标签跨行断开」的行。
    """
    out, used = {}, set()
    for pass_no in (0, 1):
        for canon, pats in items:
            if canon in out:
                continue
            for idx, (labels, vals) in enumerate(rows):
                if idx in used:
                    continue
                cand = labels[:1] if pass_no == 0 else labels
                if any(re.search(p, lb) for p in pats for lb in cand):
                    out[canon] = vals
                    used.add(idx)
                    break
    if unmatched_sink is not None:
        for idx, (labels, vals) in enumerate(rows):
            if idx not in used:
                unmatched_sink.append(" | ".join(labels))
    return out


# ---------------------------------------------------------------- 各源定义

ANNUAL = ["2019", "2020", "2021", "2022", "2023", "2024", "2025"]

SEC_ANNUAL = {
    "IS": (r"^\s{6,}合并利润表\s*$", r"母公司利润表"),
    "BS": (r"^\s{6,}合并资产负债表\s*$", r"母公司资产负债表"),
    "CF": (r"^\s{6,}合并现金流量表\s*$", r"母公司现金流量表"),
}
SEC_PROSP = {
    "BS": (r"^（一）合并资产负债表\s*$", r"（二）合并利润表"),
    "IS": (r"^\s*（二）合并利润表", r"（三）合并现金流量表"),
    "CF": (r"^\s*（三）合并现金流量表", r"报告期内公司主要会计政策"),
}
ITEMS = {"IS": IS_ITEMS, "BS": BS_ITEMS, "CF": CF_ITEMS}


def collect(show_unmatched=False):
    """返回 readings[stmt][canon][year] = [(源, 值), ...]"""
    readings = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    unmatched = defaultdict(list)

    # 招股书：4 列 = 2019H1 / 2018 / 2017 / 2016（只采三个完整年度）
    pages = pdf_text("八方股份-招股说明书")
    for stmt, (sp, ep) in SEC_PROSP.items():
        rows = take_section(pages, sp, ep, 4, first_page=260)
        sink = unmatched[f"招股书-{stmt}"] if show_unmatched else None
        got = pick(rows, ITEMS[stmt], sink)
        for canon, vals in got.items():
            for j, yr in enumerate(["2019H1", "2018", "2017", "2016"]):
                if yr == "2019H1":
                    continue
                if vals[j] is not None:
                    readings[stmt][canon][yr].append(("招股书", vals[j]))

    # 年报：2 列 = 本年 / 上年
    for y in ANNUAL:
        pages = pdf_text(f"八方股份-{y}")
        for stmt, (sp, ep) in SEC_ANNUAL.items():
            rows = take_section(pages, sp, ep, 2)
            sink = unmatched[f"{y}年报-{stmt}"] if show_unmatched else None
            got = pick(rows, ITEMS[stmt], sink)
            for canon, vals in got.items():
                for j, yr in enumerate([y, str(int(y) - 1)]):
                    if vals[j] is not None:
                        readings[stmt][canon][yr].append((f"{y}年报", vals[j]))
    if show_unmatched:
        for k, v in unmatched.items():
            if v:
                print(f"\n--- 未命中别名表 [{k}] ---")
                for lab in v:
                    print(f"    {lab}")
    return readings


def reconcile(readings, tol=0.51):
    """多源交叉核 + 单源优先取数。

    ⚠️ 两条纪律：
      1. 「分部/分产品营收一律取当年年报的当年数」同理适用于三表 —— 优先级
         当年年报 > 次年年报上年列 > 招股书。
      2. **同一 (表, 年) 尽量只用一个源**：若某科目在优先源缺失而从别的源兜底，
         会把「本版数」和「重述版数」混进同一年 → 资产负债表当场不平（2022 实证：
         负债合计取 2022 年报、所有者权益合计兜底到 2023 年报重述值，差 349,964.14）。
         故兜底必须逐条显式报出，由人判断。
    返回 (data[stmt][canon][year]=值, conflicts, fallbacks)
    """
    data = defaultdict(lambda: defaultdict(dict))
    conflicts, fallbacks = [], []
    for stmt, items in readings.items():
        for canon, byyear in items.items():
            for yr, obs in byyear.items():
                vals = [v for _, v in obs]
                if max(vals) - min(vals) > tol:
                    conflicts.append((stmt, canon, yr, obs))
                order = [f"{yr}年报", f"{int(yr)+1}年报", "招股书"] if yr.isdigit() else []
                pick_src = pick_val = None
                for want in order:
                    hit = next((v for s, v in obs if s == want), None)
                    if hit is not None:
                        pick_src, pick_val = want, hit
                        break
                if pick_val is None:
                    pick_src, pick_val = obs[0]
                if pick_src != f"{yr}年报" and len(obs) >= 1:
                    fallbacks.append((stmt, canon, yr, pick_src))
                data[stmt][canon][yr] = pick_val
    return data, conflicts, fallbacks


# ---------------------------------------------------------------- 勾稽校验

def g(data, stmt, canon, yr):
    return data[stmt].get(canon, {}).get(yr)


REQUIRED = {  # (表, 科目) → 必须在所有年份非空；缺一格直接判不过
    ("BS", "资产总计"), ("BS", "负债和所有者权益总计"), ("BS", "流动资产合计"),
    ("BS", "非流动资产合计"), ("BS", "流动负债合计"), ("BS", "负债合计"),
    ("BS", "所有者权益合计"), ("BS", "归属于母公司所有者权益合计"),
    ("BS", "货币资金"), ("BS", "应收账款"), ("BS", "存货"), ("BS", "应付账款"),
    ("IS", "营业总收入"), ("IS", "营业收入"), ("IS", "营业成本"), ("IS", "营业利润"),
    ("IS", "利润总额"), ("IS", "净利润"), ("IS", "归属于母公司股东的净利润"),
    ("IS", "扣非归母净利润"), ("IS", "销售费用"), ("IS", "管理费用"), ("IS", "研发费用"),
    ("CF", "销售商品、提供劳务收到的现金"), ("CF", "购买商品、接受劳务支付的现金"),
    ("CF", "经营活动现金流入小计"), ("CF", "经营活动现金流出小计"),
    ("CF", "经营活动产生的现金流量净额"), ("CF", "投资活动产生的现金流量净额"),
    ("CF", "购建固定资产等支付的现金"),
    ("CF", "现金及现金等价物净增加额"), ("CF", "期初现金及现金等价物余额"),
    ("CF", "期末现金及现金等价物余额"),
}


def check(data, years):
    """三表勾稽 + 跨表衔接 + 必填完整性。返回 [(年, 项, 差额)]。

    🔴 两条纪律（都是被实盘打出来的）：
      1. **加总等式里的分项缺失一律当 0 参与、但合计项必须非空**。此前写成「任一为 None 就
         整条跳过」，结果 2016「非流动负债合计 3,653,400.00」因标签被空值占位符「-」粘住而
         漏读时，勾稽静默放行——缺数和平账被混为一谈。
      2. **必填清单单独查一遍**：小计行能解析出来 ≠ 明细行也解析出来了（实证：招股书
         2016/2017 的销售收现/购买商品付现等 4 行全漏，而流入流出小计正常，勾稽照样全过）。
    """
    bad = []

    def near(a, b, label, yr, tol=1.0):
        if a is None or b is None:
            bad.append((yr, f"{label}（组件缺失，无法核对）", float("nan")))
            return
        if abs(a - b) > tol:
            bad.append((yr, label, a - b))

    def z(stmt, canon, yr):
        """分项：缺失当 0（报表里的空格就是「无此项/为零」）。"""
        v = g(data, stmt, canon, yr)
        return 0.0 if v is None else v

    for yr in years:
        # —— 必填完整性 ——
        for stmt, canon in sorted(REQUIRED):
            if g(data, stmt, canon, yr) is None:
                bad.append((yr, f"必填缺失 [{stmt}] {canon}", float("nan")))

        # 资产负债表（合计项走 near 必须非空，分项走 z 缺失当 0）
        near(g(data, "BS", "资产总计", yr), g(data, "BS", "负债和所有者权益总计", yr),
             "资产总计 = 负债和所有者权益总计", yr)
        near(z("BS", "流动资产合计", yr) + z("BS", "非流动资产合计", yr),
             g(data, "BS", "资产总计", yr), "流动+非流动 = 资产总计", yr)
        near(z("BS", "流动负债合计", yr) + z("BS", "非流动负债合计", yr),
             g(data, "BS", "负债合计", yr), "流动+非流动负债 = 负债合计", yr)
        near(z("BS", "负债合计", yr) + z("BS", "所有者权益合计", yr),
             g(data, "BS", "负债和所有者权益总计", yr), "负债+权益 = 总计", yr)

        # 利润表
        near(z("IS", "营业利润", yr) + z("IS", "营业外收入", yr) - z("IS", "营业外支出", yr),
             g(data, "IS", "利润总额", yr), "营业利润+营业外收支 = 利润总额", yr)
        near(z("IS", "利润总额", yr) - z("IS", "所得税费用", yr),
             g(data, "IS", "净利润", yr), "利润总额-所得税 = 净利润", yr)
        near(z("IS", "归属于母公司股东的净利润", yr) + z("IS", "少数股东损益", yr),
             g(data, "IS", "净利润", yr), "归母+少数股东损益 = 净利润", yr)

        # 现金流量表
        net = g(data, "CF", "现金及现金等价物净增加额", yr)
        near(z("CF", "经营活动产生的现金流量净额", yr) + z("CF", "投资活动产生的现金流量净额", yr)
             + z("CF", "筹资活动产生的现金流量净额", yr) + z("CF", "汇率变动对现金的影响", yr),
             net, "经营+投资+筹资+汇率 = 净增加额", yr)
        near(z("CF", "期初现金及现金等价物余额", yr) + (net or 0),
             g(data, "CF", "期末现金及现金等价物余额", yr), "期初+净增加 = 期末", yr)
        near(z("CF", "经营活动现金流入小计", yr) - z("CF", "经营活动现金流出小计", yr),
             g(data, "CF", "经营活动产生的现金流量净额", yr), "经营流入-流出 = 经营净额", yr)
        near(z("CF", "投资活动现金流入小计", yr) - z("CF", "投资活动现金流出小计", yr),
             g(data, "CF", "投资活动产生的现金流量净额", yr), "投资流入-流出 = 投资净额", yr)
        near(z("CF", "筹资活动现金流入小计", yr) - z("CF", "筹资活动现金流出小计", yr),
             g(data, "CF", "筹资活动产生的现金流量净额", yr), "筹资流入-流出 = 筹资净额", yr)
        # 明细相加 = 小计（这一条才真正拦得住「明细漏读但小计正常」）
        near(z("CF", "销售商品、提供劳务收到的现金", yr) + z("CF", "收到的税费返还", yr)
             + z("CF", "收到其他与经营活动有关的现金", yr),
             g(data, "CF", "经营活动现金流入小计", yr), "经营流入明细和 = 流入小计", yr)
        near(z("CF", "购买商品、接受劳务支付的现金", yr) + z("CF", "支付给职工以及为职工支付的现金", yr)
             + z("CF", "支付的各项税费", yr) + z("CF", "支付其他与经营活动有关的现金", yr),
             g(data, "CF", "经营活动现金流出小计", yr), "经营流出明细和 = 流出小计", yr)

        # 跨表：期末现金 ≤ 货币资金（受限资金差额）
        cash_bs = g(data, "BS", "货币资金", yr)
        end = g(data, "CF", "期末现金及现金等价物余额", yr)
        if None not in (cash_bs, end) and end - cash_bs > 1.0:
            bad.append((yr, "期末现金 > 货币资金（异常）", end - cash_bs))
    return bad


def check_chain(data, years):
    """跨年衔接：上年期末现金 = 本年期初现金。"""
    bad = []
    for a, b in zip(years, years[1:]):
        pe = g(data, "CF", "期末现金及现金等价物余额", a)
        nb = g(data, "CF", "期初现金及现金等价物余额", b)
        if None not in (pe, nb) and abs(pe - nb) > 1.0:
            bad.append((f"{a}→{b}", "上年期末现金 = 本年期初现金", pe - nb))
    return bad


# ---------------------------------------------------------------- 写出

def write_csv(path, items, data_stmt, years, header_note):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([f"# {header_note}"])
        w.writerow(["科目"] + years)
        for canon, _ in items:
            row = data_stmt.get(canon)
            if not row:
                continue
            w.writerow([canon] + [("" if row.get(y) is None else f"{row[y]:.2f}") for y in years])
    print(f"  写出 {path.name}")


# ---------------------------------------------------------------- 分部 / 产销量
# 主营业务分产品、分地区表的版式极乱（「毛利率比上年增减」是跨 2-3 行的中文，
# 分产品名也被逐字竖排断行，见 2022 年报「电/踏/车/电/机」），位置聚类不可靠。
# 故按模板认可的「LLM 提取 + 勾稽固化」：下面是逐页人读的值，由 check_segments()
# 用**三重勾稽**机器把关 —— 分产品和 = 分地区和 = 当年年报自述的主营业务收入。
# 校验不过不写出。全部取自「当年年报的当年列」，无一处用后一年同比反推。

# 当年年报自述（元，从「报告期内，公司实现主营业务收入 X 万元」换算）
MAIN_REV = {
    "2019": 1_196_198_900.0, "2020": 1_396_799_000.0, "2021": 2_645_839_000.0,
    "2022": 2_844_543_800.0, "2023": 1_642_033_100.0, "2024": 1_352_788_000.0,
    "2025": 1_327_513_500.0,
}
# 分产品营收（元）。⚠️ 口径逐年变：2019 是六分法；2020 起归并为「电踏车电机/套件/电池」
# 三大类（中置+轮毂=电踏车电机，仪表+控制器+其他配套件=套件）；2021 起拆出「一体轮电机」；
# 2025 起「电池」并入「套件」不再单列（见 RESTATEMENTS）。
SEG_PRODUCT = {
    "2019": {"中置电机": 487_860_341.85, "轮毂电机": 300_888_081.37, "仪表": 101_106_551.55,
             "控制器": 54_987_515.46, "其他配套件": 165_690_523.64, "电池": 85_665_867.21},
    "2020": {"电踏车电机": 980_935_963.53, "套件": 338_593_138.78, "电池": 77_269_875.37},
    "2021": {"电踏车电机": 1_542_310_226.81, "一体轮电机": 475_726_545.91,
             "套件": 521_465_055.53, "电池": 106_337_194.99},
    "2022": {"电踏车电机": 1_367_488_170.16, "一体轮电机": 781_135_191.41,
             "套件": 516_029_709.63, "电池": 179_890_683.83},
    "2023": {"电踏车电机": 743_040_036.11, "一体轮电机": 499_910_813.98,
             "套件": 269_708_009.53, "电池": 129_374_204.27},
    "2024": {"电踏车电机": 591_633_271.89, "一体轮电机": 288_418_537.05,
             "套件": 337_732_525.08, "电池": 135_003_671.05},
    "2025": {"电踏车电机": 580_062_431.91, "一体轮电机": 370_534_116.79,
             "套件": 376_916_917.37},  # 套件已含电池
}
SEG_REGION = {
    "2019": {"境内": 539_419_076.71, "境外": 656_779_804.37},
    "2020": {"境内": 944_441_229.70, "境外": 452_357_747.98},
    "2021": {"境内": 1_730_869_733.51, "境外": 914_969_289.73},
    "2022": {"境内": 1_881_271_796.63, "境外": 963_271_958.40},
    "2023": {"境内": 1_099_730_931.52, "境外": 542_302_132.37},
    "2024": {"境内": 936_209_899.15, "境外": 416_578_105.92},
    "2025": {"境内": 1_055_504_650.86, "境外": 272_008_815.21},
}
# 产销量（台）：{年: {产品: (生产量, 销售量, 期末库存量)}}
VOLUME = {
    "2019": {"中置电机": (323_190, 308_622, 40_330), "轮毂电机": (695_371, 682_138, 79_437)},
    "2020": {"中置电机": (428_480, 396_811, 65_600), "轮毂电机": (974_013, 863_820, 163_393)},
    "2021": {"中置电机": (548_390, 553_330, 45_971), "轮毂电机": (1_553_055, 1_573_991, 88_734),
             "一体轮电机": (2_884_572, 2_860_492, 32_119)},
    "2022": {"中置电机": (509_849, 510_453, 48_841), "轮毂电机": (1_107_820, 1_132_272, 55_285),
             "一体轮电机": (4_248_959, 4_135_174, 113_895)},
    "2023": {"中置电机": (235_076, 247_830, 21_942), "轮毂电机": (750_427, 767_243, 31_010),
             "一体轮电机": (3_026_730, 3_055_962, 40_848)},
    "2024": {"中置电机": (174_056, 167_839, 21_721), "轮毂电机": (878_660, 857_442, 44_014),
             "一体轮电机": (1_962_328, 1_899_594, 40_054)},
    "2025": {"中置电机": (179_081, 170_421, 23_432), "轮毂电机": (1_067_338, 1_032_398, 64_474),
             "一体轮电机": (2_512_260, 2_513_825, 23_832)},
}

# 主营业务成本（元，年报自述）
MAIN_COST = {
    "2019": 684_994_700.0, "2020": 792_592_600.0, "2021": 1_740_311_900.0,
    "2022": 1_958_856_600.0, "2023": 1_171_414_100.0, "2024": 1_023_966_400.0,
    "2025": 999_564_500.0,
}
# 分产品营业成本（元）。「运费(成本)」只有成本无收入，是主营业务成本的组成项。
SEG_PRODUCT_COST = {
    "2019": {"中置电机": 236_932_637.10, "轮毂电机": 177_188_224.94, "仪表": 58_285_773.31,
             "控制器": 33_834_154.94, "其他配套件": 101_528_066.73, "电池": 77_225_853.40},
    "2020": {"电踏车电机": 489_754_478.99, "套件": 232_633_084.24, "电池": 56_788_548.57,
             "运费": 13_416_507.07},
    "2021": {"电踏车电机": 808_715_013.84, "一体轮电机": 456_242_416.45, "套件": 364_460_236.45,
             "电池": 88_350_333.66, "运费": 22_543_898.19},
    "2022": {"电踏车电机": 700_101_998.98, "一体轮电机": 739_665_056.85, "套件": 350_864_093.90,
             "电池": 148_119_836.40, "运费": 20_105_595.40},
    "2023": {"电踏车电机": 383_864_714.60, "一体轮电机": 496_286_778.78, "套件": 176_517_066.27,
             "电池": 99_093_493.45, "运费": 15_652_073.58},
    "2024": {"电踏车电机": 347_302_922.22, "一体轮电机": 294_902_922.73, "套件": 250_583_494.83,
             "电池": 117_380_953.87, "运费": 13_796_120.89},
    "2025": {"电踏车电机": 373_893_523.61, "一体轮电机": 356_505_542.17, "套件": 255_814_165.71,
             "运费": 13_351_303.35},
}
SEG_REGION_COST = {
    "2019": {"境内": 303_673_760.40, "境外": 381_320_950.02},
    "2020": {"境内": 544_286_898.47, "境外": 234_889_213.33, "运费": 13_416_507.07},
    "2021": {"境内": 1_199_466_400.34, "境外": 518_301_600.06, "运费": 22_543_898.19},
    "2022": {"境内": 1_356_702_757.76, "境外": 582_048_228.37, "运费": 20_105_595.40},
    "2023": {"境内": 842_375_697.30, "境外": 313_386_355.80, "运费": 15_652_073.58},
    "2024": {"境内": 718_705_130.93, "境外": 291_465_162.72, "运费": 13_796_120.89},
    "2025": {"境内": 792_957_732.71, "境外": 193_255_498.78, "运费": 13_351_303.35},
}

SEG_YEARS = [str(y) for y in range(2019, 2026)]


def check_segments():
    """四重勾稽：收入两路 + 成本两路，都要对上年报自述的主营业务收入/成本。

    ⚠️ 本库教训（贵州茅台 2021）：只跑「分产品」一路而漏跑「分渠道」一路，
    渠道两行整体左移一列、连续 6 年没被发现。**三路都要跑，只通一路 = 没跑。**
    """
    bad = []
    for y in SEG_YEARS:
        pr, rr, mr = sum(SEG_PRODUCT[y].values()), sum(SEG_REGION[y].values()), MAIN_REV[y]
        pc, rc, mc = (sum(SEG_PRODUCT_COST[y].values()), sum(SEG_REGION_COST[y].values()),
                      MAIN_COST[y])
        if abs(pr - rr) > 1.0:
            bad.append((y, "分产品收入和 = 分地区收入和", pr - rr))
        if abs(pr - mr) / mr > 0.001:
            bad.append((y, "分产品收入和 = 主营业务收入(年报自述)", pr - mr))
        if abs(pc - rc) > 1.0:
            bad.append((y, "分产品成本和 = 分地区成本和", pc - rc))
        if abs(pc - mc) / mc > 0.001:
            bad.append((y, "分产品成本和 = 主营业务成本(年报自述)", pc - mc))
    return bad


# 重述 / 口径变更台账（全部有一手出处，见 README 的「复核记录」）
RESTATEMENTS = [
    ("2022", "递延所得税资产(合并)", 20_650_771.53, 20_300_807.39,
     "《企业会计准则解释第16号》单项交易递延所得税不适用初始确认豁免", "2023年报 重要会计政策变更"),
    ("2022", "未分配利润(合并)", 1_357_151_079.61, 1_356_798_174.21,
     "同上(累计影响)", "2023年报 重要会计政策变更"),
    ("2022", "所得税费用(合并)", 78_784_786.11, 78_821_768.89,
     "同上", "2023年报 重要会计政策变更"),
    ("2022", "净利润=归母净利(合并)", 512_130_233.66, 512_093_250.88,
     "同上", "2023年报 重要会计政策变更"),
    ("2022", "基本每股收益(元/股)", 4.27, 3.05,
     "2023年每10股转增4股，追溯调整股数(4.27÷1.4=3.05)", "2023年报 主要会计数据"),
    ("2023", "销售费用", 117_695_466.20, 77_840_743.59,
     "《解释第18号》保证类质量保证预计负债改计入营业成本", "2024年报 重要会计政策变更"),
    ("2023", "营业成本", 1_172_162_102.22, 1_212_016_824.83,
     "同上(与销售费用同额对调 39,854,722.61)", "2024年报 重要会计政策变更"),
    ("2025", "分产品「套件」口径", 337_732_525.08, 376_916_917.37,
     "2025年报「电池」不再单列、并入「套件」；可比口径同比 -20.27%（表面 +11.60% 为口径造成）",
     "2025年报 主营业务分产品情况(算术反证)"),
]


def build_interim():
    """2026 中报三表 → *-H1.csv。

    ⚠️ 列语义两轴不同，**不可混读**：
       资产负债表 = 2026-06-30 / 2025-12-31（时点：期末 vs 上年度末）
       利润表·现金流量表 = 2026 年 1-6 月 / 2025 年 1-6 月（期间：半年度累计，非单季、非全年）
    """
    pages = pdf_text("八方股份-2026-Q2")
    out, checks = {}, []
    colmap = {"BS": ["2026-06-30", "2025-12-31"], "IS": ["2026H1", "2025H1"],
              "CF": ["2026H1", "2025H1"]}
    for stmt, (sp, ep) in SEC_ANNUAL.items():
        rows = take_section(pages, sp, ep, 2)
        got = pick(rows, ITEMS[stmt])
        out[stmt] = {c: dict(zip(colmap[stmt], v)) for c, v in got.items()}

    def g(stmt, canon, col):
        return out[stmt].get(canon, {}).get(col)

    for col in ("2026H1", "2025H1"):
        a, b = g("IS", "利润总额", col), g("IS", "净利润", col)
        t = g("IS", "所得税费用", col)
        if None not in (a, b) and abs(a - (t or 0) - b) > 1.0:
            checks.append((col, "利润总额-所得税=净利润", a - (t or 0) - b))
        o, i, f = (g("CF", k, col) for k in (
            "经营活动产生的现金流量净额", "投资活动产生的现金流量净额", "筹资活动产生的现金流量净额"))
        fx, net = g("CF", "汇率变动对现金的影响", col), g("CF", "现金及现金等价物净增加额", col)
        if None not in (o, i, net) and abs(o + i + (f or 0) + (fx or 0) - net) > 1.0:
            checks.append((col, "经营+投资+筹资+汇率=净增加额", o + i + (f or 0) + (fx or 0) - net))
    for col in ("2026-06-30", "2025-12-31"):
        ta, tl, te = (g("BS", k, col) for k in ("资产总计", "负债合计", "所有者权益合计"))
        if None not in (ta, tl, te) and abs(tl + te - ta) > 1.0:
            checks.append((col, "负债+权益=资产总计", tl + te - ta))
    # 跨报告衔接：中报的「上年度末」列必须等于 2025 年报的 2025 年末
    return out, checks


def write_interim(out):
    note_map = {
        "IS": ("利润表-H1.csv", "期间=半年度累计(1-6月)，非单季、非全年"),
        "BS": ("资产负债表-H1.csv", "时点=2026-06-30 期末 vs 2025-12-31 上年度末"),
        "CF": ("现金流量表-H1.csv", "期间=半年度累计(1-6月)"),
    }
    cols = {"BS": ["2026-06-30", "2025-12-31"], "IS": ["2026H1", "2025H1"],
            "CF": ["2026H1", "2025H1"]}
    items = {"IS": IS_ITEMS, "BS": BS_ITEMS, "CF": CF_ITEMS}
    for stmt, (fn, sem) in note_map.items():
        p = OUT_DIR / fn
        with open(p, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([f"# 单位：{UNIT}；来源：report/八方股份/八方股份-2026-Q2.pdf（未经审计）；{sem}"])
            w.writerow(["科目"] + cols[stmt])
            for canon, _ in items[stmt]:
                row = out[stmt].get(canon)
                if not row:
                    continue
                w.writerow([canon] + [("" if row.get(c) is None else f"{row[c]:.2f}")
                                      for c in cols[stmt]])
        print(f"  写出 {p.name}")


def write_segments():
    """分部营收.csv（收入/成本/毛利率 × 分产品·分地区）+ 产销量.csv"""
    p = OUT_DIR / "分部营收.csv"
    with open(p, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([f"# 单位：{UNIT}（毛利率为 %）；来源：各年年报「主营业务分产品/分地区情况」当年列；"
                    f"四重勾稽通过（分产品收入和=分地区收入和=主营业务收入；成本同理）。"
                    f"⚠️ 分产品口径逐年变动，2025 起「电池」并入「套件」，跨年比较见 重述与口径变更.csv"])
        w.writerow(["科目"] + SEG_YEARS)
        for title, rev_map, cost_map in (("分产品", SEG_PRODUCT, SEG_PRODUCT_COST),
                                         ("分地区", SEG_REGION, SEG_REGION_COST)):
            names = []
            for y in SEG_YEARS:
                for k in list(rev_map[y]) + list(cost_map[y]):
                    if k not in names:
                        names.append(k)
            for k in names:
                w.writerow([f"{title}-{k}-营业收入"] +
                           [f"{rev_map[y][k]:.2f}" if k in rev_map[y] else "" for y in SEG_YEARS])
                w.writerow([f"{title}-{k}-营业成本"] +
                           [f"{cost_map[y][k]:.2f}" if k in cost_map[y] else "" for y in SEG_YEARS])
                gm = []
                for y in SEG_YEARS:
                    r, c = rev_map[y].get(k), cost_map[y].get(k)
                    gm.append(f"{(r - c) / r * 100:.2f}" if r and c is not None and r else "")
                w.writerow([f"{title}-{k}-毛利率(%)"] + gm)
        w.writerow(["主营业务收入(年报自述)"] + [f"{MAIN_REV[y]:.2f}" for y in SEG_YEARS])
        w.writerow(["主营业务成本(年报自述)"] + [f"{MAIN_COST[y]:.2f}" for y in SEG_YEARS])
    print(f"  写出 {p.name}")

    p = OUT_DIR / "产销量.csv"
    with open(p, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["# 单位：台；来源：各年年报「产销量情况分析表」当年列。"
                    "一体轮电机 2021 年起单独披露；2019-2020 未单列"])
        w.writerow(["科目"] + SEG_YEARS)
        names = []
        for y in SEG_YEARS:
            for k in VOLUME[y]:
                if k not in names:
                    names.append(k)
        for k in names:
            for i, tag in enumerate(("生产量", "销售量", "期末库存量")):
                w.writerow([f"{k}-{tag}"] +
                           [str(VOLUME[y][k][i]) if k in VOLUME[y] else "" for y in SEG_YEARS])
    print(f"  写出 {p.name}")


# 本年度**宣派**现金分红总额（元）。与现金流量表的「分配股利…支付的现金」（**已付**口径）
# 差一整年 —— 本库实盘教训（泡泡玛特 8.5% vs 25%，姿态结论反转）要求两口径分列、不得混用。
# 本公司全程无有息负债，故「已付」几乎不含付息，次年已付 ≈ 本年度宣派（下表逐年验证吻合）。
DIV_DECLARED = {
    "2019": (120_000_000.00, "每10股派10元 × 120,000,000 股【源·2019年报利润分配预案】；2020 年实付 120,000,000.00 精确吻合"),
    "2020": (240_629_910.00, "每10股派20元 × 120,314,955 股【推·2020年报预案×年末股本】；2021 年实付 240,963,742.73（差异来自股权登记日股本口径）"),
    "2021": (240_468_252.00, "【推·按 2022 年实付倒推】每10股派20元、扣回购专户差异化分红"),
    "2022": (239_804_222.00, "【源·2025-04-30《2024年度利润分配方案公告》最近三年分红表】；2023 年实付 239,406,102.00"),
    "2023": (167_584_271.00, "【源·2024-06-25《关于调整2023年度利润分配方案现金分红总额…的公告》】；2024 年实付同额"),
    "2024": (23_461_797.90, "【源·2025-04-30《2024年度利润分配方案公告》】；2025 年实付同额"),
    "2025": (35_192_696.85, "【源·2026-04-29《2025年度利润分配方案公告》】；2026H1 实付同额"),
}


def write_dividends(data, years):
    p = OUT_DIR / "分红.csv"
    with open(p, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["# 单位：元。🔴 两个口径**差一整年**，跨年比较前先对齐："
                    "「本年度宣派」= 该财政年度利润分配方案的分红总额（决策口径）；"
                    "「当年实付」= 现金流量表「分配股利、利润或偿付利息支付的现金」（含付息，本公司无有息负债故≈纯分红），"
                    "实际支付发生在宣派年度的**次年**。"])
        w.writerow(["科目"] + years)
        w.writerow(["本年度宣派现金分红总额"] +
                   [f"{DIV_DECLARED[y][0]:.2f}" if y in DIV_DECLARED else "" for y in years])
        par = data["IS"].get("归属于母公司股东的净利润", {})
        w.writerow(["宣派分红率(占当年归母净利,%)"] +
                   [f"{DIV_DECLARED[y][0] / par[y] * 100:.2f}"
                    if y in DIV_DECLARED and par.get(y) else "" for y in years])
        w.writerow(["当年实付现金分红(现金流量表口径)"] +
                   [f"{v:.2f}" if (v := data['CF'].get('分配股利、利润或偿付利息支付的现金', {}).get(y))
                    else "" for y in years])
        w.writerow(["当年实付对应的财政年度"] +
                   [str(int(y) - 1) if int(y) >= 2017 else "" for y in years])
        w.writerow([])
        w.writerow(["# 上市以来股东回报 vs 股权融资（单位：元）"])
        cum_div = sum(v for v, _ in DIV_DECLARED.values())
        IPO_NET = 1_237_580_200.00      # IPO 募集资金净额 123,758.02 万元【源·2019年报 主要会计数据说明】
        BUYBACK_CANCEL = 67_339_829.00  # 2022 年回购 395,024 股、2025-07-16 注销【源·2026-04-29 分红公告注】
        w.writerow(["累计宣派现金分红(2019-2025年度)", f"{cum_div:.2f}"])
        w.writerow(["累计回购并注销金额", f"{BUYBACK_CANCEL:.2f}"])
        w.writerow(["累计股东回报合计", f"{cum_div + BUYBACK_CANCEL:.2f}"])
        w.writerow(["累计股权融资净额(仅 IPO)", f"{IPO_NET:.2f}"])
        w.writerow(["股东回报 ÷ 股权融资(%)", f"{(cum_div + BUYBACK_CANCEL) / IPO_NET * 100:.2f}"])
        w.writerow(["# 注：上市至今仅 IPO 一次股权融资。2021 年度非公开发行预案虽于 2022-05-19 获证监会核准批复，"
                    "但公司于 2023-04-28 公告终止，未实施【源·cninfo 公告 id=1216666782】。"])
        w.writerow([])
        w.writerow(["# 宣派金额出处逐年备注"])
        for y in years:
            if y in DIV_DECLARED:
                w.writerow([y, DIV_DECLARED[y][1]])
    print(f"  写出 {p.name}")


def write_restatements():
    p = OUT_DIR / "重述与口径变更.csv"
    with open(p, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["# 三表 CSV 一律存「当年年报的当年列」(as-reported)。本表记录被后续年报"
                    "追溯重述/改口径的格，跨年比较时按本表调整。单位同三表（元）。"])
        w.writerow(["会计年度", "项目", "当年年报原值", "后续年报重述值", "原因", "一手出处"])
        for row in RESTATEMENTS:
            w.writerow(list(row))
    print(f"  写出 {p.name}")


def write_ratios(data, years):
    """财务比率.csv = scripts/derived.py 通用底 + 本公司定制层。"""
    sys.path.insert(0, str(ROOT / "scripts"))
    import derived  # noqa: E402

    def tab(stmt, items):
        return {c: [data[stmt].get(c, {}).get(y) for y in years] for c, _ in items
                if c in data[stmt]}

    common, unmatched = derived.compute_common_ratios(
        tab("IS", IS_ITEMS), tab("BS", BS_ITEMS), tab("CF", CF_ITEMS))
    rows = [(n, v) for n, v, _ in common]
    if unmatched:
        print(f"  ⚠️ derived 未匹配科目: {'、'.join(sorted(set(unmatched)))}")

    # ---- 定制层（制造 + 出口 + 类现金重 的公司特有）----
    def col(y, f):
        return f(y) if y in SEG_YEARS else None

    def safe(a, b, mul=1.0):
        return None if (a is None or not b) else a / b * mul

    rows.append(("境外营收占比(%)", [col(y, lambda y: safe(
        SEG_REGION[y]["境外"], SEG_REGION[y]["境内"] + SEG_REGION[y]["境外"], 100)) for y in years]))
    rows.append(("电踏车电机销量(万台)", [col(y, lambda y: (
        VOLUME[y].get("中置电机", (0, 0, 0))[1] + VOLUME[y].get("轮毂电机", (0, 0, 0))[1]) / 1e4)
        for y in years]))
    rows.append(("电踏车电机均价(元/台)", [col(y, lambda y: safe(
        SEG_PRODUCT[y].get("电踏车电机",
                           SEG_PRODUCT[y].get("中置电机", 0) + SEG_PRODUCT[y].get("轮毂电机", 0)),
        VOLUME[y].get("中置电机", (0, 0, 0))[1] + VOLUME[y].get("轮毂电机", (0, 0, 0))[1]))
        for y in years]))
    rows.append(("一体轮电机销量(万台)", [col(y, lambda y: (
        VOLUME[y]["一体轮电机"][1] / 1e4) if "一体轮电机" in VOLUME[y] else None) for y in years]))
    rows.append(("一体轮电机均价(元/台)", [col(y, lambda y: safe(
        SEG_PRODUCT[y].get("一体轮电机"),
        VOLUME[y]["一体轮电机"][1] if "一体轮电机" in VOLUME[y] else None)) for y in years]))
    rows.append(("一体轮电机毛利率(%)", [col(y, lambda y: (
        None if "一体轮电机" not in SEG_PRODUCT[y] else
        (SEG_PRODUCT[y]["一体轮电机"] - SEG_PRODUCT_COST[y]["一体轮电机"])
        / SEG_PRODUCT[y]["一体轮电机"] * 100)) for y in years]))
    rows.append(("电踏车电机毛利率(%)", [col(y, lambda y: (
        None if "电踏车电机" not in SEG_PRODUCT[y] else
        (SEG_PRODUCT[y]["电踏车电机"] - SEG_PRODUCT_COST[y]["电踏车电机"])
        / SEG_PRODUCT[y]["电踏车电机"] * 100)) for y in years]))

    # 类现金（货币+交易性金融资产+债权投资）占总资产 —— 本公司资产结构的主线
    cashish, ta = [], data["BS"].get("资产总计", {})
    for y in years:
        s = 0.0
        ok = False
        for k in ("货币资金", "交易性金融资产", "债权投资"):
            v = data["BS"].get(k, {}).get(y)
            if v is not None:
                s += v
                ok = True
        cashish.append(safe(s, ta.get(y), 100) if ok else None)
    rows.append(("类现金(货币+交易性金融资产+债权投资)占总资产(%)", cashish))

    ibd = []
    for y in years:
        s = 0.0
        for k in ("短期借款", "长期借款", "一年内到期的非流动负债", "应付债券"):
            v = data["BS"].get(k, {}).get(y)
            if v is not None:
                s += v
        ibd.append(safe(s, ta.get(y), 100))
    rows.append(("有息负债占总资产(%)", ibd))

    p = OUT_DIR / "财务比率.csv"
    with open(p, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["科目"] + years)
        for name, vals in rows:
            w.writerow([name] + [("" if v is None else f"{v:.2f}") for v in vals])
    print(f"  写出 {p.name}（通用底 {len(common)} 项 + 定制层 {len(rows) - len(common)} 项）")


def main():
    show_unmatched = "--unmatched" in sys.argv
    check_only = "--check" in sys.argv

    print("== 解析一手 PDF ==")
    readings = collect(show_unmatched)

    print("\n== 多源交叉核 ==")
    data, conflicts, fallbacks = reconcile(readings)
    years = [str(y) for y in range(2016, 2026)]
    if conflicts:
        print(f"  ⚠️ {len(conflicts)} 处多源读数不一致（重述 or 解析错，逐条看）：")
        for stmt, canon, yr, obs in conflicts:
            detail = " / ".join(f"{s}:{v:,.2f}" for s, v in obs)
            print(f"    [{stmt}] {canon} @{yr}  {detail}")
    else:
        print("  ✅ 无冲突（所有重叠年份多源读数一致）")

    # 2016-2018 只有招股书一个源、2025 只有 2025 年报一个源 —— 这类「当然兜底」不必报。
    noisy = [f for f in fallbacks if f[2] in {str(y) for y in range(2019, 2026)}]
    if noisy:
        print(f"  ⚠️ {len(noisy)} 处未取到「当年年报当年列」，已兜底（混源风险，逐条确认）：")
        for stmt, canon, yr, src in noisy:
            print(f"    [{stmt}] {canon} @{yr} ← {src}")
    else:
        print("  ✅ 2019-2025 全部取自「当年年报的当年列」，无混源")

    # ---- 老式利润表（2016/2017 招股书）没有「营业总收入/归母净利」两行，补齐 ----
    # 依据：招股书「合并利润表主要数据」明列 归属于母公司所有者的净利润 = 净利润
    #      （2016 8,933.91万 / 2017 5,332.97万），且少数股东权益全程为 0。
    for yr in ("2016", "2017"):
        if data["IS"]["营业收入"].get(yr) is None:
            data["IS"]["营业收入"][yr] = data["IS"]["营业总收入"].get(yr)
        if data["IS"]["归属于母公司股东的净利润"].get(yr) is None:
            data["IS"]["归属于母公司股东的净利润"][yr] = data["IS"]["净利润"].get(yr)

    # ---- 扣非归母：两条独立路径对撞 ----
    print("\n== 扣非归母（两路对撞）==")
    nr = nonrecurring()
    kf_disc = disclosed_kf()
    kf_bad = []
    for yr in years:
        obs = nr.get(yr, [])
        if not obs:
            continue
        vals = [v for _, v in obs]
        if max(vals) - min(vals) > 0.51:
            kf_bad.append((yr, "非经常性损益合计 多源打架", max(vals) - min(vals)))
        total = next((v for s, v in obs if s == f"{yr}年报"), obs[0][1])
        parent = data["IS"]["归属于母公司股东的净利润"].get(yr)
        if parent is None:
            continue
        data["IS"]["非经常性损益合计"][yr] = total
        data["IS"]["扣非归母净利润"][yr] = parent - total
        if yr in kf_disc and abs((parent - total) - kf_disc[yr]) > 1.0:
            kf_bad.append((yr, "路径①(归母−非经常) ≠ 路径②(年报披露扣非)",
                           (parent - total) - kf_disc[yr]))
    for yr in years:
        got = data["IS"]["扣非归母净利润"].get(yr)
        src = len(nr.get(yr, []))
        chk = "✓对撞" if yr in kf_disc else ("—" if yr < "2019" else "?")
        print(f"  {yr}: 扣非={got:>18,.2f}  独立源={src}  年报披露值{chk}" if got else f"  {yr}: ⏳")
    if kf_bad:
        print("  ❌ 扣非校验不过：")
        for a, b, c in kf_bad:
            print(f"    {a} {b} 差={c:,.2f}")
    else:
        print("  ✅ 两路一致 + 多源一致")

    print("\n== 中期（2026 中报）==")
    interim, int_bad = build_interim()
    # 跨报告衔接：中报「上年度末」列 = 2025 年报年末
    for canon in ("资产总计", "归属于母公司所有者权益合计", "货币资金", "存货", "应收账款"):
        a = interim["BS"].get(canon, {}).get("2025-12-31")
        b = data["BS"].get(canon, {}).get("2025")
        if None not in (a, b) and abs(a - b) > 1.0:
            int_bad.append(("2025-12-31", f"中报上年度末[{canon}] = 2025年报年末", a - b))
    print(f"  中期勾稽 + 跨报告衔接：{'❌' if int_bad else '✅ 全过'}")

    print("\n== 勾稽校验 ==")
    bad = check(data, years) + check_chain(data, years) + kf_bad + int_bad
    seg_bad = check_segments()
    if seg_bad:
        bad += seg_bad
    print(f"  分部三重勾稽（分产品和=分地区和=主营业务收入）：{'❌' if seg_bad else '✅ 7 年全过'}")
    if bad:
        print(f"  ❌ {len(bad)} 处不平：")
        for yr, label, diff in bad:
            print(f"    {yr}  {label}  差额={diff:,.2f}")
    else:
        print("  ✅ 全部通过")

    for stmt in ("IS", "BS", "CF"):
        ys = sorted({y for c in data[stmt].values() for y in c})
        print(f"  {stmt} 覆盖年份: {ys}")

    if bad:
        sys.exit("\n[ABORT] 校验不过 → 不写出 CSV（先回查 PDF）")
    if check_only:
        print("\n(--check：不写文件)")
        return

    print("\n== 写出 CSV ==")
    note = (f"单位：{UNIT}；来源：report/八方股份/ 招股说明书(2016-2018) + 历年年报(2019-2025) "
            f"逐行解析；空=该期财报无此科目；数值一律取「当年年报的当年列」(as-reported)，"
            f"被后续年报重述的格见 重述与口径变更.csv")
    write_csv(OUT_DIR / "利润表.csv", IS_ITEMS, data["IS"], years, note)
    write_csv(OUT_DIR / "资产负债表.csv", BS_ITEMS, data["BS"], years, note)
    write_csv(OUT_DIR / "现金流量表.csv", CF_ITEMS, data["CF"], years, note)
    write_interim(interim)
    write_segments()
    write_dividends(data, years)
    write_restatements()
    write_ratios(data, years)


if __name__ == "__main__":
    main()
