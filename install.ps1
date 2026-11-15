<#
.SYNOPSIS
    Installer script for Hermes Custom Gateway Hub (`custom-gateway-hub`).
.DESCRIPTION
    Copies the backend Python plugin and Desktop runtime UI plugin into `$HERMES_HOME`
    (defaults to `$env:LOCALAPPDATA\hermes` on Windows or `~/.hermes` if present)
    without modifying any core `hermes-agent` files.
#>
param(
    [string]$HermesHome = $(if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif (Test-Path "$env:LOCALAPPDATA\hermes") { "$env:LOCALAPPDATA\hermes" } else { "$HOME\.hermes" })
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

$SrcBackend = Join-Path $RepoRoot "plugins\custom-gateway-hub"
$SrcDesktop = Join-Path $RepoRoot "desktop-plugins\custom-gateway-hub"

$DstBackend = Join-Path $HermesHome "plugins\custom-gateway-hub"
$DstDesktop = Join-Path $HermesHome "desktop-plugins\custom-gateway-hub"

if ((Resolve-Path $RepoRoot).Path -ne (Resolve-Path $HermesHome -ErrorAction SilentlyContinue).Path) {
    New-Item -ItemType Directory -Force -Path $DstBackend | Out-Null
    New-Item -ItemType Directory -Force -Path $DstDesktop | Out-Null
    Copy-Item -Recurse -Force "$SrcBackend\*" $DstBackend
    Copy-Item -Recurse -Force "$SrcDesktop\*" $DstDesktop
    Write-Host "[OK] Installed backend plugin -> $DstBackend" -ForegroundColor Green
    Write-Host "[OK] Installed desktop plugin -> $DstDesktop" -ForegroundColor Green
} else {
    Write-Host "[OK] Already running directly inside HERMES_HOME ($HermesHome)." -ForegroundColor Green
}

Write-Host "`nNext steps:" -ForegroundColor Cyan
Write-Host "  1. Ensure 'custom-gateway-hub' is listed under 'plugins.enabled' in $HermesHome\config.yaml (see config.example.yaml)."
Write-Host "  2. Set HERMES_CUSTOM_CUSTOM_GATEWAY_API_KEY=sk-... in $HermesHome\.env."
Write-Host "  3. In Hermes Desktop, press Ctrl+K -> 'Reload desktop plugins' and open 'Gateway Models'."
