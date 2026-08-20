"""向量化策略信号 (替代 backtrader 版)

与 backtrader 的 next() 事件驱动不同, 这里一次性对整个价格序列计算信号:
- entries: 布尔 Series, True 表示该根 K 线产生买入信号
- exits:   布尔 Series, True 表示该根 K 线产生平仓信号
由 run.py 统一交给 vbt.Portfolio.from_signals 跑回测, 框架自动管仓位/手续费/下单。

向量化优势: 改参数秒出结果, 且 vbt 自带 Plotly 交互图(买卖点天然清晰)。
"""


def ma_strategy(df, fast=5, slow=20):
    """双均线交叉 (金叉买入, 死叉平仓)"""
    close = df["close"]
    ma_fast = close.rolling(fast).mean()
    ma_slow = close.rolling(slow).mean()
    # 金叉: 快线上穿慢线; 死叉: 快线下穿慢线
    entries = (ma_fast > ma_slow) & (ma_fast.shift(1) <= ma_slow.shift(1))
    exits = (ma_fast < ma_slow) & (ma_fast.shift(1) >= ma_slow.shift(1))
    return entries.fillna(False), exits.fillna(False)


def macd_strategy(df, fast=12, slow=26, signal=9):
    """MACD 金叉死叉 (DIF 上穿 DEA 买入, 下穿平仓)"""
    close = df["close"]
    ema_fast = close.ewm(span=(fast,), adjust=False).mean()
    ema_slow = close.ewm(span=(slow,), adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=(signal,), adjust=False).mean()
    entries = (dif > dea) & (dif.shift(1) <= dea.shift(1))
    exits = (dif < dea) & (dif.shift(1) >= dea.shift(1))
    return entries.fillna(False), exits.fillna(False)


def turtle_strategy(df, entry=20, exit=20):
    """海龟法则 / 唐奇安通道 (收盘价突破 N 日最高买入, 跌破 N 日最低平仓)

    用 shift(1) 取上一根 K 线的高低点, 避免未来函数。
    """
    high, low, close = df["high"], df["low"], df["close"]
    highest = high.rolling(entry).max().shift(1)   # 上一根为止的 N 日最高
    lowest = low.rolling(exit).min().shift(1)      # 上一根为止的 N 日最低
    entries = close >= highest
    exits = close <= lowest
    return entries.fillna(False), exits.fillna(False)


STRATS = {
    "ma": ma_strategy,
    "macd": macd_strategy,
    "turtle": turtle_strategy,
}
