import json
import datetime as dt

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.models import Team
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.metrics.backend.derived import DerivedMetricQueryRunner, derived_metrics_enabled
from products.metrics.backend.facade.api import list_metric_names, list_metric_picker_names, run_metric_query
from products.metrics.backend.facade.contracts import (
    METRICS_DERIVED_SERIES_FEATURE_FLAG,
    MetricFilter,
    MetricGroupBy,
    MetricQueryClause,
    MetricQueryRequest,
    MetricQueryTooManyRowsError,
    MetricSeries,
)
from products.metrics.backend.facade.enums import AttributeScope, FilterOp, MetricAggregation, MetricRangeFunction

REQUESTS = "posthog.derived.spans.requests"
ERRORS = "posthog.derived.spans.errors"
DURATION = "posthog.derived.spans.duration"
LOG_RECORDS = "posthog.derived.logs.records"

DATE_FROM = dt.datetime(2026, 6, 2, 8, 0, tzinfo=dt.UTC)
DATE_TO = dt.datetime(2026, 6, 2, 9, 0, tzinfo=dt.UTC)

SERVER, INTERNAL, CLIENT = 2, 1, 3
OK, ERROR = 0, 2

# (service, kind, is_root, duration_ms, status, http.route, deployment.environment)
# "web" has server spans, so its root internal span (a cron job) and its client child do not count.
# "worker" has no server spans, so its root spans count as requests and its child does not.
# "jobs" has server spans only in production, so its staging root span counts in staging.
SPANS = [
    ("web", SERVER, True, 10, OK, "/a", "production"),
    ("web", SERVER, True, 20, OK, "/a", "production"),
    ("web", SERVER, True, 30, OK, "/a", "production"),
    ("web", SERVER, True, 40, ERROR, "/a", "production"),
    ("web", CLIENT, False, 500, OK, None, "production"),
    ("web", INTERNAL, True, 900, OK, None, "production"),
    ("worker", INTERNAL, True, 100, OK, None, "production"),
    ("worker", INTERNAL, True, 300, ERROR, None, "production"),
    ("worker", INTERNAL, False, 700, ERROR, None, "production"),
    ("api", SERVER, True, 5, OK, "/b", "production"),
    ("jobs", SERVER, True, 15, OK, None, "production"),
    ("jobs", INTERNAL, True, 60, OK, None, "staging"),
]

# (service, severity)
LOGS = [("web", "info"), ("web", "info"), ("web", "error"), ("worker", "warn")]


def _flags(*enabled: str, derived_variant: str | bool | None = "test"):
    return patch.multiple(
        "posthoganalytics",
        feature_enabled=MagicMock(side_effect=lambda flag, *_, **__: flag in enabled),
        get_feature_flag=MagicMock(side_effect=lambda flag, *_, **__: derived_variant if flag in enabled else None),
    )


def _insert_spans(team_id: int) -> None:
    rows: list[str] = []
    for index, (service, kind, is_root, duration_ms, status, route, environment) in enumerate(SPANS):
        start = DATE_FROM + dt.timedelta(minutes=10, seconds=index)
        end = start + dt.timedelta(milliseconds=duration_ms)
        parent = "" if is_root else f"parent{index}"
        attributes = f"{{'http.route__str': '{route}'}}" if route else "{}"
        rows.append(
            f"('019e8756-0000-0000-0000-{index:012d}', {team_id}, 'trace{index}', 'span{index}', '{parent}', "
            f"'op', {kind}, '{start:%Y-%m-%d %H:%M:%S.%f}', '{end:%Y-%m-%d %H:%M:%S.%f}', "
            f"'{start:%Y-%m-%d %H:%M:%S.%f}', {status}, '{service}', {attributes}, "
            f"{{'deployment.environment': '{environment}'}})"
        )
    sync_execute(
        "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, timestamp, "
        "end_time, observed_timestamp, status_code, service_name, attributes_map_str, resource_attributes) VALUES "
        + ",".join(rows)
    )


def _insert_logs(team_id: int) -> None:
    rows = []
    for index, (service, severity) in enumerate(LOGS):
        timestamp = DATE_FROM + dt.timedelta(minutes=20, seconds=index)
        rows.append(
            {
                "team_id": team_id,
                "timestamp": f"{timestamp:%Y-%m-%d %H:%M:%S.%f}",
                "observed_timestamp": f"{timestamp:%Y-%m-%d %H:%M:%S.%f}",
                "service_name": service,
                "severity_text": severity,
                "body": "line",
            }
        )
    sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(row) for row in rows))


def _by_label(series: list[MetricSeries], key: str) -> dict[str, float | None]:
    return {s.labels.get(key, ""): s.points[0].value for s in series if s.points}


class TestDerivedMetricsQuery(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        _insert_spans(self.team.id)
        _insert_logs(self.team.id)

    def _run(
        self,
        metric_name: str,
        aggregation: MetricAggregation,
        *,
        quantile: float | None = None,
        group_by: tuple[str, ...] = ("service.name",),
        filters: tuple[MetricFilter, ...] = (),
        range_function: MetricRangeFunction | None = None,
    ) -> list[MetricSeries]:
        clause = MetricQueryClause(
            name="a",
            metric_name=metric_name,
            aggregation=aggregation,
            quantile=quantile,
            group_by=tuple(MetricGroupBy(key=key) for key in group_by),
            filters=filters,
            range_function=range_function,
        )
        request = MetricQueryRequest(clauses=(clause,), date_from=DATE_FROM, date_to=DATE_TO, interval="hour")
        return run_metric_query(team=self.team, request=request)

    @parameterized.expand(
        [
            ("requests", REQUESTS, MetricAggregation.SUM, None, None, {"web": 4, "worker": 2, "api": 1, "jobs": 1}),
            (
                "requests_increase",
                REQUESTS,
                MetricAggregation.INCREASE,
                None,
                None,
                {"web": 4, "worker": 2, "api": 1, "jobs": 1},
            ),
            # A service without errors keeps a zero series, so `errors / requests` keeps it.
            ("errors", ERRORS, MetricAggregation.SUM, None, None, {"web": 1, "worker": 1, "api": 0, "jobs": 0}),
            (
                "request_rate",
                REQUESTS,
                MetricAggregation.SUM,
                None,
                MetricRangeFunction.RATE,
                {"web": 4 / 3600, "worker": 2 / 3600, "api": 1 / 3600, "jobs": 1 / 3600},
            ),
            (
                "max_duration_ms",
                DURATION,
                MetricAggregation.MAX,
                None,
                None,
                {"web": 40, "worker": 300, "api": 5, "jobs": 15},
            ),
            (
                "p50_duration_ms",
                DURATION,
                MetricAggregation.HISTOGRAM_QUANTILE,
                0.5,
                None,
                {"web": 25, "worker": 200, "api": 5, "jobs": 15},
            ),
        ]
    )
    def test_span_series_per_service_match_the_fixtures(
        self,
        _name: str,
        metric_name: str,
        aggregation: MetricAggregation,
        quantile: float | None,
        range_function: MetricRangeFunction | None,
        expected: dict[str, float],
    ) -> None:
        with _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG):
            series = self._run(metric_name, aggregation, quantile=quantile, range_function=range_function)

        assert _by_label(series, "service.name") == expected

    def test_a_new_counter_selection_without_aggregation_counts_requests(self) -> None:
        # The picker sends `none` for a counter that the user has not aggregated yet.
        with _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG):
            series = self._run(REQUESTS, MetricAggregation.NONE, group_by=())

        assert _by_label(series, "service.name") == {"": 8}

    def test_root_span_fallback_follows_the_environment_filter(self) -> None:
        with _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG):
            series = self._run(
                REQUESTS,
                MetricAggregation.SUM,
                filters=(
                    MetricFilter(
                        key="deployment.environment",
                        op=FilterOp.EQ,
                        value="staging",
                        scope=AttributeScope.RESOURCE,
                    ),
                ),
            )

        assert _by_label(series, "service.name") == {"jobs": 1}

    def test_span_attribute_group_by_and_filter(self) -> None:
        with _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG):
            series = self._run(
                REQUESTS,
                MetricAggregation.SUM,
                group_by=("http.route",),
                filters=(MetricFilter(key="service.name", op=FilterOp.NEQ, value="worker"),),
            )

        assert _by_label(series, "http.route") == {"/a": 4, "/b": 1, "": 1}

    def test_log_records_per_severity(self) -> None:
        with _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG):
            series = self._run(
                LOG_RECORDS,
                MetricAggregation.SUM,
                group_by=("severity_text",),
                filters=(MetricFilter(key="service.name", op=FilterOp.EQ, value="web"),),
            )

        assert _by_label(series, "severity_text") == {"info": 2, "error": 1}

    def test_derived_series_stay_hidden_without_the_flag(self) -> None:
        with _flags("metrics"):
            series = self._run(REQUESTS, MetricAggregation.SUM)

        assert all(not s.points for s in series)

    def test_row_cap_raises_instead_of_dropping_series(self) -> None:
        with (
            _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG),
            patch("products.metrics.backend.derived._ROW_LIMIT", 2),
            self.assertRaises(MetricQueryTooManyRowsError),
        ):
            self._run(REQUESTS, MetricAggregation.SUM)

    @time_machine.travel(DATE_TO, tick=False)
    def test_names_list_derived_metrics_only_for_teams_with_spans_or_logs(self) -> None:
        empty_team = Team.objects.create(organization=self.organization, name="no telemetry")

        with _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG):
            names = {row["name"] for row in list_metric_names(team=self.team)}
            empty_names = {row["name"] for row in list_metric_names(team=empty_team)}

        assert {REQUESTS, ERRORS, DURATION, LOG_RECORDS} <= names
        assert not any(name.startswith("posthog.derived.") for name in empty_names)

    @time_machine.travel(DATE_TO, tick=False)
    def test_catalog_lookups_respect_the_limit_and_resolve_derived_names(self) -> None:
        with _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG):
            limited = list_metric_names(team=self.team, limit=1)
            limited_picker = list_metric_picker_names(team=self.team, limit=1)
            exact = list_metric_names(team=self.team, names=[REQUESTS, LOG_RECORDS])

        assert len(limited) == 1
        assert len(limited_picker) == 1
        assert {row["name"] for row in exact} == {REQUESTS, LOG_RECORDS}

    @time_machine.travel(DATE_TO, tick=False)
    def test_a_failed_presence_check_keeps_the_other_names(self) -> None:
        def fail_on_spans(*args, **kwargs):
            if kwargs["query"].select_from.table.chain == ["posthog", "trace_spans"]:
                raise TimeoutError("presence check timed out")
            return execute_hogql_query(*args, **kwargs)

        with (
            _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG),
            patch("products.metrics.backend.derived.execute_hogql_query", side_effect=fail_on_spans),
        ):
            names = {row["name"] for row in list_metric_picker_names(team=self.team)}

        with _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG):
            held = {row["name"] for row in list_metric_picker_names(team=self.team)}

        with (
            time_machine.travel(DATE_TO + dt.timedelta(minutes=1, seconds=1), tick=False),
            _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG),
        ):
            retried = {row["name"] for row in list_metric_picker_names(team=self.team)}

        assert LOG_RECORDS in names
        assert REQUESTS not in names
        # A failed answer is held for a minute, so polling does not re-run a probe that is timing out.
        assert REQUESTS not in held
        assert REQUESTS in retried

    def test_presence_answers_are_cached_by_outcome(self) -> None:
        empty_team = Team.objects.create(organization=self.organization, name="no telemetry yet")
        probes: list[dict] = []

        def record(*args, **kwargs):
            probes.append(kwargs)
            return execute_hogql_query(*args, **kwargs)

        def names_at(team: Team, at: dt.datetime) -> set[str]:
            with (
                time_machine.travel(at, tick=False),
                _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG),
                patch("products.metrics.backend.derived.execute_hogql_query", side_effect=record),
            ):
                return {row["name"] for row in list_metric_picker_names(team=team)}

        empty = names_at(empty_team, DATE_TO)
        _insert_spans(empty_team.id)
        held = names_at(empty_team, DATE_TO + dt.timedelta(seconds=59))
        arrived = names_at(empty_team, DATE_TO + dt.timedelta(minutes=1, seconds=1))
        probes_after_arrival = len(probes)
        kept = names_at(empty_team, DATE_TO + dt.timedelta(minutes=5))

        # An empty answer is re-checked after a minute, so new spans reach the picker without a five-minute wait.
        assert REQUESTS not in empty
        assert REQUESTS not in held
        assert REQUESTS in arrived
        # An answer with data keeps the longer TTL.
        assert REQUESTS in kept
        assert len(probes) == probes_after_arrival == 4
        assert {probe["settings"].max_execution_time for probe in probes} == {10}

    @parameterized.expand(
        [
            ("token_without_tracing_scope", ["metrics:read"], True, 403),
            ("token_with_tracing_scope", ["metrics:read", "tracing:read"], True, 200),
            ("user_without_tracing_access", None, False, 403),
        ]
    )
    def test_derived_queries_need_access_to_the_source(
        self, _name: str, scopes: list[str] | None, has_source_access: bool, expected_status: int
    ) -> None:
        if scopes is not None:
            value = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                label="test", user=self.user, secure_value=hash_key_value(value), scopes=scopes
            )
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {value}")

        with (
            _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG),
            patch(
                "products.access_control.backend.facade.user_access_control.UserAccessControl.check_access_level_for_resource",
                side_effect=lambda resource, *_, **__: resource != "tracing" or has_source_access,
            ),
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/metrics/query/",
                {
                    "query": {
                        "metricName": REQUESTS,
                        "aggregation": "sum",
                        "dateFrom": DATE_FROM.isoformat(),
                        "dateTo": DATE_TO.isoformat(),
                        "interval": "hour",
                    }
                },
                format="json",
            )

        assert response.status_code == expected_status, response.json()

    @parameterized.expand([("test_variant", "test", True), ("control_variant", "control", False)])
    @time_machine.travel(DATE_TO, tick=False)
    def test_has_metrics_reports_derived_sources_and_series(self, _name: str, variant: str, derived_on: bool) -> None:
        with _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG, derived_variant=variant):
            response = self.client.get(f"/api/projects/{self.team.id}/metrics/has_metrics/")

        assert response.status_code == 200, response.json()
        assert response.json() == {"hasMetrics": False, "hasDerivedSources": True, "hasDerivedMetrics": derived_on}

    @parameterized.expand(
        [
            ("token_without_source_scopes", ["metrics:read"], True, False),
            ("token_with_tracing_scope", ["metrics:read", "tracing:read"], True, True),
            ("user_without_source_access", None, False, False),
        ]
    )
    @time_machine.travel(DATE_TO, tick=False)
    def test_has_metrics_hides_sources_the_caller_cannot_read(
        self, _name: str, scopes: list[str] | None, has_source_access: bool, expected: bool
    ) -> None:
        if scopes is not None:
            value = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                label="test", user=self.user, secure_value=hash_key_value(value), scopes=scopes
            )
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {value}")

        with (
            _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG),
            patch(
                "products.access_control.backend.facade.user_access_control.UserAccessControl.check_access_level_for_resource",
                side_effect=lambda resource, *_, **__: resource not in ("logs", "tracing") or has_source_access,
            ),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/metrics/has_metrics/")

        assert response.status_code == 200, response.json()
        assert response.json() == {"hasMetrics": False, "hasDerivedSources": expected, "hasDerivedMetrics": expected}

    def test_query_event_marks_derived_queries(self) -> None:
        with (
            _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG),
            patch("products.metrics.backend.presentation.api.report_user_action") as report,
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/metrics/query/",
                {
                    "query": {
                        "metricName": REQUESTS,
                        "aggregation": "sum",
                        "dateFrom": DATE_FROM.isoformat(),
                        "dateTo": DATE_TO.isoformat(),
                        "interval": "hour",
                    }
                },
                format="json",
            )

        assert response.status_code == 200, response.json()
        assert sum(point["value"] for point in response.json()["results"][0]["points"]) == 8
        assert report.call_args.args[2]["is_derived"] is True


class TestDerivedMetricQueryCaps(SimpleTestCase):
    @parameterized.expand(
        [
            ("range_over_seven_days", REQUESTS, MetricAggregation.SUM, None, (), 8),
            ("three_group_by_keys", REQUESTS, MetricAggregation.SUM, None, ("a", "b", "c"), 1),
            ("count_of_a_counter", REQUESTS, MetricAggregation.COUNT, None, (), 1),
            ("sum_of_durations", DURATION, MetricAggregation.SUM, None, (), 1),
            ("unknown_derived_name", "posthog.derived.spans.nope", MetricAggregation.SUM, None, (), 1),
        ]
    )
    def test_rejects_queries_outside_the_caps(
        self,
        _name: str,
        metric_name: str,
        aggregation: MetricAggregation,
        quantile: float | None,
        group_by: tuple[str, ...],
        days: int,
    ) -> None:
        clause = MetricQueryClause(
            name="a",
            metric_name=metric_name,
            aggregation=aggregation,
            quantile=quantile,
            group_by=tuple(MetricGroupBy(key=key) for key in group_by),
        )

        with self.assertRaises(ValueError):
            DerivedMetricQueryRunner(
                team=Team(timezone="UTC"),
                clause=clause,
                date_from=DATE_TO - dt.timedelta(days=days),
                date_to=DATE_TO,
                interval=None,
            )


class TestDerivedSeriesVariant(SimpleTestCase):
    # The experiment flag is multivariate, so the control variant is a truthy string that must not turn series on.
    @parameterized.expand(
        [("control", "control", False), ("test", "test", True), ("boolean", True, True), ("off", None, False)]
    )
    def test_only_the_test_variant_turns_derived_series_on(
        self, _name: str, variant: str | bool | None, expected: bool
    ) -> None:
        team = Team(id=1, organization_id="01a1a8b0-0000-0000-0000-000000000000")

        with patch("posthoganalytics.get_feature_flag", return_value=variant):
            assert derived_metrics_enabled(team) is expected
