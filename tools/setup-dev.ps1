<#
.SYNOPSIS
    One-time setup helper for Windows DARTS dev workflow.
.DESCRIPTION
    Detects or prompts for the authoritative repository root, validates the repository,
    and saves the paths to a local, Git-ignored configuration file (.dev-workflow.local.json).
.PARAMETER RepoRoot
    Optional path to the authoritative repository root. If omitted, detects current directory.
.PARAMETER DeployPath
    Optional path where Stream Deck plugin should be deployed. Defaults to %APPDATA%\Elgato\StreamDeck\Plugins\com.pineapplecola.darts.sdPlugin.
.PARAMETER BackupDir
    Optional path for external backups. Defaults to %USERPROFILE%\.darts-dev-backups.
.PARAMETER NonInteractive
    Skip interactive prompts.
#>

[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$DeployPath,
    [string]$BackupDir,
    [switch]$NonInteractive
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $scriptDir "dev-workflow-common.ps1")

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "       DARTS Windows Dev Workflow: One-Time Setup           " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "This helper establishes your authoritative repository folder"
Write-Host "and remembers plugin paths in a local, Git-ignored config file."
Write-Host ""

# 1. Resolve Repo Root
$detectedRepo = if ($RepoRoot) { $RepoRoot } else { Find-RepoRoot -StartingDirectory (Get-Location).Path }
if (-not $detectedRepo) {
    if ($NonInteractive) {
        throw "Could not automatically detect repository root. Please specify -RepoRoot."
    }
    Write-Host "Could not automatically detect repository root from current location." -ForegroundColor Yellow
    $detectedRepo = Read-Host "Enter the full path to your authoritative EHS_STAT_SERV folder"
}

if (-not $NonInteractive -and -not $RepoRoot) {
    Write-Host "Detected repository root:" -ForegroundColor White
    Write-Host "  $detectedRepo" -ForegroundColor Green
    $answer = Read-Host "Is this your single authoritative repository? [Y/n]"
    if (-not [string]::IsNullOrWhiteSpace($answer) -and $answer.Trim().ToLower() -ne 'y') {
        $detectedRepo = Read-Host "Enter the full path to your authoritative EHS_STAT_SERV folder"
    }
}

# 2. Validate authoritative repo
$validation = Test-IsAuthoritativeRepo -Path $detectedRepo
if (-not $validation.IsValid) {
    Write-Host "ERROR: Repository validation failed!" -ForegroundColor Red
    Write-Host "Reason: $($validation.Reason)" -ForegroundColor Red
    exit 1
}

# 3. Resolve Deploy & Backup Paths
if (-not $DeployPath) {
    $DeployPath = Get-DefaultDeployPath
}
if (-not $BackupDir) {
    $BackupDir = Get-DefaultBackupPath
}

if (-not $NonInteractive) {
    Write-Host ""
    Write-Host "Target Stream Deck plugin deployment path:" -ForegroundColor White
    Write-Host "  $DeployPath" -ForegroundColor DarkGray
    $customDeploy = Read-Host "Press ENTER to keep default, or enter custom path"
    if (-not [string]::IsNullOrWhiteSpace($customDeploy)) {
        $DeployPath = $customDeploy.Trim()
    }

    Write-Host ""
    Write-Host "Dedicated backup directory (outside Stream Deck & Git):" -ForegroundColor White
    Write-Host "  $BackupDir" -ForegroundColor DarkGray
    $customBackup = Read-Host "Press ENTER to keep default, or enter custom path"
    if (-not [string]::IsNullOrWhiteSpace($customBackup)) {
        $BackupDir = $customBackup.Trim()
    }
}

# 4. Save config
$config = Set-DevWorkflowConfig -RepoRoot $validation.Path -DeployPath $DeployPath -BackupDir $BackupDir

Write-Host ""
Write-Host "SUCCESS: Dev workflow configuration saved!" -ForegroundColor Green
Write-Host "  Config File   : $(Get-ConfigFilePath -RepoRoot $config.sourceRoot)"
Write-Host "  Authoritative : $($config.sourceRoot)"
Write-Host "  Deployed To   : $($config.streamDeckPluginDeployPath)"
Write-Host "  Backups In    : $($config.backupDirectory)"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  - Run '.\tools\get-status.ps1' to check system diagnostic status."
Write-Host "  - Run '.\tools\test-commit.ps1' to test current commit."
Write-Host "  - Run '.\tools\test-commit.ps1 -Deploy' to test and safely deploy."
Write-Host "  - Run '.\tools\rollback-plugin.ps1' if you need to restore the previous build."
Write-Host "============================================================" -ForegroundColor Cyan
