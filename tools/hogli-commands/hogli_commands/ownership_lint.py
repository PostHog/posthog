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
from owners_yaml import GitRefSource, OwnersResolver, is_unowned_test, runner_for_path, unowned_test_directories
from owners_yaml.schema import DEFAULT_ALIAS_FILES, OWNERS_FILENAME

from hogli_commands.change_detection import matches_globs
from hogli_commands.preflight_checks import Outcome, Scope
from hogli_commands.size_lint import _merge_base

BASELINE = Path("posthog/test/repo_invariants/unowned_test_directories_baseline.txt")
PRUNE = "PYTHONPATH=.:tools/hogli-commands python posthog/test/repo_invariants/test_unowned_test_directories.py"
HINT = "A failing test with no team owner reaches nobody. `hogli owners:who <path>` shows which owners.yaml applies."

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


def _drift(resolver: OwnersResolver, files: Iterable[str]) -> BaselineDrift:
    current = unowned_test_directories(resolver, files)
    baseline = _baseline(resolver)
    return BaselineDrift(added=sorted(current - baseline), removed=sorted(baseline - current))


def baseline_drift(committed_only: bool = False) -> BaselineDrift:
    return _drift(*_tree(committed_only))


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


def _added_paths(merge_base: str, files: Iterable[str], committed_only: bool) -> set[str]:
    """Paths that `merge_base` lacks. Rename detection keeps a moved file out of the set."""
    added = _git_paths(
        "diff", "--name-only", "--diff-filter=A", "--find-renames", merge_base, *(["HEAD"] if committed_only else [])
    )
    if committed_only:
        return added
    untracked = set(files) - _git_paths("ls-files", "--cached")
    return added | untracked


def new_test_problems(
    resolver: OwnersResolver, files: Iterable[str], merge_base: str, committed_only: bool
) -> list[str]:
    """The baseline lists directories, so this is what stops a new unowned test in a listed directory."""
    return [
        f"{path} is a new test that no team owns: name the team in its nearest owners.yaml"
        for path in sorted(_added_paths(merge_base, files, committed_only))
        if is_unowned_test(resolver, path)
    ]


def check_test_owners(scope: Scope) -> Outcome:
    # `*/test_*.py` also matches `test_utils/foo.py`.
    if not any(runner_for_path(path) or matches_globs(path, OWNERSHIP_FILE_GLOBS) for path in scope.files):
        return "pass", "no test or ownership file changed"
    resolver, files = _tree(scope.committed_only)
    problems = [
        *new_test_problems(resolver, files, scope.merge_base, scope.committed_only),
        *drift_problems(_drift(resolver, files)),
    ]
    if not problems:
        return "pass", "every new test has a team owner"
    detail = " · ".join(problems[:3]) + (f" · and {len(problems) - 3} more" if len(problems) > 3 else "")
    # Warn only: the baseline scan covers the whole tree, so a gap left on master would block every push.
    return "warning", detail


@click.command(name="lint:test-owners", help="Fail when the branch adds a test file that no team owns.")
@click.option("--against", default=None, help="Diff base ref. Default: origin/master, then master.")
@click.option("--committed", is_flag=True, help="Check commits only, not the working tree.")
def cmd_lint_test_owners(against: str | None, committed: bool) -> None:
    merge_base = _merge_base(against)
    if merge_base is None:
        raise click.ClickException(f"no merge base with {against or 'origin/master or master'}")
    problems = new_test_problems(*_tree(committed), merge_base, committed)
    for problem in problems:
        click.echo(problem)
    if problems:
        click.echo(HINT)
        raise SystemExit(1)
