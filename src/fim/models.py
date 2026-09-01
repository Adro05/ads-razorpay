"""Core data structures shared by the pipeline, storage and API layers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# Actions a member of staff can take that move or reduce money. "sale" is not a
# risk action but is kept because it is the denominator for most rates.
ACTION_TYPES = ("sale", "refund", "discount", "void", "manual_override")
RISK_ACTIONS = ("refund", "discount", "void", "manual_override")


@dataclass(frozen=True)
class Event:
    """One staff-initiated financial action."""

    event_id: str
    timestamp: datetime
    employee_id: str
    employee_name: str
    role: str
    store_id: str
    action_type: str
    amount: float
    order_id: str = ""
    customer_ref: str = ""          # who the money went to / the counterparty
    payment_method: str = ""
    original_txn_id: str = ""       # empty on a refund => no linked original sale
    discount_pct: float = 0.0
    note: str = ""

    @property
    def is_off_hours_key(self) -> int:
        return self.timestamp.hour


@dataclass
class FeatureVector:
    """A window of behaviour for one employee, reduced to comparable numbers."""

    employee_id: str
    employee_name: str
    role: str
    store_id: str
    window_start: datetime
    window_end: datetime
    values: Dict[str, float] = field(default_factory=dict)
    counts: Dict[str, float] = field(default_factory=dict)   # raw supporting numbers
    event_count: int = 0
    last_event_at: Optional[datetime] = None
    data_sufficient: bool = True

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["window_start"] = self.window_start.isoformat()
        d["window_end"] = self.window_end.isoformat()
        d["last_event_at"] = self.last_event_at.isoformat() if self.last_event_at else None
        return d


@dataclass
class Reason:
    """One human-readable justification for a score. Never a bare number."""

    code: str
    feature: str
    headline: str
    detail: str
    observed: float
    comparison: float
    z: float
    contribution: float          # 0..1 share of the composite score
    basis: str                   # "peer" | "self" | "model"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EmployeeAssessment:
    """The scored result for one employee in one scan."""

    employee_id: str
    employee_name: str
    role: str
    store_id: str
    window_start: datetime
    window_end: datetime
    risk_score: float
    status: str                  # flagged | watch | clear | insufficient_data
    presence: str                # active | idle
    components: Dict[str, Optional[float]]
    peer_group: str
    peer_group_size: int
    summary: str = ""
    reasons: List[Reason] = field(default_factory=list)
    features: Dict[str, float] = field(default_factory=dict)
    counts: Dict[str, float] = field(default_factory=dict)
    event_count: int = 0
    last_event_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "employee_id": self.employee_id,
            "employee_name": self.employee_name,
            "role": self.role,
            "store_id": self.store_id,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "risk_score": round(self.risk_score, 2),
            "status": self.status,
            "presence": self.presence,
            "summary": self.summary,
            "components": self.components,
            "peer_group": self.peer_group,
            "peer_group_size": self.peer_group_size,
            "reasons": [r.to_dict() for r in self.reasons],
            "features": self.features,
            "counts": self.counts,
            "event_count": self.event_count,
            "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
        }
