import json
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.my_hours import my_hours
from products.warehouse_sources.backend.temporal.data_imports.sources.my_hours.my_hours import (
    MY_HOURS_BASE_URL,
    MyHoursApiKeyAuth,
    check_access,
    my_hours_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.my_hours.settings import (
    ENDPOINTS,
    MY_HOURS_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# Client retry attempts default; lowered to 1 so a retryable response surfaces at once (no backoff sleep).
RETRY_ATTEMPTS_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.DEFAULT_RETRY_ATTEMPTS"
)


def _response(body: Any, *, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = f"{MY_HOURS_BASE_URL}/Clients"
    if body is not None:
        resp._content = json.dumps(body).encode()
    return resp


def _wire(responses: list[Response]) -> tuple[requests.Session, list[Any]]:
    """Real session whose prepare_request runs for real (so auth + URL are built) but whose send is
    canned. Returns the session and a list that captures each PreparedRequest at send time."""
    session = requests.Session()
    sent: list[Any] = []

    def _send(prepared: Any, **_kwargs: Any) -> Response:
        sent.append(prepared)
        return responses[len(sent) - 1]

    session.send = mock.MagicMock(side_effect=_send)  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
    return session, sent


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestSync:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_yields_the_full_array_once(self, mock_session: mock.MagicMock) -> None:
        session, sent = _wire([_response([{"id": 1}, {"id": 2}])])
        mock_session.return_value = session

        rows = _rows(my_hours_source(api_key="mh-key", endpoint="clients", team_id=1, job_id="j"))

        assert rows == [{"id": 1}, {"id": 2}]
        # Unpaginated: exactly one request, no pagination follow-up.
        assert session.send.call_count == 1  # type: ignore[attr-defined]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_array_yields_nothing(self, mock_session: mock.MagicMock) -> None:
        session, _sent = _wire([_response([])])
        mock_session.return_value = session

        assert _rows(my_hours_source(api_key="mh-key", endpoint="clients", team_id=1, job_id="j")) == []

    @parameterized.expand([("clients", "/Clients"), ("projects", "/Projects/getAll"), ("users", "/Users/getAll")])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_request_targets_the_expected_url(self, endpoint: str, path: str, mock_session: mock.MagicMock) -> None:
        session, sent = _wire([_response([])])
        mock_session.return_value = session

        _rows(my_hours_source(api_key="mh-key", endpoint=endpoint, team_id=1, job_id="j"))

        assert sent[0].url == f"{MY_HOURS_BASE_URL}{path}"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_uses_apikey_prefixed_authorization_header(self, mock_session: mock.MagicMock) -> None:
        # My Hours rejects requests that omit the literal `apikey ` prefix, so this is load-bearing.
        session, sent = _wire([_response([])])
        mock_session.return_value = session

        _rows(my_hours_source(api_key="mh-key", endpoint="clients", team_id=1, job_id="j"))

        assert sent[0].headers["Authorization"] == "apikey mh-key"

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(RETRY_ATTEMPTS_PATCH, 1)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_raise_retryable_error(
        self, _name: str, status: int, mock_session: mock.MagicMock
    ) -> None:
        session, _sent = _wire([_response(None, status=status)])
        mock_session.return_value = session

        with pytest.raises(RESTClientRetryableError):
            _rows(my_hours_source(api_key="mh-key", endpoint="clients", team_id=1, job_id="j"))

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(RETRY_ATTEMPTS_PATCH, 1)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_raise_for_status(self, _name: str, status: int, mock_session: mock.MagicMock) -> None:
        session, _sent = _wire([_response({"error": "nope"}, status=status)])
        mock_session.return_value = session

        with pytest.raises(requests.HTTPError):
            _rows(my_hours_source(api_key="mh-key", endpoint="clients", team_id=1, job_id="j"))

    @mock.patch(RETRY_ATTEMPTS_PATCH, 1)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_is_retryable(self, mock_session: mock.MagicMock) -> None:
        # A 200 whose body isn't the expected bare array is treated as transient and reissued.
        session, _sent = _wire([_response({"error": "nope"})])
        mock_session.return_value = session

        with pytest.raises(RESTClientRetryableError):
            _rows(my_hours_source(api_key="mh-key", endpoint="clients", team_id=1, job_id="j"))


class TestAuth:
    def test_sets_apikey_prefixed_header(self) -> None:
        request = requests.Request("GET", MY_HOURS_BASE_URL).prepare()
        MyHoursApiKeyAuth("mh-key")(request)
        assert request.headers["Authorization"] == "apikey mh-key"

    def test_declares_raw_key_as_secret_for_redaction(self) -> None:
        assert MyHoursApiKeyAuth("mh-key").secret_values() == ("mh-key",)


class TestCheckAccess:
    def _patch_session(self, monkeypatch: Any, response: Any) -> mock.MagicMock:
        session = mock.MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        monkeypatch.setattr(my_hours, "make_tracked_session", lambda **kwargs: session)
        return session

    @parameterized.expand(
        [
            ("reachable", 200, True, 200, None),
            ("unauthorized", 401, False, 401, None),
            ("forbidden", 403, False, 403, None),
            ("server_error", 500, False, 500, "My Hours returned HTTP 500"),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, ok: bool, expected_status: int, expected_message: str | None
    ) -> None:
        response = mock.MagicMock()
        response.status_code = status
        response.ok = ok
        with pytest.MonkeyPatch().context() as mp:
            self._patch_session(mp, response)
            assert check_access("mh-key") == (expected_status, expected_message)

    def test_connection_error_maps_to_zero(self, monkeypatch: Any) -> None:
        self._patch_session(monkeypatch, requests.ConnectionError("boom"))
        status, message = check_access("mh-key")
        assert status == 0
        assert message is not None and "boom" in message

    def test_probe_targets_clients_endpoint(self, monkeypatch: Any) -> None:
        response = mock.MagicMock(status_code=200, ok=True)
        session = self._patch_session(monkeypatch, response)
        check_access("mh-key")
        assert session.get.call_args.args[0] == f"{MY_HOURS_BASE_URL}/Clients"


class TestMyHoursSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, mock_session: mock.MagicMock) -> None:
        mock_session.return_value = mock.MagicMock()
        response = my_hours_source(api_key="mh-key", endpoint=endpoint, team_id=1, job_id="j")
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # The list endpoints carry no stable timestamp, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in MY_HOURS_ENDPOINTS.values())
        assert set(MY_HOURS_ENDPOINTS) == set(ENDPOINTS)
