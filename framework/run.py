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
import pandas as pd

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

    # 从 vectorbt 实际成交记录提取买卖点 (而非原始信号, 避免无持仓时的虚假卖出)
    buys, sells = [], []
    try:
        trades_df = pf.trades.records_readable
        for _, row in trades_df.iterrows():
            entry_ts = int(pd.Timestamp(row["Entry Timestamp"]).timestamp() * 1000)
            exit_ts = int(pd.Timestamp(row["Exit Timestamp"]).timestamp() * 1000)
            entry_price = round(float(row["Avg Entry Price"]), 2)
            exit_price = round(float(row["Avg Exit Price"]), 2)
            pnl = round(float(row["PnL"]), 2)
            ret = round(float(row["Return"]) * 100, 2)
            buys.append({"timestamp": entry_ts, "price": entry_price})
            sells.append({"timestamp": exit_ts, "price": exit_price,
                          "pnl": pnl, "return": ret})
    except Exception as e:
        print(f"  [警告] 提取成交记录失败: {e}")

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
    print(f"  看板服务:   framework/ 目录下执行  python serve_dashboard.py")
    print(f"  浏览器打开: http://localhost:8000/framework/results/dashboard.html")
    print(f"  (每次刷新页面都会自动加载最新回测记录)")


def _build_dashboard():
    """汇总 runs/ 目录下所有 JSON, 生成自包含看板 (klinecharts 离线, 无需服务器)。

    数据通过 runs/index.js 引入 (file:// 双击打开也能读目录内容),
    看板页面不再内嵌大段数据。
    """
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
    # 本地服务模式: 页面通过 fetch('runs/') 遍历目录、选中后懒加载对应 JSON,
    # 因此这里不再写 index.js, 数据完全由 runs/ 下的文件决定。
    # dashboard.html 视为固定模板: 仅当不存在时生成一次, 之后绝不覆盖。
    if not os.path.exists(DASHBOARD_PATH):
        open(DASHBOARD_PATH, "w", encoding="utf-8").write(DASHBOARD_TEMPLATE)


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
  .err { color:#ff7875; padding:20px; }
</style>
</head>
<body>
<header>
  <h1>量化回测看板</h1>
  <select id="sel"><option>加载中...</option></select>
  <span class="hint">本地服务模式 · 遍历 runs/ 目录 · 选中后懒加载</span>
</header>
<div class="wrap">
  <div id="chart"></div>
  <div class="panel" id="metrics"></div>
  <canvas id="equity"></canvas>
  <div id="err" class="err"></div>
</div>

<script>
let FILES = [];           // 文件名列表 (来自 fetch runs/ 目录)
let chart = null;

const sel = document.getElementById('sel');
const errBox = document.getElementById('err');

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
  if(!equity || !equity.length) return;
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

function render(data){
  if(chart) chart.remove();
  chart = klinecharts.init({ container: document.getElementById('chart') });
  chart.applyNewData(data.candles);
  data.buys.forEach(p=>{
    try { chart.createOverlay({ name:'circle', lock:true,
      points:[{timestamp:p.timestamp, price:p.price}],
      styles:{ circle:{ radius:9, color:'rgba(255,77,79,0.22)', border:{color:'#ff4d4f', size:2} } } }); } catch(e){}
    try { chart.createOverlay({ name:'text', lock:true,
      points:[{timestamp:p.timestamp, price:p.price}],
      styles:{ text:{ text:'B', color:'#fff', fontSize:12, fontWeight:'bold' } } }); } catch(e){}
  });
  data.sells.forEach(p=>{
    try { chart.createOverlay({ name:'circle', lock:true,
      points:[{timestamp:p.timestamp, price:p.price}],
      styles:{ circle:{ radius:9, color:'rgba(0,200,83,0.22)', border:{color:'#00c853', size:2} } } }); } catch(e){}
    try { chart.createOverlay({ name:'text', lock:true,
      points:[{timestamp:p.timestamp, price:p.price}],
      styles:{ text:{ text:'S', color:'#fff', fontSize:12, fontWeight:'bold' } } }); } catch(e){}
  });
  const m = data.metrics || {};
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
  drawEquity(data.equity);
}

// 选中某条历史 -> 懒加载对应 JSON
async function loadAndRender(idx){
  const name = FILES[idx];
  if(!name) return;
  try {
    const res = await fetch('runs/' + name);
    if(!res.ok) throw new Error('HTTP ' + res.status);
    render(await res.json());
  } catch(e){
    errBox.textContent = '加载失败: ' + name + ' (' + e.message + ')';
  }
}

sel.addEventListener('change', e => loadAndRender(+e.target.value));

// 启动: 遍历 runs/ 目录, 列出所有 .json (排除 index.js)
async function init(){
  try {
    const res = await fetch('runs/');
    if(!res.ok) throw new Error('HTTP ' + res.status);
    const html = await res.text();
    // 从目录列表页里提取 .json 文件名 (python http.server 的 <a href>)
    const names = [...html.matchAll(/href="([^"]+\.json)"/g)].map(m=>m[1])
                    .filter(n => n !== 'index.js');
    FILES = names;
    sel.innerHTML = '';
    names.forEach((n, i) => {
      const o = document.createElement('option');
      o.value = i; o.textContent = n.replace('.json',''); sel.appendChild(o);
    });
    if(names.length) loadAndRender(0);
    else errBox.textContent = 'runs/ 目录下没有 .json 文件';
  } catch(e){
    errBox.innerHTML = '无法遍历 runs/ 目录 (' + e.message + ')。<br>' +
      '请通过本地服务打开, 例如: <code>python -m http.server</code> 然后访问 ' +
      '<code>http://localhost:8000/framework/results/dashboard.html</code>';
  }
}
init();
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
    # 从 records_readable 提取 PnL 数组手动计算 (pf.trades.won/lost 在此版本不可用)
    try:
        pnls = pf.trades.records_readable["PnL"].values
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        win_rate = (len(wins) / n_trades * 100) if n_trades else 0.0
        sum_win = float(wins.sum()) if len(wins) else 0.0
        sum_loss = float(abs(losses.sum())) if len(losses) else 0.0
        profit_factor = (sum_win / sum_loss) if sum_loss != 0 else float("inf")
    except Exception:
        win_rate = 0.0
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
