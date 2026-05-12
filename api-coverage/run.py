from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lablib.readme_runner import build_readme_lab_spec
from lablib.scaffold import add_standard_lab_args, run_lab


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the api-coverage lab automation from the README-driven execution plan."))
    args = parser.parse_args()
    return run_lab(build_readme_lab_spec("api-coverage"), args)


def build_lab_spec():
    return build_readme_lab_spec("api-coverage")


if __name__ == "__main__":
    raise SystemExit(main())
