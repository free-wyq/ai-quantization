"""双均线交叉策略"""

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
        indicators = [
            {"name": "MA_Fast", "shortName": f"MA{p['fast']}", "pane": "separate", "paneId": "ma",
             "color": "#ffa940", "values": series_to_list(ma_fast, n)},
            {"name": "MA_Slow", "shortName": f"MA{p['slow']}", "pane": "separate", "paneId": "ma",
             "color": "#42a5f5", "values": series_to_list(ma_slow, n)},
        ]
        return entries.fillna(False), exits.fillna(False), indicators
