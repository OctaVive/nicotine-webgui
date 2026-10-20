#!/usr/bin/env python3
"""Run the frozen macOS app headlessly with a disposable profile."""
import configparser
import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from docker.bootstrap import bootstrap


def main():
    executable = sys.argv[1] if len(sys.argv) > 1 else "/Applications/Nicotine+.app/Contents/MacOS/Nicotine+"
    with tempfile.TemporaryDirectory(prefix="nicotine-webgui-frozen-") as temporary:
        root = Path(temporary)
        source = root / "plugin"
        shutil.copytree(ROOT / "plugin", source)
        shutil.copytree(ROOT / "web/dist", source / "webgui/static", dirs_exist_ok=True)
        bootstrap(root / "config", root / "data", source, {})
        path = root / "config/nicotine/config"
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(path)
        parser.set("server", "auto_connect_startup", "False")
        with path.open("w") as handle:
            parser.write(handle)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {**os.environ, "XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data"),
               "NICOTINE_WEBUI_PORT": str(port), "NICOTINE_WEBUI_HOST": "127.0.0.1", "NICOTINE_WEBUI_TOKEN": "frozen-test-only"}
        with (root / "output.log").open("w+") as output:
            process = subprocess.Popen([executable, "--headless", "--config", str(path), "--user-data", str(root / "data/nicotine")],
                                       env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT)
            try:
                for _ in range(100):
                    try:
                        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                        connection.request("GET", "/api/v1/health")
                        response = connection.getresponse()
                        value = json.loads(response.read())
                        connection.close()
                        if response.status == 200:
                            assert value["connected"] is False
                            print("PASS: frozen macOS runtime imports bridge dependencies and serves HTTP offline")
                            duration = float(sys.argv[2]) if len(sys.argv) > 2 else 0
                            if duration:
                                login = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                                login.request("POST", "/api/v1/auth/login", json.dumps({"token": "frozen-test-only"}),
                                              {"Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json"})
                                auth = login.getresponse()
                                assert auth.status == 200
                                cookie = auth.getheader("Set-Cookie").split(";")[0]
                                cursor = json.loads(auth.read())["cursor"]
                                login.close()
                                stream = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
                                stream.request("GET", "/api/v1/events?cursor=" + cursor, headers={"Cookie": cookie})
                                events = stream.getresponse()
                                assert events.status == 200
                                started, heartbeats = time.monotonic(), 0
                                while time.monotonic() - started < duration:
                                    line = events.readline()
                                    assert line, "SSE disconnected during soak"
                                    if line.startswith(b": heartbeat"):
                                        heartbeats += 1
                                        print(f"SSE alive: {time.monotonic() - started:.0f}s, {heartbeats} heartbeats", flush=True)
                                events.close()
                                stream.close()
                                print(f"PASS: frozen-runtime SSE stayed connected for {duration:.0f} seconds", flush=True)
                            return
                    except (OSError, ValueError):
                        pass
                    if process.poll() is not None:
                        break
                    time.sleep(.1)
                output.seek(0)
                raise AssertionError(output.read())
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                        raise AssertionError("Frozen Nicotine+ did not shut down within ten seconds")
                    assert process.returncode == 0, f"Unexpected shutdown status: {process.returncode}"


if __name__ == "__main__":
    main()
