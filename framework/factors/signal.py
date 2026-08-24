"""信号因子协议定义。

仅定义信号因子的接口规范, 不含具体实现。
具体因子计算和买入信号组合逻辑由各策略自行实现。

用法:
    from framework.factors.signal import SignalFactor

    class MACDBull:
        def compute(self, df: pd.DataFrame) -> pd.Series:
            close = df["close"]
            ema_fast = close.ewm(span=12, adjust=False).mean()
            ema_slow = close.ewm(span=26, adjust=False).mean()
            dif = ema_fast - ema_slow
            dea = dif.ewm(span=9, adjust=False).mean()
            return (dif > dea).fillna(False)

    # 策略中组合多个因子:
    factors = [MACDBull(), WeeklyKDJ(), ...]
    entries = pd.Series(True, index=df.index)
    for f in factors:
        entries = entries & f.compute(df)
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class SignalFactor(Protocol):
    """信号因子协议 — 定义单个因子的计算接口。

    每个因子接收日K DataFrame, 返回布尔 Series (True=条件满足)。
    具体如何组合多个因子构成买入信号, 由策略类决定。
    """

    def compute(self, df: pd.DataFrame) -> pd.Series:
        """计算因子信号。

        Args:
            df: 日K DataFrame, 含 open/high/low/close/volume 等列。

        Returns:
            布尔 Series, 与 df 等长、索引对齐。True 表示该因子条件满足。
        """
        ...
