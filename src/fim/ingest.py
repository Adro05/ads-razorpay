"""CSV ingest for staff-initiated financial actions.

Deliberately dependency-free: the point of entry to a monitoring tool should be
easy to audit and hard to break. Bad rows are collected and reported rather than
silently dropped, because a silently dropped refund is a blind spot.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Tuple

from .models import ACTION_TYPES, Event

REQUIRED_COLUMNS = {
    "event_id",
    "timestamp",
    "employee_id",
    "role",
    "store_id",
    "action_type",
    "amount",
}


class IngestError(ValueError):
    pass


def parse_timestamp(raw: str) -> datetime:
    raw = (raw or "").strip().replace("Z", "+00:00")
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise IngestError(f"unparseable timestamp {raw!r}") from exc
    # Store-local naive time keeps the business-hours logic honest.
    return ts.replace(tzinfo=None)


def _to_float(raw, field: str) -> float:
    if isinstance(raw, (int, float)):
        return float(raw)
    raw = (raw or "").strip()
    if raw == "":
        return 0.0
    try:
        return float(raw)
    except ValueError as exc:
        raise IngestError(f"non-numeric {field}={raw!r}") from exc


def parse_row(row: dict, line_no: int) -> Event:
    action = (row.get("action_type") or "").strip().lower()
    if action not in ACTION_TYPES:
        raise IngestError(f"line {line_no}: unknown action_type {action!r}")
    amount = abs(_to_float(row.get("amount", ""), "amount"))
    return Event(
        event_id=(row.get("event_id") or f"row-{line_no}").strip(),
        timestamp=parse_timestamp(row.get("timestamp", "")),
        employee_id=(row.get("employee_id") or "").strip(),
        employee_name=(row.get("employee_name") or row.get("employee_id") or "").strip(),
        role=(row.get("role") or "unknown").strip(),
        store_id=(row.get("store_id") or "unknown").strip(),
        action_type=action,
        amount=amount,
        order_id=(row.get("order_id") or "").strip(),
        customer_ref=(row.get("customer_ref") or "").strip(),
        payment_method=(row.get("payment_method") or "").strip(),
        original_txn_id=(row.get("original_txn_id") or "").strip(),
        discount_pct=_to_float(row.get("discount_pct", ""), "discount_pct"),
        note=(row.get("note") or "").strip(),
    )


def load_events(path: str | Path, strict: bool = False) -> Tuple[List[Event], List[str]]:
    """Return (events, problems). With strict=True the first problem raises."""
    path = Path(path)
    if not path.exists():
        raise IngestError(f"events file not found: {path}. Run: python -m fim.cli gen-data")

    events: List[Event] = []
    problems: List[str] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise IngestError(f"{path} is missing columns: {sorted(missing)}")
        for line_no, row in enumerate(reader, start=2):
            try:
                event = parse_row(row, line_no)
            except IngestError as exc:
                if strict:
                    raise
                problems.append(str(exc))
                continue
            if not event.employee_id:
                problems.append(f"line {line_no}: missing employee_id")
                continue
            events.append(event)

    events.sort(key=lambda e: e.timestamp)
    return events, problems


def latest_timestamp(events: Iterable[Event]) -> datetime:
    ts = [e.timestamp for e in events]
    if not ts:
        raise IngestError("no events to derive an as-of time from")
    return max(ts)
