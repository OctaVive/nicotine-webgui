import os
import secrets

from pynicotine.pluginsystem import BasePlugin

# Nicotine+ adds the plugin folder to sys.path but does not register the
# entrypoint as a package in sys.modules. Its loader requires absolute imports.
from webgui.adapter import Adapter
from webgui.bridge import Bridge, DEFAULTS


class Plugin(BasePlugin):
    def __init__(self):
        super().__init__()
        self.settings = dict(DEFAULTS)
        self.metasettings = {key: {"description": key.replace("_", " ").title(),
                                  "type": "int" if isinstance(value, int) else "str"}
                             for key, value in DEFAULTS.items()}
        self.bridge = None

    def init(self):
        adapter = Adapter()
        settings = dict(self.settings)
        for key in ("host", "port", "token", "trusted_hosts"):
            env = os.environ.get("NICOTINE_WEBUI_" + key.upper())
            if env is not None:
                settings[key] = int(env) if key == "port" else env
        if not settings["token"]:
            self.settings["token"] = settings["token"] = secrets.token_urlsafe(32)
            adapter.save()
        if settings["host"] not in {"127.0.0.1", "0.0.0.0"}:
            raise ValueError("Web GUI host must be 127.0.0.1 or 0.0.0.0")
        if not 1 <= settings["port"] <= 65535:
            raise ValueError("Invalid Web GUI port")
        for key in ("result_limit", "history_limit", "log_limit", "search_limit", "conversation_limit"):
            if not isinstance(settings[key], int) or not 1 <= settings[key] <= 100000:
                raise ValueError("Invalid Web GUI retention limit: " + key)
        self.bridge = Bridge(adapter, settings)
        try:
            self.bridge.start()
        except Exception:
            self.bridge.stop()
            self.bridge = None
            raise
        self.log("Web GUI listening on port %s; login token is in plugin preferences", settings["port"])

    def disable(self):
        if self.bridge:
            self.bridge.stop()
            self.bridge = None

    shutdown_notification = disable

    def incoming_public_chat_notification(self, room, user, line):
        if self.bridge:
            self.bridge.adapter.guarded(self.bridge.ingest.message)("room", room, user, line, user == self.bridge.adapter.username())

    def outgoing_public_chat_notification(self, room, line):
        # Room messages are echoed by the server through the incoming callback.
        # Recording both notifications would duplicate our own messages.
        pass

    def incoming_private_chat_notification(self, user, line):
        if self.bridge:
            self.bridge.adapter.guarded(self.bridge.ingest.message)("private", user, user, line)

    def outgoing_private_chat_notification(self, user, line):
        if self.bridge:
            self.bridge.adapter.guarded(self.bridge.ingest.message)("private", user, self.bridge.adapter.username(), line, True)
