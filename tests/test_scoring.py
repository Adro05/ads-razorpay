from datetime import datetime

from conftest import AS_OF, build_cohort

from fim.engine import assess
from fim.features import build_feature_table
from fim.models import FeatureVector
from fim.scoring import (
    combine_z,
    resolve_peer_group,
    robust_stats,
    robust_z,
    score_cohort,
    status_for,
    z_to_score,
)


def vec(emp: str, role: str, store: str, **values) -> FeatureVector:
    return FeatureVector(
        employee_id=emp, employee_name=emp, role=role, store_id=store,
        window_start=datetime(2026, 6, 23), window_end=AS_OF, values=values,
        counts={}, event_count=50, last_event_at=AS_OF, data_sufficient=True,
    )


def test_robust_stats_uses_median_not_mean():
    """One extreme colluder must not drag the comparison towards themselves."""
    sample = [0.05, 0.05, 0.06, 0.05, 0.90]
    median, _ = robust_stats(sample)
    assert median == 0.05


def test_materiality_floor_caps_manufactured_sigma():
    """A peer group sitting on identical values must not produce a huge z."""
    identical = [0.10] * 8
    z_no_floor, _, _ = robust_z(0.12, identical, floor=0.0)
    z_floored, _, _ = robust_z(0.12, identical, floor=0.05)
    assert z_no_floor == 0.0        # no spread at all: honest answer is zero
    assert 0 < z_floored < 1.0      # 2 points against a 5-point floor


def test_small_samples_are_shrunk():
    big = [0.05] * 20
    small = [0.05] * 4
    z_big, _, _ = robust_z(0.20, big, floor=0.02)
    z_small, _, _ = robust_z(0.20, small, floor=0.02)
    assert z_small < z_big


def test_combine_z_equals_max_for_single_deviation():
    assert combine_z([4.0, 0.0, -2.0], top_k=3) == 4.0
    # breadth counts for more than a single spike of the same size
    assert combine_z([3.0, 3.0, 3.0], top_k=3) > 3.0


def test_z_to_score_saturates_at_cap():
    assert z_to_score(-1, 6) == 0.0
    assert z_to_score(3, 6) == 50.0
    assert z_to_score(99, 6) == 100.0


def test_peer_group_never_crosses_roles_by_default():
    target = vec("EMP-1", "Returns Desk", "ST-01", refund_rate=0.3)
    cohort = [target] + [vec(f"EMP-{i}", "Cashier", "ST-01", refund_rate=0.04)
                         for i in range(2, 12)]
    label, peers = resolve_peer_group(target, cohort, min_peer_group=4)
    assert peers == []
    assert label == "no comparable peer group"

    label, peers = resolve_peer_group(target, cohort, min_peer_group=4,
                                      allow_cross_role=True)
    assert len(peers) == 10


def test_peer_group_prefers_same_store_then_widens_to_role():
    target = vec("EMP-1", "Cashier", "ST-01", refund_rate=0.05)
    same_store = [vec(f"S{i}", "Cashier", "ST-01", refund_rate=0.05) for i in range(4)]
    other_store = [vec(f"O{i}", "Cashier", "ST-02", refund_rate=0.05) for i in range(4)]
    label, peers = resolve_peer_group(target, [target] + same_store + other_store, 4)
    assert label == "Cashier at ST-01"
    assert len(peers) == 4

    label, peers = resolve_peer_group(target, [target] + other_store, 4)
    assert label == "Cashier across all stores"


def test_status_thresholds():
    assert status_for(85, 70, 50) == "flagged"
    assert status_for(60, 70, 50) == "watch"
    assert status_for(10, 70, 50) == "clear"


def test_obvious_refund_mill_outscores_its_peers(config):
    events = build_cohort(n_employees=8, bad_employee="EMP-3")
    current, baselines = build_feature_table(
        events, as_of=AS_OF, window_days=7, baseline_days=28
    )
    details = score_cohort(current, baselines, config)
    bad = details["EMP-3"].risk_score
    others = [d.risk_score for k, d in details.items() if k != "EMP-3"]
    assert bad > max(others)
    assert bad >= config.get("thresholds.flag_score")


def test_honest_cohort_produces_no_flags(config):
    events = build_cohort(n_employees=8, bad_employee=None)
    assessments, _ = assess(events, config, as_of=AS_OF)
    assert [a.status for a in assessments].count("flagged") == 0


def test_insufficient_data_is_never_flagged(config):
    events = build_cohort(n_employees=8, bad_employee="EMP-3")
    thin = [e for e in events if e.employee_id != "EMP-8"][:]
    thin += [e for e in events if e.employee_id == "EMP-8"][:4]
    assessments, _ = assess(thin, config, as_of=AS_OF)
    emp8 = next(a for a in assessments if a.employee_id == "EMP-8")
    assert emp8.status == "insufficient_data"
    assert emp8.risk_score == 0.0
    assert emp8.reasons == []
