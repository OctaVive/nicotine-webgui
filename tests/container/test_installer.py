import configparser
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dev.scripts import install_plugin


class InstallerTests(unittest.TestCase):
    def test_windows_detects_nested_config_and_preserves_account(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plugin").mkdir()
            (root / "plugin/__init__.py").write_text("# fixture")
            config = root / "nicotine/config/config"
            config.parent.mkdir(parents=True)
            original = "[server]\nlogin = existing\npassw = unchanged\n"
            config.write_text(original)
            with patch.object(install_plugin, "ROOT", root), patch.object(sys, "platform", "win32"), patch.dict(os.environ, {"APPDATA": str(root)}), patch.object(sys, "argv", ["install"]), patch.object(install_plugin.subprocess, "check_output", return_value=""):
                install_plugin.main()
            cfg = configparser.ConfigParser(interpolation=None)
            cfg.read(config)
            self.assertEqual(cfg["server"]["login"], "existing")
            self.assertEqual(cfg["server"]["passw"], "unchanged")
            self.assertIn("nicotine_webui", cfg["plugins"]["enabled"])
            self.assertEqual(config.with_suffix(".pre-webgui").read_text(), original)
            self.assertTrue((root / "nicotine/plugins/nicotine_webui/__init__.py").exists())

    def test_directory_config_is_rejected_before_installing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(sys, "platform", "win32"), patch.dict(os.environ, {"APPDATA": str(root)}), patch.object(sys, "argv", ["install", "--config", str(root), "--data-dir", str(root / "data")]), patch.object(install_plugin.subprocess, "check_output", return_value=""):
                with self.assertRaisesRegex(SystemExit, "path is a directory"):
                    install_plugin.main()
            self.assertFalse((root / "data").exists())

    def test_refuses_running_python_engine_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(sys, "platform", "linux"), patch.object(sys, "argv", ["install", "--data-dir", str(root / "data"), "--config", str(root / "config")]), patch.object(install_plugin.subprocess, "check_output", return_value="python3 -m pynicotine --headless\n"):
                with self.assertRaises(SystemExit):
                    install_plugin.main()
            self.assertEqual(list(root.iterdir()), [])

    def test_installs_assets_and_preserves_existing_account(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plugin").mkdir()
            (root / "plugin/__init__.py").write_text("# plugin")
            (root / "web/dist").mkdir(parents=True)
            (root / "web/dist/index.html").write_text("<title>test</title>")
            config = root / "profile/config"
            config.parent.mkdir()
            config.write_text("[server]\nlogin = existing\npassw = unchanged\n[plugins]\nenabled = ['other']\n")
            with patch.object(install_plugin, "ROOT", root), patch.object(sys, "platform", "linux"), patch.object(sys, "argv", ["install", "--with-ui", "--data-dir", str(root / "data"), "--config", str(config)]), patch.object(install_plugin.subprocess, "check_output", return_value="unrelated-process\n"):
                install_plugin.main()
            cfg = configparser.ConfigParser(interpolation=None)
            cfg.read(config)
            self.assertEqual(cfg["server"]["passw"], "unchanged")
            self.assertIn("other", cfg["plugins"]["enabled"])
            self.assertIn("nicotine_webui", cfg["plugins"]["enabled"])
            self.assertTrue(config.with_suffix(".pre-webgui").exists())
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            self.assertTrue((root / "data/plugins/nicotine_webui/webgui/static/index.html").exists())

    def test_bridge_only_install_requires_no_web_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plugin").mkdir()
            (root / "plugin/__init__.py").write_text("# fixture")
            with patch.object(install_plugin, "ROOT", root), patch.object(sys, "platform", "linux"), patch.object(sys, "argv", ["install", "--data-dir", str(root / "data"), "--config", str(root / "config")]), patch.object(install_plugin.subprocess, "check_output", return_value="unrelated-process\n"):
                install_plugin.main()
            self.assertTrue((root / "data/plugins/nicotine_webui/__init__.py").exists())
            self.assertFalse((root / "data/plugins/nicotine_webui/webgui/static/index.html").exists())
