"""海龟法则 / 唐奇安通道策略"""

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
        indicators = [
            {"name": "DC_Up", "shortName": f"DC高{p['entry']}", "pane": "separate", "paneId": "dc",
             "color": "#ff6b6b", "values": series_to_list(highest, n)},
            {"name": "DC_Low", "shortName": f"DC低{p['exit']}", "pane": "separate", "paneId": "dc",
             "color": "#51cf66", "values": series_to_list(lowest, n)},
        ]
        return entries.fillna(False), exits.fillna(False), indicators
