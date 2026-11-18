"""Click entrypoint for ``hogli test:quarantine``.

Wired into the hogli CLI via the ``click:`` manifest entry in ``hogli.yaml``.
Schema contract and selector grammar: ``hogli_commands.quarantine.core``.

    hogli test:quarantine add <id> --reason ... --owner ... [--issue ...] [--days 14] [--mode run|skip]
    hogli test:quarantine list [--json]
    hogli test:quarantine remove <id>
    hogli test:quarantine check
    hogli test:quarantine due --in-days 7 [--in-days 1] [--max-chars 3000]
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
    help="run = still executes with tolerated failures; skip = not executed (hangs, state-polluters).",
)
@click.option(
    "--runner",
    type=click.Choice(core.ADAPTED_RUNNERS),
    default=core.PYTEST_RUNNER,
    show_default=True,
    help="Which enforcement adapter interprets the selector.",
)
@click.pass_obj
def add(path: Path, selector_id: str, reason: str, owner: str, issue: str, days: int, mode: str, runner: str) -> None:
    selector_problem = core.validate_selector(selector_id, runner)
    if selector_problem is not None:
        raise click.ClickException(f"invalid selector '{selector_id}': {selector_problem}")
    result = _load_for_writing(path)
    today = core.today_utc()
    entry = core.Entry(
        id=selector_id,
        added=today,
        expires=today + timedelta(days=days),
        runner=runner,
        reason=reason,
        owner=owner,
        issue=issue,
        mode=mode,
    )
    entries = [e for e in result.entries if (e.id, e.runner) != (entry.id, entry.runner)] + [entry]
    path.write_text(core.render(entries, result.extras))
    click.echo(f"Quarantined '{selector_id}' ({runner}/{mode}) until {entry.expires.isoformat()}.")


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
@click.pass_obj
def check(path: Path) -> None:
    result = core.load(path)
    check_result = core.check(result, today=core.today_utc())
    for message in check_result.warnings:
        click.secho(f"warning: {message}", fg="yellow", err=True)
    for message in check_result.violations:
        click.secho(f"error: {message}", fg="red", err=True)
    if check_result.violations:
        raise SystemExit(1)
    click.echo(f"{path.name} OK ({len(result.entries)} entries).")


@quarantine.command(name="due", help="List entries that start failing `check` in exactly the given number of days.")
@click.option(
    "--in-days",
    type=click.IntRange(min=1),
    multiple=True,
    required=True,
    help="Days until `check` fails. Repeat to match several distances.",
)
@click.option(
    "--max-chars",
    type=click.IntRange(min=1),
    help="Keep the output within this many characters. The last line counts the entries left out.",
)
@click.pass_obj
def due(path: Path, in_days: tuple[int, ...], max_chars: int | None) -> None:
    result = core.load(path)
    for message in result.errors:
        click.secho(f"error: {message}", fg="red", err=True)
    if result.errors:
        raise SystemExit(1)

    today = core.today_utc()
    lines: list[str] = []
    for entry in core.entries_failing_check_in(result.entries, today, in_days):
        quarantine_state = "ends" if core.is_active(entry, today) else "ended"
        lines.append(
            f"• `{entry.id}` ({entry.owner}): quarantine {quarantine_state} {entry.expires.isoformat()}, "
            f"`check` fails on {core.check_failure_date(entry).isoformat()}"
        )
    for line in _fit_within(lines, max_chars):
        click.echo(line)


def _fit_within(lines: list[str], max_chars: int | None) -> list[str]:
    for shown in range(len(lines), -1, -1):
        hidden = len(lines) - shown
        fitted = lines[:shown] + ([f"• {hidden} more not shown"] if hidden else [])
        if max_chars is None or len("\n".join(fitted)) <= max_chars:
            return fitted
    return []


# Direct invocation needs only click + stdlib (used by test-quarantine.yml to
# avoid installing the full dev environment): python -m hogli_commands.quarantine.cli
if __name__ == "__main__":
    quarantine()
