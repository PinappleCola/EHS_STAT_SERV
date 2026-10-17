import importlib.util
import unittest
from pathlib import Path
from unittest.mock import call, patch


def _load_darts_module():
    darts_path = Path(__file__).resolve().parents[1] / "darts.py"
    spec = importlib.util.spec_from_file_location("darts_under_test_global_cpr", str(darts_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DARTS = _load_darts_module()


def _cpr_frame(cpr_lat, cpr_lon, is_odd, tc=11):
    bits = ["0"] * 56
    bits[:5] = f"{tc:05b}"
    bits[21] = "1" if is_odd else "0"
    bits[22:39] = f"{cpr_lat:017b}"
    bits[39:56] = f"{cpr_lon:017b}"
    return "".join(bits)


# Fixed 17-bit fields, rounded to nearest using independently specified NL
# counts, not the decoder's cpr_nl(). Expected coordinates are in degrees.
WORLD_VECTORS = (
    ("Queensland", -27.9, 153.4, (45875, 76531), (56033, 20680)),
    ("London", 51.5074, -0.1278, (76620, 129350), (57867, 129397)),
    ("New York", 40.7128, -74.006, (102953, 98206), (88130, 125150)),
    ("Quito", -0.1807, -78.4678, (127125, 18350), (127190, 46919)),
    ("Equator", 0.0, 31.0, (0, 10559), (0, 130344)),
    ("North equator", 0.0001, 32.0, (2, 32040), (2, 20389)),
    ("South equator", -0.0001, -32.0, (131070, 99032), (131070, 110683)),
    ("East dateline", 12.3, 179.999, (6554, 131051), (2075, 65515)),
    ("West dateline", -12.3, -179.999, (124518, 21), (128997, 65557)),
    ("Dateline", 0.0, -180.0, (0, 65536), (0, 0)),
    ("Arctic", 86.8, 42.0, (61167, 30583), (29564, 15292)),
    ("Antarctic", -86.8, -42.0, (69905, 100489), (101508, 115780)),
    ("87 north", 87.0, -135.0, (65536, 32768), (33860, 81920)),
    ("87 south", -87.0, 135.0, (65536, 98304), (97212, 49152)),
    ("North polar", 88.0, 135.0, (87381, 49152), (55342, 49152)),
    ("South polar", -88.0, -135.0, (43691, 81920), (75730, 81920)),
    ("North pole", 90.0, 45.0, (0, 16384), (98304, 16384)),
    ("South pole", -90.0, -45.0, (0, 114688), (32768, 114688)),
    ("NL boundary below", 10.4704, 120.0, (97657, 87381), (93845, 43691)),
    ("NL boundary above", 10.4706, 120.0, (97662, 43691), (93850, 0)),
    ("Polar boundary below", 86.5353, 40.0, (55384, 43691), (23878, 29127)),
    ("Polar boundary above", 86.5355, 40.0, (55389, 29127), (23882, 14564)),
)

# Published airborne CPR example from The 1090 MHz Riddle, with motion
# between the even and odd reports so timestamp selection is observable.
KNOWN_EVEN = f"{int('58C382D690C8AC', 16):056b}"
KNOWN_ODD = f"{int('58C386435CC412', 16):056b}"


class GlobalCPRTests(unittest.TestCase):
    def setUp(self):
        DARTS.cpr_position_cache.clear()

    def test_nl_standard_counts_and_boundaries(self):
        for lat, expected in (
            (0.0, 59), (10.4704712, 59), (10.4704714, 58),
            (45.0, 42), (60.0, 29), (80.0, 10), (85.0, 4),
            (86.0, 3), (86.5353699, 3), (86.5353701, 2),
            (86.8, 2), (87.0, 2), (87.0000001, 1), (90.0, 1),
        ):
            for sign in (-1, 1):
                with self.subTest(lat=sign * lat):
                    self.assertEqual(DARTS.cpr_nl(sign * lat), expected)

    def test_world_vectors_in_both_arrival_orders(self):
        for name, lat, lon, even_fields, odd_fields in WORLD_VECTORS:
            for last_is_odd in (False, True):
                with self.subTest(region=name, last_is_odd=last_is_odd):
                    DARTS.cpr_position_cache.clear()
                    frames = (_cpr_frame(*even_fields, False), _cpr_frame(*odd_fields, True))
                    self.assertIsNone(DARTS.decode_global_cpr_position(
                        "ABC123", frames[not last_is_odd], not last_is_odd, 100.0))
                    position = DARTS.decode_global_cpr_position(
                        "ABC123", frames[last_is_odd], last_is_odd, 101.0)
                    self.assertIsNotNone(position)
                    self.assertAlmostEqual(position[0], lat, delta=0.0001)
                    # At NL=1, half a longitude quantization step is 0.001374°.
                    tolerance = 0.0015 if abs(lat) > 86.0 else 0.0001
                    self.assertAlmostEqual(position[1], lon, delta=tolerance)

    def test_published_pair_uses_newest_position(self):
        for use_odd, expected in ((False, (52.2572, 3.9194)), (True, (52.2658, 3.9389))):
            with self.subTest(use_odd=use_odd):
                self.assertEqual(DARTS.bare_metal_cpr_global(KNOWN_EVEN, KNOWN_ODD, use_odd), expected)

    def test_global_pair_decodes_aircraft_away_from_sydney_reference(self):
        lat, lon = -27.9, 153.4
        even = _cpr_frame(45875, 76531, False)
        odd = _cpr_frame(56033, 20680, True)

        self.assertIsNone(DARTS.decode_global_cpr_position("QLD001", even, False, 100.0))
        position = DARTS.decode_global_cpr_position("QLD001", odd, True, 101.0)

        self.assertAlmostEqual(position[0], lat, places=3)
        self.assertAlmostEqual(position[1], lon, places=3)

    def test_global_pair_can_arrive_odd_then_even(self):
        lat, lon = -27.9, 153.4
        odd = _cpr_frame(56033, 20680, True)
        even = _cpr_frame(45875, 76531, False)

        self.assertIsNone(DARTS.decode_global_cpr_position("QLD002", odd, True, 100.0))
        position = DARTS.decode_global_cpr_position("QLD002", even, False, 101.0)

        self.assertAlmostEqual(position[0], lat, places=3)
        self.assertAlmostEqual(position[1], lon, places=3)

    def test_stale_global_pair_is_not_used(self):
        even = _cpr_frame(45875, 76531, False)
        odd = _cpr_frame(56033, 20680, True)

        self.assertIsNone(DARTS.decode_global_cpr_position("QLD003", even, False, 100.0))
        self.assertIsNone(DARTS.decode_global_cpr_position("QLD003", odd, True, 110.1))

    def test_freshness_limit_in_both_orders_and_timestamp_directions(self):
        for last_is_odd in (False, True):
            for elapsed in (-10.001, -10.0, 10.0, 10.001):
                with self.subTest(last_is_odd=last_is_odd, elapsed=elapsed):
                    DARTS.cpr_position_cache.clear()
                    frames = (KNOWN_EVEN, KNOWN_ODD)
                    DARTS.decode_global_cpr_position("ABC123", frames[not last_is_odd], not last_is_odd, 100.0)
                    position = DARTS.decode_global_cpr_position(
                        "ABC123", frames[last_is_odd], last_is_odd, 100.0 + elapsed)
                    if abs(elapsed) > 10.0:
                        self.assertIsNone(position)
                        latest_parity = last_is_odd if elapsed > 0 else not last_is_odd
                        self.assertEqual(set(DARTS.cpr_position_cache["ABC123"]),
                                         {"odd" if latest_parity else "even"})
                    else:
                        self.assertIsNotNone(position)

    def test_out_of_order_timestamps_select_newer_report(self):
        for newer_is_odd, expected in ((False, (52.2572, 3.9194)), (True, (52.2658, 3.9389))):
            with self.subTest(newer_is_odd=newer_is_odd):
                DARTS.cpr_position_cache.clear()
                frames = (KNOWN_EVEN, KNOWN_ODD)
                DARTS.decode_global_cpr_position("ABC123", frames[newer_is_odd], newer_is_odd, 102.0)
                self.assertEqual(DARTS.decode_global_cpr_position(
                    "ABC123", frames[not newer_is_odd], not newer_is_odd, 101.0), expected)

    def test_older_same_parity_does_not_replace_newer_frame(self):
        DARTS.decode_global_cpr_position("ABC123", KNOWN_EVEN, False, 102.0)
        older_even = _cpr_frame(45875, 76531, False)
        self.assertIsNone(DARTS.decode_global_cpr_position("ABC123", older_even, False, 100.0))
        self.assertEqual(DARTS.cpr_position_cache["ABC123"]["even"], (KNOWN_EVEN, 102.0))

    def test_same_parity_and_other_aircraft_cannot_form_pair(self):
        self.assertIsNone(DARTS.decode_global_cpr_position("ABC123", KNOWN_EVEN, False, 100.0))
        self.assertIsNone(DARTS.decode_global_cpr_position("ABC123", KNOWN_EVEN, False, 101.0))
        self.assertIsNone(DARTS.decode_global_cpr_position("DEF456", KNOWN_ODD, True, 102.0))

    def test_stale_pair_recovers_with_fresh_opposite_frame(self):
        DARTS.decode_global_cpr_position("ABC123", KNOWN_EVEN, False, 100.0)
        self.assertIsNone(DARTS.decode_global_cpr_position("ABC123", KNOWN_ODD, True, 111.0))
        self.assertEqual(DARTS.decode_global_cpr_position("ABC123", KNOWN_EVEN, False, 112.0),
                         (52.2572, 3.9194))

    def test_default_freshness_uses_monotonic_clock(self):
        with patch.object(DARTS.time, "monotonic", side_effect=[100.0, 110.1]) as clock:
            self.assertIsNone(DARTS.decode_global_cpr_position("ABC123", KNOWN_EVEN, False))
            self.assertIsNone(DARTS.decode_global_cpr_position("ABC123", KNOWN_ODD, True))
        self.assertEqual(clock.call_count, 2)

    def test_pair_crossing_nl_boundary_is_rejected(self):
        even = _cpr_frame(97657, 87381, False)  # 10.4704°, NL=59
        odd = _cpr_frame(93850, 0, True)  # 10.4706°, NL=58
        for use_odd in (False, True):
            self.assertIsNone(DARTS.bare_metal_cpr_global(even, odd, use_odd))

    def test_both_reconstructed_latitudes_must_be_valid(self):
        even = _cpr_frame(0, 16384, False)  # 90°
        odd = _cpr_frame(98305, 16384, True)  # Just beyond 90°
        for use_odd in (False, True):
            self.assertIsNone(DARTS.bare_metal_cpr_global(even, odd, use_odd))

    def test_process_frame_decodes_all_airborne_position_types(self):
        for df in (17, 18):
            for tc in (*range(9, 19), 20, 21, 22):
                for last_is_odd in (False, True):
                    with self.subTest(df=df, tc=tc, last_is_odd=last_is_odd):
                        DARTS.cpr_position_cache.clear()
                        frames = (_cpr_frame(45875, 76531, False, tc),
                                  _cpr_frame(56033, 20680, True, tc))
                        with patch.object(DARTS.pipeline, "decode", return_value={"icao": "ABC123"}), \
                                patch.object(DARTS, "handle_entry_gate"), \
                                patch.object(DARTS, "update_aircraft") as update:
                            for index, parity in enumerate((not last_is_odd, last_is_odd)):
                                payload = bytes([(df << 3) | 5]) + bytes.fromhex("ABC123")
                                payload += int(frames[parity], 2).to_bytes(7, "big") + bytes(3)
                                DARTS.process_frame(bytes([0x33]) + bytes(7) + payload)
                                positions = [c for c in update.call_args_list if c.args[1] in ("lat", "lon")]
                                if index == 0:
                                    self.assertEqual(positions, [])
                            self.assertEqual(positions, [call("ABC123", "lat", -27.9),
                                                         call("ABC123", "lon", 153.4)])
                            update.assert_any_call("ABC123", "air_ground", "AIR")

    def test_surface_frames_do_not_enter_airborne_pair_cache(self):
        with patch.object(DARTS.pipeline, "decode", return_value={"icao": "ABC123"}), \
                patch.object(DARTS, "handle_entry_gate"), \
                patch.object(DARTS, "update_aircraft") as update:
            for parity in (False, True):
                mb = _cpr_frame(45875, 76531, parity, tc=5)
                payload = bytes.fromhex("8DABC123") + int(mb, 2).to_bytes(7, "big") + bytes(3)
                DARTS.process_frame(bytes([0x33]) + bytes(7) + payload)
            self.assertEqual(DARTS.cpr_position_cache, {})
            update.assert_any_call("ABC123", "air_ground", "GROUND")
            self.assertFalse(any(c.args[1] in ("lat", "lon") for c in update.call_args_list))


if __name__ == "__main__":
    unittest.main()
