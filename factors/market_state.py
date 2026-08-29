"""中期策略 - 市场状态闸门 (F1 个股广度 / F2 情绪分位 / F3 板块温度)

F1 个股广度: 站上20日线的个股占比 (替代大盘点位, 防失真)
F2 情绪分位: 涨停/跌停比近60日分位 (分位法, 防绝对数失真) — 需逐日数据, 默认关闭
F3 板块温度: 31行业中 MA20向上的占比 (用已建 sectors 模块)

开仓条件 (EXPERIENCE 12.3): F1/F2/F3 满足任意2个 → 允许开仓。
"""
from __future__ import annotations

import pandas as pd
import numpy as np


def breadth(pool_dfs: list, ma_period: int = 20) -> pd.Series:
    """F1 个股广度: 站上MA20的个股占比 (%)。输入各股票日K DataFrame 列表。"""
    above_list = []
    for df in pool_dfs:
        close = df["close"].astype(float)
        ma = close.rolling(ma_period).mean()
        above_list.append((close > ma).astype(int))
    mat = pd.concat(above_list, axis=1)
    return mat.mean(axis=1, skipna=True) * 100.0


def sector_temperature(sector_dfs: list, ma_period: int = 20) -> pd.Series:
    """F3 板块温度: 行业中 MA20向上的占比 (%)。输入各板块指数日K DataFrame 列表。"""
    above_list = []
    for df in sector_dfs:
        close = df["close"].astype(float)
        ma = close.rolling(ma_period).mean()
        above_list.append((close > ma).astype(int))
    mat = pd.concat(above_list, axis=1)
    return mat.mean(axis=1, skipna=True) * 100.0


def emotion_gate(dates: pd.DatetimeIndex, zt_series: pd.Series, dt_series: pd.Series,
                 window: int = 60) -> pd.Series:
    """F2 情绪分位闸门 (需逐日涨停/跌停序列, 可选; midterm v2 默认未启用)。

    返回每日是否允许做 (布尔)。分位<20%冰点=False(空仓), 其余=True。
    zt_series/dt_series 需为按日期索引的每日涨停/跌停家数。

    注: 默认闸门采用 F1个体广度 + F3板块温度 (满足2个才开仓), 不依赖此函数。
        启用 F2 需先落逐日涨停/跌停数据 (akshare stock_zt_em / stock_dt_em)。
    """
    ratio = zt_series / dt_series.clip(lower=1)
    pct = ratio.rolling(window).apply(lambda x: float((x[-1] >= x).mean()), raw=True)
    gate = (pct >= 0.20)
    return gate.reindex(dates).fillna(True)
