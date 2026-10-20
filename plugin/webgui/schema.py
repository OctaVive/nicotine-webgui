"""OpenAPI 3.1 contract. JSON is also a valid YAML representation."""
from .router import ROUTES


def obj(properties, required=None):
    return {"type": "object", "properties": properties, "required": list(properties) if required is None else required}


def ref(name):
    return {"$ref": "#/components/schemas/" + name}


STRING, NUMBER, BOOLEAN = {"type": "string"}, {"type": "number"}, {"type": "boolean"}
FILE_PROPERTIES = {"id": STRING, "username": STRING, "virtual_path": STRING, "size": NUMBER,
                   "speed": NUMBER, "queue": NUMBER, "bitrate": {"type": ["number", "null"]}}
MODELS = {
    "Status": obj({"connected": BOOLEAN, "username": {"type": ["string", "null"]}, "away": BOOLEAN,
                   "download_speed": NUMBER, "upload_speed": NUMBER}),
    "Session": obj({"csrf": STRING, "expires": NUMBER, "capabilities": {"type": "array", "items": STRING},
                    "version": STRING, "nicotine_version": STRING}),
    "FileRow": obj(FILE_PROPERTIES, ["id", "username", "virtual_path", "size"]),
    "Transfer": obj({**FILE_PROPERTIES, "status": STRING, "current_byte_offset": NUMBER,
                     "time_left": NUMBER, "queue_position": NUMBER},
                    ["id", "username", "virtual_path", "size", "status", "current_byte_offset", "time_left", "queue_position"]),
    "Results": obj({"items": {"type": "array", "items": ref("FileRow")}, "truncated": BOOLEAN,
                    "total": NUMBER, "next_cursor": {"type": ["string", "null"]}}, ["items", "truncated"]),
    "Search": obj({"token": NUMBER, "term": STRING, "mode": STRING}),
    "Message": obj({"id": NUMBER, "user": STRING, "message": STRING, "ts": NUMBER, "outgoing": BOOLEAN}),
    "History": obj({"items": {"type": "array", "items": ref("Message")}, "unread": NUMBER, "truncated": BOOLEAN}),
    "Room": obj({"name": STRING, "users": {"type": "array", "items": obj({"username": STRING, "status": NUMBER})},
                 "tickers": {"type": "object", "additionalProperties": STRING}}),
    "Buddy": obj({"username": STRING, "note": STRING, "notify_status": BOOLEAN, "is_prioritized": BOOLEAN,
                  "is_trusted": BOOLEAN, "last_seen": STRING, "status": NUMBER},
                 ["username", "note", "notify_status", "is_prioritized", "is_trusted", "status"]),
    "Share": obj({"id": STRING, "path": STRING, "permission": STRING}),
    "Plugin": obj({"name": STRING, "enabled": BOOLEAN, "protected": BOOLEAN}),
    "Notice": obj({"id": NUMBER, "message": STRING, "title": {"type": ["string", "null"]}, "read": BOOLEAN, "ts": NUMBER},
                  ["id", "message", "read", "ts"]),
    "Log": obj({"message": STRING, "level": STRING, "ts": NUMBER}),
}
RESPONSES = {"/status": ref("Status"), "/session": ref("Session"), "/searches/{name}": ref("Results"),
             "/users/{name}/browse": ref("Results"), "/rooms/{name}/messages": ref("History"),
             "/private/{name}/messages": ref("History")}
for path, name in {"/downloads": "Transfer", "/uploads": "Transfer", "/searches": "Search", "/rooms": "Room",
                   "/buddies": "Buddy", "/shares": "Share", "/plugins": "Plugin",
                   "/notifications": "Notice", "/logs": "Log"}.items():
    RESPONSES[path] = {"type": "array", "items": ref(name)}


def specification():
    paths = {}
    extra = [("GET", "/health"), ("GET", "/meta"), ("GET", "/diagnostics"),
             ("GET", "/session"), ("GET", "/openapi.json"), ("GET", "/events"),
             ("POST", "/auth/login"), ("POST", "/auth/logout")]
    for method, path in [(r[0], r[1]) for r in ROUTES] + extra:
        operation = {"operationId": method.lower() + path.replace("/", "_").replace("{", "").replace("}", "").replace("-", "_"),
                     "responses": {"200": {"description": "Success", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Envelope"}}}},
                                   "400": {"description": "Invalid input"}, "401": {"description": "Authentication required"},
                                   "403": {"description": "Forbidden"}, "409": {"description": "State conflict"},
                                   "429": {"description": "Rate limited"}, "503": {"description": "Busy or unavailable"}},
                     "security": [{"session": []}]}
        if "{name}" in path:
            operation["parameters"] = [{"name": "name", "in": "path", "required": True, "schema": {"type": "string"}}]
        if method != "GET":
            operation["responses"]["202"] = {"description": "Command running; poll /commands/{command_id}"}
            operation.setdefault("parameters", []).append({"name": "X-CSRF-Token", "in": "header", "required": path != "/auth/login", "schema": {"type": "string"}})
            schema = {"type": "object"}
            if path == "/auth/login":
                schema = {"type": "object", "required": ["token"], "properties": {"token": {"type": "string"}}}
            if path == "/searches" and method == "POST":
                schema = {"$ref": "#/components/schemas/SearchInput"}
            if path.endswith("/messages"):
                schema = {"type": "object", "required": ["message"], "properties": {"message": {"type": "string", "minLength": 1, "maxLength": 4000}}}
            operation["requestBody"] = {"required": True, "content": {"application/json": {"schema": schema}}}
        if path in {"/health", "/auth/login"}:
            operation["security"] = []
        if path == "/health":
            operation["responses"]["200"]["content"]["application/json"]["schema"] = {"type": "object", "required": ["status", "version", "connected", "uptime"]}
        if path == "/events":
            operation["responses"]["200"] = {"description": "Revisioned SSE stream; resync requires snapshot refetch", "content": {"text/event-stream": {"schema": {"type": "string"}}}}
        if method == "GET" and path in RESPONSES:
            operation["responses"]["200"]["content"]["application/json"]["schema"] = {
                "allOf": [ref("Envelope"), {"properties": {"data": RESPONSES[path]}}]}
        paths[path] = {**paths.get(path, {}), method.lower(): operation}
    result = {"openapi": "3.1.0", "info": {"title": "Nicotine Web GUI", "version": "0.1.0"},
            "servers": [{"url": "/api/v1"}], "paths": paths,
            "components": {"securitySchemes": {"session": {"type": "apiKey", "in": "cookie", "name": "npw_session"}},
                           "schemas": {
                               "Envelope": {"type": "object", "required": ["ok", "data", "revision", "instance", "cursor"], "properties": {
                                   "ok": {"const": True}, "data": {}, "revision": {"type": "integer"}, "instance": {"type": "string"}, "cursor": {"type": "string"}}},
                               "SearchInput": {"type": "object", "required": ["term"], "properties": {
                                   "term": {"type": "string", "minLength": 1, "maxLength": 500}, "mode": {"enum": ["global", "rooms", "buddies", "user"]},
                                   "room": {"type": "string"}, "users": {"type": "array", "items": {"type": "string"}}}}}}}
    result["components"]["schemas"].update(MODELS)
    return result
