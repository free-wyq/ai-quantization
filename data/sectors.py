"""板块数据模块 (申万一级行业真指数)

提供:
- 申万一级行业列表 (31个) 下载与缓存
- 板块指数日K (申万官方指数) 下载与缓存
- 个股 -> 所属板块 映射下载与缓存
- 板块成分股查询

数据源: akshare 申万接口 (数据干净、官方、31个一级行业)
  - sw_index_first_info()        板块列表
  - index_hist_sw(symbol)         板块指数日K (全量, 本地切片)
  - index_component_sw(symbol)    板块成分股

运行方式 (项目根目录):
    python -m data.sectors            # 下载板块列表 + 映射 + 全部板块指数
    python -m data.sectors --list     # 仅板块列表
    python -m data.sectors --mapping  # 仅个股-板块映射
    python -m data.sectors --index    # 仅全部板块指数日K
"""

import os
import time
import argparse
import datetime

import pandas as pd
import akshare as ak
from loguru import logger

from config.settings import DATA_DIR

# 板块数据缓存目录
SECTOR_DIR = os.path.join(DATA_DIR, "sectors")
os.makedirs(SECTOR_DIR, exist_ok=True)

SECTOR_LIST_CACHE = os.path.join(DATA_DIR, "sector_list.csv")
SECTOR_MAPPING_CACHE = os.path.join(DATA_DIR, "sector_mapping.csv")

# 默认回测起点 (与 batch_download 对齐)
DEFAULT_START = "20210101"


# ============================================================
# 1. 申万一级行业列表
# ============================================================
def fetch_sector_list(use_cache: bool = True) -> pd.DataFrame:
    """获取申万一级行业列表 (31个)

    Returns:
        DataFrame: columns=['行业代码','行业名称','成份个数',...]
        行业代码示例: '801010' (农林牧渔)
    """
    if use_cache:
        if os.path.exists(SECTOR_LIST_CACHE):
            logger.info(f"板块列表缓存命中: {SECTOR_LIST_CACHE}")
            return pd.read_csv(SECTOR_LIST_CACHE)

    logger.info("联网获取申万一级行业列表 (sw_index_first_info)")
    df = ak.sw_index_first_info()
    df = df.rename(columns={"行业代码": "sector_code", "行业名称": "sector_name"})
    df.to_csv(SECTOR_LIST_CACHE, index=False, encoding="utf-8-sig")
    logger.info(f"板块列表已缓存: {SECTOR_LIST_CACHE} ({len(df)}个)")
    return df


# ============================================================
# 2. 板块指数 (申万官方日K)
# ============================================================
def fetch_sector_index(sector_code: str, start_date: str, end_date: str,
                       use_cache: bool = True) -> pd.DataFrame:
    """获取单个申万行业指数日K

    Args:
        sector_code: 申万行业代码, 如 "801010"
        start_date:  "20210101"
        end_date:    "20260823"
        use_cache:   是否使用本地缓存

    Returns:
        DataFrame, 以 date 为索引, 列与个股行情对齐:
        open/high/low/close/volume/amount
        (申万指数不含 amplitude/pct_change, 由调用方按需补算)
    """
    path = os.path.join(SECTOR_DIR, f"{sector_code}_daily.csv")

    if use_cache:
        if os.path.exists(path):
            cached = pd.read_csv(path, index_col=0, parse_dates=True)
            cstart, cend = cached.index.min(), cached.index.max()
            start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
            today = pd.Timestamp.now().normalize()
            is_fresh = cend >= (today - pd.Timedelta(days=1))
            if cstart <= start and cend >= end and is_fresh:
                logger.info(f"板块指数缓存命中: {sector_code}")
                return cached.loc[start:end]

    logger.info(f"联网获取申万指数: {sector_code} {start_date}~{end_date}")
    raw = ak.index_hist_sw(symbol=sector_code, period="day")
    raw = raw.rename(columns={
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low",
        "成交量": "volume", "成交额": "amount",
    })
    raw["date"] = pd.to_datetime(raw["date"])
    cols = ["date", "open", "high", "low", "close", "volume", "amount"]
    raw = raw[[c for c in cols if c in raw.columns]].set_index("date")
    raw.to_csv(path)
    logger.info(f"板块指数已缓存: {path} ({len(raw)}条)")
    return raw.loc[pd.Timestamp(start_date):pd.Timestamp(end_date)]


# ============================================================
# 3. 个股 -> 板块 映射
# ============================================================
def fetch_sector_mapping(use_cache: bool = True) -> pd.DataFrame:
    """获取 个股 -> 所属申万一级行业 映射

    遍历31个行业成分股, 汇总成 (symbol, name, sector_code, sector_name) 表。

    Returns:
        DataFrame: columns=['symbol','name','sector_code','sector_name']
        symbol 为6位代码 (如 "600519"), 与 stock_list.csv 一致
    """
    if use_cache:
        if os.path.exists(SECTOR_MAPPING_CACHE):
            logger.info(f"板块映射缓存命中: {SECTOR_MAPPING_CACHE}")
            cached = pd.read_csv(SECTOR_MAPPING_CACHE)
            # CSV 中 symbol 可能被读成 int, 统一转 str 并补齐6位
            cached["symbol"] = cached["symbol"].astype(str).str.zfill(6)
            return cached

    sectors = fetch_sector_list(use_cache=use_cache)
    rows = []
    total = len(sectors)
    for i, (_, row) in enumerate(sectors.iterrows()):
        # 申万行业代码形如 "801010.SI", 去掉 .SI 后缀传给接口
        code = str(row["sector_code"]).split(".")[0]
        name = row["sector_name"]
        try:
            cons = ak.index_component_sw(symbol=code)
            for _, c in cons.iterrows():
                stock_code = str(c["证券代码"]).zfill(6)
                stock_name = c["证券名称"]
                rows.append({
                    "symbol": stock_code,
                    "name": stock_name,
                    "sector_code": code,
                    "sector_name": name,
                })
            logger.info(f"[{i+1}/{total}] {name}({code}): {len(cons)} 只")
        except Exception as e:
            logger.warning(f"板块 {name}({code}) 成分股获取失败: {e}")
        time.sleep(0.2)

    df = pd.DataFrame(rows, columns=["symbol", "name", "sector_code", "sector_name"])
    df.to_csv(SECTOR_MAPPING_CACHE, index=False, encoding="utf-8-sig")
    logger.info(f"板块映射已缓存: {SECTOR_MAPPING_CACHE} ({len(df)}条)")
    return df


def get_stock_sectors(symbol: str,
                      mapping: pd.DataFrame | None = None) -> list:
    """查询某股票所属的所有申万一级行业

    Args:
        symbol: 6位股票代码, 如 "600519"
        mapping: 可选, 预先加载的映射表

    Returns:
        list[str]: 行业名称列表 (多数股票只属1个一级行业)
    """
    if mapping is None:
        mapping = fetch_sector_mapping()
    sub = mapping[mapping["symbol"] == str(symbol).zfill(6)]
    return sub["sector_name"].tolist()


def get_sector_stocks(sector_name: str,
                      mapping: pd.DataFrame | None = None) -> pd.DataFrame:
    """查询某申万行业包含的所有个股

    Returns:
        DataFrame: columns=['symbol','name']
    """
    if mapping is None:
        mapping = fetch_sector_mapping()
    sub = mapping[mapping["sector_name"] == sector_name]
    return sub[["symbol", "name"]].reset_index(drop=True)


# ============================================================
# 4. 批量下载
# ============================================================
def fetch_all_sector_index(start_date: str, end_date: str | None = None,
                           use_cache: bool = True):
    """批量下载所有申万一级行业指数日K"""
    if end_date is None:
        end_date = datetime.datetime.now().strftime("%Y%m%d")
    sectors = fetch_sector_list(use_cache=use_cache)
    success, fail = 0, 0
    for i, (_, row) in enumerate(sectors.iterrows()):
        code = str(row["sector_code"])
        name = row["sector_name"]
        try:
            fetch_sector_index(code, start_date, end_date, use_cache=use_cache)
            success += 1
        except Exception as e:
            logger.error(f"板块 {name}({code}) 指数下载失败: {e}")
            fail += 1
        time.sleep(0.3)
    logger.info(f"板块指数批量下载完成: 成功 {success}, 失败 {fail}")


def main():
    parser = argparse.ArgumentParser(description="申万板块指数与映射下载")
    parser.add_argument("--list", action="store_true", help="仅下载板块列表")
    parser.add_argument("--mapping", action="store_true", help="仅下载个股-板块映射")
    parser.add_argument("--index", action="store_true", help="仅下载全部板块指数日K")
    parser.add_argument("--start", default=DEFAULT_START, help="起始日期 YYYYMMDD")
    parser.add_argument("--end", default=None, help="结束日期 YYYYMMDD")
    args = parser.parse_args()

    end_date = args.end or datetime.datetime.now().strftime("%Y%m%d")

    logger.info("=== 步骤1: 申万一级行业列表 ===")
    sectors = fetch_sector_list(use_cache=False)
    logger.info(f"共 {len(sectors)} 个一级行业")
    if args.list:
        print(sectors[["sector_code", "sector_name", "成份个数"]].to_string())
        return

    if args.mapping or not args.index:
        logger.info("=== 步骤2: 个股-板块映射 ===")
        mapping = fetch_sector_mapping(use_cache=False)
        logger.info(f"映射总数: {len(mapping)} 条")
        if args.mapping:
            return

    if not args.mapping:
        logger.info("=== 步骤3: 全部板块指数日K ===")
        fetch_all_sector_index(args.start, end_date, use_cache=False)


if __name__ == "__main__":
    main()
