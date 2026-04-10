from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lablib.labs_comparison import COMPARISON_HTML_PATH, COMPARISON_JSON_PATH, generate_labs_comparison


def main() -> int:
    generate_labs_comparison(ROOT)
    print(f"Wrote labs comparison JSON report to {COMPARISON_JSON_PATH}")
    print(f"Wrote labs comparison HTML report to {COMPARISON_HTML_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
