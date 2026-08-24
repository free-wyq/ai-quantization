"""中期策略 - 退出因子 (F14 ATR跟踪止损 / F15 量价背离) + ADX

ADX 不指示方向, 仅度量趋势强度; ATR 度量波动幅度。
两者组合用于: 决定止损宽度 (强趋势宽止损) 与仓位系数 (见 strategies/midterm.py)。

ATR/ADX 用 ta 库的 Wilder 平滑 (标准定义), 与看板 klinecharts 内置 DMI/VOL 同源。
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from ta.trend import ADXIndicator
from ta.volatility import AverageTrueRange


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """平均真实波幅 (F14 基础)。ta 库 Wilder 平滑 (标准 ATR)。"""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    return AverageTrueRange(high, low, close, window=period, fillna=False).average_true_range()


def adx(df: pd.DataFrame, period: int = 14):
    """返回 (ADX, +DI, -DI)。ta 库 Wilder 平滑 (标准 ADX), 度量趋势强度 (无方向)。"""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    i = ADXIndicator(high, low, close, window=period, fillna=False)
    return i.adx(), i.adx_pos(), i.adx_neg()


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
    # ta 库 ATR warmup 段为 NaN, 填 0 防 NaN 传播 (warmup 段止损线取 highest, 即无 ATR 缓冲)
    atr_safe = atr_series.fillna(0.0)
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
            prev_stop = highest - base_mult.iloc[i] * float(atr_safe.iloc[i])
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
            new_stop = highest - current_mult * float(atr_safe.iloc[i])
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


def ma_stop_exits(df, entries, ma_period: int = 20):
    """均线止损: 收盘跌破 MA(ma_period) 即退出。

    止损线 = MA(ma_period), 持仓期间每日更新。
    返回 (exits布尔, stop_line序列)。
    """
    close = df["close"].astype(float)
    ma = close.rolling(ma_period).mean()
    exits = pd.Series(False, index=df.index)
    in_pos = False
    for i in range(len(df)):
        if entries.iloc[i] and not in_pos:
            in_pos = True
        elif in_pos:
            if not np.isnan(ma.iloc[i]) and float(close.iloc[i]) < float(ma.iloc[i]):
                exits.iloc[i] = True
                in_pos = False
    return exits.fillna(False), ma


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
                use_f15: bool = False, profit_tighten=None, max_retracement=None,
                use_ma_stop: bool = False, ma_stop_period: int = 20):
    """综合退出 = MA止损 / ATR跟踪止损 + 量价背离(可选)。返回 (exits, stop_line)。

    use_ma_stop=True 时使用均线止损 (收盘跌破MA即退出), 忽略 ATR 止损参数。
    """
    if use_ma_stop:
        base_exit, stop_line = ma_stop_exits(df, entries, ma_period=ma_stop_period)
    else:
        atr_s = atr(df, atr_period)
        adx_s, _, _ = adx(df, adx_period)
        base_exit, stop_line = trailing_stop_exits(
            df, entries, atr_s, adx_s,
            mult_strong=mult_strong, mult_weak=mult_weak, adx_thresh=adx_thresh,
            profit_tighten=profit_tighten, max_retracement=max_retracement)
    if use_f15:
        f15_exit = volume_divergence_exits(df, entries)
        exits = base_exit | f15_exit
    else:
        exits = base_exit
    return exits.fillna(False), stop_line
