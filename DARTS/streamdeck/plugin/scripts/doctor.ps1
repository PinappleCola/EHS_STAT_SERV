<#
.SYNOPSIS
    Diagnoses the DARTS Stream Deck plugin installation status and logs.
.DESCRIPTION
    1. Scans AppData, LocalAppData, and Program Files for any manifest.json referencing com.pineapplecola.darts.
    2. Detects duplicate-UUID installations (e.g. AppData vs Program Files conflict).
    3. Analyzes recent Stream Deck log entries for conflict, connected, and NodeManager messages.
    4. Prints a PASS/FAIL summary with actionable remediation steps.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"

Write-Host "=== DARTS Stream Deck Plugin - Diagnostics (Doctor) ===" -ForegroundColor Cyan
Write-Host ""

$uuid = "com.pineapplecola.darts"
$searchRoots = @(
    "$env:APPDATA\Elgato",
    "$env:LOCALAPPDATA\Elgato",
    "C:\Program Files\Elgato",
    "C:\Program Files (x86)\Elgato"
)
if ($env:ProgramFiles) { $searchRoots += "$env:ProgramFiles\Elgato" }
if (${env:ProgramFiles(x86)}) { $searchRoots += "${env:ProgramFiles(x86)}\Elgato" }
$searchRoots = $searchRoots | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique

# 1. Search for installed copies
Write-Host "[1/3] Searching for installed DARTS plugin manifests..."
$foundManifests = @()

foreach ($root in $searchRoots) {
    $manifestFiles = Get-ChildItem -Recurse -Path $root -Filter "manifest.json" -ErrorAction SilentlyContinue
    foreach ($mf in $manifestFiles) {
        try {
            $content = Get-Content $mf.FullName -Raw -ErrorAction SilentlyContinue
            if ($content -match "com\.pineapplecola\.darts") {
                $foundManifests += $mf.FullName
            }
        } catch {}
    }
}

$foundManifests = $foundManifests | Select-Object -Unique

Write-Host "  Found $($foundManifests.Count) plugin manifest(s):"
foreach ($m in $foundManifests) {
    Write-Host "    - $m"
}

# 2. Check for duplicate UUID installation
Write-Host ""
Write-Host "[2/3] Checking for duplicate plugin conflicts..."
$hasDuplicate = ($foundManifests.Count -gt 1)
$hasProgramFilesCopy = ($foundManifests | Where-Object { $_ -like "*Program Files*" }).Count -gt 0
$hasAppDataCopy = ($foundManifests | Where-Object { $_ -like "*AppData\Roaming*" }).Count -gt 0

if ($hasDuplicate) {
    Write-Host "  [!] DUPLICATE DETECTED: Multiple copies of '$uuid' found." -ForegroundColor Red
    if ($hasProgramFilesCopy -and $hasAppDataCopy) {
        Write-Host "      You have copies in both AppData and Program Files." -ForegroundColor Red
        Write-Host "      This triggers the Elgato 'Plugin conflict' bug and '(AlreadyInstalled)' error!" -ForegroundColor Red
    }
} elseif ($foundManifests.Count -eq 1) {
    Write-Host "  [OK] Single plugin installation found." -ForegroundColor Green
    if ($hasProgramFilesCopy) {
        Write-Host "  [!] Notice: Plugin is installed in Program Files rather than per-user AppData." -ForegroundColor Yellow
    }
} else {
    Write-Host "  [!] No installed DARTS plugin found." -ForegroundColor Yellow
}

# 3. Analyze Stream Deck logs
Write-Host ""
Write-Host "[3/3] Inspecting Stream Deck logs..."
$logFile = "$env:APPDATA\Elgato\StreamDeck\logs\StreamDeck.log"
$logEntries = @()
$hasConflict = $false
$hasConnected = $false
$hasAlreadyInstalled = $false

if (Test-Path $logFile) {
    $recentLines = Get-Content $logFile -Tail 150 -ErrorAction SilentlyContinue
    foreach ($line in $recentLines) {
        if ($line -match "pineapplecola" -or $line -match "darts" -or $line -match "Plugin conflict") {
            $logEntries += $line
            if ($line -match "Plugin conflict.*com\.pineapplecola\.darts") { $hasConflict = $true }
            if ($line -match "connected.*com\.pineapplecola\.darts" -or $line -match "Plugin 'DARTS Live Map'.*connected") { $hasConnected = $true }
            if ($line -match "\(AlreadyInstalled\).*com\.pineapplecola\.darts") { $hasAlreadyInstalled = $true }
        }
    }
    
    if ($logEntries.Count -gt 0) {
        Write-Host "  Relevant log entries (last $([Math]::Min(10, $logEntries.Count))):"
        $logEntries | Select-Object -Last 10 | ForEach-Object { Write-Host "    $_" }
    } else {
        Write-Host "  No recent log entries found for DARTS or conflicts."
    }
} else {
    Write-Host "  StreamDeck.log not found at $logFile" -ForegroundColor Yellow
}

# 4. Summary & Verdict
Write-Host ""
Write-Host "=== Summary & Recommendations ===" -ForegroundColor Cyan

if ($hasDuplicate -or $hasConflict -or $hasAlreadyInstalled) {
    Write-Host "VERDICT: FAIL - Plugin conflict / Duplicate UUID detected" -ForegroundColor Red
    Write-Host ""
    Write-Host "Root Cause:" -ForegroundColor Yellow
    Write-Host "  A duplicate copy exists (typically in C:\Program Files\Elgato\StreamDeck\Plugins\)."
    Write-Host "  This causes Stream Deck to report 'Plugin conflict: already loaded plugin with same uuid'"
    Write-Host "  and the installer to say '(AlreadyInstalled)' without exposing any actions."
    Write-Host ""
    Write-Host "Fix:" -ForegroundColor Green
    Write-Host "  1. Run uninstall.ps1 (from an elevated/Administrator PowerShell prompt if Program Files has a copy):"
    Write-Host "     Remove-Item -Recurse -Force 'C:\Program Files\Elgato\StreamDeck\Plugins\com.pineapplecola.darts.sdPlugin'"
    Write-Host "  2. Install via manual copy into %APPDATA%\Elgato\StreamDeck\Plugins\ using install-manual.ps1"
    Write-Host "  3. Restart Stream Deck."
} elseif ($foundManifests.Count -eq 0) {
    Write-Host "VERDICT: NOT INSTALLED" -ForegroundColor Yellow
    Write-Host "Run install-manual.ps1 or double-click dist/com.pineapplecola.darts.streamDeckPlugin to install."
} elseif ($hasConnected -or ($foundManifests.Count -eq 1 -and -not $hasConflict)) {
    Write-Host "VERDICT: PASS - Plugin is cleanly installed" -ForegroundColor Green
    Write-Host "If Stream Deck is running, the DARTS actions (MAP, IFR, VFR) should be available."
} else {
    Write-Host "VERDICT: ATTENTION REQUIRED" -ForegroundColor Yellow
    Write-Host "Check the logs above or perform a clean reinstall with uninstall.ps1 and install-manual.ps1."
}
