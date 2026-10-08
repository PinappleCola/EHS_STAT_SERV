import importlib.util
import json
import shutil
import sqlite3
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.request import urlopen


_SPEC = importlib.util.spec_from_file_location(
    "trail_export3d_under_test", Path(__file__).resolve().parents[1] / "trail_export3d.py")
EXPORT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(EXPORT)
UTC = timezone.utc


def row(row_id, ts, altitude=10000, ground=0, icao="ABC123", lat=-33, lon=151,
        marker=None, telemetry=False):
    if lon == 151:
        lon += ts / 1000000
    result = (row_id, icao, ts, lat, lon, altitude, ground, "TEST123", "ADSB", "RX1", marker)
    if telemetry:
        result += (240, 180, 175, -500, -490, -510, 2, 250, 230, 0.6, "CLEAN", "0123", -18, 1.2)
    return result


class BuilderTests(unittest.TestCase):
    def test_pairwise_start_sample_telemetry_and_units(self):
        rows = [row(3, 3000, 10200, telemetry=True), row(1, 1000, telemetry=True),
                row(2, 2000, 10100, telemetry=True)]
        rows[1] = rows[1][:11] + (200,) + rows[1][12:]
        payload = EXPORT.build_geojson3d(rows)
        self.assertEqual(payload["type"], "FeatureCollection")
        self.assertEqual(len(payload["features"]), 2)
        first, second = payload["features"]
        self.assertEqual(first["geometry"]["coordinates"], [[151.001, -33., 3048.], [151.002, -33., 3078.5]])
        self.assertEqual(first["properties"]["groundspeed_kt"], 200)
        self.assertEqual(second["properties"]["groundspeed_kt"], 240)
        for column in EXPORT.TRAIL_TELEMETRY_COLUMNS:
            self.assertIn(column, first["properties"])
        self.assertEqual(first["properties"]["squawk"], "0123")
        self.assertFalse(first["properties"]["tcas_active"])
        self.assertEqual(first["properties"]["start_ts"], 1)
        self.assertEqual(first["properties"]["altitude_ft"], 10050)
        self.assertEqual(first["properties"]["altitude_start_ft"], 10000)
        self.assertEqual(first["properties"]["altitude_end_ft"], 10100)
        self.assertEqual(first["id"], "ABC123:1000:0")
        self.assertEqual(first["properties"]["duration_s"], 1)
        self.assertIsInstance(first["properties"]["start_ts"], int)
        expected = {
            "icao", "callsign", "start_time", "end_time", "start_ts", "duration_s",
            "altitude_ft", "altitude_start_ft", "altitude_end_ft",
            "tcas_active", "emergency", "on_ground", "segment_index", "trail_id",
            "source_label", "receiver_id",
        } | set(EXPORT.TRAIL_TELEMETRY_COLUMNS)
        self.assertEqual(set(first["properties"]), expected)
        self.assertEqual(first["properties"]["segment_index"], 0)
        self.assertEqual(second["properties"]["segment_index"], 1)
        self.assertEqual(first["properties"]["trail_id"], second["properties"]["trail_id"])
        self.assertTrue(all(not isinstance(v, (list, dict)) for v in first["properties"].values()))
        self.assertEqual(payload["metadata"]["units"]["altitude_ft"], "ft")
        self.assertEqual(payload["metadata"]["units"]["z"], "m (pressure altitude converted)")
        self.assertEqual(payload["metadata"]["schema"], "darts-3dspat-v1")
        self.assertIsNone(payload["metadata"]["serial"])
        self.assertFalse(payload["metadata"]["auto"])
        self.assertIsNone(payload["metadata"]["filename"])
        self.assertEqual(set(payload["metadata"]), {
            "schema", "generated_at", "units", "timezone", "serial", "auto", "filename",
            "feature_count", "data_first_ms", "data_last_ms", "window_from", "window_to",
        })
        self.assertTrue({"coordinates", "ts_ms", "end_ts", "altitude", "altitude_m"}.isdisjoint(
            payload["metadata"]["units"]))
        self.assertTrue(payload["metadata"]["generated_at"].endswith("Z"))
        json.dumps(payload, allow_nan=False)

    def test_legacy_rows_duplicate_identity_and_independent_aircraft(self):
        payload = EXPORT.build_geojson3d([
            row(1, 1000), row(5, 1000), row(2, 2000),
            row(3, 1000, icao="DEF456"), row(4, 2000, icao="DEF456")])
        self.assertEqual(len(payload["features"]), 2)
        self.assertEqual([f["properties"]["icao"] for f in payload["features"]], ["ABC123", "DEF456"])
        self.assertTrue(all(payload["features"][0]["properties"][c] is None
                            for c in EXPORT.TRAIL_TELEMETRY_COLUMNS))

    def test_distinct_altitude_or_coordinate_not_deduplicated(self):
        payload = EXPORT.build_geojson3d([
            row(1, 1000), row(2, 1000, altitude=11000), row(3, 1000, lat=-34)])
        self.assertEqual(len(payload["features"]), 2)

    def test_marker_before_point_breaks_same_timestamp_and_changes_trail(self):
        payload = EXPORT.build_geojson3d([
            row(1, 1000), row(2, 2000), row(3, 3000), row(4, 4000),
            row(99, 3000, altitude=None, lat=None, lon=None, marker="gap_break")])
        first, second = payload["features"]
        self.assertEqual(first["properties"]["end_time"], "1970-01-01T00:00:02.000Z")
        self.assertEqual(second["properties"]["start_ts"], 3)
        self.assertNotEqual(first["properties"]["trail_id"], second["properties"]["trail_id"])
        self.assertEqual(second["properties"]["segment_index"], 0)
        self.assertEqual(second["id"], "ABC123:3000:0")

    def test_invalid_airborne_altitudes_break_instead_of_becoming_ground(self):
        for value in (None, "?", float("nan"), float("inf"), ""):
            with self.subTest(altitude=value):
                payload = EXPORT.build_geojson3d([
                    row(1, 1000), row(2, 2000, value), row(3, 3000), row(4, 4000)])
                self.assertEqual(len(payload["features"]), 1)
                self.assertEqual(payload["features"][0]["properties"]["start_ts"], 3)

    def test_ground_uses_zero_and_airborne_negative_altitude_is_valid(self):
        features = EXPORT.build_geojson3d([
            row(1, 1000, None, 1), row(2, 2000, "ground", 1), row(3, 3000, -100)])["features"]
        self.assertEqual(features[0]["geometry"]["coordinates"][0][2], 0)
        self.assertEqual(features[1]["geometry"]["coordinates"][1][2], -30.5)

    def test_bad_coordinates_break_adjacency(self):
        for coordinate in (None, float("nan"), 999):
            with self.subTest(coordinate=coordinate):
                payload = EXPORT.build_geojson3d([
                    row(1, 1000), row(2, 2000, lat=coordinate), row(3, 3000)])
                self.assertEqual(payload["features"], [])

    def test_empty_single_point_and_marker_only(self):
        for rows in ([], [row(1, 1000)], [row(1, 1000, marker="gap_break")]):
            self.assertEqual(EXPORT.build_geojson3d(rows)["features"], [])

    def test_zero_length_coordinates_omitted_and_latest_sample_carried_forward(self):
        features = EXPORT.build_geojson3d([
            row(1, 1000, lon=152), row(2, 2000, lon=152), row(3, 3000, lon=153)])["features"]
        self.assertEqual(len(features), 1)
        self.assertEqual(features[0]["id"], "ABC123:2000:0")

    def test_ground_literal_and_boolean_flags_emergency(self):
        first = list(row(1, 1000, "GROUND", None, telemetry=True))
        first[22] = "7700"
        feature = EXPORT.build_geojson3d([tuple(first), row(2, 2000, 100)])["features"][0]
        self.assertEqual(feature["geometry"]["coordinates"][0][2], 0)
        self.assertEqual(feature["properties"]["altitude_start_ft"], 0)
        self.assertIsNone(feature["properties"]["on_ground"])
        self.assertTrue(feature["properties"]["emergency"])
        feature = EXPORT.build_geojson3d([row(1, 1000, ground=1), row(2, 2000)])["features"][0]
        self.assertIs(feature["properties"]["on_ground"], True)

    def test_raw_altitude_changes_smaller_than_z_precision_are_retained(self):
        features = EXPORT.build_geojson3d([
            row(1, 1000, altitude=100, lon=152),
            row(2, 2000, altitude=100.01, lon=152)])["features"]
        self.assertEqual(len(features), 1)
        self.assertEqual(features[0]["geometry"]["coordinates"][0],
                         features[0]["geometry"]["coordinates"][1])
        self.assertEqual(features[0]["properties"]["altitude_start_ft"], 100)
        self.assertEqual(features[0]["properties"]["altitude_end_ft"], 100.01)

    def test_invalid_numeric_telemetry_null_and_tcas_unknown_or_active(self):
        first = list(row(1, 1000, telemetry=True))
        first[11] = float("nan")
        first[21] = None
        features = EXPORT.build_geojson3d([tuple(first), row(2, 2000, telemetry=True)])["features"]
        self.assertIsNone(features[0]["properties"]["groundspeed_kt"])
        self.assertIsNone(features[0]["properties"]["tcas_active"])
        first[21] = "RA CLB"
        features = EXPORT.build_geojson3d([tuple(first), row(2, 2000)])["features"]
        self.assertTrue(features[0]["properties"]["tcas_active"])

    def test_tcas_unknown_strings_are_null_not_false_or_active(self):
        for value in ("unknown", "UNKNOWN", "----", "", None):
            with self.subTest(value=value):
                first = list(row(1, 1000, telemetry=True))
                first[21] = value
                properties = EXPORT.build_geojson3d([
                    tuple(first), row(2, 2000)])["features"][0]["properties"]
                self.assertIsNone(properties["tcas_ra"])
                self.assertIsNone(properties["tcas_active"])


class FilenameTests(unittest.TestCase):
    def test_sydney_timestamp_english_month_duration_serial_auto(self):
        first = int(datetime(2026, 1, 1, 0, 15, tzinfo=UTC).timestamp() * 1000)
        self.assertEqual(EXPORT.format_export_filename(first, first + 90 * 60000, 10),
                         "3DSPAT_01JAN26_1115_0090_000A.geojson")
        self.assertEqual(EXPORT.format_export_filename(first, first + 60 * 1000, 65535, True),
                         "AUTO_3DSPAT_01JAN26_1115_0001_FFFF.geojson")

    def test_duration_clamps_and_winter_offset(self):
        first = int(datetime(2026, 7, 1, 0, tzinfo=UTC).timestamp() * 1000)
        self.assertIn("_1000_", EXPORT.format_export_filename(first, first, 0))
        self.assertIn("_9999_", EXPORT.format_export_filename(first, first + 20000 * 60000, 0))
        self.assertIn("_0000_", EXPORT.format_export_filename(first, first - 60000, 0))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(__file__).resolve().parent / (".export3d-tests-" + uuid.uuid4().hex)
        self.directory.mkdir()
        self.database = self.directory / "db" / "trails.sqlite"
        self.base = self.directory / "nested"
        self.output = self.base / "3DSPAT_SAVES"
        self.store = EXPORT.Export3DStore(self.database, self.base)
        self.query = Mock(return_value=[row(1, 1000), row(2, 2000)])
        self.builder = Mock(side_effect=lambda rows, apply_backstop: EXPORT.build_geojson3d(rows))

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.directory)

    def logs(self):
        with sqlite3.connect(self.database) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(r) for r in connection.execute("SELECT * FROM export_log ORDER BY id")]

    def test_saved_json_query_builder_contract_and_metadata(self):
        payload, filename = self.store.export(1000, 2000, self.query, self.builder, icao="ABC123")
        self.query.assert_called_once_with(1000, 2000, icao="ABC123", apply_backstop=False)
        self.builder.assert_called_once_with(self.query.return_value, apply_backstop=True)
        self.assertEqual(json.loads((self.output / filename).read_text()), payload)
        self.assertEqual(payload["metadata"]["serial"], "0000")
        self.assertFalse(payload["metadata"]["auto"])
        self.assertEqual(payload["metadata"]["filename"], filename)
        self.assertEqual(set(payload["metadata"]), {
            "schema", "generated_at", "units", "timezone", "serial", "auto", "filename",
            "feature_count", "aircraft_count", "data_first_ms", "data_last_ms",
            "window_from", "window_to",
        })
        self.assertEqual(self.logs()[0]["status"], "ok")
        self.assertEqual(self.logs()[0]["feature_count"], 1)
        self.assertEqual(self.logs()[0]["aircraft_count"], 1)
        self.assertEqual(self.logs()[0]["window_from_ms"], 1000)
        self.assertEqual(self.logs()[0]["data_last_ms"], 2000)
        self.assertEqual(self.logs()[0]["serial_hex"], "0000")
        self.assertEqual(self.logs()[0]["path"], str(self.output / filename))
        self.assertTrue(self.logs()[0]["created_at_utc"].endswith("Z"))
        self.assertEqual(payload["metadata"]["window_from"], "1970-01-01T00:00:01.000Z")
        self.assertEqual(len(list(self.output.iterdir())), 1)

    def test_serial_persistence_across_store_recreation_and_log_deletion(self):
        self.store.export(1000, 2000, self.query, self.builder)
        self.store.close()
        with sqlite3.connect(self.database) as connection:
            connection.execute("DELETE FROM export_log")
        self.store = EXPORT.Export3DStore(self.database, self.base)
        payload, _ = self.store.export(1000, 2000, self.query, self.builder)
        self.assertEqual(payload["metadata"]["serial"], "0001")

    def test_serial_wraps_after_ffff(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE export_serial SET next_serial = 65535")
        first, _ = self.store.export(1000, 2000, self.query, self.builder)
        second, _ = self.store.export(1000, 2000, self.query, self.builder)
        self.assertEqual([first["metadata"]["serial"], second["metadata"]["serial"]], ["FFFF", "0000"])

    def test_empty_auto_no_serial_no_file_manual_empty_saves(self):
        self.query.return_value = []
        payload, filename = self.store.export(1000, 2000, self.query, self.builder, is_auto=True)
        self.assertIsNone(filename)
        self.assertIsNone(payload["metadata"]["serial"])
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(list((self.base / "AUTO_3DSPAT_SAVES").iterdir()), [])
        self.assertEqual(self.logs()[0]["status"], "empty")
        self.assertEqual(self.logs()[0]["serial"], -1)
        self.assertEqual(self.logs()[0]["serial_hex"], "")
        self.assertEqual(self.logs()[0]["filename"], "")
        self.assertEqual(self.logs()[0]["path"], "")
        payload, filename = self.store.export(1000, 2000, self.query, self.builder)
        self.assertEqual(payload["metadata"]["serial"], "0000")
        self.assertTrue((self.output / filename).exists())

    def test_populated_auto_saves_and_consumes_serial(self):
        payload, filename = self.store.export(1000, 2000, self.query, self.builder, is_auto=True)
        self.assertEqual(payload["metadata"]["serial"], "0000")
        self.assertTrue(payload["metadata"]["auto"])
        self.assertNotIn("is_auto", payload["metadata"])
        self.assertTrue(filename.startswith("AUTO_"))
        self.assertEqual(self.logs()[0]["serial"], 0)
        self.assertTrue((self.base / "AUTO_3DSPAT_SAVES" / filename).exists())

    def test_filename_uses_sample_window_not_requested_window(self):
        self.query.return_value = [row(1, 60000), row(2, 180000)]
        _, filename = self.store.export(0, 3600000, self.query, self.builder)
        self.assertEqual(filename, EXPORT.format_export_filename(60000, 180000, 0))

    def test_empty_manual_uses_request_start_and_zero_duration(self):
        self.query.return_value = []
        _, filename = self.store.export(0, 3600000, self.query, self.builder)
        self.assertEqual(filename, EXPORT.format_export_filename(0, 0, 0))
        self.assertEqual(self.logs()[0]["status"], "empty")

    def test_singleton_auto_observation_saves_even_without_altitude_or_feature(self):
        self.query.return_value = [row(1, 123456, altitude=None)]
        payload, filename = self.store.export(
            0, 3600000, self.query, self.builder, is_auto=True)
        self.assertEqual(payload["features"], [])
        self.assertEqual(payload["metadata"]["serial"], "0000")
        self.assertEqual(filename, EXPORT.format_export_filename(123456, 123456, 0, True))
        self.assertTrue((self.base / "AUTO_3DSPAT_SAVES" / filename).exists())
        log = self.logs()[0]
        self.assertEqual(log["status"], "ok")
        self.assertEqual(log["feature_count"], 0)
        self.assertEqual(log["aircraft_count"], 1)
        self.assertEqual(log["data_first_ms"], 123456)
        self.assertEqual(log["data_last_ms"], 123456)
        self.assertEqual(log["serial"], 0)
        self.query.return_value = [row(2, 1000), row(3, 2000)]
        payload, _ = self.store.export(0, 3600000, self.query, self.builder)
        self.assertEqual(payload["metadata"]["serial"], "0001")

    def test_first_last_data_rows_include_isolated_unknown_altitude_exclude_markers(self):
        self.query.return_value = [
            row(1, 60000, altitude=None), row(2, 120000), row(3, 180000),
            row(4, 240000, altitude=None), row(5, 300000, marker="gap_break"),
            row(6, 0, marker="jump_break"), row(7, 360000, lat=None),
        ]
        payload, filename = self.store.export(0, 3600000, self.query, self.builder)
        self.assertEqual(len(payload["features"]), 1)
        self.assertEqual(filename, EXPORT.format_export_filename(60000, 240000, 0))
        self.assertEqual(self.logs()[0]["data_first_ms"], 60000)
        self.assertEqual(self.logs()[0]["data_last_ms"], 240000)

    def test_auto_marker_only_window_skips_save_and_serial(self):
        self.query.return_value = [row(1, 1000, marker="gap_break")]
        _, filename = self.store.export(0, 3600000, self.query, self.builder, is_auto=True)
        self.assertIsNone(filename)
        self.assertEqual(self.logs()[0]["serial"], -1)
        self.assertEqual(self.logs()[0]["status"], "empty")
        self.assertEqual(list((self.base / "AUTO_3DSPAT_SAVES").iterdir()), [])

    def test_automatic_25_hour_dst_window_is_not_clamped_to_manual_24_hours(self):
        end = EXPORT.scheduled_instant(date(2026, 4, 6))
        start = EXPORT.previous_scheduled_run(end)
        from_ms, to_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
        self.query.return_value = [
            row(1, from_ms, lon=151.1), row(2, to_ms, lon=151.2)]
        payload, filename = self.store.export(
            from_ms, to_ms, self.query, self.builder, is_auto=True)
        self.assertEqual(to_ms - from_ms, 25 * 3600000)
        self.query.assert_called_once_with(
            from_ms, to_ms, icao=None, apply_backstop=False)
        self.assertEqual(payload["metadata"]["window_from"], EXPORT._iso_ms(from_ms))
        self.assertEqual(payload["metadata"]["window_to"], EXPORT._iso_ms(to_ms))
        self.assertIn("_1500_", filename)
        self.assertEqual(self.logs()[0]["window_to_ms"] - self.logs()[0]["window_from_ms"],
                         25 * 3600000)
        self.assertEqual(self.logs()[0]["status"], "ok")

    def test_query_and_builder_errors_logged_and_manual_serial_consumed(self):
        self.query.side_effect = RuntimeError("query failed")
        with self.assertLogs(EXPORT.LOGGER, level="ERROR"), self.assertRaisesRegex(RuntimeError, "query failed"):
            self.store.export(1000, 2000, self.query, self.builder)
        self.query.side_effect = None
        self.builder.side_effect = ValueError("build failed")
        with self.assertLogs(EXPORT.LOGGER, level="ERROR"), self.assertRaisesRegex(ValueError, "build failed"):
            self.store.export(1000, 2000, self.query, self.builder)
        logs = self.logs()
        self.assertEqual([r["status"] for r in logs], ["error", "error"])
        self.assertEqual([r["serial"] for r in logs], [0, 1])
        self.assertIn("query failed", logs[0]["error"])
        self.assertIn("build failed", logs[1]["error"])
        self.assertEqual(list(self.output.iterdir()), [])

    def test_auto_query_failure_logged_without_allocating_serial(self):
        self.query.side_effect = RuntimeError("offline")
        with self.assertLogs(EXPORT.LOGGER, level="ERROR"), self.assertRaises(RuntimeError):
            self.store.export(1000, 2000, self.query, self.builder, is_auto=True)
        self.assertEqual(self.logs()[0]["status"], "error")
        self.assertEqual(self.logs()[0]["serial"], -1)

    def test_invalid_window_logged_without_query(self):
        with self.assertLogs(EXPORT.LOGGER, level="ERROR"), self.assertRaises(ValueError):
            self.store.export(2000, 1000, self.query, self.builder)
        self.query.assert_not_called()
        self.assertEqual(self.logs()[0]["status"], "error")

    def test_atomic_replace_failure_preserves_existing_and_cleans_partial(self):
        filename = EXPORT.format_export_filename(1000, 2000, 0)
        self.output.mkdir(parents=True, exist_ok=True)
        destination = self.output / filename
        destination.write_text("previous export")
        with patch.object(EXPORT.os, "replace", side_effect=OSError("disk failed")):
            with self.assertLogs(EXPORT.LOGGER, level="ERROR"), self.assertRaisesRegex(OSError, "disk failed"):
                self.store.export(1000, 2000, self.query, self.builder)
        self.assertEqual(destination.read_text(), "previous export")
        self.assertEqual(list(self.output.iterdir()), [destination])
        self.assertEqual(self.logs()[0]["status"], "error")

    def test_json_failure_logged_and_partial_removed(self):
        self.builder.side_effect = None
        self.builder.return_value = {"features": [], "metadata": {"bad": float("nan")}}
        with self.assertLogs(EXPORT.LOGGER, level="ERROR"), self.assertRaises(ValueError):
            self.store.export(1000, 2000, self.query, self.builder)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(self.logs()[0]["status"], "error")

    def test_audit_schema_exact_required_columns_and_constraints(self):
        expected = {
            "id", "serial", "serial_hex", "filename", "path", "is_auto", "created_at_utc",
            "window_from_ms", "window_to_ms", "data_first_ms", "data_last_ms",
            "feature_count", "aircraft_count", "status", "error",
        }
        with sqlite3.connect(self.database) as connection:
            columns = connection.execute("PRAGMA table_info(export_log)").fetchall()
        self.assertEqual({r[1] for r in columns}, expected)
        required = {"serial", "serial_hex", "filename", "path", "is_auto", "created_at_utc", "status"}
        self.assertTrue(all(r[3] for r in columns if r[1] in required))

    def test_concurrent_stores_and_threads_reserve_unique_serials(self):
        other = EXPORT.Export3DStore(self.database, self.base)
        try:
            def perform(index):
                store = self.store if index % 2 else other
                payload, filename = store.export(
                    1000, 2000, lambda *a, **kw: [row(1, 1000), row(2, 2000)],
                    lambda rows, **kw: EXPORT.build_geojson3d(rows), is_auto=bool(index % 3))
                return int(payload["metadata"]["serial"], 16), filename
            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(perform, range(24)))
            self.assertEqual(sorted(r[0] for r in results), list(range(24)))
            self.assertEqual(len(set(r[1] for r in results)), 24)
            self.assertEqual(len(self.logs()), 24)
            self.assertTrue(all(r["status"] == "ok" for r in self.logs()))
            self.assertEqual(len(list(self.output.iterdir())) +
                             len(list((self.base / "AUTO_3DSPAT_SAVES").iterdir())), 24)
        finally:
            other.close()


class SchedulingTests(unittest.TestCase):
    def test_time_normalization_and_invalid_default_warning(self):
        for text, expected in (("2400", (0, 0)), ("0000", (0, 0)), ("0230", (2, 30)),
                               (" 1215 ", (12, 15)), (0, (0, 0)), (930, (9, 30)),
                               (2400, (0, 0))):
            self.assertEqual(EXPORT.parse_daily_time(text), expected)
        for value in ("2401", "2360", "2500", "foo", None, "１２３４", "0:000", True,
                      "09:30", "00:00", "930", (2, 30), 2401, 1260):
            with self.assertLogs(EXPORT.LOGGER, level="WARNING"):
                self.assertEqual(EXPORT.parse_daily_time(value), (0, 0))

    def test_2400_and_0000_are_same_midnight_on_local_wall_date(self):
        self.assertEqual(EXPORT.scheduled_instant(date(2026, 1, 1)),
                         datetime(2025, 12, 31, 13, tzinfo=UTC))
        self.assertEqual(EXPORT.scheduled_instant(date(2026, 1, 1), "2400"),
                         EXPORT.scheduled_instant(date(2026, 1, 1), "0000"))

    def test_spring_nonexistent_wall_time_moves_to_first_valid_minute(self):
        self.assertEqual(EXPORT.scheduled_instant(date(2026, 10, 4), "0230"),
                         datetime(2026, 10, 3, 16, tzinfo=UTC))
        self.assertEqual(EXPORT.scheduled_instant(date(2026, 10, 4), "0200"),
                         datetime(2026, 10, 3, 16, tzinfo=UTC))

    def test_autumn_ambiguous_wall_time_uses_first_fold(self):
        self.assertEqual(EXPORT.scheduled_instant(date(2026, 4, 5), "0230"),
                         datetime(2026, 4, 4, 15, 30, tzinfo=UTC))

    def test_next_strictly_after_now_and_previous_calendar_day(self):
        for time in ("2400", "0000", "0230", "1200"):
            current = EXPORT.scheduled_instant(date(2026, 1, 2), time)
            self.assertEqual(EXPORT.next_scheduled_run(current, time),
                             EXPORT.scheduled_instant(date(2026, 1, 3), time))
            self.assertEqual(EXPORT.next_scheduled_run(current - timedelta(microseconds=1), time), current)
            self.assertEqual(EXPORT.previous_scheduled_run(current, time),
                             EXPORT.scheduled_instant(date(2026, 1, 1), time))

    def test_dst_day_windows_have_23_or_25_hours(self):
        spring = EXPORT.scheduled_instant(date(2026, 10, 5))
        autumn = EXPORT.scheduled_instant(date(2026, 4, 6))
        self.assertEqual((spring - EXPORT.previous_scheduled_run(spring)).total_seconds(), 23 * 3600)
        self.assertEqual((autumn - EXPORT.previous_scheduled_run(autumn)).total_seconds(), 25 * 3600)

    def test_schedule_rejects_naive_now(self):
        with self.assertRaises(ValueError):
            EXPORT.next_scheduled_run(datetime(2026, 1, 1))
        with self.assertRaises(ValueError):
            EXPORT.previous_scheduled_run(datetime(2026, 1, 1))

    def run_scheduler(self, initial, wakeups, callback):
        class FakeStop:
            def __init__(self):
                self.now = initial
                self.stopped = False
                self.waits = []
                self.wakeups = iter(wakeups)

            def is_set(self):
                return self.stopped

            def wait(self, timeout):
                self.waits.append(timeout)
                try:
                    self.now = next(self.wakeups)
                except StopIteration:
                    self.stopped = True
                return self.stopped
        stop = FakeStop()
        EXPORT.run_daily_exports(callback, stop_event=stop, clock=lambda: stop.now)
        self.assertTrue(all(0 <= delay <= 30 for delay in stop.waits))

    def test_scheduler_no_immediate_backfill_exports_at_boundary(self):
        current = EXPORT.scheduled_instant(date(2026, 1, 1))
        calls = Mock()
        self.run_scheduler(current - timedelta(seconds=10), [current], calls)
        calls.assert_called_once_with(
            int(EXPORT.previous_scheduled_run(current).timestamp() * 1000),
            int(current.timestamp() * 1000))
        calls.reset_mock()
        self.run_scheduler(current, [], calls)
        calls.assert_not_called()

    def test_delayed_wakeup_skips_missed_windows(self):
        current = EXPORT.scheduled_instant(date(2026, 1, 1))
        latest = EXPORT.scheduled_instant(date(2026, 1, 4))
        calls = Mock()
        self.run_scheduler(current - timedelta(seconds=10), [latest + timedelta(hours=1)], calls)
        calls.assert_called_once_with(
            int(EXPORT.previous_scheduled_run(latest).timestamp() * 1000),
            int(latest.timestamp() * 1000))

    def test_callback_error_continues_and_clock_rollback_no_duplicates(self):
        current = EXPORT.scheduled_instant(date(2026, 1, 1))
        tomorrow = EXPORT.next_scheduled_run(current)
        calls = Mock(side_effect=RuntimeError("test"))
        with self.assertLogs(EXPORT.LOGGER, level="ERROR"):
            self.run_scheduler(current - timedelta(seconds=10), [
                current, current - timedelta(hours=2), current, tomorrow], calls)
        self.assertEqual(calls.call_count, 2)
        self.assertEqual([c.args[1] for c in calls.call_args_list],
                         [int(current.timestamp() * 1000), int(tomorrow.timestamp() * 1000)])

    def test_already_stopped_event_does_not_export(self):
        stop = threading.Event()
        stop.set()
        calls = Mock()
        EXPORT.run_daily_exports(calls, stop_event=stop)
        calls.assert_not_called()


class ManualHTTPSmokeTests(unittest.TestCase):
    def test_receiver_free_http_download_matches_atomic_saved_body_and_header(self):
        spec = importlib.util.spec_from_file_location(
            "darts_under_export_http_smoke", Path(__file__).resolve().parents[1] / "darts.py")
        darts = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(darts)
        directory = Path(__file__).resolve().parent / (".export3d-http-" + uuid.uuid4().hex)
        directory.mkdir()
        server = None
        thread = None
        try:
            with patch.object(darts, "BASE_DIR", str(directory)), patch.object(
                    darts, "get_trail_db_path", return_value=str(directory / "trails.sqlite")):
                darts.init_trail_store()
                samples = [row(1, 1000), row(2, 2000, altitude=10100)]
                for sample in samples:
                    darts.trail_db_conn.execute(
                        "INSERT INTO trail_points "
                        "(icao, ts_ms, lat, lon, altitude, on_ground, callsign, source_label, "
                        "receiver_id, marker_type, event_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        sample[1:7] + ("TÉST123",) + sample[8:11] + (f"smoke:{sample[0]}",))
                darts.trail_db_conn.commit()
                server = ThreadingHTTPServer(("127.0.0.1", 0), darts.DARTSAPIHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                with urlopen(
                        f"http://127.0.0.1:{server.server_port}/api/trails/export3d.geojson"
                        "?from=1000&to=2000&icao=ABC123", timeout=10) as response:
                    body = response.read()
                    disposition = response.headers["Content-Disposition"]
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers["Content-Type"], "application/geo+json")
                payload = json.loads(body)
                filename = payload["metadata"]["filename"]
                self.assertIn(f'filename="{filename}"', disposition)
                self.assertEqual((directory / "3DSPAT_SAVES" / filename).read_bytes(), body)
                self.assertEqual(payload["metadata"]["schema"], "darts-3dspat-v1")
                self.assertEqual(len(payload["features"]), 1)
                self.assertEqual(payload["features"][0]["properties"]["callsign"], "TÉST123")
                self.assertEqual(payload["features"][0]["geometry"]["coordinates"][0][2], 3048)
                with sqlite3.connect(directory / "trails.sqlite") as connection:
                    self.assertEqual(connection.execute(
                        "SELECT status, feature_count FROM export_log").fetchone(), ("ok", 1))
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=10)
            if darts.export3d_store is not None:
                darts.export3d_store.close()
            if darts.trail_db_conn is not None:
                darts.trail_db_conn.close()
            shutil.rmtree(directory)


if __name__ == "__main__":
    unittest.main()
