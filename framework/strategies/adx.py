"""ADX 趋势强度策略

利用 ADX (平均趋向指数) 判断趋势强度，配合 +DI/-DI 方向线产生信号:

- ADX > 阈值 → 趋势明确，可以交易
  - +DI > -DI → 多头趋势，买入
  - +DI < -DI → 空头趋势，卖出
- ADX < 阈值 → 无趋势（震荡市），不交易

指标布局:
  ┌─────────────────────┐
  │  K线                │  ← 主图
  ├─────────────────────┤
  │  ADX + +DI + -DI    │  ← 副图 (paneId="adx")
  └─────────────────────┘
"""

import numpy as np
import pandas as pd

from .base import Strategy, series_to_list


def calc_adx(df, period=14):
    """计算 ADX, +DI, -DI

    Returns:
        adx: pd.Series  — 趋势强度 (0-100)
        plus_di: pd.Series  — 多头方向指标
        minus_di: pd.Series — 空头方向指标
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    # True Range
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm = pd.Series(plus_dm, index=close.index)
    minus_dm = pd.Series(minus_dm, index=close.index)

    # Wilder 平滑 (等价于 EMA alpha=1/period)
    alpha = 1.0 / period
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_dm_smooth = plus_dm.ewm(alpha=alpha, adjust=False).mean()
    minus_dm_smooth = minus_dm.ewm(alpha=alpha, adjust=False).mean()

    # +DI / -DI
    plus_di = 100 * plus_dm_smooth / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm_smooth / atr.replace(0, np.nan)

    # DX → ADX
    di_sum = plus_di + minus_di
    di_diff = (plus_di - minus_di).abs()
    dx = 100 * di_diff / di_sum.replace(0, np.nan)
    adx = dx.ewm(alpha=alpha, adjust=False).mean()

    return adx, plus_di, minus_di


class ADXStrategy(Strategy):
    name = "adx"
    label = "ADX趋势强度"
    params = {"period": 14, "threshold": 25}

    def run(self, df):
        close = df["close"]
        n = len(df)
        p = self.params

        adx, plus_di, minus_di = calc_adx(df, p["period"])
        threshold = p["threshold"]

        # 信号: ADX 趋势强度达标 + DI 方向交叉
        # 买入: ADX > 阈值 且 +DI 上穿 -DI
        entries = (adx > threshold) & (plus_di > minus_di) & (plus_di.shift(1) <= minus_di.shift(1))
        # 卖出: ADX > 阈值 且 +DI 下穿 -DI
        exits = (adx > threshold) & (plus_di < minus_di) & (plus_di.shift(1) >= minus_di.shift(1))

        # 补充: ADX 跌破阈值时也平仓（趋势消失）
        exits = exits | (adx < threshold) & (adx.shift(1) >= threshold)
        entries = entries.fillna(False)
        exits = exits.fillna(False)

        indicators = [
            {"name": "ADX", "shortName": f"ADX{p['period']}", "pane": "separate", "paneId": "adx",
             "color": "#ffd666", "values": series_to_list(adx, n)},
            {"name": "PlusDI", "shortName": "+DI", "pane": "separate", "paneId": "adx",
             "color": "#ef5350", "values": series_to_list(plus_di, n)},
            {"name": "MinusDI", "shortName": "-DI", "pane": "separate", "paneId": "adx",
             "color": "#26a69a", "values": series_to_list(minus_di, n)},
            {"name": "Threshold", "shortName": f"阈值{threshold}", "pane": "separate", "paneId": "adx",
             "color": "#888888", "lineStyle": "dashed", "values": [threshold] * n},
            self.vr_indicator(self.compute_volume_ratio(df), n),
        ]
        reasons = self.reasons_from_signals(
            entries, exits, f"ADX趋势确立(+DI上穿)", "ADX趋势消退/反转")
        return entries, exits, indicators, reasons
