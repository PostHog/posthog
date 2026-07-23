import pytest
from unittest.mock import patch

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
