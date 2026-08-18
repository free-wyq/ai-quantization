"""双均线交叉策略 (MA Cross)

当短期均线上穿长期均线时买入，下穿时卖出。
"""

import pandas as pd
from strategy.base import BaseStrategy


class MACrossStrategy(BaseStrategy):
    """双均线交叉策略"""

    def __init__(self, short_period: int = 5, long_period: int = 20):
        super().__init__(name=f"MA({short_period},{long_period})交叉策略")
        self.short_period = short_period
        self.long_period = long_period

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        # 计算均线
        df["ma_short"] = df["close"].rolling(self.short_period).mean()
        df["ma_long"] = df["close"].rolling(self.long_period).mean()

        # 生成信号: 短期均线上穿长期均线 -> 买入(1), 下穿 -> 卖出(-1)
        df["signal"] = 0
        df.loc[df["ma_short"] > df["ma_long"], "signal"] = 1
        df.loc[df["ma_short"] < df["ma_long"], "signal"] = -1

        # 只在交叉点产生交易信号
        df["trade"] = df["signal"].diff().fillna(0).astype(int)

        return df


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from data.fetcher import fetch_stock_history

    strategy = MACrossStrategy(short_period=5, long_period=20)
    df = fetch_stock_history("000001", "20240101", "20241231")
    result = strategy.generate_signals(df)

    # 查看交易信号
    trades = result[result["trade"] != 0]
    print(f"策略: {strategy.name}")
    print(f"交易次数: {len(trades)}")
    print(trades[["close", "ma_short", "ma_long", "trade"]].head(10))
