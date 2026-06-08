"""
order_manager.py — Gestión de órdenes en Binance Spot
Long-only: BUY BTC / SELL BTC
"""
import ccxt
import logging
import math
from datetime import datetime
from bot.data_fetcher import get_exchange, get_min_order_size
from config import POSITION_SIZE_PCT, MAX_CAPITAL_USDT, MIN_ORDER_USDT

logger = logging.getLogger(__name__)


def round_down(value: float, decimals: int) -> float:
    factor = 10 ** decimals
    return math.floor(value * factor) / factor


def calc_quantity(usdt_amount: float, price: float,
                  symbol: str = "BTC/USDT") -> float:
    """Calcula la cantidad de BTC a comprar dado un monto USDT"""
    limits   = get_min_order_size(symbol)
    decimals = limits.get("precision", 5)
    qty      = usdt_amount / price
    qty      = round_down(qty, decimals)
    if qty < limits["min_amount"]:
        logger.warning(f"Cantidad {qty} BTC por debajo del mínimo {limits['min_amount']}")
        return 0.0
    if qty * price < limits["min_cost"]:
        logger.warning(f"Orden {qty*price:.2f} USDT por debajo del mínimo {limits['min_cost']}")
        return 0.0
    return qty


def place_market_buy(symbol: str, quote_balance: float,
                     stop_loss: float, take_profit: float,
                     rr_ratio: float = 2.0,
                     capital_to_use: float | None = None) -> dict | None:
    """
    Abre una posición long en el par indicado.
    Devuelve el trade dict o None si falla.
    """
    ex = get_exchange()
    base = symbol.split("/")[0]
    quote = symbol.split("/")[1]

    if capital_to_use is None:
        capital_to_use = min(
            quote_balance * POSITION_SIZE_PCT,
            MAX_CAPITAL_USDT * POSITION_SIZE_PCT,
        )
    else:
        capital_to_use = min(capital_to_use, quote_balance)

    if capital_to_use < MIN_ORDER_USDT:
        logger.warning(
            f"Capital insuficiente en {symbol}: "
            f"{capital_to_use:.2f} {quote} < mínimo {MIN_ORDER_USDT}")
        return None

    ticker = ex.fetch_ticker(symbol)
    price  = float(ticker["last"])

    qty = calc_quantity(capital_to_use, price, symbol)
    if qty == 0:
        return None

    try:
        order = ex.create_market_buy_order(symbol, qty)
        fill_price = float(order.get("average") or order.get("price") or price)
        fill_qty   = float(order.get("filled")  or qty)
        cost       = fill_price * fill_qty

        sl_distance = fill_price - stop_loss
        actual_sl   = fill_price - sl_distance
        actual_tp   = fill_price + sl_distance * rr_ratio

        logger.info(f"✅ BUY {fill_qty:.6f} {base} @ {fill_price:.2f} {quote}")
        logger.info(f"   SL: {actual_sl:.2f}  TP: {actual_tp:.2f}  R:R {rr_ratio}x")

        return {
            "order_id":    order["id"],
            "side":        "long",
            "quantity":    fill_qty,
            "entry_price": fill_price,
            "cost_usdt":   cost,
            "stop_loss":   actual_sl,
            "take_profit": actual_tp,
            "entry_time":  datetime.utcnow(),
        }

    except ccxt.InsufficientFunds as e:
        logger.error(f"Fondos insuficientes: {e}")
        return None
    except ccxt.ExchangeError as e:
        logger.error(f"Error de exchange en BUY: {e}")
        return None


def place_market_sell(symbol: str, base_quantity: float,
                      reason: str = "signal") -> dict | None:
    """Cierra la posición long vendiendo el activo base."""
    ex = get_exchange()
    base = symbol.split("/")[0]
    quote = symbol.split("/")[1]

    if base_quantity <= 0:
        logger.warning(f"Cantidad {base} a vender es cero o negativa")
        return None

    try:
        order = ex.create_market_sell_order(symbol, base_quantity)
        fill_price = float(order.get("average") or order.get("price") or 0)
        fill_qty   = float(order.get("filled")  or base_quantity)

        logger.info(f"✅ SELL {fill_qty:.6f} {base} @ {fill_price:.2f} {quote} ({reason})")

        return {
            "order_id":   order["id"],
            "exit_price": fill_price,
            "quantity":   fill_qty,
            "exit_time":  datetime.utcnow(),
            "exit_reason": reason,
        }

    except ccxt.InsufficientFunds as e:
        logger.error(f"Fondos insuficientes en SELL: {e}")
        return None
    except ccxt.ExchangeError as e:
        logger.error(f"Error de exchange en SELL: {e}")
        return None


def check_exit_conditions(current_price: float, position: dict,
                          trail_level: float, trail_dir: int,
                          score: dict | None = None,
                          params: dict | None = None) -> str | None:
    """
    Verifica si se deben activar SL, TP, Trail Flip o cierre por score bajista.
    Devuelve el motivo de salida o None si no hay salida.
    """
    sl = position.get("stop_loss", 0)
    tp = position.get("take_profit", 999999)

    if current_price <= sl:
        return "sl"
    if current_price >= tp:
        return "tp"
    if trail_dir == -1:
        return "trail_flip"
    if score and params:
        threshold = params.get("score_threshold", 68)
        if score.get("score_bear", 0) >= threshold:
            return "score_bear"
    return None


def update_stop_loss(position: dict, new_sl: float) -> dict:
    """Actualiza el stop loss si el trail se movió a favor."""
    current_sl = position.get("stop_loss", 0)
    if new_sl > current_sl:
        position["stop_loss"] = new_sl
        logger.info(f"📈 Trail SL actualizado: {current_sl:.2f} → {new_sl:.2f}")
    return position
