"""
shadow_trader.py — Paper trading paralelo al bot real
Opera siempre en background para comparar params actuales vs candidatos
Soporta long y short simulados (sin órdenes reales).
"""
import uuid
import logging
from datetime import datetime
from bot.database import (save_trade, get_open_trade, close_trade,
                          compute_metrics, get_recent_trades, update_trade_stop_loss)
from bot.live_signals import get_trading_signal, use_trailing_exit
from bot.order_manager import (
    check_exit_conditions, calc_trade_pnl, compute_trailing_stop, trade_side,
)
from bot.style_runtime import get_runtime
from bot.pairs import calc_order_capital, can_open_new_trade

logger = logging.getLogger(__name__)


def _close_shadow_trade(open_trade, price, exit_reason, symbol):
    entry = open_trade["entry_price"]
    qty = open_trade["quantity"]
    side = trade_side(open_trade)
    pnl_usdt, pnl_pct = calc_trade_pnl(entry, price, qty, side)
    if close_trade(open_trade["trade_id"], price, exit_reason, pnl_usdt, pnl_pct):
        emoji = "✅" if pnl_usdt > 0 else "❌"
        label = side.upper()
        logger.info(
            f"📋 [SHADOW][{symbol}] CLOSE {label} {exit_reason} @ {price:.2f} | "
            f"PnL {pnl_usdt:+.2f} USDT ({pnl_pct:+.2%}) {emoji}"
        )


def _open_shadow_trade(state, sc, symbol, side: str) -> dict:
    rt = get_runtime()
    price = state["price"]
    trade_id = f"shadow_{uuid.uuid4().hex[:8]}"
    if side == "short":
        sl, tp = state["short_sl"], state["short_tp"]
    else:
        sl, tp = state["long_sl"], state["long_tp"]

    return {
        "trade_id":    trade_id,
        "mode":        "shadow",
        "side":        side,
        "symbol":      symbol,
        "timeframe":   rt.timeframe,
        "entry_time":  datetime.utcnow(),
        "entry_price": price,
        "exit_time":   None,
        "exit_price":  None,
        "exit_reason": None,
        "quantity":    calc_order_capital("shadow") / price,
        "pnl_usdt":    None,
        "pnl_pct":     None,
        "stop_loss":   sl,
        "take_profit": tp,
        "score_bull":  sc["score_bull"],
        "score_bear":  sc["score_bear"],
        "trail_level": state["trail_level"],
        "params_id":   None,
        "trading_style": rt.style,
    }


def process_shadow_signal(state: dict, params: dict,
                           last_long_bar: int | None,
                           last_short_bar: int | None,
                           current_bar: int,
                           symbol: str) -> tuple[int | None, int | None]:
    """
    Simula trades shadow sin ejecutar órdenes reales.
    Devuelve (nuevo last_long_bar, nuevo last_short_bar); None = sin cambio.
    """
    open_trade = get_open_trade(mode="shadow", symbol=symbol)
    price = state["price"]
    sc = state["score"]
    trail_lv = state["trail_level"]
    trail_dir = state["trail_dir"]
    atr_val = state["atr"]
    new_long = None
    new_short = None

    signal = get_trading_signal(
        state, params, last_long_bar, last_short_bar,
        current_bar, open_trade)

    # ── Gestionar posición abierta (trail + salidas) ──────
    if open_trade:
        side = trade_side(open_trade)
        if use_trailing_exit(params):
            new_sl = compute_trailing_stop(trail_lv, atr_val, side)
            old_sl = open_trade["stop_loss"]
            should_update = (
                (side == "short" and new_sl < old_sl) or
                (side == "long" and new_sl > old_sl)
            )
            if should_update:
                update_trade_stop_loss(open_trade["trade_id"], new_sl)
                open_trade["stop_loss"] = new_sl

        exit_reason = check_exit_conditions(
            price, open_trade, trail_lv, trail_dir, score=sc, params=params)

        if exit_reason:
            _close_shadow_trade(open_trade, price, exit_reason, symbol)
            return new_long, new_short

    open_trade = get_open_trade(mode="shadow", symbol=symbol)
    has_position = open_trade is not None

    if signal == "long" and not has_position:
        ok, reason = can_open_new_trade("shadow", symbol)
        if not ok:
            logger.debug(f"[SHADOW][{symbol}] Long ignorado: {reason}")
        else:
            trade = _open_shadow_trade(state, sc, symbol, "long")
            save_trade(trade)
            logger.info(
                f"📋 [SHADOW][{symbol}] OPEN LONG @ {price:.2f} | "
                f"SL {state['long_sl']:.2f} | TP {state['long_tp']:.2f}"
            )
            new_long = current_bar

    elif signal == "short" and not has_position:
        ok, reason = can_open_new_trade("shadow", symbol)
        if not ok:
            logger.debug(f"[SHADOW][{symbol}] Short ignorado: {reason}")
        else:
            trade = _open_shadow_trade(state, sc, symbol, "short")
            save_trade(trade)
            logger.info(
                f"📋 [SHADOW][{symbol}] OPEN SHORT @ {price:.2f} | "
                f"SL {state['short_sl']:.2f} | TP {state['short_tp']:.2f}"
            )
            new_short = current_bar

    return new_long, new_short


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
