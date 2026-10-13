<#
.SYNOPSIS
    Regression test suite for DARTS Windows dev workflow PowerShell tools.
.DESCRIPTION
    Validates repo detection, configuration management, Git metadata extraction,
    build/test execution, backup creation, deployment, rollback, and diagnostic scanning.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptDir "..\.."))
$toolsDir = Join-Path $repoRoot "tools"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "     Running Dev Workflow PowerShell Regression Tests       " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

. (Join-Path $toolsDir "dev-workflow-common.ps1")

$passCount = 0
$failCount = 0

function Assert-Condition {
    param(
        [bool]$Condition,
        [string]$Message
    )
    if ($Condition) {
        Write-Host "  PASS: $Message" -ForegroundColor Green
        $script:passCount++
    }
    else {
        Write-Host "  FAIL: $Message" -ForegroundColor Red
        $script:failCount++
    }
}

# ---------------------------------------------------------
# Test 1: Find-RepoRoot
# ---------------------------------------------------------
Write-Host "`nTest Suite 1: Repo Root Discovery" -ForegroundColor Yellow
$foundFromTools = Find-RepoRoot -StartingDirectory $toolsDir
Assert-Condition ($foundFromTools -eq $repoRoot) "Find-RepoRoot discovers repository from tools/"

$foundFromDeep = Find-RepoRoot -StartingDirectory (Join-Path $repoRoot "DARTS/streamdeck/plugin/src_go")
Assert-Condition ($foundFromDeep -eq $repoRoot) "Find-RepoRoot discovers repository from deeply nested directory"

# ---------------------------------------------------------
# Test 2: Test-IsAuthoritativeRepo
# ---------------------------------------------------------
Write-Host "`nTest Suite 2: Repository Verification" -ForegroundColor Yellow
$validRepo = Test-IsAuthoritativeRepo -Path $repoRoot
Assert-Condition ($validRepo.IsValid -eq $true) "Test-IsAuthoritativeRepo validates genuine repository"

$fakeTemp = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), [System.Guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $fakeTemp | Out-Null
try {
    $invalidRepo = Test-IsAuthoritativeRepo -Path $fakeTemp
    Assert-Condition ($invalidRepo.IsValid -eq $false) "Test-IsAuthoritativeRepo rejects arbitrary folder"
}
finally {
    Remove-Item -LiteralPath $fakeTemp -Recurse -Force -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------
# Test 3: Get-GitInfo
# ---------------------------------------------------------
Write-Host "`nTest Suite 3: Git Metadata Extraction" -ForegroundColor Yellow
$gitInfo = Get-GitInfo -RepoRoot $repoRoot
Assert-Condition ($gitInfo.IsGit -eq $true) "Get-GitInfo identifies git worktree"
Assert-Condition ($gitInfo.Commit.Length -ge 7) "Get-GitInfo extracts valid commit SHA: $($gitInfo.ShortCommit)"
Assert-Condition (-not [string]::IsNullOrWhiteSpace($gitInfo.Branch)) "Get-GitInfo extracts active branch: $($gitInfo.Branch)"

# ---------------------------------------------------------
# Test 4: Configuration File Management (isolated sandbox)
# ---------------------------------------------------------
Write-Host "`nTest Suite 4: Local Config Lifecycle" -ForegroundColor Yellow
$tempSandbox = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), "darts-test-" + [System.Guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $tempSandbox | Out-Null

try {
    $mockDeploy = Join-Path $tempSandbox "deployed-plugin"
    $mockBackup = Join-Path $tempSandbox "backups"

    $savedConfig = Set-DevWorkflowConfig -RepoRoot $repoRoot -DeployPath $mockDeploy -BackupDir $mockBackup
    Assert-Condition ($savedConfig.sourceRoot -eq $repoRoot) "Config sourceRoot matches repoRoot"
    Assert-Condition ($savedConfig.streamDeckPluginDeployPath -eq $mockDeploy) "Config deploy path stored"
    Assert-Condition ($savedConfig.backupDirectory -eq $mockBackup) "Config backup directory stored"

    $readConfig = Get-DevWorkflowConfig -RepoRoot $repoRoot
    Assert-Condition ($readConfig.repository -eq "PinappleCola/EHS_STAT_SERV") "Config repository matches PinappleCola/EHS_STAT_SERV"
    Assert-Condition ($readConfig.streamDeckPluginDeployPath -eq $mockDeploy) "Config read back matches deploy path"

    # Test 5: Deploy, Backup, and Rollback Lifecycle
    Write-Host "`nTest Suite 5: Deploy, Backup, and Rollback" -ForegroundColor Yellow

    # Initial deploy
    $deployResult = Deploy-PluginFiles -Config $readConfig -NonInteractive -Force
    Assert-Condition ($deployResult.Success -eq $true) "Deploy-PluginFiles succeeded"
    Assert-Condition (Test-Path -LiteralPath (Join-Path $mockDeploy "manifest.json")) "Deployed plugin contains manifest.json"
    Assert-Condition (Test-Path -LiteralPath (Join-Path $mockDeploy "bin/darts-plugin.exe")) "Deployed plugin contains binary"

    # Simulate modifying deployed binary to test rollback
    $targetExe = Join-Path $mockDeploy "bin/darts-plugin.exe"
    $originalBytes = [System.IO.File]::ReadAllBytes($targetExe)
    [System.IO.File]::WriteAllText($targetExe, "MOCK_MODIFIED_BINARY_DATA")

    # Second deploy: should back up previous deployment
    $deployResult2 = Deploy-PluginFiles -Config $readConfig -NonInteractive -Force
    Assert-Condition ($deployResult2.BackupInfo.Created -eq $true) "Second deployment triggers automatic backup"
    $backupPath = $deployResult2.BackupInfo.BackupPath
    Assert-Condition (Test-Path -LiteralPath $backupPath) "Backup folder exists at $backupPath"
    Assert-Condition (Test-Path -LiteralPath (Join-Path $backupPath "backup-meta.json")) "Backup includes backup-meta.json"

    # Rollback to the previous backup
    $restoreResult = Restore-PluginBackup -Config $readConfig -NonInteractive -Force
    Assert-Condition ($restoreResult.Success -eq $true) "Restore-PluginBackup succeeded"
    $restoredExeText = [System.IO.File]::ReadAllText($targetExe)
    Assert-Condition ($restoredExeText -eq "MOCK_MODIFIED_BINARY_DATA") "Rollback restored previous deployment state"

    # Test 6: Diagnostics and Confusing Folder Detection
    Write-Host "`nTest Suite 6: Diagnostics & Stray Folder Scan" -ForegroundColor Yellow
    # Create a simulated rogue folder with 'darts' in sibling directory
    $rogueDir = Join-Path $tempSandbox "stray-com.pineapplecola.darts-test"
    New-Item -ItemType Directory -Path $rogueDir | Out-Null

    $diag = Get-DevWorkflowStatus -Config $readConfig -ScanConfusingFolders
    Assert-Condition ($diag.AuthoritativeRepoRoot -eq $repoRoot) "Diagnostic reports correct authoritative repo"
    Assert-Condition ($diag.BackupCount -ge 1) "Diagnostic reports backup count >= 1"
    Assert-Condition ($diag.HasLastKnownGood -eq $true) "Diagnostic reports last-known-good present"

    $foundRogue = $diag.ConfusingLocations | Where-Object { $_.Location -eq $rogueDir }
    Assert-Condition ($null -ne $foundRogue) "Diagnostic scan detected sibling duplicate/stray folder"
}
finally {
    # Clean up temp sandbox
    Remove-Item -LiteralPath $tempSandbox -Recurse -Force -ErrorAction SilentlyContinue

    # Remove temporary .dev-workflow.local.json created during test
    $testConfigFile = Get-ConfigFilePath -RepoRoot $repoRoot
    if (Test-Path -LiteralPath $testConfigFile) {
        Remove-Item -LiteralPath $testConfigFile -Force -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------
# Test 7: CLI Entrypoint (dev.ps1)
# ---------------------------------------------------------
Write-Host "`nTest Suite 7: Unified CLI Entrypoint (dev.ps1)" -ForegroundColor Yellow
$helpOutput = & pwsh -File (Join-Path $toolsDir "dev.ps1") help
Assert-Condition ($LASTEXITCODE -eq 0) "dev.ps1 help exits with code 0"

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host "Results: $passCount passed, $failCount failed." -ForegroundColor $(if ($failCount -eq 0) { 'Green' } else { 'Red' })
Write-Host "============================================================" -ForegroundColor Cyan

if ($failCount -gt 0) {
    exit 1
}
else {
    exit 0
}
