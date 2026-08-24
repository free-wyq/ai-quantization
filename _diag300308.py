"""诊断 300308 修复后完整信号"""
import sys, os
_PROJ = os.path.dirname(os.path.abspath(__file__))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

import pandas as pd
import numpy as np
from data.fetcher import fetch_stock_history
from framework.factors.signal import build_entries, macd, volume_ratio, ma_trend, weekly_kdj
from framework.factors.leader import compute_leader_for_stock
from framework.strategies.midterm import _compute_state

df = fetch_stock_history("300308", "2025-01-01", "2026-08-24")
df = df[["open","high","low","close","volume","amount","turnover_rate"]].dropna()
df.index = pd.to_datetime(df.index)
if "symbol" not in df.columns:
    df["symbol"] = "300308"
print(f"300308: {len(df)} 根K线, 涨幅: {df['close'].iloc[-1]/df['close'].iloc[0]*100-100:.1f}%\n")

# base
base = build_entries(df, use_weekly_kdj=True, use_ma60=True, use_vol=True, vol_min=1.2, vol_lookback=5)
print(f"base=True: {base.sum()} 天")

# state
state = _compute_state(df.index.min(), df.index.max(), 50.0, 60.0, 3)
gate = state["gate"].reindex(df.index).fillna(False)
mapping = state["mapping"]

sym = "300308"
sub = mapping[mapping["symbol"] == sym]
sec_name = sub["sector_name"].iloc[0] if len(sub) else None

if sec_name and sec_name in state["sector_strong_map"]:
    sstrong = state["sector_strong_map"][sec_name].reindex(df.index).fillna(False)
else:
    sstrong = pd.Series(False, index=df.index)

# 龙头: 实时计算
if sym in state["leader_map"]:
    lflag = state["leader_map"][sym].reindex(df.index).fillna(False)
    print(f"lflag (池内): {lflag.sum()} 天")
else:
    lflag = compute_leader_for_stock(sym, df, state["pool"], mapping, top_n=3)
    print(f"lflag (实时计算): {lflag.sum()} 天")

print(f"sstrong=True: {sstrong.sum()} 天")
print(f"gate=True: {gate.sum()} 天")

print(f"\n=== 最终 ===")
print(f"  base & sstrong:         {(base & sstrong).sum()}")
print(f"  base & sstrong & lflag: {(base & sstrong & lflag).sum()}")
print(f"  base & gate:            {(base & gate).sum()}")
print(f"  base & sstrong & lflag & gate: {(base & sstrong & lflag & gate).sum()}  <-- 买入信号")

# 显示买入信号日期
entries = (base & sstrong & lflag & gate).fillna(False)
if entries.sum() > 0:
    print(f"\n买入信号日期:")
    for d in entries[entries].index[:10]:
        print(f"  {d.date()}  close={df.loc[d, 'close']:.2f}")
