import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.culture_amp import (
    CultureAmpResumeConfig,
    _format_timestamp,
    culture_amp_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.settings import (
    CULTURE_AMP_ENDPOINTS,
    ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# OAuth2Auth mints tokens through its own tracked session in the auth module.
AUTH_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth.make_tracked_session"
)
# validate_credentials probes through a tracked session built in the culture_amp module.
PROBE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.culture_amp.make_tracked_session"
)

DEMOGRAPHICS_PATH = "employees/{employee_id}/demographics"


def _response(payload: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(payload).encode()
    resp.url = "https://api.cultureamp.com/v1/test"
    return resp


def _page(rows: list[dict[str, Any]], after_key: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"data": rows}
    if after_key:
        body["pagination"] = {"afterKey": after_key, "nextPath": f"/v1/x?cursor={after_key}"}
    return body


def _token_response(expires_in: int = 3599) -> mock.MagicMock:
    # OAuth2Auth reads the token exchange body via response.raw.read (stream=True).
    resp = mock.MagicMock()
    resp.status_code = 200
    resp.raw.read.return_value = json.dumps(
        {"access_token": "tok-1", "expires_in": expires_in, "token_type": "Bearer"}
    ).encode()
    return resp


def _make_manager(resume_state: CultureAmpResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock RESTClient session and snapshot each request AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead. A real
    ``requests.Session`` does the preparing so the OAuth2 auth (token mint + Bearer header) is
    actually applied, letting tests assert on the minted Authorization header and the request URLs.
    """
    session.headers = {}
    real_session = requests.Session()
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> requests.PreparedRequest:
        prepared = real_session.prepare_request(request)
        snapshots.append({"params": dict(request.params or {}), "url": prepared.url, "headers": dict(prepared.headers)})
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(
    endpoint: str,
    manager: mock.MagicMock,
    *,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
):
    return culture_amp_source(
        client_id="cid",
        client_secret="sec",
        account_id="entity-1",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


class TestFormatTimestamp:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        ],
    )
    def test_formats(self, value, expected):
        assert _format_timestamp(value) == expected


class TestValidateCredentials:
    @mock.patch(PROBE_SESSION_PATCH)
    def test_invalid_on_exception(self, mock_session):
        # A failed token mint (bad credentials) raises out of the auth callable during the probe.
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("cid", "bad", "entity-1") is False


class TestCursorEndpoints:
    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follow_after_key_until_absent(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        snapshots = _wire(
            session,
            [
                _response(_page([{"id": "e1"}], after_key="k1")),
                _response(_page([{"id": "e2"}])),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("employees", manager))

        assert [row["id"] for row in rows] == ["e1", "e2"]
        assert "cursor" not in snapshots[0]["params"]
        assert snapshots[1]["params"]["cursor"] == "k1"
        # State saved only while a next page remains, after the batch is yielded.
        assert [call.args[0].cursor for call in manager.save_state.call_args_list] == ["k1"]

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_passes_after_date(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        snapshots = _wire(session, [_response(_page([]))])

        _rows(
            _source(
                "performance_cycles",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["after_date"] == "2024-01-02T03:04:05Z"

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        snapshots = _wire(session, [_response(_page([{"managerReviewId": "r9"}]))])

        manager = _make_manager(CultureAmpResumeConfig(cursor="k9"))
        _rows(_source("manager_reviews", manager))

        assert snapshots[0]["params"]["cursor"] == "k9"

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_4xx_raises_immediately(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        _wire(session, [_response({}, status_code=400)])

        with pytest.raises(requests.HTTPError):
            _rows(_source("employees", _make_manager()))

        assert session.send.call_count == 1


class TestEmployeeDemographicsFanOut:
    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_per_employee_and_injects_employee_id(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        snapshots = _wire(
            session,
            [
                _response(_page([{"id": "e1"}, {"id": "e2"}])),
                _response(_page([{"name": "department", "value": "eng"}])),
                _response(_page([{"name": "department", "value": "sales"}])),
            ],
        )

        rows = _rows(_source("employee_demographics", _make_manager()))

        assert [(r["_employee_id"], r["value"]) for r in rows] == [("e1", "eng"), ("e2", "sales")]
        # The framework's include_from_parent key is renamed away — rows keep their old shape.
        assert all("_employees_id" not in r for r in rows)
        urls = [s["url"] for s in snapshots]
        assert urls[0] == "https://api.cultureamp.com/v1/employees"
        assert urls[1] == "https://api.cultureamp.com/v1/employees/e1/demographics"
        assert urls[2] == "https://api.cultureamp.com/v1/employees/e2/demographics"

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_fanout_state(self, MockSession, MockAuth):
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        snapshots = _wire(
            session,
            [
                _response(_page([{"id": "e1"}, {"id": "e2"}])),
                _response(_page([{"name": "department", "value": "sales"}])),
            ],
        )

        manager = _make_manager(
            CultureAmpResumeConfig(fanout_state={"completed": [DEMOGRAPHICS_PATH.format(employee_id="e1")]})
        )
        rows = _rows(_source("employee_demographics", manager))

        assert [r["_employee_id"] for r in rows] == ["e2"]
        assert len(snapshots) == 2
        assert snapshots[1]["url"].endswith("/employees/e2/demographics")

    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_beginning_when_saved_employee_removed(self, MockSession, MockAuth):
        # The employee whose id was saved (e9) is gone from the refetched list, so no one is
        # skipped and the sync processes everyone rather than dropping rows.
        session = MockSession.return_value
        MockAuth.return_value.post.return_value = _token_response()
        _wire(
            session,
            [
                _response(_page([{"id": "e1"}, {"id": "e2"}])),
                _response(_page([{"name": "department", "value": "eng"}])),
                _response(_page([{"name": "department", "value": "sales"}])),
            ],
        )

        manager = _make_manager(CultureAmpResumeConfig(last_processed_employee_id="e9"))
        rows = _rows(_source("employee_demographics", manager))

        assert [r["_employee_id"] for r in rows] == ["e1", "e2"]


class TestCultureAmpSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(AUTH_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, MockSession, MockAuth, endpoint):
        config = CULTURE_AMP_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Incremental streams defer the watermark (ordering undocumented).
        expected_sort = "desc" if config.incremental_fields else "asc"
        assert response.sort_mode == expected_sort
