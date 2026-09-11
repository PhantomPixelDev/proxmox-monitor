param([Parameter(ValueFromRemainingArguments=$true)][string[]]$NuitkaArgs)
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot | Join-Path -ChildPath ".." -Resolve -ErrorAction SilentlyContinue | ForEach-Object { if($_){$_} else {(Get-Location).Path} })
# fallback
if (-not (Test-Path "src/proxmox_widget/__main__.py")) { Set-Location "C:\Users\tpwin\Documents\github\proxmox-monitor" }

Write-Host "=== Detached Nuitka run $(Get-Date) ==="
Write-Host "Args: $($NuitkaArgs -join ' ')"
Write-Host "PWD: $(Get-Location)"
Write-Host "Python: $(python --version)"
# Run directly, capture both streams, no timeout kill, just wait
$log = "dist/nuitka_build.log"
$stdoutLog = "dist/nuitka_stdout.log"
$stderrLog = "dist/nuitka_stderr.log"
# Ensure dist exists
New-Item -ItemType Directory -Force -Path dist | Out-Null
# Clean previous partial logs but keep build cache for incremental? For this attempt we keep build cache to see error, but you can uncomment clean
# if (Test-Path dist/__main__.build) { Write-Host "Keeping existing build cache"; }
# if (Test-Path dist/__main__.dist) { Remove-Item -Recurse -Force dist/__main__.dist -ErrorAction SilentlyContinue }

# Build command string
$argString = $NuitkaArgs -join " "
Write-Host "Running: python -m nuitka $argString"

# Use Start-Process with wait, capturing output via Tee
# Do not use WaitForExit timeout; wait indefinitely
try {
  # Use cmd to handle redirection properly
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = "python"
  $psi.Arguments = "-m nuitka $argString"
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.UseShellExecute = $false
  $psi.CreateNoWindow = $true
  $psi.WorkingDirectory = (Get-Location).Path

  $proc = New-Object System.Diagnostics.Process
  $proc.StartInfo = $psi
  $proc.EnableRaisingEvents = $true

  $outBuilder = New-Object System.Text.StringBuilder
  $errBuilder = New-Object System.Text.StringBuilder

  $proc.add_OutputDataReceived({
    param($s,$e)
    if ($e.Data -ne $null) {
      $null = $outBuilder.AppendLine($e.Data)
      Write-Host $e.Data
      # also append to file incremental
      Add-Content -Path $using:log -Value $e.Data -Encoding utf8
      Add-Content -Path $using:stdoutLog -Value $e.Data -Encoding utf8
    }
  })
  $proc.add_ErrorDataReceived({
    param($s,$e)
    if ($e.Data -ne $null) {
      $null = $errBuilder.AppendLine($e.Data)
      Write-Host $e.Data -ForegroundColor Yellow
      Add-Content -Path $using:log -Value $e.Data -Encoding utf8
      Add-Content -Path $using:stderrLog -Value $e.Data -Encoding utf8
    }
  })

  # Clear log
  "" | Out-File -Encoding utf8 $log
  "" | Out-File -Encoding utf8 $stdoutLog
  "" | Out-File -Encoding utf8 $stderrLog
  "Nuitka detached start $(Get-Date) Args: $argString" | Out-File -Encoding utf8 $log -Append

  $proc.Start() | Out-Null
  $proc.BeginOutputReadLine()
  $proc.BeginErrorReadLine()
  $proc.WaitForExit()
  $exitCode = $proc.ExitCode
  "Exit code: $exitCode" | Out-File -Encoding utf8 $log -Append
  Write-Host "Exit code: $exitCode"
  exit $exitCode
} catch {
  Write-Host "Exception: $_" -ForegroundColor Red
  $_ | Out-File -Append $log
  exit 99
}

