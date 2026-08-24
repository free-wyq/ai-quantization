"""中期量化复合策略 — Strategy 子类, 复用框架回测引擎。

职责单一: 只生成个股信号 (入场/退出/指标/原因)。
跨股票筛选(闸门/板块/龙头)和仓位控制由引擎或独立模块负责。
七层闭环架构见 STRATEGY_GUIDE.md。

信号因子协议见 framework/factors/signal.py (SignalFactor)。
具体因子实现和买入信号组合逻辑在本策略中定义。
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from framework.strategies.base import Strategy, series_to_list, SignalResult
from framework.factors.exit import build_exits, atr, adx, volume_divergence_exits


# ---- 因子计算 (本策略专用) ----

def _macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD 多头状态 (F10)。返回 (多头布尔, DIF, DEA)。

    多头状态 = DIF > DEA, 从金叉持续到死叉 (非单日事件)。
    """
    close = df["close"].astype(float)
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd_bull = (dif > dea).fillna(False)
    return macd_bull, dif, dea


def _weekly_kdj(df: pd.DataFrame, n: int = 9, k_period: int = 3, d_period: int = 3):
    """周线 KDJ。返回 (周线多头布尔(日度ffill), K, D)。

    周线多头状态 (K>D) 作为方向过滤; 日线 MACD 金叉作为具体买点。
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


class MidTermStrategy(Strategy):
    name = "midterm"
    label = "中期量化"
    params = {
        # 信号
        "vol_min": 1.2, "vol_lookback": 5, "ma_period": 20,
        "no_weekly": False, "no_ma60": False, "no_vol": False,
        # 退出
        "atr": 14, "adx": 14,
        "mult_strong": 3.5, "mult_weak": 2.0, "adx_thresh": 30.0,
        "use_f15": False, "profit_tighten": None, "max_retracement": 0.10,
        "use_ma_stop": True, "ma_stop_period": 20,
    }

    def generate(self, df: pd.DataFrame) -> SignalResult:
        n = len(df)
        p = self.params

        # --- 入场信号: MACD多头 & 周KDJ多头 & MA向上 & 量比放大 ---
        macd_bull, _, _ = _macd(df)
        wk_long, _, _ = _weekly_kdj(df)
        ma_up, _ = _ma_trend(df, p["ma_period"])
        vol_ok, _ = _volume_ratio(df, min_ratio=p["vol_min"], lookback=p["vol_lookback"])

        entries = macd_bull.copy()
        if not p["no_weekly"]:
            entries = entries & wk_long
        if not p["no_ma60"]:
            entries = entries & ma_up
        if not p["no_vol"]:
            entries = entries & vol_ok
        entries = entries.fillna(False)

        # --- 退出 ---
        exits, stop_line = build_exits(
            df, entries,
            atr_period=p["atr"], adx_period=p["adx"],
            mult_strong=p["mult_strong"], mult_weak=p["mult_weak"],
            adx_thresh=p["adx_thresh"], use_f15=p["use_f15"],
            profit_tighten=p.get("profit_tighten"),
            max_retracement=p.get("max_retracement"),
            use_ma_stop=p.get("use_ma_stop", False),
            ma_stop_period=p.get("ma_stop_period", 20),
        )

        # --- 可视化指标 ---
        _, dif, dea = _macd(df)
        _ind_specs = [
            ("ATRstop", "ATR止损", "main", "main", "#fa8c16", "dashed", stop_line),
            ("DIF", "DIF", "separate", "strat", "#ffa940", "solid", dif),
            ("DEA", "DEA", "separate", "strat", "#42a5f5", "solid", dea),
        ]
        indicators = [
            {"name": nm, "shortName": sn, "pane": pn, "paneId": pid,
             "color": cl, "lineStyle": ls, "values": series_to_list(val, n)}
            for nm, sn, pn, pid, cl, ls, val in _ind_specs
        ]

        # --- 买卖原因 ---
        reasons = self._build_reasons(df, entries, exits, stop_line, p)

        return SignalResult(entries, exits.fillna(False), indicators, reasons)

    def _build_reasons(self, df, entries, exits, stop_line, p):
        """为每个买入/卖出日期生成原因说明。"""
        close = df["close"].astype(float)
        macd_bull, _, _ = _macd(df)
        wk_long, _, _ = _weekly_kdj(df)
        ma60_up, _ = _ma_trend(df, p["ma_period"])
        vol_ok, _ = _volume_ratio(df, min_ratio=p["vol_min"], lookback=p["vol_lookback"])

        buy_flags = [
            (macd_bull, "MACD多头"), (wk_long, "周KDJ多头"),
            (ma60_up, "MA向上"), (vol_ok, "量比放大"),
        ]

        buy_reasons = {}
        for idx in entries[entries].index:
            parts = [label for flag, label in buy_flags if flag.loc[idx]]
            ts = int(pd.Timestamp(idx).timestamp() * 1000)
            buy_reasons[ts] = " | ".join(parts) if parts else "信号触发"

        sell_reasons = {}
        f15_exit = volume_divergence_exits(df, entries) if p["use_f15"] else pd.Series(False, index=df.index)
        for idx in exits[exits].index:
            parts = []
            sl = stop_line.loc[idx] if idx in stop_line.index else np.nan
            if not np.isnan(sl) and close.loc[idx] < sl:
                parts.append("ATR跟踪止损")
            if p["use_f15"] and f15_exit.loc[idx]:
                parts.append("量价背离")
            ts = int(pd.Timestamp(idx).timestamp() * 1000)
            sell_reasons[ts] = " | ".join(parts) if parts else "退出信号"

        return {"buy_reasons": buy_reasons, "sell_reasons": sell_reasons}
