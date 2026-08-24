"""测试策略基类: 参数覆盖、标签、未知参数警告、模板方法骨架"""

import warnings

import pandas as pd
import pytest

from framework.strategies import STRATS
from framework.strategies.base import Strategy, SignalResult, series_to_list
from framework.strategies.midterm import MidTermStrategy


class TestStrategyBase:
    """Strategy 基类行为"""

    def test_all_strategies_have_required_attrs(self):
        """每个策略都应有 label 和 params"""
        for key, cls in STRATS.items():
            instance = cls()
            assert hasattr(instance, "label"), f"{key} 缺少 label"
            assert hasattr(instance, "params"), f"{key} 缺少 params"
            assert isinstance(instance.params, dict), f"{key} params 不是 dict"

    def test_param_override(self):
        """参数覆盖应生效"""
        s = MidTermStrategy(vol_min=1.5, atr=20)
        assert s.params["vol_min"] == 1.5
        assert s.params["atr"] == 20

    def test_unknown_param_warning(self):
        """未知参数应触发警告"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            MidTermStrategy(unknown_param=999)
            assert len(w) == 1
            assert "unknown_param" in str(w[0].message)

    def test_run_not_implemented(self):
        """基类 generate 未实现时 run 应抛 NotImplementedError"""
        s = Strategy()
        with pytest.raises(NotImplementedError):
            s.run(pd.DataFrame())

    def test_ma_lines_default(self):
        """基类 MA_LINES 默认 4 条均线"""
        assert Strategy.MA_LINES == [(5, "#faad14"), (10, "#13c2c2"),
                                     (20, "#722ed1"), (60, "#f5222d")]


class TestTemplateMethod:
    """模板方法: run() 组装公共指标 (MA系统 + 量比) + 子类特色指标"""

    @staticmethod
    def _stub_strategy():
        """最小 Stub: 实现 generate 返回固定信号 + 一个特色指标"""
        class StubStrategy(Strategy):
            name = "stub"
            label = "测试桩"
            params = {}
            def generate(self, df):
                n = len(df)
                entries = pd.Series(False, index=df.index)
                exits = pd.Series(False, index=df.index)
                ind = [{"name": "SPECIAL", "shortName": "S", "pane": "separate",
                        "paneId": "sp", "color": "#fff",
                        "values": series_to_list(df["close"], n)}]
                return SignalResult(entries, exits, ind)
        return StubStrategy()

    def test_run_returns_fixed_5_tuple(self, sample_df):
        """run() 必须返回固定 5 元组 (entries, exits, indicators, size, reasons)"""
        s = self._stub_strategy()
        result = s.run(sample_df)
        assert len(result) == 5, "run() 应返回 5 元组"

    def test_run_injects_ma_system(self, sample_df):
        """基类自动注入 MA5/10/20/60 四条主图均线"""
        s = self._stub_strategy()
        _, _, indicators, _, _ = s.run(sample_df)
        names = [i["name"] for i in indicators]
        assert "MA5" in names and "MA10" in names
        assert "MA20" in names and "MA60" in names

    def test_run_preserves_special_indicators(self, sample_df):
        """子类特色指标保留在 indicators 中"""
        s = self._stub_strategy()
        _, _, indicators, _, _ = s.run(sample_df)
        names = [i["name"] for i in indicators]
        assert "SPECIAL" in names

    def test_run_size_and_reasons_default_none(self, sample_df):
        """未提供 size/reasons 时为 None"""
        s = self._stub_strategy()
        _, _, _, size, reasons = s.run(sample_df)
        assert size is None
        assert reasons is None
