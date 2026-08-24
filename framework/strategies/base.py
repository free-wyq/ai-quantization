"""策略基类与工具函数

设计 (模板方法模式):
  - run(df) 是模板骨架, 子类一般不重写。它组装公共指标 (MA均线系统 + 量比),
    再调子类的 generate(df) 钩子拿信号 + 特色指标 + 原因 + 仓位, 统一返回 5 元组。
  - generate(df) 是子类唯一需实现的钩子, 返回 SignalResult。
  - 公共指标 (MA系统/量比) 上提到基类, 保证口径一致 + 看板契约 (name='VR' 等);
    各策略特色指标 (MACD/KDJ 等) 才由子类自行实现。

三层分离铁律: 策略只算信号, 绝不自己跑回测 (回测在 run.py / batch_backtest.py)。
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


# 主图均线系统配置: (周期, 颜色)。所有策略共享同一套主图均线显示。
# 子类可覆盖 MA_LINES 类属性自定义周期/颜色 (如 [(20,'#fff')] 只画一条)。
MA_LINES = [(5, "#faad14"), (10, "#13c2c2"), (20, "#722ed1"), (60, "#f5222d")]


@dataclass
class SignalResult:
    """generate() 的返回值 — 子类产出的信号与特色部分。

    公共指标 (MA系统/量比) 由基类 run() 组装, 子类的 indicators 只放特色指标
    (如 MACD的DIF/DEA、ATR止损线), 不含 MA5/10/20/60 与 VR。
    """
    entries: pd.Series
    exits: pd.Series
    indicators: list = field(default_factory=list)   # 特色指标 dict 列表
    reasons: dict | None = None                       # {buy_reasons, sell_reasons}; None=无标注
    size: pd.Series | None = None                     # 仓位比例 Series; None=等权满仓


class Strategy:
    """策略基类: 自研策略继承此类, 实现 generate() 方法即可。

    使用方式:
        1. 在 strategies/ (或 custom/) 下新建 .py 文件
        2. 定义 Strategy 子类, 设置 name/label/params (可覆盖 MA_LINES)
        3. 实现 generate(df) 方法, 返回 SignalResult
        4. 框架自动发现并注册, 无需修改任何框架代码

    示例::

        class MyStrategy(Strategy):
            name = "my"
            label = "我的策略"
            params = {"period": 14}

            def generate(self, df):
                close = df["close"]
                ma = close.rolling(self.params["period"]).mean()
                entries = close > ma
                exits = close < ma
                indicators = [
                    {"name": "MA", "shortName": "MA", "pane": "main", "paneId": "main",
                     "color": "#ffa940", "values": series_to_list(ma, len(df))},
                ]
                return SignalResult(entries, exits, indicators)
    """

    name = "base"
    label = "基础策略"
    params: dict = {}
    # 主图均线配置, 子类可覆盖
    MA_LINES = MA_LINES

    def __init__(self, **overrides):
        # 拷贝 params, 避免修改类属性
        self.params = dict(self.params)
        for k, v in overrides.items():
            if k in self.params:
                self.params[k] = v
            else:
                warnings.warn(f"策略 {self.name} 无参数 '{k}', 已忽略", stacklevel=2)

    # ---- 模板骨架: 子类一般不重写 ----
    def run(self, df: pd.DataFrame) -> tuple:
        """模板方法: 组装公共指标 + 调子类 generate(), 返回固定 5 元组。

        Returns:
            (entries, exits, indicators, size, reasons)
            - entries/exits: 布尔 Series (与 df 等长, fillna(False))
            - indicators: 公共(MA系统+量比) + 特色(generate 返回)
            - size: 仓位 Series 或 None (等权满仓)
            - reasons: {buy_reasons, sell_reasons} 或 None
        """
        n = len(df)
        res = self.generate(df)

        # 公共指标: 主图均线系统 + 量比副图 (看板双Y轴左轴契约 name='VR')
        indicators = self.ma_indicators(df, n)
        indicators.append(self.vr_indicator(self.compute_volume_ratio(df), n))
        indicators.extend(res.indicators)

        return (
            res.entries.fillna(False),
            res.exits.fillna(False),
            indicators,
            res.size,
            res.reasons,
        )

    def generate(self, df: pd.DataFrame) -> SignalResult:
        """子类钩子: 产出信号 + 特色指标 + 原因 + 仓位。

        返回 SignalResult。公共指标 (MA系统/量比) 由基类 run() 组装, 此处只放特色指标。
        """
        raise NotImplementedError

    # ---- 公共指标计算 ----
    def ma_series(self, df: pd.DataFrame, period: int) -> pd.Series:
        """单条简单移动平均线 (SMA)。"""
        return df["close"].astype(float).rolling(period).mean()

    def ma_indicators(self, df: pd.DataFrame, n: int) -> list:
        """主图均线系统指标 dict 列表, 按 self.MA_LINES 配置生成。

        所有策略共享同一套主图均线显示, 口径统一 (SMA, rolling period)。
        """
        out = []
        for period, color in self.MA_LINES:
            ma = self.ma_series(df, period)
            out.append({
                "name": f"MA{period}", "shortName": f"MA{period}",
                "pane": "main", "paneId": "main",
                "color": color, "values": series_to_list(ma, n),
            })
        return out

    def compute_volume_ratio(self, df: pd.DataFrame, window: int = 20) -> pd.Series:
        """量比值序列 = 当日成交量 / 过去 window 日均量。

        所有策略共用同一口径: >1 放量, <1 缩量, 1 上下波动。
        window 默认 20 (与 framework/factors/signal.py 的 volume_ratio 默认一致)。
        """
        vol = df["volume"].astype(float)
        return vol / vol.rolling(window).mean()

    def vr_indicator(self, ratio: pd.Series, n: int, color: str = "#52c41a") -> dict:
        """量比指标 dict。

        name 固定为 'VR' —— 这是与 dashboard.js 的显式契约:
        vol_pane 双 Y 轴左轴通过 find(name==='VR') 提取量比值渲染, name 不符则量比线不显示。
        ratio 应来自 compute_volume_ratio (或等价计算)。
        """
        return {"name": "VR", "shortName": "量比", "pane": "separate", "paneId": "vol",
                "color": color, "values": series_to_list(ratio, n)}

    def reasons_from_signals(self, entries: pd.Series, exits: pd.Series,
                             buy_reason: str, sell_reason: str) -> dict:
        """从信号 Series 构建买卖原因 dict (供 _export_result 在看板标注成交原因)。

        entries/exits 应是最终返回的 Series (经 fillna 等), 时间戳与 vectorbt 成交记录对齐。
        """
        buy_reasons, sell_reasons = {}, {}
        for idx in entries[entries.fillna(False)].index:
            buy_reasons[int(pd.Timestamp(idx).timestamp() * 1000)] = buy_reason
        for idx in exits[exits.fillna(False)].index:
            sell_reasons[int(pd.Timestamp(idx).timestamp() * 1000)] = sell_reason
        return {"buy_reasons": buy_reasons, "sell_reasons": sell_reasons}


def series_to_list(s, n):
    """pandas Series -> list[float|None], NaN 转 None"""
    vals = s.values
    return [None if np.isnan(v) else round(float(v), 4) for v in vals[:n]]


def signal_persist(signal: pd.Series, lookback: int) -> pd.Series:
    """信号持续: 近 lookback 日内有过 True 则保持 True。

    用于将单日事件(如放量、金叉)扩展为持续状态,
    避免多条件同日共振过严 (信号在不同日触发但实际是同一趋势)。
    lookback=1 时退化为原始行为 (仅当天满足)。
    """
    if lookback <= 1:
        return signal.fillna(False)
    return signal.rolling(lookback).max().fillna(0).astype(bool)
