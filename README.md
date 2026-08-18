# AI 量化交易系统

基于 Python 的量化交易学习项目，包含数据获取、策略编写、回测引擎等模块。

## 项目结构

```
ai-Quantification/
├── config/             # 配置文件
│   └── settings.py     # 全局配置 (资金、手续费、路径等)
├── data/               # 数据模块
│   └── fetcher.py      # 行情数据获取 (akshare)
├── framework/          # 专业回测框架 (backtrader)
│   ├── strategies.py   # backtrader 版策略 (MA/MACD/海龟)
│   └── run.py          # 专业回测运行入口
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

使用专业回测框架 `framework/run.py`（基于 backtrader，输出收益率/夏普比率/最大回撤/胜率/盈亏比）：

```bash
# 默认: 海龟策略 + 平安银行(000001)
python framework/run.py

# 指定策略与股票
python framework/run.py ma 600519
python framework/run.py macd 000001

# 生成收益曲线图
python framework/run.py turtle 000001 --plot
```

程序会自动获取对应股票 2024 年的日线数据并回测，首次联网下载后缓存到 `data/`，之后离线可用。

### 3. 自定义策略

在 `framework/strategies.py` 中新增一个 `bt.Strategy` 子类，并在 `run.py` 的 `STRATS` 字典里注册即可：

```python
import backtrader as bt

class MyStrategy(bt.Strategy):
    params = (("period", 20),)

    def __init__(self):
        self.ma = bt.ind.SMA(period=self.p.period)

    def next(self):
        if not self.position and self.data.close[0] > self.ma[0]:
            self.buy()
        elif self.position and self.data.close[0] < self.ma[0]:
            self.close()
```

```python
# framework/run.py 中注册
STRATS = {..., "my": MyStrategy}
```

## 核心模块说明

| 模块 | 说明 |
|------|------|
| `data/fetcher.py` | 使用 akshare 获取 A 股历史行情数据 |
| `framework/strategies.py` | backtrader 版策略 (MA / MACD / 海龟)，定义交易逻辑 |
| `framework/run.py` | 专业回测运行入口，内置夏普/回撤/胜率等指标 |

## 学习路线建议

1. **数据获取** - 熟悉 `data/fetcher.py`，尝试获取不同股票的数据
2. **技术指标** - 在策略中添加 MACD、RSI、布林带等指标
3. **策略编写** - 基于 `bt.Strategy` 实现自己的策略
4. **回测优化** - 调整参数，观察夏普比率、最大回撤变化
5. **实盘对接** - 学习使用券商 API 进行模拟/实盘交易

## 数据源

- [akshare](https://akshare.akfamily.xyz/) - 免费 A 股数据 (无需注册)
- [tushare](https://tushare.pro/) - 需注册获取 token，数据更丰富
