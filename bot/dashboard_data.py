"""
dashboard_data.py — Consultas de solo lectura para el dashboard Streamlit
"""
import pandas as pd
from bot.database import get_conn, compute_metrics, get_state, get_active_params


def get_trades_df(mode: str = "shadow", days: int = 90) -> pd.DataFrame:
    with get_conn() as conn:
        df = pd.read_sql_query(
            """
            SELECT * FROM trades
            WHERE mode = ?
              AND entry_time >= datetime('now', ? || ' days')
            ORDER BY entry_time ASC
            """,
            conn,
            params=(mode, f"-{days}"),
        )
    if not df.empty:
        for col in ("entry_time", "exit_time", "created_at"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
    return df


def get_closed_trades_df(mode: str = "shadow", days: int = 90) -> pd.DataFrame:
    df = get_trades_df(mode, days)
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


def get_metrics(mode: str = "shadow", days: int = 90) -> dict:
    closed = get_closed_trades_df(mode, days)
    if closed.empty:
        return {}
    return compute_metrics(closed.to_dict("records"))


def get_bot_status() -> dict:
    return {
        "bot_killed": bool(get_state("bot_killed", False)),
        "kill_reason": get_state("kill_reason"),
        "pause_until": get_state("pause_until"),
        "active_params": get_active_params(),
    }


def build_equity_curve(closed: pd.DataFrame) -> pd.DataFrame:
    if closed.empty:
        return pd.DataFrame(columns=["exit_time", "pnl_usdt", "equity"])
    curve = closed.sort_values("exit_time")[["exit_time", "pnl_usdt"]].copy()
    curve["equity"] = curve["pnl_usdt"].cumsum()
    return curve
