from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from lablib.workspace_setup import LicenseFileState, refresh_upstream_labs, resolve_license_txt_content, restore_upstream_labs_license


class WorkspaceSetupLicenseTests(unittest.TestCase):
    def test_resolve_license_txt_content_from_github_secret(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GITHUB_ACTIONS": "true",
                "SPECMATIC_LICENSE_KEY": "LICENSE-FROM-SECRET",
            },
            clear=False,
        ):
            content, source = resolve_license_txt_content()
        self.assertEqual(content, "LICENSE-FROM-SECRET\n")
        self.assertIn("SPECMATIC_LICENSE_KEY", source)

    def test_resolve_license_txt_content_from_local_temp_file(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            temp_dir = root / "temp"
            temp_dir.mkdir(parents=True)
            (temp_dir / "License-labs-test.txt").write_text(
                "LOCAL-LICENSE-CONTENT",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"GITHUB_ACTIONS": "", "GITHUB_RUN_ID": ""}, clear=False):
                with patch("lablib.workspace_setup.ROOT", root):
                    content, source = resolve_license_txt_content()
        self.assertEqual(content, "LOCAL-LICENSE-CONTENT\n")
        self.assertIn("License-labs-test.txt", source)

    def test_resolve_license_txt_content_from_local_temp_file_case_insensitive(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            temp_dir = root / "temp"
            temp_dir.mkdir(parents=True)
            (temp_dir / "license-LABS-test-Local.TXT").write_text(
                "LOCAL-LICENSE-CONTENT",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"GITHUB_ACTIONS": "", "GITHUB_RUN_ID": ""}, clear=False):
                with patch("lablib.workspace_setup.ROOT", root):
                    content, source = resolve_license_txt_content()
        self.assertEqual(content, "LOCAL-LICENSE-CONTENT\n")
        self.assertIn("license-LABS-test-Local.TXT", source)

    def test_resolve_license_txt_content_fails_when_multiple_local_temp_files_exist(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            temp_dir = root / "temp"
            temp_dir.mkdir(parents=True)
            (temp_dir / "License-labs-test.txt").write_text("ONE", encoding="utf-8")
            (temp_dir / "License-labs-test-Local.txt").write_text("TWO", encoding="utf-8")
            with patch.dict(os.environ, {"GITHUB_ACTIONS": "", "GITHUB_RUN_ID": ""}, clear=False):
                with patch("lablib.workspace_setup.ROOT", root):
                    with self.assertRaises(RuntimeError) as exc:
                        resolve_license_txt_content()
        self.assertIn("multiple local labs-test license files", str(exc.exception))

    def test_restore_upstream_labs_license_restores_original_or_deletes_file(self) -> None:
        with TemporaryDirectory() as tmp:
            license_path = Path(tmp) / "license.txt"

            license_path.write_text("ORIGINAL", encoding="utf-8")
            restore_upstream_labs_license(
                LicenseFileState(
                    path=license_path,
                    existed=True,
                    original_content="ORIGINAL",
                    applied_source="test",
                )
            )
            self.assertEqual(license_path.read_text(encoding="utf-8"), "ORIGINAL")

            license_path.write_text("TEMPORARY", encoding="utf-8")
            restore_upstream_labs_license(
                LicenseFileState(
                    path=license_path,
                    existed=False,
                    original_content=None,
                    applied_source="test",
                )
            )
            self.assertFalse(license_path.exists())

    def test_refresh_upstream_labs_fetches_remote_tracking_refs_for_target_and_main(self) -> None:
        executed: list[list[str]] = []

        class FakeResult:
            def __init__(self, command: list[str]) -> None:
                self.command = command
                self.cwd = "/tmp/labs"
                self.exit_code = 0
                self.started_at = ""
                self.finished_at = ""
                self.duration_seconds = 0.0
                self.stdout = ""
                self.stderr = ""

        def fake_execute(command, cwd, prefix, *, stream_output):
            executed.append(command)
            return FakeResult(command)

        with patch("lablib.workspace_setup.execute", side_effect=fake_execute):
            refresh_upstream_labs(stream_output=False, target_branch="dynamic-labs")

        self.assertEqual(
            executed[0],
            ["git", "fetch", "origin", "refs/heads/dynamic-labs:refs/remotes/origin/dynamic-labs"],
        )
        self.assertEqual(
            executed[1],
            ["git", "fetch", "origin", "refs/heads/main:refs/remotes/origin/main"],
        )
        self.assertEqual(
            executed[2],
            ["git", "branch", "-f", "origin/main", "refs/remotes/origin/main"],
        )

    def test_refresh_upstream_labs_fetches_main_once_when_target_is_main(self) -> None:
        executed: list[list[str]] = []

        class FakeResult:
            def __init__(self, command: list[str]) -> None:
                self.command = command
                self.cwd = "/tmp/labs"
                self.exit_code = 0
                self.started_at = ""
                self.finished_at = ""
                self.duration_seconds = 0.0
                self.stdout = ""
                self.stderr = ""

        def fake_execute(command, cwd, prefix, *, stream_output):
            executed.append(command)
            return FakeResult(command)

        with patch("lablib.workspace_setup.execute", side_effect=fake_execute):
            refresh_upstream_labs(stream_output=False, target_branch="main")

        self.assertEqual(
            executed[0],
            ["git", "fetch", "origin", "refs/heads/main:refs/remotes/origin/main"],
        )
        self.assertEqual(
            executed[1],
            ["git", "branch", "-f", "origin/main", "refs/remotes/origin/main"],
        )
        self.assertEqual(sum(1 for command in executed if command[:3] == ["git", "fetch", "origin"]), 1)


if __name__ == "__main__":
    unittest.main()
