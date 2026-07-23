"""Temporal trigger seams for the person-property feature, exposed through the warehouse_sources
facade so customer_analytics (which can't import data_warehouse) can start these from a DRF request.

Both open a Temporal client, so this module must stay off the ``django.setup()`` path — it's reached
only from the facade on a request, never from an AppConfig or model.
"""

from django.conf import settings

import structlog
from asgiref.sync import async_to_sync
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.client import async_connect, sync_connect
from posthog.temporal.common.schedule import trigger_schedule

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    PersonPropertyBackfillActivityInputs,
)

logger = structlog.get_logger(__name__)

BACKFILL_WORKFLOW_NAME = "backfill-warehouse-person-properties"

# The canonical warehouse schema reload/resync endpoints reject a manual sync with this message when
# the team's syncing is paused (monthly limit reached); reused so person-property "sync now" matches.
SYNC_PAUSED_MESSAGE = "Monthly sync limit reached. Please increase your billing limit to resume syncing."


class ExternalDataSchemaSyncPausedError(Exception):
    """Raised by ``trigger_schema_sync`` when the team's warehouse syncing is paused, so a manual
    person-property sync can't be used to run billable imports past the monthly limit."""


def trigger_schema_sync(*, team_id: int, schema_id: str) -> None:
    """Trigger the underlying warehouse schema's Temporal schedule — a real, billable sync. The normal
    incremental person-property child runs off it, so this doubles as person-property "sync now".
    Honors the team's sync pause the same way the canonical reload/resync endpoints do."""
    # Resolved lazily: the data_warehouse facade is PEP 562 lazy-loaded (heavy deps + an import cycle
    # with warehouse_sources), so a module-top ``from`` import would eagerly pull that chain in.
    from products.data_warehouse.backend.facade.api import is_any_external_data_schema_paused  # noqa: PLC0415

    log = logger.bind(team_id=team_id, schema_id=str(schema_id))
    if is_any_external_data_schema_paused(team_id):
        log.info("person-property sync-now rejected: team's warehouse syncing is paused")
        raise ExternalDataSchemaSyncPausedError(SYNC_PAUSED_MESSAGE)
    try:
        temporal = sync_connect()
        trigger_schedule(temporal, schedule_id=str(schema_id))
    except Exception as e:
        # Surfaces to the caller as a 500, but capture with context so a failing "sync now" is
        # diagnosable rather than an opaque Temporal client error in the request log.
        log.exception("Failed to trigger warehouse schema sync for person-property sync-now")
        capture_exception(e, {"team_id": team_id, "schema_id": str(schema_id)})
        raise
    log.info("Triggered warehouse schema sync for person-property sync-now")


def start_person_property_backfill(*, team_id: int, schema_id: str, trigger: str) -> bool:
    """Start the per-table backfill workflow. One workflow per ``{team, schema}`` (id-keyed), so
    concurrent triggers for the same table coalesce: returns False (does not raise) when one is
    already running. Also returns False when the schema no longer exists."""
    log = logger.bind(team_id=team_id, schema_id=str(schema_id), trigger=trigger)
    # exclude(deleted=True): a soft-deleted schema (its source removed) must not kick off a backfill.
    schema = (
        ExternalDataSchema.objects.exclude(deleted=True)
        .filter(id=schema_id, team_id=team_id)
        .select_related("source")
        .first()
    )
    if schema is None:
        log.warning("person-property backfill not started: schema no longer exists")
        return False
    inputs = PersonPropertyBackfillActivityInputs(
        team_id=team_id,
        schema_id=schema.id,
        source_type=schema.source.source_type,
        schema_name=schema.name,
        trigger=trigger,
    )
    workflow_id = f"{BACKFILL_WORKFLOW_NAME}-{team_id}-{schema_id}"
    return _start_backfill_workflow(inputs, workflow_id)


@async_to_sync
async def _start_backfill_workflow(inputs: PersonPropertyBackfillActivityInputs, workflow_id: str) -> bool:
    log = logger.bind(workflow_id=workflow_id, **inputs.properties_to_log)
    try:
        client: Client = await async_connect()
        # ALLOW_DUPLICATE so a manual re-backfill is allowed after a prior run closes; a run currently
        # in flight for the same id raises WorkflowAlreadyStartedError, which we swallow to coalesce.
        await client.start_workflow(
            BACKFILL_WORKFLOW_NAME,
            inputs,
            id=workflow_id,
            task_queue=settings.DATA_WAREHOUSE_METADATA_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )
        log.info("Started person-property backfill workflow")
        return True
    except WorkflowAlreadyStartedError:
        # Expected: a backfill for this table is already in flight, so this trigger coalesces into it.
        log.info("person-property backfill already running for schema, coalescing")
        return False
    except Exception as e:
        # A real failure to reach Temporal — capture it; the caller (facade) treats a raise as
        # "start failed" and the placeholder running row is reconciled to failed by the next run.
        log.exception("Failed to start person-property backfill workflow")
        capture_exception(e, {**inputs.properties_to_log, "workflow_id": workflow_id})
        raise
