"""
Dashboard Streamlit — visualización de trades y señales del Nextwaves Bot
Ejecutar: streamlit run dashboard/app.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

import config as cfg
from dashboard.auth import check_auth, get_cookie_manager, clear_session
from bot.trading_styles import TRADING_STYLES, STYLE_LABELS
from bot.dashboard_data import (
    get_trades_df, get_closed_trades_df, get_open_trades_df,
    get_signals_df, get_metrics, get_bot_status, build_equity_curve,
)

st.set_page_config(
    page_title="Nextwaves Bot Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

EXIT_LABELS = {
    "sl": "Stop Loss",
    "tp": "Take Profit",
    "trail_flip": "Trail Flip",
    "score_bear": "Score bajista",
    "manual": "Manual",
}


def fmt_usdt(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:,.2f} USDT"


def fmt_pct(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:+.2%}"


def main():
    if not check_auth():
        return

    st.title("Nextwaves Bot Dashboard")
    status = get_bot_status()
    active_style = status.get("trading_style", "swing")
    style_label = status.get("style_label", STYLE_LABELS.get(active_style, active_style))
    tf = status.get("timeframe", "4h")
    st.caption(
        f"{cfg.SYMBOL} · **{style_label}** ({tf}) · "
        f"modo: **{status.get('bot_mode', 'shadow')}** · HTF {status.get('htf', '1d')}"
    )

    with st.sidebar:
        st.header("Filtros")
        mode = st.selectbox("Modo operación", ["shadow", "paper", "live"], index=0)
        style_options = list(TRADING_STYLES.keys())
        style_filter = st.selectbox(
            "Estilo (histórico)",
            ["todos"] + style_options,
            format_func=lambda x: "Todos" if x == "todos" else STYLE_LABELS.get(x, x),
        )
        style_param = None if style_filter == "todos" else style_filter
        days = st.slider("Días de historial", 7, 365, 90)
        auto_refresh = st.checkbox("Auto-refresh (60s)", value=False)
        if auto_refresh:
            st.markdown(
                '<meta http-equiv="refresh" content="60">',
                unsafe_allow_html=True,
            )
        if st.button("Actualizar ahora"):
            st.rerun()

        if os.getenv("DASHBOARD_PASSWORD"):
            if st.button("Cerrar sesión"):
                clear_session(get_cookie_manager())
                st.rerun()

        st.divider()
        st.markdown("**Estilos disponibles**")
        for key, sc in TRADING_STYLES.items():
            marker = "▶ " if key == active_style else "  "
            st.caption(f"{marker}**{sc['label']}** — {sc['timeframe']} / HTF {sc['htf']}")
        st.caption(
            "Cambiar estilo/modo: envía comandos al bot en Telegram (/ayuda)."
        )

        st.divider()
        st.markdown("**Acceso seguro**")
        st.caption(
            "Recomendado: túnel SSH\n\n"
            "`ssh -L 8501:localhost:8501 root@tu-vps`"
        )

    metrics = get_metrics(mode, days, style_param)
    closed = get_closed_trades_df(mode, days, style_param)
    open_df = get_open_trades_df(mode)
    if style_param and not open_df.empty and "trading_style" in open_df.columns:
        open_df = open_df[
            (open_df["trading_style"] == style_param) | open_df["trading_style"].isna()]
    signals = get_signals_df(days=min(days, 30))

    # ── Alertas de estado ─────────────────────────────────
    if status.get("bot_killed"):
        st.error(f"Kill switch activo: {status.get('kill_reason', '—')}")
    elif status.get("pause_until"):
        st.warning(f"Bot en pausa hasta: {status.get('pause_until')}")

    # ── KPIs ──────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Trades cerrados", metrics.get("total_trades", 0))
    c2.metric("Win Rate", f"{metrics.get('win_rate', 0):.1%}" if metrics else "—")
    c3.metric("Profit Factor", metrics.get("profit_factor", "—"))
    c4.metric("PnL neto", fmt_usdt(metrics.get("net_pnl")) if metrics else "—")
    c5.metric("Max Drawdown", f"{metrics.get('max_drawdown', 0):.1%}" if metrics else "—")

    # ── Posición abierta ──────────────────────────────────
    st.subheader("Posición abierta")
    if open_df.empty:
        st.info("Sin posición abierta en este modo.")
    else:
        for _, row in open_df.iterrows():
            cols = st.columns(6)
            cols[0].metric("Entrada", fmt_usdt(row["entry_price"]))
            cols[1].metric("SL", fmt_usdt(row["stop_loss"]))
            cols[2].metric("TP", fmt_usdt(row["take_profit"]))
            cols[3].metric("Qty BTC", f"{row['quantity']:.6f}")
            cols[4].metric("Score Bull", int(row["score_bull"]))
            cols[5].metric("Desde", str(row["entry_time"])[:16])

    st.divider()

    tab_equity, tab_trades, tab_signals, tab_reasons = st.tabs(
        ["Curva de equity", "Operaciones", "Señales", "Por motivo de salida"]
    )

    with tab_equity:
        curve = build_equity_curve(closed)
        if curve.empty:
            st.info("Aún no hay trades cerrados para mostrar la curva.")
        else:
            fig = px.area(
                curve, x="exit_time", y="equity",
                title=f"PnL acumulado ({mode}) — últimos {days} días",
                labels={"exit_time": "Fecha cierre", "equity": "PnL acumulado (USDT)"},
            )
            fig.update_layout(hovermode="x unified", height=400)
            fig.add_hline(y=0, line_dash="dot", line_color="gray")
            st.plotly_chart(fig, use_container_width=True)

            # Marcadores entrada/salida en timeline
            markers = closed[["entry_time", "exit_time", "entry_price",
                              "exit_price", "pnl_usdt", "exit_reason"]].copy()
            markers["result"] = markers["pnl_usdt"].apply(
                lambda x: "Ganancia" if x > 0 else "Pérdida")
            fig2 = go.Figure()
            for _, r in markers.iterrows():
                color = "#22c55e" if r["pnl_usdt"] > 0 else "#ef4444"
                fig2.add_trace(go.Scatter(
                    x=[r["entry_time"], r["exit_time"]],
                    y=[r["entry_price"], r["exit_price"]],
                    mode="lines+markers",
                    name=r["exit_reason"],
                    line=dict(color=color, width=2),
                    marker=dict(size=8),
                    hovertemplate=(
                        f"Entry: {r['entry_price']:.2f}<br>"
                        f"Exit: {r['exit_price']:.2f}<br>"
                        f"PnL: {r['pnl_usdt']:+.2f}<extra></extra>"
                    ),
                ))
            fig2.update_layout(
                title="Entradas y salidas (precio)",
                xaxis_title="Tiempo",
                yaxis_title="Precio USDT",
                height=400,
                showlegend=False,
            )
            st.plotly_chart(fig2, use_container_width=True)

    with tab_trades:
        if closed.empty:
            st.info("Sin operaciones cerradas en el periodo seleccionado.")
        else:
            display = closed[[
                "entry_time", "exit_time", "entry_price", "exit_price",
                "pnl_usdt", "pnl_pct", "exit_reason", "quantity",
                "score_bull", "score_bear",
            ]].sort_values("exit_time", ascending=False).copy()
            display["exit_reason"] = display["exit_reason"].map(
                lambda x: EXIT_LABELS.get(x, x))
            display["pnl_usdt"] = display["pnl_usdt"].round(2)
            display["pnl_pct"] = display["pnl_pct"].apply(
                lambda x: f"{x:+.2%}" if pd.notna(x) else "—")

            def color_pnl(val):
                if isinstance(val, (int, float)):
                    color = "#166534" if val > 0 else "#991b1b"
                    return f"color: {color}; font-weight: 600"
                return ""

            st.dataframe(
                display.style.map(color_pnl, subset=["pnl_usdt"]),
                use_container_width=True,
                hide_index=True,
            )

    with tab_signals:
        if signals.empty:
            st.info("Sin señales registradas aún. El bot evalúa en cada cierre de vela 4H.")
        else:
            sig_display = signals[[
                "timestamp", "direction", "score_bull", "score_bear",
                "trail_dir", "htf_bull", "regime_ok", "acted_on",
            ]].copy()
            st.dataframe(sig_display, use_container_width=True, hide_index=True)

            longs = (signals["direction"] == "long").sum()
            acted = signals["acted_on"].astype(bool).sum()
            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("Señales long", int(longs))
            sc2.metric("Actuadas", int(acted))
            sc3.metric("Total señales", len(signals))

    with tab_reasons:
        if closed.empty:
            st.info("Sin datos de cierre.")
        else:
            by_reason = closed.groupby("exit_reason")["pnl_usdt"].agg(
                ["count", "sum", "mean"]).reset_index()
            by_reason.columns = ["Motivo", "Trades", "PnL total", "PnL medio"]
            by_reason["Motivo"] = by_reason["Motivo"].map(
                lambda x: EXIT_LABELS.get(x, x))

            col_a, col_b = st.columns(2)
            with col_a:
                fig3 = px.bar(
                    by_reason, x="Motivo", y="Trades",
                    title="Trades por motivo de salida",
                    color="Motivo",
                )
                st.plotly_chart(fig3, use_container_width=True)
            with col_b:
                fig4 = px.bar(
                    by_reason, x="Motivo", y="PnL total",
                    title="PnL total por motivo",
                    color="PnL total",
                    color_continuous_scale=["red", "yellow", "green"],
                )
                st.plotly_chart(fig4, use_container_width=True)


if __name__ == "__main__":
    main()
