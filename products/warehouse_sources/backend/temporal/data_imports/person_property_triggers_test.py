import dataclasses

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from products.warehouse_sources.backend.temporal.data_imports import person_property_triggers
from products.warehouse_sources.backend.temporal.data_imports.person_property_triggers import (
    ExternalDataSchemaSyncPausedError,
    trigger_schema_sync,
)

# is_any_external_data_schema_paused is imported lazily inside trigger_schema_sync from the
# data_warehouse facade, so patch it at that (lazy) resolution point rather than on this module.
_PAUSE_CHECK = "products.data_warehouse.backend.facade.api.is_any_external_data_schema_paused"


@patch.object(person_property_triggers, "sync_connect")
@patch(_PAUSE_CHECK, return_value=True)
def test_trigger_schema_sync_blocked_when_paused(_paused, mock_connect):
    with pytest.raises(ExternalDataSchemaSyncPausedError):
        trigger_schema_sync(team_id=1, schema_id="abc")
    # Never opens a Temporal client / triggers the schedule when syncing is paused.
    mock_connect.assert_not_called()


@patch.object(person_property_triggers, "trigger_schedule")
@patch.object(person_property_triggers, "sync_connect")
@patch(_PAUSE_CHECK, return_value=False)
def test_trigger_schema_sync_triggers_when_not_paused(_paused, _connect, mock_trigger_schedule):
    trigger_schema_sync(team_id=1, schema_id="abc")
    mock_trigger_schedule.assert_called_once()


def test_backfill_request_uses_signal_with_start_for_the_binding_workflow():
    inputs = person_property_triggers.PersonPropertyBackfillActivityInputs(
        team_id=1,
        schema_id=None,
        saved_query_id=None,
        source_type="Stripe",
        schema_name="users",
        trigger="backfill",
    )
    client = MagicMock()
    client.start_workflow = AsyncMock()

    with patch.object(person_property_triggers, "async_connect", AsyncMock(return_value=client)):
        person_property_triggers._start_backfill_workflow(inputs, "backfill-1-schema")

    client.start_workflow.assert_awaited_once_with(
        person_property_triggers.BACKFILL_WORKFLOW_NAME,
        dataclasses.replace(inputs, skip_initial_run=True),
        id="backfill-1-schema",
        task_queue=person_property_triggers.settings.DATA_WAREHOUSE_METADATA_TASK_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        start_signal=person_property_triggers.BACKFILL_SIGNAL_NAME,
        start_signal_args=[inputs],
    )
