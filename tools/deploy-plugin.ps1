<#
.SYNOPSIS
    Safely deploys the built DARTS Stream Deck plugin to the authoritative location.
.DESCRIPTION
    Backs up the currently deployed plugin, safely terminates Stream Deck to prevent
    file-locking issues, deploys the new plugin, and prompts to restart Stream Deck.
.PARAMETER SkipTests
    Skip running tests before deploying.
.PARAMETER NonInteractive
    Skip interactive prompts.
.PARAMETER Force
    Force deployment and process closure without prompting.
#>

[CmdletBinding()]
param(
    [switch]$SkipTests,
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

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "             Deploying DARTS Stream Deck Plugin             " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Optionally run tests
if (-not $SkipTests) {
    Write-Host "[deploy] Running tests before deployment..." -ForegroundColor Cyan
    $testResult = Invoke-PluginTests -Config $config
    if (-not $testResult.Passed) {
        Write-Host "ERROR: Tests failed! Aborting deployment." -ForegroundColor Red
        foreach ($err in $testResult.Errors) {
            Write-Host "  - $err" -ForegroundColor Red
        }
        exit 1
    }
    Write-Host "[deploy] Tests passed." -ForegroundColor Green
}

# 2. Deploy
try {
    $deployInfo = Deploy-PluginFiles -Config $config -NonInteractive:$NonInteractive -Force:$Force
    Start-StreamDeckSafe -NonInteractive:$NonInteractive
}
catch {
    Write-Host "ERROR: Deployment failed: $_" -ForegroundColor Red
    exit 1
}

# 3. Record
$gitInfo = Get-GitInfo -RepoRoot $config.sourceRoot
$runRecord = [ordered]@{
    "timestamp" = (Get-Date -Format "o")
    "commit" = $gitInfo.Commit
    "shortCommit" = $gitInfo.ShortCommit
    "branch" = $gitInfo.Branch
    "testPassed" = (-not $SkipTests)
    "deployed" = $true
    "deployedPath" = $deployInfo.DeployedPath
    "binarySha256" = $deployInfo.BinarySha256
    "backupPath" = if ($deployInfo.BackupInfo.Created) { $deployInfo.BackupInfo.BackupPath } else { $null }
}
Write-RunRecord -Config $config -Record $runRecord

Write-Host ""
Write-Host "Deployment completed successfully and recorded." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
