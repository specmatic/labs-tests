from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from lablib.workspace_setup import LicenseFileState, resolve_license_txt_content, restore_upstream_labs_license


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

    def test_resolve_license_txt_content_from_local_license_json(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            license_dir = home / ".specmatic"
            license_dir.mkdir(parents=True)
            (license_dir / "license.json").write_text(
                '{"status": {"license": "LOCAL-LICENSE-CONTENT"}}',
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"GITHUB_ACTIONS": "", "GITHUB_RUN_ID": ""}, clear=False):
                with patch("lablib.workspace_setup.Path.home", return_value=home):
                    content, source = resolve_license_txt_content()
        self.assertEqual(content, "LOCAL-LICENSE-CONTENT\n")
        self.assertIn(".specmatic/license.json", source)

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


if __name__ == "__main__":
    unittest.main()
