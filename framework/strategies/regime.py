"""市场状态自适应策略 (Regime Switching)

核心思想: 没有一种策略能适应所有市场，先用 ADX 判断市场状态，再自动切换策略。

市场状态判断 (ADX):
  ADX > 25  → 趋势市 → 启用双均线交叉 (追涨杀跌)
  ADX < 20  → 震荡市 → 启用 RSI 超买超卖 (低买高卖)
  20~25     → 模糊区 → 不开新仓 (等待方向明确)

为什么有效:
  - 趋势策略 (MA/MACD) 在震荡市频繁假信号，高买低卖
  - 震荡策略 (RSI) 在趋势市逆势操作，越买越跌
  - 自适应策略在两种市场都能用对的工具

指标布局 (降维: 3副图 → 主图叠加 + 1副图):
  ┌─────────────────────┐
  │  K线 + MA5 + MA20   │  ← 主图叠加均线
  ├─────────────────────┤
  │  ADX + RSI          │  ← 合并副图 (均为0~100量纲)
  │  25 ─ ─ ─ ─ ─ ─ ─  │  ← 趋势/震荡分界线
  │  60 ─ ─ ─ ─ ─ ─ ─  │  ← RSI超买线
  │  40 ─ ─ ─ ─ ─ ─ ─  │  ← RSI超卖线
  └─────────────────────┘
"""

import pandas as pd

from .base import Strategy, series_to_list
from .adx import calc_adx
from .rsi import calc_rsi


class RegimeStrategy(Strategy):
    name = "regime"
    label = "市场状态自适应"
    params = {
        "adx_period": 14,
        "trend_threshold": 25,   # ADX > 25 → 趋势市
        "range_threshold": 20,   # ADX < 20 → 震荡市
        "ma_fast": 5,
        "ma_slow": 20,
        "rsi_period": 14,
        "rsi_oversold": 40,
        "rsi_overbought": 60,
    }

    def run(self, df):
        close = df["close"]
        n = len(df)
        p = self.params

        # ── 1. 市场状态判断 ──
        adx, _, _ = calc_adx(df, p["adx_period"])
        is_trending = adx > p["trend_threshold"]   # 趋势市
        is_ranging = adx < p["range_threshold"]    # 震荡市

        # ── 2. 趋势市信号: 双均线交叉 ──
        ma_fast = close.rolling(p["ma_fast"]).mean()
        ma_slow = close.rolling(p["ma_slow"]).mean()
        trend_entry = (ma_fast > ma_slow) & (ma_fast.shift(1) <= ma_slow.shift(1))
        trend_exit = (ma_fast < ma_slow) & (ma_fast.shift(1) >= ma_slow.shift(1))

        # ── 3. 震荡市信号: RSI 超买超卖 ──
        rsi = calc_rsi(close, p["rsi_period"])
        range_entry = (rsi > p["rsi_oversold"]) & (rsi.shift(1) <= p["rsi_oversold"])
        range_exit = (rsi < p["rsi_overbought"]) & (rsi.shift(1) >= p["rsi_overbought"])

        # ── 4. 信号合并: 根据市场状态路由 ──
        entries = (is_trending & trend_entry) | (is_ranging & range_entry)
        exits = (is_trending & trend_exit) | (is_ranging & range_exit)

        # ── 5. 状态切换时平仓 ──
        # 趋势→模糊: 趋势减弱, 落袋为安
        exits = exits | (adx < p["trend_threshold"]) & (adx.shift(1) >= p["trend_threshold"])
        # 震荡→模糊: 震荡被打破, 可能要变盘
        exits = exits | (adx > p["range_threshold"]) & (adx.shift(1) <= p["range_threshold"])

        # ── 6. 指标输出 (MA叠加主图, ADX+RSI合并副图) ──
        entries = entries.fillna(False)
        exits = exits.fillna(False)
        indicators = [
            # 主图: 双均线叠加在K线上
            {"name": "MAFast", "shortName": f"MA{p['ma_fast']}", "pane": "main", "paneId": "main",
             "color": "#ffa940", "values": series_to_list(ma_fast, n)},
            {"name": "MASlow", "shortName": f"MA{p['ma_slow']}", "pane": "main", "paneId": "main",
             "color": "#42a5f5", "values": series_to_list(ma_slow, n)},
            # 副图: ADX + RSI 合并 (均为0~100量纲)
            {"name": "ADX", "shortName": f"ADX{p['adx_period']}", "pane": "separate", "paneId": "regime",
             "color": "#ffd666", "values": series_to_list(adx, n)},
            {"name": "RSI", "shortName": f"RSI{p['rsi_period']}", "pane": "separate", "paneId": "regime",
             "color": "#ab47bc", "values": series_to_list(rsi, n)},
            {"name": "TrendLine", "shortName": f"趋势{p['trend_threshold']}", "pane": "separate", "paneId": "regime",
             "color": "#ef5350", "lineStyle": "dashed", "values": [p["trend_threshold"]] * n},
            {"name": "Overbought", "shortName": f"超买{p['rsi_overbought']}", "pane": "separate", "paneId": "regime",
             "color": "#ef5350", "lineStyle": "dashed", "values": [p["rsi_overbought"]] * n},
            {"name": "Oversold", "shortName": f"超卖{p['rsi_oversold']}", "pane": "separate", "paneId": "regime",
             "color": "#26a69a", "lineStyle": "dashed", "values": [p["rsi_oversold"]] * n},
            self.vr_indicator(self.compute_volume_ratio(df), n),
        ]
        # regime 信号按市场状态路由, 同一信号点原因不同, 按当期状态标注
        buy_reasons, sell_reasons = {}, {}
        for idx in entries[entries].index:
            buy_reasons[int(pd.Timestamp(idx).timestamp() * 1000)] = (
                "趋势金叉" if is_trending.loc[idx] else "RSI超卖反弹")
        for idx in exits[exits].index:
            sell_reasons[int(pd.Timestamp(idx).timestamp() * 1000)] = (
                "趋势死叉" if is_trending.loc[idx] else "RSI超买回落")
        reasons = {"buy_reasons": buy_reasons, "sell_reasons": sell_reasons}
        return entries, exits, indicators, reasons
