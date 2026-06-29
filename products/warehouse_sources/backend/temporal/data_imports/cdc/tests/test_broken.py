import uuid
from contextlib import contextmanager

import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc.broken import mark_cdc_broken

pytestmark = pytest.mark.django_db


def _source(team):
    return ExternalDataSource.objects.create(
        team_id=team.pk,
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        status="Completed",
        source_type="Postgres",
    )


def _cdc_schema(team, source, *, name="users", should_sync=True, sync_type=ExternalDataSchema.SyncType.CDC):
    return ExternalDataSchema.objects.create(
        team_id=team.pk,
        source=source,
        name=name,
        sync_type=sync_type,
        should_sync=should_sync,
        sync_type_config={"cdc_mode": "streaming"},
    )


@contextmanager
def _mocked_boundaries():
    # Patch the true boundaries mark_cdc_broken reaches (Temporal, Kafka, analytics) at their source
    # modules, since broken.py imports the schedule/notification helpers lazily.
    with (
        patch("products.data_warehouse.backend.logic.data_load.service.pause_cdc_extraction_schedule") as mock_pause,
        patch("products.notifications.backend.facade.api.create_notification") as mock_notify,
        patch("posthoganalytics.capture") as mock_capture,
    ):
        yield mock_pause, mock_notify, mock_capture


def test_persists_broken_state_on_source_and_schemas(team):
    source = _source(team)
    schema = _cdc_schema(team, source)

    with _mocked_boundaries() as (mock_pause, mock_notify, mock_capture):
        mark_cdc_broken(source, "auto_dropped_critical_lag", "lag too high", lag_mb=4096.0)

    source.refresh_from_db()
    assert source.status == ExternalDataSource.Status.ERROR

    schema.refresh_from_db()
    assert schema.status == ExternalDataSchema.Status.FAILED
    assert schema.latest_error == "lag too high"
    broken = schema.sync_type_config["cdc_broken"]
    assert broken["reason"] == "auto_dropped_critical_lag"
    assert broken["lag_mb"] == 4096.0
    assert "at" in broken
    # The locked merge must preserve unrelated sync_type_config keys.
    assert schema.sync_type_config["cdc_mode"] == "streaming"

    mock_pause.assert_called_once_with(str(source.id))
    mock_notify.assert_called_once()
    mock_capture.assert_called_once()
    assert mock_capture.call_args.kwargs["event"] == "cdc marked broken"


@pytest.mark.parametrize("pause", [True, False])
def test_pause_flag_controls_schedule_pause(team, pause):
    source = _source(team)
    _cdc_schema(team, source)

    with _mocked_boundaries() as (mock_pause, _notify, _capture):
        mark_cdc_broken(source, "critical_lag_self_managed", "msg", pause=pause)

    assert mock_pause.called is pause


def test_only_active_cdc_schemas_are_marked(team):
    source = _source(team)
    active = _cdc_schema(team, source, name="active")
    paused = _cdc_schema(team, source, name="paused", should_sync=False)
    incremental = _cdc_schema(team, source, name="incr", sync_type=ExternalDataSchema.SyncType.INCREMENTAL)

    with _mocked_boundaries():
        mark_cdc_broken(source, "auto_dropped_critical_lag", "msg")

    active.refresh_from_db()
    assert "cdc_broken" in active.sync_type_config

    for untouched in (paused, incremental):
        untouched.refresh_from_db()
        assert "cdc_broken" not in untouched.sync_type_config
