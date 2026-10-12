# Stream Deck batch files

Ready-to-use `.bat` files for driving DARTS from an Elgato Stream Deck on
**Windows**. Each file runs one action against the local DARTS HTTP API
(`http://localhost:8766` by default).

See `../STREAMDECK.md` for the full guide, key layout, and Raspberry Pi / Linux
equivalents.

## How to use

1. Make sure DARTS is running (`DARTS/run.bat`).
2. In the Stream Deck software, add a **System → Open** action to a key.
3. For the **App / File**, browse to the `.bat` file you want.
4. Give the key a title and press it.

> Tip: for the two "open a page" actions (map and grid) you can skip the batch
> files and use the **System → Website** action with the URL directly.

## What each file does

| File | Type | What it does |
|------|------|--------------|
| `key01_map.bat` | open page | Opens the live map in your browser |
| `key02_grid.bat` | open page | Opens the live grid (table) in your browser |
| `key03_export3d.bat` | save data | Saves the 3D trail export to your Downloads folder |
| `key04_export2d.bat` | save data | Saves the 2D trail export to your Downloads folder |
| `key05_rx_status.bat` | show info | Prints whether receiver A/B is connected |
| `key06_rx_config.bat` | show info | Prints the current receiver mode and ports |
| `key07_audit_alerts.bat` | show info | Prints any active audit alerts |
| `key08_mode_a.bat` | control | Switches to single-receiver mode A (restarts A) |
| `key09_mode_b.bat` | control | Switches to single-receiver mode B (restarts B) |
| `key10_mode_dual.bat` | control | Switches to DUAL mode (restarts both receivers) |
| `key11_restart_a.bat` | control | Restarts receiver A without changing mode |
| `key12_restart_b.bat` | control | Restarts receiver B without changing mode |

## Changing the port

If your DARTS HTTP API is not on port 8766, edit the `BASE` line near the top of
each file and set it to your port, for example:

```bat
set "BASE=http://localhost:9000"
```
