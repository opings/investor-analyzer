#!/usr/bin/env python3
"""当日/区间公告拉取 —— 给 daily-news skill 用，从巨潮(cninfo)拉一手公告标题+链接。

用法:
    python3 scripts/notices.py [起始日] [结束日] [代码...]

    起始日/结束日: YYYY-MM-DD，省略则都用「今天」；只给起始日则区间=单日。
    代码: 省略则读 knowledge/companies/_watchlist.md 全部 14 家；也可显式指定若干。

示例:
    python3 scripts/notices.py                      # 今天，全部 watchlist
    python3 scripts/notices.py 2026-06-22           # 指定单日，全部
    python3 scripts/notices.py 2026-06-01 2026-06-23 600519 00700   # 区间+指定公司

数据源: akshare → stock_zh_a_disclosure_report_cninfo（A股 market=沪深京 / 港股 market=港股）。
只拉一手公告（标题+时间+cninfo链接），不下任何判断 —— 重大性/真伪由 daily-news skill 判定。
依赖: akshare（复用 scripts/.venv）。
"""
import os
import re
import sys
import time
from datetime import date, datetime

# venv 自举（同 quote.py，逻辑见 _venv.py）：缺 akshare 但有 .venv 就用 venv 的 python 重跑本脚本
from _venv import bootstrap

bootstrap(__file__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHLIST = os.path.join(ROOT, "knowledge", "companies", "_watchlist.md")

# 例行/低信息量公告标题（默认折叠，但会报告折叠数量，不静默丢弃）
NOISE_PAT = re.compile(
    r"翌日披露报表|法律意见书|独立董事|监事会决议|持股.*简式权益|更正公告|英文版|"
    r"持续关连交易之|月报表|股份发行人.*证券变动月报"
)


def fail(msg, code=1):
    print(f"[notices] {msg}", file=sys.stderr)
    sys.exit(code)


def parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        fail(f"日期格式应为 YYYY-MM-DD，收到: {s}")


def load_watchlist_codes():
    """从 _watchlist.md 表格第 2 列抽取代码。返回 [(code, name), ...]。"""
    if not os.path.exists(WATCHLIST):
        fail(f"找不到 watchlist: {WATCHLIST}")
    out = []
    with open(WATCHLIST, encoding="utf-8") as f:
        for line in f:
            if not line.lstrip().startswith("|"):
                continue
            cols = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cols) < 2:
                continue
            name, code = cols[0], cols[1]
            if code.isdigit():  # 跳过表头(代码)与分隔行(---)
                out.append((code, name))
    if not out:
        fail("watchlist 未解析到任何代码")
    return out


def market_of(code):
    """6 位 = A 股(沪深京)；5 位及以下 = 港股。返回 (market, normalized_code)。"""
    c = code.strip()
    if len(c) == 6 and c.isdigit():
        return "沪深京", c
    if c.isdigit() and len(c) <= 5:
        return "港股", c.zfill(5)
    fail(f"无法识别代码: {code}（A股 6 位如 600519 / 港股 5 位如 00700）")


def fetch_one(ak, code, start, end, retries=2):
    market, sym = market_of(code)
    df = None
    last_exc = None
    for attempt in range(retries + 1):
        try:
            df = ak.stock_zh_a_disclosure_report_cninfo(
                symbol=sym, market=market,
                start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"))
            break
        except KeyError:
            # akshare 对「窗口内零公告」的已知行为：空响应时内部列重命名失败抛 KeyError → 视为无公告，不重试
            return []
        except Exception as exc:
            # 瞬时错误（JSON 解析失败/网络抖动/限流）→ 退避重试
            last_exc = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise last_exc
    rows = []
    if df is not None and len(df):
        for _, r in df.iterrows():
            rows.append((str(r["公告时间"]), str(r["公告标题"]), str(r["公告链接"])))
    rows.sort(reverse=True)  # 倒序，最新在上
    return rows


def main():
    argv = sys.argv[1:]
    dates = [a for a in argv if re.fullmatch(r"\d{4}-\d{2}-\d{2}", a)]
    codes = [a for a in argv if a.isdigit()]

    today = date.today()
    if not dates:
        start = end = today
    elif len(dates) == 1:
        start = end = parse_date(dates[0])
    else:
        start, end = parse_date(dates[0]), parse_date(dates[1])
    if end < start:
        fail("结束日早于起始日")

    targets = [(c, c) for c in codes] if codes else load_watchlist_codes()

    import akshare as ak

    win = start.strftime("%Y-%m-%d") + ("" if start == end else f" ~ {end.strftime('%Y-%m-%d')}")
    print(f"# 公告拉取（cninfo 巨潮一手）· 窗口 {win} · {len(targets)} 家\n")

    total, dropped_total = 0, 0
    for code, name in targets:
        try:
            rows = fetch_one(ak, code, start, end)
        except Exception as exc:
            print(f"## {name}（{code}）—— 拉取失败: {exc}\n", flush=True)
            continue
        kept = [r for r in rows if not NOISE_PAT.search(r[1])]
        dropped = len(rows) - len(kept)
        dropped_total += dropped
        if not kept:
            tail = f"（另折叠 {dropped} 条例行公告）" if dropped else ""
            print(f"## {name}（{code}）—— 窗口内无公告{tail}\n", flush=True)
            continue
        total += len(kept)
        print(f"## {name}（{code}）· {len(kept)} 条" + (f"（已折叠 {dropped} 条例行）" if dropped else ""))
        for t, title, url in kept:
            print(f"- {t} | {title}\n  {url}")
        print(flush=True)

    print(f"---\n合计 {total} 条候选公告，折叠 {dropped_total} 条例行公告。"
          f"\n（本脚本只拉一手公告，重大性/真伪判断交给 daily-news skill）")


if __name__ == "__main__":
    main()
