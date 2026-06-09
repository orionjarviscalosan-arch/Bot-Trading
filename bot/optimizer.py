"""
optimizer.py — Auto-optimización cada 30 días
Prueba nuevos parámetros en backtest, promueve si mejoran métricas del set activo
"""
import logging
import itertools
from datetime import datetime
from bot.database import (get_active_params, get_active_param_metrics, save_param_set,
                          get_recent_trades, compute_metrics, get_state, set_state)
from bot.signal_engine import compute_all, get_signal
from bot.order_manager import check_exit_conditions, calc_trade_pnl, compute_trailing_stop
from bot.data_fetcher import fetch_ohlcv
from config import OPTIMIZER, PARAM_GRID, SIGNAL_PARAMS, POSITION_SIZE_PCT

logger = logging.getLogger(__name__)


def run_simulation(df_4h, df_1d, params: dict) -> dict:
    """
    Simula el backtest de un set de parámetros sobre datos históricos.
    Soporta long y short. Devuelve las métricas del set.
    """
    trades = []
    capital = 10000.0
    pos = None
    last_long = None
    last_short = None
    bar_i = 0
    position_pct = params.get("position_size_pct", POSITION_SIZE_PCT)

    for i in range(300, len(df_4h)):
        chunk_4h = df_4h.iloc[:i + 1]
        chunk_1d = df_1d

        try:
            state = compute_all(chunk_4h, chunk_1d, params)
        except Exception:
            continue

        price = state["price"]
        trail_lv = state["trail_level"]
        trail_dir = state["trail_dir"]
        sc = state["score"]

        open_trade = None
        if pos is not None:
            open_trade = {
                "side": pos["side"],
                "stop_loss": pos["sl"],
                "take_profit": pos["tp"],
            }

        signal = get_signal(state, params, last_long, last_short, bar_i, open_trade)

        if pos is not None:
            exit_reason = check_exit_conditions(
                price, open_trade, trail_lv, trail_dir, score=sc, params=params)

            if exit_reason:
                pnl, _ = calc_trade_pnl(pos["entry"], price, pos["qty"], pos["side"])
                trades.append(pnl)
                pos = None
            else:
                new_sl = compute_trailing_stop(trail_lv, state["atr"], pos["side"])
                if pos["side"] == "short" and new_sl < pos["sl"]:
                    pos["sl"] = new_sl
                elif pos["side"] == "long" and new_sl > pos["sl"]:
                    pos["sl"] = new_sl

        if signal == "long" and pos is None:
            entry = price
            qty = (capital * position_pct) / entry
            pos = {
                "side": "long",
                "entry": entry,
                "sl": state["long_sl"],
                "tp": state["long_tp"],
                "qty": qty,
            }
            last_long = bar_i

        elif signal == "short" and pos is None:
            entry = price
            qty = (capital * position_pct) / entry
            pos = {
                "side": "short",
                "entry": entry,
                "sl": state["short_sl"],
                "tp": state["short_tp"],
                "qty": qty,
            }
            last_short = bar_i

        bar_i += 1

    if pos:
        last_price = df_4h["close"].iloc[-1]
        pnl, _ = calc_trade_pnl(pos["entry"], last_price, pos["qty"], pos["side"])
        trades.append(pnl)

    return compute_metrics([{"pnl_usdt": p} for p in trades])


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
            metrics = run_simulation(df_4h, df_1d, candidate)
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
