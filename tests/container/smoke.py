#!/usr/bin/env python3
"""Test a UI-only image without credentials, engine directories, or volumes."""
import json
import subprocess
import sys
import time
from uuid import uuid4


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def main():
    image = sys.argv[1] if len(sys.argv) > 1 else "nicotine-webgui:local"
    name = "nicotine-webgui-test-" + uuid4().hex[:10]
    try:
        docker("run", "-d", "--name", name, "--read-only", "--tmpfs", "/tmp", "--network", "none",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", image)
        for _ in range(30):
            result = subprocess.run(["docker", "exec", name, "python", "-c",
                                     "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/health').read().decode())"], capture_output=True, text=True)
            if result.returncode == 0:
                assert json.loads(result.stdout)["service"] == "web-ui"
                break
            time.sleep(1)
        else:
            raise AssertionError(docker("logs", name))
        assert docker("exec", name, "id", "-u") != "0"
        mounts = json.loads(docker("inspect", "--format", "{{json .Mounts}}", name))
        assert all(mount["Type"] == "tmpfs" and mount["Destination"] == "/tmp" for mount in mounts), mounts
        docker("exec", name, "python", "-c", "import importlib.util; from pathlib import Path; assert importlib.util.find_spec('pynicotine') is None; assert not Path('/data').exists(); assert not Path('/config').exists(); import urllib.request; assert b'<html' in urllib.request.urlopen('http://127.0.0.1:8080/search/123').read()")
        docker("stop", "--time", "10", name)
        assert docker("inspect", "--format", "{{.State.ExitCode}}", name) == "0"
        print("PASS: UI-only image, no engine/volumes/credentials, non-root, read-only root, SPA fallback, graceful shutdown")
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


if __name__ == "__main__":
    main()
