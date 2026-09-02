from datetime import date
from typing import Any, Optional

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.transistor.settings import (
    TRANSISTOR_BASE_URL,
    TRANSISTOR_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.transistor.transistor import (
    RequestThrottle,
    TransistorResumeConfig,
    date_windows,
    episode_analytics_rows,
    flatten_resource,
    get_rows,
    list_shows,
    paginate,
    parse_download_date,
    show_analytics_rows,
    transistor_source,
    validate_credentials,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.transistor.transistor"

LOGGER = structlog.get_logger()


def _response(status: int = 200, body: Optional[dict[str, Any]] = None) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status
    response.ok = 200 <= status < 300
    response.json.return_value = body if body is not None else {}
    if not response.ok:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status} Client Error for url: {TRANSISTOR_BASE_URL}", response=requests.Response()
        )
    return response


class _FakeSession(requests.Session):
    def __init__(self, responder) -> None:
        super().__init__()
        self._responder = responder
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: Any, **kwargs: Any) -> Any:
        recorded = dict(kwargs.get("params") or {})
        self.calls.append((str(url), recorded))
        return self._responder(str(url), recorded)


class _FakeResumableManager(ResumableSourceManager[TransistorResumeConfig]):
    def __init__(self, state: TransistorResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[TransistorResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> TransistorResumeConfig | None:
        return self._state

    def save_state(self, data: TransistorResumeConfig) -> None:
        self.saved.append(data)


def _resource(resource_id: str, resource_type: str, attributes: dict[str, Any]) -> dict[str, Any]:
    return {"id": resource_id, "type": resource_type, "attributes": attributes, "relationships": {}}


def _list_body(items: list[dict[str, Any]], current_page: int = 1, total_pages: int = 1) -> dict[str, Any]:
    return {"data": items, "meta": {"currentPage": current_page, "totalPages": total_pages, "totalCount": len(items)}}


def _shows_body() -> dict[str, Any]:
    return _list_body(
        [
            _resource("22", "show", {"title": "Second", "created_at": "2026-07-01T00:00:00Z"}),
            _resource("11", "show", {"title": "First", "created_at": "2026-07-01T00:00:00Z"}),
        ]
    )


def _run(responder, endpoint: str, manager: _FakeResumableManager, **kwargs) -> tuple[list[list[dict]], _FakeSession]:
    session = _FakeSession(responder)
    with mock.patch(f"{MODULE}._make_session", return_value=session):
        batches = list(
            get_rows(
                endpoint=endpoint,
                api_key="key",
                logger=LOGGER,
                resumable_source_manager=manager,
                **kwargs,
            )
        )
    return batches, session


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    monkeypatch.setattr(f"{MODULE}.MIN_REQUEST_INTERVAL_SECONDS", 0)


class TestTransistorTransport:
    def test_flatten_resource_hoists_attributes_and_relationships(self):
        row = flatten_resource(
            {
                "id": "3056098",
                "type": "episode",
                "attributes": {"title": "How To Roast Coffee", "id": "attribute-id-should-lose"},
                "relationships": {
                    "show": {"data": {"id": "132543", "type": "show"}},
                    "playlists": {"data": [{"id": "1"}, {"id": "2"}]},
                    "broken": "not-a-dict",
                },
            }
        )

        # Attributes land at the row root so columns are queryable without unnesting, and the
        # JSON:API envelope id wins over any same-named attribute.
        assert row["title"] == "How To Roast Coffee"
        assert row["id"] == "3056098"
        assert row["type"] == "episode"
        assert row["show_id"] == "132543"
        assert row["playlists_ids"] == ["1", "2"]
        assert "broken" not in row

    def test_flatten_resource_tolerates_missing_sections(self):
        assert flatten_resource({"id": "1", "type": "show"}) == {"id": "1", "type": "show"}

    @pytest.mark.parametrize(
        "raw, expected",
        [
            # The documented parameter format is dd-mm-yyyy and wins when ambiguous.
            ("18-07-2026", date(2026, 7, 18)),
            ("07-08-2026", date(2026, 8, 7)),
            # Response samples are inconsistent, so ISO and mm-dd-yyyy are accepted as fallbacks.
            ("2026-07-18", date(2026, 7, 18)),
            ("07-18-2026", date(2026, 7, 18)),
            (" 18-07-2026 ", date(2026, 7, 18)),
            ("not-a-date", None),
            ("", None),
            (None, None),
            (20260718, None),
        ],
    )
    def test_parse_download_date(self, raw, expected):
        assert parse_download_date(raw) == expected

    @pytest.mark.parametrize(
        "start, end, window_days, expected",
        [
            (date(2026, 1, 1), date(2026, 1, 1), 5, [(date(2026, 1, 1), date(2026, 1, 1))]),
            (date(2026, 1, 1), date(2026, 1, 5), 5, [(date(2026, 1, 1), date(2026, 1, 5))]),
            (
                date(2026, 1, 1),
                date(2026, 1, 7),
                5,
                [(date(2026, 1, 1), date(2026, 1, 5)), (date(2026, 1, 6), date(2026, 1, 7))],
            ),
            # An end before the start yields nothing rather than looping.
            (date(2026, 1, 5), date(2026, 1, 1), 5, []),
        ],
    )
    def test_date_windows_are_contiguous_and_bounded(self, start, end, window_days, expected):
        assert list(date_windows(start, end, window_days)) == expected

    def test_paginate_follows_meta_and_stops_at_the_last_page(self):
        pages = {
            1: _list_body([_resource("1", "show", {})], current_page=1, total_pages=3),
            2: _list_body([_resource("2", "show", {})], current_page=2, total_pages=3),
            3: _list_body([_resource("3", "show", {})], current_page=3, total_pages=3),
        }

        def responder(url, params):
            return _response(200, pages[params.get("pagination[page]", 1)])

        session = _FakeSession(responder)
        results = list(paginate(session, RequestThrottle(0), f"{TRANSISTOR_BASE_URL}/shows", {}, LOGGER))

        assert [next_page for _, next_page in results] == [2, 3, None]
        # The first request omits the page param so the API's own base page applies, and later
        # pages come from `currentPage` rather than an assumed base.
        assert "pagination[page]" not in session.calls[0][1]
        assert [call[1].get("pagination[page]") for call in session.calls] == [None, 2, 3]
        assert all(call[1]["pagination[per]"] for call in session.calls)

    def test_paginate_seeds_the_resumed_page(self):
        session = _FakeSession(lambda url, params: _response(200, _list_body([], current_page=4, total_pages=4)))

        list(paginate(session, RequestThrottle(0), f"{TRANSISTOR_BASE_URL}/shows", {}, LOGGER, start_page=4))

        assert session.calls[0][1]["pagination[page]"] == 4

    @pytest.mark.parametrize("row_count, expected_next", [(100, 2), (3, None)])
    def test_paginate_without_meta_walks_only_while_pages_are_full(self, row_count, expected_next):
        body = {"data": [_resource(str(index), "webhook", {}) for index in range(row_count)]}
        session = _FakeSession(lambda url, params: _response(200, body))

        rows, next_page = next(paginate(session, RequestThrottle(0), f"{TRANSISTOR_BASE_URL}/webhooks", {}, LOGGER))

        assert len(rows) == row_count
        assert next_page == expected_next

    def test_paginate_skips_a_404_instead_of_failing(self):
        session = _FakeSession(lambda url, params: _response(404))

        results = list(paginate(session, RequestThrottle(0), f"{TRANSISTOR_BASE_URL}/subscribers", {}, LOGGER))

        assert results == [([], None)]

    def test_list_shows_is_sorted_by_id(self):
        session = _FakeSession(lambda url, params: _response(200, _shows_body()))

        shows = list_shows(session, RequestThrottle(0), LOGGER)

        # Sorted by id, so fan-out resume indexes stay stable even though the endpoint orders
        # by updated date, which reshuffles whenever a show is edited.
        assert [show["id"] for show in shows] == ["11", "22"]

    def test_list_shows_is_capped(self, monkeypatch):
        monkeypatch.setattr(f"{MODULE}.MAX_SHOWS", 1)
        session = _FakeSession(lambda url, params: _response(200, _shows_body()))

        assert len(list_shows(session, RequestThrottle(0), LOGGER)) == 1

    def test_shows_yields_rows_and_checkpoints_each_page(self):
        pages = {
            1: _list_body([_resource("11", "show", {"title": "First"})], current_page=1, total_pages=2),
            2: _list_body([_resource("22", "show", {"title": "Second"})], current_page=2, total_pages=2),
        }
        manager = _FakeResumableManager()

        batches, _ = _run(
            lambda url, params: _response(200, pages[params.get("pagination[page]", 1)]), "shows", manager
        )

        assert [row["title"] for batch in batches for row in batch] == ["First", "Second"]
        # State is only saved while there is a next page to resume to.
        assert [state.page for state in manager.saved] == [2]

    def test_fanout_rows_carry_the_show_id_and_advance_the_checkpoint(self):
        def responder(url, params):
            if url.endswith("/shows"):
                return _response(200, _shows_body())
            return _response(200, _list_body([_resource("709423", "subscriber", {"email": "a@example.com"})]))

        manager = _FakeResumableManager()
        batches, _ = _run(responder, "subscribers", manager)

        rows = [row for batch in batches for row in batch]
        # `show_id` completes the [show_id, id] primary key for a stream fetched per show.
        assert [(row["show_id"], row["id"]) for row in rows] == [("11", "709423"), ("22", "709423")]
        assert [(state.show_index, state.page) for state in manager.saved] == [(1, None), (2, None)]

    def test_fanout_resumes_at_the_saved_show_and_page(self):
        calls: list[tuple[str, dict[str, Any]]] = []

        def responder(url, params):
            calls.append((url, params))
            if url.endswith("/shows"):
                return _response(200, _shows_body())
            return _response(200, _list_body([_resource("1", "episode", {"title": "One"})]))

        manager = _FakeResumableManager(TransistorResumeConfig(show_index=1, page=3))
        batches, _ = _run(responder, "episodes", manager)

        episode_calls = [params for url, params in calls if url.endswith("/episodes")]
        # Only the second show is fetched, and it restarts on the saved page instead of page one.
        assert len(episode_calls) == 1
        assert episode_calls[0]["show_id"] == "22"
        assert episode_calls[0]["pagination[page]"] == 3
        # `order=asc` pins the walk so mid-sync publishes don't shift later pages.
        assert episode_calls[0]["order"] == "asc"
        assert [row["show_id"] for batch in batches for row in batch] == ["22"]

    @freeze_time("2026-08-04")
    @pytest.mark.parametrize(
        "should_use_incremental_field, last_value, expected_start",
        [
            # A first sync reaches back to the show's creation date.
            (False, None, "01-07-2026"),
            # An incremental sync starts at the watermark the pipeline hands over.
            (True, "2026-08-01", "01-08-2026"),
            (True, None, "01-07-2026"),
        ],
    )
    def test_show_analytics_window_start(self, should_use_incremental_field, last_value, expected_start):
        analytics_params: list[dict[str, Any]] = []

        def responder(url, params):
            if url.endswith("/shows"):
                return _response(200, _list_body([_resource("11", "show", {"created_at": "2026-07-01T00:00:00Z"})]))
            analytics_params.append(params)
            return _response(200, {"data": {"attributes": {"downloads": [{"date": "18-07-2026", "downloads": 7}]}}})

        batches, _ = _run(
            responder,
            "show_analytics",
            _FakeResumableManager(),
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )

        assert analytics_params == [{"start_date": expected_start, "end_date": "04-08-2026"}]
        assert batches == [
            [{"show_id": "11", "date": "2026-07-18", "raw_date": "18-07-2026", "downloads": 7}],
        ]

    @freeze_time("2026-08-04")
    def test_analytics_splits_long_backfills_into_windows_and_checkpoints_each(self):
        analytics_params: list[dict[str, Any]] = []

        def responder(url, params):
            if url.endswith("/shows"):
                return _response(200, _list_body([_resource("11", "show", {"created_at": "2024-01-01T00:00:00Z"})]))
            analytics_params.append(params)
            return _response(200, {"data": {"attributes": {"downloads": []}}})

        manager = _FakeResumableManager()
        _run(responder, "show_analytics", manager, should_use_incremental_field=False)

        assert [params["start_date"] for params in analytics_params] == ["01-01-2024", "31-12-2024", "31-12-2025"]
        # Each finished window is a resume point; the final one advances past the show.
        assert [(state.show_index, state.window_start) for state in manager.saved] == [
            (0, "2024-12-31"),
            (0, "2025-12-31"),
            (1, None),
        ]

    @freeze_time("2026-08-04")
    def test_analytics_resumes_at_the_saved_window(self):
        analytics_params: list[dict[str, Any]] = []

        def responder(url, params):
            if url.endswith("/shows"):
                return _response(200, _list_body([_resource("11", "show", {"created_at": "2024-01-01T00:00:00Z"})]))
            analytics_params.append(params)
            return _response(200, {"data": {"attributes": {"downloads": []}}})

        manager = _FakeResumableManager(TransistorResumeConfig(show_index=0, window_start="2025-12-31"))
        _run(responder, "show_analytics", manager, should_use_incremental_field=False)

        assert [params["start_date"] for params in analytics_params] == ["31-12-2025"]

    def test_show_analytics_rows_drop_unparseable_dates(self):
        payload = {
            "data": {
                "attributes": {
                    "downloads": [
                        {"date": "18-07-2026", "downloads": 3},
                        {"date": "whenever", "downloads": 4},
                        "not-a-dict",
                    ]
                }
            }
        }

        rows = list(show_analytics_rows("11", payload))

        assert rows == [{"show_id": "11", "date": "2026-07-18", "raw_date": "18-07-2026", "downloads": 3}]

    def test_episode_analytics_rows_carry_the_full_primary_key(self):
        payload = {
            "data": {
                "attributes": {
                    "episodes": [
                        {
                            "id": 2,
                            "title": "Episode Two",
                            "published_at": "2026-07-23 04:57:15 UTC",
                            "downloads": [{"date": "18-07-2026", "downloads": 9}],
                        },
                        {"title": "no id, skipped", "downloads": [{"date": "18-07-2026", "downloads": 1}]},
                    ]
                }
            }
        }

        rows = list(episode_analytics_rows("11", payload))

        assert rows == [
            {
                "show_id": "11",
                "episode_id": "2",
                "episode_title": "Episode Two",
                "episode_published_at": "2026-07-23 04:57:15 UTC",
                "date": "2026-07-18",
                "raw_date": "18-07-2026",
                "downloads": 9,
            }
        ]

    @pytest.mark.parametrize("endpoint", list(TRANSISTOR_ENDPOINTS))
    def test_source_response_shape_per_endpoint(self, endpoint):
        config = TRANSISTOR_ENDPOINTS[endpoint]

        response = transistor_source(
            endpoint=endpoint,
            api_key="key",
            logger=LOGGER,
            resumable_source_manager=_FakeResumableManager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Fan-out restarts dates at every show, so the watermark must only commit at completion.
        assert response.sort_mode == "desc"
        assert response.partition_keys == ([config.partition_key] if config.partition_key else None)

    @pytest.mark.parametrize(
        "status, expected_ok, expected_message_fragment",
        [
            (200, True, None),
            (401, False, "rejected the API key"),
            (403, False, "rejected the API key"),
            (500, False, "unexpected status code: 500"),
        ],
    )
    def test_validate_credentials_status_mapping(self, status, expected_ok, expected_message_fragment):
        session = _FakeSession(lambda url, params: _response(status))

        with mock.patch(f"{MODULE}._make_session", return_value=session):
            ok, message = validate_credentials("key")

        assert ok is expected_ok
        if expected_message_fragment is None:
            assert message is None
        else:
            assert expected_message_fragment in (message or "")

    @pytest.mark.parametrize("api_key", ["", "   ", None])
    def test_validate_credentials_rejects_a_blank_key_without_a_request(self, api_key):
        with mock.patch(f"{MODULE}._make_session") as make_session:
            ok, message = validate_credentials(api_key)

        assert ok is False
        assert message == "An API key is required."
        make_session.assert_not_called()

    def test_validate_credentials_reports_an_unreachable_api(self):
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")

        with mock.patch(f"{MODULE}._make_session", return_value=session):
            ok, message = validate_credentials("key")

        assert ok is False
        assert message is not None and "Could not reach" in message


class TestRequestThrottle:
    def test_paces_requests_to_the_minimum_interval(self):
        # Transistor blocks for 10 seconds once 10 requests land in 10 seconds, so requests are
        # paced rather than left to 429 backoff.
        clock = iter([0.0, 0.5, 1.1])
        sleeps: list[float] = []

        with (
            mock.patch("time.monotonic", lambda: next(clock)),
            mock.patch("time.sleep", lambda seconds: sleeps.append(seconds)),
        ):
            throttle = RequestThrottle(1.0)
            throttle.wait()
            throttle.wait()

        assert sleeps == [0.5]
