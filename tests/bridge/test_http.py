import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "plugin"), str(ROOT / "dev")]
from mock_bridge import FakeAdapter
from webgui.bridge import Bridge, DEFAULTS


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        Path(self.temp.name, "index.html").write_text("<!doctype html><title>test</title>")
        self.adapter = FakeAdapter()
        self.bridge = Bridge(self.adapter, {**DEFAULTS, "port": 0, "token": "test-token"}, self.temp.name)
        self.adapter.bridge = self.bridge
        self.bridge.start()
        self.port = self.bridge.server.http.server_port
        self.running = True
        self.loop = threading.Thread(target=self.tick, daemon=True)
        self.loop.start()
        self.cookie = ""
        self.csrf = ""

    def tick(self):
        while self.running:
            self.adapter.tick()

    def tearDown(self):
        self.running = False
        self.loop.join(1)
        self.bridge.stop()
        self.temp.cleanup()

    def call(self, path, method="GET", body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        request_headers = {"Origin": f"http://127.0.0.1:{self.port}", "Content-Type": "application/json",
                           "Cookie": self.cookie, "X-CSRF-Token": self.csrf, **(headers or {})}
        connection.request(method, path, json.dumps(body or {}) if method != "GET" else None, request_headers)
        response = connection.getresponse()
        content = response.read()
        status, result_headers = response.status, dict(response.getheaders())
        connection.close()
        value = json.loads(content) if content and "application/json" in result_headers.get("Content-Type", "") else content.decode()
        return status, value, result_headers

    def login(self):
        status, response, headers = self.call("/api/v1/auth/login", "POST", {"token": "test-token"})
        self.assertEqual(status, 200)
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.csrf = response["data"]["csrf"]

    def test_security_login_csrf_host_origin_redaction(self):
        self.assertEqual(self.call("/api/v1/health")[0], 200)
        self.assertEqual(self.call("/api/v1/status")[0], 401)
        self.assertEqual(self.call("/api/v1/health", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.call("/api/v1/auth/login", "POST", {"token": "test-token"}, {"Origin": "http://evil.example"})[0], 403)
        self.login()
        self.assertEqual(self.call("/api/v1/disconnect", "POST", headers={"X-CSRF-Token": "wrong"})[0], 403)
        status, response, _ = self.call("/api/v1/bridge/settings")
        self.assertEqual(status, 200)
        self.assertNotIn("token", response["data"])
        self.assertNotIn("test-token", json.dumps(response))
        self.assertEqual(self.call("/api/v1/auth/logout", "POST")[0], 200)
        self.assertEqual(self.call("/api/v1/status")[0], 401)

    def test_search_selection_and_transfer_actions(self):
        self.login()
        status, created, _ = self.call("/api/v1/searches", "POST", {"term": "ambient"})
        self.assertEqual(status, 200)
        token = created["data"]["token"]
        status, results, _ = self.call(f"/api/v1/searches/{token}?limit=10&sort=-size")
        self.assertEqual(status, 200)
        self.assertEqual(len(results["data"]["items"]), 10)
        row = results["data"]["items"][0]
        self.assertEqual(results["data"]["total"], 10000)
        cursor = results["data"]["next_cursor"]
        self.assertEqual(len(self.call(f"/api/v1/searches/{token}?limit=10&cursor={cursor}")[1]["data"]["items"]), 10)
        self.bridge.store.put("search/" + str(token), {"items": [], "truncated": True}, "search.results")
        self.assertEqual(self.call(f"/api/v1/searches/{token}?cursor={cursor}")[0], 409)
        # Selection resolves retained server IDs rather than trusting browser paths.
        self.assertEqual(self.call(f"/api/v1/searches/{token}/downloads", "POST", {"ids": [row["id"]]})[0], 200)
        _, transfers, _ = self.call("/api/v1/downloads")
        self.assertEqual(transfers["data"][0]["virtual_path"], row["virtual_path"])
        self.assertEqual(self.call("/api/v1/downloads/actions", "POST", {"ids": [row["id"]], "action": "pause"})[0], 200)
        self.assertEqual(self.call("/api/v1/downloads")[1]["data"][0]["status"], "Paused")
        self.assertEqual(self.call(f"/api/v1/searches/{token}", "DELETE")[0], 200)

    def test_chat_read_ack_preserves_newer_unread(self):
        self.login()
        status, _, _ = self.call("/api/v1/rooms/music/messages", "POST", {"message": "hello"})
        self.assertEqual(status, 200)
        history = self.call("/api/v1/rooms/music/messages")[1]["data"]
        self.assertEqual(len(history["items"]), 2)
        self.assertEqual(history["unread"], 1)
        self.call("/api/v1/rooms/music/read", "POST", {"through": history["items"][0]["id"]})
        self.assertEqual(self.call("/api/v1/rooms/music/messages")[1]["data"]["unread"], 1)
        self.call("/api/v1/rooms/music/read", "POST", {"through": history["items"][-1]["id"]})
        self.assertEqual(self.call("/api/v1/rooms/music/messages")[1]["data"]["unread"], 0)

    def test_sse_replay_and_static_traversal(self):
        self.login()
        snapshot = self.call("/api/v1/status")[1]
        self.bridge.store.publish("connection.changed", {"test": True})
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request("GET", "/api/v1/events?cursor=" + snapshot["cursor"], headers={"Cookie": self.cookie})
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        lines = [response.readline().decode() for _ in range(6)]
        self.assertIn("event: connection.changed\n", lines)
        response.close()
        connection.close()
        self.assertEqual(self.call("/%2e%2e/secret")[0], 403)
        self.assertEqual(self.call("/search/123")[0], 200)
        self.assertEqual(self.call("/missing.js")[0], 404)

    def test_port_conflict_does_not_leave_event_callbacks_or_listener(self):
        other = Bridge(FakeAdapter(), {**DEFAULTS, "port": self.port, "token": "other"}, self.temp.name)
        with self.assertRaises(OSError):
            other.start()
        other.stop()
        self.assertEqual(self.call("/api/v1/health")[0], 200)

    def test_browse_batch_uses_retained_result_ids(self):
        self.login()
        self.assertEqual(self.call("/api/v1/users/alice/browse", "POST")[0], 200)
        self.assertEqual(self.call("/api/v1/users/alice/downloads", "POST", {"ids": ["demo-file"]})[0], 200)
        self.assertEqual(self.call("/api/v1/downloads")[1]["data"][0]["virtual_path"], "Music\\Example.flac")
        self.assertEqual(self.call("/api/v1/users/alice/downloads", "POST", {"ids": ["expired"]})[0], 409)

    def test_cross_origin_bearer_session_preflight_and_revocation(self):
        origin = "https://ui.example.com"
        self.bridge.settings["allowed_origins"] = origin
        headers = {"Origin": origin}
        status, _, cors = self.call("/api/v1/auth/login", "OPTIONS", headers={**headers, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type,x-csrf-token"})
        self.assertEqual(status, 204)
        self.assertEqual(cors["Access-Control-Allow-Origin"], origin)
        self.assertNotIn("Access-Control-Allow-Credentials", cors)
        status, response, cors = self.call("/api/v1/auth/login", "POST", {"token": "test-token", "mode": "bearer"}, headers)
        self.assertEqual(status, 200)
        self.assertNotIn("Set-Cookie", cors)
        sid = response["data"]["session_token"]
        self.csrf = response["data"]["csrf"]
        headers["Authorization"] = "Bearer " + sid
        self.assertEqual(self.call("/api/v1/session", headers=headers)[0], 200)
        self.assertEqual(self.call("/api/v1/away", "POST", {"away": True}, headers)[0], 200)
        self.assertEqual(self.call("/api/v1/away", "POST", {"away": True}, {**headers, "X-CSRF-Token": "bad"})[0], 403)
        self.cookie = "npw_session=" + sid
        self.assertEqual(self.call("/api/v1/session")[0], 401)
        self.assertEqual(self.call("/api/v1/auth/logout", "POST", headers=headers)[0], 200)
        status, _, cors = self.call("/api/v1/session", headers=headers)
        self.assertEqual(status, 401)
        self.assertEqual(cors["Access-Control-Allow-Origin"], origin)

    def test_disallowed_origins_and_preflight_headers(self):
        self.bridge.settings["allowed_origins"] = "https://ui.example.com"
        for origin in ("null", "https://ui.example.com.evil", "https://evil.example.com"):
            status, _, headers = self.call("/api/v1/health", headers={"Origin": origin})
            self.assertEqual(status, 403)
            self.assertNotIn("Access-Control-Allow-Origin", headers)
        status, _, _ = self.call("/api/v1/session", "OPTIONS", headers={"Origin": "https://ui.example.com", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "x-unexpected"})
        self.assertEqual(status, 403)

    def test_bearer_events_and_expiry(self):
        origin = "https://ui.example.com"
        self.bridge.settings["allowed_origins"] = origin
        _, login, _ = self.call("/api/v1/auth/login", "POST", {"token": "test-token", "mode": "bearer"}, {"Origin": origin})
        sid = login["data"]["session_token"]
        self.bridge.store.publish("status.updated", {"resource": "status"})
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request("GET", "/api/v1/events?cursor=" + login["cursor"], headers={"Origin": origin, "Authorization": "Bearer " + sid})
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Access-Control-Allow-Origin"), origin)
        lines = [response.readline().decode() for _ in range(6)]
        self.assertIn("event: status.updated\n", lines)
        response.close(); connection.close()
        self.bridge.auth.sessions[sid]["expires"] = 0
        self.assertEqual(self.call("/api/v1/session", headers={"Origin": origin, "Authorization": "Bearer " + sid})[0], 401)


if __name__ == "__main__":
    unittest.main()
