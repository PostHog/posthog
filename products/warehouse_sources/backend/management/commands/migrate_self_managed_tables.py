import time
from collections import Counter
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.temporal.common.client import sync_connect

from products.warehouse_sources.backend.self_managed_migration import (
    DEFAULT_ABANDON_REASON,
    MigrationOptions,
    abandon_tables,
    describe_status,
    evaluate_tables,
    migrate_self_managed_tables,
)


def _split_ids(raw: str | None) -> list[str]:
    seen: dict[str, None] = {}
    for part in (raw or "").split(","):
        if part.strip():
            seen.setdefault(part.strip(), None)
    return list(seen)


class Command(BaseCommand):
    help = (
        "Copy self-managed warehouse tables into object storage sources with one non-billable sync each. "
        "Each table keeps its id and name, and its schema stays turned off, so nothing is billed until the "
        "user turns syncing on. Runs only for teams with the object storage sources feature flag. "
        "Without --live-run the command only reports what it would do."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Only act on this team's tables.")
        parser.add_argument("--table-ids", type=str, default=None, help="Comma-separated warehouse table ids.")
        parser.add_argument(
            "--limit", type=int, default=None, help="Start at most N copies in this run, for a cautious first batch."
        )
        parser.add_argument(
            "--sleep-seconds",
            type=float,
            default=30.0,
            help="Pause between two starts so a batch does not reach the workers at once. Default 30.",
        )
        parser.add_argument(
            "--status", action="store_true", help="Report each table's migration state and change nothing."
        )
        parser.add_argument(
            "--retry-failed",
            action="store_true",
            help="Start the copy again for failed tables, and for copies that started but never ran.",
        )
        parser.add_argument(
            "--abandon",
            type=str,
            default=None,
            help="Comma-separated table ids to leave self-managed. Removes what the migration created for them.",
        )
        parser.add_argument(
            "--abandon-reason",
            type=str,
            default=DEFAULT_ABANDON_REASON,
            help="The reason recorded on each abandoned table.",
        )
        parser.add_argument(
            "--live-run", action="store_true", help="Act. Without this the command only reports what it would do."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["sleep_seconds"] < 0:
            raise CommandError("--sleep-seconds cannot be negative.")
        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be at least 1.")
        modes = [bool(options["status"]), options["abandon"] is not None]
        if sum(modes) > 1:
            raise CommandError("Pass only one of --status and --abandon.")

        team_id: int | None = options["team_id"]
        table_ids = _split_ids(options["table_ids"])
        live_run: bool = options["live_run"]

        if options["status"]:
            self._report_status(team_id, table_ids)
        elif options["abandon"] is not None:
            self._abandon(_split_ids(options["abandon"]), options["abandon_reason"], team_id, live_run)
        else:
            self._migrate(team_id, table_ids, live_run, options)

    def _report_status(self, team_id: int | None, table_ids: list[str]) -> None:
        statuses = evaluate_tables(team_id=team_id, table_ids=table_ids)
        for status in statuses:
            self.stdout.write(describe_status(status))
        counts = Counter(str(status.state) for status in statuses)
        self.stdout.write(f"\n{len(statuses)} table(s): " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())))

    def _abandon(self, table_ids: list[str], reason: str, team_id: int | None, live_run: bool) -> None:
        if not table_ids:
            raise CommandError("--abandon needs at least one table id.")
        for outcome in abandon_tables(table_ids, reason=reason, team_id=team_id, live_run=live_run):
            detail = f" ({outcome.reason})" if outcome.reason else ""
            self.stdout.write(f"table={outcome.table_id} {outcome.action}{detail}")
        if not live_run:
            self.stdout.write(self.style.WARNING("\nDry run. Pass --live-run to abandon these tables."))

    def _migrate(self, team_id: int | None, table_ids: list[str], live_run: bool, options: dict[str, Any]) -> None:
        client = None
        if live_run:
            try:
                client = sync_connect()
            except Exception as e:
                raise CommandError(f"Failed to connect to Temporal: {e}")
        sleep_seconds: float = options["sleep_seconds"]
        outcomes = migrate_self_managed_tables(
            MigrationOptions(
                team_id=team_id,
                table_ids=tuple(table_ids),
                live_run=live_run,
                retry_failed=options["retry_failed"],
                limit=options["limit"],
            ),
            client=client,
            pause=(lambda: time.sleep(sleep_seconds)) if sleep_seconds else None,
        )
        for outcome in outcomes:
            detail = f" workflow_id={outcome.workflow_id}" if outcome.workflow_id else ""
            error = f" error={outcome.error}" if outcome.error else ""
            self.stdout.write(f"{describe_status(outcome.status)} action={outcome.action}{detail}{error}")
        actions = Counter(outcome.action for outcome in outcomes)
        self.stdout.write(f"\n{len(outcomes)} table(s): " + ", ".join(f"{n} {a}" for a, n in sorted(actions.items())))
        if not live_run:
            self.stdout.write(self.style.WARNING("\nDry run. Pass --live-run to start the copies."))
