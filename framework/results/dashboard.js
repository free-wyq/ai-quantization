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
  candle: {
    bar: {
      upColor: '#ef5350',        // 涨: 红
      downColor: '#26a69a',      // 跌: 绿
      noChangeColor: '#888888',
      upBorderColor: '#ef5350',
      downBorderColor: '#26a69a',
      noChangeBorderColor: '#888888',
      upWickColor: '#ef5350',
      downWickColor: '#26a69a',
      noChangeWickColor: '#888888'
    }
  },
  indicator: {
    bars: [{
      upColor: '#ef5350',        // 涨: 红
      downColor: '#26a69a',      // 跌: 绿
      noChangeColor: '#888888'
    }]
  },
  crosshair: {
    horizontal: { text: { backgroundColor: '#1f77b4' } },
    vertical: { text: { backgroundColor: '#1f77b4' } }
  }
});

// 买卖点标注 (simpleAnnotation: 虚线+箭头+文字)
function addAnnotation(point, label, color) {
  try {
    const text = point.reason ? `${label} ${point.reason}` : label;
    chart.createOverlay({
      name: 'simpleAnnotation',
      lock: true,
      points: [{ timestamp: point.timestamp, value: point.price }],
      extendData: text,
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

// 自定义成交量+量比融合指标 (复制内置VOL柱子逻辑 + 量比线按均量缩放)
let _vrValues = [];
klinecharts.registerIndicator({
  name: 'VOL_1',
  shortName: 'VOL/量比',
  series: 'volume',
  precision: 0,
  figures: [
    { key: 'vol', title: '成交量: ', type: 'bar' },
    { key: 'vr',  title: '量比: ',  type: 'line' },
  ],
  calc: dataList => {
    const n = dataList.length;
    const maPeriod = 20;
    // 计算20日均量用于缩放量比线
    const volMA = [];
    for (let i = 0; i < n; i++) {
      const start = Math.max(0, i - maPeriod + 1);
      const slice = [];
      for (let j = start; j <= i; j++) slice.push(dataList[j].volume || 0);
      volMA.push(slice.reduce((a, b) => a + b, 0) / slice.length);
    }
    return dataList.map((d, i) => {
      const vol = d.volume || null;
      const up = d.close >= d.open;
      const vrRaw = (i < _vrValues.length && _vrValues[i] != null) ? _vrValues[i] : null;
      const vrScaled = (vrRaw != null && volMA[i] > 0) ? vrRaw * volMA[i] : null;
      // 柱子按K线涨跌着色: 涨红跌绿
      return {
        vol: { value: vol, color: up ? '#ef5350' : '#26a69a' },
        vr: vrScaled
      };
    });
  }
});

// 策略曲线: 按 paneId 分组, 同 pane 的多条线合并为一个指标的多 figures
let registeredStratInds = [];
function renderStrategyIndicators(r) {
  // 清除旧策略指标
  registeredStratInds.forEach(name => chart.removeIndicator({ name }));
  registeredStratInds = [];
  if (!r.indicators || !r.indicators.length) return;

  // 过滤掉 VR (已单独渲染到 vr_pane)
  const filtered = r.indicators.filter(i => i.name !== 'VR');

  // 按 paneId 分组 (main 单独处理)
  const groups = {};
  filtered.forEach(ind => {
    const gid = ind.pane === 'main' ? 'candle_pane' : (ind.paneId || ind.name);
    if (!groups[gid]) groups[gid] = [];
    groups[gid].push(ind);
  });

  Object.entries(groups).forEach(([paneKey, inds]) => {
    const indName = 'STRAT_' + paneKey;
    const isMain = inds[0].pane === 'main';
    const paneId = isMain ? 'candle_pane' : ('strat_' + paneKey);

    // 构建 figures: 每条线一个 figure
    const figures = inds.map(ind => ({
      key: ind.name,
      title: ind.shortName + ': ',
      type: ind.type || 'line'
    }));

    // 构建 lines 样式: 每条线对应一个颜色
    const lines = inds.map(ind => ({
      color: ind.color,
      style: ind.lineStyle || 'solid',
      size: ind.lineWidth || 1
    }));

    // 收集各指标的 values, 供 calc 闭包引用
    const valsMap = {};
    inds.forEach(ind => { valsMap[ind.name] = ind.values; });

    klinecharts.registerIndicator({
      name: indName,
      shortName: inds.map(i => i.shortName).join(' / '),
      series: isMain ? 'price' : 'normal',
      precision: 4,
      figures: figures,
      calc: dataList => dataList.map((d, i) => {
        const row = {};
        inds.forEach(ind => {
          const v = (i < valsMap[ind.name].length && valsMap[ind.name][i] != null)
            ? valsMap[ind.name][i] : null;
          row[ind.name] = v;
        });
        return row;
      })
    });

    chart.createIndicator({ name: indName, paneId, styles: { lines } });
    registeredStratInds.push(indName);
  });
}

function render(idx){
  const r = RUNS[idx];
  if (!r) return;

  chart.removeOverlay();
  chart.removeIndicator({ name: 'VOL_1' });
  chart.removeIndicator({ name: 'EQUITY' });

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
        const fitBars = Math.floor(w / barSpace);
        chart.scrollToDataIndex(Math.min(r.candles.length - 1, fitBars - SCROLL_OFFSET));

        // 四层布局: 主图45% | 成交量+量比22% | 策略18% | 权益15%
        const totalH = chartEl.clientHeight;
        const layout = [
          { id: 'candle_pane', height: Math.floor(totalH * 0.45) },
          { id: 'vol_pane',    height: Math.floor(totalH * 0.22) },
          { id: 'strat_strat', height: Math.floor(totalH * 0.18) },
          { id: 'equity_pane', height: Math.floor(totalH * 0.15) },
        ];
        layout.forEach(l => {
          try { chart.setPaneOptions({ id: l.id, height: l.height }); } catch(e) {}
        });
      }, 50);
    }
  });

  // 先提取 VR 值供 VR_LINE 指标使用
  const vrInd = (r.indicators || []).find(i => i.name === 'VR');
  _vrValues = vrInd ? vrInd.values : [];

  // 自定义 VOL_1: 成交量柱 + 量比线融合 (柱子按K线涨跌着色)
  chart.createIndicator({
    name: 'VOL_1', paneId: 'vol_pane',
    styles: {
      bars: [{
        upColor: '#ef5350',
        downColor: '#26a69a',
        noChangeColor: '#888888'
      }],
      lines: [{ color: '#52c41a', style: 'solid', size: 1 }],
    }
  });

  // 策略曲线 (MA均线/MACD等, 由策略函数动态提供)
  renderStrategyIndicators(r);

  // 权益曲线 (放在所有副图最下方, 紧邻策略收益)
  equityData = r.equity || [];
  chart.createIndicator({
    name: 'EQUITY', paneId: 'equity_pane',
    styles: { lines: [{ color: '#1f77b4', style: 'solid', size: 1.5 }] }
  });

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
    trades.push({type:'买入', date:b.timestamp, price:b.price, pnl:null, reason:b.reason||''});
    if (s) trades.push({type:'卖出', date:s.timestamp, price:s.price, pnl:s.return, reason:s.reason||''});
  });
  tradesBody.innerHTML = trades.map(t => {
    const tagCls = t.type==='买入' ? 'tag-buy' : 'tag-sell';
    const pnlStr = t.pnl===null ? '—' : (t.pnl>=0?'+':'')+fmt(t.pnl)+'%';
    const pnlCls = t.pnl===null ? '' : (t.pnl>=0?'pnl-pos':'pnl-neg');
    return `<tr><td class="${tagCls}">${t.type}</td><td>${fmtDate(t.date)}</td><td>${fmt(t.price)}</td><td class="${pnlCls}">${pnlStr}</td><td class="trade-reason">${t.reason}</td></tr>`;
  }).join('');
}

sel.addEventListener('change', e => render(+e.target.value));
render(0);
