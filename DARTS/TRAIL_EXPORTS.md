# 3D Trail Exports (Kepler.gl)

The map's **EXPORT 3D** button downloads `/api/trails/export3d.geojson` and
atomically saves the same file in `DARTS/3DSPAT_SAVES/`. The existing 2D export
is unchanged. Each 3D feature is one pair of consecutive valid observations;
gap/jump markers and unknown airborne altitude break the chain. Exact duplicates
and zero-length segments are omitted.

## Data and schema

Coordinates are `[longitude, latitude, z]`: `z` is barometric **pressure altitude**
converted from feet to metres (rounded to 0.1 m), **not** ellipsoidal height.
Ground is zero; valid negative altitude is preserved. Flat properties carry
start-sample historical telemetry, never current live-state backfills. Track
expires after 8 seconds; heading and other telemetry expire after 12 seconds.
Unobserved TCAS (including the initial UI default `CLEAN`), stale values, invalid
numbers, and fields absent in older rows export as `null`. Squawk remains text.
The v2 properties omit all three `vert_rate_*` fields; stored telemetry is
unchanged. `roll_deg` is rounded to whole integer degrees (or `null`).
Longitude, latitude, and feet altitudes retain full precision; pressure-altitude
conversion to metres is rounded to 0.1 m.

Exports read database rows in batches, spool the snapshot to temporary disk
storage, and serialize features incrementally to an atomic `.part` file.
HTTP downloads stream that completed file. Server console logs show the window,
auto flag, queried row count, progress every 10,000 features (aircraft, bytes,
elapsed time), and completion or failure. The manual download logs bytes received
in the browser console and uses `Content-Disposition` for the filename without
re-parsing the GeoJSON. The browser still holds the final download blob.
Nightly failures are logged with a traceback and the exception type/detail in
`export_log.error`.

Metadata identifies schema `darts-3dspat-v2`, units, UTC generation/window times,
filename, and serial. In Kepler.gl, enable 3D/elevation, colour by `altitude_ft`,
size the stroke by `groundspeed_kt`, filter on `tcas_active`, and use epoch-seconds
`start_ts` for the time filter. For field confidence guidance, see
[Data Validity](DATA_VALIDITY.md).

## Filenames and audit

Filenames follow `3DSPAT_DDMMMYY_HHMM_MMMM_XXXX.geojson`, for example
`3DSPAT_08OCT26_1329_0397_00F4.geojson`. Date/time are the **first sample in
Australia/Sydney**, English uppercase month (including MAY); duration is real
elapsed whole minutes, padded to four digits and capped at 9999. Empty manual
exports use the requested start and duration `0000`.

Automatic files have an `AUTO_` prefix and go in `DARTS/AUTO_3DSPAT_SAVES/`.
Both directories are created automatically and ignored by Git. The trail database
(`DARTS/data/trails.db` by default) contains `export_log` and a persistent serial
counter shared by manual/automatic exports. Serials start at `0000`, increment
transactionally, and wrap after `FFFF` with a warning. Every attempt is logged
(`ok`, `empty`, or `error`); empty automatic windows write no file and consume no
serial. Failed attempts may consume a serial. Skipped automatic attempts use audit
serial `-1` and an empty `serial_hex`; they do not advance the counter.

## Automatic daily exports

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
