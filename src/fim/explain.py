"""The explainability layer.

A red dot next to a person's name is an accusation. This module exists so that
no flag ever leaves the system without a sentence a merchant could read aloud to
the employee, and a number that person could challenge.

Rules enforced here:
  * every reason names the feature, the observed value, what it was compared
    with, and over what window;
  * every reason states its basis - peers, the employee's own history, or the
    model - because "unusual for you" and "unusual for your role" are different
    claims with different remedies;
  * contributions sum to the composite score, so a merchant can see that a flag
    rests on three things and not on one twitchy metric.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Sequence

from .features import SPECS_BY_NAME
from .models import FeatureVector, Reason
from .scoring import Deviation, ScoreDetail

DEFAULT_MIN_REPORTABLE_Z = 1.5


class _SafeDict(defaultdict):
    def __missing__(self, key):  # noqa: D105 - templates tolerate absent counts
        return 0.0


def _basis_label(deviation: Deviation, peer_group: str, baseline_windows: int) -> str:
    if deviation.basis == "peer":
        return f"peers ({peer_group})"
    return f"their own baseline ({baseline_windows} prior windows)"


def _sigma_phrase(z: float) -> str:
    return f"{z:.1f} standard deviations above"


def _render(
    deviation: Deviation,
    vector: FeatureVector,
    peer_group: str,
    baseline_windows: int,
) -> tuple[str, str]:
    spec = SPECS_BY_NAME.get(deviation.feature)
    label = spec.label if spec else deviation.feature
    basis_label = _basis_label(deviation, peer_group, baseline_windows)
    headline = f"{label} {_sigma_phrase(deviation.z)} {basis_label}"

    fmt = _SafeDict(float, {k: float(v) for k, v in vector.counts.items()})
    fmt["observed"] = deviation.observed
    fmt["comparison"] = deviation.comparison
    fmt["basis_label"] = basis_label
    fmt["z"] = deviation.z
    body = spec.template.format_map(fmt) if spec else (
        f"observed {deviation.observed:.3f} versus {deviation.comparison:.3f}"
    )
    days = max((vector.window_end - vector.window_start).days, 1)
    detail = f"Over the last {days} days this employee {body}."
    return headline, detail


def _model_reason(
    detail: ScoreDetail,
    vector: FeatureVector,
    contribution: float,
) -> Optional[Reason]:
    """Explain the Isolation Forest in terms of what it actually reacted to."""
    if not detail.peer_deviations:
        return None
    ranked = sorted(detail.peer_deviations, key=lambda d: d.z, reverse=True)[:2]
    named = ", ".join(
        (SPECS_BY_NAME[d.feature].label if d.feature in SPECS_BY_NAME else d.feature).lower()
        for d in ranked if d.z > 0
    )
    if not named:
        named = "several rates at once"
    return Reason(
        code="model_outlier",
        feature="isolation_forest",
        headline="Unusual combination of behaviours for this cohort",
        detail=(
            "An unsupervised outlier model looking at all features together placed "
            f"this employee outside the cohort (outlier margin {detail.model_outlier_raw:+.3f}). "
            f"The features pulling hardest were {named}. This component is a "
            "cross-check on the per-feature statistics, not independent evidence."
        ),
        observed=float(detail.model_outlier_raw or 0.0),
        comparison=0.0,
        z=0.0,
        contribution=round(contribution, 4),
        basis="model",
    )


def build_reasons(
    detail: ScoreDetail,
    vector: FeatureVector,
    config,
    max_reasons: int = 5,
) -> List[Reason]:
    """Turn a ScoreDetail into ranked, human-readable reasons."""
    if not detail.scored or detail.risk_score <= 0:
        return []

    min_z = float(config.get("thresholds.min_reason_z", DEFAULT_MIN_REPORTABLE_Z))
    top_k = int(config.get("scoring.top_k_reasons", 3))
    weights = dict(config.get("scoring.weights") or {})

    # Share of the composite held by each component, after renormalisation.
    available = {k: v for k, v in detail.components.items() if v is not None}
    total_weight = sum(float(weights.get(k, 0.0)) for k in available) or 1.0
    component_share: Dict[str, float] = {}
    for name, value in available.items():
        weighted = float(weights.get(name, 0.0)) * float(value) / total_weight
        component_share[name] = weighted / detail.risk_score if detail.risk_score else 0.0

    baseline_windows = (
        detail.self_deviations[0].sample_size if detail.self_deviations else 0
    )

    reasons: List[Reason] = []
    for basis, deviations in (
        ("peer", detail.peer_deviations),
        ("self", detail.self_deviations),
    ):
        share = component_share.get(basis, 0.0)
        top = sorted((d for d in deviations if d.z > 0), key=lambda d: d.z, reverse=True)[:top_k]
        weight_total = sum(d.z * d.z for d in top) or 1.0
        for deviation in top:
            if deviation.z < min_z:
                continue
            spec = SPECS_BY_NAME.get(deviation.feature)
            if spec and abs(deviation.observed - deviation.comparison) < spec.floor:
                # Statistically unusual but operationally trivial. Saying it out
                # loud would put a number on a person for no practical reason.
                continue
            contribution = share * (deviation.z * deviation.z) / weight_total
            headline, text = _render(deviation, vector, detail.peer_group, baseline_windows)
            reasons.append(
                Reason(
                    code=f"{basis}_{deviation.feature}",
                    feature=deviation.feature,
                    headline=headline,
                    detail=text,
                    observed=round(deviation.observed, 6),
                    comparison=round(deviation.comparison, 6),
                    z=round(deviation.z, 2),
                    contribution=round(contribution, 4),
                    basis=basis,
                )
            )

    model_share = component_share.get("isolation_forest", 0.0)
    if model_share > 0.01 and (detail.components.get("isolation_forest") or 0) > 0:
        model = _model_reason(detail, vector, model_share)
        if model:
            reasons.append(model)

    reasons.sort(key=lambda r: r.contribution, reverse=True)
    return reasons[:max_reasons]


def summarise(reasons: Sequence[Reason], status: str, score: float) -> str:
    """One line for the dashboard card and the audit log."""
    if status == "insufficient_data":
        return "Not scored: too little activity in this window to compare fairly."
    if not reasons:
        return f"No material deviation detected (risk score {score:.0f}/100)."
    # The model component is a cross-check, not evidence, so it never leads a
    # summary while a per-feature statistic is available to lead it instead.
    lead = next((r for r in reasons if r.basis != "model"), reasons[0])
    if status == "clear":
        # Below the watch line. Show the largest deviation for transparency, but
        # frame it as what it is: normal variation, not a finding.
        return f"Within normal range ({score:.0f}/100). Largest deviation: {lead.headline}."
    if len(reasons) == 1:
        return f"{lead.headline}."
    return f"{lead.headline}, plus {len(reasons) - 1} further deviation(s)."
