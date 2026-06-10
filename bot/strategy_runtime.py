"""
strategy_runtime.py — Estrategia guardada activa para operación en tiempo real
"""
from __future__ import annotations

import logging

from bot.database import get_strategy, get_state, set_state, save_param_set
from bot.strategy_types import apply_strategy_type_params, STRATEGY_TYPES
from bot.style_runtime import get_runtime, _build, _reschedule_jobs, _reset_bar_counters

logger = logging.getLogger(__name__)


def get_active_strategy_id() -> int | None:
    sid = get_state("active_strategy_id")
    return int(sid) if sid is not None else None


def get_active_strategy_meta() -> dict | None:
    sid = get_active_strategy_id()
    if not sid:
        return None
    row = get_strategy(strategy_id=sid)
    if not row:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "strategy_type": row["strategy_type"],
        "timeframe": row.get("timeframe"),
        "htf": row.get("htf"),
        "symbol": row.get("symbol"),
    }


def apply_operating_strategy(strategy_id: int | None) -> str:
    """Activa una estrategia SQLite para el bot en vivo."""
    from bot import style_runtime

    if strategy_id is None:
        set_state("active_strategy_id", None)
        set_state("active_strategy_name", None)
        set_state("kill_notify_sent", None)
        rt = get_runtime()
        style_runtime.sync_params(rt)
        return "Operación vuelta al estilo base del runtime (sin estrategia guardada)."

    strat = get_strategy(strategy_id=strategy_id)
    if not strat:
        return f"Estrategia id {strategy_id} no encontrada."

    params = apply_strategy_type_params(strat["params"].copy(), strat["strategy_type"])
    cfg = STRATEGY_TYPES.get(strat["strategy_type"], {})
    if cfg.get("ema_rsi_atr"):
        params["ema_rsi_atr"] = True
    if cfg.get("nextwave_v2"):
        params["nextwave_v2"] = True

    save_param_set(params, source=f"strategy_{strategy_id}")
    set_state("active_strategy_id", strategy_id)
    set_state("active_strategy_name", strat["name"])
    set_state("params_style", f"strategy_{strategy_id}")

    rt = get_runtime()
    tf = strat.get("timeframe") or rt.timeframe
    htf = strat.get("htf") or rt.htf
    style_runtime._runtime = _build(rt.style, rt.bot_mode, timeframe=tf, htf=htf)
    _reset_bar_counters()
    _reschedule_jobs(style_runtime._runtime)

    logger.info(
        f"Estrategia activa: «{strat['name']}» ({strat['strategy_type']}) · {tf}/{htf}")
    return (
        f"Estrategia «{strat['name']}» activa.\n"
        f"Tipo: {strat['strategy_type']} · TF {tf} · HTF {htf}\n"
        f"El bot usará estos parámetros en la próxima vela."
    )


def list_strategies_for_ui() -> list[dict]:
    from bot.database import list_strategies
    return list_strategies()
