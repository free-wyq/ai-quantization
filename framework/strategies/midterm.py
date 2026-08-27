"""中期量化复合策略 — Strategy 子类, 复用框架回测引擎。

职责单一: 只生成个股信号 (入场/退出/指标/原因)。
跨股票筛选(闸门/板块/龙头)和仓位控制由引擎或独立模块负责。
七层闭环架构见 DESIGN.md 第二部分。
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from ta.volume import OnBalanceVolumeIndicator
from ta.volatility import BollingerBands
from ta.momentum import RSIIndicator
from ta.trend import MACD, ADXIndicator, TRIXIndicator
from ta.momentum import StochasticOscillator
from ta.volatility import AverageTrueRange
from framework.strategies.base import Strategy, series_to_list, SignalResult


# ---- 入场因子 (本策略专用) ----

def _macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD 多头状态 (F10)。返回 (多头布尔, DIF, DEA)。

    用 ta 库 MACD (标准 EMA 口径)。多头状态 = DIF > DEA, 从金叉持续到死叉 (非单日事件)。
    """
    close = df["close"].astype(float)
    m = MACD(close, window_slow=slow, window_fast=fast, window_sign=signal, fillna=False)
    dif, dea = m.macd(), m.macd_signal()
    macd_bull = (dif > dea).fillna(False)
    return macd_bull, dif, dea


def _weekly_kdj(df: pd.DataFrame, n: int = 9, k_period: int = 3, d_period: int = 3):
    """周线 KDJ。返回 (周线多头布尔(日度ffill), K, D)。

    用 ta 库 StochasticOscillator。周线多头状态 (K>D) 作为方向过滤;
    日线 MACD 金叉作为具体买点。周线重采样到日度 (ffill)。

    防未来函数: 周线序列 shift(1) 后再 reindex, 保证只引用"已收盘的上周"信号,
    不使用尚未收盘的本周 (避免回测中用本周未来数据, 导致回测比实盘乐观)。
    """
    w_close = df["close"].resample("W").last().astype(float)
    w_high = df["high"].resample("W").max().astype(float)
    w_low = df["low"].resample("W").min().astype(float)
    s = StochasticOscillator(w_high, w_low, w_close, window=n, smooth_window=k_period, fillna=False)
    K, D = s.stoch(), s.stoch_signal()
    weekly_long = (K > D)
    # shift(1): 周线信号滞后一周, 不引用未收盘的本周; 再 ffill 到日度
    daily_long = weekly_long.shift(1).reindex(df.index, method="ffill").fillna(False)
    return daily_long.astype(bool), K, D


def _monthly_trend(df: pd.DataFrame, ma_period: int = 20):
    """月线方向过滤 (多周期共振的最高层: 大周期定方向)。

    月线 = close.resample('M').last(); 月线多头 = 月收盘站上月线MA(ma_period)。
    作为方向闸门: 月线多头才允许做多, 月线空头全程不做 (不抄底/不逆势, 只抓大趋势)。
    这是方向过滤而非入场AND: 月线信号慢 (月度更新, 多头期持续数月),
    过滤的是逆大势的日线假突破, 不与日线趋势因子 (MACD/TRIX/ADX) 共线 (时间尺度不同)。

    防未来函数: 月线信号 reindex ffill 到日度 — 日K只用"最近已收盘月"的信号
    (月中日K落到上月末信号; 月末日K落到当月信号, 当月收盘同日已知, point-in-time OK)。
    预热期 (月线MA不足 ma_period 个月) 无信号 → 放行 (True), 不因数据不足误杀;
    实盘建议回测 --start 提前约2年, 以充分预热月线MA20。
    返回 (月线多头布尔(日度对齐), 月线MA序列)。
    """
    m_close = df["close"].resample("ME").last().astype(float)
    m_ma = m_close.rolling(ma_period).mean()
    monthly_long = (m_close > m_ma)
    # reindex ffill: 日K取最近已收盘月的信号; 预热期NaN → 放行(True)
    daily_long = monthly_long.reindex(df.index, method="ffill").fillna(True)
    return daily_long.astype(bool), m_ma


def _boll(df: pd.DataFrame, window: int = 20, dev: float = 2.0):
    """BOLL 布林带 (波动率/价格通道, 独立于趋势维度)。

    多头状态 = 收盘价站上布林中轨 (MA20)。与单纯 MA 向上不同:
    BOLL 中轨即 MA20, 但带宽度量波动率, 可供通道突破/收口判断扩展。
    返回 (多头布尔, 中轨序列, 上轨, 下轨, 带宽序列)。
    """
    close = df["close"].astype(float)
    bb = BollingerBands(close=close, window=window, window_dev=dev, fillna=False)
    mid = bb.bollinger_mavg()
    upper = bb.bollinger_hband()
    lower = bb.bollinger_lband()
    boll_bull = (close > mid).fillna(False)
    # 带宽 = (上轨-下轨)/中轨*100, 度量波动率; 收口(低位) = 蓄力期
    bandwidth = ((upper - lower) / mid.replace(0, np.nan) * 100)
    return boll_bull, mid, upper, lower, bandwidth


def _boll_squeeze(df: pd.DataFrame, bw_window: int = 20, bw_rank_window: int = 60,
                  squeeze_pct: float = 0.20):
    """BOLL 带宽收口判断 (波动率状态维度)。

    收口 = 带宽处于近 bw_rank_window 日的低位 (分位 <= squeeze_pct) = 蓄力期。
    蓄力期波动率被压缩, 随后将爆发单边行情; 此时周KDJ等趋势因子常钝化,
    适合放宽入场条件抓住启动点 (择时增强, 非 AND 硬过滤)。
    返回 (收口布尔, 带宽分位序列 0~1)。
    """
    close = df["close"].astype(float)
    bb = BollingerBands(close=close, window=bw_window, window_dev=2.0, fillna=False)
    mid = bb.bollinger_mavg()
    bandwidth = (bb.bollinger_hband() - bb.bollinger_lband()) / mid.replace(0, np.nan) * 100
    bw_pct = bandwidth.rolling(bw_rank_window).rank(pct=True)
    squeeze = (bw_pct <= squeeze_pct).fillna(False)
    return squeeze, bw_pct


def _rsi(df: pd.DataFrame, window: int = 14, ob: float = 70.0, os: float = 30.0):
    """RSI 相对强弱 (动量超买超卖, 独立于趋势/量能维度)。

    用法 (反向, 非入场AND): 超买(RSI>=ob)提示趋势过热, 供退出端参考; 超卖(RSI<=os)提示企稳。
    返回 (RSI序列, 超买布尔, 超卖布尔)。
    """
    close = df["close"].astype(float)
    rsi = RSIIndicator(close=close, window=window, fillna=False).rsi()
    overbought = (rsi >= ob).fillna(False)
    oversold = (rsi <= os).fillna(False)
    return rsi, overbought, oversold


def _volume_ratio(df: pd.DataFrame, window: int = 20, min_ratio: float = 1.2, lookback: int = 5):
    """[已废弃] 量比确认 (F13)。被 _obv 取代, 保留供 use_f15 量价背离退出复用。

    lookback: 近N日内有任意一天量比>min_ratio即满足 (信号持续)。
    """
    close = df["close"].astype(float)
    vol = df["volume"].astype(float)
    avg = vol.rolling(window).mean()
    ratio = vol / avg
    # 量价齐升: 近N日内有任意一天 量比>min_ratio 且当日收涨 (避免放量下跌的假突破)
    raw = ((ratio > min_ratio) & (close > close.shift(1))).fillna(False)
    if lookback > 1:
        raw = raw.rolling(lookback).max().fillna(0).astype(bool)
    return raw, ratio


def _obv(df: pd.DataFrame, window: int = 20, ma_window: int = 30):
    """OBV 能量潮 (量在价先)。

    OBV = 累计成交量 (涨日加, 跌日减, 平盘不变), 反映资金持续流入/流出。
    多头状态 = OBV 在其均线上方 (资金整体流入, 趋势有量能支撑)。
    比"量比放大"更扎实: 量比只看单日放量, OBV 看累计资金方向 (中长期量能)。

    注: 曾用"近 window 日创新高"门槛, 实测满足率仅 ~15% (大涨股高位盘整期 OBV
    不再创新高即卡死, 信号瓶颈), 故改为"站上均线" (持续流入即可, 不要求天天新高),
    满足率约 40~60%, 不再堵死其他趋势因子。
    返回 (多头布尔, OBV序列)。
    """
    close = df["close"].astype(float)
    vol = df["volume"].astype(float)
    obv = OnBalanceVolumeIndicator(close=close, volume=vol, fillna=False).on_balance_volume()
    obv_ma = obv.rolling(ma_window).mean()
    obv_bull = (obv > obv_ma).fillna(False)
    return obv_bull, obv


def _trix(df: pd.DataFrame, window: int = 12, signal_window: int = 9):
    """TRIX 趋势过滤 (三重平滑均线变化率)。

    TRIX = 三重 EMA 的变化率 (%)。配信号线 (TRIX 的 EMA)。
    多头状态 = TRIX > 信号线 (中长期趋势向上, 过滤震荡市的频繁假信号)。
    返回 (多头布尔, TRIX序列, 信号序列)。
    window 默认 12 (A股常用); ta 库默认 15, 此处用 12 更敏感。
    """
    close = df["close"].astype(float)
    trix = TRIXIndicator(close=close, window=window, fillna=False).trix()
    signal = trix.ewm(span=signal_window, adjust=False).mean()
    trix_bull = (trix > signal).fillna(False)
    return trix_bull, trix, signal


# ---- 退出因子 (本策略专用) ----

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """平均真实波幅 (F14 基础)。ta 库 Wilder 平滑 (标准 ATR)。"""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    return AverageTrueRange(high, low, close, window=period, fillna=False).average_true_range()


def _atr_breakout(df: pd.DataFrame, atr_period: int = 14, squeeze_window: int = 20,
                  squeeze_pct: float = 0.5):
    """ATR 波动率收缩→扩张 (全新波动率维度, 独立于趋势/量能)。

    逻辑: ATR 处于近 squeeze_window 日低位 (<= 分位 squeeze_pct) 视为"收缩压缩",
    之后 ATR 环比放大 (今日 ATR > 昨日 ATR) 视为"扩张启动" = 变盘/趋势爆发点。
    这捕捉的是波动率状态转换, 而非价格方向, 与 MACD/MA/TRIX 趋势因子不共线。
    返回 (收缩扩张布尔, ATR分位序列)。
    """
    atr = _atr(df, atr_period)
    # ATR 在近 N 日的分位 (0~1)
    roll_max = atr.rolling(squeeze_window).max()
    roll_min = atr.rolling(squeeze_window).min()
    atr_pct = (atr - roll_min) / (roll_max - roll_min).replace(0, np.nan)
    squeezed = (atr_pct <= squeeze_pct).fillna(False)
    # 收缩后 ATR 环比放大 = 扩张启动
    expanding = (atr > atr.shift(1)).fillna(False)
    breakout = (squeezed & expanding).fillna(False)
    return breakout, atr_pct


def _adx(df: pd.DataFrame, period: int = 14):
    """返回 (ADX, +DI, -DI)。ta 库 Wilder 平滑 (标准 ADX), 度量趋势强度 (无方向)。"""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    i = ADXIndicator(high, low, close, window=period, fillna=False)
    return i.adx(), i.adx_pos(), i.adx_neg()


def _trailing_stop_exits(df, entries, atr_series, adx_series,
                         mult_strong: float = 3.5, mult_weak: float = 2.0,
                         adx_thresh: float = 30.0,
                         profit_tighten=None,
                         max_retracement: float = None):
    """ATR 跟踪止损 (F14) + 利润保护 + 最大回撤止盈。

    止损线 = 持仓最高价 - mult*ATR, 只上移不下移。触碰即卖。
    mult 由 ADX 决定: ADX>=阈值(强趋势)用宽止损吃满, 否则适中。

    profit_tighten: list of (profit_pct, mult), 如 [(1.0, 2.5), (2.0, 2.0)]
    盈利超过 profit_pct 时, 使用更紧的 mult, 锁定利润降低回撤。
    注意: profit_pct 是"小数" (1.0 = 100% 盈利)。盈利 10% 应写 0.1。

    max_retracement: 如 0.25 表示从持仓最高价回落 25% 即退出。
    返回 (exits布尔, stop_line序列)。
    """
    close = df["close"].astype(float)
    n = len(df)
    base_mult = pd.Series(np.where(adx_series >= adx_thresh, mult_strong, mult_weak),
                          index=df.index).astype(float)
    atr_safe = atr_series.fillna(0.0)
    stop_line = pd.Series(np.nan, index=df.index)
    exits = pd.Series(False, index=df.index)
    in_pos = False
    highest = 0.0
    entry_px = 0.0
    prev_stop = np.nan
    for i in range(n):
        if entries.iloc[i] and not in_pos:
            in_pos = True
            highest = float(close.iloc[i])
            entry_px = float(close.iloc[i])
            prev_stop = highest - base_mult.iloc[i] * float(atr_safe.iloc[i])
            stop_line.iloc[i] = prev_stop
        elif in_pos:
            highest = max(highest, float(close.iloc[i]))
            current_mult = base_mult.iloc[i]
            if profit_tighten:
                profit_pct = (highest / entry_px - 1) if entry_px > 0 else 0.0
                for pct, m in sorted(profit_tighten, key=lambda x: x[0]):
                    if profit_pct >= pct:
                        current_mult = m
            new_stop = highest - current_mult * float(atr_safe.iloc[i])
            if max_retracement is not None:
                retracement_stop = highest * (1 - max_retracement)
                # max_retracement 是利润保护底线, 与 profit_tighten 主动收紧取严者
                new_stop = max(new_stop, retracement_stop)
            prev_stop = new_stop if np.isnan(prev_stop) else max(prev_stop, new_stop)
            stop_line.iloc[i] = prev_stop
            if float(close.iloc[i]) < prev_stop:
                exits.iloc[i] = True
                in_pos = False
                prev_stop = np.nan
    return exits.fillna(False), stop_line


def _ma_stop_exits(df, entries, ma_period: int = 20):
    """均线止损: 收盘跌破 MA(ma_period) 即退出。

    止损线 = MA(ma_period), 持仓期间每日更新。
    返回 (exits布尔, stop_line序列)。
    """
    close = df["close"].astype(float)
    ma = close.rolling(ma_period).mean()
    exits = pd.Series(False, index=df.index)
    in_pos = False
    for i in range(len(df)):
        if entries.iloc[i] and not in_pos:
            in_pos = True
        elif in_pos:
            if not np.isnan(ma.iloc[i]) and float(close.iloc[i]) < float(ma.iloc[i]):
                exits.iloc[i] = True
                in_pos = False
    return exits.fillna(False), ma


def _volume_divergence_exits(df, entries, window: int = 20,
                             low_ratio: float = 0.8, high_ratio: float = 3.0):
    """量价背离退出 (F15): 缩量跌回突破位 / 放量滞涨。返回布尔 Series。

    F15a 缩量跌回突破位: close<入场价 且 量比<0.8 → 假突破早退
    F15b 放量滞涨:       量比>3 且 (长上影 或 收跌) → 出货早退
    注: 无持仓日的信号由回测引擎忽略 (不影响)。
    """
    close = df["close"].astype(float)
    vol = df["volume"].astype(float)
    avg_vol = vol.rolling(window).mean()
    ratio = vol / avg_vol
    entry_days = entries & ~entries.shift(1, fill_value=False)
    entry_price = close.where(entry_days).ffill()
    f15a = (close < entry_price) & (ratio < low_ratio)

    body_high = df[["open", "close"]].max(axis=1)
    body_low = df[["open", "close"]].min(axis=1)
    upper_shadow = (df["high"] - body_high)
    body = (body_high - body_low)
    long_upper = upper_shadow > 2.0 * body
    f15b = (ratio > high_ratio) & (long_upper | (df["close"] < df["open"]))

    return (f15a | f15b).fillna(False)


def _build_exits(df, entries, atr_period=14, adx_period=14,
                 mult_strong=3.5, mult_weak=2.0, adx_thresh=30.0,
                 use_f15=False, profit_tighten=None, max_retracement=None,
                 use_signal_exit=False, signal_exit=None,
                 use_ma_stop=False, ma_stop_period=20,
                 f15_exit=None, atr_s=None, adx_s=None, rsi_exit=None):
    """综合退出 = MA止损 / ATR跟踪止损 + 量价背离(可选) + 趋势反转(可选) + RSI超买(可选)。返回 (exits, stop_line)。

    use_ma_stop=True 时使用均线止损, 忽略 ATR 止损参数。
    signal_exit: 预计算的"趋势反转"布尔 Series (如 MACD 死叉日), 传入则叠加为主动退出。
    rsi_exit: 预计算的"RSI超买"布尔 Series, 传入则叠加为主动止盈。
    f15_exit / atr_s / adx_s: 预计算序列, 传入则跳过内部重复计算。
    """
    if use_ma_stop:
        base_exit, stop_line = _ma_stop_exits(df, entries, ma_period=ma_stop_period)
    else:
        if atr_s is None:
            atr_s = _atr(df, atr_period)
        if adx_s is None:
            adx_s, _, _ = _adx(df, adx_period)
        base_exit, stop_line = _trailing_stop_exits(
            df, entries, atr_s, adx_s,
            mult_strong=mult_strong, mult_weak=mult_weak, adx_thresh=adx_thresh,
            profit_tighten=profit_tighten, max_retracement=max_retracement)
    exits = base_exit
    if use_f15:
        if f15_exit is None:
            f15_exit = _volume_divergence_exits(df, entries)
        exits = exits | f15_exit
    if use_signal_exit and signal_exit is not None:
        exits = exits | signal_exit
    if rsi_exit is not None:
        exits = exits | rsi_exit
    return exits.fillna(False), stop_line


class MidTermStrategy(Strategy):
    name = "midterm"
    label = "中期量化"
    params = {
        # 信号
        "vol_min": 1.2, "vol_lookback": 5,
        "no_weekly": False,
        # 月线方向过滤 (多周期共振最高层: 月线多头才允许做多; 默认关, 按需开启)
        "no_monthly": True, "monthly_ma": 20,
        "no_adx": False, "adx_entry_min": 20.0,
        "no_trix": False, "trix_window": 12, "trix_signal": 9,
        "no_obv": False, "obv_window": 20, "obv_ma_window": 30,
        "no_boll": False, "boll_window": 20, "boll_dev": 2.0,
        "use_rsi_exit": False, "rsi_window": 14, "rsi_ob": 70.0,
        # BOLL 带宽收口择时增强 (波动率维度; 默认关, 开启后收口期放宽ADX入场)
        "use_boll_squeeze": False, "boll_rank_window": 60,
        "boll_squeeze_pct": 0.20, "boll_squeeze_adx_min": 10.0,
        # ATR 波动率收缩→扩张 (入场过滤, 独立维度; 默认关, 按需开启)
        "no_atr_breakout": True, "atr_squeeze_window": 20, "atr_squeeze_pct": 0.5,
        # 退出
        "atr": 14, "adx": 14,
        "mult_strong": 3.5, "mult_weak": 2.0, "adx_thresh": 30.0,
        "use_f15": False,
        # B路径(低胜率高赔率): 利润<30% 不收紧止损, 让利润奔跑吃满趋势;
        # 大赚后(30%/60%)才逐步锁利, 避免早止盈砍掉主升浪
        "profit_tighten": [(0.30, 3.0), (0.60, 2.5)], "max_retracement": 0.25,
        # 仓位分级 (双闸: 趋势强度ADX + 大周期方向月线, 都是"减仓"而非"禁入"):
        # ADX>=adx_thresh 且 月线多头 → 满仓; 否则半仓。30股回测: 均PF 1.11→1.26,
        # 回撤 34.4%→22.2%, test段均回撤 11.2% (基准16.5%); 弱势半仓是把震荡市假信号
        # 的亏损减半, 不牺牲趋势市满仓吃利润的机会。size_scale=0 关闭分级回满仓。
        "use_tier_size": True, "size_scale": 0.5,
        "use_signal_exit": False,
        "use_ma_stop": False, "ma_stop_period": 20,
        # 跨股票过滤层 (默认全关, 开启需 data/ 下全市场数据; 数据不全自动降级跳过)
        "use_gate": False, "use_sector_strong": False, "use_leader": False,
        "leader_top": 3, "leader_turnover_min": 1.0, "leader_turnover_max": 30.0,
        # 资金面共振 (默认全关, 开启需联网 akshare 东财; 取数失败自动降级跳过)
        "use_northbound": False, "use_main_flow": False,
        # 基本面排雷 (默认全关, 开启需联网 akshare 百度估值+新浪财务; 取数失败自动降级跳过)
        "use_valuation": False, "use_quality": False, "use_goodwill": False,
        "pe_pct_max": 80.0, "pb_pct_max": 80.0,
        "roe_min": 8.0, "gw_ratio_max": 30.0, "valuation_lookback": 1250,
    }

    def generate(self, df: pd.DataFrame) -> SignalResult:
        n = len(df)
        p = self.params

        # --- 因子计算 (只算一次) ---
        macd_bull, _, _ = _macd(df)
        wk_long, _, _ = _weekly_kdj(df)
        obv_bull, _ = _obv(df, window=p["obv_window"], ma_window=p.get("obv_ma_window", 30))
        trix_bull, _, _ = _trix(df, window=p["trix_window"], signal_window=p["trix_signal"])
        boll_bull, _, _, _, _ = _boll(df, window=p["boll_window"], dev=p["boll_dev"])
        rsi_s, rsi_ob, _ = _rsi(df, window=p["rsi_window"], ob=p["rsi_ob"])
        atr_s = _atr(df, p["atr"])
        adx_s, _, _ = _adx(df, p["adx"])
        # BOLL 带宽收口 (波动率状态: 蓄力期择时增强, 默认关)
        boll_squeeze, _ = _boll_squeeze(
            df, bw_window=p["boll_window"],
            bw_rank_window=p.get("boll_rank_window", 60),
            squeeze_pct=p.get("boll_squeeze_pct", 0.20))
        # 月线方向过滤 (多周期共振最高层: 月线多头才允许做多; 默认关)
        monthly_long, _ = _monthly_trend(df, ma_period=p.get("monthly_ma", 20))
        # ATR 波动率收缩→扩张 (默认关; 开启时作为入场过滤, 独立维度)
        atr_breakout_ok = None
        if not p.get("no_atr_breakout", True):
            atr_breakout_ok, _ = _atr_breakout(
                df, atr_period=p["atr"],
                squeeze_window=p.get("atr_squeeze_window", 20),
                squeeze_pct=p.get("atr_squeeze_pct", 0.5))

        # --- 跨股票因子 (闸门/板块/龙头, 默认全关; 开启需全市场数据, 降级自动跳过) ---
        gate_ok = sector_strong_ok = leader_ok = None
        if p.get("use_gate") or p.get("use_sector_strong") or p.get("use_leader"):
            try:
                from framework.factors.cross_stock import get_cross_stock_factors as _csf
                cs = _csf(
                    str(df["symbol"].iloc[0]) if "symbol" in df.columns else "",
                    df.index,
                    leader_top=p.get("leader_top", 3),
                    turnover_min=p.get("leader_turnover_min", 1.0),
                    turnover_max=p.get("leader_turnover_max", 30.0),
                )
                if cs is not None:
                    gate_ok = cs["gate"]
                    sector_strong_ok = cs["sector_strong"]
                    leader_ok = cs["leader"]
            except Exception:
                pass

        # --- 资金面因子 (北向/主力净流入, 默认全关; 开启需 akshare 东财, 降级自动跳过) ---
        nb_ok = mf_ok = None
        if p.get("use_northbound") or p.get("use_main_flow"):
            try:
                from framework.factors.flow import get_flow_factors as _gff
                sym = str(df["symbol"].iloc[0]) if "symbol" in df.columns else ""
                fl = _gff(sym, df.index)
                if fl is not None:
                    nb_ok = fl["northbound"]
                    mf_ok = fl["main_flow"]
            except Exception:
                pass

        # --- 基本面排雷 (PE/PB分位/ROE/商誉, 默认全关; 开启需 akshare 百度+新浪, 降级自动跳过) ---
        val_ok = qual_ok = gw_ok = None
        if p.get("use_valuation") or p.get("use_quality") or p.get("use_goodwill"):
            try:
                from framework.factors.fundamental import get_fundamental_factors as _gffd
                sym = str(df["symbol"].iloc[0]) if "symbol" in df.columns else ""
                fd = _gffd(sym, df.index,
                           lookback=p.get("valuation_lookback", 1250),
                           pe_max=p.get("pe_pct_max", 80.0), pb_max=p.get("pb_pct_max", 80.0),
                           roe_min=p.get("roe_min", 8.0), gw_ratio_max=p.get("gw_ratio_max", 30.0))
                if fd is not None:
                    val_ok = fd["valuation"]
                    qual_ok = fd["quality"]
                    gw_ok = fd["goodwill"]
            except Exception:
                pass

        # --- 入场信号: MACD多头 & 周KDJ多头 & ADX趋势强 & TRIX & OBV & BOLL ---
        # 严格入场 (6因子AND); BOLL收口期(蓄力)择时增强: 放宽ADX+跳过周KDJ抓启动点
        # 收口期趋势因子常钝化(周KDJ), 故蓄力期跳过周KDJ并用宽松ADX, 等待方向选择
        use_squeeze = bool(p.get("use_boll_squeeze", False))
        if use_squeeze:
            adx_loose = adx_s >= p.get("boll_squeeze_adx_min", 10.0)
            # 收口期: MACD & OBV & TRIX & BOLL & (宽松ADX或严格ADX) — 跳过周KDJ
            # 非收口期: 完整6因子
            base = macd_bull & obv_bull
            if not p["no_trix"]: base = base & trix_bull
            if not p["no_boll"]: base = base & boll_bull
            adx_strict = (adx_s >= p["adx_entry_min"]) if not p["no_adx"] else pd.Series(True, index=df.index)
            adx_part = (boll_squeeze & adx_loose) | (~boll_squeeze & adx_strict)
            entries = base & adx_part
            if not p["no_weekly"]:
                entries = entries & (~boll_squeeze | wk_long)   # 收口期跳过周KDJ
        else:
            entries = macd_bull.copy()
            if not p["no_adx"]:
                entries = entries & (adx_s >= p["adx_entry_min"])
            if not p["no_trix"]:
                entries = entries & trix_bull
            if not p["no_obv"]:
                entries = entries & obv_bull
            if not p["no_boll"]:
                entries = entries & boll_bull
            if not p["no_weekly"]:
                # 周KDJ软过滤(非硬AND): 强趋势(ADX>=阈值)跳过周KDJ(强趋势期周KDJ钝化不可信,
                # 硬AND会踏空主升浪, 如 300308 2023-03翻倍行情全程被周KDJ False 卡死);
                # 弱趋势才用周KDJ过滤, 避免震荡市假信号。
                weekly_strong = adx_s >= p["adx_thresh"]
                entries = entries & (weekly_strong | wk_long)
        # ATR 波动率收缩→扩张: 变盘启动点 (独立维度, 默认关)
        if not p.get("no_atr_breakout", True) and atr_breakout_ok is not None:
            entries = entries & atr_breakout_ok
        # 月线方向过滤 (多周期共振最高层: 月线空头全程不做, 不逆大势; 默认关)
        if not p.get("no_monthly", True):
            entries = entries & monthly_long
        # 跨股票过滤层 (默认关; 开启且数据可用时叠加)
        if p.get("use_gate") and gate_ok is not None:
            entries = entries & gate_ok
        if p.get("use_sector_strong") and sector_strong_ok is not None:
            entries = entries & sector_strong_ok
        if p.get("use_leader") and leader_ok is not None:
            entries = entries & leader_ok
        # 资金面共振 (默认关; 开启且数据可用时叠加, 数据不全默认放行)
        if p.get("use_northbound") and nb_ok is not None:
            entries = entries & nb_ok
        if p.get("use_main_flow") and mf_ok is not None:
            entries = entries & mf_ok
        # 基本面排雷 (默认关; 开启且数据可用时叠加, 数据不全默认放行)
        if p.get("use_valuation") and val_ok is not None:
            entries = entries & val_ok
        if p.get("use_quality") and qual_ok is not None:
            entries = entries & qual_ok
        if p.get("use_goodwill") and gw_ok is not None:
            entries = entries & gw_ok
        entries = entries.fillna(False)

        # --- 退出 ---
        f15_exit = _volume_divergence_exits(df, entries) if p["use_f15"] else None
        # 趋势反转主动退出: 趋势弱时(ADX<阈值, 震荡市)MACD或周KDJ死叉即撤, 早断亏损;
        # 趋势强时(ADX>=阈值)不触发, 交给 ATR 跟踪止损吃满趋势利润 (不砍大牛股的趋势)。
        # 用 reindex 对齐到日线; 仅作退出信号, 入场逻辑不变。
        signal_exit = None
        if p.get("use_signal_exit"):
            macd_bear = (~macd_bull).reindex(df.index).fillna(False)
            wk_bear = (~wk_long).reindex(df.index).fillna(False)
            weak_trend = (adx_s < p["adx_thresh"]).reindex(df.index).fillna(False)
            signal_exit = ((macd_bear | wk_bear) & weak_trend).fillna(False)
        # RSI 超买退出: RSI>=超买线提示趋势过热, 叠加为主动止盈 (默认关, 强趋势股慎用)
        rsi_exit = rsi_ob.reindex(df.index).fillna(False) if p.get("use_rsi_exit") else None
        exits, stop_line = _build_exits(
            df, entries,
            atr_period=p["atr"], adx_period=p["adx"],
            mult_strong=p["mult_strong"], mult_weak=p["mult_weak"],
            adx_thresh=p["adx_thresh"], use_f15=p["use_f15"],
            profit_tighten=p.get("profit_tighten"),
            max_retracement=p.get("max_retracement"),
            use_signal_exit=p.get("use_signal_exit", False),
            signal_exit=signal_exit,
            use_ma_stop=p.get("use_ma_stop", False),
            ma_stop_period=p.get("ma_stop_period", 20),
            f15_exit=f15_exit, atr_s=atr_s, adx_s=adx_s,
            rsi_exit=rsi_exit,
        )

        # --- 可视化指标 ---
        _ind_specs = [
            ("ATRstop", "ATR止损", "main", "main", "#fa8c16", "dashed", "line", stop_line),
        ]
        indicators = [
            {"name": nm, "shortName": sn, "pane": pn, "paneId": pid,
             "color": cl, "lineStyle": ls, "type": tp, "values": series_to_list(val, n)}
            for nm, sn, pn, pid, cl, ls, tp, val in _ind_specs
        ]

        # --- 买卖原因 ---
        reasons = self._build_reasons(df, entries, exits, stop_line, p,
                                     macd_bull, wk_long, adx_s,
                                     f15_exit, signal_exit, trix_bull, obv_bull, boll_bull, rsi_exit,
                                     atr_breakout_ok, monthly_long)

        # --- 仓位分级 (双闸: 强趋势&月线多头满仓, 否则减仓; 减仓≠禁入, 不砍趋势利润) ---
        size = None
        if p.get("use_tier_size", True):
            weak_scale = float(p.get("size_scale", 0.5))
            strong = (adx_s >= p["adx_thresh"]) & monthly_long
            size = pd.Series(np.where(strong, 1.0, weak_scale), index=df.index)

        return SignalResult(entries, exits.fillna(False), indicators, reasons, size=size)

    def _build_reasons(self, df, entries, exits, stop_line, p,
                       macd_bull, wk_long, adx_s,
                       f15_exit=None, signal_exit=None, trix_bull=None, obv_bull=None,
                       boll_bull=None, rsi_exit=None, atr_breakout_ok=None, monthly_long=None):
        """为每个买入/卖出日期生成原因说明。"""
        close = df["close"].astype(float)

        buy_flags = [
            (macd_bull, "MACD多头"), (wk_long, "周KDJ多头"),
        ]
        if not p["no_adx"]:
            buy_flags.append((adx_s >= p["adx_entry_min"], "ADX趋势强"))
        if not p["no_trix"]:
            buy_flags.append((trix_bull, "TRIX多头"))
        if not p["no_obv"]:
            buy_flags.append((obv_bull, "OBV资金流入"))
        if not p["no_boll"]:
            buy_flags.append((boll_bull, "BOLL站上中轨"))
        if not p.get("no_atr_breakout", True) and atr_breakout_ok is not None:
            buy_flags.append((atr_breakout_ok, "ATR波动扩张"))
        if not p.get("no_monthly", True) and monthly_long is not None:
            buy_flags.append((monthly_long, "月线多头"))

        buy_reasons = {}
        for idx in entries[entries].index:
            parts = [label for flag, label in buy_flags if flag.loc[idx]]
            ts = int(pd.Timestamp(idx).timestamp() * 1000)
            buy_reasons[ts] = " | ".join(parts) if parts else "信号触发"

        sell_reasons = {}
        use_ma_stop = p.get("use_ma_stop", False)
        for idx in exits[exits].index:
            parts = []
            sl = stop_line.loc[idx] if idx in stop_line.index else np.nan
            if not np.isnan(sl) and close.loc[idx] < sl:
                parts.append("MA止损" if use_ma_stop else "ATR跟踪止损")
            if p["use_f15"] and f15_exit is not None and f15_exit.loc[idx]:
                parts.append("量价背离")
            if p.get("use_signal_exit") and signal_exit is not None and signal_exit.loc[idx]:
                parts.append("趋势反转")
            if p.get("use_rsi_exit") and rsi_exit is not None and rsi_exit.loc[idx]:
                parts.append("RSI超买")
            ts = int(pd.Timestamp(idx).timestamp() * 1000)
            sell_reasons[ts] = " | ".join(parts) if parts else "退出信号"

        return {"buy_reasons": buy_reasons, "sell_reasons": sell_reasons}
