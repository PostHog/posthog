"""Compare the directories that hold unowned tests with the baseline that repo-checks enforces.

posthog/test/repo_invariants/test_unowned_test_directories.py gates CI on it, and the
`test-owners` preflight check runs the same comparison before a push.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from hogli.manifest import REPO_ROOT
from owners_yaml import OwnersResolver, runner_for_path, unowned_test_directories
from owners_yaml.schema import DEFAULT_ALIAS_FILES, OWNERS_FILENAME

from hogli_commands.preflight_checks import Outcome, Scope

BASELINE = Path("posthog/test/repo_invariants/unowned_test_directories_baseline.txt")
PRUNE = "PYTHONPATH=.:tools/hogli-commands python posthog/test/repo_invariants/test_unowned_test_directories.py"
BLOCKING_FROM = date.fromisoformat("2026-11-11")

# fnmatch globs for the preflight trigger, where `*` spans `/`. runner_for_path decides inside the check.
TEST_FILE_GLOBS = (
    "test_*.py",
    "*/test_*.py",
    "*_test.py",
    *(f"*.{kind}.{ext}" for kind in ("test", "spec") for ext in ("js", "jsx", "ts", "tsx")),
)
OWNERSHIP_FILE_GLOBS = (
    OWNERS_FILENAME,
    *(f"*/{name}" for name in (OWNERS_FILENAME, *DEFAULT_ALIAS_FILES)),
    str(BASELINE),
)


@dataclass(frozen=True, kw_only=True, slots=True)
class BaselineDrift:
    added: list[str]
    removed: list[str]


def read_baseline() -> set[str]:
    text = (REPO_ROOT / BASELINE).read_text(encoding="utf-8")
    return {line.strip() for line in text.splitlines() if line.strip()}


def baseline_drift() -> BaselineDrift:
    current = unowned_test_directories(OwnersResolver(REPO_ROOT))
    baseline = read_baseline()
    return BaselineDrift(added=sorted(current - baseline), removed=sorted(baseline - current))


def prune_baseline() -> None:
    """Drop the directories that hold no unowned tests. It never adds one, so a new gap stays a failure."""
    remaining = sorted(read_baseline() & unowned_test_directories(OwnersResolver(REPO_ROOT)))
    (REPO_ROOT / BASELINE).write_text("".join(f"{directory}\n" for directory in remaining), encoding="utf-8")


def drift_problems(drift: BaselineDrift) -> list[str]:
    return [
        *(
            f"{directory} holds tests that no team owns: name the team in its nearest owners.yaml"
            for directory in drift.added
        ),
        *(f"{directory} has no unowned tests left: run `{PRUNE}`" for directory in drift.removed),
    ]


def _is_ownership_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name in (OWNERS_FILENAME, *DEFAULT_ALIAS_FILES) or path == str(BASELINE)


def _uncommitted_ownership_files() -> list[str]:
    status = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain", "-z", "--no-renames", "--untracked-files=all"],
        capture_output=True,
        text=True,
    )
    return sorted(entry[3:] for entry in status.stdout.split("\0") if len(entry) > 3 and _is_ownership_file(entry[3:]))


def check_test_owners(scope: Scope) -> Outcome:
    # The trigger globs over-match (`*/test_*.py` also matches `test_utils/foo.py`), so decide here.
    if not any(runner_for_path(path) or _is_ownership_file(path) for path in scope.files):
        return "pass", "no test or ownership file changed"
    # Ownership resolves from the working tree, so an uncommitted owners.yaml would pass here and fail in CI.
    if scope.committed_only and (dirty := _uncommitted_ownership_files()):
        return "fail", f"commit or discard the changes to {', '.join(dirty[:3])}: the push carries only HEAD"
    problems = drift_problems(baseline_drift())
    if not problems:
        return "pass", "no new directory of unowned tests"
    return "fail", " · ".join(problems[:3]) + (f" · and {len(problems) - 3} more" if len(problems) > 3 else "")
