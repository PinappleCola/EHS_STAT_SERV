# DARTS Stream Deck plugin (v0.1)

Three coloured, live-state keys for the DARTS live map:

| Action | What a press does | Same as ribbon button |
|--------|-------------------|-----------------------|
| **MAP toggle** | Basemap / network mode on ⇄ off | `MAP TOGGLE` (`btn-network`) |
| **IFR waypoints** | IFR waypoints visible ⇄ hidden | `IFR` (`btn-ifr-toggle`) |
| **VFR waypoints** | VFR waypoints visible ⇄ hidden | `VFR` (`btn-vfr-toggle`) |

Each key shows a large label (MAP / IFR / VFR), a status line, and a coloured background:

| Key face | Default colour | Meaning |
|----------|----------------|---------|
| `ON` | green `#15803D` | basemap on / waypoint layer visible |
| `OFF` | red `#B91C1C` | basemap off / waypoint layer hidden |
| `WAIT` | amber `#B45309` | command sent, waiting for the map to confirm |
| `ERROR` | amber `#B45309` | command failed or was not confirmed within 3 s (shown briefly, then re-syncs) |
| `NO MAP` | grey `#475569` | DARTS is running but no live map page is open |
| `STALE` | grey `#475569` | the map stopped reporting (no update for 6 s) |
| `OFFLINE` | dark `#1E293B` | DARTS is not reachable |

For IFR/VFR, **ON means the layer is enabled** on the map; the global
**ELEMENT TOGGLE** or an empty waypoint file can still mean nothing is drawn.

## How it works

```
Stream Deck app ⇄ plugin (Node.js) ──HTTP──▶ DARTS :8766 ──WebSocket :8765──▶ live map tab
                                     ◀─────── GET /api/ui-state ◀── ui_state reports ──┘
```

- **Press** → `POST /api/ui-command` `{"command":"toggle_ifr","request_id":"sd-…"}`.
  DARTS forwards it over its existing WebSocket to the open live map(s), which run
  the same code as clicking the ribbon button.
- **State** → the live map is authoritative. It reports `mapEnabled`, `ifrEnabled`
  and `vfrEnabled` to DARTS when it connects, after every toggle (Stream Deck or
  mouse click) and every 2 s as a heartbeat. The plugin reads this from
  `GET /api/ui-state` once per second (4×/s while a press is pending).
- After a press the key stays **WAIT** until the map echoes the same `request_id`.
  The plugin never guesses the result. If no confirmation arrives within 3 s the
  key shows **ERROR**, flashes the Stream Deck alert, and then returns to whatever
  the map reports. Toggles are never retried automatically.
- Presses are ignored (alert shown, nothing sent) while the key is `NO MAP`,
  `STALE`, `OFFLINE`, or another press is still pending.
- With several map tabs open, every tab toggles (as before), and the keys show the
  state of the **controlling map** — the earliest-connected tab still open. If it
  closes, the next tab takes over.

### Standalone executable architecture (no managed Node.js dependency)

Unlike plugins that require Stream Deck's managed Node.js runtime (`%APPDATA%\Elgato\StreamDeck\NodeJS\`),
this plugin is compiled into **self-contained native binaries** (`darts-plugin.exe` for Windows and
`darts-plugin` universal binary for macOS) with all dependencies embedded.
It **does not depend on Stream Deck's managed Node.js runtime** or any system-installed Node.js,
so it loads and runs reliably even on machines where `%APPDATA%\Elgato\StreamDeck\NodeJS\` is empty,
absent, or failed to install.

## Automated Windows Development & Testing Workflow

For testing new commits, avoiding folder confusion, and automating plugin deployment and rollback on Windows, use the repository's helper launcher:

```powershell
# From the repository root in PowerShell:
.\tools\dev.ps1 setup    # One-time setup: establish authoritative repo and plugin paths
.\tools\dev.ps1 status   # Inspect deployed version, commit SHA, and detect stray folders
.\tools\dev.ps1 test     # Run all regression tests on current or target commit
.\tools\dev.ps1 deploy   # Safely backup and deploy to Stream Deck AppData
.\tools\dev.ps1 rollback # Instantly restore the last known good build
```

See the complete guide in [DEV_WORKFLOW.md](../../../DEV_WORKFLOW.md).

## Install by double-click (recommended)

Requirements: **Stream Deck app 7.1 or newer**, on the **same computer** as DARTS.
**No Node.js runtime is required.**

The canonical plugin UUID is **`com.pineapplecola.darts`**. Its folder name,
manifest UUID and MAP / IFR / VFR action UUIDs must match; do not rename the
folder or edit its contents.

1. Download [**com.pineapplecola.darts.streamDeckPlugin**](dist/com.pineapplecola.darts.streamDeckPlugin)
   from this repository (use **Download raw file** on GitHub, not Save page).
   A prebuilt installer is committed in `dist/`.
2. **Double-click the downloaded file** and approve installation in Stream Deck.
   Stream Deck installs the whole plugin, including the UI, code, and images.
3. Find **DARTS** in the actions list and drag **MAP toggle**, **IFR waypoints**
   and **VFR waypoints** onto keys.
4. Start DARTS and open the live map as described under **Use** below.

For a clean reinstall after earlier manual edits, fully quit Stream Deck and
remove previous DARTS plugin folders from its Plugins directory first. Reopen
Stream Deck, then double-click the installer. Replace old key actions if they
belonged to a differently named plugin.

## Fallback: manual copy

Use this only if you cannot use the installer. **Copy the ENTIRE `.sdPlugin`
folder unchanged**; never copy or move its `ui`, `bin`, or `imgs` separately.

1. **Fully quit Stream Deck** (Windows: tray icon → Quit; macOS: Stream Deck →
   Quit). Closing its window is not enough.
2. For a clean reinstall, remove any previous DARTS plugin folders from the
   Plugins directory below. Do not merge this download with an edited copy.
3. Copy **`DARTS/streamdeck/plugin/com.pineapplecola.darts.sdPlugin/`** from the
   downloaded repository. Copy the **`com.pineapplecola.darts.sdPlugin` folder
   itself**, not its parent `plugin` folder, into:
   - Windows: `%APPDATA%\Elgato\StreamDeck\Plugins\`
   - macOS: `~/Library/Application Support/com.elgato.StreamDeck/Plugins/`
4. Verify that `manifest.json` is directly inside the installed `.sdPlugin`
   folder, with no extra nesting:

   ```text
   Plugins/
   └── com.pineapplecola.darts.sdPlugin/
      ├── manifest.json
      ├── bin/
      │   ├── darts-plugin.exe   (Windows native binary)
      │   ├── darts-plugin       (macOS universal native binary)
      │   ├── plugin.js
      │   └── state.js
      ├── ui/
      │   └── settings.html
      └── imgs/
   ```

   The installed manifest must be at exactly:
   - Windows: `%APPDATA%\Elgato\StreamDeck\Plugins\com.pineapplecola.darts.sdPlugin\manifest.json`
   - macOS: `~/Library/Application Support/com.elgato.StreamDeck/Plugins/com.pineapplecola.darts.sdPlugin/manifest.json`
5. **Restart the Stream Deck app.** A **DARTS** category appears in the actions list
   with **MAP toggle**, **IFR waypoints** and **VFR waypoints**.
6. Drag each action onto a key. When replacing a differently named plugin,
   remove its old key actions and add these new actions; the new UUID does not
   inherit the old plugin's settings.

To update, use the double-click installer again. Settings for the same UUID are
stored by Stream Deck and are kept.

## Build / validate / package

Building from source requires **Go 1.22+** and **Node.js** (for running the build/validation scripts):

```sh
cd DARTS/streamdeck/plugin
npm ci
npm run build
npm run validate
npm run pack
```

- `npm run build` compiles `bin/darts-plugin.exe` (Windows amd64) and `bin/darts-plugin` (macOS universal binary with x86_64 and arm64 slices) from `src_go/`. Dependencies in `src_go/vendor/` are fully vendored and build 100% offline.
- `npm run validate` runs the regression tests and Elgato's manifest validator.
- `npm run pack` builds, validates, and packages `dist/com.pineapplecola.darts.streamDeckPlugin`.
The prebuilt native binaries and `.streamDeckPlugin` installer are committed in this repository.

Alternatively, install the CLI globally and run its commands directly from
`DARTS/streamdeck/plugin`:

```sh
npm i -g @elgato/cli
node build.js
streamdeck validate com.pineapplecola.darts.sdPlugin
streamdeck pack com.pineapplecola.darts.sdPlugin --output dist --force
```

The validator may warn that category **DARTS** differs from plugin name
**DARTS Live Map**; this is intentional and does not prevent packaging.

## Use

1. Start DARTS (`run.bat` / `run.sh`).
2. **Open the live map**: `http://localhost:8766/map`. Without it the keys show
   `NO MAP` — the layers only exist in the browser.
3. Press a key. It turns amber briefly, then green/red once the map confirms.
   Clicking the ribbon buttons with the mouse updates the keys too.

## Settings (property inspector)

Select a key in the Stream Deck app to change its appearance. This only changes
how the key looks, not what it does.

- **Label** — up to 10 characters (default MAP / IFR / VFR).
- **Colours** — On, Off, Pending/error, Offline, No map/stale.
- **Icon file** — optional full path to a PNG/JPG/GIF/SVG (≤ 512 KB) drawn above
  the label. Leave empty for text only.
- **Reset to defaults** — restores label, colours and icon.
- **DARTS API** (shared by all keys) — defaults to `http://127.0.0.1:8766`. Change
  it only if you changed DARTS' `http_port`.

## Files

| Path | Purpose |
|------|---------|
| `manifest.json` | Plugin and action definitions (specifies native executables per OS) |
| `bin/darts-plugin.exe` | Windows native compiled binary (standalone, no Node runtime required) |
| `bin/darts-plugin` | macOS universal native binary (x86_64 + arm64) |
| `src_go/` | Go source code and offline vendored dependencies |
| `bin/plugin.js` | Reference JavaScript implementation |
| `bin/state.js` | State model (`mapEnabled`, `ifrEnabled`, `vfrEnabled`, `connectionState`, `pendingCommand`) and SVG key-face rendering |
| `ui/settings.html` | Property inspector (label / colours / icon / DARTS URL) |
| `imgs/` | Default plugin, category, action-list and key images |

Tests: `node DARTS/tests/streamdeck_plugin_regression.test.js`.

## Troubleshooting

- **DARTS does not appear in the actions list** — check Stream Deck is 7.1+,
  then use the **double-click installer**.
  - If you previously tried Node-based plugins that failed because Stream Deck's managed Node.js runtime was absent from `%APPDATA%\Elgato\StreamDeck\NodeJS\`, this standalone architecture completely resolves that issue by running as a native executable.
  - For manual copy, verify that `manifest.json`, `bin/darts-plugin.exe` (Windows) or `bin/darts-plugin` (macOS), `ui/settings.html`, and `imgs/` are all inside `%APPDATA%\Elgato\StreamDeck\Plugins\com.pineapplecola.darts.sdPlugin\`.
  - Always fully quit Stream Deck (right click tray icon → Quit) and restart it after installing or modifying plugins.
- **Confirming the plugin loaded** — in Stream Deck Settings → Plugins, **DARTS Live Map** appears in the installed list. In addition, when Stream Deck launches the plugin, the `darts-plugin.exe` (or `darts-plugin`) process will be running in Task Manager / Activity Monitor.
- **All keys `OFFLINE`** — DARTS isn't running, or the DARTS API setting/port is
  wrong. Check `curl http://localhost:8766/api/ui-state`.
- **All keys `NO MAP`** — open (or refresh) `http://localhost:8766/map`. An old
  map tab from before this update does not report state; refresh it.
- **Key goes `ERROR` after a press** — the map didn't confirm within 3 s (tab
  frozen/backgrounded or closed). The key re-syncs automatically.
- Plugin logs are written by the Stream Deck app to its logs folder
  (`%APPDATA%\Elgato\StreamDeck\logs` on Windows).
