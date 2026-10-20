import time
from pathlib import Path

from . import VERSION
from .actions import Actions
from .auth import Auth
from .ingest import Ingest, DOMAINS
from .store import Store

DEFAULTS = {"host": "127.0.0.1", "port": 8181, "token": "", "history_limit": 500,
            "result_limit": 10000, "log_limit": 2000, "search_limit": 20,
            "conversation_limit": 100, "trusted_hosts": "localhost,127.0.0.1"}


class Bridge:
    domains = DOMAINS

    def __init__(self, adapter, settings, static=None):
        self.adapter, self.settings = adapter, settings
        self.started = time.monotonic()
        self.store = Store()
        self.auth = Auth(settings["token"])
        self.actions = Actions(adapter.invoke)
        self.ingest = Ingest(adapter, self.store, settings)
        self.static = Path(static or Path(__file__).parent / "static").resolve()
        self.server = None

    def start(self):
        from .server import Server
        self.ingest.start()
        self.store.put("bridge/settings", {k: v for k, v in self.settings.items() if k != "token"})
        self.store.put("notifications", [])
        self.store.put("logs", [])
        self.store.put("unread", {})
        self.server = Server(self)
        self.server.start()

    def stop(self):
        self.actions.close()
        self.store.close()
        if self.server:
            self.server.stop()
        self.adapter.stop()

    def envelope(self, data):
        response = self.store.snapshot("__empty__")
        response["data"] = data
        return response

    def meta(self):
        return {"version": VERSION, "nicotine_version": self.adapter.version,
                "capabilities": list(DOMAINS) + ["browse", "profiles", "recommendations"],
                "history": "Bounded in-memory messages with optional background log backfill"}

    def health(self):
        status = self.store.snapshot("status")["data"] or {}
        return {"status": "ok", "version": VERSION, "uptime": time.monotonic() - self.started,
                "connected": status.get("connected", False)}
