"""海龟法则 (Turtle Trading / 唐奇安通道) 策略

经典趋势跟踪策略, 由 Richard Dennis 与 William Eckhardt 在 1983 年提出。
核心思想: 捕捉单边大趋势, "让利润奔跑"。

原版规则 (简化实现):
- 入场: 价格突破 N 日最高价 (唐奇安通道上轨) -> 买入
- 离场: 价格跌破 N 日最低价 (唐奇安通道下轨) -> 卖出
- ATR: 平均真实波幅, 用于衡量波动、控制仓位/加仓步长

本实现:
- 上轨 = N 日最高价 (默认 20 日, 海龟的 "55日" 是中周期, 20日是短周期)
- 下轨 = N 日最低价 (默认 20 日)
- 金叉(突破上轨)买入, 死叉(跌破下轨)卖出, 与现有回测引擎 trade 列兼容
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from strategy.base import BaseStrategy


class TurtleStrategy(BaseStrategy):
    """海龟法则 (唐奇安通道) 策略"""

    def __init__(self, entry_period: int = 20, exit_period: int = 20):
        """
        Args:
            entry_period: 入场通道周期 (突破 N 日最高)
            exit_period:  离场通道周期 (跌破 N 日最低)
        """
        super().__init__(
            name=f"海龟法则(入场{entry_period}日/离场{exit_period}日)"
        )
        self.entry_period = entry_period
        self.exit_period = exit_period

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        # 1. 计算唐奇安通道: 上轨(最高价)和下轨(最低价)
        df["upper"] = df["high"].rolling(self.entry_period).max()  # 上轨: N日最高
        df["lower"] = df["low"].rolling(self.exit_period).min()    # 下轨: N日最低

        # 2. 计算 ATR (平均真实波幅), 衡量波动
        prev_close = df["close"].shift(1)
        tr = pd.concat([
            (df["high"] - df["low"]),
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ], axis=1).max(axis=1)
        df["atr"] = tr.rolling(14).mean()  # 14日 ATR

        # 3. 生成信号 (状态机):
        #    突破上轨 -> 持有(1), 跌破下轨 -> 空仓(-1), 中间保持原状态
        #    注意: 不能简单用 close>=upper 赋值, 否则非突破日 signal 变 0 会"一买就卖"
        signals = []
        pos = 0  # 当前状态: 1=持有, -1=空仓
        for _, row in df.iterrows():
            if row["close"] >= row["upper"]:
                pos = 1
            elif row["close"] <= row["lower"]:
                pos = -1
            signals.append(pos)
        df["signal"] = signals

        # 4. 只在突破/跌破那一刻产生交易动作
        df["trade"] = df["signal"].diff().fillna(0).astype(int)

        return df


if __name__ == "__main__":
    from data.fetcher import fetch_stock_history

    strategy = TurtleStrategy()
    df = fetch_stock_history("000001", "20240101", "20241231")
    result = strategy.generate_signals(df)

    trades = result[result["trade"] != 0]
    print(f"策略: {strategy.name}")
    print(f"交易次数: {len(trades)}")
    print(trades[["close", "upper", "lower", "atr", "trade"]].head(10))
