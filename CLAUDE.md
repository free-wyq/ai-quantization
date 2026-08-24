# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

A股量化交易学习项目:vectorbt 向量化回测 + akshare 行情 + klinecharts 离线看板。单股票回测为核心,演进方向见 `ROADMAP.md`(参数优化 → 风控 → 多股票组合 → 实盘)。

设计文档:`EXPERIENCE.md`(9策略×30股×5年回测的实战经验总结,策略设计的事实来源)、`STRATEGY_GUIDE.md`(信号分级/Kelly/ATR止损的理论)。

## 常用命令

```bash
# 回测(默认 midterm 策略 + 000001)
python framework/run.py
python framework/run.py macd 000001
python framework/run.py ma 000001 -p fast=10 slow=30          # 覆盖参数
python framework/run.py regime 000001 --sl 5 --tp 10          # 止损止盈(百分比)
python framework/run.py ma 000001 --start 20250101 --end 20260818
python framework/run.py ma 000001 --optimize                 # 网格搜索+样本外验证
python framework/run.py --list                                # 列所有策略

# 批量回测(7策略×30股, train/test拆分检测过拟合)
python framework/batch_backtest.py --strategies ma rsi

# 看板服务(看 runs/ 下历史回测记录)
python framework/server_dashboard.py
# → http://localhost:8000/framework/results/dashboard.html

# 测试
pytest                         # 全部
pytest tests/test_ma.py        # 单文件
pytest tests/test_ma.py::test_golden_cross   # 单测
```

**日期格式注意**:`run.py`/`fetcher` 用 `YYYYMMDD`(如 `20260101`),不是 ISO。`run()` 函数签名里 `start_date`/`end_date` 是 `str` 默认 `"20260101"`/`"20260818"`,argparse `--start`/`--end` 默认值也在 `run.py:226-227`。

## 架构(需读多个文件才能看懂的部分)

### 三层分离:策略只算信号,框架统一回测

```
data/fetcher.py        取数(本地CSV缓存优先→akshare新浪→东方财富兜底)
framework/strategies/   策略(只产出 entries/exits/indicators,不回测)
framework/run.py       回测入口(vectorbt.Portfolio.from_signals + 绩效 + 看板导出)
framework/batch_backtest.py  30股批量回测
```

**关键约束:策略绝不自己跑回测。** `midterm.py:4` 明确写"不重写回测器,本类只负责生成信号"。策略 `run(df)` 返回 `(entries, exits, indicators)` 或加 `size`(仓位比例 Series)或加 `reasons`(dict,含 `buy_reasons`/`sell_reasons` 给看板标注)。回测逻辑(成本/资金/止损止盈)统一在 `run.py` 的 `vbt.Portfolio.from_signals` 调用里(L139-151),`batch_backtest.py` 和 `optimize.py` 各自复刻一份简化版。

### 策略自动发现

`framework/strategies/__init__.py` 在包 import 时用 `pkgutil.walk_packages` 扫描所有子模块,收集 `Strategy` 子类(排除 `Strategy` 本身,且 `obj.__module__ == modname` 防止重复注册)填入 `STRATS` dict,key 是 `cls.name`。

- 内置策略直接放 `framework/strategies/*.py`
- **用户自定义策略放 `framework/strategies/custom/`**(已有 `my_multi_factor.py`),框架自动发现,**无需改任何框架代码**
- 新策略:继承 `Strategy`,设 `name`/`label`/`params`,实现 `run(df)`,返回值用 `series_to_list()` 转 indicator values(`.fillna(False)` 必须做,vectorbt 不吃 NaN)

### A股成本模型(三处必须一致)

`COST_FEES=0.0008`(佣金万3+印花税千1,买卖平均)+ `COST_SLIPPAGE=0.001`(0.1%)。在 `run.py`、`batch_backtest.py`、`optimize.py` 各硬编码一份。**改成本必须三处同改**,目前是复制粘贴的重复,未抽公共。

### 看板数据流(不可改 dashboard.html 的约定)

`framework/results/dashboard.html` 是**手写静态文件,绝不修改**(用户明确诉求,见 `server_dashboard.py:7`)。`server_dashboard.py` 在响应 dashboard.html 时,运行时扫描 `framework/results/runs/*.json`,注入 `window.__RUNS__` 列表(replace 掉 `<script src="runs/index.js">`)。所以:

- 每次回测 `run.py` 的 `_export_result()` 往 `runs/` 写一个独立 JSON(`{symbol}_{strategy}_{时间戳}.json`),含 candles/buys/sells/equity/indicators/metrics
- 看板刷新即重新扫描,**不重新生成 HTML**
- `file://` 打开无效,必须走 `server_dashboard.py`(8000端口)
- buys/sells 从 `pf.trades.records_readable` 提取真实成交,不是原始信号(避免无持仓时的虚假卖出)

### 中期复合策略(midterm)的七层 + 因子库

`framework/strategies/midterm.py` 是当前主推策略,七层闭环对应 `EXPERIENCE.md` 第十五章。它依赖 `framework/factors/` 因子库(纯函数:输入日K,输出等长对齐 Series):

- `factors/signal.py` — MACD/周KDJ/量比/MA60
- `factors/exit.py` — ATR跟踪止损/量价背离/ADX
- `factors/market_state.py` — 个股广度/情绪/板块温度(闸门)
- `factors/sector_trend.py` — 板块强势(申万)
- `factors/leader.py` — 龙头筛选

跨股票状态(广度/板块/龙头)在 midterm 模块级缓存(`_STATE` dict,按区间+阈值 key),避免每只股票重算全市场。依赖 `data/sectors.py`(申万板块映射 + `sector_mapping.csv`/`stock_list.csv`)。

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
