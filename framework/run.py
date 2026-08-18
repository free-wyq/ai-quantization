"""专业回测运行器 (backtrader)

用法:
    python framework/run.py [策略] [股票代码]
    python framework/run.py turtle 000001
    python framework/run.py ma 000001
    python framework/run.py macd 000001

输出专业绩效报告: 收益率 / 夏普 / 最大回撤 / 胜率 / 盈亏比
可选 --plot 生成收益曲线图 (保存为 framework/result.png)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import backtrader as bt

from data.fetcher import fetch_stock_history
from framework.strategies import MAStrategy, MACDStrategy, TurtleStrategy

STRATS = {
    "ma": MAStrategy,
    "macd": MACDStrategy,
    "turtle": TurtleStrategy,
}


def run(strategy_key: str, symbol: str, do_plot: bool = False):
    # 1. 准备数据 (复用现有 fetcher, 带本地缓存)
    df = fetch_stock_history(symbol, "20260526", "20260818").copy()
    if "openinterest" not in df.columns:
        df["openinterest"] = 0.0
    df = df[["open", "high", "low", "close", "volume", "openinterest"]]
    data_feed = bt.feeds.PandasData(dataname=df)

    # 2. 构建 cerebro (stdstats=False: 关闭默认observer自动添加, 改用下面自定义配色版)
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(data_feed)
    cerebro.addstrategy(STRATS[strategy_key])

    # 初始资金 & 手续费 (与之前一致: 万三)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0003)

    # 仓位管理: 每次买入约 95% 可用资金 (模拟全仓)
    cerebro.addsizer(bt.sizers.PercentSizer, percents=95)

    # 3. 接入专业分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Days, annualize=True,
                        riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")

    # 统一配色: 红=涨/赚, 绿=跌/亏 (A股习惯)
    # Broker 默认会在 stdstats 里自动加, 关掉后需手动加回(资产曲线)
    # 买卖点/盈亏点的颜色在下方 plot 后用 matplotlib 后处理统一
    cerebro.addobserver(bt.observers.Broker)
    cerebro.addobserver(bt.observers.BuySell)
    cerebro.addobserver(bt.observers.Trades)

    # 4. 运行
    init_cash = cerebro.broker.getcash()
    results = cerebro.run()
    strat = results[0]
    final_value = cerebro.broker.getvalue()

    # 5. 提取指标
    sharpe = strat.analyzers.sharpe.get_analysis().get("sharperatio")
    dd = strat.analyzers.drawdown.get_analysis().get("max", {}).get("drawdown")
    rets = strat.analyzers.returns.get_analysis()
    total_return = rets.get("rtot")

    ta = strat.analyzers.trades.get_analysis()
    total = ta.get("total", {}) or {}
    won_d = ta.get("won", {}) or {}
    lost_d = ta.get("lost", {}) or {}
    closed = total.get("closed", 0)
    won = won_d.get("total", 0)
    lost = lost_d.get("total", 0)
    win_rate = (won / closed * 100) if closed else 0.0
    avg_win = won_d.get("pnl", {}).get("average", 0.0) if won else 0.0
    avg_loss = lost_d.get("pnl", {}).get("average", 0.0) if lost else 0.0
    profit_factor = (abs(avg_win / avg_loss) if avg_loss else float("inf"))

    # 基准 (买入持有)
    benchmark = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100

    # 6. 打印专业报告
    print("\n" + "=" * 56)
    print(f"  专业回测报告  [{STRATS[strategy_key].__name__} | {symbol}]")
    print("=" * 56)
    print(f"  初始资金:      {init_cash:>14,.2f}")
    print(f"  最终资产:      {final_value:>14,.2f}")
    print(f"  策略收益率:    {total_return*100:>13.2f}%")
    print(f"  基准收益率:    {benchmark:>13.2f}%")
    print(f"  超额收益:      {total_return*100-benchmark:>13.2f}%")
    print("-" * 56)
    print(f"  夏普比率:      {sharpe:>14.2f}" if sharpe is not None else "  夏普比率:             N/A")
    print(f"  最大回撤:      {dd:>13.2f}%" if dd is not None else "  最大回撤:               N/A")
    print("-" * 56)
    print(f"  交易次数:      {closed:>14}")
    print(f"  盈利/亏损:      {won}/{lost}")
    print(f"  胜率:          {win_rate:>13.2f}%")
    print(f"  平均盈利:      {avg_win:>14.2f}")
    print(f"  平均亏损:      {avg_loss:>14.2f}")
    print(f"  盈亏比:        {profit_factor:>14.2f}" if profit_factor != float("inf") else "  盈亏比:             ∞")
    print("=" * 56)

    # 7. 可选绘图
    if do_plot:
        try:
            # 先拿图对象(不自动保存), 再统一后处理配色
            figs = cerebro.plot(style="candlestick",
                                barup="red", barupfill=True,        # 上涨K线: 红色实心
                                bardown="green", bardownfill=True,  # 下跌K线: 绿色实心
                                volup="red", voldown="green",       # 成交量柱: 涨红跌绿
                                voloverlay=False,                   # 成交量单独成图, 不与K线重叠
                                plotdist=0.02,
                                savefig=False)
            # 后处理: 买卖点/盈亏点统一成 红=涨/赚, 绿=跌/亏
            obs_color = {"buy": "red", "sell": "green",
                         "pnlplus": "red", "pnlminus": "green"}
            out_path = os.path.join(os.path.dirname(__file__), "result.png")
            for fig_group in figs:
                # backtrader 返回两层列表 [ [fig1, ...] ], 需展平
                fig_list = fig_group if isinstance(fig_group, (list, tuple)) else [fig_group]
                for fig in fig_list:
                    for ax in fig.axes:
                        for line in ax.get_lines():
                            label = line.get_label()
                            for key, col in obs_color.items():
                                if label.endswith(key):
                                    line.set_color(col)
                            if label.endswith("buy"):
                                line.set_marker("^")
                                line.set_markersize(14)
                                line.set_markeredgecolor("darkred")
                                line.set_markeredgewidth(1.5)
                                line.set_zorder(10)
                            elif label.endswith("sell"):
                                line.set_marker("v")
                                line.set_markersize(14)
                                line.set_markeredgecolor("darkgreen")
                                line.set_markeredgewidth(1.5)
                                line.set_zorder(10)
                    fig.savefig(out_path, dpi=150)
            print(f"  收益曲线已保存: framework/result.png")
        except Exception as e:
            print(f"  绘图失败 (可忽略): {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="专业回测运行器")
    parser.add_argument("strategy", nargs="?", default="turtle",
                        choices=list(STRATS.keys()))
    parser.add_argument("symbol", nargs="?", default="000001")
    parser.add_argument("--plot", action="store_true", help="生成收益曲线图", default=type)
    args = parser.parse_args()
    run(args.strategy, args.symbol, args.plot)
