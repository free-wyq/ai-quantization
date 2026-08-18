"""项目配置文件"""

import os
from dotenv import load_dotenv

load_dotenv()

# ===== 路径配置 =====
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "logs")

# 确保目录存在
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# ===== 数据源配置 =====
# Tushare token (在 .env 文件中配置: TUSHARE_TOKEN=your_token)
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")

# ===== 日志配置 =====
LOG_CONFIG = {
    "level": "DEBUG",
    "format": "{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
    "file": os.path.join(LOG_DIR, "quant_{time:YYYYMMDD}.log"),
    "rotation": "1 day",
    "retention": "30 days",
}
