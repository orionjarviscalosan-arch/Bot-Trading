"""
pairs.py — Utilidades para trading multi-par
"""
from __future__ import annotations

import config as cfg


def symbol_key(symbol: str) -> str:
    return symbol.replace("/", "_")


def symbol_base_asset(symbol: str) -> str:
    return symbol.split("/")[0]


def symbol_quote_asset(symbol: str) -> str:
    return symbol.split("/")[1]


def bar_state_keys(prefix: str, symbol: str) -> tuple[str, str]:
    sk = symbol_key(symbol)
    return f"{prefix}{sk}_current_bar", f"{prefix}{sk}_last_long_bar"


def unique_quote_assets(pairs: list[str] | None = None) -> list[str]:
    pairs = pairs or cfg.TRADING_PAIRS
    return sorted({symbol_quote_asset(p) for p in pairs})


def calc_order_capital(mode: str, quote_balance: float | None = None) -> float:
    """Capital máximo por operación (POSITION_SIZE_PCT del capital de referencia)."""
    per_trade = cfg.MAX_CAPITAL_USDT * cfg.POSITION_SIZE_PCT
    if mode == "shadow":
        return cfg.SHADOW_CAPITAL * cfg.POSITION_SIZE_PCT
    if mode == "live" and quote_balance is not None:
        return min(per_trade, quote_balance * cfg.POSITION_SIZE_PCT)
    return per_trade


def can_open_new_trade(mode: str, symbol: str) -> tuple[bool, str]:
    from bot.database import get_open_trade, count_open_trades

    if get_open_trade(mode=mode, symbol=symbol):
        return False, f"posición ya abierta en {symbol}"
    open_count = count_open_trades(mode)
    if open_count >= cfg.MAX_ACTIVE_PAIRS:
        return False, (
            f"máximo {cfg.MAX_ACTIVE_PAIRS} pares activos "
            f"({open_count} abiertos)"
        )
    return True, ""
