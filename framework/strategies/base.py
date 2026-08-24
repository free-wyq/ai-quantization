"""策略基类与工具函数"""

import warnings
from typing import Any

import numpy as np
import pandas as pd


class Strategy:
    """策略基类: 自研策略继承此类，实现 run() 方法即可。

    使用方式:
        1. 在 strategies/custom/ 下新建 .py 文件
        2. 定义 Strategy 子类，设置 name/label/params
        3. 实现 run(df) 方法，返回 (entries, exits, indicators)
        4. 框架自动发现并注册，无需修改任何框架代码

    示例::

        class MyStrategy(Strategy):
            name = "my"
            label = "我的策略"
            params = {"period": 14}

            def run(self, df):
                close = df["close"]
                n = len(df)
                p = self.params
                ma = close.rolling(p["period"]).mean()
                entries = close > ma
                exits = close < ma
                indicators = [
                    {"name": "MA", "shortName": "MA", "pane": "separate", "paneId": "ma",
                     "color": "#ffa940", "values": series_to_list(ma, n)},
                ]
                return entries.fillna(False), exits.fillna(False), indicators
    """

    name = "base"
    label = "基础策略"
    params = {}

    def __init__(self, **overrides):
        # 拷贝 params，避免修改类属性
        self.params = dict(self.params)
        for k, v in overrides.items():
            if k in self.params:
                self.params[k] = v
            else:
                warnings.warn(f"策略 {self.name} 无参数 '{k}'，已忽略", stacklevel=2)

    def run(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series, list[dict[str, Any]]] | tuple[pd.Series, pd.Series, list[dict[str, Any]], pd.Series]:
        """计算策略信号与指标

        Args:
            df: K线数据, 含 open/high/low/close/volume 列, 每行代表一个交易日

        Returns:
            (entries, exits, indicators)  或  (entries, exits, indicators, size)
            entries: 布尔 Series (与 df 等长), True 表示该日触发买入信号
            exits:   布尔 Series (与 df 等长), True 表示该日触发平仓信号
            indicators: 指标列表, 每项是一条可视化曲线, 结构如下:
                {
                    "name": str,            # 唯一标识, 如 "MA5"
                    "shortName": str,       # 图例显示名, 如 "MA5"
                    "pane": str,            # "main" 叠加在K线上 / "separate" 独立副图
                    "paneId": str,          # 仅 separate 有效, 相同 paneId 共享一个副图
                    "color": str,           # 线条颜色, 如 "#ffa940"
                    "lineStyle": str,       # 可选: "solid"(实线) / "dashed"(虚线), 默认 solid
                    "lineWidth": int,       # 可选: 线宽, 默认 1
                    "type": str,            # 可选: "line"(折线) / "bar"(柱状), 默认 line
                    "values": list[float|None],  # 与 df 等长的数值序列, NaN 用 None
                }
            size:     [可选] 布尔 Series 或 float Series, 每笔买入的仓位比例(0~1)。
                      - None 或省略 → 引擎等权满仓 (老策略默认)
                      - 与 entries 等长的 Series → 仅在 entry 当日读取该值作为仓位
        """
        raise NotImplementedError

    # ---- 公共指标计算 (模板方法: 所有策略共享, 保证看板契约一致) ----
    # 设计: K线/成交量柱由看板渲染层统一画, 不进策略 indicators;
    #       量比(VR)是跨策略通用的市场结构指标, 计算口径与指标结构上提到基类,
    #       子类调用即可获得一致的量比线, 避免各策略手写 dict / 口径漂移;
    #       各策略特色指标 (MACD/RSI/KDJ 等) 才由子类自行实现。
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
        子类在 indicators 列表里 append 本方法返回值即可获得量比线。
        ratio 应来自 compute_volume_ratio (或等价计算)。
        """
        return {"name": "VR", "shortName": "量比", "pane": "separate", "paneId": "vol",
                "color": color, "values": series_to_list(ratio, n)}

    def reasons_from_signals(self, entries: pd.Series, exits: pd.Series,
                             buy_reason: str, sell_reason: str) -> dict:
        """从信号 Series 构建买卖原因 dict (供 _export_result 在看板标注成交原因)。

        策略返回四元组 (entries, exits, indicators, reasons) 即可让看板显示每笔交易的原因。
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
