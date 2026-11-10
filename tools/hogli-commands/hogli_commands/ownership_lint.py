"""CI fails on a test file that a branch leaves with no team owner, because its failures reach nobody."""

from __future__ import annotations

import subprocess
from pathlib import PurePosixPath

import click
from hogli.manifest import REPO_ROOT
from owners_yaml import OwnersResolver, newly_unowned, runner_for_path

from hogli_commands.preflight_checks import Outcome, Scope

HINT = (
    "Name the owning team in the nearest owners.yaml. An @handle alone does not count. "
    "`hogli owners:who <path>` shows which file applies."
)


def _teamless_tests(against: str, committed_only: bool) -> list[str]:
    return newly_unowned(REPO_ROOT, against, committed_only=committed_only, teams_only=True, include=runner_for_path)


def check_test_owners(scope: Scope) -> Outcome:
    ownership_filenames = OwnersResolver(REPO_ROOT).ownership_filenames()
    if not any(runner_for_path(path) or PurePosixPath(path).name in ownership_filenames for path in scope.changed):
        return "pass", "no test or ownership file changed"
    tests = _teamless_tests(scope.merge_base, scope.committed_only)
    if not tests:
        return "pass", "the branch leaves no test file without a team owner"
    more = f" and {len(tests) - 1} more" if len(tests) > 1 else ""
    return "fail", f"the branch leaves {tests[0]}{more} with no team owner. {HINT}"


@click.command(name="lint:test-owners", help="Fail when the branch leaves a test file with no team owner.")
@click.option("--against", default="origin/master", show_default=True, help="Ref to compare with, at its merge base.")
@click.option("--committed", is_flag=True, help="Read HEAD and not the working tree.")
def cmd_lint_test_owners(against: str, committed: bool) -> None:
    try:
        tests = _teamless_tests(against, committed)
    except subprocess.CalledProcessError as error:
        raise click.ClickException(f"could not compare with {against!r}: {error.stderr.strip()}") from error
    if not tests:
        return
    # The pull request author controls each path, and CI reads a line that starts with `::` as a
    # workflow command. The fixed prefix keeps the path off the start of the line, and the escapes
    # stop a newline in the path from starting another line.
    for path in tests:
        click.echo("no team owner: " + path.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A"))
    click.echo(HINT)
    raise SystemExit(1)
