"""
chart_renderer.py — Punto único para renderizar gráficos del dashboard
"""
from __future__ import annotations

from dashboard.kline_component import render_kline_chart
from dashboard.tv_component import render_tradingview_chart

CHART_ENGINES = {
    "kline": "KLineChart Pro",
    "lightweight": "Lightweight Charts",
}


def render_chart(payload: dict, engine: str = "kline", height: int = 680) -> str:
    """
    Renderiza el gráfico según motor seleccionado.
    Devuelve: 'kline' | 'lightweight' | 'charting_library'
    """
    if engine == "lightweight":
        return render_tradingview_chart(payload, height=height)
    return render_kline_chart(payload, height=height)
