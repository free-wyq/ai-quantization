"""行情数据获取模块

支持:
- 本地缓存 (优先读取 data/{symbol}_daily.csv)
- 多数据源 fallback (东方财富 -> 新浪)
"""

import os
import pandas as pd
import akshare as ak
from loguru import logger

from config.settings import DATA_DIR


def _cache_path(symbol: str) -> str:
    return os.path.join(DATA_DIR, f"{symbol}_daily.csv")


def _load_cache(symbol: str) -> pd.DataFrame | None:
    """尝试从本地缓存读取数据"""
    path = _cache_path(symbol)
    if os.path.exists(path):
        logger.info(f"读取本地缓存: {path}")
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return df
    return None


def _save_cache(df: pd.DataFrame, symbol: str):
    """保存数据到本地缓存"""
    path = _cache_path(symbol)
    df.to_csv(path)
    logger.info(f"数据已缓存到 {path}")


def _from_eastmoney(symbol: str, start_date: str, end_date: str,
                    name: str = "") -> pd.DataFrame:
    """东方财富数据源 (akshare)

    返回字段: symbol, name, open, high, low, close, volume, amount,
             amplitude, pct_change, change, turnover_rate
    """
    df = ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust="qfq",
    )
    df = df.rename(columns={
        "日期": "date", "股票代码": "symbol",
        "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low",
        "成交量": "volume", "成交额": "amount",
        "振幅": "amplitude", "涨跌幅": "pct_change", "涨跌额": "change",
        "换手率": "turnover_rate",
    })
    df["name"] = name
    df["date"] = pd.to_datetime(df["date"])
    # 统一列顺序
    cols = ["symbol", "name", "open", "high", "low", "close",
            "volume", "amount", "amplitude", "pct_change", "change",
            "turnover_rate"]
    df = df[[c for c in cols if c in df.columns]]
    return df.set_index("date")


def _from_sina(symbol: str, start_date: str, end_date: str,
               name: str = "") -> pd.DataFrame:
    """新浪数据源 (akshare)

    返回字段: symbol, name, open, high, low, close, volume, amount,
             amplitude, pct_change, change, turnover_rate

    新浪源不直接提供振幅/涨跌幅/涨跌额, 由 OHLC 补算:
    - pct_change = (close - prev_close) / prev_close * 100
    - change     = close - prev_close
    - amplitude  = (high - low) / prev_close * 100
    """
    prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
    df = ak.stock_zh_a_daily(
        symbol=f"{prefix}{symbol}",
        start_date=start_date,
        end_date=end_date,
        adjust="qfq",
    )
    df = df.rename(columns={"turnover": "turnover_rate"})
    # 新浪换手率是小数比率 (0.005 = 0.5%), 转为百分比与东方财富统一
    df["turnover_rate"] = (df["turnover_rate"] * 100).round(2)
    df["symbol"] = symbol
    df["name"] = name
    df["date"] = pd.to_datetime(df["date"])

    # 补算涨跌幅/涨跌额/振幅 (依赖前一日收盘)
    prev_close = df["close"].shift(1)
    df["change"] = (df["close"] - prev_close).round(2)
    df["pct_change"] = (df["change"] / prev_close * 100).round(2)
    df["amplitude"] = ((df["high"] - df["low"]) / prev_close * 100).round(2)

    # 统一列顺序 (去掉 outstanding_share)
    cols = ["date", "symbol", "name", "open", "high", "low", "close",
            "volume", "amount", "amplitude", "pct_change", "change",
            "turnover_rate"]
    df = df[[c for c in cols if c in df.columns]]
    return df.set_index("date")


def _download(symbol: str, start_date: str, end_date: str,
              name: str = "") -> pd.DataFrame:
    """联网获取指定区间行情 (多数据源兜底: 新浪 -> 东方财富)"""
    logger.info(f"获取 {symbol} 行情数据: {start_date} ~ {end_date}")
    df = None
    for src_name, func in [("新浪", _from_sina), ("东方财富", _from_eastmoney)]:
        try:
            logger.info(f"尝试数据源: {src_name}")
            df = func(symbol, start_date, end_date, name=name)
            if df is not None and len(df) > 0:
                logger.info(f"数据源 {src_name} 成功, 获取 {len(df)} 条")
                break
        except Exception as e:
            logger.warning(f"数据源 {src_name} 失败: {e}")

    if df is None or len(df) == 0:
        raise ConnectionError(
            f"所有数据源均失败, 请检查网络连接或稍后重试。\n"
            f"如需离线学习, 可将数据放入: {_cache_path(symbol)}"
        )
    return df


def fetch_stock_history(symbol: str, start_date: str, end_date: str,
                        use_cache: bool = True, name: str = "") -> pd.DataFrame:
    """
    获取股票历史行情数据

    Args:
        symbol: 股票代码, 如 "000001"
        start_date: 开始日期, 如 "20240101"
        end_date: 结束日期, 如 "20241231"
        use_cache: 是否优先使用本地缓存 (默认 True)
        name: 股票名称 (可选, 会写入 CSV 的 name 列)

    Returns:
        包含 OHLCV 数据的 DataFrame (按请求的 start_date~end_date 区间返回)
    """
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)

    # 1. 优先读缓存: 历史区间已覆盖即直接用, 仅实时区间要求新鲜
    if use_cache:
        cached = _load_cache(symbol)
        if cached is not None:
            cstart, cend = cached.index.min(), cached.index.max()
            today = pd.Timestamp.now().normalize()
            is_fresh = cend >= (today - pd.Timedelta(days=1))
            # 请求的是历史区间(end 在过去) → 只要缓存覆盖就直接复用, 不再联网
            is_history = end < (today - pd.Timedelta(days=1))
            covers = cstart <= start and cend >= end

            if covers and (is_fresh or is_history):
                logger.info(f"缓存已覆盖区间, 直接复用: {start.date()} ~ {end.date()}")
                return cached.loc[start:end]
            # 未覆盖或需刷新最新数据 → 联网补充并合并回缓存
            logger.info(
                f"缓存(末尾{cend.date()})未覆盖/需刷新, 联网补充: "
                f"{start.date()}~{end.date()}"
            )
            df = _download(symbol, start_date, end_date, name=name)
            merged = pd.concat([cached, df])
            merged = merged[~merged.index.duplicated(keep='last')].sort_index()
            _save_cache(merged, symbol)
            return merged.loc[start:end]

    # 2. 无缓存 / 关闭缓存 -> 直接联网获取请求的区间
    df = _download(symbol, start_date, end_date, name=name)
    _save_cache(df, symbol)
    return df


if __name__ == "__main__":
    df = fetch_stock_history("000001", "20240101", "20241231")
    print(df.head())
