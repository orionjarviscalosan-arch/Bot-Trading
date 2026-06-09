"""
chart_payload.py — Serializa OHLCV y marcadores para el gráfico TradingView
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

TIMEFRAME_TO_BINANCE = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "8h": "8h",
    "12h": "12h", "1d": "1d",
}

TIMEFRAME_TO_TV_RESOLUTION = {
    "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30",
    "1h": "60", "2h": "120", "4h": "240", "6h": "360", "8h": "480",
    "12h": "720", "1d": "1D",
}


def symbol_to_binance(symbol: str) -> str:
    return symbol.replace("/", "").upper()


def _to_unix_seconds(ts) -> int | None:
    if ts is None or (isinstance(ts, float) and pd.isna(ts)):
        return None
    if isinstance(ts, str):
        ts = pd.to_datetime(ts, utc=True)
    elif getattr(ts, "tzinfo", None) is None:
        ts = pd.Timestamp(ts).tz_localize("UTC")
    return int(ts.timestamp())


def ohlcv_to_bars(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    bars = []
    for ts, row in df.iterrows():
        t = _to_unix_seconds(ts)
        if t is None:
            continue
        bars.append({
            "time": t,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row.get("volume", 0)),
        })
    return bars


def _side(row) -> str:
    side = row.get("side") if hasattr(row, "get") else None
    return side if side in ("long", "short") else "long"


def build_chart_payload(
    ohlcv: pd.DataFrame,
    trades: pd.DataFrame,
    open_trades: pd.DataFrame,
    symbol: str,
    timeframe: str,
    signals: pd.DataFrame | None = None,
    show_unacted_signals: bool = False,
) -> dict:
    """Payload JSON para Lightweight Charts o Charting Library."""
    markers: list[dict] = []
    shapes: list[dict] = []
    price_lines: list[dict] = []
    mark_id = 0

    def add_marker(time_s, price, label, text, color, kind):
        nonlocal mark_id
        if time_s is None:
            return
        mark_id += 1
        entry = {
            "id": str(mark_id),
            "time": time_s,
            "label": label,
            "text": text,
            "color": color,
            "kind": kind,
        }
        if price is not None and not (isinstance(price, float) and pd.isna(price)):
            entry["price"] = float(price)
        markers.append(entry)
        shapes.append(entry)

    closed = pd.DataFrame()
    if not trades.empty and "symbol" in trades.columns:
        sym = trades[trades["symbol"] == symbol]
        if not sym.empty and "exit_time" in sym.columns:
            closed = sym[sym["exit_time"].notna()].copy()

    if not closed.empty:
        for _, row in closed.iterrows():
            side = _side(row)
            entry_t = _to_unix_seconds(row.get("entry_time"))
            exit_t = _to_unix_seconds(row.get("exit_time"))
            entry_p = row.get("entry_price")
            exit_p = row.get("exit_price")
            pnl = row.get("pnl_usdt") or 0

            if side == "short":
                add_marker(entry_t, entry_p, "S", f"SHORT @ {entry_p:.4f}", "#ef4444", "entry_short")
            else:
                add_marker(entry_t, entry_p, "L", f"LONG @ {entry_p:.4f}", "#22c55e", "entry_long")

            exit_color = "#22c55e" if pnl > 0 else "#ef4444"
            reason = row.get("exit_reason") or "exit"
            add_marker(
                exit_t, exit_p, "X",
                f"Salida ({reason}) PnL {pnl:+.2f}",
                exit_color, "exit",
            )

    open_sym = pd.DataFrame()
    if not open_trades.empty and "symbol" in open_trades.columns:
        open_sym = open_trades[open_trades["symbol"] == symbol].copy()

    for _, row in open_sym.iterrows():
        side = _side(row)
        entry_t = _to_unix_seconds(row.get("entry_time"))
        entry_p = row.get("entry_price")
        sl = row.get("stop_loss")
        tp = row.get("take_profit")
        label = "L" if side != "short" else "S"
        color = "#22c55e" if side != "short" else "#ef4444"
        add_marker(
            entry_t, entry_p, label,
            f"Abierta {side.upper()} @ {entry_p:.4f}",
            color, f"open_{side}",
        )
        if pd.notna(sl):
            price_lines.append({
                "price": float(sl),
                "color": "#ef4444",
                "title": f"SL {side.upper()}",
                "lineStyle": 2,
            })
        if pd.notna(tp):
            price_lines.append({
                "price": float(tp),
                "color": "#22c55e",
                "title": f"TP {side.upper()}",
                "lineStyle": 2,
            })

    if signals is not None and not signals.empty and "symbol" in signals.columns:
        sig = signals[
            (signals["symbol"] == symbol)
            & signals["direction"].isin(["long", "short"])
        ].copy()
        if not show_unacted_signals and "acted_on" in sig.columns:
            sig = sig[sig["acted_on"].astype(bool)]

        for _, row in sig.iterrows():
            ts = _to_unix_seconds(row.get("timestamp"))
            direction = row.get("direction")
            bull = row.get("score_bull", "—")
            bear = row.get("score_bear", "—")
            if direction == "short":
                add_marker(ts, None, "s", f"Señal SHORT B{bear}", "#f87171", "signal_short")
            else:
                add_marker(ts, None, "l", f"Señal LONG B{bull}", "#86efac", "signal_long")

    # Señales sin precio: usar close de la vela más cercana
    if not ohlcv.empty and markers:
        close_by_time = {b["time"]: b["close"] for b in ohlcv_to_bars(ohlcv)}
        sorted_times = sorted(close_by_time.keys())
        for m in markers:
            if "price" in m:
                continue
            t = m["time"]
            if not sorted_times:
                continue
            nearest = min(sorted_times, key=lambda x: abs(x - t))
            m["price"] = close_by_time[nearest]

    binance_sym = symbol_to_binance(symbol)
    interval = TIMEFRAME_TO_BINANCE.get(timeframe, timeframe)
    resolution = TIMEFRAME_TO_TV_RESOLUTION.get(timeframe, "60")

    return {
        "symbol": symbol,
        "binanceSymbol": binance_sym,
        "timeframe": timeframe,
        "interval": interval,
        "resolution": resolution,
        "bars": ohlcv_to_bars(ohlcv),
        "markers": markers,
        "shapes": shapes,
        "priceLines": price_lines,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }


def payload_to_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
