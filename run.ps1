<#
.SYNOPSIS
  Set up and run HCG Knowledge Centre on Windows (PowerShell equivalent of run.sh).
.EXAMPLE
  .\run.ps1                 # create .venv, install requirements, initialise the database, start on http://127.0.0.1:5000
  .\run.ps1 -SetupOnly      # prepare everything without starting the server
  .\run.ps1 -Port 8000 -NoDebug
.NOTES
  If scripts are blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#>
param(
  [switch]$SetupOnly,
  [int]$Port = 0,
  [string]$BindHost = "127.0.0.1",
  [switch]$NoDebug
)
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# 1. Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $python) { throw "Python 3.10+ is required. Install it from https://www.python.org/downloads/ and tick 'Add python.exe to PATH'." }

# 2. Virtual environment
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  Step "Creating virtual environment (.venv)"
  & $python.Source -m venv .venv
}
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

# 3. Dependencies, re-installed only when requirements.txt changes
$stampFile = ".venv\.requirements.sha256"
$hash = (Get-FileHash requirements.txt -Algorithm SHA256).Hash
if (-not (Test-Path $stampFile) -or (Get-Content $stampFile) -ne $hash) {
  Step "Installing dependencies"
  & $venvPython -m pip install --quiet --upgrade pip
  & $venvPython -m pip install --quiet -r requirements.txt
  Set-Content -Path $stampFile -Value $hash
} else {
  Step "Dependencies up to date"
}

# 4. Database: create tables, apply init_scripts/*.sql, seed demo data (LMS_SEED_DEMO)
Step "Initialising the database"
& $venvPython -m flask --app app init-db

if ($SetupOnly) { Step "Setup complete. Start the app with .\run.ps1"; exit 0 }

# 5. Port: honour -Port / LMS_PORT, otherwise 5000 with fallback to 5050-5059 when busy
if ($Port -eq 0) { $Port = if ($env:LMS_PORT) { [int]$env:LMS_PORT } else { 5000 } }
function PortBusy($p) { return (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue) -ne $null }
if (PortBusy $Port) {
  $candidate = 5050
  while ($candidate -le 5059 -and (PortBusy $candidate)) { $candidate++ }
  if ($candidate -gt 5059) { throw "Ports $Port and 5050-5059 are all in use." }
  Write-Host "Port $Port is busy, using $candidate" -ForegroundColor Yellow
  $Port = $candidate
}

$env:LMS_HOST = $BindHost
$env:LMS_PORT = "$Port"
if ($NoDebug) { $env:LMS_DEBUG = "0" }
Step "Starting HCG Knowledge Centre on http://$BindHost`:$Port  (Ctrl+C to stop)"
& $venvPython app.py
