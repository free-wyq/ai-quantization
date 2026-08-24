"""双均线交叉策略

快线上穿慢线金叉买入, 下穿死叉卖出。最基础的趋势跟踪策略,
信号明确但滞后, 震荡市频繁假信号。常作为基准与其他策略对比。

指标布局:
  ┌─────────────────────┐
  │  K线                │  ← 主图
  ├─────────────────────┤
  │  MA{fast} + MA{slow} │  ← 副图 (paneId="ma")
  └─────────────────────┘
"""

from .base import Strategy, series_to_list


class MAStrategy(Strategy):
    name = "ma"
    label = "双均线交叉"
    params = {"fast": 5, "slow": 20}

    def run(self, df):
        close = df["close"]
        n = len(df)
        p = self.params
        ma_fast = close.rolling(p["fast"]).mean()
        ma_slow = close.rolling(p["slow"]).mean()
        entries = (ma_fast > ma_slow) & (ma_fast.shift(1) <= ma_slow.shift(1))
        exits = (ma_fast < ma_slow) & (ma_fast.shift(1) >= ma_slow.shift(1))
        entries = entries.fillna(False)
        exits = exits.fillna(False)
        indicators = [
            {"name": "MA_Fast", "shortName": f"MA{p['fast']}", "pane": "separate", "paneId": "ma",
             "color": "#ffa940", "values": series_to_list(ma_fast, n)},
            {"name": "MA_Slow", "shortName": f"MA{p['slow']}", "pane": "separate", "paneId": "ma",
             "color": "#42a5f5", "values": series_to_list(ma_slow, n)},
            self.vr_indicator(self.compute_volume_ratio(df), n),
        ]
        reasons = self.reasons_from_signals(entries, exits, "均线金叉", "均线死叉")
        return entries, exits, indicators, reasons
