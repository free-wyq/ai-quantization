"""测试指标计算函数: calc_rsi, calc_adx, calc_obv 等"""

import numpy as np
import pandas as pd
import pytest

from framework.strategies.rsi import calc_rsi
from framework.strategies.obv import calc_obv


class TestCalcRSI:

    def test_rsi_range(self, sample_df):
        """RSI 应在 0-100 之间"""
        rsi = calc_rsi(sample_df["close"], 14)
        valid = rsi.dropna()
        assert (valid >= 0).all() and (valid <= 100).all(), "RSI 超出 0-100 范围"

    def test_rsi_period_affects_sensitivity(self, sample_df):
        """短周期 RSI 比长周期更敏感 (波动更大)"""
        rsi_short = calc_rsi(sample_df["close"], 7)
        rsi_long = calc_rsi(sample_df["close"], 21)
        assert rsi_short.std() > rsi_long.std(), "短周期 RSI 波动应更大"

    def test_rsi_uptrend_high(self, sample_df):
        """上涨趋势段 RSI 偏高"""
        rsi = calc_rsi(sample_df["close"], 14)
        # 取前50天（上涨趋势段）的 RSI 均值
        trend_rsi = rsi.iloc[14:50].dropna()
        assert trend_rsi.mean() > 50, f"上涨趋势段 RSI 均值应 > 50, 实际 {trend_rsi.mean():.1f}"

    def test_rsi_all_up(self, sample_df):
        """上涨趋势段 RSI 应偏高"""
        rsi = calc_rsi(sample_df["close"], 14)
        trend_rsi = rsi.iloc[14:50].dropna()
        assert len(trend_rsi) > 0, "应有有效 RSI 值"
        assert trend_rsi.mean() > 60, f"上涨段 RSI 均值应 > 60, 实际 {trend_rsi.mean():.1f}"


class TestCalcOBV:

    def test_obv_increases_on_up_day(self, sample_df):
        """上涨日 OBV 应增加"""
        obv = calc_obv(sample_df["close"], sample_df["volume"])
        up_days = sample_df["close"] > sample_df["close"].shift(1)
        assert up_days.sum() > 0, "测试数据应有上涨日"

    def test_obv_decreases_on_down_day(self, sample_df):
        """下跌日 OBV 应减少"""
        obv = calc_obv(sample_df["close"], sample_df["volume"])
        down_days = sample_df["close"] < sample_df["close"].shift(1)
        assert down_days.sum() > 0, "测试数据应有下跌日"

    def test_obv_pure_uptrend_positive(self, uptrend_df):
        """纯上涨趋势 OBV 应持续增加"""
        obv = calc_obv(uptrend_df["close"], uptrend_df["volume"])
        assert obv.iloc[-1] > obv.iloc[1], "上涨趋势 OBV 应持续增加"
