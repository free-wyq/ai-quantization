"""批量下载股票行情数据

筛选范围: 上证 + 创业板 + 深证, 市值 > 100亿
数据来源: 新浪财经 (akshare stock_zh_a_daily)
"""

import time
import datetime
from loguru import logger

from config.settings import DATA_DIR
from data.fetcher import fetch_stock_history

# 市值前 30 只股票 (上证 + 创业板 + 深证, 2025 年市值排名)
STOCK_LIST = [
    # 上证主板
    ("600519", "贵州茅台"),
    ("601398", "工商银行"),
    ("601288", "农业银行"),
    ("601988", "中国银行"),
    ("601628", "中国人寿"),
    ("601857", "中国石油"),
    ("600036", "招商银行"),
    ("601318", "中国平安"),
    ("601166", "兴业银行"),
    ("600028", "中国石化"),
    ("601088", "中国神华"),
    ("600030", "中信证券"),
    ("601688", "华泰证券"),
    ("600276", "恒瑞医药"),
    ("600900", "长江电力"),
    ("601668", "中国建筑"),
    ("600887", "伊利股份"),
    ("600000", "浦发银行"),
    ("600048", "保利发展"),
    # 创业板
    ("300750", "宁德时代"),
    ("300059", "东方财富"),
    ("300760", "迈瑞医疗"),
    ("300015", "爱尔眼科"),
    ("300124", "汇川技术"),
    # 深证主板 / 中小板
    ("000001", "平安银行"),
    ("000858", "五粮液"),
    ("000333", "美的集团"),
    ("002594", "比亚迪"),
    ("000651", "格力电器"),
    ("002475", "立讯精密"),
]

START_DATE = "20210101"


def main():
    end_date = datetime.datetime.now().strftime("%Y%m%d")
    logger.info(f"批量下载: {START_DATE} ~ {end_date}, 共 {len(STOCK_LIST)} 只股票")

    # 保存股票列表
    import csv
    list_path = f"{DATA_DIR}/stock_list.csv"
    with open(list_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["symbol", "name"])
        for symbol, name in STOCK_LIST:
            writer.writerow([symbol, name])
    logger.info(f"股票列表已保存: {list_path}")

    # 逐只下载
    success, fail = 0, 0
    for i, (symbol, name) in enumerate(STOCK_LIST):
        logger.info(f"[{i+1}/{len(STOCK_LIST)}] {symbol} {name}")
        try:
            df = fetch_stock_history(
                symbol=symbol,
                start_date=START_DATE,
                end_date=end_date,
                use_cache=False,
                name=name,
            )
            logger.info(f"  -> {len(df)} 条, 列: {list(df.columns)}")
            success += 1
        except Exception as e:
            logger.error(f"  -> 失败: {e}")
            fail += 1

        time.sleep(0.5)

    logger.info(f"完成: 成功 {success}, 失败 {fail}")


if __name__ == "__main__":
    main()
