"""市场级因子库

因子按 DESIGN.md 第二部分「七层闭环架构」实现:
  market_state.py - 市场状态闸门 (F1 个股广度 / F2 情绪 / F3 板块温度)
  sector_trend.py - 板块趋势 (F4/F5)
  leader.py       - 龙头筛选 (F6-F9)
  cross_stock.py  - 跨股票状态缓存 (闸门/板块/龙头全市场状态, 按 symbol 切片)
  flow.py         - 资金面 (北向资金净流入 / 个股主力净流入, akshare 东财)
  fundamental.py  - 基本面排雷 (PE/PB分位 / ROE / 商誉占比, 百度估值+新浪财务)

所有因子函数为纯函数: 输入日K DataFrame, 输出等长、索引对齐的 Series/DataFrame。
状态: 设计稿 v2 的代码落地, 待回测验证。
"""

from framework.factors import market_state
from framework.factors import sector_trend
from framework.factors import leader
from framework.factors import cross_stock
from framework.factors import flow
from framework.factors import fundamental
