import json
from typing import Any, Optional

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.jobnimbus.jobnimbus import (
    PAGE_SIZE,
    JobNimbusResumeConfig,
    jobnimbus_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jobnimbus.settings import (
    ENDPOINTS,
    JOBNIMBUS_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the jobnimbus module.
JOBNIMBUS_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.jobnimbus.jobnimbus.make_tracked_session"
)
# tenacity sleeps between retries; patch it so the retry-path tests don't actually wait.
TENACITY_SLEEP_PATCH = "tenacity.nap.time.sleep"


def _raw_response(body: Any, *, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = "https://app.jobnimbus.com/api1/contacts"
    resp._content = b"" if body is None else json.dumps(body).encode()
    return resp


def _response(results: list[dict[str, Any]], count: int, *, status: int = 200) -> Response:
    return _raw_response({"count": count, "results": results}, status=status)


def _make_manager(resume_state: Optional[JobNimbusResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so inspecting it after the run shows
    only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _source(manager: mock.MagicMock, endpoint: str = "contacts") -> Any:
    return jobnimbus_source(
        api_key="jn-key",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_progresses_offset(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        full = [{"jnid": str(i)} for i in range(PAGE_SIZE)]
        params = _wire(session, [_response(full, PAGE_SIZE + 1), _response([{"jnid": "last"}], PAGE_SIZE + 1)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert [r["jnid"] for r in rows] == [*(str(i) for i in range(PAGE_SIZE)), "last"]
        # size/from map onto the offset paginator's limit/offset params.
        assert params[0] == {"from": 0, "size": PAGE_SIZE}
        assert params[1]["from"] == PAGE_SIZE
        # Checkpoint saved once after the first full page (points at the next page); short page ends it.
        manager.save_state.assert_called_once_with(JobNimbusResumeConfig(offset=PAGE_SIZE))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_first_page_one_request_and_no_checkpoint(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"jnid": "a"}, {"jnid": "b"}], 2)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert [r["jnid"] for r in rows] == ["a", "b"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_when_offset_reaches_reported_count(self, MockSession: mock.MagicMock) -> None:
        # A full page whose length exactly equals the reported total must terminate without a second
        # request, even though the page isn't short — the `count` total drives the stop.
        session = MockSession.return_value
        full = [{"jnid": str(i)} for i in range(PAGE_SIZE)]
        _wire(session, [_response(full, PAGE_SIZE)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert len(rows) == PAGE_SIZE
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"jnid": "x"}], PAGE_SIZE + 1)])

        # Offset 0 must never be fetched on resume.
        manager = _make_manager(JobNimbusResumeConfig(offset=PAGE_SIZE))
        _rows(_source(manager))

        assert params[0]["from"] == PAGE_SIZE

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], 0)])

        manager = _make_manager()
        rows = _rows(_source(manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(TENACITY_SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried_then_succeeds(
        self, _name: str, status: int, MockSession: mock.MagicMock, _sleep: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        _wire(session, [_raw_response(None, status=status), _response([{"jnid": "ok"}], 1)])

        rows = _rows(_source(_make_manager()))

        assert [r["jnid"] for r in rows] == ["ok"]
        # The first (retryable) response is reissued, so the successful page needs a second send.
        assert session.send.call_count == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_status_raises(self, _name: str, status: int, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_raw_response(None, status=status)])

        with pytest.raises(HTTPError):
            _rows(_source(_make_manager()))

    @parameterized.expand(
        [
            ("missing_results_key", {"count": 0}),
            ("bare_list_body", [{"jnid": "1"}]),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_shape_change_fails_loud(self, _name: str, body: Any, MockSession: mock.MagicMock) -> None:
        # A 200 body without a `results` list means the response shape changed — fail loud instead of
        # silently syncing 0 rows or wrapping a stray object as a row.
        session = MockSession.return_value
        _wire(session, [_raw_response(body)])

        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source(_make_manager()))


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid JobNimbus API key"),
            ("forbidden", 403, False, "Invalid JobNimbus API key"),
            ("server_error", 500, False, "JobNimbus returned HTTP 500"),
        ]
    )
    @mock.patch(JOBNIMBUS_SESSION_PATCH)
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: mock.MagicMock,
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("jn-key") == (expected_valid, expected_message)

    @mock.patch(JOBNIMBUS_SESSION_PATCH)
    def test_probe_failure_is_not_validated(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("jn-key") == (False, "Could not validate JobNimbus API key")


class TestSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, _MockSession: mock.MagicMock) -> None:
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.name == endpoint
        assert response.primary_keys == ["jnid"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_jnid_primary_key(self) -> None:
        assert all(config.primary_keys == ["jnid"] for config in JOBNIMBUS_ENDPOINTS.values())
        assert set(JOBNIMBUS_ENDPOINTS) == set(ENDPOINTS)
