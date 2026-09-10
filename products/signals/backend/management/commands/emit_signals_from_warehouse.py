import uuid
import asyncio
import datetime as dt

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from temporalio.common import RetryPolicy

from posthog.models import Team
from posthog.temporal.common.client import async_connect

from products.signals.backend.emission import get_signal_config
from products.signals.backend.emission.emit_signals import EmitDataImportSignalsWorkflow, EmitSignalsActivityInputs
from products.warehouse_sources.backend.facade.models import ExternalDataSchema

# Maps the CLI --type arg to (ExternalDataSourceType value, registered schema name).
# Conversations is excluded — it's an internal Postgres source, not warehouse-backed.
_SOURCES = {
    "github": ("Github", "issues"),
    "linear": ("Linear", "issues"),
    "pganalyze": ("PgAnalyze", "issues"),
    "zendesk": ("Zendesk", "tickets"),
}


async def _start_workflow(
    team_id: int,
    schema_id: uuid.UUID,
    source_id: uuid.UUID,
    source_type: str,
    schema_name: str,
    last_synced_at: str | None,
) -> str:
    client = await async_connect()
    job_id = str(uuid.uuid4())
    workflow_id = f"emit-data-import-signals-{job_id}"
    await client.start_workflow(
        EmitDataImportSignalsWorkflow.run,
        EmitSignalsActivityInputs(
            team_id=team_id,
            schema_id=schema_id,
            source_id=source_id,
            job_id=job_id,
            source_type=source_type,
            schema_name=schema_name,
            last_synced_at=last_synced_at,
        ),
        id=workflow_id,
        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        execution_timeout=dt.timedelta(hours=2),
        retry_policy=RetryPolicy(maximum_attempts=1),
    )
    return workflow_id


class Command(BaseCommand):
    help = (
        "Re-emit signals for a team from rows already synced into the data warehouse, "
        "without re-running the upstream sync. Fires the same EmitDataImportSignalsWorkflow "
        "the data-import job normally chains as a child after a sync completes. "
        "Use this (rather than emit_signals_from_fixture) when you want to exercise the "
        "warehouse fetcher + workflow path against real synced rows — fixtures bypass "
        "both the fetcher and the workflow, so they don't catch HogQL or table-shape regressions."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="Team to emit for")
        parser.add_argument(
            "--type",
            choices=sorted(_SOURCES.keys()),
            required=True,
            help=f"Friendly source name. One of: {', '.join(sorted(_SOURCES.keys()))}",
        )
        parser.add_argument(
            "--last-synced-at",
            type=str,
            default=None,
            help=(
                "Optional ISO timestamp (e.g. 2026-01-01T00:00:00+00:00). Records with "
                "partition_field > this value are emitted. Default: None — falls back to "
                "the registered config's first_sync_lookback_days window, capped at "
                "config.max_records. Pass an old timestamp like 1970-01-01T00:00:00+00:00 "
                "to force a full re-emit of every row in the warehouse table."
            ),
        )

    def handle(self, *args, **options):
        team_id = options["team_id"]
        source_type, schema_name = _SOURCES[options["type"]]
        last_synced_at = options["last_synced_at"]
        if last_synced_at is not None:
            try:
                dt.datetime.fromisoformat(last_synced_at)
            except ValueError as err:
                raise CommandError(
                    f"--last-synced-at must be an ISO 8601 timestamp (got {last_synced_at!r}): {err}"
                ) from err

        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist as err:
            raise CommandError(f"Team {team_id} not found") from err

        if get_signal_config(source_type, schema_name) is None:
            raise CommandError(
                f"No signal emitter registered for {source_type}/{schema_name} — "
                f"check products/signals/backend/emission/registry.py"
            )

        schema = (
            ExternalDataSchema.objects.select_related("source", "table")
            .filter(team_id=team_id, source__source_type=source_type, name=schema_name)
            .exclude(source__deleted=True)
            .first()
        )
        if schema is None:
            raise CommandError(
                f"No ExternalDataSchema for team {team_id} with source_type={source_type} "
                f"schema={schema_name}. Connect the source and run a sync first."
            )
        if schema.table is None:
            raise CommandError(
                f"Schema {schema.id} has no warehouse table yet — wait for the sync to finish before re-emitting."
            )

        workflow_id = asyncio.run(
            _start_workflow(
                team_id=team_id,
                schema_id=schema.id,
                source_id=schema.source.id,
                source_type=source_type,
                schema_name=schema_name,
                last_synced_at=last_synced_at,
            )
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Started EmitDataImportSignalsWorkflow for {source_type}/{schema_name} "
                f"team={team_id} ({team.name}) [workflow_id={workflow_id}]"
            )
        )
        self.stdout.write(
            f"Watch progress: ./manage.py signal_pipeline_status --team-id {team_id} --wait --poll-interval 10 --json"
        )
