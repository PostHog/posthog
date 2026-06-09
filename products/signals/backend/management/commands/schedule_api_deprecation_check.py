"""Create / update / delete the Temporal schedule for the API deprecation check (per team).

Dev-first: this is run on demand (not wired into the global startup bootstrap), so you can bring the
schedule up on a dev environment without affecting prod. Dispatch is off by default — a bare schedule
only surfaces signals in the inbox; pass --dispatch to also open draft PRs / file issues.

    # Daily inbox-only check for team 1 on dev
    python manage.py schedule_api_deprecation_check --team-id 1

    # Also dispatch (mechanical → draft PR), but keep migrations dry-run
    python manage.py schedule_api_deprecation_check --team-id 1 --dispatch

    # Remove the schedule
    python manage.py schedule_api_deprecation_check --team-id 1 --delete
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand

from asgiref.sync import async_to_sync

from posthog.temporal.common.client import async_connect

from products.signals.backend.temporal.api_deprecation import create_api_deprecation_schedule, schedule_id_for


class Command(BaseCommand):
    help = "Create/update/delete the per-team Temporal schedule for the API deprecation check."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--repository", default="posthog/posthog")
        parser.add_argument("--every-hours", type=int, default=24, help="Schedule interval in hours.")
        parser.add_argument("--dispatch", action="store_true", help="Also dispatch findings (draft PRs / issues).")
        parser.add_argument(
            "--real-migration-run",
            action="store_true",
            help="Allow the dispatched task to run the migration for real (default: dry-run only).",
        )
        parser.add_argument("--delete", action="store_true", help="Delete the schedule instead of creating it.")

    def handle(self, *args: Any, **options: Any) -> None:
        async_to_sync(self._run)(options)

    async def _run(self, options: dict[str, Any]) -> None:
        client = await async_connect()
        schedule_id = schedule_id_for(options["team_id"])

        if options["delete"]:
            await client.get_schedule_handle(schedule_id).delete()
            self.stdout.write(f"deleted schedule {schedule_id}")
            return

        created = await create_api_deprecation_schedule(
            client,
            team_id=options["team_id"],
            repository=options["repository"],
            every=timedelta(hours=options["every_hours"]),
            dispatch=options["dispatch"],
            dispatch_dry_run=not options["real_migration_run"],
        )
        self.stdout.write(
            f"scheduled {created} every {options['every_hours']}h (dispatch={'on' if options['dispatch'] else 'off'})"
        )
