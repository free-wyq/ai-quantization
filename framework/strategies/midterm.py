"""中期量化复合策略 — Strategy 子类, 复用框架回测引擎。

职责单一: 只生成个股信号 (入场/退出/指标/原因)。
跨股票筛选(闸门/板块/龙头)和仓位控制由引擎或独立模块负责。
七层闭环架构见 DESIGN.md 第二部分。
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from ta.trend import MACD, ADXIndicator
from ta.momentum import StochasticOscillator
from ta.volatility import AverageTrueRange
from framework.strategies.base import Strategy, series_to_list, SignalResult


# ---- 入场因子 (本策略专用) ----

def _macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD 多头状态 (F10)。返回 (多头布尔, DIF, DEA)。

    用 ta 库 MACD (标准 EMA 口径)。多头状态 = DIF > DEA, 从金叉持续到死叉 (非单日事件)。
    """
    close = df["close"].astype(float)
    m = MACD(close, window_slow=slow, window_fast=fast, window_sign=signal, fillna=False)
    dif, dea = m.macd(), m.macd_signal()
    macd_bull = (dif > dea).fillna(False)
    return macd_bull, dif, dea


def _weekly_kdj(df: pd.DataFrame, n: int = 9, k_period: int = 3, d_period: int = 3):
    """周线 KDJ。返回 (周线多头布尔(日度ffill), K, D)。

    用 ta 库 StochasticOscillator。周线多头状态 (K>D) 作为方向过滤;
    日线 MACD 金叉作为具体买点。周线重采样到日度 (ffill)。
    """
    w_close = df["close"].resample("W").last().astype(float)
    w_high = df["high"].resample("W").max().astype(float)
    w_low = df["low"].resample("W").min().astype(float)
    s = StochasticOscillator(w_high, w_low, w_close, window=n, smooth_window=k_period, fillna=False)
    K, D = s.stoch(), s.stoch_signal()
    weekly_long = (K > D)
    daily_long = weekly_long.reindex(df.index, method="ffill").fillna(False)
    return daily_long.astype(bool), K, D


def _ma_trend(df: pd.DataFrame, period: int = 60):
    """MA 多空分界。返回 (close>MA 布尔, MA序列)。

    定位: 只允许做多过滤, 不抢金叉投票 (避免与 MACD 共线)。
    """
    close = df["close"].astype(float)
    ma = close.rolling(period).mean()
    return (close > ma).fillna(False), ma


def _volume_ratio(df: pd.DataFrame, window: int = 20, min_ratio: float = 1.2, lookback: int = 5):
    """量比确认 (F13)。返回 (量比满足布尔, 量比序列)。

    lookback: 近N日内有任意一天量比>min_ratio即满足 (信号持续)。
    """
    vol = df["volume"].astype(float)
    avg = vol.rolling(window).mean()
    ratio = vol / avg
    raw = (ratio > min_ratio).fillna(False)
    if lookback > 1:
        raw = raw.rolling(lookback).max().fillna(0).astype(bool)
    return raw, ratio


# ---- 退出因子 (本策略专用) ----

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """平均真实波幅 (F14 基础)。ta 库 Wilder 平滑 (标准 ATR)。"""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    return AverageTrueRange(high, low, close, window=period, fillna=False).average_true_range()


def _adx(df: pd.DataFrame, period: int = 14):
    """返回 (ADX, +DI, -DI)。ta 库 Wilder 平滑 (标准 ADX), 度量趋势强度 (无方向)。"""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    i = ADXIndicator(high, low, close, window=period, fillna=False)
    return i.adx(), i.adx_pos(), i.adx_neg()


def _trailing_stop_exits(df, entries, atr_series, adx_series,
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
            current_mult = base_mult.iloc[i]
            if profit_tighten:
                profit_pct = (highest / entry_px - 1) if entry_px > 0 else 0.0
                for pct, m in sorted(profit_tighten, key=lambda x: x[0]):
                    if profit_pct >= pct:
                        current_mult = m
            new_stop = highest - current_mult * float(atr_safe.iloc[i])
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


def _ma_stop_exits(df, entries, ma_period: int = 20):
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


def _volume_divergence_exits(df, entries, window: int = 20,
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


def _build_exits(df, entries, atr_period=14, adx_period=14,
                 mult_strong=3.5, mult_weak=2.0, adx_thresh=30.0,
                 use_f15=False, profit_tighten=None, max_retracement=None,
                 use_ma_stop=False, ma_stop_period=20,
                 f15_exit=None, atr_s=None, adx_s=None):
    """综合退出 = MA止损 / ATR跟踪止损 + 量价背离(可选)。返回 (exits, stop_line)。

    use_ma_stop=True 时使用均线止损, 忽略 ATR 止损参数。
    f15_exit / atr_s / adx_s: 预计算序列, 传入则跳过内部重复计算。
    """
    if use_ma_stop:
        base_exit, stop_line = _ma_stop_exits(df, entries, ma_period=ma_stop_period)
    else:
        if atr_s is None:
            atr_s = _atr(df, atr_period)
        if adx_s is None:
            adx_s, _, _ = _adx(df, adx_period)
        base_exit, stop_line = _trailing_stop_exits(
            df, entries, atr_s, adx_s,
            mult_strong=mult_strong, mult_weak=mult_weak, adx_thresh=adx_thresh,
            profit_tighten=profit_tighten, max_retracement=max_retracement)
    if use_f15:
        if f15_exit is None:
            f15_exit = _volume_divergence_exits(df, entries)
        exits = base_exit | f15_exit
    else:
        exits = base_exit
    return exits.fillna(False), stop_line


class MidTermStrategy(Strategy):
    name = "midterm"
    label = "中期量化"
    params = {
        # 信号
        "vol_min": 1.2, "vol_lookback": 5, "ma_period": 20,
        "no_weekly": False, "no_ma60": False, "no_vol": False,
        "no_adx": False, "adx_entry_min": 20.0,
        # 退出
        "atr": 14, "adx": 14,
        "mult_strong": 3.5, "mult_weak": 2.0, "adx_thresh": 30.0,
        "use_f15": False, "profit_tighten": None, "max_retracement": 0.10,
        "use_ma_stop": False, "ma_stop_period": 20,
    }

    def generate(self, df: pd.DataFrame) -> SignalResult:
        n = len(df)
        p = self.params

        # --- 因子计算 (只算一次) ---
        macd_bull, _, _ = _macd(df)
        wk_long, _, _ = _weekly_kdj(df)
        ma_up, _ = _ma_trend(df, p["ma_period"])
        vol_ok, _ = _volume_ratio(df, min_ratio=p["vol_min"], lookback=p["vol_lookback"])
        atr_s = _atr(df, p["atr"])
        adx_s, _, _ = _adx(df, p["adx"])

        # --- 入场信号: MACD多头 & 周KDJ多头 & MA向上 & 量比放大 & ADX趋势强 ---
        entries = macd_bull.copy()
        if not p["no_weekly"]:
            entries = entries & wk_long
        if not p["no_ma60"]:
            entries = entries & ma_up
        if not p["no_vol"]:
            entries = entries & vol_ok
        if not p["no_adx"]:
            entries = entries & (adx_s >= p["adx_entry_min"])
        entries = entries.fillna(False)

        # --- 退出 ---
        f15_exit = _volume_divergence_exits(df, entries) if p["use_f15"] else None
        exits, stop_line = _build_exits(
            df, entries,
            atr_period=p["atr"], adx_period=p["adx"],
            mult_strong=p["mult_strong"], mult_weak=p["mult_weak"],
            adx_thresh=p["adx_thresh"], use_f15=p["use_f15"],
            profit_tighten=p.get("profit_tighten"),
            max_retracement=p.get("max_retracement"),
            use_ma_stop=p.get("use_ma_stop", False),
            ma_stop_period=p.get("ma_stop_period", 20),
            f15_exit=f15_exit, atr_s=atr_s, adx_s=adx_s,
        )

        # --- 可视化指标 ---
        _ind_specs = [
            ("ATRstop", "ATR止损", "main", "main", "#fa8c16", "dashed", "line", stop_line),
        ]
        indicators = [
            {"name": nm, "shortName": sn, "pane": pn, "paneId": pid,
             "color": cl, "lineStyle": ls, "type": tp, "values": series_to_list(val, n)}
            for nm, sn, pn, pid, cl, ls, tp, val in _ind_specs
        ]

        # --- 买卖原因 ---
        reasons = self._build_reasons(df, entries, exits, stop_line, p, macd_bull, wk_long, ma_up, vol_ok, adx_s, f15_exit)

        return SignalResult(entries, exits.fillna(False), indicators, reasons)

    def _build_reasons(self, df, entries, exits, stop_line, p,
                       macd_bull, wk_long, ma_up, vol_ok, adx_s, f15_exit=None):
        """为每个买入/卖出日期生成原因说明。"""
        close = df["close"].astype(float)

        buy_flags = [
            (macd_bull, "MACD多头"), (wk_long, "周KDJ多头"),
            (ma_up, "MA向上"), (vol_ok, "量比放大"),
        ]
        if not p["no_adx"]:
            buy_flags.append((adx_s >= p["adx_entry_min"], "ADX趋势强"))

        buy_reasons = {}
        for idx in entries[entries].index:
            parts = [label for flag, label in buy_flags if flag.loc[idx]]
            ts = int(pd.Timestamp(idx).timestamp() * 1000)
            buy_reasons[ts] = " | ".join(parts) if parts else "信号触发"

        sell_reasons = {}
        use_ma_stop = p.get("use_ma_stop", False)
        for idx in exits[exits].index:
            parts = []
            sl = stop_line.loc[idx] if idx in stop_line.index else np.nan
            if not np.isnan(sl) and close.loc[idx] < sl:
                parts.append("MA止损" if use_ma_stop else "ATR跟踪止损")
            if p["use_f15"] and f15_exit is not None and f15_exit.loc[idx]:
                parts.append("量价背离")
            ts = int(pd.Timestamp(idx).timestamp() * 1000)
            sell_reasons[ts] = " | ".join(parts) if parts else "退出信号"

        return {"buy_reasons": buy_reasons, "sell_reasons": sell_reasons}
