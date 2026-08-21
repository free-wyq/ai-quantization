"""测试策略基类: 参数覆盖、标签、未知参数警告"""

import warnings

import pandas as pd
import pytest

from framework.strategies import STRATS
from framework.strategies.base import Strategy


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
        from framework.strategies.ma import MAStrategy
        s = MAStrategy(fast=10, slow=30)
        assert s.params["fast"] == 10
        assert s.params["slow"] == 30

    def test_unknown_param_warning(self):
        """未知参数应触发警告"""
        from framework.strategies.ma import MAStrategy
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            MAStrategy(unknown_param=999)
            assert len(w) == 1
            assert "unknown_param" in str(w[0].message)

    def test_run_not_implemented(self):
        """基类 run 应抛 NotImplementedError"""
        s = Strategy()
        with pytest.raises(NotImplementedError):
            s.run(pd.DataFrame())
