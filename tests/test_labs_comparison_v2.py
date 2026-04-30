from __future__ import annotations

import unittest
from pathlib import Path

from lablib.labs_comparison import build_lab_profile


ROOT = Path(__file__).resolve().parents[1]


class LabsComparisonV2Tests(unittest.TestCase):
    def test_quick_start_api_testing_surfaces_shell_and_output_validation_fields(self) -> None:
        profile = build_lab_profile(ROOT / "quick-start-api-testing")
        self.assertTrue(profile["readme"]["allCommandBlocksUseExecutableSyntax"])
        self.assertTrue(profile["readme"]["everyCommandHasOutputSnippet"])
        self.assertFalse(profile["readme"]["allOutputBlocksUseTerminalOutput"])
        self.assertTrue(
            any("```terminalOutput```" in issue for issue in profile["readme"]["osDocumentation"]["outputLanguageIssues"])
        )

    def test_external_examples_video_links_are_detected(self) -> None:
        profile = build_lab_profile(ROOT / "external-examples")
        self.assertEqual(len(profile["readme"]["videoLinks"]), 1)
        self.assertIn("youtube.com", profile["readme"]["videoLinks"][0]["target"])
        phases = profile["testCountConsistency"]["phases"]
        self.assertIn("Baseline Phase", [item["phase"] for item in phases])
        self.assertIn("Final Phase", [item["phase"] for item in phases])


if __name__ == "__main__":
    unittest.main()
