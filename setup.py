from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lablib.workspace_setup import ROOT as WORKSPACE_ROOT
from lablib.workspace_setup import run_setup


OUTPUT_DIR = WORKSPACE_ROOT / "output"
OUTPUT_PATH = OUTPUT_DIR / "setup-output.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare the upstream labs checkout and Docker images.")
    parser.add_argument(
        "--refresh-labs",
        action="store_true",
        help="Destructively reset ../labs to the latest state on the target branch before refreshing Docker images.",
    )
    parser.add_argument(
        "--branch",
        default="main",
        help="Branch to use with --refresh-labs. Defaults to main.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Required with --refresh-labs when ../labs has local changes. Discards tracked and untracked changes.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Starting workspace setup...")
    result = run_setup(
        stream_output=True,
        refresh_labs=args.refresh_labs,
        target_branch=args.branch,
        force=args.force,
    )
    OUTPUT_PATH.write_text(
        json.dumps(
            {
                "status": result.status,
                "upstreamLabsPath": result.upstream_labs_path,
                "refreshLabs": args.refresh_labs,
                "branch": args.branch,
                "force": args.force,
                "commands": result.commands,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Setup status: {result.status}")
    print(f"Wrote setup details to {OUTPUT_PATH}")
    return 0 if result.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
