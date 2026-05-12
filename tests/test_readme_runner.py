from __future__ import annotations

import unittest

from lablib.readme_runner import build_readme_lab_spec


class ReadmeRunnerPilotTests(unittest.TestCase):
    def test_api_coverage_is_driven_by_pilot_config(self) -> None:
        spec = build_readme_lab_spec("api-coverage")

        self.assertIn("service_spec", spec.files)
        self.assertEqual(spec.command_env["PETSTORE_PORT"], str(int(spec.command_env["PETSTORE_PORT"])))
        self.assertEqual(
            [phase.readme_phase_id for phase in spec.phases],
            ["baseline", "final"],
        )
        self.assertIn("service_spec", spec.phases[0].file_transforms)
        self.assertIsNotNone(spec.phases[0].extra_assertions)
        self.assertEqual(
            spec.phases[1].fix_summary,
            (
                "Changed the contract path from GET /pets/search to GET /pets/find in specs/service.yaml.",
                "Re-ran the same Specmatic test command against the running provider to confirm both operations are covered.",
            ),
        )

    def test_quick_start_api_testing_is_driven_by_pilot_config(self) -> None:
        spec = build_readme_lab_spec("quick-start-api-testing")

        self.assertEqual(
            set(spec.files.keys()),
            {"finance_11", "support_55"},
        )
        self.assertEqual(
            [phase.readme_phase_id for phase in spec.phases],
            ["baseline", "intermediate", "final"],
        )

        artifact_labels = {artifact.label for artifact in spec.common_artifact_specs}
        self.assertIn("ctrf-report.json", artifact_labels)
        self.assertIn("specmatic-report.html", artifact_labels)
        self.assertIn("test_finance_user_11.json", artifact_labels)
        self.assertIn("test_support_user_55.json", artifact_labels)

        task_a = spec.phases[1]
        self.assertIn("finance_11", task_a.file_transforms)
        self.assertIn("support_55", task_a.file_transforms)
        self.assertIsNotNone(task_a.extra_assertions)
        self.assertEqual(
            task_a.fix_summary,
            ("Changed examples/test_finance_user_11.json so decision uses $match(pattern: approved|verified).",),
        )


if __name__ == "__main__":
    unittest.main()
