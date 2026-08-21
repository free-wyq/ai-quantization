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

    def run(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series, list[dict[str, Any]]]:
        """计算策略信号与指标

        Args:
            df: K线数据, 含 open/high/low/close/volume 列, 每行代表一个交易日

        Returns:
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
        """
        raise NotImplementedError


def series_to_list(s, n):
    """pandas Series -> list[float|None], NaN 转 None"""
    vals = s.values
    return [None if np.isnan(v) else round(float(v), 4) for v in vals[:n]]
