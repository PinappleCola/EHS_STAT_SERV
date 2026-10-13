<#
.SYNOPSIS
    Reports diagnostic and authoritative status for the DARTS dev workflow.
.DESCRIPTION
    Shows the authoritative repository location, active Git branch/commit,
    currently deployed Stream Deck plugin details, available backups, and scans
    for duplicate or misplaced plugin copies (such as stray copies in Program Files).
.PARAMETER RepoRoot
    Optional path to repository root. If omitted, uses current directory or saved config.
.PARAMETER NoScan
    Skip scanning for duplicate or confusing plugin folders.
#>

[CmdletBinding()]
param(
    [string]$RepoRoot,
    [switch]$NoScan
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptDir "dev-workflow-common.ps1")

$root = if ($RepoRoot) { $RepoRoot } else { Find-RepoRoot -StartingDirectory (Get-Location).Path }
if (-not $root) {
    Write-Host "ERROR: Could not locate EHS_STAT_SERV repository root." -ForegroundColor Red
    Write-Host "Run '.\tools\setup-dev.ps1' to initialize configuration." -ForegroundColor Yellow
    exit 1
}

$config = Get-DevWorkflowConfig -RepoRoot $root
if (-not $config) {
    Write-Host "Dev workflow configuration not found in $root." -ForegroundColor Yellow
    Write-Host "Creating default configuration now..." -ForegroundColor Cyan
    $config = Set-DevWorkflowConfig -RepoRoot $root
}

$status = Get-DevWorkflowStatus -Config $config -ScanConfusingFolders:(-not $NoScan)

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "           DARTS Dev Workflow & Diagnostic Status           " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Authoritative Repository
Write-Host "1. Authoritative Repository:" -ForegroundColor White
Write-Host "   Path        : $($status.AuthoritativeRepoRoot)" -ForegroundColor Green
Write-Host "   Git Branch  : $($status.GitBranch)"
Write-Host "   Git Commit  : $($status.GitCommit)"
Write-Host "   Clean/Dirty : $(if ($status.GitDirty) { 'DIRTY (uncommitted changes exist)' } else { 'CLEAN' })" -ForegroundColor $(if ($status.GitDirty) { 'Yellow' } else { 'Green' })
if ($status.GitRemote -ne "UNKNOWN") {
    Write-Host "   Remote URL  : $($status.GitRemote)"
}
Write-Host ""

# 2. Deployed Stream Deck Plugin
Write-Host "2. Deployed Stream Deck Plugin:" -ForegroundColor White
Write-Host "   Target Path : $($status.DeployedPluginPath)"
if ($status.DeployedPluginInstalled) {
    Write-Host "   Status      : INSTALLED" -ForegroundColor Green
    Write-Host "   Manifest Ver: $($status.DeployedVersion)"
    Write-Host "   Binary SHA256: $($status.DeployedBinarySha256)"
    Write-Host "   Binary Date : $($status.DeployedBinaryDate)"
}
else {
    Write-Host "   Status      : NOT DEPLOYED YET" -ForegroundColor Yellow
}
Write-Host ""

# 3. Backups & Rollback
Write-Host "3. Backups & Rollback:" -ForegroundColor White
Write-Host "   Backup Dir  : $($status.BackupDirectory)"
Write-Host "   Saved Count : $($status.BackupCount)"
Write-Host "   Last Known  : $(if ($status.HasLastKnownGood) { 'READY (last-known-good available)' } else { 'None yet' })" -ForegroundColor $(if ($status.HasLastKnownGood) { 'Green' } else { 'DarkGray' })
Write-Host "   Latest Backup: $($status.LatestBackup)"
Write-Host ""

# 4. Last Recorded Run
Write-Host "4. Last Test / Deploy Run:" -ForegroundColor White
if ($status.LastRun) {
    Write-Host "   Timestamp   : $($status.LastRun.timestamp)"
    Write-Host "   Commit      : $($status.LastRun.commit)"
    Write-Host "   Branch      : $($status.LastRun.branch)"
    Write-Host "   Test Passed : $($status.LastRun.testPassed)" -ForegroundColor $(if ($status.LastRun.testPassed) { 'Green' } else { 'Red' })
    Write-Host "   Deployed    : $($status.LastRun.deployed)"
}
else {
    Write-Host "   No run records yet. Run '.\tools\test-commit.ps1' to test." -ForegroundColor DarkGray
}
Write-Host ""

# 5. Diagnostic: Duplicate / Confusing Folder Scan
Write-Host "5. Diagnostic Folder Scan:" -ForegroundColor White
if ($status.ConfusingLocations.Count -eq 0) {
    Write-Host "   Clean: No confusing or duplicate plugin installations detected." -ForegroundColor Green
}
else {
    Write-Host "   ATTENTION: Confusing or duplicate folders detected!" -ForegroundColor Yellow
    foreach ($item in $status.ConfusingLocations) {
        $color = if ($item.Severity -eq "Critical") { 'Red' } else { 'Yellow' }
        Write-Host "   - [$($item.Severity)] $($item.Category):" -ForegroundColor $color
        Write-Host "       Location: $($item.Location)"
        Write-Host "       Note    : $($item.Note)"
    }
    Write-Host ""
    Write-Host "   Safety Note: The helper does NOT automatically delete or move these folders." -ForegroundColor Cyan
    Write-Host "   Review the paths above to avoid confusion between different local copies."
}

Write-Host "============================================================" -ForegroundColor Cyan
