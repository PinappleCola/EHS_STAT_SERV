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
        self.feed = DARTS.Vdl2JsonFeed()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.feed_path = Path(self.temp_dir.name) / "vdl2.json"
        self.feed_path.write_bytes(b"")

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def _frame(src="7CAF1B"):
        return json.dumps({"vdl2": {"avlc": {"src": {"addr": src}}}})

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


if __name__ == "__main__":
    unittest.main()
