"""参数优化器: 网格搜索 + 样本外验证

用法:
    python framework/run.py ma 000001 --optimize
    python framework/run.py regime 000001 --optimize

流程:
    1. 将数据按 7:3 拆分为训练集 / 测试集
    2. 遍历所有参数组合, 在训练集上回测
    3. 取训练集夏普最高的 Top 10, 在测试集上验证
    4. 对比样本内外表现, 检测过拟合
"""

import sys
import os
import itertools
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import vectorbt as vbt
import pandas as pd

from data.fetcher import fetch_stock_history
from framework.strategies import STRATS

# ===== 各策略参数搜索网格 =====
PARAM_GRIDS = {
    "ma":      {"fast": [3, 5, 10], "slow": [10, 20, 30, 60]},
    "macd":    {"fast": [8, 12, 16], "slow": [20, 26, 30], "signal": [7, 9, 11]},
    "adx":     {"period": [10, 14, 20], "threshold": [20, 25, 30]},
    "rsi":     {"period": [7, 14, 21], "oversold": [30, 35, 40], "overbought": [60, 65, 70]},
    "obv":     {"ma_period": [10, 15, 20, 30]},
    "regime":  {"trend_threshold": [20, 25, 30], "range_threshold": [15, 20, 25]},
    "turtle":  {"entry": [10, 15, 20, 30], "exit": [5, 10, 15, 20]},
    "midterm": {
        "ma_period": [10, 20, 30],
        "vol_min": [1.0, 1.2, 1.5],
        "vol_lookback": [3, 5],
        "mult_weak": [1.5, 2.0, 2.5],
        "mult_strong": [3.0, 3.5],
        "no_weekly": [False, True],
        "no_vol": [False, True],
    },
}

TRAIN_RATIO = 0.7  # 70% 训练集, 30% 测试集


def _quick_backtest(df, strategy_key, params):
    """快速回测, 返回 (收益率%, 夏普, 最大回撤%, 交易次数)"""
    strategy = STRATS[strategy_key](**params)
    result = strategy.run(df)
    # 兼容不同策略返回值数量 (3~5个)
    entries, exits = result[0], result[1]
    pf = vbt.Portfolio.from_signals(
        close=df["close"],
        entries=entries,
        exits=exits,
        direction="longonly",
        init_cash=100000.0,
        fees=0.0008,
        slippage=0.001,
    )
    total_return = float(pf.total_return()) * 100
    sharpe = float(pf.sharpe_ratio(freq="d", risk_free=0.0))
    max_dd = abs(float(pf.max_drawdown(freq="d"))) * 100
    n_trades = int(pf.trades.count())
    return total_return, sharpe, max_dd, n_trades


def optimize(strategy_key, symbol, start="20250101", end="20260818"):
    """网格搜索 + 样本外验证"""
    # 1. 获取数据
    df = fetch_stock_history(symbol, start, end).copy()
    df = df[["open", "high", "low", "close", "volume"]].dropna()

    # 2. 训练/测试拆分 (时间序列, 不能随机打乱)
    split_idx = int(len(df) * TRAIN_RATIO)
    df_train = df.iloc[:split_idx]
    df_test = df.iloc[split_idx:]

    print(f"\n{'=' * 80}")
    print(f"  参数优化器  [{STRATS[strategy_key].label} | {symbol}]")
    print(f"{'=' * 80}")
    print(f"  数据: {symbol} 共 {len(df)} 天")
    print(f"  训练集: {df_train.index[0].date()} ~ {df_train.index[-1].date()} ({len(df_train)} 天)")
    print(f"  测试集: {df_test.index[0].date()} ~ {df_test.index[-1].date()} ({len(df_test)} 天)")

    # 3. 生成参数组合
    grid = PARAM_GRIDS.get(strategy_key)
    if not grid:
        print(f"\n  策略 {strategy_key} 未定义参数网格, 跳过优化")
        print(f"  可优化策略: {', '.join(PARAM_GRIDS.keys())}")
        return

    keys = list(grid.keys())
    combos = list(itertools.product(*[grid[k] for k in keys]))
    print(f"  搜索空间: {len(combos)} 个参数组合")
    print(f"{'=' * 80}")

    # 4. 逐个回测 (训练集 + 测试集)
    results = []
    for i, combo in enumerate(combos):
        params = dict(zip(keys, combo))
        try:
            tr_ret, tr_sharpe, tr_dd, tr_n = _quick_backtest(df_train, strategy_key, params)
            te_ret, te_sharpe, te_dd, te_n = _quick_backtest(df_test, strategy_key, params)
            results.append({
                "params": params,
                "is_return": tr_ret, "is_sharpe": tr_sharpe, "is_dd": tr_dd, "is_trades": tr_n,
                "oos_return": te_ret, "oos_sharpe": te_sharpe, "oos_dd": te_dd, "oos_trades": te_n,
            })
        except Exception:
            pass  # 跳过无效参数组合

    if not results:
        print("\n  无有效结果, 请检查参数网格")
        return

    # 5. 过滤无效结果 (0交易 或 inf夏普) 并按训练集夏普排序
    results = [r for r in results if r["is_trades"] > 0 and math.isfinite(r["is_sharpe"])]
    if not results:
        print("\n  所有参数组合均无有效交易, 无法优化")
        return
    results.sort(key=lambda x: x["is_sharpe"], reverse=True)

    # 6. 打印 Top 10
    print(f"\n{'排名':>4}  {'参数':<35}  {'IS夏普':>7} {'IS收益':>7} {'IS回撤':>7}  {'OOS夏普':>7} {'OOS收益':>7} {'OOS回撤':>7}  {'过拟合':>6}")
    print("-" * 110)

    for i, r in enumerate(results[:10]):
        if r["is_sharpe"] > 0 and math.isfinite(r["oos_sharpe"]):
            ratio = r["oos_sharpe"] / r["is_sharpe"]
            overfit = "!!" if ratio < 0.5 else "OK"
        else:
            ratio = 0
            overfit = "-" if r["oos_sharpe"] != r["oos_sharpe"] else "OK"

        params_str = ", ".join(f"{k}={v}" for k, v in r["params"].items())
        print(f"  {i+1:>2}  {params_str:<35}  {r['is_sharpe']:>7.2f} {r['is_return']:>6.1f}% {r['is_dd']:>6.1f}%  {r['oos_sharpe']:>7.2f} {r['oos_return']:>6.1f}% {r['oos_dd']:>6.1f}%  {overfit:>6}")

    print("=" * 110)

    # 7. 推荐最优参数
    best = results[0]
    print(f"\n  >> 推荐参数: {best['params']}")
    print(f"     训练集: 夏普={best['is_sharpe']:.2f}, 收益={best['is_return']:.1f}%, 回撤={best['is_dd']:.1f}%, 交易={best['is_trades']}次")
    print(f"     测试集: 夏普={best['oos_sharpe']:.2f}, 收益={best['oos_return']:.1f}%, 回撤={best['oos_dd']:.1f}%, 交易={best['oos_trades']}次")

    # 8. 过拟合检测
    if best["is_sharpe"] > 0 and math.isfinite(best["oos_sharpe"]):
        ratio = best["oos_sharpe"] / best["is_sharpe"]
        if ratio < 0.5:
            print(f"\n  [!] 过拟合警告: 样本外夏普仅为样本内的 {ratio*100:.0f}%")
            print(f"      建议: 减少参数数量 / 放宽参数范围 / 增加样本量")
        else:
            print(f"\n  [OK] 样本外夏普为样本内的 {ratio*100:.0f}%, 未明显过拟合")
    elif not math.isfinite(best["oos_sharpe"]):
        print(f"\n  [!] 样本外无有效交易, 无法判断过拟合")

    # 9. 基准对比
    bench_train = (df_train["close"].iloc[-1] / df_train["close"].iloc[0] - 1) * 100
    bench_test = (df_test["close"].iloc[-1] / df_test["close"].iloc[0] - 1) * 100
    print(f"\n  基准 (买入持有): 训练集 {bench_train:.1f}%, 测试集 {bench_test:.1f}%")
    if best["oos_return"] > bench_test:
        print(f"  [OK] 样本外收益 {best['oos_return']:.1f}% 跑赢基准 {bench_test:.1f}%")
    else:
        print(f"  [!] 样本外收益 {best['oos_return']:.1f}% 未跑赢基准 {bench_test:.1f}%")

    # 10. 使用建议
    print(f"\n  使用推荐参数运行:")
    param_str = " ".join(f"-p {k}={v}" for k, v in best["params"].items())
    print(f"  python framework/run.py {strategy_key} {symbol} {param_str}")
    print()
