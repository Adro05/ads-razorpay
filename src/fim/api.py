"""FastAPI backend for the merchant-facing dashboard.

Read endpoints serve the latest persisted scan. The only write endpoints are
"run a scan" and "record a review" - there is deliberately no endpoint that
edits or deletes a flag, because the value of the audit trail comes entirely
from what it is not allowed to forget.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import MODEL_VERSION, __version__
from .audit import AuditTrail
from .config import Config
from .db import init_db
from .engine import (
    assessments_for_scan,
    flags_with_reviews,
    latest_scan,
    record_review,
    run_scan,
)
from .features import FEATURE_SPECS
from .ingest import load_events
from .models import Event

CONFIG = Config.load()
DASHBOARD_DIR = CONFIG.root / "dashboard"

app = FastAPI(
    title="Internal Fund Integrity Monitor",
    version=__version__,
    description="Defence-only anomaly monitoring for staff-initiated financial actions.",
)


def get_conn() -> sqlite3.Connection:
    return init_db(CONFIG.path("data.db_path"))


class _EventCache:
    """Keeps the CSV in memory, reloading only when the file changes."""

    def __init__(self) -> None:
        self.events: List[Event] = []
        self.mtime: float = -1.0
        self.problems: List[str] = []

    def get(self) -> List[Event]:
        path = CONFIG.path("data.events_csv")
        if not path.exists():
            return []
        mtime = path.stat().st_mtime
        if mtime != self.mtime:
            self.events, self.problems = load_events(path)
            self.mtime = mtime
        return self.events


EVENTS = _EventCache()


class ReviewRequest(BaseModel):
    reviewer: str = Field(min_length=1, description="Who is taking responsibility")
    decision: str
    notes: str = ""


class ScanRequest(BaseModel):
    actor: str = "dashboard"
    as_of: Optional[str] = None


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "version": __version__,
        "model_version": MODEL_VERSION,
        "events_loaded": len(EVENTS.get()),
    }


@app.get("/api/overview")
def overview() -> Dict[str, Any]:
    conn = get_conn()
    try:
        scan = latest_scan(conn)
        if not scan:
            return {"scan": None, "counts": {}, "audit": AuditTrail(conn).verify()}
        rows = assessments_for_scan(conn, scan["scan_id"])
        counts = {
            "employees": len(rows),
            "flagged": sum(1 for r in rows if r["status"] == "flagged"),
            "watch": sum(1 for r in rows if r["status"] == "watch"),
            "clear": sum(1 for r in rows if r["status"] == "clear"),
            "insufficient_data": sum(1 for r in rows if r["status"] == "insufficient_data"),
            "active_now": sum(1 for r in rows if r["presence"] == "active"),
            "open_flags": conn.execute(
                "SELECT COUNT(*) AS c FROM flags WHERE state = 'open'"
            ).fetchone()["c"],
        }
        return {
            "scan": scan,
            "counts": counts,
            "audit": AuditTrail(conn).verify(),
            "thresholds": {
                "flag_score": CONFIG.get("thresholds.flag_score"),
                "watch_score": CONFIG.get("thresholds.watch_score"),
                "window_days": CONFIG.get("window.window_days"),
                "baseline_days": CONFIG.get("window.baseline_days"),
                "active_minutes": CONFIG.get("window.active_minutes"),
            },
        }
    finally:
        conn.close()


@app.get("/api/employees")
def employees(
    status: Optional[str] = None,
    store_id: Optional[str] = None,
    role: Optional[str] = None,
) -> Dict[str, Any]:
    conn = get_conn()
    try:
        scan = latest_scan(conn)
        if not scan:
            return {"scan_id": None, "employees": []}
        rows = assessments_for_scan(conn, scan["scan_id"])
        if status:
            rows = [r for r in rows if r["status"] == status]
        if store_id:
            rows = [r for r in rows if r["store_id"] == store_id]
        if role:
            rows = [r for r in rows if r["role"] == role]
        return {"scan_id": scan["scan_id"], "as_of": scan["as_of"], "employees": rows}
    finally:
        conn.close()


@app.get("/api/employees/{employee_id}")
def employee_detail(employee_id: str, timeline: int = 40) -> Dict[str, Any]:
    conn = get_conn()
    try:
        scan = latest_scan(conn)
        if not scan:
            raise HTTPException(404, "no scans yet")
        rows = assessments_for_scan(conn, scan["scan_id"])
        row = next((r for r in rows if r["employee_id"] == employee_id), None)
        if row is None:
            raise HTTPException(404, f"unknown employee {employee_id}")

        events = [e for e in EVENTS.get() if e.employee_id == employee_id]
        events.sort(key=lambda e: e.timestamp, reverse=True)
        row["timeline"] = [
            {
                "event_id": e.event_id,
                "timestamp": e.timestamp.isoformat(),
                "action_type": e.action_type,
                "amount": e.amount,
                "customer_ref": e.customer_ref,
                "original_txn_id": e.original_txn_id,
                "discount_pct": e.discount_pct,
                "payment_method": e.payment_method,
            }
            for e in events[:timeline]
        ]
        row["history"] = [
            dict(r) for r in conn.execute(
                """
                SELECT s.as_of, a.risk_score, a.status
                FROM assessments a JOIN scans s ON s.scan_id = a.scan_id
                WHERE a.employee_id = ?
                ORDER BY s.created_at DESC LIMIT 20
                """,
                (employee_id,),
            ).fetchall()
        ]
        row["flags"] = flags_with_reviews(conn, employee_id=employee_id)
        return row
    finally:
        conn.close()


@app.get("/api/flags")
def flags(state: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    conn = get_conn()
    try:
        return {"flags": flags_with_reviews(conn, state=state, limit=limit)}
    finally:
        conn.close()


@app.post("/api/flags/{flag_id}/review")
def review(flag_id: str, payload: ReviewRequest) -> Dict[str, Any]:
    conn = get_conn()
    try:
        return record_review(
            conn, flag_id, payload.reviewer, payload.decision, payload.notes,
            CONFIG.get("review.decisions", []),
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        conn.close()


@app.post("/api/scan")
def scan(payload: Optional[ScanRequest] = None) -> Dict[str, Any]:
    payload = payload or ScanRequest()
    conn = get_conn()
    try:
        as_of = datetime.fromisoformat(payload.as_of) if payload.as_of else None
        return run_scan(CONFIG, as_of=as_of, actor=payload.actor, conn=conn)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        conn.close()


@app.get("/api/audit")
def audit(limit: int = 200, entity_id: Optional[str] = None) -> Dict[str, Any]:
    conn = get_conn()
    try:
        trail = AuditTrail(conn)
        return {"entries": trail.entries(limit=limit, entity_id=entity_id),
                "verification": trail.verify()}
    finally:
        conn.close()


@app.get("/api/audit/verify")
def audit_verify() -> Dict[str, Any]:
    conn = get_conn()
    try:
        return AuditTrail(conn).verify()
    finally:
        conn.close()


@app.get("/api/features")
def feature_catalogue() -> Dict[str, Any]:
    return {
        "features": [
            {
                "name": s.name,
                "label": s.label,
                "unit": s.unit,
                "description": s.description,
                "materiality_floor": s.floor,
            }
            for s in FEATURE_SPECS
        ],
        "review_decisions": CONFIG.get("review.decisions", []),
    }


@app.get("/api/metrics")
def metrics() -> JSONResponse:
    path = CONFIG.root / "data" / "evaluation.json"
    if not path.exists():
        return JSONResponse(
            {"available": False,
             "hint": "run: python scripts/evaluate.py --trials 8"},
            status_code=200,
        )
    import json

    return JSONResponse({"available": True, **json.loads(path.read_text(encoding="utf-8"))})


@app.get("/")
def index() -> FileResponse:
    return FileResponse(DASHBOARD_DIR / "index.html")


if DASHBOARD_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="static")
