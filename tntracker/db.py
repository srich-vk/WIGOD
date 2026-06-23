"""SQLite store and the 'seen' ledger.

One row per GO, keyed by `go_key` (the PDF filename stem, which is globally
unique and stable). `status` tracks progress through the pipeline so a re-run
only does outstanding work and never re-summarizes what's already done.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from . import config

# Pipeline states a row can be in.
STATUS_NEW = "new"            # metadata scraped, nothing fetched yet
STATUS_FETCHED = "fetched"    # PDF downloaded + hashed
STATUS_EXTRACTED = "extracted"  # text pulled out of the PDF
STATUS_SUMMARIZED = "summarized"  # LLM summary stored — terminal/success
STATUS_NO_TEXT = "no_text"    # PDF is scanned/empty — needs OCR, skipped
STATUS_ERROR = "error"        # something failed; see `error` column

SCHEMA = """
CREATE TABLE IF NOT EXISTS gos (
    go_key        TEXT PRIMARY KEY,   -- pdf filename stem, e.g. rd_e_ms_108_2026
    dept_id       INTEGER NOT NULL,
    dept_name     TEXT NOT NULL,
    year          INTEGER NOT NULL,
    go_number     TEXT,               -- e.g. "108"
    go_type       TEXT,               -- ms / d / rt
    source_lang   TEXT,               -- "en" or "ta" (from filename _e_/_t_)
    pdf_url       TEXT NOT NULL,
    pdf_path      TEXT,               -- local cached copy
    pdf_sha256    TEXT,
    go_date       TEXT,               -- ISO date parsed from PDF text, if found
    raw_text_len  INTEGER,
    summary       TEXT,               -- one plain-English line
    policy_area   TEXT,
    districts     TEXT,               -- JSON array
    confidence    REAL,
    source_snippet TEXT,              -- grounding excerpt for auditability
    status        TEXT NOT NULL,
    error         TEXT,
    scraped_at    TEXT DEFAULT (datetime('now')),
    summarized_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_gos_status ON gos(status);
CREATE INDEX IF NOT EXISTS idx_gos_date ON gos(go_date);
"""


def init_db() -> None:
    config.ensure_dirs()
    with get_conn() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def seen(go_key: str) -> bool:
    """Ledger check: has this GO already been recorded?"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM gos WHERE go_key = ?", (go_key,)
        ).fetchone()
        return row is not None


def insert_metadata(meta: dict) -> bool:
    """Insert a freshly scraped GO. Returns False if it already existed.

    For existing rows we backfill light metadata (go_number/go_type) when it was
    missing, without disturbing pipeline status or any stored summary.
    """
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO gos
               (go_key, dept_id, dept_name, year, go_number, go_type,
                source_lang, pdf_url, status)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                meta["go_key"], meta["dept_id"], meta["dept_name"], meta["year"],
                meta.get("go_number"), meta.get("go_type"),
                meta.get("source_lang"), meta["pdf_url"], STATUS_NEW,
            ),
        )
        if cur.rowcount == 0:
            conn.execute(
                """UPDATE gos
                   SET go_number = COALESCE(go_number, ?),
                       go_type   = COALESCE(go_type, ?)
                   WHERE go_key = ?""",
                (meta.get("go_number"), meta.get("go_type"), meta["go_key"]),
            )
        return cur.rowcount > 0


def update(go_key: str, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE gos SET {cols} WHERE go_key = ?",
            (*fields.values(), go_key),
        )


def rows_with_status(*statuses: str) -> list[sqlite3.Row]:
    placeholders = ",".join("?" for _ in statuses)
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM gos WHERE status IN ({placeholders}) ORDER BY go_key",
            statuses,
        ).fetchall()


def summarized_rows() -> list[dict]:
    """All successfully summarized GOs, newest first, ready for rendering."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM gos WHERE status = ?
               ORDER BY COALESCE(go_date, '0000') DESC, go_key DESC""",
            (STATUS_SUMMARIZED,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["districts"] = json.loads(d["districts"]) if d.get("districts") else []
        out.append(d)
    return out


def counts_by_status() -> dict[str, int]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) c FROM gos GROUP BY status"
        ).fetchall()
    return {r["status"]: r["c"] for r in rows}
