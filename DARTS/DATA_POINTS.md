# DARTS Data Point Reference Table

Every telemetry field decoded by DARTS, showing its register source, unit, data size, and how it appears across database, grid, and map.

All fields are stored in the `aircraft_state` dictionary, emitted over WebSocket, persisted to the `telemetry` SQLite table (on value change), and rendered in both the live grid and map tag displays.

| Register | Key | Description | Unit | Data Size | Example DB Entry | Example Grid Readout | Example Map Tag Readout |
|---|---|---|---|---|---|---|---|
| **IDENTIFICATION** | | | | | | | |
| PI Parity | `icao` | ICAO 24-bit address | — | 24 bits | `4CA682` | `4CA682` | `4CA682` |
| DF17 TC:1-4 | `callsign` | Flight callsign (ICAO 6-bit charset) | — | 48 bits (8×6) | `BAW452` | `BAW452` | `BAW452` |
| DB Lookup | `airline` | Airline name from callsign prefix | — | derived | `British Airways` | `British Airways` | `British Airways` |
| DF11 / DF21 | `squawk` | Transponder squawk code | — | 13 bits | `4521` | `4521` | `4521` |
| DF17 TC / Mode S | `air_ground` | Air/ground status | — | 1-3 bits | `AIR` | `AIR` | `AIR` |
| **ALTITUDE** | | | | | | | |
| DF17 / DF20 | `alt` | Barometric altitude | ft | 12 bits | `36025` | `36,025 ft` | `36,025 ft ≈` |
| BDS 4,0 | `target_alt` | Selected target altitude (MCP/FMS) | ft | 12 bits | `MCP:35008ft` | `MCP:35008ft` | `MCP:35008ft` |
| BDS 4,0 | `alt_mcp` | MCP/FCU selected altitude (raw) | ft | 12 bits | `35008` | `35008` | `35008` |
| BDS 4,0 | `alt_fms` | FMS selected altitude (raw) | ft | 12 bits | `36000` | `36000` | `36000` |
| BDS 4,5 | `radio_height` | Radio altimeter height | ft | 12 bits | `1520` | `1520 ft` | `1520 ft` |
| **KINEMATICS** | | | | | | | |
| BDS 6,0 | `vert_rate` | Primary vertical rate (baro or inertial) | ft/min | 10 bits | `-1280` | `<span>-1280 ft/min</span>` | `---- (virtual)` |
| BDS 6,0 | `vert_rate_baro` | Barometric vertical rate | ft/min | 10 bits (1+9) | `-640` | `-640` | `-640 fpm` |
| BDS 6,0 | `vert_rate_inertial` | Inertial vertical rate | ft/min | 10 bits (1+9) | `512` | `512` | `+512 fpm` |
| BDS 6,0 | `inertial_vr` | Inertial VR (display alias) | ft/min | 10 bits (1+9) | `512` | `+512 ft/min` | `512 fpm` |
| BDS 5,0 / TC19 | `speed` | Ground speed | kt | 10 bits | `462` | `462 kt` | `462 kt` |
| BDS 5,0 | `tas` | True airspeed | kt | 10 bits | `448` | `448 kt` | `448 kt` |
| BDS 6,0 | `ias` | Indicated airspeed | kt | 10 bits | `272` | `272 kt` | `272 kt` |
| BDS 6,0 | `mach` | Mach number | — | 10 bits | `0.784` | `M0.784` | `M0.784` |
| BDS 6,0 | `heading` | Magnetic heading | deg | 11 bits (1+10) | `247.38` | `247° (dial)` | `247°` |
| Arbitrated | `display_heading` | Display heading (track→heading→sel) | deg | virtual | `247.38` | `247° (dial)` | `247°` |
| BDS 5,0 | `track` | True track angle | deg | 11 bits (1+10) | `249.12` | `249.12°` | `249°T` |
| BDS 5,0 | `track_rate` | Track angle rate | deg/s | 10 bits (1+9) | `-0.25` | `-0.25°/s` | `-0.25°/s` |
| BDS 5,0 | `roll` | Roll / bank angle | deg | 10 bits (1+9) | `-3.52` | `-3.52° (dial)` | `-3.52°` |
| BDS 5,3 | `air_vector_heading` | Air-referenced heading | deg | 11 bits (1+10) | `248.44` | `248.44°` | `248.44°` |
| BDS 5,3 | `air_vector_ias` | Air-referenced IAS | kt | 10 bits | `275` | `275 kt` | `275 kt` |
| BDS 5,3 | `air_vector_mach` | Air-referenced Mach | — | 9 bits | `0.792` | `M0.792` | `M0.792` |
| BDS 5,3 | `air_vector_tas` | Air-referenced TAS | kt | 12 bits | `452.5` | `452.5 kt` | `452.5 kt` |
| BDS 5,3 | `air_vector_vr` | Air-referenced vertical rate | ft/min | 9 bits (1+8) | `-384` | `-384 ft/min` | `-384 fpm` |
| Arbitration | `display_heading_source` | Source of display heading | — | virtual | `track` | `track` | `track` |
| **SYSTEM** | | | | | | | |
| BDS 4,0 | `baro` | Barometric pressure setting | hPa | 12 bits | `1013.2 hPa` | `1013.2 hPa` | `1013.2 hPa` |
| BDS 6,2 / TC29 | `discretes` | Discrete mode flags | — | 6 bits | `AP/VNAV/TCAS` | `AP/VNAV/TCAS` | `---- (virtual)` |
| BDS 1,7 | `capability_summary` | GICB capability summary | — | 24 bits | `CAP:EHS/INT/MET` | `CAP:EHS/INT/MET` | `---- (virtual)` |
| Decoded | `last_bds_hit` | Last BDS register decoded | — | derived | `BDS50` | `BDS50` | `---- (virtual)` |
| BDS 1,7 | `supported_bds` | List of supported BDS codes | — | 24 bits | `["4,0","5,0","6,0"]` | `4,0, 5,0, 6,0` | `---- (virtual)` |
| BDS 5,F | `qsp_mcp_alt_change` | QSP: MCP altitude change counter | — | 2 bits | `1` | `1` | `1` |
| BDS 5,F | `qsp_next_wp_change` | QSP: next waypoint change counter | — | 2 bits | `2` | `2` | `2` |
| BDS 5,F | `qsp_fms_vmode_change` | QSP: FMS vertical mode change | — | 2 bits | `0` | `0` | `0` |
| BDS 5,F | `qsp_vhf_change` | QSP: VHF channel change counter | — | 2 bits | `1` | `1` | `1` |
| BDS 5,F | `qsp_meteo_change` | QSP: meteo/hazard change counter | — | 2 bits | `0` | `0` | `0` |
| BDS 5,F | `qsp_fms_alt_change` | QSP: FMS altitude change counter | — | 2 bits | `1` | `1` | `1` |
| BDS 5,F | `qsp_baro_change` | QSP: baro setting change counter | — | 2 bits | `0` | `0` | `0` |
| Sys Clock | `age` | Time since last message | s | virtual | `3` | `3s` | `3s` |
| Sys Clock | `first_seen` | Time aircraft first appeared | — | virtual | `14:22:07` | `14:22:07` | `14:22:07` |
| **SAFETY** | | | | | | | |
| BDS 3,0 | `tcas_ra` | TCAS resolution advisory status | — | 14 bits | `RA ALERT` | `RA ALERT` | `RA ALERT` |
| BDS 4,4/4,5 | `hazard` | Hazard summary string | — | derived | `TURB MOD` | `TURB MOD` | `TURB MOD` |
| BDS 4,5 | `wind_shear_level` | Wind shear severity (0-3) | — | 2 bits | `2` | `MOD` | `WS:MOD` |
| BDS 4,5 | `microburst_level` | Microburst severity (0-3) | — | 2 bits | `0` | `NIL` | `MB:NIL` |
| BDS 4,5 | `icing_level` | Icing severity (0-3) | — | 2 bits | `1` | `LIGHT` | `ICE:LIGHT` |
| BDS 4,5 | `wake_vortex_level` | Wake vortex severity (0-3) | — | 2 bits | `0` | `NIL` | `WV:NIL` |
| BDS 3,0 | `threat_icao` | TCAS threat aircraft ICAO | — | 24 bits | `4CA123` | `4CA123` | `4CA123` |
| BDS 3,0 | `threat_range_nm` | TCAS threat range | NM | 7 bits | `2.3` | `2.3 NM` | `2.3 NM` |
| BDS 3,0 | `threat_bearing_deg` | TCAS threat bearing | deg | 6 bits | `135` | `135°` | `135°` |
| BDS 4,4 | `turbulence_level` | Turbulence severity (0-3) | — | 2 bits | `1` | `1` | `1` |
| **INTENT** | | | | | | | |
| BDS 4,1 | `intent_next_wp` | Next FMS waypoint name | — | 54 bits (9×6) | `LOGAN` | `LOGAN` | `LOGAN` |
| BDS 4,2 | `intent_wp_lat` | Next waypoint latitude | deg | 19 bits (1+18) | `51.47050` | `51.47050°` | `51.47050°` |
| BDS 4,2 | `intent_wp_lon` | Next waypoint longitude | deg | 19 bits (1+18) | `-0.45428` | `-0.45428°` | `-0.45428°` |
| BDS 4,2 | `intent_wp_cross_alt` | Next waypoint crossing altitude | ft | 15 bits (1+14) | `6000` | `6000 ft` | `6000 ft` |
| BDS 4,3 | `intent_bearing` | Bearing to next waypoint | deg | 11 bits (1+10) | `247.85` | `247.85°` | `247.85°` |
| BDS 4,3 | `intent_time_to_go` | Time to next waypoint | min | 12 bits | `8.3` | `8.3 min` | `8.3 min` |
| BDS 4,3 | `intent_dist_to_go` | Distance to next waypoint | NM | 16 bits | `42.7` | `42.7 NM` | `42.7 NM` |
| **COMMS** | | | | | | | |
| BDS 4,8 | `vhf1_freq_mhz` | VHF radio 1 frequency | MHz | 15 bits | `124.850` | `124.850 MHz` | `124.850 MHz` |
| BDS 4,8 | `vhf2_freq_mhz` | VHF radio 2 frequency | MHz | 15 bits | `121.500` | `121.500 MHz` | `121.500 MHz` |
| BDS 4,8 | `vhf3_freq_mhz` | VHF radio 3 frequency | MHz | 15 bits | `131.725` | `131.725 MHz` | `131.725 MHz` |
| BDS 4,8 | `vhf1_audio` | VHF1 audio output mode | — | 2 bits | `HEADSET` | `HEADSET` | `HEADSET` |
| BDS 4,8 | `vhf2_audio` | VHF2 audio output mode | — | 2 bits | `SPEAKER` | `SPEAKER` | `SPEAKER` |
| BDS 4,8 | `vhf3_audio` | VHF3 audio output mode | — | 2 bits | `NOBODY` | `NOBODY` | `NOBODY` |
| BDS 4,8 | `vhf_guard_audio` | 121.5 MHz guard audio mode | — | 2 bits | `HEADSET` | `HEADSET` | `HEADSET` |
| **METEOROLOGY** | | | | | | | |
| BDS 4,4 Calc | `wind` | Wind summary (speed + dir) | — | derived | `285/32kt` | `285/32kt` | `285/32kt` |
| BDS 4,4/4,5 | `sat` | Static air temperature | °C | 11 bits (1+10) | `-42.5C` | `-42.5C` | `-42.5°C` |
| BDS 4,4 | `humidity` | Relative humidity | % | 6 bits | `62.5` | `62.5%` | `62.5%` |
| BDS 4,4 | `meteo_source` | Meteorology data source (FOM) | — | 4 bits | `GNSS` | `GNSS` | `GNSS` |
| BDS 4,4 | `wind_speed` | Wind speed (raw) | kt | 9 bits | `32` | `32` | `32 kt` |
| BDS 4,4 | `wind_direction` | Wind direction (raw) | deg | 9 bits | `285` | `285` | `285°` |
| BDS 4,4/4,5 | `static_pressure` | Static pressure | hPa | 11 bits | `238` | `238` | `238 hPa` |
| **POSITION** | | | | | | | |
| Local CPR Math | `lat` | Latitude | deg | 17 bits | `-33.9461` | `-33.9461` | `-33.9461` |
| Local CPR Math | `lon` | Longitude | deg | 17 bits | `151.1772` | `151.1772` | `151.1772` |
| DF17 TC:31 | `gnss_qual` | GNSS quality / accuracy metrics | — | variable | `NACp:9 SIL:3` | `NACp:9 SIL:3` | `NACp:9 SIL:3` |
| **INTEGRITY** | | | | | | | |
| BDS 6,2 / TC29 | `selected_heading` | Selected heading (autopilot) | deg | 9 bits | `248` | `248°` | `SEL:248°` |
| BDS 6,2 / BDS 4,0 | `selected_alt_source` | Selected altitude source | — | 1 bit | `MCP/FCU` | `MCP/FCU` | `MCP/FCU` |
| BDS 6,2 | `autopilot_mode` | Autopilot engaged | — | 1 bit | `ON` | `ON` | `ON` |
| BDS 4,0 / 6,2 | `vnav_mode` | VNAV mode active | — | 1 bit | `ON` | `ON` | `ON` |
| BDS 4,0 / 6,2 | `alt_hold_mode` | Altitude hold mode active | — | 1 bit | `OFF` | `OFF` | `OFF` |
| BDS 4,0 / 6,2 | `approach_mode` | Approach mode active | — | 1 bit | `OFF` | `OFF` | `OFF` |
| BDS 6,2 | `lnav_mode` | LNAV mode active | — | 1 bit | `ON` | `ON` | `ON` |
| BDS 6,2 | `tcas_operational` | TCAS operational status | — | 1 bit | `ON` | `ON` | `ON` |
| BDS 6,2 / TC29 | `nac_p` | Navigation accuracy category (position) | — | 4 bits | `9` | `NACp:9` | `NACp:9` |
| BDS 6,2 / TC29 | `sil` | Surveillance integrity level | — | 2 bits | `3` | `SIL:3` | `SIL:3` |
| BDS 6,2 / TC29 | `nic_baro` | NIC barometric flag | — | 1 bit | `1` | `BARO✓` | `BARO✓` |
| **SURVEILLANCE** | | | | | | | |
| Δt(Burst) Calc | `radar_sweep` | Estimated SSR sweep interval | s | derived | `4.1s (14.6 RPM)` | `4.1s (14.6 RPM)` | `4.1s (14.6 RPM)s` |
| Sys Counter | `msg_count` | Total messages received | — | counter | `847` | `847` | `847` |
| Sys Clock | `data_age_heading` | Age of last heading update | s | virtual | `1.2` | `1.2` | `1.2s` |
| Sys Clock | `data_age_position` | Age of last position update | s | virtual | `0.8` | `0.8` | `0.8s` |
| ADSBee Beast | `rssi_dbfs` | Received signal strength | dBFS | 8 bits | `-22.4` | `-22.4 dBFS` | `-22.4 dBFS` |
