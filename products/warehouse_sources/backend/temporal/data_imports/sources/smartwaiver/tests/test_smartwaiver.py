import json
from datetime import UTC, date, datetime
from typing import Any

from freezegun import freeze_time
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.smartwaiver import (
    CHECKINS_MAX_OFFSET,
    PAGE_SIZE,
    SmartwaiverResumeConfig,
    _clamp_before_current_hour,
    _format_dts,
    smartwaiver_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the smartwaiver module.
SMARTWAIVER_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.smartwaiver.make_tracked_session"
)

_NOW = datetime(2026, 7, 8, 15, 42, 30, tzinfo=UTC)
# `fromDts` must not be within the current hour, so recent cursors clamp to 14:59:59.
_HOUR_BOUNDARY = "2026-07-08T14:59:59"


def _response(body: dict[str, Any]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _waiver_body(ids: list[str]) -> dict[str, Any]:
    return {"type": "waivers", "waivers": [{"waiverId": i} for i in ids]}


def _checkin_body(ids: list[int], more: bool) -> dict[str, Any]:
    return {
        "type": "checkins",
        "checkins": {"moreCheckins": more, "checkins": [{"checkinId": i, "position": 0} for i in ids]},
    }


def _make_manager(resume_state: SmartwaiverResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list capturing each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared instead of inspecting it after the run.
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


def _source(session_mock: mock.MagicMock, responses: list[Response], **kwargs: Any) -> Any:
    session = session_mock.return_value
    params = _wire(session, responses)
    manager = kwargs.pop("manager", None) or _make_manager()
    source = smartwaiver_source(api_key="key", team_id=1, job_id="j", resumable_source_manager=manager, **kwargs)
    return source, params, manager


class TestFormatDts:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00"),
            # Smartwaiver responses carry naive space-separated timestamps; they must round-trip
            # into the `T`-separated form the API accepts for `fromDts`.
            ("api_response_string", "2018-01-01 12:32:16", "2018-01-01T12:32:16"),
            ("iso_string", "2018-01-01T12:32:16", "2018-01-01T12:32:16"),
            ("unparseable_string_passthrough", "not-a-date", "not-a-date"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_dts(value) == expected


class TestClampBeforeCurrentHour:
    @parameterized.expand(
        [
            ("old_value_untouched", "2026-01-01 10:00:00", "2026-01-01T10:00:00"),
            ("within_current_hour_clamped", "2026-07-08 15:30:00", _HOUR_BOUNDARY),
            ("future_value_clamped", datetime(2026, 7, 9, 1, 0, 0, tzinfo=UTC), _HOUR_BOUNDARY),
        ]
    )
    def test_clamp(self, _name: str, value: Any, expected: str) -> None:
        assert _clamp_before_current_hour(value, _NOW) == expected


class TestWaivers:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_partial_page(self, MockSession) -> None:
        full_page = [str(i) for i in range(PAGE_SIZE)]
        source, params, manager = _source(
            MockSession,
            [_response(_waiver_body(full_page)), _response(_waiver_body(["last"]))],
            endpoint="waivers",
        )
        rows = _rows(source)

        assert len(rows) == PAGE_SIZE + 1
        # A partial (short) page ends pagination without an extra empty-page request.
        assert MockSession.return_value.send.call_count == 2
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == PAGE_SIZE
        assert params[1]["offset"] == 1
        # State saved only while more pages may remain, never on the final partial page.
        assert manager.save_state.call_count == 1
        assert manager.save_state.call_args.args[0] == SmartwaiverResumeConfig(next_offset=1, from_dts=None)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_second_page_ends_pagination(self, MockSession) -> None:
        full_page = [str(i) for i in range(PAGE_SIZE)]
        source, _params, manager = _source(
            MockSession,
            [_response(_waiver_body(full_page)), _response(_waiver_body([]))],
            endpoint="waivers",
        )
        _rows(source)

        assert manager.save_state.call_count == 1
        assert manager.save_state.call_args.args[0] == SmartwaiverResumeConfig(next_offset=1, from_dts=None)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset_and_window(self, MockSession) -> None:
        manager = _make_manager(SmartwaiverResumeConfig(next_offset=3, from_dts="2026-01-01T00:00:00"))
        source, params, _manager = _source(
            MockSession, [_response(_waiver_body(["w1"]))], endpoint="waivers", manager=manager
        )
        rows = _rows(source)

        assert [r["waiverId"] for r in rows] == ["w1"]
        assert params[0]["offset"] == 3
        assert params[0]["fromDts"] == "2026-01-01T00:00:00"

    @parameterized.expand(
        [
            # Old cursor is left untouched (already before the current hour).
            ("old_cursor", "2026-01-01 10:00:00", "2026-01-01T10:00:00"),
            # A cursor within the current hour clamps to the hour boundary.
            ("within_current_hour", "2026-07-08 15:30:00", _HOUR_BOUNDARY),
        ]
    )
    @freeze_time(_NOW)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_cursor_added_and_clamped(self, _name, cursor, expected, MockSession) -> None:
        source, params, _manager = _source(
            MockSession,
            [_response(_waiver_body(["w1"]))],
            endpoint="waivers",
            should_use_incremental_field=True,
            db_incremental_field_last_value=cursor,
        )
        _rows(source)
        assert params[0]["fromDts"] == expected

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_omits_time_filter(self, MockSession) -> None:
        source, params, _manager = _source(MockSession, [_response(_waiver_body(["w1"]))], endpoint="waivers")
        _rows(source)
        assert "fromDts" not in params[0]


class TestCheckins:
    @freeze_time(_NOW)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_sync_uses_default_window(self, MockSession) -> None:
        source, params, _manager = _source(
            MockSession, [_response(_checkin_body([1], more=False))], endpoint="checkins"
        )
        rows = _rows(source)

        assert [r["checkinId"] for r in rows] == [1]
        # Both bounds are required by the API: an old default lower bound and an upper bound
        # strictly before the current hour.
        assert params[0]["fromDts"] == "2000-01-01T00:00:00"
        assert params[0]["toDts"] == _HOUR_BOUNDARY
        assert params[0]["limit"] == PAGE_SIZE
        assert params[0]["offset"] == 0

    @freeze_time(_NOW)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_sync_starts_window_at_watermark(self, MockSession) -> None:
        source, params, _manager = _source(
            MockSession,
            [_response(_checkin_body([1], more=False))],
            endpoint="checkins",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-06-01 08:00:00",
        )
        _rows(source)
        assert params[0]["fromDts"] == "2026-06-01T08:00:00"
        assert params[0]["toDts"] == _HOUR_BOUNDARY

    @freeze_time(_NOW)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_while_more_checkins_and_saves_state(self, MockSession) -> None:
        source, params, manager = _source(
            MockSession,
            [_response(_checkin_body([1], more=True)), _response(_checkin_body([2], more=False))],
            endpoint="checkins",
        )
        rows = _rows(source)

        assert [r["checkinId"] for r in rows] == [1, 2]
        assert params[0]["offset"] == 0
        assert params[1]["offset"] == 1
        assert manager.save_state.call_count == 1
        assert manager.save_state.call_args.args[0] == SmartwaiverResumeConfig(
            next_offset=1, from_dts="2000-01-01T00:00:00", to_dts=_HOUR_BOUNDARY
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_at_offset_cap(self, MockSession) -> None:
        # A window with more results past the API's offset cap must terminate, not loop, and must
        # not persist a resume state past the cap.
        manager = _make_manager(
            SmartwaiverResumeConfig(
                next_offset=CHECKINS_MAX_OFFSET, from_dts="2000-01-01T00:00:00", to_dts=_HOUR_BOUNDARY
            )
        )
        source, params, _manager = _source(
            MockSession, [_response(_checkin_body([1], more=True))], endpoint="checkins", manager=manager
        )
        rows = _rows(source)

        assert [r["checkinId"] for r in rows] == [1]
        assert MockSession.return_value.send.call_count == 1
        assert params[0]["offset"] == CHECKINS_MAX_OFFSET
        manager.save_state.assert_not_called()


class TestTemplates:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_fetch_yields_templates(self, MockSession) -> None:
        body = {"type": "templates", "templates": [{"templateId": "t1"}, {"templateId": "t2"}]}
        source, _params, _manager = _source(MockSession, [_response(body)], endpoint="templates")
        rows = _rows(source)

        assert [r["templateId"] for r in rows] == ["t1", "t2"]
        assert MockSession.return_value.send.call_count == 1


class TestSmartwaiverSourceResponse:
    @parameterized.expand(
        [
            ("templates", ["templateId"], None),
            ("waivers", ["waiverId"], ["createdOn"]),
            ("checkins", ["checkinId", "position"], ["date"]),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_keys_and_partitioning(
        self, endpoint: str, expected_pks: list[str], expected_partition_keys: list[str] | None, MockSession
    ) -> None:
        response = smartwaiver_source(
            api_key="key",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        assert response.partition_keys == expected_partition_keys
        # List order is undocumented, so the watermark must only advance on completed syncs.
        assert response.sort_mode == "desc"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, True, None),
            ("unauthorized", 401, False, "Invalid Smartwaiver API key"),
            ("forbidden", 403, False, "Invalid Smartwaiver API key"),
            ("server_error", 500, False, "Smartwaiver returned HTTP 500"),
        ]
    )
    @mock.patch(SMARTWAIVER_SESSION_PATCH)
    def test_status_mapping(
        self, _name: str, status: int, expected_valid: bool, expected_message: str | None, mock_session
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        is_valid, message = validate_credentials("key")
        assert is_valid is expected_valid
        assert message == expected_message

    @mock.patch(SMARTWAIVER_SESSION_PATCH)
    def test_connection_error_is_not_validated(self, mock_session) -> None:
        # A probe that raises (transport error) must never bubble out of validate_credentials.
        mock_session.return_value.get.side_effect = Exception("boom")
        is_valid, message = validate_credentials("key")
        assert is_valid is False
        assert message == "Could not validate Smartwaiver API key"
