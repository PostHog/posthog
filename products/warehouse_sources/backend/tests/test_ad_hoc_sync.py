import pytest
from unittest.mock import MagicMock, patch

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from products.warehouse_sources.backend.ad_hoc_sync import (
    SyncStillRunningError,
    WorkflowStartError,
    resume_schedule_after_ad_hoc_run,
    trigger_ad_hoc_sync,
)
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

pytestmark = [pytest.mark.django_db]

MODULE = "products.warehouse_sources.backend.ad_hoc_sync"


@pytest.fixture
def no_sync_to_wait_for():
    """No sync of the table can hand over, so a reset is staged here rather than left to capture.

    The real check reads the load queue, which lives in the warehouse-sources database these tests
    do not create — it would raise, and a failed check hands the reset over.
    """
    with patch(f"{MODULE}.cancel_sync_that_could_hand_over", return_value=False) as stub:
        yield stub


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


@pytest.mark.parametrize(
    "marker,unpause_error,expect_resume",
    [
        ("wf-ad-hoc", None, True),
        (True, None, True),
        (None, None, False),
        ("wf-other-run", None, False),
        # The marker is the only record of the pause, so it stays until the unpause succeeds.
        ("wf-ad-hoc", RuntimeError("temporal down"), True),
    ],
    ids=["own_run", "legacy_marker", "no_marker", "other_run", "unpause_fails"],
)
def test_resume_schedule_after_ad_hoc_run(schema, marker, unpause_error, expect_resume):
    schema.sync_type_config = {
        "reset_pipeline": True,
        **({"admin_unpause_schedule_after_run": marker} if marker else {}),
    }
    schema.save()
    job = ExternalDataJob.objects.create(
        team_id=schema.team_id, pipeline=schema.source, schema=schema, status="Completed", workflow_id="wf-ad-hoc"
    )

    with patch(f"{MODULE}.a_unpause_external_data_schedule", side_effect=unpause_error) as mock_unpause:
        if unpause_error:
            with pytest.raises(RuntimeError):
                resume_schedule_after_ad_hoc_run(schema.id, schema.team_id, job.id)
        else:
            assert resume_schedule_after_ad_hoc_run(schema.id, schema.team_id, job.id) is expect_resume

    if expect_resume:
        mock_unpause.assert_called_once_with(str(schema.id))
    else:
        mock_unpause.assert_not_called()
    schema.refresh_from_db()
    marker_kept = bool(marker) and (not expect_resume or unpause_error is not None)
    assert ("admin_unpause_schedule_after_run" in schema.sync_type_config) is marker_kept
    assert schema.sync_type_config["reset_pipeline"] is True


@pytest.mark.parametrize(
    "previous_marker",
    [
        # Auto-unpausing would undo an operator's own manual pause.
        None,
        # A failed ad-hoc run left the pause, and only the retry can still complete to resume it.
        "wf-failed-ad-hoc",
    ],
    ids=["paused_by_hand", "paused_by_earlier_ad_hoc_run"],
)
def test_a_schedule_already_paused_is_left_paused(schema, previous_marker):
    if previous_marker:
        schema.sync_type_config = {"admin_unpause_schedule_after_run": previous_marker}
        schema.save()

    with (
        patch(f"{MODULE}.is_schedule_paused", return_value=True),
        patch(f"{MODULE}.pause_external_data_schedule") as mock_pause,
        patch(f"{MODULE}.start_external_data_workflow"),
    ):
        trigger = trigger_ad_hoc_sync(
            MagicMock(), schema, billable=False, reset_pipeline=False, workflow_id_prefix="test"
        )

    mock_pause.assert_not_called()
    assert trigger.schedule_paused_now is False
    schema.refresh_from_db()
    expected_marker = trigger.workflow_id if previous_marker else None
    assert schema.sync_type_config.get("admin_unpause_schedule_after_run") == expected_marker


def test_failed_start_restores_staged_reset_state(schema, no_sync_to_wait_for):
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


def test_a_reset_of_a_streaming_cdc_table_keeps_its_buffer_and_concurrent_keys(schema, no_sync_to_wait_for):
    schema.sync_type = ExternalDataSchema.SyncType.CDC
    schema.sync_type_config = {"cdc_mode": "streaming", "cdc_table_mode": "consolidated"}
    schema.initial_sync_complete = True
    schema.save()
    # Capture writes the row after this copy was loaded; the reset must not revert it.
    update_sync_type_config_keys(schema.id, schema.team_id, updates={"cdc_last_run_at": "2026-09-24T00:00:00+00:00"})

    with (
        patch(f"{MODULE}.is_schedule_paused", return_value=True),
        patch(f"{MODULE}.start_external_data_workflow"),
    ):
        trigger_ad_hoc_sync(MagicMock(), schema, billable=False, reset_pipeline=True, workflow_id_prefix="test")

    schema.refresh_from_db()
    assert schema.sync_type_config["cdc_mode"] == "snapshot"
    # Unmarked, the next capture run empties the buffer and can delete changes the snapshot never saw.
    assert schema.sync_type_config.get("cdc_snapshot_lane") == "buffer"
    assert schema.sync_type_config["cdc_last_run_at"] == "2026-09-24T00:00:00+00:00"


def test_a_cdc_reset_is_refused_while_the_tables_sync_can_still_hand_over(schema):
    schema.sync_type = ExternalDataSchema.SyncType.CDC
    schema.sync_type_config = {"cdc_mode": "streaming"}
    schema.save()

    with (
        patch(f"{MODULE}.cancel_sync_that_could_hand_over", return_value=True),
        patch(f"{MODULE}.pause_external_data_schedule") as pause,
        patch(f"{MODULE}.start_external_data_workflow") as start,
        pytest.raises(SyncStillRunningError),
    ):
        trigger_ad_hoc_sync(MagicMock(), schema, billable=False, reset_pipeline=True, workflow_id_prefix="test")

    pause.assert_not_called()
    start.assert_not_called()
    schema.refresh_from_db()
    assert schema.sync_type_config == {"cdc_mode": "streaming"}
