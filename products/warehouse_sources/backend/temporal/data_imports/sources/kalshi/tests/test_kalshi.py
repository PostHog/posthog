import json
from datetime import UTC, date, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.kalshi import (
    KalshiResumeConfig,
    _to_epoch_seconds,
    kalshi_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.settings import KALSHI_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
KALSHI_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.kalshi.make_tracked_session"
)


def _response(data_key: str, items: list[dict[str, Any]] | None, *, cursor: str | None = None) -> Response:
    body: dict[str, Any] = {data_key: items or []}
    if cursor is not None:
        body["cursor"] = cursor
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: KalshiResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params at send time.

    ``request.params`` is one dict mutated in place across pages, so a copy has to be taken as each
    request is prepared; reading it afterwards would only show the last page's state.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append(dict(request.params or {}))
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any) -> Any:
    return kalshi_source(endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)


class TestKalshiTransport:
    @parameterized.expand(
        [
            ("datetime", datetime(2021, 1, 1, tzinfo=UTC), 1609459200),
            ("date", date(2021, 1, 1), 1609459200),
            ("int_passthrough", 1609459200, 1609459200),
            ("iso_string", "2021-01-01T00:00:00+00:00", 1609459200),
            ("iso_string_z", "2021-01-01T00:00:00Z", 1609459200),
            ("none", None, None),
            ("garbage", "not-a-date", None),
        ]
    )
    def test_to_epoch_seconds(self, _name: str, value: Any, expected: int | None) -> None:
        # min_ts is epoch seconds; sending an ISO string instead would be silently ignored by the
        # API and quietly turn every incremental sync into a full scan.
        assert _to_epoch_seconds(value) == expected

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_trades_incremental_sends_min_ts(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response("trades", [{"trade_id": "t1"}])])

        _rows(
            _source(
                "trades",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2021, 1, 1, tzinfo=UTC),
            )
        )

        assert params[0]["min_ts"] == 1609459200
        assert params[0]["limit"] == KALSHI_ENDPOINTS["trades"].page_size

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_trades_full_refresh_omits_min_ts(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response("trades", [{"trade_id": "t1"}])])

        _rows(
            _source(
                "trades",
                _make_manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value=datetime(2021, 1, 1, tzinfo=UTC),
            )
        )

        assert "min_ts" not in params[0]

    @parameterized.expand(["markets", "events", "milestones"])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_incremental_endpoints_never_send_min_ts(self, endpoint: str, MockSession) -> None:
        # Kalshi answers 200 and ignores params it doesn't recognise, so a filter wired onto an
        # endpoint that has none would look like it worked while syncing everything every run.
        session = MockSession.return_value
        params = _wire(session, [_response(KALSHI_ENDPOINTS[endpoint].data_key, [{"id": "1"}])])

        _rows(
            _source(
                endpoint,
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2021, 1, 1, tzinfo=UTC),
            )
        )

        assert "min_ts" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_cursor_pagination_walks_then_stops(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response("markets", [{"ticker": "A"}], cursor="c1"),
                _response("markets", [{"ticker": "B"}], cursor="c2"),
                # No cursor on the final page.
                _response("markets", [{"ticker": "C"}]),
            ],
        )

        rows = _rows(_source("markets", _make_manager()))

        assert [row["ticker"] for row in rows] == ["A", "B", "C"]
        # The first request carries no cursor; each later one carries the previous response's.
        assert "cursor" not in params[0]
        assert [p["cursor"] for p in params[1:]] == ["c1", "c2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_series_is_single_page(self, MockSession) -> None:
        # /series returns the whole collection and no cursor key. Paginating it would either loop or
        # re-request page one forever, so it must send no limit and stop after one request.
        session = MockSession.return_value
        params = _wire(session, [_response("series", [{"ticker": "S1"}, {"ticker": "S2"}])])

        rows = _rows(_source("series", _make_manager()))

        assert len(rows) == 2
        assert len(params) == 1
        assert "limit" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_seeds_cursor_onto_first_request(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response("markets", [{"ticker": "B"}])])

        _rows(_source("markets", _make_manager(KalshiResumeConfig(cursor="saved"))))

        assert params[0]["cursor"] == "saved"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_state_saved_per_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response("markets", [{"ticker": "A"}], cursor="c1"),
                _response("markets", [{"ticker": "B"}]),
            ],
        )
        manager = _make_manager()

        _rows(_source("markets", manager))

        # Only the page that has a successor is checkpointed; the terminal page has nothing to resume to.
        assert [c.args[0].cursor for c in manager.save_state.call_args_list] == ["c1"]

    @parameterized.expand(
        [
            ("trades", "desc"),
            ("markets", "asc"),
            ("series", "asc"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sort_mode_matches_api_order(self, endpoint: str, expected: str, MockSession) -> None:
        # Trades arrive newest-first. Declaring "asc" would checkpoint the watermark to ~now after
        # the first batch and skip the rest of the backfill.
        session = MockSession.return_value
        _wire(session, [_response(KALSHI_ENDPOINTS[endpoint].data_key, [])])

        assert _source(endpoint, _make_manager()).sort_mode == expected

    @parameterized.expand(
        [
            ("markets", ["ticker"]),
            ("events", ["event_ticker"]),
            ("series", ["ticker"]),
            ("trades", ["trade_id"]),
            ("milestones", ["id"]),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_primary_keys_per_endpoint(self, endpoint: str, expected: list[str], MockSession) -> None:
        # A wrong key seeds duplicate rows that every later merge multi-matches.
        session = MockSession.return_value
        _wire(session, [_response(KALSHI_ENDPOINTS[endpoint].data_key, [])])

        assert _source(endpoint, _make_manager()).primary_keys == expected

    @parameterized.expand(
        [
            ("trades", ["created_time"]),
            ("markets", ["created_time"]),
            ("series", None),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_partitioning_only_where_a_stable_key_exists(
        self, endpoint: str, expected: list[str] | None, MockSession
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_response(KALSHI_ENDPOINTS[endpoint].data_key, [])])

        response = _source(endpoint, _make_manager())

        assert response.partition_keys == expected
        assert response.partition_mode == ("datetime" if expected else None)

    @parameterized.expand([("ok", 200, True), ("forbidden", 403, False), ("server_error", 500, False)])
    @mock.patch(KALSHI_SESSION_PATCH)
    def test_validate_credentials_maps_status(self, _name: str, status: int, expected: bool, MockSession) -> None:
        resp = Response()
        resp.status_code = status
        MockSession.return_value.get.return_value = resp

        assert validate_credentials() is expected

    @mock.patch(KALSHI_SESSION_PATCH)
    def test_validate_credentials_survives_transport_error(self, MockSession) -> None:
        # An unreachable API must not raise out of source creation.
        MockSession.side_effect = OSError("boom")

        assert validate_credentials() is False
