"""
strategy_presets.py — Estrategias predefinidas para el laboratorio de backtest
"""
from __future__ import annotations

from bot.regime_hmm import DEFAULT_HMM_PARAMS

# Parámetros alineados con Pine «NextWave Suite v2» — modo Day Trader en 4H
# HTF 1D · capital 1000 · comisión Binance 0.10%/lado · apalancamiento x3
NEXTWAVE_V2_BTC_4H: dict = {
    "name": "NextWave Suite v2 - BTC 4H HMM",
    "strategy_type": "nextwave_v2_hmm",
    "trading_style": "swing",
    "symbol": "BTC/USDT",
    "timeframe": "4h",
    "htf": "1d",
    "notes": (
        "Réplica optimizada del Pine NextWave Suite v2. "
        "BTC/USDT 4H · HTF 1D · Day Trader · filtro HMM · "
        "riesgo 1%/trade · leverage x3 · comisión 0.10% · capital 1000 USD."
    ),
    "params": {
        "score_threshold": 58,
        "watch_threshold": 48,
        "score_bull_margin": 10,
        "watch_bull_margin": 5,
        "entry_type": "strong_only",
        "allow_longs": True,
        "allow_shorts": True,
        "require_trail_dir": True,
        "risk_pct": 1.0,
        "leverage": 3.0,
        "commission_pct": 0.001,
        "slippage_pct": 0.0001,
        "initial_capital": 1000.0,
        "use_take_profit": True,
        "use_trail_exit": True,
        "rr_ratio": 2.0,
        "htf_fast": 20,
        "htf_slow": 50,
        "htf_trend": 200,
        "left_bars": 5,
        "right_bars": 5,
        "bos_bars_window": 8,
        "cross_window_bars": 4,
        "channel_len": 9,
        "avg_len": 21,
        "signal_len": 4,
        "rsi_len": 14,
        "mfi_len": 14,
        "atr_len": 14,
        "fvg_atr_filter": 0.15,
        "zone_lookback": 15,
        "regime_min_ratio": 4.0,
        "regime_penalty": 0.6,
        "trail_mult": 2.0,
        "trail_lookback": 22,
        "use_adaptive": True,
        "adaptive_lb": 100,
        "cooldown_bars": 12,
        "sl_buffer": 0.5,
        "sl_lookback": 8,
        "momentum_against_long": -0.5,
        "momentum_against_short": 0.5,
        "use_liquidity_filter": False,
        "min_ltf_bars": 250,
        "min_htf_bars": 50,
        **DEFAULT_HMM_PARAMS,
        "use_hmm_regime": True,
        "hmm_n_states": 3,
        "hmm_train_bars": 360,
        "hmm_refit_every": 42,
        "hmm_allow_range_trades": False,
    },
}

BUILTIN_STRATEGIES: list[dict] = [
    NEXTWAVE_V2_BTC_4H,
]
