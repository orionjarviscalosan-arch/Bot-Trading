"""
style_runtime.py — Estilo y modo activos en runtime (controlable vía Telegram)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
import os

import config as cfg
from bot.database import get_state, set_state, save_param_set, get_active_params, get_active_param_source
from bot.trading_styles import (
    normalize_style, get_style_config, apply_style_to_signal_params,
    STYLE_LABELS, VALID_STYLES, list_styles_summary,
)
from bot.pairs import bar_state_keys
from bot.scheduler_utils import candle_close_trigger, candle_close_description
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

VALID_MODES = ("shadow", "paper", "live")


@dataclass
class RuntimeConfig:
    style: str
    label: str
    timeframe: str
    htf: str
    candles_lb: int
    price_monitor_minutes: int
    signal_params: dict
    bot_mode: str


_runtime: RuntimeConfig | None = None
_scheduler = None


def set_scheduler(scheduler) -> None:
    global _scheduler
    _scheduler = scheduler


def _build(style: str, bot_mode: str) -> RuntimeConfig:
    style = normalize_style(style)
    bot_mode = bot_mode.lower().strip()
    if bot_mode not in VALID_MODES:
        bot_mode = cfg.BOT_MODE
    sc = get_style_config(style)
    params = apply_style_to_signal_params(cfg._BASE_SIGNAL_PARAMS, style)
    return RuntimeConfig(
        style=style,
        label=sc["label"],
        timeframe=sc["timeframe"],
        htf=sc["htf"],
        candles_lb=sc["candles_lb"],
        price_monitor_minutes=sc["price_monitor_minutes"],
        signal_params=params,
        bot_mode=bot_mode,
    )


def init_runtime() -> RuntimeConfig:
    """Carga estilo/modo desde bot_state o .env en el primer arranque."""
    global _runtime
    style = get_state("trading_style")
    bot_mode = get_state("bot_mode")
    if style is None:
        from bot.trading_styles import resolve_active_style
        style = resolve_active_style()
        set_state("trading_style", style)
    if bot_mode is None:
        bot_mode = getattr(cfg, "BOT_MODE", None) or os.getenv("BOT_MODE", "shadow")
        set_state("bot_mode", bot_mode)
    _runtime = _build(style, bot_mode)
    sync_params(_runtime)
    set_state("active_trading_style", _runtime.style)
    logger.info(
        f"Runtime: estilo {_runtime.label} ({_runtime.timeframe}) | "
        f"modo {_runtime.bot_mode}")
    return _runtime


def get_runtime() -> RuntimeConfig:
    if _runtime is None:
        return init_runtime()
    return _runtime


def _reset_bar_counters() -> None:
    for symbol in cfg.TRADING_PAIRS:
        for prefix in ("shadow_", ""):
            cur_key, last_long_key, last_short_key = bar_state_keys(prefix, symbol)
            set_state(cur_key, 0)
            set_state(last_long_key, None)
            set_state(last_short_key, None)
    # Limpiar keys legacy (pre multi-par)
    for key, val in [
        ("shadow_current_bar", 0), ("current_bar", 0),
        ("shadow_last_long_bar", None), ("last_long_bar", None),
    ]:
        set_state(key, val)


def sync_params(rt: RuntimeConfig) -> None:
    stored = get_state("active_trading_style")
    params_style = get_state("params_style")
    params = get_active_params()
    source = get_active_param_source()

    style_changed = stored != rt.style or params_style != rt.style
    missing = params is None
    unmigrated = params_style is None and params is not None
    stale = (
        source == "optimized"
        and params_style is not None
        and params_style != rt.style
    )
    drifted = (
        source
        and source.startswith("style_")
        and params is not None
        and params.get("score_threshold") != rt.signal_params.get("score_threshold")
    )

    if style_changed or missing or unmigrated or stale or drifted:
        save_param_set(rt.signal_params.copy(), source=f"style_{rt.style}")
        set_state("active_trading_style", rt.style)
        set_state("params_style", rt.style)
        logger.info(
            f"Parámetros sincronizados con estilo {rt.style} "
            f"(source={source}, params_style={params_style})")


def _reschedule_jobs(rt: RuntimeConfig) -> None:
    if _scheduler is None:
        return
    try:
        _scheduler.reschedule_job(
            "candle_close",
            trigger=candle_close_trigger(rt.timeframe),
        )
        _scheduler.reschedule_job(
            "price_monitor",
            trigger=IntervalTrigger(minutes=rt.price_monitor_minutes),
        )
        logger.info(
            f"Scheduler actualizado: {rt.timeframe} | "
            f"monitor {rt.price_monitor_minutes}min | "
            f"{candle_close_description(rt.timeframe)}")
    except Exception as e:
        logger.error(f"Error al reprogramar scheduler: {e}")


def apply_style(style: str) -> str:
    """Cambia el estilo de trading en caliente."""
    global _runtime
    rt = get_runtime()
    new_style = normalize_style(style)
    if new_style == rt.style:
        return (
            f"Ya estás en <b>{rt.label}</b> ({rt.timeframe}).\n"
            f"Sin cambios."
        )
    old_label = rt.label
    _runtime = _build(new_style, rt.bot_mode)
    set_state("trading_style", new_style)
    _reset_bar_counters()
    sync_params(_runtime)
    _reschedule_jobs(_runtime)
    return (
        f"✅ Estilo cambiado\n"
        f"<b>{old_label}</b> → <b>{_runtime.label}</b>\n"
        f"Timeframe: <b>{_runtime.timeframe}</b> · HTF {_runtime.htf}\n"
        f"Score ≥ {_runtime.signal_params['score_threshold']} · "
        f"R:R {_runtime.signal_params['rr_ratio']} · "
        f"Cooldown {_runtime.signal_params['cooldown_bars']} velas\n"
        f"Próxima evaluación al cierre de vela {_runtime.timeframe}."
    )


def apply_mode(mode: str) -> str:
    """Cambia shadow / paper / live."""
    global _runtime
    mode = mode.lower().strip()
    if mode not in VALID_MODES:
        return f"Modo inválido. Usa: shadow | paper | live"
    rt = get_runtime()
    if mode == rt.bot_mode:
        return f"Ya estás en modo <b>{mode.upper()}</b>."
    if mode == "live":
        return (
            "⚠️ Para activar <b>LIVE</b> confirma con:\n"
            "<code>/live confirmar</code>\n"
            "(Opera con dinero real)"
        )
    old = rt.bot_mode
    _runtime = _build(rt.style, mode)
    set_state("bot_mode", mode)
    return (
        f"✅ Modo cambiado\n"
        f"<b>{old.upper()}</b> → <b>{mode.upper()}</b>"
    )


def apply_live_confirmed() -> str:
    global _runtime
    rt = get_runtime()
    _runtime = _build(rt.style, "live")
    set_state("bot_mode", "live")
    return "🔴 Modo <b>LIVE</b> activado — operaciones reales en Binance."


def get_status_message() -> str:
    from bot.database import get_open_trades, count_open_trades

    rt = get_runtime()
    killed = get_state("bot_killed", False)
    pause = get_state("pause_until")
    open_trades = get_open_trades(rt.bot_mode)
    open_count = count_open_trades(rt.bot_mode)

    lines = [
        "📊 <b>Estado del bot</b>",
        f"Estilo: <b>{rt.label}</b> ({rt.timeframe} / HTF {rt.htf})",
        f"Modo: <b>{rt.bot_mode.upper()}</b>",
        f"Pares ({len(cfg.TRADING_PAIRS)}):",
        " · ".join(f"<code>{p}</code>" for p in cfg.TRADING_PAIRS),
        f"Posiciones: <b>{open_count}/{cfg.MAX_ACTIVE_PAIRS}</b> · "
        f"{cfg.POSITION_SIZE_PCT:.0%} capital/par",
        f"Score mín: {rt.signal_params['score_threshold']} · "
        f"R:R {rt.signal_params['rr_ratio']} · "
        f"Cooldown {rt.signal_params['cooldown_bars']} velas",
    ]
    if open_trades:
        lines.append("<b>Abiertas:</b>")
        for t in open_trades:
            sym = t.get("symbol", "?")
            entry = t.get("entry_price", 0)
            lines.append(f"  · {sym} @ {entry:,.4f}")
    if killed:
        lines.append(f"🚨 Kill switch: {get_state('kill_reason', '—')}")
    elif pause:
        lines.append(f"⏸ Pausa hasta: {pause}")
    else:
        lines.append("✅ Operativo")
    return "\n".join(lines)


def get_pairs_message() -> str:
    from bot.database import get_open_trades, count_open_trades
    from bot.pairs import symbol_base_asset

    rt = get_runtime()
    open_by_symbol = {t["symbol"]: t for t in get_open_trades(rt.bot_mode)}
    open_count = count_open_trades(rt.bot_mode)

    lines = [
        "📈 <b>Pares configurados</b>",
        f"Máx. simultáneos: <b>{cfg.MAX_ACTIVE_PAIRS}</b> · "
        f"Capital/par: <b>{cfg.POSITION_SIZE_PCT:.0%}</b>",
        f"Activas ahora: <b>{open_count}</b>",
        "",
    ]
    for sym in cfg.TRADING_PAIRS:
        base = symbol_base_asset(sym)
        trade = open_by_symbol.get(sym)
        if trade:
            lines.append(
                f"🟢 <b>{sym}</b> — LONG @ {trade['entry_price']:,.4f} "
                f"({base} {trade['quantity']:.4f})"
            )
        else:
            lines.append(f"⚪ <code>{sym}</code> — sin posición")
    return "\n".join(lines)


def get_help_message() -> str:
    return (
        "🤖 <b>Nextwaves Bot — Comandos</b>\n\n"
        "<b>Timeframe (autoajusta indicadores)</b>\n"
        "/1m — ultra scalping (1 min)\n"
        "/5m — micro scalping (5 min)\n"
        "/15m o /scalper — scalper (15 min)\n"
        "/day — intradía (1h)\n"
        "/swing — posiciones largas (4h)\n"
        "/tiempo — ver todos los modos\n"
        "/estilo — estilo activo\n\n"
        "<b>Modo de ejecución</b>\n"
        "/shadow — simulación (sin dinero)\n"
        "/paper — paper trading\n"
        "/live confirmar — dinero real ⚠️\n\n"
        "<b>Info</b>\n"
        "/pares — posiciones por par\n"
        "/estado — resumen completo\n"
        "/ayuda — este mensaje"
    )
