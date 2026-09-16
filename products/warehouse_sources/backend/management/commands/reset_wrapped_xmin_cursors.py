from typing import Any

from django.core.management.base import BaseCommand, CommandParser

import structlog

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = (
        "Clear the xmin cursor on schemas whose backfill may have run against a wrapped cluster. "
        "Those backfills filtered on an [0, ceiling) window of raw 32-bit xids, which skips tuples "
        "written in an earlier epoch, so the table can be missing rows that no later incremental "
        "run brings back. Clearing the cursor makes the next sync re-read the whole table and "
        "upsert by primary key."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Actually clear the cursors. Without this flag the command only lists matches (dry-run).",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            default=None,
            help="Only consider schemas belonging to this team",
        )
        parser.add_argument(
            "--schema-id",
            action="append",
            default=None,
            help="Target these schema ids explicitly, skipping the wraparound filter. Repeatable.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        live_run = options["live_run"]
        team_id = options["team_id"]
        schema_ids = options["schema_id"]

        schemas = ExternalDataSchema.objects.select_related("source").filter(
            sync_type=ExternalDataSchema.SyncType.XMIN,
            deleted=False,
        )

        if team_id is not None:
            schemas = schemas.filter(team_id=team_id)

        if schema_ids:
            # An operator naming schemas has already established they need re-seeding, so don't
            # second-guess it with the epoch heuristic.
            candidates = list(schemas.filter(id__in=schema_ids))
        else:
            # Epoch 0 clusters never wrapped, so their [0, ceiling) window covered the whole xid
            # space and the backfill read everything. Past a wraparound the window is a candidate
            # rather than proof, since a large remainder can still have caught every tuple.
            candidates = [schema for schema in schemas if (schema.xmin_num_wraparound or 0) > 0]

        if not candidates:
            self.stdout.write(self.style.WARNING("No xmin schemas found with a cursor captured past a wraparound."))
            return

        # A sync that is already streaming persists the ceiling it captured at startup when it
        # completes, which would restore the cursor this command just cleared.
        running = set(
            ExternalDataJob.objects.filter(
                schema_id__in=[schema.id for schema in candidates],
                status=ExternalDataJob.Status.RUNNING,
            ).values_list("schema_id", flat=True)
        )

        self.stdout.write(f"Found {len(candidates)} xmin schema(s) whose backfill may have skipped rows:\n")

        for schema in candidates:
            # Share of the 32-bit xid space the backfill window covered. The lower it is, the more
            # of the table the backfill could have skipped.
            window_covered = (schema.xmin_last_value or 0) / 0x100000000
            self.stdout.write(
                f"  schema={schema.id} team={schema.team_id} source={schema.source_id} "
                f"name={schema.name} epoch={schema.xmin_num_wraparound} cursor={schema.xmin_ceiling} "
                f"window_covered={window_covered:.1%}"
                + (" [sync running, will be skipped]" if schema.id in running else "")
            )

        if not live_run:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDry run: {len(candidates) - len(running)} cursor(s) would be cleared. Pass --live-run to execute."
                )
            )
            return

        succeeded = 0
        failed = 0
        skipped = 0

        for schema in candidates:
            if schema.id in running:
                skipped += 1
                self.stdout.write(
                    self.style.WARNING(f"Skipped schema={schema.id}: a sync is running. Re-run once it finishes.")
                )
                continue
            try:
                schema.clear_xmin_state()
                succeeded += 1
                logger.info(
                    "Cleared xmin cursor for re-backfill",
                    schema_id=str(schema.id),
                    team_id=schema.team_id,
                )
            except Exception:
                failed += 1
                logger.exception("Failed to clear xmin cursor", schema_id=str(schema.id), team_id=schema.team_id)

        self.stdout.write(self.style.SUCCESS(f"\nDone. Cleared: {succeeded}, Skipped: {skipped}, Failed: {failed}"))
