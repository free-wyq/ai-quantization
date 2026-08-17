"""简易回测引擎

用于评估策略在历史数据上的表现。
"""

import pandas as pd
import numpy as np
from loguru import logger

from config.settings import BACKTEST_CONFIG


class BacktestEngine:
    """简易回测引擎"""

    def __init__(self, config: dict = None):
        self.config = config or BACKTEST_CONFIG
        self.initial_capital = self.config["initial_capital"]
        self.commission = self.config["commission"]

    def run(self, df: pd.DataFrame) -> dict:
        """
        运行回测

        Args:
            df: 包含 trade 列的 DataFrame (1=买入, -1=卖出, 0=无操作)

        Returns:
            回测结果字典
        """
        capital = self.initial_capital
        position = 0  # 持仓数量
        trades = []

        for date, row in df.iterrows():
            price = row["close"]
            signal = row.get("trade", 0)

            if signal > 0 and position == 0:
                # 买入
                shares = int(capital / (price * (1 + self.commission)))
                if shares > 0:
                    cost = shares * price * (1 + self.commission)
                    capital -= cost
                    position = shares
                    trades.append({
                        "date": date, "action": "BUY",
                        "price": price, "shares": shares, "cost": cost
                    })

            elif signal < 0 and position > 0:
                # 卖出
                revenue = position * price * (1 - self.commission)
                capital += revenue
                trades.append({
                    "date": date, "action": "SELL",
                    "price": price, "shares": position, "revenue": revenue
                })
                position = 0

        # 计算最终资产
        final_price = df["close"].iloc[-1]
        total_assets = capital + position * final_price

        # 计算指标
        total_return = (total_assets - self.initial_capital) / self.initial_capital
        benchmark_return = (df["close"].iloc[-1] - df["close"].iloc[0]) / df["close"].iloc[0]

        result = {
            "initial_capital": self.initial_capital,
            "final_assets": round(total_assets, 2),
            "total_return": f"{total_return:.2%}",
            "benchmark_return": f"{benchmark_return:.2%}",
            "excess_return": f"{total_return - benchmark_return:.2%}",
            "trade_count": len(trades),
            "trades": trades,
        }

        logger.info(f"回测完成: 最终资产 {result['final_assets']}, 收益率 {result['total_return']}")
        return result

    @staticmethod
    def print_result(result: dict):
        """打印回测结果"""
        print("=" * 50)
        print("  回测结果")
        print("=" * 50)
        print(f"  初始资金:   {result['initial_capital']:>14,.2f}")
        print(f"  最终资产:   {result['final_assets']:>14,.2f}")
        print(f"  策略收益率: {result['total_return']:>14}")
        print(f"  基准收益率: {result['benchmark_return']:>14}")
        print(f"  超额收益:   {result['excess_return']:>14}")
        print(f"  交易次数:   {result['trade_count']:>14}")
        print("=" * 50)


if __name__ == "__main__":
    from data.fetcher import fetch_stock_history
    from strategy.ma_cross import MACrossStrategy

    # 获取数据
    df = fetch_stock_history("000001", "20240101", "20241231")

    # 生成信号
    strategy = MACrossStrategy(short_period=5, long_period=20)
    df = strategy.generate_signals(df)

    # 回测
    engine = BacktestEngine()
    result = engine.run(df)
    engine.print_result(result)
