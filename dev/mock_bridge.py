#!/usr/bin/env python3
"""Deterministic demo server. No account, network engine, or user profile."""
import argparse
from copy import deepcopy
import queue
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin"))
from webgui.bridge import Bridge, DEFAULTS
from webgui.ingest import DOMAINS
from webgui.serializers import resource_id
from webgui.errors import APIError


class FakeAdapter:
    version = "3.3.6 (demo)"

    def __init__(self):
        self.pending = queue.Queue()
        self.callbacks = {}
        self.repeating = []
        self.state = {domain: [] for domain in DOMAINS}
        self.state.update(status={"connected": True, "username": "listener", "away": False, "download_speed": 0, "upload_speed": 0},
                          limits={"downloadlimit": 1000, "uploadlimit": 1000, "use_download_speed_limit": "unlimited", "use_upload_speed_limit": "unlimited", "uploadslots": 2, "useupslots": True},
                          available=["music", "electronic", "jazz"], rooms=[{"name": "music", "users": [{"username": "alice", "status": 2}], "tickers": {}}],
                          private=[{"name": "alice"}], settings={"server": {"autoaway": 15}, "transfers": {"usernamesubfolders": False}},
                          interests={"likes": ["ambient", "jazz"], "dislikes": []}, statistics={"downloaded_size": 0, "uploaded_size": 0},
                          plugins=[{"name": "nicotine_webui", "enabled": True, "protected": True}])
        self.bridge = None

    def invoke(self, callback):
        self.pending.put(callback)

    def subscribe(self, name, callback):
        self.callbacks.setdefault(name, []).append(callback)

    def repeat(self, seconds, callback):
        self.repeating.append(callback)

    def stop(self):
        self.repeating.clear()

    def emit(self, name, *args):
        for callback in self.callbacks.get(name, []):
            callback(*args)

    def snapshot(self, domain):
        return deepcopy(self.state[domain])

    def tick(self):
        try:
            self.pending.get(timeout=.05)()
        except queue.Empty:
            pass
        for callback in self.repeating:
            callback()

    def execute(self, command, body, name=None):
        from types import SimpleNamespace
        if command in {"connect", "disconnect"}:
            self.state["status"]["connected"] = command == "connect"
        elif command == "away":
            self.state["status"]["away"] = body["away"]
        elif command == "search":
            token = max([s["token"] for s in self.state["searches"]] + [0]) + 1
            self.state["searches"].append({"token": token, "term": body["term"], "mode": body.get("mode", "global")})
            msg = SimpleNamespace(token=token, username="alice", ulspeed=512000, inqueue=0,
                                  list=[(1, f"Music\\{body['term']}\\Track {i + 1:04}.flac", 31457280, "flac", {0: 900, 1: 240}) for i in range(10000)])
            self.emit("file-search-response", msg)
            return {"token": token}
        elif command == "remove-search":
            self.state["searches"] = [s for s in self.state["searches"] if str(s["token"]) != name]
        elif command == "download":
            self.state["downloads"].append({**body, "id": resource_id(body["username"], body["virtual_path"]),
                                           "status": "Queued", "current_byte_offset": 0, "speed": 0, "time_left": 0, "queue_position": 1})
        elif command in {"downloads", "uploads"}:
            for row in self.state[command]:
                if row["id"] in body["ids"]:
                    row["status"] = {"pause": "Paused", "resume": "Queued", "retry": "Queued", "cancel": "Cancelled"}.get(body["action"], row["status"])
            if body["action"] == "clear":
                self.state[command] = [r for r in self.state[command] if r["id"] not in body["ids"]]
        elif command == "limits":
            self.state["limits"].update(body)
        elif command == "join":
            if not any(r["name"] == body["name"] for r in self.state["rooms"]):
                self.state["rooms"].append({"name": body["name"], "users": [], "tickers": {}})
        elif command == "leave":
            self.state["rooms"] = [r for r in self.state["rooms"] if r["name"] != name]
        elif command in {"room-message", "private-message"}:
            kind = "room" if command == "room-message" else "private"
            self.bridge.ingest.message(kind, name, "listener", body["message"], True)
            self.bridge.ingest.message(kind, name, "alice", "Thanks for sharing! " + body["message"])
        elif command == "buddy-add":
            self.state["buddies"].append({"username": body["username"], "note": "", "notify_status": False, "is_prioritized": False, "is_trusted": False, "status": 2})
        elif command == "buddy-remove":
            self.state["buddies"] = [b for b in self.state["buddies"] if b["username"] != name]
        elif command == "browse":
            self.bridge.store.put("browse/" + name, {"items": [{"id": "demo-file", "username": name, "virtual_path": "Music\\Example.flac", "size": 31457280}], "truncated": False}, "browse.updated")
        elif command == "profile":
            self.bridge.store.put("profile/" + name, {"username": name, "description": "Welcome to my collection. Ambient, jazz, and everything in between.", "slots": 3, "queue": 0}, "user.info")
        elif command == "recommendations":
            self.bridge.store.put("recommendations", {"recommendations": {"ambient": 42, "jazz": 21}})
        else:
            raise APIError(409, "demo", "This action is not available in the demo adapter")
        return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8181)
    parser.add_argument("--token", default="demo")
    args = parser.parse_args()
    adapter = FakeAdapter()
    bridge = Bridge(adapter, {**DEFAULTS, "port": args.port, "token": args.token}, Path(__file__).resolve().parents[1] / "web/dist")
    adapter.bridge = bridge
    bridge.start()
    bridge.ingest.message("room", "music", "alice", "Welcome! What are you listening to today?")
    print(f"Demo bridge: http://127.0.0.1:{args.port} (token supplied by --token; default: demo)", flush=True)
    try:
        while True:
            adapter.tick()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()


if __name__ == "__main__":
    main()
