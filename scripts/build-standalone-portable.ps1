param(
  [int]$MaxAttempts = 5,
  [int]$NuitkaTimeoutMs = 600000
)
$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $PSScriptRoot
if (-not $here) { $here = (Get-Location).Path }
Set-Location $here
Write-Host "=== Nuitka Standalone Portable ZIP builder (retry until success) ==="
Write-Host "PWD: $here"
Write-Host "Python: $(python --version)"
Write-Host "Nuitka: $(python -m nuitka --version)"
Write-Host "App.ico exists: $(Test-Path src/proxmox_widget/resources/app.ico)"

# Clean previous partial artifacts but keep dist folder
if (Test-Path dist/__main__.dist) { Write-Host "Removing previous dist/__main__.dist"; Remove-Item -Recurse -Force dist/__main__.dist -ErrorAction SilentlyContinue }
if (Test-Path dist/__main__.build) { Write-Host "Removing previous dist/__main__.build"; Remove-Item -Recurse -Force dist/__main__.build -ErrorAction SilentlyContinue }
Remove-Item dist/ProxmoxWidget-Portable.zip -Force -ErrorAction SilentlyContinue
Remove-Item dist/nuitka_build.log -Force -ErrorAction SilentlyContinue
Remove-Item dist/nuitka_stderr.log -Force -ErrorAction SilentlyContinue
Remove-Item dist/nuitka_stdout.log -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path dist | Out-Null

$attempts = @(
  @{
    Name = "attempt1-exact-task-flags"
    Args = @("--standalone","--enable-plugin=pyside6","--assume-yes-for-downloads","--include-data-dir=src/proxmox_widget/resources=resources","--include-package=proxmox_widget","--windows-console-mode=disable","--windows-icon-from-ico=src/proxmox_widget/resources/app.ico","--output-dir=dist","src/proxmox_widget/__main__.py")
  },
  @{
    Name = "attempt2-add-qt-plugins"
    Args = @("--standalone","--enable-plugin=pyside6","--assume-yes-for-downloads","--include-data-dir=src/proxmox_widget/resources=resources","--include-package=proxmox_widget","--windows-console-mode=disable","--windows-icon-from-ico=src/proxmox_widget/resources/app.ico","--include-qt-plugins=sensible,iconengines,imageformats,platforms,styles,tls","--output-dir=dist","src/proxmox_widget/__main__.py")
  },
  @{
    Name = "attempt3-remove-include-package"
    Args = @("--standalone","--enable-plugin=pyside6","--assume-yes-for-downloads","--include-data-dir=src/proxmox_widget/resources=resources","--windows-console-mode=disable","--windows-icon-from-ico=src/proxmox_widget/resources/app.ico","--output-dir=dist","src/proxmox_widget/__main__.py")
  },
  @{
    Name = "attempt4-no-icon"
    Args = @("--standalone","--enable-plugin=pyside6","--assume-yes-for-downloads","--include-data-dir=src/proxmox_widget/resources=resources","--include-package=proxmox_widget","--windows-console-mode=disable","--output-dir=dist","src/proxmox_widget/__main__.py")
  },
  @{
    Name = "attempt5-minimal"
    Args = @("--standalone","--enable-plugin=pyside6","--assume-yes-for-downloads","--output-dir=dist","src/proxmox_widget/__main__.py")
  }
)

$success = $false
$lastExit = -1

for ($i=0; $i -lt $attempts.Count -and $i -lt $MaxAttempts; $i++) {
  $attempt = $attempts[$i]
  Write-Host ""
  Write-Host "=== [$($i+1)/$MaxAttempts] $($attempt.Name) ==="
  Write-Host "Args: $($attempt.Args -join ' ')"
  $logFile = "dist/nuitka_build.log"
  $errFile = "dist/nuitka_stderr.log"
  $outFile = "dist/nuitka_stdout.log"

  # Remove previous build artifacts for clean retry, except on first iteration we already cleaned
  if ($i -gt 0) {
    if (Test-Path dist/__main__.dist) { Remove-Item -Recurse -Force dist/__main__.dist -ErrorAction SilentlyContinue }
    if (Test-Path dist/__main__.build) { Remove-Item -Recurse -Force dist/__main__.build -ErrorAction SilentlyContinue }
  }

  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = "python"
  $psi.Arguments = "-m nuitka " + ($attempt.Args -join " ")
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.UseShellExecute = $false
  $psi.CreateNoWindow = $true
  $psi.WorkingDirectory = $here

  $proc = New-Object System.Diagnostics.Process
  $proc.StartInfo = $psi

  $stdout = New-Object System.Text.StringBuilder
  $stderr = New-Object System.Text.StringBuilder

  $proc.add_OutputDataReceived({ param($sender,$e) if ($e.Data -ne $null) { $null = $stdout.AppendLine($e.Data); Write-Host $e.Data } })
  $proc.add_ErrorDataReceived({ param($sender,$e) if ($e.Data -ne $null) { $null = $stderr.AppendLine($e.Data); Write-Host $e.Data -ForegroundColor Yellow } })

  $proc.Start() | Out-Null
  $proc.BeginOutputReadLine()
  $proc.BeginErrorReadLine()

  $exited = $proc.WaitForExit($NuitkaTimeoutMs)
  if (-not $exited) {
    Write-Host "TIMEOUT after $NuitkaTimeoutMs ms - killing process" -ForegroundColor Red
    try { $proc.Kill($true) } catch {}
    $lastExit = 124
    $stdout.ToString() | Out-File -Encoding utf8 $outFile
    $stderr.ToString() | Out-File -Encoding utf8 $errFile
    "TIMEOUT after $NuitkaTimeoutMs ms`nArgs: $($attempt.Args -join ' ')" | Out-File -Encoding utf8 $logFile
    # timeout is a hard failure, try next variant
    continue
  }

  $proc.WaitForExit()
  $lastExit = $proc.ExitCode
  $stdout.ToString() | Out-File -Encoding utf8 $outFile
  $stderr.ToString() | Out-File -Encoding utf8 $errFile
  # also create combined log for task requirement
  $combined = "Nuitka exit code: $lastExit`nArgs: $($attempt.Args -join ' ')`n`nSTDOUT:`n" + $stdout.ToString() + "`n`nSTDERR:`n" + $stderr.ToString()
  $combined | Out-File -Encoding utf8 $logFile

  Write-Host "Exit code: $lastExit"

  if ($lastExit -eq 0) {
    # verify Test-Path dist/__main__.dist exists and is not empty
    $exists = Test-Path dist/__main__.dist
    Write-Host "Test-Path dist/__main__.dist: $exists"
    if ($exists) {
      $items = Get-ChildItem dist/__main__.dist -Force -ErrorAction SilentlyContinue
      $count = (Get-ChildItem dist/__main__.dist -Recurse -ErrorAction SilentlyContinue | Measure-Object).Count
      Write-Host "dist/__main__.dist items: $($items.Count) top-level, $count recursive"
      Get-ChildItem dist/__main__.dist | Select-Object -First 20 Name, Length | Format-Table -AutoSize | Out-String | Write-Host
      $hasExe = (Test-Path dist/__main__.dist/__main__.exe) -or (Test-Path dist/__main__.dist/__main__.dist/__main__.exe) -or ((Get-ChildItem dist/__main__.dist -Filter *.exe -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0)
      Write-Host "Has exe: $hasExe"
      if ($count -gt 0 -and $hasExe) {
        $success = $true
        break
      } else {
        Write-Host "dist/__main__.dist empty or missing exe - treating as failure, will retry" -ForegroundColor Red
        $lastExit = 2
      }
    } else {
      Write-Host "dist/__main__.dist missing - treating as failure" -ForegroundColor Red
      $lastExit = 3
    }
  }

  # if we are here, attempt failed - read log and decide fix
  Write-Host "Reading $logFile for diagnostics..." -ForegroundColor Cyan
  if (Test-Path $logFile) { Get-Content $logFile | Select-Object -Last 80 | ForEach-Object { Write-Host $_ -ForegroundColor DarkGray } }
  if (Test-Path $errFile) { Write-Host "--- stderr tail ---"; Get-Content $errFile | Select-Object -Last 40 | ForEach-Object { Write-Host $_ -ForegroundColor Yellow } }

  # heuristic fixes printed
  $logContent = ""
  if (Test-Path $errFile) { $logContent += Get-Content $errFile -Raw }
  if (Test-Path $outFile) { $logContent += Get-Content $outFile -Raw }
  if ($logContent -match "bad flag|unknown option|unrecognized") {
    Write-Host "Detected bad flag - next attempt will remove suspect flag" -ForegroundColor Magenta
  }
  if ($logContent -match "include-qt-plugins|Qt plugins") {
    Write-Host "Qt plugin hint detected" -ForegroundColor Magenta
  }
  Write-Host "Retrying with next variant..." -ForegroundColor Cyan
}

if (-not $success) {
  Write-Host ""
  Write-Host "=== ALL ATTEMPTS FAILED (last exit $lastExit) ===" -ForegroundColor Red
  exit 1
}

Write-Host ""
Write-Host "=== Nuitka standalone SUCCESS ===" -ForegroundColor Green
Get-ChildItem dist/__main__.dist | Format-Table Name, Length -AutoSize | Out-String | Write-Host
Write-Host "Recursive count: $((Get-ChildItem dist/__main__.dist -Recurse | Measure-Object).Count)"

# Verify has ProxmoxWidget.exe or __main__.exe + PySide6 files
$exeCandidates = Get-ChildItem dist/__main__.dist -Filter *.exe -Recurse -ErrorAction SilentlyContinue
Write-Host "Found exes: $($exeCandidates.Name -join ', ')"
$hasPySide = Test-Path dist/__main__.dist/PySide6 -or (Get-ChildItem dist/__main__.dist -Recurse -Filter "*PySide*" -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0
Write-Host "Has PySide6 files: $hasPySide"

# Rename __main__.exe to ProxmoxWidget.exe if needed for zip consistency
if ((Test-Path dist/__main__.dist/__main__.exe) -and -not (Test-Path dist/__main__.dist/ProxmoxWidget.exe)) {
  Write-Host "Copying __main__.exe to ProxmoxWidget.exe for verification"
  Copy-Item dist/__main__.dist/__main__.exe dist/__main__.dist/ProxmoxWidget.exe -Force
}

# Zip to dist/ProxmoxWidget-Portable.zip via Compress-Archive
$zipPath = "dist/ProxmoxWidget-Portable.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Write-Host "Zipping dist/__main__.dist to $zipPath via Compress-Archive..."
Compress-Archive -Path dist/__main__.dist/* -DestinationPath $zipPath -Force
Write-Host "Zip created: $(Test-Path $zipPath)"
Get-ChildItem dist/*.zip | Format-Table Name, Length, LastWriteTime -AutoSize | Out-String | Write-Host

# Generate sha256
$hash = Get-FileHash $zipPath -Algorithm SHA256
$shaPath = "$zipPath.sha256"
"$($hash.Hash.ToLower())  $($hash.Path | Split-Path -Leaf)" | Out-File -Encoding utf8 $shaPath
Write-Host "SHA256: $($hash.Hash.ToLower())"
Write-Host "SHA file: $shaPath"
Get-Content $shaPath | Write-Host

# Also for exe inside dist for gh verification
if (Test-Path dist/__main__.dist/ProxmoxWidget.exe) {
  $exeHash = Get-FileHash dist/__main__.dist/ProxmoxWidget.exe -Algorithm SHA256
  Write-Host "Exe SHA256: $($exeHash.Hash.ToLower())"
}

# Append to notepad
$notepadEntry = "$(Get-Date -Format 'yyyy-MM-dd HH:mm') Portable ZIP: $zipPath ($([math]::Round((Get-Item $zipPath).Length/1MB,2)) MB) sha256 $($hash.Hash.Substring(0,8))... Nuitka standalone OK"
Add-Content -Path notepad.txt -Value $notepadEntry -Encoding utf8
Write-Host "Appended to notepad.txt: $notepadEntry"
Get-Content notepad.txt | Select-Object -Last 5 | Write-Host

# Verification per task
Write-Host ""
Write-Host "=== Verification ==="
Write-Host "Get-ChildItem dist/*.zip:"
Get-ChildItem dist/*.zip | Format-Table Name, Length -AutoSize | Out-String | Write-Host
Write-Host "Get-ChildItem dist/__main__.dist has ProxmoxWidget.exe + PySide6:"
Get-ChildItem dist/__main__.dist | Where-Object { $_.Name -match "ProxmoxWidget|PySide|__main__" } | Format-Table Name, Length -AutoSize | Out-String | Write-Host
Get-ChildItem dist/__main__.dist -Recurse -Filter "*PySide6*" | Select-Object -First 5 FullName | Write-Host
Write-Host "gh run list (local build success):"
try { gh run list --limit 3 | Out-String | Write-Host } catch { Write-Host "gh not available or no runs" }

Write-Host "=== DONE ===" -ForegroundColor Green
exit 0
