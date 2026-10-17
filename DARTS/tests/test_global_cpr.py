import importlib.util
import unittest
from pathlib import Path


def _load_darts_module():
    darts_path = Path(__file__).resolve().parents[1] / "darts.py"
    spec = importlib.util.spec_from_file_location("darts_under_test_global_cpr", str(darts_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DARTS = _load_darts_module()


def _encode_cpr_frame(lat, lon, is_odd):
    dlat = 360.0 / (59 if is_odd else 60)
    cpr_lat = int((lat % dlat) / dlat * 131072)
    ni = max(DARTS.cpr_nl(lat) - int(is_odd), 1)
    dlon = 360.0 / ni
    cpr_lon = int((lon % dlon) / dlon * 131072)

    bits = ["0"] * 56
    bits[21] = "1" if is_odd else "0"
    bits[22:39] = f"{cpr_lat:017b}"
    bits[39:56] = f"{cpr_lon:017b}"
    return "".join(bits)


class GlobalCPRTests(unittest.TestCase):
    def test_global_pair_decodes_aircraft_away_from_sydney_reference(self):
        lat, lon = -27.9, 153.4
        even = _encode_cpr_frame(lat, lon, False)
        odd = _encode_cpr_frame(lat, lon, True)

        self.assertIsNone(DARTS.decode_global_cpr_position("QLD001", even, False, 100.0))
        position = DARTS.decode_global_cpr_position("QLD001", odd, True, 101.0)

        self.assertAlmostEqual(position[0], lat, places=3)
        self.assertAlmostEqual(position[1], lon, places=3)

    def test_global_pair_can_arrive_odd_then_even(self):
        lat, lon = -27.9, 153.4
        odd = _encode_cpr_frame(lat, lon, True)
        even = _encode_cpr_frame(lat, lon, False)

        self.assertIsNone(DARTS.decode_global_cpr_position("QLD002", odd, True, 100.0))
        position = DARTS.decode_global_cpr_position("QLD002", even, False, 101.0)

        self.assertAlmostEqual(position[0], lat, places=3)
        self.assertAlmostEqual(position[1], lon, places=3)

    def test_stale_global_pair_is_not_used(self):
        even = _encode_cpr_frame(-27.9, 153.4, False)
        odd = _encode_cpr_frame(-27.9, 153.4, True)

        self.assertIsNone(DARTS.decode_global_cpr_position("QLD003", even, False, 100.0))
        self.assertIsNone(DARTS.decode_global_cpr_position("QLD003", odd, True, 110.1))


if __name__ == "__main__":
    unittest.main()
