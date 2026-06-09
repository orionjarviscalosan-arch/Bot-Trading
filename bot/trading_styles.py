"""
trading_styles.py — Presets por timeframe con parámetros autoajustados
"""
from __future__ import annotations

VALID_STYLES = ("ultra_1m", "micro_5m", "scalper", "day_trader", "swing")

STYLE_LABELS = {
    "ultra_1m":   "Ultra 1m",
    "micro_5m":  "Micro 5m",
    "scalper":   "Scalper 15m",
    "day_trader": "Day Trader",
    "swing":     "Swing",
}

# Presets: timeframe, htf, monitor de precio (min), velas históricas, params de señal
TRADING_STYLES: dict[str, dict] = {
    "ultra_1m": {
        "label":       "Ultra 1m",
        "description": "Scalping ultra-rápido. Timeframe 1m, contexto 5m.",
        "timeframe":   "1m",
        "htf":         "5m",
        "price_monitor_minutes": 1,
        "candles_lb":  800,
        "params": {
            "score_threshold":  58,
            "score_bull_margin": 6,
            "momentum_min":     0.0,
            "rr_ratio":         1.0,
            "cooldown_bars":    5,
            "trail_mult":       1.5,
            "trail_lookback":   4,
            "left_bars":        2,
            "right_bars":       2,
            "bos_bars_window":  3,
            "regime_min_ratio": 2.0,
            "zone_lookback":    6,
            "channel_len":      5,
            "avg_len":          10,
            "signal_len":       3,
            "rsi_len":          8,
            "mfi_len":          8,
            "atr_len":          10,
            "fvg_atr_filter":   0.08,
            "adaptive_lb":      60,
            "sl_buffer":        0.12,
            "min_ltf_bars":     120,
            "min_htf_bars":     40,
            "htf_fast":  5,
            "htf_slow":  12,
            "htf_trend": 30,
        },
    },
    "micro_5m": {
        "label":       "Micro 5m",
        "description": "Scalping frecuente. Timeframe 5m, contexto 15m.",
        "timeframe":   "5m",
        "htf":         "15m",
        "price_monitor_minutes": 1,
        "candles_lb":  600,
        "params": {
            "score_threshold":  55,
            "score_bull_margin": 5,
            "htf_min_score":    10,
            "momentum_min":     -0.3,
            "momentum_max":     0.3,
            "rr_ratio":         1.1,
            "cooldown_bars":    2,
            "trail_mult":       1.8,
            "trail_lookback":   5,
            "left_bars":        2,
            "right_bars":       2,
            "bos_bars_window":  4,
            "regime_min_ratio": 2.0,
            "zone_lookback":    8,
            "channel_len":      6,
            "avg_len":          12,
            "signal_len":       3,
            "rsi_len":          10,
            "mfi_len":          10,
            "atr_len":          10,
            "fvg_atr_filter":   0.10,
            "adaptive_lb":      80,
            "sl_buffer":        0.15,
            "min_ltf_bars":     150,
            "min_htf_bars":     45,
            "htf_fast":  8,
            "htf_slow":  16,
            "htf_trend": 40,
        },
    },
    "swing": {
        "label":       "Swing",
        "description": "Operaciones de varios días. Timeframe 4H, contexto diario.",
        "timeframe":   "4h",
        "htf":         "1d",
        "price_monitor_minutes": 5,
        "candles_lb":  500,
        "params": {
            "score_threshold":  68,
            "score_bull_margin": 10,
            "momentum_min":     -0.5,
            "rr_ratio":         2.0,
            "cooldown_bars":    20,
            "trail_mult":       3.0,
            "trail_lookback":   10,
            "left_bars":        5,
            "right_bars":       5,
            "bos_bars_window":  8,
            "regime_min_ratio": 4.0,
            "sl_buffer":        0.20,
            "min_ltf_bars":     200,
            "min_htf_bars":     50,
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
            "score_bull_margin": 9,
            "momentum_min":     -0.4,
            "rr_ratio":         1.5,
            "cooldown_bars":    8,
            "trail_mult":       2.5,
            "trail_lookback":   8,
            "left_bars":        4,
            "right_bars":       4,
            "bos_bars_window":  6,
            "regime_min_ratio": 3.5,
            "zone_lookback":    12,
            "sl_buffer":        0.18,
            "min_ltf_bars":     200,
            "min_htf_bars":     50,
            "htf_fast":  20,
            "htf_slow":  50,
            "htf_trend": 100,
        },
    },
    "scalper": {
        "label":       "Scalper 15m",
        "description": "Operaciones rápidas. Timeframe 15m, contexto 1H.",
        "timeframe":   "15m",
        "htf":         "1h",
        "price_monitor_minutes": 1,
        "candles_lb":  500,
        "params": {
            "score_threshold":  62,
            "score_bull_margin": 8,
            "momentum_min":     -0.3,
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
            "sl_buffer":        0.18,
            "min_ltf_bars":     180,
            "min_htf_bars":     50,
            "htf_fast":  10,
            "htf_slow":  20,
            "htf_trend": 50,
        },
    },
}


def normalize_style(style: str) -> str:
    s = (style or "swing").lower().strip().replace("-", "_").replace(" ", "_")
    aliases = {
        "1m":          "ultra_1m",
        "ultra":       "ultra_1m",
        "scalp_1m":    "ultra_1m",
        "5m":          "micro_5m",
        "micro":       "micro_5m",
        "scalp_5m":    "micro_5m",
        "15m":         "scalper",
        "daytrader":   "day_trader",
        "day":         "day_trader",
        "swing_trader": "swing",
    }
    s = aliases.get(s, s)
    if s not in VALID_STYLES:
        raise ValueError(
            f"TRADING_STYLE inválido: '{style}'. "
            f"Usa: ultra_1m | micro_5m | scalper | day_trader | swing"
        )
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


def list_styles_summary() -> str:
    """Resumen de estilos para Telegram/dashboard."""
    lines = []
    for key in VALID_STYLES:
        sc = TRADING_STYLES[key]
        lines.append(f"· <b>{sc['label']}</b> — {sc['timeframe']} / HTF {sc['htf']}")
    return "\n".join(lines)
