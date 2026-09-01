"""SQLite storage for scans, assessments, flags, reviews and the audit log.

SQLite on purpose: the whole evidence base is a single file the merchant can
copy, hand to an accountant, or attach to a dispute. Nothing about this tool
should require trusting a service you cannot inspect.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS scans (
    scan_id          TEXT PRIMARY KEY,
    created_at       TEXT NOT NULL,
    as_of            TEXT NOT NULL,
    window_days      INTEGER NOT NULL,
    baseline_days    INTEGER NOT NULL,
    model_version    TEXT NOT NULL,
    config_digest    TEXT NOT NULL,
    events_ingested  INTEGER NOT NULL,
    employees_seen   INTEGER NOT NULL,
    employees_scored INTEGER NOT NULL,
    flags_raised     INTEGER NOT NULL,
    notes            TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS assessments (
    scan_id         TEXT NOT NULL,
    employee_id     TEXT NOT NULL,
    employee_name   TEXT NOT NULL,
    role            TEXT NOT NULL,
    store_id        TEXT NOT NULL,
    window_start    TEXT NOT NULL,
    window_end      TEXT NOT NULL,
    risk_score      REAL NOT NULL,
    status          TEXT NOT NULL,
    presence        TEXT NOT NULL,
    peer_group      TEXT NOT NULL,
    peer_group_size INTEGER NOT NULL,
    event_count     INTEGER NOT NULL,
    last_event_at   TEXT,
    summary         TEXT NOT NULL DEFAULT '',
    components_json TEXT NOT NULL,
    features_json   TEXT NOT NULL,
    counts_json     TEXT NOT NULL,
    reasons_json    TEXT NOT NULL,
    PRIMARY KEY (scan_id, employee_id),
    FOREIGN KEY (scan_id) REFERENCES scans(scan_id)
);

CREATE TABLE IF NOT EXISTS flags (
    flag_id       TEXT PRIMARY KEY,
    scan_id       TEXT NOT NULL,
    employee_id   TEXT NOT NULL,
    employee_name TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    window_start  TEXT NOT NULL,
    window_end    TEXT NOT NULL,
    risk_score    REAL NOT NULL,
    status        TEXT NOT NULL,
    summary       TEXT NOT NULL,
    reasons_json  TEXT NOT NULL,
    model_version TEXT NOT NULL,
    state         TEXT NOT NULL DEFAULT 'open',
    FOREIGN KEY (scan_id) REFERENCES scans(scan_id)
);

CREATE TABLE IF NOT EXISTS reviews (
    review_id  TEXT PRIMARY KEY,
    flag_id    TEXT NOT NULL,
    reviewer   TEXT NOT NULL,
    decision   TEXT NOT NULL,
    notes      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (flag_id) REFERENCES flags(flag_id)
);

-- Append-only, hash-chained. See audit.py.
CREATE TABLE IF NOT EXISTS audit_log (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    actor        TEXT NOT NULL,
    action       TEXT NOT NULL,
    entity_type  TEXT NOT NULL,
    entity_id    TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    prev_hash    TEXT NOT NULL,
    entry_hash   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_flags_employee ON flags(employee_id);
CREATE INDEX IF NOT EXISTS idx_flags_scan ON flags(scan_id);
CREATE INDEX IF NOT EXISTS idx_reviews_flag ON reviews(flag_id);
CREATE INDEX IF NOT EXISTS idx_assess_employee ON assessments(employee_id);
"""

# Rows edited after the fact would break the paper trail. The audit log is
# protected by the hash chain; these triggers stop the obvious accidents.
GUARDS = """
CREATE TRIGGER IF NOT EXISTS audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str | Path) -> sqlite3.Connection:
    conn = connect(db_path)
    conn.executescript(SCHEMA)
    conn.executescript(GUARDS)
    conn.commit()
    return conn


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> List[Dict[str, Any]]:
    return [dict(r) for r in rows]


def loads(value: Optional[str], default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)
