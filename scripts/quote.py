#!/usr/bin/env python3
"""区间行情查询 —— 给 backtest-call 用，把大V的 call 接上真实涨跌。

用法:
    python3 scripts/quote.py <代码> <起始日> <结束日>

示例:
    python3 scripts/quote.py 600519 2018-12-28 2021-12-31   # A股 贵州茅台
    python3 scripts/quote.py 00700  2017-01-01 2017-12-31   # 港股 腾讯
    python3 scripts/quote.py sh000300 2019-01-01 2019-12-31 # 沪深300 指数

只取行情、算区间首尾收盘价与涨跌幅（A股前复权），不下任何"准不准"的判断 ——
✓/✗ 由 backtest-call 结合方向 + 验证窗口判定。

依赖: pip install akshare
"""
import os
import sys
from datetime import datetime

# 自举：若当前解释器没有 akshare，但同目录有 .venv，则用 venv 的 python 重跑
# 这样无论是否手动激活 venv，`python3 scripts/quote.py ...` 都能直接用
def _bootstrap_venv():
    try:
        import akshare  # noqa: F401
        return
    except ImportError:
        pass
    # 已经重跑过一次还是没有 → 别再 exec，避免死循环（让 load_akshare 给出友好提示）
    if os.environ.get("_QUOTE_VENV_REEXEC"):
        return
    venv_py = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           ".venv", "bin", "python")
    # 注意：venv 的 python 可能和系统 python3 指向同一个二进制，
    # 但 venv 有独立 site-packages（靠 pyvenv.cfg），所以不能用二进制路径判重，用环境变量哨兵
    if os.path.exists(venv_py):
        os.environ["_QUOTE_VENV_REEXEC"] = "1"
        os.execv(venv_py, [venv_py, os.path.abspath(__file__), *sys.argv[1:]])


_bootstrap_venv()


def fail(msg, code=1):
    print(f"[quote] {msg}", file=sys.stderr)
    sys.exit(code)


def parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        fail(f"日期格式应为 YYYY-MM-DD，收到: {s}")


def classify(ticker):
    """返回 (kind, normalized_symbol)。kind ∈ a / hk / index。"""
    t = ticker.strip().lower()
    if t.startswith(("sh", "sz")) and t[2:].isdigit():
        return "index", t
    digits = t.lstrip("0") or "0"
    if t.isdigit() and len(t) <= 5 and not (len(t) == 6):
        # 5 位及以下纯数字按港股处理（腾讯 00700 / 0700）
        return "hk", t.zfill(5)
    if t.isdigit() and len(t) == 6:
        return "a", t
    fail(f"无法识别代码类型: {ticker}（A股填 6 位如 600519，港股填 5 位如 00700，指数填 sh000300）")


def load_akshare():
    try:
        import akshare as ak
        return ak
    except ImportError:
        fail("未安装 akshare，请先运行:  pip install akshare", code=2)


def _sina_a_symbol(code):
    """A 股代码 → 新浪所需的市场前缀符号。"""
    if code[0] in ("6", "9"):  # 沪市主板/科创 + 沪 B
        return "sh" + code
    return "sz" + code         # 深市主板/中小/创业 + 深 B(200/300/00x)


def _window(df, date_col, start, end):
    return df[(df[date_col].astype(str) >= start.strftime("%Y-%m-%d")) &
              (df[date_col].astype(str) <= end.strftime("%Y-%m-%d"))]


def fetch(ak, kind, symbol, start, end):
    """返回 (df, date_col, close_col, source)。

    数据源策略：**统一以新浪为首选**，保证同一标的多次查询结果可复现。
    （东财 stock_zh_a_hist 的前复权锚点与新浪不同，且会限流——同一标的两次跑可能得出不同涨幅，
      故仅作 A 股的兜底源，不作首选。）
    """
    s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    if kind == "a":
        # 首选新浪 stock_zh_a_daily（前复权更贴近真实总回报、结果稳定）
        try:
            df = ak.stock_zh_a_daily(symbol=_sina_a_symbol(symbol), adjust="qfq")
            if df is not None and len(df):
                return _window(df, "date", start, end), "date", "close", "新浪"
        except Exception:
            pass
        # 兜底东财（注意：前复权口径与新浪不同，仅在新浪不可用时使用）
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily",
                                start_date=s, end_date=e, adjust="qfq")
        return df, "日期", "收盘", "东财(兜底,口径异于新浪)"
    if kind == "hk":
        # 新浪源（stock_hk_daily）比东财源（stock_hk_hist）稳，返回全历史，自行截窗
        df = ak.stock_hk_daily(symbol=symbol, adjust="qfq")
        return _window(df, "date", start, end), "date", "close", "新浪"
    if kind == "index":
        # 该接口不收日期参数，需自行截窗
        df = ak.stock_zh_index_daily(symbol=symbol)
        return _window(df, "date", start, end), "date", "close", "新浪"
    fail(f"未支持的类型: {kind}")


def main():
    if len(sys.argv) != 4:
        fail("用法: python3 scripts/quote.py <代码> <起始日YYYY-MM-DD> <结束日YYYY-MM-DD>")
    ticker, start_s, end_s = sys.argv[1], sys.argv[2], sys.argv[3]
    start, end = parse_date(start_s), parse_date(end_s)
    if end < start:
        fail("结束日早于起始日")

    kind, symbol = classify(ticker)
    ak = load_akshare()

    try:
        df, date_col, close_col, source = fetch(ak, kind, symbol, start, end)
    except Exception as exc:  # 网络 / 停牌 / 退市 / 接口变更
        fail(f"取行情失败（可能停牌/退市/网络问题）: {exc}", code=3)

    if df is None or len(df) == 0:
        fail("区间内无行情数据（可能停牌/退市/尚未上市）", code=3)

    df = df.reset_index(drop=True)
    first, last = df.iloc[0], df.iloc[-1]
    p0, p1 = float(first[close_col]), float(last[close_col])
    pct = (p1 - p0) / p0 * 100 if p0 else float("nan")

    print(f"代码:       {ticker}  ({kind})")
    print(f"数据源:     {source}（前复权）")
    print(f"区间:       {first[date_col]} → {last[date_col]}  (交易日 {len(df)} 天)")
    print(f"首日收盘:   {p0:.3f}")
    print(f"末日收盘:   {p1:.3f}")
    print(f"区间涨跌幅: {pct:+.2f}%")


if __name__ == "__main__":
    main()
