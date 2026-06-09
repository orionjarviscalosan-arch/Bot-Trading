"""
backtest.py — Motor de backtesting con rangos de fechas personalizados
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from bot.database import compute_metrics
from bot.data_fetcher import fetch_ohlcv_range, estimate_bars_between
from bot.signal_engine import (
    compute_all, get_signal, calc_confluence_score,
    calc_atr, calc_wavetrend, calc_rsi, calc_mfi, calc_pivots,
    calc_structure, calc_fvg, calc_trail, ema,
)
from bot.order_manager import check_exit_conditions, calc_trade_pnl, compute_trailing_stop
from bot.backtest_costs import calc_trade_costs, calc_risk_position_size
from bot.nextwave_v2 import get_nextwave_signal, compute_nextwave_stops
from bot.regime_hmm import (
    compute_regime_series, get_hmm_pure_signal,
    hmm_allows_long, hmm_allows_short, merge_hmm_params,
)
from bot.strategy_types import apply_strategy_type_params, STRATEGY_TYPES
from bot.csv_data_loader import load_btc_csv, default_csv_paths
from bot.ema_rsi_atr import run_ema_rsi_atr_backtest, DEFAULT_EMA_RSI_ATR_PARAMS
from config import POSITION_SIZE_PCT

logger = logging.getLogger(__name__)

MAX_BACKTEST_BARS = 80_000
WARMUP_EXTRA_BARS = 400


def _as_utc_timestamp(value) -> pd.Timestamp:
    """Normaliza datetime/str/Timestamp a UTC sin duplicar tzinfo."""
    ts = pd.Timestamp(value)
    if ts.tz is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _iso_ts(ts) -> str:
    if hasattr(ts, "isoformat"):
        return ts.isoformat()
    return str(ts)


def _slice_htf(df_htf: pd.DataFrame, ts) -> pd.DataFrame:
    return df_htf[df_htf.index <= ts]


def _build_htf_frame(df_htf: pd.DataFrame, params: dict) -> pd.DataFrame:
    p = params
    return pd.DataFrame({
        "htf_fast":  ema(df_htf["close"], p["htf_fast"]),
        "htf_slow":  ema(df_htf["close"], p["htf_slow"]),
        "htf_trend": ema(df_htf["close"], p["htf_trend"]),
        "htf_close": df_htf["close"],
    }, index=df_htf.index)


def _precompute_ltf_frame(df_ltf: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Calcula todos los indicadores LTF una sola vez (O(n) backtest)."""
    p = params
    df = df_ltf.copy()
    atr = calc_atr(df, p["atr_len"])
    wt1, wt2 = calc_wavetrend(df, p["channel_len"], p["avg_len"], p["signal_len"])
    rsi = calc_rsi(df["close"], p["rsi_len"])
    mfi = calc_mfi(df, p["mfi_len"])
    piv_h, piv_l = calc_pivots(df, p["left_bars"], p["right_bars"])
    struct = calc_structure(df, piv_h, piv_l, p["bos_bars_window"])
    fvg = calc_fvg(df, atr, p["fvg_atr_filter"], p["zone_lookback"])
    trail, tdir = calc_trail(
        df, atr, p["trail_mult"], p["trail_lookback"],
        p["use_adaptive"], p["adaptive_lb"],
    )
    cw = p.get("cooldown_bars", 4)
    cross_w = p.get("cross_window_bars", cw)
    bull_cross = (wt1 > wt2) & (wt1.shift(1) <= wt2.shift(1))
    bear_cross = (wt1 < wt2) & (wt1.shift(1) >= wt2.shift(1))
    price_range = df["high"].rolling(20).max() - df["low"].rolling(20).min()
    atr_ratio = price_range / atr.replace(0, np.nan)

    df["wt1"] = wt1
    df["wt2"] = wt2
    df["rsi"] = rsi
    df["mfi"] = mfi
    df["atr"] = atr
    df["atr_ratio"] = atr_ratio
    df["trail_level"] = trail
    df["trail_dir"] = tdir
    df["bull_cross_recent"] = bull_cross.rolling(cross_w).max().astype(bool)
    df["bear_cross_recent"] = bear_cross.rolling(cross_w).max().astype(bool)
    for col in struct.columns:
        df[col] = struct[col]
    for col in fvg.columns:
        df[col] = fvg[col]
    return df


def _state_at_index(
    df_ltf: pd.DataFrame,
    htf_frame: pd.DataFrame,
    params: dict,
    i: int,
    regime: str | None = None,
) -> dict:
    row = df_ltf.iloc[i]
    ts = df_ltf.index[i]
    htf_slice = htf_frame[htf_frame.index <= ts]
    row_htf = htf_slice.iloc[-1] if len(htf_slice) else htf_frame.iloc[0]
    score = calc_confluence_score(row, row_htf, params)
    if regime:
        score = dict(score)
        score["hmm_regime"] = regime

    price = float(row["close"])
    trail_level = float(row["trail_level"])
    atr_val = float(row["atr"])
    trail_dir = int(row["trail_dir"])
    rr = params["rr_ratio"]

    if params.get("nextwave_v2"):
        long_sl, long_tp, short_sl, short_tp = compute_nextwave_stops(
            df_ltf, i, params, price, atr_val, trail_level, trail_dir)
    else:
        sl_buffer = params.get("sl_buffer", 0.2)
        long_sl = trail_level - atr_val * sl_buffer
        long_tp = price + (price - long_sl) * rr
        short_sl = trail_level + atr_val * sl_buffer
        short_tp = price - (short_sl - price) * rr

    return {
        "timestamp": ts,
        "price": price,
        "atr": atr_val,
        "trail_level": trail_level,
        "trail_dir": trail_dir,
        "long_sl": round(long_sl, 2),
        "long_tp": round(long_tp, 2),
        "short_sl": round(short_sl, 2),
        "short_tp": round(short_tp, 2),
        "score": score,
    }


def _apply_hmm_filter(signal: str, regime: str, params: dict) -> str:
    if signal == "long" and not hmm_allows_long(regime, params):
        return "none"
    if signal == "short" and not hmm_allows_short(regime, params):
        return "none"
    return signal


def run_simulation(
    df_ltf: pd.DataFrame,
    df_htf: pd.DataFrame,
    params: dict,
    strategy_type: str = "confluence",
    start_idx: int | None = None,
    end_idx: int | None = None,
    capital: float = 10000.0,
    regime_series: pd.Series | None = None,
) -> dict:
    """
    Simula trades sobre datos históricos.
    Devuelve metrics, trades (lista detallada) y equity_curve.
    """
    params = apply_strategy_type_params(params, strategy_type)
    cfg = STRATEGY_TYPES.get(strategy_type, STRATEGY_TYPES["confluence"])
    warmup = max(int(params.get("min_ltf_bars", 200)), 300)
    start = start_idx if start_idx is not None else warmup
    end = end_idx if end_idx is not None else len(df_ltf)
    use_risk_sizing = params.get("risk_pct") is not None
    initial_equity = float(params.get("initial_capital", capital))

    if regime_series is None and params.get("use_hmm_regime"):
        regime_series = compute_regime_series(df_ltf, params)

    ltf_frame = _precompute_ltf_frame(df_ltf, params)
    htf_frame = _build_htf_frame(df_htf, params)

    trades: list[dict] = []
    equity_curve: list[dict] = []
    pos = None
    last_long = None
    last_short = None
    bar_i = 0
    equity = initial_equity
    total_commission = 0.0
    is_nextwave = cfg.get("nextwave_v2") or params.get("nextwave_v2")
    prev_regime = None

    for i in range(start, end):
        ts = df_ltf.index[i]
        regime = "range"
        if regime_series is not None and i < len(regime_series):
            regime = str(regime_series.iloc[i])

        try:
            state = _state_at_index(ltf_frame, htf_frame, params, i, regime)
        except Exception:
            continue

        price = state["price"]
        trail_lv = state["trail_level"]
        trail_dir = state["trail_dir"]
        sc = state["score"]

        open_trade = None
        if pos is not None:
            open_trade = {
                "side": pos["side"],
                "stop_loss": pos["sl"],
                "take_profit": pos["tp"],
            }

        if cfg.get("hmm_pure"):
            signal = get_hmm_pure_signal(
                regime, prev_regime,
                pos is not None,
                pos["side"] if pos else None,
            )
        elif is_nextwave:
            signal = get_nextwave_signal(
                state, params, last_long, last_short, bar_i, open_trade)
            if params.get("use_hmm_regime"):
                signal = _apply_hmm_filter(signal, regime, params)
        else:
            signal = get_signal(state, params, last_long, last_short, bar_i, open_trade)
            if params.get("use_hmm_regime"):
                signal = _apply_hmm_filter(signal, regime, params)

        prev_regime = regime

        if pos is not None:
            exit_reason = check_exit_conditions(
                price, open_trade, trail_lv, trail_dir, score=sc, params=params)

            if exit_reason or signal == "close":
                reason = exit_reason or "regime_flip"
                gross_pnl, pnl_pct = calc_trade_pnl(
                    pos["entry"], price, pos["qty"], pos["side"])
                comm, slip = calc_trade_costs(pos["entry"], price, pos["qty"], params)
                net_pnl = gross_pnl - comm - slip
                total_commission += comm
                equity += net_pnl
                trades.append({
                    "entry_time": _iso_ts(pos["entry_time"]),
                    "exit_time": _iso_ts(ts),
                    "side": pos["side"],
                    "entry_price": pos["entry"],
                    "exit_price": price,
                    "pnl_usdt": round(net_pnl, 2),
                    "pnl_pct": round(pnl_pct, 4),
                    "commission": round(comm, 2),
                    "exit_reason": reason,
                    "hmm_regime": regime,
                })
                equity_curve.append({
                    "time": _iso_ts(ts),
                    "equity": round(equity - initial_equity, 2),
                })
                pos = None
            else:
                new_sl = compute_trailing_stop(trail_lv, state["atr"], pos["side"])
                if pos["side"] == "short" and new_sl < pos["sl"]:
                    pos["sl"] = new_sl
                elif pos["side"] == "long" and new_sl > pos["sl"]:
                    pos["sl"] = new_sl

        if signal == "long" and pos is None:
            sl, tp = state["long_sl"], state["long_tp"]
            if use_risk_sizing:
                qty = calc_risk_position_size(equity, price, sl, params)
            else:
                pct = params.get("position_size_pct", POSITION_SIZE_PCT)
                qty = (equity * pct) / price
            if qty <= 0:
                bar_i += 1
                continue
            pos = {
                "side": "long",
                "entry": price,
                "entry_time": ts,
                "sl": sl,
                "tp": tp if params.get("use_take_profit", True) else None,
                "qty": qty,
            }
            last_long = bar_i

        elif signal == "short" and pos is None:
            sl, tp = state["short_sl"], state["short_tp"]
            if use_risk_sizing:
                qty = calc_risk_position_size(equity, price, sl, params)
            else:
                pct = params.get("position_size_pct", POSITION_SIZE_PCT)
                qty = (equity * pct) / price
            if qty <= 0:
                bar_i += 1
                continue
            pos = {
                "side": "short",
                "entry": price,
                "entry_time": ts,
                "sl": sl,
                "tp": tp if params.get("use_take_profit", True) else None,
                "qty": qty,
            }
            last_short = bar_i

        bar_i += 1

    if pos:
        last_price = float(df_ltf["close"].iloc[end - 1])
        last_ts = df_ltf.index[end - 1]
        gross_pnl, pnl_pct = calc_trade_pnl(
            pos["entry"], last_price, pos["qty"], pos["side"])
        comm, slip = calc_trade_costs(pos["entry"], last_price, pos["qty"], params)
        net_pnl = gross_pnl - comm - slip
        total_commission += comm
        equity += net_pnl
        trades.append({
            "entry_time": _iso_ts(pos["entry_time"]),
            "exit_time": _iso_ts(last_ts),
            "side": pos["side"],
            "entry_price": pos["entry"],
            "exit_price": last_price,
            "pnl_usdt": round(net_pnl, 2),
            "pnl_pct": round(pnl_pct, 4),
            "commission": round(comm, 2),
            "exit_reason": "end_of_data",
            "hmm_regime": prev_regime or "range",
        })
        equity_curve.append({
            "time": _iso_ts(last_ts),
            "equity": round(equity - initial_equity, 2),
        })

    metrics = compute_metrics(trades)
    if metrics:
        net = round(equity - initial_equity, 2)
        metrics["net_pnl"] = net
        metrics["total_commission"] = round(total_commission, 2)
        metrics["return_pct"] = round(net / initial_equity, 4) if initial_equity else 0
        metrics["final_equity"] = round(equity, 2)
        if metrics.get("max_drawdown", 0) > 0:
            metrics["calmar_ratio"] = round(
                (net / initial_equity) / metrics["max_drawdown"], 3)

    regime_dist = {}
    if regime_series is not None:
        sliced = regime_series.iloc[start:end]
        for lbl in ("bear", "range", "bull"):
            regime_dist[lbl] = round(float((sliced == lbl).mean()), 4)

    return {
        "metrics": metrics,
        "trades": trades,
        "equity_curve": equity_curve,
        "regime_distribution": regime_dist,
        "bars_simulated": end - start,
    }


def run_backtest(
    symbol: str,
    timeframe: str,
    htf: str,
    params: dict,
    start_date: datetime | str,
    end_date: datetime | str | None = None,
    strategy_type: str = "confluence",
    capital: float = 10000.0,
) -> dict:
    """
    Backtest completo: descarga histórico y simula.
    start_date / end_date: ISO o datetime UTC.
    """
    if isinstance(start_date, str):
        start_date = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
    if end_date is None:
        end_date = datetime.now(timezone.utc)
    elif isinstance(end_date, str):
        end_date = datetime.fromisoformat(end_date.replace("Z", "+00:00"))

    since = _as_utc_timestamp(start_date)
    until = _as_utc_timestamp(end_date)
    if since >= until:
        raise ValueError("start_date debe ser anterior a end_date")

    est_bars = estimate_bars_between(since, until, timeframe)
    warmup_td = pd.Timedelta(days=max(WARMUP_EXTRA_BARS // 24, 30))
    fetch_since = since - warmup_td

    if est_bars > MAX_BACKTEST_BARS:
        raise ValueError(
            f"Periodo demasiado largo (~{est_bars:,} velas {timeframe}). "
            f"Máximo {MAX_BACKTEST_BARS:,}. Usa timeframe mayor (1h, 4h, 1d)."
        )

    logger.info(
        f"Backtest {symbol} {timeframe}/{htf} | {since.date()} → {until.date()} | "
        f"~{est_bars} velas | tipo {strategy_type}")

    df_ltf = fetch_ohlcv_range(symbol, timeframe, fetch_since, until)
    df_htf = fetch_ohlcv_range(symbol, htf, fetch_since, until)

    params = apply_strategy_type_params(params, strategy_type)
    cfg = STRATEGY_TYPES.get(strategy_type, STRATEGY_TYPES["confluence"])

    if cfg.get("ema_rsi_atr"):
        merged = {**DEFAULT_EMA_RSI_ATR_PARAMS, **params}
        start_idx = int(df_ltf.index.searchsorted(since))
        end_idx = int(df_ltf.index.searchsorted(until, side="right"))
        regime_series = None
        if merged.get("use_hmm_regime"):
            regime_series = compute_regime_series(df_ltf, merged)
        result = run_ema_rsi_atr_backtest(
            df_ltf, merged, regime_series=regime_series,
            start_idx=start_idx, end_idx=end_idx,
        )
        result["symbol"] = symbol
        result["timeframe"] = timeframe
        result["htf"] = htf
        result["start_date"] = since.isoformat()
        result["end_date"] = until.isoformat()
        result["strategy_type"] = strategy_type
        result["capital"] = float(merged.get("initial_capital", capital))
        result["bars_fetched"] = len(df_ltf)
        result["data_source"] = "binance"
        return result

    start_idx = int(df_ltf.index.searchsorted(since))
    start_idx = max(start_idx, max(int(params.get("min_ltf_bars", 200)), 300))

    capital = float(params.get("initial_capital", capital))
    regime_series = None
    if params.get("use_hmm_regime"):
        regime_series = compute_regime_series(df_ltf, params)

    result = run_simulation(
        df_ltf, df_htf, params,
        strategy_type=strategy_type,
        start_idx=start_idx,
        capital=capital,
        regime_series=regime_series,
    )
    result["symbol"] = symbol
    result["timeframe"] = timeframe
    result["htf"] = htf
    result["start_date"] = since.isoformat()
    result["end_date"] = until.isoformat()
    result["strategy_type"] = strategy_type
    result["capital"] = capital
    result["bars_fetched"] = len(df_ltf)
    return result


def _resolve_csv_path(timeframe: str, params: dict) -> str | None:
    explicit = params.get("csv_path")
    if explicit and os.path.isfile(explicit):
        return explicit
    paths = default_csv_paths()
    path = paths.get(timeframe)
    if path and os.path.isfile(path):
        return path
    win = os.path.join(r"C:\Users\cayet\Downloads", f"btc_{timeframe}_data_2018_to_2025.csv")
    return win if os.path.isfile(win) else None


def run_backtest_csv(
    timeframe: str,
    params: dict,
    start_date: datetime | str,
    end_date: datetime | str | None = None,
    strategy_type: str = "ema_rsi_atr",
    csv_path: str | None = None,
) -> dict:
    """Backtest EMA-RSI-ATR desde CSV local (Binance export)."""
    params = apply_strategy_type_params(params, strategy_type)
    merged = {**DEFAULT_EMA_RSI_ATR_PARAMS, **params}
    path = csv_path or _resolve_csv_path(timeframe, merged)
    if not path:
        raise FileNotFoundError(
            f"No hay CSV para {timeframe}. Sube btc_{timeframe}_data_2018_to_2025.csv "
            "o indica csv_path en params."
        )

    if isinstance(start_date, str):
        start_date = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
    if end_date is None:
        end_date = datetime.now(timezone.utc)
    elif isinstance(end_date, str):
        end_date = datetime.fromisoformat(end_date.replace("Z", "+00:00"))

    since = _as_utc_timestamp(start_date)
    until = _as_utc_timestamp(end_date)

    df = load_btc_csv(path)
    start_idx = int(df.index.searchsorted(since))
    end_idx = int(df.index.searchsorted(until, side="right"))
    if end_idx - start_idx < 100:
        raise ValueError(f"Datos insuficientes tras filtrar fechas ({end_idx - start_idx} velas).")

    regime_series = None
    if merged.get("use_hmm_regime"):
        regime_series = compute_regime_series(df, merged)

    result = run_ema_rsi_atr_backtest(
        df, merged, regime_series=regime_series,
        start_idx=start_idx, end_idx=end_idx,
    )
    result["symbol"] = merged.get("symbol", "BTC/USDT")
    result["timeframe"] = timeframe
    result["htf"] = merged.get("htf", "—")
    result["start_date"] = since.isoformat()
    result["end_date"] = until.isoformat()
    result["strategy_type"] = strategy_type
    result["capital"] = float(merged.get("initial_capital", 1000))
    result["bars_fetched"] = len(df)
    result["data_source"] = "csv"
    result["csv_path"] = path
    return result
