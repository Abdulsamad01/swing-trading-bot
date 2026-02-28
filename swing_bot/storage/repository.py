"""
SQLite repository.
Manages trades, bot_state, and events tables.
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class Repository:

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id TEXT,
                    timestamp_utc TEXT,
                    profile TEXT,
                    exchange TEXT,
                    symbol TEXT,
                    direction TEXT,
                    entry_price REAL,
                    exit_price REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    quantity REAL,
                    notional_usdt REAL,
                    margin_usdt REAL,
                    risk_budget_usdt REAL,
                    leverage INTEGER,
                    sizing_balance_inr REAL,
                    est_fee_usdt REAL,
                    pnl_usdt REAL,
                    fees_usdt REAL,
                    net_pnl_usdt REAL,
                    exit_reason TEXT,
                    status TEXT,
                    sl_order_id TEXT,
                    tp_order_id TEXT,
                    entry_order_id TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_utc TEXT,
                    level TEXT,
                    event_type TEXT,
                    message TEXT,
                    context_json TEXT
                );

                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT UNIQUE,
                    profile TEXT,
                    symbol TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    total_trades INTEGER,
                    winning_trades INTEGER,
                    losing_trades INTEGER,
                    win_rate REAL,
                    gross_pnl_usdt REAL,
                    total_fees_usdt REAL,
                    net_pnl_usdt REAL,
                    max_drawdown_usdt REAL,
                    best_trade_usdt REAL,
                    worst_trade_usdt REAL,
                    avg_rr REAL,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS backtest_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT,
                    bar_index INTEGER,
                    timestamp_utc TEXT,
                    direction TEXT,
                    entry_price REAL,
                    exit_price REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    quantity REAL,
                    notional_usdt REAL,
                    risk_budget_usdt REAL,
                    rr_ratio REAL,
                    gross_pnl_usdt REAL,
                    fees_usdt REAL,
                    net_pnl_usdt REAL,
                    exit_reason TEXT,
                    bars_held INTEGER,
                    session TEXT
                );
            """)
        logger.info(f"Database initialized: {self.db_path}")

    # ---------------------------------------------------------------- trades

    def insert_trade(self, trade: dict) -> int:
        cols = ", ".join(trade.keys())
        placeholders = ", ".join(["?"] * len(trade))
        sql = f"INSERT INTO trades ({cols}) VALUES ({placeholders})"
        with self._conn() as conn:
            cur = conn.execute(sql, list(trade.values()))
            return cur.lastrowid

    def update_trade(self, trade_id: int, fields: dict):
        assignments = ", ".join([f"{k}=?" for k in fields.keys()])
        sql = f"UPDATE trades SET {assignments} WHERE id=?"
        with self._conn() as conn:
            conn.execute(sql, list(fields.values()) + [trade_id])

    def get_open_trade(self) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM trades WHERE status='open' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def get_recent_trades(self, limit: int = 10) -> List[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ----------------------------------------------------------- bot_state

    def set_state(self, key: str, value: Any):
        now = datetime.now(timezone.utc).isoformat()
        val_str = json.dumps(value) if not isinstance(value, str) else value
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO bot_state (key, value, updated_at) VALUES (?, ?, ?)",
                (key, val_str, now),
            )

    def get_state(self, key: str, default=None) -> Any:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM bot_state WHERE key=?", (key,)
            ).fetchone()
            if row is None:
                return default
            try:
                return json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                return row["value"]

    # ------------------------------------------------------------- events

    def log_event(
        self,
        level: str,
        event_type: str,
        message: str,
        context: dict = None,
    ):
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO events (timestamp_utc, level, event_type, message, context_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (now, level, event_type, message, json.dumps(context) if context else None),
            )

    # --------------------------------------------------------- backtest

    def insert_backtest_run(self, run: dict) -> int:
        cols = ", ".join(run.keys())
        placeholders = ", ".join(["?"] * len(run))
        sql = f"INSERT OR REPLACE INTO backtest_runs ({cols}) VALUES ({placeholders})"
        with self._conn() as conn:
            cur = conn.execute(sql, list(run.values()))
            return cur.lastrowid

    def insert_backtest_trade(self, trade: dict):
        cols = ", ".join(trade.keys())
        placeholders = ", ".join(["?"] * len(trade))
        sql = f"INSERT INTO backtest_trades ({cols}) VALUES ({placeholders})"
        with self._conn() as conn:
            conn.execute(sql, list(trade.values()))

    def get_backtest_runs(self, limit: int = 20) -> List[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM backtest_runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_backtest_trades(self, run_id: str) -> List[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM backtest_trades WHERE run_id=? ORDER BY bar_index ASC",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
