import json
from typing import Any, Optional

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.workiz.settings import PAGE_SIZE
from products.warehouse_sources.backend.temporal.data_imports.sources.workiz.workiz import (
    WorkizResumeConfig,
    get_resource,
    validate_credentials,
    workiz_source,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the workiz module.
WORKIZ_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.workiz.workiz.make_tracked_session"
)
TENACITY_SLEEP_PATCH = "tenacity.nap.time.sleep"


def _raw_response(body: Any, *, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = "https://api.workiz.com/api/v1/tok/job/all/"
    resp._content = b"" if body is None else json.dumps(body).encode()
    return resp


def _job(uuid: str) -> dict[str, Any]:
    return {"flag": True, "data": {"UUID": uuid, "Status": "Submitted"}}


def _make_manager(resume_state: Optional[WorkizResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    `request.params` is one dict mutated in place across pages, so inspecting it after the run
    shows only the final state -- snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(
    manager: mock.MagicMock,
    endpoint: str = "Leads",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> Any:
    return workiz_source(
        api_token="tok",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        incremental_field=incremental_field,
    )


def _rows(resource: Any) -> list[dict[str, Any]]:
    return [row for page in resource for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_progresses_offset(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        full_page = [{"UUID": str(i)} for i in range(PAGE_SIZE)]
        params = _wire(
            session,
            [
                _raw_response(full_page),
                _raw_response([{"UUID": "last"}]),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert [r["UUID"] for r in rows] == [*(str(i) for i in range(PAGE_SIZE)), "last"]
        assert params[0]["offset"] == 0
        assert params[0]["records"] == PAGE_SIZE
        assert params[1]["offset"] == PAGE_SIZE
        manager.save_state.assert_called_once_with(WorkizResumeConfig(offset=PAGE_SIZE))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_one_request_and_no_checkpoint(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_raw_response([{"UUID": "a"}, {"UUID": "b"}])])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert [r["UUID"] for r in rows] == ["a", "b"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_raw_response([{"UUID": "x"}])])

        manager = _make_manager(WorkizResumeConfig(offset=PAGE_SIZE))
        _rows(_source(manager))

        assert params[0]["offset"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_raw_response([])])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @parameterized.expand([("Team",), ("TimeOff",)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unpaginated_endpoints_send_one_request_with_no_offset(
        self, endpoint: str, MockSession: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        params = _wire(session, [_raw_response([{"id": "1"}])])

        rows = _rows(_source(_make_manager(), endpoint=endpoint))

        assert len(rows) == 1
        assert session.send.call_count == 1
        assert "offset" not in params[0]
        assert "records" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_jobs_unwraps_flag_data_wrapper(self, MockSession: mock.MagicMock) -> None:
        # Workiz's OpenAPI spec wraps each job/all item as {"flag": bool, "data": Job}.
        session = MockSession.return_value
        _wire(session, [_raw_response([_job("a"), _job("b")])])

        rows = _rows(_source(_make_manager(), endpoint="Jobs"))

        assert [r["UUID"] for r in rows] == ["a", "b"]
        assert all("flag" not in r and "data" not in r for r in rows)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_leads_are_not_wrapped(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_raw_response([{"UUID": "a"}])])

        rows = _rows(_source(_make_manager(), endpoint="Leads"))

        assert rows == [{"UUID": "a"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_session_excludes_responses_from_sample_capture(self, MockSession: mock.MagicMock) -> None:
        # Jobs/Leads rows carry customer PII (contact details, addresses, job comments) the
        # name-based sample scrubbers aren't built to catch, so the client must opt the sync
        # session out of HTTP diagnostic sample capture entirely.
        session = MockSession.return_value
        _wire(session, [_raw_response([])])

        _rows(_source(_make_manager()))

        assert MockSession.call_args.kwargs["capture"] is False


class TestIncrementalParams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_incremental_sync_anchors_to_earliest_date(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_raw_response([])])

        _rows(_source(_make_manager(), should_use_incremental_field=True, db_incremental_field_last_value=None))

        assert params[0]["start_date"] == "2010-01-01"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_also_anchors_to_earliest_date(self, MockSession: mock.MagicMock) -> None:
        # Omitting start_date makes the vendor API default to the last 14 days -- a full-refresh
        # sync must still pass an explicit far-past anchor to get the whole table.
        session = MockSession.return_value
        params = _wire(session, [_raw_response([])])

        _rows(_source(_make_manager(), should_use_incremental_field=False))

        assert params[0]["start_date"] == "2010-01-01"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_sync_uses_last_synced_date(self, MockSession: mock.MagicMock) -> None:
        import datetime

        session = MockSession.return_value
        params = _wire(session, [_raw_response([])])

        _rows(
            _source(
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime.datetime(2024, 3, 15, 9, 0, 0),
            )
        )

        assert params[0]["start_date"] == "2024-03-15"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_only_open_and_records_are_always_sent(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_raw_response([])])

        _rows(_source(_make_manager()))

        assert params[0]["only_open"] == "false"
        assert params[0]["records"] == PAGE_SIZE

    @parameterized.expand([("Team",), ("TimeOff",)])
    def test_unpaginated_endpoints_have_no_start_date_param(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=False, incremental_field=None)
        resource_endpoint = resource["endpoint"]
        assert isinstance(resource_endpoint, dict)
        assert resource_endpoint.get("params") is None


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(TENACITY_SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried_then_succeeds(
        self, _name: str, status: int, MockSession: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_raw_response(None, status=status), _raw_response([{"UUID": "ok"}])])

        rows = _rows(_source(_make_manager()))

        assert [r["UUID"] for r in rows] == ["ok"]
        assert session.send.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_status_raises(self, _name: str, status: int, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_raw_response(None, status=status)])

        with pytest.raises(HTTPError):
            _rows(_source(_make_manager()))


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            (
                "unauthorized",
                401,
                False,
                "Invalid API token. Check Settings > Integrations > Developer in Workiz and try again.",
            ),
            (
                "forbidden",
                403,
                False,
                "Invalid API token. Check Settings > Integrations > Developer in Workiz and try again.",
            ),
            ("server_error", 500, False, "Workiz returned HTTP 500."),
        ]
    )
    @mock.patch(WORKIZ_SESSION_PATCH)
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: mock.MagicMock,
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("tok") == (expected_valid, expected_message)

    @mock.patch(WORKIZ_SESSION_PATCH)
    def test_probe_failure_is_not_validated(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("tok") == (False, "Could not reach Workiz to validate the API token.")

    @mock.patch(WORKIZ_SESSION_PATCH)
    def test_probe_session_excludes_response_from_sample_capture(self, mock_session: mock.MagicMock) -> None:
        # The probe response is a team-member list -- same PII concern as the sync client.
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("tok")
        assert mock_session.call_args.kwargs["capture"] is False
