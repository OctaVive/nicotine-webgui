"""Explicit API surface shared with the OpenAPI generator."""
import re
from urllib.parse import unquote

from .errors import APIError, integer

# method, path, operation, target. Parameters match one encoded URL segment.
ROUTES = [
    ("GET", "/status", "read", "status"), ("GET", "/searches", "read", "searches"),
    ("POST", "/connect", "command", "connect"), ("POST", "/disconnect", "command", "disconnect"),
    ("POST", "/away", "command", "away"), ("POST", "/searches", "command", "search"),
    ("GET", "/searches/{name}", "search", "search/"),
    ("DELETE", "/searches/{name}", "command", "remove-search"),
    ("POST", "/searches/{name}/downloads", "selection", "download"),
    ("POST", "/searches/{name}/folder-downloads", "selection", "folder-download"),
    ("GET", "/downloads", "read", "downloads"), ("GET", "/uploads", "read", "uploads"),
    ("POST", "/downloads", "command", "download"),
    ("POST", "/downloads/actions", "command", "downloads"),
    ("POST", "/uploads/actions", "command", "uploads"),
    ("GET", "/transfers/limits", "read", "limits"), ("PATCH", "/transfers/limits", "command", "limits"),
    ("GET", "/rooms", "read", "rooms"), ("GET", "/rooms/available", "read", "available"),
    ("POST", "/rooms", "command", "join"), ("DELETE", "/rooms/{name}", "command", "leave"),
    ("GET", "/rooms/{name}/messages", "history", "room/"),
    ("GET", "/rooms/{name}/users", "room-users", "rooms"),
    ("POST", "/rooms/{name}/messages", "command", "room-message"),
    ("POST", "/rooms/{name}/commands", "command", "room-command"),
    ("POST", "/rooms/{name}/read", "read-ack", "room"),
    ("POST", "/rooms/{name}/history", "backfill", "room"),
    ("GET", "/private", "read", "private"), ("GET", "/private/{name}/messages", "history", "private/"),
    ("POST", "/private/{name}/messages", "command", "private-message"),
    ("POST", "/private/{name}/read", "read-ack", "private"),
    ("POST", "/private/{name}/history", "backfill", "private"),
    ("GET", "/unread", "read", "unread"),
    ("GET", "/chat/commands", "read", "chat_commands"),
    ("GET", "/notifications", "read", "notifications"),
    ("POST", "/notifications/read", "notifications-read", "notifications"),
    ("GET", "/logs", "read", "logs"), ("GET", "/bridge/settings", "read", "bridge/settings"),
    ("GET", "/commands/{name}", "command-status", "commands"),
    ("GET", "/users/{name}/browse", "browse", "browse/"),
    ("GET", "/users/{name}/picture", "read-named", "picture/"),
    ("POST", "/users/{name}/browse", "command", "browse"),
    ("POST", "/users/{name}/downloads", "command", "download"),
    ("POST", "/users/{name}/folder-downloads", "command", "folder-download"),
    ("GET", "/users/{name}", "read-named", "profile/"),
    ("POST", "/users/{name}/refresh", "command", "profile"),
    ("GET", "/buddies", "read", "buddies"), ("POST", "/buddies", "command", "buddy-add"),
    ("PATCH", "/buddies/{name}", "command", "buddy-update"),
    ("DELETE", "/buddies/{name}", "command", "buddy-remove"),
    ("GET", "/interests", "read", "interests"),
    ("POST", "/interests/{name}", "command", "interest-add"),
    ("DELETE", "/interests/{name}", "command", "interest-remove"),
    ("GET", "/recommendations", "read", "recommendations"),
    ("POST", "/recommendations", "command", "recommendations"),
    ("GET", "/wishlist", "read", "wishlist"), ("POST", "/wishlist", "command", "wish-add"),
    ("DELETE", "/wishlist/{name}", "command", "wish-remove"),
    ("GET", "/shares", "read", "shares"), ("POST", "/shares", "command", "share-add"),
    ("GET", "/shares/status", "read", "shares/status"),
    ("POST", "/shares/rescan", "command", "rescan"), ("POST", "/shares/rebuild", "command", "rebuild"),
    ("DELETE", "/shares/{name}", "command", "share-remove"),
    ("GET", "/plugins", "read", "plugins"), ("POST", "/plugins/{name}", "command", "plugin"),
    ("GET", "/plugins/{name}/settings", "plugin-settings", "plugin-settings"),
    ("PATCH", "/plugins/{name}/settings", "command", "plugin-settings"),
    ("GET", "/settings", "read", "settings"), ("PATCH", "/settings", "command", "settings"),
    ("GET", "/statistics", "read", "statistics"),
] + [("POST", "/users/{name}/" + action, "command", action) for action in ("ignore", "unignore", "ban", "unban")]


def match(method, path):
    for verb, template, operation, target in ROUTES:
        if method != verb:
            continue
        pattern = re.escape(template).replace(re.escape("{name}"), "([^/]+)")
        found = re.fullmatch(pattern, path)
        if found:
            name = unquote(found.group(1)) if found.groups() else None
            if name is not None and ("\x00" in name or len(name) > 4096):
                raise APIError(400, "validation", "Invalid resource name")
            return operation, target, name
    raise APIError(404, "not_found", "Unknown API route")


def query_int(query, key, default, maximum, minimum=0):
    try:
        value = int(query.get(key, [default])[0])
    except (TypeError, ValueError):
        raise APIError(400, "validation", "Invalid " + key) from None
    return integer(value, key, minimum=minimum, maximum=maximum)


def dispatch(bridge, method, path, body, query):
    operation, target, name = match(method, path)
    if operation == "command-status":
        return 200, bridge.envelope(bridge.actions.status(name))
    if operation in {"command", "read-ack", "notifications-read", "selection", "backfill", "plugin-settings"}:
        def execute():
            if operation == "plugin-settings":
                return bridge.adapter.plugin_settings(name)
            if operation == "backfill":
                return bridge.ingest.backfill(target, name)
            if operation == "read-ack":
                through = integer(body.get("through"), "through", maximum=2**63 - 1)
                return bridge.ingest.read(target, name, through)
            if operation == "notifications-read":
                return bridge.ingest.notifications_read()
            if operation == "selection":
                ids = body.get("ids")
                if not isinstance(ids, list) or not 1 <= len(ids) <= 1000 or not all(isinstance(i, str) for i in ids):
                    raise APIError(400, "validation", "Select 1–1000 result IDs")
                result = bridge.ingest.results.get(name)
                if result is None or any(i not in result["items"] for i in ids):
                    raise APIError(409, "conflict", "Selected results have expired")
                folders = set()
                for result_id in ids:
                    row = dict(result["items"][result_id])
                    if target == "folder-download":
                        row["virtual_path"] = row["virtual_path"].rsplit("\\", 1)[0]
                        key = (row["username"], row["virtual_path"])
                        if key in folders:
                            continue
                        folders.add(key)
                    bridge.adapter.execute(target, row)
                bridge.ingest.dirty.update(("downloads", "status"))
                bridge.ingest.flush()
                return {"accepted": len(ids)}
            if target == "search" and len(bridge.adapter.snapshot("searches")) >= bridge.settings["search_limit"]:
                raise APIError(409, "limit", "Close an existing search first")
            if target == "download" and name and "ids" in body:
                ids = body["ids"]
                if not isinstance(ids, list) or not 1 <= len(ids) <= 1000 or not all(isinstance(i, str) for i in ids):
                    raise APIError(400, "validation", "Select 1–1000 browse result IDs")
                snapshot = bridge.store.snapshot("browse/" + name)["data"] or {"items": []}
                available = {row["id"]: row for row in snapshot["items"]}
                if any(i not in available for i in ids):
                    raise APIError(409, "conflict", "Browse results expired; refresh the user’s shares")
                for result_id in ids:
                    bridge.adapter.execute("download", available[result_id])
                bridge.ingest.dirty.update(("downloads", "status"))
                bridge.ingest.flush()
                return {"accepted": len(ids)}
            payload = dict(body)
            if target in {"download", "folder-download"} and name:
                payload["username"] = name
            value = bridge.adapter.execute(target, payload, name)
            bridge.ingest.dirty.update(bridge.domains)
            bridge.ingest.flush()
            return value
        status, data = bridge.actions.execute(execute)
        return status, bridge.envelope(data)

    key = target + name if operation in {"search", "browse", "history", "read-named"} else target
    response = bridge.store.snapshot(key)
    data = response["data"]
    if operation == "room-users":
        room = next((r for r in data or [] if r["name"] == name), None)
        if room is None:
            raise APIError(404, "not_found", "Room not found")
        response["data"] = room["users"]
    elif operation == "history":
        data = data or {"items": [], "unread": 0, "truncated": False}
        before = query_int(query, "before", 2**63 - 1, 2**63 - 1, minimum=-(2**63))
        limit = query_int(query, "limit", 100, 500)
        response["data"] = {**data, "items": [m for m in data["items"] if m["id"] < before][-limit:] if limit else []}
    elif operation in {"search", "browse"}:
        data = data or {"items": [], "truncated": False}
        rows = data["items"]
        term = query.get("filter", query.get("q", [""]))[0].casefold()
        rows = [r for r in rows if term in (r["virtual_path"] + " " + r["username"]).casefold()]
        sort = query.get("sort", ["virtual_path"])[0]
        if sort.lstrip("-") not in {"virtual_path", "username", "size", "speed", "id"}:
            raise APIError(400, "validation", "Invalid sort field")
        rows = sorted(rows, key=lambda r: (r.get(sort.lstrip("-")) or 0 if sort.lstrip("-") in {"size", "speed"} else r.get(sort.lstrip("-"), ""), r["id"]), reverse=sort.startswith("-"))
        cursor = query.get("cursor", [None])[0]
        offset = 0
        if cursor:
            try:
                instance, revision, offset_text = cursor.split(":")
                offset = integer(int(offset_text), "cursor", maximum=10000000)
                if instance != response["instance"] or int(revision) != response["resource_revision"]:
                    raise APIError(409, "snapshot_changed", "Results changed; restart pagination from the first page")
            except (TypeError, ValueError):
                raise APIError(400, "validation", "Invalid page cursor") from None
        limit = query_int(query, "limit", 1000, 10000)
        response["data"] = {**data, "items": rows[offset:offset + limit], "total": len(rows),
                            "next_cursor": f"{response['instance']}:{response['resource_revision']}:{offset + limit}" if offset + limit < len(rows) and limit else None}
    elif isinstance(data, list):
        term = query.get("q", [""])[0].casefold()
        if term:
            data = [r for r in data if term in str(r).casefold()]
        for field in ("status", "user", "level"):
            if field in query:
                data = [r for r in data if isinstance(r, dict) and str(r.get("username" if field == "user" else field)) == query[field][0]]
        if "limit" in query:
            limit = query_int(query, "limit", 2000, 10000)
            data = data[-limit:] if limit else []
        response["data"] = data
    return 200, response
