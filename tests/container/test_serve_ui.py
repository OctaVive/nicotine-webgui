from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from docker.serve_ui import UIHandler


class UIServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        (root / "index.html").write_text("<html>Web GUI</html>")
        (root / "assets").mkdir()
        (root / "assets/app.js").write_text("console.log('ui')")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(UIHandler, directory=str(root)))
        self.thread = Thread(target=self.server.serve_forever)
        self.thread.start()
        self.url = "http://127.0.0.1:%s" % self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.directory.cleanup()

    def test_health(self):
        with urlopen(self.url + "/health") as response:
            self.assertEqual(json.load(response), {"service": "web-ui"})

    def test_spa_routes_and_head(self):
        for path in ("/", "/search/123?query=test"):
            with urlopen(self.url + path) as response:
                self.assertIn(b"<html>", response.read())
        with urlopen(Request(self.url + "/search/123", method="HEAD")) as response:
            self.assertEqual(response.read(), b"")
            self.assertGreater(int(response.headers["Content-Length"]), 0)

    def test_static_assets_and_missing_files(self):
        with urlopen(self.url + "/assets/app.js") as response:
            self.assertIn(b"console.log", response.read())
        for path in ("/assets/missing.js", "/missing.ico"):
            with self.assertRaises(HTTPError) as error:
                urlopen(self.url + path)
            self.assertEqual(error.exception.code, 404)
            error.exception.close()

    def test_rejects_traversal(self):
        with self.assertRaises(HTTPError) as error:
            urlopen(self.url + "/%2e%2e/secret")
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
