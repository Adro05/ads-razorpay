"""Configuration loading with defaults, so the package works without a file."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict

import yaml

DEFAULTS: Dict[str, Any] = {
    "data": {
        "events_csv": "data/events.csv",
        "db_path": "data/fim.db",
        "ground_truth_json": "data/ground_truth.json",
    },
    "window": {
        "window_days": 7,
        "baseline_days": 28,
        "active_minutes": 45,
        "idle_hours": 12,
    },
    "business_hours": {"start_hour": 8, "end_hour": 21},
    "thresholds": {
        "min_events_for_scoring": 15,
        "min_refunds_for_concentration": 4,
        "min_peer_group": 4,
        "allow_cross_role_peers": False,
        "z_cap": 6.0,
        "min_reason_z": 2.0,
        "flag_score": 70,
        "watch_score": 50,
    },
    "scoring": {
        "weights": {"peer": 0.45, "self": 0.30, "isolation_forest": 0.25},
        "top_k_reasons": 3,
        "isolation_forest": {
            "n_estimators": 200,
            "random_state": 7,
            "min_samples": 8,
            "score_scale": 0.15,
        },
    },
    "features": {"enabled": None},  # None => every registered feature
    "review": {"decisions": ["confirmed_issue", "cleared", "needs_more_info", "escalated"]},
    # Named alternative (events_csv, db_path, ground_truth_json) triples the
    # dashboard can switch between at runtime. Empty by default so a bare
    # config still behaves exactly as before; see api.py's /api/datasets.
    "datasets": {},
}


def project_root() -> Path:
    """Repository root (the directory containing config/ and data/)."""
    return Path(__file__).resolve().parents[2]


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class Config:
    """Dict-backed config with dotted lookup and path resolution."""

    def __init__(self, data: Dict[str, Any], root: Path | None = None):
        self.data = data
        self.root = Path(root) if root else project_root()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        root = project_root()
        if path is None:
            path = root / "config" / "config.yaml"
        path = Path(path)
        loaded = {}
        if path.exists():
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(_deep_merge(DEFAULTS, loaded), root)

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def path(self, dotted: str) -> Path:
        """Resolve a configured path relative to the project root."""
        value = self.get(dotted)
        if value is None:
            raise KeyError(f"no path configured at {dotted!r}")
        p = Path(value)
        return p if p.is_absolute() else (self.root / p)
