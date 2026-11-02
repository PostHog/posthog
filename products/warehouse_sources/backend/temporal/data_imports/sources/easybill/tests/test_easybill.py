from datetime import UTC, date, datetime
from typing import Any

import pytest

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.easybill.easybill import (
    EasybillResumeConfig,
    date_range_since,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.easybill.settings import EASYBILL_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.easybill.source import EasybillSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.easybill import (
    EasybillSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(EasybillSource(), EasybillSourceConfig(api_key="key"))


def _response(
    items: list[dict[str, Any]] | None,
    *,
    page: int = 1,
    pages: int = 1,
    status: int = 200,
    body_override: dict[str, Any] | None = None,
) -> ScriptedResponse:
    body: dict[str, Any] = (
        body_override
        if body_override is not None
        else {
            "page": page,
            "pages": pages,
            "limit": 1000,
            "total": len(items or []),
            "items": items or [],
        }
    )
    return ScriptedResponse(status=status, json=body)


class TestDateRangeSince:
    @parameterized.expand(
        [
            ("datetime", datetime(2024, 3, 10, 12, 0, tzinfo=UTC), f"2024-03-09,{date.today().isoformat()}"),
            ("date", date(2024, 3, 10), f"2024-03-09,{date.today().isoformat()}"),
            ("iso_string", "2024-03-10T00:00:00+00:00", f"2024-03-09,{date.today().isoformat()}"),
            ("iso_string_z", "2024-03-10T00:00:00Z", f"2024-03-09,{date.today().isoformat()}"),
            ("plain_date_string", "2024-03-10", f"2024-03-09,{date.today().isoformat()}"),
            ("none", None, None),
            ("garbage_string", "not-a-date", None),
        ]
    )
    def test_date_range_since(self, _name: str, value: Any, expected: str | None) -> None:
        assert date_range_since(value) == expected


class TestIncrementalParams:
    def test_documents_incremental_adds_edited_at_range(self) -> None:
        result = _driver().run(
            "Documents",
            [_response([{"id": 1}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2024, 3, 10),
        )

        assert result.raised is None
        assert result.requests[0].param("edited_at") == f"2024-03-09,{date.today().isoformat()}"
        assert result.requests[0].param("limit") == "1000"
        assert result.requests[0].param("page") == "1"

    def test_documents_first_sync_omits_filter(self) -> None:
        result = _driver().run(
            "Documents",
            [_response([{"id": 1}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        assert result.raised is None
        assert result.requests[0].param("edited_at") is None

    @parameterized.expand(
        ["DocumentPayments", "IncomingDocuments", "Customers", "Positions", "Projects", "CustomerGroups"]
    )
    def test_non_incremental_endpoints_never_filter(self, endpoint: str) -> None:
        result = _driver().run(
            endpoint,
            [_response([{"id": 1}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2024, 3, 10),
        )

        assert result.raised is None
        assert result.requests[0].param("edited_at") is None


class TestPagination:
    def test_paginates_until_last_page(self) -> None:
        result = _driver().run(
            "Customers",
            [
                _response([{"id": 1}], page=1, pages=2),
                _response([{"id": 2}], page=2, pages=2),
            ],
        )

        assert result.raised is None
        assert [r["id"] for r in result.rows] == [1, 2]
        assert result.params("page") == ["1", "2"]
        assert len(result.requests) == 2
        assert result.saved_states == [EasybillResumeConfig(page=2)]

    def test_single_page_makes_one_request(self) -> None:
        result = _driver().run("Customers", [_response([{"id": 1}])])

        assert result.raised is None
        assert [r["id"] for r in result.rows] == [1]
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_empty_first_page_stops(self) -> None:
        result = _driver().run("Customers", [_response([])])

        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 1

    def test_resumes_from_saved_page(self) -> None:
        result = _driver().run(
            "Customers",
            [_response([{"id": 2}], page=2, pages=2)],
            resume_state=EasybillResumeConfig(page=2),
        )

        assert result.raised is None
        assert [r["id"] for r in result.rows] == [2]
        assert result.params("page") == ["2"]
        assert len(result.requests) == 1


class TestSourceResponseShape:
    @parameterized.expand(
        [
            ("Documents", "documents", "created_at"),
            ("IncomingDocuments", "incoming_documents", "created_at"),
            ("Customers", "customers", "created_at"),
            ("Positions", "positions", None),
            ("Projects", "projects", None),
            ("CustomerGroups", "customer_groups", None),
            ("DocumentPayments", "document_payments", None),
        ]
    )
    def test_response_shape(self, endpoint: str, table_name: str, partition_key: str | None) -> None:
        result = _driver().run(endpoint, [_response([])])
        response = result.response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert EASYBILL_ENDPOINTS[endpoint].table_name == table_name
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"
            assert response.partition_keys == [partition_key]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("key") is expected

        assert network.requests_log[0].path == "/rest/v1/customers"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer key"


class TestRetryAndErrors:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status_code: int) -> None:
        # easybill enforces a strict per-minute rate limit (10/min on PLUS, 60/min on BUSINESS)
        # returned as 429; the shared client retries on status so one throttle doesn't fail the sync.
        result = _driver().run(
            "Customers",
            [
                _response(None, status=status_code, body_override={"error": "transient"}),
                _response([{"id": 1}]),
            ],
        )

        assert result.raised is None
        assert [r["id"] for r in result.rows] == [1]
        assert len(result.requests) == 2

    def test_client_error_fails_loud(self) -> None:
        result = _driver().run(
            "Customers",
            [_response(None, status=401, body_override={"error": "unauthorized"})],
        )

        assert isinstance(result.raised, HTTPError)


if __name__ == "__main__":
    pytest.main([__file__])
