"""Tests for PATCH `cdc_table_mode` semantics on the ExternalDataSchema viewset.

Uses pytest function-scoped fixtures (rather than `APIBaseTest`) to avoid mixing
TransactionTestCase semantics into the same module/process as the existing pytest
fixture-based tests in `test_external_data_schema.py` — that mix causes pytest-django
to behave inconsistently with the live `temporal` fixture used there.

Every external dependency (workflow trigger/cancel, schedule sync, CDC publication
mutation) is mocked. These tests only exercise the serializer + helper logic.
"""

import pytest
from unittest import mock

from django.test.client import Client as HttpClient

from temporalio.service import RPCError, RPCStatusCode

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user

from products.warehouse_sources.backend.facade.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

pytestmark = [pytest.mark.django_db]


_VIEW = "products.warehouse_sources.backend.presentation.views.external_data_schema"
_PATCH_TARGETS = {
    "is_cdc_enabled_for_team": "products.warehouse_sources.backend.presentation.views.external_data_schema.is_cdc_enabled_for_team",
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
    "is_buffered_snapshot_enabled": (
        "products.warehouse_sources.backend.temporal.data_imports.cdc.snapshot_lane.is_buffered_snapshot_enabled"
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
    cdc_deferred_runs: list[dict] | None = None,
    initial_sync_complete: bool = True,
    ingest_mode: str | None = None,
) -> tuple[ExternalDataSource, ExternalDataSchema]:
    job_inputs = {
        "schema": "public",
        "cdc_enabled": True,
        "cdc_management_mode": "posthog",
        "cdc_slot_name": "test_slot",
        "cdc_publication_name": "test_pub",
    }
    if ingest_mode is not None:
        job_inputs["cdc_ingest_mode"] = ingest_mode
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
    if cdc_deferred_runs is not None:
        sync_type_config["cdc_deferred_runs"] = cdc_deferred_runs

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
    ("old_mode", "new_mode", "ingest_mode"),
    [
        ("consolidated", "cdc_only", None),
        ("consolidated", "both", None),
        ("cdc_only", "consolidated", None),
        ("cdc_only", "both", None),
        ("consolidated", "both", "buffered"),
    ],
)
def test_patch_cdc_table_mode_adding_target_triggers_resnapshot(
    team, user, client: HttpClient, old_mode, new_mode, ingest_mode
):
    source, schema = _make_cdc_source_and_schema(
        team,
        cdc_table_mode=old_mode,
        # Pending deferred runs keep a buffered source's table on the legacy lane, so only the legacy
        # cases carry them.
        cdc_deferred_runs=None if ingest_mode else [{"job_id": "stale", "run_uuid": "stale", "batch_results": []}],
        ingest_mode=ingest_mode,
    )
    running_job = ExternalDataJob.objects.create(
        team=team,
        pipeline=source,
        schema=schema,
        status=ExternalDataJob.Status.RUNNING,
        workflow_id="running-workflow-id",
    )
    client.force_login(user)

    with (
        mock.patch(_PATCH_TARGETS["is_cdc_enabled_for_team"], return_value=True),
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
        mock.patch(_PATCH_TARGETS["is_buffered_snapshot_enabled"], return_value=True),
    ):
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={"cdc_table_mode": new_mode},
            content_type="application/json",
        )

    assert response.status_code == 200, response.content

    schema.refresh_from_db()
    assert schema.cdc_table_mode == new_mode
    # A buffered source's changes keep going to the buffer, which the new snapshot then replays.
    assert (schema.sync_type_config.get("cdc_snapshot_lane") == "buffer") is (ingest_mode == "buffered")
    assert schema.sync_type_config.get("cdc_mode") == "snapshot"
    assert schema.sync_type_config.get("cdc_last_log_position") is None
    assert schema.sync_type_config.get("cdc_deferred_runs") is None
    assert schema.initial_sync_complete is False
    assert schema.sync_type_config.get("reset_pipeline") is True
    mock_cancel.assert_called_once_with(running_job.workflow_id)
    mock_trigger.assert_called_once()


@pytest.mark.parametrize("action", ["resync", "cdc_table_mode_switch", "re_enable"])
def test_a_reset_is_left_to_capture_while_the_tables_sync_can_still_hand_over(team, user, client: HttpClient, action):
    source, schema = _make_cdc_source_and_schema(team, cdc_table_mode="consolidated", ingest_mode="buffered")
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
        mock.patch(_PATCH_TARGETS["is_cdc_enabled_for_team"], return_value=True),
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
    assert schema.sync_type_config["cdc_reset_pending"] == {
        "clear_deferred_runs": True,
        "trigger": True,
        "generation": 1,
    }
    assert "reset_pipeline" not in schema.sync_type_config
    assert schema.sync_type_config["cdc_mode"] == "streaming"
    assert schema.initial_sync_complete is True
    mock_cancel.assert_called_once_with(running_job.workflow_id)
    mock_pause.assert_called_once_with(str(schema.id))
    mock_view_unpause.assert_not_called()
    mock_trigger.assert_not_called()
    mock_trigger_capture.assert_called_once_with(source)


def test_a_hand_over_keeps_a_reset_that_is_still_waiting_on_a_slot(team, user, client: HttpClient):
    # Replacing the key instead of merging into it would drop `awaiting_slot`, and the next capture
    # run would start the snapshot before slot recovery has a point for it to resume from.
    source, schema = _make_cdc_source_and_schema(team, cdc_table_mode="consolidated")
    ExternalDataSchema.objects.filter(id=schema.id).update(
        sync_type_config={
            **schema.sync_type_config,
            "cdc_reset_pending": {"clear_deferred_runs": False, "awaiting_slot": True},
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
        "clear_deferred_runs": True,
        "trigger": True,
        "awaiting_slot": True,
        "generation": 1,
    }


@pytest.mark.parametrize(("should_sync_before", "should_sync_after"), [(True, False), (False, True)])
def test_toggling_sync_drops_the_snapshot_marker(team, user, client: HttpClient, should_sync_before, should_sync_after):
    # Capture skips a table while its sync is off, so its buffer has a gap. A marker left behind would
    # have the hand-over replay files from before the gap and bring deleted rows back.
    _, schema = _make_cdc_source_and_schema(team, cdc_table_mode="consolidated", ingest_mode="buffered")
    ExternalDataSchema.objects.filter(id=schema.id).update(
        should_sync=should_sync_before,
        initial_sync_complete=False,
        sync_type_config={**schema.sync_type_config, "cdc_mode": "snapshot", "cdc_snapshot_lane": "buffer"},
    )
    client.force_login(user)
    with (
        mock.patch(_PATCH_TARGETS["is_cdc_enabled_for_team"], return_value=True),
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


@pytest.mark.parametrize("ingest_mode", [None, "buffered"])
def test_resync_of_a_streaming_table_keeps_its_buffer_on_a_buffered_source(team, user, client: HttpClient, ingest_mode):
    _, schema = _make_cdc_source_and_schema(team, cdc_table_mode="consolidated", ingest_mode=ingest_mode)
    client.force_login(user)
    with (
        mock.patch(_PATCH_TARGETS["is_any_external_data_schema_paused"], return_value=False),
        mock.patch(_PATCH_TARGETS["has_queued_batches"], return_value=False),
        mock.patch(_PATCH_TARGETS["trigger_external_data_workflow"]),
        mock.patch(_PATCH_TARGETS["is_buffered_snapshot_enabled"], return_value=True),
    ):
        response = client.post(f"/api/environments/{team.pk}/external_data_schemas/{schema.id}/resync")

    assert response.status_code == 200, response.content
    schema.refresh_from_db()
    assert schema.sync_type_config.get("cdc_mode") == "snapshot"
    # Unmarked, the next capture run empties the buffer and can delete changes the snapshot never saw.
    assert (schema.sync_type_config.get("cdc_snapshot_lane") == "buffer") is (ingest_mode == "buffered")


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
        mock.patch(_PATCH_TARGETS["is_cdc_enabled_for_team"], return_value=True),
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
        mock.patch(_PATCH_TARGETS["is_cdc_enabled_for_team"], return_value=True),
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
        mock.patch(_PATCH_TARGETS["is_cdc_enabled_for_team"], return_value=True),
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
        mock.patch(_PATCH_TARGETS["is_cdc_enabled_for_team"], return_value=True),
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
