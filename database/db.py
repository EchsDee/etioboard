"""Acesso ao banco SQLite: conexão, schema e migrações."""
from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    icon        TEXT NOT NULL DEFAULT '📁',
    color       TEXT NOT NULL DEFAULT '#6366F1',
    position    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS snippets (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    file_path         TEXT NOT NULL,
    original_filename TEXT NOT NULL DEFAULT '',
    category_id       INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    icon              TEXT NOT NULL DEFAULT '🔊',
    color             TEXT NOT NULL DEFAULT '#3B3F5C',
    hotkey            TEXT,
    volume            REAL NOT NULL DEFAULT 1.0,
    speed             REAL NOT NULL DEFAULT 1.0,
    loop              INTEGER NOT NULL DEFAULT 0,
    favorite          INTEGER NOT NULL DEFAULT 0,
    position          INTEGER NOT NULL DEFAULT 0,
    duration          REAL NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_snippets_category ON snippets(category_id, position);

CREATE TABLE IF NOT EXISTS presets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    data        TEXT NOT NULL,
    is_default  INTEGER NOT NULL DEFAULT 0,
    builtin_key TEXT,
    hotkey      TEXT,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS hotkeys (
    action  TEXT PRIMARY KEY,
    hotkey  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS autotune_presets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    data        TEXT NOT NULL,
    builtin_key TEXT,
    position    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS songs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    file_path         TEXT NOT NULL,
    original_filename TEXT NOT NULL DEFAULT '',
    duration          REAL NOT NULL DEFAULT 0,
    status            TEXT NOT NULL DEFAULT 'pending',
    error             TEXT,
    analysis          TEXT,
    analysis_auto     TEXT,
    preset_id         INTEGER REFERENCES autotune_presets(id) ON DELETE SET NULL,
    correction_mode   TEXT NOT NULL DEFAULT 'chord',
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""


class Database:
    """Wrapper fino e thread-safe sobre sqlite3."""

    def __init__(self, path: Path | str):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self._migrate()

    # ------------------------------------------------------------------ schema
    def _migrate(self) -> None:
        with self._lock:
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            self.conn.executescript(SCHEMA)
            if version < SCHEMA_VERSION:
                log.info("Migrando banco de dados v%s -> v%s", version, SCHEMA_VERSION)
                self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @property
    def is_new(self) -> bool:
        row = self.query_one("SELECT value FROM settings WHERE key = '__seeded__'")
        return row is None

    def mark_seeded(self) -> None:
        self.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('__seeded__', '1')")

    # ------------------------------------------------------------------ helpers
    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Executa uma instrução e retorna lastrowid."""
        with self._lock:
            cur = self.conn.execute(sql, tuple(params))
            return cur.lastrowid

    def executemany(self, sql: str, rows: Iterable[Iterable[Any]]) -> None:
        with self._lock:
            self.conn.execute("BEGIN")
            try:
                self.conn.executemany(sql, [tuple(r) for r in rows])
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        with self._lock:
            row = self.conn.execute(sql, tuple(params)).fetchone()
            return dict(row) if row else None

    def transaction(self):
        return _Transaction(self)

    def close(self) -> None:
        with self._lock:
            try:
                self.conn.close()
            except sqlite3.Error:
                pass


class _Transaction:
    def __init__(self, db: Database):
        self.db = db

    def __enter__(self):
        self.db._lock.acquire()
        self.db.conn.execute("BEGIN")
        return self.db

    def __exit__(self, exc_type, exc, tb):
        try:
            self.db.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.db._lock.release()
        return False
