import time
import string
import datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.aviationstack import (
    AviationstackResumeConfig,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.source import AviationstackSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.aviationstack import (
    AviationstackSourceConfig,
)


def _driver(airport_iata_codes: str | None = None, flights_future_days: int | None = None) -> SourceDriver:
    return SourceDriver(
        AviationstackSource(),
        AviationstackSourceConfig(
            access_key="supersecret", airport_iata_codes=airport_iata_codes, flights_future_days=flights_future_days
        ),
    )


def _page(data: list[dict[str, Any]] | None, *, total: int | None = None, drop_data: bool = False) -> ScriptedResponse:
    body: dict[str, Any] = {"pagination": {"limit": 100, "offset": 0, "count": len(data or []), "total": total}}
    if not drop_data:
        body["data"] = data or []
    return ScriptedResponse(json=body)


def _error_body(code: str) -> ScriptedResponse:
    # aviationstack signals API-level errors with an HTTP 200 body envelope.
    return ScriptedResponse(json={"error": {"code": code, "message": "boom"}})


class TestPagination:
    def test_paginates_until_total_reached(self) -> None:
        page1 = [{"id": i} for i in range(100)]
        page2 = [{"id": i} for i in range(100, 200)]

        result = _driver().run("airlines", [_page(page1, total=200), _page(page2, total=200)])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == list(range(200))
        assert result.params("offset") == ["0", "100"]
        assert result.params("limit") == ["100", "100"]
        assert len(result.requests) == 2

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "airlines", [_page([{"id": 9}])], resume_state=AviationstackResumeConfig(next_offset=200)
        )

        # The first (and only) request must start from the persisted offset, not 0.
        assert result.raised is None
        assert result.params("offset") == ["200"]

    def test_saves_state_after_yielding_a_page(self) -> None:
        page1 = [{"id": i} for i in range(100)]
        page2 = [{"id": i} for i in range(100, 200)]

        result = _driver().run("airlines", [_page(page1, total=200), _page(page2, total=200)])

        # State saved once, with the next offset to resume from, only while more pages remain.
        assert result.raised is None
        assert result.saved_states == [AviationstackResumeConfig(next_offset=100)]
        assert result.committed_states == [AviationstackResumeConfig(next_offset=100)]

    def test_missing_data_key_raises_loudly(self) -> None:
        result = _driver().run("airlines", [_page(None, drop_data=True)])

        # A 200 body without "data" (an unrecognized error envelope or changed shape) fails loud
        # rather than silently syncing 0 rows.
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestBodyErrorEnvelope:
    def test_permanent_body_code_raises_and_hides_secret(self) -> None:
        result = _driver().run("airlines", [_error_body("invalid_access_key")])

        assert isinstance(result.raised, ValueError)
        # The stable [code] token is what get_non_retryable_errors matches on.
        assert "[invalid_access_key]" in str(result.raised)
        # The access_key secret value must never leak into the user-visible error.
        assert "supersecret" not in str(result.raised)
        # Permanent: raised on the first response, never retried.
        assert len(result.requests) == 1

    def test_rate_limit_body_code_is_retryable(self) -> None:
        result = _driver().run("airlines", always(_error_body("rate_limit_reached")))

        assert isinstance(result.raised, RESTClientRetryableError)
        # Retried up to the client's default attempt cap, then re-raised.
        assert len(result.requests) == 5


class TestHttpErrors:
    @parameterized.expand([("unauthorized", 401, "401"), ("forbidden", 403, "403")])
    def test_hard_auth_status_raises_without_leaking_secret(self, _name: str, status: int, expected: str) -> None:
        result = _driver().run("airlines", [ScriptedResponse(status=status, json={"data": [], "pagination": {}})])

        assert isinstance(result.raised, ValueError)
        assert expected in str(result.raised)
        assert "supersecret" not in str(result.raised)
        assert "access_key" not in str(result.raised)
        # Permanent credential/plan problem — not retried.
        assert len(result.requests) == 1

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_retryable_status_retries_then_raises(self, _name: str, status: int) -> None:
        result = _driver().run("airlines", always(ScriptedResponse(status=status, json={})))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5


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
        result = _driver().run("timetable", [])

        assert isinstance(result.raised, ValueError)
        assert "needs at least one airport" in str(result.raised)
        assert result.requests == []

    def test_flights_future_starts_beyond_the_vendor_cutoff(self) -> None:
        # aviationstack only serves /flightsFuture for dates more than 7 days out.
        today = datetime.date(2026, 3, 1)
        plan = build_request_plan(AVIATIONSTACK_ENDPOINTS["flights_future"], ["JFK"], 3, today=today)

        assert [request.params["date"] for request in plan if request.params["type"] == "departure"] == [
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

    def test_timetable_walks_every_planned_request_and_tags_rows(self) -> None:
        result = _driver(airport_iata_codes="JFK,DXB").run(
            "timetable", [_page([{"flight": {"number": str(index)}}]) for index in range(4)]
        )

        assert result.raised is None
        assert list(zip(result.params("iataCode"), result.params("type"))) == [
            ("JFK", "departure"),
            ("JFK", "arrival"),
            ("DXB", "departure"),
            ("DXB", "arrival"),
        ]
        assert [(row["queried_iata_code"], row["queried_type"]) for row in result.rows] == [
            ("JFK", "departure"),
            ("JFK", "arrival"),
            ("DXB", "departure"),
            ("DXB", "arrival"),
        ]

    def test_flights_future_rows_carry_the_requested_date(self) -> None:
        # The payload has a weekday and a wall-clock time but no date, so without the injected
        # queried_date a future schedule cannot be placed on a calendar at all.
        result = _driver(airport_iata_codes="JFK", flights_future_days=1).run(
            "flights_future", [_page([{"weekday": "7", "departure": {"scheduledTime": "06:15"}}]) for _ in range(2)]
        )

        assert result.raised is None
        assert len({row["queried_date"] for row in result.rows}) == 1
        assert all("date" not in row for row in result.rows)

    def test_exhausted_request_checkpoints_the_next_one(self) -> None:
        result = _driver(airport_iata_codes="JFK").run(
            "timetable", [_page([{"flight": {"number": str(index)}}]) for index in range(2)]
        )

        # After JFK departures completes, a resumed attempt must start at JFK arrivals, not re-run it.
        assert result.raised is None
        assert result.saved_states == [AviationstackResumeConfig(next_offset=0, next_request_index=1)]
        # The final request leaves no checkpoint behind.
        assert result.committed_states == [AviationstackResumeConfig(next_offset=0, next_request_index=1)]

    def test_resume_rebuilds_the_same_future_date_window(self) -> None:
        # A job resumed after a UTC midnight would otherwise shift its window by a day and skip the
        # date the crash interrupted.
        result = _driver(airport_iata_codes="JFK", flights_future_days=1).run(
            "flights_future",
            [_page([{"weekday": "1"}])],
            resume_state=AviationstackResumeConfig(next_offset=0, next_request_index=1, plan_start_date="2020-01-09"),
        )

        assert result.raised is None
        assert result.params("date") == ["2020-01-09"]


class TestThrottledEndpoints:
    @parameterized.expand([("timetable",), ("flights_future",)])
    def test_throttled_feeds_outlast_the_rate_limit_window(self, endpoint: str) -> None:
        request_times: list[float] = []

        def rate_limit(_request: RecordedRequest) -> ScriptedResponse:
            request_times.append(time.monotonic())
            return ScriptedResponse(status=429, json={})

        result = _driver(airport_iata_codes="JFK", flights_future_days=1).run(endpoint, rate_limit)

        assert isinstance(result.raised, RESTClientRetryableError)
        # The per-airport feeds allow one request every 60s on free plans, so the retry budget has to
        # outlast a whole window rather than the 15s the client's default budget covers.
        assert request_times[-1] - request_times[0] > 60


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
        result = _driver().run(endpoint, [_page([])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == expected_keys


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, {"data": []}, True),
            ("unauthorized", 401, {"error": {"code": "invalid_access_key"}}, False),
            ("ok_status_but_error_body", 200, {"error": {"code": "usage_limit_reached"}}, False),
        ]
    )
    def test_status_and_body_mapping(self, _name: str, status: int, body: dict[str, Any], expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status, json=body)]) as network:
            assert validate_credentials("k") is expected

        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/v1/countries"
        assert network.requests_log[0].param("access_key") == "k"

    def test_handles_network_error(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            assert validate_credentials("k") is False

        assert {request.path for request in network.requests_log} == {"/v1/countries"}
