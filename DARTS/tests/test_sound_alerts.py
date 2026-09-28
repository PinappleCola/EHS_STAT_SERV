import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def _load_darts_module(darts_path=None, module_name="darts_under_test_sound"):
    darts_path = Path(darts_path) if darts_path else (Path(__file__).resolve().parents[1] / "darts.py")
    spec = importlib.util.spec_from_file_location(module_name, str(darts_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DARTS = _load_darts_module()


class SoundAlertTests(unittest.TestCase):
    def test_default_sound_files_dir_is_under_darts_root(self):
        expected = Path(DARTS.__file__).resolve().parent / "SOUND_FILES"
        self.assertEqual(Path(DARTS.SOUND_FILES_DIR).resolve(), expected)

    def test_default_discovery_reads_darts_sound_root_not_repo_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            darts_root = repo_root / "DARTS"
            darts_sound_root = darts_root / "SOUND_FILES"
            repo_sound_root = repo_root / "SOUND_FILES"
            darts_root.mkdir(parents=True)
            repo_sound_root.mkdir(parents=True)
            darts_sound_root.mkdir(parents=True)

            shutil.copy2(Path(DARTS.__file__), darts_root / "darts.py")

            (darts_sound_root / "01_Darts.wav").write_bytes(b"darts")
            (repo_sound_root / "01_Repo.wav").write_bytes(b"repo")

            temp_module = _load_darts_module(darts_root / "darts.py", module_name="darts_under_test_sound_temp")
            discovered, _warnings = temp_module.discover_numbered_sound_files()

            self.assertEqual(discovered["01"]["filename"], "01_Darts.wav")
            self.assertEqual(Path(discovered["01"]["path"]).resolve().parent, darts_sound_root.resolve())

    def test_discover_numbered_sound_files_case_insensitive_and_deterministic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "01_Zulu.wav").write_bytes(b"zulu")
            (root / "01_alpha.WAV").write_bytes(b"alpha")
            (root / "02_Mixed_Case.WaV").write_bytes(b"mixed")
            (root / "1_bad.wav").write_bytes(b"bad")
            (root / "03missingunderscore.wav").write_bytes(b"bad")

            discovered, warnings = DARTS.discover_numbered_sound_files(str(root))

            self.assertEqual(discovered["01"]["filename"], "01_alpha.WAV")
            self.assertEqual(discovered["02"]["filename"], "02_Mixed_Case.WaV")
            self.assertNotIn("1", discovered)
            self.assertEqual(len(warnings), 1)
            self.assertIn("Multiple files match sound 01", warnings[0])

    def test_resolve_numbered_sound_file_rejects_invalid_ids_and_missing_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "07_Test.wav").write_bytes(b"audio")

            self.assertIsNone(DARTS.resolve_numbered_sound_file("../07", str(root)))
            self.assertIsNone(DARTS.resolve_numbered_sound_file("7", str(root)))
            self.assertIsNone(DARTS.resolve_numbered_sound_file("08", str(root)))
            self.assertEqual(DARTS.resolve_numbered_sound_file("07", str(root))["filename"], "07_Test.wav")

    def test_collect_aircraft_transition_sound_ids_is_edge_triggered(self):
        self.assertEqual(
            DARTS.collect_aircraft_transition_sound_ids(
                {"tcas_ra": "CLEAN", "hazard": "----", "squawk": "1200"},
                {"tcas_ra": "RA DESC CORR", "hazard": "WS MOD", "squawk": "7500"},
            ),
            ["03", "04", "05"],
        )
        self.assertEqual(
            DARTS.collect_aircraft_transition_sound_ids(
                {"tcas_ra": "RA DESC CORR", "hazard": "WS MOD", "squawk": "7500"},
                {"tcas_ra": "RA TERM", "hazard": "ICE SEV", "squawk": "7500"},
            ),
            [],
        )
        self.assertEqual(
            DARTS.collect_aircraft_transition_sound_ids(
                {"tcas_ra": "CLEAN", "hazard": "----", "squawk": "7600"},
                {"tcas_ra": "CLEAN", "hazard": "normal", "squawk": "7700"},
            ),
            ["07"],
        )

    def test_evaluate_audit_alert_entries_tracks_per_aircraft_and_per_point(self):
        audit_points = [
            {"name": "ALPHA", "lat": 0.0, "lon": 0.0, "outer_radius_nm": 5.0, "inner_radius_nm": 2.0},
            {"name": "BRAVO", "lat": 0.0, "lon": 0.0, "outer_radius_nm": 5.0, "inner_radius_nm": 2.0},
        ]
        aircraft = {
            "ABC123": {"callsign": "TEST123", "lat": 0.0, "lon": 0.0},
        }

        alerts_1, occupants_1, crossings_1 = DARTS.evaluate_audit_alert_entries(audit_points[:1], aircraft, {})
        self.assertEqual({entry["perimeter"] for entry in alerts_1}, {"OUTER", "INNER"})
        self.assertEqual(
            {(entry["point_name"], entry["perimeter"]) for entry in crossings_1},
            {("ALPHA", "OUTER"), ("ALPHA", "INNER")},
        )

        alerts_2, occupants_2, crossings_2 = DARTS.evaluate_audit_alert_entries(audit_points, aircraft, occupants_1)
        self.assertEqual(len(crossings_2), 2)
        self.assertEqual(
            {(entry["point_name"], entry["perimeter"]) for entry in crossings_2},
            {("BRAVO", "OUTER"), ("BRAVO", "INNER")},
        )

        alerts_3, occupants_3, crossings_3 = DARTS.evaluate_audit_alert_entries(audit_points, {}, occupants_2)
        self.assertEqual(alerts_3, [])
        self.assertEqual(crossings_3, [])

        _alerts_4, _occupants_4, crossings_4 = DARTS.evaluate_audit_alert_entries(audit_points[:1], aircraft, occupants_3)
        self.assertEqual(
            {(entry["point_name"], entry["perimeter"]) for entry in crossings_4},
            {("ALPHA", "OUTER"), ("ALPHA", "INNER")},
        )

    def test_trigger_sound_is_silent_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.object(DARTS, "SOUND_FILES_DIR", tmpdir):
                with mock.patch("builtins.print") as print_mock:
                    self.assertFalse(DARTS.trigger_sound("09"))
                    print_mock.assert_not_called()

    def test_trigger_sound_uses_restart_safe_opaque_event_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "01_Test.wav").write_bytes(b"audio")
            with mock.patch.object(DARTS, "SOUND_FILES_DIR", tmpdir):
                old_events = list(DARTS.sound_events)
                old_sequence = DARTS.sound_event_sequence
                old_session_id = DARTS.sound_event_session_id
                try:
                    DARTS.sound_events[:] = []
                    DARTS.sound_event_sequence = 0
                    DARTS.sound_event_session_id = "session-abc"
                    self.assertTrue(DARTS.trigger_sound("01"))
                    events = DARTS.get_recent_sound_events()
                    self.assertEqual(events[0]["event_id"], "session-abc:1")
                    self.assertEqual(events[0]["url"], "/sounds/01")
                finally:
                    DARTS.sound_events[:] = old_events
                    DARTS.sound_event_sequence = old_sequence
                    DARTS.sound_event_session_id = old_session_id


if __name__ == "__main__":
    unittest.main()
