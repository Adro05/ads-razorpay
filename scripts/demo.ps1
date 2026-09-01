# End-to-end demo: build a labelled synthetic store, scan it, evaluate honestly,
# record one human review, then verify the audit chain.
#
#   powershell -ExecutionPolicy Bypass -File scripts\demo.ps1
#
# Everything runs locally against data\fim.db. No real data is touched.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONPATH = "src"

function Step($text) {
    Write-Host ""
    Write-Host ("=" * 72) -ForegroundColor DarkGray
    Write-Host "  $text" -ForegroundColor Cyan
    Write-Host ("=" * 72) -ForegroundColor DarkGray
}

Step "1/6  Generate a synthetic store with four planted bad actors"
python -m fim.cli gen-data

Step "2/6  Reset the local database so the demo starts from nothing"
Remove-Item -Path "data\fim.db", "data\fim.db-wal", "data\fim.db-shm" -Force -ErrorAction SilentlyContinue
Write-Host "cleared data\fim.db"

Step "3/6  Run a scan (scores every employee, raises flags, writes the audit trail)"
python -m fim.cli scan --actor "demo"

Step "4/6  The activity tracker, as text"
python -m fim.cli report --flagged-only

Step "5/6  Honest metrics over 8 independently generated stores"
python scripts\evaluate.py --trials 8

Step "6/6  Record a human review, then verify the audit chain"
$flagJson = python -m fim.cli flags --state open
$flagJson | Select-Object -First 2
$flagId = ($flagJson | Select-String -Pattern "^flag-\S+").Matches.Value | Select-Object -First 1
if ($flagId) {
    python -m fim.cli review --flag $flagId --reviewer "Demo Reviewer" `
        --decision needs_more_info --notes "Pulled the till tape before deciding."
} else {
    Write-Host "no open flags to review" -ForegroundColor Yellow
}
python -m fim.cli audit --verify

Write-Host ""
Write-Host "Now start the dashboard:  python -m fim.cli serve" -ForegroundColor Green
Write-Host "then open http://127.0.0.1:8000" -ForegroundColor Green
