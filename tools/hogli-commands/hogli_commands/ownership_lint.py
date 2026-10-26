"""Compare the directories that hold unowned tests with the baseline that repo-checks enforces.

posthog/test/repo_invariants/test_unowned_test_directories.py gates CI on it, and the
`test-owners` preflight check runs the same comparison before a push.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from hogli.manifest import REPO_ROOT
from owners_yaml import OwnersResolver, runner_for_path, unowned_test_directories

from hogli_commands.preflight_checks import Outcome, Scope, _git

BASELINE = Path("posthog/test/repo_invariants/unowned_test_directories_baseline.txt")
PRUNE = (
    "PYTHONPATH=.:tools/hogli:tools/hogli-commands python posthog/test/repo_invariants/test_unowned_test_directories.py"
)
BLOCKING_FROM = date.fromisoformat("2026-11-02")


@dataclass(frozen=True, kw_only=True, slots=True)
class BaselineDrift:
    added: list[str]  # directories of unowned tests that the baseline does not list
    removed: list[str]  # listed directories that hold no unowned tests


def read_baseline() -> set[str]:
    text = (REPO_ROOT / BASELINE).read_text(encoding="utf-8")
    return {line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")}


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


def _can_change_baseline(scope: Scope) -> bool:
    """An edit inside an existing test file cannot change which directories hold unowned tests.
    Adding, deleting or moving a test can, and so can any change to an ownership file or the baseline."""
    if any(runner_for_path(path) is None for path in scope.files):
        return True
    head = ["HEAD"] if scope.committed_only else []
    added_or_removed = _git("diff", "--name-only", "--diff-filter=ADR", scope.merge_base, *head, "--", *scope.files)
    return added_or_removed is None or bool(added_or_removed.strip())


def check_test_owners(scope: Scope) -> Outcome:
    if not _can_change_baseline(scope):
        return "pass", "no test file was added, deleted or moved"
    drift = baseline_drift()
    problems = drift_problems(drift)
    if not problems:
        return "pass", "no new directory of unowned tests"
    # Match repo-checks, which only warns about a new directory until BLOCKING_FROM.
    status = "warning" if not drift.removed and date.today() < BLOCKING_FROM else "fail"
    return status, " · ".join(problems[:3]) + (f" · and {len(problems) - 3} more" if len(problems) > 3 else "")
