$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )
    Write-Host "`n== $Label ==" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    Invoke-Checked "Secret check" { py -3.10 scripts/check_no_secrets.py }
    Invoke-Checked "Python tests" { py -3.10 -m pytest -q }
    Invoke-Checked "Python compile check" { py -3.10 -m compileall -q backend scripts tests }
    Push-Location frontend
    try {
        Invoke-Checked "Frontend build" { npm run build }
        Invoke-Checked "Frontend tests" { npm test -- --run }
        Invoke-Checked "Dependency audit" { npm audit --audit-level=high }
    }
    finally {
        Pop-Location
    }
}
finally {
    Pop-Location
}

Write-Host "`nAll checks passed." -ForegroundColor Green
