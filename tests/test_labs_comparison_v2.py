from __future__ import annotations

import unittest
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace

from lablib.labs_comparison import (
    analyze_readme_os_documentation,
    build_license_profile,
    build_lab_profile,
    build_count_cell,
    describe_license_delivery,
    detect_license_mode_from_text,
    extract_specmatic_compose_targets,
    extract_license_source_from_text,
    extract_fenced_code_blocks,
    extract_headings,
    extract_tests_run_summaries,
    select_readme_summary_for_v2_phase,
    select_readme_summary_for_phase,
    test_counts_for_phase,
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

    def test_windows_parity_phases_use_executable_linux_commands(self) -> None:
        for lab_name in ("external-examples", "partial-examples"):
            module = load_run_module(lab_name)
            spec = module.build_lab_spec()
            parity_phases = [phase for phase in spec.phases if "Windows command parity" in phase.name]
            self.assertTrue(parity_phases)
            for phase in parity_phases:
                self.assertNotIn("../license.txt:/specmatic/specmatic-license.txt:ro", phase.command)
                self.assertTrue(any("/specmatic/specmatic-license.txt:ro" in part for part in phase.command))

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

    def test_service_startup_command_without_output_is_skipped(self) -> None:
        readme_text = """# Sample

## Step

```shell
docker compose up consumer --build
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
        self.assertIn("service startup commands", check["notes"])

    def test_setup_commands_without_output_are_skipped(self) -> None:
        for command in (
            "chmod +x hooks/pre.sh hooks/post.sh",
            "git update-index --chmod=+x hooks/pre.sh hooks/post.sh",
            "docker compose stop mock",
        ):
            readme_text = f"""# Sample

## Step

```shell
{command}
```
"""
            os_doc = analyze_readme_os_documentation(
                readme_text,
                extract_headings(readme_text),
                extract_fenced_code_blocks(readme_text),
            )
            self.assertEqual(len(os_doc["commandOutputChecks"]), 1)
            self.assertEqual(os_doc["commandOutputChecks"][0]["status"], "skipped")

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

    def test_yaml_block_after_skipped_startup_command_is_not_treated_as_output(self) -> None:
        readme_text = """# Sample

## Step

```shell
docker compose --profile studio up
```

```yaml
tags:
  - WIP
```
"""
        os_doc = analyze_readme_os_documentation(
            readme_text,
            extract_headings(readme_text),
            extract_fenced_code_blocks(readme_text),
        )
        self.assertEqual(len(os_doc["commandOutputChecks"]), 2)
        self.assertEqual(os_doc["commandOutputChecks"][0]["status"], "skipped")
        self.assertEqual(os_doc["commandOutputChecks"][1]["status"], "skipped")

    def test_test_counts_flag_disables_count_validation(self) -> None:
        readme_doc = SimpleNamespace(metadata={"test_counts": False})
        self.assertFalse(test_counts_for_phase(readme_doc, None))
        cell = build_count_cell(
            None,
            {
                "testCountsEnabled": False,
                "expectedSources": {
                    "readme_summary": True,
                    "console_summary": True,
                    "ctrf": True,
                    "html": True,
                },
            },
            "readme_summary",
        )
        self.assertEqual(cell["text"], "Not Applicable")

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
        self.assertIn(
            "not applicable",
            describe_license_delivery("not-applicable", "", ""),
        )

    def test_extract_specmatic_compose_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            compose_file = Path(tmp) / "docker-compose.yaml"
            compose_file.write_text(
                """
services:
  consumer:
    image: python:3.14-alpine
  mock:
    container_name: quick-start-mock-server
    image: specmatic/enterprise:latest
  studio:
    image: specmatic/enterprise:latest
""".strip()
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                extract_specmatic_compose_targets(compose_file),
                {"mock", "studio", "quick-start-mock-server"},
            )

    def test_build_license_profile_falls_back_to_compose_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upstream_lab = root / "lab"
            upstream_lab.mkdir()
            (upstream_lab / "docker-compose.yaml").write_text(
                """
services:
  camelCaseService:
    container_name: camel-case-service
    image: specmatic/enterprise:latest
""".strip()
                + "\n",
                encoding="utf-8",
            )
            phase_dir = root / "baseline"
            phase_dir.mkdir(parents=True)
            (phase_dir / "build" / "data-adapters").mkdir(parents=True)
            (phase_dir / "command.log").write_text("python3 wrapper.py\n", encoding="utf-8")
            (phase_dir / "build" / "data-adapters" / "compose.log").write_text(
                "camel-case-service | Using Specmatic Trial license initialized from jar:file:/usr/local/share/enterprise/enterprise.jar!/specmatic-default-trial-license.txt\n",
                encoding="utf-8",
            )
            spec = SimpleNamespace(
                upstream_lab=upstream_lab,
                phases=(SimpleNamespace(name="Baseline mismatch", output_dir_name="baseline"),),
            )
            snapshot = {"root": root, "phases": [{"name": "Baseline mismatch", "command": {"display": "python3 wrapper.py"}}]}
            profile = build_license_profile(spec, snapshot)
            self.assertTrue(profile["consistent"])
            self.assertEqual(profile["detectedMode"], "trial")
            self.assertEqual(profile["rows"][0]["status"], "Pass")
            self.assertIn("compose.log", profile["rows"][0]["path"])

    def test_build_license_profile_marks_non_specmatic_phase_not_applicable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upstream_lab = root / "lab"
            upstream_lab.mkdir()
            (upstream_lab / "docker-compose.yaml").write_text(
                """
services:
  consumer:
    container_name: quick-start-mock-consumer
    image: python:3.14-alpine
  mock:
    container_name: quick-start-mock-server
    image: specmatic/enterprise:latest
""".strip()
                + "\n",
                encoding="utf-8",
            )
            phase_dir = root / "baseline"
            phase_dir.mkdir(parents=True)
            (phase_dir / "command.log").write_text("python3 wrapper.py\n", encoding="utf-8")
            (phase_dir / "docker-logs").mkdir(parents=True)
            (phase_dir / "docker-logs" / "quick-start-mock-consumer.log").write_text(
                "serving http on 0.0.0.0 port 8081\n",
                encoding="utf-8",
            )
            spec = SimpleNamespace(
                upstream_lab=upstream_lab,
                phases=(SimpleNamespace(name="Baseline mismatch", output_dir_name="baseline"),),
            )
            snapshot = {"root": root, "phases": [{"name": "Baseline mismatch", "command": {"display": "python3 wrapper.py"}}]}
            profile = build_license_profile(spec, snapshot)
            self.assertTrue(profile["consistent"])
            self.assertEqual(profile["detectedMode"], "not-applicable")
            self.assertEqual(profile["rows"][0]["status"], "Not Applicable")


if __name__ == "__main__":
    unittest.main()
