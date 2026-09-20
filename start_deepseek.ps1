$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

$secureKey = Read-Host "Enter your new DeepSeek API key (input is hidden)" -AsSecureString
$enteredKey = [System.Net.NetworkCredential]::new("", $secureKey).Password
if ([string]::IsNullOrWhiteSpace($enteredKey)) {
    throw "No API key entered. Startup cancelled."
}
$env:DEEPSEEK_API_KEY = $enteredKey
Remove-Variable enteredKey, secureKey

$env:DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
$env:DEEPSEEK_MODEL = "deepseek-chat"
$env:LLM_TIMEOUT_SECONDS = "20"

& (Join-Path $PSScriptRoot "run_grok.ps1")
