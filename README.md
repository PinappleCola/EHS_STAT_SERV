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

4. **Testing commits and Stream Deck deployment:**
   For a streamlined Windows workflow that prevents folder confusion and automates testing, deployment, and rollback:
   ```powershell
   .\tools\dev.ps1 setup    # One-time setup: confirm authoritative repository
   .\tools\dev.ps1 status   # Check active commit & detect stray copies
   .\tools\dev.ps1 test     # Run regression test suite
   .\tools\dev.ps1 deploy   # Safely deploy plugin with automatic backup
   .\tools\dev.ps1 rollback # Restore last known good build
   ```
   See [DEV_WORKFLOW.md](DEV_WORKFLOW.md) for full instructions.

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

## Documentation

| Guide | Contents |
|---|---|
| [Windows development workflow](DEV_WORKFLOW.md) | Testing commits, deploying the Stream Deck plugin, diagnostics, and rollback |
| [Stream Deck quickstart](DARTS/STREAMDECK.md) | API-driven keys, scripts, and endpoint reference |
| [Stream Deck plugin guide](DARTS/streamdeck/plugin/README.md) | Plugin installation, configuration, and troubleshooting |
| [Plugin build guide](DARTS/streamdeck/plugin/BUILD.md) | Native builds, validation, and packaging |
| [Button design specification](DARTS/streamdeck/plugin/BUTTON_SPEC.md) | Button behavior and guidance for adding controls |
| [Architecture](DARTS/ARCHITECTURE.md) | Data flow, heading arbitration, and known risks |
| [Data point reference](DARTS/DATA_POINTS.md) | Decoded telemetry fields and static map data |
| [Data validity model](DARTS/DATA_VALIDITY.md) | Confidence classifications and trust guidance |
| [3D trail exports](DARTS/TRAIL_EXPORTS.md) | Export schema, scheduling, retention, and filenames |
| [Sound files](DARTS/SOUND_FILES/README.md) | Sound naming, trigger IDs, and playback behavior |

The vendored Gorilla WebSocket README under `DARTS/streamdeck/plugin/src_go/vendor/`
documents that dependency rather than the DARTS application.

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

The **EXPORT 3D** button downloads `/api/trails/export3d.geojson`; automatic
exports are also supported. See the [3D trail export guide](DARTS/TRAIL_EXPORTS.md)
for the schema, filenames, scheduling, retention, and Kepler.gl workflow. These
decoder-derived values are for visualisation, not safety-critical decisions; see
[Data Validity](DARTS/DATA_VALIDITY.md).

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
