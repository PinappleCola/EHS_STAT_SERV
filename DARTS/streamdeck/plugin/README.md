# DARTS Stream Deck Plugin (`com.pineapplecola.darts`)

Three coloured, live-state keys for the DARTS live map:

| Action | What a press does | Same as ribbon button | Action UUID |
|--------|-------------------|-----------------------|-------------|
| **MAP toggle** | Basemap / network mode on ⇄ off | `MAP TOGGLE` (`btn-network`) | `com.pineapplecola.darts.map` |
| **IFR waypoints** | IFR waypoints visible ⇄ hidden | `IFR` (`btn-ifr-toggle`) | `com.pineapplecola.darts.ifr` |
| **VFR waypoints** | VFR waypoints visible ⇄ hidden | `VFR` (`btn-vfr-toggle`) | `com.pineapplecola.darts.vfr` |

Each key displays a prominent label (MAP / IFR / VFR), a live status text, and a colour-coded background:

| Key face | Default colour | Hex | Meaning |
|----------|----------------|-----|---------|
| `ON` | Green | `#15803D` | Basemap enabled / waypoint layer visible |
| `OFF` | Red | `#B91C1C` | Basemap disabled / waypoint layer hidden |
| `WAIT` | Amber | `#B45309` | Internal pending state (hidden for normal toggles; key retains last confirmed state) |
| `ERROR` | Amber | `#B45309` | Command failed or was unconfirmed after 3 s (briefly shown, then re-syncs) |
| `NO MAP` | Grey | `#475569` | DARTS is running, but no live map browser tab is open |
| `STALE` | Grey | `#475569` | The map stopped reporting (no heartbeat update for > 6 s) |
| `OFFLINE` | Light neutral | `#CBD5E1` | DARTS API is unreachable or offline (calm appearance with dark text `#0F172A`) |

> **Note on IFR/VFR**: `ON` means the waypoint layer is enabled in the live map view. The global **ELEMENT TOGGLE** or an empty waypoint dataset can still result in no markers being drawn on screen.

> For the comprehensive design standard, architecture details, and recipe for adding new buttons, see [BUTTON_SPEC.md](BUTTON_SPEC.md).

---

## Table of Contents

- [Overview & Requirements](#overview--requirements)
- [How It Works](#how-it-works)
- [Button Design Standard (`BUTTON_SPEC.md`)](BUTTON_SPEC.md)
- [Install Method 1: Double-Click Installer (Primary)](#install-method-1-double-click-installer-primary)
- [Install Method 2: Manual Copy (Reliable Fallback)](#install-method-2-manual-copy-reliable-fallback)
- [Uninstall & Clean Reset (Critical)](#uninstall--clean-reset-critical)
- [Troubleshooting & FAQ](#troubleshooting--faq)
- [PowerShell Helper Scripts](#powershell-helper-scripts)
- [Usage & Live Map Integration](#usage--live-map-integration)
- [Settings (Property Inspector)](#settings-property-inspector)
- [Reproducible Build & Packaging Pipeline](#reproducible-build--packaging-pipeline)
- [Files & Directory Structure](#files--directory-structure)

---

## Overview & Requirements

- **Self-contained native executable architecture**:
  This plugin is compiled into self-contained native binaries (`bin/darts-plugin.exe` on Windows, `bin/darts-plugin` universal binary on macOS) referenced via `CodePathWin` and `CodePathMac` in `manifest.json`.
  **It does NOT require Stream Deck's managed Node.js runtime**, and it has no `Nodejs` block in `manifest.json`. It loads and runs reliably even when `%APPDATA%\Elgato\StreamDeck\NodeJS\` is completely empty, unprovisioned, or absent.
- **Supported Operating Systems**: Windows 10+ (64-bit) and macOS 12+ (Apple Silicon or Intel).
- **Stream Deck Application**: Minimum version **7.1** (confirmed working on v7.6+ on Windows 11).
- **Host Location**: Must run on the **same computer** hosting DARTS (defaulting to `http://127.0.0.1:8766`).
- **Canonical Naming**:
  - Plugin UUID: `com.pineapplecola.darts` (spelled with `pineapple`, including the `e`).
  - Folder name: `com.pineapplecola.darts.sdPlugin`.
  - Actions: `com.pineapplecola.darts.map`, `com.pineapplecola.darts.ifr`, `com.pineapplecola.darts.vfr`.

---

## How It Works

```text
Stream Deck App ⇄ Native Plugin Binary ──HTTP POST /api/ui-command──▶ DARTS (:8766) ──WebSocket (:8765)──▶ Live Map Tab
                                        ◀──HTTP GET /api/ui-state─────┘ (echoed request_id) ◀── ui_state reports ──┘
```

1. **User Press**:
   Pressing a key dispatches `POST /api/ui-command` with a unique request ID (e.g. `{"command":"toggle_ifr","request_id":"sd-…"}`). DARTS forwards the command over its WebSocket to all connected map tabs, triggering the exact same handler as clicking the corresponding ribbon button.
2. **Internal Pending Tracking (Calm Toggle UX)**:
   On a normal successful press, the button keeps showing its last confirmed state rather than flashing a distracting WAIT graphic. Internally, the plugin tracks pending confirmation, accelerates polling to 4×/s, and reconciles the echoed `request_id`. Rapid double-presses while pending are ignored without triggering an alarming exclamation-mark alert.
3. **Confirmed Authoritative State**:
   The active live map browser tab is authoritative. It reports `mapEnabled`, `ifrEnabled`, and `vfrEnabled` to DARTS when connecting, after every toggle, and as a 2-second heartbeat. Once the map applies the command, it echoes back the `request_id`.
   The plugin polls `GET /api/ui-state` once per second (accelerating to 4×/s while awaiting confirmation). When the matching request ID is seen, the key transitions to `ON` (green) or `OFF` (red).
4. **Timeout & Failure Handling**:
   If no confirmation arrives within 3 seconds, the key displays `ERROR`, flashes the Stream Deck alert triangle, and then resynchronizes to the live state reported by the map. Real errors (network transport failure, HTTP error, timeout) trigger alerts; commands are never retried automatically.
5. **Multiple Browser Tabs & Background Execution**:
   The live map browser tab does **not** need to be the active/frontmost window on screen; it only needs to remain open and connected. With multiple map tabs open, all tabs toggle together, and keys reflect the state of the *controlling map* (the earliest-connected active tab). If closed, the next tab takes over.

---

## Install Method 1: Double-Click Installer (Primary)

The repository provides a prebuilt, validated `.streamDeckPlugin` installer bundle in `dist/`.

1. **Download the installer file**:
   Download [`dist/com.pineapplecola.darts.streamDeckPlugin`](dist/com.pineapplecola.darts.streamDeckPlugin).
   > **IMPORTANT**: On GitHub, click the **Download raw file** button (the down-arrow icon) or use a direct raw URL. Do not use your browser's "Save link as..." on the GitHub preview page, as that can save an HTML document. **Verify the downloaded file size is ~8 MB before installing.**
2. **Quit Stream Deck**:
   Fully quit the Stream Deck application before installing (right-click the Stream Deck tray icon in Windows taskbar notification area → **Quit**). Closing the desktop window is not enough.
3. **Install**:
   Double-click `com.pineapplecola.darts.streamDeckPlugin` and approve the installation in the dialog. Stream Deck unpacks the plugin bundle directly into `%APPDATA%\Elgato\StreamDeck\Plugins\`.
4. **Configure Keys**:
   Open Stream Deck, locate the **DARTS** category in the right-hand actions panel, and drag **MAP toggle**, **IFR waypoints**, and **VFR waypoints** onto your keys.

*(If the installer reports `(AlreadyInstalled)` but no DARTS actions appear, see [Uninstall & Clean Reset](#uninstall--clean-reset-critical) below to clear a duplicate-UUID conflict).*

---

## Install Method 2: Manual Copy (Reliable Fallback)

If the double-click installer fails or reports `(AlreadyInstalled)` due to duplicate package registrations, manual copying into `%APPDATA%\Elgato\StreamDeck\Plugins\` is the **proven, reliable fallback**:

1. **Fully quit Stream Deck**:
   Ensure `StreamDeck.exe` is completely stopped (taskbar tray icon → Quit, or kill via Task Manager).
2. **Copy the `.sdPlugin` directory**:
   Extract the `.streamDeckPlugin` (it is a standard zip archive) OR copy the `com.pineapplecola.darts.sdPlugin` folder directly into:
   - **Windows**: `%APPDATA%\Elgato\StreamDeck\Plugins\com.pineapplecola.darts.sdPlugin`
   - **macOS**: `~/Library/Application Support/com.elgato.StreamDeck/Plugins/com.pineapplecola.darts.sdPlugin`

   *(Ensure `manifest.json` is directly inside `com.pineapplecola.darts.sdPlugin\manifest.json`, with no nested subfolder).*

3. **PowerShell one-liner / script**:
   From a standard PowerShell prompt on Windows:

   ```powershell
   $work = "$env:TEMP\darts-extract"
   Expand-Archive -Force "<path-to>\com.pineapplecola.darts.streamDeckPlugin" "$work\out"
   $dst = "$env:APPDATA\Elgato\StreamDeck\Plugins\com.pineapplecola.darts.sdPlugin"
   Remove-Item -Recurse -Force $dst -ErrorAction SilentlyContinue
   Copy-Item -Recurse -Force "$work\out\com.pineapplecola.darts.sdPlugin" $dst
   ```

   Or run the automated helper script included in this repository:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\install-manual.ps1
   ```

4. **Restart Stream Deck**:
   Launch Stream Deck from the Start menu. The **DARTS** category will now appear in the action list.

---

## Uninstall & Clean Reset (Critical)

Stream Deck plugins can be stored in **TWO** locations on Windows:
1. **Per-user location**:
   `%APPDATA%\Elgato\StreamDeck\Plugins\com.pineapplecola.darts.sdPlugin\`
2. **System-wide location**:
   `C:\Program Files\Elgato\StreamDeck\Plugins\com.pineapplecola.darts.sdPlugin\`
   *(Or `C:\Program Files (x86)\Elgato\StreamDeck\Plugins\...`)*

### The Duplicate-UUID Conflict Trap

If a copy of `com.pineapplecola.darts.sdPlugin` was previously placed or unpacked in `C:\Program Files\Elgato\StreamDeck\Plugins\`, Stream Deck attempts to load both copies. This produces:
```text
Plugins war esd::plugins::Storage::load Plugin conflict: 'com.pineapplecola.darts' (already loaded plugin with same uuid)
```
When this conflict occurs:
- The Stream Deck installer reports **`(AlreadyInstalled)`** when you double-click `.streamDeckPlugin`.
- **No DARTS actions appear** in the action list.
- Standard user resets (wiping `%APPDATA%`, clearing user temp folders, or deleting user registry keys) **fail to resolve the issue** because the Program Files copy lives outside the user profile and survives normal uninstalls.
- Deleting the Program Files copy **requires an Administrator-elevated prompt**.

### Clean Reset Steps

1. **Find every installed copy**:
   Run this command in PowerShell to locate every copy across all user and system paths:

   ```powershell
   Get-ChildItem -Recurse -Path "$env:APPDATA\Elgato","$env:LOCALAPPDATA\Elgato","C:\Program Files\Elgato","C:\Program Files (x86)\Elgato" -Filter "manifest.json" -ErrorAction SilentlyContinue |
     Where-Object { (Get-Content $_.FullName -Raw) -match "com\.pineapplecola\.darts" } |
     Select-Object FullName
   ```

2. **Remove the system-wide Program Files copy (requires Admin PowerShell)**:
   Open **PowerShell as Administrator** and execute:

   ```powershell
   Remove-Item -Recurse -Force "C:\Program Files\Elgato\StreamDeck\Plugins\com.pineapplecola.darts.sdPlugin" -ErrorAction SilentlyContinue
   ```

3. **Remove the per-user copy**:

   ```powershell
   Remove-Item -Recurse -Force "$env:APPDATA\Elgato\StreamDeck\Plugins\com.pineapplecola.darts.sdPlugin" -ErrorAction SilentlyContinue
   ```

4. **Clear the temp import cache**:

   ```powershell
   Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Temp\com.elgato.streamdeck" -ErrorAction SilentlyContinue
   ```

5. **(Optional) Reset registry cache**:
   If performing a complete factory reset of Stream Deck configurations:
   - Registry path: `HKCU\Software\Elgato Systems GmbH\StreamDeck` (note: survives a normal uninstallation of the Stream Deck app).

6. **Automated clean uninstall**:
   Alternatively, run the repository's cleanup script:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1
   ```

---

## Troubleshooting & FAQ

### Log Line Reference

| Log Line / Symptom | Root Cause | Fix |
|-------------------|------------|-----|
| `Plugin conflict: 'com.pineapplecola.darts' (already loaded plugin with same uuid)` | Duplicate copies exist in `C:\Program Files\Elgato\StreamDeck\Plugins\` and `%APPDATA%\Elgato\StreamDeck\Plugins\`. | Remove the system-wide copy from `C:\Program Files\...` using an **elevated Administrator PowerShell prompt**. Then restart Stream Deck. |
| Installer dialog says **"already installed"** / log shows `(AlreadyInstalled) Plugin 'DARTS Live Map' [?][com.pineapplecola.darts]` but **no actions appear** | Stream Deck detects the existing duplicate registration from Program Files and refuses to overwrite it, but fails to load the plugin due to conflict. | Follow the [Clean Reset Steps](#clean-reset-steps) to delete the Program Files copy and cache, then reinstall using manual copy. |
| `NodeManager ... Manifest file not found at ...\NodeJS\manifest.json` or `Failed to save Node.js manifest` | Stream Deck internal background routine attempting to provision its managed Node.js environment. | **HARMLESS.** This plugin ships a compiled standalone executable (`bin/darts-plugin.exe` / `bin/darts-plugin`). It does not use Stream Deck's Node runtime. You can safely ignore these warnings. |
| Actions list is empty, only default Elgato actions like `com.elgato.tutorial` / `com.elgato.keycreator` appear | Historically caused when Node-based plugins couldn't run without a managed Node runtime. | Run `powershell -ExecutionPolicy Bypass -File scripts\doctor.ps1` to inspect plugin status. Verify `bin/darts-plugin.exe` is present and permissions are intact. |
| All keys show `OFFLINE` | DARTS backend is not running or is bound to a different port. | Start DARTS (`run.bat` or `run.sh`). Confirm with `curl http://127.0.0.1:8766/api/ui-state`. |
| All keys show `NO MAP` | DARTS is running, but no browser tab has `http://localhost:8766/map` open. | Open `http://localhost:8766/map` in your browser. State is reported by the map page. |
| Key flashes `ERROR` after press | Map tab was frozen, backgrounded, closed, or did not echo the request ID within 3 seconds. | Key automatically re-syncs to the map's current state on the next poll. Ensure the live map tab remains active. |

### How to Verify the Plugin Loaded in Stream Deck Logs

Run this command in PowerShell to inspect the latest Stream Deck log entries:

```powershell
Get-Content "$env:APPDATA\Elgato\StreamDeck\logs\StreamDeck.log" -Tail 60 | Select-String -Pattern "pineapplecola","darts","conflict","connected"
```

**What success looks like**:
- Zero `Plugin conflict` lines.
- A `connected` entry for `com.pineapplecola.darts` (e.g. `Plugin 'DARTS Live Map' [...] connected`).
- In Task Manager (Windows) or Activity Monitor (macOS), `darts-plugin.exe` (or `darts-plugin`) is actively running.

---

## PowerShell Helper Scripts

Located under `DARTS/streamdeck/plugin/scripts/`:

1. **`install-manual.ps1`**:
   - Quits Stream Deck if running.
   - Verifies source directory and copies `com.pineapplecola.darts.sdPlugin` to `%APPDATA%\Elgato\StreamDeck\Plugins\`.
   - Clears the `%LOCALAPPDATA%\Temp\com.elgato.streamdeck` import cache.
   - Restarts Stream Deck.
   - Idempotent and safe to run multiple times.
2. **`uninstall.ps1`**:
   - Identifies and removes all copies of the plugin across `%APPDATA%`, `%LOCALAPPDATA%`, and both 64-bit and 32-bit `Program Files`.
   - Clears the import cache.
   - Warns with exact elevated command if removal in Program Files requires Administrator elevation.
3. **`doctor.ps1`**:
   - Searches all standard directories for manifests matching `com.pineapplecola.darts`.
   - Checks for duplicate-UUID conflicts.
   - Inspects `StreamDeck.log` for conflicts, connections, and error patterns.
   - Outputs a clear `PASS` / `FAIL` verdict with recommended fixes.

---

## Usage & Live Map Integration

1. **Start DARTS**:
   Run `run.bat` (Windows) or `run.sh` (macOS/Linux).
2. **Open the live map**:
   Navigate to `http://localhost:8766/map` in your web browser. Without an open map tab, the keys display `NO MAP` because layer states are managed by Leaflet in the browser.
3. **Press a key**:
   - On a normal successful toggle, the key face calmly retains its confirmed state rather than flashing a distracting WAIT graphic.
   - The map receives the command via WebSocket and toggles the layer (the browser tab does not need to be active or frontmost, only open and connected).
   - The map reports the confirmed state back to DARTS with the echoed `request_id`.
   - The key updates to `ON` (green) or `OFF` (red).
   - Rapid double-presses while busy are ignored without alarming exclamation-mark alerts. Real errors or timeouts trigger `ERROR` and an alert.
4. **Mouse sync**:
   Toggling layers using the live map's ribbon buttons updates the Stream Deck keys within 1 second.

---

## Settings (Property Inspector)

Clicking any DARTS key in the Stream Deck software opens its Property Inspector:

- **Label**: Override the button text (up to 10 characters; default MAP, IFR, or VFR).
- **Colours**: Customize hex colours for On, Off, Pending/Wait, Offline, and No Map/Stale.
- **Icon file**: Full path to a local PNG/JPG/GIF/SVG (≤ 512 KB) to render above the label.
- **Reset to defaults**: Restores default labels, colours, and layout.
- **DARTS API**: Shared URL across all keys, defaulting to `http://127.0.0.1:8766`. Change only if DARTS is configured on a non-default port.

---

## Reproducible Build & Packaging Pipeline

Building from source requires **Go 1.22+** and **Node.js**:

```sh
cd DARTS/streamdeck/plugin
npm ci
npm run build
npm run validate
npm run pack
```

- **`npm run build`** (`node build.js`):
  Compiles standalone binaries from `src_go/`:
  - `bin/darts-plugin.exe`: Windows amd64 compiled with `CGO_ENABLED=0 -ldflags="-s -w"`.
  - `bin/darts-plugin`: macOS universal Mach-O binary containing both `amd64` and `arm64` slices.
  - Dependencies are vendored in `src_go/vendor/` and compile 100% offline.
- **`npm run validate`** (`npm test && streamdeck validate com.pineapplecola.darts.sdPlugin`):
  Executes the regression test suite and runs Elgato's official manifest schema validator.
- **`npm run pack`** (`streamdeck pack com.pineapplecola.darts.sdPlugin --output dist --force`):
  Builds, validates, and packages the distribution bundle at `dist/com.pineapplecola.darts.streamDeckPlugin`.
- The prebuilt installer is version-controlled at `DARTS/streamdeck/plugin/dist/com.pineapplecola.darts.streamDeckPlugin`.
- See [`BUILD.md`](BUILD.md) for full developer details and cross-compilation internals.

---

## Files & Directory Structure

```text
DARTS/streamdeck/plugin/
├── README.md                                 # This documentation
├── BUILD.md                                  # Developer build & packaging reference
├── build.js                                  # Cross-compilation & universal Mach-O packaging
├── build.sh                                  # Shell wrapper for build
├── package.json                              # Scripts and CLI devDependencies
├── dist/
│   └── com.pineapplecola.darts.streamDeckPlugin  # Prebuilt, self-contained installer (~8 MB)
├── scripts/
│   ├── install-manual.ps1                    # Automated manual-copy installation
│   ├── uninstall.ps1                         # Complete uninstall & clean reset
│   └── doctor.ps1                            # Diagnostic verification & log analyzer
├── src_go/                                   # Standalone Go source code & vendored deps
└── com.pineapplecola.darts.sdPlugin/         # Plugin distribution directory
    ├── manifest.json                         # Plugin definition (CodePathWin / CodePathMac)
    ├── bin/
    │   ├── darts-plugin.exe                  # Standalone Windows x64 executable
    │   ├── darts-plugin                      # Standalone macOS universal executable
    │   ├── plugin.js                         # Reference JS implementation
    │   └── state.js                          # State model & SVG renderer
    ├── ui/
    │   └── settings.html                     # Property Inspector HTML/JS
    └── imgs/                                 # Action icons and category images
```
