import asyncio
import http.client
import http.server
import importlib.util
import json
import threading
import unittest
from pathlib import Path
from unittest import mock

import websockets


def _load_darts_module():
    darts_path = Path(__file__).resolve().parents[1] / "darts.py"
    spec = importlib.util.spec_from_file_location("darts_under_test_ui_commands", str(darts_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DARTS = _load_darts_module()


class UICommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        DARTS.WS_LOOP = asyncio.get_running_loop()
        self.ws_server = await websockets.serve(DARTS.broadcast_state, "127.0.0.1", 0)
        self.ws_url = f"ws://127.0.0.1:{self.ws_server.sockets[0].getsockname()[1]}"
        self.http_server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), DARTS.DARTSAPIHandler)
        self.http_thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
        self.http_thread.start()

    async def asyncTearDown(self):
        await asyncio.to_thread(self.http_server.shutdown)
        self.http_server.server_close()
        self.http_thread.join()
        self.ws_server.close()
        await self.ws_server.wait_closed()
        DARTS.WS_LOOP = None
        self.assertFalse(DARTS.WS_CLIENTS)

    async def post(self, body):
        def request():
            conn = http.client.HTTPConnection("127.0.0.1", self.http_server.server_port, timeout=5)
            try:
                conn.request("POST", "/api/ui-command", body, {"Content-Type": "application/json"})
                response = conn.getresponse()
                return response.status, json.loads(response.read())
            finally:
                conn.close()
        return await asyncio.to_thread(request)

    async def test_commands_reach_all_clients_on_existing_sockets(self):
        async with websockets.connect(self.ws_url) as first, websockets.connect(self.ws_url) as second:
            for client in (first, second):
                state = json.loads(await asyncio.wait_for(client.recv(), 3))
                self.assertIn("airframes", state)
            for command in ("toggle_map", "toggle_ifr", "toggle_vfr"):
                status, response = await self.post(json.dumps({"command": command}))
                self.assertEqual(status, 200)
                self.assertEqual(response, {"ok": True, "command": command})
                for client in (first, second):
                    while True:
                        message = json.loads(await asyncio.wait_for(client.recv(), 3))
                        if message.get("type") == "ui_command":
                            break
                    self.assertEqual(message, {"type": "ui_command", "command": command})

    async def test_commands_are_accepted_without_clients(self):
        for command in ("toggle_map", "toggle_ifr", "toggle_vfr"):
            status, response = await self.post(json.dumps({"command": command}))
            self.assertEqual(status, 200)
            self.assertEqual(response, {"ok": True, "command": command})

    async def test_invalid_commands_and_json_are_rejected_without_broadcast(self):
        bodies = ("", "{", "null", "[]", '"toggle_ifr"', "{}",
                  '{"command":"reload_map_data"}', '{"command":null}',
                  '{"command":123}', '{"command":[]}', '{"command":{}}', b"\xff")
        with mock.patch.object(DARTS, "broadcast_ui_command") as broadcast:
            for body in bodies:
                with self.subTest(body=body):
                    status, response = await self.post(body)
                    self.assertEqual(status, 400)
                    self.assertIn("error", response)
            broadcast.assert_not_called()

    async def test_unavailable_websocket_loop_returns_json_error(self):
        DARTS.WS_LOOP = None
        status, response = await self.post('{"command":"toggle_ifr"}')
        self.assertEqual(status, 503)
        self.assertIn("error", response)


if __name__ == "__main__":
    unittest.main()
