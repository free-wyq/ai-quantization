const RUNS = window.__RUNS__ || [];
const sel = document.getElementById('sel');
const chartEl = document.getElementById('chart');
const metricsEl = document.getElementById('metrics');
const tradesBody = document.querySelector('#trades tbody');

RUNS.forEach((r, i) => {
  const o = document.createElement('option');
  o.value = i; o.textContent = r.label; sel.appendChild(o);
});

function fmt(n, d=2){ return Number(n).toLocaleString('zh-CN',{minimumFractionDigits:d,maximumFractionDigits:d}); }
function cls(v){ return v>=0 ? 'pos' : 'neg'; }
function sign(v){ return v>=0 ? '+' : ''; }
function fmtDate(ts){
  const d = new Date(ts);
  return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
}

/* ---- klinecharts v10 ---- */
const MAX_BARS = 150;
const SCROLL_OFFSET = 3;  // scrollToDataIndex 边界修正值

const chart = klinecharts.init('chart');
chart.setStyles({
  grid: { horizontal: { color: 'transparent' }, vertical: { color: 'transparent' } },
  crosshair: {
    horizontal: { text: { backgroundColor: '#1f77b4' } },
    vertical: { text: { backgroundColor: '#1f77b4' } }
  }
});

// 买卖点标注 (simpleAnnotation: 虚线+箭头+文字)
function addAnnotation(point, label, color) {
  try {
    chart.createOverlay({
      name: 'simpleAnnotation',
      lock: true,
      points: [{ timestamp: point.timestamp, value: point.price }],
      extendData: label,
      styles: { line: { color, style: 'dashed' }, text: { color, size: 13, weight: 'bold' } }
    });
  } catch(e) { console.warn('overlay:', e); }
}

// 权益曲线 (注册为 klinecharts 指标, 与 K 线/成交量自动联动十字光标)
let equityData = [];
klinecharts.registerIndicator({
  name: 'EQUITY',
  shortName: '账户权益',
  series: 'normal',
  precision: 2,
  figures: [{ key: 'equity', title: '权益: ', type: 'line' }],
  calc: dataList => dataList.map((d, i) => ({
    equity: (i < equityData.length && equityData[i] != null) ? equityData[i].value : null
  }))
});

// 策略曲线: 动态注册并绘制
let registeredStratInds = [];
function renderStrategyIndicators(r) {
  // 清除旧策略指标
  registeredStratInds.forEach(name => chart.removeIndicator({ name }));
  registeredStratInds = [];
  if (!r.indicators || !r.indicators.length) return;

  r.indicators.forEach(ind => {
    const figKey = ind.name;  // 每个指标用唯一 key, 避免同 pane 冲突
    const figType = ind.type || 'line';
    const figStyle = ind.lineStyle || 'solid';
    const figWidth = ind.lineWidth || 1;
    klinecharts.registerIndicator({
      name: ind.name,
      shortName: ind.shortName,
      series: ind.pane === 'main' ? 'price' : 'normal',
      precision: 4,
      figures: [{ key: figKey, title: ind.shortName + ': ', type: figType }],
      calc: dataList => dataList.map((d, i) => ({
        [figKey]: (i < ind.values.length && ind.values[i] != null) ? ind.values[i] : null
      }))
    });
    const paneId = ind.pane === 'main' ? 'candle_pane' : ('strat_' + (ind.paneId || ind.name));
    chart.createIndicator({
      name: ind.name, paneId,
      styles: { lines: [{ color: ind.color, style: figStyle, size: figWidth }] }
    });
    registeredStratInds.push(ind.name);
  });
}

function render(idx){
  const r = RUNS[idx];
  if (!r) return;

  chart.removeOverlay();
  chart.removeIndicator({ name: 'VOL' });
  chart.removeIndicator({ name: 'EQUITY' });

  // 权益曲线 (klinecharts pane, 自动联动十字光标)
  equityData = r.equity || [];
  chart.createIndicator({
    name: 'EQUITY', paneId: 'equity_pane',
    styles: { lines: [{ color: '#1f77b4', style: 'solid', size: 1.5 }] }
  });

  // v10: setSymbol + setPeriod + setDataLoader 三者就绪后触发 getBars
  chart.setSymbol({ ticker: r.symbol });
  chart.setPeriod({ type: 'day', span: 1 });
  chart.setDataLoader({
    getBars: ({ callback }) => {
      callback(r.candles, false);
      // 设置柱宽并让首根K线显示在最左侧
      setTimeout(() => {
        const w = chartEl.clientWidth;
        const visibleBars = Math.min(r.candles.length, MAX_BARS);
        const barSpace = Math.max(4, Math.min(50, Math.floor(w / visibleBars)));
        chart.setBarSpace(barSpace);
        // scrollToDataIndex(n) 将第n根放到右侧边缘，滚动到 fitBars-offset 使首根在左侧
        const fitBars = Math.floor(w / barSpace);
        chart.scrollToDataIndex(Math.min(r.candles.length - 1, fitBars - SCROLL_OFFSET));
      }, 50);
    }
  });

  chart.createIndicator({ name: 'VOL', paneId: 'vol_pane' });

  // 策略曲线 (MA均线/唐奇安通道/MACD等, 由策略函数动态提供)
  renderStrategyIndicators(r);

  // 买卖点标注
  r.buys.forEach(p => addAnnotation(p, 'B', '#ff4d4f'));
  r.sells.forEach(p => addAnnotation(p, 'S', '#00c853'));

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
  metricsEl.innerHTML = cards.map(c =>
    `<div class="card"><div class="k">${c[0]}</div><div class="v ${c[2]}">${c[1]}</div></div>`).join('');

  // 交易明细表
  const trades = [];
  r.buys.forEach((b, i) => {
    const s = r.sells[i];
    trades.push({type:'买入', date:b.timestamp, price:b.price, pnl:null});
    if (s) trades.push({type:'卖出', date:s.timestamp, price:s.price, pnl:s.return});
  });
  tradesBody.innerHTML = trades.map(t => {
    const tagCls = t.type==='买入' ? 'tag-buy' : 'tag-sell';
    const pnlStr = t.pnl===null ? '—' : (t.pnl>=0?'+':'')+fmt(t.pnl)+'%';
    const pnlCls = t.pnl===null ? '' : (t.pnl>=0?'pnl-pos':'pnl-neg');
    return `<tr><td class="${tagCls}">${t.type}</td><td>${fmtDate(t.date)}</td><td>${fmt(t.price)}</td><td class="${pnlCls}">${pnlStr}</td></tr>`;
  }).join('');
}

sel.addEventListener('change', e => render(+e.target.value));
render(0);
