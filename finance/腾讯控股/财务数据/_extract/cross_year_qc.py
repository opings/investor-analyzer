"""Cross-year QC: for each key line, compare year-t CY (from t report)
vs year-t PY (comparative column printed in the t+1 report).
Mismatches = either extraction error or a genuine restatement (must be explained)."""
import json
import os
import sys

sys.path.insert(0, '/Users/zhaoyongzhen/workspace/ai-tool/investor-analyzer/finance/腾讯控股/财务数据')
from _build_from_pdf import (clean, IS_MAP, BS_MAP, CF_MAP, CF_CONTAINS, SEG_MAP,
                             cf_classify, EXTRACT, iter_rows, load_year_values)

KEYS = {
    'IS': ('income_statement', IS_MAP, None,
           ['营业收入', '毛利', '经营盈利', '年度盈利', '归母净利']),
    'BS': ('balance_sheet', BS_MAP, None,
           ['资产总额', '权益总额', '负债总额', '现金及现金等价物', '应收账款']),
    'CF': ('cash_flow', CF_MAP, CF_CONTAINS,
           ['经营活动现金流净额', '投资活动现金流净额', '融资活动现金流净额', '年末现金']),
}


def load_values(data, section, mapping, contains, use='cy'):
    out = {}
    for r in iter_rows(data.get(section)):
        v = r.get(use)
        if v is None:
            continue
        c = clean(r.get('item', ''))
        name = mapping.get(c)
        if name is None and mapping is CF_MAP:
            name = cf_classify(c)
        if name is None and contains:
            low = c.lower()
            for kw, std in contains:
                if all(k in low or k in c for k in kw):
                    name = std
                    break
        if name is None:
            continue
        if name == '经营活动现金流净额' and name in out:
            out[name] = v  # 2004 两行同名取后者
        elif name not in out:
            out[name] = v
    return out


mismatch = 0
for t in range(2004, 2025):
    cur = json.load(open(os.path.join(EXTRACT, f'{t}.json')))
    nxt = json.load(open(os.path.join(EXTRACT, f'{t + 1}.json')))
    for tbl, (section, mapping, contains, names) in KEYS.items():
        cy_vals = load_values(cur, section, mapping, contains, 'cy')
        py_vals = load_values(nxt, section, mapping, contains, 'py')
        for n in names:
            a, b = cy_vals.get(n), py_vals.get(n)
            if a is None or b is None:
                continue
            if t < 2013 <= t + 1:
                b = b * 1000.0  # t+1 年报已改百万口径,其比较列换算回千元
            tol = max(2.0 if t >= 2013 else 2000.0, abs(a) * 0.001)
            if abs(a - b) > tol:
                unit = '百万' if t >= 2013 else '千元'
                print(f'{t} {tbl} {n}: 本年报={a:,.0f} vs {t+1}年报比较列={b:,.0f} ({unit}) diff={a-b:,.0f}')
                mismatch += 1

print(f'\n=== cross-year mismatches: {mismatch} (0 = 全部互证一致; 非零项须归因: 重列 or 提取错) ===')
