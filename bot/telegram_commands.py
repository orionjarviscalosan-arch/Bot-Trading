"""
telegram_commands.py — Control del bot vía comandos de Telegram
"""
import logging
import requests

import config as cfg
from bot.database import get_state, set_state
from bot.style_runtime import (
    apply_style, apply_mode, apply_live_confirmed,
    get_status_message, get_help_message, get_pairs_message,
)

logger = logging.getLogger(__name__)

_STYLE_COMMANDS = {
    "/1m":         "ultra_1m",
    "/ultra":      "ultra_1m",
    "/5m":         "micro_5m",
    "/micro":      "micro_5m",
    "/15m":        "scalper",
    "/scalper":    "scalper",
    "/daytrader":  "day_trader",
    "/day":        "day_trader",
    "/swing":      "swing",
    "/1h":         "day_trader",
    "/4h":         "swing",
}

_MODE_COMMANDS = {
    "/shadow": "shadow",
    "/paper":  "paper",
}


def _send(chat_id: str, text: str) -> bool:
    if not cfg.TELEGRAM_TOKEN:
        return False
    try:
        url = f"https://api.telegram.org/bot{cfg.TELEGRAM_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id":    chat_id,
            "text":       text,
            "parse_mode": "HTML",
        }, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"Error enviando respuesta Telegram: {e}")
        return False


def _authorized(chat_id: int | str) -> bool:
    allowed = str(cfg.TELEGRAM_CHAT_ID).strip()
    if not allowed:
        return False
    return str(chat_id) == allowed


def _parse_command(text: str) -> tuple[str, str]:
    """Devuelve (comando, argumento)."""
    parts = (text or "").strip().split(maxsplit=1)
    cmd = parts[0].lower().split("@")[0]  # ignorar @BotName
    arg = parts[1].strip().lower() if len(parts) > 1 else ""
    return cmd, arg


def _handle_command(chat_id: str, text: str) -> str | None:
    cmd, arg = _parse_command(text)

    if cmd in ("/start", "/ayuda", "/help"):
        return get_help_message()

    if cmd == "/estado":
        return get_status_message()

    if cmd == "/pares":
        return get_pairs_message()

    if cmd == "/estilo":
        from bot.style_runtime import get_runtime
        from bot.trading_styles import list_styles_summary
        rt = get_runtime()
        return (
            f"Estilo activo: <b>{rt.label}</b>\n"
            f"Timeframe: <b>{rt.timeframe}</b> · HTF {rt.htf}\n"
            f"Modo: <b>{rt.bot_mode.upper()}</b>\n\n"
            f"<b>Estilos disponibles:</b>\n{list_styles_summary()}"
        )

    if cmd == "/tiempo":
        from bot.trading_styles import list_styles_summary
        from bot.style_runtime import get_runtime
        rt = get_runtime()
        return (
            f"⏱ <b>Timeframes</b> (activo: <b>{rt.label}</b> · {rt.timeframe})\n\n"
            f"{list_styles_summary()}\n\n"
            "Cambia con:\n"
            "<code>/1m</code> · <code>/5m</code> · <code>/15m</code>\n"
            "<code>/day</code> · <code>/swing</code>"
        )

    if cmd == "/reanudar":
        from bot.risk_manager import RiskManager
        rm = RiskManager(cfg.MAX_CAPITAL_USDT)
        if get_state("bot_killed"):
            return (
                "El bot está en <b>KILL SWITCH</b> permanente.\n"
                "Revisa el dashboard y resetea manualmente tras analizar el drawdown."
            )
        rm.clear_pause()
        return "▶️ Pausa eliminada. El bot operará en la próxima vela."

    if cmd in _STYLE_COMMANDS:
        return apply_style(_STYLE_COMMANDS[cmd])

    if cmd in _MODE_COMMANDS:
        return apply_mode(_MODE_COMMANDS[cmd])

    if cmd == "/live":
        if arg == "confirmar":
            return apply_live_confirmed()
        return apply_mode("live")

    if cmd == "/modo" and arg in ("shadow", "paper", "live"):
        if arg == "live":
            return apply_mode("live")
        return apply_mode(arg)

    return None


def init_telegram_offset() -> None:
    """Ignora comandos antiguos acumulados antes del arranque."""
    if get_state("telegram_update_offset") is not None:
        return
    if not cfg.TELEGRAM_TOKEN:
        return
    try:
        url = f"https://api.telegram.org/bot{cfg.TELEGRAM_TOKEN}/getUpdates"
        resp = requests.get(url, params={"offset": -1, "limit": 1}, timeout=5)
        data = resp.json()
        results = data.get("result", [])
        offset = results[-1]["update_id"] + 1 if results else 0
        set_state("telegram_update_offset", offset)
    except Exception as e:
        logger.debug(f"Init telegram offset: {e}")
        set_state("telegram_update_offset", 0)


def poll_telegram_commands() -> None:
    """Lee mensajes nuevos de Telegram y procesa comandos."""
    if not cfg.TELEGRAM_TOKEN or not cfg.TELEGRAM_CHAT_ID:
        return

    offset = get_state("telegram_update_offset", 0) or 0
    try:
        url = f"https://api.telegram.org/bot{cfg.TELEGRAM_TOKEN}/getUpdates"
        resp = requests.get(url, params={
            "offset":  offset,
            "timeout": 0,
            "allowed_updates": ["message"],
        }, timeout=5)
        if resp.status_code != 200:
            return
        data = resp.json()
        if not data.get("ok"):
            return

        for update in data.get("result", []):
            update_id = update["update_id"]
            offset = update_id + 1

            msg = update.get("message") or {}
            chat = msg.get("chat") or {}
            chat_id = chat.get("id")
            text = msg.get("text", "")

            if not text.startswith("/"):
                continue
            if not _authorized(chat_id):
                logger.warning(f"Comando ignorado de chat no autorizado: {chat_id}")
                continue

            reply = _handle_command(str(chat_id), text)
            if reply:
                _send(str(chat_id), reply)
                logger.info(f"Comando Telegram: {text.split()[0]}")

        if offset != get_state("telegram_update_offset", 0):
            set_state("telegram_update_offset", offset)

    except requests.RequestException as e:
        logger.debug(f"Poll Telegram: {e}")
    except Exception as e:
        logger.error(f"Error procesando comandos Telegram: {e}")
