from __future__ import annotations

import unittest
from pathlib import Path

from lablib.labs_comparison import build_lab_profile


ROOT = Path(__file__).resolve().parents[1]


class LabsComparisonV2Tests(unittest.TestCase):
    def test_quick_start_api_testing_uses_common_os_command_flow(self) -> None:
        profile = build_lab_profile(ROOT / "quick-start-api-testing")
        os_doc = profile["readme"]["osDocumentation"]
        self.assertTrue(os_doc["commonCommandForAllOs"])
        self.assertEqual(
            os_doc["commonCommandPhaseTitles"],
            ["Baseline Phase", "Intermediate Phase: Task A", "Final Phase"],
        )
        self.assertEqual(profile["testCountConsistency"]["phases"][0]["phase"], "Baseline Phase")
        self.assertEqual(profile["testCountConsistency"]["phases"][1]["phase"], "Intermediate Phase: Task A")
        self.assertEqual(profile["testCountConsistency"]["phases"][2]["phase"], "Final Phase")

    def test_external_examples_video_and_phase_counts_follow_v2_metadata(self) -> None:
        profile = build_lab_profile(ROOT / "external-examples")
        self.assertEqual(len(profile["readme"]["videoLinks"]), 1)
        self.assertIn("youtube.com", profile["readme"]["videoLinks"][0]["target"])
        phases = profile["testCountConsistency"]["phases"]
        self.assertEqual([item["phase"] for item in phases], ["Baseline Phase", "Studio Phase", "Final Phase"])
        self.assertEqual(phases[0]["status"], "match")
        self.assertEqual(phases[1]["status"], "expected-not-available")
        self.assertEqual(phases[2]["status"], "match")
        self.assertIsNone(phases[1]["readmeCounts"])
        self.assertIsNone(phases[1]["consoleCounts"])


if __name__ == "__main__":
    unittest.main()
