"""中期量化策略因子库

因子按 EXPERIENCE.md 第十五章「中期策略指标分层 v2」实现:
  signal.py       - 信号因子协议 (SignalFactor Protocol, 仅接口定义)
  exit.py         - 退出 (F14 ATR跟踪止损 / F15 量价背离) + ADX
  market_state.py - 市场状态闸门 (F1 个股广度 / F2 情绪 / F3 板块温度)
  sector_trend.py - 板块趋势 (F4/F5)
  leader.py       - 龙头筛选 (F6-F9)

所有因子函数为纯函数: 输入日K DataFrame, 输出等长、索引对齐的 Series/DataFrame。
状态: 设计稿 v2 的代码落地, 待回测验证。
"""

from framework.factors import signal
from framework.factors import exit as exit
from framework.factors import market_state
from framework.factors import sector_trend
from framework.factors import leader
