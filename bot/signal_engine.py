"""
signal_engine.py — Replica exacta de los indicadores Pine Script v7
Calcula todos los pilares del sistema de confluencia en Python
"""
import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# INDICADORES BASE
# ══════════════════════════════════════════════════════════

def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()

def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(length).mean()

def calc_atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=length, adjust=False).mean()

def calc_rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(span=length, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(span=length, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def calc_mfi(df: pd.DataFrame, length: int = 14) -> pd.Series:
    hlc3     = (df["high"] + df["low"] + df["close"]) / 3
    raw_mf   = hlc3 * df["volume"]
    pos_mf   = raw_mf.where(hlc3 > hlc3.shift(1), 0).rolling(length).sum()
    neg_mf   = raw_mf.where(hlc3 < hlc3.shift(1), 0).rolling(length).sum()
    mfr      = pos_mf / neg_mf.replace(0, np.nan)
    return 100 - (100 / (1 + mfr))

def calc_wavetrend(df: pd.DataFrame, channel_len=9, avg_len=21, signal_len=4):
    """WaveTrend — réplica exacta del Pine Script"""
    ap  = (df["high"] + df["low"] + df["close"]) / 3
    esa = ema(ap, channel_len)
    de  = ema((ap - esa).abs(), channel_len)
    ci  = (ap - esa) / (0.015 * de.replace(0, np.nan))
    wt1 = ema(ci, avg_len)
    wt2 = sma(wt1, signal_len)
    return wt1, wt2


# ══════════════════════════════════════════════════════════
# PIVOTS — sin repainting
# Equivalente a ta.pivothigh/pivotlow con rightBars de confirmación
# ══════════════════════════════════════════════════════════

def calc_pivots(df: pd.DataFrame, left: int = 5, right: int = 5):
    """
    Devuelve series de pivot highs y lows confirmados.
    El pivot se asigna a la vela donde se detectó (bar_index - rightBars).
    """
    high  = df["high"]
    low   = df["low"]
    n     = len(df)
    ph    = pd.Series(np.nan, index=df.index)
    pl    = pd.Series(np.nan, index=df.index)

    for i in range(left, n - right):
        window_h = high.iloc[i - left : i + right + 1]
        window_l = low.iloc[i  - left : i + right + 1]
        if high.iloc[i] == window_h.max():
            ph.iloc[i] = high.iloc[i]
        if low.iloc[i] == window_l.min():
            pl.iloc[i] = low.iloc[i]

    return ph, pl


# ══════════════════════════════════════════════════════════
# ESTRUCTURA — BOS / CHoCH
# ══════════════════════════════════════════════════════════

def calc_structure(df: pd.DataFrame, piv_high: pd.Series, piv_low: pd.Series,
                   bos_bars_window: int = 8):
    """
    Calcula structureBias, bullBos, bearBos, bullChoch, bearChoch.
    Solo usa datos pasados (sin lookahead).
    """
    close       = df["close"]
    n           = len(df)
    struct_bias = np.zeros(n, dtype=int)
    bull_bos    = np.zeros(n, dtype=bool)
    bear_bos    = np.zeros(n, dtype=bool)
    bull_choch  = np.zeros(n, dtype=bool)
    bear_choch  = np.zeros(n, dtype=bool)

    last_sh = np.nan
    last_sl = np.nan
    bias    = 0

    for i in range(1, n):
        # Actualizar último swing conocido
        if not np.isnan(piv_high.iloc[i - 1]):
            last_sh = piv_high.iloc[i - 1]
        if not np.isnan(piv_low.iloc[i - 1]):
            last_sl = piv_low.iloc[i - 1]

        c0 = close.iloc[i]
        c1 = close.iloc[i - 1]

        b_bos = (not np.isnan(last_sh)) and c0 > last_sh and c1 <= last_sh
        s_bos = (not np.isnan(last_sl)) and c0 < last_sl and c1 >= last_sl

        b_choch = b_bos and (bias == -1)
        s_choch = s_bos and (bias ==  1)

        if b_bos:
            bias = 1
        if s_bos:
            bias = -1

        struct_bias[i] = bias
        bull_bos[i]    = b_bos
        bear_bos[i]    = s_bos
        bull_choch[i]  = b_choch
        bear_choch[i]  = s_choch

    idx = df.index
    df_out = pd.DataFrame({
        "struct_bias": struct_bias,
        "bull_bos":    bull_bos,
        "bear_bos":    bear_bos,
        "bull_choch":  bull_choch,
        "bear_choch":  bear_choch,
    }, index=idx)

    # BOS / CHoCH reciente dentro de la ventana
    df_out["bull_bos_recent"]   = df_out["bull_bos"].rolling(bos_bars_window).max().astype(bool)
    df_out["bear_bos_recent"]   = df_out["bear_bos"].rolling(bos_bars_window).max().astype(bool)
    df_out["bull_choch_recent"] = df_out["bull_choch"].rolling(bos_bars_window).max().astype(bool)
    df_out["bear_choch_recent"] = df_out["bear_choch"].rolling(bos_bars_window).max().astype(bool)

    return df_out


# ══════════════════════════════════════════════════════════
# FVG — Fair Value Gaps
# ══════════════════════════════════════════════════════════

def calc_fvg(df: pd.DataFrame, atr: pd.Series, atr_filter: float = 0.15,
             zone_lookback: int = 15):
    """Detecta FVGs alcistas y bajistas"""
    low, high = df["low"], df["high"]
    n = len(df)

    bull_fvg = pd.Series(False, index=df.index)
    bear_fvg = pd.Series(False, index=df.index)

    for i in range(2, n):
        bull = (low.iloc[i] > high.iloc[i - 2] and
                (low.iloc[i] - high.iloc[i - 2]) > atr.iloc[i] * atr_filter)
        bear = (high.iloc[i] < low.iloc[i - 2] and
                (low.iloc[i - 2] - high.iloc[i]) > atr.iloc[i] * atr_filter)
        bull_fvg.iloc[i] = bull
        bear_fvg.iloc[i] = bear

    # FVG reciente dentro del lookback
    recent_bull = bull_fvg.rolling(zone_lookback).max().astype(bool)
    recent_bear = bear_fvg.rolling(zone_lookback).max().astype(bool)

    # Distancia al FVG más reciente (en ATR)
    bull_fvg_top = low.where(bull_fvg)
    bear_fvg_bot = high.where(bear_fvg)
    bull_fvg_top_ffill = bull_fvg_top.ffill()
    bear_fvg_bot_ffill = bear_fvg_bot.ffill()

    bull_dist = (df["close"] - bull_fvg_top_ffill).abs() / atr
    bear_dist = (df["close"] - bear_fvg_bot_ffill).abs() / atr
    bull_dist = bull_dist.where(recent_bull, 999.0)
    bear_dist = bear_dist.where(recent_bear, 999.0)

    return pd.DataFrame({
        "bull_fvg":        bull_fvg,
        "bear_fvg":        bear_fvg,
        "recent_bull_fvg": recent_bull,
        "recent_bear_fvg": recent_bear,
        "bull_fvg_dist":   bull_dist.fillna(999.0),
        "bear_fvg_dist":   bear_dist.fillna(999.0),
        "bull_zone_near":  recent_bull & (bull_dist < 1.0),
        "bear_zone_near":  recent_bear & (bear_dist < 1.0),
    })


# ══════════════════════════════════════════════════════════
# CHANDELIER EXIT ADAPTATIVO — réplica del Trend Trail v7
# ══════════════════════════════════════════════════════════

def calc_trail(df: pd.DataFrame, atr: pd.Series, multiplier: float = 3.0,
               lookback: int = 10, use_adaptive: bool = True,
               adaptive_lb: int = 100):
    """
    Trail puro: solo se mueve a favor del precio.
    Devuelve trail_level y trail_dir (1=bull, -1=bear).
    """
    atr_high = atr.rolling(adaptive_lb).max()
    atr_low  = atr.rolling(adaptive_lb).min()
    atr_pct  = (atr - atr_low) / (atr_high - atr_low).replace(0, 1)
    adapt_f  = (0.8 + atr_pct * 0.6) if use_adaptive else pd.Series(1.0, index=df.index)
    final_m  = multiplier * adapt_f

    long_raw  = df["high"].rolling(lookback).max() - atr * final_m
    short_raw = df["low"].rolling(lookback).min()  + atr * final_m

    n           = len(df)
    trail_level = np.full(n, np.nan)
    trail_dir   = np.ones(n, dtype=int)

    for i in range(n):
        lr = long_raw.iloc[i]
        sr = short_raw.iloc[i]
        if np.isnan(lr) or np.isnan(sr):
            if i > 0:
                trail_level[i] = trail_level[i - 1]
                trail_dir[i]   = trail_dir[i - 1]
            continue

        if i == 0:
            trail_level[i] = lr
            trail_dir[i]   = 1
            continue

        prev_lv  = trail_level[i - 1]
        prev_dir = trail_dir[i - 1]
        c        = df["close"].iloc[i]

        if prev_dir == 1:
            new_lv = max(lr, prev_lv)
            if c < new_lv:
                trail_dir[i]   = -1
                trail_level[i] = sr
            else:
                trail_dir[i]   = 1
                trail_level[i] = new_lv
        else:
            new_lv = min(sr, prev_lv)
            if c > new_lv:
                trail_dir[i]   = 1
                trail_level[i] = lr
            else:
                trail_dir[i]   = -1
                trail_level[i] = new_lv

    return (pd.Series(trail_level, index=df.index),
            pd.Series(trail_dir,   index=df.index))


# ══════════════════════════════════════════════════════════
# CONFLUENCIA — 5 pilares, réplica exacta del Dashboard v7
# ══════════════════════════════════════════════════════════

def calc_confluence_score(row: pd.Series, htf_row: pd.Series,
                          params: dict) -> dict:
    """
    Calcula el score de confluencia de los 5 pilares para la última vela.
    row     = última fila del DataFrame 4H con todos los indicadores
    htf_row = última fila del DataFrame 1D
    """
    # ── P1: HTF Context (25 pts) ──────────────────────────
    htf_fast_over_slow  = htf_row.get("htf_fast",  0) > htf_row.get("htf_slow",  0)
    htf_slow_over_trend = htf_row.get("htf_slow",  0) > htf_row.get("htf_trend", 0)
    htf_price_over_fast = htf_row.get("htf_close", 0) > htf_row.get("htf_fast",  0)

    p1_bull = min(
        (12.0 if htf_fast_over_slow  else 0) +
        (8.0  if htf_slow_over_trend else 0) +
        (5.0  if htf_price_over_fast else 0), 25.0)
    p1_bear = min(
        (12.0 if not htf_fast_over_slow  else 0) +
        (8.0  if not htf_slow_over_trend else 0) +
        (5.0  if not htf_price_over_fast else 0), 25.0)

    htf_bull = htf_fast_over_slow and htf_slow_over_trend and htf_price_over_fast
    htf_bear = not htf_fast_over_slow and not htf_slow_over_trend and not htf_price_over_fast

    # ── P2: Structure (25 pts) ────────────────────────────
    sb = row.get("struct_bias", 0)
    bull_choch_r = bool(row.get("bull_choch_recent", False))
    bear_choch_r = bool(row.get("bear_choch_recent", False))
    bull_bos_r   = bool(row.get("bull_bos_recent",   False))
    bear_bos_r   = bool(row.get("bear_bos_recent",   False))

    p2_bull = min(
        (12.0 if sb == 1 else 0) +
        (15.0 if bull_choch_r else 8.0 if bull_bos_r else 0), 25.0)
    p2_bear = min(
        (12.0 if sb == -1 else 0) +
        (15.0 if bear_choch_r else 8.0 if bear_bos_r else 0), 25.0)

    # ── P3: Zone / FVG (20 pts) ───────────────────────────
    r_bull_fvg = bool(row.get("recent_bull_fvg", False))
    r_bear_fvg = bool(row.get("recent_bear_fvg", False))
    bull_dist  = float(row.get("bull_fvg_dist",  999))
    bear_dist  = float(row.get("bear_fvg_dist",  999))

    p3_bull = min(
        (8.0 if r_bull_fvg else 0) +
        (max(12.0 - bull_dist * 3.0, 0) if r_bull_fvg else 0), 20.0)
    p3_bear = min(
        (8.0 if r_bear_fvg else 0) +
        (max(12.0 - bear_dist * 3.0, 0) if r_bear_fvg else 0), 20.0)

    # ── P4: Momentum (20 pts) ─────────────────────────────
    wt1      = float(row.get("wt1", 0))
    wt2      = float(row.get("wt2", 0))
    rsi      = float(row.get("rsi", 50))
    mfi      = float(row.get("mfi", 50))

    wt_norm  = max(min(wt1 / 80.0, 1.0), -1.0)
    rsi_norm = max(min((rsi - 50) / 50.0, 1.0), -1.0)
    mfi_norm = max(min((mfi - 50) / 50.0, 1.0), -1.0)

    is_trend = abs(wt1) > 30
    wt_w  = 0.55 if is_trend else 0.40
    rsi_w = 0.25 if is_trend else 0.30
    mfi_w = 0.20 if is_trend else 0.30
    mom_raw = wt_w * wt_norm + rsi_w * rsi_norm + mfi_w * mfi_norm

    bull_cross_r = bool(row.get("bull_cross_recent", False))
    bear_cross_r = bool(row.get("bear_cross_recent", False))
    p4_bull_evt  = 10.0 if (bull_cross_r and wt1 < -20) else 6.0 if bull_cross_r else 0.0
    p4_bear_evt  = 10.0 if (bear_cross_r and wt1 >  20) else 6.0 if bear_cross_r else 0.0

    p4_bull = min((mom_raw * 10 if mom_raw > 0 else 0) + p4_bull_evt, 20.0)
    p4_bear = min((abs(mom_raw) * 10 if mom_raw < 0 else 0) + p4_bear_evt, 20.0)

    # ── P5: Regime bonus (10 pts) ─────────────────────────
    atr_ratio = float(row.get("atr_ratio", 0))
    regime_ok = atr_ratio >= params["regime_min_ratio"]
    p5_bonus  = 10.0 if atr_ratio >= params["regime_min_ratio"] * 2 else 0.0

    # ── Scores finales ────────────────────────────────────
    raw_bull = p1_bull + p2_bull + p3_bull + p4_bull + p5_bonus
    raw_bear = p1_bear + p2_bear + p3_bear + p4_bear + p5_bonus

    penalty = params.get("regime_penalty", 0.6)
    final_bull = round(raw_bull * penalty if not regime_ok else min(raw_bull, 100))
    final_bear = round(raw_bear * penalty if not regime_ok else min(raw_bear, 100))

    return {
        "score_bull":    final_bull,
        "score_bear":    final_bear,
        "htf_bull":      htf_bull,
        "htf_bear":      htf_bear,
        "struct_bias":   int(sb),
        "regime_ok":     regime_ok,
        "momentum_raw":  round(mom_raw, 4),
        "trail_dir":     int(row.get("trail_dir", 1)),
        "bull_zone_near": bool(row.get("bull_zone_near", False)),
        "bear_zone_near": bool(row.get("bear_zone_near", False)),
        "bull_choch_recent": bull_choch_r,
        "bear_choch_recent": bear_choch_r,
        "bull_bos_recent":   bull_bos_r,
        "bear_bos_recent":   bear_bos_r,
        "p1_bull": round(p1_bull), "p1_bear": round(p1_bear),
        "p2_bull": round(p2_bull), "p2_bear": round(p2_bear),
        "p3_bull": round(p3_bull), "p3_bear": round(p3_bear),
        "p4_bull": round(p4_bull), "p4_bear": round(p4_bear),
        "p5_bonus": round(p5_bonus),
    }


# ══════════════════════════════════════════════════════════
# PIPELINE PRINCIPAL
# ══════════════════════════════════════════════════════════

def compute_all(df_4h: pd.DataFrame, df_1d: pd.DataFrame,
                params: dict) -> dict:
    """
    Calcula todos los indicadores y devuelve el estado actual del mercado.
    df_4h: DataFrame 4H con OHLCV (velas confirmadas)
    df_1d: DataFrame 1D con OHLCV
    params: parámetros activos del SIGNAL_PARAMS
    """
    p = params
    if len(df_4h) < p.get("min_ltf_bars", 200) or len(df_1d) < p.get("min_htf_bars", 50):
        raise ValueError("Datos insuficientes para calcular indicadores")

    # ── Indicadores 4H ────────────────────────────────────
    atr_4h        = calc_atr(df_4h, p["atr_len"])
    wt1, wt2      = calc_wavetrend(df_4h, p["channel_len"], p["avg_len"], p["signal_len"])
    rsi           = calc_rsi(df_4h["close"], p["rsi_len"])
    mfi           = calc_mfi(df_4h, p["mfi_len"])
    piv_h, piv_l  = calc_pivots(df_4h, p["left_bars"], p["right_bars"])
    struct        = calc_structure(df_4h, piv_h, piv_l, p["bos_bars_window"])
    fvg           = calc_fvg(df_4h, atr_4h, p["fvg_atr_filter"], p["zone_lookback"])
    trail, tdir   = calc_trail(df_4h, atr_4h, p["trail_mult"], p["trail_lookback"],
                               p["use_adaptive"], p["adaptive_lb"])

    # Cruce de WaveTrend con ventana
    bull_cross = (wt1 > wt2) & (wt1.shift(1) <= wt2.shift(1))
    bear_cross = (wt1 < wt2) & (wt1.shift(1) >= wt2.shift(1))
    cw = p.get("cooldown_bars", 4)
    bull_cross_r = bull_cross.rolling(cw).max().astype(bool)
    bear_cross_r = bear_cross.rolling(cw).max().astype(bool)

    # Regime
    price_range = df_4h["high"].rolling(20).max() - df_4h["low"].rolling(20).min()
    atr_ratio   = price_range / atr_4h.replace(0, np.nan)

    # ── Indicadores 1D (HTF) ──────────────────────────────
    htf_fast_ema  = ema(df_1d["close"], p["htf_fast"])
    htf_slow_ema  = ema(df_1d["close"], p["htf_slow"])
    htf_trend_ema = ema(df_1d["close"], p["htf_trend"])

    # ── Ensamblar DataFrame 4H ────────────────────────────
    df_4h = df_4h.copy()
    df_4h["wt1"]              = wt1
    df_4h["wt2"]              = wt2
    df_4h["rsi"]              = rsi
    df_4h["mfi"]              = mfi
    df_4h["atr"]              = atr_4h
    df_4h["atr_ratio"]        = atr_ratio
    df_4h["trail_level"]      = trail
    df_4h["trail_dir"]        = tdir
    df_4h["bull_cross_recent"]= bull_cross_r
    df_4h["bear_cross_recent"]= bear_cross_r
    for col in struct.columns:
        df_4h[col] = struct[col]
    for col in fvg.columns:
        df_4h[col] = fvg[col]

    # ── Última fila confirmada ─────────────────────────────
    row_4h = df_4h.iloc[-1]

    # HTF más reciente anterior o igual a la última vela 4H
    htf_df = pd.DataFrame({
        "htf_fast":  htf_fast_ema,
        "htf_slow":  htf_slow_ema,
        "htf_trend": htf_trend_ema,
        "htf_close": df_1d["close"],
    })
    # Seleccionar la barra diaria más reciente anterior a la última 4H
    last_4h_ts = df_4h.index[-1]
    htf_filtered = htf_df[htf_df.index <= last_4h_ts]
    row_htf = htf_filtered.iloc[-1] if len(htf_filtered) > 0 else htf_df.iloc[-1]

    # ── Score de confluencia ──────────────────────────────
    score = calc_confluence_score(row_4h, row_htf, p)

    if p.get("use_hmm_regime"):
        from bot.regime_hmm import predict_current_regime
        regime_label, regime_probs = predict_current_regime(df_4h, p)
        score["hmm_regime"] = regime_label
        score["hmm_probs"] = regime_probs

    # ── Niveles de entrada ────────────────────────────────
    current_price = float(df_4h["close"].iloc[-1])
    trail_level   = float(df_4h["trail_level"].iloc[-1])
    atr_val       = float(atr_4h.iloc[-1])
    sl_buffer     = p.get("sl_buffer", 0.2)

    long_sl  = trail_level - atr_val * sl_buffer
    long_tp  = current_price + (current_price - long_sl) * p["rr_ratio"]
    short_sl = trail_level + atr_val * sl_buffer
    short_tp = current_price - (short_sl - current_price) * p["rr_ratio"]

    return {
        "timestamp":     df_4h.index[-1],
        "price":         current_price,
        "atr":           atr_val,
        "trail_level":   trail_level,
        "trail_dir":     int(tdir.iloc[-1]),
        "long_sl":       round(long_sl, 2),
        "long_tp":       round(long_tp, 2),
        "short_sl":      round(short_sl, 2),
        "short_tp":      round(short_tp, 2),
        "score":         score,
        "df":            df_4h,
    }


# ══════════════════════════════════════════════════════════
# DECISIÓN DE SEÑAL
# ══════════════════════════════════════════════════════════

def get_signal(state: dict, params: dict,
               last_long_bar: int | None,
               last_short_bar: int | None,
               current_bar: int,
               open_trade: dict | None = None) -> str:
    """
    Evalúa el estado actual y devuelve: 'long' | 'short' | 'close' | 'none'
    Entradas long/short son espejo del Pine Entry Trigger v7.
    """
    sc       = state["score"]
    p        = params
    threshold = p["score_threshold"]
    cd_bars   = p["cooldown_bars"]
    bull_margin = p.get("score_bull_margin", 10)
    bear_margin = p.get("score_bear_margin", bull_margin)
    momentum_min = p.get("momentum_min", -0.5)
    momentum_max = p.get(
        "momentum_max",
        -0.01 if momentum_min >= 0 else -momentum_min,
    )

    bull = sc["score_bull"]
    bear = sc["score_bear"]

    has_position = open_trade is not None
    position_side = (open_trade or {}).get("side", "long")

    long_cooldown_ok = (
        last_long_bar is None or current_bar - last_long_bar > cd_bars
    )
    short_cooldown_ok = (
        last_short_bar is None or current_bar - last_short_bar > cd_bars
    )

    # Señal de ENTRADA LONG
    long_signal = (
        bull >= threshold
        and bull > bear + bull_margin
        and (sc["htf_bull"] or sc.get("p1_bull", 0) >= p.get("htf_min_score", 12))
        and sc["struct_bias"] == 1
        and (sc["bull_choch_recent"] or
             (sc["bull_bos_recent"] and sc["bull_zone_near"]))
        and sc["momentum_raw"] > momentum_min
        and sc["regime_ok"]
        and sc["trail_dir"] == 1
        and long_cooldown_ok
        and not has_position
    )

    # Señal de ENTRADA SHORT (espejo bajista)
    short_signal = (
        bear >= threshold
        and bear > bull + bear_margin
        and (sc["htf_bear"] or sc.get("p1_bear", 0) >= p.get("htf_min_score", 12))
        and sc["struct_bias"] == -1
        and (sc["bear_choch_recent"] or
             (sc["bear_bos_recent"] and sc["bear_zone_near"]))
        and sc["momentum_raw"] < momentum_max
        and sc["regime_ok"]
        and sc["trail_dir"] == -1
        and short_cooldown_ok
        and not has_position
    )

    # Señal de CIERRE según lado de la posición
    close_signal = False
    if has_position:
        if position_side == "short":
            close_signal = (
                sc["trail_dir"] == 1
                or bull >= threshold
            )
        else:
            close_signal = (
                sc["trail_dir"] == -1
                or bear >= threshold
            )

    if long_signal:
        return _apply_hmm_entry_filter("long", sc, p)
    if short_signal:
        return _apply_hmm_entry_filter("short", sc, p)
    if close_signal:
        return "close"
    return "none"


def _apply_hmm_entry_filter(signal: str, sc: dict, params: dict) -> str:
    if signal not in ("long", "short") or not params.get("use_hmm_regime"):
        return signal
    from bot.regime_hmm import hmm_allows_long, hmm_allows_short
    regime = sc.get("hmm_regime", "range")
    if signal == "long" and not hmm_allows_long(regime, params):
        return "none"
    if signal == "short" and not hmm_allows_short(regime, params):
        return "none"
    return signal