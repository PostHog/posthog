import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.pagerduty import (
    PAGE_SIZE,
    PagerDutyResumeConfig,
    _format_incremental_value,
    _get_headers,
    pagerduty_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.settings import PAGERDUTY_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the pagerduty module.
PAGERDUTY_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.pagerduty.make_tracked_session"
)


def _response(items: Optional[list[dict[str, Any]]], *, more: bool = False, envelope: str = "incidents") -> Response:
    body: dict[str, Any] = {"more": more}
    if items is not None:
        body[envelope] = items
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    resp.url = "https://api.pagerduty.com/incidents"
    return resp


def _error_response(status_code: int) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps({"error": {"message": "boom"}}).encode()
    resp.url = "https://api.pagerduty.com/incidents"
    return resp


def _make_manager(resume_state: Optional[PagerDutyResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
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


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            (date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("already-a-cursor", "already-a-cursor"),
        ],
    )
    def test_format(self, value: Any, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestHeaders:
    def test_token_auth_header(self) -> None:
        headers = _get_headers("tok_abc")
        assert headers["Authorization"] == "Token token=tok_abc"
        assert headers["Accept"] == "application/vnd.pagerduty+json;version=2"


class TestAuth:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_token_sent_as_pagerduty_authorization_header(self, MockSession) -> None:
        # The framework auth config must reproduce PagerDuty's `Token token=<key>` scheme.
        session = MockSession.return_value
        captured: dict[str, Any] = {}

        def _prepare(request: Any) -> mock.MagicMock:
            request.auth(request)
            captured["auth"] = request.headers.get("Authorization")
            return mock.MagicMock()

        session.headers = {}
        session.prepare_request.side_effect = _prepare
        session.send.side_effect = [_response([{"id": "1"}], more=False)]

        _rows(pagerduty_source("tok_abc", "incidents", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert captured["auth"] == "Token token=tok_abc"


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_yields_rows(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "1"}, {"id": "2"}], more=True),
                _response([{"id": "3"}], more=False),
            ],
        )

        rows = _rows(
            pagerduty_source("tok", "incidents", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )
        assert [r["id"] for r in rows] == ["1", "2", "3"]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_advances_offset_between_pages(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _response([{"id": "1"}], more=True),
                _response([{"id": "2"}], more=False),
            ],
        )

        _rows(pagerduty_source("tok", "incidents", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert params[0]["offset"] == 0
        assert params[0]["limit"] == PAGE_SIZE
        assert params[1]["offset"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_more_flag_drives_continuation_regardless_of_page_size(self, MockSession) -> None:
        # A short page (1 item) with more=True must still continue — PagerDuty's `more` boolean,
        # not page fullness, is the authoritative "another page" signal.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "1"}], more=True),
                _response([{"id": "2"}], more=False),
            ],
        )

        rows = _rows(
            pagerduty_source("tok", "incidents", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )
        assert [r["id"] for r in rows] == ["1", "2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_more_false_stops(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "1"}], more=False)])

        rows = _rows(
            pagerduty_source("tok", "incidents", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )
        assert [r["id"] for r in rows] == ["1"]
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_stops_iteration(self, MockSession) -> None:
        session = MockSession.return_value
        # more=True but no items — a missing/empty envelope must stop rather than loop forever.
        _wire(session, [_response([], more=True)])

        rows = _rows(
            pagerduty_source("tok", "incidents", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )
        assert rows == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_envelope_key_stops_without_error(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, more=True)])

        rows = _rows(
            pagerduty_source("tok", "incidents", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )
        assert rows == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_uses_envelope_key_per_endpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": "svc_1"}], more=False, envelope="services")])

        rows = _rows(
            pagerduty_source("tok", "services", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )
        assert [r["id"] for r in rows] == ["svc_1"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_before_crossing_max_offset(self, MockSession) -> None:
        # PagerDuty 400s when offset + limit exceeds 10000. Full pages that always report more=True
        # must stop before requesting offset=10000 (the first page whose offset+limit would exceed).
        session = MockSession.return_value
        session.headers = {}
        offsets: list[int] = []

        def _prepare(request: Any) -> mock.MagicMock:
            offsets.append(request.params["offset"])
            return mock.MagicMock()

        session.prepare_request.side_effect = _prepare
        # Always more=True — only the offset ceiling can stop it.
        session.send.side_effect = [_response([{"id": str(i)}], more=True) for i in range(200)]

        _rows(pagerduty_source("tok", "incidents", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert offsets[0] == 0
        assert offsets[-1] == 9900
        assert 10000 not in offsets


class TestResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "x"}], more=False)])

        manager = _make_manager(PagerDutyResumeConfig(offset=PAGE_SIZE))
        _rows(pagerduty_source("tok", "incidents", team_id=1, job_id="j", resumable_source_manager=manager))
        assert params[0]["offset"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoints_next_offset_after_each_continued_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "1"}], more=True),
                _response([{"id": "2"}], more=False),
            ],
        )

        manager = _make_manager()
        _rows(pagerduty_source("tok", "incidents", team_id=1, job_id="j", resumable_source_manager=manager))
        # Checkpoint saved once (next offset) after the first page; the final page (more=False) saves nothing.
        saved = [c.args[0] for c in manager.save_state.call_args_list]
        assert saved == [PagerDutyResumeConfig(offset=PAGE_SIZE)]


class TestIncremental:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_endpoint_sends_since_and_sort(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "1"}], more=False)])

        _rows(
            pagerduty_source(
                "tok",
                "incidents",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        assert params[0]["sort_by"] == "created_at:asc"
        assert params[0]["since"] == "2026-01-01T00:00:00+00:00"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_endpoint_without_watermark_omits_since(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "1"}], more=False)])

        _rows(
            pagerduty_source(
                "tok",
                "incidents",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=None,
            )
        )
        assert params[0]["sort_by"] == "created_at:asc"
        assert "since" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_incremental_endpoint_sends_stable_sort_only(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "1"}], more=False)])

        _rows(pagerduty_source("tok", "incidents", team_id=1, job_id="j", resumable_source_manager=_make_manager()))
        assert params[0]["sort_by"] == "created_at:asc"
        assert "since" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_incremental_endpoint_has_no_sort_or_since(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "1"}], more=False, envelope="users")])

        _rows(
            pagerduty_source(
                "tok",
                "users",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        assert "sort_by" not in params[0]
        assert "since" not in params[0]


class TestRetries:
    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_on_429_then_succeeds(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(429), _response([{"id": "1"}], more=False)])

        rows = _rows(
            pagerduty_source("tok", "incidents", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )
        assert [r["id"] for r in rows] == ["1"]
        assert session.send.call_count == 2

    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retries_on_500_then_succeeds(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(500), _response([{"id": "1"}], more=False)])

        rows = _rows(
            pagerduty_source("tok", "incidents", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        )
        assert [r["id"] for r in rows] == ["1"]
        assert session.send.call_count == 2


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_ok,expected_status",
        [
            (200, True, 200),
            (401, False, 401),
            (403, False, 403),
            (500, False, 500),
        ],
    )
    def test_status_mapping(self, status_code: int, expected_ok: bool, expected_status: int) -> None:
        with mock.patch(PAGERDUTY_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
            ok, status, _error = validate_credentials("tok")
        assert ok is expected_ok
        assert status == expected_status

    def test_transport_failure_returns_zero_status(self) -> None:
        with mock.patch(PAGERDUTY_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.side_effect = Exception("no network")
            ok, status, error = validate_credentials("tok")
        assert ok is False
        assert status == 0
        assert error is not None

    def test_custom_messages_per_status(self) -> None:
        with mock.patch(PAGERDUTY_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=401)
            assert validate_credentials("tok")[2] == "Invalid PagerDuty API key"
        with mock.patch(PAGERDUTY_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=403)
            assert validate_credentials("tok")[2] == "Your PagerDuty API key does not have access to this resource"

    def test_uses_endpoint_path_when_schema_given(self) -> None:
        with mock.patch(PAGERDUTY_SESSION_PATCH) as mock_session:
            mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
            validate_credentials("tok", endpoint="incidents")
            called_url = mock_session.return_value.get.call_args.args[0]
        assert called_url.startswith("https://api.pagerduty.com/incidents?")


class TestPagerDutySourceResponse:
    def test_incidents_partitioned_on_created_at(self) -> None:
        response = pagerduty_source("tok", "incidents", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["created_at"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "week"
        assert response.sort_mode == "asc"

    def test_unpartitioned_endpoint_has_no_partition_settings(self) -> None:
        response = pagerduty_source("tok", "users", team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.primary_keys == ["id"]
        assert response.partition_keys is None
        assert response.partition_mode is None

    @pytest.mark.parametrize("endpoint", list(PAGERDUTY_ENDPOINTS.keys()))
    def test_every_endpoint_builds_a_response(self, endpoint: str) -> None:
        response = pagerduty_source("tok", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())
        assert response.name == endpoint
        assert response.primary_keys == [PAGERDUTY_ENDPOINTS[endpoint].primary_key]
        assert callable(response.items)
