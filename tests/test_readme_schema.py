from __future__ import annotations

from pathlib import Path
import unittest

from lablib.readme_expectations import README_V2_H2_SEQUENCE
from lablib.readme_schema import parse_readme_document


ROOT = Path(__file__).resolve().parents[1]
LABS_ROOT = ROOT.parent / "labs"


class ReadmeSchemaTest(unittest.TestCase):
    def test_quick_start_api_testing_v2_readme_parses(self) -> None:
        document = parse_readme_document((LABS_ROOT / "quick-start-api-testing" / "README.md").read_text(encoding="utf-8"))
        self.assertTrue(document.is_v2)
        self.assertEqual(document.h2_titles, list(README_V2_H2_SEQUENCE))
        self.assertEqual([phase.id for phase in document.phases], ["baseline", "task-a", "final"])
        self.assertEqual([phase.kind for phase in document.phases], ["baseline", "intermediate", "final"])

    def test_external_examples_v2_readme_parses(self) -> None:
        document = parse_readme_document((LABS_ROOT / "external-examples" / "README.md").read_text(encoding="utf-8"))
        self.assertTrue(document.is_v2)
        self.assertEqual(document.h2_titles, list(README_V2_H2_SEQUENCE))
        self.assertEqual([phase.id for phase in document.phases], ["baseline", "studio-fix", "final"])
        self.assertEqual([phase.kind for phase in document.phases], ["baseline", "studio", "final"])
        self.assertEqual(document.metadata["reports"]["ctrf"], False)
        self.assertEqual(document.metadata["reports"]["html"], False)


if __name__ == "__main__":
    unittest.main()
