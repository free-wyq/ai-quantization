# AI 量化交易系统

基于 Python + vectorbt 的量化交易学习项目，包含数据获取、策略编写、回测引擎、可视化看板。

## 项目结构

```
ai-Quantification/
├── config/                # 配置
│   └── settings.py        # 全局配置 (资金、手续费、路径等)
├── data/                  # 数据模块
│   └── fetcher.py         # 行情数据获取 (akshare + 本地缓存)
├── framework/             # 回测框架
│   ├── run.py             # 回测入口
│   ├── serve_dashboard.py # 看板服务
│   ├── strategies/        # 策略包 (自动发现)
│   │   ├── base.py        # 策略基类
│   │   ├── ma.py          # 双均线交叉
│   │   ├── macd.py        # MACD
│   │   ├── adx.py         # ADX 趋势强度
│   │   ├── rsi.py         # RSI 超买超卖
│   │   ├── obv.py         # OBV 能量潮
│   │   ├── regime.py      # 市场状态自适应
│   │   ├── turtle.py      # 唐奇安通道
│   │   └── custom/        # 用户自定义策略
│   └── results/           # 看板前端 + 回测结果
│       ├── dashboard.js   # klinecharts 可视化
│       ├── dashboard.css
│       └── index.html
├── requirements.txt
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

### 2. 运行回测

```bash
# 默认: regime 策略 + 平安银行(000001)
python framework/run.py

# 指定策略与股票
python framework/run.py ma 600519
python framework/run.py macd 000001
python framework/run.py regime 000001

# 查看可用策略
python framework/run.py --list
```

### 3. 查看看板

```bash
python framework/server_dashboard.py
# 浏览器打开 http://localhost:8080
```

看板展示 K 线 + 买卖标注 + 成交量 + 权益曲线 + 策略指标，支持十字光标联动。

### 4. 自定义策略

在 `framework/strategies/custom/` 下新建 `.py` 文件，继承 `Strategy` 类：

```python
from ..base import Strategy, series_to_list

class MyStrategy(Strategy):
    name = "my"
    label = "我的策略"
    params = {"period": 20}

    def run(self, df):
        close = df["close"]
        n = len(df)
        ma = close.rolling(self.params["period"]).mean()
        entries = close > ma
        exits = close < ma
        indicators = [
            {"name": "MA", "shortName": "MA20", "pane": "main",
             "color": "#ffa940", "values": series_to_list(ma, n)},
        ]
        return entries.fillna(False), exits.fillna(False), indicators
```

框架自动发现，无需修改任何框架代码。

## 策略一览

| 策略 | 类型 | 适合市场 | 说明 |
|------|------|---------|------|
| ma | 趋势 | 单边趋势 | 双均线交叉，快线上穿慢线买入 |
| macd | 趋势 | 单边趋势 | MACD 柱状图由负转正买入 |
| adx | 趋势 | 强趋势 | ADX>25 且 +DI/-DI 交叉 |
| rsi | 震荡 | 横盘震荡 | RSI 超卖买入、超买卖出 |
| obv | 量价 | 趋势确认 | OBV 上穿均线买入 |
| regime | 自适应 | 全市场 | ADX 判断市场状态，自动切换 MA/RSI |
| turtle | 趋势 | 强趋势 | 唐奇安通道突破 |

## 数据源

- [akshare](https://akshare.akfamily.xyz/) - 免费 A 股数据 (无需注册)
- 本地缓存，首次下载后离线可用
