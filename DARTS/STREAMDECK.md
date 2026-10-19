# Stream Deck Quickstart (DARTS)

Drive DARTS from an Elgato **Stream Deck (15 keys)** using the existing DARTS HTTP
API — **no code changes required**. Each key runs a `curl` command (or opens a URL)
against the local HTTP API server.

> DARTS exposes its HTTP API on `http://localhost:8766` by default
> (`http_port` in `runtime_config.json`, or the `EHS_HTTP_PORT` env var).
> All commands below assume that default. If you changed the port, update the
> `BASE` value accordingly.

---

## 1. One-time setup

### Confirm the API is reachable

With DARTS running, open a terminal and check RX status:

```bash
curl http://localhost:8766/api/rx-status
```

You should get a JSON blob with receiver `A`/`B` state. If you get a connection
error, make sure DARTS is running and that the port matches your config.

### Where to put commands on the Stream Deck

- **Open a URL (map/grid):** use the built-in **System → Website** action, or
  **System → Open** with the URL.
- **Run a `curl` command:** use **System → Open** and point it at a small script
  (`.bat` on Windows, `.sh` on Pi/Linux). Stream Deck's "Open" action runs any
  executable/script. One script per key is the simplest, most reliable setup.

Create a `streamdeck/` folder somewhere convenient and drop the scripts below in it.

### Want coloured live-state keys instead? (MAP / IFR / VFR)

The batch files can't show anything on the key face. For coloured live-state keys,
the **DARTS Stream Deck plugin** uses confirmed state from the open live map.
It requires Stream Deck 7.1+ and ships as a self-contained native executable; it
does not depend on Stream Deck's managed Node.js runtime.

See the [plugin guide](streamdeck/plugin/README.md) for installation, manual
fallback, clean reset, troubleshooting, and settings. That guide is the canonical
source for plugin setup and support.

---

## 2. Suggested 15-key layout

| Key | Action | Endpoint / URL | Method |
|-----|--------|----------------|--------|
| 1 | Open Live Map | `http://localhost:8766/map` | open URL |
| 2 | Open Live Grid | `http://localhost:8766/grid` | open URL |
| 3 | Export 3D trails (Kepler.gl) | `/api/trails/export3d.geojson` | GET |
| 4 | Export 2D trails | `/api/trails/export.geojson` | GET |
| 5 | RX status | `/api/rx-status` | GET |
| 6 | RX config (inspect) | `/api/rx-config` | GET |
| 7 | Audit alerts | `/api/audit-alerts` | GET |
| 8 | Switch to RX mode **A** | `/api/rx-config` `{"rx_mode":"A","restart":"A"}` | POST |
| 9 | Switch to RX mode **B** | `/api/rx-config` `{"rx_mode":"B","restart":"B"}` | POST |
| 10 | Switch to **DUAL** | `/api/rx-config` `{"rx_mode":"DUAL","restart":"BOTH"}` | POST |
| 11 | Restart receiver **A** | `/api/rx-config` `{"restart":"A"}` | POST |
| 12 | Restart receiver **B** | `/api/rx-config` `{"restart":"B"}` | POST |
| 13 | Toggle basemap (MAP TOGGLE) | `/api/ui-command` `{"command":"toggle_map"}` | POST |
| 14 | Toggle IFR waypoints | `/api/ui-command` `{"command":"toggle_ifr"}` | POST |
| 15 | Toggle VFR waypoints | `/api/ui-command` `{"command":"toggle_vfr"}` | POST |

> The receiver POST keys (8–12) read the current receiver config and change only `rx_mode` /
> `restart`. If you run a single receiver, keys 9 and 12 can be left unused.

---

## 3. Windows (`.bat`) scripts

Save each as its own file (e.g. `streamdeck/key03_export3d.bat`) and point the
Stream Deck **System → Open** action at it.

### Open map / grid (keys 1–2)
Use the **System → Website** action instead of a script:
- Key 1 → `http://localhost:8766/map`
- Key 2 → `http://localhost:8766/grid`

### GET endpoints (keys 3–7)

```bat
:: key03_export3d.bat — download the 3D trail export to Downloads
@echo off
set "BASE=http://localhost:8766"
set "OUT=%USERPROFILE%\Downloads\darts_export3d.geojson"
curl -s "%BASE%/api/trails/export3d.geojson" -o "%OUT%"
echo Saved to %OUT%
```

```bat
:: key04_export2d.bat
@echo off
set "BASE=http://localhost:8766"
set "OUT=%USERPROFILE%\Downloads\darts_export2d.geojson"
curl -s "%BASE%/api/trails/export.geojson" -o "%OUT%"
echo Saved to %OUT%
```

```bat
:: key05_rx_status.bat — print RX status and pause so you can read it
@echo off
curl -s http://localhost:8766/api/rx-status
echo.
pause
```

(Keys 6 and 7 are the same as key 5 with `/api/rx-config` and `/api/audit-alerts`.)

### POST endpoints (keys 8–12)

```bat
:: key10_dual.bat — switch to DUAL mode and restart both receivers
@echo off
curl -s -X POST http://localhost:8766/api/rx-config ^
  -H "Content-Type: application/json" ^
  -d "{\"rx_mode\":\"DUAL\",\"restart\":\"BOTH\"}"
echo.
```

```bat
:: key08_mode_a.bat — switch to single-receiver mode A
@echo off
curl -s -X POST http://localhost:8766/api/rx-config ^
  -H "Content-Type: application/json" ^
  -d "{\"rx_mode\":\"A\",\"restart\":\"A\"}"
echo.
```

```bat
:: key11_restart_a.bat — restart receiver A without changing mode
@echo off
curl -s -X POST http://localhost:8766/api/rx-config ^
  -H "Content-Type: application/json" ^
  -d "{\"restart\":\"A\"}"
echo.
```

> On Windows `.bat`, inner quotes in the JSON body must be escaped with `\"`.

### Live map toggles (keys 13–15)

Ready-to-use files are in `streamdeck/key13_toggle_map.bat`,
`streamdeck/key14_toggle_ifr.bat`, and `streamdeck/key15_toggle_vfr.bat`.
Point a **System → Open** action at each file.

```bat
@echo off
set "BASE=http://localhost:8766"
curl -s -X POST "%BASE%/api/ui-command" -H "Content-Type: application/json" -d "{\"command\":\"toggle_map\"}"
echo.
timeout /t 2 >nul
```

Use `toggle_ifr` or `toggle_vfr` for the other two keys.
On Pi/Linux, use `curl -s -X POST http://localhost:8766/api/ui-command -H "Content-Type: application/json" -d '{"command":"toggle_ifr"}'`.

**The live map page must be open in a browser**: these layers render client-side.
The command toggles each connected map's current state, exactly like clicking its
ribbon button, including label/active styling. With no map client connected, the
command is accepted but has no visible effect. Commands are not saved for later.

---

## 4. Raspberry Pi 5 / Linux (`.sh`) scripts

Make each script executable: `chmod +x key03_export3d.sh`.

```bash
#!/usr/bin/env bash
# key03_export3d.sh — download the 3D trail export
BASE="http://localhost:8766"
OUT="$HOME/Downloads/darts_export3d.geojson"
mkdir -p "$HOME/Downloads"
curl -s "$BASE/api/trails/export3d.geojson" -o "$OUT"
echo "Saved to $OUT"
```

```bash
#!/usr/bin/env bash
# key05_rx_status.sh
curl -s http://localhost:8766/api/rx-status | python3 -m json.tool
```

```bash
#!/usr/bin/env bash
# key10_dual.sh — switch to DUAL mode and restart both receivers
curl -s -X POST http://localhost:8766/api/rx-config \
  -H "Content-Type: application/json" \
  -d '{"rx_mode":"DUAL","restart":"BOTH"}'
```

```bash
#!/usr/bin/env bash
# key11_restart_a.sh — restart receiver A without changing mode
curl -s -X POST http://localhost:8766/api/rx-config \
  -H "Content-Type: application/json" \
  -d '{"restart":"A"}'
```

> On Linux, the Stream Deck app is community software
> (e.g. `streamdeck-ui` / `streamdeck_ui`). Map each key's command to run the
> matching `.sh` script (for example: `bash /path/to/key10_dual.sh`).

---

## 5. Endpoint reference

All relative to `http://localhost:8766` (the fixed HTTP API server).

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/map` | Live map (browser) |
| GET | `/grid` | Live grid (browser) |
| GET | `/api/rx-status` | Receiver A/B connected state + last-frame age |
| GET | `/api/rx-config` | Current `rx_mode`, receiver_a/b config |
| GET | `/api/audit-alerts` | Active audit alerts |
| GET | `/api/night-config` | Clamped Night Mode brightness levels from `runtime_config.json` |
| GET | `/api/trails/export.geojson` | 2D trail export (GeoJSON) |
| GET | `/api/trails/export3d.geojson` | 3D trail export (Kepler.gl GeoJSON) |
| POST | `/api/rx-config` | Set `rx_mode` (`A`/`B`/`DUAL`) and/or `restart` (`A`/`B`/`BOTH`) |
| POST | `/api/ui-command` | Send a map command: `toggle_map`, `toggle_ifr`, `toggle_vfr`, `span_30m`, `span_1h`, `span_2h`, `span_4h`, `span_day`, `toggle_night`, `toggle_osd`, or `export_3d` |
| GET | `/api/ui-state` | Toggle, trail-span, Night/OSD, and export lifecycle state reported by the controlling live map |

`/api/ui-command` returns `{"ok": true, "command": "<command>"}` on success.
Missing/invalid commands or malformed JSON return HTTP 400 with `{"error":"..."}`.
If the WebSocket server is unavailable or delivery times out, it returns HTTP 503.
An optional `"request_id"` (1–64 characters of `A-Z a-z 0-9 _ . : -`) is echoed in
the response, forwarded to the map, and reported back by the map in
`/api/ui-state` `lastRequestId` once applied — this is how the plugin confirms a press.

`/api/ui-state` example:

```json
{"connectionState": "connected", "mapEnabled": false, "ifrEnabled": true, "vfrEnabled": true,
 "activeSpan": "2h", "nightMode": false, "osdVisible": true, "exportState": "idle", "exportProgress": null,
 "lastRequestId": "sd-…", "stateAgeMs": 840, "revision": 7, "mapClients": 1, "staleAfterMs": 6000}
```

`connectionState` is `connected`, `no_map` (no live map page open; map toggle fields
are `null`) or `stale` (the map hasn't reported for more than 6 s). `activeSpan` is
`30m`, `1h`, `2h`, `4h`, `day`, or `null`; `exportState` is `idle`, `working`, `done`,
or `error`; `exportProgress` is nullable and ranges from 0 to 100. The live map
reports over its existing WebSocket (`{"action":"ui_state", ...}`) on connect, after
state changes, and every 2 s. With several map tabs open, the earliest-connected tab
is the controlling map whose state is reported.

Night Mode brightness can be tuned in `DARTS/runtime_config.json` using the
independent `brightness_map`, `brightness_elements`, and `brightness_trails`
settings (each defaults to `0.4`, clamped to `[0,1]`). Audit point defaults are
INNER `0.1 NM` and OUTER `0.3 NM`.

---

## 6. Notes & limitations

- These keys use **only endpoints that already exist** in `darts.py`
  (`DARTSAPIHandler`). No app changes are needed.
- Actions that live purely in the browser map (clear trails, mute sound,
  arm/disarm audit) do **not** have HTTP endpoints yet, so they can't be keyed
  this way without adding server-side routes. That's a natural next step.
- The API binds to `localhost`, so the Stream Deck's host must be the **same
  machine** running DARTS. Driving a remote DARTS instance would require binding
  the HTTP server to a reachable interface (not currently configurable) — treat
  that as out of scope for this quickstart.
- Trail exports accept optional `from`, `to` (epoch ms) and `icao` query
  parameters; omitting them exports the default maximum window.
- Batch/URL keys cannot show live data on the Stream Deck key face; use the
  [DARTS Stream Deck plugin](streamdeck/plugin/README.md) for live MAP / IFR / VFR
  key colours and interactive status.
- The browser live map does **not** need to be the active/frontmost window for
  Stream Deck plugin toggles to work; it only needs to remain open and connected.
- For full details on the confirmed-toggle button standard, state transitions, and
  how to add new buttons, see [BUTTON_SPEC.md](streamdeck/plugin/BUTTON_SPEC.md).
