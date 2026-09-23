import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class ManifestTests(unittest.TestCase):
    def test_plugin_and_marketplace_names_match(self):
        plugin = json.loads((ROOT / "plugins/arcgis-pro-guardian/.codex-plugin/plugin.json").read_text(encoding="utf-8"))
        marketplace = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["name"], "arcgis-pro-guardian")
        self.assertEqual(marketplace["plugins"][0]["name"], plugin["name"])
        self.assertEqual(marketplace["plugins"][0]["source"]["path"], "./plugins/arcgis-pro-guardian")
        self.assertTrue(plugin["version"].startswith("0.3.0"))


if __name__ == "__main__":
    unittest.main()
