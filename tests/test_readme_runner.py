from __future__ import annotations

import argparse
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

    def test_enterprise_image_override_is_added_to_command_env(self) -> None:
        spec = build_readme_lab_spec("api-coverage")
        phase = spec.phases[0]
        args = argparse.Namespace(
            refresh_report=False,
            skip_setup=True,
            refresh_labs=False,
            labs_branch="main",
            force=False,
            enterprise_image="ghcr.io/specmatic/enterprise:1.2.3-rc1",
        )

        command_env = dict(spec.command_env)
        enterprise_image = getattr(args, "enterprise_image", None)
        if enterprise_image:
            command_env["SPECMATIC_ENTERPRISE_IMAGE"] = enterprise_image

        self.assertEqual(
            command_env["SPECMATIC_ENTERPRISE_IMAGE"],
            "ghcr.io/specmatic/enterprise:1.2.3-rc1",
        )


if __name__ == "__main__":
    unittest.main()
