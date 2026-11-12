"""Tests for PATCH `cdc_table_mode` semantics on the ExternalDataSchema viewset.

Uses pytest function-scoped fixtures (rather than `APIBaseTest`) to avoid mixing
TransactionTestCase semantics into the same module/process as the existing pytest
fixture-based tests in `test_external_data_schema.py` — that mix causes pytest-django
to behave inconsistently with the live `temporal` fixture used there.

Every external dependency (workflow trigger/cancel, schedule sync, CDC publication
mutation) is mocked. These tests only exercise the serializer + helper logic.
"""

from contextlib import ExitStack

import pytest
from unittest import mock

from django.test.client import Client as HttpClient

from temporalio.service import RPCError, RPCStatusCode

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.models import ActivityLog, Team, User

from products.warehouse_sources.backend.facade.models import (
    INCREMENTAL_HISTORY_KEY,
    DataWarehouseTable,
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.models.column_statistics import WarehouseColumnStatistics

pytestmark = [pytest.mark.django_db]


_VIEW = "products.warehouse_sources.backend.presentation.views.external_data_schema"
_PATCH_TARGETS = {
    # Single private method backing both add_table/remove_table on the adapter — patching it
    # no-ops the engine-side ALTER PUBLICATION without touching parse_cdc_config gating.
    "alter_cdc_publication": (
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter._alter_publication_membership"
    ),
    "external_data_workflow_exists": (
        "products.warehouse_sources.backend.presentation.views.external_data_schema.external_data_workflow_exists"
    ),
    "sync_external_data_job_workflow": (
        "products.warehouse_sources.backend.presentation.views.external_data_schema.sync_external_data_job_workflow"
    ),
    "sync_cdc_extraction_schedule": (
        "products.warehouse_sources.backend.presentation.views.external_data_schema.sync_cdc_extraction_schedule"
    ),
    "cancel_external_data_workflow": "products.data_warehouse.backend.facade.api.cancel_external_data_workflow",
    # The hand-over reaches the facade directly, so the view's own name is a different object.
    "facade_sync_cdc_extraction_schedule": "products.data_warehouse.backend.facade.api.sync_cdc_extraction_schedule",
    "pause_external_data_schedule": "products.data_warehouse.backend.facade.api.pause_external_data_schedule",
    "trigger_cdc_extraction_schedule": "products.data_warehouse.backend.facade.api.trigger_cdc_extraction_schedule",
    # The load queue lives in the warehouse-sources database, which these tests do not create. Left
    # real, the probe raises and a reset is handed to capture instead of being applied here.
    "has_queued_batches": (
        "products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager.has_queued_batches"
    ),
    "trigger_external_data_workflow": (
        "products.warehouse_sources.backend.presentation.views.external_data_schema.trigger_external_data_workflow"
    ),
    "is_any_external_data_schema_paused": (
        "products.warehouse_sources.backend.presentation.views.external_data_schema.is_any_external_data_schema_paused"
    ),
}


@pytest.fixture
def organization():
    org = create_organization("Test Org")
    yield org
    org.delete()


@pytest.fixture
def team(organization):
    t = create_team(organization)
    yield t
    t.delete()


@pytest.fixture
def user(team):
    u = create_user("test@user.com", "Test User", team.organization)
    yield u
    u.delete()


def _make_cdc_source_and_schema(
    team,
    cdc_table_mode: str,
    cdc_last_log_position: str | None = "0/12345",
    initial_sync_complete: bool = True,
) -> tuple[ExternalDataSource, ExternalDataSchema]:
    job_inputs = {
        "schema": "public",
        "cdc_enabled": True,
        "cdc_management_mode": "posthog",
        "cdc_slot_name": "test_slot",
        "cdc_publication_name": "test_pub",
    }
    source = ExternalDataSource.objects.create(
        team=team,
        source_type=ExternalDataSourceType.POSTGRES,
        job_inputs=job_inputs,
    )
    sync_type_config: dict = {
        "cdc_mode": "streaming",
        "cdc_table_mode": cdc_table_mode,
        "primary_key_columns": ["id"],
    }
    if cdc_last_log_position is not None:
        sync_type_config["cdc_last_log_position"] = cdc_last_log_position

    schema = ExternalDataSchema.objects.create(
        team=team,
        source=source,
        name="orders",
        should_sync=True,
        sync_type=ExternalDataSchema.SyncType.CDC,
        initial_sync_complete=initial_sync_complete,
        sync_type_config=sync_type_config,
    )
    return source, schema


@pytest.mark.parametrize(
    ("old_mode", "new_mode"),
    [
        ("consolidated", "cdc_only"),
        ("consolidated", "both"),
        ("cdc_only", "consolidated"),
        ("cdc_only", "both"),
    ],
)
def test_patch_cdc_table_mode_adding_target_triggers_resnapshot(team, user, client: HttpClient, old_mode, new_mode):
    source, schema = _make_cdc_source_and_schema(team, cdc_table_mode=old_mode)
    running_job = ExternalDataJob.objects.create(
        team=team,
        pipeline=source,
        schema=schema,
        status=ExternalDataJob.Status.RUNNING,
        workflow_id="running-workflow-id",
    )
    client.force_login(user)

    with (
        mock.patch(_PATCH_TARGETS["alter_cdc_publication"]),
        mock.patch(_PATCH_TARGETS["external_data_workflow_exists"], return_value=True),
        mock.patch(_PATCH_TARGETS["sync_external_data_job_workflow"]),
        mock.patch(_PATCH_TARGETS["sync_cdc_extraction_schedule"]),
        mock.patch(
            _PATCH_TARGETS["cancel_external_data_workflow"],
            side_effect=RPCError("workflow not found", RPCStatusCode.NOT_FOUND, b""),
        ) as mock_cancel,
        mock.patch(_PATCH_TARGETS["has_queued_batches"], return_value=False),
        mock.patch(_PATCH_TARGETS["trigger_external_data_workflow"]) as mock_trigger,
    ):
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={"cdc_table_mode": new_mode},
            content_type="application/json",
        )

    assert response.status_code == 200, response.content

    schema.refresh_from_db()
    assert schema.cdc_table_mode == new_mode
    # The table's changes keep going to the buffer, which the new snapshot then replays.
    assert schema.sync_type_config.get("cdc_snapshot_lane") == "buffer"
    assert schema.sync_type_config.get("cdc_mode") == "snapshot"
    assert schema.sync_type_config.get("cdc_last_log_position") is None
    assert schema.initial_sync_complete is False
    assert schema.sync_type_config.get("reset_pipeline") is True
    mock_cancel.assert_called_once_with(running_job.workflow_id)
    mock_trigger.assert_called_once()


@pytest.mark.parametrize("action", ["resync", "cdc_table_mode_switch", "re_enable"])
def test_a_reset_is_left_to_capture_while_the_tables_sync_can_still_hand_over(team, user, client: HttpClient, action):
    source, schema = _make_cdc_source_and_schema(team, cdc_table_mode="consolidated")
    if action == "re_enable":
        ExternalDataSchema.objects.filter(id=schema.id).update(should_sync=False)
    running_job = ExternalDataJob.objects.create(
        team=team,
        pipeline=source,
        schema=schema,
        status=ExternalDataJob.Status.RUNNING,
        workflow_id="running-workflow-id",
    )
    client.force_login(user)

    with (
        mock.patch(_PATCH_TARGETS["is_any_external_data_schema_paused"], return_value=False),
        mock.patch(_PATCH_TARGETS["alter_cdc_publication"]),
        mock.patch(_PATCH_TARGETS["external_data_workflow_exists"], return_value=True),
        mock.patch(_PATCH_TARGETS["sync_external_data_job_workflow"]),
        mock.patch(_PATCH_TARGETS["sync_cdc_extraction_schedule"]),
        mock.patch(_PATCH_TARGETS["cancel_external_data_workflow"]) as mock_cancel,
        mock.patch(_PATCH_TARGETS["pause_external_data_schedule"]) as mock_pause,
        mock.patch(_PATCH_TARGETS["trigger_external_data_workflow"]) as mock_trigger,
        mock.patch(_PATCH_TARGETS["trigger_cdc_extraction_schedule"]) as mock_trigger_capture,
        mock.patch(f"{_VIEW}.pause_external_data_schedule"),
        mock.patch(f"{_VIEW}.unpause_external_data_schedule") as mock_view_unpause,
    ):
        url = f"/api/environments/{team.pk}/external_data_schemas/{schema.id}"
        if action == "resync":
            response = client.post(f"{url}/resync")
        else:
            payload = {"cdc_table_mode": "both"} if action == "cdc_table_mode_switch" else {"should_sync": True}
            response = client.patch(url, data=payload, content_type="application/json")

    assert response.status_code == 200, response.content
    schema.refresh_from_db()
    assert schema.sync_type_config["cdc_reset_pending"] == {"trigger": True, "generation": 1}
    assert "reset_pipeline" not in schema.sync_type_config
    assert schema.sync_type_config["cdc_mode"] == "streaming"
    assert schema.initial_sync_complete is True
    mock_cancel.assert_called_once_with(running_job.workflow_id)
    mock_pause.assert_called_once_with(str(schema.id))
    mock_view_unpause.assert_not_called()
    mock_trigger.assert_not_called()
    mock_trigger_capture.assert_called_once_with(str(source.id))


def test_a_hand_over_keeps_a_reset_that_is_still_waiting_on_a_slot(team, user, client: HttpClient):
    # Replacing the key instead of merging into it would drop `awaiting_slot`, and the next capture
    # run would start the snapshot before slot recovery has a point for it to resume from.
    source, schema = _make_cdc_source_and_schema(team, cdc_table_mode="consolidated")
    ExternalDataSchema.objects.filter(id=schema.id).update(
        sync_type_config={
            **schema.sync_type_config,
            "cdc_reset_pending": {"awaiting_slot": True},
        }
    )
    ExternalDataJob.objects.create(
        team=team,
        pipeline=source,
        schema=schema,
        status=ExternalDataJob.Status.RUNNING,
        workflow_id="running-workflow-id",
    )
    client.force_login(user)

    with (
        mock.patch(_PATCH_TARGETS["is_any_external_data_schema_paused"], return_value=False),
        mock.patch(_PATCH_TARGETS["cancel_external_data_workflow"]),
        mock.patch(_PATCH_TARGETS["pause_external_data_schedule"]),
        mock.patch(_PATCH_TARGETS["trigger_external_data_workflow"]),
        mock.patch(_PATCH_TARGETS["trigger_cdc_extraction_schedule"]),
    ):
        response = client.post(f"/api/environments/{team.pk}/external_data_schemas/{schema.id}/resync")

    assert response.status_code == 200, response.content
    schema.refresh_from_db()
    assert schema.sync_type_config["cdc_reset_pending"] == {
        "trigger": True,
        "awaiting_slot": True,
        "generation": 1,
    }


def test_a_hand_over_recreates_a_capture_schedule_that_is_gone(team, user, client: HttpClient):
    # Triggering a schedule that is gone starts no run, so the pending reset would wait for a tick
    # that never comes. Creating the schedule fires its first run, which finishes the reset.
    source, schema = _make_cdc_source_and_schema(team, cdc_table_mode="consolidated")
    ExternalDataJob.objects.create(
        team=team,
        pipeline=source,
        schema=schema,
        status=ExternalDataJob.Status.RUNNING,
        workflow_id="running-workflow-id",
    )
    client.force_login(user)

    with (
        mock.patch(_PATCH_TARGETS["is_any_external_data_schema_paused"], return_value=False),
        mock.patch(_PATCH_TARGETS["cancel_external_data_workflow"]),
        mock.patch(_PATCH_TARGETS["pause_external_data_schedule"]),
        mock.patch(_PATCH_TARGETS["trigger_external_data_workflow"]),
        mock.patch(_PATCH_TARGETS["trigger_cdc_extraction_schedule"], return_value=False),
        mock.patch(_PATCH_TARGETS["facade_sync_cdc_extraction_schedule"]) as mock_create_capture,
    ):
        response = client.post(f"/api/environments/{team.pk}/external_data_schemas/{schema.id}/resync")

    assert response.status_code == 200, response.content
    schema.refresh_from_db()
    assert schema.sync_type_config["cdc_reset_pending"]["trigger"] is True
    mock_create_capture.assert_called_once_with(source, create=True)


@pytest.mark.parametrize(("should_sync_before", "should_sync_after"), [(True, False), (False, True)])
def test_toggling_sync_drops_the_snapshot_marker(team, user, client: HttpClient, should_sync_before, should_sync_after):
    # Capture skips a table while its sync is off, so its buffer has a gap. A marker left behind would
    # have the hand-over replay files from before the gap and bring deleted rows back.
    _, schema = _make_cdc_source_and_schema(team, cdc_table_mode="consolidated")
    ExternalDataSchema.objects.filter(id=schema.id).update(
        should_sync=should_sync_before,
        initial_sync_complete=False,
        sync_type_config={**schema.sync_type_config, "cdc_mode": "snapshot", "cdc_snapshot_lane": "buffer"},
    )
    client.force_login(user)
    with (
        mock.patch(_PATCH_TARGETS["alter_cdc_publication"]),
        mock.patch(_PATCH_TARGETS["external_data_workflow_exists"], return_value=True),
        mock.patch(_PATCH_TARGETS["sync_external_data_job_workflow"]),
        mock.patch(_PATCH_TARGETS["sync_cdc_extraction_schedule"]),
        mock.patch(_PATCH_TARGETS["trigger_external_data_workflow"]),
        mock.patch(f"{_VIEW}.pause_external_data_schedule"),
        mock.patch(f"{_VIEW}.unpause_external_data_schedule"),
    ):
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={"should_sync": should_sync_after},
            content_type="application/json",
        )

    assert response.status_code == 200, response.content
    schema.refresh_from_db()
    assert "cdc_snapshot_lane" not in schema.sync_type_config


@pytest.mark.parametrize("should_sync_before", [True, False])
@pytest.mark.parametrize("new_sync_type", [ExternalDataSchema.SyncType.FULL_REFRESH, None])
def test_moving_a_table_off_cdc_drops_it_from_the_publication(
    team: Team, user: User, client: HttpClient, should_sync_before: bool, new_sync_type: str | None
) -> None:
    _, schema = _make_cdc_source_and_schema(team, cdc_table_mode="consolidated")
    ExternalDataSchema.objects.filter(id=schema.id).update(
        should_sync=should_sync_before,
        sync_type_config={key: value for key, value in schema.sync_type_config.items() if key != "primary_key_columns"},
    )
    client.force_login(user)
    with (
        mock.patch(_PATCH_TARGETS["alter_cdc_publication"]) as alter_publication,
        mock.patch(_PATCH_TARGETS["external_data_workflow_exists"], return_value=True),
        mock.patch(_PATCH_TARGETS["sync_external_data_job_workflow"]),
        mock.patch(_PATCH_TARGETS["sync_cdc_extraction_schedule"]) as sync_capture_schedule,
        mock.patch(_PATCH_TARGETS["trigger_external_data_workflow"]),
        mock.patch(f"{_VIEW}.pause_external_data_schedule"),
        mock.patch(f"{_VIEW}.unpause_external_data_schedule"),
    ):
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={"sync_type": new_sync_type, "should_sync": True},
            content_type="application/json",
        )

    assert response.status_code == 200, response.content
    assert [call.kwargs["add"] for call in alter_publication.call_args_list] == [False]
    sync_capture_schedule.assert_called_once()
    schema.refresh_from_db()
    assert schema.sync_type == new_sync_type


@pytest.mark.parametrize("management_mode", ["posthog", "self_managed"])
def test_a_table_moved_off_cdc_during_a_handed_over_reset_syncs_again(
    team: Team, user: User, client: HttpClient, management_mode: str
) -> None:
    source, schema = _make_cdc_source_and_schema(team, cdc_table_mode="consolidated")
    source.job_inputs = {**source.job_inputs, "cdc_management_mode": management_mode}
    source.save()
    ExternalDataSchema.objects.filter(id=schema.id).update(
        sync_type_config={
            **schema.sync_type_config,
            "cdc_reset_pending": {"trigger": True},
            "cdc_snapshot_lane": "buffer",
            "cdc_snapshot_position": 23803368,
        }
    )
    client.force_login(user)
    with (
        mock.patch(_PATCH_TARGETS["alter_cdc_publication"]),
        mock.patch(_PATCH_TARGETS["external_data_workflow_exists"], return_value=True),
        mock.patch(_PATCH_TARGETS["sync_external_data_job_workflow"]),
        mock.patch(_PATCH_TARGETS["sync_cdc_extraction_schedule"]),
        mock.patch(_PATCH_TARGETS["trigger_external_data_workflow"]),
        mock.patch(f"{_VIEW}.unpause_external_data_schedule") as unpause,
    ):
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={"sync_type": "full_refresh"},
            content_type="application/json",
        )

    assert response.status_code == 200, response.content
    schema.refresh_from_db()
    assert "cdc_reset_pending" not in schema.sync_type_config
    assert "cdc_snapshot_lane" not in schema.sync_type_config
    assert "cdc_snapshot_position" not in schema.sync_type_config
    unpause.assert_called_once_with(str(schema.id))


@pytest.mark.parametrize(
    ("table_mode", "over_billing_limit", "expected_status", "resynced"),
    [
        ("cdc_only", False, 200, True),
        ("cdc_only", True, 400, False),
        ("both", False, 200, False),
    ],
)
def test_moving_a_cdc_only_table_off_cdc_resyncs_it(
    team: Team,
    user: User,
    client: HttpClient,
    table_mode: str,
    over_billing_limit: bool,
    expected_status: int,
    resynced: bool,
) -> None:
    _, schema = _make_cdc_source_and_schema(team, cdc_table_mode=table_mode)
    client.force_login(user)
    with (
        mock.patch(_PATCH_TARGETS["alter_cdc_publication"]),
        mock.patch(_PATCH_TARGETS["external_data_workflow_exists"], return_value=True),
        mock.patch(_PATCH_TARGETS["sync_external_data_job_workflow"]),
        mock.patch(_PATCH_TARGETS["sync_cdc_extraction_schedule"]),
        mock.patch(_PATCH_TARGETS["trigger_external_data_workflow"]) as trigger,
        mock.patch(_PATCH_TARGETS["is_any_external_data_schema_paused"], return_value=over_billing_limit),
    ):
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={"sync_type": "full_refresh"},
            content_type="application/json",
        )

    assert response.status_code == expected_status, response.content
    schema.refresh_from_db()
    assert bool(schema.sync_type_config.get("reset_pipeline")) is resynced
    assert trigger.called is resynced


def test_a_table_stays_in_the_publication_when_its_move_off_cdc_is_not_saved(
    team: Team, user: User, client: HttpClient
) -> None:
    _, schema = _make_cdc_source_and_schema(team, cdc_table_mode="consolidated")
    client.force_login(user)
    client.raise_request_exception = False
    with (
        mock.patch(_PATCH_TARGETS["alter_cdc_publication"]) as alter_publication,
        mock.patch(_PATCH_TARGETS["sync_cdc_extraction_schedule"]),
        mock.patch(
            f"{_VIEW}.ExternalDataSchemaSerializer._save_merging_sync_type_config",
            side_effect=RuntimeError("save failed"),
        ),
    ):
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={"sync_type": "full_refresh"},
            content_type="application/json",
        )

    assert response.status_code == 500
    alter_publication.assert_not_called()
    schema.refresh_from_db()
    assert schema.sync_type == ExternalDataSchema.SyncType.CDC


@pytest.mark.parametrize(("sync_frequency", "expected_status"), [("7day", 200), ("30day", 400)])
def test_a_cdc_table_syncs_before_its_captured_changes_expire(
    team, user, client: HttpClient, sync_frequency, expected_status
):
    _, schema = _make_cdc_source_and_schema(team, cdc_table_mode="consolidated")
    client.force_login(user)
    with (
        mock.patch(_PATCH_TARGETS["external_data_workflow_exists"], return_value=True),
        mock.patch(_PATCH_TARGETS["sync_external_data_job_workflow"]),
    ):
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={"sync_frequency": sync_frequency},
            content_type="application/json",
        )

    assert response.status_code == expected_status, response.content
    if expected_status == 400:
        assert "must sync at least weekly" in str(response.json())


def test_resync_of_a_streaming_table_keeps_its_buffer(team, user, client: HttpClient):
    _, schema = _make_cdc_source_and_schema(team, cdc_table_mode="consolidated")
    client.force_login(user)
    with (
        mock.patch(_PATCH_TARGETS["is_any_external_data_schema_paused"], return_value=False),
        mock.patch(_PATCH_TARGETS["has_queued_batches"], return_value=False),
        mock.patch(_PATCH_TARGETS["trigger_external_data_workflow"]),
    ):
        response = client.post(f"/api/environments/{team.pk}/external_data_schemas/{schema.id}/resync")

    assert response.status_code == 200, response.content
    schema.refresh_from_db()
    assert schema.sync_type_config.get("cdc_mode") == "snapshot"
    # Unmarked, the next capture run empties the buffer and can delete changes the snapshot never saw.
    assert schema.sync_type_config.get("cdc_snapshot_lane") == "buffer"


@pytest.mark.parametrize(
    ("old_mode", "new_mode"),
    [
        ("both", "consolidated"),
        ("both", "cdc_only"),
    ],
)
def test_patch_cdc_table_mode_dropping_target_skips_resnapshot(team, user, client: HttpClient, old_mode, new_mode):
    _, schema = _make_cdc_source_and_schema(team, cdc_table_mode=old_mode)
    client.force_login(user)

    with (
        mock.patch(_PATCH_TARGETS["alter_cdc_publication"]),
        mock.patch(_PATCH_TARGETS["external_data_workflow_exists"], return_value=True),
        mock.patch(_PATCH_TARGETS["sync_external_data_job_workflow"]),
        mock.patch(_PATCH_TARGETS["sync_cdc_extraction_schedule"]),
        mock.patch(_PATCH_TARGETS["cancel_external_data_workflow"]) as mock_cancel,
        mock.patch(_PATCH_TARGETS["trigger_external_data_workflow"]) as mock_trigger,
    ):
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={"cdc_table_mode": new_mode},
            content_type="application/json",
        )

    assert response.status_code == 200, response.content

    schema.refresh_from_db()
    assert schema.cdc_table_mode == new_mode
    # Streaming state preserved — the remaining target table still holds current data.
    assert schema.sync_type_config.get("cdc_mode") == "streaming"
    assert schema.sync_type_config.get("cdc_last_log_position") == "0/12345"
    assert schema.initial_sync_complete is True
    mock_cancel.assert_not_called()
    mock_trigger.assert_not_called()


def test_patch_cdc_table_mode_idempotent_skips_resnapshot(team, user, client: HttpClient):
    _, schema = _make_cdc_source_and_schema(team, cdc_table_mode="both", cdc_last_log_position="0/9999")
    client.force_login(user)

    with (
        mock.patch(_PATCH_TARGETS["alter_cdc_publication"]),
        mock.patch(_PATCH_TARGETS["external_data_workflow_exists"], return_value=True),
        mock.patch(_PATCH_TARGETS["sync_external_data_job_workflow"]),
        mock.patch(_PATCH_TARGETS["sync_cdc_extraction_schedule"]),
        mock.patch(_PATCH_TARGETS["cancel_external_data_workflow"]) as mock_cancel,
        mock.patch(_PATCH_TARGETS["trigger_external_data_workflow"]) as mock_trigger,
    ):
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={"cdc_table_mode": "both"},
            content_type="application/json",
        )

    assert response.status_code == 200, response.content

    schema.refresh_from_db()
    assert schema.sync_type_config.get("cdc_mode") == "streaming"
    assert schema.initial_sync_complete is True
    mock_cancel.assert_not_called()
    mock_trigger.assert_not_called()


def test_patch_cdc_table_mode_rejected_when_team_over_billing_limit(team, user, client: HttpClient):
    """Re-snapshot-triggering transitions are gated on the team being under their sync billing limit
    — otherwise the new job would land immediately in BillingLimit state. Pre-save check so the new
    mode doesn't get persisted without an actual resnapshot."""
    source, schema = _make_cdc_source_and_schema(team, cdc_table_mode="consolidated")
    client.force_login(user)

    with (
        mock.patch(_PATCH_TARGETS["alter_cdc_publication"]),
        mock.patch(_PATCH_TARGETS["external_data_workflow_exists"], return_value=True),
        mock.patch(_PATCH_TARGETS["sync_external_data_job_workflow"]),
        mock.patch(_PATCH_TARGETS["sync_cdc_extraction_schedule"]),
        mock.patch(_PATCH_TARGETS["cancel_external_data_workflow"]) as mock_cancel,
        mock.patch(_PATCH_TARGETS["trigger_external_data_workflow"]) as mock_trigger,
        mock.patch(_PATCH_TARGETS["is_any_external_data_schema_paused"], return_value=True),
    ):
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={"cdc_table_mode": "both"},
            content_type="application/json",
        )

    assert response.status_code == 400, response.content
    assert b"Monthly sync limit reached" in response.content

    schema.refresh_from_db()
    # Mode unchanged; no workflow side-effects fired.
    assert schema.cdc_table_mode == "consolidated"
    assert schema.sync_type_config.get("cdc_mode") == "streaming"
    mock_cancel.assert_not_called()
    mock_trigger.assert_not_called()


def test_patch_cdc_table_mode_drop_target_allowed_when_team_over_billing_limit(team, user, client: HttpClient):
    """Drop-target transitions don't kick a re-snapshot, so the billing gate doesn't apply — the
    schema's existing tables already hold current data."""
    _, schema = _make_cdc_source_and_schema(team, cdc_table_mode="both")
    client.force_login(user)

    with (
        mock.patch(_PATCH_TARGETS["alter_cdc_publication"]),
        mock.patch(_PATCH_TARGETS["external_data_workflow_exists"], return_value=True),
        mock.patch(_PATCH_TARGETS["sync_external_data_job_workflow"]),
        mock.patch(_PATCH_TARGETS["sync_cdc_extraction_schedule"]),
        mock.patch(_PATCH_TARGETS["cancel_external_data_workflow"]),
        mock.patch(_PATCH_TARGETS["trigger_external_data_workflow"]),
        mock.patch(_PATCH_TARGETS["is_any_external_data_schema_paused"], return_value=True),
    ):
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={"cdc_table_mode": "consolidated"},
            content_type="application/json",
        )

    assert response.status_code == 200, response.content
    schema.refresh_from_db()
    assert schema.cdc_table_mode == "consolidated"


@pytest.mark.parametrize(
    ("old_mode", "patch", "expected_event", "expected_table_mode"),
    [
        ("consolidated", {"cdc_table_mode": "both"}, "data warehouse history enabled", "both"),
        ("both", {"cdc_table_mode": "consolidated"}, "data warehouse history disabled", "both"),
        ("cdc_only", {"sync_type": "full_refresh"}, "data warehouse history disabled", "cdc_only"),
        ("cdc_only", {"cdc_table_mode": "both"}, None, None),
        ("consolidated", {"cdc_table_mode": "consolidated"}, None, None),
    ],
)
def test_patch_reports_history_enabled_and_disabled(
    team, user, client: HttpClient, old_mode, patch, expected_event, expected_table_mode
):
    source, schema = _make_cdc_source_and_schema(team, cdc_table_mode=old_mode)
    client.force_login(user)

    with (
        mock.patch(_PATCH_TARGETS["alter_cdc_publication"]),
        mock.patch(_PATCH_TARGETS["external_data_workflow_exists"], return_value=True),
        mock.patch(_PATCH_TARGETS["sync_external_data_job_workflow"]),
        mock.patch(_PATCH_TARGETS["sync_cdc_extraction_schedule"]),
        mock.patch(_PATCH_TARGETS["cancel_external_data_workflow"]),
        mock.patch(_PATCH_TARGETS["facade_sync_cdc_extraction_schedule"]),
        mock.patch(_PATCH_TARGETS["pause_external_data_schedule"]),
        mock.patch(_PATCH_TARGETS["trigger_cdc_extraction_schedule"]),
        mock.patch(_PATCH_TARGETS["has_queued_batches"], return_value=False),
        mock.patch(_PATCH_TARGETS["trigger_external_data_workflow"]),
        mock.patch(_PATCH_TARGETS["is_any_external_data_schema_paused"], return_value=False),
        mock.patch("posthog.event_usage.posthoganalytics.capture") as mock_capture,
    ):
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data=patch,
            content_type="application/json",
        )

    assert response.status_code == 200, response.content
    history_events = [
        call.kwargs
        for call in mock_capture.call_args_list
        if str(call.kwargs.get("event", "")).startswith("data warehouse history")
    ]
    assert [event["event"] for event in history_events] == ([expected_event] if expected_event else [])
    if expected_event:
        assert history_events[0]["properties"]["schema_id"] == str(schema.id)
        assert history_events[0]["properties"]["source_id"] == str(source.id)
        assert history_events[0]["properties"]["table_mode"] == expected_table_mode


_GET_S3_CLIENT = "products.data_warehouse.backend.facade.api.get_s3_client"


def _history_table(schema: ExternalDataSchema, *, linked: bool = False) -> DataWarehouseTable:
    table = DataWarehouseTable.objects.create(
        team=schema.team,
        name="postgres_orders_cdc",
        format="DeltaS3Wrapper",
        url_pattern="s3://bucket/orders_cdc",
        external_data_source=schema.source,
        options={"history_table": True},
    )
    if linked:
        ExternalDataSchema.objects.filter(id=schema.id).update(table=table)
    return table


def _history_drop_mocks(*, queued: bool = False, workflow_running: bool = False) -> list:
    return [
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.cdc.snapshot_lane._workflow_is_running",
            return_value=workflow_running,
        ),
        mock.patch(_PATCH_TARGETS["alter_cdc_publication"]),
        mock.patch(_PATCH_TARGETS["external_data_workflow_exists"], return_value=True),
        mock.patch(_PATCH_TARGETS["sync_external_data_job_workflow"]),
        mock.patch(_PATCH_TARGETS["sync_cdc_extraction_schedule"]),
        mock.patch(_PATCH_TARGETS["cancel_external_data_workflow"]),
        mock.patch(_PATCH_TARGETS["has_queued_batches"], return_value=queued),
        mock.patch(_PATCH_TARGETS["trigger_external_data_workflow"]),
        mock.patch(_PATCH_TARGETS["is_any_external_data_schema_paused"], return_value=False),
        mock.patch(_GET_S3_CLIENT, return_value=mock.MagicMock(**{"ls.return_value": []})),
    ]


@pytest.mark.parametrize(
    ("old_mode", "patch", "drop", "job_running", "expected_status", "dropped"),
    [
        ("both", {"cdc_table_mode": "consolidated"}, True, False, 200, True),
        ("both", {"cdc_table_mode": "consolidated"}, False, False, 200, False),
        # cdc_only links the schema to its history table, and the switch takes a new snapshot.
        ("cdc_only", {"cdc_table_mode": "consolidated"}, True, False, 200, True),
        ("both", {"sync_type": "full_refresh"}, True, False, 200, True),
        # The schema keeps its CDC mode, but no incremental history marker, so it stops writing history.
        (
            "both",
            {"sync_type": "incremental", "incremental_field": "updated_at", "incremental_field_type": "datetime"},
            True,
            False,
            200,
            True,
        ),
        ("consolidated", {"cdc_table_mode": "both"}, True, False, 400, False),
        ("both", {"cdc_table_mode": "consolidated"}, True, True, 400, False),
    ],
)
def test_a_switch_off_history_drops_the_history_table_only_when_asked(
    team, user, client: HttpClient, old_mode, patch, drop, job_running, expected_status, dropped
):
    source, schema = _make_cdc_source_and_schema(team, cdc_table_mode=old_mode)
    history = _history_table(schema, linked=old_mode == "cdc_only")
    if job_running:
        ExternalDataJob.objects.create(
            team=team,
            pipeline=source,
            schema=schema,
            status=ExternalDataJob.Status.RUNNING,
            workflow_id="sync-workflow",
        )
    client.force_login(user)

    with ExitStack() as stack:
        for patcher in _history_drop_mocks(workflow_running=job_running):
            stack.enter_context(patcher)
        capture = stack.enter_context(mock.patch("posthog.event_usage.posthoganalytics.capture"))
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={**patch, "drop_history_table": drop},
            content_type="application/json",
        )

    assert response.status_code == expected_status, response.content
    history.refresh_from_db()
    schema.refresh_from_db()
    assert history.deleted is dropped
    if dropped:
        assert schema.table_id is None
    deleted_events = [
        call.kwargs
        for call in capture.call_args_list
        if call.kwargs.get("event") == "data warehouse history table deleted"
    ]
    assert [event["properties"]["trigger"] for event in deleted_events] == (["mode_change"] if dropped else [])


@pytest.mark.parametrize(
    ("sync_type", "mode", "extra", "drop", "expected_status", "record_kept"),
    [
        # A table that stopped writing history keeps it, and a new mask can't reach its past values. Nothing
        # refills it, so the confirmed delete removes the record too.
        (ExternalDataSchema.SyncType.CDC, "consolidated", {}, False, 400, True),
        (ExternalDataSchema.SyncType.CDC, "consolidated", {}, True, 200, False),
        # An incremental table that keeps history fills the same table again from the masking rebuild.
        (ExternalDataSchema.SyncType.INCREMENTAL, "both", {}, False, 400, True),
        (ExternalDataSchema.SyncType.INCREMENTAL, "both", {}, True, 200, True),
        # The same request turns history off, so nothing refills the table.
        (ExternalDataSchema.SyncType.INCREMENTAL, "both", {"cdc_table_mode": "consolidated"}, True, 200, False),
    ],
)
def test_masking_a_table_with_a_history_table_empties_it_only_when_asked(
    team, user, client: HttpClient, sync_type, mode, extra, drop, expected_status, record_kept
):
    _, schema = _make_cdc_source_and_schema(team, cdc_table_mode=mode)
    config = {
        **schema.sync_type_config,
        "schema_metadata": {
            "columns": [
                {"name": name, "data_type": "text", "is_nullable": True} for name in ("id", "email", "updated_at")
            ]
        },
    }
    if sync_type == ExternalDataSchema.SyncType.INCREMENTAL:
        config |= {
            "incremental_field": "updated_at",
            "incremental_field_type": "datetime",
            INCREMENTAL_HISTORY_KEY: True,
        }
    ExternalDataSchema.objects.filter(id=schema.id).update(sync_type=sync_type, sync_type_config=config)
    if sync_type == ExternalDataSchema.SyncType.INCREMENTAL:
        # Incremental history always writes the `_history` naming.
        history = DataWarehouseTable.objects.create(
            team=team,
            name="postgres_orders_history",
            format="DeltaS3Wrapper",
            external_data_source=schema.source,
            options={"history_table": True, "history_naming": "ph_validity"},
        )
    else:
        history = _history_table(schema)
    stats = WarehouseColumnStatistics.objects.for_team(team.id).create(
        team=team,
        table=history,
        column_name="email",
        min_value="a@example.com",
        max_value="z@example.com",
        has_min_max=True,
    )
    client.force_login(user)
    folder = f"bucket/{schema.folder_path()}/{history.name.removeprefix('postgres_')}"
    s3 = mock.MagicMock(**{"ls.return_value": [folder, f"{folder}_ph_staging"]})

    with ExitStack() as stack:
        for patcher in _history_drop_mocks():
            stack.enter_context(patcher)
        stack.enter_context(mock.patch(_GET_S3_CLIENT, return_value=s3))
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={"masked_columns": ["email"], "drop_history_table": drop, **extra},
            content_type="application/json",
        )

    assert response.status_code == expected_status, response.content
    history.refresh_from_db()
    schema.refresh_from_db()
    # A kept record lets the rebuild register the same table, so its access rules stay in force.
    assert history.deleted is not record_kept
    deleted = sorted(s3.rm.call_args.args[0]) if s3.rm.called else []
    assert deleted == ([folder, f"{folder}_ph_staging"] if expected_status == 200 else [])
    assert (schema.masked_columns or []) == (["email"] if expected_status == 200 else [])
    stats.refresh_from_db()
    assert stats.max_value == (None if expected_status == 200 else "z@example.com")
    logged = list(
        ActivityLog.objects.filter(scope="DataWarehouseTable", item_id=str(history.id)).values_list(
            "activity", flat=True
        )
    )
    assert logged == ([] if expected_status != 200 else ["updated"] if record_kept else ["deleted"])


@pytest.mark.parametrize(("chose_history", "reported"), [(False, "consolidated"), (True, "both")])
def test_a_schema_that_left_cdc_returns_to_the_mode_the_api_reports(
    team, user, client: HttpClient, chose_history, reported
):
    _, schema = _make_cdc_source_and_schema(team, cdc_table_mode="both")
    config = {
        **schema.sync_type_config,
        "incremental_field": "updated_at",
        "incremental_field_type": "datetime",
        INCREMENTAL_HISTORY_KEY: chose_history,
    }
    ExternalDataSchema.objects.filter(id=schema.id).update(
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL, sync_type_config=config
    )
    client.force_login(user)
    url = f"/api/environments/{team.pk}/external_data_schemas/{schema.id}"

    assert client.get(url).json()["cdc_table_mode"] == reported
    with ExitStack() as stack:
        for patcher in _history_drop_mocks():
            stack.enter_context(patcher)
        response = client.patch(url, data={"sync_type": "cdc"}, content_type="application/json")

    assert response.status_code == 200, response.content
    schema.refresh_from_db()
    assert schema.cdc_table_mode == reported


def test_a_mask_whose_history_delete_is_refused_is_not_saved(team, user, client: HttpClient):
    _, schema = _make_cdc_source_and_schema(team, cdc_table_mode="consolidated")
    config = {
        **schema.sync_type_config,
        "schema_metadata": {
            "columns": [
                {"name": name, "data_type": "text", "is_nullable": True} for name in ("id", "email", "updated_at")
            ]
        },
    }
    ExternalDataSchema.objects.filter(id=schema.id).update(sync_type_config=config)
    history = _history_table(schema)
    client.force_login(user)
    s3 = mock.MagicMock(**{"ls.return_value": [f"bucket/{schema.folder_path()}/orders_cdc"]})

    with ExitStack() as stack:
        for patcher in _history_drop_mocks():
            stack.enter_context(patcher)
        stack.enter_context(mock.patch(_GET_S3_CLIENT, return_value=s3))
        # A sync starts between the check before the save and the delete.
        stack.enter_context(mock.patch(_PATCH_TARGETS["has_queued_batches"], side_effect=[False, True]))
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={"masked_columns": ["email"], "drop_history_table": True},
            content_type="application/json",
        )

    assert response.status_code == 400, response.content
    assert "drop_history_table" in response.json()["attr"]
    schema.refresh_from_db()
    history.refresh_from_db()
    assert not schema.masked_columns
    assert not history.deleted
    s3.rm.assert_not_called()


@pytest.mark.parametrize(
    ("sync_running", "expected_status"),
    [
        (False, 200),
        # The rows can't be deleted while a sync could still stage more, so the mask isn't saved.
        (True, 400),
    ],
)
def test_a_mask_deletes_staged_history_rows_before_any_history_table_exists(
    team, user, client: HttpClient, sync_running, expected_status
):
    # A first history sync staged rows and failed before it registered its history table.
    _, schema = _make_cdc_source_and_schema(team, cdc_table_mode="both")
    config = {
        **schema.sync_type_config,
        "incremental_field": "updated_at",
        "incremental_field_type": "datetime",
        INCREMENTAL_HISTORY_KEY: True,
        "schema_metadata": {
            "columns": [
                {"name": name, "data_type": "text", "is_nullable": True} for name in ("id", "email", "updated_at")
            ]
        },
    }
    ExternalDataSchema.objects.filter(id=schema.id).update(
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL, sync_type_config=config
    )
    client.force_login(user)
    staging = f"bucket/{schema.folder_path()}/orders_history_ph_staging"
    s3 = mock.MagicMock(**{"ls.return_value": [f"bucket/{schema.folder_path()}/orders", staging]})

    with ExitStack() as stack:
        for patcher in _history_drop_mocks(queued=sync_running):
            stack.enter_context(patcher)
        stack.enter_context(mock.patch(_GET_S3_CLIENT, return_value=s3))
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={"masked_columns": ["email"]},
            content_type="application/json",
        )

    assert response.status_code == expected_status, response.content
    schema.refresh_from_db()
    assert (schema.masked_columns or []) == (["email"] if expected_status == 200 else [])
    deleted = s3.rm.call_args.args[0] if s3.rm.called else []
    assert deleted == ([staging] if expected_status == 200 else [])


@pytest.mark.parametrize(("mode", "expected_status"), [("consolidated", 204), ("both", 400)])
def test_the_history_table_action_deletes_only_a_table_the_schema_no_longer_writes(
    team, user, client: HttpClient, mode, expected_status
):
    _, schema = _make_cdc_source_and_schema(team, cdc_table_mode=mode)
    history = _history_table(schema)
    client.force_login(user)
    url = f"/api/environments/{team.pk}/external_data_schemas/{schema.id}"

    before = client.get(url).json()["registered_history_table_name"]
    with ExitStack() as stack:
        for patcher in _history_drop_mocks():
            stack.enter_context(patcher)
        response = client.delete(f"{url}/history_table/")
    after = client.get(url).json()["registered_history_table_name"]

    assert response.status_code == expected_status, response.content
    history.refresh_from_db()
    assert history.deleted is (expected_status == 204)
    assert (before, after) == ("postgres_orders_cdc", None if mode == "consolidated" else "postgres_orders_cdc")


def test_a_drop_refused_after_the_save_names_the_kept_history_table(team, user, client: HttpClient):
    _, schema = _make_cdc_source_and_schema(team, cdc_table_mode="both")
    history = _history_table(schema)
    client.force_login(user)

    with ExitStack() as stack:
        for patcher in _history_drop_mocks():
            stack.enter_context(patcher)
        # A sync starts between the check before the save and the drop after it.
        stack.enter_context(mock.patch(_PATCH_TARGETS["has_queued_batches"], side_effect=[False, True]))
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={"cdc_table_mode": "consolidated", "drop_history_table": True},
            content_type="application/json",
        )

    assert response.status_code == 200, response.content
    assert response.json()["registered_history_table_name"] == "postgres_orders_cdc"
    history.refresh_from_db()
    assert not history.deleted
