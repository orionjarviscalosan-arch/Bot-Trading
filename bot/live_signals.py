"""
live_signals.py — Señales en vivo según tipo de estrategia (confluencia o EMA-RSI-ATR)
"""
from __future__ import annotations

import pandas as pd

from bot.signal_engine import compute_all, get_signal
from bot.ema_rsi_atr import compute_indicators, bar_signals, DEFAULT_EMA_RSI_ATR_PARAMS
from bot.strategy_types import apply_strategy_type_params


def is_ema_strategy(params: dict) -> bool:
    st = str(params.get("strategy_type", ""))
    return bool(params.get("ema_rsi_atr")) or st.startswith("ema_rsi_atr")


def build_market_state(
    df_ltf: pd.DataFrame,
    df_htf: pd.DataFrame,
    params: dict,
) -> dict:
    """Estado de mercado unificado para gestión de posiciones."""
    p = {**DEFAULT_EMA_RSI_ATR_PARAMS, **params}
    if is_ema_strategy(p):
        ind = compute_indicators(df_ltf, p)
        if len(ind) < 3:
            raise ValueError("Datos insuficientes para EMA-RSI-ATR")
        row = ind.iloc[-2]
        price = float(ind.iloc[-1]["close"])
        atr = float(row["atr"])
        if atr <= 0:
            atr = float(ind["atr"].iloc[-3] or 1.0)
        sl_m = float(p["sl_atr_mult"])
        tp_m = float(p["tp_atr_mult"])
        return {
            "timestamp": ind.index[-1],
            "price": price,
            "atr": atr,
            "long_sl": price - atr * sl_m,
            "long_tp": price + atr * tp_m,
            "short_sl": price + atr * sl_m,
            "short_tp": price - atr * tp_m,
            "trail_level": price,
            "trail_dir": 0,
            "score": {
                "score_bull": 55 if row["ema_fast"] > row["ema_slow"] else 25,
                "score_bear": 55 if row["ema_fast"] < row["ema_slow"] else 25,
                "trail_dir": 0,
            },
            "_ema_row": row,
            "_ema_ind": ind,
        }
    return compute_all(df_ltf, df_htf, params)


def get_trading_signal(
    state: dict,
    params: dict,
    last_long_bar: int | None,
    last_short_bar: int | None,
    current_bar: int,
    open_trade: dict | None,
) -> str:
    p = {**params}
    if is_ema_strategy(p):
        row = state.get("_ema_row")
        if row is None:
            return "none"
        long_sig, short_sig = bar_signals(row, p)
        cooldown = int(p.get("cooldown_bars", 3))
        side = (open_trade or {}).get("side") or "long"

        if open_trade:
            if side == "long" and short_sig:
                return "close"
            if side == "short" and long_sig:
                return "close"
            return "none"

        if long_sig and (last_long_bar is None or (current_bar - last_long_bar) > cooldown):
            if p.get("allow_longs", True):
                return "long"
        if short_sig and (last_short_bar is None or (current_bar - last_short_bar) > cooldown):
            if p.get("allow_shorts", True):
                return "short"
        return "none"

    return get_signal(state, params, last_long_bar, last_short_bar, current_bar, open_trade)


def use_trailing_exit(params: dict) -> bool:
    if is_ema_strategy(params):
        return False
    return params.get("use_trail_exit", True)
