import json
import uuid
from datetime import timedelta
from typing import Any

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.hogql.database.database import get_data_warehouse_table_name

from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import LivenessHeartbeater as Heartbeater

from products.signals.backend.emission import get_signal_config
from products.signals.backend.emission.pipeline import run_signal_pipeline
from products.warehouse_sources.backend.facade.hooks import EmitSignalsActivityInputs
from products.warehouse_sources.backend.facade.models import ExternalDataSchema

logger = structlog.get_logger(__name__)


@activity.defn
async def emit_data_import_signals_activity(inputs: EmitSignalsActivityInputs) -> dict[str, Any]:
    """Emit signals for newly imported records from external data sources."""
    log = logger.bind(signals_type="data-import-signals", **inputs.properties_to_log)
    log.info(f"Starting signal emission for {inputs.source_type}/{inputs.schema_name}")
    config = get_signal_config(inputs.source_type, inputs.schema_name)
    # Check if we care about this source type + schema
    if config is None:
        log.warning(f"No signal emitter config registered for {inputs.source_type}/{inputs.schema_name}")
        return {"status": "skipped", "reason": "no_config_registered", "signals_emitted": 0}
    async with Heartbeater():
        # Fetch schema and team
        schema, team = await _fetch_schema_and_team(inputs.schema_id, inputs.team_id)
        if schema.table is None:
            log.warning(f"Schema {inputs.schema_id} has no table for emitting signals")
            return {"status": "skipped", "reason": "no_table", "signals_emitted": 0}
        # `DataWarehouseTable.name` is the storage form (e.g. `<prefix><source_type>_<schema>`),
        # but HogQL exposes warehouse tables under the keys produced by `get_data_warehouse_table_name`
        # (e.g. `github.issues` or `github.<prefix>.<schema>`). Querying the storage name fails to resolve.
        fetcher_context = {
            "table_name": get_data_warehouse_table_name(schema.source, schema.table.name),
            "last_synced_at": inputs.last_synced_at,
            "extra": inputs.properties_to_log,
        }
        records = await database_sync_to_async(config.record_fetcher, thread_sensitive=False)(
            team, config, fetcher_context
        )
        return await run_signal_pipeline(
            team=team,
            config=config,
            records=records,
            extra=inputs.properties_to_log,
        )


async def _fetch_schema_and_team(schema_id: uuid.UUID, team_id: int) -> tuple[ExternalDataSchema, Team]:
    schema = await ExternalDataSchema.objects.prefetch_related("table", "source").aget(id=schema_id, team_id=team_id)
    team = await Team.objects.aget(id=team_id)
    return schema, team


@workflow.defn(name="emit-data-import-signals")
class EmitDataImportSignalsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> EmitSignalsActivityInputs:
        loaded = json.loads(inputs[0])
        return EmitSignalsActivityInputs(**loaded)

    @workflow.run
    async def run(self, inputs: EmitSignalsActivityInputs) -> None:
        await workflow.execute_activity(
            emit_data_import_signals_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=60),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
