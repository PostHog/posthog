"""Build activity summaries as of past dates and emit their vectors, for the offline ranking evaluation.

Each build reads only the inputs before its as-of date and writes only an embedding under the
`activity_summary_backfill` document type. `document_embeddings` drops rows three months after their
timestamp, so keep the as-of dates inside that window and copy the vectors out soon after a run.
"""

import json
import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from products.signals.backend.activity_summary.backfill import (
    BackfillOptions,
    TeamUser,
    backfill_jobs,
    plan_backfill,
    run_backfill,
)
from products.signals.backend.activity_summary.config import parse_limits
from products.signals.backend.activity_summary.logic import MIN_UNITS


def _date(value: str) -> datetime.date:
    return datetime.date.fromisoformat(value)


def as_of_dates(
    dates: list[datetime.date] | None,
    start: datetime.date | None,
    end: datetime.date | None,
    every_days: int,
) -> list[datetime.datetime]:
    """Midnight UTC of each date, from `--as-of` or from `--start` to `--end` inclusive."""
    if dates:
        days = sorted(set(dates))
    elif start is not None and end is not None and start <= end:
        step = datetime.timedelta(days=max(1, every_days))
        days = []
        day = start
        while day <= end:
            days.append(day)
            day += step
    else:
        raise CommandError("Give --as-of, or --start and --end with --start on or before --end.")
    return [datetime.datetime.combine(day, datetime.time(), tzinfo=datetime.UTC) for day in days]


class Command(BaseCommand):
    help = "Build activity summaries as of past dates and emit their embeddings. Writes no live summary state."

    def add_arguments(self, parser):
        parser.add_argument("--as-of", type=_date, nargs="+", help="As-of dates, YYYY-MM-DD. Each is midnight UTC.")
        parser.add_argument("--start", type=_date, help="The first as-of date, YYYY-MM-DD.")
        parser.add_argument("--end", type=_date, help="The last as-of date, YYYY-MM-DD.")
        parser.add_argument("--every-days", type=int, default=7, help="Days between as-of dates from --start.")
        parser.add_argument("--team-id", type=int)
        parser.add_argument("--user-id", type=int)
        parser.add_argument(
            "--inbox-users",
            action="store_true",
            help="Every (team, user) with an inbox report action before each as-of date.",
        )
        parser.add_argument("--exclude-inbox", action="store_true", help="Leave out inbox activity and views.")
        parser.add_argument("--min-units", type=int, default=MIN_UNITS)
        parser.add_argument(
            "--limits",
            type=json.loads,
            default=None,
            help="Render limits as JSON, with the clamps of the flag payload.",
        )
        parser.add_argument("--concurrency", type=int, default=4)
        parser.add_argument(
            "--max-cost-usd",
            type=float,
            required=True,
            help="Stop between batches when the cost of the run reaches this.",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Count the builds and their highest cost. No model call."
        )

    def handle(self, *args, **options):
        has_pair = options["team_id"] is not None and options["user_id"] is not None
        has_id = options["team_id"] is not None or options["user_id"] is not None
        if options["inbox_users"] == has_id or (has_id and not has_pair):
            raise CommandError("Give both --team-id and --user-id, or --inbox-users alone.")
        dates = as_of_dates(options["as_of"], options["start"], options["end"], options["every_days"])
        if dates[-1] > timezone.now():
            raise CommandError("An as-of date is in the future.")

        pair = None if options["inbox_users"] else TeamUser(team_id=options["team_id"], user_id=options["user_id"])
        jobs = backfill_jobs(dates, pair=pair)
        backfill_options = BackfillOptions(
            limits=parse_limits(options["limits"]),
            min_units=options["min_units"],
            exclude_inbox=options["exclude_inbox"],
        )
        if options["dry_run"]:
            plan = plan_backfill(jobs, backfill_options)
            self.stdout.write(
                f"dry run: {plan.jobs} jobs on {len(dates)} dates, {plan.builds} clear min units, "
                f"at most {plan.max_cost_usd:.2f} usd"
            )
            return

        result = run_backfill(
            jobs,
            backfill_options,
            concurrency=options["concurrency"],
            max_cost_usd=options["max_cost_usd"],
            on_batch=lambda done, cost: self.stdout.write(f"{done}/{len(jobs)} jobs, {cost:.4f} usd"),
        )
        stopped = ", stopped at the cost cap" if result.stopped_at_cost_cap else ""
        self.stdout.write(
            f"done: {result.attempted}/{result.jobs} jobs, statuses {json.dumps(result.statuses, sort_keys=True)}, "
            f"{result.cost_usd:.4f} usd{stopped}"
        )
