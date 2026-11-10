"""CI fails on a new test file that has no owner, because a failing test with no owner reaches nobody."""

from __future__ import annotations

import subprocess

import click
from hogli.manifest import REPO_ROOT
from owners_yaml import newly_unowned, runner_for_path

from hogli_commands.preflight_checks import Outcome, Scope

HINT = "Name the owner in the nearest owners.yaml. `hogli owners:who <path>` shows which file applies."


def _unowned_new_tests(against: str, committed_only: bool) -> list[str]:
    return [path for path in newly_unowned(REPO_ROOT, against, committed_only=committed_only) if runner_for_path(path)]


def check_test_owners(scope: Scope) -> Outcome:
    tests = _unowned_new_tests(scope.merge_base, scope.committed_only)
    if not tests:
        return "pass", "every new test has an owner"
    return "warning", f"CI fails on {len(tests)} new test(s) with no owner, such as {tests[0]}. {HINT}"


@click.command(name="lint:test-owners", help="Fail when the branch leaves a test file with no owner.")
@click.option("--against", default="origin/master", show_default=True, help="Ref to compare with, at its merge base.")
@click.option("--committed", is_flag=True, help="Read HEAD and not the working tree.")
def cmd_lint_test_owners(against: str, committed: bool) -> None:
    try:
        tests = _unowned_new_tests(against, committed)
    except subprocess.CalledProcessError as error:
        raise click.ClickException(f"could not compare with {against!r}: {error.stderr.strip()}") from error
    if not tests:
        return
    # The pull request author controls each path, and CI reads a line that starts with `::` as a
    # workflow command. The fixed prefix keeps the path off the start of the line, and the escapes
    # stop a newline in the path from starting another line.
    for path in tests:
        click.echo("no owner: " + path.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A"))
    click.echo(HINT)
    raise SystemExit(1)
