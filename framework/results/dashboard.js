const RUNS = window.__RUNS__ || [];
const sel = document.getElementById('sel');
const chartEl = document.getElementById('chart');
const metricsEl = document.getElementById('metrics');
const tradesBody = document.querySelector('#trades tbody');

let currentIdx = 0;
let currentPeriod = 'day';   // 'day' | 'week' | 'month'
let currentIndicator = 'MACD';   // 动态副图指标 (下拉选择)

RUNS.forEach((r, i) => {
  const o = document.createElement('option');
  o.value = i; o.textContent = r.label; sel.appendChild(o);
});

// 周期切换器 (JS 注入, 不改 dashboard.html): 日线 / 周线 / 月线
const periodSel = document.createElement('select');
periodSel.id = 'period';
periodSel.style.minWidth = '0';
periodSel.style.width = '90px';
[['day','日线'],['week','周线'],['month','月线']].forEach(([v,t])=>{
  const o=document.createElement('option'); o.value=v; o.textContent=t; periodSel.appendChild(o);
});
sel.parentNode.insertBefore(periodSel, sel.nextSibling);
periodSel.addEventListener('change', e=>{ currentPeriod=e.target.value; render(currentIdx); });

// 动态指标选择器 (副图: MACD/KDJ/RSI 等 klinecharts 内置指标, 切换即时重算)
const INDICATORS = [
  ['MACD','MACD'],['KDJ','KDJ'],['RSI','RSI'],['DMI','DMI(ADX)'],['WR','WR威廉'],
  ['CCI','CCI'],['OBV','OBV能量潮'],['VR','VR量比'],['BOLL','BOLL布林'],['TRIX','TRIX'],
  ['MTM','MTM动量'],['BIAS','BIAS乖离'],['CR','CR'],['BRAR','BRAR'],['EMV','EMV'],
  ['PSY','PSY心理线'],['PVT','PVT'],['ROC','ROC'],
];
const indicatorSel = document.createElement('select');
indicatorSel.id = 'indicator';
indicatorSel.style.minWidth = '0';
indicatorSel.style.width = '110px';
INDICATORS.forEach(([v,t])=>{
  const o=document.createElement('option'); o.value=v; o.textContent=t; indicatorSel.appendChild(o);
});
periodSel.parentNode.insertBefore(indicatorSel, periodSel.nextSibling);
indicatorSel.addEventListener('change', e=>{ currentIndicator=e.target.value; applyIndicator(); });

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

// 成交量面板用 klinecharts 内置 VOL 指标 (柱按涨跌着色 + MA5/MA10 成交量均线),
// 不再手写 registerIndicator。配色跟随 setStyles.indicator.bars (涨红跌绿)。

// 策略曲线: 按 paneId 分组, 同 pane 的多条线合并为一个指标的多 figures
let registeredStratInds = [];
function renderStrategyIndicators(r) {
  // 清除旧策略指标
  registeredStratInds.forEach(name => chart.removeIndicator({ name }));
  registeredStratInds = [];
  if (!r.indicators || !r.indicators.length) return;

  // 按 paneId 分组 (main 单独处理)
  const groups = {};
  r.indicators.forEach(ind => {
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

/* ---- 周期重采样: 日线 → 周/月线 (纯前端聚合, 不改后端) ---- */

// 按 ISO 周 / 自然月给每根日 bar 打分组 key
function periodKey(ts, period){
  const d = new Date(ts);
  if (period === 'month') return d.getUTCFullYear() + '-' + String(d.getUTCMonth()+1).padStart(2,'0');
  // ISO 周: 用周四定位所属周 (getUTCDate + 3 - getUTCDay), 周日=0→化为周一=0 口径
  const thu = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + 3 - (d.getUTCDay()||7)));
  const year = thu.getUTCFullYear();
  const week1Thu = new Date(Date.UTC(year, 0, 4));
  const week = 1 + Math.round(((thu - week1Thu) / 86400000 - 3 + (week1Thu.getUTCDay()||7)) / 7);
  return year + '-W' + String(week).padStart(2,'0');
}

// 将日级 run 数据按 period 重采样为周/月视图。period==='day' 时原样返回 (零开销, 保留现状)。
function buildView(r0, period){
  if (period === 'day' || !r0.candles || r0.candles.length === 0) return r0;

  // 分组: 连续相同 key 的日 bar 归为一组, 记录组内日线索引
  const groups = [];      // number[][] — 每组是日线索引数组
  const dailyToGroup = new Array(r0.candles.length);  // 日线索引 → 组索引
  let prevKey = null;
  r0.candles.forEach((c, i) => {
    const k = periodKey(c.timestamp, period);
    if (k !== prevKey) { groups.push([]); prevKey = k; }
    const gi = groups.length - 1;
    groups[gi].push(i);
    dailyToGroup[i] = gi;
  });

  // 聚合 candles: open=组首, high=max, low=min, close=组末, volume=sum, ts=组首
  const candles = groups.map(idx => {
    const first = r0.candles[idx[0]];
    const last  = r0.candles[idx[idx.length-1]];
    let hi = -Infinity, lo = Infinity, vol = 0;
    idx.forEach(j => {
      hi = Math.max(hi, r0.candles[j].high);
      lo = Math.min(lo, r0.candles[j].low);
      vol += r0.candles[j].volume;
    });
    return { timestamp: first.timestamp, open: first.open, high: hi, low: lo,
             close: last.close, volume: vol };
  });

  // 指标 values 每组取组末值 (该周/月最后一日的值; MA/ATRstop 均取周末生效值)
  const indicators = (r0.indicators||[]).map(ind => {
    const vals = groups.map(idx => {
      const lastIdx = idx[idx.length-1];
      return (lastIdx < ind.values.length) ? ind.values[lastIdx] : null;
    });
    return { ...ind, values: vals };
  });

  // 权益每组取组末 value, ts 换成组首 (对齐 candles 索引, 供 EQUITY calc 用)
  const equity = groups.map(idx => {
    const lastIdx = idx[idx.length-1];
    const e = (r0.equity && lastIdx < r0.equity.length) ? r0.equity[lastIdx] : null;
    return { timestamp: r0.candles[idx[0]].timestamp, value: e ? e.value : null };
  });

  // 买卖点: trade.ts → 日线索引 → 组索引 → 组首 bar ts (让 overlay 落在正确的周/月 bar)
  const tsToDaily = {};
  r0.candles.forEach((c, i) => { tsToDaily[c.timestamp] = i; });
  const remap = arr => arr.map(p => {
    const di = tsToDaily[p.timestamp];
    const gi = (di != null) ? dailyToGroup[di] : -1;
    const newTs = (gi >= 0) ? candles[gi].timestamp : p.timestamp;
    return { ...p, timestamp: newTs };
  });

  return { ...r0, candles, indicators, equity, buys: remap(r0.buys||[]), sells: remap(r0.sells||[]) };
}

/* ---- 动态指标副图 (下拉选择 klinecharts 内置指标) ---- */
let dynamicIndName = null;   // 当前已挂载的动态指标名 (用于精确移除)

// 移除上一个动态指标 (按 name 移除; 兼容 registerIndicator 自定义名)
function removeDynamicIndicator(){
  if (dynamicIndName) {
    chart.removeIndicator({ name: dynamicIndName });
    dynamicIndName = null;
  }
}

// 切换/挂载当前选中的动态指标到 strat_indicator 副图
function applyIndicator(){
  removeDynamicIndicator();
  const name = currentIndicator;
  chart.createIndicator({ name, paneId: 'strat_indicator' });
  dynamicIndName = name;
}

function render(idx){
  currentIdx = idx;
  const r0 = RUNS[idx];
  if (!r0) return;
  const r = buildView(r0, currentPeriod);   // 重采样视图 (日线时 === r0)

  chart.removeOverlay();
  chart.removeIndicator({ name: 'EQUITY' });
  // 内置指标: VOL(成交量+MA) 固定; 动态副图指标每次切换 run 先清掉再由 applyIndicator 重建
  chart.removeIndicator({ name: 'VOL' });
  removeDynamicIndicator();

  // v10: setSymbol + setPeriod + setDataLoader 三者就绪后触发 getBars
  chart.setSymbol({ ticker: r.symbol });
  chart.setPeriod({ type: currentPeriod, span: 1 });
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

        // 四层布局: 主图50% | 成交量15% | 动态指标20% | 账户权益15%
        const totalH = chartEl.clientHeight;
        const layout = [
          { id: 'candle_pane',    height: Math.floor(totalH * 0.50) },
          { id: 'vol_pane',       height: Math.floor(totalH * 0.15) },
          { id: 'strat_indicator',height: Math.floor(totalH * 0.20) },
          { id: 'equity_pane',    height: Math.floor(totalH * 0.15) },
        ];
        layout.forEach(l => {
          try { chart.setPaneOptions({ id: l.id, height: l.height }); } catch(e) {}
        });
      }, 50);
    }
  });

  // 内置 VOL 指标: 成交量柱 (按涨跌着色) + MA5/MA10 成交量均线, 绑 vol_pane 默认右轴
  // calcParams 控制均线周期, 主题色跟随 setStyles.indicator.bars (涨红跌绿)
  chart.createIndicator({
    name: 'VOL', paneId: 'vol_pane',
    calcParams: [5, 10]
  });

  // 策略曲线 (ATR止损线等策略专属, 由策略函数动态提供; MA均线由基类注入)
  renderStrategyIndicators(r);

  // 动态指标副图 (下拉选择 MACD/KDJ/RSI 等, 原生指标前端从K线自算, 切换周期自动重算)
  applyIndicator();

  // 权益曲线 (放在所有副图最下方)
  equityData = r.equity || [];
  chart.createIndicator({
    name: 'EQUITY', paneId: 'equity_pane',
    styles: { lines: [{ color: '#1f77b4', style: 'solid', size: 1.5 }] }
  });

  // 买卖点标注 (用重采样视图 r: ts 已 remap 到周/月 bar)
  r.buys.forEach(p => addAnnotation(p, 'B', '#ff4d4f'));
  r.sells.forEach(p => addAnnotation(p, 'S', '#00c853'));

  // 指标卡片 + 交易明细表: 用原始日线 r0 (周期无关 — 交易日仍是日级事实, metrics 是回测总计)
  const m = r0.metrics;
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
  r0.buys.forEach((b, i) => {
    const s = r0.sells[i];
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
