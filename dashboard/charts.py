"""
charts.py — Datos OHLCV cacheados para el dashboard
"""
from __future__ import annotations

import streamlit as st

from bot.data_fetcher import fetch_ohlcv

CHART_CANDLE_LIMIT = 350


@st.cache_data(ttl=60, show_spinner=False)
def get_chart_ohlcv(symbol: str, timeframe: str, limit: int = CHART_CANDLE_LIMIT):
    """OHLCV de Binance cacheado 60 s para no saturar la API."""
    return fetch_ohlcv(symbol, timeframe, limit=limit)
