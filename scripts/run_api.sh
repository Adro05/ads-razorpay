#!/usr/bin/env bash
# Start the dashboard + API on http://127.0.0.1:8000
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH=src
python -m fim.cli serve --host 127.0.0.1 --port 8000
