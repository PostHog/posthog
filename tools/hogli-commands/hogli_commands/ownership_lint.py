"""Test-ownership nudge, scoped to changed files.

Every test file should resolve to a team through owners.yaml, so its failures, flakes and
reviews reach someone. The author who just changed an unowned test is the person best
placed to name that team, so this reports each one with the file to edit. It never fails
a build.

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

# A superset of runner_for_path, for preflight's trigger; the command narrows it to real test files.
TEST_FILE_SCOPE = ("*test_*.py", "*_test.py", "*.test.*", "*.spec.*")


def _nearest_ownership_file(path: str) -> str:
    for directory in Path(path).parents:
        candidate = directory / "owners.yaml"
        if (REPO_ROOT / candidate).is_file():
            return str(candidate)
    return "owners.yaml"


@click.command(name="lint:test-owners", help="Report changed test files that no team owns (warn-only).")
@click.argument("files", nargs=-1)
@click.option("--against", default=None, help="Diff against this base ref instead of the branch default.")
def cmd_lint_test_owners(files: tuple[str, ...], against: str | None) -> None:
    paths = list(files) if files else changed_files(against)
    tests = [path for path in paths if runner_for_path(path) and (REPO_ROOT / path).is_file()]
    resolver = OwnersResolver(REPO_ROOT)
    unowned = 0
    for path in tests:
        resolution = resolver.resolve(path)
        if resolution.unowned_by_design or first_team_owner(resolution.owners):
            continue
        unowned += 1
        held_by = (
            f"only by {', '.join(resolution.owners)}, a person rather than a team"
            if resolution.owners
            else "by no team"
        )
        ownership_file = resolution.source or _nearest_ownership_file(path)
        click.echo(
            f"{path}:1:1: warning: owned {held_by}. Name the team responsible for the behavior it checks "
            f"in {ownership_file} or a new owners.yaml in {Path(path).parent}/, so its failures and flakes reach that team."
        )
    click.echo(f"test-owners: {len(tests)} test file(s) checked, {unowned} without a team owner", err=True)
