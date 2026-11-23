import pytest
from posthog.test.base import BaseTest
from unittest import mock

from posthog.models import Team

from products.warehouse_sources.backend.facade.staff import stop_schema_syncing_for_staff, syncing_schema_ids_for_staff
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
        temporal = mock.MagicMock()
        temporal.get_schedule_handle.return_value.pause = mock.AsyncMock()

        with (
            mock.patch(TEMPORAL_CLIENT, return_value=temporal),
            mock.patch(TEARDOWN) as teardown,
            self.captureOnCommitCallbacks(execute=True),
        ):
            assert stop_schema_syncing_for_staff(mine, team_ids=[self.team.pk]) is True
            assert stop_schema_syncing_for_staff(mine, team_ids=[self.team.pk]) is False
            assert stop_schema_syncing_for_staff(theirs, team_ids=[self.team.pk]) is False

        temporal.get_schedule_handle.assert_called_once_with(mine)
        temporal.get_schedule_handle.return_value.pause.assert_awaited_once()
        assert syncing_schema_ids_for_staff([self.team.pk, other_team.pk]) == [theirs]
        assert [call.kwargs["schema_id"] for call in teardown.call_args_list] == [mine]

    def test_a_schedule_temporal_cannot_pause_keeps_syncing(self) -> None:
        schema_id = self._schema(self.team)
        temporal = mock.MagicMock()
        temporal.get_schedule_handle.return_value.pause = mock.AsyncMock(side_effect=RuntimeError("unavailable"))

        with mock.patch(TEMPORAL_CLIENT, return_value=temporal), pytest.raises(RuntimeError):
            stop_schema_syncing_for_staff(schema_id, team_ids=[self.team.pk])

        assert syncing_schema_ids_for_staff([self.team.pk]) == [schema_id]
