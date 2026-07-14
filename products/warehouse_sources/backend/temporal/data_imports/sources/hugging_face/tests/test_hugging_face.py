from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.hugging_face import hugging_face
from products.warehouse_sources.backend.temporal.data_imports.sources.hugging_face.hugging_face import (
    HuggingFaceResumeConfig,
    HuggingFaceRetryableError,
    _build_initial_url,
    _parse_next_url,
    get_rows,
    hugging_face_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hugging_face.settings import (
    HUGGING_FACE_ENDPOINTS,
)


class _FakeResumableManager:
    def __init__(self, state: HuggingFaceResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[HuggingFaceResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> HuggingFaceResumeConfig | None:
        return self._state

    def save_state(self, data: HuggingFaceResumeConfig) -> None:
        self.saved.append(data)


class _FakeResponse:
    def __init__(self, items: Any, next_url: str | None) -> None:
        self._items = items
        link = f'<{next_url}>; rel="next"' if next_url else ""
        self.headers = {"Link": link}

    def json(self) -> Any:
        return self._items


class TestParseNextUrl:
    @parameterized.expand(
        [
            (
                "next_only",
                '<https://huggingface.co/api/models?cursor=abc>; rel="next"',
                "https://huggingface.co/api/models?cursor=abc",
            ),
            (
                "prev_and_next",
                '<https://huggingface.co/api/models?cursor=p>; rel="prev", '
                '<https://huggingface.co/api/models?cursor=n>; rel="next"',
                "https://huggingface.co/api/models?cursor=n",
            ),
            ("no_next", '<https://huggingface.co/api/models?cursor=p>; rel="prev"', None),
            ("empty", "", None),
        ]
    )
    def test_parse_next_url(self, _name: str, header: str, expected: str | None) -> None:
        assert _parse_next_url(header) == expected


class TestBuildInitialUrl:
    def test_models_url_is_scoped_sorted_and_full(self) -> None:
        url = _build_initial_url(HUGGING_FACE_ENDPOINTS["models"], author="huggingface")
        assert url.startswith("https://huggingface.co/api/models?")
        assert "author=huggingface" in url
        # createdAt is immutable, so ascending pages don't shift mid-sync.
        assert "sort=createdAt" in url
        assert "direction=1" in url
        assert "limit=1000" in url
        assert "full=true" in url

    @parameterized.expand([("models",), ("datasets",), ("spaces",)])
    def test_every_endpoint_builds_a_scoped_url(self, endpoint: str) -> None:
        url = _build_initial_url(HUGGING_FACE_ENDPOINTS[endpoint], author="acme")
        assert f"/api/{endpoint}?" in url
        assert "author=acme" in url


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_bool(self, _name: str, status_code: int, expected: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response
        with patch.object(hugging_face, "make_tracked_session", return_value=session):
            assert validate_credentials("hf_token") is expected

    def test_network_error_is_false(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(hugging_face, "make_tracked_session", return_value=session):
            assert validate_credentials("hf_token") is False


class TestFetchPage:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_raises_retryable_error(self, _name: str, status_code: int) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response
        with patch.object(hugging_face._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(HuggingFaceRetryableError):
                hugging_face._fetch_page(session, "https://huggingface.co/api/models", {}, MagicMock())

    @parameterized.expand([("read_timeout", requests.ReadTimeout()), ("connection", requests.ConnectionError())])
    def test_transient_errors_are_retried_then_succeed(self, _name: str, transient: Exception) -> None:
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        session = MagicMock()
        session.get.side_effect = [transient, good]
        with patch.object(hugging_face._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = hugging_face._fetch_page(session, "https://huggingface.co/api/models", {}, MagicMock())
        assert result is good

    def test_unauthorized_raises_for_status(self) -> None:
        response = MagicMock()
        response.status_code = 401
        response.ok = False
        response.raise_for_status.side_effect = requests.HTTPError(
            "401 Client Error: Unauthorized", response=requests.Response()
        )
        session = MagicMock()
        session.get.return_value = response
        with pytest.raises(requests.HTTPError):
            hugging_face._fetch_page(session, "https://huggingface.co/api/models", {}, MagicMock())


def _collect(manager: _FakeResumableManager, monkeypatch: Any, pages: dict[str, _FakeResponse], endpoint: str) -> list:
    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> _FakeResponse:
        return pages[url]

    monkeypatch.setattr(hugging_face, "_fetch_page", fake_fetch)
    monkeypatch.setattr(hugging_face, "make_tracked_session", lambda *a, **k: MagicMock())

    rows: list = []
    for page in get_rows(
        api_token="hf_token",
        endpoint=endpoint,
        author="acme",
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(page)
    return rows


class TestGetRows:
    def test_follows_link_header_pagination(self, monkeypatch: Any) -> None:
        start = _build_initial_url(HUGGING_FACE_ENDPOINTS["models"], author="acme")
        page2 = "https://huggingface.co/api/models?cursor=2"
        pages = {
            start: _FakeResponse([{"id": "acme/a"}, {"id": "acme/b"}], next_url=page2),
            page2: _FakeResponse([{"id": "acme/c"}], next_url=None),
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, "models")
        assert [r["id"] for r in rows] == ["acme/a", "acme/b", "acme/c"]

    def test_checkpoints_current_page_after_yield(self, monkeypatch: Any) -> None:
        # Saving the current (not next) page URL means a crash re-fetches it; merge dedupes on id.
        start = _build_initial_url(HUGGING_FACE_ENDPOINTS["models"], author="acme")
        page2 = "https://huggingface.co/api/models?cursor=2"
        pages = {
            start: _FakeResponse([{"id": "acme/a"}], next_url=page2),
            page2: _FakeResponse([{"id": "acme/b"}], next_url=None),
        }
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, pages, "models")
        # Only the first page has a next page, so exactly one checkpoint — pointing at the first page.
        assert [s.resume_url for s in manager.saved] == [start]

    def test_resumes_from_saved_state(self, monkeypatch: Any) -> None:
        start = _build_initial_url(HUGGING_FACE_ENDPOINTS["models"], author="acme")
        page2 = "https://huggingface.co/api/models?cursor=2"
        pages = {
            start: _FakeResponse([{"id": "acme/a"}], next_url=page2),
            page2: _FakeResponse([{"id": "acme/b"}], next_url=None),
        }
        manager = _FakeResumableManager(state=HuggingFaceResumeConfig(resume_url=page2))
        rows = _collect(manager, monkeypatch, pages, "models")
        # Resuming at page2 skips the already-synced first page.
        assert [r["id"] for r in rows] == ["acme/b"]

    def test_empty_response_terminates(self, monkeypatch: Any) -> None:
        start = _build_initial_url(HUGGING_FACE_ENDPOINTS["datasets"], author="acme")
        pages = {start: _FakeResponse([], next_url="https://huggingface.co/api/datasets?cursor=2")}
        rows = _collect(_FakeResumableManager(), monkeypatch, pages, "datasets")
        assert rows == []


class TestHuggingFaceSource:
    @parameterized.expand([("models",), ("datasets",), ("spaces",)])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = hugging_face_source(
            api_token="hf_token",
            endpoint=endpoint,
            author="acme",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]
