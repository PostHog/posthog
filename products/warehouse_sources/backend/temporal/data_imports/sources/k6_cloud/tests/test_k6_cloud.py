from datetime import UTC, date, datetime
from typing import Any

import pytest

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.k6cloud import (
    K6CloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.k6_cloud.k6_cloud import (
    K6_CLOUD_BASE_URL,
    K6CloudResumeConfig,
    _absolute_url,
    _format_rfc3339,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.k6_cloud.source import K6CloudSource


def _driver() -> SourceDriver:
    return SourceDriver(K6CloudSource(), K6CloudSourceConfig(api_token="tok", stack_id="1"))


def _page(
    value: list[dict[str, Any]] | None = None,
    *,
    next_link: str | None = None,
    drop_value: bool = False,
    status: int = 200,
) -> ScriptedResponse:
    body: dict[str, Any] = {}
    if not drop_value:
        body["value"] = value or []
    if next_link is not None:
        body["@nextLink"] = next_link
    return ScriptedResponse(status=status, json=body)


class TestFormatRfc3339:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            ("microseconds", datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string_passthrough", "some-cursor", "some-cursor"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        result = _format_rfc3339(value)
        assert result == expected
        assert "+00:00" not in result


class TestAbsoluteUrl:
    @parameterized.expand(
        [
            (
                "absolute_https",
                "https://api.k6.io/cloud/v6/test_runs",
                "https://api.k6.io/cloud/v6/test_runs?$skip=1000",
                "https://api.k6.io/cloud/v6/test_runs?$skip=1000",
            ),
            (
                "relative_path",
                "https://api.k6.io/cloud/v6/test_runs",
                "/cloud/v6/test_runs?$skip=1000",
                "https://api.k6.io/cloud/v6/test_runs?$skip=1000",
            ),
        ]
    )
    def test_absolute_url(self, _name: str, current: str, next_link: str, expected: str) -> None:
        assert _absolute_url(current, next_link) == expected

    @parameterized.expand(
        [
            ("other_host", "https://evil.example.com/steal"),
            ("relative_to_other_host", "//evil.example.com/steal"),
            ("http_scheme", "http://api.k6.io/cloud/v6/test_runs"),
        ]
    )
    def test_rejects_non_k6_next_link(self, _name: str, next_link: str) -> None:
        # A tampered `@nextLink` must never redirect the credential-bearing request off the k6 origin.
        with pytest.raises(ValueError):
            _absolute_url("https://api.k6.io/cloud/v6/test_runs", next_link)


class TestPagination:
    def test_follows_next_link_and_progresses(self) -> None:
        next_url = "https://api.k6.io/cloud/v6/test_runs?$skip=1000&$top=1000"
        result = _driver().run(
            "test_runs",
            [
                _page([{"id": 1}, {"id": 2}], next_link=next_url),
                _page([{"id": 3}]),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        # Second request follows the @nextLink URL rather than re-hitting the base path.
        assert result.paths == ["/cloud/v6/test_runs", "/cloud/v6/test_runs"]
        assert result.urls[1] == next_url
        assert result.params("$skip") == [None, "1000"]

    def test_test_runs_never_sends_orderby(self) -> None:
        # The top-level test_runs endpoint rejects $orderby, so it must never be sent there.
        result = _driver().run("test_runs", [_page([{"id": 1}])])

        assert result.raised is None
        assert result.requests[0].param("$orderby") is None

    def test_missing_value_key_raises_loudly(self) -> None:
        # A 200 body without `value` is an unexpected shape — fail loud rather than empty the table.
        result = _driver().run("load_zones", [_page(drop_value=True)])

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestDistributionFanOut:
    def test_follows_parent_next_link(self) -> None:
        next_url = "https://api.k6.io/cloud/v6/test_runs?$skip=1000&$top=1000"
        zone = {"distribution": {"amazon:us:ashburn": {"percentage": 100, "nodes": []}}}
        result = _driver().run(
            "test_run_distribution",
            [
                _page([{"id": 1, "created": "2026-03-04T00:00:00Z"}], next_link=next_url),
                ScriptedResponse(json=zone),
                _page([{"id": 2, "created": "2026-03-05T00:00:00Z"}]),
                ScriptedResponse(json=zone),
            ],
        )

        assert result.raised is None
        assert [row["test_run_id"] for row in result.rows] == [1, 2]
        assert result.urls[2] == next_url

    def test_success_body_without_distribution_raises(self) -> None:
        # A 200 without the required key is a shape change; silently emitting no rows would drop the
        # run from a full refresh.
        result = _driver().run(
            "test_run_distribution",
            [
                _page([{"id": 1, "created": "2026-03-04T00:00:00Z"}]),
                ScriptedResponse(json={}),
            ],
        )

        assert isinstance(result.raised, ValueError)
        assert "has no `distribution`" in str(result.raised)


class TestIncremental:
    def test_created_after_added_when_last_value_present(self) -> None:
        result = _driver().run(
            "test_runs",
            [_page([{"id": 1}])],
            incremental_field="created",
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("created_after") == "2026-03-04T02:58:14.000Z"

    def test_projects_never_sends_time_filter(self) -> None:
        # Projects has no server-side time filter, so a passed-in watermark must not add one.
        result = _driver().run(
            "projects",
            [_page([{"id": 1}])],
            incremental_field="created",
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[0].param("created_after") is None


class TestResume:
    def test_resumes_from_saved_next_link(self) -> None:
        resume_url = "https://api.k6.io/cloud/v6/test_runs?$skip=2000&$top=1000"
        result = _driver().run(
            "test_runs",
            [_page([{"id": 9}])],
            resume_state=K6CloudResumeConfig(next_url=resume_url),
        )

        assert result.raised is None
        assert result.rows == [{"id": 9}]
        # The first (only) request goes straight to the saved next link, not the base path.
        assert result.urls == [resume_url]

    def test_rejects_poisoned_resume_url(self) -> None:
        # Resume state is loaded from Redis; a poisoned next link must not leak credentials off-origin.
        result = _driver().run(
            "test_runs",
            [],
            resume_state=K6CloudResumeConfig(next_url="https://evil.example.com/steal"),
        )

        assert isinstance(result.raised, ValueError)
        assert result.requests == []


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status: int) -> None:
        result = _driver().run("test_runs", [_page(status=status), _page([{"id": 1}])])

        assert result.raised is None
        assert result.rows == [{"id": 1}]
        assert len(result.requests) == 2

    def test_client_error_raises_immediately(self) -> None:
        # A 401 is not retryable — raise_for_status surfaces it on the first attempt.
        result = _driver().run("test_runs", [_page(status=401)])

        assert isinstance(result.raised, HTTPError)
        assert len(result.requests) == 1


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, (True, False)),
            ("bad_token", 401, None, (False, False)),
            ("forbidden", 403, None, (False, True)),
            ("forbidden_schema", 403, "test_runs", (False, True)),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, schema_name: str | None, expected: tuple[bool, bool]
    ) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert validate_credentials("tok", "1", schema_name) == expected

        assert len(network.requests_log) == 1

    def test_network_error_is_invalid_not_forbidden(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))):
            assert validate_credentials("tok", "1") == (False, False)

    def test_fan_out_schema_probes_parent_listing(self) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            validate_credentials("tok", "1", "test_run_distribution")

        assert network.requests_log[0].url == f"{K6_CLOUD_BASE_URL}/test_runs?%24top=1"
