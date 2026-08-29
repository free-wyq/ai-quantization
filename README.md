# AI 量化交易系统

基于 Python + vectorbt 的量化交易学习项目，包含数据获取、策略编写、回测引擎、可视化看板。

## 项目结构

```
ai-Quantification/
├── config/                # 配置
│   └── settings.py        # 全局配置 (资金、手续费、路径等)
├── data/                  # 数据模块
│   ├── fetcher.py         # 行情数据获取 (akshare + 本地缓存)
│   └── sectors.py         # 申万行业指数 + 板块/股票映射
├── strategies/            # ③ 策略层 (只产信号, 自动发现)
│   ├── base.py            # 策略基类 (模板方法: run 骨架 + generate 钩子)
│   └── midterm.py         # 中期复合策略 (信号 + 退出)
├── factors/               # ② 因子库 (纯函数: 日K 进, 等长对齐 Series 出)
│   ├── market_state.py    # 个股广度 / 板块温度 / 情绪 (库内备用, 暂未接入)
│   ├── sector_trend.py    # 板块趋势 (库内备用, 暂未接入)
│   ├── leader.py          # 龙头筛选 (库内备用, 暂未接入)
│   ├── cross_stock.py     # 跨股票因子缓存入口
│   ├── flow.py            # 资金面 (北向/主力, 默认关)
│   └── fundamental.py     # 基本面排雷 (默认关)
├── engine/                # ⑤ 执行层 (回测撮合)
│   ├── backtest.py        # 回测入口 (单股 + 看板导出)
│   └── costs.py           # 成本模型唯一定义
├── research/              # ⑦ 研究闭环
│   ├── batch_backtest.py  # 30股批量回测 (train/test 拆分)
│   └── optimize.py        # 参数网格搜索 + 样本外验证
├── portfolio/ risk/ evaluation/  # ④⑥⑧ 层骨架 (待建设)
├── dashboard_server.py    # 看板服务 (动态注入 runs/, 端口 8000)
├── framework/results/     # 看板前端 + 回测结果 (产物目录)
│       ├── dashboard.html # 看板 (手写静态, 绝不修改)
│       ├── dashboard.js   # klinecharts 可视化
│       ├── dashboard.css
│       └── klinecharts.min.js
├── tests/                 # pytest (conftest 构造模拟K线, 不依赖网络)
├── DESIGN.md              # 设计文档 (经验档案 + 策略理论 + 演进路线)
├── CLAUDE.md              # Claude Code 指引
└── requirements.txt
```

## 快速开始

### 1. 安装依赖

```bash
python -m venv venv && source venv/bin/activate     # Linux/Mac
# venv\Scripts\activate                              # Windows
pip install -r requirements.txt
# 关键依赖: vectorbt>=0.25 (回测)、akshare (行情)、ta (指标)、loguru、python-dotenv
```

> **WSL 注意**: Windows 侧的 `venv/`(python.exe) 不可在 WSL 用，必须建 Linux venv (python3 是 3.10)。

### 2. 运行回测

```bash
# 默认: midterm 策略 + 平安银行(000001)
python engine/backtest.py

# 指定策略与股票 (目前内置仅 midterm)
python engine/backtest.py midterm 000001
python engine/backtest.py midterm 000001 -p vol_min=1.5      # 覆盖参数
python engine/backtest.py midterm 000001 --sl 5 --tp 10       # 止损止盈(百分比)
python engine/backtest.py midterm 000001 --start 20250101 --end 20260818
python engine/backtest.py midterm 000001 --optimize          # 网格搜索 + 样本外验证
python engine/backtest.py --list                             # 列所有策略
```

### 3. 查看看板

```bash
python dashboard_server.py
# 浏览器打开 http://localhost:8000/framework/results/dashboard.html
```

看板展示 K 线 + MA 均线 + 买卖标注 + 成交量(含MA5/MA10均线) + 权益曲线 + 策略指标，
支持十字光标联动。每次回测往 `framework/results/runs/` 写独立 JSON，刷新页面即重新扫描，
**不重新生成 HTML** (`file://` 打开无效，必须走 `server_dashboard.py`)。

### 4. 自定义策略

在 `strategies/` (或其 `custom/` 子包) 下新建 `.py` 文件，继承 `Strategy`，
实现 `generate()` 钩子返回 `SignalResult`：

```python
from framework.strategies.base import Strategy, SignalResult, series_to_list

class MyStrategy(Strategy):
    name = "my"
    label = "我的策略"
    params = {"period": 20}

    def generate(self, df) -> SignalResult:
        close = df["close"]
        ma = close.rolling(self.params["period"]).mean()
        entries = close > ma
        exits = close < ma
        # 特色指标只放策略自己的; MA系统由基类 run() 统一组装
        indicators = [
            {"name": "MA20", "shortName": "MA20", "pane": "main", "paneId": "main",
             "color": "#ffa940", "values": series_to_list(ma, len(df))},
        ]
        return SignalResult(entries.fillna(False), exits.fillna(False), indicators)
```

框架自动发现 (无需改任何框架代码)。基类 `run()` 是模板骨架，自动注入公共指标
(MA5/10/20/60 主图均线) 并调子类 `generate()`，返回固定 5 元组
`(entries, exits, indicators, size, reasons)` 供回测引擎消费。

## 策略一览

| 策略 | 类型 | 说明 |
|------|------|------|
| midterm | 中期趋势 | 周KDJ + MACD + MA + 量比 共振入场，ATR跟踪止损 + 量价背离退出 |

## 数据源

- [akshare](https://akshare.akfamily.xyz/) - 免费 A 股数据 (无需注册)
- 本地 CSV 缓存 (`data/{symbol}_daily.csv`)，首次下载后离线可用
- 申万行业指数 + 板块/股票映射 (`data/sectors.py` + `sector_mapping.csv`/`stock_list.csv`)
