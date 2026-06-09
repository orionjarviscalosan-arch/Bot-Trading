"""
ema_rsi_atr.py — Estrategia momentum EMA + RSI + ATR

Long:  EMA rápida > lenta, precio > EMA rápida, RSI en banda alcista, ATR > media
Short: espejo bajista
SL/TP dinámicos por múltiplos de ATR
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.signal_engine import calc_atr, calc_rsi, ema
from bot.backtest_costs import calc_trade_costs, calc_risk_position_size
from bot.database import compute_metrics


DEFAULT_EMA_RSI_ATR_PARAMS = {
    "ema_fast": 21,
    "ema_slow": 55,
    "rsi_len": 14,
    "rsi_long_min": 50,
    "rsi_long_max": 70,
    "rsi_short_min": 30,
    "rsi_short_max": 50,
    "atr_len": 14,
    "atr_ma_len": 20,
    "atr_filter_mult": 1.0,
    "sl_atr_mult": 1.5,
    "tp_atr_mult": 3.0,
    "allow_longs": True,
    "allow_shorts": True,
    "use_hmm_regime": False,
    "risk_pct": 1.0,
    "leverage": 3.0,
    "commission_pct": 0.001,
    "slippage_pct": 0.0001,
    "spread_pct": 0.0002,
    "initial_capital": 1000.0,
    "cooldown_bars": 3,
}


def compute_indicators(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    p = {**DEFAULT_EMA_RSI_ATR_PARAMS, **params}
    out = df.copy()
    out["ema_fast"] = ema(out["close"], int(p["ema_fast"]))
    out["ema_slow"] = ema(out["close"], int(p["ema_slow"]))
    out["rsi"] = calc_rsi(out["close"], int(p["rsi_len"]))
    out["atr"] = calc_atr(out, int(p["atr_len"]))
    out["atr_ma"] = out["atr"].rolling(int(p["atr_ma_len"])).mean()
    return out


def bar_signals(row, params: dict) -> tuple[bool, bool]:
    p = {**DEFAULT_EMA_RSI_ATR_PARAMS, **params}
    if pd.isna(row["ema_fast"]) or pd.isna(row["atr_ma"]):
        return False, False

    vol_ok = row["atr"] >= row["atr_ma"] * float(p["atr_filter_mult"])
    if not vol_ok:
        return False, False

    long_trend = row["ema_fast"] > row["ema_slow"] and row["close"] > row["ema_fast"]
    short_trend = row["ema_fast"] < row["ema_slow"] and row["close"] < row["ema_fast"]

    rsi = row["rsi"]
    long_rsi = float(p["rsi_long_min"]) < rsi < float(p["rsi_long_max"])
    short_rsi = float(p["rsi_short_min"]) < rsi < float(p["rsi_short_max"])

    long_sig = bool(p.get("allow_longs", True)) and long_trend and long_rsi
    short_sig = bool(p.get("allow_shorts", True)) and short_trend and short_rsi
    return long_sig, short_sig


def run_ema_rsi_atr_backtest(
    df: pd.DataFrame,
    params: dict,
    regime_series: pd.Series | None = None,
    start_idx: int | None = None,
    end_idx: int | None = None,
) -> dict:
    """Backtest barra a barra con equity compuesta, comisiones y apalancamiento."""
    p = {**DEFAULT_EMA_RSI_ATR_PARAMS, **params}
    ind = compute_indicators(df, p)
    warmup = max(int(p["ema_slow"]) + 10, int(p["atr_ma_len"]) + 5, 60)
    start = start_idx if start_idx is not None else warmup
    end = min(end_idx, len(ind)) if end_idx is not None else len(ind)

    equity = float(p["initial_capital"])
    initial = equity
    pos = None
    trades: list[dict] = []
    equity_curve: list[dict] = []
    total_commission = 0.0
    last_entry_bar = -9999
    cooldown = int(p.get("cooldown_bars", 3))

    def _iso(ts):
        return ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

    for i in range(start, end - 1):
        row = ind.iloc[i]
        nxt = ind.iloc[i + 1]
        ts = ind.index[i + 1]
        entry_px = float(nxt["open"])
        atr = float(row["atr"])
        if atr <= 0 or np.isnan(atr):
            continue

        regime = "range"
        if regime_series is not None and i < len(regime_series):
            regime = str(regime_series.iloc[i])

        long_sig, short_sig = bar_signals(row, p)
        if p.get("use_hmm_regime"):
            if regime == "bear":
                long_sig = False
            if regime == "bull":
                short_sig = False
            if regime == "range" and not p.get("hmm_allow_range_trades", False):
                long_sig = short_sig = False

        if pos is not None:
            side = pos["side"]
            exit_reason = None
            exit_px = entry_px

            if side == "long":
                if float(nxt["low"]) <= pos["sl"]:
                    exit_reason, exit_px = "sl", pos["sl"]
                elif float(nxt["high"]) >= pos["tp"]:
                    exit_reason, exit_px = "tp", pos["tp"]
                elif short_sig:
                    exit_reason, exit_px = "signal_flip", entry_px
            else:
                if float(nxt["high"]) >= pos["sl"]:
                    exit_reason, exit_px = "sl", pos["sl"]
                elif float(nxt["low"]) <= pos["tp"]:
                    exit_reason, exit_px = "tp", pos["tp"]
                elif long_sig:
                    exit_reason, exit_px = "signal_flip", entry_px

            if exit_reason:
                spread = float(p.get("spread_pct", 0))
                exit_px = exit_px * (1 - spread) if side == "long" else exit_px * (1 + spread)
                gross, pnl_pct = _pnl(side, pos["entry"], exit_px, pos["qty"])
                comm, slip = calc_trade_costs(pos["entry"], exit_px, pos["qty"], p)
                net = gross - comm - slip
                total_commission += comm
                equity += net
                trades.append({
                    "entry_time": _iso(pos["entry_time"]),
                    "exit_time": _iso(ts),
                    "side": side,
                    "entry_price": round(pos["entry"], 2),
                    "exit_price": round(exit_px, 2),
                    "pnl_usdt": round(net, 2),
                    "pnl_pct": round(pnl_pct, 4),
                    "commission": round(comm, 2),
                    "exit_reason": exit_reason,
                })
                equity_curve.append({"time": _iso(ts), "equity": round(equity - initial, 2)})
                pos = None

        if pos is None and (i - last_entry_bar) > cooldown:
            spread = float(p.get("spread_pct", 0))
            if long_sig:
                sl = entry_px - atr * float(p["sl_atr_mult"])
                tp = entry_px + atr * float(p["tp_atr_mult"])
                px = entry_px * (1 + spread)
                qty = calc_risk_position_size(equity, px, sl, p)
                if qty > 0:
                    pos = {"side": "long", "entry": px, "entry_time": ts, "sl": sl, "tp": tp, "qty": qty}
                    last_entry_bar = i
            elif short_sig:
                sl = entry_px + atr * float(p["sl_atr_mult"])
                tp = entry_px - atr * float(p["tp_atr_mult"])
                px = entry_px * (1 - spread)
                qty = calc_risk_position_size(equity, px, sl, p)
                if qty > 0:
                    pos = {"side": "short", "entry": px, "entry_time": ts, "sl": sl, "tp": tp, "qty": qty}
                    last_entry_bar = i

    metrics = compute_metrics(trades) if trades else {}
    net = round(equity - initial, 2)
    if metrics:
        metrics["net_pnl"] = net
        metrics["return_pct"] = round(net / initial, 4) if initial else 0
        metrics["total_commission"] = round(total_commission, 2)
        metrics["final_equity"] = round(equity, 2)
        dd = metrics.get("max_drawdown", 0) or 0
        if dd > 0:
            metrics["calmar_ratio"] = round((net / initial) / dd, 3)

    return {
        "metrics": metrics,
        "trades": trades,
        "equity_curve": equity_curve,
        "bars_simulated": end - start,
    }


def _pnl(side: str, entry: float, exit_px: float, qty: float) -> tuple[float, float]:
    if side == "short":
        pnl = (entry - exit_px) * qty
        pct = (entry - exit_px) / entry if entry else 0
    else:
        pnl = (exit_px - entry) * qty
        pct = (exit_px - entry) / entry if entry else 0
    return pnl, pct


def score_backtest(result: dict, min_trades: int = 20) -> float:
    """Score compuesto: Calmar + PF penalizando pocos trades y DD alto."""
    m = result.get("metrics") or {}
    nt = m.get("total_trades", 0)
    if nt < min_trades:
        return -999.0
    calmar = m.get("calmar_ratio", 0) or 0
    pf = m.get("profit_factor", 0) or 0
    ret = m.get("return_pct", 0) or 0
    dd = m.get("max_drawdown", 1) or 1
    if pf < 1.0 or ret <= 0:
        return -500.0 + ret * 100
    return calmar * 2 + pf + ret * 5 - dd * 2
