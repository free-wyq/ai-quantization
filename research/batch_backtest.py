"""批量回测: 策略 x 30股票, 默认参数, train/test拆分检测过拟合

用法:
    python research/batch_backtest.py
    python research/batch_backtest.py --strategies midterm
    python research/batch_backtest.py --split 0.7

输出:
    framework/results/batch_summary.csv   — 每只股票每个策略的完整指标
    framework/results/batch_aggregate.csv — 每个策略的跨股票汇总统计
    控制台打印排名表
"""

import sys
import os
import argparse
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
import vectorbt as vbt

from strategies import STRATS
from data.fetcher import fetch_stock_history

warnings.filterwarnings("ignore")

from engine.costs import COST_FEES, COST_SLIPPAGE, INIT_CASH  # 成本模型唯一定义

# ===== 路径 =====
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "framework", "results")


def _load_stock_list():
    """读取 stock_list.csv 获取股票代码和名称"""
    path = os.path.join(DATA_DIR, "stock_list.csv")
    df = pd.read_csv(path)
    return list(zip(df["symbol"].astype(str).str.zfill(6), df["name"]))


def _run_backtest(df, strategy_key, param_overrides=None):
    """对给定数据跑一次回测, 返回指标字典"""
    if param_overrides is None:
        param_overrides = {}
    strategy = STRATS[strategy_key](**param_overrides)
    result = strategy.run(df)
    entries, exits, _ = result[0], result[1], result[2]
    size = result[3] if len(result) > 3 else None

    pf = vbt.Portfolio.from_signals(
        close=df["close"],
        entries=entries,
        exits=exits,
        size=size,
        size_type='percent' if size is not None else None,
        direction="longonly",
        init_cash=INIT_CASH,
        fees=COST_FEES,
        slippage=COST_SLIPPAGE,
    )

    n_trades = int(pf.trades.count())
    try:
        pnls = pf.trades.records_readable["PnL"].values
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        win_rate = (len(wins) / n_trades * 100) if n_trades else 0.0
        sum_loss = float(abs(losses.sum())) if len(losses) else 0.0
        sum_win = float(wins.sum()) if len(wins) else 0.0
        profit_factor = (sum_win / sum_loss) if sum_loss != 0 else 0.0
    except Exception:
        win_rate = 0.0
        profit_factor = 0.0

    total_return = float(pf.total_return()) * 100
    benchmark = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100
    sharpe = float(pf.sharpe_ratio(freq="d", risk_free=0.0))
    max_dd = abs(float(pf.max_drawdown(freq="d"))) * 100

    return {
        "total_return": round(total_return, 2),
        "benchmark": round(benchmark, 2),
        "excess": round(total_return - benchmark, 2),
        "sharpe": round(sharpe, 2),
        "max_dd": round(max_dd, 2),
        "n_trades": n_trades,
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2),
    }


def run_batch(strategies, stock_list, split_ratio, start_date, end_date):
    """批量回测主函数

    Args:
        strategies: 策略key列表
        stock_list: [(symbol, name), ...]
        split_ratio: train占比 (0.7 = 前70%训练, 后30%测试)
        start_date / end_date: 回测区间

    Returns:
        summary_df: 每只股票每个策略的完整指标 (含train/test拆分)
    """
    rows = []
    total = len(strategies) * len(stock_list)
    done = 0

    for symbol, name in stock_list:
        # 读取数据
        df = fetch_stock_history(symbol, start_date, end_date).copy()
        # 透传完整行情列 (含 symbol/成交额/换手率), 复合策略(中期)需要
        keep = ["open", "high", "low", "close", "volume", "amount", "turnover_rate", "symbol"]
        keep = [c for c in keep if c in df.columns]
        df = df[keep].dropna()
        if len(df) < 60:
            print(f"  [跳过] {symbol} {name}: 数据不足({len(df)}行)")
            done += len(strategies)
            continue

        # train/test 拆分
        split_idx = int(len(df) * split_ratio)
        df_train = df.iloc[:split_idx]
        df_test = df.iloc[split_idx:]

        for skey in strategies:
            done += 1
            tag = f"[{done}/{total}] {symbol} {name} x {skey}"
            try:
                # 全量回测
                m_full = _run_backtest(df, skey)
                # train 回测
                m_train = _run_backtest(df_train, skey)
                # test 回测
                m_test = _run_backtest(df_test, skey)

                row = {
                    "symbol": symbol,
                    "name": name,
                    "strategy": skey,
                    "n_bars": len(df),
                    "train_bars": len(df_train),
                    "test_bars": len(df_test),
                    # 全量
                    "full_return": m_full["total_return"],
                    "full_benchmark": m_full["benchmark"],
                    "full_excess": m_full["excess"],
                    "full_sharpe": m_full["sharpe"],
                    "full_max_dd": m_full["max_dd"],
                    "full_trades": m_full["n_trades"],
                    "full_winrate": m_full["win_rate"],
                    "full_pf": m_full["profit_factor"],
                    # train
                    "train_return": m_train["total_return"],
                    "train_sharpe": m_train["sharpe"],
                    "train_max_dd": m_train["max_dd"],
                    "train_trades": m_train["n_trades"],
                    # test
                    "test_return": m_test["total_return"],
                    "test_sharpe": m_test["sharpe"],
                    "test_max_dd": m_test["max_dd"],
                    "test_trades": m_test["n_trades"],
                    # 过拟合指标: train/test一致性
                    "overfit_gap": round(m_train["total_return"] - m_test["total_return"], 2),
                }
                rows.append(row)
                print(f"  {tag}  full={m_full['total_return']:+.1f}%  "
                      f"train={m_train['total_return']:+.1f}%  test={m_test['total_return']:+.1f}%")
            except Exception as e:
                print(f"  {tag}  [错误] {e}")
                rows.append({
                    "symbol": symbol, "name": name, "strategy": skey,
                    "n_bars": len(df), "train_bars": len(df_train), "test_bars": len(df_test),
                    "error": str(e),
                })

    return pd.DataFrame(rows)


def aggregate_summary(summary_df):
    """按策略汇总跨股票统计"""
    agg_rows = []
    for skey in summary_df["strategy"].unique():
        sub = summary_df[summary_df["strategy"] == skey]
        sub = sub.dropna(subset=["full_return"])

        # 超额收益为正的股票数
        beat_benchmark = (sub["full_excess"] > 0).sum()
        # train/test同号（都正或都负）的比例 → 策略一致性
        consistent = ((sub["train_return"] > 0) == (sub["test_return"] > 0)).sum()

        agg_rows.append({
            "strategy": skey,
            "label": STRATS[skey].label,
            "n_stocks": len(sub),
            # 全量统计
            "avg_return": round(sub["full_return"].mean(), 2),
            "median_return": round(sub["full_return"].median(), 2),
            "std_return": round(sub["full_return"].std(), 2),
            "avg_excess": round(sub["full_excess"].mean(), 2),
            "avg_sharpe": round(sub["full_sharpe"].mean(), 2),
            "avg_max_dd": round(sub["full_max_dd"].mean(), 2),
            "avg_winrate": round(sub["full_winrate"].mean(), 2),
            "avg_pf": round(sub["full_pf"].mean(), 2),
            # 跑赢基准
            "beat_count": int(beat_benchmark),
            "beat_rate": round(beat_benchmark / len(sub) * 100, 1) if len(sub) else 0,
            # train/test
            "avg_train_return": round(sub["train_return"].mean(), 2),
            "avg_test_return": round(sub["test_return"].mean(), 2),
            "avg_overfit_gap": round(sub["overfit_gap"].mean(), 2),
            "consistent_count": int(consistent),
            "consistent_rate": round(consistent / len(sub) * 100, 1) if len(sub) else 0,
        })

    agg_df = pd.DataFrame(agg_rows)
    # 按平均超额收益排序
    agg_df = agg_df.sort_values("avg_excess", ascending=False).reset_index(drop=True)
    return agg_df


def print_ranking(agg_df):
    """控制台打印策略排名表"""
    print("\n" + "=" * 100)
    print("  策略排名 (按平均超额收益排序)")
    print("=" * 100)
    header = (f"  {'策略':<12s} {'均收益%':>8s} {'中位%':>8s} {'标准差%':>8s} "
              f"{'超额%':>8s} {'夏普':>6s} {'回撤%':>8s} {'胜率%':>8s} "
              f"{'跑赢':>6s} {'train%':>8s} {'test%':>8s} {'过拟合':>8s} {'一致率%':>8s}")
    print(header)
    print("-" * 100)
    for _, r in agg_df.iterrows():
        line = (f"  {r['label']:<12s} {r['avg_return']:>8.1f} {r['median_return']:>8.1f} "
                f"{r['std_return']:>8.1f} {r['avg_excess']:>8.1f} {r['avg_sharpe']:>6.2f} "
                f"{r['avg_max_dd']:>8.1f} {r['avg_winrate']:>8.1f} "
                f"{r['beat_count']:>3d}/{r['n_stocks']:<2d} "
                f"{r['avg_train_return']:>8.1f} {r['avg_test_return']:>8.1f} "
                f"{r['avg_overfit_gap']:>8.1f} {r['consistent_rate']:>8.1f}")
        print(line)
    print("=" * 100)

    # 解读
    print("\n  解读指南:")
    print("  - 超额% > 0: 策略跑赢买入持有基准")
    print("  - 跑赢: N/30 只股票跑赢基准")
    print("  - train% vs test%: 两者同号且接近 → 策略稳定; train大赚test大亏 → 过拟合")
    print("  - 过拟合: train收益 - test收益, 正值越大越可能过拟合")
    print("  - 一致率%: train/test收益同号的比例, 越高越稳定")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量回测: 策略 x 30股票")
    parser.add_argument("--strategies", nargs="*", default=None,
                        help="指定策略 (默认全部)")
    parser.add_argument("--split", type=float, default=0.7,
                        help="train占比 (默认0.7)")
    parser.add_argument("--start", type=str, default="20210101")
    parser.add_argument("--end", type=str, default="20260821")
    args = parser.parse_args()

    # 策略列表
    all_strats = sorted(STRATS.keys())
    strategies = args.strategies if args.strategies else all_strats

    # 股票列表
    stock_list = _load_stock_list()

    print(f"\n  批量回测启动")
    print(f"  策略: {', '.join(strategies)} ({len(strategies)}个)")
    print(f"  股票: {len(stock_list)}只")
    print(f"  Train/Test拆分: {args.split:.0%} / {1-args.split:.0%}")
    print(f"  区间: {args.start} ~ {args.end}")
    print(f"  总回测次数: {len(strategies) * len(stock_list) * 3} (全量+train+test)\n")

    # 运行
    summary_df = run_batch(strategies, stock_list, args.split, args.start, args.end)

    # 汇总
    agg_df = aggregate_summary(summary_df)

    # 保存
    os.makedirs(RESULTS_DIR, exist_ok=True)
    summary_path = os.path.join(RESULTS_DIR, "batch_summary.csv")
    agg_path = os.path.join(RESULTS_DIR, "batch_aggregate.csv")
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
    agg_df.to_csv(agg_path, index=False, encoding="utf-8-sig")

    # 打印排名
    print_ranking(agg_df)

    print(f"\n  详细数据: {summary_path}")
    print(f"  汇总统计: {agg_path}")
