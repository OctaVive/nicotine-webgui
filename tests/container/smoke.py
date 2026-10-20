#!/usr/bin/env python3
"""Exercise a built image with disposable named volumes and no Soulseek login."""
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
    data, config = name + "-data", name + "-config"
    try:
        for volume in (data, config):
            docker("volume", "create", volume)
        fixture = "from pathlib import Path; p=Path('/config/nicotine'); p.mkdir(parents=True,exist_ok=True); (p/'config').write_text('[server]\\nauto_connect_startup = False\\n')"
        docker("run", "--rm", "-v", config + ":/config", "--entrypoint", "python", image, "-c", fixture)
        args = ["run", "-d", "--name", name, "--read-only", "--tmpfs", "/tmp", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                "-e", "NICOTINE_WEBUI_TOKEN=container-test-only", "-v", data + ":/data", "-v", config + ":/config", image]
        docker(*args)
        for _ in range(60):
            result = subprocess.run(["docker", "exec", name, "python", "-c", "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8181/api/v1/health').read().decode())"], capture_output=True, text=True)
            if result.returncode == 0:
                assert json.loads(result.stdout)["status"] == "ok"
                break
            time.sleep(1)
        else:
            raise AssertionError(docker("logs", name))
        uid = docker("exec", name, "id", "-u")
        assert uid != "0", uid
        docker("exec", name, "python", "-c", "from pathlib import Path; Path('/data/restart-marker').write_text('persisted')")
        docker("stop", "--time", "30", name)
        assert docker("inspect", "--format", "{{.State.ExitCode}}", name) == "0"
        docker("start", name)
        assert docker("exec", name, "cat", "/data/restart-marker") == "persisted"
        print("PASS: image health, non-root UID, read-only root, graceful stop, and persistent volumes")
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        for volume in (data, config):
            subprocess.run(["docker", "volume", "rm", volume], capture_output=True)


if __name__ == "__main__":
    main()
