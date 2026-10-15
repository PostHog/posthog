from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sendowl import (
    SendowlSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.sendowl import (
    PER_PAGE,
    SendowlResumeConfig,
    check_access,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.settings import (
    ENDPOINTS,
    SENDOWL_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.source import SendowlSource


def _driver() -> SourceDriver:
    return SourceDriver(SendowlSource(), SendowlSourceConfig(api_key="sendowl-key", api_secret="sendowl-secret"))


def _wrapped(wrapper_key: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # SendOwl returns each list item under a single-key wrapper, e.g. `{"product": {...}}`.
    return [{wrapper_key: row} for row in rows]


def _page(wrapper_key: str, rows: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json=_wrapped(wrapper_key, rows))


def _body_response(status: int, body: Any) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


class TestPagination:
    def test_resumes_from_saved_page(self) -> None:
        full_page = [{"id": i} for i in range(PER_PAGE)]

        result = _driver().run(
            "products",
            [_page("product", full_page), _page("product", [{"id": 7}])],
            resume_state=SendowlResumeConfig(next_page=2),
        )

        # Page 1 must never be fetched on resume; the first request targets the saved page.
        assert result.requests[0].param("page") == "2"
        assert result.rows == [*full_page, {"id": 7}]


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_retry_then_raise(self, _name: str, status: int) -> None:
        result = _driver().run("products", always(_body_response(status, {})))

        assert isinstance(result.raised, RESTClientRetryableError)
        # DEFAULT_RETRY_ATTEMPTS attempts are made before the retryable error is reraised.
        assert len(result.requests) == 5

    @parameterized.expand([("dict_body", {"error": "unexpected"}), ("bare_string", "nope")])
    def test_non_list_body_is_retryable(self, _name: str, body: Any) -> None:
        result = _driver().run("products", always(_body_response(200, body)))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_immediately(self, _name: str, status: int) -> None:
        result = _driver().run("products", [_body_response(status, [])])

        assert isinstance(result.raised, requests.HTTPError)
        # A non-retryable client error is not retried.
        assert len(result.requests) == 1


class TestCheckAccess:
    @parameterized.expand(
        [
            ("reachable", 200, 200, None),
            ("unauthorized", 401, 401, None),
            ("forbidden", 403, 403, None),
            ("server_error", 500, 500, "SendOwl returned HTTP 500"),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_status: int, expected_message: str | None) -> None:
        with scripted_network(always(_body_response(status, {}))):
            assert check_access("sendowl-key", "sendowl-secret") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self) -> None:
        # validate_via_probe swallows the transport error, so the probe reports "not validated".
        with scripted_network(always(requests.ConnectionError("boom"))):
            assert check_access("sendowl-key", "sendowl-secret") == (0, "Could not connect to SendOwl")


class TestSendowlSourceResponse:
    @parameterized.expand([("products",), ("orders",), ("subscriptions",), ("discount_codes",)])
    def test_response_uses_id_primary_key(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])

        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]
        assert result.response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in SENDOWL_ENDPOINTS.values())
        assert set(SENDOWL_ENDPOINTS) == set(ENDPOINTS)
