"""
trading_styles.py — Presets Scalper / Day Trader / Swing
Autoajusta timeframe, HTF y parámetros de señal.
"""
from __future__ import annotations

VALID_STYLES = ("scalper", "day_trader", "swing")

STYLE_LABELS = {
    "scalper":    "Scalper",
    "day_trader": "Day Trader",
    "swing":      "Swing",
}

# Presets: timeframe, htf, monitor de precio (min), velas históricas, params de señal
TRADING_STYLES: dict[str, dict] = {
    "swing": {
        "label":       "Swing",
        "description": "Operaciones de varios días. Timeframe 4H, contexto diario.",
        "timeframe":   "4h",
        "htf":         "1d",
        "price_monitor_minutes": 5,
        "candles_lb":  500,
        "params": {
            "score_threshold":  68,
            "rr_ratio":         2.0,
            "cooldown_bars":    20,
            "trail_mult":       3.0,
            "trail_lookback":   10,
            "left_bars":        5,
            "right_bars":       5,
            "bos_bars_window":  8,
            "regime_min_ratio": 4.0,
            "htf_fast":  20,
            "htf_slow":  50,
            "htf_trend": 200,
        },
    },
    "day_trader": {
        "label":       "Day Trader",
        "description": "Operaciones intradía. Timeframe 1H, contexto 4H.",
        "timeframe":   "1h",
        "htf":         "4h",
        "price_monitor_minutes": 2,
        "candles_lb":  500,
        "params": {
            "score_threshold":  65,
            "rr_ratio":         1.5,
            "cooldown_bars":    8,
            "trail_mult":       2.5,
            "trail_lookback":   8,
            "left_bars":        4,
            "right_bars":       4,
            "bos_bars_window":  6,
            "regime_min_ratio": 3.5,
            "zone_lookback":    12,
            "htf_fast":  20,
            "htf_slow":  50,
            "htf_trend": 100,
        },
    },
    "scalper": {
        "label":       "Scalper",
        "description": "Operaciones rápidas. Timeframe 15m, contexto 1H.",
        "timeframe":   "15m",
        "htf":         "1h",
        "price_monitor_minutes": 1,
        "candles_lb":  500,
        "params": {
            "score_threshold":  60,
            "rr_ratio":         1.2,
            "cooldown_bars":    3,
            "trail_mult":       2.0,
            "trail_lookback":   6,
            "left_bars":        3,
            "right_bars":       3,
            "bos_bars_window":  5,
            "regime_min_ratio": 3.0,
            "zone_lookback":    10,
            "channel_len":      7,
            "avg_len":          14,
            "fvg_atr_filter":   0.12,
            "htf_fast":  10,
            "htf_slow":  20,
            "htf_trend": 50,
        },
    },
}


def normalize_style(style: str) -> str:
    s = (style or "swing").lower().strip().replace("-", "_").replace(" ", "_")
    aliases = {
        "daytrader": "day_trader",
        "day":       "day_trader",
        "swing_trader": "swing",
    }
    s = aliases.get(s, s)
    if s not in VALID_STYLES:
        raise ValueError(f"TRADING_STYLE inválido: '{style}'. Usa: scalper | day_trader | swing")
    return s


def resolve_active_style() -> str:
    """Estilo activo: bot_state → env → swing."""
    try:
        from bot.database import get_state
        stored = get_state("trading_style") or get_state("active_trading_style")
        if stored:
            return normalize_style(stored)
    except Exception:
        pass
    import os
    return normalize_style(os.getenv("TRADING_STYLE", "swing"))


def get_style_config(style: str) -> dict:
    return TRADING_STYLES[normalize_style(style)]


def apply_style_to_signal_params(base: dict, style: str) -> dict:
    """Fusiona params base con el preset del estilo."""
    preset = get_style_config(style)["params"]
    merged = base.copy()
    merged.update(preset)
    return merged
