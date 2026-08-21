"""专业回测运行器 (vectorbt 向量化)

用法:
    python framework/run.py [策略] [股票代码] [-p key=value ...]
    python framework/run.py turtle 000001
    python framework/run.py ma 000001 -p fast=10 slow=30
    python framework/run.py macd 000001
    python framework/run.py multi_factor 000001
    python framework/run.py --list

自研策略: 在 framework/strategies/custom/ 下新建 .py 文件,
          定义 Strategy 子类即可被框架自动发现, 无需修改框架代码。

输出专业绩效报告: 收益率 / 夏普 / 最大回撤 / 胜率 / 盈亏比
每次运行会把结果写入 framework/results/, 并自动生成离线看板 dashboard.html
(用 klinecharts 画 K 线 + 买卖点, 浏览器打开下拉切换历史记录)
"""

import sys
import os
import json
import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import vectorbt as vbt
import pandas as pd

from data.fetcher import fetch_stock_history
from framework.strategies import STRATS

# ===== 结果看板相关路径 =====
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
RUNS_DIR = os.path.join(RESULTS_DIR, "runs")
MAX_RUNS = 50  # 最多保留最近 50 次运行


def _export_result(strategy_key, symbol, df, entries, exits, pf, metrics, indicators):
    """把本次回测结果写成独立 JSON 文件 (按 代码_策略_时间 命名), 并重建看板。"""
    os.makedirs(RUNS_DIR, exist_ok=True)
    now = datetime.datetime.now()
    ts = now.strftime("%Y%m%d_%H%M%S")

    candles = []
    for i in range(len(df)):
        candles.append({
            "timestamp": int(df.index[i].timestamp() * 1000),
            "open": round(float(df["open"].iloc[i]), 2),
            "high": round(float(df["high"].iloc[i]), 2),
            "low": round(float(df["low"].iloc[i]), 2),
            "close": round(float(df["close"].iloc[i]), 2),
            "volume": float(df["volume"].iloc[i]),
        })

    # 从 vectorbt 实际成交记录提取买卖点 (而非原始信号, 避免无持仓时的虚假卖出)
    buys, sells = [], []
    try:
        trades_df = pf.trades.records_readable
        for _, row in trades_df.iterrows():
            entry_ts = int(pd.Timestamp(row["Entry Timestamp"]).timestamp() * 1000)
            exit_ts = int(pd.Timestamp(row["Exit Timestamp"]).timestamp() * 1000)
            entry_price = round(float(row["Avg Entry Price"]), 2)
            exit_price = round(float(row["Avg Exit Price"]), 2)
            pnl = round(float(row["PnL"]), 2)
            ret = round(float(row["Return"]) * 100, 2)
            buys.append({"timestamp": entry_ts, "price": entry_price})
            sells.append({"timestamp": exit_ts, "price": exit_price,
                          "pnl": pnl, "return": ret})
    except Exception as e:
        print(f"  [警告] 提取成交记录失败: {e}")

    value = pf.value()
    equity = [{
        "timestamp": int(value.index[i].timestamp() * 1000),
        "value": round(float(value.iloc[i]), 2),
    } for i in range(len(value))]

    run_data = {
        "id": ts,
        "label": f"{strategy_key.upper()} {symbol} {now.strftime('%Y-%m-%d %H:%M')}",
        "file": f"{symbol}_{strategy_key}_{ts}.json",
        "strategy": strategy_key,
        "symbol": symbol,
        "metrics": metrics,
        "candles": candles,
        "buys": buys,
        "sells": sells,
        "equity": equity,
        "indicators": indicators,
    }

    # 每次运行写一个独立文件, 文件名含 代码_策略_时间
    filename = run_data["file"]
    json.dump(run_data, open(os.path.join(RUNS_DIR, filename), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    print(f"  结果已存档: framework/results/runs/{filename}")
    print(f"  看板服务:   framework/ 目录下执行  python serve_dashboard.py")
    print(f"  浏览器打开: http://localhost:8000/framework/results/dashboard.html")
    print(f"  (每次刷新页面都会自动加载最新回测记录)")


def run(strategy_key: str, symbol: str, do_plot: bool = False, param_overrides: dict = None):
    if param_overrides is None:
        param_overrides = {}
    # 1. 准备数据 (复用现有 fetcher, 带本地缓存)
    df = fetch_stock_history(symbol, "20260101", "20260818").copy()
    df = df[["open", "high", "low", "close", "volume"]].dropna()

    # 2. 计算策略信号 (向量化, 一次性算完)
    strategy = STRATS[strategy_key](**param_overrides)
    entries, exits, indicators = strategy.run(df)

    # 3. 向量化回测: 手续费万三, 初始资金10万, 满仓做多
    pf = vbt.Portfolio.from_signals(
        close=df["close"],
        entries=entries,
        exits=exits,
        direction="longonly",
        init_cash=100000.0,
        fees=0.0003,
    )

    # 4. 提取指标 (vbt 需要显式频率才能年化; 日频用 freq='d')
    init_cash = 100000.0
    final_value = float(pf.value().iloc[-1])
    total_return = float(pf.total_return()) * 100
    benchmark = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100

    sharpe = float(pf.sharpe_ratio(freq="d", risk_free=0.0))
    max_dd = abs(float(pf.max_drawdown(freq="d"))) * 100

    n_trades = int(pf.trades.count())
    # 从 records_readable 提取 PnL 数组手动计算 (pf.trades.won/lost 在此版本不可用)
    try:
        pnls = pf.trades.records_readable["PnL"].values
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        win_rate = (len(wins) / n_trades * 100) if n_trades else 0.0
        sum_win = float(wins.sum()) if len(wins) else 0.0
        sum_loss = float(abs(losses.sum())) if len(losses) else 0.0
        profit_factor = (sum_win / sum_loss) if sum_loss != 0 else float("inf")
    except Exception:
        win_rate = 0.0
        profit_factor = float("inf")

    metrics = {
        "total_return": round(total_return, 2),
        "benchmark": round(benchmark, 2),
        "excess": round(total_return - benchmark, 2),
        "sharpe": round(sharpe, 2),
        "max_dd": round(max_dd, 2),
        "n_trades": n_trades,
        "win_rate": round(win_rate, 2),
        "profit_factor": profit_factor,
    }

    # 5. 打印专业报告
    print("\n" + "=" * 56)
    print(f"  专业回测报告  [{strategy.label} | {symbol}]  (vectorbt)")
    print("=" * 56)
    print(f"  初始资金:      {init_cash:>14,.2f}")
    print(f"  最终资产:      {final_value:>14,.2f}")
    print(f"  策略收益率:    {total_return:>13.2f}%")
    print(f"  基准收益率:    {benchmark:>13.2f}%")
    print(f"  超额收益:      {total_return-benchmark:>13.2f}%")
    print("-" * 56)
    print(f"  夏普比率:      {sharpe:>14.2f}")
    print(f"  最大回撤:      {max_dd:>13.2f}%")
    print("-" * 56)
    print(f"  交易次数:      {n_trades:>14}")
    print(f"  胜率:          {win_rate:>13.2f}%")
    print(f"  盈亏比:        {profit_factor:>14.2f}" if profit_factor != float("inf") else "  盈亏比:             ∞")
    print("=" * 56)

    # 6. 导出结果 + 生成离线看板
    if do_plot:
        _export_result(strategy_key, symbol, df, entries, exits, pf, metrics, indicators)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="专业回测运行器 (vectorbt)")
    parser.add_argument("strategy", nargs="?", default="macd",
                        choices=list(STRATS.keys()))
    parser.add_argument("symbol", nargs="?", default="000001")
    parser.add_argument("--plot", default=True, help="导出结果并生成离线看板")
    parser.add_argument("-p", "--params", nargs="*", default=[],
                        help="策略参数覆盖, 格式: key=value (如: ma_slow=30)")
    parser.add_argument("--list", action="store_true", help="列出所有可用策略")
    args = parser.parse_args()

    if args.list:
        print("\n可用策略:")
        for key, cls in sorted(STRATS.items()):
            params_str = ", ".join(f"{k}={v}" for k, v in cls.params.items())
            print(f"  {key:16s} {cls.label:16s} 参数: {params_str}")
        sys.exit(0)

    # 解析参数覆盖: ["ma_slow=30", "rsi_period=21"] -> {"ma_slow": 30, "rsi_period": 21}
    overrides = {}
    for item in args.params:
        if "=" in item:
            k, v = item.split("=", 1)
            try:
                v = int(v)
            except ValueError:
                try:
                    v = float(v)
                except ValueError:
                    pass
            overrides[k] = v

    run(args.strategy, args.symbol, args.plot, overrides)
