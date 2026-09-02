#!/usr/bin/env python
"""Generate a synthetic ledger of staff-initiated financial actions.

Everything produced here is fictional: the names, stores and customer records do
not refer to real people. The point is to have data where we *know* the answer,
so the detector's claims can be checked rather than admired.

Four injected patterns, each with a different shape, so the evaluation has
something to fail at:

  refund_mill      - many small refunds, concentrated on a handful of
                     counterparties, often with no linked original sale.
  discount_abuse   - discounts applied far more often and far deeper than peers,
                     mostly to the same few customer records.
  void_skimmer     - voids sales after hours; the money never reaches the till.
  slow_burn        - a modest lift in refund size only. Deliberately near the
                     threshold: a detector that catches every one of these on a
                     seven-day window is overfitting, and the metrics should say so.

Ground truth is written alongside the CSV and is never read by the detector.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

FIRST = [
    "Amara", "Devin", "Priya", "Tobias", "Ines", "Marco", "Naomi", "Hugo",
    "Leila", "Sam", "Ravi", "Cora", "Jonah", "Mei", "Ollie", "Fatima",
    "Anders", "Yusuf", "Bea", "Kwame", "Nadia", "Theo", "Lucia", "Idris",
]
LAST = [
    "Okonkwo", "Reyes", "Nair", "Lindqvist", "Barros", "Ferrari", "Adeyemi",
    "Novak", "Haddad", "Whitfield", "Menon", "Duarte", "Klein", "Chan",
    "Byrne", "Zahra", "Holm", "Demir", "Ricci", "Mensah", "Farah", "Voss",
]

ROLE_PROFILE = {
    "Cashier": dict(
        sales_per_shift=34, refund_rate=0.045, void_rate=0.012, discount_rate=0.07,
        override_rate=0.004, shift_start=(8, 12), weight=0.5,
    ),
    "Returns Desk": dict(
        sales_per_shift=14, refund_rate=0.30, void_rate=0.02, discount_rate=0.05,
        override_rate=0.02, shift_start=(9, 13), weight=0.17,
    ),
    "Shift Supervisor": dict(
        sales_per_shift=22, refund_rate=0.08, void_rate=0.03, discount_rate=0.10,
        override_rate=0.05, shift_start=(7, 14), weight=0.22,
    ),
    "Store Manager": dict(
        sales_per_shift=12, refund_rate=0.10, void_rate=0.035, discount_rate=0.14,
        override_rate=0.08, shift_start=(8, 11), weight=0.11,
    ),
}

PATTERNS = ("refund_mill", "discount_abuse", "void_skimmer", "slow_burn")


class Ledger:
    def __init__(self) -> None:
        self.rows: List[Dict[str, object]] = []
        self._n = 0

    def add(self, **row) -> str:
        self._n += 1
        event_id = f"evt-{self._n:07d}"
        row["event_id"] = event_id
        self.rows.append(row)
        return event_id


def role_quota(n: int, min_per_role: int = 5) -> List[str]:
    """Staff every role deeply enough to have a real peer group.

    The detector refuses to compare across roles, so a role with two people in it
    simply cannot be peer-scored. A store that thin is a legitimate limitation of
    the method, not something to paper over in the demo data.
    """
    roles = list(ROLE_PROFILE)
    base = min(min_per_role, max(n // len(roles), 1))
    counts = {r: base for r in roles}
    remaining = n - base * len(roles)
    weights = np.array([ROLE_PROFILE[r]["weight"] for r in roles], dtype=float)
    weights /= weights.sum()
    for i, role in enumerate(roles):
        if remaining <= 0:
            break
        extra = int(round(remaining * weights[i]))
        counts[role] += extra
    # Fix any rounding drift against the requested headcount.
    drift = n - sum(counts.values())
    counts[roles[0]] = max(counts[roles[0]] + drift, 1)
    out: List[str] = []
    for role, count in counts.items():
        out.extend([role] * count)
    return out[:n]


def make_employees(rng: np.random.Generator, n: int, stores: List[str]) -> List[Dict]:
    assigned_roles = role_quota(n)

    names = set()
    employees = []
    for i in range(n):
        while True:
            name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            if name not in names:
                names.add(name)
                break
        role = assigned_roles[i]
        employees.append(
            {
                "employee_id": f"EMP-{1001 + i}",
                "employee_name": name,
                "role": role,
                "store_id": stores[i % len(stores)],
                # Honest people differ from each other. Without this spread the
                # peer MAD collapses to zero and everything looks like an outlier.
                "intensity": float(np.exp(rng.normal(0, 0.22))),
                "diligence": float(np.exp(rng.normal(0, 0.30))),
                "work_prob": float(np.clip(rng.normal(0.78, 0.07), 0.55, 0.95)),
                "pattern": None,
                "onset": None,
            }
        )
    return employees


def assign_patterns(
    rng: np.random.Generator, employees: List[Dict], as_of: datetime, n_bad: int
) -> None:
    """Give a few employees a pattern that starts partway through the history."""
    eligible = [e for e in employees if e["role"] in ("Cashier", "Returns Desk",
                                                      "Shift Supervisor")]
    chosen = rng.choice(len(eligible), size=min(n_bad, len(eligible)), replace=False)
    for slot, idx in enumerate(chosen):
        employee = eligible[int(idx)]
        employee["pattern"] = PATTERNS[slot % len(PATTERNS)]
        # Onset inside the scoring window's reach but late enough that the prior
        # windows still describe honest behaviour.
        employee["onset"] = as_of - timedelta(days=int(rng.integers(9, 16)))
        employee["collusion_refs"] = [
            f"CUST-{int(rng.integers(70000, 79999))}" for _ in range(rng.integers(2, 4))
        ]


def default_as_of() -> datetime:
    """End the ledger part-way through a trading day.

    The tracker's whole point is showing who is handling funds *now*, so the
    demo data has to end mid-shift. Ending at midnight would leave every card
    reading "off shift", which is accurate but tells the merchant nothing.
    """
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    if 10 <= now.hour <= 20:
        return now
    anchor = now if now.hour > 20 else now - timedelta(days=1)
    return anchor.replace(hour=17)


def sale_amount(rng: np.random.Generator) -> float:
    return float(np.round(np.exp(rng.normal(3.3, 0.62)), 2))


def generate(
    days: int = 56,
    n_employees: int = 24,
    n_bad: int = 4,
    seed: int = 42,
    as_of: datetime | None = None,
    stores: List[str] | None = None,
) -> tuple[Ledger, List[Dict], Dict]:
    rng = np.random.default_rng(seed)
    stores = stores or ["ST-01", "ST-02"]
    as_of = as_of or default_as_of()

    employees = make_employees(rng, n_employees, stores)
    assign_patterns(rng, employees, as_of, n_bad)

    customer_pool = {s: [f"CUST-{10000 + i}" for i in range(400)] for s in stores}
    ledger = Ledger()
    start = as_of - timedelta(days=days)

    for day_offset in range(days + 1):
        day = (start + timedelta(days=day_offset)).replace(hour=0, minute=0, second=0)
        weekday_factor = 0.85 if day.weekday() >= 5 else 1.0

        for emp in employees:
            if rng.random() > emp["work_prob"]:
                continue  # day off

            profile = ROLE_PROFILE[emp["role"]]
            active = emp["pattern"] is not None and day >= emp["onset"]
            pattern = emp["pattern"] if active else None

            shift_start = int(rng.integers(*profile["shift_start"]))
            shift_hours = 8.0

            def stamp(offset_hours: float | None = None) -> datetime:
                offset = rng.uniform(0, shift_hours) if offset_hours is None else offset_hours
                return day + timedelta(hours=shift_start + offset,
                                       minutes=float(rng.integers(0, 60)))

            n_sales = int(rng.poisson(
                profile["sales_per_shift"] * emp["intensity"] * weekday_factor
            ))
            recent_sales: List[tuple[str, str, float]] = []
            for _ in range(n_sales):
                amount = sale_amount(rng)
                customer = str(rng.choice(customer_pool[emp["store_id"]]))
                event_id = ledger.add(
                    timestamp=stamp().isoformat(timespec="seconds"),
                    employee_id=emp["employee_id"],
                    employee_name=emp["employee_name"],
                    role=emp["role"],
                    store_id=emp["store_id"],
                    action_type="sale",
                    amount=amount,
                    order_id=f"ORD-{rng.integers(100000, 999999)}",
                    customer_ref=customer,
                    payment_method=str(rng.choice(["card", "cash", "wallet"],
                                                  p=[0.68, 0.22, 0.10])),
                    original_txn_id="",
                    discount_pct=0.0,
                    note="",
                )
                recent_sales.append((event_id, customer, amount))

            # ---- refunds -------------------------------------------------
            refund_rate = profile["refund_rate"] * emp["diligence"]
            if pattern == "refund_mill":
                refund_rate *= rng.uniform(4.0, 6.0)
            elif pattern == "slow_burn":
                refund_rate *= rng.uniform(1.15, 1.35)
            n_refunds = int(rng.binomial(max(n_sales, 1), min(refund_rate, 0.95)))

            for _ in range(n_refunds):
                linked = recent_sales[int(rng.integers(0, len(recent_sales)))] if recent_sales else None
                has_original = rng.random() < (0.35 if pattern == "refund_mill" else 0.92)
                if pattern in ("refund_mill",) and rng.random() < 0.75:
                    customer = str(rng.choice(emp["collusion_refs"]))
                elif linked and has_original:
                    customer = linked[1]
                else:
                    customer = str(rng.choice(customer_pool[emp["store_id"]]))

                amount = linked[2] if (linked and has_original) else sale_amount(rng)
                if pattern == "slow_burn":
                    amount = float(np.round(amount * rng.uniform(1.5, 1.9), 2))
                ledger.add(
                    timestamp=stamp().isoformat(timespec="seconds"),
                    employee_id=emp["employee_id"],
                    employee_name=emp["employee_name"],
                    role=emp["role"],
                    store_id=emp["store_id"],
                    action_type="refund",
                    amount=amount,
                    order_id=f"ORD-{rng.integers(100000, 999999)}",
                    customer_ref=customer,
                    payment_method=str(rng.choice(["card", "cash"], p=[0.6, 0.4])),
                    original_txn_id=linked[0] if (linked and has_original) else "",
                    discount_pct=0.0,
                    note="",
                )

            # ---- voids ---------------------------------------------------
            void_rate = profile["void_rate"] * emp["diligence"]
            if pattern == "void_skimmer":
                void_rate *= rng.uniform(4.5, 7.0)
            for _ in range(int(rng.binomial(max(n_sales, 1), min(void_rate, 0.9)))):
                if pattern == "void_skimmer" and rng.random() < 0.6:
                    ts = day + timedelta(hours=float(rng.choice([5.5, 6.0, 22.0, 23.0])),
                                         minutes=float(rng.integers(0, 60)))
                else:
                    ts = stamp()
                ledger.add(
                    timestamp=ts.isoformat(timespec="seconds"),
                    employee_id=emp["employee_id"],
                    employee_name=emp["employee_name"],
                    role=emp["role"],
                    store_id=emp["store_id"],
                    action_type="void",
                    amount=sale_amount(rng),
                    order_id=f"ORD-{rng.integers(100000, 999999)}",
                    customer_ref="",
                    payment_method="cash" if pattern == "void_skimmer" else "card",
                    original_txn_id=(
                        recent_sales[int(rng.integers(0, len(recent_sales)))][0]
                        if recent_sales else ""
                    ),
                    discount_pct=0.0,
                    note="",
                )

            # ---- discounts ----------------------------------------------
            discount_rate = profile["discount_rate"] * emp["diligence"]
            depth_mu, depth_sigma = 11.0, 3.5
            if pattern == "discount_abuse":
                discount_rate *= rng.uniform(3.0, 4.5)
                depth_mu, depth_sigma = 38.0, 9.0
            for _ in range(int(rng.binomial(max(n_sales, 1), min(discount_rate, 0.95)))):
                if pattern == "discount_abuse" and rng.random() < 0.7:
                    customer = str(rng.choice(emp["collusion_refs"]))
                else:
                    customer = str(rng.choice(customer_pool[emp["store_id"]]))
                ledger.add(
                    timestamp=stamp().isoformat(timespec="seconds"),
                    employee_id=emp["employee_id"],
                    employee_name=emp["employee_name"],
                    role=emp["role"],
                    store_id=emp["store_id"],
                    action_type="discount",
                    amount=sale_amount(rng),
                    order_id=f"ORD-{rng.integers(100000, 999999)}",
                    customer_ref=customer,
                    payment_method="card",
                    original_txn_id="",
                    discount_pct=float(np.round(np.clip(
                        rng.normal(depth_mu, depth_sigma), 2, 90), 1)),
                    note="",
                )

            # ---- manual overrides ---------------------------------------
            override_lambda = profile["override_rate"] * max(n_sales, 1) * emp["diligence"]
            if pattern in ("refund_mill", "void_skimmer"):
                override_lambda *= rng.uniform(2.0, 3.2)
            for _ in range(int(rng.poisson(override_lambda))):
                ledger.add(
                    timestamp=stamp().isoformat(timespec="seconds"),
                    employee_id=emp["employee_id"],
                    employee_name=emp["employee_name"],
                    role=emp["role"],
                    store_id=emp["store_id"],
                    action_type="manual_override",
                    amount=sale_amount(rng),
                    order_id=f"ORD-{rng.integers(100000, 999999)}",
                    customer_ref="",
                    payment_method="card",
                    original_txn_id="",
                    discount_pct=0.0,
                    note="price override",
                )

    # Shift stamps land anywhere inside a shift, so the final day can spill past
    # the as-of instant. Drop those: a monitor must never hold events from the
    # future, and the tracker's live status depends on it.
    ledger.rows = [
        r for r in ledger.rows
        if datetime.fromisoformat(str(r["timestamp"])) <= as_of
    ]

    ground_truth = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": as_of.isoformat(timespec="seconds"),
        "seed": seed,
        "days": days,
        "employees": len(employees),
        "labelled": {
            e["employee_id"]: {
                "name": e["employee_name"],
                "role": e["role"],
                "store_id": e["store_id"],
                "pattern": e["pattern"],
                "onset": e["onset"].isoformat(timespec="seconds") if e["onset"] else None,
            }
            for e in employees if e["pattern"]
        },
        "note": "Ground truth is for evaluation only. The detector never reads this file.",
    }
    return ledger, employees, ground_truth


FIELDNAMES = [
    "event_id", "timestamp", "employee_id", "employee_name", "role", "store_id",
    "action_type", "amount", "order_id", "customer_ref", "payment_method",
    "original_txn_id", "discount_pct", "note",
]


def write_csv(ledger: Ledger, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(ledger.rows, key=lambda r: str(r["timestamp"]))
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in FIELDNAMES})


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--days", type=int, default=56)
    parser.add_argument("--employees", type=int, default=24)
    parser.add_argument("--bad-actors", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default=str(ROOT / "data" / "events.csv"))
    parser.add_argument("--truth", default=str(ROOT / "data" / "ground_truth.json"))
    parser.add_argument("--stores", default=None,
                        help="comma-separated store ids, e.g. STORE-A or ST-01,ST-02")
    args = parser.parse_args(argv)

    stores = [s.strip() for s in args.stores.split(",") if s.strip()] if args.stores else None
    ledger, employees, truth = generate(
        days=args.days, n_employees=args.employees,
        n_bad=args.bad_actors, seed=args.seed, stores=stores,
    )
    write_csv(ledger, Path(args.out))
    Path(args.truth).write_text(json.dumps(truth, indent=2), encoding="utf-8")

    print(f"wrote {len(ledger.rows):,} events for {len(employees)} employees -> {args.out}")
    print(f"ground truth ({len(truth['labelled'])} labelled) -> {args.truth}")
    for emp_id, meta in truth["labelled"].items():
        print(f"  {emp_id}  {meta['name']:<20} {meta['pattern']:<15} onset {meta['onset'][:10]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
