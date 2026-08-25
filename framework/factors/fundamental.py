"""基本面排雷因子 (PE/PB分位 + ROE + 商誉占比)

定位: 选股池硬过滤 (排雷), 非择时。剔除估值过高 / 盈利差 / 商誉雷的股票。

数据源 (akshare, 均为非东财域名, WSL 可通):
  - PE/PB 历史: ak.stock_zh_valuation_baidu(symbol, indicator, period='全部')  -> gushitong.baidu.com
  - ROE / 商誉: ak.stock_financial_report_sina(stock, symbol='利润表'/'资产负债表') -> vip.stock.finance.sina

因子口径:
  - valuation_ok: 当日 PE分位 < pe_pct_max 且 PB分位 < pb_pct_max (估值不贵; 每日变动)
  - quality_ok:   最新 ROE(TTM) >= roe_min       (盈利达标; 季报口径TTM, 整段常数)
  - goodwill_ok:   最新 商誉/归母权益 < gw_ratio_max (商誉不超标; 整段常数)

缓存:
  data/fundamental/{symbol}_pe.csv / _pb.csv / _fundamentals.csv
  断网/取数失败 -> 读缓存; 缓存也无 -> 返回 None, midterm 基本面层自动跳过。

降级契约 (与 cross_stock/flow 一致): get_fundamental_factors 返回 None 表示数据不可用,
caller 跳过该层; 返回 dict 时各项已对齐到传入 index, 缺失日默认 True (不卡死)。

注: 新浪财务报表为银行股特殊口径(如 000001 利润表无传统营业收入但净利润口径完整),
ROE 用 归母净利润/归母权益 通用公式, 对所有股票一致。
"""
from __future__ import annotations

import os
import pandas as pd
from config.settings import DATA_DIR

_FUND_DIR = os.path.join(DATA_DIR, "fundamental")
_PE_CACHE: dict = {}        # {symbol: PE Series}
_PB_CACHE: dict = {}        # {symbol: PB Series}
_FUNDAMENTALS_CACHE: dict = {}  # {symbol: {'roe': float, 'gw_ratio': float}}


def _ensure_dir():
    os.makedirs(_FUND_DIR, exist_ok=True)


def _market_prefix(symbol: str) -> str:
    return "sh" if str(symbol).startswith(("6", "9")) else "sz"


def fetch_valuation(symbol: str, indicator: str) -> pd.Series | None:
    """百度估值历史 (PE-TTM 或 PB), 返回 float Series (index=日期)。失败返回 None。

    indicator: '市盈率(TTM)' 或 '市净率'
    """
    symbol = str(symbol).zfill(6)
    cache_key = f"pe" if "盈" in indicator else "pb"
    cache = _PE_CACHE if cache_key == "pe" else _PB_CACHE
    if symbol in cache:
        return cache[symbol]

    _ensure_dir()
    cache_path = os.path.join(_FUND_DIR, f"{symbol}_{cache_key}.csv")
    if os.path.exists(cache_path):
        try:
            s = pd.read_csv(cache_path, index_col=0, parse_dates=True).iloc[:, 0]
            cache[symbol] = s
            return s
        except Exception:
            pass
    try:
        import akshare as ak
        df = ak.stock_zh_valuation_baidu(symbol=symbol, indicator=indicator, period="全部")
        if df is None or len(df) == 0:
            return None
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        s = pd.to_numeric(df["value"], errors="coerce")
        s.index = df["date"]
        s = s.dropna().sort_index()
        s.name = cache_key
        s.to_csv(cache_path)
        cache[symbol] = s
        return s
    except Exception:
        return None


def fetch_fundamentals(symbol: str) -> dict | None:
    """新浪财务报表: 最新 ROE(TTM) 与 商誉占比。

    ROE = TTM归母净利润 / 最新归母权益 * 100 (%)
      TTM净利润 = 最近半年报累计 + 上一年年报 - 上一年同期半年报
        (滚动12月, 消除季节性; 若不足3期则用最新累计值近似, 银行股中报口径不影响排序)
    商誉占比 = 商誉 / 归母权益 * 100 (%)
    返回 {'roe': float, 'gw_ratio': float} 或 None。
    """
    symbol = str(symbol).zfill(6)
    if symbol in _FUNDAMENTALS_CACHE:
        return _FUNDAMENTALS_CACHE[symbol]

    _ensure_dir()
    cache_path = os.path.join(_FUND_DIR, f"{symbol}_fundamentals.csv")
    if os.path.exists(cache_path):
        try:
            row = pd.read_csv(cache_path)
            d = {"roe": float(row["roe"].iloc[0]), "gw_ratio": float(row["gw_ratio"].iloc[0])}
            _FUNDAMENTALS_CACHE[symbol] = d
            return d
        except Exception:
            pass
    try:
        import akshare as ak
        stock = f"{_market_prefix(symbol)}{symbol}"
        bs = ak.stock_financial_report_sina(stock=stock, symbol="资产负债表")
        inc = ak.stock_financial_report_sina(stock=stock, symbol="利润表")
        if bs is None or inc is None or len(bs) == 0 or len(inc) == 0:
            return None
        bs = bs.set_index("报告日")
        inc = inc.set_index("报告日")

        eq_col = next((c for c in bs.columns if "母公司" in c and "权益" in c), None)
        gw_col = next((c for c in bs.columns if "商誉" in c), None)
        np_col = next((c for c in inc.columns if "母公司" in c and "净利润" in c), None)
        if eq_col is None or np_col is None:
            return None

        equity = pd.to_numeric(bs[eq_col], errors="coerce")
        goodwill = pd.to_numeric(bs[gw_col], errors="coerce") if gw_col else pd.Series(0, index=bs.index)
        netprofit = pd.to_numeric(inc[np_col], errors="coerce")

        equity_v = equity.dropna().iloc[0] if equity.dropna().size else None
        if equity_v is None or equity_v == 0:
            return None
        gw_v = goodwill.dropna().iloc[0] if goodwill.dropna().size else 0.0

        # TTM 归母净利润 (滚动12月): 最新半年报累计 + 上一年年报 - 上一年同期半年报
        np_idx = netprofit.dropna()
        np_v = np_idx.iloc[0] if np_idx.size else 0.0
        if len(np_idx) >= 3:
            dates = list(np_idx.index)
            latest = dates[0]                      # 最新报告日
            latest_h1 = str(pd.Timestamp(latest).year) + "0630" if str(latest).endswith("0630") else None
            if latest_h1 and latest_h1 == latest:
                prev_year = str(pd.Timestamp(latest).year - 1)
                annual = f"{prev_year}1231"
                prev_h1 = f"{prev_year}0630"
                if annual in np_idx.index and prev_h1 in np_idx.index:
                    np_v = np_idx.loc[latest] + np_idx.loc[annual] - np_idx.loc[prev_h1]

        d = {"roe": round(np_v / equity_v * 100, 2), "gw_ratio": round(gw_v / equity_v * 100, 2)}
        pd.DataFrame([d]).to_csv(cache_path, index=False)
        _FUNDAMENTALS_CACHE[symbol] = d
        return d
    except Exception:
        return None


def valuation_signal(symbol: str, index: pd.DatetimeIndex,
                     lookback: int = 1250, pe_max: float = 80.0,
                     pb_max: float = 80.0) -> pd.Series:
    """PE/PB 分位同时 < 阈值 布尔 (估值不贵), 对齐到 index。数据不可用默认 True。

    lookback: 分位回看窗口 (默认 1250 交易日 ≈ 5年)。
    pe_max/pb_max: 分位上限(百分数), 如 80 表示 PE/PB 不超过近5年80%分位。

    注: 百度 PE/PB 历史日期互不对齐 (不同日有值), 先各自 reindex+ffill 到统一日历,
    再算分位, 否则 AND 因错位日期产生 NaN 而失效。
    """
    pe = fetch_valuation(symbol, "市盈率(TTM)")
    pb = fetch_valuation(symbol, "市净率")
    has_pe = pe is not None and len(pe) > 0
    has_pb = pb is not None and len(pb) > 0
    if not has_pe and not has_pb:
        return pd.Series(True, index=index)

    def _pct_rank(s: pd.Series) -> pd.Series:
        if s is None or len(s) == 0:
            return None
        # 先对齐到目标日历并前向填充, 保证 PE/PB 同日可比
        s_daily = s.reindex(index, method="ffill").dropna()
        if s_daily.empty:
            return None
        win = lookback
        return s_daily.rolling(win, min_periods=min(60, win)).apply(
            lambda x: float((x[-1] >= x).mean()) * 100, raw=True)

    pe_rank = _pct_rank(pe) if has_pe else None
    pb_rank = _pct_rank(pb) if has_pb else None
    if pe_rank is not None and pb_rank is not None:
        sig = (pe_rank < pe_max) & (pb_rank < pb_max)
    elif pe_rank is not None:
        sig = pe_rank < pe_max
    elif pb_rank is not None:
        sig = pb_rank < pb_max
    else:
        return pd.Series(True, index=index)
    return sig.astype(bool).reindex(index).fillna(True)


def quality_signal(symbol: str, index: pd.DatetimeIndex,
                   roe_min: float = 8.0) -> pd.Series:
    """ROE >= roe_min 布尔 (盈利达标, 整段常数), 对齐到 index。数据不可用默认 True。"""
    d = fetch_fundamentals(symbol)
    ok = (d is not None and d["roe"] >= roe_min)
    return pd.Series(ok, index=index)


def goodwill_signal(symbol: str, index: pd.DatetimeIndex,
                    gw_ratio_max: float = 30.0) -> pd.Series:
    """商誉占比 < gw_ratio_max 布尔 (商誉不超标, 整段常数), 对齐到 index。数据不可用默认 True。"""
    d = fetch_fundamentals(symbol)
    ok = (d is not None and d["gw_ratio"] < gw_ratio_max)
    return pd.Series(ok, index=index)


def get_fundamental_factors(symbol: str, index: pd.DatetimeIndex,
                            lookback: int = 1250, pe_max: float = 80.0,
                            pb_max: float = 80.0, roe_min: float = 8.0,
                            gw_ratio_max: float = 30.0):
    """为单股取基本面排雷因子切片。

    Returns:
        dict: {
          'valuation': bool Series (PE/PB分位不贵, 每日),
          'quality':   bool Series (ROE达标, 常数),
          'goodwill':  bool Series (商誉不超标, 常数),
        } 全对齐到 index, 缺失日默认 True (放行)。
        None: 所有基本面数据均不可用时 (caller 跳过该层)。
    """
    pe = fetch_valuation(symbol, "市盈率(TTM)")
    pb = fetch_valuation(symbol, "市净率")
    fd = fetch_fundamentals(symbol)
    if (pe is None or len(pe) == 0) and (pb is None or len(pb) == 0) and fd is None:
        return None
    return {
        "valuation": valuation_signal(symbol, index, lookback, pe_max, pb_max),
        "quality": quality_signal(symbol, index, roe_min),
        "goodwill": goodwill_signal(symbol, index, gw_ratio_max),
    }
