import sqlite3

import pytest
from conftest import AS_OF, build_cohort

from fim.audit import GENESIS, AuditTrail, compute_hash
from fim.db import init_db
from fim.engine import assess, flags_with_reviews, record_review, run_scan


# --------------------------------------------------------------- explainability
def test_every_flag_carries_a_stated_reason(config):
    events = build_cohort(n_employees=8, bad_employee="EMP-3")
    assessments, _ = assess(events, config, as_of=AS_OF)
    flagged = [a for a in assessments if a.status == "flagged"]
    assert flagged, "fixture should produce at least one flag"
    for a in flagged:
        assert a.reasons, f"{a.employee_id} was flagged with no reason"
        for reason in a.reasons:
            assert reason.headline and reason.detail
            assert reason.basis in ("peer", "self", "model")
            # The detail must quote real numbers back, not just assert a verdict.
            assert any(ch.isdigit() for ch in reason.detail)


def test_reason_contributions_are_shares_of_the_score(config):
    events = build_cohort(n_employees=8, bad_employee="EMP-3")
    assessments, _ = assess(events, config, as_of=AS_OF)
    bad = next(a for a in assessments if a.employee_id == "EMP-3")
    total = sum(r.contribution for r in bad.reasons)
    assert 0 < total <= 1.05  # top-N reasons, so slightly under 1 is expected


def test_summary_is_written_for_every_employee(config):
    events = build_cohort(n_employees=8, bad_employee="EMP-3")
    assessments, _ = assess(events, config, as_of=AS_OF)
    assert all(a.summary for a in assessments)


# ----------------------------------------------------------------- audit trail
def test_chain_verifies_after_appends(tmp_path):
    conn = init_db(tmp_path / "audit.db")
    trail = AuditTrail(conn)
    assert trail.head() == (0, GENESIS)
    for i in range(5):
        trail.record("tester", "test.action", "thing", f"id-{i}", {"i": i})
    report = trail.verify()
    assert report["ok"] is True
    assert report["entries"] == 5
    conn.close()


def test_audit_log_rejects_updates_and_deletes(tmp_path):
    conn = init_db(tmp_path / "audit.db")
    AuditTrail(conn).record("tester", "test.action", "thing", "id-1", {})
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE audit_log SET actor = 'someone else' WHERE seq = 1")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM audit_log WHERE seq = 1")
    conn.close()


def test_forged_entry_breaks_verification(tmp_path):
    conn = init_db(tmp_path / "audit.db")
    trail = AuditTrail(conn)
    trail.record("tester", "flag.raised", "flag", "flag-1", {"risk_score": 90})
    # Someone inserts a record directly, without extending the chain honestly.
    conn.execute(
        """
        INSERT INTO audit_log (seq, ts, actor, action, entity_type, entity_id,
                               payload_json, prev_hash, entry_hash)
        VALUES (2, '2026-01-01T00:00:00', 'ghost', 'flag.reviewed', 'flag',
                'flag-1', '{}', 'not-the-previous-hash', 'made-up-hash')
        """
    )
    conn.commit()
    report = trail.verify()
    assert report["ok"] is False
    assert report["broken_at"] == 2
    conn.close()


def test_hash_covers_the_payload(tmp_path):
    a = compute_hash(1, "t", "actor", "act", "flag", "f1", '{"risk_score":90}', GENESIS)
    b = compute_hash(1, "t", "actor", "act", "flag", "f1", '{"risk_score":10}', GENESIS)
    assert a != b


# ---------------------------------------------------------------- full pipeline
def test_run_scan_persists_flags_and_audit_entries(config, tmp_path):
    events = build_cohort(n_employees=8, bad_employee="EMP-3")
    conn = init_db(config.path("data.db_path"))
    summary = run_scan(config, as_of=AS_OF, actor="pytest", conn=conn, events=events)

    assert summary["flags_raised"] >= 1
    flags = flags_with_reviews(conn)
    assert len(flags) == summary["flags_raised"]
    assert all(f["state"] == "open" for f in flags)
    assert all(f["reasons"] for f in flags), "a persisted flag must carry its reasons"

    actions = [e["action"] for e in AuditTrail(conn).entries(limit=50)]
    assert "scan.started" in actions
    assert "scan.completed" in actions
    assert actions.count("flag.raised") == summary["flags_raised"]
    assert AuditTrail(conn).verify()["ok"]
    conn.close()


def test_review_is_recorded_and_audited(config):
    events = build_cohort(n_employees=8, bad_employee="EMP-3")
    conn = init_db(config.path("data.db_path"))
    run_scan(config, as_of=AS_OF, actor="pytest", conn=conn, events=events)
    flag_id = flags_with_reviews(conn)[0]["flag_id"]

    record_review(conn, flag_id, "R. Mensah", "cleared", "Checked the receipts.",
                  config.get("review.decisions"))
    flag = next(f for f in flags_with_reviews(conn) if f["flag_id"] == flag_id)
    assert flag["state"] == "reviewed"
    assert flag["reviews"][0]["reviewer"] == "R. Mensah"

    entry = next(e for e in AuditTrail(conn).entries(limit=10)
                 if e["action"] == "flag.reviewed")
    assert entry["actor"] == "R. Mensah"
    assert entry["payload"]["decision"] == "cleared"
    assert AuditTrail(conn).verify()["ok"]
    conn.close()


def test_review_rejects_unknown_decisions_and_anonymous_reviewers(config):
    events = build_cohort(n_employees=8, bad_employee="EMP-3")
    conn = init_db(config.path("data.db_path"))
    run_scan(config, as_of=AS_OF, actor="pytest", conn=conn, events=events)
    flag_id = flags_with_reviews(conn)[0]["flag_id"]

    with pytest.raises(ValueError):
        record_review(conn, flag_id, "someone", "fired_them",
                      "", config.get("review.decisions"))
    with pytest.raises(ValueError):
        record_review(conn, flag_id, "  ", "cleared", "", config.get("review.decisions"))
    with pytest.raises(KeyError):
        record_review(conn, "flag-does-not-exist", "someone", "cleared", "",
                      config.get("review.decisions"))
    conn.close()
