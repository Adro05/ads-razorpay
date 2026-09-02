"""FastAPI backend for the merchant-facing dashboard.

Read endpoints serve the latest persisted scan. The only write endpoints are
"run a scan" and "record a review" - there is deliberately no endpoint that
edits or deletes a flag, because the value of the audit trail comes entirely
from what it is not allowed to forget.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
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

# Which named entry in config.yaml's `datasets:` block CONFIG.data["data"]
# currently points at. Purely a UI convenience for labelling the active
# choice in /api/datasets; switching datasets mutates CONFIG in place the
# same way tests already do via monkeypatch.
ACTIVE_DATASET = "default"

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


SIM_DIR = CONFIG.root / "data" / "simulations"
SIM_INDEX = SIM_DIR / "index.json"


class SimulationRequest(BaseModel):
    """Bounded so a UI-triggered generation can never become a resource hog."""

    name: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9_-]+$")
    employees: int = Field(20, ge=6, le=60)
    days: int = Field(90, ge=14, le=200)
    bad_actors: int = Field(3, ge=0, le=8)
    seed: int = Field(1, ge=0, le=10_000_000)


def _load_simulations() -> Dict[str, Any]:
    if not SIM_INDEX.exists():
        return {}
    try:
        return json.loads(SIM_INDEX.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_simulations(index: Dict[str, Any]) -> None:
    SIM_DIR.mkdir(parents=True, exist_ok=True)
    SIM_INDEX.write_text(json.dumps(index, indent=2), encoding="utf-8")


def _sim_modules():
    """Reuse the existing generator and evaluator exactly as the CLI does."""
    scripts_dir = str(CONFIG.root / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import evaluate as ev  # noqa: E402
    import generate_synthetic_data as gen  # noqa: E402

    return gen, ev


# Simulations created in a previous run of the server still have their files
# on disk; re-register them as datasets on startup so they don't disappear
# from the switcher just because the process restarted.
for _sim_name, _sim_entry in _load_simulations().items():
    CONFIG.data.setdefault("datasets", {}).setdefault(_sim_name, {
        "label": _sim_entry.get("label", _sim_name),
        "description": _sim_entry.get("description", ""),
        "events_csv": _sim_entry["events_csv"],
        "db_path": _sim_entry["db_path"],
        "ground_truth_json": _sim_entry.get("ground_truth_json", ""),
    })


@app.get("/api/simulations")
def simulations() -> Dict[str, Any]:
    return {"simulations": list(_load_simulations().values())}


@app.post("/api/simulations")
def create_simulation(payload: SimulationRequest) -> Dict[str, Any]:
    """Generate a brand-new synthetic store, scan it, and register it as a dataset.

    Pure composition of existing pieces - generate_synthetic_data.generate(),
    run_scan(), and evaluate's own scoring function - over a fresh, isolated
    (events, db) pair under data/simulations/<name>/. No detection code changes.
    """
    index = _load_simulations()
    registry = CONFIG.get("datasets") or {}
    if payload.name in index or payload.name in registry:
        raise HTTPException(400, f"a dataset named {payload.name!r} already exists")

    gen, ev = _sim_modules()

    sim_root = SIM_DIR / payload.name
    events_path = sim_root / "events.csv"
    truth_path = sim_root / "ground_truth.json"
    db_path = sim_root / "fim.db"

    ledger, employees, truth = gen.generate(
        days=payload.days, n_employees=payload.employees,
        n_bad=payload.bad_actors, seed=payload.seed,
        stores=[payload.name.upper()],
    )
    gen.write_csv(ledger, events_path)
    truth_path.write_text(json.dumps(truth, indent=2), encoding="utf-8")

    sim_config = Config(dict(CONFIG.data), CONFIG.root)
    sim_config.data["data"] = {
        "events_csv": str(events_path.relative_to(CONFIG.root)),
        "db_path": str(db_path.relative_to(CONFIG.root)),
        "ground_truth_json": str(truth_path.relative_to(CONFIG.root)),
    }
    scan_summary = run_scan(sim_config, actor="simulation-lab")

    events, _problems = load_events(events_path)
    metrics = ev.evaluate_once(events, truth, sim_config)

    entry = {
        "name": payload.name,
        "label": f"Simulation: {payload.name}",
        "description": (
            f"{payload.employees} employees, {payload.days} days, "
            f"{payload.bad_actors} planted actors, seed {payload.seed}."
        ),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "params": payload.model_dump(),
        "events_csv": sim_config.data["data"]["events_csv"],
        "db_path": sim_config.data["data"]["db_path"],
        "ground_truth_json": sim_config.data["data"]["ground_truth_json"],
        "scan": scan_summary,
        "metrics": {
            "flagged": metrics["flagged"],
            "flagged_or_watch": metrics["flagged_or_watch"],
            "average_precision": metrics["average_precision"],
            "planted": metrics["planted"],
            "per_pattern": metrics["per_pattern"],
        },
    }
    index[payload.name] = entry
    _save_simulations(index)

    # Make it selectable in the dataset switcher immediately, without a restart.
    registry[payload.name] = {
        "label": entry["label"],
        "description": entry["description"],
        "events_csv": entry["events_csv"],
        "db_path": entry["db_path"],
        "ground_truth_json": entry["ground_truth_json"],
    }
    CONFIG.data["datasets"] = registry

    return entry


@app.get("/api/audit")
def audit(
    limit: int = 200, entity_id: Optional[str] = None, action: Optional[str] = None
) -> Dict[str, Any]:
    conn = get_conn()
    try:
        trail = AuditTrail(conn)
        return {"entries": trail.entries(limit=limit, entity_id=entity_id, action=action),
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


@app.get("/api/datasets")
def datasets() -> Dict[str, Any]:
    """List the named (events, db) pairs the dashboard can switch between."""
    registry = CONFIG.get("datasets") or {}
    out = []
    for dataset_id, entry in registry.items():
        events_path = CONFIG.root / entry["events_csv"]
        db_path = CONFIG.root / entry["db_path"]
        truth_path = CONFIG.root / entry["ground_truth_json"] if entry.get("ground_truth_json") else None
        planted = None
        if truth_path and truth_path.exists():
            try:
                truth = json.loads(truth_path.read_text(encoding="utf-8"))
                planted = len(truth.get("labelled") or {})
            except (json.JSONDecodeError, OSError):
                planted = None
        out.append({
            "id": dataset_id,
            "label": entry.get("label", dataset_id),
            "description": entry.get("description", ""),
            "is_active": dataset_id == ACTIVE_DATASET,
            "events_ready": events_path.exists(),
            "planted_actors": planted,
        })
    return {"active": ACTIVE_DATASET, "datasets": out}


@app.post("/api/datasets/{dataset_id}/activate")
def activate_dataset(dataset_id: str) -> Dict[str, Any]:
    """Point the running server at a different named dataset.

    This only swaps which files CONFIG resolves to a plain in-memory switch,
    same mechanism the test suite already uses (see conftest.api_config).
    Nothing about a scan, flag or the audit log changes - each dataset keeps
    its own database file untouched.
    """
    global ACTIVE_DATASET, EVENTS
    registry = CONFIG.get("datasets") or {}
    entry = registry.get(dataset_id)
    if entry is None:
        raise HTTPException(404, f"unknown dataset {dataset_id!r}")
    CONFIG.data["data"] = {
        "events_csv": entry["events_csv"],
        "db_path": entry["db_path"],
        "ground_truth_json": entry.get("ground_truth_json", ""),
    }
    ACTIVE_DATASET = dataset_id
    EVENTS = _EventCache()
    return {"active": ACTIVE_DATASET}


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
    return JSONResponse({"available": True, **json.loads(path.read_text(encoding="utf-8"))})


@app.get("/")
def index() -> FileResponse:
    return FileResponse(DASHBOARD_DIR / "index.html")


if DASHBOARD_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="static")
