"""All access to Nicotine+ internals lives here and runs on its main thread.

The supported baseline is 3.3.6. The web server never touches these objects.
"""
import os
import re
import math

from .errors import APIError, text, integer
from .serializers import transfer

LIMIT_FIELDS = {"downloadlimit", "downloadlimitalt", "uploadlimit", "uploadlimitalt", "uploadslots"}
LIMIT_MODES = {"use_download_speed_limit", "use_upload_speed_limit"}
SETTING_FIELDS = {"server": {"autoaway": int}, "transfers": {"usernamesubfolders": bool}}


class Adapter:
    def __init__(self):
        from pynicotine.core import core
        from pynicotine.config import config
        from pynicotine.events import events, EVENT_NAMES
        from pynicotine import __version__
        self.core, self.config, self.events = core, config, events
        self.event_names, self.version = EVENT_NAMES, __version__
        self.callbacks = []
        self.timers = []
        self.callback_errors = 0
        parts = tuple(int(p) for p in self.version.split(".")[:3])
        if not (3, 3, 6) <= parts < (3, 4, 0):
            raise RuntimeError("Nicotine Web GUI requires Nicotine+ 3.3.6–3.3.x")

    def guarded(self, callback):
        def safe(*args, **kwargs):
            try:
                return callback(*args, **kwargs)
            except Exception:
                # Nicotine+'s event bus does not isolate subscriber failures.
                # Count errors without recursively logging through log-message.
                self.callback_errors += 1
        return safe

    def invoke(self, callback):
        self.events.invoke_main_thread(callback)

    def subscribe(self, name, callback):
        if name in self.event_names:
            callback = self.guarded(callback)
            self.events.connect(name, callback)
            self.callbacks.append((name, callback))

    def repeat(self, seconds, callback):
        self.timers.append(self.events.schedule(seconds, self.guarded(callback), repeat=True))

    def stop(self):
        for timer in self.timers:
            self.events.cancel_scheduled(timer)
        for name, callback in self.callbacks:
            self.events.disconnect(name, callback)
        self.callbacks.clear()

    def save(self):
        self.config.write_configuration()

    def password(self):
        return self.config.sections["server"]["passw"]

    def username(self):
        return self.core.users.login_username

    def history_source(self, kind, name):
        from pynicotine.utils import clean_file
        cfg = self.config.sections["logging"]
        folder = cfg["roomlogsdir" if kind == "room" else "privatelogsdir"]
        return os.path.join(folder, clean_file(name + ".log")), cfg["log_timestamp"], self.core.users.login_username

    def plugin_settings(self, name):
        if name == "nicotine_webui":
            raise APIError(403, "forbidden", "Configure the serving plugin on the host")
        plugin = self.core.pluginhandler.enabled_plugins.get(name)
        if plugin is None:
            raise APIError(409, "conflict", "Enable the plugin before editing settings")
        fields = {}
        for key, meta in plugin.metasettings.items():
            if re.search(r"token|secret|passw|credential|api.?key", key + " " + str(meta.get("description", "")), re.I) or meta.get("type") == "password":
                continue
            value = plugin.settings.get(key)
            if type(value) not in (str, int, bool, float):
                continue
            if isinstance(value, float) and not math.isfinite(value):
                continue
            choices = meta.get("options", [])
            if isinstance(value, str) and (meta.get("type") not in {"dropdown", "radio"}
                                           or not isinstance(choices, (list, tuple)) or value not in choices):
                # Free-form strings may contain credentials under innocuous keys.
                # Edit those locally rather than attempting heuristic redaction.
                continue
            fields[key] = {"value": value, "description": meta.get("description", key), "type": type(value).__name__}
            if isinstance(value, str):
                fields[key]["choices"] = list(choices)
        return fields

    def snapshot(self, domain):
        c, cfg = self.core, self.config.sections
        if domain == "status":
            return {"connected": bool(c.users.login_status), "username": c.users.login_username,
                    "away": c.users.login_status == 1, "privileges": c.users.privileges_left,
                    "download_speed": c.downloads.total_bandwidth, "upload_speed": c.uploads.total_bandwidth}
        if domain in ("downloads", "uploads"):
            return [transfer(t) for t in getattr(c, domain).transfers.values()]
        if domain == "rooms":
            return [{"name": name, "users": [{"username": u, "status": c.users.statuses.get(u, 0)}
                                             for u in sorted(room.users)], "tickers": dict(room.tickers)}
                    for name, room in c.chatrooms.joined_rooms.items()]
        if domain == "available":
            return sorted(c.chatrooms.server_rooms)
        if domain == "private":
            return [{"name": name} for name in c.privatechat.users]
        if domain == "searches":
            return [{"token": s.token, "term": s.term, "mode": s.mode} for s in c.search.searches.values()
                    if not s.is_ignored]
        if domain == "limits":
            return {k: cfg["transfers"][k] for k in LIMIT_FIELDS | LIMIT_MODES | {"useupslots"}}
        if domain == "buddies":
            fields = ("username", "note", "notify_status", "is_prioritized", "is_trusted", "last_seen", "status")
            return [{k: getattr(b, k) for k in fields} for b in c.buddies.users.values()]
        if domain == "interests":
            return {"likes": list(cfg["interests"]["likes"]), "dislikes": list(cfg["interests"]["dislikes"])}
        if domain == "wishlist":
            return list(cfg["server"]["autosearch"])
        if domain == "shares":
            return [{"id": name, "path": path, "permission": kind}
                    for kind, shares in zip(("public", "buddy", "trusted"), c.shares.get_shared_folders())
                    for name, path in shares]
        if domain == "plugins":
            return [{"name": name, "enabled": name in c.pluginhandler.enabled_plugins,
                     "protected": name == "nicotine_webui"} for name in c.pluginhandler.list_installed_plugins()]
        if domain == "chat_commands":
            return sorted(cmd for cmd in c.pluginhandler.get_command_list("chatroom")
                          if cmd.strip("/ ") not in {"quit", "q", "exit", "plugin", "reload"})
        if domain == "settings":
            return {section: {k: cfg[section][k] for k in fields} for section, fields in SETTING_FIELDS.items()}
        if domain == "statistics":
            return dict(cfg["statistics"])
        raise APIError(404, "not_found", "Unknown resource")

    def execute(self, command, body, name=None):
        c = self.core
        if command in {"search", "room-message", "private-message", "room-command", "browse", "profile", "recommendations"} and not c.users.login_status:
            raise APIError(409, "not_connected", "Connect to Soulseek first")
        if command in {"connect", "disconnect"}:
            getattr(c, command)()
            return {}
        if command == "away":
            if not isinstance(body.get("away"), bool):
                raise APIError(400, "validation", "away must be a boolean")
            c.users.set_away_mode(body["away"], save_state=True)
        elif command == "search":
            term = text(body.get("term"), "term", 500)
            mode = body.get("mode", "global")
            if mode not in {"global", "rooms", "buddies", "user"}:
                raise APIError(400, "validation", "Unknown search mode")
            room, users = body.get("room"), body.get("users")
            if mode == "rooms":
                text(room, "room", 24)
            if mode == "user":
                if not isinstance(users, list) or not 1 <= len(users) <= 50:
                    raise APIError(400, "validation", "users must contain 1–50 usernames")
                for user in users:
                    text(user, "username", 30)
            c.search.do_search(term, mode, room=room, users=users, switch_page=False)
            return {"token": c.search.token}
        elif command == "remove-search":
            try:
                token = int(name)
            except ValueError:
                raise APIError(400, "validation", "Search token must be numeric") from None
            c.search.remove_search(token)
        elif command == "download":
            user = text(body.get("username"), "username", 30)
            path = text(body.get("virtual_path"), "virtual_path", 4096)
            size = integer(body.get("size", 0), "size", maximum=2**63 - 1)
            # Local destination paths are deliberately not browser-controlled.
            c.downloads.enqueue_download(user, path, size=size)
        elif command == "folder-download":
            c.downloads.enqueue_folder(text(body.get("username"), "username", 30),
                                      text(body.get("virtual_path"), "virtual_path", 4096))
        elif command in {"downloads", "uploads"}:
            manager = getattr(c, command)
            ids = body.get("ids")
            action = body.get("action")
            allowed = {"retry", "cancel", "clear", "deny"} if command == "uploads" else {"pause", "resume", "retry", "cancel", "clear"}
            if action not in allowed or not isinstance(ids, list) or not 1 <= len(ids) <= 1000 or not all(isinstance(i, str) for i in ids):
                raise APIError(400, "validation", "Invalid transfer action or IDs")
            live = {transfer(t)["id"]: t for t in manager.transfers.values()}
            if any(i not in live for i in ids):
                raise APIError(409, "conflict", "A selected transfer no longer exists")
            selected = [live[i] for i in ids]
            if action in {"retry", "resume"}:
                getattr(manager, "retry_" + command)(selected)
            elif action == "clear":
                getattr(manager, "clear_" + command)(selected)
            else:
                kwargs = {"status": "Paused" if action == "pause" else "Cancelled"}
                if action == "deny":
                    kwargs["denied_message"] = text(body.get("message"), "message", 500)
                getattr(manager, "abort_" + command)(selected, **kwargs)
        elif command == "limits":
            if not body or set(body) - (LIMIT_FIELDS | LIMIT_MODES | {"useupslots"}):
                raise APIError(400, "validation", "Unknown transfer limit")
            for key, value in body.items():
                if key in LIMIT_FIELDS:
                    integer(value, key, maximum=10000000)
                elif key in LIMIT_MODES and value not in {"unlimited", "primary", "alternative"}:
                    raise APIError(400, "validation", "Invalid limit mode")
                elif key == "useupslots" and not isinstance(value, bool):
                    raise APIError(400, "validation", "useupslots must be boolean")
            self.config.sections["transfers"].update(body)
            c.downloads.update_transfer_limits()
            c.uploads.update_transfer_limits()
            self.save()
        elif command in {"join", "leave"}:
            room = text(name or body.get("name"), "room", 24)
            getattr(c.chatrooms, "show_room" if command == "join" else "remove_room")(room)
        elif command in {"room-message", "private-message"}:
            text(name, "recipient", 30)
            message = text(body.get("message"), "message", 4000)
            if command == "room-message" and name not in c.chatrooms.joined_rooms:
                raise APIError(409, "conflict", "Join the room before sending")
            manager = c.chatrooms if command == "room-message" else c.privatechat
            if command == "private-message":
                manager.show_user(name, switch_page=False)
            manager.send_message(name, message)
        elif command == "room-command":
            command_name = text(body.get("command"), "command", 100).lstrip("/")
            args = body.get("args", "")
            if not isinstance(args, str) or len(args) > 4000:
                raise APIError(400, "validation", "Invalid command arguments")
            # Administrative CLI commands are not exposed through room commands.
            if command_name in {"quit", "q", "exit", "plugin", "reload"}:
                raise APIError(403, "forbidden", "Use the host to manage the bridge lifecycle")
            c.pluginhandler.trigger_chatroom_command_event(name, command_name, args)
        elif command in {"ignore", "unignore", "ban", "unban"}:
            getattr(c.network_filter, command + "_user")(text(name, "username", 30))
        elif command == "browse":
            c.userbrowse.browse_user(text(name, "username", 30), new_request=True, switch_page=False)
        elif command == "profile":
            c.userinfo.show_user(text(name, "username", 30), refresh=True, switch_page=False)
        elif command == "buddy-add":
            c.buddies.add_buddy(text(body.get("username"), "username", 30))
        elif command == "buddy-remove":
            c.buddies.remove_buddy(text(name, "username", 30))
        elif command == "buddy-update":
            methods = {"note": c.buddies.set_buddy_note, "notify": c.buddies.set_buddy_notify,
                       "prioritized": c.buddies.set_buddy_prioritized, "trusted": c.buddies.set_buddy_trusted}
            if not body or set(body) - methods.keys():
                raise APIError(400, "validation", "Invalid buddy fields")
            for key, value in body.items():
                if key == "note":
                    if not isinstance(value, str) or len(value) > 2000:
                        raise APIError(400, "validation", "Invalid note")
                elif not isinstance(value, bool):
                    raise APIError(400, "validation", "Buddy flags must be boolean")
            for key, value in body.items():
                methods[key](name, value)
        elif command in {"wish-add", "wish-remove"}:
            getattr(c.search, "add_wish" if command == "wish-add" else "remove_wish")(text(body.get("term") or name, "term", 500))
        elif command in {"interest-add", "interest-remove"}:
            if name not in {"likes", "dislikes"}:
                raise APIError(400, "validation", "Expected likes or dislikes")
            method = ("add" if command == "interest-add" else "remove") + "_thing_i_" + ("like" if name == "likes" else "hate")
            getattr(c.interests, method)(text(body.get("item"), "item", 200))
        elif command == "recommendations":
            c.interests.request_recommendations()
        elif command == "share-add":
            permission = body.get("permission", "public")
            if permission not in {"public", "buddy", "trusted"}:
                raise APIError(400, "validation", "Invalid share permission")
            path = text(body.get("path"), "path", 4096)
            if "name" in body:
                text(body["name"], "name", 200)
            if not os.path.isabs(path) or not os.path.isdir(path):
                raise APIError(400, "validation", "Share must be an existing absolute directory on the host")
            result = c.shares.add_share(path, permission_level=permission, virtual_name=body.get("name"))
            if result is None:
                raise APIError(400, "validation", "Share is not readable")
            self.save()
        elif command == "share-remove":
            c.shares.remove_share(name)
            self.save()
        elif command in {"rescan", "rebuild"}:
            c.shares.rescan_shares(rebuild=command == "rebuild")
        elif command == "plugin":
            if name == "nicotine_webui":
                raise APIError(403, "forbidden", "The serving plugin cannot manage itself")
            action = body.get("action")
            if action not in {"enable", "disable", "reload"} or name not in c.pluginhandler.list_installed_plugins():
                raise APIError(400, "validation", "Invalid plugin or action")
            if not getattr(c.pluginhandler, action + "_plugin")(name) and action != "reload":
                raise APIError(409, "conflict", "Plugin action did not succeed")
        elif command == "plugin-settings":
            available = self.plugin_settings(name)
            if not body or set(body) - available.keys():
                raise APIError(400, "validation", "Unknown or protected plugin settings")
            plugin = c.pluginhandler.enabled_plugins[name]
            for key, value in body.items():
                if type(value) is not type(plugin.settings[key]) or isinstance(value, str) and len(value) > 4000:
                    raise APIError(400, "validation", "Invalid plugin setting type or length")
                if isinstance(value, str) and value not in available[key].get("choices", []):
                    raise APIError(400, "validation", "Choose an available plugin setting value")
                if isinstance(value, (int, float)) and (not math.isfinite(value) or abs(value) > 10**9):
                    raise APIError(400, "validation", "Plugin setting number is outside the supported range")
            plugin.settings.update(body)
            self.save()
        elif command == "settings":
            if not body or set(body) - SETTING_FIELDS.keys():
                raise APIError(400, "validation", "Unknown settings section")
            for section, values in body.items():
                if not isinstance(values, dict) or set(values) - SETTING_FIELDS[section].keys():
                    raise APIError(400, "validation", "Unknown setting")
                for key, value in values.items():
                    if type(value) is not SETTING_FIELDS[section][key]:
                        raise APIError(400, "validation", "Invalid setting type")
                    if key == "autoaway":
                        integer(value, key, maximum=1440)
            for section, values in body.items():
                self.config.sections[section].update(values)
            self.save()
        else:
            raise APIError(404, "not_found", "Unknown command")
        return {}
