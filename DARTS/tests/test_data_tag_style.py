import copy
import http.client
import http.server
import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


def _load_darts_module():
    darts_path = Path(__file__).resolve().parents[1] / "darts.py"
    spec = importlib.util.spec_from_file_location("darts_under_test_data_tag_style", str(darts_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DARTS = _load_darts_module()
DEFAULT = {"font_family": "B612 Mono", "font_size_px": 11, "text_colour": None}
CUSTOM = {"font_family": "Courier New", "font_size_px": 22, "text_colour": "#ffd166"}


class DataTagStyleTests(unittest.TestCase):
    def test_defaults_and_independent_validation(self):
        for raw in (None, {}, [], "", 123):
            with self.subTest(raw=raw):
                self.assertEqual(DARTS.normalize_data_tag_style(raw), DEFAULT)
        self.assertEqual(DARTS.normalize_data_tag_style(CUSTOM), CUSTOM)
        for key, invalid in {
            "font_family": (None, "", 12, [], "Arial; 40px serif", "Arial, serif", "A" * 101),
            "font_size_px": (None, "16", True, [], 7, 33, float("nan"), float("inf"), 10**400),
            "text_colour": ("red", "currentColor", "#abcd", "#12345g", "#abc\n", {}, 123),
        }.items():
            for value in invalid:
                with self.subTest(key=key, value=value):
                    expected = {**CUSTOM, key: DEFAULT[key]}
                    self.assertEqual(DARTS.normalize_data_tag_style({**CUSTOM, key: value}), expected)
        for size in (8, 11.5, 32):
            self.assertEqual(DARTS.normalize_data_tag_style({"font_size_px": size})["font_size_px"], size)
        self.assertEqual(DARTS.normalize_data_tag_style({"text_colour": "#AbC"})["text_colour"], "#AbC")
        self.assertEqual(DARTS.normalize_data_tag_style({"font_family": " monospace "})["font_family"], "monospace")

    def test_file_loading_and_fallbacks(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "runtime_config.json"
            with mock.patch.object(DARTS, "CONFIG_PATH", str(config_path)), mock.patch.dict(DARTS.os.environ, {}, clear=True):
                self.assertEqual(DARTS.load_runtime_config()["data_tag_style"], DEFAULT)
                for content, expected in (
                    ("{", DEFAULT),
                    ("[]", DEFAULT),
                    ("{}", DEFAULT),
                    ('{"data_tag_style": []}', DEFAULT),
                    (json.dumps({"data_tag_style": CUSTOM}), CUSTOM),
                    ('{"data_tag_style": {"font_size_px": 99}}', DEFAULT),
                ):
                    with self.subTest(content=content):
                        config_path.write_text(content)
                        self.assertEqual(DARTS.load_runtime_config()["data_tag_style"], expected)

    def test_http_style_and_receiver_save_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "runtime_config.json"
            with mock.patch.object(DARTS, "CONFIG_PATH", str(config_path)), \
                    mock.patch.object(DARTS, "RUNTIME_CONFIG", copy.deepcopy(DARTS.RUNTIME_CONFIG)):
                DARTS.RUNTIME_CONFIG["data_tag_style"] = dict(CUSTOM)
                server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), DARTS.DARTSAPIHandler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                try:
                    for raw, expected in ((CUSTOM, CUSTOM), ({}, DEFAULT), ({"text_colour": "bad"}, DEFAULT)):
                        DARTS.RUNTIME_CONFIG["data_tag_style"] = raw
                        connection.request("GET", "/api/data-tag-style")
                        response = connection.getresponse()
                        self.assertEqual(response.status, 200)
                        self.assertEqual(json.loads(response.read()), expected)
                    DARTS.RUNTIME_CONFIG["data_tag_style"] = dict(CUSTOM)
                    connection.request("POST", "/api/rx-config", json.dumps({"rx_mode": DARTS.RX_MODE}))
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertTrue(json.loads(response.read())["ok"])
                    self.assertEqual(json.loads(config_path.read_text())["data_tag_style"], CUSTOM)
                    self.assertEqual(DARTS.load_runtime_config()["data_tag_style"], CUSTOM)
                finally:
                    connection.close()
                    server.shutdown()
                    server.server_close()
                    thread.join()


if __name__ == "__main__":
    unittest.main()
