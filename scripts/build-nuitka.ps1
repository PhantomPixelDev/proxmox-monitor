#Requires -Version 5.1
<#
.SYNOPSIS
  Local Nuitka build helper for Windows (PowerShell).
  Mirrors the flags used in .github/workflows/release.yml so local builds match CI.

.DESCRIPTION
  Produces a standalone onefile exe with:
    --standalone --onefile --enable-plugin=pyside6
    --windows-console-mode=disable --windows-icon-from-ico=src/proxmox_widget/resources/app.ico
    --include-data-dir=src/proxmox_widget/resources=resources

  On non-Windows the windows-only flags are skipped.

.PARAMETER OutputFile
  Output filename. Default: dist/ProxmoxWidget-windows.exe on Windows, dist/ProxmoxWidget.bin elsewhere.

.PARAMETER Clean
  Remove dist/ build artifacts before building.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts/build-nuitka.ps1
  powershell -ExecutionPolicy Bypass -File scripts/build-nuitka.ps1 -Clean
#>
[CmdletBinding()]
param(
  [string]$OutputFile = "",
  [switch]$Clean
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

if (-not $OutputFile) {
  if ($IsWindows -or $env:OS -like "*Windows*") {
    $OutputFile = "ProxmoxWidget-windows.exe"
  } else {
    $OutputFile = "ProxmoxWidget.bin"
  }
}

$IconPath = "src/proxmox_widget/resources/app.ico"
$EntryPoint = "src/proxmox_widget/__main__.py"
$DistDir = "dist"

if (-not (Test-Path $EntryPoint)) {
  Write-Error "Entry point not found: $EntryPoint (run from repo root)"
  exit 1
}
if (-not (Test-Path $IconPath)) {
  Write-Warning "Icon not found at $IconPath — build will continue without --windows-icon-from-ico"
  $HasIcon = $false
} else {
  $HasIcon = $true
}

if ($Clean -and (Test-Path $DistDir)) {
  Write-Host "Cleaning $DistDir..." -ForegroundColor Yellow
  Remove-Item -Recurse -Force $DistDir
}

# Ensure output dir exists
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null

# Ensure deps
Write-Host "Checking Python deps..." -ForegroundColor Cyan
python -m pip install --upgrade pip
pip install -e .
pip install nuitka ordered-set

# Detect Windows for conditional flags
$IsWin = $IsWindows
if (-not $PSBoundParameters.ContainsKey("IsWindows") -and $null -eq $IsWindows) {
  # Windows PowerShell 5.1 has no $IsWindows
  $IsWin = $env:OS -like "*Windows*"
}

$NuitkaArgs = @(
  "--standalone"
  "--onefile"
  "--enable-plugin=pyside6"
  "--include-data-dir=src/proxmox_widget/resources=resources"
  "--output-filename=$OutputFile"
  "--output-dir=$DistDir"
  $EntryPoint
)

if ($IsWin) {
  $NuitkaArgs = @(
    "--standalone"
    "--onefile"
    "--enable-plugin=pyside6"
    "--windows-console-mode=disable"
    "--include-data-dir=src/proxmox_widget/resources=resources"
  ) + @(
    if ($HasIcon) { "--windows-icon-from-ico=$IconPath" } else { @() }
  ) + @(
    "--output-filename=$OutputFile"
    "--output-dir=$DistDir"
    $EntryPoint
  )
  # Flatten (PowerShell @() nesting)
  $NuitkaArgs = $NuitkaArgs | ForEach-Object { $_ }
}

Write-Host "Running: python -m nuitka $($NuitkaArgs -join ' ')" -ForegroundColor Green
& python -m nuitka @NuitkaArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$Built = Join-Path $DistDir $OutputFile
if (Test-Path $Built) {
  $Item = Get-Item $Built
  Write-Host "Build OK: $Built ($([math]::Round($Item.Length/1MB,2)) MB)" -ForegroundColor Green
  # SHA256
  $Hash = (Get-FileHash $Built -Algorithm SHA256).Hash.ToLower()
  $ShaFile = "$Built.sha256"
  "$Hash  $OutputFile" | Set-Content -NoNewline $ShaFile
  Write-Host "SHA256: $Hash" -ForegroundColor Cyan
  Write-Host "Checksum: $ShaFile" -ForegroundColor Cyan
  Get-ChildItem $DistDir | Format-Table Name, Length, LastWriteTime
} else {
  Write-Error "Build finished but $Built not found"
  exit 1
}
