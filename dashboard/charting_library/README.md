# TradingView Charting Library (opcional)

El dashboard usa **Lightweight Charts** (TradingView, open source) por defecto.
Para activar la **Charting Library** completa (herramientas de dibujo, más timeframes, UI pro):

## 1. Obtener licencia

Solicita acceso en: https://www.tradingview.com/HTML5-stock-chart-library/

TradingView te enviará un ZIP con la carpeta `charting_library/`.

## 2. Instalar en el VPS

Copia el contenido del ZIP aquí:

```
dashboard/charting_library/
  charting_library.js
  charting_library.standalone.js
  bundles/
  ...
```

**No subas estos archivos a GitHub** (licencia privada). Están en `.gitignore`.

## 3. URL pública del dashboard

En `.env`:

```env
DASHBOARD_PUBLIC_URL=https://tu-dashboard.ejemplo.com
```

Streamlit debe servir estáticos (Streamlit ≥ 1.31). La ruta esperada:

`{DASHBOARD_PUBLIC_URL}/static/charting_library/charting_library.standalone.js`

Alternativa: copia también la librería a `dashboard/static/charting_library/`.

## 4. Reiniciar

```bash
sudo systemctl restart nextwaves-dashboard
```

En la pestaña **Gráfico**, el motor pasará a **Charting Library** si detecta los archivos.
