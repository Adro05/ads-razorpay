#!/usr/bin/env python
"""Honest metrics for the anomaly engine.

Reports what the detector actually does on data where the answer is known, at
the thresholds that are actually configured - not at whichever threshold makes
the numbers look best.

Three things are measured:

1. **Alert quality at the configured thresholds.** Precision and recall for
   "flagged", and again for "flagged or watch". Absolute counts are printed
   alongside, because a precision of 1.00 over three alerts is a much weaker
   claim than a precision of 1.00 over three hundred.
2. **Ranking quality.** Average precision over the full risk ranking, which does
   not depend on where the thresholds sit.
3. **A fixed-rule baseline.** The naive "refund rate above 15%" rule the tool
   claims to improve on. If the statistical engine cannot beat it, that belongs
   in the open, and staff can game a published fixed rule in a week anyway.

Use `--trials N` to repeat over N independently generated stores. One synthetic
store with four planted actors is far too small a sample to conclude anything;
the spread across trials is the number worth quoting.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from fim.config import Config           # noqa: E402
from fim.engine import assess           # noqa: E402
from fim.ingest import load_events, parse_row  # noqa: E402
from fim.models import Event            # noqa: E402

import generate_synthetic_data as gen   # noqa: E402

NAIVE_REFUND_RATE_RULE = 0.15


def prf(tp: int, fp: int, fn: int) -> Dict[str, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": round(precision, 3), "recall": round(recall, 3),
            "f1": round(f1, 3), "tp": tp, "fp": fp, "fn": fn}


def average_precision(ranked_labels: Sequence[int]) -> float:
    """AP over a ranking already sorted from most to least suspicious."""
    positives = sum(ranked_labels)
    if positives == 0:
        return 0.0
    hits, total = 0, 0.0
    for i, label in enumerate(ranked_labels, start=1):
        if label:
            hits += 1
            total += hits / i
    return round(total / positives, 3)


def evaluate_once(events: Sequence[Event], truth: Dict, config: Config) -> Dict[str, Any]:
    labelled = set(truth["labelled"])
    assessments, as_of = assess(events, config)

    ranked = [1 if a.employee_id in labelled else 0 for a in assessments]
    flagged = {a.employee_id for a in assessments if a.status == "flagged"}
    alerted = {a.employee_id for a in assessments if a.status in ("flagged", "watch")}
    scored = {a.employee_id for a in assessments if a.status != "insufficient_data"}
    population = {a.employee_id for a in assessments}

    def score_set(predicted: set) -> Dict[str, float]:
        tp = len(predicted & labelled)
        fp = len(predicted - labelled)
        fn = len((labelled & population) - predicted)
        return prf(tp, fp, fn)

    # Naive fixed rule, evaluated on exactly the same window and population.
    naive = {
        a.employee_id for a in assessments
        if a.status != "insufficient_data"
        and float(a.features.get("refund_rate", 0.0)) > NAIVE_REFUND_RATE_RULE
    }

    per_pattern = {}
    order = {a.employee_id: i + 1 for i, a in enumerate(assessments)}
    for emp_id, meta in truth["labelled"].items():
        a = next((x for x in assessments if x.employee_id == emp_id), None)
        per_pattern[meta["pattern"]] = {
            "employee_id": emp_id,
            "risk_score": round(a.risk_score, 1) if a else None,
            "status": a.status if a else "absent",
            "rank": order.get(emp_id),
            "of": len(assessments),
            "caught": bool(a and a.status == "flagged"),
        }

    return {
        "as_of": as_of.isoformat(),
        "employees": len(assessments),
        "scored": len(scored),
        "planted": len(labelled),
        "flagged": score_set(flagged),
        "flagged_or_watch": score_set(alerted),
        "naive_refund_rule": score_set(naive),
        "average_precision": average_precision(ranked),
        "per_pattern": per_pattern,
    }


def run_trials(config: Config, trials: int, base_seed: int, days: int,
               employees: int, bad: int) -> List[Dict[str, Any]]:
    results = []
    for i in range(trials):
        ledger, _, truth = gen.generate(
            days=days, n_employees=employees, n_bad=bad, seed=base_seed + i
        )
        events = [parse_row(row, n) for n, row in enumerate(ledger.rows, start=2)]
        events.sort(key=lambda e: e.timestamp)
        results.append(evaluate_once(events, truth, config))
    return results


def _spread(values: Sequence[float]) -> str:
    if not values:
        return "n/a"
    if len(values) == 1:
        return f"{values[0]:.2f}"
    return (f"{statistics.mean(values):.2f} "
            f"(sd {statistics.pstdev(values):.2f}, min {min(values):.2f}, max {max(values):.2f})")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--config", default=None)
    parser.add_argument("--trials", type=int, default=1,
                        help="independently generated stores; 1 uses the data on disk")
    parser.add_argument("--seed", type=int, default=1000, help="base seed for --trials")
    parser.add_argument("--days", type=int, default=56)
    parser.add_argument("--employees", type=int, default=24)
    parser.add_argument("--bad-actors", type=int, default=4)
    parser.add_argument("--out", default=str(ROOT / "data" / "evaluation.json"))
    args = parser.parse_args(argv)

    config = Config.load(args.config)

    if args.trials <= 1:
        truth_path = config.path("data.ground_truth_json")
        if not truth_path.exists():
            print(f"no ground truth at {truth_path}; run gen-data first")
            return 1
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        events, problems = load_events(config.path("data.events_csv"))
        if problems:
            print(f"note: {len(problems)} rows rejected at ingest")
        results = [evaluate_once(events, truth, config)]
        header = "single store, the dataset currently on disk"
    else:
        results = run_trials(config, args.trials, args.seed, args.days,
                             args.employees, args.bad_actors)
        header = f"{args.trials} independently generated stores"

    flag_p = [r["flagged"]["precision"] for r in results]
    flag_r = [r["flagged"]["recall"] for r in results]
    alert_p = [r["flagged_or_watch"]["precision"] for r in results]
    alert_r = [r["flagged_or_watch"]["recall"] for r in results]
    naive_p = [r["naive_refund_rule"]["precision"] for r in results]
    naive_r = [r["naive_refund_rule"]["recall"] for r in results]
    ap = [r["average_precision"] for r in results]

    print(f"\nEvaluation - {header}")
    print(f"config: flag>={config.get('thresholds.flag_score')}  "
          f"watch>={config.get('thresholds.watch_score')}  "
          f"window={config.get('window.window_days')}d  "
          f"baseline={config.get('window.baseline_days')}d")
    print("=" * 84)
    print(f"{'metric':<34}{'precision':<38}{'recall'}")
    print("-" * 84)
    print(f"{'flagged':<34}{_spread(flag_p):<38}{_spread(flag_r)}")
    print(f"{'flagged or watch':<34}{_spread(alert_p):<38}{_spread(alert_r)}")
    print(f"{'naive rule: refund rate > 15%':<34}{_spread(naive_p):<38}{_spread(naive_r)}")
    print("-" * 84)
    print(f"average precision over the ranking: {_spread(ap)}")

    total_tp = sum(r["flagged"]["tp"] for r in results)
    total_fp = sum(r["flagged"]["fp"] for r in results)
    total_fn = sum(r["flagged"]["fn"] for r in results)
    planted = sum(r["planted"] for r in results)
    print(f"totals across trials: {total_tp} caught, {total_fp} false alarms, "
          f"{total_fn} missed, out of {planted} planted actors")

    print("\nBy planted pattern (last trial):")
    for pattern, meta in results[-1]["per_pattern"].items():
        mark = "caught" if meta["caught"] else f"MISSED ({meta['status']})"
        print(f"  {pattern:<16} score {str(meta['risk_score']):>6}  "
              f"rank {meta['rank']}/{meta['of']}  {mark}")

    print("\nRead this with the caveats:")
    print("  - Synthetic data. The planted patterns are the ones this engine was")
    print("    designed around, so these numbers are an upper bound, not a forecast.")
    print(f"  - {planted} planted actors across {len(results)} trial(s) is a small sample;")
    print("    a single caught or missed actor moves recall by a large fraction.")
    print("  - Thresholds were chosen by hand and were not tuned on held-out data.")
    print("  - 'slow_burn' is deliberately near the detection limit. Catching it")
    print("    every time would suggest the thresholds are too loose, not that the")
    print("    model is good.")
    print("  - No real employee was scored to produce any of this.")

    payload = {
        "header": header,
        "thresholds": {
            "flag_score": config.get("thresholds.flag_score"),
            "watch_score": config.get("thresholds.watch_score"),
            "window_days": config.get("window.window_days"),
            "baseline_days": config.get("window.baseline_days"),
        },
        "trials": results,
        "summary": {
            "flagged_precision": flag_p,
            "flagged_recall": flag_r,
            "alert_precision": alert_p,
            "alert_recall": alert_r,
            "naive_precision": naive_p,
            "naive_recall": naive_r,
            "average_precision": ap,
            "caught": total_tp,
            "false_alarms": total_fp,
            "missed": total_fn,
            "planted": planted,
        },
    }
    Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
