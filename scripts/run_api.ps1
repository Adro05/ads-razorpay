# Start the dashboard + API on http://127.0.0.1:8000
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$env:PYTHONPATH = "src"
python -m fim.cli serve --host 127.0.0.1 --port 8000
