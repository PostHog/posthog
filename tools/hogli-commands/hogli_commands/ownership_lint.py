"""Warn when a changed test file has no team owner in owners.yaml, so its failures and flakes reach no one.

hogli lint:test-owners                     # changed files vs origin/master
hogli lint:test-owners path/to/test_x.py   # explicit files
"""

from __future__ import annotations

from pathlib import Path

import click
from hogli.manifest import REPO_ROOT
from owners_yaml import OwnersResolver, first_team_owner
from owners_yaml.census import runner_for_path

from hogli_commands.change_detection import changed_files
from hogli_commands.preflight_checks import Outcome, Scope


def unowned_test_warnings(paths: list[str]) -> list[str]:
    tests = [path for path in paths if runner_for_path(path) and (REPO_ROOT / path).is_file()]
    resolver = OwnersResolver(REPO_ROOT)
    warnings = []
    for resolution in map(resolver.resolve, tests):
        if resolution.unowned_by_design or first_team_owner(resolution.owners):
            continue
        held_by = f"only by people ({', '.join(resolution.owners)})" if resolution.owners else "by no team"
        where = resolution.source or f"an owners.yaml at or above {Path(resolution.path).parent}/"
        warnings.append(
            f"{resolution.path}:1:1: warning: owned {held_by}. Name the team responsible for the behavior "
            f"it checks in {where}, so its failures and flakes reach that team."
        )
    return warnings


def check_test_owners(scope: Scope) -> Outcome:
    warnings = unowned_test_warnings(scope.files)
    if not warnings:
        return "pass", "every changed test file has a team owner"
    return "warning", f"{len(warnings)} changed test file(s) have no team owner · " + " · ".join(warnings[:3])


@click.command(name="lint:test-owners", help="Report changed test files that no team owns (warn-only).")
@click.argument("files", nargs=-1)
@click.option("--against", default=None, help="Diff against this base ref instead of the branch default.")
def cmd_lint_test_owners(files: tuple[str, ...], against: str | None) -> None:
    for warning in unowned_test_warnings(list(files) if files else changed_files(against)):
        click.echo(warning)
