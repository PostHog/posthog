from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.beamer import beamer
from products.warehouse_sources.backend.temporal.data_imports.sources.beamer.beamer import (
    BeamerResumeConfig,
    _build_url,
    _format_datetime,
    beamer_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.beamer.settings import BEAMER_ENDPOINTS


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        ]
    )
    def test_format_datetime(self, _name: str, value: object, expected: str) -> None:
        assert _format_datetime(value) == expected

    def test_no_plus_zero_offset(self) -> None:
        assert "+00:00" not in _format_datetime(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))


class TestBuildUrl:
    def test_drops_none_params(self) -> None:
        url = _build_url("/posts", {"maxResults": 10, "page": 1, "dateFrom": None})
        assert url == "https://api.getbeamer.com/v0/posts?maxResults=10&page=1"

    def test_no_params_has_no_query_string(self) -> None:
        assert _build_url("/posts", {}) == "https://api.getbeamer.com/v0/posts"


class TestValidateCredentials:
    @parameterized.expand(
        [
            # 200 = good key, 403 = real key missing the optional 'Read posts' permission — both valid.
            ("ok", 200, True, None),
            ("forbidden_is_valid_key", 403, True, None),
            ("unauthorized_is_invalid", 401, False, "Invalid Beamer API key"),
            # A 5xx is inconclusive — never reported as an invalid key (would prompt a needless rotation).
            ("server_error_is_inconclusive", 500, False, "could not validate"),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_ok: bool, expected_msg: str | None) -> None:
        response = MagicMock()
        response.status_code = status_code
        session = MagicMock()
        session.get.return_value = response
        with patch.object(beamer, "make_tracked_session", return_value=session):
            ok, message = validate_credentials("key")
        assert ok is expected_ok
        if expected_msg is None:
            assert message is None
        else:
            assert message is not None and expected_msg in message

    def test_network_error_is_inconclusive_not_invalid(self) -> None:
        # A transport failure must not be reported as an invalid key.
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError()
        with patch.object(beamer, "make_tracked_session", return_value=session):
            ok, message = validate_credentials("key")
        assert ok is False
        assert message is not None and "Could not reach Beamer" in message


class _FakeResumableManager:
    def __init__(self, state: BeamerResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[BeamerResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> BeamerResumeConfig | None:
        return self._state

    def save_state(self, data: BeamerResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    monkeypatch: Any,
    endpoint: str,
    pages: dict[str, Any],
    manager: _FakeResumableManager | None = None,
    **kwargs: Any,
) -> tuple[list[dict], list[str]]:
    """Run get_rows against a fake page map keyed by URL, returning (rows, fetched_urls)."""
    fetched: list[str] = []

    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> Any:
        fetched.append(url)
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(beamer, "_fetch_page", fake_fetch)
    monkeypatch.setattr(beamer, "make_tracked_session", lambda *args, **kwargs: MagicMock())

    rows: list[dict] = []
    for table in get_rows(
        api_key="key",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager or _FakeResumableManager(),  # type: ignore[arg-type]
        **kwargs,
    ):
        rows.extend(table.to_pylist())
    return rows, fetched


class TestTopLevelPagination:
    def test_paginates_until_short_page(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.getbeamer.com/v0/posts?maxResults=10&page=1": [
                {"id": i, "date": "2026-01-01"} for i in range(10)
            ],
            "https://api.getbeamer.com/v0/posts?maxResults=10&page=2": [{"id": 10, "date": "2026-01-02"}],
        }
        rows, fetched = _collect(monkeypatch, "posts", pages)
        assert [r["id"] for r in rows] == list(range(11))
        # Stops after the short second page; never requests page 3.
        assert fetched == [
            "https://api.getbeamer.com/v0/posts?maxResults=10&page=1",
            "https://api.getbeamer.com/v0/posts?maxResults=10&page=2",
        ]

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        pages: dict[str, list[dict[str, Any]]] = {"https://api.getbeamer.com/v0/posts?maxResults=10&page=1": []}
        rows, fetched = _collect(monkeypatch, "posts", pages)
        assert rows == []

    def test_incremental_adds_datefrom(self, monkeypatch: Any) -> None:
        url = "https://api.getbeamer.com/v0/posts?maxResults=10&dateFrom=2026-03-04T02%3A58%3A14Z&page=1"
        pages = {url: [{"id": 1, "date": "2026-03-05"}]}
        rows, fetched = _collect(
            monkeypatch,
            "posts",
            pages,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="date",
        )
        assert rows == [{"id": 1, "date": "2026-03-05"}]
        assert "dateFrom=2026-03-04T02%3A58%3A14Z" in fetched[0]

    def test_nps_uses_larger_page_size(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.getbeamer.com/v0/nps?maxResults=100&page=1": [{"id": 1, "date": "2026-01-01", "score": 9}]
        }
        rows, fetched = _collect(monkeypatch, "nps", pages)
        assert rows[0]["score"] == 9
        assert "maxResults=100" in fetched[0]

    def test_resume_starts_from_saved_page(self, monkeypatch: Any) -> None:
        pages = {"https://api.getbeamer.com/v0/posts?maxResults=10&page=3": [{"id": 99, "date": "2026-01-01"}]}
        manager = _FakeResumableManager(BeamerResumeConfig(page=3, parent_id=None))
        rows, fetched = _collect(monkeypatch, "posts", pages, manager=manager)
        assert rows == [{"id": 99, "date": "2026-01-01"}]
        assert fetched == ["https://api.getbeamer.com/v0/posts?maxResults=10&page=3"]

    def test_mid_page_yield_checkpoints_current_page_not_next(self, monkeypatch: Any) -> None:
        # Force a flush on every item (chunk_size=1) so we can observe the per-item checkpoint. A
        # mid-page flush must save the current page, not page+1 — saving page+1 mid-page would skip
        # the page's un-batched tail on a crash. Only the page's final item advances the checkpoint.
        monkeypatch.setattr(beamer, "Batcher", lambda **kwargs: Batcher(logger=MagicMock(), chunk_size=1))
        pages = {
            "https://api.getbeamer.com/v0/posts?maxResults=10&page=1": [
                {"id": i, "date": "2026-01-01"} for i in range(10)
            ],
            "https://api.getbeamer.com/v0/posts?maxResults=10&page=2": [{"id": 10, "date": "2026-01-02"}],
        }
        manager = _FakeResumableManager()
        _collect(monkeypatch, "posts", pages, manager=manager)
        saved_pages = [state.page for state in manager.saved]
        # Page 1 is full: its first nine items checkpoint page 1, its last item advances to page 2.
        # Page 2 is short (no further pages): its lone item checkpoints page 2, never page 3.
        assert saved_pages == [1] * 9 + [2, 2]


class TestFanOut:
    def _post_pages(self, extra: dict[str, Any]) -> dict[str, Any]:
        pages = {
            "https://api.getbeamer.com/v0/posts?maxResults=10&page=1": [{"id": "P1"}, {"id": "P2"}],
        }
        pages.update(extra)
        return pages

    def test_injects_parent_id_into_child_rows(self, monkeypatch: Any) -> None:
        pages = self._post_pages(
            {
                "https://api.getbeamer.com/v0/posts/P1/comments?maxResults=10&page=1": [
                    {"id": "C1", "date": "2026-01-01", "text": "hi"}
                ],
                "https://api.getbeamer.com/v0/posts/P2/comments?maxResults=10&page=1": [
                    {"id": "C2", "date": "2026-01-02", "text": "yo"}
                ],
            }
        )
        rows, _ = _collect(monkeypatch, "post_comments", pages)
        assert rows == [
            {"id": "C1", "date": "2026-01-01", "text": "hi", "post_id": "P1"},
            {"id": "C2", "date": "2026-01-02", "text": "yo", "post_id": "P2"},
        ]

    def test_feature_request_votes_inject_feature_request_id(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.getbeamer.com/v0/requests?maxResults=10&page=1": [{"id": "R1"}],
            "https://api.getbeamer.com/v0/requests/R1/votes?maxResults=10&page=1": [{"id": "V1", "date": "2026-01-01"}],
        }
        rows, _ = _collect(monkeypatch, "feature_request_votes", pages)
        assert rows == [{"id": "V1", "date": "2026-01-01", "feature_request_id": "R1"}]

    def test_deleted_parent_404_is_skipped(self, monkeypatch: Any) -> None:
        not_found = requests.HTTPError(response=MagicMock(status_code=404))
        pages = self._post_pages(
            {
                "https://api.getbeamer.com/v0/posts/P1/comments?maxResults=10&page=1": not_found,
                "https://api.getbeamer.com/v0/posts/P2/comments?maxResults=10&page=1": [
                    {"id": "C2", "date": "2026-01-02"}
                ],
            }
        )
        rows, _ = _collect(monkeypatch, "post_comments", pages)
        assert rows == [{"id": "C2", "date": "2026-01-02", "post_id": "P2"}]

    def test_non_404_error_propagates(self, monkeypatch: Any) -> None:
        server_error = requests.HTTPError(response=MagicMock(status_code=500))
        pages = self._post_pages({"https://api.getbeamer.com/v0/posts/P1/comments?maxResults=10&page=1": server_error})
        with pytest.raises(requests.HTTPError):
            _collect(monkeypatch, "post_comments", pages)

    def test_resume_from_bookmarked_parent(self, monkeypatch: Any) -> None:
        # Bookmarked at P2 — P1 is skipped, P2 resumed at page 2.
        pages = self._post_pages(
            {
                "https://api.getbeamer.com/v0/posts/P2/comments?maxResults=10&page=2": [
                    {"id": "C9", "date": "2026-01-09"}
                ],
            }
        )
        manager = _FakeResumableManager(BeamerResumeConfig(page=2, parent_id="P2"))
        rows, fetched = _collect(monkeypatch, "post_comments", pages, manager=manager)
        assert rows == [{"id": "C9", "date": "2026-01-09", "post_id": "P2"}]
        assert "https://api.getbeamer.com/v0/posts/P1/comments?maxResults=10&page=1" not in fetched


class TestBeamerSourceResponse:
    @parameterized.expand(
        [
            ("posts", ["id"], "date", "desc"),
            ("feature_requests", ["id"], "date", "desc"),
            ("nps", ["id"], "date", "desc"),
            ("users", ["beamerId"], "firstSeen", "asc"),
            ("post_comments", ["post_id", "id"], "date", "asc"),
            ("feature_request_votes", ["feature_request_id", "id"], "date", "asc"),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str], partition_key: str, sort_mode: str
    ) -> None:
        response = beamer_source(
            api_key="key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == sort_mode

    def test_incremental_endpoints_sort_desc(self) -> None:
        # Endpoints with a server-side dateFrom filter must use "desc" so the watermark is only
        # persisted at the end of a successful sync (we can't verify the API's default sort order).
        for name, config in BEAMER_ENDPOINTS.items():
            response = beamer_source(
                api_key="key", endpoint=name, logger=MagicMock(), resumable_source_manager=MagicMock()
            )
            expected = "desc" if config.supports_incremental else "asc"
            assert response.sort_mode == expected, name
