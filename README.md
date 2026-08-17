# AI 量化交易系统

基于 Python 的量化交易学习项目，包含数据获取、策略编写、回测引擎等模块。

## 项目结构

```
ai-Quantification/
├── config/             # 配置文件
│   └── settings.py     # 全局配置 (资金、手续费、路径等)
├── data/               # 数据模块
│   └── fetcher.py      # 行情数据获取 (akshare)
├── strategy/           # 策略模块
│   ├── base.py         # 策略基类
│   └── ma_cross.py     # 双均线交叉策略
├── backtest/           # 回测模块
│   └── engine.py       # 简易回测引擎
├── utils/              # 工具模块
│   └── logger.py       # 日志配置
├── main.py             # 主入口
├── requirements.txt    # 项目依赖
├── .env.example        # 环境变量示例
└── README.md
```

## 快速开始

### 1. 安装依赖

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/Mac
pip install -r requirements.txt
```

### 2. 运行示例

```bash
python main.py
```

程序会自动获取平安银行(000001) 2024 年的日线数据，使用 5/20 双均线策略回测，输出收益情况。

### 3. 自定义策略

在 `strategy/` 目录下创建新策略，继承 `BaseStrategy`：

```python
from strategy.base import BaseStrategy
import pandas as pd

class MyStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(name="我的策略")

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["signal"] = 0
        # 你的策略逻辑...
        return df
```

## 核心模块说明

| 模块 | 说明 |
|------|------|
| `data/fetcher.py` | 使用 akshare 获取 A 股历史行情数据 |
| `strategy/base.py` | 策略基类，定义 `generate_signals` 接口 |
| `strategy/ma_cross.py` | 双均线交叉策略示例 |
| `backtest/engine.py` | 简易回测引擎，计算收益率、超额收益等 |

## 学习路线建议

1. **数据获取** - 熟悉 `data/fetcher.py`，尝试获取不同股票的数据
2. **技术指标** - 在策略中添加 MACD、RSI、布林带等指标
3. **策略编写** - 基于 `BaseStrategy` 实现自己的策略
4. **回测优化** - 扩展回测引擎，加入夏普比率、最大回撤等指标
5. **实盘对接** - 学习使用券商 API 进行模拟/实盘交易

## 数据源

- [akshare](https://akshare.akfamily.xyz/) - 免费 A 股数据 (无需注册)
- [tushare](https://tushare.pro/) - 需注册获取 token，数据更丰富
