$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendRoot = Join-Path $repoRoot "backend"
$pythonExe = "D:\software\anaconda\envs\play\python.exe"
$port = if ($env:BACKEND_PORT) { [int]$env:BACKEND_PORT } else { 8485 }

if (-not (Test-Path $pythonExe)) {
  throw "Python not found: $pythonExe"
}

$proxyKeys = @(
  "HTTP_PROXY",
  "HTTPS_PROXY",
  "ALL_PROXY",
  "http_proxy",
  "https_proxy",
  "all_proxy",
  "VIDEONOTE_USE_ENV_PROXY"
)
foreach ($key in $proxyKeys) {
  Remove-Item "Env:$key" -ErrorAction SilentlyContinue
}

function Test-PortListening {
  param([int]$Port)

  $pattern = "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+\d+"
  $matches = netstat -ano -p tcp | Select-String -Pattern $pattern
  return $null -ne $matches
}

if (Test-PortListening -Port $port) {
  Write-Host "Backend port $port is already occupied." -ForegroundColor Yellow
  Write-Host "Open the existing app: http://127.0.0.1:$port"
  Write-Host "Diagnostics: http://127.0.0.1:$port/api/runtime_diagnostics"
  exit 0
}

$env:BACKEND_PORT = [string]$port
Set-Location $backendRoot

Write-Host "Starting VideoNote backend on http://127.0.0.1:$port"
Write-Host "Browser entry: http://127.0.0.1:$port"
Write-Host "Runtime diagnostics: http://127.0.0.1:$port/api/runtime_diagnostics"
& $pythonExe main.py
