from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.xmatters import (
    XmattersSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.xmatters.source import XmattersSource
from products.warehouse_sources.backend.temporal.data_imports.sources.xmatters.xmatters import (
    PAGE_SIZE,
    XmattersResumeConfig,
    _base_url,
    _format_incremental_value,
    is_valid_subdomain,
    validate_credentials,
)


def _response(items: list[dict[str, Any]], next_url: Optional[str] = None) -> ScriptedResponse:
    body: dict[str, Any] = {"count": len(items), "total": len(items), "data": items}
    if next_url is not None:
        body["links"] = {"next": next_url}
    return ScriptedResponse(json=body)


def _driver() -> SourceDriver:
    return SourceDriver(XmattersSource(), XmattersSourceConfig(subdomain="acme", username="svc", password="secret"))


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            (date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("already-a-cursor", "already-a-cursor"),
        ],
    )
    def test_format(self, value: Any, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestSubdomainValidation:
    # An editor-controlled subdomain like `attacker.example/` would make the worker send its
    # requests (and Basic auth header) to an arbitrary host instead of *.xmatters.com (SSRF).
    @pytest.mark.parametrize(
        "subdomain",
        [
            "attacker.example/",
            "user@evil.example",
            "acme.evil.example",
            "127.0.0.1:8443/",
            "acme/path",
            "acme?x=",
            "acme#frag",
            "",
            "-acme",
            "acme-",
            "a" * 64,
        ],
    )
    def test_hostile_subdomains_rejected(self, subdomain: str) -> None:
        assert is_valid_subdomain(subdomain) is False
        with pytest.raises(ValueError):
            _base_url(subdomain)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_ok,expected_status",
        [
            (200, True, 200),
            (401, False, 401),
            (403, False, 403),
            (500, False, 500),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_ok: bool, expected_status: int) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))):
            ok, status, _error = validate_credentials("acme", "svc", "secret")
        assert ok is expected_ok
        assert status == expected_status


class TestPagination:
    def test_advances_offset_and_sets_page_params(self) -> None:
        result = _driver().run(
            "events",
            [_response([{"id": "1"}], next_url="/api/xm/1/events?offset=1000"), _response([{"id": "2"}])],
        )

        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        assert result.requests[0].param("limit") == str(PAGE_SIZE)

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "events", [_response([{"id": "x"}])], resume_state=XmattersResumeConfig(offset=PAGE_SIZE)
        )

        assert result.requests[0].param("offset") == str(PAGE_SIZE)

    def test_empty_page_stops_with_one_request_and_no_checkpoint(self) -> None:
        result = _driver().run("events", [_response([], next_url="/api/xm/1/events?offset=1000")])

        assert result.rows == []
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_events_incremental_sends_from_and_sort(self) -> None:
        result = _driver().run(
            "events",
            [_response([{"id": "1"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        request = result.requests[0]
        assert request.param("from") == "2026-01-01T00:00:00+00:00"
        assert request.param("sortBy") == "START_TIME"
        assert request.param("sortOrder") == "ASCENDING"
