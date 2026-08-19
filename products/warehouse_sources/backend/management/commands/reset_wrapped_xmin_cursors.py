from django.core.management.base import BaseCommand

import structlog

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = (
        "Clear the xmin cursor on schemas whose backfill ran against a wrapped cluster. "
        "Those backfills filtered on an [0, ceiling) window of raw 32-bit xids, which skips every "
        "tuple written in an earlier epoch, so the table is missing rows that no later incremental "
        "run can bring back. Clearing the cursor makes the next sync re-read the whole table and "
        "upsert by primary key."
    )

    def add_arguments(self, parser):
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

    def handle(self, *args, **options):
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
            # space and the backfill read everything.
            candidates = [schema for schema in schemas if (schema.xmin_num_wraparound or 0) > 0]

        if not candidates:
            self.stdout.write(self.style.WARNING("No xmin schemas found with a cursor captured past a wraparound."))
            return

        self.stdout.write(f"Found {len(candidates)} xmin schema(s) whose backfill may have skipped rows:\n")

        for schema in candidates:
            self.stdout.write(
                f"  schema={schema.id} team={schema.team_id} source={schema.source_id} "
                f"name={schema.name} epoch={schema.xmin_num_wraparound} cursor={schema.xmin_ceiling}"
            )

        if not live_run:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDry run: {len(candidates)} cursor(s) would be cleared. Pass --live-run to execute."
                )
            )
            return

        succeeded = 0
        failed = 0

        for schema in candidates:
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

        self.stdout.write(self.style.SUCCESS(f"\nDone. Cleared: {succeeded}, Failed: {failed}"))
