"""The anomaly scoring engine.

Three views of the same window, deliberately kept separate so a flag can always
be attributed to one of them:

1. **Peer deviation** - robust z-score against comparable colleagues. Catches the
   employee who is out of step with the people doing the same job.
2. **Self deviation** - robust z-score against that employee's own prior windows.
   Catches the employee whose behaviour changed, even if they still look normal
   next to their peers.
3. **Isolation Forest** - an unsupervised model over the whole feature vector.
   Catches odd *combinations* that no single feature makes obvious.

Robust statistics (median / MAD) are used throughout rather than mean and
standard deviation: a single colluding employee inside a small peer group would
otherwise drag the mean towards themselves and hide the very behaviour we are
looking for.

Everything here is deterministic given the same inputs and config, which is what
makes the audit trail worth anything.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .features import ALL_FEATURES, SPECS_BY_NAME
from .models import FeatureVector

MAD_TO_SIGMA = 1.4826  # makes MAD comparable to a standard deviation for normal data
SMALL_SAMPLE_PRIOR = 3.0  # pseudo-observations used to shrink z from thin samples


@dataclass
class Deviation:
    """One feature, one basis, one comparison."""

    feature: str
    basis: str            # "peer" | "self"
    observed: float
    comparison: float     # peer median or the employee's own historical median
    scale: float          # robust sigma used as the denominator
    z: float
    sample_size: int


@dataclass
class ScoreDetail:
    employee_id: str
    risk_score: float
    components: Dict[str, Optional[float]]
    peer_deviations: List[Deviation] = field(default_factory=list)
    self_deviations: List[Deviation] = field(default_factory=list)
    peer_group: str = ""
    peer_group_size: int = 0
    model_outlier_raw: Optional[float] = None
    scored: bool = True
    skip_reason: str = ""


def robust_stats(sample: Sequence[float], floor: float = 0.0) -> Tuple[float, float]:
    """Return (median, robust sigma). Falls back to std when the MAD collapses.

    `floor` is the feature's materiality floor (see FeatureSpec.floor). Sigma is
    never allowed below it, which is what stops a tightly clustered peer group
    from turning a one-point difference into a nine-sigma accusation.
    """
    arr = np.asarray([float(v) for v in sample], dtype=float)
    if arr.size == 0:
        return 0.0, 0.0
    median = float(np.median(arr))
    mad = float(np.median(np.abs(arr - median)))
    sigma = mad * MAD_TO_SIGMA
    if sigma <= 1e-12:
        # More than half the cohort sits on the same value (very common for
        # rates that are usually zero). Standard deviation still carries signal.
        sigma = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
    return median, max(sigma, float(floor))


def robust_z(
    value: float, sample: Sequence[float], floor: float = 0.0
) -> Tuple[float, float, float]:
    """Signed robust z of `value` against `sample`. Returns (z, median, sigma).

    The z is shrunk towards zero for thin samples: four historical windows are
    not enough evidence to justify a six-sigma claim about a person, however
    neatly the arithmetic works out.
    """
    median, sigma = robust_stats(sample, floor)
    if sigma <= 1e-12:
        # No spread and no materiality floor: "how unusual" is unanswerable.
        # Zero is the honest answer; a large constant would be an invented one.
        return 0.0, median, 0.0
    n = len(sample)
    shrink = math.sqrt(n / (n + SMALL_SAMPLE_PRIOR)) if n > 0 else 0.0
    return ((float(value) - median) / sigma) * shrink, median, sigma


def z_to_score(z: float, cap: float) -> float:
    """Map a one-sided z onto 0..100, saturating at `cap` sigmas."""
    if z <= 0 or cap <= 0:
        return 0.0
    return 100.0 * min(1.0, z / cap)


def combine_z(zs: Sequence[float], top_k: int) -> float:
    """Combine the strongest positive deviations into a single z-like number.

    Root-sum-square over the top-k: identical to the maximum when only one
    feature deviates, and rewards breadth when several do at once - which is the
    realistic signature of siphoning, since a refund mill moves several rates.
    """
    positives = sorted((z for z in zs if z > 0), reverse=True)[:max(top_k, 1)]
    if not positives:
        return 0.0
    return math.sqrt(sum(z * z for z in positives))


def resolve_peer_group(
    target: FeatureVector,
    cohort: Sequence[FeatureVector],
    min_peer_group: int,
    allow_cross_role: bool = False,
) -> Tuple[str, List[FeatureVector]]:
    """Widen the comparison group until it is big enough to mean anything.

    Widening stops at the role boundary by default. A returns desk clerk refunds
    an order of magnitude more often than a cashier because that is the job;
    comparing the two produces a confident, well-explained, entirely wrong
    accusation. Where no valid peer group exists the peer component is dropped
    and the employee's own history plus the model carry the score.
    """
    others = [v for v in cohort if v.employee_id != target.employee_id]

    same_role_store = [
        v for v in others if v.role == target.role and v.store_id == target.store_id
    ]
    if len(same_role_store) >= min_peer_group:
        return f"{target.role} at {target.store_id}", same_role_store

    same_role = [v for v in others if v.role == target.role]
    if len(same_role) >= min_peer_group:
        return f"{target.role} across all stores", same_role

    if allow_cross_role and len(others) >= min_peer_group:
        return "all monitored staff (no role peer group available)", others

    return "no comparable peer group", []


def _feature_matrix(
    vectors: Sequence[FeatureVector], features: Sequence[str]
) -> np.ndarray:
    return np.asarray(
        [[float(v.values.get(f, 0.0)) for f in features] for v in vectors], dtype=float
    )


def _robust_scale_matrix(matrix: np.ndarray, floors: Sequence[float]) -> np.ndarray:
    """Column-wise robust standardisation, clipped to keep the model stable."""
    if matrix.size == 0:
        return matrix
    scaled = np.zeros_like(matrix)
    for j in range(matrix.shape[1]):
        median, sigma = robust_stats(matrix[:, j], floors[j])
        if sigma <= 1e-12:
            continue  # constant column carries no information; leave it at zero
        scaled[:, j] = np.clip((matrix[:, j] - median) / sigma, -10.0, 10.0)
    return scaled


def isolation_forest_scores(
    vectors: Sequence[FeatureVector],
    features: Sequence[str],
    n_estimators: int = 200,
    random_state: int = 7,
    min_samples: int = 8,
    score_scale: float = 0.15,
) -> Dict[str, Tuple[float, float]]:
    """Return {employee_id: (component_0_100, raw_outlier_margin)}.

    The raw margin is `-decision_function`: at or above zero the model itself
    considers the point an outlier. Negative margins map to a component of 0, so
    a genuinely well-behaved cohort contributes nothing here rather than being
    forced to nominate a "most anomalous" member.
    """
    if len(vectors) < min_samples:
        return {}
    try:
        from sklearn.ensemble import IsolationForest
    except ImportError:  # scikit-learn is optional at runtime
        return {}

    floors = [SPECS_BY_NAME[f].floor if f in SPECS_BY_NAME else 0.0 for f in features]
    matrix = _robust_scale_matrix(_feature_matrix(vectors, features), floors)
    model = IsolationForest(
        n_estimators=n_estimators,
        contamination="auto",
        random_state=random_state,
        bootstrap=False,
    )
    model.fit(matrix)
    margins = -model.decision_function(matrix)

    out: Dict[str, Tuple[float, float]] = {}
    for vector, margin in zip(vectors, margins):
        margin = float(margin)
        component = 100.0 * min(1.0, max(0.0, margin) / max(score_scale, 1e-9))
        out[vector.employee_id] = (component, margin)
    return out


def score_cohort(
    current: Dict[str, FeatureVector],
    baselines: Dict[str, List[Dict[str, float]]],
    config,
) -> Dict[str, ScoreDetail]:
    """Score every employee in the cohort for the current window."""
    features: List[str] = list(config.get("features.enabled") or ALL_FEATURES)
    features = [f for f in features if f in ALL_FEATURES]

    z_cap = float(config.get("thresholds.z_cap", 5.0))
    min_peer_group = int(config.get("thresholds.min_peer_group", 4))
    allow_cross_role = bool(config.get("thresholds.allow_cross_role_peers", False))
    floors = {f: (SPECS_BY_NAME[f].floor if f in SPECS_BY_NAME else 0.0) for f in features}
    top_k = int(config.get("scoring.top_k_reasons", 3))
    weights = dict(config.get("scoring.weights") or {})
    if_cfg = dict(config.get("scoring.isolation_forest") or {})

    scoreable = [v for v in current.values() if v.data_sufficient]
    scoreable.sort(key=lambda v: v.employee_id)

    if_scores = isolation_forest_scores(
        scoreable,
        features,
        n_estimators=int(if_cfg.get("n_estimators", 200)),
        random_state=int(if_cfg.get("random_state", 7)),
        min_samples=int(if_cfg.get("min_samples", 8)),
        score_scale=float(if_cfg.get("score_scale", 0.15)),
    )

    details: Dict[str, ScoreDetail] = {}

    for vector in current.values():
        if not vector.data_sufficient:
            details[vector.employee_id] = ScoreDetail(
                employee_id=vector.employee_id,
                risk_score=0.0,
                components={"peer": None, "self": None, "isolation_forest": None},
                scored=False,
                skip_reason=(
                    f"only {vector.event_count} actions in the window; below the "
                    f"{config.get('thresholds.min_events_for_scoring', 15)} needed to score"
                ),
            )
            continue

        group_label, peers = resolve_peer_group(
            vector, scoreable, min_peer_group, allow_cross_role
        )

        peer_devs: List[Deviation] = []
        for feature in features:
            if not peers:
                break
            sample = [float(p.values.get(feature, 0.0)) for p in peers]
            z, median, sigma = robust_z(
                float(vector.values.get(feature, 0.0)), sample, floors[feature]
            )
            peer_devs.append(
                Deviation(feature, "peer", float(vector.values.get(feature, 0.0)),
                          median, sigma, z, len(sample))
            )

        history = baselines.get(vector.employee_id, [])
        self_devs: List[Deviation] = []
        if len(history) >= 2:
            for feature in features:
                sample = [float(h.get(feature, 0.0)) for h in history]
                z, median, sigma = robust_z(
                    float(vector.values.get(feature, 0.0)), sample, floors[feature]
                )
                self_devs.append(
                    Deviation(feature, "self", float(vector.values.get(feature, 0.0)),
                              median, sigma, z, len(sample))
                )

        peer_component = (
            z_to_score(combine_z([d.z for d in peer_devs], top_k), z_cap)
            if peer_devs else None
        )
        self_component = (
            z_to_score(combine_z([d.z for d in self_devs], top_k), z_cap)
            if self_devs else None
        )
        if_component, if_raw = if_scores.get(vector.employee_id, (None, None))

        components: Dict[str, Optional[float]] = {
            "peer": None if peer_component is None else round(peer_component, 2),
            "self": None if self_component is None else round(self_component, 2),
            "isolation_forest": None if if_component is None else round(if_component, 2),
        }

        # Weights are renormalised over whichever components exist, so a new
        # employee with no history is not quietly scored out of 70 instead of 100.
        available = {k: v for k, v in components.items() if v is not None}
        total_weight = sum(float(weights.get(k, 0.0)) for k in available) or 0.0
        if total_weight > 0:
            risk = sum(float(weights.get(k, 0.0)) * v for k, v in available.items())
            risk /= total_weight
        else:
            risk = 0.0

        details[vector.employee_id] = ScoreDetail(
            employee_id=vector.employee_id,
            risk_score=float(round(risk, 2)),
            components=components,
            peer_deviations=peer_devs,
            self_deviations=self_devs,
            peer_group=group_label,
            peer_group_size=len(peers),
            model_outlier_raw=None if if_raw is None else float(round(if_raw, 4)),
            scored=True,
        )

    return details


def status_for(score: float, flag_at: float, watch_at: float) -> str:
    if score >= flag_at:
        return "flagged"
    if score >= watch_at:
        return "watch"
    return "clear"
