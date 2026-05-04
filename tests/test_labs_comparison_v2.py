from __future__ import annotations

import unittest
import importlib.util
from pathlib import Path

from lablib.labs_comparison import (
    analyze_readme_os_documentation,
    build_lab_profile,
    describe_license_delivery,
    detect_license_mode_from_text,
    extract_license_source_from_text,
    extract_fenced_code_blocks,
    extract_headings,
    extract_tests_run_summaries,
    select_readme_summary_for_v2_phase,
    select_readme_summary_for_phase,
)
from lablib.readme_schema import parse_readme_document


ROOT = Path(__file__).resolve().parents[1]
LABS_ROOT = ROOT.parent / "labs"


def load_run_module(lab_name: str):
    module_path = ROOT / lab_name / "run.py"
    spec = importlib.util.spec_from_file_location(f"{lab_name.replace('-', '_')}_run", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


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

    def test_external_examples_maps_count_rows_to_the_expected_readme_summaries(self) -> None:
        module = load_run_module("external-examples")
        spec = module.build_lab_spec()
        readme_text = (LABS_ROOT / "external-examples" / "README.md").read_text(encoding="utf-8")
        readme_doc = parse_readme_document(readme_text)
        summaries = extract_tests_run_summaries(readme_text)
        readme_phases = {phase.id: phase for phase in readme_doc.phases}

        selected = []
        for index, phase in enumerate(spec.phases):
            readme_phase = readme_phases.get(phase.readme_phase_id) if phase.readme_phase_id else None
            selected.append(
                select_readme_summary_for_v2_phase(readme_phase)
                if readme_phase is not None
                else select_readme_summary_for_phase(summaries, phase, index)
            )
        summary_values = [item["summary"] if item else None for item in selected]

        self.assertEqual(
            [phase.readme_phase_id for phase in spec.phases if phase.readme_phase_id],
            ["baseline", "baseline", "studio", "final"],
        )
        self.assertEqual(
            summary_values,
            [
                "Examples: 1 passed and 3 failed out of 4 total",
                "Examples: 1 passed and 3 failed out of 4 total",
                "Examples: 6 passed and 0 failed out of 6 total",
                "Examples: 6 passed and 0 failed out of 6 total",
            ],
        )

    def test_partial_examples_maps_count_rows_to_the_expected_readme_summaries(self) -> None:
        module = load_run_module("partial-examples")
        spec = module.build_lab_spec()
        readme_text = (LABS_ROOT / "partial-examples" / "README.md").read_text(encoding="utf-8")
        readme_doc = parse_readme_document(readme_text)
        summaries = extract_tests_run_summaries(readme_text)
        readme_phases = {phase.id: phase for phase in readme_doc.phases}

        selected = []
        for index, phase in enumerate(spec.phases):
            readme_phase = readme_phases.get(phase.readme_phase_id) if phase.readme_phase_id else None
            selected.append(
                select_readme_summary_for_v2_phase(readme_phase, phase)
                if readme_phase is not None
                else select_readme_summary_for_phase(summaries, phase, index)
            )
        summary_values = [item["summary"] if item else None for item in selected]

        self.assertEqual(
            [phase.readme_phase_id for phase in spec.phases if phase.readme_phase_id],
            ["baseline", "baseline", "studio", "final"],
        )
        self.assertEqual(
            summary_values,
            [
                "Examples: 0 passed and 3 failed out of 3 total",
                "Examples: 0 passed and 3 failed out of 3 total",
                "Examples: 3 passed and 0 failed out of 3 total",
                "Examples: 3 passed and 0 failed out of 3 total",
            ],
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
