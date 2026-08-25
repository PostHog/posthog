"""Create (or update) the Temporal Schedule that runs the daily ICP re-enrichment sweep.

Idempotent: safe to re-run on deploy or by hand. The schedule only starts the workflow; all
eligibility guards (kill switch, region, cap) are re-checked inside the sweep's selection
activity on every run, so pausing the sweep is a settings change, not a Temporal operation.
"""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from temporalio.client import Schedule, ScheduleActionStartWorkflow, ScheduleOverlapPolicy, SchedulePolicy, ScheduleSpec

from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.schedule import create_schedule, schedule_exists, update_schedule
from posthog.utils import get_instance_region

from products.growth.backend.temporal.signup_enrichment.reenrichment import IcpReenrichmentSweepInputs

SCHEDULE_ID = "icp-reenrichment-sweep-daily"

# 07:40 UTC daily: off the hour to avoid the shared-queue thundering herd, and adjacent to
# the existing 7am growth/billing batch window so operators find related runs together.
CRON = "40 7 * * *"


class Command(BaseCommand):
    help = "Create or update the daily ICP re-enrichment sweep schedule (idempotent)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--trigger-now", action="store_true", help="Also run the sweep immediately")

    def handle(self, *args: Any, **options: Any) -> None:
        if get_instance_region() not in ("US", "EU"):
            self.stdout.write("Cloud-only; nothing to do in this region")
            return

        schedule = Schedule(
            action=ScheduleActionStartWorkflow(
                "icp-reenrichment-sweep",
                IcpReenrichmentSweepInputs(),
                id=SCHEDULE_ID,
                task_queue=settings.SIGNUP_ENRICHMENT_TASK_QUEUE,
            ),
            spec=ScheduleSpec(cron_expressions=[CRON]),
            # A sweep that overruns its slot (huge backlog) must not stack a second run on top.
            policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
        )

        client = sync_connect()
        if schedule_exists(client, SCHEDULE_ID):
            update_schedule(client, SCHEDULE_ID, schedule)
            outcome = "updated"
        else:
            create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=options["trigger_now"])
            outcome = "created"
        self.stdout.write(self.style.SUCCESS(f"{outcome} schedule {SCHEDULE_ID} ({CRON} UTC)"))
