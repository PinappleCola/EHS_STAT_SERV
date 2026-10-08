# EHS_STAT_SERV — DART-B ADS-B Decoder

Real-time ADS-B/Mode-S decoder and surveillance display. Reads Beast-raw frames
from an **ADSBee 1090** USB receiver, decodes Extended Squitter and EHS (Enhanced
Surveillance) registers, and serves a live map and grid via WebSocket + HTTP.

Runs on **Raspberry Pi 5** and **Windows 10/11** (Python 3.8+).

---

## Requirements

- Python 3.8 or later
- An [ADSBee 1090](https://adsbee.io) receiver connected via USB

---

## Quick Start

### Raspberry Pi 5 / Linux

1. **Grant serial port access** (one-time; log out and back in after):
   ```bash
   sudo usermod -aG dialout $USER
   ```

2. **Find your serial port:**
   ```bash
   ls /dev/ttyACM* /dev/ttyUSB* 2>/dev/null
   ```
   The ADSBee 1090 typically appears as `/dev/ttyACM0`.

3. **Configure the port** in `DARTS/runtime_config.json` if it differs from the
   default (`/dev/ttyACM0`):
   ```json
   {
       "port": "/dev/ttyACM0",
       "receiver_a": { "port": "/dev/ttyACM0" }
   }
   ```

4. **Run:**
   ```bash
   cd DARTS
   bash run.sh
   ```
   The script creates a virtual environment, installs dependencies, and starts DARTS.

---

### Windows 10 / 11

1. **Find your COM port:** open Device Manager → Ports (COM & LPT). The ADSBee 1090
   typically appears as *USB Serial Device (COMx)*.

2. **Configure the port** in `DARTS/runtime_config.json` if it differs from the
   default (`COM5`):
   ```json
   {
       "port": "COM5",
       "receiver_a": { "port": "COM5" }
   }
   ```

3. **Run** (double-click or from a Command Prompt):
   ```bat
   cd DARTS
   run.bat
   ```
   The script creates a virtual environment, installs dependencies, and starts DARTS.

---

## Manual Setup (any platform)

```bash
cd DARTS
python3 -m venv .venv
# Linux/macOS:  source .venv/bin/activate
# Windows:      .venv\Scripts\activate.bat
pip install -r requirements.txt
python darts.py
```

---

## Interfaces

| Interface | Default address | Description |
|-----------|----------------|-------------|
| WebSocket | `ws://localhost:8765` | Live aircraft state (1 Hz) |
| HTTP API  | `http://localhost:8766` | Field definitions, grid config |
| Live map  | `http://localhost:8766/map` | Browser map view |
| Live grid | `http://localhost:8766/grid` | Browser tabular view |

---

## Sound alerts

- Put alert WAV files in `DARTS/SOUND_FILES/` using `XX_description.wav`.
- IDs `01`-`07` are active sound triggers, while `08`-`10` are reserved for future use.
- DARTS ignores missing numbered files, so unconfigured sounds stay silent without failing the app.
- Sound playback happens in the browser live map over the existing localhost HTTP/WebSocket stack, so browser autoplay rules may require a click or other user interaction before audio can play.
- WAV clips under about five seconds are recommended; larger uncompressed files increase transfer, memory, and startup cost.

See `DARTS/SOUND_FILES/README.md` for the current ID map and duplicate-file behavior.

---

## Configuration (`DARTS/runtime_config.json`)

| Key | Default (Windows) | Default (Pi/Linux) | Description |
|-----|------------------|--------------------|-------------|
| `port` | `COM5` | `/dev/ttyACM0` | Primary receiver serial port |
| `baud` | `115200` | `115200` | Baud rate |
| `ws_host` | `localhost` | `localhost` | WebSocket bind address |
| `ws_port` | `8765` | `8765` | WebSocket port |
| `http_port` | `8766` | `8766` | HTTP API port |
| `rx_mode` | `A` | `A` | Receiver mode: `A`, `B`, or `DUAL` |

All keys can also be overridden with environment variables:
`EHS_PORT`, `EHS_BAUD`, `EHS_WS_HOST`, `EHS_WS_PORT`, `EHS_HTTP_PORT`, `EHS_RECEIVER_ID`.

---

## 3D trail exports (Kepler.gl)

The map's **EXPORT 3D** button downloads `/api/trails/export3d.geojson` and
atomically saves the same file in `DARTS/3DSPAT_SAVES/`. The existing 2D export
is unchanged. Each 3D feature is one pair of consecutive valid observations;
gap/jump markers and unknown airborne altitude break the chain. Exact duplicates
and zero-length segments are omitted.

Coordinates are `[longitude, latitude, z]`: `z` is barometric **pressure altitude**
converted from feet to metres (rounded to 0.1 m), **not ellipsoidal height**.
Ground is zero; valid negative altitude is preserved. Flat properties carry
start-sample historical telemetry, never current live-state backfills. Track
expires after 8 seconds; heading and other telemetry expire after 12 seconds.
Unobserved TCAS (including the initial UI default `CLEAN`), stale values, invalid
numbers, and fields absent in older rows export as `null`. Squawk remains text.

Filenames follow `3DSPAT_DDMMMYY_HHMM_MMMM_XXXX.geojson`, for example
`3DSPAT_08OCT26_1329_0397_00F4.geojson`. Date/time are the **first sample in
Australia/Sydney**, English uppercase month (including MAY); duration is real
elapsed whole minutes, padded to four digits and capped at 9999. Empty manual
exports use the requested start and duration `0000`.

Automatic files have an `AUTO_` prefix and go in `DARTS/AUTO_3DSPAT_SAVES/`.
Both directories are created automatically and ignored by Git.
The trail database (`DARTS/data/trails.db` by default) contains `export_log` and
a persistent serial counter shared by manual/automatic exports. Serials start
at `0000`, increment transactionally, and wrap after `FFFF` with a warning.
Every attempt is logged (`ok`, `empty`, or `error`); empty automatic windows
write no file and consume no serial. Failed attempts may consume a serial.
Skipped automatic attempts use audit serial `-1` and an empty `serial_hex`;
they do not advance the counter.

Daily export configuration (preserved when receiver settings are saved):

```json
"3DGEO_AUTO_EXPORT_ENABLE": 1,
"3DGEO_AUTO_EXPORT_DAILY_TIME": "2400",
"3DGEO_AUTO_EXPORT_TIMEZONE": "Australia/Sydney"
```

Override enable/time with `EHS_3DGEO_AUTO_EXPORT_ENABLE` and
`EHS_3DGEO_AUTO_EXPORT_DAILY_TIME`. Time accepts HHMM strings or integers;
`2400` and `0000` both mean midnight, invalid times warn and use midnight.
Configuration changes take effect after restart.

The first scheduled run is strictly **after startup**; exports missed while
offline are **not back-filled**. Windows span the previous to current Sydney
scheduled instant, so midnight windows can be 23 or 25 hours across DST.
Scheduling follows local wall-clock dates, not fixed 86400-second increments.
Non-existent times run at the first valid instant after the requested time;
ambiguous times run once using the first occurrence (`fold=0`).
The daemon rechecks the clock at least every 30 seconds.
Automatic queries bypass the manual 1440-minute limit. Default retention is
26 hours, and pruning enforces at least 26 hours while auto export is enabled
to protect the 25-hour day. `tzdata` supplies timezone data on Windows;
Python 3.8 uses `backports.zoneinfo`.
Pruning also protects the pending automatic window until its export attempt
finishes, including after delayed wakes.

In Kepler.gl, enable 3D/elevation, colour by `altitude_ft`, size the stroke by
`groundspeed_kt` (or a derived `abs(vert_rate_fpm)`), filter on `tcas_active`,
and use epoch-seconds `start_ts` for the time filter. Metadata identifies
schema `darts-3dspat-v1`, units, UTC generation/window times, filename and serial.
Decoder-derived values are for visualisation, not safety-critical decisions;
see `DARTS/DATA_VALIDITY.md`.

---

## Waypoint Scoring LUT

Waypoint scoring defaults and score-to-colour bands are configured in:

- `DARTS/waypoint_scoring_lut.json`

Supported keys:
- `SCORING_RAD_INNER` (NM)
- `SCORING_RAD_OUTER` (NM)
- `POINTS_DECAY_PER_HOUR`
- `RAD_OUT_CROSS_AWARD`
- `RAD_IN_CROSS_AWARD`
- `SCORE_TABLE` entries with `SCORE` and `COLOUR_STATE` (`[R,G,B]`)

---

## Dual-Receiver Mode (SIGINT triangulation)

Set `"rx_mode": "DUAL"` and configure both `receiver_a` and `receiver_b` ports.
DARTS will deduplicate frames received by both antennas and use time-difference
of arrival to triangulate transmitter positions.
