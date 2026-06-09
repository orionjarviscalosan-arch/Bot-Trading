"""
csv_data_loader.py — Carga OHLCV desde CSV exportado de Binance
"""
from __future__ import annotations

import os
import pandas as pd


def load_btc_csv(path: str) -> pd.DataFrame:
    """Carga CSV Binance (Open time, Open, High, Low, Close, Volume)."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"No se encuentra el CSV: {path}")

    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]

    time_col = "Open time" if "Open time" in df.columns else df.columns[0]
    df[time_col] = pd.to_datetime(df[time_col].astype(str).str.strip(), utc=True)
    df = df.rename(columns={
        time_col: "timestamp",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    })
    df = df.set_index("timestamp")
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    df = df[~df.index.isna()]
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def default_csv_paths() -> dict[str, str]:
    """Rutas por defecto en Downloads del usuario."""
    base = os.path.expanduser("~/Downloads")
    return {
        "15m": os.path.join(base, "btc_15m_data_2018_to_2025.csv"),
        "1h": os.path.join(base, "btc_1h_data_2018_to_2025.csv"),
        "4h": os.path.join(base, "btc_4h_data_2018_to_2025.csv"),
        "1d": os.path.join(base, "btc_1d_data_2018_to_2025.csv"),
    }
