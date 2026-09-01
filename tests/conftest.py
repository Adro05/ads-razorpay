import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fim.config import Config  # noqa: E402
from fim.models import Event  # noqa: E402

AS_OF = datetime(2026, 6, 30, 17, 0, 0)


def make_event(
    n: int,
    employee_id: str = "EMP-1",
    action: str = "sale",
    amount: float = 40.0,
    when: datetime | None = None,
    customer: str = "",
    original: str = "",
    role: str = "Cashier",
    store: str = "ST-01",
    discount_pct: float = 0.0,
) -> Event:
    return Event(
        event_id=f"evt-{n}",
        timestamp=when or AS_OF - timedelta(hours=1),
        employee_id=employee_id,
        employee_name=f"Person {employee_id}",
        role=role,
        store_id=store,
        action_type=action,
        amount=amount,
        order_id=f"ORD-{n}",
        customer_ref=customer,
        payment_method="card",
        original_txn_id=original,
        discount_pct=discount_pct,
    )


def build_cohort(
    n_employees: int = 8,
    days: int = 35,
    sales_per_day: int = 12,
    refunds_per_day: int = 1,
    bad_employee: str | None = None,
) -> list[Event]:
    """A deterministic cohort: everyone identical apart from a small drift, plus
    an optional employee whose recent week is obviously abnormal."""
    events: list[Event] = []
    counter = 0
    for i in range(n_employees):
        emp = f"EMP-{i + 1}"
        for day in range(days):
            when = AS_OF - timedelta(days=day)
            drift = i % 3  # keeps the peer MAD away from zero
            for s in range(sales_per_day + drift):
                counter += 1
                events.append(make_event(
                    counter, emp, "sale", 40.0 + s,
                    when.replace(hour=10) + timedelta(minutes=s),
                    customer=f"CUST-{(counter % 97) + 1}",
                ))
            recent = day < 7
            n_refunds = refunds_per_day
            if bad_employee == emp and recent:
                n_refunds = refunds_per_day + 9
            for r in range(n_refunds):
                counter += 1
                collusive = bad_employee == emp and recent
                events.append(make_event(
                    counter, emp, "refund", 60.0,
                    when.replace(hour=12) + timedelta(minutes=r),
                    customer="CUST-9001" if collusive else f"CUST-{(counter % 89) + 1}",
                    original="" if collusive else f"evt-{counter - 1}",
                ))
    events.sort(key=lambda e: e.timestamp)
    return events


@pytest.fixture
def config(tmp_path) -> Config:
    cfg = Config.load()
    cfg.data["data"]["db_path"] = str(tmp_path / "test.db")
    cfg.data["data"]["events_csv"] = str(tmp_path / "events.csv")
    return cfg


@pytest.fixture
def as_of() -> datetime:
    return AS_OF
