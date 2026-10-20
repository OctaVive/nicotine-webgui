"""Main-thread event ingestion. High-frequency events flush every 250 ms."""
import time
import base64
from collections import OrderedDict, deque
from threading import Thread

from .serializers import resource_id

DOMAINS = ("status", "downloads", "uploads", "rooms", "available", "private", "searches", "limits",
           "buddies", "interests", "wishlist", "shares", "plugins", "settings", "statistics", "chat_commands")
EVENT_DOMAINS = {
    "status": ("server-login", "server-disconnect", "user-status", "set-connection-stats"),
    "downloads": ("update-download", "abort-download", "clear-download", "abort-downloads", "clear-downloads"),
    "uploads": ("update-upload", "abort-upload", "clear-upload", "abort-uploads", "clear-uploads"),
    "rooms": ("join-room", "leave-room", "show-room", "remove-room", "user-joined-room", "user-left-room", "ticker-add", "ticker-remove", "ticker-state"),
    "available": ("room-list",), "private": ("private-chat-show-user", "private-chat-remove-user"),
    "searches": ("add-search", "remove-search"), "limits": ("update-download-limits", "update-upload-limits"),
    "buddies": ("add-buddy", "remove-buddy", "buddy-note", "buddy-notify", "buddy-prioritized", "buddy-trusted"),
    "interests": ("add-interest", "remove-interest", "add-dislike", "remove-dislike"),
    "wishlist": ("add-wish", "remove-wish"), "statistics": ("update-stat",),
    "shares": ("shares-scanning", "shares-ready", "shares-unavailable")}


class Ingest:
    def __init__(self, adapter, store, settings):
        self.adapter, self.store, self.settings = adapter, store, settings
        self.dirty = set(DOMAINS)
        self.results = OrderedDict()
        self.histories = OrderedDict()
        self.unread = {}
        self.sequence = 0
        self.logs, self.notifications = deque(maxlen=settings["log_limit"]), deque(maxlen=500)
        self.browse, self.profiles = OrderedDict(), OrderedDict()
        self.started_at = time.time()
        self.backfilled = set()
        self.backfill_pending = set()

    def start(self):
        for domain, names in EVENT_DOMAINS.items():
            for name in names:
                self.adapter.subscribe(name, lambda *a, domain=domain, **kw: self.dirty.add(domain))
        for event in ("server-login", "server-disconnect"):
            self.adapter.subscribe(event, lambda *a, **kw: self.dirty.update(DOMAINS))
        self.adapter.subscribe("user-status", lambda *a, **kw: self.dirty.update(("rooms", "buddies", "private")))
        self.adapter.subscribe("file-search-response", self.search_results)
        self.adapter.subscribe("shared-file-list-response", self.browse_results)
        self.adapter.subscribe("user-info-response", self.profile_result)
        self.adapter.subscribe("recommendations", self.recommendations)
        self.adapter.subscribe("log-message", self.log)
        self.adapter.subscribe("show-notification", self.notification)
        for name in ("shares-scanning", "shares-preparing", "shares-ready", "shares-unavailable"):
            self.adapter.subscribe(name, lambda *a, name=name, **kw: self.store.put("shares/status", {"state": name}, "shares.scan"))
        self.adapter.repeat(.25, self.flush)
        self.flush()

    def flush(self):
        dirty, self.dirty = self.dirty, set()
        for domain in dirty:
            if domain.startswith("search/"):
                token = domain.split("/", 1)[1]
                result = self.results.get(token)
                if result is not None:
                    self.store.put(domain, {"items": list(result["items"].values()), "truncated": result["truncated"]}, "search.results")
            elif domain in DOMAINS:
                self.store.put(domain, self.adapter.snapshot(domain))
        if "searches" in dirty:
            active = {str(s["token"]) for s in self.store.snapshot("searches")["data"]}
            for token in list(self.results):
                if token not in active:
                    del self.results[token]
                    self.store.forget("search/" + token)

    def search_results(self, msg):
        if msg.token is None:
            return
        token = str(msg.token)
        if token not in self.results:
            if len(self.results) >= self.settings["search_limit"]:
                return
            self.results[token] = {"items": OrderedDict(), "truncated": False}
        result = self.results[token]
        for _code, path, size, _ext, attributes, *_ in msg.list:
            key = resource_id(msg.username, path)
            result["items"][key] = {"id": key, "username": msg.username, "virtual_path": path,
                                    "size": size, "speed": msg.ulspeed, "queue": msg.inqueue,
                                    "bitrate": attributes.get(0), "length": attributes.get(1)}
            if len(result["items"]) > self.settings["result_limit"]:
                result["items"].popitem(last=False)
                result["truncated"] = True
        self.dirty.add("search/" + token)

    def message(self, kind, name, user, message, outgoing=False):
        key = f"{kind}/{name}"
        if key not in self.histories:
            if len(self.histories) >= self.settings["conversation_limit"]:
                old, _ = self.histories.popitem(last=False)
                self.unread.pop(old, None)
                self.store.put(old, {"items": [], "unread": 0, "truncated": True}, old.split("/", 1)[0] + ".message")
                self.store.forget(old)
            self.histories[key] = deque(maxlen=self.settings["history_limit"])
        self.histories.move_to_end(key)
        self.sequence += 1
        self.histories[key].append({"id": self.sequence, "user": user, "message": message,
                                    "ts": time.time(), "outgoing": outgoing})
        self.unread[key] = self.unread.get(key, 0) + (not outgoing)
        self.update_history(key)
        self.dirty.add("rooms" if kind == "room" else "private")

    def update_history(self, key):
        rows = list(self.histories.get(key, []))
        self.store.put(key, {"items": rows, "unread": self.unread.get(key, 0),
                             "truncated": len(rows) >= self.settings["history_limit"]}, key.split("/")[0] + ".message")
        self.store.put("unread", dict(self.unread), "private.unread")

    def read(self, kind, name, through):
        key = f"{kind}/{name}"
        if key not in self.histories:
            return {}
        self.unread[key] = sum(not row["outgoing"] and row["id"] > through for row in self.histories.get(key, []))
        self.update_history(key)
        return {}

    def backfill(self, kind, name):
        key = f"{kind}/{name}"
        if key in self.backfilled or key in self.backfill_pending or not hasattr(self.adapter, "history_source"):
            return {}
        if len(self.backfill_pending) >= 2 or len(self.backfilled) >= self.settings["conversation_limit"]:
            return {}
        from .history import read_history
        path, timestamp_format, own = self.adapter.history_source(kind, name)
        self.backfill_pending.add(key)
        def worker():
            rows = read_history(path, timestamp_format, self.settings["history_limit"], own, self.started_at)
            def merge():
                self.backfill_pending.discard(key)
                self.backfilled.add(key)
                if self.store.closed or not rows:
                    return
                if key not in self.histories and len(self.histories) >= self.settings["conversation_limit"]:
                    return
                live = list(self.histories.get(key, []))
                for index, row in enumerate(rows):
                    row["id"] = index - len(rows)
                merged = (rows + live)[-self.settings["history_limit"]:]
                self.histories[key] = deque(merged, maxlen=self.settings["history_limit"])
                self.update_history(key)
            self.adapter.invoke(merge)
        Thread(target=worker, name="NicotineWebHistory", daemon=True).start()
        return {}

    def browse_results(self, msg):
        entries = []
        for folder, files in msg.list:
            for _code, filename, size, _ext, attrs, *_ in files:
                path = folder + "\\" + filename
                entries.append({"id": resource_id(msg.username, path), "username": msg.username,
                                "virtual_path": path, "size": size, "folder": folder})
                if len(entries) >= self.settings["result_limit"]:
                    break
            if len(entries) >= self.settings["result_limit"]:
                break
        self.browse[msg.username] = {"items": entries, "truncated": len(entries) >= self.settings["result_limit"]}
        while len(self.browse) > 20:
            old, _ = self.browse.popitem(last=False)
            self.store.forget("browse/" + old)
        self.store.put("browse/" + msg.username, self.browse[msg.username], "browse.updated")

    def profile_result(self, msg):
        # Picture decoding and file serving are not delegated to the HTTP thread.
        self.profiles[msg.username] = {"username": msg.username, "description": msg.descr,
                                       "slots": msg.totalupl, "queue": msg.queuesize}
        while len(self.profiles) > 100:
            old, _ = self.profiles.popitem(last=False)
            self.store.forget("profile/" + old)
            self.store.forget("picture/" + old)
        self.store.put("profile/" + msg.username, self.profiles[msg.username], "user.info")
        picture = msg.pic
        if picture and len(picture) <= 1048576:
            mime = "image/png" if picture.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg" if picture.startswith(b"\xff\xd8\xff") else "image/gif" if picture.startswith((b"GIF87a", b"GIF89a")) else None
            if mime:
                self.store.put("picture/" + msg.username, {"data_url": "data:" + mime + ";base64," + base64.b64encode(picture).decode()}, "user.info")
                return
        self.store.put("picture/" + msg.username, None, "user.info")

    def recommendations(self, msg):
        self.store.put("recommendations", {"recommendations": msg.recommendations, "unrecommendations": msg.unrecommendations})

    def log(self, timestamp_format, message, title=None, level=None):
        message = str(message)
        for secret in (self.settings.get("token"), getattr(self.adapter, "password", lambda: "")()):
            if secret:
                message = message.replace(secret, "[redacted]")
        self.logs.append({"ts": time.time(), "message": message, "level": level or "info"})
        self.store.put("logs", list(self.logs), "log")

    def notification(self, message, title=None, **kwargs):
        self.sequence += 1
        self.notifications.append({"id": self.sequence, "ts": time.time(), "message": message, "title": title, "read": False})
        self.store.put("notifications", list(self.notifications), "notification")

    def notifications_read(self):
        for row in self.notifications:
            row["read"] = True
        self.store.put("notifications", list(self.notifications), "notification")
        return {}
