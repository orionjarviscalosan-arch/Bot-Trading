"""
risk_manager.py — Gestión de riesgo y kill switch
"""
import logging
from datetime import datetime, timedelta
from bot.database import get_state, set_state, get_recent_trades
from config import KILL_SWITCH

logger = logging.getLogger(__name__)


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
        # ── Pausa temporal por pérdidas consecutivas ──────
        pause_until = get_state("pause_until")
        if pause_until:
            pt = datetime.fromisoformat(pause_until)
            if datetime.utcnow() < pt:
                remaining = (pt - datetime.utcnow()).seconds // 60
                return True, f"Pausa activa por {remaining} min más"
            else:
                set_state("pause_until", None)

        # ── Drawdown máximo total ──────────────────────────
        dd_pct = (self.initial_capital - current_equity) / self.initial_capital
        if dd_pct >= KILL_SWITCH["max_drawdown_pct"]:
            msg = f"KILL SWITCH: Drawdown {dd_pct:.1%} ≥ máximo {KILL_SWITCH['max_drawdown_pct']:.1%}"
            logger.critical(msg)
            self.killed = True
            set_state("bot_killed", True)
            set_state("kill_reason", msg)
            return True, msg

        # ── Pérdida diaria máxima ──────────────────────────
        today_trades = self._get_today_trades(mode)
        daily_pnl    = sum(t.get("pnl_usdt", 0) for t in today_trades
                          if t.get("pnl_usdt") is not None)
        daily_loss_pct = abs(daily_pnl) / self.initial_capital if daily_pnl < 0 else 0
        if daily_loss_pct >= KILL_SWITCH["max_daily_loss_pct"]:
            msg = f"Pérdida diaria {daily_loss_pct:.1%} ≥ máximo {KILL_SWITCH['max_daily_loss_pct']:.1%}"
            logger.warning(msg)
            pause_hours = 24
            set_state("pause_until", (datetime.utcnow() + timedelta(hours=pause_hours)).isoformat())
            return True, msg

        # ── Pérdidas consecutivas ──────────────────────────
        recent = get_recent_trades(mode, days=30)
        if recent:
            consecutive = 0
            for t in recent[:10]:
                pnl = t.get("pnl_usdt", 0)
                if pnl is not None and pnl < 0:
                    consecutive += 1
                else:
                    break
            if consecutive >= KILL_SWITCH["max_consecutive_loss"]:
                msg = f"{consecutive} pérdidas consecutivas → pausa 24h"
                logger.warning(msg)
                set_state("pause_until", (datetime.utcnow() + timedelta(hours=24)).isoformat())
                return True, msg

        return False, ""

    def _get_today_trades(self, mode: str) -> list:
        all_trades = get_recent_trades(mode, days=1)
        today      = datetime.utcnow().date()
        return [t for t in all_trades
                if t.get("entry_time") and
                datetime.fromisoformat(str(t["entry_time"])).date() == today]

    def calc_position_size(self, equity: float, position_pct: float,
                           max_capital: float) -> float:
        """Calcula el USDT a invertir en el siguiente trade"""
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

    def reset_kill(self):
        """Solo para uso manual tras revisión humana"""
        set_state("bot_killed", False)
        set_state("kill_reason", None)
        set_state("pause_until", None)
        self.killed = False
        logger.info("Kill switch reseteado manualmente")
