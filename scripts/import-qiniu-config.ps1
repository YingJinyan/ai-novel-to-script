$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$configPath = Join-Path $root ".local\qiniu-config.json"
if (-not (Test-Path -LiteralPath $configPath)) {
    return
}

$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($config.encrypted_api_key) {
    $secureKey = ConvertTo-SecureString $config.encrypted_api_key
    $credential = [System.Net.NetworkCredential]::new("", $secureKey)
    $env:QINIU_AI_API_KEY = $credential.Password.Trim()
}
if ($config.model) {
    $env:QINIU_AI_MODEL = ([string]$config.model).Trim()
}
