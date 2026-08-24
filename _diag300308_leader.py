"""诊断 300308 龙头条件"""
import sys, os
_PROJ = os.path.dirname(os.path.abspath(__file__))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

import pandas as pd
import numpy as np
from data.fetcher import fetch_stock_history
from data import sectors as sec
from config.settings import DATA_DIR
from framework.strategies.midterm import _compute_state

df = fetch_stock_history("300308", "2025-01-01", "2026-08-24")
df = df[["open","high","low","close","volume","amount","turnover_rate"]].dropna()
df.index = pd.to_datetime(df.index)
if "symbol" not in df.columns:
    df["symbol"] = "300308"

state = _compute_state(df.index.min(), df.index.max(), 50.0, 60.0, 3)
mapping = state["mapping"]

sym = "300308"
sub = mapping[mapping["symbol"] == sym]
sec_name = sub["sector_name"].iloc[0] if len(sub) else "未知"
print(f"300308 所属板块: {sec_name}")

# 看板块内有多少股票
sec_stocks = mapping[mapping["sector_name"] == sec_name]
print(f"板块 '{sec_name}' 内股票数: {len(sec_stocks)}")
print(f"板块内股票: {list(sec_stocks['symbol'].head(20))}\n")

# 300308 的龙头条件
to = df["turnover_rate"].astype(float)
avg_amt = df["amount"].astype(float).rolling(20).mean()

print(f"=== 300308 龙头条件 ===")
print(f"  换手率 3-15% 日数:    {((to >= 3.0) & (to <= 15.0)).sum()} / {len(df)}")
print(f"  换手率 < 3% 日数:      {(to < 3.0).sum()}")
print(f"  换手率 > 15% 日数:     {(to > 15.0).sum()}")
print(f"  20日均额 > 2亿 日数:   {(avg_amt > 2e8).sum()} / {len(df)}")
print(f"  20日均额中位数:        {avg_amt.median()/1e8:.2f} 亿")
print(f"  20日均额最大值:        {avg_amt.max()/1e8:.2f} 亿")

# 检查 300308 是否在 pool 中
pool = {}
stock_list_path = os.path.join(DATA_DIR, "stock_list.csv")
sl = pd.read_csv(stock_list_path)
stock_list = list(zip(sl["symbol"].astype(str).str.zfill(6), sl["name"]))
print(f"\n股票池总数: {len(stock_list)}")
print(f"300308 在股票池中: {'300308' in [s for s, _ in stock_list]}")

# 检查板块内排名
sec_syms = [s for s in sec_stocks["symbol"].astype(str).str.zfill(6).tolist() if s in [p for p in state.get("leader_map", {}).keys()]]
print(f"板块 '{sec_name}' 中在 leader_map 里的股票: {sec_syms}")

# 如果 300308 不在 leader_map
if sym not in state.get("leader_map", {}):
    print(f"\n300308 不在 leader_map 中!")
    # 检查是否在 pool 中
    # 重新加载 pool 看看
    all_pool_syms = set()
    for s, _ in stock_list:
        try:
            tdf = fetch_stock_history(s, "2025-01-01", "2026-08-24")
            if len(tdf) > 120:
                all_pool_syms.add(s)
        except:
            continue
    print(f"实际加载到 pool 的股票数: {len(all_pool_syms)}")
    print(f"300308 在 pool 中: {'300308' in all_pool_syms}")
