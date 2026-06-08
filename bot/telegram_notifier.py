"""
telegram_notifier.py — Notificaciones vía Telegram
"""
import logging
import requests
from datetime import datetime
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


def send(text: str, parse_mode: str = "HTML") -> bool:
    """Envía un mensaje al chat de Telegram"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug(f"[TELEGRAM DESACTIVADO] {text[:80]}")
        return False
    try:
        url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": parse_mode,
        }, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"Error Telegram: {e}")
        return False


def notify_start(mode: str, symbol: str, style_label: str = "Swing",
                 timeframe: str = "4h"):
    send(
        f"🤖 <b>Nextwaves Bot iniciado</b>\n"
        f"Modo: <b>{mode.upper()}</b>\n"
        f"Estilo: <b>{style_label}</b> ({timeframe})\n"
        f"Par: {symbol}\n"
        f"Hora: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
    )


def notify_signal(score: dict, price: float, direction: str):
    emoji = "🟢" if direction == "long" else "🔴"
    send(
        f"{emoji} <b>Señal detectada: {direction.upper()}</b>\n"
        f"Precio: {price:,.2f} USDT\n"
        f"Score Bull: <b>{score['score_bull']}</b>  |  Bear: <b>{score['score_bear']}</b>\n"
        f"HTF: {'✅ Bull' if score['htf_bull'] else '❌'}\n"
        f"Estructura: {'CHoCH ↑' if score['bull_choch_recent'] else 'BOS ↑' if score['bull_bos_recent'] else '–'}\n"
        f"Momentum: {score['momentum_raw']:+.3f}\n"
        f"Régimen: {'✅ Tendencia' if score['regime_ok'] else '⚠️ Lateral'}"
    )


def notify_trade_open(entry_price: float, stop_loss: float,
                      take_profit: float, quantity: float, mode: str):
    rr = abs(take_profit - entry_price) / abs(entry_price - stop_loss)
    send(
        f"{'💰' if mode == 'live' else '📋'} <b>TRADE ABIERTO [{mode.upper()}]</b>\n"
        f"Entry:  <b>{entry_price:,.2f} USDT</b>\n"
        f"SL:     {stop_loss:,.2f} USDT\n"
        f"TP:     {take_profit:,.2f} USDT\n"
        f"R:R:    {rr:.2f}x\n"
        f"Qty:    {quantity:.6f} BTC"
    )


def notify_trade_close(entry: float, exit_price: float, pnl_usdt: float,
                       pnl_pct: float, reason: str, mode: str):
    emoji = "✅" if pnl_usdt > 0 else "❌"
    reason_map = {"sl": "Stop Loss", "tp": "Take Profit",
                  "trail_flip": "Trail Flip", "score_bear": "Score bajista",
                  "manual": "Manual"}
    send(
        f"{emoji} <b>TRADE CERRADO [{mode.upper()}]</b>\n"
        f"Motivo: {reason_map.get(reason, reason)}\n"
        f"Entry:  {entry:,.2f}\n"
        f"Exit:   {exit_price:,.2f}\n"
        f"PnL:    <b>{pnl_usdt:+.2f} USDT ({pnl_pct:+.2%})</b>"
    )


def notify_trail_update(old_sl: float, new_sl: float):
    send(
        f"📈 <b>Trail actualizado</b>\n"
        f"SL anterior: {old_sl:,.2f}\n"
        f"SL nuevo:    {new_sl:,.2f} (+{new_sl-old_sl:.2f})"
    )


def notify_kill_switch(reason: str):
    send(
        f"🚨 <b>KILL SWITCH ACTIVADO</b>\n"
        f"Motivo: {reason}\n"
        f"El bot ha parado. Revisa la situación antes de reiniciar."
    )


def notify_optimization(old_params: dict, new_params: dict, metrics: dict):
    changed = {k: (old_params.get(k), v)
               for k, v in new_params.items()
               if old_params.get(k) != v}
    changes = "\n".join(f"  {k}: {a} → {b}" for k, (a, b) in changed.items())
    send(
        f"🔧 <b>Parámetros optimizados</b>\n"
        f"Win Rate: {metrics.get('win_rate', 0):.1%}\n"
        f"PF: {metrics.get('profit_factor', 0):.3f}\n"
        f"Trades: {metrics.get('total_trades', 0)}\n"
        f"Cambios:\n{changes or '  Ninguno'}"
    )


def notify_daily_summary(equity: float, daily_pnl: float,
                         trades_today: int, win_rate: float):
    emoji = "📈" if daily_pnl >= 0 else "📉"
    send(
        f"{emoji} <b>Resumen diario</b>  {datetime.utcnow().strftime('%Y-%m-%d')}\n"
        f"Equity:   {equity:,.2f} USDT\n"
        f"PnL día:  {daily_pnl:+.2f} USDT\n"
        f"Trades:   {trades_today}\n"
        f"Win Rate: {win_rate:.1%}"
    )
