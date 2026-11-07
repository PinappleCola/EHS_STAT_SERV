# VDL2 sample data inventory

This note records decoded message types and fields identified in the sample
DumpVDL2 NDJSON shared during VDL2 integration work. It is intended as a
handoff for future maintainers and AI agents.

## Evidence and limits

- The original large chat attachments are not retained with the repository.
  Findings below reflect sample records and counts extracted while they were
  available, not a fresh scan of a complete capture.
- One inspected sample contained 109 decoded records. The ACARS label counts
  below describe that sample only; they are not rates, unique-aircraft counts,
  or a guarantee of all formats emitted on VDL2.
- Some labels were seen without enough payload detail to identify their
  application semantics. Do not infer a decoder or plotting rule from a label
  alone.
- DumpVDL2 output is decoded data, not raw radio-frame bytes. DARTS currently
  does not perform general ACARS reassembly or decode every payload format.

## ACARS label counts in the 109-record sample

| Label / sublabel | Records | Observations |
|---|---:|---|
| `H1/DF` | 77 | Mixed airline payloads; includes RSI and other dense reports |
| `B6` | 9 | Structured ADS-C / ARINC 622 messages |
| `H1/10` | 8 | Includes multi-point BSM-like position reports |
| `H1/M1` | 6 | Includes `POSS` position reports |
| No ACARS label | 3 | Label absent in decoded records |
| `16` | 2 | Present; semantics not established |
| `49` | 1 | Present; semantics not established |
| `H1/T1` | 1 | Present; semantics not established |
| `MA` | 1 | Sample contains nested MIAM single-transfer data |
| `SA` | 1 | Present; semantics not established |

## Position-bearing and location-bearing formats

### ADS-C / ARINC 622 (`B6`)

DumpVDL2 exposes decoded fields under the ACARS `arinc622.adsc.tags` array.
The samples included:

- `basic_report`: current latitude, longitude, altitude, position accuracy,
  seconds-past-hour timestamp, navigation-redundancy flag, and TCAS flag.
- `earth_ref_data`: ground speed, true track with a validity flag, and vertical
  speed.
- `meteo_data`: temperature and true wind direction/speed with validity flags.
- `predicted_route`: `next_wpt` and `next_next_wpt`, with coordinates and
  altitudes; `next_wpt` may include ETA.
- `wpt_change_event`: reported current position and event time. It can coexist
  with `predicted_route`; NEXT/NEXT+1 are predictions, not observed fixes.
- `alt_range_event` and `lat_dev_change_event`: observed ADS-C event positions.
  Their presence alone does not establish a trigger threshold or deviation size.

The sample's Basic Report and `earth_ref_data.true_trk_deg` belong to separate
tags in the same decoded message. Plot true track only when
`true_trk_valid` is true. Do not label true track as aircraft heading.

### H1/DF RSI

An RSI text report has a date/time row followed by a column header similar to:

```text
LAT      LON      GALT  TTRK GS
-34.1103  150.9005  19801  -73 323
```

`LAT`/`LON` are decimal degrees; `GALT` is feet; `TTRK` is true track and can
be signed (normalize to 0–359 degrees, e.g. `-73` -> `287`); `GS` is knots.
The footer contains `POS-ERR`; the observed sample had zero. The current parser
requires a complete CRC-valid H1/DF message, valid coordinates/date/time,
and zero POS-ERR before plotting.

### ADS-C event report: waypoint change

The inspected `wpt_change_event` sample contained:

- Current event position (`lat`, `lon`, `alt`, `ts_sec`,
  `pos_accuracy_nm`, navigation/TCAS status).
- `predicted_route.next_wpt` with coordinates, altitude, and ETA.
- `predicted_route.next_next_wpt` with coordinates and altitude.

The event timestamp is seconds past the UTC hour and is resolved against
capture time. The event fix is distinct from predicted route points.

### XID aircraft location

XID appears in AVLC U-frames (`cmd: "XID"`). A decoded handoff-initiation
sample included VDL parameters such as destination airport and
`ac_location.value.loc.lat` / `.lon`, with altitude in
`ac_location.value.alt`. The formatted console showed a rounded location like
`33.9S 150.8E 7000 ft`. Other XID examples included link-establishment and
connection-management parameters.

The location has no verified independent report timestamp or sensor accuracy
in the inspected examples. DARTS timestamps it with the VDL2 frame capture
time. A one-decimal-degree display corresponds to a rounding cell of
approximately 0.1 degrees per axis; an optional conservative circle can show
the cell's half-diagonal (roughly 4 nautical miles near Sydney). The live map
plots validated `ac_location` fixes as a point with a dotted circle; the
console colors its coordinates, altitude, and radius using the configured
position-data color. This circle is a **coordinate-precision estimate**, not a
reported or measured accuracy. The marker uses frame capture time and retains
decoded altitude for map measurement.

### ACARS label `11` POS

An observed payload used readable fields such as `CAS`, `LAT`, `LON`, `ALT`,
`FOB`, `UTC`, and wind/temperature values. This format was identified from
text, but no general parser has been validated against enough examples.

### ACARS label `80` POSWX / POSRPT

`POSWX` examples carried `/POS` entries with `/OVR` times, altitude, fuel,
mach, airspeed, and ground speed. Multiple `/POS` entries can occur in one
message and appear to represent successive reported locations, not necessarily
one current fix. A `POSRPT` sample used a compact position string and included
altitude, mach, fuel, time, wind, temperature, and ETA. These formats need
separate validated parsers before plotting.

### ACARS label `H1/10` BSM-like reports

One message contained a `BSM...` header followed by repeated records with
hemisphere-prefixed latitude/longitude, time-like fields, and numeric flight
data. Treat as a potential multi-point history format; exact field semantics
and continuation/reassembly behavior were not established.

### Other H1/DF payloads

Several dense H1/DF text messages contained embedded coordinates or numeric
blocks, but their message family and coordinate semantics were not identified.
Do not scrape coordinate-shaped substrings without a validated message
signature and field interpretation.

## XID examples and frequency

The 109-record count above is an ACARS-label inventory, not an XID count.
Earlier inspection of a separate sample of roughly 105 records found two
`ac_location` parameters. XID messages are AVLC U-frames and are not included
in ACARS label counts.

## Other observed structure

- AVLC I-frames carried most inspected ACARS messages.
- AVLC U-frames included XID link-management/handoff messages.
- A `MA` ACARS sample included a nested MIAM single-transfer payload with
  another decoded ACARS message.
- Source ICAO identifies the sending aircraft in the inspected aircraft
  records; receiver/ground-station addresses appear as the other AVLC endpoint.

## Current DARTS behavior

The live-map VDL2 layer plots validated H1/M1 POSS, ADS-C Basic Reports, H1/DF
RSI, ADS-C waypoint-change, altitude-range and lateral-deviation events, and XID
aircraft locations. Basic and waypoint-change reports can show predicted
NEXT/NEXT+1 points, linked by a dotted route separately from observed fixes.
Valid decoded altitude and reported position accuracy are included when available.
ADS-C seconds-past-hour timestamps are resolved against capture time; a Basic
report missing that field uses capture time. Other VDL2 frames
can be correlated with an active ADS-B ICAO at the ADS-B position observed on
receipt; those dots are not positions reported in the VDL2 payload.

Keep the XID source label distinct from ADS-C and RSI, and describe its circle
as rounding-derived precision rather than sensor accuracy. See the VDL2 live
console section in the root README for current controls and lifecycle behavior.

## Airport references

`DARTS/airports.JSON` is a user-supplied object keyed by four-letter ICAO codes.
The VDL2 feed caches its keys and matches complete, case-insensitive tokens in
decoded ACARS/XID payload string values once per incoming record. JSON keys
and transport addresses are not searched. Embedded or concatenated codes are
intentionally excluded to avoid interpreting opaque payload substrings.

`frame_airports` stays aligned with the frame buffer; `new_frames` and plotted
positions carry `airport_codes`. Console/popup text uses the existing extracted
data color, and observed fixes and correlated dots get airport tags. Matches
are references only: do not infer departure/destination from ordering. Lookup
errors are reported separately from feed errors and do not stop decoding.
Lookup changes affect new messages only. ADS-B state and emission are untouched;
shared CPU/browser rendering overhead remains a deployment consideration.

New VDL2 batches notify through the existing browser sound player using sound
`08`. Initial buffers and repeated polling are silent. Console type-out is a
display-only, bounded scheduled animation that retains existing colored spans;
it does not delay message ingestion, positional extraction, or map updates.
