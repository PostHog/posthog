import dataclasses

import pytest
from posthog.test.base import BaseTest

from posthog.schema import DateRange, FilterLogicalOperator, LogsQuery, PropertyGroupFilter, PropertyGroupFilterValue

from products.logs.backend import (
    tasks as internal_tasks,
    temporal as internal_temporal,
)
from products.logs.backend.facade import (
    api as facade_api,
    queries as facade_queries,
    tasks as facade_tasks,
    temporal as facade_temporal,
)
from products.logs.backend.facade.contracts import TeamLogsConfigData
from products.logs.backend.logs_query_runner import LogsQueryRunner
from products.logs.backend.models import DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEY, TeamLogsConfig


class TestTeamLogsConfigFacade(BaseTest):
    def test_get_or_create_returns_default_contract(self):
        data = facade_api.get_or_create_team_logs_config(self.team)

        assert isinstance(data, TeamLogsConfigData)
        assert data.team_id == self.team.id
        assert data.logs_distinct_id_attribute_key == DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEY
        assert TeamLogsConfig.objects.filter(team=self.team).exists()

    def test_get_or_create_is_idempotent(self):
        first = facade_api.get_or_create_team_logs_config(self.team)
        second = facade_api.get_or_create_team_logs_config(self.team)

        assert first == second
        assert TeamLogsConfig.objects.filter(team=self.team).count() == 1

    def test_update_persists_and_returns_contract(self):
        data = facade_api.update_team_logs_config(self.team, logs_distinct_id_attribute_key="userId")

        assert data == TeamLogsConfigData(team_id=self.team.id, logs_distinct_id_attribute_key="userId")
        assert TeamLogsConfig.objects.get(team=self.team).logs_distinct_id_attribute_key == "userId"

    def test_contract_is_frozen(self):
        data = facade_api.get_or_create_team_logs_config(self.team)

        with pytest.raises(dataclasses.FrozenInstanceError):
            data.logs_distinct_id_attribute_key = "mutated"  # type: ignore[misc]  # ty: ignore[invalid-assignment]


class TestLogsQueryFacade(BaseTest):
    def _query(self) -> LogsQuery:
        return LogsQuery(
            dateRange=DateRange(date_from="2024-01-10T00:00:00Z", date_to="2024-01-15T23:59:59Z"),
            serviceNames=[],
            severityLevels=[],
            filterGroup=PropertyGroupFilter(
                type=FilterLogicalOperator.AND_,
                values=[PropertyGroupFilterValue(type=FilterLogicalOperator.AND_, values=[])],
            ),
        )

    def test_runner_class_is_reexported_identically(self):
        assert facade_queries.LogsQueryRunner is LogsQueryRunner

    def test_build_matches_direct_construction(self):
        built = facade_queries.build_logs_query_runner(self._query(), self.team)
        direct = LogsQueryRunner(query=self._query(), team=self.team)

        assert type(built) is LogsQueryRunner
        assert built.to_query() == direct.to_query()


class TestWiringSurfaces(BaseTest):
    def test_temporal_surface_reexports_same_objects(self):
        assert facade_temporal.WORKFLOWS is internal_temporal.WORKFLOWS
        assert facade_temporal.ACTIVITIES is internal_temporal.ACTIVITIES
        assert facade_temporal.LogsAlertCheckWorkflow is internal_temporal.LogsAlertCheckWorkflow

    def test_celery_task_surface_and_registered_name(self):
        assert facade_tasks.logs_alert_events_cleanup_task is internal_tasks.logs_alert_events_cleanup_task
        # Core's beat schedule depends on this registration name staying stable.
        assert (
            facade_tasks.logs_alert_events_cleanup_task.name
            == "products.logs.backend.tasks.logs_alert_events_cleanup_task"
        )
