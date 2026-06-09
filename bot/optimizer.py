"""
optimizer.py — Auto-optimización cada 30 días
Prueba nuevos parámetros en backtest, promueve si mejoran métricas del set activo
"""
import logging
import itertools
from datetime import datetime
from bot.backtest import run_simulation
from bot.database import (get_active_params, get_active_param_metrics, save_param_set,
                          get_recent_trades, compute_metrics, get_state, set_state)
from bot.signal_engine import compute_all, get_signal
from bot.order_manager import check_exit_conditions, calc_trade_pnl, compute_trailing_stop
from bot.data_fetcher import fetch_ohlcv
from config import OPTIMIZER, PARAM_GRID, SIGNAL_PARAMS, POSITION_SIZE_PCT

logger = logging.getLogger(__name__)


def run_simulation_legacy(df_4h, df_1d, params: dict) -> dict:
    """Compatibilidad: delega al motor de backtest unificado."""
    result = run_simulation(df_4h, df_1d, params, strategy_type="confluence")
    return result.get("metrics", {})


def find_best_params(df_4h, df_1d) -> tuple[dict, dict]:
    """
    Grid search sobre PARAM_GRID.
    Devuelve (best_params, best_metrics).
    """
    current = get_active_params() or SIGNAL_PARAMS.copy()
    active_metrics = get_active_param_metrics()
    best_calmar = active_metrics.get("calmar_ratio", 0) or 0
    best_params  = current.copy()
    best_metrics = {}

    keys   = list(PARAM_GRID.keys())
    values = list(PARAM_GRID.values())
    combos = list(itertools.product(*values))

    logger.info(f"Grid search: {len(combos)} combinaciones")

    for combo in combos:
        candidate = current.copy()
        for k, v in zip(keys, combo):
            candidate[k] = v

        try:
            metrics = run_simulation_legacy(df_4h, df_1d, candidate)
        except Exception as e:
            logger.debug(f"Combo falló: {e}")
            continue

        pf = metrics.get("profit_factor", 0)
        cm = metrics.get("calmar_ratio",  0)
        nt = metrics.get("total_trades",  0)

        if (pf >= OPTIMIZER["min_profit_factor"] and
                nt >= OPTIMIZER["min_trades"] and
                cm > best_calmar):
            best_calmar  = cm
            best_params  = candidate.copy()
            best_metrics = metrics
            logger.info(f"Nuevo mejor: Calmar {cm:.3f}  PF {pf:.3f}  Trades {nt}")

    return best_params, best_metrics


def should_run_optimization() -> bool:
    """¿Es hora de optimizar?"""
    last_opt = get_state("last_optimization")
    if not last_opt:
        return False
    last_dt = datetime.fromisoformat(last_opt)
    days_since = (datetime.utcnow() - last_dt).days
    return days_since >= OPTIMIZER["run_every_days"]


def run_optimization(symbol: str, timeframe: str, htf: str):
    """Punto de entrada de la optimización periódica."""
    logger.info("=== Iniciando optimización de parámetros ===")
    set_state("last_optimization", datetime.utcnow().isoformat())

    try:
        df_4h = fetch_ohlcv(symbol, timeframe, limit=1000)
        df_1d = fetch_ohlcv(symbol, htf,       limit=500)

        best_params, best_metrics = find_best_params(df_4h, df_1d)
        current_params = get_active_params() or SIGNAL_PARAMS.copy()
        active_metrics = get_active_param_metrics()
        current_calmar = active_metrics.get("calmar_ratio", 0) or 0

        if (best_metrics and
                best_metrics.get("calmar_ratio", 0) > current_calmar * 1.05 and
                best_metrics.get("profit_factor", 0) >= OPTIMIZER["min_profit_factor"] and
                best_metrics.get("total_trades",  0) >= OPTIMIZER["min_trades"]):

            set_state("candidate_params",  best_params)
            set_state("candidate_metrics", best_metrics)
            set_state("candidate_since",   datetime.utcnow().isoformat())
            logger.info(
                f"Candidato guardado: Calmar {best_metrics.get('calmar_ratio'):.3f} "
                f"(actual {current_calmar:.3f})")
            return best_params, best_metrics

        logger.info("No se encontró mejora — manteniendo parámetros actuales")
        return current_params, {}

    except Exception as e:
        logger.error(f"Error en optimización: {e}")
        return get_active_params() or SIGNAL_PARAMS.copy(), {}


def maybe_promote_candidate():
    """
    Tras shadow_test_days, promueve el candidato si supera al set activo
    en métricas de backtest (comparación homogénea).
    """
    candidate = get_state("candidate_params")
    since_str = get_state("candidate_since")
    if not candidate or not since_str:
        return

    since = datetime.fromisoformat(since_str)
    days_tested = (datetime.utcnow() - since).days

    if days_tested < OPTIMIZER["shadow_test_days"]:
        logger.debug(
            f"Candidato en evaluación: {days_tested}/{OPTIMIZER['shadow_test_days']} días")
        return

    candidate_metrics = get_state("candidate_metrics", {})
    active_metrics    = get_active_param_metrics()

    candidate_calmar = candidate_metrics.get("calmar_ratio", 0)
    active_calmar    = active_metrics.get("calmar_ratio", 0)
    candidate_pf     = candidate_metrics.get("profit_factor", 0)
    active_pf        = active_metrics.get("profit_factor", 0)

    if (candidate_calmar > active_calmar * 1.1 and
            candidate_pf >= active_pf):
        save_param_set(candidate, source="optimized", metrics=candidate_metrics)
        set_state("params_style", get_state("active_trading_style") or get_state("trading_style"))
        set_state("candidate_params",  None)
        set_state("candidate_metrics", None)
        set_state("candidate_since",   None)
        logger.info(f"✅ Candidato promovido a activo (Calmar {candidate_calmar:.3f})")
        return True

    logger.info("Candidato no supera al set activo — descartado")
    set_state("candidate_params",  None)
    set_state("candidate_metrics", None)
    set_state("candidate_since",   None)
    return False
