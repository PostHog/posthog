from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.giphy import giphy
from products.warehouse_sources.backend.temporal.data_imports.sources.giphy.giphy import (
    PAGE_SIZE,
    GiphyResumeConfig,
    _build_url,
    _fetch_page,
    _normalize_items,
    get_rows,
    giphy_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.giphy.settings import GIPHY_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: GiphyResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[GiphyResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> GiphyResumeConfig | None:
        return self._state

    def save_state(self, data: GiphyResumeConfig) -> None:
        self.saved.append(data)


def _gif_page(ids: list[str], offset: int, total_count: int) -> dict[str, Any]:
    return {
        "data": [{"id": i, "type": "gif"} for i in ids],
        "pagination": {"offset": offset, "count": len(ids), "total_count": total_count},
        "meta": {"status": 200, "msg": "OK"},
    }


class TestBuildUrl:
    def test_trending_has_limit_and_offset_no_query(self) -> None:
        url = _build_url("KEY", GIPHY_ENDPOINTS["gifs_trending"], offset=50, search_query=None)
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        assert parsed.path == "/v1/gifs/trending"
        assert params["api_key"] == ["KEY"]
        assert params["limit"] == [str(PAGE_SIZE)]
        assert params["offset"] == ["50"]
        assert "q" not in params

    def test_search_includes_query(self) -> None:
        url = _build_url("KEY", GIPHY_ENDPOINTS["gifs_search"], offset=0, search_query="cats")
        params = parse_qs(urlparse(url).query)
        assert params["q"] == ["cats"]
        assert params["limit"] == [str(PAGE_SIZE)]

    def test_term_list_has_no_pagination_params(self) -> None:
        url = _build_url("KEY", GIPHY_ENDPOINTS["trending_search_terms"], offset=0, search_query=None)
        params = parse_qs(urlparse(url).query)
        assert params["api_key"] == ["KEY"]
        assert "limit" not in params
        assert "offset" not in params


class TestNormalizeItems:
    def test_object_endpoint_passthrough(self) -> None:
        data = {"data": [{"id": "a"}, {"id": "b"}]}
        assert _normalize_items(GIPHY_ENDPOINTS["gifs_trending"], data) == [{"id": "a"}, {"id": "b"}]

    def test_term_list_wraps_strings(self) -> None:
        data = {"data": ["cats", "dogs"]}
        assert _normalize_items(GIPHY_ENDPOINTS["trending_search_terms"], data) == [
            {"search_term": "cats"},
            {"search_term": "dogs"},
        ]

    def test_missing_data_key_is_empty(self) -> None:
        assert _normalize_items(GIPHY_ENDPOINTS["gifs_trending"], {"meta": {}}) == []


class TestGetRows:
    @staticmethod
    def _collect(manager: _FakeResumableManager, monkeypatch: Any, pages: dict[str, Any], **kwargs: Any) -> list[dict]:
        def fake_fetch(session: Any, url: str, logger: Any) -> dict:
            # Key the fake pages by the offset query param so tests stay URL-order agnostic.
            offset = parse_qs(urlparse(url).query).get("offset", ["0"])[0]
            return pages[offset]

        monkeypatch.setattr(giphy, "_fetch_page", fake_fetch)

        rows: list[dict] = []
        for batch in get_rows(
            api_key="KEY",
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            **kwargs,
        ):
            rows.extend(batch)
        return rows

    def test_paginates_until_total_count_reached(self, monkeypatch: Any) -> None:
        pages = {
            "0": _gif_page([str(i) for i in range(PAGE_SIZE)], offset=0, total_count=PAGE_SIZE + 2),
            str(PAGE_SIZE): _gif_page(["x", "y"], offset=PAGE_SIZE, total_count=PAGE_SIZE + 2),
        }
        rows = self._collect(_FakeResumableManager(), monkeypatch, pages, endpoint="gifs_trending")
        assert len(rows) == PAGE_SIZE + 2
        assert rows[-1] == {"id": "y", "type": "gif"}

    def test_stops_on_short_page(self, monkeypatch: Any) -> None:
        # A page shorter than PAGE_SIZE means the result set is exhausted.
        pages = {"0": _gif_page(["a", "b"], offset=0, total_count=999)}
        rows = self._collect(_FakeResumableManager(), monkeypatch, pages, endpoint="gifs_trending")
        assert [r["id"] for r in rows] == ["a", "b"]

    def test_stops_on_empty_page(self, monkeypatch: Any) -> None:
        pages = {"0": _gif_page([], offset=0, total_count=0)}
        rows = self._collect(_FakeResumableManager(), monkeypatch, pages, endpoint="gifs_trending")
        assert rows == []

    def test_stops_at_offset_cap(self, monkeypatch: Any) -> None:
        # gifs_trending caps at offset 499. A full page lands next_offset at 500 > 499, so we stop
        # without ever requesting an offset GIPHY would reject, even though total_count is far larger.
        cap = GIPHY_ENDPOINTS["gifs_trending"].max_offset
        assert cap == 499
        requested_offsets: list[int] = []

        def fake_fetch(session: Any, url: str, logger: Any) -> dict:
            offset = int(parse_qs(urlparse(url).query)["offset"][0])
            requested_offsets.append(offset)
            return _gif_page([f"{offset}_{i}" for i in range(PAGE_SIZE)], offset=offset, total_count=10_000)

        monkeypatch.setattr(giphy, "_fetch_page", fake_fetch)
        list(
            get_rows(
                api_key="KEY",
                endpoint="gifs_trending",
                logger=MagicMock(),
                resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
            )
        )
        assert max(requested_offsets) <= cap
        assert max(requested_offsets) + PAGE_SIZE > cap

    def test_resumes_from_saved_offset(self, monkeypatch: Any) -> None:
        pages = {
            str(PAGE_SIZE): _gif_page(["x", "y"], offset=PAGE_SIZE, total_count=PAGE_SIZE + 2),
        }
        manager = _FakeResumableManager(GiphyResumeConfig(offset=PAGE_SIZE))
        rows = self._collect(manager, monkeypatch, pages, endpoint="gifs_trending")
        assert [r["id"] for r in rows] == ["x", "y"]

    def test_saves_state_after_each_batch(self, monkeypatch: Any) -> None:
        pages = {
            "0": _gif_page([str(i) for i in range(PAGE_SIZE)], offset=0, total_count=PAGE_SIZE + 1),
            str(PAGE_SIZE): _gif_page(["last"], offset=PAGE_SIZE, total_count=PAGE_SIZE + 1),
        }
        manager = _FakeResumableManager()
        self._collect(manager, monkeypatch, pages, endpoint="gifs_trending")
        # State is saved once, advancing to the second page's offset, before that page is fetched.
        assert [s.offset for s in manager.saved] == [PAGE_SIZE]

    def test_term_list_single_fetch(self, monkeypatch: Any) -> None:
        def fake_fetch(session: Any, url: str, logger: Any) -> dict:
            return {"data": ["cats", "dogs", "memes"], "meta": {"status": 200}}

        monkeypatch.setattr(giphy, "_fetch_page", fake_fetch)
        manager = _FakeResumableManager()
        rows = [
            r
            for batch in get_rows(
                api_key="KEY",
                endpoint="trending_search_terms",
                logger=MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
            )
            for r in batch
        ]
        assert rows == [{"search_term": "cats"}, {"search_term": "dogs"}, {"search_term": "memes"}]
        assert manager.saved == []

    @parameterized.expand(["gifs_search", "stickers_search"])
    def test_search_without_query_raises(self, endpoint: str) -> None:
        with pytest.raises(ValueError, match="requires a search query"):
            list(
                get_rows(
                    api_key="KEY",
                    endpoint=endpoint,
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                    search_query="   ",
                )
            )


class TestGiphySourceResponse:
    @parameterized.expand(
        [
            ("gifs_trending", ["id"]),
            ("stickers_trending", ["id"]),
            ("gifs_search", ["id"]),
            ("stickers_search", ["id"]),
            ("categories", ["name_encoded"]),
            ("trending_search_terms", ["search_term"]),
        ]
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, expected_keys: list[str]) -> None:
        response = giphy_source(
            api_key="KEY",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
            search_query="cats",
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_keys

    def test_full_refresh_sort_mode_default_ascending(self) -> None:
        response = giphy_source(
            api_key="KEY",
            endpoint="gifs_trending",
            logger=MagicMock(),
            resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
        )
        assert response.sort_mode == "asc"


class TestFetchPageErrorHandling:
    def test_client_error_does_not_leak_api_key(self) -> None:
        # The api_key rides in the query string, so raise_for_status() would put it in
        # the exception message, which lands in the schema's latest_error.
        api_key = "super-secret-key"
        response = MagicMock()
        response.status_code = 400
        response.ok = False
        response.reason = "Bad Request"
        response.text = "invalid request"
        response.url = f"https://api.giphy.com/v1/gifs/search?api_key={api_key}&q=cats"

        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError) as exc_info:
            _fetch_page(session, response.url, MagicMock())

        assert api_key not in str(exc_info.value)
        assert "api.giphy.com/v1/gifs/search" in str(exc_info.value)


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code, expected", [(200, True), (401, False), (403, False), (500, False)])
    def test_status_maps_to_validity(self, monkeypatch: Any, status_code: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status_code)
        monkeypatch.setattr(giphy, "_get_session", lambda *_: session)
        assert giphy.validate_credentials("KEY") is expected

    def test_network_error_is_invalid(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        monkeypatch.setattr(giphy, "_get_session", lambda *_: session)
        assert giphy.validate_credentials("KEY") is False


class TestSessionRedaction:
    def test_api_key_registered_for_redaction(self, monkeypatch: Any) -> None:
        # The key travels in the query string, so it must be passed to make_tracked_session as a
        # redacted value — otherwise it leaks into tracked URLs/samples.
        captured: dict[str, Any] = {}

        def fake_make_session(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr(giphy, "make_tracked_session", fake_make_session)
        giphy._get_session("super-secret-key")
        assert captured["redact_values"] == ("super-secret-key",)
