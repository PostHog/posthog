import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import structlog
from asgiref.sync import async_to_sync
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy

from posthog.temporal.common.client import sync_connect
from posthog.temporal.utils import ExternalDataWorkflowInputs

from products.data_warehouse.backend.facade.api import pause_external_data_schedule, unpause_external_data_schedule
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

logger = structlog.get_logger(__name__)


@async_to_sync
async def _start_external_data_workflow(client: Client, workflow_id: str, inputs: ExternalDataWorkflowInputs) -> None:
    await client.start_workflow(
        "external-data-job",
        inputs,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
    )


@async_to_sync
async def _is_schedule_paused(client: Client, schedule_id: str) -> bool:
    handle = client.get_schedule_handle(schedule_id)
    try:
        desc = await handle.describe()
    except Exception:
        return False
    return bool(desc.schedule.state.paused)


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

    def _trigger(self, client: Client, schema: ExternalDataSchema, *, reset: bool) -> bool:
        # Mirrors `ExternalDataSchemaAdmin.trigger_sync_view`: pause the schedule so the scheduled
        # workflow cannot race this ad-hoc one, stage the reset, then start the workflow directly.
        # The schedule's stored input is always billable, which is why this bypasses it.
        was_paused = _is_schedule_paused(client, str(schema.id))
        admin_paused_now = False
        if not was_paused:
            try:
                pause_external_data_schedule(str(schema.id))
                admin_paused_now = True
            except Exception:
                logger.exception("Failed to pause schedule, skipping", schema_id=str(schema.id))
                return False

        update_fields: list[str] = []
        if reset:
            schema.sync_type_config["reset_pipeline"] = True
            update_fields.append("sync_type_config")
            # A streaming CDC schema no-ops a normal reset, so flip it back to snapshot for a full
            # re-snapshot. On completion `set_initial_sync_complete` returns it to streaming.
            if schema.is_cdc and schema.cdc_mode == "streaming":
                schema.sync_type_config["cdc_mode"] = "snapshot"
                schema.sync_type_config.pop("cdc_last_log_position", None)
                schema.sync_type_config.pop("cdc_deferred_runs", None)
                schema.initial_sync_complete = False
                update_fields.append("initial_sync_complete")
        if admin_paused_now:
            schema.sync_type_config["admin_unpause_schedule_after_run"] = True
            if "sync_type_config" not in update_fields:
                update_fields.append("sync_type_config")
        if update_fields:
            schema.save(update_fields=update_fields)

        inputs = ExternalDataWorkflowInputs(
            team_id=schema.team_id,
            external_data_source_id=schema.source.id,
            external_data_schema_id=schema.id,
            billable=False,
            reset_pipeline=None,
        )
        workflow_id = f"{schema.id}-bulk-resync-{int(time.time())}"
        try:
            _start_external_data_workflow(client, workflow_id, inputs)
        except Exception:
            # Without this rollback a failed start leaves the schedule paused forever, because the
            # unpause marker is only read by a workflow that never began.
            if admin_paused_now:
                try:
                    unpause_external_data_schedule(str(schema.id))
                    schema.sync_type_config.pop("admin_unpause_schedule_after_run", None)
                    schema.save(update_fields=["sync_type_config"])
                except Exception:
                    logger.exception("Failed to roll back pause", schema_id=str(schema.id))
            logger.exception("Failed to trigger sync", schema_id=str(schema.id), team_id=schema.team_id)
            return False

        self.stdout.write(f"  triggered {schema.id} workflow_id={workflow_id}")
        logger.info(
            "Triggered non-billable sync",
            schema_id=str(schema.id),
            team_id=schema.team_id,
            workflow_id=workflow_id,
            reset=reset,
        )
        return True
