from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lablib.compose_runtime import rewrite_compose_file


class ComposeRuntimeTests(unittest.TestCase):
    def test_rewrite_compose_file_absolutizes_relative_volume_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            compose_dir = root / "lab"
            compose_dir.mkdir()
            source = compose_dir / "docker-compose.yaml"
            source.write_text(
                "\n".join(
                    [
                        "services:",
                        "  mock:",
                        "    image: specmatic/enterprise:latest",
                        "    volumes:",
                        "      - ./:/usr/src/app",
                        "      - ../license.txt:/specmatic/specmatic-license.txt:ro",
                        "    ports:",
                        '      - "9100:9100"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            destination = root / "rewritten.yaml"

            rewrite_compose_file(source, destination, {"mock": {9100: 51000}})

            rewritten = destination.read_text(encoding="utf-8")
            self.assertIn(f"      - {compose_dir.resolve()}:/usr/src/app", rewritten)
            self.assertIn(
                f"      - {(compose_dir.parent / 'license.txt').resolve()}:/specmatic/specmatic-license.txt:ro",
                rewritten,
            )
            self.assertIn('      - "51000:9100"', rewritten)


if __name__ == "__main__":
    unittest.main()
