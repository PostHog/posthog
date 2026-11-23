import pytest
from posthog.test.base import BaseTest
from unittest import mock

from posthog.models import Team
from posthog.test.temporal_schedules import RecordingTemporal

from products.warehouse_sources.backend.facade.staff import (
    running_source_ids_for_staff,
    stop_schema_syncing_for_staff,
    stop_source_for_staff,
    syncing_schema_ids_for_staff,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

TEMPORAL_CLIENT = "products.data_warehouse.backend.logic.data_load.service.sync_connect"
TEARDOWN = "products.warehouse_sources.backend.tasks.cleanup_disabled_external_data_schema.delay"


class TestStopSchemaSyncing(BaseTest):
    def _schema(self, team: Team) -> str:
        source = ExternalDataSource.objects.create(team=team, source_type=ExternalDataSourceType.POSTGRES)
        return str(ExternalDataSchema.objects.create(team=team, source=source, name="orders", should_sync=True).id)

    def test_pauses_the_schedule_then_stops_syncing_and_the_running_sync_only_for_the_given_teams(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        mine, theirs = self._schema(self.team), self._schema(other_team)
        schema = ExternalDataSchema.objects.get(id=mine)
        ExternalDataJob.objects.create(
            team_id=self.team.pk, pipeline=schema.source, schema=schema, status=ExternalDataJob.Status.RUNNING
        )
        temporal = RecordingTemporal()
        torn_down: list[str] = []

        with (
            mock.patch(TEMPORAL_CLIENT, return_value=temporal),
            mock.patch(TEARDOWN, side_effect=lambda **task: torn_down.append(task["schema_id"])),
            self.captureOnCommitCallbacks(execute=True),
        ):
            assert stop_schema_syncing_for_staff(mine, team_id=self.team.pk) is True
            assert stop_schema_syncing_for_staff(mine, team_id=self.team.pk) is False
            assert stop_schema_syncing_for_staff(theirs, team_id=self.team.pk) is False

        assert temporal.paused == [(mine, None)]
        assert syncing_schema_ids_for_staff([self.team.pk, other_team.pk]) == [theirs]
        assert torn_down == [mine]

    def test_a_schedule_temporal_cannot_pause_keeps_syncing(self) -> None:
        schema_id = self._schema(self.team)
        temporal = RecordingTemporal(failing=frozenset({schema_id}))

        with mock.patch(TEMPORAL_CLIENT, return_value=temporal), pytest.raises(RuntimeError):
            stop_schema_syncing_for_staff(schema_id, team_id=self.team.pk)

        assert syncing_schema_ids_for_staff([self.team.pk]) == [schema_id]

    def test_stopping_a_source_pauses_its_cdc_extraction_and_its_syncing_of_new_tables(self) -> None:
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.POSTGRES, auto_sync_new_schemas=True
        )
        cdc_table = ExternalDataSchema.objects.create(
            team=self.team, source=source, name="orders", should_sync=True, sync_type=ExternalDataSchema.SyncType.CDC
        )
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        other = ExternalDataSource.objects.create(
            team=other_team, source_type=ExternalDataSourceType.POSTGRES, auto_sync_new_schemas=True
        )
        temporal = RecordingTemporal()

        with mock.patch(TEMPORAL_CLIENT, return_value=temporal):
            assert stop_source_for_staff(str(other.id), team_id=self.team.pk) is False
            assert stop_source_for_staff(str(source.id), team_id=self.team.pk) is True
            stop_schema_syncing_for_staff(str(cdc_table.id), team_id=self.team.pk)
            assert stop_source_for_staff(str(source.id), team_id=self.team.pk) is False

        assert (f"cdc-extraction-{source.id}", None) in temporal.paused
        assert running_source_ids_for_staff([self.team.pk, other_team.pk]) == [str(other.id)]
