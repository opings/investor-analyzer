# -*- coding: utf-8 -*-
"""建事实底座·财务三表下载器（A股=新浪 / 港股=东财）
用法: python3 scripts/fetch_fundamentals.py <代码> <公司名>
  A股: python3 scripts/fetch_fundamentals.py 000568 泸州老窖
  港股: python3 scripts/fetch_fundamentals.py 09633 农夫山泉   (代码 5 位或带 .HK 自动识别)
产出: finance/<公司名>/_raw_akshare/<公司名>_{利润表,资产负债表,现金流量表}.csv
      港股另产出 <公司名>_财务指标.csv（含经营现金流/销售、ROE、现金含量基础等，东财已算好）
说明:
  A股 新浪接口返回全历史(年报+季报);港股 东财接口取年度三表 + 年度财务指标。
  港股原始为长表(报告期×科目→金额),本脚本透视成与 A股 一致的 wide 格式(行=报告期、列=科目),
  以便用同一套"按列名提取"逻辑读取。⚠️港股金额单位见东财(农夫等以人民币列报,东财 currency 标签可能为名义 HKD)。
"""
import os
import sys
import akshare as ak
import pandas as pd

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "finance")
TABLES = ("利润表", "资产负债表", "现金流量表")


def is_hk(code):
    c = str(code).upper().replace(".HK", "").strip()
    # A股为 6 位数字；港股通常 5 位(含前导 0，如 09633/00700)
    return not (len(c) == 6 and c.isdigit())


def sina_symbol(code):
    code = str(code).zfill(6)
    if code[0] == "6":
        return "sh" + code
    if code[0] in ("0", "3"):
        return "sz" + code
    if code[0] in ("4", "8"):
        return "bj" + code
    raise ValueError(f"无法判断交易所前缀: {code}")


def fetch_a(code, name, out_dir):
    sym = sina_symbol(code)
    for table in TABLES:
        try:
            df = ak.stock_financial_report_sina(stock=sym, symbol=table)
            path = os.path.join(out_dir, f"{name}_{table}.csv")
            df.to_csv(path, index=False, encoding="utf-8-sig")
            spans = df["报告日"].astype(str)
            print(f"✓ {table}: {len(df)} 期 ({spans.min()}~{spans.max()}) -> {path}")
        except Exception as e:
            print(f"✗ {table} 失败: {e}")


def fetch_hk(code, name, out_dir):
    hk = str(code).upper().replace(".HK", "").strip().zfill(5)
    for table in TABLES:
        try:
            df = ak.stock_financial_hk_report_em(stock=hk, symbol=table, indicator="年度")
            df["报告期"] = df["REPORT_DATE"].astype(str).str[:10]
            wide = df.pivot_table(index="报告期", columns="STD_ITEM_NAME",
                                  values="AMOUNT", aggfunc="first")
            wide = wide.sort_index(ascending=False).reset_index()
            path = os.path.join(out_dir, f"{name}_{table}.csv")
            wide.to_csv(path, index=False, encoding="utf-8-sig")
            print(f"✓ {table}: {len(wide)} 期 ({wide['报告期'].min()}~{wide['报告期'].max()}) -> {path}")
        except Exception as e:
            print(f"✗ {table} 失败: {e}")
    # 港股财务指标(东财已算好经营现金流/销售、ROE、现金含量基础等)
    try:
        ind = ak.stock_financial_hk_analysis_indicator_em(symbol=hk, indicator="年度")
        path = os.path.join(out_dir, f"{name}_财务指标.csv")
        ind.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"✓ 财务指标: {len(ind)} 期 -> {path}")
    except Exception as e:
        print(f"✗ 财务指标 失败: {e}")


def main():
    if len(sys.argv) < 3:
        print("用法: python3 scripts/fetch_fundamentals.py <代码> <公司名>")
        sys.exit(1)
    code, name = sys.argv[1], sys.argv[2]
    out_dir = os.path.join(BASE, name, "_raw_akshare")
    os.makedirs(out_dir, exist_ok=True)
    if is_hk(code):
        print(f"[港股·东财] {code} {name}")
        fetch_hk(code, name, out_dir)
    else:
        print(f"[A股·新浪] {code} {name}")
        fetch_a(code, name, out_dir)


if __name__ == "__main__":
    main()
