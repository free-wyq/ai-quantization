"""海龟法则 / 唐奇安通道策略

价格突破 N 日最高价买入, 跌破 N 日最低价卖出。趋势跟踪型,
抓大波段但回撤期间反复打脸。经典海龟交易系统的简化版。

指标布局:
  ┌─────────────────────┐
  │  K线 + DC通道上下轨  │  ← 主图 (通道叠加在K线上更直观)
  └─────────────────────┘
"""
from .base import Strategy, series_to_list


class TurtleStrategy(Strategy):
    name = "turtle"
    label = "唐奇安通道"
    params = {"entry": 20, "exit": 20}

    def run(self, df):
        high, low, close = df["high"], df["low"], df["close"]
        n = len(df)
        p = self.params
        highest = high.rolling(p["entry"]).max().shift(1)
        lowest = low.rolling(p["exit"]).min().shift(1)
        entries = close >= highest
        exits = close <= lowest
        entries = entries.fillna(False)
        exits = exits.fillna(False)
        indicators = [
            {"name": "DC_Up", "shortName": f"DC高{p['entry']}", "pane": "main", "paneId": "main",
             "color": "#ff6b6b", "values": series_to_list(highest, n)},
            {"name": "DC_Low", "shortName": f"DC低{p['exit']}", "pane": "main", "paneId": "main",
             "color": "#51cf66", "values": series_to_list(lowest, n)},
            self.vr_indicator(self.compute_volume_ratio(df), n),
        ]
        reasons = self.reasons_from_signals(
            entries, exits, f"突破{p['entry']}日新高", f"跌破{p['exit']}日新低")
        return entries, exits, indicators, reasons
