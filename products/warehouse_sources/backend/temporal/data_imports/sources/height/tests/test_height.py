import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import PreparedRequest, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.height.height import (
    HeightAPIKeyAuth,
    height_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.height.settings import ENDPOINTS, HEIGHT_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the height module.
HEIGHT_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.height.height.make_tracked_session"
)


def _response(body: Any) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[str]:
    """Wire a mock session; capture each request's URL AT SEND TIME.

    The request object is mutated in place, so snapshot the URL when each request is prepared.
    """
    session.headers = {}
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        url_snapshots.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return url_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestHeightAuth:
    def test_authorization_header_uses_api_key_scheme(self) -> None:
        auth = HeightAPIKeyAuth("secret_abc")
        request = PreparedRequest()
        request.prepare(method="GET", url="https://api.height.app/users")
        auth(request)
        # Height's scheme is the literal word `api-key` followed by the secret, not a Bearer token.
        assert request.headers["Authorization"] == "api-key secret_abc"

    def test_redacts_both_composite_and_raw_key(self) -> None:
        # Both the header value and the raw key on its own are scrubbed from logged errors.
        auth = HeightAPIKeyAuth("secret_abc")
        assert set(auth.secret_values()) == {"api-key secret_abc", "secret_abc"}


class TestHeightSourceRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_yields_rows_from_list_key(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"list": [{"id": "a"}, {"id": "b"}]})])

        rows = _rows(height_source(api_key="secret_key", endpoint="users", team_id=1, job_id="j"))
        assert rows == [{"id": "a"}, {"id": "b"}]
        # Height list endpoints are single-shot; exactly one request pulls the whole collection.
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_list_yields_nothing(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"list": []})])

        rows = _rows(height_source(api_key="secret_key", endpoint="users", team_id=1, job_id="j"))
        assert rows == []

    @parameterized.expand([(e,) for e in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_every_endpoint_targets_its_path(self, endpoint: str, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        urls = _wire(session, [_response({"list": []})])

        _rows(height_source(api_key="secret_key", endpoint=endpoint, team_id=1, job_id="j"))
        assert urls[0] == f"https://api.height.app{HEIGHT_ENDPOINTS[endpoint].path}"

    @parameterized.expand(
        [
            ("bare_array", [{"id": 1}]),
            ("missing_list_key", {"data": []}),
            ("null_body", None),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unexpected_payload_fails_loud(self, _name: str, body: Any, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response(body)])

        # A 200 body without a `list` key means the response shape changed — fail loud, not 0 rows.
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(height_source(api_key="secret_key", endpoint="users", team_id=1, job_id="j"))


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "Invalid Height API key"),
            (403, False, "Invalid Height API key"),
            (500, False, "Height returned HTTP 500"),
        ]
    )
    @mock.patch(HEIGHT_SESSION_PATCH)
    def test_status_mapping(
        self,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_make_session: mock.MagicMock,
    ) -> None:
        mock_make_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("secret_key") == (expected_valid, expected_message)

    @mock.patch(HEIGHT_SESSION_PATCH)
    def test_connection_error_is_not_validated(self, mock_make_session: mock.MagicMock) -> None:
        mock_make_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("secret_key") == (False, "Could not validate Height API key")


class TestHeightSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, _MockSession: mock.MagicMock) -> None:
        response = height_source(api_key="secret_key", endpoint=endpoint, team_id=1, job_id="j")
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in HEIGHT_ENDPOINTS.values())
        assert set(HEIGHT_ENDPOINTS) == set(ENDPOINTS)
