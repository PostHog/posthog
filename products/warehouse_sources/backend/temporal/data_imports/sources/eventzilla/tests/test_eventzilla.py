import json
from typing import Any, Optional

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.eventzilla import eventzilla as ez
from products.warehouse_sources.backend.temporal.data_imports.sources.eventzilla.eventzilla import (
    PAGE_SIZE,
    EventzillaResumeConfig,
    eventzilla_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# tenacity sleeps between the client's own retries — patch it so retry tests don't actually wait.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _json_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _page(data_key: str, items: list[dict[str, Any]], total: Optional[int] = None) -> Response:
    """A list page. When ``total`` is given a ``pagination`` envelope is included (the paginate
    signal); omit it to model an endpoint that returns its whole result set in one response."""
    body: dict[str, Any] = {data_key: items}
    if total is not None:
        body["pagination"] = {"offset": 0, "limit": PAGE_SIZE, "total": total}
    return _json_response(body)


def _make_manager(resume_state: EventzillaResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[str], list[dict[str, Any]]]:
    """Wire a mock session and capture each request's URL and query params AT SEND TIME.

    ``request.params`` is mutated in place across pages (the paginator rewrites the offset), so
    snapshot a copy when each request is prepared. ``prepared.url`` carries the built query string so
    a test can read the offset the client actually sent.
    """
    session.headers = {}
    url_snapshots: list[str] = []
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        params = dict(request.params or {})
        param_snapshots.append(params)
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = request.url + (f"?{query}" if query else "")
        url_snapshots.append(url)
        prepared = mock.MagicMock()
        prepared.url = url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return url_snapshots, param_snapshots


def _offsets(param_snapshots: list[dict[str, Any]]) -> list[int]:
    return [int(p["offset"]) for p in param_snapshots if "offset" in p]


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _pages(source_response):
    yield from source_response.items()


def _source(endpoint: str, manager: mock.MagicMock | None = None):
    return eventzilla_source(
        api_key="key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager or _make_manager(),
    )


class TestTopLevelPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_first_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page("events", [], total=0)])

        assert _rows(_source("events")) == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_without_pagination_object_stops(self, MockSession) -> None:
        # A page with no `pagination` object means the list is exhausted; a second request (which
        # would re-read the same rows for a non-paging endpoint) is a bug.
        session = MockSession.return_value
        _wire(session, [_page("categories", [{"category": "Music"}, {"category": "Tech"}])])

        rows = _rows(_source("categories"))

        assert rows == [{"category": "Music"}, {"category": "Tech"}]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_pagination_total_terminates_even_on_a_full_page(self, MockSession) -> None:
        # When `total` is reached we must stop, even though the page came back full (== PAGE_SIZE),
        # otherwise we'd issue an unnecessary extra request and risk re-reading rows.
        session = MockSession.return_value
        full_page = [{"id": i} for i in range(PAGE_SIZE)]
        _wire(session, [_page("events", full_page, total=PAGE_SIZE)])

        rows = _rows(_source("events"))

        assert len(rows) == PAGE_SIZE
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_multiple_pages_until_total_reached(self, MockSession) -> None:
        session = MockSession.return_value
        _urls, params = _wire(
            session,
            [
                _page("events", [{"id": i} for i in range(PAGE_SIZE)], total=PAGE_SIZE + 1),
                _page("events", [{"id": 999}], total=PAGE_SIZE + 1),
            ],
        )

        rows = _rows(_source("events"))

        assert len(rows) == PAGE_SIZE + 1
        # The offset advances by the real returned count, not a fixed step.
        assert _offsets(params) == [0, PAGE_SIZE]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_offset_advances_by_actual_count_when_server_clamps_page_size(self, MockSession) -> None:
        # If the server clamps `limit` below PAGE_SIZE we must advance by rows returned, not PAGE_SIZE,
        # or we'd skip rows. Two clamped-to-20 pages then an empty page.
        session = MockSession.return_value
        _urls, params = _wire(
            session,
            [
                _page("events", [{"id": i} for i in range(20)], total=25),
                _page("events", [{"id": i} for i in range(20, 25)], total=25),
            ],
        )

        rows = _rows(_source("events"))

        assert [r["id"] for r in rows] == list(range(25))
        assert _offsets(params) == [0, 20]


class TestTopLevelResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_uses_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        _urls, params = _wire(session, [_page("events", [], total=40)])

        _rows(_source("events", _make_manager(EventzillaResumeConfig(offset=40))))

        assert _offsets(params) == [40]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_state_saved_only_after_page_is_yielded_carrying_next_offset(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _page("events", [{"id": 1}], total=2),
                _page("events", [{"id": 2}], total=2),
            ],
        )
        manager = _make_manager()

        rows = iter(_pages(_source("events", manager)))

        assert next(rows) == [{"id": 1}]
        # A crash here must re-fetch page 1 (nothing persisted yet), not skip it.
        manager.save_state.assert_not_called()

        assert next(rows) == [{"id": 2}]
        # After page 1 is yielded the checkpoint points at the NEXT offset; top-level saves never
        # carry a fan-out state.
        saved = manager.save_state.call_args.args[0]
        assert saved.offset == 1
        assert saved.fanout_state is None


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool) -> None:
        session = mock.MagicMock()
        session.get.return_value = _json_response({}, status_code=status)
        with mock.patch.object(ez, "make_tracked_session", return_value=session):
            assert validate_credentials("key") is expected

    def test_transport_error_is_false(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = Exception("boom")
        with mock.patch.object(ez, "make_tracked_session", return_value=session):
            assert validate_credentials("key") is False

    def test_probe_carries_api_key_header(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _json_response({}, status_code=200)
        with mock.patch.object(ez, "make_tracked_session", return_value=session):
            validate_credentials("secret-key")
        _args, kwargs = session.get.call_args
        assert kwargs["headers"]["x-api-key"] == "secret-key"


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_5xx_and_429_are_retried_then_succeed(self, _name: str, status: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_json_response({}, status_code=status), _page("events", [{"id": 1}], total=1)])

        rows = _rows(_source("events"))

        assert [r["id"] for r in rows] == [1]
        assert session.send.call_count == 2

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_4xx_auth_error_is_raised(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_json_response({"error": "unauthorized"}, status_code=401)])

        with pytest.raises(Exception):
            _rows(_source("events"))


class TestFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stamps_event_id_and_aggregates_across_events(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _page("events", [{"id": 1}, {"id": 2}], total=2),  # events discovery
                _page("attendees", [{"id": "A1"}, {"id": "A2"}]),  # event 1
                _page("attendees", [{"id": "A3"}]),  # event 2
            ],
        )

        rows = _rows(_source("attendees", _make_manager()))

        # Each child row is stamped with its parent event id (as a string, keeping the composite
        # primary key (event_id, id) unique table-wide).
        assert rows == [
            {"id": "A1", "event_id": "1"},
            {"id": "A2", "event_id": "1"},
            {"id": "A3", "event_id": "2"},
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_child_url_targets_the_event(self, MockSession) -> None:
        session = MockSession.return_value
        urls, _params = _wire(
            session,
            [_page("events", [{"id": 7}], total=1), _page("attendees", [{"id": "A1"}])],
        )

        _rows(_source("attendees", _make_manager()))

        assert any("/events/7/attendees" in url for url in urls)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fan_out_is_resumable_and_checkpoints(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _page("events", [{"id": 1}, {"id": 2}], total=2),
                _page("attendees", [{"id": "A1"}]),
                _page("attendees", [{"id": "A2"}]),
            ],
        )
        manager = _make_manager()

        _rows(_source("attendees", manager))

        assert manager.save_state.called
        saved = manager.save_state.call_args.args[0]
        assert saved.fanout_state is not None

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_events(self, MockSession) -> None:
        # Resuming with event 1's child path already completed must skip it entirely and only fetch
        # event 2's attendees. Only two responses are wired (events discovery + event 2), so a fetch
        # of event 1 would exhaust the side-effect list and fail.
        session = MockSession.return_value
        urls, _params = _wire(
            session,
            [_page("events", [{"id": 1}, {"id": 2}], total=2), _page("attendees", [{"id": "A3"}])],
        )
        fanout_state = {
            "completed": ["/events/1/attendees"],
            "current": "/events/2/attendees",
            "child_state": {"offset": 0},
        }
        manager = _make_manager(EventzillaResumeConfig(fanout_state=fanout_state))

        rows = _rows(_source("attendees", manager))

        assert rows == [{"id": "A3", "event_id": "2"}]
        assert not any("/events/1/attendees" in url for url in urls)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_event_deleted_mid_fan_out_is_skipped(self, MockSession) -> None:
        # A 404 on a child fetch (event deleted between enumeration and fetch) is ignored so the sync
        # skips that event and continues, rather than failing the whole import.
        session = MockSession.return_value
        _wire(
            session,
            [
                _page("events", [{"id": 1}, {"id": 2}], total=2),
                _json_response({"error": "not found"}, status_code=404),  # event 1 gone
                _page("attendees", [{"id": "A3"}]),  # event 2
            ],
        )

        rows = _rows(_source("attendees", _make_manager()))

        assert rows == [{"id": "A3", "event_id": "2"}]

    @mock.patch(SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_404_child_error_propagates(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        # A 5xx is retried up to the client's attempt cap; supply enough copies that the retryable
        # error (not a side-effect-exhaustion artifact) is what finally propagates.
        _wire(
            session,
            [_page("events", [{"id": 1}], total=1)] + [_json_response({"error": "boom"}, status_code=500)] * 5,
        )

        with pytest.raises(Exception):
            _rows(_source("attendees", _make_manager()))


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
        response = _source(endpoint)

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"
            assert response.partition_keys == [partition_key]
