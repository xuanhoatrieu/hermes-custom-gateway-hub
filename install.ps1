<#
.SYNOPSIS
    Zero-touch installer for Hermes Custom Gateway Hub (`custom-gateway-hub` v1.1.0).
.DESCRIPTION
    Installs the unified backend + Desktop UI plugin into `$HERMES_HOME` and automatically
    enables `custom-gateway-hub` in `$HERMES_HOME\config.yaml` — no manual `.env` or
    `config.yaml` file editing required!
#>
param(
    [string]$HermesHome = $(if ($env:HERMES_HOME) { $env:HERMES_HOME } elseif (Test-Path "$env:LOCALAPPDATA\hermes") { "$env:LOCALAPPDATA\hermes" } else { "$HOME\.hermes" })
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Split-Path -Parent $MyInvocation.MyCommand.Path)).Path

New-Item -ItemType Directory -Force -Path $HermesHome | Out-Null
$HermesHomeResolved = (Resolve-Path $HermesHome).Path

$DstBackend = Join-Path $HermesHomeResolved "plugins\custom-gateway-hub"
$DstDesktop = Join-Path $HermesHomeResolved "desktop-plugins\custom-gateway-hub"

if ($RepoRoot -ne $DstBackend) {
    New-Item -ItemType Directory -Force -Path $DstBackend | Out-Null
    Get-ChildItem -Path $RepoRoot -Force | Where-Object { $_.Name -notin @("__pycache__", ".pytest_cache", ".ruff_cache") } | ForEach-Object {
        Copy-Item -Recurse -Force $_.FullName (Join-Path $DstBackend $_.Name)
    }
    Write-Host "[OK] Installed unified backend package -> $DstBackend" -ForegroundColor Green
} else {
    Write-Host "[OK] Package is already located at $DstBackend" -ForegroundColor Green
}

New-Item -ItemType Directory -Force -Path $DstDesktop | Out-Null
Copy-Item -Force (Join-Path $DstBackend "desktop\plugin.js") (Join-Path $DstDesktop "plugin.js")
Write-Host "[OK] Synced Desktop UI plugin -> $DstDesktop\plugin.js" -ForegroundColor Green

# Auto-enable 'custom-gateway-hub' in $HermesHome\config.yaml
$ToolsPy = Get-ChildItem -Path (Join-Path $HermesHomeResolved "tools\python-*\python.exe") -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -ExpandProperty FullName
$PythonCandidates = @(
    $ToolsPy,
    (Join-Path $HermesHomeResolved "runtime\venv\Scripts\python.exe"),
    (Join-Path $HermesHomeResolved "python\python.exe"),
    (Join-Path $HermesHomeResolved "hermes-agent\.venv\Scripts\python.exe"),
    (Join-Path $HermesHomeResolved ".venv\Scripts\python.exe")
) | ForEach-Object { $_ } | Where-Object { $_ -and (Test-Path $_) }
$PythonExe = $PythonCandidates | Select-Object -First 1

$EnabledOk = $false
if ($PythonExe) {
    $EnableScript = @"
import os, sys
from pathlib import Path
home = Path(r'$HermesHomeResolved')
os.environ['HERMES_HOME'] = str(home)
agent_dir = home / 'hermes-agent'
if agent_dir.is_dir():
    sys.path.insert(0, str(agent_dir))
    try:
        import hermes_bootstrap
    except Exception:
        pass
from hermes_cli.config import load_config, save_config
cfg = load_config()
if not isinstance(cfg, dict):
    cfg = {}
plugins = cfg.setdefault('plugins', {})
if not isinstance(plugins, dict):
    plugins = {}
    cfg['plugins'] = plugins
enabled = plugins.get('enabled')
if not isinstance(enabled, list):
    enabled = []
    plugins['enabled'] = enabled
if 'custom-gateway-hub' not in enabled:
    enabled.append('custom-gateway-hub')
    save_config(cfg)
print('ENABLED_OK')
"@
    try {
        $Out = & $PythonExe -c $EnableScript 2>$null
        if ($Out -match "ENABLED_OK") {
            $EnabledOk = $true
            Write-Host "[OK] Auto-enabled 'custom-gateway-hub' in $HermesHomeResolved\config.yaml" -ForegroundColor Green
        }
    } catch {
        $EnabledOk = $false
    }
}

if (-not $EnabledOk) {
    $CfgPath = Join-Path $HermesHomeResolved "config.yaml"
    if (-not (Test-Path $CfgPath)) {
        Set-Content -Path $CfgPath -Encoding UTF8 -Value "plugins:`n  enabled:`n    - custom-gateway-hub`n"
        Write-Host "[OK] Created $CfgPath with 'custom-gateway-hub' enabled." -ForegroundColor Green
    } else {
        $RawCfg = Get-Content -Path $CfgPath -Raw -Encoding UTF8
        if ($RawCfg -notmatch "custom-gateway-hub") {
            Write-Host "[INFO] Open Hermes Desktop -> Capabilities -> Plugins and switch ON 'Custom Gateway Hub'." -ForegroundColor Yellow
        }
    }
}

Write-Host "`nHoan tat cai dat Custom Gateway Hub v1.1.0!" -ForegroundColor Cyan
Write-Host "  1. Mo Hermes Desktop (hoac nhan Ctrl+K -> 'Reload desktop plugins' neu dang mo)."
Write-Host "  2. Chon tab 'Gateway Models' o thanh ben trai."
Write-Host "  3. Dan Base URL (/v1) + API Key -> nhan 'Check Connection & Tai Model moi' -> 'Luu & Ap dung ngay'!"
