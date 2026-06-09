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
from apscheduler.triggers.interval import IntervalTrigger

import config as cfg
from bot.database      import (init_db, get_active_params, save_param_set,
                                save_signal, save_trade, get_open_trade,
                                get_open_trades, close_trade, get_state, set_state,
                                get_recent_trades, update_trade_stop_loss)
from bot.data_fetcher  import (fetch_ohlcv, fetch_balance, fetch_base_balance,
                                fetch_current_price)
from bot.signal_engine import compute_all, get_signal
from bot.order_manager import (place_market_buy, place_market_sell, check_exit_conditions,
                                calc_trade_pnl, compute_trailing_stop, trade_side)
from bot.risk_manager  import RiskManager
from bot.shadow_trader import process_shadow_signal, get_shadow_metrics
from bot.optimizer     import should_run_optimization, run_optimization, maybe_promote_candidate
from bot.scheduler_utils import candle_close_trigger, candle_close_description
from bot.startup_check import run_startup_checks
from bot.style_runtime import init_runtime, get_runtime, set_scheduler, sync_params
from bot.telegram_commands import poll_telegram_commands, init_telegram_offset
from bot.telegram_notifier import (notify_start, notify_signal, notify_trade_open,
                                    notify_trade_close, notify_trail_update,
                                    notify_kill_switch, notify_optimization,
                                    notify_daily_summary, send as tg_send)
from bot.pairs import (
    bar_state_keys, calc_order_capital, can_open_new_trade,
    symbol_quote_asset, unique_quote_assets,
)

# ── LOGGING ───────────────────────────────────────────────
os.makedirs("data", exist_ok=True)
handler = logging.handlers.RotatingFileHandler(
    cfg.LOG_FILE, maxBytes=5*1024*1024, backupCount=3)
logging.basicConfig(
    level=getattr(logging, cfg.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[handler, logging.StreamHandler()])
logger = logging.getLogger("nextwaves_bot")

risk_manager = RiskManager(cfg.MAX_CAPITAL_USDT)


def get_params() -> dict:
    rt = get_runtime()
    sync_params(rt)
    params = get_active_params()
    return params if params else rt.signal_params.copy()


def _persist_bar_state(prefix: str, symbol: str,
                       current_bar: int,
                       last_long_bar: int | None,
                       last_short_bar: int | None = None):
    cur_key, last_long_key, last_short_key = bar_state_keys(prefix, symbol)
    set_state(cur_key, current_bar)
    set_state(last_long_key, last_long_bar)
    set_state(last_short_key, last_short_bar)


def _load_bar_state(prefix: str, symbol: str) -> tuple[int, int | None, int | None]:
    cur_key, last_long_key, last_short_key = bar_state_keys(prefix, symbol)
    current = get_state(cur_key, 0)
    last_long = get_state(last_long_key)
    last_short = get_state(last_short_key)
    return current, last_long, last_short


def _estimate_equity(mode: str) -> float:
    if mode != "live":
        return cfg.MAX_CAPITAL_USDT
    total = 0.0
    for quote in unique_quote_assets():
        total += fetch_balance(quote)
    return total if total > 0 else cfg.MAX_CAPITAL_USDT


def _process_symbol_candle_close(symbol: str, rt, mode: str, params: dict):
    shadow_bar, shadow_last_long, shadow_last_short = _load_bar_state("shadow_", symbol)
    shadow_bar += 1

    try:
        df_ltf = fetch_ohlcv(symbol, rt.timeframe, limit=rt.candles_lb)
        df_htf = fetch_ohlcv(symbol, rt.htf,       limit=500)
    except Exception as e:
        logger.error(f"[{symbol}] Error al obtener datos: {e}")
        return

    try:
        state = compute_all(df_ltf, df_htf, params)
    except Exception as e:
        logger.error(f"[{symbol}] Error en signal_engine: {e}")
        return

    sc    = state["score"]
    price = state["price"]

    signal_rec = {
        "timestamp":     state["timestamp"],
        "symbol":        symbol,
        "direction":     "none",
        "score_bull":    sc["score_bull"],
        "score_bear":    sc["score_bear"],
        "trail_dir":     sc["trail_dir"],
        "htf_bull":      sc["htf_bull"],
        "htf_bear":      sc["htf_bear"],
        "struct_bias":   sc["struct_bias"],
        "regime_ok":     sc["regime_ok"],
        "momentum_raw":  sc["momentum_raw"],
        "acted_on":      False,
        "trading_style": rt.style,
    }

    new_long, new_short = process_shadow_signal(
        state, params, shadow_last_long, shadow_last_short, shadow_bar, symbol)
    if new_long is not None:
        shadow_last_long = new_long
    if new_short is not None:
        shadow_last_short = new_short
    _persist_bar_state(
        "shadow_", symbol, shadow_bar, shadow_last_long, shadow_last_short)

    if mode in ("live", "paper"):
        current_bar, last_long_bar, last_short_bar = _load_bar_state("", symbol)
        current_bar += 1

        open_trade = get_open_trade(mode=mode, symbol=symbol)

        if open_trade:
            _manage_open_position(open_trade, state, price, mode, symbol, params)

        open_trade = get_open_trade(mode=mode, symbol=symbol)
        has_pos = open_trade is not None

        signal = get_signal(
            state, params, last_long_bar, last_short_bar,
            current_bar, open_trade)
        signal_rec["direction"] = signal

        if signal == "close" and has_pos and open_trade:
            exit_reason = check_exit_conditions(
                price, open_trade, state["trail_level"], state["trail_dir"],
                score=sc, params=params) or "trail_flip"
            signal_rec["acted_on"] = True
            _close_position(open_trade, price, exit_reason, mode, symbol, rt)

        elif signal == "long" and not has_pos:
            ok, skip_reason = can_open_new_trade(mode, symbol)
            if ok:
                signal_rec["acted_on"] = True
                logger.info(
                    f"🟢 [{symbol}] SEÑAL LONG | Bull {sc['score_bull']} | "
                    f"Price: {price:.4f}")
                notify_signal(sc, price, "long", symbol)
                if _open_long(state, symbol, mode, params, rt):
                    last_long_bar = current_bar
            else:
                logger.info(f"[{symbol}] Señal long ignorada: {skip_reason}")

        elif signal == "short" and not has_pos and mode == "paper":
            ok, skip_reason = can_open_new_trade(mode, symbol)
            if ok:
                signal_rec["acted_on"] = True
                logger.info(
                    f"🔴 [{symbol}] SEÑAL SHORT | Bear {sc['score_bear']} | "
                    f"Price: {price:.4f}")
                notify_signal(sc, price, "short", symbol)
                if _open_short(state, symbol, mode, params, rt):
                    last_short_bar = current_bar
            else:
                logger.info(f"[{symbol}] Señal short ignorada: {skip_reason}")

        _persist_bar_state("", symbol, current_bar, last_long_bar, last_short_bar)
    else:
        open_trade = get_open_trade(mode="shadow", symbol=symbol)
        signal = get_signal(
            state, params, shadow_last_long, shadow_last_short,
            shadow_bar, open_trade)
        signal_rec["direction"] = signal

    save_signal(signal_rec)

    logger.info(
        f"   [{symbol}] Bull {sc['score_bull']} / Bear {sc['score_bear']} | "
        f"Trail: {'↑' if sc['trail_dir'] == 1 else '↓'} | "
        f"HTF: {'Bull' if sc['htf_bull'] else 'Bear' if sc['htf_bear'] else 'Neutro'}")


def on_candle_close():
    rt     = get_runtime()
    mode   = rt.bot_mode
    params = get_params()

    logger.info(
        f"── Vela {rt.timeframe} cerrada [{rt.label}] · "
        f"{len(cfg.TRADING_PAIRS)} pares ──")

    if risk_manager.is_killed():
        logger.warning("Bot detenido por kill switch. Operación manual requerida.")
        return

    equity = _estimate_equity(mode)
    should_stop, reason = risk_manager.check_kill_switch(equity, mode)
    if should_stop:
        notify_kill_switch(reason)
        return

    for symbol in cfg.TRADING_PAIRS:
        _process_symbol_candle_close(symbol, rt, mode, params)

    maybe_promote_candidate()


def run_scheduled_optimization():
    if not should_run_optimization():
        return
    rt = get_runtime()
    params = get_params()
    primary = cfg.TRADING_PAIRS[0]
    logger.info(f"Iniciando optimización ({primary})...")
    new_params, metrics = run_optimization(primary, rt.timeframe, rt.htf)
    if metrics:
        notify_optimization(params, new_params, metrics)


def _manage_open_position(open_trade, state, price, mode, symbol, params):
    trail_lv  = state["trail_level"]
    trail_dir = state["trail_dir"]
    atr_val   = state["atr"]
    sc        = state["score"]
    side      = trade_side(open_trade)

    old_sl = open_trade["stop_loss"]
    new_sl = compute_trailing_stop(trail_lv, atr_val, side)
    should_update = (
        (side == "short" and new_sl < old_sl) or
        (side == "long" and new_sl > old_sl)
    )
    if should_update:
        if update_trade_stop_loss(open_trade["trade_id"], new_sl):
            if mode == "live":
                notify_trail_update(old_sl, new_sl, symbol)
            open_trade["stop_loss"] = new_sl

    exit_reason = check_exit_conditions(
        price, open_trade, trail_lv, trail_dir, score=sc, params=params)
    if exit_reason:
        _close_position(open_trade, price, exit_reason, mode, symbol, get_runtime())


def _open_long(state, symbol, mode, params, rt) -> bool:
    sc = state["score"]

    if mode == "live":
        quote = symbol_quote_asset(symbol)
        quote_balance = fetch_balance(quote)
        capital = calc_order_capital("live", quote_balance)
        result = place_market_buy(
            symbol, quote_balance, state["long_sl"], state["long_tp"],
            rr_ratio=params.get("rr_ratio", 2.0),
            capital_to_use=capital)
        if not result:
            return False
        trade = {
            "trade_id":      f"live_{uuid.uuid4().hex[:8]}",
            "mode":          "live",
            "side":          "long",
            "symbol":        symbol,
            "timeframe":     rt.timeframe,
            "entry_time":    result["entry_time"],
            "entry_price":   result["entry_price"],
            "exit_time":     None,
            "exit_price":    None,
            "exit_reason":   None,
            "quantity":      result["quantity"],
            "pnl_usdt":      None,
            "pnl_pct":       None,
            "stop_loss":     result["stop_loss"],
            "take_profit":   result["take_profit"],
            "score_bull":    sc["score_bull"],
            "score_bear":    sc["score_bear"],
            "trail_level":   state["trail_level"],
            "params_id":     None,
            "trading_style": rt.style,
        }
        save_trade(trade)
        notify_trade_open(result["entry_price"], result["stop_loss"],
                          result["take_profit"], result["quantity"], mode, symbol)
        return True

    if mode == "paper":
        entry = state["price"]
        qty = calc_order_capital("paper") / entry
        trade = {
            "trade_id":      f"paper_{uuid.uuid4().hex[:8]}",
            "mode":          "paper",
            "side":          "long",
            "symbol":        symbol,
            "timeframe":     rt.timeframe,
            "entry_time":    datetime.utcnow(),
            "entry_price":   entry,
            "exit_time":     None,
            "exit_price":    None,
            "exit_reason":   None,
            "quantity":      qty,
            "pnl_usdt":      None,
            "pnl_pct":       None,
            "stop_loss":     state["long_sl"],
            "take_profit":   state["long_tp"],
            "score_bull":    sc["score_bull"],
            "score_bear":    sc["score_bear"],
            "trail_level":   state["trail_level"],
            "params_id":     None,
            "trading_style": rt.style,
        }
        save_trade(trade)
        notify_trade_open(entry, state["long_sl"], state["long_tp"], qty, mode, symbol)
        return True

    return False


def _open_short(state, symbol, mode, params, rt) -> bool:
    """Abre short simulado (solo paper). Live sigue long-only."""
    if mode != "paper":
        return False

    sc = state["score"]
    entry = state["price"]
    qty = calc_order_capital("paper") / entry
    trade = {
        "trade_id":      f"paper_{uuid.uuid4().hex[:8]}",
        "mode":          "paper",
        "side":          "short",
        "symbol":        symbol,
        "timeframe":     rt.timeframe,
        "entry_time":    datetime.utcnow(),
        "entry_price":   entry,
        "exit_time":     None,
        "exit_price":    None,
        "exit_reason":   None,
        "quantity":      qty,
        "pnl_usdt":      None,
        "pnl_pct":       None,
        "stop_loss":     state["short_sl"],
        "take_profit":   state["short_tp"],
        "score_bull":    sc["score_bull"],
        "score_bear":    sc["score_bear"],
        "trail_level":   state["trail_level"],
        "params_id":     None,
        "trading_style": rt.style,
    }
    save_trade(trade)
    notify_trade_open(entry, state["short_sl"], state["short_tp"], qty, mode, symbol)
    return True


def _close_position(open_trade, price, reason, mode, symbol, rt):
    if open_trade.get("exit_time"):
        return

    entry = open_trade["entry_price"]
    qty   = open_trade["quantity"]
    side  = trade_side(open_trade)
    pnl_usdt, pnl_pct = calc_trade_pnl(entry, price, qty, side)

    if mode == "live" and side == "long":
        base_bal = fetch_base_balance(symbol)
        if base_bal > 0:
            place_market_sell(symbol, min(qty, base_bal), reason)

    if not close_trade(open_trade["trade_id"], price, reason, pnl_usdt, pnl_pct):
        logger.debug(f"Trade {open_trade['trade_id']} ya estaba cerrado")
        return

    notify_trade_close(entry, price, pnl_usdt, pnl_pct, reason, mode, symbol)
    logger.info(
        f"{'✅' if pnl_usdt > 0 else '❌'} [{symbol}] Trade cerrado ({reason}) | "
        f"PnL: {pnl_usdt:+.2f} USDT ({pnl_pct:+.2%})")


def daily_summary():
    rt = get_runtime()
    mode = rt.bot_mode
    report_mode = mode if mode in ("live", "paper") else "shadow"
    trades = get_recent_trades(report_mode, days=1)
    today_pnl  = sum(t.get("pnl_usdt", 0) for t in trades
                    if t.get("pnl_usdt") is not None)
    wins   = sum(1 for t in trades if (t.get("pnl_usdt") or 0) > 0)
    wr     = wins / len(trades) if trades else 0
    equity = _estimate_equity(mode)
    notify_daily_summary(equity, today_pnl, len(trades), wr)

    shadow_m = get_shadow_metrics(30)
    if shadow_m.get("total_trades", 0) > 0:
        logger.info(
            f"Shadow 30d: PF {shadow_m.get('profit_factor'):.3f} | "
            f"WR {shadow_m.get('win_rate'):.1%} | "
            f"Trades {shadow_m.get('total_trades')}")


def check_price_monitor():
    rt = get_runtime()
    mode = rt.bot_mode
    if mode not in ("live", "paper"):
        return

    for open_trade in get_open_trades(mode):
        symbol = open_trade["symbol"]
        side = trade_side(open_trade)
        try:
            price = fetch_current_price(symbol)
            sl = open_trade.get("stop_loss", 0)
            tp = open_trade.get("take_profit")

            if side == "short":
                if price >= sl:
                    logger.warning(
                        f"[{symbol}] SL short tocado ({price:.4f} ≥ {sl:.4f}) — cerrando")
                    _close_position(open_trade, price, "sl", mode, symbol, rt)
                elif tp is not None and price <= tp:
                    logger.info(
                        f"[{symbol}] TP short alcanzado ({price:.4f} ≤ {tp:.4f}) — cerrando")
                    _close_position(open_trade, price, "tp", mode, symbol, rt)
            else:
                tp_long = tp if tp is not None else 999999
                if price <= sl:
                    logger.warning(
                        f"[{symbol}] SL tocado ({price:.4f} ≤ {sl:.4f}) — cerrando")
                    _close_position(open_trade, price, "sl", mode, symbol, rt)
                elif price >= tp_long:
                    logger.info(
                        f"[{symbol}] TP alcanzado ({price:.4f} ≥ {tp:.4f}) — cerrando")
                    _close_position(open_trade, price, "tp", mode, symbol, rt)
        except Exception as e:
            logger.error(f"[{symbol}] Error en monitoreo de precio: {e}")


def main():
    init_db()

    if get_state("last_optimization") is None:
        set_state("last_optimization", datetime.utcnow().isoformat())
        logger.info("Optimización diferida — próxima ejecución en 30 días")

    run_startup_checks()
    rt = init_runtime()

    pairs_str = ", ".join(cfg.TRADING_PAIRS)
    logger.info("=" * 60)
    logger.info("  NEXTWAVES BOT — Iniciando")
    logger.info(f"  Modo:   {rt.bot_mode.upper()}")
    logger.info(f"  Estilo: {rt.label} ({rt.timeframe} · HTF {rt.htf})")
    logger.info(f"  Pares:  {pairs_str}")
    logger.info(
        f"  Límite: {cfg.MAX_ACTIVE_PAIRS} pares simultáneos · "
        f"{cfg.POSITION_SIZE_PCT:.0%} capital/par")
    logger.info("=" * 60)

    params = get_params()
    logger.info(
        f"Parámetros activos: score={params['score_threshold']} | "
        f"trail={params['trail_mult']} | rr={params['rr_ratio']}")

    notify_start(rt.bot_mode, cfg.TRADING_PAIRS, rt.label, rt.timeframe)
    init_telegram_offset()
    tg_send(
        "💬 Control por Telegram activo.\n"
        "Envía <b>/ayuda</b> para ver los comandos."
    )

    scheduler = BlockingScheduler(timezone="UTC")
    set_scheduler(scheduler)

    scheduler.add_job(
        on_candle_close,
        candle_close_trigger(rt.timeframe),
        id="candle_close",
        name=f"Cierre vela {rt.timeframe}",
        misfire_grace_time=120,
    )

    scheduler.add_job(
        check_price_monitor,
        IntervalTrigger(minutes=rt.price_monitor_minutes),
        id="price_monitor", name="Monitor precio",
    )

    scheduler.add_job(
        poll_telegram_commands,
        IntervalTrigger(seconds=3),
        id="telegram_poll", name="Comandos Telegram",
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
    logger.info(f"Cierre de vela: {candle_close_description(rt.timeframe)}")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot detenido por el usuario")
        scheduler.shutdown()


if __name__ == "__main__":
    main()
