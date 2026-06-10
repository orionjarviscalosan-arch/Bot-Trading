"""
risk_manager.py — Gestión de riesgo y kill switch
"""
import logging
from datetime import datetime, timedelta
from bot.database import get_state, set_state, get_recent_trades
from config import KILL_SWITCH

logger = logging.getLogger(__name__)

PAUSE_HOURS = float(KILL_SWITCH.get("pause_hours", 4))


class RiskManager:
    def __init__(self, initial_capital: float):
        self.initial_capital = initial_capital
        self.killed          = False
        self.pause_until     = None

    def check_kill_switch(self, current_equity: float, mode: str = "live") -> tuple[bool, str]:
        """
        Verifica si se deben activar las protecciones.
        Devuelve (parar, motivo).
        """
        pause_until = get_state("pause_until")
        if pause_until:
            pt = datetime.utcnow()
            end = datetime.fromisoformat(pause_until)
            if pt < end:
                remaining = max(1, int((end - pt).total_seconds() // 60))
                base = get_state("pause_reason") or "Pausa por riesgo"
                return True, f"{base} ({remaining} min restantes)"
            set_state("pause_until", None)
            set_state("pause_reason", None)
            set_state("kill_notify_sent", None)

        dd_pct = (self.initial_capital - current_equity) / self.initial_capital
        if dd_pct >= KILL_SWITCH["max_drawdown_pct"]:
            msg = f"KILL SWITCH: Drawdown {dd_pct:.1%} ≥ máximo {KILL_SWITCH['max_drawdown_pct']:.1%}"
            logger.critical(msg)
            self.killed = True
            set_state("bot_killed", True)
            set_state("kill_reason", msg)
            return True, msg

        today_trades = self._get_today_trades(mode)
        daily_pnl    = sum(t.get("pnl_usdt", 0) for t in today_trades
                          if t.get("pnl_usdt") is not None)
        daily_loss_pct = abs(daily_pnl) / self.initial_capital if daily_pnl < 0 else 0
        if daily_loss_pct >= KILL_SWITCH["max_daily_loss_pct"]:
            msg = f"Pérdida diaria {daily_loss_pct:.1%} ≥ máximo {KILL_SWITCH['max_daily_loss_pct']:.1%}"
            logger.warning(msg)
            self._set_pause(msg, PAUSE_HOURS)
            return True, msg

        recent = get_recent_trades(mode, days=30)
        if recent:
            consecutive = 0
            for t in recent[:15]:
                pnl = t.get("pnl_usdt", 0)
                if pnl is not None and pnl < 0:
                    consecutive += 1
                else:
                    break
            if consecutive >= KILL_SWITCH["max_consecutive_loss"]:
                msg = f"{consecutive} pérdidas consecutivas → pausa {PAUSE_HOURS:.0f}h"
                logger.warning(msg)
                self._set_pause(msg, PAUSE_HOURS)
                return True, msg

        return False, ""

    def _set_pause(self, reason: str, hours: float) -> None:
        until = datetime.utcnow() + timedelta(hours=hours)
        set_state("pause_until", until.isoformat())
        set_state("pause_reason", reason)

    def _get_today_trades(self, mode: str) -> list:
        all_trades = get_recent_trades(mode, days=1)
        today      = datetime.utcnow().date()
        return [t for t in all_trades
                if t.get("entry_time") and
                datetime.fromisoformat(str(t["entry_time"])).date() == today]

    def calc_position_size(self, equity: float, position_pct: float,
                           max_capital: float) -> float:
        usdt = min(equity * position_pct, max_capital)
        logger.debug(f"Position size: {usdt:.2f} USDT ({position_pct:.0%} de {equity:.2f})")
        return usdt

    def is_paused(self) -> bool:
        pause_until = get_state("pause_until")
        if pause_until:
            return datetime.utcnow() < datetime.fromisoformat(pause_until)
        return False

    def is_killed(self) -> bool:
        return bool(get_state("bot_killed", False))

    def clear_pause(self) -> None:
        set_state("pause_until", None)
        set_state("pause_reason", None)
        set_state("kill_notify_sent", None)
        logger.info("Pausa temporal eliminada manualmente")

    def reset_kill(self):
        """Solo para uso manual tras revisión humana"""
        set_state("bot_killed", False)
        set_state("kill_reason", None)
        set_state("pause_until", None)
        set_state("pause_reason", None)
        set_state("kill_notify_sent", None)
        self.killed = False
        logger.info("Kill switch reseteado manualmente")
