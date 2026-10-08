# DARTS Data Validity & Trust Model

This document classifies the telemetry and derived fields used by DARTS by how much confidence we should place in them when building UI, scoring, alerts, exports, and future analytics.

The intent is not to prove protocol conformance here, but to create a practical engineering trust model:

- **High** — strong confidence, standard ADS-B / Mode-S field, or directly observable receiver/runtime metric.
- **Medium** — useful and likely correct, but partly derived, inferred, or implementation-specific.
- **Low** — experimental, heuristic, or intentionally best-effort; use with caution.

## 1) High-confidence fields

These fields are the safest foundation for the app and should generally be treated as primary truth sources.

| Key | Validity | Why it is trustworthy | Suggested use |
|---|---|---|---|
| `icao` | High | Direct Mode-S aircraft address extraction / parity-based identification. | Primary aircraft identity, joins, deduping, logs. |
| `callsign` | High | Standard ADS-B identification field. | Grid, tag, history, airline lookup seed. |
| `alt` | High | Core altitude field from ADS-B / Mode S decodes. | Grid, trail export, alerts. |
| `speed` | High | Groundspeed derived from velocity messages. | Map motion, trail logic, separation tools. |
| `track` | High | True track from velocity decode. | Movement direction, map heading logic. |
| `heading` | High | Magnetic heading from decode. | Secondary motion display, arbitration input. |
| `lat` | High | CPR-derived latitude. | Map position, audit zones, trails. |
| `lon` | High | CPR-derived longitude. | Map position, audit zones, trails. |
| `squawk` | High | Standard transponder squawk field. | Emergency detection, labels, filters. |
| `tcas_ra` | High | Explicit TCAS RA decoding with state summary. | Safety UI, alarms, sound triggers. |
| `rssi_dbfs` | Medium-High | Receiver-derived signal metric. | Debugging, link quality, antenna health. |

## 2) Medium-confidence fields

These are valuable and should stay in the app, but they are partially derived, arbitrated, inferred, or dependent on decoded context.

| Key | Validity | Why it is medium-confidence | Suggested use |
|---|---|---|---|
| `display_heading` | Medium-High | Arbitrated from track/heading/selected heading with freshness and hysteresis. | Default heading display, map orientation. |
| `display_heading_source` | Medium-High | Describes arbitration outcome, not a raw broadcast fact. | Diagnostics, UI transparency. |
| `selected_heading` | Medium | Comes from selected-state / integrity decoding. Good, but not universal. | Optional integrity views. |
| `selected_alt_source` | Medium | Inferred selected altitude origin. | Advanced cockpit-style views. |
| `selected_altitude` / `target_alt` | Medium | Useful interpretation of selected altitude state. | Advanced target-state panel. |
| `capability_summary` | Medium | Summary of supported BDS capability flags. | Capability overview. |
| `supported_bds` | Medium | Inferred Comm-B capability list. | Debugging, expert views. |
| `gnss_qual` | Medium | Formatted integrity summary (`NACp`, `SIL`, `NICbaro`). | Advanced quality display. |
| `autopilot_mode` | Medium | Derived from BDS 6,2 / TC29. | Expert grid columns. |
| `vnav_mode` | Medium | Derived mode flag. | Expert grid columns. |
| `alt_hold_mode` | Medium | Derived mode flag. | Expert grid columns. |
| `approach_mode` | Medium | Derived mode flag. | Expert grid columns. |
| `lnav_mode` | Medium | Derived mode flag. | Expert grid columns. |
| `tcas_operational` | Medium | Derived operational flag. | Expert grid columns. |
| `wind` | Medium | Either decoded or calculated from motion values. | HUD, meteo panel, export context. |
| `hazard` | Medium | Merged from BDS 4,4 and BDS 4,5 hazard states. | Safety UI, alerts, sound triggers. |
| `airline` | Medium | Callsign-prefix lookup; useful but not broadcast truth. | Tags, sorting, registry UI. |
| `msg_count` | Medium | Runtime counter, valid for app behavior not aircraft truth. | Diagnostics. |
| `data_age_heading` | Medium | Runtime freshness metric. | UI staleness, debugging. |
| `data_age_position` | Medium | Runtime freshness metric. | UI staleness, debugging. |
| `age` | Medium | Application-age of state snapshot. | Coasting logic, row fading. |
| `first_seen` | Medium | App first-seen timestamp. | History and UI. |
| `air_ground` | Medium | Useful but can depend on multiple interpretations and transitions. | State column, logic, labels. |

## 3) Low-confidence / experimental fields

These should remain visible for experimentation, but the app should avoid depending on them for hard decisions without fallback logic.

| Key | Validity | Why it is low-confidence | Suggested use |
|---|---|---|---|
| `vhf1_freq_mhz` | Low | BDS 4,8 interpretation is explicitly noisy / experimental. | Expert-only view. |
| `vhf2_freq_mhz` | Low | Same as above. | Expert-only view. |
| `vhf3_freq_mhz` | Low | Same as above. | Expert-only view. |
| `vhf1_audio` | Low | Heuristic decode; not operational truth. | Expert-only view. |
| `vhf2_audio` | Low | Heuristic decode; not operational truth. | Expert-only view. |
| `vhf3_audio` | Low | Heuristic decode; not operational truth. | Expert-only view. |
| `vhf_guard_audio` | Low | Heuristic decode; not operational truth. | Expert-only view. |
| `qsp_mcp_alt_change` | Low | Quasi-static parameter counter; useful but not canonical. | Diagnostics / advanced cockpit display. |
| `qsp_next_wp_change` | Low | Same. | Diagnostics / advanced cockpit display. |
| `qsp_fms_vmode_change` | Low | Same. | Diagnostics / advanced cockpit display. |
| `qsp_vhf_change` | Low | Same. | Diagnostics / advanced cockpit display. |
| `qsp_meteo_change` | Low | Same. | Diagnostics / advanced cockpit display. |
| `qsp_fms_alt_change` | Low | Same. | Diagnostics / advanced cockpit display. |
| `qsp_baro_change` | Low | Same. | Diagnostics / advanced cockpit display. |
| Some BDS 4,1 / 4,2 / 4,3 / 5,3 / 5,F fields | Low-Medium | Useful but register inference and edge-case ambiguity remain. | Advanced / expert opt-in views only. |

## 4) Trust rules for app design

### Use these fields as hard dependencies
- `icao`
- `callsign`
- `alt`
- `speed`
- `track`
- `heading`
- `lat`
- `lon`
- `squawk`
- `tcas_ra`

### Use these fields with fallback or arbitration
- `display_heading`
- `target_alt`
- `selected_heading`
- `capability_summary`
- `gnss_qual`
- `wind`
- `hazard`
- `airline`

### Keep these fields behind expert toggles or label them clearly
- `vhf*_freq_mhz`
- `vhf*_audio`
- `vhf_guard_audio`
- `qsp_*`
- advanced BDS-derived registers that are still ambiguous

## 5) Implementation notes from the repo

These are especially relevant to future app improvements:

1. **Heading arbitration is intentional.**
   The repo already defines `compute_display_heading()` and documents its freshness gates and hysteresis. This should be preserved as the canonical user-facing heading.

2. **Some values are UI summaries, not raw data.**
   Fields like `sys_mode`, `meteo`, `gnss_qual`, `capability_summary`, `display_heading_source`, and `hazard` are summaries. They are valuable, but they should not be treated as protocol-level facts.

3. **Experimental fields should be isolated.**
   The VHF BDS 4,8 fields and QSP counters should stay in an expert/advanced category so they do not dilute trust in the core display.

4. **Telemetry persistence should follow confidence.**
   Core fields belong in normal telemetry and exports. Experimental fields should either be excluded, stored separately, or clearly flagged as inferred.

5. **UI labels should communicate certainty.**
   If a field is derived or inferred, the label should say so. Example: `DISPLAY HDG`, `CAPABILITIES`, `HDG SOURCE`, `METEO SRC`.

## 6) Recommended next steps

If we use this to improve the app, the most useful follow-up changes would be:

- tag every field in `FIELD_REGISTRY` with a `trust` level
- visually separate raw vs derived vs experimental columns
- add tooltips describing data provenance
- disable persistence or exporting of clearly experimental fields unless explicitly requested
- create a “core truth” subset for safety-critical UI logic

## 7) Practical summary

For most users, the app’s **core truth** is:

- who the aircraft is (`icao`, `callsign`)
- where it is (`lat`, `lon`)
- how it is moving (`speed`, `track`, `heading`, `display_heading`)
- how high it is (`alt`)
- whether it is in an emergency or RA state (`squawk`, `tcas_ra`)

Everything else is either derived support data or advanced inference.
