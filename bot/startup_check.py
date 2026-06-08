"""
startup_check.py — Validación de configuración al arrancar
"""
import logging
import config as cfg
from bot.trading_styles import VALID_STYLES, TRADING_STYLES, STYLE_LABELS
from bot.data_fetcher import validate_connection

logger = logging.getLogger(__name__)

VALID_MODES = {"shadow", "paper", "live"}


def validate_startup() -> list[str]:
    """
    Valida la configuración. Devuelve lista de errores (vacía = OK).
    """
    errors = []

    if cfg.BOT_MODE not in VALID_MODES:
        errors.append(f"BOT_MODE inválido: '{cfg.BOT_MODE}'. Usa: shadow | paper | live")

    if cfg.TRADING_STYLE not in VALID_STYLES:
        errors.append(
            f"TRADING_STYLE inválido: '{cfg.TRADING_STYLE}'. "
            f"Usa: ultra_1m | micro_5m | scalper | day_trader | swing")

    if not cfg.TRADING_PAIRS:
        errors.append("TRADING_PAIRS está vacío — define al menos un par")

    if cfg.MAX_ACTIVE_PAIRS < 1:
        errors.append("MAX_ACTIVE_PAIRS debe ser ≥ 1")

    if cfg.MAX_ACTIVE_PAIRS > len(cfg.TRADING_PAIRS):
        errors.append(
            f"MAX_ACTIVE_PAIRS ({cfg.MAX_ACTIVE_PAIRS}) no puede superar "
            f"el número de pares ({len(cfg.TRADING_PAIRS)})"
        )

    min_per_trade = cfg.MAX_CAPITAL_USDT * cfg.POSITION_SIZE_PCT
    if min_per_trade < cfg.MIN_ORDER_USDT:
        errors.append(
            f"Capital por par ({min_per_trade:.2f} USDT) debe ser ≥ "
            f"MIN_ORDER_USDT ({cfg.MIN_ORDER_USDT}) — "
            f"sube MAX_CAPITAL_USDT o POSITION_SIZE_PCT"
        )

    if cfg.BOT_MODE == "live":
        if not cfg.BINANCE_API_KEY or not cfg.BINANCE_API_SECRET:
            errors.append("Modo live requiere BINANCE_API_KEY y BINANCE_API_SECRET")
        if cfg.MAX_CAPITAL_USDT <= 0:
            errors.append("MAX_CAPITAL_USDT debe ser > 0 en modo live")

    if cfg.TELEGRAM_TOKEN and not cfg.TELEGRAM_CHAT_ID:
        errors.append("TELEGRAM_TOKEN definido pero falta TELEGRAM_CHAT_ID")
    if cfg.TELEGRAM_CHAT_ID and not cfg.TELEGRAM_TOKEN:
        errors.append("TELEGRAM_CHAT_ID definido pero falta TELEGRAM_TOKEN")

    for symbol in cfg.TRADING_PAIRS:
        ok, msg = validate_connection(symbol)
        if not ok:
            errors.append(f"Binance [{symbol}]: {msg}")

    return errors


def run_startup_checks():
    """Ejecuta validación; lanza SystemExit si hay errores críticos."""
    errors = validate_startup()
    if errors:
        for err in errors:
            logger.error(f"Configuración inválida: {err}")
        raise SystemExit(
            "Arranque abortado por errores de configuración. Revisa .env y los logs."
        )

    if not cfg.TELEGRAM_TOKEN:
        logger.warning("Telegram no configurado — las notificaciones estarán desactivadas")
    if cfg.BOT_MODE == "shadow":
        logger.info("Modo SHADOW: no se ejecutarán órdenes reales")
    elif cfg.BOT_MODE == "paper":
        logger.info("Modo PAPER: simulación con capital virtual, sin órdenes reales")
    logger.info(
        f"Estilo {cfg.TRADING_STYLE_LABEL}: {cfg.TIMEFRAME} (HTF {cfg.HTF}) — "
        f"{TRADING_STYLES[cfg.TRADING_STYLE]['description']}")
    logger.info(
        f"Multi-par: {len(cfg.TRADING_PAIRS)} pares · "
        f"máx {cfg.MAX_ACTIVE_PAIRS} simultáneos · "
        f"{cfg.POSITION_SIZE_PCT:.0%}/par"
    )
