from __future__ import annotations

import unittest
from pathlib import Path

from lablib.labs_comparison import (
    analyze_readme_os_documentation,
    build_lab_profile,
    describe_license_delivery,
    detect_license_mode_from_text,
    extract_license_source_from_text,
    extract_fenced_code_blocks,
    extract_headings,
)


ROOT = Path(__file__).resolve().parents[1]


class LabsComparisonV2Tests(unittest.TestCase):
    def test_quick_start_api_testing_surfaces_shell_and_output_validation_fields(self) -> None:
        profile = build_lab_profile(ROOT / "quick-start-api-testing")
        self.assertTrue(profile["readme"]["allCommandBlocksUseExecutableSyntax"])
        self.assertTrue(profile["readme"]["everyCommandHasOutputSnippet"])
        self.assertTrue(profile["readme"]["allOutputBlocksUseTerminalOutput"])
        self.assertFalse(profile["readme"]["osDocumentation"]["outputLanguageIssues"])

    def test_external_examples_video_links_are_detected(self) -> None:
        profile = build_lab_profile(ROOT / "external-examples")
        self.assertEqual(len(profile["readme"]["videoLinks"]), 1)
        self.assertIn("youtube.com", profile["readme"]["videoLinks"][0]["target"])
        self.assertIsInstance(profile["testCountConsistency"]["phases"], list)

    def test_external_examples_surfaces_skipped_command_output_rows(self) -> None:
        profile = build_lab_profile(ROOT / "external-examples")
        checks = profile["readme"]["osDocumentation"]["commandOutputChecks"]
        self.assertTrue(any(item["status"] == "skipped" for item in checks))
        self.assertTrue(
            any(
                item["status"] == "skipped"
                and "terminaloutput is not required" in item["notes"].lower()
                for item in checks
            )
        )

    def test_skipped_teardown_command_still_requires_shell_fence(self) -> None:
        readme_text = """# Sample

## Step

```powershell
docker compose down -v
```
"""
        os_doc = analyze_readme_os_documentation(
            readme_text,
            extract_headings(readme_text),
            extract_fenced_code_blocks(readme_text),
        )
        self.assertEqual(len(os_doc["commandOutputChecks"]), 1)
        check = os_doc["commandOutputChecks"][0]
        self.assertEqual(check["status"], "fail")
        self.assertEqual(check["commandFence"], "powershell")
        self.assertIn("Command fence must be ```shell```.", check["notes"])
        self.assertIn("terminaloutput is not required", check["notes"])

    def test_yaml_file_display_block_is_skipped_in_fencing_validation(self) -> None:
        readme_text = """# Sample

## Step

```yaml
path: ./specs/service.yaml
```
"""
        os_doc = analyze_readme_os_documentation(
            readme_text,
            extract_headings(readme_text),
            extract_fenced_code_blocks(readme_text),
        )
        self.assertEqual(len(os_doc["commandOutputChecks"]), 1)
        check = os_doc["commandOutputChecks"][0]
        self.assertEqual(check["status"], "skipped")
        self.assertEqual(check["outputFence"], "yaml")
        self.assertEqual(check["output"], "(not shown)")

    def test_detect_license_mode_from_text(self) -> None:
        self.assertEqual(
            detect_license_mode_from_text("Using Specmatic Enterprise license initialized from /specmatic/specmatic-license.txt"),
            "enterprise",
        )
        self.assertEqual(
            detect_license_mode_from_text("Using Specmatic Trial license initialized from jar:file:/usr/local/share/enterprise/enterprise.jar!/specmatic-default-trial-license.txt"),
            "trial",
        )
        self.assertEqual(
            detect_license_mode_from_text("docker.io/specmatic/specmatic:latest\nSpecmatic Core v2.44.2"),
            "oss",
        )

    def test_extract_license_source_and_delivery_details(self) -> None:
        enterprise_text = "Using Specmatic Enterprise license initialized from /specmatic/specmatic-license.txt"
        trial_text = "Using Specmatic Trial license initialized from jar:file:/usr/local/share/enterprise/enterprise.jar!/specmatic-default-trial-license.txt"
        self.assertEqual(extract_license_source_from_text(enterprise_text), "/specmatic/specmatic-license.txt")
        self.assertEqual(
            extract_license_source_from_text(trial_text),
            "jar:file:/usr/local/share/enterprise/enterprise.jar!/specmatic-default-trial-license.txt",
        )
        self.assertIn(
            "Docker-mounted enterprise license file",
            describe_license_delivery("enterprise", "/specmatic/specmatic-license.txt", "docker compose up test"),
        )
        self.assertIn(
            "Bundled trial license",
            describe_license_delivery("trial", "jar:file:/usr/local/share/enterprise/enterprise.jar!/specmatic-default-trial-license.txt", "docker compose up"),
        )
        self.assertIn(
            "OSS Docker image",
            describe_license_delivery("oss", "", "docker run specmatic/specmatic:latest validate"),
        )


if __name__ == "__main__":
    unittest.main()
