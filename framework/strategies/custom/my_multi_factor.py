"""多因子策略示例: MA 均线 + RSI 超买过滤

演示多因子策略的写法:
- 因子1 (MA): 副图1，双均线交叉产生信号
- 因子2 (RSI): 副图2，超买区过滤买入信号

指标布局:
  ┌─────────────────────┐
  │  K线                │  ← 主图
  ├─────────────────────┤
  │  MA5 + MA20         │  ← 副图1 (paneId="ma")
  ├─────────────────────┤
  │  RSI                │  ← 副图2 (paneId="rsi")
  └─────────────────────┘
"""

from ..base import Strategy, series_to_list


class MyMultiFactor(Strategy):
    name = "multi_factor"
    label = "多因子: MA+RSI"
    params = {
        "ma_fast": 5,
        "ma_slow": 20,
        "rsi_period": 14,
        "rsi_overbought": 70,
    }

    def run(self, df):
        close = df["close"]
        n = len(df)
        p = self.params

        # 因子1: 双均线
        ma_f = close.rolling(p["ma_fast"]).mean()
        ma_s = close.rolling(p["ma_slow"]).mean()

        # 因子2: RSI
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(p["rsi_period"]).mean()
        loss = (-delta.clip(upper=0)).rolling(p["rsi_period"]).mean()
        rs = gain / loss.replace(0, 1e-10)
        rsi = 100 - 100 / (1 + rs)

        # 信号: 金叉 + RSI 未超买
        entries = (ma_f > ma_s) & (ma_f.shift(1) <= ma_s.shift(1)) & (rsi < p["rsi_overbought"])
        exits = (ma_f < ma_s) & (ma_f.shift(1) >= ma_s.shift(1))

        indicators = [
            # 副图1: MA 均线
            {"name": "MA_F", "shortName": f"MA{p['ma_fast']}", "pane": "separate", "paneId": "ma",
             "color": "#ffa940", "values": series_to_list(ma_f, n)},
            {"name": "MA_S", "shortName": f"MA{p['ma_slow']}", "pane": "separate", "paneId": "ma",
             "color": "#42a5f5", "values": series_to_list(ma_s, n)},
            # 副图2: RSI (paneId="rsi" → 独占一个窗格)
            {"name": "RSI", "shortName": f"RSI{p['rsi_period']}", "pane": "separate",
             "paneId": "rsi", "color": "#ab47bc", "values": series_to_list(rsi, n)},
        ]
        return entries.fillna(False), exits.fillna(False), indicators
