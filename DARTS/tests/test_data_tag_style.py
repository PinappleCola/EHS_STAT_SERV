import asyncio
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

import websockets


def _load_darts_module():
    darts_path = Path(__file__).resolve().parents[1] / "darts.py"
    spec = importlib.util.spec_from_file_location("darts_under_test_data_tag_style", str(darts_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DARTS = _load_darts_module()
DEFAULT = {
    "font_family": "B612 Mono", "font_size_px": 11, "text_colour": None,
    "active_text_colour": None, "inactive_text_colour": None,
}
CUSTOM = {
    "font_family": "Courier New", "font_size_px": 22, "text_colour": "#ffd166",
    "active_text_colour": "#AbC", "inactive_text_colour": "#789abc",
}


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
            "active_text_colour": (None, "red", "#abcd", "#12345g", "#abc\n", {}, True),
            "inactive_text_colour": (None, "red", "#abcd", "#12345g", "#abc\n", {}, True),
        }.items():
            for value in invalid:
                with self.subTest(key=key, value=value):
                    expected = {**CUSTOM, key: DEFAULT[key]}
                    self.assertEqual(DARTS.normalize_data_tag_style({**CUSTOM, key: value}), expected)
        for size in (8, 11.5, 32):
            self.assertEqual(DARTS.normalize_data_tag_style({"font_size_px": size})["font_size_px"], size)
        self.assertEqual(DARTS.normalize_data_tag_style({"text_colour": "#AbC"})["text_colour"], "#AbC")
        self.assertEqual(DARTS.normalize_data_tag_style({"font_family": " monospace "})["font_family"], "monospace")
        self.assertEqual(
            DARTS.normalize_data_tag_style({"text_colour": "#ffd166"}),
            {**DEFAULT, "text_colour": "#ffd166"},
        )

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
                    ('{"data_tag_style": {"text_colour": "#abc"}}', {**DEFAULT, "text_colour": "#abc"}),
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
                    for raw, expected in (
                        (CUSTOM, CUSTOM), ({}, DEFAULT), ({"text_colour": "bad"}, DEFAULT),
                        ({"text_colour": "#abc"}, {**DEFAULT, "text_colour": "#abc"}),
                        ({**CUSTOM, "active_text_colour": "bad"}, {**CUSTOM, "active_text_colour": None}),
                        ({**CUSTOM, "inactive_text_colour": "bad"}, {**CUSTOM, "inactive_text_colour": None}),
                    ):
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
                    DARTS.RUNTIME_CONFIG["data_tag_style"] = {"text_colour": "#abc"}
                    connection.request("POST", "/api/rx-config", json.dumps({"rx_mode": DARTS.RX_MODE}))
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertTrue(json.loads(response.read())["ok"])
                    self.assertEqual(
                        DARTS.load_runtime_config()["data_tag_style"],
                        {**DEFAULT, "text_colour": "#abc"},
                    )
                finally:
                    connection.close()
                    server.shutdown()
                    server.server_close()
                    thread.join()


class DataTagActivityTests(unittest.IsolatedAsyncioTestCase):
    async def test_broadcast_boundary_farewell_and_fresh_update(self):
        aircraft = {"last_seen": 990.001, "ident_time": 0}
        with mock.patch.object(DARTS, "aircraft_state", {"ABC123": aircraft}), \
                mock.patch.object(DARTS.time, "time", return_value=1000.0), \
                mock.patch.object(DARTS, "sync_waypoint_decay"), \
                mock.patch.object(DARTS, "compute_display_heading", return_value=None):
            async with websockets.serve(DARTS.broadcast_state, "127.0.0.1", 0) as server:
                url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
                async with websockets.connect(url) as client:
                    for age, farewell in ((9.999, False), (10, False), (10.01, True), (0, False)):
                        with self.subTest(age=age, farewell=farewell):
                            aircraft["last_seen"] = 1000.0 - age
                            aircraft["farewell_sent"] = farewell
                            payload = json.loads(await asyncio.wait_for(client.recv(), 3))
                            plane = payload["airframes"][0]
                            self.assertEqual(plane["data_tag_inactive"], age >= 10)
                            self.assertEqual(plane["is_coasting"], age > 5)
                            if farewell:
                                self.assertIsInstance(plane["age"], str)
                            else:
                                self.assertEqual(plane["age"], int(age))


if __name__ == "__main__":
    unittest.main()
