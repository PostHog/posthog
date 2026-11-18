import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast

import pytest
import time_machine
from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import (
    CachedMetricsQueryResponse,
    DashboardFilter,
    DateRange,
    EventPropertyFilter,
    GoalLine,
    HogQLQuery,
    HogQLQueryResponse,
    MetricsDashboardVariable,
    MetricsDashboardVariableSelection,
    MetricsDisplaySettings,
    MetricsQuery,
    MetricsQueryClause,
    MetricsQueryFilter,
    MetricsQueryGroupBy,
    MetricsQueryResponse,
    MetricsYAxisSettings,
    QueryStatus,
)

from posthog.clickhouse.client.execute import KillSwitchLevel
from posthog.clickhouse.client.execute_async import QueryStatusManager
from posthog.clickhouse.client.limit import (
    ConcurrencyLimitExceeded,
    ConcurrencySlot,
    RateLimit,
    get_app_dashboard_queries_rate_limiter,
    get_app_org_rate_limiter,
)
from posthog.constants import AvailableFeature
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode, QueryRunner
from posthog.models import User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.shared_link_user import SharedLinkUser

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.access_control.backend.models.access_control import AccessControl
from products.metrics.backend.facade.enums import AttributeScope, FilterOp, MetricAggregation, MetricType
from products.metrics.backend.hogql_queries.metrics_query_runner import MetricsQueryRunner
from products.metrics.backend.tests._seeder import seed_metric
from products.product_analytics.backend.facade.models import Insight


class TestMetricsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _runner(self, query: MetricsQuery) -> MetricsQueryRunner:
        return MetricsQueryRunner(query=query, team=self.team)

    @parameterized.expand([("fixed", "minute"), ("dashboard_variable", "$window")])
    def test_translates_schema_node_to_facade_request(self, _name: str, interval: str) -> None:
        query = MetricsQuery(
            clauses=[
                MetricsQueryClause(
                    name="a",
                    metricName="http_requests_total",
                    aggregation="histogram_quantile",
                    metricType="histogram",
                    quantile=0.95,
                    filters=[MetricsQueryFilter(key="container", op="eq", value="capture", scope="attribute")],
                    groupBy=[MetricsQueryGroupBy(key="namespace")],
                )
            ],
            dateRange=DateRange(date_from="2026-09-19T00:00:00Z", date_to="2026-09-19T01:00:00Z"),
            interval=interval,
            formula=None,
        )

        runner = self._runner(query)
        runner.apply_dashboard_filters(
            DashboardFilter(
                metricVariables=[
                    MetricsDashboardVariable(
                        name="window", source="custom", current=MetricsDashboardVariableSelection(values=["1m"])
                    )
                ]
            )
        )
        request = runner._to_request()

        clause = request.clauses[0]
        assert clause.metric_name == "http_requests_total"
        assert clause.metric_type is MetricType.HISTOGRAM
        assert clause.aggregation is MetricAggregation.HISTOGRAM_QUANTILE
        assert clause.quantile == 0.95
        assert clause.filters[0].op is FilterOp.EQ
        assert clause.filters[0].scope is AttributeScope.ATTRIBUTE
        assert clause.group_by[0].scope is AttributeScope.AUTO
        assert request.interval == "minute"
        assert (request.date_to - request.date_from) == dt.timedelta(hours=1)

    def test_sql_tiles_check_the_budget_and_load_all_options_before_taking_a_concurrency_slot(self) -> None:
        events: list[str] = []

        @contextmanager
        def slot(*args: Any, **kwargs: Any) -> Iterator[None]:
            events.append("slot")
            yield

        def fill(*args: Any, variables: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            events.append("options")
            return variables

        runner = MetricsQueryRunner(
            query=MetricsQuery(clauses=[], language="sql", sql="SELECT now() AS time, 1 AS value WHERE 'a' IN $job"),
            team=self.team,
        )
        runner.apply_dashboard_filters(
            DashboardFilter(
                metricVariables=[
                    MetricsDashboardVariable(
                        name="job",
                        source="sql",
                        query="SELECT 'a'",
                        includeAll=True,
                        current=MetricsDashboardVariableSelection(values=[], all=True),
                    )
                ]
            )
        )
        with (
            patch("products.metrics.backend.hogql_queries.metrics_query_runner.get_query_tag_value", return_value=True),
            patch.object(
                MetricsQueryRunner, "_enforce_api_queries_budget", side_effect=lambda: events.append("budget")
            ),
            patch("posthog.hogql_queries.query_runner.app_org_concurrency_slot", side_effect=slot),
            patch("products.metrics.backend.hogql_queries.metrics_query_runner.fill_all_values", side_effect=fill),
            patch("products.metrics.backend.hogql_queries.metrics_query_runner.substitute_sql") as substitute,
            patch("products.metrics.backend.hogql_queries.metrics_query_runner.run_metrics_sql", return_value=[]),
        ):
            substitute.return_value.unresolved = ()
            runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)

        assert events.index("budget") < events.index("options") < events.index("slot")

    def test_default_date_range_is_last_24_hours(self) -> None:
        query = MetricsQuery(
            clauses=[MetricsQueryClause(name="a", metricName="http_requests_total", aggregation="sum")]
        )

        request = self._runner(query)._to_request()

        assert (request.date_to - request.date_from) == dt.timedelta(hours=24)

    @time_machine.travel("2026-09-19T12:00:00Z", tick=False)
    def test_calculate_returns_one_series_per_group(self) -> None:
        base = dt.datetime(2026, 9, 19, 11, 30, tzinfo=dt.UTC)
        for container, value in (("capture", 5.0), ("ingestion", 7.0)):
            seed_metric(
                team_id=self.team.pk,
                metric_name="queue_depth",
                metric_type="gauge",
                points=[(base + dt.timedelta(minutes=i), value) for i in range(3)],
                labels={"container": container},
            )

        query = MetricsQuery(
            clauses=[
                MetricsQueryClause(
                    name="a",
                    metricName="queue_depth",
                    aggregation="sum",
                    groupBy=[MetricsQueryGroupBy(key="container")],
                )
            ],
            dateRange=DateRange(date_from="2026-09-19T11:00:00Z", date_to="2026-09-19T12:00:00Z"),
        )

        response = self._runner(query).calculate()

        by_container = {series.labels.get("container"): series for series in response.results}
        assert set(by_container) == {"capture", "ingestion"}
        assert max(point.value for point in by_container["capture"].points if point.value is not None) == 5.0
        assert max(point.value for point in by_container["ingestion"].points if point.value is not None) == 7.0

    def test_generic_query_endpoint_accepts_metrics_query(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.pk}/query/",
            {
                "query": {
                    "kind": "MetricsQuery",
                    "clauses": [{"name": "a", "metricName": "queue_depth", "aggregation": "sum"}],
                }
            },
        )

        assert response.status_code == 200, response.json()
        assert "results" in response.json()

    @parameterized.expand([("unknown_alias", "a / b", None), ("non_finite_literal", "9" * 400, "Use a smaller number")])
    def test_generic_query_endpoint_rejects_invalid_formula_before_querying(
        self, _name: str, formula: str, expected_message: str | None
    ) -> None:
        with patch("products.metrics.backend.facade.api.build_metric_query_runner") as build_runner:
            build_runner.return_value.run.return_value = []
            response = self.client.post(
                f"/api/projects/{self.team.pk}/query/",
                {
                    "query": {
                        "kind": "MetricsQuery",
                        "clauses": [{"name": "a", "metricName": "queue_depth", "aggregation": "sum"}],
                        "formula": formula,
                    }
                },
            )

            assert response.status_code == 400, response.json()
            if expected_message is not None:
                assert expected_message in response.json()["detail"]
            build_runner.assert_not_called()

    @parameterized.expand([("web", {}), ("mcp", {"X-PostHog-Client": "mcp"})])
    def test_insight_saves_with_metrics_query(self, _name: str, client_headers: dict[str, str]) -> None:
        query = {
            "kind": "MetricsQuery",
            "clauses": [{"name": "a", "metricName": "queue_depth", "aggregation": "sum"}],
            "dateRange": {"date_from": "-24h"},
        }
        response = self.client.post(
            f"/api/projects/{self.team.pk}/insights/",
            {"name": "queue depth", "saved": True, "query": query},
            format="json",
            headers=client_headers,
        )

        assert response.status_code == 201, response.json()
        assert response.json()["query"]["kind"] == "MetricsQuery"

        update_response = self.client.patch(
            f"/api/projects/{self.team.pk}/insights/{response.json()['id']}/",
            {"query": query},
            format="json",
            headers=client_headers,
        )

        assert update_response.status_code == 200, update_response.json()
        assert update_response.json()["query"] == response.json()["query"]

        with_values = {**query, "variables": {"job": {"values": ["api"]}}}
        rejected_create = self.client.post(
            f"/api/projects/{self.team.pk}/insights/",
            {"name": "queue depth", "saved": True, "query": with_values},
            format="json",
            headers=client_headers,
        )
        rejected_update = self.client.patch(
            f"/api/projects/{self.team.pk}/insights/{response.json()['id']}/",
            {"query": with_values},
            format="json",
            headers=client_headers,
        )

        for rejected in (rejected_create, rejected_update):
            assert rejected.status_code == 400, rejected.json()
            assert "can't store variable values" in str(rejected.json())

    def test_validate_query_runner_access_granted(self) -> None:
        query = MetricsQuery(clauses=[MetricsQueryClause(name="a", metricName="queue_depth", aggregation="sum")])

        assert self._runner(query).validate_query_runner_access(self.user) is True

    def test_validate_query_runner_access_denied_without_feature_flag(self) -> None:
        query = MetricsQuery(clauses=[MetricsQueryClause(name="a", metricName="queue_depth", aggregation="sum")])

        with patch("posthoganalytics.feature_enabled", return_value=False):
            with pytest.raises(UserAccessControlError):
                self._runner(query).validate_query_runner_access(self.user)

    def test_calculate_denied_for_shared_link_viewer_without_feature_flag(self) -> None:
        # Shared-link renders execute with an anonymous SharedLinkUser, which skips
        # validate_query_runner_access — the flag gate must also hold at calculation time.
        sharing_config = SharingConfiguration.objects.create(team=self.team, enabled=True)
        query = MetricsQuery(clauses=[MetricsQueryClause(name="a", metricName="queue_depth", aggregation="sum")])
        runner = MetricsQueryRunner(query=query, team=self.team, user=cast(User, SharedLinkUser(sharing_config)))

        with patch("posthoganalytics.feature_enabled", return_value=False):
            with pytest.raises(UserAccessControlError):
                runner.calculate()

    def test_calculate_allowed_for_shared_link_viewer_with_feature_flag(self) -> None:
        sharing_config = SharingConfiguration.objects.create(team=self.team, enabled=True)
        query = MetricsQuery(clauses=[MetricsQueryClause(name="a", metricName="queue_depth", aggregation="sum")])
        runner = MetricsQueryRunner(query=query, team=self.team, user=cast(User, SharedLinkUser(sharing_config)))

        assert runner.calculate().results is not None

    @parameterized.expand([("cold_cache", False), ("warm_cache", True)])
    def test_shared_link_run_without_telemetry_opt_in_is_denied(self, _name: str, warm_cache: bool) -> None:
        sharing_config = SharingConfiguration.objects.create(team=self.team, enabled=True)
        query = MetricsQuery(clauses=[MetricsQueryClause(name="a", metricName="queue_depth", aggregation="sum")])
        if warm_cache:
            MetricsQueryRunner(query=query, team=self.team).run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
        runner = MetricsQueryRunner(query=query, team=self.team)

        with pytest.raises(UserAccessControlError):
            runner.run(
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
                user=cast(User, SharedLinkUser(sharing_config)),
            )

    def test_shared_link_run_with_telemetry_opt_in_returns_results(self) -> None:
        sharing_config = SharingConfiguration.objects.create(
            team=self.team, enabled=True, settings={"allowTelemetry": True}
        )
        query = MetricsQuery(clauses=[MetricsQueryClause(name="a", metricName="queue_depth", aggregation="sum")])
        runner = MetricsQueryRunner(query=query, team=self.team)

        response = runner.run(
            execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE,
            user=cast(User, SharedLinkUser(sharing_config)),
        )

        assert isinstance(response, MetricsQueryResponse | CachedMetricsQueryResponse)
        assert response.results is not None

    @parameterized.expand([("without_opt_in", None, False), ("with_opt_in", {"allowTelemetry": True}, True)])
    @time_machine.travel("2026-09-19T12:00:00Z", tick=False)
    def test_shared_link_refresh_returns_metrics_only_with_the_telemetry_opt_in(
        self, _name: str, sharing_settings: dict | None, expect_results: bool
    ) -> None:
        seed_metric(
            team_id=self.team.pk,
            metric_name="queue_depth",
            metric_type="gauge",
            points=[(dt.datetime(2026, 9, 19, 11, 30, tzinfo=dt.UTC), 5.0)],
        )
        insight = Insight.objects.create(
            team=self.team,
            created_by=self.user,
            query=MetricsQuery(
                clauses=[MetricsQueryClause(name="a", metricName="queue_depth", aggregation="sum")],
                dateRange=DateRange(date_from="2026-09-19T11:00:00Z", date_to="2026-09-19T12:00:00Z"),
            ).model_dump(exclude_none=True),
        )
        sharing_config = SharingConfiguration.objects.create(
            team=self.team, insight=insight, enabled=True, settings=sharing_settings
        )
        self.client.logout()

        response = self.client.get(
            f"/api/environments/{self.team.id}/insights/{insight.id}/",
            {"sharing_access_token": sharing_config.access_token, "refresh": "blocking"},
        )

        assert response.status_code == 200, response.content
        assert bool(response.json().get("result")) is expect_results, response.json()

    def test_validate_query_runner_access_denied_without_resource_access(self) -> None:
        AccessControl.objects.create(team=self.team, resource="metrics", access_level="none")
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        query = MetricsQuery(clauses=[MetricsQueryClause(name="a", metricName="queue_depth", aggregation="sum")])

        with pytest.raises(UserAccessControlError):
            self._runner(query).validate_query_runner_access(self.user)

    @parameterized.expand(
        [
            (["query:read"], "queue_depth", 403),
            (["query:read", "metrics:read"], "queue_depth", 200),
            # A derived metric reads spans or logs, so the token also needs that source's scope.
            (["query:read", "metrics:read"], "posthog.derived.spans.requests", 403),
            (["query:read", "metrics:read", "tracing:read"], "posthog.derived.spans.requests", 200),
            (["query:read", "metrics:read"], "posthog.derived.logs.records", 403),
            (["query:read", "metrics:read", "logs:read"], "posthog.derived.logs.records", 200),
        ]
    )
    def test_query_endpoint_scope_parity_for_api_keys(
        self, scopes: list[str], metric_name: str, expected_status: int
    ) -> None:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="test", user=self.user, secure_value=hash_key_value(value), scopes=scopes)

        response = self.client.post(
            f"/api/projects/{self.team.pk}/query/",
            {
                "query": {
                    "kind": "MetricsQuery",
                    "clauses": [{"name": "a", "metricName": metric_name, "aggregation": "sum"}],
                }
            },
            HTTP_AUTHORIZATION=f"Bearer {value}",
        )

        assert response.status_code == expected_status, response.json()

    @parameterized.expand(
        [
            ("token_without_tracing_scope", ["query:read", "metrics:read"], True, 403),
            ("token_with_tracing_scope", ["query:read", "metrics:read", "tracing:read"], True, 200),
            ("user_without_tracing_access", None, False, 403),
        ]
    )
    def test_async_derived_results_need_access_to_the_source(
        self, _name: str, scopes: list[str] | None, has_source_access: bool, expected_status: int
    ) -> None:
        query = MetricsQuery(
            clauses=[MetricsQueryClause(name="a", metricName="posthog.derived.spans.requests", aggregation="sum")]
        )
        query_id = "derived-async-query"
        QueryStatusManager(query_id, self.team.pk).store_query_status(
            QueryStatus(
                id=query_id,
                team_id=self.team.pk,
                complete=True,
                labels=self._runner(query).query_status_labels(),
                results=["derived result"],
            )
        )
        headers = {}
        if scopes is not None:
            value = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                label="test", user=self.user, secure_value=hash_key_value(value), scopes=scopes
            )
            headers["Authorization"] = f"Bearer {value}"
        if not has_source_access:
            AccessControl.objects.create(team=self.team, resource="tracing", access_level="none")
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
            ]
            self.organization.save()

        response = self.client.get(f"/api/projects/{self.team.pk}/query/{query_id}/", headers=headers)

        assert response.status_code == expected_status, response.content
        assert ("derived result" in response.content.decode()) == (expected_status == 200)

    def test_dashboard_date_filters_override_query_date_range(self) -> None:
        query = MetricsQuery(
            clauses=[MetricsQueryClause(name="a", metricName="queue_depth", aggregation="sum")],
            dateRange=DateRange(date_from="-24h"),
        )
        runner = self._runner(query)

        runner.apply_dashboard_filters(DashboardFilter(date_from="-7d", date_to="-1d"))

        assert runner.query.dateRange is not None
        assert runner.query.dateRange.date_from == "-7d"
        assert runner.query.dateRange.date_to == "-1d"

    def test_saved_dashboard_metric_filters_do_not_apply(self) -> None:
        own_filter = MetricsQueryFilter(key="namespace", op="eq", value="posthog")
        query = MetricsQuery(
            clauses=[
                MetricsQueryClause(name="a", metricName="queue_depth", aggregation="sum", filters=[own_filter]),
                MetricsQueryClause(name="b", metricName="requests_total", aggregation="rate"),
            ],
        )
        runner = self._runner(query)
        dashboard_filter = MetricsQueryFilter(key="service.name", op="eq", value="checkout")

        runner.apply_dashboard_filters(DashboardFilter(metricFilters=[dashboard_filter]))

        assert runner.query.clauses[0].filters == [own_filter]
        assert runner.query.clauses[1].filters is None

    def test_dashboard_property_filters_do_not_apply(self) -> None:
        query = MetricsQuery(clauses=[MetricsQueryClause(name="a", metricName="queue_depth", aggregation="sum")])
        runner = self._runner(query)

        runner.apply_dashboard_filters(
            DashboardFilter(properties=[EventPropertyFilter(key="$browser", operator="exact", value="Chrome")])
        )

        assert runner.query.clauses[0].filters is None

    def _cache_key_for(self, **kwargs) -> str:
        return self._runner(
            MetricsQuery(clauses=[MetricsQueryClause(name="a", metricName="queue_depth", aggregation="sum")], **kwargs)
        ).get_cache_key()

    @parameterized.expand(
        [
            ("chart_type", MetricsDisplaySettings(type="bar")),
            ("goal_lines", MetricsDisplaySettings(goalLines=[GoalLine(label="SLO", value=99.9)])),
            ("y_axis", MetricsDisplaySettings(yAxis=MetricsYAxisSettings(scale="log", min=10, max=100))),
            ("stat_summary", MetricsDisplaySettings(type="stat", statSummary="average")),
        ]
    )
    def test_display_settings_do_not_change_the_cache_key(self, _name: str, display: MetricsDisplaySettings) -> None:
        assert self._cache_key_for(display=display) == self._cache_key_for()

    def test_query_semantics_still_change_the_cache_key(self) -> None:
        assert self._cache_key_for(dateRange=DateRange(date_from="-7d")) != self._cache_key_for()


class TestTelemetryConcurrencyKey(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(patch("posthog.clickhouse.client.limit.TEST", False))
        self.enterContext(
            patch("posthog.clickhouse.client.execute.get_kill_switch_level", return_value=KillSwitchLevel.OFF)
        )
        self.enterContext(patch("posthog.rate_limit.team_is_allowed_to_bypass_throttle", return_value=False))
        held: list[tuple[RateLimit, ConcurrencySlot]] = []
        org_id = self.team.organization_id
        for i in range(20):
            org_limiter = get_app_org_rate_limiter()
            org_slot = org_limiter.use(org_id=org_id, team_id=self.team.pk, task_id=f"held-org-{i}")
            assert org_slot is not None
            held.append((org_limiter, org_slot))
        for i in range(6):
            dashboard_limiter = get_app_dashboard_queries_rate_limiter()
            dashboard_slot = dashboard_limiter.use(
                org_id=org_id, dashboard_id=1, team_id=self.team.pk, task_id=f"held-dashboard-{i}"
            )
            assert dashboard_slot is not None
            held.append((dashboard_limiter, dashboard_slot))
        for limiter, slot in held:
            self.addCleanup(limiter.release, slot)

    def _run(self, runner: QueryRunner, response: Any, *, flag_on: bool) -> None:
        with (
            patch.object(
                QueryRunner,
                "_team_flag_enabled_locally",
                side_effect=lambda key: flag_on and key == "telemetry-concurrency-key",
            ),
            patch.object(type(runner), "calculate", return_value=response),
        ):
            runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS, dashboard_id=1)

    def test_metrics_query_runs_while_the_org_dashboard_slots_are_full_when_flag_is_on(self) -> None:
        runner = MetricsQueryRunner(query=MetricsQuery(clauses=[]), team=self.team)

        self._run(runner, MetricsQueryResponse(results=[]), flag_on=True)

    @parameterized.expand([("metrics_flag_off", "metrics", False), ("analytics_flag_on", "hogql", True)])
    def test_query_is_rejected_while_the_org_dashboard_slots_are_full(
        self, _name: str, kind: str, flag_on: bool
    ) -> None:
        runner: QueryRunner
        response: Any
        if kind == "metrics":
            runner = MetricsQueryRunner(query=MetricsQuery(clauses=[]), team=self.team)
            response = MetricsQueryResponse(results=[])
        else:
            runner = HogQLQueryRunner(query=HogQLQuery(query="SELECT 1"), team=self.team)
            response = HogQLQueryResponse(results=[])

        with pytest.raises(ConcurrencyLimitExceeded):
            self._run(runner, response, flag_on=flag_on)
