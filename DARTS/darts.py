# ==========================================
# DART-B CORE
# APP VERSION: v53
# ENTRYPOINT FILE: darts.py
# NOTE: The filename is retained for compatibility. Runtime versioning lives in
# the APP_VERSION constant below so comments and behavior cannot drift apart.
# ==========================================

import serial
import time
import datetime
import json
import math
import threading
import asyncio
import websockets
import binascii
import sqlite3
import queue
import re
import os
import http.server

APP_VERSION = "v53"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "runtime_config.json")

try:
    import pyModeS as pms
except ImportError:
    pms = None

def load_runtime_config():
    config = {
        "port": "COM5",
        "baud": 115200,
        "ws_host": "localhost",
        "ws_port": 8765,
        "http_port": 8766,
        "receiver_id": "ADSBEE-01",
    }

    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r") as config_file:
                loaded = json.load(config_file)
            if isinstance(loaded, dict):
                config.update({key: value for key, value in loaded.items() if value not in [None, ""]})
    except Exception as exc:
        print(f"{ANSI.DIM}[{get_iso_time()}]{ANSI.RESET} {ANSI.YELLOW}WARNING: runtime_config.json load failed: {exc}. Using defaults/environment.{ANSI.RESET}")

    config["port"] = os.getenv("EHS_PORT", config["port"])
    config["baud"] = int(os.getenv("EHS_BAUD", config["baud"]))
    config["ws_host"] = os.getenv("EHS_WS_HOST", config["ws_host"])
    config["ws_port"] = int(os.getenv("EHS_WS_PORT", config["ws_port"]))
    config["http_port"] = int(os.getenv("EHS_HTTP_PORT", config["http_port"]))
    config["receiver_id"] = os.getenv("EHS_RECEIVER_ID", config["receiver_id"])
    return config

# --- Windows ANSI Compatibility Hook ---
if os.name == "nt":
    os.system("color")

# --- Terminal ANSI Color Palette ---
class ANSI:
    RESET = '\033[0m'
    DIM = '\033[90m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'

# --- Optional pyModeS Support ---
MODE_S_POLY = 0xFFF409

def mode_s_crc(message_hex):
    try:
        bit_length = len(message_hex) * 4
        working = int(message_hex[:-6] + "000000", 16)
        for shift in range(bit_length - 24):
            top_bit = 1 << (bit_length - 1 - shift)
            if working & top_bit:
                working ^= MODE_S_POLY << (bit_length - 25 - shift)
        return working & 0xFFFFFF
    except Exception:
        return None

def extract_icao_address(message_hex):
    try:
        df_int = int(message_hex[:2], 16) >> 3
    except Exception:
        return None

    if df_int in {11, 17, 18} and len(message_hex) >= 8:
        return message_hex[2:8].upper()

    if df_int in {20, 21} and len(message_hex) >= 28:
        crc = mode_s_crc(message_hex)
        if crc is None:
            return None
        parity = int(message_hex[-6:], 16)
        return f"{crc ^ parity:06X}"

    return None

def wrong_status(payload_int, status_bit, start_bit, bit_length):
    status = (payload_int >> (55 - status_bit)) & 0x1
    mask = (1 << bit_length) - 1
    value = (payload_int >> (55 - (start_bit + bit_length - 1))) & mask
    return status == 0 and value != 0

def signed_magnitude(raw_value, sign_bit):
    return -raw_value if sign_bit else raw_value

def normalise_angle(angle_deg):
    return angle_deg % 360.0

def is_bds40_payload(payload_int):
    if payload_int == 0:
        return False

    if wrong_status(payload_int, 0, 1, 12):
        return False
    if wrong_status(payload_int, 13, 14, 12):
        return False
    if wrong_status(payload_int, 26, 27, 12):
        return False
    if wrong_status(payload_int, 47, 48, 3):
        return False
    if wrong_status(payload_int, 53, 54, 2):
        return False

    if ((payload_int >> (55 - 46)) & 0xFF) != 0:
        return False
    if ((payload_int >> (55 - 52)) & 0x3) != 0:
        return False

    meaningful_status = [0, 13, 26, 47, 53]
    return any(((payload_int >> (55 - bit)) & 0x1) == 1 for bit in meaningful_status)

def decode_bds40_payload(payload_int):
    result = {}

    if (payload_int >> (55 - 0)) & 0x1:
        result["selected_altitude_mcp"] = ((payload_int >> (55 - 12)) & 0xFFF) * 16
    if (payload_int >> (55 - 13)) & 0x1:
        result["selected_altitude_fms"] = ((payload_int >> (55 - 25)) & 0xFFF) * 16
    if (payload_int >> (55 - 26)) & 0x1:
        result["baro_pressure_setting"] = (((payload_int >> (55 - 38)) & 0xFFF) * 0.1) + 800.0

    return result

def is_bds50_payload(payload_int):
    if payload_int == 0:
        return False

    if wrong_status(payload_int, 0, 1, 10):
        return False
    if wrong_status(payload_int, 11, 12, 11):
        return False
    if wrong_status(payload_int, 23, 24, 10):
        return False
    if wrong_status(payload_int, 34, 35, 10):
        return False
    if wrong_status(payload_int, 45, 46, 10):
        return False

    roll_status = (payload_int >> (55 - 0)) & 0x1
    roll_sign = (payload_int >> (55 - 1)) & 0x1
    roll_mag = (payload_int >> (55 - 10)) & 0x1FF

    gs_status = (payload_int >> (55 - 23)) & 0x1
    gs_raw = (payload_int >> (55 - 33)) & 0x3FF

    tas_status = (payload_int >> (55 - 45)) & 0x1
    tas_raw = (payload_int >> (55 - 55)) & 0x3FF

    if roll_status:
        roll_deg = signed_magnitude(roll_mag, roll_sign) * 45.0 / 256.0
        if abs(roll_deg) > 35.0:
            return False

    if gs_status and gs_raw * 2 > 600:
        return False
    if tas_status and tas_raw * 2 > 600:
        return False
    if gs_status and tas_status and abs((tas_raw * 2) - (gs_raw * 2)) > 200:
        return False

    return True

def decode_bds50_payload(payload_int):
    result = {}

    if (payload_int >> (55 - 0)) & 0x1:
        sign = (payload_int >> (55 - 1)) & 0x1
        mag = (payload_int >> (55 - 10)) & 0x1FF
        result["roll"] = signed_magnitude(mag, sign) * 45.0 / 256.0

    if (payload_int >> (55 - 11)) & 0x1:
        sign = (payload_int >> (55 - 12)) & 0x1
        raw = (payload_int >> (55 - 22)) & 0x3FF
        result["true_track"] = normalise_angle(signed_magnitude(raw, sign) * 90.0 / 512.0)

    if (payload_int >> (55 - 23)) & 0x1:
        result["groundspeed"] = ((payload_int >> (55 - 33)) & 0x3FF) * 2

    if (payload_int >> (55 - 34)) & 0x1:
        sign = (payload_int >> (55 - 35)) & 0x1
        mag = (payload_int >> (55 - 44)) & 0x1FF
        result["track_rate"] = signed_magnitude(mag, sign) * 8.0 / 256.0

    if (payload_int >> (55 - 45)) & 0x1:
        result["true_airspeed"] = ((payload_int >> (55 - 55)) & 0x3FF) * 2

    return result

def is_bds60_payload(payload_int):
    if payload_int == 0:
        return False

    if wrong_status(payload_int, 0, 1, 11):
        return False
    if wrong_status(payload_int, 12, 13, 10):
        return False
    if wrong_status(payload_int, 23, 24, 10):
        return False
    if wrong_status(payload_int, 34, 35, 10):
        return False
    if wrong_status(payload_int, 45, 46, 10):
        return False

    ias_status = (payload_int >> (55 - 12)) & 0x1
    ias_raw = (payload_int >> (55 - 22)) & 0x3FF
    mach_status = (payload_int >> (55 - 23)) & 0x1
    mach_raw = (payload_int >> (55 - 33)) & 0x3FF
    vrb_status = (payload_int >> (55 - 34)) & 0x1
    vrb_sign = (payload_int >> (55 - 35)) & 0x1
    vrb_mag = (payload_int >> (55 - 44)) & 0x1FF
    vri_status = (payload_int >> (55 - 45)) & 0x1
    vri_sign = (payload_int >> (55 - 46)) & 0x1
    vri_mag = (payload_int >> (55 - 55)) & 0x1FF

    if ias_status and ias_raw > 500:
        return False
    if mach_status and (mach_raw * 2.048 / 512.0) > 1.0:
        return False
    if vrb_status and abs(signed_magnitude(vrb_mag, vrb_sign) * 32) > 6000:
        return False
    if vri_status and abs(signed_magnitude(vri_mag, vri_sign) * 32) > 6000:
        return False

    return True

def decode_bds60_payload(payload_int):
    result = {}

    if (payload_int >> (55 - 0)) & 0x1:
        sign = (payload_int >> (55 - 1)) & 0x1
        raw = (payload_int >> (55 - 11)) & 0x3FF
        result["magnetic_heading"] = normalise_angle(signed_magnitude(raw, sign) * 90.0 / 512.0)

    if (payload_int >> (55 - 12)) & 0x1:
        result["indicated_airspeed"] = (payload_int >> (55 - 22)) & 0x3FF

    if (payload_int >> (55 - 23)) & 0x1:
        result["mach"] = ((payload_int >> (55 - 33)) & 0x3FF) * 2.048 / 512.0

    if (payload_int >> (55 - 34)) & 0x1:
        sign = (payload_int >> (55 - 35)) & 0x1
        mag = (payload_int >> (55 - 44)) & 0x1FF
        result["baro_vertical_rate"] = signed_magnitude(mag, sign) * 32

    if (payload_int >> (55 - 45)) & 0x1:
        sign = (payload_int >> (55 - 46)) & 0x1
        mag = (payload_int >> (55 - 55)) & 0x1FF
        result["inertial_vertical_rate"] = signed_magnitude(mag, sign) * 32

    return result

def is_bds17_payload(payload_int):
    if payload_int == 0:
        return False
    if ((payload_int >> (55 - 6)) & 0x1) == 0:
        return False
    return (payload_int & ((1 << 32) - 1)) == 0

CAPABILITY_BDS = [
    "0,5", "0,6", "0,7", "0,8", "0,9", "0,A",
    "2,0", "2,1",
    "4,0", "4,1", "4,2", "4,3", "4,4", "4,5", "4,8",
    "5,0", "5,1", "5,2", "5,3", "5,4", "5,5", "5,6", "5,F",
    "6,0",
]

# ==========================================
# --- LIVE GRID FIELD REGISTRY (single source of truth) ---
# Each entry describes one selectable grid column.
# Fields marked defaultVisible=True form the initial default layout.
# 'key' must match the aircraft_state dict key (or a virtual aggregation key).
# Virtual keys (sys_mode, ias_mach, track_info, latlon, meteo) are computed
# in the frontend renderer from their constituent raw fields.
# ==========================================
FIELD_REGISTRY = [
    # --- Identification ---
    {"key": "icao",             "label": "ICAO",           "type": "text",   "unit": None,   "category": "IDENTIFICATION", "sortable": True,  "defaultVisible": True,  "source": "PI Parity"},
    {"key": "callsign",         "label": "CALLSIGN",       "type": "text",   "unit": None,   "category": "IDENTIFICATION", "sortable": True,  "defaultVisible": True,  "source": "DF17 TC:1-4"},
    {"key": "airline",          "label": "AIRLINE",        "type": "text",   "unit": None,   "category": "IDENTIFICATION", "sortable": True,  "defaultVisible": True,  "source": "DB Lookup"},
    {"key": "squawk",           "label": "SQUAWK",         "type": "text",   "unit": None,   "category": "IDENTIFICATION", "sortable": True,  "defaultVisible": True,  "source": "DF11 / DF21"},
    # --- Altitude ---
    {"key": "alt",              "label": "ALTITUDE",       "type": "number", "unit": "ft",   "category": "ALTITUDE",       "sortable": True,  "defaultVisible": True,  "source": "DF17 / DF20"},
    {"key": "target_alt",       "label": "TARGET ALT",     "type": "text",   "unit": "ft",   "category": "ALTITUDE",       "sortable": False, "defaultVisible": True,  "source": "BDS 4,0"},
    # --- Kinematics ---
    {"key": "vert_rate",        "label": "VERT RATE",      "type": "number", "unit": "ft/m", "category": "KINEMATICS",     "sortable": True,  "defaultVisible": True,  "source": "BDS 6,0"},
    # sys_mode and baro are placed here so the default column order matches the original live grid layout
    {"key": "sys_mode",         "label": "SYS MODE",       "type": "virtual","unit": None,   "category": "SYSTEM",         "sortable": False, "defaultVisible": True,  "source": "BDS 4,0/6,2/4,8"},
    {"key": "baro",             "label": "BARO SET",       "type": "text",   "unit": "hPa",  "category": "SYSTEM",         "sortable": False, "defaultVisible": True,  "source": "BDS 4,0"},
    {"key": "speed",            "label": "SPEED GS",       "type": "number", "unit": "kt",   "category": "KINEMATICS",     "sortable": True,  "defaultVisible": True,  "source": "BDS 5,0 / TC19"},
    {"key": "tas",              "label": "TAS",            "type": "number", "unit": "kt",   "category": "KINEMATICS",     "sortable": True,  "defaultVisible": True,  "source": "BDS 5,0"},
    {"key": "ias_mach",         "label": "IAS / MACH",     "type": "virtual","unit": None,   "category": "KINEMATICS",     "sortable": False, "defaultVisible": True,  "source": "BDS 6,0"},
    {"key": "ias",              "label": "IAS",            "type": "number", "unit": "kt",   "category": "KINEMATICS",     "sortable": True,  "defaultVisible": False, "source": "BDS 6,0"},
    {"key": "mach",             "label": "MACH",           "type": "number", "unit": None,   "category": "KINEMATICS",     "sortable": True,  "defaultVisible": False, "source": "BDS 6,0"},
    {"key": "heading",          "label": "MAG HDG",        "type": "angle",  "unit": "deg",  "category": "KINEMATICS",     "sortable": True,  "defaultVisible": True,  "source": "BDS 6,0"},
    {"key": "track_info",       "label": "TRUE TRK / RATE","type": "virtual","unit": None,   "category": "KINEMATICS",     "sortable": False, "defaultVisible": True,  "source": "BDS 5,0"},
    {"key": "track",            "label": "TRUE TRK",       "type": "angle",  "unit": "deg",  "category": "KINEMATICS",     "sortable": True,  "defaultVisible": False, "source": "BDS 5,0"},
    {"key": "track_rate",       "label": "TRACK RATE",     "type": "number", "unit": "deg/s","category": "KINEMATICS",     "sortable": True,  "defaultVisible": False, "source": "BDS 5,0"},
    {"key": "roll",             "label": "BANK INDEX",     "type": "angle",  "unit": "deg",  "category": "KINEMATICS",     "sortable": True,  "defaultVisible": True,  "source": "BDS 5,0"},
    # --- Additional system fields ---
    {"key": "discretes",        "label": "DISCRETES",      "type": "text",   "unit": None,   "category": "SYSTEM",         "sortable": False, "defaultVisible": False, "source": "BDS 6,2 / TC29"},
    {"key": "capability_summary","label":"CAPABILITIES",   "type": "text",   "unit": None,   "category": "SYSTEM",         "sortable": False, "defaultVisible": False, "source": "BDS 1,7"},
    {"key": "last_bds_hit",     "label": "LAST BDS HIT",   "type": "text",   "unit": None,   "category": "SYSTEM",         "sortable": False, "defaultVisible": False, "source": "Decoded"},
    {"key": "supported_bds",    "label": "SUPP BDS REGS",  "type": "text",   "unit": None,   "category": "SYSTEM",         "sortable": False, "defaultVisible": False, "source": "BDS 1,7"},
    # --- Safety ---
    {"key": "tcas_ra",          "label": "TCAS RA",        "type": "text",   "unit": None,   "category": "SAFETY",         "sortable": False, "defaultVisible": True,  "source": "BDS 3,0"},
    {"key": "hazard",           "label": "HAZARD",         "type": "text",   "unit": None,   "category": "SAFETY",         "sortable": False, "defaultVisible": False, "source": "BDS 4,4/4,5"},
    # --- Surveillance ---
    {"key": "radar_sweep",      "label": "RADAR SWEEP",    "type": "text",   "unit": "s",    "category": "SURVEILLANCE",   "sortable": False, "defaultVisible": True,  "source": "Δt(Burst) Calc"},
    # --- Position ---
    {"key": "gnss_qual",        "label": "GNSS QUAL",      "type": "text",   "unit": None,   "category": "POSITION",       "sortable": False, "defaultVisible": True,  "source": "DF17 TC:31"},
    {"key": "latlon",           "label": "LAT / LON",      "type": "virtual","unit": "deg",  "category": "POSITION",       "sortable": False, "defaultVisible": True,  "source": "Local CPR Math"},
    {"key": "lat",              "label": "LATITUDE",       "type": "number", "unit": "deg",  "category": "POSITION",       "sortable": True,  "defaultVisible": False, "source": "Local CPR Math"},
    {"key": "lon",              "label": "LONGITUDE",      "type": "number", "unit": "deg",  "category": "POSITION",       "sortable": True,  "defaultVisible": False, "source": "Local CPR Math"},
    # --- Meteorology ---
    {"key": "meteo",            "label": "METEO / SENSORS","type": "virtual","unit": None,   "category": "METEO",          "sortable": False, "defaultVisible": True,  "source": "BDS4,4 + Calc"},
    {"key": "wind",             "label": "WIND",           "type": "text",   "unit": None,   "category": "METEO",          "sortable": False, "defaultVisible": False, "source": "BDS 4,4 Calc"},
    {"key": "sat",              "label": "SAT TEMP",       "type": "text",   "unit": "°C",   "category": "METEO",          "sortable": False, "defaultVisible": False, "source": "BDS 4,4/4,5"},
    # --- System timing ---
    {"key": "age",              "label": "AGE",            "type": "number", "unit": "s",    "category": "SYSTEM",         "sortable": True,  "defaultVisible": True,  "source": "Sys Clock"},
]

def decode_bds17_payload(payload_int):
    supported = []
    for index, bds_code in enumerate(CAPABILITY_BDS):
        if (payload_int >> (55 - index)) & 0x1:
            supported.append(bds_code)
    return {"supported_bds": supported}

def is_bds30_payload(payload_int):
    if payload_int == 0:
        return False

    if (payload_int >> 48) & 0xFF != 0x30:
        return False

    ara_reserved = (payload_int >> (55 - 21)) & 0x7F
    if ara_reserved >= 48:
        return False

    threat_type = (payload_int >> (55 - 29)) & 0x3
    return threat_type != 0x3

def decode_bds30_payload(payload_int):
    result = {
        "threat_type_indicator": (payload_int >> (55 - 29)) & 0x3,
        "issued_ra": bool((payload_int >> (55 - 8)) & 0x1),
        "corrective": bool((payload_int >> (55 - 9)) & 0x1),
        "downward_sense": bool((payload_int >> (55 - 10)) & 0x1),
        "increased_rate": bool((payload_int >> (55 - 11)) & 0x1),
        "sense_reversal": bool((payload_int >> (55 - 12)) & 0x1),
        "altitude_crossing": bool((payload_int >> (55 - 13)) & 0x1),
        "positive": bool((payload_int >> (55 - 14)) & 0x1),
        "no_below": bool((payload_int >> (55 - 22)) & 0x1),
        "no_above": bool((payload_int >> (55 - 23)) & 0x1),
        "no_left": bool((payload_int >> (55 - 24)) & 0x1),
        "no_right": bool((payload_int >> (55 - 25)) & 0x1),
        "ra_terminated": bool((payload_int >> (55 - 26)) & 0x1),
        "multiple_threat": bool((payload_int >> (55 - 27)) & 0x1),
    }

    threat_type = result["threat_type_indicator"]
    if threat_type == 1:
        threat_icao = (payload_int >> 2) & 0xFFFFFF
        result["threat_icao"] = f"{threat_icao:06X}"
    elif threat_type == 2:
        range_raw = (payload_int >> 6) & 0x7F
        bearing_raw = payload_int & 0x3F
        result["threat_range_nm"] = round((range_raw - 1) / 10.0, 1) if range_raw > 0 else None
        result["threat_bearing_deg"] = (6 * (bearing_raw - 1) + 3) if bearing_raw > 0 else None

    return result

def decode_bds62_payload(payload_int):
    result = {"subtype": (payload_int >> 49) & 0x3}

    alt_source_bit = (payload_int >> 47) & 0x1
    alt_raw = (payload_int >> 36) & 0x7FF
    if alt_raw == 0:
        result["selected_altitude"] = None
        result["selected_altitude_source"] = "N/A"
    else:
        result["selected_altitude"] = (alt_raw - 1) * 32
        result["selected_altitude_source"] = "FMS" if alt_source_bit == 1 else "MCP/FCU"

    baro_raw = (payload_int >> 27) & 0x1FF
    result["baro_pressure_setting"] = None if baro_raw == 0 else 800 + (baro_raw - 1) * 0.8

    hdg_status = (payload_int >> 26) & 0x1
    hdg_raw = (payload_int >> 17) & 0x1FF
    result["selected_heading"] = None if hdg_status == 0 else hdg_raw * 360 / 512

    result["nac_p"] = (payload_int >> 13) & 0xF
    result["nic_baro"] = (payload_int >> 12) & 0x1
    result["sil"] = (payload_int >> 10) & 0x3

    mode_status = (payload_int >> 9) & 0x1
    if mode_status == 0:
        result["autopilot"] = None
        result["vnav_mode"] = None
        result["altitude_hold_mode"] = None
        result["approach_mode"] = None
        result["lnav_mode"] = None
    else:
        result["autopilot"] = bool((payload_int >> 8) & 0x1)
        result["vnav_mode"] = bool((payload_int >> 7) & 0x1)
        result["altitude_hold_mode"] = bool((payload_int >> 6) & 0x1)
        result["approach_mode"] = bool((payload_int >> 4) & 0x1)
        result["lnav_mode"] = bool((payload_int >> 2) & 0x1)

    result["tcas_operational"] = bool((payload_int >> 3) & 0x1)
    return result

def summarise_capabilities(supported_bds):
    if not supported_bds:
        return "----"

    buckets = []
    if any(code.startswith("4,") or code.startswith("5,") or code.startswith("6,") for code in supported_bds):
        buckets.append("EHS")
    if any(code in {"4,1", "4,2", "4,3"} for code in supported_bds):
        buckets.append("INT")
    if any(code in {"4,4", "4,5"} for code in supported_bds):
        buckets.append("MET")
    if any(code.startswith("0,") for code in supported_bds):
        buckets.append("ES")

    if not buckets:
        buckets.append("GICB")
    return "CAP:" + "/".join(buckets)

def summarise_target_state_modes(decoded_data):
    mode_flags = []
    if decoded_data.get("autopilot") is True:
        mode_flags.append("AP")
    if decoded_data.get("vnav_mode") is True:
        mode_flags.append("VNAV")
    if decoded_data.get("altitude_hold_mode") is True:
        mode_flags.append("ALTHLD")
    if decoded_data.get("approach_mode") is True:
        mode_flags.append("APP")
    if decoded_data.get("lnav_mode") is True:
        mode_flags.append("LNAV")
    if decoded_data.get("tcas_operational") is True:
        mode_flags.append("TCAS")

    if mode_flags:
        return "/".join(mode_flags)
    if decoded_data.get("autopilot") is False:
        return "MANUAL"
    return "----"

def summarise_target_state_quality(decoded_data):
    parts = []
    nac_p = decoded_data.get("nac_p")
    sil = decoded_data.get("sil")
    if nac_p is not None:
        parts.append(f"NACp:{nac_p}")
    if sil is not None:
        parts.append(f"SIL:{sil}")
    if decoded_data.get("nic_baro"):
        parts.append("NICbaro")
    return " / ".join(parts) if parts else "----"

def build_target_state_log(icao, decoded_data):
    segments = []
    if decoded_data.get("selected_altitude") is not None:
        segments.append(f"{decoded_data.get('selected_altitude_source', 'N/A')} {int(decoded_data['selected_altitude'])}ft")
    if decoded_data.get("selected_heading") is not None:
        segments.append(f"HDG {round(float(decoded_data['selected_heading']))}deg")

    mode_summary = summarise_target_state_modes(decoded_data)
    if mode_summary != "----":
        segments.append(mode_summary)

    quality_summary = summarise_target_state_quality(decoded_data)
    if quality_summary != "----":
        segments.append(quality_summary)

    if not segments:
        return None, None

    ui_time = get_ui_time()
    summary = " | ".join(segments)
    log_text = (
        f"> <span class=\"ts-badge\">[{ui_time}]</span> TARGET STATE: "
        f"<span class=\"icao-badge\">{icao}</span> {summary}"
    )
    return f"tc29_{icao}_{summary}", log_text

def summarise_tcas_ra(decoded_data):
    if decoded_data.get("issued_ra") is not True:
        return "RA TERM" if decoded_data.get("ra_terminated") else "CLEAN"

    parts = ["RA"]
    parts.append("DESC" if decoded_data.get("downward_sense") else "CLB")
    parts.append("CORR" if decoded_data.get("corrective") else "PREV")

    if decoded_data.get("increased_rate"):
        parts.append("INC")
    if decoded_data.get("sense_reversal"):
        parts.append("REV")
    if decoded_data.get("altitude_crossing"):
        parts.append("XING")
    if decoded_data.get("positive"):
        parts.append("POS")
    if decoded_data.get("multiple_threat"):
        parts.append("MULTI")

    return " ".join(parts)

def build_tcas_ra_log(icao, decoded_data):
    summary = summarise_tcas_ra(decoded_data)
    if summary == "CLEAN":
        return None, None

    segments = [summary]

    blocked = []
    if decoded_data.get("no_below"):
        blocked.append("NO-BELOW")
    if decoded_data.get("no_above"):
        blocked.append("NO-ABOVE")
    if decoded_data.get("no_left"):
        blocked.append("NO-LEFT")
    if decoded_data.get("no_right"):
        blocked.append("NO-RIGHT")
    if blocked:
        segments.append("/".join(blocked))

    threat_type = decoded_data.get("threat_type_indicator")
    if threat_type == 1 and decoded_data.get("threat_icao"):
        segments.append(f"THREAT {decoded_data['threat_icao']}")
    elif threat_type == 2:
        threat_parts = []
        if decoded_data.get("threat_range_nm") is not None:
            threat_parts.append(f"{decoded_data['threat_range_nm']}NM")
        if decoded_data.get("threat_bearing_deg") is not None:
            threat_parts.append(f"BRG {int(decoded_data['threat_bearing_deg'])}deg")
        if threat_parts:
            segments.append("THREAT " + " ".join(threat_parts))

    ui_time = get_ui_time()
    summary_text = " | ".join(segments)
    log_text = (
        f"> <span class=\"ts-badge\">[{ui_time}]</span> TCAS RA: "
        f"<span class=\"icao-badge\">{icao}</span> {summary_text}"
    )
    return f"ra_{icao}_{summary_text}", log_text

def is_bds44_payload(payload_int):
    if payload_int == 0:
        return False

    fom = (payload_int >> (55 - 3)) & 0xF
    if fom > 4:
        return False

    if ((payload_int >> (55 - 4)) & 0x1) == 0:
        return False

    if wrong_status(payload_int, 34, 35, 11):
        return False
    if wrong_status(payload_int, 46, 47, 2):
        return False
    if wrong_status(payload_int, 49, 50, 6):
        return False

    wind_speed = (payload_int >> (55 - 13)) & 0x1FF
    wind_dir_raw = (payload_int >> (55 - 22)) & 0x1FF
    temp_sign = (payload_int >> (55 - 23)) & 0x1
    temp_raw = (payload_int >> (55 - 33)) & 0x3FF
    temp_c = signed_magnitude(temp_raw, temp_sign) * 0.25

    if wind_speed > 250:
        return False
    if temp_c < -80.0 or temp_c > 60.0:
        return False

    return not (wind_speed == 0 and wind_dir_raw == 0 and temp_raw == 0)

def decode_bds44_payload(payload_int):
    result = {"figure_of_merit": (payload_int >> (55 - 3)) & 0xF}

    if (payload_int >> (55 - 4)) & 0x1:
        result["wind_speed"] = (payload_int >> (55 - 13)) & 0x1FF
        result["wind_direction"] = ((payload_int >> (55 - 22)) & 0x1FF) * (180.0 / 256.0)

    temp_sign = (payload_int >> (55 - 23)) & 0x1
    temp_raw = (payload_int >> (55 - 33)) & 0x3FF
    result["static_air_temperature"] = signed_magnitude(temp_raw, temp_sign) * 0.25

    if (payload_int >> (55 - 34)) & 0x1:
        result["static_pressure"] = (payload_int >> (55 - 45)) & 0x7FF
    if (payload_int >> (55 - 46)) & 0x1:
        result["turbulence"] = (payload_int >> (55 - 48)) & 0x3
    if (payload_int >> (55 - 49)) & 0x1:
        result["humidity"] = ((payload_int >> (55 - 55)) & 0x3F) * (100.0 / 64.0)

    return result

def is_bds45_payload(payload_int):
    if payload_int == 0:
        return False
    if is_bds17_payload(payload_int):
        return False
    if (payload_int & 0x1F) != 0:
        return False

    if wrong_status(payload_int, 0, 1, 2):
        return False
    if wrong_status(payload_int, 3, 4, 2):
        return False
    if wrong_status(payload_int, 6, 7, 2):
        return False
    if wrong_status(payload_int, 9, 10, 2):
        return False
    if wrong_status(payload_int, 12, 13, 2):
        return False
    if wrong_status(payload_int, 15, 16, 10):
        return False
    if wrong_status(payload_int, 26, 27, 11):
        return False
    if wrong_status(payload_int, 38, 39, 12):
        return False

    if (payload_int >> (55 - 15)) & 0x1:
        temp_sign = (payload_int >> (55 - 16)) & 0x1
        temp_mag = (payload_int >> (55 - 25)) & 0x1FF
        temp_c = signed_magnitude(temp_mag, temp_sign) * 0.25
        if temp_c < -80.0 or temp_c > 60.0:
            return False

    return True

def decode_bds45_payload(payload_int):
    result = {}

    if (payload_int >> (55 - 0)) & 0x1:
        result["turbulence"] = (payload_int >> (55 - 2)) & 0x3
    if (payload_int >> (55 - 3)) & 0x1:
        result["wind_shear"] = (payload_int >> (55 - 5)) & 0x3
    if (payload_int >> (55 - 6)) & 0x1:
        result["microburst"] = (payload_int >> (55 - 8)) & 0x3
    if (payload_int >> (55 - 9)) & 0x1:
        result["icing"] = (payload_int >> (55 - 11)) & 0x3
    if (payload_int >> (55 - 12)) & 0x1:
        result["wake_vortex"] = (payload_int >> (55 - 14)) & 0x3
    if (payload_int >> (55 - 15)) & 0x1:
        temp_sign = (payload_int >> (55 - 16)) & 0x1
        temp_mag = (payload_int >> (55 - 25)) & 0x1FF
        result["static_air_temperature"] = signed_magnitude(temp_mag, temp_sign) * 0.25
    if (payload_int >> (55 - 26)) & 0x1:
        result["static_pressure"] = (payload_int >> (55 - 37)) & 0x7FF
    if (payload_int >> (55 - 38)) & 0x1:
        result["radio_height"] = ((payload_int >> (55 - 50)) & 0xFFF) * 16

    return result

def format_temperature(temp_c):
    return f"{round(float(temp_c), 1)}C"

def turbulence_label(level):
    labels = {0: "TURB NIL", 1: "TURB LGT", 2: "TURB MOD", 3: "TURB SEV"}
    return labels.get(level)

def build_hazard_summary(decoded_data):
    labels = {
        "turbulence": {0: None, 1: "TURB LGT", 2: "TURB MOD", 3: "TURB SEV"},
        "wind_shear": {0: None, 1: "WS LGT", 2: "WS MOD", 3: "WS SEV"},
        "microburst": {0: None, 1: "MB LGT", 2: "MB MOD", 3: "MB SEV"},
        "icing": {0: None, 1: "ICE LGT", 2: "ICE MOD", 3: "ICE SEV"},
        "wake_vortex": {0: None, 1: "WV LGT", 2: "WV MOD", 3: "WV SEV"},
    }

    parts = []
    for field_name, field_labels in labels.items():
        value = decoded_data.get(field_name)
        if value is None:
            continue
        label = field_labels.get(value)
        if label:
            parts.append(label)
    return " | ".join(parts) if parts else "----"

def angular_difference(angle_a, angle_b):
    diff = abs(float(angle_a) - float(angle_b)) % 360.0
    return min(diff, 360.0 - diff)

def score_bds50(decoded_data, known_state):
    score = 0.0
    matched = 0

    known_speed = known_state.get("speed")
    if known_speed not in [None, "----"] and decoded_data.get("groundspeed") is not None:
        score += abs(float(decoded_data["groundspeed"]) - float(known_speed)) / 50.0
        matched += 1

    known_track = known_state.get("track")
    if known_track not in [None, "----"] and decoded_data.get("true_track") is not None:
        score += angular_difference(decoded_data["true_track"], known_track) / 30.0
        matched += 1

    known_tas = known_state.get("tas")
    if known_tas not in [None, "----"] and decoded_data.get("true_airspeed") is not None:
        score += abs(float(decoded_data["true_airspeed"]) - float(known_tas)) / 50.0
        matched += 1

    return score if matched > 0 else float("inf")

def score_bds60(decoded_data, known_state):
    score = 0.0
    matched = 0

    known_heading = known_state.get("heading")
    if known_heading not in [None, "----"] and decoded_data.get("magnetic_heading") is not None:
        score += angular_difference(decoded_data["magnetic_heading"], known_heading) / 30.0
        matched += 1

    known_ias = known_state.get("ias")
    if known_ias not in [None, "----"] and decoded_data.get("indicated_airspeed") is not None:
        score += abs(float(decoded_data["indicated_airspeed"]) - float(known_ias)) / 50.0
        matched += 1

    known_mach = known_state.get("mach")
    if known_mach not in [None, "----"] and decoded_data.get("mach") is not None:
        score += abs(float(decoded_data["mach"]) - float(known_mach)) / 0.1
        matched += 1

    return score if matched > 0 else float("inf")

def infer_comm_b_type(message_hex, known_state=None):
    try:
        df_int = int(message_hex[:2], 16) >> 3
        if df_int not in {20, 21}:
            return "UNKNOWN", {}
        mb_int = int(message_hex[8:22], 16)
    except Exception:
        return "UNKNOWN", {}

    if is_bds17_payload(mb_int):
        return "BDS17", decode_bds17_payload(mb_int)

    if is_bds30_payload(mb_int):
        return "BDS30", decode_bds30_payload(mb_int)

    if is_bds40_payload(mb_int):
        return "BDS40", decode_bds40_payload(mb_int)

    if is_bds44_payload(mb_int):
        return "BDS44", decode_bds44_payload(mb_int)

    if is_bds45_payload(mb_int):
        return "BDS45", decode_bds45_payload(mb_int)

    bds50_ok = is_bds50_payload(mb_int)
    bds60_ok = is_bds60_payload(mb_int)

    if bds50_ok and not bds60_ok:
        return "BDS50", decode_bds50_payload(mb_int)
    if bds60_ok and not bds50_ok:
        return "BDS60", decode_bds60_payload(mb_int)
    if not bds50_ok and not bds60_ok:
        return "UNKNOWN", {}

    decoded_50 = decode_bds50_payload(mb_int)
    decoded_60 = decode_bds60_payload(mb_int)
    known_state = known_state or {}
    score_50 = score_bds50(decoded_50, known_state)
    score_60 = score_bds60(decoded_60, known_state)

    if score_50 < score_60:
        return "BDS50", decoded_50
    if score_60 < score_50:
        return "BDS60", decoded_60

    if score_50 == float("inf") and score_60 == float("inf"):
        return "UNKNOWN", {}

    return "BDS50", decoded_50

try:
    from pyModeS import PipeDecoder
except ImportError:
    try:
        from pyModeS.decoder import PipeDecoder
    except ImportError:
        class PipeDecoder:
            def __init__(self): pass
            def decode(self, payload, timestamp=None):
                icao = extract_icao_address(payload)
                return {"icao": icao} if icao else {}

# --- Configuration ---
RUNTIME_CONFIG = load_runtime_config()
PORT = RUNTIME_CONFIG["port"]
BAUD = RUNTIME_CONFIG["baud"]
WS_HOST = RUNTIME_CONFIG["ws_host"]
WS_PORT = RUNTIME_CONFIG["ws_port"]
HTTP_PORT = RUNTIME_CONFIG["http_port"]
RECEIVER_ID = RUNTIME_CONFIG["receiver_id"]

# ==========================================
# --- DARTS HTTP API SERVER (field registry + grid config) ---
# Runs on HTTP_PORT (default 8766) alongside the WebSocket server.
# Provides CORS-enabled endpoints for the frontend column manager.
# ==========================================
class DARTSAPIHandler(http.server.BaseHTTPRequestHandler):
    """Lightweight HTTP handler serving field registry and grid config endpoints."""

    def log_message(self, msg_format, *args):
        # Log 4xx/5xx only; suppress noisy 200/OPTIONS to keep console clean.
        # Build message safely without passing untrusted args through format string.
        code = str(args[1]) if len(args) > 1 else ""
        if code.startswith(("4", "5")):
            safe_msg = " ".join(str(a) for a in args)
            print(f"{ANSI.DIM}[{get_iso_time()}]{ANSI.RESET} {ANSI.YELLOW}[HTTP API] {safe_msg}{ANSI.RESET}")

    def _send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/fields":
            # Return the complete field registry so frontends can build column pickers
            self._send_json(FIELD_REGISTRY)
        elif self.path == "/api/grid-config":
            # Returns the default config structure; user preferences are stored client-side
            default_cols = [f["key"] for f in FIELD_REGISTRY if f["defaultVisible"]]
            self._send_json({"columns": default_cols, "sortKey": None, "sortDir": "asc"})
        else:
            self._send_json({"error": "Not found"}, status=404)

def run_http_server():
    """Run the DARTS HTTP API server bound to localhost only (security: no LAN exposure)."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), DARTSAPIHandler)
    server.serve_forever()

# --- Reference Coordinates for Local CPR Decoding (Sydney, NSW) ---
RECEIVER_LAT = -33.8688
RECEIVER_LON = 151.2093

# --- Bare-Metal ICAO 6-Bit Alphabet ---
ICAO_ALPHABET = "#ABCDEFGHIJKLMNOPQRSTUVWXYZ#####_###############0123456789######"

def decode_baudot_string(mb_bin):
    try:
        callsign = ""
        for i in range(8, 56, 6):
            char_binary = mb_bin[i:i+6]
            char_index = int(char_binary, 2)
            callsign += ICAO_ALPHABET[char_index]
        return callsign.replace("_", " ").replace("#", "").strip()
    except Exception:
        return None

def get_iso_time():
    return datetime.datetime.now().isoformat(timespec='milliseconds')

def get_ui_time():
    return datetime.datetime.now().strftime('%H:%M:%S')

# ==========================================
# --- BARE-METAL CPR MATH ENGINE (NO DEPS) ---
# ==========================================
def cpr_nl(lat):
    if abs(lat) >= 87.0: return 1
    try:
        val = 1.0 - (1.0 - math.cos(math.pi / 30.0)) / (math.cos(math.radians(lat)) ** 2)
        if val < 0: val = 0
        return max(1, math.floor(2 * math.pi / math.acos(val)))
    except Exception: return 1

def bare_metal_cpr_local(mb_bin, is_odd, lat_ref, lon_ref):
    try:
        cpr_lat = int(mb_bin[22:39], 2)
        cpr_lon = int(mb_bin[39:56], 2)
        
        dLat = 360.0 / 59.0 if is_odd else 360.0 / 60.0
        
        j = math.floor(lat_ref / dLat) + math.floor(0.5 + ((lat_ref % dLat) / dLat) - (cpr_lat / 131072.0))
        lat = dLat * (j + (cpr_lat / 131072.0))
        
        if lat > 90 or lat < -90: return None
        
        nl = cpr_nl(lat)
        ni = max(1, nl - 1) if is_odd else max(1, nl)
        dLon = 360.0 / ni
        
        m = math.floor(lon_ref / dLon) + math.floor(0.5 + ((lon_ref % dLon) / dLon) - (cpr_lon / 131072.0))
        lon = dLon * (m + (cpr_lon / 131072.0))
        
        return round(lat, 4), round(lon, 4)
    except Exception:
        return None

# ==========================================
# --- MASSIVE TACTICAL AIRLINE REGISTRY  ---
# ==========================================
TACTICAL_AIRLINE_DB = {}

def load_airline_db():
    global TACTICAL_AIRLINE_DB
    iso_time = get_iso_time()
    try:
        if os.path.exists("airline_lookup.json"):
            with open("airline_lookup.json", "r") as f:
                TACTICAL_AIRLINE_DB = json.load(f)
            print(f"{ANSI.DIM}[{iso_time}]{ANSI.RESET} {ANSI.GREEN}Airline Registry Loaded: {len(TACTICAL_AIRLINE_DB)} signatures locked in RAM.{ANSI.RESET}")
        else:
            print(f"{ANSI.DIM}[{iso_time}]{ANSI.RESET} {ANSI.YELLOW}WARNING: 'airline_lookup.json' not found. Proceeding with blank registry.{ANSI.RESET}")
    except Exception as e:
        print(f"{ANSI.DIM}[{iso_time}]{ANSI.RESET} {ANSI.RED}Error loading 'airline_lookup.json': {e}{ANSI.RESET}")

def resolve_airline(callsign):
    if not callsign or callsign == "----": return "----"
    match = re.match(r'^([A-Z]+)', callsign)
    if match:
        prefix = match.group(1)
        if prefix in TACTICAL_AIRLINE_DB:
            return TACTICAL_AIRLINE_DB[prefix]
    if callsign.startswith("VH"): return "CIVIL (AUS)"
    if re.match(r'^N\d', callsign): return "CIVIL (USA)"
    if callsign.startswith("ZK"): return "CIVIL (NZ)"
    if re.match(r'^G[A-Z]', callsign): return "CIVIL (UK)"
    if re.match(r'^C[A-Z]', callsign): return "CIVIL (CAN)"
    return "----"

# ==========================================
# --- GEOJSON AIRSPACE MATRIX            ---
# ==========================================
AIRSPACE_GEOJSON = {
    "type": "FeatureCollection",
    "features": []
}

def load_airspace():
    global AIRSPACE_GEOJSON
    iso_time = get_iso_time()
    try:
        if os.path.exists("airspace.geojson"):
            with open("airspace.geojson", "r") as f:
                AIRSPACE_GEOJSON = json.load(f)
            features_count = len(AIRSPACE_GEOJSON.get("features", []))
            print(f"{ANSI.DIM}[{iso_time}]{ANSI.RESET} {ANSI.GREEN}GeoJSON Airspace Loaded: {features_count} geometry features locked in RAM.{ANSI.RESET}")
        else:
            print(f"{ANSI.DIM}[{iso_time}]{ANSI.RESET} {ANSI.YELLOW}WARNING: 'airspace.geojson' not found. Initializing blank FeatureCollection.{ANSI.RESET}")
            save_airspace()
    except Exception as e:
        print(f"{ANSI.DIM}[{iso_time}]{ANSI.RESET} {ANSI.RED}Error loading 'airspace.geojson': {e}{ANSI.RESET}")

def save_airspace():
    try:
        with open("airspace.geojson", "w") as f:
            json.dump(AIRSPACE_GEOJSON, f, indent=4)
    except Exception as e:
        print(f"{ANSI.DIM}[{get_iso_time()}]{ANSI.RESET} {ANSI.RED}Error saving 'airspace.geojson': {e}{ANSI.RESET}")

# ==========================================
# --- Active Tracking SIGINT System ---
# ==========================================
class SIGINT_Triangulator:
    def __init__(self):
        self.paint_buffer = [] 
        self.lock = threading.Lock()
        self.active_radars = {} 
        self.solving_sweeps = set()
        
        for f in AIRSPACE_GEOJSON.get("features", []):
            if f.get("properties", {}).get("icon") in ("RADAR", "RADAR_POINT"):
                sweep = f.get("properties", {}).get("sweep")
                if sweep:
                    sweep_key = round(sweep, 1)
                    self.active_radars[sweep_key] = {
                        "lat": f["geometry"]["coordinates"][1],
                        "lon": f["geometry"]["coordinates"][0],
                        "health": 100
                    }

    def log_paint(self, icao, lat, lon, time_hit, sweep_interval):
        if not (3.5 < sweep_interval < 15.0): return
        sweep_rounded = round(sweep_interval, 1)
        
        with self.lock:
            self.paint_buffer.append({"icao": icao, "lat": lat, "lon": lon, "time": time_hit, "raw_sweep": sweep_interval})
            if len(self.paint_buffer) > 1000: self.paint_buffer.pop(0)
            
            # Prevent thread explosion if solver is already running for this sweep
            if sweep_rounded in self.solving_sweeps: return 

            cluster = [p for p in self.paint_buffer if abs(p["raw_sweep"] - sweep_interval) <= 0.15]
            
            # Restored 12 point gate to reject immediate noise.
            if len(cluster) >= 12:
                self.solving_sweeps.add(sweep_rounded)
                print(f"{ANSI.DIM}[{get_iso_time()}]{ANSI.RESET} {ANSI.CYAN}[SIGINT MATH] Firing active tracker for {sweep_rounded}s sweep. ({len(cluster)} hits){ANSI.RESET}")
                threading.Thread(target=self.solve_radar_origin, args=(cluster, sweep_rounded), daemon=True).start()
                
                # Strip used points to prevent immediate re-triggering
                self.paint_buffer = [p for p in self.paint_buffer if p not in cluster]

    def solve_radar_origin(self, points, sweep_interval):
        avg_lat = sum(p["lat"] for p in points) / len(points)
        avg_lon = sum(p["lon"] for p in points) / len(points)
        
        # If tracking an active radar, center the coarse search on the known coordinates.
        with self.lock:
            if sweep_interval in self.active_radars:
                avg_lat = self.active_radars[sweep_interval]["lat"]
                avg_lon = self.active_radars[sweep_interval]["lon"]
        
        best_point = (avg_lat, avg_lon)
        min_variance = float('inf')
        
        step = 0.1
        for dLat in [x * step for x in range(-10, 11)]:
            for dLon in [x * step for x in range(-10, 11)]:
                test_lat = avg_lat + dLat
                test_lon = avg_lon + dLon
                var = self.calculate_variance(test_lat, test_lon, points, sweep_interval)
                if var < min_variance:
                    min_variance = var
                    best_point = (test_lat, test_lon)
                    
        fine_step = 0.01
        fine_min_var = min_variance
        fine_best = best_point
        for dLat in [x * fine_step for x in range(-10, 11)]:
            for dLon in [x * fine_step for x in range(-10, 11)]:
                test_lat = best_point[0] + dLat
                test_lon = best_point[1] + dLon
                var = self.calculate_variance(test_lat, test_lon, points, sweep_interval)
                if var < fine_min_var:
                    fine_min_var = var
                    fine_best = (test_lat, test_lon)

        print(f"{ANSI.DIM}[{get_iso_time()}]{ANSI.RESET} {ANSI.YELLOW}[SIGINT DEBUG] {sweep_interval}s Solver Complete. Variance: {round(fine_min_var, 2)}{ANSI.RESET}")

        with self.lock:
            if fine_min_var < 500:
                if sweep_interval in self.active_radars:
                    # Center of Mass refinement.
                    old_lat = self.active_radars[sweep_interval]["lat"]
                    old_lon = self.active_radars[sweep_interval]["lon"]
                    new_lat = (old_lat * 0.7) + (fine_best[0] * 0.3)
                    new_lon = (old_lon * 0.7) + (fine_best[1] * 0.3)
                    
                    self.active_radars[sweep_interval]["lat"] = new_lat
                    self.active_radars[sweep_interval]["lon"] = new_lon
                    self.active_radars[sweep_interval]["health"] = 100
                    
                    print(f"{ANSI.DIM}[{get_iso_time()}]{ANSI.RESET} {ANSI.MAGENTA}[SIGINT TRACK] {sweep_interval}s Emitter Refined. Pulling coordinates to truer center.{ANSI.RESET}")
                    self.update_geojson(sweep_interval, new_lat, new_lon)
                else:
                    # New Lock
                    self.active_radars[sweep_interval] = {"lat": fine_best[0], "lon": fine_best[1], "health": 100}
                    print(f"{ANSI.DIM}[{get_iso_time()}]{ANSI.RESET} {ANSI.MAGENTA}[SIGINT LOCK] New Emitter Verified [{sweep_interval}s]. Lat: {round(fine_best[0],4)}, Lon: {round(fine_best[1],4)}{ANSI.RESET}")
                    self.add_geojson(sweep_interval, fine_best[0], fine_best[1])
            else:
                # Confidence decay (ghost purge).
                if sweep_interval in self.active_radars:
                    self.active_radars[sweep_interval]["health"] -= 25
                    health = self.active_radars[sweep_interval]["health"]
                    print(f"{ANSI.DIM}[{get_iso_time()}]{ANSI.RESET} {ANSI.YELLOW}[SIGINT WARN] {sweep_interval}s Variance High. Emitter Health dropping: {health}%{ANSI.RESET}")
                    
                    if health <= 0:
                        print(f"{ANSI.DIM}[{get_iso_time()}]{ANSI.RESET} {ANSI.RED}[SIGINT PURGE] Ghost Emitter {sweep_interval}s completely eradicated from active matrix.{ANSI.RESET}")
                        del self.active_radars[sweep_interval]
                        self.remove_geojson(sweep_interval)

            self.solving_sweeps.discard(sweep_interval)

    def calculate_variance(self, r_lat, r_lon, points, sweep_interval):
        errors = []
        for p in points:
            brg = math.degrees(math.atan2(p["lon"] - r_lon, p["lat"] - r_lat)) % 360
            expected_brg = ((p["time"] % sweep_interval) / sweep_interval) * 360
            diff = (brg - expected_brg) % 360
            if diff > 180: diff = 360 - diff
            errors.append(diff)
        mean_err = sum(errors) / len(errors)
        return sum((e - mean_err) ** 2 for e in errors) / len(errors)

    def add_geojson(self, sweep, lat, lon):
        feature = {
            "type": "Feature",
            "geometry": { "type": "Point", "coordinates": [round(lon,4), round(lat,4)] },
            "properties": { "name": f"SSR {sweep}s", "icon": "RADAR_POINT", "sweep": sweep, "color": "rgba(16, 185, 129, 0.9)" }
        }
        AIRSPACE_GEOJSON["features"].append(feature)
        save_airspace()

    def update_geojson(self, sweep, lat, lon):
        for f in AIRSPACE_GEOJSON["features"]:
            if f.get("properties", {}).get("sweep") == sweep:
                f["geometry"]["coordinates"] = [round(lon,4), round(lat,4)]
                f["properties"]["icon"] = "RADAR_POINT"
                break
        save_airspace()

    def remove_geojson(self, sweep):
        AIRSPACE_GEOJSON["features"] = [
            f for f in AIRSPACE_GEOJSON["features"] 
            if f.get("properties", {}).get("sweep") != sweep
        ]
        save_airspace()

sigint = SIGINT_Triangulator()

# --- State Engines & Queues ---
aircraft_state = {}
historical_state = {} 
comm_d_buffer = {}  
fms_intent_cache = {} 
state_lock = threading.Lock()
pipeline = PipeDecoder()
log_queue = queue.Queue()

# --- DB Engine & Live Metrics ---
db_conn = sqlite3.connect("DATABASE.db", check_same_thread=False)
db_cursor = db_conn.cursor()
db_lock = threading.Lock()
ledger_count = 0 

with db_lock:
    db_cursor.execute('''CREATE TABLE IF NOT EXISTS aircraft_registry
                         (icao TEXT PRIMARY KEY, latest_callsign TEXT, airline TEXT, last_lat TEXT, last_lon TEXT, total_spots INTEGER)''')
    
    db_cursor.execute('''CREATE TABLE IF NOT EXISTS flight_ledger
                         (timestamp TEXT, event TEXT, icao TEXT, callsign TEXT, airline_or_data TEXT, lat TEXT, lon TEXT)''')
    
    try:
        db_cursor.execute("ALTER TABLE aircraft_registry ADD COLUMN last_lat TEXT DEFAULT '----'")
        db_cursor.execute("ALTER TABLE aircraft_registry ADD COLUMN last_lon TEXT DEFAULT '----'")
    except sqlite3.OperationalError: pass 
    
    try:
        db_cursor.execute("ALTER TABLE flight_ledger ADD COLUMN lat TEXT DEFAULT '----'")
        db_cursor.execute("ALTER TABLE flight_ledger ADD COLUMN lon TEXT DEFAULT '----'")
    except sqlite3.OperationalError: pass
    
    try:
        db_cursor.execute("SELECT COUNT(*) FROM flight_ledger")
        ledger_count = db_cursor.fetchone()[0]
    except Exception:
        pass
    db_conn.commit()


def load_historical_state():
    global historical_state
    iso_time = get_iso_time()
    try:
        with db_lock:
            db_cursor.execute("SELECT icao, total_spots, latest_callsign, airline, last_lat, last_lon FROM aircraft_registry")
            rows = db_cursor.fetchall()
            for row in rows:
                historical_state[row[0]] = {
                    "total_spots": row[1], 
                    "latest_callsign": row[2], 
                    "airline": row[3],
                    "last_lat": row[4] if len(row) > 4 else "----",
                    "last_lon": row[5] if len(row) > 5 else "----"
                }
    except Exception as e:
        print(f"{ANSI.DIM}[{iso_time}]{ANSI.RESET} {ANSI.RED}Error loading historical registry: {e}{ANSI.RESET}")


def archivist_loop():
    global ledger_count
    while True:
        time.sleep(5)
        ledger_batch, reg_updates, reg_inserts = [], [], []
        
        while not log_queue.empty():
            try:
                item = log_queue.get_nowait()
                if item[0] == "LEDGER": 
                    if len(item) == 8:
                        ledger_batch.append(item[1:]) 
                    else:
                        ledger_batch.append((item[1], item[2], item[3], item[4], item[5], "----", "----"))
                elif item[0] == "REGISTRY_UPDATE": 
                    reg_updates.append((item[2], item[3], item[4], item[5], item[6], item[1])) 
                elif item[0] == "REGISTRY_INSERT": 
                    reg_inserts.append((item[1], item[2], item[3], item[4], item[5], item[6])) 
            except queue.Empty: break
                
        if ledger_batch or reg_updates or reg_inserts:
            try:
                with db_lock:
                    if ledger_batch: 
                        db_cursor.executemany("INSERT INTO flight_ledger (timestamp, event, icao, callsign, airline_or_data, lat, lon) VALUES (?, ?, ?, ?, ?, ?, ?)", ledger_batch)
                        ledger_count += len(ledger_batch)
                    if reg_inserts: db_cursor.executemany("INSERT INTO aircraft_registry (icao, latest_callsign, airline, last_lat, last_lon, total_spots) VALUES (?, ?, ?, ?, ?, ?)", reg_inserts)
                    if reg_updates: db_cursor.executemany("UPDATE aircraft_registry SET latest_callsign=?, airline=?, last_lat=?, last_lon=?, total_spots=? WHERE icao=?", reg_updates)
                    db_conn.commit()
            except Exception: pass


def handle_entry_gate(icao):
    now = time.time()
    if icao in aircraft_state and (now - aircraft_state[icao].get("last_seen", 0) < 60): return

    plain_log = ""
    iso_time = get_iso_time()
    ui_time = get_ui_time()
    
    if icao in historical_state:
        historical_state[icao]["total_spots"] += 1
        count = historical_state[icao]["total_spots"]
        cached_callsign = historical_state[icao]["latest_callsign"]
        cached_airline = historical_state[icao]["airline"]
        cached_lat = historical_state[icao].get("last_lat", "----")
        cached_lon = historical_state[icao].get("last_lon", "----")
        
        pos_str = f"[LAST POS: {cached_lat}, {cached_lon}]" if cached_lat != "----" else "[POS: ----]"
        
        event_pad = "[SIGHT]".ljust(13)
        count_pad = f"#{count}".ljust(6)
        cs_pad = cached_callsign.ljust(8)
        
        plain_log = f"{event_pad} {count_pad} {icao}  {cs_pad}  {cached_airline} {pos_str}"
        console_log = f"{ANSI.DIM}[{iso_time}]{ANSI.RESET} {ANSI.CYAN}{event_pad}{ANSI.RESET} {ANSI.DIM}{count_pad}{ANSI.RESET} {ANSI.YELLOW}{icao}{ANSI.RESET}  {ANSI.CYAN}{cs_pad}{ANSI.RESET}  {ANSI.CYAN}{cached_airline}{ANSI.RESET} {ANSI.DIM}{pos_str}{ANSI.RESET}"
        print(console_log)
        
        log_queue.put(("LEDGER", iso_time, "SIGHT", icao, cached_callsign, cached_airline, cached_lat, cached_lon))
        log_queue.put(("REGISTRY_UPDATE", icao, cached_callsign, cached_airline, cached_lat, cached_lon, count))
    else:
        historical_state[icao] = {"total_spots": 1, "latest_callsign": "----", "airline": "----", "last_lat": "----", "last_lon": "----"}
        event_pad = "[AQUISITION]".ljust(13)
        count_pad = "#1".ljust(6)
        cs_pad = "----".ljust(8)
        pos_str = "[POS: ----]"
        
        plain_log = f"{event_pad} {count_pad} {icao}  {cs_pad}  ---- {pos_str}"
        console_log = f"{ANSI.DIM}[{iso_time}]{ANSI.RESET} {ANSI.GREEN}{event_pad}{ANSI.RESET} {ANSI.DIM}{count_pad}{ANSI.RESET} {ANSI.YELLOW}{icao}{ANSI.RESET}  {ANSI.CYAN}{cs_pad}{ANSI.RESET}  {ANSI.DIM}---- {pos_str}{ANSI.RESET}"
        print(console_log)
        
        log_queue.put(("LEDGER", iso_time, "AQUISITION", icao, "----", "----", "----", "----"))
        log_queue.put(("REGISTRY_INSERT", icao, "----", "----", "----", "----", 1))
            
    formatted_log = f"> <span class=\"ts-badge\">[{ui_time}]</span> <span style=\"color:#39ff14;\">{plain_log}</span>"
    update_aircraft(icao, "latest_sys_log", {"hash": f"gate_{icao}_{now}", "text": formatted_log})


def run_reaper_loop():
    while True:
        time.sleep(5)
        now = time.time()
        to_log_comm_d = []
        
        with state_lock:
            to_delete = []
            for icao, data in aircraft_state.items():
                if now - data["last_seen"] > 60:
                    if not data.get("farewell_sent"):
                        ui_time = get_ui_time()
                        iso_time = get_iso_time() 
                        
                        true_exit_iso = datetime.datetime.fromtimestamp(data["last_seen"]).isoformat(timespec='milliseconds')
                        
                        event_pad = "[FAREWELL]".ljust(13)
                        count_pad = "      " 
                        cs_val = data.get('callsign', '----')
                        al_val = data.get('airline', '----')
                        lat_val = data.get('lat', '----')
                        lon_val = data.get('lon', '----')
                        cs_pad = cs_val.ljust(8)
                        
                        pos_str = f"[EXIT POS: {lat_val}, {lon_val}]" if lat_val != "----" else "[EXIT POS: ----]"
                        
                        plain_log = f"{event_pad} {count_pad} {icao}  {cs_pad}  {al_val} {pos_str}"
                        console_log = f"{ANSI.DIM}[{iso_time}]{ANSI.RESET} {ANSI.RED}{event_pad}{ANSI.RESET} {ANSI.DIM}{count_pad}{ANSI.RESET} {ANSI.YELLOW}{icao}{ANSI.RESET}  {ANSI.CYAN}{cs_pad}{ANSI.RESET}  {ANSI.CYAN}{al_val}{ANSI.RESET} {ANSI.DIM}{pos_str}{ANSI.RESET}"
                        print(console_log)
                        
                        log_queue.put(("LEDGER", true_exit_iso, "FAREWELL", icao, cs_val, al_val, lat_val, lon_val))
                        
                        formatted_log = f"> <span class=\"ts-badge\">[{ui_time}]</span> <span style=\"color:#f87171;\">{plain_log}</span>"
                        data["latest_sys_log"] = {"hash": f"sys_exit_{icao}_{now}", "text": formatted_log}
                        data["farewell_sent"] = True
                        data["last_seen"] = now - 56 
                    else:
                        to_delete.append(icao)
            
            for icao in to_delete:
                final_callsign = aircraft_state[icao].get("callsign", "----")
                final_airline = aircraft_state[icao].get("airline", "----")
                final_lat = aircraft_state[icao].get("lat", "----")
                final_lon = aircraft_state[icao].get("lon", "----")
                
                if icao in historical_state:
                    if final_callsign != "----":
                        historical_state[icao]["latest_callsign"] = final_callsign
                        historical_state[icao]["airline"] = final_airline
                    if final_lat != "----":
                        historical_state[icao]["last_lat"] = final_lat
                        historical_state[icao]["last_lon"] = final_lon
                        
                    log_queue.put(("REGISTRY_UPDATE", icao, 
                                   historical_state[icao]["latest_callsign"], 
                                   historical_state[icao]["airline"], 
                                   historical_state[icao]["last_lat"], 
                                   historical_state[icao]["last_lon"], 
                                   historical_state[icao]["total_spots"]))
                                   
                del aircraft_state[icao]
                if icao in fms_intent_cache: del fms_intent_cache[icao]
                
            for d_icao, d_data in list(comm_d_buffer.items()):
                if now - d_data["timestamp"] > 2.0:
                    to_log_comm_d.append((d_icao, d_data["segments"]))
                    del comm_d_buffer[d_icao]

        for d_icao, segments in to_log_comm_d:
            sorted_seqs = sorted(segments.keys())
            stitched = "".join([segments[seq] for seq in sorted_seqs])
            try:
                with open("comm_d_intercepts.log", "a") as logfile:
                    logfile.write(f"[{get_iso_time()}] ICAO: {d_icao} | Segments: {len(sorted_seqs)} | Raw: {stitched}\n")
            except Exception: pass

def calculate_wind(gs, track, tas, heading):
    try:
        rad_track = math.radians(float(track))
        rad_heading = math.radians(float(heading))
        gx = float(gs) * math.sin(rad_track)
        gy = float(gs) * math.cos(rad_track)
        ax = float(tas) * math.sin(rad_heading)
        ay = float(tas) * math.cos(rad_heading)
        wx = gx - ax
        wy = gy - ay
        wind_speed = math.sqrt(wx**2 + wy**2)
        wind_dir = (math.degrees(math.atan2(-wx, -wy))) % 360
        return f"{int(wind_speed)}kt@{int(wind_dir)}°"
    except Exception:
        return "----"

def refresh_motion_derivatives(icao):
    with state_lock:
        snapshot = aircraft_state.get(icao, {}).copy()

    required = [snapshot.get("speed"), snapshot.get("track"), snapshot.get("tas"), snapshot.get("heading")]
    if all(value not in [None, "----"] for value in required):
        update_aircraft(icao, "wind", calculate_wind(snapshot["speed"], snapshot["track"], snapshot["tas"], snapshot["heading"]))

def update_aircraft(icao, key, value):
    with state_lock:
        now = time.time()
        
        if icao not in aircraft_state:
            aircraft_state[icao] = {
                "icao": icao, "callsign": "----", "airline": "----", "alt": "----", "speed": "----", 
                "tas": "----", "ias": "----", "mach": "----", "vert_rate": "----",
                "heading": "----", "track": "----", "track_rate": "----", "roll": "----",
                "target_alt": "----", "baro": "----", "squawk": "----", "tcas_ra": "CLEAN",
                "ident_time": 0, "wind": "----", "sat": "----", "discretes": "HAND", "hazard": "----",       
                "gnss_qual": "----", "radar_sweep": "----", "raw_sweep_interval": 1.5,
                "capability_summary": "----", "supported_bds": [], "last_bds_hit": "----",
                "lat": "----", "lon": "----",
                "latest_intent": {}, "latest_db_log": {}, "latest_sys_log": {}, "last_msg_time": 0, 
                "current_burst_start": 0, "last_seen": now, "first_seen_time": now
            }
        
        curr_lat = aircraft_state[icao].get("lat", "----")
        curr_lon = aircraft_state[icao].get("lon", "----")

        if key == "lat":
            old_lat = aircraft_state[icao].get("lat")
            if old_lat == "----" and value != "----":
                ui_time = get_ui_time()
                iso_time = get_iso_time()
                event_label = "[POS LOCK]".ljust(13)
                cs_log = aircraft_state[icao].get("callsign", "----")
                log_text = f"> <span class=\"ts-badge\">[{ui_time}]</span> POS LOCK: <span class=\"icao-badge\">{icao}</span> acquired spatial coordinates."
                console_log = f"{ANSI.DIM}[{iso_time}]{ANSI.RESET} {ANSI.MAGENTA}{event_label}{ANSI.RESET} {' '*6} {ANSI.YELLOW}{icao}{ANSI.RESET}  {ANSI.CYAN}{cs_log.ljust(8)}{ANSI.RESET}  {ANSI.MAGENTA}Coordinates Acquired{ANSI.RESET}"
                print(console_log)
                log_queue.put(("LEDGER", iso_time, "POS LOCK", icao, cs_log, "Lat Lock", value, curr_lon))
                aircraft_state[icao]["latest_sys_log"] = {"hash": f"cpr_{icao}_{now}", "text": log_text}

        if key == "callsign" and value != "----":
            aircraft_state[icao]["airline"] = resolve_airline(value)

        aircraft_state[icao][key] = value
        aircraft_state[icao]["last_seen"] = now
        
        p = aircraft_state[icao]
        if key == "last_seen":
            if p["last_msg_time"] > 0:
                gap = now - p["last_msg_time"]
                if gap > 1.5:
                    if p["current_burst_start"] > 0:
                        sweep_interval = now - p["current_burst_start"]
                        if 3.0 <= sweep_interval <= 15.0:
                            estimated_rpm = 60.0 / sweep_interval
                            p["radar_sweep"] = f"{round(sweep_interval, 1)}s ({round(estimated_rpm, 1)} RPM)"
                            p["raw_sweep_interval"] = sweep_interval
                            
                            # SIGINT injection.
                            if p.get("lat") != "----" and p.get("lon") != "----":
                                sigint.log_paint(icao, float(p["lat"]), float(p["lon"]), now, sweep_interval)
                                
                    p["current_burst_start"] = now
            else:
                p["current_burst_start"] = now
            p["last_msg_time"] = now


def process_frame(frame):
    if len(frame) < 8: return 
    frame_type = frame[0]
    payload = binascii.hexlify(frame[8:]).decode('ascii').upper()
    
    if frame_type == 0x33:
        try:
            decoded = pipeline.decode(payload, timestamp=time.time())
            if decoded and "icao" in decoded:
                icao = decoded["icao"].upper()
                handle_entry_gate(icao)
                update_aircraft(icao, "last_seen", time.time())

                with state_lock:
                    known_state = aircraft_state.get(icao, {}).copy()
                
                callsign = decoded.get("callsign") or decoded.get("cs")
                if callsign is not None: update_aircraft(icao, "callsign", str(callsign).strip())
                alt = decoded.get("altitude") or decoded.get("alt")
                if alt is not None: update_aircraft(icao, "alt", alt)
                if decoded.get("squawk") is not None: update_aircraft(icao, "squawk", decoded["squawk"])
                speed = decoded.get("groundspeed") or decoded.get("gs")
                if speed is not None: update_aircraft(icao, "speed", speed)
                tas = decoded.get("true_airspeed") or decoded.get("tas")
                if tas is not None: update_aircraft(icao, "tas", tas)
                track = decoded.get("track") or decoded.get("true_track") or decoded.get("trk")
                if track is not None: update_aircraft(icao, "track", round(float(track), 2))
                heading = decoded.get("magnetic_heading") or decoded.get("heading") or decoded.get("hdg")
                if heading is not None: update_aircraft(icao, "heading", round(float(heading), 2))
                if decoded.get("roll") is not None: update_aircraft(icao, "roll", round(float(decoded["roll"]), 2))
                
                if decoded.get("selected_altitude_mcp") is not None: 
                    update_aircraft(icao, "target_alt", f"MCP:{decoded.get('selected_altitude_mcp')}ft")
                
                baro = decoded.get("baro_pressure_setting") or decoded.get("baro") or decoded.get("qnh")
                if baro is not None: update_aircraft(icao, "baro", f"{baro} hPa")
                if decoded.get("tcas_ra") is not None: update_aircraft(icao, "tcas_ra", "RA ALERT" if decoded["tcas_ra"] else "CLEAN")

                try: df_int = int(payload[:2], 16) >> 3
                except Exception: df_int = 0

                mb_hex = payload[8:22]
                try: mb_bin = bin(int(mb_hex, 16))[2:].zfill(56)
                except Exception: mb_bin = "0" * 56
                
                tc = 0
                if df_int == 17 or df_int == 18:
                    try: tc = int(mb_bin[0:5], 2)
                    except Exception: pass

                try:
                    if 1 <= tc <= 4:
                        tactical_cs = decode_baudot_string(mb_bin)
                        if tactical_cs: update_aircraft(icao, "callsign", tactical_cs)
                        
                    elif 9 <= tc <= 18:
                        try:
                            is_odd = mb_bin[21] == "1"
                            pos = bare_metal_cpr_local(mb_bin, is_odd, RECEIVER_LAT, RECEIVER_LON)
                            if pos:
                                update_aircraft(icao, "lat", pos[0])
                                update_aircraft(icao, "lon", pos[1])
                        except Exception: pass

                    elif tc == 29:
                        try:
                            tc29_data = decode_bds62_payload(int(mb_hex, 16))

                            if tc29_data.get("selected_altitude") is not None:
                                source = tc29_data.get("selected_altitude_source", "N/A")
                                update_aircraft(icao, "target_alt", f"{source}:{int(tc29_data['selected_altitude'])}ft")
                            if tc29_data.get("baro_pressure_setting") is not None:
                                update_aircraft(icao, "baro", f"{round(float(tc29_data['baro_pressure_setting']), 1)} hPa")

                            mode_summary = summarise_target_state_modes(tc29_data)
                            if mode_summary != "----":
                                update_aircraft(icao, "discretes", mode_summary)

                            quality_summary = summarise_target_state_quality(tc29_data)
                            if quality_summary != "----":
                                update_aircraft(icao, "gnss_qual", quality_summary)

                            target_hash, target_log = build_target_state_log(icao, tc29_data)
                            if target_hash and target_log:
                                update_aircraft(icao, "latest_sys_log", {"hash": target_hash, "text": target_log})
                        except Exception:
                            pass
                        
                except Exception: pass

                bds_type, bds_data = infer_comm_b_type(payload, known_state)

                if bds_type != "UNKNOWN":
                    update_aircraft(icao, "last_bds_hit", bds_type)

                if bds_type == "BDS17":
                    try:
                        with state_lock:
                            previous_caps = list(aircraft_state.get(icao, {}).get("supported_bds", []))

                        supported_bds = bds_data.get("supported_bds", [])
                        capability_summary = summarise_capabilities(supported_bds)
                        update_aircraft(icao, "supported_bds", supported_bds)
                        update_aircraft(icao, "capability_summary", capability_summary)

                        if previous_caps != supported_bds:
                            ui_time = get_ui_time()
                            caps_text = ", ".join(supported_bds) if supported_bds else "none"
                            formatted_log = (
                                f"> <span class=\"ts-badge\">[{ui_time}]</span> "
                                f"GICB CAPS: <span class=\"icao-badge\">{icao}</span> supports "
                                f"<span class=\"bds-badge\">{caps_text}</span>"
                            )
                            update_aircraft(icao, "latest_sys_log", {"hash": f"cap_{icao}_{mb_hex}", "text": formatted_log})
                    except Exception:
                        pass

                elif bds_type == "BDS40":
                    try:
                        target_str = []
                        if bds_data.get("selected_altitude_mcp") is not None:
                            target_str.append(f"MCP:{int(bds_data['selected_altitude_mcp'])}")
                        if bds_data.get("selected_altitude_fms") is not None:
                            target_str.append(f"FMS:{int(bds_data['selected_altitude_fms'])}")
                        if target_str: update_aircraft(icao, "target_alt", " ".join(target_str))
                        if bds_data.get("baro_pressure_setting") is not None:
                            update_aircraft(icao, "baro", f"{round(float(bds_data['baro_pressure_setting']), 1)} hPa")
                    except Exception: pass

                elif bds_type == "BDS50":
                    try:
                        if bds_data.get("roll") is not None:
                            update_aircraft(icao, "roll", round(float(bds_data["roll"]), 2))
                        if bds_data.get("true_track") is not None:
                            update_aircraft(icao, "track", round(float(bds_data["true_track"]), 2))
                        if bds_data.get("groundspeed") is not None:
                            update_aircraft(icao, "speed", int(bds_data["groundspeed"]))
                        if bds_data.get("track_rate") is not None:
                            update_aircraft(icao, "track_rate", round(float(bds_data["track_rate"]), 2))
                        if bds_data.get("true_airspeed") is not None:
                            update_aircraft(icao, "tas", int(bds_data["true_airspeed"]))
                        refresh_motion_derivatives(icao)
                    except Exception:
                        pass

                elif bds_type == "BDS60":
                    try:
                        if bds_data.get("magnetic_heading") is not None:
                            update_aircraft(icao, "heading", round(float(bds_data["magnetic_heading"]), 2))
                        if bds_data.get("indicated_airspeed") is not None:
                            update_aircraft(icao, "ias", int(bds_data["indicated_airspeed"]))
                        if bds_data.get("mach") is not None:
                            update_aircraft(icao, "mach", round(float(bds_data["mach"]), 3))

                        if bds_data.get("baro_vertical_rate") is not None:
                            update_aircraft(icao, "vert_rate", int(bds_data["baro_vertical_rate"]))
                        elif bds_data.get("inertial_vertical_rate") is not None:
                            update_aircraft(icao, "vert_rate", int(bds_data["inertial_vertical_rate"]))

                        refresh_motion_derivatives(icao)
                    except Exception:
                        pass

                elif bds_type == "BDS30":
                    try:
                        ra_summary = summarise_tcas_ra(bds_data)
                        update_aircraft(icao, "tcas_ra", ra_summary)

                        ra_hash, ra_log = build_tcas_ra_log(icao, bds_data)
                        if ra_hash and ra_log:
                            update_aircraft(icao, "latest_sys_log", {"hash": ra_hash, "text": ra_log})
                    except Exception:
                        pass

                elif bds_type == "BDS44":
                    try:
                        if bds_data.get("wind_speed") is not None and bds_data.get("wind_direction") is not None:
                            wind_str = f"{int(bds_data['wind_speed'])}kt@{int(round(float(bds_data['wind_direction']))) % 360}°"
                            update_aircraft(icao, "wind", wind_str)
                        if bds_data.get("static_air_temperature") is not None:
                            update_aircraft(icao, "sat", format_temperature(bds_data["static_air_temperature"]))
                        if bds_data.get("static_pressure") is not None:
                            update_aircraft(icao, "baro", f"{int(bds_data['static_pressure'])} hPa")

                        turb_label = turbulence_label(bds_data.get("turbulence")) if bds_data.get("turbulence") is not None else None
                        if turb_label and turb_label != "TURB NIL":
                            update_aircraft(icao, "hazard", turb_label)
                    except Exception:
                        pass

                elif bds_type == "BDS45":
                    try:
                        if bds_data.get("static_air_temperature") is not None:
                            update_aircraft(icao, "sat", format_temperature(bds_data["static_air_temperature"]))
                        if bds_data.get("static_pressure") is not None:
                            update_aircraft(icao, "baro", f"{int(bds_data['static_pressure'])} hPa")

                        hazard_summary = build_hazard_summary(bds_data)
                        if hazard_summary != "----":
                            update_aircraft(icao, "hazard", hazard_summary)
                    except Exception:
                        pass

                elif bds_type in ["BDS41", "BDS42"]:
                    try:
                        if icao not in fms_intent_cache: fms_intent_cache[icao] = {}
                        if fms_intent_cache[icao].get(bds_type) != mb_hex:
                            fms_intent_cache[icao][bds_type] = mb_hex 
                            update_aircraft(icao, "latest_intent", {"time": get_ui_time(), "icao": icao, "bds": bds_type, "hex": mb_hex})
                    except Exception: pass

        except Exception: pass

def serial_reader_thread():
    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.1)
        in_frame = False
        frame_data = bytearray()
        while True:
            if ser.in_waiting > 0:
                byte = ser.read(1)
                if not byte: continue 
                if byte == b'\x1A':
                    next_byte = ser.read(1)
                    if next_byte == b'\x1A':
                        if in_frame: frame_data.append(0x1A)
                    elif next_byte in [b'\x32', b'\x33', b'\xEC']:
                        if in_frame and len(frame_data) >= 8:
                            process_frame(frame_data)
                        in_frame = True
                        frame_data = bytearray()
                        frame_data.append(next_byte[0])
                else:
                    if in_frame: frame_data.append(byte[0])
            else:
                time.sleep(0.01)
    except Exception as e: print(f"{ANSI.DIM}[{get_iso_time()}]{ANSI.RESET} {ANSI.RED}Serial Interface Drop: {e}{ANSI.RESET}")


async def broadcast_state(websocket):
    global ledger_count
    
    async def send_updates():
        try:
            while True:
                with state_lock:
                    now = time.time()
                    payload = []
                    for icao, data in aircraft_state.items():
                        plane = data.copy()
                        age = now - data["last_seen"]
                        if data.get("farewell_sent"):
                            plane["age"] = "<span class='empty-datum'>----</span><span style='display:none;'>"
                        else:
                            plane["age"] = int(age)
                            
                        raw_sweep = data.get("raw_sweep_interval", 1.5)
                        coast_threshold = max(5.0, min(raw_sweep + 2.5, 15.0))
                        plane["is_coasting"] = age > coast_threshold
                        plane["is_identing"] = (now - data["ident_time"]) < 18
                        payload.append(plane)
                
                out_data = {
                    "airframes": payload,
                    "airspace": AIRSPACE_GEOJSON,
                    "meta": { "ledger_count": ledger_count }
                }
                await websocket.send(json.dumps(out_data))
                await asyncio.sleep(1)
        except websockets.exceptions.ConnectionClosed: pass

    async def receive_updates():
        try:
            async for message in websocket:
                data = json.loads(message)
                if data.get("action") == "add_wpt":
                    wpt = data.get("waypoint")
                    if wpt:
                        feature = {
                            "type": "Feature",
                            "geometry": { "type": "Point", "coordinates": [wpt["LONG"], wpt["LAT"]] },
                            "properties": { "name": wpt["Waypoint_Name"], "icon": wpt["type"], "color": "rgba(56, 189, 248, 0.9)" }
                        }
                        AIRSPACE_GEOJSON["features"].append(feature)
                        save_airspace()
                        
                elif data.get("action") == "delete_feature":
                    idx = data.get("index")
                    if idx is not None and 0 <= idx < len(AIRSPACE_GEOJSON["features"]):
                        del AIRSPACE_GEOJSON["features"][idx]
                        save_airspace()
        except Exception: pass

    await asyncio.gather(send_updates(), receive_updates())


async def main():
    print(f"{ANSI.DIM}[{get_iso_time()}]{ANSI.RESET} {ANSI.CYAN}Serial source armed on {PORT} @ {BAUD} baud ({RECEIVER_ID}){ANSI.RESET}")
    print(f"{ANSI.DIM}[{get_iso_time()}]{ANSI.RESET} {ANSI.GREEN}Tactical Matrix Core {APP_VERSION} online on ws://{WS_HOST}:{WS_PORT}{ANSI.RESET}")
    print(f"{ANSI.DIM}[{get_iso_time()}]{ANSI.RESET} {ANSI.CYAN}DARTS API online on http://localhost:{HTTP_PORT} (fields + grid config){ANSI.RESET}")
    async with websockets.serve(broadcast_state, WS_HOST, WS_PORT):
        await asyncio.Future()

if __name__ == "__main__":
    load_airline_db()
    load_historical_state()
    load_airspace()
    threading.Thread(target=serial_reader_thread, daemon=True).start()
    threading.Thread(target=run_reaper_loop, daemon=True).start()
    threading.Thread(target=archivist_loop, daemon=True).start()
    threading.Thread(target=run_http_server, daemon=True).start()
    try: asyncio.run(main())
    except KeyboardInterrupt: print(f"\n{ANSI.DIM}[{get_iso_time()}]{ANSI.RESET} {ANSI.RED}Shutting down Tactical Matrix...{ANSI.RESET}")