"""KDJ 随机指标策略 (短线入场 + ATR跟踪止损)

设计思路:
  KDJ灵敏是优势 → 用它抓入场拐点
  KDJ灵敏是劣势 → 不能用它退出 (利润没跑远就被洗出去)

解决方案: 分工明确
  入场: KDJ金叉 + J值近期超卖 (抓反转拐点)
  退出: ATR跟踪止损 (让利润奔跑, 不被正常震荡洗出)

对比版本:
  原版(金叉买死叉卖): 93次交易, 胜率33%, -30%
  过滤版(加J值+冷却): 2次交易, 太少
  本版(KDJ入场+ATR退出): 预计20-30次, 盈亏比3:1+

指标布局:
  ┌─────────────────────┐
  │  K线 + MA + ATR止损  │  ← 主图
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
    """
    lowest_low = low.rolling(period, min_periods=1).min()
    highest_high = high.rolling(period, min_periods=1).max()
    rsv = (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan) * 100
    rsv = rsv.fillna(50.0)

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

    k.iloc[:period] = np.nan
    d.iloc[:period] = np.nan
    j.iloc[:period] = np.nan

    return k, d, j


def calc_atr(high, low, close, period=14):
    """Average True Range (Wilder平滑)"""
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    return atr


class KDJStrategy(Strategy):
    name = "kdj"
    label = "KDJ随机指标"
    params = {
        "period": 9,            # RSV计算窗口
        "oversold": 20,         # KDJ超卖线 (显示用)
        "overbought": 80,       # KDJ超买线 (显示用)
        "j_oversold": 20,       # J值超卖线 (买入需J近期低于此值)
        "ma_period": 20,        # 趋势确认均线
        "cooldown": 5,          # 信号冷却天数
        "atr_period": 14,       # ATR计算周期
        "atr_mult": 3.5,        # ATR止损倍数 (3.5 = 宽止损, 容忍波动让趋势跑)
    }

    def run(self, df):
        high = df["high"]
        low = df["low"]
        close = df["close"]
        n = len(df)
        p = self.params

        # --- KDJ ---
        k, d, j = calc_kdj(high, low, close, p["period"])
        ma = close.rolling(p["ma_period"]).mean()
        atr = calc_atr(high, low, close, p["atr_period"])

        # --- 入场信号: KDJ金叉 + J值近期超卖 ---
        # 不加MA过滤: 实测MA20过滤会错过主升浪(如比亚迪涨35%但策略亏59%)
        # 让KDJ自由抓拐点, 用ATR止损控制风险
        golden_cross = (k > d) & (k.shift(1) <= d.shift(1))
        lookback = 5
        j_was_oversold = (j.rolling(lookback).min() < p["j_oversold"]).fillna(False)

        entry_signal = (golden_cross & j_was_oversold).fillna(False).values

        # --- 退出: ATR跟踪止损 (不用KDJ死叉) ---
        close_vals = close.values
        high_vals = high.values
        atr_vals = atr.values

        trailing_stop = np.full(n, np.nan)
        entries = np.zeros(n, dtype=bool)
        exits = np.zeros(n, dtype=bool)
        in_position = False
        highest_since_entry = 0.0
        stop_price = 0.0
        last_trade_bar = -p["cooldown"] - 1

        for i in range(n):
            if np.isnan(atr_vals[i]) or np.isnan(k.values[i]):
                continue

            if not in_position and entry_signal[i] and (i - last_trade_bar) > p["cooldown"]:
                # --- 入场 ---
                in_position = True
                highest_since_entry = high_vals[i]
                stop_price = close_vals[i] - p["atr_mult"] * atr_vals[i]
                trailing_stop[i] = stop_price
                entries[i] = True
                last_trade_bar = i

            elif in_position:
                # --- 持仓: 跟踪止损线只上移 ---
                if high_vals[i] > highest_since_entry:
                    highest_since_entry = high_vals[i]
                new_stop = highest_since_entry - p["atr_mult"] * atr_vals[i]
                stop_price = max(stop_price, new_stop)
                trailing_stop[i] = stop_price

                # --- 触发止损退出 ---
                if close_vals[i] < stop_price:
                    exits[i] = True
                    in_position = False
                    last_trade_bar = i

        entries_series = pd.Series(entries, index=df.index)
        exits_series = pd.Series(exits, index=df.index)

        indicators = [
            {"name": f"MA{p['ma_period']}", "shortName": f"MA{p['ma_period']}",
             "pane": "main", "paneId": "main",
             "color": "#42a5f5", "values": series_to_list(ma, n)},
            {"name": "ATR止损", "shortName": "ATR Stop",
             "pane": "main", "paneId": "main",
             "color": "#ff5252", "lineStyle": "dashed", "lineWidth": 1,
             "values": series_to_list(pd.Series(trailing_stop), n)},
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
        return entries_series, exits_series, indicators
