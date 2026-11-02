from datetime import UTC, date, datetime
from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import rest_client
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.retently import (
    RetentlySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.retently.retently import (
    RetentlyResumeConfig,
    _format_start_date,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.retently.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.retently.source import RetentlySource


def _run(endpoint: str, script: Script, **inputs: Any) -> DriveResult:
    return SourceDriver(RetentlySource(), RetentlySourceConfig(api_key="key")).run(endpoint, script, **inputs)


def _response(body: Any = None, *, status_code: int = 200, content: bytes | None = None) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body, body=content)


class TestFormatStartDate:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("epoch_passthrough", 1704067200, "1704067200"),
            ("string_passthrough", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        ]
    )
    def test_format_start_date(self, _name: str, value: object, expected: str) -> None:
        assert _format_start_date(value) == expected


class TestEnvelopeShapes:
    @parameterized.expand(
        [
            # Records nested under `data.<key>` — feedback, outbox, customers, companies.
            ("nested_in_data", "feedback", {"data": {"responses": [{"id": "1"}], "pages": 1}}, [{"id": "1"}]),
            # /reports returns a bare list under `data`.
            ("bare_list_under_data", "reports", {"data": [{"campaignId": "c1"}]}, [{"campaignId": "c1"}]),
            # Campaigns/templates document the array at the top level, outside `data`.
            ("top_level_array", "campaigns", {"campaigns": [{"id": "c1"}]}, [{"id": "c1"}]),
        ]
    )
    def test_documented_envelope_shapes_yield_rows(self, _name: str, endpoint: str, body: Any, expected: list) -> None:
        result = _run(endpoint, [_response(body)])
        assert result.rows == expected

    @parameterized.expand(
        [
            ("not_a_dict", [{"id": "1"}]),
            ("no_recognisable_array", {"data": {"total": 3, "tags": ["a"], "other": ["b"]}}),
        ]
    )
    def test_unexpected_payloads_are_retried_then_fail(self, _name: str, body: Any) -> None:
        # An unexpected 200-body shape is treated as transient: retried, and exhausting retries
        # raises rather than silently syncing garbage rows.
        result = _run("feedback", always(_response(body)))

        assert isinstance(result.raised, rest_client.RESTClientRetryableError)


class TestPagination:
    def test_top_level_pages_metadata_keeps_paginating(self) -> None:
        # The customers docs place `pages` at the top level; a short page must not end the loop
        # while the metadata says more pages exist (e.g. the API caps `limit` below our request).
        bodies = [
            {"data": {"subscribers": [{"id": "1"}]}, "page": 1, "pages": 2},
            {"data": {"subscribers": [{"id": "2"}]}, "page": 2, "pages": 2},
        ]
        result = _run("customers", [_response(b) for b in bodies])
        assert [r["id"] for r in result.rows] == ["1", "2"]
        assert len(result.requests) == 2

    def test_short_page_ends_loop_without_pages_metadata(self) -> None:
        result = _run("feedback", [_response({"data": {"responses": [{"id": "1"}]}})])
        assert result.rows == [{"id": "1"}]
        assert len(result.requests) == 1

    def test_empty_first_page_yields_nothing(self) -> None:
        result = _run("feedback", [_response({"data": {"responses": [], "page": 1, "pages": 0}})])
        assert result.rows == []
        assert len(result.requests) == 1

    @parameterized.expand(
        [
            ("campaigns", {"campaigns": [{"id": "c1"}]}),
            ("templates", {"templates": [{"id": "t1"}]}),
            ("reports", {"data": [{"campaignId": "c1"}]}),
        ]
    )
    def test_unpaginated_endpoints_make_one_request_without_page_params(self, endpoint: str, body: Any) -> None:
        result = _run(endpoint, [_response(body)])
        assert len(result.rows) == 1
        assert len(result.requests) == 1
        assert "page" not in result.requests[0].query
        assert "limit" not in result.requests[0].query


class TestIncremental:
    def test_start_date_sent_when_incremental(self) -> None:
        result = _run(
            "feedback",
            [_response({"data": {"responses": [{"id": "1"}], "pages": 1}})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert result.requests[0].param("startDate") == "2026-03-04T02:58:14Z"
        assert result.requests[0].param("sort") == "createdDate"

    @parameterized.expand(
        [
            ("full_refresh_run", False, datetime(2026, 3, 4, tzinfo=UTC)),
            ("first_incremental_run_has_no_watermark", True, None),
        ]
    )
    def test_start_date_omitted(self, _name: str, should_use: bool, last_value: Any) -> None:
        result = _run(
            "feedback",
            [_response({"data": {"responses": [{"id": "1"}], "pages": 1}})],
            should_use_incremental_field=should_use,
            db_incremental_field_last_value=last_value,
        )
        assert "startDate" not in result.requests[0].query


class TestResume:
    def test_resume_starts_from_saved_page(self) -> None:
        result = _run(
            "feedback",
            [_response({"data": {"responses": [{"id": "9"}], "page": 3, "pages": 3}})],
            resume_state=RetentlyResumeConfig(page=3),
        )
        assert result.rows == [{"id": "9"}]
        assert result.requests[0].param("page") == "3"


class TestRetries:
    @parameterized.expand(
        [
            ("rate_limited", _response({}, status_code=429)),
            ("server_error", _response({}, status_code=500)),
            # A truncated / partial JSON body (a page cut off mid-stream) starts like JSON but fails
            # to parse, so it must retry the single request, not fail the sync. A non-JSON body (e.g.
            # an HTML error page) is treated as non-retryable and is not covered here.
            ("truncated_body", _response(content=b'{"data": {"responses": [')),
        ]
    )
    def test_transient_failures_are_retried(self, _name: str, first_response: ScriptedResponse) -> None:
        responses = [first_response, _response({"data": {"responses": [{"id": "1"}], "pages": 1}})]
        result = _run("feedback", responses)
        assert result.rows == [{"id": "1"}]
        assert len(result.requests) == 2

    def test_auth_error_raises_immediately(self) -> None:
        result = _run("feedback", [_response({"message": "Account not found"}, status_code=401)])
        assert isinstance(result.raised, requests.HTTPError)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_ok: bool, expected_msg: str | None) -> None:
        with scripted_network(always(_response({}, status_code=status_code))) as network:
            ok, message = validate_credentials("key")
        assert ok is expected_ok
        if expected_msg is None:
            assert message is None
        else:
            assert message is not None and expected_msg in message
        assert network.requests_log[0].path.endswith("/ping")


class TestSourceResponse:
    @parameterized.expand(
        [
            ("customers", ["id"], "createdDate", "asc"),
            ("companies", ["id"], "createdDate", "asc"),
            # feedback is the only incremental endpoint: "desc" defers the watermark to the end of
            # a successful sync because the API's sort behavior could not be live-verified.
            ("feedback", ["id"], "createdDate", "desc"),
            ("outbox", None, None, "asc"),
            ("campaigns", ["id"], None, "asc"),
            ("templates", ["id"], None, "asc"),
            ("reports", ["campaignId"], None, "asc"),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str] | None, partition_key: str | None, sort_mode: str
    ) -> None:
        response = _run(endpoint, always(_response({}))).response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        if partition_key is None:
            assert response.partition_keys is None
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"

    @parameterized.expand(ENDPOINTS)
    def test_every_declared_endpoint_builds_a_response(self, endpoint: str) -> None:
        response = _run(endpoint, always(_response({}))).response
        assert response is not None
        assert response.name == endpoint
