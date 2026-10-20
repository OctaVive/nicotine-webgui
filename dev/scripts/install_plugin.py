#!/usr/bin/env python3
"""Install the bridge on the existing Nicotine+ host while it is stopped."""
import argparse
import ast
import configparser
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--with-ui", action="store_true", help="Also install a built SPA for native same-origin hosting")
    args = parser.parse_args()
    if sys.platform == "win32":
        default_data = Path(os.environ["APPDATA"]) / "nicotine"
        default_config = default_data / "config"
        if not default_config.is_file():
            default_config = default_config / "config"
        processes = subprocess.check_output(["tasklist", "/FO", "CSV"], text=True).lower()
        running = "nicotine.exe" in processes
    else:
        default_data = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "nicotine"
        default_config = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "nicotine/config"
        processes = subprocess.check_output(["ps", "-A", "-o", "args="], text=True).splitlines()
        running = False
        for process in processes:
            try:
                arguments = shlex.split(process)
            except ValueError:
                continue
            if any(Path(argument).name.lower() in {"nicotine", "nicotine+", "nicotine.py"} for argument in arguments):
                running = True
            if any(arguments[i:i + 2] == ["-m", "pynicotine"] for i in range(len(arguments) - 1)):
                running = True
    if running:
        raise SystemExit("Close Nicotine+ before installing; its configuration must not be edited while running.")
    if args.with_ui and not (ROOT / "web/dist/index.html").exists():
        raise SystemExit("Build assets first: cd web && npm ci && npm run build")
    data = args.data_dir or default_data
    config = args.config or default_config
    if config.is_dir():
        raise SystemExit(f"Configuration path is a directory: {config}. Use --config with the configuration file, not its folder.")
    cfg = configparser.ConfigParser(interpolation=None)
    if config.exists():
        with config.open(encoding="utf-8") as handle:
            cfg.read_file(handle)
    if not cfg.has_section("plugins"):
        cfg.add_section("plugins")
    enabled = ast.literal_eval(cfg.get("plugins", "enabled", fallback="[]"))
    if not isinstance(enabled, list):
        raise SystemExit("Invalid enabled plugin list")
    if "nicotine_webui" not in enabled:
        enabled.append("nicotine_webui")
    cfg.set("plugins", "enable", "True")
    cfg.set("plugins", "enabled", repr(enabled))
    destination = data / "plugins/nicotine_webui"
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "plugin", destination, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if args.with_ui:
        shutil.copytree(ROOT / "web/dist", destination / "webgui/static", dirs_exist_ok=True)
    config.parent.mkdir(parents=True, exist_ok=True)
    if config.exists():
        shutil.copy2(config, config.with_suffix(".pre-webgui"))
    descriptor, temporary = tempfile.mkstemp(prefix="config-webgui-", dir=config.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            cfg.write(handle)
        os.replace(temporary, config)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f"Installed {destination}. Start Nicotine+ and get the login token from plugin preferences.")


if __name__ == "__main__":
    main()
