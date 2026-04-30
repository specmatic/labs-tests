from __future__ import annotations

from pathlib import Path
import unittest

from lablib.command_runner import CommandResult
from lablib.readme_expectations import README_V2_H2_SEQUENCE
from lablib.readme_schema import parse_readme_document
from lablib.scaffold import (
    LabSpec,
    PhaseSpec,
    ValidationContext,
    evaluate_readme_console_structure,
    evaluate_readme_os_documentation,
    evaluate_v2_phase_readme_alignment,
)


ROOT = Path(__file__).resolve().parents[1]
LABS_ROOT = ROOT.parent / "labs"


class ReadmeSchemaTest(unittest.TestCase):
    def test_quick_start_api_testing_v2_readme_parses(self) -> None:
        document = parse_readme_document((LABS_ROOT / "quick-start-api-testing" / "README.md").read_text(encoding="utf-8"))
        self.assertTrue(document.is_v2)
        self.assertEqual(document.h2_titles, list(README_V2_H2_SEQUENCE))
        self.assertEqual([phase.id for phase in document.phases], ["baseline", "final"])

    def test_external_examples_v2_readme_parses(self) -> None:
        document = parse_readme_document((LABS_ROOT / "external-examples" / "README.md").read_text(encoding="utf-8"))
        self.assertTrue(document.is_v2)
        self.assertEqual(document.h2_titles, list(README_V2_H2_SEQUENCE))
        self.assertEqual([phase.id for phase in document.phases], ["baseline", "final"])
        self.assertFalse(document.metadata["reports"]["ctrf"])
        self.assertFalse(document.metadata["reports"]["html"])

    def test_v2_phase_requires_shell_fences(self) -> None:
        readme_text = """---
lab_schema: v2
reports:
  ctrf: false
  html: false
  readme_summary: true
---
# Sample Lab
## Objective
Text
## Why this lab matters
Text
## Time required
Text
## Prerequisites
Text
## Architecture
Text
## Files in this lab
Text
## Lab Rules
Text
## Specmatic references
Text
## Lab Implementation Phases
### Baseline Phase
<!--
phase-meta
id: baseline
kind: baseline
-->
```bash
docker run demo
```
```terminaloutput
Tests run: 1, Successes: 1, Failures: 0
```
## Pass Criteria
Text
## Troubleshooting
Text
## Cleanup
Text
## What you learned
Text
## Next step
Text
"""
        failures = self._phase_failures(readme_text, "baseline")
        self.assertIn("readme.v2.phase.command_fences", failures)

    def test_v2_phase_requires_following_terminaloutput_in_same_phase(self) -> None:
        readme_text = """---
lab_schema: v2
reports:
  ctrf: false
  html: false
  readme_summary: true
---
# Sample Lab
## Objective
Text
## Why this lab matters
Text
## Time required
Text
## Prerequisites
Text
## Architecture
Text
## Files in this lab
Text
## Lab Rules
Text
## Specmatic references
Text
## Lab Implementation Phases
### Baseline Phase
<!--
phase-meta
id: baseline
kind: baseline
-->
```shell
docker run demo
```
### Final Phase
<!--
phase-meta
id: final
kind: final
-->
```terminaloutput
Tests run: 1, Successes: 1, Failures: 0
```
## Pass Criteria
Text
## Troubleshooting
Text
## Cleanup
Text
## What you learned
Text
## Next step
Text
"""
        failures = self._phase_failures(readme_text, "baseline")
        self.assertIn("readme.v2.phase.outputs", failures)

    def test_v2_phase_allows_skipped_teardown_command_without_terminaloutput(self) -> None:
        readme_text = """---
lab_schema: v2
reports:
  ctrf: false
  html: false
  readme_summary: true
---
# Sample Lab
## Objective
Text
## Why this lab matters
Text
## Time required
Text
## Prerequisites
Text
## Architecture
Text
## Files in this lab
Text
## Lab Rules
Text
## Specmatic references
Text
## Lab Implementation Phases
### Baseline Phase
<!--
phase-meta
id: baseline
kind: baseline
-->
```shell
docker compose down -v
```
```shell
docker run demo
```
```terminaloutput
Tests run: 1, Successes: 1, Failures: 0
```
## Pass Criteria
Text
## Troubleshooting
Text
## Cleanup
Text
## What you learned
Text
## Next step
Text
"""
        failures = self._phase_failures(readme_text, "baseline")
        self.assertNotIn("readme.v2.phase.outputs", failures)

    def test_v2_phase_rejects_terminaloutput_casing_variants(self) -> None:
        readme_text = """---
lab_schema: v2
reports:
  ctrf: false
  html: false
  readme_summary: true
---
# Sample Lab
## Objective
Text
## Why this lab matters
Text
## Time required
Text
## Prerequisites
Text
## Architecture
Text
## Files in this lab
Text
## Lab Rules
Text
## Specmatic references
Text
## Lab Implementation Phases
### Baseline Phase
<!--
phase-meta
id: baseline
kind: baseline
-->
```shell
docker run demo
```
```terminalOutput
Tests run: 1, Successes: 1, Failures: 0
```
## Pass Criteria
Text
## Troubleshooting
Text
## Cleanup
Text
## What you learned
Text
## Next step
Text
"""
        failures = self._phase_failures(readme_text, "baseline")
        self.assertIn("readme.v2.phase.output_fences", failures)

    def test_legacy_readme_rejects_bare_command_fences(self) -> None:
        readme_text = """# Sample Lab

## Baseline

```
docker run demo
```
```terminaloutput
containers are up
```
"""
        failures = self._legacy_failures(readme_text)
        self.assertIn("readme.commands.executable_fences", failures)

    def test_legacy_readme_rejects_terminaloutput_casing_variants(self) -> None:
        readme_text = """# Sample Lab

## Baseline

```shell
docker run demo
```
```terminalOutput
containers are up
```
"""
        failures = self._legacy_failures(readme_text)
        self.assertIn("readme.output.terminaloutput_fence", failures)
        self.assertNotIn("readme.command_output.followup", failures)

    def _phase_failures(self, readme_text: str, phase_id: str) -> set[str]:
        document = parse_readme_document(readme_text)
        phase = PhaseSpec(name=phase_id, description="phase", expected_exit_code=0, readme_phase_id=phase_id)
        lab = LabSpec(
            name="sample",
            description="sample",
            root=ROOT,
            upstream_lab=ROOT,
            files={},
            readme_path=ROOT / "README.md",
            output_dir=ROOT / "output",
            command=["echo", "sample"],
            phases=(phase,),
        )
        result = CommandResult(
            command=["echo", "sample"],
            cwd=str(ROOT),
            exit_code=0,
            stdout="Tests run: 1, Successes: 1, Failures: 0",
            stderr="",
            started_at="2026-04-30T00:00:00+00:00",
            finished_at="2026-04-30T00:00:01+00:00",
            duration_seconds=1.0,
        )
        context = ValidationContext(
            lab=lab,
            phase=phase,
            target_dir=ROOT,
            command_result=result,
            executed_command=["echo", "sample"],
            readme_text=readme_text,
            readme_doc=document,
            artifacts={},
            original_files={},
        )
        return {
            assertion["code"]
            for assertion in evaluate_v2_phase_readme_alignment(context)
            if assertion["status"] == "failed"
        }

    def _legacy_failures(self, readme_text: str) -> set[str]:
        document = parse_readme_document(readme_text)
        phase = PhaseSpec(name="baseline", description="phase", expected_exit_code=0, readme_phase_id=None)
        lab = LabSpec(
            name="sample",
            description="sample",
            root=ROOT,
            upstream_lab=ROOT,
            files={},
            readme_path=ROOT / "README.md",
            output_dir=ROOT / "output",
            command=["echo", "sample"],
            phases=(phase,),
        )
        result = CommandResult(
            command=["echo", "sample"],
            cwd=str(ROOT),
            exit_code=0,
            stdout="Tests run: 1, Successes: 1, Failures: 0",
            stderr="",
            started_at="2026-04-30T00:00:00+00:00",
            finished_at="2026-04-30T00:00:01+00:00",
            duration_seconds=1.0,
        )
        context = ValidationContext(
            lab=lab,
            phase=phase,
            target_dir=ROOT,
            command_result=result,
            executed_command=["echo", "sample"],
            readme_text=readme_text,
            readme_doc=document,
            artifacts={},
            original_files={},
        )
        assertions = [
            *evaluate_readme_console_structure(context),
            *evaluate_readme_os_documentation(context),
        ]
        return {
            assertion["code"]
            for assertion in assertions
            if assertion["status"] == "failed"
        }


if __name__ == "__main__":
    unittest.main()
