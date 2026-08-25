"""临时诊断脚本: 分析 midterm 策略的交易进出和退出原因"""
import pandas as pd
import vectorbt as vbt
from data.fetcher import fetch_stock_history
from framework.strategies import STRATS
from framework.strategies.midterm import _atr, _adx, _trailing_stop_exits, _volume_divergence_exits

df = fetch_stock_history('300308', '20250102', '20260818').copy()
keep = [c for c in ['open','high','low','close','volume','amount','turnover_rate','symbol'] if c in df.columns]
df = df[keep].dropna()

strat = STRATS['midterm']()
result = strat.run(df)
entries, exits = result[0], result[1]

pf = vbt.Portfolio.from_signals(
    close=df['close'], entries=entries, exits=exits,
    direction='longonly', init_cash=100000.0, fees=0.0008, slippage=0.001
)
trades = pf.trades.records_readable

# 退出原因分析
atr_s = _atr(df, 14)
adx_s, _, _ = _adx(df, 14)
atr_exit, stop_line = _trailing_stop_exits(df, entries, atr_s, adx_s, mult_strong=3.5, mult_weak=2.0, adx_thresh=30.0)
f15_exit = _volume_divergence_exits(df, entries)

print("=" * 100)
print(f"{'#':>2}  {'入场':>12}  {'退出':>12}  {'天数':>4}  {'买价':>8}  {'卖价':>8}  {'收益':>8}  {'退出原因'}")
print("-" * 100)

for i, row in trades.iterrows():
    entry_dt = pd.Timestamp(row['Entry Timestamp'])
    exit_dt = pd.Timestamp(row['Exit Timestamp'])
    entry_px = float(row['Avg Entry Price'])
    exit_px = float(row['Avg Exit Price'])
    pnl = float(row['PnL'])
    ret = float(row['Return']) * 100
    days = (exit_dt - entry_dt).days

    atr_flag = atr_exit.loc[exit_dt] if exit_dt in atr_exit.index else False
    f15_flag = f15_exit.loc[exit_dt] if exit_dt in f15_exit.index else False
    reason = []
    if atr_flag: reason.append('ATR止损')
    if f15_flag: reason.append('量价背离')
    reason_str = ' + '.join(reason) if reason else '未知'

    print(f"{i+1:>2}  {entry_dt.strftime('%Y-%m-%d'):>12}  {exit_dt.strftime('%Y-%m-%d'):>12}  {days:>4}  {entry_px:>8.1f}  {exit_px:>8.1f}  {ret:>7.1f}%  {reason_str}")

print("=" * 100)

# 看每次退出后到下次入场之间的间隔
print("\n退出→再入场间隔:")
for i in range(len(trades) - 1):
    exit_dt = pd.Timestamp(trades.iloc[i]['Exit Timestamp'])
    next_entry = pd.Timestamp(trades.iloc[i+1]['Entry Timestamp'])
    gap = (next_entry - exit_dt).days
    # 看看这期间股价变化
    exit_px = float(trades.iloc[i]['Avg Exit Price'])
    next_entry_px = float(trades.iloc[i+1]['Avg Entry Price'])
    price_change = (next_entry_px / exit_px - 1) * 100
    print(f"  交易{i+1}退出({exit_dt.strftime('%m-%d')} @{exit_px:.1f}) → 交易{i+2}入场({next_entry.strftime('%m-%d')} @{next_entry_px:.1f})  间隔{gap}天  期间股价{price_change:+.1f}%")

# 看看买入持有 vs 策略 在各交易段的表现
print(f"\n买入持有收益: {(df['close'].iloc[-1]/df['close'].iloc[0]-1)*100:.1f}%")
print(f"策略总收益:   {(pf.total_return()*100):.1f}%")
