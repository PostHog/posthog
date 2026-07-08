from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews import judgeme_reviews
from products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews.judgeme_reviews import (
    PAGE_SIZE,
    JudgeMeReviewsResumeConfig,
    JudgeMeReviewsRetryableError,
    _normalize_shop_domain,
    _parse_retry_after,
    check_access,
    get_rows,
    judgeme_reviews_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews.settings import (
    ENDPOINTS,
    JUDGEME_REVIEWS_ENDPOINTS,
)

# Call the undecorated function so the tenacity retry/backoff wrapper doesn't slow failure-path tests.
_fetch_page_unwrapped = judgeme_reviews._fetch_page.__wrapped__  # type: ignore[attr-defined]


class _FakeResumableManager:
    def __init__(self, state: JudgeMeReviewsResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[JudgeMeReviewsResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> JudgeMeReviewsResumeConfig | None:
        return self._state

    def save_state(self, data: JudgeMeReviewsResumeConfig) -> None:
        self.saved.append(data)


def _page(items: list[dict], page: int = 1, list_key: str = "reviews") -> dict[str, Any]:
    return {"current_page": page, "per_page": PAGE_SIZE, list_key: items}


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager, monkeypatch: Any, pages: dict[int, dict], endpoint: str = "reviews"
    ) -> list[dict]:
        def fake_fetch(session: Any, path: str, shop_domain: str, page: int, logger: Any) -> dict:
            return pages[page]

        monkeypatch.setattr(judgeme_reviews, "_fetch_page", fake_fetch)
        monkeypatch.setattr(judgeme_reviews, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for batch in get_rows(
            api_token="jm-token",
            shop_domain="example.myshopify.com",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_paginates_until_empty_page(self, monkeypatch: Any) -> None:
        # There is no has_more flag, so a full page must still be followed by another fetch.
        manager = _FakeResumableManager()
        pages = {
            1: _page([{"id": 1}], page=1),
            2: _page([{"id": 2}], page=2),
            3: _page([], page=3),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": 1}, {"id": 2}]

    def test_empty_first_page_yields_nothing_and_saves_no_state(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, {1: _page([])})
        assert rows == []
        assert manager.saved == []

    def test_saves_next_page_after_yielding_each_batch(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            1: _page([{"id": 1}], page=1),
            2: _page([], page=2),
        }
        self._collect(manager, monkeypatch, pages)
        # State is saved AFTER page 1 is yielded (pointing at page 2), never before.
        assert [s.next_page for s in manager.saved] == [2]

    def test_resumes_from_saved_page(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(JudgeMeReviewsResumeConfig(next_page=2))
        pages = {
            # Page 1 must never be fetched on resume.
            2: _page([{"id": 2}], page=2),
            3: _page([], page=3),
        }
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == [{"id": 2}]

    def test_uses_endpoint_specific_list_key(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            1: _page([{"id": 7}], page=1, list_key="products"),
            2: _page([], page=2, list_key="products"),
        }
        rows = self._collect(manager, monkeypatch, pages, endpoint="products")
        assert rows == [{"id": 7}]

    def test_missing_list_key_raises(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()

        def fake_fetch(session: Any, path: str, shop_domain: str, page: int, logger: Any) -> dict:
            return {"current_page": 1, "per_page": PAGE_SIZE}

        monkeypatch.setattr(judgeme_reviews, "_fetch_page", fake_fetch)
        monkeypatch.setattr(judgeme_reviews, "make_tracked_session", lambda **kwargs: MagicMock())

        with pytest.raises(JudgeMeReviewsRetryableError):
            list(
                get_rows(
                    api_token="jm-token",
                    shop_domain="example.myshopify.com",
                    endpoint="reviews",
                    logger=MagicMock(),
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                )
            )


class TestFetchPage:
    def _session_returning(
        self, status_code: int, body: Any = None, headers: dict[str, str] | None = None
    ) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.ok = status_code < 400
        response.json.return_value = body if body is not None else {}
        response.text = ""
        response.headers = headers or {}
        response.raise_for_status.side_effect = (
            requests.HTTPError(f"{status_code} error", response=response) if status_code >= 400 else None
        )
        session = MagicMock()
        session.get.return_value = response
        return session

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(JudgeMeReviewsRetryableError):
            _fetch_page_unwrapped(session, "/reviews", "example.myshopify.com", 1, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        session = self._session_returning(status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "/reviews", "example.myshopify.com", 1, MagicMock())

    def test_rate_limit_sleeps_for_retry_after(self) -> None:
        session = self._session_returning(429, headers={"Retry-After": "7"})
        with patch.object(judgeme_reviews.time, "sleep") as mock_sleep:
            with pytest.raises(JudgeMeReviewsRetryableError):
                _fetch_page_unwrapped(session, "/reviews", "example.myshopify.com", 1, MagicMock())
        mock_sleep.assert_called_once_with(7)

    def test_success_returns_json_body(self) -> None:
        body = _page([{"id": 1}])
        session = self._session_returning(200, body)
        result = _fetch_page_unwrapped(session, "/reviews", "example.myshopify.com", 1, MagicMock())
        assert result == body

    def test_non_dict_body_is_retryable(self) -> None:
        session = self._session_returning(200, [{"id": 1}])
        with pytest.raises(JudgeMeReviewsRetryableError):
            _fetch_page_unwrapped(session, "/reviews", "example.myshopify.com", 1, MagicMock())

    def test_request_params_include_shop_domain_and_pagination(self) -> None:
        session = self._session_returning(200, _page([]))
        _fetch_page_unwrapped(session, "/products", "example.myshopify.com", 3, MagicMock())
        _, kwargs = session.get.call_args
        assert kwargs["params"] == {"shop_domain": "example.myshopify.com", "page": 3, "per_page": PAGE_SIZE}

    @parameterized.expand(
        [
            ("missing", None, None),
            ("integer", "12", 12),
            ("zero", "0", None),
            ("http_date", "Wed, 21 Oct 2026 07:28:00 GMT", None),
        ]
    )
    def test_parse_retry_after(self, _name: str, value: str | None, expected: int | None) -> None:
        assert _parse_retry_after(value) == expected


class TestNormalizeShopDomain:
    @parameterized.expand(
        [
            ("bare", "example.myshopify.com", "example.myshopify.com"),
            ("https", "https://example.myshopify.com", "example.myshopify.com"),
            ("http", "http://example.myshopify.com", "example.myshopify.com"),
            ("trailing_slash", "https://example.myshopify.com/", "example.myshopify.com"),
            ("whitespace", "  example.myshopify.com ", "example.myshopify.com"),
        ]
    )
    def test_normalization(self, _name: str, raw: str, expected: str) -> None:
        assert _normalize_shop_domain(raw) == expected


class TestCheckAccess:
    def _patch_session(self, response: Any) -> Any:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return patch.object(judgeme_reviews, "make_tracked_session", lambda **kwargs: session)

    @parameterized.expand(
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "Judge.me returned HTTP 500"),
        ]
    )
    def test_status_mapping(self, status: int, ok: bool, expected_status: int, expected_message: str | None) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        with self._patch_session(response):
            assert check_access("jm-token", "example.myshopify.com") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self) -> None:
        with self._patch_session(requests.ConnectionError("boom")):
            status, message = check_access("jm-token", "example.myshopify.com")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "Invalid Judge.me shop domain or API token"),
            (403, False, "Invalid Judge.me shop domain or API token"),
            (500, False, "Judge.me returned HTTP 500"),
        ]
    )
    def test_validate_credentials(self, status: int, expected_valid: bool, expected_message: str | None) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        with self._patch_session(response):
            assert validate_credentials("jm-token", "example.myshopify.com") == (expected_valid, expected_message)


class TestJudgeMeReviewsSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = judgeme_reviews_source(
            api_token="jm-token",
            shop_domain="example.myshopify.com",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Response ordering is undocumented and syncs are full refresh, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in JUDGEME_REVIEWS_ENDPOINTS.values())
        assert set(JUDGEME_REVIEWS_ENDPOINTS) == set(ENDPOINTS)
