#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""361度 财务比率构建器 —— 通用底（`scripts/derived.py`）+ 361度 定制层。

与 `_build_from_pdf.py` 分文件，是因为两件事的变更节奏不同：
三表别名层随新年份科目改名而增补，比率定义则跨年稳定。

由 `_build_from_pdf.py` 在三表勾稽通过后调用；单独跑无意义（比率必须建立在
已校验的三表之上）。
"""
import csv
import os
import sys

from _build_from_pdf import PERIODS, SOURCE_OF  # noqa: F401  (SOURCE_OF 供血缘留痕)

HERE = os.path.dirname(os.path.abspath(__file__))


def _s(data, st, item):
    """取一条按 PERIODS 排好的序列。"""
    d = data[st].get(item, {})
    return [d.get(p) for p in PERIODS]


def _add(*series):
    out = []
    for i in range(len(PERIODS)):
        vals = [s[i] for s in series if s[i] is not None]
        out.append(sum(vals) if vals else None)
    return out


def build_ratios(data):
    """通用底（`scripts/derived.py`）+ 361度 定制层 → 财务比率.csv。

    把港股科目名**映射**成 derived 别名层已识别的通用名再调用 ——
    适配放在自己这一侧，不动被多家公司共用的引擎。

    🔴 **不能走 `derived.py` 的 CLI 路径**：它按表头解析年份列，只认 `2025` 与
       `FY2026/3` 两种写法，本库的 `2011H2` 会被整列丢掉 → 行值与年份列错位且静默。
       故这里按架构推荐**传 dict**（纯位置对齐，不碰表头）。
    """
    sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "scripts"))
    import derived

    # 应收「合并口径」：三代列报（见 BS_SPEC 注释）拼成同一条连续序列，
    # 否则 FY2010→FY2011 会凭空掉一大截（那只是拆行，不是回款恶化）
    ar = _add(_s(data, "bs", "贸易及其他应收款项-合并口径"),
              _s(data, "bs", "应收账款及应收票据-合并口径"),
              _s(data, "bs", "应收账款"), _s(data, "bs", "应收票据"),
              _s(data, "bs", "按金预付款项及其他应收款项"))
    borrow = _add(_s(data, "bs", "银行贷款-流动"), _s(data, "bs", "银行贷款-非流动"),
                  _s(data, "bs", "其他贷款-流动"),
                  _s(data, "bs", "计息借贷-流动"), _s(data, "bs", "计息借贷-非流动"),
                  _s(data, "bs", "可换股债券-流动"), _s(data, "bs", "可换股债券-非流动"))
    cashlike = _add(_s(data, "bs", "现金及现金等价物"), _s(data, "bs", "银行存款"),
                    _s(data, "bs", "已抵押银行存款"))

    PL = {
        "营业收入": _s(data, "is", "营业额"),
        "营业成本": _s(data, "is", "销售成本"),
        "毛利": _s(data, "is", "毛利"),
        "销售费用": _s(data, "is", "销售及分销开支"),
        "管理费用": _s(data, "is", "行政开支"),
        "净利润": _s(data, "is", "本期溢利"),
        "归母净利润": _s(data, "is", "股东应占溢利"),
        "利润总额": _s(data, "is", "除税前溢利"),
        "所得税费用": _s(data, "is", "所得税"),
    }
    BS_ = {
        "应收账款": ar,
        "存货": _s(data, "bs", "存货"),
        "应付账款": _s(data, "bs", "贸易及其他应付款项"),
        "固定资产": _s(data, "bs", "物业厂房及设备"),
        "资产总计": _s(data, "bs", "资产总值"),
        "非流动资产合计": _s(data, "bs", "非流动资产合计"),
        "流动资产合计": _s(data, "bs", "流动资产合计"),
        "权益总额": _s(data, "bs", "资产净值"),
        "归母权益": _s(data, "bs", "股东应占权益"),
        "现金及现金等价物": _s(data, "bs", "现金及现金等价物"),
        "定期存款-流动": _s(data, "bs", "银行存款"),
        "质押存款-流动": _s(data, "bs", "已抵押银行存款"),
    }
    CF_ = {
        "经营活动现金流量净额": _s(data, "cf", "经营活动现金净额"),
        "购建固定资产": _s(data, "cf", "购建物业厂房设备"),
        "已付股息": _s(data, "cf", "已付股息"),
    }
    common, unmatched = derived.compute_common_ratios(PL, BS_, CF_)
    rows = [(n, v) for n, v, _f in common]

    rev, ta = PL["营业收入"], BS_["资产总计"]
    op = _s(data, "is", "经营溢利")
    fin = _s(data, "is", "财务成本")
    oneoff = _add(_s(data, "is", "可换股债券衍生工具公允值变动"),
                  _s(data, "is", "购回可换股债券损益"),
                  _s(data, "is", "购回优先票据损益"))
    parent = PL["归母净利润"]

    def ratio(a, b):
        return [None if (a[i] is None or not b[i]) else a[i] / b[i]
                for i in range(len(PERIODS))]

    # 港股无「扣非」线。361度 的非经常大项是 2012-2021 年的可换股债券/优先票据
    # 公允值变动与购回损益 —— 按同一定义回算历年「经调整股东应占溢利」（税前口径近似，
    # 因该类利得/损失在公司披露中未单独计税）。用于替代扣非做趋势比较。
    adj = [None if parent[i] is None else parent[i] - (oneoff[i] or 0)
           for i in range(len(PERIODS))]
    netcash = [None if (cashlike[i] is None and borrow[i] is None)
               else (cashlike[i] or 0) - (borrow[i] or 0) for i in range(len(PERIODS))]

    rows += [
        ("经营溢利率 Operating margin", ratio(op, rev)),
        ("财务成本/营收 Finance cost/Revenue", ratio([None if v is None else abs(v) for v in fin], rev)),
        ("经调整股东应占溢利(剔可转债及票据损益)(百万元)", adj),
        ("经调整股东应占溢利率", ratio(adj, rev)),
        ("有息负债(百万元)", borrow),
        ("有息负债/总资产 Borrowings/TA", ratio(borrow, ta)),
        ("净现金 Net cash(百万元)", netcash),
        ("净现金/总资产 Net cash/TA", ratio(netcash, ta)),
    ]
    rows = [(n, v) for n, v in rows if any(x is not None for x in v)]

    path = os.path.join(HERE, "财务比率.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["# 财务比率（361度 01361.HK）· 派生自本目录三表，非财报直接披露"])
        w.writerow(["# 通用底 = scripts/derived.py compute_common_ratios()；其余为 361度 定制层"])
        w.writerow(["# 比率为小数（0.62 = 62%）；天数为天；标(百万元)者为金额"])
        w.writerow(["# 🔴 2011H2 只有 6 个月：所有「流量÷存量」指标（ROE / 周转天数 / 现金含量分母）"
                    "在该列天然只有半年强度，**不可与 12 个月期直接比**"])
        w.writerow(["# ⚠️ 应收口径：FY2006-FY2010 合并行 / FY2011 两行 / 2011H2 起三行，"
                    "已合并成连续口径（含按金预付款项），与单看「贸易应收款项」不同"])
        w.writerow(["# ⚠️ 分红率分母用「已付股息」(现金流量表·期内实付)，与「宣派」口径有跨年时间差"])
        w.writerow(["指标"] + PERIODS)
        for name, vals in rows:
            w.writerow([name] + ["" if v is None else f"{v:.4f}".rstrip("0").rstrip(".")
                                 for v in vals])
    print(f"  ✅ 财务比率.csv（{len(rows)} 指标 × {len(PERIODS)} 期）")
    if unmatched:
        print(f"  ⚠️ derived 未匹配科目：{sorted(set(unmatched))}")


