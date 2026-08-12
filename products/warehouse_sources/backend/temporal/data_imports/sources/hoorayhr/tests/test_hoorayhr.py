import json
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.hoorayhr import (
    hoorayhr_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hoorayhr.settings import (
    ENDPOINTS,
    HOORAYHR_BASE_URL,
    HOORAYHR_ENDPOINTS,
)

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
        seen.append({"url": request.url, "auth_headers": dict(prepared.headers)})
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


class TestSourceResponseConfig:
    def test_all_endpoints_buildable_with_declared_keys(self) -> None:
        for endpoint in ENDPOINTS:
            response = _source(endpoint)
            assert response.name == endpoint
            assert response.primary_keys == HOORAYHR_ENDPOINTS[endpoint].primary_keys

    def test_partitioning_uses_stable_creation_field(self) -> None:
        users = _source("users")
        assert users.partition_mode == "datetime"
        assert users.partition_format == "month"
        assert users.partition_keys == ["createdAt"]

    def test_teams_information_is_unpartitioned_and_keyed_by_team_id(self) -> None:
        teams = _source("teams_information")
        assert teams.primary_keys == ["teamId"]
        assert teams.partition_mode is None
        assert teams.partition_keys is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status, expected",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @mock.patch(HOORAYHR_SESSION_PATCH)
    def test_status_mapping(self, mock_session: mock.MagicMock, status: int, expected: bool) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("pk_k") is expected

    @mock.patch(HOORAYHR_SESSION_PATCH)
    def test_connection_error_returns_false(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("pk_k") is False

    @mock.patch(HOORAYHR_SESSION_PATCH)
    def test_probes_leave_types_with_bearer_header(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("pk_k")

        call = mock_session.return_value.get.call_args
        called_url = call.args[0] if call.args else call.kwargs["url"]
        assert called_url == f"{HOORAYHR_BASE_URL}/leave-types"
        assert call.kwargs["headers"]["Authorization"] == "Bearer pk_k"
        # The key must be registered for redaction in tracked telemetry.
        assert mock_session.call_args.kwargs["redact_values"] == ("pk_k",)
