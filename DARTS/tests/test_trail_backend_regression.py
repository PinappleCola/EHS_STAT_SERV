import copy
import importlib.util
import sqlite3
import threading
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch


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
        for column in DARTS.TRAIL_TELEMETRY_COLUMNS:
            kind = "TEXT" if column in ("tcas_ra", "squawk") else "REAL"
            DARTS.trail_db_conn.execute(f"ALTER TABLE trail_points ADD COLUMN {column} {kind}")
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

    def test_3d_export_metres_and_invalid_altitude_breaks(self):
        icao = "ALT001"
        t0 = 7_000_000
        altitudes = ["-120", "GROUND", None, "", "oops", "NaN", "Infinity", "123.5"]
        records = [
            (icao, t0 + i * 1000, -33.0 + i * 0.0001, 151.0 + i * 0.0001,
             altitude, 0, "ALT", "RX", "A", None,
             DARTS.make_trail_event_key(icao, t0 + i * 1000, -33.0 + i * 0.0001,
                                        151.0 + i * 0.0001, None))
            for i, altitude in enumerate(altitudes)
        ]
        marker_time = t0 + 8_000
        records.append((icao, marker_time, None, None, None, None, "ALT", "RX", "A",
                        "gap_break", DARTS.make_trail_event_key(icao, marker_time, None, None, "gap_break")))
        for i in range(2):
            ts = marker_time + i * 1000
            records.append((icao, ts, -33.001 - i * 0.0001, 151.001 + i * 0.0001,
                            "-45", 0, "ALT", "RX", "A", None,
                            DARTS.make_trail_event_key(icao, ts, -33.001 - i * 0.0001,
                                                       151.001 + i * 0.0001, None)))
        self._persist(records)
        rows = DARTS.query_trail_rows(t0, marker_time + 1000, icao=icao, apply_backstop=False)
        two_d = DARTS.build_geojson_from_trail_rows(rows, apply_backstop=True)
        three_d = DARTS.build_geojson3d_from_trail_rows(rows, apply_backstop=True)
        self.assertEqual(three_d["type"], "FeatureCollection")
        self.assertEqual(len(three_d["features"]), 2)
        self.assertEqual(three_d["features"][0]["geometry"]["coordinates"],
                         [[row[4], row[3], z] for row, z in zip(rows[:2], [-36.6, 0])])
        self.assertEqual(three_d["features"][0]["properties"]["altitude_ft"], -60)
        self.assertEqual(three_d["features"][0]["properties"]["start_ts"], t0 // 1000)
        self.assertIsNone(three_d["features"][0]["properties"]["groundspeed_kt"])
        self.assertEqual([point[2] for point in three_d["features"][1]["geometry"]["coordinates"]], [-13.7, -13.7])
        self.assertEqual(three_d["metadata"]["schema"], "darts-3dspat-v1")
        for feature in three_d["features"]:
            self.assertFalse(any(isinstance(value, list) for value in feature["properties"].values()))
            self.assertNotIn("start_time_ms", feature["properties"])
        # The 2D schema still preserves its original full-trail arrays/raw altitude.
        self.assertEqual(two_d["features"][0]["properties"]["point_altitudes"], altitudes)
        self.assertEqual(two_d["features"][0]["properties"]["point_count"], 8)

    def test_3d_export_handler_reads_rows_and_sets_download_headers(self):
        class Response:
            def _parse_trail_range(self, query):
                return 1000, 2000, "ALT001"

            def _send_bytes(self, body, **kwargs):
                self.body = body
                self.kwargs = kwargs

        row = (1, "ALT001", 1000, -33.0, 151.0, "-7", 0, "ALT", "RX", "A", None)
        row2 = (2, "ALT001", 2000, -33.0001, 151.0001, "GROUND", 1, "ALT", "RX", "A", None)
        response = Response()
        with tempfile.TemporaryDirectory() as directory:
            store = DARTS.Export3DStore(str(Path(directory) / "trails.db"), directory)
            with patch.object(DARTS, "export3d_store", store), patch.object(DARTS, "query_trail_rows", return_value=[row, row2]) as query:
                DARTS.DARTSAPIHandler._handle_export_trails_geojson_3d(response, {})
            payload = json.loads(response.body)
            saved = Path(directory) / "3DSPAT_SAVES" / payload["metadata"]["filename"]
            self.assertEqual(json.loads(saved.read_text()), payload)
            store.close()
        query.assert_called_once_with(1000, 2000, icao="ALT001", apply_backstop=False)
        self.assertEqual(response.kwargs["content_type"], "application/geo+json")
        self.assertIn('3DSPAT_01JAN70_1000_0000_0000.geojson', response.kwargs["extra_headers"]["Content-Disposition"])
        self.assertEqual(json.loads(response.body)["features"][0]["geometry"]["coordinates"],
                         [[151.0, -33.0, -2.1], [151.0001, -33.0001, 0]])

    def test_stationary_altitude_tcas_squawk_and_ground_changes_are_recorded(self):
        now = 8_000_000
        snapshot = self._snapshot("STATE1", -33, 151, now)
        self._persist(DARTS.build_trail_records(snapshot, now, self.cfg))
        for field, value in (("alt", "30100"), ("tcas_ra", "RA ALERT"), ("squawk", "0070"), ("air_ground", "GROUND")):
            now += 1000
            data = snapshot["STATE1"]
            data["_lat_update_time"] = now / 1000
            data[field] = value
            data[f"_{field}_update_time"] = now / 1000
            records = DARTS.build_trail_records(snapshot, now, self.cfg)
            self.assertEqual(len(records), 1, field)
            self._persist(records)
        self.assertEqual(len(DARTS.query_trail_rows(8_000_000, now)), 5)

    def test_telemetry_numeric_freshness_and_unobserved_tcas(self):
        now = 9_000_000
        data = self._snapshot("FRESH1", -33, 151, now)["FRESH1"]
        data.update(speed="123.5", track="90", heading="180", vert_rate="-640",
                    roll="NaN", tcas_ra="CLEAN", squawk="0070")
        for field in ("speed", "track", "heading", "vert_rate", "roll", "squawk"):
            data[f"_{field}_update_time"] = now / 1000 - 1
        record = DARTS.build_trail_records({"FRESH1": data}, now, self.cfg)[0]
        telemetry = dict(zip(DARTS.TRAIL_TELEMETRY_COLUMNS, record[11:]))
        self.assertEqual(telemetry["groundspeed_kt"], 123.5)
        self.assertEqual(telemetry["vert_rate_fpm"], -640)
        self.assertEqual(telemetry["squawk"], "0070")
        self.assertIsNone(telemetry["tcas_ra"])
        self.assertIsNone(telemetry["roll_deg"])
        data["_track_update_time"] = now / 1000 - 9
        data["_heading_update_time"] = now / 1000 - 13
        data["_speed_update_time"] = now / 1000 - 13
        stale = dict(zip(DARTS.TRAIL_TELEMETRY_COLUMNS, DARTS._trail_telemetry(data, now)))
        self.assertIsNone(stale["track_deg_true"])
        self.assertIsNone(stale["heading_deg_mag"])
        self.assertIsNone(stale["groundspeed_kt"])

    def test_update_aircraft_tracks_actual_observations_and_snapshot_timestamps(self):
        with patch.object(DARTS, "aircraft_state", {}), patch.object(DARTS, "queue_telemetry_delta"), patch.object(DARTS, "trigger_sound"), patch.object(DARTS.time, "time", return_value=100):
            DARTS.update_aircraft("OBS001", "speed", 0)
            initial = DARTS.snapshot_trail_aircraft_state()["OBS001"]
            self.assertEqual(initial["_speed_update_time"], 100)
            self.assertEqual(initial["_tcas_ra_update_time"], 0)
            DARTS.update_aircraft("OBS001", "tcas_ra", "CLEAN")
            observed = DARTS.snapshot_trail_aircraft_state()["OBS001"]
            self.assertEqual(observed["_tcas_ra_update_time"], 100)
            telemetry = dict(zip(DARTS.TRAIL_TELEMETRY_COLUMNS, DARTS._trail_telemetry(observed, 100000)))
            self.assertEqual(telemetry["groundspeed_kt"], 0)
            self.assertEqual(telemetry["tcas_ra"], "CLEAN")

    def test_store_migration_leaves_historical_telemetry_null(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "legacy.db")
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE trail_points (id INTEGER PRIMARY KEY, icao TEXT, ts_ms INTEGER, lat REAL, lon REAL, altitude TEXT, on_ground INTEGER, callsign TEXT, source_label TEXT, receiver_id TEXT, marker_type TEXT)")
            conn.execute("INSERT INTO trail_points VALUES (1,'OLD001',1000,-33,151,'1200',0,'OLD','A','A',NULL)")
            conn.commit()
            conn.close()
            old_store = DARTS.export3d_store
            memory_conn = DARTS.trail_db_conn
            try:
                with patch.object(DARTS, "get_trail_db_path", return_value=db_path), patch.object(DARTS, "BASE_DIR", directory):
                    DARTS.init_trail_store()
                    rows = DARTS.query_trail_rows(0, 2000, apply_backstop=False)
                    self.assertEqual(rows[0][11:], (None,) * len(DARTS.TRAIL_TELEMETRY_COLUMNS))
                    self.assertEqual(rows[0][5], "1200")
                    DARTS.trail_db_conn.close()
                    DARTS.export3d_store.close()
                    DARTS.init_trail_store()
                    self.assertEqual(len(DARTS.query_trail_rows(0, 2000)), 1)
            finally:
                DARTS.trail_db_conn.close()
                DARTS.export3d_store.close()
                DARTS.trail_db_conn = memory_conn
                DARTS.export3d_store = old_store

    def test_runtime_auto_config_defaults_and_environment(self):
        with patch.object(DARTS.os.path, "exists", return_value=False), patch.dict(DARTS.os.environ, {}, clear=True):
            config = DARTS.load_runtime_config()
        self.assertEqual(config["3DGEO_AUTO_EXPORT_ENABLE"], 1)
        self.assertEqual(config["3DGEO_AUTO_EXPORT_DAILY_TIME"], "2400")
        with patch.dict(DARTS.os.environ, {"EHS_3DGEO_AUTO_EXPORT_ENABLE": "0", "EHS_3DGEO_AUTO_EXPORT_DAILY_TIME": "2211"}):
            config = DARTS.load_runtime_config()
        self.assertEqual(config["3DGEO_AUTO_EXPORT_ENABLE"], 0)
        self.assertEqual(config["3DGEO_AUTO_EXPORT_DAILY_TIME"], "2211")

    def test_pruning_protects_25_hour_auto_window(self):
        now = 100_000_000
        ts = now - 25 * 3600 * 1000
        self._persist([("KEEP01", ts, -33, 151, "100", 0, None, "A", "A", None, "keep")])
        cfg = copy.deepcopy(self.cfg)
        cfg["persistence"]["retention_hours"] = 24
        with patch.object(DARTS, "get_trail_config_snapshot", return_value=cfg), patch.dict(DARTS.RUNTIME_CONFIG, {"3DGEO_AUTO_EXPORT_ENABLE": 1}):
            DARTS.prune_trail_records(now)
        self.assertEqual(len(DARTS.query_trail_rows(ts, now)), 1)

    def test_pruning_cannot_delete_pending_auto_window_after_sleep(self):
        now = 200_000_000
        ts = now - 30 * 3600 * 1000
        self._persist([("KEEP02", ts, -33, 151, "100", 0, None, "A", "A", None, "keep2")])
        with patch.object(DARTS, "auto_export_pending_from_ms", ts), patch.dict(DARTS.RUNTIME_CONFIG, {"3DGEO_AUTO_EXPORT_ENABLE": 1}):
            DARTS.prune_trail_records(now)
        self.assertEqual(len(DARTS.query_trail_rows(ts, now)), 1)

    def test_same_timestamp_altitude_change_has_distinct_event_key(self):
        now = 10_000_000
        snapshot = self._snapshot("SAME01", -33, 151, now)
        self._persist(DARTS.build_trail_records(snapshot, now, self.cfg))
        snapshot["SAME01"]["alt"] = "30100"
        self._persist(DARTS.build_trail_records(snapshot, now, self.cfg))
        self.assertEqual(len(DARTS.query_trail_rows(now, now, apply_backstop=False)), 2)

    def test_decoder_preserves_zero_kinematic_values(self):
        decoded = {"icao": "ZERO01", "altitude": 0, "groundspeed": 0,
                   "true_airspeed": 0, "track": 0, "magnetic_heading": 0}
        with patch.object(DARTS.pipeline, "decode", return_value=decoded), patch.object(DARTS, "handle_entry_gate"), patch.object(DARTS, "update_aircraft") as update:
            DARTS.process_frame(bytes([0x33]) + bytes(20))
        updates = {(call.args[1], call.args[2]) for call in update.call_args_list}
        for field in ("alt", "speed", "tas", "track", "heading"):
            self.assertIn((field, 0), updates)


if __name__ == "__main__":
    unittest.main()
