$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

$localSecrets = Join-Path $PSScriptRoot ".streamlit\secrets.toml"
if (-not $env:LLM_API_KEY -and -not $env:DEEPSEEK_API_KEY -and -not (Test-Path -LiteralPath $localSecrets)) {
    $secureKey = Read-Host "DeepSeek API key (press Enter for rule-based research)" -AsSecureString
    $enteredKey = [System.Net.NetworkCredential]::new("", $secureKey).Password
    if (-not [string]::IsNullOrWhiteSpace($enteredKey)) {
        $env:DEEPSEEK_API_KEY = $enteredKey
    }
    Remove-Variable enteredKey, secureKey
}

if ($env:DEEPSEEK_API_KEY) {
    if (-not $env:DEEPSEEK_BASE_URL) { $env:DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1" }
    if (-not $env:DEEPSEEK_MODEL) { $env:DEEPSEEK_MODEL = "deepseek-chat" }
}

& (Join-Path $PSScriptRoot "run_app.ps1")
