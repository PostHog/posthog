"""The crossings ledger grows only in a change to the scanner.

products/architecture.md § Wiring couplings: the ledger records the debt that existed when a check
landed, and it takes no new exceptions. The repo-invariant test holds the file equal to a scan of
the tree, so it passes a change that adds a coupling and its line together. This check compares the
file with the pull request's base instead. A change to the scanner may add lines, because a new
check records the findings that already exist when it lands, and because an approved exception
(an approved interface, a MODEL_CROSSINGS entry, a carve-out) is a scanner change too.

Growth is crossings.grown_debt, the rule a regenerate applies too.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .crossings import BASELINE_PATH, grown_debt, parse_baseline, read_baseline
from .paths import REPO_ROOT

# CI sets this to the pull request's base commit. Unset, the check does not run.
LEDGER_BASE_ENV = "CROSSINGS_LEDGER_BASE"

# A change here may add ledger lines, so .stamphog/policy.yml holds the whole folder under
# devex_guardrails: such a change always gets a human review.
SCANNER_DIR = "tools/hogli-commands/hogli_commands/product/"

LEDGER_GROWTH_INSTRUCTION = (
    f"{BASELINE_PATH.name} records the debt that existed when a DevEx check landed. It takes no new "
    "lines, and a hand-edited line is not an exception. Change the caller instead: "
    "`hogli product:crossings <product>` and `hogli product:lint <product>` print the move for each "
    "kind. A coupling that must stand needs a DevEx change to the scanner in "
    f"{SCANNER_DIR} (an approved interface, a MODEL_CROSSINGS entry or a carve-out). Only such a "
    "change may add lines."
)


class LedgerBaseUnreadable(Exception):
    pass


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise LedgerBaseUnreadable(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def ledger_growth_issues(repo_root: Path = REPO_ROOT, ledger_path: Path = BASELINE_PATH) -> list[str] | None:
    """The debt the ledger gained since the base, or None when no base is set."""
    ref = os.environ.get(LEDGER_BASE_ENV)
    if not ref:
        return None
    ledger = ledger_path.relative_to(repo_root).as_posix()
    try:
        base = _git(repo_root, "merge-base", ref, "HEAD").strip()
        base_text = _git(repo_root, "show", f"{base}:{ledger}")
        scanner_changes = _git(repo_root, "diff", "--name-only", base, "HEAD", "--", SCANNER_DIR)
    except LedgerBaseUnreadable as error:
        return [f"{LEDGER_BASE_ENV}={ref} could not be read: {error}"]
    if scanner_changes.strip():
        return []
    return grown_debt(parse_baseline(base_text), read_baseline(ledger_path))
