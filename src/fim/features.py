"""Behavioural features per employee, per rolling window.

Every feature is a *rate or a shape*, never a raw count, so that a busy cashier
is not flagged simply for being busy. Raw counts are carried alongside in
`counts` so that explanations can quote real numbers back to the merchant.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Sequence, Tuple

from .models import RISK_ACTIONS, Event, FeatureVector


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    label: str
    unit: str          # ratio | currency | index | pct
    description: str
    template: str      # explanation sentence, formatted with observed/comparison/counts
    floor: float = 0.0
    """Smallest difference in this feature we are willing to call meaningful.

    Used as a floor on the robust sigma. Without it, a peer group that happens to
    sit on nearly identical values turns a one-percentage-point difference into a
    nine-sigma accusation - the single most common way a monitoring tool like this
    manufactures false positives against real people.
    """


FEATURE_SPECS: Tuple[FeatureSpec, ...] = (
    FeatureSpec(
        "refund_rate", "Refund rate", "ratio",
        "Refunds issued per sale processed by this employee.",
        "issued {refund_count:.0f} refunds against {sale_count:.0f} sales "
        "({observed:.1%} of sales) versus {comparison:.1%} for {basis_label}",
        floor=0.02,
    ),
    FeatureSpec(
        "refund_value_ratio", "Refunded value share", "ratio",
        "Refunded money as a share of money taken.",
        "refunded a value of {refund_amount:,.0f} against {sale_amount:,.0f} taken "
        "({observed:.1%} of takings) versus {comparison:.1%} for {basis_label}",
        floor=0.02,
    ),
    FeatureSpec(
        "avg_refund_amount", "Average refund size", "currency",
        "Mean value of a refund.",
        "average refund of {observed:,.2f} versus {comparison:,.2f} for {basis_label}",
        floor=4.0,
    ),
    FeatureSpec(
        "void_rate", "Void rate", "ratio",
        "Voided transactions per sale.",
        "voided {void_count:.0f} transactions ({observed:.1%} of sales) versus "
        "{comparison:.1%} for {basis_label}",
        floor=0.01,
    ),
    FeatureSpec(
        "manual_override_rate", "Manual override rate", "ratio",
        "Share of all actions that bypassed the normal flow.",
        "{override_count:.0f} manual overrides, {observed:.1%} of all actions, "
        "versus {comparison:.1%} for {basis_label}",
        floor=0.01,
    ),
    FeatureSpec(
        "discount_rate", "Discount frequency", "ratio",
        "Discounts applied per sale.",
        "applied discounts on {observed:.1%} of sales versus {comparison:.1%} "
        "for {basis_label}",
        floor=0.02,
    ),
    FeatureSpec(
        "avg_discount_pct", "Average discount depth", "pct",
        "Mean percentage taken off when a discount is applied.",
        "average discount of {observed:.1f}% versus {comparison:.1f}% for {basis_label}",
        floor=2.0,
    ),
    FeatureSpec(
        "off_hours_ratio", "Off-hours activity", "ratio",
        "Share of actions outside configured trading hours.",
        "{observed:.1%} of actions fell outside trading hours versus "
        "{comparison:.1%} for {basis_label}",
        floor=0.03,
    ),
    FeatureSpec(
        "recipient_hhi", "Refund recipient concentration", "index",
        "Herfindahl index over refund counterparties: 1.0 means every refund "
        "went to the same customer record.",
        "refunds spread over only {distinct_recipients:.0f} customer records "
        "(concentration {observed:.2f} versus {comparison:.2f} for {basis_label})",
        floor=0.05,
    ),
    FeatureSpec(
        "top_recipient_share", "Largest recipient share", "ratio",
        "Share of refunds going to a single customer record.",
        "{observed:.0%} of refunds went to one customer record versus "
        "{comparison:.0%} for {basis_label}",
        floor=0.05,
    ),
    FeatureSpec(
        "no_original_ratio", "Refunds with no original sale", "ratio",
        "Refunds not linked to an original transaction.",
        "{no_original_count:.0f} refunds had no linked original sale "
        "({observed:.0%}) versus {comparison:.0%} for {basis_label}",
        floor=0.05,
    ),
    FeatureSpec(
        "repeat_recipient_ratio", "Repeat-recipient refunds", "ratio",
        "Share of refunds going to counterparties this employee has already "
        "refunded three or more times inside the window.",
        "{observed:.0%} of refunds went to repeatedly-refunded customers versus "
        "{comparison:.0%} for {basis_label}",
        floor=0.05,
    ),
)

SPECS_BY_NAME: Dict[str, FeatureSpec] = {s.name: s for s in FEATURE_SPECS}
ALL_FEATURES: Tuple[str, ...] = tuple(s.name for s in FEATURE_SPECS)


def _safe_div(numerator: float, denominator: float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _hhi(labels: Sequence[str]) -> float:
    """Herfindahl-Hirschman index over a list of labels, normalised to 0..1."""
    if not labels:
        return 0.0
    counts = Counter(labels)
    total = float(len(labels))
    return float(sum((c / total) ** 2 for c in counts.values()))


def compute_features(
    events: Sequence[Event],
    business_start: int = 8,
    business_end: int = 21,
    min_refunds_for_concentration: int = 4,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Reduce one employee's window of events to features and supporting counts."""
    sales = [e for e in events if e.action_type == "sale"]
    refunds = [e for e in events if e.action_type == "refund"]
    voids = [e for e in events if e.action_type == "void"]
    discounts = [e for e in events if e.action_type == "discount"]
    overrides = [e for e in events if e.action_type == "manual_override"]

    sale_count = len(sales)
    sale_amount = sum(e.amount for e in sales)
    refund_count = len(refunds)
    refund_amount = sum(e.amount for e in refunds)
    total_actions = len(events)

    # Rates are per-sale so throughput alone never looks like risk. With no sales
    # at all we fall back to a per-action denominator rather than dividing by zero.
    sale_denominator = float(sale_count) if sale_count else float(max(total_actions, 1))

    off_hours = [
        e for e in events
        if e.timestamp.hour < business_start or e.timestamp.hour >= business_end
    ]

    recipients = [e.customer_ref or "unlinked::" + e.event_id for e in refunds]
    enough_refunds = refund_count >= min_refunds_for_concentration
    hhi = _hhi(recipients) if enough_refunds else 0.0
    top_share = (
        max(Counter(recipients).values()) / float(refund_count)
        if enough_refunds and refund_count else 0.0
    )
    repeat_refs = {ref for ref, c in Counter(recipients).items() if c >= 3}
    repeat_ratio = (
        _safe_div(sum(1 for r in recipients if r in repeat_refs), refund_count)
        if enough_refunds else 0.0
    )
    no_original = [e for e in refunds if not e.original_txn_id]

    values: Dict[str, float] = {
        "refund_rate": _safe_div(refund_count, sale_denominator),
        "refund_value_ratio": _safe_div(refund_amount, sale_amount) if sale_amount else 0.0,
        "avg_refund_amount": _safe_div(refund_amount, refund_count),
        "void_rate": _safe_div(len(voids), sale_denominator),
        "manual_override_rate": _safe_div(len(overrides), max(total_actions, 1)),
        "discount_rate": _safe_div(len(discounts), sale_denominator),
        "avg_discount_pct": _safe_div(sum(e.discount_pct for e in discounts), len(discounts)),
        "off_hours_ratio": _safe_div(len(off_hours), max(total_actions, 1)),
        "recipient_hhi": hhi,
        "top_recipient_share": top_share,
        "no_original_ratio": _safe_div(len(no_original), refund_count),
        "repeat_recipient_ratio": repeat_ratio,
    }

    counts: Dict[str, float] = {
        "total_actions": float(total_actions),
        "sale_count": float(sale_count),
        "sale_amount": float(round(sale_amount, 2)),
        "refund_count": float(refund_count),
        "refund_amount": float(round(refund_amount, 2)),
        "void_count": float(len(voids)),
        "discount_count": float(len(discounts)),
        "override_count": float(len(overrides)),
        "off_hours_count": float(len(off_hours)),
        "no_original_count": float(len(no_original)),
        "distinct_recipients": float(len(set(recipients))),
        "risk_action_count": float(sum(1 for e in events if e.action_type in RISK_ACTIONS)),
    }
    return values, counts


def group_by_employee(events: Iterable[Event]) -> Dict[str, List[Event]]:
    grouped: Dict[str, List[Event]] = defaultdict(list)
    for event in events:
        grouped[event.employee_id].append(event)
    return dict(grouped)


def slice_window(events: Sequence[Event], start: datetime, end: datetime) -> List[Event]:
    """Events in [start, end)."""
    return [e for e in events if start <= e.timestamp < end]


def build_feature_table(
    events: Sequence[Event],
    as_of: datetime,
    window_days: int,
    baseline_days: int,
    business_start: int = 8,
    business_end: int = 21,
    min_events_for_scoring: int = 15,
    min_refunds_for_concentration: int = 4,
) -> Tuple[Dict[str, FeatureVector], Dict[str, List[Dict[str, float]]]]:
    """Current-window vectors plus each employee's own prior windows.

    The historical windows are the same length as the scoring window, tiled
    backwards across the baseline period. That is what makes the self-comparison
    meaningful: a 7-day slice is only ever compared with other 7-day slices.
    """
    window = timedelta(days=window_days)
    window_start = as_of - window
    window_end = as_of + timedelta(microseconds=1)   # inclusive of the as-of instant
    grouped = group_by_employee(events)

    current: Dict[str, FeatureVector] = {}
    baselines: Dict[str, List[Dict[str, float]]] = {}
    n_baseline_windows = max(int(baseline_days // window_days), 0)
    min_baseline_events = max(5, min_events_for_scoring // 3)

    for employee_id, emp_events in grouped.items():
        identity = max(emp_events, key=lambda e: e.timestamp)
        win_events = slice_window(emp_events, window_start, window_end)
        values, counts = compute_features(
            win_events, business_start, business_end, min_refunds_for_concentration
        )
        current[employee_id] = FeatureVector(
            employee_id=employee_id,
            employee_name=identity.employee_name or employee_id,
            role=identity.role,
            store_id=identity.store_id,
            window_start=window_start,
            window_end=as_of,
            values=values,
            counts=counts,
            event_count=len(win_events),
            last_event_at=max((e.timestamp for e in win_events), default=None),
            data_sufficient=len(win_events) >= min_events_for_scoring,
        )

        history: List[Dict[str, float]] = []
        for i in range(1, n_baseline_windows + 1):
            hist_end = as_of - window * i
            hist_start = hist_end - window
            hist_events = slice_window(emp_events, hist_start, hist_end)
            if len(hist_events) < min_baseline_events:
                continue  # too thin to be a baseline; excluding beats inventing one
            hist_values, _ = compute_features(
                hist_events, business_start, business_end, min_refunds_for_concentration
            )
            history.append(hist_values)
        baselines[employee_id] = history

    return current, baselines
