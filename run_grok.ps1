$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

if (-not $env:GROK_API_KEY -and -not $env:DEEPSEEK_API_KEY -and -not $env:LLM_API_KEY) {
    throw "No supported AI API key is configured. Run start.ps1 or start_deepseek.ps1."
}

if ($env:DEEPSEEK_API_KEY) {
    $aiEndpoint = $env:DEEPSEEK_BASE_URL
    $aiModel = $env:DEEPSEEK_MODEL
} elseif ($env:LLM_API_KEY) {
    $aiEndpoint = $env:LLM_BASE_URL
    $aiModel = $env:LLM_MODEL
} else {
    $aiEndpoint = $env:GROK_BASE_URL
    $aiModel = $env:GROK_MODEL
}

if (-not $aiEndpoint) {
    $aiEndpoint = "http://100.94.190.42:18080/v1"
}
if (-not $aiModel) {
    $aiModel = "grok-4.5"
}

if ($env:DEEPSEEK_API_KEY) {
    $providerLabel = "DeepSeek"
} elseif ($env:LLM_API_KEY) {
    $providerLabel = "OpenAI-compatible"
} else {
    $providerLabel = "Grok"
}

if (-not $env:GROK_BASE_URL -and -not $env:DEEPSEEK_BASE_URL -and -not $env:LLM_BASE_URL) {
    $env:GROK_BASE_URL = "http://100.94.190.42:18080/v1"
}

Write-Host "$providerLabel endpoint: $aiEndpoint"
Write-Host "$providerLabel model:    $aiModel"
Write-Host "Keep this window open. After startup, open http://localhost:8501"
$pythonArgs = @()
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) {
    $pythonCommand = $venvPython
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCommand = "py"
    $pythonArgs = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCommand = "python"
} else {
    throw "Python was not found. Install Python 3.11 or 3.12 and reopen PowerShell."
}
& $pythonCommand @pythonArgs -m streamlit run app.py --server.headless true --server.port 8501
if ($LASTEXITCODE -ne 0) {
    throw "Streamlit exited with code $LASTEXITCODE. Check the error above. To install dependencies: $pythonCommand $pythonArgs -m pip install -r requirements.txt"
}
