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
| 13 | Reserved | — | — |
| 14 | Reserved | — | — |
| 15 | Reserved | — | — |

> The POST keys read the current receiver config and change only `rx_mode` /
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
| GET | `/api/trails/export.geojson` | 2D trail export (GeoJSON) |
| GET | `/api/trails/export3d.geojson` | 3D trail export (Kepler.gl GeoJSON) |
| POST | `/api/rx-config` | Set `rx_mode` (`A`/`B`/`DUAL`) and/or `restart` (`A`/`B`/`BOTH`) |

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
