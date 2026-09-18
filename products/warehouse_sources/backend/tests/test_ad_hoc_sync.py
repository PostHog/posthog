import pytest
from unittest.mock import MagicMock, patch

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from products.warehouse_sources.backend.ad_hoc_sync import WorkflowStartError, trigger_ad_hoc_sync
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

pytestmark = [pytest.mark.django_db]

MODULE = "products.warehouse_sources.backend.ad_hoc_sync"


@pytest.fixture
def schema():
    team = create_team(organization=create_organization("test org"))
    source = ExternalDataSource.objects.create(team=team, source_type="Postgres", job_inputs={})
    return ExternalDataSchema.objects.create(
        name="public.users",
        team=team,
        source=source,
        should_sync=True,
        sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        sync_type_config={},
    )


def test_failed_start_rolls_back_the_pause_it_took(schema):
    with (
        patch(f"{MODULE}.is_schedule_paused", return_value=False),
        patch(f"{MODULE}.pause_external_data_schedule"),
        patch(f"{MODULE}.unpause_external_data_schedule") as mock_unpause,
        patch(f"{MODULE}.start_external_data_workflow", side_effect=RuntimeError("temporal down")),
        pytest.raises(WorkflowStartError),
    ):
        trigger_ad_hoc_sync(MagicMock(), schema, billable=False, reset_pipeline=False, workflow_id_prefix="test")

    # The unpause marker is only read by a workflow that never began, so without the rollback the
    # schedule stays paused forever and the flag is orphaned in config.
    mock_unpause.assert_called_once_with(str(schema.id))
    schema.refresh_from_db()
    assert "admin_unpause_schedule_after_run" not in schema.sync_type_config


def test_a_schedule_already_paused_is_left_paused(schema):
    with (
        patch(f"{MODULE}.is_schedule_paused", return_value=True),
        patch(f"{MODULE}.pause_external_data_schedule") as mock_pause,
        patch(f"{MODULE}.start_external_data_workflow"),
    ):
        trigger = trigger_ad_hoc_sync(
            MagicMock(), schema, billable=False, reset_pipeline=False, workflow_id_prefix="test"
        )

    # Auto-unpausing would undo an operator's own manual pause.
    mock_pause.assert_not_called()
    assert trigger.schedule_paused_now is False
    schema.refresh_from_db()
    assert "admin_unpause_schedule_after_run" not in schema.sync_type_config


def test_failed_start_restores_staged_reset_state(schema):
    schema.sync_type_config = {"cdc_mode": "streaming", "cdc_last_log_position": "0/ABC"}
    schema.sync_type = ExternalDataSchema.SyncType.CDC
    schema.initial_sync_complete = True
    schema.save()

    with (
        patch(f"{MODULE}.is_schedule_paused", return_value=True),
        patch(f"{MODULE}.start_external_data_workflow", side_effect=RuntimeError("temporal down")),
        pytest.raises(WorkflowStartError),
    ):
        trigger_ad_hoc_sync(MagicMock(), schema, billable=False, reset_pipeline=True, workflow_id_prefix="test")

    # A run that never started must not change what the next scheduled run does. Leaving the reset
    # staged would wipe the Delta table, and the deleted CDC log position cannot be undone key by key.
    schema.refresh_from_db()
    assert "reset_pipeline" not in schema.sync_type_config
    assert schema.sync_type_config["cdc_mode"] == "streaming"
    assert schema.sync_type_config["cdc_last_log_position"] == "0/ABC"
    assert schema.initial_sync_complete is True
