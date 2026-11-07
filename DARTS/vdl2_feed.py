import json
import datetime
import math
import os
import re
import threading
import time
import uuid


AIRPORT_CODE_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{4})(?![A-Z0-9])")


def find_airport_codes(record, airport_codes):
    """Match complete ICAO tokens in decoded payload values, not JSON keys."""
    avlc = record.get("vdl2", {}).get("avlc", {})
    if not airport_codes or not isinstance(avlc, dict):
        return []
    pending = [avlc.get("acars"), avlc.get("xid")]
    matches = set()
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, str):
            matches.update(code for code in AIRPORT_CODE_RE.findall(value.upper())
                           if code in airport_codes)
    return sorted(matches)


def parse_poss_report(record):
    frame = record.get("vdl2", {})
    if not isinstance(frame, dict):
        return None
    avlc = frame.get("avlc", {})
    if not isinstance(avlc, dict):
        return None
    source = avlc.get("src", {})
    acars = avlc.get("acars", {})
    if not isinstance(source, dict) or not isinstance(acars, dict):
        return None
    if source.get("type") != "Aircraft" or acars.get("label") != "H1" or acars.get("sublabel") != "M1":
        return None
    if acars.get("err") is not False or acars.get("crc_ok") is not True or acars.get("more") is not False:
        return None
    icao = source.get("addr", "")
    if not isinstance(icao, str) or not re.fullmatch(r"[0-9a-fA-F]{6}", icao):
        return None
    text = acars.get("msg_text", "")
    match = re.match(r"^POS([NS])(\d{2})(\d{3})([EW])(\d{3})(\d{3}),[^,\r\n]*,(\d{6}),", text) if isinstance(text, str) else None
    if not match:
        return None
    ns, lat_deg, lat_min, ew, lon_deg, lon_min, clock = match.groups()
    lat_minutes, lon_minutes = int(lat_min) / 10, int(lon_min) / 10
    lat, lon = int(lat_deg) + lat_minutes / 60, int(lon_deg) + lon_minutes / 60
    if lat_minutes >= 60 or lon_minutes >= 60 or lat > 90 or lon > 180:
        return None
    timestamp = frame.get("t", {})
    capture = timestamp.get("sec") if isinstance(timestamp, dict) else None
    if isinstance(capture, bool) or not isinstance(capture, (int, float)) or not math.isfinite(capture):
        return None
    try:
        captured_at = datetime.datetime.fromtimestamp(capture, datetime.timezone.utc)
        reported_at = captured_at.replace(hour=int(clock[:2]), minute=int(clock[2:4]), second=int(clock[4:]), microsecond=0)
        candidates = [reported_at + datetime.timedelta(days=offset) for offset in (-1, 0, 1)]
        reported_at = min(candidates, key=lambda value: abs((value - captured_at).total_seconds()))
    except (ValueError, OverflowError, OSError):
        return None
    if reported_at.timestamp() > capture + 60:
        return None
    coordinate_text = match[0].split(",", 1)[0]
    return {
        "icao": icao.upper(),
        "lat": -lat if ns == "S" else lat,
        "lon": -lon if ew == "W" else lon,
        "report_time": reported_at.timestamp(),
        "message_type": f'{acars["label"]}/{acars["sublabel"]} POS',
        "coordinate_text": coordinate_text,
        "record": record,
    }


def parse_adsc_basic_report(record):
    return _parse_adsc_report(record, "basic_report", "ADS-C BASIC")


def parse_adsc_waypoint_report(record):
    return _parse_adsc_report(record, "wpt_change_event", "ADS-C WPT CHANGE")


def parse_adsc_altitude_event(record):
    return _parse_adsc_report(record, "alt_range_event", "ADS-C ALT RANGE")


def parse_adsc_lateral_event(record):
    return _parse_adsc_report(record, "lat_dev_change_event", "ADS-C LAT DEV")


def parse_xid_aircraft_location(record):
    frame = record.get("vdl2", {})
    if not isinstance(frame, dict):
        return None
    avlc = frame.get("avlc", {})
    if not isinstance(avlc, dict) or avlc.get("frame_type") != "U" or avlc.get("cmd") != "XID":
        return None
    source = avlc.get("src")
    xid = avlc.get("xid")
    if not isinstance(source, dict) or source.get("type") != "Aircraft" or not isinstance(xid, dict):
        return None
    icao = source.get("addr")
    if not isinstance(icao, str) or not re.fullmatch(r"[0-9a-fA-F]{6}", icao):
        return None
    timestamp = frame.get("t", {})
    capture = timestamp.get("sec") if isinstance(timestamp, dict) else None
    if isinstance(capture, bool) or not isinstance(capture, (int, float)) or not math.isfinite(capture):
        return None
    params = xid.get("vdl_params")
    if not isinstance(params, list):
        return None
    for param in params:
        if not isinstance(param, dict) or param.get("name") != "ac_location":
            continue
        value = param.get("value")
        location = value.get("loc") if isinstance(value, dict) else None
        if not isinstance(location, dict):
            continue
        lat, lon = location.get("lat"), location.get("lon")
        if (isinstance(lat, bool) or not isinstance(lat, (int, float))
                or not math.isfinite(lat) or not -90 <= lat <= 90):
            return None
        if (isinstance(lon, bool) or not isinstance(lon, (int, float))
                or not math.isfinite(lon) or not -180 <= lon <= 180):
            return None
        # A one-decimal-degree coordinate represents a rounded cell; this
        # radius conservatively reaches the cell's corners at this latitude.
        lat_half_cell_nm = 0.05 * 60
        lon_half_cell_nm = 0.05 * 60 * math.cos(math.radians(lat))
        radius_nm = math.hypot(lat_half_cell_nm, lon_half_cell_nm)
        altitude = value.get("alt")
        if isinstance(altitude, bool) or not isinstance(altitude, (int, float)) or not math.isfinite(altitude):
            altitude = None
        return {
            "icao": icao.upper(), "lat": lat, "lon": lon,
            "true_track_deg": None, "alt": altitude,
            "position_uncertainty_nm": radius_nm,
            "report_time": float(capture), "message_type": "XID LOCATION",
            "coordinate_text": None, "record": record,
        }
    return None


def _parse_adsc_report(record, report_key, message_type):
    frame = record.get("vdl2", {})
    if not isinstance(frame, dict):
        return None
    avlc = frame.get("avlc", {})
    if not isinstance(avlc, dict):
        return None
    source = avlc.get("src", {})
    acars = avlc.get("acars", {})
    if not isinstance(source, dict) or source.get("type") != "Aircraft":
        return None
    if not isinstance(acars, dict):
        return None
    if acars.get("err") is not False or acars.get("crc_ok") is not True or acars.get("more") is not False:
        return None
    arinc622 = acars.get("arinc622", {})
    adsc = arinc622.get("adsc", {}) if isinstance(arinc622, dict) else {}
    if not isinstance(adsc, dict) or adsc.get("err") is not False:
        return None
    if arinc622.get("crc_ok") is not True:
        return None
    icao = source.get("addr", "")
    if not isinstance(icao, str) or not re.fullmatch(r"[0-9a-fA-F]{6}", icao):
        return None
    timestamp = frame.get("t", {})
    capture = timestamp.get("sec") if isinstance(timestamp, dict) else None
    if isinstance(capture, bool) or not isinstance(capture, (int, float)) or not math.isfinite(capture):
        return None

    basic_report = None
    earth_ref_data = None
    tags = adsc.get("tags", [])
    if not isinstance(tags, list):
        return None
    for tag in tags:
        if not isinstance(tag, dict):
            continue
        if basic_report is None and isinstance(tag.get(report_key), dict):
            basic_report = tag[report_key]
        if earth_ref_data is None and isinstance(tag.get("earth_ref_data"), dict):
            earth_ref_data = tag["earth_ref_data"]
    if basic_report is None:
        return None

    lat = basic_report.get("lat")
    lon = basic_report.get("lon")
    if (isinstance(lat, bool) or not isinstance(lat, (int, float)) or not math.isfinite(lat)
            or not -90 <= lat <= 90):
        return None
    if (isinstance(lon, bool) or not isinstance(lon, (int, float)) or not math.isfinite(lon)
            or not -180 <= lon <= 180):
        return None

    true_track = None
    if isinstance(earth_ref_data, dict) and earth_ref_data.get("true_trk_valid") is True:
        value = earth_ref_data.get("true_trk_deg")
        if (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and 0 <= value < 360):
            true_track = value
    report_time = float(capture)
    seconds = basic_report.get("ts_sec")
    if seconds is not None or report_key != "basic_report":
        if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                or not math.isfinite(seconds) or not 0 <= seconds < 3600):
            return None
        # ADS-C timestamps are seconds past the hour, dated against reception.
        report_time = math.floor(capture / 3600) * 3600 + seconds
        if report_time > capture + 60:
            report_time -= 3600
    route = []
    if report_key in ("basic_report", "wpt_change_event"):
        for tag in tags:
            predicted = tag.get("predicted_route") if isinstance(tag, dict) else None
            if not isinstance(predicted, dict):
                continue
            for key, label in (("next_wpt", "NEXT"), ("next_next_wpt", "NEXT+1")):
                waypoint = predicted.get(key)
                if not isinstance(waypoint, dict):
                    continue
                lat_wpt, lon_wpt = waypoint.get("lat"), waypoint.get("lon")
                if (isinstance(lat_wpt, bool) or not isinstance(lat_wpt, (int, float))
                        or not -90 <= lat_wpt <= 90
                        or isinstance(lon_wpt, bool) or not isinstance(lon_wpt, (int, float))
                        or not -180 <= lon_wpt <= 180):
                    continue
                point = {"lat": lat_wpt, "lon": lon_wpt, "label": label}
                altitude = waypoint.get("alt")
                if (isinstance(altitude, (int, float)) and not isinstance(altitude, bool)
                        and math.isfinite(altitude)):
                    point["alt"] = altitude
                eta = waypoint.get("eta_sec")
                if (isinstance(eta, (int, float)) and not isinstance(eta, bool)
                        and math.isfinite(eta) and eta >= 0):
                    point["eta_sec"] = eta
                route.append(point)
            break
    result = {
        "icao": icao.upper(),
        "lat": lat,
        "lon": lon,
        "true_track_deg": true_track,
        "report_time": report_time,
        "message_type": message_type,
        "coordinate_text": None,
        "record": record,
    }
    altitude = basic_report.get("alt")
    if (isinstance(altitude, (int, float)) and not isinstance(altitude, bool)
            and math.isfinite(altitude)):
        result["alt"] = altitude
    accuracy = basic_report.get("pos_accuracy_nm")
    if (isinstance(accuracy, (int, float)) and not isinstance(accuracy, bool)
            and math.isfinite(accuracy) and accuracy >= 0):
        result["pos_accuracy_nm"] = accuracy
    if report_key in ("basic_report", "wpt_change_event"):
        result["predicted_route"] = route
    return result


def parse_rsi_report(record):
    frame = record.get("vdl2", {})
    if not isinstance(frame, dict) or not isinstance(frame.get("avlc"), dict):
        return None
    avlc = frame["avlc"]
    source, acars = avlc.get("src"), avlc.get("acars")
    if not isinstance(source, dict) or not isinstance(acars, dict):
        return None
    icao = source.get("addr")
    if (source.get("type") != "Aircraft" or not isinstance(icao, str)
            or not re.fullmatch(r"[0-9a-fA-F]{6}", icao)
            or acars.get("label") != "H1" or acars.get("sublabel") != "DF"
            or acars.get("err") is not False or acars.get("crc_ok") is not True
            or acars.get("more") is not False):
        return None
    text = acars.get("msg_text")
    if not isinstance(text, str):
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not re.match(r"^\s*RSI\s*\n", text):
        return None
    clock = re.search(r"(?m)^\s*(\d{2})(\d{2})\s+(\d{2})([A-Z]{3})(\d{2})\s+", text)
    row = re.search(
        r"LAT\s+LON\s+GALT\s+TTRK\s+GS\s*\n\s*"
        r"([+-]?\d+\.\d+)\s+([+-]?\d+\.\d+)\s+(\d+)\s+([+-]?\d+)\s+(\d+)\s*(?:\n|$)", text
    )
    status = re.search(
        r"INOP\s+NON-AP\s+INHB\s+POS-ERR\s*\n\s*\d+\s+\d+\s+\d+\s+(\d+)\s*(?:\n|$)", text
    )
    if not clock or not row or not status or int(status[1]) != 0:
        return None
    lat, lon, track = float(row[1]), float(row[2]), int(row[4])
    if not -90 <= lat <= 90 or not -180 <= lon <= 180 or not -180 <= track < 360:
        return None
    timestamp = frame.get("t", {})
    capture = timestamp.get("sec") if isinstance(timestamp, dict) else None
    if isinstance(capture, bool) or not isinstance(capture, (int, float)) or not math.isfinite(capture):
        return None
    months = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
    try:
        report_time = datetime.datetime(
            2000 + int(clock[5]), months.index(clock[4]) + 1, int(clock[3]),
            int(clock[1]), int(clock[2]), tzinfo=datetime.timezone.utc,
        ).timestamp()
    except (ValueError, OverflowError):
        return None
    if report_time > capture + 60:
        return None
    return {
        "icao": icao.upper(), "lat": lat, "lon": lon,
        "true_track_deg": track % 360, "report_time": report_time,
        "message_type": "H1/DF RSI", "coordinate_text": None, "record": record,
    }


class Vdl2JsonFeed:
    def __init__(self, airport_path=None):
        self.stream_id = uuid.uuid4().hex
        self.sequence = 0
        self.lock = threading.Lock()
        self.airport_path = airport_path if airport_path is not None else os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "airports.JSON"
        )
        self.airport_signature = None
        self.airport_codes = frozenset()
        self.airport_lookup_error = ""
        self.state = {
            "path": None,
            "offset": 0,
            "pending": b"",
            "identity": None,
            "frames": [],
            "frame_coordinates": [],
            "frame_ads_c": [],
            "frame_positions": [],
            "frame_airports": [],
            "frame_ids": [],
            "error": "",
            "invalid_lines": 0,
            "last_frame_time": None,
            "positions": {},
        }

    def _refresh_airport_lookup(self):
        try:
            stat = os.stat(self.airport_path)
            signature = (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size)
            if signature == self.airport_signature:
                return
            self.airport_signature = signature
            with open(self.airport_path, encoding="utf-8-sig") as lookup_file:
                lookup = json.load(lookup_file)
            if not isinstance(lookup, dict):
                raise ValueError("expected an object keyed by four-letter ICAO airport codes")
            for code, airport in lookup.items():
                if not re.fullmatch(r"[A-Z]{4}", code) or not isinstance(airport, dict):
                    raise ValueError(f"invalid airport entry: {code!r}")
                if airport.get("icao", code) != code:
                    raise ValueError(f"ICAO field does not match airport key: {code}")
            self.airport_codes = frozenset(lookup)
            self.airport_lookup_error = ""
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            if isinstance(exc, OSError):
                self.airport_signature = None
            self.airport_codes = frozenset()
            self.airport_lookup_error = f"Airport lookup unavailable ({self.airport_path}): {exc}"

    def snapshot(self, path):
        path = path.strip() if isinstance(path, str) else ""
        new_frames = []
        with self.lock:
            state = self.state
            if path != state["path"]:
                state.update({
                    "path": path,
                    "offset": 0,
                    "pending": b"",
                    "identity": None,
                    "frames": [],
                    "frame_coordinates": [],
                    "frame_ads_c": [],
                    "frame_positions": [],
                    "frame_airports": [],
                    "frame_ids": [],
                    "error": "",
                    "invalid_lines": 0,
                    "last_frame_time": None,
                    "positions": {},
                })

            if path:
                self._refresh_airport_lookup()
                try:
                    stat = os.stat(path)
                    identity = (stat.st_dev, stat.st_ino)
                    if state["identity"] is None:
                        state["identity"] = identity
                        state["offset"] = stat.st_size
                    elif identity != state["identity"] or stat.st_size < state["offset"]:
                        state["identity"] = identity
                        state["offset"] = 0
                        state["pending"] = b""

                    with open(path, "rb") as feed_file:
                        feed_file.seek(state["offset"])
                        chunk = feed_file.read()
                        state["offset"] = feed_file.tell()
                    lines = (state["pending"] + chunk).split(b"\n")
                    state["pending"] = lines.pop()
                    for raw_line in lines:
                        raw_line = raw_line.strip()
                        if not raw_line:
                            continue
                        try:
                            frame = json.loads(raw_line.decode("utf-8-sig"))
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            state["invalid_lines"] += 1
                            continue
                        if not isinstance(frame, dict) or not isinstance(frame.get("vdl2"), dict):
                            state["invalid_lines"] += 1
                            continue
                        airports = find_airport_codes(frame, self.airport_codes)
                        state["frame_airports"].append(airports)
                        state["frame_airports"] = state["frame_airports"][-100:]
                        state["frames"].append(frame)
                        state["frames"] = state["frames"][-100:]
                        state["last_frame_time"] = time.time()
                        position = parse_poss_report(frame)
                        adsc_position = parse_adsc_basic_report(frame)
                        rsi_position = parse_rsi_report(frame)
                        waypoint_position = parse_adsc_waypoint_report(frame)
                        altitude_position = parse_adsc_altitude_event(frame)
                        lateral_position = parse_adsc_lateral_event(frame)
                        xid_position = parse_xid_aircraft_location(frame)
                        parsed_positions = (position, adsc_position, rsi_position, waypoint_position,
                                            altitude_position, lateral_position, xid_position)
                        for parsed_position in parsed_positions:
                            if parsed_position:
                                parsed_position["airport_codes"] = airports
                        decoded_position = next((item for item in parsed_positions if item), None)
                        self.sequence += 1
                        state["frame_ids"].append(self.sequence)
                        state["frame_ids"] = state["frame_ids"][-100:]
                        state["frame_positions"].append(
                            {key: decoded_position.get(key) for key in
                             ("icao", "lat", "lon", "true_track_deg", "message_type", "predicted_route",
                              "position_uncertainty_nm", "pos_accuracy_nm", "alt", "airport_codes")}
                            if decoded_position else None
                        )
                        state["frame_positions"] = state["frame_positions"][-100:]
                        new_frames.append({
                            "id": self.sequence, "record": frame,
                            "position": state["frame_positions"][-1],
                            "airport_codes": airports,
                        })
                        state["frame_coordinates"].append(
                            position["coordinate_text"] if position else None
                        )
                        state["frame_coordinates"] = state["frame_coordinates"][-100:]
                        state["frame_ads_c"].append(
                            {
                                key: adsc_position[key]
                                for key in ("icao", "lat", "lon", "true_track_deg")
                            }
                            if adsc_position else None
                        )
                        state["frame_ads_c"] = state["frame_ads_c"][-100:]
                        for parsed_position in parsed_positions:
                            if not parsed_position:
                                continue
                            key = (parsed_position["icao"], parsed_position["message_type"])
                            history = state["positions"].setdefault(key, [])
                            duplicate_index = next((
                                index for index, item in enumerate(history)
                                if item["report_time"] == parsed_position["report_time"]
                                and (
                                    item.get("coordinate_text") == parsed_position["coordinate_text"]
                                    if parsed_position["coordinate_text"] is not None
                                    else item["lat"] == parsed_position["lat"]
                                    and item["lon"] == parsed_position["lon"]
                                    and item.get("true_track_deg") == parsed_position["true_track_deg"]
                                )
                            ), None)
                            if duplicate_index is None:
                                history.append(parsed_position)
                                history.sort(key=lambda item: item["report_time"])
                            else:
                                history[duplicate_index] = parsed_position
                    state["error"] = ""
                except OSError as exc:
                    state["error"] = str(exc)
            else:
                state["error"] = ""

            now = time.time()
            state["positions"] = {
                key: [
                    position for position in history
                    if 0 <= now - position["report_time"] < 600
                ]
                for key, history in state["positions"].items()
            }
            state["positions"] = {
                key: history for key, history in state["positions"].items() if history
            }
            return {
                "path": path,
                "configured": bool(path),
                "connected": bool(path) and not state["error"],
                "error": state["error"],
                "invalid_lines": state["invalid_lines"],
                "last_frame_time": state["last_frame_time"],
                "frames": list(state["frames"]),
                "frame_coordinates": list(state["frame_coordinates"]),
                "frame_ads_c": list(state["frame_ads_c"]),
                "frame_positions": list(state["frame_positions"]),
                "frame_airports": list(state["frame_airports"]),
                "airport_lookup_error": self.airport_lookup_error if path else "",
                "frame_ids": list(state["frame_ids"]),
                "stream_id": self.stream_id,
                "new_frames": new_frames,
                "positions": [
                    position for history in state["positions"].values() for position in history
                ],
            }
