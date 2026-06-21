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
$credential = [System.Net.NetworkCredential]::new("", $secureKey)
$apiKey = $credential.Password.Trim()
if (-not $apiKey) {
    throw "API Key cannot be empty."
}
if ($apiKey -match "\s" -or $apiKey -match "[^\x21-\x7E]") {
    throw "API Key contains spaces, Chinese characters, or invisible characters. Paste only the key itself, for example sk-..."
}
$secureKey = ConvertTo-SecureString $apiKey -AsPlainText -Force
$modelId = $Model.Trim()

New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
@{
    encrypted_api_key = ConvertFrom-SecureString $secureKey
    model = $modelId
} | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8

$env:QINIU_AI_API_KEY = $apiKey
$env:QINIU_AI_MODEL = $modelId

Write-Host "Qiniu configuration was encrypted for the current Windows user." -ForegroundColor Green
Write-Host "start-demo.ps1 and verify-qiniu.ps1 will load it automatically."
Write-Host "The config is under the Git-ignored .local directory. Do not share it."
