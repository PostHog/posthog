from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bluetally import bluetally
from products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.bluetally import (
    PAGE_SIZE,
    BluetallyResumeConfig,
    BluetallyRetryableError,
    _build_url,
    bluetally_source,
    get_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.settings import (
    BLUETALLY_ENDPOINTS,
    ENDPOINTS,
)


class _FakeResumableManager:
    def __init__(self, state: BluetallyResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[BluetallyResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> BluetallyResumeConfig | None:
        return self._state

    def save_state(self, data: BluetallyResumeConfig) -> None:
        self.saved.append(data)


def _response_with_status(status_code: int, body: Any = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = b"" if body is None else str(body).encode()
    return response


class TestBuildUrl:
    def test_includes_all_pagination_params(self) -> None:
        url = _build_url("/assets", {"limit": 1000, "offset": 0, "sort": "created_at", "order": "asc"})
        assert url == "https://app.bluetallyapp.com/api/v1/assets?limit=1000&offset=0&sort=created_at&order=asc"

    def test_omits_none_tenant_id(self) -> None:
        url = _build_url("/employees", {"limit": 50, "offset": 0, "tenant_id": None})
        assert "tenant_id" not in url

    def test_includes_tenant_id_when_set(self) -> None:
        url = _build_url("/employees", {"offset": 0, "tenant_id": "42"})
        assert "tenant_id=42" in url

    def test_offset_zero_is_kept(self) -> None:
        # offset=0 is the first page; it must not be dropped as a falsy value.
        url = _build_url("/assets", {"offset": 0})
        assert "offset=0" in url


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response_with_status(status)
        # No-op the backoff sleep so the 5 attempts run instantly.
        with patch.object(bluetally._fetch_page.retry, "sleep", lambda *a, **k: None):  # type: ignore[attr-defined]
            with pytest.raises(BluetallyRetryableError):
                bluetally._fetch_page(session, "https://app.bluetallyapp.com/api/v1/assets", MagicMock())
        assert session.get.call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response_with_status(status)
        with pytest.raises(requests.HTTPError):
            bluetally._fetch_page(session, "https://app.bluetallyapp.com/api/v1/assets", MagicMock())

    def test_returns_list_payload(self) -> None:
        response = _response_with_status(200)
        response._content = b'[{"id": 1}, {"id": 2}]'
        session = MagicMock()
        session.get.return_value = response
        rows = bluetally._fetch_page(session, "https://app.bluetallyapp.com/api/v1/assets", MagicMock())
        assert rows == [{"id": 1}, {"id": 2}]

    def test_non_list_payload_raises_value_error(self) -> None:
        # A non-list 200 is a permanent contract violation, so it must bypass the retry decorator.
        response = _response_with_status(200)
        response._content = b'{"error": "unexpected"}'
        session = MagicMock()
        session.get.return_value = response
        with pytest.raises(ValueError):
            bluetally._fetch_page(session, "https://app.bluetallyapp.com/api/v1/assets", MagicMock())
        assert session.get.call_count == 1


class TestGetRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: list[list[dict]],
        tenant_id: str | None = None,
    ) -> tuple[list[dict], list[str]]:
        fetched_urls: list[str] = []

        def fake_fetch(session: Any, url: str, logger: Any) -> list[dict]:
            fetched_urls.append(url)
            # Map the requested offset to the corresponding canned page.
            offset = int(url.split("offset=")[1].split("&")[0])
            index = offset // PAGE_SIZE
            return pages[index] if index < len(pages) else []

        monkeypatch.setattr(bluetally, "_fetch_page", fake_fetch)
        monkeypatch.setattr(bluetally, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for page in get_rows(
            api_key="key",
            endpoint="assets",
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            tenant_id=tenant_id,
        ):
            rows.extend(page)
        return rows, fetched_urls

    def test_single_short_page_stops_without_saving_state(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, urls = self._collect(manager, monkeypatch, [[{"id": 1}, {"id": 2}]])
        assert rows == [{"id": 1}, {"id": 2}]
        assert len(urls) == 1
        # A short first page never advances the offset, so no resume state is persisted.
        assert manager.saved == []

    def test_paginates_until_short_page(self, monkeypatch: Any) -> None:
        full_page = [{"id": i} for i in range(PAGE_SIZE)]
        last_page = [{"id": PAGE_SIZE}]
        manager = _FakeResumableManager()
        rows, urls = self._collect(manager, monkeypatch, [full_page, last_page])
        assert len(rows) == PAGE_SIZE + 1
        assert len(urls) == 2
        # State is saved after the full page (pointing at the next offset), then we stop on the short page.
        assert manager.saved == [BluetallyResumeConfig(offset=PAGE_SIZE)]

    def test_resumes_from_saved_offset(self, monkeypatch: Any) -> None:
        full_page = [{"id": i} for i in range(PAGE_SIZE)]
        last_page = [{"id": PAGE_SIZE}]
        manager = _FakeResumableManager(BluetallyResumeConfig(offset=PAGE_SIZE))
        rows, urls = self._collect(manager, monkeypatch, [full_page, last_page])
        # Resuming at offset=PAGE_SIZE skips the already-synced first page.
        assert rows == [{"id": PAGE_SIZE}]
        assert urls == [
            f"https://app.bluetallyapp.com/api/v1/assets?limit={PAGE_SIZE}&offset={PAGE_SIZE}&sort=created_at&order=asc"
        ]

    def test_threads_tenant_id_into_requests(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        _, urls = self._collect(manager, monkeypatch, [[{"id": 1}]], tenant_id="99")
        assert all("tenant_id=99" in url for url in urls)

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, urls = self._collect(manager, monkeypatch, [[]])
        assert rows == []
        assert len(urls) == 1


class TestBluetallySourceResponse:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, name: str) -> None:
        response = bluetally_source(
            api_key="key",
            endpoint=name,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == name
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        # Stable creation timestamp drives datetime partitioning for every endpoint.
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"

    def test_every_endpoint_partitions_on_created_at(self) -> None:
        # Guards against accidentally partitioning on a churning field like updated_at.
        assert all(cfg.partition_key == "created_at" for cfg in BLUETALLY_ENDPOINTS.values())
