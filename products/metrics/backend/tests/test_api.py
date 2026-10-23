import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from functools import partial
from typing import Any

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.utils import timezone

import requests
from parameterized import parameterized
from rest_framework import status

from posthog.schema import DateRange, MetricsDashboardVariable, MetricsDashboardVariableSource

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.constants import AvailableFeature
from posthog.errors import CHQueryErrorTooManyBytes
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.facade.user_access_control import AccessControlLevelResource
from products.access_control.backend.models.access_control import AccessControl
from products.error_tracking.backend.facade.testing import create_issue, create_spike_event
from products.metrics.backend.date_range import metrics_query_date_range
from products.metrics.backend.variable_options import (
    _shared_options,
    apply_regex,
    cache as options_cache,
    fill_all_values,
    list_variable_options,
)
from products.metrics.backend.variables import Variable, substitute_sql


class TestMetricsValuesApi(APIBaseTest):
    @parameterized.expand(
        [
            ("zero", "0"),
            ("over_max", "1001"),
            ("not_an_integer", "abc"),
        ]
    )
    def test_invalid_limit_is_rejected_with_400(self, _name: str, limit: str) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/metrics/values/", {"limit": limit})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "limit"


OPTIONS_SQL = "SELECT DISTINCT service_name FROM posthog.metrics"


@override_settings(SNUFFLE_APM_URL="http://snuffle.test:9091")
class TestMetricsVariableOptionsApi(APIBaseTest):
    def _post(self, body: dict[str, Any]) -> Any:
        return self.client.post(f"/api/projects/{self.team.id}/metrics/variable_options/", body, format="json")

    def _fill_all(self, date_from: Any, date_to: Any) -> list[str]:
        filled = fill_all_values(
            team=self.team,
            names=["job"],
            variables={"job": Variable(values=(), is_all=True, all_value=None, options=())},
            definitions={
                "job": MetricsDashboardVariable(
                    name="job", source=MetricsDashboardVariableSource.SQL, query=OPTIONS_SQL, includeAll=True
                )
            },
            date_from=date_from,
            date_to=date_to,
        )
        return list(filled["job"].values)

    def test_tiles_that_miss_the_cache_at_once_run_the_options_query_once(self) -> None:
        def slow_options(*args: Any, **kwargs: Any) -> list[str]:
            time.sleep(0.3)
            return ["api", "worker"]

        date_to = timezone.now()
        with patch("products.metrics.backend.variable_options.run_metrics_sql_values", side_effect=slow_options) as run:
            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(lambda _: self._fill_all(date_to - timedelta(hours=6), date_to), range(8)))

        assert run.call_count == 1
        assert results == [["api", "worker"]] * 8

    def test_the_dashboard_select_fills_the_cache_that_tiles_read(self) -> None:
        window = metrics_query_date_range(self.team, DateRange(date_from="-6h"))
        too_long = "x" * 1025
        with patch(
            "products.metrics.backend.variable_options.run_metrics_sql_values",
            return_value=["api", "worker", too_long],
        ) as run:
            response = self._post({"source": "sql", "query": OPTIONS_SQL, "dateFrom": "-6h"})
            assert response.status_code == status.HTTP_200_OK
            assert response.json() == {"results": ["api", "worker"]}
            assert self._fill_all(window.date_from(), window.date_to()) == ["api", "worker"]

        assert run.call_count == 1

    @parameterized.expand(
        [
            ("wider_than_tiles", {"dateFrom": "-60d"}),
            ("start_after_end", {"dateFrom": "-1h", "dateTo": "-2h"}),
        ]
    )
    def test_rejects_windows_that_tiles_reject(self, _name: str, window: dict[str, str]) -> None:
        with patch("products.metrics.backend.variable_options.run_metrics_sql_values") as run:
            response = self._post({"source": "sql", "query": OPTIONS_SQL, **window})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        run.assert_not_called()

    def test_only_option_queries_that_run_take_a_concurrency_slot(self) -> None:
        with patch("products.metrics.backend.variable_options.run_metrics_sql_values", return_value=["api"]) as run:
            assert self._post({"source": "sql", "query": OPTIONS_SQL}).status_code == status.HTTP_200_OK
            with patch(
                "products.metrics.backend.query_concurrency.app_org_concurrency_slot",
                side_effect=ConcurrencyLimitExceeded("full"),
            ):
                cached = self._post({"source": "sql", "query": OPTIONS_SQL})
                throttled = self._post({"source": "sql", "query": f"{OPTIONS_SQL} WHERE 1 = 1"})

        assert cached.status_code == status.HTTP_200_OK
        assert throttled.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert run.call_count == 1

    def test_a_failed_options_query_is_shared_with_the_next_caller(self) -> None:
        with patch(
            "products.metrics.backend.variable_options.run_metrics_sql_values",
            side_effect=ExposedHogQLError("Unknown column"),
        ) as run:
            responses = [self._post({"source": "sql", "query": OPTIONS_SQL}) for _ in range(2)]

        assert [response.status_code for response in responses] == [status.HTTP_400_BAD_REQUEST] * 2
        assert all("Unknown column" in response.json()["detail"] for response in responses)
        assert run.call_count == 1

    def test_all_of_a_list_ignores_a_regex_left_over_from_a_query(self) -> None:
        filled = fill_all_values(
            team=self.team,
            names=["env"],
            variables={"env": Variable(values=(), is_all=True, all_value=None, options=())},
            definitions={
                "env": MetricsDashboardVariable(
                    name="env",
                    source=MetricsDashboardVariableSource.CUSTOM,
                    customValues=["api", "web"],
                    regex="^api",
                    includeAll=True,
                )
            },
            date_from=timezone.now() - timedelta(hours=1),
            date_to=timezone.now(),
        )

        assert filled["env"].values == ("api", "web")

    @parameterized.expand(
        [
            (
                "chain_without_a_loop",
                {"v1": "$v0", "v2": "$v1", "v3": "$v2", "v4": "$v3", "v5": "$v4", "v6": "$v5"},
                None,
            ),
            ("loop", {"v1": "$v2", "v2": "$v1"}, "loop"),
        ]
    )
    def test_all_expansion_reports_only_real_loops(
        self, _name: str, parents: dict[str, str], error: str | None
    ) -> None:
        all_value = Variable(values=(), is_all=True, all_value=None, options=())
        definitions = {
            "v0": MetricsDashboardVariable(
                name="v0", source=MetricsDashboardVariableSource.CUSTOM, customValues=["a"], includeAll=True
            ),
            **{
                name: MetricsDashboardVariable(
                    name=name,
                    source=MetricsDashboardVariableSource.SQL,
                    query=f"SELECT service_name FROM posthog.metrics WHERE service_name IN {parent}",
                    includeAll=True,
                )
                for name, parent in parents.items()
            },
        }
        names = [name for name in definitions if name != "v0"]
        with patch("products.metrics.backend.variable_options.run_metrics_sql_values", return_value=["a"]):
            fill = partial(
                fill_all_values,
                team=self.team,
                names=names[-1:],
                variables=dict.fromkeys(definitions, all_value),
                definitions=definitions,
                date_from=timezone.now() - timedelta(hours=1),
                date_to=timezone.now(),
            )
            if error:
                with pytest.raises(ValueError, match=error):
                    fill()
            else:
                assert fill()[names[-1]].values == ("a",)

    def test_all_expansion_loads_each_variable_once(self) -> None:
        all_value = Variable(values=(), is_all=True, all_value=None, options=())
        definitions = {
            f"v{index}": MetricsDashboardVariable(
                name=f"v{index}",
                source=MetricsDashboardVariableSource.SQL,
                query=" UNION ALL ".join(
                    ["SELECT 'a'", *(f"SELECT 'a' WHERE 'a' IN $v{parent}" for parent in reversed(range(index)))]
                ),
                includeAll=True,
            )
            for index in range(8)
        }
        with (
            patch("products.metrics.backend.variable_options.run_metrics_sql_values", return_value=["a"]),
            patch(
                "products.metrics.backend.variable_options.list_variable_options", wraps=list_variable_options
            ) as load,
        ):
            fill_all_values(
                team=self.team,
                names=["v7"],
                variables=dict.fromkeys(definitions, all_value),
                definitions=definitions,
                date_from=timezone.now() - timedelta(hours=1),
                date_to=timezone.now(),
            )

        assert load.call_count == 8

    def test_all_expansion_stops_before_its_values_outgrow_a_query(self) -> None:
        definitions = {
            name: MetricsDashboardVariable(
                name=name, source=MetricsDashboardVariableSource.SQL, query="SELECT 1", includeAll=True
            )
            for name in ("a", "b")
        }
        all_value = Variable(values=(), is_all=True, all_value=None, options=())
        with (
            patch("products.metrics.backend.variable_options.run_metrics_sql_values", return_value=["x" * 6]),
            patch("products.metrics.backend.variable_options.MAX_QUERY_SIZE_BYTES", 30),
        ):
            with pytest.raises(ValueError, match="too many values"):
                fill_all_values(
                    team=self.team,
                    names=["a", "b"],
                    variables=dict.fromkeys(definitions, all_value),
                    definitions=definitions,
                    date_from=timezone.now() - timedelta(hours=1),
                    date_to=timezone.now(),
                )

    @parameterized.expand(
        [
            ("chain_longer_than_the_cap", 60, timedelta(hours=1), "at most 50 variables"),
            ("window_wider_than_tiles", 1, timedelta(days=60), "at most 31 days"),
        ]
    )
    def test_all_expansion_limits(self, _name: str, length: int, window: timedelta, error: str) -> None:
        all_value = Variable(values=(), is_all=True, all_value=None, options=())
        definitions = {
            f"v{index}": MetricsDashboardVariable(
                name=f"v{index}",
                source=MetricsDashboardVariableSource.SQL,
                query=f"SELECT 'a' WHERE 'a' IN $v{index - 1}" if index else "SELECT 'a'",
                includeAll=True,
            )
            for index in range(length)
        }
        with patch("products.metrics.backend.variable_options.run_metrics_sql_values", return_value=["a"]) as run:
            with pytest.raises(ValueError, match=error):
                fill_all_values(
                    team=self.team,
                    names=[f"v{length - 1}"],
                    variables=dict.fromkeys(definitions, all_value),
                    definitions=definitions,
                    date_from=timezone.now() - window,
                    date_to=timezone.now(),
                )

        run.assert_not_called()

    @parameterized.expand(
        [
            ("promql_with_a_key", {"source": "promql", "query": "query_result(up)"}, True, 429),
            ("sql_with_a_key", {"source": "sql", "query": OPTIONS_SQL}, True, 429),
            ("list_in_the_browser", {"source": "custom", "customValues": ["a"]}, False, 200),
        ]
    )
    def test_options_respect_the_query_byte_budget(
        self, _name: str, body: dict[str, Any], with_key: bool, expected_status: int
    ) -> None:
        exhausted = MagicMock(remaining_bytes=0, retry_after_seconds=30)
        headers = {}
        if with_key:
            token = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                label="options", user=self.user, secure_value=hash_key_value(token), scopes=["metrics:read"]
            )
            self.client.logout()
            headers = {"authorization": f"Bearer {token}"}
        with (
            patch(
                "products.metrics.backend.presentation.api.api_queries_budget_enforcement_enabled", return_value=True
            ),
            patch("products.metrics.backend.presentation.api.get_api_queries_budget_status", return_value=exhausted),
            patch("posthog.api.snuffle_proxy.internal_requests.request") as request,
            patch("products.metrics.backend.variable_options.run_metrics_sql_values") as run,
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/metrics/variable_options/", body, format="json", headers=headers
            )

        assert response.status_code == expected_status
        request.assert_not_called()
        run.assert_not_called()

    def test_windows_in_the_same_minutes_run_on_the_same_bounds(self) -> None:
        start = timezone.now().replace(second=0, microsecond=0) - timedelta(hours=1)
        with patch("products.metrics.backend.variable_options.run_metrics_sql_values", return_value=["a"]) as run:
            for seconds in (10, 50):
                window = {"dateFrom": (start + timedelta(seconds=seconds)).isoformat()}
                self._post({"source": "sql", "query": OPTIONS_SQL, **window})

        assert run.call_count == 1
        assert run.call_args.args[2] == start

    def test_sql_options_drop_long_values_in_clickhouse(self) -> None:
        with patch("products.metrics.backend.variable_options.run_metrics_sql_values", return_value=["a"]) as run:
            self._post({"source": "sql", "query": OPTIONS_SQL})
            self._post({"source": "sql", "query": OPTIONS_SQL, "regex": "a(.)"})

        assert [call.kwargs["max_length"] for call in run.call_args_list] == [1024, 16 * 1024]

    def test_a_selection_set_to_all_without_options_is_an_empty_set(self) -> None:
        with patch("products.metrics.backend.variable_options.run_metrics_sql_values", return_value=["a"]) as run:
            response = self._post(
                {
                    "source": "sql",
                    "query": f"{OPTIONS_SQL} WHERE service_name IN $zone",
                    "variables": [{"name": "zone", "values": [], "all": True}],
                }
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert run.call_args.args[5] == {"metric_variable_zone": ast.Tuple(exprs=[])}

    def test_all_without_options_is_an_empty_set(self) -> None:
        with patch("products.metrics.backend.variable_options.run_metrics_sql_values", return_value=[]):
            filled = fill_all_values(
                team=self.team,
                names=["job"],
                variables={"job": Variable(values=(), is_all=True, all_value=None, options=())},
                definitions={
                    "job": MetricsDashboardVariable(
                        name="job", source=MetricsDashboardVariableSource.SQL, query=OPTIONS_SQL, includeAll=True
                    )
                },
                date_from=timezone.now() - timedelta(hours=1),
                date_to=timezone.now(),
            )

        substitution = substitute_sql("SELECT 1 WHERE service_name IN $job", filled)
        assert substitution.placeholders == {"metric_variable_job": ast.Tuple(exprs=[])}

    def test_the_regex_applies_before_the_option_length_limit(self) -> None:
        line = 'up{instance="api", ' + "x" * 1100 + "}"
        with patch("products.metrics.backend.variable_options.run_metrics_sql_values", return_value=[line, "web"]):
            response = self._post({"source": "sql", "query": OPTIONS_SQL, "regex": '/instance="([^"]+)"/'})

        assert response.json() == {"results": ["api"]}

    def test_a_regex_group_that_does_not_match_gives_no_option(self) -> None:
        assert apply_regex(["web", "api-web"], "^(api-)?web$") == ["api-"]

    def test_a_load_that_outlives_its_lock_keeps_the_new_lock(self) -> None:
        def slow_load() -> list[str]:
            options_cache.set("options:lock", "taken-over", 90)
            return ["a"]

        assert _shared_options("options", slow_load) == ["a"]
        assert options_cache.get("options:lock") == "taken-over"

    def test_clickhouse_limits_are_shown_to_the_user(self) -> None:
        with patch(
            "products.metrics.backend.variable_options.run_metrics_sql_values",
            side_effect=CHQueryErrorTooManyBytes("Limit for rows or bytes to read exceeded"),
        ):
            response = self._post({"source": "sql", "query": OPTIONS_SQL})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "bytes to read" in response.json()["detail"]

    def test_custom_options_drop_duplicates_and_blanks(self) -> None:
        response = self._post({"source": "custom", "customValues": ["b", "a", "b", ""]})
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"results": ["b", "a"]}

    @parameterized.expand(
        [
            (
                "vector",
                {"resultType": "vector", "result": [{"metric": {"job": "api"}, "value": [1, "2"]}]},
                ['{job="api"} 2 1000'],
            ),
            ("scalar", {"resultType": "scalar", "result": [1, "2"]}, ["2"]),
        ]
    )
    def test_query_result_reads_each_result_type(self, _name: str, data: dict[str, Any], expected: list[str]) -> None:
        upstream = MagicMock(spec=requests.Response, status_code=200, headers={})
        upstream.json.return_value = {"status": "success", "data": data}
        with patch("posthog.api.snuffle_proxy.internal_requests.request", return_value=upstream):
            response = self._post({"source": "promql", "query": "query_result(1 + 1)"})

        assert response.json() == {"results": expected}

    def test_label_values_resolves_the_parent_variable(self) -> None:
        upstream = MagicMock(spec=requests.Response, status_code=200, headers={})
        upstream.json.return_value = {"status": "success", "data": ["i-1", "i-2"]}
        with patch("posthog.api.snuffle_proxy.internal_requests.request", return_value=upstream) as request:
            response = self._post(
                {
                    "source": "promql",
                    "query": 'label_values(up{job=~"$job"}, instance)',
                    "variables": [{"name": "job", "values": ["api", "web"]}],
                }
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"results": ["i-1", "i-2"]}
        method, url = request.call_args.args
        assert (method, url) == ("GET", "http://snuffle.test:9091/api/v1/label/instance/values")
        assert request.call_args.kwargs["params"]["match[]"] == ['up{job=~"(api|web)"}']

    @parameterized.expand(
        [
            ("label_values", "label_values(up, job)", "/api/v1/label/job/values", ["up"]),
            ("metrics_regex", "metrics(^http_)", "/api/v1/label/__name__/values", ['{__name__=~".*(?:^http_).*"}']),
        ]
    )
    def test_promql_queries_match_and_limit_on_snuffle(
        self, _name: str, query: str, path: str, match: list[str]
    ) -> None:
        upstream = MagicMock(spec=requests.Response, status_code=200, headers={})
        upstream.json.return_value = {"status": "success", "data": ["a"]}
        with patch("posthog.api.snuffle_proxy.internal_requests.request", return_value=upstream) as request:
            response = self._post({"source": "promql", "query": query})

        assert response.status_code == status.HTTP_200_OK
        assert request.call_args.args[1] == f"http://snuffle.test:9091{path}"
        params = request.call_args.kwargs["params"]
        assert (params["match[]"], params["limit"]) == (match, ["1000"])

    def test_promql_queries_need_the_snuffle_flag(self) -> None:
        def flag_enabled(flag: str, *args: Any, **kwargs: Any) -> bool:
            return flag != "logs-metrics-snuffle-api"

        with (
            patch("posthoganalytics.feature_enabled", side_effect=flag_enabled),
            patch("posthog.api.snuffle_proxy.internal_requests.request") as request,
        ):
            response = self._post({"source": "promql", "query": "query_result(up)"})

        assert response.status_code == status.HTTP_403_FORBIDDEN
        request.assert_not_called()

    @parameterized.expand(
        [
            ("parent_without_value", {"source": "promql", "query": 'label_values(up{job="$job"}, instance)'}, "$job"),
            ("unknown_function", {"source": "promql", "query": "sum(up)"}, "label_values"),
            ("bad_label", {"source": "promql", "query": "label_values(up, 1abc)"}, "not a label name"),
            ("empty_query", {"source": "sql", "query": " "}, "Write a query"),
            ("invalid_regex", {"source": "promql", "query": "label_values(job)", "regex": "("}, "regex cannot be used"),
        ]
    )
    def test_bad_queries_are_rejected_with_400(self, _name: str, body: dict, message: str) -> None:
        with patch("posthog.api.snuffle_proxy.internal_requests.request") as request:
            response = self._post(body)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert message in response.json()["detail"]
        request.assert_not_called()


class TestMetricsErrorSpikesApi(APIBaseTest):
    def test_returns_spikes_from_error_tracking_in_the_window(self) -> None:
        issue_id = create_issue(team_id=self.team.id, name="Boom")
        now = timezone.now()
        create_spike_event(team_id=self.team.id, issue_id=issue_id, detected_at=now)

        # The overlay is a staff-only PoC behind its own flag, on top of the
        # `metrics` gate the conftest already enables — turn both on here.
        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self.client.get(
                f"/api/projects/{self.team.id}/metrics/error_spikes/",
                {"dateFrom": (now - timedelta(hours=1)).isoformat()},
            )

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["issue_id"] == str(issue_id)
        assert results[0]["issue_name"] == "Boom"

    def test_is_forbidden_when_only_the_metrics_flag_is_enabled(self) -> None:
        # The autouse conftest enables `metrics` but not `metrics-error-overlays`,
        # so the endpoint must stay closed even though the rest of metrics is open.
        response = self.client.get(
            f"/api/projects/{self.team.id}/metrics/error_spikes/",
            {"dateFrom": (timezone.now() - timedelta(hours=1)).isoformat()},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand(
        [
            ("metrics_scope_only", ["metrics:read"], status.HTTP_403_FORBIDDEN),
            ("both_scopes", ["metrics:read", "error_tracking:read"], status.HTTP_200_OK),
        ]
    )
    def test_token_needs_the_error_tracking_scope_too(
        self, _name: str, scopes: list[str], expected_status: int
    ) -> None:
        # The response is Error Tracking data, so a token delegated only metrics:read
        # must not reach it — the scope check is the token-level counterpart of the
        # user-level access-control check.
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="scoped", user=self.user, secure_value=hash_key_value(token), scopes=scopes)
        self.client.logout()

        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self.client.get(
                f"/api/projects/{self.team.id}/metrics/error_spikes/",
                {"dateFrom": (timezone.now() - timedelta(hours=1)).isoformat()},
                headers={"authorization": f"Bearer {token}"},
            )

        assert response.status_code == expected_status
        if expected_status == status.HTTP_403_FORBIDDEN:
            assert response.json()["detail"] == "API key missing required scope 'error_tracking:read'"


class TestMetricsFeatureFlagGate(APIBaseTest):
    @parameterized.expand(
        [
            ("enabled", True, status.HTTP_200_OK),
            ("disabled", False, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_metrics_flag_gates_the_api(self, _name: str, flag_enabled: bool, expected_status: int) -> None:
        with (
            patch("posthoganalytics.feature_enabled", return_value=flag_enabled),
            patch("products.metrics.backend.presentation.api.team_has_metrics", return_value=True),
        ):
            response = self.client.get(f"/api/projects/{self.team.id}/metrics/has_metrics/")

        assert response.status_code == expected_status


@pytest.mark.ee
class TestMetricsAccessControl(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()

        self.viewer_user = User.objects.create_and_join(self.organization, "metrics-viewer@posthog.com", "testtest")
        self.no_access_user = User.objects.create_and_join(
            self.organization, "metrics-no-access@posthog.com", "testtest"
        )

    def _create_access_control(
        self, user: User, access_level: AccessControlLevelResource, resource: str = "metrics"
    ) -> None:
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=None,
            access_level=access_level,
            organization_member=membership,
        )

    @parameterized.expand(
        [
            ("viewer", status.HTTP_200_OK),
            ("none", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_access_level_controls_metrics_queries(
        self, access_level: AccessControlLevelResource, expected_status: int
    ) -> None:
        user = self.viewer_user if access_level == "viewer" else self.no_access_user
        self._create_access_control(user, access_level)
        self.client.force_login(user)

        with patch(
            "products.metrics.backend.presentation.api.team_has_metrics", return_value=True
        ) as team_has_metrics_mock:
            response = self.client.get(f"/api/projects/{self.team.id}/metrics/has_metrics/")

        assert response.status_code == expected_status
        assert team_has_metrics_mock.call_count == (1 if expected_status == status.HTTP_200_OK else 0)

    @parameterized.expand(
        [
            ("values", "GET", {"limit": "0"}),
            ("attributes", "GET", {"limit": "0"}),
            ("attribute_values", "GET", {}),
            ("query", "POST", {}),
            ("samples", "POST", {}),
            ("error_spikes", "GET", {}),
            ("characterize", "POST", {}),
            ("variable_options", "POST", {}),
        ]
    )
    def test_none_access_blocks_every_metrics_action_before_validation(
        self, action: str, method: str, payload: dict[str, str]
    ) -> None:
        self._create_access_control(self.no_access_user, "none")
        self.client.force_login(self.no_access_user)
        url = f"/api/projects/{self.team.id}/metrics/{action}/"

        if method == "GET":
            response = self.client.get(url, payload)
        else:
            response = self.client.post(url, payload, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand(
        [
            ("error_tracking_viewer", "viewer", status.HTTP_200_OK),
            ("error_tracking_none", "none", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_error_spikes_requires_error_tracking_access(
        self, _name: str, error_tracking_level: AccessControlLevelResource, expected_status: int
    ) -> None:
        # The overlay endpoint serves Error Tracking data, so metrics access alone must not
        # reach it — the caller also needs Error Tracking view access.
        self._create_access_control(self.viewer_user, "viewer", resource="metrics")
        self._create_access_control(self.viewer_user, error_tracking_level, resource="error_tracking")
        self.client.force_login(self.viewer_user)

        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self.client.get(
                f"/api/projects/{self.team.id}/metrics/error_spikes/",
                {"dateFrom": (timezone.now() - timedelta(hours=1)).isoformat()},
            )

        assert response.status_code == expected_status
