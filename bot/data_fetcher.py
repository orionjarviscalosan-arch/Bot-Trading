"""
data_fetcher.py — Obtiene datos OHLCV de Binance via ccxt
"""
import ccxt
import pandas as pd
import logging
import time
from datetime import datetime, timezone
from config import BINANCE_API_KEY, BINANCE_API_SECRET, CANDLES_LB

logger = logging.getLogger(__name__)

_exchange = None

def get_exchange():
    global _exchange
    if _exchange is None:
        _exchange = ccxt.binance({
            "apiKey":    BINANCE_API_KEY,
            "secret":    BINANCE_API_SECRET,
            "enableRateLimit": True,
            "options":   {"defaultType": "spot"},
        })
    return _exchange

def symbol_base_asset(symbol: str) -> str:
    """Extrae el activo base de un par CCXT, p.ej. BTC/USDT → BTC."""
    return symbol.split("/")[0]


def timeframe_to_timedelta(timeframe: str) -> pd.Timedelta:
    """Convierte timeframe CCXT a Timedelta pandas (evita ambigüedad de 'm')."""
    mapping = {
        "1m": "1min", "3m": "3min", "5m": "5min", "15m": "15min",
        "30m": "30min", "1h": "1h", "2h": "2h", "4h": "4h",
        "6h": "6h", "8h": "8h", "12h": "12h", "1d": "1d",
    }
    return pd.Timedelta(mapping.get(timeframe, timeframe))

def fetch_ohlcv(symbol: str, timeframe: str, limit: int = CANDLES_LB) -> pd.DataFrame:
    """
    Descarga velas OHLCV confirmadas (excluye la vela actual en formación).
    Devuelve DataFrame con columnas: open, high, low, close, volume
    Index: DatetimeIndex UTC
    """
    ex = get_exchange()
    retries = 3

    for attempt in range(retries):
        try:
            raw = ex.fetch_ohlcv(symbol, timeframe, limit=limit + 1)
            df = pd.DataFrame(raw, columns=["timestamp","open","high","low","close","volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df.set_index("timestamp", inplace=True)
            df = df.astype(float)

            now_utc = datetime.now(timezone.utc)
            if len(df) > 0 and df.index[-1] >= now_utc - timeframe_to_timedelta(timeframe):
                df = df.iloc[:-1]

            return df

        except ccxt.NetworkError as e:
            logger.warning(f"Error de red (intento {attempt+1}/{retries}): {e}")
            time.sleep(2 ** attempt)
        except ccxt.ExchangeError as e:
            logger.error(f"Error de exchange: {e}")
            raise

    raise RuntimeError(f"No se pudieron obtener datos después de {retries} intentos")

def fetch_balance(symbol_base: str = "USDT") -> float:
    """Obtiene el balance disponible de un activo."""
    ex = get_exchange()
    balance = ex.fetch_balance()
    return float(balance["free"].get(symbol_base, 0))

def fetch_base_balance(symbol: str) -> float:
    """Balance del activo base del par (p.ej. BTC para BTC/USDT)."""
    return fetch_balance(symbol_base_asset(symbol))

def fetch_btc_balance() -> float:
    """Compatibilidad: balance BTC."""
    return fetch_balance("BTC")

def fetch_current_price(symbol: str) -> float:
    """Precio actual del mercado"""
    ex = get_exchange()
    ticker = ex.fetch_ticker(symbol)
    return float(ticker["last"])

def get_min_order_size(symbol: str) -> dict:
    """Obtiene restricciones mínimas de orden para el símbolo"""
    ex = get_exchange()
    markets = ex.load_markets()
    market  = markets.get(symbol, {})
    limits  = market.get("limits", {})
    return {
        "min_amount": limits.get("amount", {}).get("min", 0.00001),
        "min_cost":   limits.get("cost",   {}).get("min", 10.0),
        "precision":  market.get("precision", {}).get("amount", 5),
    }

def validate_connection(symbol: str) -> tuple[bool, str]:
    """Comprueba conectividad con Binance descargando una vela."""
    try:
        fetch_ohlcv(symbol, "1h", limit=5)
        return True, "Conexión OK"
    except Exception as e:
        return False, str(e)
