"""测试 MA 策略核心逻辑: 金叉买入、死叉卖出"""

import pandas as pd

from framework.strategies.ma import MAStrategy


class TestMAStrategy:

    def test_golden_cross_triggers_entry(self, sample_df):
        """含趋势+震荡的数据中应出现金叉买入信号"""
        s = MAStrategy(fast=5, slow=20)
        entries, exits, indicators = s.run(sample_df)
        assert entries.sum() > 0, "应有买入信号"

    def test_death_cross_triggers_exit(self, sample_df):
        """含趋势+震荡的数据中应出现死叉卖出信号"""
        s = MAStrategy(fast=5, slow=20)
        entries, exits, indicators = s.run(sample_df)
        assert exits.sum() > 0, "应有卖出信号"

    def test_entry_means_fast_crosses_above_slow(self, uptrend_df):
        """买入信号当天: 快线从下方穿到上方"""
        s = MAStrategy(fast=5, slow=20)
        entries, exits, indicators = s.run(uptrend_df)

        ma_fast = uptrend_df["close"].rolling(5).mean()
        ma_slow = uptrend_df["close"].rolling(20).mean()

        for i in range(1, len(uptrend_df)):
            if entries.iloc[i]:
                # 今天快线在上方
                assert ma_fast.iloc[i] > ma_slow.iloc[i], \
                    f"买入信号第{i}天: 快线应 > 慢线"
                # 昨天快线在下方
                assert ma_fast.iloc[i-1] <= ma_slow.iloc[i-1], \
                    f"买入信号第{i}天: 前一天快线应 <= 慢线"

    def test_exit_means_fast_crosses_below_slow(self, uptrend_df):
        """卖出信号当天: 快线从上方穿到下方"""
        s = MAStrategy(fast=5, slow=20)
        entries, exits, indicators = s.run(uptrend_df)

        ma_fast = uptrend_df["close"].rolling(5).mean()
        ma_slow = uptrend_df["close"].rolling(20).mean()

        for i in range(1, len(uptrend_df)):
            if exits.iloc[i]:
                assert ma_fast.iloc[i] < ma_slow.iloc[i], \
                    f"卖出信号第{i}天: 快线应 < 慢线"
                assert ma_fast.iloc[i-1] >= ma_slow.iloc[i-1], \
                    f"卖出信号第{i}天: 前一天快线应 >= 慢线"

    def test_indicators_contain_ma_lines(self, sample_df):
        """指标列表应包含 MA 快线和慢线"""
        s = MAStrategy(fast=5, slow=20)
        entries, exits, indicators = s.run(sample_df)
        names = [ind["name"] for ind in indicators]
        assert "MA_Fast" in names, f"缺少 MA_Fast, 实际: {names}"
        assert "MA_Slow" in names, f"缺少 MA_Slow, 实际: {names}"

    def test_custom_params(self, sample_df):
        """自定义参数应生效"""
        s = MAStrategy(fast=10, slow=30)
        assert s.params["fast"] == 10
        assert s.params["slow"] == 30
        entries, exits, indicators = s.run(sample_df)
        # 不同参数应产生不同信号
        s2 = MAStrategy(fast=3, slow=10)
        entries2, _, _ = s2.run(sample_df)
        assert not entries.equals(entries2), "不同参数应产生不同信号"
