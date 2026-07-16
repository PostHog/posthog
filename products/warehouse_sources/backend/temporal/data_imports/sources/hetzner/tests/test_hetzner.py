from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.hetzner import hetzner
from products.warehouse_sources.backend.temporal.data_imports.sources.hetzner.hetzner import (
    HETZNER_BASE_URL,
    HetznerResumeConfig,
    HetznerRetryableError,
    _build_url,
    _parse_retry_after,
    get_rows,
    hetzner_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hetzner.settings import HETZNER_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: HetznerResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[HetznerResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> HetznerResumeConfig | None:
        return self._state

    def save_state(self, data: HetznerResumeConfig) -> None:
        self.saved.append(data)


class _OneRowBatcher(Batcher):
    """Force a yield after every row so pagination/resume checkpoints are observable without
    materializing the 2000-row default chunk."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["chunk_size"] = 1
        super().__init__(*args, **kwargs)


def _mock_response(status_code: int, headers: dict[str, str] | None = None, body: Any = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.headers = headers or {}
    response.json.return_value = body if body is not None else {}
    response.text = "" if body is None else str(body)
    if not response.ok:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} Client Error for url: {HETZNER_BASE_URL}/servers", response=response
        )
    return response


def _servers_page(items: list[dict], next_page: int | None) -> dict:
    return {"servers": items, "meta": {"pagination": {"next_page": next_page}}}


class TestBuildUrl:
    def test_includes_pagination_and_sort(self) -> None:
        url = _build_url(HETZNER_ENDPOINTS["servers"], page=3)
        query = parse_qs(urlparse(url).query)
        assert url.startswith(f"{HETZNER_BASE_URL}/servers?")
        assert query["page"] == ["3"]
        assert query["per_page"] == ["50"]
        assert query["sort"] == ["id:asc"]

    def test_catalog_endpoint_omits_sort(self) -> None:
        # server_types has no verified sort support, so we must not send a sort param that could 400.
        url = _build_url(HETZNER_ENDPOINTS["server_types"], page=1)
        assert "sort" not in parse_qs(urlparse(url).query)


class TestParseRetryAfter:
    def test_prefers_retry_after_header(self) -> None:
        response = _mock_response(429, headers={"Retry-After": "12"})
        assert _parse_retry_after(response) == 12.0

    def test_falls_back_to_ratelimit_reset_minus_server_now(self) -> None:
        # Date parses to 1445412480 (server's "now"); reset is 60s later, so we wait ~60s using the
        # server clock rather than the local one (which may be skewed).
        response = _mock_response(
            429,
            headers={"RateLimit-Reset": "1445412540", "Date": "Wed, 21 Oct 2015 07:28:00 GMT"},
        )
        assert _parse_retry_after(response) == 60.0

    def test_returns_none_without_usable_headers(self) -> None:
        assert _parse_retry_after(_mock_response(429)) is None


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, None, True),
            ("unauthorized", 401, None, False),
            ("forbidden", 403, None, False),
        ]
    )
    def test_status_maps_to_validity(self, _name: str, status: int, body: Any, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(status, body=body)
        with patch.object(hetzner, "make_tracked_session", return_value=session):
            valid, _message = validate_credentials("token")
        assert valid is expected

    def test_network_error_is_invalid_not_raised(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(hetzner, "make_tracked_session", return_value=session):
            valid, message = validate_credentials("token")
        assert valid is False
        assert message == "boom"


class TestFetchPageRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_transient_status_raises_retryable(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(status, headers={"Retry-After": "1"} if status == 429 else {})
        with patch.object(hetzner._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(HetznerRetryableError):
                hetzner._fetch_page(session, f"{HETZNER_BASE_URL}/servers", {}, MagicMock())
        # 5 attempts (stop_after_attempt(5)) before giving up.
        assert session.get.call_count == 5

    def test_retries_then_succeeds(self) -> None:
        session = MagicMock()
        session.get.side_effect = [
            requests.ReadTimeout("slow"),
            _mock_response(200, body=_servers_page([], None)),
        ]
        with patch.object(hetzner._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = hetzner._fetch_page(session, f"{HETZNER_BASE_URL}/servers", {}, MagicMock())
        assert result == _servers_page([], None)
        assert session.get.call_count == 2

    def test_client_error_is_not_retried(self) -> None:
        # A 404/401 is fatal; raising HTTPError immediately (not retrying) lets get_non_retryable_errors act.
        session = MagicMock()
        session.get.return_value = _mock_response(401)
        with pytest.raises(requests.HTTPError):
            hetzner._fetch_page(session, f"{HETZNER_BASE_URL}/servers", {}, MagicMock())
        assert session.get.call_count == 1


class TestGetRows:
    @staticmethod
    def _collect(manager: _FakeResumableManager, responses: dict[int, dict], endpoint: str = "servers") -> list[dict]:
        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            page = int(parse_qs(urlparse(url).query)["page"][0])
            return responses[page]

        rows: list[dict] = []
        with patch.object(hetzner, "_fetch_page", fake_fetch):
            for table in get_rows("token", endpoint, MagicMock(), manager):  # type: ignore[arg-type]
                rows.extend(table.to_pylist())
        return rows

    def test_paginates_until_next_page_is_null(self) -> None:
        responses = {
            1: _servers_page([{"id": 1}, {"id": 2}], next_page=2),
            2: _servers_page([{"id": 3}], next_page=None),
        }
        rows = self._collect(_FakeResumableManager(), responses)
        assert [r["id"] for r in rows] == [1, 2, 3]

    def test_stops_when_response_key_empty(self) -> None:
        rows = self._collect(_FakeResumableManager(), {1: _servers_page([], next_page=2)})
        assert rows == []

    def test_resumes_from_saved_page(self) -> None:
        # A saved page must skip already-synced pages instead of restarting at page 1.
        responses = {2: _servers_page([{"id": 99}], next_page=None)}
        rows = self._collect(_FakeResumableManager(HetznerResumeConfig(page=2)), responses)
        assert [r["id"] for r in rows] == [99]

    def test_checkpoints_current_page_then_advances_past_end(self) -> None:
        # In-flight we checkpoint the CURRENT page (not next_page) so a crash re-fetches that page
        # instead of skipping its un-yielded tail and dropping rows. On completion we advance the
        # checkpoint past the last page so a post-final-write crash resumes onto an empty page rather
        # than replaying already-written pages into the full-refresh table.
        responses = {
            1: _servers_page([{"id": 1}, {"id": 2}], next_page=2),
            2: _servers_page([{"id": 3}], next_page=None),
        }
        manager = _FakeResumableManager()
        with patch.object(hetzner, "Batcher", _OneRowBatcher):
            self._collect(manager, responses)
        saved_pages = [state.page for state in manager.saved]
        # Page 1 yields twice (checkpoint 1), page 2 yields once (checkpoint 2), then the completion
        # sentinel advances to page 3 (the empty page past the end).
        assert saved_pages == [1, 1, 2, 3]


class TestHetznerSourceResponse:
    def test_datetime_partition_for_resource_endpoint(self) -> None:
        response = hetzner_source("token", "servers", MagicMock(), MagicMock())
        assert response.name == "servers"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created"]

    @parameterized.expand([("actions",), ("server_types",), ("locations",)])
    def test_no_partition_for_timestampless_endpoints(self, endpoint: str) -> None:
        # actions has no `created`; catalog endpoints carry no timestamps — partitioning on a null or
        # absent field would rewrite partitions every sync, so these must stay unpartitioned.
        response = hetzner_source("token", endpoint, MagicMock(), MagicMock())
        assert response.partition_mode is None
        assert response.partition_keys is None
