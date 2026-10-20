import sys
from pathlib import Path
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "plugin"), str(ROOT / "dev")]
from webgui.actions import Actions
from webgui.auth import Auth
from webgui.errors import APIError
from webgui.store import Store


class StoreTests(unittest.TestCase):
    def test_snapshot_and_subscribe_have_no_gap(self):
        store = Store()
        store.put("status", {"connected": False})
        snapshot = store.snapshot()
        store.put("status", {"connected": True})
        client, replay = store.subscribe(snapshot["cursor"])
        self.assertEqual(len(replay), 1)
        store.put("status", {"connected": False})
        self.assertEqual(client.get_nowait()["id"], store.cursor())
        snapshot["data"]["status"]["connected"] = "changed"
        self.assertFalse(store.snapshot("status")["data"]["connected"])

    def test_expired_and_wrong_instance_cursor_require_resync(self):
        store = Store(replay_limit=2)
        cursor = store.cursor()
        for i in range(3):
            store.publish("test", i)
        for old in (cursor, "another:3", "bad", store.instance + ":100"):
            client, replay = store.subscribe(old)
            self.assertEqual(replay[0]["event"], "resync")
            store.unsubscribe(client)

    def test_slow_client_overflow_and_shutdown(self):
        store = Store(queue_limit=2)
        client, _ = store.subscribe(store.cursor())
        for i in range(3):
            store.publish("test", i)
        self.assertEqual(client.get_nowait()["event"], "resync")
        self.assertEqual(store.dropped, 1)
        store.close()
        self.assertIsNone(client.get_nowait())


class AuthTests(unittest.TestCase):
    def test_expiry_csrf_and_logout(self):
        auth = Auth("secret")
        sid, session = auth.login("secret")
        self.assertEqual(auth.session("npw_session=" + sid)[1], session)
        with self.assertRaises(APIError):
            auth.check_csrf(session, "wrong")
        auth.check_csrf(session, session["csrf"])
        auth.logout(sid)
        with self.assertRaises(APIError):
            auth.session("npw_session=" + sid)
        sid, _ = auth.login("secret")
        auth.sessions[sid]["expires"] = 0
        with self.assertRaises(APIError):
            auth.session("npw_session=" + sid)

    def test_login_rate_is_bounded(self):
        auth = Auth("secret")
        for _ in range(5):
            with self.assertRaises(APIError) as caught:
                auth.login("wrong")
            self.assertEqual(caught.exception.status, 401)
        with self.assertRaises(APIError) as caught:
            auth.login("secret")
        self.assertEqual(caught.exception.status, 429)


class ActionTests(unittest.TestCase):
    def test_timed_out_pending_command_never_runs(self):
        pending, effects = [], []
        actions = Actions(pending.append, timeout=.001)
        with self.assertRaises(APIError) as caught:
            actions.execute(lambda: effects.append("bad"))
        self.assertEqual(caught.exception.status, 503)
        pending[0]()
        self.assertEqual(effects, [])

    def test_started_command_is_polled_without_repeating(self):
        started, release = threading.Event(), threading.Event()
        def invoke(callback):
            threading.Thread(target=callback, daemon=True).start()
            started.wait(1)
        actions = Actions(invoke, timeout=.001)
        def callback():
            started.set()
            release.wait(1)
            return {"value": 42}
        status, result = actions.execute(callback)
        self.assertEqual(status, 202)
        self.assertEqual(actions.status(result["command_id"])["state"], "running")
        release.set()
        future = actions.commands[result["command_id"]]
        self.assertEqual(future.result(1), {"value": 42})
        self.assertEqual(actions.status(result["command_id"])["state"], "completed")


if __name__ == "__main__":
    unittest.main()
