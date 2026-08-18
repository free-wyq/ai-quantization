"""MACD 策略

MACD (Moving Average Convergence Divergence) 指数平滑异同移动平均:
- EMA_fast:  快速指数均线 (默认12)
- EMA_slow:  慢速指数均线 (默认26)
- DIF:       快慢EMA之差 (快线)
- DEA:       DIF的9日指数均线 (慢线/信号线)
- MACD柱:    2 * (DIF - DEA)  (用柱状图直观看背离)

交易规则:
- DIF 上穿 DEA (金叉) -> 买入(1)
- DIF 下穿 DEA (死叉) -> 卖出(-1)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from strategy.base import BaseStrategy


class MACDStrategy(BaseStrategy):
    """MACD 金叉死叉策略"""

    def __init__(self, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9):
        super().__init__(
            name=f"MACD({fast_period},{slow_period},{signal_period})策略"
        )
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period

    @staticmethod
    def _ema(series: pd.Series, period: int) -> pd.Series:
        """计算指数移动平均 (EMA)"""
        return series.ewm(span=period, adjust=False).mean()

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        close = df["close"]

        # 1. 计算 DIF (快线) 和 DEA (慢线)
        ema_fast = self._ema(close, self.fast_period)
        ema_slow = self._ema(close, self.slow_period)
        df["dif"] = ema_fast - ema_slow               # 快线
        df["dea"] = self._ema(df["dif"], self.signal_period)  # 慢线/信号线
        df["macd"] = 2 * (df["dif"] - df["dea"])      # MACD 柱状图

        # 2. 生成信号: DIF 在 DEA 上方 -> 持有(1), 下方 -> 空仓(-1)
        df["signal"] = 0
        df.loc[df["dif"] > df["dea"], "signal"] = 1
        df.loc[df["dif"] < df["dea"], "signal"] = -1

        # 3. 只在金叉/死叉那一刻产生交易动作
        df["trade"] = df["signal"].diff().fillna(0).astype(int)

        return df


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from data.fetcher import fetch_stock_history

    strategy = MACDStrategy()
    df = fetch_stock_history("000001", "20240101", "20241231")
    result = strategy.generate_signals(df)

    trades = result[result["trade"] != 0]
    print(f"策略: {strategy.name}")
    print(f"交易次数: {len(trades)}")
    print(trades[["close", "dif", "dea", "macd", "trade"]].head(10))
