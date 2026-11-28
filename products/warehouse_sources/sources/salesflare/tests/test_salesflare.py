from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.salesflare import salesflare
from products.warehouse_sources.sources.salesflare._config import SalesflareSourceConfig
from products.warehouse_sources.sources.salesflare.salesflare import PAGE_SIZE, SalesflareResumeConfig
from products.warehouse_sources.sources.salesflare.settings import ENDPOINTS, SALESFLARE_ENDPOINTS
from products.warehouse_sources.sources.salesflare.source import SalesflareSource
from products.warehouse_sources.sources.sdk import RESTClientRetryableError
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always

SINGLE_RESOURCE_ENDPOINTS = tuple(endpoint for endpoint in ENDPOINTS if endpoint != "custom_fields")


def _response(body: Any, *, status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body)


def _full_page(start_id: int) -> list[dict[str, Any]]:
    return [{"id": start_id + i} for i in range(PAGE_SIZE)]


def _driver() -> SourceDriver:
    return SourceDriver(SalesflareSource(), SalesflareSourceConfig(api_key="sf-key"))


class TestPagination:
    def test_paginates_and_progresses_offset(self) -> None:
        result = _driver().run("contacts", [_response(_full_page(0)), _response([{"id": 999}])])

        assert len(result.rows) == PAGE_SIZE + 1
        assert result.rows[-1] == {"id": 999}
        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        assert result.params("limit")[0] == str(PAGE_SIZE)
        # Checkpoint saved after the first full page (points at the next page); short page ends it.
        assert result.saved_states == [SalesflareResumeConfig(offset=PAGE_SIZE)]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run("contacts", [_response([{"id": 1}])], resume_state=SalesflareResumeConfig(offset=300))

        assert result.params("offset") == ["300"]

    @parameterized.expand([(e,) for e in SINGLE_RESOURCE_ENDPOINTS])
    def test_requests_the_endpoint_path(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_response([])])

        assert result.urls[0].split("?")[0] == f"{salesflare.SALESFLARE_BASE_URL}{SALESFLARE_ENDPOINTS[endpoint].path}"

    @parameterized.expand([(e, SALESFLARE_ENDPOINTS[e].paginated) for e in SINGLE_RESOURCE_ENDPOINTS])
    def test_only_paginated_endpoints_send_page_params(self, endpoint: str, paginated: bool) -> None:
        result = _driver().run(endpoint, [_response(_full_page(0)), _response([])])

        if paginated:
            assert result.params("offset") == ["0", str(PAGE_SIZE)]
            assert result.params("limit")[0] == str(PAGE_SIZE)
        else:
            assert len(result.requests) == 1
            assert result.urls[0] == f"{salesflare.SALESFLARE_BASE_URL}{SALESFLARE_ENDPOINTS[endpoint].path}"
            assert len(result.rows) == PAGE_SIZE


class TestCustomFields:
    @parameterized.expand([(True,), (False,)])
    def test_reads_all_item_classes(self, has_contact_fields: bool) -> None:
        contact_fields = [{"id": 17}] if has_contact_fields else []
        result = _driver().run(
            "custom_fields",
            [_response([{"id": 17}]), _response(contact_fields), _response([{"id": 17}])],
        )

        assert result.raised is None
        assert result.urls == [
            f"https://api.salesflare.com/customfields/{item_class}?includeDisabled=true"
            for item_class in ("accounts", "contacts", "opportunities")
        ]
        expected_rows = [{"id": 17, "item_class": "accounts"}, {"id": 17, "item_class": "opportunities"}]
        if has_contact_fields:
            expected_rows.insert(1, {"id": 17, "item_class": "contacts"})
        assert result.rows == expected_rows


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_are_retried_then_raise(self, _name: str, status: int) -> None:
        result = _driver().run("contacts", always(_response({"error": "nope"}, status_code=status)))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) > 1

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_immediately(self, _name: str, status: int) -> None:
        result = _driver().run("contacts", [_response({"error": "nope"}, status_code=status)])

        assert isinstance(result.raised, requests.HTTPError)
        # 4xx is not retryable — exactly one request is made.
        assert len(result.requests) == 1

    def test_non_list_body_is_retryable(self) -> None:
        # A 200 whose body isn't a bare array is a malformed payload — retried, then reraised.
        result = _driver().run("contacts", always(_response({"error": "nope"})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) > 1
