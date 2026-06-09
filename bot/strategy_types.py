"""
strategy_types.py — Tipos de estrategia disponibles en backtest y laboratorio
"""
from __future__ import annotations

STRATEGY_TYPES: dict[str, dict] = {
    "confluence": {
        "label": "Confluencia SMC (actual)",
        "description": "Señales Pine v7: HTF, estructura, FVG, momentum y régimen ATR.",
        "use_hmm_regime": False,
        "hmm_pure": False,
    },
    "hmm_confluence": {
        "label": "Confluencia + filtro HMM",
        "description": "Confluencia SMC filtrada por régimen HMM (long en bull, short en bear).",
        "use_hmm_regime": True,
        "hmm_pure": False,
    },
    "hmm_regime": {
        "label": "HMM puro por régimen",
        "description": "Entradas por transición de régimen HMM (bear/range/bull).",
        "use_hmm_regime": True,
        "hmm_pure": True,
    },
    "nextwave_v2": {
        "label": "NextWave Suite v2 (Pine)",
        "description": "Réplica Entry Trigger v7 + Confluence + Trend Trail.",
        "use_hmm_regime": False,
        "hmm_pure": False,
        "nextwave_v2": True,
    },
    "nextwave_v2_hmm": {
        "label": "NextWave Suite v2 + HMM",
        "description": "NextWave v2 filtrado por régimen HMM para reducir drawdown.",
        "use_hmm_regime": True,
        "hmm_pure": False,
        "nextwave_v2": True,
    },
    "ema_rsi_atr": {
        "label": "EMA + RSI + ATR (momentum)",
        "description": "Tendencia EMA 21/55, RSI 50-70, filtro ATR, SL/TP dinámicos.",
        "use_hmm_regime": False,
        "hmm_pure": False,
        "ema_rsi_atr": True,
    },
    "ema_rsi_atr_hmm": {
        "label": "EMA + RSI + ATR + HMM",
        "description": "Momentum EMA-RSI-ATR filtrado por régimen HMM (long bull, short bear).",
        "use_hmm_regime": True,
        "hmm_pure": False,
        "ema_rsi_atr": True,
    },
}


def strategy_type_labels() -> dict[str, str]:
    return {k: v["label"] for k, v in STRATEGY_TYPES.items()}


def apply_strategy_type_params(params: dict, strategy_type: str) -> dict:
    cfg = STRATEGY_TYPES.get(strategy_type, STRATEGY_TYPES["confluence"])
    out = params.copy()
    out["use_hmm_regime"] = cfg.get("use_hmm_regime", False)
    out["strategy_type"] = strategy_type
    if cfg.get("nextwave_v2"):
        out["nextwave_v2"] = True
    if cfg.get("ema_rsi_atr"):
        out["ema_rsi_atr"] = True
    return out
