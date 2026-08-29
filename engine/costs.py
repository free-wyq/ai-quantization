# -*- coding: utf-8 -*-
"""⑤ 执行层 — A股交易成本模型(全项目唯一定义)。

历史教训:成本模型曾在 run.py / batch_backtest.py / optimize.py 各硬编码一份,
三处漂移风险高。现在统一从这里 import。

改成本必须清楚口径:
- COST_FEES     佣金(万3,买卖均收) + 印花税(千1,仅卖出),买卖平均摊成 0.0008
- COST_SLIPPAGE 滑点 0.1%,按买卖方向各计一次
- INIT_CASH     初始资金
"""

COST_FEES = 0.0008      # 佣金+印花税 (买卖平均)
COST_SLIPPAGE = 0.001   # 滑点 0.1%
INIT_CASH = 100000.0    # 初始资金
