"""中期策略 - 个股信号因子 (F10 MACD / F12 周KDJ / MA60 / F13 量比)

所有函数输入为个股日K DataFrame (含 open/high/low/close/volume/amount/turnover_rate),
输出为布尔/数值 Series, 与输入等长、索引对齐。
"""
from __future__ import annotations

import pandas as pd
import numpy as np


def macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD 多头状态 (F10)。返回 (多头布尔 Series, DIF, DEA)。

    多头状态 = DIF > DEA, 从金叉持续到死叉 (非单日事件)。
    这样与其他持续状态条件(周KDJ多头/MA60向上)可以自然重叠,
    不会因"金叉当天恰好不满足其他条件"而漏掉趋势。
    """
    close = df["close"].astype(float)
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_bull = (dif > dea).fillna(False)
    return macd_bull, dif, dea


def weekly_kdj(df: pd.DataFrame, n: int = 9, k_period: int = 3, d_period: int = 3):
    """周线 KDJ。返回 (周线多头状态布尔(日度ffill), K, D)。

    周线多头状态 (K>D) 作为方向过滤; 日线 MACD 金叉作为具体买点。
    这是「周线定方向、日线定点」的双周期确认实现。
    """
    w_close = df["close"].resample("W").last().astype(float)
    w_high = df["high"].resample("W").max().astype(float)
    w_low = df["low"].resample("W").min().astype(float)
    low_n = w_low.rolling(n).min()
    high_n = w_high.rolling(n).max()
    rsv = (w_close - low_n) / (high_n - low_n) * 100.0
    rsv = rsv.fillna(50.0)
    K = rsv.ewm(alpha=1.0 / k_period, adjust=False).mean()
    D = K.ewm(alpha=1.0 / d_period, adjust=False).mean()
    weekly_long = (K > D)  # 周线多头状态 (持续, 非单日)
    daily_long = weekly_long.reindex(df.index, method="ffill").fillna(False)
    return daily_long.astype(bool), K, D


def ma_trend(df: pd.DataFrame, period: int = 60):
    """MA 多空分界 (v2 新增)。返回 (close>MA(period) 布尔, MA序列)。

    定位: 只允许做多过滤, 不抢金叉投票 (避免与 MACD 共线)。
    """
    close = df["close"].astype(float)
    ma = close.rolling(period).mean()
    return (close > ma).fillna(False), ma


def volume_ratio(df: pd.DataFrame, window: int = 20, min_ratio: float = 1.2, lookback: int = 5):
    """量比确认 (F13)。返回 (量比满足布尔, 量比序列)。

    lookback: 近N日内有任意一天量比>min_ratio即满足 (信号持续)。
    放量往往只持续1-2天, 用lookback避免与MACD等持续状态错位。
    lookback=1 时退化为原始行为 (仅当天满足)。
    """
    vol = df["volume"].astype(float)
    avg = vol.rolling(window).mean()
    ratio = vol / avg
    raw = (ratio > min_ratio).fillna(False)
    if lookback > 1:
        raw = raw.rolling(lookback).max().fillna(0).astype(bool)
    return raw, ratio


def build_entries(df: pd.DataFrame, use_weekly_kdj: bool = True, use_ma60: bool = True,
                 use_vol: bool = True, vol_min: float = 1.2, vol_lookback: int = 5,
                 ma_period: int = 20):
    """综合个股入场信号 = MACD多头 & 周KDJ多头 & MA向上 & 量比放大(近N日)。

    所有条件均为持续状态(非单日事件), 避免多条件同日共振过严。
    MACD多头从金叉持续到死叉; 量比用lookback窗口放宽;
    周KDJ/MA本身就是持续状态。
    """
    macd_bull, _, _ = macd(df)
    weekly_long, _, _ = weekly_kdj(df)
    ma60_up, _ = ma_trend(df, ma_period)
    vol_ok, _ = volume_ratio(df, min_ratio=vol_min, lookback=vol_lookback)

    entries = macd_bull.copy()
    if use_weekly_kdj:
        entries = entries & weekly_long
    if use_ma60:
        entries = entries & ma60_up
    if use_vol:
        entries = entries & vol_ok
    return entries.fillna(False)
