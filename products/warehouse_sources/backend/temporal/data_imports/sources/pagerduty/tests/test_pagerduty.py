import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.pagerduty import (
    PAGE_SIZE,
    PagerDutyResumeConfig,
    _format_incremental_value,
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


def _error_response(status_code: int, *, path: str = "/incidents", body: Optional[dict[str, Any]] = None) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body if body is not None else {"error": {"message": "boom"}}).encode()
    resp.url = f"https://api.pagerduty.com{path}"
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


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_stops_iteration(self, MockSession) -> None:
        session = MockSession.return_value
        # more=True but no items — a missing/empty envelope must stop rather than loop forever.
        _wire(session, [_response([], more=True)])

        rows = _rows(
            pagerduty_source(
                "tok",
                "incidents",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                logger=mock.MagicMock(),
            )
        )
        assert rows == []
        assert session.send.call_count == 1

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

        _rows(
            pagerduty_source(
                "tok",
                "incidents",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                logger=mock.MagicMock(),
            )
        )
        assert offsets[0] == 0
        assert offsets[-1] == 9900
        assert 10000 not in offsets


class TestResume:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": "x"}], more=False)])

        manager = _make_manager(PagerDutyResumeConfig(offset=PAGE_SIZE))
        _rows(
            pagerduty_source(
                "tok", "incidents", team_id=1, job_id="j", resumable_source_manager=manager, logger=mock.MagicMock()
            )
        )
        assert params[0]["offset"] == PAGE_SIZE


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
                logger=mock.MagicMock(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        assert params[0]["sort_by"] == "created_at:asc"
        assert params[0]["since"] == "2026-01-01T00:00:00+00:00"


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


class TestPlanGatedEndpoints:
    @pytest.mark.parametrize(
        "endpoint,status_code,body,feature",
        [
            # The statuses PagerDuty answers on an account whose plan lacks the feature. The 402
            # body keeps PagerDuty's documented error code 2014, which the client appends to the
            # raised message as "api error: code=2014".
            ("teams", 402, {"error": {"code": 2014, "message": "Required abilities are unavailable"}}, "teams"),
            ("priorities", 404, {"error": {"message": "Not Found"}}, "incident priorities"),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_plan_gated_endpoint_syncs_no_rows_and_warns(
        self, MockSession, endpoint: str, status_code: int, body: dict[str, Any], feature: str
    ) -> None:
        session = MockSession.return_value
        path = PAGERDUTY_ENDPOINTS[endpoint].path
        _wire(session, [_error_response(status_code, path=path, body=body)])
        logger = mock.MagicMock()

        rows = _rows(
            pagerduty_source(
                "tok", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager(), logger=logger
            )
        )
        assert rows == []
        warning = logger.warning.call_args.args[0]
        assert f"does not include {feature}" in warning
        assert f"the {endpoint} table synced no rows" in warning

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_ungated_endpoint_still_fails_on_404(self, MockSession) -> None:
        # Only endpoints declaring a plan-gated feature swallow a 404; elsewhere it is a real
        # failure the sync must surface.
        session = MockSession.return_value
        _wire(session, [_error_response(404, path="/users")])

        with pytest.raises(HTTPError):
            _rows(
                pagerduty_source(
                    "tok",
                    "users",
                    team_id=1,
                    job_id="j",
                    resumable_source_manager=_make_manager(),
                    logger=mock.MagicMock(),
                )
            )

    @pytest.mark.parametrize("status_code", [401, 403])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_plan_gated_endpoint_still_fails_on_other_statuses(self, MockSession, status_code: int) -> None:
        # Only 402 and 404 mean "your plan does not include this"; a credential problem on a gated
        # endpoint must still fail rather than be reported as an empty table.
        session = MockSession.return_value
        _wire(session, [_error_response(status_code, path="/teams")])
        logger = mock.MagicMock()

        with pytest.raises(HTTPError):
            _rows(
                pagerduty_source(
                    "tok", "teams", team_id=1, job_id="j", resumable_source_manager=_make_manager(), logger=logger
                )
            )
        logger.warning.assert_not_called()

    @pytest.mark.parametrize(
        "endpoint,wrong_status",
        [
            # teams is plan-gated at 402, not 404; priorities is plan-gated at 404, not 402. The
            # gated status is endpoint-specific, so the other status on that same endpoint is a
            # genuine failure and must still raise rather than being read as "plan lacks it".
            ("teams", 404),
            ("priorities", 402),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_plan_gated_endpoint_fails_on_the_other_endpoints_gated_status(
        self, MockSession, endpoint: str, wrong_status: int
    ) -> None:
        session = MockSession.return_value
        path = PAGERDUTY_ENDPOINTS[endpoint].path
        _wire(session, [_error_response(wrong_status, path=path)])
        logger = mock.MagicMock()

        with pytest.raises(HTTPError):
            _rows(
                pagerduty_source(
                    "tok", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager(), logger=logger
                )
            )
        logger.warning.assert_not_called()
