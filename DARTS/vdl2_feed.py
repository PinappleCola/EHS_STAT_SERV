import json
import datetime
import math
import os
import re
import threading
import time
import uuid


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
        if basic_report is None and isinstance(tag.get("basic_report"), dict):
            basic_report = tag["basic_report"]
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
    return {
        "icao": icao.upper(),
        "lat": lat,
        "lon": lon,
        "true_track_deg": true_track,
        "report_time": float(capture),
        "message_type": "ADS-C BASIC",
        "coordinate_text": None,
        "record": record,
    }


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
    def __init__(self):
        self.stream_id = uuid.uuid4().hex
        self.sequence = 0
        self.lock = threading.Lock()
        self.state = {
            "path": None,
            "offset": 0,
            "pending": b"",
            "identity": None,
            "frames": [],
            "frame_coordinates": [],
            "frame_ads_c": [],
            "frame_positions": [],
            "frame_ids": [],
            "error": "",
            "invalid_lines": 0,
            "last_frame_time": None,
            "positions": {},
        }

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
                    "frame_ids": [],
                    "error": "",
                    "invalid_lines": 0,
                    "last_frame_time": None,
                    "positions": {},
                })

            if path:
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
                        state["frames"].append(frame)
                        state["frames"] = state["frames"][-100:]
                        state["last_frame_time"] = time.time()
                        position = parse_poss_report(frame)
                        adsc_position = parse_adsc_basic_report(frame)
                        rsi_position = parse_rsi_report(frame)
                        decoded_position = position or adsc_position or rsi_position
                        self.sequence += 1
                        state["frame_ids"].append(self.sequence)
                        state["frame_ids"] = state["frame_ids"][-100:]
                        state["frame_positions"].append(
                            {key: decoded_position.get(key) for key in
                             ("icao", "lat", "lon", "true_track_deg", "message_type")}
                            if decoded_position else None
                        )
                        state["frame_positions"] = state["frame_positions"][-100:]
                        new_frames.append({
                            "id": self.sequence, "record": frame,
                            "position": state["frame_positions"][-1],
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
                        for parsed_position in (position, adsc_position, rsi_position):
                            if not parsed_position:
                                continue
                            key = (parsed_position["icao"], parsed_position["message_type"])
                            history = state["positions"].setdefault(key, [])
                            duplicate = any(
                                item["report_time"] == parsed_position["report_time"]
                                and (
                                    item.get("coordinate_text") == parsed_position["coordinate_text"]
                                    if parsed_position["coordinate_text"] is not None
                                    else item["lat"] == parsed_position["lat"]
                                    and item["lon"] == parsed_position["lon"]
                                    and item.get("true_track_deg") == parsed_position["true_track_deg"]
                                )
                                for item in history
                            )
                            if not duplicate:
                                history.append(parsed_position)
                                history.sort(key=lambda item: item["report_time"])
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
                "frame_ids": list(state["frame_ids"]),
                "stream_id": self.stream_id,
                "new_frames": new_frames,
                "positions": [
                    position for history in state["positions"].values() for position in history
                ],
            }
