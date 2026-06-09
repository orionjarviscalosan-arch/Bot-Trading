"""
charts.py — Gráfico candlestick Plotly con marcadores de trades del bot
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from bot.data_fetcher import fetch_ohlcv

CHART_CANDLE_LIMIT = 350


@st.cache_data(ttl=60, show_spinner=False)
def get_chart_ohlcv(symbol: str, timeframe: str, limit: int = CHART_CANDLE_LIMIT) -> pd.DataFrame:
    """OHLCV de Binance cacheado 60 s para no saturar la API."""
    return fetch_ohlcv(symbol, timeframe, limit=limit)


def _side_series(df: pd.DataFrame) -> pd.Series:
    if df.empty or "side" not in df.columns:
        return pd.Series(["long"] * len(df), index=df.index)
    return df["side"].fillna("long")


def _price_at_time(ohlcv: pd.DataFrame, ts) -> float:
    try:
        if ohlcv.index.tz is not None and getattr(ts, "tzinfo", None) is None:
            ts = pd.Timestamp(ts).tz_localize("UTC")
        return float(ohlcv["close"].asof(ts))
    except Exception:
        return float(ohlcv["close"].iloc[-1])


def build_trade_chart(
    ohlcv: pd.DataFrame,
    trades: pd.DataFrame,
    open_trades: pd.DataFrame,
    symbol: str,
    timeframe: str,
    signals: pd.DataFrame | None = None,
    show_unacted_signals: bool = False,
) -> go.Figure:
    """Candlestick + entradas/salidas + SL/TP de posiciones abiertas."""
    fig = go.Figure()

    if ohlcv.empty:
        fig.update_layout(
            title=f"{symbol} · {timeframe} — sin datos OHLCV",
            height=520,
            template="plotly_dark",
        )
        return fig

    fig.add_trace(go.Candlestick(
        x=ohlcv.index,
        open=ohlcv["open"],
        high=ohlcv["high"],
        low=ohlcv["low"],
        close=ohlcv["close"],
        name=symbol,
        increasing_line_color="#22c55e",
        decreasing_line_color="#ef4444",
        increasing_fillcolor="#22c55e",
        decreasing_fillcolor="#ef4444",
    ))

    sym_trades = trades[trades["symbol"] == symbol].copy() if not trades.empty else trades
    sym_open = open_trades[open_trades["symbol"] == symbol].copy() if not open_trades.empty else open_trades

    closed = sym_trades[sym_trades["exit_time"].notna()].copy() if not sym_trades.empty else sym_trades
    sides = _side_series(closed) if not closed.empty else pd.Series(dtype=str)

    if not closed.empty:
        long_closed = closed[sides != "short"]
        short_closed = closed[sides == "short"]

        if not long_closed.empty:
            fig.add_trace(go.Scatter(
                x=long_closed["entry_time"],
                y=long_closed["entry_price"],
                mode="markers",
                name="Entrada LONG",
                marker=dict(
                    symbol="triangle-up", size=13, color="#22c55e",
                    line=dict(width=1, color="#ffffff"),
                ),
                customdata=long_closed[["trade_id", "entry_price"]].values,
                hovertemplate=(
                    "LONG entrada<br>"
                    "Precio: %{y:,.4f}<br>"
                    "ID: %{customdata[0]}<extra></extra>"
                ),
            ))

        if not short_closed.empty:
            fig.add_trace(go.Scatter(
                x=short_closed["entry_time"],
                y=short_closed["entry_price"],
                mode="markers",
                name="Entrada SHORT",
                marker=dict(
                    symbol="triangle-down", size=13, color="#ef4444",
                    line=dict(width=1, color="#ffffff"),
                ),
                customdata=short_closed[["trade_id", "entry_price"]].values,
                hovertemplate=(
                    "SHORT entrada<br>"
                    "Precio: %{y:,.4f}<br>"
                    "ID: %{customdata[0]}<extra></extra>"
                ),
            ))

        exit_colors = [
            "#22c55e" if (pnl or 0) > 0 else "#ef4444"
            for pnl in closed["pnl_usdt"].fillna(0)
        ]
        exit_custom = closed.apply(
            lambda r: (
                r.get("exit_reason") or "—",
                r.get("pnl_usdt") if pd.notna(r.get("pnl_usdt")) else 0.0,
                r.get("pnl_pct") if pd.notna(r.get("pnl_pct")) else 0.0,
            ),
            axis=1,
        ).tolist()
        fig.add_trace(go.Scatter(
            x=closed["exit_time"],
            y=closed["exit_price"],
            mode="markers",
            name="Salida",
            marker=dict(
                symbol="circle", size=10, color=exit_colors,
                line=dict(width=1, color="#ffffff"),
            ),
            customdata=exit_custom,
            hovertemplate=(
                "Salida (%{customdata[0]})<br>"
                "Precio: %{y:,.4f}<br>"
                "PnL: %{customdata[1]:+.2f} USDT (%{customdata[2]:+.2%})<extra></extra>"
            ),
        ))

    if not sym_open.empty:
        open_sides = _side_series(sym_open)
        for _, row in sym_open.iterrows():
            side = row.get("side") or "long"
            side_label = side.upper()
            entry = row.get("entry_price")
            sl = row.get("stop_loss")
            tp = row.get("take_profit")

            if pd.notna(entry):
                color = "#22c55e" if side != "short" else "#ef4444"
                symbol_marker = "triangle-up" if side != "short" else "triangle-down"
                fig.add_trace(go.Scatter(
                    x=[row["entry_time"]],
                    y=[entry],
                    mode="markers",
                    name=f"Abierta {side_label}",
                    marker=dict(
                        symbol=symbol_marker, size=16, color=color,
                        line=dict(width=2, color="#fbbf24"),
                    ),
                    showlegend=False,
                    hovertemplate=(
                        f"Posición {side_label} abierta<br>"
                        "Entry: %{y:,.4f}<extra></extra>"
                    ),
                ))

            if pd.notna(sl):
                fig.add_hline(
                    y=float(sl), line_dash="dash", line_color="#ef4444", line_width=1,
                    annotation_text=f"SL {side_label}",
                    annotation_position="right",
                )
            if pd.notna(tp):
                fig.add_hline(
                    y=float(tp), line_dash="dash", line_color="#22c55e", line_width=1,
                    annotation_text=f"TP {side_label}",
                    annotation_position="right",
                )

    if signals is not None and not signals.empty and "symbol" in signals.columns:
        sig = signals[
            (signals["symbol"] == symbol)
            & signals["direction"].isin(["long", "short"])
        ].copy()
        if not show_unacted_signals and "acted_on" in sig.columns:
            sig = sig[sig["acted_on"].astype(bool)]

        if not sig.empty:
            sig_long = sig[sig["direction"] == "long"]
            sig_short = sig[sig["direction"] == "short"]

            if not sig_long.empty:
                fig.add_trace(go.Scatter(
                    x=sig_long["timestamp"],
                    y=[_price_at_time(ohlcv, ts) for ts in sig_long["timestamp"]],
                    mode="markers",
                    name="Señal long",
                    marker=dict(symbol="diamond", size=8, color="rgba(34,197,94,0.45)"),
                    customdata=sig_long[["score_bull", "score_bear", "acted_on"]].values,
                    hovertemplate=(
                        "Señal LONG<br>"
                        "Bull: %{customdata[0]} Bear: %{customdata[1]}<br>"
                        "Actuada: %{customdata[2]}<extra></extra>"
                    ),
                ))

            if not sig_short.empty:
                fig.add_trace(go.Scatter(
                    x=sig_short["timestamp"],
                    y=[_price_at_time(ohlcv, ts) for ts in sig_short["timestamp"]],
                    mode="markers",
                    name="Señal short",
                    marker=dict(symbol="diamond", size=8, color="rgba(239,68,68,0.45)"),
                    customdata=sig_short[["score_bull", "score_bear", "acted_on"]].values,
                    hovertemplate=(
                        "Señal SHORT<br>"
                        "Bull: %{customdata[0]} Bear: %{customdata[1]}<br>"
                        "Actuada: %{customdata[2]}<extra></extra>"
                    ),
                ))

    fig.update_layout(
        title=f"{symbol} · {timeframe} — velas Binance + operaciones del bot",
        xaxis_title="Tiempo (UTC)",
        yaxis_title="Precio",
        height=560,
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=80, t=80, b=40),
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(255,255,255,0.06)")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.06)")

    return fig
