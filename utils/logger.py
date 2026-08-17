"""日志配置模块"""

from loguru import logger
from config.settings import LOG_CONFIG


def setup_logger():
    """配置 loguru 日志"""
    logger.remove()  # 移除默认配置
    logger.add(
        sink=lambda msg: print(msg, end=""),
        level=LOG_CONFIG["level"],
        format=LOG_CONFIG["format"],
    )
    logger.add(
        sink=LOG_CONFIG["file"],
        level=LOG_CONFIG["level"],
        format=LOG_CONFIG["format"],
        rotation=LOG_CONFIG["rotation"],
        retention=LOG_CONFIG["retention"],
        encoding="utf-8",
    )
    return logger


# 全局 logger 实例
log = setup_logger()
