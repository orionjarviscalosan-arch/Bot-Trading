#!/usr/bin/env python3
"""Optimiza EMA-RSI-ATR en CSVs BTC 2018-2025 por temporalidad."""
import itertools
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.csv_data_loader import load_btc_csv, default_csv_paths
from bot.ema_rsi_atr import (
    DEFAULT_EMA_RSI_ATR_PARAMS, run_ema_rsi_atr_backtest, score_backtest,
)
from bot.regime_hmm import compute_regime_series


def _print(msg: str):
    print(msg, flush=True)


def build_combos(full: bool) -> list[dict]:
    if full:
        grid = {
            "ema_fast": [18, 21, 34],
            "ema_slow": [50, 55, 89],
            "sl_atr_mult": [1.2, 1.5, 2.0],
            "tp_atr_mult": [2.5, 3.0, 4.0],
            "atr_filter_mult": [0.95, 1.0, 1.05],
            "cooldown_bars": [2, 4, 8],
            "allow_shorts": [True, False],
        }
    else:
        grid = {
            "ema_fast": [21, 34],
            "ema_slow": [55, 89],
            "sl_atr_mult": [1.5, 2.0],
            "tp_atr_mult": [3.0, 4.0],
            "atr_filter_mult": [1.0, 1.05],
            "cooldown_bars": [4, 8],
            "allow_shorts": [True, False],
        }
    keys = list(grid.keys())
    combos = []
    for combo in itertools.product(*grid.values()):
        params = dict(zip(keys, combo))
        if params["ema_fast"] >= params["ema_slow"]:
            continue
        combos.append(params)
    return combos


def grid_search(df, timeframe: str, use_hmm: bool, combos: list[dict], base: dict) -> tuple[dict, dict, float]:
    best_score = -9999.0
    best_params = {}
    best_result = {}

    regime = None
    if use_hmm:
        hmm_params = {**base, "use_hmm_regime": True}
        _print(f"  Calculando HMM ({len(df)} velas)…")
        regime = compute_regime_series(df, hmm_params)

    for n, combo in enumerate(combos, 1):
        params = {**base, **combo, "use_hmm_regime": use_hmm}
        try:
            result = run_ema_rsi_atr_backtest(df, params, regime_series=regime)
            min_tr = 12 if timeframe in ("4h", "1d") else 25
            sc = score_backtest(result, min_trades=min_tr)
            if sc > best_score:
                best_score = sc
                best_params = params.copy()
                best_result = result
        except Exception:
            continue
        if n % 50 == 0:
            _print(f"    … {n}/{len(combos)}")

    return best_params, best_result, best_score


def main():
    paths = default_csv_paths()
    win_base = r"C:\Users\cayet\Downloads"
    for tf, fn in [("15m", "btc_15m"), ("1h", "btc_1h"), ("4h", "btc_4h"), ("1d", "btc_1d")]:
        alt = os.path.join(win_base, f"{fn}_data_2018_to_2025.csv")
        if os.path.isfile(alt):
            paths[tf] = alt

    order = ["1d", "4h", "1h", "15m"]
    overall_best = None
    results_summary = []
    phase1_winners: list[tuple[str, dict]] = []

    for tf in order:
        path = paths.get(tf)
        if not path or not os.path.isfile(path):
            _print(f"SKIP {tf}: no file")
            continue
        _print(f"\n=== {tf.upper()} ===")
        df = load_btc_csv(path)
        _print(f"  Velas: {len(df)} | {df.index[0].date()} -> {df.index[-1].date()}")

        base = DEFAULT_EMA_RSI_ATR_PARAMS.copy()
        base["initial_capital"] = 1000.0
        base["leverage"] = 3.0

        full_grid = tf == "1d"
        combos = build_combos(full_grid)
        _print(f"  Fase 1 (sin HMM): {len(combos)} combos")

        params, result, sc = grid_search(df, tf, False, combos, base)
        m = result.get("metrics") or {}
        row = {
            "timeframe": tf, "hmm": False, "score": round(sc, 3),
            "trades": m.get("total_trades", 0), "pnl": m.get("net_pnl", 0),
            "return_pct": m.get("return_pct", 0), "pf": m.get("profit_factor", 0),
            "dd": m.get("max_drawdown", 0),
            "params": {k: params.get(k) for k in (
                "ema_fast", "ema_slow", "sl_atr_mult", "tp_atr_mult",
                "atr_filter_mult", "cooldown_bars", "allow_shorts")},
        }
        results_summary.append(row)
            _print(
                f"  sin HMM | score={sc:.2f} | trades={m.get('total_trades')} | "
                f"PnL={m.get('net_pnl')} | PF={m.get('profit_factor')} | DD={m.get('max_drawdown', 0):.1%} | "
                f"params={json.dumps({k: params[k] for k in ('ema_fast','ema_slow','sl_atr_mult','tp_atr_mult','atr_filter_mult','cooldown_bars','allow_shorts') if k in params})}"
            )
        if params:
            phase1_winners.append((tf, params))
        if overall_best is None or sc > overall_best["score"]:
            overall_best = {"score": sc, "timeframe": tf, "params": params, "metrics": m, "hmm": False}

        # HMM solo en 1d/4h/1h con params ganadores + variantes cercanas
        if tf != "15m" and params:
            hmm_base = params.copy()
            hmm_base.update({
                "hmm_train_bars": min(360, len(df) // 4),
                "hmm_refit_every": 84 if tf == "1d" else 42,
                "hmm_allow_range_trades": False,
            })
            hmm_combos = [params]
            _print(f"  Fase 2 (HMM): 1 combo")
            p2, r2, sc2 = grid_search(df, tf, True, hmm_combos, hmm_base)
            m2 = r2.get("metrics") or {}
            results_summary.append({
                "timeframe": tf, "hmm": True, "score": round(sc2, 3),
                "trades": m2.get("total_trades", 0), "pnl": m2.get("net_pnl", 0),
                "return_pct": m2.get("return_pct", 0), "pf": m2.get("profit_factor", 0),
                "dd": m2.get("max_drawdown", 0),
                "params": {k: p2.get(k) for k in (
                    "ema_fast", "ema_slow", "sl_atr_mult", "tp_atr_mult",
                    "atr_filter_mult", "cooldown_bars", "allow_shorts", "use_hmm_regime")},
            })
            _print(
                f"  con HMM | score={sc2:.2f} | trades={m2.get('total_trades')} | "
                f"PnL={m2.get('net_pnl')} | PF={m2.get('profit_factor')} | DD={m2.get('max_drawdown', 0):.1%}"
            )
            if sc2 > (overall_best or {}).get("score", -9999):
                overall_best = {"score": sc2, "timeframe": tf, "params": p2, "metrics": m2, "hmm": True}

    _print("\n" + "=" * 60)
    if overall_best:
        ob = overall_best
        _print(f"MEJOR: {ob['timeframe'].upper()} | HMM={ob.get('hmm')} | score={ob['score']:.2f}")
        _print(f"  PnL: {ob['metrics'].get('net_pnl')} USDT ({ob['metrics'].get('return_pct', 0):.1%})")
        _print(f"  Trades: {ob['metrics'].get('total_trades')} | PF: {ob['metrics'].get('profit_factor')}")
        _print(f"  Max DD: {ob['metrics'].get('max_drawdown', 0):.1%}")

    out_path = os.path.join(os.path.dirname(__file__), "..", "data", "ema_rsi_atr_optimization.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"summary": results_summary, "best": overall_best}, f, indent=2, default=str)
    _print(f"\nGuardado: {out_path}")


if __name__ == "__main__":
    main()
