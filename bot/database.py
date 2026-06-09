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


def _json_safe(obj):
    """Convierte Timestamp/datetime/numpy a tipos serializables en JSON."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "isoformat") and type(obj).__name__ in ("Timestamp", "datetime"):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if hasattr(obj, "item"):
        try:
            return obj.item()
        except Exception:
            pass
    return str(obj)


def _json_dumps(data) -> str:
    return json.dumps(_json_safe(data))


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

        -- Estrategias nombradas (backtest / laboratorio)
        CREATE TABLE IF NOT EXISTS strategies (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name           TEXT UNIQUE NOT NULL,
            strategy_type  TEXT NOT NULL DEFAULT 'confluence',
            trading_style  TEXT,
            symbol         TEXT,
            timeframe      TEXT,
            htf            TEXT,
            params         TEXT NOT NULL,
            notes          TEXT,
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Resultados de backtests guardados
        CREATE TABLE IF NOT EXISTS backtest_runs (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_id    INTEGER,
            strategy_name  TEXT,
            symbol         TEXT NOT NULL,
            timeframe      TEXT,
            htf            TEXT,
            strategy_type  TEXT,
            start_date     TEXT NOT NULL,
            end_date       TEXT NOT NULL,
            capital        REAL DEFAULT 10000,
            metrics        TEXT,
            trades_json    TEXT,
            equity_json    TEXT,
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (strategy_id) REFERENCES strategies(id)
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


def get_active_param_source() -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT source FROM param_sets WHERE active = TRUE ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return row["source"] if row else None

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


# ── ESTRATEGIAS NOMBRADAS ─────────────────────────────────

def save_strategy(name: str, strategy_type: str, params: dict,
                  trading_style: str | None = None,
                  symbol: str | None = None,
                  timeframe: str | None = None,
                  htf: str | None = None,
                  notes: str | None = None,
                  strategy_id: int | None = None) -> int:
    name = name.strip()
    if not name:
        raise ValueError("El nombre de la estrategia no puede estar vacío")
    with get_conn() as conn:
        if strategy_id:
            conn.execute("""
                UPDATE strategies SET
                    name = ?, strategy_type = ?, trading_style = ?, symbol = ?,
                    timeframe = ?, htf = ?, params = ?, notes = ?,
                    updated_at = ?
                WHERE id = ?
            """, (name, strategy_type, trading_style, symbol, timeframe, htf,
                  json.dumps(params), notes, datetime.utcnow(), strategy_id))
            return strategy_id
        cur = conn.execute("""
            INSERT INTO strategies
            (name, strategy_type, trading_style, symbol, timeframe, htf, params, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, strategy_type, trading_style, symbol, timeframe, htf,
              json.dumps(params), notes))
        return cur.lastrowid


def list_strategies() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM strategies ORDER BY updated_at DESC, name ASC"
        ).fetchall()
    return [_strategy_row(r) for r in rows]


def _strategy_row(row) -> dict:
    d = dict(row)
    d["params"] = json.loads(d["params"])
    return d


def get_strategy(strategy_id: int | None = None, name: str | None = None) -> dict | None:
    with get_conn() as conn:
        if strategy_id is not None:
            row = conn.execute(
                "SELECT * FROM strategies WHERE id = ?", (strategy_id,)
            ).fetchone()
        elif name:
            row = conn.execute(
                "SELECT * FROM strategies WHERE name = ?", (name.strip(),)
            ).fetchone()
        else:
            return None
    return _strategy_row(row) if row else None


def delete_strategy(strategy_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM strategies WHERE id = ?", (strategy_id,))
    return cur.rowcount > 0


def save_backtest_run(strategy_name: str, symbol: str, start_date: str,
                      end_date: str, metrics: dict, trades: list,
                      equity_curve: list, strategy_id: int | None = None,
                      strategy_type: str | None = None,
                      timeframe: str | None = None, htf: str | None = None,
                      capital: float = 10000.0) -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO backtest_runs
            (strategy_id, strategy_name, symbol, timeframe, htf, strategy_type,
             start_date, end_date, capital, metrics, trades_json, equity_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (strategy_id, strategy_name, symbol, timeframe, htf, strategy_type,
              start_date, end_date, capital,
              _json_dumps(metrics), _json_dumps(trades), _json_dumps(equity_curve)))
        return cur.lastrowid


def list_backtest_runs(limit: int = 50) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM backtest_runs
            ORDER BY created_at DESC LIMIT ?
        """, (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["metrics"] = json.loads(d["metrics"]) if d.get("metrics") else {}
        d["trades"] = json.loads(d["trades_json"]) if d.get("trades_json") else []
        d["equity_curve"] = json.loads(d["equity_json"]) if d.get("equity_json") else []
        out.append(d)
    return out
