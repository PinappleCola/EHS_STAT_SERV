import builtins
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


def _load_darts_module():
    darts_path = Path(__file__).resolve().parents[1] / "darts.py"
    spec = importlib.util.spec_from_file_location("darts_under_test_altitude_fallback", str(darts_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_darts_without_pymodes():
    darts_path = Path(__file__).resolve().parents[1] / "darts.py"
    spec = importlib.util.spec_from_file_location("darts_without_pymodes", str(darts_path))
    module = importlib.util.module_from_spec(spec)
    original_import = builtins.__import__

    def import_without_pymodes(name, *args, **kwargs):
        if name == "pyModeS" or name.startswith("pyModeS."):
            raise ImportError("pyModeS unavailable")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=import_without_pymodes):
        spec.loader.exec_module(module)
    return module


DARTS = _load_darts_module()


class ModeSAltitudeFallbackTests(unittest.TestCase):
    def test_legacy_decoder_reads_df17_and_df20_altitudes(self):
        adsb_altitude = Mock(return_value=36_000)
        commb_altcode = Mock(return_value=35_000)
        legacy_pms = SimpleNamespace(
            adsb=SimpleNamespace(altitude=adsb_altitude),
            common=SimpleNamespace(altcode=commb_altcode),
        )

        with patch.object(DARTS, "pms", legacy_pms):
            self.assertEqual(DARTS.decode_legacy_altitude("8DABC123" + "0" * 20, 17), 36_000)
            self.assertEqual(DARTS.decode_legacy_altitude("A0000000" + "0" * 20, 20), 35_000)

        adsb_altitude.assert_called_once_with("8DABC123" + "0" * 20)
        commb_altcode.assert_called_once_with("A0000000" + "0" * 20)

    def test_legacy_altitude_is_optional_for_other_formats_or_missing_pymodes(self):
        with patch.object(DARTS, "pms", None):
            self.assertIsNone(DARTS.decode_legacy_altitude("8DABC123" + "0" * 20, 17))

        legacy_pms = SimpleNamespace(adsb=SimpleNamespace(altitude=Mock(return_value=1)))
        with patch.object(DARTS, "pms", legacy_pms):
            self.assertIsNone(DARTS.decode_legacy_altitude("8DABC123" + "0" * 20, 0))

    def test_fallback_pipe_decoder_includes_df17_and_df20_altitudes(self):
        fallback_darts = _load_darts_without_pymodes()
        legacy_pms = SimpleNamespace(
            adsb=SimpleNamespace(altitude=Mock(return_value=36_000)),
            common=SimpleNamespace(altcode=Mock(return_value=35_000)),
        )
        df17 = "8DABC123" + "0" * 20
        df20 = "A0000000" + "0" * 20

        with patch.object(fallback_darts, "pms", legacy_pms):
            decoder = fallback_darts.PipeDecoder()
            self.assertEqual(decoder.decode(df17)["altitude"], 36_000)
            self.assertEqual(decoder.decode(df20)["altitude"], 35_000)

        legacy_pms.adsb.altitude.assert_called_once_with(df17)
        legacy_pms.common.altcode.assert_called_once_with(df20)


if __name__ == "__main__":
    unittest.main()
