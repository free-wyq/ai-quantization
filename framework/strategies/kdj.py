"""KDJ 随机指标策略 (短线震荡)

KDJ 是经典短线指标，利用价格在区间中的位置判断超买超卖:

- K线与D线金叉（K上穿D）→ 买入
- K线与D线死叉（K下穿D）→ 卖出
- J值 > 100 极度超买, J值 < 0 极度超卖

与RSI的区别:
  RSI: 单线判断强弱, 适合中短线
  KDJ: 双线交叉+J值极值, 信号更频繁, 适合短线

指标布局:
  ┌─────────────────────┐
  │  K线                │  ← 主图
  ├─────────────────────┤
  │  K, D, J            │  ← 副图 (paneId="kdj")
  │  80 ─ ─ ─ ─ ─ ─ ─  │  ← 超买线
  │  20 ─ ─ ─ ─ ─ ─ ─  │  ← 超卖线
  └─────────────────────┘
"""

import numpy as np
import pandas as pd

from .base import Strategy, series_to_list


def calc_kdj(high, low, close, period=9):
    """计算 KDJ 随机指标

    RSV = (Close - LLV(low, N)) / (HHV(high, N) - LLV(low, N)) * 100
    K = 2/3 * prev_K + 1/3 * RSV   (SMA平滑, 初始值50)
    D = 2/3 * prev_D + 1/3 * K     (SMA平滑, 初始值50)
    J = 3 * K - 2 * D

    Args:
        high/low/close: 价格序列
        period: RSV计算窗口 (默认9)

    Returns:
        k, d, j: 三个 pd.Series, 范围 0~100 (J可超出)
    """
    lowest_low = low.rolling(period, min_periods=1).min()
    highest_high = high.rolling(period, min_periods=1).max()
    rsv = (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan) * 100
    rsv = rsv.fillna(50.0)  # 区间为0时RSV取50(中性)

    # SMA平滑: K = 2/3 * prev_K + 1/3 * RSV, 初始K=50
    k = pd.Series(np.nan, index=close.index, dtype=float)
    d = pd.Series(np.nan, index=close.index, dtype=float)
    k_val = 50.0
    d_val = 50.0

    rsv_vals = rsv.values
    for i in range(len(rsv_vals)):
        k_val = 2.0 / 3.0 * k_val + 1.0 / 3.0 * rsv_vals[i]
        d_val = 2.0 / 3.0 * d_val + 1.0 / 3.0 * k_val
        k.iloc[i] = k_val
        d.iloc[i] = d_val

    j = 3 * k - 2 * d

    # 前 period 个值是预热期, 不可靠, 置空
    k.iloc[:period] = np.nan
    d.iloc[:period] = np.nan
    j.iloc[:period] = np.nan

    return k, d, j


class KDJStrategy(Strategy):
    name = "kdj"
    label = "KDJ随机指标"
    params = {
        "period": 9,           # RSV计算窗口
        "oversold": 20,        # 超卖阈值
        "overbought": 80,      # 超买阈值
    }

    def run(self, df):
        high = df["high"]
        low = df["low"]
        close = df["close"]
        n = len(df)
        p = self.params

        k, d, j = calc_kdj(high, low, close, p["period"])

        # 信号: 金叉买入 + 死叉卖出
        # 买入: K从下方上穿D (金叉), 且K在超卖区附近(< overbought, 避免高位金叉)
        golden_cross = (k > d) & (k.shift(1) <= d.shift(1))
        entries = golden_cross & (k < p["overbought"])

        # 卖出: K从上方下穿D (死叉), 且K在超买区附近(> oversold, 避免低位死叉)
        death_cross = (k < d) & (k.shift(1) >= d.shift(1))
        exits = death_cross & (k > p["oversold"])

        indicators = [
            {"name": "K", "shortName": "K", "pane": "separate", "paneId": "kdj",
             "color": "#ffa940", "values": series_to_list(k, n)},
            {"name": "D", "shortName": "D", "pane": "separate", "paneId": "kdj",
             "color": "#42a5f5", "values": series_to_list(d, n)},
            {"name": "J", "shortName": "J", "pane": "separate", "paneId": "kdj",
             "color": "#ab47bc", "values": series_to_list(j, n)},
            {"name": "Overbought", "shortName": f"超买{p['overbought']}", "pane": "separate", "paneId": "kdj",
             "color": "#ef5350", "lineStyle": "dashed", "values": [p["overbought"]] * n},
            {"name": "Oversold", "shortName": f"超卖{p['oversold']}", "pane": "separate", "paneId": "kdj",
             "color": "#26a69a", "lineStyle": "dashed", "values": [p["oversold"]] * n},
        ]
        return entries.fillna(False), exits.fillna(False), indicators
