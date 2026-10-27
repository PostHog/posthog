from collections.abc import Callable
from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    UnexpectedRequest,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.printify import (
    PrintifySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.printify import printify
from products.warehouse_sources.backend.temporal.data_imports.sources.printify.printify import (
    PrintifyResumeConfig,
    PrintifyRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.printify.settings import (
    ENDPOINTS,
    PRINTIFY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.printify.source import PrintifySource

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = printify._fetch_page.__wrapped__  # type: ignore[attr-defined]

# (path, page) -> (items, has_more), the shape the vendor answers per request.
_Pages = dict[tuple[str, int | None], tuple[list[dict], bool]]


def _script(pages: _Pages) -> Callable[[RecordedRequest], ScriptedResponse]:
    """Answer each (path, page) from `pages`. A request for a page that is not listed fails the run."""

    def respond(request: RecordedRequest) -> ScriptedResponse:
        page = request.param("page")
        key = (request.path.removeprefix("/v1"), int(page) if page is not None else None)
        if key not in pages:
            raise UnexpectedRequest(f"the script has no page for {key}")
        items, has_more = pages[key]
        if key[1] is None:
            return ScriptedResponse(json=items)
        current = key[1]
        return ScriptedResponse(
            json={"current_page": current, "last_page": current + 1 if has_more else current, "data": items}
        )

    return respond


def _driver() -> SourceDriver:
    return SourceDriver(PrintifySource(), PrintifySourceConfig(api_key="printify-key"))


class TestFetchPage:
    def _session_returning(
        self,
        status_code: int,
        body: Any = None,
        url: str = "https://api.printify.com/v1/shops.json",
        reason: str = "Error",
    ) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else []
        response.text = ""
        response.url = url
        response.reason = reason
        session = MagicMock()
        session.get.return_value = response
        return session

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(PrintifyRetryableError):
            _fetch_page_unwrapped(session, "/shops.json", None, None, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/shops.json", None, None, MagicMock())

    def test_client_error_scrubs_query_string_and_keeps_non_retryable_prefix(self) -> None:
        # Printify authenticates via header today, but a redirect or future query-param auth must
        # never land in the rebuilt HTTPError (surfaced as the schema's latest_error). The status
        # and host prefix stays stable so get_non_retryable_errors() still matches.
        session = self._session_returning(
            401, url="https://api.printify.com/v1/shops.json?token=SECRET&page=1", reason="Unauthorized"
        )
        with pytest.raises(requests.HTTPError) as exc:
            _fetch_page_unwrapped(session, "/shops.json", 1, None, MagicMock())
        assert str(exc.value) == "401 Client Error: Unauthorized for url: https://api.printify.com/v1/shops.json"

    @parameterized.expand(
        [
            ("mid_pagination", {"current_page": 1, "last_page": 3, "data": [{"id": "a"}]}, True),
            ("last_page", {"current_page": 3, "last_page": 3, "data": [{"id": "a"}]}, False),
            ("empty_page", {"current_page": 1, "last_page": 3, "data": []}, False),
            ("next_url_fallback", {"data": [{"id": "a"}], "next_page_url": "https://api.printify.com/?page=2"}, True),
            ("null_next_url_fallback", {"data": [{"id": "a"}], "next_page_url": None}, False),
        ]
    )
    def test_paginator_termination(self, _name: str, body: dict, expected_has_more: bool) -> None:
        session = self._session_returning(200, body)
        items, has_more = _fetch_page_unwrapped(session, "/shops/1/products.json", 1, 100, MagicMock())
        assert items == body["data"]
        assert has_more is expected_has_more

    @parameterized.expand(
        [
            ("string_body", "nope"),
            ("dict_without_data", {"error": "oops"}),
            ("data_not_a_list", {"data": {"id": 1}}),
        ]
    )
    def test_malformed_payload_is_retryable(self, _name: str, body: Any) -> None:
        session = self._session_returning(200, body)
        with pytest.raises(PrintifyRetryableError):
            _fetch_page_unwrapped(session, "/shops/1/products.json", 1, 100, MagicMock())

    @parameterized.expand(
        [
            ("page_and_limit", 2, 100, {"page": 2, "limit": 100}),
            ("page_without_limit", 2, None, {"page": 2}),
            ("no_pagination_params", None, None, None),
        ]
    )
    def test_request_params(self, _name: str, page: int | None, limit: int | None, expected: dict | None) -> None:
        session = self._session_returning(200, [])
        _fetch_page_unwrapped(session, "/shops/1/orders.json", page, limit, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == expected


class TestGetRows:
    @staticmethod
    def _run(pages: _Pages, endpoint: str, resume_state: PrintifyResumeConfig | None = None) -> DriveResult:
        result = _driver().run(endpoint, _script(pages), resume_state=resume_state)
        assert result.raised is None
        return result

    def test_shop_fanout_injects_shop_id_into_rows(self) -> None:
        pages: _Pages = {
            ("/shops.json", None): ([{"id": 111}, {"id": 222}], False),
            ("/shops/111/products.json", 1): ([{"id": "p1"}], False),
            ("/shops/222/products.json", 1): ([{"id": "p2"}], False),
        }
        result = self._run(pages, "products")
        assert result.rows == [{"id": "p1", "shop_id": 111}, {"id": "p2", "shop_id": 222}]

    def test_webhook_rows_keep_api_shop_id_and_drop_signing_secret(self) -> None:
        pages: _Pages = {
            ("/shops.json", None): ([{"id": 111}], False),
            ("/shops/111/webhooks.json", None): ([{"id": "w1", "shop_id": "111", "secret": "whsec_123"}], False),
        }
        result = self._run(pages, "webhooks")
        # The signing secret must never reach the warehouse — a reader could forge webhook requests.
        assert result.rows == [{"id": "w1", "shop_id": "111"}]

    def test_paginated_fanout_saves_state_after_each_page(self) -> None:
        pages: _Pages = {
            ("/shops.json", None): ([{"id": 111}], False),
            ("/shops/111/products.json", 1): ([{"id": "p1"}], True),
            ("/shops/111/products.json", 2): ([{"id": "p2"}], False),
        }
        result = self._run(pages, "products")
        assert [r["id"] for r in result.rows] == ["p1", "p2"]
        assert [(s.shop_id, s.page) for s in result.saved_states] == [(111, 2)]

    def test_resume_skips_earlier_shops_and_starts_at_saved_page(self) -> None:
        # Pages for shop 111 (and pages 1-2 of shop 222) are deliberately absent — fetching them
        # would fail the run, proving the resume path never re-fetches them.
        pages: _Pages = {
            ("/shops.json", None): ([{"id": 111}, {"id": 222}, {"id": 333}], False),
            ("/shops/222/products.json", 3): ([{"id": "p3"}], False),
            ("/shops/333/products.json", 1): ([{"id": "p4"}], False),
        }
        result = self._run(pages, "products", PrintifyResumeConfig(shop_id=222, page=3))
        assert [r["id"] for r in result.rows] == ["p3", "p4"]
        assert result.paths == ["/v1/shops.json", "/v1/shops/222/products.json", "/v1/shops/333/products.json"]

    def test_resume_with_vanished_shop_restarts_from_first_shop(self) -> None:
        pages: _Pages = {
            ("/shops.json", None): ([{"id": 111}], False),
            ("/shops/111/products.json", 1): ([{"id": "p1"}], False),
        }
        result = self._run(pages, "products", PrintifyResumeConfig(shop_id=999, page=5))
        assert [r["id"] for r in result.rows] == ["p1"]

    def test_account_level_paginated_endpoint_resumes_from_saved_page(self) -> None:
        pages: _Pages = {
            ("/uploads.json", 2): ([{"id": "u2"}], False),
        }
        result = self._run(pages, "uploads", PrintifyResumeConfig(shop_id=None, page=2))
        assert [r["id"] for r in result.rows] == ["u2"]

    def test_account_level_paginated_endpoint_starts_from_the_first_page(self) -> None:
        pages: _Pages = {
            ("/uploads.json", 1): ([{"id": "u1"}], False),
        }
        result = self._run(pages, "uploads")
        assert [r["id"] for r in result.rows] == ["u1"]

    def test_non_paginated_account_endpoint_yields_once_without_state(self) -> None:
        pages: _Pages = {
            ("/catalog/blueprints.json", None): ([{"id": 5}, {"id": 6}], False),
        }
        result = self._run(pages, "blueprints")
        assert [r["id"] for r in result.rows] == [5, 6]
        assert result.saved_states == []

    def test_non_paginated_fanout_saves_state_per_shop(self) -> None:
        pages: _Pages = {
            ("/shops.json", None): ([{"id": 111}, {"id": 222}], False),
            ("/shops/111/webhooks.json", None): ([{"id": "w1"}], False),
            ("/shops/222/webhooks.json", None): ([], False),
        }
        result = self._run(pages, "webhooks")
        assert [(s.shop_id, s.page) for s in result.saved_states] == [(111, 1), (222, 1)]


class TestPrintifySourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _driver().run(endpoint, always(ScriptedResponse(json=[]))).response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == PRINTIFY_ENDPOINTS[endpoint].primary_keys

    def test_shop_scoped_endpoints_use_composite_primary_key(self) -> None:
        for config in PRINTIFY_ENDPOINTS.values():
            expected = ["shop_id", "id"] if config.shop_scoped else ["id"]
            assert config.primary_keys == expected, config.name
