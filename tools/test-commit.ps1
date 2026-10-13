<#
.SYNOPSIS
    Runs test suite for the current commit or a target commit/branch, and optionally deploys.
.DESCRIPTION
    Validates tests, builds binaries if needed, and safely deploys the Stream Deck
    plugin into the remembered AppData location only if all tests pass.
.PARAMETER Commit
    Optional Git commit SHA or branch name to checkout before testing.
.PARAMETER Branch
    Optional Git branch name to checkout before testing.
.PARAMETER Deploy
    Switch to automatically deploy to Stream Deck if all tests pass.
.PARAMETER SkipBuild
    Skip running Go binary build before testing.
.PARAMETER NonInteractive
    Skip interactive prompts.
.PARAMETER Force
    Force checkout even if uncommitted changes exist (discards or allows checkout).
#>

[CmdletBinding()]
param(
    [string]$Commit,
    [string]$Branch,
    [switch]$Deploy,
    [switch]$SkipBuild,
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
    Write-Host "Config not found in $repoRoot. Initializing default config..." -ForegroundColor Cyan
    $config = Set-DevWorkflowConfig -RepoRoot $repoRoot
}

# 1. Handle target checkout if requested
$targetRef = if ($Commit) { $Commit } elseif ($Branch) { $Branch } else { $null }
if ($targetRef) {
    Write-Host "[git] Switching to target: $targetRef" -ForegroundColor Cyan
    try {
        Checkout-GitTarget -RepoRoot $config.sourceRoot -Target $targetRef -Force:$Force
    }
    catch {
        Write-Host "ERROR: $_" -ForegroundColor Red
        exit 1
    }
}

$gitInfo = Get-GitInfo -RepoRoot $config.sourceRoot
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "               Testing Commit / Branch                      " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Repository : $($config.sourceRoot)"
Write-Host "  Branch     : $($gitInfo.Branch)"
Write-Host "  Commit SHA : $($gitInfo.Commit)"
Write-Host "  Clean Tree : $(-not $gitInfo.IsDirty)"
Write-Host ""

# 2. Build if not skipped
if (-not $SkipBuild) {
    $buildResult = Invoke-PluginBuild -Config $config
    if (-not $buildResult.Success) {
        Write-Host "ERROR: Plugin build failed!" -ForegroundColor Red
        Write-Host "$($buildResult.Error)" -ForegroundColor Red

        # Record failure
        $runRecord = [ordered]@{
            "timestamp" = (Get-Date -Format "o")
            "commit" = $gitInfo.Commit
            "shortCommit" = $gitInfo.ShortCommit
            "branch" = $gitInfo.Branch
            "testPassed" = $false
            "deployed" = $false
            "stage" = "build"
            "error" = $buildResult.Error
        }
        Write-RunRecord -Config $config -Record $runRecord
        exit 1
    }
}

# 3. Run regression tests
Write-Host "[tests] Running repository test suites..." -ForegroundColor Cyan
$testResult = Invoke-PluginTests -Config $config

if (-not $testResult.Passed) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host "TESTS FAILED! Stopping workflow. No deployment will occur." -ForegroundColor Red
    Write-Host "============================================================" -ForegroundColor Red
    foreach ($err in $testResult.Errors) {
        Write-Host "  - $err" -ForegroundColor Red
    }

    $runRecord = [ordered]@{
        "timestamp" = (Get-Date -Format "o")
        "commit" = $gitInfo.Commit
        "shortCommit" = $gitInfo.ShortCommit
        "branch" = $gitInfo.Branch
        "testPassed" = $false
        "deployed" = $false
        "stage" = "test"
        "errors" = $testResult.Errors
    }
    Write-RunRecord -Config $config -Record $runRecord
    exit 1
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "ALL TESTS PASSED!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""

# 4. Deployment decision
$shouldDeploy = $false
if ($Deploy) {
    $shouldDeploy = $true
}
elseif (-not $NonInteractive) {
    $answer = Read-Host "Tests passed. Deploy this build to Stream Deck now? [Y/n]"
    if ([string]::IsNullOrWhiteSpace($answer) -or $answer.Trim().ToLower() -eq 'y') {
        $shouldDeploy = $true
    }
}

$deployInfo = $null
if ($shouldDeploy) {
    Write-Host "[deploy] Proceeding with safe deployment..." -ForegroundColor Cyan
    try {
        $deployInfo = Deploy-PluginFiles -Config $config -NonInteractive:$NonInteractive -Force:$Force
        Start-StreamDeckSafe -NonInteractive:$NonInteractive
    }
    catch {
        Write-Host "ERROR: Deployment failed: $_" -ForegroundColor Red

        $runRecord = [ordered]@{
            "timestamp" = (Get-Date -Format "o")
            "commit" = $gitInfo.Commit
            "shortCommit" = $gitInfo.ShortCommit
            "branch" = $gitInfo.Branch
            "testPassed" = $true
            "deployed" = $false
            "stage" = "deploy"
            "error" = "$_"
        }
        Write-RunRecord -Config $config -Record $runRecord
        exit 1
    }
}
else {
    Write-Host "Deployment skipped. Run '.\tools\deploy-plugin.ps1' when ready to deploy." -ForegroundColor DarkGray
}

# 5. Record run record
$runRecord = [ordered]@{
    "timestamp" = (Get-Date -Format "o")
    "commit" = $gitInfo.Commit
    "shortCommit" = $gitInfo.ShortCommit
    "branch" = $gitInfo.Branch
    "testPassed" = $true
    "deployed" = $shouldDeploy
    "deployedPath" = if ($deployInfo) { $deployInfo.DeployedPath } else { $null }
    "binarySha256" = if ($deployInfo) { $deployInfo.BinarySha256 } else { $null }
    "backupPath" = if ($deployInfo -and $deployInfo.BackupInfo.Created) { $deployInfo.BackupInfo.BackupPath } else { $null }
}
Write-RunRecord -Config $config -Record $runRecord

Write-Host ""
Write-Host "Test run complete and recorded in run history." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
