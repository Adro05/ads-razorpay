"""Tamper-evident audit trail.

Every consequential act - a scan running, a flag being raised, a human reviewing
it, a threshold being changed - is appended to a hash chain. Each entry commits
to the hash of the entry before it, so removing or editing history invalidates
every subsequent link and `verify()` will name the first broken seq.

This is deliberately modest: a hash chain in a local SQLite file proves internal
consistency, not that nobody with write access rewrote the whole chain. To claim
more you would anchor the head hash somewhere the merchant does not control
(a daily email, an append-only bucket, a notary). `head()` exists for exactly
that, and the honest limitation is documented in the README.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

GENESIS = "0" * 64


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(
    seq: int,
    ts: str,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    payload_json: str,
    prev_hash: str,
) -> str:
    blob = "|".join(
        [str(seq), ts, actor, action, entity_type, entity_id, payload_json, prev_hash]
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AuditTrail:
    """Append-only log over an existing SQLite connection."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def head(self) -> Tuple[int, str]:
        """(seq, hash) of the newest entry, or (0, GENESIS) when empty."""
        row = self.conn.execute(
            "SELECT seq, entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return 0, GENESIS
        return int(row["seq"]), str(row["entry_hash"])

    def record(
        self,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str,
        payload: Optional[Dict[str, Any]] = None,
        ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        prev_seq, prev_hash = self.head()
        seq = prev_seq + 1
        ts = ts or _now()
        payload_json = _canonical(payload or {})
        entry_hash = compute_hash(
            seq, ts, actor, action, entity_type, entity_id, payload_json, prev_hash
        )
        self.conn.execute(
            """
            INSERT INTO audit_log
                (seq, ts, actor, action, entity_type, entity_id, payload_json,
                 prev_hash, entry_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (seq, ts, actor, action, entity_type, entity_id, payload_json,
             prev_hash, entry_hash),
        )
        self.conn.commit()
        return {
            "seq": seq,
            "ts": ts,
            "actor": actor,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "payload": json.loads(payload_json),
            "prev_hash": prev_hash,
            "entry_hash": entry_hash,
        }

    def entries(
        self,
        limit: int = 200,
        entity_id: Optional[str] = None,
        action: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM audit_log"
        clauses, params = [], []
        if entity_id:
            clauses.append("entity_id = ?")
            params.append(entity_id)
        if action:
            clauses.append("action = ?")
            params.append(action)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY seq DESC LIMIT ?"
        params.append(int(limit))
        rows = self.conn.execute(sql, params).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            out.append(item)
        return out

    def verify(self) -> Dict[str, Any]:
        """Walk the chain from the start. Returns a verification report."""
        rows = self.conn.execute("SELECT * FROM audit_log ORDER BY seq ASC").fetchall()
        prev_hash = GENESIS
        expected_seq = 1
        for row in rows:
            if int(row["seq"]) != expected_seq:
                return {
                    "ok": False,
                    "entries": len(rows),
                    "broken_at": int(row["seq"]),
                    "problem": f"sequence gap: expected {expected_seq}, found {row['seq']}",
                    "head": prev_hash,
                }
            if str(row["prev_hash"]) != prev_hash:
                return {
                    "ok": False,
                    "entries": len(rows),
                    "broken_at": int(row["seq"]),
                    "problem": "prev_hash does not match the previous entry",
                    "head": prev_hash,
                }
            recomputed = compute_hash(
                int(row["seq"]), row["ts"], row["actor"], row["action"],
                row["entity_type"], row["entity_id"], row["payload_json"],
                row["prev_hash"],
            )
            if recomputed != str(row["entry_hash"]):
                return {
                    "ok": False,
                    "entries": len(rows),
                    "broken_at": int(row["seq"]),
                    "problem": "entry contents do not match its recorded hash",
                    "head": prev_hash,
                }
            prev_hash = str(row["entry_hash"])
            expected_seq += 1
        return {
            "ok": True,
            "entries": len(rows),
            "broken_at": None,
            "problem": None,
            "head": prev_hash,
        }
