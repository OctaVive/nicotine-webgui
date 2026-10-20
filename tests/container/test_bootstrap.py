import configparser
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from docker.bootstrap import bootstrap


class BootstrapTests(unittest.TestCase):
    def test_idempotent_upgrade_preserves_credentials_and_refreshes_plugin(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / "source"
            source.mkdir()
            (source / "__init__.py").write_text("v1")
            args = (root / "config", root / "data", source)
            bootstrap(*args, {"NICOTINE_USERNAME": "original", "NICOTINE_PASSWORD": "a%secret"})
            destination = root / "data/nicotine/plugins/nicotine_webui"
            (destination / "obsolete.py").write_text("old")
            (source / "__init__.py").write_text("v2")
            bootstrap(*args, {"NICOTINE_USERNAME": "replacement", "NICOTINE_PASSWORD": "different"})
            cfg = configparser.ConfigParser(interpolation=None)
            path = root / "config/nicotine/config"
            cfg.read(path)
            self.assertEqual(cfg["server"]["login"], "original")
            self.assertEqual(cfg["server"]["passw"], "a%secret")
            self.assertEqual(cfg["plugins"]["enabled"].count("nicotine_webui"), 1)
            self.assertFalse((destination / "obsolete.py").exists())
            self.assertEqual((destination / "__init__.py").read_text(), "v2")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_missing_credentials_still_enable_bridge(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / "source"
            source.mkdir()
            bootstrap(root / "config", root / "data", source, {})
            cfg = configparser.ConfigParser(interpolation=None)
            cfg.read(root / "config/nicotine/config")
            self.assertTrue(cfg.getboolean("plugins", "enable"))
            self.assertFalse(cfg.getboolean("server", "upnp"))
            self.assertNotIn("login", cfg["server"])


if __name__ == "__main__":
    unittest.main()
