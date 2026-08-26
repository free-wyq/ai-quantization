# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

A股量化交易学习项目:vectorbt 向量化回测 + akshare 行情 + klinecharts 离线看板。单股票回测为核心,演进方向见 `DESIGN.md` 第三部分(参数优化 → 风控 → 多股票组合 → 实盘)。

设计文档:`DESIGN.md` 三合一(第一部分经验档案 — 9策略×30股×5年回测结论;第二部分策略理论 — 信号分级/Kelly/ATR止损/七层闭环架构;第三部分演进路线)。

## 常用命令

```bash
# 回测(默认 midterm 策略 + 000001)
python framework/run.py
python framework/run.py midterm 000001
python framework/run.py midterm 000001 -p vol_min=1.5          # 覆盖参数
python framework/run.py midterm 000001 --sl 5 --tp 10            # 止损止盈(百分比)
python framework/run.py midterm 000001 --start 20250101 --end 20260818
python framework/run.py midterm 000001 --optimize               # 网格搜索+样本外验证
python framework/run.py --list                                  # 列所有策略

# 批量回测(策略×30股, train/test拆分检测过拟合)
python framework/batch_backtest.py --strategies midterm

# 看板服务(看 runs/ 下历史回测记录)
python framework/server_dashboard.py
# → http://localhost:8000/framework/results/dashboard.html

# 测试
pytest                         # 全部
pytest tests/test_base.py      # 单文件
pytest tests/test_base.py::TestTemplateMethod::test_run_injects_vr   # 单测
```

**日期格式注意**:`run.py`/`fetcher` 用 `YYYYMMDD`(如 `20250101`),不是 ISO。`run()` 函数签名里 `start_date`/`end_date` 是 `str` 默认 `"20260101"`/`"20260818"`,argparse `--start`/`--end` 默认值在 `run.py:228-229`。

## 架构(需读多个文件才能看懂的部分)

### 三层分离:策略只算信号,框架统一回测

```
data/fetcher.py        取数(本地CSV缓存优先→akshare新浪→东方财富兜底)
framework/strategies/   策略(只产出 entries/exits/indicators,不回测)
framework/run.py       回测入口(vectorbt.Portfolio.from_signals + 绩效 + 看板导出)
framework/batch_backtest.py  30股批量回测
```

**关键约束:策略绝不自己跑回测。** `midterm.py` docstring 明确"不重写回测器,本类只负责生成信号"。策略 `run(df)` 返回**固定 5 元组** `(entries, exits, indicators, size, reasons)`(`size` 可 None=等权满仓,`reasons` 可 None)。回测逻辑(成本/资金/止损止盈)统一在 `run.py` 的 `vbt.Portfolio.from_signals` 调用里(L141-153),`batch_backtest.py` 和 `optimize.py` 各自复刻一份简化版。

### 策略基类:模板方法模式

`framework/strategies/base.py` 的 `Strategy.run(df)` 是**模板骨架**(子类一般不重写):组装公共指标 → 调子类 `generate(df)` 钩子 → 返回固定 5 元组。

- **公共指标上提到基类**:主图均线系统(`MA_LINES = [(5,#faad14),(10,#13c2c2),(20,#722ed1),(60,#f5222d)]`,子类可覆盖类属性自定义)。子类的 `generate()` 返回的 `indicators` **只放特色指标**(如 midterm 的 ATRstop),不含 MA。看板成交量面板用内置 `VOL` 指标(柱+MA5/MA10),量比仅作入场过滤(`midterm._volume_ratio`),不再单独渲染量比线。
- **`SignalResult` dataclass**:`generate()` 的命名返回(entries/exits/indicators/reasons/size),替代脆弱的可变元组。
- 新策略:继承 `Strategy`,设 `name`/`label`/`params`,实现 `generate(df)`,返回 `SignalResult`;indicator values 用 `series_to_list()` 转(`.fillna(False)` 必须做,vectorbt 不吃 NaN)。

### 策略自动发现

`framework/strategies/__init__.py` 在包 import 时用 `pkgutil.walk_packages` 扫描所有子模块,收集 `Strategy` 子类(排除 `Strategy` 本身,且 `obj.__module__ == modname` 防止重复注册)填入 `STRATS` dict,key 是 `cls.name`。

- 内置策略直接放 `framework/strategies/*.py`(当前仅 `midterm.py`)
- **用户自定义策略放 `framework/strategies/custom/`**(子包不存在则创建),框架自动发现,**无需改任何框架代码**
- 新策略:继承 `Strategy`,设 `name`/`label`/`params`,实现 `generate(df)` 返回 `SignalResult`,indicator values 用 `series_to_list()` 转(`.fillna(False)` 必须做,vectorbt 不吃 NaN)

### A股成本模型(三处必须一致)

`COST_FEES=0.0008`(佣金万3+印花税千1,买卖平均)+ `COST_SLIPPAGE=0.001`(0.1%)。在 `run.py`、`batch_backtest.py`、`optimize.py` 各硬编码一份。**改成本必须三处同改**,目前是复制粘贴的重复,未抽公共(见 `DESIGN.md` 技术债务)。

### 看板数据流(不可改 dashboard.html 的约定)

`framework/results/dashboard.html` 是**手写静态文件,绝不修改**(用户明确诉求,见 `server_dashboard.py` 模块 docstring)。`server_dashboard.py` 在响应 dashboard.html 时,运行时扫描 `framework/results/runs/*.json`,注入 `window.__RUNS__` 列表(replace 掉 `<script src="runs/index.js">`)。所以:

- 每次回测 `run.py` 的 `_export_result()` 往 `runs/` 写一个独立 JSON(`{symbol}_{strategy}_{时间戳}.json`),含 candles/buys/sells/equity/indicators/metrics
- 看板刷新即重新扫描,**不重新生成 HTML**
- `file://` 打开无效,必须走 `server_dashboard.py`(8000端口)
- buys/sells 从 `pf.trades.records_readable` 提取真实成交,不是原始信号(避免无持仓时的虚假卖出)

### 中期复合策略(midterm) + 因子库

`framework/strategies/midterm.py` 是当前唯一内置策略,七层闭环架构见 `DESIGN.md` 第二部分。它依赖 `framework/factors/` 因子库(纯函数:输入日K,输出等长对齐 Series):

- `factors/market_state.py` — 个股广度/情绪/板块温度(闸门)
- `factors/sector_trend.py` — 板块强势(申万)
- `factors/leader.py` — 龙头筛选
- `factors/cross_stock.py` — 跨股票因子缓存入口(gate/sector_strong/leader)
- `factors/flow.py` — 北向/主力净流入(东财接口,WSL 必降级)
- `factors/fundamental.py` — PE/PB分位(百度)+ROE(TTM)+商誉(新浪)
- ⚠️ 退出逻辑(ATR跟踪止损/量价背离/ADX)**不在 factors/,已内联在 midterm.py**(`_atr`/`_build_exits` 等),`factors/exit.py` 早已删除。

midterm 的 `generate(df)` 组装个股信号层(第3层信号 + 第5层退出 + 可视化指标 + 买卖原因);跨股票/资金面/基本面三类因子**已接入但默认全关**(`use_*` 开关,取数失败自动降级跳过)。

> **架构债(待重构)**:三类选股因子当前通过 `entries = entries & xxx` 混在 `generate()` 末尾,违反「选股与回测分离」单一职责。设计见 `DESIGN.md` 第三部分「3.1 选股与回测分离」——静态选股迁入基类 `select()` 钩子、动态跨股票迁入独立 `MarketRegime` 模块、`generate()` 回归纯单股择时。后续重构方向,不立即动代码。

依赖 `data/sectors.py`(申万板块映射 + `sector_mapping.csv`/`stock_list.csv`)。

## 环境

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# 关键依赖:vectorbt>=0.25(回测)、akshare(行情)、ta(指标)、loguru、python-dotenv
```

- **WSL 环境**:Windows 侧的 `venv/`(python.exe)不可在 WSL 用,必须建 Linux venv。WSL python3 是 3.10。
- Tushare token(可选)放 `.env`:`TUSHARE_TOKEN=xxx`(`config/settings.py` 读,`.env.example` 有模板);默认走 akshare 无需 token。
- 行情优先读 `data/{symbol}_daily.csv` 缓存(已有31只),断网可用缓存做历史回测。

## 配置与约定

- 路径配置在 `config/settings.py`(`BASE_DIR`/`DATA_DIR`/`LOG_DIR`),日志用 loguru 按 `logs/quant_YYYYMMDD.log` 滚动。
- 初始资金 `100000`,满仓做多(`direction="longonly"`),`freq="d"` 日频年化。
- `.gitignore` 已忽略 `venv/`、`*.csv`(数据缓存)、`logs/`、`.env`、`framework/results/runs/`(回测产物)、`.claude/settings.local.json`。**不要把数据缓存或回测产物提交进 git。**
- git 身份:`wyq <ai-quantization@free-wyq>`(项目级,对齐其他项目 `项目名@free-wyq` 命名风格)。
