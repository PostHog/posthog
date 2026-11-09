"""Find tests that no team owns: new test files, and directories missing from the baseline.

Shared by the CI gates (test_unowned_test_directories.py and `hogli lint:test-owners`) and the
`test-owners` preflight check.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import click
from hogli.manifest import REPO_ROOT
from owners_yaml import GitRefSource, OwnersResolver, runner_for_path, unowned_test_directories
from owners_yaml.census import UNOWNED_TEAM, owning_team
from owners_yaml.schema import DEFAULT_ALIAS_FILES, OWNERS_FILENAME

from hogli_commands.change_detection import matches_globs
from hogli_commands.preflight_checks import Outcome, Scope

BASELINE = Path("posthog/test/repo_invariants/unowned_test_directories_baseline.txt")
PRUNE = "PYTHONPATH=.:tools/hogli-commands python posthog/test/repo_invariants/test_unowned_test_directories.py"

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


def unowned_new_tests(merge_base: str, committed_only: bool = False) -> list[str]:
    """Test files that are absent at `merge_base` and that no team owns.

    The baseline lists directories, so this is what stops a new unowned test in a listed directory.
    A moved test counts as new.
    """
    resolver, files = _tree(committed_only)
    new = set(files) - GitRefSource(REPO_ROOT, ref=merge_base).files
    return sorted(path for path in new if runner_for_path(path) and owning_team(resolver.resolve(path)) == UNOWNED_TEAM)


def new_test_problems(paths: Iterable[str]) -> list[str]:
    return [f"{path} is a new test that no team owns: name the team in its nearest owners.yaml" for path in paths]


def check_test_owners(scope: Scope) -> Outcome:
    # `*/test_*.py` also matches `test_utils/foo.py`.
    if not any(runner_for_path(path) or matches_globs(path, OWNERSHIP_FILE_GLOBS) for path in scope.files):
        return "pass", "no test or ownership file changed"
    problems = [
        *new_test_problems(unowned_new_tests(scope.merge_base, scope.committed_only)),
        *drift_problems(baseline_drift(scope.committed_only)),
    ]
    if not problems:
        return "pass", "every new test has a team owner"
    detail = " · ".join(problems[:3]) + (f" · and {len(problems) - 3} more" if len(problems) > 3 else "")
    # The baseline scan covers the whole tree, so a gap that another branch left on master would block
    # every push that touches a test. CI rejects these problems, and this check only warns before the push.
    return "warning", detail


@click.command(name="lint:test-owners", help="Fail when the branch adds a test file that no team owns.")
@click.option("--against", default="origin/master", show_default=True, help="Diff base ref.")
@click.option("--committed", is_flag=True, help="Check commits only, not the working tree.")
def cmd_lint_test_owners(against: str, committed: bool) -> None:
    merge_base = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "merge-base", against, "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    if not merge_base:
        raise click.ClickException(f"no merge base with {against}")
    problems = new_test_problems(unowned_new_tests(merge_base, committed))
    for problem in problems:
        click.echo(problem)
    if problems:
        click.echo(
            "A failing test with no team owner reaches nobody. `hogli owners:who <path>` shows which owners.yaml applies."
        )
        raise SystemExit(1)
