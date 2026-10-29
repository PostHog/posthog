from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.twenty import TwentySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.twenty import twenty as twenty_module
from products.warehouse_sources.backend.temporal.data_imports.sources.twenty.source import TwentySource
from products.warehouse_sources.backend.temporal.data_imports.sources.twenty.twenty import (
    TwentyHostNotAllowedError,
    TwentyResumeConfig,
    _format_filter_value,
    normalize_base_url,
    validate_credentials,
)


def _page(
    rows: list[dict[str, Any]],
    *,
    object_name: str = "companies",
    has_next_page: bool = False,
    end_cursor: str | None = None,
) -> ScriptedResponse:
    body: dict[str, Any] = {
        "data": {object_name: rows},
        "totalCount": len(rows),
        "pageInfo": {"hasNextPage": has_next_page, "startCursor": None, "endCursor": end_cursor},
    }
    return ScriptedResponse(json=body)


def _run(
    script: Script,
    *,
    base_url: str | None = None,
    endpoint: str = "companies",
    resume_state: TwentyResumeConfig | None = None,
    **kwargs: Any,
) -> DriveResult:
    driver = SourceDriver(TwentySource(), TwentySourceConfig(api_key="tok", base_url=base_url))
    return driver.run(endpoint, script, resume_state=resume_state, **kwargs)


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, "https://api.twenty.com"),
            ("", "https://api.twenty.com"),
            ("   ", "https://api.twenty.com"),
            ("https://api.twenty.com", "https://api.twenty.com"),
            ("https://api.twenty.com/", "https://api.twenty.com"),
            ("https://api.twenty.com/rest", "https://api.twenty.com"),
            ("twenty.example.com", "https://twenty.example.com"),
            ("http://twenty.example.com/", "http://twenty.example.com"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_base_url(raw) == expected


class TestHostOf:
    @pytest.mark.parametrize(
        "url, expected_host",
        [
            ("https://twenty.example.com", "twenty.example.com"),
            # A backslash — literal or `%5c`-encoded — is an SSRF vector: `urlparse` and
            # requests/urllib3 disagree on the host, so the check could validate a decoy host while
            # the request reaches an internal address. No legitimate URL contains one, so `_host_of`
            # fails closed and returns "" (rejected upstream).
            ("https://safe.com\\@169.254.169.254", ""),
            ("https://safe.com%5c@169.254.169.254", ""),
            ("https://safe.com%5C@169.254.169.254", ""),
        ],
    )
    def test_host_rejects_backslash_ssrf_bypass(self, url, expected_host):
        assert twenty_module._host_of(url) == expected_host


class TestFormatFilterValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (datetime(2024, 1, 1, 12, 30, 0, tzinfo=UTC), "2024-01-01T12:30:00.000Z"),
            (datetime(2024, 1, 1, 12, 30, 0), "2024-01-01T12:30:00.000Z"),
            (date(2024, 1, 1), "2024-01-01"),
            ("2024-01-01T00:00:00.000Z", "2024-01-01T00:00:00.000Z"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_filter_value(value) == expected


class TestValidateCredentials:
    @staticmethod
    def _status(status_code: int) -> Script:
        return always(ScriptedResponse(status=status_code, json={}))

    def test_invalid_key_401(self):
        with scripted_network(self._status(401)):
            valid, msg = validate_credentials(None, "tok", team_id=1)
            assert valid is False
            assert "Invalid Twenty API key" in (msg or "")

    def test_permission_403_at_source_create_is_accepted(self):
        with scripted_network(self._status(403)):
            assert validate_credentials(None, "tok", team_id=1, schema_name=None) == (True, None)

    def test_permission_403_for_scoped_probe_fails(self):
        with scripted_network(self._status(403)):
            valid, msg = validate_credentials(None, "tok", team_id=1, schema_name="companies")
            assert valid is False
            assert msg is not None

    def test_unexpected_status(self):
        with scripted_network(self._status(500)):
            valid, msg = validate_credentials(None, "tok", team_id=1)
            assert valid is False
            assert "500" in (msg or "")

    def test_blocks_unsafe_host(self):
        with (
            mock.patch.object(twenty_module, "_is_host_safe", return_value=(False, "internal address")),
            scripted_network(self._status(200)) as network,
        ):
            valid, msg = validate_credentials("http://10.0.0.1", "tok", team_id=99)
            assert valid is False
            assert msg == "internal address"
            assert network.requests_log == []

    def test_rejects_plaintext_http_before_sending_token(self):
        with scripted_network(self._status(200)) as network:
            valid, msg = validate_credentials("http://twenty.example.com", "tok", team_id=1)
            assert valid is False
            assert msg == twenty_module.HTTP_NOT_ALLOWED_ERROR
            assert network.requests_log == []

    def test_probe_hits_configured_host_with_bearer_token(self):
        with scripted_network(self._status(200)) as network:
            validate_credentials("https://twenty.example.com", "tok", team_id=1)
            request = network.requests_log[0]
            assert request.url == "https://twenty.example.com/rest/companies?limit=1"
            assert request.headers["authorization"] == "Bearer tok"

    def test_probe_does_not_follow_redirects(self):
        redirect = ScriptedResponse(status=302, headers={"Location": "https://attacker.example/steal"})
        with scripted_network(always(redirect)) as network:
            valid, _msg = validate_credentials("https://twenty.example.com", "tok", team_id=1)
            assert valid is False
            assert {request.origin for request in network.requests_log} == {"https://twenty.example.com"}

    def test_redacts_token_in_telemetry(self):
        with scripted_network(self._status(200)) as network:
            validate_credentials(None, "tok", team_id=1)
            assert network.session_options[0]["redact_values"] == ("tok",)


class TestPagination:
    def test_paginates_via_cursor(self):
        result = _run(
            [
                _page([{"id": "1"}, {"id": "2"}], has_next_page=True, end_cursor="cursor-a"),
                _page([{"id": "3"}], has_next_page=False, end_cursor="cursor-b"),
            ]
        )

        assert [r["id"] for r in result.rows] == ["1", "2", "3"]
        assert result.params("starting_after") == [None, "cursor-a"]
        assert result.requests[0].param("limit") == "200"

    def test_resumes_from_saved_state(self):
        result = _run(
            [_page([{"id": "9"}], has_next_page=False)],
            resume_state=TwentyResumeConfig(starting_after="cursor-a"),
        )

        assert result.requests[0].param("starting_after") == "cursor-a"
        assert [r["id"] for r in result.rows] == ["9"]

    def test_does_not_follow_redirects(self):
        redirect = ScriptedResponse(status=302, headers={"Location": "https://attacker.example/steal"})

        result = _run(always(redirect))

        assert result.raised is not None
        assert {request.origin for request in result.requests} == {"https://api.twenty.com"}

    def test_redacts_token_in_telemetry(self):
        result = _run([_page([{"id": "1"}])])

        assert result.session_options[0]["redact_values"] == ("tok",)

    def test_raises_when_host_not_allowed(self):
        with mock.patch.object(twenty_module, "_is_host_safe", return_value=(False, "internal address")):
            result = _run([_page([{"id": "1"}])])

        assert isinstance(result.raised, TwentyHostNotAllowedError)

    def test_raises_on_plaintext_http(self):
        result = _run([_page([{"id": "1"}])], base_url="http://twenty.example.com")

        assert isinstance(result.raised, TwentyHostNotAllowedError)
        assert result.requests == []

    def test_incremental_first_sync_omits_filter(self):
        # No watermark yet (first incremental sync): the filter param is dropped entirely rather
        # than sending a malformed value, so the full history is pulled.
        result = _run(
            [_page([{"id": "1"}])],
            should_use_incremental_field=True,
            incremental_field="updatedAt",
            db_incremental_field_last_value=None,
        )

        request = result.requests[0]
        assert request.param("order_by") == "updatedAt[AscNullsFirst]"
        assert "filter" not in request.query

    def test_incremental_defaults_to_updated_at_when_field_unset(self):
        result = _run(
            [_page([{"id": "1"}])],
            should_use_incremental_field=True,
            incremental_field=None,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )

        assert result.requests[0].param("order_by") == "updatedAt[AscNullsFirst]"
