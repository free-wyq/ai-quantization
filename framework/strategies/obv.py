"""OBV 能量潮策略 (量价关系)

利用 OBV (On Balance Volume) 衡量资金流向，通过量价关系判断趋势:

- 收盘上涨日，OBV += 当日成交量（资金流入）
- 收盘下跌日，OBV -= 当日成交量（资金流出）
- 收平日，OBV 不变

交易信号:
- OBV 上穿 OBV 均线 → 量能转强，买入
- OBV 下穿 OBV 均线 → 量能转弱，卖出

核心思想: 量在价先，成交量往往领先价格变动。
适合与趋势策略配合使用，OBV 确认趋势的真实性。

指标布局:
  ┌─────────────────────┐
  │  K线                │  ← 主图
  ├─────────────────────┤
  │  OBV                │  ← 副图 (paneId="obv")
  │  OBV MA ─ ─ ─ ─ ─  │  ← 信号线
  └─────────────────────┘
"""

import numpy as np
import pandas as pd

from .base import Strategy, series_to_list


def calc_obv(close, volume):
    """计算 OBV (能量潮)

    OBV 是累积成交量:
    - 收盘上涨: OBV += volume
    - 收盘下跌: OBV -= volume
    - 收平:     OBV 不变

    Returns:
        obv: pd.Series — 累积成交量
    """
    direction = np.sign(close.diff().fillna(0))  # +1 / -1 / 0
    obv = (direction * volume).cumsum()
    return obv


class OBVStrategy(Strategy):
    name = "obv"
    label = "OBV能量潮"
    params = {"ma_period": 20}

    def run(self, df):
        close = df["close"]
        volume = df["volume"]
        n = len(df)
        p = self.params

        obv = calc_obv(close, volume)
        obv_ma = obv.rolling(p["ma_period"]).mean()

        # 预热期置空
        obv_ma.iloc[:p["ma_period"]] = np.nan

        # 信号: OBV 上穿均线买入, 下穿均线卖出
        entries = (obv > obv_ma) & (obv.shift(1) <= obv_ma.shift(1))
        exits = (obv < obv_ma) & (obv.shift(1) >= obv_ma.shift(1))

        indicators = [
            {"name": "OBV", "shortName": "OBV", "pane": "separate", "paneId": "obv",
             "color": "#ffa940", "values": series_to_list(obv, n)},
            {"name": "OBVMA", "shortName": f"MA{p['ma_period']}", "pane": "separate", "paneId": "obv",
             "color": "#42a5f5", "lineStyle": "dashed", "values": series_to_list(obv_ma, n)},
        ]
        return entries.fillna(False), exits.fillna(False), indicators
