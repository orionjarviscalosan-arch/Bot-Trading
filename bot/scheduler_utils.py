"""
scheduler_utils.py — Mapeo de timeframe a triggers del scheduler
"""
from apscheduler.triggers.cron import CronTrigger

# Ejecutar tras el cierre de vela (UTC). 1m evalúa cada minuto.
_TIMEFRAME_CRON = {
    "1m":  {"hour": "*", "minute": "*"},
    "5m":  {"hour": "*", "minute": "1,6,11,16,21,26,31,36,41,46,51,56"},
    "15m": {"hour": "*", "minute": "1,16,31,46"},
    "30m": {"hour": "*", "minute": "1,31"},
    "1h":  {"hour": "*", "minute": "1"},
    "2h":  {"hour": "0,2,4,6,8,10,12,14,16,18,20,22", "minute": "1"},
    "4h":  {"hour": "0,4,8,12,16,20", "minute": "1"},
    "6h":  {"hour": "0,6,12,18",      "minute": "1"},
    "8h":  {"hour": "0,8,16",         "minute": "1"},
    "12h": {"hour": "0,12",           "minute": "1"},
    "1d":  {"hour": "0",              "minute": "1"},
}


def candle_close_trigger(timeframe: str) -> CronTrigger:
    """Devuelve un CronTrigger alineado al cierre de vela del timeframe."""
    spec = _TIMEFRAME_CRON.get(timeframe, _TIMEFRAME_CRON["4h"])
    return CronTrigger(
        hour=spec["hour"],
        minute=spec["minute"],
        timezone="UTC",
    )


def candle_close_description(timeframe: str) -> str:
    """Descripción legible del schedule para logs."""
    spec = _TIMEFRAME_CRON.get(timeframe, _TIMEFRAME_CRON["4h"])
    return f"hour={spec['hour']} minute={spec['minute']} UTC"
