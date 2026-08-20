"""专业回测运行器 (vectorbt 向量化)

用法:
    python framework/run.py [策略] [股票代码]
    python framework/run.py turtle 000001
    python framework/run.py ma 000001
    python framework/run.py macd 000001

输出专业绩效报告: 收益率 / 夏普 / 最大回撤 / 胜率 / 盈亏比
每次运行会把结果写入 framework/results/, 并自动生成离线看板 dashboard.html
(用 klinecharts 画 K 线 + 买卖点, 浏览器打开下拉切换历史记录)
"""

import sys
import os
import json
import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import vectorbt as vbt

from data.fetcher import fetch_stock_history
from framework.strategies import STRATS

# ===== 结果看板相关路径 =====
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
RUNS_DIR = os.path.join(RESULTS_DIR, "runs")
DASHBOARD_PATH = os.path.join(RESULTS_DIR, "dashboard.html")
MAX_RUNS = 50  # 最多保留最近 50 次运行


def _export_result(strategy_key, symbol, df, entries, exits, pf, metrics):
    """把本次回测结果写成独立 JSON 文件 (按 代码_策略_时间 命名), 并重建看板。"""
    os.makedirs(RUNS_DIR, exist_ok=True)
    now = datetime.datetime.now()
    ts = now.strftime("%Y%m%d_%H%M%S")

    candles = []
    for i in range(len(df)):
        candles.append({
            "timestamp": int(df.index[i].timestamp() * 1000),
            "open": round(float(df["open"].iloc[i]), 2),
            "high": round(float(df["high"].iloc[i]), 2),
            "low": round(float(df["low"].iloc[i]), 2),
            "close": round(float(df["close"].iloc[i]), 2),
            "volume": float(df["volume"].iloc[i]),
        })

    buys, sells = [], []
    for i in range(len(df)):
        t = candles[i]["timestamp"]
        if bool(entries.iloc[i]):
            buys.append({"timestamp": t, "price": candles[i]["close"]})
        if bool(exits.iloc[i]):
            sells.append({"timestamp": t, "price": candles[i]["close"]})

    value = pf.value()
    equity = [{
        "timestamp": int(value.index[i].timestamp() * 1000),
        "value": round(float(value.iloc[i]), 2),
    } for i in range(len(value))]

    run_data = {
        "id": ts,
        "label": f"{strategy_key.upper()} {symbol} {now.strftime('%Y-%m-%d %H:%M')}",
        "file": f"{symbol}_{strategy_key}_{ts}.json",
        "strategy": strategy_key,
        "symbol": symbol,
        "metrics": metrics,
        "candles": candles,
        "buys": buys,
        "sells": sells,
        "equity": equity,
    }

    # 每次运行写一个独立文件, 文件名含 代码_策略_时间
    filename = run_data["file"]
    json.dump(run_data, open(os.path.join(RUNS_DIR, filename), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    _build_dashboard()
    print(f"  结果已存档: framework/results/runs/{filename}")
    print(f"  看板页面:   {DASHBOARD_PATH}  (浏览器打开, 下拉切换历史)")


def _build_dashboard():
    """汇总 runs/ 目录下所有 JSON, 生成自包含看板 (klinecharts 离线, 无需服务器)。"""
    runs = []
    if os.path.isdir(RUNS_DIR):
        for fn in os.listdir(RUNS_DIR):
            if fn.endswith(".json"):
                try:
                    runs.append(json.load(open(os.path.join(RUNS_DIR, fn),
                                               encoding="utf-8")))
                except Exception:
                    pass
    # 按 id(时间) 倒序, 最新的排最前, 并限制数量
    runs.sort(key=lambda r: r.get("id", ""), reverse=True)
    runs = runs[:MAX_RUNS]
    runs_json = json.dumps(runs, ensure_ascii=False)
    html = DASHBOARD_TEMPLATE.replace("/*__RUNS__*/", runs_json)
    open(DASHBOARD_PATH, "w", encoding="utf-8").write(html)


# 看板 HTML 模板
DASHBOARD_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>量化回测看板</title>
<script src="klinecharts.min.js"></script>
<style>
  * { box-sizing: border-box; }
  body { margin:0; font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
         background:#0f1115; color:#e6e6e6; }
  header { padding:12px 16px; background:#171a21; display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
  header h1 { font-size:16px; margin:0; color:#ffd666; }
  select { background:#22262f; color:#e6e6e6; border:1px solid #333; border-radius:6px;
           padding:6px 10px; font-size:14px; min-width:300px; }
  .wrap { padding:16px; }
  #chart { width:100%; height:520px; background:#171a21; border-radius:8px; }
  .panel { display:flex; flex-wrap:wrap; gap:10px; margin:14px 0; }
  .card { background:#171a21; border:1px solid #262b35; border-radius:8px; padding:10px 14px; min-width:130px; }
  .card .k { font-size:12px; color:#8b93a1; }
  .card .v { font-size:18px; font-weight:600; margin-top:2px; }
  .pos { color:#ff4d4f; } .neg { color:#00c853; }
  #equity { width:100%; height:160px; background:#171a21; border-radius:8px; margin-top:6px; }
  .hint { color:#8b93a1; font-size:12px; margin-left:auto; }
</style>
</head>
<body>
<header>
  <h1>量化回测看板</h1>
  <select id="sel"></select>
  <span class="hint">klinecharts 离线版 · 下拉切换历史</span>
</header>
<div class="wrap">
  <div id="chart"></div>
  <div class="panel" id="metrics"></div>
  <canvas id="equity"></canvas>
</div>

<script>
const RUNS = /*__RUNS__*/;
const sel = document.getElementById('sel');
RUNS.forEach((r, i) => {
  const o = document.createElement('option');
  o.value = i; o.textContent = r.label; sel.appendChild(o);
});

let chart = null;
function fmt(n, d=2){ return Number(n).toLocaleString('zh-CN',{minimumFractionDigits:d,maximumFractionDigits:d}); }
function cls(v){ return v>=0 ? 'pos' : 'neg'; }
function sign(v){ return v>=0 ? '+' : ''; }

function drawEquity(equity){
  const cv = document.getElementById('equity');
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth, h = cv.clientHeight;
  cv.width = w*dpr; cv.height = h*dpr;
  const ctx = cv.getContext('2d'); ctx.scale(dpr,dpr);
  ctx.clearRect(0,0,w,h);
  if(!equity.length) return;
  const vals = equity.map(e=>e.value);
  const min = Math.min(...vals), max = Math.max(...vals);
  const x = i => w * i/(vals.length-1 || 1);
  const y = v => h - 10 - (h-20) * (v-min)/((max-min)||1);
  ctx.strokeStyle = '#1f77b4'; ctx.lineWidth = 1.5; ctx.beginPath();
  vals.forEach((v,i)=> i? ctx.lineTo(x(i),y(v)) : ctx.moveTo(x(i),y(v)));
  ctx.stroke();
  ctx.fillStyle = '#8b93a1'; ctx.font = '12px sans-serif';
  ctx.fillText('账户权益  '+fmt(vals[vals.length-1]), 8, 16);
}

function render(idx){
  const r = RUNS[idx];
  // K线
  if(chart) chart.remove();
  chart = klinecharts.init({ container: document.getElementById('chart') });
  chart.applyNewData(r.candles);
  // 买卖点 (内置 circle + text 画线模型)
  r.buys.forEach(p=>{
    try { chart.createOverlay({ name:'circle', lock:true,
      points:[{timestamp:p.timestamp, price:p.price}],
      styles:{ circle:{ radius:9, color:'rgba(255,77,79,0.22)', border:{color:'#ff4d4f', size:2} } } }); } catch(e){}
    try { chart.createOverlay({ name:'text', lock:true,
      points:[{timestamp:p.timestamp, price:p.price}],
      styles:{ text:{ text:'B', color:'#fff', fontSize:12, fontWeight:'bold' } } }); } catch(e){}
  });
  r.sells.forEach(p=>{
    try { chart.createOverlay({ name:'circle', lock:true,
      points:[{timestamp:p.timestamp, price:p.price}],
      styles:{ circle:{ radius:9, color:'rgba(0,200,83,0.22)', border:{color:'#00c853', size:2} } } }); } catch(e){}
    try { chart.createOverlay({ name:'text', lock:true,
      points:[{timestamp:p.timestamp, price:p.price}],
      styles:{ text:{ text:'S', color:'#fff', fontSize:12, fontWeight:'bold' } } }); } catch(e){}
  });
  // 指标卡片
  const m = r.metrics;
  const cards = [
    ['策略收益率', sign(m.total_return)+fmt(m.total_return)+'%', cls(m.total_return)],
    ['基准收益率', fmt(m.benchmark)+'%', cls(m.benchmark)],
    ['超额收益', sign(m.excess)+fmt(m.excess)+'%', cls(m.excess)],
    ['夏普比率', fmt(m.sharpe), ''],
    ['最大回撤', fmt(m.max_dd)+'%', 'neg'],
    ['交易次数', m.n_trades, ''],
    ['胜率', fmt(m.win_rate)+'%', ''],
    ['盈亏比', m.profit_factor===Infinity?'∞':fmt(m.profit_factor), ''],
  ];
  document.getElementById('metrics').innerHTML = cards.map(c=>
    `<div class="card"><div class="k">${c[0]}</div><div class="v ${c[2]}">${c[1]}</div></div>`).join('');
  drawEquity(r.equity);
}

sel.addEventListener('change', e => render(+e.target.value));
render(0);
</script>
</body>
</html>
"""


def run(strategy_key: str, symbol: str, do_plot: bool = False):
    # 1. 准备数据 (复用现有 fetcher, 带本地缓存)
    df = fetch_stock_history(symbol, "20260301", "20260818").copy()
    df = df[["open", "high", "low", "close", "volume"]].dropna()

    # 2. 计算策略信号 (向量化, 一次性算完)
    entries, exits = STRATS[strategy_key](df)

    # 3. 向量化回测: 手续费万三, 初始资金10万, 满仓做多
    pf = vbt.Portfolio.from_signals(
        close=df["close"],
        entries=entries,
        exits=exits,
        direction="longonly",
        init_cash=100000.0,
        fees=0.0003,
    )

    # 4. 提取指标 (vbt 需要显式频率才能年化; 日频用 freq='d')
    init_cash = 100000.0
    final_value = float(pf.value().iloc[-1])
    total_return = float(pf.total_return()) * 100
    benchmark = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100

    sharpe = float(pf.sharpe_ratio(freq="d", risk_free=0.0))
    max_dd = abs(float(pf.max_drawdown(freq="d"))) * 100

    n_trades = int(pf.trades.count())
    try:
        win_rate = float(pf.trades.win_rate()) * 100 if n_trades else 0.0
        won_pnl = pf.trades.won.pnl
        lost_pnl = pf.trades.lost.pnl
        avg_win = float(won_pnl.mean()) if len(won_pnl) else 0.0
        avg_loss = float(lost_pnl.mean()) if len(lost_pnl) else 0.0
        sum_win = float(won_pnl.sum())
        sum_loss = float(lost_pnl.sum())
        profit_factor = (abs(sum_win / sum_loss) if sum_loss != 0 else float("inf"))
    except Exception:
        win_rate = avg_win = avg_loss = 0.0
        profit_factor = float("inf")

    metrics = {
        "total_return": round(total_return, 2),
        "benchmark": round(benchmark, 2),
        "excess": round(total_return - benchmark, 2),
        "sharpe": round(sharpe, 2),
        "max_dd": round(max_dd, 2),
        "n_trades": n_trades,
        "win_rate": round(win_rate, 2),
        "profit_factor": profit_factor,
    }

    # 5. 打印专业报告
    print("\n" + "=" * 56)
    print(f"  专业回测报告  [{strategy_key.upper()} | {symbol}]  (vectorbt)")
    print("=" * 56)
    print(f"  初始资金:      {init_cash:>14,.2f}")
    print(f"  最终资产:      {final_value:>14,.2f}")
    print(f"  策略收益率:    {total_return:>13.2f}%")
    print(f"  基准收益率:    {benchmark:>13.2f}%")
    print(f"  超额收益:      {total_return-benchmark:>13.2f}%")
    print("-" * 56)
    print(f"  夏普比率:      {sharpe:>14.2f}")
    print(f"  最大回撤:      {max_dd:>13.2f}%")
    print("-" * 56)
    print(f"  交易次数:      {n_trades:>14}")
    print(f"  胜率:          {win_rate:>13.2f}%")
    print(f"  平均盈利:      {avg_win:>14.2f}")
    print(f"  平均亏损:      {avg_loss:>14.2f}")
    print(f"  盈亏比:        {profit_factor:>14.2f}" if profit_factor != float("inf") else "  盈亏比:             ∞")
    print("=" * 56)

    # 6. 导出结果 + 生成离线看板
    if do_plot:
        _export_result(strategy_key, symbol, df, entries, exits, pf, metrics)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="专业回测运行器 (vectorbt)")
    parser.add_argument("strategy", nargs="?", default="ma",
                        choices=list(STRATS.keys()))
    parser.add_argument("symbol", nargs="?", default="000001")
    parser.add_argument("--plot", default=True, help="导出结果并生成离线看板")
    args = parser.parse_args()
    run(args.strategy, args.symbol, args.plot)
