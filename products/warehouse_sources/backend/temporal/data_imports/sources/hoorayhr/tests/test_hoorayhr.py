import json
from typing import Any

import time_machine
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.hoorayhr import (
    hoorayhr_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.settings import HOORAYHR_BASE_URL

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the hoorayhr module.
HOORAYHR_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.hoorayhr.make_tracked_session"
)


def _response(body: Any, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's URL + auth headers at prepare time."""
    session.headers = {}
    seen: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        prepared = mock.MagicMock()
        prepared.headers = {}
        if request.auth is not None:
            request.auth(prepared)
        seen.append({"url": request.url, "params": request.params, "auth_headers": dict(prepared.headers)})
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return seen


def _source(endpoint: str):
    return hoorayhr_source("pk_test_key", endpoint, team_id=1, job_id="j")


def _batches(source_response) -> list[list[dict[str, Any]]]:
    return [list(page) for page in source_response.items()]


class TestHoorayHRTransport:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_time_off_yields_single_batch_with_bearer_auth(self, MockSession) -> None:
        session = MockSession.return_value
        seen = _wire(session, [_response([{"id": 1}, {"id": 2}])])

        batches = _batches(_source("time_off"))

        assert batches == [[{"id": 1}, {"id": 2}]]
        # No pagination anywhere on HoorayHR's API — exactly one request per endpoint.
        assert session.send.call_count == 1
        assert seen[0]["url"] == f"{HOORAYHR_BASE_URL}/time-off"
        assert seen[0]["auth_headers"]["Authorization"] == "Bearer pk_test_key"

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_public_holidays_fetches_each_year_and_merges_policy_duplicates(self, MockSession) -> None:
        session = MockSession.return_value
        seen = _wire(
            session,
            [
                _response([]),
                _response(
                    [
                        {"id": 7, "name": "New Year", "date": "2026-01-01", "userIds": [1, 2]},
                        {"id": 7, "name": "New Year", "date": "2026-01-01", "userIds": [2, 3]},
                        {"id": 8, "name": "Kings Day", "date": "2026-04-27", "userIds": [1]},
                    ]
                ),
                _response([{"id": 7, "name": "New Year", "date": "2027-01-01", "userIds": [1]}]),
            ],
        )

        batches = _batches(_source("public_holidays"))

        assert batches == [
            [
                {"id": 7, "name": "New Year", "date": "2026-01-01", "userIds": [1, 2, 3]},
                {"id": 8, "name": "Kings Day", "date": "2026-04-27", "userIds": [1]},
            ],
            [{"id": 7, "name": "New Year", "date": "2027-01-01", "userIds": [1]}],
        ]
        assert [s["params"] for s in seen] == [
            {"date[$gte]": "2025-01-01", "date[$lte]": "2025-12-31"},
            {"date[$gte]": "2026-01-01", "date[$lte]": "2026-12-31"},
            {"date[$gte]": "2027-01-01", "date[$lte]": "2027-12-31"},
        ]
        assert all(s["url"] == f"{HOORAYHR_BASE_URL}/public-holidays" for s in seen)
        assert seen[0]["auth_headers"]["Authorization"] == "Bearer pk_test_key"


class TestValidateCredentials:
    @mock.patch(HOORAYHR_SESSION_PATCH)
    def test_connection_error_returns_false(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("pk_k") is False
