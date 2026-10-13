<#
.SYNOPSIS
    Restores the Stream Deck plugin from a previous backup.
.DESCRIPTION
    Rolls back the deployed Stream Deck plugin to the last known good backup,
    or a specifically chosen backup folder from the dedicated backup directory.
.PARAMETER BackupName
    Optional specific backup folder name (e.g. backup-20261013-143000 or last-known-good).
.PARAMETER List
    List all available backups and exit.
.PARAMETER NonInteractive
    Skip interactive prompts.
.PARAMETER Force
    Force rollback without confirmation prompts.
#>

[CmdletBinding()]
param(
    [string]$BackupName,
    [switch]$List,
    [switch]$NonInteractive,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptDir "dev-workflow-common.ps1")

$repoRoot = Find-RepoRoot -StartingDirectory (Get-Location).Path
if (-not $repoRoot) {
    Write-Host "ERROR: Could not locate EHS_STAT_SERV repository root." -ForegroundColor Red
    exit 1
}

$config = Get-DevWorkflowConfig -RepoRoot $repoRoot
if (-not $config) {
    Write-Host "Config not found. Initializing default config..." -ForegroundColor Cyan
    $config = Set-DevWorkflowConfig -RepoRoot $repoRoot
}

$backupDir = $config.backupDirectory
if (-not (Test-Path -LiteralPath $backupDir -PathType Container)) {
    Write-Host "ERROR: Backup directory does not exist: $backupDir" -ForegroundColor Red
    Write-Host "No backups are available yet to restore." -ForegroundColor Yellow
    exit 1
}

$availableBackups = @(Get-ChildItem -LiteralPath $backupDir -Directory | Sort-Object Name -Descending)

if ($List) {
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "                 Available Backups                          " -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Backup Directory: $backupDir"
    Write-Host ""
    if ($availableBackups.Count -eq 0) {
        Write-Host "No backups found." -ForegroundColor DarkGray
    }
    else {
        foreach ($b in $availableBackups) {
            $metaFile = Join-Path $b.FullName "backup-meta.json"
            $metaDesc = ""
            if (Test-Path -LiteralPath $metaFile) {
                try {
                    $meta = Get-Content -LiteralPath $metaFile -Raw -Encoding utf8 | ConvertFrom-Json
                    $metaDesc = "[$($meta.label)] timestamp: $($meta.timestamp)"
                }
                catch {}
            }
            Write-Host "  $($b.Name)  $metaDesc" -ForegroundColor Green
        }
    }
    Write-Host "============================================================" -ForegroundColor Cyan
    exit 0
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "              Rollback Stream Deck Plugin                   " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

if (-not $NonInteractive -and -not $Force) {
    $targetDesc = if ($BackupName) { $BackupName } else { "last-known-good / latest backup" }
    $answer = Read-Host "Are you sure you want to restore the plugin from $targetDesc? [Y/n]"
    if (-not [string]::IsNullOrWhiteSpace($answer) -and $answer.Trim().ToLower() -ne 'y') {
        Write-Host "Rollback cancelled by user." -ForegroundColor Yellow
        exit 0
    }
}

try {
    $rollbackInfo = Restore-PluginBackup -Config $config -BackupName $BackupName -NonInteractive:$NonInteractive -Force:$Force
    Start-StreamDeckSafe -NonInteractive:$NonInteractive
}
catch {
    Write-Host "ERROR: Rollback failed: $_" -ForegroundColor Red
    exit 1
}

# Record rollback in run records
$gitInfo = Get-GitInfo -RepoRoot $config.sourceRoot
$runRecord = [ordered]@{
    "timestamp" = (Get-Date -Format "o")
    "action" = "rollback"
    "commit" = $gitInfo.Commit
    "shortCommit" = $gitInfo.ShortCommit
    "branch" = $gitInfo.Branch
    "restoredFrom" = $rollbackInfo.RestoredFrom
    "destination" = $rollbackInfo.Destination
    "binarySha256" = $rollbackInfo.BinarySha256
}
Write-RunRecord -Config $config -Record $runRecord

Write-Host ""
Write-Host "Rollback completed successfully." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
