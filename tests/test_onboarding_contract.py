"""Offline checks for optional native WOL onboarding metadata."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
ASSISTANT_URL = (
    "https://my.home-assistant.io/redirect/config_flow_start/?domain=wake_on_lan"
)


class OnboardingContractTests(unittest.TestCase):
    """Validate metadata without loading HA or sending a packet."""

    def test_wol_help_is_optional_in_both_existing_forms(self):
        for relative in (
            "custom_components/qnap/strings.json",
            "custom_components/qnap/translations/en.json",
        ):
            data = json.loads((ROOT / relative).read_text("utf-8"))
            for step in ("user", "reconfigure"):
                with self.subTest(file=relative, step=step):
                    description = data["config"]["step"][step]["description"]
                    self.assertIn("({wake_on_lan_url})", description)
                    self.assertIn("optional", description)

        constants = (ROOT / "custom_components/qnap/const.py").read_text("utf-8")
        self.assertIn(ASSISTANT_URL, constants)

    def test_wol_has_no_package_or_integration_dependency(self):
        manifest = json.loads(
            (ROOT / "custom_components/qnap/manifest.json").read_text("utf-8")
        )
        for field in ("dependencies", "after_dependencies"):
            self.assertNotIn("wake_on_lan", manifest.get(field, []))
        self.assertEqual(manifest["requirements"], ["qnap-client==1.1.0"])

    def test_declared_minimum_matches_existing_api_requirement(self):
        metadata = json.loads((ROOT / "hacs.json").read_text("utf-8"))
        self.assertEqual(metadata["homeassistant"], "2025.3.0")

    def test_native_assistant_is_documented(self):
        guide = (ROOT / "docs/getting-started.md").read_text("utf-8")
        self.assertIn(ASSISTANT_URL, guide)


if __name__ == "__main__":
    unittest.main()
