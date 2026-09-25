import uuid
import datetime as dt
from contextlib import contextmanager

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc.activities import cleanup_orphan_slots_activity
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.config import PostgresCDCConfig

pytestmark = pytest.mark.django_db

_ACTIVITIES = "products.warehouse_sources.backend.temporal.data_imports.cdc.activities"
_BILLING_EXPIRY = "products.warehouse_sources.backend.temporal.data_imports.cdc.billing_expiry"


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


def _mock_adapter(*, lag_bytes=0, retention_cap_mb=None, slot_survives_drop=False):
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
    adapter.slot_exists.return_value = slot_survives_drop
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
        patch("products.data_warehouse.backend.logic.data_load.service.pause_external_data_schedule"),
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


def test_deleted_source_purges_shadow_buffer_prefixes(team):
    # destroy() defers all external reaping to the sweep, so the sweep must purge the
    # deleted source's buffer prefixes — including soft-deleted CDC schema rows.
    source = _create_source(team, deleted=True, job_inputs=_cdc_job_inputs())
    schema = _create_cdc_schema(team, source)
    schema.deleted = True
    schema.save()

    adapter = _mock_adapter()
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.cdc.activities.purge_buffer_prefix"
    ) as mock_purge:
        _run(adapter)

    assert [call.args[1] for call in mock_purge.call_args_list] == [str(schema.id)]


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


@pytest.mark.parametrize(
    "reason, lag_mb, cleared",
    [
        ("critical_lag_self_managed", 10, True),
        ("critical_lag_self_managed", 1500, False),
        ("auth_failed", 10, False),
    ],
)
def test_self_managed_lag_marker_clears_once_lag_recovers(team, reason, lag_mb, cleared):
    source = _create_source(team, job_inputs=_cdc_job_inputs(management="self_managed"))
    source.status = ExternalDataSource.Status.ERROR
    source.save()
    schema = _create_cdc_schema(team, source)
    schema.sync_type_config = {**schema.sync_type_config, "cdc_broken": {"reason": reason}}
    schema.save()

    _run(_mock_adapter(lag_bytes=lag_mb * 1024 * 1024))

    schema.refresh_from_db()
    source.refresh_from_db()
    assert ("cdc_broken" not in schema.sync_type_config) is cleared
    assert (source.status == ExternalDataSource.Status.RUNNING) is cleared


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


def _job(team, source, schema, status, age):
    job = ExternalDataJob.objects.create(team_id=team.pk, pipeline=source, schema=schema, status=status, rows_synced=0)
    ExternalDataJob.objects.filter(id=job.id).update(created_at=dt.datetime.now(tz=dt.UTC) - age)


def _billing_blocked_schema(team, source, *, blocked_for, last_load_ago=None, other_outcome_ago=None):
    schema = _create_cdc_schema(team, source)
    ExternalDataSchema.objects.filter(id=schema.id).update(
        status=ExternalDataSchema.Status.BILLING_LIMIT_REACHED,
        last_synced_at=dt.datetime.now(tz=dt.UTC) - (last_load_ago or blocked_for),
    )
    if other_outcome_ago is not None:
        _job(team, source, schema, ExternalDataJob.Status.FAILED, other_outcome_ago)
    _job(team, source, schema, ExternalDataJob.Status.BILLING_LIMIT_REACHED, blocked_for)
    return schema


@pytest.mark.parametrize(
    "job_inputs, dropped, paused",
    [
        (_cdc_job_inputs(), True, True),
        (_cdc_job_inputs(auto_drop_slot=False), False, False),
        (_cdc_job_inputs(management="self_managed"), False, False),
    ],
)
def test_a_source_blocked_by_billing_past_buffer_retention_is_marked_broken(team, job_inputs, dropped, paused):
    source = _create_source(team, job_inputs=job_inputs)
    schema = _billing_blocked_schema(team, source, blocked_for=dt.timedelta(days=15))
    adapter = _mock_adapter()

    with patch(f"{_BILLING_EXPIRY}.is_team_limited", return_value=True):
        _, _, mock_pause = _run(adapter)

    assert adapter.drop_resources.called is dropped
    assert mock_pause.called is paused
    schema.refresh_from_db()
    assert schema.sync_type_config["cdc_broken"]["reason"] == "billing_limit_expired"
    adapter.get_lag_bytes.assert_not_called()


@pytest.mark.parametrize(
    "blocked_for, other_outcome_ago, team_limited, already_broken",
    [
        (dt.timedelta(days=3), None, True, False),
        (dt.timedelta(days=15), None, False, False),
        (dt.timedelta(days=15), None, True, True),
        (dt.timedelta(days=1), dt.timedelta(days=2), True, False),
    ],
)
def test_a_source_is_left_running_unless_billing_blocks_it_past_buffer_retention(
    team, blocked_for, other_outcome_ago, team_limited, already_broken
):
    source = _create_source(team, job_inputs=_cdc_job_inputs())
    schema = _billing_blocked_schema(
        team, source, blocked_for=blocked_for, last_load_ago=dt.timedelta(days=15), other_outcome_ago=other_outcome_ago
    )
    if already_broken:
        ExternalDataSchema.objects.filter(id=schema.id).update(
            sync_type_config={**schema.sync_type_config, "cdc_broken": {"reason": "auto_dropped_critical_lag"}}
        )
    adapter = _mock_adapter()

    with patch(f"{_BILLING_EXPIRY}.is_team_limited", return_value=team_limited):
        _run(adapter)

    adapter.drop_resources.assert_not_called()
    schema.refresh_from_db()
    assert (schema.sync_type_config.get("cdc_broken") or {}).get("reason") != "billing_limit_expired"


def test_a_slot_that_survives_the_drop_keeps_billing_capture_running(team):
    # drop_resources only logs a refused drop, so pausing capture on the strength of the call alone
    # would leave a live slot with nothing advancing it and the customer's WAL growing.
    source = _create_source(team, job_inputs=_cdc_job_inputs())
    schema = _billing_blocked_schema(team, source, blocked_for=dt.timedelta(days=15))
    adapter = _mock_adapter(slot_survives_drop=True)

    with patch(f"{_BILLING_EXPIRY}.is_team_limited", return_value=True):
        _, _, mock_pause = _run(adapter)

    adapter.drop_resources.assert_called_once()
    mock_pause.assert_not_called()
    source.refresh_from_db()
    assert source.status != ExternalDataSource.Status.ERROR
    schema.refresh_from_db()
    assert "cdc_broken" not in schema.sync_type_config


def test_a_job_from_another_table_does_not_defer_the_billing_stop(team):
    # The billing limit is team-wide, so only the blocked tables' own jobs end their blocked run: a
    # sibling table that fails, or a non-billable run that skips the billing check and completes,
    # would otherwise reset the clock on every tick and defer the stop indefinitely.
    source = _create_source(team, job_inputs=_cdc_job_inputs())
    schema = _billing_blocked_schema(team, source, blocked_for=dt.timedelta(days=15))
    sibling = _create_cdc_schema(team, source, name="events")
    _job(team, source, sibling, ExternalDataJob.Status.COMPLETED, dt.timedelta(hours=1))
    adapter = _mock_adapter()

    with patch(f"{_BILLING_EXPIRY}.is_team_limited", return_value=True):
        _run(adapter)

    adapter.drop_resources.assert_called_once()
    schema.refresh_from_db()
    assert schema.sync_type_config["cdc_broken"]["reason"] == "billing_limit_expired"


def test_a_failed_billing_check_still_checks_the_slots_lag(team):
    source = _create_source(team, job_inputs=_cdc_job_inputs())
    schema = _create_cdc_schema(team, source)
    adapter = _mock_adapter(lag_bytes=5000 * 1024 * 1024)

    with patch(f"{_ACTIVITIES}.blocked_past_buffer_retention", side_effect=RuntimeError("quota cache down")):
        _run(adapter)

    adapter.drop_resources.assert_called_once()
    schema.refresh_from_db()
    assert schema.sync_type_config["cdc_broken"]["reason"] == "auto_dropped_critical_lag"
