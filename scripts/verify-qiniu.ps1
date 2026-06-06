param(
    [string]$Model = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "import-qiniu-config.ps1")
$arguments = @("-3.10", "-m", "scripts.verify_qiniu")
if ($Model.Trim()) {
    $arguments += @("--model", $Model.Trim())
}

Push-Location $root
try {
    & py @arguments
    $verificationExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

exit $verificationExitCode
