"""
tv_component.py — Componente Streamlit con gráfico estilo TradingView + marcadores del bot
"""
from __future__ import annotations

import html
import json
import os
from pathlib import Path

import streamlit.components.v1 as components

_STATIC = Path(__file__).parent / "static"
_LW_CDN = "https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"


def _load_chart_js(filename: str) -> str:
    return (_STATIC / filename).read_text(encoding="utf-8")


def _sanitize_payload_json(payload: dict) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False)
    return payload_json.replace("</", "<\\/")


_CHART_JS = _load_chart_js("tv_chart.js")


def _charting_library_config() -> tuple[bool, str]:
    """
    Detecta Charting Library local + URL pública para library_path.
    Requiere DASHBOARD_PUBLIC_URL y archivos en charting_library/ o static/charting_library/.
    """
    base = Path(__file__).parent
    candidates = (
        base / "charting_library" / "charting_library.standalone.js",
        base / "charting_library" / "charting_library.js",
        base / "static" / "charting_library" / "charting_library.standalone.js",
        base / "static" / "charting_library" / "charting_library.js",
    )
    if not any(p.exists() for p in candidates):
        return False, ""

    public = os.getenv("DASHBOARD_PUBLIC_URL", "").strip().rstrip("/")
    if not public:
        return False, ""

    custom_path = os.getenv("TV_CHARTING_LIBRARY_PATH", "").strip()
    if custom_path:
        return True, custom_path if custom_path.endswith("/") else custom_path + "/"

    if (base / "static" / "charting_library").exists():
        return True, f"{public}/static/charting_library/"
    if (base / "charting_library").exists():
        # Copiar o enlazar a static/ en producción; path configurable:
        return True, f"{public}/static/charting_library/"
    return False, ""


def render_tradingview_chart(payload: dict, height: int = 640) -> str:
    """
    Renderiza el gráfico en un iframe Streamlit.
    Devuelve el motor usado: 'charting_library' | 'lightweight'.
    """
    use_cl, lib_path = _charting_library_config()
    payload = dict(payload)
    payload["useChartingLibrary"] = use_cl
    payload["libraryPath"] = lib_path

    payload_json = _sanitize_payload_json(payload)

    cl_script = ""
    if use_cl and lib_path:
        cl_script = f'<script src="{html.escape(lib_path)}charting_library.standalone.js"></script>'

    page = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <script src="{_LW_CDN}"></script>
  {cl_script}
  <style>
    html, body {{
      margin: 0; padding: 0; width: 100%; height: 100%;
      background: #0b0e11; overflow: hidden;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    #nw-chart-wrap {{
      display: flex; flex-direction: column;
      width: 100%; height: 100vh; box-sizing: border-box;
    }}
    #nw-chart-root {{
      flex: 1; min-height: 0;
    }}
    #nw-chart-status {{
      flex: 0 0 auto;
      padding: 6px 12px;
      font-size: 11px;
      color: #848e9c;
      border-top: 1px solid rgba(42, 46, 57, 0.8);
      background: #0b0e11;
    }}
    #nw-legend {{
      flex: 0 0 auto;
      padding: 4px 12px 8px;
      font-size: 11px;
      color: #848e9c;
      background: #0b0e11;
    }}
    #nw-legend span {{
      margin-right: 14px;
    }}
    .lg-long {{ color: #26a69a; }}
    .lg-short {{ color: #ef5350; }}
    .lg-exit {{ color: #fbbf24; }}
  </style>
</head>
<body>
  <div id="nw-chart-wrap">
    <div id="nw-chart-root"></div>
    <div id="nw-legend">
      <span class="lg-long">▲ Long</span>
      <span class="lg-short">▼ Short</span>
      <span class="lg-exit">● Salida</span>
      <span>— — SL / TP</span>
    </div>
    <div id="nw-chart-status">Cargando gráfico…</div>
  </div>
  <script>
    window.__NW_CHART_PAYLOAD__ = {payload_json};
  </script>
  <script>{_CHART_JS}</script>
</body>
</html>"""

    components.html(page, height=height, scrolling=False)
    return "charting_library" if use_cl else "lightweight"


def charting_library_status() -> dict:
    """Estado de la Charting Library para mensajes en el dashboard."""
    base = Path(__file__).parent
    files_ok = any(
        p.exists()
        for p in (
            base / "charting_library" / "charting_library.standalone.js",
            base / "static" / "charting_library" / "charting_library.standalone.js",
        )
    )
    public = bool(os.getenv("DASHBOARD_PUBLIC_URL", "").strip())
    use_cl, lib_path = _charting_library_config()
    return {
        "files_installed": files_ok,
        "public_url_set": public,
        "active": use_cl,
        "library_path": lib_path,
    }
