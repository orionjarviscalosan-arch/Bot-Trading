"""
config.py — Configuración central del bot
Todos los parámetros en un solo lugar
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── CONEXIÓN ─────────────────────────────────────────────
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY",    "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
TELEGRAM_TOKEN     = os.getenv("TELEGRAM_TOKEN",     "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "")

# ── MODO ─────────────────────────────────────────────────
# shadow = solo monitorea, NO ejecuta
# paper  = simula con capital virtual
# live   = opera con dinero real
BOT_MODE = os.getenv("BOT_MODE", "shadow")

# ── PAR Y TIMEFRAME ──────────────────────────────────────
SYMBOL     = os.getenv("SYMBOL",    "BTC/USDT")
TIMEFRAME  = os.getenv("TIMEFRAME", "4h")
HTF        = "1d"          # Higher timeframe para contexto
CANDLES_LB = 500           # Velas históricas a cargar

# ── GESTIÓN DE CAPITAL ───────────────────────────────────
MAX_CAPITAL_USDT  = float(os.getenv("MAX_CAPITAL_USDT", "1000.0"))
SHADOW_CAPITAL    = float(os.getenv("SHADOW_CAPITAL", "10000.0"))
POSITION_SIZE_PCT = float(os.getenv("POSITION_SIZE_PCT", "0.25"))
MIN_ORDER_USDT    = 15.0   # Mínimo orden en Binance Spot

# ── PARÁMETROS DE SEÑAL (activos — optimizables) ─────────
SIGNAL_PARAMS = {
    # Core
    "score_threshold":  68,
    "rr_ratio":         2.0,
    "cooldown_bars":    20,

    # WaveTrend
    "channel_len":  9,
    "avg_len":      21,
    "signal_len":   4,

    # RSI / MFI
    "rsi_len": 14,
    "mfi_len": 14,

    # ATR
    "atr_len": 14,

    # Estructura
    "left_bars":       5,
    "right_bars":      5,
    "bos_bars_window": 8,

    # FVG
    "fvg_atr_filter": 0.15,
    "zone_lookback":  15,

    # Trail (Chandelier Exit)
    "trail_mult":     3.0,
    "trail_lookback": 10,
    "use_adaptive":   True,
    "adaptive_lb":    100,

    # Regime
    "regime_min_ratio": 4.0,

    # HTF EMAs
    "htf_fast":  20,
    "htf_slow":  50,
    "htf_trend": 200,
}

# ── OPTIMIZACIÓN AUTOMÁTICA ──────────────────────────────
OPTIMIZER = {
    "run_every_days":     30,   # cada cuántos días re-optimizar
    "lookback_days":      90,   # datos históricos a usar
    "shadow_test_days":   14,   # días de shadow antes de promover
    "min_trades":         10,   # mínimo trades para evaluar
    "min_profit_factor":  1.3,  # PF mínimo para considerar válido
}

# ── GRID DE PARÁMETROS A OPTIMIZAR ───────────────────────
PARAM_GRID = {
    "score_threshold":  [58, 63, 68, 73],
    "trail_mult":       [2.5, 3.0, 3.5, 4.0],
    "rr_ratio":         [1.5, 2.0, 2.5, 3.0],
    "cooldown_bars":    [10, 15, 20, 25],
}

# ── KILL SWITCH ──────────────────────────────────────────
KILL_SWITCH = {
    "max_daily_loss_pct":   0.05,  # 5% pérdida en un día → para todo
    "max_drawdown_pct":     0.15,  # 15% DD total → para todo
    "max_consecutive_loss": 5,     # 5 pérdidas seguidas → pausa 24h
}

# ── BASE DE DATOS ─────────────────────────────────────────
DB_PATH = "data/nextwaves_bot.db"

# ── LOGGING ──────────────────────────────────────────────
LOG_LEVEL  = "INFO"
LOG_FILE   = "data/bot.log"

# ── DASHBOARD STREAMLIT ──────────────────────────────────
DASHBOARD_PORT     = int(os.getenv("DASHBOARD_PORT", "8501"))
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
