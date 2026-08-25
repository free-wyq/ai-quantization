"""资金面因子 (北向资金净流入 + 个股主力资金净流入)

数据源 (akshare, 东方财富):
  - 北向资金:   ak.stock_hsgt_hist_em(symbol='北向资金')        -> 日度净流入历史 (全市场共享)
  - 个股主力:   ak.stock_individual_fund_flow(stock, market)      -> 日度主力净流入历史 (单股)

缓存:
  data/flow/northbound.csv            北向净流入 (全市场共享一份)
  data/flow/{symbol}_flow.csv         个股主力净流入 (按 symbol)
  断网/取数失败 -> 读缓存; 缓存也无 -> 返回 None, midterm 资金面层自动跳过 (开关形同关闭)。

因子口径 (共振确认, 非择时):
  - 北向: 当日北向净流入 > 0  (外资看好)
  - 主力: 当日主力净流入 > 0  (大单净买入)
  二项独立返回布尔 Series; midterm 可单独用或合并共振。数据不全时默认放行 (True)。

降级契约 (与 cross_stock.py 一致): get_flow_factors 返回 None 表示数据不可用,
caller 应跳过该层; 返回 dict 时各项已对齐到传入 index, 缺失日默认 True (不卡死)。
"""
from __future__ import annotations

import os
import pandas as pd
from config.settings import DATA_DIR

_FLOW_DIR = os.path.join(DATA_DIR, "flow")
_NB_CACHE: pd.Series | None = None     # 北向净流入 (全市场)
_FLOW_CACHE: dict = {}                 # {symbol: 主力净流入 Series}


def _market_of(symbol: str) -> str:
    """6位代码 -> 东财 market 标识 (sh/sz)。与 fetcher._from_sina 同口径。"""
    return "sh" if str(symbol).startswith(("6", "9")) else "sz"


def _ensure_dir():
    os.makedirs(_FLOW_DIR, exist_ok=True)


def fetch_northbound() -> pd.Series | None:
    """北向资金日度净流入 (亿元)。缓存优先 -> akshare 东财。失败返回 None。"""
    global _NB_CACHE
    if _NB_CACHE is not None:
        return _NB_CACHE

    _ensure_dir()
    cache_path = os.path.join(_FLOW_DIR, "northbound.csv")
    # 1. 内存/磁盘缓存
    if os.path.exists(cache_path):
        try:
            s = pd.read_csv(cache_path, index_col=0, parse_dates=True).iloc[:, 0]
            s.name = "northbound"
            _NB_CACHE = s
            return s
        except Exception:
            pass
    # 2. 联网 (akshare 东财北向历史)
    try:
        import akshare as ak
        df = ak.stock_hsgt_hist_em(symbol="北向资金")
        # 东财列名: 日期 / 当日成交净买额(或 当日资金流入) 等, 取净买额列
        if df is None or len(df) == 0:
            return None
        df = df.copy()
        date_col = "日期" if "日期" in df.columns else df.columns[0]
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.set_index(date_col).sort_index()
        # 净买额列名随接口版本变化, 按关键字匹配
        net_col = None
        for c in df.columns:
            if "净买" in c or "净流入" in c or "成交净" in c:
                net_col = c
                break
        if net_col is None:
            net_col = df.columns[0]
        s = pd.to_numeric(df[net_col], errors="coerce").dropna()
        s.name = "northbound"
        s.to_csv(cache_path)
        _NB_CACHE = s
        return s
    except Exception:
        return None


def fetch_stock_main_flow(symbol: str) -> pd.Series | None:
    """个股主力资金日度净流入 (元)。缓存优先 -> akshare 东财。失败返回 None。"""
    symbol = str(symbol).zfill(6)
    if symbol in _FLOW_CACHE:
        return _FLOW_CACHE[symbol]

    _ensure_dir()
    cache_path = os.path.join(_FLOW_DIR, f"{symbol}_flow.csv")
    if os.path.exists(cache_path):
        try:
            s = pd.read_csv(cache_path, index_col=0, parse_dates=True).iloc[:, 0]
            s.name = "main_flow"
            _FLOW_CACHE[symbol] = s
            return s
        except Exception:
            pass
    try:
        import akshare as ak
        df = ak.stock_individual_fund_flow(stock=symbol, market=_market_of(symbol))
        if df is None or len(df) == 0:
            return None
        df = df.copy()
        date_col = "日期" if "日期" in df.columns else df.columns[0]
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.set_index(date_col).sort_index()
        # 主力净流入列名: "主力净流入-净额" / "主力净流入净额" 等
        net_col = None
        for c in df.columns:
            if "主力" in c and ("净额" in c or "净流入" in c):
                net_col = c
                break
        if net_col is None:
            return None
        s = pd.to_numeric(df[net_col], errors="coerce").dropna()
        s.name = "main_flow"
        s.to_csv(cache_path)
        _FLOW_CACHE[symbol] = s
        return s
    except Exception:
        return None


def northbound_signal(index: pd.DatetimeIndex) -> pd.Series:
    """北向净流入>0 布尔, 对齐到 index。数据不可用默认全 True (放行)。"""
    s = fetch_northbound()
    if s is None or len(s) == 0:
        return pd.Series(True, index=index)
    sig = (s > 0).astype(bool)
    return sig.reindex(index, method="ffill").fillna(True)


def main_flow_signal(symbol: str, index: pd.DatetimeIndex) -> pd.Series:
    """个股主力净流入>0 布尔, 对齐到 index。数据不可用默认全 True (放行)。"""
    s = fetch_stock_main_flow(symbol)
    if s is None or len(s) == 0:
        return pd.Series(True, index=index)
    sig = (s > 0).astype(bool)
    return sig.reindex(index, method="ffill").fillna(True)


def get_flow_factors(symbol: str, index: pd.DatetimeIndex):
    """为单股取资金面因子切片。

    Returns:
        dict: {'northbound': bool Series, 'main_flow': bool Series} 全对齐到 index
              缺失日默认 True (放行)。
        None: 北向与个股主力数据均不可用时 (caller 跳过该层)。
    """
    nb = fetch_northbound()
    mf = fetch_stock_main_flow(symbol)
    if (nb is None or len(nb) == 0) and (mf is None or len(mf) == 0):
        return None
    return {
        "northbound": northbound_signal(index),
        "main_flow": main_flow_signal(symbol, index),
    }
