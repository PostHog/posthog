from datetime import UTC, date, datetime
from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.salesloft import (
    SalesLoftSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.salesloft import (
    SALESLOFT_BASE_URL,
    SalesloftResumeConfig,
    _build_params,
    _format_datetime,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.settings import SALESLOFT_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.salesloft.source import SalesLoftSource


def _response(items: list[dict[str, Any]] | None, next_page: int | None, status: int = 200) -> ScriptedResponse:
    body: dict[str, Any] = {"data": items or [], "metadata": {"paging": {"per_page": 100, "next_page": next_page}}}
    return ScriptedResponse(status=status, json=body)


def _driver() -> SourceDriver:
    return SourceDriver(SalesLoftSource(), SalesLoftSourceConfig(api_key="sl_token"))


class TestFormatDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("already-a-string", "already-a-string"),
        ],
    )
    def test_format_datetime(self, value: object, expected: str) -> None:
        result = _format_datetime(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildParams:
    def test_falls_back_to_updated_at_when_field_missing(self) -> None:
        params = _build_params(
            SALESLOFT_ENDPOINTS["accounts"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field=None,
        )
        assert "updated_at[gte]" in params


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code, expected) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("sl_token") is expected

        request = network.requests_log[0]
        assert request.url == f"{SALESLOFT_BASE_URL}/me"
        assert request.headers["authorization"] == "Bearer sl_token"


class TestPagination:
    def test_paginates_until_next_page_is_null(self) -> None:
        result = _driver().run(
            "people", [_response([{"id": 1}, {"id": 2}], next_page=2), _response([{"id": 3}], next_page=None)]
        )

        assert [row["id"] for row in result.rows] == [1, 2, 3]
        assert len(result.requests) == 2
        # First request carries the static params; the next page rides the `page` cursor.
        assert result.requests[0].param("per_page") == "100"
        assert result.requests[0].param("page") is None
        assert result.requests[1].param("page") == "2"

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "people", [_response([{"id": 9}], next_page=None)], resume_state=SalesloftResumeConfig(next_page=5)
        )

        assert [row["id"] for row in result.rows] == [9]
        assert result.requests[0].param("page") == "5"

    def test_resumes_from_legacy_next_url_state(self) -> None:
        legacy = SalesloftResumeConfig(next_url=f"{SALESLOFT_BASE_URL}/people?per_page=100&page=7")

        result = _driver().run("people", [_response([{"id": 9}], next_page=None)], resume_state=legacy)

        assert result.requests[0].param("page") == "7"

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _driver().run("people", [_response([{"id": 9}], next_page=None)])

        assert result.requests[0].param("page") is None

    def test_non_retryable_status_raises(self) -> None:
        result = _driver().run("people", [_response(None, next_page=None, status=404)])

        assert isinstance(result.raised, requests.HTTPError)


class TestSalesloftSource:
    def test_partition_key_is_always_created_at_never_updated_at(self) -> None:
        for config in SALESLOFT_ENDPOINTS.values():
            assert config.partition_key in (None, "created_at")
