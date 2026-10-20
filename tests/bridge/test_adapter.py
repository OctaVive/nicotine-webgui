from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugin"))
from webgui.adapter import Adapter
from webgui.errors import APIError


class AdapterBoundaryTests(unittest.TestCase):
    def adapter(self, plugin):
        adapter = Adapter.__new__(Adapter)
        adapter.core = SimpleNamespace(pluginhandler=SimpleNamespace(enabled_plugins={"example": plugin}))
        adapter.callback_errors = 0
        return adapter

    def test_plugin_settings_do_not_expose_free_form_secrets(self):
        plugin = SimpleNamespace(settings={"secret": "token", "innocent_name": "hidden credentials", "enabled": True,
                                           "count": 10, "mode": "calm", "api_key_count": 123},
                                 metasettings={"secret": {"type": "str"}, "innocent_name": {"type": "str"},
                                               "enabled": {"type": "bool"}, "count": {"type": "int"},
                                               "mode": {"type": "dropdown", "options": ["calm", "fast"]},
                                               "api_key_count": {"type": "int"}})
        adapter = self.adapter(plugin)
        result = adapter.plugin_settings("example")
        self.assertEqual(set(result), {"enabled", "count", "mode"})
        self.assertEqual(result["mode"]["choices"], ["calm", "fast"])
        with self.assertRaises(APIError):
            adapter.plugin_settings("nicotine_webui")

    def test_event_subscriber_failure_is_contained(self):
        adapter = self.adapter(None)
        def broken():
            raise RuntimeError("should not escape into the Nicotine+ event loop")
        adapter.guarded(broken)()
        self.assertEqual(adapter.callback_errors, 1)
