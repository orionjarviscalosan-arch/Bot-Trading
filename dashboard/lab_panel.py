"""
lab_panel.py — Backtesting con fechas custom y gestión de estrategias nombradas
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import plotly.express as px
import streamlit as st

import config as cfg
from bot.backtest import run_backtest, MAX_BACKTEST_BARS
from bot.data_fetcher import estimate_bars_between
from bot.database import (
    save_strategy, list_strategies, get_strategy, delete_strategy,
    save_backtest_run, list_backtest_runs, init_db,
)
from bot.strategy_types import STRATEGY_TYPES
from bot.trading_styles import (
    TRADING_STYLES, STYLE_LABELS, get_style_config, apply_style_to_signal_params,
)
from bot.regime_hmm import DEFAULT_HMM_PARAMS


def _build_params_from_ui(style: str, strategy_type: str, hmm_extra: dict) -> dict:
    params = apply_style_to_signal_params(cfg._BASE_SIGNAL_PARAMS, style)
    params.update(DEFAULT_HMM_PARAMS)
    params.update(hmm_extra)
    params["use_hmm_regime"] = STRATEGY_TYPES[strategy_type].get("use_hmm_regime", False)
    params["strategy_type"] = strategy_type
    return params


def _safe_style_index(style_key: str) -> int:
    keys = list(TRADING_STYLES.keys())
    normalized = style_key if style_key in keys else cfg.TRADING_STYLE
    return keys.index(normalized) if normalized in keys else 0


def render_strategies_tab():
    st.subheader("Mis estrategias (SQLite)")
    st.caption("Guarda configuraciones con nombre propio para reutilizar en backtests.")

    strategies = list_strategies()

    with st.expander("Crear / editar estrategia", expanded=not strategies):
        edit_id = st.session_state.get("lab_edit_strategy_id")
        edit_row = get_strategy(strategy_id=edit_id) if edit_id else None
        if edit_id and edit_row is None:
            st.session_state.pop("lab_edit_strategy_id", None)
            edit_id = None

        def _ev(key: str, default=""):
            if not edit_row:
                return default
            val = edit_row.get(key)
            return default if val is None else val

        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input(
                "Nombre",
                value=_ev("name"),
                placeholder="BTC HMM 4h 2018-2026",
            )
            strategy_type = st.selectbox(
                "Tipo de estrategia",
                list(STRATEGY_TYPES.keys()),
                index=list(STRATEGY_TYPES.keys()).index(
                    _ev("strategy_type", "confluence")
                ),
                format_func=lambda k: STRATEGY_TYPES[k]["label"],
            )
            style = st.selectbox(
                "Preset base (estilo)",
                list(TRADING_STYLES.keys()),
                index=_safe_style_index(_ev("trading_style", cfg.TRADING_STYLE)),
                format_func=lambda k: STYLE_LABELS.get(k, k),
            )
        with c2:
            symbol = st.text_input(
                "Par por defecto",
                value=_ev("symbol", "BTC/USDT"),
            )
            scfg = get_style_config(style)
            tf_opts = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
            htf_opts = ["5m", "15m", "30m", "1h", "4h", "1d"]
            tf_default = _ev("timeframe", scfg["timeframe"])
            htf_default = _ev("htf", scfg["htf"])
            timeframe = st.selectbox(
                "Timeframe",
                tf_opts,
                index=tf_opts.index(tf_default) if tf_default in tf_opts else 4,
            )
            htf = st.selectbox(
                "HTF",
                htf_opts,
                index=htf_opts.index(htf_default) if htf_default in htf_opts else 3,
            )
            notes = st.text_area(
                "Notas",
                value=_ev("notes"),
                height=68,
            )

        st.markdown(f"*{STRATEGY_TYPES[strategy_type]['description']}*")

        if strategy_type in ("hmm_confluence", "hmm_regime"):
            hc1, hc2, hc3 = st.columns(3)
            with hc1:
                hmm_states = st.number_input("Estados HMM", 2, 5, 3)
            with hc2:
                hmm_train = st.number_input("Barras entrenamiento", 100, 2000, 500)
            with hc3:
                hmm_refit = st.number_input("Re-entrenar cada N velas", 10, 500, 50)
            allow_range = st.checkbox("Operar en régimen lateral (range)", value=False)
            hmm_extra = {
                "hmm_n_states": int(hmm_states),
                "hmm_train_bars": int(hmm_train),
                "hmm_refit_every": int(hmm_refit),
                "hmm_allow_range_trades": allow_range,
            }
        else:
            hmm_extra = {}

        params = _build_params_from_ui(style, strategy_type, hmm_extra)
        with st.expander("Ver parámetros JSON"):
            st.json(params)

        bc1, bc2 = st.columns(2)
        with bc1:
            if st.button("Guardar estrategia", type="primary", use_container_width=True):
                if not name.strip():
                    st.error("Indica un nombre.")
                else:
                    try:
                        sid = save_strategy(
                            name=name.strip(),
                            strategy_type=strategy_type,
                            params=params,
                            trading_style=style,
                            symbol=symbol.strip() or None,
                            timeframe=timeframe,
                            htf=htf,
                            notes=notes.strip() or None,
                            strategy_id=edit_id,
                        )
                        st.success(f"Estrategia «{name.strip()}» guardada (id {sid}).")
                        st.session_state.pop("lab_edit_strategy_id", None)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"No se pudo guardar: {exc}")
        with bc2:
            if edit_id and st.button("Cancelar edición", use_container_width=True):
                st.session_state.pop("lab_edit_strategy_id", None)
                st.rerun()

    if not strategies:
        st.info("Aún no hay estrategias guardadas.")
        return

    st.markdown("### Estrategias guardadas")
    for s in strategies:
        col_a, col_b, col_c, col_d = st.columns([3, 2, 1, 1])
        with col_a:
            st.markdown(f"**{s['name']}**")
            st.caption(
                f"{STRATEGY_TYPES.get(s['strategy_type'], {}).get('label', s['strategy_type'])} · "
                f"{s.get('symbol') or '—'} · {s.get('timeframe')}/{s.get('htf')}"
            )
        with col_b:
            p = s["params"]
            st.caption(
                f"Score ≥ {p.get('score_threshold', '—')} · "
                f"Lev x{p.get('leverage', 1)} · "
                f"HMM: {'sí' if p.get('use_hmm_regime') else 'no'}"
            )
        with col_c:
            if st.button("Editar", key=f"edit_strat_{s['id']}"):
                st.session_state["lab_edit_strategy_id"] = s["id"]
                st.rerun()
        with col_d:
            if st.button("Eliminar", key=f"del_strat_{s['id']}"):
                delete_strategy(s["id"])
                st.rerun()


def render_backtest_tab():
    st.subheader("Backtest con periodo personalizado")
    st.caption(
        "Ejemplo: BTC/USDT desde 2018 hasta hoy en **4h** o **1d**. "
        f"Máximo ~{MAX_BACKTEST_BARS:,} velas por ejecución."
    )

    strategies = list_strategies()
    strat_options = ["— Configuración manual —"] + [s["name"] for s in strategies]
    saved_name = st.selectbox("Cargar estrategia guardada", strat_options)
    saved = get_strategy(name=saved_name) if saved_name != strat_options[0] else None

    pair_options = list(dict.fromkeys(list(cfg.TRADING_PAIRS) + ["BTC/USDT", "ETH/USDT"]))
    default_symbol = (saved or {}).get("symbol") or pair_options[0]
    sym_index = pair_options.index(default_symbol) if default_symbol in pair_options else 0

    c1, c2, c3 = st.columns(3)
    with c1:
        symbol = st.selectbox("Par", pair_options, index=sym_index)
    with c2:
        default_start = date(2024, 1, 1)
        start_d = st.date_input("Desde", value=default_start)
    with c3:
        end_d = st.date_input("Hasta", value=date.today())

    if saved:
        style = saved.get("trading_style") or cfg.TRADING_STYLE
        strategy_type = saved["strategy_type"]
        timeframe = saved.get("timeframe") or get_style_config(style)["timeframe"]
        htf = saved.get("htf") or get_style_config(style)["htf"]
        params = dict(saved["params"])
        p = params
        st.info(
            f"**{saved['name']}** · {timeframe}/{htf} · "
            f"riesgo {p.get('risk_pct', '—')}% · leverage x{p.get('leverage', 1)} · "
            f"comisión {float(p.get('commission_pct', 0))*100:.2f}%"
        )
        if p.get("nextwave_v2") or strategy_type.startswith("nextwave"):
            lev = st.slider(
                "Apalancamiento (x3–x5)",
                3, 5,
                int(min(max(p.get("leverage", 3), 3), 5)),
            )
            params["leverage"] = float(lev)
    else:
        c4, c5 = st.columns(2)
        with c4:
            style = st.selectbox(
                "Estilo base",
                list(TRADING_STYLES.keys()),
                format_func=lambda k: STYLE_LABELS.get(k, k),
            )
            strategy_type = st.selectbox(
                "Tipo",
                list(STRATEGY_TYPES.keys()),
                format_func=lambda k: STRATEGY_TYPES[k]["label"],
            )
        with c5:
            scfg = get_style_config(style)
            tf_opts = ["5m", "15m", "1h", "4h", "1d"]
            htf_opts = ["15m", "1h", "4h", "1d"]
            tf_def = scfg["timeframe"] if scfg["timeframe"] in tf_opts else "4h"
            htf_def = scfg["htf"] if scfg["htf"] in htf_opts else "1d"
            timeframe = st.selectbox("Timeframe", tf_opts, index=tf_opts.index(tf_def))
            htf = st.selectbox("HTF", htf_opts, index=htf_opts.index(htf_def))

        if strategy_type in ("hmm_confluence", "hmm_regime"):
            hmm_states = st.slider("Estados HMM", 2, 5, 3)
            hmm_train = st.slider("Barras entrenamiento HMM", 100, 1000, 500)
            hmm_extra = {
                "hmm_n_states": hmm_states,
                "hmm_train_bars": hmm_train,
                "hmm_refit_every": 50,
            }
        else:
            hmm_extra = {}
        params = _build_params_from_ui(style, strategy_type, hmm_extra)

    cap_default = float((saved or {}).get("params", {}).get("initial_capital", 1000.0))
    c6, c7, c8 = st.columns(3)
    with c6:
        capital = st.number_input("Capital inicial (USDT)", 100.0, 1_000_000.0, cap_default, 100.0)
        if saved:
            params["initial_capital"] = float(capital)
    with c7:
        save_name = st.text_input(
            "Nombre para guardar resultado",
            value=saved["name"] if saved else f"{symbol} backtest",
        )
    with c8:
        run_save = st.checkbox("Guardar en SQLite", value=True)

    since_ts = pd.Timestamp(datetime.combine(start_d, datetime.min.time())).tz_localize("UTC")
    until_ts = pd.Timestamp(datetime.combine(end_d, datetime.max.time())).tz_localize("UTC")
    est = estimate_bars_between(since_ts, until_ts, timeframe)
    if est > MAX_BACKTEST_BARS:
        st.warning(
            f"~{est:,} velas estimadas en {timeframe} — supera el límite ({MAX_BACKTEST_BARS:,}). "
            "Usa timeframe **4h** o **1d** para periodos largos (p.ej. 2018–actualidad)."
        )
    else:
        st.caption(f"~{est:,} velas estimadas en {timeframe}")

    if st.button("Ejecutar backtest", type="primary"):
        with st.spinner(f"Descargando datos y simulando {symbol}…"):
            try:
                result = run_backtest(
                    symbol=symbol,
                    timeframe=timeframe,
                    htf=htf,
                    params=params,
                    start_date=since_ts.isoformat(),
                    end_date=until_ts.isoformat(),
                    strategy_type=strategy_type,
                    capital=float(capital),
                )
                st.session_state["lab_last_backtest"] = result
                st.session_state["lab_last_backtest_meta"] = {
                    "strategy_name": save_name,
                    "strategy_id": saved["id"] if saved else None,
                }
            except Exception as exc:
                st.error(str(exc))
                return

    result = st.session_state.get("lab_last_backtest")
    if not result:
        return

    metrics = result.get("metrics") or {}
    trades = result.get("trades") or []
    equity = result.get("equity_curve") or []

    st.divider()
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Trades", metrics.get("total_trades", 0))
    m2.metric("Win Rate", f"{metrics.get('win_rate', 0):.1%}")
    m3.metric("Profit Factor", metrics.get("profit_factor", "—"))
    m4.metric("PnL neto", f"{metrics.get('net_pnl', 0):,.2f} USDT")
    m5.metric("Retorno", f"{metrics.get('return_pct', 0):.1%}")
    m6.metric("Comisiones", f"{metrics.get('total_commission', 0):,.2f} USDT")
    c7, c8, c9 = st.columns(3)
    c7.metric("Max DD", f"{metrics.get('max_drawdown', 0):.1%}")
    c8.metric("Calmar", metrics.get("calmar_ratio", "—"))
    c9.metric("Equity final", f"{metrics.get('final_equity', '—')} USDT")

    if result.get("regime_distribution"):
        st.caption(
            "Distribución HMM: "
            + " · ".join(
                f"{k} {v:.0%}" for k, v in result["regime_distribution"].items()
            )
        )

    if equity:
        eq_df = pd.DataFrame(equity)
        eq_df["time"] = pd.to_datetime(eq_df["time"])
        fig = px.line(
            eq_df, x="time", y="equity",
            title=f"Curva de equity — {result.get('symbol')} ({timeframe})",
        )
        fig.add_hline(y=0, line_dash="dot")
        st.plotly_chart(fig, use_container_width=True)

    if trades:
        st.dataframe(pd.DataFrame(trades), use_container_width=True, hide_index=True)

    meta = st.session_state.get("lab_last_backtest_meta", {})
    if run_save and st.button("Guardar resultado del backtest"):
        try:
            rid = save_backtest_run(
                strategy_name=meta.get("strategy_name") or save_name,
                symbol=result["symbol"],
                start_date=result["start_date"][:10],
                end_date=result["end_date"][:10],
                metrics=metrics,
                trades=trades,
                equity_curve=equity,
                strategy_id=meta.get("strategy_id"),
                strategy_type=result.get("strategy_type"),
                timeframe=result.get("timeframe"),
                htf=result.get("htf"),
                capital=result.get("capital", capital),
            )
            st.success(f"Backtest guardado (id {rid}).")
        except Exception as exc:
            st.error(str(exc))

    runs = list_backtest_runs(limit=10)
    if runs:
        st.markdown("### Últimos backtests guardados")
        rows = []
        for r in runs:
            m = r.get("metrics") or {}
            rows.append({
                "id": r["id"],
                "nombre": r.get("strategy_name"),
                "par": r["symbol"],
                "periodo": f"{r['start_date']} → {r['end_date']}",
                "trades": m.get("total_trades", 0),
                "PnL": m.get("net_pnl", 0),
                "PF": m.get("profit_factor", 0),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_lab_panel():
    init_db()
    tab_bt, tab_st = st.tabs(["Backtest", "Mis estrategias"])
    with tab_bt:
        render_backtest_tab()
    with tab_st:
        render_strategies_tab()
