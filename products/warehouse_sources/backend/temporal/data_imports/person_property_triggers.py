"""Temporal trigger seams for the person-property feature, exposed through the warehouse_sources
facade so customer_analytics (which can't import data_warehouse or data_modeling) can start these
from a DRF request.

A "sync now" means a fresh warehouse run of whatever the source binds to: an import for a schema, a
materialization for a view. Both produce staged rows the person-property child then consumes.

Every entry point opens a Temporal client, so this module must stay off the ``django.setup()`` path —
it's reached only from the facade on a request, never from an AppConfig or model.
"""

from uuid import UUID

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
    MATERIALIZED_VIEW_SOURCE_TYPE,
    PersonPropertyBackfillActivityInputs,
    WarehouseBinding,
)

logger = structlog.get_logger(__name__)

BACKFILL_WORKFLOW_NAME = "backfill-warehouse-person-properties"

# The canonical warehouse schema reload/resync endpoints reject a manual sync with this message when
# the team's syncing is paused (monthly limit reached); reused so person-property "sync now" matches.
SYNC_PAUSED_MESSAGE = "Monthly sync limit reached. Please increase your billing limit to resume syncing."

VIEW_MISSING_MESSAGE = "This view no longer exists."
VIEW_NOT_ON_V2_MESSAGE = (
    "This view still runs on the older data modeling schedule, which can't update warehouse properties. "
    "Use Backfill to update them from the last materialization."
)


class ExternalDataSchemaSyncPausedError(Exception):
    """Raised by ``trigger_schema_sync`` when the team's warehouse syncing is paused, so a manual
    person-property sync can't be used to run billable imports past the monthly limit."""


class SavedQueryNotFoundError(Exception):
    """Raised by ``trigger_saved_query_materialization`` when the view no longer resolves."""


class SavedQueryNotOnV2ScheduleError(Exception):
    """Raised by ``trigger_saved_query_materialization`` when the view is still on the older
    per-query data-modeling schedule, whose workflow never stages person-property rows."""


class WarehouseBindingMissingError(Exception):
    """Raised by ``start_person_property_backfill`` when the binding's warehouse object (schema or
    view) no longer resolves. A caller that created placeholder run rows before starting must fail
    them on this, so they don't sit 'running' until the stale-run sweep clears them hours later."""


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


def start_person_property_backfill(*, team_id: int, binding: WarehouseBinding, trigger: str) -> bool:
    """Start the per-table backfill workflow. One workflow per ``{team, binding}`` (id-keyed), so
    concurrent triggers for the same table coalesce: returns False (does not raise) when one is
    already running. Raises ``WarehouseBindingMissingError`` when the warehouse object no longer
    exists, kept distinct from the coalesced False so the caller can fail the run rows it created
    rather than reporting a coalesced run for a table that is gone."""
    log = logger.bind(team_id=team_id, binding_kind=binding.kind, binding_id=binding.id, trigger=trigger)
    inputs = _backfill_inputs(team_id, binding, trigger)
    if inputs is None:
        log.warning("person-property backfill not started: warehouse object no longer exists")
        raise WarehouseBindingMissingError
    workflow_id = f"{BACKFILL_WORKFLOW_NAME}-{team_id}-{binding.id}"
    return _start_backfill_workflow(inputs, workflow_id)


def _backfill_inputs(
    team_id: int, binding: WarehouseBinding, trigger: str
) -> PersonPropertyBackfillActivityInputs | None:
    """The workflow payload for a binding, or None when it no longer resolves.

    ``source_type``/``schema_name`` are the activity's log labels, so a view fills them with the kind
    and its own name rather than an import source's.
    """
    if binding.is_saved_query:
        # Resolved lazily: the data_modeling facade is PEP 562 lazy-loaded over HogQL/temporal-heavy
        # modules, so a module-top import would pull that chain onto this module's import path.
        from products.data_modeling.backend.facade.api import get_saved_query_summary  # noqa: PLC0415

        summary = get_saved_query_summary(team_id, binding.id)
        if summary is None:
            return None
        return PersonPropertyBackfillActivityInputs(
            team_id=team_id,
            schema_id=None,
            source_type=MATERIALIZED_VIEW_SOURCE_TYPE,
            schema_name=summary.name,
            trigger=trigger,
            saved_query_id=UUID(binding.id),
        )

    # exclude(deleted=True): a soft-deleted schema (its source removed) must not kick off a backfill.
    schema = (
        ExternalDataSchema.objects.exclude(deleted=True)
        .filter(id=binding.id, team_id=team_id)
        .select_related("source")
        .first()
    )
    if schema is None:
        return None
    return PersonPropertyBackfillActivityInputs(
        team_id=team_id,
        schema_id=schema.id,
        source_type=schema.source.source_type,
        schema_name=schema.name,
        trigger=trigger,
    )


def trigger_saved_query_materialization(*, team_id: int, saved_query_id: str) -> None:
    """Trigger a materialization of the view — person-property "sync now" for a view-backed source.

    The materialization stages its rows and forks the person-property sync child, mirroring how a
    schema's sync does. Only the v2 data-modeling workflow stages rows, so a view still on the older
    per-query schedule raises ``SavedQueryNotOnV2ScheduleError`` rather than starting a run whose rows
    would never reach person properties.
    """
    # Lazy for the same reason as _backfill_inputs above.
    from products.data_modeling.backend.facade import api as data_modeling  # noqa: PLC0415

    log = logger.bind(team_id=team_id, saved_query_id=str(saved_query_id))
    try:
        data_modeling.run_saved_query_materialization(team_id, saved_query_id)
    except data_modeling.SavedQueryNotFoundError as e:
        log.warning("person-property sync-now rejected: view no longer exists")
        raise SavedQueryNotFoundError(VIEW_MISSING_MESSAGE) from e
    except data_modeling.SavedQueryNotOnV2ScheduleError as e:
        log.info("person-property sync-now rejected: view is not on the v2 data modeling schedule")
        raise SavedQueryNotOnV2ScheduleError(VIEW_NOT_ON_V2_MESSAGE) from e
    except Exception as e:
        # Surfaces to the caller as a 500, but capture with context so a failing "sync now" is
        # diagnosable rather than an opaque Temporal client error in the request log.
        log.exception("Failed to materialize view for person-property sync-now")
        capture_exception(e, {"team_id": team_id, "saved_query_id": str(saved_query_id)})
        raise
    log.info("Triggered view materialization for person-property sync-now")


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
        log.info("person-property backfill already running for binding, coalescing")
        return False
    except Exception as e:
        # A real failure to reach Temporal — capture it; the caller (facade) treats a raise as
        # "start failed" and the placeholder running row is reconciled to failed by the next run.
        log.exception("Failed to start person-property backfill workflow")
        capture_exception(e, {**inputs.properties_to_log, "workflow_id": workflow_id})
        raise
