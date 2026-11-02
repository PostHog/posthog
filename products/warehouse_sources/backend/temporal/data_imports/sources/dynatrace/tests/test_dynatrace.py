from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynatrace import dynatrace as dt
from products.warehouse_sources.backend.temporal.data_imports.sources.dynatrace.dynatrace import (
    METRIC_SELECTOR_REQUIRED_ERROR,
    DynatraceHostNotAllowedError,
    DynatraceResumeConfig,
    _build_url,
    _clamped_from_value,
    _flatten_metric_data_points,
    _format_from_value,
    _validated_hostname,
    check_endpoint_permissions,
    normalize_environment_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynatrace.settings import TAGGED_ENTITY_TYPES
from products.warehouse_sources.backend.temporal.data_imports.sources.dynatrace.source import DynatraceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dynatrace import (
    DynatraceSourceConfig,
)

BASE_URL = "https://abc12345.live.dynatrace.com"


class TestNormalizeEnvironmentUrl:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("https://abc12345.live.dynatrace.com", "https://abc12345.live.dynatrace.com"),
            ("https://abc12345.live.dynatrace.com/", "https://abc12345.live.dynatrace.com"),
            ("abc12345.live.dynatrace.com", "https://abc12345.live.dynatrace.com"),
            (" https://abc12345.live.dynatrace.com ", "https://abc12345.live.dynatrace.com"),
            # A pasted API path must not double up when endpoint paths are appended.
            ("https://abc12345.live.dynatrace.com/api/v2", "https://abc12345.live.dynatrace.com"),
            ("https://abc12345.live.dynatrace.com/api", "https://abc12345.live.dynatrace.com"),
            # Managed environments carry a path prefix that must be preserved.
            ("https://dynatrace.example.com/e/abc-123", "https://dynatrace.example.com/e/abc-123"),
            ("https://dynatrace.example.com/e/abc-123/api/v2", "https://dynatrace.example.com/e/abc-123"),
        ],
    )
    def test_normalize(self, raw: str, expected: str) -> None:
        assert normalize_environment_url(raw) == expected


class TestValidatedHostname:
    @pytest.mark.parametrize(
        "url",
        [
            "https://127.0.0.1\\@example.com",  # backslash userinfo smuggling
            "https://127.0.0.1%5C@example.com",  # percent-encoded backslash
            "https://user@example.com",  # userinfo
            "ftp://example.com",  # non-http scheme
            "https://exa mple.com",  # invalid hostname characters
        ],
    )
    def test_rejects_ambiguous_urls(self, url: str) -> None:
        assert _validated_hostname(url) is None

    def test_rejects_plain_http_on_cloud(self) -> None:
        with mock.patch.object(dt, "is_cloud", return_value=True):
            assert _validated_hostname("http://dynatrace.internal.example.com") is None


class TestFormatFromValue:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1735689600000, "1735689600000"),  # epoch-ms watermark passes through
            (datetime(2025, 1, 1, tzinfo=UTC), "1735689600000"),
            (datetime(2025, 1, 1), "1735689600000"),  # naive datetimes treated as UTC
            ("now-30d", "now-30d"),  # relative seeds pass through
        ],
    )
    def test_format(self, value: Any, expected: str) -> None:
        assert _format_from_value(value) == expected


class TestClampedFromValue:
    def test_relative_seed_passes_through(self) -> None:
        assert _clamped_from_value("now-6h", timedelta(hours=6)) == "now-6h"


def _driver(metric_selector: str | None = "builtin:host.cpu.usage") -> SourceDriver:
    return SourceDriver(
        DynatraceSource(),
        DynatraceSourceConfig(environment_url=BASE_URL, api_token="token", metric_selector=metric_selector),
    )


class TestFirstPageParams:
    def test_entity_endpoint_sends_selector_and_fields(self) -> None:
        result = _driver().run("hosts", [ScriptedResponse(json={"entities": [], "nextPageKey": None})])
        assert result.raised is None
        assert result.requests[0].param("entitySelector") == 'type("HOST")'
        assert result.requests[0].param("from") == "now-30d"
        assert (result.requests[0].param("fields") or "").startswith("+firstSeenTms")

    def test_non_time_filtered_endpoint_never_sends_from(self) -> None:
        # `metrics` has no timeframe filter; a stray watermark must not leak into the request.
        result = _driver().run(
            "metrics",
            [ScriptedResponse(json={"metrics": [], "nextPageKey": None})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1735689600000,
        )
        assert result.raised is None
        assert result.requests[0].param("from") is None

    def test_synthetic_executions_watermark_is_clamped_to_the_served_window(self) -> None:
        result = _driver().run(
            "synthetic_executions",
            [ScriptedResponse(json={"executions": [], "nextPageKey": None})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1735689600000,
        )
        assert result.raised is None
        earliest_ms = int((datetime.now(UTC) - timedelta(hours=6)).timestamp() * 1000)
        assert int(result.requests[0].param("executionFrom") or "0") == pytest.approx(earliest_ms, abs=5000)

    @pytest.mark.parametrize(
        ("should_use_incremental_field", "expected_from"),
        [
            (False, "now-30d"),
            (True, "1735689600000"),
        ],
    )
    def test_attacks_window_starts_at_the_watermark_on_incremental_runs(
        self, should_use_incremental_field: bool, expected_from: str
    ) -> None:
        result = _driver().run(
            "attacks",
            [ScriptedResponse(json={"attacks": [], "nextPageKey": None})],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=1735689600000 if should_use_incremental_field else None,
        )
        assert result.raised is None
        assert result.requests[0].param("from") == expected_from
        assert "+request" in (result.requests[0].param("fields") or "")

    def test_metric_data_points_without_a_selector_is_refused(self) -> None:
        result = _driver(metric_selector="   ").run("metric_data_points", [])
        assert isinstance(result.raised, ValueError)
        assert "Metric keys" in str(result.raised)
        assert result.requests == []


class TestPagination:
    def test_cursor_pagination_yields_and_saves_state_after_yield(self) -> None:
        result = _driver().run(
            "problems",
            [
                ScriptedResponse(json={"problems": [{"problemId": "P-1"}], "nextPageKey": "key-2"}),
                ScriptedResponse(json={"problems": [{"problemId": "P-2"}], "nextPageKey": None}),
            ],
        )
        assert result.raised is None
        assert result.rows == [{"problemId": "P-1"}, {"problemId": "P-2"}]
        assert result.saved_states == [DynatraceResumeConfig(next_page_key="key-2")]
        # Follow-up request carries only the cursor — Dynatrace rejects mixed params.
        assert result.queries[1] == {"nextPageKey": ("key-2",)}

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "problems",
            [ScriptedResponse(json={"problems": [{"problemId": "P-9"}], "nextPageKey": None})],
            resume_state=DynatraceResumeConfig(next_page_key="resume-key"),
        )
        assert result.raised is None
        assert result.rows == [{"problemId": "P-9"}]
        # The saved cursor reseeds the first request and drops the first-page filters.
        assert result.queries[0] == {"nextPageKey": ("resume-key",)}

    def test_redirect_is_refused(self) -> None:
        # Redirects are disabled so the Authorization header can't be bounced off the validated host.
        result = _driver().run(
            "problems",
            [ScriptedResponse(status=302, json={}, headers={"Location": "https://evil.example.com"})],
        )
        assert isinstance(result.raised, ValueError)
        assert result.paths == ["/api/v2/problems"]

    def test_unsafe_host_is_refused_before_any_request(self) -> None:
        with mock.patch.object(dt, "_is_host_safe", return_value=(False, "blocked")):
            result = _driver().run("problems", [])
        assert isinstance(result.raised, DynatraceHostNotAllowedError)
        # The host check runs before a session is ever built.
        assert result.requests == []
        assert result.session_options == []


class TestEntityTagFanOut:
    def test_a_cursor_does_not_carry_into_the_next_entity_type(self) -> None:
        responses = [
            ScriptedResponse(json={"tags": [{"stringRepresentation": "a"}], "nextPageKey": "key-2"}),
            ScriptedResponse(json={"tags": [{"stringRepresentation": "b"}]}),
        ]
        responses += [ScriptedResponse(json={"tags": []}) for _ in TAGGED_ENTITY_TYPES[1:]]
        result = _driver().run("entity_tags", responses)

        assert result.raised is None
        assert result.queries[1] == {"nextPageKey": ("key-2",)}
        # The next type starts its own walk; reusing the previous type's cursor would re-read it.
        assert result.requests[2].param("entitySelector") == f'type("{TAGGED_ENTITY_TYPES[1]}")'
        assert result.requests[2].param("nextPageKey") is None


class TestRemediationItemFanOut:
    def test_items_are_read_per_security_problem_and_stamped_with_its_id(self) -> None:
        problems = "/api/v2/securityProblems"
        script = route(
            {
                f"{problems}/S-1/remediationItems": [
                    ScriptedResponse(json={"remediationItems": [{"id": "PROCESS_GROUP-1"}, {"id": "PROCESS_GROUP-2"}]})
                ],
                f"{problems}/S%2F2/remediationItems": [ScriptedResponse(status=404, json={"error": {"code": 404}})],
                f"{problems}/S-3/remediationItems": [
                    ScriptedResponse(json={"remediationItems": [{"id": "PROCESS_GROUP-1"}]})
                ],
                problems: [
                    ScriptedResponse(
                        json={
                            "securityProblems": [
                                {"securityProblemId": "S-1"},
                                {"displayId": "S-no-id"},
                                {"securityProblemId": "S/2"},
                            ],
                            "nextPageKey": "key-2",
                        }
                    ),
                    ScriptedResponse(json={"securityProblems": [{"securityProblemId": "S-3"}], "nextPageKey": None}),
                ],
            }
        )
        result = _driver().run("security_problem_remediation_items", script)

        assert result.raised is None
        assert [(row["securityProblemId"], row["id"]) for row in result.rows] == [
            ("S-1", "PROCESS_GROUP-1"),
            ("S-1", "PROCESS_GROUP-2"),
            ("S-3", "PROCESS_GROUP-1"),
        ]
        parent_requests = [request for request in result.requests if request.path == problems]
        assert parent_requests[0].param("securityProblemSelector") == 'vulnerabilityType("THIRD_PARTY","RUNTIME")'
        assert parent_requests[1].query == {"nextPageKey": ("key-2",)}
        # The parent walk keeps no cursor: a staged parent cursor would skip the children of its page.
        assert result.saved_states == []


class TestFlattenMetricDataPoints:
    def test_dimension_key_falls_back_to_the_ordered_dimensions(self) -> None:
        # Older responses carry only the deprecated `dimensions` list, and the key still has to
        # separate the series.
        rows = _flatten_metric_data_points(
            [
                {
                    "metricId": "builtin:host.cpu.usage",
                    "data": [{"dimensions": ["HOST-1"], "timestamps": [1], "values": [1.0]}],
                }
            ]
        )
        assert [row["dimensionKey"] for row in rows] == ["HOST-1"]

    def test_the_metrics_query_response_is_flattened_end_to_end(self) -> None:
        result = _driver().run(
            "metric_data_points",
            [
                ScriptedResponse(
                    json={
                        "result": [
                            {
                                "metricId": "builtin:host.cpu.usage",
                                "data": [
                                    {
                                        "dimensionMap": {"dt.entity.host": "HOST-1"},
                                        "timestamps": [1735689600000],
                                        "values": [42.0],
                                    }
                                ],
                            }
                        ],
                        "nextPageKey": None,
                    }
                )
            ],
        )
        assert result.raised is None
        assert [(row["metricId"], row["timestamp"], row["value"]) for row in result.rows] == [
            ("builtin:host.cpu.usage", 1735689600000, 42.0)
        ]


class TestValidateCredentials:
    def _validate(self, status_code: int, schema_name: str | None = None) -> tuple[bool, str | None]:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            result = validate_credentials(BASE_URL, "token", team_id=None, schema_name=schema_name)
        expected_paths = {
            "hosts": "/api/v2/entities",
            # The child path needs a security problem id, so the scope is probed on the parent listing.
            "security_problem_remediation_items": "/api/v2/securityProblems",
        }
        assert network.requests_log[0].path == expected_paths.get(schema_name or "", "/api/v2/problems")
        return result

    @pytest.mark.parametrize(
        ("status_code", "schema_name", "expected_valid"),
        [
            (200, None, True),
            (401, None, False),
            # 403 at source-create means the token is genuine but lacks the probed scope —
            # users may legitimately only grant scopes for the tables they sync.
            (403, None, True),
            (403, "problems", False),
            (200, "hosts", True),
            (200, "security_problem_remediation_items", True),
            (500, None, False),
            (400, None, False),
            (302, None, False),
        ],
    )
    def test_status_mapping(self, status_code: int, schema_name: str | None, expected_valid: bool) -> None:
        is_valid, error = self._validate(status_code, schema_name)
        assert is_valid is expected_valid
        if not expected_valid:
            assert error is not None

    def test_malformed_url_fails_without_network(self) -> None:
        with scripted_network([]) as network:
            is_valid, error = validate_credentials("ftp://example.com", "token")
        assert is_valid is False
        assert error is not None
        assert network.requests_log == []
        assert network.session_options == []

    def test_request_exception_is_caught(self) -> None:
        with scripted_network(always(requests.exceptions.ConnectionError("boom"))) as network:
            is_valid, error = validate_credentials(BASE_URL, "token")
        assert is_valid is False
        assert error is not None
        assert {request.path for request in network.requests_log} == {"/api/v2/problems"}


class TestCheckEndpointPermissions:
    def test_403_reports_missing_scope_and_shares_probe_across_entity_tables(self) -> None:
        with scripted_network([ScriptedResponse(), ScriptedResponse(status=403)]) as network:
            results = check_endpoint_permissions(
                BASE_URL, "token", ["problems", "hosts", "services", "applications", "process_groups"], team_id=1
            )

        assert results["problems"] is None
        for endpoint in ("hosts", "services", "applications", "process_groups"):
            reason = results[endpoint]
            assert reason is not None
            assert "entities.read" in reason
        # The four entity tables share the entities.read scope, so one probe covers them all.
        assert [request.path for request in network.requests_log] == ["/api/v2/problems", "/api/v2/entities"]

    def test_metric_data_points_reports_the_missing_metric_keys_instead_of_probing(self) -> None:
        # Nothing about the token stops this table syncing — the user has not said which metrics
        # to read — so the picker must say that rather than run a probe that cannot answer it.
        with scripted_network([]) as network:
            results = check_endpoint_permissions(BASE_URL, "token", ["metric_data_points"], team_id=1)

        assert results["metric_data_points"] == METRIC_SELECTOR_REQUIRED_ERROR
        assert network.requests_log == []

    def test_network_blip_is_not_reported_as_missing_permission(self) -> None:
        with scripted_network(always(requests.exceptions.ConnectionError("boom"))) as network:
            results = check_endpoint_permissions(BASE_URL, "token", ["problems"], team_id=1)

        assert results == {"problems": None}
        assert {request.path for request in network.requests_log} == {"/api/v2/problems"}


class TestBuildUrl:
    def test_no_params(self) -> None:
        assert _build_url(BASE_URL, "/api/v2/metrics", {}) == f"{BASE_URL}/api/v2/metrics"
