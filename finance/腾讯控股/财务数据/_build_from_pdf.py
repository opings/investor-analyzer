#!/usr/bin/env python3
"""腾讯控股三表 CSV 生成器。

数据流:report/腾讯控股/{招股说明书,YYYY}.pdf --LLM逐行提取--> _extract/*.json --本脚本--> *.csv

- _extract/*.json = 每年年报(+招股书 2001-2003)合并报表的逐行提取结果(item 保持财报印刷原文)
- 本脚本做:科目名清洗归一 -> 单位统一(2001-2012 千元 / 2013+ 百万 -> 全部人民币百万元)
  -> 三表勾稽校验 + 跨年衔接校验 -> 写出 利润表.csv / 资产负债表.csv / 现金流量表.csv / 分部营收.csv
- 勾稽不过 = 不写出(直接抛异常)

用法:python3 _build_from_pdf.py
"""
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXTRACT = os.path.join(HERE, '_extract')

YEARS = list(range(2001, 2026))
THOUSAND_YEARS = set(range(2001, 2013))   # 财报单位=千元的年份(2013 年报起改百万)

# ---------------------------------------------------------------- 清洗

def clean(item: str) -> str:
    """去附注号/层级前缀/标点差异,返回可映射的科目名。"""
    s = item.strip()
    s = re.sub(r'[〔【（]', '(', s)
    s = re.sub(r'[〕】）]', ')', s)
    s = re.sub(r'\s*[\(\[]附註.*$', '', s)                    # (附註5(c)(i))… 附注总在结尾,截到行尾
    s = re.sub(r'\s*[\(\[]附註[^)\]]*[\)\]]', '', s)          # (附註5) [附註5]
    s = re.sub(r'\s*\[Note[^\]]*\]', '', s, flags=re.I)       # [Note 6]
    s = re.sub(r'\s*\(Note[^)]*\)', '', s, flags=re.I)
    s = re.sub(r'[,，]\s*附註[^)]*\)', ')', s)                 # (合計，附註6) -> (合計)
    s = s.replace('—', '-').replace('－', '-').replace('–', '-').replace('|', ':').replace('：', ':')
    s = s.replace('／', '/').replace('╱', '/')
    s = re.sub(r'\s+', '', s)
    s = s.replace('帳', '賬').replace('税', '稅').replace('滙', '匯')
    # 提取残留的孤立括号(如「所得稅開支)」);成对外层括号(如「(收入合計)」)剥掉
    if s.startswith('(') and s.endswith(')') and s.count('(') == 1:
        s = s[1:-1]
    if s.endswith(')') and s.count(')') > s.count('('):
        s = s[:-1]
    if s.startswith('(') and s.count('(') > s.count(')'):
        s = s[1:]
    # 层级前缀(資產:流動資產:xxx / 流動負債-xxx / 權益:xxx ...)只留最末级
    parts = re.split(r'[:\-]', s)
    if len(parts) > 1:
        prefixes = {'資產', '負債', '權益', '流動資產', '非流動資產', '流動負債', '非流動負債',
                    '股東權益', '本公司權益持有人應佔權益', '收入', '下列人士應佔', '應佔',
                    'Attributableto', 'Revenues'}
        while len(parts) > 1 and parts[0] in prefixes:
            parts = parts[1:]
        s2 = '-'.join(parts)
    else:
        s2 = s
    return s2

# ---------------------------------------------------------------- 科目映射(清洗名 -> 标准行名)

IS_MAP = {
    # 收入合计
    '收入': '营业收入', '收入合計': '营业收入', '收入(合計)': '营业收入',
    '收入(合計,附註6)': '营业收入', 'Revenues(total)': '营业收入',
    # 成本/毛利
    '收入成本': '营业成本', 'Costofrevenues': '营业成本',
    '毛利': '毛利', 'Grossprofit': '毛利',
    # 其他损益
    '利息收入': '利息收入', 'Interestincome': '利息收入',
    '其他收益淨額': '其他收益净额', '其他(虧損)/收益淨額': '其他收益净额',
    '其他收益/(虧損)淨額': '其他收益净额', '其他收益╱(虧損)淨額': '其他收益净额',
    '其他經營收入/(開支)淨額': '其他收益净额', '其他經營(開支)/收入淨額': '其他收益净额',
    'Othergains/(losses),net': '其他收益净额',
    '投資收益/(虧損)淨額及其他': '投资收益净额及其他', '投資收益╱(虧損)淨額及其他': '投资收益净额及其他',
    'Netgains/(losses)frominvestmentsandothers': '投资收益净额及其他',
    # 费用
    '銷售及市場推廣開支': '销售及市场推广开支', 'Sellingandmarketingexpenses': '销售及市场推广开支',
    '一般及行政開支': '一般及行政开支', 'Generalandadministrativeexpenses': '一般及行政开支',
    # 经营/财务/联营
    '經營盈利': '经营盈利', 'Operatingprofit': '经营盈利',
    '融資收入淨額': '财务成本净额', '融資(開支)/收入淨額': '财务成本净额',
    '財務成本': '财务成本净额', '財務成本淨額': '财务成本净额', '財務成本,淨額': '财务成本净额',
    '財務(成本)/收入淨額': '财务成本净额', '財務收入/(成本)淨額': '财务成本净额',
    'Financecosts': '财务成本净额',
    '分佔聯營公司盈利': '分占联营合营盈亏', '分佔聯營公司虧損': '分占联营合营盈亏',
    '分佔聯營公司(虧損)/盈利': '分占联营合营盈亏', '分佔聯營公司盈利/(虧損)': '分占联营合营盈亏',
    '分佔聯營公司/一間共同控制實體虧損': '分占联营合营盈亏',
    '分佔一間共同控制實體的盈利': '分占联营合营盈亏', '應佔一間共同控制實體虧損': '分占联营合营盈亏',
    '分佔共同控制實體(虧損)/盈利': '分占联营合营盈亏', '分佔共同控制實體虧損': '分占联营合营盈亏',
    '分佔合營公司虧損': '分占联营合营盈亏',
    '分佔聯營公司及合營公司(虧損)/盈利': '分占联营合营盈亏',
    '分佔聯營公司及合營公司(虧損)/盈利淨額': '分占联营合营盈亏',
    '分佔聯營公司及合營公司(虧損)╱盈利淨額': '分占联营合营盈亏',
    '分佔聯營公司及合營公司盈利': '分占联营合营盈亏',
    '分佔聯營公司及合營公司盈利/(虧損)': '分占联营合营盈亏',
    '分佔聯營公司及合營公司盈利╱(虧損)淨額': '分占联营合营盈亏',
    '分佔聯營公司及合營公司盈利/(虧損)淨額': '分占联营合营盈亏',
    '分佔聯營公司及合營公司虧損': '分占联营合营盈亏',
    'Shareofprofit/(loss)ofassociatesandjointventures,net': '分占联营合营盈亏',
    # 税/净利
    '除稅前盈利': '除税前盈利', 'Profitbeforeincometax': '除税前盈利',
    '稅項': '所得税开支', '所得稅開支': '所得税开支', '所得税開支': '所得税开支',
    '所得稅(開支)/收益': '所得税开支', '所得稅收益/(開支)': '所得税开支',
    '所得税收益/(開支)': '所得税开支', 'Incometaxexpense': '所得税开支',
    '年度盈利': '年度盈利', '純利': '年度盈利', '年內/期內盈利': '年度盈利',
    '年度盈利/年度全面收益總額': '年度盈利',
    'Profitfortheyear': '年度盈利',
    # 归属
    '本公司權益持有人': '归母净利', 'Attributableto:EquityholdersoftheCompany': '归母净利',
    'EquityholdersoftheCompany': '归母净利',
    '非控制性權益': '非控制性权益损益', '少數股東權益': '非控制性权益损益',
    'Attributableto:Non-controllinginterests': '非控制性权益损益',
    'Non-controllinginterests': '非控制性权益损益',
}

BS_MAP = {
    # 非流动资产
    '固定資產': '物业设备及器材', '物業、設備及器材': '物业设备及器材',
    'Property,plantandequipment': '物业设备及器材',
    '在建工程': '在建工程', 'Constructioninprogress': '在建工程',
    '投資物業': '投资物业', 'Investmentproperties': '投资物业',
    '土地使用權': '土地使用权', '租賃土地及土地使用權': '土地使用权', 'Landuserights': '土地使用权',
    '使用權資產': '使用权资产', 'Right-of-useassets': '使用权资产',
    '無形資產': '无形资产', 'Intangibleassets': '无形资产',
    '於聯營公司的投資': '于联营公司的投资', '於聯營公司的權益': '于联营公司的投资',
    'Investmentsinassociates': '于联营公司的投资',
    '於聯營公司可贖回優先股的投資': '于联营公司可赎回工具的投资',
    '於聯營公司可贖回工具的投資': '于联营公司可赎回工具的投资',
    '於合營公司的投資': '于合营公司的投资', '於共同控制實體的投資': '于合营公司的投资',
    'Investmentsinjointventures': '于合营公司的投资',
    '可供出售金融資產': '可供出售金融资产', '可供出售的金融資產': '可供出售金融资产',
    '可供出售的投資': '可供出售金融资产',
    '持有至到期日的投資': '持有至到期投资',
    '以公允價值計量且其變動計入損益的金融資產': '以公允价值计量计入损益的金融资产(FVPL)',
    'Financialassetsatfairvaluethroughprofitorloss': '以公允价值计量计入损益的金融资产(FVPL)',
    '以公允價值計量且其變動計入其他全面收益的金融資產': '以公允价值计量计入其他全面收益的金融资产(FVOCI)',
    'Financialassetsatfairvaluethroughothercomprehensiveincome': '以公允价值计量计入其他全面收益的金融资产(FVOCI)',
    'Financialassetsatfairvaluethroughothercomprehensivei': '以公允价值计量计入其他全面收益的金融资产(FVOCI)',
    '其他金融資產': '其他金融资产', 'Otherfinancialassets': '其他金融资产',
    '遞延所得稅資產': '递延所得税资产', 'Deferredincometaxassets': '递延所得税资产',
    '定期存款': '定期存款', 'Termdeposits': '定期存款',
    '初步為期超過三個月的定期存款': '定期存款',
    '預付款項、按金及其他資產': '预付款项按金及其他资产',
    '預付款項、按金及其他應收款項': '预付款项按金及其他资产',
    'Prepayments,depositsandotherassets': '预付款项按金及其他资产',
    '非流動資產合計': '非流动资产合计', '非流動資產(小計)': '非流动资产合计',
    'Non-currentassets(subtotal)': '非流动资产合计',
    # 流动资产
    '存貨': '存货', 'Inventories': '存货',
    '應收賬款': '应收账款', 'Accountsreceivable': '应收账款',
    '應收股東款項': '应收股东款项',
    '為交易而持有的投資': '为交易而持有的金融资产', '為交易而持有的金融資產': '为交易而持有的金融资产',
    '衍生金融工具': '衍生金融工具',
    '受限制現金': '受限制现金', 'Restrictedcash': '受限制现金',
    '現金及現金等價物': '现金及现金等价物', 'Cashandcashequivalents': '现金及现金等价物',
    '持有待分配資產': '持有待分配资产',
    '流動資產合計': '流动资产合计', '流動資產(小計)': '流动资产合计',
    'Currentassets(subtotal)': '流动资产合计',
    '資產總額': '资产总额', '總資產': '资产总额', 'Totalassets': '资产总额',
    # 权益
    '股本': '股本', 'Sharecapital': '股本',
    '股本溢價': '股本溢价', 'Sharepremium': '股本溢价',
    '庫存股': '库存股', 'Treasuryshares': '库存股',
    '股份獎勵計劃所持股份': '股份奖励计划所持股份',
    'Sharesheldforshareawardschemes': '股份奖励计划所持股份',
    '股份酬金儲備': '股份酬金储备', '股份報酬儲備': '股份酬金储备',
    '其他儲備': '其他储备', '儲備': '其他储备', 'Otherreserves': '其他储备',
    '保留盈利': '保留盈利', 'Retainedearnings': '保留盈利',
    '本公司權益持有人應佔權益合計': '归母权益合计', '本公司權益持有人應佔權益(小計)': '归母权益合计',
    '本公司權益持有人應佔權益': '归母权益合计',
    'EquityattributabletoequityholdersoftheCompany(subtot': '归母权益合计',
    'EquityattributabletoequityholdersoftheCompany(subtotal)': '归母权益合计',
    '非控制性權益': '非控制性权益', 'Non-controllinginterests': '非控制性权益',
    '少數股東權益': '非控制性权益',
    '權益總額': '权益总额', '股東權益總額': '权益总额', '股東權益合計': '权益总额',
    '股東權益(小計)': '权益总额',
    'Totalequity': '权益总额',
    # 负债
    '應付賬款': '应付账款', 'Accountspayable': '应付账款',
    '應付股息': '应付股息', '以實物分派的應付股息': '以实物分派的应付股息',
    '應付所得稅': '流动所得税负债', '流動所得稅負債': '流动所得税负债', '流動所得税負債': '流动所得税负债',
    'Currentincometaxliabilities': '流动所得税负债',
    '其他應付稅項': '其他税项负债', '其他稅項負債': '其他税项负债', '其他税項負債': '其他税项负债',
    'Othertaxliabilities': '其他税项负债',
    '其他應付款項及預提費用': '其他应付款项及预提费用', '其他應付賬款及應計費用': '其他应付款项及预提费用',
    'Otherpayablesandaccruals': '其他应付款项及预提费用',
    '遞延收入': '递延收入', 'Deferredrevenue': '递延收入',
    '短期銀行借款': '借款', '短期借款': '借款', '借款': '借款', 'Borrowings': '借款',
    '借款(流動)': '借款', '借款(非流動)': '借款',
    '短期定期存款': '定期存款',
    '應付票據': '应付票据', '長期應付票據': '应付票据', 'Notespayable': '应付票据',
    '租賃負債': '租赁负债', 'Leaseliabilities': '租赁负债',
    '其他金融負債': '其他金融负债', 'Otherfinancialliabilities': '其他金融负债',
    '長期應付款項': '长期应付款项', 'Long-termpayables': '长期应付款项',
    '遞延所得稅負債': '递延所得税负债', 'Deferredincometaxliabilities': '递延所得税负债',
    '應付股東款項': '应付股东款项', '應付關連人士款項': '应付关联方款项',
    '流動負債合計': '流动负债合计', '流動負債(小計)': '流动负债合计',
    'Currentliabilities(subtotal)': '流动负债合计',
    '非流動負債合計': '非流动负债合计', '非流動負債(小計)': '非流动负债合计',
    'Non-currentliabilities(subtotal)': '非流动负债合计',
    '負債總額': '负债总额', '總負債': '负债总额', 'Totalliabilities': '负债总额',
    '權益及負債總額': '权益及负债总额', '股東權益及負債總額': '权益及负债总额',
    '總負債及股東權益': '权益及负债总额', 'Totalequityandliabilities': '权益及负债总额',
}

def cf_classify(c: str):
    """规则化识别现金流关键行(各年措辞变体太多,枚举不可维护)。返回标准名或 None。"""
    low = c.lower()
    detail = any(k in c for k in ('處置', '購買', '發行', '結算', '收購', '償還', '贖回', '注資', '按金'))
    is_net = c.endswith('現金淨額') or c.endswith('現金流量淨額') or \
        ('netcash' in low and 'activities' in low)
    if is_net and not detail:
        if '經營' in c or 'operating' in low:
            return '经营活动现金流净额'
        if '投資' in c or 'investing' in low:
            return '投资活动现金流净额'
        if '融資' in c or 'financing' in low:
            return '融资活动现金流净额'
    if '現金及現金等價物' in c or 'cashandcashequivalents' in low:
        if '匯兌' in c or '匯率' in c or 'exchange' in low:
            return '汇率影响'
        if '年初' in c or '期初' in c or 'beginning' in low:
            return '年初现金'
        if '年末' in c or '年終' in c or '期終' in c or ('end' in low and 'year' in low):
            return '年末现金'
        if not detail and ('增加' in c or '減少' in c or 'increase' in low or 'decrease' in low):
            return '现金及现金等价物净增加'
    return None


CF_MAP = {}  # 全部走 cf_classify 规则 + CF_CONTAINS 关键词

# capex / 无形 / 股息 / 回购:关键词包含匹配(行名各年差异过大)。顺序敏感:先专后泛。
CF_CONTAINS = [
    (('購買固定資產',), 'capex(购建固定资产等)'),
    (('購買物業、設備及器材',), 'capex(购建固定资产等)'),
    (('paymentsforproperty'.lower(),), 'capex(购建固定资产等)'),
    (('prepaymentsforproperty'.lower(),), 'capex(购建固定资产等)'),
    (('purchaseofproperty'.lower(),), 'capex(购建固定资产等)'),
    (('購買無形資產',), '购买无形资产'),
    (('paymentsforintangible'.lower(),), '购买无形资产'),
    (('purchaseofintangible'.lower(),), '购买无形资产'),
    (('additionstointangible'.lower(),), '购买无形资产'),
    (('已付股息', '非控制'), '已付股息(非控股)'),
    (('股息', '非控制性權益'), '已付股息(非控股)'),
    (('股息', '少數股東'), '已付股息(非控股)'),
    (('dividendspaidtonon-controlling'.lower(),), '已付股息(非控股)'),
    (('已付股息', '股東'), '已付股息(股东)'),
    (('已付本公司股東股息',), '已付股息(股东)'),
    (('已支付予股東的股息',), '已付股息(股东)'),
    (('向本公司股東支付股息',), '已付股息(股东)'),
    (('向本公司權益持有人支付股息',), '已付股息(股东)'),
    (('dividendspaidtothecompany'.lower(),), '已付股息(股东)'),
    (('dividendspaidtoequityholders'.lower(),), '已付股息(股东)'),
    (('已付股息',), '已付股息(股东)'),          # 兜底:上市前/早年无 NCI 时的裸「已付股息」
    (('dividendspaid'.lower(), 'shareholders'), '已付股息(股东)'),
    (('購回股份',), '回购股份支付'),
    (('回購股份',), '回购股份支付'),
    (('repurchaseofshares'.lower(),), '回购股份支付'),
    (('paymentsforrepurchase'.lower(),), '回购股份支付'),
]

SEG_MAP = {
    '互聯網增值服務': '互联网增值服务', 'InternetVAS': '互联网增值服务',
    '移動及電信增值服務': '移动及电信增值服务', '移動及通信增值服務': '移动及电信增值服务',
    '增值服務': '增值服务', 'Revenues-Value-addedServices': '增值服务',
    'Value-addedServices': '增值服务', 'VAS': '增值服务',
    '網絡廣告': '网络广告/营销服务', '營銷服務*(原「網絡廣告」)': '网络广告/营销服务',
    '營銷服務': '网络广告/营销服务', 'Revenues-MarketingServices': '网络广告/营销服务',
    'MarketingServices': '网络广告/营销服务',
    '金融科技及企業服務': '金融科技及企业服务', '金融科技及企業服務(*)': '金融科技及企业服务',
    'Revenues-FinTechandBusinessServices': '金融科技及企业服务',
    'FinTechandBusinessServices': '金融科技及企业服务',
    '電子商務交易': '电子商务交易',
    '其他': '其他', '其他(*)': '其他', 'Revenues-Others': '其他', 'Others': '其他',
    '收入合計': '合计', '收入(合計)': '合计', 'TheGroup(total)': '合计', 'Total': '合计',
}

IS_ROWS = ['营业收入', '营业成本', '毛利', '利息收入', '其他收益净额', '投资收益净额及其他',
           '销售及市场推广开支', '一般及行政开支', '经营盈利', '财务成本净额', '分占联营合营盈亏',
           '除税前盈利', '所得税开支', '年度盈利', '归母净利', '非控制性权益损益']
BS_ROWS = ['物业设备及器材', '在建工程', '投资物业', '土地使用权', '使用权资产', '无形资产',
           '于联营公司的投资', '于联营公司可赎回工具的投资', '于合营公司的投资',
           '可供出售金融资产', '持有至到期投资',
           '以公允价值计量计入损益的金融资产(FVPL)', '以公允价值计量计入其他全面收益的金融资产(FVOCI)',
           '其他金融资产', '预付款项按金及其他资产', '定期存款', '递延所得税资产', '非流动资产合计',
           '存货', '应收账款', '为交易而持有的金融资产', '受限制现金', '现金及现金等价物',
           '持有待分配资产', '流动资产合计', '资产总额',
           '股本', '股本溢价', '库存股', '股份奖励计划所持股份', '股份酬金储备', '其他储备',
           '保留盈利', '归母权益合计', '非控制性权益', '权益总额',
           '应付账款', '其他应付款项及预提费用', '流动所得税负债', '其他税项负债', '递延收入',
           '借款', '应付票据', '租赁负债', '其他金融负债', '以实物分派的应付股息',
           '长期应付款项', '递延所得税负债', '流动负债合计', '非流动负债合计', '负债总额', '权益及负债总额']
CF_ROWS = ['经营活动现金流净额', '投资活动现金流净额', '融资活动现金流净额',
           '现金及现金等价物净增加', '汇率影响', '年初现金', '年末现金',
           'capex(购建固定资产等)', '购买无形资产', '已付股息(股东)', '已付股息(非控股)', '回购股份支付']
SEG_ROWS = ['互联网增值服务', '移动及电信增值服务', '增值服务', '网络广告/营销服务',
            '金融科技及企业服务', '电子商务交易', '其他', '合计']

# 流动/非流动双现科目:同一标准名一年内出现两次时相加(如借款、应付票据、租赁负债、
# 递延收入、其他金融资产/负债、FVPL、定期存款)。CSV 落合计口径,README 说明。
DUAL_OK = {'借款', '应付票据', '租赁负债', '递延收入', '其他金融资产', '其他金融负债',
           '以公允价值计量计入损益的金融资产(FVPL)',
           '以公允价值计量计入其他全面收益的金融资产(FVOCI)',
           '定期存款', '受限制现金', '持有待分配资产', '衍生金融工具', '为交易而持有的金融资产',
           '持有至到期投资', '预付款项按金及其他资产', '存货'}

# ---------------------------------------------------------------- 读取

def iter_rows(section):
    """Yield rows from a section dict, tolerating one nesting level (2025 revenue_breakdown)."""
    if section is None:
        return
    if 'rows' in section:
        yield from section['rows']
        return
    for v in section.values():
        if isinstance(v, dict) and 'rows' in v:
            yield from v['rows']
        elif isinstance(v, list) and v and isinstance(v[0], dict) and 'item' in v[0]:
            yield from v


def load_year_values(data, section_name, mapping, contains_rules=None, dual_ok=frozenset()):
    """Map one year's section rows -> {standard_name: cy_value}."""
    out = {}
    for r in iter_rows(data.get(section_name)):
        item = r.get('item', '')
        cy = r.get('cy')
        if cy is None:
            continue
        name = None
        c = clean(item)
        if c in mapping:
            name = mapping[c]
        elif mapping is CF_MAP:
            name = cf_classify(c)
        if name is None and contains_rules:
            low = c.lower()
            for keywords, std in contains_rules:
                if all(k in low or k in c for k in keywords):
                    name = std
                    break
        if name is None:
            continue
        if name in out:
            if name in dual_ok:
                out[name] += cy
            else:
                # 同名重复且非双现白名单:2004 现金流「經營活動所得現金淨額」两行,取最后(扣息税后)
                out[name] = cy
        else:
            out[name] = cy
    return out


def load_prospectus():
    """招股书 2001-2003:rows 是 {item, y2001, y2002, y2003}。"""
    data = json.load(open(os.path.join(EXTRACT, 'prospectus_2001_2003.json')))
    per_year = {y: {'IS': {}, 'BS': {}, 'CF': {}, 'SEG': {}} for y in (2001, 2002, 2003)}
    section_of = {'income_statement': ('IS', IS_MAP, None),
                  'balance_sheet': ('BS', BS_MAP, None),
                  'cash_flow': ('CF', CF_MAP, CF_CONTAINS),
                  'revenue_breakdown': ('SEG', SEG_MAP, None)}
    for sec_name, (key, mapping, contains_rules) in section_of.items():
        for r in iter_rows(data.get(sec_name)):
            item = r.get('item', '')
            c = clean(item)
            name = mapping.get(c)
            if name is None and mapping is CF_MAP:
                name = cf_classify(c)
            if name is None and contains_rules:
                low = c.lower()
                for keywords, std in contains_rules:
                    if all(k in low or k in c for k in keywords):
                        name = std
                        break
            if name is None:
                continue
            for y in (2001, 2002, 2003):
                v = r.get(f'y{y}')
                if v is None:
                    continue
                bucket = per_year[y][key]
                if name in bucket:
                    if name in DUAL_OK:
                        bucket[name] += v
                    else:
                        bucket[name] = v
                else:
                    bucket[name] = v
    return per_year


def load_all():
    """Return {year: {'IS':…,'BS':…,'CF':…,'SEG':…}} in RMB million."""
    result = load_prospectus()
    for y in range(2004, 2026):
        path = os.path.join(EXTRACT, f'{y}.json')
        data = json.load(open(path))
        seg_section = data.get('revenue_breakdown')
        # 2025 revenue_breakdown 嵌套多子表(分部收入/分部毛利/地域):只取收入子表,防毛利混入
        if isinstance(seg_section, dict) and 'rows' not in seg_section:
            for key in ('by_segment', 'rows_by_segment', 'segments'):
                if key in seg_section:
                    seg_section = seg_section[key]
                    break
        result[y] = {
            'IS': load_year_values(data, 'income_statement', IS_MAP),
            'BS': load_year_values(data, 'balance_sheet', BS_MAP, dual_ok=DUAL_OK),
            'CF': load_year_values(data, 'cash_flow', CF_MAP, CF_CONTAINS),
            'SEG': load_year_values({'seg': seg_section}, 'seg', SEG_MAP),
        }
        # 分部行也可能印在收益表表面(收入-互聯網增值服務):从 IS rows 再收一遍分部
        for r in iter_rows(data.get('income_statement')):
            item, cy = r.get('item', ''), r.get('cy')
            if cy is None:
                continue
            c = clean(item)
            if c in SEG_MAP:
                result[y]['SEG'].setdefault(SEG_MAP[c], cy)
    # 单位统一 -> 百万
    for y, tables in result.items():
        if y in THOUSAND_YEARS:
            for key in tables:
                tables[key] = {k: round(v / 1000.0, 3) for k, v in tables[key].items()}
    # 分部合计缺失年份自动补 = 分部和(勾稽已验证分部和=收入)
    for y, tables in result.items():
        seg = tables['SEG']
        if seg and '合计' not in seg:
            seg['合计'] = round(sum(v for k, v in seg.items() if k != '合计'), 3)
    return result

# ---------------------------------------------------------------- 勾稽

def approx(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol


def validate(all_data):
    errors, warns = [], []
    for y in YEARS:
        t = all_data[y]
        IS, BS, CF, SEG = t['IS'], t['BS'], t['CF'], t['SEG']
        tol = 2.0 if y >= 2013 else 0.01  # 百万年份容差 2(四舍五入),千元年份 0.001*10

        rev, cost, gp = IS.get('营业收入'), IS.get('营业成本'), IS.get('毛利')
        if None in (rev, cost, gp):
            errors.append(f'{y} IS 缺收入/成本/毛利')
        elif not approx(rev + cost, gp, tol):
            errors.append(f'{y} IS 收入{rev}+成本{cost}≠毛利{gp}')

        pbt, tax, np_ = IS.get('除税前盈利'), IS.get('所得税开支'), IS.get('年度盈利')
        if None in (pbt, np_):
            errors.append(f'{y} IS 缺除税前/年度盈利')
        elif not approx(pbt + (tax or 0), np_, tol):
            errors.append(f'{y} IS 除税前{pbt}+税{tax}≠净利{np_}')

        parent, nci = IS.get('归母净利'), IS.get('非控制性权益损益')
        if parent is not None and not approx(parent + (nci or 0), np_, tol):
            errors.append(f'{y} IS 归母{parent}+NCI{nci}≠净利{np_}')

        ta, tl, te = BS.get('资产总额'), BS.get('负债总额'), BS.get('权益总额')
        if None in (ta, te):
            errors.append(f'{y} BS 缺总资产/权益')
        elif tl is not None and not approx(tl + te, ta, tol):
            errors.append(f'{y} BS 负债{tl}+权益{te}≠资产{ta}')

        o, i, f = CF.get('经营活动现金流净额'), CF.get('投资活动现金流净额'), CF.get('融资活动现金流净额')
        net = CF.get('现金及现金等价物净增加')
        if None in (o, i, f, net):
            errors.append(f'{y} CF 缺三段/净增加')
        elif not approx(o + i + f, net, tol):
            errors.append(f'{y} CF 三段{o}+{i}+{f}≠净增{net}')

        beg, end, fx = CF.get('年初现金'), CF.get('年末现金'), CF.get('汇率影响')
        if None in (beg, end):
            errors.append(f'{y} CF 缺年初/年末现金')
        elif not approx(beg + (net or 0) + (fx or 0), end, tol):
            errors.append(f'{y} CF 年初{beg}+净增{net}+汇率{fx}≠年末{end}')

        cash_bs = BS.get('现金及现金等价物')
        if cash_bs is not None and end is not None and not approx(cash_bs, end, tol):
            errors.append(f'{y} 跨表 BS现金{cash_bs}≠CF年末{end}')

        seg_named = {k: v for k, v in SEG.items() if k not in ('合计',)}
        if seg_named and rev is not None:
            s = sum(seg_named.values())
            if not approx(s, rev, max(tol, abs(rev) * 0.002)):
                errors.append(f'{y} 分部和{s}≠收入{rev} ({sorted(seg_named)})')

    # 跨年衔接:年末现金(t) vs 年初现金(t+1) —— 重列年份降为 warning
    RESTATED = {2004, 2007}  # 2005 年报重列 2004;2008 年报重列 2007(业务合并)
    for y in YEARS[:-1]:
        end_t = all_data[y]['CF'].get('年末现金')
        beg_next = all_data[y + 1]['CF'].get('年初现金')
        # beg_next 来自 t+1 年报的本年列——JSON 只存 cy,故年初现金即 t+1 年报口径的 t 年末
        if end_t is None or beg_next is None:
            continue
        tol = 2.0 if y + 1 >= 2013 else 0.01
        if not approx(end_t, beg_next, tol):
            msg = f'{y}年末现金{end_t} ≠ {y+1}年初现金{beg_next}'
            (warns if y in RESTATED else errors).append(msg)
    return errors, warns

# ---------------------------------------------------------------- 写出

def write_csv(fname, header_comment, row_names, getter):
    path = os.path.join(HERE, fname)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow([header_comment])
        w.writerow(['科目'] + [str(y) for y in YEARS])
        for name in row_names:
            row = [name]
            for y in YEARS:
                v = getter(y, name)
                row.append('' if v is None else v)
            if any(c != '' for c in row[1:]):
                w.writerow(row)
    print(f'written {fname}')


def main():
    all_data = load_all()
    errors, warns = validate(all_data)
    for wmsg in warns:
        print(f'WARN(重列已知): {wmsg}')
    if errors:
        print('\n=== 勾稽失败,不写出 CSV ===')
        for e in errors:
            print('FAIL:', e)
        sys.exit(1)
    print(f'勾稽全部通过({len(YEARS)} 年)')

    note = ("# 单位: 人民币百万元(2001-2012 財报原单位为千元,已÷1000;2013 起财报原单位即百万)。"
            "来源: 招股说明书会计师报告(2001-2003)+上市至今全部年报(2004-2025)逐行解析,"
            "见 _extract/*.json 与 _build_from_pdf.py。空格 = 该年无此科目。")
    write_csv('利润表.csv', note + ' 每股数据不入本表(见年报)。', IS_ROWS,
              lambda y, n: all_data[y]['IS'].get(n))
    write_csv('资产负债表.csv', note + ' 流动/非流动双现科目(借款/应付票据/租赁负债/递延收入/FVPL/定期存款等)为两段合计。',
              BS_ROWS, lambda y, n: all_data[y]['BS'].get(n))
    write_csv('现金流量表.csv', note + ' capex=购建固定资产/在建工程/投资物业主行,购买无形资产单列。',
              CF_ROWS, lambda y, n: all_data[y]['CF'].get(n))

    seg_note = ("# 单位: 人民币百万元。分部口径变迁: 2001-2011 互联网增值/移动电信增值/网络广告/其他;"
                "2012-2014 +电子商务交易; 2015-2018 增值服务(并移动电信)/网络广告/其他(并电商);"
                "2019 起金融科技及企业服务单列; 2024 起网络广告更名营销服务。空 = 该年无此口径。")
    write_csv('分部营收.csv', seg_note, SEG_ROWS,
              lambda y, n: all_data[y]['SEG'].get(n))

    write_ratios(all_data)


def write_ratios(all_data):
    """财务比率.csv = scripts/derived.py 通用底 + 腾讯定制层(单一写者 = 本脚本)。"""
    sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'scripts'))
    import derived

    def table(key, row_names):
        return {n: [all_data[y][key].get(n) for y in YEARS] for n in row_names}

    PL = table('IS', IS_ROWS)
    BS = table('BS', BS_ROWS)
    CF = table('CF', CF_ROWS)
    common, unmatched = derived.compute_common_ratios(PL, BS, CF)
    if unmatched:
        print(f'⚠️ derived 未匹配科目: {unmatched}')

    N = len(YEARS)

    def col(tbl, name):
        return [tbl[name][i] for i in range(N)]

    def d(a, b):
        return [None if a[i] is None or not b[i] else a[i] / b[i] for i in range(N)]

    rev = col(PL, '营业收入')
    parent = col(PL, '归母净利')
    npr = col(PL, '年度盈利')
    # 2001-2006 报表无归属拆分行(无重大 NCI):归母 = 年度盈利,供 ROE/分红率联动
    parent = [parent[i] if parent[i] is not None else npr[i] for i in range(N)]
    ta = col(BS, '资产总额')
    deferred = col(BS, '递延收入')
    invest_keys = ['于联营公司的投资', '于联营公司可赎回工具的投资', '于合营公司的投资',
                   '可供出售金融资产', '持有至到期投资', '为交易而持有的金融资产',
                   '以公允价值计量计入损益的金融资产(FVPL)',
                   '以公允价值计量计入其他全面收益的金融资产(FVOCI)', '其他金融资产']
    invest = [sum(BS[k][i] for k in invest_keys if BS[k][i] is not None) for i in range(N)]
    buyback = [None if CF['回购股份支付'][i] is None else abs(CF['回购股份支付'][i]) for i in range(N)]
    div = [None if CF['已付股息(股东)'][i] is None else abs(CF['已付股息(股东)'][i]) for i in range(N)]
    payout_total = [None if div[i] is None and buyback[i] is None
                    else ((div[i] or 0) + (buyback[i] or 0)) for i in range(N)]

    custom = [
        ('递延收入/营收 Deferred revenue/Rev(平台预收蓄水池)', d(deferred, rev), 'pct'),
        ('投资资产/总资产 Investment assets/TA(联营+FVPL+FVOCI等)', d(invest, ta), 'pct'),
        ('分红+回购/归母 Total shareholder return ratio', d(payout_total, parent), 'pct'),
    ]

    path = os.path.join(HERE, '财务比率.csv')
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['# 派生自三表 CSV(通用底 scripts/derived.py + 腾讯定制层,本脚本为唯一写者)。'
                    '比率为小数(0.5=50%),周转为天。港股无扣非披露线,扣非行 n/a;'
                    '2001-2006 报表无归属拆分行(无重大 NCI),归母按年度盈利计。'])
        w.writerow(['指标'] + [str(y) for y in YEARS])
        for name, vals, _fmt in list(common) + custom:
            if all(v is None for v in vals):
                continue
            w.writerow([name] + ['' if v is None else round(v, 4) for v in vals])
    print('written 财务比率.csv')


if __name__ == '__main__':
    main()
