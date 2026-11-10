"""Ownership of the files a branch adds.

CI fails on a new test file that has no owner, because a failing test with no owner reaches nobody.
The preflight check warns about every new file with no owner.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import click
from hogli.manifest import REPO_ROOT
from owners_yaml import newly_unowned, runner_for_path

from hogli_commands.preflight_checks import Outcome, Scope

HINT = "Name the owner in the nearest owners.yaml. `hogli owners:who <path>` shows which file applies."


def _one_line(text: str) -> str:
    """Git allows a newline in a path. CI reads a line that starts with `::` as a workflow command,
    so a path that kept its newline could forge an annotation."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _first(paths: list[str]) -> str:
    return ", ".join(paths[:3]) + (f" and {len(paths) - 3} more" if len(paths) > 3 else "")


def check_unowned_paths(scope: Scope) -> Outcome:
    paths = newly_unowned(REPO_ROOT, scope.merge_base, committed_only=scope.committed_only)
    if not paths:
        return "pass", "every new file has an owner"
    if tests := [path for path in paths if runner_for_path(path)]:
        return "warning", f"CI fails on a new test with no owner: {_first(tests)}. {HINT}"
    return "warning", f"no owner for {_first(paths)}. {HINT}"


@click.command(name="lint:test-owners", help="Fail when the branch leaves a test file with no owner.")
@click.option("--against", default="origin/master", show_default=True, help="Ref to compare with, at its merge base.")
@click.option("--committed", is_flag=True, help="Read HEAD and not the working tree.")
def cmd_lint_test_owners(against: str, committed: bool) -> None:
    try:
        paths = newly_unowned(REPO_ROOT, against, committed_only=committed)
    except subprocess.CalledProcessError as error:
        raise click.ClickException(f"could not compare with {against!r}: {error.stderr.strip()}") from error
    tests = [_one_line(path) for path in paths if runner_for_path(path)]
    if not tests:
        return
    for path in tests:
        click.echo(f"{path}: this test has no owner")
    click.echo(HINT)
    if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
        # A fence closes only on a line of its own, so a one-line path cannot break out of the block.
        with Path(summary_path).open("a", encoding="utf-8") as summary:
            summary.write(
                "### Tests with no owner\n\n```text\n" + "".join(f"{path}\n" for path in tests) + f"```\n\n{HINT}\n\n"
            )
    raise SystemExit(1)
