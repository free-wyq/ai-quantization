"""midterm 参数对比脚本 — 改完参数跑这个, 一眼看出哪组好。

用途:
  每次 run.py 不知道参数怎么设时, 在 PRESETS 里加几组候选参数组合,
  跑本脚本即可横向对比 收益/回撤/胜率/盈亏比, 找出最优组再写进 run 命令。

用法:
  python scripts/compare_params.py                     # 默认: 5股 × 所有预设组合
  python scripts/compare_params.py 000001 002475       # 指定股票
  python scripts/compare_params.py --start 20220101    # 改区间
  python scripts/compare_params.py --show-cmd          # 打印最优组合的 run.py 命令

注意:
  - 用 Windows venv: ./venv/Scripts/python.exe scripts/compare_params.py
  - 数据来自 data/{symbol}_daily.csv 缓存 (断网可用)
  - 成本模型与 run.py 一致 (COST_FEES=0.0008, COST_SLIPPAGE=0.001, init_cash=10万)
"""
from __future__ import annotations

import os
import sys
import argparse
import pandas as pd
import vectorbt as vbt

# 让脚本能 import framework (无论从哪运行)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from framework.strategies.midterm import MidTermStrategy  # noqa: E402

# A股成本模型 (与 run.py / batch_backtest.py 一致)
COST_FEES = 0.0008
COST_SLIPPAGE = 0.001
INIT_CASH = 100000.0
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# 默认测试股票池 (data/ 下有缓存的)
DEFAULT_STOCKS = ["000001", "600519", "000858", "300750", "002475"]


# ===== 预设参数组合: 在这里加你要对比的组 =====
# 每组: (组名, {参数覆盖}; {} 表示用策略类默认值)
# 改完直接跑脚本, 不需要改其他代码
PRESETS = [
    ("默认(当前线上)", {}),
    ("关利润保护(旧)", {"profit_tighten": None, "max_retracement": 0.10}),
    ("利润保护激进",   {"profit_tighten": [(0.05, 2.0), (0.10, 1.5), (0.20, 1.0)],
                          "max_retracement": 0.20}),
    ("利润保护保守",   {"profit_tighten": [(0.15, 2.5), (0.30, 2.0)],
                          "max_retracement": 0.30}),
    ("开趋势反转退出", {"use_signal_exit": True}),
    ("宽止损吃趋势",   {"mult_strong": 4.0, "mult_weak": 2.5, "max_retracement": 0.30}),
    ("窄止损防回撤",   {"mult_strong": 3.0, "mult_weak": 1.5, "max_retracement": 0.15}),
]


def load_df(symbol: str, start: str, end: str) -> pd.DataFrame:
    path = os.path.join(DATA_DIR, f"{symbol}_daily.csv")
    if not os.path.exists(path):
        print(f"  [跳过] {symbol}: 无缓存 {path}")
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    df = df.loc[s:e]
    if len(df) < 60:
        print(f"  [跳过] {symbol}: 区间内数据不足({len(df)}行)")
        return None
    return df


def backtest(df: pd.DataFrame, params: dict) -> dict:
    """跑一次回测, 返回指标字典。"""
    strategy = MidTermStrategy(**params)
    result = strategy.run(df)
    entries, exits = result[0], result[1]

    pf = vbt.Portfolio.from_signals(
        close=df["close"].astype(float),
        entries=entries,
        exits=exits,
        direction="longonly",
        init_cash=INIT_CASH,
        fees=COST_FEES,
        slippage=COST_SLIPPAGE,
        freq="d",
    )

    try:
        rets = pf.trades.records_readable["Return"].dropna()
        n = len(rets)
        wins = rets[rets > 0]
        losses = rets[rets < 0]
        win_rate = (len(wins) / n * 100) if n else 0.0
        avg_win = wins.mean() if len(wins) else 0.0
        avg_loss = losses.abs().mean() if len(losses) else 0.0
        profit_factor = (avg_win / avg_loss) if avg_loss > 0 else float("inf")
    except Exception:
        win_rate, profit_factor, n = 0.0, 0.0, 0

    return {
        "收益%": round(pf.total_return() * 100, 1),
        "回撤%": round(abs(pf.max_drawdown()) * 100, 1),
        "交易": n,
        "胜率%": round(win_rate, 1),
        "盈亏比": round(profit_factor, 2),
        "夏普": round(float(pf.sharpe_ratio()), 2),
    }


def fmt_row(name, m, best_in_col=None):
    """格式化一行, 最优值标 *。"""
    def cell(v, col):
        s = str(v)
        if best_in_col and best_in_col.get(col) == v:
            s = f"\033[32m{s}*\033[0m"  # 绿色标最优
        return s.rjust(8)
    return (f"  {name:18s} |"
            f" 收益{cell(m['收益%'],'收益%')} |"
            f" 回撤{cell(m['回撤%'],'回撤%')} |"
            f" 交易{cell(m['交易'],'交易')} |"
            f" 胜率{cell(m['胜率%'],'胜率%')} |"
            f" 盈亏比{cell(m['盈亏比'],'盈亏比')} |"
            f" 夏普{cell(m['夏普'],'夏普')}")


def params_to_cmd(params: dict, symbol: str, start: str, end: str) -> str:
    """参数字典 -> run.py 命令行。

    run.py 的 -p 解析器只认 int/float/str, 不认列表/None 字面量。
    所以含列表(如 profit_tighten)或 None 的组合, 命令行跑不了,
    必须写进代码改默认值。这里对此类组合给出提示而非无效命令。
    """
    base = f"python framework/run.py midterm {symbol} --start {start} --end {end}"
    if not params:
        return base + "  # 用默认参数"

    # 检测命令行跑不了的参数 (列表 / None)
    unsupported = [k for k, v in params.items()
                   if isinstance(v, list) or v is None]
    if unsupported:
        return (f"# ⚠️ 含列表/None参数 ({', '.join(unsupported)}) -p 跑不了, 需改代码默认值:\n"
                f"#   {base}  # 然后在 midterm.py params 改: {params}")

    parts = [f"{k}={v}" for k, v in params.items()]
    return f"{base} -p {' '.join(parts)}"


def main():
    parser = argparse.ArgumentParser(description="midterm 参数对比")
    parser.add_argument("stocks", nargs="*", default=DEFAULT_STOCKS,
                        help=f"股票代码 (默认: {' '.join(DEFAULT_STOCKS)})")
    parser.add_argument("--start", default="20220101", help="起始日期 YYYYMMDD")
    parser.add_argument("--end", default="20260818", help="结束日期 YYYYMMDD")
    parser.add_argument("--show-cmd", action="store_true",
                        help="打印每只股票最优组合的 run.py 命令")
    args = parser.parse_args()

    print(f"区间: {args.start} ~ {args.end}  |  股票: {', '.join(args.stocks)}")
    print(f"成本: 佣金万3+印花税千1+滑点0.1%  |  初始资金: 10万\n")

    # 每只股票: 算所有预设组合, 找最优 (按收益排)
    best_overall = {}  # {symbol: (preset_name, params, metrics)}

    for symbol in args.stocks:
        df = load_df(symbol, args.start, args.end)
        if df is None:
            continue

        print(f"\n{'='*70}")
        print(f"  {symbol}")
        print(f"{'='*70}")
        print(f"  {'参数组合':18s} | 收益    | 回撤    | 交易   | 胜率    | 盈亏比  | 夏普   ")

        results = []
        for name, params in PRESETS:
            try:
                m = backtest(df, params)
                results.append((name, params, m))
            except Exception as e:
                print(f"  {name:18s} | ERR: {str(e)[:50]}")
                continue

        if not results:
            continue

        # 找每列最优 (收益高/回撤低/胜率高/盈亏比高 为优; 交易数不比)
        def best_val(items, key, higher_better=True):
            vals = [(it[2][key]) for it in items]
            vals = [v for v in vals if v == v]  # 去 NaN
            if not vals:
                return None
            return max(vals) if higher_better else min(vals)
        best_in_col = {
            "收益%": best_val(results, "收益%", True),
            "回撤%": best_val(results, "回撤%", False),
            "胜率%": best_val(results, "胜率%", True),
            "盈亏比": best_val(results, "盈亏比", True),
            "夏普": best_val(results, "夏普", True),
        }
        for name, params, m in results:
            print(fmt_row(name, m, best_in_col))

        # 该股最优: 按夏普综合排序 (夏普兼顾收益与回撤, 较公允)
        best = max(results, key=lambda x: x[2]["夏普"])
        print(f"\n  → {symbol} 最优(夏普): {best[0]}  →  {best[2]}")
        best_overall[symbol] = best

    # 汇总 + 命令
    if args.show_cmd and best_overall:
        print(f"\n{'='*70}")
        print("  最优组合的 run.py 命令 (可直接复制运行):")
        print(f"{'='*70}")
        for symbol, (name, params, m) in best_overall.items():
            print(f"\n# {symbol} - {name} (收益{m['收益%']}% 夏普{m['夏普']})")
            print(params_to_cmd(params, symbol, args.start, args.end))


if __name__ == "__main__":
    main()
