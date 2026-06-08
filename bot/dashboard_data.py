"""
dashboard_data.py — Consultas de solo lectura para el dashboard Streamlit
"""
import os
import pandas as pd
from bot.database import get_conn, compute_metrics, get_state, get_active_params
from bot.trading_styles import TRADING_STYLES, resolve_active_style


def _default_bot_mode() -> str:
    return get_state("bot_mode") or os.getenv("BOT_MODE", "shadow")


def get_trades_df(mode: str = "shadow", days: int = 90,
                  trading_style: str | None = None) -> pd.DataFrame:
    with get_conn() as conn:
        query = """
            SELECT * FROM trades
            WHERE mode = ?
              AND entry_time >= datetime('now', ? || ' days')
        """
        params: list = [mode, f"-{days}"]
        if trading_style:
            query += " AND (trading_style = ? OR trading_style IS NULL)"
            params.append(trading_style)
        query += " ORDER BY entry_time ASC"
        df = pd.read_sql_query(query, conn, params=params)
    if not df.empty:
        for col in ("entry_time", "exit_time", "created_at"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
    return df


def get_closed_trades_df(mode: str = "shadow", days: int = 90,
                         trading_style: str | None = None) -> pd.DataFrame:
    df = get_trades_df(mode, days, trading_style)
    if df.empty:
        return df
    return df[df["exit_time"].notna()].copy()


def get_open_trades_df(mode: str = "shadow") -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query(
            """
            SELECT * FROM trades
            WHERE mode = ? AND exit_time IS NULL
            ORDER BY entry_time DESC
            """,
            conn,
            params=(mode,),
        )
    if not df.empty:
        df["entry_time"] = pd.to_datetime(df["entry_time"], errors="coerce", utc=True)
    return df


def get_signals_df(days: int = 30, limit: int = 200) -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query(
            """
            SELECT * FROM signals
            WHERE timestamp >= datetime('now', ? || ' days')
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            conn,
            params=(f"-{days}", limit),
        )
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    return df


def get_metrics(mode: str = "shadow", days: int = 90,
                trading_style: str | None = None) -> dict:
    closed = get_closed_trades_df(mode, days, trading_style)
    if closed.empty:
        return {}
    return compute_metrics(closed.to_dict("records"))


def get_bot_status() -> dict:
    """Estado del bot leyendo SQLite (sin depender del proceso del bot)."""
    active_style = resolve_active_style()
    style_cfg = TRADING_STYLES.get(active_style, TRADING_STYLES["swing"])
    bot_mode = _default_bot_mode()
    return {
        "bot_killed": bool(get_state("bot_killed", False)),
        "kill_reason": get_state("kill_reason"),
        "pause_until": get_state("pause_until"),
        "active_params": get_active_params(),
        "trading_style": active_style,
        "style_label": style_cfg.get("label", active_style),
        "timeframe": style_cfg.get("timeframe", "4h"),
        "htf": style_cfg.get("htf", "1d"),
        "bot_mode": bot_mode,
    }


def build_equity_curve(closed: pd.DataFrame) -> pd.DataFrame:
    if closed.empty:
        return pd.DataFrame(columns=["exit_time", "pnl_usdt", "equity"])
    curve = closed.sort_values("exit_time")[["exit_time", "pnl_usdt"]].copy()
    curve["equity"] = curve["pnl_usdt"].cumsum()
    return curve


def enrich_open_trades(df: pd.DataFrame) -> tuple[pd.DataFrame, float | None]:
    """Añade precio actual y PnL no realizado a posiciones abiertas."""
    if df.empty:
        return df, None

    import config as cfg
    from bot.data_fetcher import fetch_current_price

    symbol = df.iloc[0].get("symbol") or cfg.SYMBOL
    try:
        current = fetch_current_price(symbol)
    except Exception:
        current = None

    out = df.copy()
    if current is not None:
        out["precio_actual"] = current
        out["pnl_no_realizado"] = (out["precio_actual"] - out["entry_price"]) * out["quantity"]
        out["pnl_pct_no_realizado"] = (
            (out["precio_actual"] - out["entry_price"]) / out["entry_price"]
        )
    return out, current
