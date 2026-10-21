# ==============================================================================
# code-search-graph Docker Launcher (Windows PowerShell)
# Usage:
#   .\scripts\docker-run.ps1 [-TargetDir D:\my-project]
# ==============================================================================

param(
    [string]$TargetDir = (Get-Location).Path
)

$ResolvedPath = (Resolve-Path $TargetDir).Path
Write-Host "[code-search-graph] Starting Docker MCP service..." -ForegroundColor Green
Write-Host "[code-search-graph] Mounting repository: $ResolvedPath" -ForegroundColor Cyan

# Check if Docker image exists locally
$imageExists = docker images -q code-search-graph:latest
if (-not $imageExists) {
    Write-Host "[code-search-graph] Image not found locally, building code-search-graph:latest..." -ForegroundColor Yellow
    $RootDir = (Resolve-Path "$PSScriptRoot\..").Path
    docker build -t code-search-graph:latest $RootDir
}

# Run container with interactive stdio attached for MCP protocol
docker run -i --rm `
  -v "${ResolvedPath}:/workspace:ro" `
  -v "code-search-cache:/root/.code-search-graph" `
  code-search-graph:latest `
  serve
