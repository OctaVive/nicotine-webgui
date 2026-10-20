#!/usr/bin/env python3
"""Real plugin load/reload and HTTP tests against an isolated, offline profile.

Run with pynicotine importable (e.g. PYTHONPATH pointing at its extracted wheel).
This script never connects to Soulseek or accesses the normal user profile.
"""
import http.client
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    from pynicotine.config import config
    from pynicotine.core import core
    from pynicotine.events import events
    with tempfile.TemporaryDirectory(prefix="nicotine-webgui-integration-") as temporary:
        root = Path(temporary)
        config.set_config_file(str(root / "config/config"))
        config.set_data_folder(str(root / "data"))
        # Start core with all data isolated, but no network thread or CLI.
        core.init_components(enabled_components={"users", "notifications", "network_filter", "statistics", "search",
                             "downloads", "uploads", "interests", "userbrowse", "userinfo", "buddies", "chatrooms",
                             "privatechat", "pluginhandler", "shares"})
        events.connect("log-message", lambda _fmt, message, *args: print(message, flush=True))
        core.pluginhandler._start()
        config.sections["server"]["auto_connect_startup"] = False
        plugin_folder = root / "data/plugins/nicotine_webui"
        shutil.copytree(ROOT / "plugin", plugin_folder)
        config.sections["plugins"]["nicotine_webui"] = {"port": 0, "token": "integration-only", "allowed_origins": "https://ui.example.test"}
        # Plugin settings require a nonzero port; reserve one for the isolated test.
        import socket
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        config.sections["plugins"]["nicotine_webui"]["port"] = port
        assert core.pluginhandler.enable_plugin("nicotine_webui"), "Plugin failed to load"
        plugin = core.pluginhandler.enabled_plugins["nicotine_webui"]
        core.users.login_username = "self-test"
        plugin.outgoing_public_chat_notification("music", "echoed once")
        plugin.incoming_public_chat_notification("music", "self-test", "echoed once")
        own_history = plugin.bridge.store.snapshot("room/music")["data"]
        assert len(own_history["items"]) == 1 and own_history["unread"] == 0
        core.users.login_username = None
        outcome = []

        def exercise():
            try:
                def request(path, method="GET", body=None, cookie="", csrf="", extra=None):
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    connection.request(method, "/api/v1" + path, json.dumps(body or {}) if method != "GET" else None,
                                       {"Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json", "Cookie": cookie, "X-CSRF-Token": csrf, **(extra or {})})
                    response = connection.getresponse()
                    value = json.loads(response.read())
                    headers, status = dict(response.getheaders()), response.status
                    connection.close()
                    assert status == 200, (status, value)
                    return value, headers
                login, headers = request("/auth/login", "POST", {"token": "integration-only"})
                cookie = headers["Set-Cookie"].split(";")[0]
                for domain in ("/status", "/downloads", "/uploads", "/rooms", "/private", "/buddies", "/shares", "/settings", "/statistics"):
                    request(domain, cookie=cookie)
                request("/transfers/limits", "PATCH", {"downloadlimit": 1234}, cookie, login["data"]["csrf"])
                snapshot, _ = request("/transfers/limits", cookie=cookie)
                assert snapshot["data"]["downloadlimit"] == 1234
                csrf = login["data"]["csrf"]
                request("/buddies", "POST", {"username": "offline-test-user"}, cookie, csrf)
                request("/buddies/offline-test-user", "PATCH", {"note": "integration", "trusted": True}, cookie, csrf)
                buddy_state, _ = request("/buddies", cookie=cookie)
                assert buddy_state["data"][0]["note"] == "integration"
                request("/buddies/offline-test-user", "DELETE", {}, cookie, csrf)
                request("/interests/likes", "POST", {"item": "ambient"}, cookie, csrf)
                request("/interests/likes", "DELETE", {"item": "ambient"}, cookie, csrf)
                request("/wishlist", "POST", {"term": "ambient test"}, cookie, csrf)
                request("/wishlist/ambient%20test", "DELETE", {}, cookie, csrf)
                request("/downloads", "POST", {"username": "offline-test-user", "virtual_path": "Music\\test.flac", "size": 123}, cookie, csrf)
                downloads, _ = request("/downloads", cookie=cookie)
                transfer_id = downloads["data"][0]["id"]
                for action in ("pause", "resume", "cancel", "clear"):
                    request("/downloads/actions", "POST", {"ids": [transfer_id], "action": action}, cookie, csrf)
                request("/settings", "PATCH", {"server": {"autoaway": 10}}, cookie, csrf)
                origin = {"Origin": "https://ui.example.test"}
                remote, remote_headers = request("/auth/login", "POST", {"token": "integration-only", "mode": "bearer"}, extra=origin)
                assert "Set-Cookie" not in remote_headers
                assert remote_headers["Access-Control-Allow-Origin"] == origin["Origin"]
                bearer = {**origin, "Authorization": "Bearer " + remote["data"]["session_token"]}
                request("/status", extra=bearer)
                request("/transfers/limits", "PATCH", {"downloadlimit": 4321}, csrf=remote["data"]["csrf"], extra=bearer)
                request("/auth/logout", "POST", csrf=remote["data"]["csrf"], extra=bearer)
                outcome.append(True)
            except Exception as error:
                outcome.append(error)
        worker = threading.Thread(target=exercise, daemon=True)
        worker.start()
        deadline = time.monotonic() + 20
        while worker.is_alive() and time.monotonic() < deadline:
            events.process_thread_events()
            time.sleep(.01)
        worker.join(.1)
        assert outcome and outcome[0] is True, outcome
        assert plugin.bridge.adapter.callback_errors == 0, "Event callback errors"
        old_bridge = plugin.bridge
        assert core.pluginhandler.disable_plugin("nicotine_webui", is_permanent=False)
        assert not old_bridge.server.thread.is_alive()
        assert core.pluginhandler.enable_plugin("nicotine_webui"), "Reload failed to rebind the port"
        plugin = core.pluginhandler.enabled_plugins["nicotine_webui"]
        assert plugin.bridge.store.instance != old_bridge.store.instance
        core.pluginhandler.disable_plugin("nicotine_webui", is_permanent=False)
        print("PASS: real Nicotine+ plugin load, snapshots, main-thread mutation, unload, and port rebind")


if __name__ == "__main__":
    main()
