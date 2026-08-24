"""中期策略 - 退出因子 (F14 ATR跟踪止损 / F15 量价背离) + ADX

ADX 不指示方向, 仅度量趋势强度; ATR 度量波动幅度。
两者组合用于: 决定止损宽度 (强趋势宽止损) 与仓位系数 (见 strategies/midterm.py)。
"""
from __future__ import annotations

import pandas as pd
import numpy as np


def _true_range(df: pd.DataFrame) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """平均真实波幅 (F14 基础)。"""
    return _true_range(df).rolling(period).mean()


def adx(df: pd.DataFrame, period: int = 14):
    """返回 (ADX, +DI, -DI)。ADX 度量趋势强度 (无方向)。"""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    plus_dm = (high - prev_high).clip(lower=0.0)
    minus_dm = (prev_low - low).clip(lower=0.0)
    tr = _true_range(df)
    atr_ = tr.rolling(period).mean()
    plus_di = 100.0 * (plus_dm.rolling(period).mean() / atr_)
    minus_di = 100.0 * (minus_dm.rolling(period).mean() / atr_)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx_ = dx.rolling(period).mean()
    return adx_, plus_di, minus_di


def trailing_stop_exits(df, entries, atr_series, adx_series,
                        mult_strong: float = 3.5, mult_weak: float = 2.0,
                        adx_thresh: float = 30.0,
                        profit_tighten=None,
                        max_retracement: float = None):
    """ATR 跟踪止损 (F14) + 利润保护 + 最大回撤止盈。

    止损线 = 持仓最高价 - mult*ATR, 只上移不下移。触碰即卖。
    mult 由 ADX 决定: ADX>=阈值(强趋势)用宽止损吃满, 否则适中。

    profit_tighten: list of (profit_pct, mult), 如 [(1.0, 2.5), (2.0, 2.0)]
    盈利超过 profit_pct 时, 使用更紧的 mult, 锁定利润降低回撤。

    max_retracement: 如 0.15 表示从持仓最高价回落 15% 即退出。
    返回 (exits布尔, stop_line序列)。
    """
    close = df["close"].astype(float)
    n = len(df)
    base_mult = pd.Series(np.where(adx_series >= adx_thresh, mult_strong, mult_weak),
                          index=df.index).astype(float)
    stop_line = pd.Series(np.nan, index=df.index)
    exits = pd.Series(False, index=df.index)
    in_pos = False
    highest = 0.0
    entry_px = 0.0
    prev_stop = np.nan
    for i in range(n):
        if entries.iloc[i] and not in_pos:
            in_pos = True
            highest = float(close.iloc[i])
            entry_px = float(close.iloc[i])
            prev_stop = highest - base_mult.iloc[i] * float(atr_series.iloc[i])
            stop_line.iloc[i] = prev_stop
        elif in_pos:
            highest = max(highest, float(close.iloc[i]))
            # 利润保护: 盈利越多, 止损越紧
            current_mult = base_mult.iloc[i]
            if profit_tighten:
                profit_pct = (highest / entry_px - 1) if entry_px > 0 else 0.0
                for pct, m in sorted(profit_tighten, key=lambda x: x[0]):
                    if profit_pct >= pct:
                        current_mult = m
            new_stop = highest - current_mult * float(atr_series.iloc[i])
            # 最大回撤止盈: 从最高价回落超过 max_retracement 也触发退出
            if max_retracement is not None:
                retracement_stop = highest * (1 - max_retracement)
                new_stop = max(new_stop, retracement_stop)
            prev_stop = new_stop if np.isnan(prev_stop) else max(prev_stop, new_stop)
            stop_line.iloc[i] = prev_stop
            if float(close.iloc[i]) < prev_stop:
                exits.iloc[i] = True
                in_pos = False
                prev_stop = np.nan
    return exits.fillna(False), stop_line


def volume_divergence_exits(df, entries, window: int = 20,
                            low_ratio: float = 0.8, high_ratio: float = 3.0):
    """量价背离退出 (F15): 缩量跌回突破位 / 放量滞涨。返回布尔 Series。

    F15a 缩量跌回突破位: close<入场价 且 量比<0.8 → 假突破早退
    F15b 放量滞涨:       量比>3 且 (长上影 或 收跌) → 出货早退
    注: 无持仓日的信号由回测引擎忽略 (不影响)。
    """
    close = df["close"].astype(float)
    vol = df["volume"].astype(float)
    avg_vol = vol.rolling(window).mean()
    ratio = vol / avg_vol
    # 只在真正入场日( False→True 转换)锁定入场价, 避免持续状态不断抬高
    entry_days = entries & ~entries.shift(1, fill_value=False)
    entry_price = close.where(entry_days).ffill()
    f15a = (close < entry_price) & (ratio < low_ratio)

    body_high = df[["open", "close"]].max(axis=1)
    body_low = df[["open", "close"]].min(axis=1)
    upper_shadow = (df["high"] - body_high)
    body = (body_high - body_low)
    long_upper = upper_shadow > 2.0 * body
    f15b = (ratio > high_ratio) & (long_upper | (df["close"] < df["open"]))

    return (f15a | f15b).fillna(False)


def build_exits(df, entries, atr_period: int = 14, adx_period: int = 14,
                mult_strong: float = 3.5, mult_weak: float = 2.0, adx_thresh: float = 30.0,
                use_f15: bool = False, profit_tighten=None, max_retracement=None):
    """综合退出 = ATR跟踪止损 (默认) + 量价背离(可选)。返回 (exits, stop_line)。"""
    atr_s = atr(df, atr_period)
    adx_s, _, _ = adx(df, adx_period)
    atr_exit, stop_line = trailing_stop_exits(
        df, entries, atr_s, adx_s,
        mult_strong=mult_strong, mult_weak=mult_weak, adx_thresh=adx_thresh,
        profit_tighten=profit_tighten, max_retracement=max_retracement)
    if use_f15:
        f15_exit = volume_divergence_exits(df, entries)
        exits = atr_exit | f15_exit
    else:
        exits = atr_exit
    return exits.fillna(False), stop_line
