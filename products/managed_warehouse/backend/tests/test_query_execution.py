from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from uuid import UUID

import pytest
from unittest.mock import MagicMock, PropertyMock, patch

from django.test import override_settings

from posthog.schema import HogQLQuery, HogQLQueryModifiers, HogQLQueryResponse

from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.timings import HogQLTimings

from posthog.clickhouse.cluster import Workload
from posthog.clickhouse.query_tagging import AccessMethod, QueryTags, tags_context
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner, ExecutionMode
from posthog.models import Organization, Team, User

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseTableNames,
    ManagedWarehouseTeamMembership,
)
from products.managed_warehouse.backend.facade.query_labels import MANAGED_TRINO_RAW_QUERY_STATUS_LABEL
from products.managed_warehouse.backend.query_execution import execute_managed_trino_query, validate_managed_trino_query
from products.warehouse_sources.backend.facade.types import ManagedWarehouseSQLMode

CANARY_DOMAIN = "canary.dw.us.postwh.com"


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


def _canary_runner(
    team: Team, *, connection: bool, limit_context: LimitContext = LimitContext.QUERY
) -> HogQLQueryRunner:
    runner = object.__new__(HogQLQueryRunner)
    runner.query = HogQLQuery(
        query="SELECT 1",
        executionTarget=None if connection else "managed_trino",
        connectionId="source-1" if connection else None,
        sendRawQuery=True,
    )
    runner.team = team
    runner.user = User(id=9, distinct_id="user-9")
    runner.limit_context = limit_context
    runner._user_access_control = None
    runner.settings = HogQLGlobalSettings()
    runner.modifiers = HogQLQueryModifiers()
    runner.timings = HogQLTimings()
    runner.is_query_service = False
    runner.workload = Workload.DEFAULT
    runner._direct_connection_validated = False
    runner._direct_engine = None
    runner._managed_warehouse_sql_mode = None
    runner._trino_canary = False
    return runner


@contextmanager
def _canary_runner_boundaries(canary_domain: str = CANARY_DOMAIN) -> Iterator[tuple[MagicMock, MagicMock]]:
    source = MagicMock(
        direct_engine="postgres",
        has_managed_warehouse_prefix=True,
        managed_warehouse_sql_mode=ManagedWarehouseSQLMode.BUILT_IN,
    )
    module = "posthog.hogql_queries.hogql_query_runner"
    with (
        override_settings(MANAGED_WAREHOUSE_TRINO_CANARY_DOMAIN=canary_domain),
        tags_context(trigger=None, feature=None, alert_config_id=None),
        patch(f"{module}.validate_managed_trino_query"),
        patch(f"{module}.get_direct_connection_source", return_value=source),
        patch(f"{module}.get_adapter_for_source", return_value=MagicMock(engine="trino")),
        patch(f"{module}.tag_contains_user_hogql"),
        patch(f"{module}.execute_managed_trino_query") as managed_trino,
        patch(f"{module}.execute_hogql_query") as direct,
    ):
        yield managed_trino, direct


@pytest.mark.parametrize("connection", [False, True])
@pytest.mark.parametrize(
    "limit_context,flag,expected_variant",
    [
        (LimitContext.QUERY, True, "_trino_canary"),
        (LimitContext.QUERY_ASYNC, True, "_trino_canary"),
        (LimitContext.QUERY, False, ""),
        (LimitContext.EXPORT, True, ""),
        (LimitContext.SQL_ALERT, True, ""),
        (LimitContext.POSTHOG_AI, True, ""),
    ],
)
def test_canary_results_do_not_share_a_cache_entry_with_the_normal_lane(
    team: Team, connection: bool, limit_context: LimitContext, flag: bool, expected_variant: str
) -> None:
    runner = _canary_runner(team, connection=connection, limit_context=limit_context)
    with _canary_runner_boundaries(), patch("posthoganalytics.feature_enabled", return_value=flag):
        assert runner.get_cache_key_variant() == expected_variant


def test_queries_off_managed_trino_never_evaluate_the_canary_flag(team: Team) -> None:
    runner = object.__new__(HogQLQueryRunner)
    runner.query = HogQLQuery(query="SELECT 1")
    runner.team = team
    runner.user = User(id=9, distinct_id="user-9")
    runner.limit_context = LimitContext.QUERY
    runner._direct_connection_validated = False
    with (
        override_settings(MANAGED_WAREHOUSE_TRINO_CANARY_DOMAIN=CANARY_DOMAIN),
        patch("posthoganalytics.feature_enabled", side_effect=AssertionError("evaluated a flag")),
    ):
        assert runner.get_cache_key_variant() == ""


@pytest.mark.parametrize("connection", [False, True])
@pytest.mark.parametrize("first,later", [(True, False), (False, True)])
def test_the_cache_key_and_the_connection_share_one_canary_decision(
    team: Team, connection: bool, first: bool, later: bool
) -> None:
    runner = _canary_runner(team, connection=connection)
    with (
        _canary_runner_boundaries() as (managed_trino, direct),
        patch("posthog.hogql_queries.hogql_query_runner.use_trino_canary", side_effect=[first, later, later]) as decide,
    ):
        variants = {runner.get_cache_key_variant(), runner.get_cache_key_variant()}
        runner._calculate()
    assert variants == {"_trino_canary" if first else ""}
    assert decide.call_count == 1
    used_canary = direct.call_args.kwargs["trino_canary"] if connection else managed_trino.call_args.kwargs["canary"]
    assert used_canary is first


@pytest.mark.parametrize("canary", [False, True])
def test_a_managed_trino_run_connects_the_way_the_runner_decided(team: Team, canary: bool) -> None:
    user = User(id=9, distinct_id="user-9")
    cursor = MagicMock()
    cursor.fetchmany.return_value = [(1,)]
    cursor.description = [("value", "bigint")]
    connection = MagicMock()
    connection.cursor.return_value = cursor
    with (
        patch("posthoganalytics.feature_enabled", return_value=True),
        patch("products.managed_warehouse.backend.query_execution.enable_customer_warehouse_access", return_value=True),
        patch(
            "products.managed_warehouse.backend.query_execution.UserAccessControl.has_project_access",
            new_callable=PropertyMock,
            return_value=True,
        ),
        patch(
            "products.managed_warehouse.backend.query_execution.connect_managed_warehouse_trino",
            return_value=nullcontext(connection),
        ) as connect,
    ):
        execute_managed_trino_query(
            HogQLQuery(query="SELECT 1", executionTarget="managed_trino", sendRawQuery=True),
            team=team,
            user=user,
            user_access_control=None,
            settings=HogQLGlobalSettings(),
            timings=HogQLTimings(),
            limit_context=LimitContext.QUERY,
            canary=canary,
        )
    connect.assert_called_once_with(
        str(team.organization_id), principal=f"posthog:sql-editor:team:{team.pk}:user:{user.pk}", canary=canary
    )


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
    "limit_clause, limit_context, offset, row_count, expected_limit, has_more",
    [
        ("", LimitContext.QUERY, None, 1, 100, False),
        ("", LimitContext.QUERY, None, 101, 100, True),
        ("", LimitContext.QUERY, 200, 1, 100, False),
        (" LIMIT 1", LimitContext.SQL_ALERT, None, 1, 1, False),
        (" LIMIT 1", LimitContext.SQL_ALERT, None, 2, 1, True),
    ],
)
def test_live_query_binds_values_and_uses_hosted_service_credentials(
    team: Team,
    limit_clause: str,
    limit_context: LimitContext,
    offset: int | None,
    row_count: int,
    expected_limit: int,
    has_more: bool,
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
                offset=offset,
            ),
            team=team,
            user=user,
            user_access_control=None,
            settings=HogQLGlobalSettings(),
            timings=HogQLTimings(),
            limit_context=limit_context,
        )
    connect.assert_called_once_with(
        str(team.organization_id), principal=f"posthog:sql-editor:team:{team.pk}:user:{user.pk}", canary=False
    )
    cursor.execute.assert_called_once_with(
        f'SELECT ? AS "value" OFFSET {offset or 0} ROWS LIMIT {expected_limit + 1}', ["quoted ' value"]
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
    "tags,expected_access",
    [
        (QueryTags(browser_session=True), True),
        (QueryTags(access_method=AccessMethod.PERSONAL_API_KEY), False),
        # An export or alert runs as the user who made it, but in a worker with no session.
        (QueryTags(), False),
    ],
)
def test_hogql_results_that_may_read_raw_views_are_kept_from_callers_without_a_session(
    team: Team, tags: QueryTags, expected_access: bool
) -> None:
    def cache_payload_and_labels(tags: QueryTags) -> tuple[dict, list[str] | None]:
        runner = _canary_runner(team, connection=False)
        runner.query = HogQLQuery(query="SELECT * FROM raw_view", executionTarget="managed_trino")
        runner._modifiers_override_provided = False
        with (
            patch.object(HogQLQueryRunner, "_queried_table_names", new_callable=PropertyMock, return_value=set()),
            patch("posthoganalytics.feature_enabled", return_value=False),
            patch.object(AnalyticsQueryRunner, "get_cache_payload", return_value={}),
            patch(
                "products.managed_warehouse.backend.query_execution.enable_customer_warehouse_access", return_value=True
            ),
            patch(
                "products.managed_warehouse.backend.query_execution.UserAccessControl.has_project_access",
                new_callable=PropertyMock,
                return_value=True,
            ),
            patch("products.managed_warehouse.backend.query_execution.get_query_tags", return_value=tags),
        ):
            return runner.get_cache_payload(), runner.query_status_labels()

    browser_payload, _ = cache_payload_and_labels(QueryTags(browser_session=True))
    payload, labels = cache_payload_and_labels(tags)
    assert (payload == browser_payload) is expected_access
    assert labels == ([MANAGED_TRINO_RAW_QUERY_STATUS_LABEL] if expected_access else None)


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


@pytest.mark.django_db
def test_raw_query_sends_a_view_name_to_trino_unchanged() -> None:
    organization = Organization.objects.create(name="Example organization")
    team = Team.objects.create(organization=organization)
    user = User.objects.create_and_join(organization, "reader@example.com", "password")
    raw_view = {"kind": "HogQLQuery", "executionTarget": "managed_trino", "sendRawQuery": True, "query": "SELECT 1"}
    DataWarehouseSavedQuery.objects.create(team=team, name="raw_view", query=raw_view)
    cursor = MagicMock()
    cursor.fetchmany.return_value = [(1,)]
    cursor.description = [("id", "integer")]
    connection = MagicMock()
    connection.cursor.return_value = cursor
    with (
        patch("posthoganalytics.feature_enabled", return_value=True),
        patch(
            "products.managed_warehouse.backend.query_execution.connect_managed_warehouse_trino",
            return_value=nullcontext(connection),
        ),
    ):
        execute_managed_trino_query(
            HogQLQuery(query="select * from raw_view", executionTarget="managed_trino", sendRawQuery=True),
            team=team,
            user=user,
            user_access_control=None,
            settings=HogQLGlobalSettings(),
            timings=HogQLTimings(),
            limit_context=LimitContext.QUERY,
        )
    cursor.execute.assert_called_once_with("select * from raw_view")


@pytest.mark.parametrize("browser_session", [True, False])
@pytest.mark.django_db
def test_only_a_browser_session_runs_a_hogql_query_that_reads_a_raw_view(browser_session: bool) -> None:
    organization = Organization.objects.create(name="Example organization")
    team = Team.objects.create(organization=organization)
    user = User.objects.create_and_join(organization, "reader@example.com", "password")
    raw_view = {
        "kind": "HogQLQuery",
        "executionTarget": "managed_trino",
        "sendRawQuery": True,
        "query": "SELECT 1 AS id",
    }
    columns = {"id": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"}}
    DataWarehouseSavedQuery.objects.create(team=team, name="raw_view", query=raw_view, columns=columns)
    cursor = MagicMock()
    cursor.fetchmany.return_value = [(1,)]
    cursor.description = [("id", "integer")]
    connection = MagicMock()
    connection.cursor.return_value = cursor
    with (
        tags_context(browser_session=browser_session or None),
        patch("posthoganalytics.feature_enabled", return_value=True),
        patch("products.managed_warehouse.backend.cp_teams.list_org_teams", return_value=[]),
        patch(
            "products.managed_warehouse.backend.trino_compiler.get_ready_trino_catalog_name",
            return_value="org_catalog",
        ),
        patch(
            "products.managed_warehouse.backend.trino_compiler.get_org_team_membership",
            return_value=ManagedWarehouseTeamMembership(
                team_id=team.pk,
                organization_id=str(organization.pk),
                schema_name="production",
                enabled=True,
                backfill_enabled=True,
                table_names=ManagedWarehouseTableNames(
                    events_table="events_example",
                    persons_table="persons_example",
                    data_imports_schema="imports_example",
                ),
                earliest_event_date=None,
            ),
        ),
        patch(
            "products.managed_warehouse.backend.query_execution.connect_managed_warehouse_trino",
            return_value=nullcontext(connection),
        ),
    ):
        runner = HogQLQueryRunner(
            query=HogQLQuery(query="SELECT id FROM raw_view", executionTarget="managed_trino"),
            team=team,
            user=user,
            limit_context=LimitContext.EXPORT if not browser_session else LimitContext.QUERY,
        )
        if not browser_session:
            with pytest.raises(ExposedHogQLError, match="Open it from the SQL editor while signed in"):
                runner.calculate()
            cursor.execute.assert_not_called()
            return
        runner.calculate()
    assert cursor.execute.call_args.args[0].startswith("WITH __ph_rv_0 AS (\nSELECT 1 AS id\n)")
