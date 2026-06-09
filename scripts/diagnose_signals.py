#!/usr/bin/env python3
"""Diagnóstico: por qué no hay señales long/short en cada par."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config as cfg
from bot.data_fetcher import fetch_ohlcv
from bot.signal_engine import compute_all, get_signal
from bot.trading_styles import get_style_config
from bot.database import get_active_params, get_active_param_source, init_db
from bot.style_runtime import init_runtime


def check_long(sc, params):
    threshold = params["score_threshold"]
    bull_margin = params.get("score_bull_margin", 10)
    momentum_min = params.get("momentum_min", -0.5)
    bull, bear = sc["score_bull"], sc["score_bear"]
    checks = {
        f"score_bull>={threshold} ({bull})": bull >= threshold,
        f"bull>bear+{bull_margin} ({bull}>{bear}+{bull_margin})": bull > bear + bull_margin,
        "htf (bull o p1>=min)": (
            sc["htf_bull"] or sc.get("p1_bull", 0) >= params.get("htf_min_score", 12)
        ),
        "struct_bias==1": sc["struct_bias"] == 1,
        "choch|bos+zone": (
            sc["bull_choch_recent"]
            or (sc["bull_bos_recent"] and sc["bull_zone_near"])
        ),
        f"momentum>{momentum_min} ({sc['momentum_raw']})": sc["momentum_raw"] > momentum_min,
        "regime_ok": sc["regime_ok"],
        "trail_dir==1": sc["trail_dir"] == 1,
    }
    return checks


def check_short(sc, params):
    threshold = params["score_threshold"]
    bear_margin = params.get("score_bear_margin", params.get("score_bull_margin", 10))
    momentum_min = params.get("momentum_min", -0.5)
    momentum_max = params.get(
        "momentum_max", -0.01 if momentum_min >= 0 else -momentum_min)
    bull, bear = sc["score_bull"], sc["score_bear"]
    checks = {
        f"score_bear>={threshold} ({bear})": bear >= threshold,
        f"bear>bull+{bear_margin} ({bear}>{bull}+{bear_margin})": bear > bull + bear_margin,
        "htf (bear o p1>=min)": (
            sc["htf_bear"] or sc.get("p1_bear", 0) >= params.get("htf_min_score", 12)
        ),
        "struct_bias==-1": sc["struct_bias"] == -1,
        "choch|bos+zone": (
            sc["bear_choch_recent"]
            or (sc["bear_bos_recent"] and sc["bear_zone_near"])
        ),
        f"momentum<{momentum_max} ({sc['momentum_raw']})": sc["momentum_raw"] < momentum_max,
        "regime_ok": sc["regime_ok"],
        "trail_dir==-1": sc["trail_dir"] == -1,
    }
    return checks


def main():
    init_db()
    rt = init_runtime()
    style = rt.style
    scfg = get_style_config(style)
    params = get_active_params() or rt.signal_params.copy()
    tf, htf = scfg["timeframe"], scfg["htf"]
    source = get_active_param_source() or "runtime"

    print(f"Estilo: {style} | TF {tf} / HTF {htf}")
    print(f"Fuente params: {source}")
    print(f"Umbral score: {params['score_threshold']} | régimen min: {params['regime_min_ratio']}")
    print(f"HTF min score: {params.get('htf_min_score', 12)}")
    print("=" * 70)

    for symbol in cfg.TRADING_PAIRS:
        try:
            df_ltf = fetch_ohlcv(symbol, tf, limit=scfg["candles_lb"])
            df_htf = fetch_ohlcv(symbol, htf, limit=500)
            state = compute_all(df_ltf, df_htf, params)
            sc = state["score"]
            signal = get_signal(state, params, None, None, 999, None)

            print(f"\n{symbol} @ {state['price']:.4f} → señal: {signal.upper()}")
            print(f"  Bull {sc['score_bull']} / Bear {sc['score_bear']} | "
                  f"HTF bull={sc['htf_bull']} bear={sc['htf_bear']} | "
                  f"struct={sc['struct_bias']} trail={'↑' if sc['trail_dir']==1 else '↓'} | "
                  f"regime={'OK' if sc['regime_ok'] else 'NO'}")

            long_c = check_long(sc, params)
            short_c = check_short(sc, params)
            long_ok = all(long_c.values())
            short_ok = all(short_c.values())

            print("  LONG:", "✅ LISTO" if long_ok else "❌ bloqueado por:")
            if not long_ok:
                for k, v in long_c.items():
                    if not v:
                        print(f"    · {k}")

            print("  SHORT:", "✅ LISTO" if short_ok else "❌ bloqueado por:")
            if not short_ok:
                for k, v in short_c.items():
                    if not v:
                        print(f"    · {k}")

        except Exception as e:
            print(f"\n{symbol}: ERROR {e}")


if __name__ == "__main__":
    main()
