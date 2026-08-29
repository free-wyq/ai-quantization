"""跨股票状态缓存 (闸门/板块/龙头因子的全市场状态)

跨股票因子(个股广度/板块温度/板块强势/龙头标记)需遍历整个股票池 + 板块指数,
不能在单股 generate() 内重算。本模块按"区间+阈值"缓存全市场状态,
midterm.generate() 通过 _state() 懒加载、按 symbol 取当日切片。

降级: 当股票池/板块数据不可用时 (如单股离线回测、无 amount 列),
_state() 返回 None, midterm 跨股票层自动跳过 (params 开关形同关闭)。
"""
from __future__ import annotations

import os
import glob
import pandas as pd
from config.settings import DATA_DIR

_POOL: dict | None = None        # {symbol: 日K df}
_SECTORS: dict | None = None     # {板块名: 板块指数 df}
_MAPPING: pd.DataFrame | None = None


def _load_pool() -> dict:
    """加载 data/*_daily.csv 为 {symbol: df}。"""
    global _POOL
    if _POOL is not None:
        return _POOL
    pool = {}
    for f in sorted(glob.glob(os.path.join(DATA_DIR, "*_daily.csv"))):
        sym = os.path.basename(f).replace("_daily.csv", "")
        try:
            d = pd.read_csv(f, index_col=0, parse_dates=True)
            pool[sym] = d
        except Exception:
            continue
    _POOL = pool
    return pool


def _load_sectors() -> dict:
    """加载 data/sectors/*.csv 为 {板块名: 板块指数 df}。"""
    global _SECTORS
    if _SECTORS is not None:
        return _SECTORS
    sec_idx: dict = {}
    sec_dir = os.path.join(DATA_DIR, "sectors")
    if not os.path.isdir(sec_dir):
        _SECTORS = {}
        return _SECTORS
    slist_path = os.path.join(DATA_DIR, "sector_list.csv")
    code2name = {}
    if os.path.exists(slist_path):
        try:
            slist = pd.read_csv(slist_path)
            code2name = {str(r["sector_code"]).split(".")[0]: r["sector_name"]
                         for _, r in slist.iterrows()}
        except Exception:
            pass
    for f in sorted(glob.glob(os.path.join(sec_dir, "*_daily.csv"))):
        code = os.path.basename(f).replace("_daily.csv", "")
        name = code2name.get(code, code)
        try:
            sec_idx[name] = pd.read_csv(f, index_col=0, parse_dates=True)
        except Exception:
            continue
    _SECTORS = sec_idx
    return sec_idx


def _load_mapping() -> pd.DataFrame | None:
    """加载 个股-板块 映射表。"""
    global _MAPPING
    if _MAPPING is not None:
        return _MAPPING
    path = os.path.join(DATA_DIR, "sector_mapping.csv")
    if not os.path.exists(path):
        _MAPPING = None
        return None
    try:
        mp = pd.read_csv(path)
        mp["symbol"] = mp["symbol"].astype(str).str.zfill(6)
        _MAPPING = mp
        return mp
    except Exception:
        _MAPPING = None
        return None


# 按区间+阈值缓存的全市场状态 (避免同一批回测重复算)
_STATE: dict = {}


def _state_key(start, end, breadth_ma, sector_ma, leader_top, to_min, to_max):
    return (str(start), str(end), breadth_ma, sector_ma, leader_top, to_min, to_max)


def _compute_market_state(start, end, breadth_ma=20, sector_ma=20,
                          leader_top=3, turnover_min=1.0, turnover_max=30.0):
    """计算全市场跨股票状态 (一次性), 返回 dict 或 None (数据不可用时)。

    返回:
        {
          'gate': pd.Series(布尔, 日度),          # F1+F3 满足≥2 个开仓
          'sector_strong': pd.Series(布尔, 日度), # 当前股所属板块当日是否强势
          'leader': pd.Series(布尔, 日度),         # 当前股当日是否龙头
        }
        按 symbol 切片由 caller 负责。这里只算全市场广度/温度, 单股龙头单独算。
    """
    pool = _load_pool()
    if len(pool) < 5:           # 池太小没意义
        return None

    from factors.market_state import breadth, sector_temperature
    from factors.sector_trend import build_sector_strong_map

    # 截区间
    s = pd.Timestamp(start) if start else None
    e = pd.Timestamp(end) if end else None
    pool_cut = {sym: (d.loc[s:e] if s and e else d) for sym, d in pool.items()}

    # F1 个股广度
    b = breadth(list(pool_cut.values()), ma_period=breadth_ma)
    # F3 板块温度
    sec_named = _load_sectors()
    sec_cut = {n: (d.loc[s:e] if s and e else d) for n, d in sec_named.items()}
    st = sector_temperature(list(sec_cut.values()), ma_period=sector_ma) if sec_cut else None

    # 闸门: F1>=50 + F3>=50 满足≥2 个 (F3 不可用则只看 F1>=50)
    if st is not None:
        b_a = b.reindex(st.index).fillna(50.0)
        st_a = st.reindex(st.index).fillna(50.0)
        gate = (((b_a >= 50).astype(int) + (st_a >= 50).astype(int)) >= 2)
    else:
        gate = (b >= 50)
    gate = gate.fillna(True)   # 数据不全默认放行, 不卡死

    # 板块强势 map {板块名: 布尔Series}
    strong_map = build_sector_strong_map(sec_cut) if sec_cut else {}

    return {"gate": gate, "sector_strong_map": strong_map}


def get_cross_stock_factors(symbol: str, index: pd.DatetimeIndex,
                            start=None, end=None,
                            breadth_ma=20, sector_ma=20,
                            leader_top=3, turnover_min=1.0, turnover_max=30.0):
    """为单股取跨股票因子切片。

    Returns:
        dict: {'gate': bool Series, 'sector_strong': bool Series, 'leader': bool Series}
        全部对齐到 index; 数据不可用则各项默认 True (放行)。
    """
    pool = _load_pool()
    mp = _load_mapping()
    if len(pool) < 5 or mp is None:
        return None

    key = _state_key(start, end, breadth_ma, sector_ma, leader_top, turnover_min, turnover_max)
    state = _STATE.get(key)
    if state is None:
        state = _compute_market_state(start, end, breadth_ma, sector_ma,
                                      leader_top, turnover_min, turnover_max)
        _STATE[key] = state
    if state is None:
        return None

    # 闸门 (全市场, 对齐到该股)
    gate = state["gate"].reindex(index).fillna(True)

    # 板块强势 (该股所属板块)
    sector_strong = pd.Series(True, index=index)   # 默认放行
    sym_sec = mp[mp["symbol"] == str(symbol).zfill(6)]
    if len(sym_sec) > 0:
        sec_name = sym_sec["sector_name"].iloc[0]
        sm = state["sector_strong_map"].get(sec_name)
        if sm is not None:
            sector_strong = sm.reindex(index).fillna(True)

    # 龙头 (单股实时算: 池内同板块排名)
    leader = pd.Series(True, index=index)   # 默认放行
    try:
        from factors.leader import compute_leader_for_stock
        df = pool.get(str(symbol).zfill(6))
        if df is not None:
            pool_cut = {s: (d.loc[pd.Timestamp(start):pd.Timestamp(end)]
                            if start and end else d) for s, d in pool.items()}
            lflag = compute_leader_for_stock(
                str(symbol), df.loc[df.index[0]:df.index[-1]],
                pool_cut, mp, top_n=leader_top,
                turnover_min=turnover_min, turnover_max=turnover_max)
            leader = lflag.reindex(index).fillna(False)
    except Exception:
        pass

    return {"gate": gate, "sector_strong": sector_strong, "leader": leader}
