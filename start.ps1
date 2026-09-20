$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

$secureKey = Read-Host "Enter your new Grok API key (input is hidden)" -AsSecureString
$enteredKey = [System.Net.NetworkCredential]::new("", $secureKey).Password
if ([string]::IsNullOrWhiteSpace($enteredKey)) {
    throw "No API key entered. Startup cancelled."
}
$env:GROK_API_KEY = $enteredKey
Remove-Variable enteredKey, secureKey

$env:GROK_BASE_URL = "http://100.94.190.42:18080/v1"
$env:GROK_MODEL = "grok-4.5"

& (Join-Path $PSScriptRoot "run_grok.ps1")
