"""
database.py — Registro SQLite de trades, señales y rendimiento
"""
import sqlite3
import os
import json
import logging
from datetime import datetime
from config import DB_PATH

logger = logging.getLogger(__name__)

def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Crea todas las tablas si no existen"""
    with get_conn() as conn:
        conn.executescript("""
        -- Trades reales
        CREATE TABLE IF NOT EXISTS trades (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id     TEXT    UNIQUE,
            mode         TEXT,        -- live | shadow | paper
            side         TEXT,        -- long | short
            symbol       TEXT,
            timeframe    TEXT,
            entry_time   TIMESTAMP,
            entry_price  REAL,
            exit_time    TIMESTAMP,
            exit_price   REAL,
            exit_reason  TEXT,        -- sl | tp | trail_flip | score_bear | manual
            quantity     REAL,
            pnl_usdt     REAL,
            pnl_pct      REAL,
            stop_loss    REAL,
            take_profit  REAL,
            score_bull   INTEGER,
            score_bear   INTEGER,
            trail_level  REAL,
            params_id    INTEGER,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Señales generadas (con o sin trade)
        CREATE TABLE IF NOT EXISTS signals (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp    TIMESTAMP,
            symbol       TEXT,
            direction    TEXT,   -- long | short | none
            score_bull   INTEGER,
            score_bear   INTEGER,
            trail_dir    INTEGER,
            htf_bull     BOOLEAN,
            htf_bear     BOOLEAN,
            struct_bias  INTEGER,
            regime_ok    BOOLEAN,
            momentum_raw REAL,
            acted_on     BOOLEAN DEFAULT FALSE,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Sets de parámetros activos y su historial
        CREATE TABLE IF NOT EXISTS param_sets (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            params       TEXT,   -- JSON
            source       TEXT,   -- initial | optimized | manual
            profit_factor REAL,
            win_rate     REAL,
            calmar_ratio REAL,
            trades_count INTEGER,
            active       BOOLEAN DEFAULT FALSE,
            shadow_since TIMESTAMP,
            live_since   TIMESTAMP,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Rendimiento diario
        CREATE TABLE IF NOT EXISTS daily_performance (
            date         TEXT PRIMARY KEY,
            trades       INTEGER DEFAULT 0,
            wins         INTEGER DEFAULT 0,
            losses       INTEGER DEFAULT 0,
            pnl_usdt     REAL    DEFAULT 0,
            equity       REAL,
            drawdown_pct REAL,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Estado del bot
        CREATE TABLE IF NOT EXISTS bot_state (
            key   TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        _migrate_schema(conn)
    logger.info("Base de datos inicializada")

def _migrate_schema(conn):
    """Añade columnas nuevas en bases de datos existentes."""
    trade_cols = {r[1] for r in conn.execute("PRAGMA table_info(trades)").fetchall()}
    if "trading_style" not in trade_cols:
        conn.execute("ALTER TABLE trades ADD COLUMN trading_style TEXT DEFAULT 'swing'")
    signal_cols = {r[1] for r in conn.execute("PRAGMA table_info(signals)").fetchall()}
    if "trading_style" not in signal_cols:
        conn.execute("ALTER TABLE signals ADD COLUMN trading_style TEXT DEFAULT 'swing'")

# ── TRADES ────────────────────────────────────────────────

def save_trade(trade: dict):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO trades
            (trade_id, mode, side, symbol, timeframe, entry_time, entry_price,
             exit_time, exit_price, exit_reason, quantity, pnl_usdt, pnl_pct,
             stop_loss, take_profit, score_bull, score_bear, trail_level, params_id,
             trading_style)
            VALUES
            (:trade_id, :mode, :side, :symbol, :timeframe, :entry_time, :entry_price,
             :exit_time, :exit_price, :exit_reason, :quantity, :pnl_usdt, :pnl_pct,
             :stop_loss, :take_profit, :score_bull, :score_bear, :trail_level, :params_id,
             :trading_style)
        """, trade)

def update_trade_stop_loss(trade_id: str, new_sl: float) -> bool:
    """Actualiza el stop loss de un trade abierto."""
    with get_conn() as conn:
        cur = conn.execute("""
            UPDATE trades SET stop_loss = ?
            WHERE trade_id = ? AND exit_time IS NULL
        """, (new_sl, trade_id))
    return cur.rowcount > 0

def get_recent_trades(mode="live", days=90):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM trades
            WHERE mode = ?
              AND entry_time >= datetime('now', ? || ' days')
              AND exit_time IS NOT NULL
            ORDER BY entry_time DESC
        """, (mode, f"-{days}")).fetchall()
    return [dict(r) for r in rows]

def get_open_trade(mode="live", symbol=None):
    with get_conn() as conn:
        if symbol:
            row = conn.execute("""
                SELECT * FROM trades
                WHERE mode = ? AND symbol = ? AND exit_time IS NULL
                ORDER BY entry_time DESC LIMIT 1
            """, (mode, symbol)).fetchone()
        else:
            row = conn.execute("""
                SELECT * FROM trades
                WHERE mode = ? AND exit_time IS NULL
                ORDER BY entry_time DESC LIMIT 1
            """, (mode,)).fetchone()
    return dict(row) if row else None


def get_open_trades(mode="live", symbols=None):
    with get_conn() as conn:
        if symbols:
            placeholders = ",".join("?" * len(symbols))
            rows = conn.execute(f"""
                SELECT * FROM trades
                WHERE mode = ? AND exit_time IS NULL
                  AND symbol IN ({placeholders})
                ORDER BY entry_time DESC
            """, (mode, *symbols)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM trades
                WHERE mode = ? AND exit_time IS NULL
                ORDER BY entry_time DESC
            """, (mode,)).fetchall()
    return [dict(r) for r in rows]


def count_open_trades(mode="live") -> int:
    with get_conn() as conn:
        row = conn.execute("""
            SELECT COUNT(*) AS n FROM trades
            WHERE mode = ? AND exit_time IS NULL
        """, (mode,)).fetchone()
    return int(row["n"]) if row else 0

def close_trade(trade_id, exit_price, exit_reason, pnl_usdt, pnl_pct) -> bool:
    """Cierra un trade. Devuelve False si ya estaba cerrado (evita doble cierre)."""
    with get_conn() as conn:
        cur = conn.execute("""
            UPDATE trades
            SET exit_time = ?, exit_price = ?, exit_reason = ?,
                pnl_usdt = ?, pnl_pct = ?
            WHERE trade_id = ? AND exit_time IS NULL
        """, (datetime.utcnow(), exit_price, exit_reason,
              pnl_usdt, pnl_pct, trade_id))
    return cur.rowcount > 0

# ── SEÑALES ───────────────────────────────────────────────

def save_signal(signal: dict):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO signals
            (timestamp, symbol, direction, score_bull, score_bear,
             trail_dir, htf_bull, htf_bear, struct_bias, regime_ok,
             momentum_raw, acted_on, trading_style)
            VALUES
            (:timestamp, :symbol, :direction, :score_bull, :score_bear,
             :trail_dir, :htf_bull, :htf_bear, :struct_bias, :regime_ok,
             :momentum_raw, :acted_on, :trading_style)
        """, signal)

# ── PARÁMETROS ────────────────────────────────────────────

def save_param_set(params: dict, source="initial", metrics=None):
    metrics = metrics or {}
    with get_conn() as conn:
        conn.execute("UPDATE param_sets SET active = FALSE WHERE active = TRUE")
        cur = conn.execute("""
            INSERT INTO param_sets
            (params, source, profit_factor, win_rate, calmar_ratio,
             trades_count, active, live_since)
            VALUES (?, ?, ?, ?, ?, ?, TRUE, ?)
        """, (json.dumps(params),
              source,
              metrics.get("profit_factor", 0),
              metrics.get("win_rate", 0),
              metrics.get("calmar_ratio", 0),
              metrics.get("trades_count", 0),
              datetime.utcnow()))
        return cur.lastrowid

def get_active_params():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM param_sets WHERE active = TRUE ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row:
        return json.loads(row["params"])
    return None

def get_active_param_metrics() -> dict:
    """Métricas almacenadas del set de parámetros activo."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT profit_factor, win_rate, calmar_ratio, trades_count FROM param_sets "
            "WHERE active = TRUE ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row:
        return dict(row)
    return {}

# ── ESTADO DEL BOT ────────────────────────────────────────

def set_state(key: str, value):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO bot_state (key, value, updated_at)
            VALUES (?, ?, ?)
        """, (key, json.dumps(value), datetime.utcnow()))

def get_state(key: str, default=None):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM bot_state WHERE key = ?", (key,)
        ).fetchone()
    if row:
        return json.loads(row["value"])
    return default

# ── RENDIMIENTO ───────────────────────────────────────────

def compute_metrics(trades: list) -> dict:
    """Calcula métricas sobre una lista de trades cerrados"""
    if not trades:
        return {}

    pnls   = [t["pnl_usdt"] for t in trades if t.get("pnl_usdt") is not None]
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    gross_profit = sum(wins)
    gross_loss   = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    win_rate = len(wins) / len(pnls) if pnls else 0

    equity = 0
    peak   = 0
    max_dd = 0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    net_pnl = sum(pnls)
    calmar  = (net_pnl / 10000) / max_dd if max_dd > 0 else 0

    return {
        "total_trades":   len(pnls),
        "win_rate":       round(win_rate, 4),
        "profit_factor":  round(profit_factor, 3),
        "max_drawdown":   round(max_dd, 4),
        "net_pnl":        round(net_pnl, 2),
        "calmar_ratio":   round(calmar, 3),
        "avg_win":        round(sum(wins)   / len(wins)   if wins   else 0, 2),
        "avg_loss":       round(sum(losses) / len(losses) if losses else 0, 2),
    }
