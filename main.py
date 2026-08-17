"""AI 量化交易系统 - 主入口"""

from utils.logger import log
from data.fetcher import fetch_stock_history
from strategy.ma_cross import MACrossStrategy
from backtest.engine import BacktestEngine


def main():
    log.info("=" * 50)
    log.info("AI 量化交易系统启动")
    log.info("=" * 50)

    # 1. 获取行情数据
    symbol = "000001"  # 平安银行
    df = fetch_stock_history(symbol, "20240101", "20241231")

    # 2. 运行策略
    strategy = MACrossStrategy(short_period=5, long_period=20)
    log.info(f"使用策略: {strategy.name}")
    df = strategy.generate_signals(df)

    # 3. 回测
    engine = BacktestEngine()
    result = engine.run(df)

    # 4. 输出结果
    engine.print_result(result)


if __name__ == "__main__":
    main()
