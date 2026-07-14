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

## Dual-Receiver Mode (SIGINT triangulation)

Set `"rx_mode": "DUAL"` and configure both `receiver_a` and `receiver_b` ports.
DARTS will deduplicate frames received by both antennas and use time-difference
of arrival to triangulate transmitter positions.
