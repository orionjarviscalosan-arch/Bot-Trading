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
}


def strategy_type_labels() -> dict[str, str]:
    return {k: v["label"] for k, v in STRATEGY_TYPES.items()}


def apply_strategy_type_params(params: dict, strategy_type: str) -> dict:
    cfg = STRATEGY_TYPES.get(strategy_type, STRATEGY_TYPES["confluence"])
    out = params.copy()
    out["use_hmm_regime"] = cfg.get("use_hmm_regime", False)
    out["strategy_type"] = strategy_type
    return out
