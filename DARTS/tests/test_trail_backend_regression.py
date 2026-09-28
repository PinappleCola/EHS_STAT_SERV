import copy
import importlib.util
import sqlite3
import threading
import unittest
from pathlib import Path


def _load_darts_module():
    darts_path = Path(__file__).resolve().parents[1] / "darts.py"
    spec = importlib.util.spec_from_file_location("darts_under_test", str(darts_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DARTS = _load_darts_module()


class TrailBackendRegressionTests(unittest.TestCase):
    def setUp(self):
        self._old_conn = DARTS.trail_db_conn
        self._old_lock = DARTS.trail_db_lock
        self._old_state = DARTS.trail_runtime_state

        DARTS.trail_db_conn = sqlite3.connect(":memory:", check_same_thread=False)
        DARTS.trail_db_lock = threading.Lock()
        DARTS.trail_runtime_state = {}

        DARTS.trail_db_conn.execute(
            """
            CREATE TABLE trail_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                icao TEXT NOT NULL,
                ts_ms INTEGER NOT NULL,
                lat REAL,
                lon REAL,
                altitude TEXT,
                on_ground INTEGER,
                callsign TEXT,
                source_label TEXT,
                receiver_id TEXT,
                marker_type TEXT,
                event_key TEXT UNIQUE
            )
            """
        )
        DARTS.trail_db_conn.commit()

        self.cfg = copy.deepcopy(DARTS.DEFAULT_TRAIL_CONFIG)
        self.cfg["stale_position_threshold_seconds"] = 65.0
        self.cfg["adaptive_gap"]["enabled"] = True
        self.cfg["adaptive_gap"]["min_seconds"] = 10.0
        self.cfg["adaptive_gap"]["max_seconds"] = 65.0
        self.cfg["adaptive_gap"]["multiplier"] = 4.0

    def tearDown(self):
        DARTS.trail_db_conn.close()
        DARTS.trail_db_conn = self._old_conn
        DARTS.trail_db_lock = self._old_lock
        DARTS.trail_runtime_state = self._old_state

    @staticmethod
    def _snapshot(icao, lat, lon, now_ms, alt="30000", air_ground="AIR"):
        return {
            icao: {
                "icao": icao,
                "lat": lat,
                "lon": lon,
                "alt": alt,
                "air_ground": air_ground,
                "callsign": "TEST123",
                "_lat_update_time": now_ms / 1000.0,
            }
        }

    def _persist(self, records):
        DARTS.persist_trail_records(records)

    def test_gap_break_same_timestamp_and_no_direct_segment(self):
        icao = "ABC123"
        t0 = 1_000_000
        t1 = t0 + 70_000

        records_a = DARTS.build_trail_records(self._snapshot(icao, -33.0, 151.0, t0), t0, self.cfg)
        self.assertEqual(len(records_a), 1)
        self._persist(records_a)

        records_b = DARTS.build_trail_records(self._snapshot(icao, -33.2, 151.2, t1), t1, self.cfg)
        self.assertEqual(len(records_b), 2)
        self.assertEqual(records_b[0][9], "gap_break")
        self.assertIsNone(records_b[1][9])
        self.assertEqual(records_b[0][1], records_b[1][1])
        self.assertNotEqual(records_b[0][10], records_b[1][10])
        self._persist(records_b)

        rows = DARTS.query_trail_rows(t0 - 1, t1 + 1, icao=icao)
        markers = [row for row in rows if row[10]]
        self.assertEqual(len(markers), 1)
        marker_idx = next(i for i, row in enumerate(rows) if row[10])
        self.assertEqual(rows[marker_idx + 1][10], None)
        self.assertEqual(rows[marker_idx][2], rows[marker_idx + 1][2])

        geojson = DARTS.build_geojson_from_trail_rows(rows)
        self.assertEqual(geojson["features"], [])

    def test_jump_break_emitted_for_implausible_move(self):
        icao = "JMP001"
        t0 = 2_000_000
        t1 = t0 + 5_000
        jump_cfg = copy.deepcopy(self.cfg)
        jump_cfg["stale_position_threshold_seconds"] = 120.0

        self._persist(DARTS.build_trail_records(self._snapshot(icao, 0.0, 0.0, t0), t0, jump_cfg))
        records = DARTS.build_trail_records(self._snapshot(icao, 20.0, 20.0, t1), t1, jump_cfg)
        self.assertEqual(records[0][9], "jump_break")

    def test_normal_consecutive_points_join(self):
        icao = "NORM01"
        t0 = 3_000_000
        t1 = t0 + 5_000

        self._persist(DARTS.build_trail_records(self._snapshot(icao, -34.0, 150.0, t0), t0, self.cfg))
        self._persist(DARTS.build_trail_records(self._snapshot(icao, -34.01, 150.01, t1), t1, self.cfg))

        rows = DARTS.query_trail_rows(t0 - 1, t1 + 1, icao=icao)
        self.assertFalse(any(row[10] for row in rows))
        geojson = DARTS.build_geojson_from_trail_rows(rows)
        self.assertEqual(len(geojson["features"]), 1)
        self.assertEqual(geojson["features"][0]["properties"]["point_count"], 2)

    def test_legacy_missing_marker_is_split_by_backstop(self):
        icao = "LEG001"
        t0 = 4_000_000
        t1 = t0 + 90_000

        rows_to_insert = [
            (icao, t0, -33.0, 151.0, "30000", 0, "LEGACY", "A", "A", None, DARTS.make_trail_event_key(icao, t0, -33.0, 151.0, None)),
            (icao, t1, -33.1, 151.1, "30000", 0, "LEGACY", "A", "A", None, DARTS.make_trail_event_key(icao, t1, -33.1, 151.1, None)),
        ]
        self._persist(rows_to_insert)

        rows = DARTS.query_trail_rows(t0 - 1, t1 + 1, icao=icao)
        self.assertTrue(any(row[10] == "gap_break" for row in rows))

        geojson = DARTS.build_geojson_from_trail_rows(rows)
        self.assertEqual(geojson["features"], [])

    def test_duplicate_observation_after_gap_keeps_marker(self):
        icao = "DUP001"
        t0 = 5_000_000
        t1 = t0 + 70_000
        t2 = t1 + 5_000

        self._persist(DARTS.build_trail_records(self._snapshot(icao, -32.0, 150.0, t0), t0, self.cfg))

        duplicate_reacquire = DARTS.build_trail_records(self._snapshot(icao, -32.0, 150.0, t1), t1, self.cfg)
        self.assertEqual(len(duplicate_reacquire), 1)
        self.assertEqual(duplicate_reacquire[0][9], "gap_break")
        self._persist(duplicate_reacquire)

        moved = DARTS.build_trail_records(self._snapshot(icao, -32.0001, 150.0001, t2), t2, self.cfg)
        self.assertEqual(len(moved), 1)
        self.assertIsNone(moved[0][9])
        self._persist(moved)

        rows = DARTS.query_trail_rows(t0 - 1, t2 + 1, icao=icao)
        marker_indices = [idx for idx, row in enumerate(rows) if row[10]]
        self.assertEqual(len(marker_indices), 1)

        geojson = DARTS.build_geojson_from_trail_rows(rows)
        self.assertEqual(geojson["features"], [])

    def test_marker_sorts_before_point_when_same_timestamp(self):
        icao = "ORD001"
        ts = 6_000_000

        point_row = (icao, ts, -30.0, 140.0, "25000", 0, "ORD", "A", "A", None, DARTS.make_trail_event_key(icao, ts, -30.0, 140.0, None))
        marker_row = (icao, ts, None, None, None, None, "ORD", "A", "A", "gap_break", DARTS.make_trail_event_key(icao, ts, None, None, "gap_break"))
        self._persist([point_row, marker_row])

        rows = DARTS.query_trail_rows(ts - 1, ts + 1, icao=icao)
        self.assertEqual(rows[0][10], "gap_break")
        self.assertIsNone(rows[1][10])


if __name__ == "__main__":
    unittest.main()
