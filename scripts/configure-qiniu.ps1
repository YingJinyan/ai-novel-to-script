param(
    [string]$Model = "deepseek-v3"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$configDirectory = Join-Path $root ".local"
$configPath = Join-Path $configDirectory "qiniu-config.json"

$secureKey = Read-Host "Enter Qiniu AI API Key (input is hidden)" -AsSecureString
if ($secureKey.Length -eq 0) {
    throw "API Key cannot be empty."
}
if (-not $Model.Trim()) {
    throw "Model ID cannot be empty."
}

New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
@{
    encrypted_api_key = ConvertFrom-SecureString $secureKey
    model = $Model.Trim()
} | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8

Write-Host "Qiniu configuration was encrypted for the current Windows user." -ForegroundColor Green
Write-Host "start-demo.ps1 and verify-qiniu.ps1 will load it automatically."
Write-Host "The config is under the Git-ignored .local directory. Do not share it."
