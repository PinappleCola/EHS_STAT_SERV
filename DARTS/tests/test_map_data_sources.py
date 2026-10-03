import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def _load_darts_module():
    darts_path = Path(__file__).resolve().parents[1] / "darts.py"
    spec = importlib.util.spec_from_file_location("darts_under_test_map_sources", str(darts_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DARTS = _load_darts_module()


def _feature(name, category, lon, lat, **properties):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"name": name, "icon": category, **properties},
    }


def _collection(features):
    return {"type": "FeatureCollection", "features": features}


class MapDataSourceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.paths = {
            "airspace": str(root / "airspace.geojson"),
            "ifr_waypoints": str(root / "waypoints_ifr.geojson"),
            "vfr_waypoints": str(root / "waypoints_vfr.geojson"),
            "unclassified_waypoints": str(root / "waypoints_unclassified.geojson"),
            "audit_points": str(root / "audit_points.geojson"),
        }
        self.old_paths = DARTS.MAP_SOURCE_PATHS
        self.old_sources = DARTS.MAP_GEOJSON
        self.old_airspace = DARTS.AIRSPACE_GEOJSON
        self.old_revision = DARTS.MAP_DATA_REVISION
        self.old_audit_config = DARTS.audit_config_cache
        DARTS.MAP_SOURCE_PATHS = self.paths
        DARTS.MAP_GEOJSON = {key: _collection([]) for key in self.paths}
        DARTS.AIRSPACE_GEOJSON = DARTS.MAP_GEOJSON["airspace"]
        DARTS.audit_config_cache = {}

    def tearDown(self):
        DARTS.MAP_SOURCE_PATHS = self.old_paths
        DARTS.MAP_GEOJSON = self.old_sources
        DARTS.AIRSPACE_GEOJSON = self.old_airspace
        DARTS.MAP_DATA_REVISION = self.old_revision
        DARTS.audit_config_cache = self.old_audit_config
        self.tempdir.cleanup()

    def _write_sources(self, airspace, ifr=None, vfr=None, unknown=None, audit=None):
        contents = {
            "airspace": airspace,
            "ifr_waypoints": ifr or [],
            "vfr_waypoints": vfr or [],
            "unclassified_waypoints": unknown or [],
            "audit_points": audit or [],
        }
        for source, features in contents.items():
            Path(self.paths[source]).write_text(json.dumps(_collection(features)), encoding="utf-8")

    def test_legacy_features_migrate_without_guessing_waypoint_rules(self):
        runway = {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[1, 2], [3, 4]]}, "properties": {"name": "RWY"}}
        old_waypoint = _feature("FIX", "WAYPOINT", 1.0, 2.0)
        duplicate_waypoint = _feature("FIX", "WAYPOINT", 1.0, 2.0)
        old_audit = _feature("AUDIT-X", "AUDIT", 5.0, 6.0)
        self._write_sources([runway, old_waypoint, duplicate_waypoint, old_audit])

        DARTS.load_map_data()
        snapshot = DARTS.get_map_data_snapshot()["sources"]

        self.assertEqual(snapshot["airspace"]["features"][0]["properties"]["name"], runway["properties"]["name"])
        self.assertEqual(snapshot["audit_points"]["features"][0]["properties"]["name"], "AUDIT-X")
        self.assertEqual(snapshot["unclassified_waypoints"]["features"][0]["properties"]["flight_rules"], "UNCLASSIFIED")
        self.assertEqual(len(snapshot["unclassified_waypoints"]["features"]), 2)
        waypoint_ids = [feature["properties"]["feature_id"] for feature in snapshot["unclassified_waypoints"]["features"]]
        self.assertNotEqual(waypoint_ids[0], waypoint_ids[1])
        self.assertTrue(Path(self.paths["unclassified_waypoints"]).exists())

    def test_queries_read_only_their_sources_and_scoring_keys_are_namespaced(self):
        ifr = _feature("DUP", "WAYPOINT", 1.0, 2.0)
        vfr = _feature("DUP", "WPT", 3.0, 4.0)
        shared_ifr = _feature("COMMON", "WAYPOINT", 7.0, 8.0, fix_id="COMMON-1")
        shared_vfr = _feature("COMMON", "WAYPOINT", 7.0, 8.0, fix_id="COMMON-1")
        audit = _feature("AUDIT", "AUDIT", 5.0, 6.0)
        DARTS.MAP_GEOJSON = {
            "airspace": _collection([_feature("NOT-SCORED", "WAYPOINT", 0, 0)]),
            "ifr_waypoints": _collection([ifr, shared_ifr]),
            "vfr_waypoints": _collection([vfr, shared_vfr]),
            "unclassified_waypoints": _collection([]),
            "audit_points": _collection([audit]),
        }

        scored = DARTS.get_scored_waypoints()
        keys = {point["name"]: [] for point in scored}
        for point in scored:
            keys.setdefault(point["name"], []).append(point["key"])

        self.assertEqual(len(scored), 4)
        self.assertNotEqual(keys["DUP"][0], keys["DUP"][1])
        self.assertEqual(keys["COMMON"][0], keys["COMMON"][1])
        self.assertEqual([point["name"] for point in DARTS.get_audit_points()], ["AUDIT"])

    def test_invalid_source_does_not_replace_current_snapshot(self):
        self._write_sources([_feature("REPLACED", "LANDMARK", 3, 4)])
        DARTS.load_map_data()
        previous = DARTS.MAP_GEOJSON
        Path(self.paths["ifr_waypoints"]).write_text("[]", encoding="utf-8")

        with mock.patch("builtins.print"):
            DARTS.load_map_data()

        self.assertIs(DARTS.MAP_GEOJSON, previous)
        self.assertEqual(DARTS.MAP_GEOJSON["airspace"]["features"][0]["properties"]["name"], "REPLACED")


if __name__ == "__main__":
    unittest.main()
