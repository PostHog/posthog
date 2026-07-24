#!/usr/bin/env python3
"""Workspace-local entry point invoked by pi-autoresearch's run_experiment.

Placeholders (``__KEY__``) are filled in by ``ch_campaign_init.py``.
"""

from __future__ import annotations

import sys
import subprocess
from pathlib import Path

PACKAGE_ROOT = Path("__PACKAGE_ROOT__")
WORKSPACE_DIR = Path(__file__).resolve().parent


def main() -> int:
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(PACKAGE_ROOT / "scripts" / "ch_run_candidate.py"),
            "--workspace",
            str(WORKSPACE_DIR),
            "--label",
            "autoresearch",
        ],
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
