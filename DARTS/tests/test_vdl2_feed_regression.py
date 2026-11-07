import importlib.util
import json
import tempfile
import unittest
import copy
from unittest.mock import patch
from pathlib import Path


def _load_darts_module():
    feed_path = Path(__file__).resolve().parents[1] / "vdl2_feed.py"
    spec = importlib.util.spec_from_file_location("darts_vdl2_feed_under_test", str(feed_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DARTS = _load_darts_module()


class Vdl2FeedRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.feed_path = Path(self.temp_dir.name) / "vdl2.json"
        self.feed_path.write_bytes(b"")
        self.airport_path = Path(self.temp_dir.name) / "airports.JSON"
        self.airport_path.write_text(json.dumps({
            "YSSY": {"icao": "YSSY", "name": "Sydney Airport"},
            "YPAD": {"icao": "YPAD", "name": "Adelaide Airport"},
        }))
        self.feed = DARTS.Vdl2JsonFeed(self.airport_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def _frame(src="7CAF1B"):
        return json.dumps({"vdl2": {"avlc": {"src": {"addr": src}}}})

    def test_airport_matching_only_complete_payload_tokens(self):
        record = self._rsi_record()
        original = copy.deepcopy(record)
        self.assertEqual(DARTS.find_airport_codes(record, {"YSSY", "YPAD"}),
                         ["YPAD", "YSSY"])
        self.assertEqual(record, original, "matching must not modify decoded records")
        record["vdl2"]["avlc"]["acars"]["msg_text"] = (
            "yssy /YPAD YSSY, XYSSYX YSSY123 1YPAD YSSYYPAD UNKNOWN"
        )
        self.assertEqual(DARTS.find_airport_codes(record, {"YSSY", "YPAD"}),
                         ["YPAD", "YSSY"])
        record["vdl2"]["avlc"]["acars"] = {"YSSY": "XYSSYX", "flight": "YSSY123"}
        record["vdl2"]["avlc"]["src"]["addr"] = "YPAD"
        self.assertEqual(DARTS.find_airport_codes(record, {"YSSY", "YPAD"}), [])
        record = self._xid_record()
        record["vdl2"]["avlc"]["xid"]["vdl_params"].append(
            {"name": "dst_airport", "value": "YSSY"})
        self.assertEqual(DARTS.find_airport_codes(record, {"YSSY"}), ["YSSY"])
        self.assertEqual(DARTS.find_airport_codes(record, set()), [])

    def test_airport_lookup_is_cached_and_matches_are_aligned(self):
        record = self._rsi_record()
        unmatched = {"vdl2": {"avlc": {"src": {"addr": "7CAF1B", "type": "Aircraft"},
                                     "acars": {"msg_text": "No airports here"}}}}
        original = copy.deepcopy(record)
        with patch.object(DARTS.time, "time", return_value=record["vdl2"]["t"]["sec"]), \
                patch.object(DARTS.json, "load", wraps=DARTS.json.load) as load, \
                patch.object(DARTS, "find_airport_codes", wraps=DARTS.find_airport_codes) as match:
            self.feed.snapshot(str(self.feed_path))
            with self.feed_path.open("a") as feed:
                feed.write(json.dumps(record) + "\n" + json.dumps(unmatched) + "\n")
            snapshot = self.feed.snapshot(str(self.feed_path))
            self.feed.snapshot(str(self.feed_path))
            self.assertEqual(load.call_count, 1, "unchanged lookup is not reread per poll")
            self.assertEqual(match.call_count, 2, "only new records are matched")
        self.assertEqual(snapshot["frame_airports"], [["YPAD", "YSSY"], []])
        self.assertEqual(snapshot["new_frames"][0]["airport_codes"], ["YPAD", "YSSY"])
        self.assertEqual(snapshot["frame_positions"][0]["airport_codes"], ["YPAD", "YSSY"])
        self.assertEqual(snapshot["positions"][0]["airport_codes"], ["YPAD", "YSSY"])
        self.assertEqual(snapshot["frames"], [original, unmatched])
        self.assertEqual(snapshot["airport_lookup_error"], "")
        self.assertEqual(self.feed.snapshot("")["frame_airports"], [])

    def test_airport_lookup_errors_do_not_interrupt_vdl2_and_recover(self):
        self.airport_path.unlink()
        missing = self.feed.snapshot(str(self.feed_path))
        self.assertTrue(missing["connected"])
        self.assertIn("Airport lookup unavailable", missing["airport_lookup_error"])
        for content in ("{", "[]", '{"BAD": {}}', '{"YSSY": {"icao": "YPAD"}}'):
            self.airport_path.write_text(content)
            with self.feed_path.open("a") as feed:
                feed.write(json.dumps(self._rsi_record()) + "\n")
            snapshot = self.feed.snapshot(str(self.feed_path))
            self.assertTrue(snapshot["connected"])
            self.assertTrue(snapshot["airport_lookup_error"])
            self.assertEqual(snapshot["frame_airports"][-1], [])
        self.airport_path.write_text('{"YSSY": {"icao": "YSSY"}}')
        # Ensure the replacement is observable even on coarse-timestamp filesystems.
        stat = self.airport_path.stat()
        DARTS.os.utime(self.airport_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        with self.feed_path.open("a") as feed:
            feed.write(json.dumps(self._rsi_record()) + "\n")
        snapshot = self.feed.snapshot(str(self.feed_path))
        self.assertEqual(snapshot["airport_lookup_error"], "")
        self.assertEqual(snapshot["frame_airports"][-1], ["YSSY"])

    def test_reads_only_complete_newline_delimited_frames(self):
        self.feed_path.write_text(self._frame("OLD123") + "\n", encoding="utf-8")
        initial = self.feed.snapshot(str(self.feed_path))
        self.assertTrue(initial["connected"])
        self.assertEqual(initial["frames"], [])

        with self.feed_path.open("ab") as feed:
            feed.write(self._frame().encode("utf-8"))
        self.assertEqual(self.feed.snapshot(str(self.feed_path))["frames"], [])

        with self.feed_path.open("ab") as feed:
            feed.write(b"\n")
        frames = self.feed.snapshot(str(self.feed_path))["frames"]
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["vdl2"]["avlc"]["src"]["addr"], "7CAF1B")

    def test_skips_malformed_lines_and_recovers_from_truncation(self):
        self.feed.snapshot(str(self.feed_path))
        with self.feed_path.open("ab") as feed:
            feed.write(b"not-json\n")
            feed.write((self._frame() + "\n").encode("utf-8"))
        snapshot = self.feed.snapshot(str(self.feed_path))
        self.assertEqual(snapshot["invalid_lines"], 1)
        self.assertEqual(len(snapshot["frames"]), 1)

        self.feed_path.write_text(self._frame("A3D91F") + "\n", encoding="utf-8")
        snapshot = self.feed.snapshot(str(self.feed_path))
        self.assertEqual(len(snapshot["frames"]), 2)
        self.assertEqual(snapshot["frames"][-1]["vdl2"]["avlc"]["src"]["addr"], "A3D91F")

    def test_poss_coordinates_and_validation(self):
        record = self._position_record()
        position = DARTS.parse_poss_report(record)
        self.assertAlmostEqual(position["lat"], -(32 + 43.3 / 60))
        self.assertAlmostEqual(position["lon"], 149 + 26.9 / 60)
        self.assertEqual(position["icao"], "7C7A49")
        self.assertEqual(position["message_type"], "H1/M1 POS")
        self.assertEqual(position["coordinate_text"], "POSS32433E149269")
        self.assertIs(position["record"], record)
        for field, value in [("crc_ok", False), ("more", True), ("label", "DF")]:
            invalid = copy.deepcopy(record)
            invalid["vdl2"]["avlc"]["acars"][field] = value
            self.assertIsNone(DARTS.parse_poss_report(invalid))
        record["vdl2"]["avlc"]["acars"]["msg_text"] = "POSS32600E149269,SPLIZ,041237,390,"
        self.assertIsNone(DARTS.parse_poss_report(record))

    def test_adsc_basic_report_position_and_true_track(self):
        record = self._adsc_record()
        position = DARTS.parse_adsc_basic_report(record)
        self.assertEqual(position["icao"], "888168")
        self.assertEqual(position["lat"], -33.638077)
        self.assertEqual(position["lon"], 150.827522)
        self.assertEqual(position["true_track_deg"], 313.417969)
        self.assertEqual(position["message_type"], "ADS-C BASIC")
        self.assertEqual(position["report_time"], 1793927332.0)
        self.assertIs(position["record"], record)

        invalid = copy.deepcopy(record)
        invalid["vdl2"]["avlc"]["acars"]["arinc622"]["adsc"]["tags"][1]["earth_ref_data"]["true_trk_valid"] = False
        self.assertIsNone(DARTS.parse_adsc_basic_report(invalid)["true_track_deg"])
        invalid = copy.deepcopy(record)
        invalid["vdl2"]["avlc"]["acars"]["arinc622"]["adsc"]["tags"][0]["basic_report"]["lat"] = 91
        self.assertIsNone(DARTS.parse_adsc_basic_report(invalid))
        invalid = copy.deepcopy(record)
        invalid["vdl2"]["avlc"]["acars"]["crc_ok"] = False
        self.assertIsNone(DARTS.parse_adsc_basic_report(invalid))

    def test_xid_aircraft_location_and_rounding_uncertainty(self):
        record = self._xid_record()
        position = DARTS.parse_xid_aircraft_location(record)
        expected_radius = DARTS.math.hypot(
            3, 3 * DARTS.math.cos(DARTS.math.radians(-33.6))
        )
        self.assertEqual(position["icao"], "7CF836")
        self.assertEqual(position["lat"], -33.6)
        self.assertEqual(position["lon"], 150.9)
        self.assertEqual(position["alt"], 4000)
        self.assertEqual(position["message_type"], "XID LOCATION")
        self.assertEqual(position["report_time"], 1793937866.0)
        self.assertAlmostEqual(position["position_uncertainty_nm"], expected_radius)
        self.assertIs(position["record"], record)

        invalid = copy.deepcopy(record)
        invalid["vdl2"]["avlc"]["xid"]["vdl_params"][0]["value"]["loc"]["lat"] = 91
        self.assertIsNone(DARTS.parse_xid_aircraft_location(invalid))
        invalid = copy.deepcopy(record)
        invalid["vdl2"]["avlc"]["xid"]["vdl_params"][0]["value"]["loc"]["lon"] = float("nan")
        self.assertIsNone(DARTS.parse_xid_aircraft_location(invalid))
        invalid = copy.deepcopy(record)
        invalid["vdl2"]["avlc"]["src"]["addr"] = "not-icao"
        self.assertIsNone(DARTS.parse_xid_aircraft_location(invalid))
        invalid = copy.deepcopy(record)
        invalid["vdl2"]["avlc"]["xid"]["vdl_params"][0]["value"]["alt"] = True
        self.assertIsNone(DARTS.parse_xid_aircraft_location(invalid)["alt"])

    @staticmethod
    def _position_record():
        return {"vdl2": {
            "t": {"sec": 1793938360},
            "avlc": {
                "src": {"addr": "7c7a49", "type": "Aircraft"},
                "acars": {"label": "H1", "sublabel": "M1", "err": False, "crc_ok": True,
                          "more": False, "msg_text": "POSS32433E149269,SPLIZ,041237,390,"},
            },
        }}

    @staticmethod
    def _adsc_record():
        return {"vdl2": {
            "t": {"sec": 1793927332},
            "avlc": {
                "src": {"addr": "888168", "type": "Aircraft"},
                "acars": {
                    "label": "B6", "err": False, "crc_ok": True, "more": False,
                    "arinc622": {
                        "crc_ok": True,
                        "adsc": {"err": False, "tags": [
                            {"basic_report": {
                                "lat": -33.638077, "lon": 150.827522,
                                "alt": 11592, "pos_accuracy_nm": 0.05,
                            }},
                            {"earth_ref_data": {
                                "true_trk_deg": 313.417969, "true_trk_valid": True,
                            }},
                        ]},
                    },
                },
            },
        }}

    @staticmethod
    def _xid_record():
        return {"vdl2": {
            "t": {"sec": 1793937866},
            "avlc": {
                "src": {"addr": "7CF836", "type": "Aircraft"},
                "frame_type": "U", "cmd": "XID",
                "xid": {"vdl_params": [
                    {"name": "ac_location", "value": {
                        "loc": {"lat": -33.6, "lon": 150.9}, "alt": 4000,
                    }},
                ]},
            },
        }}

    def test_latest_position_expiry_and_duplicate_handling(self):
        record = self._position_record()
        with patch.object(DARTS.time, "time", return_value=1793938360):
            self.feed.snapshot(str(self.feed_path))
            with self.feed_path.open("a") as feed:
                feed.write(json.dumps(record) + "\n")
                feed.write(json.dumps(record) + "\n")
            snapshot = self.feed.snapshot(str(self.feed_path))
            self.assertEqual(len(snapshot["positions"]), 1)
            report_time = snapshot["positions"][0]["report_time"]
            older = copy.deepcopy(record)
            older["vdl2"]["avlc"]["acars"]["msg_text"] = "POSS31091E150442,RUPOG,041200,370,"
            with self.feed_path.open("a") as feed:
                feed.write(json.dumps(older) + "\n")
            history = self.feed.snapshot(str(self.feed_path))["positions"]
            self.assertEqual(len(history), 2)
            self.assertEqual(max(item["report_time"] for item in history), report_time)
        with patch.object(DARTS.time, "time", return_value=report_time + 599):
            self.assertEqual(len(self.feed.snapshot(str(self.feed_path))["positions"]), 1)
        with patch.object(DARTS.time, "time", return_value=report_time + 600):
            self.assertEqual(self.feed.snapshot(str(self.feed_path))["positions"], [])

    def test_midnight_date_and_northern_western_coordinates(self):
        record = self._position_record()
        midnight = DARTS.datetime.datetime(2026, 11, 7, 0, 0, 10, tzinfo=DARTS.datetime.timezone.utc)
        record["vdl2"]["t"]["sec"] = midnight.timestamp()
        record["vdl2"]["avlc"]["acars"]["msg_text"] = "POSN32433W149269,SPLIZ,235950,390,"
        position = DARTS.parse_poss_report(record)
        self.assertEqual(position["report_time"], midnight.timestamp() - 20)
        self.assertGreater(position["lat"], 0)
        self.assertLess(position["lon"], 0)

    def test_stream_coordinate_metadata_preserves_full_records_and_alignment(self):
        record = self._position_record()
        invalid = copy.deepcopy(record)
        invalid["vdl2"]["avlc"]["acars"]["crc_ok"] = False
        self.feed.snapshot(str(self.feed_path))
        records = [record, invalid] * 53
        with self.feed_path.open("a") as feed:
            for item in records:
                feed.write(json.dumps(item) + "\n")
            feed.write("invalid-json\n")
        snapshot = self.feed.snapshot(str(self.feed_path))
        self.assertEqual(snapshot["frames"], records[-100:])
        self.assertEqual(snapshot["frame_ids"], list(range(7, 107)))
        self.assertEqual(len(snapshot["new_frames"]), 106)
        self.assertEqual(len(snapshot["frame_positions"]), 100)
        self.assertEqual(
            snapshot["frame_coordinates"], ["POSS32433E149269", None] * 50
        )
        self.assertEqual(snapshot["invalid_lines"], 1)
        cleared = self.feed.snapshot("")
        self.assertEqual(cleared["frame_coordinates"], [])
        self.assertEqual(cleared["frame_ads_c"], [])

    def test_adsc_reports_are_added_to_vdl2_positions_and_console_metadata(self):
        record = self._adsc_record()
        with patch.object(DARTS.time, "time", return_value=record["vdl2"]["t"]["sec"]):
            self.feed.snapshot(str(self.feed_path))
            with self.feed_path.open("a") as feed:
                feed.write(json.dumps(record) + "\n")
            snapshot = self.feed.snapshot(str(self.feed_path))
        self.assertEqual(snapshot["frame_ads_c"], [{
            "icao": "888168", "lat": -33.638077, "lon": 150.827522,
            "true_track_deg": 313.417969,
        }])
        self.assertEqual(len(snapshot["positions"]), 1)
        self.assertEqual(snapshot["positions"][0]["message_type"], "ADS-C BASIC")
        self.assertEqual(snapshot["positions"][0]["true_track_deg"], 313.417969)

    def test_xid_location_is_added_to_position_history_and_frame_metadata(self):
        record = self._xid_record()
        with patch.object(DARTS.time, "time", return_value=record["vdl2"]["t"]["sec"]):
            self.feed.snapshot(str(self.feed_path))
            with self.feed_path.open("a") as feed:
                feed.write(json.dumps(record) + "\n")
            snapshot = self.feed.snapshot(str(self.feed_path))
        expected_radius = DARTS.parse_xid_aircraft_location(record)["position_uncertainty_nm"]
        self.assertEqual(snapshot["frame_positions"][0]["message_type"], "XID LOCATION")
        self.assertAlmostEqual(snapshot["frame_positions"][0]["position_uncertainty_nm"], expected_radius)
        self.assertEqual(snapshot["frame_positions"][0]["alt"], 4000)
        self.assertEqual(snapshot["positions"][0]["icao"], "7CF836")
        self.assertAlmostEqual(snapshot["positions"][0]["position_uncertainty_nm"], expected_radius)

    @staticmethod
    def _rsi_record():
        capture = DARTS.datetime.datetime(2026, 11, 7, 6, 13, 38,
                                         tzinfo=DARTS.datetime.timezone.utc).timestamp()
        return {"vdl2": {"t": {"sec": capture}, "avlc": {
            "src": {"addr": "7C6DD9", "type": "Aircraft"},
            "acars": {"label": "H1", "sublabel": "DF", "err": False,
                      "crc_ok": True, "more": False, "msg_text":
                      "RSI\r\nTEST FLIGHT\r\n0613 07NOV26 YSSY YPAD CL 235\r\n\r\n"
                      "  LAT      LON      GALT  TTRK GS\r\n"
                      "-34.1103  150.9005  19801  -73 323\r\n\r\n"
                      "INOP NON-AP INHB POS-ERR\r\n  1  0  0  0\r\n"},
        }}}

    def test_adsc_waypoint_change_current_and_predicted_route(self):
        record = self._adsc_record()
        record["vdl2"]["t"]["sec"] = 1794040298
        tags = record["vdl2"]["avlc"]["acars"]["arinc622"]["adsc"]["tags"]
        tags[:] = [
            {"wpt_change_event": {"lat": -33.779869, "lon": 150.573807, "ts_sec": 1896.0}},
            {"predicted_route": {
                "next_wpt": {"lat": -33.746567, "lon": 151.124325, "eta_sec": 351},
                "next_next_wpt": {"lat": -33.845959, "lon": 151.149902},
            }},
        ]
        parsed = DARTS.parse_adsc_waypoint_report(record)
        self.assertEqual(parsed["message_type"], "ADS-C WPT CHANGE")
        self.assertEqual(parsed["report_time"], 1794040296)
        self.assertIsNone(parsed["true_track_deg"])
        self.assertEqual(parsed["lat"], -33.779869)
        self.assertEqual([point["label"] for point in parsed["predicted_route"]], ["NEXT", "NEXT+1"])
        self.assertEqual(parsed["predicted_route"][0]["eta_sec"], 351)
        self.assertIsNone(DARTS.parse_adsc_basic_report(record))
        with patch.object(DARTS.time, "time", return_value=1794040298):
            self.feed.snapshot(str(self.feed_path))
            with self.feed_path.open("a") as feed:
                feed.write(json.dumps(record) + "\n")
            snapshot = self.feed.snapshot(str(self.feed_path))
        self.assertEqual(snapshot["frame_positions"][0]["message_type"], "ADS-C WPT CHANGE")
        self.assertEqual(len(snapshot["positions"]), 1)
        self.assertEqual(len(snapshot["positions"][0]["predicted_route"]), 2)
        tags[1]["predicted_route"]["next_wpt"]["lat"] = 91
        self.assertEqual(len(DARTS.parse_adsc_waypoint_report(record)["predicted_route"]), 1)
        tags[0]["wpt_change_event"]["ts_sec"] = 3600
        self.assertIsNone(DARTS.parse_adsc_waypoint_report(record))

    def test_adsc_waypoint_timestamp_previous_hour(self):
        record = self._adsc_record()
        record["vdl2"]["t"]["sec"] = 1794042002  # 09:00:02 UTC
        record["vdl2"]["avlc"]["acars"]["arinc622"]["adsc"]["tags"] = [
            {"wpt_change_event": {"lat": -33.7, "lon": 150.5, "ts_sec": 3599}},
        ]
        self.assertEqual(DARTS.parse_adsc_waypoint_report(record)["report_time"], 1794041999)

    def test_adsc_basic_predicted_route_and_report_time(self):
        record = self._adsc_record()
        record["vdl2"]["t"]["sec"] = 1794027780
        tags = record["vdl2"]["avlc"]["acars"]["arinc622"]["adsc"]["tags"]
        tags[0]["basic_report"].update(
            lat=-33.593445, lon=150.591488, alt=18348, ts_sec=179, pos_accuracy_nm=0.05)
        tags.append({"predicted_route": {
            "next_wpt": {"lat": -33.411827, "lon": 150.438709, "alt": 23160, "eta_sec": 168},
            "next_next_wpt": {"lat": -33.113823, "lon": 150.079765, "alt": 29776},
        }})
        parsed = DARTS.parse_adsc_basic_report(record)
        self.assertEqual(parsed["report_time"], 1794027779)
        self.assertEqual(parsed["alt"], 18348)
        self.assertEqual(parsed["pos_accuracy_nm"], 0.05)
        self.assertEqual(parsed["predicted_route"], [
            {"label": "NEXT", "lat": -33.411827, "lon": 150.438709, "alt": 23160, "eta_sec": 168},
            {"label": "NEXT+1", "lat": -33.113823, "lon": 150.079765, "alt": 29776},
        ])
        with patch.object(DARTS.time, "time", return_value=1794027780):
            self.feed.snapshot(str(self.feed_path))
            with self.feed_path.open("a") as feed:
                feed.write(json.dumps(record) + "\n")
            snapshot = self.feed.snapshot(str(self.feed_path))
        self.assertEqual(snapshot["frame_positions"][0]["predicted_route"], parsed["predicted_route"])
        self.assertEqual(snapshot["positions"][0]["report_time"], 1794027779)
        self.assertEqual(snapshot["positions"][0]["alt"], 18348)
        tags[-1]["predicted_route"]["next_wpt"]["alt"] = 24000
        with patch.object(DARTS.time, "time", return_value=1794027780):
            with self.feed_path.open("a") as feed:
                feed.write(json.dumps(record) + "\n")
            snapshot = self.feed.snapshot(str(self.feed_path))
        self.assertEqual(len(snapshot["positions"]), 1)
        self.assertEqual(snapshot["positions"][0]["predicted_route"][0]["alt"], 24000)
        tags[-1]["predicted_route"]["next_wpt"]["lat"] = float("nan")
        self.assertEqual(len(DARTS.parse_adsc_basic_report(record)["predicted_route"]), 1)
        tags[0]["basic_report"]["ts_sec"] = float("nan")
        self.assertIsNone(DARTS.parse_adsc_basic_report(record))

    def test_adsc_altitude_and_lateral_events(self):
        for key, label, parser in (
            ("alt_range_event", "ADS-C ALT RANGE", DARTS.parse_adsc_altitude_event),
            ("lat_dev_change_event", "ADS-C LAT DEV", DARTS.parse_adsc_lateral_event),
        ):
            with self.subTest(key=key):
                record = self._adsc_record()
                record["vdl2"]["t"]["sec"] = 1794032337
                tags = record["vdl2"]["avlc"]["acars"]["arinc622"]["adsc"]["tags"]
                tags[:] = [{key: {"lat": -33.823299, "lon": 151.029224, "alt": 5708,
                                  "ts_sec": 1135, "pos_accuracy_nm": 0.05}}]
                parsed = parser(record)
                self.assertEqual((parsed["message_type"], parsed["report_time"]), (label, 1794032335))
                self.assertEqual((parsed["lat"], parsed["lon"], parsed["alt"]), (-33.823299, 151.029224, 5708))
                self.assertEqual(parsed["pos_accuracy_nm"], 0.05)
                with patch.object(DARTS.time, "time", return_value=1794032337):
                    self.feed.snapshot(str(self.feed_path))
                    with self.feed_path.open("a") as feed:
                        feed.write(json.dumps(record) + "\n")
                    snapshot = self.feed.snapshot(str(self.feed_path))
                self.assertEqual(snapshot["frame_positions"][-1]["message_type"], label)
                self.assertTrue(any(p["message_type"] == label for p in snapshot["positions"]))
                invalid = copy.deepcopy(record)
                invalid["vdl2"]["avlc"]["acars"]["arinc622"]["crc_ok"] = False
                self.assertIsNone(parser(invalid))
                invalid = copy.deepcopy(record)
                invalid["vdl2"]["avlc"]["acars"]["arinc622"]["adsc"]["tags"][0][key]["ts_sec"] = 3600
                self.assertIsNone(parser(invalid))
                invalid = copy.deepcopy(record)
                invalid["vdl2"]["avlc"]["acars"]["arinc622"]["adsc"]["tags"][0][key]["lat"] = True
                self.assertIsNone(parser(invalid))

    def test_rsi_decimal_position_signed_track_and_report_time(self):
        record = self._rsi_record()
        parsed = DARTS.parse_rsi_report(record)
        self.assertEqual(parsed["lat"], -34.1103)
        self.assertEqual(parsed["lon"], 150.9005)
        self.assertEqual(parsed["true_track_deg"], 287)
        self.assertEqual(parsed["message_type"], "H1/DF RSI")
        self.assertEqual(parsed["report_time"], record["vdl2"]["t"]["sec"] - 38)
        for raw, expected in (("-152", 208), ("73", 73), ("0", 0), ("359", 359)):
            candidate = copy.deepcopy(record)
            candidate["vdl2"]["avlc"]["acars"]["msg_text"] = (
                candidate["vdl2"]["avlc"]["acars"]["msg_text"].replace("-73", raw))
            self.assertEqual(DARTS.parse_rsi_report(candidate)["true_track_deg"], expected)

    def test_rsi_rejects_invalid_or_incomplete_positions(self):
        record = self._rsi_record()
        for field, value in (("more", True), ("crc_ok", False), ("err", True),
                             ("sublabel", "M1")):
            candidate = copy.deepcopy(record)
            candidate["vdl2"]["avlc"]["acars"][field] = value
            self.assertIsNone(DARTS.parse_rsi_report(candidate))
        text = record["vdl2"]["avlc"]["acars"]["msg_text"]
        for invalid in (text.replace("-34.1103", "-94.1103"),
                        text.replace("-73", "-181"), text.replace("-73", "360"),
                        text.replace("  1  0  0  0", "  1  0  0  1"),
                        text.replace("07NOV26", "31NOV26"),
                        text.replace("0613", "2413"),
                        text.replace("POS-ERR", "OTHER")):
            candidate = copy.deepcopy(record)
            candidate["vdl2"]["avlc"]["acars"]["msg_text"] = invalid
            self.assertIsNone(DARTS.parse_rsi_report(candidate))

    def test_rsi_feed_classification_and_sequence_alignment(self):
        record = self._rsi_record()
        now = record["vdl2"]["t"]["sec"]
        with patch.object(DARTS.time, "time", return_value=now):
            self.feed.snapshot(str(self.feed_path))
            with self.feed_path.open("a") as feed:
                feed.write(json.dumps(record) + "\n" + self._frame() + "\n")
            snapshot = self.feed.snapshot(str(self.feed_path))
            self.assertEqual(snapshot["frame_ids"], [1, 2])
            self.assertEqual(snapshot["frame_positions"][0]["message_type"], "H1/DF RSI")
            self.assertIsNone(snapshot["frame_positions"][1])
            self.assertEqual(snapshot["positions"][0]["true_track_deg"], 287)
            self.assertEqual(self.feed.snapshot(str(self.feed_path))["frame_ids"], [1, 2])
        with patch.object(DARTS.time, "time", return_value=now + 562):
            self.assertEqual(self.feed.snapshot(str(self.feed_path))["positions"], [])
        self.assertEqual(self.feed.snapshot("")["frame_ids"], [])
        self.assertEqual(self.feed.snapshot("")["new_frames"], [])


if __name__ == "__main__":
    unittest.main()
