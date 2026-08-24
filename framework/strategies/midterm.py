"""中期量化复合策略 (七层闭环 v2) — Strategy 子类, 复用框架回测引擎

设计: 不重写回测器。本类只负责"生成信号", 回测由 framework/run.py
      (单股+看板) 与 framework/batch_backtest.py (30股批量) 统一执行。

七层对应 EXPERIENCE.md 第十五章:
  第0层 闸门:  F3 板块温度 & F1 个股广度 (满足2个才开仓)
  第1层 板块:  F4/F5 板块趋势 (强势板块)
  第2层 选股:  F6-F9 龙头筛选 (强势板块内只选龙头)
  第3层 信号:  周KDJ多头 & MACD金叉 & MA60向上 & 量比>1.2
  第4层 环境:  ADX+ATR (决定止损宽度, 不投票)
  第5层 退出:  F14 ATR跟踪止损 OR F15 量价背离
  第6层 仓位:  由回测引擎 size 控制 (本版先等权, 精细化见报告)

跨股票状态(广度/板块/龙头)在模块级缓存, 避免每只股票重算全市场。
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import numpy as np
from .base import Strategy, series_to_list
from data import sectors as sec
from data.fetcher import fetch_stock_history
from config.settings import DATA_DIR
from framework.factors.signal import (
    build_entries, macd, volume_ratio, ma_trend, weekly_kdj,
)
from framework.factors.exit import build_exits, atr, adx, volume_divergence_exits
from framework.factors.market_state import breadth, sector_temperature
from framework.factors.sector_trend import build_sector_strong_map
from framework.factors.leader import leader_flags, compute_leader_for_stock

# 保险: 单独 import 本模块时也能定位项目根 (data/config 等包)
_PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJ not in sys.path:
    sys.path.insert(0, _PROJ)

# ===== 模块级缓存: 跨股票状态只算一次 =====
_STATE: dict = {}
_MAPPING = None


def _get_mapping() -> pd.DataFrame:
    global _MAPPING
    if _MAPPING is None:
        _MAPPING = sec.fetch_sector_mapping(use_cache=True)
    return _MAPPING


def _compute_state(start, end, temp_th, breadth_th, top_n):
    """预计算全市场状态(闸门/板块强势/龙头), 按区间+阈值缓存。"""
    key = (pd.Timestamp(start).date(), pd.Timestamp(end).date(),
           float(temp_th), float(breadth_th), int(top_n))
    if key in _STATE:
        return _STATE[key]

    mapping = _get_mapping()
    sl_path = os.path.join(DATA_DIR, "stock_list.csv")
    sl = pd.read_csv(sl_path)
    stock_list = list(zip(sl["symbol"].astype(str).str.zfill(6), sl["name"]))

    # --- 加载个股池 (用于广度 F1 + 龙头排名 F6-F9) ---
    pool = {}
    for sym, _ in stock_list:
        try:
            df = fetch_stock_history(sym, start, end).copy()
            df = df[["open", "high", "low", "close", "volume",
                     "amount", "turnover_rate"]].dropna()
            df.index = pd.to_datetime(df.index)
            if len(df) > 120:
                pool[sym] = df
        except Exception:  # noqa
            continue

    # --- 板块指数 (F3/F4/F5) ---
    sector_dfs = {}
    sectors_info = sec.fetch_sector_list(use_cache=True)
    for _, row in sectors_info.iterrows():
        code = str(row["sector_code"]).split(".")[0]
        try:
            sdf = sec.fetch_sector_index(code, start, end, use_cache=True)
            sdf = sdf[["open", "high", "low", "close", "volume"]].dropna()
            sdf.index = pd.to_datetime(sdf.index)
            if len(sdf) > 60:
                sector_dfs[row["sector_name"]] = sdf
        except Exception:  # noqa
            continue

    # --- 闸门: F3板块温度 & F1个股广度 (满足2个才开仓) ---
    br = breadth(list(pool.values()))
    temp = sector_temperature(list(sector_dfs.values()))
    common = br.index.intersection(temp.index)
    gate = ((temp.reindex(common) > temp_th) & (br.reindex(common) > breadth_th)).fillna(False)

    # --- 板块强势 map / 龙头 map ---
    sector_strong_map = build_sector_strong_map(sector_dfs) if sector_dfs else {}
    leader_map = leader_flags(pool, mapping, top_n=top_n) if pool else {}

    _STATE[key] = {
        "gate": gate,
        "sector_strong_map": sector_strong_map,
        "leader_map": leader_map,
        "mapping": mapping,
        "pool": pool,
    }
    return _STATE[key]


class MidTermStrategy(Strategy):
    name = "midterm"
    label = "中期量化七层闭环"
    params = {
        "vol_min": 1.2, "vol_lookback": 5,
        "atr": 14, "adx": 14,
"mult_strong": 3.5, "mult_weak": 2.0, "adx_thresh": 30.0,
    "use_f15": False,
    "profit_tighten": None,
    "max_retracement": 0.10,
    "use_ma_stop": True,
    "ma_stop_period": 20,
        "top_n": 3,
        "temp_th": 50.0, "breadth_th": 60.0,
        "no_weekly": False, "no_ma60": False, "no_vol": False,
    "ma_period": 20,
        # 跨股票过滤层开关 (默认全关, 逐个开启观察效果)
        "use_sector_strong": False,
        "use_leader": False,
        "use_gate": False,
        "use_size": False,
    }

    def run(self, df: pd.DataFrame):
        n = len(df)
        p = self.params

        # --- 取 symbol (fetcher 已带 symbol 列) ---
        sym = None
        if "symbol" in df.columns:
            sym = str(df["symbol"].iloc[0]).zfill(6)

        # --- 跨股票状态 (懒加载: 仅在需要时才计算全市场数据) ---
        need_cross = p["use_sector_strong"] or p["use_leader"] or p["use_gate"]
        if need_cross:
            state = _compute_state(
                df.index.min(), df.index.max(),
                p["temp_th"], p["breadth_th"], p["top_n"],
            )
            gate = state["gate"].reindex(df.index).fillna(False)
            mapping = state["mapping"]

            # 所属板块 & 龙头标记
            sec_name = None
            if sym is not None:
                sub = mapping[mapping["symbol"] == sym]
                if len(sub):
                    sec_name = sub["sector_name"].iloc[0]
            if sec_name and sec_name in state["sector_strong_map"]:
                sstrong = state["sector_strong_map"][sec_name].reindex(df.index).fillna(False)
            else:
                sstrong = pd.Series(False, index=df.index)
            if sym and sym in state["leader_map"]:
                lflag = state["leader_map"][sym].reindex(df.index).fillna(False)
            elif sym and sec_name:
                lflag = compute_leader_for_stock(
                    sym, df, state["pool"], mapping, top_n=p["top_n"]).fillna(False)
            else:
                lflag = pd.Series(False, index=df.index)
        else:
            gate = pd.Series(False, index=df.index)
            sstrong = pd.Series(False, index=df.index)
            lflag = pd.Series(False, index=df.index)

        # --- 第3层 个股信号 ---
        base = build_entries(
            df,
            use_weekly_kdj=not p["no_weekly"],
            use_ma60=not p["no_ma60"],
            use_vol=not p["no_vol"],
            vol_min=p["vol_min"],
            vol_lookback=p["vol_lookback"],
            ma_period=p["ma_period"],
        )

        # --- 组合: 逐层叠加过滤 ---
        entries = base.copy()
        if p["use_sector_strong"]:
            entries = entries & sstrong
        if p["use_leader"]:
            entries = entries & lflag
        if p["use_gate"]:
            entries = entries & gate
        entries = entries.fillna(False)

        # --- 第5层 退出 ---
        exits, stop_line = build_exits(
            df, entries,
            atr_period=p["atr"], adx_period=p["adx"],
            mult_strong=p["mult_strong"], mult_weak=p["mult_weak"],
            adx_thresh=p["adx_thresh"], use_f15=p["use_f15"],
            profit_tighten=p.get("profit_tighten"),
            max_retracement=p.get("max_retracement"),
            use_ma_stop=p.get("use_ma_stop", False),
            ma_stop_period=p.get("ma_stop_period", 20),
        )

        # --- 可视化指标 ---
        macd_bull, dif, dea = macd(df)
        wk_long, _, _ = weekly_kdj(df)
        ma60_up, ma60 = ma_trend(df, 60)
        vol_ok, _ = volume_ratio(df, min_ratio=p["vol_min"], lookback=p["vol_lookback"])
        # 显示用: 量比值序列 (基类公共口径, 1上下真实值, 供看板双Y轴左轴)
        vr_ratio = self.compute_volume_ratio(df)
        atr_s = atr(df, p["atr"])
        close = df["close"].astype(float)
        ma5 = close.rolling(5).mean()
        ma10 = close.rolling(10).mean()
        ma20 = close.rolling(20).mean()
        indicators = [
            # 主图: 均线 + ATR止损
            {"name": "MA5", "shortName": "MA5", "pane": "main", "paneId": "main",
             "color": "#faad14", "values": series_to_list(ma5, n)},
            {"name": "MA10", "shortName": "MA10", "pane": "main", "paneId": "main",
             "color": "#13c2c2", "values": series_to_list(ma10, n)},
            {"name": "MA20", "shortName": "MA20", "pane": "main", "paneId": "main",
             "color": "#722ed1", "values": series_to_list(ma20, n)},
            {"name": "MA60", "shortName": "MA60", "pane": "main", "paneId": "main",
             "color": "#f5222d", "values": series_to_list(ma60, n)},
            {"name": "ATRstop", "shortName": "ATR止损", "pane": "main", "paneId": "main",
             "color": "#fa8c16", "lineStyle": "dashed", "values": series_to_list(stop_line, n)},
            # 成交量副图: 量比 (基类 vr_indicator, name='VR' 看板契约)
            self.vr_indicator(vr_ratio, n),
            # 策略副图: MACD
            {"name": "DIF", "shortName": "DIF", "pane": "separate", "paneId": "strat",
             "color": "#ffa940", "values": series_to_list(dif, n)},
            {"name": "DEA", "shortName": "DEA", "pane": "separate", "paneId": "strat",
             "color": "#42a5f5", "values": series_to_list(dea, n)},
        ]

        # --- 买卖原因 ---
        reasons = self._build_reasons(
            df, entries, exits, stop_line,
            macd_bull, wk_long, ma60_up, vol_ok,
            sstrong, lflag, gate, p)

        # ===== 第6层 仓位: 半Kelly × ADX系数 + 信号分级 + 连损冷却 =====
        if p["use_size"]:
            adx_s, _, _ = adx(df, p["adx"])
            size = self._compute_size(df, entries, exits, atr_s, adx_s, p)
            return entries.fillna(False), exits.fillna(False), indicators, size, reasons
        return entries.fillna(False), exits.fillna(False), indicators, reasons

    def _build_reasons(self, df, entries, exits, stop_line,
                       macd_bull, wk_long, ma60_up, vol_ok,
                       sstrong, lflag, gate, p):
        """为每个买入/卖出日期生成原因说明。"""
        buy_reasons, sell_reasons = {}, {}
        close = df["close"].astype(float)

        # 买入原因
        for idx in entries[entries].index:
            parts = []
            if macd_bull.loc[idx]: parts.append("MACD多头")
            if wk_long.loc[idx]: parts.append("周KDJ多头")
            if ma60_up.loc[idx]: parts.append("MA60向上")
            if vol_ok.loc[idx]: parts.append("量比放大")
            if p.get("use_sector_strong") and sstrong.loc[idx]: parts.append("板块强势")
            if p.get("use_leader") and lflag.loc[idx]: parts.append("龙头")
            if p.get("use_gate") and gate.loc[idx]: parts.append("市场闸门")
            ts = int(pd.Timestamp(idx).timestamp() * 1000)
            buy_reasons[ts] = " | ".join(parts) if parts else "信号触发"

        # 卖出原因: ATR止损 (close < stop_line) 或 量价背离
        f15_exit = volume_divergence_exits(df, entries)
        for idx in exits[exits].index:
            parts = []
            sl = stop_line.loc[idx] if idx in stop_line.index else np.nan
            if not np.isnan(sl) and close.loc[idx] < sl:
                parts.append("ATR跟踪止损")
            if f15_exit.loc[idx]:
                parts.append("量价背离")
            ts = int(pd.Timestamp(idx).timestamp() * 1000)
            sell_reasons[ts] = " | ".join(parts) if parts else "退出信号"

        return {"buy_reasons": buy_reasons, "sell_reasons": sell_reasons}

    def _compute_size(self, df, entries, exits, atr_s, adx_s, p):
        """第6层 仓位控制 (EXPERIENCE 15.4/15.6)。

        逻辑:
          - 半 Kelly 基准: 胜率40% 盈亏比3:1 → 满Kelly20% / 半Kelly10%;
                          胜率55% 盈亏比3:1 → 满Kelly36.7% / 半Kelly18.3%
          - ADX 系数: ADX>阈值(强趋势)→1.0; 20-阈值→0.6; <20→0(不持仓)
          - 信号分级: 四指标全共振 + 龙头前1 → 满系数(A); 否则半系数(B)
          - 连损冷却: 连续退出(亏损)≥2次 → 强制休息 cooldown 日 (size=0)
        返回与 df 等长的仓位比例 Series (0~0.4 量级), 仅在 entry 日读取。
        """
        n = len(df)
        idx = df.index

        # --- 半 Kelly 基准 (按 A/B 分级给两档) ---
        kelly_full_base = 0.20     # 保守基准: 40%胜率3:1 的满Kelly
        half_kelly = kelly_full_base / 2.0   # 0.10
        size_a = half_kelly                # A级 = 半Kelly满系数
        size_b = half_kelly * 0.5          # B级 = 减半

        # --- ADX 趋势强度系数 ---
        adx_coeff = pd.Series(0.0, index=idx)
        adx_coeff[adx_s >= p["adx_thresh"]] = 1.0
        adx_coeff[(adx_s >= 20) & (adx_s < p["adx_thresh"])] = 0.6

        # --- 信号分级: 四指标全中=A, 否则=B (近似: 全共振=base, 弱=0.5) ---
        # base 已含 周KDJ&MACD&MA60&量比; 龙头前1 额外加成在 _compute_state 未细分,
        # 这里以 base 是否触发作为 A 级判据 (简化, 后续可细分龙头排名)
        grade = pd.Series(size_b, index=idx)
        grade[entries] = size_a

        # --- 逐 bar 连损冷却 (需模拟持仓序列) ---
        size_series = pd.Series(0.0, index=idx)
        in_pos = False
        loss_streak = 0
        cooldown_left = 0
        entry_px = 0.0
        for i in range(n):
            if entries.iloc[i] and not in_pos and cooldown_left <= 0:
                size_series.iloc[i] = grade.iloc[i] * adx_coeff.iloc[i]
                in_pos = True
                entry_px = float(df["close"].iloc[i])
            elif in_pos and exits.iloc[i]:
                # 判定该笔盈亏
                ret = float(df["close"].iloc[i]) / entry_px - 1.0
                if ret < 0:
                    loss_streak += 1
                else:
                    loss_streak = 0
                if loss_streak >= 2:
                    cooldown_left = p.get("cooldown", 5)
                in_pos = False
            elif in_pos and entries.iloc[i]:
                # 已持仓时避免重复开仓
                pass
            if cooldown_left > 0:
                cooldown_left -= 1
                # 冷却期内强制不新开仓
                if entries.iloc[i] and not in_pos:
                    size_series.iloc[i] = 0.0
        return size_series
