"""
nextwave_v2.py — Lógica alineada con Pine «NextWave Suite - Backtest Strategy v2»
Entry Trigger v7 + Confluence Dashboard v7 + Trend Trail v7
"""
from __future__ import annotations


def get_nextwave_signal(
    state: dict,
    params: dict,
    last_long_bar: int | None,
    last_short_bar: int | None,
    current_bar: int,
    open_trade: dict | None = None,
) -> str:
    sc = state["score"]
    p = params
    threshold = p["score_threshold"]
    watch_threshold = p.get("watch_threshold", 48)
    bull_margin = p.get("score_bull_margin", 10)
    bear_margin = p.get("score_bear_margin", bull_margin)
    watch_margin = p.get("watch_bull_margin", 5)

    bull = sc["score_bull"]
    bear = sc["score_bear"]
    momentum = sc.get("momentum_raw", 0.0)

    allow_longs = p.get("allow_longs", True)
    allow_shorts = p.get("allow_shorts", True)
    require_trail = p.get("require_trail_dir", True)
    entry_type = p.get("entry_type", "strong_only")

    long_cd = last_long_bar is None or current_bar - last_long_bar > p["cooldown_bars"]
    short_cd = last_short_bar is None or current_bar - last_short_bar > p["cooldown_bars"]

    mom_vs_long = momentum < p.get("momentum_against_long", -0.5)
    mom_vs_short = momentum > p.get("momentum_against_short", 0.5)

    struct_long = sc.get("bull_choch_recent") or sc.get("bull_bos_recent")
    struct_short = sc.get("bear_choch_recent") or sc.get("bear_bos_recent")
    zone_long = sc.get("bull_zone_near") or sc.get("bull_cross_recent", False)
    zone_short = sc.get("bear_zone_near") or sc.get("bear_cross_recent", False)

    strong_long = (
        bull >= threshold
        and bull > bear + bull_margin
        and sc.get("htf_bull")
        and sc.get("struct_bias") == 1
        and struct_long
        and zone_long
        and not mom_vs_long
        and sc.get("regime_ok")
        and long_cd
    )
    strong_short = (
        bear >= threshold
        and bear > bull + bear_margin
        and sc.get("htf_bear")
        and sc.get("struct_bias") == -1
        and struct_short
        and zone_short
        and not mom_vs_short
        and sc.get("regime_ok")
        and short_cd
    )

    watch_long = (
        entry_type == "strong_watch"
        and bull >= watch_threshold
        and bull > bear + watch_margin
        and sc.get("htf_bull")
        and sc.get("struct_bias") == 1
        and not mom_vs_long
        and sc.get("regime_ok")
        and not strong_long
    )
    watch_short = (
        entry_type == "strong_watch"
        and bear >= watch_threshold
        and bear > bull + watch_margin
        and sc.get("htf_bear")
        and sc.get("struct_bias") == -1
        and not mom_vs_short
        and sc.get("regime_ok")
        and not strong_short
    )

    trail_ok_long = not require_trail or sc.get("trail_dir") == 1
    trail_ok_short = not require_trail or sc.get("trail_dir") == -1

    long_signal = allow_longs and (strong_long or watch_long) and trail_ok_long
    short_signal = allow_shorts and (strong_short or watch_short) and trail_ok_short

    has_position = open_trade is not None
    position_side = (open_trade or {}).get("side", "long")
    use_trail_exit = p.get("use_trail_exit", True)

    close_signal = False
    if has_position and use_trail_exit:
        if position_side == "short" and sc.get("trail_dir") == 1:
            close_signal = True
        elif position_side == "long" and sc.get("trail_dir") == -1:
            close_signal = True

    if long_signal and not has_position:
        return "long"
    if short_signal and not has_position:
        return "short"
    if close_signal:
        return "close"
    return "none"


def compute_nextwave_stops(
    df_ltf,
    i: int,
    params: dict,
    price: float,
    atr: float,
    trail_level: float,
    trail_dir: int,
) -> tuple[float, float, float, float]:
    """SL/TP estilo Pine v2 (invalidación + trail + R multiple)."""
    sl_lookback = int(params.get("sl_lookback", 8))
    sl_buff = float(params.get("sl_buffer", 0.5))
    rr = float(params.get("rr_ratio", 2.0))
    trail_mult = float(params.get("trail_mult", 2.0))

    window = df_ltf.iloc[max(0, i - sl_lookback + 1): i + 1]
    lowest = float(window["low"].min())
    highest = float(window["high"].max())

    long_inv = lowest - atr * sl_buff
    short_inv = highest + atr * sl_buff

    if trail_dir == 1 and trail_level < price:
        long_stop = max(long_inv, trail_level)
    else:
        long_stop = long_inv
    if long_stop >= price:
        long_stop = price - atr * (trail_mult + sl_buff)

    if trail_dir == -1 and trail_level > price:
        short_stop = min(short_inv, trail_level)
    else:
        short_stop = short_inv
    if short_stop <= price:
        short_stop = price + atr * (trail_mult + sl_buff)

    long_risk = max(price - long_stop, price * 1e-8)
    short_risk = max(short_stop - price, price * 1e-8)
    long_tp = price + long_risk * rr
    short_tp = price - short_risk * rr

    return long_stop, long_tp, short_stop, short_tp
