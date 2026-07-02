from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.pexels import pexels
from products.warehouse_sources.backend.temporal.data_imports.sources.pexels.pexels import (
    PexelsResumeConfig,
    _build_url,
    _get_headers,
    get_rows,
    pexels_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pexels.settings import PEXELS_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: PexelsResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[PexelsResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> PexelsResumeConfig | None:
        return self._state

    def save_state(self, data: PexelsResumeConfig) -> None:
        self.saved.append(data)


class TestHeaders:
    def test_authorization_header_is_raw_key_without_bearer_prefix(self) -> None:
        # Pexels rejects a "Bearer " prefix — the key must be the raw Authorization value.
        headers = _get_headers("my-secret-key")
        assert headers["Authorization"] == "my-secret-key"
        assert "Bearer" not in headers["Authorization"]


class TestBuildUrl:
    @parameterized.expand(
        [
            ("encodes_spaces", "https://api.pexels.com/v1/search", {"query": "red car"}, "query=red+car"),
            ("no_params", "https://api.pexels.com/v1/curated", {}, None),
            ("page_param", "https://api.pexels.com/v1/curated", {"per_page": 80, "page": 2}, "per_page=80&page=2"),
        ]
    )
    def test_build_url(self, _name: str, base: str, params: dict, expected_fragment: str | None) -> None:
        url = _build_url(base, params)
        if expected_fragment is None:
            assert url == base
        else:
            assert expected_fragment in url


class TestGetRows:
    @staticmethod
    def _run(manager: _FakeResumableManager, pages: dict[int, Any], endpoint: str, **kwargs: Any) -> list[dict]:
        def fake_fetch(session: Any, url: str, headers: dict, logger: Any) -> dict:
            # Derive the page number from the URL so the fake mirrors real page-number paging.
            page = int(parse_qs(urlparse(url).query).get("page", ["1"])[0])
            return pages[page]

        with patch.object(pexels, "_fetch_page", fake_fetch), patch.object(pexels, "make_tracked_session", MagicMock()):
            rows: list[dict] = []
            for batch in get_rows(
                api_key="k",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
                **kwargs,
            ):
                rows.extend(batch)
            return rows

    def test_paginates_until_next_page_absent(self) -> None:
        pages = {
            1: {"photos": [{"id": 1}, {"id": 2}], "next_page": "https://api.pexels.com/v1/curated?page=2&per_page=80"},
            2: {"photos": [{"id": 3}]},  # no next_page -> terminate
        }
        rows = self._run(_FakeResumableManager(), pages, "curated_photos")
        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]

    def test_stops_on_empty_page(self) -> None:
        pages = {1: {"photos": [], "next_page": "https://api.pexels.com/v1/curated?page=2&per_page=80"}}
        rows = self._run(_FakeResumableManager(), pages, "curated_photos")
        assert rows == []

    def test_reads_videos_data_key(self) -> None:
        # popular_videos reads the "videos" key, not "photos".
        pages = {1: {"videos": [{"id": 9}], "photos": [{"id": 111}]}}
        rows = self._run(_FakeResumableManager(), pages, "popular_videos")
        assert rows == [{"id": 9}]

    def test_search_endpoint_sends_query_param(self) -> None:
        captured: list[str] = []

        def fake_fetch(session: Any, url: str, headers: dict, logger: Any) -> dict:
            captured.append(url)
            return {"photos": [{"id": 1}]}

        with patch.object(pexels, "_fetch_page", fake_fetch), patch.object(pexels, "make_tracked_session", MagicMock()):
            list(
                get_rows(
                    api_key="k",
                    endpoint="search_photos",
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                    search_query="red car",
                )
            )

        assert "query=red+car" in captured[0]
        assert "/v1/search" in captured[0]

    @parameterized.expand([("none", None), ("empty", "")])
    def test_search_endpoint_without_query_raises(self, _name: str, query: str | None) -> None:
        # A missing query on a search endpoint must fail loudly, not send a literal `?query=None`.
        with patch.object(pexels, "make_tracked_session", MagicMock()):
            with pytest.raises(ValueError, match="requires a search query"):
                list(
                    get_rows(
                        api_key="k",
                        endpoint="search_photos",
                        logger=MagicMock(),
                        resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                        search_query=query,
                    )
                )

    def test_saves_current_page_after_each_yield(self) -> None:
        # State must point at the just-yielded page so a crash re-fetches (and merge-dedupes) it
        # rather than skipping it.
        manager = _FakeResumableManager()
        pages = {
            1: {"photos": [{"id": 1}], "next_page": "https://api.pexels.com/v1/curated?page=2&per_page=80"},
            2: {"photos": [{"id": 2}]},
        }
        self._run(manager, pages, "curated_photos")
        assert [s.page for s in manager.saved] == [1, 2]

    def test_resumes_from_saved_page(self) -> None:
        # A resumed job must start at the saved page, not page 1.
        manager = _FakeResumableManager(PexelsResumeConfig(page=2))
        pages = {
            1: {"photos": [{"id": 1}]},
            2: {"photos": [{"id": 2}]},
        }
        rows = self._run(manager, pages, "curated_photos")
        assert rows == [{"id": 2}]


class TestPexelsSourceResponse:
    @parameterized.expand([(name,) for name in PEXELS_ENDPOINTS])
    def test_response_is_full_refresh_with_id_primary_key(self, endpoint: str) -> None:
        # Every endpoint keys on the global `id` and declares no datetime partition — Pexels has no
        # stable timestamp, so a partition key would rewrite partitions every sync.
        response = pexels_source(
            api_key="k",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        )
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_keys is None
        assert response.partition_mode is None


class TestApiKeyRedaction:
    # Pexels sends the key as a raw Authorization value the sampler can't scrub by name, so the
    # source must register it via redact_values or the plaintext key leaks into captured samples.
    def test_get_rows_registers_api_key_for_redaction(self) -> None:
        factory = MagicMock()
        with (
            patch.object(pexels, "_fetch_page", lambda *_: {"photos": []}),
            patch.object(pexels, "make_tracked_session", factory),
        ):
            list(
                get_rows(
                    api_key="secret-key",
                    endpoint="curated_photos",
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                )
            )
        assert factory.call_args.kwargs["redact_values"] == ("secret-key",)

    def test_validate_credentials_registers_api_key_for_redaction(self) -> None:
        factory = MagicMock()
        factory.return_value.get.return_value = MagicMock(status_code=200)
        with patch.object(pexels, "make_tracked_session", factory):
            validate_credentials("secret-key")
        assert factory.call_args.kwargs["redact_values"] == ("secret-key",)


class TestFetchPageRetries:
    @parameterized.expand(
        [
            ("rate_limited", 429),
            ("server_error", 500),
            ("bad_gateway", 502),
        ]
    )
    def test_retryable_status_codes_are_retried(self, _name: str, status_code: int) -> None:
        bad = MagicMock(status_code=status_code, ok=False)
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"photos": []}
        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(pexels._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = pexels._fetch_page(session, "https://api.pexels.com/v1/curated", {}, MagicMock())

        assert result == {"photos": []}
        assert session.get.call_count == 2

    @parameterized.expand(
        [
            ("read_timeout", requests.ReadTimeout("Read timed out.")),
            ("connection_error", requests.ConnectionError("Connection reset by peer")),
            ("chunked", requests.exceptions.ChunkedEncodingError("Connection broken")),
        ]
    )
    def test_transient_errors_are_retried(self, _name: str, err: Exception) -> None:
        good = MagicMock(status_code=200, ok=True)
        good.json.return_value = {"photos": []}
        session = MagicMock()
        session.get.side_effect = [err, good]

        with patch.object(pexels._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = pexels._fetch_page(session, "https://api.pexels.com/v1/curated", {}, MagicMock())

        assert result == {"photos": []}
        assert session.get.call_count == 2

    def test_unauthorized_raises_and_is_not_retried(self) -> None:
        # A 401 is a credential problem — it must surface immediately (raise_for_status), not retry.
        response = requests.Response()
        response.status_code = 401
        response._content = b'{"code":"Unauthorized"}'
        response.url = "https://api.pexels.com/v1/curated"
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            pexels._fetch_page(session, "https://api.pexels.com/v1/curated", {}, MagicMock())
        assert session.get.call_count == 1


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_bool(self, _name: str, status_code: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status_code)
        with patch.object(pexels, "make_tracked_session", return_value=session):
            assert validate_credentials("k") is expected

    def test_network_error_is_false(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(pexels, "make_tracked_session", return_value=session):
            assert validate_credentials("k") is False
