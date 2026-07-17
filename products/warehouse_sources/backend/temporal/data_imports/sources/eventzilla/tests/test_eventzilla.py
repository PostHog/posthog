from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.eventzilla import eventzilla
from products.warehouse_sources.backend.temporal.data_imports.sources.eventzilla.eventzilla import (
    PAGE_SIZE,
    EventzillaResumeConfig,
    EventzillaRetryableError,
    _build_url,
    _iter_pages,
    eventzilla_source,
    get_rows,
    validate_credentials,
)


def _response_with_status(status_code: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    return response


class _FakeResumableManager:
    def __init__(self, state: EventzillaResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[EventzillaResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> EventzillaResumeConfig | None:
        return self._state

    def save_state(self, data: EventzillaResumeConfig) -> None:
        self.saved.append(data)


def _collect(manager: _FakeResumableManager, monkeypatch: Any, endpoint: str, pages: dict[str, Any]) -> list[dict]:
    def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(eventzilla, "_fetch_page", fake_fetch)

    rows: list[dict] = []
    for table in get_rows(
        api_key="key",
        endpoint=endpoint,
        logger=MagicMock(),
        resumable_source_manager=manager,  # type: ignore[arg-type]
    ):
        rows.extend(table.to_pylist())
    return rows


class TestIterPages:
    def test_stops_on_empty_first_page(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(eventzilla, "_fetch_page", lambda *a, **k: {"events": []})
        assert list(_iter_pages(MagicMock(), "/events", "events", {}, MagicMock())) == []

    def test_single_short_page_without_pagination_stops(self, monkeypatch: Any) -> None:
        # A page shorter than PAGE_SIZE and no `pagination` object means the list is exhausted;
        # a second request (which would return the same rows for a non-paging endpoint) is a bug.
        calls: list[str] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            calls.append(url)
            return {"tickets": [{"id": 1}, {"id": 2}]}

        monkeypatch.setattr(eventzilla, "_fetch_page", fake_fetch)
        pages = list(_iter_pages(MagicMock(), "/events/9/tickets", "tickets", {}, MagicMock()))

        assert [items for items, _ in pages] == [[{"id": 1}, {"id": 2}]]
        assert len(calls) == 1

    def test_pagination_total_terminates_even_on_a_full_page(self, monkeypatch: Any) -> None:
        # When `total` is reached we must stop, even though the page came back full (== PAGE_SIZE),
        # otherwise we'd issue an unnecessary extra request and risk re-reading rows.
        full_page = [{"id": i} for i in range(PAGE_SIZE)]
        fetched: list[str] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            fetched.append(url)
            return {"events": full_page, "pagination": {"offset": 0, "limit": PAGE_SIZE, "total": PAGE_SIZE}}

        monkeypatch.setattr(eventzilla, "_fetch_page", fake_fetch)
        pages = list(_iter_pages(MagicMock(), "/events", "events", {}, MagicMock()))

        assert len(pages) == 1
        assert len(fetched) == 1

    def test_follows_multiple_pages_until_total_reached(self, monkeypatch: Any) -> None:
        responses = [
            {"events": [{"id": i} for i in range(PAGE_SIZE)], "pagination": {"total": PAGE_SIZE + 1}},
            {"events": [{"id": 999}], "pagination": {"total": PAGE_SIZE + 1}},
        ]

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            return responses.pop(0)

        monkeypatch.setattr(eventzilla, "_fetch_page", fake_fetch)
        pages = list(_iter_pages(MagicMock(), "/events", "events", {}, MagicMock()))

        assert [len(items) for items, _ in pages] == [PAGE_SIZE, 1]
        # next_offset advances by the real returned count, not a fixed step.
        assert [next_offset for _, next_offset in pages] == [PAGE_SIZE, PAGE_SIZE + 1]

    def test_offset_advances_by_actual_count_when_server_clamps_page_size(self, monkeypatch: Any) -> None:
        # If the server clamps `limit` below PAGE_SIZE we must advance by rows returned, not PAGE_SIZE,
        # or we'd skip rows. Two clamped-to-20 pages then an empty page.
        responses = [
            {"events": [{"id": i} for i in range(20)], "pagination": {"offset": 0, "limit": 20, "total": 25}},
            {"events": [{"id": i} for i in range(20, 25)], "pagination": {"offset": 20, "limit": 20, "total": 25}},
        ]
        seen_offsets: list[int] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            seen_offsets.append(int(url.split("offset=")[1].split("&")[0]))
            return responses.pop(0)

        monkeypatch.setattr(eventzilla, "_fetch_page", fake_fetch)
        list(_iter_pages(MagicMock(), "/events", "events", {}, MagicMock()))

        assert seen_offsets == [0, 20]


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = _response_with_status(status)
        with patch.object(eventzilla, "make_tracked_session", return_value=session):
            assert validate_credentials("key") is expected

    def test_transport_error_is_false(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(eventzilla, "make_tracked_session", return_value=session):
            assert validate_credentials("key") is False


class TestFetchPageRetries:
    @parameterized.expand(
        [
            ("read_timeout", requests.ReadTimeout("slow")),
            ("connection_error", requests.ConnectionError("down")),
        ]
    )
    def test_transient_errors_are_retried(self, _name: str, transient: Exception) -> None:
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"events": []}
        session = MagicMock()
        session.get.side_effect = [transient, good]

        with patch.object(eventzilla._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = eventzilla._fetch_page(session, "https://www.eventzillaapi.net/api/v2/events", {}, MagicMock())

        assert result == {"events": []}
        assert session.get.call_count == 2

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_5xx_and_429_are_retryable(self, _name: str, status: int) -> None:
        resp = MagicMock()
        resp.status_code = status
        session = MagicMock()
        session.get.return_value = resp

        with patch.object(eventzilla._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            with pytest.raises(EventzillaRetryableError):
                eventzilla._fetch_page(session, "https://www.eventzillaapi.net/api/v2/events", {}, MagicMock())

    def test_4xx_raises_for_status(self) -> None:
        resp = MagicMock()
        resp.status_code = 401
        resp.ok = False
        resp.raise_for_status.side_effect = requests.HTTPError("401", response=_response_with_status(401))
        session = MagicMock()
        session.get.return_value = resp

        with pytest.raises(requests.HTTPError):
            eventzilla._fetch_page(session, "https://www.eventzillaapi.net/api/v2/events", {}, MagicMock())


class TestFanOut:
    def _pages_for_two_events(self) -> dict[str, Any]:
        return {
            _build_url("/events", 0): {"events": [{"id": 1}, {"id": 2}], "pagination": {"total": 2}},
            _build_url("/events/1/attendees", 0): {"attendees": [{"id": "A1"}, {"id": "A2"}]},
            _build_url("/events/2/attendees", 0): {"attendees": [{"id": "A3"}]},
        }

    def test_stamps_event_id_and_aggregates_across_events(self, monkeypatch: Any) -> None:
        rows = _collect(_FakeResumableManager(), monkeypatch, "attendees", self._pages_for_two_events())
        assert rows == [
            {"id": "A1", "event_id": "1"},
            {"id": "A2", "event_id": "1"},
            {"id": "A3", "event_id": "2"},
        ]

    def test_resume_from_saved_event_and_offset(self, monkeypatch: Any) -> None:
        # Resuming into event 2 at offset 0 must skip event 1 entirely, and enumeration always
        # re-walks /events first.
        pages = {
            _build_url("/events", 0): {"events": [{"id": 1}, {"id": 2}], "pagination": {"total": 2}},
            _build_url("/events/2/attendees", 0): {"attendees": [{"id": "A3"}]},
        }
        manager = _FakeResumableManager(EventzillaResumeConfig(offset=0, event_id="2"))
        rows = _collect(manager, monkeypatch, "attendees", pages)
        assert rows == [{"id": "A3", "event_id": "2"}]

    def test_resume_from_deleted_event_restarts_from_first(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager(EventzillaResumeConfig(offset=5, event_id="999"))
        rows = _collect(manager, monkeypatch, "attendees", self._pages_for_two_events())
        assert [r["event_id"] for r in rows] == ["1", "1", "2"]

    def test_event_deleted_mid_fan_out_is_skipped(self, monkeypatch: Any) -> None:
        not_found = requests.HTTPError(response=_response_with_status(404))
        pages = {
            _build_url("/events", 0): {"events": [{"id": 1}, {"id": 2}], "pagination": {"total": 2}},
            _build_url("/events/1/attendees", 0): not_found,
            _build_url("/events/2/attendees", 0): {"attendees": [{"id": "A3"}]},
        }
        rows = _collect(_FakeResumableManager(), monkeypatch, "attendees", pages)
        assert rows == [{"id": "A3", "event_id": "2"}]

    def test_non_404_http_error_propagates(self, monkeypatch: Any) -> None:
        server_error = requests.HTTPError(response=_response_with_status(500))
        pages = {
            _build_url("/events", 0): {"events": [{"id": 1}], "pagination": {"total": 1}},
            _build_url("/events/1/attendees", 0): server_error,
        }
        with pytest.raises(requests.HTTPError):
            _collect(_FakeResumableManager(), monkeypatch, "attendees", pages)


class TestTopLevelResume:
    def test_resume_uses_saved_offset(self, monkeypatch: Any) -> None:
        fetched: list[str] = []

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            fetched.append(url)
            return {"events": []}

        monkeypatch.setattr(eventzilla, "_fetch_page", fake_fetch)
        manager = _FakeResumableManager(EventzillaResumeConfig(offset=40))
        list(
            get_rows(
                api_key="key",
                endpoint="events",
                logger=MagicMock(),
                resumable_source_manager=manager,  # type: ignore[arg-type]
            )
        )
        assert fetched == [_build_url("/events", 40)]


class TestSaveStateAfterYield:
    class _ImmediateBatcher:
        # Yields after every batched item so we can observe save_state timing without 2000+ rows.
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._items: list[dict] = []

        def batch(self, item: dict) -> None:
            self._items.append(item)

        def should_yield(self, include_incomplete_chunk: bool = False) -> bool:
            return bool(self._items)

        def get_table(self) -> Any:
            table = MagicMock()
            table.to_pylist.return_value = list(self._items)
            self._items = []
            return table

    def test_top_level_saves_next_offset_after_each_yield(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(eventzilla, "Batcher", self._ImmediateBatcher)
        pages = {
            _build_url("/events", 0): {"events": [{"id": 1}], "pagination": {"total": 2}},
            _build_url("/events", 1): {"events": [{"id": 2}], "pagination": {"total": 2}},
        }
        manager = _FakeResumableManager()
        _collect(manager, monkeypatch, "events", pages)

        # State is saved AFTER each yielded batch carrying the NEXT offset, so a crash re-reads the
        # last batch rather than skipping it. Top-level saves never carry an event_id.
        assert [s.offset for s in manager.saved] == [1, 2]
        assert all(s.event_id is None for s in manager.saved)


class TestSourceResponse:
    @parameterized.expand(
        [
            ("events", ["id"], None),
            ("categories", ["category"], None),
            ("users", ["id"], None),
            ("attendees", ["event_id", "id"], "transaction_date"),
            ("transactions", ["event_id", "checkout_id"], "transaction_date"),
            ("tickets", ["event_id", "id"], None),
        ]
    )
    def test_primary_keys_and_partitioning(
        self, endpoint: str, primary_keys: list[str], partition_key: str | None
    ) -> None:
        response = eventzilla_source(
            api_key="key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
