from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.printify import printify
from products.warehouse_sources.backend.temporal.data_imports.sources.printify.printify import (
    PrintifyResumeConfig,
    PrintifyRetryableError,
    check_access,
    get_rows,
    printify_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.printify.settings import (
    ENDPOINTS,
    PRINTIFY_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = printify._fetch_page.__wrapped__  # type: ignore[attr-defined]

# (path, page) -> (items, has_more), the shape _fetch_page returns per request.
_Pages = dict[tuple[str, int | None], tuple[list[dict], bool]]


class _FakeResumableManager:
    def __init__(self, state: PrintifyResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[PrintifyResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> PrintifyResumeConfig | None:
        return self._state

    def save_state(self, data: PrintifyResumeConfig) -> None:
        self.saved.append(data)


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

    def test_bare_array_response_has_no_more_pages(self) -> None:
        session = self._session_returning(200, [{"id": 1}, {"id": 2}])
        items, has_more = _fetch_page_unwrapped(session, "/shops.json", None, None, MagicMock())
        assert items == [{"id": 1}, {"id": 2}]
        assert has_more is False

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
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: _Pages,
        endpoint: str,
    ) -> list[dict]:
        def fake_fetch(
            session: Any, path: str, page: int | None, limit: int | None, logger: Any
        ) -> tuple[list[dict], bool]:
            return pages[(path, page)]

        monkeypatch.setattr(printify, "_fetch_page", fake_fetch)
        monkeypatch.setattr(printify, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_key="printify-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_shop_fanout_injects_shop_id_into_rows(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: _Pages = {
            ("/shops.json", None): ([{"id": 111}, {"id": 222}], False),
            ("/shops/111/products.json", 1): ([{"id": "p1"}], False),
            ("/shops/222/products.json", 1): ([{"id": "p2"}], False),
        }
        rows = self._collect(manager, monkeypatch, pages, "products")
        assert rows == [{"id": "p1", "shop_id": 111}, {"id": "p2", "shop_id": 222}]

    def test_webhook_rows_keep_api_shop_id_and_drop_signing_secret(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: _Pages = {
            ("/shops.json", None): ([{"id": 111}], False),
            ("/shops/111/webhooks.json", None): ([{"id": "w1", "shop_id": "111", "secret": "whsec_123"}], False),
        }
        rows = self._collect(manager, monkeypatch, pages, "webhooks")
        # The signing secret must never reach the warehouse — a reader could forge webhook requests.
        assert rows == [{"id": "w1", "shop_id": "111"}]

    def test_paginated_fanout_saves_state_after_each_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: _Pages = {
            ("/shops.json", None): ([{"id": 111}], False),
            ("/shops/111/products.json", 1): ([{"id": "p1"}], True),
            ("/shops/111/products.json", 2): ([{"id": "p2"}], False),
        }
        rows = self._collect(manager, monkeypatch, pages, "products")
        assert [r["id"] for r in rows] == ["p1", "p2"]
        assert [(s.shop_id, s.page) for s in manager.saved] == [(111, 2)]

    def test_resume_skips_earlier_shops_and_starts_at_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(PrintifyResumeConfig(shop_id=222, page=3))
        # Pages for shop 111 (and pages 1-2 of shop 222) are deliberately absent — fetching them
        # would KeyError, proving the resume path never re-fetches them.
        pages: _Pages = {
            ("/shops.json", None): ([{"id": 111}, {"id": 222}, {"id": 333}], False),
            ("/shops/222/products.json", 3): ([{"id": "p3"}], False),
            ("/shops/333/products.json", 1): ([{"id": "p4"}], False),
        }
        rows = self._collect(manager, monkeypatch, pages, "products")
        assert [r["id"] for r in rows] == ["p3", "p4"]

    def test_resume_with_vanished_shop_restarts_from_first_shop(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(PrintifyResumeConfig(shop_id=999, page=5))
        pages: _Pages = {
            ("/shops.json", None): ([{"id": 111}], False),
            ("/shops/111/products.json", 1): ([{"id": "p1"}], False),
        }
        rows = self._collect(manager, monkeypatch, pages, "products")
        assert [r["id"] for r in rows] == ["p1"]

    def test_account_level_paginated_endpoint_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(PrintifyResumeConfig(shop_id=None, page=2))
        pages: _Pages = {
            ("/uploads.json", 2): ([{"id": "u2"}], False),
        }
        rows = self._collect(manager, monkeypatch, pages, "uploads")
        assert [r["id"] for r in rows] == ["u2"]

    def test_non_paginated_account_endpoint_yields_once_without_state(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: _Pages = {
            ("/catalog/blueprints.json", None): ([{"id": 5}, {"id": 6}], False),
        }
        rows = self._collect(manager, monkeypatch, pages, "blueprints")
        assert [r["id"] for r in rows] == [5, 6]
        assert manager.saved == []

    def test_non_paginated_fanout_saves_state_per_shop(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages: _Pages = {
            ("/shops.json", None): ([{"id": 111}, {"id": 222}], False),
            ("/shops/111/webhooks.json", None): ([{"id": "w1"}], False),
            ("/shops/222/webhooks.json", None): ([], False),
        }
        self._collect(manager, monkeypatch, pages, "webhooks")
        assert [(s.shop_id, s.page) for s in manager.saved] == [(111, 1), (222, 1)]


class TestPrintifySourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = printify_source(
            api_key="printify-key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == PRINTIFY_ENDPOINTS[endpoint].primary_keys

    def test_shop_scoped_endpoints_use_composite_primary_key(self) -> None:
        for config in PRINTIFY_ENDPOINTS.values():
            expected = ["shop_id", "id"] if config.shop_scoped else ["id"]
            assert config.primary_keys == expected, config.name


class TestCheckAccess:
    @staticmethod
    def _session(response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @parameterized.expand(
        [
            ("ok", 200, True, 200, None),
            ("unauthorized", 401, False, 401, None),
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "Printify returned HTTP 500"),
        ]
    )
    @patch(f"{printify.__name__}.make_tracked_session")
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        ok: bool,
        expected_status: int,
        expected_message: str | None,
        mock_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        mock_session.return_value = self._session(response)
        assert check_access("printify-key") == (expected_status, expected_message)

    @patch(f"{printify.__name__}.make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_session: MagicMock) -> None:
        mock_session.return_value = self._session(requests.ConnectionError("boom"))
        status, message = check_access("printify-key")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Printify API token"),
            ("forbidden", 403, False, "Invalid Printify API token"),
            ("server_error", 500, False, "Printify returned HTTP 500"),
        ]
    )
    @patch(f"{printify.__name__}.make_tracked_session")
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        mock_session.return_value = self._session(response)
        assert validate_credentials("printify-key") == (expected_valid, expected_message)
