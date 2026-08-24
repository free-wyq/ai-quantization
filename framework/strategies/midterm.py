"""中期量化复合策略 — Strategy 子类, 复用框架回测引擎。

职责单一: 只生成个股信号 (入场/退出/指标/原因)。
跨股票筛选(闸门/板块/龙头)和仓位控制由引擎或独立模块负责。
七层闭环架构见 DESIGN.md 第二部分。
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from ta.trend import MACD
from ta.momentum import StochasticOscillator
from framework.strategies.base import Strategy, series_to_list, SignalResult
from framework.factors.exit import build_exits, adx, volume_divergence_exits


# ---- 因子计算 (本策略专用) ----

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
        adx_s, _, _ = adx(df, p["adx"])

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
        # MACD/DIF/DEA/ADX 用 klinecharts 内置指标库渲染 (前端 createIndicator name='MACD'/'DMI'),
        # 此处只保留策略专属的 ATR止损线 (自定义 STRAT_* 指标)。
        _ind_specs = [
            ("ATRstop", "ATR止损", "main", "main", "#fa8c16", "dashed", "line", stop_line),
        ]
        indicators = [
            {"name": nm, "shortName": sn, "pane": pn, "paneId": pid,
             "color": cl, "lineStyle": ls, "type": tp, "values": series_to_list(val, n)}
            for nm, sn, pn, pid, cl, ls, tp, val in _ind_specs
        ]

        # --- 买卖原因 ---
        reasons = self._build_reasons(df, entries, exits, stop_line, p, macd_bull, wk_long, ma_up, vol_ok, adx_s)

        return SignalResult(entries, exits.fillna(False), indicators, reasons)

    def _build_reasons(self, df, entries, exits, stop_line, p,
                       macd_bull, wk_long, ma_up, vol_ok, adx_s):
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
        f15_exit = volume_divergence_exits(df, entries) if p["use_f15"] else pd.Series(False, index=df.index)
        use_ma_stop = p.get("use_ma_stop", False)
        for idx in exits[exits].index:
            parts = []
            sl = stop_line.loc[idx] if idx in stop_line.index else np.nan
            if not np.isnan(sl) and close.loc[idx] < sl:
                parts.append("MA止损" if use_ma_stop else "ATR跟踪止损")
            if p["use_f15"] and f15_exit.loc[idx]:
                parts.append("量价背离")
            ts = int(pd.Timestamp(idx).timestamp() * 1000)
            sell_reasons[ts] = " | ".join(parts) if parts else "退出信号"

        return {"buy_reasons": buy_reasons, "sell_reasons": sell_reasons}
