"""Pipeline: ingest -> features -> score -> explain -> persist -> audit.

`run_scan` is the only place that writes flags, and it always writes an audit
entry for each one. There is no code path that raises a flag off the record.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from . import MODEL_VERSION
from .audit import AuditTrail
from .config import Config
from .db import dumps, init_db, loads
from .explain import build_reasons, summarise
from .features import build_feature_table
from .ingest import load_events
from .models import EmployeeAssessment, Event
from .scoring import score_cohort, status_for


def config_digest(config: Config) -> str:
    blob = json.dumps(config.data, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _presence(
    last_event_at: Optional[datetime],
    as_of: datetime,
    active_minutes: int,
    idle_hours: int,
) -> str:
    """Live status for the tracker: is this person handling money right now?"""
    if last_event_at is None:
        return "off_shift"
    age = as_of - last_event_at
    if age <= timedelta(minutes=active_minutes):
        return "active"
    if age <= timedelta(hours=idle_hours):
        return "idle"
    return "off_shift"


def assess(
    events: Sequence[Event],
    config: Config,
    as_of: Optional[datetime] = None,
) -> tuple[List[EmployeeAssessment], datetime]:
    """Score every employee for the window ending at `as_of`. Pure: no writes."""
    if as_of is None:
        as_of = max(e.timestamp for e in events)

    current, baselines = build_feature_table(
        events,
        as_of=as_of,
        window_days=int(config.get("window.window_days", 7)),
        baseline_days=int(config.get("window.baseline_days", 28)),
        business_start=int(config.get("business_hours.start_hour", 8)),
        business_end=int(config.get("business_hours.end_hour", 21)),
        min_events_for_scoring=int(config.get("thresholds.min_events_for_scoring", 15)),
        min_refunds_for_concentration=int(
            config.get("thresholds.min_refunds_for_concentration", 4)
        ),
    )
    details = score_cohort(current, baselines, config)

    flag_at = float(config.get("thresholds.flag_score", 70))
    watch_at = float(config.get("thresholds.watch_score", 50))
    active_minutes = int(config.get("window.active_minutes", 45))
    idle_hours = int(config.get("window.idle_hours", 12))

    assessments: List[EmployeeAssessment] = []
    for employee_id, vector in current.items():
        detail = details[employee_id]
        if detail.scored:
            reasons = build_reasons(detail, vector, config)
            status = status_for(detail.risk_score, flag_at, watch_at)
            summary = summarise(reasons, status, detail.risk_score)
            # A flag with nothing to say is not a flag. If the score cleared the
            # bar but no single deviation is reportable, we hold it at "watch"
            # rather than accuse someone with an empty explanation.
            if status == "flagged" and not reasons:
                status = "watch"
                summary = "Composite score high but no single deviation is individually reportable."
        else:
            reasons = []
            status = "insufficient_data"
            summary = detail.skip_reason

        assessments.append(
            EmployeeAssessment(
                employee_id=employee_id,
                employee_name=vector.employee_name,
                role=vector.role,
                store_id=vector.store_id,
                window_start=vector.window_start,
                window_end=vector.window_end,
                risk_score=detail.risk_score,
                status=status,
                presence=_presence(vector.last_event_at, as_of, active_minutes, idle_hours),
                components=detail.components,
                peer_group=detail.peer_group,
                peer_group_size=detail.peer_group_size,
                reasons=reasons,
                features={k: round(float(v), 6) for k, v in vector.values.items()},
                counts=vector.counts,
                event_count=vector.event_count,
                last_event_at=vector.last_event_at,
                summary=summary,
            )
        )

    assessments.sort(key=lambda a: (-a.risk_score, a.employee_name))
    return assessments, as_of


def run_scan(
    config: Config,
    as_of: Optional[datetime] = None,
    actor: str = "system",
    conn: Optional[sqlite3.Connection] = None,
    events: Optional[Sequence[Event]] = None,
) -> Dict[str, Any]:
    """Run a full scan and persist it. Returns a summary dict."""
    own_conn = conn is None
    conn = conn or init_db(config.path("data.db_path"))
    audit = AuditTrail(conn)

    problems: List[str] = []
    if events is None:
        events, problems = load_events(config.path("data.events_csv"))
    if not events:
        raise ValueError("no usable events found; nothing to scan")

    scan_id = f"scan-{uuid.uuid4().hex[:12]}"
    digest = config_digest(config)
    audit.record(
        actor, "scan.started", "scan", scan_id,
        {
            "events": len(events),
            "ingest_problems": len(problems),
            "config_digest": digest,
            "model_version": MODEL_VERSION,
        },
    )

    assessments, resolved_as_of = assess(events, config, as_of)
    created_at = datetime.now().isoformat(timespec="seconds")
    flagged = [a for a in assessments if a.status == "flagged"]

    conn.execute(
        """
        INSERT INTO scans (scan_id, created_at, as_of, window_days, baseline_days,
                           model_version, config_digest, events_ingested,
                           employees_seen, employees_scored, flags_raised, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scan_id, created_at, resolved_as_of.isoformat(),
            int(config.get("window.window_days", 7)),
            int(config.get("window.baseline_days", 28)),
            MODEL_VERSION, digest, len(events), len(assessments),
            sum(1 for a in assessments if a.status != "insufficient_data"),
            len(flagged),
            f"{len(problems)} rows rejected at ingest" if problems else "",
        ),
    )

    for a in assessments:
        conn.execute(
            """
            INSERT INTO assessments
                (scan_id, employee_id, employee_name, role, store_id, window_start,
                 window_end, risk_score, status, presence, peer_group, peer_group_size,
                 event_count, last_event_at, summary, components_json, features_json,
                 counts_json, reasons_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scan_id, a.employee_id, a.employee_name, a.role, a.store_id,
                a.window_start.isoformat(), a.window_end.isoformat(), a.risk_score,
                a.status, a.presence, a.peer_group, a.peer_group_size, a.event_count,
                a.last_event_at.isoformat() if a.last_event_at else None,
                a.summary, dumps(a.components), dumps(a.features),
                dumps(a.counts), dumps([r.to_dict() for r in a.reasons]),
            ),
        )

    flag_ids: List[str] = []
    for a in flagged:
        flag_id = f"flag-{uuid.uuid4().hex[:12]}"
        flag_ids.append(flag_id)
        conn.execute(
            """
            INSERT INTO flags (flag_id, scan_id, employee_id, employee_name, created_at,
                               window_start, window_end, risk_score, status, summary,
                               reasons_json, model_version, state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
            """,
            (
                flag_id, scan_id, a.employee_id, a.employee_name, created_at,
                a.window_start.isoformat(), a.window_end.isoformat(), a.risk_score,
                a.status, a.summary,
                dumps([r.to_dict() for r in a.reasons]), MODEL_VERSION,
            ),
        )
        audit.record(
            actor, "flag.raised", "flag", flag_id,
            {
                "employee_id": a.employee_id,
                "risk_score": a.risk_score,
                "scan_id": scan_id,
                "peer_group": a.peer_group,
                "components": a.components,
                "reasons": [
                    {"code": r.code, "z": r.z, "headline": r.headline} for r in a.reasons
                ],
            },
        )

    conn.commit()
    audit.record(
        actor, "scan.completed", "scan", scan_id,
        {
            "employees_seen": len(assessments),
            "flags_raised": len(flagged),
            "watch": sum(1 for a in assessments if a.status == "watch"),
            "insufficient_data": sum(
                1 for a in assessments if a.status == "insufficient_data"
            ),
        },
    )

    summary = {
        "scan_id": scan_id,
        "as_of": resolved_as_of.isoformat(),
        "events_ingested": len(events),
        "ingest_problems": problems[:20],
        "employees_seen": len(assessments),
        "flags_raised": len(flagged),
        "flag_ids": flag_ids,
        "watch": sum(1 for a in assessments if a.status == "watch"),
        "insufficient_data": sum(1 for a in assessments if a.status == "insufficient_data"),
        "model_version": MODEL_VERSION,
        "config_digest": digest,
    }
    if own_conn:
        conn.close()
    return summary


# --------------------------------------------------------------------------
# Read helpers used by the API and CLI
# --------------------------------------------------------------------------

def latest_scan(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM scans ORDER BY created_at DESC, rowid DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def assessments_for_scan(conn: sqlite3.Connection, scan_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM assessments WHERE scan_id = ? ORDER BY risk_score DESC, employee_name",
        (scan_id,),
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["components"] = loads(item.pop("components_json"), {})
        item["features"] = loads(item.pop("features_json"), {})
        item["counts"] = loads(item.pop("counts_json"), {})
        item["reasons"] = loads(item.pop("reasons_json"), [])
        out.append(item)
    return out


def flags_with_reviews(
    conn: sqlite3.Connection,
    state: Optional[str] = None,
    employee_id: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM flags"
    clauses, params = [], []
    if state:
        clauses.append("state = ?")
        params.append(state)
    if employee_id:
        clauses.append("employee_id = ?")
        params.append(employee_id)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
    params.append(int(limit))

    flags = []
    for row in conn.execute(sql, params).fetchall():
        item = dict(row)
        item["reasons"] = loads(item.pop("reasons_json"), [])
        item["reviews"] = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM reviews WHERE flag_id = ? ORDER BY created_at",
                (item["flag_id"],),
            ).fetchall()
        ]
        flags.append(item)
    return flags


def record_review(
    conn: sqlite3.Connection,
    flag_id: str,
    reviewer: str,
    decision: str,
    notes: str,
    allowed_decisions: Sequence[str],
) -> Dict[str, Any]:
    """Attach a human decision to a flag. The flag itself is never deleted."""
    if decision not in allowed_decisions:
        raise ValueError(f"decision must be one of {list(allowed_decisions)}")
    row = conn.execute("SELECT * FROM flags WHERE flag_id = ?", (flag_id,)).fetchone()
    if row is None:
        raise KeyError(f"unknown flag {flag_id}")
    if not reviewer.strip():
        raise ValueError("a review must name a reviewer")

    review_id = f"rev-{uuid.uuid4().hex[:12]}"
    created_at = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO reviews (review_id, flag_id, reviewer, decision, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (review_id, flag_id, reviewer.strip(), decision, notes.strip(), created_at),
    )
    conn.execute("UPDATE flags SET state = 'reviewed' WHERE flag_id = ?", (flag_id,))
    conn.commit()

    AuditTrail(conn).record(
        reviewer.strip(), "flag.reviewed", "flag", flag_id,
        {
            "review_id": review_id,
            "decision": decision,
            "notes": notes.strip(),
            "employee_id": row["employee_id"],
            "risk_score": row["risk_score"],
        },
    )
    return {
        "review_id": review_id,
        "flag_id": flag_id,
        "reviewer": reviewer.strip(),
        "decision": decision,
        "notes": notes.strip(),
        "created_at": created_at,
    }
