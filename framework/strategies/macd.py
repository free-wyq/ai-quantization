"""MACD 金叉死叉策略"""

from .base import Strategy, series_to_list


class MACDStrategy(Strategy):
    name = "macd"
    label = "MACD金叉死叉"
    params = {"fast": 12, "slow": 26, "signal": 9}

    def run(self, df):
        close = df["close"]
        n = len(df)
        p = self.params
        ema_fast = close.ewm(span=p["fast"], adjust=False).mean()
        ema_slow = close.ewm(span=p["slow"], adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=p["signal"], adjust=False).mean()
        entries = (dif > dea) & (dif.shift(1) <= dea.shift(1))
        exits = (dif < dea) & (dif.shift(1) >= dea.shift(1))
        indicators = [
            {"name": "DIF", "shortName": "DIF", "pane": "separate", "paneId": "macd",
             "color": "#ffa940", "values": series_to_list(dif, n)},
            {"name": "DEA", "shortName": "DEA", "pane": "separate", "paneId": "macd",
             "color": "#42a5f5", "values": series_to_list(dea, n)},
        ]
        return entries.fillna(False), exits.fillna(False), indicators
