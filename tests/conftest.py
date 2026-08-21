"""共享测试 fixtures: 构造模拟K线数据, 不依赖网络"""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def sample_df():
    """100天模拟K线数据, 含趋势段和震荡段"""
    np.random.seed(42)
    n = 100
    dates = pd.date_range("2026-01-01", periods=n, freq="B")

    # 前50天上涨趋势, 后50天震荡
    trend = np.linspace(10, 15, 50)
    noise = np.random.randn(50) * 0.1
    close_trend = trend + noise

    range_prices = 15 + np.sin(np.linspace(0, 6 * np.pi, 50)) * 0.5
    close_range = range_prices + np.random.randn(50) * 0.1

    close = np.concatenate([close_trend, close_range])
    opn = close + np.random.randn(n) * 0.05
    high = np.maximum(opn, close) + np.abs(np.random.randn(n)) * 0.1
    low = np.minimum(opn, close) - np.abs(np.random.randn(n)) * 0.1
    volume = np.random.randint(100000, 500000, n).astype(float)

    df = pd.DataFrame({
        "open": opn, "high": high, "low": low, "close": close, "volume": volume
    }, index=dates)
    return df


@pytest.fixture
def uptrend_df():
    """纯上涨趋势数据"""
    n = 60
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    close = pd.Series(np.linspace(10, 20, n), index=dates)
    df = pd.DataFrame({
        "open": close - 0.05,
        "high": close + 0.1,
        "low": close - 0.1,
        "close": close,
        "volume": np.full(n, 200000.0),
    }, index=dates)
    return df


@pytest.fixture
def sideways_df():
    """纯震荡数据 (围绕均值波动)"""
    n = 60
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    close = pd.Series(15 + np.sin(np.linspace(0, 8 * np.pi, n)) * 1.0, index=dates)
    df = pd.DataFrame({
        "open": close - 0.05,
        "high": close + 0.2,
        "low": close - 0.2,
        "close": close,
        "volume": np.full(n, 200000.0),
    }, index=dates)
    return df
