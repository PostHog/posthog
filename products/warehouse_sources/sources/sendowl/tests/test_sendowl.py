from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.sdk import RESTClientRetryableError
from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
    always,
)
from products.warehouse_sources.sources.sendowl._config import SendowlSourceConfig
from products.warehouse_sources.sources.sendowl.sendowl import PER_PAGE, SENDOWL_BASE_URL, SendowlResumeConfig
from products.warehouse_sources.sources.sendowl.settings import ENDPOINTS, SENDOWL_ENDPOINTS
from products.warehouse_sources.sources.sendowl.source import SendowlSource


def _driver() -> SourceDriver:
    return SourceDriver(SendowlSource(), SendowlSourceConfig(api_key="sendowl-key", api_secret="sendowl-secret"))


def _wrapped(wrapper_key: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # SendOwl returns each list item under a single-key wrapper, e.g. `{"product": {...}}`.
    return [{wrapper_key: row} for row in rows]


def _page(wrapper_key: str, rows: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json=_wrapped(wrapper_key, rows))


def _body_response(status: int, body: Any) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


def _by_url(responses_by_url: dict[str, list[ScriptedResponse]]) -> Callable[[RecordedRequest], ScriptedResponse]:
    def _norm(url: str) -> tuple[str, tuple[tuple[str, str], ...]]:
        parts = urlsplit(url)
        return parts.path, tuple(sorted(parse_qsl(parts.query)))

    queues = {_norm(url): list(queue) for url, queue in responses_by_url.items()}

    def respond(request: RecordedRequest) -> ScriptedResponse:
        queue = queues.get(_norm(request.url))
        if not queue:
            raise UnexpectedRequest(f"unexpected request url {request.url!r}")
        return queue.pop(0)

    return respond


def _url(path: str, page: int = 1) -> str:
    return f"{SENDOWL_BASE_URL}{path}?per_page={PER_PAGE}&page={page}"


def _license(license_id: int, product_id: int) -> dict[str, Any]:
    return {"id": license_id, "product_id": product_id, "order_id": None, "order_refunded": False, "key": "TEST-KEY"}


class TestLicensesFanout:
    def test_walks_every_page_of_each_software_product_and_skips_other_products(self) -> None:
        full_page = [_license(i, 1) for i in range(PER_PAGE)]
        responses = {
            _url("/api/v1/products"): [
                _page(
                    "product",
                    [
                        {"id": 1, "product_type": "software"},
                        {"id": 2, "product_type": "digital"},
                        {"id": 3, "product_type": "software"},
                    ],
                )
            ],
            _url("/api/v1/products/1/licenses"): [_page("license", full_page)],
            _url("/api/v1/products/1/licenses", page=2): [_page("license", [_license(100, 1)])],
            _url("/api/v1/products/3/licenses"): [_page("license", [_license(200, 3)])],
        }

        result = _driver().run("licenses", _by_url(responses))

        assert result.raised is None
        assert result.rows == [*full_page, _license(100, 1), _license(200, 3)]
        assert all("/products/2/" not in request.url for request in result.requests)

    def test_product_deleted_before_its_licenses_are_fetched_is_skipped(self) -> None:
        responses = {
            _url("/api/v1/products"): [
                _page("product", [{"id": 1, "product_type": "software"}, {"id": 2, "product_type": "software"}])
            ],
            _url("/api/v1/products/1/licenses"): [_body_response(404, {"error": "not found"})],
            _url("/api/v1/products/2/licenses"): [_page("license", [_license(7, 2)])],
        }

        result = _driver().run("licenses", _by_url(responses))

        assert result.raised is None
        assert result.rows == [_license(7, 2)]

    @parameterized.expand([("parent_listing_from_start", None, 1), ("parent_listing_from_saved_page", 2, 2)])
    def test_resumes_mid_product_from_the_saved_page(
        self, _name: str, saved_parent_page: int | None, expected_parent_page: int
    ) -> None:
        responses = {
            _url("/api/v1/products", page=expected_parent_page): [
                _page("product", [{"id": 1, "product_type": "software"}, {"id": 2, "product_type": "software"}])
            ],
            _url("/api/v1/products/2/licenses", page=3): [_page("license", [_license(9, 2)])],
        }
        fanout_state: dict[str, Any] = {
            "completed": ["/api/v1/products/1/licenses"],
            "current": "/api/v1/products/2/licenses",
            "child_state": {"page": 3},
        }
        if saved_parent_page is not None:
            fanout_state["parent"] = {"page": saved_parent_page}

        result = _driver().run(
            "licenses", _by_url(responses), resume_state=SendowlResumeConfig(fanout_state=fanout_state)
        )

        assert result.raised is None
        assert result.rows == [_license(9, 2)]


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


class TestSendowlSourceResponse:
    @parameterized.expand(
        [("products",), ("bundles",), ("orders",), ("subscriptions",), ("discount_codes",), ("licenses",)]
    )
    def test_response_uses_id_primary_key(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])

        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]
        assert result.response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in SENDOWL_ENDPOINTS.values())
        assert set(SENDOWL_ENDPOINTS) == set(ENDPOINTS)
