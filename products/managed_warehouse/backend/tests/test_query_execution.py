from contextlib import nullcontext
from uuid import UUID

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import HogQLQuery

from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.timings import HogQLTimings

from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner, ExecutionMode
from posthog.models import Organization, Team, User

from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseTableNames,
    ManagedWarehouseTeamMembership,
)
from products.managed_warehouse.backend.query_execution import execute_managed_trino_query, validate_managed_trino_query


@pytest.fixture
def team() -> Team:
    return Team(id=7, organization_id=UUID("00000000-0000-0000-0000-000000000001"))


def test_default_requests_keep_normal_execution_without_evaluating_the_flag(team: Team) -> None:
    runner = object.__new__(HogQLQueryRunner)
    runner.query = HogQLQuery(query="SELECT 1")
    runner.team = team
    runner.user = User(id=9)
    runner._direct_connection_validated = False
    with patch("posthoganalytics.feature_enabled", side_effect=AssertionError("default query evaluated hosted flag")):
        runner._validate_direct_connection()
    assert runner.query.executionTarget is None


@pytest.mark.parametrize("flag_result", [False, None, RuntimeError("flag unavailable")])
def test_disabled_target_rejects_cached_requests(team: Team, flag_result: object) -> None:
    runner = object.__new__(HogQLQueryRunner)
    runner.query = HogQLQuery(query="SELECT 1", executionTarget="managed_trino")
    runner.team = team
    runner.user = User(id=9)
    with (
        patch(
            "posthoganalytics.feature_enabled",
            side_effect=flag_result if isinstance(flag_result, Exception) else None,
            return_value=flag_result,
        ),
        patch.object(AnalyticsQueryRunner, "run") as cached_run,
        pytest.raises(ExposedHogQLError, match="not enabled"),
    ):
        runner.run(execution_mode=ExecutionMode.CACHE_ONLY_NEVER_CALCULATE)
    cached_run.assert_not_called()


@pytest.mark.parametrize(
    "user, connection_id, raw", [(None, None, False), (User(id=9), "external-source", False), (User(id=9), None, True)]
)
def test_hosted_target_rejects_unauthenticated_and_external_modes(
    team: Team, user: User | None, connection_id: str | None, raw: bool
) -> None:
    with patch("posthoganalytics.feature_enabled", return_value=True), pytest.raises(ExposedHogQLError):
        validate_managed_trino_query(
            HogQLQuery(query="SELECT 1", connectionId=connection_id, sendRawQuery=raw), team, user
        )


@pytest.mark.django_db
def test_live_query_binds_values_and_uses_hosted_service_credentials(team: Team) -> None:
    organization = Organization.objects.create(id=team.organization_id, name="Example organization")
    team = Team.objects.create(organization=organization)
    user = User.objects.create(email="reader@example.com")
    membership = ManagedWarehouseTeamMembership(
        team_id=team.pk,
        organization_id=str(organization.pk),
        schema_name="production",
        enabled=True,
        backfill_enabled=True,
        table_names=ManagedWarehouseTableNames(
            events_table="events_example", persons_table="persons_example", data_imports_schema="imports_example"
        ),
        earliest_event_date=None,
    )
    cursor = MagicMock()
    cursor.fetchmany.return_value = [("quoted ' value",)]
    cursor.description = [("value", "varchar")]
    connection = MagicMock()
    connection.cursor.return_value = cursor
    with (
        patch("posthoganalytics.feature_enabled", return_value=True),
        patch(
            "products.managed_warehouse.backend.trino_compiler.get_ready_trino_catalog_name",
            return_value="example_catalog",
        ),
        patch("products.managed_warehouse.backend.trino_compiler.get_org_team_membership", return_value=membership),
        patch("products.managed_warehouse.backend.cp_teams.list_org_teams", return_value=[]),
        patch(
            "products.managed_warehouse.backend.query_execution.connect_managed_warehouse_trino",
            return_value=nullcontext(connection),
        ) as connect,
    ):
        response = execute_managed_trino_query(
            HogQLQuery(
                query="SELECT {value} AS value", values={"value": "quoted ' value"}, executionTarget="managed_trino"
            ),
            team=team,
            user=user,
            user_access_control=None,
            settings=HogQLGlobalSettings(),
            timings=HogQLTimings(),
            limit_context=LimitContext.QUERY,
        )
    connect.assert_called_once_with(
        str(team.organization_id), principal=f"posthog:sql-editor:team:{team.pk}:user:{user.pk}"
    )
    cursor.execute.assert_called_once_with('SELECT ? AS "value" LIMIT 50000', ["quoted ' value"])
    cursor.close.assert_called_once()
    assert response.results == [("quoted ' value",)]
    assert response.columns == ["value"]
