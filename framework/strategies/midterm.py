"""中期量化复合策略 — Strategy 子类, 复用框架回测引擎

职责单一: 只生成个股信号 (入场/退出/指标/原因)。
跨股票筛选(闸门/板块/龙头)和仓位控制由引擎或独立模块负责。
七层闭环架构见 STRATEGY_GUIDE.md。
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from framework.strategies.base import Strategy, series_to_list, SignalResult
from framework.factors.signal import (
    build_entries, macd, volume_ratio, ma_trend, weekly_kdj,
)
from framework.factors.exit import build_exits, atr, adx, volume_divergence_exits


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

        # --- 入场信号 ---
        entries = build_entries(
            df,
            use_weekly_kdj=not p["no_weekly"],
            use_ma60=not p["no_ma60"],
            use_vol=not p["no_vol"],
            vol_min=p["vol_min"],
            vol_lookback=p["vol_lookback"],
            ma_period=p["ma_period"],
        ).fillna(False)

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
        _, dif, dea = macd(df)
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
        macd_bull, _, _ = macd(df)
        wk_long, _, _ = weekly_kdj(df)
        ma60_up, _ = ma_trend(df, p["ma_period"])
        vol_ok, _ = volume_ratio(df, min_ratio=p["vol_min"], lookback=p["vol_lookback"])

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
