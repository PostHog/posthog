from datetime import timedelta
from uuid import uuid4

import pytest
from unittest.mock import patch

from django.utils import timezone

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from products.data_warehouse.backend.facade.api import ScheduleReconcileResult
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.tasks.tasks import reconcile_drifted_schema_schedules

pytestmark = [pytest.mark.django_db]

RECONCILE = "products.data_warehouse.backend.logic.data_load.service.bulk_reconcile_external_data_schedules"


@pytest.fixture
def team():
    return create_team(organization=create_organization("test org"))


def _make_source(team, access_method=ExternalDataSource.AccessMethod.WAREHOUSE):
    return ExternalDataSource.objects.create(
        source_id=str(uuid4()),
        connection_id=str(uuid4()),
        destination_id=str(uuid4()),
        team=team,
        status="Completed",
        source_type="Postgres",
        access_method=access_method,
        job_inputs={},
    )


def _make_schema(team, source, *, last_synced_at, **kwargs):
    defaults = {
        "name": "TestSchema",
        "team_id": team.pk,
        "source_id": source.pk,
        "sync_type": ExternalDataSchema.SyncType.FULL_REFRESH,
        "sync_type_config": {},
        "should_sync": True,
        "status": ExternalDataSchema.Status.COMPLETED,
        "sync_frequency_interval": timedelta(hours=6),
        "sync_time_of_day": "00:00:00",
        "last_synced_at": last_synced_at,
    }
    defaults.update(kwargs)
    return ExternalDataSchema.objects.create(**defaults)


class TestReconcileDriftedSchemaSchedules:
    def test_reconciles_only_drifted_schemas(self, team):
        now = timezone.now()
        stale = now - timedelta(hours=13)  # older than 2x the 6h interval
        fresh = now - timedelta(hours=1)
        source = _make_source(team)
        direct_source = _make_source(team, access_method=ExternalDataSource.AccessMethod.DIRECT)

        drifted = _make_schema(team, source, last_synced_at=stale)

        # None of these should be picked up.
        _make_schema(team, source, last_synced_at=fresh)  # synced recently
        _make_schema(team, source, last_synced_at=stale, should_sync=False)  # disabled
        _make_schema(team, source, last_synced_at=stale, deleted=True)  # soft-deleted
        _make_schema(team, source, last_synced_at=stale, sync_type=ExternalDataSchema.SyncType.CDC)  # CDC
        _make_schema(team, direct_source, last_synced_at=stale)  # direct-query source, no schedule
        _make_schema(team, source, last_synced_at=stale, status=ExternalDataSchema.Status.FAILED)  # already surfaced
        _make_schema(
            team, source, last_synced_at=stale, sync_type_config={"admin_unpause_schedule_after_run": True}
        )  # deliberately paused by an admin
        _make_schema(team, source, last_synced_at=None)  # never synced

        with patch(RECONCILE, return_value=ScheduleReconcileResult()) as mock_reconcile:
            reconcile_drifted_schema_schedules()

        mock_reconcile.assert_called_once()
        passed = mock_reconcile.call_args.args[0]
        assert [s.id for s in passed] == [drifted.id]

    def test_no_call_when_nothing_drifted(self, team):
        source = _make_source(team)
        _make_schema(team, source, last_synced_at=timezone.now() - timedelta(hours=1))

        with patch(RECONCILE) as mock_reconcile:
            reconcile_drifted_schema_schedules()

        mock_reconcile.assert_not_called()
