#!/usr/bin/env bash
# End-to-end demo: build a labelled synthetic store, scan it, evaluate honestly,
# record one human review, then verify the audit chain.
#
#   bash scripts/demo.sh
#
# Everything runs locally against data/fim.db. No real data is touched.

set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=src

step() {
  echo
  printf '=%.0s' {1..72}; echo
  echo "  $1"
  printf '=%.0s' {1..72}; echo
}

step "1/6  Generate a synthetic store with four planted bad actors"
python -m fim.cli gen-data

step "2/6  Reset the local database so the demo starts from nothing"
rm -f data/fim.db data/fim.db-wal data/fim.db-shm
echo "cleared data/fim.db"

step "3/6  Run a scan (scores every employee, raises flags, writes the audit trail)"
python -m fim.cli scan --actor demo

step "4/6  The activity tracker, as text"
python -m fim.cli report --flagged-only

step "5/6  Honest metrics over 8 independently generated stores"
python scripts/evaluate.py --trials 8

step "6/6  Record a human review, then verify the audit chain"
FLAG_ID="$(python -m fim.cli flags --state open | grep -o '^flag-[a-z0-9]*' | head -1 || true)"
if [ -n "${FLAG_ID}" ]; then
  python -m fim.cli review --flag "${FLAG_ID}" --reviewer "Demo Reviewer" \
    --decision needs_more_info --notes "Pulled the till tape before deciding."
else
  echo "no open flags to review"
fi
python -m fim.cli audit --verify

echo
echo "Now start the dashboard:  python -m fim.cli serve"
echo "then open http://127.0.0.1:8000"
