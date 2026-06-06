param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $root ".demo-pids.json"
. (Join-Path $PSScriptRoot "import-qiniu-config.ps1")

if (Test-Path $pidFile) {
    throw "Demo PID file already exists. Run .\scripts\stop-demo.ps1 first."
}
if (-not (Test-Path (Join-Path $root "frontend\node_modules\vite\bin\vite.js"))) {
    throw "Frontend dependencies are missing. Run npm install inside frontend first."
}

$backend = Start-Process -FilePath "py" `
    -ArgumentList "-3.10", "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru
$frontend = Start-Process -FilePath "node" `
    -ArgumentList "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "5173" `
    -WorkingDirectory (Join-Path $root "frontend") -WindowStyle Hidden -PassThru

@{
    backend = $backend.Id
    frontend = $frontend.Id
} | ConvertTo-Json | Set-Content -Encoding UTF8 $pidFile

try {
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:8000/api/v1/health"
            $page = Invoke-WebRequest "http://127.0.0.1:5173/" -UseBasicParsing
            if ($health.status -eq "ok" -and $page.StatusCode -eq 200) {
                $ready = $true
                break
            }
        }
        catch {
        }
    }
    if (-not $ready) {
        throw "Demo services did not become ready."
    }
    if (-not $NoBrowser) {
        Start-Process "http://127.0.0.1:5173/"
    }
    Write-Host "Demo is running at http://127.0.0.1:5173/" -ForegroundColor Green
    Write-Host "Run .\scripts\stop-demo.ps1 to stop it."
}
catch {
    & (Join-Path $PSScriptRoot "stop-demo.ps1")
    throw
}
