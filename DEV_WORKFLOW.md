# Windows Development, Testing, and Deployment Workflow

This guide explains the predictable, automated Windows workflow for testing commits and deploying the DARTS Stream Deck plugin.

It eliminates the confusion of multiple local folder copies, guarantees safety, and enables one-command testing, deployment, and rollback.

---

## Core Principles

| Concept | Location / Purpose |
|---|---|
| **One authoritative repository** | The single Git clone on your PC where code is checked out and modified. |
| **One installed plugin location** | `%APPDATA%\Elgato\StreamDeck\Plugins\com.pineapplecola.darts.sdPlugin` (the only live plugin folder used by Stream Deck). |
| **One backup directory** | `%USERPROFILE%\.darts-dev-backups\` (completely outside Stream Deck folders so backups cannot be accidentally loaded as duplicate plugins). |
| **One local configuration** | `.dev-workflow.local.json` in your repository root (ignored by Git, remembers your chosen paths). |
| **No Program Files copies** | Stream Deck plugins must never be placed in `C:\Program Files` or `Program Files (x86)`. |

---

## Quick Reference CLI (`tools\dev.ps1`)

A unified launcher is provided in `tools\dev.ps1`:

```powershell
# 1. One-time setup: detect and confirm paths
.\tools\dev.ps1 setup

# 2. Status & diagnostics: see active branch, commit, deployed version, and detect stray copies
.\tools\dev.ps1 status

# 3. Test: run regression tests on the current commit
.\tools\dev.ps1 test

# 4. Test & Deploy: test a specific branch/commit and deploy if all tests pass
.\tools\dev.ps1 test -Branch main -Deploy
.\tools\dev.ps1 test -Commit 9ce0199 -Deploy

# 5. Standalone Deploy: backup previous plugin and deploy current build
.\tools\dev.ps1 deploy

# 6. Rollback: restore the last known good build if something breaks
.\tools\dev.ps1 rollback
```

*(You can also call the individual scripts under `tools/` directly if preferred: `setup-dev.ps1`, `get-status.ps1`, `test-commit.ps1`, `deploy-plugin.ps1`, `rollback-plugin.ps1`.)*

---

## 1. One-Time Setup

Run the setup helper once to establish your authoritative paths:

```powershell
.\tools\dev.ps1 setup
```

What the setup step does:
1. **Detects or asks for your repository root**: Automatically finds the folder containing `DARTS/darts.py` and the Stream Deck plugin manifest.
2. **Verifies repository authenticity**: Checks that the repository markers and plugin UUID (`com.pineapplecola.darts`) are valid.
3. **Identifies default deployment & backup paths**:
   - Deployment: `%APPDATA%\Elgato\StreamDeck\Plugins\com.pineapplecola.darts.sdPlugin`
   - Backups: `%USERPROFILE%\.darts-dev-backups`
4. **Saves configuration** to `.dev-workflow.local.json` in the repository root.

### The Local Configuration File (`.dev-workflow.local.json`)
This file is ignored by Git so your personal PC paths are never committed. It looks like:

```json
{
  "schemaVersion": "1.0",
  "repository": "PinappleCola/EHS_STAT_SERV",
  "sourceRoot": "C:\\Users\\User\\source\\repos\\EHS_STAT_SERV",
  "dartsRoot": "C:\\Users\\User\\source\\repos\\EHS_STAT_SERV\\DARTS",
  "streamDeckPluginSource": "C:\\Users\\User\\source\\repos\\EHS_STAT_SERV\\DARTS\\streamdeck\\plugin\\com.pineapplecola.darts.sdPlugin",
  "streamDeckPluginDeployPath": "C:\\Users\\User\\AppData\\Roaming\\Elgato\\StreamDeck\\Plugins\\com.pineapplecola.darts.sdPlugin",
  "backupDirectory": "C:\\Users\\User\\.darts-dev-backups",
  "historyFile": "C:\\Users\\User\\.darts-dev-backups\\run-history.json",
  "updatedAt": "2026-10-13T01:30:00.0000000Z"
}
```

---

## 2. Testing Commits & Branches

To test the current working tree or a specific commit before deploying:

```powershell
# Test current working tree
.\tools\dev.ps1 test

# Test a specific commit SHA and deploy if tests pass
.\tools\dev.ps1 test -Commit a1b2c3d -Deploy

# Test a PR or feature branch
.\tools\dev.ps1 test -Branch copilot/my-feature-branch -Deploy
```

What the test runner does:
1. **Checks Git state**: Warns if there are uncommitted changes before switching commits.
2. **Checks out the target branch or commit** (if `-Branch` or `-Commit` specified).
3. **Runs repository regression tests**:
   - Stream Deck plugin regression suite (`DARTS/tests/streamdeck_plugin_regression.test.js`)
   - UI commands regression (`DARTS/tests/test_ui_commands_regression.py`)
   - 3D export regression (`DARTS/tests/test_export3d_regression.py`)
   - Map sources regression (`DARTS/tests/test_map_sources_regression.py`)
   - Sound playback regression (`DARTS/tests/sound_playback_regression.test.js`)
   - Trail logic regression (`DARTS/tests/test_trail_logic_regression.py`)
4. **Builds the native binary** (if Go is available).
5. **Halts immediately if any test fails**: Prevents broken builds from reaching Stream Deck.
6. **Deploys automatically if `-Deploy` is passed and all tests pass.**
7. **Records the run record** in `run-history.json` (commit SHA, branch, outcome, timestamp).

---

## 3. Safe Deployment

To deploy the current plugin files to Stream Deck:

```powershell
.\tools\dev.ps1 deploy
```

Safety features:
1. **Process check**: Detects if `StreamDeck.exe` is running and prompts you to close it to avoid Windows file locks.
2. **Automatic backup**: Before touching the deployed directory, the existing deployed copy is automatically archived to `.darts-dev-backups\backup-YYYYMMDD-HHMMSS` and also saved as `.darts-dev-backups\last-known-good`.
3. **Atomic copy**: Copies the authoritative `.sdPlugin` folder cleanly into `%APPDATA%\Elgato\StreamDeck\Plugins\com.pineapplecola.darts.sdPlugin`.
4. **Binary SHA256 verification**: Computes and logs the SHA256 of `darts-plugin.exe` so you can verify exactly what executable is installed.

---

## 4. Rollback & Restoring Known Good Builds

If a new commit causes an issue on your hardware, rollback to the previous version with a single command:

```powershell
# Restore the last known good build
.\tools\dev.ps1 rollback

# Or list available historical backups
.\tools\dev.ps1 rollback -List

# Or restore a specific timestamped backup
.\tools\dev.ps1 rollback -BackupName backup-20261013-143000
```

What rollback does:
1. Checks that Stream Deck is safely stopped.
2. Restores files from `.darts-dev-backups\last-known-good` (or your chosen backup).
3. Verifies the restored binary hash and reports success.

---

## 5. Diagnostics & Detecting Duplicate Folders

To see what is currently installed and detect confusing or duplicate folders on your PC:

```powershell
.\tools\dev.ps1 status
```

Status output reports:
1. **Authoritative repository**: Path, active branch, current commit SHA, clean/dirty state.
2. **Deployed plugin**: Target path, installed status, manifest version, binary SHA256 hash, and last modified date.
3. **Backups**: Backup folder path, number of saved backups, presence of `last-known-good`.
4. **Last run history**: Most recently tested commit, test outcome, and deployment status.
5. **Confusing / Duplicate locations scan**:
   - Checks `%APPDATA%\Elgato\StreamDeck\Plugins` for sibling folders containing `darts` or `pineapplecola`.
   - Checks `C:\Program Files` and `C:\Program Files (x86)` for stray plugins.
   - **Important**: The tool will **never delete** these folders automatically; it prints clear warnings and advice on what to remove manually.

---

## 6. Continuing in a New Copilot Chat

When starting a new Copilot chat to work on this repository:
1. Point Copilot to this file:
   > *"In `PinappleCola/EHS_STAT_SERV`, read `DEV_WORKFLOW.md` and check the status of my setup using `.\tools\dev.ps1 status`."*
2. To test and deploy changes recommended by Copilot:
   > *"Run `.\tools\dev.ps1 test -Deploy` to validate and install the changes."*
3. If an issue occurs:
   > *"Run `.\tools\dev.ps1 rollback` to restore the last working build."*
