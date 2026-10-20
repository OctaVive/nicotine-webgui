#!/usr/bin/env python3
"""Serve the standalone Web GUI; no Nicotine+ process or API proxy is needed."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
import signal
from threading import Thread
from urllib.parse import unquote, urlsplit


class UIHandler(SimpleHTTPRequestHandler):
    def send_head(self):
        path = unquote(urlsplit(self.path).path)
        if path == "/health":
            body = b'{"service":"web-ui"}\n'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return BytesIO(body)

        root = Path(self.directory).resolve()
        target = (root / path.lstrip("/")).resolve()
        if not target.is_relative_to(root):
            self.send_error(403)
            return None
        if not target.is_file():
            # Client-side routes use index.html, but missing assets must be 404s.
            if path.startswith("/assets/") or Path(path).suffix:
                self.send_error(404)
                return None
            self.path = "/index.html"
        return super().send_head()

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()


def main():
    server = ThreadingHTTPServer(("0.0.0.0", 8080), partial(UIHandler, directory="/opt/webui"))

    def stop(signum, frame):
        # shutdown() must run outside the serve_forever thread.
        Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
