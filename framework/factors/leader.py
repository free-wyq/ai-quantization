"""中期策略 - 龙头筛选 (F6-F9) 板块内排名

F6 板块内成交额排名: 板块内个股成交额分位 前N
F7 板块内涨幅排名:   板块内个股当日涨幅分位 前N
F8 换手率区间:       3% <= 换手率 <= 15%
F9 流动性门槛:       20日均成交额 > 2亿

组合: (F6 OR F7) AND F8 AND F9 → 候选龙头股池 (排除ST/流动性枯竭)。
定位: 在强势板块内只选龙头, 不买杂毛 (铁律)。
"""
from __future__ import annotations

import pandas as pd
import numpy as np


def leader_flags(pool: dict, mapping: pd.DataFrame,
                 top_n: int = 3, turnover_min: float = 3.0, turnover_max: float = 15.0,
                 min_avg_amount: float = 2e8):
    """对股票池筛选龙头。

    Args:
        pool:    {symbol: 个股日K df} (symbol 为6位字符串)
        mapping: 个股-板块映射 df (columns: symbol, sector_name)
        top_n:   板块内成交额/涨幅排名前N算龙头候选
    Returns:
        {symbol: 每日是否龙头(布尔Series, index=该股票df.index)}
    """
    mapping = mapping.copy()
    mapping["symbol"] = mapping["symbol"].astype(str).str.zfill(6)

    # 按板块分组 symbol
    groups: dict = {}
    for sym, df in pool.items():
        sub = mapping[mapping["symbol"] == sym]
        if len(sub) == 0:
            continue
        sec_name = sub["sector_name"].iloc[0]
        groups.setdefault(sec_name, []).append(sym)

    result: dict = {}
    for sec_name, symbols in groups.items():
        if len(symbols) == 0:
            continue
        # 组内每日成交额 / 涨幅矩阵 (按索引对齐, 取并集)
        amount_mat = pd.concat(
            [pool[s]["amount"].astype(float).rename(s) for s in symbols], axis=1)
        pct_mat = pd.concat(
            [pool[s]["close"].pct_change().rename(s) for s in symbols], axis=1)
        amount_rank = amount_mat.rank(axis=1, ascending=False)
        pct_rank = pct_mat.rank(axis=1, ascending=False)
        f6 = amount_rank <= top_n
        f7 = pct_rank <= top_n

        for s in symbols:
            df = pool[s]
            f6_s = f6[s].reindex(df.index).fillna(False)
            f7_s = f7[s].reindex(df.index).fillna(False)
            to = df["turnover_rate"].astype(float)
            avg_amt = df["amount"].astype(float).rolling(20).mean()
            f8 = (to >= turnover_min) & (to <= turnover_max)
            f9 = avg_amt > min_avg_amount
            sym_leader = ((f6_s | f7_s) & f8 & f9).fillna(False)
            result[s] = sym_leader
    return result
