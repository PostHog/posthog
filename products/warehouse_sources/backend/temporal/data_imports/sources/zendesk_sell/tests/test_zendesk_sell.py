import json
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sell import zendesk_sell
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sell.zendesk_sell import (
    PER_PAGE,
    ZendeskSellResumeConfig,
    ZendeskSellRetryableError,
    ZendeskSellUntrustedURLError,
    _build_initial_url,
    _extract_records,
    _fetch_page,
    _validate_pagination_url,
    get_rows,
    validate_credentials,
    zendesk_sell_source,
)


class _FakeResumableManager:
    def __init__(self, state: ZendeskSellResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[ZendeskSellResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> ZendeskSellResumeConfig | None:
        return self._state

    def save_state(self, data: ZendeskSellResumeConfig) -> None:
        self.saved.append(data)


def _envelope(records: list[dict[str, Any]], next_page: str | None) -> dict[str, Any]:
    """Build the Zendesk Sell collection envelope around a list of record dicts."""
    links: dict[str, Any] = {"self": "https://api.getbase.com/v2/contacts?page=1&per_page=100"}
    if next_page:
        links["next_page"] = next_page
    return {
        "items": [{"data": r, "meta": {"type": "contact"}} for r in records],
        "meta": {"type": "collection", "count": len(records), "links": links},
    }


def _response_with(status_code: int, body: dict[str, Any] | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(body or {}).encode()
    response.url = "https://api.getbase.com/v2/contacts"
    return response


# The undecorated function behind tenacity's retry wrapper — call it to exercise status handling
# without the retry/backoff loop actually sleeping.
_fetch_page_unwrapped = _fetch_page.__wrapped__  # type: ignore[attr-defined]


class TestExtractRecords:
    @parameterized.expand(
        [
            ("empty", {"items": []}, []),
            ("missing_items", {"meta": {}}, []),
            (
                "single",
                {"items": [{"data": {"id": 1, "name": "Acme"}, "meta": {"type": "contact"}}]},
                [{"id": 1, "name": "Acme"}],
            ),
        ]
    )
    def test_extract_records(self, _name: str, payload: dict[str, Any], expected: list[dict[str, Any]]) -> None:
        assert _extract_records(payload) == expected

    def test_item_without_data_fails_fast(self) -> None:
        # Every envelope item carries `data`; a missing key means a malformed response, which should
        # raise rather than silently drop the record.
        with pytest.raises(KeyError):
            _extract_records({"items": [{"meta": {"type": "contact"}}]})


class TestBuildInitialUrl:
    def test_uses_base_url_and_max_page_size(self) -> None:
        assert _build_initial_url("/v2/deals") == f"https://api.getbase.com/v2/deals?per_page={PER_PAGE}"


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = _response_with(status_code)
        with pytest.raises(ZendeskSellRetryableError):
            _fetch_page_unwrapped(session, "https://api.getbase.com/v2/contacts", {}, MagicMock())

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = _response_with(status_code)
        with pytest.raises(requests.HTTPError):
            _fetch_page_unwrapped(session, "https://api.getbase.com/v2/contacts", {}, MagicMock())

    def test_ok_returns_parsed_json(self) -> None:
        session = MagicMock()
        session.get.return_value = _response_with(200, _envelope([{"id": 1}], next_page=None))
        result = _fetch_page_unwrapped(session, "https://api.getbase.com/v2/contacts", {}, MagicMock())
        assert result["items"][0]["data"] == {"id": 1}


class TestGetRowsPagination:
    @staticmethod
    def _collect(manager: _FakeResumableManager, monkeypatch: Any, pages: dict[str, Any]) -> list[dict[str, Any]]:
        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict[str, Any]:
            result = pages[url]
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(zendesk_sell, "_fetch_page", fake_fetch)

        rows: list[dict[str, Any]] = []
        for batch in get_rows(
            access_token="token",
            endpoint="contacts",
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(batch)
        return rows

    def test_yields_flattened_records_across_pages(self, monkeypatch: Any) -> None:
        page2 = "https://api.getbase.com/v2/contacts?page=2&per_page=100"
        pages = {
            f"https://api.getbase.com/v2/contacts?per_page={PER_PAGE}": _envelope(
                [{"id": 1}, {"id": 2}], next_page=page2
            ),
            page2: _envelope([{"id": 3}], next_page=None),
        }
        rows = self._collect(_FakeResumableManager(), monkeypatch, pages)
        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]

    def test_saves_state_only_when_more_pages_remain(self, monkeypatch: Any) -> None:
        page2 = "https://api.getbase.com/v2/contacts?page=2&per_page=100"
        pages = {
            f"https://api.getbase.com/v2/contacts?per_page={PER_PAGE}": _envelope([{"id": 1}], next_page=page2),
            page2: _envelope([{"id": 2}], next_page=None),
        }
        manager = _FakeResumableManager()
        self._collect(manager, monkeypatch, pages)
        # Exactly one checkpoint: after the first page (which had a next_page). The final page must not
        # persist state, so a completed sync leaves nothing to resume into.
        assert manager.saved == [ZendeskSellResumeConfig(next_url=page2)]

    def test_resumes_from_saved_next_url(self, monkeypatch: Any) -> None:
        page2 = "https://api.getbase.com/v2/contacts?page=2&per_page=100"
        pages = {
            page2: _envelope([{"id": 2}], next_page=None),
        }
        manager = _FakeResumableManager(ZendeskSellResumeConfig(next_url=page2))
        rows = self._collect(manager, monkeypatch, pages)
        # The initial page is never requested — only the saved next_url is fetched.
        assert rows == [{"id": 2}]

    def test_empty_collection_yields_nothing(self, monkeypatch: Any) -> None:
        pages = {
            f"https://api.getbase.com/v2/contacts?per_page={PER_PAGE}": _envelope([], next_page=None),
        }
        manager = _FakeResumableManager()
        rows = self._collect(manager, monkeypatch, pages)
        assert rows == []
        assert manager.saved == []

    def test_hostile_upstream_next_page_is_rejected(self, monkeypatch: Any) -> None:
        # An upstream response pointing next_page at another host must abort before the bearer token is
        # sent there, and must not be persisted as resume state.
        pages = {
            f"https://api.getbase.com/v2/contacts?per_page={PER_PAGE}": _envelope(
                [{"id": 1}], next_page="https://evil.example.com/v2/contacts"
            ),
        }
        manager = _FakeResumableManager()
        with pytest.raises(ZendeskSellUntrustedURLError):
            self._collect(manager, monkeypatch, pages)
        assert manager.saved == []

    def test_hostile_resumed_next_url_is_rejected(self, monkeypatch: Any) -> None:
        # A poisoned resume state from Redis must never be requested with the bearer token.
        manager = _FakeResumableManager(ZendeskSellResumeConfig(next_url="https://evil.example.com/v2/contacts"))
        with pytest.raises(ZendeskSellUntrustedURLError):
            self._collect(manager, monkeypatch, {})


class TestValidatePaginationUrl:
    @parameterized.expand(
        [
            ("first_page", f"https://api.getbase.com/v2/contacts?per_page={PER_PAGE}"),
            ("next_page", "https://api.getbase.com/v2/contacts?page=2&per_page=100"),
            ("other_endpoint", "https://api.getbase.com/v2/deals?page=3"),
        ]
    )
    def test_trusted_urls_pass_through(self, _name: str, url: str) -> None:
        assert _validate_pagination_url(url) == url

    @parameterized.expand(
        [
            ("foreign_host", "https://evil.example.com/v2/contacts"),
            ("subdomain_lookalike", "https://api.getbase.com.evil.example.com/v2/contacts"),
            ("http_scheme", "http://api.getbase.com/v2/contacts"),
            ("wrong_path_prefix", "https://api.getbase.com/internal/contacts"),
            ("missing_path", "https://api.getbase.com"),
            ("metadata_endpoint", "http://169.254.169.254/latest/meta-data/"),
        ]
    )
    def test_untrusted_urls_raise(self, _name: str, url: str) -> None:
        with pytest.raises(ZendeskSellUntrustedURLError):
            _validate_pagination_url(url)


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = _response_with(status_code)
        with patch.object(zendesk_sell, "make_tracked_session", return_value=session):
            assert validate_credentials("token") is expected

    def test_network_error_is_false(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(zendesk_sell, "make_tracked_session", return_value=session):
            assert validate_credentials("token") is False


class TestTokenRedaction:
    """The bearer token must be registered for value-redaction in tracked transport so it can't leak
    into logged URLs or captured request samples."""

    def test_validate_credentials_redacts_token(self) -> None:
        session = MagicMock()
        session.get.return_value = _response_with(200)
        with patch.object(zendesk_sell, "make_tracked_session", return_value=session) as make_session:
            validate_credentials("secret-token")
        assert make_session.call_args.kwargs["redact_values"] == ("secret-token",)
        assert make_session.call_args.kwargs["allow_redirects"] is False

    def test_get_rows_redacts_token(self, monkeypatch: Any) -> None:
        session = MagicMock()
        make_session = MagicMock(return_value=session)
        monkeypatch.setattr(zendesk_sell, "make_tracked_session", make_session)
        monkeypatch.setattr(
            zendesk_sell,
            "_fetch_page",
            lambda *a, **k: _envelope([], next_page=None),
        )
        list(
            get_rows(
                access_token="secret-token",
                endpoint="contacts",
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
            )
        )
        assert make_session.call_args.kwargs["redact_values"] == ("secret-token",)
        assert make_session.call_args.kwargs["allow_redirects"] is False


class TestZendeskSellSource:
    def test_partitioned_endpoint_response(self) -> None:
        response = zendesk_sell_source(
            access_token="token",
            endpoint="contacts",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == "contacts"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    def test_unpartitioned_lookup_endpoint_response(self) -> None:
        response = zendesk_sell_source(
            access_token="token",
            endpoint="stages",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == "stages"
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None
