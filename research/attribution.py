# -*- coding: utf-8 -*-
"""⑦ 研究闭环 — 逐笔交易归因 (五步闭环第一步: 诊断先行)。

动机 (用户定调 2026-08-29): 不许靠猜优化。任何新实验前先看病灶分布。

对 60 股回测的每一笔交易打标签:
  A. 止损扫损   — 出场时收盘 < ATR止损线, 且盈利从未超过 +10%
                   (入场后很快被扫, 对应杠杆: mult/atr_norm)
  B. 假信号入场 — 止损出场且最大浮亏 < -8%, 盈利从未超过 +5%
                   (入场方向就错了, 对应杠杆: 入场过滤)
  C. 过山车     — 浮盈曾 >= +20% 但最终收益 <= 0
                   (利润没锁住, 对应杠杆: profit_tighten/max_retracement)
  D. 正常止盈   — 盈利出场且非过山车
  E. 深亏       — 亏损出场且最大浮亏 <= -15% 但不满足 B (方向对但拿太久/止损太晚)

  F. 踏空(非交易) — MACD金叉日起 20 个交易日内六因子从未同时满足,
                   但区间涨幅 >= +15% (条件太苛刻错过启动段, 对应: 软过滤/打分制)

标签按优先级互斥: A > B > C > E > D (一笔交易只归一类)。
踏空是区间级标签, 单独统计。

用法:
    python research/attribution.py                       # 默认 midterm 全股票
    python research/attribution.py --start 20210101 --end 20260818
    python research/attribution.py --detail 300308       # 单股逐笔明细
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import vectorbt as vbt

from data.fetcher import fetch_stock_history
from data.sectors import DATA_DIR  # noqa: F401  (保持与 batch 一致的路径语义)
from engine.costs import COST_FEES, COST_SLIPPAGE, INIT_CASH
from strategies import STRATS

# ---- 标签优先级 (互斥, 从严到宽) ----
LABEL_STOPPED_EARLY = "止损扫损"     # A
LABEL_FALSE_SIGNAL = "假信号入场"    # B
LABEL_ROLLERCOASTER = "过山车"       # C
LABEL_DEEP_LOSS = "深亏"             # E
LABEL_NORMAL_WIN = "正常止盈"        # D

LABEL_ORDER = [LABEL_STOPPED_EARLY, LABEL_FALSE_SIGNAL, LABEL_ROLLERCOASTER,
               LABEL_DEEP_LOSS, LABEL_NORMAL_WIN]

# ---- 阈值 (判定口径, 改这里) ----
EARLY_WIN_MAX = 0.10      # 盈利从未超过 +10% 即"早扫"
FALSE_SIGNAL_LOSS = -0.08 # 最大浮亏 <= -8% 且几乎没盈利 → 方向错
FALSE_SIGNAL_WIN = 0.05
ROLL_HIGH = 0.20          # 浮盈曾 >= +20%
ROLL_FINAL = 0.0          # 但最终 <= 0
DEEP_LOSS = -0.15         # 最大浮亏 <= -15%
MISSING_WINDOW = 20       # 金叉后观察窗口(交易日)
MISSING_GAIN = 0.15       # 窗口内涨幅 >= +15% 算踏空


def _load_stock_list():
    """读取 stock_list.csv (与 batch_backtest 同口径)。"""
    path = os.path.join(DATA_DIR, "stock_list.csv")
    df = pd.read_csv(path)
    return list(zip(df["symbol"].astype(str).str.zfill(6), df["name"]))


def _label_trade(ret: float, mfe: float, mae: float, stop_hit: bool) -> str:
    """单笔交易打标签。ret/mfe/mae 为小数收益/最大浮盈/最大浮亏。"""
    if stop_hit and mfe < EARLY_WIN_MAX:
        return LABEL_STOPPED_EARLY
    if mae <= FALSE_SIGNAL_LOSS and mfe < FALSE_SIGNAL_WIN:
        return LABEL_FALSE_SIGNAL
    if mfe >= ROLL_HIGH and ret <= ROLL_FINAL:
        return LABEL_ROLLERCOASTER
    if ret < 0 and mae <= DEEP_LOSS:
        return LABEL_DEEP_LOSS
    return LABEL_NORMAL_WIN


def attribute_trades(df: pd.DataFrame, entries, exits, stop_line, size=None):
    """对单股回测逐笔打标签。

    Returns:
        trades: list[dict] — entry/exit 时间价、ret、mfe、mae、label
    """
    close = df["close"].astype(float)
    pf = vbt.Portfolio.from_signals(
        close=close, entries=entries, exits=exits,
        size=size, size_type='percent' if size is not None else None,
        direction="longonly", init_cash=INIT_CASH,
        fees=COST_FEES, slippage=COST_SLIPPAGE,
    )
    try:
        rec = pf.trades.records_readable
    except Exception as e:
        print(f"  [警告] 提取成交失败: {e}")
        return []

    out = []
    for _, row in rec.iterrows():
        if row["Status"] != "Closed":
            continue
        e_i = close.index.get_loc(pd.Timestamp(row["Entry Timestamp"]))
        x_i = close.index.get_loc(pd.Timestamp(row["Exit Timestamp"]))
        seg = close.iloc[e_i:x_i + 1]
        mfe = float((seg.max() / row["Avg Entry Price"]) - 1)   # 最大浮盈
        mae = float((seg.min() / row["Avg Entry Price"]) - 1)   # 最大浮亏
        ret = float(row["Return"])
        stop_hit = bool(
            not np.isnan(stop_line.iloc[x_i]) and close.iloc[x_i] < stop_line.iloc[x_i])
        out.append({
            "symbol": str(df["symbol"].iloc[0]) if "symbol" in df.columns else "",
            "entry_date": str(pd.Timestamp(row["Entry Timestamp"]).date()),
            "exit_date": str(pd.Timestamp(row["Exit Timestamp"]).date()),
            "entry_px": round(float(row["Avg Entry Price"]), 2),
            "exit_px": round(float(row["Avg Exit Price"]), 2),
            "ret": round(ret * 100, 2),
            "mfe": round(mfe * 100, 2),
            "mae": round(mae * 100, 2),
            "stop_hit": stop_hit,
            "label": _label_trade(ret, mfe, mae, stop_hit),
        })
    return out


def find_missed_moves(df: pd.DataFrame, entries) -> list:
    """踏空检测: MACD金叉后 20 日内六因子从未同真, 但窗口涨幅 >= 15%。

    简化口径: 以"策略 entries 全程为 False 但 macd_bull 为 True 的起点"作候选。
    为避免重复依赖 midterm 内部因子, 这里直接从 midterm 取 macd_bull。
    """
    strat = STRATS["midterm"]()
    from strategies.midterm import _macd
    macd_bull, _, _ = _macd(df)
    close = df["close"].astype(float)
    entries = entries.reindex(df.index).fillna(False)
    macd_bull = macd_bull.reindex(df.index).fillna(False)

    missed = []
    i = 0
    n = len(df)
    while i < n:
        if bool(macd_bull.iloc[i]) and not bool(entries.iloc[max(0, i - 1)]):
            j = min(i + MISSING_WINDOW, n - 1)
            if not bool(entries.iloc[i:j + 1].any()):
                gain = float(close.iloc[j] / close.iloc[i] - 1)
                if gain >= MISSING_GAIN:
                    missed.append({
                        "symbol": str(df["symbol"].iloc[0]) if "symbol" in df.columns else "",
                        "date": str(close.index[i].date()),
                        "window_gain": round(gain * 100, 2),
                    })
                i = j  # 跳过该窗口
        i += 1
    return missed


def run(attribution_start: str, attribution_end: str, detail_symbol=None):
    """主流程: 全股票逐笔归因 + 病灶分布 + 踏空统计。"""
    stock_list = _load_stock_list()
    if detail_symbol and not any(sym == detail_symbol for sym, _ in stock_list):
        stock_list.append((detail_symbol, detail_symbol))  # 测试标的可不在名单
    all_trades, all_missed = [], []
    for k, (symbol, name) in enumerate(stock_list):
        try:
            df = fetch_stock_history(symbol, attribution_start, attribution_end).copy()
            keep = ["open", "high", "low", "close", "volume", "amount",
                    "turnover_rate", "symbol"]
            df = df[[c for c in keep if c in df.columns]].dropna()
            if len(df) < 60:
                continue
            result = STRATS["midterm"]().run(df)
            entries, exits = result[0], result[1]
            # stop_line: 用与 midterm.generate 完全相同的参数重算 (_build_exits 纯函数, 可复现)
            from strategies.midterm import MidTermStrategy, _build_exits, _atr, _adx
            p = MidTermStrategy().params
            atr_s = _atr(df, p["atr"]); adx_s, _, _ = _adx(df, p["adx"])
            _, stop_line = _build_exits(
                df, entries,
                atr_period=p["atr"], adx_period=p["adx"],
                mult_strong=p["mult_strong"], mult_weak=p["mult_weak"],
                adx_thresh=p["adx_thresh"], use_f15=p["use_f15"],
                profit_tighten=p.get("profit_tighten"),
                max_retracement=p.get("max_retracement"),
                use_signal_exit=p.get("use_signal_exit", False),
                use_ma_stop=p.get("use_ma_stop", False),
                ma_stop_period=p.get("ma_stop_period", 20),
                atr_norm_target=p.get("atr_norm_target", 0.0),
                atr_norm_clip=(p.get("atr_norm_lo", 0.6), p.get("atr_norm_hi", 1.6)))
            trades = attribute_trades(df, entries, exits, stop_line)
            all_trades.extend(trades)
            all_missed.extend(find_missed_moves(df, entries))
            if detail_symbol and symbol == detail_symbol:
                print(f"\n=== {symbol} {name} 逐笔明细 ===")
                print(pd.DataFrame(trades).to_string(index=False))
        except Exception as e:
            print(f"  [跳过] {symbol} {name}: {e}")
            continue
        print(f"\r[{k+1}/{len(stock_list)}] {symbol} {name}: {len(trades)}笔", end="", flush=True)

    tdf = pd.DataFrame(all_trades)
    mdf = pd.DataFrame(all_missed)
    print("\n\n" + "=" * 60)
    print("病灶分布 (逐笔归因, 优先级互斥)")
    print("=" * 60)
    if len(tdf):
        dist = tdf["label"].value_counts().reindex(LABEL_ORDER).fillna(0).astype(int)
        total = len(tdf)
        pnl_by = tdf.groupby("label")["ret"].agg(["count", "sum", "mean"]).round(2)
        for label in LABEL_ORDER:
            c = int(dist.get(label, 0))
            if c:
                row = pnl_by.loc[label]
                print(f"  {label:<8} {c:>4}笔 ({c/total*100:4.1f}%)  "
                      f"合计收益 {row['sum']:>9.1f}%  单笔均 {row['mean']:>7.2f}%")
        print(f"  合计 {total}笔")
        out_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "attribution_trades.csv")
        tdf.to_csv(out_csv, index=False, encoding="utf-8-sig")
        print(f"\n  逐笔明细已存: {out_csv}")
    if len(mdf):
        print(f"\n踏空 (金叉后{MISSING_WINDOW}日六因子未同真且涨>{MISSING_GAIN*100:.0f}%): "
              f"{len(mdf)} 次")
        out_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "attribution_missed.csv")
        mdf.to_csv(out_csv, index=False, encoding="utf-8-sig")
        print(f"  踏空明细已存: {out_csv}")
        print(mdf.sort_values("window_gain", ascending=False).head(10).to_string(index=False))


def main():
    ap = argparse.ArgumentParser(description="逐笔交易归因 (诊断先行)")
    ap.add_argument("--start", default="20210101")
    ap.add_argument("--end", default="20260818")
    ap.add_argument("--detail", default=None, help="单股代码, 打印逐笔明细")
    args = ap.parse_args()
    run(args.start, args.end, detail_symbol=args.detail)


if __name__ == "__main__":
    main()
