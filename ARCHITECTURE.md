# ARCHITECTURE.md — 量化系统总架构

> 本文件是项目的总蓝图:八层架构、目录映射、迁移路线。所有新功能先对照本图定位归属层,再动手。
> 设计讨论定稿于 2026-08-29(先整体后具体的架构评审)。

## 一、八层架构全景

```
┌─────────────────────────────────────────────────────────────────┐
│                     ⑦ 研究与迭代闭环 (横贯)                       │
│   归因诊断 → 假设 → 单变量A/B → 统计裁决 → 台账 → 回到归因          │
├─────────────────────────────────────────────────────────────────┤
│                     ⑥ 风控 (横贯, 三层嵌套)                       │
│   单笔风控(止损) → 组合风控(暴露上限) → 账户风控(熔断)              │
├─────────────────────────────────────────────────────────────────┤
│  ① 数据层                                                        │
│  行情采集 │ 基本面 │ 板块映射 │ 数据质量校验                        │
│       ▼                                                         │
│  数据缓存 (data/*.csv, 统一复权口径, 增量更新)                     │
│       ▼                                                         │
│  ② 因子层 (纯函数: 输入日K → 输出等长对齐 Series, 无状态)           │
│       ▼                                                         │
│  ③ 策略层 = 选股 × 择时 (只产信号意图, 不碰资金不碰撮合)             │
│       ▼                                                         │
│  ④ 组合层 (信号汇聚 → 目标持仓 → 资金分配 → 调仓计划)               │
│       ▼                                                         │
│  ⑤ 执行层 (回测撮合 ←→ 实盘/模拟盘, 同一套调仓计划格式)              │
├─────────────────────────────────────────────────────────────────┤
│  ⑧ 绩效评估 (横贯): 收益/风险/基准对照/分年度/滚动绩效              │
└─────────────────────────────────────────────────────────────────┘
```

### 各层职责边界(依赖方向: 只许上层依赖下层, 反向禁止)

| 层 | 职责 | 关键约束 |
|---|---|---|
| ① 数据 | 采集/清洗/存储 | 唯一允许有副作用的层;复权口径全项目唯一 |
| ② 因子 | 指标计算 | 纯函数、无状态、可单测;一个因子一个文件 |
| ③ 策略 | 信号意图 | **绝不自己跑回测**;返回固定5元组 |
| ④ 组合 | 资金分配 | 解决"多信号抢资金";相关性≠分散 |
| ⑤ 执行 | 撮合 | 回测撮合与实盘同构(涨跌停/T+1 待真实化) |
| ⑥ 风控 | 三层嵌套 | 单笔(有)→组合(无)→账户(无) |
| ⑦ 闭环 | 研究方法 | 五步闭环(见下);台账防重复实验 |
| ⑧ 评估 | 尺子 | 无基准对照的绩效不可信 |

## 二、目录结构(目录即架构)

```
ai-Quantification/
├── config/            # 全局配置 (BASE_DIR/DATA_DIR/LOG_DIR)
├── data/              # ① 数据层 (fetcher/sectors + csv缓存, gitignore)
├── factors/           # ② 因子层 (signal/cross_stock/flow/fundamental/market_state/...)
├── strategies/        # ③ 策略层 (base.py 模板方法 + midterm.py + custom/)
├── portfolio/         # ④ 组合层 (骨架, 待建设: allocator/constraints/rebalance)
├── engine/            # ⑤ 执行层
│   ├── backtest.py    #    回测入口(原 framework/run.py)
│   └── costs.py       #    ★ 成本模型唯一定义
├── risk/              # ⑥ 风控 (骨架, 待建设: per_trade/portfolio_risk/account)
├── research/          # ⑦ 研究闭环
│   ├── batch_backtest.py
│   ├── optimize.py
│   ├── attribution.py #    (待建: 逐笔归因)
│   └── EXPERIMENTS.md #    (待建: 实验台账)
├── evaluation/        # ⑧ 评估 (骨架, 待建设: benchmark 基准对照)
├── dashboard_server.py# 看板服务 (8000端口, 仓库根执行)
├── framework/results/ # 看板前端(dashboard.html 绝不改) + runs/ 产物
├── tests/             # 按层镜像新目录
└── ARCHITECTURE.md    # 本文件
```

**依赖规则**(import 方向):`engine/research/strategies` → `factors` → 无;`data` → `config`。`factors`/`strategies` 不许 import `engine`/`research`。

## 三、方法论:五步研究闭环(⑦层工作流)

用户定调(2026-08-29):**不许靠猜优化**。

1. **诊断先行** — 逐笔归因打标签(止损扫损/假信号/过山车/踏空),从病灶分布出发
2. **假设可证伪** — 每个实验先写"预期机制 + 受影响股票群",不许"试试看"
3. **单变量A/B** — 60股 / 20210101~20260818 / 同成本模型 / 一次只动一个开关
4. **统计裁决固化** — 中位数为主(均值被极端值绑架)、逐股改善比、样本外验证;标准定了不临场换
5. **实验台账** — 所有实验(含证伪)进 `research/EXPERIMENTS.md`,新实验先查表再开跑

## 四、迁移路线(三步,已完成)

- [x] **第一步**(c664993): `factors/`、`strategies/` 提升到仓库根,纯 git mv + import 改写
- [x] **第二步**(dce1168): 新建 `engine/ portfolio/ risk/ evaluation/ research/` 骨架;`engine/costs.py` 成本模型去重(终结三处硬编码)
- [x] **第三步**: `framework/run.py` → `engine/backtest.py`;`batch_backtest.py`/`optimize.py` → `research/`;`server_dashboard.py` → `dashboard_server.py`;CLAUDE.md/README/DESIGN.md 路径同步

**迁移不变量**:每次迁移后 `pytest` 17 全绿 + `engine/backtest.py midterm 300308` 夏普/回撤数值与迁移前一致(2.12 / 19.73%)。

## 五、待建设优先级

```
⑦ 两件套(research/attribution.py + EXPERIMENTS.md)   ← 下一步,先修尺子
⑧ evaluation/benchmark.py 沪深300基准对照             ← 评估可信的最小补丁
④ portfolio/ 最小版(等权N只 + 资金分配)
⑥ risk/ 组合暴露上限 + 账户熔断
⑤ 执行真实化(涨跌停不成交 / T+1)
```

约束:②单股择时(midterm)已到顶——参数杠杆试尽、再提升需新因子,勿在③层继续抠参数。
