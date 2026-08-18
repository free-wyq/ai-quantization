"""基于 backtrader 的专业策略实现

相比手写的玩具策略, 这里用 backtrader 的事件驱动框架:
- 框架自动管理仓位、手续费、下单
- 配合 Analyzer 可直接输出夏普比率、最大回撤、胜率等
"""

import backtrader as bt


class MAStrategy(bt.Strategy):
    """双均线交叉策略 (backtrader 版)"""

    params = (("fast", 5), ("slow", 20))

    def __init__(self):
        self.ma_fast = bt.ind.SMA(period=self.p.fast)
        self.ma_slow = bt.ind.SMA(period=self.p.slow)
        self.crossover = bt.ind.CrossOver(self.ma_fast, self.ma_slow)

    def next(self):
        if not self.position:
            if self.crossover > 0:
                self.buy()
        elif self.crossover < 0:
            self.close()


class MACDStrategy(bt.Strategy):
    """MACD 金叉死叉策略 (backtrader 版)"""

    params = (("fast", 12), ("slow", 26), ("signal", 9))

    def __init__(self):
        self.macd = bt.ind.MACD(
            period_me1=self.p.fast,
            period_me2=self.p.slow,
            period_signal=self.p.signal,
        )
        self.crossover = bt.ind.CrossOver(self.macd.macd, self.macd.signal)

    def next(self):
        if not self.position:
            if self.crossover > 0:
                self.buy()
        elif self.crossover < 0:
            self.close()


class TurtleStrategy(bt.Strategy):
    """海龟法则 / 唐奇安通道 (backtrader 版)

    入场: 收盘价突破 N 日最高 (上轨)
    离场: 收盘价跌破 N 日最低 (下轨)
    用 [-1] 取上一根K线的高/低点, 避免未来函数
    """

    params = (("entry", 20), ("exit", 20))

    def __init__(self):
        self.highest = bt.ind.Highest(self.data.high, period=self.p.entry)
        self.lowest = bt.ind.Lowest(self.data.low, period=self.p.exit)

    def next(self):
        if not self.position:
            if self.data.close[0] >= self.highest[-1]:
                self.buy()
        else:
            if self.data.close[0] <= self.lowest[-1]:
                self.close()
