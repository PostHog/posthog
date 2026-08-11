import json
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from freezegun import freeze_time
from unittest import mock

from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.sendgrid import (
    SendGridResumeConfig,
    _offset_from_url,
    _to_date_string,
    _to_epoch_seconds,
    get_endpoint_permissions,
    get_status_code,
    sendgrid_source,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# get_status_code builds its own tracked session in the sendgrid module.
SENDGRID_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.sendgrid.make_tracked_session"
)


def _response(body: Any) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: SendGridResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[str]]:
    """Wire a mock session; capture each request's params and URL AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared instead of inspecting it after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        url_snapshots.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, url_snapshots


def _source(endpoint: str, manager: mock.MagicMock, **overrides: Any) -> Any:
    return sendgrid_source("k", endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **overrides)


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestToEpochSeconds:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1700000000, 1700000000),
            ("1700000000", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (date(1970, 1, 2), 86400),
        ],
    )
    def test_to_epoch_seconds(self, value: Any, expected: int) -> None:
        assert _to_epoch_seconds(value) == expected

    def test_naive_datetime_treated_as_utc(self) -> None:
        assert _to_epoch_seconds(datetime(2023, 11, 14, 22, 13, 20)) == 1700000000


class TestToDateString:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2024-01-15", "2024-01-15"),
            ("2024-01-15T00:00:00", "2024-01-15"),
            (date(2024, 1, 15), "2024-01-15"),
            (datetime(2024, 1, 15, 22, 13, 20, tzinfo=UTC), "2024-01-15"),
            # Epoch seconds — the cursor may round-trip through storage as a number.
            (1705270400, "2024-01-14"),
        ],
    )
    def test_to_date_string(self, value: Any, expected: str) -> None:
        assert _to_date_string(value) == expected

    def test_naive_datetime_treated_as_utc(self) -> None:
        assert _to_date_string(datetime(2024, 1, 15, 22, 13, 20)) == "2024-01-15"


class TestStats:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_flattens_nested_daily_metrics_into_one_row_per_day(self, MockSession) -> None:
        session = MockSession.return_value
        body = [
            {"date": "2024-01-01", "stats": [{"metrics": {"requests": 10, "delivered": 8, "bounces": 1}}]},
            {"date": "2024-01-02", "stats": [{"metrics": {"requests": 5, "delivered": 5, "bounces": 0}}]},
        ]
        params, _urls = _wire(session, [_response(body)])

        rows = _rows(_source("stats", _make_manager()))

        # The nested {date, stats:[{metrics}]} shape flattens to flat daily rows the denominator lives on.
        assert rows == [
            {"date": "2024-01-01", "requests": 10, "delivered": 8, "bounces": 1},
            {"date": "2024-01-02", "requests": 5, "delivered": 5, "bounces": 0},
        ]
        assert params[0]["aggregated_by"] == "day"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_sync_backfills_a_required_start_date(self, MockSession) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response([])])

        # /stats rejects a request with no start_date, so a cursorless sync must still send one.
        _rows(_source("stats", _make_manager()))

        assert "start_date" in params[0]
        # A YYYY-MM-DD string, not epoch seconds — the format /stats requires.
        datetime.strptime(params[0]["start_date"], "%Y-%m-%d")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_cursor_becomes_a_date_formatted_start_date(self, MockSession) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response([])])

        _rows(
            _source(
                "stats",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value="2024-03-10",
                incremental_field="date",
            )
        )

        assert params[0]["start_date"] == "2024-03-10"


class TestOffsetFromUrl:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://api.sendgrid.com/v3/suppression/bounces?limit=500&offset=500", 500),
            ("https://api.sendgrid.com/v3/suppression/bounces?limit=500", 0),
            ("https://api.sendgrid.com/v3/suppression/bounces", 0),
        ],
    )
    def test_offset_from_url(self, url: str, expected: int) -> None:
        assert _offset_from_url(url) == expected


class TestOffsetPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page_and_saves_state(self, MockSession) -> None:
        session = MockSession.return_value
        page1 = [{"email": f"a{i}@x.com", "created": i} for i in range(500)]
        page2 = [{"email": "b@x.com", "created": 1}]
        params, _urls = _wire(session, [_response(page1), _response(page2)])

        manager = _make_manager()
        rows = _rows(_source("bounces", manager))

        assert rows == [*page1, *page2]
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == 500
        assert params[1]["offset"] == 500
        # Checkpoint saved once (after the full first page); the terminal short page saves nothing.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == SendGridResumeConfig(offset=500)
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"email": "a@x.com"}, {"email": "b@x.com"}])])

        manager = _make_manager()
        rows = _rows(_source("bounces", manager))

        assert [r["email"] for r in rows] == ["a@x.com", "b@x.com"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response([{"email": "b@x.com"}])])

        manager = _make_manager(SendGridResumeConfig(offset=500))
        _rows(_source("bounces", manager))

        assert params[0]["offset"] == 500

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_legacy_next_url_state(self, MockSession) -> None:
        # Pre-migration saved states stored the offset inside a full URL under ``next_url``.
        session = MockSession.return_value
        params, _urls = _wire(session, [_response([{"email": "b@x.com"}])])

        resume_url = "https://api.sendgrid.com/v3/suppression/bounces?limit=500&offset=500"
        manager = _make_manager(SendGridResumeConfig(next_url=resume_url))
        _rows(_source("bounces", manager))

        assert params[0]["offset"] == 500

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_start_time_in_initial_params(self, MockSession) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response([{"email": "b@x.com"}])])

        _rows(
            _source(
                "bounces",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000,
                incremental_field="created",
            )
        )

        assert params[0]["start_time"] == 1700000000
        assert params[0]["offset"] == 0

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_start_time_without_incremental(self, MockSession) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response([{"email": "b@x.com"}])])

        _rows(_source("bounces", _make_manager()))
        assert "start_time" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"unexpected": "dict"})])

        # A 200 body that isn't the expected bare array means the response shape changed — fail
        # loud instead of silently syncing 0 rows.
        with pytest.raises(ValueError, match="list response body"):
            _rows(_source("bounces", _make_manager()))


class TestMetadataPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_metadata_next(self, MockSession) -> None:
        session = MockSession.return_value
        next_url = "https://api.sendgrid.com/v3/marketing/lists?page_token=tok&page_size=100"
        page1 = {"result": [{"id": 1}], "_metadata": {"next": next_url}}
        page2 = {"result": [{"id": 2}], "_metadata": {}}
        params, urls = _wire(session, [_response(page1), _response(page2)])

        manager = _make_manager()
        rows = _rows(_source("marketing_lists", manager))

        assert rows == [{"id": 1}, {"id": 2}]
        assert params[0]["page_size"] == 100
        assert urls[1] == next_url
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == SendGridResumeConfig(next_url=next_url)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_templates_sends_generations_param(self, MockSession) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response({"result": [{"id": 1}], "_metadata": {}})])

        _rows(_source("templates", _make_manager()))
        assert params[0]["generations"] == "legacy,dynamic"
        assert params[0]["page_size"] == 100

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_result_key_raises_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"_metadata": {}})])

        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source("marketing_lists", _make_manager()))


class TestOffHostGuard:
    @pytest.mark.parametrize(
        "off_host_url",
        [
            "http://169.254.169.254/latest/meta-data/",
            "https://evil.example.com/v3/marketing/lists",
            "https://api.sendgrid.com.evil.com/v3/marketing/lists",
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_metadata_next_is_ignored(self, MockSession, off_host_url: str) -> None:
        session = MockSession.return_value
        page1 = {"result": [{"id": 1}], "_metadata": {"next": off_host_url}}
        _wire(session, [_response(page1)])

        manager = _make_manager()
        rows = _rows(_source("marketing_lists", manager))

        # The tampered next URL is dropped: yield the first page and stop without following it.
        assert rows == [{"id": 1}]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_resume_url_raises(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [])

        manager = _make_manager(SendGridResumeConfig(next_url="http://169.254.169.254/latest/meta-data/"))
        with pytest.raises(ValueError, match="unexpected URL"):
            _rows(_source("marketing_lists", manager))


class TestSinglePagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_request_no_pagination(self, MockSession) -> None:
        session = MockSession.return_value
        groups = [{"id": 1}, {"id": 2}]
        _wire(session, [_response(groups)])

        manager = _make_manager()
        rows = _rows(_source("unsubscribe_groups", manager))

        assert rows == groups
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


def _messages_page(count: int, last_event_time: str) -> list[dict[str, Any]]:
    return [{"msg_id": f"m{last_event_time}-{i}", "last_event_time": last_event_time} for i in range(count)]


class TestActivityPagination:
    @freeze_time("2026-08-07T12:00:00Z")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_query_window_backwards_until_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        # Sub-second precision on the oldest row exercises the flooring of window bounds.
        page1 = [
            *_messages_page(999, "2026-08-01T05:00:00Z"),
            {"msg_id": "old", "last_event_time": "2026-07-20T09:00:00.500Z"},
        ]
        page2 = [{"msg_id": "oldest", "last_event_time": "2026-07-10T00:00:00Z"}]
        params, _urls = _wire(session, [_response({"messages": page1}), _response({"messages": page2})])

        manager = _make_manager()
        rows = _rows(_source("message_activity", manager))

        assert rows == [*page1, *page2]
        assert params[0]["limit"] == 1000
        assert (
            params[0]["query"]
            == 'last_event_time BETWEEN TIMESTAMP "2026-07-08T12:00:00Z" AND TIMESTAMP "2026-08-07T12:00:00Z"'
        )
        # The second request narrows the window end to the oldest timestamp of the full page.
        assert (
            params[1]["query"]
            == 'last_event_time BETWEEN TIMESTAMP "2026-07-08T12:00:00Z" AND TIMESTAMP "2026-07-20T09:00:00Z"'
        )
        assert session.send.call_count == 2
        # Checkpoint saved once (after the full first page); the terminal short page saves nothing.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == SendGridResumeConfig(
            activity_window_start="2026-07-08T12:00:00Z", activity_window_end="2026-07-20T09:00:00Z"
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_window(self, MockSession) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response({"messages": [{"msg_id": "m1"}]})])

        manager = _make_manager(
            SendGridResumeConfig(
                activity_window_start="2026-07-08T12:00:00Z", activity_window_end="2026-07-20T09:00:00Z"
            )
        )
        _rows(_source("message_activity", manager))

        # Both bounds come from the saved state, so a resumed first backfill keeps its
        # original window instead of recomputing it from "now".
        assert (
            params[0]["query"]
            == 'last_event_time BETWEEN TIMESTAMP "2026-07-08T12:00:00Z" AND TIMESTAMP "2026-07-20T09:00:00Z"'
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_tampered_resume_window_raises(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [])

        manager = _make_manager(
            SendGridResumeConfig(
                activity_window_start='" OR to_email LIKE "%', activity_window_end="2026-07-20T09:00:00Z"
            )
        )
        with pytest.raises(ValueError, match="unexpected timestamp"):
            _rows(_source("message_activity", manager))

    @pytest.mark.parametrize(
        "cursor",
        [
            datetime(2026, 8, 1, 3, 4, 5, tzinfo=UTC),
            "2026-08-01T03:04:05Z",
            "2026-08-01T03:04:05.123456+00:00",
            int(datetime(2026, 8, 1, 3, 4, 5, tzinfo=UTC).timestamp()),
        ],
    )
    @freeze_time("2026-08-07T12:00:00Z")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_window_starts_at_watermark(self, MockSession, cursor: Any) -> None:
        # The cursor round-trips through storage in several shapes; all must produce the same
        # server-side window, otherwise every incremental sync silently refetches 30 days.
        session = MockSession.return_value
        params, _urls = _wire(session, [_response({"messages": [{"msg_id": "m1"}]})])

        _rows(
            _source(
                "message_activity",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=cursor,
                incremental_field="last_event_time",
            )
        )

        assert (
            params[0]["query"]
            == 'last_event_time BETWEEN TIMESTAMP "2026-08-01T03:04:05Z" AND TIMESTAMP "2026-08-07T12:00:00Z"'
        )

    @freeze_time("2026-08-07T12:00:00Z")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_page_that_cannot_narrow_the_window_stops(self, MockSession) -> None:
        # More than `limit` messages sharing the window-end second would otherwise refetch the
        # same page until the activity times out.
        session = MockSession.return_value
        page = _messages_page(1000, "2026-08-07T12:00:00Z")
        _wire(session, [_response({"messages": page})])

        manager = _make_manager()
        rows = _rows(_source("message_activity", manager))

        assert rows == page
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_403_error_text_matches_the_non_retryable_key(self, MockSession) -> None:
        # The add-on gate surfaces per table through `get_non_retryable_errors`, whose /v3/messages
        # key is a substring match on this exact error text — if the phrasing drifts, the 403
        # retries forever instead of failing with the add-on message.
        session = MockSession.return_value
        response = Response()
        response.status_code = 403
        response.reason = "Forbidden"
        response.url = "https://api.sendgrid.com/v3/messages?limit=1000&query=..."
        response._content = json.dumps({"errors": [{"message": "access forbidden"}]}).encode()
        _wire(session, [response])

        with pytest.raises(HTTPError) as excinfo:
            _rows(_source("message_activity", _make_manager()))

        assert "403 Client Error: Forbidden for url: https://api.sendgrid.com/v3/messages" in str(excinfo.value)


class TestSourceResponse:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_suppression_endpoint_partitioning_and_keys(self, MockSession) -> None:
        response = _source("bounces", _make_manager())
        assert response.name == "bounces"
        assert response.primary_keys == ["email"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created"]
        assert response.sort_mode == "asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoint_has_no_partitioning(self, MockSession) -> None:
        response = _source("marketing_lists", _make_manager())
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_message_activity_is_desc_keyed_on_msg_id_and_unpartitioned(self, MockSession) -> None:
        response = _source("message_activity", _make_manager())
        assert response.primary_keys == ["msg_id"]
        # Newest-first walk: declaring "asc" would checkpoint the watermark at ≈now after the
        # first batch and skip everything older on the next incremental sync.
        assert response.sort_mode == "desc"
        # last_event_time advances whenever a new event lands, so it can't be a partition key.
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestGetStatusCode:
    @pytest.mark.parametrize("status", [200, 401, 403, 404])
    def test_returns_status(self, status: int) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status)
        with mock.patch(SENDGRID_SESSION_PATCH, return_value=session):
            assert get_status_code("k", "/scopes") == status

    def test_returns_none_on_transport_error(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = Exception("boom")
        with mock.patch(SENDGRID_SESSION_PATCH, return_value=session):
            assert get_status_code("k", "/scopes") is None


class TestGetEndpointPermissions:
    @staticmethod
    def _probe(status: int | None, endpoints: list[str]) -> dict[str, str | None]:
        session = mock.MagicMock()
        if status is None:
            session.get.side_effect = Exception("boom")
        else:
            session.get.return_value = mock.MagicMock(status_code=status)
        with mock.patch(SENDGRID_SESSION_PATCH, return_value=session):
            return get_endpoint_permissions("k", endpoints)

    @pytest.mark.parametrize(
        ("status", "expect_blocked"),
        [
            (200, False),
            (403, True),
            (401, True),
            # A throttle, a 5xx, or a dead connection is not a scope problem. Blocking the table here
            # would tell users to change permissions that are already correct.
            (429, False),
            (500, False),
            (None, False),
        ],
    )
    def test_only_a_definitive_denial_blocks_a_table(self, status: int | None, expect_blocked: bool) -> None:
        permissions = self._probe(status, ["marketing_lists"])
        assert (permissions["marketing_lists"] is not None) is expect_blocked

    @pytest.mark.parametrize(
        ("endpoint", "fragments"),
        [
            ("marketing_lists", ["marketing.read", "Marketing Campaigns"]),
            ("message_activity", ["email_activity.read", "additional email activity history"]),
        ],
    )
    def test_403_names_the_scope_and_its_account_caveat(self, endpoint: str, fragments: list[str]) -> None:
        reason = self._probe(403, [endpoint])[endpoint]
        assert reason is not None
        for fragment in fragments:
            assert fragment in reason

    def test_unknown_endpoint_is_treated_as_reachable(self) -> None:
        assert self._probe(403, ["not_an_endpoint"]) == {"not_an_endpoint": None}

    @pytest.mark.parametrize(
        ("endpoint", "expected_params"),
        [
            ("bounces", {"limit": "1"}),
            # A blanket `limit=1` is not a param the marketing endpoints take, so probing with it
            # risks a 400 that reads as "reachable" and hides the real denial.
            ("marketing_lists", {"page_size": "1"}),
            ("templates", {"page_size": "1", "generations": "legacy,dynamic"}),
            ("unsubscribe_groups", {}),
            # /messages requires `query`, so a probe without one risks the same masking 400.
            (
                "message_activity",
                {
                    "limit": "1",
                    "query": 'last_event_time BETWEEN TIMESTAMP "2026-08-06T12:00:00Z" AND TIMESTAMP "2026-08-07T12:00:00Z"',
                },
            ),
        ],
    )
    @freeze_time("2026-08-07T12:00:00Z")
    def test_probe_uses_the_endpoints_own_pagination_params(
        self, endpoint: str, expected_params: dict[str, str]
    ) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200)
        with mock.patch(SENDGRID_SESSION_PATCH, return_value=session):
            get_endpoint_permissions("k", [endpoint])

        url = session.get.call_args[0][0]
        assert parse_qs(urlparse(url).query) == {key: [value] for key, value in expected_params.items()}
