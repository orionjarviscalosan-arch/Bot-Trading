/**
 * Nextwaves Bot — gráfico TradingView (Lightweight Charts + Charting Library opcional)
 */
(function () {
  const PAYLOAD = window.__NW_CHART_PAYLOAD__;
  if (!PAYLOAD) {
    document.getElementById("nw-chart-root").innerHTML =
      "<p style='color:#ef4444;padding:1rem'>Sin datos del gráfico.</p>";
    return;
  }

  const root = document.getElementById("nw-chart-root");
  const statusEl = document.getElementById("nw-chart-status");

  function setStatus(msg) {
    if (statusEl) statusEl.textContent = msg;
  }

  function markerPosition(kind) {
    if (kind === "entry_short" || kind === "signal_short" || kind === "exit") {
      return "aboveBar";
    }
    return "belowBar";
  }

  function markerShape(kind) {
    if (kind === "entry_long" || kind === "open_long" || kind === "signal_long") {
      return "arrowUp";
    }
    if (kind === "entry_short" || kind === "open_short" || kind === "signal_short") {
      return "arrowDown";
    }
    return "circle";
  }

  function initLightweightCharts() {
    if (typeof LightweightCharts === "undefined") {
      setStatus("Error: no se cargó Lightweight Charts.");
      return;
    }

    const chart = LightweightCharts.createChart(root, {
      width: root.clientWidth,
      height: root.clientHeight,
      layout: {
        background: { color: "#0b0e11" },
        textColor: "#d1d4dc",
        fontSize: 12,
      },
      grid: {
        vertLines: { color: "rgba(42, 46, 57, 0.6)" },
        horzLines: { color: "rgba(42, 46, 57, 0.6)" },
      },
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Normal,
        vertLine: { color: "rgba(224, 227, 235, 0.3)" },
        horzLine: { color: "rgba(224, 227, 235, 0.3)" },
      },
      rightPriceScale: {
        borderColor: "rgba(42, 46, 57, 0.8)",
        scaleMargins: { top: 0.08, bottom: 0.15 },
      },
      timeScale: {
        borderColor: "rgba(42, 46, 57, 0.8)",
        timeVisible: true,
        secondsVisible: PAYLOAD.resolution === "1" || PAYLOAD.resolution === "3",
      },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderUpColor: "#26a69a",
      borderDownColor: "#ef5350",
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350",
    });

    candleSeries.setData(PAYLOAD.bars || []);

    const lwMarkers = (PAYLOAD.markers || [])
      .filter((m) => m.price != null)
      .map((m) => ({
        time: m.time,
        position: markerPosition(m.kind),
        color: m.color,
        shape: markerShape(m.kind),
        text: m.label || "",
      }))
      .sort((a, b) => a.time - b.time);

    if (lwMarkers.length) {
      candleSeries.setMarkers(lwMarkers);
    }

    (PAYLOAD.priceLines || []).forEach((pl) => {
      candleSeries.createPriceLine({
        price: pl.price,
        color: pl.color,
        lineWidth: 1,
        lineStyle: pl.lineStyle === 2 ? 2 : 0,
        axisLabelVisible: true,
        title: pl.title || "",
      });
    });

    const volSeries = chart.addHistogramSeries({
      color: "#26a69a",
      priceFormat: { type: "volume" },
      priceScaleId: "",
    });
    volSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    });
    volSeries.setData(
      (PAYLOAD.bars || []).map((b) => ({
        time: b.time,
        value: b.volume || 0,
        color: b.close >= b.open ? "rgba(38, 166, 154, 0.5)" : "rgba(239, 83, 80, 0.5)",
      }))
    );

    new ResizeObserver(() => {
      chart.applyOptions({ width: root.clientWidth, height: root.clientHeight });
    }).observe(root);

    chart.timeScale().fitContent();
    setStatus(
      `Lightweight Charts · ${PAYLOAD.symbol} · ${PAYLOAD.timeframe} · ${(PAYLOAD.bars || []).length} velas · ${lwMarkers.length} marcas`
    );
  }

  function resolutionToBinance(res) {
    const map = {
      "1": "1m", "3": "3m", "5": "5m", "15": "15m", "30": "30m",
      "60": "1h", "120": "2h", "240": "4h", "1D": "1d", "1W": "1w",
    };
    return map[res] || PAYLOAD.interval || "5m";
  }

  function buildDatafeed(payload) {
    const marks = payload.shapes || payload.markers || [];

    return {
      onReady: (cb) => {
        setTimeout(() => cb({
          supported_resolutions: ["1", "3", "5", "15", "30", "60", "120", "240", "1D"],
          supports_marks: true,
          supports_timescale_marks: true,
          supports_search: false,
          supports_group_request: false,
        }), 0);
      },
      searchSymbols: (_userInput, _exchange, _symbolType, onResult) => onResult([]),
      resolveSymbol: (symbolName, onResolve, _onError) => {
        onResolve({
          name: symbolName,
          ticker: symbolName,
          description: symbolName,
          type: "crypto",
          session: "24x7",
          timezone: "Etc/UTC",
          exchange: "BINANCE",
          minmov: 1,
          pricescale: 100,
          has_intraday: true,
          has_weekly_and_monthly: false,
          supported_resolutions: ["1", "3", "5", "15", "30", "60", "120", "240", "1D"],
          volume_precision: 4,
          data_status: "streaming",
        });
      },
      getBars: (symbolInfo, resolution, periodParams, onResult, onError) => {
        const interval = resolutionToBinance(resolution);
        const limit = 500;
        const url = `https://api.binance.com/api/v3/klines?symbol=${payload.binanceSymbol}&interval=${interval}&limit=${limit}`;
        fetch(url)
          .then((r) => r.json())
          .then((data) => {
            if (!Array.isArray(data)) {
              onResult([], { noData: true });
              return;
            }
            const bars = data.map((k) => ({
              time: k[0],
              open: parseFloat(k[1]),
              high: parseFloat(k[2]),
              low: parseFloat(k[3]),
              close: parseFloat(k[4]),
              volume: parseFloat(k[5]),
            }));
            onResult(bars, { noData: bars.length === 0 });
          })
          .catch(onError);
      },
      subscribeBars: () => {},
      unsubscribeBars: () => {},
      getMarks: (symbolInfo, from, to, onDataCallback, resolution) => {
        const out = marks
          .filter((m) => m.time >= from && m.time <= to)
          .map((m) => ({
            id: m.id,
            time: m.time,
            color: {
              border: m.color,
              background: m.color,
            },
            text: m.text || m.label,
            label: (m.label || "•").slice(0, 1),
            labelFontColor: "#ffffff",
            minSize: 16,
          }));
        onDataCallback(out);
      },
      getTimescaleMarks: (symbolInfo, from, to, onDataCallback, resolution) => {
        onDataCallback([]);
      },
    };
  }

  function drawChartingLibraryShapes(widget, payload) {
    const chart = widget.activeChart();
    (payload.shapes || []).forEach((m) => {
      if (!m.price) return;
      const isLong = (m.kind || "").includes("long");
      const isShort = (m.kind || "").includes("short");
      const shape = isLong ? "arrow_up" : isShort ? "arrow_down" : "circle";
      try {
        chart.createShape(
          { time: m.time, price: m.price },
          {
            shape: shape,
            text: m.text,
            overrides: {
              color: m.color,
              fontsize: 10,
            },
          }
        );
      } catch (e) {
        /* ignore duplicate shape errors */
      }
    });

    (payload.priceLines || []).forEach((pl) => {
      try {
        chart.createShape(
          { time: Math.floor(Date.now() / 1000), price: pl.price },
          {
            shape: "horizontal_line",
            text: pl.title,
            overrides: {
              linecolor: pl.color,
              linestyle: 2,
              linewidth: 1,
            },
          }
        );
      } catch (e) {
        /* ignore */
      }
    });
  }

  function initChartingLibrary() {
    if (typeof TradingView === "undefined") {
      setStatus("Charting Library no cargada — usando Lightweight Charts.");
      initLightweightCharts();
      return;
    }

    root.innerHTML = "";
    const container = document.createElement("div");
    container.id = "tv_chart_container";
    container.style.width = "100%";
    container.style.height = "100%";
    root.appendChild(container);

    const widget = new TradingView.widget({
      symbol: PAYLOAD.binanceSymbol,
      interval: PAYLOAD.resolution || "5",
      container: container,
      library_path: PAYLOAD.libraryPath,
      locale: "es",
      disabled_features: [
        "use_localstorage_for_settings",
        "header_symbol_search",
        "symbol_search_hot_key",
      ],
      enabled_features: ["hide_left_toolbar_by_default"],
      theme: "dark",
      timezone: "Etc/UTC",
      autosize: true,
      datafeed: buildDatafeed(PAYLOAD),
      overrides: {
        "paneProperties.background": "#0b0e11",
        "paneProperties.backgroundType": "solid",
        "mainSeriesProperties.candleStyle.upColor": "#26a69a",
        "mainSeriesProperties.candleStyle.downColor": "#ef5350",
        "mainSeriesProperties.candleStyle.borderUpColor": "#26a69a",
        "mainSeriesProperties.candleStyle.borderDownColor": "#ef5350",
        "mainSeriesProperties.candleStyle.wickUpColor": "#26a69a",
        "mainSeriesProperties.candleStyle.wickDownColor": "#ef5350",
      },
    });

    widget.onChartReady(() => {
      drawChartingLibraryShapes(widget, PAYLOAD);
      setStatus(
        `Charting Library · ${PAYLOAD.symbol} · ${PAYLOAD.timeframe} · ${(PAYLOAD.shapes || []).length} marcas del bot`
      );
    });
  }

  function boot() {
    root.style.width = "100%";
    root.style.height = "100%";
    if (PAYLOAD.useChartingLibrary && PAYLOAD.libraryPath) {
      initChartingLibrary();
    } else {
      initLightweightCharts();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
