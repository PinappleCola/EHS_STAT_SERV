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
        self.assertFalse(DARTS.UI_MAP_REPORTS)

    async def get_state(self):
        def request():
            conn = http.client.HTTPConnection("127.0.0.1", self.http_server.server_port, timeout=5)
            try:
                conn.request("GET", "/api/ui-state")
                response = conn.getresponse()
                return response.status, json.loads(response.read())
            finally:
                conn.close()
        return await asyncio.to_thread(request)

    async def wait_for_state(self, predicate):
        for _ in range(100):
            status, state = await self.get_state()
            self.assertEqual(status, 200)
            if predicate(state):
                return state
            await asyncio.sleep(0.02)
        self.fail(f"ui state condition not met: {state}")

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

    async def test_request_id_is_forwarded_and_echoed(self):
        async with websockets.connect(self.ws_url) as client:
            await asyncio.wait_for(client.recv(), 3)
            status, response = await self.post(json.dumps({"command": "toggle_vfr", "request_id": "sd-1:abc_2.x-y"}))
            self.assertEqual(status, 200)
            self.assertEqual(response, {"ok": True, "command": "toggle_vfr", "request_id": "sd-1:abc_2.x-y"})
            while True:
                message = json.loads(await asyncio.wait_for(client.recv(), 3))
                if message.get("type") == "ui_command":
                    break
            self.assertEqual(message, {"type": "ui_command", "command": "toggle_vfr", "request_id": "sd-1:abc_2.x-y"})

    async def test_invalid_request_id_is_rejected_without_broadcast(self):
        with mock.patch.object(DARTS, "broadcast_ui_command") as broadcast:
            for request_id in ("", "x" * 65, "bad id", 5, ["a"], "<svg>"):
                with self.subTest(request_id=request_id):
                    status, response = await self.post(json.dumps({"command": "toggle_ifr", "request_id": request_id}))
                    self.assertEqual(status, 400)
                    self.assertIn("error", response)
            broadcast.assert_not_called()

    async def test_ui_state_reports_controlling_map(self):
        status, state = await self.get_state()
        self.assertEqual(status, 200)
        self.assertEqual(state["connectionState"], "no_map")
        self.assertIsNone(state["ifrEnabled"])
        self.assertEqual(state["mapClients"], 0)

        def report(map_on, ifr_on, vfr_on, request_id=None):
            return json.dumps({"action": "ui_state", "request_id": request_id,
                               "state": {"mapEnabled": map_on, "ifrEnabled": ifr_on, "vfrEnabled": vfr_on}})

        async with websockets.connect(self.ws_url) as first:
            await first.send(json.dumps({"action": "ui_state", "state": {"mapEnabled": "yes"}}))
            await first.send(report(True, False, True, "req-1"))
            state = await self.wait_for_state(lambda s: s["connectionState"] == "connected")
            self.assertEqual((state["mapEnabled"], state["ifrEnabled"], state["vfrEnabled"]), (True, False, True))
            self.assertEqual(state["lastRequestId"], "req-1")
            revision = state["revision"]

            async with websockets.connect(self.ws_url) as second:
                await second.send(report(False, True, False))
                state = await self.wait_for_state(lambda s: s["mapClients"] == 2)
                self.assertEqual((state["mapEnabled"], state["ifrEnabled"]), (True, False))
                self.assertEqual(state["revision"], revision)
            state = await self.wait_for_state(lambda s: s["mapClients"] == 1)
            self.assertEqual(state["ifrEnabled"], False)

            async with websockets.connect(self.ws_url) as second:
                await second.send(report(False, True, False))
                await self.wait_for_state(lambda s: s["mapClients"] == 2)
                await first.close()
                state = await self.wait_for_state(lambda s: s["mapClients"] == 1)
                self.assertEqual((state["mapEnabled"], state["ifrEnabled"], state["vfrEnabled"]), (False, True, False))
                self.assertIsNone(state["lastRequestId"])
                self.assertGreater(state["revision"], revision)
        await self.wait_for_state(lambda s: s["connectionState"] == "no_map")

    def test_ui_state_goes_stale_without_heartbeat(self):
        key = object()
        try:
            self.assertTrue(DARTS.record_ui_state(key, {"mapEnabled": False, "ifrEnabled": True, "vfrEnabled": True}, "bad id", now=100.0))
            fresh = DARTS.get_ui_state_snapshot(now=100.0 + DARTS.UI_STATE_STALE_SEC)
            self.assertEqual(fresh["connectionState"], "connected")
            self.assertIsNone(fresh["lastRequestId"])
            stale = DARTS.get_ui_state_snapshot(now=100.0 + DARTS.UI_STATE_STALE_SEC + 0.5)
            self.assertEqual(stale["connectionState"], "stale")
            self.assertEqual(stale["ifrEnabled"], True)
            self.assertFalse(DARTS.record_ui_state(key, None))
        finally:
            DARTS.forget_ui_state(key)


if __name__ == "__main__":
    unittest.main()
