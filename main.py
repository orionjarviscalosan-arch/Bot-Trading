"""
main.py — Orquestador principal del Nextwaves Bot
Conecta todos los módulos y gestiona el ciclo de vida
"""
import os
import uuid
import logging
import logging.handlers
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import config as cfg
from bot.database      import (init_db, get_active_params, save_param_set,
                                save_signal, save_trade, get_open_trade,
                                close_trade, get_state, set_state,
                                get_recent_trades, update_trade_stop_loss)
from bot.data_fetcher  import (fetch_ohlcv, fetch_balance, fetch_base_balance,
                                fetch_current_price)
from bot.signal_engine import compute_all, get_signal
from bot.order_manager import place_market_buy, place_market_sell, check_exit_conditions
from bot.risk_manager  import RiskManager
from bot.shadow_trader import process_shadow_signal, get_shadow_metrics
from bot.optimizer     import should_run_optimization, run_optimization, maybe_promote_candidate
from bot.scheduler_utils import candle_close_trigger, candle_close_description
from bot.startup_check import run_startup_checks
from bot.telegram_notifier import (notify_start, notify_signal, notify_trade_open,
                                    notify_trade_close, notify_trail_update,
                                    notify_kill_switch, notify_optimization,
                                    notify_daily_summary)

# ── LOGGING ───────────────────────────────────────────────
os.makedirs("data", exist_ok=True)
handler = logging.handlers.RotatingFileHandler(
    cfg.LOG_FILE, maxBytes=5*1024*1024, backupCount=3)
logging.basicConfig(
    level=getattr(logging, cfg.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[handler, logging.StreamHandler()])
logger = logging.getLogger("nextwaves_bot")

# ── ESTADO GLOBAL ─────────────────────────────────────────
risk_manager = RiskManager(cfg.MAX_CAPITAL_USDT)


def get_params() -> dict:
    """Obtiene los parámetros activos de la DB o usa los defaults"""
    params = get_active_params()
    if params is None:
        params = cfg.SIGNAL_PARAMS.copy()
        save_param_set(params, source="initial")
    return params


def _persist_bar_state(prefix: str, current_bar: int, last_long_bar: int | None):
    set_state(f"{prefix}current_bar", current_bar)
    set_state(f"{prefix}last_long_bar", last_long_bar)


def _load_bar_state(prefix: str) -> tuple[int, int | None]:
    current = get_state(f"{prefix}current_bar", 0)
    last_long = get_state(f"{prefix}last_long_bar")
    return current, last_long


def on_candle_close():
    """
    Se ejecuta al cierre de cada vela configurada.
    Corazón del bot — evalúa señales y gestiona posiciones.
    """
    mode   = cfg.BOT_MODE
    symbol = cfg.SYMBOL
    params = get_params()

    # ── Shadow (siempre activo, lógica independiente) ─────
    shadow_bar, shadow_last = _load_bar_state("shadow_")
    shadow_bar += 1
    logger.info(f"── Vela {cfg.TIMEFRAME} cerrada (shadow bar #{shadow_bar}) ──")

    if risk_manager.is_killed():
        logger.warning("Bot detenido por kill switch. Operación manual requerida.")
        return

    equity = fetch_balance("USDT") if mode == "live" else cfg.MAX_CAPITAL_USDT
    should_stop, reason = risk_manager.check_kill_switch(equity, mode)
    if should_stop:
        notify_kill_switch(reason)
        return

    try:
        df_4h = fetch_ohlcv(symbol, cfg.TIMEFRAME, limit=cfg.CANDLES_LB)
        df_1d = fetch_ohlcv(symbol, cfg.HTF,       limit=500)
    except Exception as e:
        logger.error(f"Error al obtener datos: {e}")
        return

    try:
        state = compute_all(df_4h, df_1d, params)
    except Exception as e:
        logger.error(f"Error en signal_engine: {e}")
        return

    sc    = state["score"]
    price = state["price"]

    signal_rec = {
        "timestamp":    state["timestamp"],
        "symbol":       symbol,
        "direction":    "none",
        "score_bull":   sc["score_bull"],
        "score_bear":   sc["score_bear"],
        "trail_dir":    sc["trail_dir"],
        "htf_bull":     sc["htf_bull"],
        "htf_bear":     sc["htf_bear"],
        "struct_bias":  sc["struct_bias"],
        "regime_ok":    sc["regime_ok"],
        "momentum_raw": sc["momentum_raw"],
        "acted_on":     False,
    }

    new_shadow_last = process_shadow_signal(state, params, shadow_last, shadow_bar)
    if new_shadow_last is not None:
        shadow_last = new_shadow_last
    _persist_bar_state("shadow_", shadow_bar, shadow_last)

    # ── Modo activo: paper o live (shadow NO duplica aquí) ─
    if mode in ("live", "paper"):
        current_bar, last_long_bar = _load_bar_state("")
        current_bar += 1
        logger.info(f"── Modo {mode.upper()} bar #{current_bar} ──")

        open_trade = get_open_trade(mode=mode)
        has_pos    = open_trade is not None

        if has_pos:
            _manage_open_position(open_trade, state, price, mode, symbol, params)

        open_trade = get_open_trade(mode=mode)
        has_pos    = open_trade is not None

        signal = get_signal(state, params, last_long_bar, current_bar, has_pos)
        signal_rec["direction"] = signal

        if signal == "close" and has_pos and open_trade:
            exit_reason = check_exit_conditions(
                price, open_trade, state["trail_level"], state["trail_dir"],
                score=sc, params=params) or "trail_flip"
            signal_rec["acted_on"] = True
            _close_position(open_trade, price, exit_reason, mode, symbol)

        elif signal == "long" and not has_pos:
            signal_rec["acted_on"] = True
            logger.info(
                f"🟢 SEÑAL LONG | Score Bull: {sc['score_bull']} | Price: {price:.2f}")
            notify_signal(sc, price, "long")
            if _open_long(state, symbol, mode, params):
                last_long_bar = current_bar

        _persist_bar_state("", current_bar, last_long_bar)
    else:
        signal = get_signal(state, params, shadow_last, shadow_bar,
                            get_open_trade(mode="shadow") is not None)
        signal_rec["direction"] = signal

    save_signal(signal_rec)
    maybe_promote_candidate()

    logger.info(
        f"   Score: Bull {sc['score_bull']} / Bear {sc['score_bear']} | "
        f"Trail: {'↑' if sc['trail_dir'] == 1 else '↓'} | "
        f"HTF: {'Bull' if sc['htf_bull'] else 'Bear' if sc['htf_bear'] else 'Neutro'}")


def run_scheduled_optimization():
    """Job separado para optimización — no bloquea el ciclo de vela."""
    if not should_run_optimization():
        return
    symbol = cfg.SYMBOL
    params = get_params()
    logger.info("Iniciando optimización de parámetros (job programado)...")
    new_params, metrics = run_optimization(symbol, cfg.TIMEFRAME, cfg.HTF)
    if metrics:
        notify_optimization(params, new_params, metrics)


def _manage_open_position(open_trade: dict, state: dict, price: float,
                           mode: str, symbol: str, params: dict):
    """Gestiona una posición abierta: actualiza trail, verifica SL/TP"""
    trail_lv  = state["trail_level"]
    trail_dir = state["trail_dir"]
    atr_val   = state["atr"]
    sc        = state["score"]

    old_sl = open_trade["stop_loss"]
    new_sl = trail_lv - atr_val * 0.2
    if new_sl > old_sl:
        if update_trade_stop_loss(open_trade["trade_id"], new_sl):
            if mode == "live":
                notify_trail_update(old_sl, new_sl)
            open_trade["stop_loss"] = new_sl

    exit_reason = check_exit_conditions(
        price, open_trade, trail_lv, trail_dir, score=sc, params=params)
    if exit_reason:
        _close_position(open_trade, price, exit_reason, mode, symbol)


def _open_long(state: dict, symbol: str, mode: str, params: dict) -> bool:
    """Abre una posición long. Devuelve True si se abrió correctamente."""
    sc = state["score"]

    if mode == "live":
        usdt_balance = fetch_balance("USDT")
        result = place_market_buy(
            symbol, usdt_balance, state["long_sl"], state["long_tp"],
            rr_ratio=params.get("rr_ratio", cfg.SIGNAL_PARAMS["rr_ratio"]))
        if not result:
            return False
        trade = {
            "trade_id":    f"live_{uuid.uuid4().hex[:8]}",
            "mode":        "live",
            "side":        "long",
            "symbol":      symbol,
            "timeframe":   cfg.TIMEFRAME,
            "entry_time":  result["entry_time"],
            "entry_price": result["entry_price"],
            "exit_time":   None,
            "exit_price":  None,
            "exit_reason": None,
            "quantity":    result["quantity"],
            "pnl_usdt":    None,
            "pnl_pct":     None,
            "stop_loss":   result["stop_loss"],
            "take_profit": result["take_profit"],
            "score_bull":  sc["score_bull"],
            "score_bear":  sc["score_bear"],
            "trail_level": state["trail_level"],
            "params_id":   None,
        }
        save_trade(trade)
        notify_trade_open(result["entry_price"], result["stop_loss"],
                          result["take_profit"], result["quantity"], mode)
        return True

    if mode == "paper":
        entry = state["price"]
        qty = (cfg.MAX_CAPITAL_USDT * cfg.POSITION_SIZE_PCT) / entry
        trade = {
            "trade_id":    f"paper_{uuid.uuid4().hex[:8]}",
            "mode":        "paper",
            "side":        "long",
            "symbol":      symbol,
            "timeframe":   cfg.TIMEFRAME,
            "entry_time":  datetime.utcnow(),
            "entry_price": entry,
            "exit_time":   None,
            "exit_price":  None,
            "exit_reason": None,
            "quantity":    qty,
            "pnl_usdt":    None,
            "pnl_pct":     None,
            "stop_loss":   state["long_sl"],
            "take_profit": state["long_tp"],
            "score_bull":  sc["score_bull"],
            "score_bear":  sc["score_bear"],
            "trail_level": state["trail_level"],
            "params_id":   None,
        }
        save_trade(trade)
        notify_trade_open(entry, state["long_sl"], state["long_tp"], qty, mode)
        return True

    return False


def _close_position(open_trade: dict, price: float, reason: str,
                    mode: str, symbol: str):
    """Cierra la posición abierta"""
    if open_trade.get("exit_time"):
        return

    entry    = open_trade["entry_price"]
    qty      = open_trade["quantity"]
    pnl_usdt = (price - entry) * qty
    pnl_pct  = (price - entry) / entry

    if mode == "live":
        base_bal = fetch_base_balance(symbol)
        if base_bal > 0:
            place_market_sell(symbol, min(qty, base_bal), reason)

    if not close_trade(open_trade["trade_id"], price, reason, pnl_usdt, pnl_pct):
        logger.debug(f"Trade {open_trade['trade_id']} ya estaba cerrado")
        return

    notify_trade_close(entry, price, pnl_usdt, pnl_pct, reason, mode)
    logger.info(
        f"{'✅' if pnl_usdt > 0 else '❌'} Trade cerrado ({reason}) | "
        f"PnL: {pnl_usdt:+.2f} USDT ({pnl_pct:+.2%})")


def daily_summary():
    """Resumen diario enviado por Telegram"""
    mode   = cfg.BOT_MODE
    report_mode = mode if mode in ("live", "paper") else "shadow"
    trades = get_recent_trades(report_mode, days=1)
    today_pnl  = sum(t.get("pnl_usdt", 0) for t in trades
                    if t.get("pnl_usdt") is not None)
    wins   = sum(1 for t in trades if (t.get("pnl_usdt") or 0) > 0)
    wr     = wins / len(trades) if trades else 0
    equity = fetch_balance("USDT") if mode == "live" else cfg.MAX_CAPITAL_USDT
    notify_daily_summary(equity, today_pnl, len(trades), wr)

    shadow_m = get_shadow_metrics(30)
    if shadow_m.get("total_trades", 0) > 0:
        logger.info(
            f"Shadow 30d: PF {shadow_m.get('profit_factor'):.3f} | "
            f"WR {shadow_m.get('win_rate'):.1%} | "
            f"Trades {shadow_m.get('total_trades')}")


def check_price_monitor():
    """
    Monitoreo de precio cada 5 minutos.
    Solo para modos live/paper — shadow usa cierre de vela.
    """
    mode = cfg.BOT_MODE
    if mode not in ("live", "paper"):
        return

    open_trade = get_open_trade(mode=mode)
    if not open_trade:
        return

    try:
        price = fetch_current_price(cfg.SYMBOL)
        sl    = open_trade.get("stop_loss", 0)
        tp    = open_trade.get("take_profit", 999999)

        if price <= sl:
            logger.warning(f"SL tocado ({price:.2f} ≤ {sl:.2f}) — cerrando")
            _close_position(open_trade, price, "sl", mode, cfg.SYMBOL)
        elif price >= tp:
            logger.info(f"TP alcanzado ({price:.2f} ≥ {tp:.2f}) — cerrando")
            _close_position(open_trade, price, "tp", mode, cfg.SYMBOL)
    except Exception as e:
        logger.error(f"Error en monitoreo de precio: {e}")


def main():
    logger.info("=" * 60)
    logger.info("  NEXTWAVES BOT — Iniciando")
    logger.info(f"  Modo: {cfg.BOT_MODE.upper()}")
    logger.info(f"  Par:  {cfg.SYMBOL} {cfg.TIMEFRAME}")
    logger.info("=" * 60)

    init_db()

    if get_state("last_optimization") is None:
        set_state("last_optimization", datetime.utcnow().isoformat())
        logger.info("Optimización diferida — próxima ejecución en 30 días")

    run_startup_checks()

    params = get_params()
    logger.info(
        f"Parámetros activos: score={params['score_threshold']} | "
        f"trail={params['trail_mult']} | rr={params['rr_ratio']}")

    notify_start(cfg.BOT_MODE, cfg.SYMBOL)

    scheduler = BlockingScheduler(timezone="UTC")

    scheduler.add_job(
        on_candle_close,
        candle_close_trigger(cfg.TIMEFRAME),
        id="candle_close",
        name=f"Cierre vela {cfg.TIMEFRAME}",
        misfire_grace_time=120,
    )

    scheduler.add_job(
        check_price_monitor,
        "interval", minutes=5,
        id="price_monitor", name="Monitor precio",
    )

    scheduler.add_job(
        daily_summary,
        CronTrigger(hour=23, minute=55, timezone="UTC"),
        id="daily_summary", name="Resumen diario",
    )

    scheduler.add_job(
        run_scheduled_optimization,
        CronTrigger(hour=3, minute=0, timezone="UTC"),
        id="optimization", name="Optimización diaria (si toca)",
    )

    logger.info("Scheduler iniciado.")
    logger.info(f"Cierre de vela: {candle_close_description(cfg.TIMEFRAME)}")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot detenido por el usuario")
        scheduler.shutdown()


if __name__ == "__main__":
    main()
