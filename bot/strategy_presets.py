"""
strategy_presets.py — Estrategias predefinidas para el laboratorio de backtest
"""
from __future__ import annotations

from bot.regime_hmm import DEFAULT_HMM_PARAMS
from bot.ema_rsi_atr import DEFAULT_EMA_RSI_ATR_PARAMS

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

# Optimizado en CSV BTC 2018-2025 (grid 1458 combos, sin HMM)
# Mejor score compuesto: +370 USDT, PF 1.69, DD ~42%, 63 trades
EMA_RSI_ATR_BTC_1D: dict = {
    "name": "EMA-RSI-ATR optimizado - BTC 1D",
    "strategy_type": "ema_rsi_atr",
    "trading_style": "swing",
    "symbol": "BTC/USDT",
    "timeframe": "1d",
    "htf": "1d",
    "notes": (
        "Momentum EMA 21/55 + RSI 50-70 + filtro ATR. "
        "Optimizado en CSV Binance 2018-2025 · capital 1000 · leverage x3 · "
        "SL 1.5×ATR · TP 3×ATR · sin HMM (mejor Calmar que 4H/15m)."
    ),
    "params": {
        **DEFAULT_EMA_RSI_ATR_PARAMS,
        "ema_fast": 21,
        "ema_slow": 55,
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 3.0,
        "atr_filter_mult": 1.0,
        "allow_longs": True,
        "allow_shorts": True,
        "risk_pct": 1.0,
        "leverage": 3.0,
        "commission_pct": 0.001,
        "slippage_pct": 0.0001,
        "spread_pct": 0.0002,
        "initial_capital": 1000.0,
        "cooldown_bars": 4,
        "use_hmm_regime": False,
    },
}

EMA_RSI_ATR_BTC_4H: dict = {
    "name": "EMA-RSI-ATR optimizado - BTC 4H",
    "strategy_type": "ema_rsi_atr",
    "trading_style": "swing",
    "symbol": "BTC/USDT",
    "timeframe": "4h",
    "htf": "1d",
    "notes": (
        "Variante 4H: mayor PnL bruto (+818 USDT en backtest) pero drawdown alto. "
        "Usar solo si aceptas más volatilidad; preferir preset 1D."
    ),
    "params": {
        **DEFAULT_EMA_RSI_ATR_PARAMS,
        "risk_pct": 1.0,
        "leverage": 3.0,
        "commission_pct": 0.001,
        "initial_capital": 1000.0,
        "use_hmm_regime": False,
    },
}

BUILTIN_STRATEGIES: list[dict] = [
    EMA_RSI_ATR_BTC_1D,
    EMA_RSI_ATR_BTC_4H,
    NEXTWAVE_V2_BTC_4H,
]
