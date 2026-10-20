"""Bounded stdlib HTTP server. Static files are confined to the build directory."""
import json
import mimetypes
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Empty
from urllib.parse import urlsplit, parse_qs, unquote

from .errors import APIError
from .router import dispatch


class HTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    block_on_close = False

    def __init__(self, address, bridge):
        self.bridge = bridge
        self.slots = threading.BoundedSemaphore(48)
        self.active = set()
        self.active_lock = threading.Lock()
        super().__init__(address, Handler)

    def process_request(self, request, address):
        if not self.slots.acquire(False):
            request.close()
            return
        with self.active_lock:
            self.active.add(request)
        try:
            super().process_request(request, address)
        except Exception:
            with self.active_lock:
                self.active.discard(request)
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            with self.active_lock:
                self.active.discard(request)
            self.slots.release()

    def handle_error(self, request, address):
        # Request failures never propagate into Nicotine+ or print request data.
        pass


class Server:
    def __init__(self, bridge):
        self.http = HTTPServer((bridge.settings["host"], bridge.settings["port"]), bridge)
        # Used by the HTTPS demo/test fixture. Production TLS terminates at the
        # Nicotine+ host's reverse proxy; no forwarded headers are trusted here.
        if getattr(bridge, "tls_context", None):
            self.http.socket = bridge.tls_context.wrap_socket(self.http.socket, server_side=True)
        self.thread = threading.Thread(target=self.http.serve_forever, name="NicotineWebHTTP", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.http.shutdown()
        with self.http.active_lock:
            for connection in list(self.http.active):
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                connection.close()
        self.http.server_close()
        self.thread.join(timeout=2)


class Handler(BaseHTTPRequestHandler):
    server_version = "NicotineWeb"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.handle_api()

    do_POST = do_PATCH = do_DELETE = do_OPTIONS = do_GET

    def headers_common(self, content_type):
        self.send_header("Vary", "Origin")
        if getattr(self, "cors_origin", None):
            self.send_header("Access-Control-Allow-Origin", self.cors_origin)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' https:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header("Cache-Control", "no-store")

    def respond(self, status, payload, cookie=None):
        raw = json.dumps(payload, ensure_ascii=True, allow_nan=False).encode()
        self.send_response(status)
        self.headers_common("application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        if status in {429, 503}:
            self.send_header("Retry-After", "5")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True

    def validate_host(self):
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or any(c in hosts[0] for c in "/\\@?# \t\r\n"):
            raise APIError(403, "host", "Invalid Host")
        try:
            parsed = urlsplit("http://" + hosts[0])
            port = parsed.port
            hostname = parsed.hostname
        except ValueError:
            raise APIError(403, "host", "Invalid Host") from None
        allowed = {h.strip().lower() for h in self.server.bridge.settings["trusted_hosts"].split(",")}
        if hostname not in allowed or not hostname or port == 0:
            raise APIError(403, "host", "Untrusted Host")
        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1:
            raise APIError(403, "origin", "Invalid Origin")
        origin = origins[0] if origins else None
        allowed_origins = {value.strip() for value in self.server.bridge.settings.get("allowed_origins", "").split(",") if value.strip()}
        if origin is not None and origin != "http://" + hosts[0] and origin not in allowed_origins:
            raise APIError(403, "origin", "Web GUI origin is not allowed by this plugin")
        if self.command not in {"GET", "HEAD"} and origin is None:
            raise APIError(403, "origin", "Origin is required")
        self.cors_origin = origin

    def preflight(self):
        if not urlsplit(self.path).path.startswith("/api/v1/"):
            raise APIError(404, "not_found", "Unknown API route")
        method = self.headers.get("Access-Control-Request-Method", "")
        requested = {value.strip().lower() for value in self.headers.get("Access-Control-Request-Headers", "").split(",") if value.strip()}
        if method not in {"GET", "POST", "PATCH", "DELETE"} or requested - {"authorization", "content-type", "x-csrf-token", "last-event-id"}:
            raise APIError(403, "cors", "Unsupported cross-origin request")
        self.send_response(204)
        self.headers_common("application/json")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-CSRF-Token, Last-Event-ID")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def authenticate(self):
        if len(self.headers.get_all("Authorization", [])) > 1:
            raise APIError(401, "unauthenticated", "Ambiguous authorization")
        return self.server.bridge.auth.session(self.headers.get("Cookie"), self.headers.get("Authorization"), self.headers.get("Origin"))

    def body(self):
        if self.headers.get("Transfer-Encoding"):
            raise APIError(400, "validation", "Chunked request bodies are unsupported")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) > 1:
            raise APIError(400, "validation", "Ambiguous body length")
        try:
            length = int(lengths[0]) if lengths else 0
        except ValueError:
            raise APIError(400, "validation", "Invalid body length") from None
        if not 0 <= length <= 262144:
            raise APIError(413, "too_large", "Request exceeds 256 KiB")
        if length and self.headers.get_content_type() != "application/json":
            raise APIError(415, "content_type", "Expected application/json")
        try:
            raw = self.rfile.read(length)
            def reject_constant(value):
                raise ValueError("Non-finite JSON number")
            result = json.loads(raw, parse_constant=reject_constant) if raw else {}
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (ValueError, UnicodeError):
            raise APIError(400, "validation", "Expected a JSON object") from None

    def handle_api(self):
        streaming = False
        try:
            bridge = self.server.bridge
            self.validate_host()
            if self.command == "OPTIONS":
                return self.preflight()
            parsed = urlsplit(self.path)
            path = parsed.path
            query = parse_qs(parsed.query, max_num_fields=30)
            if path == "/api/v1/health" and self.command == "GET":
                return self.respond(200, bridge.health())
            if not path.startswith("/api/"):
                if self.command != "GET":
                    raise APIError(405, "method", "Method not allowed")
                return self.static(path)
            body = self.body() if self.command != "GET" else {}
            if path == "/api/v1/auth/login" and self.command == "POST":
                mode = body.get("mode", "cookie")
                sid, session = bridge.auth.login(body.get("token"), mode, self.headers.get("Origin"))
                if mode == "bearer":
                    return self.respond(200, bridge.envelope({**session, "session_token": sid}))
                return self.respond(200, bridge.envelope(session), f"npw_session={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age={bridge.auth.ttl}")
            sid, session = self.authenticate()
            if self.command != "GET":
                bridge.auth.check_csrf(session, self.headers.get("X-CSRF-Token"))
            if path == "/api/v1/auth/logout" and self.command == "POST":
                bridge.auth.logout(sid)
                return self.respond(200, bridge.envelope({}), "npw_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
            if path == "/api/v1/session" and self.command == "GET":
                return self.respond(200, bridge.envelope({**session, **bridge.meta()}))
            if path == "/api/v1/meta" and self.command == "GET":
                return self.respond(200, bridge.envelope(bridge.meta()))
            if path == "/api/v1/diagnostics" and self.command == "GET":
                with bridge.store.lock:
                    data = {"sse_clients": len(bridge.store.clients), "dropped_events": bridge.store.dropped,
                            "callback_errors": getattr(bridge.adapter, "callback_errors", 0),
                            "revision": bridge.store.revision, "http_thread_alive": bridge.server.thread.is_alive()}
                return self.respond(200, bridge.envelope(data))
            if path == "/api/v1/openapi.json" and self.command == "GET":
                from .schema import specification
                return self.respond(200, specification())
            if path == "/api/v1/events" and self.command == "GET":
                queue, replay = bridge.store.subscribe(self.headers.get("Last-Event-ID") or query.get("cursor", [None])[0])
                streaming = True
                return self.events(queue, replay, session)
            status, payload = dispatch(bridge, self.command, path.removeprefix("/api/v1"), body, query)
            self.respond(status, payload)
        except APIError as error:
            if not streaming:
                self.respond(error.status, {"ok": False, "error": {"code": error.code, "message": error.message}})
        except (BrokenPipeError, ConnectionError, TimeoutError, socket.timeout):
            pass
        except Exception:
            if not streaming:
                self.respond(500, {"ok": False, "error": {"code": "internal", "message": "Request failed"}})

    def events(self, queue, replay, session):
        bridge = self.server.bridge
        try:
            self.send_response(200)
            self.headers_common("text/event-stream")
            self.send_header("Connection", "close")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            for frame in replay:
                self.frame(frame)
            self.wfile.flush()
            while not bridge.store.closed and time.time() < session["expires"]:
                try:
                    frame = queue.get(timeout=20)
                except Empty:
                    frame = {"event": "heartbeat", "data": {}}
                # Logout invalidates existing streams as well as future requests.
                try:
                    self.authenticate()
                except APIError:
                    break
                if frame is None:
                    break
                if frame["event"] == "heartbeat":
                    self.wfile.write(b": heartbeat\n\n")
                else:
                    self.frame(frame)
                self.wfile.flush()
        finally:
            bridge.store.unsubscribe(queue)
            self.close_connection = True

    def frame(self, frame):
        self.wfile.write((f"id: {frame['id']}\nevent: {frame['event']}\ndata: " + json.dumps(frame["data"], ensure_ascii=True) + "\n\n").encode())

    def static(self, path):
        root = self.server.bridge.static
        target = (root / unquote(path).lstrip("/")).resolve()
        if not target.is_relative_to(root):
            raise APIError(403, "forbidden", "Invalid asset path")
        if not target.is_file():
            if "." in target.name:
                raise APIError(404, "not_found", "Asset not found")
            target = root / "index.html"
        if not target.is_file():
            raise APIError(503, "assets_missing", "Build the web application before installing the plugin")
        raw = target.read_bytes()
        self.send_response(200)
        self.headers_common(mimetypes.guess_type(str(target))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True
