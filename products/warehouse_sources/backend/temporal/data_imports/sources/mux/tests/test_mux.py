from typing import Any

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.mux import mux
from products.warehouse_sources.backend.temporal.data_imports.sources.mux.mux import (
    MuxResumeConfig,
    _normalize_row,
    _strip_sensitive_fields,
    get_rows,
    get_validation_status,
    mux_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mux.settings import MUX_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: MuxResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[MuxResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> MuxResumeConfig | None:
        return self._state

    def save_state(self, data: MuxResumeConfig) -> None:
        self.saved.append(data)


def _collect(
    manager: _FakeResumableManager, monkeypatch: Any, endpoint: str, pages: dict[str, Any]
) -> tuple[list[dict], list[str]]:
    """Drive get_rows against a URL->response map, returning (rows, fetched_urls)."""
    fetched_urls: list[str] = []

    def fake_fetch(session: Any, url: str, logger: Any) -> dict:
        fetched_urls.append(url)
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(mux, "_fetch_page", fake_fetch)
    monkeypatch.setattr(mux, "_make_session", lambda *a, **k: MagicMock())

    rows: list[dict] = []
    for table in get_rows(
        access_token_id="id",
        secret_key="secret",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(table.to_pylist())
    return rows, fetched_urls


class TestNormalizeRow:
    @parameterized.expand(
        [
            ("digit_string_to_int", "assets", {"id": "a", "created_at": "1609869152"}, 1609869152),
            ("already_int_unchanged", "assets", {"id": "a", "created_at": 1609869152}, 1609869152),
            ("non_digit_string_unchanged", "assets", {"id": "a", "created_at": "not-a-ts"}, "not-a-ts"),
        ]
    )
    def test_created_at_coercion(self, _name: str, endpoint: str, item: dict, expected: Any) -> None:
        result = _normalize_row(item, MUX_ENDPOINTS[endpoint])
        assert result["created_at"] == expected

    def test_endpoint_without_partition_key_is_untouched(self) -> None:
        # Uploads have no created_at partition key, so the row passes through verbatim.
        item = {"id": "u1", "status": "waiting"}
        assert _normalize_row(item, MUX_ENDPOINTS["uploads"]) == item

    def test_missing_created_at_is_untouched(self) -> None:
        item = {"id": "a1"}
        assert _normalize_row(item, MUX_ENDPOINTS["assets"]) == item


class TestStripSensitiveFields:
    def test_live_stream_stream_key_is_dropped(self) -> None:
        item = {"id": "ls1", "created_at": "1", "stream_key": "super-secret", "status": "idle"}
        cleaned = _strip_sensitive_fields(item, MUX_ENDPOINTS["live_streams"])
        assert "stream_key" not in cleaned
        assert cleaned == {"id": "ls1", "created_at": "1", "status": "idle"}

    def test_live_stream_simulcast_target_stream_keys_are_dropped(self) -> None:
        item = {
            "id": "ls1",
            "simulcast_targets": [
                {"id": "t1", "url": "rtmp://example", "stream_key": "secret", "status": "idle"},
            ],
        }
        cleaned = _strip_sensitive_fields(item, MUX_ENDPOINTS["live_streams"])
        assert cleaned["simulcast_targets"] == [{"id": "t1", "url": "rtmp://example", "status": "idle"}]

    def test_upload_url_is_dropped(self) -> None:
        item = {"id": "u1", "url": "https://storage.googleapis.com/upload?signature=secret", "status": "waiting"}
        cleaned = _strip_sensitive_fields(item, MUX_ENDPOINTS["uploads"])
        assert "url" not in cleaned
        assert cleaned == {"id": "u1", "status": "waiting"}

    def test_endpoint_without_sensitive_fields_is_untouched(self) -> None:
        item = {"id": "a1", "status": "ready"}
        assert _strip_sensitive_fields(item, MUX_ENDPOINTS["assets"]) is item

    def test_get_rows_never_yields_stripped_fields(self, monkeypatch: Any) -> None:
        # End-to-end guard: a secret present in the API response must not survive into batched rows.
        pages = {
            "https://api.mux.com/video/v1/live-streams?limit=100&page=1": {
                "data": [{"id": "ls1", "created_at": "1609869152", "stream_key": "leak"}],
            },
        }
        rows, _ = _collect(_FakeResumableManager(), monkeypatch, "live_streams", pages)
        assert rows == [{"id": "ls1", "created_at": 1609869152}]
        assert all("stream_key" not in row for row in rows)


class TestGetValidationStatus:
    def test_returns_status_code(self, monkeypatch: Any) -> None:
        for status_code in (200, 401, 403):
            session = MagicMock()
            session.get.return_value = MagicMock(status_code=status_code)
            monkeypatch.setattr(mux, "_make_session", lambda *a, _s=session, **k: _s)
            assert get_validation_status("id", "secret", "/video/v1/assets") == status_code

    def test_transport_error_returns_none(self, monkeypatch: Any) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        monkeypatch.setattr(mux, "_make_session", lambda *a, **k: session)
        assert get_validation_status("id", "secret", "/video/v1/assets") is None


class TestOffsetPagination:
    def test_walks_pages_until_short_page(self, monkeypatch: Any) -> None:
        # live_streams uses offset pagination with page_size 100; a page shorter than the limit ends it.
        pages = {
            "https://api.mux.com/video/v1/live-streams?limit=100&page=1": {
                "data": [{"id": str(i), "created_at": "1609869152"} for i in range(100)],
            },
            "https://api.mux.com/video/v1/live-streams?limit=100&page=2": {
                "data": [{"id": "100", "created_at": "1609869152"}],
            },
        }
        rows, fetched = _collect(_FakeResumableManager(), monkeypatch, "live_streams", pages)
        assert len(rows) == 101
        assert fetched == [
            "https://api.mux.com/video/v1/live-streams?limit=100&page=1",
            "https://api.mux.com/video/v1/live-streams?limit=100&page=2",
        ]
        # created_at coerced to int for partitioning.
        assert rows[0]["created_at"] == 1609869152

    def test_empty_first_page_yields_nothing(self, monkeypatch: Any) -> None:
        pages: dict[str, Any] = {"https://api.mux.com/video/v1/live-streams?limit=100&page=1": {"data": []}}
        rows, fetched = _collect(_FakeResumableManager(), monkeypatch, "live_streams", pages)
        assert rows == []
        assert fetched == ["https://api.mux.com/video/v1/live-streams?limit=100&page=1"]

    def test_full_final_page_triggers_one_more_empty_fetch(self, monkeypatch: Any) -> None:
        # An exact-multiple final page can't be distinguished from a full page, so we fetch once more.
        pages = {
            "https://api.mux.com/video/v1/live-streams?limit=100&page=1": {
                "data": [{"id": str(i), "created_at": "1609869152"} for i in range(100)],
            },
            "https://api.mux.com/video/v1/live-streams?limit=100&page=2": {"data": []},
        }
        rows, fetched = _collect(_FakeResumableManager(), monkeypatch, "live_streams", pages)
        assert len(rows) == 100
        assert len(fetched) == 2

    def test_resume_from_saved_page(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.mux.com/video/v1/live-streams?limit=100&page=3": {
                "data": [{"id": "x", "created_at": "1609869152"}],
            },
        }
        manager = _FakeResumableManager(MuxResumeConfig(page=3))
        rows, fetched = _collect(manager, monkeypatch, "live_streams", pages)
        assert rows == [{"id": "x", "created_at": 1609869152}]
        assert fetched == ["https://api.mux.com/video/v1/live-streams?limit=100&page=3"]

    def test_saves_next_page_after_yielding_a_batch(self, monkeypatch: Any) -> None:
        # The batcher only emits a table once it crosses its 2000-row threshold; the next-page bookmark
        # is saved right after that emission so a crash re-yields rather than skips the batch.
        manager = _FakeResumableManager()
        pages = {
            "https://api.mux.com/video/v1/live-streams?limit=100&page=1": {
                "data": [{"id": str(i), "created_at": "1609869152"} for i in range(2000)],
            },
            "https://api.mux.com/video/v1/live-streams?limit=100&page=2": {
                "data": [{"id": "last", "created_at": "1609869152"}],
            },
        }
        rows, _ = _collect(manager, monkeypatch, "live_streams", pages)
        assert len(rows) == 2001
        assert MuxResumeConfig(page=2) in manager.saved


class TestCursorPagination:
    def test_assets_walk_via_next_cursor(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.mux.com/video/v1/assets?limit=100": {
                "data": [{"id": "a1", "created_at": "1609869152"}],
                "next_cursor": "CURSOR2",
            },
            "https://api.mux.com/video/v1/assets?limit=100&cursor=CURSOR2": {
                "data": [{"id": "a2", "created_at": "1609869152"}],
                "next_cursor": None,
            },
        }
        rows, fetched = _collect(_FakeResumableManager(), monkeypatch, "assets", pages)
        assert [r["id"] for r in rows] == ["a1", "a2"]
        assert fetched == [
            "https://api.mux.com/video/v1/assets?limit=100",
            "https://api.mux.com/video/v1/assets?limit=100&cursor=CURSOR2",
        ]

    def test_assets_stop_when_next_cursor_null(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.mux.com/video/v1/assets?limit=100": {
                "data": [{"id": "a1", "created_at": "1609869152"}],
                "next_cursor": None,
            },
        }
        rows, fetched = _collect(_FakeResumableManager(), monkeypatch, "assets", pages)
        assert [r["id"] for r in rows] == ["a1"]
        assert len(fetched) == 1

    def test_assets_resume_from_saved_cursor(self, monkeypatch: Any) -> None:
        pages = {
            "https://api.mux.com/video/v1/assets?limit=100&cursor=SAVED": {
                "data": [{"id": "a9", "created_at": "1609869152"}],
                "next_cursor": None,
            },
        }
        manager = _FakeResumableManager(MuxResumeConfig(cursor="SAVED"))
        rows, fetched = _collect(manager, monkeypatch, "assets", pages)
        assert [r["id"] for r in rows] == ["a9"]
        assert fetched == ["https://api.mux.com/video/v1/assets?limit=100&cursor=SAVED"]

    def test_assets_save_cursor_after_yielding_a_batch(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        pages = {
            "https://api.mux.com/video/v1/assets?limit=100": {
                "data": [{"id": str(i), "created_at": "1609869152"} for i in range(2000)],
                "next_cursor": "NEXT",
            },
            "https://api.mux.com/video/v1/assets?limit=100&cursor=NEXT": {
                "data": [{"id": "last", "created_at": "1609869152"}],
                "next_cursor": None,
            },
        }
        rows, _ = _collect(manager, monkeypatch, "assets", pages)
        assert len(rows) == 2001
        assert MuxResumeConfig(cursor="NEXT") in manager.saved


class TestRetryableError:
    # Call the undecorated function so the test isn't slowed by tenacity's retry/backoff. tenacity
    # exposes the original via __wrapped__ (functools.wraps), which the type stub doesn't model.
    _fetch_once = staticmethod(mux._fetch_page.__wrapped__)  # type: ignore[attr-defined]

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status_code: int) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=status_code, ok=False)
        with pytest.raises(mux.MuxRetryableError):
            self._fetch_once(session, "https://api.mux.com/video/v1/assets", MagicMock())

    def test_client_error_raises_for_status(self) -> None:
        response = MagicMock(status_code=403, ok=False)
        response.raise_for_status.side_effect = requests.HTTPError("403", response=MagicMock())
        session = MagicMock()
        session.get.return_value = response
        with pytest.raises(requests.HTTPError):
            self._fetch_once(session, "https://api.mux.com/video/v1/assets", MagicMock())


class TestMuxSourceResponse:
    def test_partitioned_endpoint_sets_datetime_partitioning(self) -> None:
        response = mux_source("id", "secret", "assets", MagicMock(), MagicMock())
        assert response.name == "assets"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        assert response.partition_format == "month"

    def test_unpartitioned_endpoint_has_no_partitioning(self) -> None:
        response = mux_source("id", "secret", "uploads", MagicMock(), MagicMock())
        assert response.name == "uploads"
        assert response.partition_mode is None
        assert response.partition_keys is None
