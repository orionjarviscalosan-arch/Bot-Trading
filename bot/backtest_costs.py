"""
backtest_costs.py — Comisiones, slippage, apalancamiento y sizing por riesgo
"""
from __future__ import annotations


def calc_trade_costs(
    entry: float,
    exit_price: float,
    qty: float,
    params: dict,
) -> tuple[float, float]:
    """Devuelve (comisión total, slippage total) en USDT."""
    comm_pct = float(params.get("commission_pct", 0.001))
    slip_pct = float(params.get("slippage_pct", 0.0001))
    notional_entry = entry * qty
    notional_exit = exit_price * qty
    commission = (notional_entry + notional_exit) * comm_pct
    slippage = (notional_entry + notional_exit) * slip_pct
    return commission, slippage


def calc_risk_position_size(
    equity: float,
    entry: float,
    stop: float,
    params: dict,
) -> float:
    """Tamaño por riesgo % del equity con tope de apalancamiento."""
    risk_pct = float(params.get("risk_pct", 1.0))
    leverage = float(params.get("leverage", 1.0))
    risk_per_unit = abs(entry - stop)
    if risk_per_unit <= 0 or equity <= 0:
        return 0.0
    risk_cash = equity * risk_pct / 100.0
    qty = risk_cash / risk_per_unit
    max_qty = (equity * leverage) / entry if entry > 0 else 0.0
    return min(qty, max_qty)
