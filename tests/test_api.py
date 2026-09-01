"""API tests.

The endpoint handlers are called directly rather than over HTTP: it keeps the
tests independent of the installed starlette/httpx combination, and the handlers
are plain functions by design. One HTTP smoke test is attempted as well and is
skipped when the local TestClient stack cannot be constructed.
"""

import csv

import pytest
from conftest import AS_OF, build_cohort

fim_api = pytest.importorskip("fim.api")

from fim.db import init_db  # noqa: E402
from fim.engine import run_scan  # noqa: E402

CSV_FIELDS = [
    "event_id", "timestamp", "employee_id", "employee_name", "role", "store_id",
    "action_type", "amount", "order_id", "customer_ref", "payment_method",
    "original_txn_id", "discount_pct", "note",
]


@pytest.fixture
def api_config(config, monkeypatch):
    """Point the API module at a throwaway database and event file."""
    events = build_cohort(n_employees=8, bad_employee="EMP-3")
    path = config.path("data.events_csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for e in events:
            writer.writerow({
                "event_id": e.event_id, "timestamp": e.timestamp.isoformat(),
                "employee_id": e.employee_id, "employee_name": e.employee_name,
                "role": e.role, "store_id": e.store_id, "action_type": e.action_type,
                "amount": e.amount, "order_id": e.order_id,
                "customer_ref": e.customer_ref, "payment_method": e.payment_method,
                "original_txn_id": e.original_txn_id, "discount_pct": e.discount_pct,
                "note": e.note,
            })

    monkeypatch.setattr(fim_api, "CONFIG", config)
    monkeypatch.setattr(fim_api, "EVENTS", fim_api._EventCache())

    conn = init_db(config.path("data.db_path"))
    run_scan(config, as_of=AS_OF, actor="pytest", conn=conn, events=events)
    conn.close()
    return config


def test_overview_reports_counts_and_chain_state(api_config):
    data = fim_api.overview()
    assert data["scan"] is not None
    assert data["counts"]["employees"] == 8
    assert data["counts"]["flagged"] >= 1
    assert data["audit"]["ok"] is True


def test_employees_listing_and_filtering(api_config):
    everyone = fim_api.employees()["employees"]
    assert len(everyone) == 8
    assert everyone[0]["risk_score"] >= everyone[-1]["risk_score"]

    flagged = fim_api.employees(status="flagged")["employees"]
    assert all(e["status"] == "flagged" for e in flagged)
    assert fim_api.employees(store_id="nowhere")["employees"] == []


def test_employee_detail_includes_reasons_and_timeline(api_config):
    detail = fim_api.employee_detail("EMP-3")
    assert detail["employee_id"] == "EMP-3"
    assert detail["reasons"], "a flagged employee must arrive with reasons attached"
    assert detail["timeline"], "the merchant needs the underlying actions"
    assert "history" in detail


def test_unknown_employee_is_a_404(api_config):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        fim_api.employee_detail("EMP-nobody")
    assert exc.value.status_code == 404


def test_review_endpoint_records_a_decision(api_config):
    flag = fim_api.flags()["flags"][0]
    payload = fim_api.ReviewRequest(
        reviewer="A. Reviewer", decision="needs_more_info", notes="Pulled the receipts."
    )
    result = fim_api.review(flag["flag_id"], payload)
    assert result["decision"] == "needs_more_info"

    reviewed = next(f for f in fim_api.flags()["flags"] if f["flag_id"] == flag["flag_id"])
    assert reviewed["state"] == "reviewed"
    assert fim_api.audit_verify()["ok"] is True


def test_review_rejects_an_unlisted_decision(api_config):
    from fastapi import HTTPException

    flag = fim_api.flags()["flags"][0]
    with pytest.raises(HTTPException) as exc:
        fim_api.review(flag["flag_id"],
                       fim_api.ReviewRequest(reviewer="A", decision="dismiss_employee"))
    assert exc.value.status_code == 400


def test_there_is_no_endpoint_that_deletes_a_flag():
    """The audit trail is only worth something if nothing can quietly erase it."""
    paths = {(r.path, tuple(sorted(getattr(r, "methods", set()) or set())))
             for r in fim_api.app.routes}
    for path, methods in paths:
        assert "DELETE" not in methods, f"{path} exposes DELETE"
        if path.startswith("/api/audit"):
            assert methods == ("GET",), f"{path} must be read-only"


def test_http_smoke():
    try:
        from fastapi.testclient import TestClient

        client = TestClient(fim_api.app)
        response = client.get("/api/health")
    except Exception as exc:  # pragma: no cover - depends on local httpx/starlette
        pytest.skip(f"TestClient unavailable in this environment: {exc}")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
