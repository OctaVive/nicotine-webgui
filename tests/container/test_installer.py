import configparser
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dev.scripts import install_plugin


class InstallerTests(unittest.TestCase):
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
            with patch.object(install_plugin, "ROOT", root), patch.object(sys, "platform", "linux"), patch.object(sys, "argv", ["install", "--data-dir", str(root / "data"), "--config", str(config)]), patch.object(install_plugin.subprocess, "check_output", return_value="unrelated-process\n"):
                install_plugin.main()
            cfg = configparser.ConfigParser(interpolation=None)
            cfg.read(config)
            self.assertEqual(cfg["server"]["passw"], "unchanged")
            self.assertIn("other", cfg["plugins"]["enabled"])
            self.assertIn("nicotine_webui", cfg["plugins"]["enabled"])
            self.assertTrue(config.with_suffix(".pre-webgui").exists())
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            self.assertTrue((root / "data/plugins/nicotine_webui/webgui/static/index.html").exists())
