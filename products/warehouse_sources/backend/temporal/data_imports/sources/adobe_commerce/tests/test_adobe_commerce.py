import json
import threading
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime
from typing import Any, cast
from urllib.parse import parse_qsl, urlparse
from zoneinfo import ZoneInfo

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_commerce import adobe_commerce
from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_commerce.adobe_commerce import (
    HOST_NOT_ALLOWED_ERROR,
    MAX_RESPONSE_BYTES,
    AdobeCommerceConfigurationError,
    AdobeCommerceCredentials,
    AdobeCommerceHostNotAllowedError,
    AdobeCommercePaginationLimitError,
    AdobeCommerceResponseTooLargeError,
    AdobeCommerceResponseTooSlowError,
    AdobeCommerceResumeConfig,
    AdobeCommerceRetryableError,
    AdobeCommerceTokenManager,
    _base_url,
    _format_magento_datetime,
    _read_capped_json,
    _request_page,
    adobe_commerce_source,
    build_search_criteria,
    get_rows,
    normalize_store_code,
    normalize_store_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_commerce.settings import (
    ADOBE_COMMERCE_ENDPOINTS,
    ENDPOINTS,
    VALIDATION_PROBE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

TOKEN_CREDENTIALS = AdobeCommerceCredentials(method="access_token", access_token="tok-123")
ADMIN_CREDENTIALS = AdobeCommerceCredentials(method="admin", username="admin", password="hunter2")


class _FakeResumableManager(ResumableSourceManager[AdobeCommerceResumeConfig]):
    def __init__(self, state: AdobeCommerceResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[AdobeCommerceResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> AdobeCommerceResumeConfig | None:
        return self._state

    def save_state(self, data: AdobeCommerceResumeConfig) -> None:
        self.saved.append(data)


def _make_response(status: int, body: Any = None, *, redirect: bool = False, raw: bytes | None = None) -> MagicMock:
    payload = raw if raw is not None else (b"" if body is None else json.dumps(body).encode())
    response = MagicMock()
    response.status_code = status
    response.ok = status < 400
    response.is_redirect = redirect
    response.is_permanent_redirect = False
    # A fresh iterator per call so the body can be read more than once (error preview, then parse).
    response.iter_content.side_effect = lambda chunk_size=None: iter([payload] if payload else [])
    response.raise_for_status.side_effect = (
        requests.HTTPError(f"{status} Client Error", response=response) if status >= 400 else None
    )
    return response


def _request_key(url: str) -> str:
    """`path?sorted-query` — a stable routing key for the fake session."""
    parsed = urlparse(url)
    query = "&".join(f"{k}={v}" for k, v in sorted(parse_qsl(parsed.query)))
    return f"{parsed.path}?{query}" if query else parsed.path


class _FakeSession:
    def __init__(self, route: Callable[[str], Any] | dict[str, Any]) -> None:
        self._route = route
        self.gets: list[str] = []
        self.posts: list[tuple[str, Any]] = []
        self.post_timeouts: list[Any] = []

    def _resolve(self, url: str) -> Any:
        key = _request_key(url)
        resolved = self._route(key) if callable(self._route) else self._route[key]
        if isinstance(resolved, Exception):
            raise resolved
        return resolved

    def get(self, url: str, **kwargs: Any) -> Any:
        self.gets.append(_request_key(url))
        return self._resolve(url)

    def post(self, url: str, **kwargs: Any) -> Any:
        self.posts.append((_request_key(url), kwargs.get("json")))
        self.post_timeouts.append(kwargs.get("timeout"))
        return self._resolve(url)


def _install_session(monkeypatch: pytest.MonkeyPatch, session: _FakeSession) -> None:
    monkeypatch.setattr(adobe_commerce, "_make_session", lambda credentials, capture=True, retry=None: session)
    monkeypatch.setattr(adobe_commerce, "_is_host_safe", lambda host, team_id: (True, None))


class TestNormalizeStoreUrl:
    @parameterized.expand(
        [
            ("bare_host", "store.example.com", "https://store.example.com"),
            ("https", "https://store.example.com", "https://store.example.com"),
            ("trailing_slash", "https://store.example.com/", "https://store.example.com"),
            ("subdirectory_install", "https://example.com/shop", "https://example.com/shop"),
            ("pasted_rest_base", "https://example.com/shop/rest/default/V1", "https://example.com/shop"),
            ("pasted_rest_root", "https://store.example.com/rest", "https://store.example.com"),
            ("explicit_port", "https://store.example.com:8443", "https://store.example.com:8443"),
            ("whitespace", "  https://store.example.com  ", "https://store.example.com"),
        ]
    )
    def test_accepts_and_cleans_valid_input(self, _name: str, raw: str, expected: str) -> None:
        assert normalize_store_url(raw) == expected

    @parameterized.expand(
        [
            ("http_scheme", "http://store.example.com"),
            ("http_uppercase", "HTTP://store.example.com"),
        ]
    )
    def test_rejects_plaintext_http(self, _name: str, raw: str) -> None:
        # Credentials ride every request, so plaintext transport must be refused with a message
        # that tells the merchant to switch to HTTPS rather than a generic "invalid URL".
        with pytest.raises(ValueError, match="must use HTTPS"):
            normalize_store_url(raw)

    @parameterized.expand(
        [
            ("empty", ""),
            ("whitespace_only", "   "),
            ("credentials_in_url", "https://user:pass@store.example.com"),
            ("query_string", "https://store.example.com/?redirect=http://169.254.169.254"),
            ("fragment", "https://store.example.com/#@evil.com"),
            ("traversal", "https://store.example.com/shop/../../etc"),
            ("non_http_scheme", "file:///etc/passwd"),
        ]
    )
    def test_rejects_unsafe_input(self, _name: str, raw: str) -> None:
        # The store URL is where the stored token is sent, so anything that could retarget or
        # smuggle must be rejected before a URL is built.
        with pytest.raises(ValueError):
            normalize_store_url(raw)


class TestStoreCodeAndBaseUrl:
    @parameterized.expand(
        [
            ("blank", None, ""),
            ("empty_string", "", ""),
            ("default", "default", "default"),
            ("underscored", "us_store_view", "us_store_view"),
            ("slashes_stripped", "/default/", "default"),
        ]
    )
    def test_normalize_store_code(self, _name: str, raw: str | None, expected: str) -> None:
        assert normalize_store_code(raw) == expected

    @parameterized.expand([("path_segment", "de/../all"), ("leading_digit", "1store"), ("dotted", "de.store")])
    def test_normalize_store_code_rejects_path_injection(self, _name: str, raw: str) -> None:
        with pytest.raises(ValueError):
            normalize_store_code(raw)

    @parameterized.expand(
        [
            ("no_code", "https://store.example.com", None, "https://store.example.com/rest/V1"),
            ("with_code", "https://store.example.com", "default", "https://store.example.com/rest/default/V1"),
            ("subdirectory", "https://example.com/shop", "all", "https://example.com/shop/rest/all/V1"),
        ]
    )
    def test_base_url(self, _name: str, store_url: str, store_code: str | None, expected: str) -> None:
        assert _base_url(store_url, store_code) == expected


class TestSearchCriteria:
    def test_full_refresh_sorts_by_primary_key_without_filter(self) -> None:
        params = build_search_criteria(ADOBE_COMMERCE_ENDPOINTS["orders"], page=3)
        assert params["searchCriteria[currentPage]"] == 3
        assert params["searchCriteria[pageSize]"] == ADOBE_COMMERCE_ENDPOINTS["orders"].page_size
        assert params["searchCriteria[sortOrders][0][field]"] == "entity_id"
        assert params["searchCriteria[sortOrders][0][direction]"] == "ASC"
        assert not any("filter_groups" in key for key in params)

    @parameterized.expand(
        [
            ("products", "products", "entity_id"),
            ("categories", "categories", "entity_id"),
            ("customers", "customers", "entity_id"),
            ("carts", "carts", "entity_id"),
            ("orders", "orders", "entity_id"),
            ("transactions", "transactions", "transaction_id"),
        ]
    )
    def test_full_refresh_sorts_on_the_table_column_not_the_response_field(
        self, _name: str, endpoint: str, expected_field: str
    ) -> None:
        # searchCriteria addresses the underlying table column: `/V1/products` returns `id` but
        # rejects a sort on it, so the catalog must carry the column name separately.
        params = build_search_criteria(ADOBE_COMMERCE_ENDPOINTS[endpoint], page=1)
        assert params["searchCriteria[sortOrders][0][field]"] == expected_field

    def test_incremental_sorts_by_cursor_and_filters_gteq(self) -> None:
        params = build_search_criteria(
            ADOBE_COMMERCE_ENDPOINTS["orders"],
            page=1,
            cursor_field="updated_at",
            cursor_value=datetime(2024, 5, 4, 3, 2, 1, tzinfo=UTC),
        )
        assert params["searchCriteria[sortOrders][0][field]"] == "updated_at"
        assert params["searchCriteria[sortOrders][0][direction]"] == "ASC"
        assert params["searchCriteria[filter_groups][0][filters][0][field]"] == "updated_at"
        assert params["searchCriteria[filter_groups][0][filters][0][value]"] == "2024-05-04 03:02:01"
        # `gteq` re-reads the boundary row instead of risking a skip within the same second.
        assert params["searchCriteria[filter_groups][0][filters][0][condition_type]"] == "gteq"

    def test_first_incremental_sync_sorts_by_cursor_without_a_filter(self) -> None:
        params = build_search_criteria(ADOBE_COMMERCE_ENDPOINTS["orders"], page=1, cursor_field="updated_at")
        assert params["searchCriteria[sortOrders][0][field]"] == "updated_at"
        assert not any("filter_groups" in key for key in params)

    @parameterized.expand(
        [
            ("aware_datetime", datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02 03:04:05"),
            ("naive_datetime_is_utc", datetime(2024, 1, 2, 3, 4, 5), "2024-01-02 03:04:05"),
            ("date", date(2024, 1, 2), "2024-01-02 00:00:00"),
            ("passthrough_string", "2024-01-02 03:04:05", "2024-01-02 03:04:05"),
        ]
    )
    def test_format_magento_datetime(self, _name: str, value: Any, expected: str) -> None:
        assert _format_magento_datetime(value) == expected

    def test_non_utc_datetime_is_converted(self) -> None:
        value = datetime(2024, 1, 2, 3, 4, 5, tzinfo=ZoneInfo("Europe/Berlin"))
        assert _format_magento_datetime(value) == "2024-01-02 02:04:05"


class TestTokenManager:
    def test_access_token_is_used_verbatim_without_a_request(self) -> None:
        session = _FakeSession({})
        manager = AdobeCommerceTokenManager(cast(Any, session), "https://s.example.com/rest/V1", TOKEN_CREDENTIALS)
        assert manager.get_token() == "tok-123"
        assert session.posts == []

    def test_missing_access_token_is_a_configuration_error(self) -> None:
        manager = AdobeCommerceTokenManager(
            cast(Any, _FakeSession({})),
            "https://s.example.com/rest/V1",
            AdobeCommerceCredentials(method="access_token", access_token=""),
        )
        with pytest.raises(AdobeCommerceConfigurationError):
            manager.get_token()

    def test_admin_token_is_minted_once_and_cached(self) -> None:
        session = _FakeSession({"/rest/V1/integration/admin/token": _make_response(200, "minted-token")})
        manager = AdobeCommerceTokenManager(cast(Any, session), "https://s.example.com/rest/V1", ADMIN_CREDENTIALS)
        assert manager.get_token() == "minted-token"
        assert manager.get_token() == "minted-token"
        assert len(session.posts) == 1
        assert session.posts[0][1] == {"username": "admin", "password": "hunter2"}

    def test_admin_token_is_reminted_before_it_expires(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = {"now": 0.0}
        monkeypatch.setattr(adobe_commerce.time, "monotonic", lambda: clock["now"])
        session = _FakeSession({"/rest/V1/integration/admin/token": _make_response(200, "minted-token")})
        manager = AdobeCommerceTokenManager(cast(Any, session), "https://s.example.com/rest/V1", ADMIN_CREDENTIALS)

        manager.get_token()
        # Still inside the lifetime minus the refresh margin — no re-mint.
        clock["now"] = adobe_commerce.ADMIN_TOKEN_LIFETIME_SECONDS - adobe_commerce.TOKEN_REFRESH_MARGIN_SECONDS - 1
        manager.get_token()
        assert len(session.posts) == 1

        # Inside the margin — the token would expire mid-flight, so it is re-minted first.
        clock["now"] = adobe_commerce.ADMIN_TOKEN_LIFETIME_SECONDS - adobe_commerce.TOKEN_REFRESH_MARGIN_SECONDS + 1
        manager.get_token()
        assert len(session.posts) == 2

    @parameterized.expand([("no_username", None, "pw"), ("no_password", "admin", None)])
    def test_incomplete_admin_credentials_raise_before_any_request(
        self, _name: str, username: str | None, password: str | None
    ) -> None:
        session = _FakeSession({})
        manager = AdobeCommerceTokenManager(
            cast(Any, session),
            "https://s.example.com/rest/V1",
            AdobeCommerceCredentials(method="admin", username=username, password=password),
        )
        with pytest.raises(AdobeCommerceConfigurationError):
            manager.get_token()
        assert session.posts == []

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_transient_token_failures_are_retryable(self, _name: str, status: int) -> None:
        session = _FakeSession({"/rest/V1/integration/admin/token": _make_response(status)})
        manager = AdobeCommerceTokenManager(cast(Any, session), "https://s.example.com/rest/V1", ADMIN_CREDENTIALS)
        with pytest.raises(AdobeCommerceRetryableError):
            manager.get_token()

    def test_token_redirect_is_refused(self) -> None:
        session = _FakeSession({"/rest/V1/integration/admin/token": _make_response(302, redirect=True)})
        manager = AdobeCommerceTokenManager(cast(Any, session), "https://s.example.com/rest/V1", ADMIN_CREDENTIALS)
        with pytest.raises(AdobeCommerceHostNotAllowedError):
            manager.get_token()

    @parameterized.expand([("html_login_page", {"message": "nope"}), ("empty_string", "")])
    def test_non_token_body_is_a_configuration_error(self, _name: str, body: Any) -> None:
        session = _FakeSession({"/rest/V1/integration/admin/token": _make_response(200, body)})
        manager = AdobeCommerceTokenManager(cast(Any, session), "https://s.example.com/rest/V1", ADMIN_CREDENTIALS)
        with pytest.raises(AdobeCommerceConfigurationError):
            manager.get_token()

    def test_oversized_token_body_is_a_configuration_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A real token is a short string, so validation caps the token exchange far below a data
        # page. An oversized body must fail permanently rather than buffer on the API worker.
        monkeypatch.setattr(adobe_commerce, "TOKEN_RESPONSE_MAX_BYTES", 8)
        session = _FakeSession({"/rest/V1/integration/admin/token": _make_response(200, raw=b'"' + b"x" * 64 + b'"')})
        manager = AdobeCommerceTokenManager(cast(Any, session), "https://s.example.com/rest/V1", ADMIN_CREDENTIALS)
        with pytest.raises(AdobeCommerceConfigurationError):
            manager.get_token()

    def test_token_request_timeout_is_bounded_for_inline_validation(self) -> None:
        # The exchange runs inline during validation, so its request timeout must bound the
        # connect/header wait too — not inherit the 120s data timeout a hostile store could stall on.
        session = _FakeSession({"/rest/V1/integration/admin/token": _make_response(200, "minted-token")})
        manager = AdobeCommerceTokenManager(cast(Any, session), "https://s.example.com/rest/V1", ADMIN_CREDENTIALS)
        manager.get_token()
        assert session.post_timeouts[0] == adobe_commerce.TOKEN_DOWNLOAD_SECONDS

    def test_bad_admin_password_surfaces_as_http_error(self) -> None:
        session = _FakeSession({"/rest/V1/integration/admin/token": _make_response(401, {"message": "bad"})})
        manager = AdobeCommerceTokenManager(cast(Any, session), "https://s.example.com/rest/V1", ADMIN_CREDENTIALS)
        with pytest.raises(requests.HTTPError):
            manager.get_token()


class TestRequestPage:
    def _manager(self) -> AdobeCommerceTokenManager:
        return AdobeCommerceTokenManager(
            cast(Any, _FakeSession({})), "https://s.example.com/rest/V1", TOKEN_CREDENTIALS
        )

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404), ("server_error", 500)])
    def test_error_statuses_raise_for_status(self, _name: str, status: int) -> None:
        # The tracked session already retried 429/5xx, so anything non-ok reaching here is terminal
        # for this attempt and must surface rather than be swallowed.
        session = _FakeSession({"/rest/V1/orders": _make_response(status, {"message": "no"})})
        with pytest.raises(requests.HTTPError):
            _request_page(cast(Any, session), self._manager(), "https://s.example.com/rest/V1/orders", MagicMock())

    def test_redirect_is_refused(self) -> None:
        session = _FakeSession({"/rest/V1/orders": _make_response(301, redirect=True)})
        with pytest.raises(AdobeCommerceHostNotAllowedError):
            _request_page(cast(Any, session), self._manager(), "https://s.example.com/rest/V1/orders", MagicMock())

    def test_bearer_token_is_sent(self) -> None:
        session = MagicMock()
        session.get.return_value = _make_response(200, {"items": []})
        _request_page(session, self._manager(), "https://s.example.com/rest/V1/orders", MagicMock())
        assert session.get.call_args.kwargs["headers"]["Authorization"] == "Bearer tok-123"


class TestReadCappedJson:
    def test_oversized_body_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(adobe_commerce, "MAX_RESPONSE_BYTES", 16)
        response = _make_response(200, raw=b"x" * 64)
        with pytest.raises(AdobeCommerceResponseTooLargeError):
            _read_capped_json(response)
        # The connection is released even when the read is aborted.
        response.close.assert_called()

    def test_body_within_the_cap_parses(self) -> None:
        assert _read_capped_json(_make_response(200, {"items": [{"id": 1}]})) == {"items": [{"id": 1}]}
        assert MAX_RESPONSE_BYTES > 0

    def test_slow_body_is_abandoned_at_the_deadline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A host that never completes a chunk (dripping bytes under the socket read timeout) must not
        # hold the worker: the read runs on a thread we stop waiting on once the budget expires.
        release = threading.Event()

        def blocking_iter(chunk_size: Any = None) -> Iterator[bytes]:
            release.wait(5)  # the deadline fires first; released in the finally below
            yield b'"tok"'

        monkeypatch.setattr(adobe_commerce, "MAX_DOWNLOAD_SECONDS", 0.05)
        response = MagicMock()
        response.iter_content.side_effect = blocking_iter
        try:
            with pytest.raises(AdobeCommerceResponseTooSlowError):
                _read_capped_json(response)
        finally:
            release.set()
        response.close.assert_called()


def _collect(
    manager: _FakeResumableManager,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    _install_session(monkeypatch, session)
    rows: list[dict[str, Any]] = []
    for batch in get_rows(
        store_url="https://store.example.com",
        store_code=None,
        credentials=TOKEN_CREDENTIALS,
        endpoint=endpoint,
        team_id=1,
        logger=MagicMock(),
        resumable_source_manager=manager,
        **kwargs,
    ):
        rows.extend(batch)
    return rows


def _page_key(path: str, page: int, size: int, sort_field: str, cursor: str | None = None) -> str:
    params = {
        "searchCriteria[pageSize]": str(size),
        "searchCriteria[currentPage]": str(page),
        "searchCriteria[sortOrders][0][field]": sort_field,
        "searchCriteria[sortOrders][0][direction]": "ASC",
    }
    if cursor is not None:
        params["searchCriteria[filter_groups][0][filters][0][field]"] = sort_field
        params["searchCriteria[filter_groups][0][filters][0][value]"] = cursor
        params["searchCriteria[filter_groups][0][filters][0][condition_type]"] = "gteq"
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return f"/rest/V1{path}?{query}"


class TestGetRows:
    def test_paginates_until_total_count_is_reached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ADOBE_COMMERCE_ENDPOINTS["orders"], "page_size", 2)
        routes = {
            _page_key("/orders", 1, 2, "entity_id"): _make_response(
                200, {"items": [{"entity_id": 1}, {"entity_id": 2}], "total_count": 4}
            ),
            _page_key("/orders", 2, 2, "entity_id"): _make_response(
                200, {"items": [{"entity_id": 3}, {"entity_id": 4}], "total_count": 4}
            ),
        }
        session = _FakeSession(routes)
        manager = _FakeResumableManager()
        rows = _collect(manager, session, monkeypatch, "orders")

        assert [r["entity_id"] for r in rows] == [1, 2, 3, 4]
        # Page 3 is never requested: total_count says the collection is exhausted.
        assert len(session.gets) == 2
        assert [s.current_page for s in manager.saved] == [2]

    def test_short_page_terminates_when_total_count_is_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ADOBE_COMMERCE_ENDPOINTS["orders"], "page_size", 2)
        routes = {
            _page_key("/orders", 1, 2, "entity_id"): _make_response(200, {"items": [{"entity_id": 1}]}),
        }
        rows = _collect(_FakeResumableManager(), _FakeSession(routes), monkeypatch, "orders")
        assert [r["entity_id"] for r in rows] == [1]

    def test_empty_first_page_yields_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ADOBE_COMMERCE_ENDPOINTS["orders"], "page_size", 2)
        routes = {_page_key("/orders", 1, 2, "entity_id"): _make_response(200, {"items": [], "total_count": 0})}
        manager = _FakeResumableManager()
        assert _collect(manager, _FakeSession(routes), monkeypatch, "orders") == []
        assert manager.saved == []

    def test_state_is_saved_after_each_yielded_page_and_resume_skips_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ADOBE_COMMERCE_ENDPOINTS["orders"], "page_size", 1)
        routes = {
            _page_key("/orders", 2, 1, "entity_id"): _make_response(
                200, {"items": [{"entity_id": 2}], "total_count": 3}
            ),
            _page_key("/orders", 3, 1, "entity_id"): _make_response(
                200, {"items": [{"entity_id": 3}], "total_count": 3}
            ),
        }
        session = _FakeSession(routes)
        manager = _FakeResumableManager(AdobeCommerceResumeConfig(current_page=2))
        rows = _collect(manager, session, monkeypatch, "orders")

        # Page 1 is never re-fetched; the run picks up exactly where the saved state points.
        assert [r["entity_id"] for r in rows] == [2, 3]
        assert [s.current_page for s in manager.saved] == [3]

    def test_incremental_run_sends_the_server_side_filter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ADOBE_COMMERCE_ENDPOINTS["orders"], "page_size", 2)
        key = _page_key("/orders", 1, 2, "updated_at", cursor="2024-05-04 03:02:01")
        session = _FakeSession({key: _make_response(200, {"items": [{"entity_id": 9}], "total_count": 1})})
        rows = _collect(
            _FakeResumableManager(),
            session,
            monkeypatch,
            "orders",
            should_use_incremental_field=True,
            incremental_field_name="updated_at",
            db_incremental_field_last_value=datetime(2024, 5, 4, 3, 2, 1, tzinfo=UTC),
        )
        assert [r["entity_id"] for r in rows] == [9]
        assert session.gets == [key]

    def test_incremental_falls_back_to_the_endpoint_cursor_when_none_is_chosen(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(ADOBE_COMMERCE_ENDPOINTS["transactions"], "page_size", 2)
        key = _page_key("/transactions", 1, 2, "created_at", cursor="2024-01-01 00:00:00")
        session = _FakeSession({key: _make_response(200, {"items": [{"transaction_id": 1}], "total_count": 1})})
        _collect(
            _FakeResumableManager(),
            session,
            monkeypatch,
            "transactions",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01 00:00:00",
        )
        assert session.gets == [key]

    def test_reference_endpoint_fetches_a_bare_array_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = _FakeSession({"/rest/V1/store/storeViews": _make_response(200, [{"id": 1}, {"id": 2}])})
        manager = _FakeResumableManager()
        rows = _collect(manager, session, monkeypatch, "store_views")
        assert rows == [{"id": 1}, {"id": 2}]
        # No searchCriteria, one request, nothing to resume from.
        assert session.gets == ["/rest/V1/store/storeViews"]
        assert manager.saved == []

    def test_unexpected_payload_is_retryable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = _FakeSession({"/rest/V1/store/storeViews": _make_response(200, "surprise")})
        with pytest.raises(AdobeCommerceRetryableError):
            _collect(_FakeResumableManager(), session, monkeypatch, "store_views")

    def test_pagination_is_bounded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A server that returns a full page forever with an inflated total_count would otherwise
        # loop until the activity times out.
        monkeypatch.setattr(adobe_commerce, "MAX_PAGES", 2)
        monkeypatch.setattr(ADOBE_COMMERCE_ENDPOINTS["orders"], "page_size", 1)
        session = _FakeSession(
            lambda key: _make_response(200, {"items": [{"entity_id": 1}], "total_count": 10_000_000})
        )
        with pytest.raises(AdobeCommercePaginationLimitError):
            _collect(_FakeResumableManager(), session, monkeypatch, "orders")

    def test_pagination_wall_clock_is_bounded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A store that dribbles full pages without `total_count` stays under MAX_PAGES but would run
        # to the activity timeout, so the loop's wall-clock budget must stop it independently.
        clock = {"now": 0.0}

        def fake_monotonic() -> float:
            clock["now"] += 1.0
            return clock["now"]

        monkeypatch.setattr(adobe_commerce.time, "monotonic", fake_monotonic)
        monkeypatch.setattr(adobe_commerce, "MAX_PAGINATION_SECONDS", 0)
        session = _FakeSession(lambda key: _make_response(200, {"items": [{"entity_id": 1}]}))
        with pytest.raises(AdobeCommercePaginationLimitError):
            _collect(_FakeResumableManager(), session, monkeypatch, "orders")

    def test_internal_host_is_refused_at_sync_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = _FakeSession({})
        monkeypatch.setattr(adobe_commerce, "_make_session", lambda credentials, capture=True, retry=None: session)
        monkeypatch.setattr(adobe_commerce, "_is_host_safe", lambda host, team_id: (False, "internal address"))
        with pytest.raises(AdobeCommerceHostNotAllowedError):
            list(
                get_rows(
                    store_url="https://store.example.com",
                    store_code=None,
                    credentials=TOKEN_CREDENTIALS,
                    endpoint="orders",
                    team_id=1,
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),
                )
            )
        assert session.gets == []


class TestValidateCredentials:
    def _routes_all(self, response_factory: Callable[[], Any]) -> Callable[[str], Any]:
        return lambda key: response_factory()

    def test_first_reachable_probe_endpoint_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Magento answers an unauthorized *resource* with a 401, so a narrowly-scoped integration
        # must still connect as long as one of the probe endpoints is readable.
        def route(key: str) -> Any:
            if key.startswith("/rest/V1/customers/search"):
                return _make_response(200, {"items": [], "total_count": 0})
            return _make_response(401, {"message": "denied"})

        session = _FakeSession(route)
        _install_session(monkeypatch, session)
        assert validate_credentials("https://store.example.com", None, TOKEN_CREDENTIALS, team_id=1) == (True, None)
        assert len(session.gets) == 3

    def test_all_probes_unauthorized_reports_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = _FakeSession(self._routes_all(lambda: _make_response(401, {"message": "denied"})))
        _install_session(monkeypatch, session)
        valid, message = validate_credentials("https://store.example.com", None, TOKEN_CREDENTIALS, team_id=1)
        assert valid is False
        assert message is not None and "standalone Bearer tokens" in message
        assert len(session.gets) == len(VALIDATION_PROBE_ENDPOINTS)

    def test_not_a_magento_rest_api_reports_the_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = _FakeSession(self._routes_all(lambda: _make_response(404)))
        _install_session(monkeypatch, session)
        valid, message = validate_credentials("https://store.example.com", None, TOKEN_CREDENTIALS, team_id=1)
        assert valid is False
        assert message == "No Adobe Commerce REST API found at that store URL. Check the URL and store code."

    def test_connection_failure_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = _FakeSession(self._routes_all(lambda: requests.ConnectionError("boom")))
        _install_session(monkeypatch, session)
        valid, message = validate_credentials("https://store.example.com", None, TOKEN_CREDENTIALS, team_id=1)
        assert valid is False
        assert message is not None and "boom" in message
        # A transport failure means the host is unreachable, so the probe loop must stop rather than
        # pay a full timeout on each remaining endpoint and tie up the worker for minutes.
        assert len(session.gets) == 1

    def test_scoped_probe_targets_only_that_schema(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = _FakeSession(self._routes_all(lambda: _make_response(200, {"items": [], "total_count": 0})))
        _install_session(monkeypatch, session)
        assert validate_credentials(
            "https://store.example.com", None, TOKEN_CREDENTIALS, schema_name="products", team_id=1
        ) == (True, None)
        assert len(session.gets) == 1
        assert session.gets[0].startswith("/rest/V1/products?")

    def test_probe_requests_a_single_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = _FakeSession(self._routes_all(lambda: _make_response(200, {"items": [], "total_count": 0})))
        _install_session(monkeypatch, session)
        validate_credentials("https://store.example.com", None, TOKEN_CREDENTIALS, schema_name="orders", team_id=1)
        assert "searchCriteria[pageSize]=1" in session.gets[0]

    def test_validation_disables_transport_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Validation runs inline on the API thread, so its session must opt out of the retrying
        # policy — otherwise a store answering 429/503 with a large Retry-After stalls the worker
        # across retry sleeps that the request timeout doesn't bound.
        captured: dict[str, Any] = {}
        session = _FakeSession(self._routes_all(lambda: _make_response(200, {"items": [], "total_count": 0})))

        def fake_make_session(credentials: Any, capture: bool = True, retry: Any = None) -> Any:
            captured["retry"] = retry
            return session

        monkeypatch.setattr(adobe_commerce, "_make_session", fake_make_session)
        monkeypatch.setattr(adobe_commerce, "_is_host_safe", lambda host, team_id: (True, None))
        validate_credentials("https://store.example.com", None, TOKEN_CREDENTIALS, team_id=1)
        assert captured["retry"] is not None and captured["retry"].total == 0

    def test_bad_admin_password_is_reported_before_any_probe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = _FakeSession(self._routes_all(lambda: _make_response(401, {"message": "bad"})))
        _install_session(monkeypatch, session)
        valid, message = validate_credentials("https://store.example.com", None, ADMIN_CREDENTIALS, team_id=1)
        assert valid is False
        assert message == "Adobe Commerce rejected the admin username and password."
        assert session.gets == []

    def test_invalid_store_url_fails_without_network(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = _FakeSession({})
        _install_session(monkeypatch, session)
        valid, message = validate_credentials("", None, TOKEN_CREDENTIALS, team_id=1)
        assert valid is False
        assert message is not None
        assert session.gets == [] and session.posts == []

    def test_internal_host_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = _FakeSession({})
        monkeypatch.setattr(adobe_commerce, "_make_session", lambda credentials, capture=True, retry=None: session)
        monkeypatch.setattr(adobe_commerce, "_is_host_safe", lambda host, team_id: (False, "internal address"))
        valid, message = validate_credentials("https://internal.local", None, TOKEN_CREDENTIALS, team_id=1)
        assert valid is False
        assert message == "internal address"
        assert session.gets == []

    def test_redirect_probe_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = _FakeSession(self._routes_all(lambda: _make_response(302, redirect=True)))
        _install_session(monkeypatch, session)
        valid, message = validate_credentials("https://store.example.com", None, TOKEN_CREDENTIALS, team_id=1)
        assert valid is False
        assert message == HOST_NOT_ALLOWED_ERROR


class TestSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = adobe_commerce_source(
            store_url="https://store.example.com",
            store_code=None,
            credentials=TOKEN_CREDENTIALS,
            endpoint=endpoint,
            team_id=1,
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ADOBE_COMMERCE_ENDPOINTS[endpoint].primary_keys
        # Every request asks Magento for an ascending sort, so the watermark can checkpoint per batch.
        assert response.sort_mode == "asc"

    def test_items_is_lazy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = _FakeSession({"/rest/V1/store/storeViews": _make_response(200, [{"id": 1}])})
        _install_session(monkeypatch, session)
        response = adobe_commerce_source(
            store_url="https://store.example.com",
            store_code=None,
            credentials=TOKEN_CREDENTIALS,
            endpoint="store_views",
            team_id=1,
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),
        )
        # Building the response must not touch the network — the pipeline decides when to iterate.
        assert session.gets == []
        batches = cast("Iterable[Any]", response.items())
        assert list(cast(Iterator[Any], iter(batches))) == [[{"id": 1}]]

    def test_primary_keys_are_unique_per_endpoint(self) -> None:
        for name, config in ADOBE_COMMERCE_ENDPOINTS.items():
            assert config.primary_keys, f"{name} has no primary key"
            assert len(set(config.primary_keys)) == len(config.primary_keys)
