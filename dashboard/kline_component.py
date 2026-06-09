"""
kline_component.py — KLineChart Pro en Streamlit (Apache 2.0)
"""
from __future__ import annotations

import json

import streamlit.components.v1 as components

from dashboard.tv_component import _load_chart_js, _sanitize_payload_json

_KLINE_JS = _load_chart_js("kline_chart.js")

_KLINECHARTS_CDN = "https://unpkg.com/klinecharts@9.8.0/dist/umd/klinecharts.min.js"
_KLINE_PRO_JS = "https://unpkg.com/@klinecharts/pro@0.1.1/dist/klinecharts-pro.umd.js"
_KLINE_PRO_CSS = "https://unpkg.com/@klinecharts/pro@0.1.1/dist/klinecharts-pro.css"


def render_kline_chart(payload: dict, height: int = 680) -> str:
    """Renderiza KLineChart Pro con datafeed Binance y marcadores del bot."""
    payload_json = _sanitize_payload_json(payload)

    page = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <link rel="stylesheet" href="{_KLINE_PRO_CSS}"/>
  <style>
    html, body {{
      margin: 0; padding: 0; width: 100%; height: 100%;
      background: #0b0e11; overflow: hidden;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    #nw-kline-wrap {{
      display: flex; flex-direction: column;
      width: 100%; height: 100vh; box-sizing: border-box;
    }}
    #nw-kline-root {{
      flex: 1; min-height: 0; width: 100%;
    }}
    #nw-kline-root.klinecharts-pro,
    #nw-kline-root .klinecharts-pro {{
      height: 100% !important;
    }}
    #nw-kline-status {{
      flex: 0 0 auto;
      padding: 6px 12px;
      font-size: 11px;
      color: #848e9c;
      border-top: 1px solid rgba(42, 46, 57, 0.8);
      background: #0b0e11;
    }}
    #nw-kline-legend {{
      flex: 0 0 auto;
      padding: 4px 12px;
      font-size: 11px;
      color: #848e9c;
      background: #0b0e11;
    }}
    #nw-kline-legend span {{ margin-right: 14px; }}
    .lg-long {{ color: #26a69a; }}
    .lg-short {{ color: #ef5350; }}
    .lg-exit {{ color: #fbbf24; }}
  </style>
</head>
<body>
  <div id="nw-kline-wrap">
    <div id="nw-kline-root"></div>
    <div id="nw-kline-legend">
      <span class="lg-long">▲ Long</span>
      <span class="lg-short">▼ Short</span>
      <span class="lg-exit">● Salida</span>
      <span>— — SL / TP</span>
    </div>
    <div id="nw-kline-status">Cargando KLineChart Pro…</div>
  </div>
  <script src="{_KLINECHARTS_CDN}"></script>
  <script src="{_KLINE_PRO_JS}"></script>
  <script>
    window.__NW_CHART_PAYLOAD__ = {payload_json};
  </script>
  <script>{_KLINE_JS}</script>
</body>
</html>"""

    components.html(page, height=height, scrolling=False)
    return "kline"
