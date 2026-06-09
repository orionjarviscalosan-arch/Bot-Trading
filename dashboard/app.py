"""
Dashboard Streamlit — visualización de trades y señales del Nextwaves Bot
Ejecutar: streamlit run dashboard/app.py
"""
import html
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
from dashboard.prefs import get_prefs, save_prefs
from bot.trading_styles import TRADING_STYLES, STYLE_LABELS
from bot.dashboard_data import (
    get_trades_df, get_closed_trades_df, get_open_trades_df,
    get_signals_df, get_metrics, get_bot_status, build_equity_curve,
    enrich_open_trades, get_db_summary,
)
from dashboard.chart_payload import build_chart_payload
from dashboard.chart_renderer import render_chart, CHART_ENGINES
from dashboard.charts import get_chart_ohlcv, CHART_CANDLE_LIMIT

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
    "score_bull": "Score alcista",
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


def fmt_num(v, decimals=2):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:,.{decimals}f}"


def fmt_dt(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d %H:%M:%S UTC")
    return str(v)


def _pnl_row_class(pnl) -> str:
    if pnl is None or (isinstance(pnl, float) and pd.isna(pnl)):
        return "row-neutral"
    if pnl > 0:
        return "row-profit"
    if pnl < 0:
        return "row-loss"
    return "row-neutral"


def _pnl_cell_class(pnl) -> str:
    if pnl is None or (isinstance(pnl, float) and pd.isna(pnl)):
        return ""
    return "pnl-pos" if pnl > 0 else "pnl-neg" if pnl < 0 else ""


def render_open_positions_table(open_df: pd.DataFrame) -> None:
    """Tabla HTML con scroll lateral y colores según PnL no realizado."""
    enriched, prices = enrich_open_trades(open_df)

    if not prices or all(v is None for v in prices.values()):
        st.warning(
            "No se pudo obtener el precio actual de Binance. "
            "Se muestran los datos de la posición sin PnL en vivo."
        )
    elif prices:
        price_lines = [
            f"**{sym}**: {fmt_num(px)}"
            for sym, px in prices.items() if px is not None
        ]
        if price_lines:
            st.caption("Precios actuales · " + " · ".join(price_lines))

    columns = [
        ("trade_id", "ID"),
        ("symbol", "Símbolo"),
        ("side", "Lado"),
        ("trading_style", "Estilo"),
        ("timeframe", "TF"),
        ("entry_time", "Entrada"),
        ("entry_price", "Precio entrada"),
        ("stop_loss", "Stop Loss"),
        ("take_profit", "Take Profit"),
        ("trail_level", "Trail"),
        ("quantity", "Cantidad"),
        ("score_bull", "Score Bull"),
        ("score_bear", "Score Bear"),
        ("precio_actual", "Precio actual"),
        ("pnl_no_realizado", "PnL no realizado"),
        ("pnl_pct_no_realizado", "PnL %"),
    ]

    header = "".join(
        f"<th>{html.escape(label)}</th>" for _, label in columns
    )

    rows_html = []
    for _, row in enriched.iterrows():
        pnl = row.get("pnl_no_realizado")
        row_class = _pnl_row_class(pnl)
        cells = []

        for key, _ in columns:
            val = row.get(key)
            if key == "trading_style" and pd.notna(val):
                text = STYLE_LABELS.get(str(val), str(val))
            elif key == "entry_time":
                text = fmt_dt(val)
            elif key in ("entry_price", "stop_loss", "take_profit", "trail_level", "precio_actual"):
                text = fmt_num(val)
            elif key == "quantity":
                text = fmt_num(val, 6)
            elif key == "pnl_no_realizado":
                text = fmt_usdt(val) if pd.notna(val) else "—"
            elif key == "pnl_pct_no_realizado":
                text = fmt_pct(val) if pd.notna(val) else "—"
            elif key in ("score_bull", "score_bear"):
                text = str(int(val)) if pd.notna(val) else "—"
            else:
                text = "—" if val is None or (isinstance(val, float) and pd.isna(val)) else str(val)

            css = ""
            if key in ("pnl_no_realizado", "pnl_pct_no_realizado") and pd.notna(pnl):
                css = f' class="{_pnl_cell_class(pnl)}"'

            cells.append(f"<td{css}>{html.escape(text)}</td>")

        rows_html.append(f'<tr class="{row_class}">{"".join(cells)}</tr>')

    table_html = f"""
    <style>
    .nw-table-wrap {{
        overflow-x: auto;
        width: 100%;
        margin: 0.5rem 0 1rem;
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 8px;
    }}
    .nw-positions-table {{
        width: max-content;
        min-width: 100%;
        border-collapse: collapse;
        font-size: 0.875rem;
    }}
    .nw-positions-table th,
    .nw-positions-table td {{
        padding: 10px 14px;
        white-space: nowrap;
        border-bottom: 1px solid rgba(255,255,255,0.08);
        text-align: right;
    }}
    .nw-positions-table th:first-child,
    .nw-positions-table td:first-child,
    .nw-positions-table th:nth-child(2),
    .nw-positions-table td:nth-child(2),
    .nw-positions-table th:nth-child(3),
    .nw-positions-table td:nth-child(3),
    .nw-positions-table th:nth-child(4),
    .nw-positions-table td:nth-child(4) {{
        text-align: left;
    }}
    .nw-positions-table th {{
        background: rgba(255,255,255,0.06);
        font-weight: 600;
        position: sticky;
        top: 0;
        z-index: 1;
    }}
    .nw-positions-table tr.row-profit {{
        background: rgba(34, 197, 94, 0.14);
    }}
    .nw-positions-table tr.row-loss {{
        background: rgba(239, 68, 68, 0.14);
    }}
    .nw-positions-table tr.row-neutral {{
        background: transparent;
    }}
    .nw-positions-table td.pnl-pos {{
        color: #22c55e;
        font-weight: 700;
    }}
    .nw-positions-table td.pnl-neg {{
        color: #ef4444;
        font-weight: 700;
    }}
    </style>
    <div class="nw-table-wrap">
        <table class="nw-positions-table">
            <thead><tr>{header}</tr></thead>
            <tbody>{"".join(rows_html)}</tbody>
        </table>
    </div>
    """
    st.markdown(table_html, unsafe_allow_html=True)


def _sync_bot_filters(status: dict) -> tuple[str, str]:
    """Sincroniza modo con Telegram. El filtro de estilo NO se toca (histórico)."""
    active_style = status.get("trading_style", "swing")
    bot_mode = status.get("bot_mode", "shadow")
    mode_options = ["shadow", "paper", "live"]
    if bot_mode not in mode_options:
        bot_mode = "shadow"

    st.session_state["nw_bot_style"] = active_style

    if st.session_state.get("nw_bot_mode_sync") != bot_mode:
        st.session_state["nw_bot_mode_sync"] = bot_mode
        st.session_state["nw_mode_filter"] = bot_mode

    if "nw_style_filter" not in st.session_state:
        st.session_state["nw_style_filter"] = "todos"
    if "nw_mode_filter" not in st.session_state:
        st.session_state["nw_mode_filter"] = bot_mode

    return active_style, bot_mode


def _style_filter_options(active_style: str) -> list[str]:
    others = [s for s in TRADING_STYLES if s not in (active_style, "todos")]
    return ["todos", active_style] + others


def _safe_index(options: list, value, default: int = 0) -> int:
    try:
        return options.index(value)
    except ValueError:
        return default


def _style_filter_label(value: str, active_style: str) -> str:
    if value == "todos":
        return "Todos los estilos (histórico completo)"
    if value == active_style:
        return f"▶ {STYLE_LABELS.get(value, value)} (solo estilo activo bot)"
    return STYLE_LABELS.get(value, value)


def main():
    if not check_auth():
        return

    st.title("Nextwaves Bot Dashboard")
    status = get_bot_status()
    active_style, bot_mode_active = _sync_bot_filters(status)
    style_label = status.get("style_label", STYLE_LABELS.get(active_style, active_style))
    tf = status.get("timeframe", "4h")
    prefs = get_prefs()
    pairs_label = ", ".join(status.get("trading_pairs", cfg.TRADING_PAIRS))
    st.caption(
        f"**{pairs_label}** · **{style_label}** ({tf}) · "
        f"modo: **{status.get('bot_mode', 'shadow')}** · HTF {status.get('htf', '1d')} · "
        f"máx **{status.get('max_active_pairs', cfg.MAX_ACTIVE_PAIRS)}** pares · "
        f"{status.get('position_size_pct', cfg.POSITION_SIZE_PCT):.0%}/par"
    )

    mode_options = ["shadow", "paper", "live"]
    style_options = _style_filter_options(active_style)
    current_style = st.session_state.get("nw_style_filter", active_style)
    if current_style not in style_options:
        current_style = active_style
        st.session_state["nw_style_filter"] = active_style

    with st.sidebar:
        st.header("Filtros")
        st.info(
            f"**Telegram:** {STYLE_LABELS.get(active_style, active_style)} · "
            f"{tf} · modo {bot_mode_active}"
        )

        mode = st.selectbox(
            "Modo operación",
            mode_options,
            index=_safe_index(
                mode_options,
                st.session_state.get("nw_mode_filter", bot_mode_active),
            ),
        )
        st.session_state["nw_mode_filter"] = mode

        style_filter = st.selectbox(
            "Estilo (datos)",
            style_options,
            index=_safe_index(style_options, current_style),
            format_func=lambda x: _style_filter_label(x, active_style),
        )
        st.session_state["nw_style_filter"] = style_filter
        style_param = None if style_filter == "todos" else style_filter

        pair_options = ["todos"] + list(cfg.TRADING_PAIRS)
        symbol_filter = st.selectbox("Par (histórico)", pair_options)
        symbol_param = None if symbol_filter == "todos" else symbol_filter

        days_default = int(prefs.get("days", 90))
        days = st.slider("Días de historial", 7, 365, days_default)

        auto_refresh = st.checkbox(
            "Auto-refresh (60s)",
            value=bool(prefs.get("auto_refresh", False)),
        )

        col_save, col_refresh = st.columns(2)
        with col_save:
            if st.button("Guardar prefs", use_container_width=True):
                save_prefs({
                    **prefs,
                    "auto_refresh": auto_refresh,
                    "days": days,
                    "chart_engine": st.session_state.get(
                        "nw_chart_engine_select",
                        prefs.get("chart_engine", "kline"),
                    ),
                })
                st.success("Guardado en este dispositivo")
        with col_refresh:
            if st.button("Actualizar", use_container_width=True):
                st.rerun()

        if auto_refresh:
            st.markdown(
                '<meta http-equiv="refresh" content="60">',
                unsafe_allow_html=True,
            )
            st.caption("Auto-refresh activo — recarga cada 60 s")

        if auto_refresh != prefs.get("auto_refresh") or days != prefs.get("days"):
            save_prefs({**prefs, "auto_refresh": auto_refresh, "days": days})

        if os.getenv("DASHBOARD_PASSWORD"):
            if st.button("Cerrar sesión"):
                clear_session(get_cookie_manager())
                st.rerun()

        st.divider()
        st.markdown("**Base de datos**")
        db = get_db_summary(mode)
        st.caption(
            f"Total en SQLite: **{db['total_trades']}** trades "
            f"({db['closed_trades']} cerrados · {db['open_trades']} abiertos)"
        )
        if db.get("by_style"):
            parts = [
                f"{STYLE_LABELS.get(k, k)}: {v}"
                for k, v in db["by_style"].items()
            ]
            st.caption("Por estilo: " + " · ".join(parts))
        if db.get("last_trade_time"):
            st.caption(f"Último trade: {db['last_trade_time']}")
        if db.get("last_signal_time"):
            st.caption(f"Última señal: {db['last_signal_time']}")

        st.divider()
        st.markdown("**Pares activos**")
        for sym in cfg.TRADING_PAIRS:
            st.caption(f"· `{sym}`")
        st.caption(
            f"Máx. simultáneos: **{cfg.MAX_ACTIVE_PAIRS}** · "
            f"{cfg.POSITION_SIZE_PCT:.0%} capital/par"
        )

        st.divider()
        st.markdown("**Estilos disponibles**")
        for key, sc in TRADING_STYLES.items():
            marker = "▶ " if key == active_style else "  "
            st.caption(f"{marker}**{sc['label']}** — {sc['timeframe']} / HTF {sc['htf']}")
        st.caption(
            "Cambiar timeframe: Telegram → /1m /5m /15m /day /swing (/tiempo para ver todos)."
        )

        st.divider()
        st.markdown("**Acceso seguro**")
        st.caption(
            "Recomendado: túnel SSH\n\n"
            "`ssh -L 8501:localhost:8501 root@tu-vps`"
        )

    metrics = get_metrics(mode, days, style_param, symbol_param)
    closed = get_closed_trades_df(mode, days, style_param, symbol_param)
    open_df = get_open_trades_df(mode)
    db = get_db_summary(mode)
    if symbol_param and not open_df.empty and "symbol" in open_df.columns:
        open_df = open_df[open_df["symbol"] == symbol_param]
    signals = get_signals_df(days=min(days, 30), limit=500)
    if style_param and not signals.empty and "trading_style" in signals.columns:
        signals = signals[
            (signals["trading_style"] == style_param) | signals["trading_style"].isna()
        ]

    if style_param and db["closed_trades"] > len(closed):
        hidden = db["closed_trades"] - len(closed)
        st.warning(
            f"El filtro de estilo oculta **{hidden}** trade(s) cerrado(s). "
            f"Cambia **Estilo (datos)** a **Todos los estilos (histórico completo)**."
        )

    # ── Alertas de estado ─────────────────────────────────
    if status.get("bot_killed"):
        st.error(f"Kill switch activo: {status.get('kill_reason', '—')}")
    elif status.get("pause_until"):
        st.warning(f"Bot en pausa hasta: {status.get('pause_until')}")

    # ── KPIs ──────────────────────────────────────────────
    open_count = len(open_df)
    max_pairs = status.get("max_active_pairs", cfg.MAX_ACTIVE_PAIRS)
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Posiciones abiertas", f"{open_count}/{max_pairs}")
    c2.metric("Trades cerrados", metrics.get("total_trades", 0))
    c3.metric("Win Rate", f"{metrics.get('win_rate', 0):.1%}" if metrics else "—")
    c4.metric("Profit Factor", metrics.get("profit_factor", "—"))
    c5.metric("PnL neto", fmt_usdt(metrics.get("net_pnl")) if metrics else "—")
    c6.metric("Max Drawdown", f"{metrics.get('max_drawdown', 0):.1%}" if metrics else "—")

    # ── Resumen posiciones abiertas ───────────────────────
    st.subheader("Posiciones abiertas")
    if open_df.empty:
        st.info("Sin posición abierta en este modo.")
    else:
        n = len(open_df)
        st.success(
            f"**{n}** posición(es) abierta(s). "
            "Detalle completo en la pestaña **Posiciones abiertas**."
        )

    st.divider()

    tab_chart, tab_open, tab_equity, tab_trades, tab_signals, tab_reasons = st.tabs(
        ["Gráfico", "Posiciones abiertas", "Curva de equity", "Operaciones", "Señales", "Por motivo de salida"]
    )

    with tab_chart:
        chart_pairs = list(cfg.TRADING_PAIRS)
        default_chart_pair = chart_pairs[0] if chart_pairs else "BTC/USDT"
        if "nw_chart_symbol" not in st.session_state:
            st.session_state["nw_chart_symbol"] = default_chart_pair
        if st.session_state["nw_chart_symbol"] not in chart_pairs:
            st.session_state["nw_chart_symbol"] = default_chart_pair

        c_sym, c_engine, c_sig, c_unacted = st.columns([2, 1, 1, 1])
        with c_sym:
            chart_symbol = st.selectbox(
                "Par del gráfico",
                chart_pairs,
                index=_safe_index(chart_pairs, st.session_state["nw_chart_symbol"]),
                key="nw_chart_symbol_select",
            )
            st.session_state["nw_chart_symbol"] = chart_symbol
        with c_engine:
            engine_options = list(CHART_ENGINES.keys())
            default_engine = prefs.get("chart_engine", "kline")
            if default_engine not in engine_options:
                default_engine = "kline"
            chart_engine = st.selectbox(
                "Motor gráfico",
                engine_options,
                index=_safe_index(engine_options, default_engine),
                format_func=lambda k: CHART_ENGINES[k],
                key="nw_chart_engine_select",
            )
        with c_sig:
            show_signal_markers = st.checkbox(
                "Marcar señales actuadas", value=True, key="nw_chart_signals"
            )
        with c_unacted:
            show_unacted = st.checkbox(
                "Incluir señales no actuadas", value=False, key="nw_chart_unacted"
            )

        chart_tf = status.get("timeframe", tf)
        chart_signals = signals if show_signal_markers else None
        if chart_signals is not None and not chart_signals.empty and "symbol" in chart_signals.columns:
            chart_signals = chart_signals[chart_signals["symbol"] == chart_symbol]

        all_trades = get_trades_df(mode, days, style_param, chart_symbol)
        chart_open = get_open_trades_df(mode)
        if not chart_open.empty and "symbol" in chart_open.columns:
            chart_open = chart_open[chart_open["symbol"] == chart_symbol]

        try:
            ohlcv = get_chart_ohlcv(chart_symbol, chart_tf, CHART_CANDLE_LIMIT)
            payload = build_chart_payload(
                ohlcv=ohlcv,
                trades=all_trades,
                open_trades=chart_open,
                symbol=chart_symbol,
                timeframe=chart_tf,
                signals=chart_signals,
                show_unacted_signals=show_unacted,
                pairs=list(cfg.TRADING_PAIRS),
            )
            engine_used = render_chart(payload, engine=chart_engine, height=680)
            n_closed = len(all_trades[all_trades["exit_time"].notna()]) if not all_trades.empty else 0
            n_open = len(chart_open)
            n_marks = len(payload.get("markers", []))
            engine_label = CHART_ENGINES.get(chart_engine, chart_engine)

            if engine_used == "kline":
                st.caption(
                    f"**{engine_label}** · **{chart_symbol}** · **{chart_tf}** · "
                    f"{n_marks} marcas · modo **{mode}** · "
                    f"{n_closed} cierre(s) · {n_open} abierta(s). "
                    "Indicadores · barra de dibujo · datos Binance en vivo."
                )
            else:
                st.caption(
                    f"**{engine_label}** · **{chart_symbol}** · **{chart_tf}** · "
                    f"{len(payload.get('bars', []))} velas · {n_marks} marcas · "
                    f"modo **{mode}** · {n_closed} cierre(s) · {n_open} abierta(s). "
                    "Zoom con rueda · arrastrar para desplazar."
                )
        except Exception as exc:
            st.error(f"No se pudo cargar el gráfico de {chart_symbol}: {exc}")
            st.caption(
                "Comprueba conexión a Binance y que las API keys del `.env` sean válidas "
                "(solo lectura pública también funciona para OHLCV)."
            )

    with tab_open:
        if open_df.empty:
            st.info("Sin posición abierta en este modo.")
        else:
            render_open_positions_table(open_df)
            st.caption(
                "Verde = ganando · Rojo = perdiendo · Desliza horizontalmente si no caben todas las columnas."
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
                "symbol", "entry_time", "exit_time", "entry_price", "exit_price",
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
            st.info(f"Sin señales registradas en {tf} para el filtro seleccionado.")
        else:
            sig_display = signals[[
                "timestamp", "symbol", "trading_style", "direction",
                "score_bull", "score_bear", "trail_dir", "htf_bull",
                "regime_ok", "acted_on",
            ]].copy()
            if "trading_style" in sig_display.columns:
                sig_display["trading_style"] = sig_display["trading_style"].map(
                    lambda x: STYLE_LABELS.get(str(x), x) if pd.notna(x) else "—"
                )
            st.dataframe(sig_display, use_container_width=True, hide_index=True)

            longs = (signals["direction"] == "long").sum()
            shorts = (signals["direction"] == "short").sum()
            acted = signals["acted_on"].astype(bool).sum()
            sc1, sc2, sc3, sc4 = st.columns(4)
            sc1.metric("Señales long", int(longs))
            sc2.metric("Señales short", int(shorts))
            sc3.metric("Actuadas", int(acted))
            sc4.metric("Total señales", len(signals))

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
