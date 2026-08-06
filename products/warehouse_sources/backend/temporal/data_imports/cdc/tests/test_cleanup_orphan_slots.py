import uuid
from contextlib import contextmanager

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc.activities import cleanup_orphan_slots_activity
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.config import PostgresCDCConfig

pytestmark = pytest.mark.django_db


def _create_source(team, *, deleted=False, job_inputs=None):
    return ExternalDataSource.objects.create(
        team_id=team.pk,
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        status="Completed",
        source_type="Postgres",
        deleted=deleted,
        job_inputs=job_inputs,
    )


def _create_cdc_schema(team, source, name="users"):
    return ExternalDataSchema.objects.create(
        team_id=team.pk,
        source=source,
        name=name,
        sync_type=ExternalDataSchema.SyncType.CDC,
        should_sync=True,
        sync_type_config={"cdc_mode": "streaming"},
    )


def _cdc_job_inputs(*, enabled=True, management="posthog", auto_drop_slot=True, slot="posthog_slot", pub="posthog_pub"):
    return {
        "cdc_enabled": enabled,
        "cdc_management_mode": management,
        "cdc_auto_drop_slot": auto_drop_slot,
        "cdc_slot_name": slot,
        "cdc_publication_name": pub,
    }


def _mock_adapter(*, lag_bytes=0, retention_cap_mb=None):
    """Adapter mock that decodes config for real (proving the encrypted-job_inputs path)
    but stubs every database connection."""
    adapter = MagicMock()
    adapter.parse_cdc_config.side_effect = lambda source: PostgresCDCConfig.from_source(source)

    @contextmanager
    def _conn(source, connect_timeout=15):
        yield MagicMock()

    adapter.management_connection.side_effect = _conn
    adapter.get_lag_bytes.return_value = lag_bytes
    adapter.get_retention_cap_mb.return_value = retention_cap_mb
    return adapter


def _run(adapter):
    with (
        patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity") as mock_activity,
        patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.HeartbeaterSync"),
        patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections"),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter",
            return_value=adapter,
        ),
        patch("products.data_warehouse.backend.logic.data_load.service.delete_cdc_extraction_schedule") as mock_delete,
        # mark_cdc_broken (critical-lag paths) reaches Temporal / Kafka / analytics — stub the boundaries.
        patch("products.data_warehouse.backend.logic.data_load.service.pause_cdc_extraction_schedule") as mock_pause,
        patch("products.notifications.backend.facade.api.create_notification"),
        patch("posthoganalytics.capture"),
    ):
        cleanup_orphan_slots_activity()
    return mock_activity, mock_delete, mock_pause


def test_encrypted_cdc_source_is_selected(team):
    # Regression: cdc_enabled is encrypted at rest, so the old ORM filter never matched
    # and the sweeper checked zero sources. It must now reach the active lag-check path.
    _create_source(team, job_inputs=_cdc_job_inputs())
    adapter = _mock_adapter(lag_bytes=0)

    _run(adapter)

    adapter.get_lag_bytes.assert_called_once()


@pytest.mark.parametrize(
    "job_inputs",
    [
        None,
        _cdc_job_inputs(enabled=False),
        _cdc_job_inputs(slot=""),
        _cdc_job_inputs(pub=""),
    ],
)
def test_disabled_or_incomplete_sources_skipped(team, job_inputs):
    _create_source(team, job_inputs=job_inputs)
    adapter = _mock_adapter()

    _run(adapter)

    adapter.get_lag_bytes.assert_not_called()


def test_deleted_posthog_managed_drops_resources_and_schedule(team):
    _create_source(team, deleted=True, job_inputs=_cdc_job_inputs(management="posthog"))
    adapter = _mock_adapter()

    _, mock_delete, _ = _run(adapter)

    mock_delete.assert_called_once()
    adapter.drop_resources.assert_called_once()
    adapter.get_lag_bytes.assert_not_called()


def test_deleted_self_managed_drops_schedule_but_not_slot(team):
    _create_source(team, deleted=True, job_inputs=_cdc_job_inputs(management="self_managed"))
    adapter = _mock_adapter()

    _, mock_delete, _ = _run(adapter)

    mock_delete.assert_called_once()
    adapter.drop_resources.assert_not_called()


def test_critical_lag_posthog_auto_drop_marks_broken_and_pauses(team):
    source = _create_source(team, job_inputs=_cdc_job_inputs(auto_drop_slot=True))
    schema = _create_cdc_schema(team, source)
    adapter = _mock_adapter(lag_bytes=5000 * 1024 * 1024)  # 5000 MB > 2048 MB critical default

    _, _, mock_pause = _run(adapter)

    adapter.drop_resources.assert_called_once()
    source.refresh_from_db()
    assert source.status == ExternalDataSource.Status.ERROR
    schema.refresh_from_db()
    assert schema.status == ExternalDataSchema.Status.FAILED
    assert schema.sync_type_config["cdc_broken"]["reason"] == "auto_dropped_critical_lag"
    mock_pause.assert_called_once_with(str(source.id))


def test_critical_lag_auto_drop_disabled_does_not_drop(team):
    # cdc_auto_drop_slot stored as boolean False round-trips to "False"; str_to_bool must
    # decode it as False so the safety net stays off.
    _create_source(team, job_inputs=_cdc_job_inputs(auto_drop_slot=False))
    adapter = _mock_adapter(lag_bytes=5000 * 1024 * 1024)

    _run(adapter)

    adapter.drop_resources.assert_not_called()


def test_critical_lag_self_managed_marks_broken_without_drop_or_pause(team):
    source = _create_source(team, job_inputs=_cdc_job_inputs(management="self_managed"))
    schema = _create_cdc_schema(team, source)
    adapter = _mock_adapter(lag_bytes=5000 * 1024 * 1024)

    _, _, mock_pause = _run(adapter)

    # Customer owns the slot: surface the broken state but never drop or pause — it may recover.
    adapter.drop_resources.assert_not_called()
    mock_pause.assert_not_called()
    source.refresh_from_db()
    assert source.status == ExternalDataSource.Status.ERROR
    schema.refresh_from_db()
    assert schema.sync_type_config["cdc_broken"]["reason"] == "critical_lag_self_managed"
