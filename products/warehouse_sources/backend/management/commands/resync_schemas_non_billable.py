import time

from django.core.management.base import BaseCommand, CommandError

import structlog

from posthog.temporal.common.client import sync_connect

from products.warehouse_sources.backend.ad_hoc_sync import SchedulePauseError, WorkflowStartError, trigger_ad_hoc_sync
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

logger = structlog.get_logger(__name__)


def _read_ids(raw: str | None, path: str | None) -> list[str]:
    ids: list[str] = []
    if raw:
        ids.extend(part.strip() for part in raw.split(",") if part.strip())
    if path:
        with open(path) as handle:
            for line in handle:
                line = line.split("#", 1)[0].strip()
                if line:
                    ids.append(line)
    # Preserve caller order so an operator can stage small tables first, and drop repeats.
    seen: set[str] = set()
    unique: list[str] = []
    for schema_id in ids:
        if schema_id not in seen:
            seen.add(schema_id)
            unique.append(schema_id)
    return unique


class Command(BaseCommand):
    help = (
        "Trigger a non-billable sync for many schemas at once, mirroring the admin 'Trigger sync' action. "
        "A full_refresh run replaces its table wholesale, so plain (no --reset) is enough to replace bad data. "
        "Use --reset for incremental or xmin schemas, which otherwise only read forward from their cursor."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--schema-ids",
            type=str,
            default=None,
            help="Comma-separated schema ids.",
        )
        parser.add_argument(
            "--schema-ids-file",
            type=str,
            default=None,
            help="File with one schema id per line. Blank lines and '#' comments are ignored.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help=(
                "Stage reset_pipeline, which wipes the Delta table and cursor before re-reading. "
                "Needed for incremental and xmin schemas. Note a failed run then leaves the table empty."
            ),
        )
        parser.add_argument(
            "--sleep-seconds",
            type=float,
            default=30.0,
            help="Pause between triggers so a batch does not stampede the workers or the source. Default 30.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Only act on the first N schemas, for a cautious first batch.",
        )
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Actually trigger the syncs. Without this the command only lists what it would do.",
        )

    def handle(self, *args, **options):
        schema_ids = _read_ids(options["schema_ids"], options["schema_ids_file"])
        if not schema_ids:
            raise CommandError("Pass --schema-ids or --schema-ids-file.")

        reset = options["reset"]
        live_run = options["live_run"]
        sleep_seconds = options["sleep_seconds"]

        by_id = {
            str(schema.id): schema
            for schema in ExternalDataSchema.objects.select_related("source").filter(id__in=schema_ids)
        }
        missing = [schema_id for schema_id in schema_ids if schema_id not in by_id]
        if missing:
            self.stdout.write(self.style.WARNING(f"Not found, skipping {len(missing)}: {', '.join(missing)}"))

        schemas = [by_id[schema_id] for schema_id in schema_ids if schema_id in by_id]
        if options["limit"] is not None:
            schemas = schemas[: options["limit"]]

        if not schemas:
            raise CommandError("No matching schemas.")

        mode = "reset resync (re-pulls from source, wipes table first)" if reset else "sync (no reset)"
        self.stdout.write(f"{len(schemas)} schema(s), non-billable {mode}:\n")
        for schema in schemas:
            self.stdout.write(
                f"  schema={schema.id} team={schema.team_id} name={schema.name} "
                f"sync_type={schema.sync_type} source_type={schema.source.source_type} "
                f"should_sync={schema.should_sync}"
            )

        if not live_run:
            self.stdout.write(
                self.style.WARNING(f"\nDry run. Pass --live-run to trigger {len(schemas)} non-billable run(s).")
            )
            return

        try:
            client = sync_connect()
        except Exception as e:
            raise CommandError(f"Failed to connect to Temporal: {e}")

        succeeded = 0
        failed = 0

        for index, schema in enumerate(schemas):
            if index and sleep_seconds:
                time.sleep(sleep_seconds)
            if self._trigger(client, schema, reset=reset):
                succeeded += 1
            else:
                failed += 1

        self.stdout.write(self.style.SUCCESS(f"\nDone. Triggered: {succeeded}, Failed: {failed}"))

    def _trigger(self, client, schema: ExternalDataSchema, *, reset: bool) -> bool:
        try:
            trigger = trigger_ad_hoc_sync(
                client,
                schema,
                billable=False,
                reset_pipeline=reset,
                workflow_id_prefix="bulk-resync",
            )
        except SchedulePauseError:
            logger.exception("Failed to pause schedule, skipping", schema_id=str(schema.id))
            return False
        except WorkflowStartError:
            logger.exception("Failed to trigger sync", schema_id=str(schema.id), team_id=schema.team_id)
            return False

        self.stdout.write(f"  triggered {schema.id} workflow_id={trigger.workflow_id}")
        logger.info(
            "Triggered non-billable sync",
            schema_id=str(schema.id),
            team_id=schema.team_id,
            workflow_id=trigger.workflow_id,
            reset=reset,
        )
        return True
