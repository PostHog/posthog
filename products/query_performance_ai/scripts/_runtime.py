"""Shared utilities for the in-sandbox campaign driver.

Used by `run_campaign.py` and `sandboxing.py`. Kept tiny — only the small
helpers and path constants that both files need. Anything campaign-flow
or sandbox-specific lives in its own module.
"""

from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

PRODUCT_DIR = Path(__file__).resolve().parent.parent
AUTORESEARCH_DIR = PRODUCT_DIR / "autoresearch"
SCRIPTS_DIR = AUTORESEARCH_DIR / "scripts"


class CampaignError(RuntimeError):
    pass


def log(msg: str) -> None:
    print(f"[campaign] {msg}", file=sys.stderr, flush=True)  # noqa: T201


def atomic_write(path: Path, contents: str) -> None:
    """Temp-file + rename: a SIGKILL mid-write leaves the original intact."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(contents)
    os.replace(tmp, path)


def run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    log("$ " + " ".join(cmd) + (f"  (cwd={cwd})" if cwd else ""))
    result = subprocess.run(cmd, check=False, text=True, cwd=cwd)  # noqa: S603 — fixed argv from caller
    if result.returncode != 0:
        raise CampaignError(f"command failed with exit {result.returncode}: {' '.join(cmd)}")
    return result
