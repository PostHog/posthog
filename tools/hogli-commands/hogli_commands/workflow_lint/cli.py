"""Click entrypoint for ``lint:workflows``.

Wired into the hogli CLI via the ``click:`` manifest entry in ``hogli.yaml``;
the lazy loader resolves this module only when the command actually runs.
"""

from __future__ import annotations

import os
from pathlib import Path

import click
from hogli.manifest import REPO_ROOT

from .check import Issue, WorkflowCheck
from .checks import CHECKS, get_check
from .model import Workflow, WorkflowParseError, read_workflows

_IN_GH_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"


def _gh_annotation(level: str, check_label: str, issue: Issue) -> None:
    if not _IN_GH_ACTIONS:
        return
    file_part = f" file={issue.file}" if issue.file else ""
    click.echo(f"::{level}{file_part} title=lint:workflows ({check_label})::{issue.render()}")


def _run_one(check: WorkflowCheck, workflows: list[Workflow]) -> int:
    """Run a single check, print results, return the issue count."""
    click.echo(f"  {check.id} ({check.label})...")
    result = check.run(workflows)
    for issue in result.issues:
        click.echo(f"    ✗ {issue.render()}")
        _gh_annotation("error", check.label, issue)
    if not result.issues:
        click.echo("    ✓ ok")
    return len(result.issues)


def _default_workflows_dir() -> Path:
    return REPO_ROOT / ".github" / "workflows"


@click.command(
    name="lint:workflows",
    help="Lint .github/workflows/** for repo conventions (timeouts, concurrency, dorny negation, semgrep coverage)",
)
@click.option(
    "--check",
    "check_id",
    metavar="ID",
    help="Run only the check with the given id (full id or WF### prefix, e.g. WF001 or WF001-job-timeouts)",
)
@click.option("--list", "list_checks", is_flag=True, help="List registered checks and exit")
@click.option(
    "--workflows-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    show_default=False,
    help="Workflows directory (defaults to <repo>/.github/workflows)",
)
def cmd_lint_workflows(check_id: str | None, list_checks: bool, workflows_dir: Path | None) -> None:
    if list_checks:
        for check in CHECKS:
            click.echo(f"{check.id}\t{check.label} — {check.description}")
        return

    if check_id is not None:
        target = get_check(check_id)
        if target is None:
            raise click.UsageError(f"Unknown check id '{check_id}'. Run with --list to see registered checks.")
        selected: list[WorkflowCheck] = [target]
    else:
        selected = list(CHECKS)

    resolved_dir = workflows_dir or _default_workflows_dir()
    try:
        workflows = list(read_workflows(resolved_dir))
    except WorkflowParseError as exc:
        click.echo(f"✗ {exc}", err=True)
        raise SystemExit(1) from exc

    click.echo(f"Linting {len(workflows)} workflow(s) with {len(selected)} check(s):\n")

    total_issues = 0
    failing_checks: list[WorkflowCheck] = []
    for check in selected:
        issues = _run_one(check, workflows)
        total_issues += issues
        if issues:
            failing_checks.append(check)

    click.echo("")
    if failing_checks:
        for check in failing_checks:
            if check.fix_hint:
                click.echo(f"Fix for {check.id}:\n{check.fix_hint}\n")
        click.echo(f"✗ {total_issues} issue(s) across {len(failing_checks)} check(s)")
        raise SystemExit(1)

    click.echo(f"✓ All {len(selected)} check(s) passed across {len(workflows)} workflow(s)")
