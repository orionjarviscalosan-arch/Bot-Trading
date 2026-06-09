/**
 * Nextwaves Bot — KLineChart Pro + datafeed Binance + marcadores del bot
 */
(function () {
  const PAYLOAD = window.__NW_CHART_PAYLOAD__;
  const root = document.getElementById("nw-kline-root");
  const statusEl = document.getElementById("nw-kline-status");

  function setStatus(msg) {
    if (statusEl) statusEl.textContent = msg;
  }

  if (!PAYLOAD || !root) {
    setStatus("Sin datos del gráfico.");
    return;
  }

  const kc = window.klinecharts;
  const KLineChartPro = window.klinechartspro && window.klinechartspro.KLineChartPro;

  if (!kc || !KLineChartPro) {
    setStatus("Error: no se cargó KLineChart / KLineChart Pro.");
    return;
  }

  function periodToBinance(period) {
    if (!period) return PAYLOAD.interval || "5m";
    const m = period.multiplier || 1;
    const t = period.timespan || "minute";
    if (t === "minute") return m + "m";
    if (t === "hour") return m + "h";
    if (t === "day") return m + "d";
    if (t === "week") return "1w";
    if (t === "month") return "1M";
    return PAYLOAD.interval || "5m";
  }

  function registerBotOverlays() {
    if (!kc.registerOverlay) return;

    const makeTriangle = (direction, defaultColor) => ({
      name: direction === "up" ? "nwLongEntry" : "nwShortEntry",
      totalStep: 2,
      needDefaultPointFigure: false,
      lock: true,
      createPointFigures: ({ coordinates, overlay }) => {
        if (!coordinates || !coordinates[0]) return [];
        const { x, y } = coordinates[0];
        const s = 7;
        const color = (overlay.extendData && overlay.extendData.color) || defaultColor;
        const coords =
          direction === "up"
            ? [
                { x: x, y: y + s },
                { x: x - s, y: y - s },
                { x: x + s, y: y - s },
              ]
            : [
                { x: x, y: y - s },
                { x: x - s, y: y + s },
                { x: x + s, y: y + s },
              ];
        return [
          {
            type: "polygon",
            attrs: { coordinates: coords },
            styles: { style: "fill", color: color, borderColor: color },
            ignoreEvent: false,
          },
        ];
      },
    });

    kc.registerOverlay(makeTriangle("up", "#22c55e"));
    kc.registerOverlay(makeTriangle("down", "#ef4444"));

    kc.registerOverlay({
      name: "nwExitMark",
      totalStep: 2,
      needDefaultPointFigure: false,
      lock: true,
      createPointFigures: ({ coordinates, overlay }) => {
        if (!coordinates || !coordinates[0]) return [];
        const { x, y } = coordinates[0];
        const color = (overlay.extendData && overlay.extendData.color) || "#fbbf24";
        return [
          {
            type: "circle",
            attrs: { x: x, y: y, r: 5 },
            styles: { style: "fill", color: color, borderColor: "#ffffff", borderSize: 1 },
          },
        ];
      },
    });
  }

  class BinanceDatafeed {
    constructor(pairs, defaultSymbol) {
      this.pairs = pairs || [];
      this.defaultSymbol = defaultSymbol;
      this._ws = null;
      this._callback = null;
      this._activeKey = null;
    }

    searchSymbols(search) {
      const q = (search || "").toUpperCase();
      const list = this.pairs
        .filter((s) => s.toUpperCase().includes(q) || s.replace("/", "").includes(q))
        .map((s) => {
          const base = s.split("/")[0];
          const quote = (s.split("/")[1] || "USDT").toLowerCase();
          return {
            ticker: s.replace("/", "").toUpperCase(),
            shortName: base,
            name: s,
            exchange: "BINANCE",
            market: "crypto",
            priceCurrency: quote,
            type: "crypto",
          };
        });
      return Promise.resolve(list);
    }

    async getHistoryKLineData(symbol, period, from, to) {
      const interval = periodToBinance(period);
      const ticker = symbol.ticker || symbol;
      let url =
        "https://api.binance.com/api/v3/klines?symbol=" +
        encodeURIComponent(ticker) +
        "&interval=" +
        encodeURIComponent(interval) +
        "&limit=1000";
      if (from) url += "&startTime=" + Math.floor(from);
      if (to) url += "&endTime=" + Math.floor(to);

      const resp = await fetch(url);
      if (!resp.ok) throw new Error("Binance klines HTTP " + resp.status);
      const data = await resp.json();
      if (!Array.isArray(data)) return [];

      return data.map((k) => ({
        timestamp: k[0],
        open: parseFloat(k[1]),
        high: parseFloat(k[2]),
        low: parseFloat(k[3]),
        close: parseFloat(k[4]),
        volume: parseFloat(k[5]),
      }));
    }

    subscribe(symbol, period, callback) {
      this.unsubscribe();
      const interval = periodToBinance(period);
      const ticker = (symbol.ticker || symbol).toLowerCase();
      const stream = ticker + "@kline_" + interval;
      this._activeKey = stream;
      this._callback = callback;
      this._ws = new WebSocket("wss://stream.binance.com:9443/ws/" + stream);
      this._ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          const k = msg.k;
          if (!k || !this._callback) return;
          this._callback({
            timestamp: k.t,
            open: parseFloat(k.o),
            high: parseFloat(k.h),
            low: parseFloat(k.l),
            close: parseFloat(k.c),
            volume: parseFloat(k.v),
          });
        } catch (e) {
          /* ignore */
        }
      };
    }

    unsubscribe() {
      if (this._ws) {
        try {
          this._ws.close();
        } catch (e) {
          /* ignore */
        }
      }
      this._ws = null;
      this._callback = null;
      this._activeKey = null;
    }
  }

  function getCoreChart(pro) {
    return pro._chartApi || (typeof pro.getChart === "function" ? pro.getChart() : null);
  }

  function overlayNameForKind(kind) {
    if (!kind) return "nwExitMark";
    if (kind.indexOf("long") >= 0 || kind === "signal_long") return "nwLongEntry";
    if (kind.indexOf("short") >= 0 || kind === "signal_short") return "nwShortEntry";
    if (kind === "exit") return "nwExitMark";
    return "nwExitMark";
  }

  function applyBotOverlays(pro) {
    const core = getCoreChart(pro);
    if (!core || !core.createOverlay) return false;

    const markers = PAYLOAD.markers || [];
    let applied = 0;

    markers.forEach((m, idx) => {
      if (m.price == null) return;
      const tsMs = m.time * 1000;
      try {
        core.createOverlay({
          name: overlayNameForKind(m.kind),
          id: "nw-m-" + idx,
          groupId: "nw-bot-trades",
          lock: true,
          points: [{ timestamp: tsMs, value: m.price }],
          extendData: { color: m.color, text: m.text },
        });
        applied += 1;
      } catch (e) {
        /* ignore duplicate */
      }
    });

    (PAYLOAD.priceLines || []).forEach((pl, idx) => {
      const t0 = pl.timeFrom || (PAYLOAD.bars[0] && PAYLOAD.bars[0].time * 1000);
      const t1 = pl.timeTo || (PAYLOAD.bars.length && PAYLOAD.bars[PAYLOAD.bars.length - 1].time * 1000);
      if (!t0 || !t1 || pl.price == null) return;
      try {
        core.createOverlay({
          name: "horizontalStraightLine",
          id: "nw-pl-" + idx,
          groupId: "nw-bot-levels",
          lock: true,
          points: [
            { timestamp: t0, value: pl.price },
            { timestamp: t1, value: pl.price },
          ],
          extendData: { title: pl.title },
          styles: {
            line: {
              color: pl.color || "#848e9c",
              size: 1,
              style: pl.lineStyle === 2 ? "dashed" : "solid",
            },
          },
        });
        applied += 1;
      } catch (e) {
        /* ignore */
      }
    });

    return applied > 0 || markers.length === 0;
  }

  function waitForChart(pro, attempts) {
    let n = attempts || 0;
    const tick = () => {
      const core = getCoreChart(pro);
      if (core) {
        const ok = applyBotOverlays(pro);
        setStatus(
          "KLineChart Pro · " +
            PAYLOAD.symbol +
            " · " +
            PAYLOAD.timeframe +
            " · " +
            (PAYLOAD.markers || []).length +
            " marcas del bot" +
            (ok ? "" : " (sin overlays)")
        );
        return;
      }
      if (n++ < 50) {
        setTimeout(tick, 120);
      } else {
        setStatus("KLineChart Pro cargado (marcadores pendientes — recarga la pestaña).");
      }
    };
    tick();
  }

  registerBotOverlays();

  const datafeed = new BinanceDatafeed(PAYLOAD.pairs, PAYLOAD.symbolInfo);

  let pro;
  try {
    pro = new KLineChartPro({
      container: root,
      theme: "dark",
      locale: "en-US",
      drawingBarVisible: true,
      symbol: PAYLOAD.symbolInfo,
      period: PAYLOAD.period,
      periods: PAYLOAD.periods,
      timezone: "UTC",
      mainIndicators: ["MA"],
      subIndicators: ["VOL"],
      datafeed: datafeed,
    });
  } catch (err) {
    setStatus("Error al crear KLineChart Pro: " + (err.message || err));
    return;
  }

  waitForChart(pro, 0);
})();
