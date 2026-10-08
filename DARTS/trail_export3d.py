"""Pairwise 3D trail exports, persistent export audit, and Sydney scheduling.

The scheduler is a blocking loop intended as a daemon-thread target. Startup
never exports a historical window. After a delayed wake it exports only the
most recent completed daily window, not every missed window.
"""

import json
import logging
import math
import os
import sqlite3
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python 3.8 installations may provide the compatibility module.
    from backports.zoneinfo import ZoneInfo


LOGGER = logging.getLogger(__name__)
SYDNEY = ZoneInfo("Australia/Sydney")
UTC = timezone.utc
TRAIL_TELEMETRY_COLUMNS = (
    "groundspeed_kt", "track_deg_true", "heading_deg_mag", "vert_rate_fpm",
    "vert_rate_baro_fpm", "vert_rate_inertial_fpm", "roll_deg", "tas_kt",
    "ias_kt", "mach", "tcas_ra", "squawk", "rssi_dbfs", "position_age_s",
)
_BASE_COLUMNS = (
    "id", "icao", "ts_ms", "lat", "lon", "altitude", "on_ground", "callsign",
    "source_label", "receiver_id", "marker_type",
)
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
_UNITS = {
    "z": "m (pressure altitude converted)",
    "altitude_ft": "ft", "altitude_start_ft": "ft", "altitude_end_ft": "ft",
    "start_ts": "unix_s", "duration_s": "s",
    "groundspeed_kt": "kt", "track_deg_true": "deg_true",
    "heading_deg_mag": "deg_mag", "vert_rate_fpm": "ft/min",
    "vert_rate_baro_fpm": "ft/min", "vert_rate_inertial_fpm": "ft/min",
    "roll_deg": "deg", "tas_kt": "kt", "ias_kt": "kt", "mach": "Mach",
    "tcas_ra": "text", "squawk": "code", "rssi_dbfs": "dBFS",
    "position_age_s": "s",
}


def _iso_ms(value):
    return datetime.fromtimestamp(int(value) / 1000, UTC).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def _finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _text(value):
    if value is None:
        return None
    text = str(value).strip()
    return None if text in ("", "----", "?") else text


def _altitude(row):
    if row[6] == 1 or str(row[5]).strip().upper() == "GROUND":
        return 0.0
    return _finite(row[5])


def _is_observation(row):
    lat, lon = _finite(row[3]), _finite(row[4])
    return (not row[10] and lat is not None and lon is not None
            and -90 <= lat <= 90 and -180 <= lon <= 180)


def build_geojson3d(rows):
    """Build one two-coordinate feature per adjacent valid sample pair.

    Markers reset adjacency even when they share a timestamp with a sample.
    Missing airborne altitude (or invalid coordinates) breaks rather than
    inventing a sea-level point. Properties belong to the start sample.
    """
    rows = sorted(rows, key=lambda r: (
        str(r[1]), int(r[2]), 0 if r[10] else 1, r[0] or 0))
    features = []
    previous = None
    aircraft = None
    seen = set()
    segment_index = 0
    trail_id = None
    first_ms = None
    last_ms = None
    for row in rows:
        sample = dict(zip(_BASE_COLUMNS + TRAIL_TELEMETRY_COLUMNS, row))
        for column in TRAIL_TELEMETRY_COLUMNS:
            sample.setdefault(column, None)
            if column not in ("tcas_ra", "squawk"):
                sample[column] = _finite(sample[column])
        sample["squawk"] = _text(sample["squawk"])
        sample["tcas_ra"] = _text(sample["tcas_ra"])
        if sample["tcas_ra"] is not None and sample["tcas_ra"].upper() == "UNKNOWN":
            sample["tcas_ra"] = None
        if sample["icao"] != aircraft:
            aircraft = sample["icao"]
            previous = None
            segment_index = 0
        if sample["marker_type"]:
            previous = None
            continue
        if _is_observation(row):
            timestamp = int(sample["ts_ms"])
            first_ms = timestamp if first_ms is None else min(first_ms, timestamp)
            last_ms = timestamp if last_ms is None else max(last_ms, timestamp)
        lat, lon = _finite(sample["lat"]), _finite(sample["lon"])
        altitude = _altitude(row)
        if (lat is None or lon is None or not -90 <= lat <= 90
                or not -180 <= lon <= 180 or altitude is None):
            previous = None
            continue
        key = (aircraft, int(sample["ts_ms"]), lat, lon, sample["altitude"])
        if key in seen:
            continue
        seen.add(key)
        sample["ts_ms"] = int(sample["ts_ms"])
        sample["lat"], sample["lon"] = lat, lon
        sample["altitude_ft"] = altitude
        sample["altitude_m"] = round(altitude * 0.3048, 1)
        tcas = sample["tcas_ra"]
        sample["tcas_active"] = None if tcas is None else tcas.upper() != "CLEAN"
        if previous is None:
            trail_id = f"{aircraft}:{sample['ts_ms']}"
            segment_index = 0
        else:
            if (previous["lon"], previous["lat"], previous["altitude_ft"]) == (
                    lon, lat, altitude):
                previous = sample
                continue
            properties = {column: previous[column] for column in TRAIL_TELEMETRY_COLUMNS}
            start_ms, end_ms = previous["ts_ms"], sample["ts_ms"]
            properties.update({
                "icao": aircraft, "callsign": _text(previous["callsign"]),
                "trail_id": trail_id, "segment_index": segment_index,
                "start_ts": start_ms // 1000,
                "start_time": _iso_ms(start_ms), "end_time": _iso_ms(end_ms),
                "duration_s": (end_ms - start_ms) / 1000,
                "altitude_ft": (previous["altitude_ft"] + altitude) / 2,
                "altitude_start_ft": previous["altitude_ft"], "altitude_end_ft": altitude,
                "tcas_active": previous["tcas_active"],
                "emergency": previous["squawk"] in ("7500", "7600", "7700"),
                "on_ground": (None if previous["on_ground"] is None
                              else bool(previous["on_ground"])),
                "source_label": _text(previous["source_label"]),
                "receiver_id": _text(previous["receiver_id"]),
            })
            features.append({
                "type": "Feature", "id": f"{aircraft}:{start_ms}:{segment_index}",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [previous["lon"], previous["lat"], previous["altitude_m"]],
                        [lon, lat, sample["altitude_m"]],
                    ],
                },
                "properties": properties,
            })
            segment_index += 1
        previous = sample
    return {
        "type": "FeatureCollection", "features": features,
        "metadata": {
            "schema": "darts-3dspat-v1",
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "units": dict(_UNITS), "timezone": "Australia/Sydney",
            "serial": None, "auto": False, "filename": None,
            "feature_count": len(features),
            "data_first_ms": first_ms, "data_last_ms": last_ms,
            "window_from": None if first_ms is None else _iso_ms(first_ms),
            "window_to": None if last_ms is None else _iso_ms(last_ms),
        },
    }


def format_export_filename(first_ms, last_ms, serial, is_auto=False):
    """Format a locale-independent Sydney filename with a four-digit duration."""
    start = datetime.fromtimestamp(int(first_ms) / 1000, UTC).astimezone(SYDNEY)
    minutes = min(9999, max(0, (int(last_ms) - int(first_ms)) // 60000))
    stamp = f"{start.day:02d}{_MONTHS[start.month - 1]}{start.year % 100:02d}_{start:%H%M}"
    return f"{'AUTO_' if is_auto else ''}3DSPAT_{stamp}_{minutes:04d}_{int(serial) & 0xFFFF:04X}.geojson"


class Export3DStore:
    """Independent SQLite connection and cross-process serial reservations.

    Failed manual attempts consume their reserved serial; empty automatic
    attempts do not and use audit sentinel serial -1 / serial_hex "". Initial
    reservations have error status until completion, so an interrupted process
    never leaves an attempt falsely marked successful. The counter is not
    derived from retained audit rows.
    """

    def __init__(self, db_path, base_dir):
        self.base_dir = Path(base_dir)
        for name in ("3DSPAT_SAVES", "AUTO_3DSPAT_SAVES"):
            os.makedirs(str(self.base_dir / name), exist_ok=True)
        self._lock = threading.RLock()
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
        with self._lock:
            self._connection.executescript("""
                CREATE TABLE IF NOT EXISTS export_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    serial INTEGER NOT NULL,
                    serial_hex TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    path TEXT NOT NULL,
                    is_auto INTEGER NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    window_from_ms INTEGER,
                    window_to_ms INTEGER,
                    data_first_ms INTEGER,
                    data_last_ms INTEGER,
                    feature_count INTEGER,
                    aircraft_count INTEGER,
                    status TEXT NOT NULL CHECK(status IN ('ok', 'empty', 'error')),
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS export_serial (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    next_serial INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO export_serial VALUES (1, 0);
            """)

    def close(self):
        with self._lock:
            self._connection.close()

    def _allocate_serial(self):
        serial = self._connection.execute(
            "SELECT next_serial FROM export_serial WHERE id = 1").fetchone()[0]
        if serial == 0xFFFF:
            LOGGER.warning("3D export serial wraps from FFFF to 0000")
        self._connection.execute(
            "UPDATE export_serial SET next_serial = ? WHERE id = 1", ((serial + 1) & 0xFFFF,))
        return serial

    def _reserve(self, from_ms, to_ms, icao, is_auto):
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                serial = None if is_auto else self._allocate_serial()
                cursor = self._connection.execute(
                    "INSERT INTO export_log "
                    "(created_at_utc, window_from_ms, window_to_ms, is_auto, serial, "
                    "serial_hex, filename, path, feature_count, aircraft_count, status, error) "
                    "VALUES (?, ?, ?, ?, ?, ?, '', '', 0, 0, 'error', 'Export did not complete')",
                    (datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                     from_ms, to_ms, int(is_auto), -1 if serial is None else serial,
                     "" if serial is None else f"{serial:04X}"))
                self._connection.commit()
                return cursor.lastrowid, serial
            except Exception:
                LOGGER.exception("Could not reserve 3D trail export")
                self._connection.rollback()
                raise

    def _reserve_auto_serial(self, log_id):
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                serial = self._allocate_serial()
                self._connection.execute(
                    "UPDATE export_log SET serial = ?, serial_hex = ? WHERE id = ?",
                    (serial, f"{serial:04X}", log_id))
                self._connection.commit()
                return serial
            except Exception:
                self._connection.rollback()
                raise

    def _finish(self, log_id, status, filename=None, count=None, error=None,
                path="", first_ms=None, last_ms=None, aircraft_count=0):
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE export_log SET status = ?, filename = ?, path = ?, "
                "feature_count = ?, aircraft_count = ?, data_first_ms = ?, data_last_ms = ?, "
                "error = ? WHERE id = ?",
                (status, filename or "", path, count or 0, aircraft_count,
                 first_ms, last_ms, error, log_id))

    def export(self, from_ms, to_ms, query_rows, build_payload, is_auto=False, icao=None):
        from_ms, to_ms = int(from_ms), int(to_ms)
        log_id, serial = self._reserve(from_ms, to_ms, icao, is_auto)
        filename = None
        temporary = None
        count = None
        destination = None
        first_ms = last_ms = None
        aircraft_count = 0
        try:
            if to_ms < from_ms:
                raise ValueError("export window ends before it starts")
            rows = list(query_rows(from_ms, to_ms, icao=icao, apply_backstop=False))
            observations = [r for r in rows if _is_observation(r)]
            if observations:
                times = [int(r[2]) for r in observations]
                first_ms, last_ms = min(times), max(times)
                aircraft_count = len({r[1] for r in observations})
            payload = build_payload(rows, apply_backstop=True)
            count = len(payload["features"])
            metadata = payload.setdefault("metadata", {})
            metadata.update({
                "serial": None if serial is None else f"{serial:04X}", "auto": bool(is_auto),
                "filename": None, "feature_count": count,
                "aircraft_count": aircraft_count,
                "window_from": _iso_ms(from_ms), "window_to": _iso_ms(to_ms),
                "data_first_ms": first_ms, "data_last_ms": last_ms,
            })
            if is_auto and not observations:
                self._finish(log_id, "empty", count=0)
                return payload, None
            if serial is None:
                serial = self._reserve_auto_serial(log_id)
            filename = format_export_filename(
                from_ms if first_ms is None else first_ms,
                from_ms if last_ms is None else last_ms, serial, is_auto)
            metadata.update({"serial": f"{serial:04X}", "filename": filename})
            folder = self.base_dir / ("AUTO_3DSPAT_SAVES" if is_auto else "3DSPAT_SAVES")
            os.makedirs(str(folder), exist_ok=True)
            destination = folder / filename
            temporary = folder / f".{filename}.{uuid.uuid4().hex}.part"
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(payload, stream, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(str(temporary), str(destination))
            temporary = None
            self._finish(log_id, "ok" if observations else "empty", filename, count,
                         path=str(destination), first_ms=first_ms, last_ms=last_ms,
                         aircraft_count=aircraft_count)
            return payload, filename
        except Exception as exc:
            LOGGER.exception("3D trail export failed")
            self._finish(log_id, "error", filename, count, f"{type(exc).__name__}: {exc}",
                         path="" if destination is None else str(destination),
                         first_ms=first_ms, last_ms=last_ms, aircraft_count=aircraft_count)
            raise
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass


def parse_daily_time(value):
    """Parse HHMM strings/integers; 2400 and invalid input become (0, 0)."""
    text = str(value).strip()
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 2400:
        text = f"{value:04d}"
    if len(text) == 4 and text.isascii() and text.isdigit():
        hour, minute = int(text[:2]), int(text[2:])
        if (0 <= hour <= 23 and 0 <= minute <= 59) or text == "2400":
            return (0, 0) if hour == 24 else (hour, minute)
    LOGGER.warning("Invalid daily export time %r; using 2400", value)
    return 0, 0


def scheduled_instant(local_date, daily_time="2400"):
    """UTC instant for a Sydney wall date/time; gaps advance, folds use fold=0."""
    hour, minute = parse_daily_time(daily_time)
    if isinstance(local_date, datetime):
        local_date = local_date.date()
    if not isinstance(local_date, date):
        raise TypeError("local_date must be a date")
    wall = datetime.combine(local_date, datetime.min.time()).replace(hour=hour, minute=minute)
    # Round-trip validation detects imaginary wall times without relying on
    # platform-specific zone transition internals.
    for offset in range(24 * 60 + 1):
        candidate = wall + timedelta(minutes=offset)
        instant = candidate.replace(tzinfo=SYDNEY, fold=0).astimezone(UTC)
        if instant.astimezone(SYDNEY).replace(tzinfo=None) == candidate:
            return instant
    raise ValueError("no valid Sydney scheduling instant")


def _aware_utc(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("schedule requires an aware datetime")
    return value.astimezone(UTC)


def next_scheduled_run(now, daily_time="2400"):
    now = _aware_utc(now)
    hour, minute = parse_daily_time(daily_time)
    daily_time = f"{hour:02d}{minute:02d}"
    local_date = now.astimezone(SYDNEY).date() - timedelta(days=1)
    while True:
        instant = scheduled_instant(local_date, daily_time)
        if instant > now:
            return instant
        local_date += timedelta(days=1)


def previous_scheduled_run(current, daily_time="2400"):
    current = _aware_utc(current)
    hour, minute = parse_daily_time(daily_time)
    daily_time = f"{hour:02d}{minute:02d}"
    local_date = current.astimezone(SYDNEY).date()
    return scheduled_instant(local_date - timedelta(days=1), daily_time)


def run_daily_exports(export_callback, daily_time="2400", stop_event=None, clock=None):
    """Run in a daemon thread; wait at most 30s and export only the latest window.

    A completed/failed attempt is never retried by clock rollback. Delayed wakes
    skip older missed windows. Callback errors are logged and do not kill the
    scheduler. An injected clock returns aware datetimes.
    """
    stop_event = stop_event if stop_event is not None else threading.Event()
    clock = clock if clock is not None else lambda: datetime.now(UTC)
    hour, minute = parse_daily_time(daily_time)
    daily_time = f"{hour:02d}{minute:02d}"
    upcoming = next_scheduled_run(clock(), daily_time)
    last_completed = None
    while not stop_event.is_set():
        now = _aware_utc(clock())
        if now >= upcoming:
            latest = previous_scheduled_run(next_scheduled_run(now, daily_time), daily_time)
            if last_completed is None or latest > last_completed:
                start = previous_scheduled_run(latest, daily_time)
                try:
                    export_callback(int(start.timestamp() * 1000), int(latest.timestamp() * 1000))
                except Exception:
                    LOGGER.exception("Daily 3D trail export failed")
                last_completed = latest
            upcoming = next_scheduled_run(now, daily_time)
            if last_completed is not None and upcoming <= last_completed:
                upcoming = next_scheduled_run(last_completed, daily_time)
        stop_event.wait(min(30.0, max(0.0, (upcoming - now).total_seconds())))
