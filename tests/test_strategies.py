"""测试所有策略的返回值格式: 类型、长度、必填字段"""

import pandas as pd
import pytest

from strategies import STRATS


@pytest.fixture(params=list(STRATS.keys()))
def strategy_result(request, sample_df):
    """参数化: 对每个策略跑一遍 run(), 返回 (key, entries, exits, indicators)"""
    key = request.param
    strategy = STRATS[key]()
    result = strategy.run(sample_df)
    # run() 返回固定 5 元组 (entries, exits, indicators, size, reasons)
    entries, exits, indicators = result[0], result[1], result[2]
    return key, entries, exits, indicators, sample_df


class TestStrategyReturnFormat:
    """所有策略返回值格式一致性"""

    def test_entries_is_bool_series(self, strategy_result):
        key, entries, exits, indicators, df = strategy_result
        assert isinstance(entries, pd.Series), f"{key}: entries 不是 pd.Series"
        assert entries.dtype == bool, f"{key}: entries 不是 bool 类型, 实际 {entries.dtype}"

    def test_exits_is_bool_series(self, strategy_result):
        key, entries, exits, indicators, df = strategy_result
        assert isinstance(exits, pd.Series), f"{key}: exits 不是 pd.Series"
        assert exits.dtype == bool, f"{key}: exits 不是 bool 类型, 实际 {exits.dtype}"

    def test_entries_exits_same_length_as_df(self, strategy_result):
        key, entries, exits, indicators, df = strategy_result
        assert len(entries) == len(df), f"{key}: entries 长度 {len(entries)} != df 长度 {len(df)}"
        assert len(exits) == len(df), f"{key}: exits 长度 {len(exits)} != df 长度 {len(df)}"

    def test_entries_exits_same_index(self, strategy_result):
        key, entries, exits, indicators, df = strategy_result
        assert entries.index.equals(df.index), f"{key}: entries index 与 df 不一致"
        assert exits.index.equals(df.index), f"{key}: exits index 与 df 不一致"

    def test_indicators_is_list_of_dict(self, strategy_result):
        key, entries, exits, indicators, df = strategy_result
        assert isinstance(indicators, list), f"{key}: indicators 不是 list"
        for i, ind in enumerate(indicators):
            assert isinstance(ind, dict), f"{key}: indicators[{i}] 不是 dict"

    def test_indicators_have_required_fields(self, strategy_result):
        key, entries, exits, indicators, df = strategy_result
        required = {"name", "values"}
        for i, ind in enumerate(indicators):
            missing = required - set(ind.keys())
            assert not missing, f"{key}: indicators[{i}] 缺少字段 {missing}"

    def test_indicator_values_length(self, strategy_result):
        key, entries, exits, indicators, df = strategy_result
        for i, ind in enumerate(indicators):
            assert len(ind["values"]) == len(df), \
                f"{key}: indicators[{i}] '{ind.get('name', '?')}' values 长度 {len(ind['values'])} != df 长度 {len(df)}"

    def test_no_entry_and_exit_same_day(self, strategy_result):
        """同一天不应同时出现买入和卖出信号"""
        key, entries, exits, indicators, df = strategy_result
        overlap = (entries & exits).sum()
        assert overlap == 0, f"{key}: 有 {overlap} 天同时出现买入和卖出信号"
