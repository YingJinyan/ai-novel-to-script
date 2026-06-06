$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root ".demo-pids.json"

if (-not (Test-Path $pidFile)) {
    Write-Host "Demo is not running."
    exit 0
}

$pids = Get-Content $pidFile -Raw | ConvertFrom-Json
foreach ($processId in @($pids.backend, $pids.frontend)) {
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process -and $process.ProcessName -in @("py", "python", "python3", "node")) {
        Stop-Process -Id $processId -Force
    }
}
Remove-Item -LiteralPath $pidFile -Force
Write-Host "Demo services stopped." -ForegroundColor Green
