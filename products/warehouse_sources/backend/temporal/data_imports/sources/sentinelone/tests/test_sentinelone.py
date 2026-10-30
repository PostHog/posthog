from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sentinelone import (
    SentineloneSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone import (
    sentinelone as sentinelone_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone.sentinelone import (
    SentinelOneHostNotAllowedError,
    SentinelOneResumeConfig,
    _build_initial_params,
    _format_incremental_value,
    _normalize_row,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone.settings import SENTINELONE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone.source import SentineloneSource


def _mock_response(
    *, status_code: int = 200, json_data: Any = None, location: Optional[str] = None
) -> ScriptedResponse:
    headers = {"Location": location} if location is not None else {}
    return ScriptedResponse(status=status_code, json=json_data, headers=headers)


def _page(rows: list[dict[str, Any]], next_cursor: str | None = None) -> dict[str, Any]:
    return {"data": rows, "pagination": {"nextCursor": next_cursor}}


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("already-a-cursor", "already-a-cursor"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_incremental_value(value) == expected


class TestBuildInitialParams:
    def test_incremental_builds_gte_filter_and_matching_sort(self):
        params = _build_initial_params(
            SENTINELONE_ENDPOINTS["threats"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="updatedAt",
        )
        assert params["updatedAt__gte"] == "2024-01-01T00:00:00.000Z"
        assert params["sortBy"] == "updatedAt"
        assert params["sortOrder"] == "asc"
        assert params["limit"] == 1000

    @pytest.mark.parametrize("endpoint", ["groups", "sites"])
    def test_full_refresh_only_endpoints_send_no_sort_or_filter(self, endpoint):
        params = _build_initial_params(
            SENTINELONE_ENDPOINTS[endpoint],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field=None,
        )
        assert params == {"limit": SENTINELONE_ENDPOINTS[endpoint].page_size}


class TestNormalizeRow:
    def test_hoists_threat_info_timestamps(self):
        row = {"id": "t1", "threatInfo": {"createdAt": "2024-01-01T00:00:00Z", "updatedAt": "2024-01-02T00:00:00Z"}}
        normalized = _normalize_row(row, SENTINELONE_ENDPOINTS["threats"])
        assert normalized["createdAt"] == "2024-01-01T00:00:00Z"
        assert normalized["updatedAt"] == "2024-01-02T00:00:00Z"


class TestValidateCredentials:
    def test_invalid_token(self):
        with scripted_network(always(_mock_response(status_code=401))):
            valid, msg = validate_credentials("example.sentinelone.net", "tok")
        assert valid is False
        assert msg == "Invalid SentinelOne API token"

    def test_403_at_source_create_is_accepted(self):
        with scripted_network(always(_mock_response(status_code=403))):
            assert validate_credentials("example.sentinelone.net", "tok", schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self):
        with scripted_network(always(_mock_response(status_code=403))):
            valid, msg = validate_credentials("example.sentinelone.net", "tok", schema_name="threats")
        assert valid is False
        assert msg is not None

    def test_create_probe_hits_system_info(self):
        with scripted_network(always(_mock_response(status_code=200))) as network:
            validate_credentials("example.sentinelone.net", "tok")
        assert network.requests_log[0].url == "https://example.sentinelone.net/web/api/v2.1/system/info"

    @pytest.mark.parametrize("bad_url", ["", "not a url!", "https://"])
    def test_invalid_console_url_short_circuits(self, bad_url):
        valid, msg = validate_credentials(bad_url, "tok")
        assert valid is False
        assert msg == "Invalid SentinelOne console URL"

    def test_rejects_redirect_response(self):
        # A validated host that 3xx-redirects (potentially to an internal address) must be
        # rejected, not followed (SSRF).
        with scripted_network([_mock_response(status_code=302, location="https://evil.example/")]) as network:
            valid, msg = validate_credentials("example.sentinelone.net", "tok")
        assert valid is False
        assert msg == sentinelone_module.HOST_NOT_ALLOWED_ERROR
        assert len(network.requests_log) == 1
        assert network.session_options[-1]["allow_redirects"] is False

    def test_blocks_unsafe_host(self):
        with (
            mock.patch.object(sentinelone_module, "_is_host_safe", return_value=(False, "internal address")),
            scripted_network(always(_mock_response(status_code=200))) as network,
        ):
            valid, msg = validate_credentials("10.0.0.1", "tok", team_id=99)
        assert valid is False
        assert msg == "internal address"
        assert network.requests_log == []

    def test_error_body_is_surfaced(self):
        body = {"errors": [{"title": "Bad request", "detail": "invalid filter"}]}
        with scripted_network(always(_mock_response(status_code=400, json_data=body))):
            valid, msg = validate_credentials("example.sentinelone.net", "tok")
        assert valid is False
        assert msg == "Bad request: invalid filter"


def _run(
    responses: list[ScriptedResponse],
    *,
    endpoint: str = "threats",
    resume_state: SentinelOneResumeConfig | None = None,
) -> DriveResult:
    driver = SourceDriver(
        SentineloneSource(), SentineloneSourceConfig(console_url="example.sentinelone.net", api_token="tok")
    )
    return driver.run(endpoint, responses, resume_state=resume_state)


class TestPagination:
    def test_follows_cursor_across_pages(self):
        result = _run(
            [
                _mock_response(json_data=_page([{"id": "1"}, {"id": "2"}], next_cursor="cur")),
                _mock_response(json_data=_page([{"id": "3"}])),
            ]
        )
        assert [r["id"] for r in result.rows] == ["1", "2", "3"]
        # The cursor is bound to the query it was minted against — non-cursor params carry over.
        assert result.requests[1].param("cursor") == "cur"
        assert result.requests[1].param("limit") == "1000"

    def test_resumes_from_saved_state(self):
        result = _run(
            [_mock_response(json_data=_page([{"id": "9"}]))],
            resume_state=SentinelOneResumeConfig(
                next_url="https://example.sentinelone.net/web/api/v2.1/threats?limit=1000&cursor=resume"
            ),
        )
        assert result.requests[0].param("cursor") == "resume"
        assert [r["id"] for r in result.rows] == ["9"]

    def test_ignores_resume_url_on_foreign_host(self):
        # A poisoned resume URL must fall back to a fresh start on the console host, not be followed.
        result = _run(
            [_mock_response(json_data=_page([{"id": "1"}]))],
            resume_state=SentinelOneResumeConfig(next_url="http://169.254.169.254/latest/meta-data/"),
        )
        assert result.requests[0].param("cursor") is None
        assert [r["id"] for r in result.rows] == ["1"]

    def test_empty_page_terminates_even_with_cursor(self):
        result = _run([_mock_response(json_data=_page([], next_cursor="cur"))])
        assert result.rows == []
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_redirect_response_is_rejected(self):
        # An unexpected 3xx (potentially to an internal address) must be rejected, not followed (SSRF).
        result = _run([_mock_response(status_code=302, location="https://evil.example/")])
        assert isinstance(result.raised, ValueError)


class TestRunTimeHostCheck:
    def test_unsafe_console_host_raises(self):
        # The console URL is re-validated at sync time; an internal address is refused before any request.
        with mock.patch.object(sentinelone_module, "_is_host_safe", return_value=(False, "internal address")):
            driver = SourceDriver(SentineloneSource(), SentineloneSourceConfig(console_url="10.0.0.1", api_token="tok"))
            result = driver.run("threats", [])
        assert isinstance(result.raised, SentinelOneHostNotAllowedError)
        assert result.requests == []
