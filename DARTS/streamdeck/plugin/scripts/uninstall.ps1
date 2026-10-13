<#
.SYNOPSIS
    Completely uninstalls the DARTS Stream Deck plugin from all known locations.
.DESCRIPTION
    Finds and removes all copies of com.pineapplecola.darts.sdPlugin across:
      - %APPDATA%\Elgato\StreamDeck\Plugins\
      - %LOCALAPPDATA%\Elgato\StreamDeck\Plugins\
      - C:\Program Files\Elgato\StreamDeck\Plugins\ (requires Administrator elevation)
      - C:\Program Files (x86)\Elgato\StreamDeck\Plugins\ (requires Administrator elevation)
    Also removes the temp import cache at %LOCALAPPDATA%\Temp\com.elgato.streamdeck.
    Safe and idempotent.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"

Write-Host "=== DARTS Stream Deck Plugin - Complete Uninstall / Clean Reset ===" -ForegroundColor Cyan

# 1. Best-effort quit Stream Deck
$sdProcess = Get-Process -Name "StreamDeck" -ErrorAction SilentlyContinue
if ($sdProcess) {
    Write-Host "Quitting Stream Deck..."
    $sdProcess | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

# 2. Candidate plugin directories to check and clean
$pluginFolderName = "com.pineapplecola.darts.sdPlugin"
$candidateRoots = @(
    "$env:APPDATA\Elgato\StreamDeck\Plugins",
    "$env:LOCALAPPDATA\Elgato\StreamDeck\Plugins",
    "C:\Program Files\Elgato\StreamDeck\Plugins",
    "C:\Program Files (x86)\Elgato\StreamDeck\Plugins"
)

if ($env:ProgramFiles) {
    $candidateRoots += "$env:ProgramFiles\Elgato\StreamDeck\Plugins"
}
if (${env:ProgramFiles(x86)}) {
    $candidateRoots += "${env:ProgramFiles(x86)}\Elgato\StreamDeck\Plugins"
}

# De-duplicate roots and keep only reachable paths
$candidateRoots = $candidateRoots | Where-Object { $_ -and (Test-Path $_ -ErrorAction SilentlyContinue) } | Select-Object -Unique

$removedCount = 0
$adminWarning = $false

foreach ($root in $candidateRoots) {
    $targetPath = Join-Path $root $pluginFolderName
    if (Test-Path $targetPath -ErrorAction SilentlyContinue) {
        Write-Host "Found DARTS plugin copy at: $targetPath"
        try {
            Remove-Item -Path $targetPath -Recurse -Force -ErrorAction Stop
            Write-Host "  -> REMOVED: $targetPath" -ForegroundColor Green
            $removedCount++
        } catch {
            Write-Host "  -> FAILED to remove: $targetPath" -ForegroundColor Red
            Write-Warning $_.Exception.Message
            if ($targetPath -like "*Program Files*") {
                $adminWarning = $true
            }
        }
    }
}

# Also do a deep search for any manifest.json mentioning com.pineapplecola.darts in Elgato dirs
$searchRoots = @(
    "$env:APPDATA\Elgato",
    "$env:LOCALAPPDATA\Elgato",
    "C:\Program Files\Elgato",
    "C:\Program Files (x86)\Elgato"
)
if ($env:ProgramFiles) { $searchRoots += "$env:ProgramFiles\Elgato" }
if (${env:ProgramFiles(x86)}) { $searchRoots += "${env:ProgramFiles(x86)}\Elgato" }
$searchRoots = $searchRoots | Where-Object { $_ -and (Test-Path $_ -ErrorAction SilentlyContinue) } | Select-Object -Unique

foreach ($sRoot in $searchRoots) {
    $manifests = Get-ChildItem -Recurse -Path $sRoot -Filter "manifest.json" -ErrorAction SilentlyContinue
    foreach ($m in $manifests) {
        try {
            $content = Get-Content $m.FullName -Raw -ErrorAction SilentlyContinue
            if ($content -match "com\.pineapplecola\.darts") {
                $parentFolder = $m.Directory.FullName
                if (Test-Path $parentFolder -ErrorAction SilentlyContinue) {
                    Write-Host "Found additional DARTS manifest location: $parentFolder"
                    try {
                        Remove-Item -Path $parentFolder -Recurse -Force -ErrorAction Stop
                        Write-Host "  -> REMOVED: $parentFolder" -ForegroundColor Green
                        $removedCount++
                    } catch {
                        Write-Host "  -> FAILED to remove: $parentFolder" -ForegroundColor Red
                        Write-Warning $_.Exception.Message
                        if ($parentFolder -like "*Program Files*") {
                            $adminWarning = $true
                        }
                    }
                }
            }
        } catch {
            # Skip unreadable files
        }
    }
}

# 3. Clear temp import cache
if ($env:LOCALAPPDATA) {
    $tempCache = Join-Path $env:LOCALAPPDATA "Temp\com.elgato.streamdeck"
    if (Test-Path $tempCache -ErrorAction SilentlyContinue) {
        Write-Host "Clearing Stream Deck temp import cache at: $tempCache"
        try {
            Remove-Item -Path $tempCache -Recurse -Force -ErrorAction Stop
            Write-Host "  -> Cache cleared." -ForegroundColor Green
        } catch {
            Write-Warning "Could not clear cache: $($_.Exception.Message)"
        }
    }
}

Write-Host ""
Write-Host "Uninstall summary:"
Write-Host "  Removed plugin copies: $removedCount"

if ($adminWarning) {
    Write-Host ""
    Write-Host "======================================================================" -ForegroundColor Red
    Write-Host "ADMINISTRATOR PRIVILEGES REQUIRED:" -ForegroundColor Yellow
    Write-Host "One or more copies in 'Program Files' could not be removed." -ForegroundColor Yellow
    Write-Host "A leftover copy in Program Files causes 'Plugin conflict' errors" -ForegroundColor Yellow
    Write-Host "and makes the installer report '(AlreadyInstalled)' with no actions!" -ForegroundColor Yellow
    Write-Host "Please open PowerShell as Administrator and run:" -ForegroundColor Cyan
    Write-Host 'Remove-Item -Recurse -Force "C:\Program Files\Elgato\StreamDeck\Plugins\com.pineapplecola.darts.sdPlugin"' -ForegroundColor White
    Write-Host "======================================================================" -ForegroundColor Red
} else {
    Write-Host "All targeted plugin copies and caches have been cleanly removed." -ForegroundColor Green
    Write-Host "You can now perform a clean reinstall." -ForegroundColor Green
}
