# DARTS Architecture — Data Flow & Heading Arbitration

## Version
v55 — ATC-grade data flow forensic audit + heading/map stability + UI/UX upgrades

---

## End-to-End Data Flow

```
┌─────────────┐    Beast Raw     ┌──────────────┐     decode      ┌───────────────────┐
│  ADSBee 1090 │ ──────────────► │ serial_reader │ ────────────► │  process_frame()   │
│  (Hardware)  │  @115200 baud   │   _thread()  │   0x33 frames  │  pipeline.decode() │
└─────────────┘                  └──────────────┘                └───────────────────┘
                                                                          │
                                                                          ▼
                                                          ┌───────────────────────────┐
                                                          │   update_aircraft(icao,    │
                                                          │      key, value)           │
                                                          │   + state_lock mutex       │
                                                          │   + timestamp tracking     │
                                                          └───────────────────────────┘
                                                                          │
                                                                          ▼
                                                          ┌───────────────────────────┐
                                                          │   aircraft_state[icao]     │
                                                          │   (global dict, ~50 keys)  │
                                                          └───────────────────────────┘
                                                                          │
                                                              every 1 second
                                                                          ▼
                                                          ┌───────────────────────────┐
                                                          │  broadcast_state()         │
                                                          │  + compute_display_heading │
                                                          │  + latency instrumentation │
                                                          │  → WebSocket JSON payload  │
                                                          └───────────────────────────┘
                                                                          │
                                                        ws://localhost:8765
                                                                          ▼
                                                  ┌─────────────────────────────────┐
                                                  │  Frontend (live_map / live_grid) │
                                                  │  + trail accumulation           │
                                                  │  + 60fps render loop            │
                                                  └─────────────────────────────────┘
```

## Latency Budget (per hop)

| Hop | Typical Latency | Notes |
|-----|-----------------|-------|
| RF → ADSBee decode | ~1ms | Hardware |
| Serial transfer | ~5ms | 115200 baud, 14-byte frames |
| Frame parse + decode | ~0.5ms | Python bit manipulation |
| State update | ~0.1ms | Dict write under lock |
| Broadcast interval | 0-1000ms | 1Hz WebSocket emit cycle |
| WebSocket transfer | <1ms | Localhost only |
| Frontend parse + render | ~2-5ms | JSON parse + canvas draw |
| **Total worst case** | **~1010ms** | Dominated by broadcast interval |

## Heading Arbitration (display_heading)

### Problem
Multiple heading sources update at different rates, from different BDS registers, with different reference frames (magnetic vs true). Without arbitration, the map can show brief reversals when:
- BDS 6,0 (magnetic heading) and BDS 5,0 (true track) disagree momentarily
- One source goes stale while another updates
- Track reverses briefly during turbulence while heading remains stable

### Solution: `compute_display_heading()`

**Priority order (highest first):**
1. `track` (true track from BDS 5,0 / DF17 velocity) — freshness gate: 8s
2. `heading` (magnetic heading from BDS 6,0) — freshness gate: 12s
3. `selected_heading` (autopilot target from BDS 6,2/TC29) — freshness gate: 30s
4. Hold-last-good fallback

**Hysteresis filter:**
- Rejects heading jumps > 45° in < 2s unless validated by track_rate
- Maximum allowed rate: max(6°/s, |track_rate| × 1.5) + 5° jitter margin
- Prevents map "snap" on spurious decode or source contention

**Canonical usage:**
- `display_heading` is emitted in every WebSocket frame
- Map uses `display_heading` for aircraft rotation + prediction vector
- Grid uses `display_heading` in heading widget (falls back to raw `heading`)
- Data tags use `display_heading` for heading display

### Field Lineage

| Field | Source Register | Units/Reference | Typical Cadence | Staleness Threshold |
|-------|----------------|-----------------|-----------------|---------------------|
| `track` | BDS 5,0 bits 12-22 | True (°) | 1-5s | 8s |
| `heading` | BDS 6,0 bits 1-11 | Magnetic (°) | 1-5s | 12s |
| `selected_heading` | BDS 6,2/TC29 bits 17-26 | True (°) | 5-30s | 30s |
| `display_heading` | Arbitrated | Best available (°) | 1s (emit cycle) | N/A |
| `track_rate` | BDS 5,0 bits 35-44 | °/s | 1-5s | 8s |

---

## Deep Field Catalog (v55 additions)

| Key | Label | Unit | Category | Source | Default Visible |
|-----|-------|------|----------|--------|-----------------|
| `display_heading` | DISPLAY HDG | deg | KINEMATICS | Arbitrated | ✓ |
| `display_heading_source` | HDG SOURCE | — | KINEMATICS | Arbitration | — |
| `vert_rate_baro` | BARO VR | ft/min | KINEMATICS | BDS 6,0 | — |
| `vert_rate_inertial` | INERT VR | ft/min | KINEMATICS | BDS 6,0 | — |
| `alt_mcp` | ALT MCP | ft | ALTITUDE | BDS 4,0 | — |
| `alt_fms` | ALT FMS | ft | ALTITUDE | BDS 4,0 | — |
| `wind_speed` | WIND SPD | kt | METEO | BDS 4,4 | — |
| `wind_direction` | WIND DIR | deg | METEO | BDS 4,4 | — |
| `static_pressure` | STATIC P | hPa | METEO | BDS 4,4/4,5 | — |
| `turbulence_level` | TURB LVL | — | SAFETY | BDS 4,4 | — |
| `msg_count` | MSG COUNT | — | SURVEILLANCE | Sys Counter | — |
| `data_age_heading` | HDG AGE | s | SURVEILLANCE | Sys Clock | — |
| `data_age_position` | POS AGE | s | SURVEILLANCE | Sys Clock | — |

---

## Altitude Trail Color Scheme (v55)

Non-red, colorblind-safe, perceptually ordered:

| Altitude Band | Color | RGB |
|---------------|-------|-----|
| GROUND | Orange | (249, 115, 22) |
| < FL100 | Sky Blue | (56, 189, 248) |
| FL100–200 | Teal/Mint | (52, 211, 153) |
| FL200–300 | Purple | (168, 85, 247) |
| FL300–400 | Amber/Gold | (251, 191, 36) |
| ≥ FL400 | Pink | (244, 114, 182) |

---

## Hold-Alt Tool Confidence Model (v55)

When two aircraft are dual-selected for separation measurement:

| Time Delta (|age₁ - age₂|) | Confidence | Indicator |
|-----------------------------|------------|-----------|
| ≤ 5s | HIGH | Green dot |
| 5–10s | MED | Yellow dot |
| > 10s | LOW | Grey dot |

Displayed alongside separation measurements with exact Δt value.

---

## Residual Risks

1. **GeoJSON race condition**: `AIRSPACE_GEOJSON` still has no dedicated lock for concurrent writes from SIGINT solver and WebSocket receiver. Low probability of corruption but theoretically possible under high SIGINT activity.

2. **Shallow copy in broadcast**: Nested dicts (`latest_sys_log`, `latest_intent`) use `.copy()` which is shallow. Safe only because nested objects are replaced atomically, never mutated in-place.

3. **Heading arbitration edge case**: During rapid heading source switching (e.g., aircraft transitioning from radar-only to ADS-B), there may be a single 1s frame where hysteresis holds an incorrect value. This is by design (stability over immediate accuracy).

4. **No position extrapolation**: Aircraft positions are displayed only at last-received coordinates. During data gaps, aircraft appear stationary rather than continuing on predicted path. This is intentional for a surveillance display but may confuse operators unfamiliar with the system.
