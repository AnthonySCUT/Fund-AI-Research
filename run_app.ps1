$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

if ($env:LLM_API_KEY) {
    $aiMode = "Custom OpenAI-compatible API"
    $aiModel = if ($env:LLM_MODEL) { $env:LLM_MODEL } else { "configured model" }
} elseif ($env:DEEPSEEK_API_KEY) {
    $aiMode = "DeepSeek"
    $aiModel = if ($env:DEEPSEEK_MODEL) { $env:DEEPSEEK_MODEL } else { "deepseek-chat" }
} else {
    $aiMode = "Rule-based research (configure an API key to enable AI)"
    $aiModel = ""
}

Write-Host "AI mode:  $aiMode"
if ($aiModel) {
    Write-Host "AI model: $aiModel"
}
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
    throw "Streamlit exited with code $LASTEXITCODE. Check the error above."
}
