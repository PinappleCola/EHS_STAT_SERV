<#
.SYNOPSIS
    Shared functions for the Windows-focused DARTS dev and testing workflow.
.DESCRIPTION
    Provides helper functions for repository detection, config management,
    testing, building, backing up, deploying, rolling back, and diagnosing
    Stream Deck plugin installations. Compatible with PowerShell 5.1 and 7+.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-PathCombine {
    param(
        [Parameter(Mandatory = $true)][string[]]$Paths
    )
    return [System.IO.Path]::Combine($Paths)
}

function Find-RepoRoot {
    param(
        [string]$StartingDirectory = (Get-Location).Path
    )

    $current = [System.IO.Path]::GetFullPath($StartingDirectory)
    while ($current) {
        $markerDarts = Get-PathCombine @($current, "DARTS", "darts.py")
        $markerManifest = Get-PathCombine @($current, "DARTS", "streamdeck", "plugin", "com.pineapplecola.darts.sdPlugin", "manifest.json")
        if ((Test-Path -LiteralPath $markerDarts) -and (Test-Path -LiteralPath $markerManifest)) {
            return $current
        }
        $parent = [System.IO.Path]::GetDirectoryName($current)
        if ($parent -eq $current) { break }
        $current = $parent
    }
    return $null
}

function Test-IsAuthoritativeRepo {
    param(
        [Parameter(Mandatory = $true)][string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        return @{
            IsValid = $false
            Reason = "Folder does not exist or is not a directory: $Path"
        }
    }

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $markerDarts = Get-PathCombine @($fullPath, "DARTS", "darts.py")
    $markerManifest = Get-PathCombine @($fullPath, "DARTS", "streamdeck", "plugin", "com.pineapplecola.darts.sdPlugin", "manifest.json")

    if (-not (Test-Path -LiteralPath $markerDarts)) {
        return @{
            IsValid = $false
            Reason = "Missing DARTS/darts.py. Not a valid EHS_STAT_SERV repository."
        }
    }

    if (-not (Test-Path -LiteralPath $markerManifest)) {
        return @{
            IsValid = $false
            Reason = "Missing DARTS Stream Deck manifest. Not a valid EHS_STAT_SERV repository."
        }
    }

    # Verify manifest UUID matches com.pineapplecola.darts
    try {
        $manifestContent = Get-Content -LiteralPath $markerManifest -Raw -Encoding utf8 | ConvertFrom-Json
        if ($manifestContent.UUID -ne "com.pineapplecola.darts") {
            return @{
                IsValid = $false
                Reason = "Manifest UUID is '$($manifestContent.UUID)', expected 'com.pineapplecola.darts'."
            }
        }
    }
    catch {
        return @{
            IsValid = $false
            Reason = "Failed to parse DARTS Stream Deck manifest.json: $_"
        }
    }

    return @{
        IsValid = $true
        Path = $fullPath
        Reason = "Valid authoritative repository structure verified."
    }
}

function Get-DefaultDeployPath {
    if ($env:APPDATA) {
        return Get-PathCombine @($env:APPDATA, "Elgato", "StreamDeck", "Plugins", "com.pineapplecola.darts.sdPlugin")
    }
    elseif ($env:USERPROFILE) {
        return Get-PathCombine @($env:USERPROFILE, "AppData", "Roaming", "Elgato", "StreamDeck", "Plugins", "com.pineapplecola.darts.sdPlugin")
    }
    elseif ($env:HOME) {
        # Fallback for non-Windows test environments
        return Get-PathCombine @($env:HOME, ".local", "share", "Elgato", "StreamDeck", "Plugins", "com.pineapplecola.darts.sdPlugin")
    }
    else {
        return Get-PathCombine @([System.IO.Path]::GetTempPath(), "Elgato", "StreamDeck", "Plugins", "com.pineapplecola.darts.sdPlugin")
    }
}

function Get-DefaultBackupPath {
    if ($env:USERPROFILE) {
        return Get-PathCombine @($env:USERPROFILE, ".darts-dev-backups")
    }
    elseif ($env:HOME) {
        return Get-PathCombine @($env:HOME, ".darts-dev-backups")
    }
    else {
        return Get-PathCombine @([System.IO.Path]::GetTempPath(), ".darts-dev-backups")
    }
}

function Get-ConfigFilePath {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )
    return Get-PathCombine @($RepoRoot, ".dev-workflow.local.json")
}

function Get-DevWorkflowConfig {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )

    $configFile = Get-ConfigFilePath -RepoRoot $RepoRoot
    if (-not (Test-Path -LiteralPath $configFile)) {
        return $null
    }

    try {
        $json = Get-Content -LiteralPath $configFile -Raw -Encoding utf8 | ConvertFrom-Json
        return $json
    }
    catch {
        Write-Warning "Could not parse config file at ${configFile}: $_"
        return $null
    }
}

function Set-DevWorkflowConfig {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [string]$DeployPath,
        [string]$BackupDir
    )

    $resolvedRepo = [System.IO.Path]::GetFullPath($RepoRoot)
    $validation = Test-IsAuthoritativeRepo -Path $resolvedRepo
    if (-not $validation.IsValid) {
        throw "Cannot save config: $($validation.Reason)"
    }

    if (-not $DeployPath) {
        $DeployPath = Get-DefaultDeployPath
    }
    if (-not $BackupDir) {
        $BackupDir = Get-DefaultBackupPath
    }

    $resolvedDeploy = [System.IO.Path]::GetFullPath($DeployPath)
    $resolvedBackup = [System.IO.Path]::GetFullPath($BackupDir)
    $dartsRoot = Get-PathCombine @($resolvedRepo, "DARTS")
    $pluginSource = Get-PathCombine @($dartsRoot, "streamdeck", "plugin", "com.pineapplecola.darts.sdPlugin")
    $historyFile = Get-PathCombine @($resolvedBackup, "run-history.json")

    $configObj = [ordered]@{
        "schemaVersion" = "1.0"
        "repository" = "PinappleCola/EHS_STAT_SERV"
        "sourceRoot" = $resolvedRepo
        "dartsRoot" = $dartsRoot
        "streamDeckPluginSource" = $pluginSource
        "streamDeckPluginDeployPath" = $resolvedDeploy
        "backupDirectory" = $resolvedBackup
        "historyFile" = $historyFile
        "updatedAt" = (Get-Date -Format "o")
    }

    $configFile = Get-ConfigFilePath -RepoRoot $resolvedRepo
    $jsonContent = $configObj | ConvertTo-Json -Depth 5
    Set-Content -LiteralPath $configFile -Value $jsonContent -Encoding utf8

    # Ensure backup directory exists
    if (-not (Test-Path -LiteralPath $resolvedBackup)) {
        New-Item -ItemType Directory -Path $resolvedBackup -Force | Out-Null
    }

    return (Get-Content -LiteralPath $configFile -Raw -Encoding utf8 | ConvertFrom-Json)
}

function Get-GitInfo {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )

    $info = @{
        IsGit = $false
        Branch = "UNKNOWN"
        Commit = "UNKNOWN"
        ShortCommit = "UNKNOWN"
        IsDirty = $false
        RemoteUrl = "UNKNOWN"
    }

    try {
        $insideGit = (git -C $RepoRoot rev-parse --is-inside-work-tree 2>$null)
        if ($insideGit -eq "true") {
            $info.IsGit = $true
            $commit = (git -C $RepoRoot rev-parse HEAD 2>$null)
            if ($commit) {
                $info.Commit = $commit.Trim()
                $info.ShortCommit = $info.Commit.Substring(0, [System.Math]::Min(7, $info.Commit.Length))
            }

            $branch = (git -C $RepoRoot rev-parse --abbrev-ref HEAD 2>$null)
            if ($branch) {
                $info.Branch = $branch.Trim()
            }

            $status = (git -C $RepoRoot status --porcelain 2>$null)
            if ($status) {
                $info.IsDirty = $true
            }

            $remote = (git -C $RepoRoot remote get-url origin 2>$null)
            if ($remote) {
                $info.RemoteUrl = $remote.Trim()
            }
        }
    }
    catch {
        # git command not found or not a git repository
    }

    return $info
}

function Checkout-GitTarget {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Target,
        [switch]$Force
    )

    $gitInfo = Get-GitInfo -RepoRoot $RepoRoot
    if (-not $gitInfo.IsGit) {
        throw "Cannot checkout target '$Target': $RepoRoot is not recognized as a Git repository."
    }

    if ($gitInfo.IsDirty -and -not $Force) {
        throw "Repository has uncommitted changes in '$RepoRoot'. Commit or stash your changes before switching to '$Target', or supply -Force to bypass."
    }

    Write-Host "[git] Checking out '$Target' in $RepoRoot..." -ForegroundColor Cyan
    $checkoutOutput = git -C $RepoRoot checkout $Target 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git checkout failed: $checkoutOutput"
    }

    $updatedInfo = Get-GitInfo -RepoRoot $RepoRoot
    Write-Host "[git] Now at branch '$($updatedInfo.Branch)', commit $($updatedInfo.ShortCommit)." -ForegroundColor Green
    return $updatedInfo
}

function Get-StreamDeckProcesses {
    try {
        @(Get-Process -Name "StreamDeck" -ErrorAction SilentlyContinue)
    }
    catch {
        @()
    }
}

function Stop-StreamDeckSafe {
    param(
        [switch]$NonInteractive,
        [switch]$Force
    )

    $procs = @(Get-StreamDeckProcesses)
    if ($procs.Length -eq 0) {
        return $true
    }

    Write-Host "[process] StreamDeck is currently running (PID(s): $($procs.Id -join ', '))." -ForegroundColor Yellow

    $shouldStop = $false
    if ($Force -or $NonInteractive) {
        $shouldStop = $true
    }
    else {
        $answer = Read-Host "Stream Deck must be closed to safely update/restore plugin binaries without file locking. Close Stream Deck now? [Y/n]"
        if ([string]::IsNullOrWhiteSpace($answer) -or $answer.Trim().ToLower() -eq 'y') {
            $shouldStop = $true
        }
    }

    if ($shouldStop) {
        Write-Host "[process] Closing Stream Deck..." -ForegroundColor Yellow
        foreach ($p in $procs) {
            try {
                Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            }
            catch {}
        }
        Start-Sleep -Seconds 1
        $remaining = @(Get-StreamDeckProcesses)
        if ($remaining.Length -gt 0) {
            Write-Warning "Could not terminate all StreamDeck processes. Deployed files may be locked."
            return $false
        }
        Write-Host "[process] Stream Deck closed successfully." -ForegroundColor Green
        return $true
    }
    else {
        Write-Warning "User chose not to close Stream Deck. Deployed files may be locked by Windows."
        return $false
    }
}

function Start-StreamDeckSafe {
    param(
        [switch]$NonInteractive
    )

    if ($NonInteractive) {
        Write-Host "[process] Non-interactive mode; skipping automatic Stream Deck launch." -ForegroundColor DarkGray
        return
    }

    $exeCandidates = @()
    if ($env:ProgramFiles) {
        $exeCandidates += (Get-PathCombine @($env:ProgramFiles, "Elgato", "StreamDeck", "StreamDeck.exe"))
    }
    $progFilesX86 = ${env:ProgramFiles(x86)}
    if ($progFilesX86) {
        $exeCandidates += (Get-PathCombine @($progFilesX86, "Elgato", "StreamDeck", "StreamDeck.exe"))
    }

    $foundExe = $exeCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1

    if ($foundExe) {
        $answer = Read-Host "Would you like to start Stream Deck now? [Y/n]"
        if ([string]::IsNullOrWhiteSpace($answer) -or $answer.Trim().ToLower() -eq 'y') {
            Write-Host "[process] Launching Stream Deck from $foundExe..." -ForegroundColor Cyan
            Start-Process -FilePath $foundExe
        }
    }
    else {
        Write-Host "[process] StreamDeck.exe was not found in standard Program Files locations. Please launch Stream Deck manually." -ForegroundColor Cyan
    }
}

function Invoke-PluginTests {
    param(
        [Parameter(Mandatory = $true)]$Config
    )

    $results = @{
        Passed = $true
        ExecutedTests = @()
        Errors = @()
    }

    $nodeCmd = Get-Command "node" -ErrorAction SilentlyContinue
    if (-not $nodeCmd) {
        $results.Passed = $false
        $results.Errors += "Node.js was not found in PATH. Required to run regression tests."
        return $results
    }

    $testsToRun = @(
        @{ Name = "Stream Deck Plugin Regression"; Script = Get-PathCombine @($Config.dartsRoot, "tests", "streamdeck_plugin_regression.test.js") },
        @{ Name = "UI Commands Regression"; Script = Get-PathCombine @($Config.dartsRoot, "tests", "ui_commands_regression.test.js") },
        @{ Name = "Export 3D Regression"; Script = Get-PathCombine @($Config.dartsRoot, "tests", "export3d_regression.test.js") },
        @{ Name = "Map Sources Regression"; Script = Get-PathCombine @($Config.dartsRoot, "tests", "map_sources_regression.test.js") },
        @{ Name = "Sound Playback Regression"; Script = Get-PathCombine @($Config.dartsRoot, "tests", "sound_playback_regression.test.js") },
        @{ Name = "Trail Logic Regression"; Script = Get-PathCombine @($Config.dartsRoot, "tests", "trail_logic_regression.test.js") }
    )

    foreach ($t in $testsToRun) {
        if (Test-Path -LiteralPath $t.Script) {
            Write-Host "[test] Running $($t.Name)..." -ForegroundColor Cyan
            $output = & node $t.Script 2>&1
            $exitCode = $LASTEXITCODE
            if ($exitCode -eq 0) {
                Write-Host "  PASS: $($t.Name)" -ForegroundColor Green
                $results.ExecutedTests += @{ Name = $t.Name; Status = "PASS" }
            }
            else {
                Write-Host "  FAIL: $($t.Name) (Exit code: $exitCode)" -ForegroundColor Red
                $results.Passed = $false
                $results.ExecutedTests += @{ Name = $t.Name; Status = "FAIL"; Output = "$output" }
                $results.Errors += "$($t.Name) failed: $output"
            }
        }
    }

    return $results
}

function Invoke-PluginBuild {
    param(
        [Parameter(Mandatory = $true)]$Config
    )

    $buildScript = Get-PathCombine @($Config.dartsRoot, "streamdeck", "plugin", "build.js")
    if (-not (Test-Path -LiteralPath $buildScript)) {
        return @{
            Success = $false
            Error = "build.js not found at $buildScript"
        }
    }

    $goCmd = Get-Command "go" -ErrorAction SilentlyContinue
    if (-not $goCmd) {
        Write-Warning "Go toolchain ('go') not found in PATH. Existing prebuilt binaries in bin/ will be used."
        return @{
            Success = $true
            Skipped = $true
            Reason = "Go compiler not found; prebuilt binaries retained."
        }
    }

    Write-Host "[build] Building Stream Deck native binaries via node build.js..." -ForegroundColor Cyan
    $output = & node $buildScript 2>&1
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        Write-Host "[build] Build succeeded." -ForegroundColor Green
        return @{
            Success = $true
            Output = "$output"
        }
    }
    else {
        Write-Host "[build] Build failed (exit code $exitCode)." -ForegroundColor Red
        return @{
            Success = $false
            Error = "Build failed: $output"
        }
    }
}

function Get-FileSha256 {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath
    )
    if (-not (Test-Path -LiteralPath $FilePath)) {
        return $null
    }
    try {
        $hashObj = Get-FileHash -LiteralPath $FilePath -Algorithm SHA256
        return $hashObj.Hash
    }
    catch {
        return $null
    }
}

function Backup-DeployedPlugin {
    param(
        [Parameter(Mandatory = $true)]$Config,
        [string]$Label = "Pre-deploy backup"
    )

    $deployPath = $Config.streamDeckPluginDeployPath
    if (-not (Test-Path -LiteralPath $deployPath -PathType Container)) {
        return @{
            Created = $false
            Reason = "Deployed plugin path does not exist yet. Nothing to back up."
        }
    }

    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backupDir = $Config.backupDirectory
    if (-not (Test-Path -LiteralPath $backupDir)) {
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    }

    $destFolder = Get-PathCombine @($backupDir, "backup-$timestamp")
    New-Item -ItemType Directory -Path $destFolder -Force | Out-Null

    Copy-Item -Path (Join-Path $deployPath "*") -Destination $destFolder -Recurse -Force

    # Metadata
    $exePath = Get-PathCombine @($destFolder, "bin", "darts-plugin.exe")
    $exeHash = if (Test-Path -LiteralPath $exePath) { Get-FileSha256 -FilePath $exePath } else { $null }

    $meta = [ordered]@{
        "timestamp" = (Get-Date -Format "o")
        "label" = $Label
        "sourceDeployPath" = $deployPath
        "backupFolder" = $destFolder
        "exeSha256" = $exeHash
    }
    $metaJson = $meta | ConvertTo-Json -Depth 4
    Set-Content -LiteralPath (Get-PathCombine @($destFolder, "backup-meta.json")) -Value $metaJson -Encoding utf8

    # Also maintain a 'last-known-good' copy
    $lkgFolder = Get-PathCombine @($backupDir, "last-known-good")
    if (Test-Path -LiteralPath $lkgFolder) {
        Remove-Item -LiteralPath $lkgFolder -Recurse -Force
    }
    New-Item -ItemType Directory -Path $lkgFolder -Force | Out-Null
    Copy-Item -Path (Join-Path $destFolder "*") -Destination $lkgFolder -Recurse -Force

    Write-Host "[backup] Saved backup to: $destFolder" -ForegroundColor Green
    return @{
        Created = $true
        BackupPath = $destFolder
        LastKnownGoodPath = $lkgFolder
        Timestamp = $timestamp
    }
}

function Deploy-PluginFiles {
    param(
        [Parameter(Mandatory = $true)]$Config,
        [switch]$NonInteractive,
        [switch]$Force
    )

    $source = $Config.streamDeckPluginSource
    $dest = $Config.streamDeckPluginDeployPath

    if (-not (Test-Path -LiteralPath $source -PathType Container)) {
        throw "Source plugin directory does not exist: $source"
    }

    $srcManifest = Get-PathCombine @($source, "manifest.json")
    if (-not (Test-Path -LiteralPath $srcManifest)) {
        throw "Source manifest.json not found at $srcManifest"
    }

    # Verify binary exists
    $winExe = Get-PathCombine @($source, "bin", "darts-plugin.exe")
    if (-not (Test-Path -LiteralPath $winExe)) {
        throw "Windows plugin binary not found at $winExe. Please run build first."
    }

    # Stop Stream Deck if running
    $stopped = Stop-StreamDeckSafe -NonInteractive:$NonInteractive -Force:$Force
    if (-not $stopped -and -not $Force) {
        throw "Cannot safely deploy while Stream Deck is running and locks files."
    }

    # Backup existing deployment if present
    $backupResult = Backup-DeployedPlugin -Config $Config -Label "Pre-deploy backup"

    # Create destination parent if missing
    $destParent = [System.IO.Path]::GetDirectoryName($dest)
    if (-not (Test-Path -LiteralPath $destParent)) {
        New-Item -ItemType Directory -Path $destParent -Force | Out-Null
    }

    # Create destination folder if missing
    if (-not (Test-Path -LiteralPath $dest)) {
        New-Item -ItemType Directory -Path $dest -Force | Out-Null
    }

    Write-Host "[deploy] Deploying plugin files from $source to $dest..." -ForegroundColor Cyan
    Copy-Item -Path (Join-Path $source "*") -Destination $dest -Recurse -Force

    $deployedExe = Get-PathCombine @($dest, "bin", "darts-plugin.exe")
    $deployedHash = Get-FileSha256 -FilePath $deployedExe

    Write-Host "[deploy] Deployment complete." -ForegroundColor Green
    Write-Host "  Destination : $dest"
    Write-Host "  Binary SHA256: $deployedHash"

    return @{
        Success = $true
        DeployedPath = $dest
        BinarySha256 = $deployedHash
        BackupInfo = $backupResult
    }
}

function Restore-PluginBackup {
    param(
        [Parameter(Mandatory = $true)]$Config,
        [string]$BackupName,
        [switch]$NonInteractive,
        [switch]$Force
    )

    $backupDir = $Config.backupDirectory
    if (-not (Test-Path -LiteralPath $backupDir -PathType Container)) {
        throw "Backup directory does not exist: $backupDir. No backups available to restore."
    }

    $targetBackupFolder = $null
    if ($BackupName) {
        $candidate = Get-PathCombine @($backupDir, $BackupName)
        if (Test-Path -LiteralPath $candidate -PathType Container) {
            $targetBackupFolder = $candidate
        }
        else {
            throw "Specified backup folder '$BackupName' was not found in $backupDir."
        }
    }
    else {
        # Check last-known-good first, otherwise latest backup- folder
        $lkg = Get-PathCombine @($backupDir, "last-known-good")
        if (Test-Path -LiteralPath $lkg -PathType Container) {
            $targetBackupFolder = $lkg
        }
        else {
            $backups = @(Get-ChildItem -LiteralPath $backupDir -Directory -Filter "backup-*" | Sort-Object Name -Descending)
            if ($backups.Length -gt 0) {
                $targetBackupFolder = $backups[0].FullName
            }
        }
    }

    if (-not $targetBackupFolder) {
        throw "No valid backups found in $backupDir."
    }

    Write-Host "[rollback] Restoring from: $targetBackupFolder" -ForegroundColor Cyan

    # Safety check on Stream Deck
    $stopped = Stop-StreamDeckSafe -NonInteractive:$NonInteractive -Force:$Force
    if (-not $stopped -and -not $Force) {
        throw "Cannot restore while Stream Deck is running and locks files."
    }

    $dest = $Config.streamDeckPluginDeployPath
    if (-not (Test-Path -LiteralPath $dest)) {
        New-Item -ItemType Directory -Path $dest -Force | Out-Null
    }

    Copy-Item -Path (Join-Path $targetBackupFolder "*") -Destination $dest -Recurse -Force

    $exePath = Get-PathCombine @($dest, "bin", "darts-plugin.exe")
    $exeHash = if (Test-Path -LiteralPath $exePath) { Get-FileSha256 -FilePath $exePath } else { $null }

    Write-Host "[rollback] Successfully restored backup to $dest." -ForegroundColor Green
    if ($exeHash) {
        Write-Host "  Restored Binary SHA256: $exeHash"
    }

    return @{
        Success = $true
        RestoredFrom = $targetBackupFolder
        Destination = $dest
        BinarySha256 = $exeHash
    }
}

function Write-RunRecord {
    param(
        [Parameter(Mandatory = $true)]$Config,
        [Parameter(Mandatory = $true)][hashtable]$Record
    )

    $historyFile = $Config.historyFile
    $records = @()
    if (Test-Path -LiteralPath $historyFile) {
        try {
            $existing = Get-Content -LiteralPath $historyFile -Raw -Encoding utf8 | ConvertFrom-Json
            if ($null -ne $existing) {
                $records = @($existing)
            }
        }
        catch {
            $records = @()
        }
    }

    $records += $Record
    # Keep last 50 entries
    if ($records.Length -gt 50) {
        $records = $records[($records.Length - 50)..($records.Length - 1)]
    }

    $json = $records | ConvertTo-Json -Depth 6
    Set-Content -LiteralPath $historyFile -Value $json -Encoding utf8
}

function Get-DevWorkflowStatus {
    param(
        [Parameter(Mandatory = $true)]$Config,
        [switch]$ScanConfusingFolders
    )

    $gitInfo = Get-GitInfo -RepoRoot $Config.sourceRoot

    # Deployed status
    $deployPath = $Config.streamDeckPluginDeployPath
    $deployExists = Test-Path -LiteralPath $deployPath -PathType Container
    $deployedManifest = $null
    $deployedExeHash = $null
    $deployedExeDate = $null

    if ($deployExists) {
        $mPath = Get-PathCombine @($deployPath, "manifest.json")
        if (Test-Path -LiteralPath $mPath) {
            try {
                $deployedManifest = Get-Content -LiteralPath $mPath -Raw -Encoding utf8 | ConvertFrom-Json
            }
            catch {}
        }
        $exePath = Get-PathCombine @($deployPath, "bin", "darts-plugin.exe")
        if (Test-Path -LiteralPath $exePath) {
            $deployedExeHash = Get-FileSha256 -FilePath $exePath
            $deployedExeDate = (Get-Item -LiteralPath $exePath).LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
        }
    }

    # Backup status
    $backupDir = $Config.backupDirectory
    $backupExists = Test-Path -LiteralPath $backupDir -PathType Container
    $backupCount = 0
    $hasLastKnownGood = $false
    $latestBackup = $null

    if ($backupExists) {
        $bFolders = @(Get-ChildItem -LiteralPath $backupDir -Directory -Filter "backup-*" | Sort-Object Name -Descending)
        $backupCount = $bFolders.Length
        if ($backupCount -gt 0) {
            $latestBackup = $bFolders[0].Name
        }
        $lkgPath = Get-PathCombine @($backupDir, "last-known-good")
        $hasLastKnownGood = Test-Path -LiteralPath $lkgPath -PathType Container
    }

    # Confusing / Duplicate locations scan
    $confusingLocations = @()
    if ($ScanConfusingFolders) {
        # 1. Check parent of deployPath for duplicate or misnamed plugin folders
        $deployParent = [System.IO.Path]::GetDirectoryName($deployPath)
        if ($deployParent -and (Test-Path -LiteralPath $deployParent -PathType Container)) {
            $siblingDirs = Get-ChildItem -LiteralPath $deployParent -Directory
            foreach ($s in $siblingDirs) {
                if ($s.FullName -ne $deployPath) {
                    if ($s.Name -match "darts" -or $s.Name -match "pineapplecola") {
                        $confusingLocations += @{
                            Location = $s.FullName
                            Category = "Duplicate in StreamDeck AppData Plugins"
                            Severity = "Warning"
                            Note = "Duplicate or alternative DARTS plugin folder found. Only '$deployPath' is authoritative."
                        }
                    }
                }
            }
        }

        # 2. Check Program Files for stray plugins (Stream Deck plugins should NEVER live in Program Files)
        $progDirs = @()
        if ($env:ProgramFiles) {
            $progDirs += (Get-PathCombine @($env:ProgramFiles, "Elgato", "StreamDeck", "Plugins"))
        }
        $progFilesX86 = ${env:ProgramFiles(x86)}
        if ($progFilesX86) {
            $progDirs += (Get-PathCombine @($progFilesX86, "Elgato", "StreamDeck", "Plugins"))
        }
        foreach ($pd in $progDirs) {
            if ($pd -and (Test-Path -LiteralPath $pd -PathType Container)) {
                $matches = Get-ChildItem -LiteralPath $pd -Directory -Filter "*darts*" -ErrorAction SilentlyContinue
                foreach ($m in $matches) {
                    $confusingLocations += @{
                        Location = $m.FullName
                        Category = "Invalid Plugin in Program Files"
                        Severity = "Critical"
                        Note = "Stream Deck plugins must never be placed in Program Files. Remove or ignore this folder."
                    }
                }
            }
        }
    }

    # Last run record
    $lastRecord = $null
    if (Test-Path -LiteralPath $Config.historyFile) {
        try {
            $history = Get-Content -LiteralPath $Config.historyFile -Raw -Encoding utf8 | ConvertFrom-Json
            if ($history -is [System.Collections.IEnumerable] -and $history.Count -gt 0) {
                $lastRecord = $history[-1]
            }
            elseif ($history) {
                $lastRecord = $history
            }
        }
        catch {}
    }

    return [ordered]@{
        AuthoritativeRepoRoot = $Config.sourceRoot
        RepoExists = Test-Path -LiteralPath $Config.sourceRoot -PathType Container
        GitBranch = $gitInfo.Branch
        GitCommit = $gitInfo.Commit
        GitShortCommit = $gitInfo.ShortCommit
        GitDirty = $gitInfo.IsDirty
        GitRemote = $gitInfo.RemoteUrl
        DeployedPluginPath = $deployPath
        DeployedPluginInstalled = $deployExists
        DeployedVersion = if ($deployedManifest) { $deployedManifest.Version } else { "N/A" }
        DeployedBinarySha256 = if ($deployedExeHash) { $deployedExeHash } else { "N/A" }
        DeployedBinaryDate = if ($deployedExeDate) { $deployedExeDate } else { "N/A" }
        BackupDirectory = $backupDir
        BackupCount = $backupCount
        HasLastKnownGood = $hasLastKnownGood
        LatestBackup = if ($latestBackup) { $latestBackup } else { "None" }
        LastRun = $lastRecord
        ConfusingLocations = $confusingLocations
    }
}
