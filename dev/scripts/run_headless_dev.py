#!/usr/bin/env python3
"""Launch Nicotine+ in a disposable profile; never touch the user's installation."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from docker.bootstrap import bootstrap


def main():
    with tempfile.TemporaryDirectory(prefix="nicotine-webgui-dev-") as directory:
        root = Path(directory)
        source = root / "plugin"
        shutil.copytree(ROOT / "plugin", source)
        if not (ROOT / "web/dist/index.html").exists():
            raise SystemExit("Build the SPA first: cd web && npm ci && npm run build")
        shutil.copytree(ROOT / "web/dist", source / "webgui/static", dirs_exist_ok=True)
        env = {**os.environ, "XDG_DATA_HOME": str(root / "data"), "XDG_CONFIG_HOME": str(root / "config"),
               "NICOTINE_WEBUI_HOST": "127.0.0.1", "NICOTINE_WEBUI_TOKEN": os.environ.get("NICOTINE_WEBUI_TOKEN", "development-only")}
        bootstrap(env["XDG_CONFIG_HOME"], env["XDG_DATA_HOME"], source, env)
        print("Disposable profile:", root, "— development token supplied through NICOTINE_WEBUI_TOKEN", flush=True)
        try:
            subprocess.run([sys.executable, "-m", "pynicotine", "--headless", "--user-data", str(root / "data/nicotine"),
                            "--config", str(root / "config/nicotine/config")], env=env, check=True)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
