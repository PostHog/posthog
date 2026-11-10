"""CI fails on a test file that a branch leaves with no team owner, because its failures reach nobody."""

from __future__ import annotations

import subprocess

import click
from hogli.manifest import REPO_ROOT
from owners_yaml import runner_for_path

from hogli_commands.preflight_checks import Outcome, Scope

HINT = (
    "Name the owning team in the nearest owners.yaml. An @handle alone does not count. "
    "`hogli owners:who <path>` shows which file applies."
)


def _teamless_tests(against: str, committed_only: bool) -> list[str]:
    # hogli imports `owners_yaml` from the main clone, also when it runs in a linked worktree, and
    # that copy can be older than this module. The import is here so that preflight then skips this
    # check. At the top of the module it stops every preflight run.
    from owners_yaml import newly_unowned

    return newly_unowned(REPO_ROOT, against, committed_only=committed_only, teams_only=True, include=runner_for_path)


def check_test_owners(scope: Scope) -> Outcome:
    tests = _teamless_tests(scope.merge_base, scope.committed_only)
    if not tests:
        return "pass", "the branch leaves no test file without a team owner"
    more = f" and {len(tests) - 1} more" if len(tests) > 1 else ""
    return "fail", f"the branch leaves {tests[0]!r}{more} with no team owner. {HINT}"


@click.command(name="lint:test-owners", help="Fail when the branch leaves a test file with no team owner.")
@click.option("--against", default="origin/master", show_default=True, help="Ref to compare with, at its merge base.")
@click.option("--committed", is_flag=True, help="Read HEAD and not the working tree.")
def cmd_lint_test_owners(against: str, committed: bool) -> None:
    try:
        tests = _teamless_tests(against, committed)
    except subprocess.CalledProcessError as error:
        reason = error.stderr.strip() or "no merge base"
        raise click.ClickException(f"could not compare with {against!r}: {reason}") from error
    if not tests:
        return
    # The pull request author controls each path, and the GitHub Actions runner reads `::` at the
    # start of a line and `##[` anywhere in a line as a workflow command. The prefix and the quoting
    # keep a path, and a newline in it, off a line start, and the space breaks up each `##[`.
    for path in tests:
        click.echo(f"no team owner: {path!r}".replace("##[", "## ["))
    click.echo(HINT)
    raise SystemExit(1)
