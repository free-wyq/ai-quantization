"""中期策略 - 板块趋势 (F4/F5) 与每日强势板块集合

F4: 行业指数 close > MA20        → 该行业当日"强势"
F5: 行业指数 近20日动量 > 0      → 动量向上
组合 F4&F5 同时 True → 入选强势板块 (取前3-5个做多方向)
"""
from __future__ import annotations

import pandas as pd
import numpy as np


def sector_strong(sector_df: pd.DataFrame, ma_period: int = 20, mom_period: int = 20) -> pd.Series:
    """F4/F5: 行业指数 close>MA20 且 近mom_period日动量>0 → 该板块当日强势(布尔)。"""
    close = sector_df["close"].astype(float)
    ma = close.rolling(ma_period).mean()
    mom = close.pct_change(mom_period)
    return ((close > ma) & (mom > 0)).fillna(False)


def build_sector_strong_map(sector_dfs: dict) -> dict:
    """输入 {板块名: 板块指数df}, 返回 {板块名: 每日强势布尔Series}。"""
    return {name: sector_strong(df) for name, df in sector_dfs.items()}
