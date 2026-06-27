# -*- coding: utf-8 -*-
"""建事实底座·财务三表下载器
用法: python3 scripts/fetch_fundamentals.py <代码> <公司名>
  例: python3 scripts/fetch_fundamentals.py 000568 泸州老窖
产出: finance/<公司名>/_raw_akshare/<公司名>_{利润表,资产负债表,现金流量表}.csv
说明: akshare 新浪财报接口返回全历史(年报+季报,通常≥10年);这是"近10年年报季报"事实底座的最低配。
"""
import os
import sys
import akshare as ak

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "finance")


def sina_symbol(code):
    code = str(code).zfill(6)
    if code[0] == "6":
        return "sh" + code
    if code[0] in ("0", "3"):
        return "sz" + code
    if code[0] in ("4", "8"):
        return "bj" + code
    raise ValueError(f"无法判断交易所前缀: {code}")


def main():
    if len(sys.argv) < 3:
        print("用法: python3 scripts/fetch_fundamentals.py <代码> <公司名>")
        sys.exit(1)
    code, name = sys.argv[1], sys.argv[2]
    sym = sina_symbol(code)
    out_dir = os.path.join(BASE, name, "_raw_akshare")
    os.makedirs(out_dir, exist_ok=True)

    for table in ("利润表", "资产负债表", "现金流量表"):
        try:
            df = ak.stock_financial_report_sina(stock=sym, symbol=table)
            path = os.path.join(out_dir, f"{name}_{table}.csv")
            df.to_csv(path, index=False, encoding="utf-8-sig")
            spans = df["报告日"].astype(str)
            print(f"✓ {table}: {len(df)} 期 ({spans.min()}~{spans.max()}) -> {path}")
        except Exception as e:
            print(f"✗ {table} 失败: {e}")


if __name__ == "__main__":
    main()
