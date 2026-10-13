<#
.SYNOPSIS
    Manually installs the DARTS Stream Deck plugin into %APPDATA%\Elgato\StreamDeck\Plugins.
.DESCRIPTION
    Fully quits Stream Deck (best-effort), cleans any existing per-user DARTS plugin installation,
    copies com.pineapplecola.darts.sdPlugin into %APPDATA%\Elgato\StreamDeck\Plugins\, and restarts Stream Deck.
    Idempotent and safe to run multiple times.
.PARAMETER SourcePath
    Optional path to the com.pineapplecola.darts.sdPlugin folder or com.pineapplecola.darts.streamDeckPlugin archive.
    Defaults to the repository folder relative to this script.
#>
[CmdletBinding()]
param(
    [string]$SourcePath = ""
)

$ErrorActionPreference = "Stop"

Write-Host "=== DARTS Stream Deck Plugin - Manual Installer ===" -ForegroundColor Cyan

# 1. Stop Stream Deck if running (best-effort)
Write-Host "Step 1: Quitting Stream Deck (if running)..."
$sdProcess = Get-Process -Name "StreamDeck" -ErrorAction SilentlyContinue
if ($sdProcess) {
    try {
        $sdProcess | Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        Write-Host "  Stream Deck process terminated." -ForegroundColor Green
    } catch {
        Write-Warning "  Could not stop Stream Deck automatically. Please quit Stream Deck manually."
    }
} else {
    Write-Host "  Stream Deck is not currently running."
}

# 2. Determine source plugin directory
$pluginFolderName = "com.pineapplecola.darts.sdPlugin"
$resolvedSource = ""

if ($SourcePath -and (Test-Path -Path $SourcePath)) {
    if ((Get-Item $SourcePath) -is [System.IO.DirectoryInfo]) {
        if ((Get-Item $SourcePath).Name -eq $pluginFolderName) {
            $resolvedSource = (Resolve-Path $SourcePath).Path
        } elseif (Test-Path (Join-Path $SourcePath $pluginFolderName)) {
            $resolvedSource = (Resolve-Path (Join-Path $SourcePath $pluginFolderName)).Path
        }
    } elseif ($SourcePath.EndsWith(".streamDeckPlugin", [System.StringComparison]::OrdinalIgnoreCase) -or $SourcePath.EndsWith(".zip", [System.StringComparison]::OrdinalIgnoreCase)) {
        $extractDir = Join-Path $env:TEMP "darts-manual-install"
        Remove-Item -Recurse -Force $extractDir -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Path $extractDir -Force | Out-Null
        Write-Host "  Extracting plugin package '$SourcePath'..."
        Expand-Archive -Path $SourcePath -DestinationPath $extractDir -Force
        if (Test-Path (Join-Path $extractDir $pluginFolderName)) {
            $resolvedSource = Join-Path $extractDir $pluginFolderName
        }
    }
}

if (-not $resolvedSource) {
    # Default: look relative to script root (e.g. DARTS/streamdeck/plugin/com.pineapplecola.darts.sdPlugin)
    $candidate = Join-Path $PSScriptRoot "..\$pluginFolderName"
    if (Test-Path $candidate) {
        $resolvedSource = (Resolve-Path $candidate).Path
    } else {
        # Check dist package
        $distPkg = Join-Path $PSScriptRoot "..\dist\com.pineapplecola.darts.streamDeckPlugin"
        if (Test-Path $distPkg) {
            $extractDir = Join-Path $env:TEMP "darts-manual-install"
            Remove-Item -Recurse -Force $extractDir -ErrorAction SilentlyContinue
            New-Item -ItemType Directory -Path $extractDir -Force | Out-Null
            Write-Host "  Extracting bundled package '$distPkg'..."
            Expand-Archive -Path $distPkg -DestinationPath $extractDir -Force
            if (Test-Path (Join-Path $extractDir $pluginFolderName)) {
                $resolvedSource = Join-Path $extractDir $pluginFolderName
            }
        }
    }
}

if (-not $resolvedSource -or -not (Test-Path (Join-Path $resolvedSource "manifest.json"))) {
    Write-Error "Could not locate valid source folder '$pluginFolderName' containing manifest.json. Specify -SourcePath."
    return
}

Write-Host "Step 2: Source verified at: $resolvedSource" -ForegroundColor Green

# 3. Target destination in %APPDATA%
if (-not $env:APPDATA) {
    Write-Error "Environment variable APPDATA is not defined."
    return
}
$pluginsDir = Join-Path $env:APPDATA "Elgato\StreamDeck\Plugins"
if (-not (Test-Path $pluginsDir)) {
    New-Item -ItemType Directory -Path $pluginsDir -Force | Out-Null
}

$destination = Join-Path $pluginsDir $pluginFolderName
Write-Host "Step 3: Installing into $destination..."

if (Test-Path $destination) {
    Write-Host "  Removing previous installation in $destination..."
    Remove-Item -Recurse -Force $destination -ErrorAction SilentlyContinue
}

Copy-Item -Path $resolvedSource -Destination $destination -Recurse -Force

if (Test-Path (Join-Path $destination "manifest.json")) {
    Write-Host "  Plugin files successfully copied." -ForegroundColor Green
} else {
    Write-Error "Failed to install plugin files to $destination."
    return
}

# 4. Clear import cache if present
if ($env:LOCALAPPDATA) {
    $tempCache = Join-Path $env:LOCALAPPDATA "Temp\com.elgato.streamdeck"
    if (Test-Path $tempCache -ErrorAction SilentlyContinue) {
        Write-Host "Step 4: Clearing Stream Deck import cache..."
        Remove-Item -Recurse -Force $tempCache -ErrorAction SilentlyContinue
    }
}

# 5. Restart Stream Deck
Write-Host "Step 5: Restarting Stream Deck..."
$sdExePaths = @(
    "$env:ProgramFiles\Elgato\StreamDeck\StreamDeck.exe",
    "${env:ProgramFiles(x86)}\Elgato\StreamDeck\StreamDeck.exe",
    "C:\Program Files\Elgato\StreamDeck\StreamDeck.exe"
)

$started = $false
foreach ($exe in $sdExePaths) {
    if ($exe -and (Test-Path $exe)) {
        Write-Host "  Launching $exe..."
        Start-Process -FilePath $exe
        $started = $true
        break
    }
}

if (-not $started) {
    Write-Host "  Could not find StreamDeck.exe automatically. Please launch the Stream Deck app from the Start menu." -ForegroundColor Yellow
} else {
    Write-Host "  Stream Deck launched." -ForegroundColor Green
}

Write-Host "`nInstall completed successfully!" -ForegroundColor Green
Write-Host "You should now see the 'DARTS' category in the Stream Deck actions list."
