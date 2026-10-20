from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin"))
from webgui.history import read_history


class HistoryTests(unittest.TestCase):
    def test_backfill_excludes_live_messages_and_unparseable_lines(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "chat.log"
            path.write_text("2020-01-01 12:00:00 [alice] old\n2020-01-01 12:01:00 [me] outgoing\n2030-01-01 12:00:00 [alice] live\ninvalid\n")
            rows = read_history(path, "%Y-%m-%d %H:%M:%S", 500, "me", datetime(2026, 1, 1).timestamp())
            self.assertEqual([r["message"] for r in rows], ["old", "outgoing"])
            self.assertTrue(rows[1]["outgoing"])

    def test_missing_log_is_empty(self):
        self.assertEqual(read_history("/nonexistent/chat.log", "%x %X", 10, None, 1), [])
