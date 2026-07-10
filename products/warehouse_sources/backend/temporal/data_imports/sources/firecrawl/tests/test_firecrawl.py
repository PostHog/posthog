from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl import firecrawl
from products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl.firecrawl import (
    FirecrawlResumeConfig,
    firecrawl_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.firecrawl.settings import FIRECRAWL_ENDPOINTS


class _FakeResumableManager:
    def __init__(self, state: FirecrawlResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[FirecrawlResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> FirecrawlResumeConfig | None:
        return self._state

    def save_state(self, data: FirecrawlResumeConfig) -> None:
        self.saved.append(data)


def _collect(manager: _FakeResumableManager, endpoint: str) -> list[dict]:
    rows: list[dict] = []
    for page in get_rows(
        api_key="fc-test",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(page)
    return rows


def _make_response(status_code: int, *, ok: bool | None = None, body: Any = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = ok if ok is not None else status_code < 400
    response.json.return_value = body if body is not None else {}
    response.text = ""
    return response


class TestFetchRetryClassification:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_retryable_statuses_raise_and_retry(self, _name: str, status_code: int) -> None:
        # 429 (plan rate/concurrency limit) and 5xx must retry rather than fail the sync outright.
        session = MagicMock()
        session.get.side_effect = [_make_response(status_code), _make_response(200, body={"data": []})]

        with patch.object(firecrawl._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = firecrawl._fetch(session, "https://api.firecrawl.dev/v2/team/activity", {}, None, MagicMock())

        assert result == {"data": []}
        assert session.get.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_immediately(self, _name: str, status_code: int) -> None:
        # A 4xx credential/permission error can never be fixed by retrying, so it must surface at once.
        response = _make_response(status_code)
        response.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Client Error")
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            firecrawl._fetch(session, "https://api.firecrawl.dev/v2/team/activity", {}, None, MagicMock())
        assert session.get.call_count == 1

    @parameterized.expand(
        [
            ("chunked", requests.exceptions.ChunkedEncodingError("Connection broken")),
            ("read_timeout", requests.ReadTimeout("Read timed out.")),
            ("connection", requests.ConnectionError("Connection reset by peer")),
        ]
    )
    def test_transient_network_errors_are_retried(self, _name: str, transient: Exception) -> None:
        session = MagicMock()
        session.get.side_effect = [transient, _make_response(200, body={"data": []})]

        with patch.object(firecrawl._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = firecrawl._fetch(session, "https://api.firecrawl.dev/v2/team/activity", {}, None, MagicMock())

        assert result == {"data": []}
        assert session.get.call_count == 2

    def test_transient_error_reraised_after_five_attempts(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ReadTimeout("Read timed out.")

        with patch.object(firecrawl._fetch.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(requests.ReadTimeout):
                firecrawl._fetch(session, "https://api.firecrawl.dev/v2/team/activity", {}, None, MagicMock())
        assert session.get.call_count == 5


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("server_error", 500, False)])
    def test_status_maps_to_bool(self, _name: str, status_code: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = _make_response(status_code)
        with patch.object(firecrawl, "make_tracked_session", return_value=session):
            assert validate_credentials("fc-test") is expected

    def test_network_failure_is_false(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(firecrawl, "make_tracked_session", return_value=session):
            assert validate_credentials("fc-test") is False


class TestCursorPagination:
    def _patch_fetch(self, monkeypatch: Any, pages_by_cursor: dict[Any, dict]) -> list[Any]:
        seen_cursors: list[Any] = []

        def fake_fetch(session: Any, url: str, headers: Any, params: Any, logger: Any) -> dict:
            cursor = params.get("cursor") if params else None
            seen_cursors.append(cursor)
            return pages_by_cursor[cursor]

        monkeypatch.setattr(firecrawl, "_fetch", fake_fetch)
        return seen_cursors

    def test_follows_cursor_until_has_more_false(self, monkeypatch: Any) -> None:
        pages = {
            None: {"data": [{"id": "a"}], "cursor": "c1", "has_more": True},
            "c1": {"data": [{"id": "b"}], "cursor": "c2", "has_more": True},
            "c2": {"data": [{"id": "c"}], "cursor": None, "has_more": False},
        }
        seen = self._patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()

        rows = _collect(manager, "team_activity")

        assert [r["id"] for r in rows] == ["a", "b", "c"]
        assert seen == [None, "c1", "c2"]
        # State is saved only for the pages that had a next cursor, and points at the NEXT page.
        assert [s.cursor for s in manager.saved] == ["c1", "c2"]

    def test_resumes_from_saved_cursor(self, monkeypatch: Any) -> None:
        pages = {
            "c1": {"data": [{"id": "b"}], "cursor": None, "has_more": False},
        }
        seen = self._patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager(FirecrawlResumeConfig(cursor="c1"))

        rows = _collect(manager, "team_activity")

        assert [r["id"] for r in rows] == ["b"]
        assert seen == ["c1"]  # never re-fetched the already-processed first page

    def test_stops_when_cursor_missing_even_if_has_more_true(self, monkeypatch: Any) -> None:
        # Guard against an infinite loop if the API ever returns has_more=true with a null cursor.
        pages = {None: {"data": [{"id": "a"}], "cursor": None, "has_more": True}}
        self._patch_fetch(monkeypatch, pages)
        rows = _collect(_FakeResumableManager(), "team_activity")
        assert [r["id"] for r in rows] == ["a"]


class TestOffsetPagination:
    def _patch_fetch(self, monkeypatch: Any, pages_by_offset: dict[int, list[dict]]) -> list[int]:
        seen_offsets: list[int] = []

        def fake_fetch(session: Any, url: str, headers: Any, params: Any, logger: Any) -> dict:
            offset = params["offset"]
            seen_offsets.append(offset)
            return {"data": pages_by_offset.get(offset, [])}

        monkeypatch.setattr(firecrawl, "_fetch", fake_fetch)
        return seen_offsets

    def test_pages_until_short_page(self, monkeypatch: Any) -> None:
        full_page = [{"id": str(i)} for i in range(firecrawl.PAGE_SIZE)]
        pages = {0: full_page, firecrawl.PAGE_SIZE: [{"id": "last"}]}
        seen = self._patch_fetch(monkeypatch, pages)
        manager = _FakeResumableManager()

        rows = _collect(manager, "monitors")

        assert len(rows) == firecrawl.PAGE_SIZE + 1
        assert seen == [0, firecrawl.PAGE_SIZE]  # stopped after the short second page
        assert [s.offset for s in manager.saved] == [firecrawl.PAGE_SIZE]

    def test_single_short_page_does_not_advance(self, monkeypatch: Any) -> None:
        seen = self._patch_fetch(monkeypatch, {0: [{"id": "x"}]})
        manager = _FakeResumableManager()
        rows = _collect(manager, "monitors")
        assert [r["id"] for r in rows] == ["x"]
        assert seen == [0]
        assert manager.saved == []


class TestUnpaginated:
    @pytest.mark.parametrize(
        "endpoint,selector",
        [
            ("credit_usage_historical", "periods"),
            ("token_usage_historical", "periods"),
            ("active_crawls", "crawls"),
        ],
    )
    def test_single_request_reads_the_endpoint_selector(self, endpoint: str, selector: str, monkeypatch: Any) -> None:
        calls: list[str] = []

        def fake_fetch(session: Any, url: str, headers: Any, params: Any, logger: Any) -> dict:
            calls.append(url)
            return {selector: [{"id": "1"}, {"id": "2"}]}

        monkeypatch.setattr(firecrawl, "_fetch", fake_fetch)
        rows = _collect(_FakeResumableManager(), endpoint)
        assert rows == [{"id": "1"}, {"id": "2"}]
        assert len(calls) == 1  # unpaginated: exactly one request


class TestMonitorChecksFanOut:
    def test_config_is_opt_in_fan_out(self) -> None:
        cfg = FIRECRAWL_ENDPOINTS["monitor_checks"]
        assert cfg.fan_out_over_monitors is True
        assert cfg.should_sync_default is False
        assert "{monitor_id}" in cfg.path

    def test_fans_out_over_every_monitor(self, monkeypatch: Any) -> None:
        def fake_fetch(session: Any, url: str, headers: Any, params: Any, logger: Any) -> dict:
            if url.endswith("/v2/monitor"):
                return {"data": [{"id": "m1"}, {"id": "m2"}]}
            if "m1" in url:
                return {"data": [{"id": "chk1", "monitorId": "m1"}]}
            if "m2" in url:
                return {"data": [{"id": "chk2", "monitorId": "m2"}]}
            raise AssertionError(f"unexpected url {url}")

        monkeypatch.setattr(firecrawl, "_fetch", fake_fetch)
        rows = _collect(_FakeResumableManager(), "monitor_checks")
        assert rows == [
            {"id": "chk1", "monitorId": "m1"},
            {"id": "chk2", "monitorId": "m2"},
        ]

    def test_resumes_from_saved_monitor(self, monkeypatch: Any) -> None:
        fetched: list[str] = []

        def fake_fetch(session: Any, url: str, headers: Any, params: Any, logger: Any) -> dict:
            fetched.append(url)
            if url.endswith("/v2/monitor"):
                return {"data": [{"id": "m1"}, {"id": "m2"}]}
            return {"data": [{"id": "chk2", "monitorId": "m2"}]}

        monkeypatch.setattr(firecrawl, "_fetch", fake_fetch)
        manager = _FakeResumableManager(FirecrawlResumeConfig(monitor_id="m2", offset=0))
        rows = _collect(manager, "monitor_checks")

        assert rows == [{"id": "chk2", "monitorId": "m2"}]
        # m1's checks are never fetched - we resumed straight to m2.
        assert not any("m1/checks" in url for url in fetched)

    def test_unknown_saved_monitor_restarts_from_first(self, monkeypatch: Any) -> None:
        def fake_fetch(session: Any, url: str, headers: Any, params: Any, logger: Any) -> dict:
            if url.endswith("/v2/monitor"):
                return {"data": [{"id": "m1"}]}
            return {"data": [{"id": "chk1", "monitorId": "m1"}]}

        monkeypatch.setattr(firecrawl, "_fetch", fake_fetch)
        manager = _FakeResumableManager(FirecrawlResumeConfig(monitor_id="DELETED", offset=40))
        rows = _collect(manager, "monitor_checks")
        assert rows == [{"id": "chk1", "monitorId": "m1"}]


class TestSourceResponseShape:
    @parameterized.expand(
        [
            ("team_activity", ["id"], "created_at", "week"),
            ("credit_usage_historical", ["startDate"], None, None),
            ("token_usage_historical", ["startDate"], None, None),
            ("active_crawls", ["id"], None, None),
            ("monitors", ["id"], "createdAt", "week"),
            ("monitor_checks", ["id"], "createdAt", "week"),
        ]
    )
    def test_primary_keys_and_partitioning(
        self, endpoint: str, expected_pk: list[str], partition_key: str | None, partition_format: str | None
    ) -> None:
        # Locks the primary key + a STABLE (creation-time) partition field per endpoint. A non-unique
        # key or an updated_at partition would rewrite partitions every sync and accumulate duplicates.
        response = firecrawl_source(
            api_key="fc-test",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        assert response.sort_mode == "asc"
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
            assert response.partition_format == partition_format
