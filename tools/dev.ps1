<#
.SYNOPSIS
    Unified Windows developer CLI for EHS_STAT_SERV and Stream Deck plugin testing.
.DESCRIPTION
    Provides a simple, predictable interface to setup, test commits, deploy,
    rollback, and diagnose local installations.
.EXAMPLE
    .\tools\dev.ps1 setup
    .\tools\dev.ps1 status
    .\tools\dev.ps1 test
    .\tools\dev.ps1 test -Deploy
    .\tools\dev.ps1 test -Commit 69de5a2 -Deploy
    .\tools\dev.ps1 rollback
    .\tools\dev.ps1 rollback -List
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("setup", "status", "test", "deploy", "rollback", "restore", "help")]
    [string]$Command = "help",

    # Pass-through arguments
    [string]$RepoRoot,
    [string]$DeployPath,
    [string]$BackupDir,
    [string]$Commit,
    [string]$Branch,
    [string]$BackupName,
    [switch]$Deploy,
    [switch]$SkipBuild,
    [switch]$SkipTests,
    [switch]$List,
    [switch]$NoScan,
    [switch]$NonInteractive,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

switch ($Command) {
    "setup" {
        $params = @{}
        if ($RepoRoot) { $params["RepoRoot"] = $RepoRoot }
        if ($DeployPath) { $params["DeployPath"] = $DeployPath }
        if ($BackupDir) { $params["BackupDir"] = $BackupDir }
        if ($NonInteractive) { $params["NonInteractive"] = $true }
        & (Join-Path $scriptDir "setup-dev.ps1") @params
    }

    "status" {
        $params = @{}
        if ($RepoRoot) { $params["RepoRoot"] = $RepoRoot }
        if ($NoScan) { $params["NoScan"] = $true }
        & (Join-Path $scriptDir "get-status.ps1") @params
    }

    "test" {
        $params = @{}
        if ($Commit) { $params["Commit"] = $Commit }
        if ($Branch) { $params["Branch"] = $Branch }
        if ($Deploy) { $params["Deploy"] = $true }
        if ($SkipBuild) { $params["SkipBuild"] = $true }
        if ($NonInteractive) { $params["NonInteractive"] = $true }
        if ($Force) { $params["Force"] = $true }
        & (Join-Path $scriptDir "test-commit.ps1") @params
    }

    "deploy" {
        $params = @{}
        if ($SkipTests) { $params["SkipTests"] = $true }
        if ($NonInteractive) { $params["NonInteractive"] = $true }
        if ($Force) { $params["Force"] = $true }
        & (Join-Path $scriptDir "deploy-plugin.ps1") @params
    }

    { $_ -in "rollback", "restore" } {
        $params = @{}
        if ($BackupName) { $params["BackupName"] = $BackupName }
        if ($List) { $params["List"] = $true }
        if ($NonInteractive) { $params["NonInteractive"] = $true }
        if ($Force) { $params["Force"] = $true }
        & (Join-Path $scriptDir "rollback-plugin.ps1") @params
    }

    default {
        Write-Host "============================================================" -ForegroundColor Cyan
        Write-Host "      DARTS Windows Development & Testing Launcher          " -ForegroundColor Cyan
        Write-Host "============================================================" -ForegroundColor Cyan
        Write-Host "Usage: .\tools\dev.ps1 <command> [options]"
        Write-Host ""
        Write-Host "Commands:" -ForegroundColor White
        Write-Host "  setup     Detect & remember authoritative repository and plugin paths"
        Write-Host "            Options: [-RepoRoot <path>] [-DeployPath <path>] [-BackupDir <path>] [-NonInteractive]"
        Write-Host ""
        Write-Host "  status    Show diagnostic status, Git branch/commit, deployed plugin & backups"
        Write-Host "            Options: [-NoScan]"
        Write-Host ""
        Write-Host "  test      Run test suite on current or target commit, with optional safe deploy"
        Write-Host "            Options: [-Commit <sha>] [-Branch <name>] [-Deploy] [-SkipBuild] [-NonInteractive]"
        Write-Host ""
        Write-Host "  deploy    Safely deploy the current plugin build with automatic backup"
        Write-Host "            Options: [-SkipTests] [-NonInteractive] [-Force]"
        Write-Host ""
        Write-Host "  rollback  Restore plugin from last known good or specified backup"
        Write-Host "            Options: [-BackupName <name>] [-List] [-NonInteractive] [-Force]"
        Write-Host ""
        Write-Host "Examples:" -ForegroundColor DarkGray
        Write-Host "  .\tools\dev.ps1 setup"
        Write-Host "  .\tools\dev.ps1 status"
        Write-Host "  .\tools\dev.ps1 test"
        Write-Host "  .\tools\dev.ps1 test -Deploy"
        Write-Host "  .\tools\dev.ps1 rollback"
        Write-Host "============================================================" -ForegroundColor Cyan
    }
}
