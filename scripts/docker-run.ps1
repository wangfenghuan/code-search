# ==============================================================================
# code-search-mcp Docker 启动脚本 (Windows PowerShell)
# 用法:
#   .\scripts\docker-run.ps1 [-TargetDir D:\my-project]
# ==============================================================================

param(
    [string]$TargetDir = (Get-Location).Path
)

$ResolvedPath = (Resolve-Path $TargetDir).Path
Write-Host "[code-search-mcp] 正在启动 Docker MCP 容器服务..." -ForegroundColor Green
Write-Host "[code-search-mcp] 挂载目标代码库: $ResolvedPath" -ForegroundColor Cyan

# 检查本地是否已有镜像
$imageExists = docker images -q code-search-mcp:latest
if (-not $imageExists) {
    Write-Host "[code-search-mcp] 本地未发现镜像，正在执行首次构建..." -ForegroundColor Yellow
    $RootDir = (Resolve-Path "$PSScriptRoot\..").Path
    docker build -t code-search-mcp:latest $RootDir
}

# 启动 Docker 并将当前控制台 stdio 接通
docker run -i --rm `
  -v "${ResolvedPath}:/workspace:ro" `
  -v "code-search-cache:/root/.code-search-mcp" `
  code-search-mcp:latest `
  serve
