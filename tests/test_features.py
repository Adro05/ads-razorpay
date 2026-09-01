from datetime import timedelta

from conftest import AS_OF, build_cohort, make_event

from fim.features import _hhi, build_feature_table, compute_features


def test_hhi_bounds():
    assert _hhi([]) == 0.0
    assert _hhi(["a", "a", "a"]) == 1.0
    assert _hhi(["a", "b", "c", "d"]) == 0.25
    assert 0.25 < _hhi(["a", "a", "b", "c"]) < 1.0


def test_rates_are_per_sale_not_raw_counts():
    """A busy employee and a quiet one with the same ratio must score the same."""
    busy = [make_event(i, action="sale") for i in range(100)]
    busy += [make_event(1000 + i, action="refund") for i in range(10)]
    quiet = [make_event(i, action="sale") for i in range(10)]
    quiet += [make_event(2000 + i, action="refund") for i in range(1)]

    busy_values, _ = compute_features(busy)
    quiet_values, _ = compute_features(quiet)
    assert busy_values["refund_rate"] == quiet_values["refund_rate"] == 0.1


def test_recipient_concentration_needs_enough_refunds():
    """Two refunds to the same person is a coincidence, not a pattern."""
    few = [make_event(i, action="sale") for i in range(20)]
    few += [make_event(100 + i, action="refund", customer="CUST-1") for i in range(2)]
    values, _ = compute_features(few, min_refunds_for_concentration=4)
    assert values["recipient_hhi"] == 0.0

    many = [make_event(i, action="sale") for i in range(20)]
    many += [make_event(200 + i, action="refund", customer="CUST-1") for i in range(6)]
    values, _ = compute_features(many, min_refunds_for_concentration=4)
    assert values["recipient_hhi"] == 1.0
    assert values["top_recipient_share"] == 1.0
    assert values["repeat_recipient_ratio"] == 1.0


def test_off_hours_uses_configured_trading_hours():
    events = [
        make_event(1, action="sale", when=AS_OF.replace(hour=10)),
        make_event(2, action="void", when=AS_OF.replace(hour=23)),
    ]
    values, counts = compute_features(events, business_start=8, business_end=21)
    assert values["off_hours_ratio"] == 0.5
    assert counts["off_hours_count"] == 1


def test_no_original_ratio_only_counts_refunds():
    events = [make_event(1, action="sale")]
    events += [make_event(2, action="refund", original="evt-1")]
    events += [make_event(3, action="refund", original="")]
    values, counts = compute_features(events)
    assert values["no_original_ratio"] == 0.5
    assert counts["no_original_count"] == 1


def test_window_and_baseline_split():
    events = build_cohort(n_employees=3, days=35)
    current, baselines = build_feature_table(
        events, as_of=AS_OF, window_days=7, baseline_days=28
    )
    assert set(current) == {"EMP-1", "EMP-2", "EMP-3"}
    vector = current["EMP-1"]
    assert vector.window_end == AS_OF
    assert vector.window_start == AS_OF - timedelta(days=7)
    # 28 days of history at 7-day windows gives four comparable prior windows.
    assert len(baselines["EMP-1"]) == 4
    assert vector.data_sufficient is True


def test_thin_window_is_marked_insufficient():
    events = [make_event(i, action="sale") for i in range(3)]
    current, _ = build_feature_table(
        events, as_of=AS_OF, window_days=7, baseline_days=28, min_events_for_scoring=15
    )
    assert current["EMP-1"].data_sufficient is False
