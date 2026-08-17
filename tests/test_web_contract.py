import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WebContractTests(unittest.TestCase):
    def test_javascript_element_ids_exist_in_page(self):
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        page = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        required = set(re.findall(r'\$\("([^"]+)"\)', script))
        available = set(re.findall(r'id="([^"]+)"', page))
        self.assertEqual(required - available, set())

    def test_result_workspace_has_four_progressive_views(self):
        page = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        tabs = re.findall(r'data-result-tab="([^"]+)"', page)
        panels = re.findall(r'data-tab-panel="([^"]+)"', page)
        self.assertEqual(tabs, ["overview", "schedule", "mechanics", "simulation"])
        self.assertEqual(panels, tabs)


if __name__ == "__main__":
    unittest.main()
