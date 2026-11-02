import json
import datetime as dt
from concurrent.futures import Future
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.api.snuffle_proxy import SNUFFLE_API_FEATURE_FLAG
from posthog.api.test.dashboards import DashboardAPI
from posthog.models import User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.metrics.backend.facade.testing import seed_metric

GAUGE_QUERY: dict[str, Any] = {
    "kind": "MetricsQuery",
    "clauses": [{"name": "a", "metricName": "cpu_usage", "metricType": "gauge", "aggregation": "max"}],
    "dateRange": {"date_from": "-6h"},
}

HEATMAP_QUERY: dict[str, Any] = {
    "kind": "MetricsQuery",
    "clauses": [{"name": "a", "metricName": "request_duration", "metricType": "histogram"}],
    "dateRange": {"date_from": "-6h"},
    "display": {"type": "heatmap"},
}


class _InlineExecutor:
    """Runs run_widgets work items on the test thread, so queries see the rows of the test transaction."""

    def __init__(self, max_workers: int | None = None) -> None:
        pass

    def __enter__(self) -> "_InlineExecutor":
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def submit(self, fn: Any, *args: Any, **kwargs: Any) -> "Future[Any]":
        future: Future[Any] = Future()
        future.set_result(fn(*args, **kwargs))
        return future


class TestMetricsDashboardWidget(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)
        self.enabled_flags = {"dashboard-widgets", "metrics", SNUFFLE_API_FEATURE_FLAG}
        self.users_without_metrics: set[str] = set()
        flags_patcher = patch(
            "posthoganalytics.feature_enabled",
            side_effect=lambda flag, distinct_id, *args, **kwargs: (
                flag in self.enabled_flags and not (flag == "metrics" and distinct_id in self.users_without_metrics)
            ),
        )
        flags_patcher.start()
        self.addCleanup(flags_patcher.stop)
        executor_patcher = patch("products.dashboards.backend.api.dashboard.ThreadPoolExecutor", _InlineExecutor)
        executor_patcher.start()
        self.addCleanup(executor_patcher.stop)

        now = dt.datetime.now(dt.UTC).replace(second=0, microsecond=0)
        # The value is the age in minutes, so a narrower window shows which points it kept.
        seed_metric(
            team_id=self.team.pk,
            metric_name="cpu_usage",
            points=[(now - dt.timedelta(minutes=age), float(age)) for age in (10, 30, 180)],
        )
        seed_metric(
            team_id=self.team.pk,
            metric_name="request_duration",
            metric_type="histogram",
            points=[(now - dt.timedelta(minutes=10), 6.0)],
            histogram_bounds=[10.0, 100.0],
            histogram_counts=[3, 2, 1],
            count=6,
        )
        self.dashboard_id, _ = self.dashboard_api.create_dashboard({"name": "Service health"})

    def _add_tile(self, query: dict[str, Any] | None = None) -> int:
        config = {} if query is None else {"query": query}
        _, dashboard_json = self.dashboard_api.create_widget_tile(
            self.dashboard_id, widget_type="metrics", config=config
        )
        return dashboard_json["tiles"][-1]["id"]

    def _run(
        self,
        tile_id: int,
        filters_override: dict[str, Any] | None = None,
        refresh: bool = False,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, str] = {"tile_ids": str(tile_id)}
        if filters_override is not None:
            params["filters_override"] = json.dumps(filters_override)
        if refresh:
            params["refresh"] = "true"
        extra: dict[str, Any] = {"HTTP_AUTHORIZATION": f"Bearer {api_key}"} if api_key else {}
        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/run_widgets/", params, **extra
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return response.json()["results"][0]

    @staticmethod
    def _values(result: dict[str, Any]) -> list[float]:
        return sorted(
            point["value"]
            for series in result["result"]["results"]
            for point in series["points"]
            if point["value"] is not None
        )

    def test_runs_the_query_and_follows_the_dashboard_date_filter(self) -> None:
        tile_id = self._add_tile(GAUGE_QUERY)

        self.assertEqual(self._values(self._run(tile_id)), [10.0, 30.0, 180.0])
        self.assertEqual(self._values(self._run(tile_id, filters_override={"date_from": "-1h"})), [10.0, 30.0])

    def test_a_manual_refresh_skips_the_query_cache(self) -> None:
        tile_id = self._add_tile(GAUGE_QUERY)
        self._run(tile_id)
        seed_metric(
            team_id=self.team.pk,
            metric_name="cpu_usage",
            points=[(dt.datetime.now(dt.UTC).replace(second=0, microsecond=0) - dt.timedelta(minutes=5), 5.0)],
        )

        self.assertNotIn(5.0, self._values(self._run(tile_id)))
        self.assertIn(5.0, self._values(self._run(tile_id, refresh=True)))

    def test_unconfigured_widget_asks_for_a_metric_without_running_a_query(self) -> None:
        tile_id = self._add_tile()

        result = self._run(tile_id)

        self.assertIsNone(result["error"])
        self.assertEqual(result["result"], {"needsConfiguration": True})

    def test_heatmap_display_runs_the_histogram_query(self) -> None:
        tile_id = self._add_tile(HEATMAP_QUERY)

        result = self._run(tile_id)

        self.assertIsNone(result["error"])
        self.assertEqual(result["result"]["bounds"][:2], [10.0, 100.0])
        self.assertTrue(result["result"]["times"])

    @parameterized.expand(
        [
            ("promql", {"clauses": [], "language": "promql", "promql": "up"}, "A heatmap needs a builder query"),
            (
                "gauge metric",
                {"clauses": [{"name": "a", "metricName": "cpu_usage", "metricType": "gauge"}]},
                "A heatmap needs a histogram metric.",
            ),
        ]
    )
    def test_heatmap_display_explains_an_ineligible_query(
        self, _name: str, query_patch: dict[str, Any], expected_error: str
    ) -> None:
        tile_id = self._add_tile({**HEATMAP_QUERY, **query_patch})

        result = self._run(tile_id)

        self.assertIsNone(result["result"])
        self.assertTrue(result["error"].startswith(expected_error), result["error"])
        self.assertTrue(result["error_is_user_facing"])

    def test_checks_metrics_access_for_the_viewer_not_the_widget_creator(self) -> None:
        tile_id = self._add_tile(GAUGE_QUERY)
        viewer = User.objects.create_and_join(self.organization, "viewer@example.com", "password")
        self.users_without_metrics.add(str(viewer.distinct_id))

        self.client.force_login(viewer)
        result = self._run(tile_id)

        self.assertIsNone(result["result"])
        self.assertEqual(result["error"], "You do not have access to metrics.")

    def test_a_promql_widget_needs_the_promql_flag(self) -> None:
        tile_id = self._add_tile({"kind": "MetricsQuery", "clauses": [], "language": "promql", "promql": "up"})
        self.enabled_flags.discard(SNUFFLE_API_FEATURE_FLAG)

        result = self._run(tile_id)

        self.assertIsNone(result["result"])
        self.assertEqual(result["error"], "You do not have access to metrics.")

    @parameterized.expand([("a signed-in viewer", False), ("a personal API key", True)])
    def test_only_api_key_requests_count_against_the_shared_widget_throttle(
        self, _name: str, use_api_key: bool
    ) -> None:
        tile_id = self._add_tile(GAUGE_QUERY)
        token: str | None = None
        if use_api_key:
            token = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                label="metrics widgets",
                user=self.user,
                secure_value=hash_key_value(token),
                scopes=["dashboard:read", "metrics:read"],
                scoped_teams=[],
                scoped_organizations=[],
            )

        with patch(
            "products.dashboards.backend.api.dashboard.get_dashboard_widget_query_throttle_error",
            return_value="Rate limit exceeded. Try again later.",
        ) as throttle:
            result = self._run(tile_id, api_key=token)

        self.assertEqual(throttle.called, use_api_key)
        self.assertEqual(result["error"], "Rate limit exceeded. Try again later." if use_api_key else None)

    def test_cannot_add_a_metrics_widget_without_the_metrics_flag(self) -> None:
        self.enabled_flags.discard("metrics")

        self.dashboard_api.create_widget_tile(
            self.dashboard_id,
            widget_type="metrics",
            config={"query": GAUGE_QUERY},
            expected_status=status.HTTP_400_BAD_REQUEST,
        )
