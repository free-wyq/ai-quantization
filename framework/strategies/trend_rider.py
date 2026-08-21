"""趋势骑手策略: MACD入场 + MA确认 + ATR跟踪止损

设计思路:
  - 入场: MACD金叉 + 收价在MA上方 (双重确认, 减少假信号)
  - 出场: 不用死叉退出, 改用ATR跟踪止损 (让利润奔跑)
  - 止损线: 持仓期间最高价 - N×ATR, 只上移不下移

对比原MACD策略:
  - 原MACD: 死叉就走, 大趋势没吃满
  - TrendRider: 趋势不结束不走, 吃满大波段, 代价是回撤时退出稍晚
"""

import numpy as np
import pandas as pd

from .base import Strategy, series_to_list


class TrendRiderStrategy(Strategy):
    name = "trend_rider"
    label = "趋势骑手"
    params = {
        "fast": 12,        # MACD快线
        "slow": 26,        # MACD慢线
        "signal": 9,       # MACD信号线
        "ma_period": 20,   # 趋势确认均线
        "atr_period": 14,  # ATR计算周期
        "atr_mult": 3.0,   # ATR倍数 (止损宽度)
    }

    def run(self, df):
        close = df["close"]
        high = df["high"]
        low = df["low"]
        n = len(df)
        p = self.params

        # --- ATR ---
        atr = self._compute_atr(high, low, close, p["atr_period"])

        # --- MACD ---
        ema_fast = close.ewm(span=p["fast"], adjust=False).mean()
        ema_slow = close.ewm(span=p["slow"], adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=p["signal"], adjust=False).mean()

        # --- MA趋势确认 ---
        ma = close.rolling(p["ma_period"]).mean()

        # --- 入场: MACD金叉 + 收价在MA上方 ---
        golden_cross = (dif > dea) & (dif.shift(1) <= dea.shift(1))
        entries = golden_cross & (close > ma)

        # --- ATR跟踪止损 (逐bar模拟) ---
        close_vals = close.values
        high_vals = high.values
        entry_vals = entries.values
        atr_vals = atr.values

        trailing_stop = np.full(n, np.nan)
        exits = np.zeros(n, dtype=bool)
        in_position = False
        highest_since_entry = 0.0
        stop_price = 0.0

        for i in range(n):
            if np.isnan(atr_vals[i]):
                # ATR还没算出来, 跳过
                if entry_vals[i]:
                    entry_vals[i] = False
                continue

            if not in_position and entry_vals[i]:
                # --- 入场 ---
                in_position = True
                highest_since_entry = high_vals[i]
                stop_price = close_vals[i] - p["atr_mult"] * atr_vals[i]
                trailing_stop[i] = stop_price

            elif in_position:
                # --- 持仓中: 跟踪止损线只上移 ---
                if high_vals[i] > highest_since_entry:
                    highest_since_entry = high_vals[i]
                new_stop = highest_since_entry - p["atr_mult"] * atr_vals[i]
                stop_price = max(stop_price, new_stop)
                trailing_stop[i] = stop_price

                # --- 触发止损退出 ---
                if close_vals[i] < stop_price:
                    exits[i] = True
                    in_position = False

        entries_series = pd.Series(entry_vals, index=df.index).fillna(False)
        exits_series = pd.Series(exits, index=df.index)

        indicators = [
            {
                "name": "ATR止损", "shortName": "ATR Stop",
                "pane": "main", "paneId": "main",
                "color": "#ff5252", "lineStyle": "dashed", "lineWidth": 1,
                "values": series_to_list(pd.Series(trailing_stop), n),
            },
            {
                "name": f"MA{p['ma_period']}", "shortName": f"MA{p['ma_period']}",
                "pane": "main", "paneId": "main",
                "color": "#42a5f5", "values": series_to_list(ma, n),
            },
            {
                "name": "DIF", "shortName": "DIF",
                "pane": "separate", "paneId": "macd",
                "color": "#ffa940", "values": series_to_list(dif, n),
            },
            {
                "name": "DEA", "shortName": "DEA",
                "pane": "separate", "paneId": "macd",
                "color": "#42a5f5", "values": series_to_list(dea, n),
            },
        ]

        return entries_series, exits_series, indicators

    @staticmethod
    def _compute_atr(high, low, close, period=14):
        """Average True Range (Wilder平滑)"""
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
        return atr
