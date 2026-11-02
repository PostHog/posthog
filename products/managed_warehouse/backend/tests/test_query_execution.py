from contextlib import nullcontext
from uuid import UUID

import pytest
from unittest.mock import MagicMock, PropertyMock, patch

from posthog.schema import HogQLQuery, HogQLQueryModifiers, HogQLQueryResponse

from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.timings import HogQLTimings

from posthog.clickhouse.query_tagging import AccessMethod, QueryTags
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner, ExecutionMode
from posthog.models import Organization, Team, User

from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseTableNames,
    ManagedWarehouseTeamMembership,
)
from products.managed_warehouse.backend.facade.query_labels import MANAGED_TRINO_RAW_QUERY_STATUS_LABEL
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
@pytest.mark.parametrize("raw", [False, True])
def test_disabled_target_rejects_cached_requests(team: Team, flag_result: object, raw: bool) -> None:
    runner = object.__new__(HogQLQueryRunner)
    runner.query = HogQLQuery(query="SELECT 1", executionTarget="managed_trino", sendRawQuery=raw)
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


@pytest.mark.django_db
@pytest.mark.parametrize(
    "user, connection_id, raw", [(None, None, False), (User(id=9), "external-source", False), (None, None, True)]
)
def test_hosted_target_rejects_unauthenticated_and_external_modes(
    team: Team, user: User | None, connection_id: str | None, raw: bool
) -> None:
    with patch("posthoganalytics.feature_enabled", return_value=True), pytest.raises(ExposedHogQLError):
        validate_managed_trino_query(
            HogQLQuery(query="SELECT 1", connectionId=connection_id, sendRawQuery=raw), team, user
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "limit_clause, limit_context, row_count, expected_limit, has_more",
    [
        ("", LimitContext.QUERY, 1, 100, False),
        ("", LimitContext.QUERY, 101, 100, True),
        (" LIMIT 1", LimitContext.SQL_ALERT, 1, 1, False),
        (" LIMIT 1", LimitContext.SQL_ALERT, 2, 1, True),
    ],
)
def test_live_query_binds_values_and_uses_hosted_service_credentials(
    team: Team, limit_clause: str, limit_context: LimitContext, row_count: int, expected_limit: int, has_more: bool
) -> None:
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
    cursor.fetchmany.return_value = [("quoted ' value",)] * row_count
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
                query="SELECT {value} AS value" + limit_clause,
                values={"value": "quoted ' value"},
                executionTarget="managed_trino",
            ),
            team=team,
            user=user,
            user_access_control=None,
            settings=HogQLGlobalSettings(),
            timings=HogQLTimings(),
            limit_context=limit_context,
        )
    connect.assert_called_once_with(
        str(team.organization_id), principal=f"posthog:sql-editor:team:{team.pk}:user:{user.pk}"
    )
    cursor.execute.assert_called_once_with(
        f'SELECT ? AS "value" OFFSET 0 ROWS LIMIT {expected_limit + 1}', ["quoted ' value"]
    )
    cursor.close.assert_called_once()
    assert response.results == [("quoted ' value",)] * min(row_count, expected_limit)
    assert response.hasMore is has_more
    assert response.limit == expected_limit
    assert response.columns == ["value"]


@pytest.mark.parametrize(
    "access_method,has_project_access,error",
    [(None, False, "access to this project"), *[(method, True, "browser session") for method in AccessMethod]],
)
@pytest.mark.django_db
def test_raw_target_rejects_unauthorized_callers_before_cached_results(
    team: Team, access_method: AccessMethod | None, has_project_access: bool, error: str
) -> None:
    runner = object.__new__(HogQLQueryRunner)
    runner.query = HogQLQuery(query="SELECT 1", executionTarget="managed_trino", sendRawQuery=True)
    runner.team = team
    runner.user = User(id=9)
    with (
        patch("posthoganalytics.feature_enabled", return_value=True),
        patch(
            "products.managed_warehouse.backend.query_execution.UserAccessControl.has_project_access",
            new_callable=PropertyMock,
            return_value=has_project_access,
        ),
        patch(
            "products.managed_warehouse.backend.query_execution.get_query_tags",
            return_value=QueryTags(access_method=access_method),
        ),
        patch.object(AnalyticsQueryRunner, "run") as cached_run,
        pytest.raises(ExposedHogQLError, match=error),
    ):
        runner.run(execution_mode=ExecutionMode.CACHE_ONLY_NEVER_CALCULATE)
    cached_run.assert_not_called()


@pytest.mark.parametrize(
    "sql", ['SELECT CAST(JSON \'{"ratio": "100%"}\' AS JSON) AS value', "DELETE FROM example_table"]
)
@pytest.mark.django_db
def test_raw_query_passes_native_sql_without_compilation(team: Team, sql: str) -> None:
    cursor = MagicMock()
    cursor.fetchmany.return_value = [("100%",)]
    cursor.description = [("value", "varchar")]
    connection = MagicMock()
    connection.cursor.return_value = cursor
    with (
        patch("posthoganalytics.feature_enabled", return_value=True),
        patch(
            "products.managed_warehouse.backend.query_execution.UserAccessControl.has_project_access",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch(
            "products.managed_warehouse.backend.query_execution.compile_hogql_to_trino_sql",
            side_effect=AssertionError("raw SQL reached the HogQL compiler"),
        ),
        patch(
            "products.managed_warehouse.backend.query_execution.connect_managed_warehouse_trino",
            return_value=nullcontext(connection),
        ) as connect,
    ):

        def execute() -> HogQLQueryResponse:
            runner = object.__new__(HogQLQueryRunner)
            runner.query = HogQLQuery(query=sql, executionTarget="managed_trino", sendRawQuery=True)
            runner.team = team
            runner.user = User(id=9)
            runner._user_access_control = None
            runner.settings = HogQLGlobalSettings()
            runner.modifiers = HogQLQueryModifiers()
            runner.timings = HogQLTimings()
            runner.limit_context = LimitContext.QUERY
            runner.is_query_service = True
            runner._direct_connection_validated = False
            with patch.object(runner, "_parse_query", side_effect=AssertionError("raw SQL reached the HogQL parser")):
                result = runner._calculate()
            assert runner.query_status_labels() == [MANAGED_TRINO_RAW_QUERY_STATUS_LABEL]
            return result

        if sql.startswith("DELETE"):
            with pytest.raises(ExposedHogQLError, match="read-only"):
                execute()
            connect.assert_not_called()
            return
        response = execute()
    cursor.execute.assert_called_once_with(sql)
    assert response.results == [("100%",)]
    assert response.clickhouse == sql
    assert response.hogql is None
