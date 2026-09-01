"""Command line interface.

    python -m fim.cli scan
    python -m fim.cli report
    python -m fim.cli review --flag flag-abc --reviewer "R. Mensah" --decision cleared
    python -m fim.cli audit --verify
    python -m fim.cli serve
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .audit import AuditTrail
from .config import Config
from .db import init_db
from .engine import (
    assessments_for_scan,
    flags_with_reviews,
    latest_scan,
    record_review,
    run_scan,
)

STATUS_MARK = {
    "flagged": "[FLAG]",
    "watch": "[WATCH]",
    "clear": "[ok]",
    "insufficient_data": "[n/a]",
}


def _config(args) -> Config:
    return Config.load(args.config)


def cmd_gen_data(args) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import generate_synthetic_data as gen  # noqa: E402

    return gen.main(
        ["--days", str(args.days), "--employees", str(args.employees),
         "--seed", str(args.seed)]
    )


def cmd_scan(args) -> int:
    config = _config(args)
    as_of = datetime.fromisoformat(args.as_of) if args.as_of else None
    summary = run_scan(config, as_of=as_of, actor=args.actor)
    print(json.dumps(summary, indent=2))
    if summary["ingest_problems"]:
        print(f"\n{len(summary['ingest_problems'])} rows rejected at ingest (showing up to 20):")
        for problem in summary["ingest_problems"]:
            print(f"  - {problem}")
    return 0


def cmd_report(args) -> int:
    config = _config(args)
    conn = init_db(config.path("data.db_path"))
    scan = latest_scan(conn)
    if not scan:
        print("no scans yet - run: python -m fim.cli scan")
        return 1

    rows = assessments_for_scan(conn, scan["scan_id"])
    print(f"scan {scan['scan_id']}  as of {scan['as_of']}  "
          f"({scan['events_ingested']:,} events, {scan['flags_raised']} flags)")
    print("-" * 92)
    print(f"{'':7} {'score':>6}  {'employee':<20} {'role':<17} {'store':<7} "
          f"{'actions':>7}  presence")
    print("-" * 92)
    for row in rows:
        if args.flagged_only and row["status"] not in ("flagged", "watch"):
            continue
        print(f"{STATUS_MARK.get(row['status'], ''):7} {row['risk_score']:>6.1f}  "
              f"{row['employee_name']:<20} {row['role']:<17} {row['store_id']:<7} "
              f"{row['event_count']:>7}  {row['presence']}")
        if row["status"] in ("flagged", "watch") or args.verbose:
            print(f"        {row['summary']}")
            for reason in row["reasons"]:
                print(f"          - {reason['detail']} "
                      f"[{reason['basis']}, {reason['contribution']:.0%} of score]")
    conn.close()
    return 0


def cmd_flags(args) -> int:
    config = _config(args)
    conn = init_db(config.path("data.db_path"))
    for flag in flags_with_reviews(conn, state=args.state, limit=args.limit):
        reviewed = flag["reviews"][-1]["decision"] if flag["reviews"] else "-"
        print(f"{flag['flag_id']}  {flag['created_at']}  {flag['employee_name']:<20} "
              f"score {flag['risk_score']:>5.1f}  state={flag['state']:<8} last={reviewed}")
        print(f"    {flag['summary']}")
    conn.close()
    return 0


def cmd_review(args) -> int:
    config = _config(args)
    conn = init_db(config.path("data.db_path"))
    try:
        review = record_review(
            conn, args.flag, args.reviewer, args.decision, args.notes or "",
            config.get("review.decisions", []),
        )
    except (KeyError, ValueError) as exc:
        print(f"error: {exc}")
        return 2
    print(json.dumps(review, indent=2))
    conn.close()
    return 0


def cmd_audit(args) -> int:
    config = _config(args)
    conn = init_db(config.path("data.db_path"))
    trail = AuditTrail(conn)
    if args.verify:
        report = trail.verify()
        print(json.dumps(report, indent=2))
        conn.close()
        return 0 if report["ok"] else 3
    for entry in reversed(trail.entries(limit=args.limit)):
        print(f"#{entry['seq']:<5} {entry['ts']}  {entry['actor']:<18} "
              f"{entry['action']:<16} {entry['entity_id']}")
        if args.payload:
            print(f"       {json.dumps(entry['payload'])}")
    conn.close()
    return 0


def cmd_evaluate(args) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import evaluate as ev  # noqa: E402

    return ev.main(["--config", args.config] if args.config else [])


def cmd_serve(args) -> int:
    import uvicorn

    uvicorn.run("fim.api:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fim", description=__doc__)
    parser.add_argument("--config", default=None, help="path to config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("gen-data", help="write a synthetic labelled dataset")
    p.add_argument("--days", type=int, default=56)
    p.add_argument("--employees", type=int, default=24)
    p.add_argument("--seed", type=int, default=42)
    p.set_defaults(func=cmd_gen_data)

    p = sub.add_parser("scan", help="score every employee and persist the results")
    p.add_argument("--as-of", default=None, help="ISO timestamp; defaults to newest event")
    p.add_argument("--actor", default="cli", help="who ran the scan (recorded in the audit log)")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("report", help="print the latest scan")
    p.add_argument("--flagged-only", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("flags", help="list raised flags")
    p.add_argument("--state", default=None, choices=["open", "reviewed"])
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_flags)

    p = sub.add_parser("review", help="record a human decision on a flag")
    p.add_argument("--flag", required=True)
    p.add_argument("--reviewer", required=True)
    p.add_argument("--decision", required=True)
    p.add_argument("--notes", default="")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("audit", help="read or verify the audit trail")
    p.add_argument("--verify", action="store_true")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--payload", action="store_true")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("evaluate", help="honest metrics against the synthetic ground truth")
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("serve", help="run the dashboard + API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    p.set_defaults(func=cmd_serve)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
