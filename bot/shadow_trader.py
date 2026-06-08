"""
shadow_trader.py — Paper trading paralelo al bot real
Opera siempre en background para comparar params actuales vs candidatos
"""
import uuid
import logging
from datetime import datetime
from bot.database import (save_trade, get_open_trade, close_trade,
                          compute_metrics, get_recent_trades, update_trade_stop_loss)
from bot.signal_engine import get_signal
from bot.order_manager import check_exit_conditions
from config import SYMBOL, TIMEFRAME, SHADOW_CAPITAL, POSITION_SIZE_PCT, TRADING_STYLE

logger = logging.getLogger(__name__)


def process_shadow_signal(state: dict, params: dict,
                           last_long_bar: int | None,
                           current_bar: int) -> int | None:
    """
    Simula trades shadow sin ejecutar órdenes reales.
    Devuelve el nuevo last_long_bar si abrió posición, None si no cambió.
    """
    open_trade = get_open_trade(mode="shadow")
    has_position = open_trade is not None

    signal = get_signal(state, params, last_long_bar, current_bar, has_position)
    price  = state["price"]
    sc     = state["score"]
    trail_lv  = state["trail_level"]
    trail_dir = state["trail_dir"]
    atr_val   = state["atr"]

    # ── Gestionar posición abierta (trail + salidas) ──────
    if has_position and open_trade:
        old_sl = open_trade["stop_loss"]
        new_sl = trail_lv - atr_val * 0.2
        if new_sl > old_sl:
            update_trade_stop_loss(open_trade["trade_id"], new_sl)
            open_trade["stop_loss"] = new_sl

        exit_reason = check_exit_conditions(
            price, open_trade, trail_lv, trail_dir, score=sc, params=params)

        if exit_reason:
            entry    = open_trade["entry_price"]
            qty      = open_trade["quantity"]
            pnl_usdt = (price - entry) * qty
            pnl_pct  = (price - entry) / entry
            if close_trade(open_trade["trade_id"], price, exit_reason, pnl_usdt, pnl_pct):
                emoji = "✅" if pnl_usdt > 0 else "❌"
                logger.info(
                    f"📋 [SHADOW] CLOSE {exit_reason} @ {price:.2f} | "
                    f"PnL {pnl_usdt:+.2f} USDT ({pnl_pct:+.2%}) {emoji}"
                )
            return None

    # ── ABRIR POSICIÓN SHADOW ─────────────────────────────
    if signal == "long" and not has_position:
        trade_id = f"shadow_{uuid.uuid4().hex[:8]}"
        trade = {
            "trade_id":    trade_id,
            "mode":        "shadow",
            "side":        "long",
            "symbol":      SYMBOL,
            "timeframe":   TIMEFRAME,
            "entry_time":  datetime.utcnow(),
            "entry_price": price,
            "exit_time":   None,
            "exit_price":  None,
            "exit_reason": None,
            "quantity":    (SHADOW_CAPITAL * POSITION_SIZE_PCT) / price,
            "pnl_usdt":    None,
            "pnl_pct":     None,
            "stop_loss":   state["long_sl"],
            "take_profit": state["long_tp"],
            "score_bull":  sc["score_bull"],
            "score_bear":  sc["score_bear"],
            "trail_level": state["trail_level"],
            "params_id":   None,
            "trading_style": cfg.TRADING_STYLE,
        }
        save_trade(trade)
        logger.info(
            f"📋 [SHADOW] OPEN LONG @ {price:.2f} | "
            f"SL {state['long_sl']:.2f} | TP {state['long_tp']:.2f}"
        )
        return current_bar

    return None


def get_shadow_metrics(days: int = 90) -> dict:
    """Métricas del shadow trading de los últimos N días"""
    trades = get_recent_trades(mode="shadow", days=days)
    return compute_metrics(trades)


def compare_param_sets(params_a: dict, params_b: dict,
                       shadow_days: int = 14) -> dict:
    """
    Compara dos sets de parámetros usando métricas shadow recientes.
    Nota: requiere shadow paralelo por set para comparación exacta;
    aquí compara el set activo vs métricas del candidato almacenadas en bot_state.
    """
    from bot.database import get_state

    metrics_a = get_shadow_metrics(shadow_days)
    metrics_b = get_state("candidate_metrics", {})

    calmar_a = metrics_a.get("calmar_ratio", 0)
    calmar_b = metrics_b.get("calmar_ratio", 0)

    winner = "b" if calmar_b > calmar_a else "a"
    return {
        "winner":    winner,
        "metrics_a": metrics_a,
        "metrics_b": metrics_b,
    }
