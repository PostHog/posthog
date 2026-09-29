import json
import string
import datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack import aviationstack
from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.aviationstack import (
    AviationstackResumeConfig,
    aviationstack_source,
    build_request_plan,
    parse_iata_codes,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.settings import (
    AVIATIONSTACK_ENDPOINTS,
    FLIGHTS_FUTURE_FIRST_DAY_AHEAD,
    FLIGHTS_FUTURE_MAX_DAYS,
    MAX_AIRPORTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the aviationstack module.
AVIATIONSTACK_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.aviationstack.make_tracked_session"
)


def _page(data: list[dict[str, Any]] | None, *, total: int | None = None, drop_data: bool = False) -> Response:
    body: dict[str, Any] = {"pagination": {"limit": 100, "offset": 0, "count": len(data or []), "total": total}}
    if not drop_data:
        body["data"] = data or []
    return _response(body)


def _error_body(code: str) -> Response:
    # aviationstack signals API-level errors with an HTTP 200 body envelope.
    return _response({"error": {"code": code, "message": "boom"}})


def _response(body: Any, *, status: int = 200, reason: str = "OK") -> Response:
    resp = Response()
    resp.status_code = status
    resp.reason = reason
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = "https://api.aviationstack.com/v1/airlines?access_key=supersecret&offset=0&limit=100"
    return resp


def _make_manager(resume_state: AviationstackResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(
    endpoint: str = "airlines",
    manager: mock.MagicMock | None = None,
    airport_iata_codes: str | None = None,
    flights_future_days: int | None = None,
) -> Any:
    return aviationstack_source(
        "supersecret",
        endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager or _make_manager(),
        airport_iata_codes=airport_iata_codes,
        flights_future_days=flights_future_days,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_total_reached(self, MockSession) -> None:
        session = MockSession.return_value
        page1 = [{"id": i} for i in range(100)]
        page2 = [{"id": i} for i in range(100, 200)]
        params = _wire(session, [_page(page1, total=200), _page(page2, total=200)])

        rows = _rows(_source())

        assert [r["id"] for r in rows] == list(range(200))
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == 100
        assert params[1]["offset"] == 100
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_short_page(self, MockSession) -> None:
        # A page shorter than the limit means there's no further page, even without a total.
        session = MockSession.return_value
        _wire(session, [_page([{"id": 1}], total=None)])

        rows = _rows(_source())

        assert [r["id"] for r in rows] == [1]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_first_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([], total=0)])

        rows = _rows(_source())

        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page([{"id": 9}], total=None)])

        _rows(_source(manager=_make_manager(AviationstackResumeConfig(next_offset=200))))

        # The first (and only) request must start from the persisted offset, not 0.
        assert params[0]["offset"] == 200

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_yielding_a_page(self, MockSession) -> None:
        session = MockSession.return_value
        page1 = [{"id": i} for i in range(100)]
        page2 = [{"id": i} for i in range(100, 200)]
        _wire(session, [_page(page1, total=200), _page(page2, total=200)])

        manager = _make_manager()
        _rows(_source(manager=manager))

        # State saved once, with the next offset to resume from, only while more pages remain.
        manager.save_state.assert_called_once_with(AviationstackResumeConfig(next_offset=100))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_page_saves_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"id": 1}], total=None)])

        manager = _make_manager()
        _rows(_source(manager=manager))

        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page(None, drop_data=True)])

        # A 200 body without "data" (an unrecognized error envelope or changed shape) fails loud
        # rather than silently syncing 0 rows.
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source())


class TestBodyErrorEnvelope:
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_permanent_body_code_raises_and_hides_secret(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_error_body("invalid_access_key")])

        with pytest.raises(ValueError) as exc:
            _rows(_source())

        # The stable [code] token is what get_non_retryable_errors matches on.
        assert "[invalid_access_key]" in str(exc.value)
        # The access_key secret value must never leak into the user-visible error.
        assert "supersecret" not in str(exc.value)
        # Permanent: raised on the first response, never retried.
        assert session.send.call_count == 1

    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rate_limit_body_code_is_retryable(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.return_value = mock.MagicMock()
        session.send.return_value = _error_body("rate_limit_reached")

        with pytest.raises(RESTClientRetryableError):
            _rows(_source())
        # Retried up to the client's default attempt cap, then re-raised.
        assert session.send.call_count == 5


class TestHttpErrors:
    @parameterized.expand([("unauthorized", 401, "401"), ("forbidden", 403, "403")])
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_hard_auth_status_raises_without_leaking_secret(
        self, _name: str, status: int, expected: str, MockSession, _sleep
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"data": [], "pagination": {}}, status=status, reason=expected)])

        with pytest.raises(ValueError) as exc:
            _rows(_source())

        assert expected in str(exc.value)
        assert "supersecret" not in str(exc.value)
        assert "access_key" not in str(exc.value)
        # Permanent credential/plan problem — not retried.
        assert session.send.call_count == 1

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_retries_then_raises(self, _name: str, status: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.return_value = mock.MagicMock()
        session.send.return_value = _response({}, status=status, reason="err")

        with pytest.raises(RESTClientRetryableError):
            _rows(_source())
        assert session.send.call_count == 5


class TestAirportFanOut:
    @parameterized.expand(
        [
            ("blank", None, []),
            ("empty", "   ", []),
            ("comma_separated", "jfk,DXB", ["JFK", "DXB"]),
            ("mixed_separators", "JFK DXB\nLHR", ["JFK", "DXB", "LHR"]),
            ("dedupes", "JFK, jfk", ["JFK"]),
            # Real IATA airport codes are exactly three letters; junk must not become a request.
            ("drops_wrong_length", "JFK, HEATHROW, LH", ["JFK"]),
            ("drops_non_alpha", "JFK, 123", ["JFK"]),
        ]
    )
    def test_parse_iata_codes(self, _name: str, raw: str | None, expected: list[str]) -> None:
        assert parse_iata_codes(raw) == expected

    def test_parse_iata_codes_caps_fan_out(self) -> None:
        codes = ",".join(f"A{first}{second}" for first in string.ascii_uppercase for second in "ABCD")
        assert len(parse_iata_codes(codes)) == MAX_AIRPORTS

    def test_per_airport_endpoint_without_airports_raises(self) -> None:
        with pytest.raises(ValueError, match="needs at least one airport"):
            _source("timetable")

    def test_timetable_plans_one_request_per_airport_and_direction(self) -> None:
        plan = build_request_plan(AVIATIONSTACK_ENDPOINTS["timetable"], ["JFK", "DXB"])

        assert [(r.params["iataCode"], r.params["type"]) for r in plan] == [
            ("JFK", "departure"),
            ("JFK", "arrival"),
            ("DXB", "departure"),
            ("DXB", "arrival"),
        ]
        assert all("date" not in r.params for r in plan)

    def test_flights_future_starts_beyond_the_vendor_cutoff(self) -> None:
        # aviationstack only serves /flightsFuture for dates more than 7 days out.
        today = datetime.date(2026, 3, 1)
        plan = build_request_plan(AVIATIONSTACK_ENDPOINTS["flights_future"], ["JFK"], 3, today=today)

        assert [r.params["date"] for r in plan if r.params["type"] == "departure"] == [
            "2026-03-09",
            "2026-03-10",
            "2026-03-11",
        ]
        assert (today + datetime.timedelta(days=FLIGHTS_FUTURE_FIRST_DAY_AHEAD)).isoformat() == "2026-03-09"

    @parameterized.expand([("zero", 0, 1), ("negative", -5, 1), ("oversized", 500, FLIGHTS_FUTURE_MAX_DAYS)])
    def test_flights_future_window_is_bounded(self, _name: str, days: int, expected: int) -> None:
        plan = build_request_plan(AVIATIONSTACK_ENDPOINTS["flights_future"], ["JFK"], days)
        # Two schedule directions per date.
        assert len(plan) == expected * 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_timetable_walks_every_planned_request_and_tags_rows(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page([{"flight": {"number": str(i)}}], total=None) for i in range(4)])

        rows = _rows(_source("timetable", airport_iata_codes="JFK,DXB"))

        assert [(p["iataCode"], p["type"]) for p in params] == [
            ("JFK", "departure"),
            ("JFK", "arrival"),
            ("DXB", "departure"),
            ("DXB", "arrival"),
        ]
        assert [(r["queried_iata_code"], r["queried_type"]) for r in rows] == [
            ("JFK", "departure"),
            ("JFK", "arrival"),
            ("DXB", "departure"),
            ("DXB", "arrival"),
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_flights_future_rows_carry_the_requested_date(self, MockSession) -> None:
        session = MockSession.return_value
        # The payload has a weekday and a wall-clock time but no date, so without the injected
        # queried_date a future schedule cannot be placed on a calendar at all.
        _wire(session, [_page([{"weekday": "7", "departure": {"scheduledTime": "06:15"}}]) for _ in range(2)])

        rows = _rows(_source("flights_future", airport_iata_codes="JFK", flights_future_days=1))

        assert len({r["queried_date"] for r in rows}) == 1
        assert all("date" not in r for r in rows)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_requests(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page([{"flight": {"number": "1"}}], total=None)])

        manager = _make_manager(AviationstackResumeConfig(next_offset=0, next_request_index=3))
        _rows(_source("timetable", manager=manager, airport_iata_codes="JFK,DXB"))

        # Index 3 is the last planned request (DXB arrivals) — the first three must not be re-sent.
        assert session.send.call_count == 1
        assert (params[0]["iataCode"], params[0]["type"]) == ("DXB", "arrival")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_exhausted_request_checkpoints_the_next_one(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"flight": {"number": str(i)}}], total=None) for i in range(2)])

        manager = _make_manager()
        _rows(_source("timetable", manager=manager, airport_iata_codes="JFK"))

        # After JFK departures completes, a resumed attempt must start at JFK arrivals, not re-run it.
        assert manager.save_state.call_args_list[0].args[0] == AviationstackResumeConfig(
            next_offset=0, next_request_index=1, plan_start_date=None
        )
        # The final request leaves no checkpoint behind.
        assert manager.save_state.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_rebuilds_the_same_future_date_window(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page([{"weekday": "1"}], total=None)])

        # A job resumed after a UTC midnight would otherwise shift its window by a day and skip the
        # date the crash interrupted.
        manager = _make_manager(
            AviationstackResumeConfig(next_offset=0, next_request_index=1, plan_start_date="2020-01-09")
        )
        _rows(_source("flights_future", manager=manager, airport_iata_codes="JFK", flights_future_days=1))

        assert params[0]["date"] == "2020-01-09"


class TestThrottledEndpoints:
    @parameterized.expand([("timetable",), ("flights_future",)])
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_throttled_feeds_outlast_the_rate_limit_window(self, endpoint: str, MockSession, sleep) -> None:
        session = MockSession.return_value
        session.headers = {}
        session.prepare_request.return_value = mock.MagicMock()
        session.send.return_value = _response({}, status=429, reason="Too Many Requests")

        with pytest.raises(RESTClientRetryableError):
            _rows(_source(endpoint, airport_iata_codes="JFK", flights_future_days=1))

        # The per-airport feeds allow one request every 60s on free plans, so the retry budget has to
        # outlast a whole window rather than the 15s the client's default budget covers.
        assert sum(call.args[0] for call in sleep.call_args_list) > 60


class TestSourceResponse:
    @parameterized.expand(
        [
            ("airlines", ["id"]),
            ("airports", ["id"]),
            ("countries", ["id"]),
            ("flights", None),
            ("routes", None),
        ]
    )
    def test_primary_keys(self, endpoint: str, expected_keys: list[str] | None) -> None:
        response = _source(endpoint)
        assert response.name == endpoint
        assert response.primary_keys == expected_keys

    def test_every_endpoint_builds_a_source_response(self) -> None:
        for endpoint in AVIATIONSTACK_ENDPOINTS:
            response = _source(endpoint, airport_iata_codes="JFK")
            assert response.name == endpoint
            assert callable(response.items)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, {"data": []}, True),
            ("unauthorized", 401, {"error": {"code": "invalid_access_key"}}, False),
            ("ok_status_but_error_body", 200, {"error": {"code": "usage_limit_reached"}}, False),
        ]
    )
    def test_status_and_body_mapping(self, _name: str, status: int, body: dict, expected: bool) -> None:
        response = mock.MagicMock()
        response.status_code = status
        response.json.return_value = body
        session = mock.MagicMock()
        session.get.return_value = response
        with mock.patch(AVIATIONSTACK_SESSION_PATCH, return_value=session):
            assert validate_credentials("k") is expected

    def test_handles_network_error(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(AVIATIONSTACK_SESSION_PATCH, return_value=session):
            assert validate_credentials("k") is False


def test_module_exposes_base_url() -> None:
    assert aviationstack.AVIATIONSTACK_BASE_URL == "https://api.aviationstack.com/v1"
