"""Fill `last_checked_at` on schemas whose last successful run predates the column.

Until a schema runs again, `last_checked_at` falls back to `last_synced_at`, which a run that found no new
rows leaves behind. Each run, including an empty one, completes a job, so the start of the newest completed
job is the value the sync itself now stores.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import OuterRef, Subquery

from products.warehouse_sources.backend.facade.models import ExternalDataJob, ExternalDataSchema
from products.warehouse_sources.backend.facade.types import ExternalDataJobStatus

BATCH_SIZE = 1000


def _latest_completed_job_start() -> Subquery:
    # Filtering on team and source lets Postgres use the team/source/status/created_at job index.
    return Subquery(
        ExternalDataJob.objects.filter(
            team_id=OuterRef("team_id"),
            pipeline_id=OuterRef("source_id"),
            schema_id=OuterRef("pk"),
            status=ExternalDataJobStatus.COMPLETED,
        )
        .order_by("-created_at")
        .values("created_at")[:1]
    )


class Command(BaseCommand):
    help = (
        "Set last_checked_at from the newest completed job on schemas that have none. "
        "Previews by default; pass --live-run to write."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Only fill schemas of this team.")
        parser.add_argument(
            "--live-run", action="store_true", help="Write the stamps. Without this the command only reports."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        schemas = ExternalDataSchema.objects.filter(deleted=False, last_checked_at__isnull=True)
        if options["team_id"] is not None:
            schemas = schemas.filter(team_id=options["team_id"])
        ids = list(schemas.order_by("pk").values_list("pk", flat=True))

        filled = 0
        for start in range(0, len(ids), BATCH_SIZE):
            # Re-checks the null, so a run that stamps the schema meanwhile keeps its newer value.
            batch = ExternalDataSchema.objects.filter(
                pk__in=ids[start : start + BATCH_SIZE], last_checked_at__isnull=True
            )
            filled += batch.annotate(latest=_latest_completed_job_start()).exclude(latest=None).count()
            if options["live_run"]:
                batch.update(last_checked_at=_latest_completed_job_start())

        verb = "Filled" if options["live_run"] else "Would fill"
        self.stdout.write(f"{verb} last_checked_at on {filled} schema(s).")
