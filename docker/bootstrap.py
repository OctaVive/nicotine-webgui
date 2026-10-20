#!/usr/bin/env python3
"""Offline, idempotent bootstrap. Only run before Nicotine+ starts."""
import ast
import configparser
import os
from pathlib import Path
import shutil
import tempfile


def bootstrap(config_root, data_root, plugin_source, environ):
    data = Path(data_root) / "nicotine"
    config_folder = Path(config_root) / "nicotine"
    for folder in (data / "plugins", data / "downloads", data / "incomplete", data / "logs", config_folder):
        folder.mkdir(parents=True, exist_ok=True)
        if not os.access(folder, os.W_OK):
            raise PermissionError(f"Directory is not writable: {folder}; match PUID/PGID to volume ownership")
    destination = data / "plugins/nicotine_webui"
    # Replace the dedicated plugin directory so upgrades cannot retain stale modules.
    stage = Path(tempfile.mkdtemp(prefix=".nicotine-webui-", dir=data / "plugins"))
    try:
        shutil.copytree(plugin_source, stage, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if destination.exists():
            shutil.rmtree(destination)
        stage.rename(destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    path = config_folder / "config"
    first_run = not path.exists()
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.read(path, encoding="utf-8")
    for section in ("plugins", "server", "transfers"):
        if not parser.has_section(section):
            parser.add_section(section)
    enabled = ast.literal_eval(parser.get("plugins", "enabled", fallback="[]"))
    if not isinstance(enabled, list) or not all(isinstance(x, str) for x in enabled):
        raise ValueError("Existing enabled plugin list is invalid")
    if "nicotine_webui" not in enabled:
        enabled.append("nicotine_webui")
    parser.set("plugins", "enable", "True")
    parser.set("plugins", "enabled", repr(enabled))
    if first_run:
        username, password = environ.get("NICOTINE_USERNAME"), environ.get("NICOTINE_PASSWORD")
        if bool(username) != bool(password):
            raise ValueError("Set both NICOTINE_USERNAME and NICOTINE_PASSWORD, or neither")
        if username and password:
            if any(c in username + password for c in "\r\n\x00"):
                raise ValueError("Credentials cannot contain control characters")
            parser.set("server", "login", username)
            parser.set("server", "passw", password)
        parser.set("server", "upnp", "False")
        parser.set("server", "portrange", "(2234, 2234)")
        parser.set("transfers", "downloaddir", str(data / "downloads"))
        parser.set("transfers", "incompletedir", str(data / "incomplete"))
        share = environ.get("NICOTINE_SHARES")
        if share:
            folder = Path(share)
            if folder.is_dir() and next(folder.iterdir(), None) is not None:
                parser.set("transfers", "shared", repr([(folder.name, str(folder))]))
    fd, temporary = tempfile.mkstemp(prefix="config-", dir=config_folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            parser.write(handle)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":
    try:
        bootstrap(os.environ.get("XDG_CONFIG_HOME", "/config"), os.environ.get("XDG_DATA_HOME", "/data"),
                  os.environ.get("NICOTINE_WEBUI_PLUGIN_SOURCE", "/opt/nicotine-webgui/plugin"), os.environ)
    except (OSError, ValueError, SyntaxError, configparser.Error) as error:
        raise SystemExit(f"Bootstrap failed: {error}") from None
