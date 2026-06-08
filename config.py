"""
config.py — Configuración central del bot
Todos los parámetros en un solo lugar
"""
import os
from dotenv import load_dotenv
from bot.trading_styles import normalize_style, get_style_config, apply_style_to_signal_params

load_dotenv()

# ── CONEXIÓN ─────────────────────────────────────────────
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY",    "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
TELEGRAM_TOKEN     = os.getenv("TELEGRAM_TOKEN",     "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "")

# ── MODO ─────────────────────────────────────────────────
BOT_MODE = os.getenv("BOT_MODE", "shadow")

# ── ESTILO DE TRADING ────────────────────────────────────
# ultra_1m | micro_5m | scalper | day_trader | swing — autoajusta timeframe e indicadores
TRADING_STYLE = normalize_style(os.getenv("TRADING_STYLE", "micro_5m"))
_style_cfg = get_style_config(TRADING_STYLE)

# ── PAR Y TIMEFRAME (derivados del estilo) ───────────────
_DEFAULT_PAIRS = (
    "BTC/USDT,ETH/USDT,XRP/USDT,DOGE/USDT,BNB/USDT,SOL/USDC"
)


def _parse_trading_pairs() -> list[str]:
    raw = os.getenv("TRADING_PAIRS", "").strip()
    if raw:
        return [p.strip() for p in raw.split(",") if p.strip()]
    legacy = os.getenv("SYMBOL", "").strip()
    if legacy:
        return [legacy]
    return [p.strip() for p in _DEFAULT_PAIRS.split(",") if p.strip()]


TRADING_PAIRS    = _parse_trading_pairs()
SYMBOL           = TRADING_PAIRS[0] if TRADING_PAIRS else "BTC/USDT"
MAX_ACTIVE_PAIRS = int(os.getenv("MAX_ACTIVE_PAIRS", "3"))
TIMEFRAME  = _style_cfg["timeframe"]
HTF        = _style_cfg["htf"]
CANDLES_LB = _style_cfg["candles_lb"]
PRICE_MONITOR_MINUTES = _style_cfg["price_monitor_minutes"]
TRADING_STYLE_LABEL   = _style_cfg["label"]

# ── GESTIÓN DE CAPITAL ───────────────────────────────────
MAX_CAPITAL_USDT  = float(os.getenv("MAX_CAPITAL_USDT", "1000.0"))
SHADOW_CAPITAL    = float(os.getenv("SHADOW_CAPITAL", "10000.0"))
POSITION_SIZE_PCT = float(os.getenv("POSITION_SIZE_PCT", "0.15"))
MIN_ORDER_USDT    = 15.0

# ── PARÁMETROS DE SEÑAL (base + preset del estilo) ─────
_BASE_SIGNAL_PARAMS = {
    "score_threshold":  68,
    "rr_ratio":         2.0,
    "cooldown_bars":    20,
    "channel_len":  9,
    "avg_len":      21,
    "signal_len":   4,
    "rsi_len": 14,
    "mfi_len": 14,
    "atr_len": 14,
    "left_bars":       5,
    "right_bars":      5,
    "bos_bars_window": 8,
    "fvg_atr_filter": 0.15,
    "zone_lookback":  15,
    "trail_mult":     3.0,
    "trail_lookback": 10,
    "use_adaptive":   True,
    "adaptive_lb":    100,
    "regime_min_ratio": 4.0,
    "htf_fast":  20,
    "htf_slow":  50,
    "htf_trend": 200,
}

SIGNAL_PARAMS = apply_style_to_signal_params(_BASE_SIGNAL_PARAMS, TRADING_STYLE)

# ── OPTIMIZACIÓN AUTOMÁTICA ──────────────────────────────
OPTIMIZER = {
    "run_every_days":     30,
    "lookback_days":      90,
    "shadow_test_days":   14,
    "min_trades":         10,
    "min_profit_factor":  1.3,
}

PARAM_GRID = {
    "score_threshold":  [58, 63, 68, 73],
    "trail_mult":       [2.5, 3.0, 3.5, 4.0],
    "rr_ratio":         [1.5, 2.0, 2.5, 3.0],
    "cooldown_bars":    [10, 15, 20, 25],
}

# ── KILL SWITCH ──────────────────────────────────────────
KILL_SWITCH = {
    "max_daily_loss_pct":   0.05,
    "max_drawdown_pct":     0.15,
    "max_consecutive_loss": 5,
}

DB_PATH = "data/nextwaves_bot.db"
LOG_LEVEL  = "INFO"
LOG_FILE   = "data/bot.log"

DASHBOARD_PORT     = int(os.getenv("DASHBOARD_PORT", "8501"))
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
