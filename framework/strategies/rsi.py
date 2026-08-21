"""RSI 超买超卖策略 (均值回归)

利用 RSI (相对强弱指数) 识别超买超卖区域，适合震荡市:

- RSI < 超卖阈值 → 超卖，买入（价格过度下跌，预期反弹）
- RSI > 超买阈值 → 超买，卖出（价格过度上涨，预期回落）

与趋势策略互补:
  趋势策略 (MA/MACD/ADX) 在趋势市赚钱，震荡市亏钱
  RSI 策略在震荡市赚钱，趋势市亏钱

指标布局:
  ┌─────────────────────┐
  │  K线                │  ← 主图
  ├─────────────────────┤
  │  RSI                │  ← 副图 (paneId="rsi")
  │  70 ─ ─ ─ ─ ─ ─ ─  │  ← 超买线
  │  30 ─ ─ ─ ─ ─ ─ ─  │  ← 超卖线
  └─────────────────────┘
"""

import numpy as np
import pandas as pd

from .base import Strategy, series_to_list


def calc_rsi(close, period=14):
    """计算 RSI (相对强弱指数)

    RSI = 100 - 100/(1 + RS)
    RS = N日内平均涨幅 / N日内平均跌幅

    Returns:
        rsi: pd.Series  — 0~100, >70 超买, <30 超卖
    """
    delta = close.diff()
    gain = delta.clip(lower=0)  # 涨幅（跌的记为0）
    loss = -delta.clip(upper=0)  # 跌幅（涨的记为0）

    # Wilder 平滑 (等价于 EMA alpha=1/period)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    # 前 period 个值是预热期, 不可靠, 置空
    rsi.iloc[:period] = np.nan
    return rsi


class RSIStrategy(Strategy):
    name = "rsi"
    label = "RSI超买超卖"
    params = {"period": 14, "oversold": 40, "overbought": 60}

    def run(self, df):
        close = df["close"]
        n = len(df)
        p = self.params

        rsi = calc_rsi(close, p["period"])

        # 信号: 超卖区买入, 超买区卖出
        # 买入: RSI 从超卖区上穿 oversold 线 (反弹确认)
        entries = (rsi > p["oversold"]) & (rsi.shift(1) <= p["oversold"])
        # 卖出: RSI 从超买区下穿 overbought 线 (回落确认)
        exits = (rsi < p["overbought"]) & (rsi.shift(1) >= p["overbought"])

        indicators = [
            {"name": "RSI", "shortName": f"RSI{p['period']}", "pane": "separate", "paneId": "rsi",
             "color": "#ab47bc", "values": series_to_list(rsi, n)},
            {"name": "Overbought", "shortName": f"超买{p['overbought']}", "pane": "separate", "paneId": "rsi",
             "color": "#ef5350", "lineStyle": "dashed", "values": [p["overbought"]] * n},
            {"name": "Oversold", "shortName": f"超卖{p['oversold']}", "pane": "separate", "paneId": "rsi",
             "color": "#26a69a", "lineStyle": "dashed", "values": [p["oversold"]] * n},
        ]
        return entries.fillna(False), exits.fillna(False), indicators
