"""Click entrypoint for ``hogli test:quarantine``.

Wired into the hogli CLI via the ``click:`` manifest entry in ``hogli.yaml``.
Schema contract and selector grammar: ``hogli_commands.quarantine.core``.

    hogli test:quarantine add <id> --reason ... --owner ... [--issue ...] [--days 14] [--mode run|skip]
    hogli test:quarantine list [--json]
    hogli test:quarantine remove <id>
    hogli test:quarantine check [--grace-days 7]
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import click

from hogli_commands.quarantine import core


@click.group(name="test:quarantine", help="Manage .test_quarantine.json — flaky tests that must not block CI.")
@click.option(
    "--file",
    "file_path",
    type=click.Path(path_type=Path),
    default=None,
    hidden=True,
    help="Override the quarantine file location (testing only).",
)
@click.pass_context
def quarantine(ctx: click.Context, file_path: Path | None) -> None:
    ctx.obj = file_path or core.QUARANTINE_PATH


def _load_for_writing(path: Path) -> core.LoadResult:
    result = core.load(path)
    if result.errors:
        details = "\n".join(f"  {e}" for e in result.errors)
        raise click.ClickException(f"{path} has problems — fix it before rewriting:\n{details}")
    return result


@quarantine.command(name="add", help="Quarantine a test (replaces an existing entry with the same id).")
@click.argument("selector_id", metavar="ID")
@click.option("--reason", required=True, help="Why the test is quarantined.")
@click.option("--owner", required=True, help="Team or person responsible, e.g. @team-product-analytics.")
@click.option("--issue", default="", help="Tracking issue URL.")
@click.option(
    "--days",
    type=click.IntRange(1, core.MAX_QUARANTINE_DAYS),
    default=14,
    show_default=True,
    help="Days until the entry expires and the test blocks CI again.",
)
@click.option(
    "--mode",
    type=click.Choice(core.MODES),
    default="run",
    show_default=True,
    help="run = still executes but cannot fail CI (xfail); skip = not executed (hangs, state-polluters).",
)
@click.pass_obj
def add(path: Path, selector_id: str, reason: str, owner: str, issue: str, days: int, mode: str) -> None:
    selector_problem = core.validate_selector(selector_id, core.DEFAULT_RUNNER)
    if selector_problem is not None:
        raise click.ClickException(f"invalid selector '{selector_id}': {selector_problem}")
    result = _load_for_writing(path)
    today = core.today_utc()
    entry = core.Entry(
        id=selector_id,
        added=today,
        expires=today + timedelta(days=days),
        reason=reason,
        owner=owner,
        issue=issue,
        mode=mode,
    )
    entries = [e for e in result.entries if (e.id, e.runner) != (entry.id, entry.runner)] + [entry]
    path.write_text(core.render(entries, result.extras))
    click.echo(f"Quarantined '{selector_id}' (mode: {mode}) until {entry.expires.isoformat()}.")


@quarantine.command(name="remove", help="Remove a quarantine entry for every runner (succeeds even if absent).")
@click.argument("selector_id", metavar="ID")
@click.pass_obj
def remove(path: Path, selector_id: str) -> None:
    result = _load_for_writing(path)
    remaining = [e for e in result.entries if e.id != selector_id]
    if len(remaining) == len(result.entries):
        click.echo(f"No entry for '{selector_id}' — nothing to do.")
        return
    path.write_text(core.render(remaining, result.extras))
    click.echo(f"Removed '{selector_id}'.")


@quarantine.command(name="list", help="List quarantine entries and their status.")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON instead of a table.")
@click.pass_obj
def list_entries(path: Path, as_json: bool) -> None:
    result = core.load(path)
    for message in (*result.errors, *result.warnings):
        click.secho(message, fg="yellow", err=True)
    today = core.today_utc()
    if as_json:
        click.echo(core.render(result.entries, result.extras), nl=False)
        return
    if not result.entries:
        click.echo("No quarantined tests.")
        return
    for entry in sorted(result.entries, key=lambda e: e.id):
        days_left = (entry.expires - today).days
        status = f"expires in {days_left}d" if days_left >= 0 else f"EXPIRED {-days_left}d ago"
        click.echo(f"[{entry.runner}/{entry.mode}] {entry.id}  ({status}, {entry.owner}) {entry.reason}")


@quarantine.command(name="check", help="Lint the quarantine file; exits 1 on violations (used by CI).")
@click.option(
    "--grace-days",
    type=click.IntRange(min=0),
    default=core.DEFAULT_GRACE_DAYS,
    show_default=True,
    help="Days an expired entry may linger before this check fails.",
)
@click.pass_obj
def check(path: Path, grace_days: int) -> None:
    result = core.load(path)
    violations, warnings = core.check(result, today=core.today_utc(), grace_days=grace_days)
    for message in warnings:
        click.secho(f"warning: {message}", fg="yellow", err=True)
    for message in violations:
        click.secho(f"error: {message}", fg="red", err=True)
    if violations:
        raise SystemExit(1)
    click.echo(f"{path.name} OK ({len(result.entries)} entries).")


# Direct invocation needs only click + stdlib (used by test-quarantine.yml to
# avoid installing the full dev environment): python -m hogli_commands.quarantine.cli
if __name__ == "__main__":
    quarantine()
