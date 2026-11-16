"""Compare the directories that hold unowned tests with the baseline.

Shared by test_unowned_test_directories.py (the CI gate) and the `test-owners` preflight check.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from hogli.manifest import REPO_ROOT
from owners_yaml import GitRefSource, OwnersResolver, runner_for_path, unowned_test_directories
from owners_yaml.schema import DEFAULT_ALIAS_FILES, OWNERS_FILENAME

from hogli_commands.change_detection import matches_globs
from hogli_commands.preflight_checks import Outcome, Scope

BASELINE = Path("posthog/test/repo_invariants/unowned_test_directories_baseline.txt")
PRUNE = "PYTHONPATH=.:tools/hogli-commands python posthog/test/repo_invariants/test_unowned_test_directories.py"
BLOCKING_FROM = date.fromisoformat("2026-11-11")

# fnmatch: `*` spans `/`.
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


def _git_paths(*args: str) -> set[str]:
    result = subprocess.run(["git", "-C", str(REPO_ROOT), *args, "-z"], capture_output=True, text=True, check=True)
    return {path for path in result.stdout.split("\0") if path}


def _tree(committed_only: bool) -> tuple[OwnersResolver, Iterable[str]]:
    """HEAD for a push, or the working tree, untracked files included, for a local run."""
    if committed_only:
        head = GitRefSource(REPO_ROOT)
        return OwnersResolver(REPO_ROOT, source=head), head.files
    files = _git_paths("ls-files", "--cached", "--others", "--exclude-standard") - _git_paths("ls-files", "--deleted")
    return OwnersResolver(REPO_ROOT), files


def _baseline(resolver: OwnersResolver) -> set[str]:
    return set((resolver.source.read(str(BASELINE)) or "").split())


def baseline_drift(committed_only: bool = False) -> BaselineDrift:
    resolver, files = _tree(committed_only)
    current = unowned_test_directories(resolver, files)
    baseline = _baseline(resolver)
    return BaselineDrift(added=sorted(current - baseline), removed=sorted(baseline - current))


def prune_baseline() -> None:
    """Never adds a directory, so a new gap stays a failure."""
    resolver, files = _tree(committed_only=False)
    remaining = sorted(_baseline(resolver) & unowned_test_directories(resolver, files))
    (REPO_ROOT / BASELINE).write_text("".join(f"{directory}\n" for directory in remaining), encoding="utf-8")


def drift_problems(drift: BaselineDrift) -> list[str]:
    return [
        *(
            f"{directory} holds tests that no team owns: name the team in its nearest owners.yaml"
            for directory in drift.added
        ),
        *(f"{directory} has no unowned tests left: run `{PRUNE}`" for directory in drift.removed),
    ]


def check_test_owners(scope: Scope) -> Outcome:
    # `*/test_*.py` also matches `test_utils/foo.py`.
    if not any(runner_for_path(path) or matches_globs(path, OWNERSHIP_FILE_GLOBS) for path in scope.files):
        return "pass", "no test or ownership file changed"
    drift = baseline_drift(scope.committed_only)
    problems = drift_problems(drift)
    if not problems:
        return "pass", "no new directory of unowned tests"
    detail = " · ".join(problems[:3]) + (f" · and {len(problems) - 3} more" if len(problems) > 3 else "")
    # Mirrors enforce_baseline in posthog/test/repo_invariants/ratchet.py.
    if drift.removed or date.today() >= BLOCKING_FROM:
        return "fail", detail
    return "warning", f"not blocking until {BLOCKING_FROM.isoformat()}: {detail}"
